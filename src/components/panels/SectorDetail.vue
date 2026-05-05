<!-- src/components/panels/SectorDetail.vue -->
<!-- 纯响应式版本：使用真实的 jxbk 数据 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="sector-detail-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <button class="back-btn" @click.stop="goBack">← 返回</button>
          <h3>
            📊 {{ sectorName || '题材详情' }}
            <span class="version-badge">v{{ version }}</span>
          </h3>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" @click.stop="refresh" :class="{ loading }" :disabled="loading" title="刷新">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" @click.stop="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 标签页 - 添加历史趋势 -->
      <div class="tabs-left">
        <button class="tab-btn" :class="{ active: view === 'overview' }" @click="view = 'overview'">
          📈 概览
        </button>
        <button class="tab-btn" :class="{ active: view === 'stocks' }" @click="view = 'stocks'">
          📊 成分股
          <span v-if="themeStocks.length" class="tab-count">{{ themeStocks.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: view === 'correlation' }" @click="view = 'correlation'">
          🔗 联动分析
          <span v-if="correlationThemes.length" class="tab-count">{{ correlationThemes.length }}</span>
        </button>
        <!-- ✅ 新增：历史趋势标签页 -->
        <button class="tab-btn" :class="{ active: view === 'history' }" @click="view = 'history'">
          📅 历史趋势
        </button>
      </div>

      <!-- 内容区域 -->
      <div class="panel-content" ref="contentRef">
        <!-- 加载状态 -->
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <span>{{ loadingMessage }}</span>
        </div>

        <!-- 错误状态 -->
        <div v-else-if="error" class="error-state">
          <span class="error-icon">⚠️</span>
          <span>{{ error }}</span>
          <button class="retry-btn" @click="loadData">重试</button>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!hasThemeData" class="empty-state">
          <div class="empty-icon">📊</div>
          <div class="empty-text">暂无题材数据</div>
        </div>

        <template v-else>
          <!-- 概览视图 -->
          <div v-if="view === 'overview'" class="overview-view">
            <!-- 基础信息 -->
            <div class="info-card">
              <div class="info-row">
                <span class="info-label">板块名称</span>
                <span class="info-value">{{ sectorName }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">更新时间</span>
                <span class="info-value">{{ formatTime(displayLastUpdate) }}</span>
              </div>
            </div>

            <!-- ✅ 真实数据卡片 -->
            <div class="metrics-grid">
              <div class="metric-card strength-card">
                <div class="metric-icon">💪</div>
                <div class="metric-content">
                  <div class="metric-label">板块强度</div>
                  <div class="metric-value" :style="{ color: getStrengthColor(blockData?.strength || 0) }">
                    {{ blockData?.strength || 0 }}
                  </div>
                  <div class="metric-level" :class="`strength-${getStrengthLevel(blockData?.strength || 0)}`">
                    {{ getStrengthLevelText(blockData?.strength || 0) }}
                  </div>
                </div>
              </div>

              <div class="metric-card zt-card">
                <div class="metric-icon">📈</div>
                <div class="metric-content">
                  <div class="metric-label">涨停数量</div>
                  <div class="metric-value" style="color: #ff4757">
                    {{ displayZtCount }}
                  </div>
                  <div class="metric-desc">今日涨停</div>
                </div>
              </div>

              <div class="metric-card change-card">
                <div class="metric-icon">📊</div>
                <div class="metric-content">
                  <div class="metric-label">板块涨幅</div>
                  <div class="metric-value" :class="(blockData?.change || 0) >= 0 ? 'up' : 'down'">
                    {{ (blockData?.change || 0) > 0 ? '+' : '' }}{{ blockData?.change?.toFixed(2) || '0.00' }}%
                  </div>
                  <div class="metric-desc">平均涨幅</div>
                </div>
              </div>

              <div class="metric-card volume-card">
                <div class="metric-icon">📊</div>
                <div class="metric-content">
                  <div class="metric-label">量比</div>
                  <div class="metric-value" :style="{ color: getVolumeRatioColor(blockData?.volumeRatio || 0) }">
                    {{ blockData?.volumeRatio?.toFixed(2) || '0.00' }}
                  </div>
                  <div class="metric-desc">{{ getVolumeRatioDesc(blockData?.volumeRatio || 0) }}</div>
                </div>
              </div>
            </div>

            <!-- ✅ 资金数据 -->
            <div class="funds-grid">
              <div class="fund-card">
                <div class="fund-icon">💰</div>
                <div class="fund-content">
                  <div class="fund-label">主力净额</div>
                  <div class="fund-value" :class="(blockData?.mainNetInflow || 0) >= 0 ? 'inflow' : 'outflow'">
                    {{ formatMoney(blockData?.mainNetInflow || 0) }}
                  </div>
                </div>
              </div>

              <div class="fund-card">
                <div class="fund-icon">💎</div>
                <div class="fund-content">
                  <div class="fund-label">300W大单</div>
                  <div class="fund-value" :class="(blockData?.bigMoney300 || 0) >= 0 ? 'inflow' : 'outflow'">
                    {{ formatMoney(blockData?.bigMoney300 || 0) }}
                  </div>
                </div>
              </div>

              <div class="fund-card">
                <div class="fund-icon">🏦</div>
                <div class="fund-content">
                  <div class="fund-label">机构增仓</div>
                  <div class="fund-value" :class="(blockData?.institutionBuy || 0) >= 0 ? 'inflow' : 'outflow'">
                    {{ formatMoney(blockData?.institutionBuy || 0) }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 统计卡片（从股票数据计算） -->
            <div class="stats-grid">
              <div class="stat-card">
                <span class="stat-icon">📊</span>
                <span class="stat-value">{{ themeStockCount }}</span>
                <span class="stat-label">成分股</span>
              </div>
              <div class="stat-card">
                <span class="stat-icon">📈</span>
                <span class="stat-value">{{ themeZtCount }}</span>
                <span class="stat-label">涨停股</span>
              </div>
              <div class="stat-card">
                <span class="stat-icon">👑</span>
                <span class="stat-value">{{ themeLeaderCount }}</span>
                <span class="stat-label">龙头股</span>
              </div>
              <div class="stat-card">
                <span class="stat-icon">📅</span>
                <span class="stat-value">{{ themeTotalContinuousDays }}</span>
                <span class="stat-label">连板天数</span>
              </div>
            </div>

            <!-- 龙头股 -->
            <div class="leaders-section" v-if="themeLeaders.length">
              <div class="section-header">
                <span class="section-title">👑 龙头股</span>
                <span class="section-count">{{ themeLeaders.length }}</span>
              </div>
              <div class="leaders-list">
                <div v-for="(leader, index) in themeLeaders.slice(0, 5)" :key="leader.code" class="leader-item"
                  @click.stop="selectStock(leader.code)">
                  <div class="leader-rank">{{ index + 1 }}</div>
                  <div class="leader-info">
                    <span class="leader-name">{{ leader.name }}</span>
                    <span class="leader-level"
                      :style="{ color: leader.levelColor, background: leader.levelColor + '20' }">
                      {{ leader.levelIcon }} {{ leader.level }}
                    </span>
                  </div>
                  <div class="leader-metrics">
                    <span class="leader-change" :class="getChangeClass(leader.change)">
                      {{ formatChange(leader.change) }}
                    </span>
                    <span v-if="leader.continuousDays > 1" class="leader-days">
                      {{ leader.continuousDays }}连板
                    </span>
                  </div>
                </div>
              </div>
              <div v-if="themeLeaders.length > 5" class="more-hint">
                等{{ themeLeaders.length - 5 }}只龙头...
              </div>
            </div>
          </div>

          <!-- 成分股视图 - 完整表格 -->
          <div v-if="view === 'stocks'" class="stocks-view">
            <div class="stocks-header">
              <div class="search-box">
                <input type="text" v-model="stockSearch" placeholder="搜索股票代码或名称..." class="search-input" />
                <span v-if="stockSearch" class="search-clear" @click="stockSearch = ''">✕</span>
              </div>
              <div class="sort-controls">
                <select v-model="sortBy" class="sort-select">
                  <option value="change">涨跌幅</option>
                  <option value="volumeRatio">量比</option>
                  <option value="mainNetInflow">主力净额</option>
                  <option value="bigMoney300">300W大单</option>
                  <option value="institutionBuy">机构增仓</option>
                  <option value="leadTimes">领次</option>
                  <option value="popularity">人气</option>
                  <option value="fengdan">封单额</option>
                  <option value="continuousDays">连板</option>
                  <option value="price">最新价</option>
                </select>
                <button class="sort-btn" @click="sortDesc = !sortDesc">
                  {{ sortDesc ? '↓ 降序' : '↑ 升序' }}
                </button>
              </div>
            </div>

            <div class="stocks-stats" v-if="filteredStocks.length">
              显示 {{ filteredStocks.length }} / {{ themeStocks.length }} 只股票
              <span v-if="filteredStocks.length !== themeStocks.length" class="filter-hint">
                (过滤后)
              </span>
            </div>

            <div class="stocks-table-container" v-if="filteredStocks.length">
              <table class="stocks-table">
                <thead>
                  <tr>
                    <th @click="setSort('rank')">#</th>
                    <th @click="setSort('code')">代码</th>
                    <th @click="setSort('name')">名称</th>
                    <th @click="setSort('change')">涨跌幅</th>
                    <th @click="setSort('volumeRatio')">量比</th>
                    <th @click="setSort('mainNetInflow')">主力净额</th>
                    <th @click="setSort('bigMoney300')">300W</th>
                    <th @click="setSort('institutionBuy')">机构</th>
                    <th @click="setSort('leadTimes')">领次</th>
                    <th>领涨状态</th>
                    <th @click="setSort('lianban')">连板</th>
                    <th @click="setSort('popularity')">人气</th>
                    <th @click="setSort('popularityChange')">变动</th>
                    <th>板块</th>
                    <th @click="setSort('fengdan')">封单</th>
                    <th @click="setSort('maxFengdan')">最大封</th>
                    <th @click="setSort('cirMV')">流通市值</th>
                    <th>标记</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="stock in paginatedStocks" :key="stock.code" :class="{
                    'zt-row': (stock.change || 0) > 9.5,
                    'leader-row': stock.isSectorLeader,
                  }" @click.stop="selectStock(stock.code)">
                    <td>{{ stock.rank }}</td>
                    <td><span class="code-link" @click.stop="linkToTdx(stock.code)">{{ stock.code }}</span></td>
                    <td>{{ stock.name || '-' }}</td>
                    <td :class="getChangeClass(stock.change)">
                      {{ stock.change > 0 ? '+' : '' }}{{ (stock.change || 0).toFixed(2) }}%
                    </td>
                    <td class="number">{{ (stock.volumeRatio || 0).toFixed(2) }}</td>
                    <td :class="getMoneyClass(stock.mainNetInflow)">
                      {{ formatMoney(stock.mainNetInflow) }}
                    </td>
                    <td :class="getMoneyClass(stock.bigMoney300)">
                      {{ formatMoney(stock.bigMoney300) }}
                    </td>
                    <td :class="getMoneyClass(stock.institutionBuy)">
                      {{ formatMoney(stock.institutionBuy) }}
                    </td>
                    <td class="number">{{ stock.leadTimes || '-' }}</td>
                    <td>
                      <span v-if="stock.leadStatus" class="lead-badge"
                        :class="{ 'poban': stock.leadStatus.includes('破板') }">
                        {{ stock.leadStatus }}
                      </span>
                      <span v-else>-</span>
                    </td>
                    <td>
                      <span v-if="stock.lianban" class="lianban-badge" :class="getLianbanClass(stock.lianban)">
                        {{ stock.lianban }}
                      </span>
                      <span v-else>-</span>
                    </td>
                    <td class="number">{{ stock.popularity || '-' }}</td>
                    <td :class="getPopularityChangeClass(stock.popularityChange)">
                      {{ formatPopularityChange(stock.popularityChange) }}
                    </td>
                    <td>
                      <div class="blocks-container">
                        <span v-for="block in (stock.blocks || []).slice(0, 2)" :key="block" class="block-tag">
                          {{ block }}
                        </span>
                        <span v-if="(stock.blocks?.length || 0) > 2" class="block-tag more">
                          +{{ (stock.blocks?.length || 0) - 2 }}
                        </span>
                      </div>
                    </td>
                    <td :class="getMoneyClass(stock.fengdan)">
                      {{ formatMoney(stock.fengdan) }}
                    </td>
                    <td :class="getMoneyClass(stock.maxFengdan)">
                      {{ formatMoney(stock.maxFengdan) }}
                    </td>
                    <td class="number">{{ formatMoney(stock.cirMV) }}</td>
                    <td>
                      <div class="badges">
                        <span v-if="stock.isSectorLeader" class="badge leader-badge" title="龙头">👑</span>
                        <span v-if="(stock.change || 0) > 9.5" class="badge zt-badge" title="涨停">📈</span>
                        <span v-if="stock.leadStatus?.includes('破板')" class="badge poban-badge" title="破板">💥</span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="filteredStocks.length > pageSize" class="pagination-container">
              <button class="page-btn" @click="currentPage--" :disabled="currentPage === 1">‹</button>
              <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
              <button class="page-btn" @click="currentPage++" :disabled="currentPage === totalPages">›</button>
            </div>

            <div v-if="filteredStocks.length === 0" class="empty-stocks">
              {{ stockSearch ? '无匹配股票' : '暂无成分股' }}
            </div>
          </div>

          <!-- 联动分析视图（保留原有功能） -->
          <div v-if="view === 'correlation'" class="correlation-view">
            <div class="correlation-card">
              <div class="correlation-header">
                <span class="correlation-title">题材内部联动性</span>
                <span class="correlation-value" :style="{ color: getCorrelationColor(themeSelfCorrelation) }">
                  {{ (themeSelfCorrelation * 100).toFixed(0) }}%
                </span>
              </div>
              <div class="correlation-bar">
                <div class="correlation-bar-fill" :style="{
                  width: (themeSelfCorrelation * 100) + '%',
                  background: getCorrelationColor(themeSelfCorrelation),
                }"></div>
              </div>
              <div class="correlation-level" :style="{ color: getCorrelationColor(themeSelfCorrelation) }">
                {{ correlationLevel }}
              </div>
              <div class="correlation-desc">
                {{ correlationDesc }}
              </div>
            </div>

            <div class="related-themes" v-if="correlationThemes.length">
              <div class="section-header">
                <span class="section-title">🔗 相关题材</span>
                <span class="section-count">{{ correlationThemes.length }}</span>
              </div>
              <div class="themes-list">
                <div v-for="theme in correlationThemes" :key="theme.id" class="theme-item"
                  @click.stop="selectTheme(theme.name)">
                  <div class="theme-info">
                    <span class="theme-name">{{ theme.name }}</span>
                    <span class="theme-badge" :class="`badge-${theme.level}`">
                      {{ theme.level }}
                    </span>
                  </div>
                  <div class="theme-metrics">
                    <div class="metric">
                      <span class="metric-label">相关性</span>
                      <span class="metric-value" :style="{ color: getCorrelationColor(theme.correlation) }">
                        {{ (theme.correlation * 100).toFixed(0) }}%
                      </span>
                    </div>
                  </div>
                  <div class="theme-progress">
                    <div class="progress-bar" :style="{
                      width: (theme.correlation * 100) + '%',
                      background: getCorrelationColor(theme.correlation)
                    }"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 历史趋势视图 -->
      <div v-if="view === 'history'" class="history-view">
        <div class="time-range-selector">
          <button class="time-btn" :class="{ active: timeRange === '1h' }" @click="setTimeRange('1h')">1小时</button>
          <button class="time-btn" :class="{ active: timeRange === '6h' }" @click="setTimeRange('6h')">6小时</button>
          <button class="time-btn" :class="{ active: timeRange === '1d' }" @click="setTimeRange('1d')">1天</button>
          <button class="time-btn" :class="{ active: timeRange === '1w' }" @click="setTimeRange('1w')">1周</button>
          <button class="time-btn" :class="{ active: timeRange === '1m' }" @click="setTimeRange('1m')">1月</button>
        </div>

        <div class="indicator-selector">
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('heat') }"
            @click="toggleIndicator('heat')">🔥 热度</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('zt') }"
            @click="toggleIndicator('zt')">📈 涨停</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('leader') }"
            @click="toggleIndicator('leader')">👑 龙头</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('change') }"
            @click="toggleIndicator('change')">💹 涨跌</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('volume') }"
            @click="toggleIndicator('volume')">📊 成交量</button>
        </div>

        <div class="history-chart" ref="chartRef"></div>

        <div class="history-stats-grid">
          <div class="history-stat-card">
            <div class="stat-label">最高热度</div>
            <div class="stat-value">{{ formatHeat(historyStats.max) }}</div>
            <div class="stat-time">{{ formatTime(historyStats.maxTime) }}</div>
          </div>
          <div class="history-stat-card">
            <div class="stat-label">最低热度</div>
            <div class="stat-value">{{ formatHeat(historyStats.min) }}</div>
            <div class="stat-time">{{ formatTime(historyStats.minTime) }}</div>
          </div>
          <div class="history-stat-card">
            <div class="stat-label">平均热度</div>
            <div class="stat-value">{{ formatHeat(historyStats.avg) }}</div>
            <div class="stat-trend" :class="historyStats.trend >= 0 ? 'up' : 'down'">
              {{ historyStats.trend > 0 ? '+' : '' }}{{ historyStats.trend.toFixed(1) }}
            </div>
          </div>
          <div class="history-stat-card">
            <div class="stat-label">涨停峰值</div>
            <div class="stat-value">{{ historyStats.maxZT }}</div>
            <div class="stat-time">{{ formatTime(historyStats.maxZTTime) }}</div>
          </div>
        </div>
      </div>

      <div class="panel-footer" v-if="hasThemeData && !loading">
        <span>📡 数据来源: jxbk</span>
        <span>🕒 {{ formatTime(displayLastUpdate) }}</span>
      </div>
    </div>
  </Teleport>

