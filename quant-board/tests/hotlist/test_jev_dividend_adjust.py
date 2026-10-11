# -*- coding: utf-8 -*-
"""P1-1 除权修正因子 + P1-2 zhaban 昨日 THS 身位测试（预登记 jev-ammo-p1-preregistration.md）。

纯函数/全 fake，禁触真实 jev 调用与真实 akshare 网络（AGENTS.md §1.2-7）。
P1-1 定案口径（预登记 §一附录）：百度除权除息日程（每10股口径）× 交易所公式
参考价 = round((前收 − 每股分红)/(1 + 每股送转), 2)；可信带=当日真实涨跌幅 ≤ 涨幅板+5pp。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.analysis.hotlist import jev_driver_ammo as ammo
from backend.analysis.hotlist.jev_driver_ammo import (
    position_line_from_bars,
    sequence_line_from_bars,
)


# ── P1-1 纯函数 ──

def _cash_div_case():
    """10 元股派现 0.5（每10股3元）：昨收(t)=9.50；t 日收 10.45=真实涨停（9.50×1.1）。"""
    bars = [{"date": "2026-06-01", "high": 10.2, "close": 10.0, "vol": 100.0},
            {"date": "2026-06-02", "high": 10.45, "close": 10.45, "vol": 200.0}]
    adj_prev = {"2026-06-02": 9.50}
    return bars, adj_prev


def test_sequence_line_detects_exdiv_limit_up():
    """板序假阴根治：除权日真实涨停（10.45 vs 参考价 9.50）必须判 ●，原口径=假阴。"""
    bars, adj_prev = _cash_div_case()
    fixed = sequence_line_from_bars("2026-06-02", "600000", None, 2, bars, adj_prev)
    assert "近 1 日 ●" in fixed and "除权修正已应用" in fixed
    assert "当前连板 1" in fixed
    raw = sequence_line_from_bars("2026-06-02", "600000", None, 2, bars, None)
    assert "近 1 日 ○" in raw and "当前连板 0" in raw  # 原口径假阴（旧已知边缘）
    assert "除权修正" not in raw


def test_position_line_exdiv_no_fake_crash():
    """位置轴：除权前一日归一至今日基准=9.50，窗口涨幅不被除权伪装成暴跌。"""
    bars, adj_prev = _cash_div_case()
    line = position_line_from_bars("2026-06-02", "600000", bars, adj_prev)
    assert "除权修正已应用" in line
    assert "最低收盘 9.50" in line and "+10.0%" in line
    raw = position_line_from_bars("2026-06-02", "600000", bars, None)
    assert "除权修正" not in raw  # 无参考价=原口径不注记


def test_div_scale_map_recurrence():
    """两连除权事件反向递推：scale(t)=scale(t+1)×参考价(t+1)/raw(t)。"""
    window = [{"date": "2026-06-01", "high": 10.0, "close": 10.0, "vol": 1.0},
              {"date": "2026-06-02", "high": 10.45, "close": 10.45, "vol": 1.0},
              {"date": "2026-06-03", "high": 10.95, "close": 10.95, "vol": 1.0}]
    adj_prev = {"2026-06-02": 9.50, "2026-06-03": 9.95}
    scale = ammo._div_scale_map(window, adj_prev)
    assert abs(scale["2026-06-03"] - 1.0) < 1e-12
    assert abs(scale["2026-06-02"] - 9.95 / 10.45) < 1e-9
    assert abs(scale["2026-06-01"] - 9.95 / 10.45 * 9.50 / 10.0) < 1e-9


def test_adj_prev_series_no_event_day(monkeypatch):
    """非除权股：事件表无该股 → 空 series（原口径），且不触网（_div_event_list 打桩）。"""
    import backend.operations.jev_label_jiuyan as runner
    monkeypatch.setattr(runner, "_div_event_list", lambda date: {})
    bars = [{"date": "2026-06-01", "high": 10.0, "close": 10.0, "vol": 100.0},
            {"date": "2026-06-02", "high": 5.5, "close": 5.5, "vol": 400.0}]
    assert runner._adj_prev_series("2026-06-02", "600000", bars) == {}


def test_adj_prev_series_band_guard(monkeypatch):
    """review P1-3 可信带：配股混合事件算出越界参考价（当日涨跌幅超板+5pp）→ 该链接剔出。"""
    import backend.operations.jev_label_jiuyan as runner
    bars = [{"date": "2026-06-01", "high": 20.0, "close": 20.0, "vol": 100.0},
            {"date": "2026-06-02", "high": 16.6, "close": 16.5, "vol": 400.0}]
    # 配股混合（百度表无配股价）：公式给 (20-0)/1=20 → close/参考价=0.825=-17.5% 超板 → 剔除
    monkeypatch.setattr(runner, "_div_event_list", lambda date: {"600000": (0.0, 0.0)})
    assert runner._adj_prev_series("2026-06-02", "600000", bars) == {}
    # 正常除息：参考价 19.0，close 20.45=+7.6% 带内 → 保留
    bars2 = [{"date": "2026-06-01", "high": 20.0, "close": 20.0, "vol": 100.0},
             {"date": "2026-06-02", "high": 20.45, "close": 20.45, "vol": 400.0}]
    monkeypatch.setattr(runner, "_div_event_list", lambda date: {"600000": (1.0, 0.0)})
    out = runner._adj_prev_series("2026-06-02", "600000", bars2)
    assert out == {"2026-06-02": 19.0}


def test_adj_prev_series_rejects_nonpositive_ref(monkeypatch):
    """review P2-3：分红>股价的退化参考价（≤0）不得进 map。"""
    import backend.operations.jev_label_jiuyan as runner
    bars = [{"date": "2026-06-01", "high": 1.0, "close": 1.0, "vol": 100.0},
            {"date": "2026-06-02", "high": 1.0, "close": 1.0, "vol": 100.0}]
    monkeypatch.setattr(runner, "_div_event_list", lambda date: {"600000": (2.0, 0.0)})
    assert runner._adj_prev_series("2026-06-02", "600000", bars) == {}


def test_none_adj_prev_is_identity():
    bars = _cash_div_case()[0]
    line = sequence_line_from_bars("2026-06-02", "600000", None, 2, bars, {})
    assert "除权修正" not in line  # 空 map=原口径


# ── P1-1 壳 wiring（事件表失败=原口径，不触网） ──

def test_shell_wiring_adj_series_hit(monkeypatch):
    bars, adj_prev = _cash_div_case()
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    monkeypatch.setattr(runner, "_adj_prev_series", lambda date, code, bars_: adj_prev)
    line = runner.limitup_sequence_line("2026-06-02", "600000", None, n=2)
    assert "●" in line and "除权修正已应用" in line
    pos = runner.stock_position_line("2026-06-02", "600000")
    assert "除权修正已应用" in pos
    assert abs(runner._prev_close_of_date("2026-06-02", "600000") - 9.50) < 1e-9


def test_shell_wiring_adj_series_miss_falls_back(monkeypatch):
    bars = _cash_div_case()[0]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    monkeypatch.setattr(runner, "_adj_prev_series", lambda date, code, bars_: {})
    line = runner.limitup_sequence_line("2026-06-02", "600000", None, n=2)
    assert "除权修正" not in line  # 非除权股=原口径无注记
    assert runner._prev_close_of_date("2026-06-02", "600000") == 10.0


def test_div_event_list_parses_baidu_rows(monkeypatch):
    """百度日程解析：每10股口径归一每股、非 SH/SZ 剔除、'-' 解析为 0。"""
    import sys
    import types

    import pandas as pd

    fake = types.ModuleType("akshare")
    fake.news_trade_notify_dividend_baidu = lambda date: pd.DataFrame([
        {"股票代码": "603337", "除权日": "2026-10-09", "分红": "3.00元", "送股": "-",
         "转增": "-", "实物": "-", "交易所": "SH", "股票简称": "XD杰克科", "报告期": "2026-10-09"},
        {"股票代码": "300919", "除权日": "2026-10-09", "分红": "3.80元", "送股": "2股",
         "转增": "3股", "实物": "-", "交易所": "SZ", "股票简称": "X", "报告期": "2026-10-09"},
        {"股票代码": "01398", "除权日": "2026-10-09", "分红": "0.15港元", "送股": "-",
         "转增": "-", "实物": "-", "交易所": "HK", "股票简称": "工商银行", "报告期": "2026-10-09"},
    ])
    monkeypatch.setitem(sys.modules, "akshare", fake)
    runner._DIV_LIST_CACHE.clear()
    out = runner._div_event_list("2026-10-09")
    assert out["603337"] == (0.30, 0.0)            # 每10股3元 → 每股 0.30
    assert out["300919"] == (0.38, 0.5)            # 每10股3.8元+送2转3 → 每股 0.38、送转 0.5
    assert "01398" not in out                       # HK 剔除
    assert runner._DIV_LIST_CACHE["2026-10-09"] == out  # 缓存
    runner._DIV_LIST_CACHE.clear()                  # review P2-1：不残留跨用例


# ── P1-2 zhaban 昨日 THS 身位 ──

class _FrameCol:
    def __init__(self, frames):
        self.frames = frames

    def find(self, query, projection=None):
        def match(f):
            for k, v in query.items():
                if isinstance(v, dict):
                    if "$lt" in v and not (f.get(k) and f[k] < v["$lt"]):
                        return False
                    continue
                if f.get(k) != v:
                    return False
            return True
        return iter([f for f in self.frames if match(f)])

    def find_one(self, query, projection=None, sort=None):
        for f in self.find(query):
            return f
        return None


class _ZhabanCol:
    def __init__(self):
        self.docs = {}

    def find_one(self, query, projection=None):
        doc = self.docs.get(query.get("_id"))
        return doc if doc and all(doc.get(k) == v for k, v in query.items() if k != "_id") else None

    def replace_one(self, query, doc, upsert=False):
        self.docs[query.get("_id")] = doc


class _ZhabanDb:
    def __init__(self, frames, zhaban_col: _ZhabanCol | None = None):
        self._frames = _FrameCol(frames)
        self.zhaban_col = zhaban_col

    def __getitem__(self, name):
        if name == "snapshot_frames":
            return self._frames
        if name == "hotlist_jev_zhaban_labels" and self.zhaban_col is not None:
            return self.zhaban_col
        return _FrameCol([])  # jiuyan_action 等：prev pool 缺失走 fail-visible 分支


def _ths_frame(date, items):
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "_id": f"f:{date}",
            "limitSummary": {"thsPools": {"pools": {"one": {"items": items}}}}}


def _zhaban_item(code="600000"):
    return {"code": code, "name": "甲", "open_num": 2, "change_rate": -2.1,
            "turnover_rate": 15.0, "currency_value": 5.0e9,
            "time_preview": [0, 3, 6, 9.8, 9.9, 9.8, 8.0, 7.5, 7.0, 6.5, 6.0]}


def test_zhaban_narrative_ths_prev_hit(monkeypatch):
    from backend.operations import jev_zhaban_label as zb
    runner._THS_CACHE.clear()  # ths_positions 模块级缓存跨用例隔离
    monkeypatch.setattr(zb, "_limitup_sequence_line",
                        lambda date, code, name, n=10: "板序：近 10 日 ○●○（测试桩）")
    db = _ZhabanDb([
        _ths_frame("2026-09-17", [{"stock_code": "600000", "continue_day": "2连板",
                                   "limit_up_time": "09:42:00", "industry_block": "机器人"}]),
        _ths_frame("2026-09-18", []),
    ])
    line = zb.build_zhaban_narrative(db, "2026-09-18", _zhaban_item(), {}, [])
    assert "昨日身位（THS 连板梯队）：昨日2连板" in line
    assert "梯队 one" in line and "首封 09:42:00" in line


def test_zhaban_narrative_ths_prev_miss_fail_visible(monkeypatch):
    from backend.operations import jev_zhaban_label as zb
    runner._THS_CACHE.clear()  # ths_positions 模块级缓存跨用例隔离
    monkeypatch.setattr(zb, "_limitup_sequence_line",
                        lambda date, code, name, n=10: "板序：近 10 日 ○（测试桩）")
    db = _ZhabanDb([_ths_frame("2026-09-17", [{"stock_code": "000001", "continue_day": 1}]),
                    _ths_frame("2026-09-18", [])])
    line = zb.build_zhaban_narrative(db, "2026-09-18", _zhaban_item(), {}, [])
    assert "未收录（昨日未涨停或 THS 池缺口，fail-visible）" in line


def test_zhaban_doc_stamps_ammo_version(monkeypatch):
    """新文档盖 ZHABAN_AMMO_VERSION 戳 + answers 原样包（P0-2/P1-2 落库合同）。"""
    from backend.operations import jev_zhaban_label as zb
    runner._THS_CACHE.clear()
    col = _ZhabanCol()
    db = _ZhabanDb([_ths_frame("2026-09-17", [{"stock_code": "600000", "continue_day": 2,
                                               "limit_up_time": "09:42:00"}]),
                    _ths_frame("2026-09-18", [])], zhaban_col=col)
    monkeypatch.setattr(zb, "_ths_failed_snapshot", lambda db_, date, ds: ([_zhaban_item()], True))
    monkeypatch.setattr(zb, "_pool_of", lambda db_, date: {"600000": {"board": "机器人", "boards": 2}})
    monkeypatch.setattr(zb, "_limitup_sequence_line",
                        lambda date, code, name, n=10: "板序：近 10 日 ○（测试桩）")
    def _fake_dispatch(narrative, questions):
        envelope = {"result": {"state": "Completed",
                               "result": {"model": "m",
                                          "answers": {"zhaban_cause": {
                                              "type": "choice", "choice": "chase_fail",
                                              "confidence": 0.7,
                                              "probabilities": {"chase_fail": 0.7}}},
                                          "usage": {"input_tokens": 10, "output_tokens": 2}}}}
        return envelope, 100

    monkeypatch.setattr(zb, "_dispatch_jev", _fake_dispatch)
    zb.run_zhaban_label_day(db, ["2026-09-18"])
    doc = col.docs["2026-09-18:600000"]
    assert doc["ammoVersion"] == zb.ZHABAN_AMMO_VERSION
    assert doc["answers"]["zhaban_cause"]["confidence"] == 0.7
    assert doc["zhabanCause"] == "chase_fail"
    assert "昨日身位（THS 连板梯队）" in doc["narrative"]
