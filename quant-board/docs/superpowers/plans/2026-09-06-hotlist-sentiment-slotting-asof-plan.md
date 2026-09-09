# 热榜情绪槽位级落库与时点查询实施计划（WP1b + WP1c）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hotlist_sentiment 增加槽位级文档（collector 每槽落帧后同源计算落库），回测/live 的情绪注入从"按日粒度赋给当日全部帧"改为按帧时点的 as-of 查询，消除 lookahead。

**Architecture:** `_id`/`slotTime` 哨兵契约（EOD 保留现 `_id` + slotTime="EOD"，槽位文档 `_id` 追加 `:{slot}`）；存储层提供槽位列表/EOD 两类读原语，as-of 选择编排放 provider 闭包（per-date 内存缓存，库查询 O(天数)）；collector 挂载在 `_persist_one` save 成功后，计算异常不阻断帧采集。

**Tech Stack:** Python 3 / MongoDB（测试用 Fake db）、FastAPI 路由不改。

**Spec:** `quant-board/docs/superpowers/specs/2026-09-06-hotlist-sentiment-slotting-asof-design.md`

**前置：** WP1a 计划（`2026-09-06-hotlist-sentiment-backend-migration-plan.md`）已实施完成——`build_hotlist_sentiment_document` 已含 `day_before_stocks`/`market_data` 参数，`HotListSentimentBackfillService` 取数方法已转公开（`trading_dates`/`latest_frame`/`stocks_for_frame`/`previous_day_stocks`），`services/theme/hotlist_sentiment_compute.py` 已存在。

## Global Constraints

- **TDD 不可跳过**：每个任务先写测试锁行为，再写实现。
- **无质量阻断**：情绪计算任何异常都不阻断帧采集/回测，只记 warning 或 stale/missing 标注。
- 测试位置：`quant-board/tests/*.py`；Fake 类（`FakeCursor`/`FakeReplaceResult`/`FakeCollection`/`FakeMongoDb`）从 `tests/test_hotlist_sentiment_backfill.py` L6-79 **就地复制**到新测试文件（不跨测试文件 import）。
- **pytest 全量有挂起问题**：只跑相关子集；新测试文件先 `--collect-only`。
- Python 算法只放 `backend/analysis/**`；有 I/O 编排放 `backend/services/**`；路由放 `backend/api/**`。
- 文案移植：JS toFixed 半进位 vs Python 银行家舍入的对齐已在 WP1a 处理，本计划不涉及新数值文案。
- 禁止递归删除；commit 风格 `feat(sentiment): 中文描述`。
- 验证命令目录：pytest 在 `quant-board/`。

## 源文件坐标（执行者必读）

| 内容 | 位置 |
|---|---|
| 存储服务（upsert/get_by_date/单例/provider） | `quant-board/backend/services/theme/hotlist_sentiment_service.py`（85 行，全文已核） |
| backfill 服务 | `quant-board/backend/operations/hotlist_sentiment.py`（`run_for_date` L84-138、`_trading_dates` L140、`_latest_frame` L163、`_previous_day_stocks` L169、`_stocks_for_frame` L176、`_business_key` L233） |
| 文档构造（WP1a 后含 market_data 参数） | `operations/hotlist_sentiment.py` `build_hotlist_sentiment_document`（WP1a Task 5 版本） |
| 索引定义 | `quant-board/backend/data/migrations/mongodb_migration.py` L190-196（唯一索引三元组） |
| collector 挂载点 | `quant-board/backend/snapshot_collector/service.py` `_persist_one` L522-539（save → run_status → cache_invalidate），slot_time 变量 L546 可见 |
| lookahead 本体 | `quant-board/backend/analysis/ranktrend/engine/runtime.py` `_ensure_hotlist_sentiment` L958-984（by_key 按日缓存 L968-977、状态标注 L978） |
| frame slotTime 字段 | runtime.py L1277 `"slotTime": frame.get("slotTime")` |
| provider 注入方（仅传参，预计不动） | `core/backtest/engine.py` L24-29、`services/backtest_service.py` L849-853、`api/ranktrend_routes.py` L787-792 |
| market_regime | `analysis/ranktrend/trend/risk.py` L74（reasons 输出 L149-155） |
| compute service（WP1a Task 6 产物） | `services/theme/hotlist_sentiment_compute.py`（`_compute_and_persist` 调 `HotListSentimentService(self._backfill._db).upsert(doc)`） |
| Fake 类来源 | `quant-board/tests/test_hotlist_sentiment_backfill.py` L6-79 |

### 契约定稿（与 spec 的实现细化）

- `build_hotlist_sentiment_document(..., slot_time: str | None = None)`：`None` → `slotTime="EOD"` 哨兵 + `_id` 无后缀（EOD 形态，现调用方零改动自动获得哨兵）；传 `"HH:MM"` → `slotTime=slot_time` + `_id` 追加 `:{slot}`。**该函数是 `_id`/`slotTime` 的唯一构造点。**
- as-of 选择逻辑放 `make_hotlist_sentiment_provider` 闭包（per-date 槽位文档内存缓存）；`HotListSentimentService` 只提供两个读原语：`list_slot_documents(date)` 与 `get_eod_document(date)`（spec 的 `get_as_of` 拆为闭包编排 + service 原语，语义等价、缓存安全且不破坏"纯存储封装"分层）。
- provider 闭包新合同：`(trading_date, slot_time) -> tuple[dict | None, str]`，status ∈ "ok"/"stale"/"missing"；`slot_time=None` 时走旧按日路径（防御性兼容）。
- `compute_and_upsert_for_slot(mongo_db, *, dataset_id, snapshot_type, trading_date, slot_time)`：与 spec b2 的签名（含 frame/stock_rows 入参）不同——改为**全库取数**（不信任内存对象，保证 save-后-计算一致性，且 collector 侧调用更简）；偏差原因与测试见 Task 6。

---

### Task 1: 存储层契约——slot_time 参数、哨兵、读原语

