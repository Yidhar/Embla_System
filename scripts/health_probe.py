#!/usr/bin/env python3
"""Lightweight HTTP health probe CLI.

Usage:
    python scripts/health_probe.py --url http://127.0.0.1:8000 --timeout 5
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT_SECONDS = 5.0
HEALTH_ENDPOINT_PATH = "/health"
HEALTHY_STATUS = "healthy"
DEFAULT_TIMESTAMP = "n/a"
UNKNOWN_STATUS = "unknown"
FAILURE_STATUS = "status"
FAILURE_REQUEST = "request"
FAILURE_PARSE = "parse"


@dataclass(frozen=True)
class ProbeResult:
    probe_url: str
    http_status: int | None
    status: str
    timestamp: str
    ok: bool
    failure_kind: str | None = None
    detail: str = ""


def positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid timeout value: {value}") from exc

    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("--timeout must be a positive finite number")
    return timeout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Perform a lightweight HTTP health probe.")
    parser.add_argument("--url", required=True, help="Base service URL or explicit health URL.")
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    return parser


def build_probe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    normalized_path = (parts.path or "").rstrip("/")

    if not normalized_path:
        probe_path = HEALTH_ENDPOINT_PATH
    elif normalized_path.endswith(HEALTH_ENDPOINT_PATH):
        probe_path = normalized_path
    else:
        probe_path = f"{normalized_path}{HEALTH_ENDPOINT_PATH}"

    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, probe_path, parts.query, parts.fragment))


def parse_health_payload(payload: bytes, *, encoding: str) -> tuple[str, str]:
    try:
        data = json.loads(payload.decode(encoding))
    except LookupError as exc:
        raise ValueError(f"response body uses unknown encoding '{encoding}': {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"response body is not valid {encoding}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"response body is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("response JSON must be an object")

    status = data.get("status")
    timestamp = data.get("timestamp")

    if not isinstance(status, str) or not status.strip():
        raise ValueError("response JSON must include a non-empty string 'status'")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("response JSON must include a non-empty string 'timestamp'")

    return status.strip(), timestamp.strip()


def read_response(response: object) -> tuple[int | None, str, bytes]:
    http_status = getattr(response, "status", None)
    if http_status is None and hasattr(response, "getcode"):
        http_status = response.getcode()

    headers = getattr(response, "headers")
    encoding = headers.get_content_charset() or "utf-8"
    payload = response.read()
    return http_status, encoding, payload


def build_request_failure_detail(http_status: int | None, reason: object | None = None) -> str:
    if reason not in {None, ""}:
        return f"request failed: {reason}"
    if http_status is not None:
        return f"request failed: HTTP {http_status}"
    return "request failed"


def combine_details(*details: str) -> str:
    combined: list[str] = []
    for detail in details:
        if detail and detail not in combined:
            combined.append(detail)
    return "; ".join(combined)


def probe(url: str, timeout: float) -> ProbeResult:
    probe_url = build_probe_url(url)
    request = urllib.request.Request(
        url=probe_url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    request_failure_detail = ""

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            http_status, encoding, payload = read_response(response)
    except urllib.error.HTTPError as exc:
        http_status, encoding, payload = read_response(exc)
        request_failure_detail = build_request_failure_detail(http_status=http_status, reason=exc.reason)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return ProbeResult(
            probe_url=probe_url,
            http_status=None,
            status=UNKNOWN_STATUS,
            timestamp=DEFAULT_TIMESTAMP,
            ok=False,
            failure_kind=FAILURE_REQUEST,
            detail=build_request_failure_detail(http_status=None, reason=reason),
        )
    except socket.timeout:
        return ProbeResult(
            probe_url=probe_url,
            http_status=None,
            status=UNKNOWN_STATUS,
            timestamp=DEFAULT_TIMESTAMP,
            ok=False,
            failure_kind=FAILURE_REQUEST,
            detail="request failed: timed out",
        )
    except TimeoutError:
        return ProbeResult(
            probe_url=probe_url,
            http_status=None,
            status=UNKNOWN_STATUS,
            timestamp=DEFAULT_TIMESTAMP,
            ok=False,
            failure_kind=FAILURE_REQUEST,
            detail="request failed: timed out",
        )
    except Exception as exc:  # pragma: no cover - defensive catch for CLI robustness
        return ProbeResult(
            probe_url=probe_url,
            http_status=None,
            status=UNKNOWN_STATUS,
            timestamp=DEFAULT_TIMESTAMP,
            ok=False,
            failure_kind=FAILURE_REQUEST,
            detail=f"request failed: {exc}",
        )

    try:
        status, timestamp = parse_health_payload(payload, encoding=encoding)
    except ValueError as exc:
        return ProbeResult(
            probe_url=probe_url,
            http_status=http_status,
            status=UNKNOWN_STATUS,
            timestamp=DEFAULT_TIMESTAMP,
            ok=False,
            failure_kind=FAILURE_REQUEST if request_failure_detail else FAILURE_PARSE,
            detail=combine_details(request_failure_detail, f"parse failed: {exc}"),
        )

    is_healthy = status.lower() == HEALTHY_STATUS
    if request_failure_detail:
        return ProbeResult(
            probe_url=probe_url,
            http_status=http_status,
            status=status,
            timestamp=timestamp,
            ok=False,
            failure_kind=FAILURE_REQUEST,
            detail=combine_details(request_failure_detail, "" if is_healthy else "status is not healthy"),
        )

    if not is_healthy:
        return ProbeResult(
            probe_url=probe_url,
            http_status=http_status,
            status=status,
            timestamp=timestamp,
            ok=False,
            failure_kind=FAILURE_STATUS,
            detail="status is not healthy",
        )

    return ProbeResult(
        probe_url=probe_url,
        http_status=http_status,
        status=status,
        timestamp=timestamp,
        ok=True,
    )


def format_result(result: ProbeResult) -> str:
    http_status = result.http_status if result.http_status is not None else "n/a"
    base = (
        f"url={result.probe_url} http_status={http_status} "
        f"status={result.status} timestamp={result.timestamp}"
    )
    if result.detail:
        return f"{base} detail={result.detail}"
    return base


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = probe(url=args.url, timeout=args.timeout)
    line = format_result(result)

    if result.ok:
        print(f"healthy {line}")
        return 0

    if result.failure_kind == FAILURE_STATUS:
        print(f"unhealthy {line}")
    else:
        print(f"unhealthy {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
