#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sms-bridge 接收端服务。

手机端 SmsForwarder 把新短信 POST 到 /push，本服务提取验证码并按时间窗提供查询。
接口：POST /push（写入）、GET /latest（查询）、GET /list（最近记录）、GET /healthz（免鉴权）。
除 /healthz 外都需要 token（.token 文件，install.sh 生成）。只监听 8787 端口，供局域网手机推送。

收到的短信只保存在内存里（上限 200 条、1 小时过期），不落盘、不外发。
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(BASE_DIR, ".token")
PORT = int(os.environ.get("SMSBRIDGE_PORT", "8787"))
MAX_AGE = 3600         # 记录保留上限：1 小时
DEFAULT_WITHIN = 600   # /latest 默认时间窗：10 分钟
MAX_ITEMS = 200

_lock = threading.Lock()
_items = []  # 收到的短信记录，最新在尾部

BODY_KEYS = ("body", "content", "sms", "smsContent", "text", "message", "msg",
             "短信内容", "消息内容")
SENDER_KEYS = ("from", "address", "sender", "origin", "来源号码",
               "phone", "mobile", "sim", "simInfo", "卡槽信息")

KEYWORD = r"(?:验证码|校验码|动态码|动态密码|确认码|识别码|otp|code|pin)"


def read_token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def extract_code(text):
    """从短信原文提取验证码：带关键词的优先，其次取独立的 4-8 位数字组。"""
    if not text:
        return ""
    m = re.search(KEYWORD + r"[^0-9A-Za-z]{0,15}([0-9]{4,8})", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{4,8})[^0-9A-Za-z]{0,15}" + KEYWORD, text, re.I)
    if m:
        return m.group(1)
    for m in re.finditer(r"(?<![0-9])([0-9]{4,8})(?![0-9])", text):
        before = text[max(0, m.start(1) - 2):m.start(1)]
        after = text[m.end(1):m.end(1) + 3]
        if re.search(r"(?:[¥$￥]|共|扣|付|满)\s*$", before):
            continue
        if re.match(r"\s*(?:分|秒|天|月|年|元|块|折|小时|个|号)", after):
            continue
        return m.group(1)
    return ""


def signature_of(text):
    m = re.search(r"【([^】]{1,20})】", text or "")
    return m.group(1) if m else ""


def pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v:
            return str(v).strip()
    return ""


def parse_push(raw_bytes, qs):
    """兼容多种推送格式：JSON、表单/URL 参数、纯文本。"""
    text = raw_bytes.decode("utf-8", "replace").strip()
    data = {}
    if text[:1] == "{":
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                data = j
        except ValueError:
            pass
    if not data and "=" in text:
        data = {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items() if v}
    for k in ("body", "from", "content", "sms", "text", "message", "msg"):
        v = qs.get(k, [""])[0]
        if v and k not in data:
            data[k] = v
    body = pick(data, BODY_KEYS) or text
    sender = pick(data, SENDER_KEYS)
    ts = pick(data, ("time", "timestamp", "date", "接收时间"))
    return body[:500], sender[:64], ts[:40]


def match_latest(items, keyword, since, within, now):
    kw = keyword.lower()
    best = None
    for x in items:
        if now - x.get("received_at", 0) > within:
            continue
        if since and x.get("received_at", 0) < since:
            continue
        if kw:
            hay = (x.get("sender", "") + " " + x.get("body", "")).lower()
            if kw not in hay:
                continue
        if best is None or x["received_at"] > best["received_at"]:
            best = x
    return best


class Handler(BaseHTTPRequestHandler):
    server_version = "smsbridge/1.0"

    def log_message(self, fmt, *args):
        pass  # 访问日志静默，避免刷屏

    def _send(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _auth(self, qs):
        want = read_token()
        if not want:
            return False
        got = qs.get("token", [""])[0] or self.headers.get("X-Token", "")
        return got == want

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path != "/push" or not self._auth(qs):
            self._send(403, {"ok": False, "error": "forbidden（token 不对或路径不存在）"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 64 * 1024:
            self._send(413, {"ok": False, "error": "payload too large"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        body, sender, ts = parse_push(raw, qs)
        now = time.time()
        rec = {
            "received_at": round(now, 2),
            "time": time.strftime("%m-%d %H:%M:%S"),
            "phone_time": ts,
            "sender": sender,
            "signature": signature_of(body),
            "code": extract_code(body),
            "body": body,
        }
        with _lock:
            global _items
            last = _items[-1] if _items else None
            if last and last.get("sender") == sender and last.get("body") == body \
                    and now - last["received_at"] < 120:
                _items[-1] = rec  # 同一条短信的重复推送，覆盖即可
            else:
                _items.append(rec)
            _items = [x for x in _items if now - x["received_at"] <= MAX_AGE]
            _items = _items[-MAX_ITEMS:]
        print("[push] %s from=%s code=%s" % (rec["time"], sender or "?", rec["code"] or "-"),
              flush=True)
        self._send(200, {"ok": True, "code": rec["code"]})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        path = parsed.path
        if path == "/healthz":
            self._send(200, {"ok": True, "service": "sms-bridge"})
            return
        if path == "/setup":
            # 给手机浏览器访问：直接返回要填进 SmsForwarder 的配置，避免手工复制出错
            token = read_token()
            if not token:
                self._send(500, {"ok": False, "error": "token 未生成，先运行 install.sh"})
                return
            host = self.headers.get("Host") or "127.0.0.1:8787"
            self._send(200, {
                "ok": True,
                "webhook_url": "http://%s/push?token=%s" % (host, token),
                "method": "POST",
                "web_params": '{"from":"[from]","body":"[msg]","time":"[receive_time]"}',
            })
            return
        if path not in ("/latest", "/list"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        if not self._auth(qs):
            self._send(403, {"ok": False, "error": "forbidden（token 不对）"})
            return
        now = time.time()
        with _lock:
            items = [x for x in _items if now - x["received_at"] <= MAX_AGE]
        if path == "/latest":
            try:
                within = min(int(qs.get("within", [DEFAULT_WITHIN])[0]), MAX_AGE)
            except ValueError:
                within = DEFAULT_WITHIN
            try:
                since = float(qs.get("since", [0])[0])
            except ValueError:
                since = 0.0
            keyword = qs.get("keyword", [""])[0].strip()
            hit = match_latest(items, keyword, since, within, now)
            if not hit:
                self._send(200, {"found": False, "keyword": keyword})
            else:
                self._send(200, dict(hit, found=True,
                                     age_seconds=round(now - hit["received_at"], 1)))
        else:  # /list
            try:
                limit = min(int(qs.get("limit", [20])[0]), 100)
            except ValueError:
                limit = 20
            self._send(200, {"items": list(reversed(items[-limit:]))})


def main():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(f"端口 {PORT} 被占用，sms-bridge 可能已在运行", flush=True)
        sys.exit(1)
    print(f"sms-bridge 已启动，监听 0.0.0.0:{PORT}（数据目录 {BASE_DIR}）", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
