<!-- src/components/common/DataTable.vue -->

<template>
  <div class="data-table-container">
    <!-- ✅ 增强的加载状态 -->
    <div v-if="isLoading && !sortedStocks.length" class="loading-state">
      <div class="loading-content">
        <span class="loading-icon">🐉</span>
        <span class="loading-text">{{ loadingMessage }}</span>
        <div class="loading-progress" v-if="loadingProgress > 0">
          <div class="progress-bar" :style="{ width: loadingProgress + '%' }"></div>
          <span class="progress-text">{{ loadingProgress }}%</span>
        </div>
      </div>
    </div>

    <!-- 骨架屏（可选，当有旧数据时显示）-->
    <div v-else-if="isLoading && sortedStocks.length" class="skeleton-overlay">
      <div class="skeleton-loading">
        <span class="loading-icon">🔄</span>
        <span>更新中...</span>
        <div class="loading-progress small" v-if="loadingProgress > 0">
          <div class="progress-bar" :style="{ width: loadingProgress + '%' }"></div>
        </div>
      </div>
    </div>

    <!-- 有数据才显示表格 -->
    <template v-else-if="sortedStocks.length">
      <!-- 表格头部 - 使用 grid 布局，固定列宽 -->
      <div class="table-header" ref="headerRef" :style="{ width: totalWidth + 'px' }">
        <!-- 分组表头 -->
        <div v-if="hasGroups" class="header-group-row" :style="gridTemplateStyle">
          <div v-for="group in visibleGroups" :key="group" class="header-group-cell"
            :style="{ gridColumn: `span ${getGroupColspan(group)}` }">
            {{ getGroupLabel(group) }}
          </div>
        </div>

        <!-- 列表头 -->
        <div class="header-row" :style="gridTemplateStyle">
          <div v-for="col in visibleColumns" :key="col.key" class="header-cell"
            :class="{ sorted: uiStore.sort.field === col.key }" @click="uiStore.toggleSort(col.key)">
            <template v-if="col.key === 'compRank'">
              <button class="rank-collapse-toggle" :class="{ collapsed: rankColumnsCollapsed }"
                :title="rankColumnsCollapsed ? '展开热榜排名列' : '折叠热榜排名列'" @click.stop="toggleRankColumns" type="button">
                <span class="rank-collapse-arrow">{{ rankColumnsCollapsed ? '◀' : '▶' }}</span>
              </button>
              {{ col.label }}
            </template>
            <template v-else-if="col.key === 'synergyTier'">
              <button class="rank-collapse-toggle" :class="{ collapsed: observationColumnsCollapsed }"
                :title="observationColumnsCollapsed ? '展开观察列（共振/趋势/热度/量价/周期）' : '隐藏观察列（共振/趋势/热度/量价/周期）'"
                @click.stop="toggleObservationColumns" type="button">
                <span class="rank-collapse-arrow">{{ observationColumnsCollapsed ? '◀' : '▶' }}</span>
              </button>
              {{ col.label }}
            </template>
            <template v-else-if="col.key === 'lianbanStr'">
              {{ col.label }}
              <button class="rank-collapse-toggle" :class="{ collapsed: limitupColumnsCollapsed }"
                :title="limitupColumnsCollapsed ? '展开首次/最后涨停/封单/开板' : '折叠首次/最后涨停/封单/开板'"
                @click.stop="toggleLimitupColumns" type="button">
                <span class="rank-collapse-arrow">{{ limitupColumnsCollapsed ? '◀' : '▶' }}</span>
              </button>
            </template>
            <template v-else-if="col.key === 'turnover'">
              {{ col.label }}
              <button class="rank-collapse-toggle" :class="{ collapsed: quoteColumnsCollapsed }"
                :title="quoteColumnsCollapsed ? '展开流通值/总市值/市盈率/市净率' : '折叠流通值/总市值/市盈率/市净率'"
                @click.stop="toggleQuoteColumns" type="button">
                <span class="rank-collapse-arrow">{{ quoteColumnsCollapsed ? '◀' : '▶' }}</span>
              </button>
            </template>
            <template v-else>{{ col.label }}</template>
            <span v-if="uiStore.sort.field === col.key" class="sort-icon">
              {{ uiStore.sort.order === 'asc' ? '↑' : '↓' }}
            </span>
          </div>
        </div>
      </div>

      <!-- 表格主体 - 使用 grid 布局，和数据头完全一致 -->
      <div class="table-body" ref="bodyRef" @scroll="handleBodyScroll">
        <div v-for="(stock, index) in sortedStocks" :key="stock.code" :data-code="stock.code" class="data-row" :class="[
          index % 2 === 0 ? 'row-even' : 'row-odd',
          {
            selected: uiStore.selectedCode === stock.code,
          },
        ]" :style="gridTemplateStyle" @click="onRowClick($event, stock.code)"
          @dblclick="openStockDetailFromRow($event, stock)" @contextmenu.prevent="showContextMenu($event, stock)">

          <!-- 动态渲染所有列，保持和表头一致 -->
          <div v-for="col in visibleColumns" :key="col.key" class="cell" :class="getCellClass(col.key, stock)"
            :data-key="col.key">
            <!-- 题材列 -->
            <template v-if="col.key === 'themes'">
              <div class="themes-cell">
                <span v-if="getStockThemes(stock).length > 0" class="themes-badge"
                  :class="getThemeBadgeClass(getStockThemes(stock))" :style="getThemeStyle(stock)"
                  @mouseenter="showThemeTooltip($event, stock)" @mousemove="moveRowTooltip($event)"
                  @mouseleave="hideRowTooltip">
                  {{ getThemeDisplay(getStockThemes(stock)) }}
                </span>
                <span v-else class="themes-empty">-</span>
              </div>
            </template>

            <!-- 平台排名列的特殊渲染-->
            <template v-else-if="isPlatformRankKey(col.key)">
              <span :class="[
                Number(getStockValue(stock, col.key)) >= 4 && Number(getStockValue(stock, col.key)) <= 10 ? 'rank-4-10' : '',
                getPlatformRankClass(Number(getStockValue(stock, col.key)))
              ]">
                {{ formatPlatformRank(Number(getStockValue(stock, col.key))) }}
              </span>
            </template>

            <template v-else-if="col.key === 'name'">
              <span class="stock-name-text">{{ formatCell(col.key, stock) }}</span>
            </template>

            <!-- 共振强度列：方向+数值%（2026-08-24 取消档位徽章） -->
            <template v-else-if="col.key === 'resonanceIntensity'">
              <div class="observation-cell" @click.stop="openObservationPanel(stock, 'resonance')"
                @mouseenter="showTierTooltip($event, stock, 'resonanceIntensity')"
                @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
                <template v-if="getResonanceCellValue(stock) != null">
                  <span :class="getResonanceCellClass(stock)">
                    {{ getDirectionArrow(getResonanceDirection(stock)) }}
                  </span>
                  <span :class="getResonanceCellClass(stock)">{{ getResonanceCellValue(stock) }}%</span>
                </template>
                <span v-else class="trend-steady">--</span>
              </div>
            </template>

            <template v-else-if="col.key === 'rankTrendStrength'">
              <div class="observation-cell" @click.stop="openObservationPanel(stock, 'technical')"
                @mouseenter="showTierTooltip($event, stock, 'rankTrendStrength')"
                @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
                <!-- 2026-08-24：趋势改回方向+数值%（取消横截面徽章，热度独立成列） -->
                <template v-if="getRankTrendStrengthValue(stock) != null">
                  <span :class="getDirectionClass(getRankTrendDirection(stock))">
                    {{ getDirectionArrow(getRankTrendDirection(stock)) }}
                  </span>
                  <span :class="getDirectionClass(getRankTrendDirection(stock))">{{ getRankTrendStrengthValue(stock)
                  }}%</span>
                </template>
                <span v-else class="trend-steady">--</span>
                <!-- 2026-09-21 用户裁决：趋势徽章改 MACD 金/死叉事件触发（py technical.macd.cross，
                     交叉帧才非 none 的事件语义；缺字段→无徽章） -->
                <span v-if="getMacdCrossBadge(stock) === 'golden'" class="ma-badge golden" title="MACD 金叉">▲</span>
                <span v-else-if="getMacdCrossBadge(stock) === 'death'" class="ma-badge death" title="MACD 死叉">▼</span>
              </div>
            </template>

            <!-- 热度列（技术字段 crossSection，UI 展示名「热度」）：方向+数值%（2026-08-24 新增独立列，percentile 推算方向/分值） -->
            <template v-else-if="col.key === 'crossSection'">
              <div class="observation-cell cross-section-cell"
                @mouseenter="showTierTooltip($event, stock, 'crossSection')" @mousemove="moveConfidenceTooltip($event)"
                @mouseleave="hideConfidenceTooltip">
                <template v-if="getCrossSectionValue(stock) != null">
                  <span :class="getCrossSectionClass(stock)">{{ getDirectionArrow(getCrossSectionDirection(stock))
                  }}</span>
                  <span :class="getCrossSectionClass(stock)">{{ getCrossSectionValue(stock) }}%</span>
                </template>
                <span v-else class="trend-steady">--</span>
              </div>
            </template>

            <template v-else-if="col.key === 'lifecycleOpportunity'">
              <div class="observation-cell lifecycle-cell" @click.stop="openObservationPanel(stock, 'lifecycle')"
                @mouseenter="showTierTooltip($event, stock, 'lifecycleOpportunity')"
                @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
                <!-- 生命周期为环境门（2026-08-16 优化：lifecycle 档位无方向区分度，不做方向色徽章）：
                     显示 stage 中文 + 环境色；veto 状态在悬停提示中注明（2026-08-16 去"否决"二字） -->
                <!-- 样本不足（2026-09-10 口径统一，spec §4.1）：数据质量声明优先于 lifecycle 兜底"冷却"，
                     不再显示误导性默认状态（fail-visible：样本不足不伪装成业务态） -->
                <template v-if="isLifecycleSampleInsufficient(stock)">
                  <span class="lifecycle-env-insufficient">样本不足</span>
                </template>
                <template v-else-if="getLifecycleStage(stock) != null">
                  <span :class="lifecycleEnvClass(stock)">{{ getLifecycleStageLabel(stock) }}</span>
                </template>
                <span v-else class="trend-steady">--</span>
              </div>
            </template>

            <template v-else-if="col.key === 'volumePriceQuadrant'">
              <div class="observation-cell" @click.stop="openObservationPanel(stock, 'volumePrice')"
                @mouseenter="showTierTooltip($event, stock, 'volumePriceQuadrant')"
                @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
                <!-- 2026-08-24：量价列改方向+数值%（取消档位徽章） -->
                <span :class="getQuadrantClass(stock)">{{ getQuadrantText(stock) }}</span>
              </div>
            </template>

            <!-- synergy 合并档位列（回测方案配套：消费 synergy.signalTier，前端只展示） -->
            <template v-else-if="col.key === 'synergyTier'">
              <div class="observation-cell synergy-tier-cell"
                @mouseenter="showTierTooltip($event, stock, 'synergyTier')" @mousemove="moveConfidenceTooltip($event)"
                @mouseleave="hideConfidenceTooltip">
                <TierBadge v-if="getSynergyTier(stock)" :tier="getSynergyTier(stock)" />
                <span v-else class="trend-steady">--</span>
              </div>
            </template>

            <template v-else-if="col.key === 'zlje' || col.key === 'zljzb'">
              <span :title="getMoneyFlowTitle(col.key, stock)">{{ formatCell(col.key, stock) }}</span>
            </template>

            <template v-else-if="col.key === 'volumeRatio'">
              <span :class="getVolumeRatioClass(stock)" :title="getVolumeRatioTitle(stock)">{{ formatCell(col.key,
                stock) }}</span>
            </template>

            <!-- 涨停原因列：限宽省略，悬停看全文；非涨停股显示 '-'（reason_type 仅涨停股有值） -->
            <template v-else-if="col.key === 'limitUpReason'">
              <span class="limit-up-reason-text" :title="stock.limitUpReason || ''">{{ stock.limitUpReason || '-'
              }}</span>
            </template>

            <template v-else>
              {{ formatCell(col.key, stock) }}
            </template>


          </div>
        </div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="empty-state">
      <span class="empty-icon">📭</span>
      <span>暂无数据</span>
    </div>

    <!-- 右键菜单 -->
    <div v-if="contextMenu.visible" class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }" ref="contextMenuRef">
      <div class="menu-item" @click="addToFavorite"><span class="menu-icon">⭐</span> 加入自选</div>
      <div class="menu-item" @click="addToCandidatePool"><span class="menu-icon">🎯</span> {{ candidateMenuLabel }}
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @mouseenter="showBoardMenu" @click.stop>
        <span class="menu-icon">📁</span> 加入板块
        <span class="submenu-indicator">▶</span>
        <div v-if="showBoardSubMenu" class="submenu">
          <div v-if="boardList.length === 0" class="submenu-item disabled">暂无板块</div>
          <div v-for="board in boardList" :key="board.id" class="submenu-item" @click="addToSpecificBoard(board.id)">
            <span class="board-color-dot" :style="{ backgroundColor: board.color }"></span>
            {{ board.name }}
            <span class="board-count">{{ board.count }}</span>
          </div>
          <div class="submenu-divider"></div>
          <div class="submenu-item" @click="createNewBoard">
            <span class="menu-icon">+</span> 新建板块
          </div>
        </div>
      </div>
      <div class="menu-item" @click="copyCode"><span class="menu-icon">📋</span> 复制代码</div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="viewTheme"><span class="menu-icon">📊</span> 查看题材</div>
      <div class="menu-item" @click="viewDetails"><span class="menu-icon">🔍</span> 查看详情</div>
      <div class="menu-item" @click="openRankTrendForStock">
        <span class="menu-icon">📊</span> 排名趋势
      </div>
    </div>
    <!-- 排名趋势面板 -->
    <RankTrendPanel :visible="rankTrendPanelVisible" :triggerRect="rankTrendPanelTriggerRect"
      :stock-code="rankTrendPanelStockCode" @update:visible="rankTrendPanelVisible = $event"
      @close="rankTrendPanelVisible = false" />
    <RankTrendObservationPanel :visible="observationPanelVisible" :stock="observationPanelStock"
      :initial-track="observationPanelTrack" @close="observationPanelVisible = false" />
    <div v-if="confidenceTooltip.visible" class="confidence-tooltip"
      :style="{ left: `${confidenceTooltip.x}px`, top: `${confidenceTooltip.y}px` }">
      {{ confidenceTooltip.content }}
    </div>
    <div v-if="rowTooltip.visible" class="row-tooltip" :style="{ left: `${rowTooltip.x}px`, top: `${rowTooltip.y}px` }">
      {{ rowTooltip.content }}
    </div>
  </div>

