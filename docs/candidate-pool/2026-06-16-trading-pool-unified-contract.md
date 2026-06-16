# 交易池统一合同——来源边界、展示语义、状态优先级、阈值真源、limitUp 契约

**日期**: 2026-06-16
**状态**: 权威版本，覆盖并取代此前各文档中冲突的局部口径
**实现同步**: 已按核心实现更新至 `analyzeTradingPoolCandidate` 只读默认配置真源；不支持 per-call scoring/thresholds 覆盖。
**取代**: `candidate-pool-trading-pool-design.md:378`, `2026-06-16-trading-pool-live-data-integration-design.md:69-117`, `2026-06-16-trading-pool-resonance-diagnosis.md:399-411`, `2026-06-16-trading-pool-scoring-limitup-spec.md:2.4/3.2/4.1/6.3`

---

## 1. 来源边界：四轨道统一模型

交易池接受四个来源轨道的候选人。每个轨道有明确的优先级、去重策略和可入场性：

```
输入管道（analyzeTradingPoolCandidate 入口）
  │
  ├─ 轨道 1: thesis 候选（候选池日记 tradeType=thesis）
  │    来源: CandidateJournalService.listCandidates()
  │    优先级: 最高（同名 code 时覆盖轨道 2/3）
  │    可入场: 是（经过候选池人工筛选的正式候选）
  │    持久化: 是
  │
  ├─ 轨道 2: live_projection（DataLayer 八平台热榜实时投影）
  │    来源: dataLayer.getStocks().filter(s => s.rankTrend)
  │    优先级: 次（同名 code 时被 thesis 覆盖）
  │    可入场: 是（经过评分体系判定）
  │    持久化: 否（面板关闭后丢弃，下次打开重新生成）
  │
  ├─ 轨道 3: persisted（交易池持久化记录 tradeType=trading_pool）
  │    来源: CandidateJournalService.listTradingPoolEntries()
  │    优先级: 面板挂载时合并，同名 code 以 persisted 的状态为准
  │    可入场: N/A（已是交易池内记录，参与状态恢复）
  │    持久化: 是
  │
  └─ 轨道 4: manual（手工加入）
       来源: 用户通过 UI 操作加入
       优先级: 最高（手工加入不可被其他轨道覆盖）
       可入场: 是
       持久化: 是
```

**去重规则（按 code）：**
1. 轨道 4 (manual) > 轨道 1 (thesis) > 轨道 2 (live_projection)
2. 轨道 3 (persisted) 在面板挂载时恢复，与当前重算结果合并——已介入状态保留，过期则标记 stale

**废止的口径：**
- ~~"交易池只显示候选池通过后的对象"~~（`candidate-pool-trading-pool-design.md:378`）→ 废止。交易池接受四个轨道。
- ~~`jump_blocked_resonance` 作为独立来源轨道~~ → 废止。Jump 阻断强共振票通过评分体系自然进入，不再需要独立来源标签。`TradingPoolSource.jump_blocked_resonance` 保留在类型中不删除（向后兼容），但不再被 `resolveTradingPoolSource` 产出。

**输出 source 合同：**
- 正常输出只使用 `thesis`、`live_projection`、`persisted`、`manual`、`unknown`。
- 旧输入 `jump_blocked_resonance` 与 `candidate_auto_add` 兼容归并为 `thesis` 输出。
- 未识别来源不再静默归为 `thesis`，最终兜底为 `unknown`，用于暴露未来新增来源未接入的情况。

## 2. Tooltip / 共振展示语义：最终合同

经过 A+C+E、B+D 和方向感知+归一化迭代后，DataTable 的 confidence 列 tooltip 展示格式如下：

```
📌 华天科技 (002185)
🎯 综合判断: 买入 (置信度: 80%)
🚀 Jump跃迁: 观望 50.0%
📊 共振强度: 强 (73%) · 22.0 分 (MACD金叉+3, Jump持有0, 连续+18.9)
📌 交易池: 观察买点
──────────────────────────────
📈 MACD信号: 金叉 ✅
📊 排名趋势信号:
   📈 方向一致性: 买入 (69.60%)
   ⚡ 动量加速度: 买入 (64.05%)
   🔄 零线交叉: 观望 (50.00%)
```

**关键变更：**
- "共振评分" → "共振强度"，归一化为百分比 + 五级标签
- 连续分维度已方向感知化（卖出方向置信度贡献负分，买入方向正分，hold=0）
- "交易池"行继续从 `getTradingPoolActionPreview` 的状态派生

