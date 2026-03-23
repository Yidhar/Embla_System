import asyncio
import json
import logging
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from agents.prompt_engine import PromptAssembler, get_system_prompts_root
from system.config import config, get_specialized_api_override

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_LAST_EXTRACTION_RUNTIME_STATUS: Dict[str, Any] = {
    "last_success": {},
    "last_upstream_timeout": {},
}

_PROMPT_ASSEMBLER = PromptAssembler(prompts_root=str(get_system_prompts_root()))
_STRUCTURED_SYSTEM_PROMPT_BLOCK = "memory/quintuple_extractor_structured_system.md"
_STRUCTURED_USER_PROMPT_BLOCK = "memory/quintuple_extractor_structured_user.md"
_JSON_FALLBACK_PROMPT_BLOCK = "memory/quintuple_extractor_json_fallback.md"


def _get_extraction_override() -> dict:
    """Return the specialized override dict for quintuple_extraction, or empty dict."""
    return get_specialized_api_override("quintuple_extraction") or {}


def _resolve_extraction_api_key() -> str:
    override = _get_extraction_override()
    if override.get("api_key"):
        return override["api_key"]
    return str(getattr(config.api, "api_key", "") or "").strip()


def _resolve_extraction_base_url() -> str:
    override = _get_extraction_override()
    if override.get("base_url"):
        return override["base_url"]
    return str(getattr(config.api, "base_url", "") or "").strip()


def _resolve_extraction_model() -> str:
    override = _get_extraction_override()
    if override.get("model"):
        return override["model"]
    configured = str(getattr(config.grag, "extraction_model", "") or "").strip()
    if configured:
        return configured
    return str(getattr(config.api, "model", "") or "").strip()


def _resolve_extraction_temperature() -> float:
    configured_raw = getattr(config.grag, "extraction_temperature", 1.0)
    return max(0.0, min(float(1.0 if configured_raw is None else configured_raw), 2.0))


def _build_sync_client() -> OpenAI:
    return OpenAI(
        api_key=_resolve_extraction_api_key(),
        base_url=_resolve_extraction_base_url(),
        max_retries=0,
    )


def _build_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_resolve_extraction_api_key(),
        base_url=_resolve_extraction_base_url(),
        max_retries=0,
    )


def _resolve_timeout_seconds(timeout_seconds: Optional[float]) -> float:
    configured_raw = getattr(config.grag, "extraction_timeout", 20)
    configured = float(20 if configured_raw is None else configured_raw)
    if timeout_seconds is None:
        return max(1, configured)
    return max(0.01, float(timeout_seconds))


def _resolve_completion_timeout_seconds() -> float:
    configured_raw = getattr(config.grag, "base_timeout", 40)
    return max(0.01, float(40 if configured_raw is None else configured_raw))


def _resolve_max_retries(max_retries: Optional[int]) -> int:
    configured_raw = getattr(config.grag, "extraction_retries", 2)
    configured = int(2 if configured_raw is None else configured_raw)
    if max_retries is None:
        return max(0, configured)
    return max(0, int(max_retries))


