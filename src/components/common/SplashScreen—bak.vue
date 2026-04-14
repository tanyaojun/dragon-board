<!-- src/components/common/SplashScreen.vue -->
<template>
  <div class="splash-screen" :class="{ hidden: !visible }">
    <div class="splash-container">
      <div class="splash-logo">
        <span class="logo-icon">🐲</span>
        <h1 class="logo-title">龙头看板系统</h1>
      </div>

      <div class="splash-version">
        <span class="version-badge">v1.0.0</span>
        <span class="version-author">作者：老谭</span>
      </div>

      <div class="splash-progress">
        <div class="progress-bar-container">
          <div class="progress-bar" :style="{ width: progress + '%' }"></div>
        </div>
        <div class="progress-status">
          <span class="status-text">{{ statusText }}</span>
          <span class="status-percent">{{ progress }}%</span>
        </div>
      </div>

      <div class="splash-loading">
        <div class="loading-dots">
          <span class="dot"></span>
          <span class="dot"></span>
          <span class="dot"></span>
        </div>
      </div>

      <div class="splash-footer">
        <p class="copyright">© 2026 龙头看板系统 · 数据仅供参考</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  progress?: number
  status?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update:progress', value: number): void
  (e: 'update:status', value: string): void
}>()

// 内部状态
const progress = ref(props.progress || 0)
const statusText = ref(props.status || '初始化中...')

// 监听外部 prop 变化
watch(
  () => props.progress,
  (val) => {
    if (val !== undefined) {
      progress.value = val
      emit('update:progress', val)
    }
  },
  { immediate: true },
)

watch(
  () => props.status,
  (val) => {
    if (val !== undefined) {
      statusText.value = val
      emit('update:status', val)
    }
  },
  { immediate: true },
)

// 暴露方法给父组件
defineExpose({
  setProgress(value: number) {
    progress.value = value
    emit('update:progress', value)
  },
  setStatus(text: string) {
    statusText.value = text
    emit('update:status', text)
  },
})
</script>

<style scoped>
.splash-screen {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  transition:
    opacity 0.5s ease,
    visibility 0.5s ease;
}

.splash-screen.hidden {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}

.splash-container {
  max-width: 500px;
  width: 90%;
  text-align: center;
  animation: fadeInUp 0.8s ease;
}

.splash-logo {
  margin-bottom: 30px;
}

.logo-icon {
  font-size: 80px;
  display: block;
  margin-bottom: 20px;
  animation: pulse 2s infinite;
}

.logo-title {
  font-size: 32px;
  font-weight: 700;
  color: #ffd700;
  text-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
  margin: 0;
  letter-spacing: 2px;
}

.splash-version {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 40px;
}

.version-badge {
  padding: 6px 16px;
  background: rgba(255, 127, 80, 0.2);
  border: 1px solid #ff7f50;
  border-radius: 30px;
  color: #ff7f50;
  font-size: 14px;
  font-weight: 500;
}

.version-author {
  padding: 6px 16px;
  background: rgba(52, 152, 219, 0.2);
  border: 1px solid #3498db;
  border-radius: 30px;
  color: #3498db;
  font-size: 14px;
  font-weight: 500;
}

.splash-progress {
  margin-bottom: 30px;
}

.progress-bar-container {
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #ff7f50, #ff4757);
  border-radius: 3px;
  transition: width 0.3s ease;
  box-shadow: 0 0 10px rgba(255, 127, 80, 0.5);
}

.progress-status {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #e0e0e0;
  font-size: 14px;
}

.status-text {
  color: #ff7f50;
}

.status-percent {
  font-weight: 600;
  color: #ffffff;
}

.splash-loading {
  margin-bottom: 60px;
}

.loading-dots {
  display: flex;
  justify-content: center;
  gap: 8px;
}

.dot {
  width: 8px;
  height: 8px;
  background: #ff7f50;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;
}

.dot:nth-child(1) {
  animation-delay: -0.32s;
}

.dot:nth-child(2) {
  animation-delay: -0.16s;
}

.splash-footer {
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
}

.copyright {
  margin: 0;
  letter-spacing: 1px;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
  }
}

@keyframes bounce {
  0%,
  80%,
  100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

/* 亮色主题支持 */
:root[data-theme='light'] .splash-screen {
  background: linear-gradient(135deg, #f5f5f7 0%, #e8e8ed 100%);
}

:root[data-theme='light'] .logo-title {
  color: #b8860b;
}

:root[data-theme='light'] .status-text {
  color: #c97c3b;
}

:root[data-theme='light'] .dot {
  background: #c97c3b;
}

:root[data-theme='light'] .splash-footer {
  color: rgba(0, 0, 0, 0.2);
}

:root[data-theme='matrix'] .splash-screen {
  background: linear-gradient(135deg, #0c0c0c 0%, #1a1a1a 100%);
}

:root[data-theme='matrix'] .logo-title {
  color: #00ff00;
  text-shadow: 0 0 20px rgba(0, 255, 0, 0.3);
}

:root[data-theme='matrix'] .version-badge {
  border-color: #00ff00;
  color: #00ff00;
}

:root[data-theme='matrix'] .progress-bar {
  background: linear-gradient(90deg, #00ff00, #00cc00);
}

:root[data-theme='cream'] .splash-screen {
  background: linear-gradient(135deg, #fef7e9 0%, #fdf0d8 100%);
}

:root[data-theme='cream'] .logo-title {
  color: #b8860b;
}

:root[data-theme='cream'] .version-author {
  border-color: #8b5a2b;
  color: #8b5a2b;
}
</style>
