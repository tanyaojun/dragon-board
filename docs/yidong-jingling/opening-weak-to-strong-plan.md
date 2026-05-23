# 异动精灵开盘竞价弱转强落地方案

更新时间：2026-05-22

实现状态：首版代码链路已落地，覆盖 TS/C# 共享 fixture、python-bridge 强制采样元数据、proxy 本地信号缓存、网页板异动雷达、桌面版上报和 Dragon Board 主表徽标。仍需早盘实盘确认 `09:25` 覆盖率和端到端延迟；dry-run UI 尚未完成，当前仅合同和 proxy 支持 `dryRun` 字段。

## 目标

在不接入 QMT L2、不追求通达信真十档的前提下，复用当前 `mootdx + python-bridge + YiDongJingLing.exe` 链路，捕捉这类早盘盘口：

1. `09:25` 集合竞价结束附近，L1 可见价格偏弱，例如涨幅小于等于 0。
2. `09:30-09:35` 连续竞价开始后价格快速上移，形成明显跳空。
3. 跳空后继续冲高、逼近涨停或封板。
4. `YiDongJingLing.exe` 语音提醒。
5. Dragon Board 行情主界面和异动精灵主界面都有醒目的信号标识。

本方案只使用 L1 稳定可见字段：价格、昨收、开盘、最高、成交量、成交额和五档盘口。该信号命名为“竞价弱转强”，不宣称真 L2、逐笔委托或完整集合竞价队列。

网页板的“竞价弱转强”检测主数据源统一改为 `python-bridge` WebSocket 实时行情，不使用现有选股通/同花顺 HTTP 异动事件源做主判断。选股通/同花顺事件源只保留为盘中辅助线索。

重要校正：`002552 宝鼎科技` 只是一个代表性子形态，不能把“竞价弱转强”写死成这一种公式。V3 应把它设计为“模式族”：同一个 `opening_weak_to_strong` 信号下保存具体 `variant`、`score`、`factors` 和 `riskFlags`，检测器按多因子评分和硬门槛共同判断。

子 Agent 交叉评审结论：方案整体有条件通过，但实施前必须补齐四个门禁：

1. `09:25` 强制采样闭环：不能只等 `quote_patch`，因为价格不变时 bridge 可能不广播。
2. 跨端语音仲裁：proxy 不能只事后去重，必须返回是否允许当前端播报。
3. TS/C# 统一 golden fixture：两端必须读同一份机器可读样例，防止口径漂移。
4. Dry-run 演练模式：早盘先支持只记录、不播报、不强高亮，用于验证基线和误报。

## 样例口径

以 `002552 宝鼎科技` 的讨论样例为准：

| 口径 | 价格 | 相对昨收 36.20 |
|------|------|----------------|
| `09:25` 附近最后可见 L1 价格 | 35.68 | -1.44% |
| 官方日线开盘价 | 36.92 | +1.99% |
| 通达信分时第一条价格 | 37.48 | +3.54% |
| 当日涨停价 | 39.82 | +10.00% |

核心不是“开盘固定高开 2%”，而是：

```text
09:25 竞价最后价偏弱
→ 09:30 第一阶段价格快速抬升
→ 09:30-09:35 冲板概率显著提高
```

## 网上规则复核和采纳边界

### 官方交易规则边界

深交所 2023 交易规则确认：`09:15-09:25` 为开盘集合竞价，`09:30-11:30`、`13:00-14:57` 为连续竞价；`09:20-09:25` 不接受撤销申报。集合竞价成交价按可实现最大成交量等原则产生，集合竞价所有成交以同一价格成交。开盘价由集合竞价产生，不能产生时由连续竞价第一笔成交价产生。

这带来三个实现约束：

1. `09:20` 后的数据比 `09:15-09:20` 更可信，因为无法撤单。
2. `09:25` 价、官方开盘价、`09:30` 后第一阶段观察价是三个不同口径，必须同时保存，不能混用。
3. 盘后分钟线很难还原 `09:25` 竞价最后可见状态，所以第一版必须实盘采样。

### 游资和短线社区口径

公开短线文章对“弱转强”的共识不是单一阈值，而是“预期差 + 资金承接”：

| 维度 | 常见说法 | V3 采纳方式 |
|------|----------|-------------|
| 前一日弱 | 烂板、炸板、断板、长上影、尾盘漏单、放量分歧、情绪冰点 | 作为 `previousWeakScore` 可选增强；第一版没有昨日结构数据时不设为硬门槛 |
| 次日强 | 超预期高开、低开快速翻红、开盘 1-5 分钟迅速上攻或封板 | 作为 `variant` 分类和核心评分项 |
| 量能 | 高开要带量；竞价量/成交额过小是假强；开盘 1-5 分钟成交额增量要跟上 | L1 可稳定使用 `amount`、`amountDelta`；历史竞价量占比后续有数据再加 |
| 承接 | 开盘不快速跌破开盘价/昨收，能站稳并继续推高 | 使用 `holdAboveOpenSeconds`、`maxPullbackPctPoint`、`followThroughPctPoint` 评分 |
| 板块 | 龙头或主线板块共振更可靠，杂毛跟风容易诱多 | 后续接 Dragon Board 题材/热榜强度做加分，第一版只记录 `contextMissing` |
| 风险 | 高开过大无量、非核心股、开盘回补缺口、跌破分时均价线是假弱转强 | 写入 `riskFlags`，影响评分和语音强度 |

### 量化实现边界

量化上最稳的是把“弱转强”拆成特征工程，不直接写死口号：

```text
基础时间门槛
  + 09:25 基线完整性
  + 价格从弱到强的跳变
  + 成交额或成交额增量
  + 开盘承接
  + 可选上下文：昨日弱势、板块强度、连板地位
  - 风险扣分：无量、开盘回落、过度高开、低流动性
= score / confidence / variant
```

第一版不强依赖逐笔、未匹配买卖量、真实竞价撤单队列或十档盘口。若 `mootdx` 实盘能稳定返回匹配量、未匹配量、买卖方向，才作为增强因子；否则不得作为硬条件。

信号应保存三个价格口径：

| 字段 | 含义 | 来源 |
|------|------|------|
| `auctionFinalPrice` | `09:25` 附近最后可见 L1 价格，也称 bridge 观测竞价基线 | 实盘在 `09:24:50-09:25:10` 采样有效当前价 |
| `officialOpen` | 交易所日线开盘价 | `quotes().open` |
| `firstOpenWindowPrice` | `09:30` 后工具首次观测到的连续竞价价格 | `quotes().price` 或第一根分时价格 |

## 成功标准

1. `09:24:50-09:25:10` 对监控池高频采样并锁定每只股票的 `auctionFinalPrice`。
2. `09:30:00-09:35:00` 对同一监控池继续接收行情，计算 `auctionPct`、`openPct`、`firstWindowPct`、`jumpPctPoint`。
3. 当股票满足“竞价弱转强”规则时，只触发一次高优先级异动。
4. `YiDongJingLing.exe` 在 `confidence >= strong` 且 proxy 返回桌面为 `voiceOwner` 时播报该信号。
5. 异动精灵主表格中该行使用高优先级视觉样式，类型显示“竞价弱转强”。
6. Dragon Board 主行情列表中该股票有醒目信号，例如“竞价弱转强”徽标、红色高亮或置顶短时闪烁。
7. 每条信号记录足够复盘，至少包含 `09:25` 价、开盘价、首次上移价、跳空百分点、触发时间、成交额和冲板状态。
8. 验收测试覆盖：样例命中、阈值边界、非交易时段不误报、缺失 `09:25` 基线不误报、同股只报一次。

