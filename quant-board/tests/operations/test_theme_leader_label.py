# -*- coding: utf-8 -*-
"""题材层龙头投喂 runner 测试（零真实 jev 调用 / 零网络）。

红线（AGENTS §1.2-7）：任何自动化测试都不得触发真实 jev。本文件所有用例都断言
`_dispatch_jev` 未被调用（dry-run 路径）或只调用被 monkeypatch 的假实现（run 路径）。

锁定口径：
1. `--dry-run` 零调用、零写入，但要打印"将来真下发的文本"；
2. 无 `--confirm-budget` 的实跑必须被预算护栏挡住（SystemExit）；
3. 幂等：当日 `status=ok` 的龙头再次运行时跳过（不重复烧 token）；
4. **禁止 look-ahead 泄漏**：结构基线样本窗口以当日为右边界（可含"前一日龙头→今日结局"），
   但绝不包含当日龙头的次日结局（当日 outcome 未知）；
5. THS 池缺失 → fail-visible 返回，不静默空跑。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import theme_leader_label as L


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (query or {}).items()):
                out.append({k: d.get(k) for k in projection} if projection else dict(d))
        return out


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


ROWS = [
    {"date": "2026-10-19", "board": "机器人", "code": "603278", "name": "大业股份",
     "streak": 3, "time": "09:25:00", "boardN": 5, "othersN": 4, "ladderFollowers": 1,
     "prevPeers": 2, "prevBoardN": 3, "peerCodes": ["a", "b"]},
    {"date": "2026-10-19", "board": "化工", "code": "603188", "name": "亚邦股份",
     "streak": 1, "time": "13:16:00", "boardN": 2, "othersN": 1, "ladderFollowers": 1,
     "prevPeers": 0, "prevBoardN": 0, "peerCodes": ["c"]},
]
BASELINE = [
    {"streak": 3, "boardN": 5, "time": "09:20:00", "continued": True},
    {"streak": 3, "boardN": 5, "time": "10:00:00", "continued": False},
    {"streak": 3, "boardN": 4, "time": "09:30:00", "continued": True},
    {"streak": 3, "boardN": 4, "time": "13:10:00", "continued": False},
    {"streak": 3, "boardN": 5, "time": "09:10:00", "continued": True},
    {"streak": 1, "boardN": 2, "time": "13:20:00", "continued": False},
]

ENVELOPE = {"result": {"state": "Completed", "result": {
    "model": "jev-test",
    "answers": {
        "leader_nextday_continue": {"type": "choice", "choice": "mid_45_65",
                                    "probabilities": {"mid_45_65": 0.55}},
        "catalyst_stage": {"type": "choice", "choice": "new_today"},
    },
    "usage": {"total_tokens": 1234}}}, "success": True}


@pytest.fixture
def env(monkeypatch):
    """默认把 runner 打桩成零网络零模型，并记录 dispatch 调用次数。

    返回 (calls, db)：db 是**同一个** FakeDb 实例（`_db` 每次调用必须返回同一份，否则写入被丢）。
    """
    calls: list[tuple] = []
    db = FakeDb()

    def fake_dispatch(narrative, questions):
        calls.append((narrative, questions))
        return ENVELOPE, 12

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    monkeypatch.setattr(L, "_db", lambda: db)
    monkeypatch.setattr(L, "leaders_for", lambda db, date, dataset_id=None: (
        [dict(r) for r in ROWS], {"thsPoolFound": True}))
    monkeypatch.setattr(L, "baseline_rows_for", lambda db, date, **kw: (
        [dict(r) for r in BASELINE], {"start": "2026-07-16", "end": "2026-10-16", "rows": 6}))
    monkeypatch.setattr("backend.operations.jev_label_jiuyan.market_facts_line",
                        lambda db, date, dataset_id=None: "涨停 46 家（30 分位）")
    return calls, db


def test_estimate_tokens_is_range_with_upper_bound_guard():
    est = L.estimate_tokens(1000)
    assert est["low"] < est["high"] == est["budgetGuard"]
    assert est["low"] == int(1000 * L.TOKENS_PER_CHAR_LOW) + L.TOKENS_FIXED_LOW


def test_dry_run_makes_no_call_and_writes_nothing(env, capsys):
    calls, db = env
    out = L.run("2026-10-19", dry_run=True)
    assert calls == [], "dry-run 绝不允许调用 jev"
    assert out["leaders"] == 2 and out["todo"] == 2 and out["charsTotal"] > 0
    assert out["estimatedTokensBudgetGuard"] > 0
    printed = capsys.readouterr().out
    assert "零 jev 调用（未花 token）" in printed
    assert "待判龙头：大业股份（603278）" in printed
    assert "结构基线（口径=触板−THS炸板二分 + 真连板" in printed
    assert "【题材证据 · 韭研产业树 + 投资日历】" in printed


def test_run_without_confirm_budget_is_blocked(env):
    calls, _db = env
    with pytest.raises(SystemExit) as e:
        L.run("2026-10-19")
    assert "预算护栏" in str(e.value) and "2 次" in str(e.value)
    assert calls == [], "预算未确认时不得发生任何调用"


def test_run_writes_docs_and_is_idempotent(env):
    calls, db = env
    out = L.run("2026-10-19", confirm_budget=True)
    assert len(calls) == 2 and out["labeled"] == 2 and out["ok"] == 2
    assert out["tokensUsed"] == 1234 * 2
    col = db[L.COLLECTION]
    doc = col.docs["2026-10-19:603278"]
    assert doc["origin"] == L.ORIGIN and doc["board"] == "机器人"
    assert doc["questionSetVersion"] == "v2"
    assert doc["questionSetHash"] == "985c529fded7"   # v2 换代（v1=ff010c50200e 保留在预登记文档）
    # v2 确定性门：测试库无题材语料（evidenceMissing=corpus_not_collected）→ 概率题被强制 insufficient，
    # 但模型原答必须留档（modelAnswers/gate），且催化题不受影响
    assert doc["answers"]["leader_nextday_continue"]["choice"] == "insufficient"
    assert doc["leaderNextdayContinue"] == "insufficient"
    assert doc["modelAnswers"]["leader_nextday_continue"]["choice"] == "mid_45_65"
    assert doc["gate"]["applied"] is True and doc["gate"]["reason"] == "corpus_not_collected"
    assert doc["gate"]["modelChoice"] == "mid_45_65"
    assert doc["catalystStage"] == "new_today"
    assert doc["status"] == "ok" and doc["usage"] == {"total_tokens": 1234}
    assert doc["model"] == "jev-test"
    assert doc["leaderNextdayProbabilities"] == {"insufficient": 1.0}
    assert doc["evidenceMissing"] is True and doc["evidenceMissingReason"] == "corpus_not_collected"
    assert doc["outcomeSealedNextDay"] is None, "label 时点结局未知，字段留空由评估脚本回填"
    assert doc["baselineMeta"]["rows"] == 6
    # 幂等：再跑一次全部跳过，零新调用
    calls.clear()
    again = L.run("2026-10-19", confirm_budget=True)
    assert calls == [] and again["labeled"] == 0 and again["alreadyLabeled"] == 2


def test_force_relabels(env):
    calls, _db = env
    L.run("2026-10-19", confirm_budget=True)
    calls.clear()
    out = L.run("2026-10-19", confirm_budget=True, force=True)
    assert len(calls) == 2 and out["labeled"] == 2


def test_missing_ths_pool_is_fail_visible(env, monkeypatch, capsys):
    calls, _db = env
    monkeypatch.setattr(L, "leaders_for", lambda db, date, dataset_id=None: (None, {}))
    out = L.run("2026-10-19", dry_run=True)
    assert out["ok"] is False and out["error"]["code"] == "ths_pool_missing"
    assert "THS 封板池缺失" in capsys.readouterr().out
    assert calls == []


def test_degraded_call_is_recorded_not_swallowed(env, monkeypatch):
    calls, db = env
    monkeypatch.setattr(L, "_dispatch_jev", lambda n, q: (
        {"result": {"state": "Completed", "result": {"answers": {}}}}, 5))
    out = L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert out["degraded"] == 2 and doc["status"] == "degraded"
    assert doc["leaderNextdayContinue"] is None and doc["responseRaw"] is not None


def test_baseline_window_excludes_current_day(monkeypatch):
    """结构基线样本窗口右边界=当日（含"前一日龙头→今日结局"），不含当日龙的次日结局。"""
    seen: dict = {}

    def fake_build_rows(db, start, end, dataset_id=None):
        seen["start"], seen["end"] = start, end
        return {"rows": [{"continued": True}], "skipped": {}, "dates": [start, end]}

    monkeypatch.setattr(L, "build_rows", fake_build_rows)
    monkeypatch.setattr(L, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: ["2026-10-15", "2026-10-16"])
    _, meta = L.baseline_rows_for(FakeDb(), "2026-10-19", window=60)
    assert seen == {"start": "2026-10-15", "end": "2026-10-19"}, seen
    assert meta["end"] == "2026-10-16", "披露的窗口右边界=前一日，不以当日结局当样本"
    assert meta["rows"] == 1


def test_no_gate_when_evidence_present(env, monkeypatch):
    """有催化正文（哪怕陈旧）→ 不过门，模型档位原样落库（stale 是证据，不是缺失）。"""
    calls, db = env
    real_build = L.build_one

    def fake_build_one(db_, date, row, rows_baseline, dataset_id, market_line):
        built = real_build(db_, date, row, rows_baseline, dataset_id, market_line)
        built["evidence"] = {"state": {"ok": True}, "events": [], "evidenceMissing": False,
                             "evidenceMissingReason": None}
        return built

    monkeypatch.setattr(L, "build_one", fake_build_one)
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["gate"]["applied"] is False
    assert doc["leaderNextdayContinue"] == "mid_45_65"
    assert doc["modelAnswers"] == doc["answers"], "不过门时两者应一致（不是两套数）"


def test_channel_unreachable_aborts_early_not_all_calls(env, monkeypatch):
    """通道不可达（连续零 usage 失败）→ 快速中止并结构化报错，不把 9 次空转当"跑完"。

    2026-10-20 实测：本地代理 127.0.0.1:7890 挂 → 9/9 degraded、usage 0；旧行为会把
    "通道挂了" 伪装成 "9 只都降级了"。
    """
    calls, _db = env
    tried: list = []

    def fake_dispatch(n, q):
        tried.append((n, q))
        return {"success": False, "errors": [{"message": "network: URLError: WinError 10061"}]}, 5
    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    out = L.run("2026-10-19", confirm_budget=True)
    assert len(tried) == L._TRANSPORT_FAIL_ABORT, "应在连续失败阈值处停，不跑满全部龙头"
    assert out["ok"] == 0 and out["aborted"] == "channel_unreachable"
    assert out["error"]["code"] == "jev_channel_unreachable"
    assert out["remaining"] == 0 and out["tokensUsed"] == 0


def test_single_transient_failure_does_not_abort(env, monkeypatch):
    """单次抖动（夹在成功之间）不得触发中止。"""
    calls, _db = env
    seq = iter([({"success": False, "errors": [{"message": "timeout"}]}, 5), (ENVELOPE, 12)])

    def fake_dispatch(n, q):
        calls.append((n, q))
        return next(seq)
    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    out = L.run("2026-10-19", confirm_budget=True)
    assert out.get("aborted") is None and out["ok"] == 1 and out["degraded"] == 1
    assert len(calls) == 2


# 22 次真实调用实测账（2026-10-19 v1 13 次 + 2026-10-20 v2 9 次）；
# (narrative 字符数, usage 总 token) —— 从库中 narrative 长度 × usage 反推，勿改。
_REAL_COST_LEDGER = [
    (715, 2068), (727, 2075), (728, 2078), (728, 2080), (751, 2015), (757, 2020),
    (760, 2023), (761, 2027), (889, 2146), (903, 2158), (972, 2291), (992, 2330),
    (1020, 2343), (1040, 2275), (1046, 2279), (1054, 2312), (1064, 2317), (1130, 2361),
    (1138, 2449), (1142, 2400), (1213, 2523), (1463, 2681),
]


def test_budget_guard_is_a_true_upper_bound_on_real_ledger():
    """护栏 = **上界**：22 条真实调用必须全部落在 [low, high] 内，且上界不虚胖（≤1.35×）。

    历史缺陷：固定开销 900 → 低估 16%；改 1,250 仍低估 3.9%（2026-10-20 实测 20,237 vs
    护栏 19,483）。用户批准的是「≤上界」，护栏一旦低于实耗即失效。
    """
    for chars, actual in _REAL_COST_LEDGER:
        est = L.estimate_tokens(chars)
        assert est["low"] <= actual <= est["high"], f"chars={chars} actual={actual} est={est}"
        assert est["high"] <= actual * 1.35, f"上界过松：chars={chars} {est['high']} vs {actual}"


def test_budget_guard_aggregates_over_leaders():
    """整日护栏 = 逐只上界之和（调度步据此对账），不是均值 × 只数。"""
    chars = [715, 1000, 1463]
    total = sum(L.estimate_tokens(c)["budgetGuard"] for c in chars)
    assert total == sum(int(c * L.TOKENS_PER_CHAR_HIGH) + L.TOKENS_FIXED_HIGH for c in chars)
    assert total > sum(a for c, a in _REAL_COST_LEDGER if c in chars)