</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { dataLayer } from '../../services/DataLayer'
import { useStockStore } from '../../stores/stock'
import { useFavoriteStore } from '../../stores/favorite'
import { usePanel } from '../../composables/usePanel'
import * as echarts from 'echarts'
import { nextTick } from 'vue'
import { sectorAnalyzer } from '../../services/sectorAnalyzer'
import { themeFacade } from '../../services/theme/ThemeFacade'
import type { JxbkBlockData } from '../../types'

type DisplayBlockData = JxbkBlockData & {
  lastUpdate?: number | null
  history?: any[]
}

const props = defineProps<{
  visible: boolean
  sectorName: string
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'select-theme', themeName: string): void
}>()

const version = '6.0.0'
const view = ref<'overview' | 'stocks' | 'correlation' | 'history'>('overview')
const loading = ref(false)
const error = ref<string | null>(null)

const { panelRef, panelStyle } = usePanel({
  name: 'SectorDetail',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="题材分析"]', '.sector-card'],
  onClose: close,
})


const loadData = async () => {
  if (!props.sectorName) return

  loading.value = true
  error.value = null

  try {
    // 找到板块代码
    const blocks = themeFacade.getJxbkBlocksCompat()
    const block = blocks.find(b => b.name === props.sectorName)

    if (block) {
      // ✅ 关键：强制刷新加载板块个股数据
      // 传入 true 作为 forceRefresh 参数，跳过缓存
      if (sectorAnalyzer && typeof sectorAnalyzer.loadSectorStocks === 'function') {
        await sectorAnalyzer.loadSectorStocks(block.code, props.sectorName, true)
      }

      await themeFacade.refreshJxbkAndFactors({ force: true })
    }

    // 验证数据是否存在
    if (!hasThemeData.value) {
      error.value = `板块不存在或暂无数据: ${props.sectorName}`
    }
  } catch (err) {
    console.error('[SectorDetail] 加载数据失败:', err)
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

// ========== 安全获取 dataLayer 方法 ==========
const safeDataLayer = {
  getJxbkBlock: (code: string) => {
    try {
      return (dataLayer as any).getJxbkBlock?.(code)
    } catch {
      return null
    }
  },
  getJxbkBlockByName: (name: string) => {
    try {
      const blocks = themeFacade.getJxbkBlocksCompat()
      return blocks.find((b: any) => b?.name === name)
    } catch {
      return null
    }
  }
}

// ========== 核心数据 - 从 dataLayer 获取 jxbk 数据 ==========

// 先通过名称找到对应的板块代码
const blockCode = computed(() => {
  if (!props.sectorName) return null

  try {
    const blocks = themeFacade.getJxbkBlocksCompat()
    const block = blocks.find((b: any) => b?.name === props.sectorName)
    return block?.code || null
  } catch (e) {
    console.warn('[SectorDetail] 获取blockCode失败:', e)
    return null
  }
})

// 获取板块的 jxbk 数据（通过 code）
const blockData = computed(() => {
  if (!blockCode.value) return null

  try {
    // 获取板块数据
    const blocks = themeFacade.getJxbkBlocksCompat()
    const block = blocks.find((b: any) => b?.code === blockCode.value)

    if (block) {
      return {
        ...block,
        lastUpdate: (block as DisplayBlockData).lastUpdate || Date.now()
      } as DisplayBlockData
    }
    return null
  } catch (e) {
    console.warn('[SectorDetail] 获取blockData失败:', e)
    return null
  }
})

// 或者从 dataLayer 的 jxbk 更新时间获取
const jxbkLastUpdate = computed(() => {
  try {
    return themeFacade.getJxbkLastUpdate()
  } catch {
    return null
  }
})

// 显示用的更新时间（优先使用板块自身的，否则使用全局的）
const displayLastUpdate = computed(() => {
  return blockData.value?.lastUpdate || jxbkLastUpdate.value || null
})


// 获取板块内的股票（从 jxbk stockMap 中过滤）
const themeStocks = computed(() => {
  if (!props.sectorName) return []

  try {
    const stockMap = themeFacade.getThemeStockMapCompat()

    const stocks = Object.values(stockMap)
      .filter((stock: any) => {
        return stock?.blocks?.some((b: string) => b === props.sectorName)
      })
      .map((stock: any, index: number) => ({
        rank: index + 1,
        code: stock.code || '',
        name: stock.name || '',
        change: stock.change || 0,
        volumeRatio: stock.volumeRatio || 0,
        mainNetInflow: stock.mainNetInflow || 0,
        bigMoney300: stock.bigMoney300 || 0,
        institutionBuy: stock.institutionBuy || 0,
        leadTimes: stock.leadTimes || 0,
        leadStatus: stock.leadStatus || '',
        lianban: stock.lianban || '',
        popularity: stock.popularity || 0,
        popularityChange: stock.popularityChange || 0,
        blocks: stock.blocks || [],
        fengdan: stock.fengdan || 0,
        maxFengdan: stock.maxFengdan || 0,
        cirMV: stock.cirMV || 0,
        isSectorLeader: stock.leadStatus?.includes('龙') || false,
        continuousDays: stock.lianban ? (parseInt(stock.lianban) || 1) : 1,
      }))
      .sort((a, b) => {
        const getLeaderRank = (status: string) => {
          if (!status) return 999
          const match = status.match(/龙(\d+)/)
          if (match) return parseInt(match[1])
          if (status.includes('首板')) return 100
          return 999
        }
        return getLeaderRank(a.leadStatus) - getLeaderRank(b.leadStatus)
      })

    return stocks
  } catch (e) {
    console.warn('[SectorDetail] 获取themeStocks失败:', e)
    return []
  }
})

const hasThemeData = computed(() => blockData.value !== null || themeStocks.value.length > 0)

// 统计指标
const themeStockCount = computed(() => themeStocks.value.length)

// 涨停股数量 - 优先使用 blockData 的 ztCount，如果为0则从股票列表统计
const displayZtCount = computed(() => {
  if (blockData.value?.ztCount && blockData.value.ztCount > 0) {
    return blockData.value.ztCount
  }
  return themeStocks.value.filter(s => (s.change || 0) > 9.5).length
})

const themeZtCount = displayZtCount

const themeLeaderCount = computed(() => themeLeaders.value.length)

const themeTotalContinuousDays = computed(() =>
  themeStocks.value.reduce((sum, s) => {
    const days = s.lianban ? (parseInt(s.lianban) || 0) : 0
    return sum + days
  }, 0)
)

// 龙头股
const themeLeaders = computed(() => {
  return themeStocks.value
    .filter(stock => stock.leadStatus && (stock.leadStatus.includes('龙') || stock.leadStatus.includes('首板')))
    .map(stock => ({
      code: stock.code,
      name: stock.name,
      change: stock.change,
      continuousDays: stock.lianban ? (parseInt(stock.lianban) || 1) : 1,
      level: stock.leadStatus,
      levelIcon: stock.leadStatus.includes('龙') ? '👑' : '🌱',
      levelColor: stock.leadStatus.includes('龙') ? '#ffd700' : '#4ade80',
    }))
})

// ========== 从 metrics 获取联动分析数据 ==========

// 获取题材的 metrics 数据
const themeMetrics = computed(() => {
  if (!blockCode.value) return null

  try {
    // 尝试通过板块代码获取 metrics
    const metrics = (dataLayer as any).getThemeMetrics?.(blockCode.value)
    if (metrics) return metrics

    // 如果通过代码没找到，尝试通过名称在所有 metrics 中查找
    const state = (dataLayer as any).state
    const allMetrics = state?.theme?.metrics?.byTheme || new Map()
    for (const [id, metric] of allMetrics.entries()) {
      const theme = (dataLayer as any).getThemeById?.(id)
      if (theme?.name === props.sectorName) {
        return metric
      }
    }
  } catch (e) {
    console.warn('[SectorDetail] 获取themeMetrics失败:', e)
  }
  return null
})

// 联动分析
const themeSelfCorrelation = computed(() => themeMetrics.value?.correlation || 0)

const correlationLevel = computed(() => {
  const corr = themeSelfCorrelation.value
  if (corr > 0.7) return '强联动'
  if (corr > 0.4) return '中联动'
  if (corr > 0.2) return '弱联动'
  return '无明显联动'
})

const correlationDesc = computed(() => {
  const corr = themeSelfCorrelation.value
  if (corr > 0.7) return '成分股高度同步，龙头效应明显'
  if (corr > 0.4) return '成分股走势较为一致'
  if (corr > 0.2) return '部分成分股存在联动'
  return '成分股走势独立'
})

const correlationThemes = computed(() => themeMetrics.value?.relatedThemes || [])

// ========== 成分股视图状态 ==========
const stockSearch = ref('')
const sortBy = ref('change')
const sortDesc = ref(true)
const currentPage = ref(1)
const pageSize = ref(20)

// 过滤和排序
const filteredStocks = computed(() => {
  let result = [...themeStocks.value]

  if (stockSearch.value) {
    const keyword = stockSearch.value.toLowerCase()
    result = result.filter(
      stock =>
        stock.name?.toLowerCase().includes(keyword) ||
        stock.code?.toLowerCase().includes(keyword)
    )
  }

  result.sort((a, b) => {
    let valA = a[sortBy.value as keyof typeof a] ?? 0
    let valB = b[sortBy.value as keyof typeof b] ?? 0

    if (sortBy.value === 'code' || sortBy.value === 'name') {
      const strA = String(valA || '')
      const strB = String(valB || '')
      return sortDesc.value ? strB.localeCompare(strA) : strA.localeCompare(strB)
    }

    return sortDesc.value ? Number(valB) - Number(valA) : Number(valA) - Number(valB)
  })

  return result
})

const paginatedStocks = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredStocks.value.slice(start, start + pageSize.value).map((s, i) => ({
    ...s,
    rank: start + i + 1
  }))
})

