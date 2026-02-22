# 06 - Structured tool_calls And Native Execution

This document records the current tool execution pipeline after legacy routes were removed.

## 1. Core Principle

Tool execution is driven by structured `tool_calls` only.

- No markdown fenced `tool` blocks.
- No free-form `agentType` JSON in plain text.

## 2. Execution Flow

1. `apiserver/llm_service.py` streams LLM output.
2. Tool call deltas are merged into normalized `tool_calls` entries.
3. `apiserver/agentic_tool_loop.py` validates each call.
4. Calls are dispatched by type:
   - `native` -> `apiserver/native_tools.py`
   - `mcp` -> MCP manager path
   - `live2d` -> UI notification path

## 3. Native Tool Scope

`NativeToolExecutor` handles local project operations inside sandbox boundaries.

Key tools include:

- `read_file`, `write_file`, `list_files`
- `search_keyword`, `query_docs`
- `run_cmd`
- `git_status`, `git_diff`, `git_log`, `git_show`, `git_blame`, `git_grep`
- `python_repl`
- `get_cwd`

## 4. Security Boundary

Native execution is constrained by `system/native_executor.py`:

- project-root confinement
- unsafe token blocking for shell operations
- bounded output and timeout controls

## 5. Debug Notes

If a tool call appears in output but is not executed:

1. Check validation warnings in `apiserver/agentic_tool_loop.py` logs.
2. Ensure `tool_name` and required arguments are present.
3. Verify model/tool schema alignment in request payload.

If the model emits non-structured tool syntax:

- the loop should reject it and request structured function-calling format.

## 6. Relevant Source Files

- `apiserver/llm_service.py`
- `apiserver/agentic_tool_loop.py`
- `apiserver/native_tools.py`
- `system/native_executor.py`