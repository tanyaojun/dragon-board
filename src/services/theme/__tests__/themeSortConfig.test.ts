import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  compareThemesBySpec,
  DEFAULT_THEME_SORT_SPEC,
  normalizeThemeSortSpec,
  THEME_SORT_FIELDS,
  THEME_SORT_MAX_STEPS,
  ThemeSortConfigStore,
  type ThemeSortField,
  type ThemeSortSpec,
} from '../themeSortConfig'

type SortRow = Partial<Record<ThemeSortField, number | null>>

function row(overrides: SortRow): SortRow {
  return {
    heatScore: 0,
    ztCount: 0,
    momentumScore: 0,
    mainNetInflow: 0,
    volumeRatio: 0,
    fundScore: 0,
    ...overrides,
  }
}

describe('normalizeThemeSortSpec', () => {
  it('falls back to the default spec for non-array input', () => {
    expect(normalizeThemeSortSpec(null)).toEqual(DEFAULT_THEME_SORT_SPEC)
    expect(normalizeThemeSortSpec(undefined)).toEqual(DEFAULT_THEME_SORT_SPEC)
    expect(normalizeThemeSortSpec('heat')).toEqual(DEFAULT_THEME_SORT_SPEC)
  })

  it('falls back to the default spec for an empty spec', () => {
    expect(normalizeThemeSortSpec([])).toEqual(DEFAULT_THEME_SORT_SPEC)
  })

  it('drops steps with unknown fields or directions', () => {
    const spec = normalizeThemeSortSpec([
      { field: 'hack', direction: 'desc' },
      { field: 'ztCount', direction: 'desc' },
      { field: 'heatScore', direction: 'up' },
    ])
    expect(spec).toEqual([{ field: 'ztCount', direction: 'desc' }])
  })

  it('keeps the first step when a field repeats', () => {
    const spec = normalizeThemeSortSpec([
      { field: 'heatScore', direction: 'desc' },
      { field: 'heatScore', direction: 'asc' },
      { field: 'ztCount', direction: 'asc' },
    ])
    expect(spec).toEqual([
      { field: 'heatScore', direction: 'desc' },
      { field: 'ztCount', direction: 'asc' },
    ])
  })

  it('caps the spec at the max number of steps', () => {
    const spec = normalizeThemeSortSpec([
      { field: 'heatScore', direction: 'desc' },
      { field: 'ztCount', direction: 'asc' },
      { field: 'momentumScore', direction: 'desc' },
      { field: 'volumeRatio', direction: 'asc' },
    ])
    expect(spec).toEqual([
      { field: 'heatScore', direction: 'desc' },
      { field: 'ztCount', direction: 'asc' },
      { field: 'momentumScore', direction: 'desc' },
    ])
    expect(spec.length).toBe(THEME_SORT_MAX_STEPS)
  })

  it('keeps every whitelisted field sortable', () => {
    expect(THEME_SORT_FIELDS).toEqual([
      'heatScore',
      'ztCount',
      'momentumScore',
      'mainNetInflow',
      'volumeRatio',
      'fundScore',
    ])
  })
})

