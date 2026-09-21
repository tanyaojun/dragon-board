// src/services/dataLoader/framePoolSource.ts
// 行情列表池帧源（2026-09-21 池源替换）：读取后端最新 half_hour 帧池作为
// 前端列表 membership 的事实源。复用既有 snapshotBackendRead 正式读通道，
// 不新增后端 API；任何失败返回结构化 null（fail-visible，不抛异常打断加载链）。
import type { MergedStock } from '@/types'
import { FRAME_POOL_ROW_LIMIT } from '@/config/listPool'
import { snapshotBackendRead } from '../snapshot/backendRead'
import { toLocalTradingDate } from '../snapshot/identity'
import type { SnapshotStockRow } from '../snapshot/types'
import { isRankTrendAnalysisResult } from '../rankTrend/compat'
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

/** golden 回退帧最大回看自然日数（覆盖常规假期；再往前属冷数据，如实放弃） */
const GOLDEN_FRAME_LOOKBACK_DAYS = 7

/**
 * 跨帧回溯请求的字段投影（code review M2）：回溯行的消费面只有 applyGoldenFields
 * 的 golden 排名字段子集 + 行级 analysis 回填（后端注入与 fields 过滤独立执行）。
 * code/snapshotId 是匹配键必须携带；不投影则数百 missing codes × 多帧 × 完整
 * analyze 产物的响应可达数十 MB，且串行阻塞首屏发布。
 */
const GOLDEN_BACKTRACK_FIELDS = [
  'code',
  'snapshotId',
  'compRank',
  'compScore',
  'avgRankNum',
  'avgRank',
  'platforms',
  'fundPenetration',
  'qualityFlags',
  'missingFields',
]

