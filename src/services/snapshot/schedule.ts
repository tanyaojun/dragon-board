import type { SnapshotType } from './types'

export const FIVE_MINUTES_SLOTS = [
  '09:30', '09:35', '09:40', '09:45', '09:50', '09:55',
  '10:00', '10:05', '10:10', '10:15', '10:20', '10:25',
  '10:30', '10:35', '10:40', '10:45', '10:50', '10:55',
  '11:00', '11:05', '11:10', '11:15', '11:20', '11:25', '11:30',
  '13:00', '13:05', '13:10', '13:15', '13:20', '13:25',
  '13:30', '13:35', '13:40', '13:45', '13:50', '13:55',
  '14:00', '14:05', '14:10', '14:15', '14:20', '14:25',
  '14:30', '14:35', '14:40', '14:45', '14:50', '14:55',
  '15:00',
] as const

export const QUARTER_HOUR_SLOTS = [
  '09:30', '09:45', '10:00', '10:15', '10:30', '10:45',
  '11:00', '11:15', '11:30',
  '13:00', '13:15', '13:30', '13:45',
  '14:00', '14:15', '14:30', '14:45',
  '15:00', '15:15',
] as const

export const HALF_HOUR_SLOTS = [
  '09:30', '10:00', '10:30', '11:00', '11:30',
  '13:00', '13:30', '14:00', '14:30', '15:00',
] as const

export const HOURLY_SLOTS = ['10:00', '11:00', '13:00', '14:00', '15:00'] as const
export const DAILY_SLOTS = ['15:30'] as const

export function slotTimeToMinutes(slotTime: string): number {
  const match = String(slotTime || '').match(/^(\d{2}):(\d{2})$/)
  if (!match) return -1
  return Number(match[1]) * 60 + Number(match[2])
}

export function getExpectedSlots(type: SnapshotType): string[] {
  // 这里返回的是“理论完整槽位表”，盘中 coverage 会再结合 latestObserved 做截断。
  if (type === 'five_minutes') return [...FIVE_MINUTES_SLOTS]
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
