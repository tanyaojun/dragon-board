<template>
  <Teleport to="body">
    <div v-if="visible" class="candidate-mask" @click.self="close">
      <section class="candidate-panel">
        <header class="candidate-header">
          <div>
            <h2>候选池</h2>
            <p>规则分析驱动的候选股跟踪工作台</p>
          </div>
          <button class="icon-btn" title="关闭" @click="close">×</button>
        </header>

        <div class="candidate-toolbar">
          <select v-model="statusFilter" @change="loadCandidates">
            <option value="">全部状态</option>
            <option value="observe">观察</option>
            <option value="candidate">候选</option>
            <option value="triggered">触发</option>
            <option value="tracking">跟踪中</option>
            <option value="reviewed">已复盘</option>
          </select>
          <button class="text-btn" @click="loadCandidates">刷新</button>
          <span class="summary">共 {{ candidates.length }} 条</span>
        </div>

        <div v-if="errorMessage" class="error">{{ errorMessage }}</div>

        <div class="candidate-body">
          <aside class="candidate-list">
            <div v-if="loading" class="empty">加载中...</div>
            <div v-else-if="!candidates.length" class="empty">暂无候选股</div>
            <button
              v-for="entry in candidates"
              v-else
              :key="entry.id"
              class="candidate-item"
              :class="{ active: selectedId === entry.id }"
              @click="selectedId = entry.id"
            >
              <span class="stock-line">
                <strong>{{ entry.stockName || entry.stockCode }}</strong>
                <span>{{ entry.stockCode }}</span>
              </span>
              <span class="meta-line">
                <span>{{ statusLabel(entry.status) }}</span>
                <span>{{ analysisOf(entry).grade }}级 · {{ analysisOf(entry).score }}分</span>
              </span>
            </button>
          </aside>

          <main class="candidate-detail">
            <template v-if="selectedEntry">
              <div class="detail-title">
                <div>
                  <h3>{{ selectedEntry.stockName || selectedEntry.stockCode }}</h3>
                  <span>{{ selectedEntry.stockCode }} · {{ statusLabel(selectedEntry.status) }}</span>
                </div>
                <div class="status-actions">
                  <button
                    v-for="status in nextStatuses"
                    :key="status"
                    :disabled="updatingStatus"
                    @click="updateStatus(status)"
                  >
                    {{ statusLabel(status) }}
                  </button>
                </div>
              </div>

              <section class="analysis-card">
                <h4>规则分析</h4>
                <div class="score-row">
                  <strong>{{ analysisOf(selectedEntry).grade }}级</strong>
                  <span>{{ analysisOf(selectedEntry).score }}分</span>
                </div>
                <div class="breakdown">
                  <span>RankTrend {{ analysisOf(selectedEntry).scoreBreakdown.rankTrend }}</span>
                  <span>题材 {{ analysisOf(selectedEntry).scoreBreakdown.theme }}</span>
                  <span>龙头 {{ analysisOf(selectedEntry).scoreBreakdown.dragon }}</span>
                  <span>情绪 {{ analysisOf(selectedEntry).scoreBreakdown.sentiment }}</span>
                  <span>资金 {{ analysisOf(selectedEntry).scoreBreakdown.moneyFlow }}</span>
                </div>
              </section>

              <section>
                <h4>入池理由</h4>
                <p>{{ selectedEntry.entryReason || '暂无入池理由' }}</p>
              </section>
              <section>
                <h4>交易假设</h4>
                <p>{{ selectedEntry.tradeHypothesis || '暂无交易假设' }}</p>
              </section>
              <section>
                <h4>买入前提</h4>
                <p>{{ selectedEntry.entryPrerequisites || '暂无买入前提' }}</p>
              </section>
              <section>
                <h4>失效条件</h4>
                <p>{{ selectedEntry.invalidationRules || '暂无失效条件' }}</p>
              </section>

              <section v-if="analysisOf(selectedEntry).riskWarnings.length">
                <h4>风险提示</h4>
                <ul>
                  <li v-for="risk in analysisOf(selectedEntry).riskWarnings" :key="risk">{{ risk }}</li>
                </ul>
              </section>
            </template>
            <div v-else class="empty detail-empty">选择一条候选股查看分析详情</div>
          </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type { CandidateJournalEntry, CandidateStatus } from '@/services/candidate/types'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'close'): void
}>()

const loading = ref(false)
const errorMessage = ref('')
const statusFilter = ref('')
const candidates = ref<CandidateJournalEntry[]>([])
const selectedId = ref('')
const updatingStatus = ref(false)

const selectedEntry = computed(() =>
  candidates.value.find((entry) => entry.id === selectedId.value) || null,
)

const nextStatuses: CandidateStatus[] = ['observe', 'candidate', 'triggered', 'tracking', 'reviewed']

function close() {
  emit('update:visible', false)
  emit('close')
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    observe: '观察',
    candidate: '候选',
    triggered: '触发',
    tracking: '跟踪中',
    reviewed: '已复盘',
  }
  return labels[status] || status || '未设置'
}

