"""Custom OpenAI-compatible providers with metadata on disk and secrets in OS credential storage."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx
import keyring

_SERVICE_NAME = "SovereignDesktopAgent"


class CredentialStore(Protocol):
    def get(self, service: str, username: str) -> str | None: ...

    def set(self, service: str, username: str, password: str) -> None: ...

    def delete(self, service: str, username: str) -> None: ...


class SystemCredentialStore:
    """Select the native Windows backend explicitly so PyInstaller can bundle it reliably."""

    def __init__(self) -> None:
        self.backend = None

    def _backend(self):
        if self.backend is not None:
            return self.backend
        try:
            if sys.platform == "win32":
                # Explicit import prevents PyInstaller from dropping the plugin discovered by keyring.
                from keyring.backends.Windows import WinVaultKeyring

                backend = WinVaultKeyring()
            else:
                backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise RuntimeError("No secure system credential backend is available")
            self.backend = backend
            return backend
        except Exception as exc:
            raise RuntimeError("Secure credential storage is unavailable") from exc

    def get(self, service: str, username: str) -> str | None:
        try:
            return self._backend().get_password(service, username)
        except Exception as exc:
            raise RuntimeError("Secure credential storage is unavailable") from exc

    def set(self, service: str, username: str, password: str) -> None:
        try:
            self._backend().set_password(service, username, password)
        except Exception as exc:
            raise RuntimeError("Secure credential storage is unavailable") from exc

    def delete(self, service: str, username: str) -> None:
        try:
            self._backend().delete_password(service, username)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception as exc:
            raise RuntimeError("Secure credential storage is unavailable") from exc


@dataclass
class ProviderRecord:
    id: str
    name: str
    base_url: str
    model: str
    fallback_enabled: bool = False
    preset: str | None = None


class ProviderRegistry:
    def __init__(self, path: Path, credentials: CredentialStore | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials = credentials or SystemCredentialStore()

    def _load(self) -> list[ProviderRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [ProviderRecord(**item) for item in raw]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _save(self, records: list[ProviderRecord]) -> None:
        try:
            self.path.write_text(
                json.dumps([asdict(record) for record in records], indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise RuntimeError("Application data storage is unavailable") from exc

    def _masked_key(self, record_id: str) -> str | None:
        try:
            secret = self.credentials.get(_SERVICE_NAME, record_id)
        except RuntimeError:
            return None
        if not secret:
            return None
        return f"••••••••••••{secret[-4:]}" if len(secret) >= 4 else "••••"

    def list(self) -> list[dict]:
        return [asdict(record) | {"api_key_masked": self._masked_key(record.id)} for record in self._load()]

    def upsert(
        self,
        *,
        record_id: str | None,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None,
        fallback_enabled: bool,
        preset: str | None = None,
    ) -> dict:
        parsed = httpx.URL(base_url)
        if parsed.scheme != "https":
            raise ValueError("Custom provider Base URL must use HTTPS")
        records = self._load()
        provider_id = record_id or str(uuid4())
        record = ProviderRecord(
            provider_id, name.strip(), base_url.rstrip("/"), model.strip(), fallback_enabled, preset
        )
        # Store the secret first. This prevents a ghost provider record when Credential Manager fails.
        if api_key:
            self.credentials.set(_SERVICE_NAME, provider_id, api_key)
        elif not self.credentials.get(_SERVICE_NAME, provider_id):
            raise ValueError("An API key is required for a new provider")
        records = [item for item in records if item.id != provider_id] + [record]
        self._save(records)
        return asdict(record) | {"api_key_masked": self._masked_key(provider_id)}

    def delete(self, provider_id: str) -> bool:
        records = self._load()
        new_records = [item for item in records if item.id != provider_id]
        if len(new_records) == len(records):
            return False
        self._save(new_records)
        self.credentials.delete(_SERVICE_NAME, provider_id)
        return True

    async def discover_models(self, *, base_url: str, api_key: str) -> list[str]:
        parsed = httpx.URL(base_url)
        if parsed.scheme != "https":
            raise ValueError("Custom provider Base URL must use HTTPS")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}
                )
            if not response.is_success:
                raise ValueError(f"Provider rejected model discovery (HTTP {response.status_code})")
            models = sorted(
                {
                    str(item.get("id")).strip()
                    for item in response.json().get("data", [])
                    if isinstance(item, dict) and item.get("id")
                }
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Unable to reach the provider for model discovery") from exc
        if not models:
            raise ValueError("The provider returned no selectable models")
        return models

    async def test(self, provider_id: str) -> dict:
        record = next((item for item in self._load() if item.id == provider_id), None)
        if not record:
            raise KeyError("Provider not found")
        api_key = self.credentials.get(_SERVICE_NAME, provider_id)
        if not api_key:
            raise ValueError("No securely stored API key for this provider")
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{record.base_url}/models", headers=headers)
        return {"ok": response.is_success, "status_code": response.status_code}

    def provider(self, provider_id: str) -> ProviderRecord | None:
        return next((item for item in self._load() if item.id == provider_id), None)

    def secret(self, provider_id: str) -> str | None:
        try:
            return self.credentials.get(_SERVICE_NAME, provider_id)
        except RuntimeError:
            return None
