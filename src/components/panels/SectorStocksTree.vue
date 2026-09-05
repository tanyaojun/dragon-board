<template>
  <div class="sector-stocks-container">
    <!-- 子页签：题材列表 / 题材动量 -->
    <div class="panel-tabs">
      <button class="tab-btn" :class="{ active: activeTab === 'list' }" @click="activeTab = 'list'">
        🌲 题材列表
      </button>
      <button class="tab-btn" :class="{ active: activeTab === 'momentum' }" @click="activeTab = 'momentum'">
        📊 题材动量
      </button>
    </div>

    <div v-if="activeTab === 'list'" class="tab-content">
      <!-- 左侧题材树 -->
      <div class="sector-tree">
      <div class="tree-header">
        <h4>📊 题材列表</h4>
        <div class="tree-filter-row">
          <ThemeSortControl class="tree-sort-control" />
          <div class="tree-search">
            <input v-model="treeSearch" placeholder="搜索题材..." class="search-input" />
          </div>
        </div>
        <div class="tree-stats">
          共 {{ filteredSectors.length }} 个题材
        </div>
      </div>

      <div class="tree-content" ref="treeContentRef">
        <div v-for="sector in paginatedSectors" :key="sector.id" class="tree-node"
          :class="{ 'selected': selectedSector?.id === sector.id }" @click="selectSector(sector)">
          <div class="node-header">
            <span class="node-name">{{ sector.name }}</span>
            <div class="node-badges">
              <span class="strength-badge" :class="deriveThemeHeatBand(sector.strength)">
                {{ formatStrengthBand(sector.strength) }}
              </span>
              <span class="zt-badge" v-if="sector.ztCount > 0">
                {{ sector.ztCount }}
              </span>
            </div>
          </div>
          <div class="node-metrics">
            <span class="change">
              动量 {{ sector.change.toFixed(0) }}
            </span>
            <span class="inflow" :class="(sector.mainNetInflow || 0) >= 0 ? 'inflow' : 'outflow'">
              {{ sector.mainNetInflow == null ? '--' : formatMoney(sector.mainNetInflow) }}
            </span>
          </div>
          <div class="node-progress" v-if="sector.strength != null">
            <div class="progress-bar" :style="{ width: Math.min(100, sector.strength) + '%' }"></div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="filteredSectors.length > pageSize" class="tree-pagination">
          <button @click="treePage--" :disabled="treePage === 1">←</button>
          <span>{{ treePage }}/{{ treeTotalPages }}</span>
          <button @click="treePage++" :disabled="treePage === treeTotalPages">→</button>
        </div>
      </div>
    </div>

    <!-- 右侧成分股表格 -->
    <div class="stocks-table-container" v-if="selectedSector">
      <!-- 加载状态 -->
      <div v-if="loadingStocks" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载成分股...</span>
      </div>

      <template v-else>
        <div class="table-header">
          <h4>
            📈 {{ selectedSector.name }} 成分股
            <span class="sector-metrics">
              <span class="badge" :class="deriveThemeHeatBand(selectedSector.strength)">
                热度 {{ selectedSector.strength == null ? '--' : selectedSector.strength }}
              </span>
              <span class="badge" :class="selectedSector.change >= 0 ? 'up' : 'down'">
                动量 {{ selectedSector.change.toFixed(0) }}
              </span>
            </span>
          </h4>
          <div class="table-controls">
            <div class="search-box">
              <input v-model="stockSearch" placeholder="搜索股票..." class="search-input" />
            </div>
            <div class="sort-controls">
              <select v-model="sortBy" class="sort-select">
                <option value="change">涨跌幅</option>
                <option value="volumeRatio">量比</option>
                <option value="mainNetInflow">主力净额</option>
                <option value="leader">龙头</option>
                <option value="lianban">连板</option>
                <option value="firstZtTime">首次涨停时间</option>
                <option value="fengdan">封单金额</option>
              </select>
              <button class="sort-btn" @click="sortDesc = !sortDesc">
                {{ sortDesc ? '↓' : '↑' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 表格包装器 -->
        <div class="table-wrapper" ref="tableWrapperRef">
          <table class="stocks-table">
            <thead>
              <tr>
                <th>#</th>
                <th>代码</th>
                <th>名称</th>
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
              </tr>
            </thead>
            <tbody>
              <tr v-for="(stock, index) in paginatedStocks" :key="stock.code" :class="{ 'zt-row': isZtStock(stock) }"
                @dblclick="openStockDetail(stock.code)">
                <td>{{ (stockPage - 1) * stockPageSize + index + 1 }}</td>
                <td>
                  <span class="code-link" @click.stop="openTdx(stock.code)">{{ stock.code }}</span>
                </td>
                <td>{{ stock.name }}</td>
                <td :class="stock.change >= 0 ? 'up' : 'down'">
                  {{ stock.change > 0 ? '+' : '' }}{{ stock.change.toFixed(2) }}%
                </td>
                <td>{{ stock.volumeRatio?.toFixed(2) || '-' }}</td>
                <td :class="(stock.mainNetInflow || 0) >= 0 ? 'inflow' : 'outflow'">
                  {{ stock.mainNetInflow == null ? '--' : formatMoney(stock.mainNetInflow) }}
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
      </template>
    </div>

    <!-- 未选择题材时的提示 -->
    <div v-else class="empty-selection">
      <div class="empty-icon">📊</div>
      <div class="empty-text">请从左侧选择一个题材</div>
    </div>
    </div>

    <!-- 题材动量（嵌入式面板） -->
    <ThemeMomentumPanel v-else embedded class="momentum-tab-content" />
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { StockUtils } from '@/utils/common'
import { ref, computed, onMounted, watch } from 'vue'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { deriveThemeHeatBand } from '@/services/theme/stockThemeMeta'
import {
  compareThemeStockRows,
  formatFengdanYi,
  formatLeaderRank,
  formatLianbanText,
  formatOpenNum,
} from '@/services/theme/stockLimitUpRows'
import { useThemeRuntimeSnapshot } from '@/composables/useThemeRuntimeSnapshot'
import ThemeMomentumPanel from './ThemeMomentumPanel.vue'
import ThemeSortControl from './ThemeSortControl.vue'

// Props
const props = defineProps<{
  initialSector?: string
}>()

// 事件
const emit = defineEmits<{
  (e: 'select-stock', code: string): void
}>()

// 状态
const activeTab = ref<'list' | 'momentum'>('list')
const treeSearch = ref('')
const treePage = ref(1)
const pageSize = ref(10)
const selectedSector = ref<any>(null)
const loadingStocks = ref(false)  // 添加加载状态
const sectorStockRows = ref<any[]>([])
const themeRuntime = useThemeRuntimeSnapshot()

// 表格状态
const stockSearch = ref('')
// 默认按龙头排序：leaderRank 编位（连板降序+首次涨停时间升序），龙一在最前
const sortBy = ref('leader')
const sortDesc = ref(true)
const stockPage = ref(1)
const stockPageSize = ref(20)

// DOM 引用
const treeContentRef = ref<HTMLElement>()
const tableWrapperRef = ref<HTMLElement>()

// 涨停行高亮：统一走 StockUtils 分板块阈值（主板10%/创业科创20%/北交所30%，主板ST 5%）
function isZtStock(stock: { code: string; name?: string; change?: number }): boolean {
  return StockUtils.isLimitUp(stock.change || 0, stock.code, stock.name || '')
}

// ========== 左侧题材树数据 ==========
const allSectors = computed(() => {
  if (!themeRuntime.value.factors.length) return []
  return themeFacade.getThemeSummaries(200).map(theme => ({
    id: theme.id,
    name: theme.name,
    strength: theme.heatLevelScore,
    change: theme.momentumScore,
    mainNetInflow: theme.mainNetInflow,
    ztCount: theme.ztCount,
    volumeRatio: theme.volumeRatio,
  }))
})

// 过滤题材
const filteredSectors = computed(() => {
  let result = allSectors.value
  if (treeSearch.value) {
    const keyword = treeSearch.value.toLowerCase()
    result = result.filter(s =>
      s.name.toLowerCase().includes(keyword) ||
      s.id.toLowerCase().includes(keyword)
    )
  }
  return result
})

// 分页题材
const paginatedSectors = computed(() => {
  const start = (treePage.value - 1) * pageSize.value
  return filteredSectors.value.slice(start, start + pageSize.value)
})

const treeTotalPages = computed(() =>
  Math.ceil(filteredSectors.value.length / pageSize.value)
)

// ========== 右侧成分股数据 ==========
const sectorStocks = computed(() => sectorStockRows.value)

// 过滤股票
const filteredStocks = computed(() => {
  let result = [...sectorStocks.value]
  if (stockSearch.value) {
    const keyword = stockSearch.value.toLowerCase()
    result = result.filter(s =>
      s.code.toLowerCase().includes(keyword) ||
      s.name.toLowerCase().includes(keyword)
    )
  }
  result.sort((a, b) => compareThemeStockRows(a, b, sortBy.value, sortDesc.value))
  return result
})

// 分页股票
const paginatedStocks = computed(() => {
  const start = (stockPage.value - 1) * stockPageSize.value
  return filteredStocks.value.slice(start, start + stockPageSize.value)
})

const stockTotalPages = computed(() =>
  Math.ceil(filteredStocks.value.length / stockPageSize.value)
)

// ========== 方法 ==========
async function selectSector(sector: any) {
  selectedSector.value = sector
  stockPage.value = 1
  stockSearch.value = ''

  // 显示加载状态
  loadingStocks.value = true

  try {
    // 打开题材走 30 秒 LRU 缓存（themeHeatStocksCache），避免每次点击都强制后端查 MongoDB 重算；
    // 涨停池字段（龙一/连板/封单等）由 loadSectorStocks 用 dataLayer 内存数据本地合入，不受缓存影响
    const stocks = await sectorAnalyzer.loadSectorStocks(sector.id, sector.name)
    // 行数据已由 enrichStocksWithLimitUp 合入涨停池字段并编好 leaderRank（龙一/龙二……）
    sectorStockRows.value = [...stocks]

    // 更新到本地数据
    if (stocks && stocks.length > 0) {
      // 可以加个提示
      debugLog(`[SectorStocksTree] ${sector.name} 加载 ${stocks.length} 只股票`)
    }
  } catch (error) {
    console.error('加载板块个股失败:', error)
  } finally {
    loadingStocks.value = false
  }

  setTimeout(() => {
    if (tableWrapperRef.value) {
      tableWrapperRef.value.scrollTop = 0
    }
  }, 50)
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

// 热度徽章（审计修复：旧函数吃 80/65/50/35 自造阈值且输入是 heatScore 绝对值，
// v2 口径下热门题材全部挤 'S'）。统一走 heatLevelScore 相对分 + stockThemeMeta
// deriveThemeHeatBand（80/60/40/20 五档）；缺失显示 '-' 不伪装低分。
function formatStrengthBand(score: number | null | undefined): string {
  if (score == null || typeof score !== 'number' || !Number.isFinite(score)) return '-'
  return deriveThemeHeatBand(score).toUpperCase()
}

function getLianbanClass(lianban: string): string {
  if (lianban.includes('首板')) return 'first'
  if (lianban.includes('2板')) return 'second'
  if (lianban.includes('3板')) return 'third'
  if (lianban.includes('4板')) return 'fourth'
  return ''
}

function formatMoney(value: number): string {
  if (!value) return '-'
  const abs = Math.abs(value)
  if (abs >= 1e8) return (value / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (value / 1e4).toFixed(2) + '万'
  return value.toString()
}

function openTdx(code: string) {
  window.open(`https://www.tdx.com.cn/code_${code}`, '_blank')
}

function openStockDetail(code: string) {
  debugLog('[SectorStocksTree] 双击股票:', code)
  emit('select-stock', code)
}

// 初始化选择
onMounted(() => {
  if (props.initialSector && allSectors.value.length) {
    const found = allSectors.value.find(s =>
      s.name === props.initialSector || s.id === props.initialSector
    )
    if (found) selectSector(found)
  }
})

// 监听搜索重置页码
watch(treeSearch, () => {
  treePage.value = 1
})

watch([stockSearch, sortBy, sortDesc], () => {
  stockPage.value = 1
})

</script>

<style scoped>
/* ========== 容器样式 ========== */
.sector-stocks-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 500px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

/* ========== 子页签栏（题材列表 / 题材动量） ========== */
.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 12px 0;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.tab-btn {
  padding: 7px 14px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px 8px 0 0;
  font-size: 12px;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--bg-primary);
  color: var(--text-title);
  font-weight: 600;
  border-bottom-color: var(--color-highlight);
}

.tab-content {
  flex: 1;
  display: flex;
  min-height: 0;
}

.momentum-tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
}

/* ========== 左侧题材树 ========== */
.sector-tree {
  width: 280px;
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  flex-shrink: 0;
}

.tree-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.tree-header h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--text-primary);
}

