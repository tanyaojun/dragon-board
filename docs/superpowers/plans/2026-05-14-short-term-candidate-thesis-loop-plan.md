# 3-5 天短线候选池与交易假设闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立候选池、交易假设、信号快照、状态跟踪和复盘结果的最小闭环；真实成交记录和截图作为后续增强项接入。

**Architecture:** 在已落地的交易日记能力上做保守增强，不推倒重来。第一版以 QuantBoard MongoDB 为唯一正式存储，复用现有 `trade_journal` collection、`/api/journal` 路由和 `TradeJournalPanel.vue`，把记录入口从“成交后日志”前移为“买前候选/交易假设”。SQLite 不再作为 journal 主链或兼容路径新增。

**Tech Stack:** Python FastAPI + PyMongo + MongoDB, Vue 3 + TypeScript + Vite, pytest, vue-tsc

---

## 1. 背景与结论

`dragon-board` 的下一阶段不是建设传统量化交易平台，而是固化个人 A 股 3-5 天情绪短线模型。系统应服务一个核心问题：

```text
当前市场环境下，哪些 3-5 天交易假设值得进入观察、候选、触发、跟踪和复盘流程？
```

现有 `2026-05-13-trade-journal-and-code-cleanup-plan.md` 已经落地交易日记方向，包括信号快照、复盘标签、截图、入场/出场、PnL 等能力。这些能力应保留。但它当前更偏“成交发生后的记录”，缺少“成交发生前的候选、假设、状态流转和模型复盘”。本计划的目标是补上这条链。

核心判断：

```text
不是重做 TradeJournal，而是把 TradeJournal 升级为 Candidate / Trade Thesis Journal。
```

存储口径：

```text
MongoDB 是 journal 与后续候选池闭环的正式主链。
SQLite 不再用于该模块，不新增 SQLite 模型、迁移或 Repository CRUD。
```

## 2. 当前已知问题记录

### 2.1 产品闭环问题

- 当前记录入口偏“新增入场”，容易只记录真实交易。
- 只记录真实成交会漏掉“观察但未买”“触发但放弃”“候选后失效”的样本。
- 漏掉未交易样本会造成选择偏差，后续 QuantBoard 验证会失真。
- 当前字段偏成交信息：`direction`、`tradeType`、`price`、`volume`、`pnl`。
- 缺少交易假设字段：入池理由、预期剧本、买入前提、失效条件、预期持仓天数。
- 缺少状态流转：观察中、候选、触发、跟踪中、退出复盘。
- 缺少模型复盘与执行复盘拆分。一次赚钱不等于模型正确，一次亏钱也不等于模型错误。

### 2.2 技术实现问题

- `quant-board/backend/data/mongodb_migration.py` 已有 `trade_journal` collection，但索引仍偏成交记录，应补充 `status`、`modelResult`、`executionResult` 等查询字段。
- `quant-board/backend/data/models.py` 里的 `TradeJournal` 还是成交日志 dataclass，缺少候选/假设闭环字段。
- `quant-board/backend/data/mongo_research_repository.py` 中 journal 方法当前缩进在类外，`hasattr(MongoResearchRepository, 'save_journal_entry')` 返回 `False`，MongoDB 路径实际不可用。
- `quant-board/backend/api/journal_routes.py` 目前只接受成交记录字段，缺少候选状态、交易假设、失效条件和复盘结果字段。
- `TradeJournalPanel.vue` 已实现信号快照和交易记录，但表单主语仍是入场/出场，不是候选/假设。
- 当前 `pnl` 统计疑似挂在入场记录，但统计查询筛选 `tradeType == "exit"`，口径需要统一。第一版不把 PnL 作为主验收。
- 截图静态路径 `/api/static/...` 是否已挂载需要单独核实；截图不是第一版闭环阻塞项。

### 2.3 明确不做 SQLite

本计划不做以下事项：

- 不新增 `TradeJournalModel`。
- 不修改 `ResearchBase`。
- 不修改 `quant-board/backend/data/repository.py` 来支持 journal。
- 不为 journal 增加 SQLite 迁移。
- 不把 `/api/journal` 设计成双存储兼容接口。

