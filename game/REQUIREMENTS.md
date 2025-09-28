# NagaAgent 多智能体系统需求文档

## 1. 项目概述

### 1.1 项目背景
大型语言模型（LLM）在多智能体系统中处理复杂问题时面临两个核心挑战：
- **信息差问题**：多智能体信息交互时因上下文长度限制和角色设定不同造成严重信息差
- **博弈干扰问题**：博弈式互评时容易受到批判方干扰，难以兼顾"坚持己见"与"博采众长"

### 1.2 项目目标
设计并实现 **NagaAgent Game** 多智能体博弈系统，专注于提升推理过程的透明度、鲁棒性与最终方案质量。

### 1.3 核心价值
- 通过结构化协作避免信息差
- 通过多轮博弈机制提升决策质量
- 通过创新性评估保证输出质量

## 2. 系统架构

### 2.1 整体架构
```
┌─────────────────────────────────────────────────────────────┐
│                  NagaAgent Game 多智能体博弈系统               │
├─────────────────────────────────────────────────────────────┤
│  核心模块1: 交互图生成器 (Interaction Graph Generator)        │
│  ┌─────────────┬─────────────┬─────────────────────────────┐ │
│  │  角色生成    │ 信号链路构建 │    动态传输决策              │ │
│  └─────────────┴─────────────┴─────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  核心模块2: 模型自博弈模块 (Self-Game Module)                 │
│  ┌─────────────┬─────────────┬─────────────────────────────┐ │
│  │   Actor     │ Criticizer  │        Checker             │ │
│  │   (生成)    │   (批判)    │   (基于Philoss创新性评估)   │ │
│  │             │   (1:n:1)   │                            │ │
│  └─────────────┴─────────────┴─────────────────────────────┘ │
│                                                             │
│  Checker详细架构：                                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 大模型API调用 → 文本块切分(100 token) → Qwen2.5-VL 7B   │ │
│  │                                    ↓                    │ │
│  │              Philoss MLP层 → 隐藏状态预测 → 创新度评估   │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块间交互关系
1. 交互图生成器初始化整个系统，定义角色和协作关系
2. 模型自博弈模块执行具体推理和优化任务，集成Philoss创新性评估

## 3. 核心模块需求

### 3.1 核心模块1：交互图生成器

#### 3.1.1 角色生成功能 (Distributor)
**功能描述**：通过大模型API动态生成与任务强相关的功能性角色，无预设角色枚举。

**核心组件**：
- **Distributor**: 角色分配器，负责调用大模型生成角色
- **Prompt Generator**: 专门的提示词生成器，为每个角色生成专用system prompt

**输入**：
- 研究主题/任务目标描述
- 领域类型（如：游戏开发、学术研究、产品设计等）
- 期望角色数量范围

**处理流程**：
1. **角色生成阶段**：
   - 使用专门的系统提示词调用大模型API
   - 要求大模型根据任务生成角色名称和职能描述
   - 格式化提取角色信息（JSON格式）
   
2. **权限分配阶段**：
   - 为每个生成的角色分配协作连接权限
   - 构建角色分工协作图
   - 定义角色间的通信规则

3. **提示词生成阶段**：
   - 使用Prompt Generator为每个角色生成专用system prompt
   - 包含角色职责、协作关系、思维向量等

**输出**：
- 动态生成的角色列表，每个角色包含：
  - 角色名称（大模型生成）
  - 任务职责描述（大模型生成）
  - 专业技能标签（大模型生成）
  - 连接权限列表（系统分配）
  - 专用system prompt（Prompt Generator生成）

**技术要求**：
- 集成NagaAgent现有的大模型API调用能力
- 支持JSON格式的角色信息提取和验证
- 动态构建角色协作权限图
- 为每个角色生成个性化提示词

**角色生成System Prompt模板**：
```
你是一个专业的团队组织专家，需要为特定项目任务设计最佳的角色分工方案。

【任务信息】
任务描述：{task_description}
任务领域：{domain}
复杂度评估：{complexity_level}
预期角色数量：{expected_count}个

