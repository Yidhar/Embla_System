#!/usr/bin/env python3
"""
NagaAgent 全流程测试脚本
测试普通对话、意图识别、MCP服务调用和结果返回的完整流程
"""

import asyncio
import aiohttp
import json
import time
import sys
import os
from pathlib import Path
from typing import Dict, Any, List

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class NagaAgentTester:
    """NagaAgent 全流程测试器"""
    
    def __init__(self):
        self.api_server_url = "http://localhost:8000"
        self.agentserver_url = "http://localhost:8001"
        self.mcpserver_url = "http://localhost:8003"
        self.test_results = []
        
    async def test_api_server_health(self) -> bool:
        """测试API服务器健康状态"""
        print("🔍 测试API服务器健康状态...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_server_url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ API服务器健康: {data}")
                        return True
                    else:
                        print(f"❌ API服务器健康检查失败: {resp.status}")
                        return False
        except Exception as e:
            print(f"❌ API服务器连接失败: {e}")
            return False
    
    async def test_agentserver_health(self) -> bool:
        """测试Agent服务器健康状态"""
        print("🔍 测试Agent服务器健康状态...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.agentserver_url}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ Agent服务器健康: {data}")
                        return True
                    else:
                        print(f"❌ Agent服务器健康检查失败: {resp.status}")
                        return False
        except Exception as e:
            print(f"❌ Agent服务器连接失败: {e}")
            return False
    
    async def test_mcpserver_health(self) -> bool:
        """测试MCP服务器健康状态"""
        print("🔍 测试MCP服务器健康状态...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mcpserver_url}/status") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ MCP服务器健康: {data}")
                        return True
                    else:
                        print(f"❌ MCP服务器健康检查失败: {resp.status}")
                        return False
        except Exception as e:
            print(f"❌ MCP服务器连接失败: {e}")
            return False
    
    async def test_ordinary_chat(self) -> Dict[str, Any]:
        """测试普通对话流程"""
        print("\n📝 测试普通对话流程...")
        
        test_message = "你好，请介绍一下你自己"
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "message": test_message,
                    "stream": False,
                    "session_id": f"test_session_{int(time.time())}"
                }
                
                async with session.post(
                    f"{self.api_server_url}/chat",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ 普通对话成功")
                        print(f"📄 响应: {data.get('response', '')[:100]}...")
                        return {
                            "success": True,
                            "response": data.get('response', ''),
                            "session_id": data.get('session_id', '')
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 普通对话失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 普通对话异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_streaming_chat(self) -> Dict[str, Any]:
        """测试流式对话流程"""
        print("\n🌊 测试流式对话流程...")
        
        test_message = "请详细解释一下人工智能的发展历史"
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "message": test_message,
                    "stream": True,
                    "session_id": f"test_stream_{int(time.time())}"
                }
                
                async with session.post(
                    f"{self.api_server_url}/chat/stream",
                    json=payload,
                    timeout=60.0
                ) as resp:
                    if resp.status == 200:
                        print("✅ 流式对话开始...")
                        response_chunks = []
                        
                        async for line in resp.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                data_str = line_str[6:]
                                if data_str == '[DONE]':
                                    break
                                elif data_str.startswith('session_id: '):
                                    session_id = data_str[12:]
                                    print(f"📋 会话ID: {session_id}")
                                else:
                                    response_chunks.append(data_str)
                                    print(f"📄 流式内容: {data_str}")
                        
                        complete_response = ''.join(response_chunks)
                        print(f"✅ 流式对话完成，总长度: {len(complete_response)} 字符")
                        
                        return {
                            "success": True,
                            "response": complete_response,
                            "chunks_count": len(response_chunks)
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 流式对话失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 流式对话异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_intent_analysis(self) -> Dict[str, Any]:
        """测试意图分析流程"""
        print("\n🧠 测试意图分析流程...")
        
        test_messages = [
            {"role": "user", "content": "我想查看今天的天气"},
            {"role": "assistant", "content": "我来帮您查看天气信息"},
            {"role": "user", "content": "请帮我搜索最新的科技新闻"}
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "messages": test_messages,
                    "session_id": f"test_intent_{int(time.time())}"
                }
                
                async with session.post(
                    f"{self.agentserver_url}/analyze_and_plan",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ 意图分析成功")
                        print(f"📊 分析结果: {data}")
                        return {
                            "success": True,
                            "analysis": data
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 意图分析失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 意图分析异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_mcp_task_scheduling(self) -> Dict[str, Any]:
        """测试MCP任务调度"""
        print("\n🔧 测试MCP任务调度...")
        
        test_query = "请帮我创建一个新的文档"
        test_tool_calls = [
            {
                "tool_name": "create_document",
                "parameters": {
                    "title": "测试文档",
                    "content": "这是一个测试文档"
                }
            }
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": test_query,
                    "tool_calls": test_tool_calls,
                    "session_id": f"test_mcp_{int(time.time())}",
                    "request_id": f"req_{int(time.time())}"
                }
                
                async with session.post(
                    f"{self.mcpserver_url}/schedule",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ MCP任务调度成功")
                        print(f"📋 任务ID: {data.get('task_id', 'N/A')}")
                        print(f"📊 调度结果: {data}")
                        return {
                            "success": True,
                            "task_id": data.get('task_id'),
                            "result": data
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ MCP任务调度失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ MCP任务调度异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_llm_service(self) -> Dict[str, Any]:
        """测试LLM服务"""
        print("\n🤖 测试LLM服务...")
        
        test_prompt = "请简单介绍一下Python编程语言的特点"
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "prompt": test_prompt,
                    "temperature": 0.7
                }
                
                async with session.post(
                    f"{self.api_server_url}/llm/chat",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ LLM服务调用成功")
                        print(f"📄 响应: {data.get('response', '')[:100]}...")
                        return {
                            "success": True,
                            "response": data.get('response', '')
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ LLM服务调用失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ LLM服务调用异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_full_workflow(self) -> Dict[str, Any]:
        """测试完整工作流程"""
        print("\n🔄 测试完整工作流程...")
        
        # 1. 发送一个可能触发工具调用的消息
        test_message = "请帮我查看今天的天气并创建一个天气报告文档"
        
        try:
            async with aiohttp.ClientSession() as session:
                # 发送流式对话请求
                payload = {
                    "message": test_message,
                    "stream": True,
                    "session_id": f"test_workflow_{int(time.time())}"
                }
                
                print(f"📤 发送消息: {test_message}")
                
                async with session.post(
                    f"{self.api_server_url}/chat/stream",
                    json=payload,
                    timeout=60.0
                ) as resp:
                    if resp.status == 200:
                        print("✅ 工作流程开始...")
                        response_chunks = []
                        
                        async for line in resp.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                data_str = line_str[6:]
                                if data_str == '[DONE]':
                                    break
                                elif data_str.startswith('session_id: '):
                                    session_id = data_str[12:]
                                    print(f"📋 会话ID: {session_id}")
                                else:
                                    response_chunks.append(data_str)
                                    print(f"📄 流式内容: {data_str}")
                        
                        complete_response = ''.join(response_chunks)
                        print(f"✅ 工作流程完成")
                        
                        # 等待一段时间让后台意图分析完成
                        print("⏳ 等待后台意图分析...")
                        await asyncio.sleep(5)
                        
                        return {
                            "success": True,
                            "response": complete_response,
                            "chunks_count": len(response_chunks)
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 工作流程失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 工作流程异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始NagaAgent全流程测试...")
        print("=" * 60)
        
        # 健康检查
        health_checks = await asyncio.gather(
            self.test_api_server_health(),
            self.test_agentserver_health(),
            self.test_mcpserver_health(),
            return_exceptions=True
        )
        
        api_healthy, agent_healthy, mcp_healthy = health_checks
        
        if not api_healthy:
            print("❌ API服务器不可用，终止测试")
            return
        
        # 基础功能测试
        print("\n" + "=" * 60)
        print("📋 基础功能测试")
        print("=" * 60)
        
        # 普通对话测试
        chat_result = await self.test_ordinary_chat()
        self.test_results.append(("普通对话", chat_result))
        
        # 流式对话测试
        stream_result = await self.test_streaming_chat()
        self.test_results.append(("流式对话", stream_result))
        
        # LLM服务测试
        llm_result = await self.test_llm_service()
        self.test_results.append(("LLM服务", llm_result))
        
        # 高级功能测试（如果服务可用）
        if agent_healthy:
            print("\n" + "=" * 60)
            print("🧠 高级功能测试")
            print("=" * 60)
            
            # 意图分析测试
            intent_result = await self.test_intent_analysis()
            self.test_results.append(("意图分析", intent_result))
        
        if mcp_healthy:
            # MCP任务调度测试
            mcp_result = await self.test_mcp_task_scheduling()
            self.test_results.append(("MCP任务调度", mcp_result))
        
        # 完整工作流程测试
        print("\n" + "=" * 60)
        print("🔄 完整工作流程测试")
        print("=" * 60)
        
        workflow_result = await self.test_full_workflow()
        self.test_results.append(("完整工作流程", workflow_result))
        
        # 生成测试报告
        self.generate_test_report()
    
    def generate_test_report(self):
        """生成测试报告"""
        print("\n" + "=" * 60)
        print("📊 测试报告")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        successful_tests = sum(1 for _, result in self.test_results if result.get("success", False))
        
        print(f"总测试数: {total_tests}")
        print(f"成功测试: {successful_tests}")
        print(f"失败测试: {total_tests - successful_tests}")
        print(f"成功率: {successful_tests/total_tests*100:.1f}%")
        
        print("\n详细结果:")
        for test_name, result in self.test_results:
            status = "✅ 成功" if result.get("success", False) else "❌ 失败"
            print(f"  {test_name}: {status}")
            if not result.get("success", False) and "error" in result:
                print(f"    错误: {result['error']}")
        
        # 保存测试结果到文件
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": successful_tests/total_tests*100,
            "results": self.test_results
        }
        
        with open("test_report.json", "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 详细报告已保存到: test_report.json")

async def main():
    """主函数"""
    tester = NagaAgentTester()
    
    print("NagaAgent 全流程测试脚本")
    print("请确保以下服务正在运行:")
    print("- API服务器: http://localhost:8000")
    print("- Agent服务器: http://localhost:8001") 
    print("- MCP服务器: http://localhost:8003")
    print()
    
    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n🛑 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
