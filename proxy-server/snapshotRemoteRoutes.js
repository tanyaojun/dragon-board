import axios from 'axios'
import fs from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'
import { gzipSync, gunzipSync } from 'zlib'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export const SNAPSHOT_DAY_BUNDLE_JSON_LIMIT = process.env.SNAPSHOT_DAY_BUNDLE_JSON_LIMIT || '80mb'

const SNAPSHOT_DAY_BUNDLE_DIR = 'bundles/by-date'
const SNAPSHOT_LEGACY_DAY_BUNDLE_DIR = 'day-bundles'

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return {}
  const content = fs.readFileSync(filePath, 'utf8')
  const result = {}
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const equalIndex = line.indexOf('=')
    if (equalIndex <= 0) continue
    const key = line.slice(0, equalIndex).trim()
    const value = line.slice(equalIndex + 1).trim()
    result[key] = value
  }
  return result
}

const localEnv = {
  ...loadEnvFile(join(__dirname, '.env.local')),
}

const snapshotWebdavConfig = {
  baseUrl:
    process.env.SNAPSHOT_WEBDAV_BASE_URL || localEnv.SNAPSHOT_WEBDAV_BASE_URL || '',
  username:
    process.env.SNAPSHOT_WEBDAV_USERNAME || localEnv.SNAPSHOT_WEBDAV_USERNAME || '',
  password:
    process.env.SNAPSHOT_WEBDAV_PASSWORD || localEnv.SNAPSHOT_WEBDAV_PASSWORD || '',
  root:
    process.env.SNAPSHOT_WEBDAV_ROOT || localEnv.SNAPSHOT_WEBDAV_ROOT || '/dragon-board',
  timeout: Number(process.env.SNAPSHOT_WEBDAV_TIMEOUT || localEnv.SNAPSHOT_WEBDAV_TIMEOUT || 15000),
}

function isSnapshotWebdavConfigured() {
  return Boolean(
    snapshotWebdavConfig.baseUrl &&
      snapshotWebdavConfig.username &&
      snapshotWebdavConfig.password &&
      snapshotWebdavConfig.root,
  )
}

function buildSnapshotRemoteEnvelope(data, extras = {}) {
  return {
    ok: true,
    data,
    ...extras,
  }
}

function normalizeDavPath(path) {
  const cleaned = String(path || '')
    .replace(/\\/g, '/')
    .replace(/\/+/g, '/')
    .replace(/\/$/, '')
  return cleaned.startsWith('/') ? cleaned : `/${cleaned}`
}

function resolveSnapshotRemotePath(relativePath = '') {
  const root = normalizeDavPath(snapshotWebdavConfig.root || '/dragon-board')
  const child = String(relativePath || '').replace(/^\/+/, '')
  return child ? `${root}/${child}` : root
}

function buildSnapshotRemoteUrl(relativePath = '') {
  const base = String(snapshotWebdavConfig.baseUrl || '').replace(/\/+$/, '')
  return `${base}${resolveSnapshotRemotePath(relativePath)}`
}

function createSnapshotDavClient() {
  return axios.create({
    timeout: snapshotWebdavConfig.timeout,
    auth: {
      username: snapshotWebdavConfig.username,
      password: snapshotWebdavConfig.password,
    },
    validateStatus: () => true,
  })
}

function parseDayBundleManifest(xml, dir) {
  const text = String(xml || '')
  const items = []
  const responseBlocks = text.match(/<d:response>[\s\S]*?<\/d:response>/gi) || []
  for (const block of responseBlocks) {
    const hrefMatch = block.match(/<d:href>([\s\S]*?)<\/d:href>/i)
    if (!hrefMatch) continue
    const href = decodeURIComponent(hrefMatch[1])
    const fileName = href.split('/').filter(Boolean).pop() || ''
    const match = fileName.match(/^([0-9]{4}-[0-9]{2}-[0-9]{2})\.json(?:\.gz)?$/)
    if (!match) continue
    const timestampMatch = block.match(/<d:getlastmodified>([\s\S]*?)<\/d:getlastmodified>/i)
    const contentLengthMatch = block.match(/<d:getcontentlength>([\s\S]*?)<\/d:getcontentlength>/i)
    const uploadedAt = timestampMatch ? Date.parse(timestampMatch[1]) : Date.now()
    const tradingDate = match[1]
    items.push({
      id: `day-bundle:${tradingDate}`,
      type: 'daily',
      tradingDate,
      slotTime: '15:00',
      timestamp: Number.isFinite(uploadedAt) ? uploadedAt : Date.now(),
      displayKey: `[day-bundle] ${tradingDate}`,
      size: Number(contentLengthMatch?.[1] || 0),
      contentHash: '',
      uploadedAt: Number.isFinite(uploadedAt) ? uploadedAt : Date.now(),
      storageKey: `${resolveSnapshotRemotePath(dir)}/${fileName}`,
    })
  }
  return items
}

