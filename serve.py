#!/usr/bin/env python3
"""双栈启动器：同时监听 IPv4(0.0.0.0) 与 IPv6([::]) 的服务端口。

uvicorn --host '::' 在本机（net.ipv6.bindv6only=1）只收 IPv6，局域网 IPv4
访问会被拒，故在此显式创建两个 socket 交给 uvicorn。
"""
import asyncio
import json
import socket

import uvicorn

from server import app

with open("config.json", encoding="utf-8") as f:
    PORT = json.load(f).get("port", 8000)

sockets = []
s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s4.bind(("0.0.0.0", PORT))
s4.listen(2048)
sockets.append(s4)
try:
    s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # 显式 v6-only：bindv6only=0 的系统上，"::" 双栈语义会与自己先绑的 0.0.0.0 冲突
    s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s6.bind(("::", PORT))
    s6.listen(2048)
    sockets.append(s6)
except OSError as e:
    print(f"[startup] IPv6 绑定失败，仅 IPv4 监听：{e}", flush=True)

config = uvicorn.Config(app, log_level="info")
server = uvicorn.Server(config)
asyncio.run(server.serve(sockets=sockets))
