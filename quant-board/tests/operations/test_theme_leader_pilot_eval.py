# -*- coding: utf-8 -*-
"""题材层 pilot 离线评估脚本测试（**零 jev 调用 / 零网络**）。

锁定口径：
1. 结局判定只认 `sealed_and_info`（触板−THS炸板二分），与投喂时的基线同源；
2. 次日 THS 池缺失 / 无次日文档 → 结局 `None`：**不计入率**、fail-visible 记录，不按"未续板"处理；
3. 同桶基准率逐级回退顺序与 `baseline_line` 一致（组合桶 → 连板高度桶 → 板块家数桶 → 总体）；
4. 全判 `insufficient` 时不给单点概率（不编造），并计入 `insufficientShare`；
5. 单日样本远不足验收门槛 → 判定恒为"观察，不下结论"。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "theme_leader_pilot_eval", ROOT / "scripts" / "theme_leader_pilot_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E = _load_eval()


class FakeCol:
    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.updates: list[tuple] = []

    def find_one(self, query=None, projection=None):
        return self.docs[0] if self.docs else None

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                out.append(dict(d))
        return out

    def update_one(self, flt, update):
        self.updates.append((flt, update))
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                d.update(update["$set"])


class FakeDb:
    def __init__(self, labels, sealed_next, dates=(("2026-10-19",), ("2026-10-20",))):
        self.labels = FakeCol(labels)
        self._dates = [d[0] for d in dates]

    def __getitem__(self, name):
        if name == E.COLLECTION:
            return self.labels
        if name == "jiuyan_action":
            # v5 结局回填读次日板块家数；测试库无异动文档 → fields 空（回填 None/0，不伪造）
            return FakeCol([])
        raise KeyError(name)


def _label(code, name, choice="mid_45_65", probs=None, bucket="{}", stage="ongoing",
           version="v1", gate=None):
    return {
        "_id": f"2026-10-19:{code}", "tradingDate": "2026-10-19", "code": code, "name": name,
        "board": "机器人", "questionSetVersion": version, "gate": gate or {"applied": False},
        "baselineMeta": {"start": "2026-07-16", "end": "2026-10-16"},
        "baselineBucket": bucket,
        "answers": {"leader_nextday_continue": {
            "choice": choice, "probabilities": probs or {"mid_45_65": 0.9, "insufficient": 0.1}}},
        "catalystStage": stage,
    }


@pytest.fixture
def patched(monkeypatch):
    def _apply(labels, sealed_next, rows=None, dates=(("2026-10-19",), ("2026-10-20",))):
        db = FakeDb(labels, sealed_next, dates)
        monkeypatch.setattr(E, "trading_dates",
                            lambda _db, start, end: [d[0] for d in dates if start <= d[0] <= end])
        monkeypatch.setattr(E, "sealed_and_info",
                            lambda _db, date: (sealed_next, {}, {"thsPoolFound": True}))
        monkeypatch.setattr(E, "build_rows",
                            lambda _db, start, end: {"rows": rows or []})
        return db
    return _apply


def test_outcome_in_backfilled_and_unknown_next_day_is_none(patched):
    db = patched([_label("603278", "大业股份"), _label("600686", "金龙汽车")], {"603278"})
    out = E.evaluate(db, "2026-10-19", write_outcome=True)
    assert out["nextDate"] == "2026-10-20"
    assert out["evaluable"] == 2 and out["actualContinue"] == 1
    persisted = {d["_id"]: d["outcomeSealedNextDay"] for d in db.labels.docs}
    assert persisted == {"2026-10-19:603278": True, "2026-10-19:600686": False}
    assert db.labels.docs[0]["outcomeMeta"]["nextDate"] == "2026-10-20"


def test_next_day_pool_missing_is_fail_visible_not_false(monkeypatch, patched):
    db = patched([_label("603278", "大业股份")], None)   # 次日 THS 池缺失 → sealed_and_info 返回 None
    out = E.evaluate(db, "2026-10-19", write_outcome=True)
    assert out["evaluable"] == 0 and out["actualRate"] is None
    assert out["skipped"] and "不可判定" in out["skipped"][0]
    assert db.labels.docs[0]["outcomeSealedNextDay"] is None, "未知结局不得写成 False（不伪造）"
    assert db.labels.docs[0]["outcomeMeta"]["thsPoolFound"] is False


def test_no_next_trading_day_returns_none_outcome(patched):
    db = patched([_label("603278", "大业股份")], {"603278"}, dates=(("2026-10-19",),))
    out = E.evaluate(db, "2026-10-19")
    assert out["nextDate"] is None and out["evaluable"] == 0
    assert "无次日交易日数据" in out["skipped"][0]


def test_baseline_rate_fallback_order_matches_baseline_line():
    rows = [
        {"streak": 3, "boardN": 5, "time": "09:20:00", "continued": True},
        {"streak": 3, "boardN": 5, "time": "09:25:00", "continued": False},
        {"streak": 1, "boardN": 1, "time": "14:00:00", "continued": False},
    ]
    lookup = E.baseline_rate_lookup(rows, min_combo_n=5)   # 组合桶样本 <5 → 回退
    rate, label, n = lookup('{"streak": 3, "boardN": 5, "time": "09:25:00"}')
    assert rate == pytest.approx(0.5) and n == 2 and label == "连板高度[3]"
    rate2, label2, n2 = lookup('{"streak": 1, "boardN": 1, "time": "14:00:00"}')
    assert rate2 == pytest.approx(0.0) and n2 == 1 and label2 == "连板高度[1]"
    # 连板高度也缺失时才落到总体率（逐级回退到底，不编造）
    rate4, label4, n4 = lookup('{"time": "14:00:00"}')
    assert rate4 == pytest.approx(1 / 3) and n4 == 3 and label4 == "总体"
    # 组合桶样本足够（≥min_combo_n）时优先用组合桶，与 baseline_line 同序。
    # 查键必须是 combo_key() 串（回归：曾误把结构 JSON 当键 → 静默退化只用连板高度档）
    many = rows * 6   # 该组合桶出现 6 次 ≥ min_combo_n=5
    rate3, label3, _ = E.baseline_rate_lookup(many, min_combo_n=5)(
        '{"streak": 3, "boardN": 5, "time": "09:25:00"}')
    assert rate3 == pytest.approx(0.5) and label3 == "同桶[streak3|n5-7|early<=10:00]"


def test_point_estimate_excludes_insufficient_and_marks_no_probability():
    prob, mass = E.continue_point_estimate({"high_ge65": 0.5, "verylow_lt25": 0.5, "insufficient": 0.2})
    assert prob == pytest.approx((0.75 * 0.5 + 0.125 * 0.5) / 1.0) and mass == pytest.approx(0.2)
    prob2, mass2 = E.continue_point_estimate({"insufficient": 1.0})
    assert prob2 is None and mass2 == pytest.approx(1.0), "全 insufficient → 不编造概率"
    assert E.continue_point_estimate(None) == (None, 0.0)


def test_single_day_is_observation_only(patched):
    rows = [{"streak": 1, "boardN": 1, "time": "09:25:00", "continued": True}] * 5
    db = patched([_label("603278", "大业股份")], {"603278"}, rows)
    out = E.evaluate(db, "2026-10-19")
    assert out["acceptance"]["minTradingDaysMet"] is False
    assert "观察" in out["acceptance"]["verdict"]
    assert out["tradingDaysCovered"] == 1


def test_mixed_versions_are_not_aggregated(patched):
    """跨代不可比：同一天若混有 v1/v2 标签 → 只出各代际分组指标，不给跨代合计。"""
    labels = [_label("603278", "大业股份", version="v1"),
              _label("600686", "金龙汽车", version="v2",
                     gate={"applied": True, "reason": "board_unmapped"})]
    db = patched(labels, {"603278"})
    out = E.evaluate(db, "2026-10-19")
    assert out["mixedVersions"] is True
    assert out["versions"] == {"v1": 1, "v2": 1}
    assert set(out["versionMetrics"]) == {"v1", "v2"}
    assert "meanModelProb" not in out, "混代际时不得给跨代合计口径"
    assert "跨代不可比" in out["note"]


def test_gated_label_is_counted_as_insufficient_and_reported(patched):
    """v2 门强制 insufficient 的样本：不计入 Brier（不做单点概率），但要出现在 gatedShare。"""
    labels = [_label("603278", "大业股份", version="v2",
                     probs={"insufficient": 1.0},
                     gate={"applied": True, "reason": "corpus_not_collected"})]
    db = patched(labels, {"603278"})
    out = E.evaluate(db, "2026-10-19")
    assert out["scored"] == 0 and out["insufficientShare"] == 1.0
    assert out["gatedShare"] == 1.0
    assert out["samples"][0]["gate"] == "corpus_not_collected"


def test_same_day_run_shape_is_complete_and_roster_visible(patched):
    """当日跑（结局尚未可封）不得崩，且**结构契约完整 + 逐只名册可见**。

    实测缺陷（2026-10-20）：早返回路径缺 `mixedVersions`/`perBucket` 等键 → 摘要打印
    `KeyError`；且明细只列已封样本 → 未封日等于"什么都没看到"。
    """
    labels = [_label("603278", "大业股份"), _label("600267", "海正药业")]
    db = patched(labels, {"603278"}, dates=(("2026-10-19",),))
    out = E.evaluate(db, "2026-10-19")
    for key in ("versions", "mixedVersions", "scored", "perBucket", "roster", "acceptance",
                "actualRate", "actualContinue", "skipped", "samples"):
        assert key in out, f"早返回缺键：{key}"
    assert out["nextDate"] is None and out["evaluable"] == 0
    assert out["actualRate"] is None and out["mixedVersions"] is False and out["scored"] == 0
    assert {r["code"] for r in out["roster"]} == {"603278", "600267"}
    assert all(r["outcome"] is None for r in out["roster"]), "未封不得写成 False"
    # 名册仍要给模型单点概率与同桶基线（否则无法人工核对）
    assert all("modelProb" in r and "baselineRate" in r for r in out["roster"])


def test_per_bucket_groups_by_combo_key_not_raw_structure_json(patched):
    """同桶聚合必须按 `combo_key` 粒度（与对照表同粒度），不能拿结构 JSON 原串当键。

    实测缺陷：按 `baselineBucket`（结构 JSON）聚合 → 13 只碎成 13 个 n=1 桶，
    与「同桶基准率」不同粒度，读表的人会以为每组只有 1 只。
    """
    rows = [{"streak": 2, "boardN": 9, "time": "09:20:00", "continued": True},
            {"streak": 2, "boardN": 9, "time": "09:50:00", "continued": False}]
    struct = '{"streak": 2, "boardN": 9, "time": "09:20:00"}'   # 仅做审计字段
    labels = [
        {"_id": "2026-10-19:A", "tradingDate": "2026-10-19", "code": "A", "name": "a",
         "board": "机器人", "questionSetVersion": "v2", "gate": {"applied": False},
         "baselineMeta": {"start": "2026-07-16", "end": "2026-10-16"},
         "baselineBucket": struct, "structure": struct,
         "answers": {"leader_nextday_continue": {"choice": "mid_45_65",
                                                 "probabilities": {"mid_45_65": 0.6,
                                                                   "insufficient": 0.4}}},
         "catalystStage": "ongoing"},
    ]
    db = patched(labels, {"A"}, rows=rows)
    out = E.evaluate(db, "2026-10-19")
    assert out["scored"] == 1
    buckets = [pb["bucket"] for pb in out["perBucket"]]
    assert buckets and all(b.startswith("streak") for b in buckets), buckets
    assert struct not in buckets, "结构 JSON 原串不得作为聚合键"
    assert out["roster"][0]["bucketKey"].startswith("streak")


def test_backfill_samples_are_excluded_from_aggregate_metrics(patched):
    """H1 回填不混评：合计指标只对 live 前瞻样本出，回填样本单独进 `originMetrics`。

    理由：回填可能看到「当时还不存在」的语料（题材数据只在 10-20 采集），
    混进合计会把泄漏当模型能力（预登记 §11）。
    """
    rows = [{"streak": 2, "boardN": 9, "time": "09:20:00", "continued": True},
            {"streak": 2, "boardN": 9, "time": "09:50:00", "continued": False}]

    def lab(code, origin):
        return {"_id": f"2026-10-19:{code}", "tradingDate": "2026-10-19", "code": code,
                "name": code, "board": "机器人", "questionSetVersion": "v2",
                "sampleOrigin": origin, "gate": {"applied": False},
                "baselineMeta": {"start": "2026-07-16", "end": "2026-10-16"},
                "baselineBucket": '{"streak": 2, "boardN": 9, "time": "09:20:00"}',
                "structure": '{"streak": 2, "boardN": 9, "time": "09:20:00"}',
                "answers": {"leader_nextday_continue": {"choice": "mid_45_65",
                                                        "probabilities": {"mid_45_65": 0.6,
                                                                          "insufficient": 0.4}}},
                "catalystStage": "ongoing"}

    db = patched([lab("A", "live"), lab("B", "backfill")], {"A", "B"}, rows=rows)
    out = E.evaluate(db, "2026-10-19")
    assert out["origins"] == {"live": 1, "backfill": 1}, out["origins"]
    assert out["mixedOrigins"] is True
    # 合计指标只覆盖 live：1 只，不是 2 只
    assert out["n"] == 1, out["n"]
    assert out["originMetrics"]["backfill"]["n"] == 1
    assert "回填" in (out.get("note") or "")
