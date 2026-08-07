import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ThemeMomentumPanel', () => {
  const panel = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'ThemeMomentumPanel.vue'),
    'utf8',
  )
  const facade = readFileSync(
    join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'),
    'utf8',
  )
  const app = readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

  it('renders full-field momentum ranking table with expandable rows', () => {
    expect(panel).toContain('momentum-table')
    expect(panel).toContain('RPS 5/10/20')
    expect(panel).toContain('expanded.has')
    expect(panel).toContain('detail-row')
  })

  it('loads data via themeFacade.getThemeMomentumSummary', () => {
    expect(panel).toContain('getThemeMomentumSummary')
    expect(facade).toContain('/api/theme-momentum/summary')
    expect(facade).toContain('export async function getThemeMomentumSummary')
  })

  it('is mounted in App.vue with panel state', () => {
    expect(app).toContain('ThemeMomentumPanel')
    expect(app).toContain('panels.themeMomentum')
    expect(app).toContain('themeMomentum: false')
  })

  it('opens theme momentum panel when sector tab selected', () => {
    // 题材热点 tab → panelMap 映射到 themeMomentum（不再同开旧 SectorPanel）
    expect(app).toContain("sector: 'themeMomentum'")
    expect(app).toContain('panels.value[panelMap[tabId]] = true')
    // 行情列表不承载题材动量列/字段点击入口（面板仅由顶部 tab 打开）
    expect(app).not.toContain('openThemeMomentumFromTable')
  })

  it('shows ztCount column and intraday detail blocks', () => {
    expect(panel).toContain('涨停')
    expect(panel).toContain('factor.ztCount')
    expect(panel).toContain('龙头/涨停')
    expect(panel).toContain('factor.intraday?.unavailable')
  })
})