const totalPages = computed(() => Math.ceil(filteredStocks.value.length / pageSize.value))

watch([stockSearch, sortBy, sortDesc], () => {
  currentPage.value = 1
})

// ========== ✅ 合并成一个 watcher ==========
watch(() => props.sectorName, async (newName) => {
  if (newName && props.visible) {
    loading.value = true
    error.value = null
    try {
      // 找到板块代码
      const blocks = themeFacade.getJxbkBlocksCompat()
      const block = blocks.find(b => b.name === newName)

      if (block) {
        // 安全地清除缓存（如果方法存在）
        if (sectorAnalyzer && typeof sectorAnalyzer.clearCache === 'function') {
          sectorAnalyzer.clearCache()
        }

        // 加载个股数据
        if (sectorAnalyzer && typeof sectorAnalyzer.loadSectorStocks === 'function') {
          await sectorAnalyzer.loadSectorStocks(block.code, newName)
        }
      }

      // 重新加载面板数据
      await loadData()
    } catch (err) {
      console.error('[SectorDetail] 加载数据失败:', err)
      error.value = err instanceof Error ? err.message : '加载失败'
    } finally {
      loading.value = false
    }
  }
}, { immediate: true })

// ========== 历史趋势 ==========
const timeRange = ref<'1h' | '6h' | '1d' | '1w' | '1m'>('1d')
const selectedIndicators = ref<string[]>(['heat', 'zt', 'leader'])
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

