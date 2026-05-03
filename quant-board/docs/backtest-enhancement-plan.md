# RankTrend 回测系统增强实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. 本文是实施蓝图，执行时按 Phase 顺序推进，每个 Phase 结束后必须验证再进入下一步。

**Goal:** 将 QuantBoard 当前单体化 RankTrend 回测模块拆分为可维护的模块化回测包，并在不破坏现有 API、CLI、优化链路和前端调用的前提下，增强质量门禁、策略解释、归一化结果存储和报告能力。

**Architecture:** 回测、优化、交易模拟和报告展示只在 `quant-board/` 内演进。`backend/core/backtest.py` 当前是约 1190 行单体模块，首步先拆成 `backend/core/backtest/` 包，并由包内 `__init__.py` 负责兼容导出。后续增强必须保持现有 `POST /api/backtests/rank-trend`、`run-ranktrend`、优化 trial 调用回测引擎的主链不变。

**Tech Stack:** Python 3、FastAPI、SQLAlchemy、SQLite research DB、Vue 3 QuantBoard frontend、pytest。

---

## 0. 当前事实与硬约束

- 当前回测入口是 `backend/core/backtest.py`，公开符号包括 `DEFAULT_TRADE_CONFIG`、`STRATEGY_DEFINITIONS`、`OutcomeEvaluator`、`TradeSimulator`、`BacktestEngine`、`Optimizer`。
- 当前 API 是 `POST /api/backtests/rank-trend`、`GET /api/backtests/{run_id}`、`GET /api/backtests/{run_id}/report`，不得误写为 `POST /api/backtests`。
- 当前 CLI 是 `python -m backend.cli run-ranktrend`，优化模块会调用 `BacktestService.run_ranktrend()` 产生 trial 回测结果。
- `BacktestRun` 当前只保存 `request_json` 和 `result_json` 等少量字段；新增归一化结果表属于 research SQLite，不进入 Supabase Free 版备份链路。
- 默认 `snapshot_type` 保持 `half_hour`；`quarter_hour` 只能由用户显式选择。
- 每次回测和优化 trial 必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- Dragon Board 根项目 `src/` 完全不动；回测、优化、交易模拟和报告展示不回流到根项目。
- 不批量删除文件或目录。若需要处理旧 `backend/core/backtest.py`，只能按单个明确路径操作，并先确认替代导入已经通过测试。

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

新增 repository 方法：

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

### 文档同步

Phase 4 修改 research SQLite schema 和 API/CLI 合同，实施时必须同批更新：

- `quant-board/docs/architecture.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/frontend.md`
- 如 `database-migration-plan.md` 仍列 research 表结构或同步边界，也同步说明“回测归一化结果只属于 research SQLite，不进入 Supabase Free 版备份链路”。

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

---

## Phase 5: 扩展 API 与 CLI

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

`POST /api/backtests/compare` 请求：

```json
{
  "run_ids": ["bt_001", "bt_002"],
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

### CLI

增强 `run-ranktrend` 输出字段：

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

---

## Phase 6: 前端报告增强

### 目标

在 QuantBoard `frontend/` 中增强回测列表和回测详情。前端只消费 QuantBoard 后端 API，不直连 SQLite 或 Supabase。

### 改动范围

- `frontend/src/App.vue`：增强 Backtest 和 Report tabs，展示列表、详情、权益曲线、回撤、交易明细、信号解释、候选分层和质量面板。
- `frontend/src/types.ts`：新增 `BacktestSummary`、`BacktestDetail`、`BacktestTrade`、`BacktestSignal`、`BacktestQualityReport`。
- `frontend/src/api.ts`：新增 `fetchBacktestTrades()`、`fetchBacktestEquity()`、`fetchBacktestSignals()`、`fetchBacktestQuality()`、`compareBacktests()`。

前端展示要求：

- 不把 `finalSignal` 作为唯一交易结论。
- 报告首屏显示 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- 数据质量为 degraded 或 failed 时，报告必须明显展示原因。
- `quarter_hour` 报告必须显示快照类型，避免和默认 `half_hour` 混淆。

### 验收

```powershell
cd quant-board/frontend
npm run build
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

### 单元测试

- `tests/test_metrics.py`：收益、最大回撤、夏普、空序列、单点序列。
- `tests/test_execution.py`：手续费、印花税、滑点、T+1、涨停不可买、跌停不可卖、成交量限制。
- `tests/test_quality.py`：空数据、NaN、Infinity、非正价格、负成交量、时间乱序、低覆盖率。
- `tests/test_strategy.py`：候选生成、候选分层、风险标记、解释字段稳定。
- `tests/test_repository.py`：归一化表写入、分页查询、旧 JSON blob 兼容读取。

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

---

## 文件改动清单

### 新建

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

### 修改

1. `backend/core/backtest.py`：只按 Phase 1 规则作为迁移源处理，不能作为同名包兼容层。
2. `backend/data/models.py`：新增归一化回测表，增强 `BacktestRun`。
3. `backend/data/quality_gate.py`：增强质量门禁 stats。
4. `backend/data/repository.py`：新增归一化结果存取方法。
5. `backend/services.py`：`BacktestService` 双写结果并返回兼容摘要。
6. `backend/main.py`：新增回测明细 API。
7. `backend/cli.py`：增强输出，新增 compare/export。
8. `frontend/src/App.vue`、`frontend/src/types.ts`、`frontend/src/api.ts`：报告页增强。
9. `docs/architecture.md`、`docs/api-cli.md`、`docs/frontend.md`：同步 schema、API、前端合同。
10. `docs/database-migration-plan.md`：仅在文档涉及 research schema 或同步边界时更新。

### 不动

- 根项目 `src/`。
- `backend/analysis/ranktrend.py` 的 golden 算法核心。
- `backend/optimization/**` 的搜索逻辑。优化模块只消费回测引擎，不把搜索逻辑塞进 `backend.core.backtest`。
- `backend/data/supabase_homomorphic.py`。回测归一化结果不进入 Supabase Free 版备份链路。

---

## 实施顺序

1. Phase 1：模块化重构，零行为变化。
2. Phase 2：增强质量门禁，保证结构化失败。
3. Phase 3A：新增策略解释，不改变撮合。
4. Phase 4：归一化 research SQLite 存储，保留 JSON blob。
5. Phase 5：扩展 API 和 CLI。
6. Phase 6：增强 QuantBoard 前端报告。
7. Phase 3B：可选，增加 `useStrategyDecisionForExecution` 并显式启用策略决策驱动撮合。

每个 Phase 完成后必须运行对应测试和 `.\.venv\Scripts\python.exe -m pytest tests/ -x`。如果环境缺少样本 dataset，记录无法运行 `run-ranktrend` 的原因，并至少完成可运行的单元测试、导入检查和静态检查。
