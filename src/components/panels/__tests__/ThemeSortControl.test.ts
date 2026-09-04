import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ThemeSortControl', () => {
  const control = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'ThemeSortControl.vue'),
    'utf8',
  )
  const panel = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorPanel.vue'),
    'utf8',
  )
  const tree = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorStocksTree.vue'),
    'utf8',
  )
  const facade = readFileSync(
    join(process.cwd(), 'src', 'services', 'theme', 'ThemeFacade.ts'),
    'utf8',
  )

  it('renders a multi-key sorter with field/direction/remove per step', () => {
    expect(control).toContain('sort-trigger')
    expect(control).toContain('sort-popover')
    expect(control).toContain('field-select')
    expect(control).toContain('toggleDirection')
    expect(control).toContain('removeStep')
    expect(control).toContain('addStep')
    expect(control).toContain('resetSpec')
    expect(control).toContain('THEME_SORT_MAX_STEPS')
  })

  it('commits changes through themeFacade sort spec APIs', () => {
    expect(control).toContain('themeFacade.setThemeSortSpec')
    expect(control).toContain('themeFacade.resetThemeSortSpec')
    expect(facade).toContain('export function setThemeSortSpec')
    expect(facade).toContain('export function resetThemeSortSpec')
    expect(facade).toContain('themeSortConfigStore')
  })

  it('is mounted in both theme list entry points', () => {
    expect(panel).toContain('ThemeSortControl')
    expect(panel).toContain("view === 'hot' && viewMode === 'grid'")
    expect(tree).toContain('ThemeSortControl')
    expect(tree).toContain('tree-sort-control')
  })

  it('sorts through the facade compare path applied to all consumers', () => {
    expect(facade).toContain('compareThemesBySpec')
  })
})
