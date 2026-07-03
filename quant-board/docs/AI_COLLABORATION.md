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
- Fusion 候选池历史语义：`GET /api/backtests/{run_id}/fusion-projections` 以 `ranktrend_early_big_move_v3_lifecycle_fusion` 为唯一策略锚点，必须基于 `signals + trades + tradeEvents/openPositions` 构建 projection rows；不得按股票代码把整次回测粗暴折叠成一条。
- 存储主链：当前运行主库是 MongoDB。SQLite/Supabase/Parquet 旧链路只保留为迁移前历史说明、审计/离线备份资产或 Mongo 模式下显式禁用的维护入口；实施状态、备份恢复和禁用清单以 [mongodb-migration-plan.md](mongodb-migration-plan.md) 为准。
- 当前同步批次：MongoDB 模式不再登记 SQLite/Supabase `sync_outbox`，不再运行 Supabase 自动同步、`push-backup`、`prune-backup` 或 SQLite 90 天明细归档作为生产链路；旧 API/CLI 在 Mongo 模式下应返回 410 或拒绝执行。
- MongoDB 替换 IndexedDB/SQLite 的当前切口：Dragon Board 正式写入和读取仍只通过 QuantBoard 后端 API；`POST /api/snapshots/ingest` 写入 MongoDB，`GET /api/snapshots/frames`、`/api/snapshots/records`、`/api/snapshots/stock-rows`、`/api/snapshots/sector-rows` 从 MongoDB 读取并保持 camelCase 字段合同。IndexedDB 和历史 JSON 只作为迁移前来源，不再作为正式 fallback。
- 题材映射当前切口：Dragon Board `ThemeDataService` 正式读口调用 QuantBoard `GET /api/themes/mapping`，数据来自 MongoDB 题材集合；旧 `themeDATA.db` 和旧浏览器 `ThemeDataDB/theme_mapping` 只作为迁移源或审计参考。
- failover 当前切口：不保留 SQLite + Supabase 运行时降级路径。MongoDB 不可用时正式接口必须结构化失败，不返回空列表或 `backup_only` 伪装成功。
- 题材模块 V2：Dragon Board 快照会写入稳定题材列，QuantBoard 回测会生成 `ThemeCandidateSupport`。默认 `useThemeFactorForExecution=false`，题材只做候选解释；只有显式开启时才参与置信度调整和拥挤风险降级。
- 题材模块 V12 目标：ThemeTrend 作为与 RankTrend 并列的 QuantBoard 研究链，承接题材趋势、题材共振回测、优化、API/CLI 和报告合同。当前已进入可运行主链，但 TS golden 多场景自动导出、walk-forward/样本外报告和真实 bayesian/tpe 搜索器仍是后续深化项。
- V12 Phase 1 已完成：ThemeTrend 研究数据合同（`ThemeFactorFrame`、`ThemeStockExposureFrame`、`ThemeSignalRow`、`ThemeQualityReport`）、研究结果集合/表、`ThemeResearchRepository` 和 `ThemeResearchService`（从正式快照事实回放构建题材研究帧，不修改题材基础映射）。所有记录均保留完整溯源链，质量门禁返回结构化失败。
- V12 存储口径：MongoDB 模式下 ThemeTrend 新研究结果进入 MongoDB 研究集合；旧 research SQLite 和 `themeDATA.db` 只作为迁移前历史口径，不再作为运行主库。
- V12 边界：Dragon Board 根项目不新增回测平台；共振策略以 RankTrend 候选为主，ThemeTrend 只能辅助排序、置信度、拥挤风险降级和解释，不得独立制造买入信号。
- V12 策略口径：`theme_rotation`、`leader_theme_confirmation`、`hotlist_theme_confluence` 必须在执行信号中保留独立入场、降级、过滤和解释字段；Dragon Board 只展示 QuantBoard 研究摘要，不在根项目实现交易模拟。
- L2 资金流口径：`estimated_l1` 只允许作为观察指标；正式资金流回测必须使用 `broker_l2` 或 `official_l2`，并在质量门禁中保留 `capital_flow_source`、`capital_flow_confidence`、`money_flow_estimated`。
- 实验性后端快照采集器：`backend/snapshot_collector/` 当前默认仍处于 shadow-only 阶段，默认禁用，写目标限定为 `dragonboard_backend_shadow`。Phase 6 正式切换 `dragonboard_live` 只能在完成备份和门禁后显式设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live` 与 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1`，CLI 预检和 quality gate 才会放行。本机观察实例由 Windows 计划任务守护并使用独立端口 `8001`，不得替换日常 `8000` API；守护健康判定必须使用 MongoDB `ping`、proxy/bridge 结构化健康响应和 collector scheduler shadow 合同，不得仅凭端口开放。`proxy-server` 只复用健康的 `127.0.0.1:3000`，缺失或不健康时标记 `blocked`，不得从隔离 worktree 启动代理接管主看板端口。`force` 重采写入失败时必须恢复替换前快照事实。题材 rows 必须来自共享全市场题材热度服务并与 theme count 一致；空 sector rows 只允许作为替换前历史缺口记录，不得成为新帧豁免。该模块的改动必须通过以下测试链路验证：
  - 后端 pytest：`tests/test_snapshot_collector_*.py`（包含 supervisor 自动运行合同，并覆盖 models、slots、providers、builder、quality_gate、state、service、service_factory、routes 和 repository 合同）
  - python-bridge 接口测试：`python -m unittest discover python-bridge -p "test_*.py"`（覆盖 `GET /api/quotes/snapshot?codes=...` 行情接口）
  - MongoDB 迁移审计命令：`.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour`
