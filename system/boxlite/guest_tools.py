from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, List


_DEFAULT_PREVIEW_CHARS = 6000
_IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "release", "logs"}
_WORKSPACE_TXN_PAYLOAD_ENV = "EMBLA_WORKSPACE_TXN_PAYLOAD"
_DOC_ROOTS = ("doc", "docs", "README.md", "README_en.md")


def _safe_int(value: object, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value) if value is not None else int(default)
    except Exception:
        number = int(default)
    return max(min_value, min(max_value, number))


def _preview_text(text: str, limit: int = _DEFAULT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...(truncated, total={len(text)} chars)"


def _jsonpath_deep_find(node: Any, key: str, out: List[Any], max_items: int) -> None:
    if len(out) >= max_items:
        return
    if isinstance(node, dict):
        for current_key, value in node.items():
            if current_key == key:
                out.append(value)
                if len(out) >= max_items:
                    return
            _jsonpath_deep_find(value, key, out, max_items)
            if len(out) >= max_items:
                return
    elif isinstance(node, list):
        for item in node:
            _jsonpath_deep_find(item, key, out, max_items)
            if len(out) >= max_items:
                return


def _jsonpath_extract(content: str, query: str, max_items: int = 50) -> List[Any]:
    data = json.loads(content)
    query = str(query or "").strip()
    if not query:
        raise ValueError("jsonpath query 不能为空")

    if query.startswith("$.."):
        key = query[3:].strip()
        if not key:
            raise ValueError("jsonpath 深度查询缺少 key，例如 $..trace_id")
        out: List[Any] = []
        _jsonpath_deep_find(data, key, out, max_items=max_items)
        return out

    if not query.startswith("$."):
        raise ValueError("仅支持 '$..key' 或 '$.a.b[0]' 形式的简化 jsonpath")

    cursor: Any = data
    expr = query[1:]
    while expr:
        if expr.startswith("."):
            expr = expr[1:]
            match = re.match(r"([A-Za-z0-9_\-]+)", expr)
            if not match:
                raise ValueError(f"jsonpath 字段解析失败: {query}")
            key = match.group(1)
            if not isinstance(cursor, dict) or key not in cursor:
                return []
            cursor = cursor[key]
            expr = expr[match.end():]
            continue

        if expr.startswith("["):
            match = re.match(r"\[(\d+)\]", expr)
            if not match:
                raise ValueError(f"jsonpath 索引解析失败: {query}")
            index = int(match.group(1))
            if not isinstance(cursor, list) or index >= len(cursor):
                return []
            cursor = cursor[index]
            expr = expr[match.end():]
            continue

        raise ValueError(f"不支持的 jsonpath 片段: {expr}")

    return [cursor]


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return repr(value)


def read_file(
    *,
    path: str,
    mode: str = "",
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = _DEFAULT_PREVIEW_CHARS,
    max_results: int = 50,
    pattern: str = "",
    keyword: str = "",
    query: str = "",
    jsonpath: str = "",
    use_regex: bool = False,
    case_sensitive: bool = False,
) -> str:
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    normalized_mode = str(mode or "").strip().lower()
    preview_chars = _safe_int(max_chars, _DEFAULT_PREVIEW_CHARS, 200, 50000)
    limit = _safe_int(max_results, 50, 1, 5000)

    if normalized_mode == "grep":
        pattern_text = str(pattern or keyword or query or "").strip()
        if not pattern_text:
            raise ValueError("read_file(mode=grep) 缺少 pattern/keyword/query")
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern_text if use_regex else re.escape(pattern_text), flags=flags)
        matched: list[str] = []
        for index, line in enumerate(content.splitlines(), start=1):
            if compiled.search(line):
                matched.append(f"{index:4}: {line}")
                if len(matched) >= limit:
                    break
        rendered = "\n".join(matched) if matched else "(no matches)"
        return "\n".join([f"[path] {path}", "[mode] grep", "[content]", rendered])

    if normalized_mode == "jsonpath":
        jsonpath_query = str(query or jsonpath or "").strip()
        if not jsonpath_query:
            raise ValueError("read_file(mode=jsonpath) 缺少 query/jsonpath")
        try:
            values = _jsonpath_extract(content, jsonpath_query, max_items=limit)
        except json.JSONDecodeError as exc:
            raise ValueError(f"文件不是合法 JSON，无法执行 jsonpath: {exc}") from exc
        rendered_values = [_format_value(value) for value in values]
        content_out = "\n".join(f"[{index}] {item}" for index, item in enumerate(rendered_values, start=1))
        if not content_out:
            content_out = "(no matches)"
        return "\n".join([f"[path] {path}", "[mode] jsonpath", "[content]", content_out])

    if start_line is not None or end_line is not None:
        lines = content.splitlines()
        start = _safe_int(start_line, 1, 1, len(lines) if lines else 1)
        end = _safe_int(end_line, min(start + 200, len(lines) if lines else 1), start, len(lines) if lines else start)
        selected = lines[start - 1:end]
        content = "\n".join(f"{index + start:4}: {line}" for index, line in enumerate(selected))

    return _preview_text(content, preview_chars)


