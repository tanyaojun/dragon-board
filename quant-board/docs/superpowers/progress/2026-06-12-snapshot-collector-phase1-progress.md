# 后端快照采集器 Phase 1 实施进度

> 2026-06-12 · 分支 `quantboard-backend-snapshot-collector` · 30 文件 · +10065 行

## 已完成

### 基础设施

- [x] **Task 0** — 隔离工作区 `D:\dragon-board-worktrees\quantboard-backend-snapshot-collector`，基线测试通过
- [x] **Task 1** — 从 `backend/main.py` 提取 `normalize_snapshot_ingest()` 到 `backend/data/snapshot_ingest_normalizer.py`，解除循环导入
- [x] **Task 3** — 9 个 `QUANT_BOARD_SNAPSHOT_COLLECTOR_*` 环境变量（默认关闭 + shadow-only）、`SnapshotRepository` Protocol、`service_factory`

### 核心模块

- [x] **Task 2** — `SnapshotSlot` 冻结数据类 + 四类槽位表（quarter_hour/half_hour/hourly/daily，与前段 `schedule.ts` 对齐）+ 交易日历和 grace window 逻辑
- [x] **Task 4** — 质量门禁：6 项硬阻断（空股票行、缺失标识、热榜全败、无效代码、时间戳越界、非法 live dataset）+ 5 项软告警（行情缺失、depth 缺失、L1 资金流、题材缺失、延迟采集）
- [x] **Task 5** — `python-bridge` 新增 `GET /api/quotes/snapshot?codes=...` 只读 HTTP 端点，不依赖浏览器 WebSocket 订阅
- [x] **Task 6** — `build_ingest_payload()` 将 `MarketDataContext` 转为 normalizer 接受的 ingest dict，覆盖 RankTrend 必需的稳定字段
- [x] **Task 7** — 三个 transitional Provider（`ProxyHotlistProvider`、`BridgeQuoteProvider`、`ThemeMappingProvider`）+ provider → builder → normalizer 全链路合约测试

### 服务与接口

- [x] **Task 8** — `SnapshotCollectorService` 完整编排（run_once / backfill_slots / get_status / get_runs / audit），含 dry-run、dedup、质量阻断全流程
- [x] **Task 9** — 5 个 FastAPI 路由：`GET /api/snapshot-collector/status`、`POST run-once`、`POST backfill-slots`、`GET runs`、`POST audit`
- [x] **Task 10** — 4 个 CLI 命令：`snapshot-collector-status`、`snapshot-collector-run-once`、`snapshot-collector-backfill`、`snapshot-collector-audit`

### 文档

- [x] **Task 11** — 更新 `architecture.md`、`api-cli.md`、`mongodb-migration-plan.md`、`AI_COLLABORATION.md`

### 验证

- [x] **Task 12** — 307 个 collector 测试通过、20 个 bridge 测试通过、21 个 MongoDB 回归测试通过
- [ ] 手动 dry-run：跳过（非交易日 2026-06-12 + 基础设施未运行，测试已通过 mocked provider 覆盖）

### 安全基线

- 默认写 `dragonboard_backend_shadow`，不碰 `dragonboard_live`
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=0` 默认关闭
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=0` 双重保险
- 质量门禁在 MongoDB 写入前阻断无效快照
- dry-run 默认不写库
- 不依赖浏览器页面打开或 WebSocket 订阅

---

## 未完成（后续 Phase）

### Phase 2 — Bridge 订阅池和行情稳定性增强

- QuantBoard 后端维护采样股票池，替代每次 `?codes=` 临时传入
- bridge 行情缺失时结构化错误，不写空快照
- bridge 原 WebSocket 行为保持不变
- 新测试文件：`tests/test_snapshot_collector_bridge_provider.py`

### Phase 3 — 四类快照自动 scheduler

- 启动自动 asyncio 后台任务，按槽位表定时触发采集
- 支持交易日判断、午休、15:00 close grace window
- 并发保护：同 slot 不重复采集
- 运行记录写入 `snapshot_collector_runs`
- 新测试文件：`tests/test_snapshot_collector_scheduler.py`

### Phase 4 — Shadow vs Live 对比

- 同一交易日同时保留前端 live 和后端 shadow 数据进行对比
- 对比 snapshot ids、slot 完整性、stock row count、sector row count、关键字段缺失率
- 至少连续 2 个完整交易日 shadow 无缺槽、无空帧、无计数漂移
- 15:00 `half_hour` 和 `daily` 稳定完整

### Phase 5 — Dragon Board 前端生产职责退役

- 前端配置开关，默认关闭 `snapshot.sweep` 正式写库
- `snapshotFacade.save*` 保留手动诊断入口
- 前端读取继续走 QuantBoard API
- 修改文件：`src/services/snapshot/` 相关

### Phase 6 — 正式切换

前置门槛：
- shadow 连续通过审计
- MongoDB 全量备份完成并验证
- `verify-mongodb-migration` 对 live 和 shadow 均通过

切换步骤：
1. 停止前端正式快照自动写入
2. MongoDB 全量备份
3. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live`
4. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1`
5. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=1`
6. 重启 QuantBoard 后端
7. 当天收盘后执行审计，连续观察至少一个完整交易日

### Phase 7 — proxy-server 迁移或收编

- 把 proxy-server 中正式数据源逻辑迁入 QuantBoard 后端
- proxy-server 退役或重定位为独立 Market Data Service
- Dragon Board 前端最终不直接依赖 proxy-server

---

## 文件清单

### 新增（22 个）

```
quant-board/backend/data/snapshot_ingest_normalizer.py
quant-board/backend/snapshot_collector/__init__.py
quant-board/backend/snapshot_collector/models.py
quant-board/backend/snapshot_collector/slots.py
quant-board/backend/snapshot_collector/providers.py
quant-board/backend/snapshot_collector/builder.py
quant-board/backend/snapshot_collector/quality_gate.py
quant-board/backend/snapshot_collector/state.py
quant-board/backend/snapshot_collector/repository_port.py
quant-board/backend/snapshot_collector/service.py
quant-board/backend/snapshot_collector/service_factory.py
quant-board/backend/api/snapshot_collector_routes.py
quant-board/tests/test_snapshot_collector_slots.py
quant-board/tests/test_snapshot_collector_quality_gate.py
quant-board/tests/test_snapshot_collector_builder.py
quant-board/tests/test_snapshot_collector_providers.py
quant-board/tests/test_snapshot_collector_contract.py
quant-board/tests/test_snapshot_collector_service.py
quant-board/tests/test_snapshot_collector_mongo_integration.py
quant-board/tests/test_snapshot_collector_api.py
quant-board/tests/test_snapshot_collector_cli.py
python-bridge/test_quote_snapshot_api.py
```

### 修改（8 个）

```
quant-board/backend/main.py
quant-board/backend/cli.py
quant-board/backend/settings.py
python-bridge/main.py
quant-board/docs/architecture.md
quant-board/docs/api-cli.md
quant-board/docs/mongodb-migration-plan.md
quant-board/docs/AI_COLLABORATION.md
```
