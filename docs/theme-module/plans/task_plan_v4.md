# 题材模块优化升级 V4 任务计划

## Goal

完成 V3 之后的前端调用迁移、旧逻辑退场、可观测性与一致性验收，让 Dragon Board 前端稳定消费统一 `themeFacade`。

## Current Status

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete

## Phases

### Phase 1: 计划与残留调用清单

状态：complete

- 新增 `task_plan_v4.md`。
- 更新 `progress.md` 记录 V3 提交和 V4 启动。
- 更新 `findings.md` 记录 V4 残留调用类型。

### Phase 2: ThemeFacade UI 读口与测试

状态：complete

- 新增 UI 兼容读口：`getJxbkBlocksCompat/getJxbkLastUpdate/getThemeStockMapCompat/refreshJxbkAndFactors/getRuntimeSnapshot`。
- 增加一致性和空数据测试。
- 增加 refresh 结构化 debug 输出。

### Phase 3: UI 与导出迁移

状态：complete

- `SectorPanel/SectorDetail/SectorStocksTree/SectorRotation/ExportPanel/exportService` 优先使用 `themeFacade`。
- 保留旧服务 fallback。

### Phase 4: 旧服务兼容与预警去重

状态：complete

- `sectorAnalyzer` 主路径委托 `themeFacade/JxbkThemeFeed`，旧计算标记 deprecated fallback。
- `alertService` 保留 legacy block alert，但对 ThemeEvent 和 legacy block alert 做同帧去重。
- `rotationService` 明确 facade 为权威轮动源。

### Phase 5: 验证与收尾

状态：complete

- 运行局部测试、全量前端测试、RankTrend 回归和 Vue 类型检查。
- 记录验证结果和风险点。

## Decisions

- V4 不修改 QuantBoard schema。
- V4 不删除旧服务文件。
- UI 字段兼容优先，不改布局。
- `DataLayer` 仍保存 JXBK 原始数据，但 UI 主路径改用 `themeFacade`。

## Errors Encountered

| Time | Error | Resolution |
| --- | --- | --- |
