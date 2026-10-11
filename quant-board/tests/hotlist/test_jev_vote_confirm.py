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
    backfill_quote_fields,
    build_lifecycle_narrative,
    build_vote_narrative,
    lifecycle_risk_flag,
    sample_lifecycle,
    sample_vote,
    synergy_direction,
    vote_risk_flag,
)

# ── 判据冻结件（预登记 §二·三/§三·三，逐字=代码文本；改动=改门须重走预登记）──


def test_vote_criteria_frozen_text():
    q = QUESTIONS_VOTE_CONFIRM["vote_direction"]
    # 三态纯净（2026-10-12 用户裁决 1：insufficient 逃生口删除，risk_flag 由 runner 侧预检承担）
    assert set(q["criteria"]) == {"buy", "hold", "sell"}
    assert "insufficient" not in q["instructions"]
    # 逐字锚（判据全文见预登记，漂移即违规）
    assert "buy、sell 还是 hold" in q["instructions"]
    assert "只依据所给信息判断，不预测后市" in q["instructions"]
    assert "②环境门只注记不参与投票" in q["instructions"]
    assert "以原始证据为准" in q["instructions"]
    assert q["criteria"]["buy"].startswith("多方：≥2 个有向维（共振/趋势/量价）方向为 buy")
    assert "量价档 E（出货硬风险）" in q["criteria"]["sell"]
    assert "或全部有向维方向为 hold/unknown" in q["criteria"]["hold"]


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


def test_version_stamps_independent_v1():
    # 预登记 §五：独立戳（cycle v5 旧债不重犯——判据换代不动戳=跨代不可比违规）
    assert QUESTION_SET_VERSION_VOTE_CONFIRM == "v1"
    assert QUESTION_SET_VERSION_LIFECYCLE_RECHECK == "v1"
    assert QUESTION_SET_VERSION_VOTE_CONFIRM != QUESTION_SET_VERSION_DRIVER
    assert QUESTION_SET_VERSION_LIFECYCLE_RECHECK != QUESTION_SET_VERSION_CYCLE
    assert runner.VOTE_AMMO_VERSION == "2026-10-12b"  # b 代=原料跨日化（近10日轨迹行）


# ── riskFlag 预检（裁决 1 落地）──


def test_vote_risk_flag_levels():
    dims_all = {"resonance": "S", "rankTrend": "C", "crossSection": "B", "volumePrice": "A"}
    assert vote_risk_flag(dims_all, []) == {"level": "ok", "reasons": []}
    partial = vote_risk_flag({**dims_all, "volumePrice": "unknown"}, ["evidence_missing:zlje"])
    assert partial["level"] == "partial"
    assert any("volumePrice" in r for r in partial["reasons"])
    assert any("zlje" in r for r in partial["reasons"])
    ins = vote_risk_flag({"resonance": "S", "rankTrend": "unknown",
                          "crossSection": "unknown", "volumePrice": "unknown"}, [])
    assert ins["level"] == "data_insufficient"
    assert ins["reasons"][0].startswith("有效档位维=1")


def test_lifecycle_risk_flag_levels():
    assert lifecycle_risk_flag(10, True, []) == {"level": "ok", "reasons": []}
    assert lifecycle_risk_flag(10, True, ["prev_stage_missing"])["level"] == "partial"
    ins1 = lifecycle_risk_flag(3, True, [])
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


def test_sample_vote_deterministic():
    buy = [_vc("B01", {"resonance": "S", "rankTrend": "A", "crossSection": "A", "volumePrice": "A"}, 80),
           _vc("B02", {"resonance": "B", "rankTrend": "B", "crossSection": "B", "volumePrice": "B"}, 60),
           _vc("B03", {"resonance": "A", "rankTrend": "C", "crossSection": "C", "volumePrice": "C"}, 90)]
    sell = [_vc("S01", {"resonance": "D", "rankTrend": "D", "crossSection": "D", "volumePrice": "E"}),
            _vc("S02", {"resonance": "D", "rankTrend": "D", "crossSection": "D", "volumePrice": "D"})]
    got = sample_vote(buy, sell, cap_buy=2, cap_sell=2)
    # buy：最高档位数 B01=4 > B03=1 > B02=0（共振分数只在同档位数时比较）
    assert [c["code"] for c in got[:2]] == ["B01", "B03"]
    # sell：量价 E 短路优先
    assert [c["code"] for c in got[2:]] == ["S01", "S02"]