def write_file(*, path: str, content: str, mode: str = "overwrite", encoding: str = "utf-8") -> str:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_mode = str(mode or "overwrite").strip().lower()
    content_text = str(content)

    if normalized_mode == "append":
        existing = ""
        try:
            existing = file_path.read_text(encoding=encoding, errors="ignore")
        except FileNotFoundError:
            existing = ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        write_text = existing + content_text
    else:
        write_text = content_text

    file_path.write_text(write_text, encoding=encoding)
    return f"已写入文件: {path} (mode={normalized_mode}, chars={len(content_text)})"


def _collect_search_matches(
    *,
    root: str,
    keyword: str,
    search_path: str,
    include_glob: str,
    case_sensitive: bool,
    use_regex: bool,
    max_results: int,
    max_file_size_kb: int,
) -> list[str]:
    workspace_root = Path(root).resolve(strict=False)
    base = Path(search_path or root).resolve(strict=False)
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(keyword if use_regex else re.escape(keyword), flags=flags)
    max_file_size = _safe_int(max_file_size_kb, 512, 64, 2048) * 1024
    limit = _safe_int(max_results, 50, 1, 200)

    matches: list[str] = []
    for current_root, dirs, files in os.walk(base):
        dirs[:] = [directory for directory in dirs if directory not in _IGNORE_DIRS]
        for filename in files:
            if include_glob and not Path(filename).match(include_glob):
                continue
            file_path = Path(current_root) / filename
            try:
                if file_path.stat().st_size > max_file_size:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            try:
                relative = file_path.relative_to(workspace_root)
            except ValueError:
                relative = file_path.relative_to(base)

            for line_no, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    matches.append(f"{relative}:{line_no}: {line.strip()}")
                    if len(matches) >= limit:
                        return matches
    return matches


def search_keyword(
    *,
    root: str,
    keyword: str,
    search_path: str,
    glob: str,
    case_sensitive: bool,
    use_regex: bool,
    max_results: int,
    max_file_size_kb: int,
) -> str:
    query = str(keyword or "").strip()
    if not query:
        raise ValueError("search_keyword 缺少 keyword/query")

    matches = _collect_search_matches(
        root=root,
        keyword=query,
        search_path=search_path,
        include_glob=str(glob or "").strip(),
        case_sensitive=case_sensitive,
        use_regex=use_regex,
        max_results=max_results,
        max_file_size_kb=max_file_size_kb,
    )
    if not matches:
        return f"未找到关键词: {query}"
    return "\n".join(matches)


def query_docs(
    *,
    root: str,
    query: str,
    max_results: int,
    max_file_size_kb: int,
    case_sensitive: bool,
) -> str:
    keyword = str(query or "").strip()
    if not keyword:
        raise ValueError("query_docs 缺少 query")

    matches = _collect_search_matches(
        root=root,
        keyword=keyword,
        search_path=root,
        include_glob="",
        case_sensitive=case_sensitive,
        use_regex=False,
        max_results=max_results,
        max_file_size_kb=max_file_size_kb,
    )
    if not matches:
        return f"未找到关键词: {keyword}"

    filtered: list[str] = []
    doc_prefixes = tuple(item.lower() for item in _DOC_ROOTS)
    for line in matches:
        path_part = line.split(":", 1)[0].replace("\\", "/").lower()
        if path_part.startswith("doc/") or path_part.startswith("docs/"):
            filtered.append(line)
        elif path_part in ("readme.md", "readme_en.md"):
            filtered.append(line)
        elif path_part.endswith("/readme.md"):
            filtered.append(line)
        elif any(path_part.startswith(prefix) for prefix in doc_prefixes):
            filtered.append(line)
        if len(filtered) >= _safe_int(max_results, 30, 1, 200):
            break

    if filtered:
        return "\n".join(filtered)
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


def file_ast_chunk_read(
    *,
    path: str,
    start_line: int,
    end_line: int,
    context_before: int,
    context_after: int,
    target_path: str = "",
) -> str:
    del target_path
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


def _decode_base64_text(payload: str) -> str:
    raw = str(payload or "").strip()
    if not raw:
        raise ValueError("write_file 缺少 content")
    try:
        return base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"write_file content 无法解码: {exc}") from exc


def _emit_output(text: str) -> None:
    sys.stdout.write(str(text))


