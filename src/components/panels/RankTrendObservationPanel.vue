<template>
  <Teleport to="body">
    <div v-if="visible" class="observation-layer">
      <aside class="observation-drawer" role="dialog" aria-modal="false" aria-label="排名趋势三轨观察舱">
        <header class="cockpit-header">
          <div>
            <div class="eyebrow">RANKTREND / OBSERVATION</div>
            <div class="stock-title">
              <strong>{{ stock?.name || '未命名股票' }}</strong>
              <span>{{ stock?.code || '--' }}</span>
            </div>
          </div>
          <button class="icon-button" type="button" title="关闭观察舱" aria-label="关闭观察舱" @click="close">
            ×
          </button>
        </header>

        <div class="summary-strip">
          <div>
            <span>共振</span>
            <strong :class="directionClass(latestAnalysis?.resonance?.direction)">
              {{ directionalScore(latestAnalysis?.resonance?.direction, resonanceScore(latestAnalysis?.resonance), true)
              }}
            </strong>
          </div>
          <div>
            <span>技术</span>
            <strong :class="directionClass(latestAnalysis?.observation?.rankTrend?.direction)">
              {{ directionalScore(latestAnalysis?.observation?.rankTrend?.direction,
                latestAnalysis?.observation?.rankTrend?.score, true) }}
            </strong>
          </div>
          <div>
            <span>生命周期</span>
            <strong :class="stageClass(latestAnalysis?.observation?.lifecycle?.stage)">
              {{ lifecycleScore(latestAnalysis?.observation?.lifecycle?.stage,
                latestAnalysis?.observation?.lifecycle?.score, true) }}
            </strong>
          </div>
        </div>

        <nav class="track-switcher" aria-label="观察轨道">
          <button v-for="track in tracks" :key="track.id" type="button" :class="{ active: activeTrack === track.id }"
            @click="activeTrack = track.id">
            <span class="track-index">{{ track.index }}</span>
            <span>{{ track.label }}</span>
          </button>
        </nav>

        <div class="cockpit-body">
          <div v-if="loading" class="panel-state">
            <span class="loading-mark"></span>
            正在载入数据...
          </div>

          <div v-else-if="loadError" class="panel-state error-state">
            <strong>观察服务暂时不可用</strong>
            <span>{{ loadError }}</span>
          </div>

          <template v-else>
            <div v-if="allIssues.length" class="quality-banner">
              <strong>数据观察项</strong>
              <span v-for="issue in allIssues" :key="issueKey(issue)">{{ issue.message }}</span>
            </div>

            <section v-if="activeTrack === 'resonance'" class="track-section">
              <div class="section-heading">
                <div>
                  <span class="section-kicker">TRACK 01</span>
                  <h2>共振路径</h2>
                </div>
                <div class="section-score" :class="directionClass(selectedAnalysis?.resonance?.direction)">
                  {{ directionalScore(selectedAnalysis?.resonance?.direction,
                    resonanceScore(selectedAnalysis?.resonance), true) }}
                </div>
              </div>

              <div class="chart-shell">
                <div class="chart-legend">
                  <span><i class="legend-line stock-line"></i>个股关注度百分位</span>
                  <span><i class="legend-line market-line"></i>同帧市场中位</span>
                </div>
                <svg class="path-chart" viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="最近九帧共振路径">
                  <line v-for="tick in [25, 50, 75]" :key="tick" x1="0" x2="620" :y1="chartY(tick)" :y2="chartY(tick)"
                    class="grid-line" />
                  <path :d="percentilePath" class="market-path" />
                  <path :d="stockPath" class="stock-path" />
                  <g v-for="point in jumpPoints" :key="point.key">
                    <circle :cx="point.x" :cy="point.y" r="5" class="jump-dot" />
                    <text :x="point.x" :y="point.y - 10" text-anchor="middle" class="jump-label">JUMP</text>
                  </g>
                </svg>
              </div>

              <div class="factor-stack">
                <div v-for="factor in resonanceFactors" :key="factor.label" class="factor-row">
                  <span>{{ factor.label }}</span>
                  <div class="factor-meter"><i :style="{ width: `${factor.width}%` }" :class="factor.tone"></i></div>
                  <strong>{{ factor.text }}</strong>
                </div>
              </div>
              <div class="evidence-note">
                市场中位数（同帧共享）
                <strong>{{ signed(selectedFrame?.marketMedianShortChange, 1) }}</strong>
                <span>{{ selectedFrame?.marketSampleCount || 0 }} 个横截面样本</span>
              </div>
            </section>

            <section v-if="activeTrack === 'technical'" class="track-section">
              <div class="section-heading">
                <div>
                  <span class="section-kicker">TRACK 02</span>
                  <h2>技术结构</h2>
                </div>
                <div class="section-score" :class="directionClass(selectedAnalysis?.observation?.rankTrend?.direction)">
                  {{ directionalScore(selectedAnalysis?.observation?.rankTrend?.direction,
                    selectedAnalysis?.observation?.rankTrend?.score, true) }}
                </div>
              </div>

              <div class="chart-shell macd-shell">
                <div class="chart-legend">
                  <span><i class="legend-line dif-line"></i>DIF</span>
                  <span><i class="legend-line dea-line"></i>DEA</span>
                  <span>柱体</span>
                </div>
                <svg class="path-chart" viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="最近九帧 MACD 结构">
                  <line x1="0" x2="620" y1="95" y2="95" class="zero-line" />
                  <rect v-for="bar in macdBars" :key="bar.key" :x="bar.x" :y="bar.y" :width="bar.width"
                    :height="bar.height" :class="bar.positive ? 'macd-positive' : 'macd-negative'" />
                  <path :d="difPath" class="dif-path" />
                  <path :d="deaPath" class="dea-path" />
                </svg>
              </div>

              <div class="signal-matrix">
                <div v-for="signal in technicalSignals" :key="signal.label" class="signal-row">
                  <span>{{ signal.label }}</span>
                  <strong :class="directionClass(signal.direction)">{{ signal.available ?
                    directionLabel(signal.direction) : '--' }}</strong>
                  <div class="bipolar-meter">
                    <i class="meter-zero"></i>
                    <i :class="(signal.value || 0) >= 0 ? 'positive' : 'negative'"
                      :style="bipolarStyle(signal.value)"></i>
                  </div>
                  <b>{{ signal.value == null ? '--' : signed(signal.value * 100, 0) }}</b>
                </div>
              </div>
            </section>

            <section v-if="activeTrack === 'lifecycle'" class="track-section">
              <div class="section-heading">
                <div>
                  <span class="section-kicker">TRACK 03</span>
                  <h2>阶段与风险</h2>
                </div>
                <div class="section-score" :class="stageClass(selectedAnalysis?.observation?.lifecycle?.stage)">
                  {{ lifecycleScore(selectedAnalysis?.observation?.lifecycle?.stage,
                    selectedAnalysis?.observation?.lifecycle?.score, true) }}
                </div>
              </div>

              <div class="stage-rail" aria-label="最近九帧生命周期阶段">
                <div v-for="frame in frames" :key="frame.key" :class="stageClass(frame.analysis?.cycle?.stage)">
                  <i></i>
                  <span>{{ stageLabel(frame.analysis?.cycle?.stage) }}</span>
                </div>
              </div>

              <div class="factor-stack lifecycle-factors">
                <div v-for="factor in lifecycleFactors" :key="factor.label" class="factor-row">
                  <span>{{ factor.label }}</span>
                  <div class="factor-meter"><i :style="{ width: `${factor.width}%` }" class="lifecycle-tone"></i></div>
                  <strong>{{ factor.text }}</strong>
                </div>
              </div>

              <div class="risk-grid">
                <div v-for="risk in riskSignals" :key="risk.label" class="risk-row">
                  <div><span>{{ risk.label }}</span><strong>{{ risk.level }}</strong></div>
                  <div class="risk-meter"><i :style="{ width: `${risk.value}%` }"></i></div>
                  <p>{{ risk.reason }}</p>
                </div>
              </div>

              <div v-if="selectedAnalysis?.observation?.lifecycle?.veto" class="veto-alert">
                <strong>风险否决警示</strong>
                <span>{{ selectedAnalysis.observation.lifecycle.reasons.join('；') || '风险条件已触发' }}</span>
              </div>
            </section>

            <footer class="frame-timeline">
              <div class="timeline-heading">
                <strong>最近 9 帧</strong>
                <span>三轨同步回看</span>
              </div>
              <div class="timeline-buttons">
                <button v-for="(frame, index) in frames" :key="frame.key" type="button"
                  :class="{ active: index === selectedIndex, degraded: frame.issues.length > 0 }"
                  :title="frame.issues.map((issue) => issue.message).join('；') || frame.key"
                  @click="selectedIndex = index">
                  <i></i>
                  <span>{{ frame.label }}</span>
                </button>
              </div>
            </footer>
          </template>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  rankTrendObservationService,
  type ObservationTrack,
  type RankTrendObservationIssue,
  type RankTrendObservationFrame,
  type RankTrendObservationViewModel,
} from '@/services/rankTrend/RankTrendObservationService'
import type { AttentionStage, RankSignalDirection } from '@/services/rankTrend/types'

