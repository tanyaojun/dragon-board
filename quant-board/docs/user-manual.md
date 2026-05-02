# QuantBoard 操作手册

本文按当前轻实验台界面说明日常用法。QuantBoard 的核心流程是：先导入或选择数据集，再跑 RankTrend 回测，再查看报告，最后再做参数优化。Golden 对齐是开发验收工具，不是每天研究股票必须执行的第一步。

回测统一口径详见 [backtest-policy.md](backtest-policy.md)。如果页面、报告和本文说明不一致，以该口径文档为准。

## 1. 启动服务

推荐从 `DragonBoardLauncher` 启动：

1. 打开 DragonBoardLauncher。
2. 点击 `Start All`，或分别启动 `QuantBoard API` 和 `QuantBoard UI`。
3. 看到这两个服务为 `Running` 后，在浏览器打开 `http://127.0.0.1:5174`。

也可以手动启动：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

另开一个 PowerShell：

```powershell
cd d:\dragon-board\quant-board\frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

打开页面后，右上角显示 `API ok` 表示后端可用。

## 2. 选择数据集

左侧 `数据集` 区域是后续所有操作的入口。

1. 点击 `刷新`。
2. 在下拉框选择一个数据集。
3. 选中后会显示 `ID`、日期区间、快照数、股票行数。

选中数据集后，页面会自动把 `datasetId` 填到回测、优化和 Golden 表单里。日常操作不需要手动复制 ID。

## 3. 导入真实数据

当前页面左侧的 `当前页面预览` 只是浏览器同源诊断工具。你在 `127.0.0.1:5174` 打开 QuantBoard 时，它只能读取这个地址自己的 IndexedDB，不能直接读取 DragonBoard 页面 `127.0.0.1:5173` 的 IndexedDB。所以提示 `数据库 DragonBoardData 不存在或版本不可读` 是正常现象，不代表后端数据坏了。

真实导入优先用页面里的 `运行页桥接`。这条链路不需要导出 JSON，也不需要找浏览器 profile 路径：QuantBoard 会打开或复用 `localhost:5173` 的 DragonBoard 运行页，由 DragonBoard 页面在自己的 origin 下读取 `DragonBoardData`，再把结构化快照传给 QuantBoard 后端入库。

### 3.1 运行页桥接导入

这是当前推荐方式。

前提：

- DragonBoard 正在 `http://localhost:5173` 运行；
- QuantBoard 正在 `http://localhost:5174` 运行；
- 刷新一次 DragonBoard 页面，确保运行页已加载 QuantBoard bridge。

操作：

1. 左侧 `数据导入` 选择 `运行页桥接`。
2. `数据源路径 / URL` 填 `http://localhost:5173`。
3. `数据库名` 保持 `DragonBoardData`。
4. `snapshotType` 选择 `half_hour`。
5. `预览采样` 表示最多读取多少个快照，默认 `500`。
6. 需要试跑时勾选 `dry run`；正式写入时取消勾选。
7. 点击 `提交导入`。

浏览器可能会打开或切到一个 `localhost:5173` 标签页，这是桥接需要的运行页引用。导入成功后，左侧数据集会自动刷新。

### 3.2 页面 JSON 文件上传

如果你已经有从 DragonBoard 导出的快照 JSON：

1. 左侧 `数据导入` 选择 `JSON 文件上传`。
2. 选择 JSON 文件。
3. `snapshotType` 选择 `half_hour`。
4. 需要试跑时勾选 `dry run`；正式写入时取消勾选。
5. 点击 `提交导入`。
6. 导入成功后，左侧数据集会自动刷新。

### 3.3 CLI JSON 快照包导入

如果你已经有从 DragonBoard 导出的快照 JSON：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli import-idb `
  --source json_bundle `
  --path d:\path\to\snapshot-bundle.json `
  --name "2026-04 half_hour" `
  --snapshot-type half_hour
