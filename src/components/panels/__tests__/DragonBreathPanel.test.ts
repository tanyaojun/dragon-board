import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'DragonBreathPanel.vue'), 'utf8')

describe('DragonBreathPanel 状态来源透出（spec §4）', () => {
  test('全池状态结构底部透出 golden / fallback 两通道（阶段缺失已并入「无阶段」格）', () => {
    const source = panelSource()

    expect(source).toContain('hotListStatusSourceNote')
    expect(source).toContain('`golden 判定 ${counts.displayStatus}`')
    expect(source).toContain('`fallback 接管 ${counts.fallback}`')
    // 2026-09-10：stageMissing 随分类层删除，不得复活
    expect(source).not.toContain('stageMissing')
    expect(source).toContain('class="status-source-note"')
  })

  test('缺 statusSourceCounts（旧 EOD 文档）时不硬门禁：回退池差异注，无差异才隐藏', () => {
    const source = panelSource()

    // 锚点收敛（code review F6）：不用跨行正则，避免注释/换行调整后误报
    expect(source).toContain('const hotListStatusSourceNote = computed(() => {')
    // 2026-09-19：counts 缺失不再直接返回空串——池口径差异（快照池 vs 行情列表）仍要可见；
    // poolGapNote 自身为空（无差异/缺 topN）时才整段隐藏
    expect(source).toContain('if (!counts) return hotListPoolGapNote.value')
    expect(source).toContain('v-if="hotListStatusSourceNote"')
  })

  test('池对账注脚按列表池 provenance 语义透出（2026-09-21）：一致不提示，降级/启动缓存/槽位滞后如实透出', () => {
    const source = panelSource()

    // 面板全池 = 快照帧池，行情列表池以 dataLayer provenance 为准；同槽一致不产生噪音，
    // 降级（回退热榜合并池）/启动缓存/槽位滞后/同槽残余差异必须如实透出（fail-visible），
    // 不允许两处数字静默不一致，也不再用「两池时点差」旧语义解释。
    expect(source).toContain('const hotListPoolGapNote = computed(() => {')
    expect(source).toContain('marketListPoolCount')
    // provenance 读取接入（订阅 + computed 依赖），帧池切换随 merged.stocks 响应式刷新
    expect(source).toContain('dataLayer.getListPoolProvenance()')
    // 列表池规模与 provenance 均由 merged.stocks 订阅维护（响应式），挂载时初始化一次
    expect(source).toContain("dataLayer.subscribe('merged.stocks', () => {")
    expect(source).toContain('marketListPoolCount.value = (dataLayer.getStocks()')
    // 降级提示：帧池不可用回退热榜合并池必须可见
    expect(source).toContain("'hotlist-merged'")
    expect(source).toContain('回退热榜合并池')
    // 启动缓存快路径提示
    expect(source).toContain("'startup-bundle'")
    // 槽位滞后提示：列表帧槽 ≠ 情绪区块最新槽
    expect(source).toContain('槽位暂不同步')
    // 同槽残余差异仍保留最小对账口径说明
    expect(source).toContain('snapshotPool !== listPool')
    // 一致时不产生两池差异文案（旧「两池时点差」关键词必须消失，注释一并扫）
    expect(source).not.toContain('两池进出榜时点不同')
  })

  test('全池状态结构为 6 格且不含 8 类修正栏', () => {
    const source = panelSource()

    expect(source).toContain('hotListStageOrder')
    expect(source).toContain('HOT_LIST_STAGE_LABELS')
    expect(source).toContain("key: 'unknown'")
    // 8 类 label 不得回潮
    for (const legacy of ['主升确认', '点火观察', '强资确认', '新入观察', '高位拥挤', '资金背离', '转弱预警', '样本不足']) {
      expect(source).not.toContain(`'${legacy}'`)
    }
  })

  test('三日对比历史行展示「冷却」桶（不得把 cooling 计数标成「强资」）', () => {
    const source = panelSource()

    // code review Medium 3：cooling 桶 ≠ 强资（强资只是 cooling 的强资金子集）。
    // 键名与模板文案必须同为 cooling/冷却，防止把 cooling 全桶计数伪装成强资确认数。
    expect(source).toContain('冷却 {{ item.cooling }}')
    expect(source).not.toContain('item.strongMoney')
    expect(source).not.toContain('强资 {{ item.')
  })

  test('面板顶部文案与个股生命周期区分（市场情绪阶段）', () => {
    const source = panelSource()

    expect(source).toContain('<span class="sentiment-label">市场情绪阶段</span>')
    expect(source).not.toContain('<span class="sentiment-label">当前周期</span>')
  })

  test('分层结构对旧结构 EOD 文档（无 stageCounts/stageShares）fail-visible，不抛渲染错误', () => {
    const source = panelSource()

    // 2026-09-12 修复：hotListLayerItems 不得对 stageCounts/stageShares 做裸属性访问——
    // 8 类旧结构文档（如 2026-09-11 EOD）无该字段，`metrics.stageCounts.ignition` 取
    // undefined 的属性会在渲染期抛 TypeError 并中断面板渲染（分层结构空白的根因）。
    expect(source).not.toMatch(/metrics\.stageCounts\./)
    expect(source).not.toMatch(/metrics\.stageShares\./)
    // 缺字段显示 '--' 占位（formatNullableCount），不伪装成 0
    expect(source).toContain('formatNullableCount')
  })
})
