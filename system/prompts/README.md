# Embla System Prompt Layout

This directory stores runtime prompt assets and governance specs.

## Canonical layout

- `dna/*.md`
  Agent identity DNA for Shell/Core orchestration agents.
- `core/dna/conversation_style_prompt.md`
  Global conversation composition DNA (locked).
- `core/dna/agentic_tool_prompt.md`
  Global tool-calling contract DNA (locked).
- `core/routing/conversation_analyzer_prompt.md`
  Route analysis prompt (editable).
- `core/routing/tool_dispatch_prompt.md`
  Tool dispatch prompt (editable).
- `agents/shell/*.md`
  Shell read-only / delegate profile prompt blocks.
- `agents/shell/blocks/*.md`
  Shell 路由契约、只读边界与升级策略的原子 prompt 块。
- `agents/core_exec/*.md`
  Core execution profile prompt blocks.
- `agents/core_exec/blocks/*.md`
  Core 编排职责等原子 runtime 规则块。
- `roles/*.md`, `skills/*.md`, `styles/*.md`, `rules/*.md`
  Generic atomic prompt blocks for expert roles, reusable skills and conventions.
- `agents/dev/*.md`
  Dev 自检与上报规则块。
- `agents/review/*.md`
  Review 审查规则与结果 contract。
- `agents/experts/` and `agents/recovery/`
  Reserved namespaces for expert/recovery prompt blocks.
- `specs/prompt_registry.spec`
  Prompt registry and aliases.
- `specs/prompt_acl.spec`
  Prompt write ACL policy (canonical location).

## DNA/Governance files

- `immutable_dna_manifest.spec`
  SHA-256 manifest for locked DNA files, including runtime-injected DNA and agent identity DNA.
- `immutable_dna_audit.jsonl`
  Historical audit file (legacy location; runtime audit is moving to `scratch/runtime/`).

## Governance notes

- Prompt governance specs are loaded only from `specs/prompt_registry.spec` and `specs/prompt_acl.spec`.
- Prompt list APIs are registry-driven first, then recursive scan fallback for unregistered files.
- 原子 prompt 块也应登记到 `specs/prompt_registry.spec`，否则前端按名称读取时无法稳定命中。
- 旧的仓库根 `prompts/` 已退役；runtime prompt 资产统一收敛到 `system/prompts/`。
