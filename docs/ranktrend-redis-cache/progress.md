# RankTrend Redis Cache Progress

## 2026-05-11

- 确认 Redis 服务运行于 `127.0.0.1:6379`，服务自动启动。
- 完成 RankTrend、量比、热度三条计算输入链路核查。
- 完成两个并行评审：
  - 后端：Redis/SQLite/Supabase 一致性与 key/失效策略。
  - 前端：RankTrend UI 稳定性和 base-merge 中间态。
- 已将设计、任务计划、发现和进度写入 `docs/ranktrend-redis-cache/`。
- Task 1 TDD 完成：新增 `quant-board/tests/test_snapshot_cache.py`，实现 `SnapshotCacheKeyBuilder` 和 Redis 相关 settings。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py -q`，3 passed。
- Task 2 TDD 完成：实现 `SnapshotRedisCache.get_response/set_response`、空结果短 TTL、Redis 异常 fail-open。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py -q`，6 passed。
- Task 3 基础 TDD 完成：实现 response key 反向索引登记和按索引失效，不使用 broad `KEYS`。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py -q`，7 passed。
- 增加 Redis client 工厂和 `redis>=5.0.0` 依赖，disabled 时返回 None。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py -q`，9 passed。
- Task 4 部分完成：`/api/snapshots/frames` 接入 Redis read-through cache，使用 resolved dataset id 生成 key，响应保留 `source` 并追加 `cache`。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py tests\test_quant_board.py::test_snapshot_frames_api_uses_snapshot_cache tests\test_quant_board.py::test_snapshot_frames_api_reads_sqlite_frame_bundles -q`，11 passed。
- Task 4 完成：`/api/snapshots/records`、`/stock-rows`、`/sector-rows` 接入同一 read-through helper。验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py tests\test_quant_board.py::test_snapshot_frames_api_uses_snapshot_cache tests\test_quant_board.py::test_snapshot_frames_api_reads_sqlite_frame_bundles tests\test_quant_board.py::test_snapshot_detail_read_apis_use_sqlite tests\test_quant_board.py::test_snapshot_detail_list_apis_use_snapshot_cache -q`，13 passed。
- Task 5 完成：`POST /api/snapshots/ingest` 在 SQLite 成功写入后按 dataset/date/snapshot 反向索引失效缓存，失效过程 fail-open。验证：后端目标测试 14 passed。
- Task 6 完成：`RankTrendSignalService.updateStockSignals()` 对 `rankTrend: null` 不再清空旧 RankTrend，只更新 coverage warning。验证：`pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts --reporter=dot`，5 passed。
- 组合验证中 `technicalSignalAnalyzer.test.ts` 失败，原因是当前工作区 RankTrend 默认 MACD 参数为 12/26/9 后样本预期变化；这不是 Redis/UI 保留改动引入。
- 文档合同已同步到 `quant-board/docs/api-cli.md`、`quant-board/docs/architecture.md`、`quant-board/docs/database-migration-plan.md`。
- 最新后端目标验证：`.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py tests\test_quant_board.py::test_snapshot_frames_api_reads_sqlite_frame_bundles tests\test_quant_board.py::test_snapshot_frames_api_uses_snapshot_cache tests\test_quant_board.py::test_snapshot_detail_read_apis_use_sqlite tests\test_quant_board.py::test_snapshot_detail_list_apis_use_snapshot_cache tests\test_quant_board.py::test_snapshot_ingest_invalidates_snapshot_cache_indexes -q`，14 passed。
- 最新前端目标验证：`pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts src/services/dataLoader/__tests__/DataLoaderFacade.test.ts --reporter=dot`，24 passed。
- 当前 QuantBoard `.venv` 已安装 `redis>=5.0.0`，真实 Redis smoke 使用 `hellobiga:dragon-board:local:smoke:codex` 完成 set/get/delete，输出 `ok`。
