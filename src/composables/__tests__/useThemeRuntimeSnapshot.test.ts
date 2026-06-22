import { effectScope } from 'vue'
import { describe, expect, it } from 'vitest'

import { themeRuntimeStore } from '@/services/theme/ThemeRuntimeStore'
import { useThemeRuntimeSnapshot } from '../useThemeRuntimeSnapshot'

describe('useThemeRuntimeSnapshot', () => {
  it('tracks runtime updates and unsubscribes with its Vue scope', () => {
    themeRuntimeStore.clear()
    const scope = effectScope()
    const runtime = scope.run(() => useThemeRuntimeSnapshot())!

    themeRuntimeStore.update({ lastUpdate: 100, factors: [{ themeId: 'AI' } as any] })
    expect(runtime.value.lastUpdate).toBe(100)
    expect(runtime.value.factors[0].themeId).toBe('AI')

    scope.stop()
    themeRuntimeStore.update({ lastUpdate: 200, factors: [] })
    expect(runtime.value.lastUpdate).toBe(100)
  })
})