**Files:**
- Modify: `quant-board/backend/services/theme/hotlist_sentiment_service.py`
- Modify: `quant-board/backend/operations/hotlist_sentiment.py`（`build_hotlist_sentiment_document` 加 `slot_time` 参数）
- Modify: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`（`ensure_series` 三键 find_one 改走 service 读原语）
- Test: `quant-board/tests/test_hotlist_sentiment_slot_store.py`（新建）

**Interfaces:**
- Consumes: WP1a 的 `build_hotlist_sentiment_document` 现有签名。
- Produces:
  - `build_hotlist_sentiment_document(..., slot_time: str | None = None) -> dict`（`_id`/`slotTime` 契约如上）。
  - `HotListSentimentService.upsert(payload)`：**按 `_id` 精确 upsert**（`replace_one({"_id": doc_id}, doc, upsert=True)`；payload 无 `_id` 时按四键格式构造兜底）。**不用四键业务 query**——存量 EOD 行 slotTime 仍是旧 "HH:MM" 值时，四键 query 会在 upsert 时命中 `_id` 不同的行导致 MongoDB 拒绝改 `_id`（DuplicateKeyError）。
  - `HotListSentimentService.get_by_date(dataset_id, snapshot_type, trading_date)`：**按 `_id` 精确查询** `find_one({"_id": f"{dataset_id}:{snapshot_type}:{trading_date}"})`——存量行（`_id` 无后缀、slotTime 为旧值）与迁移后哨兵行都命中，现消费方零感知；**不按 `slotTime: "EOD"` 过滤**（迁移未跑完时旧行无该值会漏读）。
  - `HotListSentimentService.list_slot_documents(dataset_id, snapshot_type, trading_date) -> list[dict]`：**双条件排除 EOD**——`"_id": {"$ne": f"{dataset_id}:{snapshot_type}:{trading_date}"}`（滤掉存量 EOD 行）+ `"slotTime": {"$ne": "EOD"}`（滤掉迁移后哨兵行）；按 slotTime 升序。
  - `HotListSentimentService.get_eod_document(dataset_id, snapshot_type, trading_date) -> dict | None`（get_by_date 显式命名别名）。
  - `HotListSentimentService.__init__` 保存 `self._db = mongo_db`（Task 3 `_query_trading_dates` 需经 `service._db` 访问 snapshot_frames）。

- [ ] **Step 1: 写失败测试**

`quant-board/tests/test_hotlist_sentiment_slot_store.py`（顶部就地复制 Fake 四类）：

```python
from __future__ import annotations

from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document
from backend.services.theme.hotlist_sentiment_service import HotListSentimentService


def _frame(slot: str) -> dict:
    return {"snapshotId": f"snap-{slot}", "slotTime": slot, "timestamp": 1757000000}


def _stocks() -> list[dict]:
    return [{"code": "000001", "name": "甲", "compRank": 1, "change": 5.0, "turnover": 8e8,
             "zlje": 1e8, "zljzb": 12, "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4,
             "turnoverRate": 8, "rank": 1}]


def test_build_document_eod_sentinel_without_slot_time():
    doc = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05",
        frame=_frame("15:00"), stocks=_stocks(),
    )
    assert doc["_id"] == "d1:half_hour:2026-06-05"
    assert doc["slotTime"] == "EOD"


def test_build_document_slot_suffix_with_slot_time():
    doc = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05",
        frame=_frame("10:30"), stocks=_stocks(), slot_time="10:30",
    )
    assert doc["_id"] == "d1:half_hour:2026-06-05:10:30"
    assert doc["slotTime"] == "10:30"


