import { describe, expect, it } from 'vitest'
import { buildThemeResearchExplanation } from '../themeResearchSummary'

describe('themeResearchSummary', () => {
  it('builds unavailable explanation without blocking runtime themeFacade flow', () => {
    const explanation = buildThemeResearchExplanation({ available: false, reason: 'backend unavailable' })

    expect(explanation.available).toBe(false)
    expect(explanation.statusText).toContain('研究摘要不可用')
    expect(explanation.mainlineText).toContain('themeFacade')
    expect(explanation.warnings).toContain('quantboard_research_unavailable')
  })

  it('builds leader and hotlist explanations from available ThemeTrend summary', () => {
    const explanation = buildThemeResearchExplanation({
      available: true,
      researchGrade: 'research_ready',
      themeCount: 3,
      signalCount: 8,
      lifecycleDistribution: { mainline: 2, crowded: 1 },
      mainlineThemes: [
        { themeId: 'AI', themeName: '人工智能', heatScore: 88 },
        { themeId: 'ROBOT', themeName: '机器人', heatScore: 82 },
      ],
      crowdingAlerts: [{ themeId: 'AI', themeName: '人工智能', crowdingRisk: 78 }],
    })

    expect(explanation.available).toBe(true)
    expect(explanation.mainlineText).toContain('人工智能')
    expect(explanation.leaderConfirmationText).toContain('龙头优先确认')
    expect(explanation.hotlistConfluenceText).toContain('过滤拥挤')
    expect(explanation.warnings).toContain('crowding_or_divergence_present')
  })
})