describe('compareThemesBySpec', () => {
  it('sorts by a single field descending', () => {
    const spec: ThemeSortSpec = [{ field: 'heatScore', direction: 'desc' }]
    const rows = [row({ heatScore: 55 }), row({ heatScore: 99 }), row({ heatScore: 70 })]
    const sorted = [...rows].sort((a, b) => compareThemesBySpec(a, b, spec))
    expect(sorted.map((r) => r.heatScore)).toEqual([99, 70, 55])
  })

  it('sorts by a single field ascending', () => {
    const spec: ThemeSortSpec = [{ field: 'ztCount', direction: 'asc' }]
    const rows = [row({ ztCount: 8 }), row({ ztCount: 0 }), row({ ztCount: 3 })]
    const sorted = [...rows].sort((a, b) => compareThemesBySpec(a, b, spec))
    expect(sorted.map((r) => r.ztCount)).toEqual([0, 3, 8])
  })

  it('falls through to later keys when earlier keys tie', () => {
    const spec: ThemeSortSpec = [
      { field: 'heatScore', direction: 'desc' },
      { field: 'ztCount', direction: 'desc' },
    ]
    const rows = [
      row({ heatScore: 70, ztCount: 2 }),
      row({ heatScore: 99, ztCount: 0 }),
      row({ heatScore: 70, ztCount: 5 }),
    ]
    const sorted = [...rows].sort((a, b) => compareThemesBySpec(a, b, spec))
    expect(sorted.map((r) => r.ztCount)).toEqual([0, 5, 2])
  })

  it('pushes null and non-finite values to the tail regardless of direction', () => {
    const descSpec: ThemeSortSpec = [{ field: 'mainNetInflow', direction: 'desc' }]
    const ascSpec: ThemeSortSpec = [{ field: 'mainNetInflow', direction: 'asc' }]
    const rows = [
      row({ mainNetInflow: 100 }),
      row({ mainNetInflow: null }),
      row({ mainNetInflow: -100 }),
      row({ mainNetInflow: Number.NaN }),
    ]
    const sortedDesc = [...rows].sort((a, b) => compareThemesBySpec(a, b, descSpec))
    const sortedAsc = [...rows].sort((a, b) => compareThemesBySpec(a, b, ascSpec))
    // 有效值按方向排序，null/NaN 一律落在有效值之后（相对顺序稳定）
    expect(sortedDesc.map((r) => r.mainNetInflow)).toEqual([100, -100, null, Number.NaN])
    expect(sortedAsc.map((r) => r.mainNetInflow)).toEqual([-100, 100, null, Number.NaN])
  })

  it('appends unused default keys for deterministic ordering', () => {
    const spec: ThemeSortSpec = [{ field: 'momentumScore', direction: 'desc' }]
    const rows = [
      row({ momentumScore: 70, heatScore: 50, ztCount: 3 }),
      row({ momentumScore: 70, heatScore: 90, ztCount: 1 }),
      row({ momentumScore: 70, heatScore: 90, ztCount: 6 }),
    ]
    const sorted = [...rows].sort((a, b) => compareThemesBySpec(a, b, spec))
    expect(sorted.map((r) => r.heatScore)).toEqual([90, 90, 50])
    expect(sorted.map((r) => r.ztCount)).toEqual([6, 1, 3])
  })

  it('does not duplicate user keys when appending default tie-breakers', () => {
    const spec: ThemeSortSpec = [{ field: 'heatScore', direction: 'asc' }]
    const rows = [
      row({ heatScore: 70, ztCount: 2 }),
      row({ heatScore: 70, ztCount: 9 }),
    ]
    const sorted = [...rows].sort((a, b) => compareThemesBySpec(a, b, spec))
    expect(sorted.map((r) => r.ztCount)).toEqual([9, 2])
  })
})

describe('ThemeSortConfigStore persistence', () => {
  const storageBacking = new Map<string, string>()

  afterEach(() => {
    vi.unstubAllGlobals()
    storageBacking.clear()
  })

  function stubStorage() {
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storageBacking.get(key) ?? null,
      setItem: (key: string, value: string) => void storageBacking.set(key, value),
      removeItem: (key: string) => void storageBacking.delete(key),
    })
  }

  it('persists a saved spec and reloads it in a new store instance', () => {
    stubStorage()
    const store = new ThemeSortConfigStore()
    store.save([{ field: 'momentumScore', direction: 'desc' }])

    const reloaded = new ThemeSortConfigStore()
    expect(reloaded.getSpec()).toEqual([{ field: 'momentumScore', direction: 'desc' }])
  })

  it('falls back to the default spec when stored JSON is corrupted', () => {
    stubStorage()
    storageBacking.set('theme_sort_config', '{broken json')
    const store = new ThemeSortConfigStore()
    expect(store.getSpec()).toEqual(DEFAULT_THEME_SORT_SPEC)
  })

  it('reset removes the persisted key so future default changes are not frozen', () => {
    stubStorage()
    const store = new ThemeSortConfigStore()
    store.save([{ field: 'momentumScore', direction: 'desc' }])
    expect(storageBacking.has('theme_sort_config')).toBe(true)

    store.reset()
    expect(storageBacking.has('theme_sort_config')).toBe(false)
    expect(store.getSpec()).toEqual(DEFAULT_THEME_SORT_SPEC)
  })

  it('works without localStorage (node/test environment)', () => {
    const store = new ThemeSortConfigStore()
    expect(store.save([{ field: 'ztCount', direction: 'asc' }])).toEqual([
      { field: 'ztCount', direction: 'asc' },
    ])
  })
})
