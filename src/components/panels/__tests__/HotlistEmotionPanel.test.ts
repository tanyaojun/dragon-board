import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

// 独立热榜情绪面板源码合同（2026-09-24）：
// 口径 = docs/hotlist-emotion-panel/01-口径梳理.md 全量；风格 = 主题变量（SectorDetail 语言）。
const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotlistEmotionPanel.vue'), 'utf8')

describe('HotlistEmotionPanel 独立热榜情绪面板', () => {
  test('七个页签齐全（概览/分层/涨停/状态/三日/轨迹/证据）', () => {
    const source = panelSource()

    for (const key of ['overview', 'layers', 'limit', 'structure', 'compare', 'track', 'evidence']) {
      expect(source).toContain(`'${key}'`)
    }
    for (const label of ['热榜概览', '分层结构', '涨停证据', '状态结构', '三日对比', '日内轨迹', '证据与风险']) {
      expect(source).toContain(label)
    }
  })

  test('fail-visible：缺失显示 -- 占位，不伪造 0（三日对比/分层/换手）', () => {
    const source = panelSource()

    expect(source).toContain('formatNullableCount')
    expect(source).toContain("counts ? formatNullableCount(counts.cooling) : '--'")
    expect(source).not.toContain('stageCounts?.cooling ?? 0')
  })

  test('诊断与业务提示分离：diagnostics 独立区块', () => {
    const source = panelSource()

    expect(source).toContain('doc.warnings')
    expect(source).toContain('diag-block')
    expect(source).toContain('数据诊断')
  })

  test('情绪路径双轨：确认阶段为主值，分歧用人话小标（短暂走高/回落）', () => {
    const source = panelSource()

    expect(source).toContain('stageDriftText')
    expect(source).toContain('短暂走高')
    expect(source).toContain('短暂回落')
    expect(source).toContain('rawStage || slot.stage')
    expect(source).toContain('pendingSince')
    expect(source).not.toContain('截面置信')
    expect(source).not.toContain('当前截面证据')
  })

  test('池换手独立页签：分池出池合并单表，成分股列表语言（2026-09-24 用户裁决）', () => {
    const source = panelSource()

    // 独立页签，位置在状态结构之前
    expect(source).toContain("{ key: 'turnover', label: '池换手', icon: '🔁' }")
    // 合并单表 + 类型筛选（全部/新入/剔除）+ 统计行
    expect(source).toContain('mergedTurnoverRows')
    expect(source).toContain('turnoverFilter')
    expect(source).toContain('新入 {{ entryDetails.length }} · 剔除 {{ exitDetails.length }}')
    // 成分股列表语言：sticky 表头/行 hover/代码下划线/类型徽章/原因省略
    expect(source).toContain('to-table-container')
    expect(source).toContain('to-code')
    expect(source).toContain('to-kind-badge')
    expect(source).toContain('涨停入选')
    expect(source).toContain('跌出榜单')
  })

  test('涨停证据显式区分口径：全市场背景标注非热榜池', () => {
    const source = panelSource()

    expect(source).toContain('非热榜池口径')
    expect(source).toContain('board4Plus')
    expect(source).toContain('yesterdayHotLimit')
  })

  test('风格走主题变量（SectorDetail 语言），不继承旧面板金融渐变', () => {
    const source = panelSource()

    expect(source).toContain('var(--bg-primary)')
    expect(source).toContain('var(--bg-secondary)')
    expect(source).toContain('var(--color-highlight)')
    // 旧面板的紫色渐变与发光风格不得回流
    expect(source).not.toContain('linear-gradient(135deg, #667eea')
    expect(source).not.toContain('dragon-gradient')
  })

  test('与 DragonBreathPanel 脱钩：不 import 其私有模块', () => {
    const source = panelSource()

    expect(source).not.toContain('DragonBreathAnalyzer')
    expect(source).not.toContain("from './DragonBreathPanel")
    expect(source).toContain('fetchHotlistSentimentSeries')
    expect(source).toContain('fetchHotlistSentimentSlots')
  })
})