function analysisOf(entry: CandidateJournalEntry) {
  const analysis = entry.signalsSnapshot?.candidateAnalysis || {}
  return {
    score: Number(analysis.score || 0),
    grade: String(analysis.grade || '-'),
    riskWarnings: Array.isArray(analysis.riskWarnings) ? analysis.riskWarnings : [],
    scoreBreakdown: {
      rankTrend: Number(analysis.scoreBreakdown?.rankTrend || 0),
      theme: Number(analysis.scoreBreakdown?.theme || 0),
      dragon: Number(analysis.scoreBreakdown?.dragon || 0),
      sentiment: Number(analysis.scoreBreakdown?.sentiment || 0),
      moneyFlow: Number(analysis.scoreBreakdown?.moneyFlow || 0),
    },
  }
}

async function loadCandidates() {
  loading.value = true
  errorMessage.value = ''
  try {
    candidates.value = await candidateJournalService.listCandidates({
      status: statusFilter.value || undefined,
      limit: 100,
    })
    if (!selectedId.value || !candidates.value.some((entry) => entry.id === selectedId.value)) {
      selectedId.value = candidates.value[0]?.id || ''
    }
  } catch (error) {
    errorMessage.value = `候选池加载失败：${error instanceof Error ? error.message : '未知错误'}`
    candidates.value = []
    selectedId.value = ''
  } finally {
    loading.value = false
  }
}

async function updateStatus(status: CandidateStatus) {
  if (!selectedEntry.value) return
  updatingStatus.value = true
  errorMessage.value = ''
  try {
    const updated = await candidateJournalService.updateCandidateStatus(selectedEntry.value.id, status)
    candidates.value = candidates.value.map((entry) => (entry.id === updated.id ? updated : entry))
  } catch (error) {
    errorMessage.value = `候选状态更新失败：${error instanceof Error ? error.message : '未知错误'}`
  } finally {
    updatingStatus.value = false
  }
}

onMounted(() => {
  if (props.visible) void loadCandidates()
})

watch(
  () => props.visible,
  (visible) => {
    if (visible) void loadCandidates()
  },
)
</script>

<style scoped>
.candidate-mask {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
}

.candidate-panel {
  display: flex;
  flex-direction: column;
  width: min(1180px, calc(100vw - 32px));
  height: min(760px, calc(100vh - 48px));
  overflow: hidden;
  color: var(--text-primary);
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
}

.candidate-header,
.candidate-toolbar,
.detail-title,
.score-row,
.stock-line,
.meta-line,
.status-actions,
.breakdown {
  display: flex;
  align-items: center;
}

.candidate-header {
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid var(--border-color);
}

.candidate-header h2,
.detail-title h3 {
  margin: 0;
  font-size: 18px;
}

.candidate-header p,
.detail-title span {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.icon-btn,
.text-btn,
.status-actions button,
.candidate-item {
  color: var(--text-primary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
}

.icon-btn {
  width: 32px;
  height: 32px;
  font-size: 18px;
}

.candidate-toolbar {
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
}

.candidate-toolbar select,
.text-btn,
.status-actions button {
  height: 30px;
  padding: 0 10px;
}

.summary {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 12px;
}

.error {
  margin: 10px 14px 0;
  padding: 8px 10px;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 6px;
  font-size: 12px;
}

.candidate-body {
  display: grid;
  grid-template-columns: 360px 1fr;
  min-height: 0;
  flex: 1;
}

.candidate-list {
  overflow-y: auto;
  border-right: 1px solid var(--border-color);
}

.candidate-item {
  display: block;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid var(--border-color);
  border-radius: 0;
  text-align: left;
}

.candidate-item.active {
  background: rgba(255, 165, 2, 0.16);
}

.stock-line,
.meta-line,
.score-row,
.breakdown {
  justify-content: space-between;
  gap: 8px;
}

.stock-line span,
.meta-line {
  color: var(--text-secondary);
  font-size: 12px;
}

.candidate-detail {
  overflow-y: auto;
  padding: 16px 18px 22px;
}

.detail-title {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.status-actions {
  flex-wrap: wrap;
  gap: 6px;
}

section {
  margin: 0 0 14px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

section h4 {
  margin: 0 0 8px;
  color: var(--text-title);
  font-size: 13px;
}

section p,
section li {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.65;
}

ul {
  margin: 0;
  padding-left: 18px;
}

.score-row strong {
  color: var(--color-highlight);
  font-size: 22px;
}

.breakdown {
  flex-wrap: wrap;
  justify-content: flex-start;
  margin-top: 8px;
}

.breakdown span {
  padding: 3px 7px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  border-radius: 5px;
  font-size: 12px;
}

.empty {
  padding: 24px;
  color: var(--text-tertiary);
  text-align: center;
}

.detail-empty {
  margin-top: 180px;
}
</style>
