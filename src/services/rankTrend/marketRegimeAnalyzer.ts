import type { MarketRegimeAnalysis } from './types'
import { clamp } from './utils'

function toNumber(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function normalizeBreathPhase(value?: unknown): string {
  if (typeof value !== 'string') return ''
  const phase = value.trim()
  return phase.endsWith('期') ? phase.slice(0, -1) : phase
}

function resolveBreathPhase(breathData: any): string {
  return normalizeBreathPhase(
    breathData?.sentiment?.phaseName ??
      breathData?.sentiment?.phase ??
      breathData?.phaseName ??
      breathData?.phase,
  )
}

function resolveBreathPhaseAdjustment(phase: string): number {
  if (phase === '高潮') return 14
  if (phase === '发酵') return 8
  if (phase === '启动') return 0
  if (phase === '退潮') return -12
  if (phase === '冰点') return -16
  return 0
}

function resolveMarketData(breathData: any): Record<string, any> {
  return (breathData?.marketData && typeof breathData.marketData === 'object')
    ? breathData.marketData
    : breathData || {}
}

export function analyzeMarketRegime(input: {
  breathData?: any
  stocks?: any[]
}): MarketRegimeAnalysis {
  const marketData = resolveMarketData(input.breathData)
  const stocks = Array.isArray(input.stocks) ? input.stocks : []
  const breathPhase = resolveBreathPhase(input.breathData)
  const ztCount = toNumber(marketData.ztCount)
  const dtCount = toNumber(marketData.dtCount)
  const upCount = toNumber(marketData.upCount)
  const downCount = toNumber(marketData.downCount)
  const totalAmo = toNumber(marketData.totalAmo)
  const passRate = marketData.passRate || {}
  const to2Rate = toNumber(passRate.to2)
  const hotStockCount = stocks.length
  const positiveMoneyCount = stocks.filter((stock) => toNumber(stock?.zlje) > 0).length
  const moneyShare = hotStockCount > 0 ? positiveMoneyCount / hotStockCount : 0
  const highVolumeCount = stocks.filter((stock) => toNumber(stock?.volumeRatio) >= 1.2).length
  const highVolumeShare = hotStockCount > 0 ? highVolumeCount / hotStockCount : 0
  const upDownSpread = upCount + downCount > 0 ? (upCount - downCount) / (upCount + downCount) : 0

  let score = 50
  const reasons: string[] = []

  if (breathPhase) {
    score += resolveBreathPhaseAdjustment(breathPhase)
    reasons.push(`情绪阶段${breathPhase}`)
  }
  if (ztCount > 0) {
    score += clamp((ztCount - 35) * 0.35, -10, 16)
    reasons.push(`涨停${ztCount}`)
  }
  if (dtCount > 0) {
    score -= clamp(dtCount * 1.6, 0, 18)
    reasons.push(`跌停${dtCount}`)
  }
  if (upCount || downCount) {
    score += clamp(upDownSpread * 18, -18, 18)
    reasons.push(`涨跌扩散${(upDownSpread * 100).toFixed(0)}%`)
  }
  if (moneyShare > 0) {
    score += clamp((moneyShare - 0.5) * 20, -10, 10)
    reasons.push(`热榜资金正向${(moneyShare * 100).toFixed(0)}%`)
  }
  if (highVolumeShare > 0) {
    score += clamp((highVolumeShare - 0.35) * 10, -5, 7)
    reasons.push(`量能活跃${(highVolumeShare * 100).toFixed(0)}%`)
  }
  if (totalAmo > 0) {
    score += clamp((totalAmo / 1e12 - 0.8) * 8, -6, 8)
  }
  if (to2Rate > 0) {
    score += clamp((to2Rate - 35) * 0.15, -5, 6)
  }

  score = clamp(score, 0, 100)

  const state =
    score >= 72
      ? 'strong'
      : score >= 52
        ? 'normal'
        : score >= 35
          ? 'weak'
          : 'retreat'

  return {
    state,
    score: Number(score.toFixed(1)),
    reasons: reasons.length ? reasons : ['市场环境数据不足，按中性处理'],
  }
}
