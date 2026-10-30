# sms-bridge — 手机短信验证码自动到 Mac

解决一件事：在电脑上注册/登录时，不用低头看手机抄验证码。

**原理**：手机装开源 App **SmsForwarder（短信转发器）**，收到短信立刻 POST 到这台 Mac 上的常驻小服务（`server.py`，端口 8787），服务自动提取验证码；任何程序跑一条 `smscode.py` 命令即可取码。

```
手机 (SmsForwarder + Tailscale)
        │  Tailscale 加密隧道（任意网络）
        ▼
Mac  <hostname>.<tailnet>.ts.net:8787  (server.py)
        │
        ▼
smscode.py  →  验证码
```

## 为什么套 Tailscale

手机和 Mac 加入同一 Tailscale 虚拟局域网后，手机在**任何网络**（流量、任意 Wi-Fi、公司网）都能推到 Mac，换 Wi-Fi 不需要重配，也不需要公网端口映射。地址用 MagicDNS 名而不是 IP，换机器时手机端不用再改。

## 一、Mac 端安装

依赖：`python3`（macOS 自带 `/usr/bin/python3`；若系统提示安装命令行工具，装一下 Xcode Command Line Tools 即可）。

```bash
git clone <本仓库地址> ~/.zcode/workspace/default/sms-bridge
cd ~/.zcode/workspace/default/sms-bridge
bash install.sh
```

`install.sh` 会做四件事，重复运行安全：

1. 没有 `.token` 就生成一个（`secrets.token_urlsafe(18)`，权限 600）
2. 写 `~/Library/LaunchAgents/local.smsbridge.plist`（开机自启 + 崩溃自动拉起）
3. `launchctl bootstrap` 起服务
4. 健康检查 `/healthz`，然后打印手机端要填的 Webhook 地址

卸载：`bash uninstall.sh`。

## 二、Tailscale 组网

1. Mac 装 Tailscale（<https://tailscale.com/download/mac> 或 App Store），登录账号。
2. 手机装 Tailscale（<https://pkgs.tailscale.com/stable#android>），**用同一账号**登录，允许 VPN 连接请求，顶部显示 Connected 即成功。
3. 手机端防杀后台：设置 → 应用管理 → Tailscale → 开「自启动」、省电策略「无限制」、忽略电池优化。
4. Mac 端开机自启 App：

```bash
cat > ~/Library/LaunchAgents/local.tailscale-start.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>local.tailscale-start</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>Tailscale</string>
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.tailscale-start.plist
```

5. 看自己在这张网里的名字和地址：

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale status
/Applications/Tailscale.app/Contents/MacOS/Tailscale status --json \
  | python3 -c 'import json,sys; s=json.load(sys.stdin)["Self"]; print(s["HostName"], s["DNSName"], s["TailscaleIPs"])'
```

`DNSName` 就是手机该用的地址（形如 `macbook-air.tailXXXXXX.ts.net`）。

## 三、手机端配置（一次性，约 10 分钟）

1. 装 **SmsForwarder 短信转发器**（开源，GitHub `pppscn/SmsForwarder`，酷安/应用商店也能搜到），授予短信读取权限，按需设「自启动 + 省电无限制」。
2. 新建转发规则：匹配「全部短信」或按发送方筛选。
3. 发送通道选 **Webhook**，填：

```
http://<你的 Mac MagicDNS 名>:8787/push?token=<你的 TOKEN>
```

请求方式 **POST**，请求体用 JSON，例如：

```json
{"from":"[from]","body":"[orgContent]","time":"[receiveTime]"}
```

`secret` 留空。服务端兼容 JSON、表单、纯文本三种格式，字段名自动识别。
4. 点通道里的「测试」，Mac 上跑 `python3 smscode.py --list` 看到新记录即通。

### 换机器时手机要不要改

**用 MagicDNS 名时不用改。** MagicDNS 名由设备名决定：新 Mac 的 Tailscale 设备名设为与旧机相同（例如 `macbook-air`）、并从后台删掉旧设备，域名保持不变，手机端 URL 无需改动。

若两台机同时在线同名，Tailscale 会自动改名成 `macbook-air-1`，域名就变了——所以换机顺序是：**先删旧设备，再用同名加新设备**。

## 四、命令速查

| 用途 | 命令 |
|---|---|
| 最新验证码 | `python3 ~/.zcode/workspace/default/sms-bridge/smscode.py` |
| 按服务筛选 | `python3 .../smscode.py google`（中文如 `淘宝` 也行） |
| 等新码（自动化用） | `python3 .../smscode.py --wait 90 google` |
| 复制到剪贴板 | 加 `--copy` |
| 看详情 | 加 `--json` |
| 列出最近短信 | `python3 .../smscode.py --list` |
| 装/重装服务 | `bash .../install.sh` |
| 卸载 | `bash .../uninstall.sh` |
| 日志 | 目录内 `server.log` / `server.err.log` |

给 AI Agent 用的典型流程：填手机号 → 点「发送验证码」→ `smscode.py --wait 90 <服务名>` → 填入返回的码。

## 五、HTTP 接口

除 `/healthz` 外都需要 token（`?token=` 或 `X-Token` 头）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/push?token=` | 手机推送入口，返回 `{"ok":true,"code":"123456"}` |
| GET | `/latest?token=&keyword=&within=&since=` | 取最新一条匹配记录 |
| GET | `/list?token=&limit=` | 最近记录 |
| GET | `/setup?token=` | 返回本机应填的手机端 Webhook 地址（自检用） |
| GET | `/healthz` | 免鉴权健康检查 |

## 六、安全

- 服务监听 `0.0.0.0:8787`，但 `100.x` 是 Tailscale 保留网段，只有自己 tailnet 内设备可达，公网不可达；访问仍需 token（`.token`，权限 600）。
- 短信内容走 WireGuard 端到端加密，不经过第三方服务器；**只存内存**（上限 200 条、1 小时过期），不落盘、不外发。
- token 泄露处置：改 `.token` 后 `bash install.sh` 重启服务，同步更新手机端 URL。

## 七、排错

收不到码按顺序查：

1. 手机 Tailscale 是否 Connected（下拉通知栏看 VPN 图标）
2. 短信转发器 App 是否被系统杀掉（点开确认通道/规则开关还在）
3. 通道点「测试」后，`smscode.py --list` 有没有新记录
4. Mac 上 `Tailscale status` 里手机是否在列
5. `server.err.log` 有没有报错
6. `curl -s http://127.0.0.1:8787/healthz` 是否返回 `{"ok":true}`

手机重启后失效是国产 ROM 杀后台老问题：两个 App 都要「自启动 + 省电无限制」，隔几周手动点开一次。

邮箱验证码不在本方案范围（那是 IMAP 的活）。
