# RankTrend Redis Cache Task Plan

## Status

- Phase 0: Redis 环境与计算链路核查 - complete
- Phase 1: 设计和计划落盘 - complete
- Phase 2: 后端 Redis cache 基础设施 - complete
- Phase 3: 接入 QuantBoard 四个快照读 API - complete
- Phase 4: ingest 成功后精确失效 - complete
- Phase 5: 前端 RankTrend 展示字段保留 - complete
- Phase 6: 文档、验证和收尾 - complete

## Success Criteria

- Redis 缓存只作为快照读模型 cache，不替代 SQLite 事实源。
- RankTrend 历史输入、量比历史输入和热度输入链路通过 Redis 降低重复读延迟。
- 行情列表在 `base-merge` 中间态保留上一轮【变化%】和【置信度】。
- Redis 异常、`backup_only`、归档 mixed 读口不破坏现有 SQLite/Supabase 合同。

## Work Breakdown

### Phase 2: Backend Cache Infrastructure

- 新增 QuantBoard Redis 配置。
- 新增 `backend/data/snapshot_cache.py`。
- 实现 key builder、query normalization、namespace 隔离、TTL 选择。
- 实现 read-through get/set 和反向索引登记/失效。
- 单测覆盖 key 稳定性、namespace 隔离、Redis 异常 fail-open。

### Phase 3: API Integration

- 接入 `/api/snapshots/frames`。
- 接入 `/api/snapshots/records`。
- 接入 `/api/snapshots/stock-rows`。
- 接入 `/api/snapshots/sector-rows`。
- 响应保留原有 `source`，追加 `cache` 诊断字段。

### Phase 4: Ingest Invalidation

- 仅在 SQLite commit 成功后失效。
- 根据 ingest records/frames/rows 派生 `dataset_id`、`snapshot_type`、`trading_date`、`snapshot_id`。
- 按反向索引删除 response keys。
- `backup_only` 不回填 Redis。

### Phase 5: Frontend Stability

- 在 `base-merge` 合并阶段显式保留上一轮 RankTrend 展示字段。
- `applySignalsToMerged()` 无新结果时不清空旧结果。
- 添加测试验证 base merge 后旧 `rankTrend/finalConfidence/rankChange` 保留。

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| 先写了未批准的 Redis 测试 | 早于设计审批执行 TDD | 已撤销该测试，重新按设计/计划流程执行 |
| Python dict 合并误写为 JS spread | Task 2 首次实现 | 改为 `{**payload, ...}` |
| 集成测试 patch 不生效 | main.py 直接导入 `get_snapshot_redis_cache` | 改为通过 `backend.data.snapshot_cache` 模块调用，便于测试替换 |
| ingest 失效取不到日期和类型 | `normalize_snapshot_ingest()` 返回 dict 列表，代码只用 `getattr` | 增加 dict/object 双路径字段读取，并让失效 fail-open |
| RankTrend 保留测试引用不相等 | DataLayer 归一化会复制对象 | 改用结构等价断言，行为目标是字段不被清空 |
| `technicalSignalAnalyzer.test.ts` MACD 断言失败 | 当前工作区 RankTrend 默认 MACD 为 12/26/9，测试样本不再覆盖旧预期 | 与本次 Redis/UI 保留改动无直接关系，记录为既有 RankTrend 参数变更影响 |
| QuantBoard venv 缺少 Python Redis client | 真实 Redis smoke 首次 import 失败 | 已执行 `.\.venv\Scripts\python.exe -m pip install "redis>=5.0.0"`，随后真实 Redis set/get/delete smoke 通过 |
