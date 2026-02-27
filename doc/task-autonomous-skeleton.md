# Autonomous Skeleton Task Tracker

> 历史归档说明（M0-M1）：
> 本文档记录的是自治骨架早期实现过程，包含 CLI/Codex 路由等阶段性方案，不作为当前执行主链依据。
> 当前权威口径请以以下文档为准：
> - `doc/00-omni-operator-architecture.md`
> - `doc/task/25-subagent-development-fabric-status-matrix.md`
> - `doc/task/runbooks/subagent_runtime_native_bridge_sequence_and_gate_runbook.md`

Last updated: 2026-02-20
Owner: Codex
Scope: Bootstrap the `autonomous/` implementation skeleton and connect minimal runtime entry points.

## Task Status

- [x] Create `autonomous/` package structure.
- [x] Implement event log skeleton (`autonomous/event_log/event_store.py`).
- [x] Implement CLI adapter contracts and subprocess adapters.
- [x] Implement CLI selector and dispatcher skeleton.
- [x] Implement sensor/planner/evaluator skeleton.
- [x] Implement `SystemAgent` loop skeleton.
- [x] Add Codex MCP verification fallback adapter placeholder.
- [x] Add autonomous config model to `system/config.py`.
- [x] Add background startup hook in `main.py` (`_try_start_autonomous_agent`).
- [x] Add initial config template (`autonomous/config/autonomous_config.yaml`).
- [x] Add `config.json.example` autonomous section.
- [x] Add DoD baseline artifacts (`memory/`, `policy/`, `config/`, `runbooks/`, `scripts/dod_check.ps1`).
- [ ] Add full observability metrics/traces.
- [x] Add durable SQL event schema (`workflow_state/workflow_event/workflow_command/outbox/inbox`).
- [x] Add state machine persistence and transition guards (skeleton-level guards).
- [x] Add lease/fencing and warm-standby failover.
- [x] Add outbox async dispatcher + inbox de-dup consumer chain.
- [x] Add canary/release rollback automation chain.
- [x] Wire `dod_check.ps1` into CI.
- [x] Align system/tool prompts with autonomous lease/fencing + outbox + canary semantics.
- [ ] Add full gate policy enforcement before write/deploy.

## Progress Log

1. Created autonomous package and tooling skeleton files.
2. Added lightweight JSONL event store for autonomous events.
3. Added CLI adapters: Codex/Claude/Gemini plus selector and dispatcher.
4. Added evaluator and fallback invocation path for Codex MCP in verification stage.
5. Added config model (`autonomous`) and startup wiring in background service loop.
6. Added minimal tests for system agent config parsing.
7. Verified syntax compile for `autonomous/`, `system/config.py`, and `main.py`.
8. Added SQLite workflow store and schema (`autonomous/state/schema.sql`, `autonomous/state/workflow_store.py`).
9. Wired `SystemAgent` task execution to durable workflow transitions and command logs.
10. Added unit tests for workflow store state/outbox behavior.
11. Added DoD check script and baseline runbooks/policy/schema artifacts.
12. Executed `scripts/dod_check.ps1` successfully (passes on current workspace).
13. Executed one in-process `SystemAgent.run_cycle()` smoke run with dict config.
14. Fixed workflow bootstrap event insertion bug in `WorkflowStore.create_workflow()` (binding mismatch).
15. Refined `last_error` persistence rule: only failure-related transitions update error field.
16. Added lease/fencing persistence methods in `WorkflowStore` (`try_acquire_or_renew_lease`, `is_lease_owner`, `read_lease`).
17. Added inbox/outbox idempotent completion path (`is_inbox_processed`, `complete_outbox_for_consumer`).
18. Refactored `SystemAgent` to lease-aware single-active loop and fenced writes.
19. Added outbox async consumer in `SystemAgent`, wired `TaskApproved` to business handler.
20. Added release controller (`autonomous/release/controller.py`) for canary decision + rollback execution hook.
21. Updated workflow path to `ReleaseCandidate -> CanaryRunning -> Promoted/RolledBack`.
22. Extended autonomous config models with `lease`, `outbox_dispatch`, `release`.
23. Added CI workflow `.github/workflows/dod-check.yml`.
24. Re-ran verification: `py_compile` pass, `dod_check.ps1` pass, `SystemAgent.run_cycle()` smoke pass.
25. Fixed lease heartbeat gap: added background lease renewal loop so long cycle intervals and long tasks keep valid lease.
26. Added smoke verification for `lease/fencing` and `outbox -> canary -> promote` path.
27. Added smoke verification for `outbox -> canary -> rollback` path (auto_rollback disabled branch).
28. Updated prompt stack (`conversation_style_prompt`/`agentic_tool_prompt`/`conversation_analyzer_prompt`/`tool_dispatch_prompt`) to encode autonomous SDLC governance:
    - single-active lease/fencing write constraints
    - `ReleaseCandidate -> CanaryRunning -> Promoted/RolledBack` release semantics
    - outbox/inbox idempotent dispatch semantics
    - Codex MCP fallback limited to `Verifying` diagnosis path
