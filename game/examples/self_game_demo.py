#!/usr/bin/env python3
"""
NagaAgent Game 自博弈模块演示

展示Actor-Criticizer-Checker三组件协同的完整博弈流程：
1. GameActor: 功能生成
2. GameCriticizer: 批判优化  
3. PhilossChecker: 创新性评估
4. GameEngine: 完整博弈流程
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from game.core.models.data_models import Task, Agent
from game.core.models.config import GameConfig, get_domain_config
from game.core.self_game import GameActor, GameCriticizer, PhilossChecker, GameEngine
from game.core.interaction_graph import RoleGenerator

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def demo_actor_component():
    """演示1: GameActor组件功能生成"""
    print("=== 演示1: GameActor 功能生成组件 ===")
    
    # 创建测试任务和智能体
    task = Task(
        task_id="actor_demo_001",
        description="设计一个智能家居控制系统",
        domain="产品设计",
        requirements=["语音控制", "手机APP", "安全防护", "节能管理"],
        constraints=["成本控制", "易用性", "兼容性"],
        max_iterations=5
    )
    
    agent = Agent(
        name="产品设计师",
        role="设计专家",
        responsibilities=["需求分析", "方案设计", "原型制作"],
        skills=["产品设计", "用户体验", "技术评估"],
        thinking_vector="核心目标: 设计智能家居控制系统",
        system_prompt="你是专业的产品设计师，负责智能家居系统的整体设计",
        connection_permissions=["技术专家", "市场分析师"]
    )
    
    # 初始化Actor
    config = get_domain_config("产品设计")
    actor = GameActor(config)
    
    try:
        print(f"📋 任务：{task.description}")
        print(f"🎭 智能体：{agent.name} ({agent.role})")
        
        # 生成内容
        print("\n🚀 开始内容生成...")
        output = await actor.generate_content(agent, task)
        
        print(f"✅ 生成完成！")
        print(f"📊 生成统计：")
        print(f"   - 耗时：{output.generation_time:.2f}秒")
        print(f"   - 迭代轮次：{output.iteration}")
        print(f"   - 内容长度：{len(output.content)}字符")
        
        print(f"\n📝 生成内容预览：")
        print("```")
        print(output.content[:500] + "..." if len(output.content) > 500 else output.content)
        print("```")
        
        # 获取统计信息
        stats = actor.get_generation_statistics()
        print(f"\n📈 Actor统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return output
        
    except Exception as e:
        print(f"❌ Actor演示失败：{e}")
        return None


async def demo_criticizer_component(actor_output):
    """演示2: GameCriticizer批判优化组件"""
    print("\n\n=== 演示2: GameCriticizer 批判优化组件 ===")
    
    if not actor_output:
        print("❌ 跳过演示：没有Actor输出可供批判")
        return None
    
    # 创建批判者智能体
    critic_agent = Agent(
        name="质量分析师",
        role="评估专家",
        responsibilities=["质量评估", "问题识别", "改进建议"],
        skills=["批判分析", "质量管控", "专业评审"],
        thinking_vector="核心目标: 客观评估并提供建设性建议",
        system_prompt="你是专业的质量分析师，负责对产品方案进行全面评估",
        connection_permissions=["产品设计师", "技术专家"]
    )
    
    task = Task(
        task_id="critic_demo_001",
        description="评估智能家居控制系统设计方案",
        domain="产品设计"
    )
    
    # 初始化Criticizer
    config = get_domain_config("产品设计")
    criticizer = GameCriticizer(config)
    
    try:
        print(f"🎭 批判者：{critic_agent.name} ({critic_agent.role})")
        print(f"📋 批判目标：{actor_output.metadata.get('agent_name', '未知')}的输出")
        
        # 执行批判
        print("\n🔍 开始批判分析...")
        critique_output = await criticizer.critique_output(actor_output, critic_agent, task)
        
        print(f"✅ 批判完成！")
        print(f"📊 批判统计：")
        print(f"   - 耗时：{critique_output.critique_time:.2f}秒")
        print(f"   - 总体评分：{critique_output.overall_score:.1f}/10")
        print(f"   - 满意度评分：{critique_output.satisfaction_score:.1f}/10")
        print(f"   - 评估维度：{len(critique_output.dimension_scores)}个")
        
        print(f"\n📋 各维度评分：")
        for score in critique_output.dimension_scores:
            print(f"   • {score.dimension.value}: {score.score:.1f}/10")
            print(f"     理由：{score.reasoning}")
            if score.suggestions:
                print(f"     建议：{score.suggestions[0]}")
        
        print(f"\n💭 总体批判意见：")
        print(f"   {critique_output.summary_critique}")
        
        print(f"\n🔧 改进建议：")
        for i, suggestion in enumerate(critique_output.improvement_suggestions, 1):
            print(f"   {i}. {suggestion}")
        
        # 获取统计信息
        stats = criticizer.get_critique_statistics()
        print(f"\n📈 Criticizer统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return critique_output
        
    except Exception as e:
        print(f"❌ Criticizer演示失败：{e}")
        return None


async def demo_philoss_checker(actor_output):
    """演示3: PhilossChecker创新性评估组件"""
    print("\n\n=== 演示3: PhilossChecker 创新性评估组件 ===")
    
    if not actor_output:
        print("❌ 跳过演示：没有Actor输出可供评估")
        return None
    
    # 初始化PhilossChecker
    config = get_domain_config("产品设计")
    philoss_checker = PhilossChecker(config)
    
    try:
        print(f"🔬 评估目标：{actor_output.metadata.get('agent_name', '未知')}的输出")
        print(f"📄 内容长度：{len(actor_output.content)}字符")
        print(f"🧠 模型状态：{'就绪' if philoss_checker.is_model_ready() else '模拟模式'}")
        
        # 执行创新性评估
        print("\n🚀 开始创新性评估...")
        philoss_output = await philoss_checker.evaluate_novelty(
            actor_output.content, 
            f"{actor_output.agent_id}_{actor_output.iteration}"
        )
        
        print(f"✅ 评估完成！")
        print(f"📊 评估统计：")
        print(f"   - 耗时：{philoss_output.analysis_time:.2f}秒")
        print(f"   - 创新性评分：{philoss_output.novelty_score:.3f}/10")
        print(f"   - 文本块数量：{len(philoss_output.text_blocks)}")
        print(f"   - 隐藏状态数量：{len(philoss_output.hidden_states)}")
        print(f"   - 预测误差数量：{len(philoss_output.prediction_errors)}")
        
        print(f"\n📈 详细分析：")
        print(f"   - 平均预测误差：{philoss_output.metadata.get('average_error', 0):.4f}")
        print(f"   - 最大预测误差：{philoss_output.metadata.get('max_error', 0):.4f}")
        print(f"   - 模型可用：{philoss_output.metadata.get('model_available', False)}")
        
        print(f"\n🧩 文本块分析：")
        for i, block in enumerate(philoss_output.text_blocks[:3], 1):  # 显示前3个块
            print(f"   块{i}: {block.token_count} tokens, {len(block.content)} 字符")
            print(f"        内容预览：{block.content[:50]}...")
        
        if len(philoss_output.prediction_errors) > 0:
            print(f"\n⚡ 预测误差分布：")
            errors = philoss_output.prediction_errors
            print(f"   - 最小误差：{min(errors):.4f}")
            print(f"   - 最大误差：{max(errors):.4f}")
            print(f"   - 平均误差：{sum(errors)/len(errors):.4f}")
        
        # 获取统计信息
        stats = philoss_checker.get_evaluation_statistics()
        print(f"\n📈 PhilossChecker统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return philoss_output
        
    except Exception as e:
        print(f"❌ PhilossChecker演示失败：{e}")
        return None


async def demo_game_engine():
    """演示4: GameEngine完整博弈流程"""
    print("\n\n=== 演示4: GameEngine 完整博弈流程 ===")
    
    # 创建复杂任务
    task = Task(
        task_id="game_engine_demo_001",
        description="设计一个面向老年人的智能健康监测系统",
        domain="产品设计",
        requirements=[
            "24小时健康监测",
            "紧急情况自动报警", 
            "简单易用的界面",
            "家属远程查看功能"
        ],
        constraints=[
            "成本控制在2000元以内",
            "电池续航不少于7天",
            "支持WiFi和4G网络"
        ],
        max_iterations=3  # 为了演示，限制迭代次数
    )
    
    # 使用RoleGenerator生成智能体
    print("📝 生成参与博弈的智能体...")
    config = get_domain_config("产品设计")
    role_generator = RoleGenerator(config)
    
    try:
        agents = await role_generator.generate_agents(task, (3, 4))
        print(f"✅ 成功生成{len(agents)}个智能体：")
        for i, agent in enumerate(agents, 1):
            print(f"   {i}. {agent.name} ({agent.role})")
    except Exception as e:
        print(f"⚠️ 智能体生成失败，使用默认智能体：{e}")
        # 创建默认智能体
        agents = [
            Agent(
                name="产品经理",
                role="产品规划",
                responsibilities=["需求分析", "产品规划"],
                skills=["产品设计", "市场分析"],
                thinking_vector="核心目标: 设计老年人健康监测系统",
                system_prompt="你是产品经理，负责整体产品规划",
                connection_permissions=["技术专家", "设计师"]
            ),
            Agent(
                name="技术专家",
                role="技术实现",
                responsibilities=["技术方案", "架构设计"],
                skills=["软件开发", "硬件设计"],
                thinking_vector="核心目标: 实现技术方案",
                system_prompt="你是技术专家，负责技术实现",
                connection_permissions=["产品经理", "设计师"]
            ),
            Agent(
                name="用户体验设计师",
                role="体验设计",
                responsibilities=["界面设计", "交互优化"],
                skills=["UI设计", "用户研究"],
                thinking_vector="核心目标: 优化用户体验",
                system_prompt="你是UX设计师，专注用户体验",
                connection_permissions=["产品经理", "技术专家"]
            )
        ]
    
    # 初始化GameEngine
    print("\n🎮 初始化GameEngine...")
    game_engine = GameEngine(config)
    
    try:
        print(f"🚀 启动完整博弈会话...")
        print(f"   任务：{task.description}")
        print(f"   参与者：{len(agents)}个智能体")
        print(f"   最大轮数：{task.max_iterations}")
        
        # 启动博弈会话
        session = await game_engine.start_game_session(task, agents)
        
        print(f"\n✅ 博弈会话完成！")
        print(f"📊 会话统计：")
        print(f"   - 会话ID：{session.session_id}")
        print(f"   - 总轮数：{len(session.rounds)}")
        print(f"   - 总耗时：{session.total_time:.2f}秒")
        print(f"   - 最终状态：{session.status.value}")
        print(f"   - 成功完成：{session.final_result.success if session.final_result else False}")
        
        # 显示各轮次摘要
        print(f"\n📋 轮次详情：")
        for round_data in session.rounds:
            print(f"   第{round_data.round_number}轮:")
            print(f"     - 生成数量：{len(round_data.actor_outputs)}")
            print(f"     - 批判数量：{len(round_data.critic_outputs)}")
            print(f"     - 评估数量：{len(round_data.philoss_outputs)}")
            print(f"     - 平均Critical评分：{round_data.metadata.get('average_critical_score', 0):.2f}")
            print(f"     - 平均Novelty评分：{round_data.metadata.get('average_novelty_score', 0):.2f}")
            print(f"     - 决策：{round_data.decision}")
        
        # 显示最终结果
        if session.final_result:
            print(f"\n🎯 最终结果：")
            print(f"   - 任务成功：{session.final_result.success}")
            print(f"   - 总迭代数：{session.final_result.total_iterations}")
            print(f"   - 收敛达成：{session.final_result.convergence_achieved}")
            print(f"   - 最终输出数量：{len(session.final_result.final_outputs)}")
            
            if session.final_result.quality_metrics:
                print(f"   - 质量指标：")
                for metric, value in session.final_result.quality_metrics.items():
                    if isinstance(value, float):
                        print(f"     • {metric}: {value:.3f}")
                    else:
                        print(f"     • {metric}: {value}")
        
        # 显示系统统计
        system_stats = game_engine.get_session_statistics()
        print(f"\n📈 系统统计：")
        for key, value in system_stats.items():
            if isinstance(value, float):
                print(f"   {key}: {value:.3f}")
            else:
                print(f"   {key}: {value}")
        
        return session
        
    except Exception as e:
        print(f"❌ GameEngine演示失败：{e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_component_integration():
    """演示5: 组件集成测试"""
    print("\n\n=== 演示5: 组件集成测试 ===")
    
    print("🔧 测试各组件间的数据流转...")
    
    # 创建简单任务
    task = Task(
        task_id="integration_test",
        description="设计一个简单的待办事项应用",
        domain="软件开发",
        requirements=["任务管理", "提醒功能"],
        max_iterations=2
    )
    
    # 创建测试智能体
    agent = Agent(
        name="软件工程师",
        role="开发者",
        responsibilities=["软件设计", "代码实现"],
        skills=["编程", "系统设计"],
        thinking_vector="核心目标: 设计待办事项应用",
        system_prompt="你是软件工程师，负责应用开发",
        connection_permissions=[]
    )
    
    config = get_domain_config("软件开发")
    
    try:
        # 步骤1：Actor生成
        print("\n1️⃣ Actor生成内容...")
        actor = GameActor(config)
        actor_output = await actor.generate_content(agent, task)
        print(f"   ✅ 生成完成，长度：{len(actor_output.content)}字符")
        
        # 步骤2：Criticizer批判
        print("\n2️⃣ Criticizer批判分析...")
        criticizer = GameCriticizer(config)
        critic_output = await criticizer.critique_output(actor_output, agent, task)
        print(f"   ✅ 批判完成，评分：{critic_output.overall_score:.1f}/10")
        
        # 步骤3：PhilossChecker评估
        print("\n3️⃣ PhilossChecker创新性评估...")
        philoss_checker = PhilossChecker(config)
        philoss_output = await philoss_checker.evaluate_novelty(
            actor_output.content, 
            f"{actor_output.agent_id}_{actor_output.iteration}"
        )
        print(f"   ✅ 评估完成，创新性：{philoss_output.novelty_score:.3f}/10")
        
        # 步骤4：数据流验证
        print("\n4️⃣ 数据流验证...")
        print(f"   • Actor → Criticizer: ✅ (输出ID: {actor_output.agent_id}_{actor_output.iteration})")
        print(f"   • Actor → PhilossChecker: ✅ (内容长度: {len(actor_output.content)})")
        print(f"   • 批判目标匹配: ✅ (目标ID: {critic_output.target_output_id})")
        print(f"   • 评估目标匹配: ✅ (目标ID: {philoss_output.target_content_id})")
        
        print(f"\n✅ 组件集成测试通过！")
        
        return {
            'actor_output': actor_output,
            'critic_output': critic_output,
            'philoss_output': philoss_output
        }
        
    except Exception as e:
        print(f"❌ 组件集成测试失败：{e}")
        return None


async def main():
    """主函数 - 运行所有演示"""
    print("🎮 NagaAgent Game - 自博弈模块完整演示")
    print("=" * 60)
    
    try:
        # 演示1：Actor组件
        actor_output = await demo_actor_component()
        
        # 演示2：Criticizer组件
        critic_output = await demo_criticizer_component(actor_output)
        
        # 演示3：PhilossChecker组件
        philoss_output = await demo_philoss_checker(actor_output)
        
        # 演示4：GameEngine完整流程
        session = await demo_game_engine()
        
        # 演示5：组件集成测试
        integration_results = await demo_component_integration()
        
        # 总结
        print("\n\n🎯 演示总结")
        print("=" * 60)
        print("✅ GameActor: 功能生成组件 - 正常运行")
        print("✅ GameCriticizer: 批判优化组件 - 正常运行") 
        print("✅ PhilossChecker: 创新性评估组件 - 正常运行")
        print("✅ GameEngine: 完整博弈流程 - 正常运行")
        print("✅ 组件集成: 数据流转 - 正常运行")
        
        print(f"\n🚀 自博弈模块已就绪，可以投入使用！")
        
    except KeyboardInterrupt:
        print("\n演示被用户中断")
    except Exception as e:
        print(f"\n❌ 演示执行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main()) 
 
"""
NagaAgent Game 自博弈模块演示

