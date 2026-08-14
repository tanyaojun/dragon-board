import { describe, expect, it } from 'vitest'
import {
  getLifecycleTier,
  getRankTrendTier,
  getResonanceTier,
  getSynergyTier,
  getSynergyTierDetail,
  getVolumePriceTier,
  tierBadgeClass,
  tierBadgeLabel,
} from '../tierDisplay'

function makeStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '000001',
    rankTrend: {
      resonance: { signalTier: 'A', tierReasons: ['方向确认'] },
      observation: {
        rankTrend: { signalTier: 'S', tierReasons: ['强趋势'] },
        volumePrice: { signalTier: 'B', tierReasons: ['放量上涨'] },
        lifecycle: { signalTier: 'A', tierReasons: ['优选路径'] },
        synergy: { signalTier: 'S', tierReasons: ['方向一致强买'] },
      },
    },
    ...overrides,
  }
}

describe('tierDisplay getters', () => {
  it('读取五维档位（前端路径 stock.rankTrend.*）', () => {
    const stock = makeStock()
    expect(getResonanceTier(stock)).toBe('A')
    expect(getRankTrendTier(stock)).toBe('S')
    expect(getVolumePriceTier(stock)).toBe('B')
    expect(getLifecycleTier(stock)).toBe('A')
    expect(getSynergyTier(stock)).toBe('S')
  })

  it('缺字段回退 null（不渲染空徽章、不报错）', () => {
    expect(getSynergyTier({})).toBeNull()
    expect(getSynergyTier(null)).toBeNull()
    expect(getSynergyTier({ rankTrend: {} })).toBeNull()
    expect(getResonanceTier({ rankTrend: { resonance: {} } })).toBeNull()
    expect(getRankTrendTier({ rankTrend: { observation: {} } })).toBeNull()
  })

  it('非法档位值回退 null（不伪装）', () => {
    const stock = makeStock({ rankTrend: { observation: { synergy: { signalTier: 'X' } } } })
    expect(getSynergyTier(stock)).toBeNull()
  })

  it('unknown 档位保留为 unknown（前端显示 --，不归零）', () => {
    const stock = makeStock({ rankTrend: { observation: { synergy: { signalTier: 'unknown' } } } })
    expect(getSynergyTier(stock)).toBe('unknown')
    expect(tierBadgeLabel('unknown')).toBe('--')
  })
})

describe('tierBadgeClass / tierBadgeLabel', () => {
  it('档位→样式类映射', () => {
    expect(tierBadgeClass('S')).toBe('tier-s')
    expect(tierBadgeClass('A')).toBe('tier-a')
    expect(tierBadgeClass('B')).toBe('tier-b')
    expect(tierBadgeClass('C')).toBe('tier-c')
    expect(tierBadgeClass('D')).toBe('tier-d')
    expect(tierBadgeClass('E')).toBe('tier-e')
    expect(tierBadgeClass('unknown')).toBe('tier-unknown')
    expect(tierBadgeClass(null)).toBeNull()
    expect(tierBadgeClass(undefined)).toBeNull()
  })

  it('展示文本', () => {
    expect(tierBadgeLabel('S')).toBe('S')
    expect(tierBadgeLabel('E')).toBe('E')
    expect(tierBadgeLabel('unknown')).toBe('--')
    expect(tierBadgeLabel(null)).toBeNull()
  })

  it('非法档位值回退 null（含原型链键如 toString 不误放行）', () => {
    expect(tierBadgeClass('X')).toBeNull()
    expect(tierBadgeLabel('X')).toBeNull()
    expect(tierBadgeClass('toString')).toBeNull()
    expect(getSynergyTier({ rankTrend: { observation: { synergy: { signalTier: 'toString' } } } })).toBeNull()
  })
})

describe('getSynergyTierDetail', () => {
  it('拼四维明细，缺维显示 -', () => {
    const stock = makeStock()
    expect(getSynergyTierDetail(stock)).toEqual(['共振 A', '趋势 S', '量价 B', '周期 A'])
    expect(getSynergyTierDetail({})).toEqual(['共振 -', '趋势 -', '量价 -', '周期 -'])
  })
})
