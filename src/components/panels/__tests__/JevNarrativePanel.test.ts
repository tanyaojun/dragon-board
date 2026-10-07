// JEV 叙事面板源码合同（独立面板 v1.0，2026-10-08）：
// 独立轨道 = 只消费 /api/hotlist-jev/series|range；解耦硬边界 = 不触碰规则 EOD 与复核/概览混装读口。
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

import { sortLimitUpStocks } from '@/services/hotlist/jevNarrativeProjection'
import type { HotlistJevLimitUpStock } from '@/types/hotlistJev'

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

  test('三大焦点可视化合同：温度计 SVG+锚分位 / 拥挤柱图+waffle+层迁移 / 置信柱图+历史维度切换+分布明细', () => {
    const source = panelSource()
    // 温度计：SVG 几何 + 近20日参照分位卡 + REVERSE 注记
    expect(source).toContain('thermo-svg')
    expect(source).toContain('anchorMetrics')
    expect(source).toContain('REVERSE')
    expect(source).toContain('近20日参照')
    // 拥挤度：ECharts 柱状图（2026-10-07 用户令，置信度页签同语言：窗口自适应历史维度+指标开关）——
    // 柱=所选层概率（柱色=归层色）+拥挤抗风险线（三层概率合计，hero 同口径）；waffle+层迁移+窗口层统计保留；
    // 当日层带色块行与多日饼图退役（时序由柱状图承接、占比由统计卡层计数承接，语义不丢）
    expect(source).toContain('crowdingBarPoints')
    expect(source).toContain('CROWDING_BARS_INDICATORS')
    expect(source).toContain('indicator-btn')
    expect(source).toContain('crowding-strip-block')
    expect(source).toContain('waffleSquares')
    expect(source).toContain('crowdingTransitions')
    expect(source).toContain('escapeRate')
    expect(source).toContain('毒层')
    expect(source).not.toContain("type: 'pie'")
    expect(source).not.toContain('crowdingChartRef')
    // 置信度：ECharts 柱状图（2026-10-07 用户令，热榜情绪·历史对比页签同语言：指标开关+柱=P+线=温度C）
    //   历史维度随顶部窗口自动切换（1天=槽位级四题 / 3日·1周·10日·30日=EOD 日级三题）+ margin/熵派生指标 + 答案分布明细
    expect(source).toContain('confidenceBarsPoints')
    expect(source).toContain('CONF_BARS_INDICATORS')
    expect(source).toContain('CONF_BARS_DAILY_INDICATORS')
    expect(source).toContain('indicator-btn')
    // 历史维度五档（2026-10-07 用户令）：1天/3日/1周/10日/30日——30日为新增档（后端 range days 上限 30 对齐）
    expect(source).toContain("key: '30d'")
    expect(source).toContain('30日')
    // 窗口切换指标选择守卫：题目集合换代（1天↔多日）才重置全选，同模式档位间保留用户开关状态
    expect(source).toContain('activeKeys.includes(key)')
    // 缺失日披露在数据分支之外：整窗全缺走空态时也必须可见（fail-visible）
    expect(source).toContain('缺失日披露放在数据分支之外')
    expect(source).toContain('connectNulls: false')
    expect(source).toContain('犹豫阈值')
    expect(source).toContain('margin')
    expect(source).toContain('熵')
    expect(source).toContain('distRows')
    expect(source).toContain('score 锚点')
    // score 型（温度）纠错（2026-10-02）：实测携带锚点分布+置信，不再误标「无分布」——
    // 温度线 C%=模型置信（不套 P 阈值色），明细卡渲染锚点分布条+锚期望，仅确缺失才标无分布
    expect(source).toContain("metrics.kind === 'score'")
    expect(source).toContain('锚期望')
    expect(source).toContain('anchorTone')
    expect(source).toContain('scoreNoDist')
    expect(source).toContain('score 型分布=10 档锚点概率')
    // ECharts 四图容器（温度/拥挤柱图/置信柱图/日级窗口；拥挤旧饼图与置信底部趋势图均已退役）
    expect(source).toContain('thermoChartRef')
    expect(source).toContain('crowdingBarChartRef')
    expect(source).toContain('confidenceBarsChartRef')
    expect(source).not.toContain('confidenceChartRef')
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
    // 环形图中心总日数（阶段分布语言）——2026-10-07 拥挤页签改柱状图后饼图退役，中心文案随删，层计数由统计卡承接
    expect(source).not.toContain('EOD 总日数')
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

  test('sortLimitUpStocks 排序方向（回归：置信比较器内建降序曾被方向系数二次取反）', () => {
    const stocks = [
      { code: 'A', stockPhasePosition: 'start', stockPhaseProbabilities: { start: 0.6 }, rank: 3, label: 'x', labelProbabilities: { x: 0.5 } },
      { code: 'B', stockPhasePosition: 'climax', stockPhaseProbabilities: { climax: 0.9 }, rank: 1, label: 'y', labelProbabilities: { y: 0.8 } },
      { code: 'C', stockPhasePosition: 'ferment', stockPhaseProbabilities: { ferment: 0.75 }, rank: 2, label: 'z', labelProbabilities: { z: 0.65 } },
    ] as unknown as HotlistJevLimitUpStock[]
    // 相位置信：降序 B(0.9)→C(0.75)→A(0.6)，升序反之
    expect(sortLimitUpStocks(stocks, 'phaseConf', true).map((s) => s.code)).toEqual(['B', 'C', 'A'])
    expect(sortLimitUpStocks(stocks, 'phaseConf', false).map((s) => s.code)).toEqual(['A', 'C', 'B'])
    // 驱动置信同方向规则
    expect(sortLimitUpStocks(stocks, 'labelConf', true).map((s) => s.code)).toEqual(['B', 'C', 'A'])
    // 相位档生命周期升序：start→ferment→climax；降序反转
    expect(sortLimitUpStocks(stocks, 'phase', false).map((s) => s.code)).toEqual(['A', 'C', 'B'])
    expect(sortLimitUpStocks(stocks, 'phase', true).map((s) => s.code)).toEqual(['B', 'C', 'A'])
    // 热榜排名升序：1→2→3
    expect(sortLimitUpStocks(stocks, 'rank', false).map((s) => s.code)).toEqual(['B', 'C', 'A'])
    // 不突变入参数组
    expect(stocks.map((s) => s.code)).toEqual(['A', 'B', 'C'])
  })

  test('sortLimitUpStocks 分类列档位序与文本列（表头点击排序 2026-10-04）', () => {
    const stocks = [
      { code: 'A', name: '中兵', catalystDepth: 'concept_assembly', freshness: 'continuing', buySideLogic: 'sector_follow', board: '电池产业链' },
      { code: 'B', name: '新华', catalystDepth: 'core_main_business', freshness: 'fresh_catalyst', buySideLogic: 'independent_catalyst', board: '公告' },
      { code: 'C', name: '长春', catalystDepth: 'insufficient_evidence', freshness: 'unclear', buySideLogic: 'pure_sentiment', board: '医药' },
    ] as unknown as HotlistJevLimitUpStock[]
    // 深度档位序（核心主业→…→概念组装→信息不足）：B→A→C
    expect(sortLimitUpStocks(stocks, 'depth', false).map((s) => s.code)).toEqual(['B', 'A', 'C'])
    // 新鲜度档位序（今日新催化→老催化→无催化→信息不足）：B→A→C
    expect(sortLimitUpStocks(stocks, 'freshness', false).map((s) => s.code)).toEqual(['B', 'A', 'C'])
    // 买盘档位序（独立催化→板块跟随→高位卡位→纯情绪）：B→A→C
    expect(sortLimitUpStocks(stocks, 'buySide', false).map((s) => s.code)).toEqual(['B', 'A', 'C'])
    // 名称/板块中文排序：环境 ICU 相关，断言方向一致性（升序=降序严格反转）而非具体拼序
    const nameAsc = sortLimitUpStocks(stocks, 'name', false).map((s) => s.code)
    const nameDesc = sortLimitUpStocks(stocks, 'name', true).map((s) => s.code)
    expect([...nameAsc].reverse()).toEqual(nameDesc)
    const boardAsc = sortLimitUpStocks(stocks, 'board', false).map((s) => s.code)
    const boardDesc = sortLimitUpStocks(stocks, 'board', true).map((s) => s.code)
    expect([...boardAsc].reverse()).toEqual(boardDesc)
    // 代码序
    expect(sortLimitUpStocks(stocks, 'code', false).map((s) => s.code)).toEqual(['A', 'B', 'C'])
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
    expect(source).toContain('相位分线{{ limitUpSortMark(\'phase\') }}</th>')
    expect(source).toContain('limitUpPhaseName')
    // 池换手同款过滤行（全部+各驱动按钮+右侧统计）与明细表容器
    expect(source).toContain('limitup-filter-btn')
    expect(source).toContain('limitup-stats')
    expect(source).toContain('limitup-table-container')
    expect(source).toContain('position: sticky')
    expect(source).toContain('tr:hover')
    // 搜索+排序（SectorDetail 成分股表同款控件，2026-10-04 用户令；排序逻辑委托投影模块纯函数）
    expect(source).toContain('limitUpSearch')
    expect(source).toContain('placeholder="搜索股票代码或名称..."')
    expect(source).toContain('limitUpSortKey')
    expect(source).toContain('limitUpSortDesc')
    expect(source).toContain('sortLimitUpStocks(stocks, limitUpSortKey.value, limitUpSortDesc.value)')
    expect(projectionSource()).toContain('LIMITUP_PHASE_ORDER')
    expect(source).toContain('<option value="phase">相位档</option>')
    expect(source).toContain('↓ 降序')
    // 表头点击排序：可排序 th+同列反转/换列默认方向
    expect(source).toContain('setLimitUpSort')
    expect(source).toContain('th.sortable')
    expect(projectionSource()).toContain('LIMITUP_SORT_DEFAULT_DESC')
    expect(projectionSource()).toContain('LIMITUP_DEPTH_ORDER')
    expect(projectionSource()).toContain('LIMITUP_FRESHNESS_ORDER')
    expect(projectionSource()).toContain('LIMITUP_BUYSIDE_ORDER')
  })

  test('打标轨道中文映射合同（驱动/深度/新鲜度/买盘/相位档/个股相位分线）', () => {
    const source = panelSource()
    for (const name of ['JEV_DRIVER_NAMES', 'JEV_DEPTH_NAMES', 'JEV_FRESHNESS_NAMES', 'JEV_BUYSIDE_NAMES', 'JEV_PHASE_BAND_NAMES', 'JEV_STOCK_PHASE_NAMES']) {
      expect(source).toContain(name)
    }
  })

  test('个股相位分线列合同（2026-10-04 试点接线）：个股位+降级未判+未跑日 fallback 双文案', () => {
    const source = panelSource()
    expect(source).toContain('stockPhaseCell')
    expect(source).toContain('limitUpHasStockPhase')
    expect(source).toContain('个股自身相位位')
    // fail-visible：试点日降级如实「未判」（不混日级带），未跑日整列回落哨兵带且口径注记随动
    expect(source).toContain("'未判'")
    expect(source).toContain('当日未跑个股相位')
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
