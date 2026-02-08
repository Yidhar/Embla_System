"""MCP相关稳定功能模块

包含MCP服务注册、manifest解析等核心功能
"""

from .mcp_manager import (
    load_manifest_file,
    create_agent_instance,
    scan_and_register_mcp_agents,
    get_service_info,
    get_registered_services,
    get_service_instance,
    clear_registry,
    get_registry_status,
    MCP_REGISTRY,
    MANIFEST_CACHE
)

__all__ = [
    "load_manifest_file",
    "create_agent_instance", 
    "scan_and_register_mcp_agents",
    "get_service_info",
    "get_registered_services",
    "get_service_instance",
    "clear_registry",
    "get_registry_status",
    "MCP_REGISTRY",
    "MANIFEST_CACHE"
]
