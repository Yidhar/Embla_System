#!/usr/bin/env python3
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from typing import List, Optional
import xml.etree.ElementTree as ET


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}


def _extract_paragraph_text(paragraph: ET.Element) -> str:
    texts: List[str] = []
    for node in paragraph.iter(f"{{{WORD_NS}}}t"):
        if node.text:
            texts.append(node.text)
    return "".join(texts).strip()


def _extract_table_rows(table: ET.Element) -> List[List[str]]:
    rows: List[List[str]] = []
    for row in table.findall("w:tr", NS):
        cells: List[str] = []
        for cell in row.findall("w:tc", NS):
            cell_texts: List[str] = []
            for node in cell.iter(f"{{{WORD_NS}}}t"):
                if node.text:
                    cell_texts.append(node.text)
            cells.append("".join(cell_texts).strip())
        if cells:
            rows.append(cells)
    return rows


def _read_document_xml(docx_path: Path) -> ET.Element:
    with zipfile.ZipFile(docx_path, "r") as archive:
        xml_bytes = archive.read("word/document.xml")
    return ET.fromstring(xml_bytes)


def extract_docx_text(docx_path: Path) -> List[str]:
    root = _read_document_xml(docx_path)
    body = root.find("w:body", NS)
    if body is None:
        return []

    output_lines: List[str] = []
    for child in list(body):
        tag = child.tag
        if tag.endswith("}p"):
            paragraph = _extract_paragraph_text(child)
            if paragraph:
                output_lines.append(paragraph)
        elif tag.endswith("}tbl"):
            table_rows = _extract_table_rows(child)
            if table_rows:
                output_lines.append("[TABLE]")
                for row in table_rows:
                    output_lines.append("\t".join(row))
                output_lines.append("[/TABLE]")
    return output_lines


def _write_output(lines: List[str], output_path: Optional[Path]) -> None:
    content = "\n".join(lines)
    if output_path is None:
        print(content)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract text and tables from a .docx file.")
    parser.add_argument("path", type=str, help="Path to the .docx file")
    parser.add_argument("--output", type=str, default=None, help="Output file path (stdout if omitted)")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    docx_path = Path(args.path).expanduser().resolve()
    if not docx_path.exists():
        raise FileNotFoundError(f"File not found: {docx_path}")

    lines = extract_docx_text(docx_path)
    output_path = Path(args.output).expanduser().resolve() if args.output else None
    _write_output(lines, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
