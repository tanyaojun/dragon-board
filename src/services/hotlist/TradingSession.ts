/**
 * 交易时段判定：与 tools/YiDongJingLing/MarketData/TradingSession.cs 语义一致。
 * 连续竞价 = 周一至周五的 09:30:00–11:30:00 与 13:00:00–15:00:00（含端点）。
 * 节假日不判定（与 C# 相同的已知局限，由事件静默兜底）。
 */
export function isContinuousAuction(timestamp: number): boolean {
  const local = new Date(timestamp)
  const day = local.getDay()
  if (day === 0 || day === 6) return false

  const minutes = local.getHours() * 60 + local.getMinutes() + local.getSeconds() / 60
  return isBetween(minutes, 9 * 60 + 30, 11 * 60 + 30) ||
    isBetween(minutes, 13 * 60, 15 * 60)
}

function isBetween(value: number, start: number, end: number): boolean {
  return value >= start && value <= end
}
