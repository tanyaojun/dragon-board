import assert from 'node:assert/strict'

import { __quoteRouteInternals } from './quotes.js'

const {
  EASTMONEY_ULIST_HIST_FLOW_LIMIT,
  buildEastmoneyClistUrl,
  buildEastmoneyHistFlowUrl,
  mergeEastmoneyRows,
  missingEastmoneyCodes,
  codesMissingFundFlow,
  mergeEastmoneyFundFlowRows,
  normalizeEastmoneyHistFlowResponse,
  normalizeEastmoneyResponse,
} =
  __quoteRouteInternals

assert.equal(EASTMONEY_ULIST_HIST_FLOW_LIMIT, 20)

const normalized = normalizeEastmoneyResponse(
  {
    rc: 0,
    data: {
      diff: [
        {
          f12: 'SZ002081',
          f14: '金螳螂',
          f2: '6.8',
          f62: '12000000',
          f184: '3.4',
          f66: '5000000',
          f69: '1.2',
        },
        { f12: '999999', f62: '1' },
      ],
    },
  },
  ['002081'],
)

assert.deepEqual(normalized.data.diff, [
  {
    f12: '002081',
    f14: '金螳螂',
    f2: 6.8,
    f3: 0,
    f5: 0,
    f6: 0,
    f8: 0,
    f9: 0,
    f20: 0,
    f21: 0,
    f23: 0,
    f62: 12000000,
    f66: 5000000,
    f69: 1.2,
    f184: 3.4,
  },
])

const merged = mergeEastmoneyRows(
  { rc: 0, data: { diff: [{ f12: '002081', f2: 6.8, f62: 0 }] } },
  { rc: 0, data: { diff: [{ f12: '002081', f62: 12000000, f184: 3.4 }] } },
  ['002081'],
)

assert.equal(merged.data.diff[0].f2, 6.8)
assert.equal(merged.data.diff[0].f62, 12000000)
assert.equal(merged.data.diff[0].f184, 3.4)
assert.deepEqual(missingEastmoneyCodes(merged, ['002081', '002580']), ['002580'])

const fundFlowMerged = mergeEastmoneyFundFlowRows(
  { rc: 0, data: { diff: [{ f12: '002081', f2: 8.88, f3: 1.23, f62: 0, f184: 0 }] } },
  { rc: 0, data: { diff: [{ f12: '002081', f2: 6.8, f3: -2.2, f62: 12000000, f184: 3.4 }] } },
  ['002081'],
)

assert.equal(fundFlowMerged.data.diff[0].f2, 8.88)
assert.equal(fundFlowMerged.data.diff[0].f3, 1.23)
assert.equal(fundFlowMerged.data.diff[0].f62, 12000000)
assert.equal(fundFlowMerged.data.diff[0].f184, 3.4)

assert.deepEqual(
  codesMissingFundFlow(
    {
      rc: 0,
      data: {
        diff: [
          { f12: '002081', f62: 0, f184: 0, f66: 0, f69: 0 },
          { f12: '002580', f62: 12000000, f184: 3.4, f66: 5000000, f69: 1.2 },
        ],
      },
    },
    ['002081', '002580', '600076'],
  ),
  ['002081', '600076'],
)

const clistWithHistFill = mergeEastmoneyRows(
  { rc: 0, data: { diff: [{ f12: '002580', f62: 334315408, f184: 12.03 }] } },
  { rc: 0, data: { diff: [{ f12: '002081', f62: -212639040, f184: -5.44 }] } },
  ['002081', '002580'],
)

assert.deepEqual(
  clistWithHistFill.data.diff.map((row) => [row.f12, row.f62, row.f184]).sort(),
  [
    ['002081', -212639040, -5.44],
    ['002580', 334315408, 12.03],
  ],
)
assert.match(buildEastmoneyClistUrl(['002081']), /api\/qt\/clist\/get/)
assert.match(buildEastmoneyClistUrl(['002081']), /fields=.*f62/)
assert.match(buildEastmoneyHistFlowUrl('002580'), /stock\/fflow\/daykline\/get/)

assert.deepEqual(
  normalizeEastmoneyHistFlowResponse(
    {
      data: {
        code: '002580',
        name: '圣阳股份',
        klines: [
          '2026-05-08,334315408.0,-165668496.0,-168646912.0,19327648.0,314987760.0,12.03,-5.96,-6.07,0.70,11.34,32.90,10.00,0.00,0.00',
        ],
      },
    },
    '002580',
  ),
  {
    f12: '002580',
    f14: '圣阳股份',
    f2: 32.9,
    f3: 10,
    f5: 0,
    f6: 0,
    f8: 0,
    f9: 0,
    f20: 0,
    f21: 0,
    f23: 0,
    f62: 334315408,
    f66: 314987760,
    f69: 11.34,
    f184: 12.03,
  },
)

console.log('quotes route internals ok')
