#!/usr/bin/env python3
"""
NagaAgent Game 基本使用示例

展示如何使用新的动态角色生成系统来创建智能体并构建交互图
"""

import asyncio
import logging
from typing import List

# 导入核心模块
from game.core.models.data_models import Task, Agent
from game.core.models.config import GameConfig
from game.core.interaction_graph import RoleGenerator, SignalRouter, DynamicDispatcher
from game.core.interaction_graph import Distributor, PromptGenerator

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def example_complete_role_generation():
    """示例1: 完整的角色生成流程"""
    print("=== 示例1: 完整的角色生成流程 ===")
    
    # 1. 创建任务
    task = Task(
        task_id="game_dev_001",
        description="设计一个创新的多人在线卡牌游戏",
        domain="游戏开发",
        requirements=[
            "支持4-8人同时游戏",
            "包含独特的卡牌机制",
            "具备社交功能",
            "支持移动端和PC端"
        ],
        constraints=[
            "开发周期6个月",
            "预算有限",
            "需要快速迭代"
        ],
        max_iterations=10
    )
    
    # 2. 初始化配置
    config = GameConfig()
    
    # 3. 创建角色生成器（集成完整流程）
    role_generator = RoleGenerator(config)
    
    # 4. 生成智能体（四步骤自动化）
    try:
        agents = await role_generator.generate_agents(task, expected_count_range=(4, 6))
        
        print(f"✅ 成功生成 {len(agents)} 个智能体:")
        for i, agent in enumerate(agents, 1):
            print(f"  {i}. {agent.name} ({agent.role})")
            print(f"     职责: {', '.join(agent.responsibilities[:2])}...")
            print(f"     技能: {', '.join(agent.skills[:3])}...")
            print(f"     连接权限: {len(agent.connection_permissions)}个角色")
            print(f"     System Prompt长度: {len(agent.system_prompt)}字符")
            print()
            
        return agents
        
    except Exception as e:
        print(f"❌ 角色生成失败: {e}")
        return []


async def example_step_by_step_generation():
    """示例2: 分步骤的角色生成过程"""
    print("\n=== 示例2: 分步骤的角色生成过程 ===")
    
    # 创建任务
    task = Task(
        task_id="research_001",
        description="研究大语言模型在教育领域的应用",
        domain="学术研究",
        requirements=[
            "文献调研",
            "实验设计",
            "数据分析",
            "论文撰写"
        ],
        max_iterations=8
    )
    
    config = GameConfig()
    
    try:
        # 步骤1: 使用Distributor生成角色信息
        print("📝 步骤1: 生成角色信息...")
        distributor = Distributor(config)
        roles_data = await distributor.generate_roles(task, (3, 5))
        print(f"   生成了 {len(roles_data)} 个角色")
        
        # 步骤2: 分配协作权限
        print("🔗 步骤2: 分配协作权限...")
        permissions = await distributor.assign_collaboration_permissions(roles_data)
        print(f"   为 {len(permissions)} 个角色分配了权限")
        
        # 步骤3: 生成专用Prompt
        print("🎭 步骤3: 生成专用Prompts...")
        prompt_generator = PromptGenerator(config)
        
        # 这里需要手动调用内部方法（仅用于演示）
        role_prompts = {}
        for role in roles_data:
            try:
                prompt = await prompt_generator.generate_role_prompt(
                    role, task, permissions, roles_data
                )
                role_prompts[role.name] = prompt
                print(f"   ✅ {role.name}: {len(prompt)}字符")
            except Exception as e:
                print(f"   ❌ {role.name}: 生成失败 - {e}")
                
        print(f"✅ 分步骤生成完成!")
        return roles_data, permissions, role_prompts
        
    except Exception as e:
        print(f"❌ 分步骤生成失败: {e}")
        return [], {}, {}


