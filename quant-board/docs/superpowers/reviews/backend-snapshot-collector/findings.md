# Backend Snapshot Collector 审查发现

## 当前事实

- 工作分支：`quantboard-backend-snapshot-collector`。
- 审查开始时已有未提交改动：`quant-board/docs/api-cli.md`、`quant-board/docs/architecture.md`、`quant-board/tests/test_snapshot_collector_api.py`。
- 这些改动属于既有工作区状态，审查中保留并纳入验证。

## 需求映射

- Phase 1：后端 run-once、shadow 写入、质量门禁、API/CLI、bridge 显式代码池。
- Phase 2：bridge 持久订阅池、缓存/陈旧检测，不依赖浏览器 WebSocket。
- Phase 3：四类快照 scheduler、交易日/收盘 grace window、重启去重。
- Phase 4：shadow/live 对比 snapshot、槽位、行数、字段缺失率和 RankTrend 样本质量；入口 Phase 5 前要求至少连续 2 个完整交易日无缺槽、空帧、record 缺失和计数漂移，且 15:00 half_hour/daily 完整。
- Phase 5：关闭前端自动正式快照写入，但保留手动诊断和后端 API 读取。

## 已识别口径风险

- `README.md` / `AI_COLLABORATION.md` 已明确 MongoDB 为当前主库，根级旧 SQLite 描述不是本任务事实源。
- 进度文档仍把 Phase 4 写成未完成；提交历史声称完成，必须用代码、测试和真实审计证据判定。
- 设计曾记录截至 Phase 4 `service_factory` 只挂载 `ProxyQuoteProvider`，`depth` 缺失率 100%，题材运行时/市场情绪/涨停池也未接入；本轮已修复 collector 代码接入缺口，历史 shadow 数据不会自动回填。
- Phase 5 若“默认关闭前端正式写库”在 Phase 6 live collector 启用前部署，会形成生产快照空窗；需检查实现计划是否明确部署顺序或 feature flag 默认值。

## 审查发现

### Important（已确认）

1. Phase 4 `POST /api/snapshot-collector/compare` 合同缺实现：service/repository、文档和未提交测试均存在，但 FastAPI 路由未注册；定向测试 5 项返回 404。
2. compare 的核心算法测试主要复制在 `FakeSnapshotRepository` 内，没有覆盖生产 `_MongoSnapshotCollectorRepository.compare_datasets()`；存在“测试复制实现而非测试实现”的盲区。
3. `compare_datasets()` 的 `summary.totalSlotsCompared` 当前只统计任一数据集已出现的槽位，而不是该日期应有槽位总数；两个数据集共同缺失的槽位完全不可见，与 Phase 4 的“槽位完整性”目标不一致。
4. shadow builder 的字段名与正式 `SnapshotStockRow` 合同错位：`pctChange/amount/heat/totalMarketValue` 未投影为 `change/turnover/hotness/totalMV`，导致真实 shadow 审计中核心字段出现 100% 假缺失。
5. `_detect_count_drifts()` 只比较两侧都存在且 frame count 为真值的 snapshot，漏报 frame=0/实际有行、frame>0/实际无行。
6. `force=true` 只跳过 service 预判重，底层 MongoRepository 仍按 snapshot id 判重，文档宣称的“强制重写”未发生。
7. bridge 池模式每次 GET 实际重新抓取行情，但返回的 `poolRefreshedAt` 一直是订阅池创建时间，30 秒后会把新鲜数据误标为陈旧。

### 环境性失败（待修测试隔离）

- `Settings()` 源码默认 `snapshot_collector_enabled=False`，但 worktree 的 `.env.local` 设置为 `1`，导致“默认禁用”测试失败。生产默认值没有被改坏，测试需显式隔离环境。

### 验证结果

- Collector 定向基线：451 passed / 6 failed / 488 deselected。失败为 compare 路由 5 项与环境污染 1 项。
- python-bridge：28 passed；出现 `tdx_hq_cache.py` 与 mootdx 的文件句柄 ResourceWarning，需确认是否为本分支影响。
- QuantBoard 全量 pytest：949 passed / 3 failed。3 项均为 `tests/test_theme_support.py` 的既有失败；在主工作区单独运行同文件得到相同的 3 failed / 7 passed，和本分支改动无因果关系。

