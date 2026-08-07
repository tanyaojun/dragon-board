import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('RankTrendObservationPanel theme momentum track', () => {
  const panel = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'RankTrendObservationPanel.vue'),
    'utf8',
  )
  const service = readFileSync(
    join(process.cwd(), 'src', 'services', 'rankTrend', 'RankTrendObservationService.ts'),
    'utf8',
  )

  it('adds theme as the fourth track with index 04', () => {
    expect(panel).toContain("{ id: 'theme', index: '04', label: '题材动量' }")
  })

  it('adds theme window to OBSERVATION_WINDOW_BARS', () => {
    expect(service).toContain('theme: 15')
  })

  it('renders analysis.themeMomentum with score/direction/phaseLabel', () => {
    expect(panel).toContain('selectedAnalysis?.themeMomentum')
    expect(panel).toContain('phaseLabel')
  })

  it('does not read resonance.theme for theme momentum anymore', () => {
    expect(panel).not.toContain('resonance?.theme?.themeMomentumScore')
  })
})
