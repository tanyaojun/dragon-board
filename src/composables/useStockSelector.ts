// src/composables/useStockSelector.ts

import { onMounted, onUnmounted } from 'vue'
import { useSelectorStore } from '@/stores/selector'
import { useFavoriteStore } from '@/stores/favorite'
import { EventManager } from '@/utils/eventManager'

export function useStockSelector() {
  const selectorStore = useSelectorStore()
  const favoriteStore = useFavoriteStore()

  // 处理表格点击
  function handleTableClick(e: MouseEvent) {
    const row = (e.target as HTMLElement).closest('#mainTable tbody tr[data-code]')
    if (row) {
      const code = row.getAttribute('data-code')
      if (code) {
        selectorStore.selectStock(code, { source: 'click' })
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

      // 存储当前股票信息
      const stock = {
        code,
        name,
        isFavorite: code ? favoriteStore.isFavorite(code) : false,
      }

      // 触发自定义事件，让ContextMenu组件处理
      EventManager.emit('contextmenu:show', {
        stock,
        x: e.pageX,
        y: e.pageY,
      })
    }
  }

  // 处理键盘导航
  function handleKeyDown(e: KeyboardEvent) {
    // 如果正在输入，不处理导航
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
      return
    }

    selectorStore.handleKeyNavigation(e)
  }

  // 处理数据更新
  function handleDataUpdate() {
    // 重建索引
    import('@/services/SearchIndex').then(({ SearchIndex }) => {
      SearchIndex.rebuild()
    })
  }

  // 设置事件监听
  onMounted(() => {
    document.addEventListener('click', handleTableClick)
    document.addEventListener('contextmenu', handleContextMenu)
    document.addEventListener('keydown', handleKeyDown)
    document.addEventListener('data-merged', handleDataUpdate)

    // 初始化
    selectorStore.init()
  })

  onUnmounted(() => {
    document.removeEventListener('click', handleTableClick)
    document.removeEventListener('contextmenu', handleContextMenu)
    document.removeEventListener('keydown', handleKeyDown)
    document.removeEventListener('data-merged', handleDataUpdate)
  })

  return {
    selectStock: selectorStore.selectStock,
    selectedCode: selectorStore.selectedCode,
    selectedStock: selectorStore.selectedStock,
    clearSelection: selectorStore.clearSelection,
    scrollToSelected: selectorStore.scrollToSelected,
    search: selectorStore.search,
    clearSearch: selectorStore.clearSearch,
  }
}
