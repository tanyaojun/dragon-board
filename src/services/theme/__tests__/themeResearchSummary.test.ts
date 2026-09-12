import { describe, expect, it, vi } from 'vitest'

import { apiService } from '@/services/apiService'

import {
  buildHotlistThemeResearchItems,
  buildThemeResearchExplanation,
  loadThemeResearchExplanation,
} from '../themeResearchSummary'

vi.mock('@/services/apiService', () => ({
  apiService: {
    getThemeResearchSummary: vi.fn(),
  },
}))

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

  it('builds stock-level hotlist confluence explanations and filter reasons', () => {
    const explanation = buildThemeResearchExplanation({
      available: true,
      researchGrade: 'research_ready',
      themeCount: 2,
      signalCount: 5,
      lifecycleDistribution: { mainline: 1, crowded: 1 },
      mainlineThemes: [{ themeId: 'ROBOT', themeName: '机器人', heatScore: 86 }],
      crowdingAlerts: [{ themeId: 'AI', themeName: '人工智能', crowdingRisk: 82 }],
    })

    const items = buildHotlistThemeResearchItems(
      [
        { code: '600001', name: '题材龙头', mainTheme: '机器人', themeRole: 'leader', themeContribution: 18, themeExposureWeight: 88 },
        { code: '600002', name: '拥挤样本', mainTheme: '人工智能', themeRole: 'noise', themeContribution: 1, themeExposureWeight: 28 },
      ],
      explanation,
    )

    expect(items[0]).toMatchObject({
      code: '600001',
      themeName: '机器人',
      themeRole: 'leader',
      noise: false,
    })
    expect(items[0].confluenceScore).toBeGreaterThanOrEqual(80)
    expect(items[0].entryReason).toContain('主线题材共振')
    expect(items[1].noise).toBe(true)
    expect(items[1].filterReason).toContain('噪声')
  })

  it('reads live theme exposure from nested stock themes', () => {
    const explanation = buildThemeResearchExplanation({
      available: true,
      researchGrade: 'research_ready',
      themeCount: 1,
      signalCount: 1,
      lifecycleDistribution: { mainline: 1 },
      mainlineThemes: [{ themeId: 'ROBOT', themeName: '机器人', heatScore: 86 }],
      crowdingAlerts: [],
    })

    const items = buildHotlistThemeResearchItems(
      [
        {
          code: '600001',
          name: '题材龙头',
          mainTheme: '机器人',
          themes: [
            {
              name: '机器人',
              role: 'leader',
              themeContribution: 18,
              exposureWeight: 88,
            },
          ],
        },
      ],
      explanation,
    )

    expect(items[0]).toMatchObject({
      themeRole: 'leader',
      noise: false,
    })
    expect(items[0].confluenceScore).toBeGreaterThanOrEqual(80)
  })
})

describe('loadThemeResearchExplanation 请求失败转写（2026-09-12）', () => {
  it('超时/中止错误转可读文案，不透出 "signal is aborted without reason" 原文', async () => {
    vi.mocked(apiService.getThemeResearchSummary).mockRejectedValueOnce(
      new DOMException('signal is aborted without reason', 'AbortError'),
    )

    const explanation = await loadThemeResearchExplanation()

    expect(explanation.available).toBe(false)
    expect(explanation.statusText).toContain('研究摘要不可用')
    expect(explanation.statusText).toContain('超时')
    expect(explanation.statusText).not.toContain('signal is aborted without reason')
  })

  it('普通请求错误仍透出原始 message（fail-visible）', async () => {
    vi.mocked(apiService.getThemeResearchSummary).mockRejectedValueOnce(new Error('backend_error: boom'))

    const explanation = await loadThemeResearchExplanation()

    expect(explanation.available).toBe(false)
    expect(explanation.statusText).toContain('backend_error: boom')
  })
})
