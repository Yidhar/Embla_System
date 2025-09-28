# NagaAgent Game - 多智能体博弈系统

## 🎯 项目概述

NagaAgent Game 是一个专注于博弈机制的多智能体系统，通过结构化协作和基于Philoss的创新性评估来解决LLM在多智能体协作中的信息差和博弈干扰问题。

## 🏗️ 系统架构

```
NagaAgent Game 多智能体博弈系统
├── 核心模块1: 交互图生成器 (Interaction Graph Generator) ✅
│   ├── 角色生成器 (RoleGenerator)
│   ├── 信号路由器 (SignalRouter) 
│   └── 动态分发器 (DynamicDispatcher)
├── 核心模块2: 模型自博弈模块 (Self-Game Module) 🔄
│   ├── Actor组件 (生成)
│   ├── Criticizer组件 (批判)
│   └── Checker组件 (基于Philoss创新性评估)
└── 配套系统
    ├── 数据模型定义 ✅
    ├── 配置管理系统 ✅
    └── 工具函数 🔄
```

## 📦 已完成模块

### 1. 数据模型系统 (✅ 完成)
- **位置**: `game/core/models/`
- **核心类**: Agent, InteractionGraph, GameResult, HiddenState, TextBlock, NoveltyScore
- **功能**: 定义了完整的数据结构和类型系统

### 2. 配置管理系统 (✅ 完成)  
- **位置**: `game/core/models/config.py`
- **功能**: 
  - Philoss模型配置 (Qwen2.5-VL 7B)
  - 自博弈参数配置
  - 交互图设置
  - 领域特定配置模板

### 3. 交互图生成器 (✅ 完成)
- **位置**: `game/core/interaction_graph/`

#### 3.1 角色生成器 (RoleGenerator) 
- **集成Distributor**: 通过大模型API动态生成功能性角色
- **集成Prompt Generator**: 为每个角色生成专用system prompt  
- **复用NagaAgent API**: 与主系统统一的LLM调用接口
- **智能角色生成**: 基于任务复杂度自动调整角色数量和类型
- **结构化提取**: JSON格式的角色信息解析和验证
- **思维向量管理**: 自动生成任务一致性约束

#### 3.2 信号路由器 (SignalRouter)
- 构建智能体间的信息传输规则
- 支持直接通信和中介通信
- 防止跨角色职责的无效沟通
- 可视化交互图生成

#### 3.3 动态分发器 (DynamicDispatcher) 
- 智能体任务完成后的动态传输决策
- 基于技能匹配、角色兼容性的目标选择
- 迭代次数限制和强制交接机制
- 协作历史和工作负载评估

## 🔄 开发中模块

### 模型自博弈模块 (🔄 开发中)
- **Actor组件**: 功能生成组件
- **Criticizer组件**: 成果批判与优化建议
- **Checker组件**: 基于Philoss的创新性评估

## 🚀 核心特性

### 1. 完整的智能角色生成流程  
```python
# 完整的四步骤角色生成
role_generator = RoleGenerator(config, naga_conversation)
agents = await role_generator.generate_agents(task, expected_count_range=(3, 6))

# 手动控制各个步骤
distributor = Distributor(config, naga_conversation)
roles = await distributor.generate_roles(task, (3, 6))  # 步骤1：生成角色
permissions = await distributor.assign_collaboration_permissions(roles)  # 步骤2：分配权限

prompt_generator = PromptGenerator(config, naga_conversation)  
prompts = await prompt_generator._generate_all_role_prompts(roles, task, permissions)  # 步骤3：生成prompts

# 为角色生成专用system prompt
prompt_generator = PromptGenerator(config)
role_prompts = await role_generator.generate_role_prompts(agents, interaction_graph, task)
```

### 2. 结构化协作路径
```python
# 构建智能体交互图
signal_router = SignalRouter(config)  
interaction_graph = await signal_router.build_interaction_graph(agents, task)
```

### 3. 动态消息分发
```python
# 智能选择下一个协作智能体
dispatcher = DynamicDispatcher(config)
decisions = await dispatcher.dispatch_message(agent_id, output, interaction_graph, task)
```

