import { debugLog } from '@/utils/logger'
// src/stores/theme.ts

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useConfigStore } from './config'
import { THEMES } from '@/themes/app-themes'
import type { ThemeType } from '@/types/theme'
import { dragonThemes } from '@/themes/dragon-themes'
import { EventManager } from '@/utils/eventManager'

// 定义龙族主题类型
export interface DragonThemeData {
  id: string
  name: string
  icon: string
  element: string
  personality: string[]
  colors: {
    primary: string
    secondary: string
    accent: string
  }
  suitable: string[]
  power: {
    name: string
    description: string
    effect: string
  }
}

// 主题存储 - 合并两个主题系统
export const useThemeStore = defineStore('theme', () => {
  const configStore = useConfigStore()

  // ========== 原有主题状态 ==========
  const currentTheme = ref<ThemeType>(configStore.user.theme as ThemeType)
  const followSystem = ref(configStore.user.followSystemTheme)
  const systemTheme = ref<'dark' | 'light'>('light')

  // ========== 龙族主题状态 ==========
  const currentDragonTheme = ref(localStorage.getItem('dragon-theme') || 'qiniu')
  const dragonThemeEnabled = ref(localStorage.getItem('dragon-theme-enabled') === 'true')
  const themeMode = ref<'light' | 'dark' | 'system'>(
    (localStorage.getItem('theme-mode') as 'light' | 'dark' | 'system') || 'system',
  )

  // ========== 原有主题计算属性 ==========
  const themeConfig = computed(() => THEMES[currentTheme.value])

  // ========== 龙族主题计算属性 ==========
  const dragonThemeData = computed<DragonThemeData>(
    () => dragonThemes.find((t) => t.id === currentDragonTheme.value) || dragonThemes[0],
  )

  // ========== 合并的主题类名 ==========
  const themeClass = computed(() => {
    if (dragonThemeEnabled.value) {
      // 龙族主题模式
      return `dragon-theme theme-${currentDragonTheme.value} ${themeMode.value}-mode`
    } else {
      // 原有主题模式
      return `${currentTheme.value}-theme`
    }
  })

  // 主题图标
  const themeIcon = computed(() => {
    if (dragonThemeEnabled.value) {
      return dragonThemeData.value.icon || '🐉'
    }
    return themeConfig.value.icon
  })

  // ========== 原有主题方法 ==========
  function setTheme(theme: ThemeType) {
    if (!THEMES[theme]) return

    const themeColors = THEMES[theme].colors
    const root = document.documentElement

    // 应用 CSS 变量
    Object.entries(themeColors).forEach(([key, value]) => {
      root.style.setProperty(key, value)
    })

    currentTheme.value = theme
    dragonThemeEnabled.value = false
    localStorage.setItem('dragon-theme-enabled', 'false')
    root.dataset.theme = theme
    root.classList.remove('dragon-theme', 'light-mode', 'dark-mode')

    // 保存到 configStore
    if (!followSystem.value) {
      configStore.setUserConfig('theme', theme)
    }

    // 更新右键菜单
    updateContextMenu(theme)

    // 更新下拉菜单
    updateDropdownMenu(theme)

    debugLog(`[ThemeStore] 已切换到 ${THEMES[theme].name} 主题`)

    // 触发事件
    window.dispatchEvent(
      new CustomEvent('theme-changed', {
        detail: { theme, name: THEMES[theme].name },
      }),
    )
  }

  function toggleTheme() {
    const themes: ThemeType[] = ['dark', 'light', 'matrix', 'cream']
    const currentIndex = themes.indexOf(currentTheme.value)
    const nextIndex = (currentIndex + 1) % themes.length

    if (followSystem.value) {
      followSystem.value = false
      configStore.setUserConfig('followSystemTheme', false)
    }

    setTheme(themes[nextIndex])
  }

  function toggleFollowSystem() {
    followSystem.value = !followSystem.value
    configStore.setUserConfig('followSystemTheme', followSystem.value)

    if (followSystem.value && systemTheme.value) {
      setTheme(systemTheme.value as ThemeType)
    }

    return followSystem.value
  }

  function detectSystemTheme() {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)')
    systemTheme.value = prefersDark.matches ? 'dark' : 'light'
  }

  function updateContextMenu(theme: ThemeType) {
    const menu = document.getElementById('context-menu')
    if (!menu) return

    menu.classList.remove('dark-theme', 'matrix-theme', 'cream-theme')

    if (theme === 'dark') {
      menu.classList.add('dark-theme')
    } else if (theme === 'matrix') {
      menu.classList.add('matrix-theme')
    } else if (theme === 'cream') {
      menu.classList.add('cream-theme')
    }

    menu.style.setProperty('background', 'var(--bg-panel)')
    menu.style.setProperty('color', 'var(--text-primary)')
  }

  function updateDropdownMenu(theme: ThemeType) {
    const dropdown = document.querySelector<HTMLElement>('.dropdown-content')
    if (!dropdown) return

    dropdown.classList.remove('dark-theme', 'matrix-theme', 'cream-theme')

    if (theme === 'dark') {
      dropdown.classList.add('dark-theme')
    } else if (theme === 'matrix') {
      dropdown.classList.add('matrix-theme')
    } else if (theme === 'cream') {
      dropdown.classList.add('cream-theme')
    }

    dropdown.style.setProperty('background', 'var(--bg-panel)')
    dropdown.style.setProperty('border-color', 'var(--border-color)')
    dropdown.style.setProperty('color', 'var(--text-primary)')
  }

  // ========== 龙族主题方法 ==========
  function setDragonTheme(themeId: string) {
    currentDragonTheme.value = themeId
    localStorage.setItem('dragon-theme', themeId)

    if (dragonThemeEnabled.value) {
      applyDragonThemeVariables(themeId)
    }

    // 使用统一事件方式触发
    const theme = dragonThemes.find((t) => t.id === themeId)
    EventManager.emit('dragon-theme-change', {
      theme: themeId,
      themeData: theme,
    })

    debugLog(`[ThemeStore] 已切换到龙族主题: ${dragonThemeData.value.name}`)
  }

  function applyDragonThemeVariables(themeId: string) {
    const theme = dragonThemes.find((t) => t.id === themeId)
    if (!theme) return

    const root = document.documentElement

    // 应用龙族颜色变量
    Object.entries(theme.colors).forEach(([key, value]) => {
      root.style.setProperty(`--color-${key}`, value)
    })

    // 设置龙族特有变量
    root.style.setProperty('--dragon-name', `"${theme.name}"`)
    root.style.setProperty('--dragon-icon', `"${theme.icon}"`)
    root.style.setProperty('--dragon-element', theme.element)

    // 同时设置一些通用变量，保持兼容性
    root.style.setProperty('--color-primary', theme.colors.primary)
    root.style.setProperty('--color-accent', theme.colors.accent)
    root.style.setProperty('--tag-bg', theme.colors.secondary + '33')
  }

  function enableDragonTheme(enable: boolean) {
    dragonThemeEnabled.value = enable
    localStorage.setItem('dragon-theme-enabled', String(enable))

    if (enable) {
      document.documentElement.classList.add('dragon-theme')
      // 切换到龙族主题
      applyDragonThemeVariables(currentDragonTheme.value)

      // 保存当前原有主题，以便切回
      localStorage.setItem('previous-theme', currentTheme.value)

      debugLog('[ThemeStore] 🐉 龙族主题已启用')
    } else {
      document.documentElement.classList.remove('dragon-theme')
      // 切换回原有主题
      setTheme(currentTheme.value)
      debugLog('[ThemeStore] 🎨 已切回普通主题')
    }

    EventManager.emit('theme-mode-changed', { dragonEnabled: enable })
  }

  // ========== 主题模式方法 ==========
  function setThemeMode(mode: 'light' | 'dark' | 'system') {
    themeMode.value = mode
    localStorage.setItem('theme-mode', mode)

    if (mode === 'system') {
      followSystem.value = true
    } else {
      followSystem.value = false
    }

    applyThemeMode(mode)
  }

  function applyThemeMode(mode: 'light' | 'dark' | 'system') {
    const root = document.documentElement

    if (mode === 'system') {
      const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      root.classList.toggle('dark-mode', systemPrefersDark)
      root.classList.toggle('light-mode', !systemPrefersDark)
    } else {
      root.classList.toggle('dark-mode', mode === 'dark')
      root.classList.toggle('light-mode', mode === 'light')
    }
  }

  // 获取下一个龙族主题（用于循环切换）
  function getNextDragonTheme(): string {
    const currentIndex = dragonThemes.findIndex((t) => t.id === currentDragonTheme.value)
    const nextIndex = (currentIndex + 1) % dragonThemes.length
    return dragonThemes[nextIndex].id
  }

  // 随机切换龙族主题
  function randomDragonTheme() {
    const randomIndex = Math.floor(Math.random() * dragonThemes.length)
    setDragonTheme(dragonThemes[randomIndex].id)
  }

  // 根据股票代码推荐龙族主题
  function recommendDragonTheme(stockCode: string): string {
    // 这里可以根据股票代码的行业属性推荐对应的龙子
    // 简单示例：根据代码尾号推荐
    const lastDigit = stockCode.slice(-1)
    const index = parseInt(lastDigit) % dragonThemes.length
    return dragonThemes[index].id
  }

  // ========== 初始化 ==========
  function init() {
    // 检测系统主题
    detectSystemTheme()

    // 应用保存的主题模式
    applyThemeMode(themeMode.value)

    if (dragonThemeEnabled.value) {
      document.documentElement.dataset.theme = currentTheme.value
      document.documentElement.classList.add('dragon-theme')
      // 应用龙族主题
      applyDragonThemeVariables(currentDragonTheme.value)
      debugLog(`[ThemeStore] 🐉 龙族主题初始化: ${dragonThemeData.value.name}`)
    } else {
      // 应用原有主题
      setTheme(currentTheme.value)
    }

    // 监听系统主题变化
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handleSystemThemeChange = (e: MediaQueryListEvent) => {
      systemTheme.value = e.matches ? 'dark' : 'light'

      if (followSystem.value) {
        setTheme(systemTheme.value as ThemeType)
      }

      if (themeMode.value === 'system') {
        applyThemeMode('system')
      }
    }

    mediaQuery.addEventListener('change', handleSystemThemeChange)

    // 监听 configStore 变化
    watch(
      () => configStore.user.theme,
      (newTheme) => {
        if (!dragonThemeEnabled.value && !followSystem.value) {
          setTheme(newTheme as ThemeType)
        }
      },
    )

    watch(
      () => configStore.user.followSystemTheme,
      (newValue) => {
        followSystem.value = newValue
        if (!dragonThemeEnabled.value && newValue && systemTheme.value) {
          setTheme(systemTheme.value as ThemeType)
        }
      },
    )

    debugLog('[ThemeStore] 🎨 主题系统初始化完成')
  }

  return {
    // 原有主题状态
    currentTheme,
    followSystem,
    systemTheme,

    // 龙族主题状态
    currentDragonTheme,
    dragonThemeEnabled,
    themeMode,

    // 计算属性
    themeConfig,
    dragonThemeData,
    themeClass,
    themeIcon,

    // 原有主题方法
    setTheme,
    toggleTheme,
    toggleFollowSystem,
    detectSystemTheme,
    updateContextMenu,
    updateDropdownMenu,

    // 龙族主题方法
    setDragonTheme,
    enableDragonTheme,
    setThemeMode,
    getNextDragonTheme,
    randomDragonTheme,
    recommendDragonTheme,

    // 初始化
    init,
  }
})

// 类型导出
export type ThemeStore = ReturnType<typeof useThemeStore>
