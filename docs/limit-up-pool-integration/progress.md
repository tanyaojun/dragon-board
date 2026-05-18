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
- 已完成阶段 6 情绪和复盘扩展：
  - `DragonBreathAnalyzer` 将 `/api/limitup/ths/pools` 归一化为 `thsLimitUpPools` 市场证据。
  - 热榜情绪 `limitEvidence.market.thsPools` 增加 THS 池计数、炸板池数量和涨停股回撤榜摘要。
  - 情绪提示明确 `THS炸板池` 只作为全市场炸板补充证据，`涨停股回撤榜` 不等同于全市场亏钱效应。
  - DragonBreath 面板涨停证据区展示 THS 炸板池和涨停股回撤榜数量。
  - 快照 `limitSummary.thsPools` 增加 THS 池计数和回撤摘要，旧 `limit/zhaban/yesterdayZt` 字段保持不变。
- 已完成验证：
  - `pnpm test -- src/services/dataLoader/__tests__/LimitUpFeed.test.ts`
  - `pnpm test -- src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
  - `pnpm test -- src/services/__tests__/apiService.test.ts`
  - `pnpm test -- src/services/snapshot/__tests__/builders.test.ts`
  - `node --test proxy-server/__tests__/thsLimitupPools.test.mjs`
  - `node --test proxy-server/__tests__/notificationRoutes.test.mjs`
  - `pnpm test -- src/services/hotlist/__tests__/ThsLimitUpEventFeed.test.ts src/services/hotlist/__tests__/CompositeHotStockEventFeed.test.ts`
  - `pnpm test -- src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts src/services/snapshot/__tests__/builders.test.ts src/services/__tests__/DragonBreathAnalyzer.thsLimitUpPools.test.ts`
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

## 下一步

- 观察实盘期间 THS 细分池字段漂移和限流情况；如后续要正式入 QuantBoard 数据库，再按数据库迁移规则补 schema/API 文档。

## 2026-05-18 盘中落库修复

- 根据盘中 MongoDB 审计，确认 `snapshot_frames.limitSummary.thsPools` 今日没有对象落库，代理接口本身实时返回正常。
- 修复 `DataLayer.updateBreathData()` 白名单漏字段问题：保留 `marketData.thsLimitUpPools`，使后续快照构建能写入 `limitSummary.thsPools`。
- 修复个股涨停字段落库断档窗口：`updateLimitUpData()` 写入 tck2 扩展后，同步把涨停复盘字段投影到当前 `merged.stocks`，避免快照保存发生在下一次平台 merge 前时丢失 `firstZtTime/lastZtTime/boardHeight/highDays/reason/isNew`。
- 同步投影只覆盖涨停复盘字段，不用 THS 池中的 `speed/turnover/poolType` 覆盖当前行情字段。
- 影响范围：仅影响修复后新生成的快照；已落库的旧快照不会因 MongoDB ingest 幂等策略自动覆盖。
- 验证：
  - `pnpm test -- src/services/__tests__/DataLayer.test.ts`
  - `pnpm test -- src/services/__tests__/DataLayer.test.ts src/services/dataLoader/__tests__/LimitUpFeed.test.ts src/services/dataLoader/__tests__/ExtraDataProjector.test.ts src/services/snapshot/__tests__/builders.test.ts src/services/__tests__/DragonBreathAnalyzer.thsLimitUpPools.test.ts`
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

## 2026-05-18 收盘 15:00 四类快照审计

- 完成 MongoDB 只读审计，目标为 `dragonboard_live` 的 `quarter_hour/half_hour/hourly/daily` 四类 `15:00` 快照。
- 四类快照均存在 `snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
- 行数一致：
  - `quarter_hour`：247 股票行、24 板块/主线行。
  - `half_hour`：247 股票行、24 板块/主线行。
  - `hourly`：100 股票行、24 板块/主线行。
  - `daily`：247 股票行、24 板块/主线行。
- 四类快照均已落库 `limitSummary.thsPools`，且 `degraded=false`、`errors=[]`。
- THS 15:00 摘要计数：首板 72、二板 5、三板 1、四板 2、高标 1、炸板 34、冲板 23、涨停股回撤 6。
- 热榜股票行中涨停字段已落库：
  - 一刻/半点/日级：34 条有 `firstZtTime/lastZtTime/boardHeight/highDays`。
  - 整点：22 条有 `firstZtTime/lastZtTime/boardHeight/highDays`，因整点快照只保留前 100 名。
- 发现剩余质量风险：
  - `fengdan` 在四类 15:00 股票行均为 0，仍需确认 THS 上游封单额字段和映射。
  - `quarter_hour/half_hour/daily` 的 15:00 槽位各有 6 条 `price=0` 股票行，按 QuantBoard 当前 `evaluate_snapshot_quality` 会触发质量门禁失败；该问题主要来自港股/非 A 股热榜项，不属于 THS 涨停池落库失败。
- 详细审计记录已写入 `docs/limit-up-pool-integration/findings.md`。

## 2026-05-18 `fengdan` 字段追踪

- 已确认 THS 上游不是无数据：
  - 新细分池 `one/two/three/four/high` 合计 81 条，`volume_money` 81/81 存在且均为正数。
  - 旧 `/api/limitup/10jqka` 合计 81 条，`order_amount` 81/81 存在且均为正数。
  - 旧 HTML 端也把 `get_limit_up_stocks` 的 `item.volume_money` 直接展示为“封单额”。
- 已确认 15:00 不是股票未匹配：
  - 一刻/半点/日级各有 34 条快照股票行能匹配上游封单额代码，整点有 22 条。
  - 这些匹配行都有 `firstZtTime`，但 `fengdan > 0` 全部为 0。
- 全天序列显示 `fengdan` 曾在 11:00、13:15、13:30 快照中出现正值，15:00 又归零，说明字段语义可用，但刷新/投影链路不稳定。
- 当前疑点：
  - 旧 `mapLimitUpItems()` 没有把 `order_amount` 映射为 `fengdan`。
  - `ExtraDataProjector.projectRuntimeFields()` 没有从 `DataLayer.getLimitUpData()` 回灌 `fengdan/maxFengdan`。
- 详细证据已追加到 `findings.md` 的 `2026-05-18 fengdan 字段追踪审计`。
