#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP 调度统一流程测试
- 目标：验证 /schedule → MCPScheduler → mcp_manager.unified_call 的单一路径
运行：python -m mcpserver.test_mcp_schedule  # 注释
"""

import asyncio  # 异步运行 #
from typing import Any, Dict  # 类型注解 #

from mcpserver import mcp_server as srv  # 引入被测模块 #


class FakeMCPManager:
    """注入的假 mcp_manager（一行注释）"""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []  # 记录统一调用 #

    async def unified_call(self, service_name: str, tool_name: str, args: dict):
        self.calls.append((service_name, tool_name, dict(args)))
        # 返回一个可识别的假结果
        return {"ok": True, "service": service_name, "tool": tool_name, "args": args}


async def run_test():
    # 启动事件，初始化模块（能力管理器等） #
    await srv.startup_event()

    # 注入假的 mcp_manager，确保 Scheduler 使用统一调用 #
    fake = FakeMCPManager()
    srv.Modules.mcp_manager = fake

    # 重新创建调度器以注入假 mcp_manager
    srv.Modules.scheduler = srv.MCPScheduler(srv.Modules.capability_manager, srv.Modules.mcp_manager)

    # 构造请求负载（单个工具调用） #
    payload: Dict[str, Any] = {
        "query": "测试调用",
        "tool_calls": [
            {
                "agentType": "mcp",
                "service_name": "demo_service",
                "tool_name": "echo",
                "text": "hello"
            }
        ],
        "session_id": "test_session"
    }

    # 直接调用路由函数（等价于 POST /schedule） #
    resp = await srv.schedule_mcp_task(payload)

    # 打印结果
    print("==== 接口返回 ====")
    print(resp)

    print("\n==== 等待任务执行完成并检查统一调用 ====")
    task_id = resp.get("task_id")
    assert resp.get("success") is True and task_id, "接口未成功或缺少task_id"

    # 等待工作线程执行，超时时间2秒
    for _ in range(40):
        await asyncio.sleep(0.05)
        if fake.calls:
            break
    print(fake.calls)
    assert fake.calls and fake.calls[0][0] == "demo_service" and fake.calls[0][1] == "echo", "未触发统一调用或参数不正确"

    print("\n✅ 测试通过：/schedule → Scheduler → mcp_manager.unified_call 单一路径生效")


if __name__ == "__main__":
    asyncio.run(run_test())  # 运行 #


