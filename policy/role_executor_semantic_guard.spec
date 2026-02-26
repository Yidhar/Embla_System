{
  "schema_version": "ws28-role-executor-semantic-guard-v1",
  "defaults": {
    "strict_semantic_guard": false
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
  }
}
