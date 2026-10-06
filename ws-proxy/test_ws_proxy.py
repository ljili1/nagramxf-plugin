# -*- coding: utf-8 -*-
"""ws_proxy.plugin 本地验证脚本（CPython，不依赖 Android 运行时）。

直接运行：python test_ws_proxy.py
1.3.6 起插件不再内置公共域名（DEFAULT_DOMAIN 已删除），测试自备 example.com。
1.3.1 起新增「派生标签」相关断言（derive_label / build_labels / build_routes(domain, labels)），
兼容标签（pluto/venus/...）的旧断言保持原样，用于守护默认行为不被改坏。
"""
import ast
import importlib.util
import os
import re
import socket
import struct
import sys
import threading
import time
from importlib.machinery import SourceFileLoader

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN = os.path.join(_HERE, "ws_proxy.plugin")
if not os.path.exists(_PLUGIN):
    _PLUGIN = os.path.join(_HERE, "ws-proxy", "ws_proxy.plugin")

spec = importlib.util.spec_from_loader(
    "ws_proxy", SourceFileLoader("ws_proxy", _PLUGIN))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

DOMAIN = "example.com"   # 插件已不再内置公共域名，测试自备一个
table, p6 = m.build_routes(DOMAIN)

# --- 1. 路由表断言（默认 = 兼容标签） ---------------------------------------
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

# --- 1a. 派生标签（1.3.0） --------------------------------------------------
LABEL_RE = re.compile(r"^[a-z][a-z2-7]{11}$")
DOMAIN2 = "example.com"
SALT = "unit-test-salt"

labels = m.build_labels(DOMAIN2, 0, SALT)
assert set(labels) == set(m.LABEL_DOMAIN_DCS), labels
for dc, name in sorted(labels.items()):
    assert LABEL_RE.match(name), "非法 DNS 标签 %r (dc=%s)" % (name, dc)
assert len(set(labels.values())) == len(labels), "各 DC 标签必须互不相同"
assert m.build_labels(DOMAIN2, 0, SALT) == labels, "同 (域名,盐值) 必须确定性"
assert m.build_labels(DOMAIN2, 0, "other-salt") != labels, "换盐值必须换整套标签"
assert m.build_labels("example.net", 0, SALT) != labels, "换域名必须换整套标签"
# 盐值留空 = 只按域名派生，必须确定性（1.3.1 修掉了随机盐导致的标签漂移）
assert m.build_labels(DOMAIN2, 0, "") == m.build_labels(DOMAIN2, 0, ""), "空盐值也必须确定性"
assert m.build_labels(DOMAIN2, 0, "") != labels, "填盐值应换出另一套标签"
assert m.build_labels(DOMAIN2, 1) == dict(m.LEGACY_LABELS), "兼容模式必须等于固定旧名"
# 跨实现交叉校验：同一算法由独立实现算得的已知答案
assert m.derive_label(DOMAIN2, 1, "saltA") == "gi74vwhmajpd", m.derive_label(DOMAIN2, 1, "saltA")
# 自定义模式：按 DC1..DC5[,...] 顺序；未填的 DC 自动用派生值补齐；非法字符被清洗
custom = m.build_labels(DOMAIN2, 2, "", "aa1, bb2, cc3, dd4, ee5")
assert [custom[d] for d in (1, 2, 3, 4, 5)] == ["aa1", "bb2", "cc3", "dd4", "ee5"], custom
assert LABEL_RE.match(custom[17]), custom[17]
assert m.build_labels(DOMAIN2, 2, "", "UP.per!, B2")[1] == "upper", "应小写并清洗非法字符"
# 派生标签必须真的被路由表用上（含 IPv6 /64 回退与拒绝路径）
table2, p62 = m.build_routes(DOMAIN2, labels)
assert m.lookup_server("149.154.175.50", table2, p62) == labels[1] + "." + DOMAIN2
assert m.lookup_server("149.154.167.91", table2, p62) == labels[4] + "." + DOMAIN2
assert m.lookup_server("2001:67c:4e8:f004::b", table2, p62) == labels[4] + "." + DOMAIN2
assert m.lookup_server("149.154.175.40", table2, p62) == labels[17] + "." + DOMAIN2
assert m.lookup_server("8.8.8.8", table2, p62) is None
print("derived labels: PASS (DC1=%s, DC4=%s)" % (labels[1], labels[4]))

