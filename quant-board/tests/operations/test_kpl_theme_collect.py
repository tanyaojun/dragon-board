# -*- coding: utf-8 -*-
"""开盘啦题材语料采集（v4 换源，事件层唯一权威源）测试——全部离线，零真实 HTTP / 零 jev 调用。

锁定口径：
1. 三端点解析（事件列表/详情、新闻流 Kword、日历）确定性与空载荷降级；
2. 详情**只补缺失**（库里已有全文的跳过，省调用）；已有正文不得被空详情覆盖（§4.0）；
3. `firstSeenAt/firstSeenDate` 不随重采覆盖（新近度可判定）；
4. 调用计数：失败同样计数；日预算超限 → 详情补拉跳过（fail-visible，不静默空跑）；
5. `--dry-run` 零写入、照常计数。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import kpl_theme_collect as C
from backend.operations import kpl_theme_fetch as F
from backend.operations import kpl_theme_store as S

TOPIC_LIST_PAYLOAD = {"List": [
    {"Day": "2026-10-22", "List": [
        {"ID": "2501", "Title": "九阳、华正、宏和科技等业绩披露，个股要点消息一览",
         "IsVote": "0", "Time": "1792665381", "New": 0, "HotVal": 34558, "HotTag": 3}]},
    {"Day": "2026-10-21", "List": [
        {"ID": "2498", "Title": "泽连斯基：愿在保留至少75%领土控制权的基础上达成和平协议",
         "IsVote": "1", "Time": "1792596888", "New": 0, "HotVal": 38836, "HotTag": 3},
        {"ID": "2499", "Title": "英伟达GTC大会来了！黃仁勋重磅演讲",
         "IsVote": "1", "Time": "1792596979", "New": 0, "HotVal": 46417, "HotTag": 3}]},
]}

TOPIC_DETAIL_PAYLOAD = {
    "Title": "泽连斯基：愿在保留至少75%领土控制权的基础上达成和平协议",
    "Content": "央视新闻10月21日消息，乌克兰总统泽连斯基…“现在我们必须冻结（战线）…”",
    "Num": 58, "HotVal": 38840, "Source": "央视新闻", "Time": "2026-10-21 23:34:48",
    "errcode": "0",
}

NEWS_PAYLOAD = {"List": [
    {"CID": 7938, "Title": "Meta未来支出承诺总额达8250亿美元涉及AI算力、数据中心及能源基础设施",
     "ZSName": "", "TimeStamp": 1792681975, "Source": "开盘啦", "Kword": "AI算力基建",
     "Statu": "0",
     "Stocks": [{"Code": "603019", "Name": "中科曙光", "Rate": 0.29, "SetTop": 1},
                {"Code": "000988", "Name": "华工科技", "Rate": -5.23, "SetTop": 0}]},
    {"CID": 7939, "Title": "泽连斯基表态推动和平协议预期，基建出口链异动",
     "ZSName": "俄乌重建", "TimeStamp": 1792600000, "Source": "开盘啦", "Kword": "俄乌重建", "Statu": "0",
     "Stocks": [{"Code": "001360", "Name": "南矿集团", "Rate": 10.0, "SetTop": 1}]},
]}

CAL_PAYLOAD = {"List": [
    {"PID": 4803, "Brief": "2026年欧洲肿瘤内科学会(ESMO)大会将于10月23日至27日举行",
     "Date": "2026-10-23", "TagName": "会议", "ColorType": "2", "Stocks": []},
]}


# ── 解析层（真实样本形状） ─────────────────────────────────────────────
def test_parse_topic_list_flattens_day_groups():
    evs = F.parse_topic_list(TOPIC_LIST_PAYLOAD)
    assert len(evs) == 3
    zt = next(e for e in evs if e["eventId"] == "2498")
    assert zt["day"] == "2026-10-21" and zt["hotVal"] == 38836 and zt["isVote"] == "1"


def test_parse_topic_detail_keeps_source_and_content():
    d = F.parse_topic_detail(TOPIC_DETAIL_PAYLOAD)
    assert d["source"] == "央视新闻" and d["time"] == "2026-10-21 23:34:48"
    assert "冻结（战线）" in d["content"] and d["num"] == 58


def test_parse_news_keeps_kword_and_stocks_normalized():
    items = F.parse_news_list(NEWS_PAYLOAD)
    assert items[0]["kword"] == "AI算力基建" and items[0]["eventDate"]
    assert items[0]["stocks"][0] == {"code": "603019", "name": "中科曙光",
                                     "rate": 0.29, "setTop": 1}
    assert items[1]["kword"] == "俄乌重建"
    # 2026-11-02 用户裁决①：ZSName 官方板块归属透传（空/非空两态）
    assert items[0]["zsName"] == "" and items[1]["zsName"] == "俄乌重建"


def test_parse_calendar_keeps_date_and_tag():
    items = F.parse_calendar_list(CAL_PAYLOAD)
    assert items[0]["date"] == "2026-10-23" and items[0]["tagName"] == "会议"
    assert "ESMO" in items[0]["brief"]


def test_errcode_structured_never_silent_success():
    out = F.fetch_topic_list.__wrapped__ if hasattr(F.fetch_topic_list, "__wrapped__") else None
    assert out is None  # fetch 层含网络，errcode 分支由 _check_errcode 单测
    assert F._check_errcode({"errcode": 1020, "errmsg": "参数出错"}) == {
        "ok": False, "errorCode": "1020", "error": "参数出错"}
    assert F._check_errcode({"errcode": "0"}) is None
    assert F._check_errcode({}) is None


# ── 存储层（假 collection，同韭研测试的简化语义） ────────────────────────
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


def test_save_topic_events_keeps_first_seen_and_merges_details():
    db = FakeDb()
    evs = F.parse_topic_list(TOPIC_LIST_PAYLOAD)
    s1 = S.save_topic_events(db, fetch_date="2026-10-21", events=evs,
                             details={"2498": F.parse_topic_detail(TOPIC_DETAIL_PAYLOAD)})
    assert s1["written"] == 3 and s1["detailFetched"] == 1
    zt = db[S.COLLECTION_TOPIC].docs["2026-10-21:2498"]
    assert zt["content"].startswith("央视新闻") and zt["source"] == "央视新闻"
    assert zt["detailFetched"] is True
    no_detail = db[S.COLLECTION_TOPIC].docs["2026-10-21:2499"]
    assert no_detail["content"] == "" and no_detail["detailFetched"] is False

    # 次日重采：firstSeen 不覆盖；已有全文不被空详情覆盖
    first_seen = zt["firstSeenAt"]
    S.save_topic_events(db, fetch_date="2026-10-22", events=evs)
    zt2 = db[S.COLLECTION_TOPIC].docs["2026-10-21:2498"]
    assert zt2["firstSeenAt"] == first_seen and zt2["firstSeenDate"] == "2026-10-21"
    assert zt2["lastFetchDate"] == "2026-10-22" and zt2["content"].startswith("央视新闻")
    # review 2026-10-23 Blocker：重采（无详情）不得抹掉首轮详情抓到的 num/eventTime/title
    assert zt2["num"] == zt["num"] and zt2["eventTime"] == zt["eventTime"]
    assert zt2["title"] == zt["title"] and zt2["source"] == zt["source"]


def test_window_getters_use_event_date():
    db = FakeDb()
    evs = F.parse_topic_list(TOPIC_LIST_PAYLOAD)
    S.save_topic_events(db, fetch_date="2026-10-22", events=evs,
                        details={e["eventId"]: F.parse_topic_detail(TOPIC_DETAIL_PAYLOAD)
                                 for e in evs})
    S.save_news_items(db, fetch_date="2026-10-22", items=F.parse_news_list(NEWS_PAYLOAD))
    S.save_calendar_items(db, fetch_date="2026-10-22", items=F.parse_calendar_list(CAL_PAYLOAD))
    got = S.get_topic_events(db, date="2026-10-22", include_past_recent=3, window_days=1)
    assert all("2026-10-19" <= e["day"] <= "2026-10-23" for e in got)
    news = S.get_news_items(db, date="2026-10-22")
    assert {n["kword"] for n in news} == {"AI算力基建", "俄乌重建"}
    assert any(n.get("zsName") == "俄乌重建" for n in news), "读口投影必须带 zsName"
    cal = S.get_calendar_items(db, date="2026-10-22", window_days=3)
    assert ["ESMO" in c["brief"] for c in cal] == [True]


def test_empty_detail_never_overwrites_content():
    db = FakeDb()
    evs = [{"eventId": "1", "day": "2026-10-22", "title": "T", "hotVal": 1, "isVote": "0",
            "time": None}]
    S.save_topic_events(db, fetch_date="2026-10-22", events=evs,
                        details={"1": {"content": "正文A", "source": "S", "time": "t"}})
    S.save_topic_events(db, fetch_date="2026-10-23", events=evs)   # 无详情重采
    assert db[S.COLLECTION_TOPIC].docs["2026-10-22:1"]["content"] == "正文A"


def test_corpus_stats_counts_and_latest():
    db = FakeDb()
    S.save_topic_events(db, fetch_date="2026-10-22", events=F.parse_topic_list(TOPIC_LIST_PAYLOAD))
    st = S.corpus_stats(db)
    assert st["topic"]["count"] == 3 and st["topic"]["latestFetchDate"] == "2026-10-22"
    assert st["news"]["count"] == 0 and st["calendar"]["count"] == 0
    assert st["latestFetchDate"] == "2026-10-22"


# ── 编排层 ───────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(C, "INTER_CALL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(C, "RETRY_SLEEP_SECONDS", 0.0)


def test_collect_once_persists_all_three(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list", lambda **kw: {
        "ok": True, "events": F.parse_topic_list(TOPIC_LIST_PAYLOAD), "empty": False})
    monkeypatch.setattr(F, "fetch_topic_detail", lambda event_id: {
        "ok": True, "detail": F.parse_topic_detail(TOPIC_DETAIL_PAYLOAD)})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: (
        {"ok": True, "items": F.parse_news_list(NEWS_PAYLOAD), "empty": False}
        if news_type == -1 else
        {"ok": True, "items": F.parse_calendar_list(CAL_PAYLOAD), "empty": False}))
    out = C.collect_once(db=db, fetch_date="2026-10-22")
    assert out["ok"] is True and out["degraded"] == []
    assert out["topic"]["written"] == 3 and out["topic"]["newDetails"] == 3
    assert out["news"]["written"] == 2 and out["calendar"]["written"] == 1
    assert out["callsUsedTodayAfter"] == 6, "3 主源 + 3 新事件详情"
    # 事件详情落库
    assert db[S.COLLECTION_TOPIC].docs["2026-10-21:2498"]["source"] == "央视新闻"


def test_collect_once_skips_details_for_known_events(monkeypatch):
    """库里已有全文的事件不重拉详情（省调用）。"""
    db = FakeDb()
    evs = F.parse_topic_list(TOPIC_LIST_PAYLOAD)
    S.save_topic_events(db, fetch_date="2026-10-20", events=evs,
                        details={e["eventId"]: {"content": "已有", "source": "S", "time": "t"}
                                 for e in evs})
    calls: list[str] = []
    monkeypatch.setattr(F, "fetch_topic_list", lambda **kw: {
        "ok": True, "events": evs, "empty": False})
    monkeypatch.setattr(F, "fetch_topic_detail",
                        lambda event_id: calls.append(event_id) or {"ok": True, "detail": {}})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: {"ok": True, "items": []})
    out = C.collect_once(db=db, fetch_date="2026-10-22")
    assert calls == [], "全部事件已有全文 → 零详情调用"
    assert out["topic"]["newDetails"] == 0


def test_collect_once_degraded_sources_not_silent(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list",
                        lambda **kw: {"ok": False, "errorCode": "1020", "error": "参数出错"})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: {
        "ok": True, "items": F.parse_news_list(NEWS_PAYLOAD), "empty": False})
    out = C.collect_once(db=db, fetch_date="2026-10-22")
    assert out["ok"] is True, "三主源只挂一个 → 仍算成功（§4.0）"
    assert out["degraded"] == ["topic_list: [1020] 参数出错"]
    assert out["topic"]["written"] == 0 and out["news"]["written"] == 2


def test_collect_once_all_down_is_failure(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list",
                        lambda **kw: {"ok": False, "errorCode": "http_error", "error": "URLError"})
    monkeypatch.setattr(F, "fetch_news_list",
                        lambda news_type, **kw: {"ok": False, "errorCode": "http_error", "error": "x"})
    out = C.collect_once(db=db, fetch_date="2026-10-22")
    assert out["ok"] is False and len(out["degraded"]) >= 3


def test_collect_once_empty_payload_is_degraded_not_success(monkeypatch):
    """errcode=0 但 0 条 → 空载荷降级（§4.0；韭研 2026-10-20 实测缺陷同款）。"""
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list", lambda **kw: {"ok": True, "events": [], "empty": True})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: {"ok": True, "items": []})
    out = C.collect_once(db=db, fetch_date="2026-10-22")
    assert out["emptySources"] == ["topic_list", "theme_news", "theme_calendar"]
    assert out["ok"] is False


def test_collect_once_dry_run_writes_nothing_but_counts(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list", lambda **kw: {
        "ok": True, "events": F.parse_topic_list(TOPIC_LIST_PAYLOAD), "empty": False})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: {"ok": True, "items": []})
    out = C.collect_once(db=db, fetch_date="2026-10-22", dry_run=True)
    assert out["dryRun"] is True
    assert (not db.cols.get(S.COLLECTION_TOPIC) or not db.cols.get(S.COLLECTION_TOPIC).docs)
    assert (not db.cols.get(S.COLLECTION_NEWS) or not db.cols.get(S.COLLECTION_NEWS).docs)
    assert out["callsUsedTodayAfter"] == 6, "dry-run 也真发 HTTP（含 3 条新事件详情），额度照扣"


def test_budget_tight_skips_details_but_keeps_main_sources(monkeypatch):
    """额度紧张：三主源优先，新事件详情补拉跳过（fail-visible，不静默）。"""
    db = FakeDb()
    monkeypatch.setattr(F, "fetch_topic_list", lambda **kw: {
        "ok": True, "events": F.parse_topic_list(TOPIC_LIST_PAYLOAD), "empty": False})
    monkeypatch.setattr(F, "fetch_news_list", lambda news_type, **kw: {"ok": True, "items": []})
    out = C.collect_once(db=db, fetch_date="2026-10-22", budget=5)
    assert out["skippedByBudget"] == ["topic_detail"]
    assert out["topic"]["newDetails"] == 0 and out["topic"]["written"] == 3
