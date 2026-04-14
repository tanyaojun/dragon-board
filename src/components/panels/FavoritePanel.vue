<!-- src/components/panels/FavoritePanel.vue -->
<template>
  <div ref="panelRef" v-show="visible" class="favorite-panel" :class="themeStore.themeClass">
    <div class="panel-header">
      <h3>
        <span class="header-icon">{{ viewMode === 'favorites' ? '⭐' : '📊' }}</span>
        {{ viewMode === 'favorites' ? '自选股' : '板块管理' }}
      </h3>
      <div class="panel-actions">
        <!-- 视图切换 -->
        <button class="btn-icon" :class="{ active: viewMode === 'favorites' }" title="自选股视图"
          @click.stop="viewMode = 'favorites'">
          <span class="icon">⭐</span>
        </button>
        <button class="btn-icon" :class="{ active: viewMode === 'boards' }" title="板块视图"
          @click.stop="viewMode = 'boards'">
          <span class="icon">📊</span>
        </button>
        <button class="btn-icon" title="刷新" @click.stop="refresh">
          <span class="icon">↻</span>
        </button>
        <button class="btn-icon" title="关闭" @click.stop="$emit('close')">
          <span class="icon">✕</span>
        </button>
      </div>
    </div>

    <!-- 自选股视图 -->
    <template v-if="viewMode === 'favorites'">
      <div class="panel-tabs">
        <button v-for="group in allGroups" :key="group.name" class="tab-btn"
          :class="{ active: currentGroup === group.name }" @click="currentGroup = group.name">
          {{ group.name }}
          <span class="tab-count">{{ group.count }}</span>
        </button>
      </div>

      <div class="panel-content">
        <div v-if="filteredFavorites.length === 0" class="empty-state">
          <div class="empty-icon">📭</div>
          <div>暂无自选股</div>
          <small>在表格中右键点击股票加入自选</small>
        </div>

        <div v-else class="favorites-list">
          <div v-for="fav in filteredFavorites" :key="fav.code" class="favorite-item" @click="selectStock(fav.code)">
            <div class="favorite-info">
              <div class="stock-header">
                <span class="stock-code">{{ fav.code }}</span>
                <span class="stock-name">{{ fav.name }}</span>
              </div>
              <div v-if="fav.notes" class="stock-notes">{{ fav.notes }}</div>
            </div>

            <div class="favorite-price">
              <span class="price">{{ formatPrice(fav.lastPrice) }}</span>
              <span class="change" :class="getChangeClass(fav.lastChange)">
                {{ formatChange(fav.lastChange) }}
              </span>
            </div>

            <div class="favorite-actions">
              <button class="btn-icon-small" title="移除" @click.stop="removeFromFavorites(fav.code)">
                <span class="icon">✕</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 板块视图 -->
    <template v-else>
      <div class="panel-tabs">
        <button class="tab-btn" :class="{ active: !selectedBoard }" @click="selectedBoard = null">
          所有板块
          <span class="tab-count">{{ favoriteStore.boardList.length }}</span>
        </button>
        <button class="tab-btn" :class="{ active: selectedBoard === 'create' }" @click="showCreateBoard = true">
          <span class="icon">+</span> 新建板块
        </button>
      </div>

      <div class="panel-content">
        <!-- 创建板块表单 -->
        <div v-if="showCreateBoard" class="create-form" @click.stop>
          <input v-model="newBoardName" type="text" placeholder="输入板块名称" @keyup.enter="handleCreateBoard"
            @keyup.esc="showCreateBoard = false" ref="boardNameInput" />
          <div class="form-actions">
            <button class="btn-primary" @click="handleCreateBoard">创建</button>
            <button class="btn-text" @click="showCreateBoard = false">取消</button>
          </div>
        </div>

        <!-- 从自选股创建板块 -->
        <div v-if="!selectedBoard" class="quick-actions">
          <button class="btn-text" @click="showCreateFromFavorites = true" v-if="favoriteStore.favoriteList.length > 0">
            <span class="icon">⭐</span> 从自选股创建板块
          </button>
        </div>

        <!-- 从自选股创建表单 -->
        <div v-if="showCreateFromFavorites" class="create-form" @click.stop>
          <input v-model="newBoardFromFav" type="text" placeholder="输入新板块名称" @keyup.enter="createBoardFromFavorites" />
          <div class="form-actions">
            <button class="btn-primary" @click="createBoardFromFavorites">创建</button>
            <button class="btn-text" @click="showCreateFromFavorites = false">取消</button>
          </div>
          <div class="form-hint">
            将 {{ favoriteStore.favoriteList.length }} 只自选股创建为新板块
          </div>
        </div>

        <!-- 板块列表 -->
        <div v-if="!selectedBoard" class="boards-list">
          <div v-if="favoriteStore.boardList.length === 0" class="empty-state">
            <div class="empty-icon">📊</div>
            <div>暂无板块</div>
            <small>点击"新建板块"创建第一个板块</small>
          </div>

          <div v-else v-for="board in favoriteStore.boardList" :key="board.id" class="board-item"
            :style="{ borderLeftColor: board.color }">
            <div class="board-header">
              <div class="board-info" @click="selectedBoard = board.id">
                <span class="board-name">{{ board.name }}</span>
                <span class="board-count">{{ board.count }}只股票</span>
              </div>
              <div class="board-actions">
                <button class="btn-icon-small" title="编辑" @click.stop="editBoard(board)">
                  <span class="icon">✎</span>
                </button>
                <button class="btn-icon-small" title="删除" @click.stop="deleteBoard(board)">
                  <span class="icon">🗑️</span>
                </button>
              </div>
            </div>

            <!-- 板块内股票预览 -->
            <div class="board-preview" @click="selectedBoard = board.id">
              <div v-for="stock in getBoardStocks(board.id).slice(0, 3)" :key="stock.stock.code" class="preview-stock"
                @click.stop="selectStock(stock.stock.code)">
                <span class="stock-code">{{ stock.stock.code }}</span>
                <span class="stock-name">{{ stock.stock.name }}</span>
                <span v-if="stock.notes" class="stock-notes">({{ stock.notes }})</span>
              </div>
              <div v-if="board.count > 3" class="preview-more">
                等 {{ board.count }} 只股票
              </div>
            </div>
          </div>
        </div>

        <!-- 板块详情视图 -->
        <div v-else class="board-detail">
          <div class="detail-header">
            <button class="btn-icon-small" @click="selectedBoard = null" title="返回">
              <span class="icon">←</span>
            </button>
            <h4>{{ currentBoard?.name }}</h4>
            <span class="board-count">{{ currentBoard?.count }}只股票</span>
          </div>

          <div class="detail-actions">
            <button class="btn-text" @click="showAddToBoard = true">
              <span class="icon">+</span> 添加股票
            </button>
            <button class="btn-text" @click="showBoardNotes = true">
              <span class="icon">📝</span> 批量备注
            </button>
          </div>

          <!-- 添加股票到板块 -->
          <div v-if="showAddToBoard" class="add-stock-form">
            <select v-model="selectedStockCode" class="stock-select">
              <option value="">选择股票</option>
              <option v-for="fav in favoriteStore.favoriteList" :key="fav.code" :value="fav.code">
                {{ fav.code }} {{ fav.name }}
              </option>
            </select>
            <input v-model="stockNotes" type="text" placeholder="备注（如：龙头、次队列）" />
            <div class="form-actions">
              <button class="btn-primary" @click="addStockToBoard" :disabled="!selectedStockCode">
                添加
              </button>
              <button class="btn-text" @click="showAddToBoard = false">取消</button>
            </div>
          </div>

          <!-- 板块内股票列表 -->
          <div class="board-stocks">
            <div v-for="item in currentBoardStocks" :key="item.stock.code" class="stock-item">
              <div class="stock-info" @click="selectStock(item.stock.code)">
                <span class="stock-code">{{ item.stock.code }}</span>
                <span class="stock-name">{{ item.stock.name }}</span>
                <span v-if="item.notes" class="stock-notes-badge">{{ item.notes }}</span>
              </div>
              <div class="stock-price">
                <span class="price">{{ formatPrice(item.stock.lastPrice) }}</span>
                <span class="change" :class="getChangeClass(item.stock.lastChange)">
                  {{ formatChange(item.stock.lastChange) }}
                </span>
              </div>
              <div class="stock-actions">
                <button class="btn-icon-small" title="编辑备注" @click.stop="editStockNotes(item)">
                  <span class="icon">✎</span>
                </button>
                <button class="btn-icon-small" title="从板块移除" @click.stop="removeStockFromBoard(item.stock.code)">
                  <span class="icon">✕</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div class="panel-footer">
      <button class="btn-text" @click="exportFavorites">
        <span class="icon">📤</span> 导出
      </button>
      <button class="btn-text" @click="importFavorites">
        <span class="icon">📥</span> 导入
      </button>
      <button class="btn-text" @click="syncWithMarketData">
        <span class="icon">↻</span> 同步
      </button>
      <button class="btn-text" @click="clearAllFavorites" v-if="favoriteStore.favoriteList.length > 0">
        <span class="icon">🗑️</span> 清空
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'  // 添加 watch
import { useFavoriteStore } from '@/stores/favorite'
import { useThemeStore } from '@/stores/theme'
import { useUIStore } from '@/stores/ui'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import type { Board } from '@/types'  // Board 从 types 导入
const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:visible', value: boolean): void
}>()

