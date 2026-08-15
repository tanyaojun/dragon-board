# RankTrend 长期回测阶段 1：性能改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 计划来源：`quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md` 阶段 1（§2.1 方案 A + §2.2 方案 B 的进程内部分）。
> 状态：待执行（已提交归档，见 git log）。工作区基线：commit `227f31a`。

**Goal:** 让长期参数搜索跑得动——Mongo 股票行拉取瘦身（字段白名单投影 + 游标分批）+ 信号缓存键按参数分组改造（交易层参数变化复用已算信号），使 24 trials + walk-forward 优化任务从 1–4 小时降到 ≤ 20 分钟量级且不再反复压垮 MongoDB。

**Architecture:** 三层独立改动，全部在 QuantBoard 后端进程内完成，不动数据库 schema、不动 API 合同、不改引擎算法：
1. `load_frames` 支持股票行字段白名单投影（`fields` 参数），优化链路传超集白名单（引擎消费字段 + quality gate 依赖字段），Mongo 传输量从 83 字段降到约 45 字段；
2. `_stock_rows_by_snapshot` 按 snapshot_id 分批游标查询（每批 200 帧），降低单次查询峰值与 Mongo 传输压力（真正降低内存/传输量的是字段白名单投影，分批不减少总拉取量）；
3. `signal_cache` 键只保留信号层参数（`to_strategy_config` 过滤出的 `RankTrendConfig` 字段子集），交易层参数（`maxPositions/takeProfit/stopLoss/synergy*` 等）变化时复用已算信号，`strategyRunCount` 显著小于 trial 数。

**Tech Stack:** Python 3.13 / FastAPI / pymongo（MongoRepository 主链）/ pytest（`quant-board/.venv`）。不改：Redis 跨运行缓存（后续子里程碑）、ProcessPoolExecutor 多进程（方案 C，后续）、walk-forward 结构、引擎算法。

---

## 0. 执行者必读的现状事实（已核实，勿凭印象改动）

