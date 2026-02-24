from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_build_win_module():
    script_path = Path("scripts/build-win.py")
    spec = importlib.util.spec_from_file_location("build_win_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_win_parse_args_phase3_closure_flags(monkeypatch) -> None:
    module = _load_build_win_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build-win.py",
            "--phase3-closure",
            "--phase3-closure-output",
            "scratch/reports/custom_chain_report.json",
            "--phase3-closure-timeout-seconds",
            "120",
        ],
    )

    args = module.parse_args()
    assert args.phase3_closure is True
    assert str(args.phase3_closure_output).replace("\\", "/").endswith("scratch/reports/custom_chain_report.json")
    assert int(args.phase3_closure_timeout_seconds) == 120


def test_build_win_phase3_closure_gate_invokes_chain_script(monkeypatch) -> None:
    module = _load_build_win_module()
    calls: list[dict[str, object]] = []

    def _fake_run(cmd, cwd=None, env=None, check=True):
        calls.append(
            {
                "cmd": list(cmd),
                "cwd": str(cwd).replace("\\", "/") if cwd else "",
                "check": bool(check),
            }
        )
        return None

    monkeypatch.setattr(module, "run", _fake_run)
    monkeypatch.setattr(module, "PHASE3_CLOSURE_SCRIPT", Path("scripts/release_phase3_closure_chain_ws22_004.py"))

    output_path = Path("scratch/reports/ws22_chain_from_build_win.json")
    module.run_phase3_closure_chain(output_file=output_path, timeout_seconds=10)

    assert len(calls) == 1
    command = calls[0]["cmd"]
    assert command[0] == sys.executable
    assert str(command[1]).replace("\\", "/").endswith("scripts/release_phase3_closure_chain_ws22_004.py")
    assert "--timeout-seconds" in command
    assert "30" in command  # clamped to minimal timeout
    assert "--output" in command
    assert str(output_path).replace("\\", "/") in [str(item).replace("\\", "/") for item in command]
