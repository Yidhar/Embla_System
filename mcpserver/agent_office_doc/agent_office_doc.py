"""MCP office document parser agent (docx/xlsx)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_XLSX_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_RELS_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


class OfficeDocAgent:
    """Extract text/tables from local Office documents."""

    name = "Office Doc Agent"

    async def handle_handoff(self, task: Dict[str, Any]) -> str:
        tool_name = str(task.get("tool_name") or "").strip().lower()
        tool_aliases = {
            "read_docx": "read_docx",
            "parse_docx": "read_docx",
            "extract_docx": "read_docx",
            "read_xlsx": "read_xlsx",
            "parse_xlsx": "read_xlsx",
            "extract_xlsx": "read_xlsx",
        }
        action = tool_aliases.get(tool_name)
        if not action:
            return self._json_error(
                "未知工具，仅支持 read_docx/read_xlsx",
                tool_name=tool_name,
            )

        path_value = str(task.get("path") or task.get("file_path") or "").strip()
        if not path_value:
            return self._json_error("缺少 path 参数", tool_name=tool_name)

        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[2] / path).resolve()
        if not path.exists() or not path.is_file():
            return self._json_error("文件不存在", tool_name=tool_name)

        try:
            if action == "read_docx":
                max_chars = self._parse_max_chars(task.get("max_chars"), default_value=12000)
                parsed = self._read_docx(path=path, max_chars=max_chars)
            else:
                sheet_name = str(task.get("sheet_name") or "").strip() or None
                max_rows = self._parse_max_rows(task.get("max_rows"), default_value=80)
                max_chars = self._parse_max_chars(task.get("max_chars"), default_value=12000)
                parsed = self._read_xlsx(
                    path=path,
                    sheet_name=sheet_name,
                    max_rows=max_rows,
                    max_chars=max_chars,
                )

            return json.dumps(
                {
                    "status": "ok",
                    "message": "文档解析完成",
                    "data": parsed,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return self._json_error(str(exc), tool_name=tool_name)

    def _read_docx(self, *, path: Path, max_chars: int) -> Dict[str, Any]:
        with zipfile.ZipFile(path, "r") as archive:
            try:
                xml_bytes = archive.read("word/document.xml")
            except KeyError as exc:
                raise RuntimeError("无效 docx：缺少 word/document.xml") from exc

        root = ET.fromstring(xml_bytes)
        paragraphs: List[str] = []
        for p_node in root.findall(".//w:p", _DOCX_NS):
            runs = [str(t.text or "") for t in p_node.findall(".//w:t", _DOCX_NS)]
            paragraph = "".join(runs).strip()
            if paragraph:
                paragraphs.append(paragraph)

        full_text = "\n".join(paragraphs)
        truncated = False
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars]
            truncated = True

        return {
            "file_type": "docx",
            "path": str(path).replace("\\", "/"),
            "paragraph_count": len(paragraphs),
            "content_text": full_text,
            "content_length": len(full_text),
            "truncated": truncated,
        }

    def _read_xlsx(
        self,
        *,
        path: Path,
        sheet_name: Optional[str],
        max_rows: int,
        max_chars: int,
    ) -> Dict[str, Any]:
        with zipfile.ZipFile(path, "r") as archive:
            workbook_xml = archive.read("xl/workbook.xml")
            rels_xml = archive.read("xl/_rels/workbook.xml.rels")
            shared_strings = self._read_shared_strings(archive)
            sheets = self._read_sheet_targets(workbook_xml=workbook_xml, rels_xml=rels_xml)
            if not sheets:
                raise RuntimeError("xlsx 工作簿未发现工作表")

            selected = None
            if sheet_name:
                for item in sheets:
                    if item["name"] == sheet_name:
                        selected = item
                        break
            if selected is None:
                selected = sheets[0]

            sheet_xml = archive.read(selected["target"])
            rows = self._read_sheet_rows(sheet_xml=sheet_xml, shared_strings=shared_strings, max_rows=max_rows)

        preview_text = json.dumps(rows, ensure_ascii=False)
        truncated = False
        if len(preview_text) > max_chars:
            preview_text = preview_text[:max_chars]
            truncated = True

        return {
            "file_type": "xlsx",
            "path": str(path).replace("\\", "/"),
            "sheet_name": selected["name"],
            "available_sheets": [item["name"] for item in sheets],
            "row_count": len(rows),
            "rows": rows,
            "rows_preview": preview_text,
            "preview_truncated": truncated,
        }

    @staticmethod
    def _read_shared_strings(archive: zipfile.ZipFile) -> List[str]:
        path = "xl/sharedStrings.xml"
        if path not in archive.namelist():
            return []
        root = ET.fromstring(archive.read(path))
        rows: List[str] = []
        for item in root.findall(".//main:si", _XLSX_NS):
            text_parts = [str(node.text or "") for node in item.findall(".//main:t", _XLSX_NS)]
            rows.append("".join(text_parts))
        return rows

    @staticmethod
    def _read_sheet_targets(*, workbook_xml: bytes, rels_xml: bytes) -> List[Dict[str, str]]:
        workbook = ET.fromstring(workbook_xml)
        rels = ET.fromstring(rels_xml)

        rel_map: Dict[str, str] = {}
        for rel_node in rels.findall("rel:Relationship", _RELS_NS):
            rid = str(rel_node.attrib.get("Id") or "").strip()
            target = str(rel_node.attrib.get("Target") or "").strip()
            if rid and target:
                rel_map[rid] = target

        sheets: List[Dict[str, str]] = []
        for sheet in workbook.findall(".//main:sheet", _XLSX_NS):
            name = str(sheet.attrib.get("name") or "").strip()
            rid = str(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or "").strip()
            target = rel_map.get(rid, "")
            if not name or not target:
                continue
            if not target.startswith("xl/"):
                target = f"xl/{target.lstrip('/')}"
            sheets.append({"name": name, "target": target})
        return sheets

    @staticmethod
    def _read_sheet_rows(*, sheet_xml: bytes, shared_strings: List[str], max_rows: int) -> List[Dict[str, str]]:
        root = ET.fromstring(sheet_xml)
        rows: List[Dict[str, str]] = []
        for row_node in root.findall(".//main:sheetData/main:row", _XLSX_NS):
            row_data: Dict[str, str] = {}
            for cell in row_node.findall("main:c", _XLSX_NS):
                ref = str(cell.attrib.get("r") or "").strip()
                cell_type = str(cell.attrib.get("t") or "").strip()
                if not ref:
                    continue
                value = ""
                if cell_type == "s":
                    shared_idx_node = cell.find("main:v", _XLSX_NS)
                    if shared_idx_node is not None and shared_idx_node.text is not None:
                        try:
                            idx = int(shared_idx_node.text)
                            value = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
                        except (TypeError, ValueError):
                            value = ""
                elif cell_type == "inlineStr":
                    text_nodes = cell.findall(".//main:t", _XLSX_NS)
                    value = "".join(str(node.text or "") for node in text_nodes)
                else:
                    value_node = cell.find("main:v", _XLSX_NS)
                    if value_node is not None and value_node.text is not None:
                        value = str(value_node.text)

                row_data[ref] = value

            if row_data:
                rows.append(row_data)
            if len(rows) >= max_rows:
                break
        return rows

    @staticmethod
    def _parse_max_rows(value: Any, *, default_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default_value
        return max(1, min(5000, parsed))

    @staticmethod
    def _parse_max_chars(value: Any, *, default_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default_value
        return max(100, min(500000, parsed))

    @staticmethod
    def _json_error(message: str, *, tool_name: str) -> str:
        return json.dumps(
            {
                "status": "error",
                "message": message,
                "tool_name": tool_name,
                "data": {},
            },
            ensure_ascii=False,
        )
