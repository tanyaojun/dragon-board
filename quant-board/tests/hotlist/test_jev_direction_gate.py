# -*- coding: utf-8 -*-
"""方向线 v4 原料层测试（runner=jev_direction_gate.py）（2026-10-13 审计落地批）——全 mock，零网络零 jev 调用。

覆盖：时点口径无未来函数 / 0 伪装缺失清洗 / 摆动锚算法（与 relay 落库叙事对齐值）/
日终折叠衍生列 / 八块组装形状与黑名单零出现 / 人口过滤统计。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import market_facts as mf  # noqa: E402
from backend.operations import jev_direction_gate as v4  # noqa: E402


# ── 共享事实服务 ────────────────────────────────────────

class FakeCursor(list):
    def sort(self, *a, **k):
        return self


class FakeFrames:
    """snapshot_frames mock：按 (date, slot) 返回帧；帧内容由用例注入。"""

    def __init__(self, frames: dict[tuple[str, str], dict]):
        self.frames = frames

    def find_one(self, q, projection=None, sort=None):
        return self.frames.get((q.get("tradingDate"), q.get("slotTime")))

    def find(self, q, projection=None):
        dates = sorted({d for (d, _s) in self.frames})
        return FakeCursor({"tradingDate": d} for d in dates)


def _frame(zt: int, up=None, down=None, flat=None, zhaban=20, drawdown=11,
           max_board=10, failed=20, byz=17) -> dict:
    return {"limitSummary": {
        "zhaban": {"ztCount": zt, "count": zhaban, "rate": 35.1},
        "drawdown": {"count": drawdown}, "continuousBoards": {"maxBoard": max_board},
        "thsPools": {"pools": {"failed": {"total": failed}, "drawdown": {"total": 11},
                               "rushing": {"total": 11}}},
        "sealQuality": {"byzCount": byz, "hardCount": 12, "rottenCount": 8,
                        "rottenShare": 0.22, "avgSucRate": 0.75}},
        "marketStats": {"upCount": up, "downCount": down, "flatCount": flat}}


class FakeFactsDB:
    def __init__(self, frames):
        self.snapshot_frames = FakeFrames(frames)

    def __getitem__(self, name):
        return self.snapshot_frames


def test_frame_facts_slot_scoped_no_lookahead():
    """11:00 口径只取 11:00 帧：与 15:00 帧数值不同（时点参数生效=无未来函数）。"""
    db = FakeFactsDB({("2026-10-12", "11:00"): _frame(zt=37),
                      ("2026-10-12", "15:00"): _frame(zt=46)})
    m11 = mf.frame_market_facts(db, "2026-10-12", "11:00")
    m15 = mf.frame_market_facts(db, "2026-10-12", "15:00")
    assert m11["ztCount"] == 37 and m15["ztCount"] == 46
    assert m11["slot"] == "11:00"
    assert m11["sealQuality"]["byzCount"] == 17
    assert m11["thsPools"] == {"failed": 20, "drawdown": 11, "rushing": 11}


def test_frame_facts_zero_breadth_is_missing():
    """up/down/flat 全 0 = 帧未采集（0 伪装缺失活案例）→ None，不喂 0。"""
    db = FakeFactsDB({("2026-10-12", "11:00"): _frame(zt=37, up=0, down=0, flat=0)})
    m = mf.frame_market_facts(db, "2026-10-12", "11:00")
    assert m["upCount"] is None and m["downCount"] is None and m["flatCount"] is None
    db2 = FakeFactsDB({("2026-10-12", "11:00"): _frame(zt=37, up=106, down=145)})
    m2 = mf.frame_market_facts(db2, "2026-10-12", "11:00")
    assert m2["upCount"] == 106 and m2["downCount"] == 145


def test_swing_anchor_matches_relay_narrative_values():
    """摆动锚算法对齐 relay v3 落库叙事（10-12：峰值 101/09-21/9d、谷值 32/09-28/5d、
    今日 46、较昨日 -23、距峰值 -55）——单一算法源验证。"""
    hist = [("2026-09-15", 32), ("2026-09-16", 66), ("2026-09-17", 60), ("2026-09-18", 77),
            ("2026-09-21", 101), ("2026-09-22", 62), ("2026-09-23", 50), ("2026-09-24", 51),
            ("2026-09-28", 32), ("2026-09-29", 56), ("2026-09-30", 53), ("2026-10-08", 42),
            ("2026-10-09", 69)]
    frames = {(d, "15:00"): _frame(zt=v) for d, v in hist}
    frames[("2026-10-12", "11:00")] = _frame(zt=46)  # 今日盘中值
    s = mf.swing_anchor(FakeFactsDB(frames), "2026-10-12", "11:00")
    assert s["ok"] and s["cur"] == 46 and s["peak"] == 101 and s["peakAgo"] == 9
    assert s["trough"] == 32 and s["troughAgo"] == 5
    assert s["deltaPrev"] == -23 and s["distPeak"] == -55


def test_swing_anchor_insufficient_window():
    db = FakeFactsDB({("2026-10-12", "11:00"): _frame(zt=46)})
    s = mf.swing_anchor(db, "2026-10-12", "11:00")
    assert s["ok"] is False and "不足" in s["reason"]


# ── 日终折叠衍生列（铁律 5：模型不替算） ──────────────────

def test_fold_attention_series():
    pts = [
        {"d": "2026-09-21", "slot": "15:00", "rank": 1, "pct": 90.0, "chg": 1.0},
        {"d": "2026-09-21", "slot": "11:00", "rank": 2, "pct": 80.0, "chg": 0.5},  # 同日两槽，后写覆盖时序假设
        {"d": "2026-09-22", "slot": "15:00", "rank": 5, "pct": 70.0, "chg": -1.0},
        {"d": "2026-09-23", "slot": "15:00", "rank": 6, "pct": 60.0, "chg": -2.0},
        {"d": "2026-09-24", "slot": "15:00", "rank": 7, "pct": 50.0, "chg": -3.0},
        {"d": "2026-09-25", "slot": "15:00", "rank": 8, "pct": 45.0, "chg": -1.0},
    ]
    # 时间升序重排（模拟真实输入：同日按 slot 升序）
    pts = [pts[1], pts[0], pts[2], pts[3], pts[4], pts[5]]
    r = mf.fold_attention_series(pts, ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"],
                                 "2026-09-25", 45.0)
    assert [x["pct"] for x in r["folded"]] == [90.0, 70.0, 60.0, 50.0, 45.0]
    assert r["directions"] == [-1, -1, -1, -1]
    assert r["jumpIdxs"] == []          # 无同向翻转（全跌）
    assert r["consecutiveFalling"] == 4


def test_fold_detects_against_trend_jump():
    pts = [{"d": f"2026-09-{18 + i}", "slot": "15:00", "rank": 1, "pct": p, "chg": 0.0}
           for i, p in enumerate([50, 55, 60, 30, 35])]
    r = mf.fold_attention_series(pts, [f"2026-09-{18 + i}" for i in range(4)], "2026-09-22", 35.0)
    assert r["directions"] == [1, 1, -1, 1]
    assert r["jumpIdxs"] == [3]         # 60→30 反向跳变标在 30 当日（幅度 30pt ≥8）
    assert r["consecutiveFalling"] == 0


# ── 人口过滤 ────────────────────────────────────────────

class FakePopDB:
    def __init__(self):
        self._by_day = {"2026-09-18": {"A", "B", "C"}, "2026-09-21": {"A", "B", "C"},
                        "2026-09-22": {"A", "B", "C"}}
        self._today = {"09:30": {"A", "B", "C", "D"}, "10:00": {"A", "B", "C", "D"},
                       "10:30": {"A", "B", "C", "D"}, "11:00": {"A", "B", "C", "D"}}

    def __getitem__(self, name):
        return self

    def find(self, q, projection=None):
        d = q.get("tradingDate")
        slots = ["09:30", "10:00", "10:30", "11:00"] if d == "2026-09-23" else ["15:00"]
        return FakeCursor({"slotTime": s, "snapshotId": f"{d}_{s}"} for s in slots)

    def distinct(self, field, q):
        sid = q.get("snapshotId", "")
        if sid.startswith("2026-09-23_"):
            return sorted(self._today[sid.replace("2026-09-23_", "")])
        return sorted(self._by_day.get(sid.split("_")[0], set()))


def _pop_ctx():
    return {"series_days": ["2026-09-18", "2026-09-21", "2026-09-22"],
            "prev3": ["2026-09-18", "2026-09-21", "2026-09-22"],
            "prev10": ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
                       "2026-09-21", "2026-09-22"],
            "cur": {"A": {"code": "A", "change": 3.0, "zlje": 1e7, "zljzb": 2.0, "rank": 1},
                    "B": {"code": "B", "change": 1.0, "zlje": None, "zljzb": 1.0, "rank": 2},
                    "C": {"code": "C", "change": 2.0, "zlje": 5e6, "zljzb": 1.0, "rank": 3},
                    "D": {"code": "D", "change": 2.0, "zlje": 5e6, "zljzb": 1.0, "rank": 4}},
            "pool": 4, "mm": -1.0, "up_share": 50.0,
            "sent": {"score": 61.7, "band": "strong", "stage": "发酵"},
            "market": {"ztCount": 37}, "swing": {"ok": False}}


def test_population_full_pool_no_exclusions():
    """v4 口径（2026-10-13 用户裁决）：人口=全热榜池，v3 三条件排除全部取消；
    主力缺失只计数不排除（case 级质量自标）。"""
    codes, stats = v4.build_population(FakePopDB(), "2026-09-23", _pop_ctx())
    assert codes == ["A", "B", "C", "D"]          # B 缺主力、D 断榜都保留判读
    assert stats["full_pool"] == 4
    assert stats["mainforce_missing_counted"] == 1


class FakeStateDB:
    """八块组装 mock：帧/行/情绪最小 fake。"""

    def __init__(self, ctx_codes):
        self.ctx_codes = ctx_codes

    def __getitem__(self, name):
        return self

    def find_one(self, q, projection=None, sort=None):
        if q.get("snapshotId") and q.get("code"):
            return {"rank": 10, "change": -2.0}
        if q.get("snapshotType"):
            return {"emotionScore": {"score": 61.7}, "stage": "发酵", "slotTime": "11:00"}
        return None

    def count_documents(self, q):
        return 200

    def distinct(self, field, q):
        return list(self.ctx_codes)

    def find(self, q, projection=None):
        return FakeCursor({"slotTime": s, "snapshotId": f"d_{s}"}
                          for s in ("09:30", "10:00", "10:30", "11:00", "15:00"))


def test_build_state_v4_blocks_and_blacklist(monkeypatch):
    monkeypatch.setattr("backend.operations.jev_label_jiuyan._daily_bars", lambda code: [])
    ctx = _pop_ctx()
    ctx["series_days"] = ["2026-09-1%d" % i for i in range(8, 10)] + ["2026-09-21", "2026-09-22"]
    db = FakeStateDB(["A"])
    head, blocks, meta = v4.build_state_v4(db, "A", "2026-09-23", ctx)
    assert set(blocks) == {"series", "position", "vp", "market", "themes", "quality", "gate"}
    narrative = "\n".join([head, *[ln for b in blocks.values() for ln in b]])
    bad = [w for w in v4.BLACKLIST_FIELDS if w in narrative]
    assert bad == [], f"黑名单字段泄漏: {bad}"
    assert meta["seenDays"] == 5 and meta["firstSeen"] is False   # 4 历史日+判读日
    assert "history depth: 5 trading days" in narrative
    assert "FIRST-SEEN" not in narrative                          # ≥5 日为主证据，无降级标注
    assert "consecutive falling days" in narrative
    assert "swing anchor" in narrative or "insufficient window" in narrative
    assert "TDX 不可用" in narrative or "个股位置" in narrative  # bars=[] → fail-visible 位置行


def test_short_series_flags_first_seen(monkeypatch):
    """新股/短历史不再拒判：全池口径下降级为 FIRST-SEEN 自标（判据不引用序列主证据）。"""
    monkeypatch.setattr("backend.operations.jev_label_jiuyan._daily_bars", lambda code: [])
    ctx = _pop_ctx()
    ctx["series_days"] = []  # 无历史日 → 仅判读点
    head, blocks, meta = v4.build_state_v4(FakeStateDB(["A"]), "A", "2026-09-23", ctx)
    assert meta["seenDays"] == 1 and meta["firstSeen"] is True
    assert "FIRST-SEEN" in "\n".join(blocks["series"])
    assert "history depth: 1 trading days" in "\n".join(blocks["series"])


def test_blacklist_constant_covers_engine_and_jev_answers():
    for w in ("compScore", "finalSignal", "relayPhase", "cycleStage", "driverType", "crowding"):
        assert w in v4.BLACKLIST_FIELDS
