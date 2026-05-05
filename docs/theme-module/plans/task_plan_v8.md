# 题材模块 V8：IndexedDB 题材映射迁移到 SQLite 主库

## 目标

把根项目 `ThemeDataService` 当前依赖的浏览器 IndexedDB 题材映射迁移到 QuantBoard 后端独立 SQLite 主库 `themeDATA.db`，前端正式读口优先走后端 SQLite API，IndexedDB 只保留为历史迁移源和显式排障缓存。

## 范围

- 新增 QuantBoard theme SQLite 主库、建表、仓库、导入服务和只读 API。
- 支持从旧 `ThemeMappingData` JSON 幂等导入，返回结构化校验结果。
- 前端新增/调整题材 repository/facade，使 `ThemeDataService` 正式加载优先走 QuantBoard API。
- 停止把 API 刷新或 `setData()` 的正式题材映射写入浏览器 IndexedDB。
- 同步 QuantBoard 文档和根项目题材模块文档。

## 非目标

- 不调整题材因子、轮动、预警或 UI 布局。
- 不迁移回测、快照、题材因子运行态事实表。
- 不删除旧浏览器 IndexedDB 数据和迁移工具。

## 阶段

1. **后端合同测试**
   - 新增 theme 数据库初始化、幂等导入、正反查和结构化错误测试。
   - 先运行测试确认失败。

2. **后端实现**
   - 新增 `ThemeBase`/engine/session 或等价独立 DB 初始化。
   - 新增 theme 模型、repository/service 和 API：`/api/themes/mapping`、`/api/themes/stocks/{theme_id}`、`/api/themes/stocks/by-code/{code}`、`/api/migrations/themes/import-json`、`/api/themes/counts`。
   - health/status 中体现 `themeDATA.db`。

3. **前端合同测试**
   - 新增 `ThemeDataService`/repository 测试，确认正式读口优先 SQLite API，后端失败才使用本地静态 fallback，不写 IndexedDB。
   - 先运行测试确认失败。

4. **前端实现**
   - 新增 `src/services/theme/ThemeRepository.ts` 或复用现有文件，封装 QuantBoard API 数据读取。
   - 改造 `ThemeDataService` 为兼容 facade：SQLite API → 本地静态 fallback；IndexedDB 只通过显式历史读取/导出方法保留。
   - 保持 `themeMapping.getAllThemes()/getThemeStocks()/getStockThemes()` 等同步读口兼容。

5. **文档同步**
   - 更新 `quant-board/docs/database-migration-plan.md`、`api-cli.md`、`architecture.md`、`AI_COLLABORATION.md`。
   - 更新 `docs/theme-module/README.md`、`findings.md`、`progress.md`。

6. **验证**
   - 运行后端相关 pytest，条件允许运行 `cd quant-board; .\.venv\Scripts\python.exe -m pytest`。
   - 运行前端相关 Vitest、`pnpm test`、`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。

## 风险和约束

- 不使用批量删除命令；如需删除旧文件必须逐个明确路径，当前计划不删除文件。
- 前端导入时要兼容旧 `ThemeMappingData`：`version/lastUpdate/totalThemes/themes[]/stockTags/stockReasons`。
- 后端错误必须结构化返回，至少包含 `code`、`message`、`field` 或 `errors`。
- QuantBoard 后端不可用时，正式 SQLite 读口失败要可见；本轮为了保持现有启动体验，首次加载可使用本地静态 JSON 作为非正式 fallback，但不能回落 IndexedDB 作为正式事实源。