const panelRef = ref<HTMLElement | null>(null)
const boardNameInput = ref<HTMLInputElement | null>(null)

const favoriteStore = useFavoriteStore()
const themeStore = useThemeStore()
const uiStore = useUIStore()

// 视图模式
const viewMode = ref<'favorites' | 'boards'>('favorites')

// 自选股相关
const currentGroup = ref('全部')

type FavoriteStock = ReturnType<typeof useFavoriteStore>['favoriteList'][0]

// 板块相关
const selectedBoard = ref<string | null>(null)
const showCreateBoard = ref(false)
const showCreateFromFavorites = ref(false)
const showAddToBoard = ref(false)
const showBoardNotes = ref(false)
const newBoardName = ref('')
const newBoardFromFav = ref('')
const selectedStockCode = ref('')
const stockNotes = ref('')
const editingStock = ref<{ stock: FavoriteStock; notes: string } | null>(null)

// 所有分组
const allGroups = computed(() => {
  const groups = [{ name: '全部', count: favoriteStore.favoriteList.length }]
  return groups.concat(favoriteStore.groupList)
})

// 过滤后的自选股
const filteredFavorites = computed(() => {
  if (currentGroup.value === '全部') {
    return favoriteStore.favoriteList
  }
  return favoriteStore.getFavorites(currentGroup.value)
})

