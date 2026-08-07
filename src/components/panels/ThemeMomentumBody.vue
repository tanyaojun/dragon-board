<!-- src/components/panels/ThemeMomentumBody.vue -->
<!-- 题材动量 v2 嵌入式正文：参照 SectorStocksTree.vue 题材树形列表面板风格（左列表 + 右详情，CSS 变量主题化） -->

<template>
  <div class="theme-momentum-embedded">
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <div class="loading-spinner"></div>
      <span>加载题材动量…</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-state">
      <span class="error-icon">⚠️</span>
      <span>{{ error }}</span>
      <button class="retry-btn" @click="$emit('retry')">重试</button>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!summary" class="empty-state">
      <span class="empty-icon">🔄</span>
      <span>暂无题材动量数据</span>
    </div>

    <template v-else>
      <!-- 左侧题材动量列表 -->
      <div class="momentum-tree">
        <div class="tree-header">
          <h4>📊 题材动量</h4>
          <div class="tree-search">
            <input v-model="treeSearch" placeholder="搜索题材..." class="search-input" />
          </div>
          <div class="tree-stats">
            共 {{ filteredFactors.length }} 个题材
          </div>
        </div>

        <div class="tree-content">
          <div v-if="paginatedFactors.length === 0" class="tree-empty">无匹配题材</div>
          <div v-for="factor in paginatedFactors" :key="factor.themeId" class="tree-node"
            :class="{ selected: selectedFactor?.themeId === factor.themeId }" @click="selectFactor(factor)">
            <div class="node-header">
              <span class="node-name">{{ factor.themeName }}</span>
              <div class="node-badges">
                <span class="strength-badge" :class="strengthLevel(factor.score)">{{ strengthText(factor.score) }}</span>
                <span class="direction-badge" :class="directionClass(factor.direction)">{{ directionText(factor.direction) }}</span>
                <span v-if="factor.ztCount != null && factor.ztCount > 0" class="zt-badge">{{ factor.ztCount }}</span>
              </div>
            </div>
            <div class="node-metrics">
              <span class="metric-item">
                动量 <b :class="directionClass(factor.direction)">{{ fmtNum(factor.score) }}</b>
              </span>
              <span class="metric-item">
                RPS
                <span class="rps-value" :class="rpsTone(factor.rps?.d5)">{{ fmtNum(factor.rps?.d5) }}</span>
                <span class="rps-sep">/</span>
                <span class="rps-value" :class="rpsTone(factor.rps?.d10)">{{ fmtNum(factor.rps?.d10) }}</span>
                <span class="rps-sep">/</span>
                <span class="rps-value" :class="rpsTone(factor.rps?.d20)">{{ fmtNum(factor.rps?.d20) }}</span>
              </span>
            </div>
            <div class="node-meta">
              <span class="phase-chip">{{ factor.phaseLabel || '—' }}</span>
              <span class="meta-item">距高 {{ fmtNum(factor.nearHigh) }}</span>
              <span class="meta-item">资金 {{ fmtFlow(factor.flowVolume) }}</span>
              <span v-if="(factor.crowdingPenalty ?? 0) > 0" class="penalty-chip penalized">
                拥挤 -{{ factor.crowdingPenalty }}
              </span>
            </div>
            <div class="node-progress" v-if="factor.score != null">
              <div class="progress-bar" :style="{ width: Math.max(0, Math.min(100, factor.score)) + '%' }"></div>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="filteredFactors.length > pageSize" class="tree-pagination">
          <button @click="treePage--" :disabled="treePage === 1">←</button>
          <span>{{ treePage }}/{{ totalPages }}</span>
          <button @click="treePage++" :disabled="treePage === totalPages">→</button>
        </div>
      </div>

      <!-- 右侧题材详情 -->
      <div class="momentum-detail">
        <div v-if="selectedFactor" class="factor-detail">
          <div class="detail-header">
            <div class="detail-title">
              <h4>{{ selectedFactor.themeName }}</h4>
              <span class="direction-badge" :class="directionClass(selectedFactor.direction)">
                {{ directionText(selectedFactor.direction) }}
              </span>
              <span class="phase-chip">{{ selectedFactor.phaseLabel || '—' }}</span>
              <span v-if="computedAtText" class="detail-time">🕒 {{ computedAtText }}</span>
            </div>
            <div class="score-hero">
              <span class="hero-score" :class="directionClass(selectedFactor.direction)">
                {{ fmtNum(selectedFactor.score) }}
              </span>
              <span class="hero-label">动量分</span>
            </div>
          </div>

          <div class="detail-grid">
            <div class="detail-block">
              <h4>多窗口动量</h4>
              <p class="stat-line"><span class="stat-key">5日</span><b>{{ fmtNum(selectedFactor.windowMomentum) }}</b></p>
              <p class="stat-line">
                <span class="stat-key">RPS 5/10/20</span>
                <b>{{ fmtNum(selectedFactor.rps?.d5) }}</b> / <b>{{ fmtNum(selectedFactor.rps?.d10) }}</b> /
                <b>{{ fmtNum(selectedFactor.rps?.d20) }}</b>
              </p>
              <p class="stat-line"><span class="stat-key">距高点</span><b>{{ fmtNum(selectedFactor.nearHigh) }}</b></p>
            </div>
            <div class="detail-block">
              <h4>整体性</h4>
              <p class="stat-line"><span class="stat-key">宽度/一致性</span><b>{{ fmtNum(selectedFactor.breadth) }}</b></p>
              <p class="stat-line"><span class="stat-key">资金量能</span><b>{{ fmtFlow(selectedFactor.flowVolume) }}</b></p>
              <p class="stat-line">
                <span class="stat-key">拥挤扣分</span>
                <b class="penalty-chip" :class="{ penalized: (selectedFactor.crowdingPenalty ?? 0) > 0 }">
                  {{ selectedFactor.crowdingPenalty ?? '--' }}
                </b>
              </p>
            </div>
            <div class="detail-block">
              <h4>龙头/涨停</h4>
              <p class="stat-line"><span class="stat-key">涨停家数</span><b>{{ selectedFactor.ztCount ?? '--' }}</b></p>
            </div>
            <div class="detail-block">
              <h4>日内状态</h4>
              <template v-if="selectedFactor.intraday?.unavailable">
                <p class="stat-line">槽位口径未接入（unavailable）</p>
              </template>
              <template v-else>
                <p class="stat-line">
                  <span class="stat-key">短变化</span><b>{{ fmtNum(selectedFactor.intraday?.shortChange) }}</b>
                </p>
                <p class="stat-line">
                  <span class="stat-key">涨停增量</span><b>{{ fmtNum(selectedFactor.intraday?.ztDelta) }}</b>
                </p>
                <p class="stat-line">
                  <span class="stat-key">资金增量</span><b>{{ fmtNum(selectedFactor.intraday?.inflowDelta) }}</b>
                </p>
              </template>
            </div>
            <div class="detail-block reasons">
              <h4>依据</h4>
              <ul>
                <li v-for="(reason, index) in (selectedFactor.reasons || [])" :key="index">{{ reason }}</li>
                <li v-if="!(selectedFactor.reasons || []).length">—</li>
              </ul>
            </div>
          </div>
        </div>

        <div v-else class="empty-selection">
          <div class="empty-icon">📊</div>
          <div class="empty-text">请从左侧选择一个题材</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { ThemeMomentumSummary, ThemeMomentumSummaryFactor } from '@/services/theme/ThemeFacade'

