import asyncio
import json
import logging
import time
from typing import List, Optional

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from agents.prompt_engine import PromptAssembler, get_system_prompts_root
from system.config import config

client = OpenAI(
    api_key=config.api.api_key,
    base_url=config.api.base_url,
)

async_client = AsyncOpenAI(
    api_key=config.api.api_key,
    base_url=config.api.base_url,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_PROMPT_ASSEMBLER = PromptAssembler(prompts_root=str(get_system_prompts_root()))
_STRUCTURED_SYSTEM_PROMPT_BLOCK = "memory/quintuple_extractor_structured_system.md"
_STRUCTURED_USER_PROMPT_BLOCK = "memory/quintuple_extractor_structured_user.md"
_JSON_FALLBACK_PROMPT_BLOCK = "memory/quintuple_extractor_json_fallback.md"


def _resolve_timeout_seconds(timeout_seconds: Optional[int]) -> int:
    configured_raw = getattr(config.grag, "extraction_timeout", 12)
    configured = int(12 if configured_raw is None else configured_raw)
    if timeout_seconds is None:
        return max(1, configured)
    return max(1, int(timeout_seconds))


def _resolve_max_retries(max_retries: Optional[int]) -> int:
    configured_raw = getattr(config.grag, "extraction_retries", 2)
    configured = int(2 if configured_raw is None else configured_raw)
    if max_retries is None:
        return max(0, configured)
    return max(0, int(max_retries))


def _remaining_time(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _render_prompt_block(block_path: str, **variables: object) -> str:
    return _PROMPT_ASSEMBLER.render_block(block_path, variables=variables).strip()


def _build_structured_messages(text: str) -> List[dict]:
    return [
        {"role": "system", "content": _render_prompt_block(_STRUCTURED_SYSTEM_PROMPT_BLOCK)},
        {"role": "user", "content": _render_prompt_block(_STRUCTURED_USER_PROMPT_BLOCK, text=text)},
    ]


def _build_json_fallback_prompt(text: str) -> str:
    return _render_prompt_block(_JSON_FALLBACK_PROMPT_BLOCK, text=text)


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
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """异步版本的五元组提取"""
    return await _extract_quintuples_async_fallback(
        text,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


async def _extract_quintuples_async_structured(
    text,
    *,
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """使用结构化输出的异步五元组提取"""
    messages = _build_structured_messages(text)
    total_timeout = _resolve_timeout_seconds(timeout_seconds)
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)

    for attempt in range(attempts):
        logger.info(f"尝试使用结构化输出提取五元组 (第{attempt + 1}次)")
        remaining = _remaining_time(deadline)
        if remaining <= 0:
            logger.warning("结构化五元组提取超时预算已耗尽")
            break

        try:
            completion = await async_client.beta.chat.completions.parse(
                model=config.api.model,
                messages=messages,
                response_format=QuintupleResponse,
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=remaining,
            )

            result = completion.choices[0].message.parsed
            quintuples = [
                (q.subject, q.subject_type, q.predicate, q.object, q.object_type)
                for q in result.quintuples
            ]
            logger.info("结构化输出成功，提取到 %s 个五元组", len(quintuples))
            return quintuples

        except Exception as exc:
            logger.warning("结构化输出失败: %s", str(exc))
            if attempt >= attempts - 1:
                logger.info("回退到传统JSON解析方法")
                remaining_budget = _remaining_time(deadline)
                if remaining_budget <= 0:
                    logger.warning("无剩余超时预算，跳过结构化输出回退")
                    return []
                return await _extract_quintuples_async_fallback(
                    text,
                    timeout_seconds=max(1, int(remaining_budget)),
                    max_retries=0,
                )
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

    return []


async def _extract_quintuples_async_fallback(
    text,
    *,
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """传统JSON解析的异步五元组提取（回退方案）"""
    prompt = _build_json_fallback_prompt(text)
    total_timeout = _resolve_timeout_seconds(timeout_seconds)
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)

    for attempt in range(attempts):
        remaining = _remaining_time(deadline)
        if remaining <= 0:
            logger.warning("传统五元组提取超时预算已耗尽")
            break
        try:
            response = await async_client.chat.completions.create(
                model=config.api.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=remaining,
            )

            content = (response.choices[0].message.content or "").strip()
            try:
                quintuples = json.loads(content)
                logger.info("传统方法成功，提取到 %s 个五元组", len(quintuples))
                return [tuple(item) for item in quintuples if len(item) == 5]
            except json.JSONDecodeError:
                logger.error("JSON解析失败，原始内容: %s", content[:200])
                if "[" in content and "]" in content:
                    start = content.index("[")
                    end = content.rindex("]") + 1
                    quintuples = json.loads(content[start:end])
                    return [tuple(item) for item in quintuples if len(item) == 5]
                raise

        except Exception as exc:
            logger.error("传统方法提取失败: %s", str(exc))
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if attempt < attempts - 1 and sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

    return []


def extract_quintuples(
    text,
    *,
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """同步版本的五元组提取"""
    return _extract_quintuples_structured(
        text,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def _extract_quintuples_structured(
    text,
    *,
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """使用结构化输出的同步五元组提取"""
    messages = _build_structured_messages(text)
    total_timeout = _resolve_timeout_seconds(timeout_seconds)
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)

    for attempt in range(attempts):
        logger.info(f"尝试使用结构化输出提取五元组 (第{attempt + 1}次)")
        remaining = _remaining_time(deadline)
        if remaining <= 0:
            logger.warning("结构化五元组提取超时预算已耗尽")
            break

        try:
            completion = client.beta.chat.completions.parse(
                model=config.api.model,
                messages=messages,
                response_format=QuintupleResponse,
                max_tokens=config.api.max_tokens,
                temperature=0.3,
                timeout=remaining,
            )

            result = completion.choices[0].message.parsed
            quintuples = [
                (q.subject, q.subject_type, q.predicate, q.object, q.object_type)
                for q in result.quintuples
            ]
            logger.info("结构化输出成功，提取到 %s 个五元组", len(quintuples))
            return quintuples

        except Exception as exc:
            logger.warning("结构化输出失败: %s", str(exc))
            if attempt >= attempts - 1:
                logger.info("回退到传统JSON解析方法")
                remaining_budget = _remaining_time(deadline)
                if remaining_budget <= 0:
                    logger.warning("无剩余超时预算，跳过结构化输出回退")
                    return []
                return _extract_quintuples_fallback(
                    text,
                    timeout_seconds=max(1, int(remaining_budget)),
                    max_retries=0,
                )
            sleep_seconds = min(float(1 + attempt), _remaining_time(deadline))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    return []


def _extract_quintuples_fallback(
    text,
    *,
    timeout_seconds: Optional[int] = None,
    max_retries: Optional[int] = None,
):
    """传统JSON解析的同步五元组提取（回退方案）"""
    prompt = _build_json_fallback_prompt(text)
    total_timeout = _resolve_timeout_seconds(timeout_seconds)
    retries = _resolve_max_retries(max_retries)
    attempts = max(1, retries + 1)
    deadline = time.monotonic() + float(total_timeout)

    for attempt in range(attempts):
        remaining = _remaining_time(deadline)
        if remaining <= 0:
            logger.warning("传统五元组提取超时预算已耗尽")
            break
        try:
            response = client.chat.completions.create(
                model=config.api.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=config.api.max_tokens,
                temperature=0.5,
                timeout=remaining,
            )

            content = (response.choices[0].message.content or "").strip()
            try:
                quintuples = json.loads(content)
                logger.info("传统方法成功，提取到 %s 个五元组", len(quintuples))
                return [tuple(item) for item in quintuples if len(item) == 5]
            except json.JSONDecodeError:
                logger.error("JSON解析失败，原始内容: %s", content[:200])
                if "[" in content and "]" in content:
                    start = content.index("[")
                    end = content.rindex("]") + 1
                    quintuples = json.loads(content[start:end])
                    return [tuple(item) for item in quintuples if len(item) == 5]
                raise

        except Exception as exc:
            logger.error("传统方法提取失败: %s", str(exc))
            sleep_seconds = min(1.0, _remaining_time(deadline))
            if attempt < attempts - 1 and sleep_seconds > 0:
                time.sleep(sleep_seconds)

    return []
