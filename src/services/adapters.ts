// src/services/adapters.ts - 优化版

import { apiService } from './apiService'
import type { PlatformData } from '../types/core'

const logData = (platform: string, data: any) => {
  console.log(`[${platform}] 原始数据:`, {
    type: typeof data,
    isArray: Array.isArray(data),
    length: data?.length,
    sample: data?.[0],
  })
}

// 统一的请求配置
const REQUEST_CONFIG = {
  context: 'platform' as const,
  priority: 'high' as const,
  retries: 2,
}

export const Adapters = {
  // 东方财富
  eastmoney: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.post<any>(
          '/api/eastmoney/hot',
          {},
          {
            // ✅ 传空对象
            ...REQUEST_CONFIG,
          },
        )
        logData('EastMoney', data?.data)
        return data?.data || []
      } catch (error) {
        console.warn('[EastMoney] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item, index) => ({
        rank: index + 1,
        code: String(item.sc || '')
          .replace(/[^0-9]/g, '')
          .padStart(6, '0'),
        name: item.sn || '-',
        source: 'eastmoney',
        rawData: item,
      }))
    },
  },

  // 同花顺
  ths: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/ths/hot', REQUEST_CONFIG)
        logData('THS', data?.data?.stock_list)
        return data?.data?.stock_list || []
      } catch (error) {
        console.warn('[THS] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item) => ({
        rank: item.order || 999,
        code: String(item.code || '')
          .replace(/[^0-9]/g, '')
          .padStart(6, '0'),
        name: item.name || '-',
        change: parseFloat(item.rate) || 0,
        source: 'ths',
        rawData: item,
      }))
    },
  },

  // 开盘啦
  kpl: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/kpl/hot', REQUEST_CONFIG)
        logData('KPL', data)
        const list = data?.List || data?.list || data?.data || []
        return list
      } catch (error) {
        console.warn('[KPL] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data
        .map((item, index) => {
          if (Array.isArray(item) && item.length >= 2) {
            return {
              rank: parseInt(item[4]) || index + 1,
              code: String(item[0] || '')
                .replace(/[^0-9]/g, '')
                .padStart(6, '0'),
              name: item[1] || '-',
              change: parseFloat(item[2]) || 0,
              source: 'kpl',
              rawData: item,
            }
          }
          return null
        })
        .filter(Boolean) as PlatformData[]
    },
  },

  // 通达信
  tdx: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.post<any>('/api/tdx/hot', [{ listType: '0', cycle: '0' }], {
          context: 'platform',
          priority: 'high',
          retries: 2,
          timeout: 8000,
        })
        console.log('[TDX] 原始数据:', data)
        return data || []
      } catch (error) {
        console.warn('[TDX] API失败:', error)
        return []
      }
    },

    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []

      const result: PlatformData[] = []
      // 通达信数据格式：前3个是元数据，从索引3开始才是股票数据
      for (let i = 3; i < data.length; i++) {
        const item = data[i]
        if (Array.isArray(item) && item.length >= 11) {
          result.push({
            rank: parseInt(item[10]) || i - 2,
            code: String(item[1] || '')
              .replace(/[^0-9]/g, '')
              .padStart(6, '0'),
            name: item[2] || '-',
            change: parseFloat(item[3]) || 0,
            source: 'tdx',
            rawData: item,
          })
        }
      }
      return result
    },
  },

  // 雪球
  xueqiu: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/xueqiu/hot', REQUEST_CONFIG)
        logData('Xueqiu', data?.data?.items)
        return data?.data?.items || []
      } catch (error) {
        console.warn('[Xueqiu] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item, index) => ({
        rank: index + 1,
        code: String(item.code || item.symbol || '')
          .replace(/[^0-9]/g, '')
          .padStart(6, '0'),
        name: item.name || '-',
        change: parseFloat(item.percent) || 0,
        source: 'xueqiu',
        rawData: item,
      }))
    },
  },

  // 财联社
  cls: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/cls/hot', REQUEST_CONFIG)
        logData('CLS', data?.data)
        return data?.errno === 0 ? data.data || [] : []
      } catch (error) {
        console.warn('[CLS] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item, index) => {
        const stock = item.stock || {}
        return {
          rank: index + 1,
          code: String(stock.StockID || '')
            .replace(/[^0-9]/g, '')
            .padStart(6, '0'),
          name: stock.name || '-',
          change: parseFloat(stock.RiseRange) || 0,
          source: 'cls',
          rawData: item,
        }
      })
    },
  },

  // 淘股吧
  tgb: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/tgb/hot', REQUEST_CONFIG)
        logData('TGB', data?.dto)
        return data?.dto || []
      } catch (error) {
        console.warn('[TGB] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item) => ({
        rank: item.ranking || 999,
        code: String(item.fullCode || '')
          .replace(/[^0-9]/g, '')
          .padStart(6, '0'),
        name: item.stockName || '-',
        popularValue: item.popularValue || 0,
        continuenum: item.continuenum || 0,
        linkingBoard: item.linkingBoard || '',
        reason: item.reason || '',
        source: 'tgb',
        rawData: item,
      }))
    },
  },

  // 大智慧
  dzh: {
    async getHotList(): Promise<any[]> {
      try {
        const data = await apiService.get<any>('/api/dzh/hot', REQUEST_CONFIG)
        logData('DZH', data?.result)
        return data?.result || []
      } catch (error) {
        console.warn('[DZH] API失败:', error)
        return []
      }
    },
    format(data: any[]): PlatformData[] {
      if (!Array.isArray(data)) return []
      return data.map((item, index) => {
        const codeKey = Object.keys(item)[0]
        const code = codeKey ? codeKey.replace(/[^0-9]/g, '') : ''
        return {
          rank: index + 1,
          code: code.padStart(6, '0'),
          name: '-',
          popularValue: item[codeKey] || 0,
          source: 'dzh',
          rawData: item,
        }
      })
    },
  },
}
