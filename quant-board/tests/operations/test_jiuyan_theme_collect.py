# -*- coding: utf-8 -*-
"""韭研题材语料采集（v4 换源后仅产业树）测试——全部离线（mock 网络层），零真实 HTTP / 零 jev 调用。

锁定口径：
1. 产业树解析容忍真实响应的形状漂移（children 可能是 dict/单元素/列表/缺失）；
2. errCode 结构化：9=配额、1/110=鉴权失败，**不得**当成"空数据成功"；
3. 板块正文变更时刷新 `contentChangedDate`（"是否新催化"要可判定）；
4. 空载荷（errCode=0 但 0 节点）= 降级不是成功（§4.0，2026-10-20 实测缺陷）；
5. 事件层（timeline/news+list）已随 2026-10-23 方案 A 换源开盘啦退役——本文件不再有
   timeline 用例，事件层测试见 `test_kpl_theme_collect.py`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_theme_collect as C
from backend.operations import jiuyan_theme_fetch as F
from backend.operations import jiuyan_theme_store as S

INDUSTRY_PAYLOAD = {
    "errCode": 0,
    "data": [
        {"code": "0079", "group_name": "国产机器人", "level": 1, "hot": 19.11,
         "content": "1、2026年8月19日，宇树机器人上市，发行市值约609亿元。",
         "update_time": "2026-10-20 14:16:44",
         "children": {"code": "00790001", "group_name": "机器人零部件", "level": 2,
                      "hot": 8.09, "content": "2026年10月12日盘前，机构点评：交付量高增。",
                      "children": []}},
        {"code": "0120", "group_name": "物理AI", "level": 1, "hot": 14.89,
         "content": "2026年6月5日讯，英伟达官宣 NVIDIA Cosmos 3 物理AI模型。", "children": []},
    ],
}


# ── 解析层 ────────────────────────────────────────────────────────────
def test_parse_ai_industry_flattens_tree_and_keeps_board_level_content():
    out = F.parse_ai_industry_response(INDUSTRY_PAYLOAD)
    assert out["ok"] is True
    names = [n["name"] for n in out["nodes"]]
    assert names == ["国产机器人", "机器人零部件", "物理AI"]
    child = out["nodes"][1]
    assert child["parentCode"] == "0079" and child["path"] == ["国产机器人", "机器人零部件"]
    assert out["nodes"][0]["content"].startswith("1、2026年8月19日")


@pytest.mark.parametrize("payload,quota,auth", [
    ({"errCode": "9", "msg": "您今天的查阅次数已达到上限"}, True, False),
    ({"errCode": "110", "msg": "token无效"}, False, True),
    ({"errCode": "1", "msg": "登录失效"}, False, True),
])
def test_errcode_is_structured_never_silent_success(payload, quota, auth):
    out = F.parse_ai_industry_response(payload)
    assert out["ok"] is False
    assert bool(out.get("quota")) is quota and bool(out.get("authFailed")) is auth


# ── 存储层（假 collection，支持 $gte/$lte/sort 简化语义） ────────────────
def _match(doc, query):
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$gte" and (val is None or not val >= arg):
                    return False
                if op == "$lte" and (val is None or not val <= arg):
                    return False
                if op not in ("$gte", "$lte"):
                    raise AssertionError(f"fake 未支持 {op}")
        elif val != cond:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: doc.get(k) for k, v in projection.items() if v}


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, query, projection=None, sort=None):
        rows = [d for d in self.docs.values() if _match(d, query)]
        if sort:
            for key, direction in sort:
                rows = sorted(rows, key=lambda d: d.get(key) or "",
                              reverse=(direction == -1))
        return _project(rows[0], projection) if rows else None

    def replace_one(self, query, doc, upsert=False):
        self.docs[doc["_id"]] = dict(doc)
        return type("R", (), {"matched_count": 1, "upserted_id": doc["_id"]})()

    def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        doc = self.docs.get(_id)
        if doc is None:
            assert upsert, "fake 只支持 upsert=True"
            doc = {"_id": _id}
            self.docs[_id] = doc
        for path, delta in (update.get("$inc") or {}).items():
            head, _, tail = path.partition(".")
            if tail:
                doc.setdefault(head, {})[tail] = int(doc.get(head, {}).get(tail, 0)) + int(delta)
            else:
                doc[head] = int(doc.get(head, 0)) + int(delta)
        for path, value in (update.get("$set") or {}).items():
            head, _, tail = path.partition(".")
            if tail:
                doc.setdefault(head, {})[tail] = value
            else:
                doc[head] = value
        return type("R", (), {"matched_count": 1, "upserted_id": _id})()

    def find(self, query=None, projection=None):
        return [_project(d, projection) for d in self.docs.values() if _match(d, query or {})]

    def count_documents(self, query=None):
        return len(self.find(query or {}))


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def test_industry_content_change_tracking():
    db = FakeDb()
    parsed = F.parse_ai_industry_response(INDUSTRY_PAYLOAD)
    s1 = S.save_industry_nodes(db, fetch_date="2026-10-20", nodes=parsed["nodes"])
    assert s1 == {"written": 3, "contentChanged": 3, "withContent": 3}
    s2 = S.save_industry_nodes(db, fetch_date="2026-10-21", nodes=parsed["nodes"])
    assert s2["contentChanged"] == 0, "正文未变不得刷新变更日"
    doc = db["jiuyan_ai_industry"].docs["0079"]
    assert doc["contentChangedDate"] == "2026-10-20" and doc["lastFetchDate"] == "2026-10-21"

    changed = F.parse_ai_industry_response({**INDUSTRY_PAYLOAD, "data": [
        {**INDUSTRY_PAYLOAD["data"][1], "content": "2026年10月21日讯，新催化：GTC 柏林站开幕。"}]})
    s3 = S.save_industry_nodes(db, fetch_date="2026-10-21", nodes=changed["nodes"])
    assert s3["contentChanged"] == 1
    assert db["jiuyan_ai_industry"].docs["0120"]["contentChangedDate"] == "2026-10-21"


def test_empty_inbound_content_never_overwrites_existing():
    """服务端降级 payload（errCode=0 但 content 空）不得把已采证据覆盖成空（§4.0）。"""
    db = FakeDb()
    S.save_industry_nodes(db, fetch_date="2026-10-20",
                          nodes=F.parse_ai_industry_response(INDUSTRY_PAYLOAD)["nodes"])
    degraded = F.parse_ai_industry_response({**INDUSTRY_PAYLOAD, "data": [
        {**INDUSTRY_PAYLOAD["data"][1], "content": ""}]})
    S.save_industry_nodes(db, fetch_date="2026-10-21", nodes=degraded["nodes"])
    assert db["jiuyan_ai_industry"].docs["0120"]["content"].startswith("2026年6月5日讯")


# ── 编排层 ───────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """测试禁真实 sleep（间隔/退避都是运行时行为，不是被测逻辑）。"""
    monkeypatch.setattr(C, "INTER_CALL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(C, "RATE_LIMIT_RETRY_SLEEP_SECONDS", 0.0)


@pytest.fixture
def fake_auth(monkeypatch):
    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": True, "session": "s", "token": "t",
                                      "timestamp": "ts", "source": "cache+cache"})


def _patch_fetchers(monkeypatch, industry=None):
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: industry)


def test_collect_once_industry_ok(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch, industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is True and out["degraded"] == []
    assert out["industry"]["written"] == 3
    assert len(db["jiuyan_ai_industry"].docs) == 3
    assert out["callsThisRun"] == 1


def test_collect_once_all_sources_down_is_failure(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch, industry={"ok": False, "error": "quota", "nodes": []})
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is False and len(out["degraded"]) == 1
    assert not db.cols.get("jiuyan_ai_industry") or not db["jiuyan_ai_industry"].docs


def test_collect_once_dry_run_writes_no_business_docs(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch, industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", dry_run=True)
    assert out["dryRun"] is True and out["industry"]["written"] == 0
    assert not db.cols.get("jiuyan_ai_industry")
    # 额度计数照记：dry-run 也真发 HTTP，服务端照样扣额度（否则护栏会失真）
    assert out["callsThisRun"] == 1 and out["callsUsedTodayAfter"] == 1


def test_collect_once_auth_failure_is_visible(monkeypatch):
    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": False, "error": "登录失效", "authFailed": True})
    out = C.collect_once(db=FakeDb(), fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is False and out["authFailed"] is True and out["degraded"] == ["auth"]


def test_daily_budget_blocks_extra_calls_and_is_visible(monkeypatch, fake_auth):
    """护栏语义：已用+计划 > 预算 → 结构化跳过（不静默空跑）；跳过的源不计数。"""
    db = FakeDb()
    _patch_fetchers(monkeypatch, industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", budget=0)
    assert out["callsThisRun"] == 0
    assert out["skippedByBudget"] == ["ai_industry"]
    assert out["industry"]["fetched"] == 0 and out["industry"]["written"] == 0
    assert S.calls_recorded(db, "2026-10-20") == 0, "跳过的源不得计数"


# ── 调度门控 ─────────────────────────────────────────────────────────
def test_schedule_gate_degrades_when_bridge_down(monkeypatch):
    """bridge 不可用时不得把整步判失败：degrade 到 cache/周内启发，并在结果里留日历来源。"""
    from backend.operations import schedule as sch

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "weekday"))
    monkeypatch.setattr(sch.subprocess, "run", lambda *a, **k: type("P", (), {
        "returncode": 0,
        "stdout": '{"ok": true, "date": "2026-10-20", "degraded": []}',
        "stderr": ""})())
    out = sch.run_theme_corpus_collect_once("2026-10-20", collectors=("jiuyan",))
    assert out["ok"] is True and out["date"] == "2026-10-20"

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (False, "cache"))
    out2 = sch.run_theme_corpus_collect_once("2026-10-20")
    assert out2 == {"ok": True, "skipped": True, "reason": "non_trading_day",
                    "date": "2026-10-20", "calendarSource": "cache"}


# ── 空载荷（2026-10-20 实测缺陷回归） ─────────────────────────────────
def test_ok_but_empty_payload_is_not_silent_success(monkeypatch, fake_auth):
    """服务端间歇限流时返回 errCode=0 但空列表，原实现当"成功无数据"——必须显式降级。"""
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: {"ok": True, "nodes": []})
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", budget=12)
    assert out["emptySources"] == ["ai_industry"]
    assert out["degraded"] == ["ai_industry: 空载荷（errCode=0 但 0 节点，疑服务端限流/降级）"]
    assert out["ok"] is False, "唯一源空载荷 → 本次采集算失败，不得报成功"
    assert out["industry"]["written"] == 0 and not db.cols.get("jiuyan_ai_industry")


# ── KPL 标记行机读接口（2026-11-02 f4e65402 主路径回归，review 2026-11-02 Nit） ──
def test_schedule_kpl_marker_line_parse(monkeypatch):
    """kpl_theme_collect stdout 用 THEME_COLLECT_RESULT_JSON: 标记行承载机读 JSON；
    调度侧必须按标记提取（前面有降级披露行也不得截错），解析失败结构化 theme_collect_parse_failed。"""
    from backend.operations import schedule as sch

    payload = '{"ok": true, "date": "2026-11-02", "news": {"written": 50}, "degraded": []}'
    noisy = ("2026-11-02 降级披露: {'some': 'dict-text'}\n"
             "THEME_COLLECT_RESULT_JSON:" + payload + "\n")
    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "weekday"))
    captured = {}

    def fake_run(*a, **k):
        captured["cmd"] = a[0] if a else k.get("args")
        return type("P", (), {"returncode": 0, "stdout": noisy, "stderr": ""})()
    monkeypatch.setattr(sch.subprocess, "run", fake_run)
    out = sch.run_theme_corpus_collect_once("2026-11-02", collectors=("kpl",))
    assert out["ok"] is True
    kpl = (out.get("collectors") or {}).get("kpl") or {}
    assert kpl.get("ok") is True and kpl.get("stats", {}).get("news", {}).get("written") == 50, \
        "标记行分支：披露行在前也不得解析失败"


def test_schedule_kpl_unparseable_stdout_is_structured_failure(monkeypatch):
    """stdout 无标记行且无可解析 JSON → 结构化 theme_collect_parse_failed，不得静默成功。"""
    from backend.operations import schedule as sch

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "weekday"))
    monkeypatch.setattr(sch.subprocess, "run", lambda *a, **k: type("P", (), {
        "returncode": 0, "stdout": "Traceback-free 但全是人类可读文本", "stderr": ""})())
    out = sch.run_theme_corpus_collect_once("2026-11-02", collectors=("kpl",))
    kpl = (out.get("collectors") or {}).get("kpl") or {}
    assert kpl.get("ok") is False and kpl.get("error", {}).get("code") == "theme_collect_parse_failed"
