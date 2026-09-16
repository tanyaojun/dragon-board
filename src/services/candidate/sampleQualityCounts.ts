// src/services/candidate/sampleQualityCounts.ts
// 候选池样本质量汇总（2026-09-16 P1-3）：统计 rankTrend.meta.sampleQuality.status 分布，
// 供池顶栏「样本不足 N · 降级 M」计数与点击过滤。缺 rankTrend/缺 status 的条目计入 total
// 但不打问题标（fail-visible：质量未知 ≠ 质量问题，也不伪装成 ok）。
export interface SampleQualitySummary {
  total: number
  ok: number
  degraded: number
  insufficient: number
  /** degraded + insufficient（质量未知不算问题） */
  issues: number
}

type RankTrendLike = { meta?: { sampleQuality?: { status?: string } } } | null | undefined

export function summarizeSampleQuality(records: Array<RankTrendLike>): SampleQualitySummary {
  const summary: SampleQualitySummary = { total: 0, ok: 0, degraded: 0, insufficient: 0, issues: 0 }
  for (const record of records) {
    summary.total += 1
    const status = record?.meta?.sampleQuality?.status
    if (status === 'ok') summary.ok += 1
    else if (status === 'degraded') summary.degraded += 1
    else if (status === 'insufficient') summary.insufficient += 1
  }
  summary.issues = summary.degraded + summary.insufficient
  return summary
}

export function hasSampleQualityIssue(record: RankTrendLike): boolean {
  const status = record?.meta?.sampleQuality?.status
  return status === 'degraded' || status === 'insufficient'
}
