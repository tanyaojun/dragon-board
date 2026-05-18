# 同花顺涨停池集成进度

## 2026-05-18

- 使用 `planning-with-files` 规则创建专题文档目录：`docs/limit-up-pool-integration/`。
- 完成 `LimitUpUpdate` 来源追踪：
  - 来源为 `/api/limitup/10jqka`。
  - 代理上游为同花顺 `dataapi/limit_up/limit_up_pool`。
  - 映射在 `src/services/dataLoader/LimitUpFeed.ts`。
- 完成运行态链路追踪：
  - `LimitUpFeed` -> `dataLayer.updateLimitUpData()` -> `ExtraDataProjector` -> `MergedStock`。
- 完成快照链路追踪：
  - 涨停时间、连板高度、封单等字段进入快照。
  - `reason` 当前被 daily compact 剔除，stock rows 也未保存。
- 实测 `/api/limitup/10jqka`：
  - 默认日期 20260518 盘前返回 `data.info: []`，只给交易状态和昨日涨跌停汇总。
  - 显式历史日期 20260515 返回 54 条具体股票明细，包含 `code/name/reason_type/first_limit_up_time/last_limit_up_time/high_days/order_amount` 等字段。
- 输出阶段计划到 `task_plan.md`。

## 当前状态

- 计划文档已落地。
- 已完成 `LimitUpFeed` 真实响应契约修复：
  - 秒级时间戳格式化为 `HH:mm:ss`。
  - `high_days` 文本解析为连板高度。
  - `continue_day: null` 时回退到 `high_days`。
- 已完成阶段 1 快照字段保留：
  - daily raw hotlist 保留 `reason`。
  - `SnapshotStockRow` 和 `buildSnapshotStockRows()` 保留 `reason`。
- 已完成阶段 2 代理聚合接口：
  - 新增 `GET /api/limitup/ths/pools?date=YYYYMMDD`。
  - 聚合首板、二板、三板、四板、高标、炸板、冲板和涨停股回撤池。
  - 单个池失败时只降级该池，并在 `errors` 中返回结构化原因。
- 已完成阶段 3 映射标准化：
  - 新增 `LimitUpPoolType`、`LimitUpPoolStock`、`mapThsLimitUpPools()`。
  - 支持 `limit_up_reason`、`limit_up_time`、`continue_day`、`volume_money`、`rise_rate`、`max_drawdown` 等字段映射。
- 已完成阶段 4 运行态接入：
  - `apiService.getThsLimitUpPools()` 调用新代理接口。
  - `DataLoaderFacade.loadLimitUpData()` 在旧涨停池后加载 THS 细分池增强。
  - 增强加载只写入真实存在的字段，避免炸板/回撤池空字段覆盖旧 `reason`、涨停时间和连板高度。
- 已完成阶段 5 异动雷达融合：
  - 新增 THS 涨停池事件 feed，将封板、炸板、冲板映射为异动事件。
  - 新增组合 feed，服务层融合选股通与 THS 事件，并按事件身份去重。
  - 大面回撤池不伪造成封板事件，留作后续风险扩展。
  - 代理端后台 worker 与 HTTP route 共享同一个飞书异动雷达客户端，避免冷却状态割裂造成重复推送。
- 已完成验证：
  - `pnpm test -- src/services/dataLoader/__tests__/LimitUpFeed.test.ts`
  - `pnpm test -- src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
  - `pnpm test -- src/services/__tests__/apiService.test.ts`
  - `pnpm test -- src/services/snapshot/__tests__/builders.test.ts`
  - `node --test proxy-server/__tests__/thsLimitupPools.test.mjs`
  - `node --test proxy-server/__tests__/notificationRoutes.test.mjs`
  - `pnpm test -- src/services/hotlist/__tests__/ThsLimitUpEventFeed.test.ts src/services/hotlist/__tests__/CompositeHotStockEventFeed.test.ts`
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

## 下一步

- 阶段 6：把 THS 炸板池计数和涨停股回撤池作为情绪/复盘补充证据。
