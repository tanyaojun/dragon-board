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

from types import SimpleNamespace

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

    def find_one(self, query=None, projection=None):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (query or {}).items()):
                # 投影忽略（返回整文档）：点路径投影（fields.stocks.code）不做嵌套裁剪，
                # 测试只依赖字段存在性，超集无害
                return dict(d)
        return None

    def update_many(self, flt, update):
        """reconcile 用（$ne/$in/$nin 富匹配；只模拟 $set）。"""
        n = 0
        for d in self.docs.values():
            ok = True
            for k, cond in (flt or {}).items():
                val = d.get(k)
                if isinstance(cond, dict):
                    for op, arg in cond.items():
                        if op == "$ne" and val == arg:
                            ok = False
                        elif op == "$in" and val not in arg:
                            ok = False
                        elif op == "$nin" and val in arg:
                            ok = False
                        elif op == "$exists" and bool(arg) != (val is not None):
                            # P2-3（review）：真 Mongo 语义对齐——缺失键与显式 None 在
                            # 本夹具均表现为 get→None（生产已不写 None 键，P2-5）
                            ok = False
                elif val != cond:
                    ok = False
                if not ok:
                    break
            if ok:
                d.update(update.get("$set") or {})
                n += 1
        return SimpleNamespace(modified_count=n)


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


@pytest.fixture(autouse=True)
def _no_calendar_network(monkeypatch):
    """前向交易日轴（2026-10-24c）日历源全程打桩：测试零网络、零日历缓存文件写入。

    weekday 启发（周一~五=交易日）在本夹具内是确定函数；需要测「非 bridge 源披露」
    的用例自行再覆盖 `trading_calendar.is_trading_day_cached`。
    """
    import backend.snapshot_collector.trading_calendar as _tc

    monkeypatch.setattr(_tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "weekday"))
    L._FWD_AXIS_CACHE.clear()
    yield
    L._FWD_AXIS_CACHE.clear()


ROWS = [
    {"date": "2026-10-19", "board": "机器人", "code": "603278", "name": "大业股份",
     "streak": 3, "time": "09:25:00", "boardN": 5, "othersN": 4, "ladderFollowers": 1,
     "prevPeers": 2, "prevBoardN": 3, "peerCodes": ["a", "b"],
     # 2026-10-24c 板面扩容字段（day_leader_rows 直出）；2026-10-24d 增 prevStill（同名仍封）
     "prevTotal": 6, "prevStill": 3, "zhabanN": 2, "prevZhabanN": 1,
     "ladderShape": {"first": 3, "two": 1, "threePlus": 1, "unknown": 0},
     "secondStreak": 2},
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
        "theme_speculation_depth": {"type": "choice", "choice": "fermenting"},
        "theme_continuation": {"type": "choice", "choice": "strong_extend"},
        "leader_nextday_continue": {"type": "choice", "choice": "mid_45_65",
                                    "probabilities": {"mid_45_65": 0.55}},
        "leader_headroom": {"type": "choice", "choice": "space_2plus"},
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
    # KPL 原料（强度/直播/龙虎榜）零网络打桩：fail-visible 行文，不影响判定链断言
    monkeypatch.setattr(L, "fetch_plate_strength",
                        lambda date: {"ok": False, "reason": "test_disabled"})
    monkeypatch.setattr(L, "fetch_live_commentary",
                        lambda st=60: {"ok": False, "reason": "test_disabled"})
    monkeypatch.setattr(L, "fetch_lhb_facts",
                        lambda date: {"ok": False, "date": date,
                                      "reason": "test_disabled"})
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
    assert "结构基线：" in printed, "2026-10-30g：口径头删（用户裁决）"
    assert "【题材证据】" in printed


def test_run_without_confirm_budget_is_blocked(env):
    calls, _db = env
    with pytest.raises(SystemExit) as e:
        L.run("2026-10-19")
    assert "预算护栏" in str(e.value) and "4 次" in str(e.value), "v12 拆题：2 龙头 doc + 2 板块 doc"
    assert calls == [], "预算未确认时不得发生任何调用"


def test_run_writes_docs_and_is_idempotent(env):
    calls, db = env
    out = L.run("2026-10-19", confirm_budget=True)
    # v12 A2 拆题：2 龙头 doc + 2 板块 doc = 4 次调用
    assert len(calls) == 4 and out["labeled"] == 4 and out["ok"] == 4
    assert out["sectorDocs"] == 2
    assert out["tokensUsed"] == 1234 * 4
    col = db[L.COLLECTION]
    doc = col.docs["2026-10-19:603278"]
    assert doc["origin"] == L.ORIGIN and doc["board"] == "机器人"
    assert doc["docKind"] == "leader" and "segment" not in doc  # 夹具行无 segment → 不写键（P2-5）
    assert doc["questionSetVersion"] == "v16"
    assert doc["questionSetHash"] == "7cec6926166d"   # v16 封板质量判据（v1-v15 hash 留档在预登记文档）
    assert doc["ammoVersion"] == "2026-11-08b"   # 2026-11-08b：封板质量语料行 + 题面 v16
    # v2 确定性门：测试库无题材语料（evidenceMissing=corpus_not_collected）→ 概率题被强制 insufficient，
    # 但模型原答必须留档（modelAnswers/gate），且催化题不受影响
    assert doc["answers"]["leader_nextday_continue"]["choice"] == "insufficient"
    assert doc["leaderNextdayContinue"] == "insufficient"
    assert doc["modelAnswers"]["leader_nextday_continue"]["choice"] == "mid_45_65"
    assert doc["gate"]["applied"] is True and doc["gate"]["reason"] == "corpus_not_collected"
    assert doc["gate"]["modelChoice"] == "mid_45_65"
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
    assert len(calls) == 4 and out["labeled"] == 4


def test_rerun_preserves_backfilled_outcome(env):
    """复跑安全（2026-10-26 用户报障）：replace_one 整文档覆写曾把已回填的 outcome* 抹掉
    （页面【复跑】后结局列消失，要等下一条挂链自愈）——重建文档必须把旧档 outcome*
    原样带走（结局是股票事实，与模型答案无关，保留恒正确）。"""
    calls, db = env
    L.run("2026-10-19", confirm_budget=True)
    col = db[L.COLLECTION]
    # 模拟结算脚本已回填 T+1 结局与 T+2 溢价
    col.docs["2026-10-19:603278"].update({
        "outcomeSealedNextDay": True,
        "outcomeBoardNNextDay": 5,
        "outcomeMeta": {"nextDate": "2026-10-20"},
        "outcomeDay2": {"date": "2026-10-21", "openPct": 2.5, "closePct": 1.3},
    })
    calls.clear()
    out = L.run("2026-10-19", confirm_budget=True, force=True)
    assert out["labeled"] == 4 and len(calls) == 4, "force 复跑照常重新调用模型"
    doc = col.docs["2026-10-19:603278"]
    assert doc["outcomeSealedNextDay"] is True, "复跑不得抹掉已回填结局"
    assert doc["outcomeDay2"]["closePct"] == 1.3, "outcome* 全键保留（含后日溢价）"
    assert doc["questionSetVersion"] == "v16", "outcome 之外字段照常重建"


def test_missing_ths_pool_is_fail_visible(env, monkeypatch, capsys):
    calls, _db = env
    monkeypatch.setattr(L, "leaders_for", lambda db, date, dataset_id=None: (None, {}))
    out = L.run("2026-10-19", dry_run=True)
    assert out["ok"] is False and out["error"]["code"] == "ths_pool_missing"
    assert "THS 封板池缺失" in capsys.readouterr().out
    assert calls == []


def test_degraded_call_is_recorded_not_swallowed(env, monkeypatch):
    """degraded（模型返答缺题）逐条落库不吞噬；注意 v12 拆题下板块 doc 先于龙头 doc，
    且 degraded 零 usage 连续两次触发通道中止——前 2 次成功、后 2 次 degraded，
    龙头 doc 写完后中止（abort 不回滚已写档）。"""
    import itertools
    calls, db = env
    seq = itertools.chain(itertools.repeat((ENVELOPE, 12), 2),
                          itertools.repeat(({"result": {"state": "Completed",
                                                    "result": {"answers": {}}}}, 5)))
    monkeypatch.setattr(L, "_dispatch_jev", lambda n, q: next(seq))
    out = L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert out["ok"] == 2 and out["degraded"] == 2
    assert doc["status"] == "degraded"
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
    real_build_sector = L.build_sector_one

    def fake_build_one(db_, date, row, rows_baseline, dataset_id, market_line,
                       board_history=None, **kwargs):
        built = real_build(db_, date, row, rows_baseline, dataset_id, market_line,
                           board_history=board_history, **kwargs)
        built["evidence"] = {"state": {"ok": True}, "events": [], "evidenceMissing": False,
                             "evidenceMissingReason": None}
        return built

    def fake_build_sector_one(db_, date, board_rows, rows_baseline, dataset_id,
                              market_line, board_history=None, **kwargs):
        built = real_build_sector(db_, date, board_rows, rows_baseline, dataset_id,
                                  market_line, board_history=board_history, **kwargs)
        built["evidence"] = {"state": {"ok": True}, "events": [], "evidenceMissing": False,
                             "evidenceMissingReason": None}
        return built

    monkeypatch.setattr(L, "build_one", fake_build_one)
    monkeypatch.setattr(L, "build_sector_one", fake_build_sector_one)
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["gate"]["applied"] is False
    assert doc["leaderNextdayContinue"] == "mid_45_65"
    assert doc["modelAnswers"] == doc["answers"], "不过门时两者应一致（不是两套数）"
    # v12 拆题：个股级 doc 只落续板/空间；深度/延续在板块级 doc
    assert doc["themeSpeculationDepth"] is None and doc["themeContinuation"] is None
    assert doc["leaderHeadroom"] == "space_2plus"
    sec = db[L.COLLECTION].docs["2026-10-19:board:机器人"]
    assert sec["docKind"] == "sector" and sec["gate"]["applied"] is False
    assert sec["themeSpeculationDepth"] == "fermenting"
    assert sec["themeContinuation"] == "strong_extend"
    assert sec["leaderNextdayContinue"] is None


def test_anchor_deviation_audit_unit():
    """P1-1 改道（2026-11-07）：jev 平台 answer schema 服务端锁死（5 探针实证），
    模型自证 reason 不可行 → 程序侧读叙事基线行计算偏离。规则①同口径：
    最细同桶样本<8 回退按连板高度桶；偏离≥1 档打 deviation_from_anchor。"""
    base = ("结构基线：同桶[streak2|n3-4|early] 历史次日连板率 61.1%（36 样本）；"
            "按连板高度[2] 42.8%（180 样本）；总体 33.9%（740 样本）")
    # 同档（61.1% ∈ mid 桶区间）：不标
    assert L._anchor_deviation_audit(base, "mid_45_65") == (None, None)
    # 偏离一档：打标 + note 带中枢读数
    flag, note = L._anchor_deviation_audit(base, "low_25_45")
    assert flag == "deviation_from_anchor" and "61.1%" in note and "同桶" in note
    # 最细桶样本<8 → 回退按连板高度桶（42.8% ∈ low，mid 偏离一档）
    low_n = base.replace("61.1%（36 样本）", "61.1%（5 样本）")
    flag2, note2 = L._anchor_deviation_audit(low_n, "mid_45_65")
    assert flag2 == "deviation_from_anchor" and "按连板高度" in note2 and "42.8%" in note2
    # 回退后同档不标
    assert L._anchor_deviation_audit(low_n, "low_25_45") == (None, None)
    # 无基线行 / insufficient / 未答：不标
    assert L._anchor_deviation_audit("无基线行叙事", "low_25_45") == (None, None)
    assert L._anchor_deviation_audit(base, "insufficient") == (None, None)
    assert L._anchor_deviation_audit(base, None) == (None, None)


def test_reason_passthrough_and_human_mark_preserved(env, monkeypatch):
    """P1-1 改道：answerReasons 容错透传保留（平台未来放开零改动）；本轮无偏离标记时
    旧档人工标记（v12 两案）防抹；协议注已撤（传输 narrative 与落库一致）。"""
    calls, db = env
    monkeypatch.setattr(L, "apply_evidence_gate",
                        lambda answers, evidence, keys=None: (
                            answers, {"applied": False, "reason": None}))
    env_reason = {**ENVELOPE, "result": {**ENVELOPE["result"], "result": {
        **ENVELOPE["result"]["result"],
        "answers": {k: {**v, "reason": "基线 41.6% 同档"}
                   for k, v in ENVELOPE["result"]["result"]["answers"].items()}}}}

    def fake_dispatch(narrative, questions):
        calls.append((narrative, questions))
        return env_reason, 12

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    monkeypatch.setattr(L, "_anchor_deviation_audit", lambda n, c: (None, None))
    db[L.COLLECTION].docs["2026-10-19:603278"] = {
        "_id": "2026-10-19:603278", "status": "pending",
        "auditFlag": "v12_case_a", "auditNote": "人工两案标记"}
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["auditFlag"] == "v12_case_a" and doc["auditNote"] == "人工两案标记"
    assert doc["answerReasons"]["leader_nextday_continue"] == "基线 41.6% 同档"
    assert doc["answerReasons"]["leader_headroom"] == "基线 41.6% 同档"
    assert "【输出要求（协议层" not in calls[0][0], "无效协议注已撤（5 探针实证）"


def test_reason_present_no_flag_and_human_mark_preserved(env, monkeypatch):
    """P1-1：模型附 reason → answerReasons 落库、auditFlag 不标；旧档人工标记
    （v12 两案）在本轮无缺失时原样带走防抹。"""
    calls, db = env
    monkeypatch.setattr(L, "apply_evidence_gate",
                        lambda answers, evidence, keys=None: (
                            answers, {"applied": False, "reason": None}))
    env_reason = {**ENVELOPE, "result": {**ENVELOPE["result"], "result": {
        **ENVELOPE["result"]["result"],
        "answers": {k: {**v, "reason": "基线 41.6% 同档"}
                   for k, v in ENVELOPE["result"]["result"]["answers"].items()}}}}

    def fake_dispatch(narrative, questions):
        calls.append((narrative, questions))
        return env_reason, 12

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    # 旧档：人工标记 + 未完成 status（不挡 todo）
    db[L.COLLECTION].docs["2026-10-19:603278"] = {
        "_id": "2026-10-19:603278", "status": "pending",
        "auditFlag": "v12_case_a", "auditNote": "人工两案标记"}
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    # 本轮无缺失：人工标记防抹（v12 两案语义）；瞬时 missing_reason 不残留
    assert doc["auditFlag"] == "v12_case_a" and doc["auditNote"] == "人工两案标记"
    assert doc["answerReasons"]["leader_nextday_continue"] == "基线 41.6% 同档"
    assert doc["answerReasons"]["leader_headroom"] == "基线 41.6% 同档"


def test_stale_transient_audit_flags_cleared_on_clean_rerun(env, monkeypatch):
    """P1-1 改道：旧档瞬时机审标记（missing_reason/deviation_from_anchor）+ 本轮无标记
    → 清除不残留；人工标记才防抹。"""
    calls, db = env
    monkeypatch.setattr(L, "apply_evidence_gate",
                        lambda answers, evidence, keys=None: (
                            answers, {"applied": False, "reason": None}))
    env_reason = {**ENVELOPE, "result": {**ENVELOPE["result"], "result": {
        **ENVELOPE["result"]["result"],
        "answers": {k: {**v, "reason": "基线 41.6% 同档"}
                   for k, v in ENVELOPE["result"]["result"]["answers"].items()}}}}

    def fake_dispatch2(narrative, questions):
        calls.append((narrative, questions))
        return env_reason, 12

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch2)
    db[L.COLLECTION].docs["2026-10-19:603278"] = {
        "_id": "2026-10-19:603278", "status": "pending",
        "auditFlag": "missing_reason", "auditNote": "缺 reason: leader_headroom"}
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["auditFlag"] is None and doc["auditNote"] is None
    # deviation_from_anchor 同属瞬时机审标记
    db[L.COLLECTION].docs["2026-10-19:603278"] = {
        "_id": "2026-10-19:603278", "status": "pending",
        "auditFlag": "deviation_from_anchor", "auditNote": "模型 low vs 同桶 61.1%"}
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["auditFlag"] is None and doc["auditNote"] is None


