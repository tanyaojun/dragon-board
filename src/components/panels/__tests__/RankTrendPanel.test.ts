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
})
