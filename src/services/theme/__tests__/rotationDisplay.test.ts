import { describe, expect, it } from 'vitest'
import { countRotationStates, marketPhaseLabel, rotationStateLabel } from '../rotationDisplay'

describe('marketPhaseLabel', () => {
  it('maps known phases to Chinese labels', () => {
    expect(marketPhaseLabel('cooling')).toBe('退潮')
    expect(marketPhaseLabel('climax')).toBe('高潮')
    expect(marketPhaseLabel('rising')).toBe('升温')
    expect(marketPhaseLabel('ice')).toBe('冰点')
    expect(marketPhaseLabel('chaos')).toBe('混沌')
    expect(marketPhaseLabel('neutral')).toBe('中性')
  })

  it('falls back for unknown and missing phases without crashing', () => {
    expect(marketPhaseLabel('new_phase')).toBe('new_phase')
    expect(marketPhaseLabel(null)).toBe('未知')
    expect(marketPhaseLabel('')).toBe('未知')
  })
})

describe('rotationStateLabel', () => {
  it('maps known states and passes unknown through', () => {
    expect(rotationStateLabel('mainline')).toBe('主线')
    expect(rotationStateLabel('inflow')).toBe('流入')
    expect(rotationStateLabel('outflow')).toBe('流出')
    expect(rotationStateLabel('emerging')).toBe('萌发')
    expect(rotationStateLabel('neutral')).toBe('中性')
    expect(rotationStateLabel('cooling')).toBe('退潮')
    expect(rotationStateLabel('new_state')).toBe('new_state')
    expect(rotationStateLabel(null)).toBe('—')
  })
})

describe('countRotationStates', () => {
  it('counts by state with null as unknown and sorts descending', () => {
    const rows = [
      { rotationState: 'inflow' },
      { rotationState: 'inflow' },
      { rotationState: 'outflow' },
      { rotationState: null },
    ]
    expect(countRotationStates(rows)).toEqual([
      { state: 'inflow', count: 2 },
      { state: 'outflow', count: 1 },
      { state: 'unknown', count: 1 },
    ])
  })

  it('returns empty for empty statuses', () => {
    expect(countRotationStates([])).toEqual([])
  })
})
