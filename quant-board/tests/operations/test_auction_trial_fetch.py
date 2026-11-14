# -*- coding: utf-8 -*-
"""竞价试盘采集器测试（auction_trial_fetch，2026-11-14c 接线）。

fixture = 11-13 真实缓存 trimmed（data/backups/probe/wzs_auction_2026-11-13.json）；
HTTP 全 mock 零外呼（AGENTS §1.2-7）；守卫与预算纪律为断言核心。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_leader_ammo as AL
from backend.operations import auction_trial_fetch as T

FIXTURE = Path(__file__).parent / "fixtures" / "wzs_auction_2026-11-13_sample.json"
DATE = "2026-11-13"


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_fixture_tp_row_units():
    res = T.parse_trial_payload(_load(), DATE)
    assert res["state"] == "ok" and res["n_rows"] == 3
    row = res["rows"]["605255"]
    # rank 单位定案（勘察 §6.1）：金额=元、比例=小数 ×100、时间=原串
    assert row["max_amount"] == 9_610_000.0 and row["last_amount"] == 8_980_000.0
    assert row["jj_percent"] == 4.78 and row["pre_percent"] == 10.0
    assert row["jj_turnover"] == 0.15
    assert row["start_time"] == "09:15:01" and row["end_time"] == "09:18:13"
    assert row["bk_name"] == "半导体(3)"


def test_parse_guard_fallback_date_rows_cleared():
    """actual_date ≠ 请求日 → rows 清空（回退数据不得冒充当日）。"""
    res = T.parse_trial_payload(_load(), "2026-11-12")
    assert res["state"] == "fallback" and res["rows"] == {} and res["n_rows"] == 0


def test_parse_api_error_structured():
    res = T.parse_trial_payload({"success": False, "message": "不支持的数据变体"}, DATE)
    assert res["state"] == "api_error" and res["rows"] == {}
    assert "变体" in res["message"]


def test_fetch_fresh_cache_single_attempt(monkeypatch):
    """缓存新鲜（龄 ≤120s）→ 仅 1 发裸读、无 refresh（预算最省路径）。"""
    saved = "2026-11-13T23:41:01+08:00"
    ts = datetime.strptime(saved[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    urls: list[str] = []

    def fake_get(url: str) -> dict:
        urls.append(url)
        return _load()

    monkeypatch.setattr(T, "_http_get_json", fake_get)
    res = T.fetch_auction_trial(DATE, now=ts + 10)
    assert res["state"] == "ok" and res["rows"]["605255"]["jj_percent"] == 4.78
    assert len(res["attempts"]) == 1 and res["attempts"][0]["refresh"] is False
    assert "refresh=1" not in urls[0]


def test_fetch_stale_cache_refresh_once(monkeypatch):
    """缓存陈旧 → 至多补 1 发 refresh=1（≤2 发封顶，无重试循环）。"""
    saved = "2026-11-13T23:41:01+08:00"
    ts = datetime.strptime(saved[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    urls: list[str] = []

    def fake_get(url: str) -> dict:
        urls.append(url)
        return _load()

    monkeypatch.setattr(T, "_http_get_json", fake_get)
    res = T.fetch_auction_trial(DATE, now=ts + 300)
    assert len(res["attempts"]) == 2
    assert res["attempts"][1]["refresh"] is True
    assert urls[0].endswith(f"date={DATE}") and urls[1].endswith(f"date={DATE}&refresh=1")


def test_fetch_fallback_no_refresh(monkeypatch):
    """回退/错误态 → 立即收手（不在无数据方向上追加请求，红线 9）。"""
    payload = _load()
    payload["actual_date"] = "2026-11-12"

    def fake_get(url: str) -> dict:
        return payload

    monkeypatch.setattr(T, "_http_get_json", fake_get)
    res = T.fetch_auction_trial(DATE)
    assert res["state"] == "fallback" and len(res["attempts"]) == 1


def test_fetch_http_error_structured_no_retry(monkeypatch):
    def fake_get(url: str) -> dict:
        raise OSError("conn refused")

    monkeypatch.setattr(T, "_http_get_json", fake_get)
    res = T.fetch_auction_trial(DATE)
    assert res["state"] == "http_error:OSError" and res["rows"] == {}


class _FakeCol:
    def __init__(self):
        self.docs = {}

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def find_one(self, query=None, **kw):
        return self.docs.get(query["_id"])


class _FakeDb:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCol())


def test_persist_trial_raw_ok_writes_full_rows():
    """ok 态全量落库：rows 全量 + 信封元数据 + _id=date（幂等覆盖）。"""
    db = _FakeDb()
    res = T.parse_trial_payload(_load(), DATE)
    p = T.persist_trial_raw(db, DATE, res)
    assert p["persisted"] is True and p["nRows"] == 3
    doc = db[T.COLLECTION_TRIAL_RAW].docs[DATE]
    assert doc["tradingDate"] == DATE and doc["source"] == "wzslinker_auction"
    assert doc["rows"]["605255"]["jj_percent"] == 4.78 and doc["nRows"] == 3
    assert doc["savedAt"] and doc["persistedAt"]
    # 幂等：重跑覆盖不叠加
    p2 = T.persist_trial_raw(db, DATE, res)
    assert p2["persisted"] and len(db[T.COLLECTION_TRIAL_RAW].docs) == 1


def test_persist_trial_raw_empty_rows_is_fact():
    """空 rows + ok = 「当日全市场无试盘个股」事实，照写 nRows=0（§4.0）。"""
    db = _FakeDb()
    p = T.persist_trial_raw(db, DATE, {"state": "ok", "rows": {}, "n_rows": 0,
                                       "actual_date": DATE, "saved_at": None})
    assert p["persisted"] is True and p["nRows"] == 0


def test_persist_trial_raw_non_ok_skipped():
    """fallback/api_error/http_error 无当日有效载荷不落（跨日冒充禁令；不覆盖好档）。"""
    db = _FakeDb()
    db[T.COLLECTION_TRIAL_RAW].docs[DATE] = {"tradingDate": DATE, "nRows": 3}
    for res in ({"state": "fallback", "rows": {}, "n_rows": 0},
                {"state": "api_error", "rows": {}, "n_rows": 0, "message": "x"},
                {"state": "http_error:URLError", "n_rows": 0}):
        p = T.persist_trial_raw(db, DATE, res)
        assert p["persisted"] is False and p["reason"].startswith("skip:")
    assert db[T.COLLECTION_TRIAL_RAW].docs[DATE]["nRows"] == 3


def test_persist_trial_raw_db_error_structured():
    """库错误结构化返回不抛（不阻断投喂）。"""
    class _Boom:
        def replace_one(self, *a, **kw):
            raise RuntimeError("conn refused")

    db = _FakeDb()
    db._cols[T.COLLECTION_TRIAL_RAW] = _Boom()
    p = T.persist_trial_raw(db, DATE, {"state": "ok", "rows": {"a": {}}, "n_rows": 1})
    assert p["persisted"] is False and p["reason"].startswith("persist_error:")


def test_backfill_process_date_offline(monkeypatch):
    """回填脚本单日处理：ok 落库 / 已有跳过 / 守卫跳过（零外呼离线）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from scripts import backfill_auction_trial_raw as B

    db = _FakeDb()
    data = _load()
    monkeypatch.setattr(B, "_http_get_json", lambda url: data)
    r = B.process_date(db, DATE)
    assert r["persisted"] and r["nRows"] == 3
    # 已有档缺省跳过（零外呼断点续跑）
    monkeypatch.setattr(B, "_http_get_json",
                        lambda url: (_ for _ in ()).throw(AssertionError("no call")))
    r2 = B.process_date(db, DATE)
    assert r2["state"] == "already_persisted"
    # 守卫：回退日不落（请求 URL 带目标日，信封 actual_date ≠ 请求日 → fallback）
    seen_urls = []

    def _spy(url):
        seen_urls.append(url)
        return data

    monkeypatch.setattr(B, "_http_get_json", _spy)
    r3 = B.process_date(db, "2026-11-12", force=True)
    assert "date=2026-11-12" in seen_urls[0]
    assert r3["state"] == "fallback" and r3["persisted"] is False
    assert db[T.COLLECTION_TRIAL_RAW].find_one({"_id": "2026-11-12"}) is None


