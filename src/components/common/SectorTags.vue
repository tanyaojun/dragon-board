<!-- src/components/common/SectorTags.vue -->
<template>
  <div class="sector-tags">
    <template v-if="themes && themes.length > 0">
      <span v-for="theme in visibleThemes" :key="getThemeId(theme)" class="sector-tag" :class="getTagClass(theme)"
        :style="getTagStyle(theme)" :title="getTagTitle(theme)" @click.stop="handleClick(theme, $event)"
        @mousedown.stop.prevent="onTagMouseDown" @mouseenter="onTagHover(theme)" @mouseleave="onTagLeave">
        {{ getThemeName(theme) }}
        <!-- 热门标记 -->
        <span v-if="isHotTheme(theme)" class="hot-indicator" title="热门题材">🔥</span>
        <!-- 轮动标记 -->
        <span v-if="isRotatingTheme(theme)" class="rotate-indicator" title="轮动中">🔄</span>
      </span>

      <!-- 更多题材提示 -->
      <span v-if="themes.length > maxVisible" class="sector-tag more" :title="moreThemes" @click.stop="showAllThemes">
        +{{ themes.length - maxVisible }}
      </span>
    </template>

    <!-- 没有题材时显示占位符 -->
    <span v-else class="no-data">-</span>

    <!-- 悬浮提示 -->
    <Teleport to="body">
      <div v-if="hoverTheme" class="theme-tooltip" :style="tooltipStyle" ref="tooltipRef">
        <div class="tooltip-header">
          <span class="tooltip-name">{{ hoverTheme.name }}</span>
          <span class="tooltip-heat" :style="{ color: getHeatColor(hoverTheme) }">
            {{ hoverTheme.heatLevel || '普通' }}
          </span>
        </div>
        <div class="tooltip-stats" v-if="hoverTheme.stats">
          <span>📊 {{ hoverTheme.stats.stockCount || 0 }}股</span>
          <span>📈 {{ hoverTheme.stats.ztCount || 0 }}涨停</span>
          <span>👑 {{ hoverTheme.stats.leaderCount || 0 }}龙头</span>
        </div>
        <div class="tooltip-momentum" v-if="hoverTheme.momentum">
          动量: {{ hoverTheme.momentum > 0 ? '+' : '' }}{{ hoverTheme.momentum.toFixed(1) }}
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { Theme } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { sectorCache } from '@/services/LRUCache'

const props = defineProps<{
  themes: any[]
  maxVisible?: number  // 默认为3
  showTooltip?: boolean
}>()

const emit = defineEmits<{
  (e: 'theme-click', theme: any, event: MouseEvent): void
}>()

// ========== 计算属性 ==========
const maxVisible = computed(() => props.maxVisible || 3)

// 添加去重的计算属性
const uniqueThemes = computed(() => {
  if (!props.themes || !Array.isArray(props.themes)) return []

  const themeMap = new Map()
  props.themes.forEach(theme => {
    if (!theme) return

    const id = typeof theme === 'string' ? theme : theme.id || theme.name
    if (!id) return

    if (!themeMap.has(id)) {
      themeMap.set(id, theme)
    }
  })

  return Array.from(themeMap.values())
})


const visibleThemes = computed(() => {
  return uniqueThemes.value?.slice(0, maxVisible.value) || []
})


const moreThemes = computed(() => {
  const remaining = uniqueThemes.value?.slice(maxVisible.value) || []
  return remaining.map((t) => getThemeName(t)).join('、')
})

// ========== 悬浮提示状态 ==========
const hoverTheme = ref<Theme | null>(null)
const tooltipRef = ref<HTMLElement | null>(null)
const mouseX = ref(0)
const mouseY = ref(0)

// 缓存热门题材ID
const hotThemeIds = ref<Set<string>>(new Set())
const rotatingThemeIds = ref<Set<string>>(new Set())

