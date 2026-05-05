# 题材模块 V12：ThemeTrend 量化研究平台化合同

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Dragon Board 题材运行态沉淀为 QuantBoard 可复现的 ThemeTrend 研究链，支持题材趋势分析、题材共振回测、参数优化和报告读取。

**Architecture:** ThemeTrend 与 RankTrend 并列作为 QuantBoard 研究链：RankTrend 继续消费股票快照序列，ThemeTrend 消费标准快照中的题材/板块行、股票行和 `themeDATA.db` 基础映射。研究结果只写入 `quant_board_research.db`，本轮不进入 Supabase；`themeDATA.db` 只承载题材基础映射，不承载回测、优化或运行态因子事实。

**Tech Stack:** Python FastAPI、SQLite research DB、现有 QuantBoard backtest/optimization 服务层、pytest、Dragon Board Vue 前端只读展示和快照供给。

---

## 当前口径

- V12 是“目标/新增合同/首批落地”文档，不代表所有实现已经完成。
- Dragon Board 不新增回测平台，不在根项目 `src/**` 承载 ThemeTrend 回测、优化、交易模拟或研究报告。
- ThemeTrend 研究主链落在 `quant-board/**`；根前端只继续提供实时看板、快照数据、题材基础展示和必要的结果读取入口。
- RankTrend 与 ThemeTrend 并列，但不能互相替代：RankTrend 仍是个股候选趋势链，ThemeTrend 是题材强度、扩散、持续性、拥挤和共振链。
- `themeDATA.db` 是题材基础映射事实源，只保存题材、股票关系、标签和原因；ThemeTrend 计算输出、回测 run、优化 run、signals、trades、quality report 进入 research SQLite。
- 本轮 ThemeTrend 研究结果不进入 Supabase，不写 `sync_outbox`，不触发 push/pull/failover。

## 默认参数合同

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `snapshotType` | `half_hour` | 与 RankTrend 默认一致，`quarter_hour` 必须显式传入 |
| `strategyName` | `theme_trend_candidate` | 纯 ThemeTrend 题材趋势策略 |
| `confluenceStrategyName` | `theme_confluence_candidate` | RankTrend + ThemeTrend 共振策略 |
| `strategyVersion` | `0.1.0` | 首批研究版本，写入 run 记录 |
| `randomSeed` | `20260430` | 优化和抽样必须可复现 |
| `lookbackBars` | `8` | 题材趋势强度观察窗口 |
| `persistenceBars` | `3` | 连续活跃确认窗口 |
| `breadthMinStocks` | `5` | 题材有效扩散最小股票数 |
| `minThemeCoverage` | `0.7` | 题材基础映射覆盖率门禁 |
| `minSnapshotCount` | `30` | 回测/优化最小快照数 |
| `maxThemeCrowding` | `0.85` | 拥挤风险上限，超过后降级 |
| `themeWeight` | `0.35` | 共振策略中 ThemeTrend 辅助权重 |
| `rankTrendWeight` | `0.65` | 共振策略中 RankTrend 主权重 |
| `initialCash` | `1000000` | 沿用 QuantBoard 回测默认 |
| `maxPositions` | `5` | 沿用短线研究默认 |
| `positionSize` | `0.2` | 沿用短线研究默认 |
| `targetHoldingDays` | `5` | 沿用短线研究默认 |
| `maxHoldingBars` | `40` | 沿用短线研究默认 |

## 质量门禁

- 数据集必须包含 `dataset_id`、`snapshot_type`、日期区间和稳定排序的快照序列。
- `snapshot_type` 默认只能是 `half_hour`；`quarter_hour`、`hourly`、`daily` 必须由 API/CLI 显式指定。
- 快照数量少于 `minSnapshotCount` 时返回结构化失败：`code=THEME_TREND_SAMPLE_TOO_SMALL`。
- 题材基础映射覆盖率低于 `minThemeCoverage` 时返回结构化失败：`code=THEME_MAPPING_COVERAGE_LOW`。
- 题材行、股票行或时间戳乱序时必须记录 `severity=fail|warn` 和具体 `snapshot_id`，不能静默跳过后返回成功。
- NaN、缺字段、空题材、非法股票代码必须显式归一化或作为质量原因输出。
- 共振策略不得让 ThemeTrend 独立制造买入信号；ThemeTrend 只能辅助已有 RankTrend 候选分层、解释和风险降级。
- 优化结果只生成候选参数，不自动写回 Python 默认值、TypeScript 默认值、API、CLI、前端表单或文档默认值。

## V12-A：ThemeTrend Python 引擎 MVP

**Files:**
- Create: `quant-board/backend/analysis/theme_trend.py`
- Test: `quant-board/tests/test_theme_trend_engine.py`