def test_normalize_trial_time_dual_format():
    """双格式归一化：HHMMSS → hh:mm:ss；带冒号原样；空 → None；不可判原样（不猜）。"""
    assert T.normalize_trial_time("91948") == "09:19:48"
    assert T.normalize_trial_time("92500") == "09:25:00"
    assert T.normalize_trial_time(91948) == "09:19:48"
    assert T.normalize_trial_time("09:18:13") == "09:18:13"
    assert T.normalize_trial_time("") is None and T.normalize_trial_time(None) is None
    assert T.normalize_trial_time("abc") == "abc"          # fail-visible 不猜不丢


def test_parse_normalizes_hhmmss_times():
    """parse 层归一化：上游无冒号时间入语义行即转 hh:mm:ss（渲染层零假时间源）。"""
    data = _load()
    sl = data["data"]["data"]["stock_list"]
    # 首行 cell 的 end_time 位注入无冒号格式（索引位 7 = _ROW_KEYS.index("end_time")）
    raw0 = sl["list"][0]
    raw0[7]["rank"] = "91813"
    res = T.parse_trial_payload(data, DATE)
    code = str((raw0[0].get("param") or {}).get("code"))
    assert res["rows"][code]["end_time"] == "09:18:13"


def test_trial_line_hhmmss_end_not_mislabeled_full_match():
    """渲染器防御：end_time=91948（未归一化残留）不得标「竞价全程匹配」也不得
    原样渲染假时间——归一化后 09:19:48 < 09:25 → 「09:19:48 时点」。"""
    trial = {"start_time": "09:15:01", "end_time": "91948",
             "jj_percent": 4.78, "jj_amount": 13_979_616.0}
    ln = AL.auction_trial_line(trial)
    assert ln is not None
    assert "91948" not in ln
    assert "竞价全程匹配" not in ln
    assert "09:19:48 时点" in ln