```

导入成功后刷新页面左侧数据集。

### 3.4 后端历史迁移 API

如果是在做 IndexedDB 历史资产迁移，优先用后端迁移入口。它可以固定 `datasetId`，支持 dry run，并且会把正式写入纳入 SQLite + Supabase 备份同步链。

先试跑：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/migrations/snapshots/import-json `
  -ContentType 'application/json' `
  -Body (@{
    datasetId = 'dragonboard_history'
    sourcePath = 'd:/exports/dragonboard-v4.json'
    name = 'DragonBoard history'
    dryRun = $true
  } | ConvertTo-Json -Depth 20)
```

确认 `report.scanned`、`report.imported`、`report.skipped` 无异常后，把 `dryRun` 改为 `$false` 正式导入。重复执行同一批数据会跳过已存在快照，不应产生重复行。

### 3.5 浏览器桥接导入

如果 DragonBoard 正在 `http://localhost:5173` 运行，可以尝试：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli import-idb `
  --source browser_bridge `
  --path http://localhost:5173 `
  --name "DragonBoard browser bridge" `
  --snapshot-type half_hour
```

首次使用 Playwright 可能需要安装浏览器：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

注意：Playwright 默认启动的是新的浏览器上下文，不一定能读取你日常 Chrome/Edge profile 里的 IndexedDB。如果返回空快照，改用 JSON 文件上传或 LevelDB。

### 3.6 LevelDB 导入

在 `quant-board/config/data_sources.yaml` 填好 Chrome 或 Edge profile 下的 IndexedDB `.leveldb` 路径后：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli import-idb `
  --source leveldb `
  --name "DragonBoard leveldb" `
  --snapshot-type half_hour
```

LevelDB 导入会先复制源目录到 `quant-board/data/staging/`，不会直接操作浏览器原始数据。

