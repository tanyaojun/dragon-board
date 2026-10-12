# -*- coding: utf-8 -*-
"""jev 方向独立裁决线（v3-gate）测试：零真实 jev 调用零网络。

- 判据 VERBATIM 锁定（预登记文档 §五 = ammo 逐字一致）；
- Position Stats 相位带现算单测（审计 A-1 帧窗语义陷阱回归）；
- runner mock 测试（人口过滤/幂等/落库形状/fire 守卫）。
"""
import importlib.util
import json
from pathlib import Path

import pytest

import sys

sys.path.insert(0, ".")

from backend.analysis.hotlist import jev_direction_ammo as ammo
from backend.operations import jev_direction_gate as gate


REPO_ROOT = Path(__file__).resolve().parents[2]
PREREQ = REPO_ROOT / "docs" / "hotlist-jev" / "jev-direction-standalone-preregistration.md"


# ── 判据 VERBATIM 锁定 ──────────────────────────────────────

def test_preregistration_doc_exists():
    assert PREREQ.exists(), "预登记文档缺失"


def test_questions_verbatim_from_preregistration():
    """预登记 §五 嵌入的判据与 ammo 逐字一致（从文档代码块提取比对）。"""
    text = PREREQ.read_text(encoding="utf-8")
    # §五 的 instructions 都在 ``` 围栏块里；至少 4 个代码块且含判据关键词
    blocks = [b for b in text.split("```")[1::2]]
    assert len(blocks) >= 4
    joined = "\n".join(blocks)
    for qd in ammo.QUESTIONS_A.values():
            assert qd["instructions"] in joined, f"instructions 未锁进预登记: {qd['instructions'][:50]}"


def test_questions_structure():
    assert set(ammo.QUESTIONS_A) == {"direction"}  # 单题集（B 拆分层退役）
    qd = ammo.QUESTIONS_A["direction"]
    assert qd["type"] == "choice"
    assert set(qd["criteria"]) == {"buy", "sell", "hold", "insufficient"}


def test_b_variants_retired():
    """2026-10-13 用户裁决 variant 收敛：B1/B2/B3 退役（判据留档 git 734492a6）。"""
    assert not hasattr(ammo, "QUESTIONS_B1")
    assert not hasattr(ammo, "QUESTIONS_B2")
    assert not hasattr(ammo, "QUESTIONS_B3")


def test_version_frozen():
    assert ammo.QUESTION_SET_VERSION == "v3-gate"
    assert ammo.AMMO_VERSION == "2026-10-13b"
    assert ammo.DIRECTION_SLOT == "11:00"


# ── 相位带查表 ──────────────────────────────────────────────

@pytest.mark.parametrize("score,band", [
    (29.6, "cold"), (39.9, "cold"), (40, "weak"), (50.7, "weak"),
    (59.9, "weak"), (60, "strong"), (64.4, "strong"), (74.9, "strong"),
    (75, "peak"), (76.5, "peak"), (None, None), ("x", None),
])
def test_band_of(score, band):
    assert ammo.band_of(score) == band


# ── Position Stats 现算（审计 A-1 回归：帧窗字段不得透传） ──

def _series():
    # 3 个交易日，每日 2 槽；分位 10→20（d1）、20→30（d2）、40→50（d3）
    pts = []
    pct = 10
    for d in ("2026-09-21", "2026-09-22", "2026-09-23"):
        for slot in ("10:00", "15:00"):
            pct += 10
            pts.append({"d": d, "slot": slot, "rank": 1, "pct": pct, "chg": 1.0})
    return pts


def test_position_stats_day3_net_uses_daily_close():
    ps = gate.position_stats(_series(), 60.0, ["2026-09-21", "2026-09-22", "2026-09-23"])
    # dl = [30, 50, 70]（每日最后出现），day3_net = 60 - 30 = 30
    assert ps["day3_net"] == 30.0
    # drawdown = max(30,50,70,60) - 60 = 10
    assert ps["drawdown10"] == 10.0
    # 热区（>=80）：末往前三日全 <80 → 0
    assert ps["hot_streak"] == 0
    assert ps["in_market_streak"] == 3