async def example_interaction_graph():
    """示例3: 构建完整的交互图"""
    print("\n=== 示例3: 构建完整的交互图 ===")
    
    # 使用示例1生成的智能体
    task = Task(
        task_id="product_design_001",
        description="设计一个面向老年人的智能健康监测应用",
        domain="产品设计",
        requirements=["用户友好", "数据准确", "隐私保护"],
        max_iterations=12
    )
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    try:
        # 生成智能体
        agents = await role_generator.generate_agents(task)
        
        # 构建信号路由
        signal_router = SignalRouter(config)
        interaction_graph = await signal_router.build_interaction_graph(agents, task)
        
        # 可视化交互图
        visualization = signal_router.visualize_interaction_graph(interaction_graph)
        print(visualization)
        
        # 获取通信矩阵
        comm_matrix = signal_router.get_communication_matrix(interaction_graph)
        
        print("\n📊 通信矩阵概览:")
        for agent_id, connections in comm_matrix.items():
            agent = interaction_graph.get_agent_by_id(agent_id)
            if agent:
                direct_count = sum(1 for conn_type in connections.values() if conn_type == "direct")
                print(f"  {agent.name}: {direct_count}个直接连接")
        
        return interaction_graph
        
    except Exception as e:
        print(f"❌ 交互图构建失败: {e}")
        return None


async def example_dynamic_dispatch():
    """示例4: 动态分发器使用"""
    print("\n=== 示例4: 动态分发器演示 ===")
    
    # 假设已有交互图和任务结果
    task = Task(
        task_id="demo_task",
        description="演示动态分发功能",
        domain="软件开发"
    )
    
    config = GameConfig()
    dispatcher = DynamicDispatcher(config)
    
    # 模拟任务输出
    task_output = {
        "type": "design_document",
        "content": "完成了系统架构设计",
        "next_phase": "implementation"
    }
    
    print("🚀 模拟动态分发过程...")
    print(f"   任务输出: {task_output['content']}")
    print("   分发决策将基于输出类型和下阶段需求进行...")
    
    # 获取分发统计信息
    stats = dispatcher.get_dispatch_statistics()
    print(f"📊 分发统计: {stats}")
    
    return True


async def example_role_prompt_regeneration():
    """示例5: 角色Prompt重新生成"""
    print("\n=== 示例5: 角色Prompt重新生成 ===")
    
    task = Task(
        task_id="regen_test",
        description="测试Prompt重新生成功能",
        domain="测试"
    )
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    try:
        # 生成初始智能体
        agents = await role_generator.generate_agents(task, (2, 3))
        
        if agents:
            # 选择第一个智能体重新生成Prompt
            target_agent = agents[0]
            print(f"🔄 为'{target_agent.name}'重新生成Prompt...")
            
            # 模拟协作权限
            collaboration_permissions = {
                agent.name: agent.connection_permissions for agent in agents
            }
            
            new_prompt = await role_generator.regenerate_role_prompt(
                target_agent, task, collaboration_permissions, agents
            )
            
            print(f"✅ 新Prompt生成成功，长度: {len(new_prompt)}字符")
            print(f"📝 新Prompt预览: {new_prompt[:200]}...")
            
        return True
        
    except Exception as e:
        print(f"❌ Prompt重新生成失败: {e}")
        return False


async def show_statistics():
    """显示系统统计信息"""
    print("\n=== 系统统计信息 ===")
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    # 获取生成统计
    stats = role_generator.get_generation_statistics()
    
    print("📊 角色生成器统计:")
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    # 显示配置信息
    print(f"\n⚙️ 系统配置:")
    print(f"   最小智能体数量: {config.interaction_graph.min_agents}")
    print(f"   最大智能体数量: {config.interaction_graph.max_agents}")
    print(f"   最大迭代次数: {config.self_game.max_iterations}")
    print(f"   启用动态路由: {config.interaction_graph.enable_dynamic_routing}")


async def main():
    """主函数 - 运行所有示例"""
    print("🎮 NagaAgent Game - 动态角色生成系统演示")
    print("=" * 60)
    
    try:
        # 运行所有示例
        await example_complete_role_generation()
        await example_step_by_step_generation()
        await example_interaction_graph()
        await example_dynamic_dispatch()
        await example_role_prompt_regeneration()
        await show_statistics()
        
        print("\n🎉 所有示例运行完成!")
        
    except Exception as e:
        logger.error(f"示例运行失败: {e}")
        print(f"❌ 示例运行出错: {e}")


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main()) 
 
