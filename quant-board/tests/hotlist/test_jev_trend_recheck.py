# -*- coding: utf-8 -*-
"""趋势维独立判读（题集 v1 试点）测试。全 fake db，零 IO 零 jev 调用（AGENTS §1.2-7）。"""
from __future__ import annotations

import pytest

from backend.analysis.hotlist.jev_trend_ammo import (
    QUESTIONS_TREND_RECHECK,
    QUESTION_SET_VERSION_TREND_RECHECK,
    TREND_AMMO_VERSION,
    TREND_MIN_BARS,
    build_trend_narrative,
    derived_indicators,
    strength_band,
    trend_risk_flag,
)
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.primitives import (
    get_technical_min_computable_samples,
)
from backend.analysis.ranktrend.trend.technical import (
    calculate_macd,
    calculate_ma_cross,
    momentum_profile,
    moving_average,
)
from backend.operations import jev_trend_recheck as runner

DATE = "2026-10-14"
SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30",
         "13:00", "13:30", "14:00", "14:30", "15:00"]
DATASET = "dragonboard_live"

# 黑名单：判定产物/他维读数一律不进叙事（机验）
_BLACKLIST = ("signalTier", "synergy", "finalSignal", "compScore", "compRank",
              "lifecycle", "cooling", "ignition", "voteDirection", "temperature",
              "crowding", "量比结论", "resonance_direction", "trendDirection")


class _Col:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        q = query or {}
        return [r for r in self.rows
                if all(r.get(k) == v for k, v in q.items() if not str(k).startswith("$"))]

    def find_one(self, query=None, projection=None, sort=None):
        for r in self.find(query):
            return r
        return None

    def replace_one(self, query, doc, upsert=False):
        self.rows = [r for r in self.rows if r.get("_id") != query.get("_id")]
        self.rows.append(doc)


class _Db:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.setdefault(name, _Col())


def _row(code, rank, avg_rank_num, slot, date=DATE, **extra):
    r = {"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": code,
         "name": f"股{code}", "rank": rank, "avgRankNum": avg_rank_num,
         "change": 1.5, "volumeRatio": 1.2, "zlje": 1000.0, "zljzb": 0.1}
    r.update(extra)
    return r


def _pool(n, date=DATE, avg_base=1.0):
    """n 只股的一帧行集（avgRankNum 递减 → attention rank 稳定）。"""
    return [_row(f"600{i:03d}", i + 1, avg_base - i * 0.01, "15:00", date=date)
            for i in range(n)]


def _ten_slots(rows, date=DATE):
    """把一帧行集铺成当日 10 个槽（每股每槽都在榜 → 10 次出现）。"""
    out = {}
    for slot in SLOTS:
        out[slot] = [dict(r, slotTime=slot, snapshotId=f"half_hour:{date}:{slot}")
                     for r in rows]
    return out


def _db_across_days(days: dict[str, dict[str, list[dict]]]) -> _Db:
    """多日帧骨架：days={tradingDate: {slot: [row,...]}}（行的 snapshotId 按所属帧重写）。"""
    frames, rows = [], []
    for d, per_slot in days.items():
        for slot, slot_rows in per_slot.items():
            sid = f"half_hour:{d}:{slot}"
            frames.append({"datasetId": DATASET, "type": "half_hour",
                           "tradingDate": d, "slotTime": slot, "snapshotId": sid})
            for r in slot_rows:
                r["snapshotId"] = sid
            rows.extend(slot_rows)
    return _Db({"snapshot_frames": _Col(frames), "snapshot_stock_rows": _Col(rows),
                "snapshot_analysis": _Col([])})


def _db_with_slots(slots: dict[str, list[dict]], date=DATE) -> _Db:
    return _db_across_days({date: slots})


