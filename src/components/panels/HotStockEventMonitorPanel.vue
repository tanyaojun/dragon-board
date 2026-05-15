<template>
  <div v-if="visible" ref="panelRef" class="event-panel" :style="panelStyle">
    <div class="event-header">
      <div>
        <h3>🔔 异动提醒</h3>
        <p>选股通数据源 | 热榜个股异动监控</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" @click="close">✕</button>
    </div>

    <div class="search-box">
      <span class="search-icon">⌕</span>
      <input v-model="keyword" type="text" placeholder="代码/名称/拼音首字母" />
    </div>

    <div class="mode-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <span>{{ tab.icon }}</span>{{ tab.label }}
      </button>
    </div>

    <div class="filter-bar">
      <button class="filter-toggle" type="button" @click="showFilters = !showFilters">
        <span>⚑筛选设置</span>
        <span class="filter-action">⚙设置</span>
      </button>
    </div>

    <div v-if="showFilters" class="filter-panel">
      <div class="filter-title">
        <span>异动类型筛选</span>
        <button type="button" @click="showFilters = false">×</button>
      </div>
      <div class="filter-actions">
        <button type="button" @click="setAllTypes(true)">全选</button>
        <button type="button" @click="invertTypes">反选</button>
        <button type="button" @click="setAllTypes(false)">清空</button>
      </div>
      <div class="type-grid">
        <label v-for="item in eventTypeOptions" :key="item.type">
          <input v-model="enabledTypes" type="checkbox" :value="item.type" />
          <span>{{ item.name }}</span>
        </label>
      </div>
    </div>

    <div class="speech-row">
      <span>语音提醒</span>
      <label class="speech-toggle">
        <input v-model="speechEnabled" type="checkbox" :disabled="!speechSupported" />
        <span>{{ speechEnabled ? '开' : '关' }}</span>
      </label>
      <span v-if="!speechSupported" class="speech-disabled">不可用</span>
    </div>

    <div class="section-title">
      <span>⚠实时异动提醒</span>
      <span class="count-badge">{{ filteredEvents.length }}</span>
    </div>

    <div class="event-list">
      <div v-if="state.loading && !state.events.length" class="empty-state">正在加载选股通数据...</div>
      <div v-else-if="state.error && !state.events.length" class="empty-state error">
        {{ state.error }}
        <button type="button" @click="refresh">重试</button>
      </div>
      <div v-else-if="!filteredEvents.length" class="empty-state">暂无热榜个股异动</div>

      <button
        v-for="event in filteredEvents"
        :key="event.id"
        class="event-card"
        type="button"
        :class="[event.direction, { candidate: event.matchedCandidate }]"
        @click="selectStock(event)"
      >
        <div class="event-time-row">
          <span>{{ formatEventTime(event.timestamp) }}</span>
          <span class="event-badge" :class="event.direction">{{ event.typeName }}</span>
        </div>
        <div class="stock-row">
          <div class="stock-name-code">
            <span class="stock-name">{{ event.name || '--' }}</span>
            <span class="stock-code">{{ event.code }}</span>
            <span v-if="event.matchedCandidate" class="candidate-badge">候选</span>
          </div>
          <span class="change" :class="event.direction">{{ formatPct(event.changePct) }}</span>
        </div>
        <div v-if="event.relatedPlates.length" class="related-plates">
          <span class="related-title">相关板块</span>
          <span v-for="plate in event.relatedPlates.slice(0, 4)" :key="plate" class="plate-chip">
            {{ plate }}
          </span>
          <span v-if="event.relatedPlates.length > 4" class="plate-chip more">
            +{{ event.relatedPlates.length - 4 }}
          </span>
        </div>
      </button>
    </div>

    <div class="event-footer">
      <span>监控 {{ state.watchedCodes.length }} 只热榜股</span>
      <button class="refresh-btn" type="button" :disabled="state.loading" @click="refresh">
        {{ state.loading ? '刷新中' : '刷新' }}
      </button>
      <button class="refresh-btn" type="button" :disabled="!speechSupported" @click="testSpeech">
        语音测试
      </button>
      <span>{{ state.lastUpdate ? formatEventTime(state.lastUpdate) : '未更新' }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { usePanel } from '../../composables/usePanel'
import {
  hotStockEventMonitorService,
} from '../../services/hotlist/HotStockEventMonitorService'
import { hotStockEventSpeechService } from '../../services/hotlist/HotStockEventSpeechService'
import {
  type HotStockAbnormalEvent,
  type HotStockAbnormalEventType,
  type HotStockEventMonitorState,
} from '../../services/hotlist/hotStockEventTypes'
import { XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES } from '../../services/hotlist/XuangubaoAbnormalEventFeed'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'select-stock', code: string): void
}>()

