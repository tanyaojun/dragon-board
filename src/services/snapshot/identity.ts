import type {
  SnapshotCaptureMode,
  SnapshotQualityMetadata,
  SnapshotRecord,
  SnapshotSource,
  SnapshotType,
} from './types'
import {
  getRankTrendSnapshotLabel,
  RANK_TREND_SNAPSHOT_TYPES,
  type RankTrendSnapshotType,
} from '../../types/rankTrendDefaults'

const RANK_TREND_SNAPSHOT_LABELS = Object.fromEntries(
  RANK_TREND_SNAPSHOT_TYPES.map((type) => [type, getRankTrendSnapshotLabel(type)]),
) as Record<RankTrendSnapshotType, string>

export const SNAPSHOT_TYPE_LABELS: Record<SnapshotType, string> = {
  ...RANK_TREND_SNAPSHOT_LABELS,
  five_minute: '5分钟快照',
}

export function padTimeSegment(value: number): string {
  return String(value).padStart(2, '0')
}

export function toLocalTradingDate(date: Date): string {
  return `${date.getFullYear()}-${padTimeSegment(date.getMonth() + 1)}-${padTimeSegment(date.getDate())}`
}

export function toLocalSlotTime(date: Date): string {
  return `${padTimeSegment(date.getHours())}:${padTimeSegment(date.getMinutes())}`
}

export function buildSnapshotDisplayKey(type: SnapshotType, tradingDate: string, slotTime: string): string {
  const label = SNAPSHOT_TYPE_LABELS[type]
  if (type === 'daily') return `[${label}] ${tradingDate}`
  return `[${label}] ${tradingDate} ${slotTime}`
}

export function buildSnapshotId(type: SnapshotType, tradingDate: string, slotTime: string): string {
  return `${type}:${tradingDate}:${slotTime || 'close'}`
}

export function normalizeSnapshotSlotTime(type: SnapshotType, slotTime?: string): string {
  if (type === 'daily') return slotTime || '15:00'
  return slotTime || '00:00'
}

export function createSnapshotQualityMetadata(
  snapshotTime: Date,
  meta?: Partial<SnapshotQualityMetadata>,
): SnapshotQualityMetadata {
  // 质量元数据在落库时统一生成，后续正式读取、恢复判断都直接依赖这里的字段。
  const dataTimestamp = Number(meta?.dataTimestamp) > 0 ? Number(meta?.dataTimestamp) : snapshotTime.getTime()
  const capturedAt = Number(meta?.capturedAt) > 0 ? Number(meta?.capturedAt) : Date.now()
  const source = (meta?.source || 'browser_runtime') as SnapshotSource
  const captureMode = (meta?.captureMode || 'real_time') as SnapshotCaptureMode
  const delayMs =
    Number.isFinite(Number(meta?.delayMs)) && Number(meta?.delayMs) >= 0
      ? Number(meta?.delayMs)
      : Math.max(0, capturedAt - snapshotTime.getTime())
  const qualityFlags = Array.isArray(meta?.qualityFlags)
    ? Array.from(new Set(meta?.qualityFlags.filter((flag): flag is string => Boolean(flag))))
    : []

  return {
    captureMode,
    capturedAt,
    dataTimestamp,
    delayMs,
    qualityFlags,
    source,
  }
}

export function createSnapshotRecord<T = any>(
  type: SnapshotType,
  snapshotTime: Date,
  payload: T,
  meta?: Partial<SnapshotQualityMetadata>,
): SnapshotRecord<T> {
  const tradingDate = toLocalTradingDate(snapshotTime)
  const slotTime = normalizeSnapshotSlotTime(type, toLocalSlotTime(snapshotTime))
  const displayKey = buildSnapshotDisplayKey(type, tradingDate, slotTime)
  const timestamp = Number((payload as any)?.timestamp) || snapshotTime.getTime()
  const quality = createSnapshotQualityMetadata(snapshotTime, meta)

  return {
    id: buildSnapshotId(type, tradingDate, slotTime),
    type,
    tradingDate,
    slotTime,
    timestamp,
    displayKey,
    ...quality,
    payload,
  }
}

export function withSnapshotPayloadCompatFields<T = any>(record: SnapshotRecord<T>): SnapshotRecord<T> {
  const payload =
    record?.payload && typeof record.payload === 'object'
      ? {
          ...(record.payload as Record<string, unknown>),
          type: record.type,
          date: record.displayKey,
          timestamp: record.timestamp,
          tradingDate: record.tradingDate,
          slotTime: record.slotTime,
          displayKey: record.displayKey,
        }
      : record.payload

  return {
    ...record,
    payload: payload as T,
  }
}
