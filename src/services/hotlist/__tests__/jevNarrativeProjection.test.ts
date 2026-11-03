// jev 投影纯函数测试（fail-visible 合同：缺失不伪造、覆盖度如实披露）
// 2026-11-03：JevNarrativePanel 面板退役，面板专属投影（叙事分段/锚分位/置信/
// 拥挤时间线/层统计/窗口裁剪/涨停排序）测试随实现一并删除，只保留存留消费方的函数。
import { describe, expect, test } from 'vitest'

import { formatJevCoverageHint } from '@/services/hotlist/jevNarrativeProjection'

describe('formatJevCoverageHint 覆盖度角标', () => {
  test('缺槽位与空证据分开计数，不折叠成「缺 N 帧」', () => {
    const hint = formatJevCoverageHint({
      frameCoverage: {
        frameCount: 10, expectedCount: 10, hasCloseFrame: true,
        missingSlots: ['09:30', '10:00'],
        emptyEvidenceSlots: [
          { slot: '10:30', reason: 'rows_empty' },
          { slot: '11:00', reason: 'snapshot_missing' },
          { slot: '11:30', reason: 'unknown' },
        ],
      },
    })
    expect(hint).toContain('缺槽位 09:30、10:00')
    expect(hint).toContain('空证据 3 帧')
    expect(hint).not.toContain('缺 5 帧')
  })

  test('缺收盘帧/无帧/存量未落档/全覆盖', () => {
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 9, expectedCount: 10, hasCloseFrame: false, lastSlot: '14:30' },
    })).toBe('覆盖 9/10：缺收盘帧（末帧 14:30）')
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 0, expectedCount: 10, hasCloseFrame: false,
                       missingSlots: ['09:30', '10:00'] },
    })).toBe('EOD 无帧（0/10）')
    expect(formatJevCoverageHint({ evidenceRawUnavailable: true })).toBe('历史证据未落档')
    expect(formatJevCoverageHint({
      frameCoverage: { frameCount: 10, expectedCount: 10, hasCloseFrame: true },
    })).toBeNull()
    expect(formatJevCoverageHint({})).toBeNull()
  })

  test('frameCount 缺失但有缺失位时：不伪造覆盖前缀，只拼缺失位（fail-visible）', () => {
    expect(formatJevCoverageHint({
      frameCoverage: { hasCloseFrame: true, missingSlots: ['10:00'] },
    } as never)).toBe('缺槽位 10:00')
  })
})
