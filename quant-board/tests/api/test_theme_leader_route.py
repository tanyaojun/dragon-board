# -*- coding: utf-8 -*-
"""题材层龙头投喂读口 `GET /api/hotlist-jev/theme-leaders`（2026-10-20 加）。

存在理由（AGENTS §1.2-5 研究↔展示同步）：v2 题目集与实际投喂的语料必须在前端可见，
否则「文档/库里有判据、页面上看不到」就是漂移。测试钉住四件事：
1. 无文档 → `no_data=true`（fail-visible，不伪造空成功）；
2. 落库口径（过门后）与模型原答**双显**，不得只给一个；
3. `with_narrative=1` 才附带叙事全文与题目原文（默认不传，避免大包）；
4. 代际/来源分布（`mixedVersions` / `origins`）逐日可见，防跨代混评。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import hotlist_jev_limitup_routes as limitup_module


class _Col:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query, projection=None):
        qd = query.get("tradingDate")
        if qd is None:
            rows = list(self._docs)   # 无参 = 全量（relay_page「全部」路径）
        elif isinstance(qd, dict):
            # P2 修复（review P2-10）：支持 $gte/$lte 闭区间——此前 mock 恒不匹配，
            # 区间查询路径零覆盖
            rows = [d for d in self._docs
                    if (not qd.get("$gte") or d.get("tradingDate") >= qd["$gte"])
                    and (not qd.get("$lte") or d.get("tradingDate") <= qd["$lte"])]
        else:
            rows = [d for d in self._docs if d.get("tradingDate") == qd]
        return _Cursor(rows)

    def count_documents(self, query):
        return len([d for d in self._docs if d.get("tradingDate") == query.get("tradingDate")])


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, spec):
        # 与生产一致：tradingDate 降序，board/code 升序（P2-10：只升序首键与生产行为不等价）
        self._rows = sorted(
            self._rows,
            key=lambda d: (str(d.get(spec[0][0]) or ""), str(d.get("board") or ""),
                           str(d.get("code") or "")),
            reverse=(spec[0][1] < 0))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def __iter__(self):
        return iter(self._rows)


class _Db:
    def __init__(self, docs):
        self._col = _Col(docs)

    def __getitem__(self, name):
        return self._col


def _doc(code, board, **kw):
    base = {
        "_id": f"2026-10-16:{code}", "tradingDate": "2026-10-16",
        "code": code, "name": f"股{code}", "board": board,
        "structure": {"streak": 2, "time": "09:31:00", "boardN": 6,
                      "ladderFollowers": 3, "prevBoardN": 4},
        "answers": {"leader_nextday_continue": {
            "choice": "insufficient", "probabilities": {"insufficient": 1.0}},
            "catalyst_stage": {"choice": "insufficient"}},
        "modelAnswers": {"leader_nextday_continue": {
            "choice": "low_25_45", "probabilities": {"low_25_45": 0.8}}},
        "gate": {"applied": True, "reason": "board_unmapped", "modelChoice": "low_25_45"},
        "evidenceMissing": True, "evidenceMissingReason": "board_unmapped",
        "evidenceIndustry": None, "evidenceEventTitles": [],
        "baselineKey": "streak2|n5-7|early<=10:00",
        "baselineMeta": {"start": "2026-07-16", "end": "2026-10-15"},
        "outcomeSealedNextDay": True, "status": "ok",
        "sampleOrigin": "backfill", "questionSetVersion": "v2",
        "questionSetHash": "985c529fded7", "ammoVersion": "2026-10-20b",
        "usage": {"input_tokens": 2000, "output_tokens": 140}, "latencyMs": 9000,
        "model": "typesafe-systemone", "computedAt": "2026-10-20T18:00:00",
        "narrative": "2026-10-16 交易日 · 盘面事实：……（实际投喂语料）",
        "questionsRaw": {"leader_nextday_continue": {"type": "choice"}},
        "responseRaw": None,
    }
    base.update(kw)
    return base


def _client(monkeypatch, docs):
    db = _Db(docs)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    app = FastAPI()
    app.include_router(limitup_module.router)
    return TestClient(app)


def test_no_data_is_fail_visible_not_empty_success(monkeypatch):
    """无投喂记录 → no_data=true（不得伪装成「0 只龙头」的成功）。"""
    c = _client(monkeypatch, [])
    body = c.get("/api/hotlist-jev/theme-leaders", params={"date": "2026-09-23"}).json()
    assert body["ok"] is True and body["no_data"] is True
    assert body["count"] == 0 and body["leaders"] == []
    assert "versions" not in body      # 无数据不编造代际分布


def test_gated_answer_and_model_answer_are_both_visible(monkeypatch):
    """落库口径（过门后 insufficient）与模型原答（low_25_45）必须双显。

    只显示一个都会误导：显示过门后 → 看不出模型原本想说什么；
    显示原答 → 把未过门的概率当结论（AGENTS §1.2-5 漂移教训）。
    """
    c = _client(monkeypatch, [_doc("600001", "公告")])
    body = c.get("/api/hotlist-jev/theme-leaders", params={"date": "2026-10-16"}).json()
    row = body["leaders"][0]
    assert row["choice"] == "insufficient"
    assert row["modelChoice"] == "low_25_45"
    assert row["gate"]["reason"] == "board_unmapped"
    assert row["evidenceMissing"] is True
    assert body["gatedCount"] == 1
    assert body["sealedCount"] == 1
    # 默认不传大包
    assert "narrative" not in row and "questionsRaw" not in row


def test_with_narrative_exposes_corpus_and_question_set(monkeypatch):
    """`with_narrative=1`：前端「投喂语料」抽屉要看的原文（叙事 + 题目集）原样透出。"""
    c = _client(monkeypatch, [_doc("600001", "机器人")])
    body = c.get("/api/hotlist-jev/theme-leaders",
                 params={"date": "2026-10-16", "with_narrative": "1"}).json()
    row = body["leaders"][0]
    assert "实际投喂语料" in row["narrative"]
    assert row["questionsRaw"]["leader_nextday_continue"]["type"] == "choice"
    assert body["questionSetHash"] == "985c529fded7"


def test_generation_and_origin_distribution_are_visible(monkeypatch):
    """代际/来源分布逐日可见：混代际或含回填样本必须在读口就能看出来（不得默认混评）。"""
    docs = [_doc("600001", "机器人"),
            _doc("600002", "半导体", questionSetVersion="v1", questionSetHash="ff010c50200e",
                 sampleOrigin="live"),
            _doc("600003", "PCB", sampleOrigin="live")]
    c = _client(monkeypatch, docs)
    body = c.get("/api/hotlist-jev/theme-leaders", params={"date": "2026-10-16"}).json()
    assert body["versions"] == {"v1": 1, "v2": 2}
    assert body["mixedVersions"] is True
    assert body["origins"] == {"backfill": 1, "live": 2}
    assert body["statusCounts"] == {"ok": 3}


def test_unsealed_outcome_is_null_not_false(monkeypatch):
    """结局未封 → None（不是 False）。把「未封板」写成「未续板」是伪造结局。"""
    docs = [_doc("600001", "机器人", outcomeSealedNextDay=None)]
    c = _client(monkeypatch, docs)
    body = c.get("/api/hotlist-jev/theme-leaders", params={"date": "2026-10-16"}).json()
    assert body["leaders"][0]["outcomeSealedNextDay"] is None
    assert body["sealedCount"] == 0


# ── 重跑端点（2026-10-20 用户需求；mock 化，绝不真调 jev —— AGENTS §1.2-7） ──

def _rerun_client(monkeypatch, existing_doc):
    """重跑端点测试夹具：token 环境变量 + run mock + 库返回 computedAt 可变的档。"""
    from backend.api import hotlist_jev_limitup_routes as limitup_module

    calls = {}

    def fake_run(date, **kw):
        calls["kw"] = kw
        # 模拟 run() 落库：刷新 computedAt
        existing_doc["computedAt"] = "2026-10-20T21:00:00"
        return {"labeled": 1, "ok": 1, "degraded": 0, "tokensUsed": 2140}

    class _Col:
        def find_one(self, q, proj=None):
            if q.get("_id") and existing_doc.get("_id") == q["_id"]:
                return dict(existing_doc)
            return None

    class _Db:
        def __getitem__(self, name):
            return _Col()

    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: _Db())
    monkeypatch.setattr("backend.operations.theme_leader_label.run", fake_run)
    return limitup_module, calls


def test_rerun_refreshes_computed_at_and_returns_doc(monkeypatch):
    """重跑成功：run 带 force+codes 单只过滤（不整日重跑），computedAt 刷新，返回新档。"""
    module, calls = _rerun_client(
        monkeypatch,
        {"_id": "2026-10-16:002835", "tradingDate": "2026-10-16", "code": "002835",
         "name": "同为股份", "board": "AI应用", "status": "degraded",
         "computedAt": "2026-10-16T16:20:00",
         "answers": {"leader_nextday_continue": {"choice": "low_25_45"}},
         "usage": {"input_tokens": 2000, "output_tokens": 140}})
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(module.router)
    resp = TestClient(app).post(
        "/api/hotlist-jev/theme-leaders/rerun",
        json={"date": "2026-10-16", "code": "002835"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["doc"]["computedAt"] == "2026-10-20T21:00:00"
    assert body["doc"]["code"] == "002835"
    assert body["summary"]["tokensUsed"] == 2140
    kw = calls["kw"]
    assert kw.get("force") is True, "重跑必须 force（覆盖幂等）"
    assert kw.get("confirm_budget") is True
    assert kw.get("codes") == {"002835"}, "必须单只过滤（不过滤会整日重跑烧 30K+ tokens）"


def test_rerun_reports_not_rerun_when_computed_at_stale(monkeypatch):
    """F6：computedAt 未刷新（code 不在龙头集合/入口跳过）→ 显式 not_rerun，不用旧档冒充成功。"""
    module, _ = _rerun_client(
        monkeypatch,
        {"_id": "2026-10-16:002835", "code": "002835",
         "computedAt": "2026-10-16T16:20:00"})
    # run mock 不刷新 computedAt（模拟入口跳过）
    monkeypatch.setattr("backend.operations.theme_leader_label.run",
                        lambda date, **kw: {"ok": 0, "labeled": 0})
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(module.router)
    body = TestClient(app).post(
        "/api/hotlist-jev/theme-leaders/rerun",
        json={"date": "2026-10-16", "code": "002835"}).json()
    assert body["ok"] is False
    assert body["errorCode"] == "not_rerun"


def test_rerun_requires_token_and_payload(monkeypatch):
    """未配 token / 缺 code → 结构化拒绝（不伪造成功）。"""
    from backend.api import hotlist_jev_limitup_routes as module
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object())
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(module.router)
    c = TestClient(app)
    body = c.post("/api/hotlist-jev/theme-leaders/rerun",
                  json={"date": "2026-10-16", "code": "002835"}).json()
    assert body["ok"] is False and body["errorCode"] == "missing_token"
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "k")
    # 缺 code → pydantic 422（校验层拒绝）；空串 code → 路由内 bad_payload
    r = c.post("/api/hotlist-jev/theme-leaders/rerun", json={"date": "2026-10-16"})
    assert r.status_code == 422
    body = c.post("/api/hotlist-jev/theme-leaders/rerun",
                  json={"date": "2026-10-16", "code": "  "}).json()
    assert body["ok"] is False and body["errorCode"] == "bad_payload"


# ── 区间查询路径（review P2-10 补：此前 $gte/$lte 零覆盖） ──

def test_range_query_closed_interval_and_boundary(monkeypatch):
    """start/end 闭区间含边界日；dates 聚合倒序；sort 为 tradingDate 降序。"""
    docs = [_doc("600001", "AI应用", _id="2026-10-14:600001", tradingDate="2026-10-14"),
            _doc("600002", "AI应用", _id="2026-10-15:600002", tradingDate="2026-10-15"),
            _doc("600003", "AI应用", _id="2026-10-16:600003", tradingDate="2026-10-16"),
            _doc("600004", "AI应用", _id="2026-10-17:600004", tradingDate="2026-10-17")]
    c = _client(monkeypatch, docs)
    body = c.get("/api/hotlist-jev/theme-leaders",
                 params={"start": "2026-10-15", "end": "2026-10-16"}).json()
    assert body["ok"] is True and body["range"] == {"start": "2026-10-15", "end": "2026-10-16"}
    assert body["count"] == 2
    assert {r["code"] for r in body["leaders"]} == {"600002", "600003"}
    assert body["dates"] == ["2026-10-16", "2026-10-15"]


def test_unqualified_full_query_has_limit_and_truncation_note(monkeypatch):
    """无参全量默认上限 500 + 截断显式回显（P2-6：60s 轮询不得无界拉取）。"""
    docs = [_doc(f"6{i:05d}", "AI应用", _id=f"2026-10-16:6{i:05d}",
                 tradingDate="2026-10-16") for i in range(520)]
    c = _client(monkeypatch, docs)
    body = c.get("/api/hotlist-jev/theme-leaders").json()
    assert body["count"] == 500 and body["truncated"] is True
    body2 = c.get("/api/hotlist-jev/theme-leaders",
                  params={"date": "2026-10-16"}).json()
    assert body2["truncated"] is False   # 单日路径不受上限影响


# ── rerun P1 修复回归（review P1-1/P1-2：datasetId 缺省 + sampleOrigin 透传） ──

def test_rerun_passes_default_dataset_id_and_preserves_sample_origin(monkeypatch):
    """缺省 datasetId 必须落到 DEFAULT_DATASET_ID（None 会查不到帧、盘面事实恒降级）；
    backfill 档重跑必须保持 sampleOrigin=backfill（泄漏标记不得被静默抹掉）。"""
    module, calls = _rerun_client(
        monkeypatch,
        {"_id": "2026-10-16:002835", "code": "002835", "sampleOrigin": "backfill",
         "computedAt": "2026-10-16T16:20:00"})
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(module.router)
    body = TestClient(app).post(
        "/api/hotlist-jev/theme-leaders/rerun",
        json={"date": "2026-10-16", "code": "002835"}).json()
    assert body["ok"] is True
    kw = calls["kw"]
    from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
    assert kw.get("dataset_id") == DEFAULT_DATASET_ID, "缺省不得传 None（P1-1）"
    assert kw.get("sample_origin") == "backfill", "backfill 必须透传（P1-2）"
    assert body["doc"]["sampleOrigin"] == "backfill"
