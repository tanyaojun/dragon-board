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
    # 严格相等锁（review R4）：containment 只拦增改不拦删句——必须存在与 ammo 逐字相等的围栏块
    for qd in ammo.QUESTIONS_A.values():
        assert qd["instructions"].strip() in (b.strip() for b in blocks), \
            f"instructions 未与预登记围栏块逐字相等: {qd['instructions'][:50]}"


def test_questions_structure():
    assert set(ammo.QUESTIONS_A) == {"direction"}  # 单题集（B 拆分层退役）
    qd = ammo.QUESTIONS_A["direction"]
    assert qd["type"] == "choice"
    assert set(qd["criteria"]) == {"buy", "sell", "hold", "insufficient"}


def test_recent_trading_dates_query_uses_type_field(monkeypatch):
    """防回归（review R0）：_recent_trading_dates_str 查 snapshot_frames 必须用 type 键。

    snapshot_frames 文档键控是 type；hotlist_sentiment 才是 snapshotType。用错查空 →
    directionVerify 每天静默 backfilled:0，验证列永远不落（线上实测 type=1101/snapshotType=0）。
    """
    captured = {}

    class FakeFrames:
        def find(self, q, projection=None):
            captured["q"] = q
            return []

    class FakeDB5:
        def __getitem__(self, name):
            assert name == "snapshot_frames"
            return FakeFrames()

    import backend.data.repositories.repository_factory as factory
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: FakeDB5())
    import backend.operations.schedule as sched
    assert sched._recent_trading_dates_str("2026-10-13", 5) == []
    assert captured["q"]["type"] == "half_hour"
    assert "snapshotType" not in captured["q"]


def test_criteria_verbatim_from_preregistration():
    """§九「题目文本逐字比对」涵盖 criteria：四条 criteria 文本必须原样在预登记文档中。"""
    text = PREREQ.read_text(encoding="utf-8")
    for c, txt in ammo.QUESTIONS_A["direction"]["criteria"].items():
        # 键到文本映射锁（review R4）：整份包含不校验映射，buy/sell 对调也能过——必须匹配列表行
        assert f"- `{c}`：{txt}" in text, f"criteria `{c}` 未锁进预登记: {txt[:40]}"


def test_runner_constants_frozen():
    """runner 冻结常量锁（review R4）：分线/窗口/热区阈值漂移=改门级变更。"""
    assert gate.SERIES_MIN_POINTS == 10
    assert gate.SERIES_WINDOW_DAYS == 10
    assert gate.HOT_ZONE == 80
    assert gate.TOKEN_FUSE == 1_500_000
    assert gate.DIRECTION_SNAPSHOT_TYPE == "half_hour"
    assert ammo.band_of(39.9) == "cold" and ammo.band_of(40.0) == "weak"
    assert ammo.band_of(59.9) == "weak" and ammo.band_of(60.0) == "strong"
    assert ammo.band_of(74.9) == "strong" and ammo.band_of(75.0) == "peak"


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


def test_fire_token_guard(monkeypatch):
    """--fire token 预检纯函数：无 token/空白 token 拒绝，任一非空放行。"""
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    assert gate.fire_token_guard() is False
    monkeypatch.setenv("JEV_CF_TOKEN", "   ")
    assert gate.fire_token_guard() is False  # 空白不算
    monkeypatch.setenv("JEV_CF_TOKEN", " tok ")
    assert gate.fire_token_guard() is True  # strip 后非空
    monkeypatch.delenv("JEV_CF_TOKEN")
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "k")
    assert gate.fire_token_guard() is True


def test_scheduler_cmd_compatible_with_runner_cli():
    """回归锁：scheduler direction_command 的 runner 参数 ⊆ runner argparse。"""
    from backend.snapshot_collector.scheduler import direction_command
    cmd = direction_command("2026-10-13")
    runner_args = cmd[cmd.index("--day"):]
    args, unknown = gate.build_arg_parser().parse_known_args(runner_args)
    assert unknown == [], f"scheduler cmd 携带 runner 不认识的参数: {unknown}"
    assert args.day == "2026-10-13" and args.fire is True


def test_population_requires_four_slots_and_mainforce(monkeypatch):
    """人口过滤：当日 <4 槽/缺主力/前三日断榜 的股票被排除。"""
    # 简化：直接测 build_direction_population 的条件分支（mock ctx + db.distinct）
    class FakeDB2(FakeDB):
        def __getitem__(self, name):
            return self

        def distinct(self, field, q):
            sid = q.get("snapshotId", "")
            codes = ["600206", "000001"]
            if sid.endswith("10:30") or sid.endswith("11:00"):
                codes.append("300999")  # 只在 2 个槽出现（<4 槽分支）
            return codes

    ctx = {"series_days": ["2026-09-18", "2026-09-21", "2026-09-22"],
           "prev3": ["2026-09-18", "2026-09-21", "2026-09-22"],
           "cur": {"600206": {"code": "600206", "change": 3.0, "zlje": 1e7, "zljzb": 2.0,
                              "rank": 10, "name": "x"},
                   "000001": {"code": "000001", "change": 1.0, "zlje": None, "zljzb": 1.0,
                              "rank": 20, "name": "y"},
                   "300999": {"code": "300999", "change": 2.0, "zlje": 5e6, "zljzb": 1.0,
                              "rank": 30, "name": "z"}},
           "pool": 3}
    def fake_day_slot_frames(db, d, dataset_id=gate.DEFAULT_DATASET_ID):
        if d == "2026-09-23":
            return [(s, f"2026-09-23_{s}") for s in ("09:30", "10:00", "10:30", "11:00")]
        return [("15:00", f"{d}_15:00")]

    monkeypatch.setattr(gate, "_day_slot_frames", fake_day_slot_frames)
    codes = gate.build_direction_population(FakeDB2(), "2026-09-23", ctx)
    assert codes == ["600206"]  # 000001 缺主力被排除；300999 仅 2 槽被排除

    # 防回归：prev3 含 series_days 键集外的日期（missed-slot）→ 不 KeyError，按无法验证排除
    ctx2 = {**ctx, "prev3": ctx["prev3"] + ["2026-09-15"]}
    assert gate.build_direction_population(FakeDB2(), "2026-09-23", ctx2) == []


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
    assert isinstance(blocks["vp"], list) and all(isinstance(x, str) for x in blocks["vp"])
    assert "strong" in "\n".join(blocks["gate"])
    assert meta["pos"]["current"] == 98.0  # (200-5+1)/200*100
