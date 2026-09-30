# -*- coding: utf-8 -*-
"""filter_enhancement 的离线结构化测试（CPython 直接运行，无需 Java）。

插件文件顶层 import Chaquopy 的 `java` 模块，无法在 CPython 中直接加载，
因此本测试基于 AST 做结构校验——它能拦截的恰恰是历史版本真实出现过、
且只能在真机上暴露的问题：

  - v1.0.0/v1.0.1 的 ClassCastException 空白页（setResult 裸 Python int 被
    Chaquopy 装箱为 Long，Xposed 以 (Integer) 强转导致布局崩溃）；
  - 元数据不合规（__id__ 格式）导致宿主拒绝安装；
  - 中英字符串表键缺失导致设置页出现裸 key；
  - 钩子安装数与声明数不一致导致功能静默降级。

运行：
    python test_filter_enhancement.py
"""
import ast
import importlib.machinery
import importlib.util
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_PATH = os.path.join(HERE, "filter_enhancement.plugin")
VERSIONS_DIR = os.path.join(HERE, "versions")
ALL_VERSIONS = ["v1.0.0", "v1.0.1", "v1.0.2", "v1.0.3", "v1.0.4", "v1.0.5"]

PASSED = [0]
FAILED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("  ok  %s" % name)
    else:
        FAILED[0] += 1
        print("FAIL  %s" % name)


