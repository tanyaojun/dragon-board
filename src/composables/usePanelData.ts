// src/composables/usePanelData.ts
import { ref } from 'vue'  // ✅ 必须添加这行
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

export function usePanelData(options: {
  name: string
  fetchData: () => Promise<any>
}) {
  const data = ref<any>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdate = ref<number>(Date.now())

  async function loadData() {
    if (loading.value) return

    loading.value = true
    error.value = null

    try {
      console.log(`[${options.name}] 加载数据...`)
      const result = await options.fetchData()

      data.value = result
      lastUpdate.value = Date.now()

      console.log(`[${options.name}] 加载完成`, result)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载失败'
      console.error(`[${options.name}] 加载失败:`, err)
    } finally {
      loading.value = false
    }
  }

  function showToast(message: string, type: 'success' | 'info' | 'error' = 'info') {
    EventManager.emit(AppEvents.UI.TOAST, {
      message,
      duration: type === 'error' ? 2000 : 1500,
      type,
    })
  }

  return {
    data,
    loading,
    error,
    lastUpdate,
    loadData,
    showToast,
  }
}
