"""
NagaGameSystem - NagaAgent Game 主系统

整合交互图生成器和自博弈模块，提供完整的多智能体协作和博弈优化功能。
包含动态角色生成、协作权限分配、自博弈优化和创新性评估的完整流程。
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from .core.models.data_models import Task, Agent, GameResult, SystemState, create_requester_agent
from .core.models.config import GameConfig, get_domain_config
from .core.interaction_graph import RoleGenerator, SignalRouter, DynamicDispatcher
from .core.interaction_graph.user_interaction_handler import UserInteractionHandler, SystemResponse
from .core.self_game import GameEngine, GameActor, GameCriticizer, PhilossChecker

logger = logging.getLogger(__name__)


@dataclass
class GameSystemResult:
    """游戏系统完整执行结果"""
    task_id: str
    success: bool
    agents: List[Agent]  # 生成的智能体
    game_result: Optional[GameResult]  # 博弈结果
    execution_time: float
    phases_completed: List[str]
    metadata: Dict[str, Any]


class NagaGameSystem:
    """NagaAgent Game 主系统"""
    
    def __init__(self, config: Optional[GameConfig] = None, naga_conversation=None):
        """
        初始化NagaGameSystem
        
        Args:
            config: 游戏配置，如果为None则使用默认配置
            naga_conversation: NagaAgent的会话实例
        """
        self.config = config or GameConfig()
        self.naga_conversation = naga_conversation
        
        # 初始化各个模块
        self.role_generator = RoleGenerator(self.config, naga_conversation)
        self.signal_router = SignalRouter(self.config)
        self.dynamic_dispatcher = DynamicDispatcher(self.config)
        self.game_engine = GameEngine(self.config, naga_conversation)
        self.user_interaction_handler = UserInteractionHandler(self.config)
        
        # 系统状态
        self.system_state = SystemState(current_phase="空闲")
        self.execution_history: List[GameSystemResult] = []
        
        logger.info("NagaGameSystem 初始化完成")
    
    async def process_user_question(self, 
                                   user_question: str,
                                   domain: Optional[str] = None,
                                   expected_agent_count: Optional[Tuple[int, int]] = None,
                                   user_id: str = "default_user") -> SystemResponse:
        """
        处理用户问题的完整流程：生成智能体 → 构建交互图 → 处理问题 → 返回结果
        
        Args:
            user_question: 用户提出的问题
            domain: 领域类型，如果不指定则自动推断
            expected_agent_count: 期望的智能体数量范围
            user_id: 用户标识符
            
        Returns:
            系统响应结果
        """
        try:
            logger.info(f"开始处理用户问题：{user_question[:50]}...")
            self.system_state.current_phase = "初始化"
            
            # 推断或使用指定的领域
            if not domain:
                domain = await self._infer_domain_from_question(user_question)
            
            # 创建任务对象
            task = Task(
                task_id=f"user_task_{int(time.time() * 1000)}",
                description=user_question,
                domain=domain,
                requirements=[user_question],
                constraints=[],
                max_iterations=3  # 用户问题通常不需要太多迭代
            )
            
            # 阶段1: 生成智能体（包含需求方）
            logger.info("阶段1: 生成专业智能体团队")
            self.system_state.current_phase = "角色生成"
            agents = await self.generate_agents_only(task, expected_agent_count)
            
            if not agents:
                raise ValueError("智能体生成失败")
            
            # 阶段2: 构建交互图
            logger.info("阶段2: 构建智能体交互图")
            interaction_graph = await self._execute_interaction_graph_phase(agents, task)
            
            # 阶段3: 处理用户问题
            logger.info("阶段3: 处理用户问题")
            self.system_state.current_phase = "用户交互"
            system_response = await self.user_interaction_handler.process_user_request(
                user_question, interaction_graph, user_id
            )
            
            # 更新系统状态
            self.system_state.current_phase = "完成"
            
            logger.info(f"用户问题处理完成，耗时：{system_response.processing_time:.2f}秒")
            return system_response
            
        except Exception as e:
            logger.error(f"用户问题处理失败：{e}")
            self.system_state.current_phase = "错误"
            
            # 返回错误响应
            from .core.interaction_graph.user_interaction_handler import SystemResponse
            return SystemResponse(
                response_id=f"error_{int(time.time() * 1000)}",
                content=f"抱歉，处理您的问题时出现了错误：{str(e)}",
                source_agent="系统",
                timestamp=time.time(),
                processing_time=0,
                metadata={'error': True, 'error_message': str(e)}
            )
    
    async def _infer_domain_from_question(self, question: str) -> str:
        """基于LLM推理从问题内容推断领域类型"""
        try:
            # 构建领域推断提示词
            domain_inference_prompt = f"""# 任务：领域推断

