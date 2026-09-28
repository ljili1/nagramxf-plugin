# -*- coding: utf-8 -*-
"""filter_sentinel 纯 Python 核心的离线单元测试（CPython 直接运行，无需 Java）。

运行：
    python test_filter_sentinel.py
"""
import importlib.util
from importlib.machinery import SourceFileLoader
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_PATH = os.path.join(HERE, "filter_sentinel.plugin")

_loader = SourceFileLoader("filter_sentinel", PLUGIN_PATH)
spec = importlib.util.spec_from_loader("filter_sentinel", _loader)
fs = importlib.util.module_from_spec(spec)
_loader.exec_module(fs)


# ---------------------------------------------------------------------------
# 测试替身：模拟 Java Pattern 的 matcher().find() 接口
# ---------------------------------------------------------------------------

class _Matcher(object):
    def __init__(self, pattern, text):
        self._pattern = pattern
        self._text = text

    def find(self):
        return self._pattern.search(self._text) is not None


class FakePattern(object):
    def __init__(self, regex, ignore_case=False):
        flags = re.MULTILINE | (re.IGNORECASE if ignore_case else 0)
        self._re = re.compile(regex, flags)

    def matcher(self, text):
        return _Matcher(self._re, text)


class FakeFilter(object):
    _seq = [0]

    def __init__(self, regex, enabled=True, reversed_=False, ignore_case=True, fid=None):
        FakeFilter._seq[0] += 1
        self.id = fid or "f%d" % FakeFilter._seq[0]
        self.regex = regex
        self.enabled = enabled
        self.reversed = reversed_
        self.pattern = FakePattern(regex, ignore_case) if regex else None


# ---------------------------------------------------------------------------
# 极简断言框架
# ---------------------------------------------------------------------------

PASSED = [0]
FAILED = [0]


def check(name, cond):
    if cond:
        PASSED[0] += 1
        print("  PASS  %s" % name)
    else:
        FAILED[0] += 1
        print("  FAIL  %s" % name)


# ---------------------------------------------------------------------------
# is_filter_match
# ---------------------------------------------------------------------------

def test_is_filter_match():
    print("[is_filter_match]")
    f = FakeFilter(r"广告")
    check("正向命中", fs.is_filter_match(f, "这是一条广告", False))
    check("正向未命中", not fs.is_filter_match(f, "正常消息", False))
    check("禁用规则不命中", not fs.is_filter_match(
        FakeFilter(r"广告", enabled=False), "广告", False))
    check("空文本不命中", not fs.is_filter_match(f, "", False))
    check("pattern 为空不命中", not fs.is_filter_match(
        FakeFilter(""), "任意", False))
    check("None 规则不命中", not fs.is_filter_match(None, "广告", False))

    rev = FakeFilter(r"安全词", reversed_=True)
    check("反向规则：未命中即过滤", fs.is_filter_match(rev, "没有那个词", False))
    check("反向规则：命中即放行", not fs.is_filter_match(rev, "包含安全词", False))
    check("反向规则在遮罩模式下被禁用", not fs.is_filter_match(rev, "没有那个词", True))


# ---------------------------------------------------------------------------
# collect_matched
# ---------------------------------------------------------------------------

def test_collect_matched():
    print("[collect_matched]")
    chat = [FakeFilter(r"招聘", fid="c1"), FakeFilter(r"广告", fid="c2")]
    shared = [FakeFilter(r"广告", fid="s1"), FakeFilter(r"抽奖", fid="s2"),
              FakeFilter(r"内推", fid="s3")]

    # 群聊（dialog_id < 0 语义 -> is_private_dialog=False）：通用规则参与
    # 文本 "招聘广告来了" 同时含「招聘」「广告」-> 本聊天命中 2 条
    m = fs.collect_matched(chat, shared, set(), "招聘广告来了", False, False, False)
    check("群聊：本聊天命中 2 条", len(m["chat"]) == 2
          and {f.id for f in m["chat"]} == {"c1", "c2"})
    check("群聊：通用命中 1 条", len(m["shared"]) == 1 and m["shared"][0].id == "s1")
    check("群聊：suppressed_shared=False", not m["suppressed_shared"])

    # 排除的通用规则不参与
    m = fs.collect_matched(chat, shared, {"s1"}, "招聘广告", False, False, False)
    check("排除通用规则后不再命中", len(m["shared"]) == 0)

    # 私聊 + 未开启「在聊天中启用通用规则」：整体跳过通用
    m = fs.collect_matched(chat, shared, set(), "招聘广告", False, True, False)
    check("私聊未启用通用：仅本聊天命中", len(m["chat"]) == 2 and len(m["shared"]) == 0)
    check("私聊未启用通用：suppressed_shared=True", m["suppressed_shared"])

    # 私聊 + 开启：通用参与
    m = fs.collect_matched(chat, shared, set(), "招聘广告", False, True, True)
    check("私聊启用通用：通用参与", len(m["shared"]) == 1)

    # 无命中
    m = fs.collect_matched(chat, shared, set(), "完全无关", False, False, False)
    check("无命中", not m["chat"] and not m["shared"])


# ---------------------------------------------------------------------------
# rule_display_text / format_rules_report
# ---------------------------------------------------------------------------