def test_sample_lifecycle_caps():
    igex = [{"code": f"I{i:02d}", "stage": "ignition"} for i in range(7)]
    late = [{"code": f"C{i:02d}", "stage": "crowded"} for i in range(5)]
    got = sample_lifecycle(igex + late, cap_igex=5, cap_total=8)
    assert len(got) == 8
    assert sum(1 for c in got if c["stage"] == "ignition") == 5  # 点火/扩散优先全量至 ≤5
    assert sum(1 for c in got if c["stage"] == "crowded") == 3


# ── EOD 补齐读法（裁决 3：只补行情字段，永不触碰引擎档位）──


def test_backfill_quote_fields():
    base = {"code": "600000", "change": None, "volumeRatio": None, "zlje": None,
            "resonance": {"signalTier": "A"}}
    donor = {"change": 3.2, "volumeRatio": 1.8, "zlje": 1.17e8, "turnoverRate": None}
    merged, filled, missing = backfill_quote_fields(
        base, donor, sparse_fields=["change", "volumeRatio", "zlje", "turnoverRate"])
    assert filled == ["change", "volumeRatio", "zlje"]
    assert missing == ["turnoverRate"]  # 两源皆缺保持缺失（fail-visible 不伪造）
    assert merged["change"] == 3.2 and merged["zlje"] == 1.17e8
    assert merged["resonance"] == {"signalTier": "A"}  # 引擎档位不触碰


def test_backfill_ignores_non_sparse_fields():
    base = {"change": 5.0, "volumeRatio": None}
    donor = {"change": 9.9, "volumeRatio": 2.0}
    merged, filled, _ = backfill_quote_fields(base, donor, sparse_fields=["volumeRatio"])
    assert filled == ["volumeRatio"]  # 基准帧非稀疏字段不覆盖
    assert merged["change"] == 5.0


# ── 叙事组装（fail-visible / 口径隔离 / 引擎块标注）──


def _traj():
    return [{"slot": "09:30", "rank": 81, "change": -0.72},
            {"slot": "10:00", "rank": None, "change": 1.62},
            {"slot": "10:30", "rank": 92.5, "change": None}]


def test_vote_narrative_fail_visible_and_gate_note():
    text = build_vote_narrative(
        trading_date="2026-09-30", slot="15:00", code="002487", name="测试股",
        resonance={"signalTier": "S", "direction": "buy", "score": 80.0,
                   "tierReasons": ["Jump 事件触发共振跃迁"], "status": "ok"},
        trend={"signalTier": "C", "direction": "hold", "score": 4, "tierReasons": ["中性"]},
        cross_section={"signalTier": "A", "percentile": 97.3, "percentileDelta": 5.2,
                       "tierReasons": ["分位强势"]},
        volume_price={"signalTier": "unknown", "direction": None, "quadrant": None,
                      "tierReasons": ["量价数据不足"]},
        trend_events={"macdCross": "golden", "maCross": None},
        row={"change": 4.13, "volumeRatio": None, "zlje": None, "turnoverRate": 12.5},
        sparse_fields=[], trajectory=_traj(),
        gate={"stage": "expansion", "veto": False}, synergy_tier="B")
    assert "002487 测试股" in text and "2026-09-30 交易日 15:00 槽" in text
    # fail-visible：量价 unknown/量比缺/主力净额缺/轨迹缺槽如实标注，不伪造 0
    assert "档位 unknown" in text and "量比 缺" in text and "主力净额 缺" in text
    assert "10:00:缺" in text and "10:30:92.5,缺" in text
    # 技术面事件（中文映射）+ 环境门只注记 + 引擎块标注
    assert "MACD=金叉、MA=无" in text
    assert "只注记不参与投票" in text
    assert "（环境门只注记不参与投票）" in text
    assert "【待复核判读】规则投票（仅供复核）" in text and "综合档位 B" in text
    # 共振 status=ok 时不加注记
    assert "证据不足如实标注" not in text


