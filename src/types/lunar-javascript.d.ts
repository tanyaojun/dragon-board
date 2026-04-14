// src/types/lunar-javascript.d.ts
declare module 'lunar-javascript' {
  export class Lunar {
    static fromDate(date: Date): Lunar
    getMonth(): number
    getDay(): number
    getSolarDate(): Date
  }
}