如果运行环境未切到 MongoDB，journal API 应返回结构化错误或在启动检查中暴露配置问题，而不是静默落回 SQLite。

### 2.4 第一版范围边界

本计划第一版不处理：

- 自动交易。
- 复杂评分模型。
- 参数优化器。
- 全局 UI 大改。
- DragonAnalyzer 清理。
- IndexedDB 清理。
- 新外部数据源。
- 截图能力完善。
- 真实成交/PnL 深度统计。

## 3. 成功标准

第一版完成后，系统必须支持以下闭环：

```text
发现股票 → 记录候选/交易假设 → 抓取信号快照 → 状态流转 → 3-5 天跟踪 → 复盘模型与执行结果
```

具体成功标准：

- 可以创建一条非成交候选记录，价格和数量允许为空或 0。
- 每条记录必须可保存：市场环境、题材地位、个股角色、入池理由、交易假设、买入前提、失效条件、预期持仓天数。
- 每条记录必须有状态：`observe`、`candidate`、`triggered`、`tracking`、`reviewed`。
- 每条记录可以保存 `signalsSnapshot`，包括龙头、市场情绪、RankTrend。
- 每条记录可以保存人工决策：观察、执行、放弃。
- 每条记录可以保存未执行原因。
- 复盘时必须区分：模型结果、执行结果、复盘结论。
- 列表可以按状态、股票、方向、标签过滤。
- MongoDB repository 方法真实挂在 `MongoResearchRepository` 类上。
- MongoDB 测试覆盖创建、更新、筛选、统计。
- 前端类型检查通过。

## 4. 领域合同

### 4.1 状态流转

```text
observe → candidate → triggered → tracking → reviewed
```

含义：

```text
observe    观察中：有异动，但条件不完整
candidate  候选：符合模型，值得重点看
triggered  触发：达到买入前提，但是否执行由人决定
tracking   跟踪中：已进入交易或模拟跟踪周期
reviewed   退出复盘：3-5 天结束，记录成败原因
```

允许人为跳转，但 UI 必须保留当前状态，不能只靠成交方向表达生命周期。

### 4.2 字段合同

保留原有字段：

```text
id
stockCode
stockName
direction
tradeType
price
volume
tradeTime
linkedEntryId
signalsSnapshot
notes
screenshotPaths
reviewTags
pnl
pnlPct
createdAt
updatedAt
```

新增第一版闭环字段：

```text
status
marketPhase
themeRole
stockRole
entryReason
tradeHypothesis
entryPrerequisites
invalidationRules
expectedHoldingDays
humanDecision
skipReason
reviewOutcome
modelResult
executionResult
reviewNotes
```

字段建议值：

```text
status: observe | candidate | triggered | tracking | reviewed
marketPhase: ice | repair | main_up | climax | divergence | decline | mixed
themeRole: mainline | branch | rotation | rebound | decline | unknown
stockRole: leader | core | follower | rebound | abnormal_watch | unknown
humanDecision: watch | execute | skip
reviewOutcome: success | partial | failed | not_triggered | pending
modelResult: correct | partial | wrong | unknown
executionResult: good | early_sell | late_sell | chased | missed | no_trade | unknown
expectedHoldingDays: 3 | 4 | 5
```

### 4.3 复盘原则

复盘必须分开判断：

```text
modelResult：当初模型判断是否正确
executionResult：人工执行是否正确
pnl：真实成交盈亏，后续增强项
```

示例：

```text
模型正确但未执行：modelResult=correct, executionResult=missed
模型错误但止损及时：modelResult=wrong, executionResult=good
模型正确但卖早：modelResult=correct, executionResult=early_sell
未触发：reviewOutcome=not_triggered, executionResult=no_trade
```

## 5. 文件结构

### 第一版需要修改

```text
quant-board/backend/data/models.py
quant-board/backend/data/mongodb_migration.py
quant-board/backend/data/mongo_research_repository.py
quant-board/backend/api/journal_routes.py
src/components/panels/TradeJournalPanel.vue
quant-board/tests/test_trade_journal.py
quant-board/tests/test_mongo_research_repository.py
```

