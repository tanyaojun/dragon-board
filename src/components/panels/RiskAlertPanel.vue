<!-- RiskAlertPanel.vue -->
<template>
  <div class="risk-panel">
    <!-- 顶部：当前风险等级 -->
    <div class="risk-level" :class="riskLevel.class">
      <span class="level-icon">{{ riskLevel.icon }}</span>
      <span class="level-text">{{ riskLevel.text }}</span>
      <span class="level-desc">{{ riskLevel.desc }}</span>
    </div>

    <!-- 核心：持仓风险监控 -->
    <div class="risk-section">
      <h3>🔴 持仓风险</h3>
      <div v-for="item in positionRisks" :key="item.code" class="risk-item critical">
        <div class="risk-header">
          <span class="stock">{{ item.name }}({{ item.code }})</span>
          <span class="badge">{{ item.level }}</span>
        </div>
        <div class="risk-body">
          <span class="reason">{{ item.reason }}</span>
          <span class="suggestion">{{ item.suggestion }}</span>
        </div>
        <div class="risk-action">
          <button @click="quickSell(item.code)">立即减仓</button>
        </div>
      </div>
    </div>

    <!-- 市场整体风险 -->
    <div class="risk-section">
      <h3>⚠️ 市场风险</h3>
      <div v-for="risk in marketRisks" :key="risk.type" class="risk-item" :class="risk.level">
        <div class="risk-header">
          <span class="title">{{ risk.title }}</span>
          <span class="badge">{{ risk.levelText }}</span>
        </div>
        <div class="risk-body">
          <span class="desc">{{ risk.desc }}</span>
          <span class="advice">{{ risk.advice }}</span>
        </div>
      </div>
    </div>

    <!-- 机会预警（但要控制手） -->
    <div class="risk-section" v-if="opportunities.length">
      <h3>🟢 机会预警（控制仓位）</h3>
      <div v-for="op in opportunities.slice(0, 2)" :key="op.code" class="risk-item warning">
        <div class="risk-header">
          <span class="stock">{{ op.name }}({{ op.theme }})</span>
          <span class="badge">{{ op.signal }}</span>
        </div>
        <div class="risk-body">
          <span class="desc">{{ op.desc }}</span>
          <span class="suggestion">建议仓位：{{ op.position }}%</span>
        </div>
      </div>
    </div>

    <!-- 底部建议 -->
    <div class="risk-footer">
      <div class="advice-box" :class="adviceClass">
        <span class="advice-icon">{{ adviceIcon }}</span>
        <span class="advice-text">{{ adviceText }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'

// ========== 核心逻辑：判断当前风险等级 ==========
const riskLevel = computed(() => {
  const blocks = dataLayer.getJxbkBlocksSorted() || []
  const alerts = dataLayer.getAlerts?.() || []

  // 判断条件（根据您的经验调整）
  const hasCriticalAlert = alerts.some(a => a.level === 'critical')
  const ztCount = blocks.reduce((sum, b) => sum + (b.ztCount || 0), 0)
  const downCount = blocks.filter(b => b.change < -5).length

  if (hasCriticalAlert || downCount > 10) {
    return {
      class: 'critical',
      icon: '🔴',
      text: '高风险',
      desc: '市场亏钱效应明显，建议空仓'
    }
  }

  if (ztCount < 20 || alerts.some(a => a.level === 'warning')) {
    return {
      class: 'warning',
      icon: '🟡',
      text: '中风险',
      desc: '局部机会，严控仓位'
    }
  }

  return {
    class: 'normal',
    icon: '🟢',
    text: '低风险',
    desc: '可以操作，但别上头'
  }
})

// ========== 持仓风险 ==========
const positionRisks = computed(() => {
  // 这里需要接入您的持仓数据
  // 临时用预警数据模拟
  const alerts = dataLayer.getAlerts?.() || []

  return alerts
    .filter(a => a.type === 'leader_fall' || a.type === 'batch_explode')
    .map(a => ({
      code: a.code,
      name: a.name,
      level: a.level === 'critical' ? '紧急' : '警告',
      reason: a.message,
      suggestion: a.level === 'critical' ? '立即止损' : '减仓观察'
    }))
    .slice(0, 3)
})

// ========== 市场风险 ==========
const marketRisks = computed(() => {
  const blocks = dataLayer.getJxbkBlocksSorted() || []
  const alerts = dataLayer.getAlerts?.() || []
  const risks = []

  // 批量炸板风险
  const explodeCount = alerts.filter(a => a.type === 'batch_explode').length
  if (explodeCount > 2) {
    risks.push({
      type: 'explode',
      level: 'critical',
      levelText: '严重',
      title: '批量炸板',
      desc: `${explodeCount}个板块出现炸板潮`,
      advice: '暂停追高'
    })
  }

  // 龙头倒下风险
  const leaderFallCount = alerts.filter(a => a.type === 'leader_fall').length
  if (leaderFallCount > 1) {
    risks.push({
      type: 'leader_fall',
      level: 'warning',
      levelText: '警告',
      title: '龙头断板',
      desc: `${leaderFallCount}只龙头倒下`,
      advice: '减仓相关板块'
    })
  }

  // 轮动过快风险
  const quickRotation = blocks.filter(b => Math.abs(b.change) > 7).length
  if (quickRotation > 5) {
    risks.push({
      type: 'rotation',
      level: 'warning',
      levelText: '提示',
      title: '轮动过快',
      desc: '日内多个板块脉冲',
      advice: '不追涨，等回调'
    })
  }

  return risks
})

// ========== 机会预警（但要控制手） ==========
const opportunities = computed(() => {
  const blocks = dataLayer.getJxbkBlocksSorted() || []

  return blocks
    .filter(b => b.ztCount >= 3 && b.mainNetInflow > 0)
    .map(b => ({
      code: b.code,
      name: b.name,
      theme: b.name,
      signal: '批量涨停',
      desc: `${b.ztCount}只涨停，资金流入${(b.mainNetInflow / 1e8).toFixed(2)}亿`,
      position: b.ztCount >= 5 ? 30 : 20
    }))
    .slice(0, 2)
})

// ========== 底部建议 ==========
const adviceClass = computed(() => riskLevel.value.class)
const adviceIcon = computed(() => riskLevel.value.icon)
const adviceText = computed(() => {
  if (riskLevel.value.class === 'critical') {
    return '建议：空仓观望，保护本金'
  }
  if (riskLevel.value.class === 'warning') {
    return '建议：轻仓试错，快进快出'
  }
  return '建议：可操作，但别超过5成仓'
})

// ========== 快速减仓 ==========
const quickSell = (code) => {
  // 这里可以接入您的交易系统
  console.log('快速减仓:', code)
  alert(`已为您生成减仓指令：${code}`)
}

onMounted(() => {
  console.log('[RiskPanel] 已启动，今晚能睡好觉了')
})
</script>

<style scoped>
.risk-panel {
  padding: 16px;
  background: #1a1a1a;
  color: #fff;
  border-radius: 12px;
  max-width: 400px;
}

.risk-level {
  padding: 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  text-align: center;
}

.risk-level.critical {
  background: rgba(255, 71, 87, 0.2);
  border: 1px solid #ff4757;
}

.risk-level.warning {
  background: rgba(255, 165, 0, 0.2);
  border: 1px solid #ffa500;
}

.risk-level.normal {
  background: rgba(46, 213, 115, 0.2);
  border: 1px solid #2ed573;
}

.level-icon {
  font-size: 24px;
  margin-right: 8px;
}

.level-text {
  font-size: 18px;
  font-weight: bold;
  margin-right: 8px;
}

.level-desc {
  font-size: 12px;
  opacity: 0.8;
}

.risk-section {
  margin-bottom: 20px;
}

.risk-section h3 {
  font-size: 14px;
  color: #888;
  margin-bottom: 12px;
}

.risk-item {
  background: #222;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}

.risk-item.critical {
  border-left: 4px solid #ff4757;
}

.risk-item.warning {
  border-left: 4px solid #ffa500;
}

.risk-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.stock {
  font-weight: bold;
  color: #ffd700;
}

.badge {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
}

.critical .badge {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.warning .badge {
  background: rgba(255, 165, 0, 0.2);
  color: #ffa500;
}

.risk-body {
  font-size: 12px;
  margin-bottom: 8px;
}

.reason,
.desc {
  display: block;
  color: #aaa;
  margin-bottom: 4px;
}

.suggestion,
.advice {
  display: block;
  color: #ffd700;
  font-weight: 500;
}

.risk-action button {
  width: 100%;
  padding: 8px;
  background: rgba(255, 71, 87, 0.2);
  border: 1px solid #ff4757;
  color: #ff4757;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}

.risk-action button:hover {
  background: #ff4757;
  color: #fff;
}

.risk-footer {
  margin-top: 20px;
}

.advice-box {
  padding: 16px;
  border-radius: 8px;
  text-align: center;
}

.advice-box.critical {
  background: rgba(255, 71, 87, 0.1);
  border: 1px dashed #ff4757;
}

.advice-box.warning {
  background: rgba(255, 165, 0, 0.1);
  border: 1px dashed #ffa500;
}

.advice-box.normal {
  background: rgba(46, 213, 115, 0.1);
  border: 1px dashed #2ed573;
}

.advice-icon {
  font-size: 20px;
  margin-right: 8px;
}

.advice-text {
  font-size: 14px;
  font-weight: bold;
}
</style>
