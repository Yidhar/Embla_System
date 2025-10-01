#!/usr/bin/env python3
"""
简单的API服务器测试
不依赖外部服务，直接测试API服务器功能
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_api_server_import():
    """测试API服务器导入"""
    print("测试API服务器导入...")
    try:
        from apiserver.api_server import app
        print("[OK] API服务器导入成功")
        return True
    except Exception as e:
        print(f"[FAIL] API服务器导入失败: {e}")
        return False

async def test_llm_service_import():
    """测试LLM服务导入"""
    print("测试LLM服务导入...")
    try:
        from apiserver.llm_service import get_llm_service
        llm_service = get_llm_service()
        print("[OK] LLM服务导入成功")
        return True
    except Exception as e:
        print(f"[FAIL] LLM服务导入失败: {e}")
        return False

async def test_message_manager_import():
    """测试消息管理器导入"""
    print("测试消息管理器导入...")
    try:
        from apiserver.message_manager import message_manager
        print("[OK] 消息管理器导入成功")
        return True
    except Exception as e:
        print(f"[FAIL] 消息管理器导入失败: {e}")
        return False

async def test_config_import():
    """测试配置系统导入"""
    print("测试配置系统导入...")
    try:
        from system.config import config, AI_NAME
        print(f"[OK] 配置系统导入成功, AI_NAME: {AI_NAME}")
        return True
    except Exception as e:
        print(f"[FAIL] 配置系统导入失败: {e}")
        return False

async def test_simple_chat():
    """测试简单对话功能"""
    print("测试简单对话功能...")
    try:
        from apiserver.llm_service import get_llm_service
        
        llm_service = get_llm_service()
        if llm_service.is_available():
            print("[OK] LLM服务可用")
            # 这里不实际调用，只是检查服务状态
            return True
        else:
            print("[WARNING] LLM服务不可用，可能是配置问题")
            return False
    except Exception as e:
        print(f"[FAIL] 简单对话测试失败: {e}")
        return False

async def main():
    """主函数"""
    print("NagaAgent 简单功能测试")
    print("=" * 50)
    
    tests = [
        ("API服务器导入", test_api_server_import),
        ("LLM服务导入", test_llm_service_import),
        ("消息管理器导入", test_message_manager_import),
        ("配置系统导入", test_config_import),
        ("简单对话功能", test_simple_chat),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"[ERROR] 测试异常: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("测试结果总结")
    print("=" * 50)
    
    successful = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"成功: {successful}/{total}")
    print(f"成功率: {successful/total*100:.1f}%")
    
    for test_name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} {test_name}")
    
    if successful == total:
        print("\n[SUCCESS] 所有基础功能测试通过！")
        print("可以尝试启动服务进行完整测试。")
    else:
        print("\n[WARNING] 部分功能测试失败，请检查依赖和配置。")

if __name__ == "__main__":
    asyncio.run(main())
