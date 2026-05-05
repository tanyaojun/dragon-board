<!-- src/components/panels/ThemeCorrelationPanel.vue -->
<!-- 题材个股联动分析看板 - 左树右表结构，懒加载 -->
<template>
  <div v-if="visible" class="correlation-panel" :class="{ embedded }" :style="embedded ? {} : panelStyle"
    ref="panelRef">
    <!-- 独立模式头部 -->
    <div v-if="!embedded" class="panel-header">
      <div class="header-left">
        <span class="panel-icon">🔗</span>
        <h3>题材联动分析</h3>
        <span class="version-badge">v1.0</span>
      </div>
      <div class="header-actions">
        <button class="btn-icon" @click="refresh" title="刷新" :disabled="refreshing">
          <span class="icon" :class="{ rotating: refreshing }">↻</span>
        </button>
        <button class="btn-icon close" @click="close" title="关闭">
          <span class="icon">✕</span>
        </button>
      </div>
    </div>

    <!-- 嵌入模式头部（简化版） -->
    <div v-else class="panel-header embedded-header">
      <div class="header-left">
        <span class="panel-icon">🔗</span>
        <h3>题材联动分析</h3>
      </div>
      <div class="header-actions">
        <button class="btn-icon" @click="refresh" title="刷新" :disabled="refreshing">
          <span class="icon" :class="{ rotating: refreshing }">↻</span>
        </button>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner"></div>
      <span>加载联动数据...</span>
    </div>

    <!-- 面板内容 - 左树右表 -->
    <div class="panel-content" :class="{ 'content-blur': loading }">
      <div class="split-layout">
        <!-- 左侧题材树 -->
        <div class="left-tree">
          <div class="tree-header">
            <h4>📊 题材列表</h4>
            <div class="tree-search">
              <input v-model="treeSearch" placeholder="搜索题材..." class="search-input" />
            </div>
            <div class="tree-stats">
              共 {{ filteredThemes.length }} 个题材
            </div>
          </div>

          <div class="tree-content" ref="treeContentRef">
            <!-- 懒加载：只渲染当前页的题材，不预加载个股数据 -->
            <div v-for="theme in paginatedThemes" :key="theme.id" class="tree-node"
              :class="{ 'selected': selectedTheme?.id === theme.id, 'loading': loadingTheme === theme.id }"
              @click="selectTheme(theme)">
              <div class="node-header">
                <span class="node-name">
                  {{ theme.name }}
                  <span v-if="theme.isMainLine" class="mainline-badge">主线</span>
                </span>
                <div class="node-badges">
                  <span class="strength-badge" :class="getStrengthClass(theme.strength)">
                    {{ formatStrength(theme.strength) }}
                  </span>
                  <span class="stock-count">{{ theme.stockCount }}只</span>
                </div>
              </div>
              <div class="node-metrics">
                <span class="correlation-badge"
                  :style="{ background: theme.correlation > 0 ? getCorrelationColor(theme.correlation) : '#95a5a6' }">
                  <template v-if="theme.correlation > 0">
                    联动 {{ (theme.correlation * 100).toFixed(0) }}%
                  </template>
                  <template v-else>
                    待计算
                  </template>
                </span>
                <span class="change" :class="theme.change >= 0 ? 'up' : 'down'">
                  {{ theme.change > 0 ? '+' : '' }}{{ theme.change?.toFixed(2) }}%
                </span>
              </div>
              <div class="node-progress">
                <div class="progress-bar" :style="{
                  width: (theme.correlation * 100) + '%',
                  background: getCorrelationColor(theme.correlation)
                }"></div>
              </div>
            </div>

            <!-- 分页 -->
            <div v-if="filteredThemes.length > pageSize" class="tree-pagination">
              <button @click="treePage--" :disabled="treePage === 1">←</button>
              <span>{{ treePage }}/{{ treeTotalPages }}</span>
              <button @click="treePage++" :disabled="treePage === treeTotalPages">→</button>
            </div>
          </div>
        </div>

        <!-- 右侧联动详情（懒加载：点击后才加载个股数据） -->
        <div class="right-detail" v-if="selectedTheme">
          <!-- 题材概览卡片（数据来自缓存，无需加载） -->
          <div class="theme-overview"
            :style="{ borderLeftColor: getCorrelationColor(themeCorrelation?.overallCorrelation) }">
            <div class="overview-header">
              <h4>{{ selectedTheme.name }}</h4>
              <div class="overview-stats">
                <span class="stat-item">
                  <span class="stat-label">整体联动</span>
                  <span class="stat-value"
                    :style="{ color: getCorrelationColor(themeCorrelation?.overallCorrelation) }">
                    {{ (((themeCorrelation?.overallCorrelation ?? 0) * 100).toFixed(1)) }}%
                  </span>
                </span>
                <span class="stat-item">
                  <span class="stat-label">核心股</span>
                  <span class="stat-value">{{ themeCorrelation?.coreStocks?.length || 0 }}</span>
                </span>
                <span class="stat-item">
                  <span class="stat-label">跟风股</span>
                  <span class="stat-value">{{ themeCorrelation?.followerStocks?.length || 0 }}</span>
                </span>
              </div>
            </div>

            <!-- ✅ 个股详情卡片 -->
            <div v-if="selectedStock" class="leader-card">
              <!-- 第一行：个股名称和基本信息 -->
              <div class="leader-header">
                <span class="leader-icon">📈</span>
                <span class="leader-title">{{ selectedStock.role === 'leader' ? '龙头股' : '成分股详情' }}</span>
                <span class="leader-name">{{ selectedStock.name }}</span>
                <span class="leader-code">{{ selectedStock.code }}</span>
              </div>

              <!-- 第二行：核心指标 -->
              <div class="leader-stats">
                <div class="stat-group">
                  <div class="stat-item">
                    <span class="stat-label">涨跌幅</span>
                    <span class="stat-value" :class="selectedStock.change >= 0 ? 'up' : 'down'">
                      {{ selectedStock.change > 0 ? '+' : '' }}{{ selectedStock.change?.toFixed(2) }}%
                    </span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最新价</span>
                    <span class="stat-value">{{ formatPrice(selectedStock.price) || '--' }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">量比</span>
                    <span class="stat-value">{{ formatVolumeRatio(selectedStock.volumeRatio) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">人气</span>
                    <span class="stat-value">{{ formatPopularity(selectedStock.popularity) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">人气变动</span>
                    <span class="stat-value" :class="getPopularityChangeClass(selectedStock.popularityChange)">
                      {{ formatPopularityChange(selectedStock.popularityChange) }}
                    </span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.mainBuy">
                    <span class="fund-label">主力买入</span>
                    <span class="stat-value up">{{ formatMoney(selectedStock.mainBuy) }}</span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.mainSell">
                    <span class="fund-label">主力卖出</span>
                    <span class="stat-value down">{{ formatMoney(selectedStock.mainSell) }}</span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.fengdan">
                    <span class="fund-label">封单额</span>
                    <span class="stat-value">{{ formatFengdan(selectedStock.fengdan) }}</span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.maxFengdan">
                    <span class="fund-label">最大封单</span>
                    <span class="stat-value">{{ formatFengdan(selectedStock.maxFengdan) }}</span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.bigMoney300">
                    <span class="fund-label">300W</span>
                    <span class="stat-value">{{ formatLargeOrder(selectedStock.bigMoney300) }}</span>
                  </div>
                  <div class="fund-item" v-if="selectedStock.cirMV">
                    <span class="fund-label">流通市值</span>
                    <span class="stat-value">{{ formatCirculatingMarketCap(selectedStock.cirMV) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- ✅ 龙头信息卡片（来自缓存，无需加载） -->
            <div v-else-if="themeCorrelation?.leader" class="leader-card">
              <!-- 第一行：龙头名称和基本信息 -->
              <div class="leader-header">
                <span class="leader-icon">👑</span>
                <span class="leader-title">板块龙头</span>
                <span class="leader-name">{{ themeCorrelation.leader.name }}</span>
                <span class="leader-code">{{ themeCorrelation.leader.code }}</span>
              </div>

              <!-- 第二行：核心指标 -->
              <div class="leader-stats">
                <div class="stat-group">
                  <div class="stat-item">
                    <span class="stat-label">龙头得分</span>
                    <span class="stat-value" :class="getLeaderScoreClass(themeCorrelation.leader.score)">
                      {{ themeCorrelation.leader.score }}
                    </span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">置信度</span>
                    <span class="stat-value" :class="getConfidenceClass(themeCorrelation.leader.confidence)">
                      {{ themeCorrelation.leader.confidence }}%
                    </span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">连板</span>
                    <span class="stat-value">{{ themeCorrelation.leader.lianban || '首板' }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">涨幅</span>
                    <span class="stat-value" :class="themeCorrelation.leader.change >= 0 ? 'up' : 'down'">
                      {{ themeCorrelation.leader.change > 0 ? '+' : '' }}{{ themeCorrelation.leader.change?.toFixed(2)
                      }}%
                    </span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">最新价</span>
                    <span class="stat-value">{{ formatPrice(themeCorrelation.leader.price) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">量比</span>
                    <span class="stat-value">{{ formatVolumeRatio(themeCorrelation.leader.volumeRatio) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">人气</span>
                    <span class="stat-value">{{ formatPopularity(themeCorrelation.leader.popularity) }}</span>
                  </div>
                  <div class="stat-item">
                    <span class="stat-label">人气变动</span>
                    <span class="stat-value"
                      :class="getPopularityChangeClass(themeCorrelation.leader.popularityChange)">
                      {{ formatPopularityChange(themeCorrelation.leader.popularityChange) }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- 第三行：资金指标 -->
              <div class="leader-funds">
                <div class="fund-group">
                  <div class="fund-item">
                    <span class="fund-label">封单额</span>
                    <span class="fund-value">{{ formatFengdan(themeCorrelation.leader.fengdan) }}</span>
                  </div>
                  <div class="fund-item">
                    <span class="fund-label">最大封单</span>
                    <span class="fund-value">{{ formatFengdan(themeCorrelation.leader.maxFengdan) }}</span>
                  </div>
                  <div class="fund-item">
                    <span class="fund-label">300W</span>
                    <span class="fund-value">{{ formatLargeOrder(themeCorrelation.leader.largeOrder300w) }}</span>
                  </div>
                  <div class="fund-item">
                    <span class="fund-label">主力买入</span>
                    <span class="fund-value up">{{ formatMoney(themeCorrelation.leader.mainBuy) }}</span>
                  </div>
                  <div class="fund-item">
                    <span class="fund-label">主力卖出</span>
                    <span class="fund-value down">{{ formatMoney(themeCorrelation.leader.mainSell) }}</span>
                  </div>
                  <div class="fund-item">
                    <span class="fund-label">流通市值</span>
                    <span class="fund-value">{{ formatCirculatingMarketCap(themeCorrelation.leader.circulatingMarketCap)
                    }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- ✅ 板块统计卡片（来自缓存，无需加载） -->
            <div v-if="themeCorrelation?.stats" class="stats-card">
              <div class="stats-row">
                <span class="stats-label">📊 板块统计</span>
                <span class="stats-item">股票数: {{ themeCorrelation.stats.totalStocks }}只</span>
                <span class="stats-item">平均涨幅: {{ themeCorrelation.stats.avgChange > 0 ? '+' : '' }}{{
                  themeCorrelation.stats.avgChange }}%</span>
                <span class="stats-item">涨停数: {{ themeCorrelation.stats.totalZtCount }}只</span>
                <span class="stats-item">平均量比: {{ themeCorrelation.stats.avgVolumeRatio }}</span>
                <span class="stats-item">总流入: {{ formatMoney(themeCorrelation.stats.totalMainInflow) }}</span>
              </div>
            </div>
          </div>

          <!-- 标签页 -->
          <div class="detail-tabs">
            <button class="tab-btn" :class="{ active: detailView === 'all' }" @click="detailView = 'all'">
              全部股票 ({{ themeStocks.length }})
            </button>
            <button class="tab-btn" :class="{ active: detailView === 'core' }" @click="detailView = 'core'">
              核心股 ({{ themeCorrelation?.coreStocks?.length || 0 }})
            </button>
            <button class="tab-btn" :class="{ active: detailView === 'follower' }" @click="detailView = 'follower'">
              跟风股 ({{ themeCorrelation?.followerStocks?.length || 0 }})
            </button>
            <button class="tab-btn" :class="{ active: detailView === 'independent' }"
              @click="detailView = 'independent'">
              独立股 ({{ themeCorrelation?.independentStocks?.length || 0 }})
            </button>
          </div>

          <!-- 搜索和排序 -->
          <div class="table-controls">
            <div class="search-box">
              <input v-model="stockSearch" placeholder="搜索股票..." class="search-input" />
            </div>
            <div class="sort-controls">
              <select v-model="sortBy" class="sort-select">
                <option value="leaderCorrelation">龙头相关</option>
                <option value="avgCorrelation">平均相关</option>
                <option value="change">涨跌幅</option>
                <option value="directionConsistency">方向一致</option>
              </select>
              <button class="sort-btn" @click="sortDesc = !sortDesc">
                {{ sortDesc ? '↓' : '↑' }}
              </button>
            </div>
          </div>

          <!-- 个股联动表格（懒加载：只有点击题材后才显示数据） -->
          <div class="table-wrapper" ref="tableWrapperRef">
            <div v-if="loadingTheme === selectedTheme?.id" class="stock-loading">
              <div class="loading-spinner-small"></div>
              <span>加载个股数据...</span>
            </div>
            <table v-else class="correlation-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>代码</th>
                  <th>名称</th>
                  <th>角色</th>
                  <th @click="setSort('avgCorrelation')">平均相关</th>
                  <th @click="setSort('leaderCorrelation')">龙头相关</th>
                  <th @click="setSort('change')">涨跌幅</th>
                  <th @click="setSort('directionConsistency')">方向一致</th>
                  <th>涨幅差异</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(stock, index) in paginatedStocks" :key="stock.code" :class="getStockRowClass(stock)">
                  <td>{{ (stockPage - 1) * stockPageSize + index + 1 }}</td>
                  <!-- ✅ 添加代码列 -->
                  <td>
                    <span class="code-link">{{ stock.code }}</span>
                  </td>
                  <td>{{ stock.name }}</td>
                  <td>
                    <span class="role-badge" :class="`role-${stock.role}`">
                      {{ getRoleName(stock.role) }}
                    </span>
                  </td>
                  <td :style="{ color: getCorrelationColor(stock.avgCorrelation), fontWeight: 'bold' }">
                    {{ (stock.avgCorrelation * 100).toFixed(1) }}%
                  </td>
                  <td :style="{ color: getCorrelationColor(stock.leaderCorrelation) }">
                    {{ (stock.leaderCorrelation * 100).toFixed(1) }}%
                  </td>
                  <td :class="(stock.change || 0) >= 0 ? 'up' : 'down'">
                    {{ (stock.change || 0) > 0 ? '+' : '' }}{{ (stock.change || 0).toFixed(2) }}%
                  </td>
                  <td>
                    <span class="consistency-text" :style="{ color: getConsistencyColor(stock.directionConsistency) }">
                      {{ (stock.directionConsistency * 100).toFixed(0) }}%
                    </span>
                  </td>
                  <td>
                    <span class="diff-badge" :class="getDiffClass(stock.changeDiff)">
                      {{ (stock.changeDiff).toFixed(0) }}%
                    </span>
                  </td>
                  <td>
                    <button class="btn-icon-small" @click.stop="selectStock(stock)" title="查看详情">🔍</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页 -->
          <div v-if="filteredStocks.length > stockPageSize" class="table-pagination">
            <button @click="stockPage--" :disabled="stockPage === 1">上一页</button>
            <span>{{ stockPage }}/{{ stockTotalPages }}</span>
            <button @click="stockPage++" :disabled="stockPage === stockTotalPages">下一页</button>
          </div>
        </div>

        <!-- 未选择题材时的提示 -->
        <div v-else class="empty-selection">
          <div class="empty-icon">🔗</div>
          <div class="empty-text">请从左侧选择一个题材查看个股联动性</div>
        </div>
      </div>
    </div>

    <!-- 底部（独立模式） -->
    <div v-if="!embedded" class="panel-footer">
      <span class="update-time">⏱️ 更新时间: {{ formatTime(lastUpdate) }}</span>
      <span class="source-info">数据源: 实时联动分析</span>
    </div>

    <!-- 底部（嵌入模式） -->
    <div v-else class="panel-footer embedded-footer">
      <span class="update-time">⏱️ 更新时间: {{ formatTime(lastUpdate) }}</span>
    </div>
  </div>
  <!-- 预加载进度提示（可选） -->
  <div v-if="preloading" class="preload-progress">
    <div class="preload-bar" :style="{ width: (preloadedCount / PRELOAD_COUNT * 100) + '%' }"></div>
    <span>预加载热门题材... {{ preloadedCount }}/{{ PRELOAD_COUNT }}</span>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { themeCorrelationAnalyzer } from '@/services/ThemeCorrelationAnalyzer'
import { usePanel } from '@/composables/usePanel'
import { useUIStore } from '@/stores/ui'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

const props = defineProps<{
  visible: boolean
  embedded?: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'select-stock', code: string): void
}>()

// ========== 面板定位 ==========
const { panelRef, panelStyle } = props.embedded
  ? { panelRef: ref(null), panelStyle: {} }
  : usePanel({
    name: 'ThemeCorrelationPanel',
    visible: props.visible,
    triggerRect: props.triggerRect,
    onClose: () => emit('close')
  })

// ========== 状态 ==========
const loading = ref(false)
const loadingTheme = ref<string | null>(null)
const refreshing = ref(false)  // ✅ 刷新动画状态
const preloading = ref(false)
const preloadedCount = ref(0)
const treeSearch = ref('')
const treePage = ref(1)
const pageSize = ref(20)
const selectedTheme = ref<any>(null)
const detailView = ref<'all' | 'core' | 'follower' | 'independent'>('all')
const stockSearch = ref('')
const sortBy = ref('leaderCorrelation')
const sortDesc = ref(true)
const stockPage = ref(1)
const stockPageSize = ref(20)
const lastUpdate = ref(Date.now())
const selectedStock = ref<any>(null)  // 选中的个股

// DOM 引用
const treeContentRef = ref<HTMLElement>()
const tableWrapperRef = ref<HTMLElement>()

// ========== 辅助函数 ==========
// 显示 Toast 消息
function showToast(message: string, type: 'success' | 'error' | 'warning' | 'info' = 'info') {
  EventManager.emit(AppEvents.UI.TOAST, {
    message,
    type,
    duration: 2000
  })
}

// ========== 方法 ==========
async function selectTheme(theme: any, forceRefresh = false) {
  selectedStock.value = null
  // 如果不是强制刷新，检查是否正在加载或已经是当前题材
  if (!forceRefresh) {
    if (loadingTheme.value === theme.id) return
    if (selectedTheme.value?.id === theme.id) return
  } else {
    // 强制刷新时，如果正在加载同一个题材，先重置 loading 状态
    if (loadingTheme.value === theme.id) {
      loadingTheme.value = null
    }
  }

  selectedTheme.value = theme
  stockPage.value = 1
  stockSearch.value = ''

  loadingTheme.value = theme.id

  try {
    // 分析联动数据，传入 force 参数
    await themeCorrelationAnalyzer.analyzeThemeCorrelation(theme.id, theme.name, { force: forceRefresh })

    // 强制触发视图更新
    await nextTick()

    lastUpdate.value = Date.now()

    if (forceRefresh) {
      debugLog(`[ThemeCorrelationPanel] 强制刷新完成: ${theme.name}`)
      showToast(`刷新成功: ${theme.name}`, 'success')
    }
  } catch (error) {
    console.error('[ThemeCorrelationPanel] 加载联动数据失败:', error)
    if (forceRefresh) {
      showToast(`刷新失败: ${theme.name}`, 'error')
    }
    throw error
  } finally {
    loadingTheme.value = null
  }
}

// ✅ 刷新函数
async function refresh() {
  if (!selectedTheme.value) {
    showToast('请先选择一个题材', 'warning')
    return
  }

  if (refreshing.value) {
    showToast('正在刷新中，请稍候...', 'info')
    return
  }

  refreshing.value = true
  showToast(`正在刷新 ${selectedTheme.value.name} 联动数据...`, 'info')

  try {
    await selectTheme(selectedTheme.value, true)
  } catch (error) {
    // 错误已在 selectTheme 中处理
  } finally {
    refreshing.value = false
  }
}

function close() {
  emit('close')
}

function setSort(field: string) {
  if (sortBy.value === field) {
    sortDesc.value = !sortDesc.value
  } else {
    sortBy.value = field
    sortDesc.value = true
  }
  stockPage.value = 1
}

async function selectStock(stock: any) {
  // 获取完整的 jxbk 数据
  const jxbkStock = dataLayer.getJxbkStock(stock.code)

  // 合并数据
  const fullStock = {
    ...stock,
    // 从 jxbk 补充数据
    price: (jxbkStock as any)?.price || 0,
    volumeRatio: jxbkStock?.volumeRatio || 0,
    popularity: jxbkStock?.popularity || 0,
    popularityChange: jxbkStock?.popularityChange || 0,
    mainBuy: jxbkStock?.mainBuy || 0,
    mainSell: jxbkStock?.mainSell || 0,
    fengdan: jxbkStock?.fengdan || 0,
    maxFengdan: jxbkStock?.maxFengdan || 0,
    bigMoney300: jxbkStock?.bigMoney300 || 0,
    cirMV: jxbkStock?.cirMV || 0,
    // 联动数据保留
    avgCorrelation: stock.avgCorrelation,
    leaderCorrelation: stock.leaderCorrelation,
    directionConsistency: stock.directionConsistency,
    changeDiff: stock.changeDiff,
    role: stock.role,
  }

  selectedStock.value = fullStock
  const uiStore = useUIStore()
  uiStore.selectStock(stock.code)
  emit('select-stock', stock.code)
}

/** 格式化人气排名变动 */
function formatPopularityChange(change: number): string {
  if (!change && change !== 0) return '--'
  if (change > 0) {
    return `↑${change}`
  } else if (change < 0) {
    return `↓${Math.abs(change)}`
  }
  return '→0'
}

/** 获取人气变动颜色类 */
function getPopularityChangeClass(change: number): string {
  if (!change) return ''
  if (change > 0) return 'popularity-up'   // 排名上升（数值为正，表示人气上升）
  if (change < 0) return 'popularity-down' // 排名下降
  return 'popularity-steady'
}

function getStrengthClass(strength: number): string {
  if (strength >= 4000) return 's'
  if (strength >= 3000) return 'a'
  if (strength >= 2000) return 'b'
  if (strength >= 1000) return 'c'
  return 'd'
}

function formatStrength(strength: number): string {
  if (strength >= 4000) return 'S'
  if (strength >= 3000) return 'A'
  if (strength >= 2000) return 'B'
  if (strength >= 1000) return 'C'
  return 'D'
}

function getCorrelationColor(value: number = 0): string {
  if (value > 0.7) return '#ff4757'
  if (value > 0.4) return '#f39c12'
  if (value > 0.2) return '#3498db'
  return '#7f8c8d'
}

function getConsistencyColor(value: number): string {
  if (value > 0.8) return '#ff7f50'  // 珊瑚橙
  if (value > 0.6) return '#f39c12'  // 橙色
  return '#95a5a6'                   // 灰色
}

function getRoleName(role: string): string {
  const map: Record<string, string> = {
    leader: '龙头',
    follower: '跟风',
    independent: '独立'
  }
  return map[role] || role
}

function getStockRowClass(stock: any): string {
  const classes = []
  if (stock.role === 'leader') classes.push('leader-row')
  if (stock.avgCorrelation > 0.7) classes.push('high-correlation')
  return classes.join(' ')
}

function getDiffClass(value: number): string {
  if (value < 5) return 'diff-low'      // 差异小于5%
  if (value < 10) return 'diff-mid'     // 差异5%-10%
  return 'diff-high'                    // 差异大于10%
}

function formatTime(timestamp: number) {
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
}

/** 格式化价格 */
function formatPrice(price: number): string {
  if (!price && price !== 0) return '--'
  return price.toFixed(2)
}

/** 获取价格颜色类 */
function getPriceClass(price: number): string {
  if (!price) return ''
  return price > 0 ? 'price-up' : 'price-down'
}

/** 格式化量比 */
function formatVolumeRatio(ratio: number): string {
  if (!ratio && ratio !== 0) return '--'
  return ratio.toFixed(2)
}

/** 格式化人气值 */
function formatPopularity(popularity: number): string {
  if (!popularity && popularity !== 0) return '--'
  if (Math.abs(popularity) >= 10000) {
    return (popularity / 10000).toFixed(1) + 'w'
  }
  return popularity.toFixed(0)
}

/** 获取变动颜色类 */
function getChangeDiffClass(diff: number): string {
  if (!diff) return ''
  return diff >= 0 ? 'up' : 'down'
}

/** 格式化变动值 */
function formatChangeDiff(diff: number): string {
  if (!diff && diff !== 0) return '--'
  return (diff > 0 ? '+' : '') + diff.toFixed(0)
}

/**
* 格式化大单金额（300W级别，自动判断单位）
*/
function formatLargeOrder(amount: number): string {
  if (!amount && amount !== 0) return '--'

  const absAmount = Math.abs(amount)
  const sign = amount > 0 ? '' : '-'

  // 如果数值过大（> 10^8），说明是元为单位，转成亿
  if (absAmount > 100000000) {
    const yi = absAmount / 100000000
    return sign + yi.toFixed(1).replace(/\.?0+$/, '') + '亿'
  }

  // 如果数值大于1万，说明是元为单位，转成万
  if (absAmount >= 10000) {
    const wan = absAmount / 10000
    if (wan >= 10000) {
      return sign + (wan / 10000).toFixed(1).replace(/\.?0+$/, '') + '亿'
    }
    return sign + wan.toFixed(0) + '万'
  }

  // 小于1万，直接显示元
  return sign + absAmount.toFixed(0) + '元'
}

/**
* 格式化流通市值（自动判断单位）
*/
function formatCirculatingMarketCap(value: number): string {
  if (!value && value !== 0) return '--'

  const absValue = Math.abs(value)

  // 如果数值过大（> 10^8），说明是元为单位，转成亿
  if (absValue > 100000000) {
    const yi = absValue / 100000000
    return yi.toFixed(1).replace(/\.?0+$/, '') + '亿'
  }

  // 如果数值大于1万，说明是元为单位，转成万
  if (absValue >= 10000) {
    const wan = absValue / 10000
    if (wan >= 10000) {
      return (wan / 10000).toFixed(1).replace(/\.?0+$/, '') + '亿'
    }
    return wan.toFixed(0) + '万'
  }

  // 小于1万，直接显示元
  return absValue.toFixed(0) + '元'
}

/**
 * 格式化封单额（自动判断单位）
 * 输入：可能是元或万元，自动判断
 */
function formatFengdan(fengdan: number): string {
  if (!fengdan && fengdan !== 0) return '--'

  // 如果数值过大（> 10^8），说明可能是以元为单位
  if (Math.abs(fengdan) > 100000000) {
    const yi = fengdan / 100000000
    return yi.toFixed(2).replace(/\.?0+$/, '') + '亿'
  }

  // 如果数值大于1万，说明可能是以元为单位，转成万
  if (Math.abs(fengdan) >= 10000) {
    const wan = fengdan / 10000
    if (Math.abs(wan) >= 10000) {
      return (wan / 10000).toFixed(2).replace(/\.?0+$/, '') + '亿'
    }
    return wan.toFixed(0) + '万'
  }

  // 小于1万，直接显示元
  return fengdan.toFixed(0) + '元'
}

/**
 * 格式化金额（主力买入/卖出等，自动判断单位）
 */
function formatMoney(value: number): string {
  if (!value && value !== 0) return '--'

  const absValue = Math.abs(value)
  const sign = value > 0 ? '' : '-'

  // 如果数值过大（> 10^8），说明是元为单位，转成亿
  if (absValue > 100000000) {
    const yi = absValue / 100000000
    return sign + yi.toFixed(1).replace(/\.?0+$/, '') + '亿'
  }

  // 如果数值大于1万，说明是元为单位，转成万
  if (absValue >= 10000) {
    const wan = absValue / 10000
    if (wan >= 10000) {
      return sign + (wan / 10000).toFixed(1).replace(/\.?0+$/, '') + '亿'
    }
    return sign + wan.toFixed(0) + '万'
  }

  // 小于1万，直接显示元
  return sign + absValue.toFixed(0) + '元'
}

function getLeaderScoreClass(score: number): string {
  if (score >= 100) return 'leader-score-high'
  if (score >= 50) return 'leader-score-mid'
  return 'leader-score-low'
}

function getConfidenceClass(confidence: number): string {
  if (confidence >= 80) return 'confidence-high'
  if (confidence >= 50) return 'confidence-mid'
  return 'confidence-low'
}

// ========== 预加载热门题材 ==========
const PRELOAD_COUNT = 10
let preloadExecuted = false

async function preloadHotThemes() {
  if (preloadExecuted) return
  if (preloading.value) return

  preloadExecuted = true
  preloading.value = true

  const themes = allThemes.value
  const hotThemes = themes.slice(0, PRELOAD_COUNT)

  debugLog(`[ThemeCorrelationPanel] 开始预加载 ${hotThemes.length} 个热门题材...`)

  for (const theme of hotThemes) {
    try {
      const cached = dataLayer.getThemeCorrelation(theme.id)
      if (cached && Date.now() - cached.lastUpdate < 5 * 60 * 1000) {
        debugLog(`[ThemeCorrelationPanel] ${theme.name} 已有缓存，跳过`)
      } else {
        await themeCorrelationAnalyzer.analyzeThemeCorrelation(theme.id, theme.name)
        debugLog(`[ThemeCorrelationPanel] ✅ 预加载完成: ${theme.name}`)
      }
      preloadedCount.value++
    } catch (error) {
      console.error(`[ThemeCorrelationPanel] ❌ 预加载失败: ${theme.name}`, error)
    }
  }

  debugLog(`[ThemeCorrelationPanel] 🎉 预加载完成，共 ${preloadedCount.value} 个题材`)
  preloading.value = false
}

// ========== 计算属性 ==========
const allThemes = computed(() => {
  const jxbkBlocks = themeFacade.getJxbkBlocks()
  const stockMap = themeFacade.getThemeStockMap()
  const rotation = themeFacade.getRotationSummary() || dataLayer.getCurrentRotation()
  const mainLineIds = new Set((rotation?.mainLines || []).map(m => m.themeId))

  const result = jxbkBlocks.map(block => {
    const stockCount = Object.values(stockMap).filter((stock: any) =>
      stock.blocks?.includes(block.name)
    ).length

    const correlation = dataLayer.getThemeCorrelation(block.code)

    return {
      id: block.code,
      name: block.name,
      strength: block.strength || 0,
      change: block.change || 0,
      stockCount,
      correlation: correlation?.overallCorrelation || 0,
      isHot: false,
      isMainLine: mainLineIds.has(block.code),
    }
  }).sort((a, b) => b.strength - a.strength)

  return result
})

const filteredThemes = computed(() => {
  let result = allThemes.value
  if (treeSearch.value) {
    const keyword = treeSearch.value.toLowerCase()
    result = result.filter(t =>
      t.name.toLowerCase().includes(keyword) ||
      t.id.toLowerCase().includes(keyword)
    )
  }
  return result
})

const paginatedThemes = computed(() => {
  const filtered = filteredThemes.value
  if (!filtered || filtered.length === 0) return []

  const start = (treePage.value - 1) * pageSize.value
  if (start >= filtered.length) {
    treePage.value = 1
    return filtered.slice(0, pageSize.value)
  }
  return filtered.slice(start, start + pageSize.value)
})

const treeTotalPages = computed(() =>
  Math.ceil(filteredThemes.value.length / pageSize.value)
)

const themeCorrelation = computed(() => {
  if (!selectedTheme.value) return null
  return dataLayer.getThemeCorrelation(selectedTheme.value.id)
})

const themeStocks = computed(() => {
  if (!selectedTheme.value || !themeCorrelation.value) return []
  const stocks = themeCorrelation.value.stocks || new Map()
  return Array.from(stocks.values())
})

const filteredStocks = computed(() => {
  let result = [...themeStocks.value]

  if (detailView.value !== 'all') {
    result = result.filter(s => s.role === detailView.value)
  }

  if (stockSearch.value) {
    const keyword = stockSearch.value.toLowerCase()
    result = result.filter(s =>
      s.code.toLowerCase().includes(keyword) ||
      s.name.toLowerCase().includes(keyword)
    )
  }

  result.sort((a, b) => {
    const aVal = Number(a[sortBy.value as keyof typeof a]) || 0
    const bVal = Number(b[sortBy.value as keyof typeof b]) || 0
    return sortDesc.value ? bVal - aVal : aVal - bVal
  })

  return result
})

const paginatedStocks = computed(() => {
  const start = (stockPage.value - 1) * stockPageSize.value
  return filteredStocks.value.slice(start, start + stockPageSize.value)
})

const stockTotalPages = computed(() =>
  Math.ceil(filteredStocks.value.length / stockPageSize.value)
)

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible) {
    setTimeout(() => {
      preloadHotThemes()
    }, 500)
  }
})

watch(allThemes, (themes) => {
  if (themes.length > 0 && props.visible && !preloading.value) {
    setTimeout(() => {
      preloadHotThemes()
    }, 1000)
  }
}, { immediate: false })
</script>

<style scoped>
/* 嵌入模式样式 */
.correlation-panel.embedded {
  position: relative;
  width: 100%;
  height: 100%;
  border: none;
  box-shadow: none;
  background: transparent;
  display: flex;
  flex-direction: column;
}

.correlation-panel.embedded .panel-header.embedded-header {
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color);
  border-radius: 8px 8px 0 0;
}

.correlation-panel.embedded .panel-footer.embedded-footer {
  padding: 8px 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-color);
  border-radius: 0 0 8px 8px;
}

.correlation-panel.embedded .panel-content {
  flex: 1;
  padding: 16px;
  max-height: none;
  background: var(--bg-secondary);
}

.correlation-panel {
  position: fixed;
  width: 1200px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10010;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 12px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-icon {
  font-size: 24px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}

.btn-icon.close:hover {
  background: rgba(255, 71, 87, 0.1);
  color: #ff4757;
  border-color: #ff4757;
}

.rotating {
  animation: rotate 1s infinite linear;
  display: inline-block;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.panel-content {
  flex: 1;
  padding: 20px;
  overflow: hidden;
  max-height: calc(85vh - 120px);
}

.loading-overlay {
  position: absolute;
  top: 60px;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
  border-radius: 0 0 16px 16px;
  gap: 12px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.content-blur {
  filter: blur(2px);
  opacity: 0.6;
  pointer-events: none;
}

.split-layout {
  display: flex;
  height: 100%;
  gap: 20px;
}

/* 左侧题材树 */
.left-tree {
  width: 320px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.tree-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.tree-header h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--text-title);
}

.tree-search {
  margin-bottom: 8px;
  width: 100px;
}

.tree-search .search-input {
  width: 100%;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
}


.tree-stats {
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}

.badge {
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--color-highlight);
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.tree-node {
  padding: 12px;
  margin-bottom: 8px;
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

.tree-node.loading {
  opacity: 0.6;
  pointer-events: none;
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.node-name {
  font-weight: 500;
  color: var(--text-primary);
  font-size: 13px;
}

.node-badges {
  display: flex;
  gap: 4px;
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

.stock-count {
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 10px;
  font-size: 10px;
  color: var(--text-secondary);
}

.node-metrics {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-bottom: 6px;
}

.correlation-badge {
  padding: 2px 8px;
  border-radius: 10px;
  color: white;
  font-weight: 500;
  background: #95a5a6;
}

.change.up {
  color: #ff4757;
}

.change.down {
  color: #2ed573;
}

.node-progress {
  height: 3px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

.tree-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 12px;
}

.tree-pagination button {
  padding: 4px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
}

.tree-pagination button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 右侧详情 */
.right-detail {
  flex: 1;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.theme-overview {
  padding: 16px;
  border-left: 4px solid transparent;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-color);
}

.overview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.overview-header h4 {
  margin: 0;
  font-size: 16px;
  color: var(--text-title);
}

.overview-stats {
  display: flex;
  gap: 20px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.stat-value {
  font-size: 16px;
  font-weight: bold;
}

/* 龙头卡片样式 */
.leader-card {
  margin-top: 8px;
  padding: 12px;
  background: linear-gradient(135deg, rgba(255, 215, 0, 0.1) 0%, rgba(255, 127, 80, 0.05) 100%);
  border-radius: 10px;
  border: 1px solid rgba(255, 215, 0, 0.3);
}

.leader-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed rgba(255, 215, 0, 0.3);
}

.leader-icon {
  font-size: 16px;
}

.leader-title {
  font-size: 11px;
  background: rgba(255, 215, 0, 0.2);
  padding: 2px 8px;
  border-radius: 12px;
  color: #ffd700;
}

.leader-name {
  font-size: 14px;
  font-weight: bold;
  color: #ffd700;
}

.leader-code {
  font-size: 11px;
  color: var(--text-secondary);
}

/* 指标组 */
.leader-stats,
.leader-funds {
  margin-bottom: 10px;
}

.stat-group,
.fund-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
}

.stat-item,
.fund-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 65px;
}

.stat-label,
.fund-label {
  font-size: 9px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.stat-value,
.fund-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.stat-value.up,
.fund-value.up {
  color: #ff4757;
}

.stat-value.down,
.fund-value.down {
  color: #2ed573;
}

/* 板块统计卡片 */
.stats-card {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.stats-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  font-size: 11px;
}

.stats-label {
  font-weight: bold;
  color: var(--text-primary);
}

.stats-item {
  color: var(--text-secondary);
}

/* 整体联动数值 */
.theme-overview .stat-value {
  font-size: 16px;
  font-weight: bold;
}

.theme-overview .stat-label {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  margin-bottom: 2px;
}

.detail-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.tab-btn {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.tab-btn.active {
  background: var(--color-highlight);
  border-color: var(--color-highlight);
  color: #000;
}

/* 调整表格控制区域布局 */
.table-controls {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  align-items: center;
}

.search-box {
  width: 200px;
  flex: none;
}

.search-box .search-input {
  width: 100%;
  padding: 6px 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
}

.sort-controls {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.sort-select {
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
}

.sort-btn {
  padding: 4px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}

.table-wrapper {
  overflow-x: auto;
  margin: 0 -16px;
  padding: 0 16px;
  flex: 1;
  min-height: 200px;
}

.stock-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 12px;
  color: var(--text-secondary);
}

.loading-spinner-small {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.correlation-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  table-layout: fixed;
}

.correlation-table th {
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  padding: 10px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  cursor: pointer;
  z-index: 2;
}

.correlation-table td {
  padding: 6px 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.correlation-table td:nth-child(5),
.correlation-table td:nth-child(6),
.correlation-table td:nth-child(7),
.correlation-table td:nth-child(8),
.correlation-table td:nth-child(9) {
  text-align: right;
}

.correlation-table td:nth-child(10) {
  text-align: center;
}

.correlation-table tbody tr {
  cursor: pointer;
  transition: background 0.2s;
}

.correlation-table tbody tr:hover {
  background: var(--bg-hover);
}

.correlation-table tbody tr.leader-row {
  background: rgba(255, 215, 0, 0.1);
}

.correlation-table tbody tr.high-correlation {
  border-left: 3px solid #ff4757;
}

.code-link {
  color: var(--color-highlight);
  text-decoration: underline;
  cursor: pointer;
}

.role-badge {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
  color: white;
}

.role-badge.role-leader {
  background: #ffd700;
  color: #000;
}

.role-badge.role-follower {
  background: #3498db;
}

.role-badge.role-independent {
  background: #7f8c8d;
}

.up {
  color: #ff4757;
  font-weight: 500;
}

.down {
  color: #2ed573;
  font-weight: 500;
}

.consistency-text {
  font-weight: 500;
  font-size: 12px;
}

.diff-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
}

.diff-badge.diff-low {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
}

.diff-badge.diff-mid {
  background: rgba(255, 165, 2, 0.2);
  color: #f39c12;
}

.diff-badge.diff-high {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.btn-icon-small {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  font-size: 14px;
}

.btn-icon-small:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

.table-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.table-pagination button {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
}

.table-pagination button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.empty-selection {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  min-height: 400px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 11px;
  color: var(--text-secondary);
}

.update-time {
  font-family: monospace;
}

.preload-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--bg-secondary);
  padding: 4px 12px;
  font-size: 10px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
  border-top: 1px solid var(--border-color);
  z-index: 20;
}

.preload-bar {
  height: 2px;
  background: var(--color-highlight);
  transition: width 0.3s ease;
  position: absolute;
  top: 0;
  left: 0;
}

/* 主线标识样式 */
.mainline-badge {
  font-size: 9px;
  background: linear-gradient(135deg, #ff4757, #ff7f50);
  color: white;
  padding: 2px 6px;
  border-radius: 12px;
  margin-left: 6px;
  font-weight: normal;
  display: inline-block;
  vertical-align: middle;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* 选中状态下主线标识 */
.tree-node.selected .mainline-badge {
  background: linear-gradient(135deg, #ff7f50, #ffa500);
}

/* 新增：多行指标布局 */
.leader-metrics-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.leader-metrics-row:first-of-type {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}

/* 当有两行以上时，第一行不需要上边框 */
.leader-metrics+.leader-metrics-row {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

/* 新增指标数值样式 */
.metric-value .price-up {
  color: #ff4757;
}

.metric-value .price-down {
  color: #2ed573;
}

/* 人气变动样式 */
.popularity-up {
  color: #ff4757;
  /* 红色表示人气上升 */
}

.popularity-down {
  color: #2ed573;
  /* 绿色表示人气下降 */
}

.popularity-steady {
  color: var(--text-secondary);
}

/* 联动指标组 */
.leader-correlation {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(255, 215, 0, 0.3);
}

.correlation-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
}

.correlation-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 65px;
}

.correlation-label {
  font-size: 9px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.correlation-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}
</style>
