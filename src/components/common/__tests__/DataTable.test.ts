import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const dataTableSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'common', 'DataTable.vue'), 'utf8')

const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('DataTable row detail interactions', () => {
  test('opens the stock detail panel from both the context menu and row double click', () => {
    const source = dataTableSource()

    expect(source).toMatch(/@dblclick="openStockDetailFromRow\(\$event,\s*stock\)"/)
    expect(source).toMatch(/const\s+openStockDetail\s*=\s*\(\s*stock:\s*Stock,\s*triggerRect:\s*DOMRect/)
    expect(source).toMatch(/const\s+viewDetails\s*=\s*\(\)\s*=>\s*{[\s\S]*openStockDetail\(\s*contextMenu\.value\.stock/)
    expect(source).toMatch(/const\s+openStockDetailFromRow\s*=\s*\(\s*event:\s*MouseEvent,\s*stock:\s*Stock/)
    expect(source).toMatch(/getBoundingClientRect\(\)\s*\?\?/)
    expect(source).toMatch(/openStockDetail\(\s*stock,\s*triggerRect,\s*'datatable-row-double-click'\s*\)/)
  })

  test('keeps DataTable as the only stock context menu entry point', () => {
    const source = dataTableSource()
    const app = appSource()

    expect(source).toMatch(/@contextmenu\.prevent="showContextMenu\(\$event,\s*stock\)"/)
    expect(app).not.toMatch(/<ContextMenu\b/)
    expect(app).not.toMatch(/import\s+ContextMenu\s+from/)
    expect(existsSync(join(process.cwd(), 'src', 'components', 'common', 'ContextMenu.vue'))).toBe(
      false,
    )
    expect(existsSync(join(process.cwd(), 'src', 'composables', 'useStockSelector.ts'))).toBe(false)
  })

  test('adds candidates from the row context menu through the candidate journal service', () => {
    const source = dataTableSource()

    expect(source).toMatch(/import\s+\{\s*candidateJournalService\s+\}\s+from\s+['"]@\/services\/candidate\/CandidateJournalService['"]/)
    expect(source).toMatch(/candidateMenuLabel/)
    expect(source).toContain('查看候选详情')
    expect(source).toMatch(/@click="addToCandidatePool"/)
    expect(source).toMatch(/const\s+addToCandidatePool\s*=\s*async\s*\(\)\s*=>/)
    expect(source).toMatch(/candidateJournalService\.getOpenCandidateForStock/)
    expect(source).toMatch(/candidateJournalService\.addCandidateFromStock\(\s*contextMenu\.value\.stock/)
    expect(source).toMatch(/EventManager\.emit\('candidate-pool:open'/)
    expect(source).not.toMatch(/\/api\/journal\/entries/)
    expect(source).not.toMatch(/trade_hypothesis/)
  })

  test('renders candidate pool status instead of legacy live signal labels', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'jumpSignal', label: '候选池'")
    expect(source).toContain('candidatePoolLabel')
    expect(source).toContain('candidate-pool-badge')
    expect(source).not.toContain('getLiveV3Signal(')
    expect(source).not.toContain('getLiveV3SignalDecision')
  })

  test('renders compact opening weak-to-strong badge in the stock name cell', () => {
    const source = dataTableSource()

    expect(source).toContain('opening-signal-badge')
    expect(source).toContain('opening-signal-row')
    expect(source).toContain('竞强')
    expect(source).toMatch(/openingSignalStore\.signalsByCode/)
    expect(source).toMatch(/openingSignalStore\.start\(\)/)
    expect(source).toMatch(/openingSignalStore\.stop\(\)/)
    expect(source).toMatch(/hasOpeningWeakToStrongSignal\(\s*stock\s*\)/)
    expect(source).not.toMatch(/fetchTodaySignals/)
    expect(source).not.toMatch(/openingSignalClient\.postSignal/)
  })

  test('renders RankTrend lifecycle tier from the display breakdown contract', () => {
    const source = dataTableSource()

    expect(source).toMatch(/getRankTrendBreakdown\(stock\)\.tierLabel/)
    expect(source).toMatch(/`strategy-tier-\$\{getRankTrendBreakdown\(stock\)\.classKeys\.tier\}`/)
    expect(source).toMatch(/formatRankTrendStatus\s*=\s*\(stock:\s*any\)\s*=>\s*getRankTrendBreakdown\(stock\)\.tierLabel/)
    expect(source).toMatch(/classes\.push\(`strategy-tier-\$\{getRankTrendBreakdown\(stock\)\.classKeys\.tier\}`\)/)
    expect(source).not.toMatch(/:class="`status-\$\{getRankTrendBreakdown\(stock\)\.classKeys\.tier\}`"/)
    expect(source).not.toMatch(/classes\.push\(`strategy-tier-\$\{getRankTrendStatus\(stock\)\.classKey\}`\)/)
  })
})
