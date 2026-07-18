import fs from 'node:fs/promises'
import { join } from 'node:path'

const MAX_LIST = 20

function shanghaiDate(timestamp) {
  return new Date(timestamp).toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })
}

function shanghaiClock(timestamp) {
  const date = new Date(timestamp)
  const weekday = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
  }).format(date)
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value || 0)
  const minute = Number(parts.find((part) => part.type === 'minute')?.value || 0)
  return { weekend: weekday === 'Sat' || weekday === 'Sun', minutes: hour * 60 + minute }
}

// 收盘后大单归档采集器（设计 §7.2）：
// - 盘中由调用方登记"当日进入候选池/交易池"的股票，收盘后自动逐只采集归档。
// - 集成主进程（参照 eventRadarBackgroundWorker 先例），timer.unref() 不阻塞退出。
// - 无质量门禁：采到即归档，单只失败记日志跳过；重复运行命中缓存，代价趋近于零。
export function createBigOrderCollector({
  service,
  dir,
  now = () => Date.now(),
  logger = console,
  maxList = MAX_LIST,
} = {}) {
  let lastRunDate = null
  let timer = null

  function listFile(date) {
    return join(dir, 'collect-list', `${date}.json`)
  }

  async function readList(date) {
    try {
      const raw = await fs.readFile(listFile(date), 'utf8')
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  async function register(stockCodes) {
    const date = shanghaiDate(now())
    const merged = [...(await readList(date))]
    for (const raw of stockCodes || []) {
      const code = String(raw || '').trim()
      if (!/^\d{6}$/.test(code) || merged.includes(code)) continue
      if (merged.length >= maxList) break
      merged.push(code)
    }
    await fs.mkdir(join(dir, 'collect-list'), { recursive: true })
    await fs.writeFile(listFile(date), JSON.stringify(merged))
    return merged
  }

  async function list() {
    return readList(shanghaiDate(now()))
  }

  async function runDaily(stockCodes = null) {
    const codes = stockCodes?.length ? stockCodes : await list()
    let succeeded = 0
    const failures = []
    for (const stockCode of codes) {
      try {
        await service.loadAllDay({ stockCode, money: 0 })
        succeeded += 1
      } catch (error) {
        failures.push({ stockCode, error: error?.message || 'unknown' })
        logger.warn(`[龙虎采集] ${stockCode} 采集失败:`, error?.message)
      }
    }
    if (codes.length) {
      logger.log(`[龙虎采集] 收盘采集完成 ${succeeded}/${codes.length} 只`)
    }
    return { requested: codes.length, succeeded, failed: failures.length, failures }
  }

  // 工作日 15:10~16:00 窗口内每天自动跑一轮；重复命中缓存无上游成本
  function startTimer() {
    if (timer) return timer
    timer = setInterval(() => {
      const { weekend, minutes } = shanghaiClock(now())
      const today = shanghaiDate(now())
      if (weekend || minutes < 910 || minutes >= 960 || lastRunDate === today) return
      lastRunDate = today
      runDaily().catch((error) => logger.warn('[龙虎采集] 收盘采集异常:', error?.message))
    }, 60_000)
    timer.unref?.()
    return timer
  }

  return { register, list, runDaily, startTimer }
}
