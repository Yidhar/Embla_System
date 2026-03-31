{
  "schema_version": "ws23-001-v1",
  "services": [
    {
      "service_name": "embla-main-headless",
      "command": [
        "python",
        "main.py",
        "--headless"
      ],
      "working_dir": ".",
      "restart_policy": "on-failure",
      "max_restarts": 5,
      "restart_backoff_seconds": 3.0,
      "lightweight_fallback_command": [
        "python",
        "main.py",
        "--lightweight"
      ]
    }
  ]
}
