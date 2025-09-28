"""
UserInteractionHandler - 用户交互处理器

专门处理需求方节点的特殊逻辑,包括:
1. 接收用户的原始问题
2. 将问题传递给第一个执行节点
3. 接收最终结果并返回给用户
4. 管理整个交互流程的状态
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from ..models.data_models import Agent, Task, InteractionGraph
from ..models.config import GameConfig

logger = logging.getLogger(__name__)


@dataclass
class UserMessage:
    """用户消息数据模型"""
    message_id: str
    content: str
    timestamp: float
    user_id: str = "default_user"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'message_id': self.message_id,
            'content': self.content,
            'timestamp': self.timestamp,
            'user_id': self.user_id
        }


@dataclass
class SystemResponse:
    """系统响应数据模型"""
    response_id: str
    content: str
    source_agent: str
    timestamp: float
    processing_time: float
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'response_id': self.response_id,
            'content': self.content,
            'source_agent': self.source_agent,
            'timestamp': self.timestamp,
            'processing_time': self.processing_time,
            'metadata': self.metadata
        }


@dataclass
class InteractionSession:
    """交互会话数据模型"""
    session_id: str
    user_message: UserMessage
    system_response: Optional[SystemResponse]
    interaction_graph: InteractionGraph
    processing_steps: List[str]
    start_time: float
    end_time: Optional[float]
    status: str  # "processing", "completed", "failed"


class UserInteractionHandler:
    """用户交互处理器"""
    
    def __init__(self, config: GameConfig, naga_conversation=None):
        """
        初始化用户交互处理器
        
        Args:
            config: 游戏配置
            naga_conversation: 可选的NagaAgent会话实例
        """
        self.config = config
        self.active_sessions: Dict[str, InteractionSession] = {}
        self.session_history: List[InteractionSession] = []
        self.naga_conversation = naga_conversation
        self._init_naga_api()
    
    def _init_naga_api(self):
        if self.naga_conversation is None:
            try:
                from system.conversation_core import NagaConversation
                self.naga_conversation = NagaConversation()
                logger.info("UserInteractionHandler 已接入 NagaConversation")
            except Exception as e:
                logger.warning(f"UserInteractionHandler 未能接入NagaConversation, 将在必要时使用降级方案: {e}")
                self.naga_conversation = None
    
    async def process_user_request(self, 
                                 user_input: str,
                                 interaction_graph: InteractionGraph,
                                 user_id: str = "default_user") -> SystemResponse:
        """
        处理用户请求的完整流程
        
        Args:
            user_input: 用户输入的问题或需求
            interaction_graph: 已构建的交互图
            user_id: 用户标识符
            
        Returns:
            系统最终响应
        """
        start_time = time.time()
        session_id = f"session_{int(time.time() * 1000)}"
        
        # 创建用户消息
        user_message = UserMessage(
            message_id=f"msg_{int(time.time() * 1000)}",
            content=user_input,
            timestamp=start_time,
            user_id=user_id
        )
        
        # 创建交互会话
        session = InteractionSession(
            session_id=session_id,
            user_message=user_message,
            system_response=None,
            interaction_graph=interaction_graph,
            processing_steps=[],
            start_time=start_time,
            end_time=None,
            status="processing"
        )
        
        self.active_sessions[session_id] = session
        
        try:
            logger.info(f"开始处理用户请求:{session_id}")
            
            # 步骤1:验证交互图
            self._validate_interaction_graph(interaction_graph, session)
            
            # 步骤2:找到需求方节点和第一个执行节点
            requester_agent, first_executor = self._identify_key_agents(interaction_graph, session)
            
            # 步骤3:启动内部处理流程
            final_result = await self._execute_internal_processing(
                user_input, requester_agent, first_executor, interaction_graph, session
            )
            
            # 步骤4:构建系统响应
            system_response = self._build_system_response(
                final_result, first_executor, start_time, session
            )
            
            # 步骤5:完成会话
            session.system_response = system_response
            session.end_time = time.time()
            session.status = "completed"
            
            # 移动到历史记录
            self.session_history.append(session)
            del self.active_sessions[session_id]
            
            logger.info(f"用户请求处理完成:{session_id}")
            return system_response
            
        except Exception as e:
            logger.error(f"用户请求处理失败:{e}")
            
            # 创建错误响应
            error_response = SystemResponse(
                response_id=f"error_{int(time.time() * 1000)}",
                content=f"抱歉,处理您的请求时出现了问题:{str(e)}",
                source_agent="系统",
                timestamp=time.time(),
                processing_time=time.time() - start_time,
                metadata={'error': True, 'error_message': str(e)}
            )
            
            session.system_response = error_response
            session.end_time = time.time()
            session.status = "failed"
            
            # 移动到历史记录
            self.session_history.append(session)
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
            
            return error_response
    
    def _validate_interaction_graph(self, interaction_graph: InteractionGraph, session: InteractionSession):
        """验证交互图的有效性"""
        session.processing_steps.append("验证交互图结构")
        
        if not interaction_graph.agents:
            raise ValueError("交互图中没有智能体")
        
        # 检查是否有需求方节点
        requester_agents = [agent for agent in interaction_graph.agents if agent.is_requester]
        if not requester_agents:
            raise ValueError("交互图中缺少需求方节点")
        
        if len(requester_agents) > 1:
            raise ValueError("交互图中有多个需求方节点")
        
        # 检查是否有执行节点
        execution_agents = [agent for agent in interaction_graph.agents if not agent.is_requester]
        if not execution_agents:
            raise ValueError("交互图中缺少执行节点")
        
        logger.debug(f"交互图验证通过:需求方1个,执行节点{len(execution_agents)}个")
    
    def _identify_key_agents(self, interaction_graph: InteractionGraph, session: InteractionSession) -> Tuple[Agent, Agent]:
        """识别关键智能体:需求方和第一个执行者"""
        session.processing_steps.append("识别关键智能体节点")
        
        # 找到需求方
        requester_agent = None
        for agent in interaction_graph.agents:
            if agent.is_requester:
                requester_agent = agent
                break
        
        # 找到第一个执行者（需求方连接的第一个节点）
        first_executor = None
        if requester_agent and requester_agent.connection_permissions:
            first_executor_name = requester_agent.connection_permissions[0]
            for agent in interaction_graph.agents:
                if agent.name == first_executor_name:
                    first_executor = agent
                    break
        
        if not first_executor:
            # 如果没有明确连接,找优先级最高的执行节点
            execution_agents = [agent for agent in interaction_graph.agents if not agent.is_requester]
            if execution_agents:
                first_executor = execution_agents[0]  # 简单取第一个
        
        if not requester_agent or not first_executor:
            raise ValueError("无法识别需求方或第一个执行者")
        
        logger.debug(f"关键智能体:需求方={requester_agent.name},第一执行者={first_executor.name}")
        return requester_agent, first_executor
    
    async def _execute_internal_processing(self, 
                                         user_input: str,
                                         requester_agent: Agent,
                                         first_executor: Agent,
                                         interaction_graph: InteractionGraph,
                                         session: InteractionSession) -> str:
        """执行内部处理流程"""
        session.processing_steps.append("执行内部智能体协作")
        
        logger.info(f"需求方'{requester_agent.name}'将请求传递给'{first_executor.name}'")
        
        # 模拟处理时间
        await asyncio.sleep(0.1)
        
        # 构建处理上下文(加强反套话约束)
        processing_prompt = f"""# 任务
