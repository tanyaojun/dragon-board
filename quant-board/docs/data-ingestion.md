# 数据导入与质量门禁

## 目标

QuantBoard 首期导入 dragon-board 的历史快照数据，形成可复现的数据集。导入结果必须能支持：

- Python rankTrend 逐快照分析；
- 回测事件循环；
- 参数优化；
- golden case 生成与验证；
- 前端报告查询。

## 数据来源

首期支持两类来源：

1. IndexedDB 导出 JSON
   - 来自 dragon-board 浏览器端快照存储。
   - 适合人工导入和归档。

2. 快照备份或投影 JSON
   - 如果已有 `snapshots`、`snapshot_frames`、`snapshot_stock_rows` 结构化导出，可直接映射。
   - 适合后续自动化同步。

不建议首期直接读浏览器 IndexedDB 文件。浏览器存储结构、锁和 LevelDB 细节会增加不必要复杂度。

## 标准数据集结构

导入后生成一个 `dataset_id`，所有表都带这个 ID。

```text
datasets
snapshot_records
snapshot_frames
snapshot_stock_rows
snapshot_sector_rows
```

正式分析优先读取：

- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`

`snapshot_records` 用于追溯、排查和重新投影。

## 快照类型

默认导入和回测口径：

```text
snapshot_type = half_hour
```

可选导入：

- `quarter_hour`
- `hourly`
- `daily`

导入器可以同时导入多种类型，但回测请求必须明确使用哪一种。没有显式传入时使用 `half_hour`。

## 字段映射

### 快照级字段

| 标准字段 | 说明 |
| --- | --- |
| `snapshot_id` | 原始快照 ID 或导入器生成 ID |
| `type` | `half_hour`、`quarter_hour` 等 |
| `trading_date` | `YYYY-MM-DD` |
| `slot_time` | `HH:mm` |
| `timestamp` | 毫秒时间戳 |
| `display_key` | 可读名称 |
| `capture_mode` | `real_time`、`delayed`、`restored` |
| `source` | `browser_runtime`、`indexeddb_export` 等 |
| `market_context_json` | 市场摘要、情绪、指数、涨跌停等 |

### 股票行字段

| 标准字段 | 说明 |
| --- | --- |
| `row_id` | `snapshot_id:code` |
| `code` | 股票代码 |
| `name` | 股票名 |
| `rank` | 热榜排名 |
| `price` | 当前价 |
| `change` | 涨跌幅 |
| `volume_ratio` | 量比 |
| `zlje` | 主力净额 |
| `zljzb` | 主力净占比 |
| `turnover` | 成交额 |
| `turnover_rate` | 换手率 |
| `payload_json` | 其他字段原样保留 |

### 板块行字段

板块、题材、主线可统一映射到 `snapshot_sector_rows`：

- `entity_type`
- `entity_key`
- `entity_name`
- `rank`
- `payload_json`

## 导入流程

1. 读取源文件。
2. 识别 schema 版本和快照列表。
3. 生成 `dataset_id` 和 `schema_fingerprint`。
4. 标准化快照 ID、日期、时间、类型。
5. 写入原始 `snapshot_records`。
6. 投影到 `snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
7. 执行质量门禁。
8. 写入 `datasets` 汇总统计。
9. 返回导入报告。

## 质量门禁

质量门禁分为导入门禁和回测门禁。

### 导入门禁

导入门禁关注数据是否能入库：

- 是否能解析为 JSON；
- 是否存在快照数组或可识别对象；
- 快照是否有 `type`、`trading_date`、`timestamp`；
- 股票行是否有 `code`、`rank`；
- 同一 `dataset_id + snapshot_id` 是否重复；
- 同一 `snapshot_id + code` 是否重复。

导入门禁失败可以整批失败，也可以进入 `partial` 状态，但必须返回错误明细。

### 回测门禁

回测门禁关注数据是否足够支持策略：

- `snapshot_type` 是否存在；
- 日期区间内快照数量是否达到最低要求；
- 快照时间是否单调递增；
- 股票行数量是否合理；
- 核心价格字段是否有效；
- `capture_mode=restored` 是否被正式回测排除；
- 单只股票有效样本是否达到 rankTrend 最低要求。

最低样本数应由 Python rankTrend 配置计算，默认可参考 TypeScript `getTechnicalMinSamples()`：`max(macdSlow, max(momentumPeriods)+1, 30)`。

QuantBoard 当前把质量分成两层：

- 可运行门槛：快照数量足够、时间顺序合法、capture mode 合法，并且剔除空热榜后仍有足够可交易快照；
- 研究可信度门槛：热榜横截面行数建议不少于 `20`。低于该阈值的快照不会直接阻断回测，但会在 `qualityGate`、回测 `dataQuality` 和优化 `warnings` 中标记为 degraded。

因此“质量门禁通过但仍有低热榜 warning”是允许状态，含义是结果可用于候选观察，不应直接用于严格验收或定参数。

空热榜快照会在导入质量门禁中记录为问题；回测/优化运行时会自动剔除这些不可交易快照继续执行，并在报告中输出 `runtimeFilter`、`droppedEmptyHotlistSnapshots`、源快照数和实际运行快照数。

## 样本质量状态

rankTrend 输出应保留样本质量：

```json
{
  "snapshotType": "half_hour",
  "sampleCount": 32,
  "requiredSampleCount": 30,
  "status": "ok",
  "coverageWarning": null,
  "latestTradingDate": "2026-04-30",
  "latestSlotTime": "14:30",
  "delayedCount": 1,
  "restoredCount": 0
}
```

状态定义：

- `ok`：达到最低样本数。
- `degraded`：样本不足但不少于 5，可用于观察，不宜作为强交易信号。
- `insufficient`：样本严重不足，不参与重点候选。

## capture_mode 规则

正式回测默认读取：

- `real_time`
- `delayed`

正式回测默认排除：

- `restored`
- `manual`

如果用户为了诊断显式包含恢复快照，报告必须标注 `include_restored=true`，不能和正式回测结果混排。

## 导入报告

建议返回：

```json
{
  "dataset_id": "ds_20260430_001",
  "source_type": "indexeddb_export",
  "snapshot_count": 80,
  "frame_count": 80,
  "stock_row_count": 16000,
  "sector_row_count": 1200,
  "snapshot_types": ["half_hour"],
  "start_date": "2026-04-20",
  "end_date": "2026-04-30",
  "warnings": [],
  "errors": []
}
```

## 验收清单

- 同一源文件重复导入时，能通过 `dataset_id` 或唯一键避免数据混乱。
- 默认 `snapshot_type` 为 `half_hour`。
- `quarter_hour` 只有在显式选择时进入回测。
- 门禁失败返回结构化原因。
- 导入后可以按 `dataset_id + snapshot_type + trading_date` 稳定查询。
- 查询结果按 `timestamp` 升序，保证回测事件顺序稳定。
