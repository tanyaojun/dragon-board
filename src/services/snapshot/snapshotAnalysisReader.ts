import type { SnapshotAnalysisEntry } from '../apiService'
import { apiService } from '../apiService'

export interface SnapshotAnalysisResult {
  ok: boolean
  analysis: Record<string, SnapshotAnalysisEntry>
}

/**
 * G4（2026-08-23 前后端分离）：读取后端持久化的快照 analyze 结果（snapshot_analysis），
 * 供**历史回放/对比**。当前帧仍保留 current_frame 实时 analyze（前后端一致），不在此替换。
 *
 * fail-visible：后端读库不可用（离线/旧缓存/未接 MongoDB）时返回 { ok:false, analysis:{} }，
 * 不中断调用方，由调用方自行决定降级（如回退实时 analyze）。
 */
export async function loadSnapshotAnalysis(
  datasetId: string,
  snapshotId: string,
  codes?: string[],
): Promise<SnapshotAnalysisResult> {
  try {
    const response = await apiService.getSnapshotAnalysis(datasetId, snapshotId, codes)
    return {
      ok: Boolean(response?.ok),
      analysis: (response?.analysis as Record<string, SnapshotAnalysisEntry> | undefined) ?? {},
    }
  } catch (error) {
    return { ok: false, analysis: {} }
  }
}
