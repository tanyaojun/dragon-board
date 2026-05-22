# 开盘竞价弱转强三端落地设计

日期：2026-05-22

## 结论

V3 采用“三端同口径、各自可工作”的方案：网页板异动雷达用 TypeScript 监听实时 L1 报价并捕捉信号；桌面版 `YiDongJingLing.exe` 用纯 C# 独立实现同一套口径并负责强提醒；`proxy-server` 提供本地信号缓存和去重接口，Dragon Board 主行情表消费该信号并高亮展示。

这个方案不依赖 QMT L2、不宣称 TDX 真十档，也不把 `09:25` 竞价价寄托给盘后分钟线。核心是实盘在 `09:24:50-09:25:10` 锁定集合竞价最后可见价，在 `09:30:00-09:35:00` 捕捉连续竞价价格大幅上移。

2026-05-22 数据源校正：网页板当前异动雷达的选股通/同花顺 HTTP feed 是事件历史和涨停池结果源，不能作为“竞价弱转强”主检测数据源。网页板 V3 必须改用 `python-bridge` WebSocket 的 `FULL_STATE` / `QUOTE_PATCH` 实时 L1 行情；选股通/同花顺只保留为普通盘中异动辅助线索。

2026-05-22 规则校正：`002552 宝鼎科技` 是“竞价尾价偏弱、开盘跳空上移”的代表样例，但不能把“竞价弱转强”写死成这一种公式。V3 合同把它设计为模式族：同一 `opening_weak_to_strong` 信号下保存 `variant`、`score`、`confidence`、`factors` 和 `riskFlags`，用硬门槛过滤、用评分模型分层。

2026-05-22 子 Agent 交叉评审校正：实现前必须补齐 `09:25` 强制采样、跨端语音仲裁、TS/C# 统一 fixture、dry-run 演练模式、基线质量字段和异常数据验收。仅监听 `QUOTE_PATCH` 不足以证明每只股票在 `09:25` 被采到；proxy 事后去重也不足以阻止网页和桌面重复语音。

## 已确认需求

目标图形不是“固定高开 2%”，而是：

```text
09:25 集合竞价最后价偏弱
09:30-09:35 连续竞价价格快速上移
中间形成明显跳空缺口
```

样例口径以 `002552 宝鼎科技` 为代表：

| 字段 | 值 |
|------|----|
| 昨收 | `36.20` |
| `09:25` 竞价最后价 | `35.68`，`-1.44%` |
| 官方日线开盘 | `36.92`，`+1.99%` |
| 通达信分时第一条观察价 | `37.48`，`+3.54%` |
| 跳空百分点 | `3.54 - (-1.44) = 4.98pct` |

## 方案权衡

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 三端同口径独立检测 + 本地信号缓存 | 网页板和桌面版都能独立工作，Dragon Board 主表能统一展示，单端异常不拖垮另一端 | 需要 TS 和 C# 各实现一份检测逻辑，测试要保证口径一致 | 选择 |
| 桌面端唯一检测，网页和主表只消费桌面信号 | 实现更少，声音链路最直接 | 桌面端未启动时网页板和主表失效，用户体验被单进程绑定 | 不选 |
| Python bridge 作为唯一检测中心 | 检测口径集中，推送天然实时 | 会把 bridge 从行情桥扩成策略引擎，增加早盘主循环风险 | 暂不选 |

## 总体架构

```text
mootdx / python-bridge
  └─ L1 quote_patch / full_state / opening forced snapshot
       ├─ Dragon Board 网页板检测器
       │    ├─ 09:25 竞价基线缓存
       │    ├─ 09:30-09:35 弱转强检测
       │    └─ HotStockEventMonitorService / local voice
       ├─ YiDongJingLing.exe 桌面检测器
       │    ├─ OpeningAuctionStateStore
       │    ├─ OpeningWeakToStrongDetector
       │    ├─ EventDeduper / EventVoicePolicy
       │    └─ MainForm 高亮 + VoiceWorker 播报
       └─ proxy-server 本地信号缓存
            ├─ POST /api/opening-signals
            ├─ GET /api/opening-signals/today
            └─ tradingDate + code + signalType 去重

Dragon Board 主行情表
  └─ DataTable.vue 合并今日信号，显示“竞价弱转强”徽标和行级强调
```

`python-bridge` 只允许做行情采样和元数据增强，不计算 `opening_weak_to_strong`。强制快照的目的只是证明 `09:25` 附近每只订阅股票是否被实际采到。

## 共享信号合同

信号类型固定为：

```text
signalType = opening_weak_to_strong
displayName = 竞价弱转强
dedupeKey = tradingDate + code + signalType
```

核心字段：

