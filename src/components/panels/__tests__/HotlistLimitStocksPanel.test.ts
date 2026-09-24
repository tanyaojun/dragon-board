import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

// 涨停池成分股明细面板源码合同（2026-09-25）：
// 三页签 = 涨停概览/成分股/历史趋势；池类型 = pool/market/yesterday；
// 风格 = 主题变量（SectorDetail 语言）；数据 = limit-stocks 名单 + series 历史聚合。
const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotlistLimitStocksPanel.vue'), 'utf8')

describe('HotlistLimitStocksPanel 涨停池成分股明细面板', () => {
  test('三个页签齐全（概览/成分股/历史趋势）+ 池类型切换（热榜池/全市场/昨日）', () => {
    const source = panelSource()

    for (const key of ['overview', 'stocks', 'history']) {
      expect(source).toContain(`'${key}'`)
    }
    expect(source).toContain("pool: '🔥 热榜池涨停'")
    expect(source).toContain("market: '🌐 全市场涨停'")
    expect(source).toContain("yesterday: '📜 昨日热榜涨停'")
  })

  test('数据链路：limit-stocks 三名单 + series 历史聚合；fail-visible 缺失 -- 不伪造', () => {
    const source = panelSource()

    expect(source).toContain('fetchHotlistLimitStocks')
    expect(source).toContain('fetchHotlistSentimentSeries')
    // 历史图表 null 断线不补 0；tooltip 缺失 -- 
    expect(source).toContain('connectNulls: false')
    expect(source).toContain("value === null || value === undefined ? '--'")
  })

  test('风格走主题变量（SectorDetail 语言），明细表为 stocks-table 语言', () => {
    const source = panelSource()

    expect(source).toContain('var(--bg-secondary)')
    expect(source).toContain('var(--color-highlight)')
    expect(source).not.toContain('linear-gradient(135deg, #667eea')
    expect(source).toContain('ls-table')
    expect(source).toContain('search-input')
  })
})
