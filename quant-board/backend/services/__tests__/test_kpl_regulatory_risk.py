# -*- coding: utf-8 -*-
"""kpl_regulatory_risk 协议层单测（2026-11-15 预登记 theme-leader-regulatory-risk）。

列序 fixture 取自 2026-11-15 探针实弹（预登记 §2 定档，与 App 截图交叉）。
pytest 纪律：全 mock（红线 7）；fetch 仅采集/运维路径真实调用。
"""
import pytest

from backend.services import kpl_regulatory_risk as R
from backend.services.kpl_ranking_service import KplRankingError

# 触发组行（20 列，探针 2026-11-13 样本：大东方/辰奕智能）
ROW_TODAY = ["600327", "大东方", "10日100%", -10.03, "昨5连板", 7.8, 7.74, 17.83,
             "未触发异动", 22.29, "零售、文创用品", 0, "10日100%", 7.9, 0, 0, 0,
             "", "2026-11-13", 6.46]
ROW_TOMORROW = ["301578", "辰奕智能", "10日100%", 0, "", 17.9, 42.23, 18.79,
                "未触发异动", 17.9, "消费电子、智能音箱", 0, "10日100%", 42.23,
                0, 0, 0, "", "2026-11-13", 35.82]
# 近期组行（天普股份：停牌+重点监控；福新转债：触发严重异动）
ROW_RECENT_SUSP = ["605255", "天普股份", "股票价格异常波动达到停牌核查", 10, "", 0, 0, 0,
                   "未触发异动", 0, "实控人变更、汽车零部件", 1, "股票价格异常波动达到停牌核查",
                   0, 0, 0, 1, "2026-11-19", "2026-11-16", 73.82]
ROW_RECENT_TRIG = ["111012", "福新转债", "30日200%", 5.22, "", 2.43, 922.963, -2.79,
                   "触发严重异动", 10.64, "皮革、汽车零部件", 0, "30日200%", 922.963,
                   -20, 1, 0, "0000-00-00", "2026-11-11", 948.111]
ROW_MONITOR = ["600825", "新华传媒", "2026-11-13", "2026-11-26", 2, 0, 0, 0, 0, 0]


def test_parse_trigger_today_space_and_streak():
    p = R.parse_trigger_row(ROW_TODAY, group="today")
    assert p["stock_id"] == "600327" and p["stock_name"] == "大东方"
    assert p["space_pct"] == 17.83 and p["trigger_pct"] == 7.8
    assert p["streak_tag"] == "昨5连板" and p["period"] == "10日100%"
    assert p["monitor_flag"] is False and not p.get("partial")
    assert p["raw"] == ROW_TODAY


def test_parse_trigger_tomorrow_uses_col9():
    p = R.parse_trigger_row(ROW_TOMORROW, group="tomorrow")
    assert p["space_pct"] == 17.9 and p["trigger_pct"] == 17.9
    assert p["streak_tag"] is None


def test_parse_trigger_short_row_partial_missing_none():
    p = R.parse_trigger_row(["600327", "大东方"], group="today")
    assert p["partial"] is True
    assert p["space_pct"] is None and p["trigger_pct"] is None  # 缺位不补 0


def test_parse_recent_flags_and_dates():
    s = R.parse_recent_row(ROW_RECENT_SUSP)
    assert s["suspended_flag"] is True and s["triggered_flag"] is False
    assert s["resume_date"] == "2026-11-19" and s["abnormal_date"] == "2026-11-16"
    assert s["monitor_flag"] is True
    assert s["period"] is None  # 状态文本不是周期标签，形态判别
    t = R.parse_recent_row(ROW_RECENT_TRIG)
    assert t["triggered_flag"] is True and t["suspended_flag"] is False
    assert t["resume_date"] is None  # 0000-00-00 → None
    assert t["period"] == "30日200%"


def test_parse_monitor_row():
    m = R.parse_monitor_row(ROW_MONITOR)
    assert m["stock_id"] == "600825" and m["start_date"] == "2026-11-13"
    assert m["end_date"] == "2026-11-26"