| 字段 | 含义 |
|------|------|
| `code` / `name` | 股票代码和名称 |
| `tradingDate` | 交易日 |
| `auctionFinalPrice` / `auctionPct` | `09:25` 最后可见竞价价格和涨幅 |
| `officialOpen` / `officialOpenPct` | 官方日线开盘价和涨幅 |
| `firstWindowPrice` / `firstWindowPct` | `09:30-09:35` 首次满足条件的观察价和涨幅 |
| `jumpPctPoint` | 从 `auctionPct` 到 `firstWindowPct` 的百分点跳空 |
| `amount` / `amountDelta` | 当前成交额和相对竞价的新增成交额 |
| `limitDistancePct` | 距涨停价百分比 |
| `triggerAt` | 信号触发时间 |
| `source` | `web`、`desktop` 或后续其它来源 |
| `variant` | 子形态，例如 `auction_gap_reversal`、`low_open_red_reversal`、`strong_open_board_attempt` |
| `score` / `confidence` | 0-100 评分和 `watch`、`strong`、`critical` 分层 |
| `factors` | 命中因子明细：跳空、放量、承接、逼近涨停、前日分歧等 |
| `riskFlags` | 风险扣分：无量高开、开盘回落、流动性不足、上下文缺失等 |
| `baselineQuality` | `09:25` 基线质量：`good`、`degraded`、`missing` |
| `auctionCapturedAt` / `bridgeTs` | bridge 捕获/广播时间，不宣称交易所时间 |
| `auctionSampleCount` / `quoteAgeMs` | 基线样本数和报价年龄 |
| `ruleVersion` / `configHash` | 规则版本和参数哈希 |
| `dryRun` | 是否演练信号 |

单位约定：所有 `*Pct` / `*PctPoint` 使用百分数点，金额统一为元，成交量统一为股。

默认硬门槛：

```text
amountDelta >= 2000 万，或 amount >= 3000 万，或满足相对量能增强条件
lastPrice >= max(preClose, officialOpen * 0.995)
09:35 后不再新增信号
缺少 09:25 基线不触发
```

第一版至少覆盖三个子形态：

| variant | 含义 | 示例规则 |
|---------|------|----------|
| `auction_gap_reversal` | 竞价尾价偏弱，开盘明显跳空上移 | `auctionPct <= 0.5`、`jumpPctPoint >= 3.0`、`firstWindowPct >= 1.5` |
| `low_open_red_reversal` | 低开/平开后 1-5 分钟快速翻红并放量承接 | `auctionPct <= 0` 或 `officialOpenPct <= 0.5`，`firstWindowPct >= 1.0` |
| `strong_open_board_attempt` | 有弱转强前置条件的开盘抢筹冲板 | `firstWindowPct >= 3.0`，且 `limitDistancePct <= 2.0` 或触及涨停，并至少满足 `auctionPct <= 0.5`、`officialOpenPct <= 0.5`、昨日分歧上下文或竞价后段抬升之一 |

评分分层：

```text
>= 80: critical，语音播报并主表醒目高亮
65-79: strong，按强信号策略播报
50-64: watch，仅列表和徽标
< 50: 不触发
```

`watch` 只入列表和弱徽标，默认不语音；`strong/critical` 才进入强提醒候选；dry-run 不语音、不飞书、不强高亮。

强信号升级：

```text
limitDistancePct <= 1.0
或 jumpPctPoint >= 5.0
或 09:30-09:35 内触及涨停
或 09:30 后 60 秒内涨幅继续扩大 >= 2.0 个百分点
```

## 网页板异动雷达

网页板新增本地 L1 检测路径，不影响现有选股通/同花顺普通事件展示，但这些 HTTP 事件源不得生成、补齐或参与 `opening_weak_to_strong`。该信号的检测输入只来自 `python-bridge` 实时行情。检测器监听 `webSocketService` 的 `FULL_STATE`、`QUOTE_PATCH` 和开盘强制采样快照或等价事件，在浏览器内维护当日开盘状态。

当前 HTTP feed 的定位：

| feed | 用途 | 边界 |
|------|------|------|
| `XuangubaoAbnormalEventFeed` | 展示选股通/选股宝异动事件 | 没有 `09:25` 竞价基线、官方开盘和成交额增量，不参与弱转强检测 |
| `ThsLimitUpEventFeed` | 展示涨停池、冲板池、炸板池线索 | 只能辅助确认冲板/封板状态，不还原弱转强过程 |
| `webSocketService` / `python-bridge` | `opening_weak_to_strong` 主检测源 | 必须在 `09:25` 前启动并订阅候选池 |

建议落点：

```text
src/services/hotlist/openingWeakToStrongTypes.ts
src/services/hotlist/OpeningWeakToStrongDetector.ts
src/services/hotlist/OpeningAuctionStateStore.ts
src/services/hotlist/HotStockEventMonitorService.ts
src/components/panels/HotStockEventMonitorPanel.vue
```

