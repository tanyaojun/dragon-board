// src/services/dataLoader/framePoolSource.ts
// 行情列表池帧源（2026-09-21 池源替换）：读取后端最新 half_hour 帧池作为
// 前端列表 membership 的事实源。复用既有 snapshotBackendRead 正式读通道，
// 不新增后端 API；任何失败返回结构化 null（fail-visible，不抛异常打断加载链）。
import type { MergedStock } from '@/types'
import { FRAME_POOL_ROW_LIMIT } from '@/config/listPool'
import { snapshotBackendRead } from '../snapshot/backendRead'
import { toLocalTradingDate } from '../snapshot/identity'
import type { SnapshotStockRow } from '../snapshot/types'
import { createEmptyMergedStock } from './StockMergeCoordinator'

export interface FramePoolSnapshot {
  codes: Set<string>
  slotTime: string
  tradingDate: string
  rowsByCode: Map<string, SnapshotStockRow>
}

export type FramePoolUnavailableReason = 'http-error' | 'no-frame' | 'empty-rows' | 'mode-disabled'

export interface FramePoolFetchResult {
  pool: FramePoolSnapshot | null
  reason?: FramePoolUnavailableReason
  message?: string
}

/** 读取当日最新 half_hour 帧的全量股票行；两步读取（先帧后行），失败逐级结构化降级 */
export async function fetchLatestFramePool(
  options: { tradingDate?: string } = {},
): Promise<FramePoolFetchResult> {
  const tradingDate = options.tradingDate || toLocalTradingDate(new Date())
  try {
    const frames = await snapshotBackendRead.listSnapshotFrames({
      type: 'half_hour',
      tradingDate,
      sort: 'desc',
      limit: 1,
    })
    const frame = frames[0]
    if (!frame?.slotTime) {
      return { pool: null, reason: 'no-frame', message: `当日(${tradingDate})无 half_hour 帧` }
    }

    const rows = await snapshotBackendRead.listSnapshotStockRows({
      type: 'half_hour',
      tradingDate,
      slotTime: frame.slotTime,
      sort: 'asc',
      limit: FRAME_POOL_ROW_LIMIT,
    })
    const rowsByCode = new Map<string, SnapshotStockRow>()
    for (const row of rows || []) {
      const code = String(row?.code || '')
      if (code && !rowsByCode.has(code)) rowsByCode.set(code, row)
    }
    if (!rowsByCode.size) {
      return {
        pool: null,
        reason: 'empty-rows',
        message: `帧 ${tradingDate} ${frame.slotTime} 无有效股票行`,
      }
    }
    return { pool: { codes: new Set(rowsByCode.keys()), slotTime: frame.slotTime, tradingDate, rowsByCode } }
  } catch (error) {
    return {
      pool: null,
      reason: 'http-error',
      message: error instanceof Error ? error.message : String(error),
    }
  }
}

function toFiniteNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/**
 * 帧行 → 种子行：名称与快照时点行情为兜底值（实时行情到达后被覆盖）；
 * 排名字段直接透传后端 golden（2026-09-21 口径唯一化裁决 A，
 * spec: docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md），
 * 前端零排名计算；前端 rank 语义 := 后端 compRank（compScore 降序 + code 稳定序）。
 */
export function buildFrameSeedStock(row: SnapshotStockRow): MergedStock {
  const stock = createEmptyMergedStock(String(row?.code || ''))
  const seedName = String(row?.name || '').trim()
  if (seedName && seedName !== '-') {
    stock.name = seedName
    stock.platformName = seedName
  }
  const price = toFiniteNumber(row?.price)
  if (price !== null && price > 0) stock.price = price
  const change = toFiniteNumber(row?.change)
  if (change !== null) stock.change = change
  const volume = toFiniteNumber(row?.volume)
  if (volume !== null && volume > 0) stock.volume = volume
  const turnoverRate = toFiniteNumber(row?.turnoverRate)
  if (turnoverRate !== null && turnoverRate > 0) stock.turnoverRate = turnoverRate

  // golden 排名字段逐位透传，缺失不伪造（保持 createEmptyMergedStock 占位语义）
  const avgRankNum = toFiniteNumber(row?.avgRankNum)
  if (avgRankNum !== null) {
    stock.avgRankNum = avgRankNum
    stock.avgRank = row?.avgRank ?? avgRankNum.toFixed(1)
  }
  if (toFiniteNumber(row?.platforms) !== null) stock.platforms = row.platforms
  const compRank = toFiniteNumber(row?.compRank)
  if (compRank !== null) {
    stock.compRank = compRank
    stock.rank = compRank
  }
  const compScore = toFiniteNumber(row?.compScore)
  if (compScore !== null) stock.compScore = compScore
  const fundPenetration = toFiniteNumber(row?.fundPenetration)
  if (fundPenetration !== null) stock.fundPenetration = fundPenetration
  if (Array.isArray(row?.qualityFlags)) stock.qualityFlags = [...row.qualityFlags]
  if (Array.isArray(row?.missingFields)) stock.missingFields = [...row.missingFields]
  return stock
}

/** 帧池模式下 platformData 行过滤到帧池范围；空平台不保留键（platformTotals 由后端帧内计算） */
export function filterPlatformDataToCodes(
  platformData: Record<string, any[]>,
  codes: Set<string>,
): Record<string, any[]> {
  const filtered: Record<string, any[]> = {}
  for (const [platform, rows] of Object.entries(platformData || {})) {
    if (!Array.isArray(rows)) {
      filtered[platform] = rows
      continue
    }
    const kept = rows.filter((row) => codes.has(String(row?.code || '')))
    if (kept.length) filtered[platform] = kept
  }
  return filtered
}
