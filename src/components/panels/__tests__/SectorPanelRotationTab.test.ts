import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// 题材轮动页签标题不渲染原始 rotationSpeed 浮点数（用户 2026-09-05 反馈）；
// 轮动视图内的轮动速度保留，但必须经 rotationSpeedText 格式化。
describe('SectorPanel 题材轮动页签', () => {
  const panel = readFileSync(
    join(process.cwd(), 'src', 'components', 'panels', 'SectorPanel.vue'),
    'utf8',
  )

  it('页签标题不渲染原始 rotationSpeed 数值', () => {
    expect(panel).not.toContain('>{{ rotationData.rotationSpeed }}%')
  })

  it('轮动视图内保留经格式化的轮动速度展示', () => {
    expect(panel).toContain('rotationSpeedText')
    expect(panel).toContain('轮动速度 {{ rotationSpeedText }}')
  })
})
