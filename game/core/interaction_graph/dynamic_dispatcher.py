"""
动态分发器 - 智能体任务完成后的动态传输决策
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from ..models.data_models import Agent, InteractionGraph, Task, GameResult
from ..models.config import GameConfig

logger = logging.getLogger(__name__)


class DynamicDispatcher:
    """动态分发器 - 根据任务输出和下阶段需求自主选择传输目标"""
    
    def __init__(self, config: GameConfig):
        self.config = config
        self.dispatch_history: List[Dict[str, Any]] = []
        self.iteration_counts: Dict[str, int] = {}
    
    async def dispatch_message(self, 
                               source_agent_id: str,
                               task_output: Any,
                               interaction_graph: InteractionGraph,
                               task: Task,
                               game_result: Optional[GameResult] = None) -> List[Tuple[str, str, Any]]:
        """
        动态分发消息到合适的目标智能体
        
        Args:
            source_agent_id: 源智能体ID
            task_output: 任务输出结果
            interaction_graph: 交互图
            task: 当前任务
            game_result: 博弈结果（可选）
            
        Returns:
            分发决策列表,格式为 [(target_agent_id, message_content, dispatch_reason)]
        """
        try:
            logger.info(f"开始为智能体{source_agent_id}分发消息")
            
            # 获取源智能体
            source_agent = interaction_graph.get_agent_by_id(source_agent_id)
            if not source_agent:
                raise ValueError(f"未找到源智能体: {source_agent_id}")
            
            # 检查迭代次数限制
            self._check_iteration_limit(source_agent_id, source_agent)
            
            # 获取可达的智能体
            reachable_agents = self._get_reachable_agents(source_agent_id, interaction_graph)
            
            # 分析任务输出,确定下一阶段需求
            next_phase_requirements = self._analyze_next_phase_requirements(
                task_output, source_agent, task, game_result
            )
            
            # 选择最佳目标智能体
            target_selections = self._select_target_agents(
                reachable_agents, next_phase_requirements, interaction_graph, task
            )
            
            # 生成分发消息
            dispatch_decisions = []
            for target_id, dispatch_reason in target_selections:
                message_content = self._generate_dispatch_message(
                    source_agent, task_output, target_id, dispatch_reason, interaction_graph
                )
                dispatch_decisions.append((target_id, message_content, dispatch_reason))
            
            # 记录分发历史
            self._record_dispatch_history(source_agent_id, dispatch_decisions, task_output)
            
            # 更新迭代计数
            self._update_iteration_count(source_agent_id)
            
            logger.info(f"成功生成{len(dispatch_decisions)}个分发决策")
            return dispatch_decisions
            
        except Exception as e:
            logger.error(f"消息分发失败:{e}")
            raise
    
    def _check_iteration_limit(self, agent_id: str, agent: Agent):
        """检查迭代次数限制"""
        current_count = self.iteration_counts.get(agent_id, 0)
        
        if current_count >= agent.max_iterations:
            logger.warning(f"智能体{agent.name}达到最大迭代次数{agent.max_iterations},强制交接")
            # 触发强制交接机制
            raise IterationLimitExceededError(f"智能体{agent.name}超过最大迭代次数")
        
        if current_count >= self.config.self_game.max_iterations:
            logger.warning(f"智能体{agent.name}达到系统最大迭代次数,强制交接")
            raise IterationLimitExceededError(f"智能体{agent.name}超过系统最大迭代次数")
    
    def _get_reachable_agents(self, source_agent_id: str, interaction_graph: InteractionGraph) -> List[Agent]:
        """获取可达的智能体列表"""
        reachable_ids = interaction_graph.get_reachable_agents(source_agent_id)
        reachable_agents = []
        
        for agent_id in reachable_ids:
            agent = interaction_graph.get_agent_by_id(agent_id)
            if agent:
                reachable_agents.append(agent)
        
        return reachable_agents
    
    def _analyze_next_phase_requirements(self, 
                                         task_output: Any,
                                         source_agent: Agent,
                                         task: Task,
                                         game_result: Optional[GameResult] = None) -> Dict[str, Any]:
        """分析下一阶段的需求"""
        requirements = {
            "required_skills": [],
            "output_type": "analysis",
            "priority": "medium",
            "collaboration_type": "sequential"
        }
        
        # 基于源智能体角色分析需求
        if source_agent.role == "产品经理":
            requirements.update({
                "required_skills": ["技术实现", "设计创作"],
                "output_type": "implementation",
                "priority": "high",
                "collaboration_type": "parallel"
            })
        elif source_agent.role == "程序员":
            requirements.update({
                "required_skills": ["质量验证", "测试分析"],
                "output_type": "validation",
                "priority": "high",
                "collaboration_type": "sequential"
            })
        elif source_agent.role == "美工":
            requirements.update({
                "required_skills": ["产品评审", "技术集成"],
                "output_type": "integration",
                "priority": "medium",
                "collaboration_type": "feedback"
            })
        elif source_agent.role == "研究员":
            requirements.update({
                "required_skills": ["数据分析", "文献验证"],
                "output_type": "analysis",
                "priority": "high",
                "collaboration_type": "parallel"
            })
        
        # 基于任务输出内容调整需求
        output_str = str(task_output).lower()
        if "设计" in output_str or "方案" in output_str:
            requirements["required_skills"].extend(["实现能力", "技术评估"])
        elif "代码" in output_str or "实现" in output_str:
            requirements["required_skills"].extend(["测试验证", "质量保证"])
        elif "测试" in output_str or "验证" in output_str:
            requirements["required_skills"].extend(["问题修复", "优化改进"])
        
        # 基于博弈结果调整需求
        if game_result and game_result.novel_score:
            if game_result.novel_score.score < 0.5:
                requirements["required_skills"].append("创新改进")
                requirements["priority"] = "high"
        
        return requirements
    
    def _select_target_agents(self, 
                              reachable_agents: List[Agent],
                              requirements: Dict[str, Any],
                              interaction_graph: InteractionGraph,
                              task: Task) -> List[Tuple[str, str]]:
        """选择目标智能体"""
        selections = []
        required_skills = requirements.get("required_skills", [])
        collaboration_type = requirements.get("collaboration_type", "sequential")
        
        # 计算每个智能体的匹配分数
        agent_scores = []
        for agent in reachable_agents:
            score = self._calculate_agent_match_score(agent, requirements, interaction_graph)
            agent_scores.append((agent, score))
        
        # 按分数排序
        agent_scores.sort(key=lambda x: x[1], reverse=True)
        
        # 根据协作类型选择智能体
        if collaboration_type == "parallel":
            # 并行协作:选择多个智能体
            max_parallel = min(3, len(agent_scores))  # 最多3个并行
            for i in range(max_parallel):
                if agent_scores[i][1] > 0.3:  # 分数阈值
                    agent = agent_scores[i][0]
                    reason = f"并行协作_{i+1}:匹配分数{agent_scores[i][1]:.2f}"
                    selections.append((agent.agent_id, reason))
        
        elif collaboration_type == "sequential":
            # 顺序协作:选择最佳匹配的智能体
            if agent_scores and agent_scores[0][1] > 0.2:
                agent = agent_scores[0][0]
                reason = f"顺序协作:最佳匹配,分数{agent_scores[0][1]:.2f}"
                selections.append((agent.agent_id, reason))
        
        elif collaboration_type == "feedback":
            # 反馈协作:选择层级较高的智能体
            coordinator_agents = [a for a in reachable_agents if self._is_coordinator_role(a.role)]
            if coordinator_agents:
                agent = coordinator_agents[0]
                reason = "反馈协作:选择协调者角色"
                selections.append((agent.agent_id, reason))
            elif agent_scores:
                agent = agent_scores[0][0]
                reason = "反馈协作:选择最佳匹配"
                selections.append((agent.agent_id, reason))
        
        # 如果没有选择任何智能体,选择默认的下一个智能体
        if not selections:
            # 默认自指（若图允许或存在自环），否则回传需求方
            if interaction_graph.is_path_allowed(source_agent_id, source_agent_id):
                selections.append((source_agent_id, "默认自指"))
            else:
                requester = next((x for x in interaction_graph.agents if getattr(x, "is_requester", False)), None)
                if requester and interaction_graph.is_path_allowed(source_agent_id, requester.agent_id):
                    selections.append((requester.agent_id, "无候选:回传需求方"))
                elif reachable_agents:
                    agent = reachable_agents[0]
                    selections.append((agent.agent_id, "无候选:第一个可达"))
         
        return selections
    
    def _calculate_agent_match_score(self, 
                                     agent: Agent,
                                     requirements: Dict[str, Any],
                                     interaction_graph: InteractionGraph) -> float:
        """计算智能体匹配分数"""
        score = 0.0
        required_skills = requirements.get("required_skills", [])
        
        # 基于技能匹配计算分数
        for required_skill in required_skills:
            for agent_skill in agent.skills:
                if self._skills_match(required_skill, agent_skill):
                    score += 0.3
        
        # 基于角色适配性计算分数
        role_score = self._calculate_role_compatibility(agent.role, requirements)
        score += role_score
        
        # 基于历史协作效果调整分数
        history_score = self._calculate_collaboration_history_score(agent.agent_id)
        score += history_score
        
        # 基于当前工作负载调整分数
        workload_score = self._calculate_workload_score(agent.agent_id)
        score *= workload_score
        
        return min(score, 1.0)  # 限制最大分数为1.0
    
    def _skills_match(self, required_skill: str, agent_skill: str) -> bool:
        """检查技能是否匹配"""
        # 简单的关键词匹配,实际可以使用更复杂的语义匹配
        skill_mappings = {
            "技术实现": ["编程", "开发", "实现", "coding"],
            "设计创作": ["设计", "美工", "创作", "UI", "UX"],
            "质量验证": ["测试", "验证", "质量", "QA"],
            "数据分析": ["分析", "统计", "数据", "analytics"],
            "产品评审": ["产品", "评审", "管理", "策划"],
            "创新改进": ["创新", "改进", "优化", "创意"]
        }
        
        required_keywords = skill_mappings.get(required_skill, [required_skill.lower()])
        agent_skill_lower = agent_skill.lower()
        
        return any(keyword in agent_skill_lower for keyword in required_keywords)
    
    def _calculate_role_compatibility(self, role: str, requirements: Dict[str, Any]) -> float:
        """计算角色兼容性分数"""
        role_compatibility = {
            "产品经理": {"analysis": 0.8, "implementation": 0.6, "validation": 0.7, "integration": 0.9},
            "程序员": {"analysis": 0.6, "implementation": 0.9, "validation": 0.7, "integration": 0.8},
            "美工": {"analysis": 0.5, "implementation": 0.7, "validation": 0.4, "integration": 0.6},
            "测试人员": {"analysis": 0.7, "implementation": 0.3, "validation": 0.9, "integration": 0.5},
            "研究员": {"analysis": 0.9, "implementation": 0.5, "validation": 0.6, "integration": 0.7},
            "数据分析师": {"analysis": 0.9, "implementation": 0.6, "validation": 0.8, "integration": 0.5}
        }
        
        output_type = requirements.get("output_type", "analysis")
        return role_compatibility.get(role, {}).get(output_type, 0.5)
    
    def _calculate_collaboration_history_score(self, agent_id: str) -> float:
        """计算协作历史分数"""
        # 简单实现:基于历史分发成功率
        successful_dispatches = 0
        total_dispatches = 0
        
        for record in self.dispatch_history:
            if agent_id in [decision[0] for decision in record.get("decisions", [])]:
                total_dispatches += 1
                # 假设有成功标记
                if record.get("success", True):
                    successful_dispatches += 1
        
        if total_dispatches == 0:
            return 0.0  # 新智能体,无历史记录
        
        success_rate = successful_dispatches / total_dispatches
        return (success_rate - 0.5) * 0.2  # 转换为-0.1到0.1的分数调整
    
    def _calculate_workload_score(self, agent_id: str) -> float:
        """计算工作负载分数"""
        current_iterations = self.iteration_counts.get(agent_id, 0)
        max_iterations = self.config.self_game.max_iterations
        
        # 工作负载越高,分数越低
        workload_ratio = current_iterations / max_iterations if max_iterations > 0 else 0
        return 1.0 - (workload_ratio * 0.3)  # 最多降低30%的分数
    
    def _is_coordinator_role(self, role: str) -> bool:
        """判断是否为协调者角色"""
        coordinator_roles = ["产品经理", "项目经理", "研究员", "主管", "负责人"]
        return role in coordinator_roles
    
    def _generate_dispatch_message(self, 
                                   source_agent: Agent,
                                   task_output: Any,
                                   target_agent_id: str,
                                   dispatch_reason: str,
                                   interaction_graph: InteractionGraph) -> Dict[str, Any]:
        """生成分发消息"""
        target_agent = interaction_graph.get_agent_by_id(target_agent_id)
        if not target_agent:
            raise ValueError(f"未找到目标智能体: {target_agent_id}")
        
        message = {
            "from_agent": {
                "id": source_agent.agent_id,
                "name": source_agent.name,
                "role": source_agent.role
            },
            "to_agent": {
                "id": target_agent.agent_id,
                "name": target_agent.name,
                "role": target_agent.role
            },
            "content": {
                "task_output": task_output,
                "thinking_vector": source_agent.thinking_vector,
                "dispatch_reason": dispatch_reason,
                "next_action_suggestion": self._generate_next_action_suggestion(
                    source_agent, target_agent, task_output
                )
            },
            "metadata": {
                "timestamp": asyncio.get_event_loop().time(),
                "iteration_count": self.iteration_counts.get(source_agent.agent_id, 0),
                "priority": "normal"
            }
        }
        
        return message
    
    def _generate_next_action_suggestion(self, 
                                         source_agent: Agent,
                                         target_agent: Agent,
                                         task_output: Any) -> str:
        """生成下一步行动建议(去模板): 给出简短动态建议"""
        return f"基于当前输出,由{target_agent.role}继续推进其核心职责,补齐缺口或验证成果"
    
    def _record_dispatch_history(self, 
                                 source_agent_id: str,
                                 dispatch_decisions: List[Tuple[str, str, Any]],
                                 task_output: Any):
        """记录分发历史"""
        record = {
            "source_agent_id": source_agent_id,
            "decisions": dispatch_decisions,
            "task_output_summary": str(task_output)[:200],  # 限制长度
            "timestamp": asyncio.get_event_loop().time(),
            "success": True  # 初始标记为成功,后续可以根据实际结果更新
        }
        
        self.dispatch_history.append(record)
        
        # 限制历史记录数量
        if len(self.dispatch_history) > 1000:
            self.dispatch_history = self.dispatch_history[-800:]  # 保留最近800条
    
    def _update_iteration_count(self, agent_id: str):
        """更新迭代计数"""
        self.iteration_counts[agent_id] = self.iteration_counts.get(agent_id, 0) + 1
    
    def get_agent_iteration_count(self, agent_id: str) -> int:
        """获取智能体的迭代次数"""
        return self.iteration_counts.get(agent_id, 0)
    
    def reset_agent_iteration_count(self, agent_id: str):
        """重置智能体的迭代次数"""
        self.iteration_counts[agent_id] = 0
    
    def get_dispatch_statistics(self) -> Dict[str, Any]:
        """获取分发统计信息"""
        total_dispatches = len(self.dispatch_history)
        successful_dispatches = sum(1 for record in self.dispatch_history if record.get("success", True))
        
        agent_dispatch_counts = {}
        for record in self.dispatch_history:
            agent_id = record["source_agent_id"]
            agent_dispatch_counts[agent_id] = agent_dispatch_counts.get(agent_id, 0) + 1
        
        return {
            "total_dispatches": total_dispatches,
            "successful_dispatches": successful_dispatches,
            "success_rate": successful_dispatches / total_dispatches if total_dispatches > 0 else 0,
            "agent_dispatch_counts": agent_dispatch_counts,
            "current_iteration_counts": self.iteration_counts.copy()
        }


class IterationLimitExceededError(Exception):
    """迭代次数超限异常"""
    pass 
 
 
 
 