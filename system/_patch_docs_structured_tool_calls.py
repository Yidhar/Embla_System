#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch docs to reflect structured tool_calls (no ```tool parsing) and remove legacy ```tool examples from skills.

Edits:
- README.md: replace section '### 流式工具调用循环' until next '---'
- README_en.md: replace section '### Streaming Tool Call Loop' until next '---'
- skills/solve/SKILL.md: remove ```tool example block
- skills/verify-authenticity/SKILL.md: remove ```tool example block

Idempotent: running multiple times should keep the new blocks.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def write(p: Path, s: str) -> None:
    p.write_text(s, encoding="utf-8")


def replace_md_section(text: str, heading_pat: str, new_block: str) -> str:
    """Replace section starting at heading_pat until the next markdown horizontal rule line ('---')."""
    m = re.search(heading_pat, text, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"Heading not found: {heading_pat}")
    start = m.start()
    # find next line that is exactly --- after the heading
    hr = re.search(r"^---\s*$", text[m.end():], flags=re.MULTILINE)
    if not hr:
        raise RuntimeError("Section terminator '---' not found")
    end = m.end() + hr.start()
    # keep the terminator (---) in place
    return text[:start] + new_block.rstrip() + "\n\n" + text[end:]


def patch_readme_zh() -> None:
    p = ROOT / "README.md"
    s = read(p)

    new_block = """### 流式工具调用循环（结构化 tool_calls）

NagaAgent 的工具调用采用 **OpenAI 兼容的 tools schema** 与 **结构化 tool_calls 流式通道**：
工具调用不再写入 assistant 的文本 content，而是作为独立的 `tool_calls` 结构化事件由后端接收、执行与回注。

**单轮流程**：

```
LLM 流式输出(content/reasoning) ──SSE──▶ 前端实时显示与 TTS
            │
            ├─（可选）delta.tool_calls 增量到达
            ▼
      LLMService 合并 tool_calls 增量
            │
            ├─ SSE: type=content/reasoning → 透传前端
            └─ SSE: type=tool_calls        → 仅供 AgenticLoop 消费（不混入正文）
                               │
                               ▼
AgenticLoop 消费结构化 tool_calls → 转换为统一 agentType 调度 → 并行执行
   ├─ mcp      → MCPManager.unified_call()（进程内）
   ├─ native   → NativeToolExecutor.execute()（本地沙盒）
   ├─ openclaw → Agent Server /openclaw/send（并支持 local-first 拦截为 native）
   └─ live2d   → UI 通知（fire-and-forget）
            │
            ▼
工具结果以 tool_results 事件回传前端，并注入 messages 进入下一轮
```

**实现要点**：

- **工具定义**：后端向模型传入 `tools=[...]`（OpenAI-compatible）。
- **结构化 tool_calls 提取**：`apiserver/llm_service.py` 在流式响应中合并 `delta.tool_calls`，并输出 `type="tool_calls"` SSE 事件。
- **Loop 执行与回注**：`apiserver/agentic_tool_loop.py` 消费结构化 tool_calls 并并行执行，不依赖 ```tool 文本解析。
- **兼容说明**：仓库中可能存在历史构建产物/旧文档仍提及 ```tool 代码块机制；以当前源码主链路的结构化 tool_calls 为准。

源码：[`apiserver/llm_service.py`](apiserver/llm_service.py)、[`apiserver/agentic_tool_loop.py`](apiserver/agentic_tool_loop.py)
"""

    s2 = replace_md_section(s, r"^###\s+流式工具调用循环\s*$", new_block)
    write(p, s2)


def patch_readme_en() -> None:
    p = ROOT / "README_en.md"
    s = read(p)

    new_block = """### Streaming Tool Call Loop (Structured tool_calls)

NagaAgent uses an **OpenAI-compatible tools schema** and a **structured streaming tool_calls channel**.
Tool calls are not embedded in assistant text content anymore. Instead, the backend receives and executes them as standalone `tool_calls` events, then injects tool results back into the conversation.

**Single-round flow**:

```
LLM streams content/reasoning ──SSE──▶ Frontend renders & TTS
         │
         ├─ (optional) delta.tool_calls arrive
         ▼
  LLMService merges tool_calls deltas
         │
         ├─ SSE type=content/reasoning → forwarded to frontend
         └─ SSE type=tool_calls        → consumed by AgenticLoop only (not mixed into text)
                            │
                            ▼
AgenticLoop consumes structured tool_calls → unified agentType dispatch → parallel execution
   ├─ mcp      → MCPManager.unified_call() (in-process)
   ├─ native   → NativeToolExecutor.execute() (sandboxed local tools)
   ├─ openclaw → Agent Server /openclaw/send (with local-first interception to native)
   └─ live2d   → UI notifications (fire-and-forget)
         │
         ▼
Tool results are sent as tool_results events and injected into messages for the next round
```

**Key points**:

- **Tool definitions** are passed via `tools=[...]` (OpenAI-compatible).
- **Structured tool_calls extraction**: `apiserver/llm_service.py` merges `delta.tool_calls` and emits an SSE chunk `type="tool_calls"`.
- **Loop execution & injection**: `apiserver/agentic_tool_loop.py` consumes structured tool_calls and executes them; the main path does not rely on ```tool text parsing.
- **Compatibility note**: legacy ```tool-block descriptions may still exist in historical build artifacts/old docs; the source code mainline uses structured tool_calls.

Source: [`apiserver/llm_service.py`](apiserver/llm_service.py), [`apiserver/agentic_tool_loop.py`](apiserver/agentic_tool_loop.py)
"""

    s2 = replace_md_section(s, r"^###\s+Streaming Tool Call Loop\s*$", new_block)
    write(p, s2)


def strip_tool_block_in_skill(text: str) -> str:
    # Remove fenced ```tool blocks entirely
    text2 = re.sub(r"\n```tool\n[\s\S]*?\n```\n", "\n", text)
    # If any inline mention of ```tool remains, remove backticks to avoid fences.
    text2 = text2.replace("```tool", "tool")
    return text2


def patch_skill_solve() -> None:
    p = ROOT / "skills" / "solve" / "SKILL.md"
    s = read(p)
    s = strip_tool_block_in_skill(s)
    # Replace step 2 wording to avoid implying literal code block output
    s = re.sub(
        r"2\.\s*判断是否需要联网：([\s\S]*?)\n3\.",
        "2. 判断是否需要联网：如果问题涉及实时信息、最新数据、具体事实核查等，先发起联网搜索/浏览器访问等工具调用（通过结构化 tool_calls 通道发起，不要在正文输出 JSON 或代码块）。\n3.",
        s,
        count=1,
    )
    write(p, s)


def patch_skill_verify() -> None:
    p = ROOT / "skills" / "verify-authenticity" / "SKILL.md"
    s = read(p)
    s = strip_tool_block_in_skill(s)
    s = re.sub(
        r"1\.\s*\*\*联网搜索\*\*：([\s\S]*?)\n2\.",
        "1. **联网搜索**：先使用工具搜索与用户内容相关的权威信息和事实依据（通过结构化 tool_calls 通道发起，不要在正文输出 JSON 或代码块）。\n2.",
        s,
        count=1,
    )
    write(p, s)


def main() -> None:
    patch_readme_zh()
    patch_readme_en()
    patch_skill_solve()
    patch_skill_verify()
    print("OK")


if __name__ == "__main__":
    main()
