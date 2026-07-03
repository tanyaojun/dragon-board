import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const panelRoot = join(process.cwd(), 'src', 'components', 'panels')

function source(name: string): string {
  return readFileSync(join(panelRoot, name), 'utf8')
}

describe('theme panel data contract', () => {
  it('uses market theme summaries without retired block contracts', () => {
    const panels = ['SectorPanel.vue', 'SectorDetail.vue', 'SectorStocksTree.vue', 'ThemeCorrelationPanel.vue']
      .map(source)
      .join('\n')

    expect(panels).toContain('getThemeSummaries')
    expect(panels).toContain('loadSectorStocks')
    expect(panels).toContain('MongoDB 题材映射 + 腾讯行情 + 东财资金')
    expect(panels).not.toMatch(/Jxbk|jxbk|JXBK|getThemeStockMap|getJxbk/)
  })

  it('renders explicit degraded fund state instead of a fabricated zero', () => {
    const panel = source('SectorPanel.vue')

    expect(panel).toContain('资金数据降级')
    expect(panel).toMatch(/fundScore\s*===\s*null|mainNetInflow\s*===\s*null/)
  })
})