def test_vote_narrative_resonance_insufficient_note():
    text = build_vote_narrative(
        trading_date="2026-09-30", slot="15:00", code="X", name="",
        resonance={"signalTier": "unknown", "direction": None, "score": None,
                   "tierReasons": [], "status": "insufficient"},
        trend={"signalTier": "D", "direction": "sell", "score": 60, "tierReasons": ["趋势转弱"]},
        cross_section={"signalTier": "C", "percentile": 40.0, "percentileDelta": -2.0,
                       "tierReasons": []},
        volume_price={"signalTier": "E", "direction": "down", "quadrant": "fall_volume",
                      "tierReasons": ["出货"]},
        trend_events={}, row={"change": -5.1, "volumeRatio": 2.2, "zlje": -3.3e7,
                              "turnoverRate": 8.0},
        sparse_fields=[], trajectory=_traj(),
        gate={"stage": "reversal", "veto": True}, synergy_tier="D")
    assert "status=insufficient，证据不足如实标注" in text
    assert "一票否决=是" in text
    # 量价方向引擎投票语义归一（down→sell）+ zlje 原始元折亿
    assert "量价：档位 E · 方向 sell" in text
    assert "主力净额 -0.330亿" in text


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
            _ana("600004", "E", stage="cooling"),   # E 档：归 B 语境
            _ana("600005", "B", vp="unknown", res="unknown", rt="unknown", cs="unknown",
                 stage="cooling")]                   # 四维全 unknown → data_insufficient
    # 前一交易日（2026-09-29）15:00 帧的 600001 analysis（prevStage 供 B 题集叙事与 riskFlag）
    anas.append({**_ana("600001", "C", stage="expansion"),
                 "snapshotId": "half_hour:2026-09-29:15:00", "code": "600001"})
    return _Db({"snapshot_frames": _Col(frames + [PREV_FRAME]),
                "snapshot_stock_rows": _Col(rows),
                "snapshot_analysis": _Col(anas)})


# ── 人口构建（fake db）──


def test_build_vote_population_classification():
    pop = runner.build_vote_population(_vote_db(), DATE)
    assert "error" not in pop["meta"]
    codes_buy = {c["code"] for c in pop["buy"]}
    codes_sell = {c["code"] for c in pop["sell"]}
    codes_ins = {c["code"] for c in pop["insufficient"]}
    assert codes_buy == {"600001"}          # B 档
    assert codes_sell == {"600002"}         # D 档（含量价 E 短路）
    assert codes_ins == {"600005"}          # 四维全 unknown → data_insufficient
    # C/E 档人口外
    assert "600003" not in codes_buy | codes_sell and "600004" not in codes_buy | codes_sell
    # 600001 原料完整性
    c1 = pop["buy"][0]
    assert c1["riskFlag"]["level"] == "ok"
    assert c1["synergyDirection"] == "buy"
    assert c1["trendEvents"]["macdCross"] == "golden"
    assert c1["gate"] == {"stage": "expansion", "veto": False}
    assert len(c1["trajectory"]) == 5  # 当日 5 个 half_hour 槽
    # 600002 的 sell 侧：风险标记与对照锚
    s1 = pop["sell"][0]
    assert s1["riskFlag"]["level"] == "ok" and s1["synergyDirection"] == "sell"


