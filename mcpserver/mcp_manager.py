"""MCP管理器 - 管理MCP服务连接和工具调用"""

from typing import Dict, Any, Optional, List
from system.config import logger
from mcpserver.mcp_registry import MCP_REGISTRY, MANIFEST_CACHE


class MCPManager:
    """MCP服务管理器 - 管理工具调用路由"""

    def __init__(self):
        self._initialized = False

    async def unified_call(self, service_name: str, tool_call: Dict[str, Any]) -> str:
        """统一调用接口 - 路由到注册的agent的handle_handoff方法"""
        agent = MCP_REGISTRY.get(service_name)
        if not agent:
            return f'{{"status": "error", "message": "未找到服务: {service_name}"}}'

        try:
            result = await agent.handle_handoff(tool_call)
            return result
        except Exception as e:
            logger.error(f"[MCPManager] 调用服务 {service_name} 失败: {e}")
            return f'{{"status": "error", "message": "调用失败: {e}"}}'

    def get_available_services(self) -> List[str]:
        """获取可用服务列表"""
        return list(MCP_REGISTRY.keys())

    def get_available_services_filtered(self) -> Dict[str, Any]:
        """获取服务详情"""
        result = {}
        for name, instance in MCP_REGISTRY.items():
            manifest = MANIFEST_CACHE.get(name, {})
            result[name] = {
                "displayName": manifest.get("displayName", name),
                "description": manifest.get("description", ""),
                "tools": manifest.get("capabilities", {}).get("invocationCommands", []),
            }
        return result

    def format_available_services(self) -> str:
        """格式化服务列表为字符串，供提示词注入"""
        lines = []
        for name, manifest in MANIFEST_CACHE.items():
            display_name = manifest.get("displayName", name)
            desc = manifest.get("description", "")
            tools = manifest.get("capabilities", {}).get("invocationCommands", [])
            lines.append(f"- 服务名(service_name): {name}")
            lines.append(f"  显示名: {display_name}")
            lines.append(f"  描述: {desc}")
            for tool in tools:
                cmd = tool.get("command", "")
                tool_desc = tool.get("description", "").split("\n")[0]
                example = tool.get("example", "")
                lines.append(f"  工具: {cmd} - {tool_desc}")
                if example:
                    lines.append(f"  示例: {example}")
            lines.append("")
        return "\n".join(lines)

    async def cleanup(self):
        """清理资源"""
        pass


# 全局单例
_MCP_MANAGER: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
