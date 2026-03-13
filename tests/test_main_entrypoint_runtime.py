from __future__ import annotations

import socket
import threading

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
    monkeypatch.setattr(runtime, "shutdown_services", lambda: calls.append("shutdown_services"))

    assert runtime.run() == 0
    assert calls == [
        "ensure_event_loop",
        "initialize_services",
        "install_signal_handlers",
        "run_supervision_loop",
        "shutdown_services",
    ]


def test_embla_runtime_run_shuts_down_services_when_initialization_fails(monkeypatch) -> None:
    runtime = main_module.EmblaRuntime(main_module.StartupOptions(headless=True))
    calls: list[str] = []

    monkeypatch.setattr(runtime, "run_diagnostic", lambda: None)
    monkeypatch.setattr(runtime, "run_startup_gate", lambda: True)
    monkeypatch.setattr(main_module, "_ensure_event_loop", lambda: calls.append("ensure_event_loop"))

    def _raise() -> None:
        calls.append("initialize_services")
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "initialize_services", _raise)
    monkeypatch.setattr(runtime, "shutdown_services", lambda: calls.append("shutdown_services"))

    assert runtime.run() == 1
    assert calls == ["ensure_event_loop", "initialize_services", "shutdown_services"]


def test_embla_runtime_detects_unexpected_api_exit() -> None:
    runtime = main_module.EmblaRuntime(main_module.StartupOptions(headless=True))
    handle = main_module.APIServerHandle(
        thread=threading.Thread(),
        server=object(),
        host="127.0.0.1",
        port=8000,
        stopped_event=threading.Event(),
        shutdown_requested=threading.Event(),
        startup_complete=True,
    )
    handle.stopped_event.set()
    runtime.services.api_server = handle

    assert runtime._should_stop_supervision() is True
    assert runtime.stop_event.is_set() is True
    assert runtime._exit_code == 1


def test_can_bind_tcp_port_sets_reuseaddr_before_bind(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def setsockopt(self, level, option, value):
            events.append(("setsockopt", (level, option, value)))

        def bind(self, sockaddr):
            events.append(("bind", sockaddr))

    monkeypatch.setattr(
        main_module,
        "_iter_tcp_addresses",
        lambda host, port, passive=False: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (host, port))],
    )
    monkeypatch.setattr(main_module.socket, "socket", lambda *args, **kwargs: _FakeSocket())

    assert main_module._can_bind_tcp_port("127.0.0.1", 8000) is True
    assert events[0] == ("setsockopt", (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1))
    assert events[1] == ("bind", ("127.0.0.1", 8000))


def test_shutdown_services_clears_handle_after_port_release(monkeypatch) -> None:
    runtime = main_module.EmblaRuntime(main_module.StartupOptions(headless=True))
    thread = threading.Thread()
    released_calls: list[tuple[str, int, float]] = []
    flags: list[tuple[str, object]] = []
    cleanup_calls: list[str] = []

    class _Server:
        should_exit = False
        force_exit = False

    handle = main_module.APIServerHandle(
        thread=thread,
        server=_Server(),
        host="127.0.0.1",
        port=8000,
        stopped_event=threading.Event(),
        shutdown_requested=threading.Event(),
        startup_complete=True,
    )
    runtime.services.api_server = handle
    runtime.services.api_started = True

    monkeypatch.setattr(
        thread,
        "join",
        lambda timeout=None: flags.append(("join", timeout)),
    )
    monkeypatch.setattr(
        thread,
        "is_alive",
        lambda: False,
    )
    monkeypatch.setattr(
        main_module,
        "_wait_for_tcp_release",
        lambda host, port, timeout_seconds=3.0: released_calls.append((host, port, timeout_seconds)) or True,
    )
    monkeypatch.setattr(
        main_module,
        "close_runtime_network_clients_sync",
        lambda: cleanup_calls.append("close_runtime_network_clients_sync") or {
            "litellm": {"attempted": True, "closed": True, "error": ""},
            "mcp_pool": {"attempted": True, "closed": True, "error": ""},
        },
    )

    runtime.shutdown_services()

    assert handle.shutdown_requested.is_set() is True
    assert getattr(handle.server, "should_exit") is True
    assert flags == []
    assert released_calls == [("127.0.0.1", 8000, 2.0)]
    assert cleanup_calls == ["close_runtime_network_clients_sync"]
    assert runtime.services.api_server is None
    assert runtime.services.api_started is False