## 非目标

- 不重新推进 TDX `7719` 真 L2。
- 不接入 QMT L2。
- 不依赖通达信客户端级十档、逐笔委托、撤单队列。
- 不承诺盘后能补齐历史 `09:25` 竞价最后价；该值必须实盘采样。
- 不在第一阶段做全市场 5000 只高频扫描；默认使用用户监控池、八平台热榜池或自定义强势池。
- 不把选股通/同花顺 HTTP 异动事件接口当作 `opening_weak_to_strong` 主数据源。

## 网页板数据源决策

当前网页板异动雷达代码主链是 HTTP 事件源，而不是逐股实时盘口源：

| 链路 | 当前能力 | 是否可做主检测 |
|------|----------|----------------|
| `XuangubaoAbnormalEventFeed` / `/api/xuangubao/events` | 获取选股通/选股宝事件历史，字段主要是 `event_type`、`event_timestamp`、`price`、`pcp`、`mtm`、相关板块 | 否。没有 `09:25` 竞价最终价、官方开盘价、逐股成交额增量，也不能按自定义监控池高频采样 |
| `ThsLimitUpEventFeed` / 同花顺涨停池 | 获取涨停池、炸板池、冲板池等结果型数据 | 否。适合确认封板/冲板状态，不适合还原 `09:25 → 09:30` 弱转强过程 |
| `python-bridge` / `webSocketService` | 推送 `FULL_STATE` / `QUOTE_PATCH`，含 `lastPrice`、`changePct`、`open`、`preClose`、`amount`、`volume`、`sourceTs` | 是。可在浏览器内实盘锁定 `09:25` 基线，并在 `09:30-09:35` 计算跳空 |

结论：网页板第一版必须和桌面版一样订阅 `python-bridge`。现有选股通/同花顺事件源可以继续展示在“异动雷达”里，但 `opening_weak_to_strong` 的检测、语音和主表信号都以 `python-bridge` 实时 L1 quote 为准。

代码层面还要修正文案：`HotStockEventMonitorPanel.vue` 当前显示“选股通数据源”，V3 后应改成“实时行情 + 异动事件源”或等价表达，避免误导。

网页端检测器不要第一版依赖 `DataLayer` 里的股票行字段，因为当前实时协调器写入 DataLayer 时主要投影 `price/change/volume/turnover/sourceTs`，不保证完整保留 `open/preClose`。弱转强检测应直接消费 `webSocketService` 事件 payload 或 `getQuotesBatch()` 里的 `QuotePatch`，确保 `open/preClose/lastPrice/amount/sourceTs` 口径完整。

## 总体架构

```text
python-bridge
  └─ mootdx quotes()
       ↓ WebSocket full_state / quote_patch

网页板异动雷达
  ├─ webSocketService 接收 quote_patch
  ├─ OpeningAuctionStateStore 保存 09:25 基线
  ├─ OpeningWeakToStrongDetector 计算弱转强
  ├─ HotStockEventMonitorService 展示事件
  ├─ HotStockEventSpeechService 本地语音
  └─ 上报 proxy-server 本地信号缓存

YiDongJingLing.exe
  ├─ TdxBridgeClient 接收 QuoteSnapshot
  ├─ OpeningAuctionStateStore 保存 09:25 基线
  ├─ OpeningWeakToStrongDetector 计算弱转强
  ├─ L1EventEngine / EventDeduper 统一事件去重
  ├─ VoiceWorker 语音播报
  ├─ MainForm 高亮显示
  └─ 上报 proxy-server 本地信号缓存

proxy-server
  ├─ POST /api/opening-signals
  ├─ GET /api/opening-signals/today
  └─ tradingDate + code + signalType 去重

Dragon Board 主界面
  ├─ 读取今日 opening signals
  └─ DataTable.vue 行情主表展示“竞价弱转强”徽标
```

V3 第一版不再把 Dragon Board 主界面作为额外项。桌面版、网页板和主行情表都要落地，但检测逻辑允许 TS 与 C# 各自独立实现；跨端共享通过统一信号合同和代理本地缓存完成。

## 共享信号合同

信号类型固定为：

```text
signalType = opening_weak_to_strong
displayName = 竞价弱转强
dedupeKey = tradingDate + code + signalType
```

字段：

| 字段 | 含义 |
|------|------|
| `code` / `name` | 股票代码和名称 |
| `tradingDate` | 交易日 |
| `auctionFinalPrice` / `auctionPct` | `09:25` 最后可见竞价价格和涨幅 |
| `officialOpen` / `officialOpenPct` | 官方日线开盘价和涨幅 |
| `firstWindowPrice` / `firstWindowPct` | `09:30-09:35` 首次满足条件的观察价和涨幅 |
| `jumpPctPoint` | `firstWindowPct - auctionPct` |
| `amount` / `amountDelta` | 当前成交额和相对竞价的新增成交额 |
| `limitDistancePct` | 距涨停价百分比 |
| `triggerAt` | 信号触发时间 |
| `source` | `web`、`desktop` 或后续其它来源 |
| `variant` | 弱转强子形态，例如 `auction_gap_reversal`、`low_open_red_reversal`、`previous_day_divergence_repair` |
| `score` / `confidence` | 0-100 评分和 `watch`、`strong`、`critical` 分层 |
| `factors` | 命中因子明细，例如跳空、放量、承接、逼近涨停、前日分歧 |
| `riskFlags` | 风险扣分，例如无量高开、开盘回落、流动性不足、上下文缺失 |
| `baselineQuality` | `good`、`degraded`、`missing`，用于说明 `09:25` 基线质量 |
| `previousWeakScore` / `previousWeakSignals` / `previousWeakSource` | 前日弱势上下文；V4 已支持桌面端从 `TDX自选股` 候选池注入 `tdx_block` 上下文 |
| `auctionCapturedAt` / `bridgeTs` | bridge 捕获/广播时间，不宣称为交易所时间 |
| `auctionSampleCount` | 竞价基线窗口内有效样本数 |
| `quoteAgeMs` / `latencyMs` | 报价年龄和端到端延迟估计 |
| `ruleVersion` / `configHash` | 规则版本和参数哈希，便于复盘 |
| `dryRun` | 是否演练信号 |

单位约定：

| 字段族 | 单位 |
|--------|------|
| `*Pct`、`*PctPoint` | 百分数点，例如 `3.54` 表示 `+3.54%`，不是 `0.0354` |
| `amount`、`amountDelta`、封单额 | 元 |
| `volume` | 股；若上游是手，进入合同前统一换算 |
| `capturedAt`、`bridgeTs`、`triggerAt` | ISO 时间或 epoch ms，统一按北京时间展示 |

`factors` 和 `riskFlags` 不只保存名称，还应保存原始值、阈值、得分贡献和扣分原因，例如：

```text
factor: { key: "auctionGap", value: 4.98, threshold: 3.0, score: 32 }
riskFlag: { key: "auction_amount_missing", severity: "medium", penalty: -8 }
```

