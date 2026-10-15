# -*- coding: utf-8 -*-
"""热度维+量价维独立判读（题集 v2 逻辑推理试点）测试。全 fake db，零 IO 零 jev 调用（AGENTS §1.2-7）。

V2（用户裁决 2026-10-15）：题集主体由「查表复现」升版为「逻辑推理」——每题答案必须能从
同一输入机械复算出锚（ammo 的 *_anchor() 纯函数），jev 判对=推理成功、判错=推理失败；
v1 复现题（tier/quadrant）原样保留为协议层阴性对照基线。
"""
from __future__ import annotations

import pytest

from backend.analysis.hotlist.jev_heat_volume_ammo import (
    HEAT_AMMO_VERSION,
    HEAT_ATTRIBUTIONS,
    HEAT_EVOLUTIONS,
    QUESTIONS_HEAT_RECHECK,
    QUESTIONS_VOLUME_RECHECK,
    QUESTION_SET_VERSION_HEAT_RECHECK,
    QUESTION_SET_VERSION_VOLUME_RECHECK,
    VOLUME_AMMO_VERSION,
    VOLUME_CAUSES,
    VOLUME_TRADABILITY,
    build_heat_narrative,
    build_volume_narrative,
    heat_attribution_anchor,
    heat_derived,
    heat_evolution_anchor,
    heat_risk_flag,
    volume_cause_anchor,
    volume_derived,
    volume_risk_flag,
    volume_tradability_anchor,
)
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import (
    _is_limit_down,
    _is_limit_up,
)
from backend.analysis.ranktrend.trend.cross_section import compute_cross_section
from backend.operations import jev_heat_volume_recheck as runner

DATE = "2026-10-14"
SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30",
         "13:00", "13:30", "14:00", "14:30", "15:00"]
DATASET = "dragonboard_live"

# 黑名单：判定产物/他维读数一律不进叙事（机验）
_BLACKLIST = ("signalTier", "synergy", "finalSignal", "compScore", "compRank",
              "lifecycle", "cooling", "ignition", "voteDirection", "temperature",
              "crowding", "量比结论", "resonance_direction", "trendDirection",
              # V2：逻辑题的答案与锚一律不进叙事（判定产物黑名单）
              "individual_strong", "market_wide_rise", "igniting", "fading",
              "volume_expansion_up", "limit_up_blocked", "over_volume_exhaustion")


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
    return [_row(f"600{i:03d}", i + 1, avg_base - i * 0.01, "15:00", date=date)
            for i in range(n)]


def _ten_slots(rows, date=DATE):
    out = {}
    for slot in SLOTS:
        out[slot] = [dict(r, slotTime=slot, snapshotId=f"half_hour:{date}:{slot}")
                     for r in rows]
    return out


def _db_across_days(days: dict[str, dict[str, list[dict]]]) -> _Db:
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


def _fake_dispatch(calls: list, heat_attr="follow_market", heat_evol="sustaining",
                   heat_dir="hold", heat_tier="C", vol_cause="neutral",
                   vol_trad="tradable", vol_dir="hold", vol_tier="D",
                   vol_quad="fall_shrink", conf=0.6):
    def _dispatch(state, questions):
        calls.append((state, questions))
        if questions is QUESTIONS_HEAT_RECHECK:
            answers = {
                "heat_attribution": {"type": "choice", "choice": heat_attr,
                                     "confidence": conf, "probabilities": {heat_attr: conf}},
                "heat_evolution": {"type": "choice", "choice": heat_evol,
                                   "confidence": conf, "probabilities": {heat_evol: conf}},
                "heat_direction": {"type": "choice", "choice": heat_dir,
                                   "confidence": conf, "probabilities": {heat_dir: conf}},
                "heat_tier": {"type": "choice", "choice": heat_tier,
                              "confidence": conf, "probabilities": {heat_tier: conf}}}
        else:
            answers = {
                "volume_cause": {"type": "choice", "choice": vol_cause,
                                 "confidence": conf, "probabilities": {vol_cause: conf}},
                "volume_tradability": {"type": "choice", "choice": vol_trad,
                                       "confidence": conf, "probabilities": {vol_trad: conf}},
                "volume_direction": {"type": "choice", "choice": vol_dir,
                                     "confidence": conf, "probabilities": {vol_dir: conf}},
                "volume_tier": {"type": "choice", "choice": vol_tier,
                                "confidence": conf, "probabilities": {vol_tier: conf}},
                "volume_quadrant": {"type": "choice", "choice": vol_quad,
                                    "confidence": conf, "probabilities": {vol_quad: conf}}}
        return {"success": True, "result": {"state": "Completed", "result": {
            "model": "typesafe/jev", "answers": answers,
            "usage": {"input_tokens": 700, "output_tokens": 50}}}}, 66
    return _dispatch


