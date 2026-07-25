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

  test('only highlights positive opening weak-to-strong stages', () => {
    const source = dataTableSource()

    expect(source).toContain('isOpeningWeakToStrongHighlightStage')
    expect(source).toMatch(/hasOpeningWeakToStrongSignal[\s\S]*isOpeningWeakToStrongHighlightStage/)
    expect(source).toContain("stage === 'auctionConditionPassed'")
    expect(source).toContain("stage === 'gapAlert'")
    expect(source).toContain("stage === 'trendConfirm'")
  })

  test('does not render the redundant RankTrend lifecycle status column', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'strategyStatus'")
    expect(source).not.toContain("col.key === 'strategyStatus'")
    expect(source).not.toContain('strategy-status-cell')
    expect(source).not.toMatch(/:class="`status-\$\{getRankTrendBreakdown\(stock\)\.classKeys\.tier\}`"/)
    expect(source).not.toMatch(/classes\.push\(`strategy-tier-\$\{getRankTrendStatus\(stock\)\.classKey\}`\)/)
  })

  test('keeps RankTrend change and confidence visible after removing the status column', () => {
    const source = dataTableSource()

    expect(source).toContain('getRankTrendAnalysis(stock)?.change')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalSignal')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalConfidence')
    expect(source).toMatch(/const\s+getRankChange\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalSignal\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalConfidence\s*=\s*\(stock:\s*any\)\s*=>/)
  })

  test('shows jump confidence in the confidence column', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'confidence', label: '跃迁度'")
    expect(source).toContain('analyzeTradingPoolCandidate')
    expect(source).toContain('getTradingPoolActionPreview')
    expect(source).toContain('getJumpConfidence')
    expect(source).toContain('getRankTrendAnalysis(stock)?.jump?.confidence')
    expect(source).toMatch(/Math\.round\(getJumpConfidence\(stock\) \|\| 0\)/)
    expect(source).toContain('Jump跃迁')
    expect(source).toContain('共振强度')
    expect(source).toContain('交易池')
    expect(source).not.toContain('共振评级')
    expect(source).not.toMatch(/<span class="signal-percent">\{\{ Math\.round\(getFinalConfidence\(stock\) \|\| 0\) \}\}%<\/span>/)
  })

  test('shows resonance intensity column with color classes', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振强度'")
    expect(source).toContain('resonanceIntensity: \'80px\'')
    expect(source).toContain("col.key === 'resonanceIntensity'")
    expect(source).toContain('getResonanceCellValue')
    expect(source).toContain('getResonanceCellClass')
    expect(source).toContain('normalizeResonanceIntensity')
    expect(source).toContain('resonance-very-strong')
    expect(source).toContain('resonance-strong')
    expect(source).toContain('resonance-medium')
    expect(source).toContain('resonance-weak')
    expect(source).toContain('resonance-very-weak')
  })

  test('colors jump confidence by jump direction instead of final signal', () => {
    const source = dataTableSource()

    expect(source).toContain('const getJumpSignalBadgeClass = (stock: any) => {')
    expect(source).toContain("const jumpDirection = getJumpDirection(stock)")
    expect(source).toContain("if (jumpDirection === 'buy') return 'signal-badge buy-badge'")
    expect(source).toContain("if (jumpDirection === 'sell') return 'signal-badge sell-badge'")
    expect(source).toContain("if (jumpDirection === 'hold') return 'signal-badge hold-badge'")
    expect(source).toContain(':class="getJumpSignalBadgeClass(stock)"')
    expect(source).not.toContain("v-if=\"getFinalSignal(stock) === 'buy'\"")
    expect(source).not.toContain("v-else-if=\"getFinalSignal(stock) === 'sell'\"")
    expect(source).not.toContain("v-else-if=\"getFinalSignal(stock) === 'hold'\"")
  })

  test('uses one row-style tooltip for theme detail and removes rank-change noise', () => {
    const source = dataTableSource()

    expect(source).not.toMatch(/class="data-row"[\s\S]*@mouseenter="showRowTooltip\(\$event,\s*stock\)"/)
    expect(source).not.toContain(':title="getThemesTitle(getStockThemes(stock))"')
    expect(source).toContain('@mouseenter="showThemeTooltip($event, stock)"')
    expect(source).toContain('getMergedThemeTooltipTitle')
    expect(source).toContain('📋 关联原因')
    expect(source).not.toMatch(/const\s+getRowTitle[\s\S]*排名变化/)
  })

  test('does not render rarely used super-large money flow columns', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'cddje'")
    expect(source).not.toContain("{ key: 'cddjzb'")
    expect(source).not.toContain("case 'cddje'")
    expect(source).not.toContain("case 'cddjzb'")
  })

  test('labels THS L2 money flow appropriately', () => {
    const source = dataTableSource()

    expect(source).toContain('getMoneyFlowTitle')
    expect(source).toContain('同花顺L2主力监控')
    expect(source).toContain('QMT L2实时资金流')
  })

  test('keeps volume ratio display visually stable across data states', () => {
    const source = dataTableSource()

    expect(source).toMatch(/if \(key === 'volumeRatio'\)[\s\S]*classes\.push\('volume-ratio-cell'\)/)
    expect(source).not.toContain('volume-ratio-stale')
    expect(source).not.toContain('volume-ratio-suspicious')
    expect(source).not.toContain('volume-ratio-unavailable')
    expect(source).not.toContain('volume-ratio-high')
    expect(source).not.toContain('volume-ratio-low')
    expect(source).not.toContain("return `${ratio.toFixed(2)}*`")
    expect(source).not.toContain("return `!${ratio.toFixed(2)}`")
  })

  test('registers only currently visible rows as the table fund priority owner', () => {
    const source = dataTableSource()

    expect(source).toContain("realtimeSubscriptionRegistry.setFundOwnerCodes('datatable.visible'")
    expect(source).toContain("realtimeSubscriptionRegistry.clearFundOwner('datatable.visible')")
    expect(source).toContain("querySelectorAll<HTMLElement>('.data-row[data-code]')")
  })
})
