{
  "schema_version": "ws31-agent-profile-v1",
  "profiles": [
    {
      "agent_type": "expert_default",
      "role": "expert",
      "label": "Default Expert",
      "description": "Fallback expert profile used when no explicit agent_type is provided.",
      "prompt_blocks": [],
      "tool_profile": "",
      "tool_subset": [],
      "enabled": true,
      "default_for_role": true,
      "builtin": true,
      "prompts_root": "system/prompts"
    },
    {
      "agent_type": "dev_default",
      "role": "dev",
      "label": "Default Dev",
      "description": "Fallback dev profile used when no explicit agent_type is provided.",
      "prompt_blocks": [],
      "tool_profile": "",
      "tool_subset": [],
      "enabled": true,
      "default_for_role": true,
      "builtin": true,
      "prompts_root": "system/prompts"
    },
    {
      "agent_type": "code_reviewer",
      "role": "review",
      "label": "Code Reviewer",
      "description": "Independent review agent preset with the canonical code-review prompt block.",
      "prompt_blocks": ["agents/review/code_reviewer.md"],
      "tool_profile": "review",
      "tool_subset": [],
      "enabled": true,
      "default_for_role": true,
      "builtin": true,
      "prompts_root": "system/prompts"
    }
  ]
}
