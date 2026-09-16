// src/services/rankTrend/historyComparison.ts
// 历史回放对比（2026-09-16 P1-1）：个股「昨日同时点」状态对比。
// 数据链：frames 读口（前一交易日同时点帧，缺则回退当日收盘帧）→
// /api/snapshots/analysis（loadSnapshotAnalysis facade，历史 analyze 产物首次接入盘面）。
// fail-visible：任何缺失（新上榜股/帧缺失/读库失败）返回 null，由调用方显示占位，不伪造。
import { loadSnapshotAnalysis } from '@/services/snapshot/snapshotAnalysisReader'
import { apiService } from '@/services/apiService'
import type { SnapshotAnalysisEntry } from '@/services/apiService'

export interface HistoryFrameRef {
  snapshotId: string
  tradingDate: string
  slotTime: string
}

export interface HistoryComparisonCurrent {
  /** 当前 displayStatus 展示词（如「冷却」） */
  stageLabel: string
  /** 当前候选分层键（如 N_NEUTRAL） */
  tier: string
  /** 当前最终信号（buy/sell/hold 原值） */
  signal: string
}

export interface HistoryComparisonView {
  tradingDate: string
  slotTime: string
  stageLabel: string
  tier: string
  signal: string
  transition?: string
  /** 状态或分层较当前发生变化 */
  changed: boolean
}

/** 从降序帧列表中选前一交易日参考帧：优先同时点，缺失回退当日最新帧（收盘 15:00）。 */
export function pickPreviousFrame(
  framesDesc: HistoryFrameRef[],
  slotTime: string,
): HistoryFrameRef | null {
  if (!framesDesc.length) return null
  const prevDate = String(framesDesc[0]?.tradingDate || '')
  const sameSlot = framesDesc.find(
    (frame) => frame.tradingDate === prevDate && frame.slotTime === slotTime,
  )
  return sameSlot ?? framesDesc[0]
}

export function buildHistoryComparisonView(
  prev: SnapshotAnalysisEntry | undefined,
  current: HistoryComparisonCurrent,
): HistoryComparisonView | null {
  if (!prev) return null
  const stageLabel = String(prev.displayStatus?.label || '')
  const tier = String(prev.strategy?.candidateTier || '')
  const signal = String(prev.decision?.final?.signal || '')
  const meta = prev.meta || {}
  if (!stageLabel && !tier && !signal) return null
  return {
    tradingDate: String(meta.latestTradingDate || ''),
    slotTime: String(meta.latestSlotTime || ''),
    stageLabel: stageLabel || '--',
    tier: tier || '--',
    signal: signal || '--',
    transition: typeof prev.cycle?.transition === 'string' ? prev.cycle.transition : undefined,
    changed: (stageLabel || '--') !== current.stageLabel || (tier || '--') !== current.tier,
  }
}

export interface HistoryComparisonLoadParams {
  datasetId?: string
  snapshotType: string
  /** 当前帧所属交易日（不含当日，取其之前） */
  tradingDate: string
  slotTime: string
  code: string
}

export interface HistoryComparisonLoaded {
  tradingDate: string
  slotTime: string
  entry: SnapshotAnalysisEntry
}

export async function loadHistoryComparisonEntry(
  params: HistoryComparisonLoadParams,
): Promise<HistoryComparisonLoaded | null> {
  const datasetId = params.datasetId || 'dragonboard_live'
  try {
    const response = await apiService.listMongoSnapshotFrames({
      type: params.snapshotType as 'half_hour',
      beforeTradingDate: params.tradingDate,
      sort: 'desc',
      limit: 40,
      fields: ['snapshotId', 'tradingDate', 'slotTime'],
    })
    const frames = (Array.isArray(response?.frames) ? response.frames : []) as HistoryFrameRef[]
    const prevFrame = pickPreviousFrame(frames, params.slotTime)
    if (!prevFrame?.snapshotId) return null
    const result = await loadSnapshotAnalysis(datasetId, prevFrame.snapshotId, [params.code])
    const entry = result.ok ? result.analysis[params.code] : undefined
    if (!entry) return null
    return {
      tradingDate: prevFrame.tradingDate,
      slotTime: prevFrame.slotTime,
      entry,
    }
  } catch {
    return null
  }
}
