import axios from 'axios'
import { wrapper } from 'axios-cookiejar-support'
import { CookieJar } from 'tough-cookie'
import fs from 'fs'

export const DEFAULT_BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

export function loadEnvFile(filePath) {
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

export function createConfigReader(localEnv = {}) {
  return function readConfig(name, fallback = '') {
    return process.env[name] || localEnv[name] || fallback
  }
}

export function createHttpClients() {
  const jar = new CookieJar()
  const client = wrapper(
    axios.create({
      jar,
      withCredentials: true,
      maxRedirects: 5,
      timeout: 8000,
      validateStatus: (status) => status >= 200 && status < 300,
    }),
  )

  const plainClient = axios.create({
    timeout: 8000,
    validateStatus: (status) => status >= 200 && status < 300,
  })

  return { client, plainClient }
}

export function buildAxiosProxyConfig(proxyUrl) {
  const value = String(proxyUrl || '').trim()
  if (!value) return {}

  const url = new URL(value)
  const protocol = url.protocol.replace(':', '')
  if (protocol !== 'http' && protocol !== 'https') {
    throw new Error(`unsupported axios proxy protocol: ${protocol}`)
  }

  const proxy = {
    protocol,
    host: url.hostname,
    port: Number(url.port) || (protocol === 'https' ? 443 : 80),
  }
  if (url.username || url.password) {
    proxy.auth = {
      username: decodeURIComponent(url.username),
      password: decodeURIComponent(url.password),
    }
  }
  return { proxy }
}

export function createSourceProxyConfig(readConfig, source) {
  if (source !== 'eastmoney') return {}
  return buildAxiosProxyConfig(
    readConfig?.('EASTMONEY_PROXY_URL') ||
      readConfig?.('EASTMONEY_HTTP_PROXY') ||
      readConfig?.('EASTMONEY_HTTPS_PROXY') ||
      '',
  )
}

export function cleanCode(code) {
  return String(code || '')
    .replace(/[^0-9]/g, '')
    .padStart(6, '0')
}

export function parseCodeList(codes, maxSize = 120) {
  const list = String(codes || '')
    .split(',')
    .map((code) => String(code || '').replace(/[^0-9]/g, ''))
    .filter((code) => code.length === 6)

  return Array.from(new Set(list)).slice(0, maxSize)
}

export function getMarketPrefix(code) {
  const c = cleanCode(code)
  return c.startsWith('6') || c.startsWith('11') || c.startsWith('51') ? '1' : '0'
}

export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