export interface GoldenFrameRows {
  rowsByCode: Map<string, SnapshotStockRow>
  tradingDate: string
  slotTime: string
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
      // 附带后端 snapshot_analysis 帧内 analyze 产物（2026-09-21）：观察六列
      // （共振/趋势/热度/量价/周期/五维）随种子行首屏同步投影，不等异步 signal 增强；
      // 缺产物行如实无值，不构成读取门禁。
      includeAnalysis: true,
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

/**
 * 最近可用帧的全量行（2026-09-22 凌晨/开盘前空窗修复）：当日无 half_hour 帧时
 * 向前回退最多 GOLDEN_FRAME_LOOKBACK_DAYS 个自然日取最新帧行（含帧内 analyze 产物）。
 *
 * **只用于降级链（热榜合并池）的 golden 排名与 analysis 投影，不参与 membership**：
 * 帧池 membership 仍按当日帧（fetchLatestFramePool），热榜合并池 membership 保持实时。
 * 帧行透传的 compRank/avgRankNum 是该时段唯一可用的后端 golden（口径唯一化后前端
 * 不再本地重算），滞后帧如实由 provenance 的 tradingDate/slotTime 打标。
 * 全部交易日无帧/查询失败返回结构化 null（fail-visible，不抛异常打断加载链）。
 */
export async function fetchLatestGoldenFrameRows(
  options: { tradingDate?: string } = {},
): Promise<GoldenFrameRows | null> {
  const startDate = options.tradingDate || toLocalTradingDate(new Date())
  const baseDay = new Date(`${startDate}T00:00:00`)
  for (let offset = 0; offset < GOLDEN_FRAME_LOOKBACK_DAYS; offset++) {
    const day = new Date(baseDay)
    day.setDate(day.getDate() - offset)
    const tradingDate = toLocalTradingDate(day)
    try {
      const frames = await snapshotBackendRead.listSnapshotFrames({
        type: 'half_hour',
        tradingDate,
        sort: 'desc',
        limit: 1,
      })
      const frame = frames[0]
      if (!frame?.slotTime) continue
      const rows = await snapshotBackendRead.listSnapshotStockRows({
        type: 'half_hour',
        tradingDate,
        slotTime: frame.slotTime,
        sort: 'asc',
        limit: FRAME_POOL_ROW_LIMIT,
        includeAnalysis: true,
      })
      const rowsByCode = new Map<string, SnapshotStockRow>()
      for (const row of rows || []) {
        const code = String(row?.code || '')
        if (code && !rowsByCode.has(code)) rowsByCode.set(code, row)
      }
      if (rowsByCode.size) {
        return { rowsByCode, tradingDate, slotTime: frame.slotTime }
      }
    } catch (error) {
      // fail-visible（review M3）：单日失败不中断回退，但保留诊断线索
      console.warn(`[framePoolSource] golden 回退帧查询失败 ${tradingDate}:`, error)
    }
  }
  return null
}

/**
 * 指定股票在 ``tradingDate`` 当日的 golden 帧行回溯（2026-09-22 空窗修复第二段）：
 * 最新帧不在池、但当日更早帧入过池的股票（盘中上过榜、收盘帧掉出），按 code 跨帧
 * 取**最近一次入池帧**的行（含帧内 analyze 产物）。请求一次（codes + trading_date
 * 跨帧查询），``sort=desc`` 时每 code 首次出现的行即最近帧行。
 * 与 fetchLatestGoldenFrameRows 同口径：只做降级链投影，不参与 membership；
 * 全天从未入池的 code 无行返回，如实缺省（fail-visible，不伪造）。
 */
export async function fetchGoldenRowsForCodes(
  codes: string[],
  options: { tradingDate?: string } = {},
): Promise<Map<string, SnapshotStockRow> | null> {
  const wanted = Array.from(new Set((codes || []).map((code) => String(code || '').trim()).filter(Boolean)))
  if (!wanted.length) return null
  const tradingDate = options.tradingDate || toLocalTradingDate(new Date())
    try {
      const rows = await snapshotBackendRead.listSnapshotStockRows({
        type: 'half_hour',
        tradingDate,
        codes: wanted,
        sort: 'desc',
        limit: Math.max(wanted.length * 12, FRAME_POOL_ROW_LIMIT),
        includeAnalysis: true,
        // 体积投影（review M2）：只取 golden 字段子集，analysis 由后端独立注入
        fields: [...GOLDEN_BACKTRACK_FIELDS],
      })
    const rowsByCode = new Map<string, SnapshotStockRow>()
    for (const row of rows || []) {
      const code = String(row?.code || '')
      if (code && !rowsByCode.has(code)) rowsByCode.set(code, row)
    }
    return rowsByCode.size ? rowsByCode : null
  } catch {
    // 回溯失败不影响主投影：调用方保留最新帧结果，结构化降级
    return null
  }
}

function toFiniteNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** golden 排名字段子集（前端消费后端 golden 的唯一字段清单；种子与既有行刷新共用，防两处漂移） */
function applyGoldenFields(stock: MergedStock, row: SnapshotStockRow): void {
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
}

/**
 * 帧行 → 种子行：名称与快照时点行情为兜底值（实时行情到达后被覆盖）；
 * 排名字段直接透传后端 golden（2026-09-21 口径唯一化裁决 A，
 * spec: docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md），
 * 前端零排名计算；前端 rank 语义 := 后端 compRank（compScore 降序 + code 稳定序）。
 *
 * 2026-09-21 首屏同步观察六列：种子行同时挂上帧内 analyze 产物（row.analysis，
 * 仅种子阶段；applyGoldenFieldsToMerged 不回写，避免旧帧行回滚 signal 增强的实时值）。
 * 形状不符（isRankTrendAnalysisResult 不过）不挂载，观察列如实显示 "--"。
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

  applyGoldenFields(stock, row)
  if (isRankTrendAnalysisResult(row?.analysis)) {
    stock.rankTrend = row.analysis
  }
  return stock
}

/**
 * 帧池模式下用最新帧行刷新既有行的 golden 排名字段子集（审查 C1 修复，2026-09-21）：
 * 种子只补缺失会让 golden 冻结在首次入池帧、降级恢复后不回填；每轮 merge 后统一刷新，
 * 保证「排名帧内滞后 ≤30min」的裁决口径成立。只动 golden 字段，name/price 等
 * 实时字段不受帧行覆盖；不在帧池中的行不触碰。
 *
 * 2026-09-22 降级链观察列投影：行无 rankTrend 且帧行带合法 analyze 产物（row.analysis，
 * include_analysis 读口附带）时回填帧内分析，供共振/趋势/热度/量价/周期/五维在
 * 降级/空窗时段首屏可显示；已有 rankTrend（种子行或 signal 增强写入）一律不回滚，
 * 形状不符不挂载，不伪造。
 */
export function applyGoldenFieldsToMerged(
  stocks: MergedStock[],
  rowsByCode: Map<string, SnapshotStockRow>,
): void {
  for (const stock of stocks || []) {
    const row = rowsByCode?.get(String(stock?.code || ''))
    if (!row) continue
    applyGoldenFields(stock, row)
    if (!stock.rankTrend && isRankTrendAnalysisResult(row?.analysis)) {
      stock.rankTrend = row.analysis
    }
  }
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
