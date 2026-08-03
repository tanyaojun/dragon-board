# Snapshot Collector 全面梳理与优化方案

> 日期：2026-08-03 · 状态：审查完成；P0（独立采集进程 + 硬门禁移除 + 行情字段原料）已全部实施并验证，
> Task 5（文档/收尾）完成；存量字段回填与既有测试文件修复留待后续排期
> 其中"独立采集进程"由 DragonBoardLauncher 核心启动项管理（8001），不建计划任务、不恢复 supervisor.py
> 依据：`AGENTS.md §4.0`、`skills/fail-visible-data-pipelines/SKILL.md`、仓库代码与 MongoDB 实测证据

## 0. 结论（先行）

采集器当前"槽位连续性基本达标、字段与链路能力不足"：

1. **可靠性**：调度器寄生在 8000 uvicorn 进程内且无守护/自动重启；provider 全部经 proxy(3000) 回环到 8000 自身，8000 一旦挂起/繁忙，采集必然失败；错过 5 分钟 grace 窗口即静默丢槽且无自动回补；交易日历强依赖 python-bridge，桥挂会停采一整天。
2. **字段原料**：`snapshot_stock_rows` 的 `pe/pb/cirMV/totalMV/volumeRatio/limitUpPrice/limitDownPrice/leadStatus/themeHeat/themeContribution/themeRole/themeRiskFlags` 实测 0% 覆盖，`snapshot_sector_rows` 的 `heatScore/fundScore/mainNetInflow/rotationState` 为 0%。根因是字段完整度依赖浏览器当天写过的 startup bundle；浏览器不运行时 fallback 合并榜只有排名，后端自身的腾讯 provider 又未映射已具备的 f9/f20/f21 等字段，量比 golden 服务未接入，涨停价/跌停价与 theme 派生字段完全没有采集链。
3. **性能/并发**：单进程同时承载 4 个调度器 + 全市场行情 49s 拉取 + 题材全市场 4263 码行情 + 5197 码资金扫描，共享 8 线程池，30s provider 超时造成 fetch_timeout 级联；本机还出现两个同命令 uvicorn 实例同时拉起。
4. **其他**：`normalize_snapshot_ingest` 保留"formal snapshot hotlist is empty"硬门禁（违反 §4.0）；`backfill-slots` 允许历史日期，存在用当前行情伪造历史快照的风险；状态 API 为进程内存态，重启清零；缺口与字段覆盖无告警。

## 1. 现状事实（证据）

### 1.1 可靠性链路

| 事实 | 代码位置 | 影响 |
| --- | --- | --- |
| 调度器在 FastAPI lifespan 内启动/停止 | `backend/main.py` on_startup / on_shutdown | 8000 进程死 = 采集死 |
| 无守护进程：autostart 计划的 supervisor.py 已不在仓库，计划任务只剩备份任务 | `backend/snapshot_collector/`（无 supervisor.py）；Windows 计划任务实测 | 无自动重启 |
| provider 全部走 `http://127.0.0.1:3000` 转发到 8000 | `providers.py _DEFAULT_PROXY_BASE_URL`、`_create_providers` | 8000 自环依赖 |
| 交易日历强依赖 bridge（2s 超时，失败抛异常） | `trading_calendar.py is_trading_day/trading_date_from_ts` | 桥挂 = 当天不采集 |
| 错过 grace 即标记 completed 跳过，无自动回补 | `scheduler.py _collect_due_slots` | 静默丢槽 |
| 今日实测：15:30 槽 tencent provider fetch_timeout×5、行情缓存 lastError=fetch_timeout | `snapshot_collector_runs` 记录 + `/api/quotes/tencent` 状态 | 字段缺口直接来源 |
| 18:21 起两个同命令 uvicorn 实例（16264/17040），仅 17040 监听 8000 | Win32_Process 实测 | 启动器可能重复拉起 |

### 1.2 字段原料

`dragonboard_live half_hour:2026-08-03:15:30`（243 行）实测覆盖率：

| 字段 | 覆盖率 | 字段 | 覆盖率 |
| --- | --- | --- | --- |
| price/change/volume/turnover/turnoverRate | 100% | volumeRatio / pe / pb / cirMV / totalMV | 0% |
| depth10 / bid1Price | 99.6% / 90.9% | limitUpPrice / limitDownPrice / lastTradePrice / lastTradeVolume | 0% |
| themes / mainTheme / sectorLabel | 93% | leadStatus / themeHeat / themeContribution / themeRole / themeRiskFlags | 0% |
| zlje / zljzb（ths_main_monitor 缓存） | 97.9% | ask1Price | 52.7% |

