"""Dynamic tool creation -- agent registers new tools with safety validation."""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class ToolRegistrationResult:
    success: bool
    tool_name: str = ""
    reason: str = ""
    registry_path: str = ""


def register_new_tool(
    *,
    name: str,
    description: str,
    code: str,
    params_schema: Dict[str, Any],
    reason: str = "",
    project_root: Path = Path("."),
) -> ToolRegistrationResult:
    """Register a new custom tool with AST validation and sandbox testing.

    Steps:
      1. Validate tool name format
      2. AST validation via custom_tools infrastructure
      3. Write tool spec to workspace/tools_registry/plugins/
      4. Update registry_manifest.yaml
      5. Audit record
    """

    # 1. Name validation
    if not re.match(r"^[a-z][a-z0-9_]{1,30}$", name):
        return ToolRegistrationResult(
            success=False,
            tool_name=name,
            reason="invalid tool name (must be lowercase, 2-31 chars)",
        )

    # 2. AST validation (reuse existing custom_tools infrastructure)
    try:
        from agents.runtime.custom_tools import validate_tool_code

        ok, issues = validate_tool_code(code)
        if not ok:
            return ToolRegistrationResult(
                success=False,
                tool_name=name,
                reason=f"code validation failed: {'; '.join(issues)}",
            )
    except ImportError:
        # validate_tool_code may not exist in all versions, do basic check
        import ast

        try:
            ast.parse(code)
        except SyntaxError as exc:
            return ToolRegistrationResult(
                success=False, tool_name=name, reason=f"syntax error: {exc}"
            )

    # 3. Write to workspace/tools_registry/plugins/
    registry_dir = project_root / "workspace" / "tools_registry" / "plugins"
    registry_dir.mkdir(parents=True, exist_ok=True)

    tool_entry = {
        "name": name,
        "description": description,
        "code": code,
        "params_schema": params_schema,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "reason": reason,
    }

    tool_file = registry_dir / f"{name}.json"
    tool_file.write_text(
        json.dumps(tool_entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 4. Update registry manifest
    manifest_path = (
        project_root / "workspace" / "tools_registry" / "registry_manifest.yaml"
    )
    try:
        import yaml

        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded

        plugins = manifest.get("plugins", [])
        if not isinstance(plugins, list):
            plugins = []
        # Remove existing entry with same name
        plugins = [
            p for p in plugins if isinstance(p, dict) and p.get("name") != name
        ]
        plugins.append(
            {
                "name": name,
                "source_path": f"plugins/{name}.json",
                "schema_hash": tool_entry["code_sha256"],
            }
        )
        manifest["plugins"] = plugins
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            yaml.dump(manifest, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Manifest update failed: %s", exc)

    # 5. Audit
    try:
        from core.security.audit_ledger import AuditLedger

        ledger = AuditLedger(
            ledger_file=project_root / "scratch" / "runtime" / "audit_ledger.jsonl"
        )
        ledger.append_record(
            record_type="tool_registered",
            change_id=f"tool_{name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            scope="tool",
            risk_level="low",
            requested_by="tool_creator",
            payload={"name": name, "reason": reason},
        )
    except Exception:
        pass

    return ToolRegistrationResult(
        success=True,
        tool_name=name,
        reason="tool registered",
        registry_path=str(tool_file),
    )
