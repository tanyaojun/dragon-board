import type { FusionStrategyProjection } from '@/types/fusionStrategyProjection'

export interface CandidatePoolOpenPayload {
  candidateId?: string
  stockCode?: string
  liveProjection?: FusionStrategyProjection | null
}
