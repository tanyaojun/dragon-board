import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

// 独立热榜情绪面板源码合同（2026-09-24）：
// 口径 = docs/hotlist-emotion-panel/01-口径梳理.md 全量；风格 = 主题变量（SectorDetail 语言）。
const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotlistEmotionPanel.vue'), 'utf8')

describe('HotlistEmotionPanel 独立热榜情绪面板', () => {
  test('七个页签齐全（概览/分层/换手/阶段/历史/趋势/jev）', () => {
    const source = panelSource()

    for (const key of ['overview', 'layers', 'turnover', 'structure', 'compare', 'track', 'jev']) {
      expect(source).toContain(`'${key}'`)
    }
    for (const label of ['热榜概览', '分层结构', '池换手', '阶段分布', '历史对比', '情绪趋势']) {
      expect(source).toContain(label)
    }
  })

  test('路线 B 连续情绪分：hero 分数条 + 可分解 tooltip + 评分不可用态（2026-09-30）', () => {
    const source = panelSource()

    // 展示：hero 区情绪分条（数值 + 0-100 进度条 + hint），tooltip 携带 dims 明细
    expect(source).toContain('hero-score-bar')
    expect(source).toContain('emotionScoreValue')
    expect(source).toContain('情绪分构成（可分解审计）')
    expect(source).toContain('连续情绪分 0-100')
    // fail-visible：score=null 时显示不可用态（不伪造 0），旧文档无字段不渲染
    expect(source).toContain('hero-score-missing')
    expect(source).toContain('情绪分不可用')
    expect(source).toContain("typeof score === 'number' && Number.isFinite(score)")
    // stage 展示逻辑零改动：评分只增展示，不改档位消费
    expect(source).toContain('const confirmedStageName = computed(() => doc.value?.stage ?? \'--\')')
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
    // 超大单净额全 0：分层图表指标不含该字段（完整文档明细表中的 superNetAmount 列不受限）
    expect(source).not.toContain("{ key: 'superNet'")
    // 旧当日分层表格语言不得回流
    expect(source).not.toContain('layers-table')
    expect(source).not.toContain('layerRows')
    expect(source).not.toContain('data-table')
  })

  test('分层结构默认视图：全池 + 涨/跌占比·平均涨幅·TRIN 四维，三指标柱图化（2026-09-28 用户裁决）', () => {
    const source = panelSource()

    // 默认分层=全池；默认指标=涨占比/跌占比/平均涨幅/TRIN
    expect(source).toContain("layersLayer = ref<LayerKey>('all')")
    expect(source).toContain(
      "layersIndicators = ref<LayerIndicatorKey[]>(['upRatio', 'downRatio', 'avgChange', 'trin'])",
    )
    // 三指标改柱图：涨占比红 / 跌占比绿 / 平均涨幅蓝，仍走 % 轴
    expect(source).toContain("name: '涨占比', type: 'bar'")
    expect(source).toContain("name: '跌占比', type: 'bar'")
    expect(source).toContain("name: '平均涨幅', type: 'bar'")
    expect(source).toContain("itemStyle: { color: '#ff4757' }, yAxisIndex: 0")
    expect(source).toContain("itemStyle: { color: '#2ed573' }, yAxisIndex: 0")
    expect(source).toContain("itemStyle: { color: '#1e90ff' }, yAxisIndex: 0")
    // 旧折线语言不得回流
    expect(source).not.toContain("name: '涨占比', type: 'line'")
    expect(source).not.toContain("name: '跌占比', type: 'line'")
    expect(source).not.toContain("name: '平均涨幅', type: 'line'")
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
    // 汇总卡改阶段迁移 metric-card 风格（2026-09-25 用户裁决），chips 语言不回流
    expect(source).toContain('turnover-grid')
    expect(source).toContain('turnoverSummaryCards')
    expect(source).not.toContain('turnover-chips')
    // 列宽固定值方案（不铺满自适应拉伸；具体像素值允许视觉调参，不锁死）
    expect(source).toContain('.to-table th:nth-child(2) { width:')
    expect(source).not.toContain('min-width: 100%')
  })

  test('热榜概览合并涨停证据：三容器全宽堆叠（标题行+计数徽章），涨停证据页签移除（2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain("{ key: 'overview', label: '热榜概览', icon: '📊' }")
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

  test('证据与风险并入热榜概览末尾（强证据/风险提示双栏 + 数据诊断），独立页签移除（2026-09-25）', () => {
    const source = panelSource()

    expect(source).not.toContain("{ key: 'evidence', label: '证据与风险', icon: '⚖️' }")
    expect(source).not.toContain(`'evidence'`)
    expect(source).toContain('✅ 强证据')
    expect(source).toContain('⚠️ 风险提示')
    expect(source).toContain('数据诊断')
    expect(source).toContain('evidence-columns two')
    expect(source).toContain('diag-block')
  })

  test('热榜概览三容器点击打开涨停池明细面板（SectorPanel→SectorDetail 交互语言，2026-09-25）', () => {
    const source = panelSource()

    expect(source).toContain('HotlistLimitStocksPanel')
    expect(source).toContain('sub-block clickable')
    expect(source).toContain("openLimitStocks('pool', $event)")
    expect(source).toContain("openLimitStocks('market', $event)")
    expect(source).toContain("openLimitStocks('yesterday', $event)")
    // 聚合 summary 与容器同源：最新日文档 limitEvidence 直传
    expect(source).toContain('doc?.metrics?.limitEvidence ?? null')
  })

  test('热榜概览涨停证据显式区分口径：全市场背景标注非热榜池', () => {
    const source = panelSource()

    expect(source).toContain('非热榜池口径')
    expect(source).toContain('board4Plus')
    expect(source).toContain('yesterdayHotLimit')
  })

  test('EOD 文档明细：全字段分组展示 + 截面表 + 未归类兜底（2026-09-25）', () => {
    const source = panelSource()

    // 区块与标题
    expect(source).toContain('doc-full-block')
    expect(source).toContain('EOD 文档明细')
    // 分组：元信息/阶段确认/核心指标/三日对比/昨强表现/池换手
    expect(source).toContain("title: '文档元信息'")
    expect(source).toContain("title: '阶段多帧确认'")
    expect(source).toContain("title: '核心指标（metrics 顶层）'")
    expect(source).toContain("title: '三日对比'")
    expect(source).toContain("title: '昨日强票表现'")
    expect(source).toContain("title: '池换手概况（明细见池换手页签）'")
    // 两张截面表（三日/分层）与共用列集
    expect(source).toContain('docDayColumns')
    expect(source).toContain("title: '三日截面指标'")
    expect(source).toContain('分层指标（top20 / top50 / top100 / 全池）')
    expect(source).toContain('doc-table-scroll')
    // fail-visible：未归类字段兜底（后端新增字段自动透出），缺失值 -- 不伪造
    expect(source).toContain('walkUncoveredDoc')
    expect(source).toContain('未归类字段')
    expect(source).toContain("fmtDocValue(confirmState?.pending, 'bool')")
    // 兜底完整性（review 2026-09-25）：子树必须逐字段 mark，整树 mark 会吞掉未来新增字段
    expect(source).not.toContain("mark('stageConfirmState')")
    expect(source).not.toContain("mark('turnover')")
    expect(source).not.toContain("mark('metrics.comparison.yesterdayStrongPerformance')")
    expect(source).toContain("'stageConfirmState.pending'")
    expect(source).toContain("'turnover.newEntryDetails'")
    expect(source).toContain("'metrics.comparison.yesterdayStrongPerformance.matchedCount'")
    // 折叠交互（2026-09-25 用户裁决）：标题即折叠按钮，默认已折叠，🗒️ 图标不回流
    expect(source).toContain('docFullCollapsed = ref(true)')
    expect(source).toContain('doc-collapse-btn')
    expect(source).toContain('v-show="!docFullCollapsed"')
    expect(source).not.toContain('🗒️')
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

  // ── jev 观察轨道（2026-10-08）：独立 AI 评判对照，缺失/降级如实展示 ──

  test('jev 观察轨道：读口接入 + 顶部并列 chip + 日级总固定', () => {
    const source = panelSource()

    expect(source).toContain('fetchHotlistJevSeries')
    expect(source).toContain("jevChoiceName(jevLatest.value, 'sequence_stage')")
    expect(source).toContain("jevChoiceName(jevLatest.value, 'frame_stage')")
    expect(source).toContain('jev-chip')
    expect(source).toContain('jev 日内序列')
    expect(source).toContain('jev 观察轨道')
    // 缺失/未开启如实展示，不伪造数据
    expect(source).toContain('暂无 jev 评判数据')
  })

  test('jev 观察轨道图表化：独立页签 + ECharts 承载（时间范围/指标开关/阶段铺底/统计卡），概览子区块不回流（2026-09-30）', () => {
    const source = panelSource()

    // 独立页签（与情绪趋势并列）：TABS 注册 + tab-pane 承载；概览内子区块不回流
    expect(source).toContain("{ key: 'jev', label: 'jev 观察轨道', icon: '🤖' }")
    expect(source).toContain(`v-show="view === 'jev'"`)
    expect(source).not.toContain('sub-block jev-block')
    // 多日读口接入 + 1天=逐槽 / 多日=EOD 日级
    expect(source).toContain('fetchHotlistJevRange')
    expect(source).toContain('ensureJevDays')
    expect(source).toContain("jevScore(slot, 'temperature')")
    expect(source).toContain("jevScore(eod, 'day_temperature')")
    // 时间范围与指标开关（情绪趋势同语言）
    expect(source).toContain('setJevTimeRange')
    expect(source).toContain('toggleJevIndicator')
    expect(source).toContain('JEV_INDICATORS')
    expect(source).toContain('jevTimeRange')
    // 图表：阶段铺底复用 + 缺失断线 + 统计卡 + 注记行
    expect(source).toContain('renderJevChart')
    expect(source).toContain('jevPoints')
    expect(source).toContain('buildStageMarkArea(points)')
    expect(source).toContain('connectNulls: false')
    expect(source).toContain('trend-stats-grid')
    // 三维度语言（2026-10-02 用户裁决）：温度紫柱 / 拥挤度黄柱 / 置信蓝线，旧折线不回流
    expect(source).toContain("name: '温度', type: 'bar'")
    expect(source).toContain("name: '拥挤度', type: 'bar'")
    expect(source).toContain("name: '置信', type: 'line'")
    expect(source).toContain("itemStyle: { color: '#9b59b6' }")
    expect(source).toContain("itemStyle: { color: '#f1c40f' }")
    expect(source).toContain("lineStyle: { color: '#4a90e2', width: 2 }")
    expect(source).not.toContain("name: '温度', type: 'line'")
    expect(source).not.toContain("name: '拥挤', type: 'line'")
    // 拥挤度数值口径（深化文档 G2 修复）：v2 离散归层无连续分，柱高=拥挤三层概率合计（jevCrowdingProbability），
    // 归层判定与三层分解进 tooltip 防与柱高混读；置信=序列档/日级档模型 confidence
    expect(source).toContain('jevCrowdingProbability')
    expect(source).toContain('jevChoiceConfidence')
    expect(source).toContain('jevCrowdingPointInfo')
    expect(source).toContain('crowdingBreakdown')
    expect(source).toContain('归层：')
    expect(source).toContain('档位 P ')
    // 置信指标开关（默认三维度全开）
    expect(source).toContain("{ key: 'confidence', label: '置信', icon: '🎯' }")
    expect(source).toContain("label: '拥挤度', icon: '🧲'")
    // 统计卡跟口径升级：概率卡带 % 后缀，置信补最低值（低置信=风险信号）
    expect(source).toContain("card('平均拥挤度', (p) => p.crowding, 'avg', '%')")
    expect(source).toContain("card('最低置信', (p) => p.confidence, 'min', '%')")
    // 版本分段守卫（2026-10-02 用户裁决）：窗口混版/含未知口径文档时注记行显式标注，跨版本对比无效
    expect(source).toContain('jevVersionNote')
    expect(source).toContain('窗口跨题目判据版本')
    expect(source).toContain("doc.questionSetVersion || '未知口径'")
    // 整窗未知口径（旧代产物）单独标注；1d 档 EOD 日级总体与槽位一并纳入版本检查
    expect(source).toContain("versions.has('未知口径')")
    expect(source).toContain('窗口文档缺题目版本号')
    expect(source).toContain('[...jevSlots.value, ...(jevEod.value ? [jevEod.value] : [])]')
    // 日级总体（盘后固定）行保留（1天档）
    expect(source).toContain('日级总体（盘后固定）')
    // fail-visible：降级/无数据状态结构化进 tooltip 与注记，不伪造分数
    expect(source).toContain('statusText')
    expect(source).toContain('窗口缺失')
    // 旧卡片网格语言不得回流
    expect(source).not.toContain('jev-grid')
    expect(source).not.toContain('jev-row')
    expect(source).not.toContain("row.sequenceName || '缺失'")
  })

  test('jev 叙事与详情卡：点选联动 + 常驻详情（概率条/置信/元信息）+ 概览 chip 展开叙事（2026-09-30 用户裁决）', () => {
    const source = panelSource()

    // 概览 chip（红框位置）：叙事全文展开入口，默认收起
    expect(source).toContain('jevHeroNarrativeOpen')
    expect(source).toContain('toggleJevHeroNarrative')
    expect(source).toContain('jev-hero-narrative')
    expect(source).toContain('narrativeRaw')
    // 详情卡：常驻图表下方 + 图表点选联动（off 先行防重复 handler，默认最新帧）
    expect(source).toContain('selectedJevKey')
    expect(source).toContain("jevChart.off('click')")
    expect(source).toContain("jevChart.on('click'")
    expect(source).toContain('jev-detail-grid')
    // 概率条两档都展示：五档（阶段语义色）+ 七类路径，confidence 透出
    expect(source).toContain('jev-prob-row')
    expect(source).toContain("buildJevChoiceDetail('frame_stage'")
    expect(source).toContain("buildJevChoiceDetail('day_pattern'")
    expect(source).toContain('JEV_STAGE_ORDER')
    expect(source).toContain('confidence')
    // fail-visible：质量注记与文档缺失透出，缺失概率显示 -- 不伪造
    expect(source).toContain('qualityNotes')
    expect(source).toContain("row.pct === null ? '--'")
    // 分数通栏紧凑条：两列布局防与概率条格同行拉伸留白（2026-09-30 修复）
    expect(source).toContain('jev-detail-scores')
    expect(source).toContain('.jev-detail-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }')
    // 旧 tooltip-only 叙事方案与抽屉语言不回流
    expect(source).not.toContain('HotlistLimitStocksPanel v-if="jevDetail"')
  })

  test('jev 轨道零规则输出：不读规则情绪文档字段作 jev 展示源', () => {
    const source = panelSource()

    // jev 展示只来自 hotlistJevApi（独立轨道），不把规则 doc 的 stage 当 jev 结论
    expect(source).toContain("from '@/services/hotlist/hotlistJevApi'")
    expect(source).toContain("from '@/types/hotlistJev'")
  })

  test('面板重开补渲染：v-if 销毁图表容器而 view/数据缓存不变，重开按当前页签重渲染（2026-10-01 BUG 修复）', () => {
    const source = panelSource()

    // 面板组件常驻 + 根节点 v-if：关闭销毁全部图表容器 DOM，重开时页签与缓存数据不变，
    // view/数据 watcher 均不触发 → 必须有 visible→true 的补渲染入口，按当前页签派发
    expect(source).toContain('面板重开补渲染')
    expect(source).toContain('watch(() => props.visible, (visible) => {')
    expect(source).toContain("if (view.value === 'track' && trendPoints.value.length) renderTrendChart()")
    expect(source).toContain("if (view.value === 'compare' && comparePoints.value.length) renderCompareChart()")
    expect(source).toContain("if (view.value === 'layers' && layerPoints.value.length) renderLayersChart()")
    expect(source).toContain("if (view.value === 'structure' && stagePieData.value.length) renderStageChart()")
    expect(source).toContain("if (view.value === 'phase') void ensurePhaseData().then(() => nextTick(() => renderPhaseChart()))")
    expect(source).toContain("if (view.value === 'jev' && jevPoints.value.length) renderJevChart()")
    // 相位渲染器补齐其余五个渲染器同款守卫：旧实例绑定 DOM 已分离必须 dispose 重建，
    // 否则重开 phase 页签时 setOption 打在分离实例上仍然空白
    const phaseRender = source.slice(source.indexOf('function renderPhaseChart'))
    expect(phaseRender).toContain('phaseChartInstance.getDom() !== phaseChartEl.value')
    expect(phaseRender).toContain('phaseChartInstance.dispose()')
    expect(phaseRender).toContain('phaseChartInstance = null')
    // 重试成功路径：loadPhaseData 只更新 phaseHistoryDays，需数据 watcher 触发渲染
    expect(source).toContain('watch(phaseHistoryDays, () => {')
    // 关闭/卸载统一释放六图实例：分离实例只余 resize 告警；onUnmounted 原漏 phase 实例，一并兜底
    expect(source).toContain('function disposeAllCharts(): void {')
    const disposeBody = source.slice(source.indexOf('function disposeAllCharts'))
    for (const inst of ['trendChart', 'compareChart', 'layersChart', 'stageChart', 'jevChart', 'phaseChartInstance']) {
      expect(disposeBody).toContain(`${inst}?.dispose()`)
      expect(disposeBody).toContain(`${inst} = null`)
    }
    const unmountBody = source.slice(source.indexOf('onUnmounted('), source.indexOf('onUnmounted(') + 200)
    expect(unmountBody).toContain('disposeAllCharts()')
    const visibleWatchBody = source.slice(source.indexOf('watch(() => props.visible'), source.indexOf('watch(() => props.visible') + 600)
    expect(visibleWatchBody).toContain('if (!visible) {')
    expect(visibleWatchBody).toContain('disposeAllCharts()')
  })

  test('融合总纲面板：三轴决策栈/深谷账本/哨兵分歧/晋升进度（2026-10-04 总纲 §5 同步）', () => {
    const source = panelSource()

    // 四块卡片齐全，口径注记随卡片走（研究-展示同步：ranktrend-phase-fusion-master-plan.md）
    expect(source).toContain('三轴决策栈（水平 × 动量 × 事件）')
    expect(source).toContain('深谷节点账本（C9 事件轴 · 盘后链每日自动积累）')
    expect(source).toContain('哨兵分歧（jev 日级哨兵 × 规则分 · 只告警不改判）')
    expect(source).toContain('候选晋升进度（样本外证据积累 · 纪律=章程 §5）')
    // 数据链：board 新字段装载（degraded 分支也要清空，不残留上一轮读数）
    expect(source).toContain('phaseC9Docs.value = board.c9 ?? []')
    expect(source).toContain('sentinelDivergence.value = board.sentinelDivergence ?? null')
    expect(source).toContain('phaseC9Docs.value = []')
    expect(source).toContain('sentinelDivergence.value = null')
    // 三轴 computed 与确认节点观察口径标注（M4 提案只展示不决策）
    expect(source).toContain('const axisLevel = computed(')
    expect(source).toContain('const axisMomentum = computed(')
    expect(source).toContain('const axisEvent = computed(')
    expect(source).toContain('观察口径）')
    // C9 账本聚合与晋升门进度（代理口径注记防混读）
    expect(source).toContain('const c9Ledger = computed(')
    expect(source).toContain('晋升门进度（代理口径）')
    expect(source).toContain('晋升判定以交易账本为准')
    // 哨兵分歧只列不一致日 + C6 晋升门常数
    expect(source).toContain('const sentinelDivergentDays = computed(')
    expect(source).toContain('const C6_GATE_MIN_TRADES = 30')
  })

  test('融合总纲落地件：时间线深谷图钉 + 哨兵档位差（2026-10-04 §7-9 与实测修正）', () => {
    const source = panelSource()

    // 深谷 ⚡ 标记：滚动 10 日最低且 <40 的散点系列 + 图例提示 + tooltip 附注
    expect(source).toContain('const valleyMarks: Array<[string, number | null]> = []')
    expect(source).toContain('滚动 10 日最低且 <40')
    expect(source).toContain("name: '深谷',")
    expect(source).toContain('chart-hint')
    expect(source).toContain('⚡ 深谷状态日（滚动10日最低且<40）')
    // 哨兵分歧按档位差表述（可差两档），不写死「一档」
    expect(source).toContain('d.notches < 0')
    expect(source).not.toContain("relation === 'lower' ? '判低一档'")
  })

  test('review 修复合同：门控不吞数据/带刻度后端携带/动量首根语义（2026-10-04 四路 review）', () => {
    const source = panelSource()

    // P1-A：bands 缺失只挡分档条，对照/试验/累积数据存在即展示（fail-visible）
    expect(source).toContain('本月缺少分环境数据（旧版格式，重新生成后补全）')
    const pulseCard = source.slice(source.indexOf('情绪环境与出手战绩'), source.indexOf('三轴决策栈'))
    expect(pulseCard).toContain('v-if="phasePulseAbLine"')
    expect(pulseCard).toContain('v-if="phasePulseChallengerRows.length"')
    expect(pulseCard).toContain('v-if="phasePulseAccRows.length"')
    // P1-B：axisLevel 档名来自 board bandScale（后端携带），前端不手抄阈值
    expect(source).toContain('bandScale.value = board.bandScale ?? []')
    expect(source).toContain('hit?.label ?? \'未知档（刻度缺失）\'')
    expect(source).not.toContain("score < 40 ? '低温期'")
    // P1-C：冷端确认=深谷后首根 Δ>+15，确认只发生一次（对齐 M4 登记口径）
    expect(source).toContain('冷端确认节点触发（深谷')
    expect(source).toContain('冷端确认已于')
    expect(source).not.toContain('const recentDeep = days.slice(-6, -1)')
    // P2：挑战者 stats 缺失不渲染假 0；晋升行披露胜率分母
    expect(source).toContain('v-if="c.tradeCount != null"')
    expect(source).toContain('分母=有代理收益的')
  })

  test('C10 高峰兑现账本卡（2026-10-04 立项，方案 ranktrend-c10-peak-exit-plan.md）', () => {
    const source = panelSource()

    // 装载（degraded 分支清空）+ 聚合（缺口三分组口径）+ 卡片
    expect(source).toContain('phaseC10Docs.value = board.c10 ?? []')
    expect(source).toContain('phaseC10Docs.value = []')
    expect(source).toContain('const c10Ledger = computed(')
    expect(source).toContain('const flat = (key:')
    expect(source).toContain('edgeGe3VsBaseline')
    expect(source).toContain('高峰兑现账本（C10 逃顶侧 · EOD≥75 · 盘后链每日自动积累）')
    // 观察态注记（不构成操作指令）
    expect(source).toContain('观察态不构成操作指令')
  })
})
