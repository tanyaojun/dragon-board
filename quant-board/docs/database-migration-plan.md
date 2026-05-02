# SQLite 主库与 Supabase 备份库并行实施计划

本文是 QuantBoard 存储迁移与备份同步的主计划。涉及 SQLite 主库、Supabase 备份库、快照入库、同步接口、API/CLI 合同或相关配置的改动，必须先对齐本文，再同步更新 [architecture.md](architecture.md)、[api-cli.md](api-cli.md)、[development-roadmap.md](development-roadmap.md) 和 [AI_COLLABORATION.md](AI_COLLABORATION.md)。

## 目标结论

- SQLite 是 QuantBoard 默认主库，负责本机低延迟读写、回测、优化和报告读取。
- Supabase 是后端专用备份库，不直接暴露给 Vue 前端，也不作为常规查询的第一选择。
- 正常路径是先写 SQLite，提交成功后镜像同一份业务对象到 Supabase。
- SQLite 不可用时，关键写入临时落 Supabase 是 M3 目标能力；Phase 1 只保证本地主库写入、备份补偿骨架和读取回退基线。
- 读路径优先 SQLite；仅当 SQLite 不可用或本地缺失目标记录时，才尝试 Supabase 回退。
- 所有同步、回退和恢复都必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed` 等可复现字段。

## 非目标

- 不把 Supabase 作为前端直连数据库。
- 不把 Supabase 备份当作新的实时协作主库。
- 不在 Dragon Board 根项目新增回测或优化职责。
- 不为了备份同步绕过数据质量门禁、Golden 校验或回测合同。
- 不自动把优化结果写回 Dragon Board 默认参数。

## 当前事实

QuantBoard 已有本地 SQLite 模型和服务骨架，主要表包括：

- `datasets`
- `snapshot_records`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `golden_ranktrend_cases`
- `backtest_runs`
- `optimization_runs`
- `sync_outbox`

Supabase 备份库必须与 SQLite 主库保持同构 schema。云端需要使用 [../backend/data/supabase_schema.sql](../backend/data/supabase_schema.sql) 重建为同名表、同业务键和同索引。脚本末尾会执行 `notify pgrst, 'reload schema'`，执行后仍应通过 `smoke-backup` 或 `/api/health` 确认 PostgREST 已看到新表结构：

- `datasets`
- `snapshot_records`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `golden_ranktrend_cases`
- `backtest_runs`
- `optimization_runs`
- `sync_outbox`

旧的 Supabase `snapshots` / payload 兼容方案已经废弃。云端不再使用 `quality_flags.kind=qb_dataset`、`qb_snapshot_bundle` 等业务枚举，也不再把 QuantBoard 明细塞进 `snapshots.payload`。如果 Supabase 仍只有旧 `snapshots`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows` 四张非同构表，健康检查会报告缺失表，`push-backup` 不应视为可用。

Supabase schema 仍与 SQLite 同构，但备份适配层允许对超大 `Text` 字段做透明 `gzip + base64` 编码，当前覆盖 `backtest_runs.request_json`、`backtest_runs.result_json`、`optimization_runs.request_json`、`optimization_runs.result_json`、`golden_ranktrend_cases.input_json` 和 `golden_ranktrend_cases.expected_json`。这是云端传输/存储适配，不改变 SQLite 原始内容；`pull-backup` 和读回退必须自动解码后再还原为原始 JSON 字符串。

当前 WP2/WP3/WP4 批次已落地的能力：

- `dataset_bundle`、`snapshot_ingest`、`backtest_run`、`optimization_run`、`golden_case` 都会在 SQLite 写入成功后登记 `sync_outbox`。
- Supabase 立即镜像成功时，对应 outbox 标记为 `done`；镜像失败时标记为 `retry` 并写入 `last_error`、`retry_count`、`next_retry_at`。
- `push-backup` 会先消费到期的 `pending/retry` outbox，再做全量扫描补推。
- Dragon Board 对已存在的半小时、十五分钟、小时等正式快照，如果 IndexedDB 已有记录但后端 ingest 失败过，会重放后端入库，不再因为本地记录存在而跳过云端链路。
- Dragon Board 正式聚合读口开始 SQLite 优先：`listSnapshotFrameBundles` 会先调用 QuantBoard `GET /api/snapshots/frames`，远端不可用或无数据时才回退 IndexedDB。
- 历史 JSON 迁移入口 `POST /api/migrations/snapshots/import-json` 已可处理 v4 bundle、records/snapshots、frames/stockRows/sectorRows 和常见 SQLite/备份导出字段。

仍未完成的边界：

