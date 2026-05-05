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

## 文件说明

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