// 模拟历史数据 - 实际应用中应该从 API 获取历史数据
const generateHistoryData = () => {
  const now = Date.now()
  const data = []
  for (let i = 30; i >= 0; i--) {
    data.push({
      timestamp: now - i * 5 * 60 * 1000, // 每5分钟一个点
      heatScore: Math.floor(Math.random() * 500) + 3000,
      ztCount: Math.floor(Math.random() * 10) + 5,
      leaderCount: Math.floor(Math.random() * 3) + 1,
      avgChange: (Math.random() * 4) - 2,
      volume: Math.floor(Math.random() * 1000) + 500
    })
  }
  return data
}

// 如果有真实的历史数据，可以从这里获取
const themeHistory = computed(() => {
  // 如果有真实的历史数据则返回，否则生成模拟数据
  if (blockData.value?.history) {
    return blockData.value.history
  }
  // 暂时用模拟数据，后续可以从 API 获取真实历史数据
  return generateHistoryData()
})

const filteredHistory = computed(() => {
  const now = Date.now()
  const ranges = {
    '1h': 60 * 60 * 1000,
    '6h': 6 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1m': 30 * 24 * 60 * 60 * 1000,
  }
  const cutoff = now - ranges[timeRange.value]
  return themeHistory.value.filter((p: any) => p.timestamp >= cutoff)
})

