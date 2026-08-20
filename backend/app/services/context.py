"""Low-cost context collection. Screenshots and clipboard are opt-in, never continuous."""

from __future__ import annotations

import platform
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class ContextSnapshot:
    os: str
    active_window: str | None
    process_count: int
    clipboard: str | None = None


class ContextCollector:
    def collect(self, allow_clipboard: bool = False) -> ContextSnapshot:
        # Active-window integrations are platform-specific; omission is safe and intentional.
        clipboard = None
        if allow_clipboard:
            try:
                import pyperclip

                clipboard = pyperclip.paste()[:1000]
            except Exception:
                clipboard = None
        return ContextSnapshot(
            os=f"{platform.system()} {platform.release()}",
            active_window=None,
            process_count=len(psutil.pids()),
            clipboard=clipboard,
        )