def test_build_one_and_sector_wire_lhb_line():
    """龙虎榜事实行（AMMO 2026-10-30a）：个股级=待判龙一优先+板内封板成员，
    板块级=双龙一轨别身位；lhb_facts=None 不出行（旧行为不变）；fetch 失败 fail-visible。"""
    facts = {"ok": True, "stocks": [
        {"code": "603278", "name": "大业股份", "main_net_yuan": 52000000,
         "main_buy_yuan": 90000000, "main_sell_yuan": -38000000,
         "reason": "日涨幅偏离值达7%的证券"},
        {"code": "002639", "name": "雪人股份", "main_net_yuan": None,
         "main_buy_yuan": None, "main_sell_yuan": None, "reason": ""},
    ]}
    row = dict(ROWS[0], boardCodes=["603278", "002639"])
    built = L.build_one(FakeDb(), "2026-10-19", row, BASELINE,
                        market_line="涨停 46 家", lhb_facts=facts)
    n = built["narrative"]
    assert "待判龙一 大业股份（603278）：主力净额 0.52亿" in n
    assert "相关个股 雪人股份（002639）：主力净额 --" in n
    assert n.index("个股打标交叉") < n.index("龙虎榜：") < n.index("【题材证据")
    # 未传入（旧行为）→ 不出行
    built0 = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), BASELINE,
                         market_line="涨停 46 家")
    assert "龙虎榜" not in built0["narrative"]
    # 板块级：双龙一轨别身位；不在榜的龙一不出现
    brows = [dict(ROWS[0], segment="main", boardCodes=["603278", "002639"]),
             dict(ROWS[1], segment="growth")]
    built_s = L.build_sector_one(FakeDb(), "2026-10-19", brows, BASELINE,
                                 market_line="涨停 46 家", lhb_facts=facts)
    ns = built_s["narrative"]
    assert "主板龙一 大业股份（603278）" in ns
    assert "雪人股份（002639）" in ns and "双创龙一 亚邦股份（603188）：" not in ns, "不在榜的龙一不出现在龙虎榜行（结构行身位不受影响）"
    # 取数失败 → fail-visible 行（不伪装无上榜）
    built_f = L.build_one(FakeDb(), "2026-10-19", row, BASELINE,
                          market_line="涨停 46 家",
                          lhb_facts={"ok": False, "reason": "fetch_failed: x"})
    assert "--，榜单拉取失败 x" in built_f["narrative"], "2026-10-30g+：工程词中文化"


def test_build_one_wires_history_and_headroom_anchor():
    """S1/Q1（2026-10-24b）：家数序列与空间锚行进叙事；行序=结构→基线→锚→证据块。

    历史样本行缺 code/date（旧形状）→ 锚 fail-safe 不出；board_history 算过但该板块
    无收录 → 「不可考」文案（不伪装趋势）。
    """
    rows_baseline = [
        {"code": "603278", "date": "2026-10-15", "streak": 3, "boardN": 5,
         "time": "09:20:00", "continued": True},
        {"code": "603278", "date": "2026-10-16", "streak": 4, "boardN": 5,
         "time": "09:25:00", "continued": False},
        {"code": "603279", "date": "2026-10-16", "streak": 1, "boardN": 2,
         "time": "13:20:00", "continued": False},
    ]
    built = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), rows_baseline,
                        market_line="涨停 46 家",
                        board_history={"机器人": [("2026-10-15", 4), ("2026-10-16", 3),
                                                ("2026-10-17", 5)]})
    n = built["narrative"]
    assert "近 3 日该板块封板家数：10-15 4 · 10-16 3 · 10-17 5" in n, \
        "2026-10-30d：序列 ≥3 日才出行（fixture 由 2 日扩为 3 日）"
    assert "空间锚" in n and "总体 再走≥1板率" in n   # 2026-10-26a 每档基率化
    # 2026-10-24c 三行：前向轴紧跟盘面行、梯队/炸板面紧跟结构行；昨日口径=总数−仍封出断板
    # （2026-10-19 是周一；weekday 桩=周一~五交易日）
    assert "交易日轴（前向）：下一交易日 2026-10-20（周二） · 下下交易日 2026-10-21（周三）" \
        "（日历源 weekday，节假日顺延未经验证）" in n
    assert "昨日该板块封板 6 只，今日仍封 3 只" in n, "2026-10-30d：断板=差值可推导不复述"
    assert "板块梯队形态：首板 3 家 / 2板 1 家 / 3板+ 1 家；龙头 3 板，次高 2 板（领先 +1）" in n
    assert "板内炸板面：今日触板未封 2 家（昨日 1 家）" in n
    i_struct, i_lad = n.index("板块「机器人」今日封板"), n.index("板块梯队形态")
    i_zhaban, i_base = n.index("板内炸板面"), n.index("结构基线")
    i_anchor, i_ev = n.index("空间锚"), n.index("【题材证据")
    assert i_struct < i_lad < i_zhaban < i_base < i_anchor < i_ev
    rows0 = dict(ROWS[0])
    rows0["ladderShape"] = None   # 旧形状行：两行 None 不出行，不报错
    rows0["zhabanN"] = None
    built_legacy = L.build_one(FakeDb(), "2026-10-19", rows0, rows_baseline,
                               market_line="涨停 46 家", board_history={})
    assert "板块梯队形态" not in built_legacy["narrative"]
    assert "板内炸板面" not in built_legacy["narrative"]
    # 旧形状基线（无 code/date）→ 锚不出；空 history dict → 不可考文案
    built2 = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), BASELINE,
                         market_line="涨停 46 家", board_history={})
    assert "空间锚" not in built2["narrative"]
    assert "家数序列不可考" in built2["narrative"]