const props = defineProps<{
  visible: boolean
  stock: any | null
  initialTrack: ObservationTrack
}>()

const emit = defineEmits<{ (event: 'close'): void }>()

const tracks: Array<{ id: ObservationTrack; index: string; label: string }> = [
  { id: 'resonance', index: '01', label: '共振路径' },
  { id: 'technical', index: '02', label: '技术结构' },
  { id: 'lifecycle', index: '03', label: '阶段与风险' },
]

const activeTrack = ref<ObservationTrack>('resonance')
const viewModel = ref<RankTrendObservationViewModel | null>(null)
const selectedIndex = ref(0)
const loading = ref(false)
const loadError = ref('')
let loadToken = 0

const frames = computed(() => viewModel.value?.frames || [])
const selectedFrame = computed<RankTrendObservationFrame | null>(() => frames.value[selectedIndex.value] || null)
const selectedAnalysis = computed(() => selectedFrame.value?.analysis || null)
const latestAnalysis = computed(() => frames.value.at(-1)?.analysis || props.stock?.rankTrend || null)
const allIssues = computed(() => {
  const issues = [...(viewModel.value?.issues || []), ...(selectedFrame.value?.issues || [])]
  return [...new Map(issues.map((issue) => [issueKey(issue), issue])).values()]
})

