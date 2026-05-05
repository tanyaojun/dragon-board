import { dataLayer } from '@/services/DataLayer'
import { apiService } from '@/services/apiService'
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
  async refreshBlocks(options: { force?: boolean; limit?: number } = {}): Promise<JxbkBlockData[]> {
    const data = await apiService.getHotBlockList(
      { st: options.limit || 20 },
      { force: options.force === true },
    )
    const blocks = Array.isArray(data?.list)
      ? data.list
          .map((item: any[]) =>
            normalizeBlock({
              code: item?.[0],
              name: item?.[1],
              strength: item?.[2],
              change: item?.[3],
              mainNetInflow: item?.[6],
              bigMoney300: item?.[12],
              institutionBuy: item?.[14],
              volumeRatio: item?.[9],
              ztCount: 0,
            }),
          )
          .filter((block: JxbkBlockData) => block.code && block.name && !block.name.includes('ST'))
      : []
    this.updateBlocks(blocks)
    return blocks
  },

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
