# -*- coding: utf-8 -*-
"""TDX 日线回补 kpl_auction_price.s0925 测试（tmp .day 二进制 + 假库，零外呼）。

锚：002652 11-18 真值 开4.40/0.00%（App 同屏）；prevclose=前一棒 close；
live 已收不覆盖；缺棒/停牌不伪值（fail-visible）。
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backfill_auction_price_tdx import backfill, open_pct_for_date

_REC = struct.Struct("<IIIIIfII")


def _write_day(path, bars):
    """bars = [(dateint, open, high, low, close), ...] 价格×100。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        for d, o, h, l, c in bars:
            fh.write(_REC.pack(d, o, h, l, c, 1.0, 1, 0))


def _mkdb(series, auct_store):
    """series = {date: [codes]}；auct_store 模拟 kpl_auction_price 点键 $set。"""

    class Coll:
        def __init__(self, owner, name):
            self.owner, self.name = owner, name

        def find(self, q, p=None):
            date = q.get("_id")
            dates = [date] if date else sorted(self.owner.series)
            out = []
            for d in dates:
                ticks = [{"it": [{"s": c} for c in self.owner.series.get(d, [])]}]
                out.append({"_id": d, "ticks": ticks})
            return iter(out)

        def update_one(self, q, u, upsert=False):
            flat = self.owner.auct.setdefault(q["_id"], {})
            flat.update(u["$set"])

        def find_one(self, q):
            flat = self.owner.auct.get(q["_id"]) or {}
            if not flat:
                return None
            doc = {"_id": q["_id"]}
            for k, v in flat.items():
                cur = doc
                parts = k.split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                cur[parts[-1]] = v
            return doc

    class DB:
        def __init__(self):
            self.series, self.auct = series, auct_store

        def __getitem__(self, name):
            return Coll(self, name)

    return DB()


def test_open_pct_basic(tmp_path):
    path = str(tmp_path / "vipdoc" / "sz" / "lday" / "sz002652.day")
    _write_day(path, [(20261117, 484, 484, 440, 440),
                      (20261118, 440, 441, 428, 428)])
    rec = open_pct_for_date(path, "2026-11-18")
    assert rec["price"] == 4.40 and rec["pct"] == 0.0 and rec["src"] == "tdx_lday"
    rec17 = open_pct_for_date(path, "2026-11-17")
    assert rec17 is None, "首棒无 prevclose → None（不伪值）"


def test_open_pct_short_file_no_negative_seek(tmp_path):
    path = str(tmp_path / "vipdoc" / "sz" / "lday" / "sz300999.day")
    _write_day(path, [(20261118, 200, 201, 199, 200)])  # 新上市仅 1 棒
    assert open_pct_for_date(path, "2026-11-18") is None


def test_backfill_fills_missing_skips_live(tmp_path):
    root = str(tmp_path)
    _write_day(os.path.join(root, "vipdoc", "sz", "lday", "sz002652.day"),
               [(20261117, 484, 484, 440, 440),
                (20261118, 440, 441, 428, 428)])
    db = _mkdb({"2026-11-18": ["002652", "600000"]}, {})
    s = backfill(db, ["2026-11-18"], root=root)
    assert s["2026-11-18"]["filled"] == 1 and s["2026-11-18"]["writeOk"]
    assert s["2026-11-18"]["noBar"] == 1 and "600000" in s["2026-11-18"]["noBarSamples"]
    doc = db["kpl_auction_price"].find_one({"_id": "2026-11-18"})
    assert doc["s0925"]["002652"]["pct"] == 0.0
    # live 已收 → 不覆盖，filled=0
    db2 = _mkdb({"2026-11-18": ["002652"]},
                {"2026-11-18": {"s0925.002652": {"price": 9.9, "pct": 5.0}}})
    s2 = backfill(db2, ["2026-11-18"], root=root)
    assert s2["2026-11-18"]["filled"] == 0 and s2["2026-11-18"]["skippedLive"] == 1
    doc2 = db2["kpl_auction_price"].find_one({"_id": "2026-11-18"})
    assert doc2["s0925"]["002652"]["pct"] == 5.0, "live 值不被 TDX 回补覆盖"


