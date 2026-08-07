import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DataTable resonance tooltip decoupled from theme momentum', () => {
  const source = readFileSync(
    join(process.cwd(), 'src', 'components', 'common', 'DataTable.vue'),
    'utf8',
  )

  it('removes inline theme momentum section from resonance tooltip', () => {
    expect(source).not.toContain('【题材动量】')
    expect(source).not.toContain('resonance.theme.themeMomentumScore')
  })
})
