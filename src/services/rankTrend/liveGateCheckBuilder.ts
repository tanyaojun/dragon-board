import type { RankTrendLiveGateCheck } from '@/types/rankTrendLiveStrategy'

export function buildLiveGateCheck(check: RankTrendLiveGateCheck): RankTrendLiveGateCheck {
  return check
}

export function selectFirstBlockingCheck(
  checks: RankTrendLiveGateCheck[],
): RankTrendLiveGateCheck | undefined {
  return checks.find((check) => check.status === 'fail' && check.hardBlock)
}
