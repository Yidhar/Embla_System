"""MCP注册表 - manifest加载、agent实例创建、服务发现与查询"""

import json
import importlib
import os
from pathlib import Path
import sys
from typing import Dict, Any, Optional, List

from mcpserver.plugin_manifest_policy import validate_plugin_manifest
from mcpserver.plugin_worker import PluginWorkerProxy, PluginWorkerSpec
from system.config import logger

# 全局注册表
MCP_REGISTRY: Dict[str, Any] = {}  # MCP服务池 {name: agent_instance}
MANIFEST_CACHE: Dict[str, Any] = {}  # manifest信息缓存 {name: manifest_dict}
ISOLATED_WORKER_REGISTRY: Dict[str, Any] = {}  # 隔离插件服务池 {name: worker_proxy}
REJECTED_PLUGIN_MANIFESTS: Dict[str, Dict[str, Any]] = {}  # 插件拒绝记录 {name_or_path: reason/meta}
_REGISTERED = False  # 是否已完成注册


def load_manifest_file(manifest_path: Path) -> Optional[Dict[str, Any]]:
    """加载manifest文件"""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"加载manifest文件失败 {manifest_path}: {e}\n")
        return None


def create_agent_instance(manifest: Dict[str, Any]) -> Optional[Any]:
    """根据manifest创建agent实例"""
    try:
        entry_point = manifest.get("entryPoint", {})
        module_name = entry_point.get("module")
        class_name = entry_point.get("class")

        if not module_name or not class_name:
            sys.stderr.write(f"manifest缺少entryPoint信息: {manifest.get('displayName', 'unknown')}\n")
            return None

        module = importlib.import_module(module_name)
        agent_class = getattr(module, class_name)
        instance = agent_class()
        return instance

    except Exception as e:
        sys.stderr.write(f"创建agent实例失败 {manifest.get('displayName', 'unknown')}: {e}\n")
        return None


def _resolve_plugin_manifest_dirs() -> List[Path]:
    raw = str(os.getenv("NAGA_PLUGIN_MANIFEST_DIRS", "")).strip()
    if not raw:
        raw = "workspace/tools/plugins"
    dirs: List[Path] = []
    for item in raw.split(os.pathsep):
        normalized = str(item or "").strip()
        if not normalized:
            continue
        path = Path(normalized).resolve()
        if path.exists():
            dirs.append(path)
    return dirs


def _manifest_isolated_mode(manifest: Dict[str, Any]) -> str:
    isolation = manifest.get("isolation")
    if isinstance(isolation, dict):
        mode = str(isolation.get("mode") or "").strip().lower()
        if mode in {"worker", "process", "isolated_worker"}:
            return "isolated_worker"
    if str(manifest.get("agentType") or "").strip().lower() in {"mcp_plugin", "plugin"}:
        return "isolated_worker"
    return "inprocess"


