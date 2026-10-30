# -*- coding: utf-8 -*-
"""炸板链「大盘行」历史补数（2026-10-20，用户令「补炸板历史行情」）。

背景（只读生产库实测）：67 个打标日里 **84.5%（1438/1701）** 的炸板文档写「大盘：不可考（帧缺失）」
——因为老 15:00 帧没有 `indices.sh`。而 `broad_market`（大盘拖累）判据在这些样本上等于没有输入。
补法（零写库、不动历史帧）：帧缺时用**上证指数日线重算**涨跌幅，并在行内标实际口径；
帧值与日线重算实测并不等价（10-16 Δ0.08pp、10-19 Δ0.37pp），所以绝不静默混用。

锁定项：
1. 帧有 changePct → 用帧值并标「15:00 帧」（relay/情绪链同源）；
2. 帧只有 change 点位 → 保持「点位口径」（防 -19.19% 假暴跌复发）；
3. 帧无 indices → 本地日线重算并标「本地日线重算」，本地缺当日棒 → 线上指数日线重算；
4. 全缺 → 如实写不可考（不补 0）。
全 fake/monkeypatch，禁网禁真实 jev。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_zhaban_label as lab

DATE = "2026-06-10"


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


@pytest.fixture(autouse=True)
def _clear_cache():
    lab._SH_PCT_CACHE.clear()
    yield
    lab._SH_PCT_CACHE.clear()


def _frame(indices):
    return {"_id": "f", "datasetId": "dragonboard_live", "type": "half_hour",
            "tradingDate": DATE, "slotTime": "15:00", "indices": indices}


# ── _pct_of_date 纯函数 ────────────────────────────────────────────────────
def test_pct_of_date_basic():
    rows = [("2026-06-09", 100.0), ("2026-06-10", 101.0)]
    assert lab._pct_of_date(rows, "2026-06-10") == pytest.approx(1.0)


@pytest.mark.parametrize("rows,target", [
    ([("2026-06-10", 101.0)], "2026-06-10"),                    # 无前一日
    ([("2026-06-09", 100.0)], "2026-06-10"),                    # 无当日
    ([("2026-06-09", 0.0), ("2026-06-10", 101.0)], "2026-06-10"),  # 前收非法
    ([], "2026-06-10"),
])
def test_pct_of_date_returns_none_when_uncomputable(rows, target):
    assert lab._pct_of_date(rows, target) is None


# ── 日线重算源 ─────────────────────────────────────────────────────────────
def test_local_lday_recalc(monkeypatch):
    recs = [(20260609, 0, 0, 0, 371648.0, 0, 0, 0),
            (20260610, 0, 0, 0, 373092.0, 0, 0, 0)]
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: ("D:/FAKE_TDX", "2026-06-10"))
    monkeypatch.setattr("backend.operations.market_dieban_tdx.read_lday",
                        lambda path, take=400: recs)
    pct, src = lab._sh_index_change_pct(_Db(), DATE)
    assert src == "本地日线重算"
    assert pct == pytest.approx((3730.92 - 3716.48) / 3716.48 * 100, abs=1e-6)


def test_falls_back_to_online_when_local_lacks_date(monkeypatch):
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: ("D:/FAKE_TDX", "2026-06-09"))
    monkeypatch.setattr("backend.operations.market_dieban_tdx.read_lday",
                        lambda path, take=400: [(20260609, 0, 0, 0, 371648.0, 0, 0, 0)])

    class _Row(dict):
        pass

    import pandas as pd
    df = pd.DataFrame([{"year": 2026, "month": 6, "day": 9, "close": 3716.48},
                       {"year": 2026, "month": 6, "day": 10, "close": 3730.92}])

    class _Client:
        def index_bars(self, **kwargs):
            assert kwargs["symbol"] == "999999"
            return df

    monkeypatch.setattr(lab, "_tdx_daily_client", lambda: _Client())
    pct, src = lab._sh_index_change_pct(_Db(), DATE)
    assert src == "线上指数日线重算"
    assert pct == pytest.approx(0.3895, abs=0.01)


def test_all_sources_missing_returns_none(monkeypatch):
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: (None, None))
    monkeypatch.setattr(lab, "_tdx_daily_client", lambda: None)
    assert lab._sh_index_change_pct(_Db(), DATE) == (None, None)


# ── 叙事行口径 ─────────────────────────────────────────────────────────────
def _narrative(db, **kw):
    item = {"code": "603186", "name": "华正新材", "time_preview": [10.0],
            "open_num": 1, "change_rate": 9.1, "turnover_rate": 14.1,
            "currency_value": 2.56e10}
    monkeypatch_args = kw
    return lab.build_zhaban_narrative(db, DATE, item, {}, [], **_anchor(monkeypatch_args))


def _anchor(_kw):
    return {}


def test_market_line_uses_frame_pct(monkeypatch):
    monkeypatch.setattr(lab, "_limitup_sequence_line", lambda *a, **k: "板序：桩")
    monkeypatch.setattr(lab, "ths_positions", lambda *a, **k: {})
    db = _Db({"snapshot_frames": _Col([_frame({"sh": {"changePct": -0.62}})])})
    text = _narrative(db)
    assert "大盘：上证今日 -0.62%" in text, "2026-10-30g+：来源注删"


def test_market_line_keeps_point_caliber(monkeypatch):
    """存量帧只有点位：不得按 % 呈现（10-12 假暴跌 -19.19% 事故口径）。"""
    monkeypatch.setattr(lab, "_limitup_sequence_line", lambda *a, **k: "板序：桩")
    monkeypatch.setattr(lab, "ths_positions", lambda *a, **k: {})
    db = _Db({"snapshot_frames": _Col([_frame({"sh": {"change": -19.19}})])})
    text = _narrative(db)
    assert "大盘：上证今日 -19.19 点" in text, "2026-10-30g+：口径注删"
    assert "-19.19%" not in text


def test_market_line_falls_back_to_daily_recalc(monkeypatch):
    monkeypatch.setattr(lab, "_limitup_sequence_line", lambda *a, **k: "板序：桩")
    monkeypatch.setattr(lab, "ths_positions", lambda *a, **k: {})
    recs = [(20260609, 0, 0, 0, 371648.0, 0, 0, 0),
            (20260610, 0, 0, 0, 373092.0, 0, 0, 0)]
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: ("D:/FAKE_TDX", "2026-06-10"))
    monkeypatch.setattr("backend.operations.market_dieban_tdx.read_lday",
                        lambda path, take=400: recs)
    text = _narrative(_Db({"snapshot_frames": _Col([_frame({})])}))
    assert "本地日线重算" not in text, "2026-10-30g+：来源注删"


def test_market_line_fail_visible_when_everything_missing(monkeypatch):
    monkeypatch.setattr(lab, "_limitup_sequence_line", lambda *a, **k: "板序：桩")
    monkeypatch.setattr(lab, "ths_positions", lambda *a, **k: {})
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: (None, None))
    monkeypatch.setattr(lab, "_tdx_daily_client", lambda: None)
    text = _narrative(_Db())
    assert "大盘：不可考" in text, "2026-10-30g+：括号删"
    assert "0.00%" not in text