def test_upsert_query_includes_slot_time():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    service.upsert({"_id": "d1:half_hour:2026-06-05:10:30", "datasetId": "d1",
                    "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                    "slotTime": "10:30", "stage": "启动"})
    service.upsert({"_id": "d1:half_hour:2026-06-05:11:00", "datasetId": "d1",
                    "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                    "slotTime": "11:00", "stage": "发酵"})
    rows = fake_db["hotlist_sentiment"].rows
    assert len(rows) == 2  # 同日两槽不互吞
    assert rows[0]["_id"] == "d1:half_hour:2026-06-05:10:30"


def test_get_by_date_hits_eod_only():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    service.upsert({"datasetId": "d1", "snapshotType": "half_hour",
                    "tradingDate": "2026-06-05", "slotTime": "EOD", "stage": "退潮"})
    doc = service.get_by_date("d1", "half_hour", "2026-06-05")
    assert doc is not None and doc["slotTime"] == "EOD"
    assert service.get_by_date("d1", "half_hour", "2026-06-99") is None


def test_list_slot_documents_sorted_and_excludes_eod():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    for slot in ("11:00", "10:00", "EOD"):
        service.upsert({"datasetId": "d1", "snapshotType": "half_hour",
                        "tradingDate": "2026-06-05", "slotTime": slot, "stage": "启动"})
    slots = service.list_slot_documents("d1", "half_hour", "2026-06-05")
    assert [doc["slotTime"] for doc in slots] == ["10:00", "11:00"]
    assert service.get_eod_document("d1", "half_hour", "2026-06-05")["slotTime"] == "EOD"
    assert service.get_eod_document("d1", "half_hour", "2026-06-04") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_store.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_store.py -v`
Expected: FAIL（`slot_time` 参数不存在 / upsert 互吞 / get_by_date 命中非哨兵行）。

- [ ] **Step 3: 实现**

`operations/hotlist_sentiment.py` `build_hotlist_sentiment_document`（WP1a 版本上改 3 行）：

```python
def build_hotlist_sentiment_document(
    *,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    frame: dict[str, Any],
    stocks: list[dict[str, Any]],
    yesterday_stocks: list[dict[str, Any]] | None = None,
    day_before_stocks: list[dict[str, Any]] | None = None,
    market_data: dict[str, Any] | None = None,
    slot_time: str | None = None,
) -> dict[str, Any]:
    # ... 纯函数调用不变 ...
    slot = str(slot_time) if slot_time else "EOD"   # None → EOD 哨兵（日级终值契约）
    suffix = f":{slot}" if slot_time else ""
    return {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}{suffix}",
        # ... 其余字段不变 ...
        "slotTime": slot,
        # ...
    }
```

`services/theme/hotlist_sentiment_service.py`（`__init__` 补一行 + 三方法重写）：

```python
    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db  # Task 3 _query_trading_dates 经此访问 snapshot_frames
        self._collection = mongo_db["hotlist_sentiment"]

    def upsert(self, payload: dict[str, Any]) -> None:
        """按 _id 精确 upsert 一条情绪文档（slotTime="EOD" 哨兵 / "HH:MM" 槽位）。

        _id 由 build_hotlist_sentiment_document 构造（唯一构造点）；payload 缺 _id 时
        按四键格式构造兜底。query 用 _id 而非业务四键——存量行 slotTime 为旧 "HH:MM"
        值时，业务 query 命中 _id 不同的行会导致 MongoDB 拒绝改 _id（DuplicateKeyError）。
        """
        dataset_id = str(payload.get("datasetId") or "")
        snapshot_type = str(payload.get("snapshotType") or "")
        trading_date = str(payload.get("tradingDate") or "")
        slot_time = str(payload.get("slotTime") or "EOD")
        doc = dict(payload)
        doc.setdefault("slotTime", slot_time)
        doc.setdefault(
            "_id",
            f"{dataset_id}:{snapshot_type}:{trading_date}"
            + ("" if slot_time == "EOD" else f":{slot_time}"),
        )
        doc["computedAt"] = int(time.time())
        self._collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def get_by_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        """按日读取 EOD 终值文档（按 _id 精确命中——存量行与迁移后哨兵行同 _id，均返回）。"""
        return self._collection.find_one({"_id": f"{dataset_id}:{snapshot_type}:{trading_date}"})

    def list_slot_documents(self, dataset_id: str, snapshot_type: str, trading_date: str) -> list[dict[str, Any]]:
        """当日全部槽位文档，按 slotTime 升序。

        双条件排除 EOD：_id $ne 滤掉存量 EOD 行（slotTime 仍为旧 "HH:MM" 值），
        slotTime $ne "EOD" 滤掉迁移后哨兵行。
        """
        return list(
            self._collection.find(
                {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "_id": {"$ne": f"{dataset_id}:{snapshot_type}:{trading_date}"},
                    "slotTime": {"$ne": "EOD"},
                }
            ).sort([("slotTime", 1)])
        )

    def get_eod_document(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        """指定交易日的 EOD 终值文档（get_by_date 的显式命名别名，供 as-of 回退用）。"""
        return self.get_by_date(dataset_id, snapshot_type, trading_date)
```

注意：`upsert` 的 `_id` setdefault 兜底只服务直接构造 payload 的测试/调用方；生产路径 `_id` 恒由 `build_hotlist_sentiment_document` 传入。核对 WP1a `_compute_and_persist` 的 upsert 调用——doc 已含 `_id`/`slotTime`，无需改动。

`services/theme/hotlist_sentiment_compute.py` `ensure_series` 内（WP1a Task 6 产物）的三键 `find_one` 改走 service 读原语（读口统一，避免查询形状漂移；`get_eod_document` 按 `_id` 命中，slotTime 哨兵迁移前后行为不变）：

```python
    doc = HotListSentimentService(mongo_db=self._db).get_eod_document(dataset_id, snapshot_type, trading_date)
```

（compute service 的 `__init__` 已持有 `mongo_db`——按其实际属性名引用；`HotListSentimentService` import 已在该文件顶部。）

- [ ] **Step 4: 回归既有测试**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_store.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py -v`
Expected: 全部 PASS（`get_by_date` 改按 `_id` 精确查询后，存量与哨兵行行为一致；WP1a 的 series lazy compute 产出的 EOD 文档 slotTime 自动变哨兵，series 断言不含 slotTime 应不受影响；若有断言 slotTime=="HH:MM" 的用例，改为断言 "EOD" 并注明哨兵契约）。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/services/theme/hotlist_sentiment_service.py quant-board/backend/operations/hotlist_sentiment.py quant-board/backend/services/theme/hotlist_sentiment_compute.py quant-board/tests/test_hotlist_sentiment_slot_store.py
git commit -m "feat(sentiment): 槽位文档 _id/slotTime 契约（EOD 哨兵 + 槽位后缀）与存储读原语"
```

---

### Task 2: 索引重建 + 存量迁移脚本

**Files:**
- Modify: `quant-board/backend/data/migrations/mongodb_migration.py:190-196`
- Create: `quant-board/backend/operations/migrate_hotlist_sentiment_slot_eod.py`
- Test: `quant-board/tests/test_hotlist_sentiment_slot_migration.py`（新建）

**Interfaces:**
- Produces:
  - 唯一索引 `("datasetId", "snapshotType", "tradingDate", "slotTime")`（unique）。
  - `migrate_eod_slot_time(mongo_db) -> dict`：把 `slotTime != "EOD"` 的 EOD 形态存量文档（`_id` 不含槽位后缀 = 恰好 3 段）批量置 `"EOD"`；返回 `{"matched": N, "updated": M}`。
  - `drop_legacy_unique_index(mongo_db) -> dict`：drop 旧三元组唯一索引 `datasetId_1_snapshotType_1_tradingDate_1`（**部署硬约束**——MongoDB 的 `create_index` 不会自动删除键集不同但同样唯一约束的旧索引；旧索引不 drop，同日第二个槽位 upsert 会触发旧唯一索引冲突而失败）。索引不存在/命名差异时返回 `{"dropped": None, "reason": ...}` 不抛错。CLI 入口 `python -m backend.operations.migrate_hotlist_sentiment_slot_eod [--dry-run] [--skip-index-drop]`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.operations.migrate_hotlist_sentiment_slot_eod import (
    drop_legacy_unique_index,
    migrate_eod_slot_time,
)


def test_migrate_legacy_eod_slot_time():
    fake_db = FakeMongoDb()  # 就地复制 Fake 四类，并在 FakeCollection 复制件补最小 update_one：
    #   def update_one(self, query: dict, update: dict) -> None:
    #       set_body = update.get("$set") or {}
    #       for row in self.rows:
    #           if all(row.get(k) == v for k, v in query.items()):
    #               row.update(set_body)
    #               return
    coll = fake_db["hotlist_sentiment"]
    coll.rows.append({"_id": "d1:half_hour:2026-06-04", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-04",
                      "slotTime": "15:00", "stage": "退潮"})
    coll.rows.append({"_id": "d1:half_hour:2026-06-05:10:30", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                      "slotTime": "10:30", "stage": "启动"})
    result = migrate_eod_slot_time(fake_db)
    assert result["updated"] == 1
    assert coll.rows[0]["slotTime"] == "EOD"
    assert coll.rows[1]["slotTime"] == "10:30"  # 槽位文档不动


def test_migrate_idempotent():
    fake_db = FakeMongoDb()  # 同上复制（含 update_one 补充）
    fake_db["hotlist_sentiment"].rows.append({
        "_id": "d1:half_hour:2026-06-04", "datasetId": "d1", "snapshotType": "half_hour",
        "tradingDate": "2026-06-04", "slotTime": "EOD", "stage": "退潮"})
    result = migrate_eod_slot_time(fake_db)
    assert result["updated"] == 0


def test_drop_legacy_index_tolerates_missing():
    fake_db = FakeMongoDb()  # FakeCollection 复制件补：
    #   def drop_index(self, name_or_keys) -> None:
    #       raise KeyError(f"index not found: {name_or_keys}")   # 模拟索引不存在
    result = drop_legacy_unique_index(fake_db)
    assert result["dropped"] is None and result["reason"]  # 容错不抛
```

- [ ] **Step 2: 运行确认失败**（模块不存在）

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_migration.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_migration.py -v`

- [ ] **Step 3: 实现迁移函数 + CLI 与索引定义**

`backend/operations/migrate_hotlist_sentiment_slot_eod.py`：

```python
"""一次性迁移：存量 hotlist_sentiment EOD 文档 slotTime → "EOD" 哨兵 + drop 旧唯一索引。

识别规则：_id 恰好 3 段（dataset:snapshot_type:date）= EOD 形态；
槽位文档 _id 4 段不动。幂等（已是 "EOD" 的不更新）。
部署硬约束：旧三元组唯一索引 datasetId_1_snapshotType_1_tradingDate_1 必须 drop——
MongoDB create_index 不会自动替换键集不同的唯一索引，旧索引残留时同日第二槽
upsert 会被旧索引拒绝。索引名若与预期不符（命名差异），从 list_indexes 输出人工确认。
用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.migrate_hotlist_sentiment_slot_eod [--dry-run] [--skip-index-drop]
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

LEGACY_UNIQUE_INDEX_NAME = "datasetId_1_snapshotType_1_tradingDate_1"


def migrate_eod_slot_time(mongo_db: Any, dry_run: bool = False) -> dict[str, Any]:
    coll = mongo_db["hotlist_sentiment"]
    matched = updated = 0
    for row in coll.find({}):
        doc_id = str(row.get("_id") or "")
        if doc_id.count(":") != 2:
            continue  # 槽位文档（4 段）或异常形态不动
        matched += 1
        if str(row.get("slotTime") or "") == "EOD":
            continue
        updated += 1
        if not dry_run:
            coll.update_one({"_id": doc_id}, {"$set": {"slotTime": "EOD"}})
    return {"matched": matched, "updated": updated, "dryRun": dry_run}


def drop_legacy_unique_index(mongo_db: Any) -> dict[str, Any]:
    """drop 旧三元组唯一索引（容错：不存在/命名差异时返回 reason 不抛错）。"""
    coll = mongo_db["hotlist_sentiment"]
    try:
        coll.drop_index(LEGACY_UNIQUE_INDEX_NAME)
        return {"dropped": LEGACY_UNIQUE_INDEX_NAME}
    except Exception as exc:
        return {"dropped": None, "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="hotlist_sentiment EOD slotTime 哨兵迁移")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-index-drop", action="store_true", help="仅迁移数据，不动索引")
    args = parser.parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    mongo_db = get_runtime_mongodb_database()
    result = migrate_eod_slot_time(mongo_db, dry_run=args.dry_run)
    print({"migration": result}, file=sys.stderr)
    if not args.skip_index_drop and not args.dry_run:
        print({"indexDrop": drop_legacy_unique_index(mongo_db)}, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`mongodb_migration.py` L190-196 唯一索引改：

```python
        "hotlist_sentiment": [
            {
                "keys": [("datasetId", 1), ("snapshotType", 1), ("tradingDate", 1), ("slotTime", 1)],
                "unique": True,
            },
            {"keys": [("datasetId", 1), ("snapshotType", 1), ("computedAt", -1)]},
        ],
```

- [ ] **Step 4: 测试通过 + 手工迁移生产库**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_migration.py -v`
Expected: PASS。生产库执行：先 `--dry-run` 看数字，再实跑，记录 updated 数与 indexDrop 结果。
**部署约束（顺序敏感）**：新索引由 mongodb_migration 启动时自动 create（四键），但**必须执行本迁移脚本 drop 旧三元组唯一索引**后才允许 collector/backfill 写第二个槽位——用 `db.hotlist_sentiment.getIndexes()` 人工验证：新四键唯一索引存在、旧 `datasetId_1_snapshotType_1_tradingDate_1` 已不在。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/data/migrations/mongodb_migration.py quant-board/backend/operations/migrate_hotlist_sentiment_slot_eod.py quant-board/tests/test_hotlist_sentiment_slot_migration.py
git commit -m "feat(sentiment): hotlist_sentiment 唯一索引扩 slotTime + 存量 EOD 哨兵迁移脚本"
```

---

### Task 3: as-of provider——闭包编排 + 逐帧注入（lookahead 修复本体）

**Files:**
- Modify: `quant-board/backend/services/theme/hotlist_sentiment_service.py`（`make_hotlist_sentiment_provider` 闭包重写）
- Modify: `quant-board/backend/analysis/ranktrend/engine/runtime.py:958-984`（`_ensure_hotlist_sentiment`）
- Test: `quant-board/tests/test_hotlist_sentiment_asof_provider.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `list_slot_documents` / `get_eod_document` / `get_by_date`；`HotListSentimentBackfillService.trading_dates`（WP1a 公开方法）。
- Produces:
  - `make_hotlist_sentiment_provider(dataset_id, snapshot_type="half_hour")` 闭包合同 `(trading_date: str, slot_time: str | None) -> tuple[dict | None, str]`（"ok"/"stale"/"missing"）；闭包内 per-date 槽位文档与 trading_dates 内存缓存（闭包生命周期 = 单次回测/live 请求，天然无失效问题）。
  - `_ensure_hotlist_sentiment`：逐帧注入，`frame["hotlistSentiment"]` = doc、`frame["hotlistSentimentStatus"]` = status；异常分支保持（"missing" + reason）。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.services.theme.hotlist_sentiment_service import make_hotlist_sentiment_provider


def _seed(fake_db) -> None:
    coll = fake_db["hotlist_sentiment"]
    frames = fake_db["snapshot_frames"]
    for date in ("2026-06-04", "2026-06-05"):
        frames.rows.append({"datasetId": "d1", "type": "half_hour", "tradingDate": date,
                            "snapshotId": f"snap-{date}", "slotTime": "15:00", "timestamp": 1})
    for slot, stage in (("10:00", "启动"), ("11:00", "发酵")):
        coll.rows.append({"_id": f"d1:half_hour:2026-06-05:{slot}", "datasetId": "d1",
                          "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                          "slotTime": slot, "stage": stage})
    coll.rows.append({"_id": "d1:half_hour:2026-06-04", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-04",
                      "slotTime": "EOD", "stage": "退潮"})
    coll.rows.append({"_id": "d1:half_hour:2026-06-05", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                      "slotTime": "EOD", "stage": "高潮"})  # 06-06 stale 回退的命中对象


def test_asof_picks_latest_slot_not_after_frame_time():
    fake_db = FakeMongoDb()  # 就地复制 Fake 四类
    _seed(fake_db)
    provider = make_hotlist_sentiment_provider("d1", "half_hour")
    doc, status = provider("2026-06-05", "10:30")
    assert status == "ok" and doc["stage"] == "启动"       # ≤10:30 的最新槽
    doc, status = provider("2026-06-05", "11:30")
    assert status == "ok" and doc["stage"] == "发酵"


def test_asof_falls_back_to_previous_day_eod_stale():
    fake_db = FakeMongoDb()  # 同上
    _seed(fake_db)
    provider = make_hotlist_sentiment_provider("d1", "half_hour")
    doc, status = provider("2026-06-05", "09:30")          # 当日无 ≤09:30 槽位 → 回退 06-04 EOD
    assert status == "stale" and doc["stage"] == "退潮"
    doc, status = provider("2026-06-06", "10:00")          # 当日完全无文档 → 回退 06-05 EOD
    assert status == "stale" and doc["stage"] == "高潮"


def test_asof_missing_when_no_data_at_all():
    fake_db = FakeMongoDb()  # 同上
    provider = make_hotlist_sentiment_provider("d1", "half_hour")
    doc, status = provider("2026-06-06", "10:00")
    assert doc is None and status == "missing"


def test_asof_slot_order_boundary_not_after():
    fake_db = FakeMongoDb()  # 同上
    _seed(fake_db)
    provider = make_hotlist_sentiment_provider("d1", "half_hour")
    doc, status = provider("2026-06-05", "11:00")          # 恰等于槽位时间 → 含该槽
    assert status == "ok" and doc["stage"] == "发酵"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_asof_provider.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_asof_provider.py -v`
Expected: FAIL（provider 现签名只收 1 参、返回 doc 不返回元组）。

- [ ] **Step 3: 重写 provider 闭包**

`services/theme/hotlist_sentiment_service.py` 尾部替换 `make_hotlist_sentiment_provider`：

```python
def make_hotlist_sentiment_provider(
    dataset_id: str,
    snapshot_type: str = "half_hour",
) -> Callable[[str, str | None], tuple[dict[str, Any] | None, str]]:
    """构造 ranktrend engine 注入用的 as-of sentiment provider。

    合同：(trading_date, slot_time) -> (doc | None, status)。
    status: "ok"=当日 ≤slot_time 的最新槽位文档；"stale"=回退前一交易日 EOD；
    "missing"=两者皆无（fail-visible，由 engine 写 frame["hotlistSentimentStatus"]）。
    slot_time=None 时走旧按日路径（get_by_date，防御性兼容旧调用方）。

    缓存：闭包生命周期 = 单次回测/请求；trading_dates 与当日槽位文档按日期缓存，
    库查询 O(天数)，逐帧选择纯内存。
    """
    service = get_hotlist_sentiment_service()
    dates_cache: dict[str, list[str]] = {}
    slots_cache: dict[str, list[dict[str, Any]]] = {}
    eod_cache: dict[str, dict[str, Any]] = {}

    def _trading_dates() -> list[str]:
        if "dates" not in dates_cache:
            dates_cache["dates"] = _query_trading_dates(service, dataset_id, snapshot_type)
        return dates_cache["dates"]

    def provider(trading_date: str, slot_time: str | None = None) -> tuple[dict[str, Any] | None, str]:
        if slot_time is None:
            doc = service.get_by_date(dataset_id, snapshot_type, trading_date)
            return (doc, "ok") if doc else (None, "missing")
        if trading_date not in slots_cache:
            slots_cache[trading_date] = service.list_slot_documents(dataset_id, snapshot_type, trading_date)
        eligible = [doc for doc in slots_cache[trading_date] if str(doc.get("slotTime") or "") <= slot_time]
        if eligible:
            return eligible[-1], "ok"
        prev = _previous_trading_date(trading_date)
        if prev and prev not in eod_cache:
            eod_cache[prev] = service.get_eod_document(dataset_id, snapshot_type, prev)
        doc = eod_cache.get(prev) if prev else None
        return (doc, "stale") if doc else (None, "missing")

    def _previous_trading_date(trading_date: str) -> str | None:
        dates = [date for date in _trading_dates() if date < trading_date]
        return dates[-1] if dates else None

    return provider
```

`services/theme/hotlist_sentiment_service.py` 模块内新增辅助（provider 闭包的 `_trading_dates` 调用它做 distinct 查询）：

```python
def _query_trading_dates(service: HotListSentimentService, dataset_id: str, snapshot_type: str) -> list[str]:
    """snapshot_frames 的 distinct tradingDate（与 BackfillService._trading_dates 同口径，避免跨层实例化）。"""
    return sorted({
        str(row.get("tradingDate") or "")
        for row in service._db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type}, {"tradingDate": 1}
        )
        if row.get("tradingDate")
    })
```

（`service._db` 由 Task 1 的 `__init__` 保存；同模块内访问可接受。若 Fake db 无 `snapshot_frames`，测试 `_seed` 已预置。）

- [ ] **Step 4: 改 `_ensure_hotlist_sentiment` 逐帧注入**

`runtime.py` L958-984 整段替换：

```python
    def _ensure_hotlist_sentiment(self, frames: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        missing_frames = [frame for frame in frames if "hotlistSentiment" not in frame]
        if not missing_frames:
            return

        provider = self._sentiment_provider
        if provider is None:
            # 未注入 provider 时跳过补全（不报错、不写字段）
            return
        try:
            # as-of 时点注入（WP1c）：逐帧按 (tradingDate, slotTime) 取 ≤ 帧时点的最新情绪，
            # 同日不同帧可注入不同文档；无当日文档回退前日 EOD（stale），不再按日共享同一 doc。
            for frame in missing_frames:
                trading_date = str(frame.get("tradingDate") or "")
                slot_time = str(frame.get("slotTime") or "") or None
                if not trading_date:
                    frame["hotlistSentiment"] = None
                    frame["hotlistSentimentStatus"] = "missing"
                    continue
                doc, status = provider(trading_date, slot_time)
                frame["hotlistSentiment"] = doc
                frame["hotlistSentimentStatus"] = status if doc else "missing"
        except Exception as exc:
            reason = f"MongoDB hotlist sentiment unavailable: {exc}"
            for frame in missing_frames:
                frame["hotlistSentiment"] = None
                frame["hotlistSentimentStatus"] = "missing"
                frame["hotlistSentimentReason"] = reason
```

- [ ] **Step 5: 新增 engine 注入回归测试**

追加到 `tests/test_hotlist_sentiment_asof_provider.py`：

```python
def test_engine_injects_per_frame_docs(monkeypatch):
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    fake_db = FakeMongoDb()  # 同上
    _seed(fake_db)
    monkeypatch.setattr(
        "backend.services.theme.hotlist_sentiment_service.get_hotlist_sentiment_service",
        lambda database=None: __import__(
            "backend.services.theme.hotlist_sentiment_service", fromlist=["HotListSentimentService"]
        ).HotListSentimentService(fake_db),
    )
    engine = RankTrendPythonEngine.__new__(RankTrendPythonEngine)  # 只测 _ensure_hotlist_sentiment
    engine._sentiment_provider = make_hotlist_sentiment_provider("d1", "half_hour")

    def frame(date: str, slot: str) -> dict:
        return {"tradingDate": date, "slotTime": slot}

    frames = [frame("2026-06-05", "10:30"), frame("2026-06-05", "11:30"), frame("2026-06-05", "09:30")]
    engine._ensure_hotlist_sentiment(frames, {})
    assert frames[0]["hotlistSentiment"]["stage"] == "启动" and frames[0]["hotlistSentimentStatus"] == "ok"
    assert frames[1]["hotlistSentiment"]["stage"] == "发酵" and frames[1]["hotlistSentimentStatus"] == "ok"
    assert frames[2]["hotlistSentiment"]["stage"] == "退潮" and frames[2]["hotlistSentimentStatus"] == "stale"


def test_engine_provider_exception_marks_missing():
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    engine = RankTrendPythonEngine.__new__(RankTrendPythonEngine)

    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    engine._sentiment_provider = boom
    frames = [{"tradingDate": "2026-06-05", "slotTime": "10:30"}]
    engine._ensure_hotlist_sentiment(frames, {})
    assert frames[0]["hotlistSentiment"] is None
    assert frames[0]["hotlistSentimentStatus"] == "missing"
    assert "db down" in frames[0]["hotlistSentimentReason"]
```

- [ ] **Step 6: 全量相关回归**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_asof_provider.py tests/test_hotlist_sentiment_slot_store.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_asof_provider.py tests/test_hotlist_sentiment_slot_store.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py -v`
Expected: 全部 PASS。另跑 golden 对齐确认注入改动无回归：`cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_golden_alignment.py -v`（若该测试不依赖 sentiment_provider 则天然绿）。

- [ ] **Step 7: 提交**

```bash
git add quant-board/backend/services/theme/hotlist_sentiment_service.py quant-board/backend/analysis/ranktrend/engine/runtime.py quant-board/tests/test_hotlist_sentiment_asof_provider.py
git commit -m "fix(sentiment): 情绪注入时点化消 lookahead（as-of provider + 逐帧注入 + stale 标注）"
```

---

### Task 4: market_regime stale reasons 透传

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend/trend/risk.py`（`market_regime` 内）
- Test: `quant-board/tests/test_market_regime_stale.py`（新建）

**Interfaces:**
- Produces: `frame["hotlistSentimentStatus"] == "stale"` 时 `market_regime` 输出 `reasons` 追加一条标注；**打分不变**。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.trend.risk import market_regime


def _frame(status: str | None) -> dict:
    # stocks 非空：market_regime 内部按 stocks 计算宽度/中位数，空表会触发与被测逻辑无关的退化分支
    frame: dict = {"stocks": [{"code": "000001", "rank": 1, "change": 5.0}], "hotlistSentiment": None}
    if status:
        frame["hotlistSentimentStatus"] = status
    return frame


def test_stale_appends_reason_without_score_change():
    base = market_regime(_frame(None))
    stale = market_regime(_frame("stale"))
    assert base["score"] == stale["score"]
    assert base["state"] == stale["state"]
    assert any("stale" in str(reason) for reason in stale["reasons"])
    assert not any("stale" in str(reason) for reason in base["reasons"])


def test_ok_and_missing_do_not_add_reason():
    for status in ("ok", "missing", None):
        reasons = market_regime(_frame(status))["reasons"]
        assert not any("stale" in str(reason) for reason in reasons)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_market_regime_stale.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_market_regime_stale.py -v`

- [ ] **Step 3: 实现（risk.py market_regime 内，reasons 组装处追加）**

```python
    # WP1c：stale 情绪回退标注（fail-visible，不改打分——分数构成见上）
    if str(frame.get("hotlistSentimentStatus") or "") == "stale":
        reasons.append("热榜情绪为前日 stale 口径（as-of 回退）")
```

（`reasons` 列表已在函数内存在；追加位置在 state 判定前、所有打分项之后，保证顺序稳定不影响 golden。）

- [ ] **Step 4: 回归 + 提交**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_market_regime_stale.py tests/test_hotlist_sentiment_asof_provider.py -v`
Expected: PASS。

```bash
git add quant-board/backend/analysis/ranktrend/trend/risk.py quant-board/tests/test_market_regime_stale.py
git commit -m "feat(sentiment): market_regime 对 stale 情绪回退加 reasons 标注（不改打分）"
```

---

### Task 5: backfill 按帧遍历模式

**Files:**
- Modify: `quant-board/backend/operations/hotlist_sentiment.py`（`HotListSentimentBackfillService` 增槽位遍历）
- Test: `quant-board/tests/test_hotlist_sentiment_backfill_slots.py`（新建）

**Interfaces:**
- Produces:
  - `HotListSentimentBackfillService.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time) -> dict | None`：当日 `slotTime == slot_time` 的帧（相同 slotTime 多帧取 timestamp 最新）。
  - `HotListSentimentBackfillService.run_for_date_slots(*, dataset_id, snapshot_type, trading_date, dry_run=False) -> dict`：遍历当日全部槽位帧，逐槽 `build_hotlist_sentiment_document(..., slot_time=槽)` + `self._sentiment.replace_one({"_id": doc["_id"]}, doc, upsert=True)`（**按 _id 写库**，与 Task 1 契约一致——业务四键 query 会在存量行 slotTime 为旧值时命中 `_id` 不同的行导致拒绝改 `_id`）；全部槽位完成后**收尾补写当日 EOD 终值**（调既有 `run_for_date`，stale 回退链路依赖每日 EOD 存在）；单槽取数/计算失败记 `slotErrors` 继续（无质量阻断）。
  - 同批修改：既有 `run_for_date`（EOD 模式）写库 query 同步改按 `_id`（`replace_one({"_id": doc["_id"]}, doc, upsert=True)`）——存量行兼容性与 Task 1 `upsert` 同理。
  - `backfill(..., mode: str = "eod")`：`mode="slots"` 时逐日调 `run_for_date_slots`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.operations.hotlist_sentiment import HotListSentimentBackfillService


def _seed_two_slots(fake_db) -> None:
    frames = fake_db["snapshot_frames"]
    rows = fake_db["snapshot_stock_rows"]
    for slot in ("10:00", "11:00"):
        frames.rows.append({"datasetId": "d1", "type": "half_hour", "tradingDate": "2026-06-05",
                            "snapshotId": f"snap-{slot}", "slotTime": slot, "timestamp": 1})
        rows.rows.append({"datasetId": "d1", "snapshotId": f"snap-{slot}", "code": "000001",
                          "name": "甲", "compRank": 1, "change": 5.0, "turnover": 8e8,
                          "zlje": 1e8, "zljzb": 12, "cddje": 5000e4, "cddjzb": 5,
                          "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1})


def test_run_for_date_slots_writes_one_doc_per_slot_plus_eod():
    fake_db = FakeMongoDb()  # 就地复制 Fake 四类
    _seed_two_slots(fake_db)
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05")
    assert result["ok"] is True and result["written"] == 2
    docs = fake_db["hotlist_sentiment"].rows
    assert sorted(doc["slotTime"] for doc in docs) == ["10:00", "11:00", "EOD"]  # 收尾补写当日 EOD
    assert all(doc["_id"].endswith(doc["slotTime"]) for doc in docs if doc["slotTime"] != "EOD")
    assert all(doc["stage"] in ("冰点", "启动", "发酵", "高潮", "退潮") for doc in docs)


def test_run_for_date_slots_dry_run_writes_nothing():
    fake_db = FakeMongoDb()  # 同上
    _seed_two_slots(fake_db)
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05", dry_run=True)
    assert result["written"] == 0 and not fake_db["hotlist_sentiment"].rows


def test_run_for_date_slots_continues_on_empty_slot():
    fake_db = FakeMongoDb()  # 同上
    _seed_two_slots(fake_db)
    fake_db["snapshot_stock_rows"].rows = [
        row for row in fake_db["snapshot_stock_rows"].rows if row["snapshotId"] != "snap-10:00"
    ]
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05")
    assert result["written"] == 1
    assert len(result["slotErrors"]) == 1 and result["slotErrors"][0]["slotTime"] == "10:00"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_backfill_slots.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_backfill_slots.py -v`

- [ ] **Step 3: 实现**

`operations/hotlist_sentiment.py` `HotListSentimentBackfillService` 内追加（WP1a 公开方法 `stocks_for_frame` 之后）：

```python
    def frame_for_slot(self, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str) -> dict[str, Any] | None:
        return self._frames.find_one(
            {
                "datasetId": dataset_id,
                "type": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": slot_time,
            },
            sort=[("timestamp", -1), ("snapshotId", -1)],
        )

    def _slot_times_of_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> list[str]:
        return sorted({
            str(row.get("slotTime") or "")
            for row in self._frames.find(
                {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
                {"slotTime": 1},
            )
            if row.get("slotTime")
        })

    def run_for_date_slots(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """按帧遍历：当日全部槽位逐槽计算情绪并 upsert 槽位文档（WP1b 历史回填模式）。

        单槽失败记 slotErrors 继续（无质量阻断）；前一交易日取数与 EOD 模式同口径。
        全部槽位完成后收尾补写当日 EOD 终值（stale 回退链路依赖每日 EOD 存在）。
        """
        previous = self.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        written = 0
        slot_errors: list[dict[str, Any]] = []
        for slot_time in self._slot_times_of_date(dataset_id, snapshot_type, trading_date):
            try:
                frame = self.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time)
                stocks = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
                if not frame or not stocks:
                    slot_errors.append({"slotTime": slot_time, "reason": "no_frame" if not frame else "empty_stock_rows"})
                    continue
                doc = build_hotlist_sentiment_document(
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    frame=frame,
                    stocks=stocks,
                    yesterday_stocks=previous.get("yesterday") or [],
                    day_before_stocks=previous.get("day_before") or [],
                    slot_time=slot_time,
                )
                if not dry_run:
                    self._sentiment.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                written += 0 if dry_run else 1
            except Exception as exc:  # 无质量阻断：单槽失败不中断整日回填
                slot_errors.append({"slotTime": slot_time, "reason": f"error: {exc}"})
        eod_written = False
        if not dry_run:
            # 收尾补写当日 EOD 终值（槽位文档不含 EOD；as-of stale 回退与既有 EOD 消费方依赖它）
            eod_result = self.run_for_date(dataset_id=dataset_id, snapshot_type=snapshot_type, trading_date=trading_date)
            eod_written = bool(eod_result.get("written"))
        return {
            "ok": True,
            "dryRun": dry_run,
            "mode": "slots",
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "written": written,
            "eodWritten": eod_written,
            "slotErrors": slot_errors,
        }
```

（`run_for_date` 的实际关键字签名以 WP1a 实施后的现文为准——执行时打开 `operations/hotlist_sentiment.py:84-138` 对齐参数名；上文按 `(dataset_id, snapshot_type, trading_date)` 关键字形式调用。）

`backfill(...)` 加 `mode: str = "eod"` 参数，循环内 `result = self.run_for_date_slots(...) if mode == "slots" else self.run_for_date_slots_eod(...)`（即原 `run_for_date` 改名或保持 `run_for_date` 并在分支里二选一调用；**保持 `run_for_date` 名称不变**，分支：`result = self.run_for_date_slots(...) if mode == "slots" else self.run_for_date(...)`），返回体加 `"mode": mode`。

- [ ] **Step 4: 测试通过 + 既有 backfill 回归**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_backfill_slots.py tests/test_hotlist_sentiment_backfill.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/operations/hotlist_sentiment.py quant-board/tests/test_hotlist_sentiment_backfill_slots.py
git commit -m "feat(sentiment): backfill 按帧遍历模式（逐槽落库 + 单槽失败不中断）"
```

---

### Task 6: collector 挂载（每槽落帧后同源计算）

**Files:**
- Modify: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`（新增模块级入口）
- Modify: `quant-board/backend/snapshot_collector/service.py`（`_persist_one` 挂载 L532-539 后）
- Test: `quant-board/tests/test_hotlist_sentiment_collector_hook.py`（新建）

**Interfaces:**
- Consumes: Task 5 的 `run_for_date_slots` 取数逻辑（此处复用其单槽路径）、`build_hotlist_sentiment_document`。
- Produces:
  - `compute_and_upsert_for_slot(mongo_db, *, dataset_id, snapshot_type, trading_date, slot_time) -> dict`：从库取该槽帧 + rows + 前两日 rows → join displayStatus + limitSummary（复用 WP1a compute service 的 `_join_display_status`/`_build_market_data_like`）→ 纯函数 → 槽位文档 upsert。返回 `{"written": bool, "reason": str | None}`；**任何异常由调用方兜住，不阻断帧采集**。
  - `_persist_one` 挂载：`run_status == "completed"` 时调用，异常 `logging.warning`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.services.theme.hotlist_sentiment_compute import compute_and_upsert_for_slot


def _seed_slot(fake_db) -> None:
    fake_db["snapshot_frames"].rows.append({
        "datasetId": "d1", "type": "half_hour", "tradingDate": "2026-06-05",
        "snapshotId": "snap-1030", "slotTime": "10:30", "timestamp": 5,
        "limitSummary": {"continuousBoards": {"yiban": 3, "erban": 1}, "zhaban": {}, "yesterdayZt": {}, "thsPools": {}},
    })
    fake_db["snapshot_stock_rows"].rows.append({
        "datasetId": "d1", "snapshotId": "snap-1030", "code": "000001", "name": "甲",
        "compRank": 1, "change": 5.0, "turnover": 8e8, "zlje": 1e8, "zljzb": 12,
        "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1,
    })


def test_compute_and_upsert_for_slot_persists_slot_doc():
    fake_db = FakeMongoDb()  # 就地复制 Fake 四类
    _seed_slot(fake_db)
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is True
    docs = fake_db["hotlist_sentiment"].rows
    assert len(docs) == 1
    assert docs[0]["_id"] == "d1:half_hour:2026-06-05:10:30"
    assert docs[0]["slotTime"] == "10:30"
    assert "stage" in docs[0] and "metrics" in docs[0]


def test_compute_and_upsert_for_slot_missing_frame_reports_reason():
    fake_db = FakeMongoDb()  # 同上
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is False and result["reason"]


def test_compute_and_upsert_for_slot_idempotent():
    fake_db = FakeMongoDb()  # 同上
    _seed_slot(fake_db)
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    assert len(fake_db["hotlist_sentiment"].rows) == 1  # replace_one 幂等
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_collector_hook.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_collector_hook.py -v`

- [ ] **Step 3: 实现 compute 入口**

`services/theme/hotlist_sentiment_compute.py` 模块级追加（复用文件内已有的 `_join_display_status`/`_build_market_data_like` 与 `HotListSentimentComputeService._compute_and_persist` 的组装模式）：

```python
def compute_and_upsert_for_slot(
    mongo_db: Any,
    *,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    slot_time: str,
) -> dict[str, Any]:
    """collector 每槽落帧后的情绪计算入口（WP1b）。

    与 series lazy compute 的差异：指定槽位帧（非当日最新帧）、产出槽位 _id 文档。
    全库取数（不信任内存对象，保证 save-后-计算的数据一致性）；缺失返回 reason 不抛异常
    ——调用方（collector）负责不阻断帧采集。
    """
    try:
        from backend.operations.hotlist_sentiment import HotListSentimentBackfillService, build_hotlist_sentiment_document

        backfill = HotListSentimentBackfillService(mongo_db)
        frame = backfill.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time)
        if not frame:
            return {"written": False, "reason": "no_snapshot_frame"}
        stocks = backfill.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
        if not stocks:
            return {"written": False, "reason": "empty_stock_rows"}
        previous = backfill.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        _join_display_status(backfill._db, dataset_id, str(frame.get("snapshotId") or ""), stocks)
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            market_data=_build_market_data_like(frame.get("limitSummary")),
            slot_time=slot_time,
        )
        HotListSentimentService(mongo_db).upsert(doc)
        return {"written": True, "reason": None}
    except Exception as exc:  # 无质量阻断：情绪失败不阻断帧采集
        return {"written": False, "reason": f"error: {exc}"}
```

（文件顶部 import 补 `HotListSentimentService`：`from backend.services.theme.hotlist_sentiment_service import HotListSentimentService`。）

- [ ] **Step 4: collector 挂载**

`snapshot_collector/service.py` `_persist_one` 在 cache_invalidate 块（L532-539）之后、`run_doc` 构造之前插入：

```python
        if run_status == "completed":
            # WP1b：每槽落帧后同源计算热榜情绪（失败不阻断采集——无质量阻断，AGENTS.md §10）
            try:
                from backend.services.theme.hotlist_sentiment_compute import compute_and_upsert_for_slot

                sentiment_result = compute_and_upsert_for_slot(
                    self._repo.db,  # MongoRepository 已暴露公开 db 句柄（mongo_repository.py L48-51，已核实）
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    slot_time=slot_time,
                )
                if not sentiment_result.get("written"):
                    quality.warnings.append(f"hotlist_sentiment_slot_skipped: {sentiment_result.get('reason')}")
            except Exception as exc:
                logging.warning("hotlist_sentiment slot compute failed for %s %s: %s", trading_date, slot_time, exc)
```

文件顶部确认有 `import logging`，没有则补。

- [ ] **Step 5: collector 既有测试回归**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_collector_hook.py tests/test_snapshot_collector_service.py -v`
Expected: 全部 PASS（挂载代码经 `self._repo.db` 取库——collector 既有测试的 fake repo 若缺 `db` 属性，给该 fake 补一个返回 `FakeMongoDb()` 的 `db` 属性即可；情绪计算失败也被 try/except 吞为 warning，不影响原断言）。

- [ ] **Step 6: 提交**

```bash
git add quant-board/backend/services/theme/hotlist_sentiment_compute.py quant-board/backend/snapshot_collector/service.py quant-board/tests/test_hotlist_sentiment_collector_hook.py
git commit -m "feat(sentiment): collector 每槽落帧后同源计算热榜情绪（失败不阻断采集）"
```

---

### Task 7: 文档同步 + L1 档案注记

**Files:**
- Modify: `quant-board/docs/database-migration-plan.md`（hotlist_sentiment 索引/_id/哨兵契约 + 迁移脚本 + **旧索引 drop 约束**）
- Modify: `quant-board/docs/architecture.md`（情绪链路时点化描述）
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`（组 5 加注）
- Read: `quant-board/docs/api-cli.md`（核对：无新 API，若 series 已在 WP1a 记录则无需改动）

- [ ] **Step 1: database-migration-plan.md 增节**

在 hotlist_sentiment 相关小节追加（或新建"槽位级情绪文档"节）：

```markdown
## hotlist_sentiment 槽位级文档（2026-09-06）

- 唯一索引 `(datasetId, snapshotType, tradingDate)` → `(datasetId, snapshotType, tradingDate, slotTime)`；
  **旧三元组唯一索引必须显式 drop**（迁移脚本顺带执行），否则同日第二槽 upsert 被旧索引拒绝。
- EOD 终值文档：`_id = {dataset}:{type}:{date}`，`slotTime = "EOD"` 哨兵；槽位文档 `_id` 追加 `:{slot}`。
- 读口契约：`get_by_date`/`upsert` 按 `_id` 精确命中（存量行与哨兵行同 `_id`）；`list_slot_documents`
  以 `_id $ne EOD` + `slotTime $ne "EOD"` 双条件排除 EOD。
- 存量迁移：`python -m backend.operations.migrate_hotlist_sentiment_slot_eod [--dry-run]`（幂等，
  实跑时顺带 drop 旧唯一索引；`--skip-index-drop` 可跳过）。
- 写入口：snapshot_collector 每槽落帧后 `compute_and_upsert_for_slot`；历史回填 `backfill(mode="slots")`
  （收尾自动补写当日 EOD）。
- 读口：as-of provider（当日 ≤slot 最新槽位 → 前日 EOD stale 回退 → missing）。
```

- [ ] **Step 2: architecture.md / L1 档案 / api-cli 核对**

- `architecture.md`：情绪链路描述更新为"槽位级落库 + as-of 时点查询（stale 回退）"。
- `quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md` 档案组 5 条目加注：`2026-09-06 WP1c 修复 regime 情绪注入 lookahead；组 5 参数结论待 9 月数据积累后按 §6 重验`。
- `api-cli.md`：核对 series 读口描述是否需补槽位语义（预计无 API 变化，仅核对）。

- [ ] **Step 3: 提交**

```bash
git add quant-board/docs/database-migration-plan.md quant-board/docs/architecture.md quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md
git commit -m "docs(sentiment): 槽位级文档契约与时点查询同步（迁移计划/架构/L1 档案注记）"
```

---

## 验证总清单

- `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_slot_store.py tests/test_hotlist_sentiment_slot_migration.py tests/test_hotlist_sentiment_asof_provider.py tests/test_market_regime_stale.py tests/test_hotlist_sentiment_backfill_slots.py tests/test_hotlist_sentiment_collector_hook.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py -v` 全绿。
- 生产库迁移脚本 `--dry-run` → 实跑 → 记录 updated 与 indexDrop 结果。
- 生产库 `db.hotlist_sentiment.getIndexes()` 人工验证：四键唯一索引存在、旧 `datasetId_1_snapshotType_1_tradingDate_1` 已不在（**部署硬约束，未 drop 前不得写第二个槽位**）。
- 首个采集日人工验证：MongoDB `hotlist_sentiment` 每交易日槽位文档数 ≤ 11（half_hour 槽位数），EOD 文档 slotTime == "EOD"。

## 风险与回退

- 回退 revert Task 3/4/6 即回日粒度注入；Task 1/2 的库契约向后兼容（`get_by_date`/`upsert` 按 `_id` 命中对存量行与哨兵行行为一致），槽位文档留存无害。
- 唯一改变部署顺序的点：旧唯一索引 drop 前不能写第二个槽位——迁移脚本实跑顺带完成，`--skip-index-drop` 仅供特殊回退场景。
- provider 闭包缓存以"单次回测/请求"为生命周期，跨请求不复用，无失效风险。
- 回填 `run_for_date_slots` 收尾自动补写当日 EOD：对已有 EOD 文档的日期是幂等覆盖（同 `_id` replace，值同源重算）；如需保留历史 EOD 原值不重算，先跑 `--dry-run` 评估。
