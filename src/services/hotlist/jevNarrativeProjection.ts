// src/services/hotlist/jevNarrativeProjection.ts
// jev 投影纯函数（消费方：热榜情绪面板 HotlistEmotionPanel）。
// 只做无副作用投影：EOD 语料覆盖度角标。
// fail-visible：任何缺失返回 null/空结构，不伪造档位、0 分或概率分布。
// 结论唯一来源 = QuantBoard 后端 jev 轨道（hotlist_jev_sentiment）落库文档，本模块零计算补齐。
// 2026-11-03：JevNarrativePanel 面板退役，其专属投影（叙事分段/锚分位/置信/拥挤时间线/
// 层统计/窗口裁剪/涨停排序）随面板一并删除（历史实现见 git）。

import type { HotlistJevFrameCoverage } from '@/types/hotlistJev'

/** 日级 EOD 语料覆盖度角标（2026-10-22）：缺失位置与类型分开披露，不折叠成「缺 N 帧」。 */
export interface JevCoverageHintInput {
  frameCoverage?: HotlistJevFrameCoverage | null
  evidenceRawUnavailable?: boolean | null
}

export function formatJevCoverageHint(
  input: JevCoverageHintInput | null | undefined,
): string | null {
  if (input?.evidenceRawUnavailable) return '历史证据未落档'
  const cov = input?.frameCoverage
  if (!cov) return null
  const frameCount = cov.frameCount
  const expected = cov.expectedCount
  if (frameCount === 0) return `EOD 无帧（0/${expected ?? '--'}）`
  const bits: string[] = []
  if (cov.hasCloseFrame === false) bits.push(`缺收盘帧（末帧 ${cov.lastSlot ?? '--'}）`)
  const missing = cov.missingSlots ?? []
  if (missing.length) bits.push(`缺槽位 ${missing.join('、')}`)
  const empty = cov.emptyEvidenceSlots ?? []
  if (empty.length) {
    const names = empty.slice(0, 3).map((item) => item.slot).filter(Boolean)
    const suffix = empty.length > names.length ? ' 等' : ''
    bits.push(`空证据 ${empty.length} 帧${names.length ? `（${names.join('、')}${suffix}）` : ''}`)
  }
  if (!bits.length) return null
  return frameCount != null
    ? `覆盖 ${frameCount}/${expected ?? '--'}：${bits.join('；')}`
    : bits.join('；')
}