def main() -> int:
    parser = argparse.ArgumentParser(description="Embla BoxLite guest helper tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser("read_file")
    read_parser.add_argument("--path", required=True)
    read_parser.add_argument("--mode", default="")
    read_parser.add_argument("--start-line", type=int)
    read_parser.add_argument("--end-line", type=int)
    read_parser.add_argument("--max-chars", type=int, default=_DEFAULT_PREVIEW_CHARS)
    read_parser.add_argument("--max-results", type=int, default=50)
    read_parser.add_argument("--pattern", default="")
    read_parser.add_argument("--keyword", default="")
    read_parser.add_argument("--query", default="")
    read_parser.add_argument("--jsonpath", default="")
    read_parser.add_argument("--use-regex", action="store_true")
    read_parser.add_argument("--case-sensitive", action="store_true")

    write_parser = subparsers.add_parser("write_file")
    write_parser.add_argument("--path", required=True)
    write_parser.add_argument("--content-base64", required=True)
    write_parser.add_argument("--mode", default="overwrite")
    write_parser.add_argument("--encoding", default="utf-8")

    docs_parser = subparsers.add_parser("query_docs")
    docs_parser.add_argument("--root", required=True)
    docs_parser.add_argument("--query", required=True)
    docs_parser.add_argument("--max-results", type=int, default=30)
    docs_parser.add_argument("--max-file-size-kb", type=int, default=768)
    docs_parser.add_argument("--case-sensitive", action="store_true")

    search_parser = subparsers.add_parser("search_keyword")
    search_parser.add_argument("--root", required=True)
    search_parser.add_argument("--keyword", required=True)
    search_parser.add_argument("--search-path", default="")
    search_parser.add_argument("--glob", default="")
    search_parser.add_argument("--case-sensitive", action="store_true")
    search_parser.add_argument("--use-regex", action="store_true")
    search_parser.add_argument("--max-results", type=int, default=50)
    search_parser.add_argument("--max-file-size-kb", type=int, default=512)

    skeleton_parser = subparsers.add_parser("file_ast_skeleton")
    skeleton_parser.add_argument("--path", required=True)
    skeleton_parser.add_argument("--max-results", type=int, default=300)

    chunk_parser = subparsers.add_parser("file_ast_chunk_read")
    chunk_parser.add_argument("--path", required=True)
    chunk_parser.add_argument("--target-path", default="")
    chunk_parser.add_argument("--start-line", type=int, default=1)
    chunk_parser.add_argument("--end-line", type=int, default=121)
    chunk_parser.add_argument("--context-before", type=int, default=3)
    chunk_parser.add_argument("--context-after", type=int, default=3)

    txn_parser = subparsers.add_parser("workspace_txn_apply")
    txn_parser.add_argument("--payload-base64", default="")

    args = parser.parse_args()

    if args.command == "read_file":
        _emit_output(
            read_file(
                path=args.path,
                mode=args.mode,
                start_line=args.start_line,
                end_line=args.end_line,
                max_chars=args.max_chars,
                max_results=args.max_results,
                pattern=args.pattern,
                keyword=args.keyword,
                query=args.query,
                jsonpath=args.jsonpath,
                use_regex=args.use_regex,
                case_sensitive=args.case_sensitive,
            )
        )
        return 0
    if args.command == "write_file":
        _emit_output(
            write_file(
                path=args.path,
                content=_decode_base64_text(args.content_base64),
                mode=args.mode,
                encoding=args.encoding,
            )
        )
        return 0
    if args.command == "query_docs":
        _emit_output(
            query_docs(
                root=args.root,
                query=args.query,
                max_results=args.max_results,
                max_file_size_kb=args.max_file_size_kb,
                case_sensitive=args.case_sensitive,
            )
        )
        return 0
    if args.command == "search_keyword":
        _emit_output(
            search_keyword(
                root=args.root,
                keyword=args.keyword,
                search_path=args.search_path or args.root,
                glob=args.glob,
                case_sensitive=args.case_sensitive,
                use_regex=args.use_regex,
                max_results=args.max_results,
                max_file_size_kb=args.max_file_size_kb,
            )
        )
        return 0
    if args.command == "file_ast_skeleton":
        _emit_output(file_ast_skeleton(path=args.path, max_results=args.max_results))
        return 0
    if args.command == "file_ast_chunk_read":
        _emit_output(
            file_ast_chunk_read(
                path=args.path,
                target_path=args.target_path,
                start_line=args.start_line,
                end_line=args.end_line,
                context_before=args.context_before,
                context_after=args.context_after,
            )
        )
        return 0
    if args.command == "workspace_txn_apply":
        _emit_output(workspace_txn_apply(payload_base64=args.payload_base64))
        return 0
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
