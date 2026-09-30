import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const dataTableSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'common', 'DataTable.vue'), 'utf8')

const appSource = () => readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

describe('DataTable row detail interactions', () => {
  test('opens the stock detail panel from both the context menu and row double click', () => {
    const source = dataTableSource()

    expect(source).toMatch(/@dblclick="openStockDetailFromRow\(\$event,\s*stock\)"/)
    expect(source).toMatch(/const\s+openStockDetail\s*=\s*\(\s*stock:\s*Stock,\s*triggerRect:\s*DOMRect/)
    expect(source).toMatch(/const\s+viewDetails\s*=\s*\(\)\s*=>\s*{[\s\S]*openStockDetail\(\s*contextMenu\.value\.stock/)
    expect(source).toMatch(/const\s+openStockDetailFromRow\s*=\s*\(\s*event:\s*MouseEvent,\s*stock:\s*Stock/)
    expect(source).toMatch(/getBoundingClientRect\(\)\s*\?\?/)
    expect(source).toMatch(/openStockDetail\(\s*stock,\s*triggerRect,\s*'datatable-row-double-click'\s*\)/)
  })

  test('keeps DataTable as the only stock context menu entry point', () => {
    const source = dataTableSource()
    const app = appSource()

    expect(source).toMatch(/@contextmenu\.prevent="showContextMenu\(\$event,\s*stock\)"/)
    expect(app).not.toMatch(/<ContextMenu\b/)
    expect(app).not.toMatch(/import\s+ContextMenu\s+from/)
    expect(existsSync(join(process.cwd(), 'src', 'components', 'common', 'ContextMenu.vue'))).toBe(
      false,
    )
    expect(existsSync(join(process.cwd(), 'src', 'composables', 'useStockSelector.ts'))).toBe(false)
  })

  test('adds candidates from the row context menu through the candidate journal service', () => {
    const source = dataTableSource()

    expect(source).toMatch(/import\s+\{\s*candidateJournalService\s+\}\s+from\s+['"]@\/services\/candidate\/CandidateJournalService['"]/)
    expect(source).toMatch(/candidateMenuLabel/)
    expect(source).toContain('查看候选详情')
    expect(source).toMatch(/@click="addToCandidatePool"/)
    expect(source).toMatch(/const\s+addToCandidatePool\s*=\s*async\s*\(\)\s*=>/)
    expect(source).toMatch(/candidateJournalService\.getOpenCandidateForStock/)
    expect(source).toMatch(/candidateJournalService\.addCandidateFromStock\(\s*contextMenu\.value\.stock/)
    expect(source).toMatch(/EventManager\.emit\('candidate-pool:open'/)
    expect(source).not.toMatch(/\/api\/journal\/entries/)
    expect(source).not.toMatch(/trade_hypothesis/)
  })

  test('removes the opening weak-to-strong row highlight and badge (2026-09-17 用户口径)', () => {
    const source = dataTableSource()

    // 行高亮、竞强徽章、store 消费与启停全部清理，不再残留
    expect(source).not.toContain('opening-signal-row')
    expect(source).not.toContain('opening-signal-badge')
    expect(source).not.toContain('竞强')
    expect(source).not.toContain('hasOpeningWeakToStrongSignal')
    expect(source).not.toContain('openingSignalTitle')
    expect(source).not.toContain('isOpeningWeakToStrongHighlightStage')
    expect(source).not.toContain('openingSignalStore')
    expect(source).not.toContain('openingSignalsByCode')
  })

  test('does not render the redundant RankTrend lifecycle status column', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'strategyStatus'")
    expect(source).not.toContain("col.key === 'strategyStatus'")
    expect(source).not.toContain('strategy-status-cell')
    expect(source).not.toMatch(/:class="`status-\$\{getRankTrendBreakdown\(stock\)\.classKeys\.tier\}`"/)
    expect(source).not.toMatch(/classes\.push\(`strategy-tier-\$\{getRankTrendStatus\(stock\)\.classKey\}`\)/)
  })

  test('keeps RankTrend change and jump evidence for tooltip after removing their columns', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'rankChange'")
    expect(source).not.toContain("{ key: 'confidence'")
    expect(source).toContain('getRankTrendAnalysis(stock)?.change')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalSignal')
    expect(source).toContain('getRankTrendAnalysis(stock)?.finalConfidence')
    expect(source).toMatch(/const\s+getRankChange\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalSignal\s*=\s*\(stock:\s*any\)\s*=>/)
    expect(source).toMatch(/const\s+getFinalConfidence\s*=\s*\(stock:\s*any\)\s*=>/)
  })

  test('keeps jump confidence in the shared observation tooltip', () => {
    const source = dataTableSource()

    expect(source).not.toContain("label: '跃迁度'")
    expect(source).toContain('analyzeTradingPoolCandidate')
    expect(source).toContain('getTradingPoolActionPreview')
    expect(source).toContain('getJumpConfidence')
    expect(source).toContain('getRankTrendAnalysis(stock)?.jump?.confidence')
    expect(source).toContain('Jump事件')
    expect(source).toContain('共振强度')
    expect(source).not.toContain('📌 交易池:')
    expect(source).not.toContain('共振评级')
    expect(source).not.toMatch(/<span class="signal-percent">\{\{ Math\.round\(getFinalConfidence\(stock\) \|\| 0\) \}\}%<\/span>/)
  })

  test('shows resonance intensity column with tier letter badge', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("resonanceIntensity: '60px'")
    expect(source).toContain("col.key === 'resonanceIntensity'")
    // 2026-09-29 用户裁决：单元格显示档位字母徽章；分值/方向明细由 tooltip 消费 getResonanceCellValue
    expect(source).toContain('getResonanceCellValue')
    expect(source).toContain('@mouseenter="showTierTooltip($event, stock, \'resonanceIntensity\')"')
    expect(source).toContain('rankTrend?.resonance')
    expect(source).toContain('相对市场')
    expect(source).toContain('路径持续性')
    expect(source).toContain('新鲜度')
    expect(source).toContain('市场中位数（同帧共享）')
    expect(source).toContain('数据来源: 八平台均榜横截面')
    expect(source).toContain("resonance.historyState === 'new_entry'")
    expect(source).not.toContain('resonance.qualityCap')
    expect(source).not.toContain('normalizeResonanceIntensity')
    expect(source).toContain('observation-buy')
    expect(source).toContain('observation-sell')
    expect(source).toContain('observation-hold')
    expect(source).not.toContain('resonance-very-strong')
  })

  test('shows three independent observation columns with dedicated panel tracks', () => {
    const source = dataTableSource()

    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("{ key: 'rankTrendStrength', label: '趋势'")
    expect(source).toContain("{ key: 'lifecycleOpportunity', label: '周期'")
    expect(source).toContain("rankTrendStrength: '60px'")
    expect(source).toContain("lifecycleOpportunity: '60px'")
    expect(source).toContain("openObservationPanel(stock, 'resonance')")
    expect(source).toContain("openObservationPanel(stock, 'technical')")
    expect(source).toContain("openObservationPanel(stock, 'lifecycle')")
    expect(source).toContain('getRankTrendStrengthValue')
    expect(source).toContain('getLifecycleOpportunityValue')
    expect(source).toContain('RankTrendObservationPanel')
    expect(source).toContain('v-else-if="getLifecycleStage(stock) != null"')
    expect(source).toContain('getResonanceDirection(stock)')
    expect(source).toContain('toFiniteObservationValue')
    expect(source).toContain('<span v-else class="trend-steady">--</span>')
    // 四信号列当前实现（2026-09-29 用户裁决）：共振/趋势/热度/量价 = S/A/B/C/D/E 档位字母徽章；
    // 生命周期 = stage 环境门标签（无方向色徽章，veto 移入 tooltip）
    expect(source).toContain('getDirectionArrow(getRankTrendDirection(stock))')
    // 徽章字母化：四信号列经 getSignalTierLabel/getSignalTierClass 渲染（复用 tierBadgeClass 配色），
    // 不直接调用 tierBadgeClass(getXxxTier(stock))
    expect(source).not.toContain('tierBadgeClass(getResonanceTier(stock))')
    expect(source).not.toContain('tierBadgeClass(getRankTrendTier(stock))')
    expect(source).not.toContain('tierBadgeClass(getVolumePriceTier(stock))')
    expect(source).not.toContain('tierBadgeClass(getLifecycleTier(stock))')
    // 生命周期列在单元格渲染 stage 环境门文字（点火/扩散/拥挤等）
    expect(source).toContain('getLifecycleStageLabel(stock)')
    // 量价配合：独立四象限列，样式/ tooltip 参照三指标观察列；数据由后端生产（_volumePrice*）前端只消费
    expect(source).toContain("{ key: 'volumePriceQuadrant', label: '量价'")
    expect(source).toContain("volumePriceQuadrant: '60px'")
    expect(source).toContain('_volumePriceScore')
    expect(source).toContain('_volumePriceQuadrant')
    // 投影缺失时回退 rankTrend.observation.volumePrice（与三轨读取口径一致，缓存预热可显示）
    expect(source).toContain('getVolumePrice')
    expect(source).toContain('stock?._volumePriceScore ?? vp.score')
    expect(source).toContain("getRankTrendAnalysis(stock)?.observation?.volumePrice")
    expect(source).toContain("@mouseenter=\"showTierTooltip($event, stock, 'volumePriceQuadrant')\"")
    expect(source).toContain("field === 'volumePriceQuadrant'")
    expect(source).toContain('【量价配合】')
    // 前端不生产量价评分（后端 observation.volumePrice）
    expect(source).not.toContain('computeVolumePriceScore')
    expect(source).not.toContain('classifyVolumePriceQuadrant')
    expect(source).not.toContain('resolveLiveLimitState')
    // 三指标数值列保持紧凑：不混入中文确认标记
    expect(source).not.toContain('vp-badge')
    expect(source).not.toContain('getVolumePriceBadge')
  })

  test('shows insufficient-sample label instead of misleading cooling stage in lifecycle column', () => {
    const source = dataTableSource()

    // 2026-09-10 口径统一（spec §4.1）：样本不足显示数据质量声明，不显示 lifecycle 兜底"冷却"
    expect(source).toContain('v-if="isLifecycleSampleInsufficient(stock)"')
    expect(source).toContain('v-else-if="getLifecycleStage(stock) != null"')
    expect(source).toContain('lifecycle-env-insufficient')
    expect(source).toContain("getRankTrendAnalysis(stock)?.meta?.sampleQuality?.status === 'insufficient'")
    expect(source).toContain('const isLifecycleSampleInsufficient')
    // 排序方向：样本不足按中性处理，不进买入/卖出方向组
    // 锚点收敛（code review F6）：改为两条稳定结构串断言，避免跨行正则受注释/换行影响
    expect(source).toContain('const getLifecycleDirection = (stock: any) => {')
    expect(source).toContain("if (isLifecycleSampleInsufficient(stock)) return 'hold'")
    // tooltip 阶段行同步显示样本不足（与周期列一致，不出现同股两判）
    expect(source).toContain(
      "isLifecycleSampleInsufficient(stock) ? '样本不足' : getAttentionStageDisplayText(getLifecycleStage(stock))",
    )
  })

  test('splits observation tooltips per field (D: resonance/rankTrend/lifecycle)', () => {
    const source = dataTableSource()

    // 分派入口：showConfidenceTooltip 接收第三参数 field
    expect(source).toContain('const showConfidenceTooltip = (event: MouseEvent, stock: any, field = \'\')')
    expect(source).toContain('const getFieldTooltip = (field: string, stock: any): string => {')

    // 三列分别传自己的 field，不共用同一份内容（hover 走 showTierTooltip，内部回退 showConfidenceTooltip）
    expect(source).toContain("showTierTooltip($event, stock, 'resonanceIntensity')")
    expect(source).toContain("showTierTooltip($event, stock, 'rankTrendStrength')")
    expect(source).toContain("showTierTooltip($event, stock, 'lifecycleOpportunity')")

    // 共振分支只含共振专属内容
    expect(source).toContain("if (field === 'resonanceIntensity') {")
    expect(source).toContain('【共振】')
    // 排名趋势分支
    expect(source).toContain("if (field === 'rankTrendStrength') {")
    expect(source).toContain('【排名趋势】')
    // 生命周期分支
    expect(source).toContain("if (field === 'lifecycleOpportunity') {")
    expect(source).toContain('【生命周期】')
    // 兜底：无 field 时仍是完整置信度
    expect(source).toContain('content: field ? getFieldTooltip(field, stock) : getConfidenceTitle(stock)')
  })

  test('adds a synergy tier column with badge and fallback', () => {
    const source = dataTableSource()

    // 新增【五维度】（原四维，synergy 合并档位）列（紧跟周期列后，group comprehensive）
    expect(source).toContain("{ key: 'synergyTier', label: '五维'")
    expect(source).toContain("synergyTier: '60px'")
    expect(source).toContain("col.key === 'synergyTier'")
    // 读取 synergy 档位（前端路径）+ 徽章（TierBadge 组件，2026-08-18 图标化）+ 悬停明细
    expect(source).toContain('getSynergyTier(stock)')
    expect(source).toContain('TierBadge')
    expect(source).toContain('getSynergyTierDetail')
    expect(source).toContain('getSynergyTierReasons')
    expect(source).toContain('tier-badge')
    // 缺档位回退 --（不渲染空徽章、不报错）
    expect(source).toContain('<span v-else class="trend-steady">--</span>')
    // 前端不重算档位
    expect(source).not.toContain('computeSynergyTier')
  })

  test('uses the user-requested tooltip template for synergy and lifecycle columns', () => {
    const source = dataTableSource()

    // 五维度 tooltip（2026-08-26 用户模板）：名称（代码）/ 阶段 / 周期 / 说明 + 操作建议
    expect(source).toContain('`${stockName}（${stockCode}）：`')
    expect(source).toContain('阶段：')
    expect(source).toContain('周期：')
    expect(source).toContain('周期不投方向票，但参与总档合成：E 一票否决、B/D 对 S/A 降一档、A 放行')
    expect(source).toContain('getSynergyVoteBreakdown(stock)')
    expect(source).toContain('getSynergyTierDetail(stock)')
    expect(source).toContain('getSynergyTierReasons(stock)')
    expect(source).toContain('操作建议：')
    // 周期列说明包含环境门规则与操作建议
    expect(source).toContain('周期为环境门，不投方向票，但参与总档位合成')
    expect(source).toContain('E 否决 → 总档强制否决')
    expect(source).toContain('B 谨慎 / D 回避 → 总档 S/A 降一档')
    expect(source).toContain('A 放行 → 不干预三维方向票')
  })

  test('adds a 热度（crossSection）column with tier letter badge (2026-09-29 用户裁决)', () => {
    const source = dataTableSource()

    // 热度列紧跟趋势列后（2026-08-24；技术字段 crossSection，UI 展示名「热度」），group comprehensive
    expect(source).toContain("{ key: 'crossSection', label: '热度'")
    expect(source).toContain("crossSection: '60px'")
    expect(source).toContain("col.key === 'crossSection'")
    // 2026-09-29 用户裁决：单元格显示 S/A/B/C/D/E 档位字母徽章（取消 2026-08-24 的方向+数值%）
    expect(source).toContain('getSignalTierLabel(stock, col.key)')
    expect(source).toContain('getCrossSectionTier')
    // tooltip 分支仍按 percentile 推算方向/分值展示
    expect(source).toContain("showTierTooltip($event, stock, 'crossSection')")
    expect(source).toContain("field === 'crossSection'")
  })

  test('renders S/A/B/C/D/E letter badges in the four signal columns (2026-09-29 用户裁决)', () => {
    const source = dataTableSource()

    // 四信号列（共振/趋势/热度/量价）档位取值复用 tierDisplay（后端 signalTier，不新增档位算法）
    expect(source).toContain('resonanceIntensity: getResonanceTier,')
    expect(source).toContain('rankTrendStrength: getRankTrendTier,')
    expect(source).toContain('crossSection: getCrossSectionTier,')
    expect(source).toContain('volumePriceQuadrant: getVolumePriceTier,')
    // 单元格：tier-badge 基础类 + tierBadgeClass 配色 + tierBadgeLabel 字母
    expect(source).toContain('class="tier-badge"')
    expect(source).toContain('getSignalTierClass(stock, col.key)')
    expect(source).toContain('{{ getSignalTierLabel(stock, col.key) }}</span>')
    // 档位缺失/unknown → null → 显示 '--'（fail-visible，不伪装）
    expect(source).toContain("tier && tier !== 'unknown' ? tierBadgeLabel(tier) : null")
    expect(source).toContain('<span v-else class="trend-steady">--</span>')
    // 字母徽章与五维度列 TierBadge 图标区分：四信号列不使用 TierBadge 组件
    expect(source).not.toContain('<TierBadge v-if="getSignalTierLabel')
    // 趋势列 MACD 金/死叉 ▲▼ 事件徽章保留
    expect(source).toContain("getMacdCrossBadge(stock) === 'golden'")
    expect(source).toContain("getMacdCrossBadge(stock) === 'death'")
  })

  test('collapses the nine platform rank columns by default with a toggle', () => {
    const source = dataTableSource()

    // 折叠集合：8 平台 + 均榜（9 个），默认折叠
    expect(source).toContain("const rankColumnsCollapsed = ref(true)")
    for (const key of ['emRank', 'thsRank', 'kplRank', 'tdxRank', 'xqRank', 'clsRank', 'tgbRank', 'dzhRank', 'avgRank']) {
      expect(source).toContain(`'${key}'`)
    }
    // visibleColumns 过滤折叠列
    expect(source).toContain('COLLAPSIBLE_RANK_KEYS.has(col.key)')
    // 切换函数
    expect(source).toContain('const toggleRankColumns')
    // 综合列左侧三角按钮（左/右三角，点击切换，不触发排序冒泡）
    expect(source).toContain('rank-collapse-toggle')
    expect(source).toContain('@click.stop="toggleRankColumns"')
    expect(source).toContain("rankColumnsCollapsed ? '◀' : '▶'")
  })

  test('collapses the five observation columns via the synergy tier toggle', () => {
    const source = dataTableSource()

    // 折叠集合：共振/趋势/热度/量价/周期，默认展开
    expect(source).toContain('const observationColumnsCollapsed = ref(false)')
    for (const key of ['resonanceIntensity', 'rankTrendStrength', 'crossSection', 'volumePriceQuadrant', 'lifecycleOpportunity']) {
      expect(source).toContain(`'${key}'`)
    }
    // visibleColumns 过滤观察列
    expect(source).toContain('COLLAPSIBLE_OBSERVATION_KEYS.has(col.key)')
    expect(source).toContain('const toggleObservationColumns')
    // synergy 列左侧三角按钮（与综合列折叠方式一致）
    expect(source).toContain("@click.stop=\"toggleObservationColumns\"")
    expect(source).toContain("observationColumnsCollapsed ? '◀' : '▶'")
  })

  test('collapses the quote columns (流通值/总市值/市盈率/市净率) via the turnover toggle', () => {
    const source = dataTableSource()

    // 2026-09-02 用户口径：默认只打开 3日量比/换手%/成交量/成交额，其余四列默认折叠；
    // 成交额移出折叠集合（始终显示），折叠按钮从成交量列改挂成交额列
    expect(source).toContain("const quoteColumnsCollapsed = ref(true)")
    for (const key of ['cirMV', 'totalMV', 'pe', 'pb']) {
      expect(source).toContain(`'${key}'`)
    }
    // visibleColumns 过滤行情列
    expect(source).toContain('COLLAPSIBLE_QUOTE_KEYS.has(col.key)')
    expect(source).toContain('const toggleQuoteColumns')
    // 成交额列 title 右侧三角按钮（与综合/synergy 折叠方式一致）
    expect(source).toContain("@click.stop=\"toggleQuoteColumns\"")
    expect(source).toContain("quoteColumnsCollapsed ? '◀' : '▶'")
  })

  test('collapses limit-up detail columns via the lianban toggle, keeps 连板/涨停原因 visible', () => {
    const source = dataTableSource()

    // 2026-09-02 用户口径：涨停相关组默认只显示连板+涨停原因，
    // 首次/最后涨停/封单/开板默认折叠，点击连板列右侧三角展开
    expect(source).toContain('const limitupColumnsCollapsed = ref(true)')
    for (const key of ['firstZtTime', 'lastZtTime', 'fengdan', 'openNum']) {
      expect(source).toContain(`'${key}'`)
    }
    expect(source).toContain('COLLAPSIBLE_LIMITUP_KEYS.has(col.key)')
    expect(source).toContain('const toggleLimitupColumns')
    expect(source).toContain("@click.stop=\"toggleLimitupColumns\"")
    expect(source).toContain("limitupColumnsCollapsed ? '◀' : '▶'")
  })

  test('opens the observation panel from the volume price column too', () => {
    const source = dataTableSource()

    // 量价列与共振/趋势/周期一致：点击打开 OBSERVATION 面板（volumePrice track）
    expect(source).toContain("@click.stop=\"openObservationPanel(stock, 'volumePrice')\"")
    expect(source).toContain("@click.stop=\"openObservationPanel(stock, 'resonance')\"")
    expect(source).toContain("@click.stop=\"openObservationPanel(stock, 'technical')\"")
    expect(source).toContain("@click.stop=\"openObservationPanel(stock, 'lifecycle')\"")
  })

  test('centers the synergy tier badge in its cell', () => {
    const source = dataTableSource()

    expect(source).toContain('.synergy-tier-cell')
    expect(source).toContain('align-items: center')
    expect(source).toContain('justify-content: center')
  })

  test('keeps observation cells vertically centered and lifecycle tooltip carries stage', () => {
    const source = dataTableSource()

    // .observation-cell 撑满 cell 高度并垂直居中（解决徽章靠上）
    expect(source).toContain('height: 100%')
    expect(source).toContain('line-height: 1')
    // 周期 tooltip（2026-08-26 用户模板）：名称（代码）/ 阶段 / 周期 / 说明 + 操作建议
    expect(source).toContain("field === 'lifecycleOpportunity'")
    expect(source).toContain('getLifecycleStageLabel(stock)')
    expect(source).toContain('阶段：')
    expect(source).toContain('周期为环境门，不投方向票，但参与总档位合成')
    expect(source).toContain('操作建议：')
    expect(source).toContain("parts.join('：')")
  })

  test('market table does not include a theme momentum column (panel only)', () => {
    const source = dataTableSource()

    // 行情列表不渲染题材动量列（题材动量仅在独立面板 / 顶部 tab）
    expect(source).not.toContain("{ key: 'themeMomentum'")
    expect(source).not.toContain("col.key === 'themeMomentum'")
    expect(source).not.toContain('open-theme-momentum')
    // 其余三列仍在
    expect(source).toContain("{ key: 'resonanceIntensity', label: '共振'")
    expect(source).toContain("{ key: 'rankTrendStrength', label: '趋势'")
    expect(source).toContain("{ key: 'lifecycleOpportunity', label: '周期'")
  })

  test('structures the confidence tooltip as conclusion, resonance, technical, and risk layers', () => {
    const source = dataTableSource()

    expect(source).toContain('【观察结论】')
    expect(source).toContain('【共振路径】')
    expect(source).toContain('【技术结构】')
    expect(source).toContain('【阶段与风险】')
    expect(source).toContain('共振方向:')
    expect(source).toContain('共振强度:')
    expect(source).toContain('Jump事件:')
    expect(source).toContain('新鲜度')
    expect(source).toContain('过热风险:')
    expect(source).toContain('资金背离风险:')
    expect(source).not.toContain('🎯 综合判断:')
    expect(source).not.toContain('🔥 过热反转风险:')
    expect(source).not.toContain('💰 热度资金背离:')
  })

  test('keeps jump direction evidence in the tooltip after removing its badge column', () => {
    const source = dataTableSource()

    expect(source).toContain("const jumpDir = getJumpDirection(stock)")
    expect(source).toContain('Jump事件:')
    expect(source).not.toContain(':class="getJumpSignalBadgeClass(stock)"')
    expect(source).not.toContain("v-if=\"getFinalSignal(stock) === 'buy'\"")
    expect(source).not.toContain("v-else-if=\"getFinalSignal(stock) === 'sell'\"")
    expect(source).not.toContain("v-else-if=\"getFinalSignal(stock) === 'hold'\"")
  })

  test('uses one row-style tooltip for theme detail and removes rank-change noise', () => {
    const source = dataTableSource()

    expect(source).not.toMatch(/class="data-row"[\s\S]*@mouseenter="showRowTooltip\(\$event,\s*stock\)"/)
    expect(source).not.toContain(':title="getThemesTitle(getStockThemes(stock))"')
    expect(source).toContain('@mouseenter="showThemeTooltip($event, stock)"')
    expect(source).toContain('getMergedThemeTooltipTitle')
    expect(source).toContain('📋 关联原因')
    expect(source).not.toMatch(/const\s+getRowTitle[\s\S]*排名变化/)
  })

  test('does not render rarely used super-large money flow columns', () => {
    const source = dataTableSource()

    expect(source).not.toContain("{ key: 'cddje'")
    expect(source).not.toContain("{ key: 'cddjzb'")
    expect(source).not.toContain("case 'cddje'")
    expect(source).not.toContain("case 'cddjzb'")
  })

  test('labels THS L2 and akshare money flow appropriately', () => {
    const source = dataTableSource()

    expect(source).toContain('getMoneyFlowTitle')
    expect(source).toContain('同花顺个股资金流')
    expect(source).toContain('同花顺网页资金流（估算）')
    // 2026-08-14：废弃源（同花顺L2主力监控/QMT L2/东财/TDX 分笔估算）已移除
    expect(source).not.toContain('同花顺L2主力监控')
    expect(source).not.toContain('QMT L2实时资金流')
  })

  test('keeps volume ratio display visually stable across data states', () => {
    const source = dataTableSource()

    expect(source).toMatch(/if \(key === 'volumeRatio'\)[\s\S]*classes\.push\('volume-ratio-cell'\)/)
    expect(source).not.toContain('volume-ratio-stale')
    expect(source).not.toContain('volume-ratio-suspicious')
    expect(source).not.toContain('volume-ratio-unavailable')
    expect(source).not.toContain('volume-ratio-high')
    expect(source).not.toContain('volume-ratio-low')
    expect(source).not.toContain("return `${ratio.toFixed(2)}*`")
    expect(source).not.toContain("return `!${ratio.toFixed(2)}`")
  })

  test('resonance tooltip decoupled from theme momentum (D2)', () => {
    const source = dataTableSource()

    expect(source).not.toContain('【题材动量】')
    expect(source).not.toContain('themeMomentumScore')
    expect(source).not.toContain('resonance.theme')
  })

  test('avgRankNum 999 sentinel renders as "-" (2026-08-25 P1 复盘)', () => {
    // 采集器全平台缺失时 avgRankNum=999 → avgRank="999.0" 字符串，须与 compRank/平台 rank 999 一致显示 '-'
    const source = dataTableSource()
    expect(source).toContain("Number(value) >= 999 ? '-' : value")
  })

  test('trend column triangle badge is driven by MACD cross events (2026-09-21 用户裁决)', () => {
    const source = dataTableSource()

    // 趋势列 ▲▼ 徽章只认 py golden technical.macd.cross（交叉帧才非 none 的事件语义），
    // 不再使用 MA10×MA20 徽章口径；缺字段 → 'none' → 无徽章
    expect(source).toContain("getMacdCrossBadge(stock) === 'golden'")
    expect(source).toContain("getMacdCrossBadge(stock) === 'death'")
    expect(source).toContain('title="MACD 金叉"')
    expect(source).toContain('title="MACD 死叉"')
    expect(source).toMatch(/const\s+getMacdCrossBadge\s*=\s*\(stock:\s*any\)\s*=>\s*[\s\S]*?technical\?\.macd\?\.cross/)
    // 徽章行不再消费 MA 交叉口径（ma-badge 只由 getMacdCrossBadge 驱动）
    expect(source).not.toMatch(/getMaCross\(stock\)[^?]*\?\?\s*'[\s\S]{0,80}ma-badge/)
    expect(source).not.toContain('title="MA10×MA20 金叉"')
    expect(source).not.toContain('title="MA10×MA20 死叉"')
    // MA 交叉因子本身保留：五因子投票与 tooltip 展示仍消费 getMaCross
    expect(source).toContain('getMaCross(stock)')
  })

})