- [ ] 定义输入输出合同：输入为标准快照序列、题材基础映射和运行参数；输出包含 `themeId`、`themeName`、`trendScore`、`breadthScore`、`persistenceScore`、`crowdingScore`、`riskFlags`、`quality`。
- [ ] 先写 pytest，覆盖空快照、低样本量、缺题材映射、NaN、时间乱序和正常题材趋势排序。
- [ ] 实现最小 ThemeTrend 引擎，保证同一输入、同一参数、同一 `randomSeed` 输出稳定。
- [ ] 输出字段使用 snake_case 入库、API 响应由适配层转 camelCase；不得依赖 Dragon Board 浏览器全局对象。
- [ ] 验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_trend_engine.py -q
```

## V12-B：ThemeTrend 研究存储和质量报告

**Files:**
- Modify: `quant-board/backend/data/**`
- Modify: `quant-board/backend/services/**`
- Test: `quant-board/tests/test_theme_trend_storage.py`

- [ ] 复用 `quant_board_research.db` 保存 ThemeTrend 研究结果，不新增 Supabase 同步对象。
- [ ] 首批可复用 `backtest_runs`、`backtest_signals`、`backtest_quality_reports` 等归一化表，通过 `strategy_name=theme_trend_candidate|theme_confluence_candidate` 区分研究链。
- [ ] 如果需要新增表，只能新增 research SQLite 表，并在 architecture/api-cli 文档同批更新；不得写入 `themeDATA.db`。
- [ ] 质量报告必须包含 `passed`、`severity`、`researchGrade`、`reasons[]`、`coverage`、`sampleCount`、`themeCoverage`。
- [ ] 验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_trend_storage.py -q
```

## V12-C：API 和 CLI 合同首批落地

**Files:**
- Modify: `quant-board/backend/api/**`
- Modify: `quant-board/backend/cli/**`
- Test: `quant-board/tests/test_theme_trend_api.py`
- Test: `quant-board/tests/test_theme_trend_cli.py`

- [ ] 新增拟定 API：`POST /api/backtests/theme-trend`，运行纯 ThemeTrend 回测。
- [ ] 新增拟定 API：`POST /api/backtests/theme-confluence`，运行 RankTrend + ThemeTrend 共振回测。
- [ ] 新增拟定 API：`POST /api/optimizations/theme-trend`，启动 ThemeTrend 参数优化。
- [ ] 新增拟定 API：`POST /api/optimizations/theme-confluence`，启动共振策略参数优化。
- [ ] 新增 CLI：`run-theme-trend`、`run-theme-confluence`、`optimize-theme-trend`、`optimize-theme-confluence`。
- [ ] API/CLI 必须写入 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- [ ] 验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_trend_api.py tests/test_theme_trend_cli.py -q
```

## V12-D：回测、共振策略和优化

**Files:**
- Modify: `quant-board/backend/core/**`
- Modify: `quant-board/backend/optimization/**`
- Test: `quant-board/tests/test_theme_confluence_backtest.py`
- Test: `quant-board/tests/test_theme_trend_optimization.py`

- [ ] 纯 ThemeTrend 策略只生成题材层信号、候选股票解释和风险提示；实际成交仍走统一回测引擎。
- [ ] 共振策略以 RankTrend 候选为主，ThemeTrend 只调整候选优先级、置信度和拥挤风险，不独立制造买入。
- [ ] 优化目标首批支持 `stability`、`totalReturn`、`maxDrawdown`、`profitFactor`，默认 `stability`。
- [ ] 优化方法沿用 `grid`、`random`、`bayesian`、`tpe`；固定 `randomSeed` 时结果可复现。
- [ ] 验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_confluence_backtest.py tests/test_theme_trend_optimization.py -q
```

## V12-E：报告展示和文档验收

**Files:**
- Modify: `quant-board/frontend/**` 或后续明确的报告页面文件
- Modify: `docs/theme-module/README.md`
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`

- [ ] 报告展示必须区分 RankTrend 信号、ThemeTrend 题材趋势、共振解释、质量门禁和真实成交。
- [ ] 前端不得把 `finalSignal` 或题材趋势分数当作唯一交易结论。
- [ ] 文档统一使用“V12 目标/新增合同/首批落地”措辞，不夸大为已完成实现。
- [ ] 验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

## API/CLI 首批请求示例

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "strategyName": "theme_trend_candidate",
  "strategyVersion": "0.1.0",
  "randomSeed": 20260430,
  "lookbackBars": 8,
  "persistenceBars": 3,
  "breadthMinStocks": 5,
  "minThemeCoverage": 0.7,
  "maxThemeCrowding": 0.85
}
```

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli run-theme-trend `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --seed 20260430 `
  --lookback-bars 8 `
  --persistence-bars 3
```

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli optimize-theme-confluence `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --method bayesian `
  --objective stability `
  --trials 36 `
  --seed 20260430
```

## 总体验证命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_trend_engine.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

## 风险与处理

- 风险：`themeDATA.db` 基础映射覆盖不足，导致 ThemeTrend 质量门禁失败。
  - 处理：先运行题材迁移校验和 `GET /api/themes/counts`，缺口通过后端导入修正，不从前端写 IndexedDB。
- 风险：共振策略被误用为 ThemeTrend 独立买入信号。
  - 处理：API、CLI、报告和 signals 明确输出 RankTrend 候选来源与 ThemeTrend 辅助原因。
- 风险：研究结果误进入 Supabase。
  - 处理：V12 首批只写 research SQLite；同步接口返回 `research.policy=local_research_db_only`。
- 风险：默认参数被优化结果污染。
  - 处理：优化 run 只保存候选排名；任何默认值变更必须另开任务、同步文档和测试。
- 风险：Dragon Board 根项目被扩展成回测平台。
  - 处理：根项目只做实时看板和结果读取；回测、优化、交易模拟、报告主链留在 QuantBoard。
