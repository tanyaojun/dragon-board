<template>
  <div v-if="visible" ref="panelRef" class="event-panel" :style="panelStyle">
    <div class="event-header">
      <div class="event-title">
        <div class="title-row">
          <span class="title-mark" aria-hidden="true"></span>
          <h3>异动雷达</h3>
        </div>
        <p>选股通数据源 · 盘中异动线索雷达</p>
      </div>
      <button class="icon-btn" type="button" title="关闭" aria-label="关闭异动雷达" @click="close">
        ×
      </button>
    </div>

    <div class="page-tabs" role="tablist" aria-label="异动雷达分类">
      <button
        v-for="page in pages"
        :key="page.id"
        type="button"
        class="page-tab"
        :class="{ active: activePage === page.id }"
        :aria-pressed="activePage === page.id"
        @click="activePage = page.id"
      >
        <span class="tab-icon" aria-hidden="true">{{ page.icon }}</span>
        <span>{{ page.label }}</span>
      </button>
    </div>

    <template v-if="activePage !== 'settings'">
      <div class="section-title">
        <span class="section-name">{{ activePageTitle }}</span>
        <span class="count-badge">{{ filteredEvents.length }}</span>
      </div>

      <div v-if="showEventSearch" class="event-search-bar">
        <label class="search-box">
          <span class="search-icon" aria-hidden="true">⌕</span>
          <input
            v-model="keyword"
            type="text"
            placeholder="代码/名称/板块/拼音首字母"
            aria-label="搜索异动个股"
          />
        </label>
      </div>

      <div class="event-list">
        <div v-if="state.loading && !state.events.length" class="empty-state">正在加载选股通数据...</div>
        <div v-else-if="state.error && !state.events.length" class="empty-state error">
          {{ state.error }}
          <button type="button" @click="refresh">重试</button>
        </div>
        <div v-else-if="!filteredEvents.length" class="empty-state">{{ emptyText }}</div>

        <article
          v-for="event in filteredEvents"
          :key="event.id"
          class="event-card"
          role="button"
          tabindex="0"
          :class="[
            event.direction,
            {
              candidate: event.matchedCandidate,
              'pool-candidate': Boolean(candidatePoolEntry(event)),
              sector: event.category === 'sector',
            },
          ]"
          @click="selectStock(event)"
          @keydown.enter.prevent="selectStock(event)"
          @keydown.space.prevent="selectStock(event)"
        >
          <div class="event-time-row">
            <span>{{ formatEventTime(event.timestamp) }}</span>
            <span class="event-badge" :class="event.direction">{{ event.typeName }}</span>
          </div>
          <div class="stock-row">
            <div class="stock-name-code">
              <span class="stock-name">{{ displayName(event) }}</span>
              <span v-if="event.code" class="stock-code">{{ event.code }}</span>
              <span v-if="event.matchedCandidate" class="candidate-badge dragon">龙头复盘</span>
              <span v-if="candidatePoolEntry(event)" class="candidate-badge pool">已入候选池</span>
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
          <div v-if="event.category === 'stock' && event.code" class="candidate-pool-actions">
            <button
              class="candidate-action-btn"
              type="button"
              :disabled="candidateActionLoadingCode === normalizeHotStockCode(event.code)"
              @click.stop="handleCandidatePoolAction(event)"
            >
              {{ candidateActionLabel(event) }}
            </button>
          </div>
        </article>
      </div>
    </template>

    <div v-else class="settings-page">
      <div class="filter-panel">
        <div class="filter-title">
          <div>
            <span class="card-kicker">筛选规则</span>
            <strong>异动类型</strong>
          </div>
          <span class="filter-summary">已启用 {{ enabledTypes.length }}/{{ ALL_EVENT_TYPES.length }}</span>
        </div>
        <div class="filter-actions" aria-label="异动类型批量操作">
          <button type="button" @click="setAllTypes(true)">全选</button>
          <button type="button" @click="invertTypes">反选</button>
          <button type="button" @click="setAllTypes(false)">清空</button>
        </div>
        <div class="type-grid">
          <label v-for="item in eventTypeOptions" :key="item.type" class="filter-chip">
            <input v-model="enabledTypes" type="checkbox" :value="item.type" />
            <span>{{ item.name }}</span>
          </label>
        </div>
      </div>

      <div class="settings-card">
        <div class="speech-row">
          <div>
            <span class="card-kicker">播报设置</span>
            <strong class="speech-card-title">语音提醒</strong>
          </div>
          <span class="speech-mode">{{ speechModeLabel }}</span>
          <label class="speech-toggle">
            <input v-model="speechEnabled" type="checkbox" :disabled="!speechSupported" />
            <span>{{ speechEnabled ? '开' : '关' }}</span>
          </label>
          <span v-if="!speechSupported" class="speech-disabled">不可用</span>
        </div>
        <label class="range-row">
          <span>
            <span>语速</span>
            <strong>{{ speechRate.toFixed(1) }}x</strong>
          </span>
          <input v-model.number="speechRate" type="range" min="0.6" max="1.8" step="0.1" />
        </label>
        <label class="range-row">
          <span>
            <span>音量</span>
            <strong>{{ speechVolume }}</strong>
          </span>
          <input v-model.number="speechVolume" type="range" min="0" max="100" step="5" />
        </label>
        <label v-if="showSpeechVoiceSelect" class="select-row">
          <span>本地语音</span>
          <select v-model="speechVoice" :disabled="!speechVoices.length">
            <option value="">系统默认</option>
            <option v-for="voice in speechVoices" :key="voice.name" :value="voice.name">
              {{ formatVoiceLabel(voice) }}
            </option>
            <option v-if="!speechVoices.length" value="" disabled>未检测到系统语音</option>
          </select>
        </label>
      </div>

      <div v-if="state.error" class="empty-state error">
        {{ state.error }}
        <button type="button" @click="refresh">重试</button>
      </div>
    </div>

    <div class="event-footer">
      <div class="footer-status">
        <span>监控 {{ state.watchedCodes.length }} 只热榜股</span>
        <span>{{ state.lastUpdate ? formatEventTime(state.lastUpdate) : '未更新' }}</span>
      </div>
      <div class="footer-actions">
        <button class="refresh-btn" type="button" :disabled="state.loading" @click="refresh">
          {{ state.loading ? '刷新中' : '刷新' }}
        </button>
        <button class="refresh-btn" type="button" :disabled="!speechSupported" @click="testSpeech">
          语音测试
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type { CandidateJournalEntry, CandidateStockLike, CandidateStatus } from '@/services/candidate/types'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { usePanel } from '../../composables/usePanel'
import {
  hotStockEventMonitorService,
} from '../../services/hotlist/HotStockEventMonitorService'
import {
  hotStockEventSpeechService,
  resolveSpeechVoiceSelection,
} from '../../services/hotlist/HotStockEventSpeechService'
import {
  type HotStockAbnormalEvent,
  type HotStockAbnormalEventType,
  type HotStockEventMonitorState,
  normalizeHotStockCode,
} from '../../services/hotlist/hotStockEventTypes'
import {
  XUANGUBAO_SECTOR_ABNORMAL_EVENT_TYPES,
  XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES,
} from '../../services/hotlist/XuangubaoAbnormalEventFeed'

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
  11000: '板块拉升',
  11001: '板块跳水',
}