const historyStats = computed(() => {
  const history = filteredHistory.value
  if (history.length === 0) {
    return { max: 0, maxTime: 0, min: 0, minTime: 0, avg: 0, trend: 0, maxZT: 0, maxZTTime: 0 }
  }

  const scores = history.map((h: any) => h.heatScore)
  const ztCounts = history.map((h: any) => h.ztCount)

  const max = Math.max(...scores)
  const maxTime = history.find((h: any) => h.heatScore === max)?.timestamp || 0
  const min = Math.min(...scores)
  const minTime = history.find((h: any) => h.heatScore === min)?.timestamp || 0
  const avg = scores.reduce((a: number, b: number) => a + b, 0) / scores.length
  const maxZT = Math.max(...ztCounts)
  const maxZTTime = history.find((h: any) => h.ztCount === maxZT)?.timestamp || 0

  let trend = 0
  if (history.length >= 3) {
    const n = history.length
    const indices = Array.from({ length: n }, (_, i) => i)
    const sumX = indices.reduce((a, b) => a + b, 0)
    const sumY = scores.reduce((a: number, b: number) => a + b, 0)
    const sumXY = indices.reduce((a, b, i) => a + b * scores[i], 0)
    const sumX2 = indices.reduce((a, b) => a + b * b, 0)
    trend = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
  }

  return { max, maxTime, min, minTime, avg, trend, maxZT, maxZTTime }
})

function setTimeRange(range: '1h' | '6h' | '1d' | '1w' | '1m') {
  timeRange.value = range
  nextTick(() => renderChart())
}

function toggleIndicator(indicator: string) {
  if (selectedIndicators.value.includes(indicator)) {
    selectedIndicators.value = selectedIndicators.value.filter(i => i !== indicator)
  } else {
    selectedIndicators.value = [...selectedIndicators.value, indicator]
  }
  nextTick(() => renderChart())
}