def test_build_vote_population_sparse_frame_detection():
    # 帧级行情字段全 0/None（daily 15:30 形态）→ 判帧级稀疏，不算个股缺口
    db = _Db({"snapshot_frames": _Col([FRAME]),
              "snapshot_stock_rows": _Col([
                  _row("700001", 5, None, volumeRatio=None, zlje=None, turnoverRate=None),
                  _row("700002", 6, None, volumeRatio=None, zlje=None, turnoverRate=None)]),
              "snapshot_analysis": _Col([
                  _ana("700001", "B"),
                  _ana("700002", "B", res="unknown", vp="unknown", rt="unknown", cs="unknown")])})
    pop = runner.build_vote_population(db, DATE)
    assert pop["meta"]["sparse_fields"] == ["change", "volumeRatio", "zlje", "turnoverRate", "amount"]
    c1 = pop["buy"][0]
    assert c1["riskFlag"]["level"] == "ok"  # 帧级稀疏不计个股证据缺口
    assert pop["insufficient"][0]["code"] == "700002"


def test_build_lifecycle_population_and_prev_stage():
    pop = runner.build_lifecycle_population(_vote_db(), DATE)
    codes = {c["code"] for c in pop["candidates"]}
    assert codes == {"600001", "600002"}  # 600003/600004/600005 cooling 不进 B 人口
    c1 = next(c for c in pop["candidates"] if c["code"] == "600001")
    assert c1["prevDate"] == "2026-09-29" and c1["prevStage"] == "expansion"
    assert c1["riskFlag"]["level"] == "ok"
    assert c1["metrics"]["rankVelocity"] == 0.3


def test_build_lifecycle_population_prev_missing_is_partial():
    base_rows = {"800001": _row("800001", 9, 1.0, volumeRatio=1.0, zlje=1e7, turnoverRate=5.0)}
    frames, rows = _day_frames_and_rows(base_rows)
    anas = [_ana("800001", "B", stage="ignition")]
    db = _Db({"snapshot_frames": _Col(frames),  # 无前日帧
              "snapshot_stock_rows": _Col(rows),
              "snapshot_analysis": _Col(anas)})
    pop = runner.build_lifecycle_population(db, DATE)
    assert pop["candidates"][0]["riskFlag"] == {"level": "partial",
                                                "reasons": ["prev_stage_missing"]}


def test_build_population_no_frame():
    db = _Db({"snapshot_frames": _Col([]), "snapshot_stock_rows": _Col([]),
              "snapshot_analysis": _Col([])})
    assert runner.build_vote_population(db, DATE)["meta"]["error"] == "no_frame"
    assert runner.build_lifecycle_population(db, DATE)["meta"]["error"] == "no_frame"


# ── 落库合同（裁决 5 全保留）+ 熔断 + dry-run 零调用 ─--

ENV_OK = {"success": True, "result": {"state": "Completed", "result": {
    "model": "typesafe/jev",
    "answers": {"vote_direction": {"type": "choice", "choice": "buy", "confidence": 0.42,
                                   "probabilities": {"buy": 0.55, "hold": 0.30, "sell": 0.15}}},
    "usage": {"input_tokens": 1000, "output_tokens": 80}}}}


def test_run_vote_fire_persist_contract(monkeypatch):
    calls = []

    def fake_dispatch(state, questions):
        calls.append((state, questions))
        return dict(ENV_OK), 123

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    db = _vote_db()
    stats = runner.run_vote_day(db, [DATE], fire=True)
    assert calls and calls[0][1] == QUESTIONS_VOTE_CONFIRM
    col = db["hotlist_jev_vote_confirm_pilot"]
    docs = {d["_id"]: d for d in col.docs}
    assert stats["ok"] == 2 and stats["tokens"] == 2160  # 1080×2（600001 buy + 600002 sell）
    d1 = docs[f"{DATE}:15:00:600001:VOTE"]
    # 全保留合同：answers 原样包 + confidence 升顶层 + responseRaw 一律存完整 envelope
    assert d1["answers"]["vote_direction"]["confidence"] == 0.42
    assert d1["voteDirection"] == "buy" and d1["voteConfidence"] == 0.42
    assert d1["voteProbabilities"]["buy"] == 0.55
    assert d1["responseRaw"] == ENV_OK
    # 盖戳与预检留痕
    assert d1["questionSetVersion"] == "v1" and d1["questionSetHash"]
    assert d1["riskFlag"] == {"level": "ok", "reasons": []}
    assert d1["synergyTier"] == "B" and d1["synergyDirection"] == "buy"
    assert d1["status"] == "ok" and d1["origin"] == "vote_confirm_pilot"
    # data_insufficient 留痕文档（不调用）
    ins = docs[f"{DATE}:15:00:600005:VOTE"]
    assert ins["status"] == "data_insufficient" and ins["answers"] is None
    assert stats["data_insufficient"] == 1
    # 幂等：重跑 ok 文档跳过
    stats2 = runner.run_vote_day(db, [DATE], fire=True)
    assert stats2["skip"] == 2


