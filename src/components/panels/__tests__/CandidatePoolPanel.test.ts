import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelPath = () => join(process.cwd(), 'src', 'components', 'panels', 'CandidatePoolPanel.vue')
const panelSource = () => readFileSync(panelPath(), 'utf8')
const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('CandidatePoolPanel source contract', () => {
  test('provides a candidate workbench backed by the candidate journal service', () => {
    expect(existsSync(panelPath())).toBe(true)
    const source = panelSource()

    expect(source).toContain('候选池')
    expect(source).toMatch(/candidateJournalService\.listCandidates/)
    expect(source).toMatch(/candidateJournalService\.updateCandidateStatus/)
    expect(source).toContain('入池理由')
    expect(source).toContain('交易假设')
    expect(source).toContain('失效条件')
    expect(source).toContain('规则分析')
    expect(source).toContain('今日新增')
    expect(source).toContain('平均评分')
    expect(source).toContain('当前重分析')
    expect(source).toContain('入池快照')
    expect(source).toContain('假设编辑')
    expect(source).toContain('写回当前分析')
    expect(source).toContain('复盘闭环')
    expect(source).toContain('触发率')
    expect(source).toContain('失效率')
    expect(source).toContain('复盘胜率')
    expect(source).toMatch(/stateLabel/)
    expect(source).toMatch(/candidateJournalService\.reanalyzeCandidate/)
    expect(source).toMatch(/candidateJournalService\.updateCandidateThesis/)
    expect(source).toMatch(/candidateJournalService\.writeBackCurrentAnalysis/)
    expect(source).toMatch(/candidateJournalService\.saveCandidateReview/)
    expect(source).toMatch(/const\s+candidateStats\s*=\s*computed/)
    expect(source).toMatch(/const\s+selectedReview\s*=\s*computed/)
    expect(source).toMatch(/const\s+thesisForm\s*=\s*ref/)
    expect(source).toMatch(/const\s+reviewForm\s*=\s*ref/)
    expect(source).toContain('候选状态更新失败')
    expect(source).toMatch(/async function updateStatus\(status: CandidateStatus\)/)
    expect(source).toMatch(/try\s*\{\s*const updated = await candidateJournalService\.updateCandidateStatus/)
  })

  test('registers the candidate pool panel in App without replacing favorites', () => {
    const source = appSource()

    expect(source).toMatch(/CandidatePoolPanel/)
    expect(source).toMatch(/candidatePool:\s*false/)
    expect(source).toMatch(/<CandidatePoolPanel\s+v-model:visible="panels\.candidatePool"/)
    expect(source).toContain("'candidate-pool:open'")
    expect(source).toContain('候选池')
    expect(source).toMatch(/<FavoritePanel\s+v-model:visible="panels\.favorite"/)
  })

  test('clears status filters before opening a candidate from the quote table', () => {
    const source = panelSource()

    expect(source).toMatch(/async function openCandidate\(target: \{ candidateId\?: string; stockCode\?: string \} = \{\}\)/)
    expect(source).toMatch(/const hasTarget = !!\(target\.candidateId \|\| target\.stockCode\)/)
    expect(source).toMatch(/statusFilter\.value = ''/)
    expect(source).toMatch(/await loadCandidates\(\)/)
    expect(source).toMatch(/if \(hasTarget && !matched\)/)
  })
})
