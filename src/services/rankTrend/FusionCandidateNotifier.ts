import { candidateJournalService } from '@/services/candidate/CandidateJournalService'
import type { CandidateJournalEntry, CandidateStatus, CandidateStockLike } from '@/services/candidate/types'
import { isFusionEntryCandidate } from './fusionStrategy'

const FUSION_STRATEGY_SOURCE = 'ranktrend_early_big_move_v3_lifecycle_fusion'

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
  ): Promise<unknown>
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
      if (!isFusionEntryCandidate(stock)) continue

      const code = normalizeCode(stock?.code)
      if (!code) continue

      const existing = await this.candidateJournal.getOpenCandidateForStock(code)
      if (existing) continue

      await this.candidateJournal.addCandidateFromStock(stock, {
        addToFavorites: true,
        source: FUSION_STRATEGY_SOURCE,
        statusOverride: 'triggered',
        signalsSnapshotPatch: {
          triggerMeta: {
            source: FUSION_STRATEGY_SOURCE,
            triggerType: 'auto',
            triggeredAt: this.now().toISOString(),
          },
        },
      })
    }
  }
}

export const fusionCandidateNotifier = new FusionCandidateNotifier()