### 4. Philoss创新性评估
```python
# 基于预测误差评估创新性
philoss_checker = PhilossChecker(config)
novelty_score = await philoss_checker.evaluate_novelty(text_output)
```

## 📋 使用示例

### 基本使用流程

```python
from game import NagaGameSystem, Task

# 1. 创建任务
task = Task(
    task_id="game_dev_001",
    description="设计一款创新的角色扮演游戏",
    domain="游戏开发",
    requirements=["创新玩法", "角色系统", "战斗机制"]
)

# 2. 初始化博弈系统
game_system = NagaGameSystem()

# 3. 执行自博弈
result = await game_system.execute_self_game(task, max_iterations=10)

# 4. 查看结果
print(f"最终共识: {result.final_consensus}")
print(f"创新性得分: {result.novel_score.score}")
print(f"整体质量: {result.get_overall_quality()}")
```

### 领域配置

```python
from game.core.models.config import get_domain_config

# 获取游戏开发领域的配置
config = get_domain_config("游戏开发")

# 自定义配置
config.interaction_graph.max_agents = 6
config.self_game.max_iterations = 15
```

## 🛠️ 技术栈

- **Python**: 3.10+
- **深度学习**: PyTorch (MLP层实现)
- **本地模型**: Qwen2.5-VL 7B (Philoss评估)  
- **异步处理**: AsyncIO
- **配置管理**: Pydantic数据验证
- **集成**: 与现有NagaAgent系统无缝集成

## 📁 项目结构

```
game/
├── __init__.py                 # 包初始化
├── README.md                   # 项目说明  
├── REQUIREMENTS.md             # 详细需求文档
├── core/                       # 核心模块
│   ├── models/                 # 数据模型 ✅
│   │   ├── data_models.py      # 核心数据结构
│   │   └── config.py           # 配置管理
│   ├── interaction_graph/      # 交互图生成器 ✅  
│   │   ├── role_generator.py   # 角色生成
│   │   ├── signal_router.py    # 信号路由
│   │   └── dynamic_dispatcher.py # 动态分发
│   └── self_game/              # 自博弈模块 🔄
│       ├── actor.py            # Actor组件
│       ├── criticizer.py       # Criticizer组件
│       ├── checker/            # Checker组件目录
│       └── game_engine.py      # 博弈引擎
├── utils/                      # 工具函数 🔄
├── tests/                      # 测试用例 📋
└── examples/                   # 使用示例 📋
```

## 🎮 支持的领域

- **游戏开发**: 产品经理、程序员、美工、测试人员
- **学术研究**: 研究员、数据分析师、文献评审员  
- **产品设计**: 产品经理、设计师、市场分析师

## 📊 性能指标

- **角色生成**: < 5秒
- **信号链路构建**: < 3秒  
- **单轮自博弈**: < 30秒
- **Philoss创新性评估**: < 10秒
- **Qwen2.5-VL推理**: < 5秒/100tokens

## 🔮 下一步计划

1. **完成自博弈模块** (🔄 进行中)
   - Actor组件实现
   - Criticizer组件实现  
   - Philoss Checker组件实现
   
2. **集成测试** 
   - 端到端流程测试
   - 性能基准测试
   - 场景化测试

3. **示例和文档**
   - 游戏开发示例
   - 学术研究示例
   - API使用指南

## 💡 创新点

1. **结构化协作**: 通过信号路由避免跨角色无效沟通
2. **动态传输决策**: 基于任务输出和技能匹配的智能分发
3. **Philoss创新性评估**: 基于预测误差的客观创新性量化
4. **迭代控制**: 防止思维盲区的强制交接机制
5. **思维向量**: 保持任务一致性的动态上下文管理

---

**Status**: 🔄 Active Development  
**Version**: 1.0.0-dev  
**Last Updated**: 2024-12-XX

此项目专门负责博弈过程优化，与NagaAgent的现有记忆模块协同工作。 
 
 
 
 
 
 