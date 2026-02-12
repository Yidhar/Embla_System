from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import get_guide_engine_settings


DEFAULT_PROMPT_CONFIG: dict[str, Any] = {
    "system_prompt": (
        "你是一个专业的游戏攻略助手，专门帮助玩家解答游戏相关问题。请基于给定上下文进行回答，不确定时明确说明。"
    ),
    "rag_enabled": True,
    "graph_rag_enabled": True,
    "retrieval_config": {"top_k": 5, "score_threshold": 0.5},
    "entity_patterns": {},
}


class PromptManager:
    def __init__(self, prompt_dir: str | None = None) -> None:
        settings = get_guide_engine_settings()
        self.prompt_dir = Path(prompt_dir or settings.prompt_dir)

    def get_prompt_config(self, game_id: str) -> dict[str, Any]:
        config = self._load_from_file(game_id)
        if config:
            return config
        result = dict(DEFAULT_PROMPT_CONFIG)
        result["game_id"] = game_id
        return result

    def _load_from_file(self, game_id: str) -> dict[str, Any] | None:
        candidates = [
            self.prompt_dir / f"{game_id}.yaml",
            self.prompt_dir / f"{self._normalize_game_id(game_id)}.yaml",
        ]
        for file_path in candidates:
            if not file_path.exists():
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                return loaded
        return None

    @staticmethod
    def _normalize_game_id(game_id: str) -> str:
        mapping = {
            "starrail": "honkai-star-rail",
            "honkai_star_rail": "honkai-star-rail",
            "genshin_impact": "genshin-impact",
            "wuthering_waves": "wuthering-waves",
            "zenless_zone_zero": "zenless-zone-zero",
            "punishing_gray_raven": "punishing-gray-raven",
            "uma_musume": "uma-musume",
            "kantai_collection": "kantai-collection",
        }
        return mapping.get(game_id, game_id)