def _create_isolated_worker_proxy(manifest: Dict[str, Any], manifest_path: Path) -> Optional[Any]:
    try:
        entry_point = manifest.get("entryPoint", {})
        module_name = str(entry_point.get("module") or "").strip()
        class_name = str(entry_point.get("class") or "").strip()
        if not module_name or not class_name:
            sys.stderr.write(f"manifest缺少entryPoint信息: {manifest.get('displayName', 'unknown')}\n")
            return None

        isolation_limits = manifest.get("_worker_limits")
        if not isinstance(isolation_limits, dict):
            isolation_limits = {}

        timeout_seconds = max(1.0, float(isolation_limits.get("timeout_seconds", 30.0)))
        max_payload_bytes = int(isolation_limits.get("max_payload_bytes", 131_072))
        max_output_bytes = int(isolation_limits.get("max_output_bytes", 262_144))
        max_memory_mb = int(isolation_limits.get("max_memory_mb", 256))
        cpu_time_seconds = int(isolation_limits.get("cpu_time_seconds", 20))
        max_failure_streak = int(isolation_limits.get("max_failure_streak", 3))
        cooldown_seconds = float(isolation_limits.get("cooldown_seconds", 30.0))
        stale_reap_grace_seconds = float(isolation_limits.get("stale_reap_grace_seconds", 90.0))

        spec = PluginWorkerSpec(
            service_name=str(manifest.get("name") or manifest.get("displayName") or "unknown").strip() or "unknown",
            module_name=module_name,
            class_name=class_name,
            timeout_seconds=timeout_seconds,
            max_payload_bytes=max_payload_bytes,
            max_output_bytes=max_output_bytes,
            max_memory_mb=max_memory_mb,
            cpu_time_seconds=cpu_time_seconds,
            max_failure_streak=max_failure_streak,
            cooldown_seconds=cooldown_seconds,
            stale_reap_grace_seconds=stale_reap_grace_seconds,
            python_executable=sys.executable,
            pythonpath_entries=[str(manifest_path.parent.resolve())],
        )
        return PluginWorkerProxy(spec)
    except Exception as e:
        sys.stderr.write(f"创建隔离worker代理失败 {manifest.get('displayName', 'unknown')}: {e}\n")
        return None


def scan_and_register_mcp_agents(mcp_dir: str = "mcpserver") -> List[str]:
    """扫描目录中的agent-manifest.json，注册MCP类型的agent"""
    d = Path(mcp_dir).resolve()
    plugin_dirs = _resolve_plugin_manifest_dirs()
    registered_agents = []
    seen_manifest_files = set()
    roots = [d, *plugin_dirs]

    for root in roots:
        if not root.exists():
            continue
        for manifest_file in root.glob("**/agent-manifest.json"):
            normalized_path = str(manifest_file.resolve()).replace("\\", "/")
            if normalized_path in seen_manifest_files:
                continue
            seen_manifest_files.add(normalized_path)
            try:
                manifest = load_manifest_file(manifest_file)
                if not manifest:
                    continue

                agent_type = str(manifest.get("agentType") or "").strip().lower()
                service_name = manifest.get("displayName")

                if not service_name:
                    sys.stderr.write(f"manifest缺少displayName字段: {manifest_file}\n")
                    continue

                if agent_type not in {"mcp", "mcp_plugin", "plugin"}:
                    continue

                # 优先使用 name 字段（英文标识）做注册 key，fallback 到 displayName
                registry_key = manifest.get("name") or service_name
                runtime_mode = _manifest_isolated_mode(manifest)
                if runtime_mode != "isolated_worker":
                    root_path = root.resolve()
                    try:
                        manifest_file.resolve().relative_to(root_path)
                        if root_path in plugin_dirs:
                            runtime_mode = "isolated_worker"
                    except Exception:
                        pass

                if runtime_mode == "isolated_worker":
                    validation = validate_plugin_manifest(manifest, manifest_path=manifest_file)
                    if not validation.accepted:
                        reject_key = (
                            str(manifest.get("name") or "").strip()
                            or str(manifest.get("displayName") or "").strip()
                            or normalized_path
                        )
                        REJECTED_PLUGIN_MANIFESTS[reject_key] = {
                            "reason": validation.reason,
                            "manifest_path": normalized_path,
                        }
                        sys.stderr.write(
                            f"❌ 拒绝隔离插件注册: {reject_key} reason={validation.reason} (来自 {manifest_file})\n"
                        )
                        continue
                    manifest = validation.normalized_manifest

                manifest_record = dict(manifest)
                manifest_record["_runtime_mode"] = runtime_mode
                manifest_record["_manifest_path"] = str(manifest_file).replace("\\", "/")
                MANIFEST_CACHE[registry_key] = manifest_record

                if runtime_mode == "isolated_worker":
                    agent_instance = _create_isolated_worker_proxy(manifest, manifest_file)
                else:
                    agent_instance = create_agent_instance(manifest)

                if agent_instance:
                    MCP_REGISTRY[registry_key] = agent_instance
                    if runtime_mode == "isolated_worker":
                        ISOLATED_WORKER_REGISTRY[registry_key] = agent_instance
                    registered_agents.append(registry_key)
                    sys.stderr.write(
                        f"✅ 注册MCP服务: {registry_key} ({service_name}) mode={runtime_mode} (来自 {manifest_file})\n"
                    )

            except Exception as e:
                sys.stderr.write(f"处理manifest文件失败 {manifest_file}: {e}\n")
                continue

    return registered_agents


