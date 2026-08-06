import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = () =>
  readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'RankTrendObservationPanel.vue'),
    'utf8',
  )

describe('RankTrendObservationPanel', () => {
  it('renders a right-side three-track observation cockpit without candidate-pool content', () => {
    const panel = source()

    expect(panel).toContain('observation-drawer')
    expect(panel).toContain("{ id: 'resonance'")
    expect(panel).toContain("{ id: 'technical'")
    expect(panel).toContain("{ id: 'lifecycle'")
    expect(panel).toContain("activeTrack === 'resonance'")
    expect(panel).toContain("activeTrack === 'technical'")
    expect(panel).toContain("activeTrack === 'lifecycle'")
    expect(panel).toContain('共振路径')
    expect(panel).toContain('技术结构')
    expect(panel).toContain('阶段与风险')
    expect(panel).toContain('最近 {{ trackFrames.length }} 帧')
    expect(panel).toContain('OBSERVATION_WINDOW_BARS')
    expect(panel).toContain("event.key === 'Escape'")
    expect(panel).toContain('function scoreText')
    expect(panel).toContain("return '--'")
    expect(panel).not.toContain('<small>/ 100</small>')
    expect(panel).toContain('width: percent(resonance?.relativeMomentum)')
    expect(panel).toContain('text: signedPercent(resonance?.relativeMomentum)')
    expect(panel).toContain("frame.issues.map((issue) => issue.message).join('；')")
    expect(panel).toContain("meta?.analysisSource === 'analysis_unavailable'")
    expect(panel).toContain('分析不可用')
    expect(panel).toContain('analysisUnavailableReason')
    expect(panel).toContain('if (!macd) return []')
    expect(panel).toContain('macdCrossPoints')
    expect(panel).toContain("cross === 'golden' ? '金叉' : '死叉'")
    expect(panel).not.toContain('Number(macd?.dif || 0)')
    expect(panel).not.toContain('Number(frame.analysis?.technical?.macd?.histogram || 0)')
    expect(panel).not.toContain('候选池')
    expect(panel).not.toContain('grid-template-columns: repeat(9')
    expect(panel).toContain('stageRailStyle')
  })

  it('共振轨 jump 标记显示幅度数值，Jump 事件行分两段展示置信度与新鲜度', () => {
    const panel = source()

    expect(panel).not.toContain('>JUMP</text>')
    expect(panel).toContain('jumpValueText')
    expect(panel).toContain('jumpMagnitude')
    expect(panel).not.toContain("label: 'Jump 新鲜度'")
    expect(panel).not.toContain("label: 'Jump 跳跃度'")
    expect(panel).toContain("label: 'Jump 事件'")
    expect(panel).toContain('segments')
    expect(panel).toContain('freshness-tone')
    expect(panel).toContain('resonance?.jumpFreshness')
    expect(panel).toContain('jumpFreshness * 100')
  })

  it('共振轨市场线分为恒定 50 参考线与动态市场中位折线', () => {
    const panel = source()

    expect(panel).not.toContain('同帧市场中位')
    expect(panel).toContain('恒定市场中位（50 参考）')
    expect(panel).toContain('动态市场中位')
    expect(panel).toContain('class="market-reference"')
    expect(panel).toContain('chartY(50)')
    expect(panel).toContain('dynamicMarketPath')
    expect(panel).toContain('marketMedianShortChange')
    expect(panel).not.toContain('percentilePath')
    expect(panel).not.toContain('marketMedianPercentile')
  })

  it('投影缓存命中时观察舱显示缓存标注', () => {
    const panel = source()

    expect(panel).toContain("source === 'cache'")
  })

  it('theme track renders analysis.themeMomentum as the fourth observation track', () => {
    const panel = source()

    expect(panel).toContain("{ id: 'theme', index: '04', label: '题材动量' }")
    expect(panel).toContain("activeTrack === 'theme'")
    expect(panel).toContain('TRACK 04')
    expect(panel).toContain('selectedAnalysis?.themeMomentum?.score')
    expect(panel).toContain('momentumDirectionClass')
    expect(panel).toContain('momentumDirectionText')
    // 旧 resonance 轨内嵌题材行已移除（D2 解耦）
    expect(panel).not.toContain("label: '题材生命周期'")
    expect(panel).not.toContain('resonance?.theme?.themeMomentumScore')
    expect(panel).not.toContain('themeRoleLabel')
  })

  it('关闭/切换股票/卸载时取消 in-flight 观察请求', () => {
    const panel = source()

    expect(panel).toContain('loadAbortController')
    expect(panel).toContain('loadAbortController.abort()')
    expect(panel).toContain('rankTrendObservationService.load(props.stock, { signal: controller.signal })')
    expect(panel).toContain("error.name === 'AbortError'")
  })
})

describe('RankTrendObservationPanel theme momentum track', () => {
  const panel = () =>
    readFileSync(
      join(process.cwd(), 'src', 'components', 'panels', 'RankTrendObservationPanel.vue'),
      'utf8',
    )
  const service = () =>
    readFileSync(
      join(process.cwd(), 'src', 'services', 'rankTrend', 'RankTrendObservationService.ts'),
      'utf8',
    )
  const dataTable = () =>
    readFileSync(join(process.cwd(), 'src', 'components', 'common', 'DataTable.vue'), 'utf8')

  it('adds theme as the fourth track with index 04', () => {
    expect(panel()).toContain("{ id: 'theme', index: '04', label: '题材动量' }")
  })

  it('adds theme window to OBSERVATION_WINDOW_BARS', () => {
    expect(service()).toContain('theme: 15')
  })

  it('renders analysis.themeMomentum with score/direction/phaseLabel', () => {
    expect(panel()).toContain('selectedAnalysis?.themeMomentum')
    expect(panel()).toContain('phaseLabel')
  })

  it('does not read resonance.theme for theme momentum anymore', () => {
    expect(panel()).not.toContain('resonance?.theme?.themeMomentumScore')
  })

  it('DataTable resonance tooltip is decoupled from theme momentum', () => {
    expect(dataTable()).not.toContain('【题材动量】')
    expect(dataTable()).not.toContain('resonance.theme.themeMomentumScore')
  })
})
