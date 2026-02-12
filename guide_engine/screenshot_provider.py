from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import get_guide_engine_settings


@dataclass(slots=True)
class ScreenshotResult:
    data_url: str
    width: int
    height: int
    monitor_index: int
    source: str = "screen"


class ScreenshotProvider:
    TEST_IMAGE_ENV: str = "TEST_PIC_PATH"

    def capture_data_url(self, monitor_index: int | None = None) -> ScreenshotResult:
        test_image_path = self._resolve_test_image_path()
        if test_image_path is not None:
            return ScreenshotResult(
                data_url=self._file_to_data_url(test_image_path),
                width=0,
                height=0,
                monitor_index=0,
                source=f"env:{self.TEST_IMAGE_ENV}",
            )

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
            if png_bytes is None:
                raise RuntimeError("mss 返回空图片数据")
            encoded = base64.b64encode(png_bytes).decode("ascii")
            data_url = f"data:image/png;base64,{encoded}"
            return ScreenshotResult(
                data_url=data_url,
                width=int(shot.width),
                height=int(shot.height),
                monitor_index=use_monitor_index,
                source="screen",
            )

    def _resolve_test_image_path(self) -> Path | None:
        raw_path = os.getenv(self.TEST_IMAGE_ENV, "").strip()
        if not raw_path:
            return None

        test_path = Path(raw_path).expanduser()
        if not test_path.is_absolute():
            test_path = (Path.cwd() / test_path).resolve()
        if not test_path.exists() or not test_path.is_file():
            raise FileNotFoundError(f"{self.TEST_IMAGE_ENV} 文件不存在: {test_path}")
        return test_path

    def _file_to_data_url(self, file_path: Path) -> str:
        mime_type = self._guess_image_mime(file_path)
        image_bytes = file_path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _guess_image_mime(file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        mapping: dict[str, str] = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        mime_type = mapping.get(suffix)
        if mime_type is None:
            raise ValueError(f"不支持的测试图片格式: {file_path.suffix}")
        return mime_type


_provider: ScreenshotProvider | None = None


def get_screenshot_provider() -> ScreenshotProvider:
    global _provider
    if _provider is None:
        _provider = ScreenshotProvider()
    return _provider
