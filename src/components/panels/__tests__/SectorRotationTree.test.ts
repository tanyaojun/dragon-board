import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTree（左目录右列表两栏视图）', () => {
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTree.vue'),
    'utf8',
  )

  it('renders the two-pane layout like SectorStocksTree (directory left, detail right)', () => {
    expect(tree).toContain('tree-layout')
    expect(tree).toContain('tree-directory')
    expect(tree).toContain('tree-detail')
    expect(tree).toContain('grid-template-columns: 280px 1fr')
  })

  it('left directory renders tree-node cards with state badges and rank', () => {
    expect(tree).toContain('tree-node')
    expect(tree).toContain('selected')
    expect(tree).toContain('node-name')
    expect(tree).toContain('state-badge')
    expect(tree).toContain('rank-badge')
    expect(tree).toContain('轮动分')
  })

  it('right detail lists rotation fields for the selected theme', () => {
    expect(tree).toContain('detail-header')
    expect(tree).toContain('detail-table')
    expect(tree).toContain('轮动状态')
    expect(tree).toContain('轮动分')
    expect(tree).toContain('热度排名')
    expect(tree).toContain('排名变化')
    expect(tree).toContain('净流入趋势')
    expect(tree).toContain('热度趋势')
    expect(tree).toContain('质量标记')
    expect(tree).toContain('点击左侧题材查看轮动明细')
  })

  it('selection is internal with auto-fallback to first visible row', () => {
    expect(tree).toContain('const selectedKey = ref<string | null>(null)')
    expect(tree).toContain('byKey ?? props.statuses[0] ?? null')
  })

  it('stays fail-visible with empty filter copy and unknown state passthrough', () => {
    expect(tree).toContain('该筛选下无题材')
    expect(tree).toContain('state-unknown')
  })
})
