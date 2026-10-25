# -*- coding: utf-8 -*-
"""V3-2/V3-3 板块名映射 + 静态全成分聚合测试——全离线，零真实 HTTP。

锁定口径（2026-10-25 用户三拍板：全量纳入+披露强度）：
1. 建议：停用词直落未收录 / exact / contains 唯一 / multi-union 全并集；
2. rebuild 幂等且不覆盖 manual；产业库新增节点后并集可扩；
3. manual_set 按名/按 code 均可，未知节点报错，空清单=删除回 auto；
4. static_members：多产业并集去重取关联最强、batchDates/sharesMedian 披露、
   未映射 reason 透出（fail-visible 不静默丢）；
5. _static_rows_compute：同式 aggregate_day 复用 + 未映射行标注 + bars 单次取齐。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import sector_industry_map as M
from backend.operations import sector_nodes as SN
from backend.operations.jiuyan_theme_store import COLLECTION_INDUSTRY_STOCKS

INDUSTRY_NAMES = ["国产机器人", "特斯拉机器人", "机器人零部件", "四足机器人/机器狗",
                  "算力概念", "国产算力芯片", "传媒出版", "房地产"]


# ── 建议规则（纯函数） ─────────────────────────────────────────────────
def test_suggest_rules():
    assert M.suggest_for("传媒出版", INDUSTRY_NAMES) == {"matchType": "exact", "codes": ["传媒出版"]}
    assert M.suggest_for("传媒", INDUSTRY_NAMES) == {"matchType": "contains", "codes": ["传媒出版"]}
    assert M.suggest_for("地产", INDUSTRY_NAMES) == {"matchType": "contains", "codes": ["房地产"]}
    ro = M.suggest_for("机器人", INDUSTRY_NAMES)
    assert ro["matchType"] == "multi-union" and len(ro["codes"]) == 4
    assert M.suggest_for("低空经济", INDUSTRY_NAMES) is None
    for x in ("公告", "其他", "新股", "次新"):
        assert M.suggest_for(x, [*INDUSTRY_NAMES, "其他金融"]) is None   # 停用词防漂移误配


# ── 存储 fake ─────────────────────────────────────────────────────────
class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, query, projection=None):
        d = self.docs.get(query["_id"]) if "_id" in query else None
        return dict(d) if d else None

    def replace_one(self, query, doc, upsert=False):
        self.docs[doc["_id"]] = dict(doc)

    def delete_one(self, query):
        self.docs.pop(query["_id"], None)
        return type("R", (), {"deleted_count": 1})()

    def find(self, query=None, projection=None):
        rows = []
        for d in self.docs.values():
            ok = all(d.get(k) == v for k, v in (query or {}).items())
            if ok:
                # pymongo 语义：projection 默认保留 _id（除非显式 0 排除）
                if projection:
                    row = {"_id": d["_id"]}
                    row.update({k: d.get(k) for k, v in projection.items() if v})
                else:
                    row = dict(d)
                rows.append(row)
        return rows


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _seed_industries(db, batch="2026-10-25"):
    """8 产业成分快照（规模刻意不同，并集/去重用）。"""
    plan = {"国产机器人": ["300454", "600580"], "特斯拉机器人": ["300454", "002472"],
            "机器人零部件": ["002472"], "四足机器人/机器狗": [],
            "算力概念": ["000977"], "国产算力芯片": ["000977", "603019"],
            "传媒出版": ["601999"], "房地产": ["600048", "001979", "600606"]}
    for name, codes in plan.items():
        code = f"c{abs(hash(name)) % 10000:04d}"
        stocks = [{"code": c, "name": f"股{c}", "sharesRange": 1.0 + i,
                   "exaggeratedCount": 0, "isShares": False, "content": "",
                   "leafPath": f"{name}/leaf{i}"} for i, c in enumerate(codes)]
        db[COLLECTION_INDUSTRY_STOCKS].replace_one(
            {"_id": code},
            {"_id": code, "code": code, "name": name, "level": 1,
             "batchDate": batch, "stockN": len(stocks), "stocks": stocks}, upsert=True)


def test_rebuild_auto_and_manual_protection():
    db = FakeDb()
    _seed_industries(db)
    out = M.rebuild(db, ["机器人", "传媒", "地产", "低空经济"])
    assert out["ok"] and out["mapped"] == 3
    assert set(out["unmapped"]) == {"低空经济"}
    # multi-union 并集 + exact 各就位
    ro = db[M.COLLECTION].docs["机器人"]
    assert ro["matchType"] == "multi-union" and len(ro["industryCodes"]) == 4
    assert db[M.COLLECTION].docs["传媒"]["matchType"] == "contains"
    # manual 固化后 rebuild 不覆盖
    M.manual_set(db, "机器人", ["国产机器人"])
    M.rebuild(db, ["机器人", "传媒", "地产", "低空经济"])
    assert db[M.COLLECTION].docs["机器人"]["matchType"] == "manual"
    assert db[M.COLLECTION].docs["机器人"]["industryNames"] == ["国产机器人"]
    # 空清单=删除回 auto：rebuild 后恢复并集
    M.manual_set(db, "机器人", [])
    M.rebuild(db, ["机器人"])
    assert db[M.COLLECTION].docs["机器人"]["matchType"] == "multi-union"


def test_rebuild_fails_visible_without_industries():
    db = FakeDb()
    out = M.rebuild(db, ["机器人"])
    assert out["ok"] is False and "未初始化" in out["reason"]


def test_rebuild_rolls_back_stale_auto():
    """auto 行失配后（产业库换名录）rebuild 删除该行——不留脏映射；manual 不受影响。"""
    db = FakeDb()
    _seed_industries(db)
    M.rebuild(db, ["机器人", "传媒"])
    assert "机器人" in db[M.COLLECTION].docs
    # 产业库整体换名录（机器人族全下线，上线医药/白酒）
    db[COLLECTION_INDUSTRY_STOCKS].docs.clear()
    for name, codes in (("创新药", ["600521"]), ("白酒", ["000568"])):
        code = f"c{abs(hash(name)) % 10000:04d}"
        stocks = [{"code": c, "name": f"股{c}", "sharesRange": 1.0, "exaggeratedCount": 0,
                   "isShares": False, "content": "", "leafPath": f"{name}/leaf"} for c in codes]
        db[COLLECTION_INDUSTRY_STOCKS].replace_one(
            {"_id": code}, {"_id": code, "code": code, "name": name, "level": 1,
                            "batchDate": "2026-11-01", "stockN": len(stocks),
                            "stocks": stocks}, upsert=True)
    out = M.rebuild(db, ["机器人", "传媒", "白酒"])
    assert "机器人" in out["unmapped"] and "机器人" not in db[M.COLLECTION].docs
    assert "传媒" in out["unmapped"] and "传媒" not in db[M.COLLECTION].docs
    assert db[M.COLLECTION].docs["白酒"]["matchType"] == "exact"


def test_static_members_union_dedup_and_disclosure():
    db = FakeDb()
    _seed_industries(db)
    M.rebuild(db, ["机器人", "算力", "低空经济"])
    ro = M.static_members(db, "机器人")
    # 并集 300454/600580/002472 去重（300454 双现取 sharesRange 高者=1.0 出现在 Tesla=300454 sharesRange=1.0?）
    assert ro["mapped"] is True
    assert ro["codes"] == {"300454", "600580", "002472"}
    assert len(ro["batchDates"]) == 1
    assert ro["sharesMedian"] is not None
    # 多义（算力 → 算力概念+国产算力芯片）
    sl = M.static_members(db, "算力")
    assert sl["codes"] == {"000977", "603019"}
    # 未映射 fail-visible
    miss = M.static_members(db, "低空经济")
    assert miss["mapped"] is False and "未收录" in miss["reason"]


def test_static_members_empty_snapshot_reason():
    """四足机器人/机器狗 成分为空 → mapped=True 但空集 reason（不伪成功）。"""
    db = FakeDb()
    _seed_industries(db)
    M.manual_set(db, "机器狗", ["四足机器人/机器狗"])
    out = M.static_members(db, "机器狗")
    assert out["mapped"] is True and out["codes"] == set() and out["reason"]


# ── _static_rows_compute（operations/sector_nodes V3-3） ───────────────
def test_static_rows_compute(monkeypatch):
    db = FakeDb()
    bars = {"300454": [{"date": "2026-10-24", "close": 11.0}, {"date": "2026-10-25", "close": 12.1}],
            "600580": [{"date": "2026-10-24", "close": 10.0}, {"date": "2026-10-25", "close": 9.9}]}
    monkeypatch.setattr(M, "static_members",
                        lambda db, b: ({"mapped": True, "codes": {"300454", "600580"},
                                        "industries": ["国产机器人(2)"], "batchDates": ["2026-10-25"],
                                        "sharesMedian": 1.0} if b == "机器人"
                        else {"mapped": False, "reason": "产业库未收录"}))
    monkeypatch.setattr(SN, "_daily_bars", lambda code: bars.get(code) or [])
    import contextlib

    @contextlib.contextmanager
    def _ctx(date):
        yield

    monkeypatch.setattr(SN, "bars_need_upto", _ctx)
    out = SN._static_rows_compute(db, "2026-10-25", ["机器人", "低空经济"])
    assert out["低空经济"] == {"mapped": False, "reason": "产业库未收录"}
    r = out["机器人"]
    assert r["mapped"] is True and r["memberN"] == 2 and r["quotedN"] == 2
    assert r["pctMean"] == round((10.0 + (-1.0)) / 2, 2)   # +10% / -1%
    assert r["redRatio"] == 0.5 and r["sharesMedian"] == 1.0
    assert r["batchDates"] == ["2026-10-25"] and r["windowDays"] == 0


def test_static_rows_compute_empty_boards(monkeypatch):
    assert SN._static_rows_compute(None, "2026-10-25", []) == {}
