import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'DragonBreathPanel.vue'), 'utf8')

describe('DragonBreathPanel（市场情绪，热榜情绪已迁出至 HotlistEmotionPanel）', () => {
  test('面板顶部文案与个股生命周期区分（市场情绪阶段）', () => {
    const source = panelSource()

    expect(source).toContain('<span class="sentiment-label">市场情绪阶段</span>')
    expect(source).not.toContain('<span class="sentiment-label">当前周期</span>')
  })

  test('热榜情绪视图与实现已移除（2026-09-24 迁移至独立 HotlistEmotionPanel）', () => {
    const source = panelSource()

    expect(source).not.toContain("view === 'hotlist'")
    expect(source).not.toContain('hotListSentiment')
    expect(source).not.toContain('hotlist-view')
    expect(source).not.toContain('ThemeTrend 共振解释')
  })
})
