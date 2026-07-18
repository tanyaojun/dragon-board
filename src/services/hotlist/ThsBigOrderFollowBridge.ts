const THS_BIG_ORDER_BRIDGE_URL = 'http://127.0.0.1:38891/hotlist/selection'

export function sendHotlistSelection(code: string, name?: string): void {
  const normalizedCode = String(code || '').replace(/^(SH|SZ|BJ)/i, '')
  if (!/^\d{6}$/.test(normalizedCode)) return

  void fetch(THS_BIG_ORDER_BRIDGE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: normalizedCode, name: name || '' }),
  }).catch(() => {
    // THSBigOrder may not be running; row selection must remain unaffected.
  })
}