- 通达信 L2 能力边界以当前 bridge 源码验证结果为准，不得把五档 L1 描述成官方客户端级 L2；任何 L2 相关功能描述必须标注已验证的 bridge 能力来源。

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
9. MongoDB 主库、备份恢复、禁用旧维护入口、快照入库和 API/CLI 合同变更，必须同批更新对应文档。
10. Dragon Board 前端不得直连 MongoDB 或 Supabase；正式快照写库必须走 QuantBoard 后端 API。正式快照判重以后端 `dataset_id + snapshot_id` 为准，不得再以浏览器 IndexedDB 记录存在性作为正式保存条件。
11. 不得重新引入 Supabase `snapshots.payload` 兼容备份方案，也不得恢复 SQLite/Supabase 运行时 failover。
12. Supabase、旧 Parquet 归档和 SQLite archive retention 只属于迁移前历史口径；MongoDB 主库明细不得因旧 retention/归档任务被删除。
13. 不得把回测、优化、Golden 或报告大 JSON 重新塞进 Supabase Free 版备份链路；MongoDB 模式下新研究结果进入 MongoDB 研究集合。
14. DuckDB 只能作为后端只读归档查询引擎，不允许新增前端可传 SQL 的接口。
15. IndexedDB 替换已经进入 MongoDB 后端读写口阶段；后续不得恢复浏览器 IndexedDB 作为正式读写 fallback，历史数据只作为迁移源或审计参考。
16. 迁移 DataLayer 的 IndexedDB 读写入口时，不得删除或重命名 `SnapshotRecord`、`SnapshotFrameBundle`、`SnapshotStockRow`、`SnapshotSectorRow` 已有字段；MongoDB 后端 API 必须承接字段并以 camelCase 返回。
17. 删除 IndexedDB 历史前必须先完成后端迁移收口与人工验收，确认 MongoDB 正式集合行数/文档数与迁移源一致；不要把浏览器端旧 IndexedDB 校验/补齐入口当成正式合同。正式快照缓存默认关闭后，不得重新在 `DataLayer` 或 `snapshotFacade` 正式读写口恢复 IndexedDB fallback；QuantBoard 后端不可用时正式读取必须显式失败。
18. 优化结果只生成候选参数，不得自动写回 Python、TypeScript、API、CLI、前端表单或文档默认值；CLI 必须支持 `tpe` 和异步提交 `--no-wait` 口径。`optuna_tpe` 仅作为后端兼容别名。
19. 题材因子不得绕过 RankTrend 独立制造买入信号；执行开关开启时也只能辅助已有候选分层。
20. 题材基础映射新增或更新必须进入 QuantBoard MongoDB 题材集合；不得重新把浏览器 IndexedDB 或旧 `themeDATA.db` 当成运行主库，也不得把题材静态映射混入快照事实集合或研究集合。
21. V12 ThemeTrend 回测、优化、signals、quality report 和报告结果在 MongoDB 模式下必须归属 MongoDB 研究集合；不得进入 Supabase 或旧 `themeDATA.db`。
22. 新增 ThemeTrend API/CLI 合同时必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`，默认 `snapshot_type=half_hour`，`quarter_hour` 只能显式传入。
23. 文档或实现涉及 ThemeTrend 时，必须区分“已完成能力”和“V12 目标/拟新增合同/首批落地”，不得把计划中的接口描述成已上线事实。
24. 资金流策略正式回测不得默认消费 L1 估算主力资金；如显式允许 `estimated_l1`，报告必须标注实验口径和高风险。
25. `trade_journal` 在 fusion 候选池语义中只能作为 execution overlay，不得反推 `triggered_wait_entry`、`active_holding`、`exit_signaled` 或 `closed`。

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
- 修改存储、同步、快照入库、数据库表字段、恢复策略或 API/CLI 请求响应字段时，必须同批更新 [mongodb-migration-plan.md](mongodb-migration-plan.md)、[architecture.md](architecture.md)、[api-cli.md](api-cli.md) 和必要的用户/路线图文档。若只涉及迁移前 SQLite/Supabase 历史说明，再同步 [database-migration-plan.md](database-migration-plan.md)。
- 发现旧文档把 Dragon Board 根项目描述为回测平台时，必须删除或改为当前 QuantBoard 口径。

## 给后续 AI 的上下文提示

开始新任务时优先阅读：

1. [README.md](README.md)
2. [mongodb-migration-plan.md](mongodb-migration-plan.md)，如果任务涉及当前存储、同步、快照入库、恢复或 API/CLI 合同
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
