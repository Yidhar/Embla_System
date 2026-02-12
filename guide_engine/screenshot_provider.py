from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .models import get_guide_engine_settings


@dataclass(slots=True)
class ScreenshotResult:
    data_url: str
    width: int
    height: int
    monitor_index: int


class ScreenshotProvider:
    def capture_data_url(self, monitor_index: int | None = None) -> ScreenshotResult:
        import mss
        import mss.tools

        settings = get_guide_engine_settings()
        use_monitor_index = monitor_index or settings.screenshot_monitor_index

        with mss.mss() as sct:
            monitors: list[dict[str, Any]] = list(sct.monitors)
            if use_monitor_index < 1 or use_monitor_index >= len(monitors):
                use_monitor_index = 1
            monitor = monitors[use_monitor_index]
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            encoded = base64.b64encode(png_bytes).decode("ascii")
            data_url = f"data:image/png;base64,{encoded}"
            return ScreenshotResult(
                data_url=data_url,
                width=int(shot.width),
                height=int(shot.height),
                monitor_index=use_monitor_index,
            )


_provider: ScreenshotProvider | None = None


def get_screenshot_provider() -> ScreenshotProvider:
    global _provider
    if _provider is None:
        _provider = ScreenshotProvider()
    return _provider
