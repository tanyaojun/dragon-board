import { describe, expect, it } from 'vitest'

import {
  buildStockThemeSignature,
  deriveThemeHeatLevel,
  resolvePrimaryStockTheme,
  sortStockThemes,
} from '../stockThemeMeta'

describe('stockThemeMeta', () => {
  it('会按题材热度、联动性和来源优先级选出主题材', () => {
    const themes = sortStockThemes([
      { id: 'robot', name: '机器人', heatScore: 58, heatLevel: '温', correlation: 0.22, source: 'static' },
      { id: 'power', name: '电力', heatScore: 76, heatLevel: '活跃', correlation: 0.31, source: 'realtime' },
      { id: 'state', name: '地方国资', heatScore: 76, heatLevel: '活跃', correlation: 0.28, source: 'static' },
    ])

    expect(themes.map((theme) => theme.name)).toEqual(['电力', '地方国资', '机器人'])
    expect(resolvePrimaryStockTheme(themes)).toEqual({
      mainTheme: '电力',
      themeHeat: 76,
      themeLevel: '活跃',
    })
  })

  it('题材 id 不变但热度变化时，签名也会变化', () => {
    const baseline = buildStockThemeSignature([
      { id: 'power', name: '电力', heatScore: 62, heatLevel: '活跃', correlation: 0.31, source: 'static' },
    ])
    const updated = buildStockThemeSignature([
      { id: 'power', name: '电力', heatScore: 75, heatLevel: '活跃', correlation: 0.31, source: 'static' },
    ])

    expect(updated).not.toBe(baseline)
  })

  it('缺少显式热度级别时，会按热度分段自动补齐', () => {
    expect(deriveThemeHeatLevel(82)).toBe('热门')
    expect(deriveThemeHeatLevel(65)).toBe('活跃')
    expect(deriveThemeHeatLevel(45)).toBe('温')
    expect(deriveThemeHeatLevel(28)).toBe('冷')
    expect(deriveThemeHeatLevel(10)).toBe('冰')
  })
})

describe('deriveThemeHeatLevel missing handling', () => {
  it('returns empty label for missing heat (not coldest tier)', () => {
    // 评审 H-2d：hasFiniteNumber(null) === true（Number(null) === 0），
    // 旧实现会把 null 判成 0 度"冰"；必须返回空标签表示缺失。
    expect(deriveThemeHeatLevel(null)).toBe('')
    expect(deriveThemeHeatLevel(undefined)).toBe('')
    expect(deriveThemeHeatLevel(Number.NaN)).toBe('')
  })
})

describe('resolvePrimaryStockTheme missing heat', () => {
  it('keeps themeHeat null when primary theme has no heatScore (not 0)', () => {
    const snap = resolvePrimaryStockTheme([{ id: 'AI', name: '人工智能', heatScore: null }])
    expect(snap.themeHeat).toBeNull()
    expect(snap.themeLevel).toBe('')
  })
})