## 数据采样策略

### 强制采样门禁

子 Agent 评审指出：现有 `python-bridge` 会做差分广播，若某只股票价格和金额在 `09:24:50-09:25:10` 没变化，客户端可能收不到 `quote_patch`，从而无法证明该股票在 `09:25` 被采到。V3 实施前必须补强采样闭环。

第一版推荐方案：

1. 在 `python-bridge` 增加开盘采样窗口的强制快照广播或等价机制，窗口内即使字段不变，也要让客户端知道每只订阅股票最近一次实际 fetch 结果。
2. 如果暂不改 bridge 主循环，则客户端必须有 timer 主动从 `webSocketService.getQuotesBatch()` / 桌面最新缓存读取，并且 quote 中必须有可证明的新鲜度字段；但这条路径只有在 bridge 暴露 `capturedAt/bridgeTs` 后才算合格。
3. `09:25` 基线验收必须看每只股票的 `capturedAt` 覆盖率，而不是只看是否最终命中。

强制采样需要记录：

| 字段 | 含义 |
|------|------|
| `requestedCount` | 本轮请求/订阅股票数 |
| `receivedCount` | bridge 实际返回股票数 |
| `capturedCount` | 成功写入有效竞价基线数量 |
| `staleCount` | 报价陈旧或时间不可信数量 |
| `elapsedMs` | 一轮采样耗时 |
| `slowBatches` / `truncatedBatches` | bridge 批次异常指标 |
| `capturedAt` / `bridgeTs` | bridge 捕获或广播时间，不宣称为交易所时间 |
| `quoteAgeMs` | 客户端收到时的报价年龄估计 |

若 `09:25` 窗口覆盖率低于阈值，今日 `opening_weak_to_strong` 默认禁用或降级为 dry-run 记录，不触发强提醒。

### 采样窗口

| 窗口 | 行为 | 目的 |
|------|------|------|
| `09:20:00-09:24:49` | 建立基础行情、订阅监控池 | 确认桥在线，避免 09:25 才启动 |
| `09:24:50-09:25:10` | 高频记录最后可见竞价价格 | 得到 `auctionFinalPrice` |
| `09:25:10-09:29:59` | 保持订阅，不触发连续竞价异动 | 等待正式开盘 |
| `09:30:00-09:35:00` | 计算弱转强并触发信号 | 捕捉目标盘口 |
| `09:35:01` 之后 | 不再新增弱转强信号 | 防止把普通盘中拉升误报为竞价信号 |

增强采样：

| 窗口 | 行为 | 第一版处理 |
|------|------|------------|
| `09:20:00-09:25:00` | 记录价格抬升序列和成交额变化 | V4 已作为 `auction_late_lift` 与量价背离降级的判断依据 |
| `09:30:00-09:31:00` | 记录最早连续竞价承接，计算是否快速跌回开盘价/昨收 | 作为 `followThrough` 和 `riskFlags` |
| `09:31:00-09:35:00` | 记录是否继续上攻、逼近涨停或触板 | 用于强信号升级和复盘 |

### 股票池

优先级从稳到激进：

1. 用户手动 `.blk` 强势池。
2. 八平台热榜合并池。
3. 昨日连板、涨停、强趋势候选池，后续可接 Dragon Board 现有热榜/题材数据。
4. 全市场扫描默认关闭，后续作为独立性能优化项。

V4 已把桌面端 `TDX自选股` 接入为前日弱势上下文：当股票池来源为 `TDX自选股` 时，已加载 `.blk` 候选股会在 C# 检测输入中带上 `previousWeakScore = 30`、`previousWeakSignals = ["tdx_block_candidate"]`、`previousWeakSource = "tdx_block"`。该分数只表示人工候选池证据，不等同于真实炸板/烂板；八平台热榜不会自动写入该上下文。

不建议第一版全市场高频扫，因为当前 `python-bridge` 是分批 `quotes(symbol=batch)`，全市场会带来延迟、截断和节点压力。用户真正关心的是早盘可操作性，候选池高质量比全市场覆盖更重要。

网页端订阅约束：不要在异动雷达里直接抢占 `webSocketService.setHotPool()`。弱转强候选池必须通过统一订阅 owner 合并，或由 `RealtimeQuoteCoordinator/DataLoaderFacade` 合并主行情池、热榜池和弱转强候选池后统一下发，避免打开异动雷达覆盖主行情订阅。

## 信号定义

### 基础字段

```text
auctionPct = (auctionFinalPrice - preClose) / preClose * 100
officialOpenPct = (officialOpen - preClose) / preClose * 100
firstWindowPct = (firstOpenWindowPrice - preClose) / preClose * 100
jumpPctPoint = firstWindowPct - auctionPct
officialOpenJumpPctPoint = officialOpenPct - auctionPct
limitDistancePct = (limitUpPrice - lastPrice) / limitUpPrice * 100
amountDelta = currentAmount - auctionAmount
followThroughPctPoint = currentPct - firstWindowPct
```

字段降级规则：

| 情况 | 处理 |
|------|------|
| 当前价来自 `last_close` fallback 或无法证明是当前价 | 不允许作为 `auctionFinalPrice`，基线标记 `missing` |
| `preClose <= 0`、`open < 0`、`amount < 0`、NaN | 不触发，返回结构化 `invalidReason` |
| `auctionAmount <= 0` 或 `currentAmount < auctionAmount` | 不计算 `amountDelta`，增加 `auction_amount_missing` 或 `amount_regressed` 风险标记 |
| `sourceTs` 缺失或明显滞后 | 使用 `capturedAt/bridgeTs` 判断窗口，并标记 `quote_time_untrusted` |
| 同股乱序 quote | 不回退已锁定的有效基线，不用旧 quote 覆盖新 quote |

### 模式族

| variant | 形态 | 第一版可用字段 | 建议门槛 |
|---------|------|----------------|----------|
| `auction_gap_reversal` | 竞价尾价偏弱，`09:30` 后明显跳空上移。`002552` 属于这一类。 | `auctionPct`、`firstWindowPct`、`jumpPctPoint`、`amountDelta`、`officialOpen` | `auctionPct <= 0.5`、`jumpPctPoint >= 3.0`、`firstWindowPct >= 1.5`、放量门槛通过 |
| `low_open_red_reversal` | `09:25` 或官方开盘仍低开/平开，`09:30-09:35` 快速翻红并放量承接。 | `auctionPct`、`officialOpenPct`、`firstWindowPct`、`followThroughPctPoint`、`amountDelta` | `auctionPct <= 0` 或 `officialOpenPct <= 0.5`，`firstWindowPct >= 1.0`，`jumpPctPoint >= 1.5` |
| `previous_day_divergence_repair` | 前一日分歧弱，次日竞价/开盘超预期修复。 | V1 可记录 `contextMissing`；后续接昨日烂板、炸板、长上影、尾盘弱等数据 | 第一版不作为硬命中，只作为增强因子或人工复盘字段 |
| `strong_open_board_attempt` | 有弱转强前置条件的开盘抢筹冲板。 | `firstWindowPct`、`limitDistancePct`、`amountDelta`、`followThroughPctPoint`、弱势前置因子 | `firstWindowPct >= 3.0`，`limitDistancePct <= 2.0` 或触及涨停，放量门槛通过，且至少满足一个弱转强前置条件 |
| `auction_late_lift` | `09:20` 后竞价价格持续抬升，`09:24-09:25` 临门抬价且成交额同步放大。 | `09:20-09:25` 连续采样序列、`amountDelta`、`lateAmountDelta` | V4 已实现；可直接作为强信号模式 |

