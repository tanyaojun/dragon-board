import { debugLog } from '@/utils/logger'
// src/stores/favorite.ts

import { defineStore } from 'pinia'
import { ref, computed, onScopeDispose } from 'vue'
import type { FavoriteStock, FavoriteGroup, FavoriteStats, Board, StockBoard } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { stockCodeManager } from '@/services/StockCodeManager'
import { dataLayer } from '@/services/DataLayer'

// 默认分组颜色
const GROUP_COLORS = [
  '#FF6B6B',
  '#4ECDC4',
  '#45B7D1',
  '#96CEB4',
  '#FFEEAD',
  '#D4A5A5',
  '#9B59B6',
  '#3498DB',
  '#E67E22',
  '#2ECC71',
]

// 预设板块颜色
const BOARD_COLORS = [
  '#FF6B6B', // 红色 - 电力
  '#4ECDC4', // 青色 - AI硬件
  '#45B7D1', // 蓝色 - 华为鸿蒙
  '#96CEB4', // 绿色 - 石油油气
  '#FFEEAD', // 黄色 - BC电池
  '#D4A5A5', // 粉色 - 华为液冷快充
  '#9B59B6', // 紫色
  '#3498DB', // 深蓝
  '#E67E22', // 橙色
  '#2ECC71', // 翠绿
]