def _fake_dispatch(calls: list, direction="buy", score=71, conf=0.62):
    def _dispatch(state, questions):
        calls.append((state, questions))
        return {"success": True, "result": {"state": "Completed", "result": {
            "model": "typesafe/jev",
            "answers": {
                "trend_direction": {"type": "choice", "choice": direction,
                                    "confidence": conf,
                                    "probabilities": {direction: conf}},
                "trend_strength": {"type": "score", "score": score, "confidence": conf}},
            "usage": {"input_tokens": 900, "output_tokens": 70}}}}, 88
    return _dispatch


# ── 判据冻结件形状 ──

def test_criteria_frozen_shape():
    q = QUESTIONS_TREND_RECHECK
    assert set(q) == {"trend_direction", "trend_strength"}
    assert q["trend_direction"]["type"] == "choice"
    assert set(q["trend_direction"]["criteria"]) == {"buy", "sell", "hold", "insufficient"}
    assert q["trend_strength"]["type"] == "score"
    assert len(q["trend_strength"]["criteria"]) == 10  # 10 档锚点
    instr = q["trend_direction"]["instructions"]
    # 口径铁律：buy/sell 只表示注意力技术面方向，绝不表示「值不值得买」
    assert "绝不表示「这只票值不值得买」" in instr
    assert "只依据所所信息判断" not in instr
    assert "只依据所给信息判断，不预测后市" in instr
    # 两步走 + 分量共识门（与引擎 compose_decision 的 minAgreement/maxOpposition 同构）
    assert "判读按两步走" in instr
    assert "同一方向的分量 ≥2 个、且反方向分量 ≤1 个 → 该方向" in instr
    assert "序列深度 <22 次出现时" in instr
    # 强度题：不得与方向矛盾
    assert "强度不得与方向矛盾" in q["trend_strength"]["instructions"]
    # 版本戳独立
    assert QUESTION_SET_VERSION_TREND_RECHECK == "v1"
    assert TREND_AMMO_VERSION.startswith("2026-10-15")


def test_precheck_thresholds_are_engine_single_source():
    cfg = RankTrendConfig()
    assert TREND_MIN_BARS == get_technical_min_computable_samples(cfg)  # 22
    assert trend_risk_flag(30) == {"level": "ok", "mode": "series", "reasons": []}
    fb = trend_risk_flag(5)
    assert fb["level"] == "partial" and fb["mode"] == "fallback"
    assert f"<{TREND_MIN_BARS}" in fb["reasons"][0]
    ins = trend_risk_flag(1)
    assert ins["level"] == "data_insufficient" and ins["mode"] is None


def test_derived_indicators_are_engine_same_source():
    """派生读数必须逐位等于引擎 trend/technical.py 的同函数输出（零第二实现）。"""
    pcts = [50.0 + (i % 7) * 1.5 - (3 if i > 15 else 0) for i in range(30)]
    cfg = RankTrendConfig()
    d = derived_indicators(pcts)
    assert d["ma5"] == moving_average(pcts, 5)
    assert d["ma10"] == moving_average(pcts, 10)
    macd = calculate_macd(pcts, cfg)
    assert d["macd"]["dif"] == macd["dif"] and d["macd"]["cross"] == macd["cross"]
    assert d["macd"]["histogram"] == macd["histogram"]
    cross = calculate_ma_cross(pcts, cfg)
    assert d["maCross"]["state"] == cross["state"] and d["maCross"]["cross"] == cross["cross"]
    mom = momentum_profile(pcts)
    assert d["momentum"]["short"] == mom["short"] and d["momentum"]["acceleration"] == mom["acceleration"]
    assert d["maTrend"] == ("up" if d["ma5"] > d["ma10"] else "down")


def test_derived_indicators_fail_visible_on_short_series():
    """短序列：不可算分量如实 None/unknown，不伪造 0（引擎 calculate_ma_cross 同口径）。"""
    d = derived_indicators([50.0, 52.0, 51.0])
    cfg = RankTrendConfig()
    assert d["maCross"]["state"] == "unknown" and d["maCross"]["cross"] == "none"
    assert d["macd"]["cross"] == calculate_macd([50.0, 52.0, 51.0], cfg)["cross"]
    assert derived_indicators([])["maTrend"] is None


