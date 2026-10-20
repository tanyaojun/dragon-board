# -*- coding: utf-8 -*-
"""原料口径测试（2026-10-05 批次B + 同日二次修正）——全 fake/monkeypatch，禁触真实 jev 调用。

- I6 涨停判定线精确化 ×1.10/0.20/0.30（旧 ×1.098 近板误判）；
  同日二次修正：阈值单源 core/limit_rules，2026-09 新规无 ST 特判（主板 ST 亦 ±10%，
  批次B 的 ST ±5% 特判已撤销），判定线 -9.8/-19.8/-29.8；
- I8 快照取数带 datasetId 隔离，帧查询带 type 并取最新帧；
- I9 trading_dates_before 改查 snapshot_frames；
- 新落库文档盖 ammoVersion 戳（旧文档缺戳=旧代原料，fail-visible）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import (
    AMMO_VERSION,
    DEFAULT_DATASET_ID,
    _advdec_segment,
    _limit_pct_of,
    advdec_ratio,
    dieban_count,
    limitup_sequence_line,
    market_facts_line,
    market_metrics,
    stock_board_shape_line,
    ths_positions,
    trading_dates_before,
)


class FakeCol:
    """记录查询参数的假集合（验证 datasetId/type/sort 下推）。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries: list[tuple[dict, dict | None, dict | None]] = []

    def find(self, query=None, projection=None):
        self.queries.append((query, projection, None))

        def matches(row):
            for key, expected in (query or {}).items():
                if key == "code" and isinstance(expected, dict) and "$in" in expected:
                    if row.get("code") not in expected["$in"]:
                        return False
                    continue
                if isinstance(expected, dict) and "$lt" in expected:
                    val = row.get(key)
                    if not (val and str(val) < expected["$lt"]):
                        return False
                    continue
                if isinstance(expected, dict) and "$exists" in expected:
                    if (row.get(key) is None) != (not expected["$exists"]):
                        return False
                    continue
                if isinstance(expected, dict) and "$ne" in expected:
                    if row.get(key) == expected["$ne"]:
                        return False
                    continue
                if row.get(key) != expected:
                    return False
            return True

        return [dict(r) for r in self.rows if matches(r)]

    def find_one(self, query=None, projection=None, sort=None):
        self.queries.append((query or {}, projection, sort))
        candidates = [r for r in self.rows if all(r.get(k) == v for k, v in (query or {}).items()
                                                  if not isinstance(v, dict))]
        if sort:
            for key, direction in reversed(sort):
                candidates.sort(key=lambda r: r.get(key) or "", reverse=direction < 0)
        return candidates[0] if candidates else None

    def replace_one(self, q, doc, upsert=False):
        self.rows = [r for r in self.rows if r.get("_id") != doc.get("_id")]
        self.rows.append(dict(doc))


