"""NativeExecutor security guard tests (WS14 runtime hardening)."""

from __future__ import annotations

import asyncio

import pytest

from system.killswitch_guard import (
    build_oob_health_probe_plan,
    validate_oob_health_probe_plan,
)
from system.native_executor import NativeExecutor, NativeSecurityError


@pytest.mark.parametrize(
    "command",
    [
        'python -c "print(1)"',
        "python3 -c 'print(1)'",
        "bash -c 'echo ok'",
        "sh -c 'echo ok'",
        "node -e \"console.log(1)\"",
        "powershell -EncodedCommand AAAA",
        "pwsh -enc AAAA",
        'echo "cm0gLXJmIC8=" | base64 -d | sh',
        "nohup python app.py &",
        "setsid python app.py",
        "docker run -d alpine sleep 60",
        "start /b cmd /c echo ok",
        "rm -rf .",
        "del /f /s *",
        "erase /f /s *",
        "rmdir /s /q .",
        "format C:",
        "diskpart /s script.txt",
        "type ..\\secret.txt",
        "cat ../secret.txt",
        "iptables -A OUTPUT -j DROP",
    ],
)
def test_malicious_payloads_are_blocked(command: str):
    ex = NativeExecutor()
    assert ex.is_safe_command(command) is False


def test_killswitch_marker_allows_oob_freeze_plan_preview():
    ex = NativeExecutor()
    safe_cmd = "iptables -A OUTPUT -j DROP # OOB_ALLOWLIST_ENFORCED"
    # This test only checks KillSwitch-specific guard behavior.
    # Other policy layers may still block execution in full runtime.
    assert ex.is_safe_command(safe_cmd) is True


def test_argv_interpreter_gate_blocks_python_c():
    ex = NativeExecutor()
    with pytest.raises(NativeSecurityError):
        asyncio.run(ex.run(["python", "-c", "print(1)"]))


def test_argv_interpreter_gate_blocks_node_e():
    ex = NativeExecutor()
    with pytest.raises(NativeSecurityError):
        asyncio.run(ex.run(["node", "-e", "console.log(1)"]))


def test_argv_detached_guard_blocks_docker_detached():
    ex = NativeExecutor()
    with pytest.raises(NativeSecurityError):
        asyncio.run(ex.run(["docker", "run", "-d", "alpine", "sleep", "10"]))


def test_safe_command_still_allowed():
    ex = NativeExecutor()
    assert ex.is_safe_command("echo hello") is True


def test_execute_shell_echo_runs_cross_platform():
    ex = NativeExecutor()
    result = asyncio.run(ex.execute_shell("echo native-executor-smoke"))
    assert result.returncode == 0
    assert "native-executor-smoke" in result.stdout.lower()


def test_execute_shell_recovers_timeout_race_when_process_already_exited(monkeypatch):
    ex = NativeExecutor()

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 90001
            self.returncode = 0
            self.kill_called = False

        async def wait(self):
            return self.returncode

        async def communicate(self):
            return b"native-timeout-race\n", b""

        def kill(self) -> None:
            self.kill_called = True

    fake_process = _FakeProcess()

    async def _fake_create_subprocess_exec(*args, **kwargs):  # noqa: ARG001
        return fake_process

    async def _fake_wait_for(awaitable, timeout):  # noqa: ARG001
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("system.native_executor.asyncio.create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr("system.native_executor.asyncio.wait_for", _fake_wait_for)

    result = asyncio.run(ex.execute_shell("echo native-timeout-race"))
    assert result.returncode == 0
    assert "native-timeout-race" in result.stdout
    assert fake_process.kill_called is False


def test_execute_shell_timeout_still_raises_when_process_not_exited(monkeypatch):
    ex = NativeExecutor()

    class _FakeProcess:
        def __init__(self) -> None:
            self.pid = 90002
            self.returncode = None
            self.kill_called = False

        async def wait(self):
            return self.returncode

        async def communicate(self):
            self.returncode = -9
            return b"", b""

        def kill(self) -> None:
            self.kill_called = True

    fake_process = _FakeProcess()

    async def _fake_create_subprocess_exec(*args, **kwargs):  # noqa: ARG001
        return fake_process

    async def _fake_wait_for(awaitable, timeout):  # noqa: ARG001
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("system.native_executor.asyncio.create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr("system.native_executor.asyncio.wait_for", _fake_wait_for)

    with pytest.raises(TimeoutError):
        asyncio.run(ex.execute_shell("echo timeout-hard-fail"))
    assert fake_process.kill_called is True


def test_oob_health_probe_plan_valid_with_marker_and_allowlist():
    plan = build_oob_health_probe_plan(
        oob_allowlist=["10.0.0.0/24", "bastion.example.com"],
        probe_targets=["10.0.0.10", "bastion.example.com"],
    )
    ok, reason = validate_oob_health_probe_plan(
        oob_allowlist=plan.oob_allowlist,
        probe_targets=["10.0.0.10", "bastion.example.com"],
        commands=plan.commands,
    )
    assert ok is True
    assert reason == "ok"


def test_oob_health_probe_plan_rejects_missing_marker():
    plan = build_oob_health_probe_plan(
        oob_allowlist=["10.0.0.0/24"],
        probe_targets=["10.0.0.25"],
    )
    commands_without_marker = [c for c in plan.commands if "OOB_ALLOWLIST_ENFORCED" not in c]

    ok, reason = validate_oob_health_probe_plan(
        oob_allowlist=plan.oob_allowlist,
        probe_targets=["10.0.0.25"],
        commands=commands_without_marker,
    )
    assert ok is False
    assert "marker" in reason.lower()


def test_oob_health_probe_plan_rejects_probe_target_outside_allowlist():
    with pytest.raises(ValueError, match="not covered by oob_allowlist"):
        build_oob_health_probe_plan(
            oob_allowlist=["10.0.0.0/24"],
            probe_targets=["198.51.100.10"],
        )