# ── 判据冻结件形状 ──

def test_criteria_frozen_shape():
    """判据形状钉死（V2 逻辑推理题；逐字=代码文本，改一字=改门）。

    热度=2 逻辑主问 + 1 语义问 + 1 复现基线；量价=2 逻辑主问 + 1 语义问 + 2 复现基线。
    逻辑题必须声明「不是查表题/没有给门槛表」+ 显式推理步骤；复现基线必须保留显式门槛表。
    """
    assert set(QUESTIONS_HEAT_RECHECK) == {"heat_attribution", "heat_evolution",
                                           "heat_direction", "heat_tier"}
    assert set(QUESTIONS_VOLUME_RECHECK) == {"volume_cause", "volume_tradability",
                                             "volume_direction", "volume_tier",
                                             "volume_quadrant"}
    for q in QUESTIONS_HEAT_RECHECK.values():
        assert set(q) == {"type", "instructions", "criteria"}
        assert "只依据所给信息判断，不预测后市" in q["instructions"]
    # 逻辑主问：必须显式声明「不是查表题、没有给门槛表」+ 三步走 + 阈值门数值
    for key, dim in (("heat_attribution", "HEAT"), ("heat_evolution", "HEAT"),
                     ("volume_cause", "VOL"), ("volume_tradability", "VOL")):
        instr = (QUESTIONS_HEAT_RECHECK if dim == "HEAT" else QUESTIONS_VOLUME_RECHECK)[key]["instructions"]
        assert "不是查表题" in instr and "没有给门槛表" in instr, key
        assert "逻辑推理题" in instr, key
    # 热度归因：三步走 + 相对门 15 + 绝对门 50 + 分母效应问题陈述
    ha = QUESTIONS_HEAT_RECHECK["heat_attribution"]["instructions"]
    assert "三步走" in ha and "15" in ha and "50" in ha
    assert "分母效应" in ha
    assert "个体与市场不可分" in ha
    # 热度演化：只用末 3 次 + 不足 3 次 → insufficient
    he = QUESTIONS_HEAT_RECHECK["heat_evolution"]["instructions"]
    assert "末 3 次有效出现" in he and "不足 3 次" in he
    # 量价归因：优先级链（硬风险 > 资金流出 > 四象限 > 中态）+ 涨幅不影响归因
    vc = QUESTIONS_VOLUME_RECHECK["volume_cause"]["instructions"]
    assert "优先于其余一切选项" in vc and "先于四象限" in vc
    assert "不影响归因" in vc
    # 量价可交易性：封板优先于资金异常（一字板≠tradable）
    vt = QUESTIONS_VOLUME_RECHECK["volume_tradability"]["instructions"]
    assert "封板优先于资金异常" in vt and "limit_up_blocked" in vt
    # 复现基线保留显式门槛表（防模型自创阈值）
    assert "显式门槛表" in QUESTIONS_HEAT_RECHECK["heat_tier"]["instructions"]
    assert "显式门槛表" in QUESTIONS_VOLUME_RECHECK["volume_tier"]["instructions"]
    assert "显式规则" in QUESTIONS_VOLUME_RECHECK["volume_quadrant"]["instructions"]
    # 量价档位与涨幅绝对大小无关（引擎同口径）
    assert "不影响档位" in QUESTIONS_VOLUME_RECHECK["volume_tier"]["instructions"]
    # 热度 A 档必须成对条件
    assert "必须成对出现才升级/降级" in QUESTIONS_HEAT_RECHECK["heat_tier"]["instructions"]
    # 语义题必须带口径铁律（绝不表示可买入性）+ 两步走 + 证据冲突=hold + 无引擎锚声明
    assert "绝不表示" in QUESTIONS_HEAT_RECHECK["heat_direction"]["instructions"]
    assert "绝不表示" in QUESTIONS_VOLUME_RECHECK["volume_direction"]["instructions"]
    assert "两步走" in QUESTIONS_HEAT_RECHECK["heat_direction"]["instructions"]
    assert "证据冲突=hold" in QUESTIONS_HEAT_RECHECK["heat_direction"]["instructions"]
    assert "没有引擎对照锚" in QUESTIONS_VOLUME_RECHECK["volume_direction"]["instructions"]
    # V2 删除项：volume_score 复现题不得复活（纯算术查表、jev 无优势）
    assert "volume_score" not in QUESTIONS_VOLUME_RECHECK