async function ensureSnapshotRemoteCollection(relativePath) {
  const client = createSnapshotDavClient()
  const segments = String(relativePath || '')
    .split('/')
    .map((item) => item.trim())
    .filter(Boolean)
  let current = ''
  for (const segment of segments) {
    current = current ? `${current}/${segment}` : segment
    const response = await client.request({
      method: 'MKCOL',
      url: buildSnapshotRemoteUrl(current),
    })
    if (![201, 301, 405].includes(response.status)) {
      throw new Error(`remote_mkcol_failed:${current}:${response.status}`)
    }
  }
}

async function fetchSnapshotRemoteJson(relativePath) {
  const client = createSnapshotDavClient()
  const response = await client.get(buildSnapshotRemoteUrl(relativePath), {
    responseType: 'text',
  })
  if (response.status === 404) return null
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`remote_fetch_failed:${relativePath}:${response.status}`)
  }
  return typeof response.data === 'string' ? JSON.parse(response.data) : response.data
}

async function fetchSnapshotRemoteGzipJson(relativePath) {
  const client = createSnapshotDavClient()
  const response = await client.get(buildSnapshotRemoteUrl(relativePath), {
    responseType: 'arraybuffer',
  })
  if (response.status === 404) return null
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`remote_fetch_failed:${relativePath}:${response.status}`)
  }
  const buffer = Buffer.from(response.data)
  return JSON.parse(gunzipSync(buffer).toString('utf8'))
}

function summarizeDavErrorPayload(data) {
  const raw = typeof data === 'string' ? data : JSON.stringify(data || '')
  return raw
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 240)
}

async function putSnapshotRemoteGzipJson(relativePath, payload) {
  const client = createSnapshotDavClient()
  const dir = relativePath.split('/').slice(0, -1).join('/')
  if (dir) {
    await ensureSnapshotRemoteCollection(dir)
  }
  const compressed = gzipSync(Buffer.from(JSON.stringify(payload), 'utf8'), { level: 9 })
  const response = await client.put(buildSnapshotRemoteUrl(relativePath), compressed, {
    headers: {
      'Content-Type': 'application/gzip',
    },
    maxBodyLength: Infinity,
    maxContentLength: Infinity,
  })
  if (response.status < 200 || response.status >= 300) {
    const detail = summarizeDavErrorPayload(response.data)
    const suffix = detail ? `:${detail}` : ''
    throw new Error(`remote_put_failed:${relativePath}:${response.status}${suffix}`)
  }
  return {
    size: compressed.length,
  }
}

function buildDayBundleRelativePath(tradingDate, mode = 'primary', format = 'json') {
  const dir = mode === 'legacy' ? SNAPSHOT_LEGACY_DAY_BUNDLE_DIR : SNAPSHOT_DAY_BUNDLE_DIR
  const suffix = format === 'gzip' ? '.json.gz' : '.json'
  return `${dir}/${tradingDate}${suffix}`
}

async function fetchDayBundleWithFallback(tradingDate) {
  const compressed = await fetchSnapshotRemoteGzipJson(
    buildDayBundleRelativePath(tradingDate, 'primary', 'gzip'),
  )
  if (compressed) return compressed
  const primary = await fetchSnapshotRemoteJson(buildDayBundleRelativePath(tradingDate, 'primary', 'json'))
  if (primary) return primary
  return fetchSnapshotRemoteJson(buildDayBundleRelativePath(tradingDate, 'legacy', 'json'))
}