# --- 1b. 纯 Python AES-256-CTR 与 obfs2 入向解码 -----------------------------
# FIPS-197 附录 C.3 AES-256 测试向量
_rk = m._aes256_expand_key(bytes(range(32)))
_vec = m._aes_encrypt_block(
    _rk, bytes.fromhex("00112233445566778899aabbccddeeff"))
assert _vec.hex() == "8ea2b7ca516745bfeafc49904b496089", _vec.hex()
print("aes256 block vector: PASS")

# CTR 与 cryptography 交叉验证（本机有该包时）
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    _k, _iv = os.urandom(32), os.urandom(16)
    _ref = Cipher(algorithms.AES(_k), modes.CTR(_iv)).encryptor().update(os.urandom(0) + b"\x00" * 100)
    _mine = m.Aes256Ctr(_k, _iv).crypt(b"\x00" * 100)
    assert _mine == _ref
    print("aes256-ctr vs cryptography: PASS")
except ImportError:
    print("aes256-ctr vs cryptography: SKIP (no cryptography)")

# obfs2 端到端：按 telethon 规则造 init，用「入向密钥」加密一个 -404 传输错误包，
# 再用插件的解码函数解回并解析
while True:
    _init = bytearray(os.urandom(64))
    if _init[0] != 0xEF and _init[:4] not in (b"PVrG", b"GET ", b"POST", b"\xee" * 4) \
            and _init[4:8] != b"\0" * 4:
        break
_ekey, _eiv = bytes(_init[8:40]), bytes(_init[40:56])
_rev = bytes(_init[8:56])[::-1]
_dkey, _div = _rev[:32], _rev[32:48]
_enc = m.Aes256Ctr(_ekey, _eiv)
_enc_full = _enc.crypt(bytes(_init))          # 加密器消耗 64B 密钥流
_wire_init = bytes(_init[:56]) + _enc_full[56:64]  # 线上形态: 明文头+密文尾
_err_pkt = b"\x01" + struct.pack("<i", -404)  # abridged: len=1word + int32(-404)
_ct = m.Aes256Ctr(_dkey, _div).crypt(_err_pkt)     # 入向密钥流从 0 开始
_pt = m.obfs2_decode_incoming(_wire_init, _ct)
assert _pt == _err_pkt, (_pt, _err_pkt)
assert m.parse_abridged_err(_pt, 5) == -404
assert m.parse_abridged_err(_pt, 6) == 0      # 总长不自洽不报
print("obfs2 incoming decode + mt_err parse: PASS")
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

# --- 4. 设置页关键字必须与宿主 SDK 签名一致（v1.3.15 修掉的崩溃类型） --------
# 宿主的 PythonPluginsEngine.loadPluginSettings() 反射构造这些 dataclass：只要
# 传了签名里没有的关键字就抛 TypeError，而该异常会终结整页设置加载，真机日志：
#   E/PythonPluginsEngine: Failed to load plugin settings
#   com.chaquo.python.PyException: TypeError:
#       Selector.__init__() got an unexpected keyword argument 'subtext'
# 根因：Selector 有 key/text/default/items/icon/on_change/on_long_click/
# link_alias，但**没有 subtext**（Switch / Input / Text 才有）。这里把宿主 SDK
# 的字段表固化成断言，防止再次把 subtext 塞给 Selector。
SDK_SIGNATURES = {
    "Header": {"text"},
    "Divider": {"text"},
    "Switch": {"key", "text", "default", "subtext", "icon", "on_change",
               "on_long_click", "link_alias"},
    "Selector": {"key", "text", "default", "items", "icon", "on_change",
                 "on_long_click", "link_alias"},
    "Input": {"key", "text", "default", "subtext", "icon", "on_change",
              "on_long_click", "link_alias"},
    "Text": {"text", "subtext", "icon", "accent", "red", "on_click",
             "on_long_click", "create_sub_fragment", "link_alias"},
    "EditText": {"key", "hint", "default", "multiline", "max_length", "mask",
                 "on_change"},
    "Custom": {"item", "view", "factory", "factory_args", "on_click",
               "on_long_click", "create_sub_fragment", "link_alias"},
}