class FakeDb:
    def __init__(self, cols: dict[str, FakeCol] | None = None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


# ---- I6 涨停判定线精确化 ----

def test_limit_pct_exact_values():
    """2026-10-05 二次修正：阈值单源 core/limit_rules，2026-09 新规无 ST 特判（主板 ST 亦 ±10%）。"""
    assert _limit_pct_of("600000", None) == 0.10
    assert _limit_pct_of("300750", None) == 0.20
    assert _limit_pct_of("688981", None) == 0.20
    assert _limit_pct_of("832000", None) == 0.30
    # 无 ST 特判（新规）：ST 标记不影响板块阈值（旧 ±5% 副本口径退役）
    assert _limit_pct_of("600000", "ST 某某") == 0.10
    assert _limit_pct_of("300750", "ST 某某") == 0.20


def test_limitup_sequence_rejects_near_limit_close(monkeypatch):
    """prev=10.00，收盘 10.98：真实涨停价 11.00，不应再被误判涨停（旧 ×1.098 判定线 10.98）。"""
    bars = [{"date": "2026-09-29", "high": 10.0, "close": 10.0, "vol": 1000.0},
            {"date": "2026-09-30", "high": 10.99, "close": 10.98, "vol": 1000.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    monkeypatch.setattr(runner, "_adj_prev_series", lambda date, code, bars_: {})  # P1-1：测试离线，原口径
    line = limitup_sequence_line("2026-09-30", "600000", None, n=2)
    assert "近 2 日 ○●" not in line  # 10.98 非涨停
    assert "当前连板 0" in line

    bars[-1]["close"] = 11.00
    bars[-1]["high"] = 11.00
    line = limitup_sequence_line("2026-09-30", "600000", None, n=2)
    assert "当前连板 1" in line  # 11.00 = 涨停价


def test_board_shape_rejects_near_limit_touch(monkeypatch):
    """板型：最高 10.98 未触真实涨停价 11.00 → 未触板（旧实现会算首触/炸板）。"""
    intraday = [{"date": "2026-09-30", "hm": "10:00", "open": 10.5, "high": 10.98, "close": 10.9}]
    monkeypatch.setattr(runner, "_daily_bars",
                        lambda code: [{"date": "2026-09-29", "high": 10.0, "close": 10.0, "vol": 1.0},
                                      {"date": "2026-09-30", "high": 10.98, "close": 10.9, "vol": 1.0}])
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: intraday)
    line = stock_board_shape_line("2026-09-30", "600000", None, prev_close=10.0)
    assert "未触板" in line


# ---- I7 跌停 ST + I8 datasetId 隔离 ----

def _row(code, pct, dataset=DEFAULT_DATASET_ID, name=None, slot="15:00"):
    return {"datasetId": dataset, "type": "half_hour", "tradingDate": "2026-09-30",
            "slotTime": slot, "code": code, "name": name, "pctChange": pct}


def test_dieban_by_board_thresholds():
    """2026-10-05 二次修正：新规无 ST 特判，判定线单源 core/limit_rules（-9.8/-19.8/-29.8）。"""
    rows = [_row("600001", -9.9, name="甲"),      # 主板 -9.9 ≤ -9.8 计
            _row("600002", -5.0, name="ST 乙"),    # 新规主板 ST 亦 ±10%：-5.0 不计
            _row("600003", -5.0, name="丙"),       # 主板非ST -5.0 不计
            _row("300001", -19.9, name="丁"),      # 创业 20cm 计
            _row("300002", -5.0, name="ST 戊"),    # 创业不计
            _row("920001", -29.9, name="己"),      # 北交 920 计
            ]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") == 3


def test_dieban_dataset_isolated():
    rows = [_row("600001", -10.0, dataset="other_dataset", name="甲")]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") is None  # 其它 dataset 不串数
    assert dieban_count(db, "2026-09-30", dataset_id="other_dataset") == 1


def test_dieban_missing_name_no_st_false_positive():
    rows = [_row("600001", -5.0)]  # 无 name：按主板阈值，不误判
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") == 0


def test_advdec_tone_words_by_ratio():
    """2026-10-16 语气词修正（审计问题 #9）：ratio<1 = 跌多涨少（偏弱）。

    旧口径 0.8-1.25 全写「没人买也没人卖」——26 家全市场跌停的日子（池内 0.82）会被读成僵持。
    """
    rows = [_row("600001", 5.0), _row("600002", -5.0)]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert advdec_ratio(db, "2026-09-30") == (1, 1, 0, 1.0)
    assert "均衡" in _advdec_segment(db, "2026-09-30")
    rows2 = [dict(_row("600001", 5.0), tradingDate="2026-10-09"),
             dict(_row("600002", -5.0), tradingDate="2026-10-09"),
             dict(_row("600003", -5.0), tradingDate="2026-10-09")]
    db2 = FakeDb({"snapshot_stock_rows": FakeCol(rows2)})
    seg = _advdec_segment(db2, "2026-10-09")
    assert "跌多涨少（偏弱）" in seg and "没人买也没人卖" not in seg


def test_advdec_dataset_isolated():
    rows = [_row("600001", 5.0, dataset="other")]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert advdec_ratio(db, "2026-09-30") is None
    assert advdec_ratio(db, "2026-09-30", dataset_id="other") == (1, 0, 0, 1.0)


# ---- I8 帧查询下推 datasetId/type/sort ----

def test_market_metrics_query_scoped_and_latest():
    col = FakeCol([
        {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "old", "timestamp": 1,
         "limitSummary": {"zhaban": {"ztCount": 30}}},
        {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "new", "timestamp": 2,
         "limitSummary": {"zhaban": {"ztCount": 55}}},
        {"datasetId": "other", "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "x", "timestamp": 9,
         "limitSummary": {"zhaban": {"ztCount": 999}}},
    ])
    db = FakeDb({"snapshot_frames": col})
    m = market_metrics(db, "2026-09-30")
    assert m["ztCount"] == 55  # 取同 dataset 最新帧
    # 首个查询即 market_metrics 的帧查询（其后 jiuyan_board_info 也会查帧取炸板池，
    # 该查询不带 sort，故断言锚在 queries[0] 而非 [-1]）
    query, projection, sort = col.queries[0]
    assert query["datasetId"] == DEFAULT_DATASET_ID and query["type"] == "half_hour"
    assert sort == [("timestamp", -1), ("snapshotId", -1)]


def test_ths_positions_query_scoped():
    col = FakeCol([{"datasetId": DEFAULT_DATASET_ID, "type": "half_hour",
                    "tradingDate": "2026-09-30", "slotTime": "15:00",
                    "limitSummary": {"thsPools": {"pools": {
                        "one": {"items": [{"stock_code": "sh600000", "continue_day": 1,
                                           "limit_up_time": "09:31", "industry_block": "地产",
                                           "main_net_amount": 1e7}]}}}}}])
    db = FakeDb({"snapshot_frames": col})
    out = ths_positions(db, "2026-09-30")
    assert "600000" in out
    query, _, sort = col.queries[-1]
    assert query["datasetId"] == DEFAULT_DATASET_ID and query["type"] == "half_hour"
    assert sort == [("timestamp", -1), ("snapshotId", -1)]


# ---- I9 交易日历改查 snapshot_frames ----

def test_trading_dates_before_uses_frames_not_rows():
    db = FakeDb({
        "snapshot_frames": FakeCol([
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-28"},
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-29"},
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30"},
            {"datasetId": "other", "type": "half_hour", "tradingDate": "2026-09-27"},
        ]),
        "snapshot_stock_rows": FakeCol([{"tradingDate": "2026-09-26"}]),  # 若误查 rows 会有 09-26
    })
    dates = trading_dates_before(db, "2026-09-30")
    assert dates == ["2026-09-28", "2026-09-29"]  # 只来自 frames 且隔离 dataset
    assert "snapshot_stock_rows" not in db.cols or db.cols["snapshot_stock_rows"].queries == []


# ---- ammoVersion 代际戳 ----

def test_ammo_version_stamp_constant():
    # P1-1（预登记 jev-ammo-p1-preregistration.md §一）：除权修正因子入叙事，代际顺延
    # 2026-10-16（预注册 jev-relay-caliber-fix-preregistration.md §5b）：涨停价取整改十进制
    # 四舍五入（内置 round 分位为 5 时低取一分，差一分未封的棒会被判成封板），代际再顺延
    # 2026-10-20（预注册 jev-driver-label-v32-preregistration.md）：个股链语料瘦身/增益
    # （市场坐标/交易日轴/封板时间坐标/解析续期/THS 缺日回退）→ 代际顺延
    assert AMMO_VERSION == "2026-10-20a"
    assert DEFAULT_DATASET_ID == "dragonboard_live"


# ---- 2026-10-10 梯队双源（jiuyan 主源 / THS 回退，Phase 0）----

def _frame(date: str, *, ths_pools: dict | None = None, zt: int = 55) -> dict:
    ls: dict = {"zhaban": {"ztCount": zt, "count": 8, "rate": 12.0}, "drawdown": {"count": 3},
                "continuousBoards": {"maxBoard": 6}}
    if ths_pools is not None:
        ls["thsPools"] = {"pools": ths_pools}
    return {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"half_hour:{date}:15:00", "timestamp": 2,
            "limitSummary": ls}


def _frame_ths(date: str, *, failed: list | None = None, layers: dict | None = None,
               max_board: int = 6, zt: int = 55, rushing: list | None = None,
               seal_quality: dict | None = None) -> dict:
    """带 ok 炸板池的 15:00 帧（streak 口径二分用）；layers={one:{total},...} 连板层五池；
    rushing=[codes] 冲刺池（含池级 ok）；sealQuality 封板质量块。"""
    failed = failed or []
    layers = layers or {}
    pools: dict = {"failed": {"key": "failed", "ok": True, "total": len(failed),
                              "items": [{"code": c, "name": f"股{c}", "open_num": 1} for c in failed]}}
    for k in ("one", "two", "three", "four", "high"):
        if k in layers:
            pools[k] = {"key": k, "total": layers[k]["total"],
                        "items": [{"stock_code": f"60001{i}", "stock_name": f"层{k}{i}",
                                   "continue_day": k} for i in range(layers[k]["total"])]}
    if rushing is not None:
        pools["rushing"] = {"key": "rushing", "ok": True, "total": len(rushing),
                            "items": [{"code": c, "name": f"冲{c}", "change_rate": 7.0} for c in rushing]}
    rate = round(len(failed) / (zt + len(failed)) * 100, 1) if (zt + len(failed)) else 0.0
    ls: dict = {"zhaban": {"ztCount": zt, "count": len(failed), "rate": rate},
                "drawdown": {"count": 3},
                "continuousBoards": {"maxBoard": max_board},
                "thsPools": {"ok": True, "degraded": False, "pools": pools}}
    if seal_quality is not None:
        ls["sealQuality"] = seal_quality
    return {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"half_hour:{date}:15:00", "timestamp": 2,
            "limitSummary": ls}


def test_market_facts_line_zhaban_rate_dual_caliber():
    """炸板率双口径（2026-10-16 补供，审计问题 #6）：曾封后开板 ｜ 触板未封（炸板池+冲刺池）。
    旧语料只给前者，「炸板面健康」判据看不到触板未封那一半（10-15 实证漏 6 家）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_ths("2026-09-30", failed=[], zt=36,
                                               rushing=["000001", "000002", "000003", "000004",
                                                        "000005", "000006"])]),
        "jiuyan_action": FakeCol([_jiuyan_final("2026-09-30", [1])]),
    })
    line = market_facts_line(db, "2026-09-30")
    assert "炸板率 0.0%（" in line and "炸板 0 家）" in line
    assert "触板未封 6 家（含冲刺 6 家），未封率 14.3%（6/42）" in line


def test_market_facts_line_zhaban_rate_single_when_no_rushing():
    """冲刺池未拉取（非 EOD 槽）→ 只给曾封后开板单口径，不猜触板未封。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_ths("2026-09-30", failed=["600009"], zt=36)]),
        "jiuyan_action": FakeCol([_jiuyan_final("2026-09-30", [1])]),
    })
    line = market_facts_line(db, "2026-09-30")
    assert "炸板率 2.7%（" in line and "炸板 1 家）" in line
    assert "触板未封" not in line