- **`backend/data/repositories/mongo_repository.py:300-326` `load_frames`**：签名 `(dataset_id, snapshot_type, start_date, end_date, include_payload=True)`，`include_payload` 参数在函数体内**未使用**（历史遗留）；固定调 `_stock_rows_by_snapshot(..., projection="full")` 全字段拉取。帧本身用 `_find_frames`（支持日期/limit/sort），股票行是瓶颈（1.65GB / 57.3 万行）。
- **`mongo_repository.py:881-950` `_stock_rows_by_snapshot`**：已有三种模式——`fields`（mongo 层投影 + 保留 null + 剥离 `_id/snapshotId`）、`projection in ("ranktrend","ranktrend+themes")`（固定 9 字段手拼）、else（`depth10:0` 排除全量）。查询是 `db["snapshot_stock_rows"].find({datasetId, snapshotId: {$in: snapshot_ids}}, projection).sort(rank)` **一次性全拉，无分批**。
- **`backend/services/optimization_service.py:261-328` `_build_request`**：`load_frames(dataset_id, snapshot_type=..., start_date=load_start, end_date=load_end, include_payload=True)`（:293）——优化链路的唯一数据入口，当前不传投影。
- **`backend/optimization/trial.py:145-152`**：`signal_key = freeze({"phase", "first", "last", "strategy": strategy_config})`。`strategy_config = {**base_strategy_config, **to_strategy_config(params)}`；`base_strategy_config` 来自请求 `backtest.strategy_config` 合并 `DEFAULT_BACKTEST_STRATEGY_CONFIG`（`backend/services/shared.py:11`，只含 4 个信号层字段），**用户可把交易层参数塞进 `backtest.strategy_config` 从而污染缓存键**。
- **`backend/optimization/search_space.py`**：`to_strategy_config(params)`（:273-278）只挑 `_STRATEGY_PARAM_KEYS`（`RankTrendConfig` 的标量 + 列表字段白名单）→ 天然是"信号层过滤函数"，可复用；`to_trade_config` 透传交易层参数。`freeze`（:281-286）稳定序列化。
- **`backend/analysis/ranktrend/engine.py` `RankTrendConfig.from_patch`**：只处理 `hasattr(base, key)` 的键，**未知键静默忽略** → 用 `to_strategy_config` 过滤键不会改变 replay 行为。
- **quality gate**：`_prepare_frames_for_backtest`（`backend/services/shared.py:136`）→ `_stock_rows_for_quality`（:72，只读 `rowId/row_id/code/MONEY_FLOW_QUALITY_FIELDS`）→ `evaluate_snapshot_quality`（`backend/data/ingest/quality_gate.py:193`）。FATAL 项（shared.py:42）为 `invalidCaptureMode/duplicateSnapshotId/nonMonotonicTimestamp/missingCoreFieldCount`——**与股票行字段裁剪无关**；白名单必须覆盖 `rowId/row_id/MONEY_FLOW_QUALITY_FIELDS` 以保持 gate 语义不变。
- **`backend/optimization/runner.py:62,138`**：`signal_cache` 是进程内 dict，结果里输出 `strategyRunCount = len(signal_cache)`（可用作验收指标）；walk-forward（runner.py:106-115）复用同一 `signal_cache`。
- **测试基础**：`quant-board/tests/test_mongo_repository.py` 内有 `FakeMongoDatabase/FakeCollection/FakeCursor`（`find` 支持 query+projection，cursor 支持 `sort/limit`，`_matches` 支持 `$in`——`test_stock_rows_by_snapshot_ranktrend_projection_keeps_snapshot_id` 已在用）；全量 `quant-board/tests/` 当前 1506 passed。
- **引擎股票行消费字段（grep 实证，`backend/analysis/ranktrend/**` 的 `stock.get(...)`/`row.get(...)`）**：`code/name/rank/avgRankNum/change/volumeRatio/zlje/zljzb/price/volume/turnover/turnoverRate/dtPrice/high/low/fengdan/lastTradePrice/lastTradeVolume/limitUpPrice/limitDownPrice/ztPrice/highPrice/lowPrice/status/leadStatus/themes/mainTheme/themeRole/themeContribution/themeHeat/themeRiskFlags/label/annotator/evidence`。
- 默认存储后端：`settings.storage_backend`；优化链路 `create_repository` 返回 `MongoResearchRepository`（mongodb）或 `Repository`（sqlite）。**阶段 1 只裁剪 Mongo 主链**；sqlite 版 `snapshot_repository.py:244 load_frames` 同步加同名参数保持签名一致（不裁剪，docstring 注明）。

**验收标准（来自 longterm 计划 §阶段 1 + 可自动断言的部分）：**

- [ ] 全量 `quant-board/tests/` pytest 通过（当前基线 1506 passed，不得减少）。
- [ ] 新增测试全绿：投影裁剪、分批完整性、signal_key 分组语义。
- [ ] golden 对齐不回归：`tests/test_ranktrend_golden_alignment.py` 通过（投影后引擎输出与 full 一致）。
- [ ] 手动验收（需真实 Mongo）：同一次优化（24 trials + walk-forward）`strategyRunCount` 显著 < `trialCount`（交易层参数变化不再重算信号），耗时 ≤ 20 分钟，Mongo 日志无全量拉取。

**范围外（本计划不做，后续里程碑）：** Redis 跨运行帧/信号缓存（文档 §2.2 后半）、ProcessPoolExecutor 多进程（§2.3 方案 C）、walk-forward 结构改动、数据质量治理（阶段 2）、信号区分度（阶段 3）、参数搜索（阶段 4）。

---

## Task 1: 字段白名单常量 + `load_frames` 投影支持（mongo 版）

**Files:**
- Modify: `quant-board/backend/services/shared.py`（MONEY_FLOW_QUALITY_FIELDS 之后加常量）
- Modify: `quant-board/backend/data/repositories/mongo_repository.py:300-326`（`load_frames` 加 `fields` 参数）
- Test: `quant-board/tests/test_mongo_repository.py`（追加两个测试）

- [ ] **Step 1: 写失败测试**

在 `quant-board/tests/test_mongo_repository.py` 文件末尾追加（复用文件内已有的 `FakeMongoDatabase`/`MongoRepository` import；`FakeCollection.find` 已支持 projection 裁剪）：

