// JEV 叙事面板源码合同（独立面板 v1.0，2026-10-08）：
// 独立轨道 = 只消费 /api/hotlist-jev/series|range；解耦硬边界 = 不触碰规则 EOD 与复核/概览混装读口。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'JevNarrativePanel.vue'), 'utf8')

/** 只取 <script setup> 代码段：解耦合同约束 import/运行时引用，不约束注释文档 */
const panelScriptSource = () => {
  const source = panelSource()
  const start = source.indexOf('<script setup lang="ts">')
  const end = source.indexOf('</script>')
  if (start < 0 || end < 0) throw new Error('script setup block not found')
  return source.slice(start, end)
}

const projectionSource = () =>
  readFileSync(join(process.cwd(), 'src', 'services', 'hotlist', 'jevNarrativeProjection.ts'), 'utf8')

describe('JevNarrativePanel 独立 JEV 叙事面板', () => {
  test('六个页签齐全（总览方格/温度计/拥挤度/置信度/叙事全文/原始返回）', () => {
    const source = panelSource()
    for (const key of ['grid', 'thermometer', 'crowding', 'confidence', 'narrative', 'raw']) {
      expect(source).toContain(`'${key}'`)
    }
    for (const label of ['总览方格', '温度计', '拥挤度', '置信度', '叙事全文', '原始返回']) {
      expect(source).toContain(label)
    }
  })

  test('解耦硬边界：只消费 jev 轨道读口，禁止规则 EOD / 复核 / 概览混装读口', () => {
    const script = panelScriptSource()
    // 允许：jev 独立轨道读口 + 投影模块 + 类型
    expect(script).toContain('fetchHotlistJevSeries')
    expect(script).toContain('fetchHotlistJevRange')
    expect(script).toContain('jevNarrativeProjection')
    // 禁止：jev+规则同包读口、复核工作台、规则情绪 API、韭研卡
    expect(script).not.toContain('fetchHotlistSentimentOverview')
    expect(script).not.toContain('fetchJevReviewList')
    expect(script).not.toContain('postJevReviewRuling')
    expect(script).not.toContain("from '@/services/hotlist/hotlistSentimentApi'")
    expect(script).not.toContain('fetchJiuyanAction')
    expect(script).not.toContain('hotlist_sentiment')
    // 禁止：规则 EOD 概念字段出现在运行时代码
    expect(script).not.toContain('emotionScore')
    expect(script).not.toContain('ruleEod')
  })

  test('全量展示合同：叙事无截断 + 原始返回三类全渲染 + fail-visible 占位', () => {
    const source = panelSource()
    // 叙事全文：不得再设 240px 类截断（max-height: none + 结构化分段）
    expect(source).toContain('narrative-text')
    expect(source).toContain('max-height: none')
    expect(source).toContain('narrative-section-title')
    // 原始返回：responseRaw / questionsRaw / evidenceRaw 三类 + 信封元信息
    expect(source).toContain('rawResponseText')
    expect(source).toContain('rawQuestionsText')
    expect(source).toContain('evidenceGroups')
    expect(source).toContain('rawEnvelopeText')
    // fail-visible：缺失 '--' 占位、降级标注、score 型无分布显式标注
    expect(source).toContain("cell.text ?? '--'")
    expect(source).toContain('无分布')
    expect(source).toContain('errorDetail')
    // EOD 未生成/缺失日如实标注
    expect(source).toContain('EOD 未生成')
    expect(source).toContain('窗口缺失')
  })

  test('三大焦点可视化合同：温度计 SVG+锚分位 / 拥挤 waffle+层带+饼图 / 置信矩阵+趋势+分布明细', () => {
    const source = panelSource()
    // 温度计：SVG 几何 + 近20日参照分位卡 + REVERSE 注记
    expect(source).toContain('thermo-svg')
    expect(source).toContain('anchorMetrics')
    expect(source).toContain('REVERSE')
    expect(source).toContain('近20日参照')
    // 拥挤度：waffle 方格 + 当日层带 + 层迁移 + 逃生率 + 毒层注记；窗口层分布用饼图（占比语义，评审修正）
    expect(source).toContain('waffleSquares')
    expect(source).toContain('crowding-strip')
    expect(source).toContain('crowdingTransitions')
    expect(source).toContain('escapeRate')
    expect(source).toContain('毒层')
    expect(source).toContain("type: 'pie'")
    expect(source).not.toContain("stack: 'layers'")
    // 置信度：矩阵 + 趋势线（犹豫阈值 markLine）+ margin/熵派生指标 + 答案分布明细（choice 全分布 + score 锚点）
    expect(source).toContain('confidenceRows')
    expect(source).toContain('犹豫阈值')
    expect(source).toContain('margin')
    expect(source).toContain('熵')
    expect(source).toContain('distRows')
    expect(source).toContain('score 锚点')
    // ECharts 三图容器
    expect(source).toContain('thermoChartRef')
    expect(source).toContain('crowdingChartRef')
    expect(source).toContain('confidenceChartRef')
  })
})

describe('jevNarrativeProjection 投影模块合同', () => {
  test('纯函数面：分段/锚分位/置信/时间线/方格/层统计 全部导出', () => {
    const source = projectionSource()
    for (const fn of [
      'parseNarrativeSections',
      'findNarrativeSection',
      'parseAnchorQuantiles',
      'anchorMetricsOfDoc',
      'confidenceMetrics',
      'crowdingTimeline',
      'crowdingTransitions',
      'layerStats',
      'buildSlotGrid',
      'buildDayGrid',
    ]) {
      expect(source).toContain(`export function ${fn}`)
    }
    // fail-visible 契约：score 型显式无分布 + 犹豫阈值常量唯一来源
    expect(source).toContain('noDistribution')
    expect(source).toContain('JEV_HESITANT_THRESHOLD')
  })

  test('投影模块不引入 fetch / IO（纯函数层零副作用）', () => {
    const source = projectionSource()
    expect(source).not.toContain('fetch(')
    expect(source).not.toContain('await ')
    expect(source).not.toContain('new Promise')
  })
})