// 工具提示位置
const tooltipStyle = computed(() => ({
  left: mouseX.value + 15 + 'px',
  top: mouseY.value + 15 + 'px',
}))

// ========== 工具函数 ==========
function getThemeName(theme: string | Theme): string {
  if (!theme) return ''
  return typeof theme === 'string' ? theme : theme.name || '未知'
}

function getThemeId(theme: string | Theme): string {
  if (!theme) return 'unknown'
  return typeof theme === 'string' ? theme : theme.id || theme.name || 'unknown'
}

function isHotTheme(theme: string | Theme): boolean {
  if (!theme) return false
  const id = getThemeId(theme)
  return hotThemeIds.value.has(id)
}

function isRotatingTheme(theme: string | Theme): boolean {
  if (!theme) return false
  const id = getThemeId(theme)
  return rotatingThemeIds.value.has(id)
}

function getHeatColor(theme: Theme): string {
  if (!theme) return '#7f8c8d'
  if (theme.heatScore > 3000) return '#ff4757'
  if (theme.heatScore > 1500) return '#f39c12'
  return '#7f8c8d'
}

// 添加缺失的 getTagClass 方法
function getTagClass(theme: string | Theme): Record<string, boolean> {
  if (!theme) return {}

  const isHot = isHotTheme(theme)
  const isRotating = isRotatingTheme(theme)

  return {
    'theme-highlight': !isHot && !isRotating,
    'hot-theme': isHot,
    'rotating-theme': isRotating,
  }
}

// 添加 getTagStyle 方法
function getTagStyle(theme: string | Theme): Record<string, string> {
  if (!theme || typeof theme === 'string') return {}

  const style: Record<string, string> = {}
  if (theme.heatColor) {
    style.backgroundColor = theme.heatColor + '20'
    style.borderColor = theme.heatColor + '40'
    style.color = theme.heatColor
  }
  return style
}

// 添加 getTagTitle 方法
function getTagTitle(theme: string | Theme): string {
  if (!theme) return ''
  if (typeof theme === 'string') return theme

  const parts = [theme.name || '']
  if (theme.heatLevel) parts.push(`热度: ${theme.heatLevel}`)
  if (theme.momentum)
    parts.push(`动量: ${theme.momentum > 0 ? '+' : ''}${theme.momentum.toFixed(1)}`)
  if (theme.stats?.ztCount) parts.push(`涨停: ${theme.stats.ztCount}`)

  return parts.join(' · ')
}

// ========== 事件处理 ==========
function handleClick(theme: any, event: MouseEvent) {
  // 阻止事件冒泡（多重保险）
  event.stopPropagation()
  event.stopImmediatePropagation()

  // 触发全局事件打开题材详情
  EventManager.emit('sector:show-detail', {
    themeId: theme.id,
    themeName: theme.name,
  })
}

function onTagHover(theme: string | Theme) {
  if (!props.showTooltip || !theme || typeof theme === 'string') return

  // 从缓存获取题材详情
  const cached = sectorCache.get(`theme:${theme.id || theme.name}`)

  if (cached) {
    hoverTheme.value = cached
  } else {
    // 尝试从热门题材中获取
    const hotThemes = sectorAnalyzer.getHotThemes?.() || []
    const found = hotThemes.find((t) => t.id === theme.id || t.name === theme.name)
    if (found) {
      hoverTheme.value = found
      // 缓存起来，30秒过期
      sectorCache.set(`theme:${theme.id || theme.name}`, found, 30000)
    }
  }
}

function onTagLeave() {
  hoverTheme.value = null
}

function showAllThemes() {
  if (!props.themes?.length) return

  const themeNames = props.themes.map((t) => getThemeName(t)).join('、')
  EventManager.emit(AppEvents.UI.TOAST, {
    message: `📚 ${themeNames}`,
    duration: 3000,
    type: 'info',
  })
}

