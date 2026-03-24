#!/usr/bin/env python3
"""One-shot self-audit: start API server, send audit request, print response."""
import json
import sys
import threading
import time
import traceback

import requests
import uvicorn


def _start_server():
    uvicorn.run("apiserver.api_server:app", host="127.0.0.1", port=8000, log_level="warning")


def main():
    t = threading.Thread(target=_start_server, daemon=True)
    t.start()

    ready = False
    for i in range(25):
        time.sleep(1)
        try:
            r = requests.get("http://127.0.0.1:8000/v1/health", timeout=2)
            if r.status_code == 200:
                print("Server ready (%ds)" % (i + 1))
                ready = True
                break
        except Exception:
            pass
    if not ready:
        print("FAILED TO START")
        return 1

    print("Sending self-audit request...")
    r = requests.post(
        "http://127.0.0.1:8000/v1/chat/stream",
        json={
            "message": "use get_system_status to check the system, then briefly assess improvement areas",
            "session_id": "audit-005",
        },
        stream=True,
        timeout=90,
    )

    tc = 0
    tr = 0
    content = []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            d = json.loads(line[6:])
        except Exception:
            continue
        evt = d.get("type", "")
        if evt == "route_decision":
            print("ROUTE: %s dispatch=%s" % (d.get("route_semantic"), d.get("dispatch_to_core")))
        elif evt == "tool_calls":
            items = d.get("text", [])
            if isinstance(items, list):
                for c in items:
                    tc += 1
                    print("CALL#%d: %s" % (tc, c.get("name", "")))
        elif evt == "tool_result":
            tr += 1
            name = d.get("tool_name", "")
            status = d.get("result", {}).get("status", "")
            preview = str(d.get("result", {}).get("result", ""))[:120]
            print("RESULT#%d: %s -> %s: %s" % (tr, name, status, preview))
        elif evt == "content":
            content.append(d.get("text", ""))

    full = "".join(content)
    print("\n" + "=" * 60)
    print("Agent self-audit response (%d chars):" % len(full))
    print("=" * 60)
    print(full[:3000])
    if len(full) > 3000:
        print("... (%d total)" % len(full))
    print("\nSTATS: tool_calls=%d tool_results=%d" % (tc, tr))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