const pages = [
  { id: 'hot', label: '热榜个股', icon: '☷' },
  { id: 'other', label: '其他个股', icon: '⌁' },
  { id: 'sector', label: '板块', icon: '◆' },
  { id: 'settings', label: '设置', icon: '⚙' },
] as const
const ALL_EVENT_TYPES = [
  ...XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES,
  ...XUANGUBAO_SECTOR_ABNORMAL_EVENT_TYPES,
]
const OPEN_CANDIDATE_STATUSES = new Set<CandidateStatus>([
  'observe',
  'candidate',
  'triggered',
  'tracking',
])

const blankState: HotStockEventMonitorState = {
  events: [],
  hotStockEvents: [],
  otherStockEvents: [],
  sectorEvents: [],
  latestAdded: [],
  latestHotStockAdded: [],
  watchedCodes: [],
  lastUpdate: null,
  loading: false,
  running: false,
  error: null,
}

const activePage = ref<(typeof pages)[number]['id']>('hot')
const keyword = ref('')
const state = ref<HotStockEventMonitorState>(blankState)
const enabledTypes = ref<HotStockAbnormalEventType[]>([...ALL_EVENT_TYPES])
const speechSupported = ref(hotStockEventSpeechService.isSupported())
const speechEnabled = ref(speechSupported.value)
const speechMode = ref(hotStockEventSpeechService.getStatus().mode)
const speechEngine = ref(hotStockEventSpeechService.getStatus().engine)
const speechVoices = ref(hotStockEventSpeechService.getStatus().voices || [])
const voiceOptions = hotStockEventSpeechService.getVoiceOptions()
const speechRate = ref(voiceOptions.rate)
const speechVolume = ref(voiceOptions.volume)
const speechVoice = ref(voiceOptions.voice || '')
const candidatePoolEntries = ref<Record<string, CandidateJournalEntry>>({})
const candidateActionLoadingCode = ref('')