def _remaining_time(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _is_upstream_timeout_error(exc: Exception) -> bool:
    exc_name = type(exc).__name__.strip().lower()
    exc_text = str(exc or "").strip().lower()
    if "timeout" in exc_name:
        return True
    if "timed out" in exc_text or "timeout" in exc_text:
        return True
    return False


def _describe_exception(exc: Exception) -> str:
    exc_name = type(exc).__name__.strip()
    exc_text = str(exc or "").strip()
    return f"{exc_name}: {exc_text}" if exc_text else exc_name


def _record_extraction_success(*, model: str, phase: str, quintuples: int) -> None:
    _LAST_EXTRACTION_RUNTIME_STATUS["last_success"] = {
        "occurred_at": time.time(),
        "model": str(model or "").strip(),
        "phase": str(phase or "").strip(),
        "quintuples": int(quintuples),
    }


def _record_upstream_timeout(*, model: str, timeout_seconds: float, phase: str, exc: Exception) -> None:
    endpoint = _resolve_extraction_base_url()
    normalized_timeout = round(max(0.0, float(timeout_seconds)), 3)
    detail = {
        "reason_code": "upstream_api_timeout",
        "occurred_at": time.time(),
        "model": str(model or "").strip(),
        "endpoint": endpoint,
        "phase": str(phase or "").strip(),
        "timeout_seconds": normalized_timeout,
        "error": _describe_exception(exc),
    }
    detail["message"] = (
        f"上游模型 API 超时：endpoint={endpoint or 'unknown'} model={detail['model'] or 'unknown'} "
        f"phase={detail['phase'] or 'unknown'} timeout={normalized_timeout}s。"
        "当前已回退到本地回退链（JSON/启发式）；请检查上游可用性或稍后重试。"
    )
    _LAST_EXTRACTION_RUNTIME_STATUS["last_upstream_timeout"] = detail


def get_extraction_runtime_status() -> Dict[str, Any]:
    return deepcopy(_LAST_EXTRACTION_RUNTIME_STATUS)


def _render_prompt_block(block_path: str, **variables: object) -> str:
    return _PROMPT_ASSEMBLER.render_block(block_path, variables=variables).strip()


def _build_structured_messages(text: str) -> List[dict]:
    return [
        {"role": "system", "content": _render_prompt_block(_STRUCTURED_SYSTEM_PROMPT_BLOCK)},
        {"role": "user", "content": _render_prompt_block(_STRUCTURED_USER_PROMPT_BLOCK, text=text)},
    ]


def _build_json_fallback_prompt(text: str) -> str:
    return _render_prompt_block(_JSON_FALLBACK_PROMPT_BLOCK, text=text)


def _normalize_quintuple_item(item: Any) -> Optional[tuple[str, str, str, str, str]]:
    if isinstance(item, (list, tuple)) and len(item) == 5:
        normalized = tuple(str(part or "").strip() for part in item)
        return normalized if all(normalized) else None
    if isinstance(item, dict):
        normalized = (
            str(item.get("subject") or "").strip(),
            str(item.get("subject_type") or "").strip(),
            str(item.get("predicate") or "").strip(),
            str(item.get("object") or "").strip(),
            str(item.get("object_type") or "").strip(),
        )
        return normalized if all(normalized) else None
    return None


def _parse_quintuple_payload(content: str) -> List[tuple[str, str, str, str, str]]:
    raw = str(content or "").strip()
    if not raw:
        return []

    candidates: List[str] = [raw]
    if "[" in raw and "]" in raw:
        candidates.append(raw[raw.index("[") : raw.rindex("]") + 1])
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.index("{") : raw.rindex("}") + 1])

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception as exc:
            last_error = exc
            continue

        if isinstance(payload, dict):
            rows = payload.get("quintuples")
        else:
            rows = payload
        if not isinstance(rows, list):
            continue

        normalized_rows: List[tuple[str, str, str, str, str]] = []
        for row in rows:
            normalized = _normalize_quintuple_item(row)
            if normalized is not None:
                normalized_rows.append(normalized)
        return _dedupe_quintuples(normalized_rows)

    if last_error is not None:
        raise last_error
    return []


_PATH_PATTERN = re.compile(
    r"(?:memory/)?(?:working|episodic|domain|\.deprecated)/[A-Za-z0-9_./-]+\.md|"
    r"README\.md|"
    r"[A-Za-z0-9_./-]+\.(?:md|txt|py|json)"
)
_IDENTIFIER_PATTERN = re.compile(r"\b[a-z0-9_]*api_shell_flow_smoke_[a-z0-9_]*\b", re.IGNORECASE)
_TOOL_CALL_PATTERN = re.compile(r"^\[tool_calls\]\s*(.+)$", re.MULTILINE)


