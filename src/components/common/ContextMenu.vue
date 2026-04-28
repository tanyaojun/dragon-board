<!-- src/components/common/ContextMenu.vue -->
<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuRef"
      class="context-menu"
      :class="themeStore.themeClass"
      :style="menuStyle"
    >
      <div v-if="stock" class="menu-header">
        <span class="stock-code">{{ stock.code }}</span>
        <span class="stock-name">{{ stock.name }}</span>
      </div>

      <div v-if="stock" class="menu-divider"></div>

      <div class="menu-item" @click="handleAction('addToFavorite')">
        <span class="item-icon">{{ stock?.isFavorite ? '➖' : '⭐' }}</span>
        <span class="item-text">{{ stock?.isFavorite ? '取消自选' : '加入自选' }}</span>
      </div>

      <div class="menu-item" @click="handleAction('addToBlock')">
        <span class="item-icon">📁</span>
        <span class="item-text">加入板块</span>
      </div>

      <div class="menu-divider"></div>

      <div class="menu-item" @click="handleAction('copyCode')">
        <span class="item-icon">📋</span>
        <span class="item-text">复制代码</span>
      </div>

      <div class="menu-item" @click="handleAction('copyName')">
        <span class="item-icon">📝</span>
        <span class="item-text">复制名称</span>
      </div>

      <div class="menu-divider"></div>

      <div class="menu-item" @click="handleAction('viewDetails')">
        <span class="item-icon">🔍</span>
        <span class="item-text">查看详情</span>
      </div>

      <div class="menu-item" @click="handleAction('viewKLine')">
        <span class="item-icon">📈</span>
        <span class="item-text">查看K线</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useFavoriteStore } from '@/stores/favorite'
import { useSelectorStore } from '@/stores/selector'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

interface StockInfo {
  code: string
  name: string
  isFavorite?: boolean
}

const themeStore = useThemeStore()
const favoriteStore = useFavoriteStore()
const selectorStore = useSelectorStore()

const visible = ref(false)
const stock = ref<StockInfo | null>(null)
const position = reactive({ x: 0, y: 0 })
const menuRef = ref<HTMLElement>()

const menuStyle = computed(() => ({
  left: `${position.x}px`,
  top: `${position.y}px`,
}))

// 处理动作
const handleAction = (action: string) => {
  if (!stock.value) return

  switch (action) {
    case 'addToFavorite':
      if (stock.value.isFavorite) {
        favoriteStore.removeFromFavorites(stock.value.code)
        stock.value.isFavorite = false
        EventManager.emit(AppEvents.UI.TOAST, {
          message: `➖ 已从自选中移除 ${stock.value.name}`,
          duration: 1500,
          type: 'info',
        })
      } else {
        favoriteStore.addToFavorites(stock.value.code, '默认', '')
        stock.value.isFavorite = true
        EventManager.emit(AppEvents.UI.TOAST, {
          message: `⭐ 已将 ${stock.value.name} 加入自选`,
          duration: 1500,
          type: 'success',
        })
      }
      break

    case 'addToBlock':
      EventManager.emit(AppEvents.UI.TOAST, {
        message: '📁 板块功能开发中',
        duration: 1500,
        type: 'info',
      })
      break

    case 'copyCode':
      const codeToCopy = stock.value.code
      navigator.clipboard
        ?.writeText(codeToCopy)
        .then(() => {
          EventManager.emit(AppEvents.UI.TOAST, {
            message: `📋 已复制 ${codeToCopy}`,
            duration: 1500,
            type: 'success',
          })
        })
        .catch(() => {
          // 降级方案
          const textarea = document.createElement('textarea')
          textarea.value = stock.value?.code || ''
          document.body.appendChild(textarea)
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)

          EventManager.emit(AppEvents.UI.TOAST, {
            message: `📋 已复制 ${stock.value?.code}`,
            duration: 1500,
            type: 'success',
          })
        })
      break

    case 'copyName':
      const nameToCopy = stock.value.name
      navigator.clipboard
        ?.writeText(nameToCopy)
        .then(() => {
          EventManager.emit(AppEvents.UI.TOAST, {
            message: `📝 已复制 ${nameToCopy}`,
            duration: 1500,
            type: 'success',
          })
        })
        .catch(() => {
          // 降级方案
          const textarea = document.createElement('textarea')
          textarea.value = stock.value?.name || ''
          document.body.appendChild(textarea)
          textarea.select()
          document.execCommand('copy')
          document.body.removeChild(textarea)

          EventManager.emit(AppEvents.UI.TOAST, {
            message: `📝 已复制 ${stock.value?.name}`,
            duration: 1500,
            type: 'success',
          })
        })
      break

    case 'viewDetails':
      if (stock.value) {
        selectorStore.selectStock(stock.value.code, { source: 'contextmenu' })
        // 触发股票选中事件
        EventManager.emit(AppEvents.STOCK.SELECTED, {
          code: stock.value.code,
          source: 'contextmenu',
        })
      }
      break

    case 'viewKLine':
      // 转换代码格式：600001 -> sh600001, 000001 -> sz000001
      const code = stock.value.code
      const market = code.startsWith('6') ? 'sh' : 'sz'
      const cleanCode = code.replace(/[^0-9]/g, '')
      window.open(`https://quote.eastmoney.com/${market}${cleanCode}.html`, '_blank')
      break
  }

  hide()
}

