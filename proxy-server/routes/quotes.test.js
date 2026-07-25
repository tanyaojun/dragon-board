import assert from 'node:assert/strict'

import { __quoteRouteInternals } from './quotes.js'

const tencentPayload = Buffer.from(
  'v_sh600522="1~ZTTX~600522~49.53~46.07~44.00~5131565~2570197~2561369~49.52~17975~49.51~1472~49.50~1839~49.49~176~49.48~543~49.53~2019~49.54~702~49.55~2167~49.56~240~49.57~103~~20260608161401~3.46~7.51~50.68~44.00~49.53/5131565/25205130127~5131565~2520513~15.04~52.93~~50.68~44.00~14.50~1690.43~1690.43~4.45~50.68~41.46~1.40~16774~49.12~45.99~58.24~~~1.75~2520513.0127~0.0000~0~ ";',
)

assert.equal(__quoteRouteInternals.parseTencentQuotePayload(tencentPayload).data.diff[0].f10, 1.4)

console.log('quotes route internals ok')