29. Hardened LLM streaming reliability path in `apiserver/llm_service.py`:
    - classify `InternalServerError`-wrapped connection issues as retryable
    - apply backoff retry for transient streaming failures
    - sanitize LiteLLM noisy hints (`Provider List` / debug tips) from surfaced backend error text
30. Added agentic loop fail-fast guard in `apiserver/agentic_tool_loop.py`:
    - detect upstream terminal stream errors (`Streaming call error`, `auth_expired`, etc.)
    - stop loop immediately instead of entering no-tool retry/repair path
31. Added LiteLLM provider-noise hardening:
    - explicit `custom_llm_provider` inference in `apiserver/llm_service.py` and `agentserver/task_scheduler.py`
    - openai-compatible model name normalization defaults to `openai/` prefix
    - global logging/environment suppression for LiteLLM noisy provider hints (`system/logging_setup.py`, `system/config.py`)
32. Wired external MCP dispatch fallback into `mcpserver/mcp_manager.py`:
    - unresolved services now fallback to `~/.mcporter/config.json` via `mcporter call`
    - supports `codex-cli <-> codex-mcp` alias resolution for `@cexll/codex-mcp-server`
    - normalizes `ask-codex` payload (`message -> prompt`) and returns structured JSON result envelope
33. Verified external Codex MCP execution in runtime environment (`uv run`):
    - `unified_call("codex-cli", {"tool_name":"ping"})` returns resolved `codex-mcp` + `Pong!`
    - `unified_call("codex-cli", {"tool_name":"ask-codex", ...})` returns expected model response
    - `scripts/dod_check.ps1` still passes after integration
34. Removed AgentServer/Agent auto-start from backend bootstrap path (`main.py`):
    - `ServiceManager.start_all_servers()` now starts API/MCP/TTS only
    - startup plan marks `Agent(AgentServer)` as disabled instead of spawning thread
    - `kill_port_occupiers()` no longer force-kills `agent_server` port owners
35. Added one-click backend API for Codex MCP bootstrap in `apiserver/api_server.py`:
    - new endpoint `POST /mcp/codex/setup` auto-writes `codex-cli` (and optional aliases) to `~/.mcporter/config.json`
    - supports optional global install mode (`npm install -g @cexll/codex-mcp-server`) or default `npx` mode
    - includes built-in connectivity validation (`ping`, optional `ask-codex`) and structured diagnostics for frontend display
36. Verified new setup endpoint flow with runtime call:
    - request `install_mode=npx, write_compat_aliases=true, validate_connection=true` returned `status=success`
    - wrote both `codex-cli` and `codex-mcp`, and `ping` validation passed
    - `scripts/dod_check.ps1` still passes after API integration
37. Completed frontend UI closure for Codex MCP one-click setup:
    - added `setupCodexMcp()` API method/types in `frontend/src/api/core.ts`
    - wired `SkillView` MCP panel with one-click button, in-place progress/status, ping result and warnings display
    - verified frontend build (`cd frontend && npm run build`) passes
38. Switched coding-task routing policy to Codex-first (prompt + runtime chain):
    - updated prompt stack (`agentic_tool_prompt` / `tool_dispatch_prompt` / `conversation_analyzer_prompt` / `conversation_style_prompt`) to treat `codex-cli/ask-codex` as primary coding execution path
    - removed previous "Codex only verifying fallback" wording and replaced with "coding mainline + read-only for diagnosis-only cases"
39. Hardened coding tool call chain for Codex dispatch:
    - `apiserver/agentic_tool_loop.py`: auto-resolve missing `service_name` to `codex-cli` for codex tool names and inject default `workspace-write + on-failure` for `ask-codex`
    - `system/background_analyzer.py`: same codex default routing when planner emits MCP calls without `service_name`
    - `mcpserver/mcp_manager.py`: support nested `arguments` merge + default codex execution params for external mcporter calls
40. Changed autonomous CLI default execution target to Codex:
    - `system/config.py`, `autonomous/system_agent.py`, `autonomous/dispatcher.py`, `autonomous/tools/cli_selector.py`, `autonomous/config/autonomous_config.yaml`, `config.json.example`
    - defaults now `preferred=codex`, fallback `claude -> gemini`