def test_build_payload_missing_vs_true_zero():
    states = {"severe": {"ok": True}, "monitor_current": {"ok": False, "reason": "x"}}
    raws = {"severe": {"List_Today": [], "List_Tormorow": [ROW_TOMORROW]}}
    p = R.build_regulatory_payload(raws, states, date="2026-11-13")
    assert p["groups"]["today"] == []          # errcode=0 空列表=真零
    assert p["groups"]["monitor_current"] is None  # 端点失败=缺失
    assert p["groups"]["recent"] is None
    assert len(p["groups"]["tomorrow"]) == 1
    assert "301578" in p["by_code"]


def test_build_payload_by_code_and_recent_dedup():
    raws = {"severe": {"List_Today": [ROW_TODAY], "List_Tormorow": []},
            "recent_0": {"List_His": [ROW_RECENT_SUSP, ROW_RECENT_TRIG]},
            "recent_1": {"List_His": [ROW_RECENT_SUSP]},   # 跨页重复去重
            "monitor_current": {"List": [ROW_MONITOR]},
            "monitor_history": {"List": []}}
    states = {k: {"ok": True} for k in raws}
    p = R.build_regulatory_payload(raws, states, date="2026-11-13")
    assert len(p["groups"]["recent"]) == 2
    assert p["by_code"]["600825"]["monitor_current"]["stock_id"] == "600825"
    hit = p["by_code"]["605255"]
    assert len(hit["recent"]) == 1 and hit["recent"][0]["suspended_flag"]
    assert p["by_code"]["600327"]["today"]["space_pct"] == 17.83
    assert p["groups"]["monitor_history"] == []


def test_fetch_endpoint_isolation_and_calls(monkeypatch):
    seen = []

    def fake_post(url, params, ua):
        seen.append((url, params["a"]))
        if params["a"] == "GetPianLiZhi_W46":
            raise KplRankingError("kpl_errcode", errorCode="1002")
        if params["a"] == "GetYDTP_ZDJK_Today":
            return {"errcode": "0", "List": [ROW_MONITOR]}
        return {"errcode": "0", "List": []}

    monkeypatch.setattr(R, "_post_form", fake_post)
    out = R.fetch_regulatory_raw(None, sleeper=lambda s: None)
    assert out["states"]["severe"]["ok"] is False
    assert out["states"]["recent_0"] == {"ok": False, "reason": "no_date"}  # 不猜日期
    assert out["states"]["monitor_current"]["ok"] is True
    assert out["calls"] == 3  # severe1 + monitor2（recent skip）
    assert out["day"] is None


def test_fetch_with_date_uses_his_and_recent_pages(monkeypatch):
    seen = []

    def fake_post(url, params, ua):
        seen.append((url, params))
        if params["a"] == "GetYDTPZFPL_W46":
            return {"errcode": "0", "Day": params["Day"], "List_Today": [ROW_TODAY],
                    "List_Tormorow": []}
        if params["a"] == "GetYDTPZFPL_W46_HisAll":
            return {"errcode": "0", "List_His": [ROW_RECENT_TRIG], "List_His_Total": 1}
        return {"errcode": "0", "List": [ROW_MONITOR]}

    monkeypatch.setattr(R, "_post_form", fake_post)
    out = R.fetch_regulatory_raw("2026-11-13", sleeper=lambda s: None)
    assert out["day"] == "2026-11-13" and out["calls"] == 5
    his_urls = [u for u, p in seen if p["a"] == "GetYDTPZFPL_W46_HisAll"]
    assert all(u == R._HOST_HIS for u in his_urls)
    assert [p["Index"] for u, p in seen if p["a"] == "GetYDTPZFPL_W46_HisAll"] == ["0", "1"]
    assert out["states"]["monitor_history"]["ok"] is True


def test_pytest_guard_blocks_real_http():
    # 未 monkeypatch _post_form 时 pytest 进程内 fetch 必须抛护栏（红线 7）
    with pytest.raises(RuntimeError, match="红线 7"):
        R.fetch_regulatory_raw(None, sleeper=lambda s: None)


class _FakeColl:
    def __init__(self):
        self.rows = {}

    def update_one(self, q, update, upsert=False):
        row = self.rows.setdefault(q["_id"], {"_id": q["_id"]})
        row.update(update["$set"])

    def find_one(self, q, projection=None):
        row = self.rows.get(q.get("_id"))
        return dict(row) if row else None

    def find(self, q, projection=None):
        out = [dict(r) for r in self.rows.values()
               if all(r.get(k) is not None for k, c in q.items()
                      if isinstance(c, dict) and "$exists" in c)]
        return _FakeCursor(out)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, field, direction):
        self.rows.sort(key=lambda r: str(r.get(field) or ""), reverse=direction < 0)
        return self

    def limit(self, n):
        return self.rows[:n]


