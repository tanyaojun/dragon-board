# AI 协作规范

本文是 QuantBoard 项目的固定协作合同。后续 AI 助手进入项目时，必须先读本文件和 [README.md](README.md)，再根据任务读取相关专题文档。

## 当前首期方案

- 项目目标：把 dragon-board 的 `rankTrend` TypeScript 分析链落地为 Python 后端可回测、可优化、可展示的 QuantBoard。
- Golden 标准：`src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/*`、`src/type/rankTrendDefaults.ts`。
- 当前主链：QuantBoard 负责参数研究、回测、优化、交易模拟和报告展示。
- 参数优化口径：优化是 `backend/optimization/**` 独立模块，负责搜索方法、目标函数、异步任务状态和实验记录；它调用回测引擎执行 trial，但不得把搜索逻辑塞回 `backend.core.backtest`。
- 优化方法口径：正式搜索方法只有 `grid`、`random`、`bayesian`、`tpe`。`method=bayesian` 是 Optuna `GPSampler` 高斯过程优化；`method=tpe` 对应 Optuna `TPESampler`。`method=optuna_tpe` 只作为后端兼容别名保留，不在前端和 CLI 展示为独立方法。
- 优化任务口径：`POST /api/optimizations/rank-trend` 异步返回 `status=running` 和 `runId`；`GET /api/optimizations/{run_id}` 只返回 `running`、`completed` 或 `failed`。
- Dragon Board 根项目只提供实时看板、快照数据和 TypeScript golden 导出。
- 默认快照：`snapshot_type=half_hour`。
- 可选快照：`quarter_hour` 可用于细颗粒度研究，但必须显式选择，不能替代默认口径。
- 存储主链：SQLite 分为快照事实库 `quant_board_snapshots.db` 和研究库 `quant_board_research.db`；Supabase 是后端专用快照备份库，只同步快照事实表和轻量 outbox，实施和恢复规则以 [database-migration-plan.md](database-migration-plan.md) 为准。
- 当前同步批次：`sync_outbox` 只覆盖快照 ingest、数据集 bundle；回测、优化和 Golden 保存在 research SQLite，不进入 Supabase Free 版备份目标。历史 JSON 迁移入口是 `POST /api/migrations/snapshots/import-json`；自动同步默认关闭，只补传到期 outbox。
- SQLite 替换 IndexedDB 的当前切口：Dragon Board 正式写入先查询 QuantBoard SQLite 是否已有同一 `snapshot_id`，缺失时走 `POST /api/snapshots/ingest`；正式读口由根前端 `src/services/snapshot/backendRead.ts` 统一调用 QuantBoard `GET /api/snapshots/frames`、`/api/snapshots/records`、`/api/snapshots/stock-rows`、`/api/snapshots/sector-rows`；IndexedDB 快照缓存默认关闭，只作为迁移源和显式缓存。浏览器端旧的 IndexedDB 校验/补齐入口与 `five_minute` 本地入口已收口，不再作为正式合同。
- failover 当前切口：SQLite 主库不可用但 Supabase 同构备份库可写时，`POST /api/snapshots/ingest` 可返回 `status=backup_only` 并写入备库；SQLite 恢复后必须执行 `pull-backup` 收敛，不能把 `backup_only` 当作本地主库已恢复。

## 工作边界

当任务明确限定为文档时：

- 只修改 `quant-board/docs/**`。
- 不修改 `quant-board/backend/**`、`quant-board/frontend/**`、根项目 `src/**`。
- 如发现代码和文档不一致，先记录在文档中，不主动改代码。

当任务允许实现时：

- 先定位现有模块和测试，再做最小改动。
- 不回滚、不覆盖他人正在修改的文件。
- 如果发现未跟踪或已修改文件，默认认为是用户或其他协作者的工作成果。

## 回答风格

- 全程中文。
- 结论先行，说明问题、原因、改法、影响面。
- 面向个人开发者，Python 后端概念要解释清楚，尽可能展开相关教学。
- 不用空泛建议；每次输出都要能指导下一步实现或验收。

## 硬约束

