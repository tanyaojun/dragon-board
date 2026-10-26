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
    assert "【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】" in printed


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
    assert doc["questionSetVersion"] == "v8"
    assert doc["questionSetHash"] == "b0914cdd3e7d"   # v8 越锚铸词内联定义（v1-v7 hash 留档在预登记文档）
    assert doc["ammoVersion"] == "2026-10-26a"   # 空间锚每档基率化（预登记 §21.2）
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

    def fake_build_one(db_, date, row, rows_baseline, dataset_id, market_line,
                       board_history=None):
        built = real_build(db_, date, row, rows_baseline, dataset_id, market_line,
                           board_history=board_history)
        built["evidence"] = {"state": {"ok": True}, "events": [], "evidenceMissing": False,
                             "evidenceMissingReason": None}
        return built

    monkeypatch.setattr(L, "build_one", fake_build_one)
    L.run("2026-10-19", confirm_budget=True)
    doc = db[L.COLLECTION].docs["2026-10-19:603278"]
    assert doc["gate"]["applied"] is False
    assert doc["leaderNextdayContinue"] == "mid_45_65"
    assert doc["modelAnswers"] == doc["answers"], "不过门时两者应一致（不是两套数）"
    # v5 四题落库：题材深度/延续性/龙头空间
    assert doc["themeSpeculationDepth"] == "fermenting"
    assert doc["themeContinuation"] == "strong_extend"
    assert doc["leaderHeadroom"] == "space_2plus"


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
                        board_history={"机器人": [("2026-10-16", 3), ("2026-10-17", 5)]})
    n = built["narrative"]
    assert "近 2 日该板块封板家数（旧→新，缺口日不列）：10-16 3 · 10-17 5" in n
    assert "空间锚" in n and "总体 再走≥1板率" in n   # 2026-10-26a 每档基率化
    # 2026-10-24c 三行：前向轴紧跟盘面行、梯队/炸板面紧跟结构行；昨日口径=总数−仍封出断板
    # （2026-10-19 是周一；weekday 桩=周一~五交易日）
    assert "交易日轴（前向）：下一交易日 2026-10-20（周二） · 下下交易日 2026-10-21（周三）" \
        "（日历源 weekday，节假日顺延未经验证）" in n
    assert "昨日该板块封板 6 只，今日仍封 3 只（断板 3）" in n
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
    assert "昨日该板块封板 1 只，今日仍封 1 只（断板 0）" in line
    assert "断板 -2" not in line and "今日仍封 3 只" not in line, "成员口径的负数/失真不得进叙事"


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


def test_coarse_buckets_are_excluded_from_jev_scope(env, monkeypatch, capsys):
    """行政桶门控（v3 收紧用户 2026-10-22 裁决 + 2026-10-26 收窄）：公告/新股/其他/ST板块
    **不纳入 jev 判定范围**——零调用、零 token。v5 起（用户 2026-10-23 裁决）排除行
    **不落库不显示**（换代后旧字段/空档位行污染前端），排除事实只留运行日志。
    2026-10-26 用户裁决摘除四个「大X」域桶（大消费/大农业/医药医疗/医疗医药）：
    真实题材域、S3 补充映射上线后 evidenceMissing 全 False（预登记 §20）。"""
    calls, db = env
    rows_with_coarse = ROWS + [
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
    assert len(calls) == 2 and out["labeled"] == 2 and out["ok"] == 2
    assert out["excludedNotTheme"] == 2
    assert "公告" in out["excludedBoards"]
    assert "其他" in out["excludedBoards"]
    for narrative, _q in calls:
        assert "三峡新材" not in narrative and "闽发铝业" not in narrative
    # v5：排除股不落库——库里只有真实判定的 ok/degraded 行，不得出现排除股文档
    for code in ("600293", "000609"):
        assert "2026-10-19:" + code not in db[L.COLLECTION].docs, "排除股不得落库（v5 用户裁决）"
    assert "排除非题材行政桶 2 只" in capsys.readouterr().out


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
    assert out["leaders"] == 3 and len(calls) == 3, "大消费龙头必须纳入投喂"
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