```python
def test_load_frames_field_whitelist_projection() -> None:
    database = FakeMongoDatabase()
    database["snapshot_frames"].rows = [
        {
            "datasetId": "dragonboard_live", "snapshotId": "s1", "type": "half_hour",
            "timestamp": 1, "tradingDate": "2026-08-01", "slotTime": "10:00",
            "captureMode": "real_time", "source": "test",
        },
    ]
    database["snapshot_stock_rows"].rows = [
        {
            "datasetId": "dragonboard_live", "snapshotId": "s1", "code": "000001",
            "name": "平安银行", "rank": 1, "change": 1.2, "volumeRatio": 1.5,
            "zlje": 100.0, "zljzb": 5.0, "themes": ["银行"], "platforms": ["同花顺"],
            "timestamp": 1,
        },
    ]
    repo = MongoRepository(database)

    frames = repo.load_frames(
        "dragonboard_live",
        fields=["code", "change", "volumeRatio", "zlje", "zljzb", "themes"],
    )

    stocks = frames[0]["stocks"]
    assert stocks[0]["code"] == "000001"
    assert stocks[0]["change"] == 1.2
    assert stocks[0]["themes"] == ["银行"]
    # 大字段与大字段之外的字段被裁剪
    assert "platforms" not in stocks[0]
    assert "name" not in stocks[0]


def test_load_frames_without_fields_keeps_full_rows() -> None:
    database = FakeMongoDatabase()
    database["snapshot_frames"].rows = [
        {
            "datasetId": "dragonboard_live", "snapshotId": "s1", "type": "half_hour",
            "timestamp": 1, "tradingDate": "2026-08-01", "slotTime": "10:00",
            "captureMode": "real_time", "source": "test",
        },
    ]
    database["snapshot_stock_rows"].rows = [
        {
            "datasetId": "dragonboard_live", "snapshotId": "s1", "code": "000001",
            "name": "平安银行", "rank": 1, "platforms": ["同花顺"],
        },
    ]
    repo = MongoRepository(database)

    frames = repo.load_frames("dragonboard_live")

    assert frames[0]["stocks"][0]["platforms"] == ["同花顺"]
    assert frames[0]["stocks"][0]["name"] == "平安银行"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_repository.py -k "field_whitelist or without_fields" -q
```

Expected: `TypeError: load_frames() got an unexpected keyword argument 'fields'`（第一个测试 FAIL，第二个测试此时 PASS——仅裁剪行为未实现）。

- [ ] **Step 3: 实现**

`quant-board/backend/services/shared.py`，在 `MONEY_FLOW_QUALITY_FIELDS` 定义之后追加：

```python
# 优化/回测链路的股票行字段白名单（阶段 1：load_frames 投影裁剪）。
# 依据：backend/analysis/ranktrend/** 引擎消费字段（grep 实证）+ quality gate 依赖
# （_stock_rows_for_quality 读 rowId/row_id/MONEY_FLOW_QUALITY_FIELDS）+ 行级排序/诊断。
# 超集原则：宁多勿缺，防止投影遗漏导致引擎静默降级（fail-visible，禁止裁剪必需字段）。
BACKTEST_RANKTREND_STOCK_FIELDS = (
    # 引擎 replay/_build_signal 消费
    "code", "name", "rank", "avgRankNum",
    "change", "volumeRatio", "zlje", "zljzb",
    "price", "volume", "turnover", "turnoverRate",
    "dtPrice", "high", "low", "fengdan",
    "lastTradePrice", "lastTradeVolume",
    "limitUpPrice", "limitDownPrice", "ztPrice",
    "highPrice", "lowPrice", "status", "leadStatus",
    "themes", "mainTheme", "themeRole", "themeContribution",
    "themeHeat", "themeRiskFlags", "label", "annotator", "evidence",
    # quality gate / 分组排序
    "rowId", "row_id", "timestamp",
    *MONEY_FLOW_QUALITY_FIELDS,
)
```

`quant-board/backend/data/repositories/mongo_repository.py:300-326`，`load_frames` 签名加 `fields` 参数并透传：