### 修复状态

- 上述 1–7 已修复并有回归覆盖；资金流行新增 `estimated_l1` provenance，质量门禁可明确发出观察口径警告。
- `tdx_hq_cache.py` 文件句柄 warning 位于分支未修改文件，不纳入本次精准修改；作为后续技术债记录。

## Phase 4 真实数据证据（2026-06-21 读取）

- shadow `half_hour`：20 frames / 20 records / 2000 stock rows / 0 sector rows，日期为 2026-06-15、2026-06-16；两天各 10 个槽位完整，15:00 完整。
- shadow `daily`：2026-06-15、2026-06-16 各 1 帧，均为 100 stock rows / 0 sector rows。
- 两天 half_hour 与 live 的平均股票行数差分别为 129.1、112.5；shadow 每槽固定 100 行，明显低于 live。
- 旧 shadow 数据中 `change`、`turnoverRate`、`hotness`、`depth10`、`totalMV` 缺失率均为 100%，sector rows 为 0。字段别名修复只影响后续新采集，不会自动改写历史 shadow 数据。
- `verify-mongodb-migration` 对 shadow 和 live 均返回 `ok=true`，但该命令只证明集合/索引/基本连续性，不证明 shadow 质量不低于 live。

## 阶段 5 结论

**No-Go。** 槽位连续性达到两日门槛，但 Phase 4 的“质量优于或不低于前端链路”未达到；必须从 2026-06-22 起使用本次修复后的代码重新采集至少两个完整交易日，并确认 canonical 字段、stock row 覆盖和 RankTrend 样本质量后再评估。`sector_rows=0` 因板块 API 端口不可用暂列为已知外部缺口，不单独阻塞这两日 shadow 采集，但不得描述为板块能力已通过。

自动运行门禁已改为独立守护方案：Windows 计划任务运行目标工作区代码，在 `8001` 启动 shadow collector，并结构化检查 scheduler 已启用、正在运行且数据集严格为 `dragonboard_backend_shadow`；现有主工作区 `8000` 服务不被替换。

提交前复审补充修复：守护进程不再仅按端口判定依赖健康，改为 MongoDB `ping`、proxy/bridge 服务身份检查和 collector scheduler 合同；自己启动但失去健康的进程会重启，未知占端口进程保持 `blocked`。`force` 重采增加失败回滚，任一事实集合写入异常时恢复替换前快照和 dataset 文档。

## 2026-06-27 缺槽与 count drift 复核

用户最新要求修复 `2026-06-22 15:00` 缺槽，并评估 `depth10`、`limitUpPool`、`sectorLabel`、`amplitude` 是否阻塞阶段 5。

根因：`backend/snapshot_collector/builder.py` 在过滤无 `code` 的 provider 原始股票行之前，先用 `len(market_context.stocks)` 写入 `frame.stockRowCount`。实际 `stockRows` 构建会跳过无效代码行，因此当原始热榜含 2-3 条无效代码时，frame 摘要为 100，但实际入库股票行为 97/98。

代码修复：`frame.stockRowCount` 改为在 `stockRows` 构建、过滤、enrich 和排序完成后回填 `len(stock_rows)`；新增回归测试覆盖“无 code 股票被跳过时 frame 计数仍等于最终 stockRows 数量”。

数据修复：仅校正两个明确历史 shadow frame 的摘要计数，不删除、不复制、不重写任何事实行，并写入 `migration_audit(opType=snapshot_collector_count_drift_repair)`：

| snapshotId | 修复前 frame stockRowCount | 实际 stock rows | 修复后 |
| --- | ---: | ---: | ---: |
| `half_hour:2026-06-23:11:00` | 100 | 97 | 97 |
| `half_hour:2026-06-26:11:30` | 100 | 98 | 98 |

修复后审计摘要：

