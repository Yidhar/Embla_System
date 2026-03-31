"""Child-agent profile registry for dynamic prompt/tool configuration.

Profiles are lightweight presets resolved at `spawn_child_agent` time. They let
operators define stable `agent_type` values that map onto the existing lifecycle
roles (`expert` / `dev` / `review`) plus prompt blocks and tool capabilities.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import json5

from agents.prompt_engine import get_system_prompts_root
from agents.runtime.tool_profiles import TOOL_PROFILE_PRESETS, normalize_tool_subset

logger = logging.getLogger(__name__)

_ALLOWED_AGENT_ROLES = {"expert", "dev", "review"}
_DEFAULT_REGISTRY_PATH = get_system_prompts_root() / "specs" / "agent_registry.spec"
_AGENT_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DEFAULT_AGENT_PROFILE_SPEC = {
    "schema_version": "ws31-agent-profile-v1",
    "profiles": [
        {
            "agent_type": "expert_default",
            "role": "expert",
            "label": "Default Expert",
            "description": "Fallback expert profile used when no explicit agent_type is provided.",
            "prompt_blocks": [],
            "tool_profile": "",
            "tool_subset": [],
            "enabled": True,
            "default_for_role": True,
            "builtin": True,
        },
        {
            "agent_type": "dev_default",
            "role": "dev",
            "label": "Default Dev",
            "description": "Fallback dev profile used when no explicit agent_type is provided.",
            "prompt_blocks": [],
            "tool_profile": "",
            "tool_subset": [],
            "enabled": True,
            "default_for_role": True,
            "builtin": True,
        },
        {
            "agent_type": "code_reviewer",
            "role": "review",
            "label": "Code Reviewer",
            "description": "Independent review agent preset with the canonical code-review prompt block.",
            "prompt_blocks": ["agents/review/code_reviewer.md"],
            "tool_profile": "review",
            "tool_subset": [],
            "enabled": True,
            "default_for_role": True,
            "builtin": True,
        },
    ],
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_prompts_root() -> str:
    return str(get_system_prompts_root())


def _normalize_prompts_root(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    try:
        if Path(text).expanduser().resolve() == Path(_default_prompts_root()).resolve():
            return ""
    except Exception:
        logger.debug("normalize prompts_root fallback: %s", text, exc_info=True)
    return text


def _resolve_registry_path(spec_path: Optional[Path] = None) -> Path:
    candidate = Path(spec_path) if spec_path is not None else _DEFAULT_REGISTRY_PATH
    return candidate.resolve()


def _normalize_agent_type(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError("agent_type is required")
    if not _AGENT_TYPE_PATTERN.match(text):
        raise ValueError("agent_type must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    return text


def _normalize_agent_role(raw_value: Any) -> str:
    text = str(raw_value or "").strip().lower()
    if text not in _ALLOWED_AGENT_ROLES:
        raise ValueError(f"role must be one of {sorted(_ALLOWED_AGENT_ROLES)}")
    return text


def _normalize_string_list(raw_value: Any) -> List[str]:
    if not isinstance(raw_value, list):
        return []
    rows: List[str] = []
    seen: set[str] = set()
    for item in raw_value:
        text = str(item or "").strip().replace("\\", "/")
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _normalize_tool_profile(raw_value: Any) -> str:
    text = str(raw_value or "").strip().lower()
    if not text:
        return ""
    if text in TOOL_PROFILE_PRESETS:
        return text
    return text


def _normalize_profile(raw_profile: Dict[str, Any], *, previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prior = dict(previous or {})
    now = _utc_now_iso()
    agent_type = _normalize_agent_type(raw_profile.get("agent_type") or raw_profile.get("name") or prior.get("agent_type") or "")
    role = _normalize_agent_role(raw_profile.get("role") or prior.get("role") or "dev")
    label = str(raw_profile.get("label") or prior.get("label") or agent_type).strip() or agent_type
    description = str(raw_profile.get("description") or prior.get("description") or "").strip()
    prompt_blocks = _normalize_string_list(raw_profile.get("prompt_blocks") if "prompt_blocks" in raw_profile else prior.get("prompt_blocks", []))
    tool_profile = _normalize_tool_profile(raw_profile.get("tool_profile") if "tool_profile" in raw_profile else prior.get("tool_profile", ""))
    tool_subset_source = raw_profile.get("tool_subset") if "tool_subset" in raw_profile else prior.get("tool_subset", [])
    tool_subset = normalize_tool_subset(tool_subset_source if isinstance(tool_subset_source, list) else [])
    enabled = bool(raw_profile.get("enabled") if "enabled" in raw_profile else prior.get("enabled", True))
    default_for_role = bool(raw_profile.get("default_for_role") if "default_for_role" in raw_profile else prior.get("default_for_role", False))
    builtin = bool(prior.get("builtin", raw_profile.get("builtin", False)))
    if "prompts_root" in raw_profile:
        prompts_root = _normalize_prompts_root(raw_profile.get("prompts_root"))
    else:
        prompts_root = _normalize_prompts_root(prior.get("prompts_root"))
    created_at = str(prior.get("created_at") or raw_profile.get("created_at") or now).strip() or now
    updated_at = now
    profile = {
        "agent_type": agent_type,
        "role": role,
        "label": label,
        "description": description,
        "prompt_blocks": prompt_blocks,
        "tool_profile": tool_profile,
        "tool_subset": tool_subset,
        "enabled": enabled,
        "default_for_role": default_for_role,
        "builtin": builtin,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    if prompts_root:
        profile["prompts_root"] = prompts_root
    return profile


def _sort_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        profiles,
        key=lambda item: (
            str(item.get("role") or ""),
            0 if bool(item.get("default_for_role")) else 1,
            0 if bool(item.get("builtin")) else 1,
            str(item.get("agent_type") or ""),
        ),
    )


def _build_registry_view(profiles: List[Dict[str, Any]], *, registry_path: Path, exists_on_disk: bool, schema_version: str) -> Dict[str, Any]:
    sorted_profiles = _sort_profiles([dict(item) for item in profiles])
    profiles_map = {str(item.get("agent_type") or ""): dict(item) for item in sorted_profiles}
    defaults_by_role: Dict[str, Dict[str, Any]] = {}
    for item in sorted_profiles:
        role = str(item.get("role") or "")
        if not role or role in defaults_by_role:
            continue
        if bool(item.get("enabled")) and bool(item.get("default_for_role")):
            defaults_by_role[role] = dict(item)
    return {
        "schema_version": schema_version,
        "registry_path": str(registry_path),
        "exists_on_disk": bool(exists_on_disk),
        "allowed_roles": sorted(_ALLOWED_AGENT_ROLES),
        "profiles": sorted_profiles,
        "profiles_map": profiles_map,
        "defaults_by_role": defaults_by_role,
    }


def load_agent_profile_registry(*, spec_path: Optional[Path] = None) -> Dict[str, Any]:
    registry_path = _resolve_registry_path(spec_path)
    loaded_payload: Dict[str, Any] = {}
    exists_on_disk = registry_path.exists()
    if exists_on_disk:
        try:
            parsed = json5.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                loaded_payload = parsed
        except Exception as exc:
            logger.warning("load agent_registry.spec failed: %s", exc)

    merged_profiles: Dict[str, Dict[str, Any]] = {}
    for raw in _DEFAULT_AGENT_PROFILE_SPEC["profiles"]:
        normalized = _normalize_profile(raw)
        merged_profiles[normalized["agent_type"]] = normalized

    raw_profiles = loaded_payload.get("profiles") if isinstance(loaded_payload.get("profiles"), list) else []
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            continue
        try:
            agent_type = _normalize_agent_type(raw.get("agent_type") or raw.get("name") or "")
            previous = merged_profiles.get(agent_type)
            merged_profiles[agent_type] = _normalize_profile(raw, previous=previous)
        except Exception as exc:
            logger.warning("ignoring invalid agent profile entry: %s", exc)

    return _build_registry_view(
        list(merged_profiles.values()),
        registry_path=registry_path,
        exists_on_disk=exists_on_disk,
        schema_version=str(loaded_payload.get("schema_version") or _DEFAULT_AGENT_PROFILE_SPEC["schema_version"]),
    )


def save_agent_profile_registry(profiles: List[Dict[str, Any]], *, spec_path: Optional[Path] = None, schema_version: Optional[str] = None) -> Dict[str, Any]:
    registry_path = _resolve_registry_path(spec_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_profiles: Dict[str, Dict[str, Any]] = {}
    for raw in profiles:
        if not isinstance(raw, dict):
            continue
        agent_type = _normalize_agent_type(raw.get("agent_type") or raw.get("name") or "")
        previous = normalized_profiles.get(agent_type)
        normalized_profiles[agent_type] = _normalize_profile(raw, previous=previous)

    payload = {
        "schema_version": str(schema_version or _DEFAULT_AGENT_PROFILE_SPEC["schema_version"]),
        "profiles": _sort_profiles(list(normalized_profiles.values())),
    }
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_agent_profile_registry(spec_path=registry_path)


def list_agent_profiles(*, spec_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return list(load_agent_profile_registry(spec_path=spec_path).get("profiles") or [])


def get_agent_profile(agent_type: str, *, spec_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    normalized_agent_type = _normalize_agent_type(agent_type)
    registry = load_agent_profile_registry(spec_path=spec_path)
    row = registry.get("profiles_map", {}).get(normalized_agent_type)
    return dict(row) if isinstance(row, dict) else None


def upsert_agent_profile(raw_profile: Dict[str, Any], *, spec_path: Optional[Path] = None) -> Dict[str, Any]:
    registry = load_agent_profile_registry(spec_path=spec_path)
    profiles = [dict(item) for item in registry.get("profiles") or [] if isinstance(item, dict)]
    agent_type = _normalize_agent_type(raw_profile.get("agent_type") or raw_profile.get("name") or "")
    existing_map = {str(item.get("agent_type") or ""): idx for idx, item in enumerate(profiles)}
    previous = registry.get("profiles_map", {}).get(agent_type)
    next_profile = _normalize_profile(raw_profile, previous=previous if isinstance(previous, dict) else None)

    if next_profile["default_for_role"]:
        now = _utc_now_iso()
        for item in profiles:
            if str(item.get("agent_type") or "") == next_profile["agent_type"]:
                continue
            if str(item.get("role") or "") == next_profile["role"] and bool(item.get("default_for_role")):
                item["default_for_role"] = False
                item["updated_at"] = now

    existing_index = existing_map.get(agent_type)
    if existing_index is None:
        profiles.append(next_profile)
    else:
        profiles[existing_index] = next_profile

    saved = save_agent_profile_registry(profiles, spec_path=spec_path, schema_version=registry.get("schema_version"))
    resolved = saved.get("profiles_map", {}).get(agent_type)
    return dict(resolved) if isinstance(resolved, dict) else next_profile


def delete_agent_profile(agent_type: str, *, spec_path: Optional[Path] = None) -> Dict[str, Any]:
    normalized_agent_type = _normalize_agent_type(agent_type)
    registry = load_agent_profile_registry(spec_path=spec_path)
    profiles = [dict(item) for item in registry.get("profiles") or [] if isinstance(item, dict)]
    target = registry.get("profiles_map", {}).get(normalized_agent_type)
    if not isinstance(target, dict):
        raise KeyError(f"agent profile not found: {normalized_agent_type}")
    if bool(target.get("builtin")):
        raise ValueError(f"builtin agent profile cannot be deleted: {normalized_agent_type}")
    filtered = [item for item in profiles if str(item.get("agent_type") or "") != normalized_agent_type]
    save_agent_profile_registry(filtered, spec_path=spec_path, schema_version=registry.get("schema_version"))
    return dict(target)


def resolve_agent_profile_defaults(
    *,
    role: str,
    agent_type: str = "",
    prompt_blocks: Optional[List[str]] = None,
    tool_profile: Any = None,
    tool_subset: Optional[List[Any]] = None,
    spec_path: Optional[Path] = None,
) -> Dict[str, Any]:
    normalized_role = _normalize_agent_role(role)
    normalized_prompt_blocks = _normalize_string_list(prompt_blocks if isinstance(prompt_blocks, list) else [])
    explicit_tool_profile = _normalize_tool_profile(tool_profile)
    explicit_tool_subset = normalize_tool_subset(tool_subset if isinstance(tool_subset, list) else [])
    registry = load_agent_profile_registry(spec_path=spec_path)

    resolved_profile: Optional[Dict[str, Any]] = None
    source = "explicit"
    normalized_agent_type = str(agent_type or "").strip()
    if normalized_agent_type:
        normalized_agent_type = _normalize_agent_type(normalized_agent_type)
        profile = registry.get("profiles_map", {}).get(normalized_agent_type)
        if not isinstance(profile, dict):
            raise KeyError(f"agent profile not found: {normalized_agent_type}")
        if not bool(profile.get("enabled", True)):
            raise ValueError(f"agent profile disabled: {normalized_agent_type}")
        if str(profile.get("role") or "") != normalized_role:
            raise ValueError(
                f"agent profile role mismatch: requested={normalized_role} profile={str(profile.get('role') or '')}"
            )
        resolved_profile = dict(profile)
        source = "agent_type"
    elif not normalized_prompt_blocks and not explicit_tool_profile and not explicit_tool_subset:
        profile = registry.get("defaults_by_role", {}).get(normalized_role)
        if isinstance(profile, dict) and bool(profile.get("enabled", True)):
            resolved_profile = dict(profile)
            normalized_agent_type = str(profile.get("agent_type") or "")
            source = "role_default"

    resolved_prompt_blocks = list(normalized_prompt_blocks or list((resolved_profile or {}).get("prompt_blocks") or []))
    resolved_tool_profile = explicit_tool_profile or str((resolved_profile or {}).get("tool_profile") or "")
    resolved_tool_subset = list(explicit_tool_subset or list((resolved_profile or {}).get("tool_subset") or []))
    resolved_agent_type = normalized_agent_type or str((resolved_profile or {}).get("agent_type") or "")

    return {
        "role": normalized_role,
        "agent_type": resolved_agent_type,
        "prompt_blocks": resolved_prompt_blocks,
        "tool_profile": resolved_tool_profile,
        "tool_subset": resolved_tool_subset,
        "source": source,
        "profile": deepcopy(resolved_profile) if isinstance(resolved_profile, dict) else None,
        "registry_path": str(registry.get("registry_path") or ""),
    }


def build_prompt_block_previews(prompt_blocks: List[str], *, prompts_root: Optional[str] = None) -> List[Dict[str, Any]]:
    root = Path(prompts_root or _default_prompts_root()).resolve()
    previews: List[Dict[str, Any]] = []
    for rel_path in _normalize_string_list(prompt_blocks):
        candidate = (root / rel_path).resolve()
        within_root = str(candidate).startswith(str(root))
        exists = within_root and candidate.exists() and candidate.is_file()
        content_preview = ""
        size_bytes = 0
        updated_at = ""
        if exists:
            content = candidate.read_text(encoding="utf-8")
            content_preview = content[:4000]
            size_bytes = int(candidate.stat().st_size)
            updated_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).isoformat()
        previews.append(
            {
                "relative_path": rel_path,
                "exists": exists,
                "size_bytes": size_bytes,
                "updated_at": updated_at,
                "content_preview": content_preview,
            }
        )
    return previews


__all__ = [
    "build_prompt_block_previews",
    "delete_agent_profile",
    "get_agent_profile",
    "list_agent_profiles",
    "load_agent_profile_registry",
    "resolve_agent_profile_defaults",
    "save_agent_profile_registry",
    "upsert_agent_profile",
]