const close = () => {
  emit('update:visible', false)
  emit('close')
}

const { panelRef, panelStyle } = usePanel({
  name: 'HotStockEventMonitorPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="异动雷达"]', '[title*="异动监控"]'],
  onClose: close,
})

const eventTypeOptions = computed(() =>
  ALL_EVENT_TYPES.map((type) => ({
    type,
    name: EVENT_TYPE_NAMES[type],
  })),
)

const pageEvents = computed(() => {
  if (activePage.value === 'other') return state.value.otherStockEvents
  if (activePage.value === 'sector') return state.value.sectorEvents
  return state.value.hotStockEvents
})

const showEventSearch = computed(() => activePage.value === 'hot' || activePage.value === 'other')

const filteredEvents = computed(() => {
  const text = showEventSearch.value ? keyword.value.trim().toUpperCase() : ''
  const enabled = new Set(enabledTypes.value)
  return pageEvents.value.filter((event) => {
    if (!enabled.has(event.type)) return false
    if (!text) return true
    return `${event.code}${event.name}${event.sectorName}${event.relatedPlates.join('')}`.toUpperCase().includes(text)
  })
})

const activePageTitle = computed(() => {
  if (activePage.value === 'other') return '其他个股异动'
  if (activePage.value === 'sector') return '板块异动'
  return '热榜个股异动'
})

const emptyText = computed(() => {
  if (activePage.value === 'other') return '暂无其他个股异动'
  if (activePage.value === 'sector') return '暂无板块异动'
  return '暂无热榜个股异动'
})

const speechModeLabel = computed(() => {
  if (speechMode.value === 'local' && speechEngine.value === 'volcengine') return '火山语音'
  if (speechMode.value === 'local') return '本地语音'
  return 'VoiceWorker 未连接'
})
const showSpeechVoiceSelect = computed(() => speechMode.value === 'local' && speechEngine.value !== 'volcengine')

function setAllTypes(checked: boolean) {
  enabledTypes.value = checked ? [...ALL_EVENT_TYPES] : []
}

function invertTypes() {
  const enabled = new Set(enabledTypes.value)
  enabledTypes.value = ALL_EVENT_TYPES.filter((type) => !enabled.has(type))
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
  await Promise.all([
    hotStockEventMonitorService.refresh(),
    loadCandidatePoolState(),
  ])
}

function selectStock(event: HotStockAbnormalEvent) {
  if (event.category === 'sector' || !event.code) return
  emit('select-stock', event.code)
}

function displayName(event: HotStockAbnormalEvent) {
  return event.category === 'sector' ? event.sectorName || event.name || '--' : event.name || '--'
}

function candidatePoolEntry(event: HotStockAbnormalEvent): CandidateJournalEntry | null {
  const code = normalizeHotStockCode(event.code)
  return code ? candidatePoolEntries.value[code] || null : null
}

function candidateActionLabel(event: HotStockAbnormalEvent) {
  const code = normalizeHotStockCode(event.code)
  if (candidateActionLoadingCode.value === code) return '处理中'
  return candidatePoolEntry(event) ? '查看候选' : '加入候选池'
}

function eventStock(event: HotStockAbnormalEvent): CandidateStockLike {
  const code = normalizeHotStockCode(event.code)
  return {
    code,
    name: event.name || code,
    price: event.price || 0,
    change: event.changePct === null ? undefined : event.changePct * 100,
    themes: event.relatedPlates.map((name) => ({ name, Name: name })),
    sourceEventType: event.typeName,
    sourceEventTimestamp: event.timestamp,
  }
}