请分析以下用户问题，推断最适合的专业领域类型。

## 用户问题
{question}

## 推断要求
1. 分析问题的核心内容和需求
2. 识别涉及的专业知识领域
3. 确定最适合处理此问题的专业领域

## 输出格式
请直接输出一个简洁的领域名称，例如：
- 软件开发
- 产品设计  
- 游戏开发
- 商业分析
- 技术架构
- 学术研究
- 或其他更准确的专业领域名称

请基于问题内容推断最合适的领域："""

            # 调用LLM进行推理
            if hasattr(self, 'naga_conversation') and self.naga_conversation:
                try:
                    domain_response = await self.naga_conversation.get_response(
                        domain_inference_prompt,
                        temperature=0.3,  # 较低温度确保推理稳定性
                        max_tokens=50     # 只需要简短的领域名称
                    )
                    
                    # 清理和提取领域名称
                    domain = domain_response.strip().replace('\n', '').replace('。', '').replace('：', '')
                    
                    # 如果响应过长，取第一行
                    if len(domain) > 20:
                        domain = domain.split('\n')[0].strip()
                    
                    logger.info(f"LLM推断问题领域：{domain}")
                    return domain
                    
                except Exception as e:
                    logger.warning(f"LLM领域推断失败，使用启发式推断：{e}")
            
            # 备用方案：基于问题内容的启发式推断
            return self._heuristic_domain_inference(question)
            
        except Exception as e:
            logger.error(f"领域推断失败：{e}")
            return "通用咨询"  # 最通用的领域
    
    def _heuristic_domain_inference(self, question: str) -> str:
        """启发式领域推断（备用方案）"""
        question_lower = question.lower()
        
        # 简单的启发式规则，但不使用固定枚举
        if any(word in question_lower for word in ["开发", "编程", "代码", "系统", "技术"]):
            return "技术开发"
        elif any(word in question_lower for word in ["设计", "产品", "用户", "界面", "体验"]):
            return "产品设计"
        elif any(word in question_lower for word in ["游戏", "玩法", "角色", "关卡"]):
            return "游戏开发"
        elif any(word in question_lower for word in ["研究", "分析", "数据", "实验"]):
            return "研究分析"
        elif any(word in question_lower for word in ["商业", "市场", "营销", "业务"]):
            return "商业咨询"
        else:
            # 基于问题的动词和名词推断更具体的领域
            return "专业咨询"
    
    async def execute_full_game_flow(self, 
                                   task: Task,
                                   expected_agent_count: Optional[Tuple[int, int]] = None,
                                   context: Optional[str] = None) -> GameSystemResult:
        """
        执行完整的游戏流程：角色生成 → 自博弈优化
        
        Args:
            task: 任务描述
            expected_agent_count: 期望的智能体数量范围
            context: 额外上下文信息
            
        Returns:
            完整的执行结果
        """
        start_time = time.time()
        phases_completed = []
        
        try:
            logger.info(f"开始执行完整游戏流程：{task.task_id}")
            self.system_state.current_phase = "角色生成"
            
            # 阶段1: 动态角色生成
            logger.info("阶段1: 动态角色生成")
            agents = await self._execute_role_generation_phase(task, expected_agent_count)
            phases_completed.append("角色生成")
            
            if not agents:
                raise ValueError("角色生成失败，无法继续执行")
            
            # 阶段2: 交互图构建
            logger.info("阶段2: 交互图构建")
            interaction_graph = await self._execute_interaction_graph_phase(agents, task)
            phases_completed.append("交互图构建")
            
            # 更新系统状态
            self.system_state.interaction_graph = interaction_graph
            self.system_state.active_agents = [agent.agent_id for agent in agents]
            
            # 阶段3: 自博弈优化
            logger.info("阶段3: 自博弈优化")
            self.system_state.current_phase = "自博弈"
            game_session = await self.game_engine.start_game_session(task, agents, context)
            phases_completed.append("自博弈优化")
            
            # 提取最终结果
            game_result = game_session.final_result
            if game_result:
                self.system_state.add_game_result(game_result)
            
            # 创建系统执行结果
            system_result = GameSystemResult(
                task_id=task.task_id,
                success=game_result.success if game_result else False,
                agents=agents,
                game_result=game_result,
                execution_time=time.time() - start_time,
                phases_completed=phases_completed,
                metadata={
                    'agent_count': len(agents),
                    'game_rounds': len(game_session.rounds),
                    'final_phase': game_session.status.value,
                    'context_provided': context is not None,
                    'system_state': self.system_state.__dict__
                }
            )
            
            # 记录执行历史
            self.execution_history.append(system_result)
            
            # 更新系统状态
            self.system_state.current_phase = "完成"
            
            logger.info(f"完整游戏流程执行完成：{task.task_id}，成功：{system_result.success}")
            return system_result
            
        except Exception as e:
            logger.error(f"完整游戏流程执行失败：{e}")
            
            # 创建失败结果
            error_result = GameSystemResult(
                task_id=task.task_id,
                success=False,
                agents=[],
                game_result=None,
                execution_time=time.time() - start_time,
                phases_completed=phases_completed,
                metadata={'error': str(e), 'error_phase': self.system_state.current_phase}
            )
            
            self.execution_history.append(error_result)
            self.system_state.current_phase = "错误"
            self.system_state.error_count += 1
            
            return error_result
    
    async def _execute_role_generation_phase(self, 
                                           task: Task, 
                                           expected_agent_count: Optional[Tuple[int, int]]) -> List[Agent]:
        """执行角色生成阶段"""
        try:
            # 根据任务领域获取特定配置
            domain_config = get_domain_config(task.domain)
            if domain_config != self.config:
                # 临时使用领域特定配置
                temp_role_generator = RoleGenerator(domain_config, self.naga_conversation)
                agents = await temp_role_generator.generate_agents(task, expected_agent_count)
            else:
                agents = await self.role_generator.generate_agents(task, expected_agent_count)
            
            logger.info(f"角色生成完成：{len(agents)}个智能体")
            return agents
            
        except Exception as e:
            logger.error(f"角色生成阶段失败：{e}")
            return []
    
    async def _execute_interaction_graph_phase(self, agents: List[Agent], task: Task):
        """执行交互图构建阶段"""
        try:
            interaction_graph = await self.signal_router.build_interaction_graph(agents, task)
            logger.info(f"交互图构建完成：{len(agents)}个节点")
            return interaction_graph
            
        except Exception as e:
            logger.error(f"交互图构建阶段失败：{e}")
            # 返回基本交互图
            from .core.models.data_models import InteractionGraph
            return InteractionGraph(
                agents=agents,
                allowed_paths=[],
                forbidden_paths=[],
                collaboration_matrix={},
                domain=task.domain,
                task_description=task.description
            )
    
    async def generate_agents_only(self, 
                                 task: Task,
                                 expected_agent_count: Optional[Tuple[int, int]] = None) -> List[Agent]:
        """
        仅生成智能体，不执行博弈流程
        
        Args:
            task: 任务描述
            expected_agent_count: 期望的智能体数量范围
            
        Returns:
            生成的智能体列表
        """
        try:
            logger.info(f"开始生成智能体：{task.task_id}")
            self.system_state.current_phase = "角色生成"
            
            agents = await self._execute_role_generation_phase(task, expected_agent_count)
            
            self.system_state.current_phase = "完成"
            logger.info(f"智能体生成完成：{len(agents)}个")
            
            return agents
            
        except Exception as e:
            logger.error(f"智能体生成失败：{e}")
            self.system_state.current_phase = "错误"
            return []
    
    async def execute_self_game_only(self, 
                                   task: Task,
                                   agents: List[Agent],
                                   context: Optional[str] = None) -> Optional[GameResult]:
        """
        仅执行自博弈流程，使用已有的智能体
        
        Args:
            task: 任务描述
            agents: 已生成的智能体列表
            context: 额外上下文信息
            
        Returns:
            博弈结果
        """
        try:
            logger.info(f"开始自博弈流程：{task.task_id}，智能体数量：{len(agents)}")
            self.system_state.current_phase = "自博弈"
            
            game_session = await self.game_engine.start_game_session(task, agents, context)
            
            if game_session.final_result:
                self.system_state.add_game_result(game_session.final_result)
            
            self.system_state.current_phase = "完成"
            logger.info(f"自博弈流程完成：成功：{game_session.final_result.success if game_session.final_result else False}")
            
            return game_session.final_result
            
        except Exception as e:
            logger.error(f"自博弈流程失败：{e}")
            self.system_state.current_phase = "错误"
            return None
    
    def evaluate_novelty(self, content: str, content_id: str) -> float:
        """
        评估内容的创新性（同步接口）
        
        Args:
            content: 待评估内容
            content_id: 内容标识符
            
        Returns:
            创新性评分 (0-10)
        """
        try:
            # 创建异步任务并运行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            philoss_output = loop.run_until_complete(
                self.game_engine.philoss_checker.evaluate_novelty(content, content_id)
            )
            
            loop.close()
            return philoss_output.novelty_score
            
        except Exception as e:
            logger.error(f"创新性评估失败：{e}")
            return 5.0  # 返回中等评分
    
    def get_system_statistics(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        try:
            # 收集各模块统计信息
            role_gen_stats = self.role_generator.get_generation_statistics()
            game_engine_stats = self.game_engine.get_session_statistics()
            
            # 系统整体统计
            successful_executions = [r for r in self.execution_history if r.success]
            
            return {
                'system_info': {
                    'total_executions': len(self.execution_history),
                    'successful_executions': len(successful_executions),
                    'success_rate': len(successful_executions) / len(self.execution_history) * 100 if self.execution_history else 0,
                    'current_phase': self.system_state.current_phase,
                    'total_execution_time': self.system_state.get_total_execution_time(),
                    'error_count': self.system_state.error_count
                },
                'role_generation': role_gen_stats,
                'game_engine': game_engine_stats,
                'latest_result': self.execution_history[-1].__dict__ if self.execution_history else None
            }
            
        except Exception as e:
            logger.error(f"统计信息获取失败：{e}")
            return {'error': str(e)}
    
    def get_latest_result(self) -> Optional[GameSystemResult]:
        """获取最新的执行结果"""
        return self.execution_history[-1] if self.execution_history else None
    
    def clear_history(self):
        """清空执行历史"""
        self.execution_history.clear()
        self.system_state = SystemState(current_phase="空闲")
        
        # 清空各模块历史
        self.game_engine.clear_history()
        
        logger.info("系统历史数据已清空")
    
    def is_philoss_ready(self) -> bool:
        """检查Philoss模块是否就绪"""
        return self.game_engine.philoss_checker.is_model_ready()
    
    def get_current_phase(self) -> str:
        """获取当前执行阶段"""
        return self.system_state.current_phase
    
    async def health_check(self) -> Dict[str, Any]:
        """系统健康检查"""
        try:
            health_status = {
                'system': 'healthy',
                'modules': {
                    'role_generator': 'ready',
                    'signal_router': 'ready',
                    'dynamic_dispatcher': 'ready',
                    'game_engine': 'ready'
                },
                'components': {
                    'philoss_checker': 'ready' if self.is_philoss_ready() else 'simulation_mode',
                    'naga_api': 'available' if self.naga_conversation else 'simulation_mode'
                },
                'current_phase': self.system_state.current_phase,
                'error_count': self.system_state.error_count,
                'execution_count': len(self.execution_history)
            }
            
            # 简单功能测试
            test_task = Task(
                task_id="health_check",
                description="系统健康检查测试",
                domain="测试",
                requirements=["基本功能"],
                max_iterations=1
            )
            
            # 测试角色生成
            try:
                test_agents = await self.generate_agents_only(test_task, (1, 2))
                if test_agents:
                    health_status['modules']['role_generator'] = 'tested_ok'
                else:
                    health_status['modules']['role_generator'] = 'warning'
            except Exception:
                health_status['modules']['role_generator'] = 'error'
            
            return health_status
            
        except Exception as e:
            logger.error(f"健康检查失败：{e}")
            return {
                'system': 'error',
                'error': str(e),
                'current_phase': self.system_state.current_phase
            } 
 
 