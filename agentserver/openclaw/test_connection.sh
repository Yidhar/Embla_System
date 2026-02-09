#!/bin/bash
# OpenClaw 通信测试脚本 (Shell 版)
#
# 使用方法:
#     chmod +x agentserver/openclaw/test_connection.sh
#     ./agentserver/openclaw/test_connection.sh

GATEWAY_URL="http://127.0.0.1:18789"
GATEWAY_TOKEN="9d3d8c24a1739f3a8a21653bbc218bc54f53ff1a5c5381de"
HOOKS_TOKEN="testnagahook"

echo "=================================================="
echo "OpenClaw 通信测试 (Shell)"
echo "Gateway: $GATEWAY_URL"
echo "=================================================="

echo ""
echo "[1] 测试 GET /"
curl -s -w "\n    状态码: %{http_code}\n" \
    -H "Authorization: Bearer $GATEWAY_TOKEN" \
    "$GATEWAY_URL/"

echo ""
echo "[2] 测试 POST /hooks/agent"
curl -s -w "\n    状态码: %{http_code}\n" \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $HOOKS_TOKEN" \
    -d '{"message": "你好，这是测试消息", "sessionKey": "naga:test", "name": "NagaTest"}' \
    "$GATEWAY_URL/hooks/agent"

echo ""
echo "[3] 测试 POST /hooks/wake"
curl -s -w "\n    状态码: %{http_code}\n" \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $HOOKS_TOKEN" \
    -d '{"text": "NagaAgent 测试事件", "mode": "now"}' \
    "$GATEWAY_URL/hooks/wake"

echo ""
echo "[4] 测试 POST /tools/invoke"
curl -s -w "\n    状态码: %{http_code}\n" \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $GATEWAY_TOKEN" \
    -d '{"tool": "bash", "args": {"command": "echo hello"}}' \
    "$GATEWAY_URL/tools/invoke"

echo ""
echo "=================================================="
echo "测试完成"
echo "=================================================="
