# 交易池混合评分 + 涨停分轨——规格

**日期**: 2026-06-16
**状态**: 已确认，待实施
**依赖**: [2026-06-16 共振入池诊断报告](./2026-06-16-trading-pool-resonance-diagnosis.md)
**关联**: [2026-06-15 强共振自动入池规格](./2026-06-15-trading-pool-resonance-auto-entry-spec.md)

## 1. 目标

将交易池 `strongConsensus` 从 8 条件 pure AND 门改为混合评分体系，消除 Jump 单点否决导致系统性空集的缺陷。同时将 `checkEntryConditions` 第 4 条涨停过滤从硬排除改为观察轨道标记。

**不改变：** 候选池 V5/Fusion 合同、`checkEntryConditions` 其余 5 条、QuantBoard 回测主链、现有阈值预设结构。

## 2. 混合评分体系

### 2.1 离散维度

```ts
interface DiscreteScoreInput {
  macdCross: 'golden' | 'none' | 'death' | null
  jumpDirection: 'buy' | 'hold' | 'sell' | null
  lifecycleAction: string | null
}

function scoreDiscrete(input: DiscreteScoreInput): { score: number; veto: boolean } {
  let score = 0

  // MACD
  if (input.macdCross === 'golden') score += 3
  else if (input.macdCross === 'death') score -= 3

  // Jump 方向
  if (input.jumpDirection === 'buy') score += 2
  else if (input.jumpDirection === 'sell') score -= 2

  // 生命周期否决
  const veto = input.lifecycleAction === 'veto'

  return { score, veto }
}
```

### 2.2 连续维度

```ts
interface ContinuousScoreInput {
  jumpConfidence: number | null    // 0~100
  finalConfidence: number | null   // 0~100
  directionConfidence: number | null
  accelerationConfidence: number | null
  zeroCrossConfidence: number | null
}

const CONTINUOUS_WEIGHTS = {
  jumpConfidence:       2.0,
  finalConfidence:      1.5,
  directionConfidence:  1.0,
  accelerationConfidence: 1.0,
  zeroCrossConfidence:  0.5,
} as const

function scoreContinuous(input: ContinuousScoreInput): number {
  let score = 0
  const maxScore = 5 // 归一化系数

  score += (input.jumpConfidence ?? 0) / 100 * CONTINUOUS_WEIGHTS.jumpConfidence * maxScore
  score += (input.finalConfidence ?? 0) / 100 * CONTINUOUS_WEIGHTS.finalConfidence * maxScore
  score += (input.directionConfidence ?? 0) / 100 * CONTINUOUS_WEIGHTS.directionConfidence * maxScore
  score += (input.accelerationConfidence ?? 0) / 100 * CONTINUOUS_WEIGHTS.accelerationConfidence * maxScore
  score += (input.zeroCrossConfidence ?? 0) / 100 * CONTINUOUS_WEIGHTS.zeroCrossConfidence * maxScore

  return score
}
```

### 2.3 综合评分

```ts
function computeResonanceScore(
  discrete: DiscreteScoreInput,
  continuous: ContinuousScoreInput,
): { totalScore: number; veto: boolean } {
  const d = scoreDiscrete(discrete)
  if (d.veto) return { totalScore: 0, veto: true }

  const c = scoreContinuous(continuous)
  return { totalScore: d.score + c, veto: false }
}
```

理论区间：离散 -3 ~ +5，连续 0 ~ 30。总分 -3 ~ 35。

### 2.4 状态判定

| 状态 | 条件 |
|------|------|
| 已退出 | lifecycle=veto 或 总分 < 8 |
| 观察中 | 总分 ≥ 8 |
| 观察买点 | 总分 ≥ 15 |
| 准备介入 | 总分 ≥ 20 + MACD=golden + Jump 置信度 ≥ 80% |

```ts
type ScoringThresholds = {
  exitMax: number           // < 8 → exit
  observeMin: number        // ≥ 8 → observe
  buyPointMin: number       // ≥ 15 → 观察买点
  readyMin: number          // ≥ 20 → 准备介入 (需同时满足 macdGolden + jumpHigh)
  readyMacdRequired: 'golden'
  readyJumpMin: number      // 准备介入额外要求 Jump ≥ 80%
}
```

