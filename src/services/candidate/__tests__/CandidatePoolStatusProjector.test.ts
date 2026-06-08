import { describe, expect, it } from 'vitest'

import { projectCandidatePoolStatus } from '../CandidatePoolStatusProjector'

describe('CandidatePoolStatusProjector', () => {
  it('maps candidate pool entries back to table-friendly status labels', () => {
    const stocks = [
      { code: '600001', name: '甲' },
      { code: '600002', name: '乙' },
    ]

    const entries = [
      { stockCode: '600001', status: 'triggered', id: 'entry-1' },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], entries as any[])

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'triggered',
      candidatePoolLabel: '已触发',
      candidatePoolEntryId: 'entry-1',
    })
    expect(result[1]).toMatchObject({
      candidatePoolStatus: 'none',
      candidatePoolLabel: '未入池',
      candidatePoolEntryId: '',
    })
  })

  it('prefers open candidate status over older reviewed history for the same stock', () => {
    const stocks = [{ code: '600001', name: '甲' }]
    const entries = [
      { stockCode: '600001', status: 'triggered', id: 'entry-open' },
      { stockCode: '600001', status: 'reviewed', id: 'entry-old' },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], entries as any[])

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'triggered',
      candidatePoolLabel: '已触发',
      candidatePoolEntryId: 'entry-open',
    })
  })
})
