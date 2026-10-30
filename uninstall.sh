#!/bin/bash
# 停止服务并移除开机自启。sms-bridge 目录本身不删，不需要可手动删除。
set -euo pipefail
LABEL="local.smsbridge"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "已停止 sms-bridge 并移除开机自启。"
