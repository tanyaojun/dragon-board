// src/composables/usePagination.ts

import { ref, computed, type Ref } from 'vue'

export interface PaginationOptions<T> {
  fetchData: (page: number, limit: number) => Promise<{ items: T[]; total: number }>
  limit?: number
  autoLoad?: boolean
}

export function usePagination<T>(options: PaginationOptions<T>) {
  const items = ref<T[]>([]) as Ref<T[]>
  const page = ref(1)
  const limit = ref(options.limit || 20)
  const total = ref(0)
  const loading = ref(false)
  
  const totalPages = computed(() => Math.ceil(total.value / limit.value))
  const hasMore = computed(() => items.value.length < total.value)
  const hasPrev = computed(() => page.value > 1)

  async function loadPage(pageNum: number) {
    if (loading.value) return
    
    loading.value = true
    try {
      const result = await options.fetchData(pageNum, limit.value)
      
      if (pageNum === 1) {
        items.value = result.items
      } else {
        items.value = [...items.value, ...result.items]
      }
      
      total.value = result.total
      page.value = pageNum
    } finally {
      loading.value = false
    }
  }

  async function loadMore() {
    if (hasMore.value) {
      await loadPage(page.value + 1)
    }
  }

  async function refresh() {
    await loadPage(1)
  }

  function reset() {
    items.value = []
    page.value = 1
    total.value = 0
  }

  return {
    items,
    page,
    limit,
    total,
    loading,
    totalPages,
    hasMore,
    hasPrev,
    loadPage,
    loadMore,
    refresh,
    reset,
  }
}