def test_logic_question_anchors_are_reproducible():
    """逻辑题锚复算（纯函数）：三步走/阈值门/按序短路全部可机验，缺项 → insufficient。"""
    # 热度归因：四象限 + 中带 + 缺项
    assert heat_attribution_anchor(72, 22) == "individual_strong"
    assert heat_attribution_anchor(30, 20) == "market_wide_rise"
    assert heat_attribution_anchor(30, -20) == "individual_weak"
    assert heat_attribution_anchor(72, -20) == "market_wide_fall"
    assert heat_attribution_anchor(50, 3) == "follow_market"      # |rel|<15 不硬拆
    assert heat_attribution_anchor(49.9, 14.9) == "follow_market"  # 边界：双门都不过
    assert heat_attribution_anchor(None, 1) == "insufficient"
    assert heat_attribution_anchor(50, None) == "insufficient"
    # 热度演化：形态五分类 + 短序列 insufficient；volatile 优先于 fading
    assert heat_evolution_anchor([50, 58, 66]) == "igniting"
    assert heat_evolution_anchor([70, 71, 69]) == "sustaining"
    assert heat_evolution_anchor([70, 62, 54]) == "fading"
    assert heat_evolution_anchor([30, 31, 29]) == "dormant"
    assert heat_evolution_anchor([30, 60, 35]) == "volatile"
    assert heat_evolution_anchor([50, 58]) == "insufficient"
    # 量价归因：优先级链
    assert volume_cause_anchor(2.0, 1.5, 5.0, None) == "volume_expansion_up"
    assert volume_cause_anchor(2.0, 3.0, 5.0, None) == "over_volume_exhaustion"   # 硬风险优先
    assert volume_cause_anchor(1.0, 1.2, 15.0, None) == "over_volume_exhaustion"  # 净占比>+10
    assert volume_cause_anchor(-1.0, 1.2, -8.0, None) == "fund_outflow"           # 先于四象限
    assert volume_cause_anchor(2.0, 0.8, 1.0, None) == "shrink_up"
    assert volume_cause_anchor(-1.0, 0.8, 1.0, None) == "shrink_down"
    assert volume_cause_anchor(-1.0, 1.5, 1.0, None) == "volume_expansion_down"
    assert volume_cause_anchor(0.0, 1.0, 0.0, None) == "neutral"
    assert volume_cause_anchor(None, 1.0, 0.0, None) == "insufficient"
    # 量价可交易性：封板优先于资金异常
    assert volume_tradability_anchor(9.9, 0.5, 1.0, True, False) == "limit_up_blocked"
    assert volume_tradability_anchor(-9.9, 0.5, 1.0, False, True) == "limit_down_blocked"
    assert volume_tradability_anchor(2.0, 1.5, 15.0, False, False) == "abnormal_fund_flow"
    assert volume_tradability_anchor(2.0, 1.5, 1.0, False, False) == "tradable"
    assert volume_tradability_anchor(None, 1.0, 0.0) == "insufficient"


