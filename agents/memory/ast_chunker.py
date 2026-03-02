"""AST-based code chunker for Hierarchical RAG (Layer 3).

Architecture ref: doc/14-multi-agent-architecture.md §5.3
  ".py 文件 AST 切分，.md 按标题切分"

Provides deterministic chunking of source files:
  - Python: AST-based (functions, classes, top-level)
  - Markdown: heading-based
  - Other: line-count-based
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    """A single chunk of code or text from a file."""

    chunk_id: str
    file_path: str
    chunk_type: str  # "function" | "class" | "top_level" | "heading" | "block"
    name: str        # Function/class/heading name or block identifier
    start_line: int
    end_line: int
    content: str
    summary: str = ""  # L1 summary (~200 tokens), filled later
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if not self.token_estimate:
            self.token_estimate = max(1, len(self.content) // 4)


def chunk_python_file(file_path: str, source: Optional[str] = None) -> List[CodeChunk]:
    """Chunk a Python file using AST — one chunk per function/class.

    Falls back to line-based chunking if AST parsing fails.
    """
    if source is None:
        source = Path(file_path).read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        logger.warning("AST parse failed for %s, falling back to line-based", file_path)
        return chunk_by_lines(file_path, source)

    lines = source.splitlines()
    chunks: List[CodeChunk] = []
    node_ranges: List[tuple] = []  # (start, end, name, chunk_type)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = _node_end_line(node, len(lines))
            node_ranges.append((node.lineno, end_line, node.name, "function"))
        elif isinstance(node, ast.ClassDef):
            end_line = _node_end_line(node, len(lines))
            node_ranges.append((node.lineno, end_line, node.name, "class"))

    # Sort by start line
    node_ranges.sort(key=lambda x: x[0])

    # Collect top-level code between nodes
    prev_end = 0
    chunk_idx = 0
    for start, end, name, ctype in node_ranges:
        # Top-level code before this node
        if start - 1 > prev_end:
            top_content = "\n".join(lines[prev_end:start - 1]).strip()
            if top_content:
                chunk_idx += 1
                chunks.append(CodeChunk(
                    chunk_id=f"{Path(file_path).stem}_top_{chunk_idx}",
                    file_path=file_path,
                    chunk_type="top_level",
                    name=f"top_level_{chunk_idx}",
                    start_line=prev_end + 1,
                    end_line=start - 1,
                    content=top_content,
                ))

        # The node itself
        chunk_idx += 1
        node_content = "\n".join(lines[start - 1:end]).strip()
        chunks.append(CodeChunk(
            chunk_id=f"{Path(file_path).stem}_{ctype}_{name}",
            file_path=file_path,
            chunk_type=ctype,
            name=name,
            start_line=start,
            end_line=end,
            content=node_content,
        ))
        prev_end = end

    # Trailing top-level code
    if prev_end < len(lines):
        trailing = "\n".join(lines[prev_end:]).strip()
        if trailing:
            chunk_idx += 1
            chunks.append(CodeChunk(
                chunk_id=f"{Path(file_path).stem}_top_{chunk_idx}",
                file_path=file_path,
                chunk_type="top_level",
                name=f"top_level_{chunk_idx}",
                start_line=prev_end + 1,
                end_line=len(lines),
                content=trailing,
            ))

    return chunks


def chunk_markdown_file(file_path: str, source: Optional[str] = None) -> List[CodeChunk]:
    """Chunk a Markdown file by heading — one chunk per section."""
    if source is None:
        source = Path(file_path).read_text(encoding="utf-8")

    lines = source.splitlines()
    chunks: List[CodeChunk] = []

    # Find heading positions
    heading_positions: List[tuple] = []  # (line_idx, level, title)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            if title:
                heading_positions.append((idx, level, title))

    if not heading_positions:
        # No headings — return entire file as one chunk
        return [CodeChunk(
            chunk_id=f"{Path(file_path).stem}_full",
            file_path=file_path,
            chunk_type="block",
            name="full_document",
            start_line=1,
            end_line=len(lines),
            content=source,
        )]

    for i, (line_idx, level, title) in enumerate(heading_positions):
        if i + 1 < len(heading_positions):
            end_idx = heading_positions[i + 1][0]
        else:
            end_idx = len(lines)

        content = "\n".join(lines[line_idx:end_idx]).strip()
        safe_title = title.lower().replace(" ", "_")[:30]
        chunks.append(CodeChunk(
            chunk_id=f"{Path(file_path).stem}_{safe_title}",
            file_path=file_path,
            chunk_type="heading",
            name=title,
            start_line=line_idx + 1,
            end_line=end_idx,
            content=content,
        ))

    return chunks


def chunk_by_lines(
    file_path: str,
    source: Optional[str] = None,
    *,
    max_lines: int = 50,
) -> List[CodeChunk]:
    """Chunk any file by line count — generic fallback."""
    if source is None:
        source = Path(file_path).read_text(encoding="utf-8")

    lines = source.splitlines()
    chunks: List[CodeChunk] = []

    for i in range(0, len(lines), max_lines):
        block = lines[i:i + max_lines]
        content = "\n".join(block).strip()
        if not content:
            continue
        chunk_idx = i // max_lines + 1
        chunks.append(CodeChunk(
            chunk_id=f"{Path(file_path).stem}_block_{chunk_idx}",
            file_path=file_path,
            chunk_type="block",
            name=f"block_{chunk_idx}",
            start_line=i + 1,
            end_line=min(i + max_lines, len(lines)),
            content=content,
        ))

    return chunks


def chunk_file(file_path: str, source: Optional[str] = None) -> List[CodeChunk]:
    """Auto-detect file type and chunk accordingly."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".py":
        return chunk_python_file(file_path, source)
    elif suffix == ".md":
        return chunk_markdown_file(file_path, source)
    else:
        return chunk_by_lines(file_path, source)


def _node_end_line(node: ast.AST, max_lines: int) -> int:
    """Get the end line of an AST node, using end_lineno if available."""
    if hasattr(node, "end_lineno") and node.end_lineno is not None:
        return node.end_lineno
    # Fallback: estimate from body
    if hasattr(node, "body") and node.body:
        last = node.body[-1]
        return _node_end_line(last, max_lines)
    return getattr(node, "lineno", max_lines)


__all__ = ["CodeChunk", "chunk_file", "chunk_markdown_file", "chunk_python_file", "chunk_by_lines"]
