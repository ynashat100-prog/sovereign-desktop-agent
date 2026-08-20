"""Deterministic local-first task classification and provider selection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.providers.base import ModelProvider

_SIMPLE_COMMANDS = (
    r"\b(?:what time|time is|read file|find file|search file|create folder)\b",
    r"\bopen\s+(?:app|file|folder)\b",
    r"\b(?:delete file|delete folder|installed apps|active processes|screenshot|brightness|volume up|volume down|read clipboard)\b",
    r"\b(?:sound|display|bluetooth|network|privacy)\s+settings\b",
    r"\b(?:search the web for|search web for|web search)\b",
    r"(?:ما الوقت|اقرأ ملف|ابحث عن ملف|أنشئ مجلد|انشئ مجلد|افتح\s+(?:برنامج|الملف|المجلد)|احذف\s+(?:ملف|مجلد)|التطبيقات المثبتة|البرامج المثبتة|البرامج النشطة|لقطة شاشة|صورة للشاشة|السطوع|ارفع الصوت|اخفض الصوت|اكتم الصوت|اقرأ الحافظة|ابحث على الإنترنت)",
)
_COMPLEX_SIGNALS = ("analyze", "build", "fix", "project", "multiple", "حلل", "ابن", "أصلح", "مشروع")


@dataclass(frozen=True)
class Route:
    mode: str
    provider_id: str | None
    reason: str


class SmartRouter:
    def is_simple(self, text: str) -> bool:
        normalized = text.casefold().strip()
        return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _SIMPLE_COMMANDS) and not any(
            re.search(rf"(?<!\w){re.escape(signal)}(?!\w)", normalized, re.IGNORECASE)
            for signal in _COMPLEX_SIGNALS
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