def test_build_one_driver_cross_join_and_fail_visible():
    """打标交叉行（2026-10-27b）：final 优先 midday 兜底、哨兵行排除、无记录出
    fail-visible 缺席行；driverCross 源审计随 built 返回（落库由 run 路径断言）。"""
    db = FakeDb()
    dcol = db[L.DRIVER_LABEL_COLLECTION]
    dcol.docs["x1"] = {"tradingDate": "2026-10-19", "code": "603278",
                       "labelSlot": "midday", "questionSetVersion": "v4.0",
                       "label": "capital_flow", "catalystDepth": "core_main_business",
                       "freshness": "fresh_catalyst", "buySideLogic": "high_board_relay",
                       "computedAt": "2026-10-27T12:35:14"}
    built = L.build_one(db, "2026-10-19", dict(ROWS[0]), BASELINE, market_line="涨停 46 家")
    assert "个股打标交叉（午盘槽）：" in built["narrative"], \
        "2026-10-30d：工程注记删，版本+槽位保留"
    assert built["driverCross"] == {"found": True, "labelSlot": "midday",
                                    "questionSetVersion": "v4.0"}
    # final 优先于 midday（同日两槽并存取 final）
    dcol.docs["x2"] = {"tradingDate": "2026-10-19", "code": "603278",
                       "labelSlot": "final", "questionSetVersion": "v3.1",
                       "label": "policy", "computedAt": "2026-10-27T16:19:04"}
    built2 = L.build_one(db, "2026-10-19", dict(ROWS[0]), BASELINE, market_line="涨停 46 家")
    assert "收盘槽" in built2["narrative"] and built2["driverCross"]["labelSlot"] == "final"
    # phase_band_daily 日级哨兵不充当个股交叉源
    dcol.docs["x3"] = {"tradingDate": "2026-10-19", "code": "603278",
                       "labelSlot": "final", "origin": "phase_band_daily",
                       "label": "policy", "computedAt": "2026-10-27T17:00:00"}
    built2b = L.build_one(db, "2026-10-19", dict(ROWS[0]), BASELINE, market_line="涨停 46 家")
    assert built2b["driverCross"]["labelSlot"] == "final" \
        and "个股打标交叉（收盘槽）" in built2b["narrative"], "2026-10-30f：题集版本披露删，槽位区分保留"
    # 无任何打标行 → fail-visible 缺席行（不伪装方向性结论）
    built3 = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), BASELINE,
                         market_line="涨停 46 家")
    assert "个股打标交叉：无当日个股打标记录" in built3["narrative"], "2026-10-30g+：注删"
    assert built3["driverCross"] == {"found": False, "labelSlot": None,
                                     "questionSetVersion": None}


def test_label_one_persists_expanded_structure_fields(env):
    """2026-10-24c 板面扩容字段随 structure 落库（审计与前端可回读，不只在叙事里）。"""
    calls, db = env
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    st = doc["structure"]
    assert st["prevTotal"] == 6 and st["prevStill"] == 3
    assert st["zhabanN"] == 2 and st["prevZhabanN"] == 1
    assert st["secondStreak"] == 2
    assert st["ladderShape"] == {"first": 3, "two": 1, "threePlus": 1, "unknown": 0}
    # 无扩容字段的行（化工/旧形状）→ 字段为 None，不报错不伪造
    doc2 = db[L.COLLECTION].docs["2026-10-19:603188"]
    assert doc2["structure"]["ladderShape"] is None
    assert doc2["structure"]["zhabanN"] is None
    # 2026-10-27 空间龙一规则：gain10/leaderSealedToday 随 structure 落库
    #（env 夹具的 ROWS 无新字段 → None 如实；space_mode 生产的真实值由
    # test_day_leader_rows_space_mode_unsealed_leader 锁定）
    assert "gain10" in st and "leaderSealedToday" in st
    # 打标交叉源审计（AMMO 2026-10-27b）：测试库无打标行 → found=False 如实落库
    assert doc["driverCross"] == {"found": False, "labelSlot": None,
                                  "questionSetVersion": None}
    assert "个股打标交叉：无当日个股打标记录" in doc["narrative"]


def test_forward_date_axis_line_sources_and_fail_visible(monkeypatch):
    """前向交易日轴（2026-10-24c）：bridge 源干净出轴；非 bridge 源显式标注未验证；
    全程无交易日 → 不可算（不猜）。"""
    import datetime as dt

    import backend.snapshot_collector.trading_calendar as tc

    L._FWD_AXIS_CACHE.clear()
    # bridge 源：周五 2026-10-23 → 下周一/周二
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "bridge"))
    line = L.forward_date_axis_line("2026-10-23")
    assert line == "交易日轴（前向）：下一交易日 2026-10-26（周一） · 下下交易日 2026-10-27（周二）"
    # weekday 源 → 必须带未验证披露（fail-visible：长假会被启发误判）
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "weekday"))
    L._FWD_AXIS_CACHE.clear()
    line2 = L.forward_date_axis_line("2026-10-23")
    assert "2026-10-26（周一）" in line2
    assert "（日历源 weekday，节假日顺延未经验证）" in line2
    # 全 False（异常场景）→ 不可算
    monkeypatch.setattr(tc, "is_trading_day_cached", lambda d: (False, "bridge"))
    L._FWD_AXIS_CACHE.clear()
    assert L.forward_date_axis_line("2026-10-23") == \
        "交易日轴（前向）：不可算（日历源异常，fail-visible）"
    # 非法日期 → 不可算，不抛
    L._FWD_AXIS_CACHE.clear()
    assert "不可算" in L.forward_date_axis_line("not-a-date")
    # 缓存生效：第一次正常算，第二次换「不许调用」桩仍直接命中缓存
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "bridge"))
    L._FWD_AXIS_CACHE.clear()
    first = L.forward_date_axis_line("2026-10-23")
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (_ for _ in ()).throw(AssertionError("should not call")))
    second = L.forward_date_axis_line("2026-10-23")
    assert first == second
    # 2026-10-24d review 处置：非 bridge 源结果**不缓存**——bridge 恢复后重算即升级，
    # 不把 weekday 启发行固化整天
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "weekday"))
    L._FWD_AXIS_CACHE.clear()
    degraded = L.forward_date_axis_line("2026-10-23")
    assert "节假日顺延未经验证" in degraded
    monkeypatch.setattr(tc, "is_trading_day_cached",
                        lambda d: (d.weekday() < 5, "bridge"))
    upgraded = L.forward_date_axis_line("2026-10-23")
    assert "节假日顺延未经验证" not in upgraded, "降级结果不得命中缓存，bridge 恢复后必须重算"


def test_day_leader_rows_board_face_expansion(monkeypatch):
    """day_leader_rows 2026-10-24c 扩容：梯队形态/次高/炸板面/昨日总数（同名板块精确匹配）。"""
    import backend.operations.theme_leader_baseline as B
    import backend.operations.jev_label_jiuyan as J

    info_today = {"603278": {}, "603280": {},
                  "603281": {"zhaban": True}, "603282": {"zhaban": True}}
    info_prev = {"603278": {}, "603280": {}, "603285": {},
                 "603286": {"zhaban": True}}

    def fake_sealed(db, date, dataset_id=None):
        if date == "2026-10-19":
            return {"603278", "603280"}, info_today, {"thsPoolFound": True}
        return {"603278", "603280", "603285"}, info_prev, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db, date, dataset_id=None: {"603278": 3, "603280": 1})
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-19:final"},
        {"_id": "2026-10-19:final", "fields": [
            {"name": "机器人", "stocks": [
                {"code": "603278", "name": "大业", "time": "09:25"},
                {"code": "603280", "name": "乙", "time": "10:00"},
                {"code": "603281", "name": "炸甲", "time": "09:40"},
                {"code": "603282", "name": "炸乙", "time": "13:30"}]}]})
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-16:final"},
        {"_id": "2026-10-16:final", "fields": [
            {"name": "机器人", "stocks": [
                {"code": "603278", "name": "大业", "time": "09:25"},
                {"code": "603280", "name": "乙", "time": "10:00"},
                {"code": "603285", "name": "丙", "time": "11:00"},
                {"code": "603286", "name": "炸丙", "time": "14:00"}]}]})
    rows, _meta = B.day_leader_rows(db, "2026-10-19", prev_date="2026-10-16")
    row = next(r for r in rows if r["board"] == "机器人")
    assert row["boardN"] == 2 and row["zhabanN"] == 2
    assert row["ladderShape"] == {"first": 1, "two": 0, "threePlus": 1, "unknown": 0}
    assert row["secondStreak"] == 1
    assert row["prevTotal"] == 3 and row["prevZhabanN"] == 1
    assert row["prevBoardN"] == 2 and row["prevPeers"] == 1
    # 昨日 THS 池缺失 → 昨日统计不可考（不拿部分数据冒充）
    monkeypatch.setattr(B, "sealed_and_info",
                        lambda db_, date, dataset_id=None: (
                            ({"603278"}, info_today, {"thsPoolFound": True})
                            if date == "2026-10-19" else (None, {}, {"thsPoolFound": False})))
    rows2, _m2 = B.day_leader_rows(db, "2026-10-19", prev_date="2026-10-16")
    row2 = rows2[0]
    assert row2["prevTotal"] is None and row2["prevStill"] is None
    assert row2["prevZhabanN"] is None
    assert row2["prevBoardN"] is None and row2["prevPeers"] is None


def test_day_leader_rows_prev_still_same_board_scope(monkeypatch):
    """2026-10-24d（review P2 处置）：prevStill=昨日**同名板块**封板股今日仍封数。

    跨板块迁移场景：昨日机器人才封 1 只、化工封 2 只，今日 3 只全部并入机器人——
    成员口径 prevBoardN=3，断板 = prevTotal(1)−prevBoardN(3) = **-2**（旧实现的自相矛盾
    「昨日封 1 只今日仍封 3 只」）；同名口径 prevStill=1，断板 0，恒 ≥0。
    """
    import backend.operations.theme_leader_baseline as B
    import backend.operations.jev_label_jiuyan as J
    from backend.analysis.hotlist.theme_leader_ammo import structure_line

    info = {"603278": {}, "603280": {}, "603290": {}}

    def fake_sealed(db_, date, dataset_id=None):
        if date == "2026-10-19":
            return {"603278", "603280", "603290"}, info, {"thsPoolFound": True}
        return {"603278", "603280", "603290"}, info, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db_, date, dataset_id=None: {"603278": 3, "603280": 1, "603290": 2})
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-19:final"},
        {"_id": "2026-10-19:final", "fields": [
            {"name": "机器人", "stocks": [
                {"code": "603278", "name": "大业", "time": "09:25"},
                {"code": "603280", "name": "乙", "time": "10:00"},
                {"code": "603290", "name": "迁入股", "time": "11:00"}]}]})
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-16:final"},
        {"_id": "2026-10-16:final", "fields": [
            {"name": "机器人", "stocks": [
                {"code": "603278", "name": "大业", "time": "09:25"}]},
            {"name": "化工", "stocks": [
                {"code": "603280", "name": "乙", "time": "10:00"},
                {"code": "603290", "name": "迁入股", "time": "11:00"}]}]})
    rows, _m = B.day_leader_rows(db, "2026-10-19", prev_date="2026-10-16")
    row = next(r for r in rows if r["board"] == "机器人")
    assert row["prevTotal"] == 1 and row["prevStill"] == 1, "同名口径：昨日机器人的大业今日仍封"
    assert row["prevBoardN"] == 3, "成员口径含昨日化工迁入的 2 只（对照项，断板不再用它算）"
    line = structure_line(board="机器人", board_n=3,
                          leader={"name": "大业", "code": "603278", "streak": 3, "time": "09:25"},
                          followers_ge_ladder=2, prev_board_n=row["prevBoardN"],
                          prev_peers=row["prevPeers"], prev_total=row["prevTotal"],
                          prev_still=row["prevStill"])
    assert "昨日该板块封板 1 只，今日仍封 1 只" in line
    assert "断板" not in line and "今日仍封 3 只" not in line, "成员口径的负数/失真不得进叙事；断板不复述（2026-10-30d）"


