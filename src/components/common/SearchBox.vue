<!-- src/components/common/SearchBox.vue -->
<template>
  <div class="search-box" :class="{ compact }" ref="searchBoxRef">
    <input ref="inputRef" type="text" class="search-input" :placeholder="placeholder" :value="modelValue"
      @input="handleInput" @keydown="handleKeyDown" @focus="handleFocus" @blur="handleBlur" />
    <button v-if="modelValue" class="search-clear" @click="clearSearch" title="清除">
      <span class="icon">✕</span>
    </button>
    <button class="search-icon">
      <span class="icon">🔍</span>
    </button>

    <!-- 搜索提示框 -->
    <div v-if="showHint && hintResults.length > 0" class="search-hint">
      <div v-for="(result, index) in hintResults" :key="result.stock.code" class="hint-item"
        :class="{ 'hint-active': activeIndex === index }" @click="selectHint(result.stock.code)"
        @mouseenter="activeIndex = index">
        <div class="hint-left">
          <span class="hint-code">{{ result.stock.code }}</span>
          <span class="hint-name">{{ result.stock.name }}</span>
          <span v-if="result.stock.isSectorLeader" class="hint-badge"
            :style="{ color: getLeaderColor(result.stock.leaderLevel) }">
            {{ getLeaderIcon(result.stock.leaderLevel) }}
          </span>
        </div>
        <div class="hint-right">
          <span class="hint-pinyin">{{ getPinyinInitials(result.stock.name) }}</span>
          <span class="hint-match">{{ getMatchTypeText(result.matchType) }}</span>
        </div>
      </div>

      <div v-if="hintResults.length > 8" class="hint-more">
        还有 {{ hintResults.length - 8 }} 个结果...
      </div>

      <div v-if="recentSearches.length > 0 && !modelValue" class="hint-recent">
        <div class="hint-recent-header">最近搜索</div>
        <div v-for="keyword in recentSearches.slice(0, 5)" :key="keyword" class="hint-recent-item"
          @click="searchKeyword(keyword)">
          <span class="icon">🕒</span>
          {{ keyword }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { SearchIndex } from '@/services/SearchIndex'
import { PinyinUtils } from '@/utils/pinyin'
import { EventManager } from '@/utils/eventManager'
import type { SearchResult } from '@/types'

const props = defineProps<{
  modelValue: string
  placeholder?: string
  autoFocus?: boolean
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'search', keyword: string): void
  (e: 'select', code: string): void
}>()

const inputRef = ref<HTMLInputElement>()
const searchBoxRef = ref<HTMLElement>()
const showHint = ref(false)
const activeIndex = ref(-1)
const hintResults = ref<SearchResult[]>([])
const recentSearches = ref<string[]>([])

// 龙头级别配置
const LEADER_LEVELS: Record<string, { icon: string; color: string }> = {
  总龙头: { icon: '👑', color: '#FFD700' },
  连板龙头: { icon: '📈', color: '#e74c3c' },
  板块龙头: { icon: '🏆', color: '#3498db' },
  中军龙头: { icon: '⚔️', color: '#9b59b6' },
  情绪龙头: { icon: '🔥', color: '#f39c12' },
}

// 获取龙头图标
function getLeaderIcon(level?: string): string {
  if (!level) return ''
  return LEADER_LEVELS[level]?.icon || ''
}

// 获取龙头颜色
function getLeaderColor(level?: string): string {
  if (!level) return ''
  return LEADER_LEVELS[level]?.color || ''
}

// 获取匹配类型文本
function getMatchTypeText(type: string): string {
  const map: Record<string, string> = {
    exact: '🔍 精确',
    prefix: '🔎 前缀',
    contains: '📄 包含',
  }
  return map[type] || ''
}

// 获取拼音首字母
function getPinyinInitials(name: string): string {
  return PinyinUtils.getPinyinInitials(name)
}

// 处理输入
let searchTimeout: number
function handleInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  emit('update:modelValue', value)

  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    performSearch(value)
  }, 300) as unknown as number
}

// 执行搜索
function performSearch(keyword: string) {
  if (!keyword) {
    hintResults.value = []
    showHint.value = false
    emit('search', '')
    // 清除高亮
    EventManager.emit('search:clear', {})
    return
  }

  const results = SearchIndex.search(keyword)
  hintResults.value = results.slice(0, 8)
  showHint.value = true
  activeIndex.value = -1

  emit('search', keyword)

  // 发出高亮事件
  EventManager.emit('search:highlight', { keyword, results })

  // 记录搜索历史
  addToHistory(keyword)
}

