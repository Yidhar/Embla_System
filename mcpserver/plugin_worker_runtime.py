"""WS24-001 isolated plugin worker runtime entry."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from typing import Any, Dict


def _json_error(message: str, **kwargs: Any) -> str:
    payload: Dict[str, Any] = {"status": "error", "message": str(message)}
    payload.update(kwargs)
    return json.dumps(payload, ensure_ascii=False)


def _load_payload(stdin_text: str) -> Dict[str, Any]:
    normalized = str(stdin_text or "").strip()
    if not normalized:
        return {}
    try:
        parsed = json.loads(normalized)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


async def _invoke_handler(handler: Any, payload: Dict[str, Any]) -> Any:
    result = handler(payload)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def run_worker(module_name: str, class_name: str, payload: Dict[str, Any]) -> tuple[int, str]:
    try:
        module = importlib.import_module(module_name)
        agent_class = getattr(module, class_name)
        instance = agent_class()
        handler = getattr(instance, "handle_handoff")
    except Exception as exc:
        return 2, _json_error(
            f"plugin bootstrap failed: {exc}",
            module_name=module_name,
            class_name=class_name,
        )

    try:
        result = await _invoke_handler(handler, payload)
    except Exception as exc:
        return 3, _json_error(
            f"plugin call failed: {exc}",
            module_name=module_name,
            class_name=class_name,
        )

    if isinstance(result, str):
        return 0, result
    try:
        return 0, json.dumps(result, ensure_ascii=False)
    except Exception:
        return 0, json.dumps({"status": "ok", "result": str(result)}, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run isolated plugin worker call")
    parser.add_argument("--module", required=True, help="Plugin module import path")
    parser.add_argument("--class", dest="class_name", required=True, help="Plugin class name")
    parser.add_argument("--max-memory-mb", type=int, default=0, help="Optional memory limit (best-effort)")
    parser.add_argument("--cpu-time-seconds", type=int, default=0, help="Optional CPU time limit (best-effort)")
    return parser.parse_args()


def _apply_resource_limits(max_memory_mb: int, cpu_time_seconds: int) -> None:
    """
    Apply best-effort per-process resource limits.

    On Windows `resource` module is unavailable; this function becomes a no-op.
    """
    if int(max_memory_mb or 0) <= 0 and int(cpu_time_seconds or 0) <= 0:
        return

    try:
        import resource  # type: ignore
    except Exception:
        return

    try:
        if int(max_memory_mb or 0) > 0 and hasattr(resource, "RLIMIT_AS"):
            limit_bytes = int(max_memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        if int(cpu_time_seconds or 0) > 0 and hasattr(resource, "RLIMIT_CPU"):
            limit_seconds = int(max(1, cpu_time_seconds))
            resource.setrlimit(resource.RLIMIT_CPU, (limit_seconds, limit_seconds))
    except Exception:
        # Best-effort only; runtime should still continue.
        return


def main() -> int:
    args = parse_args()
    _apply_resource_limits(args.max_memory_mb, args.cpu_time_seconds)
    payload = _load_payload(sys.stdin.read())
    try:
        code, output = asyncio.run(run_worker(args.module, args.class_name, payload))
    except Exception as exc:
        print(_json_error(f"worker runtime failed: {exc}"), end="")
        return 1
    print(output, end="")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
