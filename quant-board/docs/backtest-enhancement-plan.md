# RankTrend 回测系统增强实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. 本文是实施蓝图，执行时按 Phase 顺序推进，每个 Phase 结束后必须验证再进入下一步。

**Goal:** 将 QuantBoard 当前单体化 RankTrend 回测模块拆分为可维护的模块化回测包，并在不破坏现有 API、CLI、优化链路和前端调用的前提下，增强质量门禁、策略解释、归一化结果存储和报告能力。

**Architecture:** 回测、优化、交易模拟和报告展示只在 `quant-board/` 内演进。`backend/core/backtest.py` 原先是约 1190 行单体模块，目前已拆成 `backend/core/backtest/` 包，并由包内 `__init__.py` 负责兼容导出。后续增强必须保持现有 `POST /api/backtests/rank-trend`、`run-ranktrend`、优化 trial 调用回测引擎的主链不变。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、SQLite research DB、Vue 3 QuantBoard frontend、pytest。

---

## 接力状态

截至 2026-05-04，当前工作区已完成以下后端基础任务：

| Phase | 状态 | 已落地内容 | 证据 |
|---|---|---|---|
| Phase 1 | 已完成 | `backend/core/backtest.py` 已拆为 `backend/core/backtest/` 包，历史公开符号由 `__init__.py` 兼容导出，旧单体文件保留为 `backend/core/backtest_legacy.py` | commit `5241ebd` |
| Phase 2 | 已完成 | `quality_gate.py` 已增强 NaN、Infinity、负值、覆盖率等质量检查；fatal Infinity 已按审计意见修复 | commit `3af06da` 后续修正 |
| Phase 3A | 已完成 | 已新增四层策略解释模型并记录 `strategyDecisions`；撮合行为仍由原交易模拟逻辑负责 | commit `428835f` |
| Phase 4 后端核心 | 已完成 | 已新增 `BacktestTrade`、`BacktestEquityCurve`、`BacktestSignal`、`BacktestQualityReport` 和 `BacktestRun` 增强字段；`BacktestService.run_ranktrend()` 已双写 JSON blob 与归一化表；归一化写入失败会抛错，不再返回伪成功 | commit `1de75da` |
| Phase 4 文档/API 对外化 | 未完成 | `architecture.md`、`api-cli.md`、`frontend.md` 尚未完整同步归一化表和读取口径；API 仍只有旧的 run/get/report 端点 | 本文后续 Phase 4/5 |
| Phase 5 | 未完成 | 归一化结果读取 API、回测对比 API、CLI compare/export 尚未实现 | `backend/main.py`、`backend/cli.py` 当前状态 |
| Phase 6 | 未完成 | QuantBoard 前端报告页尚未消费归一化 API | `frontend/` 当前状态 |
| Phase 3B | 未开始 | `useStrategyDecisionForExecution` 仍保持可选未来项，不能在 Phase 5/6 顺手打开 | 本文 Phase 3B 约束 |

后续接力优先级：

1. 先补 Phase 4 文档同步，明确 research SQLite 归一化结果不进入 Supabase Free 版备份链路。
2. 再做 Phase 5 API/CLI，把已存在的 repository 读取方法暴露给后端接口和命令行。
3. 最后做 Phase 6 前端报告增强，改用归一化 API 读取交易、权益、信号和质量报告。
4. Phase 3B 必须单独立项，不能和报告展示任务混在同一批改动中。