| 口径 | frames | records | stock rows | sector rows | missing slots | count drifts | 备注 |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `half_hour` 全量 shadow | 70 | 70 | 7116 | 9082 | 无 | 无 | 6/22 15:00 已由 live 同槽位 donor 补入 |
| `half_hour` 2026-06-22 | 10 | 10 | 1121 | 0 | 无 | 无 | `15:00` 从 `dragonboard_live` 同槽位复制 221 stock rows，metadata/qualityFlags/migration_audit 均保留 donor provenance |
| `half_hour` 2026-06-23 | 10 | 10 | 997 | 2151 | 无 | 无 | 原 `11:00` drift 已清除 |
| `half_hour` 2026-06-24 | 10 | 10 | 1000 | 2390 | 无 | 无 | 可作为连续观察样本之一 |
| `half_hour` 2026-06-25 | 10 | 10 | 1000 | 2390 | 无 | 无 | 可作为连续观察样本之一 |
| `half_hour` 2026-06-26 | 10 | 10 | 998 | 2151 | 无 | 无 | 原 `11:30` drift 已清除 |
| `daily` 全量 shadow | 6 | 6 | 600 | 956 | 无 | 无 | daily 槽位完整 |

`2026-06-22 15:00` 修复方式：新增可复现维护命令 `copy-missing-mongodb-snapshot-slots`，默认 dry-run；本次执行 `--target-dataset-id dragonboard_backend_shadow --donor-dataset-id dragonboard_live --snapshot-id half_hour:2026-06-22:15:00 --apply`，写入 1 record、1 frame、221 stock rows、0 sector rows，并写入 `migration_audit(opType=mongodb_snapshot_slot_copy)`。这不是历史重采，也不是把 collector 写目标切到 live；只是为 shadow 补齐一个明确缺失的历史槽位。

字段门禁结论（历史判定，已被下一节代码修复取代）：

> 以下表格记录的是本轮修复前、基于历史 shadow 数据和旧 collector wiring 得出的阻塞判定。2026-06-27 后续“字段接入全面排查与修复”已补齐这些代码接入缺口；当前结论以下一节为准。

| 字段 | 当前事实 | 是否必须在进入阶段 5 前修复 | 原因 |
| --- | --- | --- | --- |
| `depth10` | 6/24、6/25、6/26 新 shadow 仍 100% 缺失；当前 collector 默认装配 `ProxyQuoteProvider`，该 provider 明确无 depth 来源。live 同期约 95%+ 有 `depth10`。 | 阻塞正式替代前端写库 / live cutover；不阻塞“槽位连续性”验收。 | 回测执行链当前消费买一/卖一价量字段而非 `depth10` 对象，但阶段 5 的目标是后端 shadow 质量不低于前端链路；缺 depth 会降低 L2/盘口诊断和未来严格撮合可信度。 |
| `limitUpPool` | shadow 与 live 当前均为 100% 缺失；回测涨跌停约束通过 `change`、`limitStatus`、`isLimitUp`、`limitUpPrice` 等信号字段推断，不直接消费该字段。 | 不单独阻塞阶段 5，但必须记录为未接入涨停池专项。 | 不能用空列表伪装修复；若阶段 5 目标包含涨停池能力替代，需另接正式涨停池来源。 |
| `sectorLabel` | stock rows 100% 缺失，且 6/26 样本中 `themes` 也未落到 stock rows；虽然 `sector_rows`/hot_theme rows 已存在，但不能替代逐股题材暴露。 | 阻塞题材解释/ThemeTrend 逐股暴露口径；若阶段 5 只关闭前端自动正式快照写入，也应先修或明确 feature flag 不切题材相关读口。 | 当前 service 默认 provider 未挂 `ThemeMappingProvider`，不是简单字段别名问题。 |
| `amplitude` | shadow 与 live 当前均为 100% 缺失，且当前 quote provider 不落 `high/low`。 | 不单独阻塞阶段 5。 | RankTrend/golden/当前执行链不直接消费 `amplitude`；若要启用盘中止盈止损高低价触发，应先接 `high/low`，而不是补一个派生空字段。 |