### 第一版不修改

```text
quant-board/backend/data/database.py
quant-board/backend/data/repository.py
proxy-server/**
python-bridge/**
tools/**
src/services/snapshot/**
src/services/DragonAnalyzer.ts
src/services/quantBoardBridge.ts
```

## 6. 实施任务

### Task 1: 后端失败测试 - 锁定 MongoDB journal repository 合同

**Files:**
- Modify: `quant-board/tests/test_mongo_research_repository.py`

- [ ] **Step 1: 新增 repository 行为测试**

在现有 MongoDB repository 测试文件末尾追加：

```python
from backend.data.models import TradeJournal


def test_mongo_research_repository_saves_candidate_thesis_fields() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    entry = TradeJournal(
        id="tj_candidate",
        stock_code="000001",
        stock_name="平安银行",
        status="candidate",
        market_phase="repair",
        theme_role="mainline",
        stock_role="core",
        entry_reason="RankTrend 持续上行，题材扩散，情绪修复",
        trade_hypothesis="未来 3-5 天沿主线继续走强",
        entry_prerequisites="次日不弱于题材，排名不明显回落",
        invalidation_rules="题材退潮或 RankTrend 断档",
        expected_holding_days=3,
        human_decision="watch",
        signals_snapshot={"rankTrend": {"candidateTier": "B_IGNITION"}},
    )

    saved = repo.save_journal_entry(entry)
    row = repo.get_journal_entry(saved.id)

    assert row["id"] == "tj_candidate"
    assert row["status"] == "candidate"
    assert row["marketPhase"] == "repair"
    assert row["themeRole"] == "mainline"
    assert row["stockRole"] == "core"
    assert row["tradeHypothesis"] == "未来 3-5 天沿主线继续走强"
    assert row["expectedHoldingDays"] == 3
    assert row["signalsSnapshot"]["rankTrend"]["candidateTier"] == "B_IGNITION"


def test_mongo_research_repository_filters_journal_entries_by_status() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    repo.save_journal_entry(TradeJournal(id="tj_1", stock_code="000001", stock_name="a", status="candidate"))
    repo.save_journal_entry(TradeJournal(id="tj_2", stock_code="000002", stock_name="b", status="reviewed"))

    rows = repo.list_journal_entries(status="candidate")

    assert [row["id"] for row in rows] == ["tj_1"]


def test_mongo_research_repository_updates_review_result_separately_from_execution() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    repo.save_journal_entry(TradeJournal(id="tj_1", stock_code="000001", stock_name="a", status="triggered"))

    row = repo.update_journal_entry(
        "tj_1",
        {
            "status": "reviewed",
            "reviewOutcome": "success",
            "modelResult": "correct",
            "executionResult": "missed",
            "skipReason": "盘中未确认仓位",
            "reviewNotes": "模型判断正确，但没有执行",
        },
    )

    assert row["status"] == "reviewed"
    assert row["modelResult"] == "correct"
    assert row["executionResult"] == "missed"
    assert row["skipReason"] == "盘中未确认仓位"
    assert row["reviewNotes"] == "模型判断正确，但没有执行"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_research_repository.py -q
```

Expected: FAIL。失败原因应包括 `MongoResearchRepository` 缺 journal 方法或新增字段未保存。

### Task 2: 扩展 TradeJournal dataclass 映射合同

**Files:**
- Modify: `quant-board/backend/data/models.py`

- [ ] **Step 1: 给 dataclass 增加闭环字段**

在 `TradeJournal` 中新增与字段合同一致的 snake_case 属性，并提供默认值：

```python
status: str = "observe"
market_phase: str = ""
theme_role: str = ""
stock_role: str = ""
entry_reason: str = ""
trade_hypothesis: str = ""
entry_prerequisites: str = ""
invalidation_rules: str = ""
expected_holding_days: int = 3
human_decision: str = "watch"
skip_reason: str = ""
review_outcome: str = "pending"
model_result: str = "unknown"
execution_result: str = "unknown"
review_notes: str = ""
```

- [ ] **Step 2: 更新 `to_dict()` 输出 camelCase**