# ── 叙事 ──

def test_narrative_fail_visible_and_scope_isolation():
    series = ([{"tradingDate": "2026-10-13", "slot": "09:30", "rank": 10, "total": 200,
                "percentile": 50.0, "delta": None}] * 6
              + [{"tradingDate": "2026-10-14", "slot": "13:30", "rank": 10, "total": 200,
                  "percentile": 52.0, "delta": 2.0},
                 {"tradingDate": "2026-10-14", "slot": "14:30", "rank": 8, "total": 200,
                  "percentile": 58.0, "delta": 6.0},
                 {"tradingDate": "2026-10-14", "slot": "15:00", "rank": 9, "total": 200,
                  "percentile": 60.0, "delta": 2.0}])
    derived = derived_indicators([s["percentile"] for s in series])
    text = build_trend_narrative(
        trading_date=DATE, slot="15:00", code="600001", name="测试股", series=series,
        derived=derived,
        frame_fields={"displayChange": 2.0, "stockChange": 1.5, "volumeRatio": 1.2,
                      "zlje": 1000.0, "zljzb": 0.1},
        entry={"isNew": False, "currentPercentile": 60.0},
        quality={"missingAppearances": [], "missingFields": []})
    assert "history depth: 9 appearances · mode: fallback" in text
    assert "2026-10-13 09:30: pct 50.0" in text and "Δ+6.0" in text
    assert "[Derived Readings" in text and "MACD(13/21/8)" in text and "MA fast/slow(10/20)" in text
    assert "momentum: short=" in text
    assert "PRIMARY evidence when series <22 appearances" in text
    assert "displayChange (last-appearance percentile delta) = +2.0" in text
    assert "volumeRatio = 1.2" in text and "zlje = 1000.0" in text
    assert "first appearance in series (new entry): no" in text
    for word in _BLACKLIST:
        assert word not in text, word


def test_narrative_series_mode_marks_primary_evidence():
    series = [{"tradingDate": "2026-10-13", "slot": "09:30", "rank": 10, "total": 200,
               "percentile": 50.0 + i, "delta": 1.0} for i in range(25)]
    text = build_trend_narrative(
        trading_date=DATE, slot="15:00", code="600001", name="x", series=series,
        derived=derived_indicators([s["percentile"] for s in series]),
        frame_fields={"displayChange": 1.0, "stockChange": 1.5, "volumeRatio": 1.2,
                      "zlje": 1000.0, "zljzb": 0.1},
        entry={"isNew": False, "currentPercentile": 74.0},
        quality={"missingAppearances": [], "missingFields": ["volumeRatio"]})
    assert "mode: series（序列可算：主证据=序列+派生读数）" in text
    assert "missing fields: ['volumeRatio']" in text


def test_strength_band_matches_engine_label_thresholds():
    assert strength_band(90) == "非常强" and strength_band(70) == "强"
    assert strength_band(55) == "中等" and strength_band(30) == "较弱"
    assert strength_band(5) == "非常弱" and strength_band(None) is None


# ── 人口与取数（同源）──