最近一次已知验证：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m py_compile backend\data\database.py backend\data\repository.py backend\services.py backend\core\backtest\engine.py
.\.venv\Scripts\python.exe -m pytest tests/ -q
git diff --check
```

已知结果：`pytest` 为 `23 passed`，仅有既有 DeprecationWarnings；`git diff --check` 无输出。

---

## 0. 当前事实与硬约束

- 当前回测入口已经是 `backend/core/backtest/` 包，公开符号包括 `DEFAULT_TRADE_CONFIG`、`STRATEGY_DEFINITIONS`、`OutcomeEvaluator`、`TradeSimulator`、`BacktestEngine`、`Optimizer`。
- 当前 API 是 `POST /api/backtests/rank-trend`、`GET /api/backtests/{run_id}`、`GET /api/backtests/{run_id}/report`，不得误写为 `POST /api/backtests`。
- 当前 CLI 是 `python -m backend.cli run-ranktrend`，优化模块会调用 `BacktestService.run_ranktrend()` 产生 trial 回测结果。
- `BacktestRun` 当前保留 `request_json` 和 `result_json` 兼容旧读取，并已增加 `date_start`、`date_end`、`finished_at`、`error_reason`；新增归一化结果表属于 research SQLite，不进入 Supabase Free 版备份链路。
- 默认 `snapshot_type` 保持 `half_hour`；`quarter_hour` 只能由用户显式选择。
- 每次回测和优化 trial 必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- Dragon Board 根项目 `src/` 完全不动；回测、优化、交易模拟和报告展示不回流到根项目。
- 不批量删除文件或目录。若需要处理旧 `backend/core/backtest.py`，只能按单个明确路径操作，并先确认替代导入已经通过测试。
- 后续实现必须尊重已完成后端结构，不要把 `backend/core/backtest_legacy.py` 重新作为运行入口，也不要把归一化结果重新塞进 Supabase 备份链路。

---

## Phase 1: 模块化目录重构，保持行为不变

### 目标

把 `backend/core/backtest.py` 拆分为 `backend/core/backtest/` 包。注意 Python 不能可靠地让同一路径下的 `backtest.py` 同时作为 `backend.core.backtest` 的兼容层；新建同名目录后，兼容导出必须放在 `backend/core/backtest/__init__.py`。

### 目标目录

```text
backend/core/backtest/
├── __init__.py          # 兼容导出所有历史公开符号
├── config.py            # DEFAULT_TRADE_CONFIG + BacktestExecutionConfig
├── strategy.py          # STRATEGY_DEFINITIONS + 策略名称归一化 + 策略解释模型
├── metrics.py           # share/average/max_drawdown/short_cycle_sharpe 等指标工具
├── evaluator.py         # OutcomeEvaluator + outcome 辅助查找函数
├── execution.py         # TradeSimulator，保持现有撮合行为
├── engine.py            # BacktestEngine + Optimizer
├── models.py            # 回测领域 dataclass，只放跨模块共享模型
├── orders.py            # 订单和成交相关模型
├── portfolio.py         # 后续持仓、现金、净值管理抽象
├── risk.py              # 后续风险约束和可执行性判断
└── quality.py           # BacktestDataQuality 和回测质量报告适配
```

### 迁移映射

| 当前符号或函数 | 迁入文件 |
|---|---|
| `DEFAULT_TRADE_CONFIG` | `config.py` |
| `STRATEGY_DEFINITIONS`、`SUPPORTED_STRATEGY_NAMES`、`CONTROL_STRATEGIES`、`DEFAULT_STRATEGY_NAME`、`normalize_strategy_name()` | `strategy.py` |
| `share()`、`average()`、`max_drawdown()`、`_sample_std()`、`short_cycle_sharpe()`、`_round_or_none()`、`_first_number()`、`_first_finite()` | `metrics.py` |
| `find_frame_index()`、`find_stock()`、`build_frame_lookup()`、`percentile()`、`momentum_bucket()`、`OutcomeEvaluator` | `evaluator.py` |
| `TradeSimulator` | `execution.py` |
| `BacktestEngine`、`Optimizer` | `engine.py` |

### 兼容导出

`backend/core/backtest/__init__.py` 必须 re-export 历史公开符号，保证以下导入继续可用：

```python
from backend.core.backtest import BacktestEngine, TradeSimulator, OutcomeEvaluator
from backend.core.backtest import DEFAULT_TRADE_CONFIG, STRATEGY_DEFINITIONS
from backend.core.backtest import normalize_strategy_name, max_drawdown, short_cycle_sharpe
```

旧 `backend/core/backtest.py` 的处理规则：

- Phase 1 实施时，先把内容拆入包内并跑测试。
- 如果保留旧文件会造成导入歧义，应将它作为单个明确文件改名为 `backend/core/backtest_legacy.py`，仅供迁移核对。
- 迁移稳定后再单独处理 legacy 文件；不得批量删除。

### 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/ -x
.\.venv\Scripts\python.exe -m backend.cli run-ranktrend --dataset-id <existing_id>
```

通过标准：

- 现有测试通过。
- `run-ranktrend` 能正常生成 `BacktestRun`。
- 优化模块中 `from backend.core.backtest import BacktestEngine` 等导入不需要改调用方。
- Phase 1 不改变任一回测指标、交易数量、信号数量和质量门禁结果。

---

## Phase 2: 增强数据质量门禁

### 目标

在现有 `backend/data/quality_gate.py` 基础上补充回测级质量报告，明确处理空数据、NaN、Infinity、非法价格、非法成交量、时间乱序、低覆盖率和样本不足。质量失败必须结构化返回，不能静默继续产出交易结果。

### 模型

在 `backend/core/backtest/quality.py` 新增：

```python
@dataclass
class BacktestDataQuality:
    passed: bool
    reasons: list[dict[str, Any]]
    frame_count: int
    stock_count: int
    sector_count: int
    missing_fields: dict[str, int]
    nan_counts: dict[str, int]
    inf_counts: dict[str, int]
    negative_price_count: int
    non_positive_price_count: int
    negative_volume_count: int
    coverage_ratio: float
    time_order_fixed: bool
    time_order_fix_count: int
    warnings: list[str]
```

### 质量检查口径