必须输出：

```python
"status": self.status,
"marketPhase": self.market_phase,
"themeRole": self.theme_role,
"stockRole": self.stock_role,
"entryReason": self.entry_reason,
"tradeHypothesis": self.trade_hypothesis,
"entryPrerequisites": self.entry_prerequisites,
"invalidationRules": self.invalidation_rules,
"expectedHoldingDays": self.expected_holding_days,
"humanDecision": self.human_decision,
"skipReason": self.skip_reason,
"reviewOutcome": self.review_outcome,
"modelResult": self.model_result,
"executionResult": self.execution_result,
"reviewNotes": self.review_notes,
```

- [ ] **Step 3: 更新 `from_dict()` 兼容旧 MongoDB 文档**

旧记录没有新增字段时必须回退：

```python
status=str(data.get("status") or "observe")
trade_type=str(data.get("tradeType") or "thesis")
expected_holding_days=int(data.get("expectedHoldingDays") or 3)
review_outcome=str(data.get("reviewOutcome") or "pending")
model_result=str(data.get("modelResult") or "unknown")
execution_result=str(data.get("executionResult") or "unknown")
```

- [ ] **Step 4: 运行 dataclass 往返检查**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -c "from backend.data.models import TradeJournal; t=TradeJournal(id='tj_test', stock_code='000001', stock_name='x', status='candidate', trade_hypothesis='h'); print(t.to_dict()['tradeHypothesis'])"
```

Expected:

```text
h
```

### Task 3: 修正 MongoResearchRepository journal 方法并扩展字段

**Files:**
- Modify: `quant-board/backend/data/mongo_research_repository.py`

- [ ] **Step 1: 把 journal 方法移动进 `MongoResearchRepository` 类**

当前文件中 journal 方法位于 `_utc_now_naive()` 后，缩进到函数体不可达区域。必须移入 `class MongoResearchRepository` 内。

- [ ] **Step 2: 保持 MongoDB 文档使用 camelCase**

`save_journal_entry()` 应使用 `entry.to_dict()` 存储，避免再做一套字段映射。

- [ ] **Step 3: 扩展 list/count 参数**

`list_journal_entries()` 和 `count_journal_entries()` 支持：

```python
stock_code=None
trade_type=None
direction=None
status=None
date_from=None
date_to=None
review_tags=None
limit=50
offset=0
```

MongoDB 查询中加入：

```python
if status:
    query["status"] = status
```

- [ ] **Step 4: 更新 stats**

统计返回：

```text
tagCounts
statusCounts
modelResultCounts
executionResultCounts
totalPnl
winRate
totalExits
```

PnL 第一版只兼容现有字段，不作为候选闭环主指标。

- [ ] **Step 5: 运行导入检查**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -c "from backend.data.mongo_research_repository import MongoResearchRepository; print(hasattr(MongoResearchRepository, 'save_journal_entry'))"
```

Expected:

```text
True
```

- [ ] **Step 6: 运行 Mongo repository 测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_research_repository.py -q
```

Expected: 新增 journal 测试 PASS。

### Task 4: 扩展 MongoDB collection indexes

**Files:**
- Modify: `quant-board/backend/data/mongodb_migration.py`

- [ ] **Step 1: 更新 `trade_journal` indexes**

保留原索引，并补充：

```python
{"keys": [("status", 1), ("createdAt", -1)]},
{"keys": [("stockCode", 1), ("status", 1), ("createdAt", -1)]},
{"keys": [("modelResult", 1), ("createdAt", -1)]},
{"keys": [("executionResult", 1), ("createdAt", -1)]},
```

- [ ] **Step 2: 运行索引构建配置检查**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -c "from backend.data.mongodb_migration import build_mongodb_indexes; print(build_mongodb_indexes()['trade_journal'])"
```

Expected: 输出包含 `status`、`modelResult`、`executionResult` 索引。

### Task 5: 后端 API 失败测试 - 锁定候选/假设接口

**Files:**
- Create: `quant-board/tests/test_trade_journal.py`

- [ ] **Step 1: 新增 API 合同测试**

