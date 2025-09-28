#!/usr/bin/env python3
"""
NagaAgent Game 用户问题处理演示

展示完全无枚举的动态用户问题处理流程：
1. 用户提出问题
2. 系统基于LLM推断领域
3. 动态生成专业智能体团队
4. 构建交互图（需求方 → 执行者 → 需求方）
5. 处理问题并返回结果

核心特点：
- 无任何固定枚举
- 完全基于LLM推理
- 动态角色生成
- 智能领域识别
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from game import NagaGameSystem
from game.core.models.config import GameConfig

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def demo_user_questions():
    """演示处理不同类型的用户问题"""
    print("🎯 NagaAgent Game - 无枚举用户问题处理演示")
    print("=" * 60)
    
    # 初始化系统
    print("🚀 初始化NagaGameSystem...")
    config = GameConfig()
    naga_system = NagaGameSystem(config)
    
    # 定义测试问题（涵盖不同领域，但不使用枚举）
    test_questions = [
        "我想开发一个手机游戏，有什么好的建议吗？",
        "如何设计一个用户友好的购物网站？", 
        "我需要分析一下我们公司的市场竞争策略",
        "想学习人工智能，应该从哪里开始？",
        "如何优化我们的软件系统性能？"
    ]
    
    print(f"📝 准备处理{len(test_questions)}个用户问题...\n")
    
    for i, question in enumerate(test_questions, 1):
        print(f"{'='*60}")
        print(f"🔍 问题 {i}: {question}")
        print(f"{'='*60}")
        
        try:
            # 处理用户问题
            print("⚡ 开始处理...")
            response = await naga_system.process_user_question(
                user_question=question,
                user_id=f"demo_user_{i}"
            )
            
            print(f"✅ 处理完成！")
            print(f"📊 处理统计：")
            print(f"   - 响应来源：{response.source_agent}")
            print(f"   - 处理耗时：{response.processing_time:.2f}秒")
            print(f"   - 会话ID：{response.metadata.get('session_id', 'unknown')}")
            print(f"   - 智能体数量：{response.metadata.get('agent_count', 0)}")
            
            print(f"\n💬 系统响应：")
            print("```")
            # 显示响应的前500字符
            response_preview = response.content[:500] + "..." if len(response.content) > 500 else response.content
            print(response_preview)
            print("```")
            
            print(f"\n🔄 处理步骤：")
            processing_steps = response.metadata.get('processing_steps', [])
            for step_num, step in enumerate(processing_steps, 1):
                print(f"   {step_num}. {step}")
            
        except Exception as e:
            print(f"❌ 处理失败：{e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "⏸️ " * 20 + "\n")
        
        # 短暂停顿，避免API调用过于频繁
        await asyncio.sleep(1)
    
    # 显示系统统计
    print("📈 系统整体统计：")
    stats = naga_system.get_system_statistics()
    print(f"   - 总执行次数：{stats['system_info']['total_executions']}")
    print(f"   - 成功次数：{stats['system_info']['successful_executions']}")
    print(f"   - 成功率：{stats['system_info']['success_rate']:.1f}%")
    print(f"   - 当前阶段：{stats['system_info']['current_phase']}")
    
    # 显示用户交互统计
    interaction_stats = naga_system.user_interaction_handler.get_session_statistics()
    print(f"\n🎭 用户交互统计：")
    print(f"   - 总会话数：{interaction_stats['total_sessions']}")
    print(f"   - 成功会话：{interaction_stats['successful_sessions']}")
    print(f"   - 平均处理时间：{interaction_stats['average_processing_time']:.2f}秒")


async def demo_dynamic_domain_inference():
    """演示动态领域推断功能"""
    print("\n\n🧠 动态领域推断演示")
    print("=" * 60)
    
    config = GameConfig()
    naga_system = NagaGameSystem(config)
    
    # 测试不同类型的问题
    test_cases = [
        "我想制作一个RPG游戏，需要什么技术栈？",
        "公司网站的用户体验需要改进，有什么建议？",
        "我们的销售数据显示下滑趋势，如何分析原因？",
        "想研究深度学习在医疗诊断中的应用",
        "如何搭建一个高并发的微服务架构？",
        "我想学习钢琴，应该怎么开始？"  # 测试非技术问题
    ]
    
    for i, question in enumerate(test_cases, 1):
        print(f"\n🔍 测试问题 {i}: {question}")
        
        try:
            # 推断领域
            inferred_domain = await naga_system._infer_domain_from_question(question)
            print(f"🎯 推断领域：{inferred_domain}")
            
        except Exception as e:
            print(f"❌ 领域推断失败：{e}")


async def demo_agent_generation_without_enumeration():
    """演示无枚举的智能体生成"""
    print("\n\n🤖 无枚举智能体生成演示")
    print("=" * 60)
    
    config = GameConfig()
    naga_system = NagaGameSystem(config)
    
    # 创建一个复杂的任务
    from game.core.models.data_models import Task
    
    task = Task(
        task_id="complex_demo",
        description="设计并开发一个面向老年人的智能健康管理平台，包含健康监测、医疗咨询、用药提醒等功能",
        domain="智能健康平台",  # 非枚举的领域
        requirements=[
            "用户界面要简单易用",
            "支持语音交互",
            "数据安全性要高",
            "能够连接各种健康设备"
        ],
        constraints=[
            "开发周期6个月",
            "预算有限",
            "需要通过医疗器械认证"
        ]
    )
    
    print(f"📋 任务描述：{task.description}")
    print(f"🏷️  任务领域：{task.domain}")
    print(f"📝 需求数量：{len(task.requirements)}")
    print(f"⚠️  约束条件：{len(task.constraints)}")
    
    try:
        print("\n🚀 开始生成智能体团队...")
        agents = await naga_system.generate_agents_only(task, (4, 6))
        
        print(f"✅ 成功生成{len(agents)}个智能体：")
        
        for i, agent in enumerate(agents, 1):
            print(f"\n{i}. **{agent.name}** ({agent.role})")
            print(f"   🎭 身份：{'需求方' if agent.is_requester else '执行者'}")
            print(f"   📋 职责：{', '.join(agent.responsibilities[:3])}...")
            print(f"   🛠️  技能：{', '.join(agent.skills[:3])}...")
            print(f"   🔗 连接权限：{', '.join(agent.connection_permissions) if agent.connection_permissions else '无'}")
        
        print(f"\n🌐 智能体网络结构：")
        requester = next((a for a in agents if a.is_requester), None)
        if requester:
            print(f"   需求方 → {requester.connection_permissions[0] if requester.connection_permissions else '无连接'}")
            
            # 查找能回传给需求方的智能体
            for agent in agents:
                if not agent.is_requester and "需求方" in agent.connection_permissions:
                    print(f"   {agent.name} → 需求方")
        
    except Exception as e:
        print(f"❌ 智能体生成失败：{e}")
        import traceback
        traceback.print_exc()


async def main():
    """主演示函数"""
    print("🎮 NagaAgent Game - 完全无枚举系统演示")
    print("🚫 本系统不使用任何固定枚举，完全基于LLM动态推理")
    print("=" * 80)
    
    try:
        # 演示1：用户问题处理
        await demo_user_questions()
        
        # 演示2：动态领域推断
        await demo_dynamic_domain_inference()
        
        # 演示3：无枚举智能体生成
        await demo_agent_generation_without_enumeration()
        
        print("\n\n🎯 演示总结")
        print("=" * 80)
        print("✅ 动态用户问题处理 - 完全基于LLM推理")
        print("✅ 智能领域推断 - 无固定领域列表") 
        print("✅ 动态智能体生成 - 无角色枚举")
        print("✅ 灵活交互图构建 - 自适应连接权限")
        print("✅ 个性化响应生成 - 基于角色特征动态生成")
        
        print(f"\n🚀 系统已完全准备就绪，可以处理任何类型的用户问题！")
        
    except KeyboardInterrupt:
        print("\n演示被用户中断")
    except Exception as e:
        print(f"\n❌ 演示执行出错：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main()) 