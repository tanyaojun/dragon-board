# 同花顺涨停池集成优化计划

## 目标

把同花顺涨停生态数据作为 Dragon Board 的增强数据源，补齐涨停原因、涨停时间、连板层级、冲板、炸板和涨停股回撤风险，同时保持现有数据层、快照层和异动雷达边界清晰。

## 成功标准

- 热榜股票运行态能稳定拿到 `reason`、`firstZtTime`、`lastZtTime`、`boardHeight`、`highDays`、`fengdan` 等字段。
- 异动雷达能融合 THS 的封板、冲板、炸板事件，且不会与选股通事件重复刷屏。
- 快照 raw payload 和 stock rows 均能保留用于复盘的关键涨停池字段，至少包括涨停原因、涨停时间、连板高度。
- THS 接口失败时返回结构化降级原因，不影响已有热榜、题材和快照主链。
- 修改范围限定在代理、数据加载、事件 feed、快照投影和必要测试，不做无关 UI 重构。

## 阶段计划

### 阶段 0：现状核验

状态：complete

验证：
- 追踪 `LimitUpUpdate` 来源、写入 DataLayer 的路径。
- 追踪涨停池字段是否进入快照 raw payload 和 stock rows。
- 输出结论到 `findings.md`。

### 阶段 1：修复现有涨停池字段快照保留缺口

状态：complete

问题：
- 当前 `reason` 已进入运行态股票，但 daily compact 快照明确剔除了 `reason`。
- `SnapshotStockRow` 类型和 `buildSnapshotStockRows` 当前未保存 `reason`。

已改动：
- `src/services/snapshot/projectionBundle.ts`：`compactHotlistItem` 增加 `reason`。
- `src/services/snapshot/types.ts`：`SnapshotStockRow` 增加 `reason?: string`。
- `src/services/snapshot/builders.ts`：`buildSnapshotHotlistItem` 和 `buildSnapshotStockRows` 保留 `reason`。
- `src/services/snapshot/__tests__/builders.test.ts`：把“reason 被剔除”的旧断言改为“reason 被保留”。

验证：
- `pnpm test -- src/services/snapshot/__tests__/builders.test.ts`
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

### 阶段 1.5：修复现有 `LimitUpFeed` 真实响应契约

状态：complete

问题：
- `/api/limitup/10jqka` 历史日期返回的 `first_limit_up_time` / `last_limit_up_time` 是秒级时间戳字符串，不是 `HH:mm:ss`。
- `high_days` 实测为 `首板`、`5天3板` 这类文本，现有类型误标为 `number`。
- `continue_day` 实测可能为 `null`，旧映射会把 `boardHeight` 写成 `null`，导致后续连板高度回退不足。

已改动：
- `src/services/dataLoader/types.ts`：放宽 `LimitUpItem.high_days`、`continue_day`、`high_days_value` 类型。
- `src/services/dataLoader/LimitUpFeed.ts`：新增时间格式化和连板文本解析。
- `src/services/dataLoader/__tests__/LimitUpFeed.test.ts`：增加真实响应契约测试。

验证：
- `pnpm test -- src/services/dataLoader/__tests__/LimitUpFeed.test.ts`
- `pnpm test -- src/services/dataLoader/__tests__`
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

### 阶段 2：代理层新增 THS 细分涨停池聚合接口

状态：complete

已新增接口：
- `GET /api/limitup/ths/pools?date=YYYYMMDD`

上游来源：
- 涨停分层：`mobileapi/hotspot_focus/stock_pool/v1/get_limit_up_stocks`
- 大面回撤：`mobileapi/hotspot_focus/stock_pool/v1/get_drawdown_stocks`
- 炸板：`dataapi/limit_up/open_limit_pool`
- 冲板：`dataapi/limit_up/limit_up`

设计要求：
- 每个池独立请求、独立降级。
- 返回统一 `ok/source/date/timestamp/pools/degraded` 结构。
- 不在 Vue 前端直接请求同花顺公网接口。

验证：
- `node --test proxy-server/__tests__/thsLimitupPools.test.mjs`

### 阶段 3：扩展 `LimitUpFeed` 标准化映射

状态：complete

已新增标准类型：
- `LimitUpPoolStock`
- `LimitUpPoolType = 'one' | 'two' | 'three' | 'four' | 'high' | 'failed' | 'rushing' | 'drawdown'`

字段映射重点：
- `limit_up_reason` / `reason_type` -> `reason`
- `limit_up_time` / `first_limit_up_time` -> `firstZtTime`
- `last_limit_up_time` -> `lastZtTime`
- `continue_day` -> `boardHeight`
- `high_days` 文本或 `high_days_value` 编码 -> `highDays` / `boardHeight`
- `volume_money` 或上游封单字段 -> `fengdan`
- `rise_rate` -> `speed`
- `max_drawdown` -> `maxDrawdown`

