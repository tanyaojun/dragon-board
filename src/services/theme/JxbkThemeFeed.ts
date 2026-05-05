import { dataLayer } from '@/services/DataLayer'
import type { JxbkBlockData, JxbkStockData } from '@/types'

function finiteNumber(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function normalizeBlock(block: Partial<JxbkBlockData>): JxbkBlockData {
  return {
    code: String(block.code || block.name || '').trim(),
    name: String(block.name || block.code || '').trim(),
    strength: finiteNumber(block.strength),
    change: finiteNumber(block.change),
    mainNetInflow: finiteNumber(block.mainNetInflow),
    bigMoney300: finiteNumber(block.bigMoney300),
    institutionBuy: finiteNumber(block.institutionBuy),
    volumeRatio: finiteNumber(block.volumeRatio),
    ztCount: finiteNumber(block.ztCount),
  } as JxbkBlockData
}

export const jxbkThemeFeed = {
  getBlocks(limit?: number): JxbkBlockData[] {
    return dataLayer
      .getJxbkBlocksSorted?.(limit)
      .map(normalizeBlock)
      .filter((block) => block.code && block.name)
  },

  getBlockByCode(code: string): JxbkBlockData | undefined {
    const block = dataLayer.getJxbkBlock?.(code)
    return block ? normalizeBlock(block) : undefined
  },

  getStock(code: string): JxbkStockData | undefined {
    return dataLayer.getJxbkStock?.(code)
  },

  getStockMap(): Record<string, JxbkStockData> {
    return dataLayer.getJxbkStockMap?.() || {}
  },

  updateBlocks(blocks: Partial<JxbkBlockData>[]) {
    dataLayer.updateJxbkBlocks(blocks.map(normalizeBlock))
  },
}
