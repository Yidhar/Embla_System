#!/usr/bin/env python3
"""
NagaAgent 服务状态检查脚本
快速检查各个服务的运行状态
"""

import asyncio
import aiohttp
import json
import sys
from typing import Dict, Any

class ServiceChecker:
    """服务状态检查器"""
    
    def __init__(self):
        self.services = {
            "API服务器": "http://localhost:8000",
            "Agent服务器": "http://localhost:8001", 
            "MCP服务器": "http://localhost:8003"
        }
        self.results = {}
    
    async def check_service(self, name: str, url: str) -> Dict[str, Any]:
        """检查单个服务状态"""
        try:
            async with aiohttp.ClientSession() as session:
                # 尝试健康检查端点
                health_endpoints = {
                    "API服务器": "/health",
                    "Agent服务器": "/health", 
                    "MCP服务器": "/status"
                }
                
                endpoint = health_endpoints.get(name, "/health")
                async with session.get(f"{url}{endpoint}", timeout=5.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "status": "running",
                            "response": data,
                            "url": url
                        }
                    else:
                        return {
                            "status": "error",
                            "error": f"HTTP {resp.status}",
                            "url": url
                        }
        except aiohttp.ClientConnectorError:
            return {
                "status": "not_running",
                "error": "连接被拒绝",
                "url": url
            }
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "error": "连接超时",
                "url": url
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "url": url
            }
    
    async def check_all_services(self):
        """检查所有服务状态"""
        print("检查NagaAgent服务状态...")
        print("=" * 50)
        
        for name, url in self.services.items():
            print(f"检查 {name} ({url})...")
            result = await self.check_service(name, url)
            self.results[name] = result
            
            if result["status"] == "running":
                print(f"[OK] {name}: 运行中")
            elif result["status"] == "not_running":
                print(f"[FAIL] {name}: 未运行")
            elif result["status"] == "timeout":
                print(f"[TIMEOUT] {name}: 连接超时")
            else:
                print(f"[ERROR] {name}: 错误 - {result.get('error', '未知错误')}")
        
        print("\n" + "=" * 50)
        print("服务状态总结")
        print("=" * 50)
        
        running_count = sum(1 for result in self.results.values() if result["status"] == "running")
        total_count = len(self.results)
        
        print(f"运行中: {running_count}/{total_count}")
        
        for name, result in self.results.items():
            status_icon = {
                "running": "[OK]",
                "not_running": "[FAIL]", 
                "timeout": "[TIMEOUT]",
                "error": "[ERROR]"
            }.get(result["status"], "[UNKNOWN]")
            
            print(f"{status_icon} {name}: {result['status']}")
            if result["status"] != "running" and "error" in result:
                print(f"   错误: {result['error']}")
        
        # 提供启动建议
        print("\n启动建议:")
        if self.results["API服务器"]["status"] != "running":
            print("启动API服务器: python apiserver/start_server.py api")
        if self.results["Agent服务器"]["status"] != "running":
            print("启动Agent服务器: python agentserver/start_server.py")
        if self.results["MCP服务器"]["status"] != "running":
            print("启动MCP服务器: python mcpserver/start_server.py")
        
        return running_count == total_count

async def main():
    """主函数"""
    checker = ServiceChecker()
    all_running = await checker.check_all_services()
    
    if all_running:
        print("\n[SUCCESS] 所有服务都在运行！可以开始测试了。")
        print("运行完整测试: python test_full_flow.py")
    else:
        print("\n[WARNING] 部分服务未运行，请先启动所需服务。")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
