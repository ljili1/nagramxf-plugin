# WS Proxy (tcp2ws) 使用教程 —— 纯 DNS 模式，无需任何服务端

> 对应插件文件：[`ws_proxy.plugin`](./ws_proxy.plugin)（v1.3.15）
> 离线自测：[`test_ws_proxy.py`](./test_ws_proxy.py)（`python test_ws_proxy.py`，无需 Android 环境）
>
> **插件介绍（写在插件里的版本）**：让 Telegram 的流量改走 WebSocket(wss)，绕过部分网络的封锁；
> 纯客户端方案，只需要一个你自己的域名，不需要任何服务器。本文件是详细教程，插件内只保留三步。

---

## TL;DR

1. 装插件 → 设置页「**域名**」里**直接填**你自己的域名（例如 `example.com`，**必填**，没有内置域名）；
2. 点一下「**复制 DNS 记录到剪贴板**」→ 存成 `.txt` → Cloudflare → DNS → Records → **Import**（务必勾选 *Proxy imported DNS records* 橙云）；设置页下方还有个多行文本框可以查看/手动全选；
3. Cloudflare → SSL/TLS → Overview → 加密模式 **Flexible**；
4. 打开「**启用代理**」，再去 Telegram 代理列表里启用它即可用。

> 同样这几步也写在插件文件开头的注释里（插件内是压缩过的三步版；细节、原理、排错都在本文档）。

不需要 Pages、不需要 Workers、不需要 VPS——**只需要一个托管在 Cloudflare 的域名**。

---

## 1. 原理（30 秒）

```
Telegram App ──tgnet──> 插件本机 SOCKS5(127.0.0.1:6356)
                          │  按目标 DC IP 换成标签主机名
                          ▼
        wss://<标签>.<你的域名>/api  ──> Cloudflare 边缘（橙云代理）
                          │  Flexible 模式：CF → 源站走明文 HTTP
                          ▼
        A 记录指向的 Telegram DC :80  ──> MTProto 正常握手
```

- 插件是**纯客户端**：它只做「路由替换 + 把 TCP 字节流装进 WebSocket 二进制帧」；
- 你的域名的 A/AAAA 记录**直接指向 Telegram DC 的 IP**，并开启 Cloudflare 橙云代理，
  于是 Cloudflare 就成了现成的 wss→TCP 中继，**不需要写任何服务端代码**；
- 插件会自动把 `127.0.0.1:6356` 注册进 Telegram 的代理列表并启用。