- SQLite 完全不可用时直接写 Supabase 的 failover 写入仍是 M3 目标能力。
- IndexedDB 还没有关闭正式写入和所有零散读口；本轮只把正式聚合分析读口改为 SQLite 优先，IndexedDB 暂时保留为缓存、失败回退、重放和迁移来源。
- Supabase 云端 schema 需要用户先在 SQL Editor 执行 `quant-board/backend/data/supabase_schema.sql`；执行前旧云端表会被删除重建，必须确认旧云端数据已经不需要或已另行备份。

## 存储拓扑

```text
Dragon Board 快照/运行页桥接
  -> QuantBoard API/CLI
  -> SQLite primary
  -> Supabase backup
```

职责边界：

- Dragon Board 负责实时看板、正式快照生成和 TypeScript golden 导出。
- QuantBoard API/CLI 负责导入、质量门禁、回测、优化、报告和同步编排。
- SQLite 保存标准化后的可复现实验事实表。
- Supabase 保存可恢复的备份对象，不承担常规低延迟分析查询。

## 写入合同

正常写入顺序：

1. 校验请求、快照类型和质量门禁。
2. 写入 SQLite，并提交事务。
3. 在同一主库事务中登记 `sync_outbox`，保存可重放 payload、`op_type` 和 `idempotency_key`。
4. 以同一业务对象构造 Supabase 备份记录。
5. Supabase 写入成功时将 outbox 标记为 `done`。
6. Supabase 写入失败时不得回滚已成功提交的 SQLite 业务事务，但必须将 outbox 标记为 `retry/failed` 并记录结构化同步诊断。

关键要求：

- SQLite 事务失败时，不得声明业务写入成功。
- Supabase 镜像失败不应阻塞本地研究主链，但必须可被 `push-backup` 后续补偿。
- 备份 payload 必须包含足够字段，能重建 SQLite 主库里的业务对象。
- `dataset_id`、`snapshot_type`、`run_id`、`case_id` 等业务键必须稳定，不能由恢复流程重新随机生成。
- 对同一业务键重复同步必须幂等，不能产生重复数据或覆盖更新更晚版本。

当前 `sync_outbox` 合同：

| 字段 | 说明 |
| --- | --- |
| `op_type` | 当前支持 `dataset_bundle`、`snapshot_ingest`、`backtest_run`、`optimization_run`、`golden_case` |
| `idempotency_key` | 幂等键；Dragon Board ingest 使用前端/后端共同生成的业务键，其他对象用对象键和 payload hash 组合 |
| `status` | `pending`、`retry`、`done`、`failed` |
| `retry_count` | 失败重试次数；达到上限后进入 `failed` |
| `last_error` | 最近一次 Supabase 镜像失败原因 |
| `next_retry_at` | 下次允许 `push-backup` 消费该任务的时间 |

`list_pending_outbox` 只返回 `pending/retry` 且 `next_retry_at` 已到期的任务。

## 读取合同

读取优先级：

1. SQLite 主库。
2. Supabase 备份库回退。
3. 明确失败，返回结构化原因。

允许回退的场景：

- SQLite 初始化失败。
- SQLite 查询异常。
- SQLite 中缺失目标 `dataset_id`、`run_id` 或 `case_id`，但 Supabase 有对应备份记录。

禁止行为：

- 在 SQLite 有可用记录时静默返回 Supabase 旧记录。
- 用空列表、空报告或默认指标伪装读取成功。
- 前端直接读取 Supabase 密钥或 Supabase 表。

## 同步接口合同

### `POST /api/sync/push-backup`

用途：把 SQLite 里已有的数据集、快照 bundle、Golden、回测和优化记录补推到 Supabase。

当前返回：

- `ok`：本次是否无错误完成。
- `direction=push`。
- `outbox`：`scanned`、`succeeded`、`failed`、`skipped`、`items`。
- `datasets`、`snapshotBundles`、`backtestRuns`、`optimizationRuns`、`goldenCases`：每类对象都有 `scanned`、`succeeded`、`failed`、`skipped`。
- `errors`：结构为 `{type,key,error}`。

行为规则：

- 先消费到期 outbox，再做 SQLite 全量扫描补推。
- outbox 成功后标记 `done`；失败后更新 `retry_count`、`last_error` 和 `next_retry_at`。
- 不支持的 outbox 类型计入 `skipped`，不能静默丢弃。
- Supabase REST upsert 使用 `return=minimal`，并按行数和请求体大小双限制分片；大回测和 Golden payload 会先透明压缩，避免单行几十 MB JSON 触发 PostgREST statement timeout。

### `POST /api/sync/push-outbox`

用途：只推送到期的 `sync_outbox` 任务，不做 SQLite 全量历史扫描。它是自动同步调度器使用的最小补偿动作。

行为规则：