const EVENT_TYPE_NAMES: Record<HotStockAbnormalEventType, string> = {
  10001: '封涨停板',
  10005: '逼近涨停',
  10003: '打开涨停板',
  10007: '即将打开涨停',
  10002: '封跌停板',
  10006: '逼近跌停',
  10004: '打开跌停板',
  10008: '即将打开跌停',
  10012: '新股开板',
  10014: '新股开板回封',
  10009: '大幅拉升',
  10010: '快速跳水',
}

const tabs = [
  { id: 'all', label: '全部', icon: '☷' },
  { id: 'up', label: '上涨', icon: '⌁' },
  { id: 'candidate', label: '候选', icon: '◆' },
] as const

const blankState: HotStockEventMonitorState = {
  events: [],
  latestAdded: [],
  watchedCodes: [],
  lastUpdate: null,
  loading: false,
  running: false,
  error: null,
}

const activeTab = ref<(typeof tabs)[number]['id']>('all')
const keyword = ref('')
const showFilters = ref(false)
const state = ref<HotStockEventMonitorState>(blankState)
const enabledTypes = ref<HotStockAbnormalEventType[]>([...XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES])
const speechSupported = ref(hotStockEventSpeechService.isSupported())
const speechEnabled = ref(speechSupported.value)

const close = () => {
  emit('update:visible', false)
  emit('close')
}

const { panelRef, panelStyle } = usePanel({
  name: 'HotStockEventMonitorPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="异动监控"]'],
  onClose: close,
})

const eventTypeOptions = computed(() =>
  XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES.map((type) => ({
    type,
    name: EVENT_TYPE_NAMES[type],
  })),
)

const filteredEvents = computed(() => {
  const text = keyword.value.trim().toUpperCase()
  const enabled = new Set(enabledTypes.value)
  return state.value.events.filter((event) => {
    if (!enabled.has(event.type)) return false
    if (activeTab.value === 'up' && event.direction !== 'up') return false
    if (activeTab.value === 'candidate' && !event.matchedCandidate) return false
    if (!text) return true
    return `${event.code}${event.name}${event.relatedPlates.join('')}`.toUpperCase().includes(text)
  })
})

function setAllTypes(checked: boolean) {
  enabledTypes.value = checked ? [...XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES] : []
}

function invertTypes() {
  const enabled = new Set(enabledTypes.value)
  enabledTypes.value = XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES.filter((type) => !enabled.has(type))
}

function formatEventTime(timestamp: number) {
  if (!timestamp) return '--:--:--'
  return new Date(timestamp).toLocaleTimeString('zh-CN', { hour12: false })
}

function formatPct(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

async function refresh() {
  await hotStockEventMonitorService.refresh()
}

function selectStock(event: HotStockAbnormalEvent) {
  emit('select-stock', event.code)
}

function testSpeech() {
  hotStockEventSpeechService.speakTest()
}

let unsubscribe: (() => void) | null = null

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      if (!unsubscribe) {
        unsubscribe = hotStockEventMonitorService.subscribe((nextState) => {
          state.value = nextState
          if (speechEnabled.value) {
            hotStockEventSpeechService.handleLatestAdded(nextState.latestAdded)
          }
        })
      }
      void hotStockEventMonitorService.refresh()
      hotStockEventMonitorService.start()
      return
    }

    unsubscribe?.()
    unsubscribe = null
    hotStockEventMonitorService.stop()
    hotStockEventSpeechService.stop()
  },
  { immediate: true },
)

watch(speechEnabled, (enabled) => {
  hotStockEventSpeechService.setEnabled(enabled)
})

onUnmounted(() => {
  unsubscribe?.()
  hotStockEventMonitorService.stop()
  hotStockEventSpeechService.stop()
})
</script>

<style scoped>
.event-panel {
  position: fixed;
  width: 360px;
  max-width: calc(100vw - 20px);
  max-height: 86vh;
  overflow: hidden;
  z-index: 10005;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #141212;
  color: var(--text-primary);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  font-size: 12px;
  display: flex;
  flex-direction: column;
}

