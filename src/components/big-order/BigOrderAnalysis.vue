<!-- src/components/big-order/BigOrderAnalysis.vue -->
<template>
  <div v-if="visible" class="big-order-analysis" :class="themeStore.themeClass">
    <div class="analysis-header">
      <h3>
        <span class="header-icon">📊</span>
        大单分析 - {{ stockName || stockCode }} ({{ stockCode }})
      </h3>
      <button class="close-btn" @click="close">×</button>
    </div>

    <div class="analysis-content">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载中... {{ progress }}%</span>
      </div>

      <!-- 无数据状态 -->
      <div v-else-if="!stats || stats.totalCount === 0" class="empty-state">
        <div class="empty-icon">📊</div>
        <div class="empty-text">暂无大单数据</div>
      </div>

      <!-- 数据展示 -->
      <template v-else>
        <!-- 总体统计 -->
        <div class="section">
          <h4>总体统计</h4>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="label">总笔数</span>
              <span class="value">{{ stats.totalCount || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="label">买入总额</span>
              <span class="value" :style="{ color: colorService.colors.buy }">
                {{ formatAmount(stats.buyAmount || 0) }}
              </span>
            </div>
            <div class="stat-item">
              <span class="label">卖出总额</span>
              <span class="value" :style="{ color: colorService.colors.sell }">
                {{ formatAmount(stats.sellAmount || 0) }}
              </span>
            </div>
            <div class="stat-item">
              <span class="label">净买入</span>
              <span class="value" :style="{
                color: colorService.getStatisticsColor('netBuy', stats.netBuy)
              }">
                {{ formatAmount(stats.netBuy || 0) }}
              </span>
            </div>
            <div class="stat-item">
              <span class="label">平均金额</span>
              <span class="value">{{ formatAmount(stats.avgAmount || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">最大金额</span>
              <span class="value">{{ formatAmount(stats.maxAmount || 0) }}</span>
            </div>
          </div>
        </div>

        <!-- 主动买卖统计 -->
        <div class="section">
          <h4>主动买卖</h4>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="label">主动买入</span>
              <span class="value">{{ formatAmount(stats.mainBuyAmount || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">主动卖出</span>
              <span class="value">{{ formatAmount(stats.mainSellAmount || 0) }}</span>
            </div>
            <div class="stat-item">
              <span class="label">主动净额</span>
              <span class="value" :style="{
                color: colorService.getStatisticsColor('netBuy', mainNet)
              }">
                {{ formatAmount(mainNet) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 标记统计 -->
        <div class="section">
          <h4>特殊标记</h4>
          <div class="tags-grid">
            <div class="tag-item" :style="{ backgroundColor: colorService.colors.ignite + '20' }">
              <span class="tag-label" :style="{ color: colorService.colors.ignite }">点火</span>
              <span class="tag-value">{{ stats.igniteCount || 0 }}</span>
            </div>
            <div class="tag-item" :style="{ backgroundColor: colorService.colors.smash + '20' }">
              <span class="tag-label" :style="{ color: colorService.colors.smash }">砸盘</span>
              <span class="tag-value">{{ stats.smashCount || 0 }}</span>
            </div>
            <div class="tag-item" :style="{ backgroundColor: colorService.colors.buyActive + '20' }">
              <span class="tag-label" :style="{ color: colorService.colors.buyActive }">买活跃</span>
              <span class="tag-value">{{ stats.buyActiveCount || 0 }}</span>
            </div>
            <div class="tag-item" :style="{ backgroundColor: colorService.colors.sellActive + '20' }">
              <span class="tag-label" :style="{ color: colorService.colors.sellActive }">承接好</span>
              <span class="tag-value">{{ stats.sellActiveCount || 0 }}</span>
            </div>
          </div>
        </div>

        <!-- 图表统计 -->
        <div class="section">
          <h4>买卖对比</h4>
          <div class="chart-container">
            <!-- 买卖比 -->
            <div class="bar-chart">
              <div class="bar-label">买卖比</div>
              <div class="bar-group">
                <div class="bar buy-bar" :style="{ width: buyRatio + '%' }">
                  {{ buyRatio.toFixed(0) }}%
                </div>
                <div class="bar sell-bar" :style="{ width: sellRatio + '%' }">
                  {{ sellRatio.toFixed(0) }}%
                </div>
              </div>
            </div>

            <!-- 主动比 -->
            <div class="bar-chart">
              <div class="bar-label">主动比</div>
              <div class="bar-group">
                <div class="bar buy-active-bar" :style="{ width: mainBuyRatio + '%' }">
                  {{ mainBuyRatio.toFixed(0) }}%
                </div>
                <div class="bar sell-active-bar" :style="{ width: mainSellRatio + '%' }">
                  {{ mainSellRatio.toFixed(0) }}%
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 时段统计表格 -->
        <div class="section">
          <h4>时段统计</h4>
          <div class="period-table">
            <table>
              <thead>
                <tr>
                  <th>时段</th>
                  <th>笔数</th>
                  <th>买入</th>
                  <th>卖出</th>
                  <th>净买</th>
                  <th title="点火">🔥</th>
                  <th title="砸盘">💥</th>
                  <th title="买活跃">📈</th>
                  <th title="承接好">📉</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="period in periodList" :key="period.name">
                  <td>{{ period.name }}</td>
                  <td>{{ period.count }}</td>
                  <td :style="{ color: colorService.colors.buy }">
                    {{ formatShortAmount(period.buyAmount) }}
                  </td>
                  <td :style="{ color: colorService.colors.sell }">
                    {{ formatShortAmount(period.sellAmount) }}
                  </td>
                  <td :style="{ color: colorService.getStatisticsColor('netBuy', period.netBuy) }">
                    {{ formatShortAmount(period.netBuy) }}
                  </td>
                  <td>{{ period.igniteCount }}</td>
                  <td>{{ period.smashCount }}</td>
                  <td>{{ period.buyActiveCount }}</td>
                  <td>{{ period.sellActiveCount }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useBigOrderStore } from '@/stores/bigOrder'
import { BigOrderColorService } from '@/services/big-order/BigOrderColorService'
import type { BigOrderStatistics, PeriodStatistics } from '@/types/big-order'

const props = defineProps<{
  visible: boolean
  stockCode: string
  stockName?: string
  statistics?: BigOrderStatistics | null
  periods?: PeriodStatistics[]
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const themeStore = useThemeStore()
const store = useBigOrderStore()
const colorService = BigOrderColorService.getInstance()

// 获取最新的统计数据（如果 props 没有提供，则从 store 获取）
const stats = computed<BigOrderStatistics | null>(() => {
  return props.statistics || store.filteredStatistics
})

const periodList = computed<PeriodStatistics[]>(() => {
  return props.periods || store.periods
})

const loading = computed(() => store.loading)
const progress = computed(() => {
  const service = (window as any).bigOrderService
  return service?.progress?.value || 0
})

// 计算比率
const total = computed(() =>
  (stats.value?.buyAmount || 0) + (stats.value?.sellAmount || 0)
)

const buyRatio = computed(() =>
  total.value ? ((stats.value?.buyAmount || 0) / total.value) * 100 : 0
)

const sellRatio = computed(() =>
  total.value ? ((stats.value?.sellAmount || 0) / total.value) * 100 : 0
)

const mainTotal = computed(() =>
  (stats.value?.mainBuyAmount || 0) + (stats.value?.mainSellAmount || 0)
)

const mainBuyRatio = computed(() =>
  mainTotal.value ? ((stats.value?.mainBuyAmount || 0) / mainTotal.value) * 100 : 0
)

const mainSellRatio = computed(() =>
  mainTotal.value ? ((stats.value?.mainSellAmount || 0) / mainTotal.value) * 100 : 0
)

const mainNet = computed(() =>
  (stats.value?.mainBuyAmount || 0) - (stats.value?.mainSellAmount || 0)
)

// 格式化函数
const formatAmount = (amount: number): string => {
  if (!amount && amount !== 0) return '0'
  if (amount >= 100000000) {
    return `${(amount / 100000000).toFixed(2)}亿`
  }
  if (amount >= 10000) {
    return `${Math.round(amount / 10000)}万`
  }
  return amount.toString()
}

const formatShortAmount = (amount: number): string => {
  if (!amount && amount !== 0) return '0'
  if (amount >= 100000000) {
    return `${(amount / 100000000).toFixed(1)}亿`
  }
  if (amount >= 10000) {
    return `${Math.round(amount / 10000)}万`
  }
  return '0'
}

// 关闭面板
const close = () => {
  emit('update:visible', false)
  emit('close')
}
</script>

<style scoped>
.big-order-analysis {
  position: fixed;
  top: 60px;
  right: 20px;
  width: 800px;
  height: calc(100vh - 80px);
  background-color: var(--bg-panel);
  backdrop-filter: blur(var(--blur-amount));
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 1500;
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.analysis-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: var(--bg-header);
}

.analysis-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.header-icon {
  font-size: 18px;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--bg-hover);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.close-btn:hover {
  background-color: var(--bg-active);
  color: var(--text-primary);
}

.analysis-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* 章节样式 */
.section {
  margin-bottom: 20px;
}

.section h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 10px 0;
  padding-left: 8px;
  border-left: 3px solid var(--color-highlight);
}

/* 统计网格 - 3列布局，卡片更紧凑 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.stat-item {
  background-color: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border-light);
}

.stat-item .label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.stat-item .value {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.2;
}

/* 买入、卖出、净买颜色 */
.buy-value {
  color: #ff4d4d !important;
  /* 亮红色 */
}

.sell-value {
  color: #4caf50 !important;
  /* 亮绿色 */
}

.net-positive {
  color: #ff4d4d !important;
  /* 净买正为红色 */
}

.net-negative {
  color: #4caf50 !important;
  /* 净买负为绿色 */
}

/* 其他数值用白色高亮 */
.stat-item .value:not(.buy-value):not(.sell-value):not(.net-positive):not(.net-negative) {
  color: var(--text-primary);
  font-weight: 600;
}

/* 主动净额特殊处理 */
.active-net-value {
  font-weight: 600;
}

/* 标签网格 - 4列，更紧凑 */
.tags-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.tag-item {
  background-color: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border-light);
}

.tag-label {
  font-size: 12px;
  font-weight: 500;
}

.tag-value {
  font-size: 20px;
  font-weight: 700;
}

/* 点火、砸盘、买活跃、承接好颜色 */
.tag-item:nth-child(1) .tag-label {
  color: #ffd700;
  /* 点火金色 */
}

.tag-item:nth-child(1) .tag-value {
  color: #ffd700;
}

.tag-item:nth-child(2) .tag-label {
  color: #9370db;
  /* 砸盘紫色 */
}

.tag-item:nth-child(2) .tag-value {
  color: #9370db;
}

.tag-item:nth-child(3) .tag-label {
  color: #ff4500;
  /* 买活跃橙红 */
}

.tag-item:nth-child(3) .tag-value {
  color: #ff4500;
}

.tag-item:nth-child(4) .tag-label {
  color: #00bfff;
  /* 承接好深蓝 */
}

.tag-item:nth-child(4) .tag-value {
  color: #00bfff;
}

/* 图表容器 - 两列布局 */
.chart-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  background-color: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-light);
}

.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bar-label {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}

.bar-group {
  display: flex;
  height: 24px;
  background-color: var(--bg-panel);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border-light);
}

.bar {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: #000;
  transition: width 0.3s ease;
  white-space: nowrap;
}

.buy-bar {
  background: #ff4d4d;
}

.sell-bar {
  background: #4caf50;
}

.buy-active-bar {
  background: #ff4500;
}

.sell-active-bar {
  background: #00bfff;
}

/* 时段表格 */
.period-table {
  background-color: var(--bg-secondary);
  border-radius: 8px;
  padding: 4px;
  border: 1px solid var(--border-light);
  overflow-x: auto;
}

.period-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  min-width: 800px;
}

.period-table th {
  background-color: var(--bg-panel);
  color: var(--text-secondary);
  font-weight: 600;
  padding: 10px 6px;
  text-align: center;
  white-space: nowrap;
  border-bottom: 2px solid var(--border-color);
  font-size: 12px;
}

.period-table td {
  padding: 8px 6px;
  text-align: center;
  border-bottom: 1px solid var(--border-light);
  white-space: nowrap;
  color: var(--text-primary);
}

.period-table tbody tr:hover {
  background-color: var(--bg-hover);
}

.period-table tbody tr:last-child td {
  border-bottom: none;
}

/* 表格内数值颜色 */
.period-table td:nth-child(3) {
  color: #ff4d4d !important;
  /* 买入列红色 */
  font-weight: 600;
}

.period-table td:nth-child(4) {
  color: #4caf50 !important;
  /* 卖出一列绿色 */
  font-weight: 600;
}

.period-table td:nth-child(5) {
  font-weight: 600;
  /* 净买列，颜色由JS动态控制 */
}

/* 加载和空状态 */
.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-tertiary);
  gap: 16px;
  background-color: var(--bg-secondary);
  border-radius: 8px;
}

.loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.empty-icon {
  font-size: 42px;
  opacity: 0.5;
}

.empty-text {
  font-size: 13px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 滚动条美化 */
.analysis-content::-webkit-scrollbar {
  width: 6px;
}

.analysis-content::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-radius: 3px;
}

.analysis-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 3px;
}

.analysis-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 响应式 */
@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .chart-container {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .big-order-analysis {
    width: 100%;
    height: 100vh;
    top: 0;
    right: 0;
    border-radius: 0;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .tags-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