def test_logic_question_anchors_share_thresholds_with_criteria_text():
    """锚与判据文本共用同一组阈值常量（杜绝两套口径）。"""
    assert HEAT_ATTRIBUTIONS[0] == "individual_strong" and HEAT_ATTRIBUTIONS[-1] == "insufficient"
    assert HEAT_EVOLUTIONS[-1] == "insufficient"
    assert VOLUME_CAUSES[0] == "over_volume_exhaustion"      # 优先级链第一档
    assert VOLUME_CAUSES[1] == "fund_outflow"                # 第二档
    assert VOLUME_TRADABILITY[-1] == "insufficient"
    # 判据里写的门（15/50/8/60/40/25/2.5/10/-5/1.05/0.95）必须在指令文本中可机验到
    assert "15" in QUESTIONS_HEAT_RECHECK["heat_attribution"]["instructions"]
    assert "2.5" in QUESTIONS_VOLUME_RECHECK["volume_cause"]["instructions"]
    assert "+10" in QUESTIONS_VOLUME_RECHECK["volume_cause"]["instructions"]
    assert "−5" in QUESTIONS_VOLUME_RECHECK["volume_cause"]["instructions"]


def test_precheck_thresholds_are_engine_single_source():
    """预检线与引擎不可算线同口径：percentile 缺失=unknown；量比≤0/缺失=不评估。"""
    assert heat_risk_flag(None, None)["level"] == "data_insufficient"
    assert heat_risk_flag(80.0, None)["level"] == "partial"   # 首帧缺 delta：绝对档可判
    assert heat_risk_flag(80.0, 2.0)["level"] == "ok"
    assert volume_risk_flag(None, 1.2)["level"] == "data_insufficient"
    assert volume_risk_flag(1.5, None)["level"] == "data_insufficient"
    assert volume_risk_flag(1.5, 0.0)["level"] == "data_insufficient"
    assert volume_risk_flag(1.5, 1.2)["level"] == "ok"


def test_heat_derived_matches_engine_compute_cross_section_inputs():
    """热度衍生输入与引擎 compute_cross_section 的输入逐位一致（percentile/delta/relative）。"""
    cfg = RankTrendConfig()
    pcts = [40.0, 44.0, 47.0, 52.0, 55.0]
    d = heat_derived(pcts, 50.0)
    assert d["percentile"] == 55.0 and d["percentileDelta"] == 3.0
    assert d["relativeToMarket"] == 5.0
    got = compute_cross_section(pcts, 50.0, cfg)
    # 引擎档位由引擎函数算（本题集不第二实现），这里只验证输入衍生正确
    assert got["percentile"] == d["percentile"]
    assert got["percentileDelta"] == d["percentileDelta"]
    assert got["relativeToMarket"] == d["relativeToMarket"]
    assert got["signalTier"] == "C"     # pct≥50 但 delta<+15 不构成 B；pct<70 且 >30 → C 兜底
    assert d["persist"] is None         # crossSectionPersistFrames=0（默认关闭）


def test_heat_derived_fail_visible_when_market_median_missing():
    d = heat_derived([40.0, 44.0], None)
    assert d["relativeToMarket"] is None      # 市场基准缺失 → 如实 None，不伪造 0
    assert d["percentile"] == 44.0


def test_volume_derived_delegates_to_engine_functions():
    """涨跌停/涨幅档位分委托引擎同一函数（零第二实现）。"""
    d = volume_derived("600000", 9.9, 2.4, 5000.0, 3.2)
    assert d["limitUp"] == _is_limit_up("600000", 9.9)
    assert d["limitDown"] == _is_limit_down("600000", 9.9)
    assert d["directionBucket"] == pytest.approx(15.0)   # 涨停档（涨幅 ≥ 涨跌幅上限）
    d2 = volume_derived("600000", None, None, None, None)
    assert d2["directionBucket"] is None and d2["limitUp"] is False