**废止的口径：**
- ~~"共振评级: 强共振 (BuyVotes: 3/4)"~~ → 废止。改为评分总分。
- ~~"共振评分"裸数字~~ → 废止。改为归一化百分比+标签。
- ~~spec 6.3 "移除共振评级行"~~ → 废止。保留该行但内容从标签改为评分。

## 3. 状态机优先级：唯一判定顺序

`decideTradingPoolStatus` 的判定顺序（从上到下，命中即返回）：

```
1. lifecycleAction === 'veto'
   → status: '已退出', decision: 'exit', reasons: ['lifecycle_veto']

2. signals.limitUp === true
   → status: '涨停观察', decision: 'watch', reasons: ['limit_up']
   （涨停票不进入评分判定，不自动入场；展示用评分拆解可复用同一组信号计算）

3. signals.dataQuality !== 'fresh'（信号过期）
   → status: previous?.status || '观察中', decision: 'stale'
   （保留上一状态，不强制退出）

4. previous?.status === '已介入'（已介入状态保持）
   ├─ 总分 < scoring.exitMax → status: '已退出', decision: 'exit'
   └─ else → status: '已介入', decision: 'stale'
   （已介入由人工操作进入，评分低到退出线才自动退出）

5. 评分判定（以下按分数从高到低）:
   ├─ totalScore < scoring.exitMax → '已退出', 'exit'
   ├─ totalScore >= scoring.readyMin
   │   AND macdCross === 'golden'
   │   AND jumpConfidence >= scoring.readyJumpMin
   │   → '准备介入', 'enter'
   ├─ totalScore >= scoring.buyPointMin → '观察买点', 'enter'
   ├─ totalScore >= scoring.observeMin → '观察中', 'watch'
   └─ else → '观察中', 'watch'
```

**关键规则：**
- `limitUp` 优先级低于 veto（被否决的涨停票仍然退出），高于评分（涨停票不评分）
- `stale` 优先级低于 limitUp（涨停票即使数据过期也保持涨停观察）
- 已介入只由人工操作设置，只由评分过低自动退出
- 评分判定只处理"未介入"状态，已介入走独立保持逻辑

## 4. 阈值真源：运行时唯一读取路径

**运行时真源：**
- `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.scoring`
- `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.weights`

```ts
// TradingPoolAnalysisService.ts
export function analyzeTradingPoolCandidate(input: TradingPoolInput): TradingPoolAnalysisResult {
  const tradingPoolConfig = DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool
  const scoring = tradingPoolConfig.scoring
  const weights = tradingPoolConfig.weights
  // ...
}
```

`TradingPoolInput` 只承载候选输入、上一轮行状态和实时投影股票：

```ts
interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
  liveStocks?: TradingPoolCandidateLike[]
}
```

**旧字段处理策略：**

| 字段 | 处理方式 |
|------|---------|
| `recallJumpMin`, `readyJumpMin`, `observeFinalMin`, `readyFinalMin`, `buyVotesMin`, `downgradeJumpMin`, `downgradeFinalMin`, `exitFinalSell`, `jumpHoldMinConfidence` | 保留在类型中，标记 `@deprecated`，**不再参与任何判定逻辑** |
| `scoring` | 新评分体系阈值真源，只从默认配置读取 |
| `weights` | 连续维度权重真源，只从默认配置读取 |
| `TradingPoolInput.thresholds` / `TradingPoolInput.scoring` | 不再作为输入合同存在；调用方传入不会被设计为生效 |

**保证"配置改了就生效"的链路：**
1. 用户修改 `RANK_TREND_LIVE_STRATEGY_PRESETS` / 默认策略配置 → 重启或重新装载配置后生效。
2. 用户通过 UI 切换策略模式 → `normalizeRankTrendLiveStrategyConfig` 重新计算 `tradingPool.scoring` / `weights` 后生效。
3. `analyzeTradingPoolCandidate` 本身不接受临时阈值覆盖，避免同一交易池在不同调用方出现多套判定口径。

### 4.1 评分公式与方向感知

`computeResonanceScore` 是模块私有的评分函数，实现离散+连续混合评分：

**离散维度（二值/三值，不做连续映射）：**

| 维度 | buy 态 | neutral 态 | sell 态 |
|------|--------|-----------|---------|
| MACD cross | golden → **+3** | none → **0** | death → **-3** |
| Jump 方向 | buy → **+2** | hold → **0** | sell → **-2** |

**连续维度（0~100 置信度 × 方向符号 × 权重 × 5）：**

