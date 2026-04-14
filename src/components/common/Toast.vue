<!-- src/components/common/Toast.vue -->
<template>
  <div class="toast-container">
    <transition-group name="toast">
      <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.type" @click="removeToast(toast.id)">
        <span class="toast-icon">{{ icons[toast.type] }}</span>
        <span class="toast-message">{{ toast.message }}</span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
  duration: number
}

const icons = {
  success: '✅',
  error: '❌',
  warning: '⚠️',
  info: 'ℹ️',
}

const toasts = ref<Toast[]>([])
let nextId = 1
let offHandler: (() => void) | null = null

onMounted(() => {
  // 监听 Toast 事件
  offHandler = EventManager.on(AppEvents.UI.TOAST, (data: any) => {
    showToast(data.message, data.duration, data.type)
  })
})

onUnmounted(() => {
  if (offHandler) offHandler()
})

function showToast(message: string, duration = 2000, type: Toast['type'] = 'info') {
  const id = nextId++
  toasts.value.push({ id, message, type, duration })

  setTimeout(() => {
    removeToast(id)
  }, duration)
}

function removeToast(id: number) {
  const index = toasts.value.findIndex((t) => t.id === id)
  if (index !== -1) {
    toasts.value.splice(index, 1)
  }
}
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 80px;
  right: 24px;
  z-index: 10050;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}

.toast {
  min-width: 280px;
  max-width: 360px;
  padding: 12px 20px;
  border-radius: 6px;
  color: white;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
  display: flex;
  align-items: center;
  gap: 12px;
  backdrop-filter: blur(8px);
  cursor: pointer;
  pointer-events: auto;
  animation: slideIn 0.3s ease;
}

.toast.success {
  background: rgba(46, 213, 115, 0.95);
}

.toast.error {
  background: rgba(255, 71, 87, 0.95);
}

.toast.warning {
  background: rgba(255, 165, 2, 0.95);
}

.toast.info {
  background: rgba(52, 152, 219, 0.95);
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.toast-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }

  to {
    transform: translateX(0);
    opacity: 1;
  }
}

.toast-icon {
  font-size: 18px;
}
</style>
