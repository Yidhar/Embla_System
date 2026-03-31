from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "health_probe.py"


@dataclass(frozen=True)
class _ResponseConfig:
    body: bytes
    status_code: int = 200
    content_type: str = "application/json; charset=utf-8"
    delay_seconds: float = 0.0


class _HealthProbeHandler(BaseHTTPRequestHandler):
    response_map: dict[str, _ResponseConfig] = {
        "/health": _ResponseConfig(body=b'{"status":"healthy","timestamp":"2026-01-01T00:00:00Z"}'),
    }
    seen_paths: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen_paths.append(self.path)
        config = type(self).response_map.get(
            self.path,
            _ResponseConfig(body=b'{"status":"not_found","timestamp":"2026-01-01T00:00:00Z"}', status_code=404),
        )
        if config.delay_seconds:
            time.sleep(config.delay_seconds)
        self.send_response(config.status_code)
        self.send_header("Content-Type", config.content_type)
        self.send_header("Content-Length", str(len(config.body)))
        self.end_headers()
        try:
            self.wfile.write(config.body)
        except BrokenPipeError:
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        return


@dataclass
class _TestServer:
    server: ThreadingHTTPServer
    thread: threading.Thread
    url: str
    handler_cls: type[_HealthProbeHandler]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _start_server(response_map: dict[str, _ResponseConfig]) -> _TestServer:
    class Handler(_HealthProbeHandler):
        pass

    Handler.response_map = response_map
    Handler.seen_paths = []

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    server = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _TestServer(server=server, thread=thread, url=f"http://{host}:{port}", handler_cls=Handler)


def _run_probe(url: str, timeout: float = 1.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--url", url, "--timeout", str(timeout)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _unused_url() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()
    return f"http://{host}:{port}"


def test_health_probe_appends_health_path_and_reports_healthy_json() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(body=json.dumps({"status": "healthy", "timestamp": "2026-01-01T00:00:00Z"}).encode()),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 0
    assert result.stderr == ""
    assert "healthy" in result.stdout
    assert "http_status=200" in result.stdout
    assert "status=healthy" in result.stdout
    assert "timestamp=2026-01-01T00:00:00Z" in result.stdout
    assert f"url={server.url}/health" in result.stdout
    assert server.handler_cls.seen_paths == ["/health"]


def test_health_probe_keeps_explicit_health_path() -> None:
    server = _start_server(
        {
            "/ready/health": _ResponseConfig(
                body=json.dumps({"status": "healthy", "timestamp": "2026-01-01T00:00:00Z"}).encode()
            ),
        }
    )
    try:
        result = _run_probe(f"{server.url}/ready/health")
    finally:
        server.close()

    assert result.returncode == 0
    assert server.handler_cls.seen_paths == ["/ready/health"]
    assert f"url={server.url}/ready/health" in result.stdout


def test_health_probe_returns_unhealthy_for_unhealthy_json_status() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(body=json.dumps({"status": "degraded", "timestamp": "2026-01-01T00:00:00Z"}).encode()),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 1
    assert "unhealthy" in result.stdout
    assert "status=degraded" in result.stdout
    assert "timestamp=2026-01-01T00:00:00Z" in result.stdout
    assert "detail=status is not healthy" in result.stdout
    assert result.stderr == ""


def test_health_probe_returns_parse_failure_for_malformed_json() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(body=b"not-json", content_type="application/json; charset=utf-8"),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unhealthy" in result.stderr
    assert "status=unknown" in result.stderr
    assert "timestamp=n/a" in result.stderr
    assert "parse failed:" in result.stderr


def test_health_probe_returns_parse_failure_for_missing_timestamp() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(body=json.dumps({"status": "healthy"}).encode()),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 1
    assert result.stdout == ""
    assert "parse failed:" in result.stderr
    assert "timestamp" in result.stderr


def test_health_probe_returns_request_failure_for_connection_error() -> None:
    result = _run_probe(_unused_url(), timeout=0.2)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unhealthy" in result.stderr
    assert "status=unknown" in result.stderr
    assert "timestamp=n/a" in result.stderr
    assert "request failed:" in result.stderr


def test_health_probe_returns_request_failure_for_timeout() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(
                body=json.dumps({"status": "healthy", "timestamp": "2026-01-01T00:00:00Z"}).encode(),
                delay_seconds=0.2,
            ),
        }
    )
    try:
        result = _run_probe(server.url, timeout=0.05)
    finally:
        server.close()

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unhealthy" in result.stderr
    assert "status=unknown" in result.stderr
    assert "timestamp=n/a" in result.stderr
    assert "request failed:" in result.stderr
    assert "timed out" in result.stderr


def test_health_probe_preserves_parsed_status_and_timestamp_for_http_error_response() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(
                body=json.dumps({"status": "degraded", "timestamp": "2026-01-01T00:00:00Z"}).encode(),
                status_code=503,
            ),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unhealthy" in result.stderr
    assert "http_status=503" in result.stderr
    assert "status=degraded" in result.stderr
    assert "timestamp=2026-01-01T00:00:00Z" in result.stderr
    assert "request failed:" in result.stderr


def test_health_probe_returns_parse_failure_for_unknown_charset() -> None:
    server = _start_server(
        {
            "/health": _ResponseConfig(
                body=json.dumps({"status": "healthy", "timestamp": "2026-01-01T00:00:00Z"}).encode(),
                content_type="application/json; charset=not-a-real-charset",
            ),
        }
    )
    try:
        result = _run_probe(server.url)
    finally:
        server.close()

    assert result.returncode == 1
    assert result.stdout == ""
    assert "unhealthy" in result.stderr
    assert "status=unknown" in result.stderr
    assert "timestamp=n/a" in result.stderr
    assert "parse failed:" in result.stderr
    assert "unknown encoding" in result.stderr


def test_health_probe_rejects_non_positive_timeout() -> None:
    result = _run_probe(_unused_url(), timeout=0)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--timeout must be a positive finite number" in result.stderr