const props = defineProps<{
  summary: ThemeMomentumSummary | null
  loading: boolean
  error: string | null
  computedAtText: string
}>()

defineEmits<{ (e: 'retry'): void }>()

// ========== 左侧题材列表状态 ==========
const treeSearch = ref('')
const treePage = ref(1)
const pageSize = 10
const selectedId = ref<string | null>(null)

const filteredFactors = computed<ThemeMomentumSummaryFactor[]>(() => {
  const factors = props.summary?.factors || []
  const sorted = [...factors].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  if (!treeSearch.value) return sorted
  const keyword = treeSearch.value.toLowerCase()
  return sorted.filter(
    (f) => f.themeName.toLowerCase().includes(keyword) || f.themeId.toLowerCase().includes(keyword),
  )
})

const paginatedFactors = computed(() => {
  const start = (treePage.value - 1) * pageSize
  return filteredFactors.value.slice(start, start + pageSize)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredFactors.value.length / pageSize)))

const selectedFactor = computed<ThemeMomentumSummaryFactor | null>(
  () => filteredFactors.value.find((f) => f.themeId === selectedId.value) ?? null,
)

function selectFactor(factor: ThemeMomentumSummaryFactor) {
  selectedId.value = factor.themeId
}

// ========== 展示辅助 ==========
function strengthLevel(score: number | null | undefined): string {
  if (score == null) return 'd'
  if (score >= 80) return 's'
  if (score >= 65) return 'a'
  if (score >= 50) return 'b'
  if (score >= 35) return 'c'
  return 'd'
}

function strengthText(score: number | null | undefined): string {
  if (score == null) return '--'
  if (score >= 80) return 'S'
  if (score >= 65) return 'A'
  if (score >= 50) return 'B'
  if (score >= 35) return 'C'
  return 'D'
}

function directionText(direction?: string): string {
  return direction === 'up' ? '上行' : direction === 'down' ? '下行' : '中性'
}

function directionClass(direction?: string): string {
  return direction === 'up' ? 'positive-tone' : direction === 'down' ? 'negative-tone' : 'neutral-tone'
}

function rpsTone(value?: number | null): string {
  if (value == null) return ''
  return value >= 80 ? 'rps-strong' : value >= 50 ? 'rps-mid' : 'rps-weak'
}