</template>

<script setup lang="ts">
import { FUND_SOURCE } from '@/config/fundSources'
import { debugLog } from '@/utils/logger'
import TierBadge from '@/components/common/TierBadge.vue'
import { ref, computed, defineAsyncComponent, onMounted, onUnmounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { Stock, Board } from '../../types'
import { EventManager } from '../../utils/eventManager'
import { AppEvents } from '../../types'
import { useUIStore } from '../../stores/ui'
import { useFavoriteStore } from '../../stores/favorite'
import { dataLoader } from '../../services/dataLoader'
import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import { analyzeTradingPoolCandidate } from '@/services/candidate/TradingPoolAnalysisService'
import { sendHotlistSelection } from '@/services/hotlist/ThsBigOrderFollowBridge'
// RankTrend 面板引 echarts，异步加载避免拖累首屏 chunk
const RankTrendPanel = defineAsyncComponent(() => import('../../components/panels/RankTrendPanel.vue'))
const RankTrendObservationPanel = defineAsyncComponent(() => import('../../components/panels/RankTrendObservationPanel.vue'))
import type { ObservationTrack } from '@/services/rankTrend/RankTrendObservationService'
import {
  getLifecycleTier,
  getRankTrendTier,
  getResonanceTier,
  getSynergyTier,
  getSynergyTierDetail,
  getSynergyTierReasons,
  getSynergyVoteBreakdown,
  getCrossSectionTier,
  getCrossSectionDetail,
  getVolumePriceTier,
  tierBadgeClass,
  tierBadgeLabel,
} from '@/services/rankTrend/tierDisplay'
import { classifyVolumeRatio, volumeRatioStateLabel } from '@/utils/volumeRatio'
import {
  classifyFundSignal,
  getVolumePriceQuadrantLabel,
  volumeStateLabel,
} from '@/services/rankTrend/volumePriceValidation'
const props = defineProps<{
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', code: string): void
}>()

// ========== Stores ==========
const uiStore = useUIStore()
const favoriteStore = useFavoriteStore()
const { sortedStocks } = storeToRefs(uiStore)

// ========== 加载状态 ==========
const isLoading = computed(() => {
  return props.loading !== undefined ? props.loading : dataLoader.isLoading?.value?.active || false
})

const loadingProgress = computed(() => {
  return dataLoader.isLoading?.value?.progress || 0
})

const loadingMessage = computed(() => {
  return dataLoader.isLoading?.value?.message || '加载数据中...'
})

const localSignalLabels: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  hold: '观望',
  none: '无',
}

const localCrossLabels: Record<string, string> = {
  golden: '金叉',
  death: '死叉',
  none: '无',
}

const localAttentionStageLabels: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
}

// ========== 状态 ==========
const headerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
// 右键菜单
const contextMenu = ref({
  visible: false,
  x: 0,
  y: 0,
  stock: null as Stock | null,
})
const contextMenuRef = ref<HTMLElement | null>(null)
const openCandidateId = ref('')
const confidenceTooltip = ref({
  visible: false,
  x: 0,
  y: 0,
  content: '',
})
const rowTooltip = ref({
  visible: false,
  x: 0,
  y: 0,
  content: '',
})
const observationPanelVisible = ref(false)
const observationPanelStock = ref<any | null>(null)
const observationPanelTrack = ref<ObservationTrack>('resonance')

// 板块列表状态
const boardList = ref<Board[]>([])
const showBoardSubMenu = ref(false)

// ========== 列配置（保持不变）==========
const columns = [
  { key: 'code', label: '代码', group: 'basic', always: true },
  { key: 'name', label: '名称', group: 'basic', always: true },
  { key: 'themes', label: '题材', group: 'basic', always: true },
  { key: 'price', label: '最新价', group: 'basic', always: true },
  { key: 'change', label: '涨幅%', group: 'basic', always: true },
  { key: 'speed', label: '涨速%', group: 'basic', always: true },
  { key: 'emRank', label: '东财', group: 'platform', always: true },
  { key: 'thsRank', label: '同花顺', group: 'platform', always: true },
  { key: 'kplRank', label: '开盘啦', group: 'platform', always: true },
  { key: 'tdxRank', label: '通达信', group: 'platform', always: true },
  { key: 'xqRank', label: '雪球', group: 'platform', always: true },
  { key: 'clsRank', label: '财联社', group: 'platform', always: true },
  { key: 'tgbRank', label: '淘股吧', group: 'platform', always: true },
  { key: 'dzhRank', label: '大智慧', group: 'platform', always: true },
  { key: 'avgRank', label: '均榜', group: 'comprehensive', always: true },
  { key: 'compRank', label: '综合', group: 'comprehensive', always: true },
  { key: 'resonanceIntensity', label: '共振', group: 'comprehensive', always: true },
  { key: 'rankTrendStrength', label: '趋势', group: 'comprehensive', always: true },
  { key: 'crossSection', label: '热度', group: 'comprehensive', always: true },
  { key: 'volumePriceQuadrant', label: '量价', group: 'comprehensive', always: true },
  { key: 'lifecycleOpportunity', label: '周期', group: 'comprehensive', always: true },
  { key: 'synergyTier', label: '五维', group: 'comprehensive', always: true },
  { key: 'zlje', label: '主力净额', group: 'money', always: true },
  { key: 'zljzb', label: '主力%', group: 'money', always: true },
  { key: 'volumeRatio', label: '3日量比', group: 'quote', always: true },
  { key: 'turnoverRate', label: '换手%', group: 'quote', always: true },
  { key: 'volume', label: '成交量', group: 'quote', always: true },
  { key: 'turnover', label: '成交额', group: 'quote', always: true },
  { key: 'cirMV', label: '流通值', group: 'quote', always: true },
  { key: 'totalMV', label: '总市值', group: 'quote', always: true },
  { key: 'pe', label: '市盈率', group: 'quote', always: true },
  { key: 'pb', label: '市净率', group: 'quote', always: true },
  // 涨停相关（2026-09-02）：取值来源同花顺涨停池（主池+细分池），字段语义与题材面板成分股一致；
  // 非涨停股保持缺失显示 '-'，不伪造
  { key: 'lianbanStr', label: '连板', group: 'limitup', always: true },
  { key: 'firstZtTime', label: '首次涨停', group: 'limitup', always: true },
  { key: 'lastZtTime', label: '最后涨停', group: 'limitup', always: true },
  { key: 'fengdan', label: '封单(亿)', group: 'limitup', always: true },
  { key: 'openNum', label: '开板', group: 'limitup', always: true },
  { key: 'limitUpReason', label: '涨停原因', group: 'limitup', always: true },
]

// ========== 列宽映射==========
const COLUMN_WIDTHS: Record<string, string> = {
  code: '60px',
  name: '84px',
  themes: '120px',
  price: '70px',
  change: '70px',
  speed: '70px',
  emRank: '50px',
  thsRank: '50px',
  kplRank: '50px',
  tdxRank: '50px',
  xqRank: '50px',
  clsRank: '50px',
  tgbRank: '50px',
  dzhRank: '50px',
  avgRank: '50px',
  compRank: '50px',
  resonanceIntensity: '60px',
  rankTrendStrength: '60px',
  crossSection: '60px',
  volumePriceQuadrant: '60px',
  lifecycleOpportunity: '60px',
  synergyTier: '60px',
  zlje: '80px',
  zljzb: '70px',
  volume: '85px',
  volumeRatio: '60px',
  turnover: '80px',
  turnoverRate: '80px',
  cirMV: '90px',
  totalMV: '90px',
  pe: '65px',
  pb: '65px',
  lianbanStr: '70px',
  firstZtTime: '75px',
  lastZtTime: '75px',
  fengdan: '70px',
  openNum: '50px',
  limitUpReason: '200px',
}

// ========== 计算属性==========
// 可折叠热榜排名列（8 平台 + 均榜）：默认折叠以缓解横向溢出，【综合】列左侧三角按钮切换
const COLLAPSIBLE_RANK_KEYS = new Set([
  'emRank', 'thsRank', 'kplRank', 'tdxRank', 'xqRank', 'clsRank', 'tgbRank', 'dzhRank', 'avgRank',
])
const rankColumnsCollapsed = ref(true)
const toggleRankColumns = () => {
  rankColumnsCollapsed.value = !rankColumnsCollapsed.value
}

// 可折叠观察列（共振/趋势/热度/量价/周期）：默认展开，【五维度】列左侧三角按钮切换（隐藏/展开五列明细）
const COLLAPSIBLE_OBSERVATION_KEYS = new Set([
  'resonanceIntensity', 'rankTrendStrength', 'crossSection', 'volumePriceQuadrant', 'lifecycleOpportunity',
])
const observationColumnsCollapsed = ref(false)
const toggleObservationColumns = () => {
  observationColumnsCollapsed.value = !observationColumnsCollapsed.value
}

// 可折叠行情列（流通值/总市值/市盈率/市净率）：默认折叠，【成交额】列 title 右侧三角按钮切换；
// 3日量比/换手%/成交量/成交额始终显示（2026-09-02 用户口径）
const COLLAPSIBLE_QUOTE_KEYS = new Set(['cirMV', 'totalMV', 'pe', 'pb'])
const quoteColumnsCollapsed = ref(true)
const toggleQuoteColumns = () => {
  quoteColumnsCollapsed.value = !quoteColumnsCollapsed.value
}

// 可折叠涨停明细列（首次/最后涨停/封单/开板）：默认折叠，【连板】列 title 右侧三角按钮切换；
// 连板/涨停原因始终显示（2026-09-02 用户口径）
const COLLAPSIBLE_LIMITUP_KEYS = new Set(['firstZtTime', 'lastZtTime', 'fengdan', 'openNum'])
const limitupColumnsCollapsed = ref(true)
const toggleLimitupColumns = () => {
  limitupColumnsCollapsed.value = !limitupColumnsCollapsed.value
}

const visibleColumns = computed(() =>
  columns.filter(
    col =>
      col.always &&
      !(rankColumnsCollapsed.value && COLLAPSIBLE_RANK_KEYS.has(col.key)) &&
      !(observationColumnsCollapsed.value && COLLAPSIBLE_OBSERVATION_KEYS.has(col.key)) &&
      !(quoteColumnsCollapsed.value && COLLAPSIBLE_QUOTE_KEYS.has(col.key)) &&
      !(limitupColumnsCollapsed.value && COLLAPSIBLE_LIMITUP_KEYS.has(col.key)),
  )
)
const visibleGroups = computed(() => {
  const groups = new Set<string>()
  visibleColumns.value.forEach(col => groups.add(col.group))
  return Array.from(groups)
})
const hasGroups = computed(() => visibleGroups.value.length > 0)
const totalWidth = computed(() => {
  return visibleColumns.value.reduce((sum, col) => {
    const widthStr = COLUMN_WIDTHS[col.key] || '70px'
    const width = parseInt(widthStr)
    return sum + width
  }, 20)
})
const gridTemplateStyle = computed(() => {
  const widths = visibleColumns.value.map(col => COLUMN_WIDTHS[col.key] || '70px')
  return {
    display: 'grid',
    gridTemplateColumns: widths.join(' '),
    width: 'fit-content',
  }
})
const candidateMenuLabel = computed(() => (openCandidateId.value ? '查看候选详情' : '加入候选池'))

// ========== 从表格数据获取题材信息 ==========

// 所有股票数据
const allStocks = computed(() => sortedStocks.value)

// 题材信息
const viewTheme = () => {
  if (contextMenu.value.stock) {
    const themes = getStockThemes(contextMenu.value.stock)
    if (themes && themes.length > 0) {
      const firstTheme = themes[0]
      const themeName = typeof firstTheme === 'string' ? firstTheme : firstTheme.name
      // ✅ 保留事件发射
      EventManager.emit('sector:show-detail', {
        themeName: themeName,
      })
    } else {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `📊 ${contextMenu.value.stock.name} 暂无题材数据`,
        duration: 1500,
        type: 'info',
      })
    }
  }
  hideContextMenu()
}

const getStockThemes = (stock: Stock) => {
  const tagThemes = (stock.tags || []).map((tag: any) => {
    const tagName = tag?.Name || tag?.name || tag
    return {
      id: `tag_${tagName}`,
      name: tagName,
      Name: tagName,
      type: 'tag',
      heatScore: 0,
    }
  })
  return removeDuplicateThemes([...(stock.themes || []), ...tagThemes])
}

const getThemeDisplay = (themes: any[]) => {
  if (!themes || themes.length === 0) return '-'

  const normalThemes = themes.filter(t => t.type !== 'tag')
  const tags = themes.filter(t => t.type === 'tag')

  if (normalThemes.length > 0) {
    const firstTheme = normalThemes[0]
    const themeName = firstTheme.name || firstTheme
    const extraCount = normalThemes.length - 1 + tags.length
    return extraCount > 0 ? `${themeName} +${extraCount}` : themeName
  }

  if (tags.length === 1) return `🏷️ ${tags[0].Name}`
  if (tags.length > 1) return `🏷️ ${tags[0].Name} +${tags.length - 1}`
  return '-'
}