# ── 单一龙头对账（2026-10-24 双龙头事故：10-23 机器人板块赛福天/大业股份并存） ──

def _seed_ghost(db):
    """10-23 机器人双行：赛福天=幽灵行（推导已不再指向），大业=现任。"""
    col = db[L.COLLECTION]
    col.replace_one({"_id": "2026-10-23:603028"},
                    {"_id": "2026-10-23:603028", "tradingDate": "2026-10-23",
                     "board": "机器人", "code": "603028", "name": "赛福天",
                     "status": "ok", "questionSetVersion": "v6"})
    col.replace_one({"_id": "2026-10-23:603278"},
                    {"_id": "2026-10-23:603278", "tradingDate": "2026-10-23",
                     "board": "机器人", "code": "603278", "name": "大业股份",
                     "status": "ok", "questionSetVersion": "v8"})


def test_fakedb_exists_operator_p2_3():
    """P2-3（review）：FakeDb 实现 $exists——legacy 对账分支（segment $exists:False）
    此前恒真，与真 Mongo 语义分叉零测试保障。"""
    col = FakeDb()["c"]
    col.replace_one({"_id": "a"}, {"_id": "a", "segment": "main"})
    col.replace_one({"_id": "b"}, {"_id": "b"})                    # 无 segment 键
    r = col.update_many({"segment": {"$exists": False}}, {"$set": {"x": 1}})
    assert r.modified_count == 1
    assert "x" not in col.docs["a"] and col.docs["b"]["x"] == 1
    r2 = col.update_many({"segment": {"$exists": True}}, {"$set": {"y": 1}})
    assert r2.modified_count == 1 and col.docs["a"]["y"] == 1 and "y" not in col.docs["b"]


def test_reconcile_legacy_boundary_not_autosuperseded():
    """P2-8（review，预登记 §8.1）：legacy 行（无 segment 键，$exists:False 真匹配）
    仅在板块已有分轨现任且 code 不在现任时退位；带 segment 的现任行永不被
    $exists:False 分支误伤（$exists 语义已对齐真 Mongo，P2-3）。"""
    db = FakeDb()
    col = db[L.COLLECTION]
    # 现任：v12 分轨 main 行（带 segment 键）
    col.replace_one({"_id": "2026-10-19:603278"}, {
        "_id": "2026-10-19:603278", "tradingDate": "2026-10-19", "code": "603278",
        "name": "大业", "board": "机器人", "segment": "main", "status": "ok",
        "questionSetVersion": "v12", "computedAt": "t1"})
    # legacy：无 segment 键、code 不在现任（应退位）
    col.replace_one({"_id": "2026-10-19:300006"}, {
        "_id": "2026-10-19:300006", "tradingDate": "2026-10-19", "code": "300006",
        "name": "legacy股", "board": "机器人", "status": "ok",
        "questionSetVersion": "v11", "computedAt": "t0"})
    rows = [{"date": "2026-10-19", "board": "机器人", "code": "603278", "name": "大业",
             "streak": 3, "segment": "main"}]
    rec = L.reconcile_superseded_leaders(db, "2026-10-19", rows)
    assert rec["superseded"] == 1
    assert col.docs["2026-10-19:300006"]["leaderSuperseded"] is True
    assert "leaderSuperseded" not in col.docs["2026-10-19:603278"],         "带 segment 的现任行不得被 $exists:False 分支误伤"


def test_reconcile_supersedes_ghost_rows_and_is_idempotent():
    """退位：同 board 下 code∉现任推导 的 ok/degraded 行打 leaderSuperseded（不删除）；
    幂等：重跑不重盖、计数归零。"""
    db = FakeDb()
    _seed_ghost(db)
    rows = [{"board": "机器人", "code": "603278"}]
    rec = L.reconcile_superseded_leaders(db, "2026-10-23", rows)
    assert rec["superseded"] == 1 and rec["details"][0]["currentLeader"] == "603278"
    ghost = db[L.COLLECTION].docs["2026-10-23:603028"]
    assert ghost["leaderSuperseded"] is True and ghost["supersededBy"] == "603278"
    assert ghost["supersededAt"], "退位时间戳必须落"
    assert "status" not in ghost or ghost["status"] == "ok", "不删除不篡改原档字段"
    # 现任行不受影响
    cur = db[L.COLLECTION].docs["2026-10-23:603278"]
    assert "leaderSuperseded" not in cur
    # 幂等：再跑零新增
    rec2 = L.reconcile_superseded_leaders(db, "2026-10-23", rows)
    assert rec2["superseded"] == 0


def test_reconcile_scoped_by_date_and_skips_other_boards():
    """只动当日、只动推导涉及的 board：他日/他板文档不受牵连。"""
    db = FakeDb()
    _seed_ghost(db)
    col = db[L.COLLECTION]
    col.replace_one({"_id": "2026-10-22:603028"},
                    {"_id": "2026-10-22:603028", "tradingDate": "2026-10-22",
                     "board": "机器人", "code": "603028", "status": "ok"})
    rows = [{"board": "机器人", "code": "603278"}]
    L.reconcile_superseded_leaders(db, "2026-10-23", rows)
    assert "leaderSuperseded" not in col.docs["2026-10-22:603028"], "他日不牵连"


def test_reconcile_no_rows_is_noop():
    """THS 池缺失（rows=None）推导不可得 → 不动历史（fail-visible，不猜现任）。"""
    db = FakeDb()
    _seed_ghost(db)
    rec = L.reconcile_superseded_leaders(db, "2026-10-23", None)
    assert rec == {"superseded": 0, "boards": 0, "details": []}
    assert "leaderSuperseded" not in db[L.COLLECTION].docs["2026-10-23:603028"]


def test_reconcile_only_makes_no_call(env):
    """--reconcile-only：零 jev 调用，返回 reconcile 结果（存量幽灵行被退位）。"""
    calls, db = env
    _seed_ghost(db)
    # env 夹具 leaders_for 桩返回 ROWS（机器人/大业 603278 + 化工）
    out = L.run("2026-10-23", reconcile_only=True)
    assert calls == [], "对账零调用"
    assert out["reconcileOnly"] is True and out["reconcile"]["superseded"] >= 0
    ghost = db[L.COLLECTION].docs.get("2026-10-23:603028")
    # env 的 ROWS 推导现任=603278（机器人）→ 幽灵行退位
    assert ghost is not None and ghost.get("leaderSuperseded") is True


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
    assert out["remaining"] == 2 and out["tokensUsed"] == 0, "v12 拆题：4 次中中止于第 2 次"


def test_single_transient_failure_does_not_abort(env, monkeypatch):
    """单次抖动（夹在成功之间）不得触发中止。"""
    calls, _db = env
    import itertools
    seq = itertools.chain([({"success": False, "errors": [{"message": "timeout"}]}, 5)],
                          itertools.repeat((ENVELOPE, 12)))

    def fake_dispatch(n, q):
        calls.append((n, q))
        return next(seq)
    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    out = L.run("2026-10-19", confirm_budget=True)
    assert out.get("aborted") is None and out["ok"] == 3 and out["degraded"] == 1
    assert len(calls) == 4, "v12 拆题：单次抖动不中止，其余 3 次照常成功"


def test_is_not_a_theme_matches_raw_name_st_board():
    """v12 开火日漏排 bug 回归钉：normalize_name("ST板块")→"ST" 曾绕过行政桶排除——
    判定必须原始名+归一双口径（jev 白烧 2 调用 + 脏行入页面的教训）。"""
    assert L.digest.is_not_a_theme("ST板块") is True
    assert L.digest.is_not_a_theme("ST 板块") is True   # P2-1：空格变体（归一后="ST"）
    assert L.digest.is_not_a_theme("ST") is True
    assert L.digest.is_not_a_theme("公告") is True
    assert L.digest.is_not_a_theme("其他") is True
    assert L.digest.is_not_a_theme("新股") is True
    assert L.digest.is_not_a_theme("机器人") is False
    assert L.digest.is_not_a_theme("大消费") is False
    assert L.digest.is_not_a_theme(None) is False


def test_coarse_buckets_are_excluded_from_jev_scope(env, monkeypatch, capsys):
    """行政桶门控（v3 收紧用户 2026-10-22 裁决 + 2026-10-26 收窄）：公告/新股/其他/ST板块
    **不纳入 jev 判定范围**——零调用、零 token。v5 起（用户 2026-10-23 裁决）排除行
    **不落库不显示**（换代后旧字段/空档位行污染前端），排除事实只留运行日志。
    2026-10-26 用户裁决摘除四个「大X」域桶（大消费/大农业/医药医疗/医疗医药）：
    真实题材域、S3 补充映射上线后 evidenceMissing 全 False（预登记 §20）。"""
    calls, db = env
    rows_with_coarse = ROWS + [
        {"date": "2026-10-19", "board": "ST板块", "code": "600001", "name": "某ST",
         "streak": 1, "time": "09:25:00", "boardN": 1, "othersN": 0, "ladderFollowers": 0,
         "prevPeers": 0, "prevBoardN": 0},
        {"date": "2026-10-19", "board": "公告", "code": "600293", "name": "三峡新材",
         "streak": 3, "time": "09:25:00", "boardN": 1, "othersN": 0, "ladderFollowers": 0,
         "prevPeers": 0, "prevBoardN": 0},
        {"date": "2026-10-19", "board": "其他", "code": "000609", "name": "闽发铝业",
         "streak": 2, "time": "10:52:00", "boardN": 7, "othersN": 6, "ladderFollowers": 6,
         "prevPeers": 2, "prevBoardN": 3},
    ]
    monkeypatch.setattr(L, "leaders_for",
                        lambda db_, date, dataset_id=None: ([dict(r) for r in rows_with_coarse],
                                                            {"thsPoolFound": True}))
    out = L.run("2026-10-19", confirm_budget=True)
    # 只对真题材桶调用（机器人/化工），行政桶零调用：叙事里不得出现被排除的龙头
    assert len(calls) == 4 and out["labeled"] == 4 and out["ok"] == 4, "2 真题材板块 ×（1 板块 doc + 1 龙头 doc）"
    assert out["excludedNotTheme"] == 3
    assert "公告" in out["excludedBoards"]
    assert "其他" in out["excludedBoards"]
    assert "ST板块" in out["excludedBoards"], "v12 漏排 bug 回归：ST板块必须被排除"
    for narrative, _q in calls:
        assert "三峡新材" not in narrative and "闽发铝业" not in narrative
        assert "某ST" not in narrative
    # v5：排除股不落库——库里只有真实判定的 ok/degraded 行，不得出现排除股文档
    # （v12 拆题：板块级 doc 同样不得落库）
    for code in ("600293", "000609", "600001"):
        assert "2026-10-19:" + code not in db[L.COLLECTION].docs, "排除股不得落库（v5 用户裁决）"
    assert "2026-10-19:board:ST板块" not in db[L.COLLECTION].docs, "行政桶板块 doc 不得落库"
    assert "排除非题材行政桶 3 只" in capsys.readouterr().out