- `evaluate_snapshot_quality()` 保留现有返回合同，在 `stats` 中新增 `nanCounts`、`infCounts`、`negativePriceCount`、`nonPositivePriceCount`、`negativeVolumeCount`、`coverageRatio`。
- 核心数值字段覆盖 `price`、`change`、`volume`、`turnover`、`turnoverRate`、`avgRankNum`、`finalConfidence`。
- `price <= 0` 对交易撮合是 fatal；`volume < 0` 是 fatal；单字段少量 NaN 可降级为 warning，但参与成交价格、收益率或仓位计算的字段不能用 NaN 继续计算。
- `_prepare_frames_for_backtest()` 继续允许空热榜帧过滤，但过滤行为必须写入 `runtimeFilter`，并保留被丢弃的 `snapshotId` 预览。
- 时间乱序如果能排序修复，记录 `timeOrderFixed=True`；如果存在重复 `snapshotId` 或核心字段缺失，直接失败。

### 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quality.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -x
```

通过标准：

- 空数据、NaN、Infinity、非法价格、低覆盖率都有明确测试。
- API 400 的 `detail` 中仍能看到结构化 `qualityGate` 信息。
- 正常数据集的回测结果不因新增质量字段发生指标变化。

---

## Phase 3: 四层策略解释模型，先记录后消费

### 目标

把当前嵌在 `TradeSimulator._entry_candidates()` 和 `_exit_reason()` 中的策略判断显式表达为四层策略解释模型。但 v1 不直接改变撮合行为，先把解释结果写入回测结果和归一化信号表；待回归测试稳定后，再允许撮合层消费 `StrategyDecision`。

### 模型

在 `backend/core/backtest/strategy.py` 新增：

```python
@dataclass
class StrategyInput:
    frame: dict[str, Any]
    historical_frames: list[dict[str, Any]]
    stock_rows: list[dict[str, Any]]
    sector_rows: list[dict[str, Any]]
    runtime_config: dict[str, Any]
    portfolio_state: dict[str, Any]

@dataclass
class StrategyDecision:
    timestamp: int
    snapshot_id: str
    candidates: list[dict[str, Any]]
    strong_candidates: list[dict[str, Any]]
    watch_candidates: list[dict[str, Any]]
    excluded_candidates: list[dict[str, Any]]
    signal: str
    confidence: float
    reasons: list[str]
    risk_flags: list[str]
    quality_flags: list[str]
    target_positions: list[dict[str, Any]]
```

四层流水线：

1. `CandidateGeneration`：从 RankTrend 信号、热榜排名、题材强度生成候选。
2. `CandidateTiering`：按 `A_MAIN`、`B_IGNITION`、`C_CROWDED`、`D_EXIT_RISK`、`N_NEUTRAL` 分层。
3. `SignalGeneration`：基于候选分层、`finalSignal`、`finalConfidence` 生成 `buy`、`sell`、`hold`、`watch`。
4. `RiskFiltering`：记录涨跌停、T+1、流动性、`regime=retreat`、样本质量等风险标记。

### 分阶段接入

- Phase 3A：`TradeSimulator` 的 `_entry_candidates()` 和退出规则保持现状；新增策略解释只作为结果字段和报告数据。
- Phase 3B：在归一化信号表和回归测试稳定后，再增加开关 `useStrategyDecisionForExecution`，默认 `False`。
- Phase 3B 只有在开关显式为 `True` 时，才允许 `TradeSimulator` 基于 `StrategyDecision.target_positions` 执行。

### 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_strategy.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -x
```

通过标准：

- Phase 3A 前后，同一数据集的交易数量、权益曲线、总收益、最大回撤保持一致。
- 回测结果新增候选分层、风险标记和解释字段。
- 前端和 API 不再把 `finalSignal` 当作唯一交易结论。

---

## Phase 4: 归一化结果存储

**当前状态：后端核心已完成，文档同步和读取 API 仍需接力。**

### 目标

保留 `BacktestRun.result_json` 兼容旧读取，同时把交易、权益曲线、信号解释、质量报告拆到 research SQLite 结构化表，支持分页查询、报告页和回测对比。

### 数据模型

在 `backend/data/models.py` 的 `ResearchBase` 下新增：

```python
class BacktestTrade(ResearchBase):
    __tablename__ = "backtest_trades"
    id: Mapped[int]
    backtest_run_id: Mapped[str]
    code: Mapped[str]
    name: Mapped[str]
    side: Mapped[str]
    entry_snapshot_id: Mapped[str | None]
    exit_snapshot_id: Mapped[str | None]
    entry_time: Mapped[int | None]
    exit_time: Mapped[int | None]
    entry_price: Mapped[float | None]
    exit_price: Mapped[float | None]
    quantity: Mapped[int]
    gross_return: Mapped[float | None]
    net_return: Mapped[float | None]
    profit: Mapped[float | None]
    holding_bars: Mapped[int | None]
    reason: Mapped[str]
    candidate_tier: Mapped[str | None]
    stage: Mapped[str | None]
    regime: Mapped[str | None]
    explanation_json: Mapped[str]
    fill_detail_json: Mapped[str]

class BacktestEquityCurve(ResearchBase):
    __tablename__ = "backtest_equity_curve"
    id: Mapped[int]
    backtest_run_id: Mapped[str]
    snapshot_id: Mapped[str]
    timestamp: Mapped[int]
    equity: Mapped[float]
    cash: Mapped[float]
    market_value: Mapped[float]
    position_count: Mapped[int]

class BacktestSignal(ResearchBase):
    __tablename__ = "backtest_signals"
    id: Mapped[int]
    backtest_run_id: Mapped[str]
    snapshot_id: Mapped[str]
    code: Mapped[str]
    candidate_tier: Mapped[str | None]
    signal: Mapped[str]
    confidence: Mapped[float | None]
    stage: Mapped[str | None]
    regime: Mapped[str | None]
    rank: Mapped[int | None]
    reasons_json: Mapped[str]
    risk_flags_json: Mapped[str]

class BacktestQualityReport(ResearchBase):
    __tablename__ = "backtest_quality_reports"
    id: Mapped[int]
    backtest_run_id: Mapped[str]
    passed: Mapped[bool]
    frame_count: Mapped[int]
    stock_count: Mapped[int]
    sector_count: Mapped[int]
    missing_fields_json: Mapped[str]
    nan_counts_json: Mapped[str]
    inf_counts_json: Mapped[str]
    coverage_ratio: Mapped[float]
    time_order_fixed: Mapped[bool]
    warnings_json: Mapped[str]
```

