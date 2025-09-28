"""
角色生成器 - 整合Distributor和PromptGenerator的完整角色生成流程
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from ..models.data_models import Agent, Task, ThinkingVector, GeneratedRole
from ..models.config import GameConfig
from .distributor import Distributor
from .prompt_generator import PromptGenerator

logger = logging.getLogger(__name__)


class RoleGenerator:
    """角色生成器 - 提供完整的角色生成服务,整合Distributor和PromptGenerator"""
    
    def __init__(self, config: GameConfig, naga_conversation=None):
        """
        初始化RoleGenerator
        
        Args:
            config: 游戏配置
            naga_conversation: NagaAgent的会话实例,用于API调用
        """
        self.config = config
        self.distributor = Distributor(config, naga_conversation)
        self.prompt_generator = PromptGenerator(config, naga_conversation)
    
    async def generate_agents(self, task: Task, expected_count_range: Optional[Tuple[int, int]] = None) -> List[Agent]:
        """
        完整的智能体生成流程
        
        Args:
            task: 任务描述
            expected_count_range: 期望角色数量范围,如果不指定则使用配置默认值
            
        Returns:
            生成的智能体列表（包含system_prompt和connection_permissions,以及需求方节点）
        """
        try:
            logger.info(f"开始完整的智能体生成流程:{task.description}")
            
            # 确定角色数量范围
            if expected_count_range is None:
                count_range = (
                    self.config.interaction_graph.min_agents,
                    self.config.interaction_graph.max_agents
                )
            else:
                count_range = expected_count_range
            
            # 步骤1:使用Distributor生成角色
            logger.info("步骤1:生成角色信息")
            generated_roles = await self.distributor.generate_roles(task, count_range)
            
            # 步骤2:分配协作权限
            logger.info("步骤2:分配协作权限")
            collaboration_permissions = await self.distributor.assign_collaboration_permissions(generated_roles)
            
            # 步骤3:为每个角色生成专用prompt
            logger.info("步骤3:生成角色专用prompts")
            role_prompts = await self._generate_all_role_prompts(
                generated_roles, task, collaboration_permissions
            )
            
            # 步骤4:创建完整的Agent对象
            logger.info("步骤4:创建Agent对象")
            agents = await self._create_agents_from_roles(
                generated_roles, task, collaboration_permissions, role_prompts
            )
            
            # 步骤5:创建需求方节点并集成到交互图中
            logger.info("步骤5:创建需求方节点")
            requester_agent = self._create_requester_agent(task, agents)
            agents.insert(0, requester_agent)  # 需求方作为第一个节点
            
            # 步骤6:更新协作权限,连接需求方
            self._update_permissions_with_requester(agents, collaboration_permissions)
            
            # 验证智能体配置
            self._validate_agents(agents)
            
            logger.info(f"成功完成智能体生成流程,共生成{len(agents)}个智能体（含需求方）")
            return agents
            
        except Exception as e:
            logger.error(f"智能体生成流程失败:{e}")
            raise
    
    async def _generate_all_role_prompts(self, 
                                         roles: List[GeneratedRole],
                                         task: Task,
                                         collaboration_permissions: Dict[str, List[str]]) -> Dict[str, str]:
        """为所有角色生成专用的system prompt"""
        role_prompts = {}
        
        # 并发生成所有角色的prompts
        async def generate_single_prompt(role: GeneratedRole) -> Tuple[str, str]:
            try:
                prompt = await self.prompt_generator.generate_role_prompt(
                    role, task, collaboration_permissions, roles
                )
                return role.name, prompt
            except Exception as e:
                logger.error(f"为角色'{role.name}'生成prompt失败:{e}")
                fallback_prompt = self.prompt_generator._get_fallback_prompt(role, task)
                return role.name, fallback_prompt
        
        # 并发执行所有prompt生成任务
        tasks = [generate_single_prompt(role) for role in roles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集结果
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"生成prompt时发生异常:{result}")
                continue
            
            role_name, prompt = result
            role_prompts[role_name] = prompt
        
        return role_prompts
    
    async def _create_agents_from_roles(self,
                                        roles: List[GeneratedRole],
                                        task: Task,
                                        collaboration_permissions: Dict[str, List[str]],
                                        role_prompts: Dict[str, str]) -> List[Agent]:
        """根据生成的角色信息创建Agent对象"""
        agents = []
        
        for role in roles:
            try:
                # 创建思维向量
                thinking_vector = self._create_thinking_vector(role, task)
                
                # 获取角色的协作权限
                connection_permissions = collaboration_permissions.get(role.name, [])
                
                # 获取角色的专用prompt
                system_prompt = role_prompts.get(role.name, "")
                if not system_prompt:
                    logger.warning(f"角色'{role.name}'缺少system prompt,使用默认prompt")
                    system_prompt = self.prompt_generator._get_default_system_prompt(role, task)
                
                # 创建Agent对象
                agent = Agent(
                    name=role.name,
                    role=role.role_type,
                    responsibilities=role.responsibilities,
                    skills=role.skills,
                    thinking_vector=thinking_vector.get_current_context(),
                    system_prompt=system_prompt,
                    connection_permissions=connection_permissions,
                    max_iterations=task.max_iterations
                )
                
                agents.append(agent)
                logger.debug(f"成功创建Agent:{role.name}")
                
            except Exception as e:
                logger.error(f"创建Agent'{role.name}'失败:{e}")
                continue
        
        return agents
    
    def _create_thinking_vector(self, role: GeneratedRole, task: Task) -> ThinkingVector:
        """创建思维向量"""
        thinking_vector = ThinkingVector(
            core_objective=f"作为{role.name},围绕'{task.description}',完成专业任务输出"
        )
        
        # 添加角色特定的思维节点
        thinking_vector.add_belief(
            role=role.name.lower().replace(" ", "_").replace("师", "").replace("员", ""),
            level=1,
            content=f"围绕{task.domain}领域的{task.description},运用{role.role_type}专业能力,产出{role.output_requirements}"
        )
        
        return thinking_vector
    
    def _validate_agents(self, agents: List[Agent]):
        """验证智能体配置"""
        if not agents:
            raise ValueError("未生成任何智能体")
        
        if len(agents) < self.config.interaction_graph.min_agents:
            raise ValueError(f"智能体数量不足,最少需要{self.config.interaction_graph.min_agents}个")
        
        if len(agents) > self.config.interaction_graph.max_agents:
            raise ValueError(f"智能体数量过多,最多允许{self.config.interaction_graph.max_agents}个")
        
        # 检查角色名称唯一性
        names = [agent.name for agent in agents]
        if len(names) != len(set(names)):
            raise ValueError("智能体名称存在重复")
        
        # 检查必需字段
        for agent in agents:
            if not agent.system_prompt:
                logger.warning(f"智能体'{agent.name}'缺少system_prompt")
            if not agent.connection_permissions and len(agents) > 1:
                logger.warning(f"智能体'{agent.name}'缺少connection_permissions")
        
        logger.info("智能体配置验证通过")
    
    async def regenerate_role_prompt(self, agent: Agent, task: Task, 
                                     collaboration_permissions: Dict[str, List[str]],
                                     all_agents: List[Agent]) -> str:
        """为指定智能体重新生成system prompt"""
        try:
            # 转换Agent为GeneratedRole格式（用于prompt生成）
            role = GeneratedRole(
                name=agent.name,
                role_type=agent.role,
                responsibilities=agent.responsibilities,
                skills=agent.skills,
                output_requirements=f"作为{agent.role}的专业输出",
                priority_level=5  # 默认优先级
            )
            
            # 转换所有Agent为GeneratedRole格式
            all_roles = []
            for a in all_agents:
                all_roles.append(GeneratedRole(
                    name=a.name,
                    role_type=a.role,
                    responsibilities=a.responsibilities,
                    skills=a.skills,
                    output_requirements=f"作为{a.role}的专业输出",
                    priority_level=5
                ))
            
            # 生成新的prompt
            new_prompt = await self.prompt_generator.generate_role_prompt(
                role, task, collaboration_permissions, all_roles
            )
            
            return new_prompt
            
        except Exception as e:
            logger.error(f"重新生成prompt失败:{e}")
            # 返回备用prompt
            role = GeneratedRole(
                name=agent.name,
                role_type=agent.role, 
                responsibilities=agent.responsibilities,
                skills=agent.skills,
                output_requirements=f"作为{agent.role}的专业输出"
            )
            return self.prompt_generator._get_fallback_prompt(role, task)
    
    def get_generation_statistics(self) -> Dict[str, Any]:
        """获取角色生成统计信息"""
        return {
            "distributor_available": self.distributor is not None,
            "prompt_generator_available": self.prompt_generator is not None,
            "config_loaded": True,
            "min_agents": self.config.interaction_graph.min_agents,
            "max_agents": self.config.interaction_graph.max_agents,
            "generation_flow": [
                "1. 角色信息生成 (Distributor)",
                "2. 协作权限分配 (Distributor)", 
                "3. 专用Prompt生成 (PromptGenerator)",
                "4. Agent对象创建 (RoleGenerator)"
            ]
        }
    
    # 保持向后兼容的接口
    def get_available_roles(self, domain: str) -> List[str]:
        """获取指定领域的可用角色列表（向后兼容）"""
        logger.info(f"注意:角色现在由大模型动态生成,不再使用预设角色列表")
        return [f"{domain}相关角色将由AI动态生成"]
    
    def get_role_details(self, role_name: str, domain: str) -> Dict[str, Any]:
        """获取角色详细信息（向后兼容）"""
        logger.info(f"注意:角色详情现在由大模型动态生成")
        return {
            "message": f"角色'{role_name}'的详情将在运行时由AI生成",
            "domain": domain,
            "generation_method": "dynamic_llm_generation"
        }
    
    def _create_requester_agent(self, task: Task, existing_agents: List[Agent]) -> Agent:
        """创建需求方节点"""
        from ..models.data_models import create_requester_agent
        return create_requester_agent(task)
    
    def _update_permissions_with_requester(self, all_agents: List[Agent], collaboration_permissions: Dict[str, List[str]]):
        """更新协作权限,将需求方连接到交互图中"""
        try:
            # 找到需求方和优先级最高的执行角色
            requester_agent = None
            highest_priority_agent = None
            highest_priority = 0
            
            for agent in all_agents:
                if agent.is_requester:
                    requester_agent = agent
                else:
                    # 根据角色名称推断优先级（产品经理、项目经理等通常优先级最高）
                    priority = self._estimate_agent_priority(agent)
                    if priority > highest_priority:
                        highest_priority = priority
                        highest_priority_agent = agent
            
            if requester_agent and highest_priority_agent:
                # 需求方连接到优先级最高的角色
                requester_agent.connection_permissions = [highest_priority_agent.name]
                
                # 优先级最高的角色也能连接到需求方
                if highest_priority_agent.name not in collaboration_permissions:
                    collaboration_permissions[highest_priority_agent.name] = []
                
                # 确保最高优先级角色能回传给需求方
                if "需求方" not in collaboration_permissions[highest_priority_agent.name]:
                    collaboration_permissions[highest_priority_agent.name].append("需求方")
                
                # 更新所有智能体的连接权限
                for agent in all_agents:
                    if agent.name in collaboration_permissions:
                        agent.connection_permissions = collaboration_permissions[agent.name]
                
                logger.info(f"需求方已连接到{highest_priority_agent.name}")
            else:
                logger.warning("无法确定需求方连接目标")
                
        except Exception as e:
            logger.error(f"更新需求方权限失败:{e}")
    
    def _estimate_agent_priority(self, agent: Agent) -> int:
        """估算智能体优先级（无模板）：
        - 若Agent已包含 priority_level，直接使用
        - 否则尝试通过 PromptGenerator 基于上下文即时让LLM给出[1..10]的整数优先级
        - 若LLM不可用/失败，返回默认5
        """
        try:
            if getattr(agent, 'priority_level', None):
                return int(agent.priority_level)
        except Exception:
            pass

        try:
            # 即时推断请求
            prompt = (
                f"请根据角色在协作闭环中的总体协调/决策/统筹重要度，为以下角色打一个1到10的优先级整数（只输出数字，不要解释）：\n"
                f"角色名称: {agent.name}\n"
                f"角色职责: {'; '.join(agent.responsibilities)}\n"
                f"角色描述: {agent.role}\n"
            )
            if hasattr(self.prompt_generator, 'naga_conversation') and self.prompt_generator.naga_conversation:
                resp = asyncio.get_event_loop().run_until_complete(
                    self.prompt_generator.naga_conversation.get_response(prompt, temperature=0.1)
                )
                # 提取首个数字
                import re
                m = re.search(r"(\d{1,2})", str(resp))
                if m:
                    val = max(1, min(10, int(m.group(1))))
                    return val
        except Exception as e:
            logger.warning(f"LLM优先级推断失败，使用默认值: {e}")
        
        return 5 
 