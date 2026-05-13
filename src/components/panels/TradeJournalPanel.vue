<script setup lang="ts">
defineProps<{ visible: boolean }>()
defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

function close() {
  // 不通过 emit，直接操作
}
</script>

<template>
  <div v-if="visible" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center">
    <div style="background:#fff;padding:40px;border-radius:8px;text-align:center">
      <h1 style="font-size:24px;margin-bottom:16px">✅ 交易日记面板已打开</h1>
      <p style="color:#666;margin-bottom:16px">如果看到这个说明 App.vue 集成和组件加载都正常</p>
      <button @click="$emit('update:visible', false); $emit('close')" style="padding:8px 24px;background:#1565c0;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:16px">关闭</button>
    </div>
  </div>
</template>
