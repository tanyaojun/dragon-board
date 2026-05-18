import { describe, expect, it } from 'vitest'

import { analyzeThemeCorrelationInput } from '../ThemeCorrelationEngine'

describe('ThemeCorrelationEngine', () => {
  it('does not promote suspicious capped volume ratio stocks as theme leaders', () => {
    const detail = analyzeThemeCorrelationInput({
      themeId: 'AI',
      themeName: '人工智能',
      stocks: [
        {
          code: '000001',
          name: '可疑放量',
          change: 1,
          volumeRatio: 99.99,
          volumeRatioMeta: {
            status: 'suspicious',
            source: 'intraday_snapshot',
            calculatedAt: Date.now(),
            currentVolume: 100000,
            capped: true,
            reason: 'ratio_capped',
          },
        },
        {
          code: '000002',
          name: '真实强势',
          change: 4,
          volumeRatio: 1.2,
          volumeRatioMeta: {
            status: 'fresh',
            source: 'intraday_snapshot',
            calculatedAt: Date.now(),
            currentVolume: 90000,
          },
        },
      ],
    })

    expect(detail.leader?.code).toBe('000002')
    expect(detail.stocks.get('000001')?.volumeRatio).toBe(0)
  })
})
