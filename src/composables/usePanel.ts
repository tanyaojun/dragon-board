// src/composables/usePanel.ts

import { ref, computed, onUnmounted, watch } from 'vue'

export function usePanel(options: {
  name: string
  visible: boolean
  triggerRect?: DOMRect
  triggerSelectors?: string[]
  onClose: () => void
}) {
  const panelRef = ref<HTMLElement | null>(null)
  const isOpening = ref(false) // 新增：标记是否正在打开

  // 计算面板样式
  const panelStyle = computed(() => {
    if (!options.triggerRect) {
      return {
        top: '100px',
        right: '20px',
      }
    }

    const viewportHeight = window.innerHeight
    const panelHeight = 600

    let top = options.triggerRect.bottom + 5

    if (top + panelHeight > viewportHeight - 20) {
      top = options.triggerRect.top - panelHeight - 5
    }

    if (top < 10) {
      top = 10
    }

    return {
      top: top + 'px',
      right: Math.max(10, window.innerWidth - options.triggerRect.right) + 'px',
    }
  })

  // 点击外部关闭（带延迟保护）
  const handleClickOutside = (e: MouseEvent) => {
    if (!options.visible) return

    const target = e.target as Node

    // 如果正在打开过程中，忽略点击事件
    if (isOpening.value) {
      isOpening.value = false
      return
    }

    if (panelRef.value?.contains(target)) return

    if (options.triggerSelectors) {
      for (const selector of options.triggerSelectors) {
        const btn = document.querySelector(selector)
        if (btn && (btn === target || btn.contains(target))) {
          return
        }
      }
    }

    options.onClose()
  }

  // ESC 关闭
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && options.visible) {
      options.onClose()
    }
  }

  // 监听可见性变化
  watch(
    () => options.visible,
    (val) => {
      if (val) {
        // 标记正在打开，防止立即被点击外部关闭
        isOpening.value = true

        // 50ms 后取消打开标记
        setTimeout(() => {
          isOpening.value = false
        }, 50)

        document.addEventListener('click', handleClickOutside)
        document.addEventListener('keydown', handleKeyDown)
      } else {
        document.removeEventListener('click', handleClickOutside)
        document.removeEventListener('keydown', handleKeyDown)
      }
    },
    { immediate: true }
  )

  onUnmounted(() => {
    document.removeEventListener('click', handleClickOutside)
    document.removeEventListener('keydown', handleKeyDown)
  })

  return {
    panelRef,
    panelStyle,
  }
}
