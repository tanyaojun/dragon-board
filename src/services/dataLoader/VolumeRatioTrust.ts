export function getTrustedVolumeRatio(stock: {
  volumeRatio?: unknown
  volumeRatioMeta?: { status?: unknown } | null
}): number {
  const value = Number(stock?.volumeRatio)
  if (!Number.isFinite(value) || value <= 0) return 0

  const meta = stock?.volumeRatioMeta
  if (!meta) return value

  return meta.status === 'fresh' ? value : 0
}
