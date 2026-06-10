import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type { CandidateJournalEntry, CandidateStatus, CandidateStockLike } from '@/services/candidate/types'
import { evaluateV5FusionEntry, V5_FUSION_DEFAULTS } from './v5FusionExecutionContract'

const FUSION_STRATEGY_SOURCE = 'ranktrend_early_big_move_v3_lifecycle_fusion'
const FEISHU_ENDPOINT = '/api/notifications/jump-signal'
const FEISHU_SOURCE = 'ranktrend-fusion-candidate-pool'
const FEISHU_TIMEOUT_MS = 8000

interface AddCandidateResult {
  created: boolean
}

interface CandidateJournalLike {
  getOpenCandidateForStock(stockCode: string): Promise<CandidateJournalEntry | null>
  addCandidateFromStock(
    stock: CandidateStockLike,
    options: {
      addToFavorites: boolean
      source: string
      statusOverride: CandidateStatus
      signalsSnapshotPatch: Record<string, unknown>
    },
  ): Promise<AddCandidateResult>
}

interface FusionCandidateNotifierDeps {
  candidateJournal?: CandidateJournalLike
  now?: () => Date
}

function normalizeCode(code: unknown): string {
  return String(code ?? '').trim()
}

export class FusionCandidateNotifier {
  private candidateJournal: CandidateJournalLike
  private now: () => Date

  constructor(deps: FusionCandidateNotifierDeps = {}) {
    this.candidateJournal = deps.candidateJournal ?? candidateJournalService
    this.now = deps.now ?? (() => new Date())
  }

  async process(stocks: CandidateStockLike[]): Promise<void> {
    for (const stock of stocks) {
      const entry = evaluateV5FusionEntry(stock)
      if (!entry.accepted) continue

      const code = normalizeCode(stock?.code)
      if (!code) continue

      const existing = await this.candidateJournal.getOpenCandidateForStock(code)
      if (existing) continue

      const result = await this.candidateJournal.addCandidateFromStock(stock, {
        addToFavorites: true,
        source: FUSION_STRATEGY_SOURCE,
        statusOverride: 'triggered',
        signalsSnapshotPatch: {
          triggerMeta: {
            source: FUSION_STRATEGY_SOURCE,
            baseline: 'early_big_move_v5',
            triggerType: 'auto',
            triggeredAt: this.now().toISOString(),
            executionCandidateTier: entry.candidateTier,
            lifecycleAction: entry.lifecycleAction,
            jumpConfidence: entry.jumpConfidence,
            minJumpConfidence: V5_FUSION_DEFAULTS.minJumpConfidence,
            blockedReasons: entry.blockedReasons,
          },
        },
      })

      if (!result.created) continue

      void this.pushFeishuEvent(stock)
    }
  }

  private async pushFeishuEvent(stock: CandidateStockLike): Promise<void> {
    if (typeof globalThis.fetch !== 'function') return

    const rankTrend = stock.rankTrend
    const candidateTier = evaluateV5FusionEntry(stock).candidateTier
    const lifecycleAction = String(rankTrend?.cycle?.decision?.action || '').trim()
    const reason = candidateTier ? `${candidateTier} 命中，已自动写入候选池` : 'fusion 策略命中，已自动写入候选池'

    await globalThis.fetch(FEISHU_ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      signal: AbortSignal.timeout(FEISHU_TIMEOUT_MS),
      body: JSON.stringify({
        source: FEISHU_SOURCE,
        events: [
          {
            code: normalizeCode(stock?.code),
            name: String(stock?.name || ''),
            signalType: 'strategy_candidate',
            signalLabel: 'Fusion 候选池触发',
            price: Number(stock?.price || stock?.lastTradePrice || 0),
            changePct: Number(stock?.change || 0),
            reason,
            candidateTier,
            lifecycleAction,
            confidence: Number(rankTrend?.jump?.confidence ?? 0),
            timestamp: this.now().getTime(),
          },
        ],
      }),
    }).catch((error) => {
      console.warn(
        '[FusionCandidateNotifier] 飞书推送失败:',
        error instanceof Error ? error.message : String(error),
      )
    })
  }
}

export const fusionCandidateNotifier = new FusionCandidateNotifier()