> 这一机制来自 Nullgram / Nekogram 的 tcp2ws（[`docs/wsproxy`](https://github.com/qwq233/Nullgram/tree/master/docs/wsproxy)、[Nekogram/wsproxy](https://gitlab.com/Nekogram/wsproxy)：*"no servers required"*）。
> 说明：本仓库开发环境无法直连 Telegram DC（DNS 被污染/连接被阻断），所以**上游链路的端到端连通性未在此环境复验**，请在真机上实测。

---

## 2. 安装与自测

| 场景 | 做法 |
|---|---|
| 安装 | 把 `ws_proxy.plugin` 发送到任意聊天 → 点击 → 安装；或 设置 → 插件 → 从文件安装 |
| 升级 | 同上直接覆盖安装；插件设置（域名/盐值等）会保留 |
| 离线自测（PC） | `cd ws-proxy && python test_ws_proxy.py` —— 校验路由表、子域名派生、AES/obfs2、握手残留字节、SOCKS5 全链路（无网络时自动 SKIP） |

---

## 3. 一次性准备

1. 一个域名（几十块钱一年的就行），**NS 托管到 Cloudflare**；
2. 该 zone 里**不要**同时跑其它需要 Full/Strict 的业务（原因见下面 ⚠️）；
3. 想清楚这个域名的用途：**它就是消耗品**，不要用主站域名。

> ⚠️ **Flexible 是 zone 级设置**：改成 Flexible 后，该 zone 下所有站点的「CF → 源站」都会变成明文 HTTP。
> 如果这个 zone 里还有正经网站，请单独用一个只做代理的域名/zone。

---

## 4. 配置步骤

### 4.1 插件设置（设置 → 插件 → WebSocket 代理）

> **「域名」是干什么的？** 插件要把 Telegram 的 5 个数据中心分别对应到一个子域名
> （例如 `abc.example.com`），你在 Cloudflare 里把这些子域名指向 Telegram 的 IP 并开启橙云代理，
> Cloudflare 就顺手成了 wss→TCP 的中继——所以**不需要买服务器**，只需要一个域名。
> 填**最外层域名**（`example.com`）的原因是：Cloudflare 的免费证书是 `*.example.com`，只覆盖一层子域名，
> 这样 5 个子域名都能被同一张证书盖住，也不会把每个子域名单独写进公开的证书透明日志。

| 界面上的项 | 推荐值 | 说明 |
|---|---|---|
| 启用代理 | 开 | 本机监听端口，并把 Telegram 的流量转到你的域名 |
| 域名 | `example.com` | **必填，直接填**。只填域名本身（不要 `http://`、不要带子域名），建议用最外层域名：这样 `*.example.com` 免费证书就能覆盖下面 5 个子域名。**留空 = 代理不启动**并在日志提示 |
| 子域标签 | **自动生成（推荐）** | 三选一：**自动生成（推荐）** / 经典名（`pluto/venus/…`）/ **自定义**；页面会按你所选只显示相关输入框（没立刻变就退出再进一次） |
| 自定义子域名 | 留空 | 只有「子域标签」选**自定义**时才显示。按 `DC1,DC2,DC3,DC4,DC5` 顺序逗号分隔，示例 `aa1`；没写的自动生成 |
| 子域名随机串 | 留空 | 默认空 = 按「域名」算出子域名（重启/重装都不变）。填随机串 = 换另一套子域名（更难被猜），但 DNS 要跟着重配；已有 16 位十六进制是 v1.3.0 残留 |
| 复制 DNS 记录到剪贴板 | — | 点一下即把**完整 zone 记录**写进剪贴板（**换行原样保留**，可直接粘成 `.txt` 上传 Import） |
| DNS 记录（多行文本框） | 自动生成 | 上面按钮复制的内容，可查看、可长按全选手动复制；随「域名 / 子域标签」自动变化 |
| 使用 TLS（wss） | 开 | Cloudflare 部署必须开 |
| 本机端口 | 6356 | 插件在本机监听的 SOCKS5 端口 |
| 跳过证书校验 | 关 | 仅排障用 |
| 代理列表里显示的名字 | `WebSocket 代理` | TG 的代理列表那一行写死显示 `127.0.0.1:端口`，这项会覆盖它（留空=不改，仍显示地址） |
| Conn-Hash / User-Agent | 默认 | 纯 DNS 模式不用管；万一上游返回 302/拒绝，换个 UA 再试 |

### 4.2 生成并导入 DNS

1. 设置页点一下「**复制 DNS 记录到剪贴板**」——整段记录（**换行原样保留**）就进了剪贴板；
   设置页下方还有一个**多行文本框**，内容完全一样，可以长按全选手动复制。
2. 把内容存成电脑上的 `ws_proxy_dns.txt`（手机上复制的可以发给自己，再到电脑上粘贴保存）。
3. Cloudflare → 你的域名 → **DNS → Records → Import and Export → Import** → 选择这个 `.txt`，
   **务必勾选 `Proxy imported DNS records`**（不勾就是直连 Telegram IP，等于没走 Cloudflare）。
4. 确认每条记录的云朵是**橙色**（Proxied）。

复制出来的内容就是下面这种（把 `example.com` 换成你的域名）：

```
; ws_proxy DNS records for example.com
; Cloudflare Import: tick Proxy (orange cloud); SSL/TLS mode must be Flexible
zhe3pgmlrvl6.example.com.	1	IN	A	149.154.175.50
momjyxgoz7vk.example.com.	1	IN	A	95.161.76.100
momjyxgoz7vk.example.com.	1	IN	A	149.154.167.51
b6uhfleke7gv.example.com.	1	IN	A	149.154.175.100
z7rcgtaurgk4.example.com.	1	IN	A	149.154.167.91
r24rxtadzlgw.example.com.	1	IN	A	149.154.171.5
mfqz3ysnzkk6.example.com.	1	IN	A	149.154.175.40
aymewq67bt3a.example.com.	1	IN	A	149.154.167.40
hdnsaw3f6zg7.example.com.	1	IN	A	149.154.175.117
zhe3pgmlrvl6.example.com.	1	IN	AAAA	2001:b28:f23d:f001::a
...（其余 AAAA 同理，一共 8 条）
```

> 整段一共 **17 条记录 + 2 行注释**，注释全是 ASCII（避免编辑器存成 GBK 时出问题）。
> 字段是标准 BIND zone 格式：`主机名.` `TTL` `IN` `类型` `值`，其中 TTL `1` 就是 Cloudflare 的 Auto。
> 想手动加也行，照抄每行即可；注意 **DC2 有两个 IP**，两条都要加。

> **最小可用集合 = DC1–DC5 的 A 记录（6 条，DC2 两个 IP）。** AAAA、测试 DC 17–19 都是可选，整段删掉不影响使用（原因见下）。
>
> **AAAA（IPv6）记录是干什么的、为什么可以不要**：
> 它声明“这个子域名的 IPv6 地址是 Telegram 的 IPv6 地址”。
> 但**你的手机从不直接连 Telegram 的 IP**——它连的是 Cloudflare 边缘节点（由 `socket.create_connection` 解析你的子域名得到），
> 只有 **Cloudflare 的边缘节点回源**时才可能走 IPv6。所以只有当你的网络是**纯 IPv6**（没有 IPv4 出口）时，AAAA 才决定“能不能连上”；
> 绝大多数手机是双栈或纯 IPv4，A 记录就够了。反过来，多一条 AAAA 只是多一条回源路径，不增加也不减少安全性。
>
> **测试 DC（17/18/19）什么时候用**：只有你把 Telegram 切到**测试服务器**（test backend）时才会连——
> 那是 Telegram 的独立测试环境：要单独注册测试账号、客户端要开启隐藏的 test backend 开关。
> 这个 fork 里开关默认是关的（`LoginActivity.TEST_BACKEND_IN_STORE = false`，测试后端勾选框只在登录页的隐藏入口里出现），
> 所以**日常正式账号永远只连 DC1–DC5**，这三条记录可以整段删掉。
> 插件路由表里保留它们只是为了“万一你在用测试账号”也能正常走代理。

> 记录**不再往日志里打**：完整内容就在设置页（复制按钮 + 多行文本框）。
> （排查连接问题仍可看日志：`Android/data/fork.risin42.nagramx/files/logs/`，搜 `ws_proxy`；
> 日志总开关在设置页最下方版本号菜单里的 `Enable/Disable logs`。）

> **为什么 v1.3.14 及更早“复制不出来”**：那条记录原本是 `Input` 控件，点开的是宿主的**单行**输入框
> （`PluginSettingsActivity.showStringInputDialog()`，`InputType.TYPE_CLASS_TEXT` 且没有 `MULTI_LINE`）。
> Android 的单行 `TextView` 会用 `SingleLineTransformationMethod` 把换行显示、复制成空格，
> 于是粘出来只剩一行，Cloudflare 自然 Import 失败。v1.3.15 起改用「一键写剪贴板 + 多行文本框」两条路。
### 4.3 切换 SSL/TLS 模式

Cloudflare → **SSL/TLS → Overview → 加密模式 = Flexible**。（纯 DNS 模式必需，原因：CF 要回源到 Telegram 的 80 端口明文 HTTP。）

### 4.4 启用并看状态

打开「启用代理」，插件状态行应显示：

```
127.0.0.1:6356 | 隧道 活动1/累计3 | *.example.com | DC1 标签 h7k2m9pqrs3t
```

隧道计数增长 = 已经建立 wss 连接；随后 Telegram 应能正常收发消息/媒体。

---

## 5. 验证与排错

| 检查 | 命令 / 现象 | 期望 |
|---|---|---|
| DNS 是否走 CF | `nslookup h7k2m9pqrs3t.example.com` | 返回 `104.x` / `172.67.x` 等 Cloudflare anycast IP（若是 `149.154.x` = 橙云没开） |
| 证书是否覆盖 | 浏览器打开 `https://h7k2m9pqrs3t.example.com/` | 证书由 Cloudflare 签发且无 SNI 告警（4xx/403 内容无所谓） |
| 证书是否进了 CT | `crt.sh/?q=example.com`（用浏览器） | 只有 `*.example.com` 通配证书、**不出现**每个标签主机名（用 apex 时） |
| 隧道是否建立 | 插件状态行 | `隧道 活动N/累计M` 随 Telegram 使用而增长 |
| 失败定位 | 插件日志 | 见下表 |

| 现象 | 常见原因 | 处理 |
|---|---|---|
| 隧道数一直是 0，日志 `ws dial ... failed: handshake rejected: HTTP 403/404` | 子域名不存在 / 没代理 | 重新导入 DNS，确认橙云；确认「域名」与记录里的域名一致 |
| `HTTP 426` 之类 | 请求没被当成 WebSocket 升级到 Telegram | 检查 A 记录是否指向 Telegram DC IP、模式是否 Flexible |
| DNS 解析到 `149.154.x` | 忘记勾选 *Proxy imported DNS records* | 删掉记录重新导入（或手动把云朵点成橙色） |
| TLS 证书错误（SNI 不匹配） | 用了二级域名（`xxx.proxy.example.com`）而通配证书只覆盖一层 | 把「域名」填成最外层域名（apex），或在 CF 里为每个主机名单独签证书（会进 CT 日志） |
| 换过「子域名随机串」后全部失败 | 子域名变了，DNS 还是旧的 | 重新生成模板并重导 DNS（见 §6） |
| **设置页打不开**，日志 `Failed to load plugin settings` + `Selector.__init__() got an unexpected keyword argument 'subtext'` | 宿主 `ui.settings.Selector` 不支持 `subtext`（只有 `Switch`/`Input`/`Text` 有）。v1.3.0 犯过；宿主是在 `loadPluginSettings()` 里反射构造设置项的，**任何一个未知参数都会让整页设置加载失败** | 升级到 **v1.3.1**（移除该参数）；**v1.3.15** 起所有设置项统一走 `item()` 兜底，宿主不认识的参数直接丢弃，同类崩溃不会再让整页失效 |
| 复制出来的 DNS 记录粘到 Cloudflare 只有一行 / Import 报格式错误 | v1.3.14 及更早用 `Input` 承载记录，点开的是宿主**单行**输入框，换行被 Android 的 `SingleLineTransformationMethod` 换成空格 | 升级到 **v1.3.15**：改用「一键写剪贴板 + 多行文本框」，换行原样保留（见 §4.2） |
| 代理列表那一行还是 `127.0.0.1:端口` | ①「代理列表里显示的名字」被清空了；② 日志出现 `代理列表改名：没找到 ProxyCell.setProxy` | ① 填回名字；② 该 fork 类名不同，把日志里的类名反馈给我即可适配 |
| 从 v1.2.1 升上来后全部失败 | 自动生成的子域名与你原有的 `pluto/venus/…` DNS 记录不一致 | 二选一：①「子域标签」切「**经典名（pluto/venus/…）**」，零改动立即恢复；② 按日志里的标签新增 DNS 记录 |
| Telegram 报 `302` 之类 | UA 被上游拒绝 | 自建域名一般不会；如遇到，把 User-Agent 改成 Telegram Web 的 UA 再试 |
| 全都正常但被墙/超时 | 域名或 Cloudflare IP 段被针对 | 见 §8 轮换与 §11 |

---

## 6. 子域标签与「子域名随机串」（重点）

- **子域名** = `<子域标签>.<你的域名>`，例如 `h7k2m9pqrs3t.example.com`；标签由 `derive_label(域名, 盐值, DC)` 用 HMAC-SHA256 派生（小写 base32 前 12 位、首字符强制为字母），是合法 DNS 主机名；
- **确定性**：同一（域名 + 「子域名随机串」）永远得到同一组子域名 → DNS 只配一次；
- **「子域名随机串」留空（默认，代码里的默认值就是空字符串）**：只按域名派生 → 同一域名永远同一套子域名，**重启、重装插件都不会变**。
  如果你看到里面已经有一串 16 位十六进制（例如 `167e177aad5579b7`），那是 **v1.3.0 会自动生成盐值的版本留下的**（v1.3.1 起不再自动生成）。
  **清空它 = 换一套子域名**，现有 DNS 记录立刻失效：要么留着不动，要么清空后重导 DNS。
- **填了「子域名随机串」**：再换一套子域名（不可预测性更强），但必须记住它；重装插件后要重新填回，否则会变；
- **改「子域名随机串」或换「域名」= 换掉整套 8 个子域名** → 必须重新导出并导入 DNS，否则全部握手失败；
- **设置项随「子域标签」联动**：自动生成 → 显示「子域名随机串」；经典名 → 两者都不显示；自定义 → 显示「自定义子域名」。切换后若页面没立刻变，退出再进一次设置页即可（宿主不支持时会回退到这种办法）；
- **想核对当前子域名**：看设置页「**DNS 记录**」多行文本框里的主机名（`h7k2m9pqrs3t.example.com.` 这种），或插件日志里的 `子域名(DC1-5)：…`；
- 三种「子域标签」：
  | 子域标签 | 行为 | 何时用 |
  |---|---|---|
  | 自动生成（推荐） | 按域名派生 | 自建域名，默认 |
  | 经典名（pluto/venus/…） | 固定 `pluto/venus/aurora/vesta/flora` | 你已按 Nullgram `records.txt` 配好这几个名字的 DNS 记录 |
  | 自定义 | 你手填（按 `DC1..DC5` 顺序逗号分隔，示例 `aa1`；没写的自动生成） | 想复用自己已有的、更"像正常业务"的子域名；非法字符会被自动清洗 |

> 注意：子域标签只影响**你自己域名**下的子域名。换模式、改「子域名随机串」或换域名之后，都要重新导出并导入 DNS 记录。

---

## 6.5 让 TG 代理列表那一行显示名字

TG 自带的代理页里，每一行的标题是**写死**的（源码 `ProxyListActivity$TextDetailProxyCell.setProxy()`：

```java
textView.setText(proxyInfo.address + ":" + proxyInfo.port);
```

`ProxyInfo` 只有 address / port / username / password / secret，**没有"名字"字段**，所以插件注册的本机代理会显示成
`127.0.0.1:6356`。Nullgram 之所以能显示名字，是它**改了自己的 app 源码**，给自家内置代理加了特判
（`LocaleController.getString("PublicProxy", ...)`）——普通插件拿不到这个特判。

本插件用宿主提供的 **Xposed 式 hook** 达到同样效果：在 `setProxy()` 执行完之后，如果是我们注册的那一行
（address=`127.0.0.1` 且 port=本机端口），就把那个 TextView 的文字换成名字。

- 名字默认 `WebSocket 代理`，可在「高级 → 代理列表里显示的名字」里改；**留空就恢复显示 `地址:端口`**。
- 只动这一行的显示，不动代理连接、不影响其它代理条目。
- 如果某个 fork 的内部类名不同，插件会在日志里说明并**自动跳过**（列表照旧显示地址，代理功能不受影响）：
  `代理列表改名：没找到 ProxyCell.setProxy，已跳过`。
- 日志里看到 `代理列表改名已启用：…setProxy -> WebSocket 代理` 就说明生效了。

## 7. 为什么不直接用 `pluto/venus/aurora/vesta/flora`

这五个名字是 **Telegram 自己的 DC 主机名**（Telegram Web 客户端源码里 `sslSubdomains = ['pluto','venus','aurora','vesta','flora']`，对应 `https://<name>.web.telegram.org/apiws`）。把它们写死当标签，等于在 SNI 里主动声明"我是 Telegram 的 WS 代理"，而且：

1. **固定**：所有用户、所有部署完全一致 → 一条 DPI 规则通杀；
2. **公开**：插件源码、Nullgram/Nekogram 仓库、教程里到处都是；
3. **低误伤**：正常网站不会用 Telegram 的 DC 名做子域 → 封锁它几乎不牵连正常流量；
4. **可能进 CT 日志**：为逐个主机名签发证书时，`pluto.<域名>` 这种名字会出现在全球可查的证书透明日志里（实测：公共中继域名的 `pluto`/`venus` 主机名确有 CT 记录），任何人都能被动枚举出候选域名。

v1.3.x 起改成自动生成子域名后，名字变成"每个部署独有 + 无意义"，上述四条同时失效。剩余指纹（路径 `/api`、`Conn-Hash` 头、UA、长连接模式、CF IP 段）都包在 TLS 里，路径上的观察者看不到，而**明文可见的 SNI 已经不再有 Telegram 特征**。

---

## 8. 轮换与运维 SOP

被墙或怀疑被针对时，按顺序试（每一步都是 3 分钟）：

1. **换子域名**：设置里把「子域名随机串」填一个新的随机串 → 点「复制 DNS 记录到剪贴板」拿新记录 → 在 Cloudflare 覆盖旧记录（或先删掉旧记录再 Import）；
2. **换域名**：把「域名」换成备用域名（建议另备 1–2 个，可放在不同 CF 账号，anycast IP 往往不同）→ 重导 DNS → 重启；
3. **客户端 DPI 绕过**：zapret / GoodbyeDPI（Windows）、ByeDPI / DPITunnel（Android，按应用覆盖 Telegram）——[tg-ws-proxy 的文档](https://github.com/Flowseal/tg-ws-proxy/blob/main/docs/EN/CfProxy.md)也要求把 Cloudflare 域名加进 zapret，因为"CF 子网可能被封锁"；
4. **回落**：NagramXF 支持多代理配置，随时切回 MTProxy / 直连，不要把可用性押在单通道。

**纪律**：域名与盐值**不要公开**（不发群、不发仓库、不分享给别人），一旦被公开就等于进入封禁倒计时。

---

## 9. 安全与合规（摘要）

以 2026-10 的 [Cloudflare Self-Serve Subscription Agreement](https://www.cloudflare.com/terms/) 现文本为准（条款会更新，且以下非法律意见）：

- **§2.2.1(j)**：`"use the Services to provide a virtual private network or other similar proxy services."` —— "把 Cloudflare 的服务用于提供 VPN 或类似代理服务"被明确写进限制清单；
- **§2.2.1(a)**：不得把服务转售/提供给第三方 —— 所以**做成公共中继/分享域名风险最高**；
- **§8**：判定违反 §2.2 可**立即停用**，且 Cloudflare 有权"随时、无需理由、无需通知"终止账号。

务实做法：只自用、不公开、用小号 + 一次性域名、别跑大流量；要完全合规就改用 VPS 自建中转或企业协议。VPN/代理类工具在不同司法辖区另有规定，与 CF 条款是两回事。

---

## 10. 变更记录

> **读旧条目时的更正说明（2026-10）**：v1.3.15 之前的几条变更记录里写着“宿主 `Text` 不派发点击”，
> 这个结论**是错的**。核对本构建（`30dcd6c`）的 `PluginSettingsActivity.onClick()` 后确认：
> `TextSetting.onClickCallback` 会被调用（`textSetting.onClickCallback.call(view)`，紧跟在
> `createSubFragmentCallback` 分支之后）。v1.3.15 起重新使用 `Text` 做「复制 DNS 记录到剪贴板」。
> 下面 v1.3.7 / v1.3.9 / v1.3.13 等条目里的相关表述请以本说明为准。

### v1.3.15
- **修好「DNS 记录导入不进去」**：v1.3.14 及更早把记录放在 `Input` 里，而 `Input` 点开的是宿主
  `PluginSettingsActivity.showStringInputDialog()` 创建的**单行** `EditTextBoldCursor`
  （`InputType.TYPE_CLASS_TEXT`，没有 `MULTI_LINE`）。Android 的单行 `TextView` 会用
  `SingleLineTransformationMethod` 把 `\n` 显示、复制成空格，于是复制出来只剩**一行**，
  Cloudflare 的 BIND 导入必然失败。现在改成两条路：
  ① `Text`「复制 DNS 记录到剪贴板」——直接 `android_utils.copy_to_clipboard()` 写剪贴板，
  完全绕过 `TextView`，换行原样保留；② `EditText(multiline=True, max_length=8192)`——
  宿主 `PluginEditTextCell` 会 `setSingleLine(false)`，可查看、可长按全选。
  两个控件都单独 `try` 导入，老宿主没有时自动退回原来的 `Input`，不会让整页设置失效。
- **DNS 记录文本大幅精简**：注释从 19 行压到 **2 行且全为 ASCII**（原来是中文 `;;` 大段说明 +
  逐 DC 注释），只剩 17 条 A/AAAA 记录；解释文字全部移到本文档 §4.2，既解决“废话太多”，
  也避免编辑器按 GBK 保存导致上传失败。
- **修正一个此前的错误结论**：v1.3.13 曾判定“宿主 `Text` 不派发点击”。核对本构建
  `PluginSettingsActivity.onClick()` 后确认 `TextSetting.onClickCallback` **是会派发的**
  （`textSetting.onClickCallback.call(view)`），因此 v1.3.15 重新用 `Text` 做复制按钮。
- **设置项构造加兜底**：新增 `item(factory, **kw)`，宿主 SDK 不认识的参数一律丢弃而不是抛错。
  起因正是 v1.3.0 的 `Selector(subtext=…)`：宿主在 `loadPluginSettings()` 里反射构造这些
  dataclass，一个未知参数就会终结整页设置加载（`Failed to load plugin settings` +
  `TypeError: Selector.__init__() got an unexpected keyword argument 'subtext'`）。
- **自测新增控件参数审计**：把宿主 SDK 的字段表固化进 `test_ws_proxy.py`，任何设置项传了
  签名里没有的关键字都会直接 FAIL，避免同类问题再犯。
- 顶部「对应插件文件」版本号同步。

### v1.3.14
- **插件介绍精简**：`__description__` 改为笼统的一句话（改走 WebSocket、纯客户端、只需一个域名），不再罗列原理细节。
- **插件文件顶部注释重写**：只保留「三步就能用」+ 一句"细节见 README.md"；原先的原理/标签/路由表长注释移到本 README。
- 「域名」输入框副标题**删掉三步说明**（那三步现在只在插件注释和本文档 TL;DR 里各出现一次）。

### v1.3.13
- **删掉「三步就能用」那一行**（设置页最后一条 `Text`），三步说明并入「域名」输入框的副标题：
  填域名 → 点开「DNS 记录（点开复制）」整段 Import（勾橙云）→ 打开「启用代理」并把 SSL/TLS 设为 Flexible。
- 从此**不再导入/使用 `Text` 控件**：设置页只由开关、下拉、输入框组成，不存在点不动的行。
  > 更正（v1.3.15）：这条结论**有误**——核对 `PluginSettingsActivity.onClick()` 后确认 `Text` 的
  > `on_click` 是会派发的，v1.3.15 已重新用它做「复制 DNS 记录到剪贴板」。

### v1.3.12
- 说明**测试 DC（17/18/19）什么时候才会用到**：仅 Telegram 测试服务器（test backend + 测试账号）场景；
  本 fork 该开关默认关闭，日常正式账号只连 DC1–DC5，因此三条测试记录可整段删除。插件路由表保留它们仅为兼容测试账号。

### v1.3.11
- 记录片段结尾补上"**下面这些可以整段删掉**"的说明：AAAA 只是冗余（手机连的是 CF 边缘，纯 IPv6 网络才用得上），测试 DC 17–19 日常用不到。
- 设置页「DNS 记录（点开复制）」的说明改为"核心就是 DC1–DC5 的 A 记录，后面是可选冗余"。

### v1.3.10
- **完整 DNS 记录直接放进设置页输入框**（点开即可复制，整段 Import 到 Cloudflare），**不再往插件日志里打**：
  删掉 `_log_dns_template()` 与启用时的日志导出，输入框内容改为完整 zone 片段（5 条 A + AAAA + 导入提示）。
- 「三步就能用」与文档同步：② 改成"整段复制并 Import（或照着手动加）"。

### v1.3.9
- **删掉所有点不动的行**：宿主 SDK 的 `Text` 不派发点击，所以移除「当前子域名」「运行状态」两行文字，
  以及只读的提示性文字行；设置页现在只剩**能用的**开关 / 下拉 / 输入框。
- **「换一套新名字」→「子域名随机串（留空即可）」**：名字和说明改成一看就懂，并写清留空/填写的后果。
- **DNS 行改名为「DNS 记录（点开复制）」**：内容改成 5 行 `子域名=IP`，方便逐条手动加 A 记录；
  需要整段导入（含 AAAA）仍可用启用代理后打进日志的完整片段。
- 「三步就能用」重写为：① 填域名 → ② 复制并添加 5 条 A 记录 → ③ 打开代理 + SSL/TLS 设 Flexible。

### v1.3.8
- **新增「DNS 记录（点开可复制）」**：设置页里唯一的可点复制入口（输入框），点开全选即可拿去 Cloudflare 加 5 条 A 记录，
  不必再翻日志；启用代理时仍会把完整 zone 片段（含 AAAA）按行打进插件日志。
- 文档补充**日志位置**与查看方式：`Android/data/<包名>/files/logs/`、文件名格式、版本号菜单里的日志开关、搜索关键字。

### v1.3.7
- 「子域名怎么起名」改回 **「子域标签」**。
- **设置项随「子域标签」联动**：自动生成 → 显示「子域名随机串」；经典名 → 两者都不显示；自定义 → 显示「自定义子域名」；
  切换时尽量让宿主重建该页，不支持时退出再进一次即可。
- **修好 DNS 记录导出**：宿主的 `Text` 行不派发点击（之前的"点了没反应"就是这个原因），
  改为**打开「启用代理」时自动把完整 records 片段打进插件日志**，设置页只保留一行只读的「当前子域名」。
- 「子域名随机串」写清默认值与来源：代码默认空；已有 16 位十六进制是 v1.3.0 自动生成的残留，清空会换子域名。

### v1.3.6
- **移除已失效的 Nullgram 公共中继**：插件不再内置任何域名（`DEFAULT_DOMAIN` 常量已删除），
  「域名」改为**必填**；未填时代理不会启动，并在日志里提示。
- 相关界面文案与注释同步更新，不再有"留空 = 公共中继"的说法。

### v1.3.5
- 「自定义子域名」的示例精简为 **1 个**：`示例：aa1（没写的会自动生成，只填 1 个也行）`。

### v1.3.4
- **「域名」直接填，不再有下拉**：留空 = 用 Nullgram 公共中继，填了就走自建（原「服务商 / 我自己的域名」两级选择已删除）。
- 起名模式第三项由「我自己填名字」改为 **「自定义」**；对应输入框改名「自定义子域名」。
- 「自定义子域名」说明补上**完整示例**：`aa1,bb2,cc3,dd4,ee5,tt1,tt2,tt3`（依次 DC1,DC2,DC3,DC4,DC5,测试1,测试2,测试3）。

### v1.3.3
- **新增：TG 代理列表那一行可以显示名字**（默认 `WebSocket 代理`）。TG 源码里这行写死为 `address:port`、
  `ProxyInfo` 也没有名字字段，Nullgram 靠改 app 源码特判；本插件改用宿主的 Xposed 式 hook，
  在 `ProxyListActivity$TextDetailProxyCell.setProxy()` 之后覆写 TextView，效果相同且不改 app。
  可在「高级 → 代理列表里显示的名字」修改，留空即恢复显示地址；hook 装不上时自动降级并在日志说明。

### v1.3.2
- **设置页重做**：单页、纯中文、按「启用 → 三步 → 域名 → 子域名 → DNS → 高级 → 运行状态」排列，
  不再有让人看不懂的术语；下拉项改为「我自己的域名 / Nullgram 公共中继」「自动生成（推荐）/
  经典名（pluto/venus/…）/ 我自己填名字」。
- 插件显示名从 `WS Proxy (tcp2ws)` 改为 **`WebSocket 代理`**（和 Nullgram 的叫法一致）。
- 「自定义域名 / 自定义标签」等旧文案全部重写：域名只填域名本身；子域名按 `DC1..DC5` 顺序逗号分隔，
  并明确标注「子域名随机串」的后果。
- 运行状态改为中文可读：`运行中：127.0.0.1:6356 ｜ 连接 活动1/共3 ｜ 域名 … ｜ DC1 子域名 …`。

### v1.3.1
- **修复（严重）**：v1.3.0 给 `Selector` 加了宿主不支持的 `subtext` 参数，导致
  `Failed to load plugin settings` / `TypeError: Selector.__init__() got an unexpected keyword argument 'subtext'`，
  **插件设置页完全打不开**。已移除该参数；新增一条控件参数审计，避免再犯。
- **修复**：不再自动生成随机盐值（也不再调用 `set_setting`）。默认只按「域名」派生标签，
  重启/重装插件后标签保持稳定；v1.3.0 的随机盐会导致标签漂移、DNS 全部失配。
- **可观测性**：启动日志打印 `子域名(DC1-5)：…`，不开设置页也能照着配 DNS；
  设置页标签行前面会显示当前模式名。
- 自测新增「空盐值也必须确定性」断言。

### v1.3.0
- **新增派生标签**：默认不再使用固定的 `pluto/venus/aurora/vesta/flora`，改为按「域名 + 盐值」派生（`derive_label` / `build_labels`）；
- **新增三种标签模式**：派生 / 兼容 / 自定义（自定义支持自动清洗非法字符、缺项自动补齐）；
- **新增 DNS 记录模板**：设置页一键输出可直接导入 Cloudflare 的 A/AAAA 记录片段（含 Flexible 提示）；
- **新增设置页预览**：显示当前 5 个标签主机名；状态行与启动日志会显示 DC1 标签，便于核对；
- **保护默认配置**：域名 = Nullgram 公共中继 时强制兼容标签，避免公共中继不可用；
- `build_routes(domain, labels=None)` 向后兼容（缺省仍是兼容标签），旧测试断言不变。

### v1.2.1 及更早
- 见 git 历史与插件目录内 README 的「故障排查 / 已修复的历史问题」。

---

## 11. 可选：自建 Pages/Workers 中继

本教程的纯 DNS 模式**不需要**任何服务端。若你希望自己控制中继（加鉴权、避免 Flexible、或 DNS 模式在你所在网络不可用），
可用同仓库的 [`cf-relay/`](./cf-relay/)（Pages 高级模式 `_worker.js`，或同一个文件部署成 Worker）——
那条路会用到 `Conn-Hash` 与「我自己的域名 + 每个 DC 主机名」的绑定，部署细节见 [cf-relay/README.md](./cf-relay/README.md)。
