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
- 设计明确记录截至 Phase 4 `service_factory` 只挂载 `ProxyQuoteProvider`，`depth` 缺失率 100%，题材运行时/市场情绪/涨停池也未接入；这些不阻断 Phase 4 槽位审计，但阻断 live cutover。
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
