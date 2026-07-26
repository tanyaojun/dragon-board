import type { RankTrendAnalysisResult } from './types'
import { detectRankJumps, type JumpResult } from './jumpDetector'

// ── 出场配置 ──
export interface JumpExitConfig {
  maxHoldingBars: number   // 最大持有周期（信号刷新次数）
  stopLossPct: number      // 硬止损线，如 -0.05
  takeProfitPct: number    // 止盈线，如 0.12
}

const DEFAULT_EXIT_CONFIG: JumpExitConfig = {
  maxHoldingBars: 40,
  stopLossPct: -0.05,
  takeProfitPct: 0.12,
}

let exitConfig: JumpExitConfig = { ...DEFAULT_EXIT_CONFIG }

export function setJumpExitConfig(config: Partial<JumpExitConfig>): void {
  exitConfig = { ...exitConfig, ...config }
}

export function getJumpExitConfig(): JumpExitConfig {
  return { ...exitConfig }
}

// ── 持仓追踪 ──
interface TrackedPosition {
  code: string
  name: string
  entryPrice: number
  entryDate: string
  entryBar: number
}

const activePositions = new Map<string, TrackedPosition>()
let globalBarCount = 0

// Legacy jump display state only. V5 fusion holding/exit semantics live in
// v5FusionExecutionContract and FusionStrategyProjector; do not use this map
// as V5 strategy state.

export function registerJumpEntry(code: string, name: string, entryPrice: number, entryDate: string): void {
  if (!activePositions.has(code)) {
    activePositions.set(code, { code, name, entryPrice, entryDate, entryBar: globalBarCount })
  }
}

export function unregisterJumpPosition(code: string): void {
  activePositions.delete(code)
}

export function incrementJumpBar(): void {
  globalBarCount++
}

export function getJumpPositionCount(): number {
  return activePositions.size
}

export function getJumpPositions(): ReadonlyMap<string, TrackedPosition> {
  return activePositions
}

function getHoldingBars(code: string): number {
  const pos = activePositions.get(code)
  if (!pos) return 0
  return globalBarCount - pos.entryBar
}

function getUnrealizedPnl(code: string, currentPrice: number): number {
  const pos = activePositions.get(code)
  if (!pos || pos.entryPrice <= 0 || currentPrice <= 0) return 0
  return (currentPrice - pos.entryPrice) / pos.entryPrice
}

// ── 涨跌幅限制 ──
function dailyLimitPct(code: string): number {
  const c = String(code || '').trim()
  if (c.startsWith('8')) return 30
  if (c.startsWith('300') || c.startsWith('301') || c.startsWith('688')) return 20
  return 10
}

function hasMomentumConfirmation(rankTrend: RankTrendAnalysisResult): boolean {
  const signals = rankTrend.technical?.signals
  return signals?.direction?.signal === 'buy' && signals?.acceleration?.signal === 'buy'
}

// ── 入场条件 AND ──
export function checkEntryConditions(
  stock: any,
  rankTrend: RankTrendAnalysisResult,
  jump: JumpResult,
): { passed: boolean; limitUp: boolean } {
  // 1. 内生阈值：排名持续跳跃式上升
  if (jump.event !== 'jump' || jump.direction !== 'buy' || !jump.sustained) return { passed: false, limitUp: false }

  // 2. 多周期动量和加速度共振
  if (!hasMomentumConfirmation(rankTrend)) return { passed: false, limitUp: false }

  // 3. 股价同向确认：股价在涨
  const changePct = Number(stock?.change ?? 0)
  if (changePct <= 0) return { passed: false, limitUp: false }

  // 4. 涨停板过滤
  const limitPct = dailyLimitPct(String(stock?.code ?? ''))
  const limitUp = changePct >= limitPct - 0.3

  // 5. MACD 金叉
  if (rankTrend.technical?.macd?.cross !== 'golden') return { passed: false, limitUp }

  // 6. 跳跃置信度 > 85
  if (Number(jump.confidence ?? 0) < 85) return { passed: false, limitUp }

  return { passed: true, limitUp }
}

// ── 出场条件 OR（七条件，含持仓管理）──
export function checkExitConditions(
  stock: any,
  rankTrend: RankTrendAnalysisResult | null,
  jump: JumpResult | null,
  isInFrame: boolean,
  currentPrice?: number,
): [boolean, string] {
  if (!isInFrame) return [true, '退出热榜池']

  if (!rankTrend || !jump) return [false, '']

  const code = String(stock?.code ?? '')

  // 1. 内生阈值：排名持续崩塌
  if (jump.event === 'jump' && jump.direction === 'sell' && jump.sustained) {
    return [true, `排名持续崩塌(jump=${jump.magnitude.toFixed(1)}pct)`]
  }

  // 2. MACD 死叉
  if (rankTrend.technical?.macd?.cross === 'death') {
    return [true, 'MACD 死叉']
  }

  // 3. 排名大幅下降（fallback）
  const rawChange = Number(rankTrend.meta?.rawChange ?? 0)
  if (rawChange < -80) {
    return [true, `排名大幅下降(${Math.round(rawChange)})`]
  }

  // 4. 达到最大持有周期
  const bars = getHoldingBars(code)
  if (bars > 0 && bars >= exitConfig.maxHoldingBars) {
    return [true, `达到最大持有周期(${bars}bars)`]
  }

  // 5-6. 止损 / 止盈
  const price = currentPrice ?? Number(stock?.price ?? stock?.lastTradePrice ?? 0)
  if (price > 0) {
    const pnl = getUnrealizedPnl(code, price)
    if (pnl !== 0) {
      if (pnl <= exitConfig.stopLossPct) {
        return [true, `硬止损(${(pnl * 100).toFixed(1)}%)`]
      }
      if (pnl >= exitConfig.takeProfitPct) {
        return [true, `止盈(${(pnl * 100).toFixed(1)}%)`]
      }
    }
  }

  return [false, '']
}

// ── 聚合评估 ──
export function evaluateJumpSignal(
  stock: any,
  rankTrend: RankTrendAnalysisResult,
  percentiles: number[],
  isInFrame: boolean,
  ranks?: number[],
): JumpSignalResult {
  const jump = detectRankJumps(percentiles, ranks, 15)
  const entryCheck = checkEntryConditions(stock, rankTrend, jump)
  const currentPrice = Number(stock?.price ?? stock?.lastTradePrice ?? 0)
  const [isExit, exitReason] = entryCheck.passed
    ? [false, '']
    : checkExitConditions(stock, rankTrend, jump, isInFrame, currentPrice)

  return { jump, isEntry: entryCheck.passed, isExit, exitReason, limitUp: entryCheck.limitUp }
}

export interface JumpSignalResult {
  jump: JumpResult
  isEntry: boolean
  isExit: boolean
  exitReason: string
  limitUp: boolean
}