【生成要求】
请生成{expected_count}个角色，确保：
1. 角色覆盖任务的全生命周期
2. 职责边界清晰，避免重复
3. 技能互补，形成完整闭环
4. 协作关系合理，便于信息传递

【输出格式】
请严格按照JSON格式输出：
{
  "roles": [
    {
      "name": "角色名称",
      "description": "角色定位和主要价值",
      "responsibilities": ["职责1", "职责2", "职责3"],
      "skills": ["技能1", "技能2", "技能3", "技能4"],
      "collaboration_needs": ["需要与XXX角色协作完成YYY", "向ZZZ角色提供AAA信息"]
    }
  ]
}
```

**Prompt Generator设计规范**：
为每个生成的角色创建专用system prompt，包含：
- 角色身份定位
- 具体职责清单
- 当前任务上下文
- 协作伙伴信息
- 思维向量约束
- 输出格式要求

**API集成方案**：
- 复用NagaAgent的`system.conversation_core.NagaConversation`
- 使用相同的配置系统和API密钥
- 保持与主系统的统一日志和错误处理

#### 3.1.2 信号链路构建功能
**功能描述**：依据各角色的职责逻辑与协作关系，制定定向的信息传输规则。

**输入**：
- 生成的角色列表
- 协作逻辑规则

**输出**：
- 有向图结构的信息传输路径
- 允许的通信路径定义
- 禁止的直接连接规则

**设计原则**：
- 避免跨角色职责的无效沟通
- 通过中间节点完成间接信息传输
- 保障信息传递的精准性

**示例**（游戏开发场景）：
```
产品经理 ⇄ 程序员
产品经理 ⇄ 美工
程序员 ⇄ 测试人员
禁止：产品经理 ↔ 测试人员（需通过程序员）
禁止：程序员 ↔ 美工（需通过产品经理）
```

#### 3.1.3 动态传输决策功能
**功能描述**：每个角色完成任务后，根据输出结果和下阶段需求，自主选择目标角色传递信息。

**输入**：
- 当前角色的任务输出
- 下一阶段需求描述
- 可用的传输路径

**输出**：
- 选择的目标角色
- 传输的信息内容
- 传输原因说明

**约束条件**：
- 迭代轮次限制（防止思维盲区）
- 强制交接机制（轮次过多时）
- 任务完成情况评估

### 3.2 核心模块2：模型自博弈模块

#### 3.2.1 系统组成
采用 **"Actor-Criticizer-Checker"** 三组件架构，比例为 **1:n:1**。

#### 3.2.2 Actor 组件
**核心职责**：功能生成

**输入**：
- 上游角色指令
- 任务目标描述
- 思维向量约束

**输出**：
- 初始任务成果
- 完成状态报告

**功能要求**：
- 执行具体的模块功能（论文框架生成、实验方案设计等）
- 基于思维向量保持任务一致性
- 支持function-call形式的思维向量更新

#### 3.2.3 Criticizer 组件
**核心职责**：成果批判与优化建议

**输入**：
- Actor的初始成果
- 任务目标和领域知识
- 评估标准

**输出**：
- 多维度批判分析
- 优化建议
- Critical Score（批判得分）
- Satisfaction Score（建议满意度得分）

**评估维度**：
- 逻辑一致性
- 创新性水平
- 细节完整性
- 可行性分析

#### 3.2.4 Checker 组件
**核心职责**：基于Philoss模块的创新性评估

**技术架构**：
- **大模型调用层**：通过API调度大模型获取输出文本
- **本地小模型层**：部署Qwen2.5-VL 7B模型作为评估引擎
- **Philoss评估层**：植入MLP层进行隐藏状态预测

**Philoss原理**：
1. **参数冻结**：冻结Qwen2.5-VL模型的其他参数，仅在模型内部置入MLP层
2. **状态预测**：MLP层基于当前隐藏状态State_x预测下一状态State_x+1
3. **创新度量**：预测误差大说明模型思考模式有趣、创新度高；误差小说明思维模式常规、无创新

**实现细节**：
- **文本块切分**：将大模型输出按100个token一组切分为文本块
- **状态更新**：小模型不基于自回归，而是基于大模型的文本块更新隐藏层状态
- **预测机制**：Philoss基于文本块序列预测隐藏层状态变化

**输入**：
- 大模型生成的文本输出
- 预设评估维度

**输出**：
- Novel Score（新颖性得分，基于预测误差）
- 状态预测误差分析
- 创新点识别报告
- 是否进入下轮优化的建议

**评估流程**：
```
大模型输出 → 100token切分 → 文本块序列 → Qwen2.5-VL处理 
    ↓