"""
NagaAgent Game 基本使用示例

展示如何使用新的动态角色生成系统来创建智能体并构建交互图
"""

import asyncio
import logging
from typing import List

# 导入核心模块
from game.core.models.data_models import Task, Agent
from game.core.models.config import GameConfig
from game.core.interaction_graph import RoleGenerator, SignalRouter, DynamicDispatcher
from game.core.interaction_graph import Distributor, PromptGenerator

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def example_complete_role_generation():
    """示例1: 完整的角色生成流程"""
    print("=== 示例1: 完整的角色生成流程 ===")
    
    # 1. 创建任务
    task = Task(
        task_id="game_dev_001",
        description="设计一个创新的多人在线卡牌游戏",
        domain="游戏开发",
        requirements=[
            "支持4-8人同时游戏",
            "包含独特的卡牌机制",
            "具备社交功能",
            "支持移动端和PC端"
        ],
        constraints=[
            "开发周期6个月",
            "预算有限",
            "需要快速迭代"
        ],
        max_iterations=10
    )
    
    # 2. 初始化配置
    config = GameConfig()
    
    # 3. 创建角色生成器（集成完整流程）
    role_generator = RoleGenerator(config)
    
    # 4. 生成智能体（四步骤自动化）
    try:
        agents = await role_generator.generate_agents(task, expected_count_range=(4, 6))
        
        print(f"✅ 成功生成 {len(agents)} 个智能体:")
        for i, agent in enumerate(agents, 1):
            print(f"  {i}. {agent.name} ({agent.role})")
            print(f"     职责: {', '.join(agent.responsibilities[:2])}...")
            print(f"     技能: {', '.join(agent.skills[:3])}...")
            print(f"     连接权限: {len(agent.connection_permissions)}个角色")
            print(f"     System Prompt长度: {len(agent.system_prompt)}字符")
            print()
            
        return agents
        
    except Exception as e:
        print(f"❌ 角色生成失败: {e}")
        return []


async def example_step_by_step_generation():
    """示例2: 分步骤的角色生成过程"""
    print("\n=== 示例2: 分步骤的角色生成过程 ===")
    
    # 创建任务
    task = Task(
        task_id="research_001",
        description="研究大语言模型在教育领域的应用",
        domain="学术研究",
        requirements=[
            "文献调研",
            "实验设计",
            "数据分析",
            "论文撰写"
        ],
        max_iterations=8
    )
    
    config = GameConfig()
    
    try:
        # 步骤1: 使用Distributor生成角色信息
        print("📝 步骤1: 生成角色信息...")
        distributor = Distributor(config)
        roles_data = await distributor.generate_roles(task, (3, 5))
        print(f"   生成了 {len(roles_data)} 个角色")
        
        # 步骤2: 分配协作权限
        print("🔗 步骤2: 分配协作权限...")
        permissions = await distributor.assign_collaboration_permissions(roles_data)
        print(f"   为 {len(permissions)} 个角色分配了权限")
        
        # 步骤3: 生成专用Prompt
        print("🎭 步骤3: 生成专用Prompts...")
        prompt_generator = PromptGenerator(config)
        
        # 这里需要手动调用内部方法（仅用于演示）
        role_prompts = {}
        for role in roles_data:
            try:
                prompt = await prompt_generator.generate_role_prompt(
                    role, task, permissions, roles_data
                )
                role_prompts[role.name] = prompt
                print(f"   ✅ {role.name}: {len(prompt)}字符")
            except Exception as e:
                print(f"   ❌ {role.name}: 生成失败 - {e}")
                
        print(f"✅ 分步骤生成完成!")
        return roles_data, permissions, role_prompts
        
    except Exception as e:
        print(f"❌ 分步骤生成失败: {e}")
        return [], {}, {}


