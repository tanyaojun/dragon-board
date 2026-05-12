# Dragon Board 全项目 MongoDB 收口记录

## 成功标准

1. QuantBoard 后端测试不受本机 `.env.local` 的 Mongo/SQLite 口径泄漏影响。
2. MongoDB 作为运行主库时，快照读取、回测新建、优化新建和研究结果读取有自动化覆盖。
3. Dragon Board 根项目前端验证链路完成：单测、RankTrend、类型检查、构建。
4. Proxy Server 文档路由验证完成。
5. 文档结论明确 SQLite/Supabase 的剩余定位：旧数据留存/归档，不再是运行主链。
6. MongoDB 正式库只保留 `dragonboard_live` 快照主库和全局基础数据，测试/调试污染数据清理完毕，并有防止 pytest 写入正式库的保护。

## 阶段

- [complete] 建立全项目收口计划与当前状态基线。
- [complete] 修正 QuantBoard 测试环境与 Mongo 迁移验收缺口。
- [complete] 并行验证 Dragon Board 根项目构建与测试。
- [complete] 清理 MongoDB 正式库中的测试/调试数据集和派生研究结果。
- [complete] 运行全量验证并归档结论。

## 已知发现

- QuantBoard 全量测试失败的主因是测试进程读取本机 `.env.local` 后进入 Mongo 模式，导致历史 SQLite/Supabase 用例期望与当前运行口径混用。
- 回测平台在 Mongo 模式下读取 Mongo 快照、写入新的 Mongo 研究集合；旧 SQLite 研究历史缺失只影响旧 run/report 的查询，不阻止新回测和新优化运行。
- 2026-05-12 发现 MongoDB 正式库被测试/调试路径污染，表现为 `/api/datasets` 返回 60 个数据集；根因是 pytest/调试链路曾写入正式 `dragon_board_quant`。

## 本次收口结论

- 运行主链：MongoDB 可以作为 QuantBoard 运行主库；本地 SQLite 和 Supabase 不再是运行依赖。
- 旧数据边界：未迁移的 SQLite 研究历史只影响旧回测/优化报告查询；新回测、新优化、新研究结果写入 MongoDB 后可正常读取。
- 测试口径：QuantBoard 测试默认固定为 SQLite 历史兼容口径，Mongo 当前主链由 `test_mongo_*` 与 `test_mongodb_*` 专项用例显式覆盖，避免本机 `.env.local` 污染全量测试。
- 根项目：Dragon Board 主前端单测、RankTrend、类型检查和构建均通过；完整测试套件在并发负载下需要 10 秒超时窗口。
- 代理服务：`/openapi.json` 与 `/docs` 文档路由可用；`swagger-ui-dist` 是现有 docs 路由运行依赖。
- MongoDB 正式库清理：已新增 `cleanup-mongodb-datasets` CLI；默认 dry-run，`--apply` 只删除非保留 dataset 及其可追踪派生研究数据。实际执行后 `/api/datasets` 只返回 `dragonboard_live`。
- 正式快照补数：已新增 `backfill-empty-mongodb-snapshots` CLI；对 2026-05-08 调试期产生的 5 个空股票快照，按同类型同交易日最近非空 frame 复制股票行，并在 frame `metadata.backfill` 和 `qualityFlags` 中留痕。
- 测试防线：pytest 默认 `QUANT_BOARD_MONGODB_DATABASE=dragon_board_quant_pytest`；如果 pytest 误连 `dragon_board_quant`，`get_runtime_mongodb_database()` 会直接拒绝。

## 验证记录

- `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_mongo_research_repository.py tests/test_mongodb_runtime_switch.py tests/test_mongodb_migration.py tests/test_mongodb_backup.py -q`：62 passed。
- `cd quant-board; .\.venv\Scripts\python.exe -m pytest -q`：272 passed。
- 根项目并行验证：`pnpm test` 306 tests passed；`pnpm test:ranktrend` 103 tests passed；`pnpm typecheck:ranktrend` passed；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` passed；`pnpm build` passed。
- `cd proxy-server; node --test __tests__\docs.test.mjs`：2 passed。
- `cd quant-board; .\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-datasets --apply`：删除 59 个非保留 datasets、867 snapshot records/frames、1604 stock rows、74 sector rows、61 backtest runs 及派生研究结果；保留 `dragonboard_live`。
- `GET http://127.0.0.1:8000/api/datasets`：仅返回 `dragonboard_live`，519 frames、109936 stock rows、8353 sector rows。
- `cd quant-board; .\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --apply`：补齐 5 个空股票快照，共插入 1004 条 `snapshot_stock_rows`；`dragonboard_live.stockRowCount` 更新为 110940。
- `cd quant-board; .\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour`：通过，`emptyFrames=[]`。

## 剩余风险

- 旧 SQLite/Supabase 相关代码仍保留为历史兼容和迁移/回归测试资产，不建议立即删除数据库文件或旧代码路径。
- Vite 构建仍有既有 chunk 警告：`ThemeFacade.ts` 同时被动态和静态导入，不影响构建通过。
- FastAPI `on_event` 和 `datetime.utcnow()` 有弃用警告，属于后续技术债，不影响本次 MongoDB 收口验收。
- 5 个空股票快照已补齐，但补齐数据来自邻近快照复制，不是原始重新采集数据；已通过 `backfilled_from_nearest_snapshot` 标记保留可追溯性。
- 仍有部分 frame 的 sector rows 为 0；这与 frame 声明计数一致，未作为结构错误处理。
