"""On-demand vision adapter; screenshot capture is explicit per request."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisionResult:
    available: bool
    detail: str
    text: str | None = None


class VisionService:
    async def analyze_current_screen(self, user_authorized: bool, prompt: str) -> VisionResult:
        if not user_authorized:
            return VisionResult(False, "Screenshot capture requires explicit user authorization")
        # Capture/model packages are deliberately optional to keep the baseline runtime usable.
        try:
            import pyautogui  # type: ignore[import-not-found]

            screenshot = pyautogui.screenshot()
            # The image is intentionally not persisted. Provider hookup remains a settings-gated extension.
            return VisionResult(
                False,
                f"Screenshot captured in memory ({screenshot.width}×{screenshot.height}); no Vision model configured",
            )
        except Exception as exc:
            return VisionResult(False, f"Vision unavailable: {exc.__class__.__name__}")
