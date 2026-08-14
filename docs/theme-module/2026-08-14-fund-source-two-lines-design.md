# 资金数据源两条线方案（2026-08-14）

## 状态

已实施并验证。废弃种子方案、取消 P0/P1 前 100 白名单、清理不可用资金源。

## 背景与问题

1. **行情主页资金覆盖不足**：`/api/health` 实测 `marketFundRefresh.seedEnabled=false`
   （akshare 全市场源被关），`thsFundRefresh.universeCount=226` 但 Redis
   `theme-fund:v3:latest` 与 MongoDB `fund_flow_l2` 当日只有 **163 只**
   （THS L2 受 30 req/min 限流 + 单票失败退避，上午只校准了 163/226 ≈ 72%）。
   缺口约 28% 的股票资金列长期 `--`。
2. **种子方案从未生效**：`ths_web_seed` / `eastmoney_seed` 从没启动（
   `QUANT_BOARD_THEME_FUND_SEED_ENABLED` 默认 false），"首屏全量占位 + 渐进
   L2 校准"效果不佳；冷启动已改由 Redis `dump.rdb` 恢复 L2 数据，种子方案可废弃。
3. **P0/P1 前 100 白名单是错误设计**：前端曾按热度前 100 上报 priorityCodes，
   后端 `_MAX_PRIORITY_CODES=100` 截断，导致行情主页大量股票接收不到资金数据
   （用户前台实测确认）。此前 2026-08-11 已"取消热度池、去 P0/P1 分级"，但
   priority 链路残留未清理。
4. **不可用数据源残留**：东财（`eastmoney`/`eastmoney_seed`，限流不可用）、
   TDX L1 分笔自算（`tdx_transaction`/`tdx_estimate`，非全日完整分笔不可靠）、
   `ths_l2`/`qmt_l2`（历史兼容）仍散落在 source 常量与前端文案中。

## 决策（用户确认）

主力资金数据流严格两条线：

| 线 | 数据源 | source 值 | 范围 | 节奏 |
| --- | --- | --- | --- | --- |
| 1 | 同花顺 mainMonitorDetail L2 主源（权威） | `ths_main_monitor` | 行情主页八平台热榜股票列表（约 200-230 只） | 每批 5 只、并发 4、批间 1s，约 1 分钟轮转一轮（2026-08-14 实测推翻 30 req/min 假设） |
| 2 | akshare 同花顺网页个股资金流（估算） | `akshare_ths_individual` | theme_fund 题材股票列表（约 4000 只） | 5 分钟全量刷新，写入独立 hash `theme-fund:v3:akshare` |

- **热榜只用 L2**：行情主页热榜资金列只接受 `ths_main_monitor`，L2 缺失的股票
  诚实显示 `--`（fail-visible），不用 akshare 估算兜底。
- **akshare 只供题材**：akshare 全市场源启用（`theme_fund_seed_enabled` 默认
  true），写入 `ThemeFundCache`，供后端题材热度聚合（`heat_service`）与
  `GET /api/themes/fund-rows` 消费，不进入行情主页资金列。
- **废弃种子方案**：删除 `ths_web_seed` / `eastmoney_seed` 常量与相关逻辑。
- **取消前 100 白名单**：移除 P0/P1 分级与 priorityCodes 全链路，订阅池 =
  行情列表全部股票，全列表统一轮转。
- **清理不可用源**：删除 `eastmoney` / `tdx_transaction` / `tdx_estimate` /
  `ths_l2` / `qmt_l2` 常量与文案；停 python-bridge 的 `fund_flow_patch` 广播。

## 改动清单

### 后端（quant-board）

- `backend/core/fund_sources.py`：只保留 `ths_main_monitor` +
  `akshare_ths_individual` 两个常量；`SUPPORTED_FUND_SOURCES` 收敛为二者。
- `backend/services/theme/fund_cache.py`：删除本地 `SUPPORTED_FUND_SOURCES`
  重定义（此前覆盖统一入口导致 seed 被误接受）；`FUND_SOURCE_RANK` 改为
  `{akshare_ths_individual: 1, ths_main_monitor: 2}`。
- `backend/core/settings.py`：`theme_fund_seed_enabled` 默认 `true`（akshare
  题材源启用，不再是"种子"开关）。
- `backend/services/market/fund_scheduler.py`：docstring/日志改为"akshare 题材
  资金源"，移除"种子首屏占位"措辞。
- `backend/services/market/fund_stream.py`：删除 `priority_codes` 全链路
  （subscribe/update 参数、`priority_codes()`、`_persisted["priority"]`）。
- `backend/services/market/ths_fund_refresh_scheduler.py`：删除
  `priority_interval_seconds` 构造参数与 status 的 `priorityCount`/
  `priorityIntervalSeconds`。
