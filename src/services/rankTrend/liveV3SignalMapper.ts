import type { RankTrendAnalysisResult, CandidateTier } from './types'

export type V3LiveSignalLabel =
  | 'A主升买点'
  | 'B点火买点'
  | '止损卖出'
  | '转弱卖出'
  | '离榜卖出'
  | '持有观察'
  | '无信号'

export type V3LiveSignalTone = 'buy' | 'sell' | 'watch' | 'neutral'

export interface V3LiveSignalDecision {
  label: V3LiveSignalLabel
  tone: V3LiveSignalTone
  reasons: string[]
  degraded: boolean
  degradedReason?: string
}

type RankTrendLike = RankTrendAnalysisResult & {
  jump?: {
    direction?: string
    confidence?: number
  }
}

type EntrySignalLabel = Extract<V3LiveSignalLabel, 'A主升买点' | 'B点火买点'>

type LiveV3TrackedPosition = {
  code: string
  entryPrice: number
  holdingBars: number
  hotlistMissingBars: number
  entryLabel: EntrySignalLabel
}

const liveV3Positions = new Map<string, LiveV3TrackedPosition>()
let lastProcessedSlotKey: string | null = null

function asNumber(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getRankTrend(stock: any): RankTrendLike | null {
  return (stock?.rankTrend as RankTrendLike | undefined) ?? null
}

function getCandidateTier(rankTrend: RankTrendLike): CandidateTier | '' {
  return (rankTrend.strategy?.candidateTier as CandidateTier | undefined) ?? ''
}

function getMomentum(rankTrend: RankTrendLike) {
  return rankTrend.technical?.momentumProfile ?? rankTrend.strategy?.momentum
}

function getSampleQualityStatus(rankTrend: RankTrendLike): 'ok' | 'degraded' | 'insufficient' | '' {
  return rankTrend.meta?.sampleQuality?.status ?? ''
}

function getLifecycleAction(rankTrend: RankTrendLike): string {
  return String(rankTrend.cycle?.decision?.action ?? '')
}

function getDegradedMetadata(rankTrend: RankTrendLike): { degraded: boolean; degradedReason?: string } {
  const sampleQuality = rankTrend.meta?.sampleQuality
  if (sampleQuality?.status === 'degraded') {
    const detail = sampleQuality.coverageWarning
      ? `：${sampleQuality.coverageWarning}`
      : '，当前信号仅供盘中辅助判断'
    return {
      degraded: true,
      degradedReason: `样本降级${detail}`,
    }
  }
  return { degraded: false }
}

function isLimitUpBlocked(stock: any): boolean {
  const change = asNumber(stock?.change)
  const code = String(stock?.code ?? '')
  const threshold = code.startsWith('300') || code.startsWith('301') || code.startsWith('688') ? 19.8 : 9.8
  return change >= threshold
}

function hasBaseV3EntryGate(stock: any, rankTrend: RankTrendLike): { ok: boolean; reasons: string[] } {
  const jumpDirection = String(rankTrend.jump?.direction ?? '')
  const jumpConfidence = asNumber(rankTrend.jump?.confidence)
  const momentum = getMomentum(rankTrend)
  const short = asNumber(momentum?.short)
  const mid = asNumber(momentum?.mid)
  const long = asNumber(momentum?.long)
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber((stock as any)?.accDelta)
  const change = asNumber(stock?.change)

  const checks = [
    jumpDirection === 'buy' ? '' : 'jump.direction 不是 buy',
    jumpConfidence >= 90 ? '' : `jump.confidence=${jumpConfidence.toFixed(1)} < 90`,
    short > 0 ? '' : `short=${short.toFixed(1)} <= 0`,
    mid > 0 ? '' : `mid=${mid.toFixed(1)} <= 0`,
    long > 0 ? '' : `long=${long.toFixed(1)} <= 0`,
    acceleration >= 10 || accDelta >= 8
      ? ''
      : `acceleration=${acceleration.toFixed(1)} 且 accDelta=${accDelta.toFixed(1)} 未达阈值`,
    change < 6 ? '' : `change=${change.toFixed(2)} >= 6`,
    !isLimitUpBlocked(stock) ? '' : '涨停附近不可买',
  ].filter(Boolean)

  return {
    ok: checks.length === 0,
    reasons: checks.length ? checks : ['满足 V3 共同入场门槛'],
  }
}

function buildDecision(
  label: V3LiveSignalLabel,
  tone: V3LiveSignalTone,
  reasons: string[],
  degraded = false,
  degradedReason?: string,
): V3LiveSignalDecision {
  return { label, tone, reasons, degraded, degradedReason }
}

function getBaseLiveV3SignalDecision(stock: any): V3LiveSignalDecision {
  const rankTrend = getRankTrend(stock)
  if (!rankTrend) {
    return buildDecision('无信号', 'neutral', ['缺少 rankTrend 数据'], true, '缺少 rankTrend 数据')
  }

  if (getSampleQualityStatus(rankTrend) === 'insufficient') {
    const sampleQuality = rankTrend.meta?.sampleQuality
    return buildDecision(
      '无信号',
      'neutral',
      [
        `样本质量不足(${sampleQuality?.sampleCount ?? 0}/${sampleQuality?.requiredSampleCount ?? 0})`,
        sampleQuality?.coverageWarning || '当前快照不足以支持 V3 动作判断',
      ].filter(Boolean),
      true,
      '样本质量不足',
    )
  }

  const degradedMeta = getDegradedMetadata(rankTrend)
  const tier = getCandidateTier(rankTrend)
  const lifecycleAction = getLifecycleAction(rankTrend)

  const baseGate = hasBaseV3EntryGate(stock, rankTrend)
  if (tier === 'A_MAIN' && baseGate.ok && lifecycleAction !== 'veto') {
    return buildDecision('A主升买点', 'buy', [
      'candidateTier = A_MAIN',
      lifecycleAction === 'caution' ? '生命周期B谨慎放行' : '生命周期B未否决',
      ...baseGate.reasons,
    ], degradedMeta.degraded, degradedMeta.degradedReason)
  }

  if (tier === 'B_IGNITION' && baseGate.ok && lifecycleAction !== 'veto') {
    const momentum = getMomentum(rankTrend)
    const mid = asNumber(momentum?.mid)
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
    if (mid >= 20 && zeroCross === 'buy') {
      return buildDecision('B点火买点', 'buy', [
        'candidateTier = B_IGNITION',
        lifecycleAction === 'caution' ? '生命周期B谨慎放行' : '生命周期B未否决',
        ...baseGate.reasons,
        `mid=${mid.toFixed(1)} >= 20`,
        'zeroCross = buy',
      ], degradedMeta.degraded, degradedMeta.degradedReason)
    }
  }

  if (tier === 'A_MAIN' || tier === 'B_IGNITION' || tier === 'C_CROWDED' || tier === 'N_NEUTRAL') {
    return buildDecision('持有观察', 'watch', [
      tier ? `candidateTier = ${tier}` : '存在候选但未达动作阈值',
      lifecycleAction === 'veto'
        ? '生命周期B当前明确反对，继续观察'
        : lifecycleAction === 'exit_watch'
          ? '生命周期B提示进入退出观察'
          : lifecycleAction === 'caution'
            ? '生命周期B提示谨慎观察'
            : '当前未命中买入动作',
      ...(baseGate.ok ? ['未命中当前层级专属确认条件'] : baseGate.reasons.slice(0, 2)),
    ], degradedMeta.degraded, degradedMeta.degradedReason)
  }

  return buildDecision('无信号', 'neutral', ['当前数据未命中 V3 动作规则'], true, '当前数据未命中 V3 动作规则')
}

function getStockCode(stock: any): string {
  return String(stock?.code ?? '')
}

function getCurrentPrice(stock: any): number {
  return asNumber(stock?.price ?? stock?.lastTradePrice ?? 0)
}

function getSlotKey(stock: any): string | null {
  const rankTrend = getRankTrend(stock)
  const sampleQuality = rankTrend?.meta?.sampleQuality
  const tradingDate = String(sampleQuality?.latestTradingDate ?? '').trim()
  const slotTime = String(sampleQuality?.latestSlotTime ?? '').trim()
  if (!tradingDate || !slotTime) return null
  return `${tradingDate} ${slotTime}`
}

function getLatestSlotKey(stocks: any[]): string | null {
  const slotKeys = stocks
    .map((stock) => getSlotKey(stock))
    .filter((value): value is string => Boolean(value))
    .sort()
  return slotKeys[slotKeys.length - 1] ?? null
}

function isEntryLabel(label: V3LiveSignalLabel): label is EntrySignalLabel {
  return label === 'A主升买点' || label === 'B点火买点'
}

function registerLiveV3Position(stock: any, decision: V3LiveSignalDecision): void {
  if (!isEntryLabel(decision.label)) return
  const code = getStockCode(stock)
  if (!code || liveV3Positions.has(code)) return
  liveV3Positions.set(code, {
    code,
    entryPrice: getCurrentPrice(stock),
    holdingBars: 0,
    hotlistMissingBars: 0,
    entryLabel: decision.label,
  })
}

function syncTrackedPositions(stocks: any[]): void {
  const currentCodes = new Set(stocks.map((stock) => getStockCode(stock)).filter(Boolean))
  const latestSlotKey = getLatestSlotKey(stocks)
  const slotAdvanced = Boolean(latestSlotKey && latestSlotKey !== lastProcessedSlotKey)

  if (slotAdvanced) {
    for (const position of liveV3Positions.values()) {
      position.holdingBars += 1
      position.hotlistMissingBars = currentCodes.has(position.code)
        ? 0
        : position.hotlistMissingBars + 1
    }
    lastProcessedSlotKey = latestSlotKey
  } else if (!lastProcessedSlotKey && latestSlotKey) {
    lastProcessedSlotKey = latestSlotKey
  } else {
    for (const position of liveV3Positions.values()) {
      if (currentCodes.has(position.code)) {
        position.hotlistMissingBars = 0
      }
    }
  }

  for (const [code, position] of liveV3Positions) {
    if (!currentCodes.has(code) && position.hotlistMissingBars >= 3) {
      liveV3Positions.delete(code)
    }
  }
}

function buildTrackedExitDecision(
  label: Extract<V3LiveSignalLabel, '止损卖出' | '转弱卖出' | '离榜卖出'>,
  reasons: string[],
  stock: any,
): V3LiveSignalDecision {
  const rankTrend = getRankTrend(stock)
  const degradedMeta = rankTrend ? getDegradedMetadata(rankTrend) : { degraded: false }
  return buildDecision(
    label,
    'sell',
    reasons,
    degradedMeta.degraded,
    degradedMeta.degradedReason,
  )
}

function evaluateTrackedPositionDecision(
  stock: any,
  position: LiveV3TrackedPosition,
): V3LiveSignalDecision {
  const rankTrend = getRankTrend(stock)
  const currentPrice = getCurrentPrice(stock)
  const grossReturn =
    position.entryPrice > 0 && currentPrice > 0
      ? (currentPrice - position.entryPrice) / position.entryPrice
      : null
  const lifecycleAction = rankTrend ? getLifecycleAction(rankTrend) : ''
  const macdCross = String(rankTrend?.technical?.macd?.cross ?? 'none')
  const rawChange = asNumber(rankTrend?.meta?.rawChange)

  if (position.hotlistMissingBars >= 3) {
    return buildTrackedExitDecision('离榜卖出', ['退出热榜连续 3 个 bar'], stock)
  }

  if (grossReturn !== null && grossReturn <= -0.05) {
    return buildTrackedExitDecision(
      '止损卖出',
      [`浮动收益 ${(grossReturn * 100).toFixed(1)}% <= -5.0%`],
      stock,
    )
  }

  if (grossReturn !== null && grossReturn <= 0 && ['veto', 'exit_watch'].includes(lifecycleAction)) {
    return buildTrackedExitDecision(
      '转弱卖出',
      [
        `生命周期B=${lifecycleAction} 且当前未盈利(${(grossReturn * 100).toFixed(1)}%)`,
      ],
      stock,
    )
  }

  if (rawChange < -50 && macdCross === 'death') {
    return buildTrackedExitDecision(
      '转弱卖出',
      [`rawChange=${rawChange.toFixed(1)} < -50`, 'MACD 死叉'],
      stock,
    )
  }

  if (position.holdingBars >= 30) {
    return buildTrackedExitDecision(
      '转弱卖出',
      [`达到最大持有快照(${position.holdingBars} bars)`],
      stock,
    )
  }

  const baseDecision = getBaseLiveV3SignalDecision(stock)
  return buildDecision(
    '持有观察',
    'watch',
    [
      `已按 ${position.entryLabel} 建立跟踪仓位`,
      `持有 ${position.holdingBars} bars`,
      grossReturn === null ? '当前缺少可靠盈亏数据' : `浮动收益 ${(grossReturn * 100).toFixed(1)}%`,
      ...baseDecision.reasons.slice(0, 2),
    ],
    baseDecision.degraded,
    baseDecision.degradedReason,
  )
}

export function resetLiveV3SignalState(): void {
  liveV3Positions.clear()
  lastProcessedSlotKey = null
}

export function applyLiveV3SignalDecisions(stocks: any[]): any[] {
  syncTrackedPositions(stocks)

  for (const stock of stocks) {
    const code = getStockCode(stock)
    const tracked = code ? liveV3Positions.get(code) : undefined
    const decision = tracked
      ? evaluateTrackedPositionDecision(stock, tracked)
      : getBaseLiveV3SignalDecision(stock)

    stock.liveV3SignalDecision = decision

    if (tracked && decision.tone === 'sell') {
      liveV3Positions.delete(code)
      continue
    }

    if (!tracked && isEntryLabel(decision.label)) {
      registerLiveV3Position(stock, decision)
    }
  }

  return stocks
}

export function getLiveV3SignalDecision(stock: any): V3LiveSignalDecision {
  return (stock?.liveV3SignalDecision as V3LiveSignalDecision | undefined) ?? getBaseLiveV3SignalDecision(stock)
}
