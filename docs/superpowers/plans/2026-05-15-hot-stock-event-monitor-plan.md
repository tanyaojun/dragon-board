# 热榜个股异动监控完整实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次性完成选股通个股与板块异动事件接入、热榜/其他个股/板块分桶展示、盘中监控面板和本地语音设置验证。

**Architecture:** 通过 `proxy-server` 代理选股通 `event/history` 个股和板块事件，根前端 `src/services/hotlist/**` service 负责解析、去重、当日过滤、热榜/其他个股/板块分桶和订阅状态，Vue 面板采用窄列表事件流形态，并复用项目主题变量和 `usePanel` 浮层行为接入主工作台。`DataLayer` 只作为当前热榜股票池和龙头候选的只读来源，不承载第三方 API 调用。

**Tech Stack:** Node.js/Express proxy, Vue 3 + TypeScript + Vite, Vitest, node:test.

---

## 约束

- 同时监控个股异动事件和板块拉升/板块跳水 `11000`、`11001`，板块事件进入独立“板块”页。
- 个股异动不再过滤掉非热榜股票，必须区分“热榜个股”和“其他个股”两个页面。
- UI 面板参照用户提供的异动提醒截图，采用窄列表事件流和四页结构：热榜个股、其他个股、板块、设置；不套用 `SectorPanel.vue` 的题材大卡片布局。
- 搜索、异动类型筛选、语音开关、语音测试、语音音量和语速调整统一放入“设置”页。
- 一次性实现代理、service、UI 接入和测试，不拆版本。
- 不把选股通 API 请求写进 `DataLayer.ts`。
- 异动事件可标记热榜池、DragonReview 候选命中，但不自动生成买卖结论。
- 语音播报只播报“热榜个股”新增异动，“其他个股”和“板块”只展示不播报。

## 文件结构

### 代理层

- Create: `proxy-server/routes/xuangubao.js`
- Modify: `proxy-server/app.js`
- Modify: `proxy-server/server.js`
- Test: `proxy-server/__tests__/xuangubaoEvents.test.mjs`

### 前端服务层

- Create: `src/services/hotlist/hotStockEventTypes.ts`
- Create: `src/services/hotlist/XuangubaoAbnormalEventFeed.ts`
- Create: `src/services/hotlist/HotStockEventMonitorService.ts`
- Test: `src/services/hotlist/__tests__/XuangubaoAbnormalEventFeed.test.ts`
- Test: `src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts`

### UI 接入

- Create: `src/components/panels/HotStockEventMonitorPanel.vue`
- Modify: `src/App.vue`

## 验收标准

- `/api/xuangubao/events` 返回个股异动事件和 `11000`、`11001` 板块事件。
- feed 能把选股通原始个股和板块事件解析为统一 `HotStockAbnormalEvent`。
- monitor 保留当日全量事件，并输出 `hotStockEvents`、`otherStockEvents`、`sectorEvents` 三个分桶。
- monitor 能标记 DragonReview 候选命中。
- 同一事件重复刷新不重复展示。
- 接口失败时保留旧事件并暴露结构化错误。
- UI 面板提供“热榜个股 / 其他个股 / 板块 / 设置”四页。
- 设置页可手动刷新、筛选事件类型、搜索股票或板块、开关语音，并调整语音音量和语速。
- `App.vue` 有入口打开该面板，且不影响现有面板。
- 相关 Vitest、proxy 测试和类型检查通过，无法运行的验证必须说明原因。

## 任务

### Task 1: 代理接口

**Files:**
- Create: `proxy-server/routes/xuangubao.js`
- Modify: `proxy-server/app.js`
- Modify: `proxy-server/server.js`
- Test: `proxy-server/__tests__/xuangubaoEvents.test.mjs`

- [x] 写代理测试，覆盖默认个股和板块 types、成功响应、失败降级。
- [ ] 实现 `/api/xuangubao/events`，默认 `count=100`，最大 `200`。
- [ ] 只允许个股和板块事件 types：`10001,10005,10003,10007,10002,10006,10004,10008,10012,10014,10009,10010,11000,11001`。
- [ ] 注册路由并更新启动日志列表。
- [ ] 运行 `cd proxy-server; node --test __tests__/xuangubaoEvents.test.mjs`。

### Task 2: 前端事件 feed 与 monitor service

**Files:**
- Create: `src/services/hotlist/hotStockEventTypes.ts`
- Create: `src/services/hotlist/XuangubaoAbnormalEventFeed.ts`
- Create: `src/services/hotlist/HotStockEventMonitorService.ts`
- Test: `src/services/hotlist/__tests__/XuangubaoAbnormalEventFeed.test.ts`
- Test: `src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts`

- [x] 写 feed 测试，覆盖个股事件解析、板块事件解析、缺字段回退。
- [x] 写 monitor 测试，覆盖热榜/其他个股/板块分桶、候选标记、当日过滤、去重、失败保留旧状态。
- [ ] 实现类型、事件映射、方向和严重级别。
- [ ] 实现 feed，调用本地 `/api/xuangubao/events`。
- [ ] 实现 monitor 的 `refresh/start/stop/getState/subscribe`。
- [ ] 运行 `pnpm exec vitest run src/services/hotlist/__tests__/XuangubaoAbnormalEventFeed.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts`。

### Task 3: UI 面板与 App 入口

**Files:**
- Create: `src/components/panels/HotStockEventMonitorPanel.vue`
- Modify: `src/App.vue`

- [ ] 按异动提醒截图风格实现窄面板：标题、四页 tab、事件卡片列表、设置页和底部来源。
- [ ] 支持热榜个股、其他个股、板块分桶展示；设置页支持手动刷新、事件类型筛选、股票/板块搜索、语音音量和语速。
- [ ] 个股卡片显示时间、类型、股票、代码、涨跌幅、候选命中标记；板块卡片显示时间、类型和板块名称。
- [ ] 点击股票复用主应用选股逻辑，打开详情或选中股票。
- [ ] 在 `App.vue` 增加异动监控按钮、导航 tab、面板注册和懒加载。
- [ ] 运行 Vue 类型检查。

### Task 4: 综合验证

**Files:**
- Modify only if verification exposes defects.

- [ ] 运行 proxy 测试。
- [ ] 运行 hotlist service Vitest。
- [ ] 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- [ ] 如可行，运行 `pnpm build`。
- [ ] 检查 `git diff`，确认没有无关改动。
