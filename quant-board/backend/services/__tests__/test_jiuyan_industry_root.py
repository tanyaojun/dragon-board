# -*- coding: utf-8 -*-
"""jiuyan_industry_root（产业树一级→粗桶对照层）单元测试（全 fake，零真库零网络）。

覆盖：①同义归一投票合并（医药医疗→医疗医药）；②阈值 0.40 自动落库/manual 不动；
③低置信 unmapped 披露；④manual_set 词表校验与覆盖优先；⑤root_index 读异常结构化。
"""
from __future__ import annotations

import pytest

from backend.services.jev import jiuyan_industry_root as mir


class FakeCol:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, q=None, proj=None):
        return [dict(d) for d in self.docs]

    def find_one(self, q):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None

    def replace_one(self, q, doc, upsert=False):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in q.items()):
                self.docs[i] = dict(doc)
                return
        self.docs.append(dict(doc))

    def delete_one(self, q):
        self.docs = [d for d in self.docs
                     if not all(d.get(k) == v for k, v in q.items())]


class FakeDB:
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, name):
        return self._cols.setdefault(name, FakeCol())


@pytest.fixture(autouse=True)
def _clean_cache():
    mir.reset_jiuyan_industry_root_cache()
    yield
    mir.reset_jiuyan_industry_root_cache()


def _fake_db():
    action = [
        # 60 日窗口内：医疗医药 与 医药医疗 同义并存 → 票数按主名合并
        {"tradingDate": "2026-11-01", "fields": [
            {"name": "医疗医药", "stocks": [{"code": "sh600001"}, {"code": "sz000100"}]},
            {"name": "机器人", "stocks": [{"code": "sz000200"}]}]},
        {"tradingDate": "2026-11-02", "fields": [
            {"name": "医药医疗", "stocks": [{"code": "sh600001"}, {"code": "sz000100"},
                                            {"code": "sz000300"}]},
            {"name": "公告", "stocks": [{"code": "sz000900"}]}]},
    ]
    industry = [
        {"name": "医疗器械", "stocks": [{"code": "sh600001"}, {"code": "sz000100"},
                                       {"code": "sz000300"}, {"code": "sz000400"}]},
        {"name": "国产机器人", "stocks": [{"code": "sz000200"}, {"code": "sz000500"}]},
    ]
    return FakeDB({
        mir.COLLECTION_ACTION: FakeCol(action),
        mir.COLLECTION_INDUSTRY_STOCKS: FakeCol(industry),
        mir.COLLECTION: FakeCol(),
        mir.COLLECTION_ALIAS: FakeCol(),
    })


def test_votes_merged_by_alias():
    db = _fake_db()
    sug = mir.build_root_votes(db)
    # 医疗器械成员票：医疗医药(1)+医药医疗(1) 同义归一合并 ×2 股 + 医药医疗(1) = 5 票
    s = sug["医疗器械"]
    assert s["root"] == "医疗医药"
    assert s["topVotes"] == 5 and s["totalVotes"] == 5 and s["top1Ratio"] == 1.0
    # 事件桶（公告）不入票
    assert "公告" not in s["top3"]


def test_rebuild_threshold_and_manual_protection():
    db = _fake_db()
    out = mir.rebuild_roots(db)
    assert out["ok"] is True
    # 医疗器械 ratio=3/4=0.75 ≥0.40 → auto 落库
    row = db[mir.COLLECTION].find_one({"_id": "医疗器械"})
    assert row and row["rootName"] == "医疗医药" and row["matchType"] == "auto_vote"
    # manual 行不被 rebuild 覆盖
    mir.manual_set(db, "医疗器械", "机器人")
    out2 = mir.rebuild_roots(db)
    assert "医疗器械" not in (out2.get("changed") or [])
    assert db[mir.COLLECTION].find_one({"_id": "医疗器械"})["matchType"] == "manual"


def test_low_confidence_unmapped_disclosed():
    db = _fake_db()
    out = mir.rebuild_roots(db)
    assert "国产机器人" not in {u["node"] for u in out.get("unmapped") or []}
    assert db[mir.COLLECTION].find_one({"_id": "国产机器人"}) is not None
    # 加入分票档：机器人(1)/大消费(1)/PCB(1) → ratio 0.333 < 0.40 → unmapped +
    # stale auto 行回退删除（消费方保留 level-1 原值兑底，不猜）
    db[mir.COLLECTION_ACTION].docs.append(
        {"tradingDate": "2026-11-03", "fields": [
            {"name": "大消费", "stocks": [{"code": "sz000500"}]}]})
    db[mir.COLLECTION_ACTION].docs.append(
        {"tradingDate": "2026-11-04", "fields": [
            {"name": "PCB", "stocks": [{"code": "sz000500"}]}]})
    out3 = mir.rebuild_roots(db)
    unmapped3 = {u["node"]: u for u in out3.get("unmapped") or []}
    assert "国产机器人" in unmapped3
    assert unmapped3["国产机器人"]["reason"] == "low_confidence"
    assert db[mir.COLLECTION].find_one({"_id": "国产机器人"}) is None


def test_manual_set_vocab_validation():
    db = _fake_db()
    # root 不在打标链主名词表（大消费未在 fake 打标链出现 → 假名）→ 拒绝
    r = mir.manual_set(db, "医疗器械", "不存在的板块")
    assert r["ok"] is False and "无此粗桶" in r["error"]
    # 假库打标链含 大消费（补档）→ 通过
    db[mir.COLLECTION_ACTION].docs.append(
        {"tradingDate": "2026-11-05", "fields": [{"name": "大消费", "stocks": [{"code": "sz000600"}]}]})
    r2 = mir.manual_set(db, "医疗器械", "大消费")
    assert r2["ok"] is True and r2["rootName"] == "大消费"
    # 空值=删除回 auto
    mir.manual_set(db, "医疗器械", "")
    assert db[mir.COLLECTION].find_one({"_id": "医疗器械"}) is None


def test_root_index_read_error_structured(monkeypatch):
    class BoomCol:
        def find(self, q=None, proj=None):
            raise RuntimeError("db down")
    db = FakeDB({mir.COLLECTION: BoomCol()})
    idx = mir.root_index(db)
    assert idx == {}               # 空索引 + 不缓存失败态（下次重试）
