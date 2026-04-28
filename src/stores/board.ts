import { debugLog } from '@/utils/logger'
// src/stores/board.ts

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { Board, BoardGroup, StockBoard, BoardStats } from '@/types/board'
import { useFavoriteStore } from './favorite'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

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

// 预设板块分组
const DEFAULT_GROUPS = [
  {
    id: 'hot-boards',
    name: '🔥 热门板块',
    boards: [] as string[],
    createTime: Date.now(),
  },
  {
    id: 'my-boards',
    name: '⭐ 我的板块',
    boards: [] as string[],
    createTime: Date.now(),
  },
]

export const useBoardStore = defineStore('board', () => {
  // ========== State ==========
  const boards = ref<Map<string, Board>>(new Map())
  const groups = ref<Map<string, BoardGroup>>(new Map())
  const stockBoards = ref<Map<string, StockBoard[]>>(new Map()) // stockCode -> boardIds
  const initialized = ref(false)

  // ========== Getters ==========
  const boardList = computed(() => 
    Array.from(boards.value.values()).sort((a, b) => b.count - a.count)
  )

  const groupList = computed(() => 
    Array.from(groups.value.values())
  )

  const stats = computed((): BoardStats => {
    const totalBoards = boards.value.size
    const totalGroups = groups.value.size
    
    // 计算热门板块趋势
    const topBoards = boardList.value.slice(0, 5).map(board => ({
      name: board.name,
      count: board.count,
      trend: getBoardTrend(board.id) as 'up' | 'down' | 'stable',
    }))

    return {
      totalBoards,
      totalGroups,
      topBoards,
    }
  })

  // ========== 初始化 ==========
  function init() {
    if (initialized.value) return

    debugLog('[BoardStore] 📊 初始化板块...')

    // 加载数据
    loadFromStorage()

    // 如果没有分组，创建默认分组
    if (groups.value.size === 0) {
      DEFAULT_GROUPS.forEach(group => {
        groups.value.set(group.id, group)
      })
    }

    initialized.value = true
    debugLog('[BoardStore] ✅ 初始化完成', {
      boards: boards.value.size,
      groups: groups.value.size,
      stockBoards: stockBoards.value.size,
    })
  }

  // ========== 存储 ==========
  function loadFromStorage() {
    try {
      const savedBoards = localStorage.getItem('stock_boards')
      if (savedBoards) {
        const data = JSON.parse(savedBoards)
        boards.value = new Map(data.boards || [])
        groups.value = new Map(data.groups || [])
        stockBoards.value = new Map(data.stockBoards || [])
      }
    } catch (e) {
      console.warn('[BoardStore] 加载失败:', e)
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem('stock_boards', JSON.stringify({
        boards: Array.from(boards.value.entries()),
        groups: Array.from(groups.value.entries()),
        stockBoards: Array.from(stockBoards.value.entries()),
      }))
    } catch (e) {
      console.warn('[BoardStore] 保存失败:', e)
    }
  }

  // ========== 板块操作 ==========
  function addBoard(name: string, color?: string): Board | null {
    if (!name) return null
    
    // 检查是否已存在
    const existing = Array.from(boards.value.values()).find(b => b.name === name)
    if (existing) return existing

    const id = `board_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    const board: Board = {
      id,
      name,
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

  function removeBoard(boardId: string): boolean {
    const board = boards.value.get(boardId)
    if (!board) return false

    // 删除板块关联
    stockBoards.value.forEach((boards, stockCode) => {
      const filtered = boards.filter(b => b.boardId !== boardId)
      if (filtered.length === 0) {
        stockBoards.value.delete(stockCode)
      } else {
        stockBoards.value.set(stockCode, filtered)
      }
    })

    // 从分组中移除
    groups.value.forEach(group => {
      group.boards = group.boards.filter(id => id !== boardId)
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

  // ========== 股票板块关联 ==========
  function addStockToBoard(stockCode: string, stockName: string, boardId: string, notes: string = '') {
    const board = boards.value.get(boardId)
    if (!board) return false

    // 获取股票的板块关联
    const stockBoardList = stockBoards.value.get(stockCode) || []

    // 检查是否已经在同一个板块
    if (stockBoardList.some(sb => sb.boardId === boardId)) {
      EventManager.emit(AppEvents.UI.TOAST, {
        message: `⚠️ 已在板块 ${board.name} 中`,
        duration: 1500,
        type: 'warning',
      })
      return false
    }

    // 添加关联
    stockBoardList.push({
      stockCode,
      boardId,
      addTime: Date.now(),
      notes,
    })

    stockBoards.value.set(stockCode, stockBoardList)

    // 更新板块计数
    board.count = getBoardStockCount(boardId)
    board.updateTime = Date.now()

    saveToStorage()

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `📊 已将 ${stockName} 加入板块 ${board.name}${notes ? ` (${notes})` : ''}`,
      duration: 1500,
      type: 'success',
    })

    return true
  }

  function removeStockFromBoard(stockCode: string, boardId: string): boolean {
    const stockBoardList = stockBoards.value.get(stockCode)
    if (!stockBoardList) return false

    const filtered = stockBoardList.filter(sb => sb.boardId !== boardId)
    
    if (filtered.length === 0) {
      stockBoards.value.delete(stockCode)
    } else {
      stockBoards.value.set(stockCode, filtered)
    }

    // 更新板块计数
    const board = boards.value.get(boardId)
    if (board) {
      board.count = getBoardStockCount(boardId)
      board.updateTime = Date.now()
    }

    saveToStorage()
    return true
  }

  function getStockBoards(stockCode: string): Array<{ board: Board; notes: string }> {
    const stockBoardList = stockBoards.value.get(stockCode) || []
    return stockBoardList
      .map(sb => {
        const board = boards.value.get(sb.boardId)
        return board ? { board, notes: sb.notes || '' } : null
      })
      .filter((b): b is { board: Board; notes: string } => b !== null)
  }

  function getBoardStockCount(boardId: string): number {
    let count = 0
    stockBoards.value.forEach(boards => {
      if (boards.some(b => b.boardId === boardId)) {
        count++
      }
    })
    return count
  }

  // ========== 从自选股创建板块 ==========
  function createBoardFromFavorites(boardName: string, groupId: string = 'my-boards'): Board | null {
    const favoriteStore = useFavoriteStore()
    
    if (favoriteStore.favoriteList.length === 0) {
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
    favoriteStore.favoriteList.forEach(fav => {
      addStockToBoard(fav.code, fav.name, board.id)
    })

    // 添加到分组
    const group = groups.value.get(groupId)
    if (group && !group.boards.includes(board.id)) {
      group.boards.push(board.id)
      saveToStorage()
    }

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `📊 已创建板块 ${boardName}，包含 ${favoriteStore.favoriteList.length} 只股票`,
      duration: 2000,
      type: 'success',
    })

    return board
  }

  // ========== 分组操作 ==========
  function addBoardToGroup(boardId: string, groupId: string): boolean {
    const group = groups.value.get(groupId)
    if (!group) return false

    if (!group.boards.includes(boardId)) {
      group.boards.push(boardId)
      saveToStorage()
      return true
    }

    return false
  }

  function removeBoardFromGroup(boardId: string, groupId: string): boolean {
    const group = groups.value.get(groupId)
    if (!group) return false

    group.boards = group.boards.filter(id => id !== boardId)
    saveToStorage()
    return true
  }

  // ========== 趋势分析 ==========
  function getBoardTrend(boardId: string): string {
    // 这里可以根据实际数据计算趋势
    // 示例：根据最近新增股票数量判断
    const board = boards.value.get(boardId)
    if (!board) return 'stable'

    // TODO: 实现趋势计算逻辑
    return Math.random() > 0.5 ? 'up' : 'down'
  }

  // ========== 搜索 ==========
  function searchBoards(keyword: string): Board[] {
    if (!keyword) return boardList.value

    const upperKeyword = keyword.toUpperCase()
    return boardList.value.filter(board => 
      board.name.toUpperCase().includes(upperKeyword)
    )
  }

  // ========== 导出/导入 ==========
  function exportBoards(): void {
    const data = {
      version: '1.0.0',
      exportTime: Date.now(),
      boards: Array.from(boards.value.entries()),
      groups: Array.from(groups.value.entries()),
      stockBoards: Array.from(stockBoards.value.entries()),
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `boards_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)

    EventManager.emit(AppEvents.UI.TOAST, {
      message: '📤 板块数据已导出',
      duration: 1500,
      type: 'success',
    })
  }

  function importBoards(jsonStr: string): boolean {
    try {
      const data = JSON.parse(jsonStr)

      if (data.version !== '1.0.0') {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '⚠️ 版本不兼容',
          duration: 1500,
          type: 'warning',
        })
        return false
      }

      boards.value = new Map(data.boards || [])
      groups.value = new Map(data.groups || [])
      stockBoards.value = new Map(data.stockBoards || [])

      saveToStorage()

      EventManager.emit(AppEvents.UI.TOAST, {
        message: '✅ 板块导入成功',
        duration: 1500,
        type: 'success',
      })

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

  return {
    // State
    boards,
    groups,
    stockBoards,
    initialized,

    // Getters
    boardList,
    groupList,
    stats,

    // 板块操作
    init,
    addBoard,
    removeBoard,

    // 股票板块关联
    addStockToBoard,
    removeStockFromBoard,
    getStockBoards,
    getBoardStockCount,

    // 从自选股创建
    createBoardFromFavorites,

    // 分组操作
    addBoardToGroup,
    removeBoardFromGroup,

    // 搜索
    searchBoards,

    // 趋势
    getBoardTrend,

    // 导出/导入
    exportBoards,
    importBoards,
  }
})