// 当前选中的板块
const currentBoard = computed(() => {
  if (!selectedBoard.value) return null
  return favoriteStore.boards.get(selectedBoard.value)
})

// 当前板块的股票
const currentBoardStocks = computed(() => {
  if (!selectedBoard.value) return []
  return favoriteStore.getBoardStocks(selectedBoard.value)
})

// 获取板块内的股票
function getBoardStocks(boardId: string) {
  return favoriteStore.getBoardStocks(boardId)
}

// 格式化函数
function formatPrice(price?: number): string {
  if (price === undefined || price === null) return '-'
  return price.toFixed(2)
}

function formatChange(change?: number): string {
  if (change === undefined || change === null) return '-'
  const sign = change > 0 ? '+' : ''
  return `${sign}${change.toFixed(2)}%`
}

function getChangeClass(change?: number): string {
  if (!change) return ''
  return change > 0 ? 'up' : change < 0 ? 'down' : ''
}

// 自选股操作
function selectStock(code: string) {
  uiStore.selectStock(code)
  emit('close')
}

function removeFromFavorites(code: string) {
  favoriteStore.removeFromFavorites(code)
}

function refresh() {
  favoriteStore.syncWithMarketData()
}

function exportFavorites() {
  favoriteStore.exportFavorites()
}

function importFavorites() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = (e: Event) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = (event) => {
        const result = event.target?.result
        if (typeof result === 'string') {
          favoriteStore.importFavorites(result)
        }
      }
      reader.readAsText(file)
    }
  }
  input.click()
}

function syncWithMarketData() {
  const updated = favoriteStore.syncWithMarketData()
  EventManager.emit(AppEvents.UI.TOAST, {
    message: `已同步 ${updated} 只自选股`,
    duration: 1500,
    type: 'success',
  })
}

function clearAllFavorites() {
  if (confirm('确定要清空所有自选股吗？')) {
    const count = favoriteStore.clearAllFavorites()
    EventManager.emit(AppEvents.UI.TOAST, {
      message: `🗑️ 已清空 ${count} 只自选股`,
      duration: 1500,
      type: 'info',
    })
  }
}