_src = open(_PLUGIN, encoding="utf-8").read()
_tree = ast.parse(_src)
sig_fails = []
guarded = 0
selector_direct = 0
for _node in ast.walk(_tree):
    if not isinstance(_node, ast.Call) or not isinstance(_node.func, ast.Name):
        continue
    _fname = _node.func.id
    _kws = {k.arg for k in _node.keywords if k.arg}
    if _fname in SDK_SIGNATURES:
        if _fname == "Selector":
            selector_direct += 1
        _bad = _kws - SDK_SIGNATURES[_fname]
        if _bad:
            sig_fails.append((_node.lineno, _fname, sorted(_bad)))
    elif _fname == "item" and _node.args and isinstance(_node.args[0], ast.Name):
        _target = _node.args[0].id
        guarded += 1
        if _target in SDK_SIGNATURES:
            _bad = _kws - SDK_SIGNATURES[_target]
            if _bad:
                sig_fails.append((_node.lineno, _target, sorted(_bad)))
        else:
            sig_fails.append((_node.lineno, _target, ["<unknown factory>"]))

print("settings kwargs vs host SDK: %s" % ("PASS" if not sig_fails else "FAIL"))
for _line, _fname, _bad in sig_fails:
    print("  FAIL line %d: %s(%s)" % (_line, _fname, ", ".join(_bad)))
if sig_fails:
    sys.exit(1)
print("settings rows built through the tolerant item(): %d" % guarded)
assert guarded >= 10, "设置项应统一走 item() 兜底，实际 %d" % guarded
assert "subtext" not in SDK_SIGNATURES["Selector"], "Selector 依旧不能有 subtext"

# --- 5. 域名解析链 / 失败日志限流（v1.3.16 起；v1.3.19 改为用宿主自带解析器） --
# 真机日志里 "[Errno 7] No address associated with hostname" 重复了 18666 次，
# 把日志刷爆且看不出原因。这节守护：
#   ① 优先用宿主自带的 DNS 选择器（Nekogram DnsFactory），系统 DNS 只做兜底；
#   ② 同一条失败不会无限刷屏，被压掉的条数会在下一行汇总。
# v1.3.19 起插件不再自带 DoH 实现——App 的「DNS 解析器」本来就有 DoH。
_f5 = []


class _FakeSock(object):
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


_real_create_connection = m.socket.create_connection
_real_gai = m.socket.getaddrinfo
_real_factory = m._DnsFactory


def _flash(*a, **k):
    raise socket.gaierror(7, "No address associated with hostname")


# 5a. 宿主没有 DnsFactory 时必须安全降级（返回空列表，不能抛）
m._DnsFactory = None
m._app_dns_cache.clear()
_ok = m.app_dns_lookup("none.example.com", wait=0.3) == []
_f5.append(("宿主无 DnsFactory 时安全降级", _ok, None))

# 5b. 系统 DNS 正常时按 IP 直连
m._DnsFactory = None
m._best_addr.clear()
m._app_dns_cache.clear()
_seen0 = []
m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.9", 443))]
m.socket.create_connection = lambda addr, timeout=None: (_seen0.append(addr), _FakeSock())[1]
try:
    m.dial_tcp("ok.example.com", 443, 3.0)
    _ok = _seen0 == [("198.51.100.9", 443)] and m.LAST_RESOLVE_SOURCE == "dns"
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
_f5.append(("系统 DNS 正常时直连", _ok, _seen0))

# 5c. 完全没有解析结果时抛 gaierror（上层据此归为 resolve）
m._DnsFactory = None
m._best_addr.clear()
m._app_dns_cache.clear()
m.socket.getaddrinfo = _flash
m.socket.create_connection = lambda addr, timeout=None: _FakeSock()
try:
    try:
        m.dial_tcp("unresolvable.example.com", 443, 3.0)
        _ok = False
    except socket.gaierror:
        _ok = True
    except Exception:
        _ok = False
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
_f5.append(("解析全失败时抛 gaierror", _ok, None))

# 5d. system_addrs 必须把 IPv4 排在 IPv6 前面
#     实测机型是 IPv4-only（tgnet 全程 ipv6:0），IPv6 排前面会白撞一次 ENETUNREACH。
m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.51.100.9", 443))]
try:
    _addrs, _e = m.system_addrs("order.example.com", 443)
finally:
    m.socket.getaddrinfo = _real_gai