// ========== 更新热门题材缓存 ==========
function updateHotThemes() {
  const hotThemes = sectorAnalyzer.getHotThemes?.() || []
  hotThemeIds.value = new Set(hotThemes.map((t) => t.id))

  // 获取轮动题材
  const rotation = sectorAnalyzer.getSectorRotation?.() || []
  const rotatingIds = new Set<string>()
  rotation.forEach((item: any) => {
    if (item.sectors) {
      item.sectors.forEach((s: any) => rotatingIds.add(s.id))
    }
  })
  rotatingThemeIds.value = rotatingIds
}

// ========== 鼠标移动追踪 ==========
function onMouseMove(e: MouseEvent) {
  mouseX.value = e.clientX
  mouseY.value = e.clientY
}

// ========== 生命周期 ==========
onMounted(() => {
  updateHotThemes()

  // 监听题材更新
  EventManager.on('sector:updated', updateHotThemes)

  window.addEventListener('mousemove', onMouseMove)
})

onUnmounted(() => {
  EventManager.off('sector:updated', updateHotThemes)
  window.removeEventListener('mousemove', onMouseMove)
})
</script>

<style scoped>
/* 样式保持不变，完全沿用你原有的样式 */
.sector-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 250px;
  position: relative;
}

.sector-tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 9px;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  position: relative;
}

.sector-tag:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
  background: var(--bg-hover);
  z-index: 2;
}

/* 普通题材样式 */
.theme-highlight {
  color: var(--color-highlight) !important;
  font-weight: 500;
  background: rgba(255, 165, 2, 0.1);
  border: 1px solid rgba(255, 165, 2, 0.3);
}

.theme-highlight:hover {
  background: rgba(255, 165, 2, 0.2);
  border-color: var(--color-highlight);
}

/* 热门题材样式 */
.hot-theme {
  background: rgba(255, 71, 87, 0.1);
  border: 1px solid rgba(255, 71, 87, 0.3);
  color: #ff4757 !important;
  font-weight: 500;
}

.hot-theme:hover {
  background: rgba(255, 71, 87, 0.2);
  border-color: #ff4757;
}

/* 轮动题材样式 */
.rotating-theme {
  background: rgba(52, 152, 219, 0.1);
  border: 1px solid rgba(52, 152, 219, 0.3);
  color: #3498db !important;
  font-weight: 500;
}

.rotating-theme:hover {
  background: rgba(52, 152, 219, 0.2);
  border-color: #3498db;
}

.hot-indicator,
.rotate-indicator {
  font-size: 8px;
  margin-left: 2px;
}

.sector-tag.more {
  background: var(--bg-header);
  color: var(--text-secondary);
  font-size: 8px;
  padding: 2px 6px;
  cursor: help;
  border: 1px solid var(--border-color);
}

.sector-tag.more:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
  transform: none;
}

.no-data {
  color: var(--text-secondary);
  font-size: 11px;
  opacity: 0.6;
}

/* 工具提示 */
.theme-tooltip {
  position: fixed;
  background: var(--bg-panel);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  z-index: 10020;
  font-size: 11px;
  min-width: 150px;
  pointer-events: none;
  backdrop-filter: blur(10px);
  animation: tooltipFadeIn 0.2s ease;
}

@keyframes tooltipFadeIn {
  from {
    opacity: 0;
    transform: translateY(5px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.tooltip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-color);
}

.tooltip-name {
  font-weight: 600;
  color: var(--text-title);
  font-size: 12px;
}

.tooltip-heat {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 10px;
  background: var(--bg-primary);
}

.tooltip-stats {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  color: var(--text-secondary);
  font-size: 10px;
}

.tooltip-momentum {
  font-size: 10px;
  color: var(--color-highlight);
  padding-top: 4px;
  border-top: 1px dashed var(--border-color);
}

/* 响应式 */
@media (max-width: 768px) {
  .sector-tags {
    max-width: 150px;
  }

  .sector-tag {
    font-size: 8px;
    padding: 1px 4px;
  }
}
</style>