```python
    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按帧+股票行加载快照。fields 非 None 时股票行走字段白名单投影
        （_stock_rows_by_snapshot fields 分支：mongo 层裁剪 + 保留 null + 剥离 _id/snapshotId），
        fields=None 保持原 full 投影行为。include_payload 为历史兼容参数（本实现不裁剪帧字段）。"""
        frame_rows = self._find_frames(
            dataset_id,
            snapshot_type,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=None,
            allowed_capture_modes=None,
            exclude_restored=False,
            limit=None,
            sort="asc",
        )
        snapshot_ids = [str(row.get("snapshotId")) for row in frame_rows if row.get("snapshotId")]
        stock_rows_by_snapshot = self._stock_rows_by_snapshot(
            dataset_id, snapshot_ids, projection="full", fields=fields
        )
        frames: list[dict[str, Any]] = []
        for row in frame_rows:
            item = self.frame_to_dict(row)
            item["stocks"] = stock_rows_by_snapshot.get(str(row.get("snapshotId")), [])
            frames.append(item)
        return frames
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_repository.py -k "field_whitelist or without_fields" -q
```

Expected: `2 passed`。

- [ ] **Step 5: 提交**

```powershell
git add quant-board/backend/services/shared.py quant-board/backend/data/repositories/mongo_repository.py quant-board/tests/test_mongo_repository.py
git commit -m "perf(ranktrend): load_frames 支持股票行字段白名单投影（阶段 1 方案 A）"
```

---

## Task 2: 优化链路传入字段白名单

**Files:**
- Modify: `quant-board/backend/services/optimization_service.py:293-299`（`_build_request` 传 `fields`）
- Test: `quant-board/tests/test_optimization_service.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `quant-board/tests/test_optimization_service.py`：

```python
# -*- coding: utf-8 -*-
"""OptimizationService._build_request 链路测试（阶段 1：字段白名单投影下传）。"""
from __future__ import annotations

from typing import Any

from backend.services.optimization_service import OptimizationService
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS


class _StubRepo:
    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = frames
        self.last_fields: list[str] | None = None

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_fields = fields
        return self.frames


def _minimal_frames() -> list[dict[str, Any]]:
    # 两帧且每帧至少一行，能通过 _prepare_frames_for_backtest 的 quality gate（min_snapshot_count=2）
    return [
        {
            "snapshotId": "s1", "type": "half_hour", "timestamp": 1,
            "tradingDate": "2026-08-01", "slotTime": "10:00",
            "captureMode": "real_time", "source": "test",
            "stocks": [{"snapshotId": "s1", "code": "000001", "capitalFlowSource": "ths"}],
        },
        {
            "snapshotId": "s2", "type": "half_hour", "timestamp": 2,
            "tradingDate": "2026-08-01", "slotTime": "10:30",
            "captureMode": "real_time", "source": "test",
            "stocks": [{"snapshotId": "s2", "code": "000002", "capitalFlowSource": "ths"}],
        },
    ]


def test_build_request_passes_field_whitelist_to_load_frames() -> None:
    stub = _StubRepo(_minimal_frames())
    # __new__ 绕过 __init__（避免 create_repository 连接真实 Mongo）；
    # 前提：_build_request 只访问 self.repo（当前实现 :293 唯一 self 访问点，落地时如增加 self 依赖需同步调整）
    service = OptimizationService.__new__(OptimizationService)
    service.repo = stub

    payload = {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "method": "random",
        "max_trials": 4,
        "random_seed": 20260430,
    }
    dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = service._build_request(payload)

    assert dataset_id == "dragonboard_live"
    assert len(run_frames) == 2
    assert stub.last_fields == list(BACKTEST_RANKTREND_STOCK_FIELDS)
    assert "fields" not in request  # 投影字段只用于数据加载，不进优化请求体（payload_for_request_json 亦不含）
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_optimization_service.py -q
```

Expected: `FAILED ... assert stub.last_fields is None`（当前 `_build_request` 不传 `fields`）。

- [ ] **Step 3: 实现**

`quant-board/backend/services/optimization_service.py`，在文件顶部 import 白名单常量（现有 import 区，`from backend.services.shared import (...)` 内追加）：

```python
from backend.services.shared import (
    DEFAULT_BACKTEST_STRATEGY_CONFIG,
    BACKTEST_RANKTREND_STOCK_FIELDS,
    camel_get,
    _prepare_frames_for_backtest
)
```

将 `:293-299` 的 `load_frames` 调用改为：

```python
        frames = self.repo.load_frames(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=load_start,
            end_date=load_end,
            include_payload=True,
            fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
        )
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_optimization_service.py -q
```

Expected: `1 passed`。

- [ ] **Step 5: 提交**

```powershell
git add quant-board/backend/services/optimization_service.py quant-board/tests/test_optimization_service.py
git commit -m "perf(ranktrend): 优化链路 load_frames 传入股票行字段白名单（阶段 1 方案 A）"
```

---

## Task 3: `_stock_rows_by_snapshot` 游标分批

**Files:**
- Modify: `quant-board/backend/data/repositories/mongo_repository.py:881-950`（分批）
- Test: `quant-board/tests/test_mongo_repository.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `quant-board/tests/test_mongo_repository.py` 文件末尾追加：

