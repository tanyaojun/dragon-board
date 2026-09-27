<!-- src/components/panels/SectorDetail.vue -->
<!-- 全市场题材详情 -->

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
                  <div class="metric-label">题材热度</div>
                  <div class="metric-value" :style="{ color: heatDisplay.color }">
                    {{ heatDisplay.value }}
                  </div>
                  <div class="metric-level" :class="`strength-${heatDisplay.band}`">
                    {{ heatDisplay.level }}
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
                  <div class="metric-label">动量分</div>
                  <div class="metric-value">{{ blockData?.momentumScore || 0 }}</div>
                  <div class="metric-desc">全市场动量</div>
                </div>
              </div>

              <div class="metric-card volume-card">
                <div class="metric-icon">📊</div>
                <div class="metric-content">
                  <div class="metric-label">量比</div>
                  <div class="metric-value" :style="{ color: getVolumeRatioColor(blockData?.volumeRatio || 0) }">
                    {{ blockData?.volumeRatio === null ? '--' : blockData?.volumeRatio?.toFixed(2) || '--' }}
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
                  <div class="fund-value" :class="blockData?.mainNetInflow == null ? '' : blockData.mainNetInflow >= 0 ? 'inflow' : 'outflow'">
                    {{ blockData?.mainNetInflow == null ? '--' : formatMoney(blockData.mainNetInflow) }}
                  </div>
                </div>
              </div>

              <div class="fund-card">
                <div class="fund-icon">💎</div>
                <div class="fund-content">
                  <div class="fund-label">资金分</div>
                  <div class="fund-value">{{ blockData?.fundScore === null ? '--' : blockData?.fundScore }}</div>
                </div>
              </div>

              <div class="fund-card">
                <div class="fund-icon">🏦</div>
                <div class="fund-content">
                  <div class="fund-label">广度分</div>
                  <div class="fund-value">{{ blockData?.breadthScore || 0 }}</div>
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

            <!-- 轮动状态（引擎 half_hour 15:00 快照，按题材名匹配；字段合并自轮动快照） -->
            <div class="rotation-section" v-if="rotationLoaded && rotationRow">
              <div class="section-header">
                <span class="section-title">🔄 轮动状态</span>
                <span class="section-count">{{ rotationDataTime }}</span>
              </div>
              <div class="rotation-metrics">
                <div class="stat-card">
                  <span class="state-badge" :class="rotationStateTone">{{ rotationStateLabel }}</span>
                  <span class="stat-label">轮动状态</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.rotationScore ?? '—' }}</span>
                  <span class="stat-label">轮动分</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.rank ?? '—' }}</span>
                  <span class="stat-label">热度排名</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value" :class="rotationFlowClass">{{ formatRotationFlow(rotationRow.flowTrend) }}</span>
                  <span class="stat-label">净流入趋势</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.factorBreakdown?.strength ?? '—' }}</span>
                  <span class="stat-label">强度</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.factorBreakdown?.flow ?? '—' }}</span>
                  <span class="stat-label">资金</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.factorBreakdown?.breadth ?? '—' }}</span>
                  <span class="stat-label">广度</span>
                </div>
                <div class="stat-card">
                  <span class="stat-value">{{ rotationRow.factorBreakdown?.crowding ?? '—' }}</span>
                  <span class="stat-label">拥挤</span>
                </div>
              </div>
              <div class="info-row" v-if="rotationRow.qualityFlags?.length">
                <span class="info-label">质量标记</span>
                <span class="info-value flags">{{ rotationRow.qualityFlags.join(', ') }}</span>
              </div>
            </div>
            <div class="rotation-section" v-else-if="rotationLoaded && !rotationRow">
              <div class="section-header">
                <span class="section-title">🔄 轮动状态</span>
              </div>
              <div class="rotation-missing">该题材不在轮动快照中</div>
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
                  <option value="price">最新价</option>
                  <option value="leader">龙头</option>
                  <option value="lianban">连板</option>
                  <option value="firstZtTime">首次涨停时间</option>
                  <option value="fengdan">封单金额</option>
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
                    <th @click="setSort('leader')">领涨状态</th>
                    <th @click="setSort('lianban')">连板</th>
                    <th @click="setSort('firstZtTime')">首次涨停</th>
                    <th @click="setSort('lastZtTime')">最后涨停</th>
                    <th @click="setSort('fengdan')">封单(亿)</th>
                    <th>开板</th>
                    <th>涨停原因</th>
                    <th>板块</th>
                    <th>标记</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="stock in paginatedStocks" :key="stock.code" :class="{
                    'zt-row': isZtStock(stock),
                    'leader-row': stock.isSectorLeader,
                  }" @click.stop="selectStock(stock.code)">
                    <td>{{ stock.rank }}</td>
                    <td><span class="code-link" @click.stop="linkToTdx(stock.code)">{{ stock.code }}</span></td>
                    <td>{{ stock.name || '-' }}</td>
                    <td :class="getChangeClass(stock.change)">
                      {{ stock.change > 0 ? '+' : '' }}{{ (stock.change || 0).toFixed(2) }}%
                    </td>
                    <td class="number">{{ (stock.volumeRatio || 0).toFixed(2) }}</td>
                    <td :class="getMoneyClass(stock.mainNetInflow || 0)">
                      {{ stock.mainNetInflow === null ? '--' : formatMoney(stock.mainNetInflow) }}
                    </td>
                    <td>
                      <!-- 领涨状态=题材内按首次涨停时间编位：龙一/龙二/龙三……，未涨停显示 -- -->
                      <span v-if="stock.leaderRank" class="lead-badge">{{ formatLeaderRank(stock.leaderRank) }}</span>
                      <span v-else>--</span>
                    </td>
                    <td>{{ formatLianbanText(stock) }}</td>
                    <td>{{ stock.firstZtTime || '--' }}</td>
                    <td>{{ stock.lastZtTime || '--' }}</td>
                    <td>{{ formatFengdanYi(stock.fengdan) }}</td>
                    <td>{{ formatOpenNum(stock.openNum) }}</td>
                    <td>
                      <span class="reason-text" :title="stock.reason || ''">{{ stock.reason || '--' }}</span>
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
                    <td>
                      <div class="badges">
                        <span v-if="stock.isSectorLeader" class="badge leader-badge" title="龙头">👑</span>
                        <span v-if="isZtStock(stock)" class="badge zt-badge" title="涨停">📈</span>
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
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('rank') }"
            @click="toggleIndicator('rank')">📊 热度排名</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('rotationState') }"
            @click="toggleIndicator('rotationState')">🔄 轮动状态</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('mainNetInflow') }"
            @click="toggleIndicator('mainNetInflow')">💰 净流入趋势</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('change') }"
            @click="toggleIndicator('change')">💹 涨跌</button>
          <button class="indicator-btn" :class="{ active: selectedIndicators.includes('volume') }"
            @click="toggleIndicator('volume')">📊 成交额</button>
        </div>

        <!-- 窗口锚定提示：非交易日/数据间歇时窗口锚定到最后可用交易日 -->
        <div v-if="historyAnchorHint" class="history-anchor-hint">
          所选窗口内无交易数据，已锚定到最后可用交易日 {{ historyAnchorHint }}
        </div>

        <!-- 历史数据结构化状态：加载/错误/空态，不伪造曲线 -->
        <div v-if="historyLoading" class="history-state">
          <div class="loading-spinner"></div>
          <span>加载历史快照数据...</span>
        </div>
        <div v-else-if="historyError" class="history-state">
          <span class="error-icon">⚠️</span>
          <span>{{ historyError }}</span>
          <button class="retry-btn" @click="loadHistoryData">重试</button>
        </div>
        <div v-else-if="historyPoints.length === 0" class="history-state">
          <span class="empty-icon">📊</span>
          <span>暂无历史快照数据（统计口径 half_hour）</span>
        </div>
        <template v-else>
          <div v-if="historySourceHint" class="history-source-hint">⚠️ {{ historySourceHint }}</div>
          <div class="history-chart" ref="chartRef"></div>

          <div class="history-stats-grid">
            <div class="history-stat-card">
              <div class="stat-label">最高热度</div>
              <div class="stat-value">{{ historyStats.max === null ? '--' : formatHeat(historyStats.max) }}</div>
              <div class="stat-time">{{ formatTime(historyStats.maxTime) }}</div>
            </div>
            <div class="history-stat-card">
              <div class="stat-label">最低热度</div>
              <div class="stat-value">{{ historyStats.min === null ? '--' : formatHeat(historyStats.min) }}</div>
              <div class="stat-time">{{ formatTime(historyStats.minTime) }}</div>
            </div>
            <div class="history-stat-card">
              <div class="stat-label">平均热度</div>
              <div class="stat-value">{{ historyStats.avg === null ? '--' : formatHeat(historyStats.avg) }}</div>
              <div class="stat-trend" :class="historyStats.trend >= 0 ? 'up' : 'down'">
                {{ historyStats.trend > 0 ? '+' : '' }}{{ historyStats.trend.toFixed(1) }}
              </div>
            </div>
            <div class="history-stat-card">
              <div class="stat-label">涨停峰值</div>
              <div class="stat-value">{{ historyStats.maxZT === null ? '--' : historyStats.maxZT }}</div>
              <div class="stat-time">{{ formatTime(historyStats.maxZTTime) }}</div>
            </div>
          </div>
        </template>
      </div>

      <div class="panel-footer" v-if="hasThemeData && !loading">
        <span>📡 MongoDB 题材映射 + 腾讯行情 + 同花顺资金</span>
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
import { getRotationSummary, type ThemeRotationStatusRow } from '../../services/theme/ThemeFacade'
import {
  rotationStateLabel as rotationStateLabelText,
  ROTATION_STATE_META,
} from '../../services/theme/rotationDisplay'
import { deriveThemeHeatBand, deriveThemeHeatLevel, deriveThemeHeatMeta } from '../../services/theme/stockThemeMeta'
import type { ThemeHeatStock } from '../../services/theme/types'
import type { ThemeStockWithLimitUp } from '../../services/theme/stockLimitUpRows'
import {
  compareThemeStockRows,
  formatFengdanYi,
  formatLeaderRank,
  formatLianbanText,
  formatOpenNum,
} from '../../services/theme/stockLimitUpRows'
import { useThemeRuntimeSnapshot } from '../../composables/useThemeRuntimeSnapshot'
import {
  fetchThemeHistorySeries,
  type ThemeHistoryPoint,
  type ThemeHistoryTimeRange,
} from '../../services/theme/themeHistorySeries'
import { StockUtils } from '../../utils/common'

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
const themeRuntime = useThemeRuntimeSnapshot()

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
  rotationRow.value = null
  rotationLoaded.value = false

  try {
    const summary = themeFacade.getThemeSummaries(Number.MAX_SAFE_INTEGER)
      .find(theme => theme.name === props.sectorName || theme.id === props.sectorName)
    if (summary) {
      // 打开面板走 30 秒 LRU 缓存（themeHeatStocksCache），避免每次打开都强制后端查 MongoDB 重算；
      // 手动刷新按钮（refresh）才 force 绕过缓存
      themeStockRows.value = await sectorAnalyzer.loadSectorStocks(summary.id, summary.name)
    }

    // 轮动状态（独立 try：轮动取数失败不影响题材主体数据展示，降级为"不在快照中"）
    try {
      const rotation = await getRotationSummary({ snapshotType: 'half_hour' })
      rotationRow.value = rotation?.statuses.find((row) => row.entityName === props.sectorName) ?? null
      rotationDataTime.value = rotation ? `${rotation.frame.tradingDate} ${rotation.frame.slotTime}` : ''
      rotationLoaded.value = true
    } catch {
      rotationLoaded.value = false
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

// enrichStocksWithLimitUp 输出：ThemeHeatStock + 涨停池字段 + leaderRank（龙一/龙二编位）
const themeStockRows = ref<Array<ThemeStockWithLimitUp<ThemeHeatStock>>>([])

// 轮动状态行（/api/theme-rotation/summary，按题材名匹配；无匹配=该题材不在快照中，如实显示）
const rotationRow = ref<ThemeRotationStatusRow | null>(null)
const rotationDataTime = ref('')
const rotationLoaded = ref(false)

const blockCode = computed(() => {
  if (!themeRuntime.value.factors.length) return null
  return themeFacade.getThemeSummaries(Number.MAX_SAFE_INTEGER)
    .find(theme => theme.name === props.sectorName || theme.id === props.sectorName)?.id || null
})

const blockData = computed(() => {
  if (!blockCode.value) return null
  return themeFacade.getThemeSummary(blockCode.value)
})

// 题材热度卡（审计修复：heatLevel 迁移后 heatScore 是 KPL 人气绝对值，可达数十万，
// 旧 4000/3000/2000/1000 分档使热门题材全部挤"极强"）。档位/颜色统一走
// heatLevelScore 相对分（0-100）+ stockThemeMeta 统一档位出口；
// 数值本身保留绝对值展示（人气量级口径），缺失显示 '--' 不伪装 0。
const heatDisplay = computed(() => {
  const heatScore = blockData.value?.heatScore
  const heatLevelScore = blockData.value?.heatLevelScore
  if (heatScore == null || typeof heatScore !== 'number' || !Number.isFinite(heatScore)) {
    return { value: '--', level: '-', band: 'd' as const, color: '#7f8c8d' }
  }
  const meta = deriveThemeHeatMeta(heatLevelScore)
  return {
    value: String(Math.round(heatScore)),
    level: deriveThemeHeatLevel(heatLevelScore) || '-',
    band: deriveThemeHeatBand(heatLevelScore),
    color: meta.color,
  }
})

const displayLastUpdate = computed(() => {
  return blockData.value?.lastUpdate || themeRuntime.value.lastUpdate || themeFacade.getThemeLastUpdate()
})

const themeStocks = computed(() => {
  return themeStockRows.value.map(stock => {
    // 连板文本/天数取真实涨停池字段（boardHeight），非涨停股保持空（不伪造）
    const lianbanText = formatLianbanText(stock)
    return {
      ...stock,
      volumeRatio: stock.volumeRatio,
      mainNetInflow: stock.mainNetInflow,
      isSectorLeader: stock.role === 'leader',
      lianban: lianbanText === '--' ? '' : lianbanText,
      continuousDays: stock.boardHeight || 0,
      blocks: [props.sectorName],
    }
  })
})

const hasThemeData = computed(() => blockData.value !== null || themeStocks.value.length > 0)

// 轮动状态展示（概览合并字段，来自 /api/theme-rotation/summary 按题材名匹配的行）
const rotationStateLabel = computed(() =>
  rotationRow.value ? rotationStateLabelText(rotationRow.value.rotationState) : '—',
)
const rotationStateTone = computed(() => {
  const state = rotationRow.value?.rotationState
  return (state && ROTATION_STATE_META[state]?.tone) || 'state-unknown'
})
const rotationFlowClass = computed(() => ({
  'rotation-flow-up': (rotationRow.value?.flowTrend ?? 0) > 0,
  'rotation-flow-down': (rotationRow.value?.flowTrend ?? 0) < 0,
}))

function formatRotationFlow(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const text = abs >= 1e8 ? `${(abs / 1e8).toFixed(1)}亿` : abs >= 1e4 ? `${(abs / 1e4).toFixed(0)}万` : String(abs)
  return (value > 0 ? '+' : value < 0 ? '-' : '') + text
}

// 统计指标
// 涨停判定统一走 StockUtils 分板块阈值（主板10%/创业科创20%/北交所30%，主板ST 5%）
function isZtStock(stock: { code: string; name?: string; change?: number }): boolean {
  return StockUtils.isLimitUp(stock.change || 0, stock.code, stock.name || '')
}

const themeStockCount = computed(() => themeStocks.value.length)

// 涨停股数量 - 优先使用 blockData 的 ztCount，如果为0则从股票列表统计
const displayZtCount = computed(() => {
  if (blockData.value?.ztCount && blockData.value.ztCount > 0) {
    return blockData.value.ztCount
  }
  return themeStocks.value.filter(s => isZtStock(s)).length
})

const themeZtCount = displayZtCount

const themeLeaderCount = computed(() => themeLeaders.value.length)

const themeTotalContinuousDays = computed(() =>
  themeStocks.value.reduce((sum, s) => sum + (s.boardHeight || 0), 0)
)

// 龙头股：按题材内连板+首次涨停时间编位（龙一/龙二……），与成分股表领涨状态列同口径
const themeLeaders = computed(() => {
  return themeStocks.value
    .filter(stock => stock.leaderRank)
    .sort((a, b) => (a.leaderRank || 0) - (b.leaderRank || 0))
    .map(stock => ({
      code: stock.code,
      name: stock.name,
      change: stock.change,
      continuousDays: stock.boardHeight || 1,
      level: formatLeaderRank(stock.leaderRank),
      levelIcon: '👑',
      levelColor: '#ffd700',
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
// 默认按龙头排序：leaderRank 编位（连板降序+首次涨停时间升序），龙一在最前
const sortBy = ref('leader')
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

  result.sort((a, b) => compareThemeStockRows(a, b, sortBy.value, sortDesc.value))

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
    await loadData()
  }
}, { immediate: true })

// ========== 历史趋势（生产数据：MongoDB 快照 sector rows + 成分股成交量聚合） ==========
const timeRange = ref<ThemeHistoryTimeRange>('1d')
const selectedIndicators = ref<string[]>(['heat', 'zt', 'rank', 'rotationState', 'mainNetInflow'])
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

// 轮动状态类别轴（自下而上：退潮→流出→中性→萌发→流入→主线，语义热度递增）
const ROTATION_STATE_AXIS_CATEGORIES = ['退潮', '流出', '中性', '萌发', '流入', '主线']
const historyAnchorHint = ref<string | null>(null)

const historyLoading = ref(false)
// 全源失败的结构化原因；部分源失败用 historySourceHint 提示，不清空已有数据
const historyError = ref<string | null>(null)
const historySourceHint = ref<string | null>(null)
const historyPoints = ref<ThemeHistoryPoint[]>([])
let historyRequestId = 0

async function loadHistoryData() {
  if (!blockCode.value || !props.sectorName) return
  const requestId = ++historyRequestId
  historyLoading.value = true
  try {
    const result = await fetchThemeHistorySeries({
      themeId: blockCode.value,
      themeName: props.sectorName,
      timeRange: timeRange.value,
    })
    if (requestId !== historyRequestId) return // 过期响应丢弃
    historyPoints.value = result.points
    historyAnchorHint.value = result.anchorDate ?? null
    const failedSources = [result.sectorRows, result.volumeSeries].filter(s => !s.ok)
    if (!result.ok) {
      historyError.value = result.message || '历史数据不可用'
      historySourceHint.value = null
    } else {
      historyError.value = null
      historySourceHint.value = failedSources.length
        ? `部分数据源不可用: ${failedSources.map(s => s.message).filter(Boolean).join('; ')}`
        : null
    }
    // 先解除 loading 态：v-else 分支挂载图表容器（chartRef）后才能渲染 ECharts
    historyLoading.value = false
    await nextTick()
    renderChart()
  } catch (err) {
    if (requestId !== historyRequestId) return
    historyError.value = err instanceof Error ? err.message : '加载历史数据失败'
  } finally {
    if (requestId === historyRequestId) historyLoading.value = false
  }
}

// 统计卡片：热度缺失的槽位不参与计算（不补 0），全缺时字段为 null 显示 '--'
const historyStats = computed(() => {
  const history = historyPoints.value
  const heats = history.map(h => h.heat).filter((v): v is number => v !== null)
  const ztCounts = history.map(h => h.ztCount).filter((v): v is number => v !== null)
  const empty = { max: null, maxTime: 0, min: null, minTime: 0, avg: null, trend: 0, maxZT: null, maxZTTime: 0 }
  if (heats.length === 0) return empty

  const max = Math.max(...heats)
  const maxTime = history.find(h => h.heat === max)?.timestamp || 0
  const min = Math.min(...heats)
  const minTime = history.find(h => h.heat === min)?.timestamp || 0
  const avg = heats.reduce((a, b) => a + b, 0) / heats.length
  const maxZT = ztCounts.length ? Math.max(...ztCounts) : null
  const maxZTTime = maxZT === null ? 0 : history.find(h => h.ztCount === maxZT)?.timestamp || 0

  // 趋势斜率：仅对热度可计算的连续样本做最小二乘
  let trend = 0
  if (heats.length >= 3) {
    const n = heats.length
    const indices = Array.from({ length: n }, (_, i) => i)
    const sumX = indices.reduce((a, b) => a + b, 0)
    const sumY = heats.reduce((a, b) => a + b, 0)
    const sumXY = indices.reduce((a, b, i) => a + b * heats[i], 0)
    const sumX2 = indices.reduce((a, b) => a + b * b, 0)
    const denominator = n * sumX2 - sumX * sumX
    trend = denominator === 0 ? 0 : (n * sumXY - sumX * sumY) / denominator
  }

  return { max, maxTime, min, minTime, avg, trend, maxZT, maxZTTime }
})

function setTimeRange(range: ThemeHistoryTimeRange) {
  timeRange.value = range
  loadHistoryData()
}

function toggleIndicator(indicator: string) {
  if (selectedIndicators.value.includes(indicator)) {
    selectedIndicators.value = selectedIndicators.value.filter(i => i !== indicator)
  } else {
    selectedIndicators.value = [...selectedIndicators.value, indicator]
  }
  nextTick(() => renderChart())
}

function formatHeat(heat: number | null): string {
  if (heat === null) return '--'
  if (heat >= 10000) return (heat / 10000).toFixed(1) + '万'
  if (heat >= 1000) return (heat / 1000).toFixed(1) + 'k'
  return heat.toString()
}

// ✅ 完整的 ECharts 渲染函数（null 缺失值断线，不补 0）
function renderChart() {
  if (!chartRef.value || historyPoints.value.length === 0) return

  // loading/空态的 v-if 状态链会卸载并重挂图表容器（如切换时间范围）：
  // 旧实例绑定的 DOM 已分离，必须 dispose 后重建，否则 setOption 落空、图表空白
  if (chart && chart.getDom() !== chartRef.value) {
    chart.dispose()
    chart = null
  }
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const history = historyPoints.value
  const indicators = selectedIndicators.value
  const series: any[] = []

  // 热度曲线
  if (indicators.includes('heat')) {
    series.push({
      name: '热度',
      type: 'line',
      data: history.map(h => h.heat),
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      connectNulls: false,
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
      data: history.map(h => h.ztCount),
      itemStyle: { color: '#ff4757' },
      barWidth: 8,
      yAxisIndex: 1
    })
  }

  // 热度排名曲线（y 轴反向：排名越靠前数值越小，向上=走强）
  if (indicators.includes('rank')) {
    series.push({
      name: '热度排名',
      type: 'line',
      data: history.map(h => h.rank),
      smooth: true,
      connectNulls: false,
      lineStyle: { color: '#e67e22', width: 1.5 },
      symbol: 'triangle',
      symbolSize: 5,
      yAxisIndex: 4
    })
  }

  // 轮动状态阶梯线（离散六态，类别轴；缺失/未知断线不伪造）
  if (indicators.includes('rotationState')) {
    series.push({
      name: '轮动状态',
      type: 'line',
      step: 'middle',
      data: history.map(h => {
        const label = h.rotationState ? rotationStateLabelText(h.rotationState) : null
        return label && ROTATION_STATE_AXIS_CATEGORIES.includes(label) ? label : null
      }),
      connectNulls: false,
      lineStyle: { color: '#9b59b6', width: 1.5 },
      symbol: 'rect',
      symbolSize: 5,
      yAxisIndex: 5
    })
  }

  // 净流入趋势曲线（half_hour rows mainNetInflow，部分槽位缺失断线）
  if (indicators.includes('mainNetInflow')) {
    series.push({
      name: '净流入趋势',
      type: 'line',
      data: history.map(h => h.mainNetInflow),
      smooth: true,
      connectNulls: false,
      lineStyle: { color: '#1abc9c', width: 1.5 },
      symbol: 'none',
      yAxisIndex: 6
    })
  }

  // 平均涨跌曲线
  if (indicators.includes('change')) {
    series.push({
      name: '平均涨跌',
      type: 'line',
      data: history.map(h => h.avgChange),
      smooth: true,
      connectNulls: false,
      lineStyle: { color: '#2ed573', width: 1.5, type: 'dashed' },
      symbol: 'diamond',
      symbolSize: 4,
      yAxisIndex: 2
    })
  }

  // 成交额曲线（题材成分股 stock rows 聚合，单位元）
  if (indicators.includes('volume')) {
    series.push({
      name: '成交额',
      type: 'line',
      data: history.map(h => h.totalAmount),
      smooth: true,
      connectNulls: false,
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

  // 跨天范围时 x 轴标签带日期，单日内只显示槽位时间
  const uniqueDates = new Set(history.map(h => h.tradingDate))
  const xLabels = history.map(h =>
    uniqueDates.size > 1 ? `${h.tradingDate.slice(5)} ${h.slotTime}` : h.slotTime
  )

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
      data: xLabels,
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
        name: '成交额',
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)' }
      },
      {
        type: 'value',
        name: '热度排名',
        inverse: true,
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)' }
      },
      {
        type: 'category',
        name: '轮动状态',
        data: ROTATION_STATE_AXIS_CATEGORIES,
        splitLine: { show: false },
        axisLabel: { color: 'var(--text-secondary)', fontSize: 10 }
      },
      {
        type: 'value',
        name: '净流入',
        splitLine: { show: false },
        axisLabel: {
          color: 'var(--text-secondary)',
          formatter: (value: number) => (Math.abs(value) >= 1e8 ? `${(value / 1e8).toFixed(1)}亿` : `${(value / 1e4).toFixed(0)}万`)
        }
      }
    ],
    series,
    backgroundColor: 'transparent'
  }

  chart.setOption(option)
  chart.resize()
}

// 监听窗口大小变化（具名 handler：卸载时可移除，避免面板反复开关累积监听器）
function handleWindowResize() {
  if (chart) {
    chart.resize()
  }
}

onMounted(() => {
  window.addEventListener('resize', handleWindowResize)
})

// 在组件卸载时销毁图表
onUnmounted(() => {
  window.removeEventListener('resize', handleWindowResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})

// 监听指标选择变化重新渲染（数据加载由 loadHistoryData 负责）
watch(
  selectedIndicators,
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

    await themeFacade.refreshRuntime({ force: true, source: 'ui' })
    if (blockCode.value) {
      themeStockRows.value = await sectorAnalyzer.loadSectorStocks(blockCode.value, props.sectorName, true)
    }
    // 历史趋势页签打开时同步刷新历史序列
    if (view.value === 'history') {
      await loadHistoryData()
    }

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
function getVolumeRatioColor(ratio: number): string {
  // 绝对阈值（golden 3 日量比：>1 放量、<1 缩量）
  if (ratio >= 1.05) return '#ff4757' // 放量
  if (ratio >= 0.95) return '#ffb142' // 常态（1.0 附近）
  if (ratio >= 0.5) return '#4a90e2' // 缩量
  return '#7f8c8d' // 地量
}

function getVolumeRatioDesc(ratio: number): string {
  if (ratio >= 1.05) return '放量'
  if (ratio >= 0.95) return '常态'
  if (ratio >= 0.5) return '缩量'
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
    // 首次进入或数据为空时拉取；已有数据只重渲染
    if (historyPoints.value.length === 0 && !historyError.value) {
      loadHistoryData()
    } else {
      nextTick(() => renderChart())
    }
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
  /* 概览指标一行四列（2026-09-27 用户反馈） */
  grid-template-columns: repeat(4, 1fr);
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

/* 涨停原因列：限宽省略，悬停看全文；其余列由内容自适应宽度 */
.stocks-table .reason-text {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
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

/* 历史数据结构化状态（加载/错误/空态） */
.history-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 12px;
}

.history-source-hint {
  padding: 6px 10px;
  background: rgba(255, 177, 66, 0.12);
  border: 1px solid rgba(255, 177, 66, 0.3);
  border-radius: 8px;
  color: #ffb142;
  font-size: 11px;
}

.time-range-selector,
.indicator-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
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

.history-anchor-hint {
  padding: 6px 12px;
  border: 1px dashed var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

/* 轮动状态区（概览合并字段） */
.rotation-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rotation-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.rotation-metrics .stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.state-badge {
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  font-size: 11px;
}
.state-mainline { color: #f5c15b; border-color: #f5c15b; }
.state-inflow { color: #f55b5b; border-color: rgba(245, 91, 91, 0.5); }
.state-emerging { color: #5bd4f5; border-color: #5bd4f5; }
.state-neutral { color: var(--text-secondary); }
.state-outflow { color: #4caf7d; border-color: rgba(76, 175, 125, 0.5); }
.state-cooling { color: #5ba3f5; border-color: rgba(91, 163, 245, 0.5); }
.state-unknown { color: var(--text-secondary); }
.rotation-flow-up { color: #f55b5b; }
.rotation-flow-down { color: #4caf7d; }
.info-value.flags { color: #f5c15b; }
.rotation-missing {
  padding: 10px 12px;
  color: var(--text-secondary);
  font-size: 12px;
}
</style>
