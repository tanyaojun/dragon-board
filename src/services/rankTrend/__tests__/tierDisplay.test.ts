import { describe, expect, it } from 'vitest'
import {
  getCrossSectionDetail,
  getCrossSectionTier,
  getLifecycleTier,
  getRankTrendTier,
  getResonanceTier,
  getSynergyTier,
  getSynergyTierDetail,
  getSynergyVoteBreakdown,
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
    expect(getSynergyTierDetail(stock)).toEqual(['共振 A', '趋势 S', '量价 B', '周期 A', '横截 -'])
    expect(getSynergyTierDetail({})).toEqual(['共振 -', '趋势 -', '量价 -', '周期 -', '横截 -'])
  })
})

describe('getSynergyVoteBreakdown（三票一票制用户友好解释）', () => {
  it('三维方向票 + 周期环境门 + 最终结果', () => {
    const stock = {
      rankTrend: {
        resonance: { signalTier: 'A', direction: 'buy' },
        observation: {
          rankTrend: { signalTier: 'A', direction: 'buy' },
          volumePrice: { signalTier: 'B', direction: 'up' },
          lifecycle: { signalTier: 'A', stage: 'expansion' },
          synergy: { signalTier: 'S', tierReasons: ['方向一致强买'] },
        },
      },
    }
    const lines = getSynergyVoteBreakdown(stock)
    expect(lines[0]).toContain('共振 买入·涨')
    expect(lines[0]).toContain('趋势 买入·涨')
    expect(lines[0]).toContain('量价 弱买·涨')
    expect(lines[1]).toContain('周期 放行（扩散）')
    expect(lines[2]).toContain('总档 S（强买）')
  })

  it('周期否决：一票否决直接决定总档', () => {
    const stock = {
      rankTrend: {
        resonance: { signalTier: 'A', direction: 'buy' },
        observation: {
          rankTrend: { signalTier: 'A', direction: 'buy' },
          volumePrice: { signalTier: 'B', direction: 'up' },
          lifecycle: { signalTier: 'E', stage: 'crowded' },
          synergy: { signalTier: 'E', tierReasons: ['周期一票否决'] },
        },
      },
    }
    const lines = getSynergyVoteBreakdown(stock)
    expect(lines.some((l) => l.includes('周期 否决'))).toBe(true)
    expect(lines.some((l) => l.includes('总档强制否决'))).toBe(true)
  })

  it('周期降档标注', () => {
    const stock = {
      rankTrend: {
        resonance: { signalTier: 'A', direction: 'buy' },
        observation: {
          rankTrend: { signalTier: 'A', direction: 'buy' },
          volumePrice: { signalTier: 'B', direction: 'up' },
          lifecycle: { signalTier: 'D', stage: 'cooling' },
          synergy: { signalTier: 'B', tierReasons: ['方向一致强买', '周期 D 环境降档'] },
        },
      },
    }
    const lines = getSynergyVoteBreakdown(stock)
    expect(lines.some((l) => l.includes('周期 回避（冷却）'))).toBe(true)
    expect(lines.some((l) => l.includes('环境门降档'))).toBe(true)
  })

  it('缺字段回退：方向票不足/总档未合并，不抛错', () => {
    const lines = getSynergyVoteBreakdown({})
    expect(lines.some((l) => l.includes('方向票不足'))).toBe(true)
    expect(lines.some((l) => l.includes('总档：数据不足'))).toBe(true)
  })
})

describe('crossSection getters（2026-08-18 第 5 维 tooltip）', () => {
  it('getCrossSectionTier 读取 observation.crossSection.signalTier', () => {
    const stock = makeStock({
      rankTrend: {
        ...makeStock().rankTrend,
        observation: {
          ...makeStock().rankTrend!.observation,
          crossSection: { signalTier: 'A', percentile: 92, percentileDelta: 8, relativeToMarket: 30 },
        },
      },
    })
    expect(getCrossSectionTier(stock)).toBe('A')
  })

  it('getCrossSectionTier 缺字段返回 null', () => {
    expect(getCrossSectionTier(makeStock())).toBeNull()
  })

  it('getCrossSectionDetail 返回 percentile/delta/rel 摘要', () => {
    const stock = makeStock({
      rankTrend: {
        ...makeStock().rankTrend,
        observation: {
          ...makeStock().rankTrend!.observation,
          crossSection: { percentile: 92.4, percentileDelta: 8.2, relativeToMarket: 30.7 },
        },
      },
    })
    expect(getCrossSectionDetail(stock)).toBe('横截 92/8/31')
  })

  it('getCrossSectionDetail 全缺返回 null', () => {
    expect(getCrossSectionDetail(makeStock())).toBeNull()
  })

  it('getSynergyTierDetail 含横截段', () => {
    const stock = makeStock({
      rankTrend: {
        ...makeStock().rankTrend,
        observation: {
          ...makeStock().rankTrend!.observation,
          crossSection: { signalTier: 'A', percentile: 92, percentileDelta: 8, relativeToMarket: 30 },
        },
      },
    })
    expect(getSynergyTierDetail(stock)).toContain('横截 A')
  })
})