### 2.5 阈值预设

| 参数 | recall_first | balanced | strict_execution |
|------|-------------|----------|-----------------|
| scoring.exitMax | 6 | 8 | 10 |
| scoring.observeMin | 6 | 8 | 10 |
| scoring.buyPointMin | 12 | 15 | 18 |
| scoring.readyMin | 16 | 20 | 24 |
| scoring.readyJumpMin | 75 | 80 | 85 |

依旧三个策略模式，每个模式一份阈值。`jumpHoldMinConfidence`（方向 E）在评分体系下不再需要——Jump=hold 在离散维度中得 0 分（而非 buy 的 +2），已经通过评分表达了降权语义，不需要额外的方向门禁。

## 3. 涨停观察子轨道

### 3.1 入口层改动

`checkEntryConditions` 条件 4 从"硬排除"改为"标记"：

```ts
// 旧逻辑
if (changePct >= limitPct - 0.3) return false // 硬排除

// 新逻辑
const isLimitUp = changePct >= (limitPct - 0.3)
// 不 return false，继续判定其余条件
// isLimitUp 传递给下游
```

Jump 入口输出新增 `limitUp: boolean` 字段。

### 3.2 交易池层处理

```ts
// 涨停票进入观察轨道，不自动评分入场
if (signals.limitUp) {
  return {
    status: '涨停观察',
    decision: 'watch',
    reasons: ['limit_up'],
  }
}
```

### 3.3 开板重算

- 面板层检测当前 `changePct < 9%` 且之前标记为 `limitUp` → 触发重算
- 重算时 `limitUp = false`，正常走评分体系
- 涨停观察期不计入已介入状态

### 3.4 新增状态类型

```ts
export type TradingPoolStatus =
  | '观察买点'
  | '准备介入'
  | '已介入'
  | '持仓观察'
  | '观察中'
  | '已退出'
  | '已完成'
  | '涨停观察'  // 新增
```

### 3.5 风险标签

```ts
export type TradingPoolRiskFlag =
  // ... 现有标签 ...
  | 'limit_up'  // 新增
```

## 4. 与现有系统的兼容

### 4.1 `decideTradingPoolStatus` 替换

当前 `decideTradingPoolStatus` 包含 8 条件 AND + 多个提前返回路径。改为：

1. 先检查 lifecycle veto / limitUp / stale → 提前返回
2. 计算离散分 + 连续分 → 得总分
3. 按阈值判定状态

旧的 `strongConsensus` 8 条件 AND 逻辑整体移除，由评分体系替代。

### 4.2 `readRiskFlags` 调整

- 移除 `jump_confidence_low`（不再需要，因为评分中已体现）
- 移除 `final_confidence_low`（同上）
- 移除 `momentum_sync_broken` 的独立否决（在评分中通过加速度维度体现）
- 新增 `limit_up` 标签

### 4.3 `consensusBreakdown` 替换

当前的 `TradingPoolConsensusBreakdown`（8 条件 pass/fail）替换为 `ScoringBreakdown`（离散分 + 连续分 + 总分 + 阈值对比）。

### 4.4 配置统一

`TradingPoolThresholds` 中新增 `scoring` 字段，替代旧的单体阈值（`recallJumpMin`、`observeFinalMin` 等）。旧字段保留但标记 deprecated，下个版本移除。

## 5. 非目标

- 不改候选池 V5/Fusion 门禁
- 不改 `checkEntryConditions` 其余 5 条（持续性跃迁、动量共振、股价>0、MACD金叉、置信度≥85）
- 不引入机器学习或自适应权重
- 不动 QuantBoard Python 后端
- 不在此 spec 中实现开板重算的 UI 自动刷新（后续单独计划）

## 6. 验收标准

```powershell
# 混合评分服务测试
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolScoringService.test.ts --reporter=dot

# 涨停观察轨道测试
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot

# 面板测试
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot

# RankTrend 回归
pnpm test:ranktrend

# 类型检查
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

浏览器验收：
- 华天科技型票（Jump=hold, MACD金叉, 3/4 BuyVotes）展示为"观察买点"
- 涨停票展示为"涨停观察"，带有 `limit_up` 风险标签
- 交易池详情区展示评分拆解（离散 + 连续 + 总分）