const getThemesTitle = (themes: any[]) => {
  if (!themes || themes.length === 0) return ''
  return themes.map(t => {
    if (t.type === 'tag') return `🏷️ ${t.Name}`
    return t.name || t
  }).filter(Boolean).join(' · ')
}

const stringToColor = (str: string) => {
  if (!str) return { bg: 'rgba(107, 114, 128, 0.15)', border: '#6b7280', text: '#9ca3af' }

  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }

  const h = Math.abs(hash % 360)
  const s = 60 + (Math.abs(hash >> 4) % 20)
  const l = 65 + (Math.abs(hash >> 8) % 10)

  return {
    bg: `hsla(${h}, ${s}%, ${l}%, 0.15)`,
    border: `hsl(${h}, ${s}%, ${l}%)`,
    text: `hsl(${h}, ${s}%, ${l}%)`,
  }
}

const getThemeStyle = (stock: any) => {
  const themes = getStockThemes(stock)
  if (!themes || themes.length === 0) return {}

  const normalTheme = themes.find((t: any) => t.type !== 'tag')
  if (normalTheme) {
    const themeName = typeof normalTheme === 'string' ? normalTheme : normalTheme.name || ''
    return stringToColor(themeName)
  }

  return {
    bg: 'rgba(156, 39, 176, 0.15)',
    border: '#9c27b0',
    text: '#9c27b0'
  }
}

const getThemeBadgeClass = (themes: any[]) => {
  if (!themes || themes.length === 0) return ''

  const normalThemes = themes.filter(t => t.type !== 'tag')
  const tags = themes.filter(t => t.type === 'tag')

  if (tags.length > 0 && normalThemes.length === 0) return 'theme-tag-only'
  if (themes.length >= 3) return 'theme-multiple'
  if (themes.length === 2) return 'theme-double'
  return 'theme-single'
}

const removeDuplicateThemes = (themes: any[]): any[] => {
  if (!themes || !Array.isArray(themes)) return []

  const themeMap = new Map()
  const tagMap = new Map()

  themes.forEach(theme => {
    if (!theme) return

    if (theme.type === 'tag') {
      const tagName = theme.Name || theme.name
      if (tagName && !tagMap.has(tagName)) {
        tagMap.set(tagName, theme)
      }
      return
    }

    let id: string
    if (typeof theme === 'string') {
      id = theme
    } else {
      id = theme.id || theme.name || JSON.stringify(theme)
    }
    if (!id) return

    if (themeMap.has(id)) {
      const existing = themeMap.get(id)
      if (typeof existing === 'string' && typeof theme === 'object') {
        themeMap.set(id, theme)
      } else if (typeof existing === 'object' && typeof theme === 'object') {
        themeMap.set(id, { ...existing, ...theme })
      }
    } else {
      themeMap.set(id, theme)
    }
  })

  return [...Array.from(themeMap.values()), ...Array.from(tagMap.values())]
}

// 题材悬浮提示：合并原题材 title 与行详情，避免同一行出现两套 tooltip。
const getMergedThemeTooltipTitle = (stock: Stock) => {
  let title = ''
  const themesTitle = getThemesTitle(getStockThemes(stock))

  title += `${stock.name} (${stock.code})`

  if (themesTitle) {
    title += `\n📌 题材: ${themesTitle}\n`
  }

  // 标签
  if (stock.tags && stock.tags.length > 0) {
    const tagNames = stock.tags.map((tag: any) => tag.Name || tag).filter(Boolean)
    if (tagNames.length > 0) {
      title += `\n🏷️ 标签: ${tagNames.join('/')}\n`
    }
  }

  // 关联原因（主营业务静态文本，题材映射来源）
  if (stock.reason) {
    title += `\n📋 关联原因:\n`
    let reason = stock.reason
    const sentences = reason.split(/([。；！？])/g)
    const paragraphs: string[] = []
    for (let i = 0; i < sentences.length; i += 2) {
      const sentence = (sentences[i] || '') + (sentences[i + 1] || '')
      if (sentence.trim()) {
        paragraphs.push(sentence.trim())
      }
    }
    paragraphs.slice(0, 5).forEach((para, idx) => {
      const displayPara = para.length > 60 ? para.slice(0, 60) + '...' : para
      title += `   ${idx + 1}. ${displayPara}\n`
    })
    if (paragraphs.length > 5) {
      title += `   ... 共 ${paragraphs.length} 条\n`
    }
  }

  // 涨停原因（同花顺涨停池 reason_type，仅涨停股有值；与关联原因是两个不同字段）
  if (stock.limitUpReason) {
    title += `\n🚀 涨停原因: ${stock.limitUpReason}\n`
  }

  // 连板信息
  const lianbanStr = stock.lianbanStr
  if (lianbanStr) {
    title += `\n📈 连板: ${lianbanStr}\n`
  }

  return title
}


const getSignalDisplayText = (signal?: string | null, fallback = '--') => {
  if (!signal) return fallback
  if (signal === 'none') return '无'
  return localSignalLabels[signal] ?? signal
}

// 金死叉通用显示文案（MACD / MA10×MA20 共用 golden|death|none 词表）
const getCrossDisplayText = (value?: string | null) => {
  if (!value) return '--'
  return localCrossLabels[value] ?? value
}

const getAttentionStageDisplayText = (value?: string | null) => {
  if (!value) return '未知'
  return localAttentionStageLabels[value] ?? value
}

const formatTooltipNumber = (value?: number | null, digits = 1) => {
  if (!Number.isFinite(Number(value))) return '--'
  return Number(value).toFixed(digits)
}

const getResonanceMomentumText = (value: number) => {
  if (value > 0) return '强于市场'
  if (value < 0) return '弱于市场'
  return '与市场持平'
}

const getResonanceAccelerationText = (momentum: number, acceleration: number) => {
  if (momentum > 0) return acceleration >= 0 ? '上升加速' : '上升减速'
  if (momentum < 0) return acceleration >= 0 ? '下降减速' : '下降加速'
  return acceleration > 0 ? '转强' : acceleration < 0 ? '转弱' : '速度稳定'
}

const getRiskLevel = (score: number, mediumThreshold: number, highThreshold: number) => {
  if (score >= highThreshold) return '高'
  if (score >= mediumThreshold) return '中'
  return '低'
}

const getDirectionArrow = (direction?: string | null) =>
  direction === 'buy' ? '↑' : direction === 'sell' ? '↓' : '—'

const getDirectionClass = (direction?: string | null) =>
  direction === 'buy'
    ? 'observation-buy'
    : direction === 'sell'
      ? 'observation-sell'
      : 'observation-hold'

// 热度（技术字段 crossSection）：仅 percentile，方向/分值由其推算（2026-08-24）
const getCrossSectionPercentile = (stock: any): number | null => {
  const cs = getRankTrendAnalysis(stock)?.observation?.crossSection ?? {}
  const pct = typeof cs.percentile === 'number' ? Math.round(cs.percentile) : null
  return pct
}

const getCrossSectionValue = (stock: any): number | null => getCrossSectionPercentile(stock)

const getCrossSectionDirection = (stock: any): 'buy' | 'sell' | null => {
  const pct = getCrossSectionPercentile(stock)
  if (pct == null) return null
  return pct >= 50 ? 'buy' : 'sell'
}

const getCrossSectionClass = (stock: any): string => getDirectionClass(getCrossSectionDirection(stock))

const toFiniteObservationValue = (value: unknown): number | null => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const getRankTrendStrengthValue = (stock: any): number | null => {
  const value = toFiniteObservationValue(
    stock._rankTrendPct ?? getRankTrendAnalysis(stock)?.observation?.rankTrend?.score,
  )
  return value === null ? null : Math.round(value)
}

const getRankTrendDirection = (stock: any) =>
  stock._rankTrendDirection ?? getRankTrendAnalysis(stock)?.observation?.rankTrend?.direction ?? 'hold'

const getLifecycleOpportunityValue = (stock: any): number | null => {
  const value = toFiniteObservationValue(
    stock._lifecyclePct ?? getRankTrendAnalysis(stock)?.observation?.lifecycle?.score,
  )
  return value === null ? null : Math.round(value)
}

const getLifecycleStage = (stock: any) =>
  stock._lifecycleStage ?? getRankTrendAnalysis(stock)?.observation?.lifecycle?.stage ?? null

// 样本不足（2026-09-10 口径统一，spec §4.1）：数据质量声明优先于 stage 兜底标签，
// 避免周期列显示生命周期兜底"冷却"而展示状态判"样本不足"的同股两判。
// 前提（code review F3）：判据取 rankTrend.meta.sampleQuality（与后端同一字段），而 stage
// 允许 stock._lifecycleStage 投影回退；当只有投影存在、rankTrend 缺失时，周期列显示 stage
// 中文而非"样本不足"。这是数据可用性差异，不是两者矛盾的证据。
const isLifecycleSampleInsufficient = (stock: any): boolean =>
  getRankTrendAnalysis(stock)?.meta?.sampleQuality?.status === 'insufficient'

const getLifecycleStageLabel = (stock: any) =>
  isLifecycleSampleInsufficient(stock) ? '样本不足' : getAttentionStageDisplayText(getLifecycleStage(stock))

// 生命周期方向（与 uiStore 排序方向组语义一致）：点火/扩散=上升(buy)，拥挤/反转/降温=下降(sell)
const getLifecycleDirection = (stock: any) => {
  // 样本不足按中性处理，不进买入/卖出方向组（spec §4.1）
  if (isLifecycleSampleInsufficient(stock)) return 'hold'
  const stage = getLifecycleStage(stock)
  if (stage === 'ignition' || stage === 'expansion') return 'buy'
  if (stage === 'crowded' || stage === 'reversal' || stage === 'cooling') return 'sell'
  return 'hold'
}

const getLifecycleClass = (stock: any) => {
  const stage = getLifecycleStage(stock)
  return stage ? `lifecycle-${stage}` : 'observation-hold'
}

// 生命周期一票否决（环境门）：读 observation.lifecycle.veto 布尔
const getLifecycleVeto = (stock: any): boolean =>
  !!(getRankTrendAnalysis(stock)?.observation?.lifecycle?.veto ?? stock?._lifecycleVeto ?? false)

// 环境门环境色（2026-08-16 优化：lifecycle 无方向区分度，不用方向色；逐 stage 色与
// OBSERVATION 面板一致：点火黄/扩散红/拥挤橙/反转绿/冷却灰；否决（veto）是动作语义，
// 由红色"否决"角标单独表达，不覆盖 stage 颜色——避免"反转阶段+否决"混淆）
const lifecycleEnvClass = (stock: any): string => {
  const stage = getLifecycleStage(stock)
  if (stage === 'ignition') return 'lifecycle-env-ignition'
  if (stage === 'expansion') return 'lifecycle-env-expansion'
  if (stage === 'crowded') return 'lifecycle-env-crowded'
  if (stage === 'reversal') return 'lifecycle-env-reversal'
  if (stage === 'cooling') return 'lifecycle-env-cooling'
  return 'lifecycle-env-neutral'
}

const openObservationPanel = (stock: any, track: ObservationTrack) => {
  observationPanelStock.value = stock
  observationPanelTrack.value = track
  observationPanelVisible.value = true
}

const getDecisionStateText = (value?: string | null) => {
  if (value === 'auto_add') return '自动入池'
  if (value === 'watch_candidate') return '观察候选'
  if (value === 'blocked_candidate') return '被拒 / 阻断'
  if (value === 'not_candidate') return '未入池'
  return value || '未触发'
}

const getGateCheckStatusText = (status?: string | null) => {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '观察'
  if (status === 'fail') return '阻断'
  return '关闭'
}

const countTradingPoolBuyVotes = (stock: any) => {
  // 2026-09-13 五因子化：技术信号 4 票 + MA 金叉 = 5 票（与 py compose_decision 分量对齐）
  return [
    getDirectionSignal(stock) === 'buy',
    getAccelerationSignal(stock) === 'buy',
    getZeroCrossSignal(stock) === 'buy',
    getMacdCross(stock) === 'golden',
    getMaCross(stock) === 'golden',
  ].filter(Boolean).length
}

const getCandidateJumpThreshold = (stock: any) => {
  const projection = getCandidatePoolProjection(stock)
  return projection?.entryDecision?.configSnapshot?.minJumpConfidence ?? null
}

const getCandidatePoolReasonPreview = (stock: any) => {
  const projection = getCandidatePoolProjection(stock)
  const decision = projection?.entryDecision
  if (!decision) return '未触发'
  const jumpCheck = decision.checks?.find((check: any) => check.key === 'jump_confidence')
  if (jumpCheck?.status === 'fail') return 'Jump阈值阻断'
  if (decision.accepted) return '严格通过'
  return decision.label || getDecisionStateText(decision.decisionState)
}

const getTradingPoolActionPreview = (stock: any) => {
  const projection = getCandidatePoolProjection(stock)
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        ...stock,
        candidateEntryDecision: projection?.entryDecision,
        rankTrend: getRankTrendAnalysis(stock),
      },
    ],
  })
  const row = result.rows[0] || null
  const buyVotes = row?.signalSnapshot.buyVotes ?? countTradingPoolBuyVotes(stock)
  const actionLabel = row ? tradingPoolDecisionPreviewLabel(row.status, row.decision) : '未触发'
  const breakdown = row?.scoringBreakdown ?? null
  return {
    buyVotes,
    actionLabel,
    breakdown,
  }
}

const tradingPoolDecisionPreviewLabel = (status: string, decision: string) => {
  if (decision === 'enter') return status
  if (decision === 'downgrade') return '降级观察'
  if (decision === 'exit') return '自动出池'
  if (decision === 'stale') return '信号过期'
  return '继续观察'
}

