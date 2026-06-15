# MongoDB Snapshot Repair Design

## 结论

当前 `dragonboard_live` MongoDB 正式快照主库存在历史残缺，但问题已经收敛到少量可枚举的结构异常，不是当前 2026-06-11 盘中定时快照全链路失效。推荐在现有 `backfill-empty-mongodb-snapshots` 修复链路上扩展，而不是新造独立 repair 体系。这样可以沿用现有 CLI、`migration_audit` 留痕和 `verify-mongodb-migration` 验收方式，用最小改动同时处理空快照、缺槽位、frame 计数字段漂移、`snapshot_record` 缺失，以及 Mongo 研究集合缺失索引。

## 目标

- 修复 `dragonboard_live` 中已知空 `half_hour` 快照，允许按显式 donor 或跨粒度 donor 补齐。
- 修复少量 frame 声明计数与实际 `snapshot_stock_rows` / `snapshot_sector_rows` 数量不一致的问题。
- 允许为缺失的 `half_hour` 槽位补造正式快照，首批规则是同日 `15:00` 缺 `half_hour` 时允许使用同日 `daily:15:00` 作为 donor。
- 修复已有 frame + rows 但缺失 `snapshot_record` 的历史快照。
- 补回 `backtest_trades` 与 `backtest_equity_curve` 的 `{ backtestRunId: 1, sequence: 1 }` 索引，并纳入 Mongo 校验。
- 形成两类文档产物：
  - 审计报告：记录发现、根因、范围、验收结果。
  - 修正记录：记录每个被修复的 snapshot、donor 来源、修复方式和最终统计。

## 非目标

- 本次不重写 Mongo ingest 主链，不改 Dragon Board 前端定时快照生产逻辑。
- 本次不清理历史 SQLite/Supabase 兼容代码。
- 本次不触碰 RankTrend 算法、回测逻辑、默认 `snapshot_type` 或研究集合合同。
- 本次不引入新的外部存储或新的大型运维框架。

## 已确认问题

基于 2026-06-11 的本地 Mongo 审计，当前 `dragonboard_live` 状态如下：

- `snapshot_records = 1223`
- `snapshot_frames = 1478`
- `snapshot_stock_rows = 321657`
- `snapshot_sector_rows = 14894`

### 1. 空 `half_hour` frame

`verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour` 当前仍返回 `ok=false`，存在 4 个 `half_hour` frame 的 `stockRowCount > 0`，但实际 `snapshot_stock_rows = 0`：

- `half_hour:2026-05-07:13:00`
- `half_hour:2026-05-08:14:00`
- `half_hour:2026-05-14:13:00`
- `half_hour:2026-05-18:11:30`

这些 frame 已带 `qualityFlags`，说明不是无痕坏数据，但当前正式快照事实仍不完整。

### 2. frame 计数字段漂移

已确认至少 6 个 `stockRowCount` 漂移和 1 个 `sectorRowCount` 漂移，例如：

- `half_hour:2026-04-16:10:00`：声明 `237`，实际 `288`
- `quarter_hour:2026-06-08:13:15`：声明 `229`，实际 `243`
- `half_hour:2026-05-18:11:30` 的 `sectorRowCount`：声明 `75`，实际 `25`

### 3. frame 存在但 `snapshot_record` 缺失

存在 `255` 个 frame 没有对应 record：

- `quarter_hour = 213`
- `half_hour = 42`

抽样确认这类问题是“frame + rows 已存在，但缺 record”，不是整帧坏掉。

### 4. Mongo 研究集合缺失索引

当前 `verify-mongodb-migration` 会报两个缺失索引：

- `backtest_trades`: `{ backtestRunId: 1, sequence: 1 }`
- `backtest_equity_curve`: `{ backtestRunId: 1, sequence: 1 }`

## 推荐方案

采用“扩展现有 repair 链路”的单路径方案。

### 1. 扩展现有快照修复 CLI

继续使用现有：

```powershell
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots
```

但将其职责从“只处理已知空股票快照”扩展为“正式快照结构修复器”，新增以下能力：

- 修空 frame：给定 `snapshot_id -> donor_snapshot_id` 映射，复制 donor 的股票行/板块行并重写目标快照键字段。
- 允许跨粒度 donor：
  - `half_hour <- quarter_hour`
  - `half_hour <- daily`
