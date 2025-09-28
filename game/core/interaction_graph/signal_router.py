"""
信号路由器 - 构建智能体之间的信息传输路径和规则
"""

import logging
from typing import List, Dict, Any, Tuple, Set, Optional
from ..models.data_models import Agent, InteractionGraph, Task
from ..models.config import GameConfig

logger = logging.getLogger(__name__)


class SignalRouter:
    """信号路由器 - 负责构建和管理智能体间的信息传输规则"""
    
    def __init__(self, config: GameConfig):
        self.config = config
        self.collaboration_rules = {}
    
    def _load_collaboration_rules(self) -> Dict[str, Dict[str, Any]]:
        """兼容接口: 返回空,避免任何领域模板与硬编码规则"""
        return {}
    
    async def build_interaction_graph(self, agents: List[Agent], task: Task) -> InteractionGraph:
        """
        构建交互图,定义智能体间的通信路径
        
        Args:
            agents: 智能体列表
            task: 任务描述
            
        Returns:
            构建的交互图
        """
        try:
            logger.info(f"开始为{len(agents)}个智能体构建交互图")
            
            # 分析领域类型
            domain = self._determine_domain(task, agents)
            logger.info(f"识别协作领域:{domain}")
            
            # 构建允许的通信路径
            allowed_paths = self._build_allowed_paths(agents, domain)
            
            # 识别禁止的直接连接
            forbidden_paths = self._build_forbidden_paths(agents, domain)
            
            # 验证路径有效性
            self._validate_paths(agents, allowed_paths, forbidden_paths)
            
            # 创建交互图
            # 允许执行者自指路由（自环），便于长输出无截断
            self_loops = [(a.agent_id, a.agent_id) for a in agents if not a.is_requester]
            allowed_paths_extended = list(set(allowed_paths + self_loops))

            # 构造最小协作矩阵（全部标记为none，交由上层动态更新）
            collaboration_matrix = {a.agent_id: {} for a in agents}

            interaction_graph = InteractionGraph(
                agents=agents,
                allowed_paths=allowed_paths_extended,
                forbidden_paths=forbidden_paths,
                collaboration_matrix=collaboration_matrix,
                domain=domain,
                task_description=task.description
            )
            
            logger.info(f"成功构建交互图,包含{len(allowed_paths)}条允许路径,{len(forbidden_paths)}条禁止路径")
            return interaction_graph
            
        except Exception as e:
            logger.error(f"构建交互图失败:{e}")
            raise
    
    def _determine_domain(self, task: Task, agents: List[Agent]) -> str:
        """确定协作领域(不使用任何模板): 优先task.domain,否则返回"通用""" 
        return task.domain or "通用"
    
    def _build_allowed_paths(self, agents: List[Agent], domain: str) -> List[Tuple[str, str]]:
        """构建允许的通信路径(无模板): 基于每个Agent的connection_permissions与ID/名称映射"""
        allowed_paths: List[Tuple[str, str]] = []
        name_to_id = {a.name: a.agent_id for a in agents}
        id_set = {a.agent_id for a in agents}
        
        # 基于显式权限生成边
        for a in agents:
            perms = a.connection_permissions or []
            for p in perms:
                target_id = name_to_id.get(p) or (p if p in id_set else None)
                if target_id:
                    allowed_paths.append((a.agent_id, target_id))
        
        # 如果没有任何显式权限,最小可用回退: 请求方<->首个执行者 以及 全体执行者之间可互联
        if not allowed_paths:
            requester = next((x for x in agents if getattr(x, "is_requester", False)), None)
            executors = [x for x in agents if not getattr(x, "is_requester", False)]
            if requester and executors:
                first_exec = executors[0]
                allowed_paths.append((requester.agent_id, first_exec.agent_id))
                allowed_paths.append((first_exec.agent_id, requester.agent_id))
            # 执行者之间互联
            for i, u in enumerate(executors):
                for j, v in enumerate(executors):
                    if i != j:
                        allowed_paths.append((u.agent_id, v.agent_id))
        
        # 去重
        allowed_paths = list(set(allowed_paths))
        return allowed_paths
    
    def _get_intermediary_role(self, comm_type: str, rules: Dict[str, Any]) -> Optional[str]:
        """获取中介角色"""
        return None
    
    def _build_forbidden_paths(self, agents: List[Agent], domain: str) -> List[Tuple[str, str]]:
        """构建禁止的直接连接(无模板): 默认无禁止,由上层策略控制"""
        return []
    
    def _validate_paths(self, agents: List[Agent], allowed_paths: List[Tuple[str, str]], 
                       forbidden_paths: List[Tuple[str, str]]):
        """验证路径配置的有效性"""
        agent_ids = {agent.agent_id for agent in agents}
        
        # 检查所有路径中的智能体ID是否存在
        for from_id, to_id in allowed_paths + forbidden_paths:
            if from_id not in agent_ids or to_id not in agent_ids:
                raise ValueError(f"路径中包含不存在的智能体ID: {from_id} -> {to_id}")
        
        # 检查是否存在冲突的路径（同时在允许和禁止列表中）
        allowed_set = set(allowed_paths)
        forbidden_set = set(forbidden_paths)
        conflicts = allowed_set & forbidden_set
        
        if conflicts:
            raise ValueError(f"存在冲突的路径配置: {conflicts}")
        
        # 确保每个智能体都有至少一条可用路径
        for agent in agents:
            outgoing_paths = [path for path in allowed_paths if path[0] == agent.agent_id]
            if not outgoing_paths:
                logger.warning(f"智能体{agent.name}({agent.agent_id})没有出向路径")
        
        logger.info("路径配置验证通过")
    
    def get_communication_matrix(self, interaction_graph: InteractionGraph) -> Dict[str, Dict[str, str]]:
        """
        生成通信矩阵,显示智能体间的通信关系
        
        Returns:
            通信矩阵,格式为 {from_agent: {to_agent: communication_type}}
        """
        matrix = {}
        
        for agent in interaction_graph.agents:
            matrix[agent.agent_id] = {}
            
            for other_agent in interaction_graph.agents:
                if agent.agent_id == other_agent.agent_id:
                    continue
                
                # 检查是否有直接路径
                if (agent.agent_id, other_agent.agent_id) in interaction_graph.allowed_paths:
                    if (agent.agent_id, other_agent.agent_id) in interaction_graph.forbidden_paths:
                        matrix[agent.agent_id][other_agent.agent_id] = "forbidden"
                    else:
                        matrix[agent.agent_id][other_agent.agent_id] = "direct"
                else:
                    # 检查是否有间接路径
                    if self._has_indirect_path(agent.agent_id, other_agent.agent_id, interaction_graph):
                        matrix[agent.agent_id][other_agent.agent_id] = "indirect"
                    else:
                        matrix[agent.agent_id][other_agent.agent_id] = "none"
        
        return matrix
    
    def _has_indirect_path(self, from_id: str, to_id: str, interaction_graph: InteractionGraph) -> bool:
        """检查是否存在间接路径（通过中介）"""
        # 简单的两跳路径检查
        for intermediate_agent in interaction_graph.agents:
            intermediate_id = intermediate_agent.agent_id
            if intermediate_id == from_id or intermediate_id == to_id:
                continue
            
            # 检查 from -> intermediate -> to 路径
            if ((from_id, intermediate_id) in interaction_graph.allowed_paths and
                (intermediate_id, to_id) in interaction_graph.allowed_paths):
                return True
        
        return False
    
    def visualize_interaction_graph(self, interaction_graph: InteractionGraph) -> str:
        """
        可视化交互图
        
        Returns:
            交互图的文本表示
        """
        lines = []
        lines.append("=== 智能体交互图 ===")
        lines.append(f"领域: {interaction_graph.domain}")
        lines.append(f"任务: {interaction_graph.task_description}")
        lines.append("")
        
        # 智能体列表
        lines.append("智能体列表:")
        for agent in interaction_graph.agents:
            lines.append(f"  - {agent.name} ({agent.role})")
        lines.append("")
        
        # 允许的通信路径
        lines.append("允许的通信路径:")
        for from_id, to_id in interaction_graph.allowed_paths:
            from_agent = interaction_graph.get_agent_by_id(from_id)
            to_agent = interaction_graph.get_agent_by_id(to_id)
            if from_agent and to_agent:
                lines.append(f"  {from_agent.name} -> {to_agent.name}")
        lines.append("")
        
        # 禁止的直接连接
        if interaction_graph.forbidden_paths:
            lines.append("禁止的直接连接:")
            for from_id, to_id in interaction_graph.forbidden_paths:
                from_agent = interaction_graph.get_agent_by_id(from_id)
                to_agent = interaction_graph.get_agent_by_id(to_id)
                if from_agent and to_agent:
                    lines.append(f"  {from_agent.name} ❌ {to_agent.name}")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_agent_connections(self, agent_id: str, interaction_graph: InteractionGraph) -> Dict[str, List[str]]:
        """
        获取指定智能体的连接信息
        
        Returns:
            {"outgoing": [...], "incoming": [...]}
        """
        connections = {"outgoing": [], "incoming": []}
        
        for from_id, to_id in interaction_graph.allowed_paths:
            if from_id == agent_id:
                connections["outgoing"].append(to_id)
            elif to_id == agent_id:
                connections["incoming"].append(from_id)
        
        return connections 
 
 