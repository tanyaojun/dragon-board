import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = () =>
  readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'RankTrendObservationPanel.vue'),
    'utf8',
  )

describe('RankTrendObservationPanel', () => {
  it('renders a right-side three-track observation cockpit without candidate-pool content', () => {
    const panel = source()

    expect(panel).toContain('observation-drawer')
    expect(panel).toContain("{ id: 'resonance'")
    expect(panel).toContain("{ id: 'technical'")
    expect(panel).toContain("{ id: 'lifecycle'")
    expect(panel).toContain("activeTrack === 'resonance'")
    expect(panel).toContain("activeTrack === 'technical'")
    expect(panel).toContain("activeTrack === 'lifecycle'")
    expect(panel).toContain('共振路径')
    expect(panel).toContain('技术结构')
    expect(panel).toContain('阶段与风险')
    expect(panel).toContain('最近 9 帧')
    expect(panel).toContain("event.key === 'Escape'")
    expect(panel).toContain('function scoreText')
    expect(panel).toContain("return '--'")
    expect(panel).not.toContain('<small>/ 100</small>')
    expect(panel).toContain('width: percent(resonance?.relativeMomentum)')
    expect(panel).toContain('text: signedPercent(resonance?.relativeMomentum)')
    expect(panel).toContain("frame.issues.map((issue) => issue.message).join('；')")
    expect(panel).toContain('if (!macd) return []')
    expect(panel).not.toContain('Number(macd?.dif || 0)')
    expect(panel).not.toContain('Number(frame.analysis?.technical?.macd?.histogram || 0)')
    expect(panel).not.toContain('候选池')
  })
})
