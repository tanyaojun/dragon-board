import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SectorRotationTab', () => {
  const tab = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTab.vue'),
    'utf8',
  )
  const facade = readFileSync(join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'), 'utf8')
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorRotationTree.vue'),
    'utf8',
  )

  it('fetches via themeFacade.getRotationSummary against the rotation summary API', () => {
    expect(tab).toContain('getRotationSummary')
    expect(facade).toContain('export async function getRotationSummary')
    expect(facade).toContain('/api/theme-rotation/summary')
    // 交互式读取：绕过后台轮询请求队列，避免页签"加载中"被队列滞留卡死
    expect(facade).toContain('bypassQueue: true')
    // 信封口径：theme-rotation 返回 {ok, status, data}（theme-momentum 平铺，两接口不一致），
    // facade 必须拆信封取 data，否则组件拿到信封体渲染即崩（2026-09-27 空白页根因）
    expect(facade).toContain('body?.ok === true && body.data ? body.data : null')
  })

  it('keeps the summary minimal: phase metrics + engine-mainline row only (fourth-round feedback)', () => {
    expect(tab).toContain('phase-badge')
    expect(tab).toContain('rotationSpeed')
    expect(tab).toContain('mainlineConcentration')
    expect(tab).toContain('maxBoardHeight')
    expect(tab).toContain('引擎判定无主线')
    // 流入/流出 chips 与 分布 计数行已删（与树形目录/明细表重复）
    expect(tab).not.toContain('inflowPreview')
    expect(tab).not.toContain('state-distribution')
    expect(tab).not.toContain('chip-inflow')
  })

  it('delegates the category directory and detail table to SectorRotationTree', () => {
    expect(tab).toContain('SectorRotationTree')
    expect(tab).toContain(':statuses="statuses"')
    expect(tab).toContain(':category="stateFilter"')
    expect(tab).toContain('@update:category="stateFilter = $event"')
    // 目录计数在树组件内维护
    expect(tree).toContain('DIRECTORY')
    // 展开题材状态表已删（与树形右栏明细表重复）
    expect(tab).not.toContain('展开题材状态表')
    expect(tab).not.toContain('visibleRows')
  })

  it('stays fail-visible on empty data', () => {
    expect(tab).toContain('暂无轮动数据')
    expect(tab).toContain('重试')
  })

  it('is wired as a rotation tab inside SectorPanel', () => {
    const panel = readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'SectorPanel.vue'), 'utf8')
    expect(panel).toContain("view === 'rotation'")
    expect(panel).toContain('轮动状态')
    expect(panel).toContain('SectorRotationTab')
  })
})