```python
def test_stock_rows_by_snapshot_batches_snapshot_ids(monkeypatch) -> None:
    import backend.data.repositories.mongo_repository as mongo_repo

    database = FakeMongoDatabase()
    collection = database["snapshot_stock_rows"]
    collection.rows = [
        {
            "datasetId": "dragonboard_live", "snapshotId": f"s{i}", "code": f"00000{i % 10}",
            "rank": i, "change": float(i),
        }
        for i in range(1, 31)
    ]
    repo = MongoRepository(database)
    monkeypatch.setattr(mongo_repo, "_STOCK_ROWS_BATCH_SIZE", 10)

    rows_by_snapshot = repo._stock_rows_by_snapshot(
        "dragonboard_live", [f"s{i}" for i in range(1, 31)], projection="full"
    )

    assert len(rows_by_snapshot) == 30
    assert [r["rank"] for r in rows_by_snapshot["s1"]] == [1]
    assert [r["code"] for r in rows_by_snapshot["s15"]] == ["000005"]
    # 30 个 snapshotId、批大小 10 → 恰好 3 次查询
    assert len(collection.find_queries) == 3
    for query in collection.find_queries:
        assert query["snapshotId"]["$in"]  # 分批仍走 $in（保持 sort(rank) 语义）
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_repository.py -k "batches_snapshot_ids" -q
```

Expected: `FAILED ... assert len(collection.find_queries) == 3`（当前一次 find，`find_queries` 长度为 1）。

- [ ] **Step 3: 实现**

`quant-board/backend/data/repositories/mongo_repository.py`，在文件顶部常量区（`_find_frames` 之前）加批大小常量；把 `_stock_rows_by_snapshot` 的查询改为分批循环：

```python
# 股票行分批游标大小（阶段 1）：按 snapshot_id 分批，避免 57 万行一次 $in 全拉进内存。
# 每批 200 帧 ≈ 4-5 万行，兼顾查询次数与单批内存。测试用 monkeypatch 覆盖此值验证分批逻辑。
_STOCK_ROWS_BATCH_SIZE = 200
```