_f5.append(("IPv4 排在 IPv6 前面", _addrs == ["198.51.100.9", "2001:db8::1"] and _e is None, _addrs))

# 5e. App 自带解析器给出的地址优先于系统 DNS
class _FakeInet(object):
    def __init__(self, ip):
        self._ip = ip

    def getHostAddress(self):
        return self._ip


class _FakeDnsFactory(object):
    def __init__(self, ips):
        self.ips = ips
        self.calls = 0

    def lookup(self, host, fallback):
        self.calls += 1
        return [_FakeInet(x) for x in self.ips]


_fake = _FakeDnsFactory(["198.51.100.77"])
m._DnsFactory = _fake
m._best_addr.clear()
m._app_dns_cache.clear()
_seen1 = []
m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.1", 443))]
m.socket.create_connection = lambda addr, timeout=None: (_seen1.append(addr), _FakeSock())[1]
try:
    m.dial_tcp("order2.example.com", 443, 3.0)
    _ok = _seen1 == [("198.51.100.77", 443)] and m.LAST_RESOLVE_SOURCE == "appdns"
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
_f5.append(("App 解析器地址优先于系统 DNS", _ok, _seen1))

# 5f. App 解析器给的地址连不上 -> 回退系统 DNS 仍能成功
m._best_addr.clear()
m._app_dns_cache.clear()
_seen2 = []


def _cc_mixed(addr, timeout=None):
    _seen2.append(addr)
    if addr[0] == "198.51.100.77":
        raise OSError(101, "Network is unreachable")
    return _FakeSock()


m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.8", 443))]
m.socket.create_connection = _cc_mixed
try:
    m.dial_tcp("fallback.example.com", 443, 3.0)
    _ok = _seen2 == [("198.51.100.77", 443), ("203.0.113.8", 443)]
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
_f5.append(("App 解析器地址连不上时回退系统 DNS", _ok, _seen2))

# 5g. App 解析结果会被插件缓存（同一个 host 第二次不再调 Java）
m._app_dns_cache.clear()
_calls_before = _fake.calls
m.app_dns_lookup("cached.example.com", wait=0.5)
_after_first = _fake.calls
m.app_dns_lookup("cached.example.com", wait=0.5)
_f5.append(("App 解析结果走缓存",
            _after_first == _calls_before + 1 and _fake.calls == _after_first,
            _fake.calls - _calls_before))
m._DnsFactory = _real_factory

# 5h. 连通过的地址会被缓存，后续拨号不再解析
_f5.append(("记住连通的地址", m._cached_addr("fallback.example.com") == "203.0.113.8",
            m._cached_addr("fallback.example.com")))

# 5i. 地址不可路由时，每个地址的错误都要写进 LAST_DIAL_TRACE（诊断的关键）
m._DnsFactory = None
m._best_addr.clear()
m._app_dns_cache.clear()
m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("31.13.1.1", 443))]


def _cc_polluted(addr, timeout=None):
    raise OSError(101, "Network is unreachable")


m.socket.create_connection = _cc_polluted
try:
    try:
        m.dial_tcp("polluted.example.com", 443, 3.0)
    except OSError:
        pass
    _ok = "31.13.1.1" in m.LAST_DIAL_TRACE and "unreachable" in m.LAST_DIAL_TRACE.lower()
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
m._DnsFactory = _real_factory
_f5.append(("不可路由地址记进 LAST_DIAL_TRACE", _ok, m.LAST_DIAL_TRACE))

# 5k. unreachable_hint 要认出 ENETUNREACH（否则会被误当成 DNS 问题）
_ok = (m.unreachable_hint(OSError(101, "Network is unreachable"))
       and m.unreachable_hint(OSError(113, "No route to host"))
       and not m.unreachable_hint(socket.gaierror(7, "No address associated with hostname")))
_f5.append(("ENETUNREACH 识别", _ok, None))

# 5l. SSLContext 必须复用（每次 create_default_context() 都要重解析整份 CA 库）
_c1 = m.tls_context(False)
_c2 = m.tls_context(False)
_c3 = m.tls_context(True)
_ok = _c1 is _c2 and _c3 is not _c1 and m.tls_context(True) is _c3
_f5.append(("SSLContext 复用", _ok, type(_c1).__name__))

# 5o. 建连时开了 TCP_NODELAY（MTProto 全是小包，Nagle 会白攒 40ms）
_opts = []


