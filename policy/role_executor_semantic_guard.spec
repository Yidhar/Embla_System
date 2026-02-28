{
  "schema_version": "ws28-role-executor-semantic-guard-v1",
  "defaults": {
    "strict_semantic_guard": true
  },
  "roles": {
    "frontend": {
      "allowed_semantic_toolchains": [
        "frontend",
        "docs",
        "config",
        "test_frontend"
      ]
    },
    "backend": {
      "allowed_semantic_toolchains": [
        "backend",
        "docs",
        "config",
        "test_backend",
        "ops"
      ]
    },
    "ops": {
      "allowed_semantic_toolchains": [
        "ops",
        "docs",
        "config",
        "test_ops"
      ]
    }
  },
  "change_control": {
    "schema_version": "ws28-role-executor-semantic-guard-change-control-v1",
    "approval_ticket_required": true,
    "audit_ledger": "doc/task/reports/role_executor_semantic_guard_change_ledger_ws28_021.jsonl",
    "acl": {
      "owners": [
        "AG-PH3-BS-01"
      ],
      "approvers": [
        "release-owner",
        "security-reviewer"
      ],
      "min_approvals": 1
    }
  }
}
