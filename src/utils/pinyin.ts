import { debugLog } from '@/utils/logger'
// src/utils/pinyin.ts

/**
 * 拼音工具 - 使用 pinyin-pro 库
 * 
 * 依赖：已在 index.html 中引入 pinyin-pro
 * CDN: https://cdn.jsdelivr.net/npm/pinyin-pro@3.19.0/dist/index.js
 */

// 声明全局变量
declare global {
  interface Window {
    pinyinPro: any
  }
}

// LRU缓存
class LRUCache<K, V> {
  private cache = new Map<K, V>()
  private maxSize: number

  constructor(maxSize: number) {
    this.maxSize = maxSize
  }

  get(key: K): V | undefined {
    const value = this.cache.get(key)
    if (value !== undefined) {
      // 重新插入以更新顺序
      this.cache.delete(key)
      this.cache.set(key, value)
    }
    return value
  }

  set(key: K, value: V): void {
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value
      if (firstKey !== undefined) {
        this.cache.delete(firstKey)
      }
    }
    this.cache.set(key, value)
  }

  clear(): void {
    this.cache.clear()
  }
}

export class PinyinUtils {
  private static cache = new LRUCache<string, string>(1000)
  private static isReady = false

  /**
   * 检查拼音库是否可用
   */
  static isAvailable(): boolean {
    return !!(window.pinyinPro?.pinyin)
  }

  /**
   * 等待拼音库加载
   */
  static async waitForLibrary(timeout = 5000): Promise<boolean> {
    if (this.isAvailable()) {
      this.isReady = true
      return true
    }

    return new Promise((resolve) => {
      const startTime = Date.now()
      
      const checkInterval = setInterval(() => {
        if (this.isAvailable()) {
          clearInterval(checkInterval)
          this.isReady = true
          debugLog('[PinyinUtils] ✅ 拼音库加载成功')
          resolve(true)
        } else if (Date.now() - startTime > timeout) {
          clearInterval(checkInterval)
          console.warn('[PinyinUtils] ⚠️ 拼音库加载超时，将使用降级方案')
          resolve(false)
        }
      }, 100)
    })
  }

  /**
   * 获取拼音首字母（带缓存）
   */
  static getPinyinInitials(name: string): string {
    if (!name || name === '-' || name === 'null' || name === 'undefined') {
      return ''
    }

    // 检查缓存
    const cached = this.cache.get(name)
    if (cached !== undefined) {
      return cached
    }

    let initials = ''

    // 使用 pinyin-pro 库
    if (this.isAvailable()) {
      try {
        const result = window.pinyinPro.pinyin(name, {
          toneType: 'none',
          pattern: 'first',
          type: 'array'
        })
        
        if (result && Array.isArray(result)) {
          initials = result.join('').toUpperCase()
        }
      } catch (error) {
        console.warn('[PinyinUtils] 拼音转换失败:', error)
        initials = this.simplePinyinInitials(name)
      }
    } else {
      // 降级方案
      initials = this.simplePinyinInitials(name)
    }

    // 存入缓存
    this.cache.set(name, initials)
    return initials
  }

  /**
   * 简单拼音首字母转换（降级方案）
   */
  private static simplePinyinInitials(name: string): string {
    // 简单的映射表（只包含常用字）
    const simpleMap: Record<string, string> = {
      '阿': 'A', '巴': 'B', '财': 'C', '达': 'D', '恩': 'E', '发': 'F',
      '哈': 'H', '基': 'J', '卡': 'K', '拉': 'L',
      '那': 'N', '欧': 'O', '帕': 'P', '奇': 'Q', '然': 'R', '萨': 'S',
      '塔': 'T', '瓦': 'W', '西': 'X', '亚': 'Y', '在': 'Z',
      
      // 常用姓氏
      '张': 'Z', '王': 'W', '李': 'L', '刘': 'L', '陈': 'C', '杨': 'Y', 
      '赵': 'Z', '黄': 'H', '周': 'Z', '吴': 'W', '徐': 'X', '孙': 'S',
      '马': 'M', '朱': 'Z', '胡': 'H', '郭': 'G', '林': 'L', '何': 'H',
      '高': 'G', '郑': 'Z', '罗': 'L',
      
      // 股票常用词
      '科': 'K', '技': 'J', '股': 'G', '份': 'F', '有': 'Y', '限': 'X',
      '公': 'G', '司': 'S', '集': 'J', '团': 'T', '控': 'K', '实': 'S',
      '业': 'Y', '投': 'T', '资': 'Z', '金': 'J', '银': 'Y', '行': 'H',
      '电': 'D', '子': 'Z', '通': 'T', '信': 'X', '软': 'R', '件': 'J',
      '网': 'W', '络': 'L', '数': 'S', '字': 'Z', '智': 'Z', '能': 'N',
      '机': 'J', '器': 'Q', '人': 'R', '新': 'X', '源': 'Y', '车': 'C'
    }

    let result = ''
    for (let i = 0; i < name.length; i++) {
      const char = name[i]
      if (simpleMap[char]) {
        result += simpleMap[char]
      } else if (char >= 'A' && char <= 'Z') {
        result += char
      } else if (char >= 'a' && char <= 'z') {
        result += char.toUpperCase()
      }
    }
    return result
  }

  /**
   * 匹配拼音
   */
  static matchPinyin(name: string, keyword: string): boolean {
    if (!name || !keyword) return false
    
    const initials = this.getPinyinInitials(name)
    if (!initials) return false
    
    const upperKeyword = keyword.toUpperCase()
    
    return initials === upperKeyword ||
           initials.includes(upperKeyword) ||
           initials.startsWith(upperKeyword)
  }

  /**
   * 清除缓存
   */
  static clearCache(): void {
    this.cache.clear()
  }

  /**
   * 获取版本信息
   */
  static getVersion(): string {
    if (this.isAvailable()) {
      return window.pinyinPro?.version || 'unknown'
    }
    return 'simple (fallback)'
  }
}

// 自动等待拼音库加载
PinyinUtils.waitForLibrary().then(loaded => {
  if (loaded) {
    debugLog(`[PinyinUtils] 📚 拼音库已就绪，版本: ${PinyinUtils.getVersion()}`)
  } else {
    debugLog('[PinyinUtils] 📚 使用降级拼音方案')
  }
})