// 板块操作
async function handleCreateBoard() {
  if (!newBoardName.value.trim()) return

  const board = favoriteStore.addBoard(newBoardName.value.trim())
  if (board) {
    newBoardName.value = ''
    showCreateBoard.value = false
  }
}

function createBoardFromFavorites() {
  if (!newBoardFromFav.value.trim()) return

  const board = favoriteStore.createBoardFromFavorites(newBoardFromFav.value.trim())
  if (board) {
    newBoardFromFav.value = ''
    showCreateFromFavorites.value = false
    selectedBoard.value = board.id
  }
}

function deleteBoard(board: Board) {
  if (confirm(`确定要删除板块 "${board.name}" 吗？`)) {
    favoriteStore.removeBoard(board.id)
    if (selectedBoard.value === board.id) {
      selectedBoard.value = null
    }
  }
}

function editBoard(board: Board) {
  const newName = prompt('请输入新的板块名称', board.name)
  if (newName && newName.trim() && newName !== board.name) {
    favoriteStore.updateBoard(board.id, { name: newName.trim() })
  }
}

function addStockToBoard() {
  if (!selectedBoard.value || !selectedStockCode.value) return

  favoriteStore.addStockToBoard(selectedStockCode.value, selectedBoard.value, stockNotes.value)
  selectedStockCode.value = ''
  stockNotes.value = ''
  showAddToBoard.value = false
}

function removeStockFromBoard(stockCode: string) {
  if (!selectedBoard.value) return
  favoriteStore.removeStockFromBoard(stockCode, selectedBoard.value)
}

function editStockNotes(item: { stock: FavoriteStock; notes: string }) {
  const newNotes = prompt('编辑备注', item.notes)
  if (newNotes !== null) {
    // 先移除再重新添加（简单处理）
    if (selectedBoard.value) {
      favoriteStore.removeStockFromBoard(item.stock.code, selectedBoard.value)
      favoriteStore.addStockToBoard(item.stock.code, selectedBoard.value, newNotes)
    }
  }
}

// 点击外部关闭
// 点击外部关闭
function handleClickOutside(e: MouseEvent) {
  if (!props.visible) return

  const target = e.target as Node

  // 如果点击的是面板内部，不关闭
  if (panelRef.value && panelRef.value.contains(target)) return

  // 获取所有可能的触发按钮
  const triggerBtns = document.querySelectorAll('[data-favorite-trigger], .btn-icon[title*="自选股"]')

  for (const btn of triggerBtns) {
    if (btn === target || btn.contains(target)) {
      return // 点击了触发按钮，不关闭
    }
  }

  // 延迟一点再关闭，避免刚打开就关闭
  setTimeout(() => {
    if (props.visible) {
      emit('close')
      emit('update:visible', false)
    }
  }, 10)
}

// 监听显示创建表单
watch(showCreateBoard, (val) => {
  if (val) {
    nextTick(() => {
      boardNameInput.value?.focus()
    })
  }
})