// 处理键盘
function handleKeyDown(e: KeyboardEvent) {
  if (!showHint.value || hintResults.value.length === 0) return

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = (activeIndex.value + 1) % hintResults.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value =
      activeIndex.value <= 0 ? hintResults.value.length - 1 : activeIndex.value - 1
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (activeIndex.value >= 0) {
      selectHint(hintResults.value[activeIndex.value].stock.code)
    }
  } else if (e.key === 'Escape') {
    showHint.value = false
  }
}

// 处理焦点
function handleFocus() {
  if (props.modelValue) {
    performSearch(props.modelValue)
  } else if (recentSearches.value.length > 0) {
    showHint.value = true
  }
}

function handleBlur() {
  setTimeout(() => {
    showHint.value = false
  }, 200)
}

// 选中提示项
function selectHint(code: string) {
  emit('select', code)
  showHint.value = false
}

// 清除搜索
function clearSearch() {
  emit('update:modelValue', '')
  emit('search', '')
  hintResults.value = []
  showHint.value = false
  // 清除高亮
  EventManager.emit('search:clear', {})
  inputRef.value?.focus()
}

// 搜索关键词
function searchKeyword(keyword: string) {
  emit('update:modelValue', keyword)
  performSearch(keyword)
}

// 搜索历史
function addToHistory(keyword: string) {
  if (!keyword) return

  recentSearches.value = recentSearches.value.filter((k) => k !== keyword)
  recentSearches.value.unshift(keyword)

  if (recentSearches.value.length > 10) {
    recentSearches.value.pop()
  }

  localStorage.setItem('recent_searches', JSON.stringify(recentSearches.value))
}

function loadHistory() {
  try {
    const saved = localStorage.getItem('recent_searches')
    if (saved) {
      recentSearches.value = JSON.parse(saved)
    }
  } catch (e) {
    console.warn('加载搜索历史失败:', e)
  }
}

// 点击外部关闭
function handleClickOutside(e: MouseEvent) {
  if (searchBoxRef.value && !searchBoxRef.value.contains(e.target as Node)) {
    showHint.value = false
  }
}

watch(
  () => props.modelValue,
  (newVal) => {
    if (!newVal) {
      hintResults.value = []
      EventManager.emit('search:clear', {})
    }
  },
)

onMounted(() => {
  loadHistory()
  document.addEventListener('click', handleClickOutside)

  if (props.autoFocus) {
    inputRef.value?.focus()
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  clearTimeout(searchTimeout)
})
</script>

<style scoped>
.search-box {
  position: relative;
  width: 300px;
}

.search-box.compact {
  width: 200px;
}

.search-input {
  width: 100%;
  height: 36px;
  padding: 0 36px 0 36px;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  transition: all 0.2s;
}

.search-box.compact .search-input {
  height: 32px;
  font-size: 12px;
}

.search-input:focus {
  outline: none;
  border-color: var(--color-highlight);
  box-shadow: 0 0 0 2px rgba(255, 127, 80, 0.2);
}

.search-input::placeholder {
  color: var(--text-tertiary);
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 4px;
}

.search-clear {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 4px;
  border-radius: 50%;
  transition: all 0.2s;
}

.search-clear:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.search-hint {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 400px;
  overflow-y: auto;
  background: var(--bg-panel);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  z-index: 10060;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.hint-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: all 0.2s;
  border-bottom: 1px solid var(--border-light);
}

.hint-item:last-child {
  border-bottom: none;
}

.hint-item:hover,
.hint-item.hint-active {
  background: var(--bg-hover);
}

.hint-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint-code {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  color: var(--color-highlight);
  font-size: 12px;
  font-weight: 500;
}

.hint-name {
  font-weight: 500;
  font-size: 13px;
}

.hint-badge {
  font-size: 14px;
  margin-left: 4px;
}

.hint-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.hint-pinyin {
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

.hint-match {
  padding: 2px 6px;
  background: var(--badge-bg);
  border-radius: 12px;
}

.hint-more {
  padding: 8px 16px;
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
  border-top: 1px solid var(--border-light);
}

.hint-recent {
  padding: 8px 0;
}

.hint-recent-header {
  padding: 8px 16px;
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.hint-recent-item {
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
}

.hint-recent-item:hover {
  background: var(--bg-hover);
}

.hint-recent-item .icon {
  font-size: 12px;
  opacity: 0.5;
}

/* 响应式 */
@media (max-width: 768px) {
  .search-box {
    width: 200px;
  }

  .search-box.compact {
    width: 160px;
  }
}

@media (max-width: 480px) {
  .search-box {
    width: 160px;
  }

  .search-box.compact {
    width: 140px;
  }

  .hint-right {
    display: none;
  }
}
</style>
