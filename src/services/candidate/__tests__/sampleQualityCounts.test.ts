import { describe, expect, it } from 'vitest'
import { summarizeSampleQuality } from '../sampleQualityCounts'

describe('summarizeSampleQuality', () => {
  it('按 status 计数 insufficient / degraded / ok', () => {
    const summary = summarizeSampleQuality([
      { meta: { sampleQuality: { status: 'ok' } } },
      { meta: { sampleQuality: { status: 'degraded' } } },
      { meta: { sampleQuality: { status: 'degraded' } } },
      { meta: { sampleQuality: { status: 'insufficient' } } },
      { meta: { sampleQuality: { status: 'ok' } } },
    ])
    expect(summary).toEqual({ total: 5, ok: 2, degraded: 2, insufficient: 1, issues: 3 })
  })

  it('缺 rankTrend / 缺 status 的条目计入 total 但不打问题标（不伪造质量结论）', () => {
    const summary = summarizeSampleQuality([null, { meta: {} }, undefined])
    expect(summary).toEqual({ total: 3, ok: 0, degraded: 0, insufficient: 0, issues: 0 })
  })
})
