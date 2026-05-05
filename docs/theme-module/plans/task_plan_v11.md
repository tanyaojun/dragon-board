# 题材模块 V11：严格收口与 IndexedDB 依赖彻底切断

## 目标

- 题材基础映射运行时只认 QuantBoard `themeDATA.db`。
- 前端题材分析模块不再保留浏览器 IndexedDB、静态 JSON 或外部批量 API 作为事实 fallback。
- 清理 `sectorAnalyzer/rotationService/themeFacade` 表面的旧兼容层，让旧公开 API 只作为 thin adapter 存在，不再持有独立事实、缓存或私有映射读取。
- 保留迁移工具和历史数据，不删除用户浏览器 IndexedDB。

## 范围

- 根前端题材模块：
  - `src/services/ThemeDataService.ts`
  - `src/services/theme/ThemeRepository.ts`
  - `src/services/theme/ThemeFacade.ts`
  - `src/services/sectorAnalyzer.ts`
  - `src/services/rotationService.ts`
  - `src/services/ThemeCorrelationAnalyzer.ts`
  - 相关面板中仍调用旧 adapter 的位置
- QuantBoard 后端只做必要读口/校验增强；不扩展因子、轮动、预警、回测或 UI。
- 文档同步：`docs/theme-module/**` 与 QuantBoard API/数据库文档。

## 非目标

- 不删除 Chrome/Edge 中的历史 `ThemeDataDB`。
- 不删除 QuantBoard `POST /api/migrations/themes/import-json` 和 `verify-json` 迁移工具。
- 不改题材因子算法、轮动算法、预警阈值和 UI 布局。
- 不把快照模块的 IndexedDB 迁移纳入本轮；快照仍按独立主线处理。

## 当前残留

1. `ThemeDataService` 正式读口已走 `GET /api/themes/mapping`，但仍保留：
   - `/data/theme_base_mapping.json` 本地静态 fallback。
   - `/api/themes/batch` 后台标签/原因增量刷新。
   - `startAutoUpdate()` 的两小时后台刷新语义。
2. `sectorAnalyzer` 仍直接读取 `themeMapping` 以及 `(themeMapping as any).stockTagsMap/stockReasonsMap`。
3. `themeRepository` 只是 `themeMapping` 的薄包装，命名上仍没有体现 SQLite 主库合同。
4. `themeFacade` 仍暴露多组 `Compat` 命名，旧组件依赖 `getJxbkBlocksCompat/getThemeStockMapCompat/getHotThemesCompat/getThemeDetailCompat/getThemeStocksCompat`。
5. 文档仍有“历史 IndexedDB 迁移源和显式排障缓存”口径，V11 后运行时口径应改为“仅离线迁移源，不进入前端正式服务链路”。

## 设计原则

- SQLite failure is failure：QuantBoard 后端不可用、返回空映射或结构异常时，题材基础映射加载失败并返回结构化状态，不回落本地 JSON 或浏览器 IndexedDB。
- 迁移与运行分离：浏览器 IndexedDB 只通过离线导出或后端迁移 API 进入 `themeDATA.db`，不在前端服务内读取。
- 兼容 API 只做委托：保留必要旧方法名给组件、控制台和诊断脚本，但内部只调用 `themeFacade/themeRepository/JxbkThemeFeed`。
- 数据写入单向：题材基础映射新增、修正、标签和原因更新只能进入 `themeDATA.db`，前端不再调用外部批量 API 修改内存事实。

## 阶段

### 1. 题材基础映射 SQLite-only

- [ ] 为 `ThemeDataService.load()` 增加失败测试：
  - SQLite API 返回 HTTP 错误时 `load()` 返回 `false`。
  - 不请求 `/data/theme_base_mapping.json`。
  - 不请求 `/api/themes/batch`。
- [ ] 删除或停用 `fetchFromLocal()`、`fetchFromAPI()`、`checkAndUpdateFromAPI()`、`startAutoUpdate()` 的运行时调用。
- [ ] `forceRefresh()` 保持只读 SQLite；失败时不污染现有内存映射。
- [ ] 增加 `getLoadStatus()` 或等价只读状态：
  - `source: 'sqlite'`
  - `loaded`
  - `lastUpdate`
  - `lastError`
  - `themeCount`
  - `mappingCount`

### 2. 题材仓库命名收口

- [ ] 将 `ThemeRepository.ts` 从 `themeMapping` 薄包装调整为明确的前端题材基础仓库入口。
- [ ] 新增或整理方法：
  - `loadThemeBase()`
  - `isThemeBaseLoaded()`
  - `getThemes()`
  - `getThemeStocks(themeId)`
  - `getStockThemes(code)`
  - `getStockTags(code)`
  - `getStockReason(code)`
  - `refreshThemeBase()`
  - `getThemeBaseStatus()`