增强 `BacktestRun`：

- `date_start`
- `date_end`
- `finished_at`
- `error_reason`

### Repository 和 Service

已新增 repository 方法：

- `save_backtest_trades(run_id, trades)`
- `save_backtest_equity_curve(run_id, equity_curve)`
- `save_backtest_signals(run_id, signals)`
- `save_backtest_quality_report(run_id, quality)`
- `get_backtest_trades(run_id, limit, offset)`
- `get_backtest_equity_curve(run_id)`
- `get_backtest_signals(run_id, limit, offset, tier=None, regime=None)`
- `get_backtest_quality_report(run_id)`

`BacktestService.run_ranktrend()` 双写：

- 继续写 `BacktestRun.result_json`，保证旧报告和优化 trial 追溯不破。
- 同时写归一化表，作为新 API 和前端报告主读取路径。
- 如果归一化写入失败，整个回测标记 `failed`，写入 `error_reason`，不能返回伪成功。

当前实现注意点：

- repository 写方法已经在 SQLAlchemy 写入失败时 rollback 并抛 `RuntimeError`，调用方不能吞掉这些异常。
- 当前 get 方法先返回完整列表，Phase 5 暴露 API 时再在 service/API 层补 `limit`、`offset`、`tier`、`regime` 过滤，或把过滤下推到 repository。
- `BacktestQualityReport.passed` 当前按 `dataQuality.severity == "pass"` 判定；前端展示时还要同时展示 `severity` 和 `researchGrade`，不能只看布尔值。
- `BacktestSignal` 来源是 `strategyDecisions.frameResults`，包含 buy/watch/excluded 候选，不等同于真实成交列表。

### 文档同步

Phase 4 修改 research SQLite schema 和 API/CLI 合同，接力时必须同批更新：

- `quant-board/docs/architecture.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/frontend.md`
- 如 `database-migration-plan.md` 仍列 research 表结构或同步边界，也同步说明“回测归一化结果只属于 research SQLite，不进入 Supabase Free 版备份链路”。

文档同步最低要求：

- `architecture.md`：在 research SQLite 表清单中补充 `backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports`，并说明 `backtest_runs.result_json` 仍是兼容追溯字段。
- `api-cli.md`：补充 Phase 5 新端点的请求、响应和错误格式；说明旧 `GET /api/backtests/{run_id}` 保持兼容。
- `frontend.md`：补充报告页读取新端点的顺序和展示职责，强调 `finalSignal` 不是唯一交易结论。
- `database-migration-plan.md`：确认 Supabase schema 不包含这些 research 表；如该文档已有类似边界，只需加一句回测归一化结果仍保持 local-only。

建议逐文件补充内容：

1. `architecture.md`
   - 在“展示阶段”补充：新报告页优先从归一化表读取 `trades/equity/signals/quality`，`backtest_runs.result_json` 只作为兼容追溯和降级展示来源。
   - 在“本地主库与 Supabase 备份库”补充：`backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports` 和 `backtest_runs` 同属 research SQLite local-only。
   - 在“关键数据库表”新增四个归一化表的小节，写清主键、`backtest_run_id` 外键语义、保存内容和查询用途。
2. `api-cli.md`
   - 在“回测接口”补充五个新端点：`trades`、`equity`、`signals`、`quality`、`compare`。
   - 在“CLI 命令”补充 `compare-backtests`、`export-report`，并更新 `run-ranktrend` 输出摘要。
   - 在“验收清单”补充：归一化明细 API 与旧报告 API 必须能用同一 `runId` 读取。
3. `frontend.md`
   - 在“报告诊断展示”补充归一化 API 的读取顺序、失败降级和空状态。
   - 在“交易列表”补充字段来源：交易列表来自 `backtest_trades`，信号诊断来自 `backtest_signals`，两者不能混用。
   - 在“联调约定”补充：新增 API 必须有 TypeScript 类型，前端不重算核心指标。
