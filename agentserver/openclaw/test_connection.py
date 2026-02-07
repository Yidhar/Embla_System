#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 通信测试脚本 (Python 版)

使用方法:
    python agentserver/openclaw/test_connection.py
"""

import asyncio
import httpx

GATEWAY_URL = "http://127.0.0.1:18789"
GATEWAY_TOKEN = "9d3d8c24a1739f3a8a21653bbc218bc54f53ff1a5c5381de"
HOOKS_TOKEN = "testnagahook"

GATEWAY_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GATEWAY_TOKEN}"
}

HOOKS_HEADERS = {
    "Content-Type": "application/json",
    "x-openclaw-token": HOOKS_TOKEN
}


async def test_root():
    """测试根路径"""
    print("\n[1] 测试 GET /")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{GATEWAY_URL}/", headers=GATEWAY_HEADERS)
            print(f"    状态码: {r.status_code}")
            print(f"    响应: {r.text[:200] if r.text else '(空)'}")
        except Exception as e:
            print(f"    错误: {e}")


async def test_hooks_agent():
    """测试发送消息 POST /hooks/agent"""
    print("\n[2] 测试 POST /hooks/agent")
    payload = {
        "message": "你好，这是测试消息",
        "sessionKey": "naga:test",
        "name": "NagaTest"
    }

    # 尝试多种认证方式
    auth_methods = [
        ("Bearer token", {"Content-Type": "application/json", "Authorization": f"Bearer {HOOKS_TOKEN}"}),
        ("x-openclaw-token", {"Content-Type": "application/json", "x-openclaw-token": HOOKS_TOKEN}),
        ("query param", {"Content-Type": "application/json"}),
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        for name, headers in auth_methods:
            try:
                url = f"{GATEWAY_URL}/hooks/agent"
                if name == "query param":
                    url += f"?token={HOOKS_TOKEN}"
                r = await client.post(url, headers=headers, json=payload)
                print(f"    [{name}] 状态码: {r.status_code}")
                if r.status_code != 401:
                    print(f"    响应: {r.text[:300] if r.text else '(空)'}")
                    break
            except Exception as e:
                print(f"    [{name}] 错误: {e}")


async def test_hooks_wake():
    """测试触发事件 POST /hooks/wake"""
    print("\n[3] 测试 POST /hooks/wake")
    payload = {
        "text": "NagaAgent 测试事件",
        "mode": "now"
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(f"{GATEWAY_URL}/hooks/wake", headers=HOOKS_HEADERS, json=payload)
            print(f"    状态码: {r.status_code}")
            print(f"    响应: {r.text[:500] if r.text else '(空)'}")
        except Exception as e:
            print(f"    错误: {e}")


async def test_tools_invoke():
    """测试工具调用 POST /tools/invoke"""
    print("\n[4] 测试 POST /tools/invoke")

    # 测试会话相关工具的详细返回
    tools_to_try = [
        ("sessions_list", {}),
        ("sessions_history", {"sessionKey": "agent:main:naga:test", "limit": 5}),
        ("session_status", {}),
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        for tool_name, args in tools_to_try:
            payload = {"tool": tool_name}
            if args:
                payload["args"] = args
            try:
                r = await client.post(
                    f"{GATEWAY_URL}/tools/invoke",
                    headers=GATEWAY_HEADERS,
                    json=payload
                )
                print(f"\n    [{tool_name}] 状态码: {r.status_code}")
                if r.status_code == 200:
                    import json
                    result = r.json()
                    print(f"    响应: {json.dumps(result, indent=2, ensure_ascii=False)[:800]}")
                else:
                    print(f"    错误: {r.text[:200]}")
            except Exception as e:
                print(f"    [{tool_name}] 错误: {e}")


async def main():
    print("=" * 50)
    print("OpenClaw 通信测试 (Python)")
    print(f"Gateway: {GATEWAY_URL}")
    print("=" * 50)

    await test_root()
    await test_hooks_agent()
    await test_hooks_wake()
    await test_tools_invoke()

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