- `backend/api/market_fund_routes.py`：删除 `_MAX_PRIORITY_CODES=100` 与
  priorityCodes 解析，订阅协议只保留 `codes`。

### python-bridge

- `main.py`：停 `tdx_fund_flow.accumulate_ticks` 累积与 `fund_flow_patch` 广播
  （TDX L1 分笔自算资金流废弃；前端早已 rank 0 不消费）。

### 前端（src）

- `src/config/fundSources.ts`：只保留 `THS_MAIN_MONITOR` +
  `AKSHARE_THS_INDIVIDUAL`。
- `src/services/moneyFlowSourcePriority.ts`：`DASHBOARD_FUND_SOURCE_RANK` 只留
  `THS_MAIN_MONITOR: 5`（行情主页资金列只收 L2）。
- `src/services/marketFundStream.ts`：移除 priorityCodes 参数与 `.slice(0,100)`，
  订阅只发 `codes`。
- `src/services/realtime/RealtimeSubscriptionRegistry.ts`：移除 priority 全链路
  （ownerPriorityCodes / applyMarketFunds 的 priority 参数）。
- `src/services/rankTrend/statusClassifier.ts`：`isEstimatedMoneyFlow` 移除
  `tdx_estimate` 判断。
- `src/components/common/DataTable.vue`：`getMoneyFlowTitle` 移除
  `ths_l2`/`qmt_l2`/`eastmoney`/`tdx_estimate` 分支，只保留 L2 与 akshare 文案。

## 验证

- 后端全量 pytest **1424 passed**（`fund_sources`/`fund_cache`/`fund_stream`/
  `ths_fund_refresh_scheduler`/`market_fund_routes` 相关测试更新）。
- 前端全量 vitest **926 passed**；`vue-tsc` 退出码 0。
- 上线首日人工验证：重启 8000 后观察
  `/api/health` 的 `marketFundRefresh.seedEnabled=true` 且 `running=true`、
  `lastRowCount≈5000`（akshare 全市场）；Redis `theme-fund:v3:latest` 同时含
  `ths_main_monitor`（热榜）与 `akshare_ths_individual`（题材）行；
  行情主页热榜资金列只显示 L2，题材聚合覆盖全市场（遵循 AGENTS.md 第 11 节：
  查实际入库数据，不只看 API status）。

## 回退边界

- 回退不得恢复 `ths_web_seed`/`eastmoney_seed`/`eastmoney`/`tdx_transaction`/
  `tdx_estimate` 资金源，不得恢复 P0/P1 priority 前 100 白名单。
- akshare 题材源失败不影响 THS L2 热榜校准（独立调度器 + 独立熔断）。
- 冷启动资金恢复仍走 Redis `dump.rdb`（L2 last-good），不依赖 akshare。

## 2026-08-14 追加修订（题材分 hash + 刷新提速）

用户反馈两个问题后追加修订：

1. **题材统一用 akshare（估算）**：原方案 `FUND_SOURCE_RANK` 让 L2 覆盖
   akshare 行，导致题材聚合里热榜股票拿到 L2 值、口径混杂。改为 **分 hash 存储**：
   - `ThemeFundCache.put_many`（akshare 全市场）写独立 hash `theme-fund:v3:akshare`
     + 内存 `_akshare`；`put`（L2 单票）仍写 `theme-fund:v3:latest` + 内存 `_latest`。
   - `heat_service.get_fund_rows` 与 `GET /api/themes/fund-rows` 改读
     `get_akshare_latest`（纯 akshare），题材聚合统一估算口径。
   - `MarketFundScheduler` 的盘后冷启动 / Redis 恢复逻辑改针对 akshare hash
     （`has_akshare_redis_data` / `akshare_memory_rows`）。
   - 前端 `ThemeHeatFeed` 移除 fund-stream 的 L2 资金补丁订阅（`applyFundPatch`），
     题材资金只走 HTTP akshare 5 分钟刷新，不再被 L2 实时补丁覆盖。

2. **热榜 L2 刷新提速**：实测（30s 压测，并发 2/4/6 各 10s）证明 THS 无
   30 req/min 硬限流——并发 4 时 18.7 rps 全程 0 429/验证码（并发 6 反而退化）。
   故：并发上限 2→4（`settings.theme_fund_concurrency` /
   `ThsFundRefreshScheduler._base_concurrency` / `ThsMainMonitorService._max_concurrency`），
   批间 sleep 从 `batch_size/30*60=10s` 改为固定 1s。一轮 225 只从约 9 分钟降到约 1 分钟，
   满足「5 分钟内全量轮询刷新」。保留 429/验证码 → 全局冷却 + 并发降 1 的保护。

验证：后端全量 pytest **1424 passed**；前端 `vue-tsc` 退出码 0、
`ThemeHeatFeed.test.ts` 6 passed（删除两个 WS patch 用例）。
