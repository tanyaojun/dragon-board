import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// 题材列表左栏（280px）空间有限：排序控件与搜索框放同一行（tree-filter-row），
// 搜索框弹性缩窄，排序按钮摘要文本限宽（完整口径由触发按钮 title 提供）。
describe('SectorStocksTree 题材列表过滤行', () => {
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorStocksTree.vue'),
    'utf8',
  )

  it('排序控件与搜索框在同一 flex 行内', () => {
    expect(tree).toContain('tree-filter-row')
    const rowStart = tree.indexOf('tree-filter-row')
    const statsStart = tree.indexOf('tree-stats')
    expect(rowStart).toBeGreaterThan(-1)
    expect(statsStart).toBeGreaterThan(rowStart)
    const row = tree.slice(rowStart, statsStart)
    expect(row).toContain('<ThemeSortControl')
    expect(row).toContain('search-input')
  })

  it('搜索框在行内弹性缩窄，排序摘要文本限宽', () => {
    expect(tree).toMatch(/\.tree-filter-row\s*\{[^}]*display:\s*flex/)
    expect(tree).toMatch(/\.tree-search\s*\{[^}]*flex:\s*1[^}]*min-width:\s*0/)
    expect(tree).toContain('.tree-sort-control :deep(.trigger-text)')
  })
})