4. `database-migration-plan.md`
   - 在“当前事实”或“存储拓扑”补充：回测归一化明细仍属于 research SQLite，不进入 Supabase 同构 schema、outbox、push/pull/failover 链路。
   - 如文档仍写 `sync_outbox` 覆盖回测、优化和 Golden，应改为当前口径：`sync_outbox` 只覆盖快照事实和数据集 bundle，研究结果 local-only。

Phase 4 文档同步完成后，应先做一次纯文档自检：

```powershell
rg -n "backtest_trades|backtest_equity_curve|backtest_signals|backtest_quality_reports|/api/backtests/.*/trades|compare-backtests|export-report|local-only|local_research_db_only" quant-board\docs
```

通过标准：

- 四张归一化表至少出现在 `architecture.md` 和本文。
- 五个新 API 至少出现在 `api-cli.md` 和本文。
- `compare-backtests`、`export-report` 至少出现在 `api-cli.md` 和本文。
- 所有涉及 Supabase 的文档都明确研究结果 local-only，不把回测归一化结果列入云端 schema 或 outbox。

### 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -x
```

通过标准：

- 新表由 `ResearchBase.metadata.create_all()` 创建。
- 旧 `GET /api/backtests/{run_id}` 仍返回兼容结果。
- 新数据可从归一化表查询交易、权益、信号和质量报告。
- 优化文档中的 trial `runId` 仍能追溯到完整回测报告。
- 四篇相关文档不存在互相冲突的 API 路径、字段名和 Supabase 备份口径。

---

## Phase 5: 扩展 API 与 CLI

**当前状态：未完成。`backend/main.py` 仍只有旧的 run/get/report 端点；`backend/cli.py` 仍只有 `run-ranktrend` 和 `show-report`，尚无 compare/export。**

### API

保留现有端点：

```text
POST /api/backtests/rank-trend
GET  /api/backtests/{run_id}
GET  /api/backtests/{run_id}/report
```

新增端点：

```text
GET  /api/backtests/{run_id}/trades
GET  /api/backtests/{run_id}/equity
GET  /api/backtests/{run_id}/signals?tier=A_MAIN&regime=advance&limit=200&offset=0
GET  /api/backtests/{run_id}/quality
POST /api/backtests/compare
```

建议实现位置：

- `backend/main.py`：新增路由，保持与现有 `get_backtest()` 同一文件风格。
- `backend/services.py`：在 `BacktestService` 增加读取和对比方法，API 层只负责 HTTP 错误映射。
- `backend/data/repository.py`：如果 API 需要分页和过滤，优先把 `limit`、`offset`、`tier`、`regime` 参数下推到查询层，避免大结果先全量加载再切片。

建议任务拆分：

1. Repository 查询能力
   - `get_backtest_trades(run_id, limit=100, offset=0)` 返回 `(items, total)` 或等价结构。
   - `get_backtest_signals(run_id, limit=200, offset=0, tier=None, regime=None)` 支持筛选并返回 total。
   - `get_backtest_equity_curve(run_id)` 保持全量升序返回，权益曲线通常用于图表，不分页。
   - `get_backtest_quality_report(run_id)` 返回兼容 API 字段结构；缺失时返回 `None`，由 service 映射为结构化错误。
   - 分页参数必须限制上限，建议 `1 <= limit <= 1000`，`offset >= 0`。
2. Service 编排
   - `get_run_or_raise(run_id)` 统一检查 run 是否存在，避免每个 API 重复拼错误。
   - `get_trades(run_id, limit, offset)`、`get_equity(run_id)`、`get_signals(run_id, limit, offset, tier, regime)`、`get_quality(run_id)` 只返回可 JSON 序列化对象。
   - `compare_runs(run_ids, metrics)` 从 `BacktestRun.result_json` 读取摘要指标，必须同时返回 `datasetId/snapshotType/strategyName/strategyVersion/configHash/randomSeed`。
   - `export_report(run_id)` 聚合旧报告和四类归一化明细，供 API 或 CLI 复用。
3. API 路由
   - 查询端点只接受 `GET`，对比使用 `POST /api/backtests/compare`。
   - 找不到 run 返回 404，`detail.code=backtest_run_not_found`。
   - 非法分页参数返回 422 或 400，但错误体必须结构化，至少包含 `code`、`field`、`value`。
   - 非法 metrics 返回 400，`detail.code=invalid_backtest_metric`，并列出允许的 metrics。
4. CLI
   - `run-ranktrend` 输出摘要应来自 service 返回结果，避免 CLI 自己重算。
   - `compare-backtests` 只做参数解析和格式化输出，不直连 repository。
   - `export-report` 只写用户显式给出的单个文件路径；如文件已存在，可以覆盖该明确文件，但必须打印 `output` 路径，不做目录清理。

允许的 compare metrics 首批建议固定为：

```text
totalReturn
realizedReturn
maxDrawdown
sharpe
winRate
totalTrades
profitFactor
openPositionCount
```

如果旧 `result_json` 中某个指标缺失，响应中该指标值用 `null`，同时在 run 项上增加 `missingMetrics`，不能用 `0` 代替。

建议响应合同：

`GET /api/backtests/{run_id}/trades`：

```json
{
  "runId": "bt_xxx",
  "items": [],
  "limit": 100,
  "offset": 0,
  "total": 0
}
```

`GET /api/backtests/{run_id}/equity`：

```json
{
  "runId": "bt_xxx",
  "items": []
}
```

`GET /api/backtests/{run_id}/signals`：

```json
{
  "runId": "bt_xxx",
  "items": [],
  "filters": {
    "tier": "A_MAIN",
    "regime": "advance"
  },
  "limit": 200,
  "offset": 0,
  "total": 0
}
```

`GET /api/backtests/{run_id}/quality`：

```json
{
  "runId": "bt_xxx",
  "qualityReport": {
    "passed": true,
    "severity": "pass",
    "researchGrade": "research_ready"
  }
}
```

`POST /api/backtests/compare` 请求：

```json
{
  "run_ids": ["bt_001", "bt_002"],
  "metrics": ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
}
```

`POST /api/backtests/compare` 响应：

```json
{
  "runs": [
    {
      "runId": "bt_001",
      "datasetId": "ds_001",
      "snapshotType": "half_hour",
      "strategyName": "rank_trend_candidate",
      "configHash": "abc123",
      "randomSeed": 20260430,
      "metrics": {
        "totalReturn": 0.12,
        "maxDrawdown": -0.08,
        "sharpe": 1.4,
        "winRate": 0.52
      }
    }
  ],
  "metrics": ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
}
```

失败响应必须包含结构化原因，例如：

```json
{
  "detail": {
    "code": "backtest_run_not_found",
    "runId": "bt_missing"
  }
}
```

分页和过滤错误示例：

```json
{
  "detail": {
    "code": "invalid_pagination",
    "field": "limit",
    "value": 5000,
    "message": "limit must be between 1 and 1000"
  }
}
```

metrics 错误示例：

```json
{
  "detail": {
    "code": "invalid_backtest_metric",
    "metric": "annualReturn",
    "allowedMetrics": ["totalReturn", "realizedReturn", "maxDrawdown", "sharpe", "winRate", "totalTrades", "profitFactor", "openPositionCount"]
  }
}
```

### CLI

增强 `run-ranktrend` 输出字段。当前命令参数已经比较完整，接力时优先调整输出摘要，不要改默认交易参数：

```text
backtest_id: bt_xxx
config_hash: abc123
quality_status: pass|warn|fail
quality_coverage: 0.95
total_return: 0.234
max_drawdown: -0.12
sharpe: 1.45
trade_count: 67
win_rate: 0.52
```

新增命令：

```powershell
python -m backend.cli compare-backtests --run-ids bt_001 bt_002 bt_003
python -m backend.cli export-report --run-id bt_001 --output quant-board/data/reports/bt_001.json
```

CLI 实现要求：

- `compare-backtests` 调用 `BacktestService.compare_runs()` 或等价 service 方法，不直接拼 repository 私有结构。
- `export-report` 默认导出完整报告 JSON，字段至少包括 `request`、`metrics`、`trades`、`equityCurve`、`signals`、`qualityReport`。
- 导出路径必须是用户显式传入的单个文件路径；不得批量清理或覆盖目录。
- 找不到 run 时返回非零退出码，并输出结构化错误摘要。

`export-report` JSON 建议结构：

```json
{
  "runId": "bt_001",
  "datasetId": "ds_001",
  "snapshotType": "half_hour",
  "strategyName": "rank_trend_candidate",
  "strategyVersion": "0.1.0",
  "configHash": "abc123",
  "randomSeed": 20260430,
  "request": {},
  "metrics": {},
  "trades": [],
  "equityCurve": [],
  "signals": [],
  "qualityReport": {},
  "exportedAt": "2026-05-04T00:00:00Z"
}
```

CLI 错误输出建议保持一行 JSON，便于脚本捕获：

```json
{"ok":false,"error":{"code":"backtest_run_not_found","runId":"bt_missing"}}
```

### 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_cli.py -v
.\.venv\Scripts\python.exe -m pytest tests/ -x
```

