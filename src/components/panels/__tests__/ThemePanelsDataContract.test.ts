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
    expect(panels).toContain('MongoDB 题材映射 + 腾讯行情 + 同花顺资金')
    expect(panels).not.toContain('TDX逐笔资金')
    expect(panels).not.toMatch(/Jxbk|jxbk|JXBK|getThemeStockMap|getJxbk/)
  })

  it('renders an empty THS fund value instead of a fabricated fallback state', () => {
    const panel = source('SectorPanel.vue')

    expect(panel).not.toContain('资金数据降级')
    expect(panel).toMatch(/mainNetInflow\s*==\s*null\s*\?\s*'--'/)
  })

  it('registers current theme stock pages as connection-scoped fund priority', () => {
    const panels = ['SectorDetail.vue', 'SectorStocksTree.vue'].map(source).join('\n')

    expect(panels).toMatch(/setFundOwnerCodes\(\s*'theme-detail\.visible'/)
    expect(panels).toContain("clearFundOwner('theme-detail.visible')")
    expect(panels).toMatch(/setFundOwnerCodes\(\s*'theme-tree\.visible'/)
    expect(panels).toContain("clearFundOwner('theme-tree.visible')")
  })
})
