import { evaluateV5FusionEntry } from './v5FusionExecutionContract'

export function isFusionEntryCandidate(stock: any): boolean {
  return evaluateV5FusionEntry(stock).accepted
}
