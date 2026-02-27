from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from scripts.run_ws28_plugin_worker_real_mcp_smoke_ws28_023 import main


def _make_case_root(prefix: str) -> Path:
    root = Path("scratch") / prefix / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup_case_root(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_run_ws28_plugin_worker_real_mcp_smoke_cli_main(monkeypatch) -> None:
    case_root = _make_case_root("test_run_ws28_plugin_worker_real_mcp_smoke_ws28_023")
    try:
        source_dir = case_root / "source_agent"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "fake_plugin_agent.py").write_text(
            """
import json

class FakePluginAgent:
    async def handle_handoff(self, task):
        return json.dumps(
            {
                "status": "ok",
                "tool_name": str(task.get("tool_name") or ""),
                "route": "fake_plugin_agent",
            },
            ensure_ascii=False,
        )
""".strip(),
            encoding="utf-8",
        )
        source_manifest = source_dir / "agent-manifest.json"
        source_manifest.write_text(
            json.dumps(
                {
                    "name": "fake_builtin_mcp",
                    "displayName": "Fake Builtin MCP",
                    "agentType": "mcp",
                    "entryPoint": {
                        "module": "fake_plugin_agent",
                        "class": "FakePluginAgent",
                    },
                    "capabilities": {
                        "invocationCommands": [{"command": "fake_ping"}],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        output = case_root / "ws28_023_report.json"
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath_value = str(source_dir.resolve())
        if existing_pythonpath.strip():
            pythonpath_value = f"{pythonpath_value}{os.pathsep}{existing_pythonpath}"
        monkeypatch.setenv("PYTHONPATH", pythonpath_value)
        monkeypatch.setattr(
            "sys.argv",
            [
                "run_ws28_plugin_worker_real_mcp_smoke_ws28_023.py",
                "--repo-root",
                ".",
                "--agent-manifest",
                str(source_manifest),
                "--invoke-payload",
                "{\"tool_name\":\"fake_ping\"}",
                "--output",
                str(output),
                "--strict",
            ],
        )

        exit_code = main()
        assert exit_code == 0
        assert output.exists() is True
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["passed"] is True
        assert payload["checks"]["service_is_plugin_worker_proxy"] is True
        assert payload["checks"]["invocation_not_worker_failure"] is True
    finally:
        _cleanup_case_root(case_root)