1. `rankTrend` TypeScript 是 golden 标准。
2. QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
3. 默认 `snapshot_type` 是 `half_hour`。
4. `quarter_hour` 是可选项，不是默认项。
5. 回测和优化必须保存 `random_seed`、`config_hash`、`dataset_id`、`snapshot_type`、`strategy_version`。
6. 数据质量门禁失败必须结构化返回，不允许静默吞掉。
7. Python 端 rankTrend 输出字段必须能和 golden case 对齐。
8. 前端展示不得把 `finalSignal` 当成唯一交易结论，应优先展示状态、候选分层、风险、样本质量和交易解释。
9. SQLite 主库、Supabase 备份库、同步接口、快照入库和 API/CLI 合同变更，必须同批更新对应文档。
10. Dragon Board 前端不得直连 Supabase；正式快照写库必须走 QuantBoard 后端 API。正式快照判重以 SQLite/后端 `snapshot_id` 为准，不得再以浏览器 IndexedDB 记录存在性作为正式保存条件。
11. 不得重新引入 Supabase `snapshots.payload` 兼容备份方案；云端表、业务键和索引必须和 SQLite 快照事实库同构。
12. 不得把回测、优化、Golden 或报告大 JSON 重新塞进 Supabase Free 版备份链路；大型研究结果只属于 research SQLite 或报告文件目录。
13. 逐步替换 IndexedDB 时必须先接入 SQLite 读接口；确认迁移和行数校验完成前，不得删除浏览器历史数据或关闭迁移工具。
14. 迁移 DataLayer 的 IndexedDB 读写入口时，不得删除或重命名 `SnapshotRecord`、`SnapshotFrameBundle`、`SnapshotStockRow`、`SnapshotSectorRow` 已有字段；SQLite 后端必须承接字段并以 camelCase 返回。
15. 删除 IndexedDB 历史前必须先完成后端迁移收口与人工验收，确认四张事实表全量行数一致；不要把浏览器端旧 IndexedDB 校验/补齐入口当成正式合同。正式快照缓存默认关闭后，不得重新在 `DataLayer` 或 `snapshotFacade` 正式读写口恢复 IndexedDB fallback；QuantBoard 后端不可用时正式读取必须显式失败。
16. 优化结果只生成候选参数，不得自动写回 Python、TypeScript、API、CLI、前端表单或文档默认值；CLI 必须支持 `tpe` 和异步提交 `--no-wait` 口径。`optuna_tpe` 仅作为后端兼容别名。

## 推荐执行流程

1. 定位：用 `rg` 或目录列表确认相关文件。
2. 对齐：确认当前任务涉及哪篇 docs 专题文档。
3. 计划：说明要改什么、为什么、影响哪些文件。
4. 落地：只改必要范围。
5. 验证：文档任务至少检查链接、关键词和文件列表；代码任务运行相关测试。
6. 总结：列出改动文件、验证结果、剩余风险。

## 文档维护规则

- README 只放总览、索引和首期硬约束。
- 专题细节写入对应文档，不把所有内容堆到 README。
- 修改默认值、策略合同、API 合同时，必须同步更新交叉引用文档。
- 修改存储、同步、快照入库、数据库表字段、Supabase payload、恢复策略或 API/CLI 请求响应字段时，必须同批更新 [database-migration-plan.md](database-migration-plan.md)、[architecture.md](architecture.md)、[api-cli.md](api-cli.md) 和必要的用户/路线图文档。
- 发现旧文档把 Dragon Board 根项目描述为回测平台时，必须删除或改为当前 QuantBoard 口径。

## 给后续 AI 的上下文提示

开始新任务时优先阅读：

1. [README.md](README.md)
2. [database-migration-plan.md](database-migration-plan.md)，如果任务涉及存储、同步、快照入库、恢复或 API/CLI 合同
3. [ranktrend-golden.md](ranktrend-golden.md)
4. [ranktrend-python-port.md](ranktrend-python-port.md)
5. 与任务直接相关的专题文档

如果用户要求实现首期功能，推荐顺序是：

1. 数据导入与质量门禁；
2. golden case 生成与校验；
3. Python rankTrend 移植；
4. 回测引擎；
5. API/CLI；
6. 前端展示；
7. 参数优化。
