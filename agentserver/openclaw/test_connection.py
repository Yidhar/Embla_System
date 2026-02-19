#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw connectivity test (local gateway).

This script is meant to be safe to commit:
- No hardcoded tokens.
- Reads gateway/hooks tokens from ~/.openclaw/openclaw.json by default.

Usage:
  python agentserver/openclaw/test_connection.py

Optional overrides:
  set OPENCLAW_CONFIG_PATH=C:\\Users\\<you>\\.openclaw\\openclaw.json
  set OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789
  set OPENCLAW_GATEWAY_TOKEN=...
  set OPENCLAW_HOOKS_TOKEN=...
  set OPENCLAW_AGENT_ID=main
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx


# Ensure localhost requests bypass proxy.
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")


def _load_openclaw_config() -> Dict[str, Any]:
    raw_path = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    cfg_path = Path(raw_path).expanduser() if raw_path else (Path.home() / ".openclaw" / "openclaw.json")
    if not cfg_path.exists():
        raise FileNotFoundError(f"OpenClaw config not found: {cfg_path}")
    # Be tolerant to UTF-8 BOM written by some editors / PowerShell defaults.
    return json.loads(cfg_path.read_text(encoding="utf-8-sig"))


def _resolve_gateway_url(cfg: Dict[str, Any]) -> str:
    env_url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    port = int(cfg.get("gateway", {}).get("port", 18789))
    # Most configs use bind=loopback; always talk to 127.0.0.1 for local dev.
    return f"http://127.0.0.1:{port}"


def _resolve_tokens(cfg: Dict[str, Any]) -> Tuple[str, str]:
    gateway_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    hooks_token = os.environ.get("OPENCLAW_HOOKS_TOKEN", "").strip()

    if not gateway_token:
        gateway_token = (cfg.get("gateway", {}).get("auth", {}) or {}).get("token", "") or ""
    if not hooks_token:
        hooks_token = (cfg.get("hooks", {}) or {}).get("token", "") or ""

    if not gateway_token:
        raise ValueError("Missing OpenClaw gateway token (gateway.auth.token).")
    if not hooks_token:
        raise ValueError("Missing OpenClaw hooks token (hooks.token).")
    return gateway_token, hooks_token


