"""Ollama local provider with graceful failure behavior."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.models.schemas import ProviderStatus
from app.providers.base import Generation, ModelProvider


class OllamaProvider(ModelProvider):
    id = "ollama"
    name = "Ollama"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def status(self) -> ProviderStatus:
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                response = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                response.raise_for_status()
                models = [item["name"] for item in response.json().get("models", [])]
            detail = "Running" if models else "Running; no models installed"
            return ProviderStatus(
                id=self.id,
                name=self.name,
                kind="local",
                available=True,
                detail=detail,
                models=models,
            )
        except (httpx.HTTPError, OSError) as exc:
            return ProviderStatus(
                id=self.id,
                name=self.name,
                kind="local",
                available=False,
                detail=f"Unavailable: {exc.__class__.__name__}",
            )

    async def pull(self, model: str) -> AsyncIterator[dict]:
        payload = {"name": model, "stream": True}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self.settings.ollama_base_url}/api/pull", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield json.loads(line)

    async def generate(self, prompt: str, *, system: str = "") -> Generation:
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.settings.ollama_base_url}/api/generate", json=payload
            )
            response.raise_for_status()
            body = response.json()
        return Generation(
            text=body.get("response", ""),
            model=body.get("model", self.settings.ollama_model),
            provider=self.id,
            local=True,
        )
