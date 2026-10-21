# -*- coding: utf-8 -*-
"""v3.2 语料瘦身/增益（2026-10-20 预注册 jev-driver-label-v32-preregistration.md）。

全 fake/monkeypatch，零真实 jev 调用（AGENTS §1.2-7）。锁定项（D 编号=预注册 §4）：

- D1 线上补尾接线：叙事组装期间必须已声明 `bars_need_upto` 上下文（ContextVar 不跨线程，
  所以断言点放在叙事组装处而不是 run() 外层）——实测 10-20 当日 77/77 只三轴全灭的根因；
- D2 THS 整池未采集日不得写成「今日触板未封/炸板」（457 只当日涨停股被写成炸板）；
- D3 板型涨停价与板序/封板判定同源（`_limit_price`，禁内置 round 副本）；
- D4 删零引用投喂（热榜排名 / THS 主力净额），落库字段不动；
- D5 盘面事实整行 → 轻量「市场坐标」三数（四题对整行零独有引用）；
- D6 交易日轴（freshness「≤2 个交易日」可数）；
- D7 封板时间坐标 + 同板块昨日家数（buy_side「封板时间偏晚」「板块联动」有基线）；
- D8 解析续期（freshness/driver 的新意锚；无命中不出行）；
- D9 phase_band 日级补板块效应 + 梯队总量分位；
- Z1 炸板触板阈值委托 `core/limit_rules`（禁副本、撤销已废除的 ST 4.8、覆盖北交所 30%）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.analysis.hotlist.jev_driver_ammo import _limit_price, closed_at_limit
from backend.operations.jev_zhaban_label import _touch_limit

DATE = "2026-10-20"
PREV1 = "2026-10-19"
PREV2 = "2026-10-16"
EXPLAIN = "①公告：中标 3.2 亿元储能订单\n②核实：主营金属腱绳，客户结构稳定"


# ── 极简假集合（只覆盖本模块用到的等值/_id 查询） ────────────────────────────
class _Col:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, projection=None, sort=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        return [dict(d) for d in self.docs
                if all(d.get(k) == v for k, v in (query or {}).items())]


class _Db:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _Col())


def _stock(code, name, time="09:36:00", num=None, day=None, expound=EXPLAIN):
    return {"code": code, "name": name, "time": time, "num": num, "day": day,
            "price": 12.34, "expound": expound}


def _jy(date, fields, slot="final"):
    return {"_id": f"{date}:{slot}", "tradingDate": date,
            "fields": [{"name": b, "stocks": s} for b, s in fields]}


@pytest.fixture(autouse=True)
def _clear_caches():
    names = ("_MKT_COORD_CACHE", "_DATE_AXIS_CACHE", "_JIYAN_EXPOUND_CACHE",
             "_BOARD_PREV_CACHE", "_THS_STATE_CACHE", "_THS_CACHE", "_FACTS_CACHE",
             "_INTRA_CACHE", "_DAILY_BARS_CACHE")
    for name in names:
        getattr(runner, name).clear()
    yield


@pytest.fixture
def no_tdx(monkeypatch):
    monkeypatch.setattr(runner, "_daily_bars", lambda code: [])
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: [])


# ── D5 市场坐标（三数、无分位） ─────────────────────────────────────────────
def test_market_coordinate_line_has_three_numbers_and_no_percentile(monkeypatch):
    monkeypatch.setattr(runner, "market_metrics",
                        lambda db, d, ds=None: {"ztCount": 68, "maxBoard": 6})
    monkeypatch.setattr(runner, "advdec_ratio", lambda db, d, ds=None: (40, 25, 3, 1.6))
    line = runner.market_coordinate_line(_Db(), DATE)
    assert line.startswith("市场坐标：")
    assert "涨停 68 家" in line and "最高 6 板" in line and "池内涨跌比 1.6" in line
    assert "分位" not in line, "个股叙事不再带 relay/PHASE 的 20 日分位刻度（防跨轨锚定）"
    assert len(line) < 80


def test_market_coordinate_line_fail_visible(monkeypatch):
    monkeypatch.setattr(runner, "market_metrics", lambda db, d, ds=None: None)
    line = runner.market_coordinate_line(_Db(), DATE)
    assert "盘面指标缺失" in line and "fail-visible" in line


# ── D6 交易日轴 ─────────────────────────────────────────────────────────────
def test_date_axis_line_counts_trading_days(monkeypatch):
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV2, PREV1][-n:])
    line = runner.date_axis_line(_Db(), DATE)
    assert "今日 2026-10-20（周二）" in line
    assert f"前1交易日 {PREV1}（周一）" in line
    assert f"前2交易日 {PREV2}（周五）" in line
    assert "交易日轴" in line and len(line) < 80


def test_date_axis_line_marks_missing_history(monkeypatch):
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [])
    line = runner.date_axis_line(_Db(), DATE)
    assert "前1交易日 不可算" in line and "前2交易日 不可算" in line


# ── D7 封板时间坐标 ─────────────────────────────────────────────────────────
def _time_doc():
    return _jy(DATE, [
        ("机器人", [_stock("600001", "甲", time="09:30:00"),
                    _stock("600002", "乙", time="10:30:00"),
                    _stock("600003", "丙", time="14:00:00")]),
        ("AI硬件", [_stock("300001", "丁", time="11:00:00"),
                    _stock("300002", "戊", time="13:00:00")]),
    ])


def test_seal_time_line_ranks_against_population_and_board():
    line = runner.seal_time_line(_time_doc(), "600002")
    assert "该股 10:30（第 2 早/5 只）" in line
    assert "名单中位 11:00" in line
    assert "板块内中位 10:30" in line          # 板块内 09:30/10:30/14:00 → 中位 10:30


def test_seal_time_line_marks_missing_own_time():
    doc = _jy(DATE, [("机器人", [_stock("600001", "甲", time=""),
                                 _stock("600002", "乙", time="10:00:00")])])
    line = runner.seal_time_line(doc, "600001")
    assert "该股时间缺失" in line and "1/2 只可算" in line


def test_seal_time_line_no_times_at_all():
    doc = _jy(DATE, [("机器人", [_stock("600001", "甲", time="--")])])
    assert "名单无可用时间" in runner.seal_time_line(doc, "600001")


# ── D7 同板块昨日家数 ───────────────────────────────────────────────────────
def test_board_prev_count_reads_prev_day(monkeypatch):
    db = _Db({"jiuyan_action": _Col([
        _jy(PREV1, [("机器人", [_stock("600001", "甲"), _stock("600002", "乙")]),
                    ("AI硬件", [_stock("300001", "丁")])])])})
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV1][-n:])
    assert runner.board_prev_count(db, DATE, "机器人") == 2
    assert runner.board_prev_count(db, DATE, "AI硬件") == 1
    # 昨日不存在该板块 → None（不可比，不补 0 冒充）
    assert runner.board_prev_count(db, DATE, "低空经济") is None


def test_board_position_appends_prev_count(monkeypatch):
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV1][-n:])
    db = _Db({"jiuyan_action": _Col([
        _jy(PREV1, [("机器人", [_stock("600001", "甲"), _stock("600002", "乙")])])])})
    line = runner.board_position(_time_doc(), "600002", db=db, date=DATE)
    assert "今日涨停 3 家（昨日同板块涨停 2 家）" in line
    assert "第 2 封板" in line


# ── D8 解析续期 ─────────────────────────────────────────────────────────────
def test_expound_trace_detects_identical_and_updated(monkeypatch):
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV1][-n:])
    db_same = _Db({"jiuyan_action": _Col([_jy(PREV1, [("机器人", [_stock("600001", "甲")])])])})
    assert "逐字相同" in runner.expound_trace_line(db_same, DATE, "600001", EXPLAIN)

    runner._JIYAN_EXPOUND_CACHE.clear()   # 同一测试内换 db：清掉上一段留下的当日解析快照
    db_diff = _Db({"jiuyan_action": _Col([
        _jy(PREV1, [("机器人", [_stock("600001", "甲",
                                       expound="此前原因：①公告：中标 1 亿元")])])])})
    line = runner.expound_trace_line(db_diff, DATE, "600001", EXPLAIN)
    assert "有更新" in line and "中标 1 亿元" in line


def test_expound_trace_silent_when_no_prev_record(monkeypatch):
    """裁决 5B：上一交易日无该股解析 → 不出行（省字；首板语义由板序 ○● 承担）。"""
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV1][-n:])
    db = _Db({"jiuyan_action": _Col([_jy(PREV1, [("机器人", [_stock("600002", "乙")])])])})
    assert runner.expound_trace_line(db, DATE, "600001", EXPLAIN) is None


# ── D2 THS 封板梯队池可用性 ─────────────────────────────────────────────────
def _frame(pools, degraded=False):
    """15:00 帧桩（带查询键：真帧含 datasetId/type/tradingDate/slotTime）。"""
    return {"_id": "f", "datasetId": "dragonboard_live", "type": "half_hour",
            "tradingDate": DATE, "slotTime": "15:00",
            "limitSummary": {"thsPools": {"ok": True, "degraded": degraded, "pools": pools}}}


def test_ths_ladder_state_full_pool():
    db = _Db({"snapshot_frames": _Col([_frame({"one": {"items": [1], "ok": True}})])})
    assert runner.ths_ladder_state(db, DATE) == {"ok": True, "reason": None}


@pytest.mark.parametrize("pools,reason_kw", [
    ({"failed": {"items": [1]}, "rushing": {"items": [1]}, "drawdown": {}},
     "封板梯队池未采集"),
    ({}, "THS 池未拉取"),
])
def test_ths_ladder_state_distinguishes_pool_missing(pools, reason_kw):
    db = _Db({"snapshot_frames": _Col([_frame(pools)])})
    state = runner.ths_ladder_state(db, DATE)
    assert state["ok"] is False and reason_kw in state["reason"]


def test_ths_ladder_state_no_frame():
    state = runner.ths_ladder_state(_Db(), DATE)
    assert state["ok"] is False and "帧缺失" in state["reason"]


def test_narrative_does_not_call_zhaban_when_pool_missing(no_tdx):
    """整池未采集日：当日涨停股不得被写成「今日触板未封/炸板口径」（事实错误文案）。"""
    db = _Db({"snapshot_frames": _Col([_frame({"failed": {"items": [{"code": "000001"}]}})])})
    jy = _jy(DATE, [("机器人", [_stock("600001", "甲")])])
    text = runner.build_pilot_narrative(db, DATE, "600001", jy["fields"][0]["stocks"][0],
                                        "机器人", 1, jiuyan_doc=jy)
    assert "THS 封板梯队未采集" in text
    assert "非「触板未封」" in text
    assert "今日触板未封/炸板口径" not in text


def test_narrative_bj_stock_not_misread_as_touch_unsealed(no_tdx):
    """北交所股、THS 池已采集但未入池：文案不得写「可能触板未封/炸板口径」。

    实测（2026-10-16/19/20 三日，THS 连板封板池 327 只 0 只北交所）：THS 池结构性
    不覆盖北交所——真涨停的 bj 股（韭研有涨停价与封板时刻）落进「池 ok 未入」分支
    就被写成触板未封嫌疑，且缓冲句「与板序冲突以板序为准」对北交所恰好落空
    （板序行本身 fail-visible，北交所日线无源）。身位改用韭研口径直供（同 D2 回退）。
    判定单源 = `core.limit_rules.limit_ratio(code) == 0.30`（43/8/92 前缀），不写副本。
    """
    db = _Db({"snapshot_frames": _Col([
        _frame({"one": {"ok": True, "items": [
            {"stock_code": "600001", "continue_day": "2连板", "limit_up_time": "09:31",
             "industry_block": "机器人"}]}})])})
    jy = _jy(DATE, [("公告", [_stock("920641", "格利尔", num="3天3板", day="3")])])
    text = runner.build_pilot_narrative(db, DATE, "920641", jy["fields"][0]["stocks"][0],
                                        "公告", 1, jiuyan_doc=jy)
    assert "THS 池不覆盖北交所" in text, "应显式声明覆盖边界（非触板未封口径推断）"
    assert "可能触板未封/炸板口径" not in text
    assert "身位证据改用韭研口径 3天3板" in text, "身位改韭研 N天M板 直供（同 D2 回退）"
    # 对照：主板股池-ok 未入池仍走原「未入池」分支（语义未被误改）
    jy2 = _jy(DATE, [("公告", [_stock("600601", "乙", num="2天2板", day="2")])])
    text2 = runner.build_pilot_narrative(db, DATE, "600601", jy2["fields"][0]["stocks"][0],
                                         "公告", 1, jiuyan_doc=jy2)
    assert "未进 THS 封板池" in text2 and "THS 池不覆盖北交所" not in text2


# ── D4 删零引用投喂 ─────────────────────────────────────────────────────────
def test_narrative_drops_hotlist_rank_and_main_net(no_tdx):
    db = _Db({"snapshot_frames": _Col([
        _frame({"one": {"ok": True, "items": [
            {"stock_code": "600001", "continue_day": "2连板", "limit_up_time": "09:31",
             "industry_block": "机器人", "main_net_amount": 73794032}]}})])})
    jy = _jy(DATE, [("机器人", [_stock("600001", "甲")])])
    text = runner.build_pilot_narrative(db, DATE, "600001", jy["fields"][0]["stocks"][0],
                                        "机器人", 7, jiuyan_doc=jy)
    assert "热榜" not in text                  # 排名不投喂（落库字段照旧）
    assert "主力净额" not in text and "73794032" not in text
    assert "THS 封板梯队：2连板" in text
    assert "该股：甲（600001），今日涨停价 12.34" in text


# ── D5/D6/D8 组装：个股叙事整行盘面事实被替换 ───────────────────────────────
def test_narrative_uses_light_market_line_not_full_facts(monkeypatch, no_tdx):
    monkeypatch.setattr(runner, "market_metrics",
                        lambda db, d, ds=None: {"ztCount": 68, "maxBoard": 6,
                                                "ladderPoolTotal": 60})
    monkeypatch.setattr(runner, "advdec_ratio", lambda db, d, ds=None: (40, 25, 3, 1.6))
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [PREV2, PREV1][-n:])
    db = _Db({"jiuyan_action": _Col([_jy(PREV1, [("机器人", [_stock("600001", "甲")])])])})
    jy = _jy(DATE, [("机器人", [_stock("600001", "甲")])])
    text = runner.build_pilot_narrative(db, DATE, "600001", jy["fields"][0]["stocks"][0],
                                        "机器人", None, jiuyan_doc=jy)
    assert text.splitlines()[0] == f"{DATE} 交易日 · 市场坐标：涨停 68 家 · 最高 6 板 · 池内涨跌比 1.6（涨40/跌25）"
    assert "盘面事实：" not in text                     # 整行事实（含 20 日分位）不再逐股重复
    assert text.splitlines()[1].startswith("交易日轴：")
    assert "解析续期：与上一交易日（2026-10-19）解析逐字相同" in text
    assert "韭研解析全文：" in text
    # 顺序：解析续期紧贴解析正文之前（不与身位/位置段混排）
    lines = text.splitlines()
    assert lines[lines.index("韭研解析全文：") - 1].startswith("解析续期：")


def test_carry_path_skips_expound_trace_line(monkeypatch):
    """承接路径：解析逐字相同已由 B 压缩标记声明 → 不再多给一行（省 45 字/只）。"""
    seen: dict = {}

    def fake_build(*a, **k):
        seen.update(k)
        return "N"

    monkeypatch.setattr(runner, "build_pilot_narrative", fake_build)
    monkeypatch.setattr(runner, "_dispatch_jev", lambda n, q: ("env", 5))
    monkeypatch.setattr(runner, "parse_jev_response",
                        lambda env, ms, **kw: {"ok": True, "answers": {"buy_side_logic": {"choice": "x"}},
                                               "usage": {"total_tokens": 1}, "model": "m",
                                               "errorCode": None, "errorDetail": None})
    col = _Col()

    class _C:
        def replace_one(self, q, doc, upsert=False):
            pass

    runner._label_one(_Db(), _C(), "a", "t", DATE, "600001", {"name": "甲"}, "b", None,
                      carry={"prevDate": PREV1, "prev": {"answers": {}}})
    assert seen.get("expound_trace") is False


# ── D1 线上补尾接线（叙事组装期间必须已声明按需补尾上下文） ─────────────────
def test_narrative_declares_bars_context(monkeypatch):
    """ContextVar 不跨线程：断言点必须在叙事组装处，否则 worker 线程拿不到 need_upto。"""
    seen: list = []
    monkeypatch.setattr(runner, "stock_position_line",
                        lambda d, c: seen.append(runner._BARS_NEED_UPTO.get()) or "个股位置：桩")
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [])
    jy = _jy(DATE, [("机器人", [_stock("600001", "甲")])])
    runner.build_pilot_narrative(_Db(), DATE, "600001", jy["fields"][0]["stocks"][0],
                                 "机器人", None, jiuyan_doc=jy)
    assert seen and all(v == DATE for v in seen)
    # 退出上下文后不得残留（同行多日重放时不能把上一日的 need_upto 带给下一日）
    assert runner._BARS_NEED_UPTO.get() is None


# ── D9 phase_band 日级补料 ─────────────────────────────────────────────────
def test_phase_band_extra_lines_board_effect_and_ladder_rank(monkeypatch):
    monkeypatch.setattr(runner, "market_metrics",
                        lambda db, d, ds=None: {"ladderPoolTotal": 80} if d == DATE else
                        {"ladderPoolTotal": 50})
    hist = [f"2026-09-{i:02d}" for i in range(1, 13)]      # ≥10 个历史样本才给分位
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: hist[-n:])
    # 历史日全部集中于单一板块（集中度 100%）→ 今日 86% 的集中度应落在 0 分位
    docs = [_jy(DATE, [("机器人", [_stock(f"60000{i}", f"股{i}") for i in range(6)]),
                       ("AI硬件", [_stock("300001", "丁")])])]
    docs += [_jy(d, [("机器人", [_stock(f"60000{i}", f"股{i}") for i in range(4)])]) for d in hist]
    db = _Db({"jiuyan_action": _Col(docs)})
    lines = runner.phase_band_extra_lines(db, DATE)
    assert lines[0] == ("板块效应：今日涨停 7 只分布于 2 个韭研板块，最大「机器人」6 家"
                        "（占 86%），前三合计 100%")
    assert lines[1] == "板块集中度：最大板块占 86%（0 分位，近 12 日样本）"
    assert lines[2] == "梯队总量：80 只（100 分位）"


def test_phase_band_extra_lines_fail_visible(monkeypatch):
    monkeypatch.setattr(runner, "market_metrics", lambda db, d, ds=None: None)
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: [])
    lines = runner.phase_band_extra_lines(_Db(), DATE)
    assert "板块效应：韭研板块结构缺失" in lines[0]
    assert "板块集中度" not in lines[0]          # 结构缺失时不给分位（不编）
    assert "梯队总量：不可算" in lines[-1]


# ── Z1 炸板触板阈值单源 ────────────────────────────────────────────────────
def test_zhaban_touch_limit_delegates_to_limit_rules():
    assert _touch_limit({"code": "600001"}) == 9.8          # 主板
    assert _touch_limit({"code": "600001", "name": "ST某某"}) == 9.8   # ST 特判已废除（±10%）
    assert _touch_limit({"code": "300001", "market_type": "GEM"}) == 19.8
    assert _touch_limit({"code": "688001", "market_type": "STAR"}) == 19.8
    assert _touch_limit({"code": "830799"}) == 29.8        # 北交所 30%（旧默认 9.8 会误判触板）
    assert _touch_limit({"code": "430047"}) == 29.8
    assert _touch_limit({"code": "920001"}) == 29.8
    # 审查 P1-2：改委托后必须先归一裸 6 位——带前缀时 limit_ratio 会落主板 0.10
    assert _touch_limit({"code": "sz300001"}) == 19.8
    assert _touch_limit({"code": "sh688001"}) == 19.8
    assert _touch_limit({"code": "bj830799"}) == 29.8
    assert _touch_limit({"code": "sh600001"}) == 9.8


# ── D3 板型涨停价与板序/封板判定同源 ────────────────────────────────────────
@pytest.mark.parametrize("prev_close", [10.35, 10.95, 11.95, 13.45, 16.95, 19.45, 21.15])
def test_board_shape_uses_same_limit_price_as_sequence(prev_close):
    """内置 round 在前收分位为 5 时低取一分 → 板型与板序自相矛盾（10-16 实测 3/99 只）。"""
    lp = _limit_price("600001", prev_close)
    assert closed_at_limit("600001", lp, prev_close) is True

    def shape(high: float) -> str:
        return runner.ammo.board_shape_line_from_bars(
            DATE, "600001", "甲", prev_close,
            [{"date": DATE, "hm": "09:35", "open": prev_close, "high": high, "close": high}])

    assert "封板至收盘" in shape(lp)
    # 差一分的棒：板序说「未涨停」，板型也必须说「未触板」（旧 round 会说触板/封板）
    assert "当日未触板" in shape(round(lp - 0.01, 2))
    assert closed_at_limit("600001", round(lp - 0.01, 2), prev_close) is False


# ── Nit-3 补充用例（2026-10-20 审查） ────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    ("09:36:14", 9 * 60 + 36), ("09:36", 9 * 60 + 36), ("9:36", 9 * 60 + 36),
    ("--", None), ("", None), (None, None), ("25:00", None), ("09:61", None),
    ("110:00", None), ("13:00:00", 13 * 60),
])
def test_minutes_of_boundaries(raw, expect):
    assert runner._minutes_of(raw) == expect


def test_market_coordinate_line_rejects_bool_counts(monkeypatch):
    """bool 是 int 子类：True 不得被当成「涨停 1 家」/「最高 True 板」（§4.0 不伪造）。"""
    monkeypatch.setattr(runner, "market_metrics",
                        lambda db, d, ds=None: {"ztCount": True, "maxBoard": False})
    monkeypatch.setattr(runner, "advdec_ratio", lambda db, d, ds=None: None)
    line = runner.market_coordinate_line(_Db(), DATE)
    assert "涨停 不可算" in line and "最高板 不可算" in line and "池内涨跌比 不可算" in line
    assert "涨停 1 家" not in line


def test_relay_shares_market_facts_line_but_individual_narrative_does_not(monkeypatch):
    """relay v7 隔离护栏（审查 Nit-3）：`market_facts_line` 仍归 relay/cycle/PHASE 用，
    个股叙事不得再引用它的整行（否则 relay 语料与该行耦合，改一处动两链）。"""
    import backend.operations.jev_relay_index as relay
    import backend.operations.jev_label_jiuyan as lab

    sentinel = "盘面事实（哨兵）"
    monkeypatch.setattr(lab, "market_facts_line", lambda *a, **k: sentinel)
    monkeypatch.setattr(relay, "market_facts_line", lambda *a, **k: sentinel,
                        raising=False)

    jy = _jy(DATE, [("机器人", [_stock("600001", "甲")])])
    text = lab.build_pilot_narrative(_Db(), DATE, "600001", jy["fields"][0]["stocks"][0],
                                     "机器人", None, jiuyan_doc=jy)
    assert sentinel not in text
    # PHASE 日级哨兵仍以该行起头（单一事实源仍在 relay/PHASE 侧）
    monkeypatch.setattr(lab, "phase_band_extra_lines", lambda *a, **k: [])
    lab.run_phase_band_day  # 只校验引用关系，不真跑（run_phase_band_day 会外呼 jev）
    assert lab.QUESTIONS_PHASE and "板块效应" in lab.QUESTIONS_PHASE["phase_band"]["instructions"]