```python
    def _stock_rows_by_snapshot(
        self,
        dataset_id: str,
        snapshot_ids: list[str],
        *,
        projection: str,
        fields: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not snapshot_ids:
            return rows_by_snapshot
        if fields is not None:
            # 行字段白名单投影（frames fields 参数）：snapshotId 必须保留（分组 key），
            # 其余只取请求字段，避免 full 投影整行 107 字段全量传输（3 帧可达 27MB）；
            # 用 is not None 判定（而非 if fields:）：fields=[] 也应走白名单分支，
            # 得到只剩 snapshotId 分组键的行，而不是落入 else 的 full 投影（审计修订）
            mongo_projection: dict[str, int] = {
                "_id": 0,
                "snapshotId": 1,
                **{field: 1 for field in fields},
            }
        elif projection in ("ranktrend", "ranktrend+themes"):
            # snapshotId 必须保留（分组 key）；regime 五因子需要 change/volumeRatio/zlje/zljzb；
            # avgRankNum 是旧 TS 横截面（市场关注度百分位中位数）的原料，必须随行输出
            mongo_projection: dict[str, int] = {
                "_id": 0,
                "snapshotId": 1,
                "code": 1,
                "name": 1,
                "rank": 1,
                "avgRankNum": 1,
                "change": 1,
                "volumeRatio": 1,
                "zlje": 1,
                "zljzb": 1,
            }
            if projection == "ranktrend+themes":
                mongo_projection.update({
                    "themes": 1,
                    "mainTheme": 1,
                    "themeRole": 1,
                    "themeContribution": 1,
                    "leadStatus": 1,
                })
        else:
            mongo_projection = {"depth10": 0}
        # 游标分批：按 snapshot_id 切批查询，组内保持 rank 排序（每批 find 自带 sort），
        # 合并到同一分组 dict，语义与一次全拉等价（分组键/排序/字段均不变）。
        batch_size = _STOCK_ROWS_BATCH_SIZE
        for start in range(0, len(snapshot_ids), batch_size):
            batch_ids = snapshot_ids[start : start + batch_size]
            for row in self.db["snapshot_stock_rows"].find(
                {"datasetId": dataset_id, "snapshotId": {"$in": batch_ids}},
                mongo_projection,
            ).sort([("rank", 1)]):
                if fields is not None:
                    # 字段白名单分支：保留请求字段（含 null 值，供引擎 .get() 消费），只剥离内部分组字段；
                    # 注：full 分支经 local_stock_to_bundle_dict 会剥离 null——两分支 null 语义不同，属现状，
                    # 勿在本阶段"统一"以免改变既有行为（未涨停行缺失 maxFengdan/firstZtTime 等字段会静默降级）。
                    # fields=[] 时 mongo_projection 只剩 snapshotId 分组键（空列表 = 不投影任何业务字段）。
                    item = {
                        key: value
                        for key, value in row.items()
                        if key not in ("_id", "snapshotId")
                    }
                elif projection in ("ranktrend", "ranktrend+themes"):
                    item = {
                        "code": row.get("code"),
                        "name": row.get("name"),
                        "rank": row.get("rank"),
                        "avgRankNum": row.get("avgRankNum"),
                        "change": row.get("change"),
                        "volumeRatio": row.get("volumeRatio"),
                        "zlje": row.get("zlje"),
                        "zljzb": row.get("zljzb"),
                    }
                    if projection == "ranktrend+themes":
                        item.update({
                            "themes": row.get("themes") or [],
                            "mainTheme": row.get("mainTheme") or "",
                            "themeRole": row.get("themeRole") or "",
                            "themeContribution": row.get("themeContribution"),
                            "leadStatus": row.get("leadStatus") or "",
                        })
                else:
                    item = self.local_stock_to_bundle_dict(row)
                rows_by_snapshot[str(row.get("snapshotId"))].append(item)
        return rows_by_snapshot
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_repository.py -q
```

Expected: 全部 PASS（含原有投影测试，确认分批未改变分组/排序语义）。

- [ ] **Step 5: 提交**

```powershell
git add quant-board/backend/data/repositories/mongo_repository.py quant-board/tests/test_mongo_repository.py
git commit -m "perf(ranktrend): _stock_rows_by_snapshot 按 snapshot_id 分批游标拉取（阶段 1 方案 A）"
```

---

## Task 4: signal_cache 键参数分组（去交易层参数）

**Files:**
- Modify: `quant-board/backend/optimization/trial.py`（抽 `_signal_cache_key` 纯函数 + 替换 :145-152）
- Test: `quant-board/tests/test_trial_signal_cache_key.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `quant-board/tests/test_trial_signal_cache_key.py`：

```python
# -*- coding: utf-8 -*-
"""signal_cache 键参数分组测试（阶段 1 方案 B：交易层参数变化复用已算信号）。"""
from __future__ import annotations

from backend.optimization.trial import _signal_cache_key

SIGNAL_FRAMES = [{"snapshotId": "a"}, {"snapshotId": "b"}]

# 信号层基线（RankTrendConfig 字段，from_patch 可识别）
SIGNAL_BASE = {
    "macdFast": 21, "macdSlow": 34, "macdSignal": 13,
    "momentumPeriods": [3, 5, 8, 13, 21],
    "tierSynergyVoteStrong": 2, "tierSynergyVoteWeak": 1, "tierSynergyVoteReverse": -1,
}


def test_signal_cache_key_ignores_trade_layer_params_in_base() -> None:
    # 用户把交易层参数塞进 backtest.strategy_config → 不得污染缓存键
    contaminated = {
        **SIGNAL_BASE,
        "maxPositions": 8, "takeProfit": 0.12, "stopLoss": -0.06,
        "synergyEntryTierMin": "a", "synergyExitOnDanger": True,
        "minJumpConfidence": 0.6,
    }
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) == _signal_cache_key(
        "train", SIGNAL_FRAMES, contaminated
    )


