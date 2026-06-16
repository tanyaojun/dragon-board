# 交易池统一合同——来源边界、展示语义、状态优先级、阈值真源、limitUp 契约

**日期**: 2026-06-16
**状态**: 权威版本，覆盖并取代此前各文档中冲突的局部口径
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

## 2. Tooltip / 共振展示语义：最终合同

经过 A+C+E 和 B+D 两轮迭代后，DataTable 的 confidence 列 tooltip 展示格式如下：

```
📌 华天科技 (002185)
🎯 综合判断: 买入 (置信度: 80%)
🚀 Jump跃迁: 观望 50.0%
📊 共振评分: 21.9 分 (MACD金叉+3, Jump持有0, 连续+18.9)
📌 交易池: 观察买点
──────────────────────────────
📈 MACD信号: 金叉 ✅
📊 排名趋势信号:
   📈 方向一致性: 买入 (69.60%)
   ⚡ 动量加速度: 买入 (64.05%)
   🔄 零线交叉: 观望 (50.00%)
```

**关键变更：**
- 移除"共振评级: 强共振/中/弱"（纯 BuyVotes 计数 → 与系统判定不一致）
- 新增"共振评分: N 分"（展示总分 + 离散/连续拆解）
- "交易池"行继续从 `getTradingPoolActionPreview` 的状态派生

**废止的口径：**
- ~~"共振评级: 强共振 (BuyVotes: 3/4)"~~ → 废止。改为评分总分。
- ~~spec 6.3 "移除共振评级行"~~ → 废止。保留该行但内容从标签改为评分。

## 3. 状态机优先级：唯一判定顺序

`decideTradingPoolStatus` 的判定顺序（从上到下，命中即返回）：

```
1. lifecycleAction === 'veto'
   → status: '已退出', decision: 'exit', reasons: ['lifecycle_veto']

2. signals.limitUp === true
   → status: '涨停观察', decision: 'watch', reasons: ['limit_up']
   （涨停票不进入评分体系，不自动入场）

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

**运行时真源：** `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.scoring`

```ts
// TradingPoolAnalysisService.ts
export function analyzeTradingPoolCandidate(input: TradingPoolInput): TradingPoolAnalysisResult {
  const thresholds = input.thresholds ?? DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool
  const scoring = thresholds.scoring  // ← 唯一运行时真源
  // ...
}
```

**旧字段处理策略：**

| 字段 | 处理方式 |
|------|---------|
| `recallJumpMin`, `readyJumpMin`, `observeFinalMin`, `readyFinalMin`, `buyVotesMin`, `downgradeJumpMin`, `downgradeFinalMin`, `exitFinalSell`, `jumpHoldMinConfidence` | 保留在类型中，标记 `@deprecated`，**不再参与任何判定逻辑** |
| `scoring` | 新评分体系的唯一真源 |
| `weights` | 连续维度权重，`computeResonanceScore` 通过参数接收，默认从 `DEFAULT_CONFIG.tradingPool.weights` 读取 |

**保证"配置改了就生效"的链路：**
1. 用户/代码修改 `input.thresholds` → 直接生效（传入覆盖）
2. 用户修改 `RANK_TREND_LIVE_STRATEGY_PRESETS` → 重启后生效（默认值变更）
3. 用户通过 UI 切换策略模式 → `normalizeRankTrendLiveStrategyConfig` 重新计算 `tradingPool.scoring` → 下次 `analyzeTradingPoolCandidate` 调用时生效

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
| Jump 信号过期（dataQuality !== 'fresh'）| `limitUp` 保留上一值，不重新判定 |

**禁止：** 交易池层不根据 `changePct` 或其他行情字段自行推断 `limitUp`。唯一真源是 `stock.rankTrend.jump.limitUp`。

## 6. 实施影响

本文档收敛后，以下文档的对应节被取代：

| 被取代的文档 | 被取代的节/行 | 取代原因 |
|-------------|-------------|---------|
| `candidate-pool-trading-pool-design.md` | L378, L399-411 | 来源边界从单轨道扩展为四轨道 |
| `2026-06-16-trading-pool-live-data-integration-design.md` | L69-117, L166-167, L194-221 | live_projection 降为四个轨道之一 |
| `2026-06-16-trading-pool-resonance-diagnosis.md` | L399-411 | jump_blocked_resonance 不再作为独立来源 |
| `2026-06-16-trading-pool-scoring-limitup-spec.md` | §2.4, §3.2, §4.1, §6.3 | 状态优先级/展示语义/tooltip 以此文为准 |

**不取代的部分：** 评分公式（离散+连续维度、权重、阈值预设）、涨停观察子轨道的 UI 展示、配置文件的 `scoring` + `weights` 结构——这些继续以 `scoring-limitup-spec.md` 和 `scoring-limitup-plan.md` 为准。