.event-header {
  padding: 12px 10px 8px;
  text-align: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  position: relative;
}

.event-header h3 {
  margin: 0 20px 4px;
  color: #d4a574;
  font-size: 16px;
}

.event-header p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 11px;
}

.icon-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.search-box {
  margin: 10px;
  height: 32px;
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #333;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
  padding: 0 8px;
}

.search-icon {
  color: #4dabf7;
  font-size: 16px;
}

.search-box input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
}

.mode-tabs,
.filter-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 0 10px 8px;
}

.mode-tabs button,
.filter-actions button {
  height: 30px;
  border: 1px solid #333;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
}

.mode-tabs button.active {
  border-color: #4dabf7;
  color: #4dabf7;
  background: rgba(77, 171, 247, 0.08);
}

.filter-bar {
  padding: 0 10px 6px;
}

.filter-toggle {
  width: 100%;
  border: none;
  background: transparent;
  color: #d4a574;
  display: flex;
  justify-content: space-between;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}

.filter-action {
  color: var(--text-primary);
  border: 1px solid #333;
  border-radius: 4px;
  padding: 2px 6px;
}

.filter-panel {
  margin: 0 10px 10px;
  border: 1px solid #333;
  border-radius: 6px;
  background: rgba(30, 28, 28, 0.92);
  padding: 10px;
}

.filter-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #d4a574;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-weight: 600;
}

.filter-title button {
  border: none;
  background: transparent;
  color: #7aa7d9;
  cursor: pointer;
  font-size: 18px;
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
}

.type-grid label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-primary);
}

.speech-row {
  margin: 0 10px 8px;
  padding: 7px 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  color: #d4a574;
}

.speech-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-primary);
}

.speech-disabled {
  color: #ff7f50;
  font-size: 11px;
}

.section-title {
  padding: 0 10px 8px;
  color: #d4a574;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.count-badge {
  background: #1c6fb8;
  color: #fff;
  border-radius: 2px;
  padding: 1px 5px;
  font-size: 11px;
}

.event-list {
  overflow-y: auto;
  padding: 0 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-state {
  padding: 16px 8px;
  color: var(--text-secondary);
  text-align: center;
}

.empty-state.error {
  color: #ff7f50;
}

.event-card {
  width: 100%;
  text-align: left;
  border: none;
  border-left: 3px solid #4dabf7;
  border-radius: 6px;
  background: rgba(30, 28, 28, 0.92);
  color: var(--text-primary);
  padding: 8px 8px 10px;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.2s;
}

.event-card:hover {
  transform: translateY(-1px);
  border-left-color: #d4a574;
}

.event-card.down {
  border-left-color: #2ed573;
}

.event-card.candidate {
  box-shadow: inset 0 0 0 1px rgba(212, 165, 116, 0.18);
}

.event-time-row,
.stock-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.event-time-row {
  color: #9fb3c8;
  margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}

.event-badge {
  border-radius: 10px;
  padding: 2px 7px;
  background: rgba(255, 183, 3, 0.12);
  color: #ffb703;
  border: 1px solid rgba(255, 183, 3, 0.35);
}

.event-badge.down {
  background: rgba(46, 213, 115, 0.1);
  color: #2ed573;
  border-color: rgba(46, 213, 115, 0.28);
}

.stock-row {
  background: #1f2b35;
  padding: 6px;
  margin: 0 -2px;
}

.stock-name-code {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.stock-name {
  font-weight: 600;
  color: #fff;
}

.stock-code,
.candidate-badge {
  color: #ffd43b;
  font-size: 11px;
}

.candidate-badge {
  color: #4dabf7;
}

.change {
  color: #ff4757;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.change.down {
  color: #2ed573;
}

.related-plates {
  background: rgba(255, 213, 79, 0.08);
  color: #ffd43b;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px;
}

.related-title {
  width: 100%;
  color: #ffd43b;
  font-weight: 600;
}

.plate-chip {
  color: #ffd43b;
}

.plate-chip:nth-child(odd) {
  color: #2ed573;
}

.plate-chip.more {
  color: #d4a574;
}

.event-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 11px;
}

.refresh-btn {
  border: 1px solid #333;
  border-radius: 4px;
  background: rgba(77, 171, 247, 0.08);
  color: #4dabf7;
  cursor: pointer;
  padding: 3px 8px;
}
</style>
