#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询手机最新短信验证码。

用法：
  smscode                  最新一条验证码（默认 10 分钟内）
  smscode google           只找内容含 google 的（不区分大小写，可中文，如：淘宝）
  smscode --wait 90        触发发送后阻塞等新验证码，最多 90 秒
  smscode --json           输出完整信息（发送方/原文/时间）
  smscode --copy           顺带把验证码复制到剪贴板
  smscode --list           列出最近收到的短信（排查用）

只访问本机 127.0.0.1:8787 的 sms-bridge 服务，不请求任何其他地址。
"""
import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse

BASE_DIR = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
HOST = "127.0.0.1"
PORT = 8787
ALLOWED_PATHS = ("/latest", "/list")


def read_token():
    path = os.path.join(BASE_DIR, ".token")
    if not os.path.isfile(path):
        sys.exit("缺少 .token 文件，请先在 sms-bridge 目录运行 install.sh")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def api(path, params):
    """向本机 sms-bridge 发 GET。主机/端口/路径全部白名单，杜绝任意请求。"""
    if path not in ALLOWED_PATHS or ".." in path:
        sys.exit("非法请求路径：%r" % path)
    params = dict(params)
    params["token"] = read_token()
    qs = urllib.parse.urlencode(params)
    conn = http.client.HTTPConnection(HOST, PORT, timeout=6)
    try:
        conn.request("GET", "%s?%s" % (path, qs))
        resp = conn.getresponse()
        payload = resp.read().decode("utf-8", "replace")
        if resp.status == 403:
            sys.exit("token 校验失败，删除 .token 后重跑 install.sh")
        if resp.status != 200:
            sys.exit("服务返回异常状态 %d" % resp.status)
        return json.loads(payload)
    except (OSError, ValueError):
        sys.exit("连不上本机服务（%s:%d）。先运行 install.sh，或查看 server.err.log" % (HOST, PORT))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="查询手机最新短信验证码")
    ap.add_argument("keyword", nargs="?", default="", help="筛选关键词，如 google、淘宝")
    ap.add_argument("--within", type=int, default=600, help="时间窗（秒），默认 600")
    ap.add_argument("--wait", type=int, default=0, metavar="秒",
                    help="阻塞等待新到的验证码，最多 N 秒")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    ap.add_argument("--copy", action="store_true", help="把验证码复制到剪贴板")
    ap.add_argument("--list", action="store_true", help="列出最近收到的短信")
    a = ap.parse_args()

    if a.list:
        d = api("/list", {"limit": 20})
        items = d.get("items", [])
        if not items:
            print("（还没有收到过任何短信推送）")
            return
        for it in reversed(items):
            who = it.get("signature") or it.get("sender") or "?"
            print(f'{it["time"]}  {who}  code={it.get("code") or "-"}  {it.get("body", "")[:60]}')
        return

    since = time.time() if a.wait else 0
    deadline = time.time() + a.wait
    while True:
        d = api("/latest", {"keyword": a.keyword, "within": a.within, "since": since})
        if d.get("found"):
            if a.json:
                print(json.dumps(d, ensure_ascii=False, indent=2))
            else:
                print(d.get("code", ""))
            if a.copy and d.get("code"):
                subprocess.run(["pbcopy"], input=d["code"].encode(), check=False)
            return
        if time.time() >= deadline:
            msg = "没有找到匹配的验证码"
            if a.wait:
                msg += f"（等了 {a.wait} 秒没收到新短信，检查手机 App、转发规则和 Wi-Fi）"
            sys.exit(msg)
        time.sleep(2)


if __name__ == "__main__":
    main()
