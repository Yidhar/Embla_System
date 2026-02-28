#!/usr/bin/env python3
"""Detect runtime imports that still depend on legacy shim modules."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


LEGACY_SHIM_MODULES = (
    "system.global_mutex",
    "system.policy_firewall",
    "system.watchdog_daemon",
    "system.brainstem_supervisor",
    "autonomous.event_log.event_schema",
    "autonomous.event_log.event_store",
    "autonomous.event_log.topic_event_bus",
)

DEFAULT_SCAN_ROOTS = (
    "apiserver",
    "autonomous",
    "system",
    "scripts",
    "core",
)
DEFAULT_OUTPUT = Path("scratch/reports/ws28_legacy_shim_imports_check_ws28_030.json")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_unix_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _module_is_legacy(module_name: str) -> bool:
    normalized = str(module_name or "").strip()
    if not normalized:
        return False
    for legacy in LEGACY_SHIM_MODULES:
        if normalized == legacy or normalized.startswith(f"{legacy}."):
            return True
    return False


def _iter_python_files(repo_root: Path, roots: Iterable[str], *, include_tests: bool) -> List[Path]:
    files: List[Path] = []
    for raw_root in roots:
        rel = str(raw_root or "").strip()
        if not rel:
            continue
        root = (repo_root / rel).resolve()
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if not include_tests and "tests" in path.parts:
                continue
            files.append(path)
    files.sort()
    return files


@dataclass(frozen=True)
class ImportHit:
    file_path: str
    line: int
    import_kind: str
    module: str
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line": int(self.line),
            "import_kind": self.import_kind,
            "module": self.module,
            "evidence": self.evidence,
        }


def _scan_file_for_legacy_imports(repo_root: Path, file_path: Path) -> List[ImportHit]:
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    hits: List[ImportHit] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = str(alias.name or "").strip()
                if not _module_is_legacy(module_name):
                    continue
                hits.append(
                    ImportHit(
                        file_path=_to_unix_path(file_path.resolve().relative_to(repo_root.resolve())),
                        line=int(getattr(node, "lineno", 1) or 1),
                        import_kind="import",
                        module=module_name,
                        evidence=f"import {module_name}",
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = str(node.module or "").strip()
            if not _module_is_legacy(module_name):
                continue
            imported_names = ", ".join(str(alias.name or "").strip() for alias in node.names if str(alias.name or "").strip())
            evidence = f"from {module_name} import {imported_names}" if imported_names else f"from {module_name} import *"
            hits.append(
                ImportHit(
                    file_path=_to_unix_path(file_path.resolve().relative_to(repo_root.resolve())),
                    line=int(getattr(node, "lineno", 1) or 1),
                    import_kind="from_import",
                    module=module_name,
                    evidence=evidence,
                )
            )
    return hits


def run_check_legacy_shim_imports_ws28_030(
    *,
    repo_root: Path,
    output_file: Path = DEFAULT_OUTPUT,
    roots: Iterable[str] = DEFAULT_SCAN_ROOTS,
    include_tests: bool = False,
) -> Dict[str, Any]:
    root = repo_root.resolve()
    output_path = output_file if output_file.is_absolute() else root / output_file
    scanned_files = _iter_python_files(root, roots, include_tests=bool(include_tests))
    hits: List[ImportHit] = []
    for path in scanned_files:
        hits.extend(_scan_file_for_legacy_imports(root, path))

    report: Dict[str, Any] = {
        "task_id": "NGA-WS28-030",
        "scenario": "legacy_shim_imports_check_ws28_030",
        "generated_at": _utc_iso_now(),
        "repo_root": _to_unix_path(root),
        "roots": [str(item) for item in roots],
        "include_tests": bool(include_tests),
        "legacy_modules": list(LEGACY_SHIM_MODULES),
        "scanned_file_count": len(scanned_files),
        "hit_count": len(hits),
        "passed": len(hits) == 0,
        "hits": [hit.to_dict() for hit in hits],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output_file"] = _to_unix_path(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect runtime legacy-shim imports")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output report path",
    )
    parser.add_argument(
        "--roots",
        nargs="*",
        default=list(DEFAULT_SCAN_ROOTS),
        help="Relative roots to scan",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests directories in scan scope",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when hit_count > 0")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_check_legacy_shim_imports_ws28_030(
        repo_root=args.repo_root,
        output_file=args.output,
        roots=list(args.roots),
        include_tests=bool(args.include_tests),
    )
    print(
        json.dumps(
            {
                "passed": bool(report.get("passed")),
                "hit_count": int(report.get("hit_count") or 0),
                "output": str(report.get("output_file") or ""),
            },
            ensure_ascii=False,
        )
    )
    if args.strict and not bool(report.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
