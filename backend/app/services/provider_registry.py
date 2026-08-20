"""Custom OpenAI-compatible providers with non-secret metadata on disk and keys in OS credential storage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import keyring

_SERVICE_NAME = "SovereignDesktopAgent"


@dataclass
class ProviderRecord:
    id: str
    name: str
    base_url: str
    model: str
    fallback_enabled: bool = False
    preset: str | None = None

    @property
    def masked_key(self) -> str | None:
        try:
            secret = keyring.get_password(_SERVICE_NAME, self.id)
        except keyring.errors.KeyringError:
            return None
        if not secret:
            return None
        return f"••••••••••••{secret[-4:]}" if len(secret) >= 4 else "••••"


class ProviderRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[ProviderRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [ProviderRecord(**item) for item in raw]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _save(self, records: list[ProviderRecord]) -> None:
        # The serialized file deliberately excludes the API key.
        self.path.write_text(
            json.dumps([asdict(record) for record in records], indent=2), encoding="utf-8"
        )

    def list(self) -> list[dict]:
        return [asdict(record) | {"api_key_masked": record.masked_key} for record in self._load()]

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
        records = [item for item in records if item.id != provider_id] + [record]
        self._save(records)
        if api_key:
            try:
                keyring.set_password(_SERVICE_NAME, provider_id, api_key)
            except keyring.errors.KeyringError as exc:
                raise RuntimeError("Secure credential storage is unavailable") from exc
        return asdict(record) | {"api_key_masked": record.masked_key}

    def delete(self, provider_id: str) -> bool:
        records = self._load()
        new_records = [item for item in records if item.id != provider_id]
        if len(new_records) == len(records):
            return False
        self._save(new_records)
        try:
            keyring.delete_password(_SERVICE_NAME, provider_id)
        except keyring.errors.PasswordDeleteError:
            pass
        return True

    async def test(self, provider_id: str) -> dict:
        record = next((item for item in self._load() if item.id == provider_id), None)
        if not record:
            raise KeyError("Provider not found")
        try:
            api_key = keyring.get_password(_SERVICE_NAME, provider_id)
        except keyring.errors.KeyringError as exc:
            raise RuntimeError("Secure credential storage is unavailable") from exc
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
            return keyring.get_password(_SERVICE_NAME, provider_id)
        except keyring.errors.KeyringError:
            return None