| 维度 | 权重 | 方向来源 |
|------|------|---------|
| Jump 置信度 | 2.0 | `directionSign(jumpDirection)` |
| 综合 final 置信度 | 2.0 | `directionSign(finalSignal)` |
| 方向一致性置信度 | 2.0 | `directionSign(directionSignal)` |
| 动量加速度置信度 | 2.0 | `directionSign(accelerationSignal)` |
| 零线交叉置信度 | 2.0 | `directionSign(zeroCrossSignal)` |

`directionSign(buy)=+1, directionSign(sell)=-1, 其他=0`。卖出信号高置信度→负连续分→拉低总分，消除"卖信号高分入池"缺陷。

### 4.2 共振强度归一化

`normalizeResonanceIntensity(totalScore)` 是公开导出函数，将原始总分映射为百分比+五级标签：

```
pct = clamp(round(totalScore / RESONANCE_NORMALIZATION_CEILING × 100), 0, 100)
```

天花板 30（五维全买100%置信理论最大约55分，30覆盖全部决策阈值区间并保留强信号余量）：

| 归一化 | 原始分 | 标签 | 锚定决策层 |
|--------|--------|------|-----------|
| ≥ 90% | ≥ 27 | 非常强 | 远超 readyMin(20) |
| 67-89% | 20-26 | 强 | 准备介入 |
| 50-66% | 15-19 | 中等 | 观察买点 |
| 27-49% | 8-14 | 较弱 | 观察中 |
| < 27% | < 8 | 非常弱 | 已退出 |

层级边界与评分阈值(exitMax=8, buyPointMin=15, readyMin=20)对齐，不按纯数学等分。

## 5. limitUp 数据契约：生产者、传播路径、回退

### 5.1 唯一生产者

`limitUp` 由 **`jumpSignalService.ts` 的 `checkEntryConditions`** 唯一产出。交易池层不自行计算涨停判定。

```ts
// jumpSignalService.ts — checkEntryConditions 返回值新增
interface JumpEntryCheckResult {
  passed: boolean
  reasons: string[]
  limitUp: boolean  // 新增：true 表示 changePct >= limitPct - 0.3
}
```

### 5.2 传播路径

```
jumpSignalService.checkEntryConditions()
  │
  ├─ limitUp: true/false
  │
  └─→ evaluateJumpSignal() 返回值
        │
        └─→ applyJumpSignal() → stock.rankTrend.jump.limitUp
              │
              └─→ RankTrendSignalService.applyJumpSignals()
                    │
                    └─→ dataLayer.stocks[i].rankTrend.jump.limitUp
                          │
                          └─→ readTradingSignals()
                                │
                                └─→ TradingPoolSignalSnapshot.limitUp
                                      │
                                      └─→ decideTradingPoolStatus()
```

### 5.3 回退策略

| 场景 | 行为 |
|------|------|
| `stock.rankTrend.jump` 不存在 | `limitUp = false`（默认非涨停） |
| `stock.rankTrend.jump.limitUp` 为 `undefined` | `limitUp = false` |
| `stock.rankTrend.jump` 存在但 `limitUp` 字段缺失（旧数据兼容） | `limitUp = false` |
| Jump 信号过期或 `rankTrend` 缺失 | 交易池层不自行重判；没有 `rankTrend.jump.limitUp` 时按 `false` 处理，上一状态由 stale 分支保留 |

**禁止：** 交易池层不根据 `changePct` 或其他行情字段自行推断 `limitUp`。唯一真源是 `stock.rankTrend.jump.limitUp`。

## 6. 实施影响

本文档收敛后，以下文档的对应节被取代：

| 被取代的文档 | 被取代的节/行 | 取代原因 |
|-------------|-------------|---------|
| `candidate-pool-trading-pool-design.md` | L378, L399-411 | 来源边界从单轨道扩展为四轨道 |
| `2026-06-16-trading-pool-live-data-integration-design.md` | L69-117, L166-167, L194-221 | live_projection 降为四个轨道之一 |
| `2026-06-16-trading-pool-resonance-diagnosis.md` | L399-411 | jump_blocked_resonance 不再作为独立来源 |
| `2026-06-16-trading-pool-scoring-limitup-spec.md` | §2.4, §3.2, §4.1, §6.3 | 状态优先级/展示语义/tooltip 以此文为准 |

**不取代的部分：** 涨停观察子轨道的 UI 展示——以 `scoring-limitup-spec.md` 和 `scoring-limitup-plan.md` 为准。评分公式、方向感知、归一化均已由本文 §4.1-§4.2 收敛，不再引外部文档。