LevelDB 直读依赖是可选项：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pip install -r requirements-leveldb.txt
```

Windows + Python 3.13 下该依赖可能需要 Microsoft C++ Build Tools。如果安装失败，不影响 JSON 文件上传和普通回测。

## 4. 跑 RankTrend 回测

页面操作：

1. 左侧选择数据集。
2. 点击上方 `回测运行`。
3. 确认 `snapshotType` 为 `half_hour`。
4. 保持默认参数先跑一版：
   - `strategyName`: `rank_trend_candidate`
   - `randomSeed`: `20260430`
   - `initialCash`: `1000000`
   - `maxPositions`: `5`
   - `targetHoldingDays`: `5`
   - `maxHoldingBars`: `40`
   - `executionMode`: `current_bar`
   - `takeProfitPct`: `0.12`
   - `stopLossPct`: `0.06`
   - `macdFast/macdSlow/macdSignal`: `21/34/13`
5. 点击 `启动回测`。

`strategyName` 现在不是备注字段，会真实控制后端交易模拟的入场策略。页面提供固定下拉选项：

- `rank_trend_candidate`：默认正式策略，买入 `A_MAIN` 与连续确认后的 `B_IGNITION`；
- `hot_top10`：只按热榜前 10 入场；
- `a_main_only`：只买 `A_MAIN`；
- `b_ignition_only`：只买连续确认后的 `B_IGNITION`；
- `a_b_combined`：显式 A+B 对照口径。

成功后 JSON 里会出现 `runId`、`totalReturn`、`maxDrawdown`、`winRate`、`tradeCount`、`equityCurve`、`trades`、`signals` 等字段。

当前默认交易模拟口径是短线 5 天持仓周期。半小时快照下 `maxHoldingBars=40`，同时启用 A 股 T+1、100 股手数、手续费、印花税、滑点、涨跌停可成交检查、盘口价优先和容量约束。报告里的 `totalReturn` 包含未平仓市值，`realizedReturn` 只统计已平仓交易，`openPositions` 展示未平仓持仓。

`executionMode` 控制信号和成交的时点：

- `current_bar`：默认兼容口径，当前快照产生信号并在当前快照撮合。
- `next_bar`：保守口径，当前快照信号在下一快照撮合；成交价、涨跌停和容量约束都使用下一快照行情。报告会保留 `signalSnapshotId`，用于区分信号时点和成交时点。

如果导入数据里有 `ask1Price` / `bid1Price`、盘口量、成交量、盘中 `high` / `low` 或涨跌停字段，撮合会优先使用这些字段；字段缺失时会回退到快照价加滑点，并在报告的 `撮合诊断` 中显示回退比例和 warning。

报告页会拆分未平仓口径：

- `持仓盯市盈亏`：当前市值减买入总成本，已经包含买入手续费和买入滑点影响。
- `预估平仓成本`：按当前市值估算卖出手续费和印花税。
- `预估平仓后盈亏`：持仓盯市盈亏再扣预估平仓成本，是更保守的未平仓盈亏口径。

回测运行页默认 MACD 参数为 `21/34/13`。当前 RankTrend 实现中，MACD 最低在 `macdSlow=34` 个半小时 bars 后开始计算；更合理的 DEA 稳定观察口径是 `macdSlow + macdSignal = 47` 个半小时 bars，约 5.9 个交易日。

MACD 金叉/死叉只作为入场前的辅助观察信号，不是独立买卖触发器。实际买卖依据仍然是多周期动量、生命周期阶段、A/B/C/D/N 分层、市场环境、风险压力、排名变化和交易风控规则。

## 回测报告新增诊断

重新运行回测后，回测报告页会展示：

- `对照组回测`：热榜 Top10、A_MAIN only、B_IGNITION only、A+B，用于判断当前正式策略是否优于朴素规则；
- `样本与 MACD 诊断`：快照数、技术最小 bars、MACD 最小 bars、稳定观察 bars、样本 OK 占比；
- `数据质量结论`：是否存在低热榜快照、空热榜剔除数、实际运行快照数、样本 OK 占比、热榜行数均值和本次结果的研究等级；
- `交易贡献分析`：按出场原因和 RankTrend 分层汇总交易次数、利润、均值和胜率；
- JSON 结果右上角仍可一键复制，方便贴给 AI 分析。

`数据质量结论` 中的 `degraded` 不代表回测失败，意思是数据可用于候选观察，但不适合作为严格验收或直接定参数依据。常见原因包括低热榜快照、空热榜快照被运行时剔除、样本 OK 占比偏低、MACD 稳定观察窗口不足。

这些诊断只帮助复盘，不会改变 RankTrend 策略算法。

CLI 等价命令：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli run-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --strategy-name rank_trend_candidate `
  --seed 20260430 `
  --initial-cash 1000000 `
  --max-positions 5 `
  --position-size 0.2 `
  --execution-mode next_bar `
  --target-holding-days 5 `
  --max-holding-bars 40 `
  --take-profit-pct 0.12 `
  --stop-loss-pct 0.06 `
  --macd-fast 21 `
  --macd-slow 34 `
  --macd-signal 13 `
  --momentum-periods 3,5,8,13,21
```

回测 CLI 已暴露 UI 的主要研究参数：

| 类别 | 参数 |
| --- | --- |
| 数据范围 | `--start-date`、`--end-date` |
| 策略指标 | `--macd-fast`、`--macd-slow`、`--macd-signal`、`--momentum-periods`、`--horizons` |
| 仓位与持有 | `--initial-cash`、`--max-positions`、`--position-size`、`--target-holding-days`、`--max-holding-bars` |
| 风控 | `--take-profit-pct`、`--stop-loss-pct` |
| 成本 | `--fee-rate`、`--stamp-tax-rate`、`--slippage-rate` |
| 成交口径 | `--execution-mode`、`--no-t1`、`--no-order-book-price`、`--no-limit-status`、`--no-volume-limit`、`--no-order-book-queue`、`--no-partial-fills`、`--volume-participation-rate`、`--order-book-participation-rate`、`--no-intrabar-stops`、`--intrabar-ambiguity` |

`--execution-mode next_bar` 是更保守的成交口径：当前快照产生信号，下一可用快照尝试成交。若需要复现早期研究口径，可使用默认的 `current_bar`。

## 5. 查看回测报告

页面操作：

1. 回测完成后点击 `查看报告`。
2. 如果输入框里已有 backtest id，点击 `拉取报告`。
3. 查看核心指标：
   - `总收益`
   - `最大回撤`
   - `胜率`
   - `交易数`
4. 下方 JSON 是完整报告，可查看 `distribution`、`forwardValidation`、`tradeSimulation`。
5. `撮合诊断` 展示买卖尝试、未成交订单、盘口覆盖率、快照价回退率和未成交原因。它用于判断本次回测到底用了多少真实盘口约束。

如果刚跑完回测但报告页为空，回到 `回测运行` 复制返回结果里的 `runId`，粘贴到报告页输入框，再点 `拉取报告`。

CLI 查看报告：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli show-report --run-id bt_xxx
```