function formatHeat(heat: number): string {
  if (!heat) return '0'
  if (heat >= 10000) return (heat / 10000).toFixed(1) + '万'
  if (heat >= 1000) return (heat / 1000).toFixed(1) + 'k'
  return heat.toString()
}

// ✅ 完整的 ECharts 渲染函数
function renderChart() {
  if (!chartRef.value || filteredHistory.value.length === 0) return

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const history = filteredHistory.value
  const indicators = selectedIndicators.value
  const series: any[] = []

  // 热度曲线
  if (indicators.includes('heat')) {
    series.push({
      name: '热度',
      type: 'line',
      data: history.map((h: any) => h.heatScore),
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: '#ff7f50', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(255, 127, 80, 0.3)' },
          { offset: 1, color: 'rgba(255, 127, 80, 0)' }
        ])
      }
    })
  }

  // 涨停柱状图
  if (indicators.includes('zt')) {
    series.push({
      name: '涨停股',
      type: 'bar',
      data: history.map((h: any) => h.ztCount),
      itemStyle: { color: '#ff4757' },
      barWidth: 8,
      yAxisIndex: 1
    })
  }

  // 龙头柱状图
  if (indicators.includes('leader')) {
    series.push({
      name: '龙头股',
      type: 'bar',
      data: history.map((h: any) => h.leaderCount),
      itemStyle: { color: '#ffd700' },
      barWidth: 8,
      yAxisIndex: 1
    })
  }

  // 平均涨跌曲线
  if (indicators.includes('change')) {
    series.push({
      name: '平均涨跌',
      type: 'line',
      data: history.map((h: any) => h.avgChange),
      smooth: true,
      lineStyle: { color: '#2ed573', width: 1.5, type: 'dashed' },
      symbol: 'diamond',
      symbolSize: 4,
      yAxisIndex: 2
    })
  }

  // 成交量曲线
  if (indicators.includes('volume')) {
    series.push({
      name: '成交量',
      type: 'line',
      data: history.map((h: any) => h.volume),
      smooth: true,
      lineStyle: { color: '#3498db', width: 1.5 },
      symbol: 'none',
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(52, 152, 219, 0.2)' },
          { offset: 1, color: 'rgba(52, 152, 219, 0)' }
        ])
      },
      yAxisIndex: 3
    })
  }

  const option = {
    grid: {
      left: '8%',
      right: '8%',
      top: '15%',
      bottom: '10%',
      containLabel: true
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' }
    },
    legend: {
      data: series.map(s => s.name),
      bottom: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: 'var(--text-secondary)' }
    },
    xAxis: {
      type: 'category',
      data: history.map((h: any) => {
        const date = new Date(h.timestamp)
        return `${date.getHours()}:${date.getMinutes().toString().padStart(2, '0')}`
      }),
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 10,
        rotate: 30
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } }
    },
    yAxis: [
      {
        type: 'value',
        name: '热度',
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed' } },
        axisLabel: { color: 'var(--text-secondary)' }
      },
      {
        type: 'value',
        name: '数量',
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)' }
      },
      {
        type: 'value',
        name: '涨跌%',
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)' }
      },
      {
        type: 'value',
        name: '成交量',
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)' }
      }
    ],
    series,
    backgroundColor: 'transparent'
  }

  chart.setOption(option)
  chart.resize()
}

// 监听窗口大小变化
onMounted(() => {
  window.addEventListener('resize', () => {
    if (chart) {
      chart.resize()
    }
  })
})

// 在组件卸载时销毁图表
onUnmounted(() => {
  if (chart) {
    chart.dispose()
    chart = null
  }
})

// 监听数据变化重新渲染
watch(
  [filteredHistory, selectedIndicators],
  () => {
    if (view.value === 'history') {
      nextTick(() => renderChart())
    }
  },
  { deep: true }
)

// ========== 操作函数 ==========
const loadingMessage = computed(() => loading.value ? '加载板块详情...' : '')

function goBack() { emit('close') }

const refresh = async () => {
  if (loading.value) return  // ✅ 防止重复点击

  try {
    loading.value = true  // ✅ 动画开始
    error.value = null

    // 清除缓存
    if (sectorAnalyzer && typeof sectorAnalyzer.clearCache === 'function') {
      sectorAnalyzer.clearCache()
    }

    // 找到板块代码
    const blocks = themeFacade.getJxbkBlocksCompat()
    const block = blocks.find(b => b.name === props.sectorName)

    if (block) {
      if (sectorAnalyzer && typeof sectorAnalyzer.loadSectorStocks === 'function') {
        await sectorAnalyzer.loadSectorStocks(block.code, props.sectorName, true)
      }
    }

    await themeFacade.refreshJxbkAndFactors({ force: true })

    await nextTick()

  } catch (err) {
    console.error('[SectorDetail] 刷新失败:', err)
    error.value = err instanceof Error ? err.message : '刷新失败'
  } finally {
    loading.value = false  // ✅ 动画结束
  }
}

function close() { emit('update:visible', false); emit('close') }

function selectStock(code: string) {
  const stockStore = useStockStore()
  stockStore.selectStock(code)
  close()
}

function selectTheme(themeName: string) { emit('select-theme', themeName) }
function addToFavorite(code: string) { useFavoriteStore().addToFavorites(code) }
function linkToTdx(code: string) { window.open(`http://www.tdx.com/code_${code}`, '_blank') }

function setSort(field: string) {
  if (sortBy.value === field) sortDesc.value = !sortDesc.value
  else { sortBy.value = field; sortDesc.value = true }
}

// ========== 工具函数 ==========
function getStrengthLevel(strength: number): string {
  if (strength >= 4000) return 's'
  if (strength >= 3000) return 'a'
  if (strength >= 2000) return 'b'
  if (strength >= 1000) return 'c'
  return 'd'
}

function getStrengthLevelText(strength: number): string {
  if (strength >= 4000) return '极强'
  if (strength >= 3000) return '强'
  if (strength >= 2000) return '中'
  if (strength >= 1000) return '弱'
  return '极弱'
}

function getStrengthColor(strength: number): string {
  if (strength >= 4000) return '#ff4757'
  if (strength >= 3000) return '#ff7f50'
  if (strength >= 2000) return '#ffb142'
  if (strength >= 1000) return '#4a90e2'
  return '#7f8c8d'
}

