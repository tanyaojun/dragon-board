import { createProxyApp } from './app.js'
import { createConfigReader, createHttpClients, loadEnvFile } from './helpers/http.js'
import { createProxyRedisCache } from './helpers/proxyCache.js'
import { createFeishuEventRadarClient } from './routes/notifications.js'
import { createEventRadarBackgroundWorker } from './services/eventRadarBackgroundPush.js'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

export async function createProxyRuntime(options = {}) {
  const port = Number(options.port || process.env.PORT || 3000)
  const localEnv = options.localEnv || loadEnvFile(join(__dirname, '.env.local'))
  const readConfig = options.readConfig || createConfigReader(localEnv)
  const cache = options.cache || await createProxyRedisCache({ readConfig })
  const clients = options.clients || createHttpClients()
  const feishuEventRadar = options.feishuEventRadar || createFeishuEventRadarClient({
    readConfig,
    fetcher: options.feishuFetcher,
    now: options.now,
  })
  const eventRadarBackgroundWorker = options.eventRadarBackgroundWorker || createEventRadarBackgroundWorker({
    readConfig,
    plainClient: clients.plainClient,
    notifier: feishuEventRadar,
    now: options.now,
  })
  const app = createProxyApp({
    port,
    localEnv,
    readConfig,
    cache,
    clients,
    feishuEventRadar,
    eventRadarBackgroundWorker,
    localVoice: options.localVoice,
    logRequests: options.logRequests,
  })

  return {
    app,
    port,
    localEnv,
    readConfig,
    cache,
    clients,
    feishuEventRadar,
    eventRadarBackgroundWorker,
  }
}
