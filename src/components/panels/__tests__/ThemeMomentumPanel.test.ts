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

  it('is no longer mounted standalone in App.vue (embedded in sector tree only)', () => {
    // 2026-09-25：题材动量面板仅作为 SectorStocksTree 内嵌页签存在，App.vue 不再独立挂载
    expect(app).not.toContain('ThemeMomentumPanel')
    expect(app).not.toContain('panels.themeMomentum')
  })

  it('opens SectorPanel when sector tab selected', () => {
    // 题材分析 tab → panelMap 映射到 SectorPanel 弹层
    expect(app).toContain("sector: 'sector'")
    expect(app).toContain('panels.value[panelMap[tabId]] = true')
    // 行情列表不承载题材动量列/字段点击入口
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