通过标准：

- 旧 API 和 CLI 仍可用。
- 新端点支持分页和过滤。
- CLI 导出的报告包含 request、metrics、trades、equityCurve、signals、qualityReport。
- `POST /api/optimizations/rank-trend` 生成的 trial `runId` 能通过新端点读取归一化结果。
- 找不到 run、非法分页参数、非法 metrics 名称均返回结构化错误。

---

## Phase 6: 前端报告增强

**当前状态：未完成。前端接力必须等 Phase 5 API 合同稳定后再做。**

### 目标

在 QuantBoard `frontend/` 中增强回测列表和回测详情。前端只消费 QuantBoard 后端 API，不直连 SQLite 或 Supabase。

### 改动范围

- `frontend/src/App.vue`：增强 Backtest 和 Report tabs，展示列表、详情、权益曲线、回撤、交易明细、信号解释、候选分层和质量面板。
- `frontend/src/types.ts`：新增 `BacktestSummary`、`BacktestDetail`、`BacktestTrade`、`BacktestSignal`、`BacktestQualityReport`。
- `frontend/src/api.ts`：新增 `fetchBacktestTrades()`、`fetchBacktestEquity()`、`fetchBacktestSignals()`、`fetchBacktestQuality()`、`compareBacktests()`。

建议页面数据流：