41. Verification for Codex-first chain:
    - py_compile passed on updated routing/config modules
    - runtime smoke passed: `_execute_mcp_call({"tool_name":"ask-codex","message":"..."})` auto-routed to `codex-cli` and returned model output
    - `uv run python -m pytest autonomous/tests/test_system_agent_config.py -q` passed
    - `scripts/dod_check.ps1` passed
42. Fixed tools loop no-tool completion semantics in `apiserver/agentic_tool_loop.py`:
    - added explicit completion marker detection (`不需要工具`) for immediate loop termination
    - when explicit marker is present, stop loop directly without injecting no-tool correction feedback
    - changed round content handling to buffered-per-round emission so no-tool correction retries can drop current-round text (effectively return n-1 round output)
43. Added tools-loop model output observability:
    - `apiserver/agentic_tool_loop.py` emits per-round `model_output` SSE event
    - `frontend/src/utils/encoding.ts` adds `model_output` stream chunk type
    - `frontend/src/views/MessageView.vue` renders loop model output info (focus on placeholder/no-content rounds)
44. Added `{End}` loop-termination protocol with safe output truncation:
    - loop now matches `{End}` (case-insensitive, supports inner spaces) and terminates immediately with `stop_reason=end_marker`
    - buffered content replay supports `content_cutoff`, truncating marker and trailing text before forwarding to frontend
    - ensures frontend正文不显示 `{End}` 结构
45. Validation for this round:
    - `python -m py_compile apiserver/agentic_tool_loop.py` passed
    - `cd frontend && npm run build` still blocked by pre-existing type issue in `frontend/src/components/LoginDialog.vue` (`accessToken` mismatch), unrelated to this change
46. Removed AgentServer call guidance from prompt stack:
    - `system/prompts/agentic_tool_prompt.txt` removed `AgentServer_call` callable/function guidance
    - `system/prompts/tool_dispatch_prompt.txt` removed AgentServer coexistence/priority rules
    - `system/prompts/conversation_analyzer_prompt.txt` removed AgentServer output schema and all AgentServer-specific dispatch rules
    - prompt policy now routes external/network capabilities via `mcp` services or native tools only
47. Prompt verification for this round:
    - `rg -n "(?i)AgentServer" system/prompts -S` returned no matches
48. Added codex-first runtime routing guard for coding tasks:
    - `apiserver/agentic_tool_loop.py` now detects coding requests and uses `tool_choice=required` until codex tool is engaged.
    - mutating native calls (`write_file`, `git_checkout_file`) are blocked before first codex call and replaced with forced `codex-cli/ask-codex`.
    - no-tool retry feedback now explicitly requires `mcp_call` to `codex-cli/ask-codex` for coding tasks.
49. Aligned background analyzer with codex-first coding policy:
    - `system/background_analyzer.py` adds coding-intent route enforcement (`_enforce_coding_codex_route`).
    - when coding intent is detected and codex call is missing, analyzer auto-injects `ask-codex` with `workspace-write + on-failure`.
    - mutating native calls are removed from analyzer output before codex engagement.
50. Hardened Codex MCP routing/reliability and observability:
    - `mcpserver/mcp_manager.py` now performs local-first route with codex-specific local-fail -> mcporter degrade path.
    - `ask-codex` payload is normalized before dispatch (`message/arguments.message -> prompt`) to avoid `prompt: Required`.
    - codex external route prefers registered `codex-cli` service, then alias fallback (`codex-mcp`).
    - added per-call route/status/result logging (start, route selection, fallback, completion/error, preview details).
    - `apiserver/agentic_tool_loop.py` now marks MCP JSON `status=error` as tool failure (instead of false success), and logs per attempt.
    - `system/background_analyzer.py` now logs MCP call start/finish/status details and normalizes `ask-codex` prompt payload.

## Not Yet Implemented (Known Gaps)

1. Real-time monitor with stall detection extensions (`poll_interval`, `stall_threshold`, adaptive patience) is only skeleton-level.
2. One-click Codex MCP bootstrap is available end-to-end; remaining work is optional UX polish (richer diagnostics/advanced options in UI).
3. Canary decision currently uses policy + supplied/synthetic windows; no live metrics adapter yet.
4. Rollback command execution is optional and currently shell-command based.
5. No security scanner for tool output injection yet.
6. Verification coverage gaps:
   - only focused tests/smokes were run; no full repository regression test suite execution yet.
7. Repository `.gitignore` currently ignores `*.md`, so new markdown artifacts (including this tracker and runbooks) are local-only unless ignore rules are adjusted.

## Next Suggested Steps

1. Add live canary metrics provider (replace synthetic window fallback).
2. Add explicit gate enforcement for `write_repo/deploy/secrets` against `policy/gate_policy.yaml`.
3. Add MCP availability probe + fallback error taxonomy.
4. Add observability counters for lease ownership churn, outbox lag, and rollback rate.
