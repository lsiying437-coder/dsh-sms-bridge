#!/bin/bash
# 模拟一条验证码短信推送到本机服务，验证「接收 → 提取 → 查询」整条链路（不需要手机）。
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN="$(cat "$DIR/.token")"
CODE=$((100000 + RANDOM % 900000))

curl -s -X POST "http://127.0.0.1:8787/push?token=$TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"from\":\"10690000000\",\"body\":\"【桥接测试】您的验证码是${CODE}，10分钟内有效，请勿泄露给他人。\"}"
echo
echo "已推送模拟短信，验证码应为 $CODE，下面用 smscode 查询："
"$DIR/smscode" 桥接测试 && echo "✅ 链路正常" || echo "❌ 查询失败，查看 server.err.log"