// 置信度悬浮提示
const getConfidenceTitle = (stock: any) => {
  let title = ''
  const rankTrend = getRankTrendAnalysis(stock)

  const finalSignal = getFinalSignal(stock)
  const hasFinalSignal = Boolean(finalSignal && finalSignal !== 'none')
  if (!rankTrend && !hasFinalSignal) return '暂无信号'

  const directionText = getSignalDisplayText(getDirectionSignal(stock), '无')
  const accelerationText = getSignalDisplayText(getAccelerationSignal(stock), '无')
  const crossText = getSignalDisplayText(getZeroCrossSignal(stock), '无')
  const jumpConfidence = getJumpConfidence(stock)
  const candidateJumpThreshold = getCandidateJumpThreshold(stock)
  const candidateJumpPassed =
    candidateJumpThreshold == null ? null : jumpConfidence >= Number(candidateJumpThreshold)
  title = `📌 ${stock.name || '-'} (${stock.code || '-'})\n\n`
  title += '【观察结论】\n'
  const resonance = rankTrend?.resonance
  const resonanceScore = getResonanceCellValue(stock)
  const resonanceDirection = getResonanceDirection(stock)
  const rankTrendScore = getRankTrendStrengthValue(stock)
  const lifecycleScore = getLifecycleOpportunityValue(stock)
  title += resonanceDirection
    ? `共振方向: ${getSignalDisplayText(resonanceDirection, '无')}\n`
    : '共振方向: 暂无信号\n'
  title += resonanceScore == null
    ? '共振强度: --\n'
    : `共振强度: ${resonanceScore}%（${resonance?.label || '未评级'}）\n`
  title += rankTrendScore == null
    ? '排名趋势: --\n'
    : `排名趋势: ${getDirectionArrow(getRankTrendDirection(stock))}${rankTrendScore}%\n`
  title += lifecycleScore == null
    ? '生命周期: --\n'
    : `生命周期: ${getLifecycleStageLabel(stock)} ${lifecycleScore}%\n`
  const jumpDir = getJumpDirection(stock)
  const jumpDirLabel = jumpDir === 'buy' ? '买入' : jumpDir === 'sell' ? '卖出' : jumpDir === 'hold' ? '观望' : '—'
  title += candidateJumpPassed === false ? '候选池: 未通过\n' : `候选池: ${getCandidatePoolReasonPreview(stock)}\n`
  if (candidateJumpPassed === false) {
    title += `原因: Jump ${formatTooltipNumber(jumpConfidence, 1)} < 准入阈值 ${candidateJumpThreshold}\n`
  }

  title += '\n【共振路径】\n'
  if (resonance) {
    title += '数据来源: 八平台均榜横截面\n'
    title +=
      resonance.historyState === 'new_entry'
        ? '路径状态: 新入榜，待持续确认\n'
        : '路径状态: 已建立\n'
    if (resonance.status === 'insufficient') {
      title += `样本状态: ${resonance.reasons.join('、')}\n`
    } else {
      const relativeMomentum = resonance.relativeMomentum * 100
      const acceleration = resonance.acceleration * 100
      title += `相对市场: ${getResonanceMomentumText(relativeMomentum)} (${formatTooltipNumber(relativeMomentum, 0)})\n`
      title += `速度变化: ${getResonanceAccelerationText(relativeMomentum, acceleration)} (${formatTooltipNumber(acceleration, 0)})\n`
      title += `路径持续性: ${formatTooltipNumber(resonance.persistence * 100, 0)}%\n`
      title += `Jump事件: ${jumpDirLabel} ${formatTooltipNumber(jumpConfidence, 1)}% · 新鲜度 ${formatTooltipNumber(resonance.jumpFreshness * 100, 0)}%\n`
      title += `反转惩罚: ${formatTooltipNumber(resonance.reversalPenalty * 100, 0)}%\n`
      title += `市场中位数（同帧共享）: ${formatTooltipNumber(resonance.marketMedianShortChange, 1)}\n`
    }
  }

  if (rankTrend) {
    title += '\n【技术结构】\n'
    // 排名变化
    const rankChange = getRankChange(stock)
    if (rankChange !== 0) {
      const change = Math.abs(rankChange)
      title += `排名变化: ${rankChange > 0 ? '↑' : '↓'}${change}%\n`
    }

    // MACD信号
    const macdCross = getMacdCross(stock)
    title += `MACD: ${getCrossDisplayText(macdCross)}${macdCross === 'golden' ? ' ✅' : ''}\n`

    // MACD值
    const macdDif = getMacdDif(stock)
    if (macdDif !== undefined) {
      title += `MACD值: DIF=${macdDif.toFixed(2)}  DEA=${getMacdDea(stock)?.toFixed(2)}  柱=${getMacdHistogram(stock)?.toFixed(2)}\n`
    }

    // 3个排名趋势信号
    title += `方向一致性: ${directionText} (${formatTooltipNumber(getDirectionConfidence(stock), 2)}%)\n`
    title += `多周期加速度: ${accelerationText} (${formatTooltipNumber(getAccelerationConfidence(stock), 2)}%)\n`
    title += `零线交叉: ${crossText} (${formatTooltipNumber(getZeroCrossConfidence(stock), 2)}%)\n`

    title += '\n【阶段与风险】\n'
    const attentionStage = getAttentionStage(stock)
    if (attentionStage) {
      title += `注意力阶段: ${getAttentionStageDisplayText(attentionStage)}\n`
    }
    const overheatScore = Math.round(getOverheatRiskScore(stock) || 0)
    const divergenceScore = Math.round(getDivergenceScore(stock) || 0)
    title += `过热风险: ${getRiskLevel(overheatScore, 45, 70)} (${overheatScore} / 100)\n`
    title += `资金背离风险: ${getRiskLevel(divergenceScore, 40, 65)} (${divergenceScore} / 100)\n`
  }

  return title
}

// 四列按字段拆分 tooltip：共振强度 / 排名趋势 / 生命周期 / 题材动量
const getFieldTooltip = (field: string, stock: any): string => {
  const rankTrend = getRankTrendAnalysis(stock)
  const finalSignal = getFinalSignal(stock)
  const hasFinalSignal = Boolean(finalSignal && finalSignal !== 'none')
  // 量价配合不依赖 rankTrend 分析（只用 change/volumeRatio/zlje/中位数），跳过兜底拦截
  if (!rankTrend && !hasFinalSignal && field !== 'volumePriceQuadrant') return '暂无信号'

  const header = `📌 ${stock.name || '-'} (${stock.code || '-'})\n`

  // —— 共振强度 ——
  if (field === 'resonanceIntensity') {
    const resonance = rankTrend?.resonance
    const resonanceScore = getResonanceCellValue(stock)
    const resonanceDirection = getResonanceDirection(stock)
    let title = header
    title += '\n【共振】\n'
    title += resonanceDirection
      ? `共振方向: ${getSignalDisplayText(resonanceDirection, '无')}\n`
      : '共振方向: 暂无信号\n'
    title += resonanceScore == null
      ? '共振强度: --\n'
      : `共振强度: ${resonanceScore}%（${resonance?.label || '未评级'}）\n`
    if (resonance) {
      title += resonance.historyState === 'new_entry'
        ? '路径状态: 新入榜，待持续确认\n'
        : '路径状态: 已建立\n'
      if (resonance.status === 'insufficient') {
        title += `样本状态: ${resonance.reasons.join('、')}\n`
      } else {
        const relativeMomentum = resonance.relativeMomentum * 100
        const acceleration = resonance.acceleration * 100
        const jumpConfidence = getJumpConfidence(stock)
        const jumpDir = getJumpDirection(stock)
        const jumpDirLabel = jumpDir === 'buy' ? '买入' : jumpDir === 'sell' ? '卖出' : jumpDir === 'hold' ? '观望' : '—'
        title += `相对市场: ${getResonanceMomentumText(relativeMomentum)} (${formatTooltipNumber(relativeMomentum, 0)})\n`
        title += `速度变化: ${getResonanceAccelerationText(relativeMomentum, acceleration)} (${formatTooltipNumber(acceleration, 0)})\n`
        title += `路径持续性: ${formatTooltipNumber(resonance.persistence * 100, 0)}%\n`
        title += `Jump事件: ${jumpDirLabel} ${formatTooltipNumber(jumpConfidence, 1)}% · 新鲜度 ${formatTooltipNumber(resonance.jumpFreshness * 100, 0)}%\n`
        title += `反转惩罚: ${formatTooltipNumber(resonance.reversalPenalty * 100, 0)}%\n`
        title += `市场中位数（同帧共享）: ${formatTooltipNumber(resonance.marketMedianShortChange, 1)}\n`
      }
    }
    return title
  }

  // —— 排名趋势 ——
  if (field === 'rankTrendStrength') {
    const rankTrendScore = getRankTrendStrengthValue(stock)
    let title = header
    title += '\n【排名趋势】\n'
    title += rankTrendScore == null
      ? '排名趋势: --\n'
      : `排名趋势: ${getDirectionArrow(getRankTrendDirection(stock))}${rankTrendScore}%\n`
    if (rankTrend) {
      const rankChange = getRankChange(stock)
      if (rankChange !== 0) {
        const change = Math.abs(rankChange)
        title += `排名变化: ${rankChange > 0 ? '↑' : '↓'}${change}%\n`
      }
      const directionText = getSignalDisplayText(getDirectionSignal(stock), '无')
      const accelerationText = getSignalDisplayText(getAccelerationSignal(stock), '无')
      const crossText = getSignalDisplayText(getZeroCrossSignal(stock), '无')
      title += `方向一致性: ${directionText} (${formatTooltipNumber(getDirectionConfidence(stock), 2)}%)\n`
      title += `多周期加速度: ${accelerationText} (${formatTooltipNumber(getAccelerationConfidence(stock), 2)}%)\n`
      title += `零线交叉: ${crossText} (${formatTooltipNumber(getZeroCrossConfidence(stock), 2)}%)\n`
      const macdCross = getMacdCross(stock)
      title += `MACD: ${getCrossDisplayText(macdCross)}${macdCross === 'golden' ? ' ✅' : ''}\n`
      const maCrossValue = getMaCross(stock)
      if (maCrossValue !== 'none') {
        title += `MA10×MA20: ${getCrossDisplayText(maCrossValue)}${maCrossValue === 'golden' ? ' ✅' : ''}\n`
      }
      const macdDif = getMacdDif(stock)
      if (macdDif !== undefined) {
        title += `MACD值: DIF=${macdDif.toFixed(2)}  DEA=${getMacdDea(stock)?.toFixed(2)}  柱=${getMacdHistogram(stock)?.toFixed(2)}\n`
      }
    }
    return title
  }

  // —— 生命周期 ——
  if (field === 'lifecycleOpportunity') {
    const lifecycleScore = getLifecycleOpportunityValue(stock)
    let title = header
    title += '\n【生命周期】\n'
    title += lifecycleScore == null
      ? '生命周期: --\n'
      : `生命周期: ${getLifecycleStageLabel(stock)} ${lifecycleScore}%\n`
    if (rankTrend) {
      const attentionStage = getAttentionStage(stock)
      if (attentionStage) {
        title += `注意力阶段: ${getAttentionStageDisplayText(attentionStage)}\n`
      }
      const overheatScore = Math.round(getOverheatRiskScore(stock) || 0)
      const divergenceScore = Math.round(getDivergenceScore(stock) || 0)
      title += `过热风险: ${getRiskLevel(overheatScore, 45, 70)} (${overheatScore} / 100)\n`
      title += `资金背离风险: ${getRiskLevel(divergenceScore, 40, 65)} (${divergenceScore} / 100)\n`
    }
    return title
  }

  // —— 量价配合 ——
  if (field === 'volumePriceQuadrant') {
    // 后端生产 observation.volumePrice，前端只消费（与三轨数据链路一致）；
    // 投影缺失时回退 rankTrend.observation.volumePrice（同 getVolumePrice）
    const vp = getVolumePrice(stock)
    const score = vp.score
    const direction = vp.direction
    const quadrant = vp.quadrant
    const reasons: string[] = vp.reasons
    const breakdown = vp.breakdown
    const volume = classifyVolumeRatio(stock.volumeRatio)
    const change = Number(stock.change)
    const changeText = Number.isFinite(change) ? (change > 0 ? '+' : '') + change.toFixed(2) + '%' : '--'
    let title = header
    title += '\n【量价配合】\n'
    title += `综合评估: ${score == null ? '--' : `${direction === 'up' ? '↑' : direction === 'down' ? '↓' : ''}${score}`
      }（${getVolumePriceQuadrantLabel(quadrant)}）\n`
    title += `涨跌: ${changeText}\n`
    title += `量能: ${volume === 'unknown' ? '无量比基准' : volumeStateLabel(volume)}\n`
    title += `资金: ${classifyFundSignal(stock.zlje, stock.zljzb) === 'support' ? '主力净流入' : classifyFundSignal(stock.zlje, stock.zljzb) === 'divergent' ? '主力净流出' : classifyFundSignal(stock.zlje, stock.zljzb) === 'suspect' ? '主力净占比异常（疑似对倒）' : '无资金数据'}\n`
    if (score != null && breakdown) {
      const b = breakdown
      const sign = (v: number) => (v >= 0 ? '+' : '') + Number(v).toFixed(1)
      title += `评分(总${score}): 基准50\n`
      title += `  方向 ${sign(b.direction)}\n`
      title += `  量价 ${sign(b.volume)}\n`
      title += `  资金 ${sign(b.fund)}\n`
    }
    if (reasons.length) {
      title += `依据: ${reasons.join('、')}\n`
    }
    return title
  }

  // 兜底：完整置信度
  return getConfidenceTitle(stock)
}

const showConfidenceTooltip = (event: MouseEvent, stock: any, field = '') => {
  hideRowTooltip()
  confidenceTooltip.value = {
    visible: true,
    x: event.clientX + 16,
    y: event.clientY + 16,
    content: field ? getFieldTooltip(field, stock) : getConfidenceTitle(stock),
  }
}

