# -*- coding: utf-8 -*-
"""题材证据块（L3 消费层）测试——纯假 collection，零网络零模型。

锁定口径：
1. **确定性映射**：本名精确 > 本名包含 > 别名包含；别名不得参与精确匹配
   （「AI硬件」的别名「算力」不能把「算力概念」判成 exact）；
2. **fail-visible**：语料未采集 / 板块未映射 / 无未来事件，三种"空"必须各自说清，
   不得用"无催化"或 T-1 数据冒充；
3. 事件按**事件日期**进窗，早报类（当日事件清单）单列一节，不混进既定日程；
4. 文本带来源与时间戳（热度/正文更新日/事件录入日），并可按字符预算截断。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_event_digest as D


class FakeCol:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs:
            ok = True
            for k, cond in (query or {}).items():
                v = d.get(k)
                if isinstance(cond, dict):
                    for op, arg in cond.items():
                        if op == "$gte" and (v is None or not v >= arg):
                            ok = False
                        elif op == "$lte" and (v is None or not v <= arg):
                            ok = False
                        elif op not in ("$gte", "$lte"):
                            raise AssertionError(op)
                elif v != cond:
                    ok = False
            if ok:
                out.append({k: d.get(k) for k in (projection or d)})
        return out

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query, projection)
        return rows[0] if rows else None

    def count_documents(self, query=None):
        return len(self.find(query))


class FakeDb:
    def __init__(self, timeline=None, industry=None):
        self.cols = {"jiuyan_timeline": FakeCol(timeline), "jiuyan_ai_industry": FakeCol(industry)}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


NODES = [
    {"code": "0079", "name": "国产机器人", "level": 1, "hot": 19.11,
     "content": "1、2026年8月19日，宇树机器人上市，发行市值约609亿元。",
     "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-20"},
    {"code": "0120", "name": "物理AI", "level": 1, "hot": 14.89,
     "content": "2026年6月5日讯，英伟达官宣 NVIDIA Cosmos 3 物理AI模型。",
     "contentChangedDate": "2026-10-18", "lastFetchDate": "2026-10-20"},
    {"code": "0300", "name": "算力概念", "level": 1, "hot": 5.0, "content": "",
     "contentChangedDate": None, "lastFetchDate": "2026-10-20"},
]

EVENTS = [
    {"date": "2026-10-21", "title": "英伟达GTC大会",
     "content": "黄仁勋将在21日发表主题演讲，聚焦物理AI与机器人。",
     "grade": 5, "themes": ["物理AI", "机器人"], "firstSeenDate": "2026-10-20"},
    {"date": "2026-10-20", "title": "早报",
     "content": "1、热点事件 1）物理AI：英伟达GTC大会10月20日至22日在德国柏林举行。",
     "grade": 6, "themes": [], "firstSeenDate": "2026-10-20"},
    {"date": "2026-10-23", "title": "全国药品交易会", "content": "药交会", "grade": 3,
     "themes": [], "firstSeenDate": "2026-10-19"},
    {"date": "2026-10-30", "title": "远期事件", "content": "超出窗口", "grade": 2,
     "themes": [], "firstSeenDate": "2026-10-20"},
]


def _db(**kw):
    return FakeDb(timeline=kw.pop("timeline", EVENTS), industry=kw.pop("industry", NODES))


# ── 名字归一与匹配优先级 ────────────────────────────────────────────────
def test_normalize_strips_noise_and_suffixes():
    assert D.normalize_name("机器人概念") == "机器人"
    assert D.normalize_name(" Ai 硬件 ") == "Ai硬件"
    assert D.normalize_name("ST摘帽") == "ST摘帽"
    assert D.normalize_name(None) == ""


def test_match_industry_precedence_and_alias_not_exact():
    nodes = NODES + [{"code": "x", "name": "机器人", "level": 1, "hot": 1.0, "content": "c"}]
    m = D.match_industry(nodes, "机器人")
    assert m["matched"] and m["method"] == "exact" and m["node"]["name"] == "机器人"

    m2 = D.match_industry(NODES, "机器人")            # 无同名 → 本名包含，取热度最高
    assert m2["method"] == "contains" and m2["node"]["name"] == "国产机器人"

    m3 = D.match_industry(NODES, "AI硬件")            # 别名「算力」→ 只能算 alias
    assert m3["method"] == "alias" and m3["node"]["name"] == "算力概念"

    m4 = D.match_industry(NODES, "培育钻石")
    assert m4["matched"] is False and m4["node"] is None


def test_match_events_is_deterministic_contains():
    hits = D.match_events(EVENTS, "机器人")
    titles = [e["title"] for e in hits]
    assert "英伟达GTC大会" in titles and "全国药品交易会" not in titles
    assert D.match_events(EVENTS, "") == []


# ── 证据块 ────────────────────────────────────────────────────────────
def test_block_contains_catalyst_events_and_timestamps():
    out = D.build_theme_evidence_block(_db(), board_name="物理AI", date="2026-10-20")
    text = out["text"]
    assert text.startswith(D.BLOCK_HEADER)
    assert "板块级催化原文（韭研产业树「物理AI」，匹配方式 exact" in text
    assert "正文更新 2026-10-18=2 天前" in text
    assert "Cosmos 3" in text
    # 早报单列一节，不混进既定日程
    assert "当日事件清单（韭研「早报」" in text
    assert "2026-10-21（T+1） 英伟达GTC大会（重要度5，录入 2026-10-20" in text
    assert "2026-10-30" not in text, "远期事件不得进窗"
    assert out["state"]["ok"] is True


def test_block_fail_visible_paths():
    # 1) 语料未采集
    empty = D.build_theme_evidence_block(FakeDb(), board_name="机器人", date="2026-10-20")
    assert "未采集" in empty["text"] and "无数据 ≠ 无催化" in empty["text"]
    assert empty["state"]["ok"] is False

    # 2) 板块未映射
    out = D.build_theme_evidence_block(_db(), board_name="培育钻石", date="2026-10-20")
    assert "未映射" in out["text"] and "不代表无催化" in out["text"]
    assert out["industry"] is None

    # 3) 有节点但正文为空
    db = _db(industry=[{"code": "0300", "name": "存储芯片", "level": 1, "hot": 1.2,
                        "content": "", "lastFetchDate": "2026-10-20"}])
    out3 = D.build_theme_evidence_block(db, board_name="存储", date="2026-10-20")
    assert "无催化正文" in out3["text"] and "原文为空" in out3["text"]

    # 4) 无未来事件
    db4 = _db(timeline=[{"date": "2026-10-30", "title": "远期", "content": "x"}])
    out4 = D.build_theme_evidence_block(db4, board_name="机器人", date="2026-10-20")
    assert "未来 3 日既定事件：无匹配" in out4["text"] and "无数据 ≠ 无催化" in out4["text"]


def test_block_marks_stale_corpus():
    db = _db(industry=[{"code": "0079", "name": "国产机器人", "level": 1, "hot": 1.0,
                        "content": "催化", "lastFetchDate": "2026-10-17"}],
             timeline=[{"date": "2026-10-21", "title": "x", "content": "y",
                        "lastFetchDate": "2026-10-17"}])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-20")
    assert "非当日" in out["text"] and out["state"]["stale"] is True


def test_block_respects_char_budget():
    long_content = "催化" * 400
    db = _db(industry=[{"code": "0079", "name": "机器人", "level": 1, "hot": 1.0,
                        "content": long_content, "lastFetchDate": "2026-10-20"}],
             timeline=[{"date": "2026-10-21", "title": "机器人大会",
                        "content": "长文" * 500, "lastFetchDate": "2026-10-20"}])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-20",
                                       content_chars=100, max_events=1)
    assert "…[截断，原文 800 字]" in out["text"]
    assert len(out["text"]) < 1200