def test_run_vote_token_fuse(monkeypatch):
    monkeypatch.setattr(runner, "TOKEN_FUSE", 100)
    n = {"k": 0}

    def fake_dispatch(state, questions):
        n["k"] += 1
        return dict(ENV_OK), 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    stats = runner.run_vote_day(_vote_db(), [DATE], fire=True)
    assert n["k"] == 1  # 首 call 后 1080 ≥ 100 → 熔断停止
    assert stats["ok"] == 1


def test_run_vote_dry_run_zero_call(monkeypatch):
    def boom(state, questions):
        raise AssertionError("dry-run 不得触发 jev 调用")

    monkeypatch.setattr(runner, "_dispatch_jev", boom)
    db = _vote_db()
    stats = runner.run_vote_day(db, [DATE], fire=False)
    assert stats["ok"] == 0 and stats["tokens"] == 0
    assert db["hotlist_jev_vote_confirm_pilot"].docs == []  # dry-run 零写库


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


def test_sample_caps_passthrough():
    buy = [_vc(f"B{i:02d}", {"resonance": "B", "rankTrend": "B", "crossSection": "B",
                             "volumePrice": "B"}, 50.0) for i in range(10)]
    sell = [_vc(f"S{i:02d}", {"resonance": "D", "rankTrend": "D", "crossSection": "C",
                              "volumePrice": "E"}) for i in range(6)]
    got = sample_vote(buy, sell, cap_buy=3, cap_sell=2)
    assert len(got) == 5  # §十一 扩窗帽：buy 3 + sell 2
    assert [c["code"] for c in got[3:]] == ["S00", "S01"]  # vp-E 优先序不变


def test_run_vote_cap_override(monkeypatch):
    def fake_dispatch(state, questions):
        return dict(ENV_OK), 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    db = _vote_db()
    db["snapshot_analysis"].docs.append(_ana("600007", "B"))
    db["snapshot_stock_rows"].docs.append(
        _row("600007", 15, 2.0, volumeRatio=1.2, zlje=2e7, turnoverRate=7.0))
    stats = runner.run_vote_day(db, [DATE], fire=True, cap_buy=1, cap_sell=1)
    assert stats["ok"] == 2 and stats["tokens"] == 2160  # 帽收紧后只采 1+1（默认帽则 2+1=3 call）
    assert not any(d["code"] == "600007" for d in db["hotlist_jev_vote_confirm_pilot"].docs)


def test_run_vote_workers_and_fuse_override(monkeypatch):
    """生产回填路径（§六·产）：workers>1 并发 + token_fuse 显式放宽。"""
    n = {"k": 0}

    def fake_dispatch(state, questions):
        n["k"] += 1
        return dict(ENV_OK), 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    stats = runner.run_vote_day(_vote_db(), [DATE], fire=True, workers=4, token_fuse=10_000_000)
    assert stats["ok"] == 2 and stats["tokens"] == 2160  # 并发路径全采
    assert n["k"] == 2


def test_run_vote_serial_fuse_default(monkeypatch):
    """缺省 token_fuse=None → 用模块 TOKEN_FUSE（150k），抽样例不触发。"""
    monkeypatch.setattr(runner, "_dispatch_jev", lambda s, q: (dict(ENV_OK), 1))
    stats = runner.run_vote_day(_vote_db(), [DATE], fire=True)
    assert stats["ok"] == 2 and stats["tokens"] == 2160


# ── 帧级口径（用户裁决 2026-10-12：每帧落库后即跑）──


