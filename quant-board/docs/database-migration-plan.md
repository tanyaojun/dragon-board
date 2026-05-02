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

Supabase 侧为了兼容已有空表，首期备份记录落在 `snapshots` 表中，通过 `type` 区分 QuantBoard 业务对象：

- `qb_dataset`
- `qb_snapshot_bundle`
- `qb_backtest_run`
- `qb_optimization_run`
- `qb_golden_case`

快照明细首期以 bundle 写入 `payload`，避免在 Supabase 表结构完全迁移前破坏已有数据。后续若拆成 Supabase 明细表，必须先更新本文的表合同和恢复流程。

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
3. 以同一业务对象构造 Supabase 备份记录。
4. Supabase 写入成功时记录同步成功状态。
5. Supabase 写入失败时不得回滚已成功提交的 SQLite 业务事务，但必须返回或记录结构化同步诊断。

关键要求：

- SQLite 事务失败时，不得声明业务写入成功。
- Supabase 镜像失败不应阻塞本地研究主链，但必须可被 `push-backup` 后续补偿。
- 备份 payload 必须包含足够字段，能重建 SQLite 主库里的业务对象。
- `dataset_id`、`snapshot_type`、`run_id`、`case_id` 等业务键必须稳定，不能由恢复流程重新随机生成。
- 对同一业务键重复同步必须幂等，不能产生重复数据或覆盖更新更晚版本。

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

必须返回：

- 推送对象类型。
- 扫描数量、成功数量、跳过数量、失败数量。
- 失败对象的业务键和结构化原因。
- 本次同步是否完整成功。

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
