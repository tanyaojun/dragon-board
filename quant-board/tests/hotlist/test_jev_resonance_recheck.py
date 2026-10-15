# -*- coding: utf-8 -*-
"""共振维独立判读测试（题集合同=docs/hotlist-jev/jev-resonance-recheck-preregistration.md）。

全 fake 零 IO，禁触真实 jev 调用与网络（AGENTS.md §1.2-7）。
覆盖：判据冻结件/独立戳、预检 riskFlag（与引擎 insufficient 同口径）、叙事 fail-visible 与
口径隔离（黑名单零出现）、同源取数（分位序列/市场基准委托引擎同一实现）、runner 落库合同
（全保留+引擎对照锚快照）、dry-run 零调用、done-skip 幂等、data_insufficient 留痕不调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_resonance_recheck as runner
from backend.analysis.hotlist.jev_resonance_ammo import (
    QUESTIONS_RESONANCE_RECHECK,
    QUESTION_SET_VERSION_RESONANCE_RECHECK,
    RESONANCE_AMMO_VERSION,
    RESONANCE_MIN_BARS,
    RESONANCE_MIN_MARKET_SAMPLE,
    build_resonance_narrative,
    resonance_risk_flag,
    short_window_excess,
    strength_band,
)
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank
from backend.analysis.ranktrend.engine.runtime import detect_rank_jumps

DATE = "2026-10-14"
SID = "half_hour:2026-10-14:15:00"


# ── 判据冻结件（改一字=改门，须重走预登记+用户点头）──


def test_criteria_frozen_shape():
    q = QUESTIONS_RESONANCE_RECHECK
    assert set(q) == {"resonance_direction", "resonance_strength"}
    assert q["resonance_direction"]["type"] == "choice"
    assert set(q["resonance_direction"]["criteria"]) == {"buy", "sell", "hold", "insufficient"}
    assert q["resonance_strength"]["type"] == "score"
    assert len(q["resonance_strength"]["criteria"]) == 10  # 10 档锚点
    # 口径铁律：buy/sell 只表示注意力相对动能，绝不表示「值不值得买」
    assert "绝不表示「这只票值不值得买」" in q["resonance_direction"]["instructions"]
    assert "只依据所给信息判断，不预测后市" in q["resonance_direction"]["instructions"]
    assert "只依据所给信息判断，不预测后市" in q["resonance_strength"]["instructions"]
    # 版本戳独立（cycle/v4/LC 旧债不重犯）
    # v2 改门钉死：三步走（顺序不可调）+ 阈值门 + 「不得反向制造方向」
    instr = q["resonance_direction"]["instructions"]
    assert "判读必须按下面三步走" in instr
    assert "X ≥ +5" in instr and "X ≤ −5" in instr and "|X| < 5" in instr
    assert "不得自行改算" in instr and "不得只看绝对升降而忘记减基准" in instr
    assert "不得把方向改成 sell，除非 X ≤ −5 或末项附近有 collapse 跳变" in instr
    assert "只把 buy 降为 hold" in instr and "不得反向制造方向" in instr  # 单行不断行（防误加换行）
    assert "**仅凭反转惩罚/持续性差/绝对下跌不得判 sell**" in q["resonance_direction"]["criteria"]["sell"]
    assert "强度不得与第一步的方向互相矛盾" in q["resonance_strength"]["instructions"]
    assert QUESTION_SET_VERSION_RESONANCE_RECHECK == "v2"
    assert RESONANCE_AMMO_VERSION.startswith("2026-10-14")


def test_narrative_carries_short_excess_as_step1_input():
    """v2 改门核心：市场基准块首行直接给短窗超额 X（判据第一步输入，USE AS-IS）。"""
    series = ([{"tradingDate": "2026-10-13", "slot": "09:30", "rank": 10, "total": 200,
                "percentile": 50.0, "delta": None}] * 6
              + [{"tradingDate": "2026-10-14", "slot": "13:30", "rank": 10, "total": 200,
                  "percentile": 52.0, "delta": 2.0},
                 {"tradingDate": "2026-10-14", "slot": "14:30", "rank": 10, "total": 200,
                  "percentile": 58.0, "delta": 6.0},
                 {"tradingDate": "2026-10-14", "slot": "15:00", "rank": 10, "total": 200,
                  "percentile": 60.0, "delta": 2.0}])
    text = build_resonance_narrative(
        trading_date=DATE, slot="15:00", code="600001", name="测试股", series=series,
        market={"medianShortChange": -3.0, "sampleCount": 200,
                "medianPercentile": 50.0, "poolSize": 200},
        entry={"isNew": False, "currentPercentile": 60.0},
        jump_events=[], quality={"missingAppearances": [], "missingFields": []})
    # 末项 60 − 倒数第3项 52 = 8；8 − (−3) = 11
    assert "short-window excess X (last-3-appearance change − pool median change): +11.0" in text
    assert "USE AS-IS" in text


def test_narrative_excess_missing_is_fail_visible():
    """基准不可算时超额值如实标「不可算」并指向 insufficient，不伪造 0。"""
    series = [{"tradingDate": "2026-10-14", "slot": "15:00", "rank": 1, "total": 10,
               "percentile": 95.0, "delta": None}]
    text = build_resonance_narrative(
        trading_date=DATE, slot="15:00", code="600001", name="x", series=series,
        market=None, entry={"isNew": True, "currentPercentile": 95.0},
        jump_events=None, quality={"missingAppearances": [], "missingFields": []})
    assert "不可算（序列 <9 次出现或基准缺失），方向题选 insufficient" in text


def test_short_window_excess_pure_function():
    """超额 = 末项分位 − 倒数第3项分位 − 基准（可复现算术衍生；不可算 → None 不猜）。

    注：序列需 ≥9 次出现（引擎预检同口径），故用例都补足长度。
    """
    def _s(*pcts):
        return [{"percentile": p} for p in pcts]
    m = {"medianShortChange": -3.0}
    assert short_window_excess(_s(*([50.0] * 6 + [52.0, 58.0, 60.0])), m) == 11.0   # 8 − (−3)
    assert short_window_excess(_s(*([50.0] * 6 + [40.0, 30.0, 20.0])), m) == -17.0  # 20−40=−20；−20−(−3)
    assert short_window_excess(_s(*([50.0] * 9)), m) == 3.0                         # 0 − (−3)
    # 序列 <9 次出现 → None（引擎同口径不判）
    assert short_window_excess(_s(50.0, 52.0, 58.0, 60.0), m) is None
    # 基准缺失/NaN → None
    assert short_window_excess(_s(*([50.0] * 9)), None) is None
    assert short_window_excess(_s(*([50.0] * 9)), {"medianShortChange": float("nan")}) is None


def test_precheck_thresholds_are_engine_single_source():
    """预检线必须等于引擎 config（单一事实源；引擎改值本层自动跟随）。"""
    c = RankTrendConfig()
    assert RESONANCE_MIN_BARS == c.resonanceMidWindowBars + 1
    assert RESONANCE_MIN_MARKET_SAMPLE == c.resonanceMinMarketSampleCount


def test_risk_flag_levels():
    assert resonance_risk_flag(10, 244) == {"level": "ok", "reasons": []}
    assert resonance_risk_flag(10, 244, missing_slots=2)["level"] == "partial"
    # 与引擎 insufficient 三条件同口径：序列不足 / 横截面样本不足 / 时间轴不完整
    for bars, sample, valid in ((5, 244, True), (10, 19, True), (10, 244, False)):
        rf = resonance_risk_flag(bars, sample, timeline_valid=valid)
        assert rf["level"] == "data_insufficient" and rf["reasons"]


def test_strength_band_matches_engine_label_thresholds():
    assert strength_band(90) == "非常强" and strength_band(85) == "非常强"
    assert strength_band(70) == "强" and strength_band(67) == "强"
    assert strength_band(55) == "中等" and strength_band(50) == "中等"
    assert strength_band(30) == "较弱" and strength_band(27) == "较弱"
    assert strength_band(5) == "非常弱"
    assert strength_band(None) is None and strength_band(float("nan")) is None


# ── 叙事：fail-visible + 口径隔离（黑名单零出现）──

_BLACKLIST = ("signalTier", "synergy", "finalSignal", "compScore", "compRank",
              "lifecycle", "cooling", "ignition", "voteDirection", "temperature",
              "crowding", "量比", "主力净额", "涨停", "跌停")


def test_narrative_fail_visible_and_scope_isolation():
    text = build_resonance_narrative(
        trading_date=DATE, slot="15:00", code="600001", name="测试股",
        series=[{"tradingDate": "2026-10-13", "slot": "15:00", "rank": 10, "total": 240,
                 "percentile": 96.3, "delta": None},
                {"tradingDate": "2026-10-14", "slot": "09:30", "rank": 12, "total": 240,
                 "percentile": 95.1, "delta": -1.2},
                {"tradingDate": "2026-10-14", "slot": "15:00", "rank": None, "total": None,
                 "percentile": None, "delta": None}],
        market={"medianShortChange": -2.5, "sampleCount": 244,
                "medianPercentile": 50.0, "poolSize": 244},
        entry={"isNew": False, "currentPercentile": 95.1},
        jump_events=[{"index": 1, "direction": "surge", "magnitude": 12.4}],
        quality={"missingAppearances": [], "missingFields": []})
    # 可数原料全呈现（跨日出现序列：每行带日期，末项=判读帧）
    assert "2026-10-13 15:00: pct 96.3" in text and "(rank 10/240" in text
    assert "2026-10-14 09:30: pct 95.1" in text and "Δ-1.2" in text
    assert "valid sample 244" in text and "pool size: 244" in text
    assert "pool median attention percentile change: -2.5" in text
    assert "surge@2026-10-14 09:30(+12.4pt)" in text
    assert "history depth: 2 appearances" in text
    # fail-visible：无效出现如实标缺，不插值不伪造 0
    assert "2026-10-14 15:00: 缺（该次无有效出现，fail-visible）" in text
    # 口径隔离：注意力维度专用语料，黑名单判定产物零出现
    for word in _BLACKLIST:
        assert word not in text, word


def test_narrative_market_baseline_missing_is_fail_visible():
    text = build_resonance_narrative(
        trading_date=DATE, slot="11:00", code="600002", name="",
        series=[{"tradingDate": "2026-10-14", "slot": "09:30", "rank": 5, "total": 100,
                 "percentile": 96.0, "delta": None}],
        market=None, entry={"isNew": True, "currentPercentile": 96.0},
        jump_events=None, quality={"missingAppearances": [], "missingFields": ["avgRankNum"]})
    assert "缺（窗口不足 4 帧或公共样本" in text
    assert "jump marks: none（<3 次出现不检测，fail-visible）" in text
    assert "first appearance in series (new entry): yes" in text
    assert "missing fields: ['avgRankNum']" in text


# ── fake db（等值匹配 + Python 过滤；不用操作符查询）──


class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.replaced: list[dict] = []

    @staticmethod
    def _match(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in (query or {}).items())

    def find(self, query=None, projection=None):
        return [d for d in self.docs if self._match(d, query or {})]

    def find_one(self, query=None, projection=None):
        for d in self.docs:
            if self._match(d, query or {}):
                return d
        return None

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append(doc)
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs[i] = doc
                return
        self.docs.append(doc)


class _Db:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.setdefault(name, _Col([]))


def _row(code, rank, avg, slot, **kw):
    d = {"datasetId": "dragonboard_live", "snapshotId": f"half_hour:{DATE}:{slot}",
         "code": code, "name": f"股{code}", "rank": rank, "avgRankNum": avg}
    d.update(kw)
    return d


def _db_with_slots(slot_rows: dict[str, list[dict]], engine: dict | None = None,
                    engine_map: dict[str, dict] | None = None):
    """slot_rows: {slot: [row,...]}（当日 half_hour 帧，按槽升序由 runner 自己排序）。

    engine/engine_map: 同帧 snapshot_analysis 的引擎共振读数（对照锚快照；engine=按 code 复用同一份）。
    """
    frames, rows = [], []
    for slot, slot_rows_list in slot_rows.items():
        sid = f"half_hour:{DATE}:{slot}"
        frames.append({"datasetId": "dragonboard_live", "type": "half_hour",
                       "tradingDate": DATE, "slotTime": slot, "snapshotId": sid})
        rows.extend(slot_rows_list)
    anas = []
    for code, res in (engine_map or ({} if engine is None else {"600000": engine})).items():
        anas.append({"datasetId": "dragonboard_live", "snapshotId": SID,
                     "code": code, "analysis": {"resonance": res}})
    return _Db({"snapshot_frames": _Col(frames), "snapshot_stock_rows": _Col(rows),
                "snapshot_analysis": _Col(anas)})


SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]


def _ten_slots(codes_ranks: dict[str, list[tuple[int, float]]]) -> dict[str, list[dict]]:
    """十槽骨架：codes_ranks={code: [(rank, avgRankNum) × 10]}，按 09:30..15:00 十槽展开。"""
    out: dict[str, list[dict]] = {s: [] for s in SLOTS}
    for code, seq in codes_ranks.items():
        for slot, (rank, avg) in zip(SLOTS, seq):
            out[slot].append(_row(code, rank, avg, slot))
    return out


def _pool(n: int = 24) -> dict[str, list[tuple[int, float]]]:
    """n 只稳定在榜股（rank/avgRankNum 逐槽不变 → 分位恒定、市场基准=0、公共样本=n ≥20）。"""
    return {f"6{i:05d}": [(i + 1, float(i + 1))] * 10 for i in range(n)}


# ── 同源取数（分位序列/市场基准=引擎同一实现）──


def test_population_series_is_engine_same_source():
    """runner 现算的分位序列必须逐位等于引擎算法（attention_rank_lookup + percentile_rank）。"""
    codes = _pool(24)
    db = _db_with_slots(_ten_slots(codes))
    pop = runner.build_population(db, DATE)
    assert pop["meta"]["poolSize"] == 24
    # 市场基准可算（公共样本 24 ≥20）→ 非 insufficient 人口
    assert pop["meta"]["marketSampleCount"] == 24
    assert pop["candidates"] and not pop["insufficient"]
    c1 = next(c for c in pop["candidates"] if c["code"] == "600000")
    expect = [percentile_rank(1, 24)] * 10  # ((24-1+1)/24)*100 = 100
    assert [s["percentile"] for s in c1["series"]] == expect
    assert c1["bars"] == 10 and c1["market"]["sampleCount"] == 24
    assert c1["riskFlag"]["level"] == "ok"
    # 引擎同一函数对同一序列给出同一跳变判定
    assert detect_rank_jumps(expect)["event"] == "none"
    # attention_rank_lookup 重排口径：avgRankNum 升序
    ranks, total = attention_rank_lookup(
        [{"code": "600002", "avgRankNum": 2.0}, {"code": "600001", "avgRankNum": 1.0}])
    assert ranks == {"600001": 1, "600002": 2} and total == 2


def test_population_market_baseline_missing_when_pool_too_small():
    """公共样本 <20 → 市场基准不可算（fail-visible）→ 全池 data_insufficient 不调用。"""
    codes = {"600001": [(3, 1.0)] * 10, "600002": [(5, 2.0)] * 10, "600003": [(9, 3.0)] * 10}
    pop = runner.build_population(_db_with_slots(_ten_slots(codes)), DATE)
    assert pop["meta"]["marketSampleCount"] == 3
    assert pop["candidates"] == [] and len(pop["insufficient"]) == 3
    assert pop["insufficient"][0]["riskFlag"]["level"] == "data_insufficient"
    assert pop["insufficient"][0]["market"] is None


def _db_across_days(days: dict[str, dict[str, list[dict]]]) -> _Db:
    """多日帧骨架：days={tradingDate: {slot: [row,...]}}（行的 snapshotId 按所属帧重写）。"""
    frames, rows = [], []
    for d, per_slot in days.items():
        for slot, slot_rows in per_slot.items():
            sid = f"half_hour:{d}:{slot}"
            frames.append({"datasetId": "dragonboard_live", "type": "half_hour",
                           "tradingDate": d, "slotTime": slot, "snapshotId": sid})
            for r in slot_rows:
                r["snapshotId"] = sid
            rows.extend(slot_rows)
    return _Db({"snapshot_frames": _Col(frames), "snapshot_stock_rows": _Col(rows),
                "snapshot_analysis": _Col([])})


def test_population_series_is_cross_day_appearance_prefix():
    """同源关键：序列=跨日「最近 ≤50 次进榜出现」的前缀（引擎 _build_code_attention_series 口径），
    不是「当日 10 槽」；未进榜的槽不插值。"""
    day1 = _ten_slots(_pool(24))
    day2 = _ten_slots(_pool(24))
    for s in SLOTS:
        day2[s] = [r for r in day2[s] if r["code"] != "600001"]
        if s in ("09:30", "10:00", "15:00"):
            day2[s].append(_row("600001", 2, 2.0, s))
    db = _db_across_days({"2026-10-13": day1, "2026-10-14": day2})
    pop = runner.build_population(db, DATE, slot="15:00")
    assert pop["meta"]["frameWindow"] == 20
    c0 = next(c for c in pop["candidates"] if c["code"] == "600000")
    assert c0["bars"] == 20
    assert [s["tradingDate"] for s in c0["series"]][:10] == ["2026-10-13"] * 10
    assert c0["series"][-1]["slot"] == "15:00" and c0["series"][-1]["tradingDate"] == DATE
    c1 = next(c for c in pop["candidates"] if c["code"] == "600001")
    assert c1["bars"] == 13  # 10 + 3 次出现，缺槽不插值
    assert [s["slot"] for s in c1["series"]][-3:] == ["09:30", "10:00", "15:00"]


def test_population_series_capped_at_50_appearances():
    """序列上限 50 次出现（引擎 SERIES max_bars）：跨 6 日全勤 → 只保留最近 50 次。"""
    days = {d: _ten_slots(_pool(24)) for d in
            ("2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13", "2026-10-14")}
    db = _db_across_days(days)
    pop = runner.build_population(db, DATE, slot="15:00")
    assert pop["meta"]["frameWindow"] == 60
    c0 = next(c for c in pop["candidates"] if c["code"] == "600000")
    assert c0["bars"] == 50 and c0["series"][0]["tradingDate"] == "2026-10-08"


def test_population_no_attention_series_is_traced_not_silently_dropped():
    """判读帧在榜但无 attention 序列（avgRankNum 缺失）→ 显式留痕，不静默消失（§4.0）。"""
    rows = [_row("600000", 1, 1.0, "15:00"), _row("600009", 9, None, "15:00")]
    for s in SLOTS[:-1]:
        rows.append(_row("600000", 1, 1.0, s))
    db = _db_with_slots({"15:00": rows})
    pop = runner.build_population(db, DATE, slot="15:00")
    traced = [c for c in pop["insufficient"] if c["code"] == "600009"]
    assert traced and traced[0]["riskFlag"]["reasons"] == [
        "无 attention 序列（avgRankNum 缺失，引擎同口径跳过）"]


def test_population_partial_when_appearances_few():
    """出现次数不足（午后新进榜）→ data_insufficient 不调用；序列不插值。"""
    slots = _ten_slots(_pool(24))
    for s in SLOTS[:-1]:
        slots[s] = [r for r in slots[s] if r["code"] != "600000"]
    pop = runner.build_population(_db_with_slots(slots), DATE)
    c = next(c for c in pop["insufficient"] if c["code"] == "600000")
    assert c["bars"] == 1 and c["series"][0]["slot"] == "15:00"
    assert c["riskFlag"]["reasons"][0].startswith("序列出现次数=1(<9)")


def test_population_no_frame_is_fail_visible():
    pop = runner.build_population(_Db({}), DATE)
    assert pop["candidates"] == [] and pop["meta"]["error"] == "no_frame"


# ── runner：dry-run 零调用 / 落库合同 / 幂等 / 留痕 �─


def _fake_dispatch(calls):
    def _dispatch(state, questions):
        calls.append((state, questions))
        return {"success": True, "result": {"state": "Completed", "result": {
            "model": "typesafe/jev",
            "answers": {
                "resonance_direction": {"type": "choice", "choice": "buy", "confidence": 0.62,
                                        "probabilities": {"buy": 0.62, "sell": 0.1,
                                                          "hold": 0.26, "insufficient": 0.02}},
                "resonance_strength": {"type": "score", "score": 71, "confidence": 0.55}},
            "usage": {"input_tokens": 900, "output_tokens": 70}}}}, 88
    return _dispatch


def test_dry_run_zero_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    codes = {"600001": [(3, 1.0)] * 10, "600002": [(5, 2.0)] * 10}
    stats = runner.run_resonance_day(_db_with_slots(_ten_slots(codes)), [DATE], fire=False)
    assert calls == [] and stats["tokens"] == 0
    assert stats["ok"] == 0


def test_fire_persist_contract_and_engine_anchor(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_with_slots(_ten_slots(_pool(24)),
                        engine={"status": "ok", "direction": "hold", "score": 12.5,
                                "label": "非常弱", "signalTier": "C"})
    stats = runner.run_resonance_day(db, [DATE], fire=True)
    assert len(calls) == 24 and calls[0][1] == QUESTIONS_RESONANCE_RECHECK
    assert stats["ok"] == 24 and stats["tokens"] == 24 * 970
    col = db["hotlist_jev_resonance_recheck_pilot"]
    doc = col.find_one({"_id": f"{DATE}:15:00:600000:RES"})
    # 判读结果升顶层 + answers 原样包 + 完整 envelope（全保留合同）
    assert doc["resonanceDirection"] == "buy" and doc["resonanceConfidence"] == 0.62
    assert doc["resonanceScore"] == 71 and doc["resonanceProbabilities"]["buy"] == 0.62
    assert doc["answers"]["resonance_direction"]["choice"] == "buy"
    assert doc["responseRaw"]["result"]["state"] == "Completed"
    assert doc["questionSetVersion"] == "v2" and doc["ammoVersion"] == RESONANCE_AMMO_VERSION
    # v2 起落档短窗超额（判据第一步输入）：事后可机械核对「模型方向 vs 超额符号」
    assert "shortExcess" in doc and doc["shortExcess"] is not None
    # 引擎对照锚快照（同帧同股，台账机械可算）
    assert doc["engineDirection"] == "hold" and doc["engineTier"] == "C"
    assert doc["engineScore"] == 12.5 and doc["engineStatus"] == "ok"


def test_fire_is_idempotent_done_skip(monkeypatch):
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_with_slots(_ten_slots(_pool(20)))
    runner.run_resonance_day(db, [DATE], fire=True)
    assert len(calls) == 20
    stats = runner.run_resonance_day(db, [DATE], fire=True)  # 重跑：同代际 ok 文档跳过，零重复调用
    assert len(calls) == 20 and stats["skip"] == 20 and stats["tokens"] == 0


def test_fire_reruns_when_question_set_generation_changes(monkeypatch):
    """代际升级（改门）必须重跑：done-skip 按题集代际，旧代际 ok 文档不挡新代际；
    同 _id 整档覆盖（单一事实源，不留双轨）。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_with_slots(_ten_slots(_pool(20)))
    # 第一遍用「旧代际 v1」跑（monkeypatch 模块级常量）
    monkeypatch.setattr(runner, "QUESTION_SET_VERSION_RESONANCE_RECHECK", "v1")
    runner.run_resonance_day(db, [DATE], fire=True)
    assert len(calls) == 20
    assert db["hotlist_jev_resonance_recheck_pilot"].find_one({"code": "600000"})["questionSetVersion"] == "v1"
    # 第二遍回到当前代际 v2：旧代际文档不跳过 → 重跑并覆盖
    monkeypatch.setattr(runner, "QUESTION_SET_VERSION_RESONANCE_RECHECK", "v2")
    stats = runner.run_resonance_day(db, [DATE], fire=True)
    assert len(calls) == 40 and stats["skip"] == 0 and stats["ok"] == 20
    doc = db["hotlist_jev_resonance_recheck_pilot"].find_one({"code": "600000"})
    assert doc["questionSetVersion"] == "v2" and doc["ammoVersion"] == RESONANCE_AMMO_VERSION
    # 同代际再跑仍幂等
    stats2 = runner.run_resonance_day(db, [DATE], fire=True)
    assert len(calls) == 40 and stats2["skip"] == 20