- [ ] 旧 `themeMapping` 导出可暂留，但内部文档标记为 deprecated adapter，不再作为新代码入口。
- [ ] 更新 `ThemeFacade/ThemeRuntimeCoordinator/sectorAnalyzer`，优先使用 `themeRepository`，减少直接引用 `ThemeDataService`。

### 3. 清理 `sectorAnalyzer` 私有映射依赖

- [ ] 删除 `(themeMapping as any).stockTagsMap/stockReasonsMap` 读取。
- [ ] `syncTagsAndReasonsToDataLayer()` 改为通过 `themeRepository.getStockTags/getStockReason`。
- [ ] `buildThemeBase()`、`initializeThemeInfo()`、`getThemeDetail()`、`getThemeStocks()`、`syncLeadersToThemes()` 改为通过仓库公开读口。
- [ ] 保留 `sectorAnalyzer` 旧方法名，但每个方法只委托 `themeFacade/themeRepository/JxbkThemeFeed`。
- [ ] `getStats().version` 升到 `11.0.0`，并暴露 `themeBaseSource: 'sqlite'`。

### 4. 兼容层收窄

- [ ] 梳理组件对 `Compat` 方法的调用：
  - `SectorPanel.vue`
  - `SectorDetail.vue`
  - `SectorStocksTree.vue`
  - `ThemeCorrelationPanel.vue`
  - `ExportPanel.vue`
- [ ] 在 `themeFacade` 增加非 Compat 正式别名：
  - `getJxbkBlocks()`
  - `getThemeStockMap()`
  - `getHotThemes()`
  - `getThemeDetail()`
  - `getThemeStocks()`
- [ ] 组件迁到正式别名；`Compat` 方法保留为 deprecated wrapper，不在新代码使用。
- [ ] `rotationService` 保留旧公开对象，但内部只读 `themeFacade.getRotationSummary()` 和 `refreshRuntime()`。

### 5. 后端合同检查

- [ ] 确认 `GET /api/themes/mapping` 返回完整标签和原因，无需前端 `/api/themes/batch` 增量补齐。
- [ ] 如缺少维护入口，补一个只限后端/CLI 的导入更新流程，不从前端浏览器写入。
- [ ] `GET /api/themes/counts` 用于前端诊断时返回：
  - `themeCount`
  - `mappingCount`
  - `stockCount`
  - `version`
  - `lastUpdate`
  - `source=sqlite`

### 6. 文档和验收

- [ ] 更新 `docs/theme-module/README.md`：V11 后题材运行时完全 SQLite-only。
- [ ] 更新 `docs/theme-module/findings.md/progress.md`：本地 fallback、外部批量 API、私有 Map 读取列入 V11 清理项。
- [ ] 更新 QuantBoard 文档：
  - `quant-board/docs/api-cli.md`
  - `quant-board/docs/database-migration-plan.md`
  - `quant-board/docs/architecture.md`
  - `quant-board/docs/AI_COLLABORATION.md`
- [ ] 运行验证命令并记录结果。

## 测试计划

### 前端

- `ThemeDataService.test.ts`
  - SQLite 成功加载。
  - SQLite 失败不 fallback 本地 JSON。
  - 不访问 `indexedDB`。
  - 不访问 `/api/themes/batch`。
  - `forceRefresh()` 失败不污染已有映射。
- `themeLegacyAdapters.test.ts`
  - `sectorAnalyzer` 旧 API 委托 `themeRepository/themeFacade/JxbkThemeFeed`。
  - `getStats()` 返回 SQLite source 和 JXBK cache stats。
- `ThemeRuntimeCoordinator.test.ts`
  - runtime context 使用仓库公开读口构建。
- 面板相关测试如已有覆盖则更新 mock 方法名。

### 后端

- `tests/test_theme_database.py`
  - mapping read 返回标签和原因。
  - counts 返回 `source=sqlite` 和 V10 导入后的基础计数字段。
  - verify/import 工具继续可用。

## 验证命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py -q
```

```powershell
pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts src/services/__tests__/themeLegacyAdapters.test.ts src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

## 风险与处理

- 风险：QuantBoard 后端未启动时题材面板无数据。
  - 处理：前端显示明确错误状态，不伪造本地 fallback。
- 风险：静态 JSON 曾覆盖部分标签/原因。
  - 处理：先用 V9 `verify-themes` 和抽样 API 检查 `themeDATA.db`，缺口通过后端导入修正。
- 风险：旧组件仍调用 `Compat` 方法。
  - 处理：本轮迁移到正式别名，同时保留 wrapper，后续版本再删 wrapper。
- 风险：误动快照 IndexedDB。
  - 处理：V11 搜索和改动限定 `src/services/theme*`、`ThemeDataService`、`sectorAnalyzer/rotationService/ThemeCorrelationAnalyzer` 和相关题材面板。
