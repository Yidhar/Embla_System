from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from system.config import get_config

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    api_base: str
    api_key: str
    model: str
    dimensions: int
    encoding_format: str
    max_input_tokens: int
    request_timeout_seconds: int

    @property
    def ready(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)


def _coerce_int(value: Any, *, default: int, minimum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(minimum, default)
    return max(minimum, parsed)


def resolve_embedding_runtime_config() -> EmbeddingRuntimeConfig:
    cfg = get_config()
    emb = cfg.embedding
    api = cfg.api
    api_base = str(emb.api_base or "").strip() or str(api.base_url or "").strip()
    api_key = str(emb.api_key or "").strip() or str(api.api_key or "").strip()
    model = str(emb.model or "").strip() or "text-embedding-v4"
    dimensions = max(0, _coerce_int(getattr(emb, "dimensions", 0), default=0, minimum=0))
    encoding_format = str(getattr(emb, "encoding_format", "float") or "float").strip().lower() or "float"
    max_input_tokens = _coerce_int(getattr(emb, "max_input_tokens", 8192), default=8192, minimum=1)
    request_timeout_seconds = _coerce_int(
        getattr(emb, "request_timeout_seconds", 30),
        default=30,
        minimum=1,
    )
    return EmbeddingRuntimeConfig(
        api_base=api_base,
        api_key=api_key,
        model=model,
        dimensions=dimensions,
        encoding_format=encoding_format,
        max_input_tokens=max_input_tokens,
        request_timeout_seconds=request_timeout_seconds,
    )


def estimate_tokens_rough(text: str) -> int:
    normalized = str(text or "")
    if not normalized:
        return 0
    cjk_count = len(_CJK_RE.findall(normalized))
    non_cjk_chars = max(0, len(normalized) - cjk_count)
    # Rough heuristic:
    # - CJK tends to be closer to 1 char ~ 1 token
    # - Non-CJK is roughly 4 chars ~ 1 token
    return cjk_count + max(1, non_cjk_chars // 4)


def _truncate_to_token_budget(text: str, *, token_budget: int) -> str:
    normalized = str(text or "")
    if token_budget <= 0:
        return normalized
    estimated = estimate_tokens_rough(normalized)
    if estimated <= token_budget:
        return normalized
    ratio = max(0.05, min(1.0, float(token_budget) / float(max(1, estimated))))
    cut = max(1, int(len(normalized) * ratio))
    candidate = normalized[:cut]
    while cut > 16 and estimate_tokens_rough(candidate) > token_budget:
        cut = max(16, cut - max(8, cut // 20))
        candidate = normalized[:cut]
    return candidate


def _build_embedding_request_kwargs(
    *,
    runtime: EmbeddingRuntimeConfig,
    input_texts: Sequence[str],
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": runtime.model,
        "input": list(input_texts),
        "encoding_format": runtime.encoding_format,
    }
    if runtime.dimensions > 0:
        kwargs["dimensions"] = runtime.dimensions
    return kwargs


def embed_texts_openai_compat(
    texts: Sequence[str],
) -> Tuple[List[Optional[List[float]]], Dict[str, Any]]:
    rows = [str(text or "") for text in texts]
    if not rows:
        return [], {"ok": True, "count": 0}

    runtime = resolve_embedding_runtime_config()
    if not runtime.ready:
        return [None for _ in rows], {"ok": False, "error": "embedding_config_incomplete"}

    prepared = [_truncate_to_token_budget(text, token_budget=runtime.max_input_tokens) for text in rows]
    try:
        from openai import OpenAI
    except Exception:
        return [None for _ in rows], {"ok": False, "error": "openai_sdk_not_available"}

    client = OpenAI(
        api_key=runtime.api_key,
        base_url=runtime.api_base,
        timeout=runtime.request_timeout_seconds,
    )
    request_kwargs = _build_embedding_request_kwargs(runtime=runtime, input_texts=prepared)
    try:
        completion = client.embeddings.create(**request_kwargs)
        result: List[Optional[List[float]]] = [None for _ in rows]
        for item in getattr(completion, "data", []) or []:
            idx = int(getattr(item, "index", -1))
            if idx < 0 or idx >= len(rows):
                continue
            embedding = getattr(item, "embedding", None)
            if isinstance(embedding, list):
                result[idx] = [float(x) for x in embedding]
        usage = getattr(completion, "usage", None)
        usage_payload = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        return result, {
            "ok": True,
            "count": len(rows),
            "usage": usage_payload,
            "model": str(getattr(completion, "model", runtime.model) or runtime.model),
        }
    except Exception as exc:
        logger.warning("[Embedding] openai-compatible embeddings.create failed: %s", exc)
        return [None for _ in rows], {"ok": False, "error": str(exc)}


__all__ = [
    "EmbeddingRuntimeConfig",
    "resolve_embedding_runtime_config",
    "estimate_tokens_rough",
    "embed_texts_openai_compat",
]