## 6. 单票回放

页面操作：

1. 先完成一次回测，并确保报告页能拉到数据。
2. 点击 `单票回放`。
3. 输入股票代码，例如 `600001`。
4. 点击 `刷新报告源`。

表格会按该股票过滤回测报告里的交易、信号或决策信息。代码为空时展示报告里可用的全部回放步骤。

单票回放中的 `时间` 会转成人可读日期时间，`价格` 保留 2 位小数。`解释` 会优先展示交易事件里的 RankTrend 细节，包括候选池分层、生命周期阶段、市场环境、技术信号、动量结构、风险压力和入场/退出原因。

## 7. 参数优化

参数优化建议在确认某个数据集能正常回测后再使用。

页面操作：

1. 左侧选择数据集。
2. 点击 `参数优化`。
3. 选择搜索方式：
   - `grid`：穷举参数组合，适合首轮小范围验证。
   - `random`：随机抽样，适合组合较多时快速探索。
   - `bayesian`：使用 Optuna `TPESampler` 做 TPE 贝叶斯优化，固定 `randomSeed` 时可复现。
4. 选择目标函数：
   - `stability`：默认推荐，优先看 validation，并惩罚样本内外落差和验证交易数过少。
   - `risk_adjusted`：收益、回撤、Sharpe 的综合分。
   - `sharpe`：偏向收益/回撤平衡。
   - `return`：偏向总收益。
   - `max_drawdown`：偏向控制回撤。
   - `win_rate`：偏向胜率，但会惩罚交易数过少。
5. `validation` 默认使用 `auto`，会按时间把后段样本作为 validation。只想快速试跑时可改为 `none`，但结果会标记为高过拟合风险。
6. 可勾选 `walk-forward` 做按交易日滚动验证。它会在 Top trials 中逐段重选，并输出分段 validation 表现。
7. 设置 `trials`，首次建议 `12` 到 `36`。
8. 参数列表用英文逗号分隔，例如：
   - `momentumWindow`: `6,8,10`
   - `takeProfitPct`: `0.08,0.12,0.16`
   - `stopLossPct`: `0.04,0.06,0.08`
   - `maxPositions`: `3,5,8`
9. 点击 `启动优化`。

返回结果里重点看：

- `runId`：优化任务 ID。
- `experiment.split`：train/validation 的样本切分。
- `overfitRisk`：当前最优 trial 的过拟合风险提示。
- `best.parameters`：当前搜索空间内的候选参数，不是最终定参。
- `best.train.runId` / `best.validation.runId`：trial 分段回测 ID，可拉取报告追溯交易。
- `trials` / `results`：全部 trial 明细。
- `parameterStability`：Top trial 的参数取值集中程度。
- `walkForward`：滚动验证分段、聚合指标和正收益分段占比。

CLI 等价命令：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli optimize-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --method grid `
  --objective stability `
  --validation-mode auto `
  --validation-ratio 0.3 `
  --walk-forward `
  --trials 12 `
  --seed 20260430
