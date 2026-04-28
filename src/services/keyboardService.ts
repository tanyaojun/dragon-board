// src/services/keyboardService.ts

interface Shortcut {
  key: string
  description: string
  category: 'navigation' | 'search' | 'view' | 'panels' | 'other'
  action: () => void
}

class KeyboardService {
  private shortcuts: Shortcut[] = []
  private enabled = true
  private registeredKeys = new Set<string>() // 记录已注册的快捷键，避免重复

  constructor() {
    this.initDefaultShortcuts()
    this.setupListener()
  }

  private initDefaultShortcuts() {
    this.shortcuts = [
      // 导航
      { key: '↑', description: '上一行', category: 'navigation', action: () => {} },
      { key: '↓', description: '下一行', category: 'navigation', action: () => {} },
      { key: 'Enter', description: '查看详情/龙头面板', category: 'navigation', action: () => {} },
      { key: 'Space', description: '快速查看', category: 'navigation', action: () => {} },
      
      // 搜索
      { key: '/', description: '聚焦搜索框', category: 'search', action: () => {} },
      { key: 'ESC', description: '清除搜索/关闭面板', category: 'search', action: () => {} },
      { key: '↓/↑', description: '导航搜索提示', category: 'search', action: () => {} },
      
      // 视图
      { key: 'F1', description: '显示/隐藏帮助', category: 'view', action: () => {} },
      { key: 'F5', description: '刷新数据', category: 'view', action: () => {} },
      { key: 'F11', description: '全屏模式', category: 'view', action: () => {} },
      
      // 面板
      { key: 'Ctrl+D', description: '显示龙头面板', category: 'panels', action: () => {} },
      { key: 'Ctrl+S', description: '显示题材分析', category: 'panels', action: () => {} },
      { key: 'Ctrl+B', description: '显示龙息分析', category: 'panels', action: () => {} },
      { key: 'Ctrl+T', description: '显示参数回测', category: 'panels', action: () => {} },
      { key: 'Ctrl+F', description: '显示自选股', category: 'panels', action: () => {} },
      
      // 其他
      { key: '?', description: '显示帮助', category: 'other', action: () => {} },
      { key: 'Shift+?', description: '显示帮助', category: 'other', action: () => {} },
      { key: 'Ctrl+Shift+A', description: '算法配置', category: 'other', action: () => {} },
      { key: 'Ctrl+E', description: '导出数据', category: 'other', action: () => {} }
    ]
    
    // 记录默认快捷键的 key
    this.shortcuts.forEach(s => this.registeredKeys.add(s.key))
  }

