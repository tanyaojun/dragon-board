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
    expect(source).not.toContain('板块异动')
  })
})