# ── 叙事 ──

def _series(n=30, start=40.0, step=0.5, date=DATE):
    out, prev = [], None
    for i in range(n):
        pct = start + step * i
        out.append({"tradingDate": date if i < 10 else "2026-10-13",
                    "slot": "15:00" if i < 10 else "15:00",
                    "rank": 30 - i, "total": 244, "percentile": pct,
                    "delta": (pct - prev) if prev is not None else None})
        prev = pct
    return out


def test_heat_narrative_has_five_blocks_and_no_blacklist():
    series = _series(12)
    derived = heat_derived([s["percentile"] for s in series], 50.0)
    text = build_heat_narrative(trading_date=DATE, slot="15:00", code="600000",
                                name="甲", series=series, derived=derived,
                                market={"medianPercentile": 50.0, "sampleCount": 240,
                                        "poolSize": 244},
                                entry={"isNew": False, "currentPercentile": 45.5},
                                quality={"missingAppearances": [], "missingFields": []})
    for marker in ("[Attention Appearance Series", "[Cross-Section Derived",
                   "[Market Baseline", "[Entry]", "[Data Quality"):
        assert marker in text
    assert "percentile (last appearance) = 45.5" in text
    assert "percentileDelta (last − previous appearance) = +0.5" in text
    for bad in _BLACKLIST:
        assert bad not in text, f"黑名单词进入叙事: {bad}"


def test_heat_narrative_fail_visible_when_delta_missing():
    series = _series(1)
    derived = heat_derived([s["percentile"] for s in series], 50.0)
    text = build_heat_narrative(trading_date=DATE, slot="15:00", code="600000",
                                name="甲", series=series, derived=derived,
                                market={"medianPercentile": 50.0, "sampleCount": 240,
                                        "poolSize": 244},
                                entry={"isNew": True, "currentPercentile": 40.0},
                                quality={"missingAppearances": [], "missingFields": ["zljzb"]})
    assert "percentileDelta (last − previous appearance) = 缺" in text
    assert "missing fields: ['zljzb']" in text
    assert "<2 次出现" in text


def test_volume_narrative_has_three_blocks_and_no_amount_ratio():
    derived = volume_derived("600000", 3.5, 1.8, 2000.0, 2.5)
    text = build_volume_narrative(trading_date=DATE, slot="15:00", code="600000",
                                  name="甲", derived=derived,
                                  quality={"missingFields": ["zljzb"]})
    for marker in ("[Judgment Frame Raw Fields", "[Derived", "[Data Quality"):
        assert marker in text
    assert "change (pct) = +3.5%" in text and "volumeRatio = 1.8" in text
    assert "limit up: no" in text
    assert "amountRatio (成交额量比) not provided" in text   # 严格同源：不用引擎未算的字段
    for bad in _BLACKLIST:
        assert bad not in text, f"黑名单词进入叙事: {bad}"


def test_volume_narrative_marks_limit_up_as_untradeable():
    derived = volume_derived("000823", 9.99, 0.6, 412777170.0, 30.0)
    text = build_volume_narrative(trading_date=DATE, slot="15:00", code="000823",
                                  name="乙", derived=derived, quality={"missingFields": []})
    assert "limit up: yes" in text
    assert "封板=不可交易，勿当普通放量" in text


# ── 人口与预检 ──

