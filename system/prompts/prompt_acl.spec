{
  // Prompt ACL enforcement mode:
  // - "block": reject disallowed writes
  // - "shadow": allow writes but emit deny decision for audit
  "enforcement_mode": "block",
  "rules": [
    {
      "path_pattern": "immutable_dna_manifest.txt",
      "level": "S0_LOCKED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "conversation_style_prompt.txt",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "conversation_analyzer_prompt.txt",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "tool_dispatch_prompt.txt",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "agentic_tool_prompt.txt",
      "level": "S1_CONTROLLED",
      "require_ticket": true,
      "require_manifest_refresh": true,
      "require_gate_verify": true,
      "allow_ai_direct_write": false
    },
    {
      "path_pattern": "*.txt",
      "level": "S2_FLEXIBLE",
      "require_ticket": false,
      "require_manifest_refresh": false,
      "require_gate_verify": false,
      "allow_ai_direct_write": true
    }
  ]
}