def _jiuyan_final(date: str, boards: list, *, codes: list | None = None) -> dict:
    """boards: 每股真实板数（None=韭研首板不标 num）；codes 可指定（默认 60000{i}）。"""
    stocks = []
    for i, b in enumerate(boards):
        code = (codes[i] if codes else f"60000{i}")
        num = None if b is None else f"{b}天{b}板"
        stocks.append({"code": code, "num": num})
    return {"_id": f"{date}:final", "fields": [{"name": "板块A", "stocks": stocks}]}


def test_market_metrics_ladder_streak_caliber():
    """2026-10-16 口径修正：梯队按**真连板**分桶且只桶封板股（触板−炸板池二分）。

    - N==M 直取 M；N>M 断板股走回溯（16天8板但昨日炸板 → 真连板 1 → one 桶，不得进 high）；
    - 今日炸板股不进涨停梯队；高度不可算（回溯撞 THS 池缺日）→ 不入桶只披露。
    """
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame_ths("2026-09-30", failed=["600009"]),   # 600009 今日炸板
            _frame_ths("2026-09-29"),                      # 昨日（回溯链用）
        ]),
        "jiuyan_action": FakeCol([
            # 600001/600002 首板；600003 2板；600004 3板；600005 5板；600006 9板(纯连板→high)；
            # 600007/600008 num=None 首板；600009 16天8板但**今日炸板**→ 不进桶
            _jiuyan_final("2026-09-30", [1, 1, 2, 3, 5, 9, None, None, 8],
                          codes=["600001", "600002", "600003", "600004", "600005", "600006",
                                 "600007", "600008", "600009"]),
        ]),
    })
    db.cols["jiuyan_action"].rows[0]["fields"][0]["stocks"][8]["num"] = "16天8板"
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "jiuyan"
    assert m["ladder"] == {"one": 4, "two": 1, "three": 1, "four": 0, "high": 2}
    assert m["ladderPoolTotal"] == 8          # 入桶=封板且高度已知（炸板的 600009 不计）
    assert m["ladderHeightUnknown"] == 0
    # 最高板=真连板最大值（600006 9天9板 → 9）；区间值另列
    assert m["maxBoard"] == 9
    assert m["maxBoardRange"] == 6            # 帧 continuousBoards（区间口径）原样保留
    assert m["maxBoardStock"]["boards"] == 9


