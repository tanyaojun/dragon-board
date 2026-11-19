# -*- coding: utf-8 -*-
"""kpl_bidding_series 逐 tick 文档化共享假库（2026-11-19 存储重构配套）。

pymongo 语义最小实现：insert_one/insert_many/find(投影+sort)/find_one/
update_one($set/$inc/$unset, upsert)/count_documents/delete_many/create_index。
查询支持：等值、$exists、$in、$ne、$type(string/objectId)。投影支持：include 顶层键、"it.s" 嵌套、
"_id": 0 排除。sort 支持 [(field, dir)]（_id：meta=日期串、tick=FakeObjectId 插入序，可排序）。

seed_series / seed_series_legacy 是**测试夹具适配器**（旧嵌入 fixture → 新
meta+tick 文档），不是生产双轨——生产读口唯一走 load_bidding_series。
"""
from __future__ import annotations

import copy
import itertools


class _FakeObjectId:
    """ObjectId 仿真：tick 文档 _id 用它，与 meta 的日期串 _id 形成类型判别
    （2026-11-19 review S4：$type:"string" 只命中 meta，同生产 ObjectId/str）。"""
    __slots__ = ("n",)

    def __init__(self, n: int):
        self.n = n

    def __repr__(self):
        return f"FakeObjectId('{self.n:08x}')"

    def __eq__(self, other):
        return isinstance(other, _FakeObjectId) and self.n == other.n

    def __lt__(self, other):
        return self.n < getattr(other, "n", 0)

    def __hash__(self):
        return hash(("fakeoid", self.n))


def _match(doc: dict, q: dict) -> bool:
    for k, v in (q or {}).items():
        val = doc.get(k)
        if isinstance(v, dict):
            for op, ov in v.items():
                if op == "$exists":
                    if (k in doc) != bool(ov):
                        return False
                elif op == "$in":
                    if val not in ov:
                        return False
                elif op == "$ne":
                    if val == ov:
                        return False
                elif op == "$type":
                    if ov == "string":
                        if not isinstance(val, str):
                            return False
                    elif ov in ("objectId", "objectid"):
                        if not isinstance(val, _FakeObjectId):
                            return False
                    else:
                        raise NotImplementedError(f"series_fake 未支持 $type {ov}")
                else:
                    raise NotImplementedError(f"series_fake 未支持算子 {op}")
        elif val != v:
            return False
    return True


def _project(doc: dict, projection: dict | None) -> dict:
    if not projection:
        return doc
    ones = {k for k, v in projection.items() if v}
    zeros = {k for k, v in projection.items() if not v}
    if not (ones - {"_id"}):
        # 排除式投影（如 {"ticks": 0}）：除指定键外全保留
        return {k: v for k, v in doc.items() if k not in zeros}
    out: dict = {}
    if projection.get("_id", 1):
        out["_id"] = doc.get("_id")
    for k in ones - {"_id"}:
        if "." in k:
            top, sub = k.split(".", 1)
            if top == "it" and sub == "s":
                out["it"] = [{"s": it.get("s")} for it in doc.get("it") or []]
            else:
                raise NotImplementedError(f"series_fake 未支持嵌套投影 {k}")
        elif k in doc:
            out[k] = doc[k]
    return out


class FakeSeriesCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, spec):
        if isinstance(spec, str):
            spec = [(spec, 1)]
        for field, direction in reversed(list(spec)):
            self._docs.sort(key=lambda d: (d.get(field) is None, d.get(field)),
                            reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self._docs)

    def __len__(self):
        return len(self._docs)


class FakeSeriesCol:
    def __init__(self):
        self.docs: list[dict] = []
        self._oid = itertools.count(1)
        self.indexes: list = []

    def _new_id(self):
        return _FakeObjectId(next(self._oid))   # 插入序单调，同 ts 页序按 _id 可排

    def insert_one(self, doc):
        d = copy.deepcopy(doc)
        d.setdefault("_id", self._new_id())
        self.docs.append(d)

        class R:
            inserted_id = d["_id"]
        return R()

    def insert_many(self, docs):
        for d in docs:
            self.insert_one(d)

    def find(self, q=None, projection=None):
        return FakeSeriesCursor([_project(copy.deepcopy(d), projection)
                                 for d in self.docs if _match(d, q)])

    def find_one(self, q=None, projection=None):
        for d in self.docs:
            if _match(d, q):
                return _project(copy.deepcopy(d), projection)
        return None

    def update_one(self, q, update, upsert=False):
        target = next((d for d in self.docs if _match(d, q)), None)
        if target is None:
            if not upsert:
                return
            target = {"_id": (q or {}).get("_id", self._new_id())}
            self.docs.append(target)
        for k, v in (update.get("$set") or {}).items():
            target[k] = copy.deepcopy(v)
        for k, v in (update.get("$inc") or {}).items():
            target[k] = (target.get(k) or 0) + v
        for k in (update.get("$unset") or {}):
            target.pop(k, None)

    def count_documents(self, q=None):
        return sum(1 for d in self.docs if _match(d, q))

    def delete_many(self, q=None):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, q)]

        class R:
            deleted_count = before - len(self.docs)
        return R()

    def create_index(self, spec, **kw):
        self.indexes.append(spec)
        return "idx"


def seed_series(col: FakeSeriesCol, date: str, ticks: list[dict], **meta_fields):
    """新形态夹具：meta（_id=date，不含 ticks）+ 逐 tick 文档。"""
    meta = {"_id": date, "date": date, "tick_n": len(ticks), **meta_fields}
    if ticks:
        last = ticks[-1]
        meta.setdefault("last_ts", last.get("ts"))
        meta.setdefault("last_n", last.get("n")
                        if last.get("n") is not None else len(last.get("it") or []))
    col.insert_one(meta)
    for t in ticks:
        col.insert_one({"date": date, "ts": t.get("ts"),
                        "n": t.get("n") if t.get("n") is not None
                        else len(t.get("it") or []),
                        "it": t.get("it") or []})
    return col


def seed_series_legacy(col: FakeSeriesCol, legacy_doc: dict):
    """旧嵌入 fixture {_id, ticks, ...} → 新形态（加字段 prev_pct 等保留）。"""
    meta_fields = {k: v for k, v in legacy_doc.items()
                   if k not in ("_id", "date", "ticks")}
    return seed_series(col, legacy_doc["_id"], legacy_doc.get("ticks") or [],
                       **meta_fields)
