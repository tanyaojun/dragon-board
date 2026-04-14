<!-- src/components/panels/config/AboutConfig.vue -->
<template>
  <div class="config-section about">
    <h4>🐲 龙头看板系统</h4>
    <p>版本: 6.0.0</p>
    <p>作者: 老谭</p>
    <p>最后更新: 2026-02-16</p>

    <h4>📦 模块版本</h4>
    <ul>
      <li>ConfigManager: 1.0.0</li>
      <li>LRUCache: 2.0.0</li>
      <li>DataLoader: 7.0.0</li>
      <li>RefreshManager: 3.0.0</li>
      <li>ThemeManager: 3.0.0</li>
      <li>AlgorithmManager: 2.4.0</li>
    </ul>

    <h4>🔧 配置说明</h4>
    <p>所有配置修改后需要点击"应用修改"才能生效。</p>
    <p>配置会自动保存到本地，刷新页面后不会丢失。</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  config: any
}>()
</script>

<style scoped>
.config-section {
  margin-bottom: 24px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.config-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: var(--color-highlight);
}

.config-section p {
  margin-bottom: 8px;
  color: var(--text-primary);
}

.config-section ul {
  list-style: none;
  padding: 0;
  margin-bottom: 16px;
}

.config-section li {
  padding: 4px 0;
  color: var(--text-secondary);
}
</style>