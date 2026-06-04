import { sendBadRequest } from '../helpers/response.js'

const SIGNAL_TYPE = 'opening_weak_to_strong'
const SOURCE_PRIORITY = new Map([
  ['desktop', 3],
  ['web', 2],
])
const STAGE_PRIORITY = new Map([
  ['auctionConditionPassed', 1],
  ['auctionConditionFailed', 1],
  ['gapAlert', 2],
  ['noGap', 2],
  ['trendConfirm', 3],
  ['trendWeak', 3],
  ['optionalFinalStatus', 4],
])
const SIGNAL_FIELDS = new Set([
  'stage',
  'status',
  'code',
  'name',
  'time',
  'price',
  'pct',
  'amount',
  'voiceEligible',
  'reason',
])

export function registerOpeningSignalRoutes(app, context = {}) {
  const store = context.openingSignalStore || createOpeningSignalStore()

  app.post('/api/opening-signals', (req, res) => {
    const source = normalizeSource(req.body?.source)
    const signal = normalizeSignal(req.body?.signal)
    if (!source || !signal) {
      sendBadRequest(res, 'opening_signal_invalid', 'opening signal payload is invalid')
      return
    }

    const result = store.upsert(source, signal)
    res.json({
      ok: true,
      accepted: true,
      ...result,
    })
  })

  app.get('/api/opening-signals/today', (req, res) => {
    const tradingDate = normalizeTradingDate(req.query?.tradingDate) || todayShanghai()
    res.json({
      ok: true,
      tradingDate,
      signals: store.list(tradingDate),
    })
  })
}

export function createOpeningSignalStore() {
  const records = new Map()

  return {
    upsert(source, signal) {
      const key = dedupeKey(signal)
      const now = new Date().toISOString()
      const previous = records.get(key)
      const report = { ...signal, source }

      if (!previous) {
        const voiceStage = signalVoiceStage(report)
        const voiceOwner = shouldGrantVoice(report) ? source : 'none'
        const voiceGrantedStages = voiceOwner === 'none' ? {} : { [voiceStage]: source }
        const record = {
          dedupeKey: key,
          canonicalSignal: report,
          reportsBySource: { [source]: report },
          sources: [source],
          firstTriggerAt: signal.time,
          lastReportedAt: now,
          voiceGrantedTo: voiceOwner === 'none' ? null : source,
          voiceGrantedStages,
        }
        records.set(key, record)
        return serializeRecord(record, {
          isNew: true,
          dedupeAction: 'created',
          voiceOwner,
        })
      }

      const reportsBySource = { ...previous.reportsBySource, [source]: report }
      const sources = mergeSources(previous.sources, source)
      const canonicalSignal = chooseCanonical([...Object.values(reportsBySource)])
      const dedupeAction = canonicalSignal === previous.canonicalSignal ? 'merged' : 'upgraded'
      const voiceGrantedStages = { ...(previous.voiceGrantedStages || {}) }
      const voiceStage = signalVoiceStage(canonicalSignal)
      const voiceOwner =
        !voiceGrantedStages[voiceStage] && canonicalSignal === report && shouldGrantVoice(canonicalSignal)
          ? source
          : 'none'
      if (voiceOwner !== 'none') voiceGrantedStages[voiceStage] = source
      const next = {
        ...previous,
        canonicalSignal,
        reportsBySource,
        sources,
        firstTriggerAt: earlierIso(previous.firstTriggerAt, signal.time),
        lastReportedAt: now,
        voiceGrantedTo: previous.voiceGrantedTo || (voiceOwner === 'none' ? null : source),
        voiceGrantedStages,
      }
      records.set(key, next)
      return serializeRecord(next, {
        isNew: false,
        dedupeAction,
        voiceOwner,
      })
    },
    list(tradingDate) {
      return [...records.values()]
        .filter(record => signalTradingDate(record.canonicalSignal) === tradingDate)
        .sort((a, b) => compareIso(b.firstTriggerAt, a.firstTriggerAt))
        .map(record => serializeRecord(record, { isNew: false, dedupeAction: 'cached', voiceOwner: 'none' }))
    },
  }
}

function serializeRecord(record, meta) {
  return {
    ...meta,
    dedupeKey: record.dedupeKey,
    canonicalSignal: publicSignal(record.canonicalSignal),
    reportsBySource: record.reportsBySource,
    sources: record.sources,
    firstTriggerAt: record.firstTriggerAt,
    lastReportedAt: record.lastReportedAt,
    voiceGrantedTo: record.voiceGrantedTo,
    voiceGrantedStages: record.voiceGrantedStages || {},
  }
}

function publicSignal(signal) {
  const { source, ...rest } = signal
  return rest
}

function normalizeSource(value) {
  const source = String(value || '').trim()
  return source === 'web' || source === 'desktop' ? source : ''
}

function normalizeSignal(value) {
  if (!value || typeof value !== 'object') return null
  if (Object.keys(value).some(key => !SIGNAL_FIELDS.has(key))) return null
  const code = normalizeCode(value.code)
  const stage = normalizeStage(value.stage)
  const time = normalizeIso(value.time)
  if (!code || !stage || !time) return null

  return {
    stage,
    status: normalizeStage(value.status) || stage,
    code,
    name: normalizeText(value.name, 24) || code,
    time,
    price: normalizeFiniteNumber(value.price),
    pct: normalizeFiniteNumber(value.pct),
    amount: normalizeFiniteNumber(value.amount),
    voiceEligible: value.voiceEligible === true,
    reason: normalizeText(value.reason, 120),
  }
}

function normalizeTradingDate(value) {
  const text = String(value || '').trim()
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : ''
}

function normalizeCode(value) {
  const code = String(value || '').replace(/\D/g, '')
  return /^\d{6}$/.test(code) ? code : ''
}

function normalizeText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength)
}

function normalizeStage(value) {
  const text = String(value || '').trim()
  return STAGE_PRIORITY.has(text) ? text : ''
}

function normalizeIso(value) {
  const timestamp = Date.parse(String(value || ''))
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : ''
}

function dedupeKey(signal) {
  return `${signalTradingDate(signal)}:${signal.code}:${SIGNAL_TYPE}`
}

function shouldGrantVoice(signal) {
  return signal.voiceEligible === true && (signal.stage === 'gapAlert' || signal.stage === 'trendConfirm')
}

function signalVoiceStage(signal) {
  return normalizeStage(signal.stage)
}

function mergeSources(previous, source) {
  return previous.includes(source) ? previous : [...previous, source]
}

function chooseCanonical(reports) {
  return [...reports].sort(compareSignals)[0]
}

function compareSignals(left, right) {
  const stageDiff = (STAGE_PRIORITY.get(right.stage) || 0) - (STAGE_PRIORITY.get(left.stage) || 0)
  if (stageDiff !== 0) return stageDiff

  const sourceDiff = (SOURCE_PRIORITY.get(right.source) || 0) - (SOURCE_PRIORITY.get(left.source) || 0)
  if (sourceDiff !== 0) return sourceDiff

  return compareIso(left.time, right.time)
}

function earlierIso(left, right) {
  return compareIso(left, right) <= 0 ? left : right
}

function normalizeFiniteNumber(value) {
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function signalTradingDate(signal) {
  return signal.time.slice(0, 10)
}

function compareIso(left, right) {
  return Date.parse(left || '') - Date.parse(right || '')
}

function todayShanghai() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const byType = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${byType.year}-${byType.month}-${byType.day}`
}