def test_population_full_pool_and_engine_anchors():
    db = _db_across_days({d: _ten_slots(_pool(24), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    db["snapshot_analysis"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "600000",
         "analysis": {"observation": {
             "crossSection": {"percentile": 55.0, "percentileDelta": 6.0,
                              "relativeToMarket": 5.0, "signalTier": "A",
                              "tierReasons": ["高位 + 热度排名上升"]},
             "volumePrice": {"score": 62, "direction": "up", "quadrant": "rise_volume",
                             "signalTier": "A", "tierReasons": ["放量上涨 + 资金流入"]},
             "amountRatio": None}}}]
    pop = runner.build_population(db, DATE, DATASET, "15:00")
    assert pop["meta"].get("error") is None
    assert len(pop["candidates"]) == 24 and len(pop["insufficient"]) == 0
    c = pop["candidates"][0]
    assert c["engineHeat"]["signalTier"] == "A"
    assert c["engineVolume"]["quadrant"] == "rise_volume"
    assert c["engineVolume"]["amountRatio"] is None
    assert c["riskFlagHeat"]["level"] == "ok"
    assert c["riskFlagVolume"]["level"] == "ok"


def test_population_volume_insufficient_when_volume_ratio_missing():
    rows = _pool(6)
    rows[0]["volumeRatio"] = None
    db = _db_with_slots(_ten_slots(rows))
    pop = runner.build_population(db, DATE, DATASET, "15:00")
    bad = [c for c in pop["candidates"] if c["code"] == "600000"]
    assert bad and bad[0]["riskFlagVolume"]["level"] == "data_insufficient"
    assert "量比缺失" in bad[0]["riskFlagVolume"]["reasons"][0]
    # 热度维仍可判（两维独立预检，不互相牵连）
    assert bad[0]["riskFlagHeat"]["level"] == "ok"


def test_population_no_frame():
    db = _db_with_slots({"09:30": _pool(5)})
    pop = runner.build_population(db, DATE, DATASET, "15:00")
    assert pop["candidates"] == [] and pop["meta"]["error"] == "no_frame"


# ── 运行契约 ──

def test_dry_run_zero_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    stats = runner.run_heat_volume_day(_db_with_slots(_ten_slots(_pool(24))), [DATE],
                                       fire=False)
    assert calls == [] and stats["tokens"] == 0


def test_fire_persists_both_dimensions_with_engine_anchor(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(8), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    db["snapshot_analysis"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "600000",
         "analysis": {"observation": {
             "crossSection": {"percentile": 55.0, "percentileDelta": 6.0,
                              "relativeToMarket": 5.0, "signalTier": "A"},
             "volumePrice": {"score": 62, "direction": "up", "quadrant": "rise_volume",
                             "signalTier": "A"},
             "amountRatio": None}}}]
    stats = runner.run_heat_volume_day(db, [DATE], fire=True)
    assert len(calls) == 16          # 8 只 × 2 维
    assert stats["ok"] == 16 and stats["tokens"] == 16 * 750
    heat = db[runner.HEAT_COLLECTION].find_one({"_id": f"{DATE}:15:00:600000:HEA"})
    # V2 逻辑主问 + 复现基线 + 语义问三类读数全部落档
    assert heat["heatAttribution"] == "follow_market" and heat["heatEvolution"] == "sustaining"
    assert heat["heatTier"] == "C" and heat["heatDirection"] == "hold"
    assert heat["engineTier"] == "A" and heat["enginePercentile"] == 55.0
    assert heat["questionSetVersion"] == QUESTION_SET_VERSION_HEAT_RECHECK
    assert heat["ammoVersion"] == HEAT_AMMO_VERSION
    vol = db[runner.VOLUME_COLLECTION].find_one({"_id": f"{DATE}:15:00:600000:VPQ"})
    assert vol["volumeCause"] == "neutral" and vol["volumeTradability"] == "tradable"
    assert vol["volumeTier"] == "D" and vol["volumeQuadrant"] == "fall_shrink"
    assert vol["volumeDirection"] == "hold"
    assert vol["engineTier"] == "A" and vol["engineQuadrant"] == "rise_volume"
    assert vol["engineScore"] == 62 and vol["engineAmountRatio"] is None
    assert vol["questionSetVersion"] == QUESTION_SET_VERSION_VOLUME_RECHECK
    assert vol["ammoVersion"] == VOLUME_AMMO_VERSION


def test_fire_dim_filter_runs_single_dimension(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(8), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    stats = runner.run_heat_volume_day(db, [DATE], fire=True, dims=("heat",))
    assert len(calls) == 8 and stats["ok"] == 8
    assert db[runner.VOLUME_COLLECTION].find_one({"code": "600000"}) is None


def test_fire_is_idempotent_done_skip(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(6), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    runner.run_heat_volume_day(db, [DATE], fire=True)
    assert len(calls) == 12
    stats = runner.run_heat_volume_day(db, [DATE], fire=True)
    assert len(calls) == 12 and stats["skip"] == 6 and stats["tokens"] == 0


def test_fire_reruns_when_question_set_generation_changes(monkeypatch):
    """代际升级（改门）必须重跑：旧代际 ok 文档不挡新代际；同 _id 整档覆盖。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_across_days({d: _ten_slots(_pool(6), date=d) for d in
                          ("2026-10-10", "2026-10-13", "2026-10-14")})
    runner.run_heat_volume_day(db, [DATE], fire=True)
    assert len(calls) == 12
    monkeypatch.setattr(runner, "QUESTION_SET_VERSION_HEAT_RECHECK", "v9-pretend")
    stats = runner.run_heat_volume_day(db, [DATE], fire=True, dims=("heat",))
    assert len(calls) == 18 and stats["skip"] == 0
    doc = db[runner.HEAT_COLLECTION].find_one({"code": "600000"})
    assert doc["questionSetVersion"] == "v9-pretend"
    stats2 = runner.run_heat_volume_day(db, [DATE], fire=True, dims=("heat",))
    assert len(calls) == 18 and stats2["skip"] == 6


def test_fire_insufficient_leaves_trace_without_call(monkeypatch):
    """预检不足：不调用，落留痕文档（riskFlag + status=data_insufficient）。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    rows = _pool(4)
    for r in rows:
        r["change"] = None
    db = _db_with_slots(_ten_slots(rows))
    stats = runner.run_heat_volume_day(db, [DATE], fire=True, dims=("volume",))
    assert calls == []
    assert stats["data_insufficient"] == 4 and stats["ok"] == 0
    doc = db[runner.VOLUME_COLLECTION].find_one({"_id": f"{DATE}:15:00:600000:VPQ"})
    assert doc["status"] == "data_insufficient" and doc["answers"] is None
    assert doc["riskFlag"]["level"] == "data_insufficient"


# ── 台账 ──

def _seed_ledger_db() -> _Db:
    """三只样本：600000 全对/600001 逻辑题分歧但基线一致/600002 逻辑题 insufficient。"""
    heat = [
        {"_id": f"{DATE}:15:00:600000:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600000", "status": "ok", "heatTier": "A", "heatDirection": "buy",
         "engineTier": "A", "heatAttribution": "individual_strong",
         "attributionAnchor": "individual_strong", "heatEvolution": "igniting",
         "evolutionAnchor": "igniting"},
        {"_id": f"{DATE}:15:00:600001:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600001", "status": "ok", "heatTier": "C", "heatDirection": "hold",
         "engineTier": "B", "heatAttribution": "market_wide_rise",
         "attributionAnchor": "follow_market", "heatEvolution": "dormant",
         "evolutionAnchor": "sustaining"},
        {"_id": f"{DATE}:15:00:600002:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600002", "status": "ok", "heatTier": "hold", "heatDirection": "hold",
         "engineTier": None, "heatAttribution": "insufficient",
         "attributionAnchor": "insufficient", "heatEvolution": "insufficient",
         "evolutionAnchor": "insufficient"},
    ]
    vol = [
        {"_id": f"{DATE}:15:00:600000:VPQ", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600000", "status": "ok", "volumeTier": "A", "volumeQuadrant": "rise_volume",
         "volumeDirection": "buy", "engineTier": "A", "engineQuadrant": "rise_volume",
         "volumeCause": "volume_expansion_up", "causeAnchor": "volume_expansion_up",
         "volumeTradability": "tradable", "tradabilityAnchor": "tradable"},
        {"_id": f"{DATE}:15:00:600001:VPQ", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600001", "status": "ok", "volumeTier": "D", "volumeQuadrant": "fall_shrink",
         "volumeDirection": "sell", "engineTier": "A", "engineQuadrant": "rise_volume",
         "volumeCause": "fund_outflow", "causeAnchor": "shrink_down",
         "volumeTradability": "limit_up_blocked", "tradabilityAnchor": "tradable"},
        {"_id": f"{DATE}:15:00:600002:VPQ", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600002", "status": "ok", "volumeTier": "insufficient",
         "volumeQuadrant": "insufficient", "volumeDirection": "insufficient",
         "engineTier": "D", "engineQuadrant": "fall_shrink",
         "volumeCause": "insufficient", "causeAnchor": "insufficient",
         "volumeTradability": "insufficient", "tradabilityAnchor": "insufficient"},
    ]
    return _Db({runner.HEAT_COLLECTION: _Col(heat), runner.VOLUME_COLLECTION: _Col(vol)})


def test_ledger_counts_logic_questions_against_anchors():
    """V2 台账：逻辑题对复算锚；复现基线对引擎读数；语义题只落分布、不进一致率。"""
    out = runner.build_ledger(_seed_ledger_db())
    s = out["summary"]
    # 逻辑主问（对复算锚）：600000 一致、600001 分歧、600002 insufficient 不计票
    assert s["heatAttributionAgree"] == 1 and s["heatAttributionDiverge"] == 1
    assert s["heatAttributionAgreeRate"] == 50.0
    assert s["heatEvolutionAgree"] == 1 and s["heatEvolutionDiverge"] == 1
    assert s["volumeCauseAgree"] == 1 and s["volumeCauseDiverge"] == 1
    assert s["volumeTradabilityAgree"] == 1 and s["volumeTradabilityDiverge"] == 1
    # 复现基线（对引擎读数）：协议层阴性对照
    assert s["heatTierAgree"] == 1 and s["heatTierDiverge"] == 1
    assert s["heatTierAgreeRate"] == 50.0
    assert s["volumeTierAgree"] == 1 and s["volumeTierDiverge"] == 1
    assert s["volumeQuadrantAgree"] == 1 and s["volumeQuadrantDiverge"] == 1
    # 语义题无锚：只统计分布（600002 三题都 insufficient，仍如实进分布）
    # 语义题无锚：只落分布，insufficient 也如实计数（不静默丢弃）
    assert s["heatDirection"] == {"buy": 1, "hold": 2}
    assert s["volumeDirection"] == {"buy": 1, "sell": 1, "insufficient": 1}
    # insufficient 计数 + 缺锚单列
    assert s["jevInsufficient"] == 2   # 两维各 1 例主问 insufficient（600002）
    # 600002 两题都 insufficient：不重复计入 missingAnchor（insufficient 与缺锚是两件事）
    assert s["missingAnchor"] == 0
    # V2 已删除 volumeBand 指标（score 复现题下线）
    assert "volumeBandAgree" not in s
    # per_day 展开键存在（供前端/复盘按日拆）
    assert out["days"] and out["days"][0]["date"] == DATE
    assert "attrAgree" in out["days"][0] and "causeDiverge" in out["days"][0]


def test_ledger_missing_anchor_is_fail_visible():
    """逻辑题锚缺失（runner 未落 anchor 字段）→ 单列 missingAnchor，不计入分母。"""
    db = _Db({runner.HEAT_COLLECTION: _Col([
        {"_id": f"{DATE}:15:00:600000:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "600000", "status": "ok", "heatAttribution": "individual_strong",
         "heatEvolution": "igniting", "heatDirection": "buy"}])})
    s = runner.build_ledger(db)["summary"]
    assert s["heatAttributionAgree"] == 0 and s["heatAttributionDiverge"] == 0
    assert s["heatEvolutionAgree"] == 0 and s["heatEvolutionDiverge"] == 0
    assert s["missingAnchor"] == 2      # 两题各缺一次锚，如实计数
    assert s["heatDirection"] == {"buy": 1}
