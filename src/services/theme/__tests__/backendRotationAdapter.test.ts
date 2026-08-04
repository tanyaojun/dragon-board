import { describe, expect, it } from 'vitest'
import { mapBackendRotationSummary } from '../backendRotationAdapter'

describe('mapBackendRotationSummary', () => {
  it('maps rising phase with mainlines', () => {
    const mapped = mapBackendRotationSummary({
      marketPhase: 'rising',
      rotationSpeed: 42,
      mainlineConcentration: 0.36,
      maxBoardHeight: 8,
      mainLines: [{ themeId: 'BKAI', themeName: '人工智能', rotationScore: 78 }],
      inflowThemes: ['BKAG'],
      outflowThemes: [],
      suggestion: '主线上升期',
      algorithmVersion: 'theme_rotation_v2',
    })
    expect(mapped?.marketPhase).toBe('rising')
    expect(mapped?.mainLines[0].themeName).toBe('人工智能')
    expect(mapped?.algorithmVersion).toBe('theme_rotation_v2')
  })

  it('returns null for empty backend payload', () => {
    expect(mapBackendRotationSummary(null)).toBeNull()
    expect(mapBackendRotationSummary({})).toBeNull() // 无 algorithmVersion 视为非引擎产出（H3）
  })
})
