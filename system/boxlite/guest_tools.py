from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
from pathlib import Path


_IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "release", "logs"}
_WORKSPACE_TXN_PAYLOAD_ENV = "EMBLA_WORKSPACE_TXN_PAYLOAD"


def _safe_int(value: object, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value) if value is not None else int(default)
    except Exception:
        number = int(default)
    return max(min_value, min(max_value, number))


def query_docs(*, root: str, query: str, max_results: int, max_file_size_kb: int) -> str:
    keyword = str(query or "").strip()
    if not keyword:
        raise ValueError("query_docs 缺少 query")

    base = Path(root).resolve(strict=False)
    if not base.exists():
        raise FileNotFoundError(f"docs root not found: {root}")

    max_file_size = _safe_int(max_file_size_kb, 768, 64, 2048) * 1024
    limit = _safe_int(max_results, 30, 1, 200)
    pattern = re.compile(re.escape(keyword), flags=re.IGNORECASE)
    matches: list[str] = []

    for path in base.rglob("*"):
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        rel_text = "/".join(rel.parts).lower()
        parts = [part.lower() for part in rel.parts]
        if not parts:
            continue
        top = parts[0]
        name = parts[-1]
        if not (top in {"doc", "docs"} or name in {"readme.md", "readme_en.md"} or rel_text.endswith("/readme.md")):
            continue
        try:
            if path.stat().st_size > max_file_size:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        shown = "/".join(rel.parts)
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                matches.append(f"{shown}:{idx}:{line.strip()}")
                if len(matches) >= limit:
                    return "\n".join(matches)

    if not matches:
        return f"未找到关键词: {keyword}"
    return "\n".join(matches)


def file_ast_skeleton(*, path: str, max_results: int) -> str:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    ext = file_path.suffix.lower()
    max_symbols = _safe_int(max_results, 300, 20, 5000)

    import_patterns = [
        re.compile(r"^\s*import\s+.+"),
        re.compile(r"^\s*from\s+.+\s+import\s+.+"),
        re.compile(r"^\s*using\s+.+;"),
    ]
    if ext in {".py"}:
        symbol_patterns = [re.compile(r"^\s*(class|def)\s+([A-Za-z_][A-Za-z0-9_]*)")]
    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        symbol_patterns = [
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(function|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\("),
        ]
    elif ext in {".cs"}:
        symbol_patterns = [
            re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+)?(class|interface|record|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z_<>\[\],?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
        ]
    else:
        symbol_patterns = [re.compile(r"^\s*(class|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)")]

    imports: list[str] = []
    symbols: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if len(imports) < 200 and any(pattern.search(line) for pattern in import_patterns):
            imports.append(f"{idx:4}: {line.strip()}")
        if len(symbols) >= max_symbols:
            continue
        for pattern in symbol_patterns:
            match = pattern.search(line)
            if not match:
                continue
            if len(match.groups()) >= 2:
                kind = match.group(1)
                name = match.group(2)
            else:
                kind = "symbol"
                name = match.group(1)
            symbols.append(f"{idx:4}: {kind} {name}")
            break

    sections = [
        f"[path] {path}",
        f"[language] {ext or '(unknown)'}",
        f"[total_lines] {len(lines)}",
        f"[total_chars] {len(text)}",
    ]
    if len(lines) > 5000:
        sections.append("[note] Monolith file detected; this is skeleton-only output.")
    sections.extend(["[imports]", "\n".join(imports) if imports else "(none)"])
    sections.extend(["[symbols]", "\n".join(symbols) if symbols else "(none)"])
    return "\n".join(sections)


def file_ast_chunk_read(*, path: str, start_line: int, end_line: int, context_before: int, context_after: int) -> str:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if not lines:
        return f"[path] {path}\n(content is empty)"

    start = _safe_int(start_line, 1, 1, len(lines))
    end_default = min(len(lines), start + 120)
    end = _safe_int(end_line, end_default, start, len(lines))
    before = _safe_int(context_before, 3, 0, 200)
    after = _safe_int(context_after, 3, 0, 200)

    from_line = max(1, start - before)
    to_line = min(len(lines), end + after)
    selected = lines[from_line - 1:to_line]

    rendered = [
        f"[path] {path}",
        f"[requested_range] {start}-{end}",
        f"[returned_range] {from_line}-{to_line}",
        "[content]",
    ]
    for idx, line in enumerate(selected, start=from_line):
        marker = ">>" if start <= idx <= end else "  "
        rendered.append(f"{marker} {idx:4}: {line}")
    return "\n".join(rendered)


def _load_workspace_txn_payload(payload_base64: str) -> dict:
    raw = str(payload_base64 or os.environ.get(_WORKSPACE_TXN_PAYLOAD_ENV, "")).strip()
    if not raw:
        raise ValueError("workspace_txn_apply 缺少 payload")
    try:
        decoded = base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"workspace_txn_apply payload 无法解码: {exc}") from exc
    try:
        payload = json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"workspace_txn_apply payload 不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("workspace_txn_apply payload 必须为 object")
    return payload


def workspace_txn_apply(*, payload_base64: str) -> str:
    payload = _load_workspace_txn_payload(payload_base64)
    from apiserver.native_tools import NativeToolExecutor

    executor = NativeToolExecutor()
    return asyncio.run(executor._workspace_txn_apply(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Embla BoxLite guest helper tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    docs_parser = subparsers.add_parser("query_docs")
    docs_parser.add_argument("--root", required=True)
    docs_parser.add_argument("--query", required=True)
    docs_parser.add_argument("--max-results", type=int, default=30)
    docs_parser.add_argument("--max-file-size-kb", type=int, default=768)

    skeleton_parser = subparsers.add_parser("file_ast_skeleton")
    skeleton_parser.add_argument("--path", required=True)
    skeleton_parser.add_argument("--max-results", type=int, default=300)

    chunk_parser = subparsers.add_parser("file_ast_chunk_read")
    chunk_parser.add_argument("--path", required=True)
    chunk_parser.add_argument("--start-line", type=int, default=1)
    chunk_parser.add_argument("--end-line", type=int, default=121)
    chunk_parser.add_argument("--context-before", type=int, default=3)
    chunk_parser.add_argument("--context-after", type=int, default=3)

    txn_parser = subparsers.add_parser("workspace_txn_apply")
    txn_parser.add_argument("--payload-base64", default="")

    args = parser.parse_args()

    if args.command == "query_docs":
        print(query_docs(root=args.root, query=args.query, max_results=args.max_results, max_file_size_kb=args.max_file_size_kb))
        return 0
    if args.command == "file_ast_skeleton":
        print(file_ast_skeleton(path=args.path, max_results=args.max_results))
        return 0
    if args.command == "file_ast_chunk_read":
        print(
            file_ast_chunk_read(
                path=args.path,
                start_line=args.start_line,
                end_line=args.end_line,
                context_before=args.context_before,
                context_after=args.context_after,
            )
        )
        return 0
    if args.command == "workspace_txn_apply":
        print(workspace_txn_apply(payload_base64=args.payload_base64))
        return 0
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
