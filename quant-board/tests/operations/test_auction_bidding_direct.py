# -*- coding: utf-8 -*-
"""竞价列表真源头直采器（MorningBiddingList @ kaipanla.com）测试——纯假库/假 POST。

合同锁定（2026-11-16 雷电模拟器 mitmproxy 实抓 + st=100 重放验证）：
1. POST form a=MorningBiddingList&c=HomeDingPan&Type=4&PidType=0&Order=1&st=N&Index=M；
2. 17 列统一数组位 → 具名字段映射，未破译列保 colN 原名不猜，raw 全行保留；
3. 翻页 Index 按页长偏移，rows < st 即末页，≤MAX_PAGES；
4. 持久化 _id=日期、rows 键=code6、source=kpl_direct_morning_bidding。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_bidding_direct as M


class FakeMblDb:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def __getitem__(self, name):
        return self

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find_one(self, q):
        return self.docs.get(q["_id"])


def _row(code: str, extra: float = 1.0) -> list:
    return [code, "测试股", 10.0 + extra, 5.0, 1000000.0 * extra, 10, 500000.0, 0.5,
            2000000.0, 800000.0, 2000000.0, "测试板块", 1e9, -50000.0, 900000.0,
            -40000.0, "首板"]


def test_parse_mbl_rows_named_and_raw():
    rows = M.parse_mbl_rows([_row("000831")])
    r = rows["000831"]
    assert r["name"] == "测试股" and r["zt_buy_amount"] == 1000000.0
    assert r["plate"] == "测试板块" and r["state"] == "首板"
    assert r["col9"] == 800000.0, "未破译列保原名不猜"
    assert r["raw"][0] == "000831", "raw 全行保留"
    assert len(r["raw"]) == 17
    # 缺列如实缺（短行）
    rows2 = M.parse_mbl_rows([["600715", "短行"]])
    assert rows2["600715"]["name"] == "短行" and rows2["600715"]["plate"] is None


def test_parse_mbl_rows_skips_bad():
    rows = M.parse_mbl_rows([None, [], ["", "空码"], _row("000831")])
    assert set(rows.keys()) == {"000831"}


def test_fetch_pagination_until_short_page(monkeypatch):
    calls = []

    def fake_post(url, params):
        calls.append(params["Index"])
        idx = params["Index"]
        n = 100 if idx == 0 else 14   # 第二页 14 行 < st=100 → 末页
        return {"errcode": "0", "info": [_row(f"60{i:04d}") for i in range(idx, idx + n)],
                "day": "2026-11-17", "time": 1, "status": 1}

    monkeypatch.setattr(M, "_post", fake_post)
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "ok" and res["n_rows"] == 114 and res["pages"] == 2
    assert calls == [0, 100], "Index 按页长偏移"
    assert res["day"] == "2026-11-17"


def test_fetch_http_error_structured(monkeypatch):
    def fake_post(url, params):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_post", fake_post)
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "http_error:RuntimeError" and res["rows"] == {}


def test_persist_and_load_roundtrip():
    db = FakeMblDb()
    res = {"state": "ok", "rows": M.parse_mbl_rows([_row("000831")]),
           "n_rows": 1, "pages": 1, "day": "2026-11-17", "time": 1, "status": 1,
           "attempts": [{"index": 0, "state": "ok"}]}
    p = M.persist_morning_bidding_raw(db, "2026-11-17", res)
    assert p["ok"] is True and p["n_rows"] == 1
    rows = M.load_morning_bidding_raw(db, "2026-11-17")
    assert rows["000831"]["bidding_pct"] == 10
    assert M.load_morning_bidding_raw(db, "2099-01-01") is None


def test_bidding_series_line_rendering():
    from backend.analysis.hotlist.auction_leader_ammo import bidding_series_line
    facts = {"first": {"ts": 1765275305, "bidding_pct": 2.1},
             "max": {"ts": 1765275760, "zt_buy_amount": 3.0e8},
             "last": {"ts": 1765275910, "bidding_pct": 4.2}}
    line = bidding_series_line(facts)
    assert line and line.startswith("竞价过程事实：")
    assert "首帧竞价涨幅 2.10%" in line and "委买额峰值 3.00亿" in line
    assert "观测值口径" not in line and "socket" not in line, "§1.2-8 开发注释禁进行文"
    assert bidding_series_line(None) is None
    assert bidding_series_line({"first": {"ts": 1, "bidding_pct": None}}) is None


def _fake_series_db():
    class FakeSeriesDb:
        def __init__(self):
            self.docs = {}
        def __getitem__(self, name):
            return self
        def find_one(self, q):
            import copy
            doc = self.docs.get(q["_id"])
            return copy.deepcopy(doc) if doc else None  # pymongo 快照语义（非活引用）
        def update_one(self, q, upd, upsert=False):
            doc = self.docs.setdefault(q["_id"], {"_id": q["_id"], "frames": []})
            for fr in upd["$push"]["frames"]["$each"]:
                doc["frames"].append(fr)
            doc["frames"] = doc["frames"][-15:]
            doc["updatedAt"] = upd["$set"]["updatedAt"]
    return FakeSeriesDb()


def test_mbl_frame_window_gate(monkeypatch):
    import datetime as dt
    from backend.operations import auction_bidding_direct as M
    db = _fake_series_db()
    # 窗外（10:00）静默跳过，零外呼
    called = []
    monkeypatch.setattr(M, "fetch_morning_bidding_list", lambda **k: called.append(1))
    out = M.collect_mbl_frame_series(db, "2026-11-17", dt.datetime(2026, 11, 17, 10, 0, 0))
    assert out["state"] == "skipped_out_of_window" and not called
    # 预算耗尽
    db.docs["2026-11-17"] = {"_id": "2026-11-17", "frames": [{"n": i} for i in range(15)]}
    out = M.collect_mbl_frame_series(db, "2026-11-17", dt.datetime(2026, 11, 17, 9, 20, 0))
    assert out["state"] == "skipped_budget_exhausted"


def test_mbl_frame_append(monkeypatch):
    import datetime as dt
    from backend.operations import auction_bidding_direct as M
    db = _fake_series_db()
    monkeypatch.setattr(M, "fetch_morning_bidding_list", lambda **k: {
        "state": "ok", "n_rows": 2, "day": "2026-11-17",
        "rows": {"000831": {"code": "000831", "raw": [1, 2, 3]},
                 "002242": {"code": "002242", "raw": [4, 5, 6]}}})
    out = M.collect_mbl_frame_series(db, "2026-11-17", dt.datetime(2026, 11, 17, 9, 21, 0))
    assert out["state"] == "ok" and out["frameN"] == 1 and out["n_rows"] == 2
    doc = db.docs["2026-11-17"]
    assert len(doc["frames"]) == 1 and doc["frames"][0]["rows"][0] == [1, 2, 3]
    # 第二帧追加 + $slice 保持
    out = M.collect_mbl_frame_series(db, "2026-11-17", dt.datetime(2026, 11, 17, 9, 22, 0))
    assert out["frameN"] == 2 and len(db.docs["2026-11-17"]["frames"]) == 2


def test_fetch_errcode_nonzero_structured(monkeypatch):
    """红线 1：上游业务错误（errcode≠0）不得记为 ok/0 行空档。"""
    monkeypatch.setattr(M, "_post", lambda u, p: {"errcode": "1002", "msg": "token 失效"})
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "kpl_errcode:1002" and res["rows"] == {}
    assert res["attempts"][0]["state"] == "kpl_errcode:1002"
    assert "token 失效" in res["message"]


def test_fetch_info_not_list_structured(monkeypatch):
    monkeypatch.setattr(M, "_post", lambda u, p: {"errcode": "0", "info": {"bad": 1}})
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "parse_error:info_not_list" and res["rows"] == {}
    assert res["attempts"][0]["got"] == "dict"


def test_fetch_truncated_flag_on_page_exhaustion(monkeypatch):
    """MAX_PAGES 耗尽且末页满页 → truncated=True（审计可见，不冒充全量）。"""
    monkeypatch.setattr(M, "_post", lambda u, p: {
        "errcode": "0", "info": [_row(f"60{i:04d}") for i in range(100)]})
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "ok" and res["pages"] == M.MAX_PAGES and res["truncated"] is True
    # 正常末页 → truncated=False
    monkeypatch.setattr(M, "_post", lambda u, p: {
        "errcode": "0", "info": [_row("600001")]})
    assert M.fetch_morning_bidding_list()["truncated"] is False


def test_collect_partial_rows_persisted_with_marker(monkeypatch):
    """红线 1：翻页中途失败但已取回 rows → 落库 + partial=true（不丢部分成功数据）。"""
    db = FakeMblDb()
    calls = []

    def fake_post(url, params):
        calls.append(params["Index"])
        if params["Index"] == 0:
            # 满页 100 行 → 翻页继续；第二页抛错，首页 100 行 partial 保留
            return {"errcode": "0", "info": [_row(f"60{i:04d}") for i in range(100)]}
        raise RuntimeError("page2 boom")

    monkeypatch.setattr(M, "_post", fake_post)
    out = M.collect_auction_bidding_direct(db, "2026-11-17")
    assert out["state"] == "http_error:RuntimeError"
    assert out["persistState"]["partial"] is True
    doc = db.docs["2026-11-17"]
    assert doc["partial"] is True and doc["state"] == "http_error:RuntimeError"
    assert doc["n_rows"] == 100 and doc["pages"] == 1
    assert doc["rows"]["600000"]["code"] == "600000", "首页部分数据保留在 partial 档"


def test_collect_error_zero_rows_no_overwrite(monkeypatch):
    """红线 1：非 ok 且 0 行 → 不写库、不覆盖同日既有好档。"""
    db = FakeMblDb()
    db.docs["2026-11-17"] = {"_id": "2026-11-17", "n_rows": 114, "rows": {"000831": {}}}
    monkeypatch.setattr(M, "_post", lambda u, p: {"errcode": "1002", "msg": "x"})
    out = M.collect_auction_bidding_direct(db, "2026-11-17")
    assert "persistState" not in out
    assert db.docs["2026-11-17"]["n_rows"] == 114, "好档未被 0 行覆盖"


def test_collect_ok_empty_market_still_persisted(monkeypatch):
    """ok 且 0 行（当日无竞价股）也是事实，照写空档。"""
    db = FakeMblDb()
    monkeypatch.setattr(M, "_post", lambda u, p: {"errcode": "0", "info": []})
    out = M.collect_auction_bidding_direct(db, "2026-11-17")
    assert out["state"] == "ok" and out["persistState"]["n_rows"] == 0
    assert db.docs["2026-11-17"]["partial"] is False


def test_persist_fields_attempts_native_and_fetched_at_ts():
    """评审 P2：attempts 原生数组可聚合；fetchedAt 是真时间戳（CST 带时区）。"""
    db = FakeMblDb()
    res = {"state": "ok", "rows": {}, "n_rows": 0, "pages": 1,
           "attempts": [{"index": 0, "state": "ok", "n_rows": 0}]}
    M.persist_morning_bidding_raw(db, "2026-11-17", res)
    doc = db.docs["2026-11-17"]
    assert isinstance(doc["attempts"], list) and doc["attempts"][0]["index"] == 0
    assert doc["fetchedAt"].endswith("+08:00") and doc["updatedAt"].endswith("+08:00")


def test_fetch_matched_type7_params_and_list_key(monkeypatch):
    """裁决②：Type=7 直采 a=DaBanList&c=HomeDingPan&Type=7&PidType=8，行键 list。"""
    seen = {}

    def fake_post(url, params):
        seen.update(params)
        return {"errcode": "0", "list": [_row("603324")], "day": "2026-11-19"}

    monkeypatch.setattr(M, "_post", fake_post)
    res = M.fetch_auction_matched_list()
    assert res["state"] == "ok" and res["n_rows"] == 1
    assert seen["a"] == "DaBanList" and seen["c"] == "HomeDingPan"
    assert seen["Type"] == 7 and seen["PidType"] == 8


def test_matched_terminal_contract_and_roundtrip():
    """跨会话合同 rows[code]={pct,price,amount,turnover,end_time}；end_time 无列=None。"""
    db = FakeMblDb()
    res = {"state": "ok", "rows": M.parse_mbl_rows([_row("603324")]),
           "n_rows": 1, "pages": 1, "day": "2026-11-19",
           "attempts": [{"index": 0, "state": "ok"}]}
    p = M.persist_auction_matched(db, "2026-11-19", res)
    assert p["ok"] and p["n_rows"] == 1
    rows = M.load_auction_matched(db, "2026-11-19")
    r = rows["603324"]
    assert r["pct"] == 10 and r["price"] == 11.0
    assert r["amount"] == 2000000.0 and r["turnover"] == 0.5
    assert r["end_time"] is None   # 17 列无时点列，fail-visible
    assert M.load_auction_matched(db, "2099-01-01") is None


class FakeMatchedDb(FakeMblDb):
    """带 count_documents 的假库（run_auction_matched_once 缺档判定用）。"""

    def count_documents(self, q):
        return 1 if q.get("_id") in self.docs else 0


def test_collect_matched_day_mismatch_no_write(monkeypatch):
    """review B1：Type=7 实时端点无日期参数（仅返回最近交易日），请求日≠返回日
    一律不落库，防当日数据错标成历史日污染终值权威档（fail-visible）。"""
    monkeypatch.setattr(M, "_post", lambda url, params: {
        "errcode": "0", "list": [_row("603324")], "day": "2026-11-19"})
    db = FakeMatchedDb()
    out = M.collect_auction_matched_direct(db, "2026-11-18")
    assert out["state"] == "day_mismatch" and out["fetchedDay"] == "2026-11-19"
    assert out["requested"] == "2026-11-18" and "persistState" not in out
    assert db.docs == {}, "错档不写库"


def test_collect_matched_day_missing_no_write(monkeypatch):
    """响应缺 day 元数据无法核对归属日 → 不落库（fail-visible）。"""
    monkeypatch.setattr(M, "_post", lambda url, params: {
        "errcode": "0", "list": [_row("603324")]})
    db = FakeMatchedDb()
    out = M.collect_auction_matched_direct(db, "2026-11-19")
    assert out["state"] == "day_missing" and db.docs == {}


def _patch_run(monkeypatch, db, dates):
    """run_auction_matched_once 测试脚手架：假库 + 假交易日历 + 假 _post（记录外呼）。"""
    from backend.operations import schedule as S
    from backend.operations import theme_leader_baseline as TB
    calls: list[dict] = []

    def fake_post(url, params):
        calls.append(params)
        return {"errcode": "0", "list": [_row("603324")], "day": "2026-11-19"}

    monkeypatch.setattr(M, "_post", fake_post)
    monkeypatch.setattr(S.repository_factory, "get_runtime_mongodb_database",
                        lambda: db)
    monkeypatch.setattr(TB, "trading_dates", lambda db_, start, end: list(dates))
    return calls


def test_run_matched_once_single_call_and_persist(monkeypatch):
    """review B1/M5：多个缺档日也只发 1 次请求（目标=最近缺档日），当日命中即落库。"""
    db = FakeMatchedDb()
    db.docs["2026-11-18"] = {"_id": "2026-11-18", "rows": {}}   # 昨日已有档
    calls = _patch_run(monkeypatch, db, ["2026-11-17", "2026-11-18", "2026-11-19"])
    from backend.operations import schedule as S
    out = S.run_auction_matched_once(today="2026-11-19")
    assert len(calls) == 1, "1 发/日：缺档多个也只外呼 1 次"
    assert out["ok"] is True and out["matchedDays"][0]["state"] == "ok"
    assert "2026-11-19" in db.docs and db.docs["2026-11-19"]["day"] == "2026-11-19"
    assert "2026-11-17" not in db.docs, "更早缺档日不写错档（端点补不了，走 TDX 应急）"


def test_run_matched_once_stale_missing_no_pollution(monkeypatch):
    """最新交易日已有档、更早日缺档 → 1 次外呼 day_mismatch 零写入（B1 污染防护）。"""
    db = FakeMatchedDb()
    db.docs["2026-11-19"] = {"_id": "2026-11-19", "rows": {}}
    calls = _patch_run(monkeypatch, db, ["2026-11-18", "2026-11-19"])
    from backend.operations import schedule as S
    out = S.run_auction_matched_once(today="2026-11-19")
    assert len(calls) == 1
    assert out["ok"] is True and out["matchedDays"][0]["state"] == "day_mismatch"
    assert set(db.docs) == {"2026-11-19"}, "不把 11-19 数据错标成 11-18"


def test_run_matched_once_no_missing_zero_call(monkeypatch):
    """近 5 交易日档齐全 → 零外呼（no_missing 短路）。"""
    db = FakeMatchedDb()
    for d in ("2026-11-17", "2026-11-18", "2026-11-19"):
        db.docs[d] = {"_id": d, "rows": {}}
    calls = _patch_run(monkeypatch, db, ["2026-11-17", "2026-11-18", "2026-11-19"])
    from backend.operations import schedule as S
    out = S.run_auction_matched_once(today="2026-11-19")
    assert calls == [] and out["ok"] is True and out["state"] == "no_missing"
