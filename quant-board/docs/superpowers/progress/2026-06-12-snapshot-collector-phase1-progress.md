# 后端快照采集器 Phase 1-2 实施进度

> 2026-06-12 · 分支 `quantboard-backend-snapshot-collector` · 32 文件 · +10800 行

## 已完成

### Phase 1 — 最小闭环

- [x] **Task 0** — 隔离工作区 + 基线测试
- [x] **Task 1** — 提取 `normalize_snapshot_ingest()` 到 `backend/data/snapshot_ingest_normalizer.py`
- [x] **Task 2** — `SnapshotSlot` 冻结数据类 + 四类槽位表 + 交易日历
- [x] **Task 3** — 9 个 `QUANT_BOARD_SNAPSHOT_COLLECTOR_*` 环境变量 + `SnapshotRepository` Protocol + `service_factory`
- [x] **Task 4** — 质量门禁：6 项硬阻断 + 5 项软告警
- [x] **Task 5** — `python-bridge` 新增 `GET /api/quotes/snapshot?codes=...` HTTP 端点
- [x] **Task 6** — `build_ingest_payload()` 构建 normalizer 接受的 ingest dict
- [x] **Task 7** — 三个 transitional Provider + provider → builder → normalizer 全链路合约测试
- [x] **Task 8** — `SnapshotCollectorService` 完整编排
- [x] **Task 9** — 5 个 FastAPI 路由
- [x] **Task 10** — 4 个 CLI 命令
- [x] **Task 11** — 更新 4 篇正式文档
- [x] **Task 12** — 307 collector + 20 bridge + 21 MongoDB 回归测试通过

### Phase 2 — Bridge 订阅池和行情稳定性增强

- [x] **Bridge 后端订阅池** — `POST /api/quotes/subscriptions` 端点，后端可设置持久采样代码池
- [x] **池缓存刷新** — 订阅池设置时立即 fetch 行情存入缓存，`GET /api/quotes/snapshot` 无 `codes` 参数时回退到池缓存
- [x] **BridgeQuoteProvider 增强** — `set_pool()` 方法 + `collect(use_pool=True)` 模式，使用池缓存而非每次传 codes
- [x] **行情陈旧检测** — `poolStalenessMs` 阈值（默认 30s），超时写入 `SourceHealth.error` 中 `quote_stale` 标记
- [x] **测试** — 8 个新 bridge 池测试 + 21 个新 provider 池测试，全量 28 bridge / 59 provider 通过
- [x] bridge 原 WebSocket 行为完全不变
- [x] `GET /api/quotes/snapshot?codes=...` 显式 codes 模式依然可用

### 安全基线

- 默认写 `dragonboard_backend_shadow`，不碰 `dragonboard_live`
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=0` 默认关闭
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=0` 双重保险
- 质量门禁在 MongoDB 写入前阻断无效快照
- dry-run 默认不写库
- 不依赖浏览器页面打开或 WebSocket 订阅

---

## 未完成（后续 Phase）

### Phase 2 — Bridge 订阅池和行情稳定性增强 ✅ （已完成）

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
quant-board/tests/test_snapshot_collector_bridge_provider.py
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
