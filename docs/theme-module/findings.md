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