- 修复 frame 计数字段：按实际子集合行数回写。
- 补 `snapshot_record`：已有 frame/rows 时按 frame 反建 record。
- 检查并补造缺失槽位：首批支持 `half_hour:15:00 <- daily:15:00`。

CLI 名称保持不变，避免新增并行维护入口。帮助文案和输出结果要更新，明确它现在不只是“backfill empty”，而是“repair empty/missing/drifted formal snapshots”。

### 2. donor 选择规则

为了避免脚本“猜数据”，本次设计采用显式优先、规则兜底：

1. **显式映射优先**
   - 在修复模块中维护本次已确认的 donor 映射。
   - 例如：
     - `half_hour:2026-05-07:13:00 <- quarter_hour:2026-05-07:13:15`
     - `half_hour:2026-05-08:14:00 <- half_hour:2026-05-08:13:30`
2. **规则兜底**
   - 只对明确支持的场景启用：
     - 同类型同日最近 donor
     - `half_hour:15:00` 缺槽位时，允许用同日 `daily:15:00`
   - tie-break 固定为：
     - 先按 `abs(target.timestamp - donor.timestamp)` 升序
     - 距离相同时优先更早的 donor
     - donor 的股票行和板块行必须来自同一个 donor snapshot，不允许分别挑不同 donor
3. **禁止无约束自动猜测**
   - 不允许脚本在未知场景里随意挑 donor，避免把错误数据扩散成“修复”。

### 3. `snapshot_record` 补造规则

对 `frame` 已存在但 `record` 缺失的快照，补造的 record 必须：

- 保持 `snapshotId / type / tradingDate / slotTime / timestamp / datasetId` 一致。
- 从 frame 和已有 rows 中补足：
  - `totalCount`
  - `qualityFlags`
  - `captureMode`
  - `displayKey`
  - `source`
- 如 frame 无法提供的字段，使用当前 `normalize_snapshot_ingest` / `frame_from_record` 的反向兼容最小集合，不伪造无法追溯的业务含义字段。

补造的 record 至少要显式写出并保持一致：

- `snapshotId`
- `type`
- `tradingDate`
- `slotTime`
- `timestamp`
- `displayKey`
- `captureMode`
- `capturedAt`
- `dataTimestamp`
- `delayMs`
- `qualityFlags`
- `source`

本次目标是恢复正式快照读口和数据一致性，不要求重建所有历史 payload 细节。

### 4. frame 计数修正规则

对每个候选 frame：

- `stockRowCount = count(snapshot_stock_rows where datasetId + snapshotId)`
- `sectorRowCount = count(snapshot_sector_rows where datasetId + snapshotId)`

如果声明值与实际值不同，则更新 frame。对于空 frame 补完 rows 后，也要同步刷新计数。

### 5. 缺槽位补齐规则

先只支持明确场景：

- 如果 `half_hour:YYYY-MM-DD:15:00` 缺失，且存在同日 `daily:YYYY-MM-DD:15:00`，允许基于该 daily 快照生成一个 formal `half_hour` frame、record 和 rows。

此行为必须：

- 在 metadata 中留下 `backfill.sourceSnapshotId`
- 在 `qualityFlags` 中追加 `backfilled_from_cross_type_snapshot`
- 在修正记录中单独标记为“缺槽位补造”，区别于“空 frame 补行”
- 新补造的 `half_hour` frame / record 字段合同固定为：
  - `captureMode = synthesized`
  - `source = cross_type_backfill`
  - `capturedAt = donor.timestamp`
  - `dataTimestamp = donor.timestamp`
  - `delayMs = 0`
  - `displayKey = targetSnapshotId`

### 6. 缺失索引修复

当前缺口不是“代码里没有索引定义”，而是“正式 MongoDB 库里缺少已定义索引”。因此本次修复目标是：

- 复用现有 `build_mongodb_indexes()` 定义；
- 在 repair / verify 链路里显式创建缺失索引；
- 确保正式库最终具备：
  - `backtest_trades(backtestRunId, sequence)`
  - `backtest_equity_curve(backtestRunId, sequence)`

并保证 `verify-mongodb-migration` 的索引校验与实际 runtime 数据库状态一致。

## 代码落点

- `quant-board/backend/data/mongodb_snapshot_repair.py`
  - 扩展 repair/backfill 主逻辑
  - 新增 donor 解析、count 修正、record 补造、缺槽位补造
