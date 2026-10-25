# -*- coding: utf-8 -*-
"""V3-1 全成分归档链（stock-tree → jiuyan_industry_stocks）测试——全离线 mock，零真实 HTTP。

锁定口径（2026-10-25 用户三拍板：全量 108 首拉 / 周频全量刷新 / 全量纳入+披露强度）：
1. 解析：同股多节点去重取 shares_range 最高人次；code 归一 6 位纯数字，非 6 位剔除计 invalidN；
2. 存储：同批次重拉幂等不滚 prevDiff；跨批次 prevDiff=added/removed 摘要（不存全量旧版）；
3. 断点续拉：当日已成功（batchDate==今日 且 stockN>0）跳过；空成分按失败不落假成功；
4. 编排：预算拦截 fail-visible、部分失败不连坐（§4.0）；
5. 调度守卫：距最新批次 ≥7 天 Popen 挂跑；fresh 批次跳过；env 可关。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_theme_collect as C
from backend.operations import jiuyan_theme_fetch as F
from backend.operations import jiuyan_theme_store as S


# ── 真实响应形状的缩编 fixture（2026-10-25 实测：POST {"code"} → data=树根） ──
def _stock(code, name, shares, content="", exaggerated=0, is_shares=0):
    return {"stock_code": code, "stock_name": name, "shares_range": shares,
            "content": content, "exaggerated_count": exaggerated,
            "is_shares": is_shares, "ai_industry_stock_id": "x"}


STOCK_TREE_PAYLOAD = {
    "errCode": 0,
    "data": {
        "code": "0079", "group_name": "国产机器人", "name": "国产机器人", "level": 1,
        "children": [
            {"code": "00790001", "name": "宇树机器人", "level": "2", "children": [
                {"code": "007900010001", "name": "股权相关", "level": "3", "children": [],
                 "stock_list": [_stock("sz300454", "深信服", 12.85, "持股比例约0.20%"),
                                _stock("sh600580", "卧龙电驱", 5.0)]},
                {"code": "007900010002", "name": "合作商", "level": "3", "children": [],
                 "stock_list": [_stock("300454", "深信服", 2.1),   # 重复出现低关联 → 取 12.85 人次
                                _stock("bad-code", "无效股", 9.9)]},  # 非 6 位 → 剔除
            ]},
        ],
    },
}


# ── 解析层 ────────────────────────────────────────────────────────────
def test_normalize_stock_code():
    assert F.normalize_stock_code("sz300454") == "300454"
    assert F.normalize_stock_code("SH600580") == "600580"
    assert F.normalize_stock_code("600000") == "600000"
    assert F.normalize_stock_code("bj873169") == "873169"
    assert F.normalize_stock_code("") == ""
    assert F.normalize_stock_code("bad-code") == ""
    assert F.normalize_stock_code(None) == ""


def test_parse_stock_tree_ok_and_errcode():
    out = F.parse_stock_tree(STOCK_TREE_PAYLOAD)
    assert out["ok"] is True and out["root"]["code"] == "0079"
    limited = F.parse_stock_tree({"errCode": 9, "msg": "服务繁忙", "data": {}})
    assert limited["ok"] is False and limited.get("rateLimited") is True
    assert F.parse_stock_tree({"errCode": 0, "data": []})["ok"] is False   # 形状异常


def test_flatten_stock_tree_dedup_takes_max_shares():
    ind = F.flatten_stock_tree(F.parse_stock_tree(STOCK_TREE_PAYLOAD)["root"])
    assert ind["code"] == "0079" and ind["name"] == "国产机器人"
    assert ind["invalidN"] == 1
    by = {s["code"]: s for s in ind["stocks"]}
    assert set(by) == {"300454", "600580"}          # 无效股剔除、重复股去重
    assert by["300454"]["sharesRange"] == 12.85      # 取关联最强人次
    assert by["300454"]["leafPath"] == "国产机器人/宇树机器人/股权相关"
    assert by["600580"]["sharesRange"] == 5.0


# ── 存储层 ────────────────────────────────────────────────────────────
def _match(doc, query):
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$gt" and (val is None or not val > arg):
                    return False
                if op not in ("$gt",):
                    raise AssertionError(f"fake 未支持 {op}")
        elif val != cond:
            return False
    return True


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, query, projection=None, sort=None):
        rows = [d for d in self.docs.values() if _match(d, query)]
        if sort:
            for key, direction in sort:
                rows = sorted(rows, key=lambda d: d.get(key) or "",
                              reverse=(direction == -1))
        return dict(rows[0]) if rows else None

    def replace_one(self, query, doc, upsert=False):
        self.docs[doc["_id"]] = dict(doc)
        return type("R", (), {"matched_count": 1})()

    def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        doc = self.docs.get(_id) or {"_id": _id}
        self.docs[_id] = doc
        for path, delta in (update.get("$inc") or {}).items():
            head, _, tail = path.partition(".")
            if tail:
                doc.setdefault(head, {})[tail] = int(doc.get(head, {}).get(tail, 0)) + int(delta)
            else:
                doc[head] = int(doc.get(head, 0)) + int(delta)
        return type("R", (), {"matched_count": 1})()

    def find(self, query=None, projection=None):
        rows = [d for d in self.docs.values() if _match(d, query or {})]
        if projection:
            rows = [{k: d.get(k) for k, v in projection.items() if v} for d in rows]
        return rows


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _stocks(codes):
    return [{"code": c, "name": f"股{c}", "sharesRange": 1.0, "exaggeratedCount": 0,
             "isShares": False, "content": "", "leafPath": "x/y"} for c in codes]


def test_save_industry_stocks_same_batch_idempotent():
    db = FakeDb()
    s1 = S.save_industry_stocks(db, code="0079", name="国产机器人",
                                batch_date="2026-10-25", stocks=_stocks(["300454", "600580"]))
    assert s1 == {"written": 1, "stockN": 2, "changed": True}
    doc = db[S.COLLECTION_INDUSTRY_STOCKS].docs["0079"]
    assert doc["prevDiff"] is None and doc["prevBatchDate"] is None   # 首批无 prev
    # 同批次重拉：幂等，不滚 prevDiff、changed=False
    s2 = S.save_industry_stocks(db, code="0079", name="国产机器人",
                                batch_date="2026-10-25", stocks=_stocks(["300454", "600580"]))
    assert s2["changed"] is False
    assert db[S.COLLECTION_INDUSTRY_STOCKS].docs["0079"]["prevDiff"] is None


def test_save_industry_stocks_cross_batch_rolls_prev_diff():
    db = FakeDb()
    S.save_industry_stocks(db, code="0079", name="国产机器人",
                           batch_date="2026-10-25", stocks=_stocks(["300454", "600580"]))
    S.save_industry_stocks(db, code="0079", name="国产机器人",
                           batch_date="2026-11-01", stocks=_stocks(["300454", "000001"]))
    doc = db[S.COLLECTION_INDUSTRY_STOCKS].docs["0079"]
    assert doc["batchDate"] == "2026-11-01" and doc["prevBatchDate"] == "2026-10-25"
    assert doc["prevDiff"] == {"added": ["000001"], "removed": ["600580"]}
    assert doc["stockN"] == 2 and doc["changedAt"]


def _seed_industry_tree(db):
    for code, name in (("0079", "国产机器人"), ("0120", "物理AI")):
        db[S.COLLECTION_INDUSTRY].replace_one(
            {"_id": code},
            {"_id": code, "code": code, "name": name, "level": 1}, upsert=True)


def test_pending_and_latest_batch():
    db = FakeDb()
    _seed_industry_tree(db)
    pending = S.pending_industry_stock_codes(db, "2026-10-25")
    assert pending == [{"code": "0079", "name": "国产机器人"},
                       {"code": "0120", "name": "物理AI"}]
    S.save_industry_stocks(db, code="0079", name="国产机器人",
                           batch_date="2026-10-25", stocks=_stocks(["300454"]))
    pending2 = S.pending_industry_stock_codes(db, "2026-10-25")
    assert pending2 == [{"code": "0120", "name": "物理AI"}]   # 断点续拉：当日成功跳过
    assert S.latest_industry_stocks_batch(db) == "2026-10-25"


# ── 编排层 ────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(C, "INTER_CALL_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(C, "RATE_LIMIT_RETRY_SLEEP_SECONDS", 0.0)


@pytest.fixture
def fake_env(monkeypatch):
    db = FakeDb()
    _seed_industry_tree(db)
    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": True, "session": "s", "token": "t",
                                      "timestamp": "ts", "source": "cache+cache"})
    monkeypatch.setattr(C, "get_runtime_mongodb_database", lambda: db) \
        if hasattr(C, "get_runtime_mongodb_database") else None
    # collect_stock_tree 内部 import get_runtime_mongodb_database → patch 工厂
    monkeypatch.setattr("backend.data.repositories.repository_factory."
                        "get_runtime_mongodb_database", lambda: db)
    return db


def _mock_tree_fetch(monkeypatch, results: dict):
    """results: {code: fetch 结果 dict}；缺省返回 ok 成分树。"""

    def fake(code, **kw):
        return results.get(code, {"ok": True, "root": None,
                                  "industry": {"code": code, "name": f"产业{code}",
                                               "stocks": _stocks([f"60000{i}" for i in range(3)]),
                                               "invalidN": 0}})
    monkeypatch.setattr(F, "fetch_industry_stock_tree", fake)


def test_collect_stock_tree_full_ok(fake_env, monkeypatch):
    _mock_tree_fetch(monkeypatch, {})
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["ok"] is True and out["written"] == 2 and out["failedN"] == 0
    assert fake_env[S.COLLECTION_INDUSTRY_STOCKS].docs["0079"]["stockN"] == 3


def test_collect_stock_tree_resume_skips_done(fake_env, monkeypatch):
    _mock_tree_fetch(monkeypatch, {})
    C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    calls: list[str] = []

    def counting(code, **kw):
        calls.append(code)
        return {"ok": True, "root": None,
                "industry": {"code": code, "name": "x", "stocks": _stocks(["600001"]),
                             "invalidN": 0}}

    monkeypatch.setattr(F, "fetch_industry_stock_tree", counting)
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["pending"] == 0 and calls == []      # 断点：全部当日成功 → 零调用


def test_collect_stock_tree_empty_stocks_is_failure(fake_env, monkeypatch):
    _mock_tree_fetch(monkeypatch, {"0079": {"ok": True, "root": None,
                                            "industry": {"code": "0079", "name": "国产机器人",
                                                         "stocks": [], "invalidN": 0}}})
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["ok"] is True                       # 部分失败不连坐
    assert out["failedN"] == 1 and out["failed"][0]["code"] == "0079"
    assert "0079" not in fake_env[S.COLLECTION_INDUSTRY_STOCKS].docs   # 不落假成功


def test_collect_stock_tree_budget_gate(fake_env, monkeypatch):
    _mock_tree_fetch(monkeypatch, {})
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25", budget=1)
    assert out["ok"] is False and out["skippedByBudget"] == ["industry_stock_tree"]
    assert not fake_env.cols.get(S.COLLECTION_INDUSTRY_STOCKS) \
        or not fake_env[S.COLLECTION_INDUSTRY_STOCKS].docs


def test_collect_stock_tree_all_down_is_failure(fake_env, monkeypatch):
    _mock_tree_fetch(monkeypatch, {"__all__": {"ok": False, "error": "HTTP 500"}})
    monkeypatch.setattr(F, "fetch_industry_stock_tree",
                        lambda code, **kw: {"ok": False, "error": "HTTP 500"})
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["ok"] is False and out["failedN"] == 2


def test_collect_stock_tree_auth_expiry_selfheals(fake_env, monkeypatch):
    """token 时效 < 挂跑时长（首拉实测 ~25 分钟后 errCode=110 连串）→ force_refresh
    重铸后续跑，不整段判死；刷新限次防死循环。"""
    state = {"n": 0, "refreshes": 0}
    orig_resolve = C.jiuyan_auth.resolve_auth

    def fake_resolve(**kw):
        if kw.get("force_refresh"):
            state["refreshes"] += 1
            return {"ok": True, "session": "s2", "token": "t2", "timestamp": "ts2",
                    "source": "login+minted"}
        return {"ok": True, "session": "s", "token": "t", "timestamp": "ts",
                "source": "cache+cache"}

    def fake_fetch(code, *, session_cookie, token, **kw):
        if token == "t":
            state["n"] += 1
            return {"ok": False, "authFailed": True, "error": "errCode=110 token无效"}
        return {"ok": True, "root": None,
                "industry": {"code": code, "name": "x", "stocks": _stocks(["600001"]),
                             "invalidN": 0}}

    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth", fake_resolve)
    monkeypatch.setattr(F, "fetch_industry_stock_tree", fake_fetch)
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["ok"] is True and out["failedN"] == 0
    assert state["refreshes"] == 1          # 每板块自愈一次（旧 token 首调即 110）
    assert fake_env[S.COLLECTION_INDUSTRY_STOCKS].docs          # 全部落库


def test_collect_stock_tree_auth_refresh_capped(fake_env, monkeypatch):
    """刷新限次后仍 authFailed → 按失败记录不无限重铸。"""
    state = {"refreshes": 0}
    monkeypatch.setattr(C.jiuyan_auth, "resolve_auth",
                        lambda **kw: ({**({"ok": True, "session": "s2", "token": "t2",
                                            "timestamp": "ts2"} if kw.get("force_refresh")
                                          else {"ok": True, "session": "s", "token": "t",
                                                "timestamp": "ts"})}))
    monkeypatch.setattr(F, "fetch_industry_stock_tree",
                        lambda code, **kw: {"ok": False, "authFailed": True,
                                            "error": "errCode=110"})
    out = C.collect_stock_tree(fetch_date="2026-10-25", date="2026-10-25")
    assert out["ok"] is False and out["failedN"] == 2


# ── 调度守卫 ──────────────────────────────────────────────────────────
def test_weekly_guard_fresh_batch_skips(monkeypatch, fake_env):
    from backend.operations import schedule as SCH
    S.save_industry_stocks(fake_env, code="0079", name="国产机器人",
                           batch_date="2026-10-23", stocks=_stocks(["300454"]))
    launched: list = []
    monkeypatch.setattr(SCH.subprocess, "Popen", lambda *a, **k: launched.append(1))
    out = SCH._maybe_launch_stocktree_weekly("2026-10-26")
    assert out["skipped"] and str(out["reason"]).startswith("fresh_batch")
    assert launched == []


def test_weekly_guard_stale_or_never_launches(monkeypatch, fake_env, tmp_path):
    from backend.operations import schedule as SCH
    S.save_industry_stocks(fake_env, code="0079", name="国产机器人",
                           batch_date="2026-10-18", stocks=_stocks(["300454"]))
    monkeypatch.setattr(SCH.repository_factory, "get_runtime_mongodb_database",
                        lambda: fake_env)
    launched: list[list] = []
    monkeypatch.setattr(SCH.subprocess, "Popen",
                        lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(SCH.Path, "mkdir", lambda self, *a, **k: None, raising=False)
    out = SCH._maybe_launch_stocktree_weekly("2026-10-26")
    assert out.get("launched") is True and len(launched) == 1
    assert "--stock-tree" in launched[0]
    # env 关闭 → 不发
    monkeypatch.setenv("JIUYAN_STOCKTREE_WEEKLY_ENABLED", "0")
    out2 = SCH._maybe_launch_stocktree_weekly("2026-10-26")
    assert out2["skipped"] is True
