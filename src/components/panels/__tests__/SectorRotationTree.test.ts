import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTree（左固定四目录右分类明细表）', () => {
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTree.vue'),
    'utf8',
  )

  it('renders the two-pane layout like SectorStocksTree (directory left, list right)', () => {
    expect(tree).toContain('tree-layout')
    expect(tree).toContain('tree-directory')
    expect(tree).toContain('tree-detail')
    expect(tree).toContain('grid-template-columns: 200px 1fr')
  })

  it('left directory is exactly four fixed entries in user-defined order', () => {
    expect(tree).toContain("{ key: 'all', label: '全部' }")
    expect(tree).toContain("{ key: 'inflow', label: '流入' }")
    expect(tree).toContain("{ key: 'outflow', label: '流出' }")
    expect(tree).toContain("{ key: 'neutral', label: '中性' }")
    expect(tree).toContain("emit('update:category', entry.key)")
  })

  it('right pane lists per-theme rotation details for the selected category', () => {
    expect(tree).toContain('题材轮动明细')
    expect(tree).toContain('detail-table')
    expect(tree).toContain('轮动状态')
    expect(tree).toContain('轮动分')
    expect(tree).toContain('热度排名')
    expect(tree).toContain('排名变化')
    expect(tree).toContain('净流入趋势')
    expect(tree).toContain('质量标记')
    expect(tree).toContain('categoryRows')
  })

  it('stays fail-visible with empty category copy and unknown state passthrough', () => {
    expect(tree).toContain('该目录下无题材')
    expect(tree).toContain('state-unknown')
  })
})