def test_slot_parameterized_ids_and_narrative(monkeypatch):
    """--slot 帧级口径：_id 含槽位、叙事槽位行、与 15:00 存量互不干扰，数据真来自该帧。"""
    def fake_dispatch(state, questions):
        return dict(ENV_OK), 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    db = _vote_db()
    sid10 = "half_hour:2026-09-30:10:00"
    db["snapshot_analysis"].docs.append(
        {**_ana("600001", "B"), "snapshotId": sid10})
    db["snapshot_analysis"].docs.append(
        {**_ana("600002", "D", res="D", vp="E", stage="reversal"), "snapshotId": sid10})
    runner.run_vote_day(db, [DATE], fire=True, slot="10:00")
    docs = db["hotlist_jev_vote_confirm_pilot"].docs
    assert docs and all(d["_id"].startswith(f"{DATE}:10:00:") for d in docs)
    assert all("10:00 槽" in d["narrative"] for d in docs if "narrative" in d)
    assert all("15:00 槽" not in d.get("narrative", "") for d in docs)
    # 数据真来自 10:00 帧：600002（D/vpE）在该帧人口内被采
    assert any(d.get("code") == "600002" for d in docs)


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


def test_population_carries_multi_day(db_factory=None):
    import backend.operations.jev_vote_confirm as runner2
    pop = runner2.build_vote_population(_vote_db(), DATE)
    c1 = pop["buy"][0]
    assert c1["multiDayTrajectory"] == [{"date": "2026-09-29", "rank": None, "change": None}]
    pop_b = runner2.build_lifecycle_population(_vote_db(), DATE)
    assert pop_b["candidates"][0]["multiDayTrajectory"][0]["date"] == "2026-09-29"


def test_ammo_version_bumped_for_cross_day():
    assert VOTE_AMMO_VERSION == "2026-10-12b"  # b 代=原料跨日化


# ── B 人口全量覆盖（用户裁决 2026-10-12：cooling 股也要有周期判读）──


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


def test_vote_population_include_neutral():
    """缺省=pilot 口径（C 不进）；include_neutral=True C 档进 neutral 桶全量判读。"""
    db = _vote_db()  # 600003 syn C
    pop_pilot = runner.build_vote_population(db, DATE)
    assert all("600003" not in {c["code"] for c in pop_pilot[k]} for k in ("buy", "sell", "neutral"))
    pop_full = runner.build_vote_population(db, DATE, include_neutral=True)
    codes = {c["code"] for c in pop_full["neutral"]}
    assert "600003" in codes
    c3 = next(c for c in pop_full["neutral"] if c["code"] == "600003")
    assert c3["synergyDirection"] == "hold"  # C→hold 对照锚
    assert c3["riskFlag"]["level"] == "partial"  # 600003 证据行缺失（fixture 设定）→ partial 仍判读


def test_run_vote_include_neutral_fire(monkeypatch):
    def fake_dispatch(state, questions):
        return dict(ENV_OK), 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    stats = runner.run_vote_day(_vote_db(), [DATE], fire=True,
                                cap_buy=200, cap_sell=200, include_neutral=True)
    assert stats["ok"] == 4  # 600001 buy + 600002 sell + 600003 C 档 + 600004 E 档（全量无帽）


def test_vote_population_include_e_tier():
    """五修（用户裁决 2026-10-12）：E 档（环境门否决）纳入 VOTE 全量人口——
    jev 判据环境门只注记不投票，方向读数独立成立。"""
    db = _vote_db()  # 600004 syn E
    pop_pilot = runner.build_vote_population(db, DATE)
    assert "600004" not in {c["code"] for c in pop_pilot.get("neutral", [])}
    pop_full = runner.build_vote_population(db, DATE, include_neutral=True)
    c4 = next((c for c in pop_full["neutral"] if c["code"] == "600004"), None)
    assert c4 is not None
    assert c4["synergyTier"] == "E" and c4["synergyDirection"] == "sell"  # E→sell 对照锚
    assert c4["gate"] == {"stage": "cooling", "veto": False}
