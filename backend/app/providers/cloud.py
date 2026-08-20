"""Optional cloud providers. They are never selected unless local execution is unavailable or chosen."""

from __future__ import annotations

import httpx

from app.models.schemas import ProviderStatus
from app.providers.base import Generation, ModelProvider


class OpenAICompatibleProvider(ModelProvider):
    def __init__(
        self, *, provider_id: str, name: str, api_key: str | None, base_url: str, model: str
    ):
        self.id = provider_id
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(
                id=self.id,
                name=self.name,
                kind="cloud",
                available=False,
                detail="API key is not configured",
            )
        return ProviderStatus(
            id=self.id,
            name=self.name,
            kind="cloud",
            available=True,
            detail="Configured; contacted only after selection or local fallback",
            models=[self.model],
        )

    async def generate(self, prompt: str, *, system: str = "") -> Generation:
        if not self.api_key:
            raise RuntimeError(f"{self.name} API key is not configured")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You are a helpful desktop assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload
            )
            response.raise_for_status()
            body = response.json()
        text = body["choices"][0]["message"]["content"]
        return Generation(text=text, model=self.model, provider=self.id, local=False)


class MistralProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None, model: str):
        super().__init__(
            provider_id="mistral",
            name="Mistral AI",
            api_key=api_key,
            base_url="https://api.mistral.ai/v1",
            model=model,
        )


class GroqProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None, model: str):
        super().__init__(
            provider_id="groq",
            name="Groq",
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            model=model,
        )


class NvidiaProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str | None, model: str):
        super().__init__(
            provider_id="nvidia",
            name="NVIDIA NIM",
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
            model=model,
        )
