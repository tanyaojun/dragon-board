# MongoDB Backtest Report Performance Design

## 结论

QuantBoard 的 MongoDB 性能问题不应先从数据库参数开始修，而应先修应用层的大报告导出链路。当前代码已经具备 `resultCompressed` 与 `backtest_result_chunks` 的存储保护，但 `BacktestService.export_report()` 和 CLI `export-report` 仍会把完整 `result`、交易、权益曲线、信号和质量报告一次性读入内存，再 `json.dumps()` 成一个超大 JSON 文件。这会放大 MongoDB 读取、Python 解压、对象构造、JSON 序列化和磁盘写入的耗时，是回测报告导出超时的主要原因。

## 目标

- 大型回测报告导出不再依赖一次性构造单个超大 Python dict。
- MongoDB 继续作为 QuantBoard 当前主存储链；Dragon Board 不直连 MongoDB，仍通过 QuantBoard API/CLI。
- 报告明细优先读取归一化集合：`backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports`。
- `backtest_runs.resultCompressed` 与 `backtest_result_chunks` 只保留兼容追溯能力，不作为页面和常规导出的首选明细源。
- 所有改动保持可回退：新增流式导出能力，保留现有兼容报告接口。

## 非目标

- 本阶段不迁移历史数据库。
- 本阶段不改变 RankTrend、回测交易规则、信号生成口径、默认 `snapshot_type` 或 golden 对齐逻辑。
- 本阶段不让 Dragon Board 前端直接连接 MongoDB。
- 本阶段不新增大型依赖或引入新的外部存储系统。

## 当前证据

- `quant-board/backend/data/mongo_research_repository.py` 已实现 `BACKTEST_RESULT_CHUNK_THRESHOLD = 8_000_000`、`BACKTEST_RESULT_CHUNK_SIZE = 4_000_000`，并在保存 `backtest_runs` 时将过大的压缩结果拆入 `backtest_result_chunks`。
- `quant-board/backend/services.py` 的 `BacktestService.export_report()` 会读取 `run.result_json`，再聚合 `get_backtest_trades()`、`get_backtest_equity_curve()`、`get_backtest_signals()`、`get_backtest_quality_report()` 和完整 `result`。
- `quant-board/backend/cli.py` 的 `cmd_export_report()` 会执行 `json.dumps(report, ensure_ascii=False, indent=2)`，再 `Path.write_text()` 写出单文件。
- `quant-board/docs/architecture.md` 已说明页面明细应优先读取归一化集合，`backtest_result_chunks` 只服务兼容完整结果追溯。
- `quant-board/docs/api-cli.md` 已说明完整结果通过 `runId` 追溯，接口默认应避免真实数据集响应过大。

## 推荐方案

采用三层方案，按优先级实施。

### 1. 流式报告导出

新增报告导出器，默认输出目录型 bundle：

```text
<output-dir>/
├── manifest.json
├── trades.jsonl
├── equity_curve.jsonl
├── signals.jsonl
├── quality_report.json
└── result_summary.json
```

`manifest.json` 保存运行元信息、请求参数、核心 metrics、明细计数、导出时间和文件清单。`trades.jsonl`、`equity_curve.jsonl`、`signals.jsonl` 按行写出归一化明细。`quality_report.json` 保存现有旧报告中的 `qualityReport`，避免报告合同回归。`result_summary.json` 只保存轻量摘要，不复制完整 `strategyDecisions.frameResults`。

对于必须交付单文件的场景，支持 `json.gz` 流式写出，但仍避免先构造完整 dict。CLI 兼容保留旧 `json` 模式，标记为兼容模式，并提示真实大数据集优先使用 `jsonl-bundle`。

### 2. 回测保存瘦身

`backtest_runs` 中保留 summary 级 `result_json`，完整信号明细以后端归一化集合为准。短期内可以先不删除兼容完整结果，只在新增导出路径中默认绕开完整 `result`；中期再为回测执行增加 `persist_full_result` 或 `artifact_mode` 选项，使大型研究运行不再重复保存完整 `strategyDecisions.frameResults`。

### 3. MongoDB 查询和写入优化