用户问题: {user_input}

# 你的身份
你是{first_executor.name} ({first_executor.role}).

# 你的职责
{chr(10).join(f"- {resp}" for resp in first_executor.responsibilities)}

# 你的技能
{chr(10).join(f"- {skill}" for skill in first_executor.skills)}

# 回应要求(非常重要)
1. 先给出直接结论或最终答案,避免铺垫性空话.
2. 逐步推理与详细展开,用条目结构表达清晰的步骤.
3. 严禁套话/模板化措辞/全局性空话; 不得复述问题.
4. 给出可执行的方案/证明/公式/代码/示例(视问题类型而定).
5. 标注关键假设与边界条件.如不确定,明确说明不确定性及需要的额外信息.
6. 输出必须自洽可检验.数学问题需给出严谨证明; 工程问题需给出步骤与接口.

# 输出格式
- 结论
- 思路/推导/算法
- 实施/证明步骤
- 验证与边界
- 后续优化
"""
        
        # 优先使用LLM生成(避免套话)
        if self.naga_conversation is not None:
            try:
                response = await self.naga_conversation.get_response(
                    processing_prompt,
                    temperature=0.4
                )
                return response.strip()
            except Exception as e:
                logger.warning(f"LLM生成响应失败,使用基于角色信息的动态响应: {e}")
        
        # 降级: 基于角色信息的动态响应(去模板化)
        return f"这里因为naga_conversation为空，返回模板结论与推导: 基于{first_executor.role}的专业能力,针对'{user_input}'给出最简必要的结论与关键推导."
    
    def _generate_role_based_response(self, user_input: str, executor: Agent) -> str:
        """基于角色信息生成动态响应（更聚焦,避免空话）"""
        response_parts = [
            f"# 结论",
            f"- 基于问题 \"{user_input}\" 的直接答案/方案见下",
            "",
            "# 思路/推导/算法",
            f"- 结合{executor.role}职责与技能,分解问题并逐步构建解法",
            "",
            "# 实施/证明步骤",
            "1. 明确目标与已知条件",
            "2. 列出关键约束与必要工具",
            "3. 分解为若干可执行子步骤并逐一完成",
            "4. 给出中间结论与最终产出",
            "",
            "# 验证与边界",
            "- 给出可验证方式与适用边界",
            "",
            "# 后续优化",
            "- 指出可改进点与下一步工作",
            "",
            f"---\n*{executor.name} | {executor.role}*"
        ]
        return "\n".join(response_parts)
    
    def _build_system_response(self, 
                              final_result: str,
                              source_agent: Agent,
                              start_time: float,
                              session: InteractionSession) -> SystemResponse:
        """构建系统响应"""
        session.processing_steps.append("构建最终响应")
        
        return SystemResponse(
            response_id=f"resp_{int(time.time() * 1000)}",
            content=final_result,
            source_agent=source_agent.name,
            timestamp=time.time(),
            processing_time=time.time() - start_time,
            metadata={
                'session_id': session.session_id,
                'processing_steps': session.processing_steps,
                'agent_count': len(session.interaction_graph.agents),
                'user_id': session.user_message.user_id
            }
        )
    
    def get_session_statistics(self) -> Dict[str, Any]:
        """获取会话统计信息"""
        total_sessions = len(self.session_history)
        successful_sessions = len([s for s in self.session_history if s.status == "completed"])
        
        if total_sessions == 0:
            return {
                'total_sessions': 0,
                'successful_sessions': 0,
                'success_rate': 0,
                'average_processing_time': 0,
                'active_sessions': len(self.active_sessions)
            }
        
        total_processing_time = sum(
            (s.end_time - s.start_time) for s in self.session_history if s.end_time
        )
        
        return {
            'total_sessions': total_sessions,
            'successful_sessions': successful_sessions,
            'failed_sessions': total_sessions - successful_sessions,
            'success_rate': successful_sessions / total_sessions * 100,
            'average_processing_time': total_processing_time / total_sessions,
            'active_sessions': len(self.active_sessions)
        }
    
    def get_latest_session(self) -> Optional[InteractionSession]:
        """获取最新的会话"""
        return self.session_history[-1] if self.session_history else None
    
    def clear_history(self):
        """清空历史记录"""
        self.session_history.clear()
        self.active_sessions.clear()
        logger.info("用户交互历史已清空") 