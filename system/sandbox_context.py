from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def normalize_execution_backend(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    aliases = {
        "": "native",
        "default": "native",
        "local": "native",
        "host": "native",
        "sandbox": "os_sandbox",
        "os": "os_sandbox",
        "os_sandbox_worktree": "os_sandbox",
        "worktree": "os_sandbox",
        "box": "boxlite",
        "vm": "boxlite",
    }
    text = aliases.get(text, text)
    if text not in {"native", "os_sandbox", "boxlite"}:
        raise ValueError(f"unsupported execution_backend: {raw}")
    return text


def inherit_execution_metadata(parent_metadata: Mapping[str, Any]) -> Dict[str, Any]:
    inherited: Dict[str, Any] = {}
    for key in (
        "execution_backend",
        "execution_backend_requested",
        "execution_root",
        "execution_profile",
        "sandbox_policy",
        "network_policy",
        "resource_profile",
        "box_profile",
        "box_provider",
        "box_mount_mode",
        "box_fallback_reason",
    ):
        value = parent_metadata.get(key)
        if value not in (None, ""):
            inherited[key] = value
    return inherited


@dataclass(frozen=True)
class SandboxContext:
    session_id: str = ""
    workspace_mode: str = "project"
    workspace_origin_root: str = ""
    workspace_host_root: str = ""
    workspace_ref: str = ""
    workspace_head_sha: str = ""
    workspace_submission_state: str = "sandboxed"
    workspace_change_id: str = ""
    execution_backend: str = "native"
    execution_backend_requested: str = "native"
    execution_root: str = ""
    execution_profile: str = "default"
    sandbox_policy: str = "default"
    network_policy: str = "disabled"
    resource_profile: str = "standard"
    box_profile: str = "default"
    box_provider: str = "sdk"
    box_name: str = ""
    box_id: str = ""
    box_mount_mode: str = "rw"
    box_fallback_reason: str = ""
    project_root: str = str(_PROJECT_ROOT)

    @classmethod
    def default(cls, *, session_id: str = "", project_root: str | Path | None = None) -> "SandboxContext":
        root = Path(project_root).resolve() if project_root else _PROJECT_ROOT
        return cls(
            session_id=str(session_id or "").strip(),
            workspace_mode="project",
            workspace_origin_root=str(root),
            workspace_host_root="",
            execution_backend="native",
            execution_backend_requested="native",
            execution_root=str(root),
            sandbox_policy="default",
            network_policy="disabled",
            resource_profile="standard",
            project_root=str(root),
        )

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, Any],
        *,
        session_id: str = "",
        project_root: str | Path | None = None,
    ) -> "SandboxContext":
        root = Path(project_root).resolve() if project_root else _PROJECT_ROOT
        workspace_mode = str(metadata.get("workspace_mode") or "project").strip().lower() or "project"
        workspace_origin_root = str(metadata.get("workspace_origin_root") or root).strip() or str(root)
        workspace_host_root = str(metadata.get("workspace_root") or "").strip()
        requested_backend_raw = metadata.get("execution_backend_requested")
        effective_backend_raw = metadata.get("execution_backend")
        execution_backend = normalize_execution_backend(effective_backend_raw or requested_backend_raw or "native")
        execution_backend_requested = normalize_execution_backend(requested_backend_raw or execution_backend)
        default_execution_root = workspace_host_root or str(root)
        execution_root = str(metadata.get("execution_root") or default_execution_root).strip() or default_execution_root
        return cls(
            session_id=str(session_id or "").strip(),
            workspace_mode=workspace_mode,
            workspace_origin_root=workspace_origin_root,
            workspace_host_root=workspace_host_root,
            workspace_ref=str(metadata.get("workspace_ref") or "").strip(),
            workspace_head_sha=str(metadata.get("workspace_head_sha") or "").strip(),
            workspace_submission_state=str(metadata.get("workspace_submission_state") or "sandboxed").strip() or "sandboxed",
            workspace_change_id=str(metadata.get("workspace_change_id") or "").strip(),
            execution_backend=execution_backend,
            execution_backend_requested=execution_backend_requested,
            execution_root=execution_root,
            execution_profile=str(metadata.get("execution_profile") or "default").strip() or "default",
            sandbox_policy=str(metadata.get("sandbox_policy") or metadata.get("execution_profile") or "default").strip() or "default",
            network_policy=str(metadata.get("network_policy") or "disabled").strip() or "disabled",
            resource_profile=str(metadata.get("resource_profile") or "standard").strip() or "standard",
            box_profile=str(metadata.get("box_profile") or "default").strip() or "default",
            box_provider=str(metadata.get("box_provider") or "sdk").strip() or "sdk",
            box_name=str(metadata.get("box_name") or "").strip(),
            box_id=str(metadata.get("box_id") or "").strip(),
            box_mount_mode=str(metadata.get("box_mount_mode") or "rw").strip() or "rw",
            box_fallback_reason=str(metadata.get("box_fallback_reason") or "").strip(),
            project_root=str(root),
        )

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "execution_backend": self.execution_backend,
            "execution_backend_requested": self.execution_backend_requested,
            "execution_root": self.execution_root,
            "execution_profile": self.execution_profile,
            "sandbox_policy": self.sandbox_policy,
            "network_policy": self.network_policy,
            "resource_profile": self.resource_profile,
            "box_profile": self.box_profile,
            "box_provider": self.box_provider,
            "box_name": self.box_name,
            "box_id": self.box_id,
            "box_mount_mode": self.box_mount_mode,
            "box_fallback_reason": self.box_fallback_reason,
        }