def test_domain_buckets_are_included_after_2026_1026(env, monkeypatch):
    """2026-10-26 用户裁决：「大消费/大农业/医药医疗/医疗医药」是真实题材域，不再排除
    （10-26 大消费龙头上海九百 4 板=当日最高板被漏判实锤；S3 上线后 evidenceMissing
    全 False，预登记 §20）。"""
    calls, db = env
    rows_domain = ROWS + [
        {"date": "2026-10-19", "board": "大消费", "code": "600838", "name": "上海九百",
         "streak": 4, "time": "09:30:00", "boardN": 7, "othersN": 6, "ladderFollowers": 6,
         "prevPeers": 2, "prevBoardN": 3},
    ]
    monkeypatch.setattr(L, "leaders_for",
                        lambda db_, date, dataset_id=None: ([dict(r) for r in rows_domain],
                                                            {"thsPoolFound": True}))
    out = L.run("2026-10-19", confirm_budget=True)
    assert out["excludedNotTheme"] == 0 and out["excludedBoards"] == []
    assert out["leaders"] == 3 and len(calls) == 6, "大消费龙头必须纳入投喂（3 板块 doc + 3 龙头 doc）"
    assert any("上海九百" in n for n, _q in calls)


def test_dry_run_excludes_coarse_buckets_without_writing(env, monkeypatch):
    """dry-run 同样排除（不投喂不估算），且零写入。"""
    calls, db = env
    monkeypatch.setattr(L, "leaders_for", lambda db_, date, dataset_id=None: (
        [dict(r) for r in ROWS + [{"date": "2026-10-19", "board": "其他", "code": "600838",
                                   "name": "上海九百", "streak": 2, "time": "10:52:00",
                                   "boardN": 7, "othersN": 6, "ladderFollowers": 6,
                                   "prevPeers": 2, "prevBoardN": 3}]],
        {"thsPoolFound": True}))
    out = L.run("2026-10-19", dry_run=True)
    assert calls == [] and out["todo"] == 2 and out["excludedNotTheme"] == 1
    assert len(db[L.COLLECTION].docs) == 0, "dry-run 绝不写入（含 skipped 台账）"


# 22 次真实调用实测账（2026-10-19 v1 13 次 + 2026-10-20 v2 9 次）；
# (narrative 字符数, usage 总 token) —— 从库中 narrative 长度 × usage 反推，勿改。
# v6 代（4 题，判据收紧措辞版）真实账：2026-10-23（10-22 backfill 6 条，usage=input+output）
# v5 首批（fixed 残差 ≤2,682 前的 2,500 版）已被 v6 加长题面实测取代归档。
_REAL_COST_LEDGER_V6: list[tuple[int, int]] = [
    (1687, 4419),   # 603278 大业股份/机器人
    (1446, 4194),   # 001360 南矿集团/俄乌重建
    (1438, 4183),   # 002724 海洋王/军工
    (1355, 4105),   # 600202 哈空调/冰雪经济
    (1639, 4373),   # 603138 海量数据/数据要素
    (1381, 4107),   # 603933 睿能科技/半导体
]

# v1-v4 代（2 题）真实账（22 条，从库中 narrative 长度 × usage 反推，勿改）
_REAL_COST_LEDGER = [
    (715, 2068), (727, 2075), (728, 2078), (728, 2080), (751, 2015), (757, 2020),
    (760, 2023), (761, 2027), (889, 2146), (903, 2158), (972, 2291), (992, 2330),
    (1020, 2343), (1040, 2275), (1046, 2279), (1054, 2312), (1064, 2317), (1130, 2361),
    (1138, 2449), (1142, 2400), (1213, 2523), (1463, 2681),
]


def test_budget_guard_is_a_true_upper_bound_on_real_ledger():
    """护栏 = **上界**：历史真实账（v1-v4，2 题代）必须全部落在 [low, high] 内。

    v5 起题集 2→4 题（输出增长），固定开销 1,700→2,500（低 1,300→1,800）——旧账只验
    「上界覆盖」（实际消耗不得突破护栏）；**非胖断言（≤1.35×）为代际绑定**：2 题代的
    旧账对 4 题新护栏必然"过松"，该项断言移入 `_REAL_COST_LEDGER_V6`（首个 v5 真实日后
    逐条补账，见预登记 §14.4——不补账 = 护栏失去校准依据，属缺陷）。
    """
    for chars, actual in _REAL_COST_LEDGER:
        est = L.estimate_tokens(chars)
        # 只验上界：低界常数随 4 题上调后，2 题旧账的实耗本就低于新低界（代际差异，非缺陷）
        assert actual <= est["high"], f"chars={chars} actual={actual} est={est}"


def test_budget_guard_non_bloat_on_v6_ledger():
    """v6 代真实账（2026-10-23 首批 6 条）：上界覆盖 + 不虚胖（≤1.35×实耗）。

    实测结论：v6 题面加长后 fixed 须 2,750（旧 2,500 时实测 25,381 > 护栏 24,390，
    低估 4%——§10.5 缺陷当场复标）；最紧一条 603278：4,271→4,521 vs 实耗 4,419。"""
    for chars, actual in _REAL_COST_LEDGER_V6:
        est = L.estimate_tokens(chars)
        assert est["low"] <= actual <= est["high"], f"chars={chars} actual={actual} est={est}"
        assert est["high"] <= actual * 1.35, f"上界过松：chars={chars} {est['high']} vs {actual}"


def test_budget_guard_aggregates_over_leaders():
    """整日护栏 = 逐只上界之和（调度步据此对账），不是均值 × 只数。"""
    chars = [715, 1000, 1463]
    total = sum(L.estimate_tokens(c)["budgetGuard"] for c in chars)
    assert total == sum(int(c * L.TOKENS_PER_CHAR_HIGH) + L.TOKENS_FIXED_HIGH for c in chars)
    assert total > sum(a for c, a in _REAL_COST_LEDGER if c in chars)


def test_day_leader_rows_space_mode_unsealed_leader(monkeypatch):
    """v12 定稿龙一口径（用户 2026-10-28 三轮裁决）：候选池=今∪近3日封板池；

    空间板=高度 ≥2（含断板股最近封板日高度 histStreak——三种情况均参与），组内 10日
    涨幅最高；全首板按当日首封最早。10-26 机器人实证复刻：大业断板（今日不在封板池）
    靠昨日池入候选、histStreak=6，gain10 77.7% 压过 3 板卡位正裕（40.9%）——
    leaderSealedToday=False，streak/time 如实 None，跟风不可算。默认 streak 口径不变
    （基线/历史窗口样本人群不随规则换代漂移）；TDX 全候选不可算 → 板块 fail-visible
    跳过 + meta 披露；断板跌停剔除（未跌停条件）。
    """
    import backend.operations.theme_leader_baseline as B
    import backend.operations.jev_label_jiuyan as J

    def fake_sealed(db_, date, dataset_id=None):
        if date == "2026-10-26":
            return {"603089"}, {"603089": {}}, {"thsPoolFound": True}
        return {"603278", "603089"}, {"603278": {}, "603089": {}}, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db_, date, dataset_id=None:
                        {"603089": 3, "603278": 6} if date == "2026-10-23" else {"603089": 3})
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-26:final"},
        {"_id": "2026-10-26:final", "fields": [
            {"name": "机器人", "stocks": [{"code": "603089", "name": "正裕", "time": "09:25"}]}]})
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-23:final"},
        {"_id": "2026-10-23:final", "fields": [
            {"name": "机器人", "stocks": [{"code": "603278", "name": "大业", "time": "13:09"},
                                          {"code": "603089", "name": "正裕", "time": "09:30"}]}]})

    gains = {"603278": 77.7, "603089": 40.9}
    rows, meta = B.day_leader_rows(db, "2026-10-26", space_mode=True,
                                   pool_dates=["2026-10-23"],
                                   gain_fetcher=lambda codes, end: gains,
                                   day_change_fetcher=lambda codes, date:
                                       {c: -2.0 for c in codes})
    row = rows[0]
    assert row["code"] == "603278" and row["name"] == "大业", "空间板组内 10日涨幅最高（断板未跌停仍可当选）"
    assert row["leaderSealedToday"] is False and row["gain10"] == 77.7
    assert row["streak"] is None and row["time"] is None
    assert row["ladderFollowers"] is None and row["boardN"] == 1
    assert row["secondStreak"] == 3 and row["peerCodes"] == ["603089"]
    assert meta["leaderMode"] == "space"

    rows_streak, meta_streak = B.day_leader_rows(db, "2026-10-26")
    assert rows_streak[0]["code"] == "603089", "默认口径（基线/历史窗口）龙一=真连板最高"
    assert rows_streak[0]["leaderSealedToday"] is True
    assert "leaderMode" not in meta_streak

    rows_none, meta_none = B.day_leader_rows(
        db, "2026-10-26", space_mode=True, pool_dates=["2026-10-23"],
        gain_fetcher=lambda codes, end: {c: None for c in codes})
    assert rows_none == []
    assert "机器人" in meta_none["spaceErrors"], "TDX 不可算 → fail-visible 跳过（用户裁决）"


def test_day_leader_rows_space_mode_multi_pool_day_keeps_recent_streak(monkeypatch):
    """P0-1（review）：近 3 日池去重必须保留**最近**封板日高度——多日连板断板股
    （d-3 首板、d-1 二板、今日断板）曾系统性塌成首板、丢失空间板组资格。"""
    import backend.operations.theme_leader_baseline as B
    import backend.operations.jev_label_jiuyan as J

    def fake_sealed(db_, date, dataset_id=None):
        sealed = {"603278"} if date in ("2026-10-23", "2026-10-27") else {"603089"}
        return sealed, {}, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    streaks = {"2026-10-23": {"603278": 1}, "2026-10-27": {"603278": 2},
               "2026-10-26": {}}
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db_, date, dataset_id=None: streaks.get(date, {}))
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-28:final"},
        {"_id": "2026-10-28:final", "fields": [
            {"name": "机器人", "stocks": [{"code": "603089", "name": "正裕", "time": "09:25"}]}]})
    for pd, t in (("2026-10-23", "09:25"), ("2026-10-27", "09:40")):
        db["jiuyan_action"].replace_one(
            {"_id": f"{pd}:final"},
            {"_id": f"{pd}:final", "fields": [
                {"name": "机器人", "stocks": [{"code": "603278", "name": "大业", "time": t}]}]})
    gains = {"603278": 87.6, "603089": 5.0}
    rows, _m = B.day_leader_rows(
        db, "2026-10-28", space_mode=True, pool_dates=["2026-10-23", "2026-10-26", "2026-10-27"],
        gain_fetcher=lambda codes, end: gains,
        day_change_fetcher=lambda codes, date: {c: -2.0 for c in codes})
    row = next(r for r in rows if r["code"] == "603278")
    assert row["streak"] is None and row["leaderSealedToday"] is False, "今日断板如实"
    assert row["gain10"] == 87.6 and row["boardN"] == 1


