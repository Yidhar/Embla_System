import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple


def _encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_message(proc: subprocess.Popen, timeout_s: float = 10.0) -> Tuple[Optional[dict], bytes, bytes]:
    """Read one MCP stdio framed JSON-RPC message.

    Returns: (json_obj|None, raw_body, raw_header)
    """
    start = time.time()
    header_lines = []
    raw_header = b""

    # Read headers (LSP-style) until blank line
    while True:
        if time.time() - start > timeout_s:
            return None, b"", raw_header

        line = proc.stdout.readline()
        if not line:
            # process ended or no output
            return None, b"", raw_header

        raw_header += line
        stripped = line.strip(b"\r\n")

        if stripped == b"":
            break
        header_lines.append(stripped)

        # Avoid unbounded header read
        if len(raw_header) > 64 * 1024:
            return None, b"", raw_header

    content_length = None
    for hl in header_lines:
        try:
            k, v = hl.split(b":", 1)
        except ValueError:
            continue
        if k.strip().lower() == b"content-length":
            try:
                content_length = int(v.strip())
            except ValueError:
                content_length = None

    if content_length is None or content_length < 0 or content_length > 50 * 1024 * 1024:
        return None, b"", raw_header

    body = proc.stdout.read(content_length)
    if not body or len(body) != content_length:
        return None, body or b"", raw_header

    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        obj = None

    return obj, body, raw_header


def _windows_cmd_for_npx() -> list[str]:
    """On Windows, `npx` is typically a `npx.cmd` shim; Popen won't resolve it unless we call via cmd.exe."""
    # Prefer cmd.exe /c npx ... for maximum compatibility with PATH resolution.
    return ["cmd.exe", "/c", "npx", "-y", "@cexll/codex-mcp-server"]


def main() -> int:
    if os.name == "nt":
        cmd = _windows_cmd_for_npx()
    else:
        cmd = ["npx", "-y", "@cexll/codex-mcp-server"]

    print("[mcp-test] spawning:", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
    )

    def send(msg: dict):
        data = _encode_message(msg)
        assert proc.stdin is not None
        proc.stdin.write(data)
        proc.stdin.flush()

    try:
        # 1) initialize
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "naga-selfcheck", "version": "0.0"},
                },
            }
        )

        init_resp, init_body, init_hdr = _read_message(proc, timeout_s=25.0)
        print("[mcp-test] initialize response:")
        if init_resp is None:
            print("  (no/invalid response)")
            if init_hdr:
                print("  raw header:", init_hdr[:500])
            if init_body:
                print("  raw body:", init_body[:500])
        else:
            print(json.dumps(init_resp, indent=2, ensure_ascii=False))

        # send initialized notification regardless (best effort)
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # 2) tools/list
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp, tools_body, tools_hdr = _read_message(proc, timeout_s=25.0)
        print("[mcp-test] tools/list response:")
        if tools_resp is None:
            print("  (no/invalid response)")
            if tools_hdr:
                print("  raw header:", tools_hdr[:500])
            if tools_body:
                print("  raw body:", tools_body[:500])
        else:
            print(json.dumps(tools_resp, indent=2, ensure_ascii=False))

        ok = bool(init_resp) and bool(tools_resp)
        return 0 if ok else 2

    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass

        # Drain stderr (best effort)
        try:
            err = proc.stderr.read() if proc.stderr else b""
            if err:
                print("[mcp-test] stderr (first 2000 bytes):")
                sys.stdout.write(err[:2000].decode("utf-8", errors="replace"))
                sys.stdout.write("\n")
        except Exception:
            pass

        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
