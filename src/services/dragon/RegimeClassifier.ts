import { dataLayer } from '../../services/DataLayer'
import type { ReviewFrame, ReviewRegime } from './types'

function average(values: number[]): number {
  if (!values.length) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

export class RegimeClassifier {
  classify(frames: ReviewFrame[]): ReviewRegime {
    const latest = frames[frames.length - 1]
    const rotation = dataLayer.getCurrentRotation?.()
    const zhabanRate = latest?.marketStats.zhabanRate || 0
    const ztCount = latest?.marketStats.ztCount || 0
    const hotConcentration = this.calculateHotConcentration(frames)
    const mainLineCount = rotation?.summary?.mainLineCount || rotation?.mainLines?.length || 0
    const rotationSpeed = rotation?.rotationSpeed || 0
    const persistentMainLines =
      rotation?.mainLines?.filter((line) => (line.persistentDays || 0) >= 2).length || 0
    const sentimentPhase = latest?.sentiment.phaseName || latest?.sentiment.phase

    if (zhabanRate >= 32 || sentimentPhase === '退潮' || sentimentPhase === 'retreat') {
      return 'DISTRIBUTION_DECAY'
    }

    if (mainLineCount >= 2 && hotConcentration < 0.45) {
      return 'MULTI_FRONT_CONTEST'
    }

    if (persistentMainLines >= 1 && ztCount >= 30 && zhabanRate <= 20) {
      return 'MAINLINE_ADVANCE'
    }

    if (rotationSpeed >= 55 && mainLineCount === 0) {
      return 'ROTATION_NO_CORE'
    }

    if ((sentimentPhase === '冰点' || sentimentPhase === 'ice' || sentimentPhase === '启动' || sentimentPhase === 'start') && ztCount <= 25) {
      return 'REPAIR_ATTEMPT'
    }

    return hotConcentration >= 0.55 ? 'HIGH_LEVEL_HUG' : 'MULTI_FRONT_CONTEST'
  }

  private calculateHotConcentration(frames: ReviewFrame[]): number {
    const samples = frames
      .filter((frame) => frame.hotlist.length > 0)
      .map((frame) => {
        const head = frame.hotlist.slice(0, 10)
        const themeBuckets = new Map<string, number>()
        head.forEach((item) => {
          const key = item.mainTheme || item.themes?.[0]?.name || 'unknown'
          themeBuckets.set(key, (themeBuckets.get(key) || 0) + 1)
        })
        const max = Math.max(...themeBuckets.values(), 0)
        return head.length > 0 ? max / head.length : 0
      })

    return average(samples)
  }
}

export const regimeClassifier = new RegimeClassifier()