// 各维档位命中规则原文（tierReasons），用于悬停展示；缺字段回退空数组（不伪造）
const getTierReasonsOf = (stock: any, field: string): string[] => {
  const rankTrend = getRankTrendAnalysis(stock)
  const observation = rankTrend?.observation || {}
  if (field === 'resonanceIntensity') {
    return Array.isArray(rankTrend?.resonance?.tierReasons) ? rankTrend.resonance.tierReasons : []
  }
  if (field === 'rankTrendStrength') {
    return Array.isArray(observation.rankTrend?.tierReasons) ? observation.rankTrend.tierReasons : []
  }
  if (field === 'volumePriceQuadrant') {
    return Array.isArray(observation.volumePrice?.tierReasons) ? observation.volumePrice.tierReasons : []
  }
  if (field === 'lifecycleOpportunity') {
    return Array.isArray(observation.lifecycle?.tierReasons) ? observation.lifecycle.tierReasons : []
  }
  return []
}

// 档位悬停：四列（共振/趋势/量价/周期）tooltip 显示"档位字母，原因"（如"B，方向确认但路径持续不足"），
// 单元格不再渲染徽章以免与【synergy】最终信号混淆；synergy 列保留徽章与完整说明
const showTierTooltip = (event: MouseEvent, stock: any, field: string) => {
  hideRowTooltip()
  const lines: string[] = []
  const stockName = (stock as any)?.name ?? '--'
  const stockCode = (stock as any)?.code ?? '--'
  const rankTrend = getRankTrendAnalysis(stock)
  const observation = (rankTrend && rankTrend.observation) || {}
  const dirText = (dir: unknown): string =>
    dir === 'buy' || dir === 'up' ? '向上' : dir === 'sell' || dir === 'down' ? '向下' : '中性'
  const tierCn: Record<string, string> = {
    S: '强买', A: '买入', B: '弱买', C: '中性', D: '回避', E: '否决',
  }
  // 周期档位中文（环境门语义，2026-08-26 用户模板：阶段/周期/说明）
  const lifecycleTierCn = (tier: string | null | undefined): string => {
    const map: Record<string, string> = { A: '放行', B: '谨慎', C: '中性', D: '回避', E: '否决' }
    return tier && tier !== 'unknown' ? map[tier] ?? tier : '--'
  }
  // 五维度总档操作建议
  const synergyActionAdvice = (tier: string | null | undefined): string => {
    const advice: Record<string, string> = {
      S: '强买——高确定性方向一致，可重点介入',
      A: '买入——方向票达标，可介入',
      B: '弱买——方向分歧或受周期降档，轻仓观察',
      C: '中性——无明确方向，观望',
      D: '回避——反向或风险信号，回避',
      E: '否决——周期一票否决，坚决回避',
    }
    return tier && tier !== 'unknown' ? advice[tier] ?? tier : '数据不足，未合并'
  }
  // 周期环境门操作建议（档位优先，回退 stage 语义）
  const lifecycleActionAdvice = (tier: string | null | undefined, stage: unknown): string => {
    if (tier === 'E') return '否决——坚决回避，不做介入'
    if (tier === 'D') return '回避——建议回避或减仓，不追高'
    if (tier === 'B') return '谨慎——低可见度，轻仓观察为主'
    if (tier === 'A') return '放行——环境允许，可正常跟踪'
    if (stage === 'ignition') return '点火——上升早期，可跟踪观察'
    if (stage === 'expansion') return '扩散——主升路径，适合介入/持有'
    if (stage === 'crowded') return '拥挤——高位拥挤，建议回避或减仓'
    if (stage === 'reversal') return '反转——见顶反转，建议回避'
    if (stage === 'cooling') return '冷却——降温阶段，建议回避观望'
    return '档位/阶段缺失，仅观察'
  }
  const pushTier = (tier: string | null | undefined) => {
    lines.push(`档位：${tier && tier !== 'unknown' ? tier : '--'}`)
  }
  if (field === 'synergyTier') {
    // 五维度（2026-08-26 用户模板）：名称（代码）/ 阶段 / 周期 / 说明（参数阈值 + 操作建议）
    const tier = getSynergyTier(stock)
    const stageLabel = getLifecycleStageLabel(stock)
    const lcTier = getLifecycleTier(stock)
    lines.push(`${stockName}（${stockCode}）：`)
    lines.push(`阶段：${stageLabel && stageLabel !== '未知' ? stageLabel : '--'}`)
    lines.push(`周期：${lifecycleTierCn(lcTier)}`)
    lines.push('说明：')
    lines.push(
      `  总档 ${tier && tier !== 'unknown' ? `${tier}（${tierCn[tier] ?? tier}）` : '--'} · 五维档位 ${getSynergyTierDetail(stock).join(' / ')}`,
    )
    lines.push(...getSynergyVoteBreakdown(stock).map((line) => `  ${line}`))
    const synReasons = getSynergyTierReasons(stock)
    if (synReasons.length) lines.push(`  依据：${synReasons.join('；')}`)
    const csDetail = getCrossSectionDetail(stock)
    if (csDetail) lines.push(`  ${csDetail}`)
    lines.push('  周期不投方向票，但参与总档合成：E 一票否决、B/D 对 S/A 降一档、A 放行')
    lines.push(`  操作建议：${synergyActionAdvice(tier)}`)
  } else if (field === 'lifecycleOpportunity') {
    // 周期（2026-08-26 用户模板）：名称（代码）/ 阶段 / 周期 / 说明（环境门规则 + 操作建议）
    const stage = getLifecycleStage(stock)
    const stageLabel = getLifecycleStageLabel(stock)
    const lcTier = getLifecycleTier(stock)
    lines.push(`${stockName}（${stockCode}）：`)
    lines.push(`阶段：${stageLabel && stageLabel !== '未知' ? stageLabel : '--'}`)
    lines.push(`周期：${lifecycleTierCn(lcTier)}`)
    lines.push('说明：周期为环境门，不投方向票，但参与总档位合成')
    lines.push('  E 否决 → 总档强制否决')
    lines.push('  B 谨慎 / D 回避 → 总档 S/A 降一档')
    lines.push('  A 放行 → 不干预三维方向票')
    const lcReasons = Array.isArray(observation.lifecycle?.tierReasons)
      ? observation.lifecycle.tierReasons
      : []
    if (lcReasons.length) lines.push(`  依据：${lcReasons.join('；')}`)
    lines.push(`  操作建议：${lifecycleActionAdvice(lcTier, stage)}`)
  } else if (field === 'resonanceIntensity') {
    const res = (rankTrend && rankTrend.resonance) || {}
    const tier = getResonanceTier(stock)
    const score = getResonanceCellValue(stock)
    lines.push(`${stockName} ${stockCode}`)
    pushTier(tier)
    lines.push(`方向：${dirText(getResonanceDirection(stock))}`)
    lines.push(`分值：${score != null ? `${score}%` : '--'}`)
    const reasons: string[] = []
    if (Array.isArray(res.tierReasons)) reasons.push(...res.tierReasons)
    const jumpDir = res.jump && res.jump.direction
    if (jumpDir === 'up') {
      reasons.push(`Jump 向上事件驱动，排名跳跃式上升${res.jumpFreshness != null ? `（新鲜度 ${Math.round(res.jumpFreshness * 100)}%）` : ''}`)
    } else if (jumpDir === 'down') {
      reasons.push(`Jump 向下事件驱动，排名跳水${res.jumpFreshness != null ? `（新鲜度 ${Math.round(res.jumpFreshness * 100)}%）` : ''}`)
    }
    if (res.marketMedianShortChange != null) reasons.push(`市场热度中位变化 ${res.marketMedianShortChange.toFixed(2)}`)
    lines.push(`说明：${reasons.length ? reasons.join('；') : '（无结构化原因）'}`)
  } else if (field === 'rankTrendStrength') {
    // 趋势：方向+数值%；档位取趋势自身（getRankTrendTier），热度独立成列后不再混入 tooltip
    const tier = getRankTrendTier(stock)
    const rt = observation.rankTrend || {}
    const score = getRankTrendStrengthValue(stock)
    lines.push(`${stockName} ${stockCode}`)
    pushTier(tier)
    lines.push(`方向：${dirText(rt.direction)}`)
    lines.push(`分值：${score != null ? `${score}%` : '--'}`)
    const reasons: string[] = []
    if (Array.isArray(rt.tierReasons)) reasons.push(...rt.tierReasons)
    const dirSig = getSignalDisplayText(getDirectionSignal(stock), '无')
    const accSig = getSignalDisplayText(getAccelerationSignal(stock), '无')
    const crossSig = getSignalDisplayText(getZeroCrossSignal(stock), '无')
    if (dirSig !== '无') reasons.push(`方向一致性 ${dirSig}`)
    if (accSig !== '无') reasons.push(`加速度 ${accSig}`)
    if (crossSig !== '无') reasons.push(`零线交叉 ${crossSig}`)
    const macdCross = getMacdCross(stock)
    if (macdCross === 'golden') reasons.push('MACD 金叉')
    else if (macdCross === 'death') reasons.push('MACD 死叉')
    lines.push(`说明：${reasons.length ? reasons.join('；') : '（无结构化原因）'}`)
  } else if (field === 'crossSection') {
    const cs = (observation.crossSection as any) || {}
    const tier = getCrossSectionTier(stock)
    const pct = typeof cs.percentile === 'number' ? Math.round(cs.percentile) : null
    lines.push(`${stockName} ${stockCode}`)
    pushTier(tier)
    // 方向/分值按 percentiles 推算（2026-08-24 用户确认）
    lines.push(`方向：${pct == null ? '中性' : pct >= 50 ? '向上' : '向下'}`)
    lines.push(`分值：${pct != null ? `${pct}%` : '--'}`)
    const reasons: string[] = []
    if (pct != null) reasons.push(`相对强弱分位 ${pct}%`)
    const delta = typeof cs.percentileDelta === 'number' ? Math.round(cs.percentileDelta) : null
    const rel = typeof cs.relativeToMarket === 'number' ? Math.round(cs.relativeToMarket) : null
    if (delta != null) reasons.push(`分位变化 ${delta}`)
    if (rel != null) reasons.push(`相对市场 ${rel}`)
    if (Array.isArray(cs.tierReasons)) reasons.push(...cs.tierReasons)
    lines.push(`说明：${reasons.length ? reasons.join('；') : '（无结构化原因）'}`)
  } else if (field === 'volumePriceQuadrant') {
    const vp = observation.volumePrice || {}
    const tier = getVolumePriceTier(stock)
    const vpData = getVolumePrice(stock)
    const score = vpData.score
    lines.push(`${stockName} ${stockCode}`)
    pushTier(tier)
    lines.push(`方向：${dirText(vpData.direction)}`)
    lines.push(`分值：${score != null ? `${Math.round(score)}%` : '--'}`)
    const reasons: string[] = []
    if (vp.quadrant) {
      const qMap: Record<string, string> = {
        rise_volume: '放量上涨', rise_shrink: '缩量上涨', fall_volume: '放量下跌',
        fall_shrink: '缩量下跌', normal: '量价常态',
      }
      reasons.push(`象限：${qMap[vp.quadrant] ?? vp.quadrant}`)
    }
    if (Array.isArray(vp.tierReasons)) reasons.push(...vp.tierReasons)
    if (Array.isArray(vp.reasons)) reasons.push(...vp.reasons)
    const zljzb = (stock as any)?.zljzb
    if (zljzb != null) reasons.push(`资金净占比 ${Math.round(zljzb)}%`)
    lines.push(`说明：${reasons.length ? reasons.join('；') : '（无结构化原因）'}`)
  } else {
    const tier =
      field === 'lifecycleOpportunity' ? getLifecycleTier(stock) : null
    const parts: string[] = []
    if (tier && tier !== 'unknown') parts.push(tierBadgeLabel(tier) ?? '')
    parts.push(...getTierReasonsOf(stock, field))
    if (parts.length) lines.push(parts.join('：'))
  }
  if (!lines.length) {
    showConfidenceTooltip(event, stock, field)
    return
  }
  confidenceTooltip.value = {
    visible: true,
    x: event.clientX + 16,
    y: event.clientY + 16,
    content: lines.join('\n'),
  }
}

const moveConfidenceTooltip = (event: MouseEvent) => {
  if (!confidenceTooltip.value.visible) return
  confidenceTooltip.value.x = event.clientX + 16
  confidenceTooltip.value.y = event.clientY + 16
}

const hideConfidenceTooltip = () => {
  confidenceTooltip.value.visible = false
}

const showThemeTooltip = (event: MouseEvent, stock: Stock) => {
  hideConfidenceTooltip()
  const content = getMergedThemeTooltipTitle(stock)
  if (!content) return
  rowTooltip.value = {
    visible: true,
    x: event.clientX + 16,
    y: event.clientY + 16,
    content,
  }
}

const moveRowTooltip = (event: MouseEvent) => {
  if (!rowTooltip.value.visible) return
  rowTooltip.value.x = event.clientX + 16
  rowTooltip.value.y = event.clientY + 16
}

const hideRowTooltip = () => {
  rowTooltip.value.visible = false
}

const getRankTrendAnalysis = (stock: any) => stock?.rankTrend

const getStockValue = (stock: Stock, key: string) => (stock as unknown as Record<string, unknown>)[key]

const getRankChange = (stock: any) => {
  if (stock._rankChange !== undefined) return stock._rankChange
  return Math.round(
    getRankTrendAnalysis(stock)?.meta?.change ??
    getRankTrendAnalysis(stock)?.change ??
    stock?.rankChange ??
    0,
  )
}

const candidatePoolStateLabels: Record<string, string> = {
  idle: '未触发',
  triggered_wait_entry: '待入场',
  active_holding: '已入场',
  exit_signaled: '策略退出观察',
  closed: '策略已关闭',
}

const getCandidatePoolProjection = (stock: any) => stock?.candidatePoolProjection || null

const hasCandidatePoolEntry = (stock: any) =>
  !!stock?.candidatePoolEntryId || !!getCandidatePoolProjection(stock)?.executionOverlay?.entryId

const formatCandidatePoolStateLabel = (stock: any) => {
  const state = getCandidatePoolProjection(stock)?.strategyState || stock?.candidatePoolStatus || 'idle'
  if (state === 'idle' && hasCandidatePoolEntry(stock)) return '观察中'
  return candidatePoolStateLabels[state] || stock?.candidatePoolLabel || '未触发'
}

