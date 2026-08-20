"""Deterministic local-first task classification and provider selection."""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.base import ModelProvider

_SIMPLE_PATTERNS = (
    "what time",
    "time is",
    "open ",
    "read file",
    "find file",
    "search file",
    "create folder",
    "ما الوقت",
    "افتح ",
    "اقرأ ملف",
    "ابحث عن ملف",
    "أنشئ مجلد",
)
_COMPLEX_SIGNALS = ("analyze", "build", "fix", "project", "multiple", "حلل", "ابن", "أصلح", "مشروع")


@dataclass(frozen=True)
class Route:
    mode: str
    provider_id: str | None
    reason: str


class SmartRouter:
    def is_simple(self, text: str) -> bool:
        normalized = text.lower().strip()
        return any(pattern in normalized for pattern in _SIMPLE_PATTERNS) and not any(
            signal in normalized for signal in _COMPLEX_SIGNALS
        )

    async def route(
        self,
        text: str,
        providers: list[ModelProvider],
        preferred_provider: str | None = None,
        allow_cloud: bool = False,
    ) -> Route:
        if self.is_simple(text):
            return Route(
                mode="fast",
                provider_id=None,
                reason="Matched a safe, deterministic command pattern",
            )

        statuses = {provider.id: await provider.status() for provider in providers}
        if (
            preferred_provider
            and statuses.get(preferred_provider, None)
            and statuses[preferred_provider].available
            and (preferred_provider == "ollama" or allow_cloud)
        ):
            return Route(mode="planner", provider_id=preferred_provider, reason="Selected by user")
        if statuses.get("ollama") and statuses["ollama"].available:
            return Route(
                mode="planner",
                provider_id="ollama",
                reason="Local model available; local-first selected",
            )
        return Route(
            mode="demo",
            provider_id=None,
            reason="No local model available and no cloud provider was explicitly selected",
        )
