# 题材轮动状态页签设计（/api/theme-rotation/summary 前端消费）

- 日期：2026-09-27
- 状态：设计已确认（用户 2026-09-27 拍板：SectorPanel 新页签 + 摘要区/全量表分层）
- 背景：后端 `/api/theme-rotation/summary` 在位（Redis 缓存、返回最近含 rotationSummary 的 half_hour 15:00 帧 + 245 行题材轮动状态），`src/` 零消费。轮动状态口径（rotationState 六值 × marketPhase × mainLines）已经 R2/R3/R3b 三轮验证，是盘面观察层的有效信息。
- 单一事实源：后端已有 API，前端零计算纯消费，不产生双源。

## 已核实接口事实（2026-09-27 生产 API 实测）

- `GET /api/theme-rotation/summary?snapshot_type=half_hour`（dataset_id 默认 dragonboard_live）：
  - `data.frame`：`{tradingDate, slotTime, snapshotId, timestamp, rotationSummary: {marketPhase, rotationSpeed, mainlineConcentration, maxBoardHeight, mainLines[], inflowThemes[], outflowThemes[]}}`（mainLines 空数组 = 引擎判定无主线，有语义状态非缺失；inflow/outflowThemes 为 `{themeId, themeName}` 列表）；
  - `data.statuses`：245 行 `{entityKey, entityName, rank, rankChange, rotationState, rotationScore, factorBreakdown: {strength, flow, breadth, crowding, lifecycle}, flowTrend, heatTrend, breadthTrend, crowdingTrend, mainlineConcentrationRank, qualityFlags[], reasons[]}`；
  - 无帧时 404（`{ok:false, status:"error"}`）。
- 前端桥接范式：组件 → `themeFacade.getXxx()`（`src/services/theme/ThemeFacade.ts`，比照 `getThemeMomentumSummary`）。
- 面板体系：SectorPanel 已有页签结构（`panel-tabs`/`tab-btn`，"热门题材"页签）；9-25 面板收敛后不新增顶栏入口。

## 设计

### 架构与文件

| 文件 | 职责 |
|---|---|
| `src/services/theme/ThemeFacade.ts` | 新增 `getRotationSummary({snapshotType})` 与 `ThemeRotationSummary` 类型（就近定义，比照 ThemeMomentumSummary 先例） |
| `src/components/panels/SectorRotationTab.vue`（新建） | 页签主体：摘要区 + 可展开全量状态表 |
| `src/components/panels/SectorPanel.vue` | tabs-left 增加"🔄 轮动状态"页签按钮；`view === 'rotation'` 分支渲染新组件 |

### 交互与数据流

- 懒加载：首次切到页签才请求；手动刷新按钮；loading/error/retry 三态（ThemeMomentumPanel 同款模式）；不做轮询。
- 摘要区（固定顶部）：数据时点徽章（tradingDate+slotTime）→ marketPhase 六态徽章（中文映射：cooling 退潮 / climax 高潮 / rising 升温 / ice 冰点 / chaos 混沌 / neutral 中性 / unknown 未知）→ rotationSpeed / mainlineConcentration / maxBoardHeight 指标 → mainLines 主线名单（空 = "引擎判定无主线"显式文案）→ 流入/流出题材 chips → rotationState 状态分布计数条。
- 全量状态表（默认折叠，点击展开）：245 行纯渲染不做虚拟化；列 = 题材名 / rank / rankChange / rotationState 徽章 / rotationScore / 四维因子分解（strength/flow/breadth/crowding）/ flowTrend / qualityFlags；点列排序（默认 rank 升序）+ rotationState 筛选按钮组。

### fail-visible

- 404/无帧 → 显式"暂无轮动数据"空态（不伪装）；
- mainLines 空 → "引擎判定无主线"文案（有语义状态）；
- qualityFlags 行内小标记展示；未知 rotationState 值原样展示不崩溃；
- 字段缺失 → 显示 "—"，不以 0 伪装。

### 样式

复用 SectorPanel 现有 `panel-tabs`/`tab-btn` 样式体系与主题 CSS 变量（暗色工业金融）；rotationState 色映射遵循 A 股语义（inflow 红系 / outflow 绿系 / neutral 灰 / mainline 金橙 / emerging 青 / cooling 蓝）；视觉质感由 frontend-design 在实现阶段把关。

## 测试策略

- Vitest 组件测试（`src/components/panels/__tests__/SectorRotationTab.test.ts`，mock facade，比照 ThemeMomentumPanel.test.ts）：摘要渲染、marketPhase 徽章映射、mainLines 空文案、表排序/筛选、错误重试态；
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json` 类型检查 + `pnpm build`；
- 浏览器验收：按用户既定分工由用户本人执行（检查页签切换、摘要字段渲染、表排序筛选、控制台无错误）。

## 非目标

- 不做轮询/自动刷新；不做虚拟滚动；不动后端 API；不新增顶栏入口；不在本批消费 mainlineConcentrationRank 做额外分析。

## 二轮增补（2026-09-27 用户验收反馈，已确认）

- **`SectorRotationTree.vue`（新建）**：轮动状态页签的嵌入式树形视图列表——按 rotationState 分组（mainline/inflow/emerging/neutral/outflow/cooling/unknown）的 tree-node 卡片列表，样式参照 `SectorStocksTree.vue`（node-header/node-metrics/node-progress/选中高亮）；卡片含题材名/状态徽章/rank 徽章/轮动分/rankChange/flowTrend/rotationScore 进度条；点击卡片 emit select。
- **`SectorRotation.vue`（新建）**：题材轮动明细弹出面板——Teleport + usePanel 弹出范式（参照 `SectorDetail.vue`）：←返回头部 + info-card（名称/状态/数据时点）+ metrics-grid（轮动分/排名/净流入趋势）+ 四维因子卡（强度/资金/广度/拥挤，进度条）+ 质量标记；数据直接取自 statuses 行（零额外 API）。
- **交互链**：轮动状态页签 = 摘要区 + 状态筛选 chips（上移为树形/表格共用）+ SectorRotationTree（主列表）+ 展开状态表（保留折叠）；点击树形卡片 → SectorRotation 弹出面板（triggerRect 定位），←返回关闭。
- 数据时点/筛选状态由 SectorRotationTab 统一持有，两个视图共用。
