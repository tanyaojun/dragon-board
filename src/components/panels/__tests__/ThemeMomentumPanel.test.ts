import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ThemeMomentumPanel', () => {
  const panel = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'ThemeMomentumPanel.vue'),
    'utf8',
  )
  const body = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'ThemeMomentumBody.vue'),
    'utf8',
  )
  const facade = readFileSync(
    join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'),
    'utf8',
  )
  const app = readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

  it('renders the embedded tree/detail momentum layout with full fields', () => {
    // 嵌入正文：左侧题材动量列表 + 右侧详情（参照 SectorStocksTree 风格）
    expect(body).toContain('momentum-tree')
    expect(body).toContain('momentum-detail')
    expect(body).toContain('RPS 5/10/20')
    expect(body).toContain('strength-badge')
    expect(body).toContain('progress-bar')
    expect(body).toContain('tree-pagination')
  })

  it('loads data via themeFacade.getThemeMomentumSummary', () => {
    expect(panel).toContain('getThemeMomentumSummary')
    expect(facade).toContain('/api/theme-momentum/summary')
    expect(facade).toContain('export async function getThemeMomentumSummary')
  })

  it('supports embedded mode rendered inside the sector tree panel', () => {
    expect(panel).toContain('embedded')
    expect(panel).toContain('ThemeMomentumBody')
    // 题材树形面板内嵌题材动量页签
    const tree = readFileSync(
      join(process.cwd(), 'src', 'components', 'panels', 'SectorStocksTree.vue'),
      'utf8',
    )
    expect(tree).toContain("activeTab === 'list'")
    expect(tree).toContain('ThemeMomentumPanel')
    expect(tree).toContain('embedded')
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
    expect(body).toContain('涨停')
    expect(body).toContain('factor.ztCount')
    expect(body).toContain('龙头/涨停')
    expect(body).toContain('selectedFactor.intraday?.unavailable')
    expect(body).toContain('依据')
    expect(body).toContain('selectedFactor.reasons')
  })
})