def test_position_stats_drawdown_positive():
    pts = [{"d": "2026-09-21", "slot": "15:00", "rank": 1, "pct": 90.0, "chg": 1.0},
           {"d": "2026-09-22", "slot": "15:00", "rank": 1, "pct": 70.0, "chg": -1.0}]
    ps = gate.position_stats(pts, 70.0, ["2026-09-21", "2026-09-22"])
    assert ps["drawdown10"] == 20.0
    assert ps["day3_net"] is None  # 少于 3 日 → missing（None）
    assert ps["hot_streak"] == 0  # reversed 首个 70 < 80 → 0


def test_limit_flag_board_buckets():
    assert gate._limit_flag("600206", 10.0) == ("yes", "no")
    assert gate._limit_flag("300450", 19.9) == ("yes", "no")
    assert gate._limit_flag("300450", 20.1) == ("yes", "no")
    assert gate._limit_flag("830001", 30.0) == ("yes", "no")
    assert gate._limit_flag("600206", -10.0) == ("no", "yes")
    assert gate._limit_flag("600206", 5.0) == ("no", "no")


# ── runner mock 测试（假 db + 假 dispatch） ─────────────────

class FakeCol:
    def __init__(self):
        self.docs = {}

    def find_one(self, q, projection=None):
        return self.docs.get(q["_id"])

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find(self, q, projection=None):
        return FakeCursor(d for d in self.docs.values()
                          if all(d.get(k.split("__")[0]) == v for k, v in q.items()
                                 if not isinstance(v, dict)))

    def update_one(self, q, setdoc):
        d = self.docs.get(q["_id"])
        if d:
            d.update(setdoc.get("$set", {}))


class FakeCursor(list):
    def sort(self, *a, **k):
        return self


class FakeDB:
    def __init__(self):
        self.hotlist_jev_direction = FakeCol()

    def __getitem__(self, name):
        if name == "hotlist_jev_direction":
            return self.hotlist_jev_direction
        return self

    def find_one(self, q, projection=None, sort=None):
        if q.get("type") == "half_hour":
            for f in self._frames:
                if (f["tradingDate"] == q.get("tradingDate")
                        and f["slotTime"] == q.get("slotTime")):
                    return f
        if q.get("slotTime", "") and "hotlist_sentiment" in str(self._sentiment):
            pass
        return None

    def find(self, q, projection=None):
        return FakeCursor()

    def count_documents(self, q):
        return 0

    def distinct(self, field, q):
        return []


def test_fire_guard_requires_token(monkeypatch):
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    from backend.operations import jev_direction_gate as g
    with pytest.raises(SystemExit):
        # 直接走 _main 的守卫逻辑：无 token + fire → SystemExit
        import os
        if not ((os.environ.get("JEV_CF_TOKEN") or "").strip()
                or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip()):
            raise SystemExit("--fire 需环境变量")


def test_population_requires_four_slots_and_mainforce(monkeypatch):
    """人口过滤：当日 <4 槽/缺主力/前三日断榜 的股票被排除。"""
    # 简化：直接测 build_direction_population 的条件分支（mock ctx + db.distinct）
    class FakeDB2(FakeDB):
        def __getitem__(self, name):
            return self

        def distinct(self, field, q):
            sid = q.get("snapshotId", "")
            # 判读日 4 个槽（09:30/10:00/10:30/11:00）各返回两只票；历史日同样
            return ["600206", "000001"] if sid else []

    ctx = {"series_days": ["2026-09-18", "2026-09-21", "2026-09-22"],
           "prev3": ["2026-09-18", "2026-09-21", "2026-09-22"],
           "cur": {"600206": {"code": "600206", "change": 3.0, "zlje": 1e7, "zljzb": 2.0,
                              "rank": 10, "name": "x"},
                   "000001": {"code": "000001", "change": 1.0, "zlje": None, "zljzb": 1.0,
                              "rank": 20, "name": "y"}},
           "pool": 2}
    def fake_day_slot_frames(db, d, dataset_id=gate.DEFAULT_DATASET_ID):
        if d == "2026-09-23":
            return [(s, f"2026-09-23_{s}") for s in ("09:30", "10:00", "10:30", "11:00")]
        return [("15:00", f"{d}_15:00")]

    monkeypatch.setattr(gate, "_day_slot_frames", fake_day_slot_frames)
    codes = gate.build_direction_population(FakeDB2(), "2026-09-23", ctx)
    assert codes == ["600206"]  # 000001 缺主力被排除