.tree-filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.tree-sort-control {
  flex-shrink: 0;
  font-size: 12px;
}

/* 行内空间有限：压缩排序摘要文本宽度，完整口径由触发按钮 title 提供 */
.tree-sort-control :deep(.trigger-text) {
  max-width: 96px;
}

.tree-search {
  flex: 1;
  min-width: 0;
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

.tree-stats {
  font-size: 11px;
  color: var(--text-secondary);
}

.tree-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
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
  font-size: 11px;
  margin-bottom: 6px;
}

.change.up {
  color: #ff4757;
}

.change.down {
  color: #2ed573;
}

.inflow.inflow {
  color: #ff4757;
}

.inflow.outflow {
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
  background: var(--color-highlight);
  border-radius: 2px;
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

/* ========== 右侧表格容器 ========== */
.stocks-table-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  min-width: 0;
}

.table-header {
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.table-header h4 {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 12px 0;
  font-size: 14px;
}

.sector-metrics {
  display: flex;
  gap: 8px;
  font-size: 11px;
}

.sector-metrics .badge {
  padding: 2px 8px;
  border-radius: 12px;
}

.table-controls {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search-box {
  flex: 1;
}

.sort-controls {
  display: flex;
  gap: 4px;
}

.sort-select {
  padding: 4px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
}

.sort-btn {
  padding: 4px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  cursor: pointer;
}

/* 表格包装器 */
.table-wrapper {
  flex: 1;
  overflow: auto;
  padding: 0 16px 16px 16px;
  scrollbar-width: thin;
}

/* 自定义滚动条样式 */
.table-wrapper::-webkit-scrollbar {
  height: 8px;
  width: 8px;
}

.table-wrapper::-webkit-scrollbar-track {
  background: var(--bg-secondary);
  border-radius: 4px;
}

.table-wrapper::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 4px;
}

.table-wrapper::-webkit-scrollbar-thumb:hover {
  background: var(--color-highlight);
}

/* 表格样式 */
.stocks-table {
  border-collapse: collapse;
  font-size: 12px;
  min-width: 100%;
  white-space: nowrap;
}

/* 涨停原因列：限宽省略，悬停看全文；其余列由内容自适应宽度 */
.stocks-table .reason-text {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
}

.stocks-table th {
  position: sticky;
  top: 0;
  background: var(--bg-primary);
  padding: 8px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  cursor: pointer;
  z-index: 2;
}

.stocks-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--border-color);
}