1. 用户在 Backtest tab 运行回测，仍调用 `POST /api/backtests/rank-trend`。
2. 取得 `runId` 后，Report tab 先调用 `GET /api/backtests/{run_id}` 读取兼容摘要。
3. 再并行调用 `trades`、`equity`、`signals`、`quality` 四个归一化端点。
4. 如果归一化端点失败，但旧报告仍存在，页面可以展示兼容摘要，同时标记“明细读取失败”，不能伪装完整报告。

建议组件拆分：

1. `BacktestRunPanel`
   - 保留现有回测表单和运行按钮。
   - 运行成功后只保存 `runId` 和摘要，不在表单组件里承载完整报告状态。
2. `BacktestReportPanel`
   - 负责按 `runId` 拉取兼容报告和归一化明细。
   - 维护 `loading/error/partial` 状态；任一明细端点失败时，显示部分可用状态。
3. `BacktestMetricStrip`
   - 展示核心指标和可复现字段。
   - `snapshot_type`、`strategy_version`、`config_hash`、`random_seed` 必须始终可见。
4. `BacktestQualityPanel`
   - 展示 `passed/severity/researchGrade/reasons/warnings/coverageRatio`。
   - `severity != pass` 时使用明显状态，不允许只显示绿色 passed 布尔值。
5. `BacktestTradeTable`
   - 只展示真实成交记录，来源为 `trades` 端点。
   - 支持本地排序；大分页先由后端分页控制。
6. `BacktestSignalTable`
   - 展示候选分层和解释，来源为 `signals` 端点。
   - 默认筛选 `A_MAIN`、`B_IGNITION` 可作为快捷筛选，但不能隐藏风险候选的入口。
7. `BacktestEquityChart`
   - 只消费 `equity` 端点。
   - 空数组时显示空状态，避免渲染异常。
8. `BacktestComparePanel`
   - 调用 `POST /api/backtests/compare`。
   - 不同 `snapshot_type`、`strategy_version`、`config_hash` 的 run 必须显示差异标签。

如果现有 `frontend/src/App.vue` 已经过大，Phase 6 应优先抽出上述组件；抽组件只限回测报告相关代码，不重构数据集、Golden 或优化页。

前端展示要求：

- 不把 `finalSignal` 作为唯一交易结论。
- 报告首屏显示 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- 数据质量为 degraded 或 failed 时，报告必须明显展示原因。
- `quarter_hour` 报告必须显示快照类型，避免和默认 `half_hour` 混淆。
- 权益曲线为空时展示空状态，不要让图表组件报错。
- 信号列表默认显示候选分层、信号、置信度、风险标记和解释原因；交易列表默认显示成交价格、持仓 bars、净收益和退出原因。
- 对比视图必须把不同 `snapshot_type` 或不同 `strategy_version` 的 run 明确标出来，避免横向比较误读。

前端类型最低合同：

```ts
export interface BacktestTrade {
  code: string
  name: string
  side: string
  entrySnapshotId?: string | null
  exitSnapshotId?: string | null
  entryTime?: number | null
  exitTime?: number | null
  entryPrice?: number | null
  exitPrice?: number | null
  quantity: number
  grossReturn?: number | null
  netReturn?: number | null
  profit?: number | null
  holdingBars?: number | null
  reason: string
  candidateTier?: string | null
  stage?: string | null
  regime?: string | null
}

export interface BacktestSignal {
  snapshotId: string
  code: string
  candidateTier?: string | null
  signal: string
  confidence?: number | null
  stage?: string | null
  regime?: string | null
  rank?: number | null
  reasons: string[]
  riskFlags: string[]
}
```

前端不得假设后端数值永远存在。展示前要统一格式化 `null/undefined/NaN/Infinity`，显示为 `--` 或结构化错误，不把异常数字传给图表。

### 验收

```powershell
cd quant-board/frontend
npm run build
```

