# -*- coding: utf-8 -*-
"""行情列表五维信号 jev 复核双题集测试（预登记 jev-vote-confirm-lifecycle-recheck-preregistration.md）。

全 fake 零 IO，禁触真实 jev 调用与网络（AGENTS.md §1.2-7）。
覆盖：判据冻结件/独立戳、riskFlag 预检、对照锚映射、确定性抽样、EOD 补齐读法、
叙事组装（fail-visible/口径隔离）、人口构建（fake db）、落库合同（全保留裁决 5）、熔断。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_vote_confirm as runner
from backend.analysis.hotlist.jev_driver_ammo import (
    QUESTION_SET_VERSION_CYCLE,
    QUESTION_SET_VERSION_DRIVER,
)
from backend.analysis.hotlist.jev_vote_ammo import (
    QUESTION_SET_VERSION_LIFECYCLE_RECHECK,
    QUESTION_SET_VERSION_VOTE_CONFIRM,
    VOTE_AMMO_VERSION,
    QUESTIONS_LIFECYCLE_RECHECK,
    QUESTIONS_VOTE_CONFIRM,
    build_lifecycle_narrative,
    lifecycle_risk_flag,
    sample_lifecycle,
    synergy_direction,
)

def _traj():
    return [{"slot": "09:30", "rank": 81, "change": -0.72},
            {"slot": "10:00", "rank": None, "change": 1.62},
            {"slot": "10:30", "rank": 92.5, "change": None}]


# ── 判据冻结件（预登记 §二·三/§三·三，逐字=代码文本；改动=改门须重走预登记）──


def test_lifecycle_criteria_frozen_text():
    q = QUESTIONS_LIFECYCLE_RECHECK["lifecycle_stage_recheck"]
    assert set(q["criteria"]) == {"ignition", "expansion", "crowded", "reversal", "cooling"}
    assert "insufficient" not in q["instructions"]
    assert "启动的新鲜度" in q["instructions"]
    assert "回落证据" in q["instructions"]
    assert "只依据所给信息判断，不预测后市" in q["instructions"]
    assert q["criteria"]["ignition"].startswith("点火：排名自低位明显起升")
    assert "高位滞留" in q["criteria"]["crowded"]
    assert "高位回落" in q["criteria"]["reversal"]
    assert q["criteria"]["cooling"].startswith("降温：排名处于中低位且无起升证据")


def test_lifecycle_risk_flag_levels():
    assert lifecycle_risk_flag(10, True, []) == {"level": "ok", "reasons": []}
    assert lifecycle_risk_flag(10, True, ["prev_stage_missing"])["level"] == "partial"
    # 六修：预检线 5→2（上榜晚的股跨日度量可算即判，缺槽如实标注）
    partial = lifecycle_risk_flag(3, True, [])
    assert partial["level"] == "partial" and any("仅3/10槽" in r for r in partial["reasons"])
    assert lifecycle_risk_flag(2, True, [])["level"] == "ok" or lifecycle_risk_flag(2, True, [])["level"] == "partial"
    ins1 = lifecycle_risk_flag(1, True, [])
    ins2 = lifecycle_risk_flag(10, False, [])
    assert ins1["level"] == "data_insufficient" and ins2["level"] == "data_insufficient"


def test_synergy_direction_map():
    assert [synergy_direction(t) for t in ("S", "A", "B")] == ["buy"] * 3
    assert synergy_direction("C") == "hold"
    assert [synergy_direction(t) for t in ("D", "E")] == ["sell"] * 2
    assert synergy_direction("unknown") == ""  # 不计台账


# ── 确定性抽样（预登记 §六：排序冻结防挑样）──


def _vc(code, dims, res_score=50.0):
    return {"code": code, "dims": dims, "resonanceScore": res_score}


def test_sample_lifecycle_caps():
    igex = [{"code": f"I{i:02d}", "stage": "ignition"} for i in range(7)]
    late = [{"code": f"C{i:02d}", "stage": "crowded"} for i in range(5)]
    got = sample_lifecycle(igex + late, cap_igex=5, cap_total=8)
    assert len(got) == 8
    assert sum(1 for c in got if c["stage"] == "ignition") == 5  # 点火/扩散优先全量至 ≤5
    assert sum(1 for c in got if c["stage"] == "crowded") == 3


# ── EOD 补齐读法（裁决 3：只补行情字段，永不触碰引擎档位）──


def test_lifecycle_narrative_scope_and_fail_visible():
    text = build_lifecycle_narrative(
        trading_date="2026-09-30", slot="15:00", code="603259", name="测试股",
        trajectory=_traj(),
        metrics={"rankVelocity": 0.3477, "rankAcceleration": -3.646, "hotZoneStreak": 2,
                 "bestRecentRank": 29, "drawdownFromPeak": 0, "rankPathCommitment": 0.993},
        evidence={"momentumShort": 5.96, "momentumMid": 21.69, "momentumLong": 27.23,
                  "momentumAcceleration": -4.27, "riskPressure": 0.2026},
        prev_stage_line="无更早帧 前一交易日阶段：数据缺口（fail-visible）",
        stage="expansion", action="allow", confidence=80, reasons=["生命周期处于点火或扩散路径"])
    # 口径隔离（预登记 §三·二：不含四维投票档位，防方向票锚定阶段判定）
    assert "共振" not in text and "量价" not in text and "synergy" not in text
    # 可数度量全呈现 + fail-visible 前日缺口 + 引擎块标注
    assert "排名速度 0.348" in text and "距峰回撤 0.00 位" in text and "热区停留 2 天" in text
    assert "数据缺口（fail-visible）" in text
    assert "【待复核判读】规则判定（仅供复核）" in text
    assert "阶段=扩散 · 动作=放行 · 置信=80" in text


# ── fake db（equality 匹配；无操作符查询——runner 刻意不用 $lt/$in）──


class _Col:
    def __init__(self, docs):
        self.docs = list(docs)
        self.replaced: list[dict] = []

    @staticmethod
    def _match(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in query.items())

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


DATE = "2026-09-30"
SID = f"half_hour:{DATE}:15:00"
# 当日 5 个 half_hour 槽（B 预检要 ≥5 可算槽；收盘槽 15:00 是判读基准帧）
DAY_SLOTS = ["09:30", "10:00", "10:30", "11:00", "15:00"]

FRAME = {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": DATE,
         "slotTime": "15:00", "snapshotId": SID}
PREV_FRAME = {"datasetId": "dragonboard_live", "type": "half_hour",
              "tradingDate": "2026-09-29", "slotTime": "15:00",
              "snapshotId": "half_hour:2026-09-29:15:00"}


def _row(code, rank, change, slot=None, **kw):
    sid = f"half_hour:{DATE}:{slot}" if slot else SID
    d = {"datasetId": "dragonboard_live", "snapshotId": sid, "code": code,
         "name": f"股{code}", "rank": rank, "change": change}
    d.update(kw)
    return d


def _day_frames_and_rows(codes):
    """当日 5 槽帧 + 每槽各股行（rank 随槽变化，15:00 槽用基础行情字段）。"""
    frames, rows = [], []
    for i, slot in enumerate(DAY_SLOTS):
        frames.append({"datasetId": "dragonboard_live", "type": "half_hour",
                       "tradingDate": DATE, "slotTime": slot,
                       "snapshotId": f"half_hour:{DATE}:{slot}"})
        for j, code in enumerate(codes):
            base = dict(codes[code])
            base["rank"] = base["rank"] + i * (j + 1)
            base["snapshotId"] = f"half_hour:{DATE}:{slot}"
            rows.append(base)
    return frames, rows


def _ana(code, syn, res="A", rt="C", cs="B", vp="A", stage="expansion",
         metrics=None, evidence=None, action="allow", conf=80):
    return {"datasetId": "dragonboard_live", "snapshotId": SID, "code": code,
            "analysis": {
                "resonance": {"signalTier": res, "direction": "buy", "score": 70.0,
                              "tierReasons": ["r"], "status": "ok"},
                "observation": {
                    "rankTrend": {"signalTier": rt, "direction": "hold", "score": 4,
                                  "tierReasons": ["t"]},
                    "crossSection": {"signalTier": cs, "percentile": 88.0,
                                     "percentileDelta": 3.0, "tierReasons": ["c"]},
                    "volumePrice": {"signalTier": vp, "direction": "buy",
                                    "quadrant": "rise_volume", "tierReasons": ["v"]},
                    "lifecycle": {"stage": stage, "score": 90, "veto": False,
                                  "tierReasons": ["l"]},
                    "synergy": {"signalTier": syn, "tierReasons": ["s"]},
                },
                "cycle": {"stage": stage, "confidence": conf,
                          "metrics": metrics if metrics is not None else
                          {"rankVelocity": 0.3, "rankAcceleration": 1.0,
                           "hotZoneStreak": 2, "bestRecentRank": 30,
                           "drawdownFromPeak": 0.0, "rankPathCommitment": 0.95},
                          "decision": {"action": action, "confidence": conf,
                                       "reasons": ["reason"],
                                       "evidence": evidence if evidence is not None else
                                       {"momentumShort": 5.0, "momentumMid": 20.0,
                                        "momentumLong": 25.0, "momentumAcceleration": -1.0,
                                        "riskPressure": 0.2}}},
                "technical": {"macd": {"cross": "golden"}, "maCross": {"cross": None}},
            }}


def _vote_db():
    base_rows = {
        "600001": _row("600001", 8, 4.1, volumeRatio=1.5, zlje=1.2e8, turnoverRate=10.0),
        "600002": _row("600002", 20, -2.0, volumeRatio=0.8, zlje=-5e7, turnoverRate=6.0),
        "600003": _row("600003", 50, 0.5, volumeRatio=None, zlje=None, turnoverRate=None),
        "600004": _row("600004", 70, -1.0, volumeRatio=0.9, zlje=-1e6, turnoverRate=2.0),
        "600005": _row("600005", 110, 0.8, volumeRatio=1.1, zlje=5e6, turnoverRate=3.0),
    }
    frames, rows = _day_frames_and_rows(base_rows)
    anas = [_ana("600001", "B"),
            _ana("600002", "D", res="D", vp="E", stage="reversal"),
            _ana("600003", "C", stage="cooling"),   # C 档：A 人口外；cooling：B 人口外
            _ana("600004", "E", stage="cooling"),   # E 档：五修纳入 neutral（全量口径）
            _ana("600005", "B", vp="unknown", res="unknown", rt="unknown", cs="unknown",
                 stage="cooling")]                   # 四维全 unknown → data_insufficient
    # 前一交易日（2026-09-29）15:00 帧的 600001 analysis（prevStage 供 B 题集叙事与 riskFlag）
    anas.append({**_ana("600001", "C", stage="expansion"),
                 "snapshotId": "half_hour:2026-09-29:15:00", "code": "600001"})
    return _Db({"snapshot_frames": _Col(frames + [PREV_FRAME]),
                "snapshot_stock_rows": _Col(rows),
                "snapshot_analysis": _Col(anas)})


# ── 人口构建（fake db）──


def test_build_lifecycle_population_and_prev_stage():
    pop = runner.build_lifecycle_population(_vote_db(), DATE)
    codes = {c["code"] for c in pop["candidates"]}
    assert codes == {"600001", "600002"}  # 600003/600004/600005 cooling 不进 B 人口
    c1 = next(c for c in pop["candidates"] if c["code"] == "600001")
    assert c1["prevDate"] == "2026-09-29" and c1["prevStage"] == "expansion"
    # 六修后 5/10 槽=partial（当日轨迹不足全日，如实标注）
    assert c1["riskFlag"]["level"] == "partial"
    assert any("仅5/10槽" in r for r in c1["riskFlag"]["reasons"])
    assert c1["metrics"]["rankVelocity"] == 0.3


def test_build_lifecycle_population_prev_missing_is_partial():
    base_rows = {"800001": _row("800001", 9, 1.0, volumeRatio=1.0, zlje=1e7, turnoverRate=5.0)}
    frames, rows = _day_frames_and_rows(base_rows)
    anas = [_ana("800001", "B", stage="ignition")]
    db = _Db({"snapshot_frames": _Col(frames),  # 无前日帧
              "snapshot_stock_rows": _Col(rows),
              "snapshot_analysis": _Col(anas)})
    pop = runner.build_lifecycle_population(db, DATE)
    rf = pop["candidates"][0]["riskFlag"]
    assert rf["level"] == "partial" and "prev_stage_missing" in rf["reasons"]


def test_run_lifecycle_fire_persist_contract(monkeypatch):
    calls = []

    def fake_dispatch(state, questions):
        calls.append((state, questions))
        return {"success": True, "result": {"state": "Completed", "result": {
            "model": "typesafe/jev",
            "answers": {"lifecycle_stage_recheck": {
                "type": "choice", "choice": "crowded", "confidence": 0.51,
                "probabilities": {"crowded": 0.51, "reversal": 0.3, "expansion": 0.1,
                                  "ignition": 0.05, "cooling": 0.04}}},
            "usage": {"input_tokens": 900, "output_tokens": 70}}}}, 88

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    db = _vote_db()
    stats = runner.run_lifecycle_day(db, [DATE], fire=True)
    assert calls and calls[0][1] == QUESTIONS_LIFECYCLE_RECHECK
    col = db["hotlist_jev_lifecycle_recheck_pilot"]
    docs = {d["_id"]: d for d in col.docs}
    # 抽样：ignition(600001) + crowded/reversal(600002) → 2 call
    assert stats["ok"] == 2 and stats["tokens"] == 1940
    d1 = docs[f"{DATE}:15:00:600001:LC"]
    assert d1["lcStage"] == "crowded" and d1["lcConfidence"] == 0.51
    assert d1["ruleStage"] == "expansion" and d1["ruleAction"] == "allow"
    assert d1["prevStage"] == "expansion" and d1["prevTradingDate"] == "2026-09-29"
    assert d1["responseRaw"]["result"]["state"] == "Completed"  # 全保留
    assert d1["questionSetVersion"] == "v1"
    # 对照锚机械可算：ruleStage=expansion vs jev crowded → diverge（台账在复盘侧做，落库带双方读数）
    assert d1["ruleStage"] != d1["lcStage"]


# ── 扩窗修正案（§十一）：帽位参数透传 ──


def test_due_slot_logic():
    import datetime as dt
    # watch 槽表 = 11:30 + 15:00（用户裁决 2026-10-12 二修：每日两帧）
    # 上午盘中 10:33 → 11:30 未到 → None
    assert runner._due_slot(dt.datetime(2026, 10, 12, 10, 33, 0)) is None
    # 11:32（满 120s 缓冲）→ 11:30
    assert runner._due_slot(dt.datetime(2026, 10, 12, 11, 32, 0)) == "11:30"
    # 午休 13:00 → 仍 11:30（已跑则标记跳过，零成本）
    assert runner._due_slot(dt.datetime(2026, 10, 12, 13, 0, 0)) == "11:30"
    # 下午盘中 14:00 → 仍 11:30
    assert runner._due_slot(dt.datetime(2026, 10, 12, 14, 0, 0)) == "11:30"
    # 盘前 09:00 → None
    assert runner._due_slot(dt.datetime(2026, 10, 12, 9, 0, 0)) is None
    # 收盘后 15:06 → 15:00
    assert runner._due_slot(dt.datetime(2026, 10, 12, 15, 6, 0)) == "15:00"


def test_frame_mark_roundtrip():
    db = _Db({"hotlist_jev_vote_confirm_pilot": _Col([])})
    assert not runner._frame_mark_done(db, "hotlist_jev_vote_confirm_pilot", DATE, "10:00", "VOTE")
    runner._write_frame_mark(db, "hotlist_jev_vote_confirm_pilot", DATE, "10:00", "VOTE",
                             {"ok": 5, "tokens": 123})
    assert runner._frame_mark_done(db, "hotlist_jev_vote_confirm_pilot", DATE, "10:00", "VOTE")
    mark = db["hotlist_jev_vote_confirm_pilot"].find_one({"_id": f"{DATE}:10:00:MARK:VOTE"})
    assert mark["status"] == "run_marker" and mark["tokens"] == 123


# ── 原料跨日化（b 代：近10日排名轨迹行，判据「多日/峰值」引用获得可数锚）──


def test_multi_day_trajectory_line_rendered():
    text = build_lifecycle_narrative(
        trading_date="2026-09-30", slot="15:00", code="603259", name="测试股",
        trajectory=_traj(),
        multi_day_trajectory=[{"date": "2026-09-25", "rank": 55, "change": 2.1},
                              {"date": "2026-09-28", "rank": 44, "change": -1.3},
                              {"date": "2026-09-29", "rank": None, "change": None}],
        metrics={"rankVelocity": 0.3, "rankAcceleration": 1.0, "hotZoneStreak": 2,
                 "bestRecentRank": 29, "drawdownFromPeak": 0, "rankPathCommitment": 0.95},
        evidence={"momentumShort": 1, "momentumMid": 2, "momentumLong": 3,
                  "momentumAcceleration": 0, "riskPressure": 0.1},
        prev_stage_line="2026-09-29 阶段=扩散", stage="expansion", action="allow",
        confidence=80, reasons=["r"])
    # 跨日可数锚呈现（判据「多日/峰值」引用的原料）+ 缺日 fail-visible
    assert "【近10日排名轨迹】（日:名次,涨幅）2026-09-25:55,+2.10% → 2026-09-28:44,-1.30% → 2026-09-29:缺,缺" in text
    assert "【当日排名轨迹】" in text


def test_multi_day_missing_fail_visible():
    text = build_lifecycle_narrative(
        trading_date="2026-09-30", slot="15:00", code="X", name="",
        trajectory=_traj(), multi_day_trajectory=None,
        metrics={"rankVelocity": 0.1, "rankAcceleration": 0.1, "hotZoneStreak": 0,
                 "bestRecentRank": 50, "drawdownFromPeak": 0, "rankPathCommitment": 0.5},
        evidence={}, prev_stage_line="缺", stage="cooling", action="caution",
        confidence=50, reasons=[])
    assert "【近10日排名轨迹】数据缺口（fail-visible）" in text


def test_lifecycle_population_include_cooling():
    """缺省=非 cooling pilot 口径；include_cooling=True 全量覆盖（含 cooling）。"""
    db = _vote_db()  # 600001 expansion / 600002 reversal / 600003-5 cooling
    pop_pilot = runner.build_lifecycle_population(db, DATE)
    assert {c["code"] for c in pop_pilot["candidates"]} == {"600001", "600002"}
    pop_full = runner.build_lifecycle_population(db, DATE, include_cooling=True)
    codes = {c["code"] for c in pop_full["candidates"]}
    assert codes == {"600001", "600002", "600003", "600004", "600005"}
    # cooling 候选原料齐备（跨日轨迹/度量/前日阶段），判据 cooling 段可判
    c3 = next(c for c in pop_full["candidates"] if c["code"] == "600003")
    assert c3["stage"] == "cooling" and c3["metrics"] and c3["multiDayTrajectory"]


def test_run_lifecycle_include_cooling_fire(monkeypatch):
    def fake_dispatch(state, questions):
        return {"success": True, "result": {"state": "Completed", "result": {
            "model": "typesafe/jev",
            "answers": {"lifecycle_stage_recheck": {"type": "choice", "choice": "cooling",
                                                    "confidence": 0.7,
                                                    "probabilities": {"cooling": 0.7}}},
            "usage": {"input_tokens": 100, "output_tokens": 20}}}}, 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    stats = runner.run_lifecycle_day(_vote_db(), [DATE], fire=True,
                                     cap_igex=100, cap_total=200, include_cooling=True)
    assert stats["ok"] == 5  # 全量人口 5 例（2 非 cooling + 3 cooling）


# ── A 人口全量覆盖（用户裁决 2026-10-12：250 只池 VOTE 也要全覆盖，C 档无方向票也判）──

