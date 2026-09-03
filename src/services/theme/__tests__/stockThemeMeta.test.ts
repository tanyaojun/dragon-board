import { describe, expect, it } from 'vitest'

import {
  buildStockThemeSignature,
  deriveThemeHeatBand,
  deriveThemeHeatLevel,
  deriveThemeHeatMeta,
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

describe('deriveThemeHeatBand (audit fix: unified 0-100 band)', () => {
  it('maps 0-100 relative score to s/a/b/c/d bands with thresholds 80/60/40/20', () => {
    expect(deriveThemeHeatBand(80)).toBe('s')
    expect(deriveThemeHeatBand(60)).toBe('a')
    expect(deriveThemeHeatBand(40)).toBe('b')
    expect(deriveThemeHeatBand(20)).toBe('c')
    expect(deriveThemeHeatBand(10)).toBe('d')
    expect(deriveThemeHeatBand(0)).toBe('d')
  })

  it('treats missing heat as coldest band (no falsy coercion)', () => {
    expect(deriveThemeHeatBand(null)).toBe('d')
    expect(deriveThemeHeatBand(undefined)).toBe('d')
    expect(deriveThemeHeatBand(Number.NaN)).toBe('d')
  })
})

describe('deriveThemeHeatMeta missing guard', () => {
  it('returns neutral gray meta for missing heat (not coldest tier)', () => {
    // 旧实现签名只收 number，运行时 null 落到 '冰' 分支伪装成真实冷档；
    // 缺失应显示中性灰色（level ''，无档位文字）
    expect(deriveThemeHeatMeta(null)).toEqual({ level: '', icon: '–', color: '#95a5a6' })
    expect(deriveThemeHeatMeta(undefined)).toEqual({ level: '', icon: '–', color: '#95a5a6' })
  })
})

describe('resolvePrimaryStockTheme range guard (audit Medium)', () => {
  it('treats out-of-range heatScore as missing (v2 absolute value must not leak)', () => {
    // theme-market-v2 下 heatScore 是 KPL 人气总和（热门题材可达数十万）；
    // 0-100 相对分消费端不得收到绝对值（与 StockHotnessCalculator M5 守卫同口径）
    const snap = resolvePrimaryStockTheme([{ id: 'tariff', name: '关税战', heatScore: 615949 }])
    expect(snap.themeHeat).toBeNull()
    expect(snap.themeLevel).toBe('')
  })

  it('keeps in-range 0-100 relative score', () => {
    const snap = resolvePrimaryStockTheme([{ id: 'AI', name: '人工智能', heatScore: 96.3 }])
    expect(snap.themeHeat).toBe(96.3)
    expect(snap.themeLevel).toBe('热门')
  })
})