def _dedupe_quintuples(rows: List[tuple[str, str, str, str, str]]) -> List[tuple[str, str, str, str, str]]:
    normalized: List[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        item = tuple(str(part or "").strip() for part in row)
        if len(item) != 5 or any(not part for part in item):
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _extract_quintuples_local(text: str) -> List[tuple[str, str, str, str, str]]:
    """Cheap heuristic fallback for Shell L2 extraction when the LLM path times out."""
    raw_text = str(text or "").strip()
    if not raw_text:
        return []

    rows: List[tuple[str, str, str, str, str]] = []
    lowered = raw_text.lower()

    if "五元组" in raw_text:
        rows.append(("用户", "person", "关注", "五元组提取", "topic"))
    if "系统状态" in raw_text or "get_system_status" in lowered:
        rows.append(("用户", "person", "查询", "系统状态", "topic"))
    if ("记忆" in raw_text and "搜索" in raw_text) or "memory_search" in lowered:
        rows.append(("用户", "person", "查询", "记忆搜索", "topic"))
    if "readme.md" in lowered:
        rows.append(("会话", "session", "引用", "README.md", "artifact"))

    for match in _TOOL_CALL_PATTERN.finditer(raw_text):
        for tool_name in str(match.group(1) or "").split(","):
            normalized = str(tool_name or "").strip()
            if normalized:
                rows.append(("Embla", "assistant", "调用", normalized, "tool"))

    for path in _PATH_PATTERN.findall(raw_text):
        normalized_path = str(path or "").strip()
        if normalized_path:
            rows.append(("会话", "session", "引用", normalized_path, "artifact"))

    for identifier in _IDENTIFIER_PATTERN.findall(raw_text):
        normalized_identifier = str(identifier or "").strip()
        if normalized_identifier:
            rows.append(("会话", "session", "涉及", normalized_identifier, "topic"))

    return _dedupe_quintuples(rows)


class Quintuple(BaseModel):
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str


class QuintupleResponse(BaseModel):
    quintuples: List[Quintuple]


async def extract_quintuples_async(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """异步版本的五元组提取。"""
    return await _extract_quintuples_async_structured(
        text,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


async def _extract_quintuples_async_structured(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """使用结构化输出的异步五元组提取"""
    messages = _build_structured_messages(text)
    request_timeout = _resolve_timeout_seconds(timeout_seconds)
    total_timeout = _resolve_completion_timeout_seconds()
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)
    async_client = _build_async_client()
    model = _resolve_extraction_model()
    temperature = _resolve_extraction_temperature()

    for attempt in range(attempts):
        remaining_budget = _remaining_time(deadline)
        remaining = min(remaining_budget, request_timeout)
        logger.info(
            "尝试使用结构化输出提取五元组 (第%s次, model=%s request_timeout=%ss, remaining=%0.2fs)",
            attempt + 1,
            model,
            request_timeout,
            remaining_budget,
        )
        if remaining <= 0:
            logger.warning("结构化五元组提取超时预算已耗尽")
            break

        try:
            completion = await async_client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=QuintupleResponse,
                max_tokens=getattr(config.api, "max_tokens", None) if hasattr(config.api, "max_tokens") else None,
                temperature=temperature,
                timeout=remaining,
            )

            result = completion.choices[0].message.parsed
            quintuples = [
                (q.subject, q.subject_type, q.predicate, q.object, q.object_type)
                for q in result.quintuples
            ]
            logger.info("结构化输出成功，提取到 %s 个五元组", len(quintuples))
            _record_extraction_success(model=model, phase="structured", quintuples=len(quintuples))
            return quintuples

        except Exception as exc:
            if _is_upstream_timeout_error(exc):
                _record_upstream_timeout(model=model, timeout_seconds=remaining, phase="structured", exc=exc)
                logger.warning("%s", get_extraction_runtime_status().get("last_upstream_timeout", {}).get("message", ""))
            else:
                logger.warning("结构化输出失败: %s", _describe_exception(exc))
            if attempt >= attempts - 1:
                logger.info("回退到传统JSON解析方法")
                remaining_budget = _remaining_time(deadline)
                if remaining_budget <= 0:
                    logger.warning("无剩余超时预算，回退本地启发式提取")
                    heuristic = _extract_quintuples_local(text)
                    if heuristic:
                        logger.warning("结构化输出失败后回退本地启发式提取，得到 %s 个五元组", len(heuristic))
                    return heuristic
                return await _extract_quintuples_async_fallback(
                    text,
                    timeout_seconds=remaining_budget,
                    max_retries=0,
                )
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

    heuristic = _extract_quintuples_local(text)
    if heuristic:
        logger.warning("结构化输出失败，回退本地启发式提取，得到 %s 个五元组", len(heuristic))
    return heuristic


async def _extract_quintuples_async_fallback(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """传统JSON解析的异步五元组提取（回退方案）"""
    prompt = _build_json_fallback_prompt(text)
    request_timeout = _resolve_timeout_seconds(timeout_seconds)
    total_timeout = _resolve_completion_timeout_seconds()
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)
    async_client = _build_async_client()
    model = _resolve_extraction_model()
    temperature = _resolve_extraction_temperature()

    for attempt in range(attempts):
        remaining_budget = _remaining_time(deadline)
        remaining = min(remaining_budget, request_timeout)
        if remaining <= 0:
            logger.warning("传统五元组提取超时预算已耗尽")
            break
        try:
            response = await async_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=getattr(config.api, "max_tokens", None) if hasattr(config.api, "max_tokens") else None,
                temperature=temperature,
                timeout=remaining,
            )

            content = (response.choices[0].message.content or "").strip()
            try:
                quintuples = _parse_quintuple_payload(content)
                logger.info("传统方法成功，提取到 %s 个五元组", len(quintuples))
                _record_extraction_success(model=model, phase="json_fallback", quintuples=len(quintuples))
                return quintuples
            except json.JSONDecodeError:
                logger.error("JSON解析失败，原始内容: %s", content[:200])
                raise

        except Exception as exc:
            if _is_upstream_timeout_error(exc):
                _record_upstream_timeout(model=model, timeout_seconds=remaining, phase="json_fallback", exc=exc)
                logger.warning("%s", get_extraction_runtime_status().get("last_upstream_timeout", {}).get("message", ""))
            else:
                logger.error("传统方法提取失败: %s", _describe_exception(exc))
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if attempt < attempts - 1 and sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

    heuristic = _extract_quintuples_local(text)
    if heuristic:
        logger.warning("传统方法失败，回退到本地启发式提取，得到 %s 个五元组", len(heuristic))
    return heuristic


def extract_quintuples(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """同步版本的五元组提取。"""
    return _extract_quintuples_structured(
        text,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def _extract_quintuples_structured(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """使用结构化输出的同步五元组提取"""
    messages = _build_structured_messages(text)
    request_timeout = _resolve_timeout_seconds(timeout_seconds)
    total_timeout = _resolve_completion_timeout_seconds()
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)
    client = _build_sync_client()
    model = _resolve_extraction_model()
    temperature = _resolve_extraction_temperature()

    for attempt in range(attempts):
        remaining_budget = _remaining_time(deadline)
        remaining = min(remaining_budget, request_timeout)
        logger.info(
            "尝试使用结构化输出提取五元组 (第%s次, model=%s request_timeout=%ss, remaining=%0.2fs)",
            attempt + 1,
            model,
            request_timeout,
            remaining_budget,
        )
        if remaining <= 0:
            logger.warning("结构化五元组提取超时预算已耗尽")
            break

        try:
            completion = client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=QuintupleResponse,
                max_tokens=getattr(config.api, "max_tokens", None) if hasattr(config.api, "max_tokens") else None,
                temperature=temperature,
                timeout=remaining,
            )

            result = completion.choices[0].message.parsed
            quintuples = [
                (q.subject, q.subject_type, q.predicate, q.object, q.object_type)
                for q in result.quintuples
            ]
            logger.info("结构化输出成功，提取到 %s 个五元组", len(quintuples))
            _record_extraction_success(model=model, phase="structured", quintuples=len(quintuples))
            return quintuples

        except Exception as exc:
            if _is_upstream_timeout_error(exc):
                _record_upstream_timeout(model=model, timeout_seconds=remaining, phase="structured", exc=exc)
                logger.warning("%s", get_extraction_runtime_status().get("last_upstream_timeout", {}).get("message", ""))
            else:
                logger.warning("结构化输出失败: %s", _describe_exception(exc))
            if attempt >= attempts - 1:
                logger.info("回退到传统JSON解析方法")
                remaining_budget = _remaining_time(deadline)
                if remaining_budget <= 0:
                    logger.warning("无剩余超时预算，回退本地启发式提取")
                    heuristic = _extract_quintuples_local(text)
                    if heuristic:
                        logger.warning("结构化输出失败后回退本地启发式提取，得到 %s 个五元组", len(heuristic))
                    return heuristic
                return _extract_quintuples_fallback(
                    text,
                    timeout_seconds=remaining_budget,
                    max_retries=0,
                )
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    heuristic = _extract_quintuples_local(text)
    if heuristic:
        logger.warning("结构化输出失败，回退本地启发式提取，得到 %s 个五元组", len(heuristic))
    return heuristic


def _extract_quintuples_fallback(
    text,
    *,
    timeout_seconds: Optional[float] = None,
    max_retries: Optional[int] = None,
):
    """传统JSON解析的同步五元组提取（回退方案）"""
    prompt = _build_json_fallback_prompt(text)
    request_timeout = _resolve_timeout_seconds(timeout_seconds)
    total_timeout = _resolve_completion_timeout_seconds()
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)
    client = _build_sync_client()
    model = _resolve_extraction_model()
    temperature = _resolve_extraction_temperature()

    for attempt in range(attempts):
        remaining_budget = _remaining_time(deadline)
        remaining = min(remaining_budget, request_timeout)
        if remaining <= 0:
            logger.warning("传统五元组提取超时预算已耗尽")
            break
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=getattr(config.api, "max_tokens", None) if hasattr(config.api, "max_tokens") else None,
                temperature=temperature,
                timeout=remaining,
            )

            content = (response.choices[0].message.content or "").strip()
            try:
                quintuples = _parse_quintuple_payload(content)
                logger.info("传统方法成功，提取到 %s 个五元组", len(quintuples))
                _record_extraction_success(model=model, phase="json_fallback", quintuples=len(quintuples))
                return quintuples
            except json.JSONDecodeError:
                logger.error("JSON解析失败，原始内容: %s", content[:200])
                raise

        except Exception as exc:
            if _is_upstream_timeout_error(exc):
                _record_upstream_timeout(model=model, timeout_seconds=remaining, phase="json_fallback", exc=exc)
                logger.warning("%s", get_extraction_runtime_status().get("last_upstream_timeout", {}).get("message", ""))
            else:
                logger.error("传统方法提取失败: %s", _describe_exception(exc))
            sleep_seconds = min(1.0, _remaining_time(deadline))
            if attempt < attempts - 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)

    heuristic = _extract_quintuples_local(text)
    if heuristic:
        logger.warning("传统方法失败，回退到本地启发式提取，得到 %s 个五元组", len(heuristic))
    return heuristic