export const useFavoriteStore = defineStore('favorite', () => {
  // ========== 原有 State ==========
  const favorites = ref<Map<string, FavoriteStock>>(new Map())
  const groups = ref<Map<string, FavoriteGroup>>(new Map())
  const currentGroup = ref('默认')
  const initialized = ref(false)

  // ========== 新增板块 State ==========
  const boards = ref<Map<string, Board>>(new Map()) // 板块列表
  const stockBoards = ref<Map<string, StockBoard[]>>(new Map()) // 股票板块关联
  const currentBoardView = ref<'groups' | 'boards'>('boards') // 当前视图：分组/板块

  // ========== 原有 Getters ==========
  const favoriteList = computed(() =>
    Array.from(favorites.value.values()).sort((a, b) => b.addTime - a.addTime),
  )

  const groupList = computed(() => Array.from(groups.value.values()))

  const stats = computed(
    (): FavoriteStats => ({
      total: favorites.value.size,
      groups: groups.value.size,
      byGroup: groupList.value.map((g) => ({
        name: g.name,
        count: g.count,
        color: g.color,
      })),
    }),
  )

  // ========== 新增板块 Getters ==========
  const boardList = computed(() =>
    Array.from(boards.value.values()).sort((a, b) => b.count - a.count),
  )

  const boardStats = computed(() => ({
    totalBoards: boards.value.size,
    totalStocks: stockBoards.value.size,
    topBoards: boardList.value.slice(0, 5).map((board) => ({
      name: board.name,
      count: board.count,
      color: board.color,
    })),
  }))

  // ========== 初始化（修改） ==========
  function init() {
    if (initialized.value) return

    debugLog('[FavoriteStore] ⭐ 初始化自选股...')

    // 加载数据
    loadFromStorage()

    // 如果没有分组，创建默认分组
    if (groups.value.size === 0) {
      addGroup('默认', GROUP_COLORS[0])
    }

    initialized.value = true

    debugLog('[FavoriteStore] ✅ 初始化完成')
    debugLog(`   ├─ 自选股: ${favorites.value.size}只`)
    debugLog(`   ├─ 板块: ${boards.value.size}个`)
    debugLog(`   └─ 分组: ${groups.value.size}个`)
  }

  function ensureInitialized(): void {
    if (!initialized.value) {
      init()
    }
  }

  function normalizeFavoriteCode(code: unknown): string {
    const digits = String(code || '').replace(/\D/g, '')
    if (!digits) return ''
    const normalized = digits.padStart(6, '0')
    return /^\d{6}$/.test(normalized) && normalized !== '000000' ? normalized : ''
  }

  function getValidStockName(name: unknown): string {
    const value = String(name || '').trim()
    return value && value !== '-' && value !== '未知' ? value : ''
  }

  function cleanupStockBoardLinks(stockCode: string): void {
    const boardLinks = stockBoards.value.get(stockCode)
    if (!boardLinks) return

    stockBoards.value.delete(stockCode)
    boardLinks.forEach((link) => {
      const board = boards.value.get(link.boardId)
      if (board) {
        board.count = getBoardStockCount(link.boardId)
        board.updateTime = Date.now()
      }
    })
  }

  // ========== 存储（修改） ==========
  function loadFromStorage() {
    try {
      const savedData = localStorage.getItem('favorite_data')
      if (savedData) {
        const data = JSON.parse(savedData)
        favorites.value = new Map(data.favorites || [])
        groups.value = new Map(data.groups || [])
        boards.value = new Map(data.boards || [])
        stockBoards.value = new Map(data.stockBoards || [])
      } else {
        // 兼容旧版本
        const savedFav = localStorage.getItem('favorite_stocks')
        if (savedFav) {
          favorites.value = new Map(JSON.parse(savedFav))
        }
        const savedGroups = localStorage.getItem('favorite_groups')
        if (savedGroups) {
          groups.value = new Map(JSON.parse(savedGroups))
        }
      }
    } catch (e) {
      console.warn('[FavoriteStore] 加载失败:', e)
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem(
        'favorite_data',
        JSON.stringify({
          favorites: Array.from(favorites.value.entries()),
          groups: Array.from(groups.value.entries()),
          boards: Array.from(boards.value.entries()),
          stockBoards: Array.from(stockBoards.value.entries()),
        }),
      )
    } catch (e) {
      console.warn('[FavoriteStore] 保存失败:', e)
    }
  }

  // ========== 原有自选股操作（保持不变）==========
  function addToFavorites(code: string, group = '默认', notes = ''): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(code)
    if (!normalizedCode) return false

    const dataLayerStock = dataLayer.getStock(normalizedCode)
    const stockInfo = stockCodeManager.getStockInfo(normalizedCode)
    const stockName = getValidStockName(stockInfo?.name) || getValidStockName(dataLayerStock?.name)

    if (!stockInfo && !dataLayerStock) {
      console.warn(`[FavoriteStore] 未找到股票代码: ${normalizedCode}`)
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `❌ 无效的股票代码: ${normalizedCode}`,
        duration: 1500,
        type: 'error',
      })
      return false
    }

    // 2. 检查是否已在自选股中
    if (favorites.value.has(normalizedCode)) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `⚠️ ${stockName || normalizedCode} 已在自选股中`,
        duration: 1500,
        type: 'warning',
      })
      return false
    }

    // 4. 添加到自选
    favorites.value.set(normalizedCode, {
      code: normalizedCode,
      name: stockName || normalizedCode,
      group,
      notes,
      addTime: Date.now(),
      lastPrice: dataLayerStock?.price || 0,
      lastChange: dataLayerStock?.change || 0,
      lastUpdate: Date.now(),
    })

    // 5. 更新分组计数
    updateGroupCount(group, 1)
    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `⭐ 已加入自选: ${stockName || normalizedCode}`,
      duration: 1500,
      type: 'success',
    })

    EventManager.emit('favorite-added', { code: normalizedCode, group })

    return true
  }

  function removeFromFavorites(code: string): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(code)
    if (!favorites.value.has(normalizedCode)) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '❌ 该股票不在自选中',
        duration: 1500,
        type: 'error',
      })
      return false
    }

    const fav = favorites.value.get(normalizedCode)!
    const stockName = fav.name

    updateGroupCount(fav.group, -1)
    favorites.value.delete(normalizedCode)
    cleanupStockBoardLinks(normalizedCode)

    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `➖ 已从自选中移除: ${stockName}`,
      duration: 1500,
      type: 'info',
    })

    EventManager.emit('favorite-removed', { code: normalizedCode })

    return true
  }

  function toggleFavorite(code: string, group = '默认'): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(code)
    if (favorites.value.has(normalizedCode)) {
      return removeFromFavorites(normalizedCode)
    } else {
      return addToFavorites(normalizedCode, group)
    }
  }

  function isFavorite(code: string): boolean {
    ensureInitialized()
    return favorites.value.has(normalizeFavoriteCode(code))
  }

  function getFavorites(group: string | null = null): FavoriteStock[] {
    ensureInitialized()

    let favs = favoriteList.value
    if (group) {
      favs = favs.filter((f) => f.group === group)
    }
    return favs
  }

  function updateFavorite(code: string, updates: Partial<FavoriteStock>): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(code)
    if (!favorites.value.has(normalizedCode)) return false

    const fav = favorites.value.get(normalizedCode)!
    const oldGroup = fav.group

    Object.assign(fav, updates, { lastUpdate: Date.now() })

    if (updates.group && updates.group !== oldGroup) {
      updateGroupCount(oldGroup, -1)
      updateGroupCount(updates.group, 1)
    }

    saveToStorage()
    EventManager.emit('favorite-updated', { code: normalizedCode })

    return true
  }

  // ========== 原有分组操作（保持不变）==========
  function addGroup(name: string, color: string | null = null): boolean {
    if (groups.value.has(name)) return false

    const groupColor = color || GROUP_COLORS[groups.value.size % GROUP_COLORS.length]

    groups.value.set(name, {
      name,
      color: groupColor,
      count: 0,
      createTime: Date.now(),
    })

    saveToStorage()
    EventManager.emit('group-added', { name })

    return true
  }

  function removeGroup(name: string): boolean {
    if (name === '默认') {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '⚠️ 不能删除默认分组',
        duration: 1500,
        type: 'warning',
      })
      return false
    }

    if (!groups.value.has(name)) return false

    favorites.value.forEach((fav) => {
      if (fav.group === name) {
        fav.group = '默认'
        updateGroupCount('默认', 1)
      }
    })

    groups.value.delete(name)
    saveToStorage()
    EventManager.emit('group-removed', { name })

    return true
  }

  function updateGroupCount(group: string, delta: number): void {
    if (groups.value.has(group)) {
      const g = groups.value.get(group)!
      g.count = Math.max(0, (g.count || 0) + delta)
    }
  }

  function clearAllFavorites(): number {
    ensureInitialized()

    const count = favorites.value.size
    favorites.value.clear()
    stockBoards.value.clear()

    groups.value.forEach((group) => {
      group.count = 0
    })
    boards.value.forEach((board) => {
      board.count = 0
      board.updateTime = Date.now()
    })

    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `🗑️ 已清空 ${count} 只自选股`,
      duration: 1500,
      type: 'info',
    })

    EventManager.emit('favorites-cleared')

    return count
  }

  // ========== 新增板块操作 ==========

  /**
   * 添加板块
   */
  function addBoard(name: string, color?: string): Board | null {
    ensureInitialized()

    if (!name.trim()) return null

    // 检查是否已存在同名板块
    const existing = Array.from(boards.value.values()).find((b) => b.name === name)
    if (existing) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `⚠️ 板块 "${name}" 已存在`,
        duration: 1500,
        type: 'warning',
      })
      return existing
    }

    const id = `board_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    const board: Board = {
      id,
      name: name.trim(),
      color: color || BOARD_COLORS[boards.value.size % BOARD_COLORS.length],
      count: 0,
      createTime: Date.now(),
      updateTime: Date.now(),
    }

    boards.value.set(id, board)
    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `✅ 已添加板块: ${name}`,
      duration: 1500,
      type: 'success',
    })

    return board
  }

  /**
   * 删除板块
   */
  function removeBoard(boardId: string): boolean {
    ensureInitialized()

    const board = boards.value.get(boardId)
    if (!board) return false

    // 删除所有股票的板块关联
    stockBoards.value.forEach((boards, stockCode) => {
      const filtered = boards.filter((b) => b.boardId !== boardId)
      if (filtered.length === 0) {
        stockBoards.value.delete(stockCode)
      } else {
        stockBoards.value.set(stockCode, filtered)
      }
    })

    boards.value.delete(boardId)
    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `🗑️ 已删除板块: ${board.name}`,
      duration: 1500,
      type: 'info',
    })

    return true
  }

  /**
   * 更新板块信息
   */
  function updateBoard(boardId: string, updates: Partial<Board>): boolean {
    ensureInitialized()

    const board = boards.value.get(boardId)
    if (!board) return false

    Object.assign(board, updates)
    saveToStorage()

    EventManager.emit('board-updated', { boardId })
    return true
  }

  /**
   * 将股票加入板块
   */
  function addStockToBoard(stockCode: string, boardId: string, notes: string = ''): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(stockCode)
    const board = boards.value.get(boardId)
    if (!board) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '❌ 板块不存在',
        duration: 1500,
        type: 'error',
      })
      return false
    }

    let stock = favorites.value.get(normalizedCode)
    if (!stock) {
      if (!addToFavorites(normalizedCode)) {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '❌ 股票不在自选股中',
          duration: 1500,
          type: 'error',
        })
        return false
      }
      stock = favorites.value.get(normalizedCode)
      if (!stock) return false
    }

    // 获取股票的板块关联
    const stockBoardList = stockBoards.value.get(normalizedCode) || []

    // 检查是否已在同一板块
    if (stockBoardList.some((sb) => sb.boardId === boardId)) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `⚠️ ${stock.name} 已在板块 ${board.name} 中`,
        duration: 1500,
        type: 'warning',
      })
      return false
    }

    // 添加关联
    stockBoardList.push({
      stockCode: normalizedCode,
      boardId,
      addTime: Date.now(),
      notes: notes.trim(),
    })

    stockBoards.value.set(normalizedCode, stockBoardList)

    // 更新板块计数
    board.count = getBoardStockCount(boardId)

    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `📊 已将 ${stock.name} 加入板块 ${board.name}${notes ? ` (${notes})` : ''}`,
      duration: 1500,
      type: 'success',
    })

    return true
  }

  /**
   * 从板块中移除股票
   */
  function removeStockFromBoard(stockCode: string, boardId: string): boolean {
    ensureInitialized()

    const normalizedCode = normalizeFavoriteCode(stockCode)
    const stockBoardList = stockBoards.value.get(normalizedCode)
    if (!stockBoardList) return false

    const filtered = stockBoardList.filter((sb) => sb.boardId !== boardId)

    if (filtered.length === 0) {
      stockBoards.value.delete(normalizedCode)
    } else {
      stockBoards.value.set(normalizedCode, filtered)
    }

    // 更新板块计数
    const board = boards.value.get(boardId)
    if (board) {
      board.count = getBoardStockCount(boardId)
    }

    saveToStorage()
    return true
  }

  /**
   * 获取股票所属的板块
   */
  function getStockBoards(stockCode: string): Array<{ board: Board; notes: string }> {
    ensureInitialized()

    const stockBoardList = stockBoards.value.get(normalizeFavoriteCode(stockCode)) || []
    return stockBoardList
      .map((sb) => {
        const board = boards.value.get(sb.boardId)
        return board ? { board, notes: sb.notes || '' } : null
      })
      .filter((b): b is { board: Board; notes: string } => b !== null)
  }

  /**
   * 获取板块内的股票
   */
  function getBoardStocks(boardId: string): Array<{ stock: FavoriteStock; notes: string }> {
    ensureInitialized()

    const stocks: Array<{ stock: FavoriteStock; notes: string }> = []

    stockBoards.value.forEach((boards, stockCode) => {
      const boardInfo = boards.find((b) => b.boardId === boardId)
      if (boardInfo) {
        const stock = favorites.value.get(stockCode)
        if (stock) {
          stocks.push({
            stock,
            notes: boardInfo.notes || '',
          })
        }
      }
    })

    return stocks.sort((a, b) => b.stock.addTime - a.stock.addTime)
  }

  /**
   * 获取板块内的股票数量
   */
  function getBoardStockCount(boardId: string): number {
    let count = 0
    stockBoards.value.forEach((boards) => {
      if (boards.some((b) => b.boardId === boardId)) {
        count++
      }
    })
    return count
  }

  /**
   * 从自选股创建板块
   */
  function createBoardFromFavorites(boardName: string): Board | null {
    ensureInitialized()

    if (favoriteList.value.length === 0) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '⚠️ 自选股列表为空',
        duration: 1500,
        type: 'warning',
      })
      return null
    }

    // 创建板块
    const board = addBoard(boardName)
    if (!board) return null

    // 将所有自选股加入板块
    favoriteList.value.forEach((fav) => {
      addStockToBoard(fav.code, board.id)
    })

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `📊 已创建板块 ${boardName}，包含 ${favoriteList.value.length} 只股票`,
      duration: 2000,
      type: 'success',
    })

    return board
  }

  /**
   * 快速将股票加入板块（智能推荐板块）
   */
  function quickAddToBoard(stockCode: string, boardName: string, notes: string = ''): boolean {
    ensureInitialized()

    // 查找或创建板块
    let board = Array.from(boards.value.values()).find((b) => b.name === boardName)

    if (!board) {
      const createdBoard = addBoard(boardName)
      if (!createdBoard) return false
      board = createdBoard
    }

    return addStockToBoard(stockCode, board.id, notes)
  }

  /**
   * 搜索板块
   */
  function searchBoards(keyword: string): Board[] {
    ensureInitialized()

    if (!keyword) return boardList.value

    const upperKeyword = keyword.toUpperCase()
    return boardList.value.filter((board) => board.name.toUpperCase().includes(upperKeyword))
  }

  /**
   * 获取板块统计数据
   */
  function getBoardStatistics() {
    ensureInitialized()

    const stats = {
      totalBoards: boards.value.size,
      totalStockBoards: stockBoards.value.size,
      topBoards: boardList.value.slice(0, 10).map((board) => ({
        ...board,
        stocks: getBoardStocks(board.id).length,
      })),
      boardDistribution: boardList.value.map((board) => ({
        name: board.name,
        count: board.count,
        color: board.color,
      })),
    }

    return stats
  }

  // ========== 数据同步（修改） ==========
  function syncWithMarketData(): number {
    ensureInitialized()

    const stocks = dataLayer.getStocks()

    if (!stocks || stocks.length === 0) return 0

    let updated = 0
    const stockByCode = new Map(stocks.map((stock) => [normalizeFavoriteCode(stock.code), stock]))

    favorites.value.forEach((fav, code) => {
      const stock = stockByCode.get(code)
      if (stock) {
        const price = Number(stock.price)
        const change = Number(stock.change)
        if (Number.isFinite(price)) fav.lastPrice = price
        if (Number.isFinite(change)) fav.lastChange = change
        fav.lastUpdate = Date.now()
        updated++
      }
    })

    if (updated > 0) {
      saveToStorage()
      EventManager.emit('favorites-synced', { updated })
    }

    return updated
  }

  // ========== 导出/导入（修改） ==========
  function exportFavorites(): void {
    ensureInitialized()

    const data = {
      version: '2.0.0', // 升级版本号
      exportTime: Date.now(),
      groups: Array.from(groups.value.entries()),
      favorites: Array.from(favorites.value.entries()),
      boards: Array.from(boards.value.entries()),
      stockBoards: Array.from(stockBoards.value.entries()),
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)

    const a = document.createElement('a')
    a.href = url
    a.download = `favorites_${new Date().toISOString().slice(0, 10)}.json`
    a.click()

    URL.revokeObjectURL(url)

    EventManager.emit(AppEvents.UI.TOAST, {
      message: '📤 自选股已导出',
      duration: 1500,
      type: 'success',
    })
  }

  function importFavorites(jsonStr: string): boolean {
    ensureInitialized()

    try {
      const data = JSON.parse(jsonStr)

      // 兼容旧版本
      if (data.version === '1.0.0') {
        favorites.value = new Map(data.favorites || [])
        groups.value = new Map(data.groups || [])
        boards.value = new Map()
        stockBoards.value = new Map()
      } else if (data.version === '2.0.0') {
        favorites.value = new Map(data.favorites || [])
        groups.value = new Map(data.groups || [])
        boards.value = new Map(data.boards || [])
        stockBoards.value = new Map(data.stockBoards || [])
      } else {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '⚠️ 版本不兼容',
          duration: 1500,
          type: 'warning',
        })
        return false
      }

      saveToStorage()

      EventManager.emit(AppEvents.UI.TOAST, {
        message: '✅ 导入成功',
        duration: 1500,
        type: 'success',
      })

      EventManager.emit('favorites-imported')

      return true
    } catch (e) {
      console.error('导入失败:', e)
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '❌ 导入失败',
        duration: 1500,
        type: 'error',
      })
      return false
    }
  }

  // ========== 搜索（保持不变） ==========
  function searchInFavorites(keyword: string): FavoriteStock[] {
    ensureInitialized()

    if (!keyword) return favoriteList.value

    const upperKeyword = keyword.toUpperCase()

    return favoriteList.value.filter(
      (fav) =>
        fav.code.includes(upperKeyword) ||
        fav.name.toUpperCase().includes(upperKeyword) ||
        fav.notes?.toUpperCase().includes(upperKeyword),
    )
  }

  const unsubscribeMergedStocks = dataLayer.subscribe('merged.stocks', () => {
    syncWithMarketData()
  })
  onScopeDispose(unsubscribeMergedStocks)

  return {
    // State
    favorites,
    groups,
    boards, // 新增：板块列表
    stockBoards, // 新增：股票板块关联
    currentGroup,
    currentBoardView, // 新增：当前视图
    initialized,

    // Getters
    favoriteList,
    groupList,
    stats,
    boardList, // 新增：板块列表
    boardStats, // 新增：板块统计

    // 自选股操作
    init,
    addToFavorites,
    removeFromFavorites,
    toggleFavorite,
    isFavorite,
    getFavorites,
    updateFavorite,
    searchInFavorites,
    clearAllFavorites, // 新增：清空所有自选

    // 分组操作
    addGroup,
    removeGroup,

    // 新增板块操作
    addBoard,
    removeBoard,
    updateBoard,
    addStockToBoard,
    removeStockFromBoard,
    getStockBoards,
    getBoardStocks,
    getBoardStockCount,
    createBoardFromFavorites,
    quickAddToBoard,
    searchBoards,
    getBoardStatistics,

    // 数据同步
    syncWithMarketData,

    // 导出/导入
    exportFavorites,
    importFavorites,
  }
})
