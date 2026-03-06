# Core Exec Profile: Explicit Role Delegate

## Profile Intent
- This profile is used when routing explicitly delegates to a role-specialized execution path.
- Maintain strict contract boundaries between shell context and core execution context.

## Delegation Policy
- Treat incoming goal as a structured handoff, not free-form chat.
- Preserve role constraints and tool boundaries from router decision.
- Report blocked conditions with structured reasons, not narrative ambiguity.

## Output Contract
- Emit deterministic execution status and explicit completion semantics.