function fmtNum(value?: number | null): string {
  return value == null ? '--' : String(value)
}

function fmtFlow(value?: number | null): string {
  if (value == null) return '--'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return String(value)
}

// ========== 状态联动 ==========
watch(treeSearch, () => {
  treePage.value = 1
})

// 数据到达后默认选中第一行
watch(
  () => filteredFactors.value,
  (factors) => {
    if (!selectedId.value && factors.length) {
      selectedId.value = factors[0].themeId
    }
  },
  { immediate: true },
)
</script>

<style scoped>
/* ========== 嵌入容器（题材树形面板内） ========== */
.theme-momentum-embedded {
  display: flex;
  height: 100%;
  min-height: 500px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

/* ========== 左侧题材动量列表 ========== */
.momentum-tree {
  width: 320px;
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.tree-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
}

.tree-header h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
  color: var(--text-title);
}

.tree-search {
  margin-bottom: 8px;
}

.search-input {
  width: 100%;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
}

.search-input:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.tree-stats {
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.tree-empty {
  padding: 24px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
}

.tree-node {
  padding: 10px;
  margin-bottom: 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.tree-node:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.tree-node.selected {
  border-color: var(--color-highlight);
  background: rgba(255, 127, 80, 0.1);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 6px;
}

.node-name {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.node-badges {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.strength-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: bold;
}

.strength-badge.s {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.strength-badge.a {
  background: rgba(255, 127, 80, 0.2);
  color: #ff7f50;
}

.strength-badge.b {
  background: rgba(255, 177, 66, 0.2);
  color: #ffb142;
}

.strength-badge.c {
  background: rgba(74, 144, 226, 0.2);
  color: #4a90e2;
}

.strength-badge.d {
  background: rgba(127, 140, 141, 0.2);
  color: #7f8c8d;
}

.direction-badge {
  display: inline-block;
  font-size: 10px;
  border-radius: 4px;
  padding: 1px 6px;
  background: var(--bg-tertiary, var(--bg-secondary));
}

.positive-tone {
  color: #ff4757;
}

.negative-tone {
  color: #2ed573;
}

.neutral-tone {
  color: #95a5a6;
}

.zt-badge {
  padding: 2px 6px;
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
  border-radius: 10px;
  font-size: 10px;
  font-weight: bold;
}

.node-metrics {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  margin-bottom: 5px;
}

.metric-item {
  color: var(--text-secondary);
  display: flex;
  align-items: baseline;
  gap: 3px;
  white-space: nowrap;
}

.metric-item b {
  font-family: monospace;
}

.rps-sep {
  opacity: 0.4;
  margin: 0 1px;
}

.rps-strong {
  color: #ff4757;
}

.rps-mid {
  color: #f39c12;
}

.rps-weak {
  color: #2ed573;
}

.node-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.phase-chip {
  padding: 1px 6px;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  font-size: 10px;
  color: var(--text-secondary);
}

.penalty-chip {
  color: #e8a87c;
  font-weight: 500;
}

.penalty-chip.penalized {
  background: rgba(232, 168, 124, 0.15);
  border-radius: 4px;
  padding: 1px 6px;
}

.node-progress {
  height: 3px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--color-highlight);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.tree-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 10px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
  font-size: 11px;
  color: var(--text-secondary);
}

.tree-pagination button {
  padding: 3px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
  font-size: 11px;
}

.tree-pagination button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* ========== 右侧题材详情 ========== */
.momentum-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  min-width: 0;
  overflow-y: auto;
}

.factor-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.detail-title h4 {
  margin: 0;
  font-size: 16px;
  color: var(--text-title);
}

.detail-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.score-hero {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex-shrink: 0;
}

.hero-score {
  font-family: monospace;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.1;
}

.hero-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  padding: 16px;
}

.detail-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px 14px;
}

.detail-block h4 {
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
}

.stat-line {
  margin: 3px 0;
  font-size: 12px;
  color: var(--text-primary);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stat-key {
  font-size: 11px;
  color: var(--text-secondary);
  min-width: 84px;
}

.stat-line b {
  font-family: monospace;
  font-weight: 600;
}

.detail-block.reasons {
  grid-column: 1 / -1;
}

.detail-block.reasons ul {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--text-primary);
}

.detail-block.reasons li {
  margin: 2px 0;
}

.empty-selection {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

/* ========== 通用状态样式 ========== */
.loading-state,
.error-state,
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 48px 20px;
}

.loading-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.error-icon,
.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.retry-btn {
  padding: 5px 14px;
  background: var(--color-highlight);
  border: none;
  border-radius: 16px;
  color: #000;
  font-size: 11px;
  cursor: pointer;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 860px) {
  .theme-momentum-embedded {
    flex-direction: column;
  }

  .momentum-tree {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
    max-height: 320px;
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
