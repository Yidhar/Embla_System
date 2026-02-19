#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch: add native get_cwd tool and fix openclaw->native cwd/pwd interception.

Idempotent patcher. Run:
  python system/_patch_add_get_cwd.py

Edits:
- apiserver/native_tools.py:
  - intercept cwd/pwd -> {tool_name: get_cwd}
  - aliases add pwd/cwd -> get_cwd
  - execute dispatch add get_cwd
  - add _get_cwd method
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "apiserver" / "native_tools.py"


def main() -> None:
    s = TARGET.read_text(encoding="utf-8")
    orig = s

    # 1) Fix interception mapping (minimal, exact strings present in current file)
    s = s.replace(
        '                "tool_name": "run_cmd",\n                "command": "cd",\n',
        '                "tool_name": "get_cwd",\n',
    )

    # 2) Add aliases entries
    marker = '            "writefile": "write_file",\n'
    if marker in s and '"pwd": "get_cwd"' not in s and '"cwd": "get_cwd"' not in s:
        s = s.replace(
            marker,
            marker + '            "pwd": "get_cwd",\n            "cwd": "get_cwd",\n',
        )

    # 3) Add execute dispatch branch after write_file
    if 'elif tool_name == "get_cwd":' not in s:
        s = s.replace(
            '            elif tool_name == "write_file":\n                result = await self._write_file(call)\n'
            '            elif tool_name == "run_cmd":\n',
            '            elif tool_name == "write_file":\n                result = await self._write_file(call)\n'
            '            elif tool_name == "get_cwd":\n                result = await self._get_cwd(call)\n'
            '            elif tool_name == "run_cmd":\n',
        )

    # 4) Add method _get_cwd before _run_cmd
    if "async def _get_cwd" not in s:
        insert_before = "    async def _run_cmd"
        idx = s.find(insert_before)
        if idx == -1:
            raise SystemExit("Cannot find insertion point for _get_cwd")
        method = (
            "    async def _get_cwd(self, call: Dict[str, Any]) -> str:\n"
            "        \"\"\"Return native sandbox working directory (project root).\"\"\"\n"
            "        return str(self.project_root).replace('\\\\', '/')\n\n\n"
        )
        s = s[:idx] + method + s[idx:]

    if s == orig:
        print("No changes applied (already patched?)")
    else:
        TARGET.write_text(s, encoding="utf-8")
        print("Patched:", TARGET)


if __name__ == "__main__":
    main()