def test_signal_cache_key_changes_with_signal_params() -> None:
    other = {**SIGNAL_BASE, "macdFast": 8}
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "train", SIGNAL_FRAMES, other
    )


def test_signal_cache_key_distinguishes_phase_and_frame_range() -> None:
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "validation", SIGNAL_FRAMES, SIGNAL_BASE
    )
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "train", [{"snapshotId": "a"}, {"snapshotId": "c"}], SIGNAL_BASE
    )
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trial_signal_cache_key.py -q
```

Expected: `FAILED ... cannot import name '_signal_cache_key'`。

- [ ] **Step 3: 实现**

`quant-board/backend/optimization/trial.py`，在 `TrialExecutor` 类定义之前加模块级纯函数；把 `evaluate_phase` 内 :145-152 的键构造替换为调用：

```python
def _signal_cache_key(phase: str, signal_frames: list[dict[str, Any]], strategy_config: dict[str, Any]) -> str:
    """信号缓存键：只含信号层参数（RankTrendConfig 字段子集，经 to_strategy_config 过滤）。

    交易层参数（maxPositions/takeProfit/stopLoss/minJumpConfidence/synergyEntryTierMin/
    synergyExitOnDanger 等，经 to_trade_config 透传给 TradeSimulator、不进 RankTrendConfig）
    不参与键——交易层参数变化时复用已算信号，是长期参数搜索缓存复用的核心（阶段 1 方案 B）。
    从 base_strategy_config 混入的非 RankTrendConfig 键同样被剔除（from_patch 本就忽略未知键，行为一致）。
    """
    return freeze(
        {
            "phase": phase,
            "first": signal_frames[0].get("snapshotId") if signal_frames else "",
            "last": signal_frames[-1].get("snapshotId") if signal_frames else "",
            "strategy": to_strategy_config(strategy_config),
        }
    )
```

替换 `evaluate_phase` 内：

```python
        signal_key = _signal_cache_key(phase, signal_frames, strategy_config)
```

（保留原 `if signal_key not in signal_cache:` 逻辑不动。`freeze`/`to_strategy_config` 已在文件头部 import，见 :9。）

- [ ] **Step 4: 运行测试确认通过**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trial_signal_cache_key.py tests/test_search_space_tier.py tests/test_trial_tier_stats.py -q
```

Expected: 全部 PASS（含既有搜索空间分组与 trial tier 测试，确认无回归）。

- [ ] **Step 5: 提交**

```powershell
git add quant-board/backend/optimization/trial.py quant-board/tests/test_trial_signal_cache_key.py
git commit -m "perf(ranktrend): signal_cache 键按参数分组，交易层参数变化复用已算信号（阶段 1 方案 B）"
```

---

## Task 5: SQLAlchemy 版 `load_frames` 签名对齐

**Files:**
- Modify: `quant-board/backend/data/repositories/snapshot_repository.py:244-251`（签名加 `fields`，仅对齐不裁剪）

- [ ] **Step 1: 实现（签名对齐，保持行为不变）**

`snapshot_repository.py:244-251`，签名与 docstring 更新：

```python
    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按帧+股票行加载快照（SQLAlchemy 版）。

        阶段 1 只对 Mongo 主链做字段白名单裁剪；sqlite 后端接受 fields 参数保持
        与 MongoRepository.load_frames 签名一致，但暂不裁剪（本地库，无压库问题）。
        """
        if self.session is None:
            raise RuntimeError("primary database is unavailable")
```

（函数体其余逻辑不变。）

- [ ] **Step 2: 运行测试确认无回归**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_repository.py tests/test_optimization_service.py tests/test_trial_signal_cache_key.py -q
```

Expected: 全部 PASS。

- [ ] **Step 3: 提交**

```powershell
git add quant-board/backend/data/repositories/snapshot_repository.py
git commit -m "perf(ranktrend): snapshot_repository.load_frames 签名对齐 fields 参数（阶段 1）"
```

---

## Task 6: 全量验证 + 文档更新

**Files:**
- Test: `quant-board/tests/`（全量）
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`（阶段 1 状态）