def test_day_leader_rows_space_mode_limit_down_excluded(monkeypatch):
    """v12「未跌停」条件：断板不反包且今日跌停（主板 ≤-9.9%）候选剔除，fail-visible 披露；

    涨跌幅不可考 → 保留（不猜，fail-visible）。"""
    import backend.operations.theme_leader_baseline as B
    import backend.operations.jev_label_jiuyan as J

    def fake_sealed(db_, date, dataset_id=None):
        if date == "2026-10-26":
            return {"603089"}, {"603089": {}}, {"thsPoolFound": True}
        return {"603278", "603089"}, {"603278": {}, "603089": {}}, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db_, date, dataset_id=None:
                        {"603089": 3, "603278": 6} if date == "2026-10-23" else {"603089": 3})
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-26:final"},
        {"_id": "2026-10-26:final", "fields": [
            {"name": "机器人", "stocks": [{"code": "603089", "name": "正裕", "time": "09:25"}]}]})
    db["jiuyan_action"].replace_one(
        {"_id": "2026-10-23:final"},
        {"_id": "2026-10-23:final", "fields": [
            {"name": "机器人", "stocks": [{"code": "603278", "name": "大业", "time": "13:09"}]}]})

    gains = {"603278": 77.7, "603089": 40.9}
    rows, meta = B.day_leader_rows(
        db, "2026-10-26", space_mode=True, pool_dates=["2026-10-23"],
        gain_fetcher=lambda codes, end: gains,
        day_change_fetcher=lambda codes, date: {c: -10.2 for c in codes})
    assert rows[0]["code"] == "603089", "断板跌停股剔除后龙一=当日封板正裕"
    assert meta["limitDownExcluded"]["机器人"] == ["大业(-10.2%)"]

    # 涨跌幅不可考 → 保留（不猜）
    rows2, meta2 = B.day_leader_rows(
        db, "2026-10-26", space_mode=True, pool_dates=["2026-10-23"],
        gain_fetcher=lambda codes, end: gains,
        day_change_fetcher=lambda codes, date: {c: None for c in codes})
    assert rows2[0]["code"] == "603278" and "limitDownExcluded" not in meta2


# ── v12 G1/G2：KPL 直播播报 + 板块名匹配 v2（2026-10-28 用户裁决） ──

def test_match_board_strength_v2_suffix_alias_anchor():
    """匹配 v2（一级板块，用户裁决不匹配二级）：尾缀剥离/别名表/共享子串锚/未命中 fail-visible。"""
    payload = {"ok": True, "items": [
        {"plate_id": "801159", "name": "机器人概念", "strength": 31837, "pct": 3.24},
        {"plate_id": "801807", "name": "算力", "strength": 6073, "pct": 3.17},
        {"plate_id": "801660", "name": "通信", "strength": 6073, "pct": 3.17},
        {"plate_id": "801001", "name": "芯片", "strength": 11695, "pct": 3.11},
    ]}
    # 尾缀剥离：韭研「机器人」↔ KPL「机器人概念」
    r1 = L.match_board_strength(payload, "机器人")
    assert r1["ok"] and r1["name"] == "机器人概念" and r1["rank"] == 1
    assert not r1["aliasUsed"]
    # 别名（单一事实源 digest.ALIASES：AI硬件→算力），行内需可披露
    r2 = L.match_board_strength(payload, "AI硬件")
    assert r2["ok"] and r2["name"] == "算力" and r2["aliasUsed"]
    # 共享子串锚：算力租赁 ↔ 算力（≥2 字含汉字锚）
    r3 = L.match_board_strength(payload, "算力租赁")
    assert r3["ok"] and r3["name"] == "算力"
    # 别名（2026-10-30e 清点实证入表：KPL 一级 241 名无「半导体」，对应名
    # 「芯片」，播报实证「芯片（存储）…长鑫科技」；韭研半导体 5 日全未匹配）
    r4 = L.match_board_strength(payload, "半导体")
    assert r4["ok"] and r4["name"] == "芯片" and r4["aliasUsed"]
    # 真无对应 → unmatched 不猜语义（大消费/AI影视/数据要素/俄乌重建，KPL 一级无对应名）
    assert L.match_board_strength(payload, "AI影视") == {"ok": False, "reason": "unmatched"}
    # 取数失败透传
    assert L.match_board_strength({"ok": False, "reason": "fetch_failed: x"},
                                  "机器人")["reason"] == "fetch_failed: x"


def test_live_entries_for_board_filter_and_historical_guard(monkeypatch):
    """直播过滤：关键词/plate 命中、AI 生成尾注剥离、历史日不可回放结构化降级（防泄漏）。"""
    import time as _time
    day = "2026-10-28"
    mk = lambda hh, mm: int(_time.mktime(_time.strptime(f"{day} {hh}:{mm:02d}", "%Y-%m-%d %H:%M")))
    payload = {"ok": True, "items": [
        {"ts": mk(14, 35), "time": "14:35", "plate_name": "", "comment":
         "AI硬件（光通信）持续异动，权重中际旭创、新易盛震荡走强涨超7%（该内容由AI大模型根据行情自动生成）"},
        {"ts": mk(9, 15), "time": "09:15", "plate_name": "机器人概念", "comment":
         "竞价看龙头：机器人概念赛福天、多伦科技"},
        {"ts": mk(14, 0), "time": "14:00", "plate_name": "", "comment":
         "三大指数午后震荡回落，创业板指涨超2%"},
    ]}
    entries, meta = L.live_entries_for_board(payload, "AI硬件", day)
    assert [e["time"] for e in entries] == ["14:35"], "AI硬件仅正文级播报命中；机器人概念的条目不串板"
    assert "AI大模型根据行情自动生成" not in entries[0]["comment"], "AI 生成尾注剥离"
    assert meta["total"] == 3 and meta["window"] == "09:15~14:35"
    # plate 命中：机器人 → 机器人概念条目
    entries_r, _m = L.live_entries_for_board(payload, "机器人", day)
    assert [e["time"] for e in entries_r] == ["09:15"]
    # 历史日：窗口内无标注日条目 → 结构化降级（不冒充语料，防 look-ahead）
    entries2, meta2 = L.live_entries_for_board(payload, "AI硬件", "2026-10-27")
    assert entries2 == [] and "不可回放" in meta2["unavailable"]
    # 取数失败透传
    entries3, meta3 = L.live_entries_for_board({"ok": False, "reason": "fetch_failed: x"},
                                               "AI硬件", day)
    assert entries3 == [] and meta3["unavailable"] == "fetch_failed: x"


def test_kpl_live_line_rendering():
    """直播行渲染（ammo 纯函数）：命中/无播报/不可用三分支 fail-visible。"""
    line = L.kpl_live_line  # noqa — 实现在 ammo，经 label 引用确认同源
    from backend.analysis.hotlist.theme_leader_ammo import kpl_live_line
    hit = kpl_live_line([{"time": "14:35", "comment": "AI硬件（光通信）持续异动"}],
                        board="AI硬件", total=60, window="09:15~15:00")
    assert "KPL直播播报（窗口 09:15~15:00，全窗 60 条）" in hit
    assert "14:35 AI硬件（光通信）持续异动" in hit
    none = kpl_live_line([], board="AI影视", total=60, window="09:15~15:00")
    assert "当日无「AI影视」相关播报" in none and "无数据 ≠ 无催化" not in none, "2026-10-30d：重复自我解释删"
    un = kpl_live_line([], board="AI影视",
                       unavailable="实时流不可回放，历史日无直播归档")
    assert "不可用，实时流不可回放，历史日无直播归档" in un, "2026-10-30g：降级不带括号"


# ── P1-2 直播日归档 / P1-1 序列 / P2-2 reason 透传（2026-10-28 用户裁决） ──

def test_get_live_for_label_archive_roundtrip(monkeypatch):
    """P1-2：当日实时取后归档 → 二次读归档（零外呼）；历史日无归档 fail-visible（防泄漏）。"""
    import time as _time
    db = FakeDb()
    today = _time.strftime("%Y-%m-%d")
    sent: list = []

    def fake_fetch(st=60):
        sent.append(st)
        ts = int(_time.mktime(_time.strptime(f"{today} 10:00", "%Y-%m-%d %H:%M")))
        return {"ok": True, "items": [{"ts": ts, "time": "10:00", "comment": "x"}],
                "notice": ""}

    monkeypatch.setattr(L, "fetch_live_commentary", fake_fetch)
    p1 = L.get_live_for_label(db, today)
    assert p1["ok"] and not p1.get("fromArchive") and len(sent) == 1
    assert db[L.LIVE_ARCHIVE_COLLECTION].docs[today]["itemCount"] == 1, "当日取后归档"
    p2 = L.get_live_for_label(db, today)
    assert p2.get("fromArchive") is True and len(sent) == 1, "二次读归档零外呼"
    # 历史日：无归档 → 结构化降级（不外呼不冒充）
    p3 = L.get_live_for_label(db, "2026-10-01")
    assert p3["ok"] is False and "不可回放" in p3["reason"] and len(sent) == 1


def test_fetch_plate_zt_history_filters_future(monkeypatch):
    """P1-1：层2 全史 → 只留 ≤ 标注日（防 look-ahead），窗口截尾；失败 fail-visible。"""
    import backend.services.kpl_ranking_service as K
    hist = [{"date": "2026-10-20", "zt_num": 9}, {"date": "2026-10-27", "zt_num": 16},
            {"date": "2026-10-29", "zt_num": 99}]   # 未来日必须被滤掉
    monkeypatch.setattr(K, "get_plate_daily_history",
                        lambda plate_id, limit=60: {"ok": True, "plate_id": plate_id,
                                                    "items": hist, "count": len(hist)})
    out = L.fetch_plate_zt_history("801159", "2026-10-28", window_days=5)
    assert out["ok"] and [r["date"] for r in out["zt_rows"]] == ["2026-10-20", "2026-10-27"]
    monkeypatch.setattr(K, "get_plate_daily_history",
                        lambda plate_id, limit=60: (_ for _ in ()).throw(
                            K.KplRankingError("kpl_errcode", errorCode="1020")))
    out2 = L.fetch_plate_zt_history("801159", "2026-10-28")
    assert out2["ok"] is False and "fetch_failed" in out2["reason"]


def test_label_persists_answer_reasons_when_present(env):
    """P2-2：模型若附 reason → 容错落库 answerReasons；不附时 {}（行为不变）。"""
    calls, db = env
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:board:机器人"]
    assert doc["answerReasons"] == {}, "夹具答案无 reason → 空 dict 如实落库"


# ── review P1-1/P2 修复回归（2026-10-29）：_series_line 接线 + 窗口过滤 ──

