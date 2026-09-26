import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTab', () => {
  const tab = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTab.vue'),
    'utf8',
  )
  const facade = readFileSync(join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'), 'utf8')

  it('fetches via themeFacade.getRotationSummary against the rotation summary API', () => {
    expect(tab).toContain('getRotationSummary')
    expect(facade).toContain('export async function getRotationSummary')
    expect(facade).toContain('/api/theme-rotation/summary')
    // 交互式读取：绕过后台轮询请求队列，避免页签"加载中"被队列滞留卡死
    expect(facade).toContain('bypassQueue: true')
  })

  it('renders summary fields with explicit engine-no-mainline copy', () => {
    expect(tab).toContain('phase-badge')
    expect(tab).toContain('rotationSpeed')
    expect(tab).toContain('mainlineConcentration')
    expect(tab).toContain('maxBoardHeight')
    expect(tab).toContain('引擎判定无主线')
    expect(tab).toContain('inflowThemes')
    expect(tab).toContain('outflowThemes')
    expect(tab).toContain('state-distribution')
  })

  it('supports sortable and filterable status table with quality flags', () => {
    expect(tab).toContain('rotation-table')
    expect(tab).toContain('toggleSort')
    expect(tab).toContain('stateFilter')
    expect(tab).toContain('qualityFlags')
    expect(tab).toContain('展开题材状态表')
  })

  it('stays fail-visible on empty data and unknown states', () => {
    expect(tab).toContain('暂无轮动数据')
    expect(tab).toContain('重试')
    expect(tab).toContain('state-unknown')
  })

  it('is wired as a rotation tab inside SectorPanel', () => {
    const panel = readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'SectorPanel.vue'), 'utf8')
    expect(panel).toContain("view === 'rotation'")
    expect(panel).toContain('轮动状态')
    expect(panel).toContain('SectorRotationTab')
  })
})