watch(
  () => props.initialTrack,
  (track) => {
    activeTrack.value = track
  },
  { immediate: true },
)

watch(
  [() => props.visible, () => props.stock?.code],
  async ([visible, code]) => {
    if (!visible || !code) return
    const token = ++loadToken
    loading.value = true
    loadError.value = ''
    try {
      const result = await rankTrendObservationService.load(props.stock)
      if (token !== loadToken) return
      viewModel.value = result
      selectedIndex.value = Math.max(0, result.frames.length - 1)
    } catch (error) {
      if (token !== loadToken) return
      loadError.value = error instanceof Error ? error.message : String(error)
      viewModel.value = null
    } finally {
      if (token === loadToken) loading.value = false
    }
  },
  { immediate: true },
)

function close() {
  emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.visible) close()
}

onMounted(() => document.addEventListener('keydown', handleKeydown))
onUnmounted(() => document.removeEventListener('keydown', handleKeydown))

function scoreText(value?: number | null, withPercent = false) {
  if (value == null || !Number.isFinite(Number(value))) return '--'
  const text = String(Math.round(Number(value)))
  return withPercent ? `${text}%` : text
}

function resonanceScore(resonance?: { status?: string; score?: number } | null) {
  return resonance?.status === 'ok' ? resonance.score : null
}

