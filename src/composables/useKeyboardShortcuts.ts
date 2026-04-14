// src/composables/useKeyboardShortcuts.ts

import { onMounted, onUnmounted } from 'vue'
import { keyboardService } from '@/services/keyboardService'

export function useKeyboardShortcuts(actions: {
  onDragon?: () => void
  onSector?: () => void
  onConfig?: () => void
  onBreath?: () => void
  onTrend?: () => void
  onRefresh?: () => void
  onHelp?: () => void
  onAlgorithm?: () => void
  onExport?: () => void
}) {
  onMounted(() => {
    keyboardService.registerPanelShortcuts(actions)
    
    if (actions.onAlgorithm) {
      keyboardService.registerShortcut({
        key: 'Ctrl+Shift+A',
        description: '算法配置',
        category: 'other',
        action: actions.onAlgorithm
      })
    }
    
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