`strong_open_board_attempt` 的弱转强前置条件至少满足一项：

```text
auctionPct <= 0.5
或 officialOpenPct <= 0.5
或 previousWeakScore >= previousWeakScoreMin，默认 30
或 09:20-09:25 后段出现从弱到强的 auction_late_lift 序列
```

若没有弱势前置，只能记录为普通“开盘冲板/逼近涨停”候选，不得以“竞价弱转强”强播；最多作为 `watch` 级别人工观察。

### 硬门槛

所有子形态都必须满足：

```text
preClose > 0
auctionFinalPrice > 0
09:25 基线时间在 09:24:50-09:25:10
当前时间在 09:30:00-09:35:00
openingAmountDelta >= 2000 万，或当前 amount >= 3000 万，或满足相对量能增强条件
lastPrice >= max(preClose, officialOpen * 0.995)
```

解释：

- `lastPrice >= max(preClose, officialOpen * 0.995)` 是最低承接门槛，避免高开一跳后快速回落仍被误判。
- 不要求每种弱转强都满足 `jumpPctPoint >= 3.0`，否则会漏掉“低开快速翻红”和“前日分歧次日修复”。
- `auction_gap_reversal` 仍使用 `jumpPctPoint >= 3.0`，保持对宝鼎科技样例的敏感度。
- 若触发前后 15-30 秒内跌回昨收或明显跌破官方开盘价，标记 `gap_fade` 并降为 `watch` 或不触发强提醒。

### 评分模型

第一版建议用简单可解释评分，不上复杂模型：

| 因子 | 加分/扣分 | 说明 |
|------|-----------|------|
| `auctionGap` | `0-35` | `jumpPctPoint` 越大越高，`auction_gap_reversal` 主因子 |
| `openingStrength` | `0-20` | `firstWindowPct`、距涨停、是否触及涨停 |
| `volumeConfirm` | `0-20` | 当前成交额和 `amountDelta` |
| `followThrough` | `0-15` | 触发后继续上攻或站稳开盘价 |
| `contextBonus` | `0-10` | 昨日分歧、热榜/题材/龙头地位，第一版没有数据时为 0 |
| `riskPenalty` | `0 到 -30` | 无量、开盘回落、流动性不足、缺上下文 |

分层：

| 分数 | confidence | 行为 |
|------|------------|------|
| `>= 80` | `critical` | 强信号，语音播报，主表醒目高亮 |
| `65-79` | `strong` | 语音播报或按强信号策略播报 |
| `50-64` | `watch` | 入列表和主表徽标，但默认不抢语音 |
| `< 50` | 不触发 | 仅内部调试可见 |

语音规则：

- `watch` 只入列表、导出和主表弱徽标，默认不播报。
- `strong` / `critical` 才进入强提醒候选。
- dry-run 信号不语音、不飞书、不强高亮。
- 两端同时打开时，以 proxy 返回的 `voiceOwner` 为准，默认 `desktop` 优先。

### 强信号加分

满足任一项时把严重级别提升为 `Critical`：

```text
limitDistancePct <= 1.0
或 09:30-09:35 内触及涨停
或 jumpPctPoint >= 5.0
或 09:30 后 60 秒内涨幅继续扩大 >= 2.0 个百分点
```

### 过滤条件

```text
缺失 preClose / auctionFinalPrice / lastPrice 时不触发
非 A 股代码不触发
ST、退市股按设置过滤
09:35 后不触发
同一股票每天只触发一次 OpeningWeakToStrong
成交额太小默认不触发，避免低流动性噪声
```

风险标记不一定阻止触发，但会降低分层和语音强度：

| riskFlag | 触发条件 |
|----------|----------|
| `thin_liquidity` | 当前成交额和开盘增量都偏低 |
| `no_volume_confirmation` | 价格满足但成交额增量不足 |
| `price_lift_without_volume` | `09:20` 后价格抬升但成交额未同步放大，降为 `watch` |
| `volume_without_price_lift` | `09:20` 后成交额放大但价格压不动，降为 `watch` |
| `auction_late_high_retreated` | `09:20` 后高位回落且 `09:25` 未收回，不算 `auction_late_lift`，降为 `watch` |
| `gap_fade` | 触发前后快速跌回官方开盘价或昨收附近 |
| `overextended_open` | 高开过大且未继续上攻，容易变成兑现 |
| `context_missing` | 没有昨日分歧、板块强度或热榜上下文，只能按盘口形态判断 |
| `auction_amount_missing` | `auctionAmount` 缺失或不可用，只能使用当前成交额兜底 |
| `amount_regressed` | `currentAmount < auctionAmount`，金额口径异常 |
| `quote_time_untrusted` | `sourceTs` 缺失、乱序或明显滞后 |

### 002552 样例计算

```text
preClose = 36.20
auctionFinalPrice = 35.68
firstOpenWindowPrice = 37.48

auctionPct = -1.44%
firstWindowPct = +3.54%
jumpPctPoint = 4.98
```

默认规则下应触发“竞价弱转强”。如果后续 `09:33` 触及 `39.82` 涨停，则记录冲板确认。

## 桌面版纯 C# 改动

### 1. 新增开盘状态存储

建议新增：

```text
tools/YiDongJingLing/MarketData/OpeningAuctionState.cs
tools/YiDongJingLing/MarketData/OpeningAuctionStateStore.cs
```

职责：

- 保存每只股票当天最后一次 `09:24:50-09:25:10` 的有效报价。
- 保存 `auctionFinalPrice`、`auctionFinalPct`、`auctionAmount`、`auctionVolume`、`capturedAt`。
- 保存 `firstOpenWindowPrice`、`firstOpenWindowPct`、`firstOpenWindowAt`。
- 每个交易日自动清理旧状态。

只保存当前交易日内存状态即可。第一版不必引入数据库；需要复盘时再导出到 CSV。

### 2. 新增检测器

建议新增：

```text
tools/YiDongJingLing/Events/OpeningWeakToStrongDetector.cs
```

输入：

```text
QuoteSnapshot quote
OpeningAuctionState state
IReadOnlyList<QuoteSnapshot> history
OpeningWeakToStrongRules rules
```

输出：

```text
EventRecord? OpeningWeakToStrong
```

这样可以避免把 `L1EventEngine` 继续变厚。`L1EventEngine` 负责常规连续竞价异动，新检测器只处理开盘弱转强这个特殊时间窗口。

检测器输出的 `EventRecord` 详情必须携带 `variant`、`score`、`confidence`、`factors`、`riskFlags`。主表可以只显示“竞价弱转强”，但日志、导出和复盘必须能区分“跳空上移”“低开翻红”“冲板抢筹”等子形态。

### 3. 事件类型

在 `L1EventType` 增加：

```text
OpeningWeakToStrong
```

建议显示名：

```text
竞价弱转强
```

建议 reason：

