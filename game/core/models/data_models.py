"""
NagaAgent Game 数据模型定义
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import torch


@dataclass
class Agent:
    """智能体数据模型"""
    name: str  # 智能体名称 (大模型生成)
    role: str  # 角色描述 (大模型生成)
    responsibilities: List[str]  # 职责列表 (大模型生成)
    skills: List[str]  # 技能标签 (大模型生成)
    thinking_vector: str  # 思维向量
    system_prompt: str  # 角色专用system prompt (Prompt Generator生成)
    connection_permissions: List[str]  # 连接权限列表 (系统分配)
    agent_id: str = field(default_factory=lambda: f"agent_{int(time.time()*1000)}")
    max_iterations: int = 10  # 最大迭代次数
    current_iteration: int = 0  # 当前迭代次数
    is_requester: bool = False  # 是否为需求方节点
    priority_level: int = 5  # 动态优先级（由LLM生成或即时推断）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'agent_id': self.agent_id,
            'name': self.name,
            'role': self.role,
            'responsibilities': self.responsibilities,
            'skills': self.skills,
            'thinking_vector': self.thinking_vector,
            'system_prompt': self.system_prompt,
            'connection_permissions': self.connection_permissions,
            'max_iterations': self.max_iterations,
            'current_iteration': self.current_iteration,
            'is_requester': self.is_requester,
            'priority_level': self.priority_level
        }


@dataclass
class RoleGenerationRequest:
    """角色生成请求"""
    task_description: str  # 任务描述
    domain: str  # 领域类型
    expected_count_range: Tuple[int, int]  # 期望角色数量范围
    constraints: List[str] = field(default_factory=list)  # 约束条件


@dataclass
class GeneratedRole:
    """大模型生成的角色信息"""
    name: str  # 角色名称
    role_type: str  # 角色类型
    responsibilities: List[str]  # 职责列表
    skills: List[str]  # 技能列表
    output_requirements: str  # 输出要求
    priority_level: int = 1  # 优先级（1-10）


@dataclass
class InteractionGraph:
    """交互图数据模型"""
    agents: List[Agent]  # 智能体列表
    allowed_paths: List[Tuple[str, str]]  # 允许的通信路径 (from_agent_id, to_agent_id)
    forbidden_paths: List[Tuple[str, str]]  # 禁止的直接连接
    collaboration_matrix: Dict[str, Dict[str, str]]  # 协作关系矩阵
    domain: str  # 领域类型
    task_description: str  # 任务描述
    
    def get_reachable_agents(self, from_agent_id: str) -> List[str]:
        """获取从指定智能体可到达的智能体列表"""
        reachable = []
        for from_id, to_id in self.allowed_paths:
            if from_id == from_agent_id:
                reachable.append(to_id)
        return reachable
    
    def is_path_allowed(self, from_agent_id: str, to_agent_id: str) -> bool:
        """检查路径是否被允许"""
        return (from_agent_id, to_agent_id) in self.allowed_paths
    
    def get_agent_by_id(self, agent_id: str) -> Optional[Agent]:
        """根据ID获取智能体"""
        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        return None


@dataclass
class TextBlock:
    """文本块数据模型 - 用于Philoss处理"""
    content: str  # 文本内容
    token_count: int  # token数量
    block_index: int  # 块索引
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if self.token_count <= 0:
            # 粗略估算token数量（1个token ≈ 4个字符）
            self.token_count = max(1, len(self.content) // 4)


@dataclass  
class HiddenState:
    """隐藏状态数据模型 - Philoss使用"""
    layer_index: int  # 层索引
    state_vector: torch.Tensor  # 状态向量
    timestamp: float = field(default_factory=time.time)
    block_index: int = 0  # 对应的文本块索引
    
    def __post_init__(self):
        if not isinstance(self.state_vector, torch.Tensor):
            raise ValueError("state_vector必须是torch.Tensor类型")


@dataclass
class NoveltyScore:
    """创新性评分数据模型"""
    score: float  # 创新性得分 (0-1)
    prediction_errors: List[float]  # 预测误差列表
    analysis: str  # 分析报告
    is_novel: bool  # 是否具有创新性
    confidence: float = 0.0  # 置信度
    
    def __post_init__(self):
        # 确保得分在合理范围内
        self.score = max(0.0, min(1.0, self.score))
        # 根据得分判断创新性（阈值0.6）
        if self.is_novel is None:
            self.is_novel = self.score >= 0.6


@dataclass
class CriticScore:
    """批判评分数据模型"""
    critical_score: float  # 批判得分 (0-1)
    satisfaction_score: float  # 满意度得分 (0-1)
    dimensions: Dict[str, float]  # 各维度得分
    suggestions: List[str]  # 改进建议
    analysis: str  # 批判分析
    
    def __post_init__(self):
        self.critical_score = max(0.0, min(1.0, self.critical_score))
        self.satisfaction_score = max(0.0, min(1.0, self.satisfaction_score))


@dataclass
class GameResult:
    """博弈结果数据模型"""
    actor_output: Any  # Actor输出结果
    critic_scores: Dict[str, CriticScore]  # Criticizer评分结果
    novel_score: NoveltyScore  # 创新性评分
    iteration_count: int  # 迭代次数
    final_consensus: str  # 最终共识
    phase: str = "完成"  # 博弈阶段（字符串）
    success: bool = True  # 是否成功
    error_message: str = ""  # 错误信息
    execution_time: float = 0.0  # 执行时间
    
    def get_average_critic_score(self) -> float:
        """获取平均批判得分"""
        if not self.critic_scores:
            return 0.0
        total = sum(score.critical_score for score in self.critic_scores.values())
        return total / len(self.critic_scores)
    
    def get_overall_quality(self) -> float:
        """获取整体质量得分"""
        avg_critic = self.get_average_critic_score()
        novel = self.novel_score.score if self.novel_score else 0.0
        return (avg_critic + novel) / 2


@dataclass
class SystemState:
    """系统状态数据模型"""
    current_phase: str  # 当前阶段（字符串）
    interaction_graph: Optional[InteractionGraph] = None  # 交互图
    active_agents: List[str] = field(default_factory=list)  # 活跃智能体ID列表
    game_history: List[GameResult] = field(default_factory=list)  # 博弈历史
    error_count: int = 0  # 错误计数
    start_time: float = field(default_factory=time.time)  # 开始时间
    
    def add_game_result(self, result: GameResult):
        """添加博弈结果"""
        self.game_history.append(result)
        if not result.success:
            self.error_count += 1
    
    def get_latest_result(self) -> Optional[GameResult]:
        """获取最新的博弈结果"""
        return self.game_history[-1] if self.game_history else None
    
    def get_total_execution_time(self) -> float:
        """获取总执行时间"""
        return time.time() - self.start_time


@dataclass
class Task:
    """任务数据模型"""
    task_id: str  # 任务ID
    description: str  # 任务描述
    domain: str  # 领域
    requirements: List[str]  # 需求列表
    constraints: List[str] = field(default_factory=list)  # 约束条件
    max_iterations: int = 10  # 最大迭代次数
    timeout: int = 300  # 超时时间（秒）
    priority: int = 1  # 优先级（1-10）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'task_id': self.task_id,
            'description': self.description,
            'domain': self.domain,
            'requirements': self.requirements,
            'constraints': self.constraints,
            'max_iterations': self.max_iterations,
            'timeout': self.timeout,
            'priority': self.priority
        }


# 思维栈相关数据结构
@dataclass  
class BeliefNode:
    """思维栈节点"""
    role: str  # 角色名
    level: int  # 层级
    content: str  # 核心目标描述
    
    def format(self) -> str:
        """格式化为思维栈字符串"""
        return f"<belief {self.role} {self.level}>{self.content}</belief {self.role} {self.level}>"


@dataclass
class ThinkingVector:
    """思维向量"""
    core_objective: str  # 核心目标
    belief_stack: List[BeliefNode] = field(default_factory=list)  # 思维栈
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文信息
    
    def add_belief(self, role: str, level: int, content: str):
        """添加思维节点"""
        belief = BeliefNode(role=role, level=level, content=content)
        self.belief_stack.append(belief)
    
    def format_stack(self) -> str:
        """格式化整个思维栈"""
        if not self.belief_stack:
            return ""
        return "\n".join(belief.format() for belief in self.belief_stack)
    
    def get_current_context(self) -> str:
        """获取当前思维上下文"""
        context_str = f"核心目标: {self.core_objective}\n"
        if self.belief_stack:
            context_str += "当前思维栈:\n" + self.format_stack()
        return context_str


@dataclass
class PromptTemplate:
    """提示词模板"""
    role_name: str  # 角色名称
    system_prompt: str  # 系统提示词
    task_context: str  # 任务上下文
    collaboration_context: str  # 协作上下文
    thinking_vector_context: str  # 思维向量上下文
    
    def format_full_prompt(self) -> str:
        """格式化完整提示词"""
        sections = [
            f"# 角色身份\n你是{self.role_name}.\n",
            f"# 系统指令\n{self.system_prompt}\n",
            f"# 任务上下文\n{self.task_context}\n",
            f"# 协作关系\n{self.collaboration_context}\n",
            f"# 思维约束\n{self.thinking_vector_context}\n"
        ]
        return "\n".join(sections)


# Philoss模块相关数据结构
@dataclass
class HiddenState:
    """隐藏状态数据模型"""
    state_id: str  # 状态ID
    vector: List[float]  # 隐藏状态向量
    block_id: str  # 对应的文本块ID
    timestamp: float  # 时间戳
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'state_id': self.state_id,
            'vector': self.vector,
            'block_id': self.block_id,
            'timestamp': self.timestamp
        }


@dataclass
class TextBlock:
    """文本块数据模型"""
    block_id: str  # 块ID
    content: str  # 文本内容
    token_count: int  # token数量
    start_position: int  # 起始位置
    end_position: int  # 结束位置
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'block_id': self.block_id,
            'content': self.content,
            'token_count': self.token_count,
            'start_position': self.start_position,
            'end_position': self.end_position
        }


@dataclass
class NoveltyScore:
    """创新性评分数据模型"""
    score: float  # 创新性分数 (0-10)
    confidence: float  # 置信度 (0-1)
    reasoning: str  # 评分理由
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据


def create_requester_agent(task: 'Task') -> Agent:
    """
    创建需求方节点
    
    Args:
        task: 任务信息,用于生成需求方描述
        
    Returns:
        需求方智能体节点
    """
    return Agent(
        name="需求方",
        role="需求提出者",
        responsibilities=[
            "提出任务需求",
            "接收最终方案",
            "评估方案可行性",
            "确认需求满足度"
        ],
        skills=[
            "需求表达",
            "方案评估",
            "沟通协调"
        ],
        thinking_vector=f"核心目标: 确保'{task.description}'的需求得到满足",
        system_prompt=f"""你是需求方,代表提出'{task.description}'这个需求的用户.

你的职责:
1. 清晰表达任务需求和期望
2. 接收团队提供的方案
3. 评估方案是否满足需求
4. 提供反馈和确认

注意:
- 你代表真实用户的需求和期望
- 当收到方案时,要从用户角度评估其可行性
- 如果方案不满足需求,要明确指出问题所在
- 如果方案满足需求,要给予确认和感谢""",
        connection_permissions=[],  # 将在构建交互图时设置
        agent_id="requester_node",
        is_requester=True
    ) 



 