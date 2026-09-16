import { dataLayer } from '@/services/DataLayer'
import { buildFusionStrategyProjection } from '@/services/rankTrend/FusionStrategyProjector'
import type { FusionSnapshotType, FusionStrategyProjection } from '@/types/fusionStrategyProjection'
import { candidateJournalService } from './CandidateJournalService'
import type { CandidateJournalEntry } from './types'

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function normalizeSnapshotType(value: unknown): FusionSnapshotType {
  return value === 'quarter_hour' ? 'quarter_hour' : 'half_hour'
}

function buildFrameTime(tradingDate: string, slotTime: string, fallback: string): string {
  if (tradingDate && slotTime) return `${tradingDate}T${slotTime}:00+08:00`
  return fallback || ''
}

/** 候选行的 rankTrend 取源（与投影同规则）：auto 触发用冻结快照，其余用 live 股票。 */
export function resolveCandidateRankTrendSource(
  entry: CandidateJournalEntry,
  liveStockInput?: Record<string, any> | null,
): Record<string, any> | null {
  const stockCode = normalizeCode(entry.stockCode)
  const liveStock = liveStockInput || (dataLayer.getStock(stockCode) as Record<string, any> | undefined) || {}
  return resolveFrozenRankTrendSnapshot(entry) || liveStock.rankTrend || null
}

function resolveFrozenRankTrendSnapshot(entry: CandidateJournalEntry): Record<string, any> | null {
  const triggerMeta = (entry.signalsSnapshot?.triggerMeta as Record<string, any> | undefined) || {}
  const snapshotRankTrend = (entry.signalsSnapshot?.rankTrend as Record<string, any> | undefined) || null
  return triggerMeta.triggerType === 'auto' && snapshotRankTrend ? snapshotRankTrend : null
}

export function buildCandidateJournalProjection(
  entry: CandidateJournalEntry,
  liveStockInput?: Record<string, any> | null,
): FusionStrategyProjection {
  const stockCode = normalizeCode(entry.stockCode)
  const liveStock = liveStockInput || (dataLayer.getStock(stockCode) as Record<string, any> | undefined) || {}
  const snapshotQuote = (entry.signalsSnapshot?.quote as Record<string, any> | undefined) || {}
  const snapshotRankTrend = (entry.signalsSnapshot?.rankTrend as Record<string, any> | undefined) || {}
  const frozenRankTrend = resolveFrozenRankTrendSnapshot(entry)
  const stock = {
    ...snapshotQuote,
    ...liveStock,
    code: stockCode,
    name: entry.stockName || stockCode,
    rankTrend: frozenRankTrend || liveStock.rankTrend || null,
  }
  const sampleQuality = stock.rankTrend?.meta?.sampleQuality || {}
  const snapshotType = normalizeSnapshotType(sampleQuality.snapshotType)
  const tradingDate = String(sampleQuality.latestTradingDate || '')
  const slotTime = String(sampleQuality.latestSlotTime || '')
  const frameTime = buildFrameTime(tradingDate, slotTime, entry.updatedAt || entry.createdAt || '')
  const strategyLifecycle =
    stock.rankTrend?.strategyLifecycle ||
    stock.rankTrend?.lifecycle ||
    snapshotRankTrend.strategyLifecycle ||
    snapshotRankTrend.lifecycle ||
    null

  return buildFusionStrategyProjection({
    stock,
    snapshotType,
    tradingDate,
    snapshotId: tradingDate && slotTime ? `${snapshotType}:${tradingDate}:${slotTime}` : `${snapshotType}:${entry.id}`,
    frameTime,
    strategyLifecycle,
    executionOverlay: candidateJournalService.toExecutionOverlay(entry),
  })
}