建议补充：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -v
```

如需要联调：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd quant-board/frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

---

## 测试矩阵

当前 `quant-board/tests/` 仍以 `tests/test_quant_board.py` 综合测试为主。下面的拆分文件名是目标形态；接力时可以先在现有综合测试中补用例，等测试体量继续增大后再拆成专题测试文件。

### 单元测试

- `tests/test_metrics.py`：收益、最大回撤、夏普、空序列、单点序列。
- `tests/test_execution.py`：手续费、印花税、滑点、T+1、涨停不可买、跌停不可卖、成交量限制。
- `tests/test_quality.py`：空数据、NaN、Infinity、非正价格、负成交量、时间乱序、低覆盖率。
- `tests/test_strategy.py`：候选生成、候选分层、风险标记、解释字段稳定。
- `tests/test_repository.py`：归一化表写入、分页查询、旧 JSON blob 兼容读取。
- `tests/test_api.py`：归一化明细端点、分页过滤、结构化错误、compare 响应。
- `tests/test_cli.py`：`run-ranktrend` 输出、`compare-backtests`、`export-report`。

### Golden 与回归测试

- 沿用 `GoldenService.validate()` 验证 Python RankTrend 与 TypeScript golden 对齐。
- 固定 dataset、固定 `snapshot_type=half_hour`、固定 `random_seed=20260430`，比较 Phase 1 和 Phase 3A 前后的交易数量、总收益、最大回撤、权益曲线长度。
- 回归指标变化超过 5% 必须记录原因；Phase 1 和 Phase 3A 不允许发生指标变化。

### 集成测试

- SQLite 读快照。
- 质量门禁。
- 跑完整回测。
- 写 `backtest_runs` 和归一化结果表。
- API 查询。
- CLI 导出报告。
- 优化 trial 的 `runId` 能继续追溯报告。
- 前端 build 通过，报告页能在空明细、降级质量、不同 snapshot_type 情况下稳定渲染。

---

## 文件改动清单

### 新建

已完成：

1. `backend/core/backtest/__init__.py`
2. `backend/core/backtest/config.py`
3. `backend/core/backtest/strategy.py`
4. `backend/core/backtest/metrics.py`
5. `backend/core/backtest/evaluator.py`
6. `backend/core/backtest/execution.py`
7. `backend/core/backtest/engine.py`
8. `backend/core/backtest/models.py`
9. `backend/core/backtest/orders.py`
10. `backend/core/backtest/portfolio.py`
11. `backend/core/backtest/risk.py`
12. `backend/core/backtest/quality.py`

Phase 5/6 可能需要新增：

1. `tests/test_api.py` 或继续扩展 `tests/test_quant_board.py`
2. `tests/test_cli.py` 或继续扩展 `tests/test_quant_board.py`
3. 前端若现有 `App.vue` 继续膨胀，可新增就近组件，例如 `frontend/src/components/BacktestReport.vue`；新增前先检查当前前端结构。

### 修改

已完成或已有基础：

1. `backend/core/backtest.py`：已按 Phase 1 规则迁移为 `backend/core/backtest_legacy.py`，不能作为同名包兼容层。
2. `backend/data/models.py`：已新增归一化回测表，增强 `BacktestRun`。
3. `backend/data/quality_gate.py`：已增强质量门禁 stats。
4. `backend/data/repository.py`：已新增归一化结果存取方法。
5. `backend/services.py`：`BacktestService` 已双写结果并返回兼容摘要。

下一步修改：

1. `backend/main.py`：新增回测明细 API 和 compare API。
2. `backend/cli.py`：增强输出，新增 compare/export。
3. `backend/services.py`：补 `BacktestService` 明细读取、分页过滤和 compare/export 编排方法。
4. `backend/data/repository.py`：按 API 需要补分页、过滤和 total count。
5. `frontend/src/App.vue`、`frontend/src/types.ts`、`frontend/src/api.ts`：报告页增强。
6. `docs/architecture.md`、`docs/api-cli.md`、`docs/frontend.md`：同步 schema、API、前端合同。
7. `docs/database-migration-plan.md`：仅在文档涉及 research schema 或同步边界时更新。

### 不动

- 根项目 `src/`。
- `backend/analysis/ranktrend.py` 的 golden 算法核心。
- `backend/optimization/**` 的搜索逻辑。优化模块只消费回测引擎，不把搜索逻辑塞进 `backend.core.backtest`。
- `backend/data/supabase_homomorphic.py`。回测归一化结果不进入 Supabase Free 版备份链路。

---

## 实施顺序

1. 已完成 Phase 1：模块化重构，零行为变化。
2. 已完成 Phase 2：增强质量门禁，保证结构化失败。
3. 已完成 Phase 3A：新增策略解释，不改变撮合。
4. 已完成 Phase 4 后端核心：归一化 research SQLite 存储，保留 JSON blob。
5. 下一步 Phase 4 文档同步：补 `architecture.md`、`api-cli.md`、`frontend.md`，必要时补 `database-migration-plan.md`。
6. 下一步 Phase 5：扩展 API 和 CLI。
7. 下一步 Phase 6：增强 QuantBoard 前端报告。
8. 未来 Phase 3B：可选，增加 `useStrategyDecisionForExecution` 并显式启用策略决策驱动撮合。

每个 Phase 完成后必须运行对应测试和 `.\.venv\Scripts\python.exe -m pytest tests/ -x`。如果环境缺少样本 dataset，记录无法运行 `run-ranktrend` 的原因，并至少完成可运行的单元测试、导入检查和静态检查。

接力执行时的最小验证基线：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/ -x
```

触碰 API/CLI 时补：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m py_compile backend\main.py backend\cli.py backend\services.py backend\data\repository.py
```

触碰前端时补：

```powershell
cd quant-board/frontend
npm run build
```
