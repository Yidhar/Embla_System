from __future__ import annotations

import main as main_module


def test_embla_runtime_run_short_circuits_on_diagnostic(monkeypatch) -> None:
    runtime = main_module.EmblaRuntime(main_module.StartupOptions(check_env=True, headless=True))
    monkeypatch.setattr(runtime, "run_diagnostic", lambda: 7)
    monkeypatch.setattr(runtime, "run_startup_gate", lambda: (_ for _ in ()).throw(AssertionError("should not run")))

    assert runtime.run() == 7


def test_embla_runtime_run_executes_default_startup_flow(monkeypatch) -> None:
    runtime = main_module.EmblaRuntime(main_module.StartupOptions(headless=True))
    calls: list[str] = []

    monkeypatch.setattr(runtime, "run_diagnostic", lambda: None)
    monkeypatch.setattr(runtime, "run_startup_gate", lambda: True)
    monkeypatch.setattr(main_module, "_ensure_event_loop", lambda: calls.append("ensure_event_loop"))
    monkeypatch.setattr(runtime, "initialize_services", lambda: calls.append("initialize_services"))
    monkeypatch.setattr(runtime, "install_signal_handlers", lambda: calls.append("install_signal_handlers"))
    monkeypatch.setattr(runtime, "run_supervision_loop", lambda: calls.append("run_supervision_loop"))

    assert runtime.run() == 0
    assert calls == [
        "ensure_event_loop",
        "initialize_services",
        "install_signal_handlers",
        "run_supervision_loop",
    ]