设计要求：
- 保留现有 `mapLimitUpItems` 和 `/api/limitup/10jqka` 行为。
- 新增映射函数不要改变旧调用方签名，先作为增强路径接入。
- 所有数字字段做有限数字判断，空值回落为 `undefined` 或 0，不能产生 NaN。
- 秒级时间戳字符串需格式化为 `HH:mm:ss`；不要把 `1778810904` 直接写入 UI 或快照时间字段。
- `high_days_value` 需按 `板数 = floor(value / 65536)` 解码，不能原样写成 196613。

验证：
- `src/services/dataLoader/__tests__/LimitUpFeed.test.ts` 增加 THS 细分池 payload 映射测试。
- `pnpm test -- src/services/dataLoader/__tests__/LimitUpFeed.test.ts`

### 阶段 4：把 THS 增强字段写入运行态股票

状态：complete

已改动：
- `src/services/apiService.ts` 增加 `getThsLimitUpPools(date?)`。
- `src/services/dataLoader/LimitUpFeed.ts` 增加增强加载函数。
- `src/services/dataLoader/DataLoaderFacade.ts` 在加载平台热榜后调用增强加载，仍通过 `dataLayer.updateLimitUpData` 写入。
- `src/services/dataLoader/LimitUpFeed.ts` 增强加载只写入有值字段，避免炸板/回撤池空字段覆盖旧涨停原因和时间。

验证：
- `pnpm test -- src/services/dataLoader/__tests__/LimitUpFeed.test.ts`
- `pnpm test -- src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
- `pnpm test -- src/services/__tests__/apiService.test.ts`

### 阶段 5：接入异动雷达事件融合

状态：complete

已改动：
- 新增 `src/services/hotlist/ThsLimitUpEventFeed.ts`，实现 `HotStockEventFetcher`。
- 新增 `src/services/hotlist/CompositeHotStockEventFeed.ts`，把选股通和 THS 事件源组合在服务层。
- `HotStockEventMonitorService` 默认使用组合 feed，不在 `HotStockEventMonitorPanel.vue` 中写数据源逻辑。
- 代理启动 runtime 复用同一个飞书异动雷达客户端，使后台 worker 与 HTTP route 共享冷却状态。

事件映射：
- `failed` -> `打开涨停板`
- `rushing` -> `逼近涨停`
- `one/two/three/four/high` -> `封涨停板`
- `drawdown` 不直接伪造成封板事件，留给阶段 6 作为风险扩展。

验证：
- `pnpm test -- src/services/hotlist/__tests__/ThsLimitUpEventFeed.test.ts src/services/hotlist/__tests__/CompositeHotStockEventFeed.test.ts`
- `node --test proxy-server/__tests__/notificationRoutes.test.mjs`

### 阶段 6：情绪和复盘扩展

状态：complete

已改动：
- `DragonBreathAnalyzer` 读取 `/api/limitup/ths/pools`，归一化为 `thsLimitUpPools` 结构化市场证据。
- `HotListSentimentAnalyzer` 将 THS 炸板池和涨停股回撤榜写入 `limitEvidence.market.thsPools`。
- 情绪告警中明确区分：
  - `THS炸板池` 只作为全市场炸板补充证据。
  - `涨停股回撤榜` 不等同于全市场亏钱效应。
- `DragonBreathPanel` 涨停证据区域展示 THS 炸板池数量和涨停股回撤榜数量。
- 快照 `limitSummary.thsPools` 增加 THS 池计数和回撤风险摘要，旧 `limit/zhaban/yesterdayZt` 字段保持不变。

验证：
- 只新增结构化字段，不改变旧情绪指标含义。
- 快照质量门禁仍通过。
- `pnpm test -- src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts src/services/snapshot/__tests__/builders.test.ts src/services/__tests__/DragonBreathAnalyzer.thsLimitUpPools.test.ts`

## 风险与约束

- THS 字段可能漂移，映射层必须多 key 兼容并保留 `raw`。
- 冲板高频刷新可能限流，必须接入缓存、交易时间门禁和退避。
- `DataLayer.ts` 只作为运行态内存和订阅层，不新增 HTTP 请求、快照拼装或算法规则。
- QuantBoard 入库若后续涉及数据库字段，必须同步更新 QuantBoard 文档和迁移规则。

## 最小执行建议

先执行阶段 1 到阶段 3。理由：先保证已有涨停原因不在快照链路丢失，再补 THS 细分池源和映射；异动雷达融合放到字段稳定之后。