def test_market_metrics_ladder_height_unknown_disclosed():
    """N>M 股回溯撞上 THS 炸板池缺失日 → 高度不可算：不入桶、计数披露，不按 M 伪算。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame_ths("2026-09-30"),          # 今日池在
            _frame("2026-09-29"),              # 昨日无 thsPools → 链不可验证
        ]),
        "jiuyan_action": FakeCol([
            _jiuyan_final("2026-09-30", [2, 8], codes=["600001", "600009"]),
        ]),
    })
    db.cols["jiuyan_action"].rows[0]["fields"][0]["stocks"][1]["num"] = "16天8板"
    m = market_metrics(db, "2026-09-30")
    assert m["ladder"] == {"one": 0, "two": 1, "three": 0, "four": 0, "high": 0}
    assert m["ladderHeightUnknown"] == 1     # 600009 披露不可算，不进 high 桶
    assert m["maxBoard"] == 2                # 不得把 16天8板的 8 当最高板


def test_market_metrics_ladder_touch_fallback_when_ths_missing():
    """今日 THS 炸板池缺失 → 封板不可二分：回退触板池按 M 分桶并标 touch_range（旧口径披露）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-09-30")]),   # 无 thsPools
        "jiuyan_action": FakeCol([_jiuyan_final("2026-09-30", [1, 2, 3, 8])]),
    })
    db.cols["jiuyan_action"].rows[0]["fields"][0]["stocks"][3]["num"] = "16天8板"
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "jiuyan_touch"
    assert m["ladder"] == {"one": 1, "two": 1, "three": 1, "four": 0, "high": 1}
    assert m["maxBoard"] is None             # 真连板不可算 → 不拿区间 M 冒充
    assert m["maxBoardRange"] == 6           # 帧区间值保留（叙事里标「区间」）


