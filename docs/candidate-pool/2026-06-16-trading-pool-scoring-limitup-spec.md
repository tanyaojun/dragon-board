# 交易池混合评分 + 涨停分轨——规格

**日期**: 2026-06-16
**状态**: 已确认，待实施
**依赖**: [2026-06-16 共振入池诊断报告](./2026-06-16-trading-pool-resonance-diagnosis.md)
**关联**: [2026-06-15 强共振自动入池规格](./2026-06-15-trading-pool-resonance-auto-entry-spec.md)
**⚠️ 优先级声明:** 本文的 §2.4（状态判定）、§3.2（涨停处理优先级）、§4.1（判定顺序）、§6.3（tooltip 展示）已被 [统一合同](./2026-06-16-trading-pool-unified-contract.md) 的第 3-5 节覆盖。实施时以统一合同为准。

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
  const maxScore = 5 // 缩放系数（乘以此值使各维度得分有区分度，总分上限约 30）

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

### 2.4 评分驱动状态判定

评分体系负责四个"自动判定"状态。其余三个状态由人工操作触发：

| 状态 | 触发方式 | 条件 |
|------|---------|------|
| 已退出 | 自动 | lifecycle=veto 或 总分 < `exitMax` |
| 观察中 | 自动 | 总分 ≥ `observeMin` 且不满足更高状态 |
| 观察买点 | 自动 | 总分 ≥ `buyPointMin` 且不满足准备介入 |
| 准备介入 | 自动 | 总分 ≥ `readyMin` + MACD=`readyMacdRequired` + Jump 置信度 ≥ `readyJumpMin` |
| 已介入 | 人工 | 用户在面板点击"已介入"按钮 |
| 持仓观察 | 人工 | 已介入状态下用户标记为持仓观察 |
| 已完成 | 人工 | 用户手动关闭交易记录 |
| 涨停观察 | 自动 | 见 §3（优先级低于 lifecycle veto，高于评分判定） |

**判定优先级：** lifecycle veto > 涨停观察 > 信号过期 > 已介入保持 > 评分判定

```ts
type ScoringThresholds = {
  exitMax: number           // 总分低于此值 → 已退出
  observeMin: number        // 总分 ≥ 此值 → 观察中
  buyPointMin: number       // 总分 ≥ 此值 → 观察买点
  readyMin: number          // 总分 ≥ 此值 + macdGolden + jumpHigh → 准备介入
  readyMacdRequired: 'golden'
  readyJumpMin: number      // 准备介入额外要求 Jump 置信度 ≥ 此值
}
```

### 2.5 与方向 E（Jump hold 降权）的关系

本评分体系替代了方向 E 的 `jumpHoldMinConfidence` 机制。Jump=hold 在离散维度中得 0 分（对比 buy 的 +2），已在评分中体现降权语义。旧的 `jumpHoldMinConfidence` 字段标记 deprecated。

### 2.6 阈值预设

| 参数 | recall_first | balanced | strict_execution |
|------|-------------|----------|-----------------|
| scoring.exitMax | 6 | 8 | 10 |
| scoring.observeMin | 6 | 8 | 10 |
| scoring.buyPointMin | 12 | 15 | 18 |
| scoring.readyMin | 16 | 20 | 24 |
| scoring.readyJumpMin | 75 | 80 | 85 |

依旧三个策略模式，每个模式一份阈值。

### 2.7 测试迁移说明

实施本 spec 后以下旧逻辑将移除，对应测试需同步更新：
- `strongConsensus` 8 条件 AND → 测试预期改为评分驱动阈值
- `TradingPoolConsensusBreakdown` → 替换为 `TradingPoolScoringBreakdown`
- `readRiskFlags` 中 `jump_confidence_low` / `final_confidence_low` / `momentum_sync_broken` → 从测试中移除这些 flag 的断言
- `jumpHoldMinConfidence` → 不再使用，`strongConsensus` 中 Jump hold 的判定改为评分体系内处理

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
