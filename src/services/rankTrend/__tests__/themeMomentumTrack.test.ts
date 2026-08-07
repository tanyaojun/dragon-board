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

  it('removes theme as the fourth track with index 04', () => {
    expect(panel).not.toContain("{ id: 'theme', index: '04', label: '题材动量' }")
  })

  it('removes theme window from OBSERVATION_WINDOW_BARS', () => {
    expect(service).not.toContain('theme: 15')
  })

  it('does not render analysis.themeMomentum in observation panel', () => {
    expect(panel).not.toContain('selectedAnalysis?.themeMomentum')
    expect(panel).not.toContain('themeMomentum')
  })

  it('does not read resonance.theme for theme momentum anymore', () => {
    expect(panel).not.toContain('resonance?.theme?.themeMomentumScore')
  })
})
