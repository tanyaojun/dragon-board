# 题材模块重构发现记录

## 2026-07-25 THS 增量资金整改审计

- Design/plan agent review identified eight architecture blockers: runtime THS leakage into formal snapshots, no post-close final pass, missing-code retry bypass, partial failure misclassified as systemic, synchronous calendar I/O in the event loop, leaked theme P0 owners, destructive multi-connection P1 persistence, and non-numeric THS `errorcode` escaping per-code failure isolation. The current implementation now contains targeted fixes/tests for all eight; final verification remains required.
- Execution review found two remaining blockers in `tools/THSBigOrder`: `BigOrderLastGoodMaxAge` still hard-coded Saturday/Sunday, and a successful bridge minute response was cached without checking its date against THS authoritative `sessionDate`. Both require deterministic regression tests before implementation.

- 失败方案把 `tdx_transaction` 同时写入 bridge、QuantBoard cache/stream、snapshot provider、前端 source priority 和实时协调器，导致资金口径与行情 WebSocket 生命周期耦合。
- 可复用部分只有 Redis last-good、版本拒绝回退、QuantBoard 到浏览器的资金 WebSocket，以及题材/行情统一读缓存的方向；bridge 上游订阅和逐笔累计必须移除。
- 现有 `ThemeFundCache` 只允许 TDX，且非交易日只有 `isFinal=true` 才能返回，无法承接 THS 最近交易日总额。
- FastAPI 当前没有 THS `mainMonitorDetail`；现有单票实现只在 proxy `/api/big-order/ths-detail`。其请求头、响应校验、金额/日期解析和错误分类应迁入 QuantBoard 共享 service，不能在 FastAPI 与 proxy 保留两套实现。
- `tools/THSBigOrder` 当前把 THS、Longhu、腾讯行情、分钟线和涨停池共用同一个 3000 base URL。迁移时只能给 `ThsBigOrderSourceClient` 单独增加 FastAPI 8000 base，不能整体替换 provider base URL。
- `tools/THSBigOrder` 的公共构造器实际设置 `_bigOrderProxyPrimary=true`，运行时 THS 是 proxy-primary，并非 direct-first/fallback；迁移后 FastAPI 8000 应保持为单票主链。
- 工具分钟线尚未迁移：当前 `TencentMinuteSourceClient` 直连腾讯并回退 `/api/quotes/tencent/minute`。python-bridge 虽已有 `/api/quotes/minute`，但实测周六把周五数据标成当天，且 raw `get_minute_time_data` 解码出现错误价格。正确 mootdx `Quotes.minutes('002297', date='20260724')` 返回 240 点；`vol` 单位为手，累计成交额需乘 100。必须先修 bridge 合同再迁工具，不能直接换 URL。
- FastAPI 单票路由必须保留独立 raw payload last-good 与 stale 元数据；dashboard `theme-fund:v3` 只有标准化 `zlje`，不能满足 THSBigOrder 的明细/价格变化解析。
- scheduler、FastAPI 单票/批次和工具请求必须共享 service 级请求门控，否则外部调用会绕过全局 THS 冷却与降并发。
- 新 THS 资金链不得依赖 proxy startup bundle。Redis owner 正常持久化恢复；冷空 Redis 等待前端真实 `marketCodes` 建立约 200 只 P1 集合，题材 4,000+ 映射不进入 owner。
- P1 owner 只由 Redis 持久集合和浏览器真实 `marketCodes` 更新维护；MongoDB 题材映射 4,000+ 股票、proxy startup bundle 和 snapshot collector 题材全集不得进入默认资金队列。
- 非交易日不能只写“读取缓存”：切换到新命名空间时缓存必然为空。必须允许缺失 owner 股票做一次 THS 冷补齐，并接受上游最近 `sessionDate`，随后停止连续轮询。
- 交易日判断必须继续复用 `snapshot_collector.trading_calendar` 到 python-bridge `/api/calendar` 的 mootdx 标准日历链；日内交易时段只用于会话状态，不用于猜测交易日。
- 前端现有 `RealtimeSubscriptionRegistry` 已区分普通 owner 和题材 fund owner，适合改造成 marketCodes=P1、fund owner/top-ranked rows=P0 的双集合合同。
- WebSocket subscriber 的接收集合必须是 `marketCodes ∪ priorityCodes`，否则不属于 200 只行情池的展开题材 P0 会被采集却收不到 patch。

