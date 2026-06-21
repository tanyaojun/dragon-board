# 题材模块文档索引

本目录归档题材模块 V1-V7 重构过程中的计划、审计发现和实施记录。

## 当前口径

- 题材模块运行态主链以 `ThemeRuntimeCoordinator.refreshRuntime()` 为权威入口。
- `themeFacade` 是 UI、服务层、预警和调试读口的统一 facade。
- `sectorAnalyzer/rotationService/alertService` 继续保留旧公开 API，但运行态事实来源均已降级为 `themeFacade` 兼容 adapter。
- QuantBoard schema 和回测主链在 V6 不再扩展，沿用 V2 已落地的稳定字段和执行开关。
- V8 后，题材基础映射事实源是 QuantBoard 后端独立 SQLite 主库 `themeDATA.db`。
- V10 已完成本机 Chrome `http_localhost_5173` 下旧 `ThemeDataDB/theme_mapping` 数据迁移，当前 `themeDATA.db` 中有 237 个题材、12215 条题材-股票关系、4166 只去重股票。
- V11 目标是运行时严格收口：前端题材分析模块不再把浏览器 IndexedDB、本地静态 JSON 或外部批量 API 当作正式或兜底事实源；旧 IndexedDB 仅作为离线历史迁移来源。
- V12 目标是 ThemeTrend 量化研究平台化：QuantBoard 新增与 RankTrend 并列的 ThemeTrend 研究链，承接题材趋势、题材共振回测、优化、API/CLI 和报告合同；Dragon Board 根项目不新增回测平台。
- V12 当前口径：`themeDATA.db` 只承载题材基础映射，ThemeTrend 回测、优化和质量报告等研究结果只进入 QuantBoard research SQLite，本轮不进入 Supabase。

## 文件说明

- `2026-06-21-mongodb-theme-heat-jxbk-replacement-design.md`：以 MongoDB 全市场题材映射、腾讯基础行情和东财资金字段替代 JXBK 5000 的前后端统一设计。
- `findings.md`：审计发现、残留调用和后续清理边界。
- `progress.md`：V1-V7 实施过程日志归档。
- `plans/`：各版本执行计划归档。

## 后续维护

- 新的题材模块方案、审计报告和实施计划继续放在本目录。
- 不再把 `task_plan*.md`、`findings.md`、`progress.md` 放在仓库根目录。
- 若形成可复用 agent 工作流，应单独沉淀到根目录 `skills/`，不要混入业务文档。

## V8 迁移口径

- 迁移入口：`POST /api/migrations/themes/import-json`。
- 正式读口：`GET /api/themes/mapping`、`GET /api/themes/stocks/{theme_id}`、`GET /api/themes/stocks/by-code/{code}`、`GET /api/themes/counts`。
- 前端入口：`src/services/ThemeDataService.ts` 作为兼容 facade 保留 `themeMapping.getAllThemes()/getThemeStocks()/getStockThemes()` 等同步读口，但加载来源切为 QuantBoard SQLite API。
- 不改题材因子、轮动、预警或 UI 布局。

## V11 收口口径

- QuantBoard SQLite 读取失败时，题材基础映射应显式失败，不回落 `/data/theme_base_mapping.json` 或浏览器 IndexedDB。
- 前端不再通过 `/api/themes/batch` 后台修正题材映射、标签或原因；这些基础事实只能通过后端导入/维护进入 `themeDATA.db`。
- `sectorAnalyzer/rotationService` 保留旧公开对象，但内部只作为 `themeFacade/themeRepository/JxbkThemeFeed` 的 adapter。
- `Compat` 方法后续只作为旧调用 wrapper，新代码改用非 Compat 的正式 facade 方法。

## V12 ThemeTrend 平台化口径

- 计划文件：`plans/task_plan_v12.md`。
- V12 后端研究链已进入可运行主链；完整平台化仍需继续深化 TS golden 多场景自动导出、walk-forward/样本外报告和真实 bayesian/tpe 搜索器接入。
- ThemeTrend 与 RankTrend 并列：RankTrend 继续负责个股候选趋势，ThemeTrend 负责题材强度、扩散、持续性、拥挤和共振解释。
- 已落地 QuantBoard 合同：`POST /api/backtests/theme-trend`、`POST /api/backtests/theme-confluence`、`POST /api/optimizations/theme-trend`、`POST /api/optimizations/theme-confluence`；CLI 对应 `run-theme-trend`、`run-theme-confluence`、`optimize-theme-trend`、`optimize-theme-confluence`。
- ThemeTrend 回测现在会把题材暴露映射为可执行股票信号，复用现有 `TradeSimulator`，并双写 `/trades`、`/equity`、`/signals`、`/quality` 读口。
- `theme_rotation`、`leader_theme_confirmation`、`hotlist_theme_confluence` 已在执行信号中区分题材轮动、龙头确认、热榜共振的入场、降级、过滤和解释字段。
- Dragon Board 根前端只消费 `GET /api/research/theme-summary` 研究摘要，不承载回测、优化或交易模拟；题材、龙头和热榜视图展示研究解释，QuantBoard 不可用时显示降级文案。
- 默认 `snapshotType=half_hour`；`quarter_hour` 只能显式选择，不能替代默认研究口径。
