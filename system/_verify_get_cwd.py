#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick regression check for get_cwd interception.

Run:
  python system/_verify_get_cwd.py

Expected:
  - intercepted tool_name == get_cwd
  - execute returns a path under project root
"""

import asyncio

from apiserver.native_tools import get_native_tool_executor


def main():
    ex = get_native_tool_executor()
    call = {
        "agentType": "openclaw",
        "task_type": "message",
        "message": "pwd",
        "session_key": "naga_test",
    }

    intercepted = ex.maybe_intercept_openclaw_call(call, session_id="test_session")
    print("intercepted=", intercepted)

    if not intercepted:
        raise SystemExit("FAIL: no interception")
    if intercepted.get("tool_name") != "get_cwd":
        raise SystemExit(f"FAIL: tool_name != get_cwd: {intercepted.get('tool_name')}")

    async def _run():
        res = await ex.execute(intercepted, session_id="test_session")
        print("execute_result=", res)
        if res.get("status") != "success":
            raise SystemExit(f"FAIL: execute status={res.get('status')}")
        path = str(res.get("result") or "")
        if not path:
            raise SystemExit("FAIL: empty cwd")

    asyncio.run(_run())
    print("PASS")


if __name__ == "__main__":
    main()