def test_fire_insufficient_leaves_trace_without_call(monkeypatch):
    """预检不足：不调用，落留痕文档（riskFlag + status=data_insufficient）。"""
    calls: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch(calls))
    db = _db_with_slots({"09:30": [_row("600001", 3, 1.0, "09:30")],
                         "15:00": [_row("600001", 3, 1.0, "15:00")]})  # 仅 2 次出现 <9
    stats = runner.run_resonance_day(db, [DATE], fire=True)
    assert calls == []
    assert stats["data_insufficient"] == 1 and stats["ok"] == 0
    doc = db["hotlist_jev_resonance_recheck_pilot"].find_one(
        {"_id": f"{DATE}:15:00:600001:RES"})
    assert doc["status"] == "data_insufficient" and doc["answers"] is None
    assert doc["riskFlag"]["level"] == "data_insufficient"


def test_ledger_counts_agree_diverge_and_missing_anchor(monkeypatch):
    monkeypatch.setattr(runner, "_dispatch_jev", _fake_dispatch([]))
    db = _db_with_slots(_ten_slots(_pool(24)), engine_map={
        "600000": {"status": "ok", "direction": "hold", "score": 12.5,
                   "label": "非常弱", "signalTier": "C"},
        "600001": {"status": "ok", "direction": "buy", "score": 71.0,
                   "label": "强", "signalTier": "A"}})
    runner.run_resonance_day(db, [DATE], fire=True)
    ledger = runner.build_ledger(db)
    s = ledger["summary"]
    # jev 全判 buy：600000 引擎 hold → diverge；600001 引擎 buy → agree；其余 22 只无锚
    assert s["dirAgree"] == 1 and s["dirDiverge"] == 1
    assert s["missingAnchor"] == 22
    assert s["dirAgreeRate"] == 50.0
    # 强度分桶：jev score=71 → 强；600001 引擎 71 → 强（agree），600000 引擎 12.5 → 非常弱（diverge）
    assert s["bandAgree"] == 1 and s["bandDiverge"] == 1
    assert ledger["days"] == [{"date": DATE, "agree": 1, "diverge": 1}]