## 2026-06-21 MongoDB Theme 动态热度替代 JXBK 调研

- 当前正式存储口径已切换为 MongoDB：Dragon Board 通过 QuantBoard `GET /api/themes/mapping` 读取题材基础映射，前端不得直连 MongoDB。
- JXBK 5000 端口承担的是板块动态行情和板块成分加载；MongoDB theme 当前首先是题材元数据与题材-股票关系事实源。替代设计必须显式补齐动态行情聚合，不能直接把静态映射等同于题材热度。
- 现有权威运行态入口仍是 `ThemeRuntimeCoordinator.refreshRuntime()` / `themeFacade`，`sectorAnalyzer` 应继续保持兼容 adapter，而不是重新承载一套独立算法。
- 工作区调研开始时 `git status --short` 为空，分支为 `main`。
- 本机 QuantBoard 8000/8001 的 MongoDB theme 读口均正常，当前实际数量为 239 个题材、12219 条映射、4167 只去重股票。
- `ThemeFactorEngine` 已能在没有 JXBK block 时基于成分股行情计算 breadth、fund、leadership、correlation 和 risk；但会产生 `jxbk_missing`，且 momentum/netInflow/strength 的部分语义仍依赖 JXBK。
- `DataLayer` 的股票运行池来自热榜合并和已有缓存，MongoDB theme 映射不会自动把全部 4167 只股票加入行情池；直接去掉 JXBK 请求会造成明显的成分覆盖偏差。
- 前端 `buildSnapshotSectorRows()` 会把 `hotThemes` 写成 `entityType=hot_theme`，即使 `jxbkBlocks` 为空仍可形成题材 sector rows；前提是 runtime 热度计算成功并同步到 `DataLayer.hotThemes`。
- 自动运行的 backend shadow collector 是另一条独立写库链。其 `ThemeMappingProvider` 已存在但未在 `_create_providers()` 装配；现有 builder 仅转换 `MarketDataContext.sectors`，没有动态题材聚合，所以 `sectorRows=0` 是上游上下文为空，不是 MongoDB insert 失败。
- 8001 当前健康：MongoDB 已连接，scheduler `enabled=true/running=true`，dataset 为 `dragonboard_backend_shadow`；2026-06-21 为非交易日，尚无采集次数。
- 用户确认最终方案必须同时覆盖根前端和 backend collector；动态计算股票池为 MongoDB theme 映射的全市场约 4167 只股票，刷新周期为 5 分钟，正式 sector rows 仍按 half-hour/daily 快照节奏持久化。
- proxy-server 东财行情接口本身按显式代码列表查询；全市场调用必须由服务端分批，不能把 4167 个代码拼进单个 URL。现有前端 `QuoteHttpFeed` 已采用 50 只一批，可作为批次口径参考。
- QuantBoard `analysis/theme_trend.py` 已有与 TypeScript runtime factor 对齐的 `_build_ts_runtime_factor` 逻辑，可提取为公开、纯计算的共享 Python 因子引擎，避免 collector 另写第三套公式。
- 用户修正数据源口径：全市场基础行情必须使用腾讯，不使用东财基础行情。腾讯当前代理合同可提供价格、涨跌幅、成交量和成交额，但换手率、量比及主力资金字段需要另行定义来源或显式标记不可用。
- 2026-06-21 本机实测：腾讯接口 3/3 返回约 0.8 秒、50/50 返回约 0.45 秒；返回价格、涨跌幅、成交量、成交额、换手率和量比，资金字段为 0。
- 同期东财接口 3/3 返回约 4.4 秒、50/50 返回约 4 秒，`f62/f66/f69/f184` 资金字段均非空；`dragonMeta.route=ulist`、`fallback=false`、`stale=false`，当前可正常连接。
- 最终数据源合同应为腾讯基础行情主源 + 东财资金字段辅源；东财响应中的价格、涨跌幅等基础字段不进入题材计算。两个来源分别统计覆盖率，东财失败时 fundScore 应标记不可用并按明确降级权重处理，不能默认资金净流入为 0。

