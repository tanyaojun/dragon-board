# 分相位验收前端可见化——设计文档

**日期**：2026-09-30 深夜（M2 收官后用户反馈驱动）
**动机**：M1/M2 全链后端运行，用户在前端完全无感——体系为实盘体感服务，用户却是唯一看不到它的人。
**状态**：方案经用户确认（B + Mongo 修正），直接进入实施。

## 1. 范围（用户三选全做）

1. **当前相位 chip**——热榜情绪面板概览 hero 区，纯前端零后端；
2. **相位历史时间线**——113 日日级相位着色段与情绪评分同图；
3. **北极星与监督线看板**——机械线逐项、走廊进度、月度 pass 序列、监督线状态。

## 2. 信息架构（方案 B）

- **挂载**：`HotlistEmotionPanel.vue`（现有 7 页签单文件面板）加**第 8 页签「相位验收」**（key='phase'，TABS 注册 + section + script refs，jev 第 7 页签同构先例）；**overview hero 情绪分条旁加相位 chip**（score 在手边，纯前端）。
- **第 8 页签布局**（上→下）：走廊进度（offense/defense 连续达线期数与 achieved 态）→ 北极星读数卡（机械线逐项 + 满仓对照）→ 相位历史时间线（ECharts，情绪评分线叠加）→ 月度 pass 序列。

## 3. 数据管道（Mongo 修正版）

| 内容 | 来源 | 读口 |
|---|---|---|
| chip | overview 已加载的 doc.emotionScore.score | 无（前端常量阈值 50，注释声明口径源=`phase_label_run.py` CANDIDATES sentiment_2b） |
| 时间线 | Mongo `hotlist_sentiment` EOD 文档逐日 score（源集合直读，免文件同步） | **新**：GET `/api/hotlist-sentiment/phase-history`（hotlist_routes.py 内薄读口，server 端按 sentiment_2b 映射 phase；前缀已在 proxy 白名单零改动） |
| 看板 | Mongo 新集合 **`phase_monitor`**（dragon_board_quant；kind=northstar 基线文档 / kind=monthly 逐月文档） | **新**：GET `/api/phase-monitor/board`（新路由文件 phase_monitor_routes.py；proxy 白名单加一行 `/api/phase-monitor/`） |

**写侧迁移**：`phase_northstar.py` 与 `phase_monitor_monthly.py` 各加 Mongo upsert（幂等）；本地 JSON 保留作调试副本不再是 API 源；存量 2 份产物重跑 CLI 即迁移。
**为什么 Mongo**：本地报告文件是研究批次惯例（易失、无消费方时成立）；前端成为消费方后按项目惯例（结构化数据=Mongo→FastAPI 读口→proxy→薄 service）迁入；全仓无"API 读本地文件"先例。

## 4. 错误处理（fail-visible）

- chip：score 缺失 → "相位不可用"降级态，不伪造；
- phase-history：无 EOD 文档日 → `phase:'unknown'` 如实返回；空集合 → 结构化空 + 原因；
- board：无 monthly 文档 → months:[] + 说明；northstar 缺 → 缺失原因字段。

## 5. 组件边界（AGENTS §2.1）

- service：`src/services/hotlist/phaseApi.ts`（fetchPhaseHistory / fetchPhaseMonitorBoard）；
- types：`src/types/hotlistSentiment.ts` 或新文件加相位类型；
- 组件：面板内 section 只展示与交互；阈值常量唯一化声明。

## 6. 测试

- 后端：phase-history 映射与空态、board 组装与空态（FastAPI TestClient，循 hotlist_routes 现有测试先例）；
- 前端：service 层与 chip computed（vitest，循 hotlist 服务测试先例）；
- 专项不跑全量；vue-tsc 必跑。

## 7. 诚实边界

- 相位定义证据状态（M1 判据未过、用户裁决立项）在前端展示为口径注记（第 8 页签页头一行），不隐藏；
- 首期 S+A/insufficient 监督线无自动源为 null，前端显示"人工补读"而非 0；
- 走廊 streak 前端计算属展示逻辑（3 行），后端 corridor_state 仍为正式语义源。
