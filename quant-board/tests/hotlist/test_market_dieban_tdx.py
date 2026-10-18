# -*- coding: utf-8 -*-
"""本地通达信日线跌停重算源测试（market_dieban_tdx + backfill_limit_down_tdx，F7 2026-10-17）。

背景：东财跌停池只有近 30 自然日窗口 → 09-16 之前无全市场口径，叙事回退 250 只采集池
（10-15 实证池内 6 vs 全市场 26；08-19 池内 53 vs 全市场 128；07-13 池内 32 vs 全市场 177）。
本模块用本地 `vipdoc/lday` 离线重算。测试**全离线**：合成 .day 字节流，禁触真实目录/网络/Mongo。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import backfill_limit_down_tdx as tool
from backend.operations import market_dieban_pool as mdp
from backend.operations import market_dieban_tdx as tdx

D1, D2 = "2026-07-10", "2026-07-13"


def _rec(date: str, *, c: float, o: float | None = None, h: float | None = None,
         l: float | None = None, amount: float = 0.0, vol: int = 1) -> bytes:
    """一根日线（价格 ×100 定点）；o/h/l 缺省取 c。"""
    o = c if o is None else o
    h = c if h is None else h
    l = c if l is None else l
    return struct.pack("<IIIIIfII", int(date.replace("-", "")), int(round(o * 100)),
                       int(round(h * 100)), int(round(l * 100)), int(round(c * 100)),
                       amount, vol, 0)


def _write(root: Path, market: str, code: str, records: list[bytes]) -> None:
    d = root / "vipdoc" / market / "lday"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{market}{code}.day").write_bytes(b"".join(records))


# ── 判定两道闸（涨跌幅线 + 价格精确匹配）────────────────────────────────────

def test_scan_counts_two_gates_and_board_ratio(tmp_path):
    """跌停 = 跌幅达线 **且** 收盘价 == 精确跌停价；阈值走 limit_ratio（创业板/北交所不同线）。

    600002 跌幅 -9.90% 过线但收盘 9.01 ≠ 跌停价 9.00（1 分边界假阳性，603893 同型）→ 不计；
    300002 创业板 -10% 未到 20% 线 → 不计；600003 除权样（前收 41.29 收 29.36）价格不匹配 → 不计。

    另注：窗口首棒（无前收）当日不可算 → 不算「有棒」，故夹具额外给一根 07-09 作前收。
    """
    pre = _rec("2026-07-09", c=10.00)
    _write(tmp_path, "sh", "600001", [pre, _rec(D1, c=10.00), _rec(D2, c=9.00)])   # -10.00% 精确 ✓
    _write(tmp_path, "sh", "600002", [pre, _rec(D1, c=10.00), _rec(D2, c=9.01)])   # -9.90% 不精确 ✗
    _write(tmp_path, "sz", "300001", [pre, _rec(D1, c=10.00), _rec(D2, c=8.00)])   # -20% 精确 ✓
    _write(tmp_path, "sz", "300002", [pre, _rec(D1, c=10.00), _rec(D2, c=9.00)])   # 未到 20% 线 ✗
    _write(tmp_path, "sh", "600003", [pre, _rec(D1, c=41.29), _rec(D2, c=29.36, o=28.70)])  # 除权样 ✗
    _write(tmp_path, "bj", "920002", [pre, _rec(D1, c=10.00), _rec(D2, c=7.00)])   # -30% 精确 ✓
    uni = {"600001", "600002", "300001", "300002", "600003", "920002"}
    counts, meta = tdx.scan_counts([D1, D2], root=str(tmp_path), universe=uni)
    assert counts.get(D2) == 3
    assert counts.get(D1) == 0            # 有棒无跌停 = 0（合法读数，不是缺口）
    assert meta["files"] == 6 and meta["coverage_max"] == 6


def test_scan_counts_skips_broken_prev_close(tmp_path):
    """前收为 0（坏数据/停牌样）→ 不伪跌停。"""
    _write(tmp_path, "sh", "600001", [_rec(D1, c=0.0), _rec(D2, c=0.0)])
    counts, _ = tdx.scan_counts([D2], root=str(tmp_path), universe={"600001"})
    assert counts.get(D2) == 0


# ── 覆盖闸 / 缺口 / 0 值语义 ────────────────────────────────────────────────

def test_scan_counts_zero_day_is_real_value_not_gap(tmp_path):
    """有棒但无跌停 → counts=0 且**不算** dates_without_bar（0 与「取不到」是两件事）。"""
    _write(tmp_path, "sh", "600001", [_rec(D1, c=10.0), _rec(D2, c=10.1)])
    counts, meta = tdx.scan_counts([D2], root=str(tmp_path), universe={"600001"})
    assert counts == {D2: 0}
    assert meta["zero_days"] == 1 and meta["dates_without_bar"] == []


def test_scan_counts_partial_coverage_day_excluded(tmp_path):
    """覆盖闸：当日有棒股数 < 峰值×0.9 → 剔除不出数（读取窗边缘防静默少算）。"""
    for i in range(10):
        code = f"6000{i:02d}"
        recs = [_rec(D1, c=10.0), _rec(D2, c=9.90)]
        if i < 5:                       # 只有 5 只覆盖次日
            recs.append(_rec("2026-07-14", c=10.0))
        _write(tmp_path, "sh", code, recs)
    counts, meta = tdx.scan_counts([D2, "2026-07-14"], root=str(tmp_path),
                                   universe={f"6000{i:02d}" for i in range(10)})
    assert meta["coverage_max"] == 10
    assert meta["partial"] == ["2026-07-14"]
    assert "2026-07-14" not in counts and counts.get(D2) == 0


def test_scan_counts_reports_dates_without_any_bar(tmp_path):
    """全市场无棒日 → dates_without_bar，绝不写 0（可算日 0 家则入 counts）。"""
    _write(tmp_path, "sh", "600001", [_rec("2026-07-09", c=10.0), _rec(D1, c=10.0)])
    counts, meta = tdx.scan_counts(["2026-07-08", D1], root=str(tmp_path), universe={"600001"})
    assert meta["dates_without_bar"] == ["2026-07-08"]
    assert "2026-07-08" not in counts and counts[D1] == 0


def test_scan_counts_universe_filter_and_missing(tmp_path):
    """宇宙过滤：目录内非宇宙文件跳过；宇宙内缺日线文件计入 missing（北交所目录缺口留档）。"""
    _write(tmp_path, "sh", "600001", [_rec(D1, c=10.0), _rec(D2, c=9.00)])
    _write(tmp_path, "sh", "600002", [_rec(D1, c=10.0), _rec(D2, c=9.00)])
    counts, meta = tdx.scan_counts([D2], root=str(tmp_path), universe={"600001", "999999"})
    assert counts.get(D2) == 1 and meta["files"] == 1 and meta["skipped"] == 1
    assert meta["missing"] == 1


# ── 目录解析 / 读取护栏 ─────────────────────────────────────────────────────

def test_resolve_root_prefers_freshest_and_honours_env(tmp_path, monkeypatch):
    """选末棒最新的目录；环境变量显式指定排首位（不被默认值覆盖）。"""
    old, new = tmp_path / "old", tmp_path / "new"
    _write(old, "sh", "600000", [_rec("2026-04-08", c=10.0)])
    _write(new, "sh", "600000", [_rec("2026-10-16", c=10.0)])
    assert tdx.resolve_root([str(tmp_path / "nope"), str(old), str(new)]) == \
        (str(new), "2026-10-16")
    assert tdx.resolve_root([str(tmp_path / "nope")]) == (None, None)
    monkeypatch.setenv(tdx.ENV_ROOT, str(new))
    assert tdx.candidate_roots()[0] == str(new)


def test_read_lday_missing_empty_and_truncated(tmp_path):
    """缺文件/空文件 → []；坏尾字节（不足一条记录）不抛错、不产假记录。"""
    assert tdx.read_lday(str(tmp_path / "nope.day")) == []
    p = tmp_path / "sh600001.day"
    p.write_bytes(b"")
    assert tdx.read_lday(str(p)) == []
    p.write_bytes(_rec(D2, c=9.0) + b"\x01\x02\x03")
    assert len(tdx.read_lday(str(p))) == 1


def test_looks_like_a_share_filters_non_stock_segments():
    """无宇宙表时的兜底过滤：指数/基金/债/B 股代码段排除。"""
    assert tdx.looks_like_a_share("600000") and tdx.looks_like_a_share("301569")
    assert tdx.looks_like_a_share("920162") and not tdx.looks_like_a_share("000001") is False
    for bad in ("510300", "113050", "200011", "399001", "110000"):
        assert not tdx.looks_like_a_share(bad), bad


# ── 回填工具：只写权威源未覆盖的日期，0 值照写，缺口不写 ────────────────────

class FakeCol:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.replaced: list[tuple] = []

    def find(self, query=None, projection=None):
        q = (query or {}).get("_id")
        rows = self.rows
        if isinstance(q, dict) and "$in" in q:
            want = set(q["$in"])
            rows = [r for r in rows if r.get("_id") in want]
        elif q is not None:
            rows = [r for r in rows if r.get("_id") == q]
        return [dict(r) for r in rows]

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append((query, doc))
        self.rows = [r for r in self.rows if r.get("_id") != doc.get("_id")] + [dict(doc)]


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        if name not in self.cols:
            self.cols[name] = FakeCol()
        return self.cols[name]


def _fake_frames(dates: list[str]) -> FakeCol:
    return FakeCol([{"tradingDate": d, "datasetId": "dragonboard_live"} for d in dates])


def test_tool_dry_run_then_apply_skips_authoritative(tmp_path, monkeypatch, capsys):
    """dry-run 不写库；apply 只写权威源未覆盖的日期，0 值日照写、无棒日不写。"""
    _write(tmp_path, "sh", "600001", [_rec(D1, c=10.0), _rec(D2, c=9.00)])
    db = FakeDb({
        "snapshot_frames": _fake_frames([D1, D2, "2026-07-14"]),
        "stock_names": FakeCol([{"code": "600001", "type": "stock"},
                                {"code": "600002", "type": "stock"}]),
        mdp.COLLECTION: FakeCol([{"_id": D1, "count": 3, "source": mdp.SOURCE_EM}]),
    })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr(tdx, "resolve_root", lambda roots=None: (str(tmp_path), "2026-10-16"))
    base = ["prog", "--start", "2026-01-01", "--end", "2026-12-31"]
    monkeypatch.setattr(sys, "argv", base)
    tool.main()
    out = capsys.readouterr().out
    assert "dry-run 未写库" in out and db[mdp.COLLECTION].replaced == []
    assert "待处理 2 日" in out             # D1 是 EM 权威源 → 跳过

    monkeypatch.setattr(sys, "argv", base + ["--apply"])
    tool.main()
    written = {q["_id"]: doc for q, doc in db[mdp.COLLECTION].replaced}
    assert set(written) == {D2}             # D1（EM）不覆盖；2026-07-14 无棒 → 不写 0
    assert written[D2]["source"] == mdp.SOURCE_TDX and written[D2]["count"] == 1
    assert db[mdp.COLLECTION].rows[0]["source"] == mdp.SOURCE_EM   # 权威行保持


def test_tool_writes_legit_zero_day(tmp_path, monkeypatch):
    """覆盖足但无跌停 → 写 0（真读数，不是缺口）。"""
    _write(tmp_path, "sh", "600001", [_rec(D1, c=10.0), _rec(D2, c=10.5)])
    db = FakeDb({"snapshot_frames": _fake_frames([D2]),
                 "stock_names": FakeCol([{"code": "600001", "type": "stock"}]),
                 mdp.COLLECTION: FakeCol()})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr(tdx, "resolve_root", lambda roots=None: (str(tmp_path), "2026-10-16"))
    monkeypatch.setattr(sys, "argv", ["prog", "--start", "2026-01-01", "--end", "2026-12-31",
                                      "--apply"])
    tool.main()
    written = {q["_id"]: doc for q, doc in db[mdp.COLLECTION].replaced}
    assert written[D2]["count"] == 0 and written[D2]["source"] == mdp.SOURCE_TDX
