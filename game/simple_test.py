#!/usr/bin/env python3
"""
简单测试脚本 - 测试NagaGameSystem的基础功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def test_basic_import():
    """测试基础导入功能"""
    print("🧪 测试1: 基础导入")
    try:
        from game.core.models.data_models import Task, Agent, create_requester_agent
        print("✅ 数据模型导入成功")
        
        from game.core.models.config import GameConfig
        print("✅ 配置模型导入成功")
        
        # 测试创建需求方节点
        test_task = Task(
            task_id="test_001",
            description="测试任务",
            domain="测试领域",
            requirements=["基础需求测试"],
            constraints=[]
        )
        
        requester = create_requester_agent(test_task)
        print(f"✅ 需求方节点创建成功: {requester.name}")
        print(f"   - 是否为需求方: {requester.is_requester}")
        print(f"   - 角色类型: {requester.role}")
        
        return True
        
    except Exception as e:
        print(f"❌ 基础导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_distributor():
    """测试Distributor组件"""
    print("\n🧪 测试2: Distributor组件")
    try:
        from game.core.interaction_graph.distributor import Distributor
        from game.core.models.data_models import RoleGenerationRequest, Task
        
        print("✅ Distributor导入成功")
        
        # 创建测试任务
        task = Task(
            task_id="test_distributor",
            description="开发一个简单的网站",
            domain="网站开发",
            requirements=["用户友好的界面", "响应式设计"],
            constraints=["开发时间2个月", "预算有限"]
        )
        
        # 创建角色生成请求
        request = RoleGenerationRequest(
            task=task,
            expected_count_range=(3, 5),
            domain_context="网站开发项目需要前端、后端和设计人员"
        )
        
        print("✅ 测试数据创建成功")
        print(f"   - 任务: {task.description}")
        print(f"   - 领域: {task.domain}")
        print(f"   - 期望角色数量: {request.expected_count_range}")
        
        return True
        
    except Exception as e:
        print(f"❌ Distributor测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_user_interaction_handler():
    """测试用户交互处理器"""
    print("\n🧪 测试3: 用户交互处理器")
    try:
        from game.core.interaction_graph.user_interaction_handler import UserInteractionHandler
        from game.core.models.config import GameConfig
        from game.core.models.data_models import Agent, InteractionGraph, Task
        
        print("✅ 用户交互处理器导入成功")
        
        # 创建配置
        config = GameConfig()
        handler = UserInteractionHandler(config)
        
        print("✅ 用户交互处理器创建成功")
        print(f"   - 活跃会话数: {len(handler.active_sessions)}")
        print(f"   - 历史会话数: {len(handler.session_history)}")
        
        return True
        
    except Exception as e:
        print(f"❌ 用户交互处理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_system_without_llm():
    """测试系统基础功能（不调用LLM）"""
    print("\n🧪 测试4: 系统基础功能")
    try:
        from game.naga_game_system import NagaGameSystem
        from game.core.models.config import GameConfig
        
        print("✅ NagaGameSystem导入成功")
        
        # 创建系统实例
        config = GameConfig()
        system = NagaGameSystem(config)
        
        print("✅ NagaGameSystem创建成功")
        print(f"   - 当前阶段: {system.system_state.current_phase}")
        print(f"   - 配置: {type(system.config).__name__}")
        print(f"   - 用户交互处理器: {type(system.user_interaction_handler).__name__}")
        
        # 测试统计功能
        stats = system.get_system_statistics()
        print("✅ 系统统计获取成功")
        print(f"   - 总执行次数: {stats['system_info']['total_executions']}")
        print(f"   - 成功率: {stats['system_info']['success_rate']:.1f}%")
        
        return True
        
    except Exception as e:
        print(f"❌ 系统基础功能测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主测试函数"""
    print("🚀 NagaAgent Game 简单测试")
    print("=" * 50)
    
    test_results = []
    
    # 运行各项测试
    test_results.append(await test_basic_import())
    test_results.append(await test_distributor())  
    test_results.append(await test_user_interaction_handler())
    test_results.append(await test_system_without_llm())
    
    # 汇总结果
    print("\n" + "=" * 50)
    print("📊 测试结果汇总")
    print("=" * 50)
    
    passed = sum(test_results)
    total = len(test_results)
    
    print(f"✅ 通过: {passed}/{total}")
    print(f"❌ 失败: {total - passed}/{total}")
    print(f"📈 成功率: {passed/total*100:.1f}%")
    
    if passed == total:
        print("\n🎉 所有基础测试通过！系统基础架构正常。")
        print("💡 提示：要测试完整功能，需要配置LLM API。")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，需要检查相关组件。")
    
    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1) 
 
 