const getCandidatePoolTooltipTitle = (stock: any) => {
  const projection = getCandidatePoolProjection(stock)
  const decision = projection?.entryDecision
  const failedChecks = (decision?.checks || []).filter((check: any) => check.status === 'fail')
  const hardFailedChecks = failedChecks.filter((check: any) => check.hardBlock)
  const warnChecks = (decision?.checks || []).filter((check: any) => check.status === 'warn')
  const lines = [`📌 ${stock.name || '-'} (${stock.code || '-'})`]

  lines.push(`🧭 策略状态: ${formatCandidatePoolStateLabel(stock)}`)
  lines.push(`📍 所处分层: ${projection?.candidateTier || '未识别'}`)

  if (projection?.lifecycleAction) {
    lines.push(`🔁 生命周期: ${projection.lifecycleAction}`)
  }
  if (projection?.holdingBars !== undefined) {
    lines.push(`⏳ 持有Bars: ${projection.holdingBars}`)
  }
  if (decision?.decisionState) {
    lines.push(`🚦 当前入池诊断: ${decision.label || getDecisionStateText(decision.decisionState)}`)
  }
  if (decision?.summary) {
    lines.push(`📝 摘要: ${decision.summary}`)
  }

  lines.push('─'.repeat(30))
  if (hardFailedChecks.length) {
    lines.push(`⛔ 被拒原因: ${hardFailedChecks.map((check: any) => check.message || check.label).join('；')}`)
  } else if (failedChecks.length) {
    lines.push(`⚠️ 观察原因: ${failedChecks.map((check: any) => check.message || check.label).join('；')}`)
  } else if (decision?.accepted) {
    lines.push('✅ 入池原因: 核心硬规则已通过，可自动入池')
  } else {
    lines.push(`👀 入池原因: ${warnChecks[0]?.message || '暂未触发硬阻断，继续观察信号强度'}`)
  }

  const importantChecks = [
    ...hardFailedChecks,
    ...warnChecks,
    ...(decision?.checks || []).filter((check: any) =>
      ['candidate_tier', 'jump_confidence', 'momentum', 'acceleration', 'change_gate'].includes(check.key),
    ),
  ].filter((check: any, index: number, list: any[]) =>
    check?.key && list.findIndex((item: any) => item.key === check.key) === index,
  )
  if (importantChecks.length) {
    lines.push('\n📋 规则矩阵关键项:')
    importantChecks.slice(0, 5).forEach((check: any) => {
      lines.push(
        `   ${check.label}: ${getGateCheckStatusText(check.status)} · 当前 ${formatGateActualForTooltip(check.actual)} / 要求 ${check.expected}`,
      )
    })
  }

  if (projection?.exitReason) {
    lines.push(`\n🚪 退出原因: ${projection.exitReason}`)
  }
  if (projection?.strategyEntryAt) {
    lines.push(`⏱️ 策略入场: ${projection.strategyEntryAt}`)
  }
  if (projection?.triggerAt) {
    lines.push(`⏱️ 首次触发: ${projection.triggerAt}`)
  }
  if (stock?.candidatePoolSource) {
    lines.push(`📎 来源: ${stock.candidatePoolSource}`)
  }
  return lines.join('\n')
}

const formatGateActualForTooltip = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}


const getFinalSignal = (stock: any) =>
  getRankTrendAnalysis(stock)?.decision?.final?.signal ??
  getRankTrendAnalysis(stock)?.finalSignal ??
  stock?.finalSignal ??
  'none'

const getFinalConfidence = (stock: any) =>
  getRankTrendAnalysis(stock)?.decision?.final?.confidence ??
  getRankTrendAnalysis(stock)?.finalConfidence ??
  stock?.finalConfidence ??
  0

const getJumpConfidence = (stock: any) => {
  if (stock._jumpConfidence !== undefined) return stock._jumpConfidence
  return (
    getRankTrendAnalysis(stock)?.jump?.confidence ??
    stock?.rankTrend?.jump?.confidence ??
    stock?.jumpConfidence ??
    0
  )
}

const getJumpDirection = (stock: any) => {
  if (stock._jumpDirection !== undefined) return stock._jumpDirection
  return (
    getRankTrendAnalysis(stock)?.jump?.direction ??
    stock?.rankTrend?.jump?.direction ??
    stock?.jumpDirection ??
    null
  )
}

function getResonanceRawScore(stock: any): number | null {
  if (stock._resonanceRawScore !== undefined) return stock._resonanceRawScore
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? resonance.score : null
}

const getResonanceDirection = (stock: any) => {
  const resonance = getRankTrendAnalysis(stock)?.resonance
  return resonance?.status === 'ok' ? resonance.direction : null
}

function getResonanceCellValue(stock: any): number | null {
  const value =
    stock._resonancePct !== undefined
      ? toFiniteObservationValue(stock._resonancePct)
      : toFiniteObservationValue(getResonanceRawScore(stock))
  return value === null ? null : Math.round(value)
}

function getResonanceCellClass(stock: any): string {
  return getDirectionClass(getResonanceDirection(stock))
}

const getMacdCross = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.macd?.cross ?? stock?.macdCross ?? 'none'

// MA10×MA20 排名百分位金死叉（2026-09-13 五因子化 additive 字段）：
// 只认 py golden 的 technical.maCross，无 stock.* 历史回退——缺字段 → 'none' → 无徽章
const getMaCross = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.maCross?.cross ?? 'none'

// MACD 金/死叉事件徽章（2026-09-21 用户裁决，趋势列 ▲▼ 取数源）：
// 只认 py golden 的 technical.macd.cross（后端仅交叉帧产出 golden/death 的事件语义），
// 无 stock.* 历史回退——缺字段 → 'none' → 无徽章
const getMacdCrossBadge = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.macd?.cross ?? 'none'

const getMacdDif = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.macd?.dif ?? stock?.macd

const getMacdDea = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.macd?.dea ?? stock?.macdSignal

const getMacdHistogram = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.macd?.histogram ?? stock?.macdHistogram

const getDirectionSignal = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.direction?.signal ?? stock?.directionSignal ?? 'none'

const getDirectionConfidence = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.direction?.confidence ?? stock?.directionConfidence ?? 0

const getAccelerationSignal = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.acceleration?.signal ?? stock?.accelerationSignal ?? 'none'

const getAccelerationConfidence = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.acceleration?.confidence ?? stock?.accelerationConfidence ?? 0

const getZeroCrossSignal = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.zeroCross?.signal ?? stock?.crossSignal ?? 'none'

const getZeroCrossConfidence = (stock: any) =>
  getRankTrendAnalysis(stock)?.technical?.signals?.zeroCross?.confidence ?? stock?.crossConfidence ?? 0

const getAttentionStage = (stock: any) =>
  getRankTrendAnalysis(stock)?.cycle?.stage

const getOverheatRiskScore = (stock: any) =>
  getRankTrendAnalysis(stock)?.risk?.overheat?.score ?? 0

const getDivergenceScore = (stock: any) =>
  getRankTrendAnalysis(stock)?.risk?.divergence?.score ?? 0

// 判断是否显示金叉死叉标记（非交易时间）
const shouldShowMacdSignal = (stock: any) => {
  const macdCross = getMacdCross(stock)
  return macdCross === 'golden' || macdCross === 'death'
}

// ========== 格式化函数（保持不变）==========
const formatMoney = (value: number): string => {
  if (!value && value !== 0) return '-'
  const absValue = Math.abs(value)
  if (absValue >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (absValue >= 1e4) return (value / 1e4).toFixed(2) + '万'
  if (absValue >= 1) return value.toFixed(2)
  return (value < 0 ? '-' : '') + absValue.toFixed(2)
}

const hasMoneyFlowSource = (stock: any) =>
  stock.moneyFlowEstimated !== undefined ||
  Boolean(stock.moneyFlowSource) ||
  Boolean(stock.capitalFlowSource)

const shouldDisplayMoneyFlow = (key: string, stock: any) => {
  if (!['zlje', 'zljzb'].includes(key)) return false
  const value = Number(stock[key])
  return Number.isFinite(value) && (value !== 0 || hasMoneyFlowSource(stock))
}

const formatMoneyFlowCell = (key: string, stock: any): string => {
  if (!shouldDisplayMoneyFlow(key, stock)) return '-'
  const value = Number(stock[key])
  if (key === 'zljzb') {
    return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
  }
  return formatMoney(value)
}

const getMoneyFlowTitle = (key: string, stock: any): string | undefined => {
  if (stock.moneyFlowSource === FUND_SOURCE.THS_MAIN_MONITOR) return '同花顺个股资金流'
  if (stock.moneyFlowSource === FUND_SOURCE.AKSHARE_THS_INDIVIDUAL) return '同花顺网页资金流（估算）'
  return undefined
}

const formatVolume = (volume: number): string => {
  if (!volume && volume !== 0) return '-'
  const absVolume = Math.abs(volume)
  if (absVolume >= 1e8) return (volume / 1e8).toFixed(2) + '亿手'
  if (absVolume >= 1e4) return (volume / 1e4).toFixed(2) + '万手'
  return volume.toString() + '手'
}

const formatCell = (key: string, stock: any) => {
  const value = key === 'rankChange' ? getRankChange(stock) : stock[key]
  if (value === undefined || value === null) return '-'

  if (key.includes('Rank') || key === 'compRank') {
    // 2026-08-25（P1 复盘）：avgRankNum 全平台缺失时采集器写 999（avgRank="999.0" 字符串），
    // 统一按哨兵显示 '-'（与平台 rank 999 / compRank 999 一致）
    return value === 999 || Number(value) >= 999 ? '-' : value
  }

  if (key === 'speed') {
    const speed = Number(value)
    if (!Number.isFinite(speed)) return '-'
    return `${speed > 0 ? '+' : ''}${speed.toFixed(2)}%`
  }

  if (['zlje', 'zljzb'].includes(key)) {
    return formatMoneyFlowCell(key, stock)
  }

  if (key.includes('Rate') || key === 'change' || key.includes('zb')) {
    return value ? (value > 0 ? '+' : '') + Number(value).toFixed(2) + '%' : '-'
  }

  if (key === 'price') {
    const price = Number(value)
    return Number.isFinite(price) ? price.toFixed(2) : '-'
  }

  // ✅ 量比格式化：保留两位小数
  if (key === 'volumeRatio') {
    return formatVolumeRatioCell(stock)
  }

  if (['turnover', 'cirMV', 'totalMV'].includes(key)) {
    return formatMoney(value)
  }

  if (key === 'volume') return formatVolume(value)
  if (key === 'pb') return value ? Number(value).toFixed(2) : '-'
  if (key === 'themes') return Array.isArray(value) ? value.join(', ') || '-' : value || '-'

  // 封单金额：亿元两位小数（与题材面板封单列同口径），缺失 '-' 不伪造 0
  if (key === 'fengdan') {
    const amount = Number(value)
    return Number.isFinite(amount) ? `${(amount / 1e8).toFixed(2)}亿` : '-'
  }

  return value ?? '-'
}

// ========== 样式类（保持不变==========
const getCellClass = (key: string, stock: any) => {
  const classes = ['cell']

  if (key === 'code') classes.push('code-cell')
  else if (key === 'name') classes.push('name-cell')
  else if (key === 'themes') classes.push('sector-cell')
  else classes.push('number-cell')

  if (key === 'change' || key === 'speed') {
    const value = Number(stock[key])
    if (value > 0) classes.push('color-up')
    else if (value < 0) classes.push('color-down')
  }

  if (key === 'volumeRatio') {
    classes.push('volume-ratio-cell')
  }

  if (key === 'zlje') {
    const value = stock[key]
    if (value > 0) classes.push('money-positive')
    else if (value < 0) classes.push('money-negative')
  }

  if (key === 'compRank' || key === 'avgRank') classes.push('color-highlight')

  if (key === 'rankChange') {
    const change = getRankChange(stock)
    if (change > 0) classes.push('rank-up')
    else if (change < 0) classes.push('rank-down')
  }

  return classes.join(' ')
}

const formatVolumeRatioCell = (stock: any) => {
  const ratio = Number(stock.volumeRatio)
  const status = stock.volumeRatioMeta?.status
  if (status === 'unavailable') return '-'
  if (!Number.isFinite(ratio) || ratio <= 0) return '-'
  return ratio.toFixed(2)
}

const getVolumeRatioRelativeText = (stock: any) => {
  const state = classifyVolumeRatio(stock.volumeRatio)
  if (state === 'unknown') return ''
  return volumeRatioStateLabel(state)
}

const getVolumeRatioClass = (stock: any) => {
  const state = classifyVolumeRatio(stock.volumeRatio)
  if (state === 'up') return 'vr-up'
  if (state === 'down') return 'vr-down'
  if (state === 'normal') return 'vr-normal'
  return ''
}

// ========== 量价配合（四象限列） ==========
// 列内文本参照三指标列「方向 + 数值」：↑/↓ 为涨跌方向，数值为量价综合评估值（0-100）；
// 完整四象限语义（放量上涨等）由颜色（quadrant-*）与 tooltip 承载。
// 读取口径与三轨一致：投影（_volumePrice*）优先，投影缺失时回退直接读
// rankTrend.observation.volumePrice（后端 Redis 缓存/前端缓存预热提供的 rankTrend 数据），
// 避免分析未完成时整列回退为 '--'。
const getVolumePrice = (stock: any) => {
  const vp = getRankTrendAnalysis(stock)?.observation?.volumePrice ?? {}
  return {
    score: stock?._volumePriceScore ?? vp.score ?? null,
    direction: stock?._volumePriceDirection ?? vp.direction ?? null,
    quadrant: stock?._volumePriceQuadrant ?? vp.quadrant ?? null,
    reasons: Array.isArray(stock?._volumePriceReasons)
      ? stock._volumePriceReasons
      : Array.isArray(vp.reasons)
        ? vp.reasons
        : [],
    breakdown: stock?._volumePriceBreakdown ?? vp.breakdown ?? null,
  }
}

const getQuadrantText = (stock: any) => {
  const score = getVolumePrice(stock).score
  if (score == null) return '--'
  const direction = getVolumePrice(stock).direction
  const arrow = direction === 'up' ? '↑' : direction === 'down' ? '↓' : ''
  return `${arrow}${Math.round(Number(score))}%`
}

const getQuadrantClass = (stock: any) => {
  const quadrant = getVolumePrice(stock).quadrant
  return quadrant ? `quadrant-${quadrant}` : ''
}

const getVolumeRatioTitle = (stock: any) => {
  const meta = stock.volumeRatioMeta
  const lines: string[] = []
  const relative = getVolumeRatioRelativeText(stock)
  if (relative) lines.push(`相对状态: ${relative}`)
  if (meta) {
    lines.push(
      `状态: ${meta.status}`,
      `来源: ${meta.source}`,
      Number.isFinite(Number(meta.currentVolume)) ? `当前成交量: ${meta.currentVolume}` : '',
      Number.isFinite(Number(meta.expectedVolume))
        ? `预期成交量: ${Number(meta.expectedVolume).toFixed(2)}`
        : '',
      Number.isFinite(Number(meta.rawRatio)) ? `原始量比: ${Number(meta.rawRatio).toFixed(2)}` : '',
      meta.reason ? `原因: ${meta.reason}` : '',
    )
  }
  return lines.filter(Boolean).join('\n')
}

const getGroupLabel = (group: string) => {
  const labels: Record<string, string> = {
    basic: '📋 基本信息',
    platform: '📊 热榜排名',
    comprehensive: '🎯 综合',
    money: '💰 资金流向',
    quote: '🔴 行情数据',
    limitup: '🚀 涨停相关',
  }
  return labels[group] || group
}

// ========== 八平台排名格式化 ==========
const formatPlatformRank = (rank: number): string => {
  if (!rank || rank >= 999) return '-'
  if (rank === 1) return '🥇1'
  if (rank === 2) return '🥈2'
  if (rank === 3) return '🥉3'
  return rank.toString()
}
const getPlatformRankClass = (rank: number): string => {
  if (!rank || rank >= 999) return ''
  if (rank === 1) return 'platform-1st'
  if (rank === 2) return 'platform-2nd'
  if (rank === 3) return 'platform-3rd'
  return ''
}

// 判断是否是平台排名列
const isPlatformRankKey = (key: string): boolean => {
  return ['emRank', 'thsRank', 'kplRank', 'tdxRank', 'xqRank', 'clsRank', 'tgbRank', 'dzhRank'].includes(key)
}

// 信号面板状态
const rankTrendPanelVisible = ref(false)
const rankTrendPanelTriggerRect = ref<DOMRect>()
const rankTrendPanelStockCode = ref('')

const openRankTrendForStock = () => {
  if (!contextMenu.value.stock) {
    console.warn('[DataTable] 没有选中的股票，无法打开')
    hideContextMenu()
    return
  }

  const stock = contextMenu.value.stock

  rankTrendPanelStockCode.value = stock.code
  rankTrendPanelVisible.value = true

  hideContextMenu()
}

const getGroupColspan = (group: string) => {
  return visibleColumns.value.filter(col => col.group === group).length
}

// ========== 右键菜单 ==========
const onRowClick = (event: MouseEvent, code: string) => {
  const target = event.target as HTMLElement
  if (target.closest('.sector-tag') || target.closest('.sector-tags')) {
    return
  }
  uiStore.selectStock(code)
  emit('select', code)
  const stock = sortedStocks.value.find((item) => item.code === code)
  sendHotlistSelection(code, stock?.name)
}

const showContextMenu = (e: MouseEvent, stock: Stock) => {
  openCandidateId.value = ''
  contextMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    stock: { ...stock },
  }
  void candidateJournalService.getOpenCandidateForStock(stock.code).then((entry) => {
    if (contextMenu.value.visible && contextMenu.value.stock?.code === stock.code) {
      openCandidateId.value = entry?.id || ''
    }
  }).catch(() => {
    if (contextMenu.value.visible && contextMenu.value.stock?.code === stock.code) {
      openCandidateId.value = ''
    }
  })
}

