"""MCP管理器

提供稳定的MCP服务管理功能，包括manifest加载、agent实例创建和服务注册
"""

import json
import importlib
from pathlib import Path
import sys
from typing import Dict, Any, Optional, List

# 全局注册表
MCP_REGISTRY = {}  # MCP服务池
MANIFEST_CACHE = {}  # manifest信息缓存


def load_manifest_file(manifest_path: Path) -> Optional[Dict[str, Any]]:
    """加载manifest文件
    
    Args:
        manifest_path: manifest文件路径
        
    Returns:
        解析后的manifest字典，失败时返回None
    """
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"加载manifest文件失败 {manifest_path}: {e}\n")
        return None


def create_agent_instance(manifest: Dict[str, Any]) -> Optional[Any]:
    """根据manifest创建agent实例
    
    Args:
        manifest: manifest配置字典
        
    Returns:
        创建的agent实例，失败时返回None
    """
    try:
        entry_point = manifest.get('entryPoint', {})
        module_name = entry_point.get('module')
        class_name = entry_point.get('class')
        
        if not module_name or not class_name:
            sys.stderr.write(f"manifest缺少entryPoint信息: {manifest.get('displayName', 'unknown')}\n")
            return None
            
        # 动态导入模块
        module = importlib.import_module(module_name)
        agent_class = getattr(module, class_name)
        
        # 创建实例
        instance = agent_class()
        return instance
        
    except Exception as e:
        sys.stderr.write(f"创建agent实例失败 {manifest.get('displayName', 'unknown')}: {e}\n")
        return None


def scan_and_register_mcp_agents(mcp_dir: str = 'mcpserver') -> List[str]:
    """扫描目录中的JSON元数据文件，注册MCP类型的agent
    
    Args:
        mcp_dir: MCP服务目录路径
        
    Returns:
        注册成功的服务名称列表
    """
    d = Path(mcp_dir)
    registered_agents = []
    
    # 扫描所有agent-manifest.json文件
    for manifest_file in d.glob('**/agent-manifest.json'):
        try:
            # 加载manifest
            manifest = load_manifest_file(manifest_file)
            if not manifest:
                continue
                
            agent_type = manifest.get('agentType')
            # 只使用displayName作为注册名称
            service_name = manifest.get('displayName')
            
            if not service_name:
                sys.stderr.write(f"manifest缺少displayName字段: {manifest_file}\n")
                continue
            
            # 根据agentType进行分类处理
            if agent_type == 'mcp':
                # MCP类型：注册到MCP_REGISTRY，使用displayName作为键
                MANIFEST_CACHE[service_name] = manifest
                agent_instance = create_agent_instance(manifest)
                if agent_instance:
                    MCP_REGISTRY[service_name] = agent_instance
                    registered_agents.append(service_name)
                    sys.stderr.write(f"✅ 注册MCP服务: {service_name} (来自 {manifest_file})\n")
                    
        except Exception as e:
            sys.stderr.write(f"处理manifest文件失败 {manifest_file}: {e}\n")
            continue
    
    return registered_agents


def get_service_info(service_name: str) -> Optional[Dict[str, Any]]:
    """获取指定服务的详细信息
    
    Args:
        service_name: 服务名称
        
    Returns:
        服务信息字典，不存在时返回None
    """
    return MANIFEST_CACHE.get(service_name)


def get_registered_services() -> List[str]:
    """获取所有已注册的服务名称
    
    Returns:
        已注册服务名称列表
    """
    return list(MCP_REGISTRY.keys())


def get_service_instance(service_name: str) -> Optional[Any]:
    """获取指定服务的实例
    
    Args:
        service_name: 服务名称
        
    Returns:
        服务实例，不存在时返回None
    """
    return MCP_REGISTRY.get(service_name)


def clear_registry():
    """清空注册表（用于测试或重置）"""
    global MCP_REGISTRY, MANIFEST_CACHE
    MCP_REGISTRY.clear()
    MANIFEST_CACHE.clear()


def get_registry_status() -> Dict[str, Any]:
    """获取注册表状态信息
    
    Returns:
        注册表状态字典
    """
    return {
        "registered_services": len(MCP_REGISTRY),
        "cached_manifests": len(MANIFEST_CACHE),
        "service_names": list(MCP_REGISTRY.keys())
    }