function directionalScore(
  direction?: RankSignalDirection | null,
  value?: number | null,
  withPercent = false,
) {
  const score = scoreText(value, withPercent)
  return score === '--' ? score : `${directionArrow(direction)}${score}`
}

function lifecycleScore(
  stage?: AttentionStage | null,
  value?: number | null,
  withPercent = false,
) {
  const score = scoreText(value, withPercent)
  return score === '--' ? score : `${stageLabel(stage)} ${score}`
}

function issueKey(issue: RankTrendObservationIssue) {
  return [issue.code, issue.frameKey, issue.field, issue.track].filter(Boolean).join(':')
}

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : 0))
}

function percent(value?: number | null) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.round(clamp(Math.abs(numeric) <= 1 ? Math.abs(numeric) * 100 : Math.abs(numeric)))
}

function percentText(value?: number | null) {
  return value == null || !Number.isFinite(Number(value)) ? '--' : `${percent(value)}%`
}

function signed(value?: number | null, digits = 0) {
  if (value == null) return '--'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(digits)}`
}

function signedPercent(value?: number | null) {
  if (value == null || !Number.isFinite(Number(value))) return '--'
  return `${signed(Number(value) * 100, 0)}%`
}

function directionArrow(direction?: string | null) {
  return direction === 'buy' ? '↑' : direction === 'sell' ? '↓' : '—'
}

function directionLabel(direction?: string | null) {
  return direction === 'buy' ? '向上' : direction === 'sell' ? '向下' : '中性'
}

function directionClass(direction?: string | null) {
  return direction === 'buy' ? 'direction-up' : direction === 'sell' ? 'direction-down' : 'direction-hold'
}

const stageLabels: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
}

function stageLabel(stage?: AttentionStage | null) {
  return stage ? stageLabels[stage] || stage : '未知'
}

function stageClass(stage?: AttentionStage | null) {
  return stage ? `stage-${stage}` : 'stage-unknown'
}

function chartY(value: number) {
  return 180 - clamp(value) * 1.7
}

function linePath(values: Array<number | null>, yProject: (value: number) => number) {
  if (values.length === 0) return ''
  const step = values.length === 1 ? 0 : 600 / (values.length - 1)
  let drawing = false
  return values
    .map((value, index) => {
      if (value == null || !Number.isFinite(value)) {
        drawing = false
        return ''
      }
      const command = drawing ? 'L' : 'M'
      drawing = true
      return `${command}${10 + index * step},${yProject(value)}`
    })
    .filter(Boolean)
    .join(' ')
}

const stockPath = computed(() => linePath(frames.value.map((frame) => frame.percentile), chartY))
const percentilePath = computed(() =>
  linePath(frames.value.map((frame) => frame.marketMedianPercentile), chartY),
)
const jumpPoints = computed(() => {
  const step = frames.value.length <= 1 ? 0 : 600 / (frames.value.length - 1)
  return frames.value.flatMap((frame, index) =>
    frame.analysis?.jump?.event === 'jump'
      ? [{ key: frame.key, x: 10 + index * step, y: chartY(frame.percentile) }]
      : [],
  )
})

const resonanceFactors = computed(() => {
  const resonance = selectedAnalysis.value?.resonance
  return [
    { label: '相对动量', width: percent(resonance?.relativeMomentum), text: signedPercent(resonance?.relativeMomentum), tone: 'positive-tone' },
    { label: '加速度', width: percent(resonance?.acceleration), text: signedPercent(resonance?.acceleration), tone: Number(resonance?.acceleration || 0) >= 0 ? 'positive-tone' : 'negative-tone' },
    { label: '路径持续性', width: percent(resonance?.persistence), text: percentText(resonance?.persistence), tone: 'positive-tone' },
    { label: 'Jump 新鲜度', width: percent(resonance?.jumpFreshness), text: percentText(resonance?.jumpFreshness), tone: 'jump-tone' },
    { label: '反转惩罚', width: percent(resonance?.reversalPenalty), text: percentText(resonance?.reversalPenalty), tone: 'negative-tone' },
  ]
})

function technicalValue(signal?: { score?: number; signal?: RankSignalDirection } | null): number | null {
  if (!signal) return null
  const value = Number(signal?.score)
  if (Number.isFinite(value)) return Math.max(-1, Math.min(1, value))
  return signal.signal === 'buy' ? 1 : signal.signal === 'sell' ? -1 : 0
}

const technicalSignals = computed(() => {
  const analysis = selectedAnalysis.value
  const signals = analysis?.technical?.signals
  const macd = analysis?.technical?.macd
  const macdScore = Number(macd?.rawScore)
  return [
    { label: '方向一致性', direction: signals?.direction?.signal, value: technicalValue(signals?.direction), available: Boolean(signals?.direction) },
    { label: '多周期加速度', direction: signals?.acceleration?.signal, value: technicalValue(signals?.acceleration), available: Boolean(signals?.acceleration) },
    { label: '零线交叉', direction: signals?.zeroCross?.signal, value: technicalValue(signals?.zeroCross), available: Boolean(signals?.zeroCross) },
    { label: 'MACD', direction: macdScore > 0 ? 'buy' : macdScore < 0 ? 'sell' : 'hold', value: Number.isFinite(macdScore) ? Math.max(-1, Math.min(1, macdScore)) : null, available: Boolean(macd) && Number.isFinite(macdScore) },
  ] as Array<{ label: string; direction?: RankSignalDirection; value: number | null; available: boolean }>
})

function bipolarStyle(value: number | null) {
  const numeric = value ?? 0
  const width = clamp(Math.abs(numeric) * 50, 0, 50)
  return numeric >= 0 ? { left: '50%', width: `${width}%` } : { right: '50%', width: `${width}%` }
}

const macdScale = computed(() => {
  const values = frames.value.flatMap((frame) => {
    const macd = frame.analysis?.technical?.macd
    if (!macd) return []
    return [macd.dif, macd.dea, macd.histogram].filter(Number.isFinite)
  })
  return Math.max(0.01, ...values.map(Math.abs))
})

function macdY(value: number) {
  return 95 - (value / macdScale.value) * 78
}

const difPath = computed(() => linePath(frames.value.map((frame) => frame.analysis?.technical?.macd?.dif ?? null), macdY))
const deaPath = computed(() => linePath(frames.value.map((frame) => frame.analysis?.technical?.macd?.dea ?? null), macdY))
const macdBars = computed(() => {
  const count = Math.max(1, frames.value.length)
  const step = count === 1 ? 600 : 600 / (count - 1)
  const width = Math.min(22, step * 0.42)
  return frames.value.flatMap((frame, index) => {
    const value = Number(frame.analysis?.technical?.macd?.histogram)
    if (!Number.isFinite(value)) return []
    const y = macdY(value)
    return [{
      key: frame.key,
      x: 10 + index * step - width / 2,
      y: Math.min(95, y),
      width,
      height: Math.max(1, Math.abs(95 - y)),
      positive: value >= 0,
    }]
  })
})

const lifecycleFactors = computed(() => {
  const factors = selectedAnalysis.value?.observation?.lifecycle?.factors
  return [
    { label: '阶段适配', width: percent(factors?.stageFitness), text: percentText(factors?.stageFitness) },
    { label: '路径承诺', width: percent(factors?.pathCommitment), text: percentText(factors?.pathCommitment) },
    { label: '动量确认', width: percent(factors?.momentumConfirmation), text: percentText(factors?.momentumConfirmation) },
    { label: '风险安全', width: percent(factors?.riskSafety), text: percentText(factors?.riskSafety) },
  ]
})

function riskLevel(value: number) {
  return value >= 70 ? '高' : value >= 35 ? '中' : '低'
}

const riskSignals = computed(() => {
  const risk = selectedAnalysis.value?.risk
  if (!risk) {
    return [
      { label: '过热风险', value: 0, level: '--', reason: '该帧风险原料缺失' },
      { label: '资金背离风险', value: 0, level: '--', reason: '该帧风险原料缺失' },
    ]
  }
  const overheat = percent(risk?.overheat?.severity)
  const divergence = percent(risk?.divergence?.severity)
  return [
    { label: '过热风险', value: overheat, level: riskLevel(overheat), reason: `压力 ${percent(risk?.pressure)}% · 协同 ${percent(risk?.synergy)}%` },
    { label: '资金背离风险', value: divergence, level: riskLevel(divergence), reason: `背离严重度 ${divergence}%` },
  ]
})
</script>

<style scoped>
.observation-layer {
  position: fixed;
  inset: 0;
  z-index: 12100;
  pointer-events: none;
}

.observation-drawer {
  --cockpit-bg: #101416;
  --cockpit-panel: #171c1f;
  --cockpit-line: rgba(214, 223, 226, 0.13);
  --cockpit-muted: #879195;
  --cockpit-text: #e7ecee;
  --up: #ff5b62;
  --down: #38c98b;
  --gold: #e7bd4d;
  position: absolute;
  top: 0;
  right: 0;
  width: min(720px, 46vw);
  min-width: 560px;
  height: 100vh;
  color: var(--cockpit-text);
  background: var(--cockpit-bg);
  border-left: 1px solid rgba(231, 189, 77, 0.32);
  box-shadow: -24px 0 60px rgba(0, 0, 0, 0.46);
  pointer-events: auto;
  overflow: hidden;
  font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}

.cockpit-header {
  height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--cockpit-line);
  background: #13191b;
}

.eyebrow,
.section-kicker {
  color: var(--cockpit-muted);
  font: 10px/1.2 Consolas, monospace;
  letter-spacing: 0;
}

.stock-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 5px;
}

.stock-title strong {
  font-size: 20px;
  font-weight: 700;
}

.stock-title span {
  color: #aeb8bb;
  font: 13px Consolas, monospace;
}

.icon-button {
  width: 34px;
  height: 34px;
  border: 1px solid var(--cockpit-line);
  border-radius: 4px;
  color: #dce2e4;
  background: transparent;
  font-size: 22px;
  cursor: pointer;
}

.icon-button:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.05);
}

.summary-strip {
  height: 58px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-bottom: 1px solid var(--cockpit-line);
}

.summary-strip>div {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-right: 1px solid var(--cockpit-line);
}

.summary-strip>div:last-child {
  border-right: 0;
}

.summary-strip span {
  color: var(--cockpit-muted);
  font-size: 11px;
}

.summary-strip strong {
  font: 700 14px Consolas, "Microsoft YaHei UI", sans-serif;
}

.track-switcher {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  height: 48px;
  border-bottom: 1px solid var(--cockpit-line);
}

.track-switcher button {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-right: 1px solid var(--cockpit-line);
  color: #98a2a6;
  background: #111719;
  cursor: pointer;
}

.track-switcher button::after {
  content: '';
  position: absolute;
  left: 18%;
  right: 18%;
  bottom: 0;
  height: 2px;
  background: transparent;
}

.track-switcher button.active {
  color: #f1f4f5;
  background: #192023;
}

.track-switcher button.active::after {
  background: var(--gold);
}

.track-index {
  color: #667174;
  font: 10px Consolas, monospace;
}

.cockpit-body {
  height: calc(100vh - 182px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #3a4447 transparent;
}

.track-section {
  padding: 22px 24px 18px;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 18px;
}

.section-heading h2 {
  margin: 3px 0 0;
  font-size: 18px;
  letter-spacing: 0;
}

.section-score {
  font: 700 28px Consolas, monospace;
}

.section-score small {
  color: var(--cockpit-muted);
  font-size: 11px;
  font-weight: 400;
}

.direction-up {
  color: var(--up) !important;
}

.direction-down {
  color: var(--down) !important;
}

.direction-hold,
.stage-unknown {
  color: #a5afb2 !important;
}

.stage-ignition {
  color: var(--gold) !important;
}

.stage-expansion {
  color: var(--up) !important;
}

.stage-crowded {
  color: #ff9f43 !important;
}

.stage-reversal {
  color: var(--down) !important;
}

.stage-cooling {
  color: #8f999c !important;
}

.chart-shell {
  padding: 14px 0 8px;
  border-top: 1px solid var(--cockpit-line);
  border-bottom: 1px solid var(--cockpit-line);
}

.chart-legend {
  display: flex;
  gap: 18px;
  margin-bottom: 10px;
  color: #9ca6aa;
  font-size: 10px;
}

.chart-legend span {
  display: flex;
  align-items: center;
  gap: 5px;
}

.legend-line {
  width: 16px;
  height: 2px;
  display: inline-block;
}

.stock-line {
  background: #eef3f4;
}

.market-line {
  border-top: 2px dashed #e7bd4d;
}

.dif-line {
  background: #58b8d8;
}

.dea-line {
  background: #e7bd4d;
}

.path-chart {
  width: 100%;
  height: 190px;
  overflow: visible;
}

.grid-line {
  stroke: rgba(255, 255, 255, 0.08);
  stroke-width: 1;
}

.zero-line {
  stroke: rgba(255, 255, 255, 0.2);
  stroke-width: 1;
}

.stock-path,
.market-path,
.dif-path,
.dea-path {
  fill: none;
  vector-effect: non-scaling-stroke;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.stock-path {
  stroke: #eef3f4;
  stroke-width: 2.4;
}

.market-path {
  stroke: var(--gold);
  stroke-width: 1.5;
  stroke-dasharray: 5 5;
  opacity: 0.75;
}

.dif-path {
  stroke: #58b8d8;
  stroke-width: 2;
}

.dea-path {
  stroke: var(--gold);
  stroke-width: 1.8;
}

.jump-dot {
  fill: var(--up);
  stroke: #fff;
  stroke-width: 1.5;
}

.jump-label {
  fill: #ff9ca1;
  font: 8px Consolas, monospace;
}

.macd-positive {
  fill: rgba(255, 91, 98, 0.62);
}

.macd-negative {
  fill: rgba(56, 201, 139, 0.62);
}

.factor-stack {
  margin-top: 18px;
  display: grid;
  gap: 11px;
}

.factor-row {
  display: grid;
  grid-template-columns: 104px 1fr 52px;
  align-items: center;
  gap: 12px;
  font-size: 11px;
}

.factor-row>span {
  color: #aeb7ba;
}

.factor-row strong {
  text-align: right;
  font: 700 11px Consolas, monospace;
}

.factor-meter,
.risk-meter {
  height: 5px;
  overflow: hidden;
  background: #283033;
}

.factor-meter i,
.risk-meter i {
  display: block;
  height: 100%;
  background: #859195;
}

.factor-meter .positive-tone {
  background: var(--up);
}

.factor-meter .negative-tone {
  background: var(--down);
}

.factor-meter .jump-tone {
  background: var(--gold);
}

.factor-meter .lifecycle-tone {
  background: #58b8d8;
}

.evidence-note {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--cockpit-line);
  color: #909a9d;
  font-size: 11px;
}

.evidence-note strong {
  color: #edf1f2;
  font-family: Consolas, monospace;
}

.evidence-note span {
  margin-left: auto;
}

.signal-matrix {
  margin-top: 18px;
}

.signal-row {
  display: grid;
  grid-template-columns: 104px 42px 1fr 42px;
  gap: 10px;
  align-items: center;
  min-height: 42px;
  border-bottom: 1px solid var(--cockpit-line);
  font-size: 11px;
}

.signal-row>span {
  color: #aeb7ba;
}

.signal-row strong {
  font-size: 11px;
}

.signal-row b {
  text-align: right;
  font: 700 11px Consolas, monospace;
}

.bipolar-meter {
  position: relative;
  height: 6px;
  background: #283033;
}

.bipolar-meter i {
  position: absolute;
  top: 0;
  bottom: 0;
}

.bipolar-meter .meter-zero {
  left: 50%;
  width: 1px;
  top: -3px;
  bottom: -3px;
  background: #7c878a;
}

.bipolar-meter .positive {
  background: var(--up);
}

.bipolar-meter .negative {
  background: var(--down);
}

.stage-rail {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 3px;
  padding: 18px 0;
  border-top: 1px solid var(--cockpit-line);
  border-bottom: 1px solid var(--cockpit-line);
}

.stage-rail>div {
  min-width: 0;
  text-align: center;
}

.stage-rail i {
  display: block;
  height: 8px;
  margin-bottom: 7px;
  background: currentColor;
  opacity: 0.78;
}

.stage-rail span {
  display: block;
  overflow: hidden;
  color: currentColor;
  font-size: 9px;
  white-space: nowrap;
}

.risk-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--cockpit-line);
}

.risk-row>div:first-child {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}

.risk-row>div:first-child span {
  color: #aeb7ba;
}

.risk-row>div:first-child strong {
  color: #e9edef;
}

.risk-meter {
  margin-top: 9px;
  height: 7px;
}

.risk-meter i {
  background: #ff9f43;
}

.risk-row p {
  margin: 8px 0 0;
  color: #7f8a8e;
  font-size: 10px;
}

.veto-alert {
  display: flex;
  gap: 10px;
  margin-top: 18px;
  padding: 11px 12px;
  border-left: 2px solid var(--up);
  background: rgba(255, 91, 98, 0.08);
  font-size: 11px;
}

.veto-alert strong {
  color: #ff8e93;
  white-space: nowrap;
}

.veto-alert span {
  color: #c2c9cb;
}

.quality-banner {
  display: grid;
  gap: 3px;
  margin: 16px 24px 0;
  padding: 10px 12px;
  border-left: 2px solid var(--gold);
  background: rgba(231, 189, 77, 0.07);
  font-size: 10px;
}

.quality-banner strong {
  color: var(--gold);
}

.quality-banner span {
  color: #aeb7ba;
}

.panel-state {
  min-height: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #9ca6aa;
  font-size: 12px;
}

.loading-mark {
  width: 22px;
  height: 22px;
  border: 2px solid #364144;
  border-top-color: var(--gold);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.error-state strong {
  color: #ff8e93;
}

.frame-timeline {
  padding: 18px 24px 26px;
  border-top: 1px solid var(--cockpit-line);
  background: #0e1315;
}

.timeline-heading {
  display: flex;
  justify-content: space-between;
  margin-bottom: 15px;
}

.timeline-heading strong {
  font-size: 12px;
}

.timeline-heading span {
  color: #798487;
  font-size: 10px;
}

.timeline-buttons {
  display: grid;
  grid-template-columns: repeat(9, minmax(0, 1fr));
  gap: 4px;
}

.timeline-buttons button {
  min-width: 0;
  padding: 0;
  border: 0;
  color: #788386;
  background: transparent;
  cursor: pointer;
}

.timeline-buttons button i {
  display: block;
  width: 7px;
  height: 7px;
  margin: 0 auto 7px;
  border: 1px solid currentColor;
  border-radius: 50%;
  background: #0e1315;
}

.timeline-buttons button span {
  display: block;
  overflow: hidden;
  font: 9px/1.3 Consolas, monospace;
  white-space: normal;
}

.timeline-buttons button.active {
  color: var(--gold);
}

.timeline-buttons button.active i {
  background: var(--gold);
  box-shadow: 0 0 0 3px rgba(231, 189, 77, 0.15);
}

.timeline-buttons button.degraded:not(.active) {
  color: #c68d55;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1220px) {
  .observation-drawer {
    width: min(720px, 72vw);
    min-width: 520px;
  }
}

@media (max-width: 720px) {
  .observation-drawer {
    width: 96vw;
    min-width: 0;
  }

  .cockpit-header,
  .track-section,
  .frame-timeline {
    padding-left: 16px;
    padding-right: 16px;
  }

  .summary-strip span {
    display: none;
  }

  .factor-row {
    grid-template-columns: 88px 1fr 46px;
  }

  .risk-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .timeline-buttons button span {
    font-size: 8px;
  }
}
</style>
