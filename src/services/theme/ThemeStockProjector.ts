import type {
  ThemeExposureProjection,
  ThemeFactorSnapshot,
  ThemeSourceContext,
  ThemeStockExposure,
  ThemeStockRole,
} from './types'
import { clamp, round, toFiniteNumber } from './utils'

const MAX_THEME_CONTRIBUTION = 18

function roleFor(
  code: string,
  stock: ThemeSourceContext['stocks'][number] | undefined,
  factor: ThemeFactorSnapshot,
  context: ThemeSourceContext,
): ThemeStockRole {
  const leadStatus = String((stock as any)?.leadStatus || '')
  if (leadStatus.includes('龙')) return 'leader'
  // 热度阈值（70/45/20）消费 heatLevel 相对分（0-100，后端 rank 百分位）。
  // 注意 JS 陷阱：null < 20 === true，必须显式 != null；缺失热度只按涨跌判定 noise。
  const heat = factor.heatLevel
  if (heat != null && heat >= 70 && toFiniteNumber(stock?.change) >= 5) return 'core'
  if (heat != null && heat >= 45 && toFiniteNumber(stock?.change) > 0) return 'follower'
  if ((heat != null && heat < 20) || toFiniteNumber(stock?.change) < -5) return 'noise'
  return 'independent'
}

function roleScore(role: ThemeStockRole, stock: ThemeSourceContext['stocks'][number] | undefined): number {
  const change = toFiniteNumber(stock?.change)
  const leadTimes = toFiniteNumber((stock as any)?.leadTimes)
  if (role === 'leader') return clamp(82 + Math.min(12, leadTimes * 4) + Math.max(0, change - 8))
  if (role === 'core') return clamp(68 + Math.max(0, change))
  if (role === 'follower') return clamp(52 + Math.max(0, change) * 0.8)
  if (role === 'independent') return 34
  return 12
}

function sourceFor(factor: ThemeFactorSnapshot, stockThemeIds: string[]): ThemeStockExposure['source'] {
  if (factor.source === 'mixed') return 'mixed'
  return stockThemeIds.includes(factor.themeId) ? 'static' : 'realtime'
}

function reasonsFor(factor: ThemeFactorSnapshot, role: ThemeStockRole): string[] {
  const reasons: string[] = []
  if (factor.rotationState === 'mainline') reasons.push('题材处于主线')
  else if (factor.rotationState === 'inflow') reasons.push('题材资金流入')
  else if (factor.rotationState === 'quick') reasons.push('题材快速轮动')
  if ((factor.heatLevel ?? 0) >= 70) reasons.push('题材热度强')
  if (factor.leadershipScore >= 55) reasons.push('题材有龙头带动')
  if (factor.correlationScore >= 65) reasons.push('板块联动较强')
  if (factor.crowdingRisk >= 55) reasons.push('题材拥挤风险偏高')
  if (role === 'leader') reasons.push('个股是题材龙头')
  if (role === 'core') reasons.push('个股是题材核心跟随')
  return reasons
}

function buildExposure(
  code: string,
  factor: ThemeFactorSnapshot,
  context: ThemeSourceContext,
  stockByCode: Map<string, ThemeSourceContext['stocks'][number]>,
): ThemeStockExposure | null {
  const stock = stockByCode.get(code)
  const stockThemeIds = context.stockThemes.get(code) || []
  const role = roleFor(code, stock, factor, context)
  const stockRoleScore = roleScore(role, stock)
  const riskPenalty = factor.crowdingRisk >= 70 ? 8 : factor.crowdingRisk >= 50 ? 4 : 0
  const exposureWeight =
    role === 'leader' ? 1 : role === 'core' ? 0.82 : role === 'follower' ? 0.62 : role === 'independent' ? 0.38 : 0.15
  const themeContribution = clamp(
    // 热度分量消费 heatLevel 相对分；加权合成项缺失→0（不伪装，仅参与加权）
    round(((factor.heatLevel ?? 0) * 0.1 + stockRoleScore * 0.08 + factor.persistenceScore * 0.03 - riskPenalty) * exposureWeight, 1),
    0,
    MAX_THEME_CONTRIBUTION,
  )

  if (role === 'noise' && themeContribution < 1) return null

  return {
    code,
    themeId: factor.themeId,
    themeName: factor.themeName,
    exposureWeight: round(exposureWeight, 2),
    source: sourceFor(factor, stockThemeIds),
    themeScore: factor.heatLevel,
    role,
    roleScore: stockRoleScore,
    themeContribution,
    riskPenalty,
    reasons: reasonsFor(factor, role),
    qualityFlags: factor.qualityFlags,
  }
}

export function projectThemeStockExposures(
  context: ThemeSourceContext,
  factors: ThemeFactorSnapshot[],
): ThemeExposureProjection {
  const byCode = new Map<string, ThemeStockExposure[]>()
  const byTheme = new Map<string, ThemeStockExposure[]>()
  const stockByCode = new Map(context.stocks.map((s) => [s.code, s]))

  factors.forEach((factor) => {
    const stockCodes = context.themeStocks.get(factor.themeId) || []
    const exposures = stockCodes
      .map((code) => buildExposure(code, factor, context, stockByCode))
      .filter((exposure): exposure is ThemeStockExposure => exposure !== null)
      .sort(
        (left, right) =>
          right.themeContribution - left.themeContribution ||
          right.roleScore - left.roleScore ||
          left.code.localeCompare(right.code),
      )

    if (exposures.length > 0) {
      byTheme.set(factor.themeId, exposures)
    }

    exposures.forEach((exposure) => {
      if (!byCode.has(exposure.code)) byCode.set(exposure.code, [])
      byCode.get(exposure.code)!.push(exposure)
    })
  })

  byCode.forEach((exposures, code) => {
    byCode.set(
      code,
      exposures.sort(
        (left, right) =>
          right.themeContribution - left.themeContribution ||
          (right.themeScore ?? 0) - (left.themeScore ?? 0) ||
          left.themeName.localeCompare(right.themeName, 'zh-CN'),
      ),
    )
  })

  return { byCode, byTheme }
}
