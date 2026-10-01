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
  it('拼投票维明细，缺维显示 -', () => {
    const stock = makeStock()
    expect(getSynergyTierDetail(stock)).toEqual(['共振 A', '趋势 S', '量价 B', '周期 A', '热度 -'])
    expect(getSynergyTierDetail({})).toEqual(['共振 -', '趋势 -', '量价 -', '周期 -', '热度 -'])
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

  it('热度第 5 维参与投票：展示票值与降档前档位（江西铜业案例）', () => {
    const stock = {
      rankTrend: {
        resonance: { signalTier: 'A', direction: 'buy' },
        observation: {
          rankTrend: { signalTier: 'B', direction: 'buy' },
          volumePrice: { signalTier: 'B', direction: 'up' },
          lifecycle: { signalTier: 'D', stage: 'crowded' },
          crossSection: { signalTier: 'B', percentile: 95, percentileDelta: 0, relativeToMarket: 44 },
          synergy: { signalTier: 'A', tierReasons: ['方向一致强买（档位加权高分）', '周期 D 环境降档'] },
        },
      },
    }
    const lines = getSynergyVoteBreakdown(stock)
    // 三维票附加权后分值（阶段 23.9 采纳票权：res/rank ×0.75、vp ×1.0：0.75 + 0.525 + 0.7；
    // B 档 0.8→0.7 随后端 2026-09-30 vsB_070 落默认同步，eabf4b44 漏更本用例后补）
    // + 热度第 5 维票 0.5×0.75=+0.375（合计 2.35，S 线 3.0 之下 → A 区间）
    expect(lines[0]).toContain('共振 买入·涨(+0.75)')
    expect(lines[0]).toContain('趋势 弱买·涨(+0.52)')
    expect(lines[0]).toContain('量价 弱买·涨(+0.7)')
    expect(lines[0]).toContain('热度 偏强（第5维票 +0.38）')
    // 周期环境门
    expect(lines[1]).toContain('周期 回避（拥挤）')
    // 总档：A 是 S 降一档后的结果，标注降档前档位
    expect(lines[2]).toContain('总档 A（买入')
    expect(lines[2]).toContain('周期环境门降档后')
    expect(lines[2]).toContain('降档前 S')
  })

  it('热度档位缺失时不展示第 5 维票（fail-visible，不伪造）', () => {
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
    expect(lines[0]).not.toContain('热度')
    expect(lines[2]).toContain('总档 S（强买）')
    expect(lines[2]).not.toContain('降档前')
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
    expect(getCrossSectionDetail(stock)).toBe('热度 92/8/31')
  })

  it('getCrossSectionDetail 全缺返回 null', () => {
    expect(getCrossSectionDetail(makeStock())).toBeNull()
  })

  it('getSynergyTierDetail 含热度段', () => {
    const stock = makeStock({
      rankTrend: {
        ...makeStock().rankTrend,
        observation: {
          ...makeStock().rankTrend!.observation,
          crossSection: { signalTier: 'A', percentile: 92, percentileDelta: 8, relativeToMarket: 30 },
        },
      },
    })
    expect(getSynergyTierDetail(stock)).toContain('热度 A')
  })
})
