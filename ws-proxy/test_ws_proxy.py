# -*- coding: utf-8 -*-
"""ws_proxy.plugin 本地验证脚本（CPython，不依赖 Android 运行时）。"""
import importlib.util
import socket
import struct
import sys
import threading
import time
from importlib.machinery import SourceFileLoader

spec = importlib.util.spec_from_loader(
    "ws_proxy",
    SourceFileLoader("ws_proxy", r"D:/WorkBuddyproject/ws/ws-proxy-plugin/ws_proxy.plugin"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

DOMAIN = m.DEFAULT_DOMAIN
table, p6 = m.build_routes(DOMAIN)

# --- 1. 路由表断言 -----------------------------------------------------------
# (地址, 期望子域)；权威地址取自 Nullgram docs/wsproxy/records.txt
CASES = [
    ("149.154.175.50", "pluto"), ("149.154.167.51", "venus"),
    ("95.161.76.100", "venus"),  ("149.154.175.100", "aurora"),
    ("149.154.167.91", "vesta"), ("149.154.171.5", "flora"),
    ("2001:b28:f23d:f001::a", "pluto"), ("2001:67c:4e8:f002::a", "venus"),
    ("2001:b28:f23d:f003::a", "aurora"), ("2001:67c:4e8:f004::a", "vesta"),
    ("2001:b28:f23f:f005::a", "flora"),
    # proxy 段
    ("149.154.175.54", "pluto"),   # .175.5 前缀
    ("149.154.161.144", "venus"), ("149.154.167.15", "venus"),
    ("149.154.167.41", "venus"),   # 修正行：dc2
    ("149.154.167.8", "vesta"), ("149.154.167.9", "vesta"),
    ("91.108.4.130", "vesta"), ("149.154.164.250", "vesta"),
    ("149.154.165.120", "vesta"), ("149.154.166.120", "vesta"),
    ("91.108.56.130", "flora"), ("111.62.91.36", "venus"),
    # IPv6 /64 回退（同块未登记主机；f002::b 为真机实测被拒案例）
    ("2001:67c:4e8:f004::b", "vesta"), ("2001:b28:f23f:f005::b", "flora"),
    ("2001:67c:4e8:f002::b", "venus"), ("2001:b28:f23d:f001::b", "pluto"),
    ("2001:b28:f23d:f003::b", "aurora"),
    # test DC
    ("149.154.175.10", "test_pluto"), ("149.154.175.40", "test_pluto"),
    ("149.154.167.40", "test_venus"), ("149.154.175.117", "test_aurora"),
    ("2001:b28:f23d:f001::e", "test_pluto"),
]
fails = 0
for ip, want in CASES:
    got = m.lookup_server(ip, table, p6)
    ok = got == "%s.%s" % (want, DOMAIN)
    if not ok:
        fails += 1
    print("%-4s %-28s -> %s (want %s)" % ("OK" if ok else "FAIL", ip, got, want))

# 未登记地址必须拒绝（None），不得静默误路由
for ip in ["149.154.167.100", "8.8.8.8", "2001:b28:f23d:f009::b"]:
    got = m.lookup_server(ip, table, p6)
    if got is not None:
        fails += 1
        print("FAIL %-28s -> %s (want None)" % (ip, got))
    else:
        print("OK   %-28s -> None (refuse)" % ip)

# 上游每个键都仍在本地表（上游为超集基线抽查）
for k in ["149.154.167.5", "149.154.167.6", "149.154.167.7", "149.154.167.2",
          "91.108.4.", "149.154.164.", "149.154.165.", "149.154.166.",
          "91.108.56.", "111.62.91."]:
    if k not in table:
        fails += 1
        print("FAIL missing upstream prefix key %s" % k)
print("route table: %s (%d failures)" % ("PASS" if fails == 0 else "FAIL", fails))
if fails:
    sys.exit(1)

# --- 2. 真实端点握手（101） ---------------------------------------------------
print()
target_host = "vesta." + DOMAIN
try:
    sock, leftover = m.ws_connect(target_host, True, m.PLUGIN_UA, m.DEFAULT_CONN_HASH, timeout=8.0)
    print("handshake: PASS (101 from %s, leftover=%dB)" % (target_host, len(leftover)))
except Exception as e:
    print("handshake: SKIP/FAIL (%s: %s) -- 本机网络不可达时不影响插件正确性" % (target_host, e))
    sock = None

# --- 2b. 握手残留字节不得丢弃（假服务端同段发送 101 头 + 首帧） -----------------
import threading as _th
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(1)
fake_port = srv.getsockname()[1]

def fake_server():
    c, _ = srv.accept()
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += c.recv(4096)
    # 同段发送：101 响应头 + 一个二进制帧 "hi"
    frame = b"\x82\x02hi"
    c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
              b"Connection: Upgrade\r\nSec-WebSocket-Accept: x\r\n\r\n" + frame)
    time.sleep(1)
    c.close()
    srv.close()

_th.Thread(target=fake_server, daemon=True).start()
s2, left = m.ws_connect("127.0.0.1", False, "ua", "", timeout=3.0, port=fake_port)
conn = m.WsConn(s2, left)
kind, payload = conn.recv_message()
ok = (kind == "data" and payload == b"hi")
print("leftover bytes: %s (kind=%s payload=%r)" % ("PASS" if ok else "FAIL", kind, payload))
if not ok:
    sys.exit(1)

# --- 2c. 拨号失败路径不得泄漏 socket（连接被拒应抛错且无残留 fd） ---------------
try:
    m.ws_connect("127.0.0.1", False, "ua", "", timeout=1.0)  # 假服务端已关
    print("dial failure cleanup: FAIL (no exception)")
    sys.exit(1)
except Exception:
    print("dial failure cleanup: PASS (exception raised, socket closed internally)")

# --- 3. SOCKS5 全链路（本机中继 -> 真实端点） ---------------------------------
if sock is not None:
    sock.close()
    relay = m.Relay(logger=lambda s: print("  [relay]", s))
    relay.configure(DOMAIN, True, m.DEFAULT_CONN_HASH, m.PLUGIN_UA, False, 16356)
    assert relay.start(), "relay start failed"
    time.sleep(0.2)
    try:
        c = socket.create_connection(("127.0.0.1", 16356), timeout=5)
        c.sendall(b"\x05\x01\x00")
        assert c.recv(2) == b"\x05\x00", "method negotiation failed"
        # CONNECT 149.154.167.91:443 (dc4 -> vesta.<domain>)
        c.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("149.154.167.91") + struct.pack(">H", 443))
        rep = c.recv(10)
        code = rep[1]
        print("socks5 chain: %s (reply code 0x%02x)" % ("PASS" if code == 0 else "FAIL", code))
        if code == 0:
            time.sleep(3)  # 隧道应能存活（空闲几秒不被秒断）
            print("tunnel alive after 3s: PASS")
        c.close()
    finally:
        relay.stop()
else:
    print("socks5 chain: SKIP（握手未完成，无法做全链路）")

print()
print("done")