def test_parse_schema_drift_guard():
    """review finding-1：head_info sort_key 序 ≠ 合同列序 → parse_error（错位风险下
    不得冒充事实）；首列 stock_id 别名放行；dropped/duplicateCodes 观测留痕。"""
    data = _load()
    res = T.parse_trial_payload(data, DATE)
    assert res["state"] == "ok" and res["obs"]["headSortKeys"][0] == "stock_id"
    assert res["obs"]["dropped"] == 0 and res["obs"]["duplicateCodes"] == 0
    # 列序漂移：交换两列 sort_key → parse_error + 指纹
    bad = _load()
    head = bad["data"]["data"]["stock_list"]["head_info"]
    head[1], head[2] = head[2], head[1]
    r2 = T.parse_trial_payload(bad, DATE)
    assert r2["state"] == "parse_error" and "schema_drift" in r2["error"]
    assert r2["rows"] == {} and r2["n_rows"] == 0
    # head_info 整体缺失 → parse_error
    none_head = _load()
    del none_head["data"]["data"]["stock_list"]["head_info"]
    r3 = T.parse_trial_payload(none_head, DATE)
    assert r3["state"] == "parse_error" and r3["rows"] == {}
    # 重复码观测
    dup = _load()
    dup["data"]["data"]["stock_list"]["list"].append(dup["data"]["data"]["stock_list"]["list"][0])
    r4 = T.parse_trial_payload(dup, DATE)
    assert r4["obs"]["duplicateCodes"] == 1 and r4["n_rows"] == 3


def test_persist_trial_raw_carries_obs_fingerprint():
    """raw 档携带 obs（headSortKeys/dropped/duplicateCodes）供回溯审计。"""
    db = _FakeDb()
    res = T.parse_trial_payload(_load(), DATE)
    T.persist_trial_raw(db, DATE, res)
    doc = db[T.COLLECTION_TRIAL_RAW].docs[DATE]
    assert doc["obs"]["headSortKeys"][0] == "stock_id"


def test_saved_at_age_offset_aware():
    """review finding-3：+08:00 偏移与 naive（按 CST 合同）龄一致；不可判 → None。"""
    now = T.datetime(2026, 11, 13, 9, 26, 2, tzinfo=T.timezone(T.timedelta(hours=8))).timestamp()
    assert T._saved_at_age("2026-11-13T09:26:00", now=now) == 2.0
    assert T._saved_at_age("2026-11-13T09:26:00+08:00", now=now) == 2.0
    assert T._saved_at_age("garbage", now=now) is None