- `quant-board/backend/data/mongodb_migration.py`
  - 扩展 `verify_mongodb_migration()` 输出：
    - `missingRecords`
    - `countMismatches`
    - `missingSlots`
  - 保持 `emptyFrames` 现有输出不回归
  - `ok` 判定必须收紧：只要存在 `missingRecords`、`countMismatches`、`missingSlots`、`emptyFrames`、缺失索引或 rank-series 缺口中的任意一种，`ok` 都必须为 `false`
- `quant-board/backend/cli.py`
  - 更新 CLI 帮助文案
  - 增强 `backfill-empty-mongodb-snapshots` 输出摘要
- `quant-board/backend/data/mongo_repository.py`
  - 只在必要时复用现有 doc 转换函数，不在 repository 中堆新 repair 逻辑
- `quant-board/tests` 与现有 Mongo 测试文件
  - 补 failing tests

## 文档落点

### 1. 设计文档

本文件：

- `quant-board/docs/superpowers/specs/2026-06-11-mongodb-snapshot-repair-design.md`

### 2. 审计报告

新增：

- `quant-board/docs/mongodb-snapshot-audit-2026-06-11.md`

内容包括：

- 审计时间
- 运行命令
- 发现的问题分类
- 影响的 snapshot 列表
- 根因判断
- 修复前后统计对比
- 剩余风险

### 3. 修正记录

新增：

- `quant-board/docs/mongodb-snapshot-repair-log-2026-06-11.md`

内容包括：

- 每个被修复的 snapshotId
- donor snapshotId
- donor 类型是否跨粒度
- 修复动作：补 rows / 补 record / 修 count / 补槽位 / 补索引
- 修复后实际行数
- 对应 `migration_audit` / repair audit 留痕摘要

### 4. 主迁移文档回写

更新：

- `quant-board/docs/mongodb-migration-plan.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/architecture.md`

补充：

- 2026-06-11 新一轮审计结果
- 修复命令
- 修复后 counts / verify 结果
- 对“旧 2026-05-12 已完全通过”的过期结论做时点说明，避免误导

## 测试策略

先补测试，再改实现。

### RED

至少新增以下失败用例：

- 空 `half_hour` frame 可由显式 donor 修复
- `half_hour <- quarter_hour` 跨粒度 donor 修复
- 缺失 `half_hour:15:00` 可由同日 `daily:15:00` 补槽位
- frame count mismatch 会被修正
- frame + rows 存在但缺 record 时会补 record
- `verify_mongodb_migration()` 能报告 `missingRecords` / `countMismatches`
- Mongo 索引定义包含两个缺失索引

### GREEN

最小实现通过上述测试，不顺手改其他行为。

### 验收命令

实现完成后至少运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongodb_migration.py -q
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live --apply
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli inspect-mongodb
```

如果本次把测试拆分到其他测试文件，验收命令要按实际文件补齐。

## 成功标准

- 4 个已知空 `half_hour` frame 被补齐，`emptyFrames=[]`
- 255 个缺 `snapshot_record` 的 frame 被识别并补齐，或审计输出明确剩余数量为 0
- 已确认的 frame count mismatch 被修正，至少 `half_hour:2026-04-16:10:00` 更新为实际 `288`
- `half_hour:2026-06-11:15:00` 若缺失，可由 `daily:2026-06-11:15:00` 正式补造
- `verify-mongodb-migration` 返回 `ok=true`，不再报 2 个缺失索引
- 审计报告和修正记录文档落库，能独立说明“修了什么、为什么修、修后怎样验证”

## 风险与边界

- 跨粒度 donor 是数据补偿，不是原始重采集，必须在 `qualityFlags` 和文档中保留可追溯性。
- `snapshot_record` 补造只能恢复正式读口契约，不保证完全重建历史原始 payload。
- 如果发现某些缺 record 的 frame 来自早期不同合同版本，需按最小兼容字段落库，不能为了追求“完全一致”引入新的历史猜测。
- 本次只处理明确规则下的缺槽位，不把所有时段缺槽都做成自动推断。

## 已确认约束

- 当前存储主链仍以 MongoDB 为准，正式快照通过 QuantBoard 后端 API 落库。
- 默认 `snapshot_type=half_hour` 不变。
- 本次修复应保持小范围、可验证、可回退，不混入与当前数据修复无关的重构。