  private setupListener() {
    window.addEventListener('keydown', (e) => {
      if (!this.enabled) return
      
      // 忽略输入框内的快捷键
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        // 特殊处理：在输入框中按 ESC 可以清除内容
        if (e.key === 'Escape' && target.tagName === 'INPUT') {
          // 让输入框自己处理 ESC
          return
        }
        return
      }

      const key = this.getKeyString(e)
      const shortcut = this.findShortcut(key)
      
      if (shortcut && shortcut.action) {
        e.preventDefault()
        shortcut.action()
      }
    })
  }

  private getKeyString(e: KeyboardEvent): string {
    const parts: string[] = []
    if (e.ctrlKey) parts.push('Ctrl')
    if (e.shiftKey) parts.push('Shift')
    if (e.altKey) parts.push('Alt')
    
    // 特殊键处理
    const keyMap: Record<string, string> = {
      ' ': 'Space',
      'Escape': 'ESC',
      'ArrowUp': '↑',
      'ArrowDown': '↓',
      'ArrowLeft': '←',
      'ArrowRight': '→'
    }
    
    const key = keyMap[e.key] || e.key.toUpperCase()
    parts.push(key)
    
    return parts.join('+')
  }

  private findShortcut(key: string): Shortcut | undefined {
    return this.shortcuts.find(s => s.key === key)
  }

  // ========== 公共方法 ==========

  registerShortcut(shortcut: Omit<Shortcut, 'action'> & { action: () => void }): boolean {
    // 检查是否已存在
    const existingIndex = this.shortcuts.findIndex(s => s.key === shortcut.key)
    if (existingIndex !== -1) {
      // 更新现有快捷键的 action
      this.shortcuts[existingIndex].action = shortcut.action
      return true
    }
    
    this.shortcuts.push(shortcut as Shortcut)
    this.registeredKeys.add(shortcut.key)
    return true
  }

  // 注销快捷键
  unregisterShortcut(key: string): boolean {
    const index = this.shortcuts.findIndex(s => s.key === key)
    if (index !== -1) {
      this.shortcuts.splice(index, 1)
      this.registeredKeys.delete(key)
      return true
    }
    return false
  }

  getShortcutsByCategory(category?: string): Shortcut[] {
    if (category) {
      return this.shortcuts.filter(s => s.category === category)
    }
    return [...this.shortcuts]
  }

  getCategories(): string[] {
    return ['navigation', 'search', 'view', 'panels', 'other']
  }

  getCategoryName(category: string): string {
    const names: Record<string, string> = {
      navigation: '导航',
      search: '搜索',
      view: '视图',
      panels: '面板',
      other: '其他'
    }
    return names[category] || category
  }

  enable() {
    this.enabled = true
  }

  disable() {
    this.enabled = false
  }

  // ========== 注册面板快捷键 ==========

  registerPanelShortcuts(actions: {
    onDragon?: () => void
    onSector?: () => void
    onConfig?: () => void
    onBreath?: () => void
    onTrend?: () => void
    onFavorite?: () => void
    onRefresh?: () => void
    onHelp?: () => void
    onSearch?: () => void
  }) {
    if (actions.onDragon) {
      this.registerShortcut({
        key: 'Ctrl+D',
        description: '显示龙头面板',
        category: 'panels',
        action: actions.onDragon
      })
    }
    
    if (actions.onSector) {
      this.registerShortcut({
        key: 'Ctrl+S',
        description: '显示题材分析',
        category: 'panels',
        action: actions.onSector
      })
    }
    
    if (actions.onConfig) {
      this.registerShortcut({
        key: 'C',
        description: '显示配置面板',
        category: 'panels',
        action: actions.onConfig
      })
    }
    
    if (actions.onBreath) {
      this.registerShortcut({
        key: 'Ctrl+B',
        description: '显示龙息分析',
        category: 'panels',
        action: actions.onBreath
      })
    }
    
    if (actions.onTrend) {
      this.registerShortcut({
        key: 'Ctrl+T',
        description: '显示参数回测',
        category: 'panels',
        action: actions.onTrend
      })
    }

    if (actions.onFavorite) {
      this.registerShortcut({
        key: 'Ctrl+F',
        description: '显示自选股',
        category: 'panels',
        action: actions.onFavorite
      })
    }
    
    if (actions.onRefresh) {
      this.registerShortcut({
        key: 'F5',
        description: '刷新数据',
        category: 'view',
        action: actions.onRefresh
      })
    }
    
    if (actions.onHelp) {
      this.registerShortcut({
        key: 'F1',
        description: '显示/隐藏帮助',
        category: 'view',
        action: actions.onHelp
      })
      this.registerShortcut({
        key: '?',
        description: '显示帮助',
        category: 'other',
        action: actions.onHelp
      })
      this.registerShortcut({
        key: 'Shift+?',
        description: '显示帮助',
        category: 'other',
        action: actions.onHelp
      })
    }

    if (actions.onSearch) {
      this.registerShortcut({
        key: '/',
        description: '聚焦搜索框',
        category: 'search',
        action: actions.onSearch
      })
    }
  }

  // 获取所有快捷键（用于帮助面板）
  getAllShortcuts(): Shortcut[] {
    return [...this.shortcuts]
  }
}

export const keyboardService = new KeyboardService()