def test_market_metrics_ladder_ths_fallback_when_jiuyan_missing():
    """jiuyan final 缺失 → THS 回退并标注来源。"""
    ths = {"one": {"total": 25}, "two": {"total": 3}, "three": {"total": 3},
           "four": {"total": 0}, "high": {"total": 1}}
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-09-30", ths_pools=ths)]),
        "jiuyan_action": FakeCol([]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "ths"
    assert m["ladder"] == {"one": 25, "two": 3, "three": 3, "four": 0, "high": 1}
    assert m["thsLadder"] == m["ladder"]


def test_market_metrics_ladder_both_missing_fail_visible():
    """双源皆缺 → ladder 全 None + source=missing，绝不伪造零梯队。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-09-30", ths_pools={})]),
        "jiuyan_action": FakeCol([]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "missing"
    assert all(v is None for v in m["ladder"].values())
    assert m["thsLadder"] is None


def test_market_metrics_ladder_day_unmarked_prev_disclosed():
    """num=None 且昨日已封板 = 真连板被漏标：不入桶，计入 ladderDayUnmarkedPrev 披露。

    §2.1 明写这条披露路径，但梯队重写后夹具昨日池为空、`prev_sealed is None → prev_limit`
    为空，该分支永久不可达、全库 grep 零覆盖（2026-10-16 review 发现）。补回——否则
    「漏标股被当成首板入桶」的回归无人拦。
    """
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_ths("2026-09-30"), _frame_ths("2026-09-29")]),
        "jiuyan_action": FakeCol([
            _jiuyan_final("2026-09-30", [1, None], codes=["600001", "600009"]),
            _jiuyan_final("2026-09-29", [1], codes=["600009"]),      # 600009 昨日确已封板
        ]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "jiuyan"
    assert m["ladder"] == {"one": 1, "two": 0, "three": 0, "four": 0, "high": 0}
    assert m["ladderPoolTotal"] == 1          # 漏标的 600009 不入桶
    assert m["ladderDayUnmarked"] == 1
    assert m["ladderDayUnmarkedPrev"] == 1    # 披露：昨日已封板，高度未知
    # 反证：昨日不在池的 num=None 股是正常首板，照常入桶、不计漏标
    db2 = FakeDb({
        "snapshot_frames": FakeCol([_frame_ths("2026-09-30"), _frame_ths("2026-09-29")]),
        "jiuyan_action": FakeCol([
            _jiuyan_final("2026-09-30", [1, None], codes=["600001", "600009"]),
            _jiuyan_final("2026-09-29", [1], codes=["600010"]),
        ]),
    })
    m2 = market_metrics(db2, "2026-09-30")
    assert m2["ladderDayUnmarkedPrev"] == 0
    assert m2["ladder"] == {"one": 2, "two": 0, "three": 0, "four": 0, "high": 0}


def test_rushing_pool_ok_and_empty_is_legit_zero():
    """冲刺池 ok 且 items 空 = 当日无冲刺股，合法 0；不是「池未拉取」。

    AGENTS §4.0：「取不到」≠「真的 0」。旧实现 `if ths_ok and pools[...].get("items")`
    把空列表当 falsy，合法 0 与池缺失同形，双口径「触板未封」整段静默消失。
    """
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_ths("2026-09-30", failed=[], zt=36, rushing=[])]),
        "jiuyan_action": FakeCol([_jiuyan_final("2026-09-30", [1])]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["rushingCount"] == 0             # 合法 0，不是 None
    line = market_facts_line(db, "2026-09-30")
    assert "触板未封 0 家（含冲刺 0 家），未封率 0.0%（0/36）" in line
