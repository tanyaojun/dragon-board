// src/composables/useKeyboardShortcuts.ts

import { onMounted, onUnmounted } from 'vue'
import { keyboardService } from '@/services/keyboardService'

export function useKeyboardShortcuts(actions: {
  onDragon?: () => void
  onSector?: () => void
  onConfig?: () => void
  onBreath?: () => void
  onFavorite?: () => void
  onRefresh?: () => void
  onHelp?: () => void
  onSearch?: () => void
  onExport?: () => void
}) {
  onMounted(() => {
    keyboardService.registerPanelShortcuts(actions)

    if (actions.onExport) {
      keyboardService.registerShortcut({
        key: 'Ctrl+E',
        description: '导出数据',
        category: 'other',
        action: actions.onExport
      })
    }
  })
}