```text
09:25 -1.44%，09:30 +3.54%，跳空 4.98pct，成交额 8140万，距涨停 5.88%
```

语音文本可读为：

```text
宝鼎科技，竞价弱转强，跳空四点九八个百分点，冲板关注
```

### 4. 设置项

在 `AppSettings` 和 `L1EventRules` 增加：

| 设置 | 默认值 | 说明 |
|------|--------|------|
| `OpeningWeakToStrongEnabled` | `true` | 是否启用 |
| `AuctionWeakMaxPct` | `0.5` | `09:25` 竞价涨幅上限 |
| `OpeningJumpMinPctPoint` | `3.0` | `09:25 → 09:30` 最小跳空百分点 |
| `OpeningFirstMinPct` | `1.5` | `09:30` 后首次价格相对昨收最低涨幅 |
| `OpeningDetectEndMinute` | `09:35` | 最晚检测时间 |
| `OpeningMinAmountWan` | `3000` | 当前最小成交额 |
| `OpeningMinAmountDeltaWan` | `2000` | 开盘后相对竞价最小新增成交额 |
| `OpeningCriticalJumpPctPoint` | `5.0` | 强信号跳空阈值 |
| `OpeningNearLimitDistancePct` | `1.0` | 距涨停多少以内升级强信号 |
| `OpeningScoreStrong` | `65` | 强信号最低分 |
| `OpeningScoreCritical` | `80` | 顶级强信号最低分 |

第一版可先把这些放在 `L1EventRules`，设置页只暴露 4 个核心项：竞价弱上限、跳空最小百分点、最小成交额、强信号分数线。其余保留默认值，避免设置页过载。

### 5. MainForm 接入点

当前 `MainForm.HandleQuotes` 在非连续竞价时段会 `Prime` 并跳过事件。需要调整为：

1. `09:24:50-09:25:10`：虽然不是连续竞价，也要把报价交给 `OpeningAuctionStateStore`。
2. `09:30:00-09:35:00`：在常规 `L1EventEngine.Evaluate` 前后调用 `OpeningWeakToStrongDetector`。
3. 事件进入现有 `_deduper.Filter`、`AddEventRow`、`EventVoicePolicy` 和 `SyncMessagesAsync`，不要新建第二套播报链路。

伪代码：

```csharp
var openingEvents = new List<EventRecord>();

if (TradingSession.IsOpeningAuctionCaptureWindow(normalizedQuote.SourceTime))
{
    _openingStore.CaptureAuctionQuote(normalizedQuote);
    _eventEngine.Prime(normalizedQuote);
    continue;
}

if (TradingSession.IsOpeningWeakToStrongWindow(normalizedQuote.SourceTime))
{
    var openingEvent = _openingDetector.Evaluate(normalizedQuote, _openingStore.Get(normalizedQuote.Code), history);
    if (openingEvent is not null) openingEvents.Add(openingEvent);
}

allEvents.AddRange(openingEvents);
allEvents.AddRange(_eventEngine.Evaluate(normalizedQuote, previous, history));
```

### 6. TradingSession 扩展

在 `TradingSession` 增加：

```text
IsOpeningAuctionCaptureWindow(timestamp)
IsOpeningWeakToStrongWindow(timestamp)
GetTradingDate(timestamp)
```

避免把时间判断散落在 UI 或检测器里。

## 网页板异动雷达改动

网页板需要独立捕捉同一信号，不依赖 `YiDongJingLing.exe` 是否启动。实现上复用 Dragon Board 已有 WebSocket 实时报价、异动雷达列表和本地语音接口。

现状提醒：当前异动雷达列表已有的 `fetchEvents()` 主体是选股通/同花顺 HTTP 事件轮询，它适合展示普通异动事件，不是本信号的盘口检测入口。实现时不要只扩展 `XuangubaoAbnormalEventFeed`、`ThsLimitUpEventFeed` 或它们的组合 feed；必须新增基于 `webSocketService` 的实时 L1 检测路径。

关键约束：`opening_weak_to_strong` 不接入 `XuangubaoAbnormalEventFeed` 或 `ThsLimitUpEventFeed` 的检测输入。这两个 feed 仍可作为普通异动事件列表来源，但它们没有 `09:25` 基线，不能判断竞价弱转强。

建议新增：

```text
src/services/hotlist/openingWeakToStrongTypes.ts
src/services/hotlist/OpeningAuctionStateStore.ts
src/services/hotlist/OpeningWeakToStrongDetector.ts
src/services/hotlist/OpeningRealtimeEventBuffer.ts
```

建议改动：

```text
src/services/hotlist/HotStockEventMonitorService.ts
src/services/hotlist/hotStockEventTypes.ts
src/services/hotlist/HotStockEventSpeechService.ts
src/components/panels/HotStockEventMonitorPanel.vue
```

接入策略：

1. 监听 `webSocketService` 的 `FULL_STATE` 和 `QUOTE_PATCH`。
2. 弱转强候选池不得直接覆盖 `webSocketService.setHotPool(...)`，必须通过统一订阅合并层加入主行情订阅池。
3. 检测器直接读取 WebSocket `QuotePatch`，不要从选股通 feed 或不完整的 DataLayer 投影反推 `open/preClose`。
4. `09:24:50-09:25:10` 写入浏览器内存中的 `OpeningAuctionStateStore`。
5. `09:30:00-09:35:00` 调用 TS 版 `OpeningWeakToStrongDetector`。
6. 命中后转换为现有 `HotStockEvent`，类型显示“竞价弱转强”。
7. 事件进入现有异动雷达去重、列表和语音服务；语音继续走 `/api/local-voice/speak`。
8. 同步上报 `proxy-server` 本地信号缓存，按返回的 `voiceOwner` 决定是否播报，供 Dragon Board 主表消费。

网页端事件合并点必须明确：

```text
httpFeedEvents + openingRealtimeEvents -> dedupeById -> HotStockEventMonitorService state
```

避免 `HotStockEventMonitorService.refresh()` 下一次 HTTP 刷新把实时 opening 事件覆盖掉。若现有 `HotStockAbnormalEventType` 是数字联合类型，第一版可新增本地合成类型，例如 `12000`，同时在事件 raw 字段保留 `signalType = opening_weak_to_strong`。

网页板只做 L1 口径，不补做真 L2、十档、逐笔或撤单队列解释。

## 本地代理信号缓存

`proxy-server` 新增轻量本地事件 API，不进入 QuantBoard，也不承担回测存储职责。

建议 API：

```text
POST /api/opening-signals
GET /api/opening-signals/today
```

职责：

- 接收网页板和桌面版上报的 `opening_weak_to_strong` 信号。
- 按 `tradingDate + code + signalType` 去重。
- 返回今日信号列表给 Dragon Board 主表。
- 可复用内存缓存；需要跨刷新保留时再加本地 JSON 文件，第一版不必写数据库。

`proxy-server` 不做行情采样，不计算 `auctionFinalPrice`，不替代网页板或桌面版检测器。它只负责保存已经生成的信号、跨端去重、语音仲裁和给主表展示同步。

### 合并和语音仲裁

`POST /api/opening-signals` 必须返回：

```text
accepted
isNew
dedupeAction = created | merged | ignored | upgraded
voiceOwner = desktop | web | none
canonicalSignal
sources
```

