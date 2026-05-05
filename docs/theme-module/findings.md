# 题材模块重构发现记录

## 当前口径

- `ThemeFacade` 和 `ThemeRuntimeCoordinator.refreshRuntime()` 是题材运行态唯一事实主链。
- `themeFacade` 统一暴露题材因子、个股暴露、轮动摘要、题材事件、JXBK 兼容读口和 runtime snapshot。
- `sectorAnalyzer`、`rotationService`、`alertService` 继续保留旧公开 API，但业务事实来源均来自 `themeFacade` 或题材 runtime store。
- QuantBoard 题材字段和回测开关沿用 V2 结果，V7 不修改数据库和回测执行策略。

## 已清理内容

- V6 已统一刷新路径：`refresh()/refreshThemeFacadeState()/refreshRuntime()` 均进入 runtime coordinator。
- V6 已把题材事件和 legacy block event 的生成统一到 `ThemeRuntimeCoordinator`，`alertService` 只做冷却、去重、保存和状态管理。
- V7 已移除 `rotationService` 内部旧手工轮动、主线、市场阶段和 localStorage 持续性事实计算。
- V7 已移除 `sectorAnalyzer` 内部旧热度计算、旧 JXBK 热度更新、旧板块预警生成和旧 hot theme fallback。
- V7 已把 `config/factors`、`ContextBuilder`、算法预热的题材事实读取迁到 `themeFacade`。

## 当前保留边界

- `sectorAnalyzer.loadSectorStocks()` 仍保留，用于 `SectorDetail/SectorStocksTree` 的板块成分股懒加载；后续可迁入 `JxbkThemeFeed`。
- `App.vue/main.ts` 仍挂载 `window.sectorAnalyzer/window.rotationService`，用于控制台、旧调试脚本和兼容服务注册。
- `RefreshCoordinator` 仍保留 `sectorAnalyzer` 节点，但该节点现在只是 legacy adapter，不再持有独立题材事实。
- `DataLayer` 仍保存 JXBK 原始 blocks/stockMap，这是运行态缓存和快照来源，不是题材业务编排入口。

## 后续候选

- V8 可考虑把 `loadSectorStocks` 和成分股缓存迁入 `JxbkThemeFeed`。
- V8 可考虑增加题材 runtime 调试面板或回放一致性工具。
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
