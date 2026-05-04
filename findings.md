# 题材模块重构发现记录

## 代码现状

- `ThemeDataService.ts` 同时承担静态映射、标签原因、缓存、API 更新和 DataLayer 同步。
- `sectorAnalyzer.ts` 同时承担 JXBK 拉取、热度计算、题材同步到个股、标签原因同步、板块预警和查询 facade。
- `rotationService.ts` 依赖 JXBK 和 `localStorage` 推导轮动/主线，主要服务展示和 DragonReview 战场种子。
- `ThemeCorrelationAnalyzer.ts` 有联动和龙头识别能力，但是 `@ts-nocheck`，且没有并入统一题材因子。
- `alertService.ts` 自己扫描 JXBK 状态生成板块/个股预警，与题材分析职责重叠。

## 子任务结论：快照与 QuantBoard

- 前端题材快照字段当前通过 `SnapshotSectorRow.metadata` 有扩展空间。
- 个股题材当前保存 `themes/mainTheme/themeHeat/themeLevel`。
- QuantBoard SQLite 当前把 `themes` 存为 `themes_json`，主字段存为 `main_theme/theme_heat/theme_level`。
- 最小兼容方案：题材因子先放 `sectorRows.metadata.themeFactor`，个股暴露先扩展 `themes[]` 元素；暂不新增数据库列。

## 子任务结论：热度与 DragonReview

- 最小接入应投影到现有 `HotTheme` 和 `stock.themes`，不要第一阶段直接改 DragonReview 判断引擎。
- `dataLoader` 会多处从 `dataLayer.getStockThemes()` 回写 `mainTheme/themeHeat`，新投影必须先写入 DataLayer，否则会被旧逻辑覆盖。
- 当前 `StockHotnessCalculator` 没有使用 `themeHeat`，题材贡献纳入热度需要显式加权和测试。

## 设计约束

- 保持 UI 字段兼容。
- 新类型优先作为策略解释和中观因子，不直接替代 RankTrend 或最终交易信号。
- 不批量删除文件。
- 保护现有工作区状态。
