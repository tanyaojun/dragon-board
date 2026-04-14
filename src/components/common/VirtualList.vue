<!-- src/components/VirtualList.vue -->
<template>
  <div class="virtual-list" ref="containerRef" @scroll="handleScroll">
    <!-- 占位元素，撑起总高度 -->
    <div class="virtual-list-phantom" :style="{ height: totalHeight + 'px' }"></div>

    <!-- 可见区域 -->
    <div class="virtual-list-content" :style="{ transform: `translateY(${offsetY}px)` }">
      <div v-for="(item, index) in visibleData" :key="getItemKey(item)" class="virtual-list-item"
        :style="{ height: itemHeight + 'px' }">
        <slot :item="item" :index="startIndex + index" :data="listData"></slot>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="virtual-list-loading">
      <span class="loading-spinner">⚙️</span>
      <span>加载数据中... {{ loadedCount }}/{{ totalCount || listData.length }}</span>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && listData.length === 0" class="virtual-list-empty">📭 暂无数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

interface Props {
  listData: any[]
  itemHeight: number
  bufferSize?: number
  loading?: boolean
  loadedCount?: number
  totalCount?: number
  itemKey?: string | ((item: any) => string)
}

const props = withDefaults(defineProps<Props>(), {
  bufferSize: 10,
  loading: false,
  loadedCount: 0,
  totalCount: 0,
  itemKey: 'code'
})

const emit = defineEmits<{
  (e: 'scroll', start: number, end: number): void
  (e: 'reach-bottom'): void
}>()

// 容器引用
const containerRef = ref<HTMLElement | null>(null)
const containerHeight = ref(0)
const scrollTop = ref(0)

// 计算总高度
const totalHeight = computed(() => props.listData.length * props.itemHeight)

// 计算可见区域可容纳的行数
const visibleRowCount = computed(() => Math.ceil(containerHeight.value / props.itemHeight))

// 计算实际渲染的起始和结束索引（包含缓冲区域）- 优化版
const startIndex = computed(() => {
  if (!props.listData.length) return 0
  const estimatedStart = Math.floor(scrollTop.value / props.itemHeight) - props.bufferSize
  return Math.max(0, Math.min(estimatedStart, props.listData.length - 1))
})

const endIndex = computed(() => {
  if (!props.listData.length) return 0
  const estimatedEnd = Math.floor(scrollTop.value / props.itemHeight) +
    visibleRowCount.value + props.bufferSize
  return Math.min(props.listData.length, estimatedEnd)
})

// 当前可视区域的数据
const visibleData = computed(() => props.listData.slice(startIndex.value, endIndex.value))

// 偏移量（用于定位内容区域）
const offsetY = computed(() => startIndex.value * props.itemHeight)

// 获取项的唯一标识 - 优化版
const getItemKey = (item: any): string => {
  if (!item) return `empty-${Math.random()}`

  if (typeof props.itemKey === 'function') {
    return props.itemKey(item)
  }

  const key = item[props.itemKey as string]
  if (key !== undefined && key !== null) {
    return String(key)
  }

  // 降级方案
  return item.code || item.id || `item-${Math.random()}`
}

// 滚动处理 - 节流版
let scrollTimer: any
const handleScroll = () => {
  if (scrollTimer) return

  scrollTimer = setTimeout(() => {
    if (!containerRef.value) {
      scrollTimer = null
      return
    }

    const container = containerRef.value
    scrollTop.value = container.scrollTop

    // 发射滚动事件
    emit('scroll', startIndex.value, endIndex.value)

    // 检测是否滚动到底部
    const scrollBottom = container.scrollTop + container.clientHeight
    const totalScrollHeight = container.scrollHeight

    if (scrollBottom >= totalScrollHeight - 20) {
      emit('reach-bottom')
    }

    scrollTimer = null
  }, 16) // 16ms ≈ 60fps，既能保证流畅又能减少计算
}

