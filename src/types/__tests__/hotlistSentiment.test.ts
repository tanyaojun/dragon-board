import { describe, expect, test } from 'vitest'

import { HOT_LIST_STAGE_LABELS } from '../hotlistSentiment'

// 词表逐字合同（code review Low 5）：后端 `STAGE_LABELS` / `STAGE_UNKNOWN_LABEL`
// （quant-board/backend/analysis/ranktrend/trend/display_status.py）是唯一来源，本文件
// 只做镜像；任一侧改词必须同批改另一侧 + 合同文档（docs/ranktrend/lifecycle-layering-contract.md）。
describe('HOT_LIST_STAGE_LABELS 词表逐字合同', () => {
  test('与后端 STAGE_LABELS / STAGE_UNKNOWN_LABEL 逐字一致', () => {
    expect(HOT_LIST_STAGE_LABELS).toEqual({
      ignition: '点火',
      expansion: '扩散',
      crowded: '拥挤',
      reversal: '反转',
      cooling: '冷却',
      unknown: '无阶段',
    })
  })

  test('不回潮已删除的 8 类 label', () => {
    const body = JSON.stringify(HOT_LIST_STAGE_LABELS)
    for (const legacy of ['主升确认', '点火观察', '强资确认', '新入观察', '高位拥挤', '资金背离', '转弱预警', '样本不足']) {
      expect(body).not.toContain(legacy)
    }
  })
})
