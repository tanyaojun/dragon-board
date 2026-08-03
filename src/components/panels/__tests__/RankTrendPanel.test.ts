import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'RankTrendPanel.vue'), 'utf8')

describe('RankTrendPanel display contract', () => {
  test('uses lifecycle candidate semantics for the hero status', () => {
    const source = panelSource()

    expect(source).toMatch(/statusLabel:\s*breakdown\.tierLabel/)
    expect(source).toMatch(/statusClass:\s*breakdown\.classKeys\.tier/)
    expect(source).toMatch(/displayStatusLabel:\s*breakdown\.displayStatusLabel/)
    expect(source).toMatch(/riskLabel:\s*breakdown\.riskLabel/)
    expect(source).toMatch(/currentStock\.displayStatusLabel/)
    expect(source).toMatch(/currentStock\.riskLabel/)
    expect(source).not.toMatch(/statusLabel:\s*status\.label/)
    expect(source).not.toMatch(/statusClass:\s*status\.classKey/)
  })

  test('reuses the last panel result within 60s for the same stock and snapshot type', () => {
    const source = panelSource()

    expect(source).toMatch(/RANK_TREND_PANEL_RESULT_TTL_MS\s*=\s*60_000/)
    expect(source).toMatch(/cached\.key === reuseKey/)
    expect(source).toMatch(/Date\.now\(\) - cached\.at < RANK_TREND_PANEL_RESULT_TTL_MS/)
    expect(source).toMatch(/function refresh\(\)[\s\S]*loadStock\(true\)/)
  })

  test('loads rank history for the selected code only', () => {
    const source = panelSource()

    expect(source).toMatch(/getSnapshotsByType\(sourceType,\s*\{[\s\S]*?codes:\s*\[code\]/)
  })
})
