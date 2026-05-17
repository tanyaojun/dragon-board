import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const storage = (() => {
  const values = new Map<string, string>()
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      values.delete(key)
    }),
    clear: vi.fn(() => {
      values.clear()
    }),
  }
})()

async function loadConfigStore() {
  vi.resetModules()
  const { useConfigStore } = await import('../config')
  return useConfigStore()
}

describe('ConfigStore legacy refresh config migration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    storage.clear()
    vi.stubGlobal('localStorage', storage)
  })

  it('drops legacy user.incrementalRefreshInterval when loading and saving app_config', async () => {
    storage.setItem(
      'app_config',
      JSON.stringify({
        user: {
          fullRefreshInterval: 30 * 60 * 1000,
          incrementalRefreshInterval: 1234,
        },
      }),
    )

    const store = await loadConfigStore()

    expect(store.user.incrementalRefreshInterval).toBeUndefined()

    store.saveConfig()

    const appConfigWrite = [...storage.setItem.mock.calls]
      .reverse()
      .find(([key]) => key === 'app_config')
    const saved = JSON.parse(String(appConfigWrite?.[1] || '{}'))
    expect(saved.user.incrementalRefreshInterval).toBeUndefined()
  })
})