// 显示菜单
const show = (menuStock: StockInfo, x: number, y: number) => {
  // 检查是否已自选
  const isFavorite = favoriteStore.isFavorite(menuStock.code)

  stock.value = {
    ...menuStock,
    isFavorite,
  }
  position.x = x
  position.y = y
  visible.value = true

  // 调整位置，确保不超出窗口
  setTimeout(() => {
    if (menuRef.value) {
      const rect = menuRef.value.getBoundingClientRect()
      const viewportWidth = window.innerWidth
      const viewportHeight = window.innerHeight

      // 水平方向调整
      if (position.x + rect.width > viewportWidth) {
        position.x = viewportWidth - rect.width - 10
      }

      // 垂直方向调整
      if (position.y + rect.height > viewportHeight) {
        position.y = viewportHeight - rect.height - 10
      }

      // 确保不超出左边界
      if (position.x < 10) {
        position.x = 10
      }

      // 确保不超出上边界
      if (position.y < 10) {
        position.y = 10
      }
    }
  }, 10)
}

// 隐藏菜单
const hide = () => {
  visible.value = false
  stock.value = null
}

// 点击外部关闭
const handleClickOutside = (e: MouseEvent) => {
  if (visible.value && menuRef.value && !menuRef.value.contains(e.target as Node)) {
    hide()
  }
}

// 监听自定义事件
const handleContextMenuShow = (e: any) => {
  const { stock: stockData, x, y } = e.detail || e
  if (stockData && x !== undefined && y !== undefined) {
    show(stockData, x, y)
  }
}

// 监听ESC键关闭
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && visible.value) {
    hide()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
  EventManager.on('contextmenu:show', handleContextMenuShow)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
  EventManager.off('contextmenu:show', handleContextMenuShow)
})
</script>

<style scoped>
.context-menu {
  position: fixed;
  min-width: 200px;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  z-index: 10070;
  padding: 8px 0;
  animation: fadeIn 0.15s ease;
  font-size: 13px;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.menu-header {
  padding: 12px 16px 8px;
  border-bottom: 1px solid var(--border-light);
}

.stock-code {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  color: var(--color-highlight);
  font-size: 12px;
  font-weight: 500;
  margin-right: 8px;
}

.stock-name {
  font-weight: 500;
  font-size: 13px;
  color: var(--text-primary);
}

.menu-item {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-primary);
  font-size: 13px;
}

.menu-item:hover {
  background: var(--bg-hover);
  color: var(--color-highlight);
  padding-left: 20px;
}

.item-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
}

.menu-divider {
  height: 1px;
  background: var(--border-light);
  margin: 4px 0;
}

/* 深色主题适配 */
[data-theme='dark'] .context-menu {
  border-color: var(--border-color);
}

/* 矩阵主题适配 */
[data-theme='matrix'] .menu-item:hover {
  background: rgba(0, 255, 0, 0.1);
}

/* 响应式 */
@media (max-width: 768px) {
  .context-menu {
    min-width: 160px;
    font-size: 12px;
  }

  .menu-item {
    padding: 8px 12px;
    gap: 8px;
  }

  .item-icon {
    font-size: 14px;
    width: 16px;
  }
}
</style>
