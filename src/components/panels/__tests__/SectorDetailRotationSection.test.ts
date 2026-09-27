import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorDetail 概览轮动状态合并（2026-09-27 二轮反馈）', () => {
  const detail = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorDetail.vue'),
    'utf8',
  )

  it('fetches the rotation summary and matches the row by sector name', () => {
    expect(detail).toContain('getRotationSummary')
    expect(detail).toContain("row.entityName === props.sectorName")
    expect(detail).toContain("snapshotType: 'half_hour'")
  })

  it('renders rotation fields in the overview without blocking sector data', () => {
    expect(detail).toContain('🔄 轮动状态')
    expect(detail).toContain('轮动分')
    expect(detail).toContain('热度排名')
    expect(detail).toContain('净流入趋势')
    expect(detail).toContain('强度')
    expect(detail).toContain('拥挤')
    expect(detail).toContain('qualityFlags')
  })

  it('stays fail-visible when the theme is absent from the rotation snapshot', () => {
    expect(detail).toContain('该题材不在轮动快照中')
    expect(detail).toContain('rotationLoaded.value = false')
  })
})
