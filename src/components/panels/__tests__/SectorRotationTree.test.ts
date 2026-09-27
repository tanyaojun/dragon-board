import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTree', () => {
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTree.vue'),
    'utf8',
  )

  it('groups statuses by rotationState with mainline-first order', () => {
    expect(tree).toContain("GROUP_ORDER = ['mainline', 'inflow', 'emerging', 'neutral', 'outflow', 'cooling']")
    expect(tree).toContain('tree-group')
    expect(tree).toContain('group-header')
  })

  it('renders tree-node cards in SectorStocksTree style with rotation metrics', () => {
    expect(tree).toContain('tree-node')
    expect(tree).toContain('selected')
    expect(tree).toContain('node-header')
    expect(tree).toContain('node-name')
    expect(tree).toContain('node-metrics')
    expect(tree).toContain('node-progress')
    expect(tree).toContain('progress-bar')
    expect(tree).toContain('rotationScore')
    expect(tree).toContain('flowTrend')
  })

  it('emits select with row and event for the detail flyout', () => {
    expect(tree).toContain("(e: 'select', row: ThemeRotationStatusRow, event: MouseEvent)")
    expect(tree).toContain("@click=\"emitSelect(row, $event)\"")
  })

  it('stays fail-visible with empty filter copy and unknown state passthrough', () => {
    expect(tree).toContain('该筛选下无题材')
    expect(tree).toContain('state-unknown')
  })
})
