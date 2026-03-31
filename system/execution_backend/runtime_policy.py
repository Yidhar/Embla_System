from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from system.config import get_config


@dataclass(frozen=True)
class OsSandboxRuntimePolicy:
    profile_name: str
    resource_profile: str
    network_enabled: bool
    inject_offline_env: bool
    enforce_network_guard: bool
    default_command_timeout_seconds: int
    max_command_timeout_seconds: int
    default_python_timeout_seconds: int
    max_python_timeout_seconds: int
    default_watch_timeout_seconds: int
    max_watch_timeout_seconds: int


def resolve_os_sandbox_runtime_policy(profile_name: Any = "default") -> OsSandboxRuntimePolicy:
    cfg = get_config()
    sandbox_cfg = getattr(cfg, "sandbox", None)
    os_sandbox_cfg = getattr(sandbox_cfg, "os_sandbox", None)

    requested_profile = str(profile_name or getattr(os_sandbox_cfg, "runtime_profile", "default") or "default").strip() or "default"
    runtime_profiles = getattr(os_sandbox_cfg, "runtime_profiles", None)
    default_profile_name = str(getattr(os_sandbox_cfg, "runtime_profile", "default") or "default").strip() or "default"

    profile = None
    if isinstance(runtime_profiles, dict):
        profile = runtime_profiles.get(requested_profile) or runtime_profiles.get(default_profile_name) or runtime_profiles.get("default")
    if profile is None:
        profile = type(
            "OsSandboxProfileFallback",
            (),
            {
                "resource_profile": "standard",
                "network_enabled": False,
                "inject_offline_env": True,
                "default_command_timeout_seconds": 120,
                "max_command_timeout_seconds": 1200,
                "default_python_timeout_seconds": 15,
                "max_python_timeout_seconds": 180,
                "default_watch_timeout_seconds": 600,
                "max_watch_timeout_seconds": 86400,
            },
        )()

    return OsSandboxRuntimePolicy(
        profile_name=requested_profile,
        resource_profile=str(getattr(profile, "resource_profile", "standard") or "standard").strip() or "standard",
        network_enabled=bool(getattr(profile, "network_enabled", False)),
        inject_offline_env=bool(getattr(profile, "inject_offline_env", True)),
        enforce_network_guard=bool(getattr(os_sandbox_cfg, "enforce_network_guard", True)),
        default_command_timeout_seconds=max(1, int(getattr(profile, "default_command_timeout_seconds", 120) or 120)),
        max_command_timeout_seconds=max(1, int(getattr(profile, "max_command_timeout_seconds", 1200) or 1200)),
        default_python_timeout_seconds=max(1, int(getattr(profile, "default_python_timeout_seconds", 15) or 15)),
        max_python_timeout_seconds=max(1, int(getattr(profile, "max_python_timeout_seconds", 180) or 180)),
        default_watch_timeout_seconds=max(1, int(getattr(profile, "default_watch_timeout_seconds", 600) or 600)),
        max_watch_timeout_seconds=max(1, int(getattr(profile, "max_watch_timeout_seconds", 86400) or 86400)),
    )


def resolve_worktree_fallback_backend(*, workspace_mode: str, workspace_root: str) -> str:
    normalized_mode = str(workspace_mode or "").strip().lower()
    if normalized_mode == "worktree" and str(workspace_root or "").strip():
        return "os_sandbox"
    return "native"