隐藏状态序列 → Philoss MLP预测 → 预测误差计算 → 创新度评分
```

#### 3.2.5 思维向量和思维栈机制
**思维向量设计**：
- 锚定核心思考方向
- 保障任务一致性
- 支持动态调整

**思维栈格式**：
```
<belief 角色名 层级>核心目标描述</belief 角色名 层级>
```

**功能要求**：
- 每次提示词末尾注入当前思维栈
- 支持思维向量的外包传递
- 确保子任务与整体目标一致



## 4. 技术实现要求

### 4.1 编程语言和框架
- **主语言**：Python 3.10+
- **AI框架**：集成现有NagaAgent的LLM调用能力
- **本地模型**：Qwen2.5-VL 7B（用于Philoss评估）
- **深度学习框架**：PyTorch（用于MLP层实现）
- **异步处理**：AsyncIO
- **配置管理**：支持热更新的配置系统
- **模型推理**：Transformers, VLLM（本地模型加速推理）

### 4.2 接口设计

#### 4.2.1 主要API接口
```python
class NagaGameSystem:
    async def initialize_system(self, task_description: str, domain: str) -> SystemState
    async def generate_interaction_graph(self, agents: List[Agent]) -> InteractionGraph
    async def execute_self_game(self, task: Task, max_iterations: int) -> GameResult
    async def evaluate_novelty(self, text_output: str) -> NoveltyScore

class Distributor:
    """角色分配器 - 通过大模型API生成角色"""
    async def generate_roles(self, task: Task, expected_count_range: Tuple[int, int]) -> List[Dict]
    async def assign_collaboration_permissions(self, roles: List[Dict]) -> Dict[str, List[str]]
    
class PromptGenerator:
    """提示词生成器 - 为每个角色生成专用system prompt"""
    async def generate_role_prompt(self, role_info: Dict, collaboration_graph: Dict) -> str
    async def generate_distributor_prompt(self, task: Task, domain: str) -> str
    
class PhilossChecker:
    async def initialize_model(self, model_path: str) -> bool
    async def process_text_blocks(self, text_blocks: List[str]) -> List[HiddenState]
    async def predict_next_state(self, current_state: HiddenState) -> HiddenState
    async def calculate_novelty_score(self, prediction_errors: List[float]) -> float
```

#### 4.2.2 数据模型
```python
@dataclass
class Agent:
    name: str  # 大模型生成
    role: str  # 大模型生成
    responsibilities: List[str]  # 大模型生成
    skills: List[str]  # 大模型生成
    thinking_vector: str
    system_prompt: str  # Prompt Generator生成
    connection_permissions: List[str]  # 系统分配的连接权限

@dataclass
class RoleGenerationRequest:
    """角色生成请求"""
    task_description: str
    domain: str
    expected_count_range: Tuple[int, int]
    constraints: List[str]

@dataclass
class GeneratedRole:
    """大模型生成的角色信息"""
    name: str
    role_type: str
    responsibilities: List[str]
    skills: List[str]
    output_requirements: str
    priority_level: int

@dataclass
class InteractionGraph:
    agents: List[Agent]
    allowed_paths: List[Tuple[str, str]]
    forbidden_paths: List[Tuple[str, str]]
    collaboration_matrix: Dict[str, Dict[str, str]]  # 协作关系矩阵

@dataclass
class GameResult:
    actor_output: Any
    critic_scores: Dict[str, float]
    novel_score: float
    iteration_count: int
    final_consensus: str