对照 2026-07-31 同槽位：`pe/totalMV=100%`、`volumeRatio≈99%` —— 当日 startup bundle 存在（浏览器跑过）；今日 bundle 为空（`startup bundle missing`），fallback 合并榜只有排名。

根因链：

- `TencentBasicQuoteProvider._normalize_row` 只映射 f12/f14/f2/f3/f6/f5/f8/f10；实测 `/api/quotes/tencent` 已返回 f9(pe)/f20(总市值)/f21(流通市值)，但被丢弃；`pb/cirMV` 全程无映射。
- `market_proxy/quotes.py to_tencent_diff_item` 未保留 akshare spot 的 `ztj/dtj`（涨停价/跌停价）、`zs/jk/zg/zd` 等列；且 f62/f66/f69/f184 硬编码 0。
- 量比 golden `backend/volume_ratio_service.py` 只通过 `/api/quotes/volume-ratio` 给前端，collector 未接入。
- theme 派生字段（leadStatus/themeHeat/themeContribution/themeRole/themeRiskFlags）只有前端 TypeScript golden 有；`backend/snapshot_derivation/` 是空目录，未实现。
- `sector_rows` 全部为 `hot_theme`，`heatScore/fundScore/mainNetInflow=0%` 因 `theme_heat_service.get_snapshot(include_runtime_funds=False)`；`rotationState` 未映射，而 `backend/analysis/theme_support.py` 明确消费 `rotationState`。

回测侧消费确认（`backend/core/backtest/execution.py _quote/_match_order/_limit_state`、`backend/analysis/theme_support.py`）：

- 涨跌停约束：`limitUpPrice/limitDownPrice`（当前 0%）。
- 撮合与止损：`bid1/ask1 + volume + high/low`（已覆盖）。
- 题材策略：`themeRole/themeHeat/themeContribution/themeRiskFlags` + sector `rotationState/momentumScore/correlationScore/crowdingRisk`（前三者 0%）。
- 资金口径：回测质量门禁 `FORMAL_MONEY_FLOW_SOURCES={"broker_l2","official_l2"}`，collector 的 `ths_main_monitor` 不在白名单；`require_formal_money_flow` 开启时会直接拒跑回测（当前默认关，属口径未对齐）。
- 合并榜 `_empty_stock` 用 `price=0/volume=0/heat=0` 占位；行情补齐失败时 0 值落库，回测门禁 `nonPositivePriceCount>0` 判 fatal（`backend/data/quality_gate.py`），与 §4.0"缺失保持缺失、禁止 0 伪装"冲突。

### 1.3 性能/并发

- 单进程承载：collector + stock_name + theme_mapping + market_fund 四个 scheduler；全市场行情缓存 300s 刷新（akshare 约 49s）；8 平台热榜；theme heat 全市场 4263 码行情；资金调度 5197 码（per-code THS akshare）。
- `providers.py` 共享 `ThreadPoolExecutor(max_workers=8)`；同刻多槽（15:30 half_hour+daily 并发）+ 每 run 一次 `theme_heat.get_snapshot`，线程池争抢 + 30s 超时级联。
- 无跨进程/跨实例锁：多 worker 或重复实例会重复采集；`run-once` API 与 scheduler 之间无锁（设计文档要求有）。
- 8000 进程 36 线程；实测两个 uvicorn 实例同命令同时存在。

## 2. 设计文档 vs 代码落地偏差

