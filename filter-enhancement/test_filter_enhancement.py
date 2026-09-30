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
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_PATH = os.path.join(HERE, "filter_enhancement.plugin")
VERSIONS_DIR = os.path.join(HERE, "versions")
ALL_VERSIONS = ["v1.0.0", "v1.0.1", "v1.0.2"]

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
    print("== 主版本（filter_enhancement.plugin，应为 v1.0.2）==")
    src, tree = parse(PLUGIN_PATH)

    compile(src, PLUGIN_PATH, "exec")
    check("语法可编译", True)

    meta = module_metadata(tree)
    check("__id__ = filter_enhancement", meta.get("__id__") == "filter_enhancement")
    check("__id__ 符合宿主格式",
          bool(re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{1,31}$", meta.get("__id__", ""))))
    check("__name__ 非空", bool(meta.get("__name__")))
    check("__version__ = 1.0.2", meta.get("__version__") == "1.0.2")
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
        if ver == "v1.0.2":
            path = PLUGIN_PATH
        else:
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


def main():
    test_latest()
    test_all_versions()
    print("\n通过 %d 项，失败 %d 项。" % (PASSED[0], FAILED[0]))
    return 1 if FAILED[0] else 0


if __name__ == "__main__":
    sys.exit(main())
