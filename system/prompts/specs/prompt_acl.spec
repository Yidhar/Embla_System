{
  // Prompt ACL enforcement mode:
  // - "block": reject disallowed writes
  // - "shadow": allow writes but emit deny decision for audit
  "enforcement_mode": "block",
  "rules": [
    {
      "path_pattern": "immutable_dna_manifest.spec",
      "level": "S0_LOCKED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "dna/shell_persona.md",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "dna/core_values.md",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "core/dna/conversation_style_prompt.md",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "core/routing/conversation_analyzer_prompt.md",
      "level": "S2_FLEXIBLE",
      "require_ticket": false,
      "require_manifest_refresh": false,
      "require_gate_verify": false,
      "allow_ai_direct_write": true
    },
    {
      "path_pattern": "core/routing/tool_dispatch_prompt.md",
      "level": "S2_FLEXIBLE",
      "require_ticket": false,
      "require_manifest_refresh": false,
      "require_gate_verify": false,
      "allow_ai_direct_write": true
    },
    {
      "path_pattern": "core/dna/agentic_tool_prompt.md",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "*.md",
      "level": "S2_FLEXIBLE",
      "require_ticket": false,
      "require_manifest_refresh": false,
      "require_gate_verify": false,
      "allow_ai_direct_write": true
    }
  ]
}
