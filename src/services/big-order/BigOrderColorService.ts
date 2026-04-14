// src/services/big-order/BigOrderColorService.ts
import type { BigOrderItem, BigOrderColorRule } from '@/types/big-order'
import { BIG_ORDER_COLORS } from '@/types/big-order'
import { MARKER_THRESHOLDS } from '@/config/constants'

export class BigOrderColorService {
  private static instance: BigOrderColorService

  // 颜色定义
  public readonly colors = { ...BIG_ORDER_COLORS }

  // 颜色规则（按优先级从高到低）
  public readonly rules: BigOrderColorRule[] = [
    {
      name: '主动卖无标记',
      priority: 1,
      condition: (o: BigOrderItem) => o.type === 4 && !o.fundMarker,
      color: BIG_ORDER_COLORS.sell,
      isBold: false
    },
    {
      name: '主动买无标记',
      priority: 2,
      condition: (o: BigOrderItem) => o.type === 2 && !o.fundMarker,
      color: BIG_ORDER_COLORS.buy,
      isBold: false
    },
    {
      name: '超大单',
      priority: 3,
      condition: (o: BigOrderItem) => 
        !o.fundMarker && (o.amount / 10000) > MARKER_THRESHOLDS.SUPER_BIG,
      color: BIG_ORDER_COLORS.superBig,
      isBold: false
    },
    {
      name: '点火',
      priority: 4,
      condition: (o: BigOrderItem) => o.fundMarker === '点火',
      color: BIG_ORDER_COLORS.ignite,
      isBold: true
    },
    {
      name: '砸盘',
      priority: 5,
      condition: (o: BigOrderItem) => o.fundMarker === '砸盘',
      color: BIG_ORDER_COLORS.smash,
      isBold: true
    },
    {
      name: '买活跃',
      priority: 6,
      condition: (o: BigOrderItem) => o.buyMarker === '买活跃',
      color: BIG_ORDER_COLORS.buyActive,
      isBold: false
    },
    {
      name: '承接好',
      priority: 7,
      condition: (o: BigOrderItem) => o.buyMarker === '承接好',
      color: BIG_ORDER_COLORS.sellActive,
      isBold: false
    }
  ]

  private constructor() {}

  static getInstance(): BigOrderColorService {
    if (!BigOrderColorService.instance) {
      BigOrderColorService.instance = new BigOrderColorService()
    }
    return BigOrderColorService.instance
  }

  /**
   * 获取订单的颜色规则
   */
  getColorRule(order: BigOrderItem): BigOrderColorRule | null {
    // 按优先级查找第一个匹配的规则
    const sortedRules = [...this.rules].sort((a, b) => a.priority - b.priority)
    return sortedRules.find(rule => rule.condition(order)) || null
  }

  /**
   * 获取订单颜色
   */
  getOrderColor(order: BigOrderItem): string {
    const rule = this.getColorRule(order)
    return rule?.color || this.colors.default
  }

  /**
   * 判断订单是否应显示为粗体
   */
  isBold(order: BigOrderItem): boolean {
    const rule = this.getColorRule(order)
    return rule?.isBold || false
  }

  /**
   * 获取统计标签颜色
   */
  getStatisticsColor(
    type: 'buy' | 'sell' | 'netBuy' | 'ignite' | 'smash' | 'buyActive' | 'sellActive', 
    value?: number
  ): string {
    switch (type) {
      case 'buy':
        return this.colors.buy
      case 'sell':
        return this.colors.sell
      case 'netBuy':
        return value && value >= 0 ? this.colors.buy : this.colors.sell
      case 'ignite':
        return this.colors.ignite
      case 'smash':
        return this.colors.smash
      case 'buyActive':
        return this.colors.buyActive
      case 'sellActive':
        return this.colors.sellActive
      default:
        return this.colors.default
    }
  }

  /**
   * 获取CSS样式对象
   */
  getOrderStyle(order: BigOrderItem): Record<string, any> {
    const rule = this.getColorRule(order)
    return {
      color: rule?.color || this.colors.default,
      fontWeight: rule?.isBold ? 'bold' : 'normal'
    }
  }
}