// 滚动到指定索引
const scrollToIndex = (index: number, behavior: ScrollBehavior = 'smooth') => {
  if (!containerRef.value || !props.listData.length) return

  const safeIndex = Math.max(0, Math.min(index, props.listData.length - 1))
  const top = safeIndex * props.itemHeight
  containerRef.value.scrollTo({ top, behavior })
}

// 滚动到指定项（通过 code）
const scrollToItem = (code: string, behavior: ScrollBehavior = 'smooth') => {
  if (!containerRef.value || !props.listData.length) return

  const index = props.listData.findIndex(item => item.code === code)
  if (index !== -1) {
    scrollToIndex(index, behavior)
    return true
  }
  return false
}

// 滚动到顶部
const scrollToTop = (behavior: ScrollBehavior = 'smooth') => {
  if (!containerRef.value) return
  containerRef.value.scrollTo({ top: 0, behavior })
}

// 记录上一次的数据长度
let lastDataLength = ref(0)

// 刷新（重新计算容器高度）- 只在必要时才真正刷新
const refresh = () => {
  if (!containerRef.value) return

  // 检查数据长度是否变化
  const currentLength = props.listData.length
  if (currentLength !== lastDataLength.value) {
    lastDataLength.value = currentLength
    containerHeight.value = containerRef.value.clientHeight
    handleScroll()
  } else {
    // 数据长度没变，只更新容器高度（可能因为窗口大小变化）
    containerHeight.value = containerRef.value.clientHeight
  }
}

// ResizeObserver 实例
let resizeObserver: ResizeObserver | null = null

// 生命周期
// 监听容器大小变化 - 用 ResizeObserver 但也要防抖
let resizeTimer: any
onMounted(() => {
  if (containerRef.value) {
    containerHeight.value = containerRef.value.clientHeight
    lastDataLength.value = props.listData.length

    try {
      resizeObserver = new ResizeObserver(() => {
        // 防抖，避免频繁触发
        clearTimeout(resizeTimer)
        resizeTimer = setTimeout(() => {
          refresh()
        }, 100)
      })
      resizeObserver.observe(containerRef.value)
    } catch (e) {
      console.warn('[VirtualList] ResizeObserver 不支持，使用降级方案', e)
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimer)
        resizeTimer = setTimeout(refresh, 100)
      })
    }
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  window.removeEventListener('resize', refresh)
})

// 监听数据变化 - 优化版
watch(
  () => props.listData.length,
  (newLen, oldLen) => {
    if (newLen !== oldLen) {
      nextTick(() => {
        refresh()
      })
    }
  },
  { immediate: true }
)

// 监听 itemHeight 变化
watch(
  () => props.itemHeight,
  () => {
    refresh()
  }
)

// 暴露方法给父组件
defineExpose({
  scrollToIndex,
  scrollToTop,
  scrollToItem,
  refresh,
  getCurrentIndex: () => startIndex.value,
  getVisibleCount: () => visibleData.value.length
})
</script>

<style scoped>
.virtual-list {
  height: 100%;
  overflow-y: auto;
  position: relative;
  -webkit-overflow-scrolling: touch;
}

.virtual-list-phantom {
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  z-index: -1;
  pointer-events: none;
}

.virtual-list-content {
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  will-change: transform;
}

.virtual-list-item {
  box-sizing: border-box;
  width: 100%;
  overflow: hidden;
}

.virtual-list-loading,
.virtual-list-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px;
  color: var(--text-secondary);
  font-size: 14px;
  background: var(--bg-primary);
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  z-index: 10;
}

.loading-spinner {
  font-size: 20px;
  animation: rotate 1s infinite linear;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

/* 自定义滚动条 */
.virtual-list::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.virtual-list::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-radius: 4px;
}

.virtual-list::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 4px;
}

.virtual-list::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
}

/* 确保内容可见 */
.virtual-list-content {
  min-width: fit-content;
}
</style>