- [ ] **Step 1: 全量 pytest**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: `1506 passed`（当前基线）或更多；**不得有失败**。重点确认 `tests/test_ranktrend_golden_alignment.py`、`tests/test_ranktrend_engine.py` 通过（引擎输出不受投影/键改造影响）。

- [ ] **Step 2: 人工 diff 自审**

```powershell
git status --short
git diff --stat
```

Expected: 只含本次 5 个任务的文件（shared.py / mongo_repository.py / optimization_service.py / trial.py / snapshot_repository.py / 3 个测试文件 / 1 个文档），无无关改动、无运行产物。

- [ ] **Step 3: 更新长期计划文档**

`quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md` 顶部状态改为 `已落地阶段 1（commit <本次 HEAD>）`，并在 §2.1/§2.2 对应条目标注实现位置：
- 字段白名单投影：`BACKTEST_RANKTREND_STOCK_FIELDS`（`backend/services/shared.py`）+ `load_frames(fields=...)`（`mongo_repository.py`）
- 游标分批：`_stock_rows_by_snapshot` 按 `_STOCK_ROWS_BATCH_SIZE=200` 分批
- 参数分组缓存键：`_signal_cache_key`（`backend/optimization/trial.py`），`strategyRunCount` 可用于度量复用率

- [ ] **Step 4: 手动验收（需真实 Mongo + 一次优化任务，标注为手动项）**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

然后对真实数据集发起一次 `method=random, max_trials=24` + walk_forward 优化，确认：
- 结果 `strategyRunCount` 显著小于 `trialCount`（交易层参数变化时信号复用生效）；
- 全程 Mongo 无 `snapshot_stock_rows` 全量 57 万行拉取日志（分批生效）；
- 任务完成耗时 ≤ 20 分钟（longterm 计划阶段 1 验收线）。

若本机无法起 Mongo/跑真实优化，在最终交付说明中如实标注"手动验收未执行"，并列出上述检查点供用户执行。

- [ ] **Step 5: 提交文档**

```powershell
git add quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md
git commit -m "docs(ranktrend): 长期回测计划阶段 1 性能改造落地状态更新"
```

---

## 风险与回退

1. **投影遗漏导致引擎静默降级（fail-visible 违约，最高风险）**：白名单是"超集 + grep 实证"，但若有引擎消费字段遗漏，引擎会拿到缺字段行。缓解：Task 6 全量 pytest + golden 对齐测试兜底；发现遗漏时把字段补进 `BACKTEST_RANKTREND_STOCK_FIELDS` 并补一条投影测试。
2. **分批改变排序/分组语义**：每批 find 自带 `sort(rank)`，合并进同一 `defaultdict(list)`，分组键与组内顺序不变；Task 3 测试断言 30 帧/3 批的分组完整性与原投影测试兜底。
3. **signal_key 改造行为变化**：`to_strategy_config` 过滤后，若用户 base 里放了会影响 replay 但不在 `_STRATEGY_PARAM_KEYS` 的键，该键不再参与缓存键——但 `RankTrendConfig.from_patch` 本就忽略未知键，replay 行为不变；Task 4 测试覆盖"base 混入交易层参数"场景。
4. **SQLAlchemy 版未裁剪**：sqlite 后端本地库无压库问题，阶段 1 明确只裁剪 Mongo 主链；已在 docstring 注明。
5. **回退**：每个 Task 独立 commit，可用 `git revert <commit>` 逐任务回退；不涉及 schema/API/算法改动，无数据迁移风险。

## Self-Review 结论

- **Spec 覆盖**：longterm 计划 §2.1（A：投影+分批）→ Task 1/2/3；§2.2 进程内部分（B：参数分组缓存键）→ Task 4；验收标准 → Task 6；sqlite 签名兼容 → Task 5；Redis/多进程/阶段 2-4 明确划出范围外。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整实现。
- **类型一致性**：`BACKTEST_RANKTREND_STOCK_FIELDS`（tuple，Task 1 定义、Task 2 用 `list(...)` 传参、Task 6 文档引用）、`_STOCK_ROWS_BATCH_SIZE`（Task 3 定义/测试 monkeypatch）、`_signal_cache_key`（Task 4 定义/测试 import）名称全计划一致；`load_frames` 的 `fields` 参数在 mongo/sqlalchemy 两版签名一致。