const hideContextMenu = () => {
  contextMenu.value.visible = false
  showBoardSubMenu.value = false
  openCandidateId.value = ''
}

const loadBoardList = () => {
  boardList.value = favoriteStore.boardList
}

const showBoardMenu = () => {
  loadBoardList()
  showBoardSubMenu.value = true
}

const addToSpecificBoard = (boardId: string) => {
  if (contextMenu.value.stock) {
    favoriteStore.addStockToBoard(contextMenu.value.stock.code, boardId)
  }
  hideContextMenu()
}

const createNewBoard = () => {
  if (contextMenu.value.stock) {
    const boardName = prompt('请输入新板块名称：')
    if (boardName && boardName.trim()) {
      const board = favoriteStore.addBoard(boardName.trim())
      if (board) {
        favoriteStore.addStockToBoard(contextMenu.value.stock.code, board.id)
      }
    }
  }
  hideContextMenu()
}

const addToFavorite = () => {
  if (contextMenu.value.stock) {
    favoriteStore.toggleFavorite(contextMenu.value.stock.code, '默认')
  }
  hideContextMenu()
}

const addToCandidatePool = async () => {
  if (!contextMenu.value.stock) {
    hideContextMenu()
    return
  }

  try {
    if (openCandidateId.value) {
      EventManager.emit('candidate-pool:open', {
        stockCode: contextMenu.value.stock.code,
        candidateId: openCandidateId.value,
      })
      return
    }

    const result = await candidateJournalService.addCandidateFromStock(contextMenu.value.stock, {
      addToFavorites: true,
      source: 'datatable-context-menu',
    })
    EventManager.emit('candidate-pool:open', {
      stockCode: contextMenu.value.stock.code,
      candidateId: result.entry?.id,
    })
  } catch (error) {
    EventManager.emit(AppEvents.UI.TOAST, {
      message: `加入候选池失败：${error instanceof Error ? error.message : '未知错误'}`,
      duration: 2000,
      type: 'error',
    })
  } finally {
    hideContextMenu()
  }
}

const copyCode = () => {
  if (contextMenu.value.stock) {
    navigator.clipboard?.writeText(contextMenu.value.stock.code).then(() => {
      // ✅ 保留事件发射
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `📋 已复制 ${contextMenu.value.stock?.code}`,
        duration: 1500,
        type: 'success',
      })
    })
  }
  hideContextMenu()
}

const openStockDetail = (stock: Stock, triggerRect: DOMRect, source: string) => {
  uiStore.selectStock(stock.code)
  EventManager.emit('stock:show-detail', {
    code: stock.code,
    name: stock.name,
    triggerRect,
    source,
  })
  EventManager.emit(AppEvents.UI.TOAST, {
    message: `🔍 查看 ${stock.name} 详情`,
    duration: 1500,
    type: 'info',
  })
  hideConfidenceTooltip()
  hideRowTooltip()
}

const viewDetails = () => {
  if (contextMenu.value.stock) {
    openStockDetail(
      contextMenu.value.stock,
      new DOMRect(contextMenu.value.x, contextMenu.value.y, 1, 1),
      'datatable-context-menu',
    )
  }
  hideContextMenu()
}

const openStockDetailFromRow = (event: MouseEvent, stock: Stock) => {
  const target = event.currentTarget as HTMLElement | null
  const triggerRect = target?.getBoundingClientRect() ?? new DOMRect(event.clientX, event.clientY, 1, 1)
  openStockDetail(stock, triggerRect, 'datatable-row-double-click')
  hideContextMenu()
}

// ========== 事件处理 ==========
const handleBodyScroll = (e: Event) => {
  if (headerRef.value) {
    headerRef.value.scrollLeft = (e.target as HTMLElement).scrollLeft
  }
  uiStore.saveScrollPosition((e.target as HTMLElement).scrollTop)
  hideConfidenceTooltip()
  hideRowTooltip()
}

const handleClickOutside = (e: MouseEvent) => {
  if (contextMenuRef.value && !contextMenuRef.value.contains(e.target as Node)) {
    hideContextMenu()
  }
  hideConfidenceTooltip()
  hideRowTooltip()
}

// ========== 生命周期 ==========
onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // 恢复滚动位置
  if (bodyRef.value && uiStore.scrollPosition) {
    bodyRef.value.scrollTop = uiStore.scrollPosition
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

defineExpose({
  refreshTable: () => { } // 空函数，保留接口
})
</script>

<style scoped>
.toolbar {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  gap: 12px;
}

.rank-trend-btn {
  padding: 6px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 4px;
}

.rank-trend-btn:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  color: var(--color-highlight);
}

.loading-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 30px;
  background: var(--bg-secondary);
  border-radius: 16px;
  box-shadow: var(--shadow-md);
  min-width: 200px;
  z-index: 10;
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.loading-icon {
  font-size: 48px;
  animation: spin 1s linear infinite;
}

.loading-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.loading-progress {
  width: 180px;
  height: 4px;
  background: var(--border-color);
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}

.progress-bar {
  height: 100%;
  background: var(--color-highlight);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.progress-text {
  position: absolute;
  right: 0;
  top: -18px;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 骨架屏覆盖层 */
.skeleton-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
  pointer-events: none;
}

.skeleton-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: var(--bg-primary);
  border-radius: 24px;
  box-shadow: var(--shadow-md);
  font-size: 13px;
  color: var(--text-secondary);
}

.loading-progress.small {
  width: 80px;
  height: 3px;
}

.loading-progress.small .progress-text {
  display: none;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.data-table-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  width: 100%;
}

/* 表头区域 */
.table-header {
  overflow-x: auto;
  overflow-y: visible;
  border-bottom: 2px solid var(--border-color);
  background: var(--bg-header);
  flex-shrink: 0;
  width: 100%;
  position: sticky;
  top: 0;
  z-index: 10;
}

.table-header::-webkit-scrollbar {
  height: 0;
  width: 0;
}

/* 确保表头和表体内容对齐 */
.table-header,
.table-body {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
}

.table-body {
  overflow-y: auto;
}

.data-row {
  box-sizing: border-box;
}

.cell {
  box-sizing: border-box;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 表体区域 */
.table-body {
  flex: 1;
  overflow: auto;
  width: 100%;
}

/* 分组表头行 */
.header-group-row {
  display: grid;
  background: var(--bg-secondary);
  border-bottom: 2px solid var(--border-color);
}

.header-group-cell {
  padding: 10px 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-title);
  text-align: center;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 列表头行 */
.header-row {
  display: grid;
  background: var(--bg-header);
  overflow: visible;
}

.header-cell {
  padding: 14px 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  text-align: center;
  border-bottom: 2px solid var(--border-color);
  transition: all 0.2s ease;
  letter-spacing: 0.3px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  position: relative;
  overflow: visible;
}

.header-cell:hover {
  color: var(--color-highlight);
  background: var(--bg-hover);
}

.header-cell.sorted {
  color: var(--color-highlight);
}

.sort-icon {
  font-size: 10px;
  opacity: 0.8;
}

/* 热榜排名折叠按钮（【综合】列左侧） */
.rank-collapse-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  line-height: 1;
  transition: color 0.2s ease, transform 0.2s ease;
}

.rank-collapse-toggle:hover {
  color: var(--color-highlight);
}

.rank-collapse-arrow {
  display: inline-block;
  font-size: 9px;
  transition: transform 0.22s ease;
}

.rank-collapse-toggle.collapsed .rank-collapse-arrow {
  transform: rotate(0deg);
  /* ▶ 右三角：折叠态，点击展开 */
}

/* 数据行 */
.data-row {
  display: grid;
  border-bottom: 1px solid var(--border-color);
  height: 48px;
  min-height: 48px;
  align-items: center;
  width: 100%;
  min-width: fit-content;
}

.data-row:hover {
  background: var(--bg-hover);
}

.data-row.selected {
  background: rgba(255, 165, 2, 0.15) !important;
  position: relative;
  z-index: 2;
}

.data-row.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--color-highlight) !important;
  box-shadow: 0 0 8px var(--color-highlight) !important;
  z-index: 3;
}

.data-row.selected:hover {
  background: rgba(255, 165, 2, 0.2) !important;
}

/* 奇偶行交替背景 */
.data-row.row-even {
  background: transparent;
}

.data-row.row-odd {
  background: rgba(0, 0, 0, 0.02);
}

/* 单元格通用样式 */
.cell {
  padding: 0 8px;
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 48px;
  height: 48px;
}

/* 文字类单元格左对齐 */
.code-cell,
.name-cell,
.sector-cell {
  text-align: left;
  font-weight: 500;
}