async function loadCandidatePoolState() {
  try {
    const entries = await candidateJournalService.listCandidates({ limit: 200 })
    const next: Record<string, CandidateJournalEntry> = {}
    for (const entry of entries) {
      const code = normalizeHotStockCode(entry.stockCode)
      if (code && OPEN_CANDIDATE_STATUSES.has(entry.status)) {
        next[code] = entry
      }
    }
    candidatePoolEntries.value = next
  } catch {
    candidatePoolEntries.value = {}
  }
}

function openCandidatePool(stockCode: string, candidateId?: string) {
  EventManager.emit('candidate-pool:open', {
    stockCode,
    candidateId,
    source: 'hot-stock-event-radar',
  })
}

async function handleCandidatePoolAction(event: HotStockAbnormalEvent) {
  const stock = eventStock(event)
  if (!stock.code) return

  const existing = candidatePoolEntry(event)
  if (existing) {
    openCandidatePool(stock.code, existing.id)
    return
  }

  candidateActionLoadingCode.value = stock.code
  try {
    const result = await candidateJournalService.addCandidateFromStock(eventStock(event), {
      source: 'hot-stock-event-radar',
    })
    if (result.entry) {
      candidatePoolEntries.value = {
        ...candidatePoolEntries.value,
        [stock.code]: result.entry,
      }
    }
    openCandidatePool(stock.code, result.entry?.id)
  } catch (error) {
    EventManager.emit(AppEvents.UI.TOAST, {
      message: `加入候选池失败：${error instanceof Error ? error.message : '未知错误'}`,
      duration: 2000,
      type: 'error',
    })
  } finally {
    candidateActionLoadingCode.value = ''
  }
}

function formatVoiceLabel(voice: { name: string; culture?: string; gender?: string }) {
  const tags = [voice.culture, voice.gender].filter(Boolean).join(' / ')
  return tags ? `${voice.name} (${tags})` : voice.name
}

async function refreshSpeechStatus() {
  const status = await hotStockEventSpeechService.refreshStatus()
  speechMode.value = status.mode
  speechEngine.value = status.engine
  speechVoices.value = status.voices || []
  speechVoice.value = resolveSpeechVoiceSelection(speechVoice.value, status.voice, speechVoices.value) || ''
  speechSupported.value = status.supported
  if (status.supported && !speechEnabled.value) {
    speechEnabled.value = true
  }
}

async function testSpeech() {
  await hotStockEventSpeechService.speakTest()
  const status = hotStockEventSpeechService.getStatus()
  speechMode.value = status.mode
  speechEngine.value = status.engine
  speechVoices.value = status.voices || []
  speechSupported.value = status.supported
}

let unsubscribe: (() => void) | null = null

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      void refreshSpeechStatus()
      if (!unsubscribe) {
        unsubscribe = hotStockEventMonitorService.subscribe((nextState) => {
          state.value = nextState
          if (speechEnabled.value) {
            void hotStockEventSpeechService.handleLatestAdded(nextState.latestHotStockAdded)
          }
        })
      }
      void refresh()
      hotStockEventMonitorService.start()
      return
    }

    unsubscribe?.()
    unsubscribe = null
    candidatePoolEntries.value = {}
    hotStockEventMonitorService.stop()
    hotStockEventSpeechService.stop()
  },
  { immediate: true },
)

watch(speechEnabled, (enabled) => {
  hotStockEventSpeechService.setEnabled(enabled)
})

