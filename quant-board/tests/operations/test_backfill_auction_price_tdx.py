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
