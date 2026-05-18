import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotStockEventMonitorPanel.vue'), 'utf8')
const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')
const refreshTaskSource = () =>
  readFileSync(join(process.cwd(), 'src', 'services', 'refresh', 'RefreshTaskRegistry.ts'), 'utf8')

describe('HotStockEventMonitorPanel speech settings', () => {
  test('shows local voice select for local non-cloud speech engines', () => {
    const source = panelSource()

    expect(source).toContain('v-if="showSpeechVoiceSelect"')
    expect(source).toContain('v-model="speechVoice"')
    expect(source).toContain('speechEngine.value !== \'volcengine\'')
    expect(source).toContain('未检测到系统语音')
  })

  test('keeps settings page organized into filter and voice cards', () => {
    const source = panelSource()

    expect(source).toContain('filter-summary')
    expect(source).toContain('filter-chip')
    expect(source).toContain('speech-card-title')
    expect(source).toContain('footer-status')
  })

  test('shows search only on stock event tabs, not settings or sector tabs', () => {
    const source = panelSource()

    expect(source).toContain('v-if="showEventSearch"')
    expect(source).toContain('aria-label="搜索异动个股"')
    expect(source).toContain("activePage.value === 'hot' || activePage.value === 'other'")
    expect(source).toContain('const text = showEventSearch.value ? keyword.value.trim().toUpperCase() : \'\'')
    expect(source).not.toContain('settings-toolbar')
  })

  test('positions the panel as an abnormal-event radar instead of a trade journal', () => {
    const source = panelSource()
    const app = appSource()
    const refreshTask = refreshTaskSource()

    expect(source).toContain('<h3>异动雷达</h3>')
    expect(source).toContain('aria-label="关闭异动雷达"')
    expect(source).toContain('aria-label="异动雷达分类"')
    expect(app).toContain('title="异动雷达"')
    expect(app).toContain("{ id: 'events', label: '异动雷达', icon: '🔔' }")
    expect(refreshTask).toContain('异动雷达面板可见时轮询选股通异动数据')
    expect(source).not.toContain('历史交易日志')
  })

  test('bridges stock abnormal events into the candidate pool without using trade journal semantics', () => {
    const source = panelSource()

    expect(source).toMatch(/candidateJournalService\.listCandidates\(\s*\{\s*limit:\s*200\s*\}/)
    expect(source).toMatch(/candidateJournalService\.addCandidateFromStock\(\s*eventStock\(event\)/)
    expect(source).toMatch(/EventManager\.emit\('candidate-pool:open'/)
    expect(source).toContain('candidate-pool-actions')
    expect(source).toContain('龙头复盘')
    expect(source).toContain('已入候选池')
    expect(source).toContain("source: 'hot-stock-event-radar'")
    expect(source).not.toContain("trade_type: 'entry'")
    expect(source).not.toContain('TradeJournalPanel')
  })
})