def test_series_line_wiring_sentinel_and_window_in_narrative(env, monkeypatch):
    """ops 接线钉死：pct/amount 透传触发哨兵、trading_days/window_first_date 传入后
    层2 按窗口过滤计数（窗外记录不展示不计数），落库 narrative 含全部证据。"""
    calls, db = env

    def fake_strength(day):
        return {"ok": True, "items": [
            # |净额| > 成交额 → 哨兵量级告警必须在落库 narrative 出现
            {"plate_id": "801159", "name": "机器人概念", "strength": 31837,
             "pct": 1.0, "amount": 1e9, "main_net": -48221868016}]}

    monkeypatch.setattr(L, "fetch_plate_strength", fake_strength)
    monkeypatch.setattr(L, "fetch_live_commentary", lambda st=60: {"ok": False, "reason": "t"})

    five_days = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
    monkeypatch.setattr(L, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: list(five_days))

    def fake_zt(plate_id, label_date, window_days=5):
        assert plate_id == "801159" and window_days == 6, "窗口交易日数必须=len(days)"
        return {"ok": True, "zt_rows": [
            {"date": "2026-10-09", "zt_num": 9, "lz_info": ""},    # 窗外 → 不得展示/计数
            {"date": "2026-10-15", "zt_num": 3, "lz_info": ""},
            {"date": "2026-10-16", "zt_num": 4, "lz_info": ""}]}

    monkeypatch.setattr(L, "fetch_plate_zt_history", fake_zt)

    out = L.run("2026-10-19", confirm_budget=True)
    assert out["ok"] == 4
    narrative = db[L.COLLECTION].docs["2026-10-19:603278"]["narrative"]
    assert "口径哨兵告警：" in narrative
    assert "净额>成交额 ×5" in narrative, "pct/amount 必须从强度行透传到哨兵（夹具 5 个交易日同一条越界行）"
    # 窗口 6 交易日（5 前日 + 当日），窗内仅 2 条记录；窗外 10-09 不得入行
    assert "板块涨停家：" in narrative, "2026-10-30g：窗口缺口注删（用户裁决）"
    assert "10-09" not in narrative, "窗外记录不得被算作窗口内在场（review P1-1）"
    assert "10-15 家3" in narrative and "10-16 家4" in narrative


def test_series_line_zero_in_window_records_still_disclosed(env, monkeypatch):
    """窗内 0 条记录：层2 段必须显式出「仅0条记录」（缺口信号本身，§4.0 不静默缺席）。"""
    calls, db = env
    monkeypatch.setattr(L, "fetch_plate_strength",
                        lambda day: {"ok": True, "items": [
                            {"plate_id": "801159", "name": "机器人概念",
                             "strength": 31837, "pct": 1.0,
                             "amount": 9e9, "main_net": -3e8}]})
    monkeypatch.setattr(L, "fetch_live_commentary", lambda st=60: {"ok": False, "reason": "t"})
    monkeypatch.setattr(L, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: [
                            "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])
    monkeypatch.setattr(L, "fetch_plate_zt_history",
                        lambda plate_id, label_date, window_days=5: {"ok": True, "zt_rows": [
                            {"date": "2026-10-09", "zt_num": 9, "lz_info": ""}]})
    L.run("2026-10-19", confirm_budget=True)
    narrative = db[L.COLLECTION].docs["2026-10-19:603278"]["narrative"]
    assert "板块涨停家：窗口内无记录" in narrative, "2026-10-30g：缺口注删，缺席照披露"
    assert "窗口内无记录" in narrative


def test_live_entries_board_suffix_bridge_bingxue(monkeypatch):
    """2026-10-30e 后缀桥实证回归：韭研「冰雪经济」命中 KPL「冰雪产业」播报。

    10-29 实测漏配：10:38 播报「冰雪产业-1.30% 冰雪产业异动拉升，冰山冷热直线涨停，
    晶雪节能、雪人集团等跟涨」——修复后须命中（plate 桥 + 文本词干锚）。
    """
    import time as _time
    day = "2026-10-29"
    mk = lambda hh, mm: int(_time.mktime(_time.strptime(f"{day} {hh}:{mm:02d}", "%Y-%m-%d %H:%M")))
    payload = {"ok": True, "items": [
        {"ts": mk(10, 38), "time": "10:38", "plate_name": "冰雪产业", "plate_pct": "-1.30",
         "comment": "冰雪产业异动拉升，冰山冷热直线涨停，晶雪节能、雪人集团等跟涨"},
        {"ts": mk(11, 0), "time": "11:00", "plate_name": "机器人概念", "comment":
         "机器人概念冲高回落"},
    ]}
    entries, meta = L.live_entries_for_board(payload, "冰雪经济", day)
    assert [e["time"] for e in entries] == ["10:38"], "经济/产业后缀桥：漏配修复"
    assert "冰雪产业异动拉升" in entries[0]["comment"]
    assert meta["total"] == 2


def test_market_summary_entry_and_narrative_placement(monkeypatch):
    """15:00 收盘总结（AMMO 2026-10-30e）：提取/缺席/两级叙事紧跟盘面事实行。"""
    import time as _time
    day = "2026-10-29"
    mk = lambda hh, mm: int(_time.mktime(_time.strptime(f"{day} {hh}:{mm:02d}", "%Y-%m-%d %H:%M")))
    summary_txt = ("15:00三大指数低开低走，上证指数跌超-0.5%，创业板指跌超-4%，收盘沪深京三市"
                   "全天成交不足1.6万亿，相较前一交易日缩量4%，下跌个股超4500家。市场震荡下行，"
                   "题材弱势轮动。冰雪产业龙江交通、冰山冷热等首板涨停。"
                   "（该内容由AI大模型根据行情自动生成）")
    payload = {"ok": True, "items": [
        {"ts": mk(15, 0), "time": "15:00", "plate_name": "", "comment": summary_txt},
        {"ts": mk(10, 38), "time": "10:38", "plate_name": "冰雪产业", "comment": "冰雪产业异动拉升"},
    ]}
    entry = L.market_summary_entry(payload, day)
    assert entry and entry["time"] == "15:00"
    assert "AI大模型根据行情自动生成" not in entry["comment"], "AI 生成尾注剥离"
    # 缺席/失败/非当日 → None（补充行缺席不伪装）
    assert L.market_summary_entry(payload, "2026-10-28") is None
    assert L.market_summary_entry({"ok": False, "reason": "x"}, day) is None
    assert L.market_summary_entry({"ok": True, "items": [
        {"ts": mk(10, 0), "time": "10:00", "plate_name": "机器人概念", "comment": "x"}]}, day) is None
    line = L.market_summary_line(entry)
    assert line.startswith("盘面总结（KPL 15:00）：15:00三大指数低开低走")
    assert L.market_summary_line(None) is None
    # 两级叙事：紧跟盘面事实行、在交易日轴前
    from backend.analysis.hotlist.theme_leader_ammo import build_leader_narrative, build_sector_narrative
    n = build_leader_narrative(date=day, market_line="涨停 46 家", forward_axis="交易日轴（前向）：X",
                               market_summary=line, structure="结构行", baseline="基线行",
                               evidence_block="【题材证据】", leader_name="X", leader_code="1")
    assert n.index("涨停 46 家") < n.index("盘面总结（KPL 15:00）") < n.index("交易日轴")
    n2 = build_leader_narrative(date=day, market_line="涨停 46 家", structure="结构行",
                                baseline="基线行", evidence_block="【题材证据】",
                                leader_name="X", leader_code="1")
    assert "盘面总结" not in n2, "缺席不出行"
    s = build_sector_narrative(date=day, board="冰雪经济", market_line="涨停 46 家",
                               forward_axis="交易日轴（前向）：X",
                               market_summary=line, structure="结构行", baseline="基线行",
                               evidence_block="【题材证据】")
    assert s.index("涨停 46 家") < s.index("盘面总结（KPL 15:00）") < s.index("交易日轴")


# ---------- v14：新龙人气成色题事件门（P3 工作流 B，B1:A） ----------

def test_v14_event_gate_wires_rebound_question_only_for_event_stock(env, monkeypatch):
    """事件门：命中弱转强事件的龙头 doc 判答第 5 题+叙事含人气证据链行；
    同日未命中事件的龙头 doc 仍 2 题、叙事不含链行（零额外调用，预登记 §四）。"""
    calls, db = env
    # 单源 wzs 文档：仅大业股份（603278）命中形式①事件
    db[L.WZS_COLLECTION].docs["2026-10-19"] = {
        "_id": "2026-10-19", "tradingDate": "2026-10-19",
        "poolRows": [{"code": "603278", "name": "大业股份", "board": "机器人",
                      "windowK": 1, "height": 3,
                      "windowChanges": [{"date": "2026-10-16", "pct": -2.5}]}],
        "events": [{"type": "leaderRebound", "date": "2026-10-19",
                    "board": "机器人", "segment": None, "code": "603278",
                    "name": "大业股份", "windowK": 1, "height": 3,
                    "gain10": 45.2}]}
    # 周期背景（可缺；本例给主升第2轮）
    db[L.CYCLE_COLLECTION].docs["2026-10-19:机器人:main"] = {
        "_id": "2026-10-19:机器人:main", "tradingDate": "2026-10-19",
        "board": "机器人", "segment": "main", "state": "mainrise", "cycleRound": 1}
    # 模型对第 5 题也给答（answer dict 原样透传；事件股 expected_keys 含新题）
    env2 = {**ENVELOPE, "result": {**ENVELOPE["result"], "result": {
        **ENVELOPE["result"]["result"],
        "answers": {**ENVELOPE["result"]["result"]["answers"],
                    "leader_rebound_popularity": {"type": "choice",
                                                  "choice": "dragon_confirm",
                                                  "confidence": 0.7}}}}}

    def fake_dispatch2(narrative, questions):
        calls.append((narrative, questions))
        # 模拟真实行为：模型只答被问的题——非事件 doc（2 题）不含第 5 题答案
        if L.REBOUND_QUESTION in questions:
            return env2, 12
        return ENVELOPE, 12

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch2)
    out = L.run("2026-10-19", confirm_budget=True)
    assert out["ok"] == 4
    doc_hit = db[L.COLLECTION].docs["2026-10-19:603278"]
    doc_miss = db[L.COLLECTION].docs["2026-10-19:603188"]
    # 事件股：3 题判答（续板/空间/人气成色）
    qs_hit = doc_hit["questionsRaw"]
    assert set(L.LEADER_QUESTIONS) <= set(qs_hit)
    assert L.REBOUND_QUESTION in qs_hit, "事件股判答人气成色题"
    assert doc_hit["leaderReboundPopularity"] == "insufficient", \
        "夹具无语料→证据门覆盖新题（v5 起全题门，v14 新题同规）；真实事件日语料在场时走模型答"
    assert L.REBOUND_QUESTION in (doc_hit.get("gate") or {}).get("forcedKeys", []), \
        "证据门 forcedKeys 含人气成色题（按 questions 子集门）"
    assert doc_hit["modelAnswers"][L.REBOUND_QUESTION]["choice"] == "dragon_confirm", \
        "模型原答在 modelAnswers 审计（不得被消费端当口径）"
    assert "人气证据链" in doc_hit["narrative"], "事件股叙事含人气证据链行组"
    assert "形式①人气股反包" in doc_hit["narrative"]
    assert "主升·第2轮" in doc_hit["narrative"], "周期背景只披露"
    # v15 P1 接线（review 2026-11-05）：run→build_one 的 cycle 透传被误删时此处先红
    assert "结构事实（程序直读" in doc_hit["narrative"], "v15 事实行恒在（fail-visible）"
    assert "周期状态=主升" in doc_hit["narrative"], "cycle 文档透传到事实行"
    assert "周期状态=不可考" in doc_miss["narrative"], "无周期文档时显式不可考不伪造"
    # 非事件股：2 题判答（B1:A 零额外调用）
    assert L.REBOUND_QUESTION not in doc_miss["questionsRaw"]
    assert "人气证据链" not in doc_miss["narrative"]
    assert doc_miss["leaderReboundPopularity"] is None
    # 调用次数不变：4 次（2 龙头 + 2 板块），事件门只换题集不增调用
    assert len(calls) == 4
    nq = {len(q) for _n, q in calls}
    assert nq == {2, 3}, "事件股 3 题、其余 2 题"


def test_v14_no_wzs_doc_zero_rebound_question(env):
    """wzs 文档缺失（当日未跑弱转强链）→ 全部龙头 2 题，不报错不硬造事件。"""
    calls, db = env
    out = L.run("2026-10-19", confirm_budget=True)
    assert out["ok"] == 4
    for did in ("2026-10-19:603278", "2026-10-19:603188"):
        assert L.REBOUND_QUESTION not in db[L.COLLECTION].docs[did]["questionsRaw"]
    assert all(len(q) == 2 for _n, q in calls)


# ---------- v14 配套：强度行专属桥（AI影视/传媒 → KPL 一级「AI应用」） ----------

def test_strength_alias_ai_yingshi_maps_to_ai_yingyong():
    """2026-11-02 用户裁决（KPL 板块行情实证）：韭研 AI影视/传媒 32 家（AI漫剧/短剧）
    归 KPL 一级「AI应用」（层2 AI视频 23 家即这批股）；旧④共享子串「传媒」把
    「文化传媒」（仅 2 家涨停）误配上、读数失真——别名③必须先于④命中。"""
    items = [  # 按今日实测形状（序位=排行 1 起）
        {"name": "AI应用", "strength": 31762, "pct": 4.886, "plate_id": "803023"},
        {"name": "三季报增长", "strength": 29095, "pct": 2.308, "plate_id": "x"},
        {"name": "游戏", "strength": 11228, "pct": 6.962, "plate_id": "x"},
        {"name": "文化传媒", "strength": 10198, "pct": 6.206, "plate_id": "801031"},
    ]
    m = L.match_board_strength({"ok": True, "items": items}, "AI影视/传媒")
    assert m["ok"] is True and m["name"] == "AI应用", "强度行归一级 AI应用（非文化传媒）"
    assert m["rank"] == 1 and m["aliasUsed"] is True
    assert m["strength"] == 31762 and m["pct"] == 4.886
    # 语料桥不受影响：digest 侧仍展开 AI视频（层2 标签粒度）
    assert "AI视频" in L.digest.board_keywords("AI影视/传媒")
    # 其他板块零影响：既有尾缀剥离匹配保持
    m2 = L.match_board_strength({"ok": True, "items": items}, "机器人")
    assert m2["ok"] is False and m2["reason"] == "unmatched", "夹具无机器人概念行，不得猜配"


# ---------- 2026-11-08a：涨停基因语料接入题集（待判龙一自身） ----------

GENE_ITEM = {"stock_id": "603278",
             "gene": {"zt_count": 4, "premium5_count": 1, "next_day_red_pct": 50,
                      "first_seal_pct": 100, "first_broken_pct": 0, "lianban_pct": 50},
             "raw": [4, 1, 50, 100, 0, 50],
             "window_note": "上游未标注统计窗口（六元数组原样透出，不自算不反推）",
             "fetched_date": "2026-10-19", "same_day": True}


def test_fetch_gene_corpus_maps_by_code_and_degraded_is_empty(monkeypatch):
    """取数走存档器读口（单一事实源）：ok → code 映射；降级/异常 → 空映射（出不可考行）。"""
    import backend.services.kpl_daban_archiver as arch

    monkeypatch.setattr(arch, "load_gene_corpus",
                        lambda db, date: {"ok": True,
                                          "items": [GENE_ITEM,
                                                    dict(GENE_ITEM, stock_id="301697")]})
    got = L.fetch_gene_corpus(FakeDb(), "2026-10-19")
    assert set(got) == {"603278", "301697"} and got["603278"]["raw"] == [4, 1, 50, 100, 0, 50]

    monkeypatch.setattr(arch, "load_gene_corpus",
                        lambda db, date: {"ok": False, "reason": "no_gene_corpus"})
    assert L.fetch_gene_corpus(FakeDb(), "2026-10-19") == {}

    def boom(db, date):
        raise RuntimeError("db down")
    monkeypatch.setattr(arch, "load_gene_corpus", boom)
    assert L.fetch_gene_corpus(FakeDb(), "2026-10-19") == {}, "读口异常不阻断整轮投喂"


def test_gene_entries_for_leaders_labels_and_missing():
    """仅待判龙一自身；分轨标签；无该股语料 → item=None（尾部出不可考）。"""
    rows = [dict(ROWS[0], segment="main"), dict(ROWS[1], segment="growth")]
    entries = L.gene_entries_for_leaders(rows, {"603278": GENE_ITEM})
    assert entries[0]["label"].startswith("主板龙一")
    assert entries[0]["item"] is GENE_ITEM
    assert entries[1]["label"].startswith("双创龙一") and entries[1]["item"] is None


def test_build_one_wires_gene_line_before_reason_line():
    """个股级叙事：涨停基因行排涨停原因行前；未传入 → 不出行（旧行为不变）。"""
    row = dict(ROWS[0], segment="main", boardCodes=["603278"])
    built = L.build_one(FakeDb(), "2026-10-19", row, BASELINE, market_line="涨停 46 家",
                        gene_entries=L.gene_entries_for_leaders([row],
                                                                {"603278": GENE_ITEM}),
                        reason_entries=[("主板龙一 大业股份", "机器人")])
    n = built["narrative"]
    assert "涨停基因（统计窗口上游未标注）：主板龙一 大业股份=涨停4次" in n
    assert n.index("涨停基因（") < n.index("涨停原因：")
    built0 = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), BASELINE,
                         market_line="涨停 46 家")
    assert "涨停基因" not in built0["narrative"]


