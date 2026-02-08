#!/bin/bash
echo "=== 测试: 直接请求 OpenClaw Gateway ==="
echo ""
echo "--- 请求详情 ---"
curl -v -X POST http://127.0.0.1:18789/hooks/agent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 9d3d8c24a1739f3a8a21653bbc218bc54f53ff1a5c5381de" \
  -d '{
    "message": "你好，请简短回复一句话",
    "name": "NagaTest",
    "sessionKey": "naga_test_001",
    "wakeMode": "now",
    "deliver": false,
    "timeoutSeconds": 60
  }' 2>&1

echo ""
echo "=== 测试完成 ==="
