import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getHotThemes: vi.fn(),
  getSnapshot: vi.fn(),
}))

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: () => [],
    getDepth10Map: () => new Map(),
    getRecentTicksMap: () => new Map(),
    getL2SummaryMap: () => new Map(),
    getBreathData: () => null,
    getBreathMarketData: () => null,
    getHotThemes: () => mocks.getHotThemes(),
    getCurrentRotation: () => null,
    getBreathHistory: () => [],
    getBreathFactors: () => [],
    getMarketMode: () => 'normal',
    getVersion: () => ({ stocks: 0 }),
  },
}))
vi.mock('../../theme/ThemeHeatFeed', () => ({
  themeHeatFeed: { getSnapshot: () => mocks.getSnapshot() },
}))
vi.mock('../../theme/ThemeRuntimeCoordinator', () => ({
  getBackendRotationSummaryRaw: () => null,
}))

import { getCurrentSnapshotBuildContext } from '../buildContext'

describe('buildContext heatLevel caliber marking (B9)', () => {
  it('marks themeHeatFactors and hotThemes rows with metadata.factorVersion and numericizes hotThemes heatLevel', () => {
    mocks.getSnapshot.mockReturnValue({
      factorVersion: 'theme-market-v2',
      sources: {},
      factors: [{ themeId: 'AI', heatScore: 2000, heatLevel: 96.3, metadata: {} }],
    })
    mocks.getHotThemes.mockReturnValue([
      { id: 'AI', name: '人工智能', heatScore: 2000, heatLevelScore: 96.3, heatLevel: '热门' },
      { id: 'COLD', name: '冷门', heatScore: 12, heatLevelScore: undefined, heatLevel: '冰' },
    ])

    const context = getCurrentSnapshotBuildContext()

    expect(context.themeHeatFactors?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    // hotThemes 行 heatLevel 数值化（来自 heatLevelScore），字符串档位标签不再进入快照行
    expect(context.hotThemes?.[0]?.heatLevel).toBe(96.3)
    expect(context.hotThemes?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    // 无 heatLevelScore → 不写 heatLevel key（tri-state）
    expect(Object.prototype.hasOwnProperty.call(context.hotThemes?.[1], 'heatLevel')).toBe(false)
    expect(context.hotThemes?.[1]?.metadata?.factorVersion).toBe('theme-market-v2')
  })

  it('falls back to theme-market-v2 marking when snapshot factorVersion is missing', () => {
    mocks.getSnapshot.mockReturnValue({ sources: {}, factors: [{ themeId: 'AI', metadata: {} }] })
    mocks.getHotThemes.mockReturnValue([{ id: 'AI', name: '人工智能' }])

    const context = getCurrentSnapshotBuildContext()

    expect(context.themeHeatFactors?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    expect(context.hotThemes?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
  })
})
