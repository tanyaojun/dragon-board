import type { SnapshotCoverageBucket, SnapshotCoverageReport } from './types'
import {
  getRankTrendSnapshotLabel,
  getRankTrendSnapshotShortLabel,
  type RankTrendSnapshotType,
} from '../../types/rankTrendDefaults'

type SnapshotCoverageKey = keyof SnapshotCoverageReport
type SnapshotCoverageMetaItem = {
  key: SnapshotCoverageKey
  type: RankTrendSnapshotType
}

const SNAPSHOT_COVERAGE_META: SnapshotCoverageMetaItem[] = [
  { key: 'quarterHour', type: 'quarter_hour' },
  { key: 'halfHour', type: 'half_hour' },
  { key: 'hourly', type: 'hourly' },
  { key: 'daily', type: 'daily' },
]

export function getSnapshotCoverageEntries(report: SnapshotCoverageReport) {
  return SNAPSHOT_COVERAGE_META.map((meta) => ({
    ...meta,
    label: getRankTrendSnapshotLabel(meta.type),
    shortLabel: getRankTrendSnapshotShortLabel(meta.type),
    bucket: report[meta.key],
  }))
}

export function deriveSnapshotCoverageSeverity(
  report: SnapshotCoverageReport | null | undefined,
): 'ok' | 'warn' | 'danger' {
  if (!report) return 'warn'

  // severity 是给 UI 和摘要层用的粗粒度信号，不等价于 requireCoverage 的严格过滤语义。
  const entries = getSnapshotCoverageEntries(report)
  const missingCount = entries.reduce((sum, item) => sum + item.bucket.missing.length, 0)
  const malformedCount = entries.reduce((sum, item) => sum + item.bucket.malformed.length, 0)
  const delayedCount = entries.reduce((sum, item) => sum + item.bucket.delayed.length, 0)
  const restoredCount = entries.reduce((sum, item) => sum + item.bucket.restored.length, 0)

  if (malformedCount > 0 || missingCount > 2) return 'danger'
  if (missingCount > 0 || delayedCount > 0 || restoredCount > 0) return 'warn'
  return 'ok'
}

export function formatSnapshotCoverageSummary(report: SnapshotCoverageReport): string {
  const coverageParts = getSnapshotCoverageEntries(report).map(
    ({ shortLabel, bucket }) => `${shortLabel} ${bucket.actual.length}/${bucket.expected.length}`,
  )
  const delayedCount = getSnapshotCoverageEntries(report).reduce((sum, item) => sum + item.bucket.delayed.length, 0)
  const restoredCount = getSnapshotCoverageEntries(report).reduce(
    (sum, item) => sum + item.bucket.restored.length,
    0,
  )

  const extraParts = [
    ...(delayedCount > 0 ? [`延迟 ${delayedCount}`] : []),
    ...(restoredCount > 0 ? [`恢复 ${restoredCount}`] : []),
  ]

  return [...coverageParts, ...extraParts].join(' · ')
}

function formatSlots(label: string, bucket: SnapshotCoverageBucket, key: 'missing' | 'malformed'): string | null {
  const values = bucket[key]
  if (values.length === 0) return null
  return `${label}${key === 'missing' ? '缺口' : '异常槽位'}: ${values.join(', ')}`
}

export function buildSnapshotCoverageWarnings(report: SnapshotCoverageReport): string[] {
  // 这里生成的是解释型文案，方便诊断层复用；正式读取是否放行仍由 runtime 的 coverage 过滤决定。
  const warnings: string[] = []
  const missingIntradayParts: string[] = []
  const malformedParts: string[] = []
  const missingDailyParts: string[] = []

  getSnapshotCoverageEntries(report).forEach(({ key, shortLabel, bucket }) => {
    const missingText = formatSlots(shortLabel, bucket, 'missing')
    const malformedText = formatSlots(shortLabel, bucket, 'malformed')

    if (missingText) {
      if (key === 'daily') {
        missingDailyParts.push(missingText)
      } else {
        missingIntradayParts.push(missingText)
      }
    }
    if (malformedText) malformedParts.push(malformedText)
  })

  if (missingIntradayParts.length > 0) {
    warnings.push(`日内快照缺口: ${missingIntradayParts.join('；')}`)
  }
  if (missingDailyParts.length > 0) {
    warnings.push(`日级快照缺口: ${missingDailyParts.join('；')}`)
  }
  if (malformedParts.length > 0) {
    warnings.push(`快照槽位异常: ${malformedParts.join('；')}`)
  }

  return warnings
}
