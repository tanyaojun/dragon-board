import { normalizeStockCode } from '@/utils/common'
import { apiService } from '../apiService'
import { dataLayer } from '../DataLayer'
import type { LimitUpItem } from './types'

type LimitUpApi = {
  getLimitUp: () => Promise<any>
}

type LimitUpDataLayer = {
  updateLimitUpData?: (updates: LimitUpUpdate[]) => void
}

export interface LimitUpUpdate {
  code: string
  reason: string
  isNew: boolean
  firstZtTime: string
  lastZtTime: string
  boardHeight: number
  highDays: number
}

export function mapLimitUpItems(items: LimitUpItem[]): LimitUpUpdate[] {
  return items.map((item) => ({
    code: normalizeStockCode(item.code),
    reason: item.reason_type,
    isNew: item.is_new === 1,
    firstZtTime: item.first_limit_up_time,
    lastZtTime: item.last_limit_up_time,
    boardHeight: item.continue_day,
    highDays: item.high_days,
  }))
}

export async function loadLimitUpData(
  dependencies: {
    api?: LimitUpApi
    dataLayer?: LimitUpDataLayer
  } = {},
): Promise<void> {
  const api = dependencies.api || apiService
  const targetDataLayer = dependencies.dataLayer || dataLayer

  try {
    const response = await api.getLimitUp()
    if (!response?.data?.info) return

    targetDataLayer.updateLimitUpData?.(mapLimitUpItems(response.data.info))
  } catch (error) {
    console.warn('[DataLoader] 加载涨停池数据失败:', error)
  }
}
