import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('App fund priority contract', () => {
  it('registers and clears main search result codes as P0 priority', () => {
    const source = readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')

    expect(source).toMatch(/realtimeSubscriptionRegistry\.setFundOwnerCodes\(\s*'app\.search'/)
    expect(source).toContain("realtimeSubscriptionRegistry.clearFundOwner('app.search')")
  })
})
