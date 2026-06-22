# 题材模块重构发现记录

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