async function listDayBundleManifestFiles() {
  const dirs = [SNAPSHOT_DAY_BUNDLE_DIR, SNAPSHOT_LEGACY_DAY_BUNDLE_DIR]
  const byTradingDate = new Map()
  for (const dir of dirs) {
    try {
      const client = createSnapshotDavClient()
      await ensureSnapshotRemoteCollection(dir)
      const response = await client.request({
        method: 'PROPFIND',
        url: buildSnapshotRemoteUrl(dir),
        headers: {
          Depth: '1',
        },
        data:
          '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/><d:getcontentlength/></d:prop></d:propfind>',
        responseType: 'text',
      })
      if (![200, 207].includes(response.status)) continue
      for (const item of parseDayBundleManifest(response.data, dir)) {
        if (!byTradingDate.has(item.tradingDate) || dir === SNAPSHOT_DAY_BUNDLE_DIR) {
          byTradingDate.set(item.tradingDate, item)
        }
      }
    } catch {
      // 远端可能没有历史目录；manifest 应尽量返回已有目录，而不是整体失败。
    }
  }
  return Array.from(byTradingDate.values())
}

async function getSnapshotRemoteHealth() {
  if (!isSnapshotWebdavConfigured()) {
    return {
      ok: false,
      enabled: false,
      message: 'snapshot_webdav_not_configured',
    }
  }

  const client = createSnapshotDavClient()
  const response = await client.request({
    method: 'PROPFIND',
    url: buildSnapshotRemoteUrl(),
    headers: {
      Depth: '0',
    },
    data:
      '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
    responseType: 'text',
  })

  if (![200, 207].includes(response.status)) {
    return {
      ok: false,
      enabled: false,
      message: `snapshot_webdav_health_failed:${response.status}`,
      baseUrl: snapshotWebdavConfig.baseUrl,
      rootPath: snapshotWebdavConfig.root,
    }
  }

  return {
    ok: true,
    enabled: true,
    writable: true,
    baseUrl: snapshotWebdavConfig.baseUrl,
    rootPath: snapshotWebdavConfig.root,
  }
}

export function registerSnapshotRemoteRoutes(app) {
  app.get('/api/snapshots/remote/health', async (req, res) => {
    try {
      const health = await getSnapshotRemoteHealth()
      res.json(buildSnapshotRemoteEnvelope(health))
    } catch (error) {
      res.status(500).json({
        ok: false,
        errorCode: 'remote_health_failed',
        message: error.message,
        data: {
          ok: false,
          enabled: false,
          message: error.message,
        },
      })
    }
  })

  app.get('/api/snapshots/remote/manifest', async (req, res) => {
    try {
      const limit = Number(req.query.limit || 5000)
      const cursor = Number(req.query.cursor || 0)
      const items = await listDayBundleManifestFiles()
      const sorted = items.sort((left, right) => right.timestamp - left.timestamp)
      const windowItems = sorted.slice(cursor, cursor + limit)
      const nextCursor = cursor + limit < sorted.length ? String(cursor + limit) : null
      res.json(
        buildSnapshotRemoteEnvelope({
          items: windowItems,
          nextCursor,
        }),
      )
    } catch (error) {
      res.status(500).json({
        ok: false,
        errorCode: 'remote_manifest_failed',
        message: error.message,
        data: {
          items: [],
          nextCursor: null,
        },
      })
    }
  })

  app.post('/api/snapshots/remote/upload-day-bundle', async (req, res) => {
    try {
      const bundle = req.body
      if (!bundle?.tradingDate) {
        return res.status(400).json({
          ok: false,
          errorCode: 'remote_day_bundle_invalid_payload',
          message: 'snapshot day bundle missing tradingDate',
        })
      }
      const relativePath = buildDayBundleRelativePath(bundle.tradingDate, 'primary', 'gzip')
      const upload = await putSnapshotRemoteGzipJson(relativePath, bundle)
      res.json(
        buildSnapshotRemoteEnvelope({
          ok: true,
          tradingDate: bundle.tradingDate,
          uploadedAt: Date.now(),
          contentHash: '',
          storageKey: resolveSnapshotRemotePath(relativePath),
          size: upload.size,
          snapshotCount: Array.isArray(bundle.items) ? bundle.items.length : 0,
        }),
      )
    } catch (error) {
      res.status(500).json({
        ok: false,
        errorCode: 'remote_day_bundle_upload_failed',
        message: error.message,
      })
    }
  })

  app.get('/api/snapshots/remote/download-day-bundle/:tradingDate', async (req, res) => {
    try {
      const bundle = await fetchDayBundleWithFallback(req.params.tradingDate)
      res.json(buildSnapshotRemoteEnvelope(bundle))
    } catch (error) {
      res.status(500).json({
        ok: false,
        errorCode: 'remote_day_bundle_download_failed',
        message: error.message,
      })
    }
  })
}
