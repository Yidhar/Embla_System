#!/usr/bin/env python3
"""
MCP服务调用流程测试脚本
测试从意图识别到MCP服务调用到结果返回的完整流程
"""

import asyncio
import aiohttp
import json
import time
import sys
from typing import Dict, Any, List

class MCPFlowTester:
    """MCP服务调用流程测试器"""
    
    def __init__(self):
        self.api_server_url = "http://localhost:8000"
        self.agentserver_url = "http://localhost:8001"
        self.mcpserver_url = "http://localhost:8003"
        self.test_results = []
    
    async def test_intent_to_mcp_flow(self) -> Dict[str, Any]:
        """测试意图识别到MCP调用的完整流程"""
        print("🔄 测试意图识别到MCP调用流程...")
        
        # 1. 发送一个可能触发工具调用的消息
        test_message = "请帮我创建一个新的文档，标题是'测试文档'"
        session_id = f"test_mcp_flow_{int(time.time())}"
        
        print(f"📤 发送消息: {test_message}")
        print(f"📋 会话ID: {session_id}")
        
        try:
            async with aiohttp.ClientSession() as session:
                # 发送流式对话请求
                payload = {
                    "message": test_message,
                    "stream": True,
                    "session_id": session_id
                }
                
                async with session.post(
                    f"{self.api_server_url}/chat/stream",
                    json=payload,
                    timeout=60.0
                ) as resp:
                    if resp.status == 200:
                        print("✅ 对话请求成功，开始接收流式响应...")
                        response_chunks = []
                        
                        async for line in resp.content:
                            line_str = line.decode('utf-8').strip()
                            if line_str.startswith('data: '):
                                data_str = line_str[6:]
                                if data_str == '[DONE]':
                                    print("✅ 流式响应完成")
                                    break
                                elif data_str.startswith('session_id: '):
                                    received_session_id = data_str[12:]
                                    print(f"📋 收到会话ID: {received_session_id}")
                                else:
                                    response_chunks.append(data_str)
                                    print(f"📄 流式内容: {data_str}")
                        
                        complete_response = ''.join(response_chunks)
                        print(f"📄 完整响应: {complete_response}")
                        
                        # 2. 等待后台意图分析
                        print("⏳ 等待后台意图分析...")
                        await asyncio.sleep(3)
                        
                        # 3. 检查是否有MCP任务被调度
                        mcp_tasks = await self.check_mcp_tasks()
                        
                        return {
                            "success": True,
                            "response": complete_response,
                            "session_id": session_id,
                            "mcp_tasks": mcp_tasks
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 对话请求失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 流程测试异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_mcp_tasks(self) -> List[Dict[str, Any]]:
        """检查MCP任务状态"""
        print("🔍 检查MCP任务状态...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.mcpserver_url}/status") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"📊 MCP服务器状态: {data}")
                        return data.get("tasks", [])
                    else:
                        print(f"❌ 无法获取MCP状态: {resp.status}")
                        return []
        except Exception as e:
            print(f"❌ 检查MCP状态异常: {e}")
            return []
    
    async def test_direct_mcp_call(self) -> Dict[str, Any]:
        """直接测试MCP服务调用"""
        print("\n🔧 直接测试MCP服务调用...")
        
        test_query = "创建一个测试文档"
        test_tool_calls = [
            {
                "tool_name": "create_document",
                "parameters": {
                    "title": "直接测试文档",
                    "content": "这是通过直接调用创建的测试文档"
                }
            }
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": test_query,
                    "tool_calls": test_tool_calls,
                    "session_id": f"test_direct_{int(time.time())}",
                    "request_id": f"req_{int(time.time())}"
                }
                
                print(f"📤 发送MCP请求: {test_query}")
                print(f"🔧 工具调用: {test_tool_calls}")
                
                async with session.post(
                    f"{self.mcpserver_url}/schedule",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ MCP调用成功")
                        print(f"📋 任务ID: {data.get('task_id', 'N/A')}")
                        print(f"📊 结果: {data}")
                        return {
                            "success": True,
                            "task_id": data.get('task_id'),
                            "result": data
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ MCP调用失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ MCP调用异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_agent_analysis(self) -> Dict[str, Any]:
        """测试Agent服务器分析功能"""
        print("\n🧠 测试Agent服务器分析功能...")
        
        test_messages = [
            {"role": "user", "content": "请帮我创建一个新的文档"},
            {"role": "assistant", "content": "我来帮您创建文档"},
            {"role": "user", "content": "文档标题是'项目报告'，内容包含项目进度和总结"}
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "messages": test_messages,
                    "session_id": f"test_analysis_{int(time.time())}"
                }
                
                print(f"📤 发送分析请求，消息数: {len(test_messages)}")
                
                async with session.post(
                    f"{self.agentserver_url}/analyze_and_plan",
                    json=payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ 分析请求成功")
                        print(f"📊 分析结果: {data}")
                        return {
                            "success": True,
                            "analysis": data
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 分析请求失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 分析请求异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def test_mcp_callback_flow(self) -> Dict[str, Any]:
        """测试MCP回调流程"""
        print("\n🔄 测试MCP回调流程...")
        
        # 模拟工具执行结果回调
        callback_payload = {
            "session_id": f"test_callback_{int(time.time())}",
            "task_id": f"task_{int(time.time())}",
            "success": True,
            "result": {
                "success": True,
                "message": "文档创建成功",
                "document_id": "doc_12345"
            }
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                print(f"📤 发送回调请求: {callback_payload}")
                
                async with session.post(
                    f"{self.mcpserver_url}/tool_result_callback",
                    json=callback_payload,
                    timeout=30.0
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"✅ 回调处理成功")
                        print(f"📊 回调结果: {data}")
                        return {
                            "success": True,
                            "callback_result": data
                        }
                    else:
                        error_text = await resp.text()
                        print(f"❌ 回调处理失败: {resp.status} - {error_text}")
                        return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            print(f"❌ 回调处理异常: {e}")
            return {"success": False, "error": str(e)}
    
    async def run_mcp_tests(self):
        """运行MCP相关测试"""
        print("🚀 开始MCP服务调用流程测试...")
        print("=" * 60)
        
        # 1. 直接MCP调用测试
        print("📋 测试1: 直接MCP服务调用")
        print("-" * 40)
        mcp_result = await self.test_direct_mcp_call()
        self.test_results.append(("直接MCP调用", mcp_result))
        
        # 2. Agent分析测试
        print("\n📋 测试2: Agent服务器分析")
        print("-" * 40)
        analysis_result = await self.test_agent_analysis()
        self.test_results.append(("Agent分析", analysis_result))
        
        # 3. MCP回调测试
        print("\n📋 测试3: MCP回调处理")
        print("-" * 40)
        callback_result = await self.test_mcp_callback_flow()
        self.test_results.append(("MCP回调", callback_result))
        
        # 4. 完整流程测试
        print("\n📋 测试4: 完整意图识别到MCP调用流程")
        print("-" * 40)
        flow_result = await self.test_intent_to_mcp_flow()
        self.test_results.append(("完整流程", flow_result))
        
        # 生成测试报告
        self.generate_mcp_report()
    
    def generate_mcp_report(self):
        """生成MCP测试报告"""
        print("\n" + "=" * 60)
        print("📊 MCP流程测试报告")
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
        
        # 保存测试结果
        report_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "test_type": "MCP流程测试",
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": successful_tests/total_tests*100,
            "results": self.test_results
        }
        
        with open("mcp_test_report.json", "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 详细报告已保存到: mcp_test_report.json")

async def main():
    """主函数"""
    tester = MCPFlowTester()
    
    print("MCP服务调用流程测试脚本")
    print("请确保以下服务正在运行:")
    print("- API服务器: http://localhost:8000")
    print("- Agent服务器: http://localhost:8001") 
    print("- MCP服务器: http://localhost:8003")
    print()
    
    try:
        await tester.run_mcp_tests()
    except KeyboardInterrupt:
        print("\n🛑 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
