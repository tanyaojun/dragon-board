import { describe, expect, it, vi, beforeEach } from 'vitest'

import { loadSnapshotAnalysis } from '../snapshotAnalysisReader'
import { apiService } from '../../apiService'

vi.mock('../../apiService', () => ({
  apiService: { getSnapshotAnalysis: vi.fn() },
}))

const mockedApi = apiService as unknown as { getSnapshotAnalysis: ReturnType<typeof vi.fn> }

describe('snapshotAnalysisReader (G4 读库)', () => {
  beforeEach(() => {
    mockedApi.getSnapshotAnalysis.mockReset()
  })

  it('reads persisted analysis and passes dataset/snapshot/codes', async () => {
    mockedApi.getSnapshotAnalysis.mockResolvedValue({
      ok: true,
      dataset_id: 'ds',
      snapshot_id: 's1',
      analysis: { '600000': { displayStatus: { label: '主升确认', classKey: 'main_confirmed' } } },
    })
    const result = await loadSnapshotAnalysis('ds', 's1', ['600000'])
    expect(result.ok).toBe(true)
    expect(result.analysis['600000'].displayStatus?.label).toBe('主升确认')
    expect(mockedApi.getSnapshotAnalysis).toHaveBeenCalledWith('ds', 's1', ['600000'])
  })

  it('fail-visible returns empty when backend unavailable', async () => {
    mockedApi.getSnapshotAnalysis.mockRejectedValue(new Error('offline'))
    const result = await loadSnapshotAnalysis('ds', 's1')
    expect(result.ok).toBe(false)
    expect(result.analysis).toEqual({})
  })
})
