import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelPath = () => join(process.cwd(), 'src', 'components', 'panels', 'FavoritePanel.vue')
const panelSource = () => readFileSync(panelPath(), 'utf8')

describe('FavoritePanel sync-to-candidate-pool source contract', () => {
  test('sync button wires the favorite pool into the candidate pool panel', () => {
    expect(existsSync(panelPath())).toBe(true)
    const source = panelSource()

    // 同步按钮绑定新逻辑而非旧的行情价格同步
    expect(source).toMatch(/<button class="btn-text" @click="syncToCandidatePool">/)
    expect(source).not.toMatch(/@click="syncWithMarketData"/)

    // 调用候选池服务批量同步并打开候选池面板
    expect(source).toContain('candidateJournalService')
    expect(source).toMatch(/candidateJournalService\.syncFavoritesToCandidatePool\(/)
    expect(source).toContain("source: 'favorite-panel-sync'")
    expect(source).toMatch(/'candidate-pool:open'/)
    expect(source).toContain('已同步')
  })
})
