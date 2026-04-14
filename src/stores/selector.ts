// src/stores/selector.ts

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useStockStore } from './stock'
import { SearchIndex } from '../services/SearchIndex'
import { useUIStore } from './ui'
import { dataLayer } from '../services/DataLayer'
import type { SearchResult } from '../services/SearchIndex'

export const useSelectorStore = defineStore('selector', () => {
  // ========== State ==========
  const selectedCode = ref<string | null>(null)
  const selectedRow = ref<HTMLElement | null>(null)
  const lastSelectedTime = ref<number | null>(null)
  const initialized = ref(false)
  const searchKeyword = ref('')
  const searchResults = ref<SearchResult[]>([])
  const isSearching = ref(false)
  const hintActiveIndex = ref(-1)
  const showHint = ref(false)

  // ========== Getters ==========
  const selectedStock = computed(() => {
    if (!selectedCode.value) return null
    return dataLayer.getStock(selectedCode.value)
  })

  // ========== 初始化 ==========
  function init() {
    if (initialized.value) return

    const stockStore = useStockStore()

    if (stockStore.stocks.length > 0) {
      SearchIndex.build(stockStore.stocks)
    }

    restoreFromUrl()
    initialized.value = true
  }

  // ========== 选择股票 ==========
  function selectStock(code: string, options?: { source?: string; scroll?: boolean }) {
    if (!code) return

    // 更新选中的代码
    selectedCode.value = code
    lastSelectedTime.value = Date.now()
    updateUrl(code)

    // ✅ 同时更新 uiStore 中的选中状态
    const uiStore = useUIStore()
    uiStore.selectStock(code)

    // 高亮对应的行
    setTimeout(() => {
      highlightSelectedRow()
      if (options?.scroll !== false) {
        scrollToSelected()
      }
    }, 50)
  }

  // 高亮选中的行
  function highlightSelectedRow() {
    if (!selectedCode.value) return

    // 直接查找 data-code 属性匹配的行
    const targetRow = document.querySelector(`tr[data-code="${selectedCode.value}"]`) as HTMLElement

    if (!targetRow) {
      // 没找到就重试一次
      setTimeout(() => highlightSelectedRow(), 100)
      return
    }

    // 移除其他高亮
    document.querySelectorAll('tr.selected').forEach((row) => {
      row.classList.remove('selected')
    })

    // 高亮当前行
    targetRow.classList.add('selected')
    selectedRow.value = targetRow
  }

  function findRowByCode(code: string): HTMLElement | null {
    return document.querySelector(`tr[data-code="${code}"]`)
  }

  // ========== 清除选中 ==========
  function clearSelection() {
    if (selectedRow.value) {
      selectedRow.value.classList.remove('selected')
    }

    document.querySelectorAll('tr.selected').forEach((row) => {
      row.classList.remove('selected')
    })

    selectedCode.value = null
    selectedRow.value = null
    updateUrl(null)
  }

  // ========== 更新URL ==========
  function updateUrl(code: string | null) {
    const url = new URL(window.location.href)
    if (code) {
      url.searchParams.set('code', code)
    } else {
      url.searchParams.delete('code')
    }
    history.replaceState({}, '', url)
  }

  // ========== 从URL恢复 ==========
  function restoreFromUrl() {
    try {
      const url = new URL(window.location.href)
      const code = url.searchParams.get('code')
      if (code) {
        setTimeout(() => {
          selectStock(code, { source: 'url', scroll: true })
        }, 500)
      }
    } catch (e) {
      console.warn('[Selector] 恢复URL失败:', e)
    }
  }

  // ========== 搜索 ==========
  function search(keyword: string): SearchResult[] {
    if (!keyword || !keyword.trim()) {
      searchResults.value = []
      showHint.value = false
      return []
    }

    isSearching.value = true
    searchKeyword.value = keyword

    const results = SearchIndex.search(keyword)
    searchResults.value = results
    showHint.value = results.length > 0
    hintActiveIndex.value = -1

    isSearching.value = false
    return results
  }

  // ========== 清除搜索 ==========
  function clearSearch() {
    searchKeyword.value = ''
    searchResults.value = []
    showHint.value = false
    hintActiveIndex.value = -1
  }

  // ========== 选中搜索结果 ==========
  function selectSearchResult(index: number) {
    if (index >= 0 && index < searchResults.value.length) {
      const result = searchResults.value[index]
      selectStock(result.stock.code, { source: 'search' })
      clearSearch()
      return true
    }
    return false
  }

  // ========== 导航提示框 ==========
  function navigateHint(direction: 'up' | 'down') {
    if (!showHint.value || searchResults.value.length === 0) return

    if (direction === 'down') {
      hintActiveIndex.value = (hintActiveIndex.value + 1) % searchResults.value.length
    } else {
      hintActiveIndex.value =
        hintActiveIndex.value <= 0 ? searchResults.value.length - 1 : hintActiveIndex.value - 1
    }
  }

  // ========== 键盘导航 ==========
  function handleKeyNavigation(e: KeyboardEvent) {
    // 忽略输入框内的键盘事件
    const target = e.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
      // 如果是搜索框且按了 ESC，清除搜索
      if (target.id === 'search-input' && e.key === 'Escape') {
        clearSearch()
        ;(target as HTMLInputElement).value = ''
        target.blur()
      }
      return
    }

    const rows = document.querySelectorAll('tr[data-code]')
    if (rows.length === 0) return

    // 如果搜索提示框可见，优先处理提示框导航
    if (showHint.value) {
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        navigateHint('up')
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        navigateHint('down')
      } else if (e.key === 'Enter' && hintActiveIndex.value >= 0) {
        e.preventDefault()
        selectSearchResult(hintActiveIndex.value)
      } else if (e.key === 'Escape') {
        e.preventDefault()
        clearSearch()
      }
      return
    }

    // 处理表格导航
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()

      let currentIndex = -1
      if (selectedCode.value) {
        currentIndex = Array.from(rows).findIndex(
          (row) => row.getAttribute('data-code') === selectedCode.value,
        )
      }

      let nextIndex
      if (e.key === 'ArrowUp') {
        nextIndex = currentIndex > 0 ? currentIndex - 1 : rows.length - 1
      } else {
        nextIndex = currentIndex < rows.length - 1 ? currentIndex + 1 : 0
      }

      const nextRow = rows[nextIndex] as HTMLElement
      const nextCode = nextRow.getAttribute('data-code')

      if (nextCode) {
        selectStock(nextCode, { source: 'keyboard' })
        nextRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  }

  // ========== 注册键盘监听 ==========
  function registerKeyboardListener() {
    window.addEventListener('keydown', handleKeyNavigation)
  }

  // ========== 移除键盘监听 ==========
  function unregisterKeyboardListener() {
    window.removeEventListener('keydown', handleKeyNavigation)
  }

  // ========== 滚动到选中 ==========
  function scrollToSelected(behavior: ScrollBehavior = 'smooth') {
    if (selectedRow.value) {
      selectedRow.value.scrollIntoView({ behavior, block: 'center' })
    } else if (selectedCode.value) {
      const row = findRowByCode(selectedCode.value)
      if (row) {
        row.scrollIntoView({ behavior, block: 'center' })
        selectedRow.value = row
      }
    }
  }

  // ========== 重置 ==========
  function reset() {
    clearSelection()
    clearSearch()
    updateUrl(null)
  }

  // ========== 监听数据更新 ==========
  watch(
    () => useStockStore().stocks,
    (newStocks) => {
      if (newStocks && newStocks.length > 0) {
        SearchIndex.build(newStocks)

        // 如果当前有选中的股票，在数据更新后重新高亮
        if (selectedCode.value) {
          requestAnimationFrame(() => {
            highlightSelectedRow()
          })
        }
      }
    },
    { deep: true, immediate: true },
  )

  return {
    selectedCode,
    selectedRow,
    lastSelectedTime,
    initialized,
    searchKeyword,
    searchResults,
    isSearching,
    hintActiveIndex,
    showHint,
    selectedStock,
    init,
    selectStock,
    clearSelection,
    highlightSelectedRow,
    scrollToSelected,
    reset,
    search,
    clearSearch,
    selectSearchResult,
    navigateHint,
    handleKeyNavigation,
    registerKeyboardListener,
    unregisterKeyboardListener,
    findRowByCode,
    restoreFromUrl,
  }
})
