from __future__ import annotations

import logging
from typing import Any

from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

COLLECTION = "fund_flow_l2"


class FundFlowRepository:
    """``fund_flow_l2`` 集合：L2 主力资金 7 档持久化（一行一股一日）。

    文档含 ``total``（title 摘要）与 ``buckets``（7 档逐笔聚合），
    唯一键 ``{sessionDate, code}``；upsert 覆盖为最新一次采集。
    """

    def __init__(self, database: Any) -> None:
        self._collection = database[COLLECTION]

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("sessionDate", 1), ("code", 1)],
            unique=True,
            name="fund_flow_l2_unique",
        )

    def upsert_many(self, docs: list[dict[str, Any]]) -> int:
        """按 ``{sessionDate, code}`` 批量 upsert，返回写入/更新的文档数。

        H2（2026-08-11 审计）：仅当已存在文档的 ``sourceTs`` 更旧（或缺失）
        时覆盖——MongoDB 慢时（wait_for 超时后后台线程晚完成）旧写不得
        覆盖新写。条件不匹配且文档已存在时 upsert 会撞唯一键，捕获
        ``DuplicateKeyError`` 降级为条件更新（跳过）。
        """
        if not docs:
            return 0

        def _filter(doc: dict[str, Any]) -> dict[str, Any]:
            return {
                "sessionDate": doc["sessionDate"],
                "code": doc["code"],
                "$or": [
                    {"sourceTs": {"$lt": doc["sourceTs"]}},
                    {"sourceTs": {"$exists": False}},
                ],
            }

        operations = [
            UpdateOne(_filter(doc), {"$set": doc}, upsert=True)
            for doc in docs
        ]
        try:
            result = self._collection.bulk_write(operations, ordered=False)
        except DuplicateKeyError:
            # 并发/条件未匹配但唯一键已存在：降级为条件更新（不插入，不覆盖新值）
            operations = [
                UpdateOne(_filter(doc), {"$set": doc}, upsert=False)
                for doc in docs
            ]
            result = self._collection.bulk_write(operations, ordered=False)
        return (result.upserted_count or 0) + (result.modified_count or 0)

    def load_latest_session(self) -> tuple[str, list[dict[str, Any]]]:
        """返回 (最近 sessionDate, 该日全部文档，按 code 排序)；无数据返回 ("", [])。"""
        latest = self._collection.find_one(
            {},
            sort=[("sessionDate", -1)],
            projection={"sessionDate": 1},
        )
        if not latest:
            return "", []
        session_date = str(latest.get("sessionDate") or "")
        if not session_date:
            return "", []
        rows = list(self._collection.find({"sessionDate": session_date}).sort("code", 1))
        return session_date, rows


def project_cache_rows(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MongoDB ``fund_flow_l2`` 文档 → ThemeFundCache 缓存行（zlje 摘要）。

    冷启动恢复用：只取 ``total.zlje`` 摘要进 Redis，完整 7 档 ``buckets``
    保留在 MongoDB。缺少 ``total.zlje`` 的文档跳过。
    """
    rows: list[dict[str, Any]] = []
    for doc in docs:
        total = doc.get("total") or {}
        if "zlje" not in total or "code" not in doc or "sessionDate" not in doc:
            continue
        source = doc.get("source") or "ths_main_monitor"
        rows.append(
            {
                "code": doc["code"],
                "zlje": total["zlje"],
                "sessionDate": doc["sessionDate"],
                "tradingDate": doc.get("tradingDate") or doc["sessionDate"],
                "source": source,
                "moneyFlowSource": source,
                "sourceTs": doc.get("sourceTs") or 0,
            }
        )
    return rows