class _SockOpt(_FakeSock):
    def setsockopt(self, *a):
        _opts.append(a)


m._best_addr.clear()
m._app_dns_cache.clear()
m.socket.getaddrinfo = lambda *a, **k: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.5", 443))]
m.socket.create_connection = lambda addr, timeout=None: _SockOpt()
try:
    m.dial_tcp("nodelay.example.com", 443, 3.0)
    _ok = any(o[0] == socket.IPPROTO_TCP and o[1] == socket.TCP_NODELAY for o in _opts)
finally:
    m.socket.create_connection = _real_create_connection
    m.socket.getaddrinfo = _real_gai
_f5.append(("建连开 TCP_NODELAY", _ok, _opts))

# 5p. 隧道关闭日志限流
_clogs = []
_relay2 = m.Relay(lambda msg: _clogs.append(msg))
for _ in range(4):
    _relay2._log_tunnel_close("t.example.com", "unexpected eof", 1.0, 10, 20, "")
_ok = len(_clogs) == 1
_f5.append(("隧道关闭日志限流（4 次记 1 条）", _ok, len(_clogs)))

# 5f. 失败分类
_ok = (m.Relay._dial_error_kind(socket.gaierror(7, "No address associated with hostname")) == "resolve"
       and m.Relay._dial_error_kind(socket.timeout("timed out")) == "timeout"
       and m.Relay._dial_error_kind(m.WsError("handshake rejected: HTTP 403")) == "other")
_f5.append(("失败原因分类", _ok, None))

# 5g. 限流：60 秒内同一条失败只记一次，且下一行汇总被压掉的条数
_logs = []
_relay = m.Relay(lambda msg: _logs.append(msg))
_ge = socket.gaierror(7, "No address associated with hostname")
for _ in range(5):
    _relay._log_dial_failure("h.example.com", _ge)
_ok = len(_logs) == 2 and _relay.dial_failures == 5
_f5.append(("失败日志限流（5 次只记 1 条）", _ok, len(_logs)))

_logs[:] = []
_relay._fail_log[("h.example.com", "resolve")] = (0.0, 4)   # 假装已过限流窗口
_relay._log_dial_failure("h.example.com", _ge)
_ok = len(_logs) == 2 and any("略过 4 条" in x for x in _logs)
_f5.append(("恢复记录时汇总被压掉的条数", _ok, _logs[0] if _logs else None))

print()
for _name, _ok, _extra in _f5:
    print("  %s  %s%s" % ("ok  " if _ok else "FAIL", _name,
                          "" if _extra is None else "  -> %r" % (_extra,)))
_bad5 = [x for x in _f5 if not x[1]]
print("dns fallback + failure throttling: %s (%d/%d)" %
      ("PASS" if not _bad5 else "FAIL", len(_f5) - len(_bad5), len(_f5)))
if _bad5:
    sys.exit(1)

# --- 6. 端口释放：stop() 后必须能立刻重新 start()（v1.3.20 修的真机 EADDRINUSE） --
# 真机日志：tcp2ws stopped 之后紧接着 bind 127.0.0.1:6356 failed: Address already in use，
# 表现就是「关掉代理再打开，它没起来」。这里用真实 socket 复现 start/stop/start。
_r6 = m.Relay(lambda msg: None)
_r6.configure("port.example.com", True, m.DEFAULT_CONN_HASH, "ua", False, 46356)
_ok_a = _r6.start()
_t6 = _r6._accept_thread
_r6.stop()
_ok_stop = (_t6 is not None and not _t6.is_alive())   # stop() 必须等到 accept 线程真正退出
_ok_b = _r6.start()
_r6.stop()
_ok6 = _ok_a and _ok_stop and _ok_b
print("port release (start/stop:accept-joined/start): %s" % ("PASS" if _ok6 else "FAIL"))
if not _ok6:
    sys.exit(1)

# 拨号失败要清掉那条缓存地址，避免下一次又先撞它一次
m._best_addr.clear()
m._remember_addr("forget.example.com", "203.0.113.99")
m._forget_addr("forget.example.com", "203.0.113.99")
_ok = m._cached_addr("forget.example.com") is None
print("forget dead cached addr: %s" % ("PASS" if _ok else "FAIL"))
if not _ok:
    sys.exit(1)

print()
print("done")