.stocks-table tbody tr {
  cursor: pointer;
}

.stocks-table tbody tr:hover {
  background: var(--bg-hover);
}

.stocks-table tbody tr.zt-row {
  background: rgba(255, 71, 87, 0.1);
}

.code-link {
  color: var(--color-highlight);
  text-decoration: underline;
  cursor: pointer;
}

.up {
  color: #ff4757;
  font-weight: 500;
}

.down {
  color: #2ed573;
  font-weight: 500;
}

.inflow {
  color: #ff4757;
  font-weight: 500;
}

.outflow {
  color: #2ed573;
  font-weight: 500;
}

.lead-badge {
  padding: 2px 6px;
  background: rgba(255, 215, 0, 0.2);
  border-radius: 4px;
  font-size: 10px;
  color: #ffd700;
}

.lead-badge.poban {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.lianban-badge {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
}

.lianban-badge.first {
  background: rgba(255, 215, 0, 0.2);
  color: #ffd700;
}

.lianban-badge.second {
  background: rgba(192, 192, 192, 0.2);
  color: #c0c0c0;
}

.lianban-badge.third {
  background: rgba(205, 127, 50, 0.2);
  color: #cd7f32;
}

.lianban-badge.fourth {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.blocks-preview {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  max-width: 120px;
}

.block-tag {
  padding: 2px 4px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 9px;
  color: var(--text-secondary);
}

.block-tag.more {
  background: var(--color-highlight);
  color: #000;
}

/* 分页样式 */
.table-pagination {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  padding: 16px;
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

/* 加载状态 */
.loading-state {
  flex: 1;
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

/* 空状态 */
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
</style>
