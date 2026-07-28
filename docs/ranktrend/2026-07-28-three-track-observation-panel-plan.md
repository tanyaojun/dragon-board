# RankTrend 三轨观察面板实施计划

**目标：** 将共振、排名趋势、生命周期作为三项独立观察指标展示，并提供覆盖式右侧观察舱。

## 1. 评分合同

- 在 `src/services/rankTrend/observationScoreComposer.ts` 实现排名趋势强度和生命周期机会成熟度。
- 在邻近测试中先验证权重、方向、阶段适配、风险扣分和 veto 不清零，再接入分析管线。
- 在 `src/services/rankTrend/types.ts` 增加结构化 `observation` 输出，保留可回算因子。

验证：`pnpm exec vitest run src/services/rankTrend/__tests__/observationScoreComposer.test.ts`

## 2. 主表三列与 tooltip

- 删除 `变化%`、`跃迁度` 列配置，保留其底层数据供 tooltip 使用。
- 新增 `排名趋势`、`生命周期`，调整共振单元格为方向箭头加百分比。
- 三列共用现有快速 tooltip；候选池只保留在 tooltip。
- 三列点击分别发出观察舱轨道入口。

验证：`pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts`

## 3. 观察读模型与面板

- 新增只读观察服务，复用当前 RankTrend 结果和最近分析序列，输出三轨统一视图模型与结构化缺失原因。
- 新增 `RankTrendObservationPanel.vue`，实现覆盖式右侧抽屉、三轨切换、Esc 关闭和股票切换。
- 共振轨展示路径折线和五因子；技术轨展示 MACD 与四信号；生命周期轨展示阶段、四因子和双风险。
- 不写回 DataLayer、候选池、交易池或快照。

验证：面板邻近 Vitest、`vue-tsc`、`pnpm build`。

## 4. 浏览器验收

- Playwright 验证三个入口、tooltip 候选池、抽屉切轨、Esc、视口边界和控制台。
- 保存桌面截图到 `output/playwright/`，运行 `git diff --check`。