| # | 设计承诺 | 代码现状 | 影响 |
| --- | --- | --- | --- |
| 1 | 槽位表 quarter_hour 止 15:00（18）、half_hour 止 15:00（10）、daily 15:00 | 代码 quarter_hour 含 15:15（19）、half_hour 含 15:30（11）、daily 15:30 | 口径偏差，需确认是否有意（注释称"与前端 schedule 对齐"但设计文本未同步） |
| 2 | `POLL_MS=1000` 轮询调度 | 改为 next-slot 精确定时，`snapshot_collector_poll_ms` 成死配置 | 死配置易误导 |
| 3 | 正式写入前质量门禁硬阻断 | 事故后改为"仅全源无数据拒写"，但 `normalize_snapshot_ingest` 仍保留 `formal snapshot hotlist is empty` 抛错 | 空 hotlist 但 sector/market 存在时整批拒写，违反 §4.0 |
| 4 | scheduler 防止同一 slot 并发采集 | 仅进程内 `_in_flight_slots` 软集合；API/CLI run-once 无锁 | 并发重复采集与写竞争 |
| 5 | `backfill-slots` 只允许当前交易日 | API 允许任意历史日期范围，直接采集当前行情写入历史槽位 | 可伪造历史快照 |
| 6 | FastAPI 自持 startup cache，前端不再上传合并 bundle | 未实现；仍由前端写 proxy startup-bundle，collector 依赖它 | 浏览器不开 → 字段缺口（今日实证） |
| 7 | `MarketFactService + SnapshotDerivationService + 统一字段合同 + fieldMeta + SnapshotFactInventory` | `backend/market_data/`、`backend/snapshot_derivation/` 均为空目录 | 2026-07-29 设计未落地 |
| 8 | `five_minute` 轻量 record | `SnapshotSlot._VALID_TYPES` 拒绝 five_minute | 五类快照能力缺失 |
| 9 | 独立 supervisor + Windows 计划任务守护（8001） | supervisor.py 已不在仓库，计划任务已删 | 无守护/自动重启 |
| 10 | runs 记录逐字段 valid/missing/stale 覆盖统计 | 只记录 sourceHealth/行数 | 字段缺口不可观测 |
| 11 | captureMode/qualityFlags/run 状态可追溯 | 已实现 | — |
| 12 | provider 失败不写空快照 | 服务层已按"仅全源无数据拒写"实现 | 但见 #3 残留硬门禁 |

## 3. 优化方案

### 3.1 可靠性（P0）

1. **调度器进程外独立**：把 `snapshot_collector.scheduler` 从 `main.py` lifespan 拆出为独立采集进程（如 `backend/collector_main.py`，独立端口只提供 `/api/snapshot-collector/*`），恢复守护/自动重启（supervisor 或 Windows 计划任务）。采集进程不依赖 8000 可用性。
2. **去掉自环 HTTP**：collector provider 改为进程内调用 `market_proxy` 的 Python service（与 FastAPI 同代码复用），或直连数据源；proxy(3000) 只留给前端。
3. **交易日历去单点**：本地缓存交易日历（首日桥可用时写入，后续离线可用），桥挂只降级不停采。
4. **自动当日回补**：定时核对"应采槽位 vs MongoDB 实际 frames"，当日缺槽自动补采（仅当前交易日、限定在收盘后窗口内），并触发飞书告警（`FEISHU_EVENT_RADAR_WEBHOOK` 已配置）。
5. **启动去重**：采集进程启动前用 Redis `SET NX` 单实例锁（复用现有 Redis），防止双实例/双 worker 重复采集。

### 3.2 字段原料（P0/P1）

1. **腾讯行情全字段映射**：`TencentBasicQuoteProvider` 补齐 `pe(f9)/totalMV(f20)/cirMV(f21)/pb(f23 或独立字段)`；`market_proxy/quotes.py` 保留并透传 `ztj/dtj/zs/jk/zg/zd`（涨停价/跌停价/昨收/今开/最高/最低），按 2026-07-29 设计统一单位（元；禁止二次换算）。
2. **量比接入**：collector 在进程内调用 `compute_volume_ratios`（不经 HTTP），与前端同一 golden。
3. **实现 SnapshotDerivationService（最小版）**：由 `MarketFactBundle`（八榜 + 行情 + 涨停池 + theme_heat factors + 资金）派生 `leadStatus/themeHeat/themeContribution/themeRole/themeRiskFlags`，先冻结前端 builder fixture 做逐字段等价测试。
4. **sector rows 补齐**：`factor_to_sector` 映射 `rotationState`；资金域按设计开启 runtime funds（`include_runtime_funds=True`）或单独采集，补齐 `heatScore/fundScore/mainNetInflow`。
5. **缺失语义**：合并榜 `_empty_stock` 改为 `None` 占位（禁止 0 伪装）；`fieldMeta` 记录 `fresh/stale/missing/invalid + source + reason`；读取/回测侧同步把"缺字段不阻断"落实。
6. **移除 normalizer 硬门禁**：`empty_formal_snapshot_ids` 抛错改为"保存 frame + sector rows + 结构化 qualityFlags"，仅全源无任何原始记录时拒写。