function getVolumeRatioColor(ratio: number): string {
  if (ratio >= 2.5) return '#ff4757'
  if (ratio >= 1.5) return '#ffb142'
  if (ratio >= 0.8) return '#4a90e2'
  return '#7f8c8d'
}

function getVolumeRatioDesc(ratio: number): string {
  if (ratio >= 2.5) return '高量'
  if (ratio >= 1.5) return '正常'
  if (ratio >= 0.8) return '缩量'
  return '地量'
}

function formatMoney(value: number): string {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 100000000) {
    return (value / 100000000).toFixed(2) + '亿'
  }
  if (absValue >= 10000) {
    return (value / 10000).toFixed(2) + '万'
  }
  return value.toString()
}

function formatTime(timestamp: number | null | undefined): string {
  if (!timestamp) return '--:--'
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

function formatChange(change: number): string {
  if (!change && change !== 0) return '-'
  return (change > 0 ? '+' : '') + change.toFixed(2) + '%'
}

function formatPopularityChange(val: number): string {
  if (!val && val !== 0) return '-'
  if (val > 0) return `↑${val}`
  if (val < 0) return `↓${Math.abs(val)}`
  return '0'
}

function getLianbanClass(lianban: string): string {
  if (lianban.includes('首板')) return 'first'
  if (lianban.includes('2板')) return 'second'
  if (lianban.includes('3板')) return 'third'
  if (lianban.includes('4板')) return 'fourth'
  if (lianban.includes('5板')) return 'fifth'
  return ''
}

function getMoneyClass(val: number): string {
  if (!val) return 'number'
  return val > 0 ? 'inflow' : 'outflow'
}

function getPopularityChangeClass(val: number): string {
  if (!val) return ''
  return val > 0 ? 'up' : 'down'
}

function getChangeClass(change: number): string {
  return change >= 0 ? 'up' : 'down'
}

function getCorrelationColor(corr: number = 0): string {
  if (corr > 0.7) return '#ff4757'
  if (corr > 0.4) return '#f39c12'
  if (corr > 0.2) return '#3498db'
  return '#7f8c8d'
}

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible && props.sectorName) {
    loadData()
  }
  // 渲染图表
  nextTick(() => {
    if (view.value === 'history') {
      renderChart()
    }
  })
})

watch(view, (newView) => {
  if (newView === 'history') {
    nextTick(() => renderChart())
  }
})

defineExpose({ themeStocks, filteredStocks, paginatedStocks })
</script>
<style scoped>
/* ========== 面板基础样式 ========== */
.sector-detail-panel {
  position: fixed;
  width: 600px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10005;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
  color: var(--text-primary);
}

/* ========== 头部样式 ========== */
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

.back-btn {
  padding: 4px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.back-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}

.panel-actions {
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

/* ========== 标签页样式 ========== */
.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.tabs-left {
  display: flex;
  gap: 4px;
  flex: 1;
}

.tab-btn {
  flex: 1;
  padding: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 12px;
  transition: all 0.2s;
  position: relative;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
  font-weight: 500;
}

.tab-count {
  margin-left: 4px;
  padding: 0 4px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 8px;
  font-size: 9px;
}

/* ========== 内容区域 ========== */
.panel-content {
  padding: 20px;
  max-height: calc(85vh - 120px);
  overflow-y: auto;
}

/* ========== 概览视图 ========== */
.overview-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 基础信息卡片 */
.info-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}

.info-row {
  display: flex;
  margin-bottom: 8px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-label {
  width: 70px;
  color: var(--text-secondary);
}

.info-value {
  flex: 1;
  color: var(--text-primary);
  font-weight: 500;
}

/* 指标卡片网格 - 2x2 布局 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.metric-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 24px;
}

.metric-content {
  flex: 1;
}

.metric-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 22px;
  font-weight: bold;
  line-height: 1.2;
}

.metric-value.up {
  color: #ff4757;
}

.metric-value.down {
  color: #2ed573;
}

.metric-level,
.metric-desc {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  display: inline-block;
  margin-top: 4px;
}

/* 强度等级 */
.strength-card .metric-level.strength-s {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
}

.strength-card .metric-level.strength-a {
  background: rgba(255, 127, 80, 0.15);
  color: #ff7f50;
}

.strength-card .metric-level.strength-b {
  background: rgba(255, 177, 66, 0.15);
  color: #ffb142;
}

.strength-card .metric-level.strength-c {
  background: rgba(74, 144, 226, 0.15);
  color: #4a90e2;
}

.strength-card .metric-level.strength-d {
  background: rgba(127, 140, 141, 0.15);
  color: #7f8c8d;
}

/* 资金卡片网格 - 3列 */
.funds-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.fund-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.fund-icon {
  font-size: 20px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 16px;
}

.fund-content {
  flex: 1;
}

.fund-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.fund-value {
  font-size: 14px;
  font-weight: bold;
}

.fund-value.inflow {
  color: #ff4757;
}

.fund-value.outflow {
  color: #2ed573;
}

/* 统计卡片 - 4列 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.stat-icon {
  font-size: 18px;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-title);
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* 龙头股区域 */
.leaders-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
}

.section-count {
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}

.leaders-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.leader-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.leader-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.leader-rank {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-highlight);
  color: #000;
  border-radius: 12px;
  font-weight: bold;
  font-size: 12px;
  flex-shrink: 0;
}

.leader-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.leader-name {
  font-weight: 500;
  color: var(--text-primary);
}

.leader-level {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  display: inline-block;
  width: fit-content;
}

.leader-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
}

.leader-change {
  font-weight: 500;
  min-width: 60px;
  text-align: right;
}

.leader-change.up {
  color: #ff4757;
}

.leader-change.down {
  color: #2ed573;
}

.leader-days {
  padding: 2px 6px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  font-size: 10px;
}

.more-hint {
  padding: 8px;
  text-align: center;
  font-size: 11px;
  color: var(--text-secondary);
  border-top: 1px dashed var(--border-color);
}

/* ========== 成分股视图 ========== */
.stocks-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 搜索和排序栏 */
.stocks-header {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.search-box {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.search-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  font-size: 12px;
}

.search-input:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.search-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 0 4px;
}

.search-clear:hover {
  color: var(--text-primary);
}

.sort-controls {
  display: flex;
  gap: 4px;
}

.sort-select {
  padding: 6px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.sort-select:hover {
  border-color: var(--color-highlight);
}

.sort-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.sort-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.stocks-stats {
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
}

.filter-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-left: 4px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 4px;
}

/* 表格样式 */
.stocks-table-container {
  max-height: 500px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
  margin-top: 8px;
}

