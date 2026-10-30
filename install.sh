#!/bin/bash
# 安装/重装 sms-bridge：生成 token、注册开机自启（LaunchAgent）、打印手机端要填的地址。
# 重复运行安全。卸载用 uninstall.sh。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="local.smsbridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT=8787

PY=/usr/bin/python3
[ -x "$PY" ] || PY="$(command -v python3)"
[ -n "$PY" ] || { echo "错误：没找到 python3"; exit 1; }

# 1) 生成访问令牌（已存在则沿用）
if [ ! -s "$DIR/.token" ]; then
  "$PY" -c 'import secrets; print(secrets.token_urlsafe(18))' > "$DIR/.token"
  chmod 600 "$DIR/.token"
fi

# 2) 写 LaunchAgent（开机自启 + 崩溃自动拉起）
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$DIR/server.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SMSBRIDGE_PORT</key><string>$PORT</string>
    </dict>
    <key>StandardOutPath</key><string>$DIR/server.log</string>
    <key>StandardErrorPath</key><string>$DIR/server.err.log</string>
</dict>
</plist>
PLIST

MYUID="$(id -u)"
launchctl bootout "gui/$MYUID/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$MYUID" "$PLIST"
sleep 1

# 3) 健康检查 + 打印手机端要填的地址
if curl -s "http://127.0.0.1:$PORT/healthz" | grep -q '"ok"'; then
  echo "✅ 服务已启动并注册开机自启（LaunchAgent: ${LABEL}）"
else
  echo "⚠️ 服务未响应，请查看 $DIR/server.err.log"
  exit 1
fi

# 优先用 Tailscale 的 MagicDNS 名：换机器/换网络都不用改手机端
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
HOST=""
if [ -x "$TS" ]; then
  HOST="$("$TS" status --json 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  [ -z "$HOST" ] && HOST="$("$TS" ip -4 2>/dev/null | head -1)"
fi
VIA="Tailscale"
if [ -z "$HOST" ]; then
  HOST="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<Mac的局域网IP>')"
  VIA="局域网（仅同一 Wi-Fi 可用；建议先装 Tailscale 再重跑本脚本）"
fi
TOKEN="$(cat "$DIR/.token")"
echo
echo "📱 手机端 SmsForwarder 里要填的 Webhook 网址（POST，经 ${VIA}）："
echo "   http://$HOST:$PORT/push?token=$TOKEN"
if [ "$VIA" = "Tailscale" ]; then
  echo "   （该地址在任何网络下都可用；换机器时保持设备名不变即可继续沿用）"
fi
