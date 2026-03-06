# Embla System Prompt Layout

This directory stores runtime prompt assets and governance specs.

## Canonical layout

- `core/dna/conversation_style_prompt.md`
  Shell chat style DNA (locked).
- `core/dna/agentic_tool_prompt.md`
  Core execution DNA (locked).
- `core/routing/conversation_analyzer_prompt.md`
  Route analysis prompt (editable).
- `core/routing/tool_dispatch_prompt.md`
  Tool dispatch prompt (editable).
- `agents/shell/*.md`
  Shell read-only / delegate profile prompt blocks.
- `agents/core_exec/*.md`
  Core execution profile prompt blocks.
- `agents/experts/` and `agents/recovery/`
  Reserved namespaces for expert/recovery prompt blocks.
- `specs/prompt_registry.spec`
  Prompt registry and aliases.
- `specs/prompt_acl.spec`
  Prompt write ACL policy (canonical location).

## DNA/Governance files

- `immutable_dna_manifest.spec`
  SHA-256 manifest for locked DNA files.
- `immutable_dna_audit.jsonl`
  Historical audit file (legacy location; runtime audit is moving to `scratch/runtime/`).

## Compatibility notes

- ACL loader now prefers `specs/prompt_acl.spec`.
- `prompt_acl.spec` at prompt root is treated as legacy fallback for compatibility only.
- Prompt list APIs are registry-driven first, then recursive scan fallback for unregistered files.