对新增导出器提供迭代式 repository 方法，使用 projection 和 batch cursor，避免一次性返回所有明细列表。新回测 run 保存子表时，避免无必要的 `count_documents({"backtestRunId": run_id})` 起始序号查询；新 run 可直接从 `1` 开始，追加场景再显式计算起点。`save_backtest_signals()` 也必须接收并传递非追加语义，否则 RankTrend 主路径仍会触发 signal count。

索引验收以 `explain("executionStats")` 为准，重点检查：

- `backtest_signals`: `{ backtestRunId: 1, sequence: 1 }`
- `backtest_trades`: `{ backtestRunId: 1, sequence: 1 }`
- `backtest_equity_curve`: `{ backtestRunId: 1, sequence: 1 }`
- `backtest_result_chunks`: `{ backtestRunId: 1, sequence: 1 }` unique
- `snapshot_stock_rows`: 热路径查询中涉及的 `{ datasetId, type, tradingDate, timestamp, rank }` 和 `{ datasetId, code, timestamp }`

## API 和 CLI 设计

CLI 增强：

```powershell
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_1 --output quant-board\data\reports\bt_1 --format jsonl-bundle
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_1 --output quant-board\data\reports\bt_1.json.gz --format json.gz
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_1 --output quant-board\data\reports\bt_1.json --format legacy-json
```

默认格式应为 `jsonl-bundle`。`legacy-json` 保留现有语义，但用于小数据集或兼容调用。

服务层新增流式导出入口，不替代现有 `export_report()`：

```python
BacktestService.export_report_bundle(run_id: str, output: Path) -> dict[str, Any]
BacktestService.export_report_gzip(run_id: str, output: Path) -> dict[str, Any]
```

repository 层新增迭代读取入口：

```python
iter_backtest_trades(run_id: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]
iter_backtest_equity_curve(run_id: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]
iter_backtest_signals(run_id: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]
```

SQLite repository 可先用列表包装成 iterator，Mongo repository 使用 cursor batch。

## 错误处理

- run 不存在：CLI 返回 `{ ok: false, error: { code: "backtest_run_not_found" } }`，不创建半成品目录。
- 导出中断：bundle 先写入临时目录，成功后替换固定输出文件并最后写 `manifest.json`；gzip 先写临时文件，成功后替换最终文件。最终路径中不存在 `manifest.json` 时，不应被视为可用 bundle。
- 明细读取为空：manifest 记录 count 为 `0`，不视为错误。
- 输出路径已存在：默认覆盖同名文件；目录 bundle 覆盖前只替换本次导出的固定文件，不删除未知文件。

## 测试策略

- CLI 参数测试：`export-report` 默认 `format=jsonl-bundle`，并支持 `json.gz`、`legacy-json`。
- 服务层单元测试：构造包含大量 signals 的 fake repository，确认 bundle 导出不会调用 `export_report()` 的完整聚合路径，并确认 `quality_report.json` 被写出。
- 原子落盘测试：模拟写入 signals 时抛错，确认最终 bundle 目录没有可用 `manifest.json`。
- Mongo repository 测试：确认迭代读取按 `sequence` 升序输出，并支持 batch cursor。
- MongoDB 索引测试：确认 `build_mongodb_indexes()` 覆盖 `backtest_trades`、`backtest_equity_curve`、`backtest_signals` 的 `{ backtestRunId, sequence }` 查询排序。
- 文档测试：更新 `api-cli.md` 和 `architecture.md`，明确默认导出格式和兼容模式。

## 成功标准

- 100k 级 signals 的导出可稳定生成 `jsonl-bundle`，不需要构造单个超大 JSON dict。
- `legacy-json` 仍可用于小型报告，兼容现有用户入口。
- MongoDB 查询通过已有索引或新增索引支持，关键导出查询使用 `{ backtestRunId, sequence }` 排序。
- QuantBoard 后端测试通过：`.\.venv\Scripts\python.exe -m pytest`。

## 已确认约束

- 当前项目口径以 `quant-board/docs/README.md` 与 `quant-board/docs/AI_COLLABORATION.md` 的 MongoDB 主链为准。
- 报告导出默认格式可以从单 JSON 改为目录型 bundle；旧单 JSON 通过 `legacy-json` 保留兼容。