def test_population_modes_and_engine_anchor():
    """跨日 3 天 ×10 槽：全勤股 30 次出现=series 模式；只出现 3 槽=fallback 模式。"""
    days = {d: _ten_slots(_pool(24), date=d) for d in
            ("2026-10-10", "2026-10-13", "2026-10-14")}
    for s in SLOTS:
        if s in ("13:30", "14:30", "15:00"):
            days["2026-10-14"][s].append(_row("600999", 25, 0.05, s))
    db = _db_across_days(days)
    db["snapshot_analysis"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "600000",
         "analysis": {"observation": {"rankTrend": {"direction": "hold", "score": 12.0,
                                                    "signedScore": 0.12, "signalTier": "C"}}}}]
    pop = runner.build_population(db, DATE)
    assert pop["meta"]["poolSize"] == 25
    assert pop["meta"]["modes"] == {"series": 24, "fallback": 1}
    c0 = next(c for c in pop["candidates"] if c["code"] == "600000")
    assert c0["bars"] == 30 and c0["mode"] == "series"
    assert c0["series"][-1]["tradingDate"] == DATE and c0["series"][-1]["slot"] == "15:00"
    assert c0["engine"]["direction"] == "hold" and c0["engine"]["signalTier"] == "C"
    c5 = next(c for c in pop["candidates"] if c["code"] == "600999")
    assert c5["bars"] == 3 and c5["mode"] == "fallback"
    assert c5["riskFlag"]["level"] == "partial"
    # 帧行字段 = 引擎 fallback 输入（displayChange=末项−前项分位差）
    assert isinstance(c5["frameFields"]["displayChange"], float)
    assert c5["frameFields"]["stockChange"] == 1.5


def test_population_insufficient_when_single_appearance():
    """单次出现：连末项−前项都不可算 → data_insufficient 留痕不调用。"""
    slots = _ten_slots(_pool(24))
    for s in SLOTS[:-1]:
        slots[s] = [r for r in slots[s] if r["code"] != "600000"]
    pop = runner.build_population(_db_with_slots(slots), DATE)
    c = next(c for c in pop["insufficient"] if c["code"] == "600000")
    assert c["bars"] == 1 and c["riskFlag"]["mode"] is None
    assert c["riskFlag"]["reasons"][0].startswith("序列出现次数=1(<2")


def test_population_no_frame():
    pop = runner.build_population(_db_with_slots({}), "2026-10-20")
    assert pop["meta"]["error"] == "no_frame" and pop["candidates"] == []


# ── dry-run / fire / 幂等 ──

def test_dry_run_zero_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    stats = runner.run_trend_day(_db_with_slots(_ten_slots(_pool(24))), [DATE], fire=False)
    assert calls == [] and stats["tokens"] == 0


def test_fire_persist_contract_and_engine_anchor(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(24), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    db["snapshot_analysis"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "600000",
         "analysis": {"observation": {"rankTrend": {"direction": "hold", "score": 12.5,
                                                    "signedScore": 0.125, "signalTier": "C",
                                                    "tierReasons": ["中性"]}}}}]
    stats = runner.run_trend_day(db, [DATE], fire=True)
    assert len(calls) == 24 and calls[0][1] == QUESTIONS_TREND_RECHECK
    assert stats["ok"] == 24 and stats["tokens"] == 24 * 970
    doc = db["hotlist_jev_trend_recheck_pilot"].find_one({"_id": f"{DATE}:15:00:600000:THD"})
    assert doc["_id"] == f"{DATE}:15:00:600000:THD"
    assert doc["trendDirection"] == "buy" and doc["trendConfidence"] == 0.62
    assert doc["trendScore"] == 71 and doc["trendProbabilities"]["buy"] == 0.62
    assert doc["answers"]["trend_direction"]["choice"] == "buy"
    assert doc["questionSetVersion"] == "v1" and doc["ammoVersion"] == TREND_AMMO_VERSION
    assert doc["mode"] == "series" and doc["bars"] == 30
    # 引擎对照锚快照（同帧同股，台账机械可算）
    assert doc["engineDirection"] == "hold" and doc["engineTier"] == "C"
    assert doc["engineScore"] == 12.5 and doc["engineSignedScore"] == 0.125


