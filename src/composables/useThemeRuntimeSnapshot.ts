import { onScopeDispose, shallowRef } from 'vue'

import { themeRuntimeStore } from '@/services/theme/ThemeRuntimeStore'

export function useThemeRuntimeSnapshot() {
  const snapshot = shallowRef(themeRuntimeStore.getSnapshot())
  const unsubscribe = themeRuntimeStore.subscribe((next) => {
    snapshot.value = next
  })
  onScopeDispose(unsubscribe)
  return snapshot
}