缓存结构不要简单 last-write-wins：

| 字段 | 说明 |
|------|------|
| `canonicalSignal` | 主表和通知使用的代表信号 |
| `reportsBySource` | `web`、`desktop` 等各端原始上报 |
| `sources` | 已上报来源数组 |
| `firstTriggerAt` | 最早触发时间 |
| `lastReportedAt` | 最近上报时间 |
| `voiceOwner` | 本次允许播报的一端，默认桌面优先 |

代表信号选择顺序：

```text
confidence 高者优先
score 高者优先
sourcePriority: desktop > web
triggerAt 早者优先
```

示例：web 先上报 `watch`，desktop 后上报 `critical`，主表应升级为 `critical`，但保留 web 原始 report。若两端同时打开，默认只允许一个端播报；网页端只有在 proxy 返回 `voiceOwner=web` 时播报，桌面端同理。

桌面版上报 opening signal 不得绑定现有飞书同步开关。即使 `SyncMessages=false`，只要信号通过本地去重，就要尝试 POST `/api/opening-signals`；失败只写诊断，不影响本地列表和语音。

不建议把该能力塞入 `python-bridge` 主循环。行情桥继续负责行情，信号缓存交给代理，职责更清楚。

## python-bridge 侧策略

第一版不把 `python-bridge/main.py` 改成策略引擎，也不在 bridge 内计算弱转强；但允许做最小行情元数据增强，以满足 `09:25` 强制采样门禁：

1. 在 `09:24:50-09:25:10` 对当前订阅池强制广播 snapshot/patch，即使价格和金额未变化。
2. 在 quote payload 中暴露 `capturedAt/bridgeTs`、本轮 `elapsedMs` 和批次异常指标。
3. 可选暴露 `lastPriceSource`，避免把 `last_close` fallback 误当成有效当前价。

但需要运行方式上保证：

1. `09:20` 前启动 `YiDongJingLing.exe`。
2. 已加载监控池并订阅到 bridge。
3. `TDX_POLL_INTERVAL_MS` 保持当前低间隔。
4. 如果用户监控池超过 300 只，界面提示“开盘弱转强延迟风险”。

如果不希望碰 bridge 主循环，则必须新增一个独立轻量 Python scanner；但 scanner 仍只负责采样和广播基线，不负责策略判断：

```text
python-bridge/opening_scanner.py
```

该 scanner 只在早盘窗口高频拉取候选池，并通过本地 WebSocket 或文件把 `auctionFinalPrice/capturedAt/coverage` 推给网页板和 `YiDongJingLing`。如果 V3 第一版选择 scanner 路线，它就是强制采样主链的一部分，而不是后续可选优化。

## 异动精灵 UI 方案

视觉方向沿用 V2 金融终端风格，不做营销式大卡片。

### 主表格

新增事件行样式：

| 项目 | 方案 |
|------|------|
| 类型 | `竞价弱转强` |
| 行背景 | 深红棕或金红强调，比普通快速拉升更醒目但不压过封板 |
| 文字色 | A 股红涨语义 |
| 详情 | 展示 `09:25`、`09:30`、跳空百分点、成交额、距涨停 |
| 排序 | 在同批事件中优先级低于“封涨停板”，高于“快速拉升” |

详情列建议显示短句：

```text
跳空上移｜分数 82｜09:25 -1.44% → 09:30 +3.54%，放量确认，距涨停 5.88%
```

若为观察级信号：

```text
低开翻红｜分数 58｜放量不足，默认仅入列表
```

### 顶部摘要

`_eventsSummaryLabel` 在 `09:30-09:35` 出现信号时显示：

```text
开盘弱转强 3 只：宝鼎科技、某某股份、某某科技
```

### 状态栏

增加或复用状态展示：

```text
开盘扫描 已锁定 128/132 只竞价基线
开盘扫描 09:30-09:35 捕获 3 只
```

如果未在 `09:25` 前启动：

```text
开盘扫描 缺少09:25基线，今日弱转强信号不可用
```

### 语音策略

`OpeningWeakToStrong` 按 `confidence` 和 proxy 语音仲裁决定是否播报：

- `watch` 默认只入列表，不播报。
- `strong` / `critical` 在 `VoiceMode.StrongOnly` 下可播报。
- 具体由 `/api/opening-signals` 返回的 `voiceOwner` 决定当前端是否播报。
- dry-run 模式不播报。
- 同股同日只播报一次。
- 多只同时触发时复用现有批量播报，上限 3 条。

## Dragon Board 主界面信号方案

V3 第一版必须把主行情表信号一并纳入。主表不自己推导弱转强，只消费 `proxy-server` 今日信号缓存，并在股票行做醒目标识。

这里的 HTTP 轮询只用于展示“已经由网页板或桌面版生成的信号”，不是行情轮询，也不参与 `09:25` 基线采样。

主表请求逻辑应放在轻量 service/store 中，例如：

```text
src/services/hotlist/OpeningSignalClient.ts
```

`DataTable.vue` 只消费今日信号状态并展示徽标，不直接承担 API 请求、缓存、错误重试和轮询生命周期。

### 数据通道候选

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 扩展 `python-bridge` WebSocket `opening_signal` | 前端已有 WebSocket | 会把行情桥变成信号中心，职责变重 | 不选第一版 |
| `YiDongJingLing` 写本地 JSON，前端轮询 | 实现简单 | 网页板触发的信号不好统一，跨端去重弱 | 备选 |
| 代理 `proxy-server` 增加本地事件 API | 网页板、桌面版、主表都能复用，去重集中 | 需要 Node 侧新增接口 | 推荐 |

推荐使用 `proxy-server` 本地事件 API：

```text
POST /api/opening-signals
GET /api/opening-signals/today
```

网页板和 `YiDongJingLing` 触发事件后都同步到代理；Dragon Board 主界面轮询今日信号后给股票行加徽标。这个轮询读取的是本地信号缓存，不是选股通/同花顺行情源。

### 主界面展示

在行情列表股票名称旁或异动列显示：

```text
竞价弱转强
跳空 +4.98pct
```

样式要求：

- 小型徽标，不做大卡片。
- 红金高亮，5-10 秒闪烁或短暂描边。
- 置顶或过滤器可后续添加，第一版只做醒目标识。

## 复盘和日志

第一版建议 `YiDongJingLing` 导出记录时追加弱转强字段：

```text
variant
score
confidence
factors
riskFlags
auctionFinalPrice
auctionPct
officialOpen
officialOpenPct
firstOpenWindowPrice
firstWindowPct
jumpPctPoint
openingAmountDelta
limitDistancePct
triggerAt
limitTouchedBefore0935
baselineCapturedAt
sourceTs
receivedAt
latencyMs
quoteSource
invalidReason
ruleVersion
configHash
dryRun
proxyPostStatus
dedupeAction
```

这样可以在 20-60 个交易日后验证：

- 命中数量。
- 09:35 前冲板率。
- 当日封板率。
- 炸板率。
- 次日溢价。

状态栏至少展示：

```text
bridge 在线/离线
proxy 在线/离线
订阅数
09:25 基线覆盖率
最近 quote 延迟
dry-run/播报模式
今日 opening signal 数
```

## Dry-run 演练模式