网页板触发后生成 `HotStockEvent` 兼容事件，进入现有异动雷达列表、去重和语音服务。语音继续走 `/api/local-voice/speak`，不要在浏览器端新建第二套声音实现。

## 桌面版异动精灵

桌面版必须独立可用，不依赖 Dragon Board 前端。C# 侧新增专用状态存储和检测器，接入现有事件链路。

建议落点：

```text
tools/YiDongJingLing/MarketData/TradingSession.cs
tools/YiDongJingLing/MarketData/OpeningAuctionState.cs
tools/YiDongJingLing/MarketData/OpeningAuctionStateStore.cs
tools/YiDongJingLing/Events/OpeningWeakToStrongDetector.cs
tools/YiDongJingLing/Events/EventRecord.cs
tools/YiDongJingLing/Events/EventDeduper.cs
tools/YiDongJingLing/Events/EventVoicePolicy.cs
tools/YiDongJingLing/Events/L1EventRules.cs
tools/YiDongJingLing/Settings/AppSettings.cs
tools/YiDongJingLing/MainForm.cs
```

`MainForm.HandleQuotes` 在非连续竞价时段不能简单跳过 `09:25` 报价：`09:24:50-09:25:10` 要写入 `OpeningAuctionStateStore`，`09:30-09:35` 调用 `OpeningWeakToStrongDetector`，事件再进入现有 `EventDeduper`、`AddEventRow`、`EventVoicePolicy` 和 `VoiceWorker`。

## 本地代理和主表展示

`proxy-server` 新增轻量本地信号缓存，不进入 QuantBoard，不写正式数据库。它只解决三件事：跨端共享、同日同股同类型去重、Dragon Board 主表读取。

`proxy-server` 不做行情采样，不计算 `auctionFinalPrice`，不替代网页板或桌面版检测器。主表对 `/api/opening-signals/today` 的 HTTP 读取只是展示同步，不是行情轮询。

`POST /api/opening-signals` 必须返回 `accepted/isNew/dedupeAction/voiceOwner/canonicalSignal/sources`。缓存结构区分 `canonicalSignal` 和 `reportsBySource`，不做 last-write-wins。默认桌面端是语音 owner；网页端只有拿到 `voiceOwner=web` 才播报。

建议 API：

```text
POST /api/opening-signals
GET /api/opening-signals/today
```

Dragon Board 主界面在行情主表合并今日信号，推荐在 [DataTable.vue](/d:/dragon-board/src/components/common/DataTable.vue) 股票名称旁显示小型“竞价弱转强”徽标，并给行增加短时红金高亮。展示应保持证券终端密度，不做大卡片或弹窗。

## 验证策略

桌面端：

```powershell
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
```

前端：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
pnpm build
```

必须覆盖的测试：

- `002552` 样例应命中。
- 低开快速翻红样例应命中。
- 有弱势前置的冲板抢筹样例应命中；无弱势前置的普通开盘冲板不得强播。
- `auction_gap_reversal` 中 `jumpPctPoint < 3.0` 不命中。
- 缺少 `09:25` 基线不命中。
- `09:35` 后不命中。
- 同一交易日同股同类型只触发一次。
- 网页端和桌面端生成的信号字段口径一致。
- 同一份 `docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json` 被 TS 和 C# 测试共同读取。
- dry-run 只记录不播报、不强高亮。
- bridge/proxy/网页/桌面离线矩阵有明确降级行为。

## 风险和处理

| 风险 | 处理 |
|------|------|
| 用户 `09:25` 前未启动工具 | 明确提示“缺少 09:25 基线，今日弱转强信号不可用”，不误报 |
| 监控池过大导致采样延迟 | 默认使用 `.blk` 强势池或八平台热榜池，超过 300 只提示延迟风险 |
| `officialOpen` 与分时第一条口径不同 | 两个字段同时保存，不混用 |
| 网页端和桌面端重复播报 | `proxy-server` 以 `tradingDate + code + signalType` 去重；语音端也保留本地冷却 |
| 低流动性跳动误报 | 成交额和成交增量门槛必开 |
| 主表 UI 过度抢眼 | 只用徽标和短时行强调，不改变主表信息密度 |

## 交付边界

V3 第一版完成时应同时满足：

1. 网页板异动雷达能在 `09:30-09:35` 捕捉并展示“竞价弱转强”。
2. `YiDongJingLing.exe` 能独立捕捉同一信号并语音播报。
3. Dragon Board 主行情表能突出显示命中股票。
4. 本地代理能保存今日信号并去重。
5. 所有能力都明确标注为 L1 口径，不宣称真 L2、十档或逐笔。
