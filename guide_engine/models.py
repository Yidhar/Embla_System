from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from system.config import config


class GuideRequest(BaseModel):
    content: str = Field(default="", description="用户问题")
    game_id: str | None = Field(default=None, description="游戏ID（可选）")
    server_id: str | None = Field(default=None, description="服务器ID")
    images: list[str] = Field(default_factory=list, description="图片base64列表")
    auto_screenshot: bool = Field(default=False, description="是否自动截图")
    history: list[dict[str, Any]] = Field(default_factory=list, description="可选历史消息")


class GuideReference(BaseModel):
    type: str = "document"
    title: str = ""
    source: str = ""
    score: float | None = None


class GuideResponse(BaseModel):
    content: str
    query_mode: str = "full"
    references: list[GuideReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class GuideEngineSettings:
    enabled: bool = True
    chroma_persist_dir: str = "./data/chroma"
    embedding_api_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_api_model: str | None = None
    vision_api_base_url: str | None = None
    vision_api_key: str | None = None
    vision_api_model: str | None = None
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "your_password"
    prompt_dir: str = "guide_engine/game_prompts"
    screenshot_monitor_index: int = 1
    auto_screenshot_on_guide: bool = True

    @classmethod
    def from_runtime(cls) -> "GuideEngineSettings":
        root = config.system.base_dir
        ge = config.guide_engine

        prompt_dir = ge.prompt_dir
        chroma_persist_dir = ge.chroma_persist_dir

        if prompt_dir.startswith("./"):
            prompt_dir = str((root / prompt_dir[2:]).resolve())
        if chroma_persist_dir.startswith("./"):
            chroma_persist_dir = str((root / chroma_persist_dir[2:]).resolve())

        return cls(
            enabled=ge.enabled,
            chroma_persist_dir=chroma_persist_dir,
            embedding_api_base_url=ge.embedding_api_base_url or config.api.base_url,
            embedding_api_key=ge.embedding_api_key or config.api.api_key,
            embedding_api_model=ge.embedding_api_model or "text-embedding-3-small",
            vision_api_base_url=ge.vision_api_base_url or config.api.base_url,
            vision_api_key=ge.vision_api_key or config.api.api_key,
            vision_api_model=ge.vision_api_model or config.api.model,
            neo4j_uri=ge.neo4j_uri,
            neo4j_user=ge.neo4j_user,
            neo4j_password=ge.neo4j_password,
            prompt_dir=prompt_dir,
            screenshot_monitor_index=ge.screenshot_monitor_index,
            auto_screenshot_on_guide=ge.auto_screenshot_on_guide,
        )


_settings: GuideEngineSettings | None = None


def get_guide_engine_settings() -> GuideEngineSettings:
    global _settings
    if _settings is None:
        _settings = GuideEngineSettings.from_runtime()
    return _settings
