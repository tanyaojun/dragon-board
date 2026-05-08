const SENSITIVE_HEADER_NAMES = new Set([
  'authorization',
  'cookie',
  'set-cookie',
  'xueqiu-cookie',
])

const SENSITIVE_QUERY_NAMES = new Set([
  'authorization',
  'cookie',
  'deviceid',
  'key',
  'password',
  'secret',
  'token',
  'userid',
])

function sanitizeUrl(url) {
  if (!url) return undefined

  try {
    const parsed = new URL(url)
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (SENSITIVE_QUERY_NAMES.has(key.toLowerCase())) {
        parsed.searchParams.delete(key)
      }
    }
    return parsed.toString()
  } catch {
    return String(url).split('?')[0]
  }
}

export function classifyUpstreamError(error) {
  const status = error?.response?.status
  if (status) return `upstream_${status}`

  const code = String(error?.code || '').toUpperCase()
  if (code === 'ECONNABORTED' || code === 'ETIMEDOUT') return 'upstream_timeout'
  if (code === 'ENOTFOUND' || code === 'ECONNRESET' || code === 'ECONNREFUSED') {
    return 'upstream_network_error'
  }
  return 'upstream_unavailable'
}

export function sanitizeErrorDetails(error) {
  const status = error?.response?.status
  const method = error?.config?.method
  const upstreamUrl = sanitizeUrl(error?.config?.url)
  const headers = error?.response?.headers || {}
  const safeHeaders = {}

  for (const [key, value] of Object.entries(headers)) {
    if (SENSITIVE_HEADER_NAMES.has(String(key).toLowerCase())) continue
    safeHeaders[key] = value
  }

  return {
    status,
    method,
    upstreamUrl,
    code: error?.code,
    headers: Object.keys(safeHeaders).length ? safeHeaders : undefined,
  }
}

export function buildDegradedEnvelope({ source, error, fallbackData = null, message }) {
  return {
    ok: false,
    degraded: true,
    source,
    errorCode: classifyUpstreamError(error),
    message: message || error?.message || 'upstream unavailable',
    data: fallbackData,
    details: sanitizeErrorDetails(error),
  }
}

export function buildBadRequestEnvelope(errorCode, message, details) {
  return {
    ok: false,
    degraded: false,
    source: 'proxy',
    errorCode,
    message,
    ...(details === undefined ? {} : { details }),
  }
}

export function buildDeprecatedEnvelope({ source, message, data = null }) {
  return {
    ok: false,
    degraded: true,
    deprecated: true,
    source,
    errorCode: 'proxy_endpoint_deprecated',
    message,
    data,
  }
}

export function sendBadRequest(res, errorCode, message, details) {
  return res.status(400).json(buildBadRequestEnvelope(errorCode, message, details))
}

export function sendDegraded(res, params, status = 200) {
  return res.status(status).json(buildDegradedEnvelope(params))
}

export function sendDeprecated(res, params) {
  return res.json(buildDeprecatedEnvelope(params))
}