onMounted(() => {
  setTimeout(() => {
    document.addEventListener('click', handleClickOutside)
  }, 100)

  favoriteStore.init()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
/* 视图切换按钮激活状态 */
.btn-icon.active {
  background: var(--color-highlight);
  color: #000;
  border-color: var(--color-highlight);
}

.header-icon {
  margin-right: 4px;
}

/* 创建表单 */
.create-form {
  margin: 12px 16px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.create-form input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 13px;
  margin-bottom: 8px;
}

.create-form input:focus {
  outline: none;
  border-color: var(--color-highlight);
}

.form-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.form-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.btn-primary {
  padding: 6px 12px;
  background: var(--color-highlight);
  border: none;
  border-radius: 4px;
  color: #000;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 快速操作区域 */
.quick-actions {
  margin: 12px 16px;
}

/* 板块列表 */
.boards-list {
  padding: 8px 0;
}

.board-item {
  margin: 0 16px 12px 16px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border-left: 4px solid transparent;
  transition: all 0.2s;
}

.board-item:hover {
  transform: translateX(2px);
  box-shadow: var(--shadow-sm);
}

.board-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.board-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.board-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.board-count {
  font-size: 11px;
  padding: 2px 6px;
  background: var(--badge-bg);
  border-radius: 12px;
  color: var(--badge-text);
}

.board-actions {
  display: flex;
  gap: 4px;
}

.board-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  cursor: pointer;
}

.preview-stock {
  padding: 2px 8px;
  background: var(--bg-hover);
  border-radius: 12px;
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.preview-stock:hover {
  background: var(--color-highlight);
  color: #000;
}

.preview-more {
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

/* 板块详情 */
.board-detail {
  padding: 12px 16px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.detail-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

/* 添加股票表单 */
.add-stock-form {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.stock-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 13px;
  margin-bottom: 8px;
}

.stock-select:focus {
  outline: none;
  border-color: var(--color-highlight);
}

/* 板块内股票列表 */
.board-stocks {
  max-height: 300px;
  overflow-y: auto;
}

.stock-item {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-light);
}

.stock-item:hover {
  background: var(--bg-hover);
}

.stock-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  min-width: 0;
}

.stock-notes-badge {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--badge-bg);
  border-radius: 12px;
  color: var(--badge-text);
  white-space: nowrap;
}

.stock-price {
  text-align: right;
  margin-right: 12px;
  min-width: 70px;
}

.stock-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s;
}

.stock-item:hover .stock-actions {
  opacity: 1;
}

/* 响应式调整 */
@media (max-width: 768px) {
  .favorite-panel {
    width: 320px;
  }
}

@media (max-width: 480px) {
  .favorite-panel {
    width: calc(100% - 20px);
  }
}

.favorite-panel {
  position: fixed;
  width: 380px;
  max-height: 500px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  z-index: 10050;
  font-size: 13px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: slideIn 0.2s ease;
  top: 60px;
  right: 20px;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
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
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
  transform: translateY(-1px);
}

.btn-icon-small {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  border-radius: 12px;
  cursor: pointer;
  opacity: 0.5;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.btn-icon-small:hover {
  opacity: 1;
  background: var(--bg-hover);
  color: var(--color-error);
}

.icon {
  font-size: 16px;
  line-height: 1;
}

.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
  overflow-x: auto;
  scrollbar-width: thin;
}

.panel-tabs::-webkit-scrollbar {
  height: 4px;
}

.panel-tabs::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 2px;
}

.tab-btn {
  flex: 1;
  min-width: 60px;
  padding: 6px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  white-space: nowrap;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
}

.tab-count {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--badge-bg);
  border-radius: 12px;
  color: var(--badge-text);
}

.tab-btn.active .tab-count {
  background: rgba(0, 0, 0, 0.2);
  color: #000;
}

.panel-content {
  flex: 1;
  max-height: 350px;
  overflow-y: auto;
  background: var(--bg-primary);
}

.panel-content::-webkit-scrollbar {
  width: 8px;
}

.panel-content::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
}

.panel-content::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 4px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

.favorites-list {
  padding: 8px 0;
}

.favorite-item {
  display: flex;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: all 0.2s;
}

.favorite-item:hover {
  background: var(--bg-hover);
}

.favorite-item:hover .favorite-actions {
  opacity: 1;
}

.favorite-info {
  flex: 1;
  min-width: 0;
}

.stock-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.stock-code {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  color: var(--color-highlight);
  font-size: 12px;
  font-weight: 500;
}

.stock-name {
  font-weight: 500;
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-notes {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-left: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.favorite-price {
  text-align: right;
  margin-right: 16px;
  min-width: 80px;
}

.price {
  display: block;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}

.change {
  display: block;
  font-size: 11px;
  font-weight: 500;
}

.change.up {
  color: var(--color-up);
}

.change.down {
  color: var(--color-down);
}

.favorite-actions {
  opacity: 0;
  transition: opacity 0.2s;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
}

.btn-text {
  background: transparent;
  border: none;
  color: var(--color-highlight);
  cursor: pointer;
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.btn-text:hover {
  background: var(--bg-hover);
  transform: translateY(-1px);
}

.empty-state {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-tertiary);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state small {
  display: block;
  margin-top: 8px;
  font-size: 11px;
  opacity: 0.7;
}

/* 响应式 */
@media (max-width: 768px) {
  .favorite-panel {
    width: 320px;
    right: 10px;
  }
}

@media (max-width: 480px) {
  .favorite-panel {
    width: calc(100% - 20px);
    right: 10px;
    left: 10px;
  }
}
</style>