测试通过 monkeypatch 替换 `journal_routes.create_repository`，避免连接真实 MongoDB：

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import journal_routes
from backend.main import app


class FakeJournalRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def save_journal_entry(self, entry):
        row = entry.to_dict()
        self.rows[row["id"]] = row
        return entry

    def get_journal_entry(self, entry_id: str):
        return self.rows.get(entry_id)

    def list_journal_entries(self, status=None, limit=50, offset=0, **_kwargs):
        rows = list(self.rows.values())
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def count_journal_entries(self, status=None, **_kwargs):
        return len(self.list_journal_entries(status=status, limit=10_000, offset=0))

    def update_journal_entry(self, entry_id: str, updates: dict):
        self.rows[entry_id].update(updates)
        return self.rows[entry_id]


def test_create_candidate_thesis_entry_round_trips_core_fields(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)

    response = client.post(
        "/api/journal/entries",
        json={
            "stock_code": "000001",
            "stock_name": "平安银行",
            "status": "candidate",
            "market_phase": "repair",
            "theme_role": "mainline",
            "stock_role": "core",
            "entry_reason": "RankTrend 持续上行，题材扩散，情绪修复",
            "trade_hypothesis": "未来 3-5 天沿主线继续走强",
            "entry_prerequisites": "次日不弱于题材，排名不明显回落",
            "invalidation_rules": "题材退潮或 RankTrend 断档",
            "expected_holding_days": 3,
            "human_decision": "watch",
            "signals_snapshot": {"rankTrend": {"candidateTier": "B_IGNITION"}},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "candidate"
    assert data["marketPhase"] == "repair"
    assert data["themeRole"] == "mainline"
    assert data["stockRole"] == "core"
    assert data["tradeHypothesis"] == "未来 3-5 天沿主线继续走强"
    assert data["price"] == 0
    assert data["volume"] == 0


def test_update_candidate_thesis_review_separates_model_and_execution_result(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)
    created = client.post(
        "/api/journal/entries",
        json={"stock_code": "000002", "stock_name": "万科A", "status": "triggered"},
    ).json()

    response = client.put(
        f"/api/journal/entries/{created['id']}",
        json={
            "status": "reviewed",
            "review_outcome": "success",
            "model_result": "correct",
            "execution_result": "missed",
            "skip_reason": "盘中未确认仓位",
            "review_notes": "模型判断正确，但没有执行",
            "review_tags": ["信号正确未执行"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "reviewed"
    assert data["reviewOutcome"] == "success"
    assert data["modelResult"] == "correct"
    assert data["executionResult"] == "missed"
    assert data["skipReason"] == "盘中未确认仓位"
    assert data["reviewNotes"] == "模型判断正确，但没有执行"
    assert data["reviewTags"] == ["信号正确未执行"]


def test_list_candidate_entries_can_filter_by_status(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)
    client.post("/api/journal/entries", json={"stock_code": "000003", "stock_name": "测试候选", "status": "candidate"})
    client.post("/api/journal/entries", json={"stock_code": "000004", "stock_name": "测试复盘", "status": "reviewed"})

    response = client.get("/api/journal/entries?status=candidate")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["entries"][0]["status"] == "candidate"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py -q
```

Expected: FAIL。失败原因应为 `/api/journal` 缺新增字段或 status filter。

### Task 6: 扩展 journal API 为 MongoDB 主链接口

**Files:**
- Modify: `quant-board/backend/api/journal_routes.py`

- [ ] **Step 1: 保持 MongoDB repository factory**

`_get_repo()` 可以继续使用：

```python
def _get_repo():
    return create_repository(None)
```

不要引入 `Depends(get_db)`，不要新增 SQLite session。

- [ ] **Step 2: 扩展 request model**

`CreateJournalEntryRequest` 新增候选字段，并让成交字段可选或有默认值：

```python
status: str = "observe"
market_phase: str = ""
theme_role: str = ""
stock_role: str = ""
entry_reason: str = ""
trade_hypothesis: str = ""
entry_prerequisites: str = ""
invalidation_rules: str = ""
expected_holding_days: int = 3
human_decision: str = "watch"
skip_reason: str = ""
review_outcome: str = "pending"
model_result: str = "unknown"
execution_result: str = "unknown"
review_notes: str = ""
direction: str = "buy"
trade_type: str = "thesis"
price: float = 0
volume: int = 0
trade_time: str = ""
```

- [ ] **Step 3: 扩展 update model**

`UpdateJournalEntryRequest` 加入同一批字段，全部为可选。

- [ ] **Step 4: create_entry 构造完整 TradeJournal**

创建时写入所有新增字段。`trade_time` 为空时使用当前时间 ISO 字符串。

- [ ] **Step 5: 扩展 field_map**

snake_case 到 camelCase：

```python
"status": "status",
"market_phase": "marketPhase",
"theme_role": "themeRole",
"stock_role": "stockRole",
"entry_reason": "entryReason",
"trade_hypothesis": "tradeHypothesis",
"entry_prerequisites": "entryPrerequisites",
"invalidation_rules": "invalidationRules",
"expected_holding_days": "expectedHoldingDays",
"human_decision": "humanDecision",
"skip_reason": "skipReason",
"review_outcome": "reviewOutcome",
"model_result": "modelResult",
"execution_result": "executionResult",
"review_notes": "reviewNotes",
```

- [ ] **Step 6: list API 加入 status filter**

`list_entries()` 增加：

```python
status: str | None = Query(None),
```

并传给 repository 的 list/count。

- [ ] **Step 7: 运行 API 测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py -q
```

Expected: 3 tests PASS。

### Task 7: 前端类型与表单主语切换为候选/假设

**Files:**
- Modify: `src/components/panels/TradeJournalPanel.vue`

- [ ] **Step 1: 扩展 `JournalEntry` interface**

加入新增 camelCase 字段：

```typescript
status: string
marketPhase: string
themeRole: string
stockRole: string
entryReason: string
tradeHypothesis: string
entryPrerequisites: string
invalidationRules: string
expectedHoldingDays: number
humanDecision: string
skipReason: string
reviewOutcome: string
modelResult: string
executionResult: string
reviewNotes: string
```

- [ ] **Step 2: 扩展 form 初始值**

默认：

```typescript
status: 'observe',
marketPhase: '',
themeRole: '',
stockRole: '',
entryReason: '',
tradeHypothesis: '',
entryPrerequisites: '',
invalidationRules: '',
expectedHoldingDays: 3,
humanDecision: 'watch',
skipReason: '',
reviewOutcome: 'pending',
modelResult: 'unknown',
executionResult: 'unknown',
reviewNotes: '',
tradeType: 'thesis',
price: 0,
volume: 0,
```

- [ ] **Step 3: 调整标题与按钮文案**

把：

```text
交易日记
新增入场
编辑入场
```

改为：

```text
候选与交易假设
新增候选/假设
编辑候选/假设
```

- [ ] **Step 4: 增加状态和假设字段 UI**

在股票选择后、成交字段前增加：

```text
状态
市场环境
题材地位
个股角色
预期持仓天数
人工决策
入池理由
交易假设
买入前提
失效条件
未执行原因
```

- [ ] **Step 5: 把成交字段改为可选增强区**

保留方向、价格、数量，但文案改为“成交信息（可选）”。第一版不要求折叠或复杂交互。

- [ ] **Step 6: 保存 payload 增加 snake_case 字段**

`saveEntry()` payload 加入：

```typescript
status: form.value.status,
market_phase: form.value.marketPhase,
theme_role: form.value.themeRole,
stock_role: form.value.stockRole,
entry_reason: form.value.entryReason,
trade_hypothesis: form.value.tradeHypothesis,
entry_prerequisites: form.value.entryPrerequisites,
invalidation_rules: form.value.invalidationRules,
expected_holding_days: form.value.expectedHoldingDays,
human_decision: form.value.humanDecision,
skip_reason: form.value.skipReason,
review_outcome: form.value.reviewOutcome,
model_result: form.value.modelResult,
execution_result: form.value.executionResult,
review_notes: form.value.reviewNotes,
```

- [ ] **Step 7: select/reset 映射新增字段**

`resetForm()` 和 `selectEntry()` 必须覆盖全部新增字段，旧数据缺字段时使用默认值。

- [ ] **Step 8: 增加状态过滤**

列表过滤区增加 `filterStatus`，请求参数增加 `status`。

### Task 8: 前端复盘区拆分模型结果与执行结果

**Files:**
- Modify: `src/components/panels/TradeJournalPanel.vue`

- [ ] **Step 1: 在选中记录详情下增加复盘区**

字段：

```text
复盘结果
模型结果
执行结果
复盘结论
复盘标签
```

- [ ] **Step 2: 保存复盘字段**

可复用 `saveEntry()`，不单独新增复杂 API。

- [ ] **Step 3: 预置标签扩展**

保留原标签，并加入：

```text
模型正确
模型错误
未触发
主线确认
支线误判
情绪退潮
题材掉队
RankTrend失效
信号正确未执行
```

### Task 9: 前端信号快照不变，只补上下文字段

**Files:**
- Modify: `src/components/panels/TradeJournalPanel.vue`

- [ ] **Step 1: 保留 `captureSignals()`**

不要重写现有信号抓取逻辑。

- [ ] **Step 2: 从信号快照回填候选字段**

最小增强：

```typescript
if (!form.value.marketPhase && sentiment?.phaseName) form.value.marketPhase = String(sentiment.phaseName)
if (!form.value.stockRole && form.value.signalsSnapshot?.dragon?.primaryRole) form.value.stockRole = String(form.value.signalsSnapshot.dragon.primaryRole)
```

注意：第一版允许中文 phase 直接落库，不强行映射枚举，避免误判。

### Task 10: 验证

**Files:** No code changes

- [ ] **Step 1: Mongo repository journal 测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongo_research_repository.py -q
```

Expected: PASS。

- [ ] **Step 2: journal API 测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py -q
```

Expected: PASS。

- [ ] **Step 3: MongoDB 导入检查**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -c "from backend.data.mongo_research_repository import MongoResearchRepository; print(hasattr(MongoResearchRepository, 'save_journal_entry'))"
```

Expected:

```text
True
```

- [ ] **Step 4: API 路由导入检查**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -c "from backend.api.journal_routes import router; print(len(router.routes))"
```

Expected: 输出路由数量，不报错。

- [ ] **Step 5: 前端类型检查**

Run:

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 无新增 `TradeJournalPanel.vue` 相关错误。

## 7. 验收清单

- [ ] 可以新增一条无成交价格/数量的候选记录。
- [ ] 候选记录保存后刷新仍保留交易假设字段。
- [ ] 可以按 `status=candidate` 过滤列表。
- [ ] 信号快照可以和候选记录一起保存。
- [ ] 可以把候选改为 `triggered`、`tracking`、`reviewed`。
- [ ] 可以记录 `modelResult=correct` 且 `executionResult=missed`。
- [ ] 未交易样本可以保存 `skipReason`。
- [ ] 旧交易日志字段不丢失。
- [ ] 截图和真实成交入口保留，但不是第一版主链。
- [ ] MongoDB 为唯一正式 journal 存储。
- [ ] `MongoResearchRepository` journal 方法挂载可用。
- [ ] 不新增 SQLite journal 代码。

## 8. 后续增强

第一版完成后，再考虑：

- 把候选历史导入 QuantBoard 做 1/3/5 日表现验证。
- 增加候选生成服务，把热榜、RankTrend、题材、龙头信号投影成入池理由。
- 做候选池专用面板，而不是继续堆在交易日记面板里。
- 完善截图静态路径和盘面截图归档。
- 增加真实成交流水、仓位、手续费、滑点、PnL 归因。
- 将交易假设样本与 dataset_id、snapshot_type、strategy_version、config_hash、random_seed 关联，进入可复现研究闭环。

## 9. 执行建议

第一批只执行 Task 1 到 Task 7，先形成买前候选/假设闭环。

Task 8 到 Task 10 用于把复盘体验和验证补完整。

不要把本计划和 DragonAnalyzer 清理、IndexedDB 清理混在一个分支里执行。那些是技术债治理，不是模型固化第一阶段的必要条件。