def test_backfill_ex_rights_band_suspect_skipped(tmp_path):
    """review B1：除权日 raw 前收 pct 系统性错（10送10 → 伪 -50%）——
    limit_rules 真实涨/跌停价 band 校验拦截，宁缺勿错只披露（不污染打分链）。"""
    root = str(tmp_path)
    _write_day(os.path.join(root, "vipdoc", "sz", "lday", "sz002652.day"),
               [(20261117, 2000, 2010, 1990, 2000),   # 前收 20.00
                (20261118, 1000, 1010, 990, 1000)])    # 除权开 10.00 → raw pct -50%
    db = _mkdb({"2026-11-18": ["002652"]}, {})
    s = backfill(db, ["2026-11-18"], root=root)["2026-11-18"]
    assert s["filled"] == 0 and s["bandSuspectN"] == 1
    assert s["bandSuspectSamples"][0]["code"] == "002652"
    assert db["kpl_auction_price"].find_one({"_id": "2026-11-18"}) is None, "嫌疑值不写库"


def test_backfill_band_allows_tick_rounding_low_price(tmp_path):
    """低价股 tick 取整：真实涨停 pct 可超名义 10%（1.05→1.16=10.48%）——
    band 用真实涨停价（limit_rules 单源）而非名义百分比，不误杀。"""
    root = str(tmp_path)
    _write_day(os.path.join(root, "vipdoc", "sz", "lday", "sz002652.day"),
               [(20261117, 105, 106, 104, 105),
                (20261118, 116, 116, 115, 116)])   # round(1.05*1.1,2)=1.16 真实涨停
    db = _mkdb({"2026-11-18": ["002652"]}, {})
    s = backfill(db, ["2026-11-18"], root=root)["2026-11-18"]
    assert s["filled"] == 1 and s["bandSuspectN"] == 0


def test_open_pct_window_head_prev_available(tmp_path):
    """review n2：目标日恰为 TAKE 窗首棒时多读 1 棒保 prevclose（不保守漏填）。"""
    path = str(tmp_path / "vipdoc" / "sz" / "lday" / "sz002652.day")
    bars = [(20261001 + i, 400 + i, 410 + i, 390 + i, 400 + i) for i in range(31)]
    _write_day(path, bars)
    rec = open_pct_for_date(path, "2026-10-02")   # 倒数第 30 棒（旧 TAKE=30 窗首 → 漏）
    assert rec is not None and rec["prevClose"] == 4.0
    assert rec["pct"] == round((4.01 / 4.0 - 1) * 100, 4)


def test_open_pct_bad_price_none(tmp_path):
    path = str(tmp_path / "vipdoc" / "sz" / "lday" / "sz002652.day")
    _write_day(path, [(20261117, 484, 484, 440, 440),
                      (20261118, 0, 0, 0, 0)])   # 坏价（停牌零棒）
    assert open_pct_for_date(path, "2026-11-18") is None


def test_intraday_forbidden_guard():
    """review n2：当日 15:00 CST 前禁跑（单写者=live collector）。"""
    from datetime import datetime, timedelta, timezone
    from scripts.backfill_auction_price_tdx import _intraday_forbidden
    tz = timezone(timedelta(hours=8))
    assert _intraday_forbidden("2026-11-18", datetime(2026, 11, 18, 10, 0, tzinfo=tz))
    assert not _intraday_forbidden("2026-11-18", datetime(2026, 11, 18, 15, 0, tzinfo=tz))
    assert not _intraday_forbidden("2026-11-17", datetime(2026, 11, 18, 10, 0, tzinfo=tz))


def test_backfill_noop_writeok_and_prevclose_not_persisted(tmp_path):
    """review n2：无可填=无操作成功（writeOk=True 与真失败区分）；prevClose 仅校验不落库。"""
    root = str(tmp_path)
    _write_day(os.path.join(root, "vipdoc", "sz", "lday", "sz002652.day"),
               [(20261117, 484, 484, 440, 440),
                (20261118, 440, 441, 428, 428)])
    db = _mkdb({"2026-11-18": ["002652"]}, {})
    s = backfill(db, ["2026-11-18"], root=root)["2026-11-18"]
    assert s["writeOk"] and s["filled"] == 1
    rec = db["kpl_auction_price"].find_one({"_id": "2026-11-18"})["s0925"]["002652"]
    assert "prevClose" not in rec and rec["src"] == "tdx_lday"
    s2 = backfill(db, ["2026-11-18"], root=root)["2026-11-18"]
    assert s2["filled"] == 0 and s2["writeOk"], "全已存 → 无操作成功非失败"