watch([speechRate, speechVolume, speechVoice], ([rate, volume, voice]) => {
  hotStockEventSpeechService.setVoiceOptions({ rate, volume, voice })
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
  width: 372px;
  max-width: calc(100vw - 20px);
  max-height: 86vh;
  overflow: hidden;
  z-index: 10005;
  border: 1px solid rgba(215, 178, 117, 0.2);
  border-radius: 8px;
  background: linear-gradient(180deg, #191514 0%, #111315 54%, #0e1113 100%);
  color: var(--text-primary);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  font-size: 12px;
  display: flex;
  flex-direction: column;
  font-variant-numeric: tabular-nums;
}

.event-header {
  padding: 14px 42px 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  position: relative;
  background: linear-gradient(135deg, rgba(212, 165, 116, 0.11), rgba(77, 171, 247, 0.05) 64%);
}

.event-title {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.title-mark {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f6b45f;
  box-shadow: 0 0 14px rgba(246, 180, 95, 0.8);
}

.event-header h3 {
  margin: 0;
  color: #f1bd7a;
  font-size: 16px;
  line-height: 20px;
  letter-spacing: 0;
}

.event-header p {
  margin: 4px 0 0;
  color: #9ba8b5;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}

.icon-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
  color: #9ba8b5;
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
}

.icon-btn:hover,
.icon-btn:focus-visible {
  border-color: rgba(246, 180, 95, 0.55);
  color: #f1bd7a;
  outline: none;
}

.event-search-bar {
  padding: 10px 12px 8px;
}

.search-box {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(121, 151, 176, 0.24);
  border-radius: 6px;
  background: rgba(7, 10, 12, 0.48);
  padding: 0 10px;
  box-shadow: inset 0 1px 8px rgba(0, 0, 0, 0.24);
}

.search-icon {
  color: #4dabf7;
  font-size: 16px;
  line-height: 1;
}

.search-box input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: #edf3f8;
  font-size: 12px;
  line-height: 18px;
}

.search-box input::placeholder {
  color: #6e7c88;
}

.page-tabs {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding: 10px 12px 9px;
  background: rgba(0, 0, 0, 0.08);
}

.page-tab {
  min-width: 0;
  min-height: 32px;
  border: 1px solid rgba(121, 151, 176, 0.24);
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.035);
  color: #c7d0da;
  cursor: pointer;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.page-tab:hover,
.page-tab:focus-visible {
  border-color: rgba(77, 171, 247, 0.48);
  color: #edf3f8;
  outline: none;
}

.page-tabs button.active {
  border-color: rgba(77, 171, 247, 0.75);
  color: #7dc6ff;
  background: linear-gradient(180deg, rgba(77, 171, 247, 0.16), rgba(77, 171, 247, 0.05));
  box-shadow: inset 0 0 0 1px rgba(77, 171, 247, 0.08);
}

.tab-icon {
  color: #f1bd7a;
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
  margin: 0 12px 10px;
  border: 1px solid rgba(121, 151, 176, 0.2);
  border-radius: 8px;
  background: rgba(24, 24, 24, 0.76);
  padding: 11px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.settings-page {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.settings-card {
  margin: 0 12px 10px;
  border: 1px solid rgba(121, 151, 176, 0.2);
  border-radius: 8px;
  background: rgba(24, 24, 24, 0.76);
  padding: 11px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.filter-title {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  color: #f1bd7a;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 9px;
  margin-bottom: 9px;
  font-weight: 600;
}

.filter-title strong,
.speech-card-title {
  display: block;
  color: #edf3f8;
  font-size: 13px;
  line-height: 18px;
}

.card-kicker {
  display: block;
  color: #8b9aaa;
  font-size: 10px;
  font-weight: 500;
  line-height: 14px;
}

.filter-summary {
  flex: 0 0 auto;
  color: #7dc6ff;
  font-size: 11px;
  line-height: 18px;
}

.filter-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 7px;
  margin-bottom: 10px;
}

.filter-actions button {
  min-height: 30px;
  border: 1px solid rgba(121, 151, 176, 0.24);
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.035);
  color: #c7d0da;
  cursor: pointer;
  font-size: 12px;
}

.filter-actions button:hover,
.filter-actions button:focus-visible {
  border-color: rgba(246, 180, 95, 0.46);
  color: #f1bd7a;
  outline: none;
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.filter-chip {
  min-width: 0;
  min-height: 28px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #cbd5df;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.025);
  padding: 4px 7px;
  cursor: pointer;
}

.filter-chip input {
  width: 13px;
  height: 13px;
  margin: 0;
  accent-color: #7dc6ff;
}

.filter-chip span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.speech-row {
  margin: 0 0 8px;
  padding: 8px 9px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.035);
  color: #f1bd7a;
}

.range-row {
  display: grid;
  gap: 6px;
  color: #cbd5df;
  margin-top: 11px;
}

.range-row > span {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.range-row strong {
  color: #edf3f8;
  font-weight: 600;
}

.range-row input {
  width: 100%;
  accent-color: #7dc6ff;
}

.select-row {
  display: grid;
  gap: 6px;
  color: #cbd5df;
  margin-top: 10px;
}

.select-row select {
  width: 100%;
  min-width: 0;
  min-height: 34px;
  border: 1px solid rgba(121, 151, 176, 0.24);
  border-radius: 5px;
  background: #111416;
  color: #edf3f8;
  padding: 0 8px;
}

.speech-toggle {
  flex: 0 0 auto;
  min-height: 26px;
  display: flex;
  align-items: center;
  gap: 5px;
  color: #edf3f8;
}

.speech-mode {
  margin-left: auto;
  color: #7dc6ff;
  font-size: 11px;
  white-space: nowrap;
}

.speech-disabled {
  color: #ff7f50;
  font-size: 11px;
  white-space: nowrap;
}

.section-title {
  padding: 2px 12px 9px;
  color: #f1bd7a;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.section-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count-badge {
  flex: 0 0 auto;
  min-width: 24px;
  text-align: center;
  background: rgba(77, 171, 247, 0.18);
  color: #7dc6ff;
  border: 1px solid rgba(77, 171, 247, 0.28);
  border-radius: 999px;
  padding: 1px 6px;
  font-size: 11px;
}

.event-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  scrollbar-width: thin;
}

.empty-state {
  padding: 16px 8px;
  color: #9ba8b5;
  text-align: center;
}

.empty-state.error {
  color: #ff7f50;
}

.event-card {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-left: 3px solid #4dabf7;
  border-radius: 8px;
  background: rgba(24, 24, 24, 0.78);
  color: #edf3f8;
  padding: 8px 8px 10px;
  cursor: pointer;
  transition: border-color 0.16s ease, transform 0.16s ease, background 0.16s ease;
}

.event-card:hover,
.event-card:focus-visible {
  transform: translateY(-1px);
  border-left-color: #d4a574;
  outline: none;
}

.event-card.down {
  border-left-color: #2ed573;
}

.event-card.candidate {
  box-shadow: inset 0 0 0 1px rgba(212, 165, 116, 0.18);
}

.event-card.pool-candidate {
  box-shadow: inset 0 0 0 1px rgba(77, 171, 247, 0.24);
}

.event-card.sector {
  border-left-color: #d4a574;
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
  background: rgba(20, 31, 40, 0.82);
  border-radius: 5px;
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-code,
.candidate-badge {
  color: #ffd43b;
  font-size: 11px;
  white-space: nowrap;
}

.candidate-badge.dragon {
  color: #f1bd7a;
}

.candidate-badge.pool {
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
  margin-top: 7px;
  background: rgba(255, 213, 79, 0.07);
  border-radius: 5px;
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

.candidate-pool-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.candidate-action-btn {
  min-height: 26px;
  border: 1px solid rgba(77, 171, 247, 0.34);
  border-radius: 5px;
  background: rgba(77, 171, 247, 0.1);
  color: #7dc6ff;
  cursor: pointer;
  padding: 0 10px;
  font-size: 11px;
}

.candidate-action-btn:hover:not(:disabled),
.candidate-action-btn:focus-visible:not(:disabled) {
  border-color: rgba(246, 180, 95, 0.55);
  color: #f1bd7a;
  outline: none;
}

.candidate-action-btn:disabled {
  cursor: wait;
  opacity: 0.6;
}

.event-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 9px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #9ba8b5;
  font-size: 11px;
  background: rgba(0, 0, 0, 0.16);
}

.footer-status {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.footer-status span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.refresh-btn {
  min-height: 30px;
  border: 1px solid rgba(77, 171, 247, 0.36);
  border-radius: 5px;
  background: rgba(77, 171, 247, 0.09);
  color: #7dc6ff;
  cursor: pointer;
  padding: 0 10px;
}

.refresh-btn:hover:not(:disabled),
.refresh-btn:focus-visible:not(:disabled) {
  border-color: rgba(246, 180, 95, 0.5);
  color: #f1bd7a;
  outline: none;
}

.refresh-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 380px) {
  .event-panel {
    width: calc(100vw - 20px);
  }

  .page-tabs {
    gap: 4px;
    padding-right: 10px;
    padding-left: 10px;
  }

  .page-tab {
    font-size: 10px;
  }

  .type-grid {
    grid-template-columns: 1fr;
  }

  .event-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .footer-actions {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