def _bearer_headers(token: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _normalize_full_session_key(agent_id: str, session_key: str) -> str:
    sk = (session_key or "").strip()
    if not sk:
        return sk
    if sk.startswith("agent:"):
        return sk
    return f"agent:{agent_id}:{sk}"


def _extract_assistant_outcome(data: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """
    Extract all assistant replies from sessions_history response, plus any terminal error.
    Returns:
      (replies, last_error_message)
    """
    replies: List[str] = []
    last_error: Optional[str] = None

    try:
        result = data.get("result", {})
        details = result.get("details", {}) if isinstance(result, dict) else {}
        messages = details.get("messages", []) if isinstance(details, dict) else []

        # Some OpenClaw builds wrap JSON into result.content[0].text.
        if not messages and isinstance(result, dict):
            content = result.get("content", [])
            if isinstance(content, list) and content:
                text0 = content[0].get("text", "") if isinstance(content[0], dict) else ""
                if isinstance(text0, str) and text0.strip():
                    try:
                        inner = json.loads(text0)
                        details = inner.get("details", {}) if isinstance(inner, dict) else {}
                        messages = details.get("messages", []) if isinstance(details, dict) else inner.get("messages", [])
                    except Exception:
                        pass

        if not isinstance(messages, list):
            return replies, last_error

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue

            if msg.get("stopReason") == "error" and msg.get("errorMessage"):
                last_error = str(msg.get("errorMessage"))

            content = msg.get("content", [])
            if isinstance(content, str):
                if content.strip():
                    replies.append(content)
                continue

            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                text = "\n".join([p for p in parts if isinstance(p, str) and p.strip()]).strip()
                if text:
                    replies.append(text)

    except Exception:
        # best-effort only
        pass

    return replies, last_error


async def _poll_sessions_history(
    *,
    client: httpx.AsyncClient,
    gateway_url: str,
    gateway_headers: Dict[str, str],
    full_session_key: str,
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 3.0,
) -> Tuple[List[str], Optional[str]]:
    start = time.time()
    last_replies: List[str] = []
    last_error: Optional[str] = None
    stable_polls = 0

    while time.time() - start < timeout_seconds:
        payload = {
            "tool": "sessions_history",
            # NOTE: tools.sessions.visibility=tree requires the top-level sessionKey to match.
            "sessionKey": full_session_key,
            "args": {"sessionKey": full_session_key, "limit": 50},
        }
        r = await client.post(f"{gateway_url}/tools/invoke", headers=gateway_headers, json=payload, timeout=15)
        if r.status_code != 200:
            last_error = f"sessions_history http {r.status_code}: {r.text[:200]}"
            await asyncio.sleep(poll_interval_seconds)
            continue

        data = r.json()
        replies, err = _extract_assistant_outcome(data)
        last_error = err

        if err and not replies:
            return [], err

        if len(replies) > len(last_replies):
            last_replies = replies
            stable_polls = 0
        else:
            stable_polls += 1
            if stable_polls >= 3 and last_replies:
                return last_replies, None

        await asyncio.sleep(poll_interval_seconds)

    if last_replies:
        return last_replies, None
    return [], last_error or "poll timeout: no assistant reply"


async def test_root(*, client: httpx.AsyncClient, gateway_url: str, gateway_headers: Dict[str, str]) -> None:
    print("\n[1] GET /")
    r = await client.get(f"{gateway_url}/", headers=gateway_headers, timeout=10)
    print(f"    status={r.status_code}")
    print(f"    body={r.text[:200] if r.text else '(empty)'}")


async def test_hooks_agent_accept(*, client: httpx.AsyncClient, gateway_url: str, hooks_headers: Dict[str, str]) -> None:
    print("\n[2] POST /hooks/agent (acceptance)")
    payload = {"message": "hello from naga test_connection.py", "sessionKey": "naga:test", "name": "NagaTest"}
    r = await client.post(f"{gateway_url}/hooks/agent", headers=hooks_headers, json=payload, timeout=30)
    print(f"    status={r.status_code}")
    print(f"    body={r.text[:300] if r.text else '(empty)'}")


async def test_hooks_wake(*, client: httpx.AsyncClient, gateway_url: str, hooks_headers: Dict[str, str]) -> None:
    print("\n[3] POST /hooks/wake")
    payload = {"text": "naga test wake", "mode": "now"}
    r = await client.post(f"{gateway_url}/hooks/wake", headers=hooks_headers, json=payload, timeout=30)
    print(f"    status={r.status_code}")
    print(f"    body={r.text[:300] if r.text else '(empty)'}")


async def test_hooks_agent_sync_reply(
    *,
    client: httpx.AsyncClient,
    gateway_url: str,
    gateway_headers: Dict[str, str],
    hooks_headers: Dict[str, str],
    agent_id: str,
) -> None:
    print("\n[4] POST /hooks/agent (send + poll sessions_history)")

    # Use a unique session key so we can poll deterministically.
    session_key = f"naga:reply-test-{int(time.time())}"
    payload = {
        "message": "Reply with OK only.",
        "sessionKey": session_key,
        "name": "NagaReplyTest",
        "deliver": False,
        "timeoutSeconds": 30,
    }

    r = await client.post(f"{gateway_url}/hooks/agent", headers=hooks_headers, json=payload, timeout=60)
    print(f"    status={r.status_code}")
    if r.status_code not in (200, 202):
        print(f"    error={r.text[:500]}")
        return

    data = r.json()
    run_id = data.get("runId")
    print(f"    runId={run_id}")

    if data.get("status") == "ok" and data.get("reply"):
        print("    got sync reply:")
        print(f"    {str(data.get('reply'))[:500]}")
        return

    full_session_key = _normalize_full_session_key(agent_id, session_key)
    replies, err = await _poll_sessions_history(
        client=client,
        gateway_url=gateway_url,
        gateway_headers=gateway_headers,
        full_session_key=full_session_key,
        timeout_seconds=60,
    )

    if replies:
        print(f"    got replies: count={len(replies)}")
        print(f"    reply[0]={replies[0][:800]}")
        return

    print(f"    poll failed: {err}")
    print("    hints:")
    print("      - If you see 'forbidden', ensure tools.sessions.visibility and sessionKey propagation are correct.")
    print("      - If you see '401 Unauthorized', check gateway/auth token vs hooks token.")
    print("      - If you see provider/model errors, check your OpenClaw model provider config.")


async def test_tools_invoke(*, client: httpx.AsyncClient, gateway_url: str, gateway_headers: Dict[str, str]) -> None:
    print("\n[5] POST /tools/invoke (sessions_list)")
    r = await client.post(
        f"{gateway_url}/tools/invoke",
        headers=gateway_headers,
        json={"tool": "sessions_list"},
        timeout=30,
    )
    print(f"    status={r.status_code}")
    print(f"    body={r.text[:600] if r.text else '(empty)'}")


async def main() -> None:
    cfg = _load_openclaw_config()
    gateway_url = _resolve_gateway_url(cfg)
    gateway_token, hooks_token = _resolve_tokens(cfg)
    agent_id = os.environ.get("OPENCLAW_AGENT_ID", "main").strip() or "main"

    gateway_headers = _bearer_headers(gateway_token)
    hooks_headers = _bearer_headers(hooks_token)

    print("=" * 70)
    print("OpenClaw connectivity test (local)")
    print(f"gateway_url={gateway_url}")
    print(f"agent_id={agent_id}")
    print("=" * 70)

    async with httpx.AsyncClient() as client:
        await test_root(client=client, gateway_url=gateway_url, gateway_headers=gateway_headers)
        await test_hooks_agent_sync_reply(
            client=client,
            gateway_url=gateway_url,
            gateway_headers=gateway_headers,
            hooks_headers=hooks_headers,
            agent_id=agent_id,
        )
        await test_hooks_agent_accept(client=client, gateway_url=gateway_url, hooks_headers=hooks_headers)
        await test_hooks_wake(client=client, gateway_url=gateway_url, hooks_headers=hooks_headers)
        await test_tools_invoke(client=client, gateway_url=gateway_url, gateway_headers=gateway_headers)

    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