## 当前口径

- `ThemeFacade` 和 `ThemeRuntimeCoordinator.refreshRuntime()` 是题材运行态唯一事实主链。
- `themeFacade` 统一暴露全市场题材摘要、个股暴露、轮动摘要、题材事件和 runtime snapshot。
- `sectorAnalyzer`、`rotationService`、`alertService` 的业务事实来源均来自 `themeFacade`、`ThemeHeatFeed` 或题材 runtime store。
- QuantBoard 题材字段和回测开关沿用 V2 结果，V7 不修改数据库和回测执行策略。

## 已清理内容

- V6 已统一刷新路径：`refresh()/refreshThemeFacadeState()/refreshRuntime()` 均进入 runtime coordinator。
- V6 已把题材事件和 legacy block event 的生成统一到 `ThemeRuntimeCoordinator`，`alertService` 只做冷却、去重、保存和状态管理。
- V7 已移除 `rotationService` 内部旧手工轮动、主线、市场阶段和 localStorage 持续性事实计算。
- V7 已移除 `sectorAnalyzer` 内部旧热度计算、旧 JXBK 热度更新、旧板块预警生成和旧 hot theme fallback。
- V7 已把 `config/factors`、`ContextBuilder`、算法预热的题材事实读取迁到 `themeFacade`。

## 当前保留边界

- `sectorAnalyzer.loadSectorStocks()` 作为面板公开 API 保留，只委托 `ThemeHeatFeed.loadThemeStocks()`。
- `App.vue/main.ts` 仍挂载 `window.sectorAnalyzer/window.rotationService`，用于控制台、旧调试脚本和兼容服务注册。
- `RefreshCoordinator` 仍保留 `sectorAnalyzer` 节点，但该节点现在只是 legacy adapter，不再持有独立题材事实。
- `DataLayer` 只保存统一 hot theme 摘要，不保存退役板块 blocks/stockMap。

## 2026-06-22 全市场题材热度替换结论

- 映射源为 MongoDB `themes/theme_stock_mappings`，基础行情源为腾讯，资金源仅为东财资金字段。
- Python `theme-market-v1` 是全市场计算合同；前端只做 API 消费、运行态投影和 UI 展示，不复制抓取算法。
- 资金源不可用时 `fundScore/mainNetInflow` 保持 `null` 并标记 degraded，不转换成 0。
- 浏览器快照使用完整 API factors 生成 `hot_theme` rows，包括不可排名的审计题材；旧 payload `sectors` 只服务历史导入。
- 切换前已落库的空 sector rows 是已知历史缺口，不回填、不伪造。实际切换时间需在两交易日 shadow 审计和正式切换后记录。

## 后续候选

- 后续可考虑增加题材 runtime 调试面板或回放一致性工具。
- 若继续清理文档，可把 `progress.md` 中历史过程日志压缩为里程碑摘要。

## 2026-05-05 V8 启动发现

- 用户明确 V8 只做 IndexedDB 题材映射迁移到 QuantBoard 独立 SQLite 主库 `themeDATA.db`，不改题材因子、轮动、预警和 UI。
- `src/services/ThemeDataService.ts` 进入 V8 前仍持有 `ThemeDataDB/theme_mapping` IndexedDB 初始化、读取、保存和自动 API 刷新写入逻辑。
- `src/services/theme/ThemeFacade.ts` 的题材 source context 仍同步读取 `themeMapping.getAllThemes()` 和 `themeMapping.getThemeStocks()`；因此 V8 前端改造应保持 `themeMapping` 同步读口兼容。
- QuantBoard 后端已有 `quant_board_snapshots.db` 与 `quant_board_research.db` 的双 Base/session 模式；V8 需要新增第三套 theme DB session/Base 或等价隔离实现。
- 现有后端 `main.py` 已有快照迁移 API 模式：业务 service 抛 `ValueError`/`ImporterError`，路由转 400；V8 主题迁移应沿用结构化错误。