async def example_interaction_graph():
    """示例3: 构建完整的交互图"""
    print("\n=== 示例3: 构建完整的交互图 ===")
    
    # 使用示例1生成的智能体
    task = Task(
        task_id="product_design_001",
        description="设计一个面向老年人的智能健康监测应用",
        domain="产品设计",
        requirements=["用户友好", "数据准确", "隐私保护"],
        max_iterations=12
    )
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    try:
        # 生成智能体
        agents = await role_generator.generate_agents(task)
        
        # 构建信号路由
        signal_router = SignalRouter(config)
        interaction_graph = await signal_router.build_interaction_graph(agents, task)
        
        # 可视化交互图
        visualization = signal_router.visualize_interaction_graph(interaction_graph)
        print(visualization)
        
        # 获取通信矩阵
        comm_matrix = signal_router.get_communication_matrix(interaction_graph)
        
        print("\n📊 通信矩阵概览:")
        for agent_id, connections in comm_matrix.items():
            agent = interaction_graph.get_agent_by_id(agent_id)
            if agent:
                direct_count = sum(1 for conn_type in connections.values() if conn_type == "direct")
                print(f"  {agent.name}: {direct_count}个直接连接")
        
        return interaction_graph
        
    except Exception as e:
        print(f"❌ 交互图构建失败: {e}")
        return None


async def example_dynamic_dispatch():
    """示例4: 动态分发器使用"""
    print("\n=== 示例4: 动态分发器演示 ===")
    
    # 假设已有交互图和任务结果
    task = Task(
        task_id="demo_task",
        description="演示动态分发功能",
        domain="软件开发"
    )
    
    config = GameConfig()
    dispatcher = DynamicDispatcher(config)
    
    # 模拟任务输出
    task_output = {
        "type": "design_document",
        "content": "完成了系统架构设计",
        "next_phase": "implementation"
    }
    
    print("🚀 模拟动态分发过程...")
    print(f"   任务输出: {task_output['content']}")
    print("   分发决策将基于输出类型和下阶段需求进行...")
    
    # 获取分发统计信息
    stats = dispatcher.get_dispatch_statistics()
    print(f"📊 分发统计: {stats}")
    
    return True


async def example_role_prompt_regeneration():
    """示例5: 角色Prompt重新生成"""
    print("\n=== 示例5: 角色Prompt重新生成 ===")
    
    task = Task(
        task_id="regen_test",
        description="测试Prompt重新生成功能",
        domain="测试"
    )
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    try:
        # 生成初始智能体
        agents = await role_generator.generate_agents(task, (2, 3))
        
        if agents:
            # 选择第一个智能体重新生成Prompt
            target_agent = agents[0]
            print(f"🔄 为'{target_agent.name}'重新生成Prompt...")
            
            # 模拟协作权限
            collaboration_permissions = {
                agent.name: agent.connection_permissions for agent in agents
            }
            
            new_prompt = await role_generator.regenerate_role_prompt(
                target_agent, task, collaboration_permissions, agents
            )
            
            print(f"✅ 新Prompt生成成功，长度: {len(new_prompt)}字符")
            print(f"📝 新Prompt预览: {new_prompt[:200]}...")
            
        return True
        
    except Exception as e:
        print(f"❌ Prompt重新生成失败: {e}")
        return False


async def show_statistics():
    """显示系统统计信息"""
    print("\n=== 系统统计信息 ===")
    
    config = GameConfig()
    role_generator = RoleGenerator(config)
    
    # 获取生成统计
    stats = role_generator.get_generation_statistics()
    
    print("📊 角色生成器统计:")
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    # 显示配置信息
    print(f"\n⚙️ 系统配置:")
    print(f"   最小智能体数量: {config.interaction_graph.min_agents}")
    print(f"   最大智能体数量: {config.interaction_graph.max_agents}")
    print(f"   最大迭代次数: {config.self_game.max_iterations}")
    print(f"   启用动态路由: {config.interaction_graph.enable_dynamic_routing}")


async def main():
    """主函数 - 运行所有示例"""
    print("🎮 NagaAgent Game - 动态角色生成系统演示")
    print("=" * 60)
    
    try:
        # 运行所有示例
        await example_complete_role_generation()
        await example_step_by_step_generation()
        await example_interaction_graph()
        await example_dynamic_dispatch()
        await example_role_prompt_regeneration()
        await show_statistics()
        
        print("\n🎉 所有示例运行完成!")
        
    except Exception as e:
        logger.error(f"示例运行失败: {e}")
        print(f"❌ 示例运行出错: {e}")


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main()) 
 
 
 
 
 
 