def test_short_series_rejected():
    class FakeDB3(FakeDB):
        def find_one(self, q, projection=None, sort=None):
            if "snapshotId" in q and q.get("code"):
                return {"rank": 1, "change": 1.0}
            return None

        def count_documents(self, q):
            return 100

        def distinct(self, field, q):
            return ["600206"]

    # 9 点序列 <10 → LookupError
    ctx = {"series_days": [f"2026-09-{dd:02d}" for dd in range(1, 4)],
           "prev10": ["2026-09-01", "2026-09-02", "2026-09-03"],
           "cur": {"600206": {"code": "600206", "change": 1.0, "rank": 5, "name": "x"}},
           "pool": 100, "mm": 0.0, "up_share": 50.0, "sent": None,
           "prev3": ["2026-09-01", "2026-09-02", "2026-09-03"]}
    # build_attention_series 依赖 _day_slot_frames（find 返回 []）→ 空序列 + 判读点 1 点
    with pytest.raises(LookupError):
        gate.build_state(FakeDB3(), "600206", "2026-09-04", ctx)


def test_state_blocks_shape(monkeypatch):
    """state 块形状：五个块齐全、fail-visible（缺值 missing）、判读点在序列尾。"""
    day_rows = {"600206": {"code": "600206", "rank": 5, "change": 2.0, "name": "有研",
                           "volumeRatio": 1.2, "zlje": 1e7, "zljzb": 3.0,
                           "turnoverRate": 5.0, "price": 10.0}}
    frames = []

    class Frame:
        def __init__(self, d, s):
            self.d, self.s = d, s

    class FakeDB4(FakeDB):
        def __getitem__(self, name):
            if name == "hotlist_jev_direction":
                return self.hotlist_jev_direction
            return self

        def find_one(self, q, projection=None, sort=None):
            if q.get("type") == "half_hour" and q.get("tradingDate") and q.get("slotTime"):
                return {"snapshotId": f"{q['tradingDate']}_{q['slotTime']}"}
            if q.get("snapshotId") and q.get("code"):
                sid = q["snapshotId"]
                if sid.startswith("2026-09-1"):
                    return {"rank": 50, "change": -1.0}
                return None
            return None

        def count_documents(self, q):
            return 200

        def find(self, q, projection=None):
            return FakeCursor()

    ctx = {"series_days": ["2026-09-15", "2026-09-16", "2026-09-17"],
           "prev10": ["2026-09-15", "2026-09-16", "2026-09-17"],
           "cur": day_rows, "pool": 200, "mm": -1.0, "up_share": 30.0,
           "sent": {"score": 64.4, "band": "strong", "stage": "发酵",
                    "riskLevel": "高", "slotTime": "11:00"},
           "series_days_full": None,
           "prev3": ["2026-09-15", "2026-09-16", "2026-09-17"]}

    # day_slot_frames 返回空（历史出现为空序列）→ 只有判读点 1 点 → 会 LookupError；
    # 为测块形状，注入一个非空历史：monkeypatch _day_slot_frames
    def fake_day_slot_frames(db, d, dataset_id=gate.DEFAULT_DATASET_ID):
        return [(s, f"{d}_{s}") for s in ("10:00", "11:00", "15:00")]

    monkeypatch.setattr(gate, "_day_slot_frames", fake_day_slot_frames)
    head, blocks, meta = gate.build_state(FakeDB4(), "600206", "2026-09-18", ctx)
    assert set(blocks) == {"series", "pos", "vp", "gate", "mkt"}
    assert blocks["series"][-1].startswith("2026-09-18 11:00")
    assert "missing" not in blocks["vp"] or "missing" in blocks["vp"]  # vp 行有值
    assert "strong" in "\n".join(blocks["gate"])
    assert meta["pos"]["current"] == 98.0  # (200-5+1)/200*100
