# -*- coding: utf-8 -*-
"""涨停打标读数聚合测试：个股/哨兵分流 + no_data fail-visible + 分布小结。

2026-10-05 批次A（C1）：degraded 文档结构化暴露（summary.degraded/phaseStatus），
读口不再按 status=ok 静默过滤（fail-visible，AGENTS §4.0）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev.jev_limitup_labels import collect_limitup_labels


class FakeCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, projection=None):
        # 读口不再带 status 条件（C1）：按 _id 命中即返回
        for d in self.docs:
            if d.get("_id") == query.get("_id"):
                return d
        return None

    def find(self, query, projection=None):
        excluded = (query.get("origin") or {}).get("$ne")
        return [d for d in self.docs
                if d.get("tradingDate") == query.get("tradingDate")
                and d.get("origin") != excluded]


class FakeDb:
    def __init__(self, docs):
        self._col = FakeCol(docs)

    def __getitem__(self, name):
        return self._col


def _stock(code, rank=None, label="ma_restructure", status="ok"):
    return {"_id": f"2026-09-30:{code}", "tradingDate": "2026-09-30", "status": status,
            "origin": "driver_label_jiuyan_v3_pilot", "code": code, "name": "X",
            "label": label, "catalystDepth": "core_main_business", "freshness": "continuing",
            "buySideLogic": "sector_follow",
            "jiuyanContext": {"inHotlist": rank is not None, "rank": rank}}


def _phase_doc(status="ok"):
    doc = {"_id": "2026-09-30:PHASE", "tradingDate": "2026-09-30", "status": status,
           "origin": "phase_band_daily", "computedAt": "t"}
    if status == "ok":
        doc.update({"phaseBand": "strong_ge60", "phaseBandProbabilities": {"strong_ge60": 0.7}})
    else:
        doc.update({"errorCode": "http_error", "errorDetail": "HTTP 500 boom"})
    return doc


def test_collect_splits_phase_and_stocks():
    docs = [_phase_doc(), _stock("600000", 5), _stock("000001")]
    out = collect_limitup_labels(FakeDb(docs), "2026-09-30")
    assert out["ok"] is True and out["noData"] is False
    assert out["phaseStatus"] == "ok" and out["phaseError"] is None
    assert out["phase"]["band"] == "strong_ge60"
    assert len(out["stocks"]) == 2  # PHASE 哨兵不混入个股列表
    assert out["summary"]["total"] == 2
    assert out["summary"]["label"]["ma_restructure"] == 2
    assert out["summary"]["degradedCount"] == 0
    # 无排名沉底：有排名在前
    assert out["stocks"][0]["rank"] == 5


def test_collect_passthrough_stock_phase_fields():
    # 个股相位分线试点字段透传（2026-10-04）；未跑日字段缺失=None=fail-visible 不伪造
    a = _stock("600000", 5)
    a["stockPhasePosition"] = "climax"
    a["stockPhaseProbabilities"] = {"climax": 0.6}
    out = collect_limitup_labels(FakeDb([a, _stock("000001")]), "2026-09-30")
    by_code = {s["code"]: s for s in out["stocks"]}
    assert by_code["600000"]["stockPhasePosition"] == "climax"
    assert by_code["600000"]["stockPhaseProbabilities"] == {"climax": 0.6}
    assert by_code["000001"]["stockPhasePosition"] is None
    assert by_code["000001"]["stockPhaseProbabilities"] is None


def test_collect_passthrough_label_slot():
    """投喂槽位透传（2026-10-20）：midday=午盘 12:30 投喂，final=收盘投喂；
    旧档无 labelSlot → None（前端不伪造档位，也不把旧档当收盘档膏称）。"""
    mid = _stock("603278", 5)
    mid["labelSlot"] = "midday"
    mid["jiuyanFetchedAt"] = "2026-10-20T12:06:00"
    fin = _stock("600001", 1)
    fin["labelSlot"] = "final"
    out = collect_limitup_labels(FakeDb([mid, fin, _stock("000001")]), "2026-09-30")
    by_code = {s["code"]: s for s in out["stocks"]}
    assert by_code["603278"]["labelSlot"] == "midday"
    assert by_code["603278"]["jiuyanFetchedAt"] == "2026-10-20T12:06:00"
    assert by_code["600001"]["labelSlot"] == "final"
    assert by_code["000001"]["labelSlot"] is None


def test_collect_stock_row_carries_trading_date():
    """归属交易日透传（2026-10-22 报障修复）：个股复跑 POST /limitup-labels/rerun 以行内
    tradingDate 组 payload；此前行缺此字段 → 前端发 undefined → 后端 422，重跑按钮永远失败。
    行内 tradingDate 必须等于读口入参 date（单一事实源，不取存档字段防陈旧）。"""
    out = collect_limitup_labels(FakeDb([_stock("603278", 5)]), "2026-09-30")
    assert out["stocks"][0]["tradingDate"] == "2026-09-30"


def test_collect_no_data_fail_visible():
    out = collect_limitup_labels(FakeDb([]), "2026-10-11")
    assert out["ok"] is True and out["noData"] is True
    assert out["stocks"] == [] and out["phase"] is None
    assert "无涨停打标" in out["reason"]


# ---- 批次A C1：degraded 文档结构化暴露 ----

def test_degraded_stock_surfaced_not_hidden():
    """降级个股不进 stocks（前端合同不变），但必须以结构化条目可见（fail-visible）。"""
    bad = _stock("600000", 5, status="degraded")
    bad.update({"label": None, "errorCode": "partial_answers",
                "errorDetail": "missing answers: catalyst_depth"})
    out = collect_limitup_labels(FakeDb([bad, _stock("000001", 1)]), "2026-09-30")
    assert [s["code"] for s in out["stocks"]] == ["000001"]  # stocks 仍只含 ok
    assert out["summary"]["total"] == 1
    assert out["summary"]["degradedCount"] == 1
    assert out["summary"]["degraded"] == [
        {"code": "600000", "name": "X", "status": "degraded",
         "errorCode": "partial_answers", "errorDetail": "missing answers: catalyst_depth",
         "computedAt": None}]
    assert out["noData"] is False  # 有文档（哪怕全降级）不谎报 no_data


def test_degraded_phase_surfaced_with_error():
    """PHASE 失败：phase=None 不伪造档位，但 phaseStatus/phaseError 必须可见。"""
    out = collect_limitup_labels(FakeDb([_phase_doc("degraded"), _stock("600000", 1)]), "2026-09-30")
    assert out["phase"] is None
    assert out["phaseStatus"] == "degraded"
    assert out["phaseError"] == {"errorCode": "http_error", "errorDetail": "HTTP 500 boom"}
    assert out["noData"] is False


def test_all_degraded_day_still_not_no_data():
    out = collect_limitup_labels(FakeDb([_stock("600000", None, status="degraded")]), "2026-09-30")
    assert out["stocks"] == [] and out["summary"]["total"] == 0
    assert out["summary"]["degradedCount"] == 1
    assert out["noData"] is False
    assert out["reason"] is None


def test_with_raw_includes_call_material_default_unchanged():
    """with_raw=True（relay_page 调用日志展开用）附带调用原始字段；默认合同不变（根前端零影响）。"""
    d = _stock("600000", 5)
    d.update({"narrative": "叙事全文…", "questionsRaw": {"driver_type": {}},
              "responseRaw": None, "model": "jev-1.13.0",
              "usage": {"input_tokens": 100, "output_tokens": 10},
              "latencyMs": 528, "errorCode": None, "questionSetVersion": "v3.1"})
    out_default = collect_limitup_labels(FakeDb([d]), "2026-09-30")
    s_def = out_default["stocks"][0]
    assert "narrative" not in s_def and "_id" not in s_def and "usage" not in s_def
    assert "status" not in s_def  # 既有合同：个股条目不带 status

    out_raw = collect_limitup_labels(FakeDb([d]), "2026-09-30", with_raw=True)
    s_raw = out_raw["stocks"][0]
    assert s_raw["narrative"] == "叙事全文…"
    assert s_raw["_id"] == "2026-09-30:600000"
    assert s_raw["questionsRaw"] == {"driver_type": {}}
    assert s_raw["responseRaw"] is None  # 成功路径如实透传 None（不伪造 envelope）
    assert s_raw["model"] == "jev-1.13.0" and s_raw["latencyMs"] == 528
    assert s_raw["status"] == "ok"
    # 共有字段两态一致（不因 with_raw 漂移）
    for k in ("code", "name", "label", "catalystDepth", "rank"):
        assert s_raw[k] == s_def[k]
