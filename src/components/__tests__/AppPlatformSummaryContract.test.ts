import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('App market platform summary', () => {
  test('shows live row counts for all eight hotlists and quote coverage', () => {
    const source = appSource()

    expect(source).toContain('class="status-bar"')
    expect(source).toContain('class="status-group"')
    expect(source).toContain('<span class="status-label">股票</span>')
    expect(source).toContain('{{ stockCount }}')
    expect(source).toContain(
      '<span class="status-label">东财:<span class="status-value">{{ marketSummary.eastmoney }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">THS:<span class="status-value">{{ marketSummary.ths }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">KPL:<span class="status-value">{{ marketSummary.kpl }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">TDX:<span class="status-value">{{ marketSummary.tdx }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">雪球:<span class="status-value">{{ marketSummary.xueqiu }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">财联:<span class="status-value">{{ marketSummary.cls }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">淘股吧:<span class="status-value">{{ marketSummary.tgb }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">大智慧:<span class="status-value">{{ marketSummary.dzh }}</span></span>',
    )
    expect(source).toContain(
      '<span class="status-label">行情:<span class="status-value">{{ marketSummary.quotes }}</span></span>',
    )
    expect(source).toContain("['raw.platforms', 'raw.platformStatus', 'merged.stocks', 'quotes:batch']")
    expect(source).toMatch(/dataLayer\.subscribe\(path,/)
    expect(source).not.toContain('数据来自当前 platformData')

    const statusCenter = source.match(/<div class="status-center">([\s\S]*?)<\/div>\s*<div class="status-right">/)?.[1]
    expect(statusCenter).toContain('<SearchBox')
  })
})