- 只处理 `pending/retry` 且 `next_retry_at` 已到期的任务。
- 默认批量大小来自 `QUANT_BOARD_AUTO_SYNC_BATCH_SIZE`。
- 返回结构与 `push-backup.outbox` 一致。

### `POST /api/sync/auto-once`

用途：手动执行一次自动同步同口径的 outbox 推送，便于联调和排障。

### `POST /api/sync/smoke-backup`

用途：Supabase 联调写读删探针。后端会在云端 `sync_outbox` 写入一条 `op_type=supabase_smoke` 的临时记录，读回确认后删除。

行为规则：

- 只验证 Supabase REST 的写入、读取和清理权限。
- 不写入 SQLite，不登记业务 outbox。
- 返回 `write`、`read`、`cleanup` 和 `last_error`。
- 该探针依赖 Supabase 已按 `supabase_schema.sql` 建好同构 `sync_outbox` 表。

### `POST /api/sync/pull-backup`

用途：把 Supabase 备份记录恢复到 SQLite，用于本地主库损坏、重建或后续 failover 写入能力落地后的收敛。

必须返回：

- 拉取对象类型。
- 发现数量、恢复数量、跳过数量、冲突数量、失败数量。
- 冲突处理策略和业务键。
- 是否需要用户人工确认的不可自动合并项。

### `GET /api/health`

必须同时报告：

- SQLite 主库连接状态。
- Supabase 备份库连接状态。
- 当前存储模式，例如 `sqlite_primary_supabase_backup`。
- 备份回退是否启用。

### `POST /api/snapshots/ingest`

用途：Dragon Board 正式快照后端入库入口。前端提交 v4 snapshot bundle，后端按 `dataset_id + snapshot_id + idempotency_key` 幂等写入 SQLite 并登记 Supabase 备份 outbox。

请求核心字段：

- `bundle`：Dragon Board v4 bundle，包含 `items/records`、`frames`、`stockRows`、`sectorRows`。
- `tradingDate`：交易日。
- `idempotencyKey`：可选；缺省时后端根据交易日、快照 ID 和来源生成。
- `source`：默认 `dragon_board_runtime`。

返回核心字段：

- `ok`
- `dataset`
- `status`：当前 outbox 状态。
- `outbox`
- `deduped`

### `GET /api/snapshots/frames`

用途：Dragon Board 和 QuantBoard 从 SQLite 主库读取正式快照聚合帧。该接口返回 frame + stock rows + sector rows 组合后的 bundle，是逐步替换 IndexedDB 正式读取的主接口。

查询字段：

- `dataset_id`：可选；缺省时后端优先使用 `dragonboard_live`，不存在时选择最新有 frame 的 SQLite 数据集，便于历史迁移期逐步替换 IndexedDB。
- `snapshot_type`：默认 `half_hour`。
- `trading_date`、`start_date`、`end_date`、`before_trading_date`。
- `allowed_capture_modes`：逗号分隔，例如 `real_time,delayed`。
- `exclude_restored`。
- `sort`：`asc` 或 `desc`。
- `limit`。

返回核心字段：

- `ok`
- `dataset`
- `datasetId`
- `snapshotType`
- `frames`
- `count`
- `source=sqlite`

Dragon Board 前端正式分析入口 `listSnapshotFrameBundles` 必须优先调用该接口；只有接口不可用、SQLite 无对应数据或迁移未完成时，才允许回退浏览器 IndexedDB。

### `POST /api/migrations/snapshots/import-json`

用途：把旧 IndexedDB 导出、Dragon Board v4 bundle、结构化 frames/rows 或 SQLite/备份导出 JSON 导入正式 SQLite 主库，并复用 `save_snapshot_ingest` 进入 outbox 同步链路。

请求核心字段：

- `datasetId`
- `sourcePath`，或 `content` / `bundle` / `payload`
- `idempotencyKey`
- `name`
- `source`
- `dryRun`

返回核心字段：

- `ok`
- `datasetId`
- `deduped`
- `dataset`
- `report.scanned`
- `report.imported`
- `report.skipped`
- `report.errors`
- `report.dry_run`

重复迁移同一 `idempotencyKey` 或同一批已存在 `snapshot_id` 时，必须跳过已入库快照，不能制造重复事实行。

## 冲突和幂等规则

首期采用保守策略：

- 同一业务键、相同 `config_hash` 或相同 payload hash：视为已同步，跳过。
- 同一业务键、不同 payload hash：标记冲突，不自动覆盖。
- SQLite 已有记录且 Supabase 较旧：保留 SQLite，记录跳过原因。
- Supabase 有记录而 SQLite 缺失：恢复到 SQLite。
- 无法判断新旧时返回结构化冲突，由用户决定是否人工处理。

