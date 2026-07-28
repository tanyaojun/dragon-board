import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('App market platform summary', () => {
  test('shows live row counts for all eight hotlists and quote coverage', () => {
    const source = appSource()

    expect(source).toContain('class="platform-summary"')
    expect(source).toContain('共{{ marketSummary.totalStocks }}只')
    expect(source).toContain('THS:{{ marketSummary.ths }}')
    expect(source).toContain('KPL:{{ marketSummary.kpl }}')
    expect(source).toContain('TDX:{{ marketSummary.tdx }}')
    expect(source).toContain('雪球:{{ marketSummary.xueqiu }}')
    expect(source).toContain('财联:{{ marketSummary.cls }}')
    expect(source).toContain('淘股吧:{{ marketSummary.tgb }}')
    expect(source).toContain('大智慧:{{ marketSummary.dzh }}')
    expect(source).toContain('行情:{{ marketSummary.quotes }}')
    expect(source).toContain("['raw.platforms', 'merged.stocks', 'quotes:batch']")
    expect(source).toMatch(/dataLayer\.subscribe\(path,/)
    expect(source).not.toContain('数据来自当前 platformData')

    const statusCenter = source.match(/<div class="status-center">([\s\S]*?)<\/div>\s*<div class="status-right">/)?.[1]
    expect(statusCenter).toContain('<SearchBox')
    expect(statusCenter).toContain('class="platform-summary"')
    expect(statusCenter?.indexOf('<SearchBox')).toBeLessThan(
      statusCenter?.indexOf('class="platform-summary"') ?? -1,
    )
  })
})
