import type { SnapshotType } from './types'

export const QUARTER_HOUR_SLOTS = [
  '09:30', '09:45', '10:00', '10:15', '10:30', '10:45',
  '11:00', '11:15', '11:30',
  '13:00', '13:15', '13:30', '13:45',
  '14:00', '14:15', '14:30', '14:45',
  '15:00',
] as const

export const HALF_HOUR_SLOTS = [
  '09:30', '10:00', '10:30', '11:00', '11:30',
  '13:00', '13:30', '14:00', '14:30', '15:00',
] as const

export const HOURLY_SLOTS = ['10:00', '11:00', '13:00', '14:00', '15:00'] as const
export const DAILY_SLOTS = ['15:00'] as const

export function slotTimeToMinutes(slotTime: string): number {
  const match = String(slotTime || '').match(/^(\d{2}):(\d{2})$/)
  if (!match) return -1
  return Number(match[1]) * 60 + Number(match[2])
}

export function getExpectedSlots(type: SnapshotType): string[] {
  // 这里返回的是“理论完整槽位表”，盘中 coverage 会再结合 latestObserved 做截断。
  if (type === 'quarter_hour') return [...QUARTER_HOUR_SLOTS]
  if (type === 'half_hour') return [...HALF_HOUR_SLOTS]
  if (type === 'hourly') return [...HOURLY_SLOTS]
  if (type === 'daily') return [...DAILY_SLOTS]
  return []
}

export function getScheduledSlotsForDate(type: SnapshotType, baseTime: Date): Date[] {
  const dayStart = new Date(baseTime)
  dayStart.setHours(0, 0, 0, 0)
  return getExpectedSlots(type).map((slotLabel) => {
    const [hours, minutes] = slotLabel.split(':').map((value) => Number(value))
    const slot = new Date(dayStart)
    slot.setHours(hours, minutes, 0, 0)
    return slot
  })
}

export function findLatestEligibleSnapshotSlot(type: SnapshotType, baseTime: Date): Date | null {
  // 给定任意当前时间，返回不晚于该时刻的最近合法槽位，用于手工保存与定时回补统一归槽。
  const candidates = getScheduledSlotsForDate(type, baseTime)
    .filter((candidate) => candidate.getTime() <= baseTime.getTime())
    .sort((left, right) => right.getTime() - left.getTime())

  return candidates[0] || null
}

export function isCloseSnapshotSlot(type: SnapshotType, slotTime: string): boolean {
  const closeSlot = getExpectedSlots(type).at(-1)
  return Boolean(closeSlot && closeSlot === slotTime)
}