### 3.3 并发与性能（P1）

1. 槽位并发信号量（默认 1，可配 2）；provider 全并行化 + 每 provider 独立超时预算，避免 30s×N 累积。
2. 共享线程池按用途拆分（行情批 / 题材映射 / 资金），或改 async httpx 单 worker。
3. 重负载任务独立进程或错峰：全市场行情刷新、5197 码资金扫描与槽位采集错开；题材行情优先复用进程内缓存。
4. 回填 `main.py` 启动参数文档：单 worker、无 `--reload`、禁止重复拉起。

### 3.4 可观测与维护（P1/P2）

1. 状态与告警：槽位缺口、字段覆盖阈值（如 `volumeRatio<80%`、`totalMV<80%`）、provider 连续失败 → 飞书告警；状态 API 持久化（重启后从 MongoDB runs/state 恢复，不再内存清零）。
2. runs 记录补逐字段 `validCount/missingCount/invalidCount/staleCount/trueZeroCount/coverageRatio`。
3. `backfill-slots` 限当前交易日；历史恢复只走有证据的 repair/import（`copy-missing-mongodb-snapshot-slots` 等已存在工具）。
4. 清理死配置与偏差：`snapshot_collector_poll_ms`、quality_gate blocking 语义、槽位表与设计文档对账。

### 3.5 存量数据修复

- 参照 2026-07-29 已执行的 `snapshot_stock_rows_repair_backup_20260729_pm` 模式：按证据回填 `volumeRatio/pe/pb/cirMV/totalMV/limitUpPrice/limitDownPrice` 等可溯源字段；无证据的保持缺失并记录 `fieldMeta`。
- 修复前先备份受影响集合，修复写入 `migration_audit`，逐槽位核对 count drift。

## 4. 影响文件（预计）

- `quant-board/backend/snapshot_collector/{scheduler,providers,builder,service,service_factory,slots,trading_calendar}.py`
- `quant-board/backend/snapshot_collector/collector_main.py`（新增，独立采集进程）
- `quant-board/backend/snapshot_collector/supervisor.py`（恢复）
- `quant-board/backend/data/snapshot_ingest_normalizer.py`、`backend/data/quality_gate.py`
- `quant-board/backend/market_proxy/quotes.py`、`backend/api/market_data_routes.py`
- `quant-board/backend/snapshot_derivation/**`（实现）
- `quant-board/backend/analysis/theme_support.py`（缺失语义对齐）
- `quant-board/backend/api/snapshot_collector_routes.py`（backfill 限当日、字段覆盖诊断）
- 文档：`quant-board/docs/architecture.md`、`api-cli.md`、`AI_COLLABORATION.md`、`database-migration-plan.md`、`snapshot-collector-field-migration/**`

## 5. 验证命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_volume_ratio_service.py tests/test_theme_support.py -q
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_live --snapshot-type half_hour --trading-date <交易日> --slot-time 15:00 --dry-run
```

验收口径：

- 缺槽自动补采 + 飞书告警可触发；bridge 离线 1 小时仍正常出槽。
- 新落库 `half_hour` 的 `volumeRatio/pe/pb/cirMV/totalMV` 覆盖率 ≥95%；`limitUpPrice/limitDownPrice` 与涨停池同步（涨停股必含）；theme 派生字段可解释非空。
- sector rows 的 `fundScore/mainNetInflow/rotationState` 非 0 覆盖率 ≥80%。
- 空 hotlist 但 sector/market 数据存在时仍落 frame + sector rows + qualityFlags，不再整批拒写。
- 单实例锁生效：双进程同时启动只采集一次；同刻多槽采集并发 ≤ 配置上限。
- 首个修复后完整交易日人工核对 MongoDB 实际行数与字段，不只查 API status。

## 6. 风险与边界

- 不借本次优化改动 RankTrend golden 口径（Python `ranktrend.py` 不变）；只补原料字段。
- `limitUpPrice/limitDownPrice` 与 `depth10` 不得宣传为官方 L2；字段沿用现有合同名。
- 历史数据无时点证据的字段保持缺失，不做无依据回填。
- 调度器拆独立进程属架构改动，先在小范围（当日观测）验证，再全量切换。
