import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

// 独立热榜情绪面板源码合同（2026-09-24）：
// 口径 = docs/hotlist-emotion-panel/01-口径梳理.md 全量；风格 = 主题变量（SectorDetail 语言）。
const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotlistEmotionPanel.vue'), 'utf8')

describe('HotlistEmotionPanel 独立热榜情绪面板', () => {
  test('六个页签齐全（概览/分层/换手/阶段/历史/趋势）', () => {
    const source = panelSource()

    for (const key of ['overview', 'layers', 'turnover', 'structure', 'compare', 'track']) {
      expect(source).toContain(`'${key}'`)
    }
    for (const label of ['市场概览', '分层结构', '池换手', '阶段分布', '历史对比', '情绪趋势']) {
      expect(source).toContain(label)
    }
  })

  test('阶段分布页签：状态条改 ECharts 饼图，六态语义配色（2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain("{ key: 'structure', label: '阶段分布', icon: '🧭' }")
    expect(source).toContain("type: 'pie'")
    expect(source).toContain('stage-layout')
    expect(source).toContain('STAGE_PIE_COLORS')
    // 旧状态条语言不得回流
    expect(source).not.toContain('status-row')
    expect(source).not.toContain('状态结构')
    // 阶段迁移：中文表述 + metric-card 方框（3×2），英文键 chips 不回流
    expect(source).toContain('transition-grid')
    expect(source).toContain('STAGE_TRANSITION_ZH')
    expect(source).not.toContain("text.replace('->', '→')")
  })

  test('fail-visible：缺失显示 -- 占位，不伪造 0（趋势图表/分层/换手）', () => {
    const source = panelSource()

    expect(source).toContain('formatNullableCount')
    // 图表数值点：缺字段传 null 断线/显示 --，不伪造 0
    expect(source).toContain('counts ? counts.reversal + counts.cooling : null')
    expect(source).toContain("=== null ? '--' :")
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
    expect(source).toContain('rawStage || item.stage')
    expect(source).toContain('pendingSince')
    expect(source).not.toContain('截面置信')
    expect(source).not.toContain('当前截面证据')
  })

  test('情绪趋势页签：ECharts 承载（时间范围/阶段铺底/指标开关/统计卡），旧轨迹行列表不回流（2026-09-24）', () => {
    const source = panelSource()

    expect(source).toContain("{ key: 'track', label: '情绪趋势', icon: '📈' }")
    expect(source).toContain("import * as echarts from 'echarts'")
    // 时间范围过滤（SectorDetail time-range 语言）：1天=日内槽位，3日/1周/1月=日线
    expect(source).toContain('time-range-selector')
    expect(source).toContain('setTimeRange')
    expect(source).toContain("RANGE_DAYS: Record<TrendTimeRange, number> = { '1d': 1, '3d': 3, '1w': 5, '1m': 20 }")
    // 图表容器卡片化 + 阶段 markArea 铺底 + 指标 pill 开关 + 图下统计卡
    expect(source).toContain('trend-chart')
    expect(source).toContain('markArea')
    expect(source).toContain('trendIndicators')
    expect(source).toContain('connectNulls: false')
    expect(source).toContain('trend-stats-grid')
    // 旧轨迹行列表语言不得回流
    expect(source).not.toContain('slot-track')
    expect(source).not.toContain('track-row')
  })

  test('历史对比页签：三日卡片改 ECharts 多日趋势（时间范围/指标开关/统计卡，2026-09-24）', () => {
    const source = panelSource()

    expect(source).toContain("{ key: 'compare', label: '历史对比', icon: '🗓️' }")
    expect(source).toContain('COMPARE_INDICATORS')
    expect(source).toContain('setCompareRange')
    expect(source).toContain('renderCompareChart')
    expect(source).toContain('buildStageMarkArea')
    // 多日序列缓存与加载态两页签共享
    expect(source).toContain('ensureSeriesDays')
    expect(source).toContain('seriesDaysLoaded')
    // 旧三日卡片语言不得回流
    expect(source).not.toContain('compare-grid')
    expect(source).not.toContain('historyItems')
    expect(source).not.toContain('strongPerformanceCards')
  })

  test('分层结构页签：当日表格改多日分层对比 ECharts（分层选择/指标开关，2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain('LAYER_INDICATORS')
    expect(source).toContain('setLayersRange')
    expect(source).toContain('setLayersLayer')
    expect(source).toContain('renderLayersChart')
    // 1天=最新交易日盘中槽位（非交易日回落上一交易日），3日/1周/1月=日线
    expect(source).toContain('LAYER_RANGES')
    expect(source).toContain("layersRange = ref<LayerTimeRange>('1d')")
    // 超大单净额全 0：分层视图不再展示该字段
    expect(source).not.toContain('superNetAmount')
    // 旧当日分层表格语言不得回流
    expect(source).not.toContain('layers-table')
    expect(source).not.toContain('layerRows')
    expect(source).not.toContain('data-table')
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

  test('市场概览合并涨停证据：三容器全宽堆叠（标题行+计数徽章），涨停证据页签移除（2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain("{ key: 'overview', label: '市场概览', icon: '📊' }")
    expect(source).not.toContain("{ key: 'limit', label: '涨停证据', icon: '🔥' }")
    expect(source).toContain('热榜池涨停交集')
    expect(source).toContain('全市场背景（非热榜池口径）')
    expect(source).toContain('昨日热榜涨停表现')
    expect(source).toContain('block-header')
    expect(source).toContain('section-count')
    // 网格：主指标 4 列 / 交集 4 列 / 全市场背景与昨日表现 6 列
    expect(source).toContain('.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }')
    expect(source).toContain('grid-4')
    expect(source).toContain('grid-6')
  })

  test('证据与风险并入市场概览末尾（强证据/风险提示双栏 + 数据诊断），独立页签移除（2026-09-25）', () => {
    const source = panelSource()

    expect(source).not.toContain("{ key: 'evidence', label: '证据与风险', icon: '⚖️' }")
    expect(source).not.toContain(`'evidence'`)
    expect(source).toContain('✅ 强证据')
    expect(source).toContain('⚠️ 风险提示')
    expect(source).toContain('数据诊断')
    expect(source).toContain('evidence-columns two')
    expect(source).toContain('diag-block')
  })

  test('市场概览三容器点击打开涨停池明细面板（SectorPanel→SectorDetail 交互语言，2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain('HotlistLimitStocksPanel')
    expect(source).toContain('sub-block clickable')
    expect(source).toContain("openLimitStocks('pool', $event)")
    expect(source).toContain("openLimitStocks('market', $event)")
    expect(source).toContain("openLimitStocks('yesterday', $event)")
    // 聚合 summary 与容器同源：最新日文档 limitEvidence 直传
    expect(source).toContain('doc?.metrics?.limitEvidence ?? null')
  })

  test('市场概览涨停证据显式区分口径：全市场背景标注非热榜池', () => {
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
