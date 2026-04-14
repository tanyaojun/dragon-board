// src/composables/useStockSelector.ts

import { onMounted, onUnmounted } from 'vue'
import { useSelectorStore } from '@/stores/selector'
import { useFavoriteStore } from '@/stores/favorite'
import { useUIStore } from '@/stores/ui'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types/config'

export function useStockSelector() {
  const selectorStore = useSelectorStore()
  const favoriteStore = useFavoriteStore()
  const uiStore = useUIStore()

  // 处理表格点击
  function handleTableClick(e: MouseEvent) {
    const row = (e.target as HTMLElement).closest('#mainTable tbody tr[data-code]')
    if (row) {
      const code = row.getAttribute('data-code')
      if (code) {
        selectorStore.selectStock(code, { source: 'click' })
        uiStore.selectStock(code)
      }
    }
  }

  // 处理右键菜单
  function handleContextMenu(e: MouseEvent) {
    const row = (e.target as HTMLElement).closest('tr[data-code]')
    if (row) {
      e.preventDefault()
      e.stopPropagation()

      const code = row.getAttribute('data-code')
      const nameCell = row.querySelector('td:nth-child(2)')
      let name = code

      if (nameCell) {
        name = nameCell.textContent?.replace(/[👑📈🏆⚔️🔥🐲]/g, '').trim() || code
      }

      const stock = {
        code,
        name,
        isFavorite: code ? favoriteStore.isFavorite(code) : false,
      }

      EventManager.emit('contextmenu:show', {
        stock,
        x: e.pageX,
        y: e.pageY,
      })
    }
  }

  // 处理键盘导航
  function handleKeyDown(e: KeyboardEvent) {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
      return
    }
    selectorStore.handleKeyNavigation(e)
  }

  // 处理数据更新 - 重建索引（使用 uiStore 获取数据）
  async function handleDataUpdate() {
    const { SearchIndex } = await import('@/services/SearchIndex')
    const stocks = uiStore.rawStocks
    if (stocks && stocks.length > 0) {
      SearchIndex.build(stocks)
    }
  }

  onMounted(() => {
    document.addEventListener('click', handleTableClick)
    document.addEventListener('contextmenu', handleContextMenu)
    document.addEventListener('keydown', handleKeyDown)
    EventManager.on(AppEvents.DATA.MERGED, handleDataUpdate)

    selectorStore.init()
  })

  onUnmounted(() => {
    document.removeEventListener('click', handleTableClick)
    document.removeEventListener('contextmenu', handleContextMenu)
    document.removeEventListener('keydown', handleKeyDown)
    EventManager.off(AppEvents.DATA.MERGED, handleDataUpdate)
  })

  return {
    selectStock: (code: string, options?: { source?: string }) => {
      selectorStore.selectStock(code, options)
      uiStore.selectStock(code)
    },
    selectedCode: selectorStore.selectedCode,
    selectedStock: selectorStore.selectedStock,
    clearSelection: selectorStore.clearSelection,
    scrollToSelected: selectorStore.scrollToSelected,
    search: selectorStore.search,
    clearSearch: selectorStore.clearSearch,
  }
}