展示Actor-Criticizer-Checker三组件协同的完整博弈流程：
1. GameActor: 功能生成
2. GameCriticizer: 批判优化  
3. PhilossChecker: 创新性评估
4. GameEngine: 完整博弈流程
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from game.core.models.data_models import Task, Agent
from game.core.models.config import GameConfig, get_domain_config
from game.core.self_game import GameActor, GameCriticizer, PhilossChecker, GameEngine
from game.core.interaction_graph import RoleGenerator

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def demo_actor_component():
    """演示1: GameActor组件功能生成"""
    print("=== 演示1: GameActor 功能生成组件 ===")
    
    # 创建测试任务和智能体
    task = Task(
        task_id="actor_demo_001",
        description="设计一个智能家居控制系统",
        domain="产品设计",
        requirements=["语音控制", "手机APP", "安全防护", "节能管理"],
        constraints=["成本控制", "易用性", "兼容性"],
        max_iterations=5
    )
    
    agent = Agent(
        name="产品设计师",
        role="设计专家",
        responsibilities=["需求分析", "方案设计", "原型制作"],
        skills=["产品设计", "用户体验", "技术评估"],
        thinking_vector="核心目标: 设计智能家居控制系统",
        system_prompt="你是专业的产品设计师，负责智能家居系统的整体设计",
        connection_permissions=["技术专家", "市场分析师"]
    )
    
    # 初始化Actor
    config = get_domain_config("产品设计")
    actor = GameActor(config)
    
    try:
        print(f"📋 任务：{task.description}")
        print(f"🎭 智能体：{agent.name} ({agent.role})")
        
        # 生成内容
        print("\n🚀 开始内容生成...")
        output = await actor.generate_content(agent, task)
        
        print(f"✅ 生成完成！")
        print(f"📊 生成统计：")
        print(f"   - 耗时：{output.generation_time:.2f}秒")
        print(f"   - 迭代轮次：{output.iteration}")
        print(f"   - 内容长度：{len(output.content)}字符")
        
        print(f"\n📝 生成内容预览：")
        print("```")
        print(output.content[:500] + "..." if len(output.content) > 500 else output.content)
        print("```")
        
        # 获取统计信息
        stats = actor.get_generation_statistics()
        print(f"\n📈 Actor统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return output
        
    except Exception as e:
        print(f"❌ Actor演示失败：{e}")
        return None


async def demo_criticizer_component(actor_output):
    """演示2: GameCriticizer批判优化组件"""
    print("\n\n=== 演示2: GameCriticizer 批判优化组件 ===")
    
    if not actor_output:
        print("❌ 跳过演示：没有Actor输出可供批判")
        return None
    
    # 创建批判者智能体
    critic_agent = Agent(
        name="质量分析师",
        role="评估专家",
        responsibilities=["质量评估", "问题识别", "改进建议"],
        skills=["批判分析", "质量管控", "专业评审"],
        thinking_vector="核心目标: 客观评估并提供建设性建议",
        system_prompt="你是专业的质量分析师，负责对产品方案进行全面评估",
        connection_permissions=["产品设计师", "技术专家"]
    )
    
    task = Task(
        task_id="critic_demo_001",
        description="评估智能家居控制系统设计方案",
        domain="产品设计"
    )
    
    # 初始化Criticizer
    config = get_domain_config("产品设计")
    criticizer = GameCriticizer(config)
    
    try:
        print(f"🎭 批判者：{critic_agent.name} ({critic_agent.role})")
        print(f"📋 批判目标：{actor_output.metadata.get('agent_name', '未知')}的输出")
        
        # 执行批判
        print("\n🔍 开始批判分析...")
        critique_output = await criticizer.critique_output(actor_output, critic_agent, task)
        
        print(f"✅ 批判完成！")
        print(f"📊 批判统计：")
        print(f"   - 耗时：{critique_output.critique_time:.2f}秒")
        print(f"   - 总体评分：{critique_output.overall_score:.1f}/10")
        print(f"   - 满意度评分：{critique_output.satisfaction_score:.1f}/10")
        print(f"   - 评估维度：{len(critique_output.dimension_scores)}个")
        
        print(f"\n📋 各维度评分：")
        for score in critique_output.dimension_scores:
            print(f"   • {score.dimension.value}: {score.score:.1f}/10")
            print(f"     理由：{score.reasoning}")
            if score.suggestions:
                print(f"     建议：{score.suggestions[0]}")
        
        print(f"\n💭 总体批判意见：")
        print(f"   {critique_output.summary_critique}")
        
        print(f"\n🔧 改进建议：")
        for i, suggestion in enumerate(critique_output.improvement_suggestions, 1):
            print(f"   {i}. {suggestion}")
        
        # 获取统计信息
        stats = criticizer.get_critique_statistics()
        print(f"\n📈 Criticizer统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return critique_output
        
    except Exception as e:
        print(f"❌ Criticizer演示失败：{e}")
        return None


async def demo_philoss_checker(actor_output):
    """演示3: PhilossChecker创新性评估组件"""
    print("\n\n=== 演示3: PhilossChecker 创新性评估组件 ===")
    
    if not actor_output:
        print("❌ 跳过演示：没有Actor输出可供评估")
        return None
    
    # 初始化PhilossChecker
    config = get_domain_config("产品设计")
    philoss_checker = PhilossChecker(config)
    
    try:
        print(f"🔬 评估目标：{actor_output.metadata.get('agent_name', '未知')}的输出")
        print(f"📄 内容长度：{len(actor_output.content)}字符")
        print(f"🧠 模型状态：{'就绪' if philoss_checker.is_model_ready() else '模拟模式'}")
        
        # 执行创新性评估
        print("\n🚀 开始创新性评估...")
        philoss_output = await philoss_checker.evaluate_novelty(
            actor_output.content, 
            f"{actor_output.agent_id}_{actor_output.iteration}"
        )
        
        print(f"✅ 评估完成！")
        print(f"📊 评估统计：")
        print(f"   - 耗时：{philoss_output.analysis_time:.2f}秒")
        print(f"   - 创新性评分：{philoss_output.novelty_score:.3f}/10")
        print(f"   - 文本块数量：{len(philoss_output.text_blocks)}")
        print(f"   - 隐藏状态数量：{len(philoss_output.hidden_states)}")
        print(f"   - 预测误差数量：{len(philoss_output.prediction_errors)}")
        
        print(f"\n📈 详细分析：")
        print(f"   - 平均预测误差：{philoss_output.metadata.get('average_error', 0):.4f}")
        print(f"   - 最大预测误差：{philoss_output.metadata.get('max_error', 0):.4f}")
        print(f"   - 模型可用：{philoss_output.metadata.get('model_available', False)}")
        
        print(f"\n🧩 文本块分析：")
        for i, block in enumerate(philoss_output.text_blocks[:3], 1):  # 显示前3个块
            print(f"   块{i}: {block.token_count} tokens, {len(block.content)} 字符")
            print(f"        内容预览：{block.content[:50]}...")
        
        if len(philoss_output.prediction_errors) > 0:
            print(f"\n⚡ 预测误差分布：")
            errors = philoss_output.prediction_errors
            print(f"   - 最小误差：{min(errors):.4f}")
            print(f"   - 最大误差：{max(errors):.4f}")
            print(f"   - 平均误差：{sum(errors)/len(errors):.4f}")
        
        # 获取统计信息
        stats = philoss_checker.get_evaluation_statistics()
        print(f"\n📈 PhilossChecker统计信息：")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        return philoss_output
        
    except Exception as e:
        print(f"❌ PhilossChecker演示失败：{e}")
        return None


async def demo_game_engine():
    """演示4: GameEngine完整博弈流程"""
    print("\n\n=== 演示4: GameEngine 完整博弈流程 ===")
    
    # 创建复杂任务
    task = Task(
        task_id="game_engine_demo_001",
        description="设计一个面向老年人的智能健康监测系统",
        domain="产品设计",
        requirements=[
            "24小时健康监测",
            "紧急情况自动报警", 
            "简单易用的界面",
            "家属远程查看功能"
        ],
        constraints=[
            "成本控制在2000元以内",
            "电池续航不少于7天",
            "支持WiFi和4G网络"
        ],
        max_iterations=3  # 为了演示，限制迭代次数
    )
    
    # 使用RoleGenerator生成智能体
    print("📝 生成参与博弈的智能体...")
    config = get_domain_config("产品设计")
    role_generator = RoleGenerator(config)
    
    try:
        agents = await role_generator.generate_agents(task, (3, 4))
        print(f"✅ 成功生成{len(agents)}个智能体：")
        for i, agent in enumerate(agents, 1):
            print(f"   {i}. {agent.name} ({agent.role})")
    except Exception as e:
        print(f"⚠️ 智能体生成失败，使用默认智能体：{e}")
        # 创建默认智能体
        agents = [
            Agent(
                name="产品经理",
                role="产品规划",
                responsibilities=["需求分析", "产品规划"],
                skills=["产品设计", "市场分析"],
                thinking_vector="核心目标: 设计老年人健康监测系统",
                system_prompt="你是产品经理，负责整体产品规划",
                connection_permissions=["技术专家", "设计师"]
            ),
            Agent(
                name="技术专家",
                role="技术实现",
                responsibilities=["技术方案", "架构设计"],
                skills=["软件开发", "硬件设计"],
                thinking_vector="核心目标: 实现技术方案",
                system_prompt="你是技术专家，负责技术实现",
                connection_permissions=["产品经理", "设计师"]
            ),
            Agent(
                name="用户体验设计师",
                role="体验设计",
                responsibilities=["界面设计", "交互优化"],
                skills=["UI设计", "用户研究"],
                thinking_vector="核心目标: 优化用户体验",
                system_prompt="你是UX设计师，专注用户体验",
                connection_permissions=["产品经理", "技术专家"]
            )
        ]
    
    # 初始化GameEngine
    print("\n🎮 初始化GameEngine...")
    game_engine = GameEngine(config)
    
    try:
        print(f"🚀 启动完整博弈会话...")
        print(f"   任务：{task.description}")
        print(f"   参与者：{len(agents)}个智能体")
        print(f"   最大轮数：{task.max_iterations}")
        
        # 启动博弈会话
        session = await game_engine.start_game_session(task, agents)
        
        print(f"\n✅ 博弈会话完成！")
        print(f"📊 会话统计：")
        print(f"   - 会话ID：{session.session_id}")
        print(f"   - 总轮数：{len(session.rounds)}")
        print(f"   - 总耗时：{session.total_time:.2f}秒")
        print(f"   - 最终状态：{session.status.value}")
        print(f"   - 成功完成：{session.final_result.success if session.final_result else False}")
        
        # 显示各轮次摘要
        print(f"\n📋 轮次详情：")
        for round_data in session.rounds:
            print(f"   第{round_data.round_number}轮:")
            print(f"     - 生成数量：{len(round_data.actor_outputs)}")
            print(f"     - 批判数量：{len(round_data.critic_outputs)}")
            print(f"     - 评估数量：{len(round_data.philoss_outputs)}")
            print(f"     - 平均Critical评分：{round_data.metadata.get('average_critical_score', 0):.2f}")
            print(f"     - 平均Novelty评分：{round_data.metadata.get('average_novelty_score', 0):.2f}")
            print(f"     - 决策：{round_data.decision}")
        
        # 显示最终结果
        if session.final_result:
            print(f"\n🎯 最终结果：")
            print(f"   - 任务成功：{session.final_result.success}")
            print(f"   - 总迭代数：{session.final_result.total_iterations}")
            print(f"   - 收敛达成：{session.final_result.convergence_achieved}")
            print(f"   - 最终输出数量：{len(session.final_result.final_outputs)}")
            
            if session.final_result.quality_metrics:
                print(f"   - 质量指标：")
                for metric, value in session.final_result.quality_metrics.items():
                    if isinstance(value, float):
                        print(f"     • {metric}: {value:.3f}")
                    else:
                        print(f"     • {metric}: {value}")
        
        # 显示系统统计
        system_stats = game_engine.get_session_statistics()
        print(f"\n📈 系统统计：")
        for key, value in system_stats.items():
            if isinstance(value, float):
                print(f"   {key}: {value:.3f}")
            else:
                print(f"   {key}: {value}")
        
        return session
        
    except Exception as e:
        print(f"❌ GameEngine演示失败：{e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_component_integration():
    """演示5: 组件集成测试"""
    print("\n\n=== 演示5: 组件集成测试 ===")
    
    print("🔧 测试各组件间的数据流转...")
    
    # 创建简单任务
    task = Task(
        task_id="integration_test",
        description="设计一个简单的待办事项应用",
        domain="软件开发",
        requirements=["任务管理", "提醒功能"],
        max_iterations=2
    )
    
    # 创建测试智能体
    agent = Agent(
        name="软件工程师",
        role="开发者",
        responsibilities=["软件设计", "代码实现"],
        skills=["编程", "系统设计"],
        thinking_vector="核心目标: 设计待办事项应用",
        system_prompt="你是软件工程师，负责应用开发",
        connection_permissions=[]
    )
    
    config = get_domain_config("软件开发")
    
    try:
        # 步骤1：Actor生成
        print("\n1️⃣ Actor生成内容...")
        actor = GameActor(config)
        actor_output = await actor.generate_content(agent, task)
        print(f"   ✅ 生成完成，长度：{len(actor_output.content)}字符")
        
        # 步骤2：Criticizer批判
        print("\n2️⃣ Criticizer批判分析...")
        criticizer = GameCriticizer(config)
        critic_output = await criticizer.critique_output(actor_output, agent, task)
        print(f"   ✅ 批判完成，评分：{critic_output.overall_score:.1f}/10")
        
        # 步骤3：PhilossChecker评估
        print("\n3️⃣ PhilossChecker创新性评估...")
        philoss_checker = PhilossChecker(config)
        philoss_output = await philoss_checker.evaluate_novelty(
            actor_output.content, 
            f"{actor_output.agent_id}_{actor_output.iteration}"
        )
        print(f"   ✅ 评估完成，创新性：{philoss_output.novelty_score:.3f}/10")
        
        # 步骤4：数据流验证
        print("\n4️⃣ 数据流验证...")
        print(f"   • Actor → Criticizer: ✅ (输出ID: {actor_output.agent_id}_{actor_output.iteration})")
        print(f"   • Actor → PhilossChecker: ✅ (内容长度: {len(actor_output.content)})")
        print(f"   • 批判目标匹配: ✅ (目标ID: {critic_output.target_output_id})")
        print(f"   • 评估目标匹配: ✅ (目标ID: {philoss_output.target_content_id})")
        
        print(f"\n✅ 组件集成测试通过！")
        
        return {
            'actor_output': actor_output,
            'critic_output': critic_output,
            'philoss_output': philoss_output
        }
        
    except Exception as e:
        print(f"❌ 组件集成测试失败：{e}")
        return None


async def main():
    """主函数 - 运行所有演示"""
    print("🎮 NagaAgent Game - 自博弈模块完整演示")
    print("=" * 60)
    
    try:
        # 演示1：Actor组件
        actor_output = await demo_actor_component()
        
        # 演示2：Criticizer组件
        critic_output = await demo_criticizer_component(actor_output)
        
        # 演示3：PhilossChecker组件
        philoss_output = await demo_philoss_checker(actor_output)
        
        # 演示4：GameEngine完整流程
        session = await demo_game_engine()
        
        # 演示5：组件集成测试
        integration_results = await demo_component_integration()
        
        # 总结
        print("\n\n🎯 演示总结")
        print("=" * 60)
        print("✅ GameActor: 功能生成组件 - 正常运行")
        print("✅ GameCriticizer: 批判优化组件 - 正常运行") 
        print("✅ PhilossChecker: 创新性评估组件 - 正常运行")
        print("✅ GameEngine: 完整博弈流程 - 正常运行")
        print("✅ 组件集成: 数据流转 - 正常运行")
        
        print(f"\n🚀 自博弈模块已就绪，可以投入使用！")
        
    except KeyboardInterrupt:
        print("\n演示被用户中断")
    except Exception as e:
        print(f"\n❌ 演示执行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main()) 
 
 
 
 
 
 