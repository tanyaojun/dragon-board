import { describe, expect, it } from 'vitest'

import type { MergedStock } from '@/types'
import {
  calculateStockHotnessRecords,
  calculateStockHotnessUpdates,
  normalizeStockHotnessConfig,
} from '../StockHotnessCalculator'

function createStock(overrides: Partial<MergedStock> = {}): MergedStock {
  return {
    code: '600001',
    name: '样本股',
    price: 10,
    change: 0,
    volume: 0,
    turnover: 0,
    turnoverRate: 0,
    pe: 0,
    pb: 0,
    totalMV: 0,
    cirMV: 0,
    zlje: 0,
    zljzb: 0,
    cddje: 0,
    cddjzb: 0,
    platforms: 0,
    avgRankNum: 999,
    avgRank: '999.0',
    compScore: 0,
    hotness: 0,
    popularity: 0,
    popularityChange: 0,
    leadTimes: 0,
    leadStatus: '',
    lianbanStr: '',
    continuousDays: 0,
    highDays: 0,
    boardHeight: 0,
    themes: [],
    tags: [],
    reason: '',
    isNew: false,
    firstZtTime: '',
    lastZtTime: '',
    platformName: '',
    fundPenetration: 0,
    themeHeat: 0,
    themeLevel: '冷',
    ...overrides,
  }
}

describe('StockHotnessCalculator', () => {
  it('热度不是 avgRank 的简单拷贝，而是综合多项个股信号计算', () => {
    const strong = createStock({
      code: '600100',
      avgRankNum: 5.2,
      avgRank: '5.2',
      platforms: 6,
      popularity: 12859,
      popularityChange: 18,
      leadStatus: '龙一',
      leadTimes: 2,
      continuousDays: 2,
      boardHeight: 2,
      turnoverRate: 14,
    })
    const sameRankButWeaker = createStock({
      code: '600200',
      avgRankNum: 5.2,
      avgRank: '5.2',
      platforms: 2,
      popularity: 3454,
      popularityChange: -3,
      leadStatus: '',
      leadTimes: 0,
      continuousDays: 0,
      boardHeight: 0,
      turnoverRate: 1.5,
    })

    const updates = calculateStockHotnessUpdates([strong, sameRankButWeaker], 8)
    const hotnessMap = new Map(updates.map((item) => [item.code, item.hotness]))

    expect(hotnessMap.get('600100')).toBeGreaterThan(hotnessMap.get('600200') || 0)
    expect(hotnessMap.get('600100')).not.toBe(Math.round(strong.avgRankNum || 0))
    expect(hotnessMap.get('600200')).not.toBe(Math.round(sameRankButWeaker.avgRankNum || 0))
  })

  it('没有热榜、人气和活跃信号时，热度应回落到 0', () => {
    const cold = createStock({
      code: '600300',
      avgRankNum: 999,
      avgRank: '999.0',
      platforms: 0,
      popularity: 0,
      popularityChange: 0,
      leadStatus: '',
      turnoverRate: 0,
    })

    const updates = calculateStockHotnessUpdates([cold], 8)
    expect(updates[0]?.hotness).toBe(0)
  })

  it('允许通过配置重调热度权重，而不需要修改计算代码', () => {
    const leaderFocused = createStock({
      code: '600400',
      avgRankNum: 20,
      avgRank: '20.0',
      platforms: 2,
      popularity: 2200,
      popularityChange: 0,
      leadStatus: '龙一',
      leadTimes: 2,
      boardHeight: 3,
      continuousDays: 3,
      turnoverRate: 5,
    })
    const popularityFocused = createStock({
      code: '600500',
      avgRankNum: 4,
      avgRank: '4.0',
      platforms: 6,
      popularity: 12600,
      popularityChange: 16,
      leadStatus: '',
      leadTimes: 0,
      boardHeight: 0,
      continuousDays: 0,
      turnoverRate: 10,
    })

    const defaultRecords = calculateStockHotnessRecords([leaderFocused, popularityFocused], 8)
    const leaderOnlyRecords = calculateStockHotnessRecords(
      [leaderFocused, popularityFocused],
      8,
      {
        weights: {
          avgRank: 0,
          platformCoverage: 0,
          popularity: 0,
          popularityChange: 0,
          leaderStatus: 0.7,
          boardHeight: 0.2,
          turnoverRate: 0.1,
        },
      },
    )

    const defaultMap = new Map(defaultRecords.map((item) => [item.code, item.hotness]))
    const leaderOnlyMap = new Map(leaderOnlyRecords.map((item) => [item.code, item.hotness]))

    expect(defaultMap.get('600500')).toBeGreaterThan(defaultMap.get('600400') || 0)
    expect(leaderOnlyMap.get('600400')).toBeGreaterThan(leaderOnlyMap.get('600500') || 0)
  })

  it('人气值按绝对热度处理，值越大贡献越高', () => {
    const highPopularity = createStock({
      code: '600600',
      avgRankNum: 10,
      avgRank: '10.0',
      platforms: 4,
      popularity: 15000,
      popularityChange: 5,
      turnoverRate: 8,
    })
    const lowPopularity = createStock({
      code: '600700',
      avgRankNum: 10,
      avgRank: '10.0',
      platforms: 4,
      popularity: 1200,
      popularityChange: 5,
      turnoverRate: 8,
    })

    const updates = calculateStockHotnessUpdates([highPopularity, lowPopularity], 8)
    const hotnessMap = new Map(updates.map((item) => [item.code, item.hotness]))

    expect(hotnessMap.get('600600')).toBeGreaterThan(hotnessMap.get('600700') || 0)
  })

  it('会把自定义权重归一化，避免配置总和漂移', () => {
    const config = normalizeStockHotnessConfig({
      weights: {
        avgRank: 3,
        platformCoverage: 1,
        popularity: 1,
      },
    })

    const totalWeight = Object.values(config.weights).reduce((sum, value) => sum + value, 0)
    expect(totalWeight).toBeCloseTo(1, 6)
    expect(config.weights.avgRank).toBeGreaterThan(config.weights.platformCoverage)
  })
})
