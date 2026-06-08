import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelPath = () => join(process.cwd(), 'src', 'components', 'panels', 'CandidatePoolPanel.vue')
const panelSource = () => readFileSync(panelPath(), 'utf8')
const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('CandidatePoolPanel source contract', () => {
  test('provides a fusion lifecycle workbench backed by the candidate journal service', () => {
    expect(existsSync(panelPath())).toBe(true)
    const source = panelSource()

    expect(source).toContain('候选池')
    expect(source).toContain('Fusion 主线策略生命周期工作台')
    expect(source).toContain('策略事实')
    expect(source).toContain('执行事实')
    expect(source).toContain('对齐复盘')
    expect(source).toContain('入池理由')
    expect(source).toContain('交易假设')
    expect(source).toContain('失效条件')
    expect(source).toContain('假设编辑')
    expect(source).toContain('执行记录')
    expect(source).toContain('策略持有 bars')
    expect(source).toContain('候选层级')
    expect(source).toContain('生命周期动作')
    expect(source).toMatch(/candidateJournalService\.listCandidates/)
    expect(source).toMatch(/candidateJournalService\.updateCandidateThesis/)
    expect(source).toMatch(/candidateJournalService\.saveCandidateReview/)
    expect(source).toMatch(/candidateJournalService\.toExecutionOverlay/)
    expect(source).toMatch(/buildFusionStrategyProjection|buildFusionStrategyProjections/)
    expect(source).toMatch(/snapshotRankTrend\.lifecycle/)
    expect(source).toMatch(/const\s+strategyRows\s*=\s*computed/)
    expect(source).toMatch(/const\s+selectedRow\s*=\s*computed/)
    expect(source).toMatch(/const\s+thesisForm\s*=\s*ref/)
    expect(source).toMatch(/const\s+reviewForm\s*=\s*ref/)
    expect(source).toContain('执行记录保存失败')
    expect(source).not.toContain('建议入池')
    expect(source).not.toContain('候选质量')
    expect(source).not.toContain('候选漏斗')
    expect(source).not.toContain('当前重分析')
    expect(source).not.toContain('入池快照')
    expect(source).not.toContain('候选研究，不含交易盈亏')
  })

  test('registers the candidate pool panel in App without replacing favorites', () => {
    const source = appSource()

    expect(source).toMatch(/CandidatePoolPanel/)
    expect(source).toMatch(/candidatePool:\s*false/)
    expect(source).toMatch(/<CandidatePoolPanel\s+v-model:visible="panels\.candidatePool"/)
    expect(source).toContain("'candidate-pool:open'")
    expect(source).toContain('候选池')
    expect(source).toMatch(/<FavoritePanel\s+v-model:visible="panels\.favorite"/)
    expect(source).toContain("'rank-trend:open'")
    expect(source).toMatch(/<RankTrendPanel\s+:visible="panels\.rankTrend"/)
  })

  test('clears status filters before opening a candidate from the quote table', () => {
    const source = panelSource()

    expect(source).toMatch(/async function openCandidate\(target: \{ candidateId\?: string; stockCode\?: string \} = \{\}\)/)
    expect(source).toMatch(/const hasTarget = !!\(target\.candidateId \|\| target\.stockCode\)/)
    expect(source).toMatch(/statusFilter\.value = ''/)
    expect(source).toMatch(/keyword\.value = ''/)
    expect(source).toMatch(/await loadCandidates\(\)/)
    expect(source).toMatch(/if \(hasTarget && !matched\)/)
  })

  test('keeps candidate operations and lifecycle list controls', () => {
    const source = panelSource()

    expect(source).toContain('删除候选')
    expect(source).toContain('加入自选')
    expect(source).toContain('股票详情')
    expect(source).toContain('排名趋势')
    expect(source).toContain('策略状态')
    expect(source).toContain('排序方式')
    expect(source).toContain('代码 / 名称')
    expect(source).toMatch(/candidateJournalService\.deleteCandidate/)
    expect(source).toMatch(/candidateJournalService\.addCandidateToFavorites/)
    expect(source).toMatch(/EventManager\.emit\('stock:show-detail'/)
    expect(source).toMatch(/EventManager\.emit\('rank-trend:open'/)
    expect(source).toMatch(/const\s+visibleRows\s*=\s*computed/)
    expect(source).toMatch(/function strategyStateLabel/)
  })

  test('removes discovery and quality dashboards from the main candidate workbench', () => {
    const source = panelSource()

    expect(source).not.toMatch(/candidateDiscoveryService\.discover/)
    expect(source).not.toMatch(/buildCandidateQualityStats/)
    expect(source).not.toContain('刷新建议')
    expect(source).not.toContain('人工确认后入池')
    expect(source).not.toContain('质量拆解')
    expect(source).not.toContain('命中率')
    expect(source).not.toContain('平均跟踪')
  })

  test('keeps the candidate workbench layout as left list and right detail container', () => {
    const source = panelSource()
    const bodyIndex = source.indexOf('<div class="candidate-body">')
    const listIndex = source.indexOf('<aside class="candidate-list">')
    const detailIndex = source.indexOf('<main class="candidate-detail">')
    const strategyFactsIndex = source.indexOf('策略事实')

    expect(bodyIndex).toBeGreaterThan(0)
    expect(listIndex).toBeGreaterThan(bodyIndex)
    expect(detailIndex).toBeGreaterThan(listIndex)
    expect(strategyFactsIndex).toBeGreaterThan(detailIndex)
  })

  test('orders the right detail area as strategy facts plus overlay editing workflow', () => {
    const source = panelSource()
    const detailIndex = source.indexOf('<main class="candidate-detail">')
    const strategyFactsIndex = source.indexOf('策略事实')
    const executionFactsIndex = source.indexOf('执行事实')
    const thesisIndex = source.indexOf('假设编辑')
    const reviewIndex = source.indexOf('对齐复盘')

    expect(strategyFactsIndex).toBeGreaterThan(detailIndex)
    expect(executionFactsIndex).toBeGreaterThan(strategyFactsIndex)
    expect(thesisIndex).toBeGreaterThan(executionFactsIndex)
    expect(reviewIndex).toBeGreaterThan(thesisIndex)
  })

  test('uses dashboard-grade visual affordances for the fusion candidate pool surface', () => {
    const source = panelSource()

    expect(source).toContain('class="candidate-item-main"')
    expect(source).toContain('class="candidate-status"')
    expect(source).toContain('class="strategy-state-pill"')
    expect(source).toContain('class="fact-grid"')
    expect(source).toContain('--candidate-accent')
    expect(source).toMatch(/\.candidate-item\.active::before/)
    expect(source).toMatch(/:focus-visible/)
    expect(source).toMatch(/@media\s*\(max-width:\s*900px\)/)
  })

  test('uses high-contrast financial typography and color tokens', () => {
    const source = panelSource()

    expect(source).toContain('--candidate-font-data')
    expect(source).toContain('--candidate-bg: #111318')
    expect(source).toContain('--candidate-surface: #1b2028')
    expect(source).toContain('--candidate-text: #f4f7fb')
    expect(source).toContain('--candidate-accent: #ffb13b')
    expect(source).toMatch(/font-family:\s*var\(--candidate-font-ui\)/)
    expect(source).toMatch(/font-family:\s*var\(--candidate-font-data\)/)
    expect(source).toMatch(/\.fact-item/)
  })
})