```

## 8. Golden 对齐

Golden 对齐用于验证 Python 版 RankTrend 是否和 TypeScript 版 `rankTrend` 结果一致。它不是普通回测入口。

截图里的错误：

```json
{
  "passed": false,
  "issues": ["caseId or path is required"]
}
```

含义是后端没有收到可用的 golden case。修复字段兼容后，如果没有导入 golden case，常见返回会变成：

```json
{
  "passed": false,
  "issues": ["golden case not found: rank_trend_default"]
}
```

这表示还没建立 TS golden 样本，不影响你跑普通回测。

### 8.1 导出 TS Golden JSON

当前不再使用“QuantBoard 自动打开 DragonBoard 新页面”的方式生成 TS Golden。稳定做法是在已经打开并能正常显示数据的 DragonBoard 页面手工导出。

步骤：

1. 打开 `http://localhost:5173` 的 DragonBoard 页面。
2. 刷新页面，确保加载最新代码。
3. 按 `F12` 打开开发者工具，进入 `Console`。
4. 执行：

```js
await window.quantBoardExportRankTrendGolden({
  caseId: 'rank_trend_default',
  datasetId: 'ds_xxx',
  snapshotType: 'half_hour',
  limit: 500,
  sampleLimit: 100
})
```

这里的 `datasetId` 建议填 QuantBoard 当前数据集 ID，方便后续追踪。执行后浏览器会下载：

```text
rank_trend_default.half_hour.ts-golden.json
```

### 8.2 导入并校验

回到 QuantBoard 页面：

1. 进入 `Golden 对齐`。
2. `caseId` 保持 `rank_trend_default`。
3. 选择刚下载的 TS Golden JSON。
4. 点击 `导入 TS Golden`。
5. 点击 `执行校验`。

结果中只有同时满足下面条件，才算正式跨语言对齐：

- `passed=true`
- `source=ts_golden_import`
- `isFormalTsGolden=true`
- `issueCount=0`

如果结果显示 `source=python_current_output`，说明这是 Python 自基线，只能用于临时回归，不能作为 TypeScript/Python 跨语言验收。

### 8.3 CLI 校验

也可以用本地 golden JSON 文件：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli validate-golden --path d:\path\to\golden.json
```

正式流程仍建议先在页面导入 TS Golden，再用 `caseId` 校验。

## 9. 常见问题

### API 显示 error

先确认后端是否启动：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

正常会返回：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "engine": "QuantBoard",
  "default_snapshot_type": "half_hour"
}
```

### 页面读不到 DragonBoardData

这是浏览器同源限制。QuantBoard UI 跑在 `localhost:5174`，DragonBoard UI 跑在 `localhost:5173`，两个 origin 的 IndexedDB 相互隔离。不要用 `当前页面预览` 导入 DragonBoard 数据，使用 `运行页桥接`。

### 回测提示没有 frames

通常是 `snapshotType` 选错。首期默认是 `half_hour`，如果数据集只有半小时快照，回测表单也必须选 `half_hour`。

### Golden 校验失败

如果提示 `golden case not found`，说明还没有导入 golden case。先跳过 Golden，直接做数据集回测和优化。

如果已经从 DragonBoard TypeScript 端导出了 golden JSON，可以在 Golden 对齐页选择文件并点击 `导入 TS Golden`。导入后继续点击 `执行校验`，后端会用同一个 `caseId` 比较 Python 当前输出和 TypeScript expected。

注意：`保存当前输出为基线` 保存的是 Python 当前输出，只用于临时回归；正式对齐仍以 `导入 TS Golden` 为准。

### 优化结果不能直接当最终参数

优化结果只是候选参数。正式使用前要换时间区间、换数据集或做 walk-forward 验证，避免只适配当前样本。

## 10. 推荐日常流程

最小可用流程：

1. 启动 DragonBoard、`QuantBoard API` 和 `QuantBoard UI`。
2. 刷新 DragonBoard 页面，让运行页 bridge 生效。
3. 在 QuantBoard 左侧用 `运行页桥接` 导入 `half_hour` 数据集。
4. 页面刷新并选择数据集。
5. 在 `回测运行` 用默认参数跑一版。
6. 在 `回测报告` 查看收益、回撤、交易和信号分布。
7. 在 `单票回放` 输入重点股票代码，检查入场和出场解释。
8. 在 `参数优化` 小范围搜索候选参数。
9. 换时间段复测候选参数。
