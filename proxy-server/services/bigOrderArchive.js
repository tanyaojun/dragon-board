import fs from 'node:fs/promises'
import crypto from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { gunzip, gzip } from 'node:zlib'

const gzipAsync = promisify(gzip)
const gunzipAsync = promisify(gunzip)
const __dirname = dirname(fileURLToPath(import.meta.url))
const DEFAULT_DIR = join(__dirname, '..', 'data', 'big-order')

// 大单全天快照本地永久归档（设计 §7.1）：
// - Redis/L1 保持可丢弃缓存定位，永久资产以本地 gzip 文件为准。
// - 同一 {sessionDate, stock, money} 就地原子覆盖；收盘后最后一次重建即全天终稿。
// - 归档失败只告警，绝不影响接口响应。
export function createBigOrderArchiver({ dir = DEFAULT_DIR, logger = console } = {}) {
  async function save({ sessionDate, stockCode, money, value }) {
    const target = join(dir, sessionDate, `${stockCode}.money${money}.json.gz`)
    try {
      await fs.mkdir(dirname(target), { recursive: true })
      const payload = await gzipAsync(
        JSON.stringify({
          sessionDate,
          stockCode,
          money,
          fetchedAt: value.fetchedAt,
          data: value.data,
        }),
      )
      const temp = `${target}.tmp-${crypto.randomBytes(4).toString('hex')}`
      await fs.writeFile(temp, payload)
      await fs.rename(temp, target)
    } catch (error) {
      // 清理可能残留的临时文件
      try { await fs.unlink(temp) } catch {}
      logger.warn(`[龙虎缓存] 快照归档失败 ${sessionDate}/${stockCode}:`, error?.message)
    }
  }

  // 冷启动回填：返回该股最近一个交易日的归档快照；找不到或解析失败返回 null
  async function load({ stockCode, money = 0 }) {
    try {
      const entries = await fs.readdir(dir, { withFileTypes: true }).catch(() => [])
      const days = entries
        .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(entry.name))
        .map((entry) => entry.name)
        .sort()
        .reverse()
      const fileName = `${stockCode}.money${money}.json.gz`
      for (const day of days) {
        const file = join(dir, day, fileName)
        const raw = await fs.readFile(file).catch(() => null)
        if (!raw) continue
        let parsed
        try {
          parsed = JSON.parse((await gunzipAsync(raw)).toString('utf8'))
        } catch {
          // 损坏文件不阻断向更早日期的回退
          logger.warn(`[龙虎缓存] 归档损坏 ${day}/${stockCode}，跳过`)
          continue
        }
        if (!parsed?.sessionDate || !Array.isArray(parsed?.data?.List)) continue
        return parsed
      }
      return null
    } catch (error) {
      logger.warn(`[龙虎缓存] 归档读取失败 ${stockCode}:`, error?.message)
      return null
    }
  }

  return { save, load, dir }
}