.stocks-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  min-width: 1400px;
}

.stocks-table th {
  position: sticky;
  top: 0;
  background: var(--bg-header);
  padding: 10px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  z-index: 1;
  font-size: 12px;
}

.stocks-table th:hover {
  color: var(--color-highlight);
  background: var(--bg-hover);
}

.stocks-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
  color: var(--text-primary);
}

.stocks-table tbody tr {
  cursor: pointer;
  transition: background 0.2s;
}

.stocks-table tbody tr:hover {
  background: var(--bg-hover);
}

.stocks-table tbody tr.zt-row {
  background: rgba(255, 71, 87, 0.15);
}

.stocks-table tbody tr.leader-row {
  border-left: 4px solid var(--color-highlight);
}

.stocks-table tbody tr.new-row {
  border-right: 4px solid #2ecc71;
}

/* 表格中的特殊样式 */
.code-link {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  cursor: pointer;
  font-weight: 500;
}

.code-link:hover {
  color: var(--color-highlight);
  text-decoration-color: var(--color-highlight);
}

.tags-container {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  max-width: 150px;
}

.tag {
  padding: 2px 6px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 10px;
  color: var(--text-primary);
  white-space: nowrap;
}

.lead-badge {
  padding: 2px 6px;
  background: rgba(255, 215, 0, 0.15);
  border: 1px solid rgba(255, 215, 0, 0.3);
  border-radius: 10px;
  font-size: 10px;
  color: #ffd700;
}

.lead-badge.poban {
  background: rgba(255, 71, 87, 0.15);
  border-color: rgba(255, 71, 87, 0.3);
  color: #ff4757;
}

.lianban-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 500;
}

.lianban-badge.first {
  background: rgba(255, 215, 0, 0.15);
  color: #ffd700;
}

.lianban-badge.second {
  background: rgba(192, 192, 192, 0.15);
  color: #c0c0c0;
}

.lianban-badge.third {
  background: rgba(205, 127, 50, 0.15);
  color: #cd7f32;
}

.lianban-badge.fourth,
.lianban-badge.fifth {
  background: rgba(255, 71, 87, 0.15);
  color: #ff4757;
}

.blocks-container {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  max-width: 150px;
}

.block-tag {
  padding: 2px 4px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 9px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.badges {
  display: flex;
  gap: 4px;
}

.badge {
  display: inline-block;
  width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 4px;
  font-size: 12px;
}

.leader-badge {
  background: rgba(255, 215, 0, 0.25);
  color: #ffd700;
  font-weight: bold;
}

.new-badge {
  background: rgba(46, 204, 113, 0.25);
  color: #2ecc71;
  font-weight: bold;
}

.zt-badge {
  background: rgba(255, 71, 87, 0.25);
  color: #ff4757;
  font-weight: bold;
}

.poban-badge {
  background: rgba(255, 71, 87, 0.25);
  color: #ff4757;
}

.reason-cell {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: 11px;
}

/* 表格数据对齐和颜色 */
td.number {
  text-align: right;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-weight: 500;
}

td.hotness {
  color: #ff7f50;
  font-weight: 600;
}

td.up {
  color: #ff4757;
  font-weight: 600;
}

td.down {
  color: #2ed573;
  font-weight: 600;
}

td.inflow {
  color: #ff4757;
  font-weight: 500;
}

td.outflow {
  color: #2ed573;
  font-weight: 500;
}

.btn-icon-small {
  width: 26px;
  height: 26px;
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

.empty-stocks {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 14px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

/* 分页 */
.pagination-container {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 16px;
}

.page-btn {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

.page-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.page-info {
  font-size: 12px;
  color: var(--text-secondary);
}

/* ========== 联动分析视图 ========== */
.correlation-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.correlation-card {
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.correlation-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.correlation-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-title);
}

.correlation-value {
  font-size: 18px;
  font-weight: bold;
}

.correlation-bar {
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.correlation-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.correlation-level {
  font-size: 14px;
  font-weight: bold;
  text-align: center;
  margin: 8px 0 4px;
}

.correlation-desc {
  font-size: 11px;
  color: var(--text-secondary);
  text-align: center;
}

.related-themes {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}

.themes-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.theme-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.theme-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.theme-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.theme-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-title);
}

.theme-badge {
  font-size: 9px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-secondary);
}

.theme-badge.badge-强联动 {
  background: #ff475720;
  color: #ff4757;
}

.theme-badge.badge-中联动 {
  background: #f39c1220;
  color: #f39c12;
}

.theme-badge.badge-弱联动 {
  background: #3498db20;
  color: #3498db;
}

.theme-metrics {
  display: flex;
  gap: 16px;
}

.theme-metrics .metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-metrics .metric-label {
  font-size: 8px;
  color: var(--text-secondary);
}

.theme-metrics .metric-value {
  font-size: 11px;
  font-weight: 500;
}

.theme-progress {
  height: 3px;
  background: var(--bg-secondary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}

/* ========== 历史趋势视图 ========== */
.history-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.time-range-selector,
.indicator-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.time-btn,
.indicator-btn {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.time-btn:hover,
.indicator-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.time-btn.active,
.indicator-btn.active {
  background: var(--color-highlight);
  border-color: var(--color-highlight);
  color: #000;
}

.history-chart {
  height: 250px;
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px;
}

.history-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-top: 16px;
}

.history-stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}

.history-stat-card .stat-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.history-stat-card .stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-title);
  line-height: 1.2;
}

.history-stat-card .stat-time {
  font-size: 9px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.history-stat-card .stat-trend {
  font-size: 11px;
  font-weight: 500;
  margin-top: 4px;
}

.history-stat-card .stat-trend.up {
  color: #ff4757;
}

.history-stat-card .stat-trend.down {
  color: #2ed573;
}

/* ========== 通用状态样式 ========== */
.loading-state,
.error-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 16px;
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

.rotate-animation {
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

.empty-icon,
.error-icon {
  font-size: 48px;
  opacity: 0.5;
  margin-bottom: 8px;
}

.retry-btn {
  padding: 8px 16px;
  background: var(--color-highlight);
  border: none;
  border-radius: 20px;
  color: #000;
  font-size: 12px;
  cursor: pointer;
}

/* ========== 页脚 ========== */
.panel-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
  color: var(--text-secondary);
  display: flex;
  justify-content: space-between;
}

/* ========== 辅助样式 ========== */
.tag-placeholder {
  color: var(--text-secondary);
  font-size: 10px;
  padding: 2px 4px;
}

td:empty::before {
  content: '-';
  color: var(--text-secondary);
}
</style>
