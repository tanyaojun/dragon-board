"""弱转强节点分类 + 语料行测试（2026-10-21 立项，全 fake 零真实调用）。

口径单源 = backend/analysis/hotlist/weak_to_strong.py，与
docs/hotlist-jev/jev-weak-to-strong-day-study.md §1 预注册一致；
语料行 = operations/jev_relay_index.weak_to_strong_line（A 路线：题目集零改动）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.hotlist import weak_to_strong as W
from backend.operations import jev_relay_index as R


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, q=None, p=None, sort=None, limit=None):
        return [dict(r) for r in self.rows if all(r.get(k) == v for k, v in (q or {}).items())]

    def update_one(self, q=None, update=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (q or {}).items()):
                r.update((update or {}).get("$set") or {})
                return
        self.rows.append(dict((update or {}).get("$set") or {}))

    def find_one(self, q=None, p=None, sort=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (q or {}).items()):
                return dict(r)
        return None

    def aggregate(self, pipeline):
        # 只支持 zt_series 的 match+sort+group last 形态
        rows = self.rows
        for stage in pipeline:
            if "$match" in stage:
                q = stage["$match"]
                rows = [r for r in rows if all(r.get(k) == v for k, v in q.items())]
            if "$sort" in stage:
                for k, direction in reversed(list(stage["$sort"].items())):
                    rows = sorted(rows, key=lambda r: str(r.get(k) or ""), reverse=direction < 0)
            if "$group" in stage:
                key = stage["$group"]["_id"].lstrip("$")
                out = []
                seen = {}
                order = []
                for r in rows:
                    k = r.get(key)
                    if k not in seen:
                        seen[k] = r
                        order.append(k)
                    else:
                        seen[k] = r
                rows = [{"_id": k, "last": seen[k].get("limitSummary", {}).get("zhaban", {}).get("ztCount")} for k in order]
        return rows


class FakeDb:
    def __init__(self, cols):
        self._cols = dict(cols)

    def __setitem__(self, name, col):
        self._cols[name] = col

    def __getitem__(self, name):
        return self._cols.get(name) or FakeCol()


def _mk_db():
    """五日构造：D1 弱(idx 30)、D2 命中(idx 55, 跌停降+涨停升)、D3 延续、D4 非弱势未贴标、D5 idx 缺前置。"""
    relay = [{"_id": f"{d}:RELAY", "status": "ok", "relayIndex": i, "tradingDate": d}
             for d, i in [("2026-03-02", 55.0), ("2026-03-03", 30.0), ("2026-03-04", 55.0),
                          ("2026-03-05", 60.0), ("2026-03-06", 44.0)]]
    dt = [{"_id": d, "count": c} for d, c in [("2026-03-02", 3), ("2026-03-03", 20), ("2026-03-04", 5),
                                              ("2026-03-05", 6), ("2026-03-06", 5)]]
    # 涨停帧（15:00 口径）：settle 定档要求确认两侧原料齐全（审查 MF-3/SF-3）；
    # 03-03/03-04 同值 46 不引入 zt_up，保持既有 classify 断言
    zt_rows = [{"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
                "tradingDate": d, "limitSummary": {"zhaban": {"ztCount": 46}}}
               for d in ("2026-03-03", "2026-03-04")]
    return FakeDb({
        "hotlist_jev_relay_index": FakeCol(relay),
        "market_daily_limit_down": FakeCol(dt),
        "snapshot_frames": FakeCol(zt_rows),
    })


W._BASELINE_CACHE.clear()


def test_classify_hit_and_continuation():
    cls = W.classify_series(_mk_db())
    assert cls["2026-03-04"]["hit"] is True        # 30→55, Δ25, 跌停 20→5
    assert cls["2026-03-04"]["confirm"] == ["dt_down"]
    assert cls["2026-03-05"]["continuation"] is True and cls["2026-03-05"]["hit"] is False
    assert cls["2026-03-02"]["reason"] == "insufficient_history"
    # D6 44.0：非弱势未贴标（防标签通胀）
    assert cls["2026-03-06"]["hit"] is False and cls["2026-03-06"]["reason"] == "prev_not_weak"
    # 节点三态（2026-10-22 用户裁决：弱/弱转强/强；优先级=转换节点>状态）
    assert cls["2026-03-04"]["state"] == "wzs"          # 命中日优先（idx 55 同时 ≥50）
    assert cls["2026-03-05"]["state"] == "strong"       # 中强区延续日
    assert cls["2026-03-03"]["state"] == "weak"         # 弱势区
    assert cls["2026-03-06"]["state"] is None           # 44 中性区不标


def test_classify_reasons():
    """专检三档 reason：昨日非弱势 / 今日未入强区 / 结构确认缺失。"""
    relay = [{"_id": f"{d}:RELAY", "status": "ok", "relayIndex": i, "tradingDate": d}
             for d, i in [("2026-04-01", 35.0), ("2026-04-02", 44.0), ("2026-04-03", 58.0)]]
    dt = [{"_id": d, "count": c} for d, c in [("2026-04-01", 5), ("2026-04-02", 6), ("2026-04-03", 5)]]
    db = FakeDb({"hotlist_jev_relay_index": FakeCol(relay),
                 "market_daily_limit_down": FakeCol(dt)})
    db["snapshot_frames"] = FakeCol([
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": d, "timestamp": 1, "snapshotId": 1,
         "limitSummary": {"zhaban": {"ztCount": 50}}} for d in ("2026-04-01", "2026-04-02", "2026-04-03")])
    cls = W.classify_series(db)
    assert cls["2026-04-02"]["reason"] == "idx_below_strong"      # 35→44：弱但未入强区
    # 04-03：58-44=14≥10 但前日 44>40 → 非弱势
    assert cls["2026-04-03"]["reason"] == "prev_not_weak"
    # 结构确认缺失档：涨跌停均未改善
    relay2 = [{"_id": f"{d}:RELAY", "status": "ok", "relayIndex": i, "tradingDate": d}
              for d, i in [("2026-04-08", 30.0), ("2026-04-09", 55.0)]]
    db2 = FakeDb({"hotlist_jev_relay_index": FakeCol(relay2),
                  "market_daily_limit_down": FakeCol([
                      {"_id": "2026-04-08", "count": 3}, {"_id": "2026-04-09", "count": 3}])})
    db2["snapshot_frames"] = FakeCol([
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": d, "timestamp": 1, "snapshotId": 1,
         "limitSummary": {"zhaban": {"ztCount": 50}}} for d in ("2026-04-08", "2026-04-09")])
    cls2 = W.classify_series(db2)
    assert cls2["2026-04-09"]["reason"] == "no_structural_confirm" and cls2["2026-04-09"]["hit"] is False


def test_baseline_matches_study_dimensions():
    """基线与研究报告同链现算：n=命中次数、延续率分子分母、反包率均值公式一致。"""
    import statistics
    from backend.operations.rewrap_pool import COLLECTION
    db = _mk_db()
    db[COLLECTION] = FakeCol([
        {"_id": "2026-03-02:final", "rewrapRate": 0.05},
        {"_id": "2026-03-03:final", "rewrapRate": 0.05},
        {"_id": "2026-03-04:final", "rewrapRate": 0.10},   # 命中日
        {"_id": "2026-03-05:final", "rewrapRate": 0.20},   # 命中日
        {"_id": "2026-03-06:final", "rewrapRate": 0.05},
    ])
    b = W.weak_to_strong_baseline(db)
    assert b["hitN"] == 1                              # 仅 03-04 命中（03-05 非弱势前夜）
    assert b["contTotal"] == 1 and b["contOk"] == 1    # 03-05 idx 60 ≥ 55 → 延续
    assert b["dtPrevMedian"] == 20 and b["dtHitMedian"] == 5
    assert b["hitRewrapMean"] == round(statistics.mean([0.10]), 4)
    assert b["allRewrapMean"] == round(statistics.mean([0.05, 0.05, 0.10, 0.20, 0.05]), 4)


def test_weak_to_strong_line_hit_and_miss(monkeypatch):
    from backend.operations.rewrap_pool import COLLECTION
    db = _mk_db()
    db["snapshot_frames"] = FakeCol([
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": d, "timestamp": 1, "snapshotId": 1,
         "limitSummary": {"zhaban": {"ztCount": z}}}
        for d, z in [("2026-03-02", 40), ("2026-03-03", 30), ("2026-03-04", 55),
                     ("2026-03-05", 58), ("2026-03-06", 50)]])
    db[COLLECTION] = FakeCol([{"_id": "2026-03-04:final", "rewrapRate": 0.10}])
    monkeypatch.setattr(W, "relay_idx_series", lambda db, *a, **k: {
        "2026-03-02": 55.0, "2026-03-03": 30.0, "2026-03-04": 55.0,
        "2026-03-05": 60.0, "2026-03-06": 44.0})
    hit_line = R.weak_to_strong_line(db, "2026-03-04")
    assert "弱转强参照" in hit_line and "符合历史弱转强形态" in hit_line
    assert "跌停 20→5" in hit_line and "涨停 30→55" in hit_line
    # v10 D2：静态历史基线/反包率对比撤出叙事（反包率+分位在反包修复行）
    assert "T+1 延续率" not in hit_line and "今日反包率" not in hit_line
    assert "历史基线" not in hit_line and "一日游" not in hit_line
    miss_line = R.weak_to_strong_line(db, "2026-03-06")
    assert "昨日 relayIndex 60.0（中强区）" in miss_line
    # v11 补遗 A2：跨链打标行为注「不贴形态标」删（§1.2-8，relay 7 题零消费）
    assert "不贴形态标" not in miss_line and "今日结构" in miss_line
    assert "T+1 延续率" not in miss_line


def test_weak_to_strong_line_midday_no_fake_confirm(monkeypatch):
    """午盘档：跌停盘后才写入，只做涨停侧预检并显式注记，不伪判形态。"""
    from backend.operations.rewrap_pool import COLLECTION
    db = _mk_db()
    # 午盘真实态：当日跌停档盘后才写入，先移除（不伪造可判）
    db["market_daily_limit_down"].rows = [
        r for r in db["market_daily_limit_down"].rows if r["_id"] != "2026-03-04"]
    db["snapshot_frames"] = FakeCol([
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "11:30",
         "tradingDate": "2026-03-04", "timestamp": 1, "snapshotId": 1,
         "limitSummary": {"zhaban": {"ztCount": 58}}}])
    monkeypatch.setattr(W, "relay_idx_series", lambda db, *a, **k: {
        "2026-03-03": 30.0, "2026-03-04": 55.0})
    monkeypatch.setattr(W, "zt_series", lambda db, *a, **k: {"2026-03-03": 30})
    line = R.weak_to_strong_line(db, "2026-03-04", slot="11:30")
    assert "午盘预检" in line and "跌停盘后写入" in line
    assert "形态盘后定档" not in line   # v11 补遗 A2：流程注删
    assert "符合历史弱转强形态" not in line


def test_weak_to_strong_line_prev_missing_fail_visible(monkeypatch):
    db = FakeDb({"hotlist_jev_relay_index": FakeCol([]),
                 "market_daily_limit_down": FakeCol([]),
                 "snapshot_frames": FakeCol([])})
    line = R.weak_to_strong_line(db, "2026-03-04")
    assert "昨日 relayIndex 缺失，形态不可判" in line, "2026-10-30g+：括号删"


def test_weak_to_strong_line_idx_below_but_structural_confirm_wording():
    """2026-10-20 重跑实证（idx 47.8<50 但 dt↓+zt↑ 均确认）暴露的措辞 bug 回归：
    未达标的是指数侧时，文案必须把「指数未达」与「结构确认已满足」分开表述，
    不得再写自相矛盾的「结构确认未命中（跌停 22→5↓、涨停 46→52↑）」。"""
    db = _mk_db()  # 03-02 idx55 / 03-03 idx30(弱) / 03-04 idx55 命中 / ...
    # 改造：03-04 落到 44（指数未达强势区），但跌停 20→5、涨停 30→55 结构双确认
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    from backend.operations.jev_relay_index import weak_to_strong_line
    line = weak_to_strong_line(db, "2026-03-04")
    assert "指数未达强势区（44.0" in line and "不贴形态标" not in line   # v11 补遗 A2
    # 夹具无涨停帧，确认侧只有跌停证据（与 classify 的 confirm=[dt_down] 一致）
    assert "结构确认已满足：跌停 20→5↓" in line
    assert "结构确认未命中" not in line


# ── 节点定格（2026-10-22 用户裁决 §6.3：判定标准必须稳定，重跑不改写） ──────────
def test_settlement_first_write_wins():
    """定档一次定格：先定档 55（命中），改底层评分为 44 再定档 → 存档节点不变。"""
    db = _mk_db()
    e1 = W.write_settlement(db, "2026-03-04")
    assert e1["hit"] is True and e1["idx"] == 55.0 and "settledAt" in e1
    for r in db["hotlist_jev_relay_index"].rows:      # 模拟重跑改写评分
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    e2 = W.settle_day(db, "2026-03-04")               # first-write-wins：已定档返回存档
    assert e2 == e1 and e2["hit"] is True and e2["idx"] == 55.0


def test_classify_series_prefers_settled_and_chain_carries():
    """定格优先：已定档日用存档节点；未定格次日 continuation 由定格 hit 传导。"""
    db = _mk_db()
    for r in db["hotlist_jev_relay_index"].rows:      # 模拟重跑把 03-04 评分改到 44
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    W.write_settlement(db, "2026-03-04", idx_override=55.0)   # 收盘定档 55（存档值）
    cls = W.classify_series(db)
    assert cls["2026-03-04"]["settled"] is True and cls["2026-03-04"]["hit"] is True
    assert cls["2026-03-04"]["idx"] == 55.0           # 定档值，非重跑值
    assert cls["2026-03-05"]["continuation"] is True  # 定格命中传导给未定格次日
    assert cls["2026-03-06"]["continuation"] is False


def test_baseline_uses_settlement():
    """基线从定格节点统计：重跑后 idx 44 不再吞掉命中，基线命中数不漂移。"""
    db = _mk_db()
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    W.write_settlement(db, "2026-03-04", idx_override=55.0)
    W._BASELINE_CACHE.clear()
    base = W.weak_to_strong_baseline(db)
    assert base["hitN"] == 1                          # 03-04 定格命中计入


def test_apply_settlement_carry_on_rerun():
    """重跑路径：已定档随档原样带过（不改写）；未定档以本次落库值首次定档。"""
    from backend.operations.jev_relay_index import _apply_settlement
    db = _mk_db()
    W.write_settlement(db, "2026-03-04", idx_override=55.0)
    prev = db["hotlist_jev_relay_index"].find_one({"_id": "2026-03-04:RELAY"})
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    new_doc = {"_id": "2026-03-04:RELAY", "tradingDate": "2026-03-04", "relayIndex": 44.0}
    _apply_settlement(prev, new_doc, db, "dragonboard_live")
    assert new_doc["wzs"]["hit"] is True and new_doc["wzs"]["idx"] == 55.0
    # 未定档日：以本次落库值首次定档
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-05:RELAY":
            r["relayIndex"] = 70.0
    new2 = {"_id": "2026-03-05:RELAY", "tradingDate": "2026-03-05", "status": "ok",
            "relayIndex": 70.0}
    _apply_settlement(None, new2, db, "dragonboard_live")
    assert new2["wzs"]["hit"] is False and new2["wzs"]["idx"] == 70.0
    assert new2["wzs"]["continuation"] is True        # 03-04 定格命中传导


def test_weak_to_strong_line_divergence_note():
    """语料行定格 vs 重评分歧注记：重跑改评分后，语料行按定档节点表述并显式注记重评值。
    v10 P2：措辞去「节点」（FORBIDDEN 黑名单词），重跑分支同过叙事卫生红线。"""
    from backend.operations.jev_relay_index import weak_to_strong_line
    from tests.hotlist.test_narrative_hygiene import FORBIDDEN
    db = _mk_db()
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    W.write_settlement(db, "2026-03-04", idx_override=55.0)
    line = weak_to_strong_line(db, "2026-03-04")
    assert "符合历史弱转强形态" in line                # 按定档节点（55 命中）表述
    assert "重跑重评 44.0，以收盘定档 55.0 为准" in line
    assert not [w for w in FORBIDDEN if w in line], "重跑分支叙事含开发注释"


# ── 定档代际绑定（2026-10-22 §6.4 预注册：题集升代→旧定格失效→--reset 重定档） ────
def test_settlement_records_generation():
    """定档条目必须带 gen=当前题集代（跨代可审计的前提）。"""
    db = _mk_db()
    e = W.settle_day(db, "2026-03-04")
    assert e["gen"] == W.QUESTION_SET_VERSION_RELAY   # v8（2026-11-12 市场周期融合升代）


def test_stale_generation_stamp_ignored(monkeypatch):
    """升代后旧代定格自动失效（回退现算），不静默沿用旧代节点。"""
    db = _mk_db()
    W.write_settlement(db, "2026-03-04", idx_override=55.0)
    assert W.classify_series(db)["2026-03-04"]["hit"] is True
    monkeypatch.setattr(W, "QUESTION_SET_VERSION_RELAY", "v8.0")   # 模拟题集升代
    cls = W.classify_series(db)
    # 关键断言：旧代定格失效，该日回退现算（settled 标记消失，不再锚定旧代 idx）
    assert cls["2026-03-04"].get("settled") is not True


def test_reset_backfill_restamps_under_new_generation(monkeypatch):
    """--reset 重新定档：旧代定格被覆盖，新档带新 gen；正常运行路径仍 first-write-wins。"""
    db = _mk_db()
    W.write_settlement(db, "2026-03-04", idx_override=55.0)
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 44.0
    monkeypatch.setattr(W, "QUESTION_SET_VERSION_RELAY", "v8.0")
    e = W.write_settlement(db, "2026-03-04", reset=True)
    assert e["gen"] == "v8.0" and e["hit"] is False and e["idx"] == 44.0
    # 正常路径依旧不改写（升代窗口关闭后重跑不能动节点）
    for r in db["hotlist_jev_relay_index"].rows:
        if r.get("_id") == "2026-03-04:RELAY":
            r["relayIndex"] = 99.0
    e2 = W.settle_day(db, "2026-03-04")
    assert e2["gen"] == "v8.0" and e2["idx"] == 44.0


# ── 独立审查处置（2026-10-22 reviewer：MF-1/2/3、SF-3/4） ────────────────────
def test_first_run_line_without_today_doc():
    """MF-1 回归：首判时当日 doc 未落库，语料行不得误报「昨日 relayIndex 缺失」，
    也不得把形态写成未命中——只给昨日分区 + 结构预检（v10 A1：「待落库」流程注删）。"""
    from backend.operations.jev_relay_index import weak_to_strong_line
    db = _mk_db()
    db["hotlist_jev_relay_index"].rows = [
        r for r in db["hotlist_jev_relay_index"].rows if r.get("_id") != "2026-03-04:RELAY"]
    line = weak_to_strong_line(db, "2026-03-04")
    assert "昨日 relayIndex 30.0（弱势区）" in line
    assert "待落库" not in line
    assert "结构预检：跌停 20→5↓" in line
    assert "缺失（形态不可判）" not in line and "未命中" not in line


def test_degraded_result_never_settles():
    """MF-2 回归：degraded/失败判定不是有效收盘定档；下轮成功后按真实评分定档。"""
    from backend.operations.jev_relay_index import _apply_settlement
    db = _mk_db()
    new_doc = {"_id": "2026-03-04:RELAY", "tradingDate": "2026-03-04",
               "status": "degraded", "relayIndex": None}
    _apply_settlement(None, new_doc, db, "dragonboard_live")
    assert "wzs" not in new_doc                       # 不定格
    ok_doc = {"_id": "2026-03-04:RELAY", "tradingDate": "2026-03-04",
              "status": "ok", "relayIndex": 55.0}
    _apply_settlement(None, ok_doc, db, "dragonboard_live")
    assert ok_doc["wzs"]["hit"] is True               # 成功后正常定档


def test_settle_refused_when_confirm_material_missing():
    """SF-3 回归：指数条件满足但跌停/涨停任一侧原料缺失 → 拒绝定档（返回 None，
    不把原料缺失定格成「判定未命中」）；原料齐后可定档。"""
    db = _mk_db()
    db["market_daily_limit_down"].rows = [r for r in db["market_daily_limit_down"].rows
                                          if r.get("_id") != "2026-03-04"]  # 当日跌停缺失
    db["snapshot_frames"].rows = []                    # 涨停帧全缺
    entry = W.settle_day(db, "2026-03-04", idx_override=55.0)
    assert entry is None
    assert W.write_settlement(db, "2026-03-04", idx_override=55.0) is None
    doc = db["hotlist_jev_relay_index"].find_one({"_id": "2026-03-04:RELAY"})
    assert "wzs" not in doc
    # 原料齐（跌停当日档 + 涨停帧回补）→ 可定档
    db["market_daily_limit_down"].rows.append({"_id": "2026-03-04", "count": 5})
    db["snapshot_frames"].rows = [{"datasetId": "dragonboard_live", "type": "half_hour",
                                   "slotTime": "15:00", "tradingDate": d,
                                   "limitSummary": {"zhaban": {"ztCount": 46}}}
                                  for d in ("2026-03-03", "2026-03-04")]
    assert W.settle_day(db, "2026-03-04", idx_override=55.0)["hit"] is True


def test_cli_wzs_settle_backfill(tmp_path, monkeypatch, capsys):
    """SF-4：CLI 命令本体——override 解析、skip 计数、--reset 归档先于覆盖、dry-run 不归档。"""
    import argparse, json
    import backend.cli as C
    db = _mk_db()
    W.write_settlement(db, "2026-03-03")              # 预置一格已定档 → skip
    from backend.data.repositories import repository_factory
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.chdir(tmp_path)
    def run(**kw):
        args = argparse.Namespace(start="2026-03-01", end="2026-03-06",
                                  idx_override=kw.get("ov", []), reset=kw.get("reset", False),
                                  dry_run=kw.get("dry", False))
        C.cmd_wzs_settle_backfill(args)
        return json.loads(capsys.readouterr().out)
    # 坏 override 格式
    try:
        run(ov=["badformat"])
        assert False, "应 SystemExit"
    except SystemExit:
        pass
    # 正常：03-04 定档（skip 03-03），override 存档值 55
    r = run(ov=["2026-03-04=55.0"])
    assert r["stamped"] == 4 and r["skippedAlreadySettled"] == 1 and r["missingDoc"] == 0
    d = [x for x in r["details"] if x["date"] == "2026-03-04"][0]
    assert d["hit"] is True and d["override"] is True
    doc = db["hotlist_jev_relay_index"].find_one({"_id": "2026-03-04:RELAY"})
    assert doc["wzs"]["idx"] == 55.0
    # dry-run + reset：不归档不写入
    before = doc["wzs"]
    r2 = run(reset=True, dry=True)
    assert r2["archivedTo"] is None
    assert db["hotlist_jev_relay_index"].find_one({"_id": "2026-03-04:RELAY"})["wzs"] == before
    # reset 实跑：归档先于覆盖
    r3 = run(reset=True)
    assert r3["archivedTo"] and (tmp_path / r3["archivedTo"]).exists()
    archived = json.loads((tmp_path / r3["archivedTo"]).read_text(encoding="utf-8"))
    assert before["idx"] in [v["idx"] for v in archived["settlements"].values()]