def get_service_info(service_name: str):
    """获取服务详细信息"""
    manifest = MANIFEST_CACHE.get(service_name)
    instance = MCP_REGISTRY.get(service_name)
    if not manifest:
        return None
    return {
        "name": service_name,
        "manifest": manifest,
        "instance": instance,
        "tools": get_available_tools(service_name),
    }


def get_available_tools(service_name: str):
    """获取服务的可用工具列表"""
    manifest = MANIFEST_CACHE.get(service_name)
    if not manifest:
        return []
    capabilities = manifest.get("capabilities", {})
    return capabilities.get("invocationCommands", [])


def get_all_services_info():
    """获取所有服务信息"""
    result = {}
    for name in MANIFEST_CACHE:
        result[name] = get_service_info(name)
    return result


def query_services_by_capability(keyword: str):
    """按关键词搜索服务"""
    matched = []
    keyword_lower = keyword.lower()
    for name, manifest in MANIFEST_CACHE.items():
        desc = manifest.get("description", "").lower()
        display = manifest.get("displayName", "").lower()
        if keyword_lower in desc or keyword_lower in display:
            matched.append(name)
    return matched


def get_service_statistics():
    """获取服务统计信息"""
    total_tools = 0
    for manifest in MANIFEST_CACHE.values():
        caps = manifest.get("capabilities", {})
        total_tools += len(caps.get("invocationCommands", []))
    return {
        "total_services": len(MCP_REGISTRY),
        "isolated_worker_services": len(ISOLATED_WORKER_REGISTRY),
        "rejected_plugin_manifests": len(REJECTED_PLUGIN_MANIFESTS),
        "total_tools": total_tools,
        "service_names": list(MCP_REGISTRY.keys()),
        "isolated_worker_names": list(ISOLATED_WORKER_REGISTRY.keys()),
        "rejected_plugin_names": list(REJECTED_PLUGIN_MANIFESTS.keys()),
    }


def auto_register_mcp():
    """自动扫描并注册MCP服务（幂等，重复调用不会重新注册）"""
    global _REGISTERED
    if _REGISTERED:
        return list(MCP_REGISTRY.keys())
    registered = scan_and_register_mcp_agents("mcpserver")
    _REGISTERED = True
    logger.info(f"[MCP Registry] 自动注册完成，已注册 {len(registered)} 个服务: {registered}")
    return registered


def get_registered_services() -> List[str]:
    return list(MCP_REGISTRY.keys())


def get_service_instance(service_name: str) -> Optional[Any]:
    return MCP_REGISTRY.get(service_name)


def clear_registry():
    global _REGISTERED
    MCP_REGISTRY.clear()
    MANIFEST_CACHE.clear()
    ISOLATED_WORKER_REGISTRY.clear()
    REJECTED_PLUGIN_MANIFESTS.clear()
    _REGISTERED = False


def get_registry_status() -> Dict[str, Any]:
    return {
        "registered_services": len(MCP_REGISTRY),
        "isolated_worker_services": len(ISOLATED_WORKER_REGISTRY),
        "rejected_plugin_manifests": len(REJECTED_PLUGIN_MANIFESTS),
        "cached_manifests": len(MANIFEST_CACHE),
        "service_names": list(MCP_REGISTRY.keys()),
        "isolated_worker_names": list(ISOLATED_WORKER_REGISTRY.keys()),
        "rejected_plugin_names": list(REJECTED_PLUGIN_MANIFESTS.keys()),
    }
