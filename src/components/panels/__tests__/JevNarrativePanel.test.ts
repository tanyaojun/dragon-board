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
    for (const label of ['叙事概览', '温度计', '拥挤度', '置信度', '叙事全文', '原始返回']) {
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
    expect(source).toContain("?? '--'")
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
    // score 型（温度）纠错（2026-10-02）：实测携带锚点分布+置信，不再误标「无分布」——
    // 矩阵格 C%=模型置信（不套 P 阈值色），明细卡渲染锚点分布条+锚期望，仅确缺失才标无分布
    expect(source).toContain("metrics.kind === 'score'")
    expect(source).toContain('锚期望')
    expect(source).toContain('anchorTone')
    expect(source).toContain('scoreNoDist')
    expect(source).toContain('score 型分布=10 档锚点概率')
    // ECharts 三图容器
    expect(source).toContain('thermoChartRef')
    expect(source).toContain('crowdingChartRef')
    expect(source).toContain('confidenceChartRef')
  })

  test('总览页视觉对齐热榜情绪面板（2026-10-03 用户裁决弃用大色块矩阵）', () => {
    const source = panelSource()
    // hero 大卡 + 圆徽指标卡 + 紧凑卡行；大色块矩阵不再回流
    expect(source).toContain('stage-hero')
    expect(source).toContain('hero-score-bar')
    expect(source).toContain('overview-chip')
    expect(source).toContain('slot-cards')
    expect(source).toContain('block-header')
    // 三段式阅读动线：分歧才标注（当前帧 chip 仅在帧≠序列时出现），重复指标卡不回流
    expect(source).toContain("latestFrameName !== latestSlotStageName")
    expect(source).not.toContain('metrics-grid')
    // 置信度/拥挤抗风险进度条（hero 三轴：热度→风险→可信度）+ 日级窗口 ECharts 三柱
    expect(source).toContain('置信 0-100')
    expect(source).toContain('confidenceGradient')
    expect(source).toContain('拥挤抗风险 0-100')
    expect(source).toContain('jevCrowdingProbability')
    expect(source).toContain('crowdingRiskGradient')
    expect(source).toContain('dayChartRef')
    expect(source).toContain("name: '日级温度'")
    expect(source).toContain("name: '日级档置信'")
    // 回归锁：distRowOf 中 legend 必须声明于 rows 使用之前（TDZ：score 温度答案生产 100% 携带分布，
    // 顺序颠倒会在 .map() 同步读取时 ReferenceError 使整面板渲染崩溃，源码合同无法被运行时测试捕获）
    const legendAt = source.indexOf('const legend: Record<string, string> =')
    const legendUseAt = source.indexOf('name: `${legend[anchor] ?? anchor}分`')
    expect(legendAt).toBeGreaterThan(-1)
    expect(legendUseAt).toBeGreaterThan(-1)
    expect(legendAt).toBeLessThan(legendUseAt)
    expect(source).toContain("name: '日级拥挤'")
    expect(source).not.toContain('buildSlotGrid')
    expect(source).not.toContain('buildDayGrid')
    expect(source).not.toContain('gridCellStyle')
    // 环形图中心总日数（阶段分布语言）
    expect(source).toContain('EOD 总日数')
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
      'trimRangeWindow',
      'countDegradedDocs',
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

describe('涨停复盘页签（打标轨道研究↔展示同步 2026-10-03；风格对齐池换手 2026-10-04）', () => {
  test('页签与读口合同：limitup 页签 + 独立读口 + fail-visible + 哨兵/个股呈现', () => {
    const source = panelSource()
    expect(source).toContain("'limitup'")
    expect(source).toContain('涨停复盘')
    expect(source).not.toContain('涨停叙事')
    expect(source).toContain('fetchHotlistJevLimitUpLabels')
    expect(source).toContain('日级相位哨兵')
    expect(source).toContain('该日无涨停打标文档')
    const script = panelScriptSource()
    // 打标轨道读口接入不破坏既有解耦边界
    expect(script).not.toContain('fetchHotlistSentimentOverview')
    expect(script).not.toContain('fetchJiuyanAction')
    expect(script).not.toContain('hotlist_sentiment')
    expect(script).not.toContain('emotionScore')
  })

  test('池换手风格对齐合同（2026-10-04 用户裁决）：整数序号 + 相位分线列 + 过滤行 + to-table 语言', () => {
    const source = panelSource()
    // 序号=过滤后列表整数序列（1..N），热榜排名只在热榜列展示
    expect(source).toContain('{{ i + 1 }}')
    expect(source).toContain('v-for="(stock, i) in filteredLimitUpStocks"')
    // 相位分线列=日级哨兵带（市场级判定，个股行同值），缺失如实 '--'
    expect(source).toContain('<th>相位分线</th>')
    expect(source).toContain('limitUpPhaseName')
    // 池换手同款过滤行（全部+各驱动按钮+右侧统计）与明细表容器
    expect(source).toContain('limitup-filter-btn')
    expect(source).toContain('limitup-stats')
    expect(source).toContain('limitup-table-container')
    expect(source).toContain('position: sticky')
    expect(source).toContain('tr:hover')
  })

  test('打标轨道中文映射合同（驱动/深度/新鲜度/买盘/相位档）', () => {
    const source = panelSource()
    for (const name of ['JEV_DRIVER_NAMES', 'JEV_DEPTH_NAMES', 'JEV_FRESHNESS_NAMES', 'JEV_BUYSIDE_NAMES', 'JEV_PHASE_BAND_NAMES']) {
      expect(source).toContain(name)
    }
  })
})

describe('涨停生态断层标注（§十三，研究↔展示同步）', () => {
  test('温度计断层卡合同：ecosystemBreak computed + 断层卡元素 + 三特征证据', () => {
    const source = panelSource()
    expect(source).toContain('ecosystemBreak')
    expect(source).toContain('涨停生态断层日')
    expect(source).toContain('反弹在即')
    expect(source).toContain('break-card')
  })
})