def test_formatting():
    print("[formatting]")
    check("正向展示原文", fs.rule_display_text(FakeFilter(r"广告")) == "广告")
    check("反向加 != 前缀", fs.rule_display_text(
        FakeFilter(r"安全词", reversed_=True)) == "!= 安全词")

    matched = {
        "chat": [FakeFilter(r"招聘", fid="c1")],
        "shared": [FakeFilter(r"广告", fid="s1"), FakeFilter(r"抽奖", fid="s2")],
        "suppressed_shared": False,
    }
    report = fs.format_rules_report(matched, dialog_id=-100123)
    check("报告含总数", "共命中 3 条规则" in report)
    check("报告含本聊天分组", "【本聊天规则】" in report and "1. 招聘" in report)
    check("报告含通用分组", "【通用规则】" in report and "2. 抽奖" in report)
    check("报告含聊天 ID", "-100123" in report)

    empty = fs.format_rules_report({"chat": [], "shared": [], "suppressed_shared": True})
    check("空结果提示未命中", "未命中任何规则" in empty)
    check("空结果标注私聊抑制", "通用规则未启用" in empty)


# ---------------------------------------------------------------------------
# FilteredStore
# ---------------------------------------------------------------------------

def test_store():
    print("[FilteredStore]")
    store = fs.FilteredStore()
    check("初始计数 0", store.count(0, -100) == 0)

    n = store.record(0, -100, 1, ["广告"], "买课广告")
    check("首次记录返回 1", n == 1)
    n = store.record(0, -100, 1, ["广告"], "买课广告")
    check("同消息去重返回 1", n == 1)
    n = store.record(0, -100, 2, ["抽奖", "广告"], "转发抽奖")
    check("新消息返回 2", n == 2)
    check("其他聊天互不影响", store.count(0, -200) == 0)
    check("多账号互不影响", store.count(1, -100) == 0)

    snap = store.snapshot(0, -100)
    check("快照条数", snap["count"] == 2)
    check("规则并集去重且保序", snap["rules"] == ["广告", "抽奖"])
    check("样例记录", snap["previews"] == ["买课广告", "转发抽奖"])

    store.record(0, -100, 3, [], None)
    check("空规则也可记录", store.count(0, -100) == 3)

    store.clear(0, -100)
    check("清除后归零", store.count(0, -100) == 0 and store.snapshot(0, -100) is None)

    store.record(0, -100, 9, ["x"])
    store.record(1, -100, 9, ["y"])
    store.clear_all()
    check("全部清除", store.count(0, -100) == 0 and store.count(1, -100) == 0)

    # msg_id 为 None 时不计入条数但规则仍合并
    store.record(0, -100, None, ["仅规则"])
    check("无 msg_id 不计数", store.count(0, -100) == 0)
    check("无 msg_id 规则仍合并", store.snapshot(0, -100)["rules"] == ["仅规则"])


# ---------------------------------------------------------------------------
# compute_placeholder_state / format_placeholder_text（v2 原位占位条）
# ---------------------------------------------------------------------------

def test_placeholder_state():
    print("[compute_placeholder_state]")
    # 列表下标 0 = 最新消息（屏幕底部），下标越大越靠上（越旧）
    # 段首 = 段内最小下标（占位条显示在整段下方，进入聊天时最先看到）
    # 过滤分布: idx 1,2,3 连续被过滤；idx 5 单独被过滤
    filtered = {1, 2, 3, 5}
    fn = lambda i: i in filtered

    state, run = fs.compute_placeholder_state(fn, 8, 0)
    check("未过滤消息: gone", state == "gone" and run == [])

    state, run = fs.compute_placeholder_state(fn, 8, 1)
    check("段首（最新一条）: head 且 run 向更旧方向覆盖整段",
          state == "head" and run == [1, 2, 3])

    state, run = fs.compute_placeholder_state(fn, 8, 2)
    check("段中: collapsed", state == "collapsed" and run == [])

    state, run = fs.compute_placeholder_state(fn, 8, 3)
    check("段尾（最旧一条）: collapsed", state == "collapsed")

    state, run = fs.compute_placeholder_state(fn, 8, 5)
    check("孤立过滤: head 且 run 长度 1", state == "head" and run == [5])

    state, run = fs.compute_placeholder_state(fn, 8, 7)
    check("列表顶未过滤: gone", state == "gone")

    state, run = fs.compute_placeholder_state(fn, 8, -1)
    check("负下标: gone", state == "gone")
    state, run = fs.compute_placeholder_state(fn, 8, 99)
    check("越界下标: gone", state == "gone")

    # 全部过滤：段首在最小下标，run 覆盖全表
    allf = lambda i: True
    state, run = fs.compute_placeholder_state(allf, 4, 0)
    check("全过滤段首为最小下标", state == "head" and run == [0, 1, 2, 3])
    state, run = fs.compute_placeholder_state(allf, 4, 3)
    check("全过滤最旧条 collapsed", state == "collapsed")

    text = fs.format_placeholder_text(3)
    check("占位文案含条数", "已隐藏 3 条消息" in text)
    check("占位文案含操作提示", "点击展开" in text and "长按看规则" in text)


def main():
    test_is_filter_match()
    test_collect_matched()
    test_formatting()
    test_store()
    test_placeholder_state()
    print("\n通过 %d 项，失败 %d 项。" % (PASSED[0], FAILED[0]))
    return 1 if FAILED[0] else 0


if __name__ == "__main__":
    sys.exit(main())
