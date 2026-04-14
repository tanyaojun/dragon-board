<!-- src/components/panels/BacktestPanel.vue -->
<!-- 回测面板 -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="backtest-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <h3>📊 策略回测系统</h3>
        <button class="btn-icon" @click="close">✕</button>
      </div>

      <div class="panel-tabs">
        <button v-for="tab in tabs" :key="tab.value" class="tab-btn" :class="{ active: activeTab === tab.value }"
          @click="activeTab = tab.value">
          {{ tab.label }}
        </button>
      </div>

      <div class="panel-content">
        <!-- 策略参数配置 -->
        <div class="params-section">
          <h4>⚙️ 策略参数</h4>
          <div class="params-grid">
            <div class="param-item">
              <label>策略类型</label>
              <select v-model="params.strategy">
                <option value="chase">追涨杀跌</option>
                <option value="mainline">主线龙头</option>
                <option value="rotation_speed">轮动速度择时</option>
                <option value="market_phase">市场阶段择时</option>
              </select>
            </div>
            <div class="param-item">
              <label>持有天数</label>
              <input type="number" v-model.number="params.holdDays" min="1" max="10" />
            </div>
            <div class="param-item">
              <label>止损(%)</label>
              <input type="number" v-model.number="params.stopLoss" step="1" />
            </div>
            <div class="param-item">
              <label>止盈(%)</label>
              <input type="number" v-model.number="params.takeProfit" step="1" />
            </div>
            <div class="param-item" v-if="params.strategy === 'chase'">
              <label>最小强度</label>
              <input type="number" v-model.number="params.minStrengthScore" step="10" />
            </div>
            <div class="param-item" v-if="params.strategy === 'chase'">
              <label>排名上升阈值</label>
              <input type="number" v-model.number="params.minRankChange" step="1" />
            </div>
            <div class="param-item" v-if="params.strategy === 'mainline'">
              <label>最小持续天数</label>
              <input type="number" v-model.number="params.minPersistentDays" step="1" />
            </div>
            <div class="param-item" v-if="params.strategy === 'rotation_speed'">
              <label>买入速度阈值</label>
              <input type="number" v-model.number="params.buySpeed" step="5" />
            </div>
            <div class="param-item" v-if="params.strategy === 'rotation_speed'">
              <label>卖出速度阈值</label>
              <input type="number" v-model.number="params.sellSpeed" step="5" />
            </div>
          </div>
          <button class="btn-run" @click="runBacktest" :disabled="loading">
            {{ loading ? '回测中...' : '🚀 运行回测' }}
          </button>
        </div>

        <!-- 回测结果 -->
        <div v-if="result" class="result-section">
          <h4>📈 回测结果</h4>
          
          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-value" :class="result.totalReturn >= 0 ? 'positive' : 'negative'">
                {{ result.totalReturn.toFixed(2) }}%
              </div>
              <div class="stat-label">总收益率</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ result.annualizedReturn.toFixed(2) }}%</div>
              <div class="stat-label">年化收益</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ result.winRate.toFixed(1) }}%</div>
              <div class="stat-label">胜率</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ result.maxDrawdown.toFixed(1) }}%</div>
              <div class="stat-label">最大回撤</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ result.sharpeRatio.toFixed(2) }}</div>
              <div class="stat-label">夏普比率</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ result.tradeCount }}</div>
              <div class="stat-label">交易次数</div>
            </div>
          </div>

          <!-- 资金曲线 -->
          <div class="equity-chart">
            <h4>📉 资金曲线</h4>
            <div class="chart-container" ref="chartRef"></div>
          </div>

          <!-- 月度收益 -->
          <div class="monthly-returns">
            <h4>📅 月度收益</h4>
            <div class="monthly-grid">
              <div v-for="m in result.monthlyReturns.slice(-12)" :key="m.month" class="month-item"
                :class="m.return >= 0 ? 'positive' : 'negative'">
                <span class="month">{{ m.month.slice(5) }}</span>
                <span class="return">{{ m.return >= 0 ? '+' : '' }}{{ m.return.toFixed(1) }}%</span>
              </div>
            </div>
          </div>

          <!-- 板块统计 -->
          <div class="sector-stats">
            <h4>🏭 板块表现</h4>
            <div class="stats-table">
              <div v-for="s in result.sectorStats.slice(0, 10)" :key="s.sector" class="stats-row">
                <span class="sector-name">{{ s.sector }}</span>
                <span class="sector-trades">{{ s.trades }}次</span>
                <span class="sector-winrate">{{ s.winRate.toFixed(0) }}%</span>
                <span class="sector-return" :class="s.avgReturn >= 0 ? 'positive' : 'negative'">
                  {{ s.avgReturn >= 0 ? '+' : '' }}{{ s.avgReturn.toFixed(1) }}%
                </span>
              </div>
            </div>
          </div>

          <!-- 龙头级别统计 -->
          <div class="leader-stats">
            <h4>👑 龙头级别表现</h4>
            <div class="stats-table">
              <div v-for="l in result.leaderStats" :key="l.level" class="stats-row">
                <span class="leader-level">{{ l.level || '普通' }}</span>
                <span class="leader-trades">{{ l.trades }}次</span>
                <span class="leader-winrate">{{ l.winRate.toFixed(0) }}%</span>
                <span class="leader-return" :class="l.avgReturn >= 0 ? 'positive' : 'negative'">
                  {{ l.avgReturn >= 0 ? '+' : '' }}{{ l.avgReturn.toFixed(1) }}%
                </span>
              </div>
            </div>
          </div>

          <!-- 交易记录 -->
          <div class="trades-list">
            <h4>📋 交易记录</h4>
            <div class="trades-table">
              <div v-for="trade in result.trades.slice(-20)" :key="trade.date + trade.action" class="trade-row"
                :class="trade.action">
                <span class="trade-date">{{ trade.date }}</span>
                <span class="trade-sector">{{ trade.sector }}</span>
                <span class="trade-leader">{{ trade.leaderName }}</span>
                <span class="trade-level">{{ trade.leaderLevel }}</span>
                <span class="trade-action">{{ trade.action === 'buy' ? '买入' : '卖出' }}</span>
                <span class="trade-return" :class="trade.returnRate >= 0 ? 'positive' : 'negative'">
                  {{ trade.returnRate >= 0 ? '+' : '' }}{{ trade.returnRate.toFixed(1) }}%
                </span>
                <span class="trade-reason">{{ trade.reason }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="!loading" class="empty-state">
          <span class="empty-icon">📊</span>
          <span>点击运行回测开始分析</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { RotationBacktest, type BacktestResult, type StrategyParams } from '@/services/backtest/RotationBacktest'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void; (e: 'close'): void }>()