当时阶段 5 复评：**槽位/record/count drift 门槛已通过，但数据域替代门槛仍 No-Go。** 该结论在下一节完成代码接入修复后更新为“代码接入阻塞已清零，但仍需修复后新落库两日审计”。

## 2026-06-27 字段接入全面排查与修复

用户追问“还有多少因为代码未实现未接入前端数据源造成阻塞进入阶段 5”。本轮按前端数据源、proxy/bridge 输出和 collector provider/builder 三层复查，确认并修复以下代码接入缺口：

| 数据域 | 根因 | 修复 | dry-run 证据 |
| --- | --- | --- | --- |
| `themes/mainTheme/sectorLabel` | `ThemeMappingProvider` 已存在，但默认 provider 列表未挂载；builder 未从逐股题材派生旧审计名 `sectorLabel`。 | 默认挂载 Mongo 题材映射 provider；builder 写入 `themes`，并从首个题材派生 `mainTheme/sectorLabel`。 | 2026-06-26 15:00 只读 dry-run：`themes/mainTheme/sectorLabel=205/213`；剩余 8 只是题材基础库未映射，不是 collector 未接入。 |
| `limitUpPool` 及涨停池字段 | 前端 `LimitUpFeed` 有 `/api/limitup/ths/pools` 来源，后端 collector 没 provider，也没有 `MarketDataContext.limit_up`。 | 新增 `ProxyLimitUpProvider`，接入 THS pools，写入 `limitUpPool/reason/firstZtTime/lastZtTime/boardHeight/highDays/fengdan` 等字段。 | 只读 dry-run：`limitUpPool=49/213`，其中 `firstZtTime/boardHeight/fengdan=30/213`。这是事件字段，只应覆盖涨停池股票，不能按全量股票 100% 审计。 |
| `depth10/bid1/ask1` | 默认未挂 `BridgeQuoteProvider`；且 bridge 返回 `bids/asks` 结构，collector 只识别扁平 `bidPrice1/askPrice1`。 | 默认挂载 bridge provider；provider 保留 `bids/asks`；builder 兼容 `bids/asks` 与扁平字段，并落 `depth10/bid1Price/ask1Price`。 | 只读 dry-run：`depth10=213/213`、`bid1Price=204/213`、`ask1Price=183/213`。部分涨停/无卖盘样本没有 ask1 属正常盘口状态。 |
| `price/change/turnoverRate` bridge 形状 | python-bridge quote 使用 `lastPrice/changePct/turnoverRate`，collector quote normalizer 只认 `price/pctChange/turnover`，导致真实样本可出现价格为 0。 | normalizer 增加真实 bridge quote 别名映射。 | 只读 dry-run：`price/change/turnoverRate=213/213`。 |
| `amplitude` | 前端 live 历史也未落该字段；但 bridge HTTP quote 有 `high/low/preClose`，collector 未保留。 | provider 保留 `high/low/preClose/open`；builder 在 `high>=low` 且 `preClose>0` 时派生 `amplitude`。Mongo 写入保留额外字段；SQLite 历史模型没有独立列。 | 只读 dry-run：`high/low/preClose/amplitude=213/213`。 |

本轮后，已确认的“前端已有来源但后端 collector 未实现/未接入/未解析”的代码阻塞项为 **0 个**。剩余风险分三类：

- 历史 shadow 库缺字段仍会在审计中显示高缺失；这不是当前代码能力，需新采集或明确回填。
- 题材 205/213 覆盖不足来自 Mongo 题材基础映射缺口，应按题材库质量专项处理。
- 当前 bridge depth 是 L1 + 标准五档，不是真 L2 十档；`depth10` 字段名沿用前端合同，不能宣传为官方十档。

阶段 5 复评更新：**代码接入阻塞已清零，但仍不能只凭历史数据库宣布进入阶段 5。** 下一步必须用修复后的 collector 实际落库至少两个完整交易日，再跑 `snapshot-collector-audit` 和 shadow/live compare。若新落库审计达到槽位、count drift、核心字段覆盖和质量门禁要求，则可以进入阶段 5 发布切口评审。