为避免早盘首次上线时误报、重复播报或干扰交易，V3 必须支持“开盘扫描演练模式”：

| 行为 | dry-run |
|------|---------|
| 锁定 `09:25` 基线 | 是 |
| 计算候选和分数 | 是 |
| 写日志/导出 | 是 |
| 上报 proxy | 可选，但必须标记 `dryRun=true` |
| 主表强高亮 | 否 |
| 语音播报 | 否 |
| 飞书同步 | 否 |

主表默认不展示 dry-run 信号；若需要展示，应使用弱样式并明确标记“演练”。

## 共享测试夹具

TS 和 C# 检测器必须读取同一份机器可读 golden case，防止口径漂移。建议路径：

```text
docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json
```

每个 case 至少包含：

```text
caseId
description
rulesVersion
rules
quotes[]
expected.triggered
expected.variant
expected.confidence
expected.scoreRange
expected.riskFlags
expected.invalidReason
```

fixture 必须覆盖：

- `002552` 跳空上移命中。
- 低开快速翻红命中。
- 有弱势前置的冲板抢筹命中。
- 无弱势前置的普通开盘冲板不得强播。
- 无量高开。
- 开盘一跳后 30 秒内跌回开盘/昨收。
- 低流动性小成交额跳价。
- 过度高开但不继续上攻。
- 缺少 `09:25` 基线。
- `sourceTs/bridgeTs` 陈旧或乱序。
- `amountDelta < 0` 或金额单位异常。
- 09:35 后不新增信号。

## 实施阶段

### Phase 1：共享口径和事件合同

改动：

- 固化 `opening_weak_to_strong` 事件合同。
- 明确弱转强是模式族，不是单一 `09:25 → 09:30` 跳空公式。
- 信号增加 `variant`、`score`、`confidence`、`factors`、`riskFlags`、`baselineQuality`、`ruleVersion`、`configHash`、`dryRun` 字段。
- 准备 TS 与 C# 共用的 `opening-weak-to-strong-cases.json` fixture。
- 明确硬门槛、评分模型、风险扣分和强信号升级规则。
- 明确 `*Pct` 为百分数点，金额为元，成交量为股。

验证：

- 002552 样例命中。
- 低开快速翻红样例可命中 `low_open_red_reversal`。
- 有弱势前置的冲板抢筹样例可命中 `strong_open_board_attempt`。
- 无弱势前置的普通开盘冲板不得强播。
- `auctionPct > 0.5` 不命中。
- `auction_gap_reversal` 中 `jumpPctPoint < 3` 不命中。
- 缺少 `09:25` 基线不命中。
- `09:35` 后不命中。
- 同股同日只触发一次。

### Phase 2：桌面版纯 C# 检测和语音

改动：

- `TradingSession` 增加开盘窗口判断。
- 新增 `OpeningAuctionStateStore`。
- 新增 `OpeningWeakToStrongDetector`。
- `L1EventType` 增加 `OpeningWeakToStrong`。
- `EventDeduper` 和 `EventVoicePolicy` 增加优先级和强信号判断。
- `MainForm.HandleQuotes` 接入开盘状态存储和检测器。
- 设置页增加“竞价弱转强”事件开关。
- 表格行样式和摘要文字支持该事件。
- 语音播报 reason 保持简短。

验证：

```powershell
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
```

手工验证：

- 用测试行情注入或 mock WebSocket 模拟 `09:25` 和 `09:30`。
- 确认主表出现“竞价弱转强”。
- 确认 `strong/critical` 且 `voiceOwner=desktop` 时才播报，`watch` 和 dry-run 不播报。

### Phase 3：网页板异动雷达检测

改动：

- `src/services/hotlist/**` 增加 TS 版开盘状态存储和检测器。
- `opening_weak_to_strong` 主检测源使用 `webSocketService` / `python-bridge`，不使用选股通/同花顺 HTTP 事件 feed。
- 保留 `XuangubaoAbnormalEventFeed`、`ThsLimitUpEventFeed` 作为普通盘中异动事件源，但不得把它们的数据补推为 `auctionFinalPrice`。
- `HotStockEventMonitorService` 接收本地 L1 检测事件。
- `HotStockEventMonitorPanel.vue` 展示“竞价弱转强”。
- `HotStockEventMonitorPanel.vue` 文案从单一“选股通数据源”调整为“实时行情 + 异动事件源”。
- `HotStockEventSpeechService` 复用本地语音接口。

验证：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

测试用例与 C# 保持同口径。

额外验收：

- mock `XuangubaoAbnormalEventFeed` / `ThsLimitUpEventFeed` 返回“逼近涨停/封板”事件时，不得生成 `opening_weak_to_strong`。
- 只有 WebSocket 强制采样先形成有效 `09:25` 基线，再在 `09:30-09:35` 出现跳空，才允许命中。

### Phase 4：本地代理信号缓存

改动：

- `proxy-server` 增加 `POST /api/opening-signals`。
- `proxy-server` 增加 `GET /api/opening-signals/today`。
- 网页板和桌面版命中后上报统一信号。
- API 返回 `accepted/isNew/dedupeAction/voiceOwner/canonicalSignal/sources`。
- 缓存 `canonicalSignal` 与 `reportsBySource`，不做 last-write-wins。
- 新增 `OpeningSignalReporter` 或等价桌面上报路径，不绑定飞书同步开关。

验证：

- Node 路由测试覆盖新增、重复、查询今日信号。
- 两端同时命中只产生一个 canonical signal，默认只允许一个语音 owner。
- web 先报 watch、desktop 后报 critical 时，主表升级为 critical，保留 web report。

### Phase 5：Dragon Board 主界面标识

改动：

- 前端增加今日 opening signal 读取服务或轻量 store，例如 `OpeningSignalClient`。
- `DataTable.vue` 股票名称旁展示“竞价弱转强”徽标。
- 命中后短时行高亮，不改变主表排序和核心列布局。