def test_run_feeds_gene_corpus_into_leader_docs(env, monkeypatch):
    """run 装配：语料按日一次取数 → 待判龙一叙事带基因行（板块级不消费，省 token）。"""
    import backend.services.kpl_daban_archiver as arch

    calls, db = env
    monkeypatch.setattr(arch, "load_gene_corpus",
                        lambda db_, date: {"ok": True, "items": [
                            dict(GENE_ITEM, stock_id=str(r.get("code") or "")[-6:])
                            for r in ROWS]})
    L.run("2026-10-19", confirm_budget=True)
    col = db[L.COLLECTION]
    leader_docs = [d for d in col.docs.values() if d.get("docKind") == "leader"]
    assert leader_docs, "至少一条个股级 doc"
    assert any("涨停基因（统计窗口上游未标注）" in d["narrative"] for d in leader_docs)
    sector_docs = [d for d in col.docs.values() if d.get("docKind") == "sector"]
    assert sector_docs and all("涨停基因" not in d["narrative"] for d in sector_docs)


# ---------- 2026-11-08b / 题集 v16：封板质量语料行（个股级判据引用源） ----------

QUALITY_ITEM = {"zt_tur": 77237472.0, "max_zt_tur": 407660096.0,
                "real_float": 4422390777.0, "real_turnover": 14.31,
                "main_net": 148080233.0, "amount": 593597266.0, "price": "",
                "pool_state": "sealed", "last_seen_ts": 1794119726.2}


def _pool_payload(items):
    return {"ok": True, "lane": "pool", "empty": False, "date": "2026-10-19",
            "items": items}


def test_fetch_pool_quality_maps_by_code_and_degraded_empty(monkeypatch):
    """取数走存档器读口 load_day(lane=pool)：ok → code 映射 + 采集帧；
    降级/异常 → 空映射（出「不可考」行，不阻断投喂）。"""
    import backend.services.kpl_daban_archiver as arch

    monkeypatch.setattr(arch, "load_day",
                        lambda db, date, lane="pool": _pool_payload(
                            [dict(QUALITY_ITEM, stock_id="603278"),
                             dict(QUALITY_ITEM, stock_id="999999")]))
    got = L.fetch_pool_quality(FakeDb(), "2026-10-19")
    assert set(got) == {"603278", "999999"}
    assert got["603278"]["item"]["zt_tur"] == 77237472.0
    assert got["603278"]["frameAt"] == "14:35", "采集帧=该股最后一帧（Asia/Shanghai）"
    assert "quotas" not in got["603278"]["item"], "只取本行消费的列，不搬整条 items"

    monkeypatch.setattr(arch, "load_day",
                        lambda db, date, lane="pool": {"ok": False, "reason": "no_archive"})
    assert L.fetch_pool_quality(FakeDb(), "2026-10-19") == {}

    def boom(db, date, lane="pool"):
        raise RuntimeError("db down")
    monkeypatch.setattr(arch, "load_day", boom)
    assert L.fetch_pool_quality(FakeDb(), "2026-10-19") == {}, "读口异常不阻断整轮投喂"


def test_seal_quality_entries_for_leaders_labels_and_unsealed():
    """仅待判龙一；分轨标签；断板反包候选（leaderSealedToday=False）→ unsealed 标记。"""
    rows = [dict(ROWS[0], segment="main"), dict(ROWS[1], segment="growth"),
            dict(ROWS[0], segment="main", leaderSealedToday=False)]
    entries = L.seal_quality_entries_for_leaders(rows, {"603278": {"item": QUALITY_ITEM,
                                                                  "frameAt": "14:35"}})
    assert entries[0]["label"].startswith("主板龙一") and entries[0]["item"] is QUALITY_ITEM
    assert entries[1]["label"].startswith("双创龙一") and entries[1]["item"] is None
    assert entries[0]["unsealed"] is False and entries[2]["unsealed"] is True


def test_build_one_wires_seal_quality_line_after_zhaban():
    """个股级叙事：封板质量行在板内炸板面行之后；未传入 → 不出行（旧行为不变）。"""
    row = dict(ROWS[0], segment="main", boardCodes=["603278"])
    built = L.build_one(FakeDb(), "2026-10-19", row, BASELINE, market_line="涨停 46 家",
                        seal_quality_entries=L.seal_quality_entries_for_leaders(
                            [row], {"603278": {"item": QUALITY_ITEM, "frameAt": "14:35"}}))
    n = built["narrative"]
    assert "封板质量（KPL 涨停池 14:35 采集帧，非收盘帧）：主板龙一 大业股份" in n
    assert n.index("板内炸板面：") < n.index("封板质量（")
    built0 = L.build_one(FakeDb(), "2026-10-19", dict(ROWS[0]), BASELINE,
                         market_line="涨停 46 家")
    assert "封板质量" not in built0["narrative"]


def test_run_feeds_pool_quality_into_leader_docs(env, monkeypatch):
    """run 装配：量价字段按日一次取数 → 待判龙一叙事带封板质量行（板块级不消费）。"""
    import backend.services.kpl_daban_archiver as arch

    calls, db = env
    monkeypatch.setattr(arch, "load_day",
                        lambda db_, date, lane="pool": _pool_payload(
                            [dict(QUALITY_ITEM, stock_id=str(r.get("code") or ""))
                             for r in ROWS]))
    L.run("2026-10-19", confirm_budget=True)
    col = db[L.COLLECTION]
    leader_docs = [d for d in col.docs.values() if d.get("docKind") == "leader"]
    assert leader_docs and all("封板质量（KPL 涨停池" in d["narrative"] for d in leader_docs)
    sector_docs = [d for d in col.docs.values() if d.get("docKind") == "sector"]
    assert sector_docs and all("封板质量" not in d["narrative"] for d in sector_docs)
