import crypto from 'crypto'

export function generateCLSSign() {
  const params = { app: 'cailianpress', os: 'android', sv: '835' }
  const str = Object.keys(params)
    .sort()
    .map((key) => `${key}=${params[key]}`)
    .join('&')
  const sha1 = crypto.createHash('sha1').update(str).digest('hex')
  const sign = crypto.createHash('md5').update(sha1).digest('hex')
  return { params, sign }
}
