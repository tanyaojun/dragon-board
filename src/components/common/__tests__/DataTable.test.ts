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

  test('keeps RankTrend change and jump evidence for tooltip after removing their columns', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'rankChange'")
    expect(source).not.toContain("{ key: 'confidence'")
    expect(source).toContain('getRankTrendAnalysis(stock)?.change')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalSignal')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalConfidence')
    expect(source).toMatch(/const\s+getRankChange\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalSignal\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalConfidence\s*=\s*\(stock:\s*any\)\s*=>/)
  })

  test('keeps jump confidence in the shared observation tooltip', () => {
    const source = dataTableSource()

    expect(source).not.toContain("label: '跃迁度'")
    expect(source).toContain('analyzeTradingPoolCandidate')
    expect(source).toContain('getTradingPoolActionPreview')
    expect(source).toContain('getJumpConfidence')
    expect(source).toContain('getRankTrendAnalysis(stock)?.jump?.confidence')
    expect(source).toContain('Jump事件')
    expect(source).toContain('共振强度')
    expect(source).not.toContain('📌 交易池:')
    expect(source).not.toContain('共振评级')
    expect(source).not.toMatch(/<span class="signal-percent">\{\{ Math\.round\(getFinalConfidence\(stock\) \|\| 0\) \}\}%<\/span>/)
  })

  test('shows resonance intensity column with directional color classes', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("resonanceIntensity: '52px'")
    expect(source).toContain("col.key === 'resonanceIntensity'")
    expect(source).toContain('getResonanceCellValue')
    expect(source).toContain('getResonanceCellClass')
    expect(source).toContain('@mouseenter="showConfidenceTooltip($event, stock, \'resonanceIntensity\')"')
    expect(source).toContain('rankTrend?.resonance')
    expect(source).toContain('相对市场')
    expect(source).toContain('路径持续性')
    expect(source).toContain('新鲜度')
    expect(source).toContain('市场中位数（同帧共享）')
    expect(source).toContain('数据来源: 八平台均榜横截面')
    expect(source).toContain("resonance.historyState === 'new_entry'")
    expect(source).not.toContain('resonance.qualityCap')
    expect(source).not.toContain('normalizeResonanceIntensity')
    expect(source).toContain('observation-buy')
    expect(source).toContain('observation-sell')
    expect(source).toContain('observation-hold')
    expect(source).not.toContain('resonance-very-strong')
  })

  test('shows three independent observation columns with dedicated panel tracks', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("{ key: 'rankTrendStrength', label: '趋势'")
    expect(source).toContain("{ key: 'lifecycleOpportunity', label: '周期'")
    expect(source).toContain("rankTrendStrength: '52px'")
    expect(source).toContain("lifecycleOpportunity: '64px'")
    expect(source).toContain("openObservationPanel(stock, 'resonance')")
    expect(source).toContain("openObservationPanel(stock, 'technical')")
    expect(source).toContain("openObservationPanel(stock, 'lifecycle')")
    expect(source).toContain('getRankTrendStrengthValue')
    expect(source).toContain('getLifecycleOpportunityValue')
    expect(source).toContain('RankTrendObservationPanel')
    expect(source).toContain('v-if="getRankTrendStrengthValue(stock) != null"')
    expect(source).toContain('v-if="getLifecycleOpportunityValue(stock) != null"')
    expect(source).toContain('getResonanceDirection(stock)')
    expect(source).toContain('toFiniteObservationValue')
    expect(source).toContain('<span v-else class="trend-steady">--</span>')
    // 量价配合：独立四象限列，样式/ tooltip 参照三指标观察列；数据由后端生产（_volumePrice*）前端只消费
    expect(source).toContain("{ key: 'volumePriceQuadrant', label: '量价'")
    expect(source).toContain("volumePriceQuadrant: '52px'")
    expect(source).toContain('_volumePriceScore')
    expect(source).toContain('_volumePriceQuadrant')
    expect(source).toContain('getQuadrantText')
    // 投影缺失时回退 rankTrend.observation.volumePrice（与三轨读取口径一致，缓存预热可显示）
    expect(source).toContain('getVolumePrice')
    expect(source).toContain('stock?._volumePriceScore ?? vp.score')
    expect(source).toContain("getRankTrendAnalysis(stock)?.observation?.volumePrice")
    expect(source).toContain("@mouseenter=\"showConfidenceTooltip($event, stock, 'volumePriceQuadrant')\"")
    expect(source).toContain("field === 'volumePriceQuadrant'")
    expect(source).toContain('【量价配合】')
    // 前端不生产量价评分（后端 observation.volumePrice）
    expect(source).not.toContain('computeVolumePriceScore')
    expect(source).not.toContain('classifyVolumePriceQuadrant')
    expect(source).not.toContain('resolveLiveLimitState')
    // 三指标数值列保持紧凑：不混入中文确认标记
    expect(source).not.toContain('vp-badge')
    expect(source).not.toContain('getVolumePriceBadge')
  })

  test('splits observation tooltips per field (D: resonance/rankTrend/lifecycle)', () => {
    const source = dataTableSource()

    // 分派入口：showConfidenceTooltip 接收第三参数 field
    expect(source).toContain('const showConfidenceTooltip = (event: MouseEvent, stock: any, field = \'\')')
    expect(source).toContain('const getFieldTooltip = (field: string, stock: any): string => {')

    // 三列分别传自己的 field，不共用同一份内容
    expect(source).toContain("showConfidenceTooltip($event, stock, 'resonanceIntensity')")
    expect(source).toContain("showConfidenceTooltip($event, stock, 'rankTrendStrength')")
    expect(source).toContain("showConfidenceTooltip($event, stock, 'lifecycleOpportunity')")

    // 共振分支只含共振专属内容
    expect(source).toContain("if (field === 'resonanceIntensity') {")
    expect(source).toContain('【共振】')
    // 排名趋势分支
    expect(source).toContain("if (field === 'rankTrendStrength') {")
    expect(source).toContain('【排名趋势】')
    // 生命周期分支
    expect(source).toContain("if (field === 'lifecycleOpportunity') {")
    expect(source).toContain('【生命周期】')
    // 兜底：无 field 时仍是完整置信度
    expect(source).toContain('content: field ? getFieldTooltip(field, stock) : getConfidenceTitle(stock)')
  })

  test('market table does not include a theme momentum column (panel only)', () => {
    const source = dataTableSource()

    // 行情列表不渲染题材动量列（题材动量仅在独立面板 / 顶部 tab）
    expect(source).not.toContain("{ key: 'themeMomentum'")
    expect(source).not.toContain("col.key === 'themeMomentum'")
    expect(source).not.toContain('open-theme-momentum')
    // 其余三列仍在
    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("{ key: 'rankTrendStrength', label: '趋势'")
    expect(source).toContain("{ key: 'lifecycleOpportunity', label: '周期'")
  })

  test('structures the confidence tooltip as conclusion, resonance, technical, and risk layers', () => {
    const source = dataTableSource()

    expect(source).toContain('【观察结论】')
    expect(source).toContain('【共振路径】')
    expect(source).toContain('【技术结构】')
    expect(source).toContain('【阶段与风险】')
    expect(source).toContain('共振方向:')
    expect(source).toContain('共振强度:')
    expect(source).toContain('Jump事件:')
    expect(source).toContain('新鲜度')
    expect(source).toContain('过热风险:')
    expect(source).toContain('资金背离风险:')
    expect(source).not.toContain('🎯 综合判断:')
    expect(source).not.toContain('🔥 过热反转风险:')
    expect(source).not.toContain('💰 热度资金背离:')
  })

  test('keeps jump direction evidence in the tooltip after removing its badge column', () => {
    const source = dataTableSource()

    expect(source).toContain("const jumpDir = getJumpDirection(stock)")
    expect(source).toContain('Jump事件:')
    expect(source).not.toContain(':class="getJumpSignalBadgeClass(stock)"')
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
    expect(source).toContain('同花顺个股资金流')
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

  test('resonance tooltip decoupled from theme momentum (D2)', () => {
    const source = dataTableSource()

    expect(source).not.toContain('【题材动量】')
    expect(source).not.toContain('themeMomentumScore')
    expect(source).not.toContain('resonance.theme')
  })

})
