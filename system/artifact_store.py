"""
Artifact Store 鍏冩暟鎹ā鍨嬩笌瀛樺偍绠＄悊

瀹炵幇 NGA-WS11-001: 寤虹珛 Artifact 鍏冩暟鎹ā鍨?
鏀寔澶у璞″紩鐢ㄣ€佷簩娆¤鍙栥€侀厤棰濈鐞嗗拰鐢熷懡鍛ㄦ湡绛栫暐銆?

鍙傝€冩枃妗?
- doc/09-tool-execution-specification.md (I/O 闃茬垎瑙勮寖)
- doc/task/11-ws-artifact-and-evidence-pipeline.md
- doc/13-security-blindspots-and-hardening.md (R16)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ContentType(str, Enum):
    """鍐呭绫诲瀷"""
    TEXT_PLAIN = "text/plain"
    APPLICATION_JSON = "application/json"
    TEXT_CSV = "text/csv"
    APPLICATION_XML = "application/xml"
    TEXT_HTML = "text/html"
    APPLICATION_OCTET_STREAM = "application/octet_stream"


@dataclass
class ArtifactMetadata:
    """
    Artifact 鍏冩暟鎹ā鍨?

    鐢ㄤ簬澶у璞″紩鐢ㄥ拰浜屾璇诲彇銆?
    """

    # === 鏍囪瘑 ===
    artifact_id: str = field(default_factory=lambda: f"artifact_{uuid.uuid4().hex[:16]}")
    content_hash: str = ""  # SHA-256 鍝堝笇

    # === 鍐呭淇℃伅 ===
    content_type: ContentType = ContentType.TEXT_PLAIN
    total_chars: int = 0
    total_lines: int = 0
    file_size_bytes: int = 0

    # === 瀛樺偍淇℃伅 ===
    storage_path: str = ""  # 鐩稿浜?artifact_root 鐨勮矾寰?
    compression: Optional[str] = None  # gzip/bzip2/none

    # === 鏉ユ簮淇℃伅 ===
    source_tool: str = ""  # 浜х敓姝?artifact 鐨勫伐鍏峰悕
    source_call_id: str = ""  # 鍏宠仈鐨勫伐鍏疯皟鐢?ID
    source_trace_id: str = ""  # 鍏宠仈鐨勮拷韪?ID

    # === 璇诲彇鎻愮ず ===
    fetch_hints: list[str] = field(default_factory=list)  # jsonpath/line_range/grep

    # === 鐢熷懡鍛ㄦ湡 ===
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # TTL 杩囨湡鏃堕棿
    access_count: int = 0
    last_accessed_at: Optional[float] = None

    # === 浼樺厛绾?===
    priority: str = "normal"  # low/normal/high/critical

    def to_dict(self) -> Dict[str, Any]:
        """杞崲涓哄瓧鍏?"""
        return {
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "content_type": self.content_type.value,
            "total_chars": self.total_chars,
            "total_lines": self.total_lines,
            "file_size_bytes": self.file_size_bytes,
            "storage_path": self.storage_path,
            "compression": self.compression,
            "source_tool": self.source_tool,
            "source_call_id": self.source_call_id,
            "source_trace_id": self.source_trace_id,
            "fetch_hints": self.fetch_hints,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactMetadata:
        """浠庡瓧鍏稿垱寤?"""
        return cls(
            artifact_id=data.get("artifact_id", ""),
            content_hash=data.get("content_hash", ""),
            content_type=ContentType(data.get("content_type", "text/plain")),
            total_chars=data.get("total_chars", 0),
            total_lines=data.get("total_lines", 0),
            file_size_bytes=data.get("file_size_bytes", 0),
            storage_path=data.get("storage_path", ""),
            compression=data.get("compression"),
            source_tool=data.get("source_tool", ""),
            source_call_id=data.get("source_call_id", ""),
            source_trace_id=data.get("source_trace_id", ""),
            fetch_hints=data.get("fetch_hints", []),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            access_count=data.get("access_count", 0),
            last_accessed_at=data.get("last_accessed_at"),
            priority=data.get("priority", "normal"),
        )


@dataclass
class ArtifactStoreConfig:
    """Artifact Store 閰嶇疆"""

    # 瀛樺偍鏍圭洰褰?
    artifact_root: Path = Path("logs/artifacts")

    # 閰嶉闄愬埗
    max_total_size_mb: int = 1024  # 1GB
    max_single_artifact_mb: int = 100  # 100MB
    max_artifact_count: int = 10000

    # TTL 閰嶇疆
    default_ttl_seconds: int = 86400  # 24 灏忔椂
    low_priority_ttl_seconds: int = 3600  # 1 灏忔椂
    high_priority_ttl_seconds: int = 604800  # 7 澶?

    # 楂樻按浣嶉厤缃?
    high_watermark_ratio: float = 0.9  # 90% 瑙﹀彂娓呯悊
    low_watermark_ratio: float = 0.7  # 70% 娓呯悊鐩爣

    # 鍏冩暟鎹瓨鍌?
    metadata_file: str = "artifacts_metadata.json"


class ArtifactStore:
    """
    Artifact 瀛樺偍绠＄悊鍣?

    鍔熻兘锛?
    1. 鎸佷箙鍖栧ぇ瀵硅薄
    2. 鍏冩暟鎹鐞?
    3. 閰嶉鎺у埗
    4. TTL 杩囨湡娓呯悊
    5. 楂樻按浣嶈儗鍘?
    """

    def __init__(self, config: Optional[ArtifactStoreConfig] = None):
        self.config = config or ArtifactStoreConfig()
        self.config.artifact_root.mkdir(parents=True, exist_ok=True)

        # 鍏冩暟鎹紦瀛?
        self._metadata_cache: Dict[str, ArtifactMetadata] = {}
        self._metrics: Dict[str, int] = {
            "store_attempt": 0,
            "store_success": 0,
            "quota_reject": 0,
            "cleanup_deleted": 0,
            "retrieve_hit": 0,
            "retrieve_miss": 0,
        }
        self._load_metadata()

    def _inc_metric(self, key: str, delta: int = 1) -> None:
        """Increment runtime metric counter."""
        if delta <= 0:
            return
        self._metrics[key] = self._metrics.get(key, 0) + delta

    def _load_metadata(self) -> None:
        """鍔犺浇鍏冩暟鎹?"""
        metadata_path = self.config.artifact_root / self.config.metadata_file

        if not metadata_path.exists():
            return

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for artifact_id, metadata_dict in data.items():
                self._metadata_cache[artifact_id] = ArtifactMetadata.from_dict(metadata_dict)
        except Exception:
            pass

    def _save_metadata(self) -> None:
        """淇濆瓨鍏冩暟鎹?"""
        metadata_path = self.config.artifact_root / self.config.metadata_file

        data = {
            artifact_id: metadata.to_dict()
            for artifact_id, metadata in self._metadata_cache.items()
        }

        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _compute_hash(self, content: str) -> str:
        """璁＄畻鍐呭鍝堝笇"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_storage_path(self, artifact_id: str, content_type: ContentType) -> Path:
        """鑾峰彇瀛樺偍璺緞"""
        # 鎸夋棩鏈熷垎鐗?
        date_prefix = time.strftime("%Y%m%d")

        # 鎸夊唴瀹圭被鍨嬪垎绫?
        type_dir = content_type.value.replace("/", "_")

        # 瀹屾暣璺緞
        return self.config.artifact_root / date_prefix / type_dir / f"{artifact_id}.dat"

    def get_total_size_mb(self) -> float:
        """鑾峰彇鎬诲瓨鍌ㄥぇ灏忥紙MB锛?"""
        total_bytes = sum(
            metadata.file_size_bytes
            for metadata in self._metadata_cache.values()
        )
        return total_bytes / (1024 * 1024)

    def get_artifact_count(self) -> int:
        """鑾峰彇 artifact 鏁伴噺"""
        return len(self._metadata_cache)

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """
        Get a lightweight runtime metrics snapshot.

        Note:
            Counters are in-memory only and reset after process restart.
        """
        return {
            "artifact_count": self.get_artifact_count(),
            "total_size_mb": self.get_total_size_mb(),
            "store_attempt": self._metrics.get("store_attempt", 0),
            "store_success": self._metrics.get("store_success", 0),
            "quota_reject": self._metrics.get("quota_reject", 0),
            "cleanup_deleted": self._metrics.get("cleanup_deleted", 0),
            "retrieve_hit": self._metrics.get("retrieve_hit", 0),
            "retrieve_miss": self._metrics.get("retrieve_miss", 0),
        }

    def _normalize_priority(self, priority: str) -> str:
        value = str(priority or "normal").strip().lower()
        if value not in {"low", "normal", "high", "critical"}:
            return "normal"
        return value

    def _usage_ratio(self) -> float:
        if self.config.max_total_size_mb <= 0:
            return 1.0
        return self.get_total_size_mb() / float(self.config.max_total_size_mb)

    def check_quota(self, new_size_bytes: int, *, priority: str = "normal") -> tuple[bool, str]:
        """
        检查配额

        Returns:
            (allowed, reason)
        """
        normalized_priority = self._normalize_priority(priority)

        # 检查单个文件大小
        new_size_mb = new_size_bytes / (1024 * 1024)
        if new_size_mb > self.config.max_single_artifact_mb:
            return False, f"Single artifact exceeds limit: {new_size_mb:.2f}MB > {self.config.max_single_artifact_mb}MB"

        # 检查总大小
        current_size_mb = self.get_total_size_mb()
        if current_size_mb + new_size_mb > self.config.max_total_size_mb:
            return False, f"Total size exceeds limit: {current_size_mb + new_size_mb:.2f}MB > {self.config.max_total_size_mb}MB"

        # 检查数量
        if self.get_artifact_count() >= self.config.max_artifact_count:
            return False, f"Artifact count exceeds limit: {self.get_artifact_count()} >= {self.config.max_artifact_count}"

        # 高水位背压：仅拒绝低优先级写入，保留关键路径
        if self.config.max_total_size_mb > 0:
            projected_usage_ratio = (current_size_mb + new_size_mb) / float(self.config.max_total_size_mb)
        else:
            projected_usage_ratio = 1.0

        if projected_usage_ratio >= self.config.high_watermark_ratio and normalized_priority == "low":
            return (
                False,
                "High watermark reached for low-priority write: "
                f"{projected_usage_ratio:.1%} >= {self.config.high_watermark_ratio:.1%}",
            )

        return True, "Quota check passed"

    def store(
        self,
        content: str,
        content_type: ContentType,
        source_tool: str = "",
        source_call_id: str = "",
        source_trace_id: str = "",
        priority: str = "normal",
        ttl_seconds: Optional[int] = None,
    ) -> tuple[bool, str, Optional[ArtifactMetadata]]:
        """
        存储 artifact

        Returns:
            (success, message, metadata)
        """
        self._inc_metric("store_attempt")

        # 计算大小
        content_bytes = content.encode("utf-8")
        size_bytes = len(content_bytes)
        normalized_priority = self._normalize_priority(priority)

        # 写入前先回收过期对象，避免无意义拒绝
        self.cleanup_expired()

        # 已达高水位时，先尝试降到低水位
        if self._usage_ratio() >= self.config.high_watermark_ratio:
            self.cleanup_to_watermark()

        # 检查配额
        allowed, reason = self.check_quota(size_bytes, priority=normalized_priority)
        if not allowed and (
            "Total size exceeds limit" in reason
            or "Artifact count exceeds limit" in reason
            or "High watermark" in reason
        ):
            # 再尝试一次回收，避免“可回收但直接拒绝”
            self.cleanup_to_watermark()
            allowed, reason = self.check_quota(size_bytes, priority=normalized_priority)

        if not allowed:
            self._inc_metric("quota_reject")
            return False, reason, None

        # 创建元数据
        metadata = ArtifactMetadata(
            content_hash=self._compute_hash(content),
            content_type=content_type,
            total_chars=len(content),
            total_lines=content.count("\n") + 1,
            file_size_bytes=size_bytes,
            source_tool=source_tool,
            source_call_id=source_call_id,
            source_trace_id=source_trace_id,
            priority=normalized_priority,
        )

        # 设置 TTL
        if ttl_seconds is None:
            if normalized_priority == "low":
                ttl_seconds = self.config.low_priority_ttl_seconds
            elif normalized_priority in ("high", "critical"):
                ttl_seconds = self.config.high_priority_ttl_seconds
            else:
                ttl_seconds = self.config.default_ttl_seconds

        metadata.expires_at = metadata.created_at + ttl_seconds

        # 生成存储路径
        storage_path = self._get_storage_path(metadata.artifact_id, content_type)
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        metadata.storage_path = str(storage_path.relative_to(self.config.artifact_root))

        # 写入文件
        try:
            with open(storage_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return False, f"Failed to write artifact: {e}", None

        # 保存元数据
        self._metadata_cache[metadata.artifact_id] = metadata
        self._save_metadata()
        self._inc_metric("store_success")

        return True, f"Artifact stored: {metadata.artifact_id}", metadata

    def retrieve(self, artifact_id: str) -> tuple[bool, str, Optional[str]]:
        """
        璇诲彇 artifact

        Returns:
            (success, message, content)
        """
        # 鏌ユ壘鍏冩暟鎹?
        metadata = self._metadata_cache.get(artifact_id)
        if not metadata:
            self._inc_metric("retrieve_miss")
            return False, f"Artifact not found: {artifact_id}", None

        # 妫€鏌ヨ繃鏈?
        if metadata.expires_at and time.time() > metadata.expires_at:
            self._inc_metric("retrieve_miss")
            return False, f"Artifact expired: {artifact_id}", None

        # 璇诲彇鏂囦欢
        storage_path = self.config.artifact_root / metadata.storage_path

        if not storage_path.exists():
            self._inc_metric("retrieve_miss")
            return False, f"Artifact file missing: {artifact_id}", None

        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._inc_metric("retrieve_miss")
            return False, f"Failed to read artifact: {e}", None

        # 鏇存柊璁块棶缁熻
        metadata.access_count += 1
        metadata.last_accessed_at = time.time()
        self._save_metadata()
        self._inc_metric("retrieve_hit")

        return True, f"Artifact retrieved: {artifact_id}", content

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """鑾峰彇鍏冩暟鎹?"""
        return self._metadata_cache.get(artifact_id)

    def delete(self, artifact_id: str) -> tuple[bool, str]:
        """鍒犻櫎 artifact"""
        metadata = self._metadata_cache.get(artifact_id)
        if not metadata:
            return False, f"Artifact not found: {artifact_id}"

        # 鍒犻櫎鏂囦欢
        storage_path = self.config.artifact_root / metadata.storage_path
        if storage_path.exists():
            try:
                storage_path.unlink()
            except Exception:
                pass

        # 鍒犻櫎鍏冩暟鎹?
        del self._metadata_cache[artifact_id]
        self._save_metadata()

        return True, f"Artifact deleted: {artifact_id}"

    def cleanup_expired(self) -> tuple[int, int]:
        """
        娓呯悊杩囨湡 artifact

        Returns:
            (deleted_count, freed_bytes)
        """
        now = time.time()
        deleted_count = 0
        freed_bytes = 0

        expired_ids = [
            artifact_id
            for artifact_id, metadata in self._metadata_cache.items()
            if metadata.expires_at and now > metadata.expires_at
        ]

        for artifact_id in expired_ids:
            metadata = self._metadata_cache[artifact_id]
            freed_bytes += metadata.file_size_bytes
            self.delete(artifact_id)
            deleted_count += 1

        self._inc_metric("cleanup_deleted", deleted_count)
        return deleted_count, freed_bytes

    def cleanup_to_watermark(self) -> tuple[int, int]:
        """
        娓呯悊鍒颁綆姘翠綅

        Returns:
            (deleted_count, freed_bytes)
        """
        current_size_mb = self.get_total_size_mb()
        target_size_mb = self.config.max_total_size_mb * self.config.low_watermark_ratio

        if current_size_mb <= target_size_mb:
            return 0, 0

        # 鎸変紭鍏堢骇鍜岃闂椂闂存帓搴忥紙浣庝紭鍏堢骇銆佹棫璁块棶浼樺厛鍒犻櫎锛?
        priority_order = {"low": 0, "normal": 1, "high": 2, "critical": 3}

        sorted_artifacts = sorted(
            self._metadata_cache.items(),
            key=lambda x: (
                priority_order.get(x[1].priority, 1),
                x[1].last_accessed_at or x[1].created_at,
            ),
        )

        deleted_count = 0
        freed_bytes = 0

        for artifact_id, metadata in sorted_artifacts:
            if current_size_mb <= target_size_mb:
                break

            freed_bytes += metadata.file_size_bytes
            current_size_mb -= metadata.file_size_bytes / (1024 * 1024)
            self.delete(artifact_id)
            deleted_count += 1

        self._inc_metric("cleanup_deleted", deleted_count)
        return deleted_count, freed_bytes


# 鍏ㄥ眬鍗曚緥
_artifact_store: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    """鑾峰彇鍏ㄥ眬 Artifact Store 瀹炰緥"""
    global _artifact_store
    if _artifact_store is None:
        _artifact_store = ArtifactStore()
    return _artifact_store


# 瀵煎嚭鍏叡鎺ュ彛
__all__ = [
    "ContentType",
    "ArtifactMetadata",
    "ArtifactStoreConfig",
    "ArtifactStore",
    "get_artifact_store",
]

