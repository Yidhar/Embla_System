"""
RAG 时效性权重模块

处理游戏攻略的过时问题：
1. 时间衰减：越新的内容权重越高
2. 版本关联：版本更新后相关内容降权
3. 内容类型：不同类型衰减速度不同
4. 显式标记：支持标记过时/废弃内容
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class FreshnessLevel(str, Enum):
    """时效性级别"""
    EVERGREEN = "evergreen"      # 常青内容（基础数据）
    STABLE = "stable"            # 稳定内容（技能效果）
    SEASONAL = "seasonal"        # 季节性内容（版本Meta）
    VOLATILE = "volatile"        # 易变内容（配队推荐）
    EPHEMERAL = "ephemeral"      # 临时内容（活动攻略）


@dataclass
class VersionInfo:
    """版本信息"""
    version: str
    release_date: datetime
    is_major: bool = False


# 不同内容类型的衰减半衰期（天）
HALF_LIFE_DAYS: dict[FreshnessLevel, int] = {
    FreshnessLevel.EVERGREEN: 365 * 2,
    FreshnessLevel.STABLE: 180,
    FreshnessLevel.SEASONAL: 90,
    FreshnessLevel.VOLATILE: 45,
    FreshnessLevel.EPHEMERAL: 14,
}

# 内容类型 -> 时效性级别
CONTENT_TYPE_FRESHNESS: dict[str, FreshnessLevel] = {
    "basic": FreshnessLevel.EVERGREEN,
    "skill": FreshnessLevel.STABLE,
    "talent": FreshnessLevel.STABLE,
    "module": FreshnessLevel.STABLE,
    "building": FreshnessLevel.EVERGREEN,
    "character_guide": FreshnessLevel.VOLATILE,
    "stage_guide": FreshnessLevel.SEASONAL,
    "team_comp": FreshnessLevel.VOLATILE,
    "beginner_guide": FreshnessLevel.STABLE,
    "event_guide": FreshnessLevel.EPHEMERAL,
    "meta_analysis": FreshnessLevel.VOLATILE,
    "guide": FreshnessLevel.SEASONAL,
    "video_transcript": FreshnessLevel.SEASONAL,
}

# 关键词 -> 时效性级别（用于自动检测）
FRESHNESS_KEYWORDS: dict[FreshnessLevel, list[str]] = {
    FreshnessLevel.EPHEMERAL: [
        r"活动", r"限时", r"复刻", r"联动",
        r"\d+\.\d+版本", r"当期", r"本期",
    ],
    FreshnessLevel.VOLATILE: [
        r"配队", r"阵容", r"T0", r"T1", r"强度榜",
        r"版本答案", r"当前版本", r"最强",
    ],
    FreshnessLevel.SEASONAL: [
        r"攻略", r"打法", r"思路",
    ],
}

# 过时标记关键词
DEPRECATED_PATTERNS: list[str] = [
    r"已过时", r"已废弃", r"不再适用",
    r"版本已更新", r"机制已改",
    r"\[过时\]", r"\[废弃\]", r"\[outdated\]",
]


def _determine_freshness_level(content_type: str, content: str) -> FreshnessLevel:
    """确定内容的时效性级别"""
    for level, patterns in FRESHNESS_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, content):
                return level
    return CONTENT_TYPE_FRESHNESS.get(content_type, FreshnessLevel.SEASONAL)


def _calculate_time_decay(publish_date: datetime, freshness_level: FreshnessLevel) -> float:
    """时间衰减：weight = 2^(-t/half_life)"""
    age_days = (datetime.now() - publish_date).days
    if age_days <= 0:
        return 1.0
    half_life = HALF_LIFE_DAYS[freshness_level]
    return math.pow(2, -age_days / half_life)


def _calculate_version_penalty(content_version: str | None, current_version: str | None) -> float:
    """版本距离惩罚"""
    if not content_version or not current_version:
        return 1.0
    try:
        content_parts = [int(x) for x in content_version.split(".")[:2]]
        current_parts = [int(x) for x in current_version.split(".")[:2]]
        major_diff = abs(current_parts[0] - content_parts[0])
        minor_diff = (
            abs(current_parts[1] - content_parts[1])
            if len(content_parts) > 1 and len(current_parts) > 1
            else 0
        )
        distance = major_diff * 10 + minor_diff
        if distance == 0:
            return 1.0
        if distance <= 2:
            return 0.95
        if distance <= 5:
            return 0.8
        if distance <= 10:
            return 0.6
        return 0.4
    except (ValueError, IndexError):
        return 1.0


def calculate_freshness_weight(
    publish_date: datetime | None,
    content_type: str,
    content: str = "",
    game_version: str | None = None,
    current_version: str | None = None,
    is_deprecated: bool = False,
) -> float:
    """计算单条内容的时效性权重，返回 0.1~1.0"""
    if is_deprecated:
        return 0.1
    if publish_date is None:
        return 0.7

    level = _determine_freshness_level(content_type, content)
    time_w = _calculate_time_decay(publish_date, level)
    ver_w = _calculate_version_penalty(game_version, current_version)
    return max(0.1, min(1.0, time_w * ver_w))


def is_deprecated(content: str, metadata: dict[str, Any] | None = None) -> bool:
    """检查内容是否已过时"""
    if metadata and metadata.get("is_deprecated"):
        return True
    for pattern in DEPRECATED_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False


def apply_freshness_weight(
    docs: list[dict[str, Any]],
    current_version: str | None = None,
) -> list[dict[str, Any]]:
    """对搜索结果按时效性重新加权排序，无时效字段时回退默认权重"""
    adjusted: list[dict[str, Any]] = []
    for doc in docs:
        metadata = doc.get("metadata", {})

        publish_date: datetime | None = None
        date_str = metadata.get("publish_date")
        if date_str:
            try:
                publish_date = datetime.fromisoformat(date_str)
            except (ValueError, TypeError):
                pass

        weight = calculate_freshness_weight(
            publish_date=publish_date,
            content_type=doc.get("doc_type", ""),
            content=doc.get("content", ""),
            game_version=metadata.get("game_version"),
            current_version=current_version,
            is_deprecated=metadata.get("is_deprecated", False),
        )

        original_score = doc.get("score", 1.0)
        entry = doc.copy()
        entry["original_score"] = original_score
        entry["freshness_weight"] = weight
        entry["score"] = original_score * weight
        adjusted.append(entry)

    adjusted.sort(key=lambda x: x["score"], reverse=True)
    return adjusted