## 2026-05-05 V8 落地发现

- 已新增 `themeDATA.db` 相关 `ThemeBase/theme_engine/ThemeSessionLocal`，默认环境变量为 `QUANT_BOARD_THEME_DATABASE_URL`。
- `themeDATA.db` 当前只包含 `theme_metadata`、`themes`、`theme_stock_mappings`，不进入 Supabase/outbox/Parquet。
- `ThemeDataService` 正式加载已切到 `apiService.getSqliteThemeMapping()`，实际请求 `http://localhost:8000/api/themes/mapping`。
- `ThemeDataService.checkAndUpdateFromAPI()` 只合并标签/原因，不再用外部批量 API 覆盖题材-股票关系事实。
- 旧 IndexedDB 私有读写函数已从 `ThemeDataService` 移除；浏览器 IndexedDB 只作为外部历史迁移来源，不再混在正式 facade 内。
- code review 发现 `get_stock_themes()` 对同一股票多题材时会覆盖标签/原因；已改为按题材顺序合并标签并用 `；` 合并原因。
- code review 发现 `buildMapping()` 初次加载原因使用 first-wins；已改为与增量合并一致的 `；` 去重合并。

## 2026-05-05 V9 落地发现

- `themeDATA.db` 新增只读校验入口，API/CLI 输出同一 diff 结构，适合导入后验收，不会写库。
- `JxbkThemeFeed` 已承接板块成分股懒加载、缓存、并发复用、DataLayer 写入和 runtime refresh。
- `sectorAnalyzer.clearCache/getStats/loadSectorStocks` 均改为委托 `JxbkThemeFeed`，继续服务旧组件和控制台入口。

## 2026-05-05 V11 启动发现

- V10 已把 Chrome `http_localhost_5173` 的 `ThemeDataDB/theme_mapping` 导入 `themeDATA.db`，校验结果为 237 个题材、12215 条题材-股票关系、4166 只去重股票，`verify-themes` 返回 `ok=true`。
- `ThemeDataService` 当前没有 IndexedDB 正式读写函数，但仍保留 `/data/theme_base_mapping.json` 本地 fallback、`/api/themes/batch` 标签/原因增量刷新和自动定时刷新。
- `sectorAnalyzer` 仍直接读取 `themeMapping`，并通过 `(themeMapping as any).stockTagsMap/stockReasonsMap` 访问私有 Map；V11 应改为仓库公开读口。
- `themeFacade` 的 `Compat` 方法仍是多个组件的读取入口；V11 应增加正式别名并迁移组件调用，保留 wrapper 但不让新代码继续扩散旧命名。
- 本轮收口范围只覆盖题材分析模块，不处理 `src/services/snapshot/**` 的 IndexedDB 迁移/缓存逻辑。

## 2026-05-05 V11 实施发现

- `ThemeDataService` 已转为 SQLite-only：QuantBoard mapping 读取失败时返回 `false` 并记录 `lastError`，不再请求本地静态 JSON 或 `/api/themes/batch`。
- `themeRepository` 已成为前端题材基础仓库正式入口；`ThemeFacade`、`ThemeRuntimeCoordinator`、`sectorAnalyzer` 已改用仓库公开读口。
- `sectorAnalyzer` 已移除对 `themeMapping` 私有标签/原因 Map 的读取，`getStats()` 返回 `themeBaseSource=sqlite` 和 `version=11.0.0`。
- 业务代码已迁到 `themeFacade` 非 Compat 正式方法；`get*Compat()` wrapper 仍保留供旧测试、控制台或后续清理使用。