class _FakeDb:
    def __init__(self):
        self.coll = _FakeColl()

    def __getitem__(self, name):
        assert name == "kpl_daban_pool"
        return self.coll


def _payload(date="2026-11-13", ok_severe=True):
    states = {"severe": {"ok": ok_severe}, "monitor_current": {"ok": True}}
    raws = {"severe": {"List_Today": [ROW_TODAY], "List_Tormorow": []},
            "monitor_current": {"List": [ROW_MONITOR]}}
    p = R.build_regulatory_payload(raws, states, date=date)
    p["calls"] = 5
    return p


def test_archive_partial_write_and_load_roundtrip():
    from backend.services.kpl_daban_archiver import (
        archive_regulatory_corpus, load_regulatory_corpus, latest_regulatory_day)
    db = _FakeDb()
    res = archive_regulatory_corpus(db, _payload())
    assert res["ok"] is True and res["codes"] == 2
    load = load_regulatory_corpus(db, "2026-11-13")
    assert load["ok"] and load["by_code"]["600327"]["today"]["space_pct"] == 17.83
    assert latest_regulatory_day(db) == "2026-11-13"
    assert load_regulatory_corpus(db, "2026-11-12")["ok"] is False


def test_archive_all_sources_failed_not_written():
    from backend.services.kpl_daban_archiver import (
        archive_regulatory_corpus, load_regulatory_corpus)
    db = _FakeDb()
    p = _payload(ok_severe=False)
    p["states"]["monitor_current"] = {"ok": False, "reason": "x"}
    p["groups"] = {k: None for k in p["groups"]}
    p["by_code"] = {}
    assert archive_regulatory_corpus(db, p)["ok"] is False
    assert load_regulatory_corpus(db, "2026-11-13")["ok"] is False
    # 空日期不写
    assert archive_regulatory_corpus(db, {**_payload(), "date": None})["reason"] == "empty_date"


def test_no_code_rows_preserved_and_dropped_counted():
    """review m4：空代码行保留+no_code（不静默丢、不进索引）；畸形行计数入 dropped。"""
    raws = {"severe": {"List_Today": [ROW_TODAY, ["", "空码", "10日100%"], "malformed"],
                       "List_Tormorow": []},
            "monitor_current": {"List": [ROW_MONITOR, []]}}
    states = {k: {"ok": True} for k in raws}
    p = R.build_regulatory_payload(raws, states, date="2026-11-13")
    assert len(p["groups"]["today"]) == 2
    assert p["groups"]["today"][1]["no_code"] is True
    assert p["dropped"] == {"today": 1}
    assert "" not in p["by_code"] and "600327" in p["by_code"]
    assert len(p["groups"]["monitor_current"]) == 2
    assert p["groups"]["monitor_current"][1]["no_code"] is True


def test_recent_no_code_preserved_without_dedup():
    row_nc = ["", "x", "30日200%", 0, "", 0, 0, 0, "触发严重异动", 0, "", 0,
              "30日200%", 0, 0, 1, 0, "0000-00-00", "2026-11-11", 0]
    raws = {"recent_0": {"List_His": [row_nc, row_nc]}}
    p = R.build_regulatory_payload(raws, {"recent_0": {"ok": True}}, date="2026-11-13")
    assert len(p["groups"]["recent"]) == 2   # 空代码无法安全判重→全保留
    assert all(i["no_code"] for i in p["groups"]["recent"])
    assert p["by_code"] == {}


def test_recent_single_page_failure_partial_build():
    """m5：recent_0 ok / recent_1 失败 → 部分页仍构建 + states 留痕。"""
    raws = {"recent_0": {"List_His": [ROW_RECENT_SUSP]}}
    states = {"recent_0": {"ok": True},
              "recent_1": {"ok": False, "reason": "errcode:1002"}}
    p = R.build_regulatory_payload(raws, states, date="2026-11-13")
    assert len(p["groups"]["recent"]) == 1
    assert p["states"]["recent_1"]["ok"] is False