验证：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
pnpm build
```

有 UI 改动时做浏览器检查，确认桌面和移动宽度不溢出。

### Phase 6：实盘早盘联调

操作：

1. 第一个实盘交易日默认启用 dry-run。
2. `09:20` 前启动 `YiDongJingLing.exe` 和 Dragon Board。
3. 加载 `.blk` 强势池或八平台热榜。
4. 确认状态栏显示行情桥、proxy、监控数量和 dry-run 状态。
5. `09:25` 后确认桌面版和网页板竞价基线锁定数量。
6. `09:30-09:35` 观察捕获结果、异动雷达和主表 dry-run 标记。
7. 盘后导出记录。

分钟级检查表：

| 时间点 | 检查项 |
|--------|--------|
| `09:20` | bridge/proxy 在线，订阅数正确，dry-run/播报模式正确 |
| `09:24:50` | 强制采样开始，记录 requested/received |
| `09:25:10` | 基线覆盖率、staleCount、slowBatches、truncatedBatches |
| `09:29:59` | 不触发连续竞价信号，等待窗口正常 |
| `09:30:00` | 首个连续竞价 quote 延迟 |
| `09:30-09:35` | 首个满足条件到展示/上报/播报耗时 |
| `09:35:01` | 禁止新增 opening signal |

验收：

- 没有崩溃或明显卡顿。
- 监控池 100-300 只时 `09:25` 基线覆盖率大于 95%。
- `09:25` 窗口内有 per-code `capturedAt/bridgeTs` 可证明。
- 信号触发时间不晚于首次满足条件后 2 秒。
- 网页板和桌面版不重复刷屏，默认不重复语音。
- Dragon Board 主表展示与异动雷达事件一致。
- bridge 离线、proxy 离线、只开网页、只开桌面都按文档降级，不静默失败。

离线矩阵：

| 场景 | 检测 | 本地语音 | 主表信号 | 恢复行为 |
|------|------|----------|----------|----------|
| bridge 离线 | 不检测 | 不播报 | 显示行情桥离线 | 恢复后仅未来窗口可用，不补造 `09:25` 基线 |
| proxy 离线 | 本地可检测 | 桌面可按本地策略播报，网页默认不跨端仲裁 | 主表不可同步，显示 proxy 离线 | 恢复后可补报未过期信号，标记 `proxyPostStatus` |
| 只开网页 | 网页可检测 | 按 proxy `voiceOwner=web` 播报 | 可显示 | 桌面后开不补造基线 |
| 只开桌面 | 桌面可检测 | 桌面播报 | proxy 在线时可显示 | 网页后开只消费主表缓存 |

### Phase 7：参数微调和复盘

基于至少 20 个交易日记录调整：

- `AuctionWeakMaxPct`
- `OpeningJumpMinPctPoint`
- `OpeningMinAmountWan`
- `OpeningNearLimitDistancePct`

只根据实盘数据调参，不凭单日样例过拟合。

## 文件改动清单

V3 建议改动：

```text
src/services/hotlist/openingWeakToStrongTypes.ts
src/services/hotlist/OpeningAuctionStateStore.ts
src/services/hotlist/OpeningWeakToStrongDetector.ts
src/services/hotlist/OpeningRealtimeEventBuffer.ts
src/services/hotlist/OpeningSignalClient.ts
src/services/hotlist/HotStockEventMonitorService.ts
src/services/hotlist/hotStockEventTypes.ts
src/services/hotlist/HotStockEventSpeechService.ts
src/components/panels/HotStockEventMonitorPanel.vue
src/components/common/DataTable.vue
proxy-server/routes/openingSignals.js
proxy-server/app.js
proxy-server/openapi.js
proxy-server/__tests__/openingSignals.test.mjs
proxy-server/__tests__/docs.test.mjs
docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json
tools/YiDongJingLing/MarketData/TradingSession.cs
tools/YiDongJingLing/MarketData/OpeningAuctionState.cs
tools/YiDongJingLing/MarketData/OpeningAuctionStateStore.cs
tools/YiDongJingLing/Events/OpeningWeakToStrongDetector.cs
tools/YiDongJingLing/Events/OpeningSignalReporter.cs
tools/YiDongJingLing/Events/EventRecord.cs
tools/YiDongJingLing/Events/EventDeduper.cs
tools/YiDongJingLing/Events/EventVoicePolicy.cs
tools/YiDongJingLing/Events/L1EventRules.cs
tools/YiDongJingLing/Settings/AppSettings.cs
tools/YiDongJingLing/SettingsForm.cs
tools/YiDongJingLing/MainForm.cs
tools/YiDongJingLing.Tests/Program.cs
docs/yidong-jingling/usage.md
docs/yidong-jingling/task_plan.md
docs/yidong-jingling/findings.md
docs/yidong-jingling/progress.md
```

实施前仍需用 `rg` 精确确认调用点，最终以最小可验证改动为准。

## 风险和对策

| 风险 | 对策 |
|------|------|
| `09:25` 工具未启动，缺少基线 | 状态栏明确提示“今日弱转强不可用”，不误报 |
| 监控池过大导致采样延迟 | 默认限制并提示延迟风险，先支持 100-300 只 |
| `mootdx` 在集合竞价阶段返回占位或空值 | 只接受 `preClose > 0`、有效当前价 > 0、`capturedAt/bridgeTs` 在窗口内的数据 |
| `officialOpen` 与第一分钟价格口径不同 | 同时保存两个字段，不混用 |
| 低流动性票跳动误报 | 加成交额和成交增量门槛 |
| 普通快速拉升与弱转强重复播报 | `EventDeduper` 中提高弱转强优先级，同股同批只保留最高优先级 |
| Dragon Board 主界面同步引入复杂度 | 通过代理本地缓存隔离，主表只消费信号，不承载检测逻辑 |

## 最小可交付

第一版完成后，只要满足以下条件即可交付：

1. 用户在 `09:20` 前打开 `YiDongJingLing.exe` 和 Dragon Board，并加载股票池。
2. `09:25` 后桌面版和网页板都能锁定竞价基线。
3. `09:30-09:35` 出现符合条件股票时，桌面版异动列表新增“竞价弱转强”并语音播报。
4. 网页板异动雷达同步显示“竞价弱转强”。
5. Dragon Board 主行情表对命中股票显示醒目标识。
6. 本地代理缓存今日信号并去重，便于后续统计冲板概率。

## 参考资料

官方规则和行情口径：

- 深交所投资者教育：集合竞价成交价确定原则。<https://investor.szse.cn/knowledge/stock/deal/t20200102_573001.html>
- 深交所投资者教育：交易时间、`09:25-09:30` 申报接收边界。<https://www.szse.cn/www/investor/knowledge/stock/deal/t20190626_568129.html>
- 深交所投资者教育：`09:20-09:25` 不接受撤单、集合竞价/连续竞价时间。<https://investor.szse.cn/warning/activities/stockintroduction/t20190513_567105.html>
- 深交所早期开放式集合竞价提示：参考价、匹配量、未匹配量曾通过买卖一/二字段揭示。<https://www.szse.cn/aboutus/trends/news/t20040623_517140.html>
- 上交所投资者教育：交易阶段包含开盘集合竞价、连续竞价、收盘集合竞价。<https://edu.sse.com.cn/best/audio/tjxwc/c/5331843.shtml>

弱转强经验和量化特征参考：

- 淘股吧短线文章：弱转强强调前日弱、次日超预期高开、带量、快速上攻。<https://m.tgb.cn/a/2rH18eikaA2>
- 新浪财经转载短线文章：弱转强关注竞价量能、开盘 5 分钟承接。<https://cj.sina.com.cn/articles/view/6229138373/173491bc500100h1za>
- BigQuant 集合竞价因子字段：隔夜涨跌幅、开盘竞价成交价、竞价成交额、竞价成交量、竞价委托量等可作为后续量化增强。<https://bigquant.pro/data/datasources/cn_stock_factors_auction>
- BigQuant 研报复现：集合竞价成交量占比是日内高频因子，开盘集合竞价反映隔夜信息释放。<https://bigquant.com/wiki/doc/61etdmb4NI>
- 海通量化/新浪财经转载：基于集合竞价分时走势的 A 股 T+0 策略，关注 `09:20-09:25` 持续上行、集合竞价量比、低开/平开约束。<https://finance.sina.cn/2019-07-17/detail-ihytcitm2536959.d.html>
- arXiv 中国市场开盘集合竞价微观结构研究：开盘竞价价格、订单量和订单簿统计特征可量化建模。<https://arxiv.org/abs/0905.0582>
