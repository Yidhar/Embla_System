#!/usr/bin/env python3
"""
上下文压缩模块
当对话消息的 token 数超过阈值时，自动将较早的消息摘要化，防止超长上下文导致 API 报错或性能下降。

策略：保留 system prompt + 最近 N 条消息不变，将较早的消息调用轻量 LLM (gpt-4.1-nano) 生成摘要，
替换为一条 system 消息注入上下文。
"""

import logging
from typing import Dict, List, Optional

import litellm
from litellm import acompletion

from . import naga_auth
from system.config import get_config

logger = logging.getLogger("ContextCompressor")

# 默认阈值：100k tokens 触发压缩
TOKEN_THRESHOLD = 100_000
# 压缩时保留的最近消息条数（约 10 轮对话）
KEEP_RECENT = 20
# 压缩用模型
COMPRESS_MODEL = "gpt-4.1-nano"

SUMMARIZE_PROMPT = """\
你是一个对话摘要助手。请将以下多轮对话历史压缩为一段简洁的摘要（中文），保留：
1. 用户的核心需求和意图
2. 已经做出的重要决策和结论
3. 关键的技术细节、代码片段名称、文件路径
4. 尚未解决的问题

只输出摘要文本，不要添加任何标题或格式前缀。摘要应控制在 800 字以内。"""


def count_tokens(messages: List[Dict], model: str = "gpt-4") -> int:
    """计算消息列表的 token 数"""
    try:
        return litellm.token_counter(model=model, messages=messages)
    except Exception as e:
        # fallback: 粗略估算（中文约 1.5 token/字，英文约 0.75 token/word）
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated = int(total_chars * 1.2)
        logger.debug(f"token_counter 失败，使用粗略估算 {estimated}: {e}")
        return estimated


def _get_compress_llm_params() -> Dict:
    """获取压缩模型的 LLM 调用参数"""
    if naga_auth.is_authenticated():
        token = naga_auth.get_access_token()
        return {
            "api_key": token,
            "api_base": naga_auth.NAGA_MODEL_URL + "/",
            "extra_body": {"user_token": token},
        }
    cfg = get_config()
    return {
        "api_key": cfg.api.api_key,
        "api_base": cfg.api.base_url.rstrip("/") + "/" if cfg.api.base_url else None,
    }


def _get_compress_model_name() -> str:
    """获取压缩模型名称（LiteLLM 格式）"""
    if naga_auth.is_authenticated():
        return f"openai/{COMPRESS_MODEL}"
    # 未登录时也尝试使用 gpt-4.1-nano（需要用户 API 支持该模型）
    base_url = (get_config().api.base_url or "").lower()
    if "openai.com" in base_url:
        return COMPRESS_MODEL
    return f"openai/{COMPRESS_MODEL}"


async def compress_context(messages: List[Dict]) -> List[Dict]:
    """当消息 token 数超过阈值时压缩上下文

    Args:
        messages: 完整的对话消息列表（含 system prompt）

    Returns:
        压缩后的消息列表（如未超阈值则原样返回）
    """
    if len(messages) <= KEEP_RECENT + 1:
        # 消息太少，无需压缩
        return messages

    total_tokens = count_tokens(messages)
    if total_tokens <= TOKEN_THRESHOLD:
        logger.debug(f"[压缩] 当前 {total_tokens} tokens，未超阈值 {TOKEN_THRESHOLD}，跳过压缩")
        return messages

    logger.info(f"[压缩] 当前 {total_tokens} tokens，超过阈值 {TOKEN_THRESHOLD}，开始压缩")

    # 分割：system prompt (messages[0]) + 早期消息 + 最近消息
    system_msg = messages[0] if messages[0]["role"] == "system" else None
    start_idx = 1 if system_msg else 0

    # 保留最近 KEEP_RECENT 条消息
    if len(messages) - start_idx <= KEEP_RECENT:
        return messages

    early_messages = messages[start_idx: -KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]

    # 将早期消息格式化为文本
    conversation_text = _format_messages_for_summary(early_messages)

    # 调用轻量 LLM 生成摘要
    summary = await _generate_summary(conversation_text)
    if not summary:
        logger.warning("[压缩] 摘要生成失败，返回原始消息")
        return messages

    # 构建压缩后的消息列表
    compressed = []
    if system_msg:
        compressed.append(system_msg)

    # 插入摘要作为 system 消息
    compressed.append({
        "role": "system",
        "content": f"[以下是之前对话的摘要，供你参考上下文]\n\n{summary}\n\n[摘要结束，以下是最近的对话]"
    })
    compressed.extend(recent_messages)

    compressed_tokens = count_tokens(compressed)
    saved = total_tokens - compressed_tokens
    logger.info(
        f"[压缩] 完成: {total_tokens} → {compressed_tokens} tokens "
        f"(节省 {saved}, 压缩了 {len(early_messages)} 条早期消息)"
    )

    return compressed


def _format_messages_for_summary(messages: List[Dict]) -> str:
    """将消息列表格式化为摘要用的文本"""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # 处理多模态消息（content 可能是 list）
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
        # 截断过长的单条消息
        if len(content) > 3000:
            content = content[:3000] + "...[截断]"
        role_label = {"user": "用户", "assistant": "助手", "system": "系统", "tool": "工具结果"}.get(role, role)
        lines.append(f"【{role_label}】{content}")
    return "\n\n".join(lines)


async def _generate_summary(conversation_text: str) -> Optional[str]:
    """调用轻量 LLM 生成对话摘要"""
    try:
        model_name = _get_compress_model_name()
        llm_params = _get_compress_llm_params()

        response = await acompletion(
            model=model_name,
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": conversation_text},
            ],
            temperature=0.3,
            max_tokens=2000,
            timeout=30,
            **llm_params,
        )
        summary = response.choices[0].message.content or ""
        logger.info(f"[压缩] 摘要生成成功，长度 {len(summary)} 字")
        return summary.strip()
    except Exception as e:
        logger.error(f"[压缩] 摘要生成失败: {e}")
        return None