后续若引入版本号或更新时间戳作为自动合并依据，必须同步更新 API 返回字段和本文规则。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `QUANT_BOARD_DATABASE_URL` | SQLite 主库连接串，默认指向 `quant-board/data/warehouse/quant_board.db` |
| `SUPABASE_URL` | Supabase 项目 URL |
| `SUPABASE_SECRET_KEY` | 后端专用密钥，禁止放入 `VITE_` 前端变量 |
| `QUANT_BOARD_ENABLE_SUPABASE_BACKUP` | 是否启用 Supabase 备份镜像，默认按 Supabase 配置自动启用 |
| `QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK` | 是否启用备份读回退，默认跟随备份镜像 |
| `QUANT_BOARD_BACKUP_TIMEOUT_SECONDS` | Supabase 请求超时时间 |
| `QUANT_BOARD_AUTO_SYNC_ENABLED` | 是否在 API 启动后自动推送到期 outbox，默认 `false` |
| `QUANT_BOARD_AUTO_SYNC_INTERVAL_SECONDS` | 自动 outbox 推送间隔，默认 `60`，最小 `5` |
| `QUANT_BOARD_AUTO_SYNC_INITIAL_DELAY_SECONDS` | API 启动后首次自动同步延迟，默认 `10` |
| `QUANT_BOARD_AUTO_SYNC_BATCH_SIZE` | 单轮自动同步最多处理多少条 outbox，默认 `50` |

自动同步默认关闭。打开后只消费到期 outbox，不做全量 `push-backup`，避免服务启动时把大量历史数据误推到 Supabase。全量补推仍必须手动调用 `push-backup` 或 CLI。

## 分阶段落地

### M0：文档和合同冻结

验收：

- 新增本文作为数据库迁移主计划。
- README、路线图、架构、API/CLI、AI 协作规范和根 AGENTS.md 都引用或同步本文规则。
- 文档明确存储、同步、快照、API/CLI 合同变更必须同批更新文档。

### M1：SQLite 主库合同收敛

验收：

- 所有导入、Golden、回测、优化写入都以 SQLite 为主链。
- 数据表字段能保留可复现所需关键字段。
- 空数据、NaN、缺字段、时间乱序和低样本量仍走质量门禁，不因备份机制降级。

### M2：Supabase 镜像写入

验收：

- 配置 Supabase 后，正式写入先落 SQLite，再镜像到 Supabase。
- Supabase 写入失败有结构化诊断。
- `push-backup` 能补偿历史 SQLite 记录。
- `sync_outbox` 已覆盖快照 ingest、数据集 bundle、回测、优化和 Golden 业务对象。
- 自动同步可按配置启动，只推送到期 outbox；Supabase smoke 探针可验证真实云端写读删。

### M3：读取回退与 failover 写入

验收：

- SQLite 读取失败或本地缺失目标记录时，能按业务键从 Supabase 回退。
- SQLite 不可用但 Supabase 可写时，关键写入能临时落备份库；该能力未完成前，写接口必须明确返回不可用，不能伪装成功。
- 恢复后 `pull-backup` 能把备份记录拉回 SQLite。

### M4：冲突诊断和恢复演练

验收：

- 同键同 hash 幂等跳过。
- 同键不同 hash 标记冲突，不自动覆盖。
- 有文档化的主库损坏恢复流程。
- 测试覆盖 push、pull、回退、冲突、Supabase 不可用和 SQLite 不可用。

## 验证清单

文档验收：

- [README.md](README.md) 索引包含本文。
- [development-roadmap.md](development-roadmap.md) 指向本文，不重复维护细节。
- [architecture.md](architecture.md) 的存储拓扑与本文一致。
- [api-cli.md](api-cli.md) 的同步接口字段与本文一致。
- [AI_COLLABORATION.md](AI_COLLABORATION.md) 明确合同改动必须同批更新文档。
- 根 [AGENTS.md](../../AGENTS.md) 明确跨项目协作规则。

代码验收：

- `quant-board` 目录下测试覆盖 SQLite 主库、Supabase 备份、读回退和恢复。
- API/CLI 对同一服务层行为一致。
- `SUPABASE_SECRET_KEY` 只在后端读取，不进入前端构建产物。
- 失败时返回结构化原因，不用空对象或空报告代表成功。

## 文档维护规则

以下任一改动必须同批更新相关文档：

- 存储拓扑、主备角色、读写优先级或 failover 规则。
- Supabase 表、`type` 枚举、payload 结构或恢复策略。
- SQLite 表字段、索引、业务键、唯一约束或迁移策略。
- 快照入库合同、快照类型默认值或质量门禁规则。
- API/CLI 请求字段、响应字段、错误结构或同步接口语义。
- 回测、优化、Golden 记录的可复现字段。

如果代码和文档不一致，后续协作者应先记录差异，再按任务范围修正文档或代码；不能静默扩大实现范围。
