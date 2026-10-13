import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('HotStockEventMonitorPanel copy', () => {
  it('labels the second stock page as TDX self-selected stocks', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/panels/HotStockEventMonitorPanel.vue'),
      'utf8',
    )

    expect(source).toContain('TDX自选股')
    expect(source).not.toContain('其他个股')
  })

  it('labels the third page as monitored TDX block files with checkboxes', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/panels/HotStockEventMonitorPanel.vue'),
      'utf8',
    )

    expect(source).toContain('监控板块')
    expect(source).toContain('板块文件')
    expect(source).toContain('selectedTdxBlockFiles')
    expect(source).toContain('setSelectedTdxBlockFiles')
    expect(source).not.toContain("label: '板块'")
    // 2026-10-13 用户裁决：新增“板块异动”展示区（本地概念聚合 + 选股宝板块事件），
    // 与第三页“监控板块”（TDX 板块文件管理）职责不同、文案并存
    expect(source).toContain('板块异动')
  })
})
