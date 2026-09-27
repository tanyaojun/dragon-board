import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotation detail flyout', () => {
  const detail = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotation.vue'),
    'utf8',
  )

  it('opens as a teleported flyout via usePanel like SectorDetail', () => {
    expect(detail).toContain('<Teleport to="body">')
    expect(detail).toContain("usePanel({")
    expect(detail).toContain("name: 'SectorRotationPanel'")
    expect(detail).toContain('triggerRect')
    expect(detail).toContain('← 返回')
  })

  it('renders overview metric cards and rotation factor breakdown', () => {
    expect(detail).toContain('metrics-grid')
    expect(detail).toContain('轮动分')
    expect(detail).toContain('热度排名')
    expect(detail).toContain('净流入趋势')
    expect(detail).toContain('factors-grid')
    expect(detail).toContain('factorBreakdown')
    expect(detail).toContain('质量标记')
  })

  it('consumes the status row directly without extra API calls', () => {
    expect(detail).toContain('row: ThemeRotationStatusRow | null')
    expect(detail).not.toContain('apiService')
    expect(detail).toContain('暂无轮动数据')
  })
})