@dataclass
class HiddenState:
    layer_index: int
    state_vector: torch.Tensor
    timestamp: float

@dataclass
class TextBlock:
    content: str
    token_count: int
    block_index: int

@dataclass
class NoveltyScore:
    score: float
    prediction_errors: List[float]
    analysis: str
    is_novel: bool

@dataclass
class PromptTemplate:
    """提示词模板"""
    role_name: str
    system_prompt: str
    task_context: str
    collaboration_context: str
    thinking_vector_context: str
```

### 4.3 集成要求

#### 4.3.1 NagaAgent API集成
- **复用现有LLM调用接口**: 使用`system.conversation_core.NagaConversation.get_response()`
- **集成配置系统**: 使用`system.config.config.api`的API配置
- **统一异步架构**: 保持与现有系统的异步调用一致性
- **错误处理机制**: 复用现有的API异常处理和重试机制

#### 4.3.2 系统集成
- 与现有NagaAgent系统无缝集成
- 复用现有的MCP服务管理能力
- 支持现有的配置热更新机制
- 独立部署Qwen2.5-VL模型服务

#### 4.3.3 API调用流程
1. **初始化阶段**: 从NagaAgent获取API客户端实例
2. **角色生成**: 调用大模型API生成角色信息
3. **提示词生成**: 为每个角色生成专用system prompt
4. **权限分配**: 基于角色信息构建协作权限图

### 4.4 系统提示词设计

#### 4.4.1 Distributor角色生成提示词
**功能**: 指导大模型根据任务生成合适的角色
**输出格式**: JSON格式的角色列表
**关键要素**: 
- 任务领域分析
- 角色职责划分
- 技能要求定义
- 优先级排序

#### 4.4.2 角色专用System Prompt
**功能**: 为每个生成的角色创建专用的行为指导
**包含要素**:
- 角色身份和职责
- 与其他角色的协作关系
- 当前任务上下文
- 思维向量约束
- 输出格式要求

#### 4.4.3 协作权限说明
**功能**: 在角色prompt中说明其连接权限
**内容包括**:
- 可直接沟通的角色列表
- 需要通过中介沟通的角色
- 禁止直接沟通的角色
- 协作流程说明

## 5. 性能要求

### 5.1 响应性能
- 角色生成：< 5秒
- 信号链路构建：< 3秒
- 单轮自博弈：< 30秒
- Philoss创新性评估：< 10秒
- Qwen2.5-VL模型推理：< 5秒/100tokens

### 5.2 可扩展性
- 支持动态添加新角色类型
- 支持自定义评估维度
- 支持领域特定的协作规则
- 支持不同规模的本地模型部署
- 支持Philoss MLP层的自定义架构

### 5.3 可靠性
- 异常恢复机制
- 数据一致性保证
- 状态持久化
- 操作日志记录

## 6. 测试要求

### 6.1 单元测试
- 每个核心模块的功能测试
- 边界条件测试
- 异常情况处理测试

### 6.2 集成测试
- 模块间协作测试
- 端到端流程测试
- 性能基准测试

### 6.3 场景测试
- 游戏开发场景测试
- 学术研究场景测试
- 产品设计场景测试

## 7. 部署和运维

### 7.1 部署要求
- 容器化部署支持
- 配置文件管理
- 日志收集和分析
- 监控指标定义

### 7.2 维护要求
- 版本管理
- 数据备份恢复
- 性能监控
- 用户行为分析

## 8. 文档要求

### 8.1 开发文档
- API接口文档
- 架构设计文档
- 数据库设计文档
- 部署运维文档

### 8.2 用户文档
- 使用指南
- 最佳实践
- 故障排查
- FAQ

---

本需求文档将指导NagaAgent Game多智能体博弈系统的设计和实现，专注于通过结构化协作和基于Philoss的创新性评估来解决LLM在多智能体协作中的信息差和博弈干扰问题。系统将与NagaAgent的现有记忆模块协同工作，专门负责博弈过程的优化。 
 
 
 
 