def test_fire_is_idempotent_done_skip(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(20), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    runner.run_trend_day(db, [DATE], fire=True)
    assert len(calls) == 20
    stats = runner.run_trend_day(db, [DATE], fire=True)  # 同代际 ok 文档跳过，零重复调用
    assert len(calls) == 20 and stats["skip"] == 20 and stats["tokens"] == 0


def test_fire_reruns_when_question_set_generation_changes(monkeypatch):
    """代际升级（改门）必须重跑：旧代际 ok 文档不挡新代际；同 _id 整档覆盖。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(20), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    monkeypatch.setattr(runner, "QUESTION_SET_VERSION_TREND_RECHECK", "v1")
    runner.run_trend_day(db, [DATE], fire=True)
    assert len(calls) == 20
    assert db["hotlist_jev_trend_recheck_pilot"].find_one({"code": "600000"})["questionSetVersion"] == "v1"
    monkeypatch.setattr(runner, "QUESTION_SET_VERSION_TREND_RECHECK", "v2")
    stats = runner.run_trend_day(db, [DATE], fire=True)
    assert len(calls) == 40 and stats["skip"] == 0 and stats["ok"] == 20
    doc = db["hotlist_jev_trend_recheck_pilot"].find_one({"code": "600000"})
    assert doc["questionSetVersion"] == "v2" and doc["ammoVersion"] == TREND_AMMO_VERSION
    stats2 = runner.run_trend_day(db, [DATE], fire=True)
    assert len(calls) == 40 and stats2["skip"] == 20


def test_fire_insufficient_leaves_trace_without_call(monkeypatch):
    """预检不足：不调用，落留痕文档（riskFlag + status=data_insufficient）。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_with_slots({"09:30": [_row("600001", 3, 1.0, "09:30")],
                         "15:00": [_row("600001", 3, 1.0, "15:00")]})  # 仅 2 次出现 <22 但 ≥2 → fallback 模式
    # 2 次出现是 fallback 模式（partial）而非 insufficient；这里改用单次出现验证留痕
    db = _db_with_slots({"15:00": [_row("600001", 3, 1.0, "15:00")]})
    stats = runner.run_trend_day(db, [DATE], fire=True)
    assert calls == []
    assert stats["data_insufficient"] == 1 and stats["ok"] == 0
    doc = db["hotlist_jev_trend_recheck_pilot"].find_one({"_id": f"{DATE}:15:00:600001:THD"})
    assert doc["status"] == "data_insufficient" and doc["answers"] is None
    assert doc["riskFlag"]["level"] == "data_insufficient"


# ── 台账 ──

def _seed_ledger_db() -> _Db:
    docs = [
        {"_id": f"{DATE}:15:00:600000:THD", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600000", "status": "ok", "mode": "series",
         "trendDirection": "buy", "trendScore": 71.0,
         "engineDirection": "buy", "engineScore": 80.0},
        {"_id": f"{DATE}:15:00:600001:THD", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600001", "status": "ok", "mode": "fallback",
         "trendDirection": "sell", "trendScore": 30.0,
         "engineDirection": "hold", "engineScore": 40.0},
        {"_id": f"{DATE}:15:00:600002:THD", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600002", "status": "ok", "mode": "series",
         "trendDirection": "hold", "trendScore": 50.0, "engineDirection": None},
        {"_id": f"{DATE}:15:00:600003:THD", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600003", "status": "ok", "mode": "fallback",
         "trendDirection": "insufficient", "trendScore": 0.0,
         "engineDirection": "sell", "engineScore": 10.0},
    ]
    return _Db({"hotlist_jev_trend_recheck_pilot": _Col(docs)})


def test_ledger_counts_agree_diverge_and_missing_anchor():
    out = runner.build_ledger(_seed_ledger_db())
    s = out["summary"]
    assert s["dirAgree"] == 1 and s["dirDiverge"] == 1
    assert s["dirAgreeRate"] == 50.0
    assert s["missingAnchor"] == 1 and s["jevInsufficient"] == 1
    # 分模式口径（series/fallback 分开披露，不混桶）
    assert s["byMode"] == {"fallback:diverge": 1, "series:agree": 1}
    assert out["days"] == [{"date": DATE, "agree": 1, "diverge": 1}]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