/* 数字单元格右对齐 */
.number-cell {
  text-align: right;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

/* 代码列特殊样式 */
.code-cell {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  color: var(--color-highlight);
}

/* 名称列特殊样式 */
.name-cell {
  font-weight: 500;
  color: var(--text-primary);
}

.stock-name-text {
  vertical-align: middle;
}

/* 题材列 */
.sector-cell {
  padding-left: 8px;
}


/* 涨跌颜色 */
.color-up {
  color: #ff4757 !important;
  font-weight: 600;
}

.color-down {
  color: #2ed573 !important;
  font-weight: 600;
}

.color-highlight {
  color: #ffa502 !important;
  font-weight: 700;
}

.money-positive {
  color: #ff4757 !important;
  font-weight: 600;
}

.money-negative {
  color: #2ed573 !important;
  font-weight: 600;
}

/* 排名变化单元格 */
.rank-change-cell {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  cursor: help;
}

/* 上升颜色 */
.rank-up {
  color: #ff4757 !important;
  font-weight: 600;
}

/* 下降颜色 */
.rank-down {
  color: #2ed573 !important;
  font-weight: 600;
}

/* 无变化 */
.trend-steady {
  color: var(--text-secondary);
}

/* 量比相对状态（当日中位数基准：×1.5 放量 / ×0.5 缩量） */
.vr-up {
  color: #ff4757;
  font-weight: 500;
}

.vr-down {
  color: #4a90e2;
  font-weight: 500;
}

.vr-normal {
  color: var(--text-secondary);
}

/* ========== 量价配合 ========== */
/* 四象限列 */
.quadrant-rise_volume {
  color: #ff4757;
  font-weight: 500;
}

.quadrant-rise_shrink {
  color: #ffb142;
  font-weight: 500;
}

.quadrant-fall_volume {
  color: #4a90e2;
  font-weight: 500;
}

.quadrant-fall_shrink {
  color: #7f8c8d;
}

.quadrant-normal {
  color: var(--text-secondary);
}

/* 趋势强度标记 */
.trend-strength {
  font-size: 10px;
  color: #ffa502;
  margin-left: 2px;
}

/* 买入信号 - 红色系 */
.signal-buy {
  font-size: 11px;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 12px;
  font-weight: 500;
  border: 1px solid;
}

/* 高置信度买入 - 深红色 */
.signal-buy.confidence-high {
  background: rgba(255, 71, 87, 0.25);
  border-color: #ff4757;
  color: #ff4757;
  font-weight: 600;
}

/* 中置信度买入 - 红色 */
.signal-buy.confidence-mid {
  background: rgba(255, 71, 87, 0.15);
  border-color: rgba(255, 71, 87, 0.6);
  color: #ff6b6b;
}

/* 低置信度买入 - 浅红色 */
.signal-buy.confidence-low {
  background: rgba(255, 71, 87, 0.08);
  border-color: rgba(255, 71, 87, 0.3);
  color: #ff8a8a;
}

/* 卖出信号 - 绿色系 */
.signal-sell {
  font-size: 11px;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 12px;
  font-weight: 500;
  border: 1px solid;
}

/* 高置信度卖出 - 深绿色 */
.signal-sell.confidence-high {
  background: rgba(46, 213, 115, 0.25);
  border-color: #2ed573;
  color: #2ed573;
  font-weight: 600;
}

/* 中置信度卖出 - 绿色 */
.signal-sell.confidence-mid {
  background: rgba(46, 213, 115, 0.15);
  border-color: rgba(46, 213, 115, 0.6);
  color: #5ee08a;
}

/* 低置信度卖出 - 浅绿色 */
.signal-sell.confidence-low {
  background: rgba(46, 213, 115, 0.08);
  border-color: rgba(46, 213, 115, 0.3);
  color: #8ae8aa;
}

/* 右键菜单 */
.context-menu {
  position: fixed;
  width: 200px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
  z-index: 10060;
  padding: 6px 0;
  font-size: 13px;
}

.menu-item {
  padding: 8px 16px;
  cursor: pointer;
  color: var(--text-primary);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 10px;
}

.menu-item:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

.menu-divider {
  height: 1px;
  background: var(--border-color);
  margin: 6px 0;
}

.menu-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

/* 子菜单 */
.submenu {
  position: absolute;
  left: 100%;
  top: 0;
  min-width: 160px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: var(--shadow-lg);
  z-index: 10070;
  padding: 6px 0;
}

.submenu-item {
  padding: 6px 12px;
  cursor: pointer;
  color: var(--text-primary);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.submenu-item:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
}

.submenu-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.submenu-divider {
  height: 1px;
  background: var(--border-color);
  margin: 6px 0;
}

.board-color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.board-count {
  margin-left: auto;
  font-size: 10px;
  padding: 2px 4px;
  background: var(--badge-bg);
  border-radius: 10px;
  color: var(--badge-text);
}

.submenu-indicator {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.6;
}

/* 滚动条 */
.table-body::-webkit-scrollbar,
.table-header::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.table-body::-webkit-scrollbar-track,
.table-header::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

.table-body::-webkit-scrollbar-thumb,
.table-header::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 4px;
}

.table-body::-webkit-scrollbar-thumb:hover,
.table-header::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 题材点击保护 */
.sector-click-guard {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
}

.sector-cell-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
}

.sector-cell :deep(.sector-tags) {
  max-width: 100%;
  overflow-x: auto;
  white-space: nowrap;
  display: flex;
  gap: 4px;
}

/* 空状态 */
.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-tertiary);
  font-size: 14px;
  padding: 30px;
  background: var(--bg-secondary);
  border-radius: 12px;
  box-shadow: var(--shadow-md);
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.empty-icon {
  font-size: 40px;
}

/* 题材单元格 */
.themes-cell {
  text-align: left;
  padding-left: 8px;
  height: 48px;
  display: flex;
  align-items: center;
}

/* 涨停原因列：限宽省略，悬停看全文；取值来源同花顺涨停池 reason_type（仅涨停股有值）；
   字体与名称列一致（12px / --text-primary，继承 .cell 基础字号） */
.limit-up-reason-text {
  display: inline-block;
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  color: var(--text-primary);
}

/* 题材徽章 */
.themes-badge {
  display: inline-block;
  padding: 0 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  line-height: 20px;
  height: 20px;
  transition: all 0.2s;
  cursor: context-menu;
}

.themes-badge:hover {
  filter: brightness(1.1);
  max-width: none;
  overflow: visible;
  position: relative;
  z-index: 10;
  transform: scale(1.02);
}

/* 单个题材 - 蓝色系（类似幼苗期） */
.theme-single {
  background: rgba(74, 222, 128, 0.15);
  border-color: #4ade80;
  color: #4ade80;
}

/* 两个题材 - 橙色系（类似成长期） */
.theme-double {
  background: rgba(251, 191, 36, 0.15);
  border-color: #fbbf24;
  color: #fbbf24;
}

/* 多个题材 - 红色系（类似成熟期） */
.theme-multiple {
  background: rgba(239, 68, 68, 0.15);
  border-color: #ef4444;
  color: #ef4444;
  font-weight: 600;
}

/* 不同热度等级 */
.themes-normal {
  background: rgba(100, 100, 100, 0.1);
  border-color: #6b7280;
  color: #9ca3af;
}

.themes-warm {
  background: rgba(251, 191, 36, 0.1);
  border-color: #fbbf24;
  color: #fbbf24;
}

.themes-hot {
  background: rgba(239, 68, 68, 0.1);
  border-color: #ef4444;
  color: #ef4444;
  font-weight: 600;
}

/* 空题材 - 灰色 */
.themes-empty {
  color: var(--text-tertiary);
  font-size: 11px;
}

.theme-tag-only {
  background: rgba(156, 39, 176, 0.15);
  border-color: #9c27b0;
  color: #9c27b0;
}

.theme-tag-only:hover {
  background: rgba(156, 39, 176, 0.25);
}

/* 置信度单元格 */
.confidence-cell {
  text-align: center;
  padding: 4px 8px;
}

.confidence-tooltip {
  position: fixed;
  z-index: 12000;
  max-width: 420px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(24, 24, 28, 0.96);
  color: #f3f0eb;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.38);
  white-space: pre-line;
  line-height: 1.6;
  font-size: 12px;
  pointer-events: none;
}

.row-tooltip {
  position: fixed;
  z-index: 11990;
  max-width: 360px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(24, 24, 28, 0.95);
  color: #ebe6df;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.32);
  white-space: pre-line;
  line-height: 1.55;
  font-size: 12px;
  pointer-events: none;
}

.candidate-pool-state-triggered_wait_entry {
  color: #ff8c42;
  background: rgba(255, 140, 66, 0.12);
  border: 1px solid rgba(255, 140, 66, 0.28);
}

.candidate-pool-state-active_holding {
  color: #3ddc97;
  background: rgba(61, 220, 151, 0.12);
  border: 1px solid rgba(61, 220, 151, 0.26);
}

.candidate-pool-state-exit_signaled {
  color: #4da6ff;
  background: rgba(77, 166, 255, 0.12);
  border: 1px solid rgba(77, 166, 255, 0.24);
}

.candidate-pool-state-closed {
  color: #d8c27a;
  background: rgba(216, 194, 122, 0.12);
  border: 1px solid rgba(216, 194, 122, 0.22);
}

.candidate-pool-state-idle {
  color: #8f99a8;
  background: rgba(143, 153, 168, 0.1);
  border: 1px solid rgba(143, 153, 168, 0.18);
}

/* MA 金死叉徽章样式（2026-09-13 五因子化：趋势列徽章 MACD→MA） */
.ma-badge {
  font-size: 14px;
  margin-left: 4px;
  display: inline-block;
  vertical-align: middle;
}

.ma-badge.golden {
  color: #ffd700;
  text-shadow: 0 0 3px rgba(255, 215, 0, 0.5);
  filter: drop-shadow(0 0 2px rgba(255, 215, 0, 0.8));
}

.ma-badge.death {
  color: #3498db;
  text-shadow: 0 0 2px rgba(52, 152, 219, 0.5);
  filter: drop-shadow(0 0 2px rgba(52, 152, 219, 0.8));
}

/* 三轨观察指标 */
.observation-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  /* 撑满 cell（48px 行高），观察列内容垂直居中，不再靠上 */
  min-height: 30px;
  line-height: 1;
  /* 覆盖 .cell 继承的 48px 行高，避免内部文本行盒撑高 */
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  border-bottom: 1px solid transparent;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.observation-cell:hover {
  border-bottom-color: currentColor;
}

.observation-buy,
.lifecycle-expansion {
  color: #ff4757;
}

.lifecycle-ignition {
  color: #f1c40f;
}

.lifecycle-crowded {
  color: #ff9f43;
}

.observation-sell,
.lifecycle-reversal {
  color: #2ed573;
}

.observation-hold,
.lifecycle-cooling {
  color: #95a5a6;
}

/* 生命周期环境门标签（2026-08-16 优化：无方向区分度，显示 stage+环境色；逐 stage 色与
   OBSERVATION 面板 .stage-* 一致：点火黄 #e7bd4d/扩散红 #ff5b62/拥挤橙 #ff9f43/反转绿 #38c98b/
   冷却灰 #8f999c；否决（veto）由红色"否决"角标单独表达） */
.lifecycle-env-ignition {
  color: #e7bd4d !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(231, 189, 77, 0.1);
}

.lifecycle-env-expansion {
  color: #ff5b62 !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(255, 91, 98, 0.1);
}

.lifecycle-env-crowded {
  color: #ff9f43 !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(255, 159, 67, 0.1);
}

.lifecycle-env-reversal {
  color: #38c98b !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(56, 201, 139, 0.1);
}

.lifecycle-env-cooling {
  color: #8f999c !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(143, 153, 156, 0.1);
}

/* 样本不足（2026-09-10 口径统一，spec §4.1）：历史样本不足时周期列显示数据质量声明（中性虚线框），
   不再显示 lifecycle 兜底"冷却"；排序方向归中性 */
.lifecycle-env-insufficient {
  color: #8f999c !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(143, 153, 156, 0.08);
  border: 1px dashed rgba(143, 153, 156, 0.4);
}

.lifecycle-env-neutral {
  color: #95a5a6 !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(149, 165, 166, 0.08);
}

/* 档位徽章（四维列方案 §4.4，与现有观察色系对齐） */
.tier-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  min-width: 20px;
  height: 20px;
  margin: 0 3px;
  padding: 0 3px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  line-height: 20px;
}

/* 档位图标（2026-08-18 lucide 内联 SVG，stroke 继承档位颜色） */
.tier-icon {
  width: 12px;
  height: 12px;
  display: block;
}

.tier-s {
  color: #ff4757;
  background: rgba(255, 71, 87, 0.14);
  border: 1px solid rgba(255, 71, 87, 0.5);
}

.tier-a {
  color: #ff9f43;
  background: rgba(255, 159, 67, 0.12);
  border: 1px solid rgba(255, 159, 67, 0.4);
}

.tier-b {
  color: #ff6b81;
  background: rgba(255, 107, 129, 0.12);
  border: 1px solid rgba(255, 107, 129, 0.4);
}

.tier-c {
  color: #95a5a6;
  background: rgba(149, 165, 166, 0.12);
  border: 1px solid rgba(149, 165, 166, 0.4);
}

.tier-d {
  color: #2ed573;
  background: rgba(46, 213, 115, 0.12);
  border: 1px solid rgba(46, 213, 115, 0.4);
}

.tier-e {
  color: #fff;
  background: #e74c3c;
  border: 1px solid #c0392b;
  box-shadow: 0 0 6px rgba(231, 76, 60, 0.6);
}

.tier-unknown {
  color: #7f8c8d;
  background: transparent;
  border: 1px dashed #7f8c8d;
}

.synergy-tier-cell {
  min-width: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 量比保持稳定显示，数据状态留在悬浮说明中 */
.volume-ratio-cell {
  color: var(--text-primary);
  font-weight: 600;
}

/* 八平台排名前三样式 */
.platform-1st {
  background: linear-gradient(135deg, #ffd700 0%, #ffb300 100%);
  color: #000 !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

.platform-2nd {
  background: linear-gradient(135deg, #c0c0c0 0%, #a0a0a0 100%);
  color: #000 !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

.platform-3rd {
  background: linear-gradient(135deg, #cd7f32 0%, #b87333 100%);
  color: #fff !important;
  padding: 0 4px;
  border-radius: 8px;
  font-weight: bold;
  font-size: 10px;
  display: inline-block;
  min-width: 24px;
  text-align: center;
  line-height: 16px;
  height: 16px;
}

/* 第4-10名排名高亮 */
.cell[data-key="emRank"] .rank-4-10,
.cell[data-key="thsRank"] .rank-4-10,
.cell[data-key="kplRank"] .rank-4-10,
.cell[data-key="tdxRank"] .rank-4-10,
.cell[data-key="xqRank"] .rank-4-10,
.cell[data-key="clsRank"] .rank-4-10,
.cell[data-key="tgbRank"] .rank-4-10,
.cell[data-key="dzhRank"] .rank-4-10 {
  color: #ffa502 !important;
  font-weight: 600;
}
</style>
