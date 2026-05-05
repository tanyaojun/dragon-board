import { ALERT_LEVELS, ALERT_TYPES } from '@/config/constants'
import type { ThemeEvent, ThemeLegacyAlertBuildContext } from './types'

function stockCodesForTheme(stockMap: ThemeLegacyAlertBuildContext['stockMap'], themeName: string): string[] {
  return Object.values(stockMap)
    .filter((stock) => stock?.blocks?.includes(themeName))
    .map((stock) => stock.code)
    .filter(Boolean)
    .slice(0, 20)
}

function makeEvent(
  type: ThemeEvent['type'],
  alertType: NonNullable<ThemeEvent['alertType']>,
  block: ThemeLegacyAlertBuildContext['blocks'][number],
  timestamp: number,
  reasons: string[],
  stockCodes: string[],
): ThemeEvent {
  return {
    id: `legacy:${type}:${block.code}:${timestamp}`,
    type,
    alertType,
    level: type === 'theme_crowding_high' ? ALERT_LEVELS.WARNING : ALERT_LEVELS.INFO,
    themeId: block.code,
    themeName: block.name,
    timestamp,
    source: 'theme_legacy_adapter',
    stockCodes,
    metrics: {
      strength: block.strength,
      ztCount: block.ztCount,
      netInflow: block.mainNetInflow,
      volumeRatio: block.volumeRatio,
      change: block.change,
    },
    riskFlags: type === 'theme_crowding_high' ? ['legacy_volume_surge'] : [],
    reasons,
  }
}

export function buildLegacyBlockThemeEvents(context: ThemeLegacyAlertBuildContext): ThemeEvent[] {
  const timestamp = context.timestamp || Date.now()
  const events: ThemeEvent[] = []

  context.blocks.forEach((block) => {
    const stockCodes = stockCodesForTheme(context.stockMap, block.name)
    if ((block.mainNetInflow || 0) >= 100000000) {
      events.push(makeEvent('theme_fund_inflow', ALERT_TYPES.MONEY_FLOW, block, timestamp, ['legacy: 板块主力资金流入'], stockCodes))
    }
    if ((block.volumeRatio || 0) >= 3) {
      events.push(makeEvent('theme_crowding_high', ALERT_TYPES.VOLUME_SURGE, block, timestamp, ['legacy: 板块放量异动'], stockCodes))
    }
    if ((block.ztCount || 0) >= 3) {
      events.push(makeEvent('theme_strength_surge', ALERT_TYPES.BATCH_LIMIT_UP, block, timestamp, ['legacy: 板块批量涨停'], stockCodes))
    }
  })

  const seen = new Set<string>()
  return events.filter((event) => {
    const key = `${event.alertType}:${event.themeId}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
