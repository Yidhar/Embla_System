"""
Episodic memory archive/search/reinjection helpers.

NGA-WS19-005:
- local lightweight persistence (JSONL)
- deterministic token hashing sparse vectors + cosine recall
- tool-result archival and reinjection prompt builder
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_FIELD_RE = re.compile(r"^\[([A-Za-z0-9_]+)\]\s*(.*)$")
_NONE_MARKERS = {"", "(none)", "none", "null", "nil", "n/a"}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _looks_like_none(value: str) -> bool:
    return value.strip().lower() in _NONE_MARKERS


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return 0x4E00 <= code <= 0x9FFF


def _tokenize(text: str) -> List[str]:
    lowered = _safe_text(text).lower()
    tokens: List[str] = []
    for piece in _TOKEN_RE.findall(lowered):
        piece = piece.strip()
        if not piece:
            continue

        if any(_is_cjk(ch) for ch in piece):
            chars = [ch for ch in piece if _is_cjk(ch)]
            tokens.extend(chars)
            if len(chars) >= 2:
                tokens.extend(chars[idx] + chars[idx + 1] for idx in range(len(chars) - 1))
            continue

        tokens.append(piece)
        if len(piece) >= 4:
            tokens.extend(piece[idx : idx + 3] for idx in range(len(piece) - 2))

    return tokens


def _hash_bucket(token: str, vector_dims: int) -> Tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    bucket = int.from_bytes(digest[:4], "big", signed=False) % vector_dims
    sign = 1.0 if (digest[4] & 1) == 0 else -1.0
    return bucket, sign


def _build_sparse_vector(text: str, vector_dims: int) -> Dict[int, float]:
    if vector_dims <= 0:
        return {}

    token_counts: Dict[str, int] = {}
    for token in _tokenize(text):
        token_counts[token] = token_counts.get(token, 0) + 1

    if not token_counts:
        return {}

    vector: Dict[int, float] = {}
    for token, count in token_counts.items():
        bucket, sign = _hash_bucket(token, vector_dims)
        weight = 1.0 + math.log(float(count))
        vector[bucket] = vector.get(bucket, 0.0) + sign * weight

    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm <= 1e-12:
        return {}

    for bucket in list(vector.keys()):
        vector[bucket] /= norm
    return vector


def _cosine_sparse(lhs: Dict[int, float], rhs: Dict[int, float]) -> float:
    if not lhs or not rhs:
        return 0.0

    # Iterate on smaller dict for performance.
    if len(lhs) > len(rhs):
        lhs, rhs = rhs, lhs

    return float(sum(value * rhs.get(bucket, 0.0) for bucket, value in lhs.items()))


def _split_fetch_hints(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (_normalize_whitespace(_safe_text(v)) for v in value) if item and not _looks_like_none(item)]

    raw = _normalize_whitespace(_safe_text(value))
    if not raw or _looks_like_none(raw):
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _format_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class EpisodicRecord:
    record_id: str
    session_id: str
    source_tool: str
    narrative_summary: str
    forensic_artifact_ref: str = ""
    fetch_hints: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "source_tool": self.source_tool,
            "narrative_summary": self.narrative_summary,
            "forensic_artifact_ref": self.forensic_artifact_ref,
            "fetch_hints": list(self.fetch_hints),
            "timestamp": float(self.timestamp),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EpisodicRecord":
        fetch_hints = _split_fetch_hints(payload.get("fetch_hints"))
        return cls(
            record_id=_normalize_whitespace(_safe_text(payload.get("record_id"))) or f"ep_{uuid.uuid4().hex[:16]}",
            session_id=_normalize_whitespace(_safe_text(payload.get("session_id"))),
            source_tool=_normalize_whitespace(_safe_text(payload.get("source_tool"))) or "unknown",
            narrative_summary=_normalize_whitespace(_safe_text(payload.get("narrative_summary"))),
            forensic_artifact_ref=_normalize_whitespace(_safe_text(payload.get("forensic_artifact_ref"))),
            fetch_hints=fetch_hints,
            timestamp=float(payload.get("timestamp", time.time())),
        )


@dataclass(frozen=True)
class EpisodicSearchHit:
    record: EpisodicRecord
    score: float
    rank: int


class EpisodicMemoryArchive:
    """Local JSONL archive + deterministic sparse-vector retrieval."""

    def __init__(
        self,
        archive_path: Optional[Path] = None,
        *,
        vector_dims: int = 4096,
        session_boost: float = 0.05,
    ) -> None:
        self.archive_path = Path(archive_path) if archive_path is not None else _default_archive_path()
        self.vector_dims = max(128, int(vector_dims))
        self.session_boost = max(0.0, float(session_boost))
        self._records: List[EpisodicRecord] = []
        self._vectors: List[Dict[int, float]] = []
        self._loaded = False
        self._lock = threading.RLock()

        self.archive_path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return

            self._records = []
            self._vectors = []
            if self.archive_path.exists():
                with self.archive_path.open("r", encoding="utf-8") as handle:
                    for line_no, raw in enumerate(handle, start=1):
                        text = raw.strip()
                        if not text:
                            continue
                        try:
                            payload = json.loads(text)
                            record = EpisodicRecord.from_dict(payload)
                            if not record.narrative_summary:
                                continue
                            self._records.append(record)
                            self._vectors.append(self._vectorize_record(record))
                        except Exception as exc:
                            logger.warning(
                                "[EpisodicMemory] skip malformed archive line %s (%s): %s",
                                line_no,
                                self.archive_path,
                                exc,
                            )
            self._loaded = True

    def _vectorize_record(self, record: EpisodicRecord) -> Dict[int, float]:
        summary = record.narrative_summary
        hints = " ".join(record.fetch_hints)
        text = " ".join(
            [
                summary,
                summary,  # upweight summary
                record.source_tool,
                hints,
                record.forensic_artifact_ref,
            ]
        ).strip()
        return _build_sparse_vector(text, self.vector_dims)

    @staticmethod
    def _extract_from_result_text(result_text: str) -> Tuple[str, str, List[str]]:
        lines = result_text.splitlines()
        scalar_fields: Dict[str, str] = {}
        section_fields: Dict[str, List[str]] = {}
        current_section: Optional[str] = None

        for raw_line in lines:
            stripped = raw_line.strip()
            match = _FIELD_RE.match(stripped)
            if match:
                key = match.group(1).strip().lower()
                value = match.group(2).strip()
                if value:
                    scalar_fields[key] = value
                    current_section = None
                else:
                    current_section = key
                    section_fields.setdefault(key, [])
                continue

            if current_section:
                section_fields.setdefault(current_section, []).append(raw_line.rstrip())

        narrative_summary = _normalize_whitespace("\n".join(section_fields.get("narrative_summary", [])).strip())
        if not narrative_summary:
            narrative_summary = _normalize_whitespace(scalar_fields.get("narrative_summary", ""))
        if not narrative_summary:
            narrative_summary = _truncate_text(_normalize_whitespace(result_text), 420)

        forensic_ref = _normalize_whitespace(
            scalar_fields.get("forensic_artifact_ref") or scalar_fields.get("raw_result_ref") or ""
        )
        if _looks_like_none(forensic_ref):
            forensic_ref = ""

        hints = _split_fetch_hints(scalar_fields.get("fetch_hints", ""))
        return narrative_summary, forensic_ref, hints

    def append_record(
        self,
        *,
        session_id: str,
        source_tool: str,
        narrative_summary: str,
        forensic_artifact_ref: str = "",
        fetch_hints: Optional[Sequence[str]] = None,
        timestamp: Optional[float] = None,
        record_id: Optional[str] = None,
    ) -> EpisodicRecord:
        summary = _normalize_whitespace(narrative_summary)
        if not summary:
            raise ValueError("narrative_summary cannot be empty")

        record = EpisodicRecord(
            record_id=_normalize_whitespace(_safe_text(record_id)) or f"ep_{uuid.uuid4().hex[:16]}",
            session_id=_normalize_whitespace(_safe_text(session_id)),
            source_tool=_normalize_whitespace(_safe_text(source_tool)) or "unknown",
            narrative_summary=summary,
            forensic_artifact_ref=_normalize_whitespace(_safe_text(forensic_artifact_ref)),
            fetch_hints=_split_fetch_hints(fetch_hints),
            timestamp=float(timestamp if timestamp is not None else time.time()),
        )

        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._lock:
            self._ensure_loaded()
            with self.archive_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._records.append(record)
            self._vectors.append(self._vectorize_record(record))
        return record

    def archive_result(self, session_id: str, result: Dict[str, Any]) -> Optional[EpisodicRecord]:
        if not isinstance(result, dict):
            return None

        result_text = _safe_text(result.get("result"))
        if not result_text.strip():
            return None

        service_name = _normalize_whitespace(_safe_text(result.get("service_name")))
        tool_name = _normalize_whitespace(_safe_text(result.get("tool_name")))
        if service_name and tool_name:
            source_tool = f"{service_name}:{tool_name}"
        else:
            source_tool = service_name or tool_name or "unknown"

        narrative_summary, parsed_forensic, parsed_hints = self._extract_from_result_text(result_text)
        if not narrative_summary:
            return None

        forensic_ref = _normalize_whitespace(
            _safe_text(result.get("forensic_artifact_ref") or result.get("raw_result_ref") or parsed_forensic)
        )
        if _looks_like_none(forensic_ref):
            forensic_ref = ""

        hints = _split_fetch_hints(result.get("fetch_hints"))
        if not hints:
            hints = parsed_hints

        return self.append_record(
            session_id=session_id,
            source_tool=source_tool,
            narrative_summary=narrative_summary,
            forensic_artifact_ref=forensic_ref,
            fetch_hints=hints,
            timestamp=time.time(),
        )

    def archive_results(self, session_id: str, results: Sequence[Dict[str, Any]]) -> List[EpisodicRecord]:
        archived: List[EpisodicRecord] = []
        for result in results:
            record = self.archive_result(session_id, result)
            if record is not None:
                archived.append(record)
        return archived

    def search(
        self,
        query: str,
        *,
        session_id: Optional[str] = None,
        top_k: int = 3,
        min_score: float = 0.12,
    ) -> List[EpisodicSearchHit]:
        normalized_query = _normalize_whitespace(query)
        if not normalized_query:
            return []

        with self._lock:
            self._ensure_loaded()
            if not self._records:
                return []

            query_vector = _build_sparse_vector(normalized_query, self.vector_dims)
            if not query_vector:
                return []

            scored: List[Tuple[float, float, str, EpisodicRecord]] = []
            for idx, record in enumerate(self._records):
                score = _cosine_sparse(query_vector, self._vectors[idx])
                if session_id and record.session_id and record.session_id == session_id:
                    score += self.session_boost
                if score < min_score:
                    continue
                scored.append((score, record.timestamp, record.record_id, record))

            scored.sort(key=lambda item: (-item[0], -item[1], item[2]))

            limit = max(1, min(int(top_k), 20))
            hits: List[EpisodicSearchHit] = []
            for rank, (score, _ts, _rid, record) in enumerate(scored[:limit], start=1):
                hits.append(EpisodicSearchHit(record=record, score=score, rank=rank))
            return hits

    def build_reinjection_context(
        self,
        query: str,
        *,
        session_id: Optional[str] = None,
        top_k: int = 3,
        min_score: float = 0.18,
        max_chars: int = 1400,
    ) -> str:
        hits = self.search(query, session_id=session_id, top_k=top_k, min_score=min_score)
        if not hits:
            return ""

        lines: List[str] = [
            "[Episodic Memory Reinjection]",
            "以下是与当前问题相关的历史经验，请优先复用有效步骤并核对当前上下文：",
        ]
        for hit in hits:
            record = hit.record
            summary = _truncate_text(record.narrative_summary, 220)
            lines.append(
                f"{hit.rank}. score={hit.score:.3f} source={record.source_tool} "
                f"time={_format_ts(record.timestamp)} summary={summary}"
            )
            if record.forensic_artifact_ref:
                lines.append(f"forensic_artifact_ref: {record.forensic_artifact_ref}")
            if record.fetch_hints:
                lines.append(f"fetch_hints: {', '.join(record.fetch_hints[:4])}")

        lines.append("若历史经验与当前事实冲突，以当前事实为准。不要原样复读以上内容。")
        return _truncate_text("\n".join(lines), max_chars)

    def size(self) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._records)


def _default_archive_path() -> Path:
    try:
        from system.config import get_config

        cfg = get_config()
        log_dir = Path(getattr(cfg.system, "log_dir", "logs"))
    except Exception:
        log_dir = Path("logs")

    return log_dir / "episodic_memory" / "episodic_archive.jsonl"


_episodic_singleton_lock = threading.Lock()
_episodic_singleton: Optional[EpisodicMemoryArchive] = None


def get_episodic_memory() -> EpisodicMemoryArchive:
    global _episodic_singleton
    if _episodic_singleton is None:
        with _episodic_singleton_lock:
            if _episodic_singleton is None:
                _episodic_singleton = EpisodicMemoryArchive()
    return _episodic_singleton


def archive_tool_results_for_session(
    session_id: str,
    results: Sequence[Dict[str, Any]],
    *,
    archive: Optional[EpisodicMemoryArchive] = None,
) -> List[EpisodicRecord]:
    store = archive or get_episodic_memory()
    return store.archive_results(session_id, results)


def build_reinjection_context(
    session_id: str,
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.18,
    archive: Optional[EpisodicMemoryArchive] = None,
) -> str:
    store = archive or get_episodic_memory()
    return store.build_reinjection_context(query, session_id=session_id, top_k=top_k, min_score=min_score)


__all__ = [
    "EpisodicRecord",
    "EpisodicSearchHit",
    "EpisodicMemoryArchive",
    "archive_tool_results_for_session",
    "build_reinjection_context",
    "get_episodic_memory",
]