const { panelRef, panelStyle } = usePanel({
  name: 'BacktestPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="回测"]'],
  onClose: () => close()
})

const activeTab = ref('params')
const loading = ref(false)
const result = ref<BacktestResult | null>(null)
const chartRef = ref<HTMLElement>()

const tabs = [
  { value: 'params', label: '⚙️ 参数配置' },
  { value: 'results', label: '📈 回测结果' }
]

const params = ref<StrategyParams>({
  strategy: 'chase',
  holdDays: 2,
  stopLoss: -5,
  takeProfit: 10,
  initialCapital: 100000,
  minRankChange: -5,
  minStrengthScore: 50,
  maxRotationSpeed: 70,
  minPersistentDays: 3,
  buySpeed: 30,
  sellSpeed: 60
})

const backtest = new RotationBacktest()

async function runBacktest() {
  loading.value = true
  try {
    result.value = await backtest.run(params.value)
    activeTab.value = 'results'
    setTimeout(() => drawChart(), 100)
  } catch (error) {
    console.error('回测失败:', error)
  } finally {
    loading.value = false
  }
}

function drawChart() {
  if (!chartRef.value || !result.value) return
  
  const canvas = document.createElement('canvas')
  canvas.width = chartRef.value.clientWidth
  canvas.height = 300
  chartRef.value.innerHTML = ''
  chartRef.value.appendChild(canvas)
  
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  
  const equityCurve = result.value.equityCurve
  const values = equityCurve.map(p => p.equity)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min
  const width = canvas.width
  const height = canvas.height
  const step = width / (values.length - 1)
  
  ctx.clearRect(0, 0, width, height)
  ctx.beginPath()
  ctx.strokeStyle = '#ffa502'
  ctx.lineWidth = 2
  
  values.forEach((v, i) => {
    const x = i * step
    const y = height - ((v - min) / range) * (height - 40) - 20
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
  
  // 画基准线
  ctx.beginPath()
  ctx.strokeStyle = '#7f8c8d'
  ctx.setLineDash([5, 5])
  const baselineY = height - ((100000 - min) / range) * (height - 40) - 20
  ctx.moveTo(0, baselineY)
  ctx.lineTo(width, baselineY)
  ctx.stroke()
  ctx.setLineDash([])
}

function close() {
  emit('update:visible', false)
  emit('close')
}

onUnmounted(() => {
  // cleanup
})
</script>

<style scoped>
.backtest-panel {
  position: fixed;
  width: 800px;
  max-width: 90vw;
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  z-index: 10006;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
}

.tab-btn {
  padding: 8px 16px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
}

.panel-content {
  padding: 20px;
  max-height: calc(85vh - 120px);
  overflow-y: auto;
}

.params-section {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 16px;
}

.params-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin: 16px 0;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-item label {
  font-size: 11px;
  color: var(--text-secondary);
}

.param-item input,
.param-item select {
  padding: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
}

.btn-run {
  width: 100%;
  padding: 12px;
  background: var(--color-highlight);
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: bold;
  cursor: pointer;
}

.result-section {
  margin-top: 20px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin: 16px 0;
}

.stat-card {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 12px;
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
}

.stat-value.positive { color: #ff4757; }
.stat-value.negative { color: #2ed573; }

.stat-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.chart-container {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 16px;
  margin: 16px 0;
  height: 300px;
}

.monthly-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin: 12px 0;
}

.month-item {
  display: flex;
  justify-content: space-between;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.month-item.positive { background: rgba(255, 71, 87, 0.1); }
.month-item.negative { background: rgba(46, 213, 115, 0.1); }

.stats-table, .trades-table {
  background: var(--bg-secondary);
  border-radius: 12px;
  overflow: auto;
  max-height: 300px;
}

.stats-row, .trade-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1.5fr;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-color);
}

.trade-row {
  grid-template-columns: 80px 100px 100px 60px 50px 70px 1fr;
}

.trade-row.buy { background: rgba(255, 71, 87, 0.05); }
.trade-row.sell { background: rgba(46, 213, 115, 0.05); }

.positive { color: #ff4757; }
.negative { color: #2ed573; }

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  gap: 16px;
  color: var(--text-secondary);
}

.empty-icon { font-size: 48px; opacity: 0.5; }
</style>