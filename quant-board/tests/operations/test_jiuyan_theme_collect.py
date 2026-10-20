# -*- coding: utf-8 -*-
"""韭研题材/事件语料采集（L3）测试——全部离线（mock 网络层），零真实 HTTP / 零 jev 调用。

锁定口径（2026-10-20 用户裁决「从 L3 开始做」）：
1. 三端点的解析必须容忍真实响应的形状漂移（data 有时 list、有时 {msg,data}）；
2. errCode 结构化：9=配额、1/110=鉴权失败，**不得**当成"空数据成功"；
3. 事件按 (事件日期, 标题) 去重——news 与 list 会给重复事件（实测 20 对）；
4. `firstSeenAt` 不随重采覆盖（"事件是不是今天新出现的"要可判定）；
5. 板块正文变更时刷新 `contentChangedDate`（"是否新催化"要可判定）；
6. 任一源失败只降级该源，全源失败才 ok=False（§4.0 fail-visible）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_theme_collect as C
from backend.operations import jiuyan_theme_fetch as F
from backend.operations import jiuyan_theme_store as S

NEWS_PAYLOAD = {
    "errCode": 0, "msg": "",
    "data": [
        {"date": "2026-10-20", "list": [
            {"article_id": "a1", "title": "早报",
             "content": "1、热点事件\n1）物理AI：英伟达GTC大会10月20日至22日在德国柏林举行。"},
            {"article_id": "a2", "title": "第九届半导体大硅片论坛",
             "content": "核心特色：聚焦300mm大硅片"},
        ]},
        {"date": "2026-10-21", "list": [
            {"article_id": "a3", "title": "英伟达GTC大会",
             "content": "黄仁勋将在21日发表主题演讲。"},
        ]},
    ],
}

LIST_PAYLOAD = {
    "errCode": "0",
    "data": [
        {"date": "2026-10-21", "list": [
            # 与 news 同日期同标题 → 必须合并成一条（list 侧带 grade/themes）
            {"article_id": "a3", "title": "英伟达GTC大会", "content": "",
             "timeline": {"timeline_id": "t3", "date": "2026-10-21", "grade": 5,
                          "create_time": "2026-10-19 10:00:00",
                          "theme_list": [{"name": "物理AI"}, {"name": "机器人"}]}},
            {"article_id": "a4", "title": "2026世界智能网联汽车大会", "content": "10月21日至23日在北京举办",
             "timeline": {"timeline_id": "t4", "date": "2026-10-21", "grade": 3,
                          "create_time": "2026-10-15 09:00:00", "theme_list": []}},
        ]},
    ],
}

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
def test_parse_timeline_news_accepts_both_shapes():
    assert F.parse_timeline_news({"data": [{"date": "2026-10-20", "list": [
        {"article_id": "a", "title": "t", "content": "c"}]}]})["days"][0]["items"][0]["title"] == "t"
    wrapped = F.parse_timeline_news({"data": {"msg": "", "data": [
        {"date": "2026-10-20", "list": [{"title": "t"}]}]}})
    assert wrapped["ok"] is True and wrapped["days"][0]["items"][0]["title"] == "t"
    bad = F.parse_timeline_news({"data": "oops"})
    assert bad["ok"] is False and bad["days"] == []


def test_parse_timeline_list_extracts_grade_themes_and_future_dates():
    out = F.parse_timeline_list_response(LIST_PAYLOAD)
    assert out["ok"] is True and len(out["items"]) == 2
    first = out["items"][0]
    assert first["date"] == "2026-10-21" and first["grade"] == 5
    assert first["themes"] == ["物理AI", "机器人"]
    assert first["createTime"] == "2026-10-19 10:00:00"
    assert out["items"][1]["grade"] == 3 and out["items"][1]["themes"] == []


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
    for parser in (F.parse_timeline_news_response, F.parse_timeline_list_response,
                   F.parse_ai_industry_response):
        out = parser(payload)
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
        for d in self.docs.values():
            if _match(d, query):
                return _project(d, projection)
        return None

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


def test_timeline_dedupe_by_event_identity_and_keep_first_seen():
    db = FakeDb()
    news = F.parse_timeline_news_response(NEWS_PAYLOAD)
    listing = F.parse_timeline_list_response(LIST_PAYLOAD)
    items = [{**it, "date": d["date"], "grade": None, "createTime": None, "themes": [],
              "timelineId": None} for d in news["days"] for it in d["items"]]
    items += listing["items"]
    s1 = S.save_timeline_items(db, fetch_date="2026-10-20", source="news_list", items=items)
    assert s1["written"] == 4          # 早报/半导体论坛/GT大会(合并)/智能网联
    assert len(db["jiuyan_timeline"].docs) == 4, "同日期同标题必须合并，不得建平行文档"
    gt = [d for d in db["jiuyan_timeline"].docs.values() if d["title"] == "英伟达GTC大会"][0]
    assert gt["grade"] == 5 and gt["themes"] == ["物理AI", "机器人"]
    assert gt["content"].startswith("黄仁勋"), "news 侧正文要与 list 侧的 grade 合并保留"
    assert gt["sources"] == ["news_list"] and gt["forwardDays"] == 1

    # 次日重采：firstSeenAt/Date 不覆盖，"新近度"仍可判定
    first_seen = gt["firstSeenAt"]
    S.save_timeline_items(db, fetch_date="2026-10-21", source="news_list", items=items)
    gt2 = [d for d in db["jiuyan_timeline"].docs.values() if d["title"] == "英伟达GTC大会"][0]
    assert gt2["firstSeenAt"] == first_seen and gt2["firstSeenDate"] == "2026-10-20"
    assert gt2["lastFetchDate"] == "2026-10-21"


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


def test_timeline_window_only_uses_event_date():
    db = FakeDb()
    S.save_timeline_items(db, fetch_date="2026-10-20", source="news_list", items=[
        {"date": "2026-10-21", "title": "A", "content": "", "timelineId": "t1"},
        {"date": "2026-10-25", "title": "B", "content": "", "timelineId": "t2"},
        {"date": "2026-10-16", "title": "C", "content": "", "timelineId": "t3"},
    ])
    got = S.get_timeline_window(db, date="2026-10-20", window_days=3)
    assert [d["title"] for d in got] == ["A"], "窗口按事件日期过滤，不含远期/过期事件"
    got2 = S.get_timeline_window(db, date="2026-10-20", window_days=3, include_past_recent=5)
    assert [d["title"] for d in got2] == ["C", "A"]


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


def _patch_fetchers(monkeypatch, news=None, listing=None, industry=None):
    monkeypatch.setattr(F, "fetch_timeline_news", lambda **kw: news)
    monkeypatch.setattr(F, "fetch_timeline_list", lambda **kw: listing)
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: industry)


def test_collect_once_persists_and_tolerates_partial_failure(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news=F.parse_timeline_news_response(NEWS_PAYLOAD),
                    listing={"ok": False, "error": "timeline/list: HTTP 500", "items": []},
                    industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is True, "单源失败只降级，不算采集失败"
    assert out["degraded"] and "timeline_list" in out["degraded"][0]
    assert out["industry"]["written"] == 3
    # news 3 条（早报/论坛/GTC）
    assert len(db["jiuyan_timeline"].docs) == 3


def test_collect_once_all_sources_down_is_failure(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news={"ok": False, "error": "quota", "days": []},
                    listing={"ok": False, "error": "quota", "items": []},
                    industry={"ok": False, "error": "quota", "nodes": []})
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is False and len(out["degraded"]) == 3
    assert not db.cols or not db["jiuyan_timeline"].docs


def test_collect_once_dry_run_writes_no_business_docs(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news=F.parse_timeline_news_response(NEWS_PAYLOAD),
                    listing=F.parse_timeline_list_response(LIST_PAYLOAD),
                    industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", dry_run=True)
    assert out["dryRun"] is True and out["timeline"]["written"] == 0
    assert not db.cols.get("jiuyan_timeline") and not db.cols.get("jiuyan_ai_industry")
    # 额度计数照记：dry-run 也真发 HTTP，服务端照样扣额度（否则护栏会失真）
    assert out["callsThisRun"] == 3 and out["callsUsedTodayAfter"] == 3


def test_collect_once_auth_failure_is_visible(monkeypatch):
    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": False, "error": "登录失效", "authFailed": True})
    out = C.collect_once(db=FakeDb(), fetch_date="2026-10-20", date="2026-10-20")
    assert out["ok"] is False and out["authFailed"] is True and out["degraded"] == ["auth"]


# ── 调度门控（2026-10-20 重启实测：theme_gate_failed） ────────────────────
def test_schedule_gate_degrades_when_bridge_down(monkeypatch):
    """bridge 不可用时不得把整步判失败：degrade 到 cache/周内启发，并在结果里留日历来源。"""
    from backend.operations import schedule as sch

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "weekday"))
    monkeypatch.setattr(sch.subprocess, "run", lambda *a, **k: type("P", (), {
        "returncode": 0,
        "stdout": '{"ok": true, "date": "2026-10-20", "degraded": []}',
        "stderr": ""})())
    out = sch.run_jiuyan_theme_collect_once("2026-10-20")
    assert out["ok"] is True and out["date"] == "2026-10-20"

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (False, "cache"))
    out2 = sch.run_jiuyan_theme_collect_once("2026-10-20")
    assert out2 == {"ok": True, "skipped": True, "reason": "non_trading_day",
                    "date": "2026-10-20", "calendarSource": "cache"}


# ── 额度护栏与分源（2026-10-20 实测：题材端点日额度被探测烧穿后当天全灭） ──
def test_daily_budget_blocks_extra_calls_and_is_visible(monkeypatch, fake_auth):
    """护栏语义：防失控调用（不是日额度断言——errCode=9 实为短时限流）。"""
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news=F.parse_timeline_news_response(NEWS_PAYLOAD),
                    listing=F.parse_timeline_list_response(LIST_PAYLOAD),
                    industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    first = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                           sources=("timeline_news",), budget=3)
    assert first["callsThisRun"] == 1 and first["callsUsedTodayAfter"] == 1
    assert S.calls_recorded(db, "2026-10-20") == 1
    # 已用 1、预算 3：本次要 3 个源 → 只放 2 个。**砍源按价值**（`SOURCE_SHED_PRIORITY`）：
    # 先砍 timeline_list（lowest），保住 ai_industry——它是 high_ge65「新催化」唯一入口
    # （2026-10-20 实测教训：原实现按 want 顺序砍 → industry 最先死，730 节点正文停在旧日）
    second = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", budget=3)
    assert second["sources"] == ["timeline_news", "ai_industry"]
    assert second["skippedByBudget"] == ["timeline_list"]
    assert S.calls_recorded(db, "2026-10-20") == 3
    # 额度用尽：本次调用全部跳过，但结果仍是"结构化跳过"而不是"无数据成功"
    third = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20", budget=3)
    assert third["callsThisRun"] == 0 and third["sources"] == []
    # 额度耗尽：三个源全跳；列表顺序 = 保留优先级降序（industry 最高 → 排最前）
    assert third["skippedByBudget"] == ["ai_industry", "timeline_news", "timeline_list"]
    assert third["industry"]["fetched"] == 0 and third["industry"]["written"] == 0
    assert S.calls_recorded(db, "2026-10-20") == 3, "跳过的源不得计数"


def test_split_sources_call_only_what_is_asked(monkeypatch, fake_auth):
    """盘前只要事件日历、收盘后只要催化正文：不拉不需要的源，减少调用。"""
    db = FakeDb()
    calls: list[str] = []
    monkeypatch.setattr(F, "fetch_timeline_news", lambda **kw: calls.append("news") or {
        "ok": True, "days": []})
    monkeypatch.setattr(F, "fetch_timeline_list", lambda **kw: calls.append("list") or {
        "ok": True, "items": []})
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: calls.append("industry") or {
        "ok": True, "nodes": []})
    pre = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                         sources=("timeline_news", "timeline_list"))
    assert calls == ["news", "list"] and pre["callsThisRun"] == 2
    calls.clear()
    post = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                          sources=("ai_industry",))
    assert calls == ["industry"] and post["callsThisRun"] == 1
    assert S.calls_recorded(db, "2026-10-20") == 3


def test_all_requested_sources_failing_marks_failure_not_success(monkeypatch, fake_auth):
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news={"ok": False, "error": "quota", "days": []},
                    listing={"ok": False, "error": "quota", "items": []},
                    industry={"ok": False, "error": "quota", "nodes": []})
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                         sources=("timeline_news",))
    assert out["ok"] is False and out["degraded"] == ["timeline_news: quota"]
    assert S.calls_recorded(db, "2026-10-20") == 1, "失败的请求照样计数（额度已被扣）"


def test_rate_limited_source_is_retried_once_then_degrades(monkeypatch, fake_auth):
    """限流（errCode=9）时退避重试一次；仍限流则结构化降级，且两次都计数（额度已被扣）。"""
    db = FakeDb()
    attempts: list[str] = []

    def flaky(**kw):
        attempts.append("news")
        if len(attempts) == 1:
            return {"ok": False, "rateLimited": True, "quota": True, "error": "timeline_news: 限流"}
        return F.parse_timeline_news_response(NEWS_PAYLOAD)

    monkeypatch.setattr(F, "fetch_timeline_news", flaky)
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                         sources=("timeline_news",), budget=12)
    assert len(attempts) == 2 and out["ok"] is True and out["degraded"] == []
    assert out["callsUsedTodayAfter"] == 2, "重试也是一次真实请求，必须计数"

    monkeypatch.setattr(F, "fetch_timeline_news", lambda **kw: {
        "ok": False, "rateLimited": True, "quota": True, "error": "timeline_news: 限流"})
    db2 = FakeDb()
    out2 = C.collect_once(db=db2, fetch_date="2026-10-21", date="2026-10-21",
                          sources=("timeline_news",), budget=12)
    assert out2["ok"] is False and "限流" in out2["degraded"][0]
    assert S.calls_recorded(db2, "2026-10-21") == C.RATE_LIMIT_MAX_RETRIES + 1


def test_ok_but_empty_payload_is_not_silent_success(monkeypatch, fake_auth):
    """实测缺陷（2026-10-20 15:45 调度）：服务端间歇限流时返回 errCode=0 但空列表，
    原实现当"成功无数据"——把限流伪装成"今天没题材"。空载荷必须显式降级（§4.0）。"""
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: {"ok": True, "nodes": []})
    out = C.collect_once(db=db, fetch_date="2026-10-20", date="2026-10-20",
                         sources=("ai_industry",), budget=12)
    assert out["emptySources"] == ["ai_industry"]
    assert out["degraded"] == ["ai_industry: 空载荷（errCode=0 但 0 条，疑服务端限流/降级）"]
    assert out["ok"] is False, "唯一请求的源空载荷 → 本次采集算失败，不得报成功"
    assert out["industry"]["written"] == 0 and not db.cols.get("jiuyan_ai_industry")

    # 多源时：单个源空载荷只降级该源，其余源正常算成功（§4.0 fail-visible 但不全军覆没）
    db2 = FakeDb()
    monkeypatch.setattr(F, "fetch_ai_industry", lambda **kw: {"ok": True, "nodes": []})
    monkeypatch.setattr(F, "fetch_timeline_list", lambda **kw: F.parse_timeline_list_response(LIST_PAYLOAD))
    out2 = C.collect_once(db=db2, fetch_date="2026-10-20", date="2026-10-20",
                          sources=("timeline_list", "ai_industry"), budget=12)
    assert out2["ok"] is True and out2["degraded"] == [out["degraded"][0]]
    assert out2["timeline"]["written"] == 2


# ── 题材层龙头投喂挂链（2026-10-20 用户裁决：每日自动投喂，累积到 20 交易日） ──
def _patch_leader_subprocess(monkeypatch, seen: list, stdout="{\"ok\": true, \"leaders\": 13}", rc=0):
    from backend.operations import schedule as sch

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return type("P", (), {"returncode": rc, "stdout": stdout, "stderr": ""})()
    monkeypatch.setattr(sch.subprocess, "run", fake_run)


def test_theme_leader_step_sends_daily_confirm_budget(monkeypatch):
    """挂链=预登记日包络下的常态投喂（带 --confirm-budget）；命令须只用当日日期。"""
    from backend.operations import schedule as sch

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "bridge"))
    seen: list = []
    _patch_leader_subprocess(monkeypatch, seen, stdout=(
        '{"ok": true, "leaders": 13, "labeled": 13, "degraded": 0, "tokensUsed": 29014,'
        ' "estimatedTokensBudgetGuard": 24460, "questionSetVersion": "v2"}'))
    out = sch.run_theme_leader_label_once("2026-10-20")
    cmd = seen[0]
    assert cmd[1:4] == ["-m", "backend.operations.theme_leader_label", "--date"]
    assert "--confirm-budget" in cmd and "2026-10-20" in cmd
    assert out["ok"] is True and out["labeled"] == 13 and out["tokensUsed"] == 29014
    assert out["questionSetVersion"] == "v2"


def test_theme_leader_step_gate_degrades_and_never_raises(monkeypatch):
    from backend.operations import schedule as sch

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (False, "weekday"))
    seen: list = []
    _patch_leader_subprocess(monkeypatch, seen)
    out = sch.run_theme_leader_label_once("2026-10-20")
    assert out["reason"] == "non_trading_day" and seen == [], "非交易日不得起子进程"
    monkeypatch.setattr(sch, "is_trading_day_cached",
                        lambda d: (_ for _ in ()).throw(RuntimeError("bridge down")))
    out2 = sch.run_theme_leader_label_once("2026-10-20")
    assert out2["ok"] is False and out2["error"]["code"] == "theme_leader_gate_failed"


def test_theme_leader_step_switch_off_and_failure_are_visible(monkeypatch):
    from backend.operations import schedule as sch

    monkeypatch.setenv("THEME_LEADER_LABEL_ENABLED", "0")
    seen: list = []
    _patch_leader_subprocess(monkeypatch, seen)
    assert sch.run_theme_leader_label_once("2026-10-20")["reason"] == "disabled"
    assert seen == []
    monkeypatch.delenv("THEME_LEADER_LABEL_ENABLED")

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "cache"))
    _patch_leader_subprocess(monkeypatch, [], rc=1)
    out = sch.run_theme_leader_label_once("2026-10-20")
    assert out["ok"] is False and out["error"]["code"] == "theme_leader_failed"
    assert sch.run_theme_leader_label_once("2026-10-20", dry_run=True)["reason"] == "dry_run"


def test_theme_leader_step_settles_previous_day(monkeypatch):
    """同一步回填近期未封结局（零 token）：pilot 不能只攒标签不攒结局。"""
    from backend.operations import schedule as sch
    from backend.operations import theme_leader_baseline as tlb

    monkeypatch.setattr(sch, "is_trading_day_cached", lambda d: (True, "bridge"))
    monkeypatch.setattr(tlb, "trading_dates",
                        lambda db, start, end: ["2026-10-16", "2026-10-19", "2026-10-20"])
    calls: list = []

    class _Col:
        def count_documents(self, q):
            # 只有 2026-10-19 仍有未封（其余日子无标签/已封）→ 只应回填那一天
            return 13 if q.get("tradingDate") == "2026-10-19" else 0

    class _Db:
        def __getitem__(self, name):
            return _Col()

    monkeypatch.setattr(sch.repository_factory, "get_runtime_mongodb_database", lambda: _Db())

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "theme_leader_label" in " ".join(cmd):
            return type("P", (), {"returncode": 0, "stdout": '{"ok": true, "leaders": 13}',
                                  "stderr": ""})()
        return type("P", (), {"returncode": 0,
                              "stdout": "[2026-10-19 → 次日 2026-10-20] 投喂 13 只；可判定 13 只",
                              "stderr": ""})()
    monkeypatch.setattr(sch.subprocess, "run", fake_run)
    out = sch.run_theme_leader_label_once("2026-10-20")
    assert [r["date"] for r in out["settledRecentDays"]] == ["2026-10-19"]
    assert out["settledRecentDays"][0]["ok"] is True
    assert out["settledRecentDays"][0]["error"] is None, "成功时不得把 stderr banner 当 error 上报"
    assert "--write-outcome" in calls[1]


def test_settle_skips_fully_sealed_and_no_labels_days(monkeypatch):
    """自愈语义：只跑「有标签且仍有未封」的日子；全封/无标签 → 不起进程。"""
    from backend.operations import schedule as sch
    from backend.operations import theme_leader_baseline as tlb

    monkeypatch.setattr(tlb, "trading_dates", lambda db, start, end: ["2026-10-20"])

    class _Col:
        def count_documents(self, q):
            return 0

    class _Db:
        def __getitem__(self, name):
            return _Col()
    monkeypatch.setattr(sch.repository_factory, "get_runtime_mongodb_database", lambda: _Db())
    assert sch._settle_recent_theme_leader_days("2026-10-20") == []


def test_theme_leader_retry_window_allows_same_day_recovery(monkeypatch):
    """失败不一次判死：同日允许退避重试（8001 重启撞上通道抖动时，那一天还能补上）。"""
    from backend.snapshot_collector import scheduler as sc

    assert sc._THEME_LEADER_MAX_ATTEMPTS == 3
    assert sc._THEME_LEADER_RETRY_AFTER == __import__("datetime").timedelta(minutes=10)
    assert sc._THEME_LEADER_LABEL_AT == __import__("datetime").time(16, 20)
    base = __import__("datetime").datetime(2026, 10, 20, 16, 20, 0, tzinfo=sc.TZ_SHANGHAI)
    assert sc._parse_iso(base.isoformat()) == base
    assert sc._parse_iso(None) is None and sc._parse_iso("bad") is None


def test_shed_priority_keeps_industry_when_budget_is_tight(monkeypatch, fake_auth):
    """额度紧缺时保住 `ai_industry`（正文是 high_ge65「新催化」唯一入口）。

    真实事故（2026-10-20 18:40）：当日 12 次额度被 timeline_list/news 与本源重试耗尽后，
    `skippedByBudget=["ai_industry"]` → 730 个产业节点 `contentChangedDate` 停在旧日 →
    全部 94 条样本「近两日新催化」= 0/94，高档判据从未可达（预登记 §11）。
    """
    db = FakeDb()
    _patch_fetchers(monkeypatch,
                    news=F.parse_timeline_news_response(NEWS_PAYLOAD),
                    listing=F.parse_timeline_list_response(LIST_PAYLOAD),
                    industry=F.parse_ai_industry_response(INDUSTRY_PAYLOAD))
    # 只剩 1 次额度：三个源里应当保住 industry，砍掉 list 与 news
    out = C.collect_once(db=db, fetch_date="2026-10-21", date="2026-10-21", budget=1)
    assert out["sources"] == ["ai_industry"], out["sources"]
    # 被砍顺序 = 价值降序（先砍 news，再砍 list）
    assert out["skippedByBudget"] == ["timeline_news", "timeline_list"]
    assert out["industry"]["fetched"] > 0