def parse(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return src, ast.parse(src, filename=path)


def module_metadata(tree):
    """提取模块级 __xxx__ 赋值。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("__") and t.id.endswith("__"):
                    try:
                        out[t.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
    return out


def string_tables(tree):
    """提取 _STRINGS 字典的 zh/en 键集合。"""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_STRINGS" for t in node.targets):
            keys = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(v, ast.Dict):
                    keys[k.value] = {kk.value for kk in v.keys}
            return keys
    return {}


def setresult_calls(src, tree):
    """收集所有 obj.setResult(...) 调用（返回 (参数源码段, 起始行)）。"""
    calls = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setResult"):
            seg = ast.get_source_segment(src, node.args[0])
            calls.append((seg.strip() if seg else "?", node.args[0], node.lineno))
    return calls


def arg_kind(arg):
    """粗判 setResult 实参类型：'int-box'（显式 Integer）、'bare-int'、'bool-box'、
    'bare-bool'、'other'（Holder/str 等）。"""
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        if arg.func.id == "JInteger":
            return "int-box"
        if arg.func.id == "JBoolean":
            return "bool-box"
    if isinstance(arg, ast.Constant):
        if isinstance(arg.value, bool):
            return "bare-bool"
        if isinstance(arg.value, int):
            return "bare-int"
    if isinstance(arg, ast.Name):
        return "bare-name"  # 可能是 int 变量，人工核对项
    return "other"


def test_latest():
    print("== 主版本（filter_enhancement.plugin，应为 v1.0.5）==")
    src, tree = parse(PLUGIN_PATH)

    compile(src, PLUGIN_PATH, "exec")
    check("语法可编译", True)

    meta = module_metadata(tree)
    check("__id__ = filter_enhancement", meta.get("__id__") == "filter_enhancement")
    check("__id__ 符合宿主格式",
          bool(re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$", meta.get("__id__", ""))))
    check("__name__ 非空", bool(meta.get("__name__")))
    check("__version__ = 1.0.5", meta.get("__version__") == "1.0.5")
    check("__min_version__ >= 12.2.10",
          meta.get("__min_version__", "0") >= "12.2.10")

    tables = string_tables(tree)
    check("中英字符串表齐全", set(tables) == {"zh", "en"})
    check("中英键一致", tables.get("zh", set()) == tables.get("en", set()))

    # 核心回归：setResult 不允许出现裸 int / 裸 bool（v1.0.0 空白页根因）
    bad = []
    for seg, arg, line in setresult_calls(src, tree):
        kind = arg_kind(arg)
        if kind in ("bare-int", "bare-bool"):
            bad.append((line, kind))
    check("setResult 无裸 int/bool（ClassCastException 回归防护）", not bad)
    if bad:
        for line, kind in bad:
            print("      line %d: %s" % (line, kind))

    # 裸变量 setResult 需逐一核对（v1.0.2 中仅 getMessageFilterMatchText 的
    # setResult(text) 属于 String 语义，onCreateViewHolder 的参数是 Holder 对象）
    bare_names = [(line, seg) for seg, arg, line in setresult_calls(src, tree)
                  if arg_kind(arg) == "bare-name"]
    check("裸变量 setResult 仅限对象/String 语义",
          all(seg in ("text",) for _, seg in bare_names))
    for line, seg in bare_names:
        if seg not in ("text",):
            print("      需核对 line %d: setResult(%s)" % (line, seg))

    # 钩子声明一致性：_install_hooks 中 _hook 调用数 == _hooks_total 初值
    hook_calls = 0
    hooks_total_init = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_hook"):
            hook_calls += 1
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, int)):
            for t in node.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "_hooks_total"
                        and isinstance(t.value, ast.Name) and t.value.id == "self"):
                    hooks_total_init = node.value.value
    check("钩子数声明一致（%s）" % hook_calls,
          hooks_total_init is not None and hook_calls == hooks_total_init)

    # VIEW_TYPE_FILTER_PLACEHOLDER 值
    vt = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "VIEW_TYPE_FILTER_PLACEHOLDER"
                for t in node.targets):
            vt = ast.literal_eval(node.value)
    check("占位条视图类型 = -1001", vt == -1001)


def test_all_versions():
    print("== 历史版本归档完整性 ==")
    for ver in ALL_VERSIONS:
        path = os.path.join(VERSIONS_DIR, ver, "filter_enhancement.plugin")
        exists = os.path.isfile(path)
        check("%s 存在" % ver, exists)
        if not exists:
            continue
        src, tree = parse(path)
        compile(src, path, "exec")
        meta = module_metadata(tree)
        check("%s 版本号自洽（文件声明 %s）" % (ver, meta.get("__version__")),
              meta.get("__version__") == ver[1:])

    # 版本演化断言：装箱修复只应出现在 v1.0.2
    for ver in ("v1.0.0", "v1.0.1"):
        path = os.path.join(VERSIONS_DIR, ver, "filter_enhancement.plugin")
        if not os.path.isfile(path):
            continue
        src, _ = parse(path)
        check("%s 不含装箱修复（历史保真）" % ver,
              "JInteger" not in src and "JLong" not in src)
    src, _ = parse(PLUGIN_PATH)
    check("v1.0.2 含装箱修复", "JInteger" in src and "JLong" in src)


def test_v103_listener_hooks():
    print("== v1.0.3 列表点击派发钩子（点击无效/长按无效修复）==")
    src, tree = parse(PLUGIN_PATH)
    method_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    check("含 _install_listener_hooks", "_install_listener_hooks" in method_names)
    check("含 _before_list_item_click", "_before_list_item_click" in method_names)
    check("含 _before_list_item_long_click", "_before_list_item_long_click" in method_names)
    check("含 _placeholder_for_view（父链解析）", "_placeholder_for_view" in method_names)
    # createView 钩子必须调用监听器安装（懒安装入口）
    call_ok = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_install_listener_hooks"):
            call_ok = True
    check("createView 中调用 _install_listener_hooks", call_ok)
    # 点击消费必须 setResult(None)（跳过原监听器）
    check("点击钩子消费事件（setResult(None)）", "param.setResult(None)" in src)
    check("长按钩子消费事件（setResult(JBoolean(True))）",
          "param.setResult(JBoolean(True))" in src)


# ---------------------------------------------------------------------------
# v1.0.4 —— Java 替身驱动的行为级测试
#
# v1.0.3 的教训：交互拦截若挂在「反射 ChatActivity 匿名监听器实例」上，
# 一旦宿主字段名变化或安装点被前面的早退/异常跳过，点击与长按会同时静默失效。
# v1.0.4 改为主钩 ChatActivity.createMenu（两种手势的汇聚点），本段用替身
# 直接驱动分派函数，验证命中/未命中、事件消费与重载参数解析。
# ---------------------------------------------------------------------------
class _JStub:
    """Any Java class / instance / static member, permissively stubbed."""

    def __init__(self, name="stub"):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, item):
        return _JStub("%s.%s" % (object.__getattribute__(self, "_name"), item))

    def __call__(self, *args, **kwargs):
        return _JStub("%s()" % object.__getattribute__(self, "_name"))

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __bool__(self):
        return True

    def __str__(self):
        return object.__getattribute__(self, "_name")


class _JBox:
    """java.lang.Integer / Boolean / Long stand-in (setResult 装箱回归防护)."""

    def __init__(self, value=True):
        self.value = value

    def __int__(self):
        return int(self.value)

    def __bool__(self):
        return bool(self.value)

    def __eq__(self, other):
        return isinstance(other, _JBox) and self.value == other.value

    def __repr__(self):
        return "_JBox(%r)" % (self.value,)


class _FakeView:
    """Identity-comparable stand-in for an android.view.View."""


def _build_stub_modules():
    """Minimal host SDK stand-ins so the plugin module can be imported on CPython."""
    java = types.ModuleType("java")

    def jclass(name):
        if name == "java.lang.System":
            stub = _JStub("System")
            stub.identityHashCode = lambda obj: id(obj)  # real identity, not 0
            return stub
        if name in ("java.lang.Integer", "java.lang.Boolean", "java.lang.Long"):
            return _JBox
        return _JStub(name)

    java.jclass = jclass

    base_plugin = types.ModuleType("base_plugin")

    class BasePlugin:
        def __init__(self):
            self.id = "filter_enhancement"

        def hook_method(self, *a, **k):
            return object()

        def unhook_method(self, *a, **k):
            pass

        def get_setting(self, key, default=None):
            return default

        def log(self, message):
            pass

    class XposedHook:
        def __init__(self, before=None, after=None):
            self.before = before
            self.after = after

    base_plugin.BasePlugin = BasePlugin
    base_plugin.XposedHook = XposedHook

    hook_utils = types.ModuleType("hook_utils")
    hook_utils.find_class = lambda name: None
    hook_utils.get_private_field = lambda obj, name: None

    android_utils = types.ModuleType("android_utils")
    android_utils.dp = lambda value: int(value)
    android_utils.log = lambda data: None
    android_utils.run_on_ui_thread = lambda func, delay=0: None
    android_utils.get_string = lambda key: "OK"
    android_utils.OnClickListener = lambda func: func
    android_utils.OnLongClickListener = lambda func: func
    android_utils.R = lambda func: func

    ui = types.ModuleType("ui")
    ui_settings = types.ModuleType("ui.settings")
    for cls_name in ("Header", "Divider", "Switch", "Text"):
        ui_settings.__dict__[cls_name] = type(cls_name, (object,), {
            "__init__": lambda self, **kw: self.__dict__.update(kw)})
    ui_alert = types.ModuleType("ui.alert")
    ui_alert.AlertDialogBuilder = _JStub("AlertDialogBuilder")
    ui.settings = ui_settings
    ui.alert = ui_alert

    return {
        "java": java,
        "base_plugin": base_plugin,
        "hook_utils": hook_utils,
        "android_utils": android_utils,
        "ui": ui,
        "ui.settings": ui_settings,
        "ui.alert": ui_alert,
    }


def load_plugin_module():
    for name, mod in _build_stub_modules().items():
        sys.modules[name] = mod
    loader = importlib.machinery.SourceFileLoader("fe_under_test", PLUGIN_PATH)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _FakeParam:
    def __init__(self, args):
        self.args = list(args)
        self.result_set = False
        self.result = None

    def setResult(self, value):
        self.result_set = True
        self.result = value

    def getResult(self):
        return self.result


def _fresh_plugin(module):
    plugin = module.FilterEnhancementPlugin()
    plugin._views = {}
    plugin._states = {}
    plugin._diag = {"taps": 0, "longs": 0, "menu_miss": 0,
                    "menu_calls": 0, "listener_calls": 0, "created": 0, "bound": 0}
    plugin._listener_hooks_done = False
    plugin._listener_hooks_dead = False
    plugin._click_hook_ok = False
    plugin._longclick_hook_ok = False
    plugin._hooks_total = 10
    plugin.log = lambda message: None
    plugin.dispatched = []
    plugin._reveal_from = lambda vs: plugin.dispatched.append(("reveal", vs["tag"]))
    plugin._on_placeholder_long_click = lambda view: plugin.dispatched.append(("long", view))
    return plugin


def _register_placeholder(module, plugin, tag="p1"):
    view = _FakeView()
    vs = {"view": view, "msg": None, "activity": None, "adapter": None, "state": {}, "tag": tag}
    plugin._views[module._identity(view)] = vs
    return view, vs


def test_v104_create_menu_dispatch():
    print("== v1.0.4 createMenu 分派（行为级，Java 替身）==")
    module = load_plugin_module()
    plugin = _fresh_plugin(module)
    plugin._menu_hook_ok = True
    root, _vs = _register_placeholder(module, plugin)

    # 1) 6 参重载：点击（longpress = args[5] = False）
    param = _FakeParam([root, True, False, 0.0, 0.0, False])
    plugin._before_create_menu(param)
    check("点击命中 → 触发 reveal", plugin.dispatched[-1] == ("reveal", "p1"))
    check("点击命中 → 消费事件（setResult 装箱布尔）",
          param.result_set and bool(param.getResult()))
    check("点击命中 → taps 计数", plugin._diag["taps"] == 1)

    # 2) 6 参重载：长按（longpress = args[5] = True）
    param = _FakeParam([root, False, True, 0.0, 0.0, True])
    plugin._before_create_menu(param)
    check("长按命中 → 触发原因弹窗", plugin.dispatched[-1] == ("long", root))
    check("长按命中 → 消费事件", param.result_set)
    check("长按命中 → longs 计数", plugin._diag["longs"] == 1)

    # 3) 7 参重载：longpress 后移一位（args[6]）
    param = _FakeParam([root, True, False, 0.0, 0.0, True, True])
    plugin._before_create_menu(param)
    check("7 参重载 → 长按解析到 args[6]", plugin.dispatched[-1] == ("long", root))
    param = _FakeParam([root, True, False, 0.0, 0.0, True, False])
    plugin._before_create_menu(param)
    check("7 参重载 → 点击解析到 args[6]", plugin.dispatched[-1] == ("reveal", "p1"))

    # 4) 非占位条视图：不得消费，宿主菜单必须保持原样
    other = _FakeView()
    miss_before = plugin._diag["menu_miss"]
    param = _FakeParam([other, True, False, 0.0, 0.0, False])
    plugin._before_create_menu(param)
    check("非占位条 → 不消费（宿主菜单不受影响）", not param.result_set)
    check("非占位条 → menu_miss 计数", plugin._diag["menu_miss"] == miss_before + 1)

    # 5) 参数解析表
    mv = module.FilterEnhancementPlugin._menu_longpress
    check("_menu_longpress 6 参取 args[5]",
          mv([0, 0, 0, 0, 0, True]) is True and mv([0, 0, 0, 0, 0, False]) is False)
    check("_menu_longpress 7/9 参取 args[6]",
          mv([0, 0, 0, 0, 0, True, True]) is True
          and mv([0, 0, 0, 0, 0, True, True, False, False]) is True)

    # 6) 次级路径（匿名监听器）仍可用且计数
    taps_before = plugin._diag["taps"]
    param = _FakeParam([root])
    plugin._before_list_item_click(param)
    check("次级点击路径消费 + 计数",
          param.result_set and plugin._diag["taps"] == taps_before + 1)
    longs_before = plugin._diag["longs"]
    param = _FakeParam([root])
    plugin._before_list_item_long_click(param)
    check("次级长按路径消费 + 计数",
          param.result_set and plugin._diag["longs"] == longs_before + 1)

    # 7) 宿主无匿名监听器字段时不得反复反射
    plugin._listener_hooks_dead = True
    attempts = []
    plugin.hook_method = lambda *a, **k: attempts.append(1)
    plugin._install_listener_hooks(object())
    check("_listener_hooks_dead 后短路（不重复反射安装）", not attempts)


def test_v104_wiring():
    print("== v1.0.4 接线与版本演化 ==")
    src, tree = parse(PLUGIN_PATH)
    method_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    check("含 _before_create_menu（主路径）", "_before_create_menu" in method_names)
    check("含 _menu_longpress（重载参数解析）", "_menu_longpress" in method_names)
    check("含 _hook_optional（可选钩子，不计入健康分）", "_hook_optional" in method_names)

    # createMenu 6 参必须用计入健康分的 _hook 声明
    main_hook = False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_hook" and len(node.args) >= 3
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "createMenu"
                and isinstance(node.args[2], ast.Constant) and node.args[2].value == 6):
            main_hook = True
    check("createMenu 6 参为主钩（计入 10 个钩子）", main_hook)

    # 关键回归：_install_listener_hooks 必须位于 _after_create_view 的 pill 块之前，
    # 即排在函数内任何 return 之前——v1.0.3 把它放在 pill 创建之后，被早退/异常跳过。
    create_view_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_after_create_view":
            create_view_fn = node
    check("定位 _after_create_view", create_view_fn is not None)
    if create_view_fn is not None:
        install_lines = [n.lineno for n in ast.walk(create_view_fn)
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "_install_listener_hooks"]
        return_lines = [n.lineno for n in ast.walk(create_view_fn) if isinstance(n, ast.Return)]
        check("_install_listener_hooks 已与 pill 块解耦（早于所有 return）",
              bool(install_lines) and bool(return_lines)
              and min(install_lines) < min(return_lines))
        check("_after_create_view 中已无重复安装调用", len(install_lines) == 1)

    # 版本演化：v1.0.3 不得含 createMenu 主路径（历史保真），v1.0.4 必须含
    v103 = os.path.join(VERSIONS_DIR, "v1.0.3", "filter_enhancement.plugin")
    if os.path.isfile(v103):
        src103, _ = parse(v103)
        check("v1.0.3 不含 createMenu 主路径（历史保真）", "_before_create_menu" not in src103)
    check("v1.0.4 含 createMenu 主路径", "_before_create_menu" in src)


class _FakeJavaView:
    """android.view.View stand-in that tracks clickable / click listeners."""

    def __init__(self, *args, **kwargs):
        self.clickable = False
        self.click_listener = None
        self.long_listener = None

    def setClickable(self, value):
        self.clickable = bool(value)

    def isClickable(self):
        return self.clickable

    def setOnClickListener(self, listener):
        self.click_listener = listener
        self.clickable = True          # mirrors View.setOnClickListener

    def setOnLongClickListener(self, listener):
        self.long_listener = listener
        self.clickable = True

    def __getattr__(self, item):                                  # noqa: D105
        return lambda *a, **k: None


class _FakeHolder:
    def __init__(self, item_view):
        self.itemView = item_view


class _FakeActivity:
    def getParentActivity(self):
        return _JStub("Context")


def _build_placeholder(plugin, activity, adapter="adapter"):
    """Drive _before_create_view_holder with viewType -1001 and return the row view."""
    plugin._activity_for_adapter = lambda _adapter: activity
    param = _FakeParam([_JStub("parent"), -1001])
    param.thisObject = adapter
    plugin._before_create_view_holder(param)
    holder = param.result
    return holder.itemView if holder is not None else None


def test_v105_row_must_stay_non_clickable():
    print("== v1.0.5 占位条必须不可点击（RecyclerListView 条目分派的前提）==")
    module = load_plugin_module()
    module.FrameLayout = _FakeJavaView
    module.TextView = _FakeJavaView
    module.FrameLayoutParams = lambda *a, **k: None
    module.RecyclerViewLayoutParams = lambda *a, **k: None
    module.RecyclerListViewHolder = _FakeHolder
    activity = _FakeActivity()

    # A) 列表级钩子可用 → 行内不得挂监听器（clickable 必须为 False）
    plugin = _fresh_plugin(module)
    plugin._menu_hook_ok = True
    row = _build_placeholder(plugin, activity)
    check("占位条创建成功", row is not None)
    check("根视图被显式置为不可点击", row is not None and row.clickable is False)
    check("主路径可用时不挂行内点击监听器", row is not None and row.click_listener is None)
    check("主路径可用时不挂行内长按监听器", row is not None and row.long_listener is None)
    check("占位条创建计数 +1", plugin._diag["created"] == 1)

    # B) 无任何列表级钩子 → 保留行内监听器作为兜底
    plugin2 = _fresh_plugin(module)
    plugin2._menu_hook_ok = False
    row2 = _build_placeholder(plugin2, activity, adapter="adapter2")
    check("无列表级钩子时保留行内兜底监听器",
          row2 is not None and row2.click_listener is not None and row2.long_listener is not None)


def test_v105_wiring():
    print("== v1.0.5 接线与版本演化 ==")
    src, tree = parse(PLUGIN_PATH)

    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_before_create_view_holder":
            fn = node
    check("定位 _before_create_view_holder", fn is not None)
    if fn is not None:
        set_clickable_lines = []
        listener_lines = []
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr == "setClickable":
                set_clickable_lines.append(n.lineno)
            if n.func.attr in ("setOnClickListener", "setOnLongClickListener"):
                listener_lines.append(n.lineno)
        check("显式调用 root.setClickable(False)", bool(set_clickable_lines))
        check("setClickable 早于任何行内监听器挂载",
              bool(set_clickable_lines) and bool(listener_lines)
              and min(set_clickable_lines) < min(listener_lines))

        # 行内监听器必须被「无列表级钩子」的条件守卫
        guarded = False
        for n in ast.walk(fn):
            if not isinstance(n, ast.If):
                continue
            # 守卫条件里钩子标志可能以属性形式（self._x）或 getattr 的字符串键出现
            names = {t.attr for t in ast.walk(n.test) if isinstance(t, ast.Attribute)}
            names |= {t.value for t in ast.walk(n.test)
                      if isinstance(t, ast.Constant) and isinstance(t.value, str)}
            has_listener = any(
                isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and c.func.attr in ("setOnClickListener", "setOnLongClickListener")
                for c in ast.walk(n))
            if has_listener and {"_menu_hook_ok", "_click_hook_ok", "_longclick_hook_ok"} & names:
                guarded = True
        check("行内监听器仅在无列表级钩子时作为兜底挂载", guarded)

    # 诊断计数器齐全
    for key in ("menu_calls", "listener_calls", "created", "bound"):
        check("诊断计数器含 %s" % key, '"%s": 0' % key in src)

    # 版本演化：v1.0.4 不得含不可点击修复（历史保真），v1.0.5 必须含
    v104 = os.path.join(VERSIONS_DIR, "v1.0.4", "filter_enhancement.plugin")
    if os.path.isfile(v104):
        src104, _ = parse(v104)
        check("v1.0.4 不含不可点击修复（历史保真）", "setClickable(False)" not in src104)
    check("v1.0.5 含不可点击修复", "setClickable(False)" in src)


def main():
    test_latest()
    test_all_versions()
    test_v103_listener_hooks()
    test_v104_create_menu_dispatch()
    test_v104_wiring()
    test_v105_row_must_stay_non_clickable()
    test_v105_wiring()
    print("\n通过 %d 项，失败 %d 项。" % (PASSED[0], FAILED[0]))
    return 1 if FAILED[0] else 0


if __name__ == "__main__":
    sys.exit(main())
