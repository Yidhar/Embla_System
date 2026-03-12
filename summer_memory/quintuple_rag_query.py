import json
import logging

import requests

from agents.prompt_engine import PromptAssembler, get_system_prompts_root
from .quintuple_extractor import config as runtime_config

config = runtime_config
API_URL = f"{config.api.base_url.rstrip('/')}/chat/completions"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_PROMPT_ASSEMBLER = PromptAssembler(prompts_root=str(get_system_prompts_root()))
_KEYWORD_PROMPT_BLOCK = "memory/quintuple_rag_keyword_prompt.md"
_KEYWORD_PROMPT_OLLAMA_BLOCK = "memory/quintuple_rag_keyword_prompt_ollama.md"

recent_context = []


def _build_keyword_prompt(context: str, user_question: str, *, ollama: bool) -> str:
    block_path = _KEYWORD_PROMPT_OLLAMA_BLOCK if ollama else _KEYWORD_PROMPT_BLOCK
    return _PROMPT_ASSEMBLER.render_block(
        block_path,
        variables={"context": context, "user_question": user_question},
    ).strip()


def set_context(texts):
    """设置查询上下文"""
    global recent_context
    context_length = getattr(config.grag, "context_length", 5)
    recent_context = texts[:context_length]
    logger.info("更新查询上下文: %s 条记录", len(recent_context))


def query_knowledge(user_question):
    """调用当前配置的聊天模型提取关键词并查询知识图谱"""
    context_str = "\n".join(recent_context) if recent_context else "无上下文"

    headers = {
        "Authorization": f"Bearer {config.api.api_key}",
        "Content-Type": "application/json",
    }

    is_ollama = "localhost" in config.api.base_url or "11434" in config.api.base_url
    prompt = _build_keyword_prompt(context_str, user_question, ollama=is_ollama)

    body = {
        "model": config.api.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": config.api.max_tokens,
        "temperature": 0.5,
    }

    if is_ollama:
        body["format"] = "json"

    try:
        response = requests.post(API_URL, headers=headers, json=body, timeout=20)
        response.raise_for_status()
        content = response.json()

        if "choices" not in content or not content["choices"]:
            logger.error("LLM API 响应中未找到 'choices' 字段")
            return "无法处理 API 响应，请稍后重试。"

        raw_content = content["choices"][0]["message"]["content"]
        try:
            raw_content = raw_content.strip()
            if raw_content.startswith("```json") and raw_content.endswith("```"):
                raw_content = raw_content[7:-3].strip()
            keywords = json.loads(raw_content)
            if not isinstance(keywords, list):
                raise ValueError("关键词应为列表")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("解析 LLM 响应失败: %s, 错误: %s", raw_content, exc)
            return "无法解析关键词，请检查问题格式。"

        if not keywords:
            logger.warning("未提取到关键词")
            return "未找到相关关键词，请提供更具体的问题。"

        logger.info("提取关键词: %s", keywords)
        from .quintuple_graph import query_graph_by_keywords

        quintuples = query_graph_by_keywords(keywords)
        if not quintuples:
            logger.info("未找到相关五元组: %s", keywords)
            return "未在知识图谱中找到相关信息。"

        answer = "我在知识图谱中找到以下相关信息：\n\n"
        for head, head_type, relation, tail, tail_type in quintuples:
            answer += f"- {head}({head_type}) —[{relation}]→ {tail}({tail_type})\n"
        return answer

    except requests.exceptions.HTTPError as exc:
        logger.error("LLM API HTTP 错误: %s", exc)
        return "调用 LLM API 失败，请检查 API 密钥、服务状态或网络连接。"
    except requests.exceptions.RequestException as exc:
        logger.error("LLM API 请求失败: %s", exc)
        return "无法连接到 LLM API，请检查网络。"
    except Exception as exc:
        logger.error("查询过程中发生未知错误: %s", exc)
        return "查询过程中发生未知错误，请稍后重试。"
