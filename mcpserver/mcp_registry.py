"""MCP注册表 - manifest加载、agent实例创建、服务发现与查询"""

import json
import importlib
from pathlib import Path
import sys
from typing import Dict, Any, Optional, List

from system.config import logger

# 全局注册表
MCP_REGISTRY: Dict[str, Any] = {}  # MCP服务池 {name: agent_instance}
MANIFEST_CACHE: Dict[str, Any] = {}  # manifest信息缓存 {name: manifest_dict}
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


def scan_and_register_mcp_agents(mcp_dir: str = "mcpserver") -> List[str]:
    """扫描目录中的agent-manifest.json，注册MCP类型的agent"""
    d = Path(mcp_dir)
    registered_agents = []

    for manifest_file in d.glob("**/agent-manifest.json"):
        try:
            manifest = load_manifest_file(manifest_file)
            if not manifest:
                continue

            agent_type = manifest.get("agentType")
            service_name = manifest.get("displayName")

            if not service_name:
                sys.stderr.write(f"manifest缺少displayName字段: {manifest_file}\n")
                continue

            if agent_type == "mcp":
                # 优先使用 name 字段（英文标识）做注册 key，fallback 到 displayName
                registry_key = manifest.get("name") or service_name
                MANIFEST_CACHE[registry_key] = manifest
                agent_instance = create_agent_instance(manifest)
                if agent_instance:
                    MCP_REGISTRY[registry_key] = agent_instance
                    registered_agents.append(registry_key)
                    sys.stderr.write(f"✅ 注册MCP服务: {registry_key} ({service_name}) (来自 {manifest_file})\n")

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
        "total_tools": total_tools,
        "service_names": list(MCP_REGISTRY.keys()),
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
    MCP_REGISTRY.clear()
    MANIFEST_CACHE.clear()


def get_registry_status() -> Dict[str, Any]:
    return {
        "registered_services": len(MCP_REGISTRY),
        "cached_manifests": len(MANIFEST_CACHE),
        "service_names": list(MCP_REGISTRY.keys()),
    }
