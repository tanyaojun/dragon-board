<!-- src/components/panels/DragonThronePanel.vue -->
<!-- 真龙天子面板 - 完整版 v4.0 (集成usePanelData) -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="dragon-throne-mask" @click.self="close">

      <div v-if="visible" class="dragon-throne-panel" :style="panelStyle" ref="panelRef" @click.stop>
        <!-- 龙纹背景 -->
        <div class="dragon-bg"></div>

        <!-- 面板头部 - 龙纹装饰 -->
        <div class="panel-header">
          <div class="header-left">
            <span class="panel-icon">🐉</span>
            <h3>真龙天子 · 龙气榜</h3>
            <span class="dragon-badge" :class="{ 'golden': hasGoldenDragon }">
              {{ dynastyTitle }}
            </span>
          </div>
          <div class="header-actions">
            <button class="btn-icon" @click="handleRefresh" title="刷新龙气" :disabled="loading">
              <span class="icon" :class="{ rotating: loading }">⚡</span>
            </button>
            <button class="btn-icon" @click="toggleAutoRefresh" :title="autoRefresh ? '自动刷新中' : '开启自动刷新'">
              <span class="icon" :class="{ 'text-golden': autoRefresh }">🔄</span>
            </button>
            <button class="btn-icon close" @click="close">
              <span class="icon">✕</span>
            </button>
          </div>
        </div>

        <!-- 加载中状态 -->
        <div v-if="loading" class="loading-state">
          <div class="loading-spinner"></div>
          <div class="loading-text">龙气汇聚中...</div>
        </div>

        <!-- 错误状态 -->
        <div v-else-if="error" class="error-state">
          <span class="error-icon">⚠️</span>
          <span class="error-text">{{ error }}</span>
          <button class="retry-btn" @click="loadData">重试</button>
        </div>

        <!-- 内容区域 - 仅在成功加载后显示 -->
        <template v-else>
          <!-- 龙气总览 -->
          <div class="dragon-overview">
            <!-- 龙脉走势图 -->
            <div class="dragon-chart">
              <canvas ref="dragonChartCanvas" width="400" height="100"></canvas>
              <div class="chart-markers">
                <div v-for="vein in topDragonVeins" :key="vein.id" class="vein-marker"
                  :style="{ left: getVeinPosition(vein) + '%' }">
                  <span class="vein-name">{{ vein.name }}</span>
                  <span class="vein-phase" :class="vein.phase">{{ vein.phase }}</span>
                </div>
              </div>
            </div>

            <!-- 龙气统计 -->
            <div class="dragon-stats">
              <div class="stat-item" title="真龙 - 龙气值800以上">
                <span class="stat-label">👑 真龙</span>
                <span class="stat-value golden">{{ dragonStats.golden }}</span>
              </div>
              <div class="stat-item" title="准龙 - 龙气值600-800">
                <span class="stat-label">🐉 准龙</span>
                <span class="stat-value purple">{{ dragonStats.purple }}</span>
              </div>
              <div class="stat-item" title="平均龙气值">
                <span class="stat-label">🔥 平均龙气</span>
                <span class="stat-value">{{ dragonStats.avgQi }}</span>
              </div>
              <div class="stat-item" title="活跃龙脉数量">
                <span class="stat-label">📈 龙脉</span>
                <span class="stat-value">{{ dragonStats.veins }}</span>
              </div>
            </div>

            <!-- 龙气等级分布 -->
            <div class="dragon-distribution">
              <div class="dist-item" v-for="level in qiLevels" :key="level.name">
                <span class="dist-label" :class="level.class">{{ level.name }}</span>
                <div class="dist-bar">
                  <div class="dist-fill" :class="level.class" :style="{ width: getLevelPercentage(level.name) + '%' }">
                  </div>
                </div>
                <span class="dist-count">{{ level.count }}</span>
              </div>
            </div>
          </div>

          <!-- 龙气榜 -->
          <div class="dragon-section">
            <div class="section-header">
              <h4>🏆 龙气排行榜</h4>
              <div class="header-tabs">
                <button class="tab-btn" :class="{ active: dragonFilter === 'all' }"
                  @click="dragonFilter = 'all'">全部</button>
                <button class="tab-btn" :class="{ active: dragonFilter === '真龙' }"
                  @click="dragonFilter = '真龙'">真龙</button>
                <button class="tab-btn" :class="{ active: dragonFilter === '准龙' }"
                  @click="dragonFilter = '准龙'">准龙</button>
                <button class="tab-btn" :class="{ active: dragonFilter === '蛟龙' }"
                  @click="dragonFilter = '蛟龙'">蛟龙</button>
              </div>
            </div>

            <div class="dragon-list">
              <div v-for="item in filteredDragons" :key="item.leader.code" class="dragon-card"
                :class="`dragon-${item.qi.level}`" @click="showDragonDetail(item.leader)">

                <!-- 龙气光效 -->
                <div class="dragon-aura" :style="{
                  background: `radial-gradient(circle at center, ${item.qi.color}40, transparent 70%)`
                }"></div>

                <div class="dragon-header">
                  <div class="dragon-title">
                    <span class="dragon-rank">#{{ item.rank }}</span>
                    <span class="dragon-code">{{ item.leader.code }}</span>
                    <span class="dragon-name">{{ item.leader.name }}</span>
                  </div>
                  <div class="dragon-qi-badge"
                    :style="{ background: item.qi.color, color: getBadgeTextColor(item.qi.color) }">
                    {{ item.qi.value }}
                  </div>
                </div>

                <!-- 龙气槽 -->
                <div class="dragon-qi-bar">
                  <div class="qi-label">龙气值</div>
                  <div class="qi-track">
                    <div class="qi-fill" :style="{
                      width: (item.qi.value / 1000 * 100) + '%',
                      background: `linear-gradient(90deg, ${item.qi.color}, gold)`
                    }"></div>
                  </div>
                  <div class="qi-level" :style="{ color: item.qi.color }">{{ item.qi.level }}</div>
                </div>

                <!-- 龙气来源 -->
                <div class="dragon-sources">
                  <div v-for="source in item.qi.sources.slice(0, 3)" :key="source.type" class="source-tag"
                    :title="source.desc">
                    {{ source.type }}
                    <span class="source-value">+{{ source.value }}</span>
                  </div>
                </div>

                <!-- 龙族信息 -->
                <div class="dragon-clan" v-if="item.clan">
                  <span class="clan-icon">🏰</span>
                  <span class="clan-name">{{ item.clan.name }}</span>
                  <span class="clan-gen">第{{ getClanGen(item.leader.code) }}代</span>
                  <span class="clan-relationship" :class="getClanRelationship(item.leader.code)">
                    {{ getClanRelationship(item.leader.code) }}
                  </span>
                </div>

                <!-- 龙脉信息 -->
                <div class="dragon-vein" v-if="item.vein">
                  <span class="vein-icon">⚡</span>
                  <span class="vein-name">{{ item.vein.name }}</span>
                  <span class="vein-phase" :class="item.vein.phase">
                    {{ item.vein.phase }}期
                  </span>
                  <span class="vein-intensity">{{ item.vein.intensity }}%</span>
                </div>

                <!-- 龙气阶段 -->
                <div class="dragon-stage">
                  <span class="stage-icon">{{ getStageIcon(item.leader.currentStage) }}</span>
                  <span class="stage-name">{{ getStageName(item.leader.currentStage) }}</span>
                  <span class="stage-days">{{ item.leader.stages[item.leader.stages.length - 1]?.continuousDays || 1
                    }}天</span>
                </div>

                <!-- 龙气趋势 -->
                <div class="dragon-trend">
                  <span class="trend-label">龙气趋势</span>
                  <span class="trend-value" :class="item.qi.trend">
                    {{ item.qi.trend }}
                    <span class="trend-arrow">{{ getTrendArrow(item.qi.trend) }}</span>
                  </span>
                </div>

                <!-- 预言 -->
                <div class="dragon-prophecy" v-if="item.prophecy">
                  <div class="prophecy-content">
                    <span class="prophecy-icon">🔮</span>
                    <span class="prophecy-text">{{ item.prophecy.nextStage }}</span>
                    <span class="prophecy-confidence">{{ item.prophecy.confidence }}%</span>
                  </div>
                  <div class="prophecy-detail">
                    <span>目标: ¥{{ formatPrice(item.prophecy.targetPrice) }}</span>
                    <span class="risk-level" :class="item.prophecy.riskLevel">
                      风险: {{ item.prophecy.riskLevel }}
                    </span>
                  </div>
                </div>

                <!-- 荣耀徽章 -->
                <div class="dragon-glory" v-if="item.glory">
                  <div class="glory-item" v-for="glory in getLeaderGlory(item.leader)" :key="glory">
                    {{ glory }}
                  </div>
                </div>
              </div>

              <!-- 空状态 -->
              <div v-if="filteredDragons.length === 0" class="empty-state">
                <span class="empty-icon">🌫️</span>
                <span class="empty-text">暂无{{ dragonFilter === 'all' ? '' : dragonFilter }}龙头</span>
              </div>
            </div>
          </div>

          <!-- 龙族谱系 -->
          <div class="dragon-section">
            <div class="section-header">
              <h4>🏰 龙族谱系</h4>
              <span class="header-count">{{ dragonClans.length }}族</span>
              <button class="view-more" @click="showAllClans" v-if="dragonClans.length > 4">查看全部</button>
            </div>

            <div class="clans-grid">
              <div v-for="clan in dragonClans.slice(0, 4)" :key="clan.id" class="clan-card">
                <div class="clan-header">
                  <span class="clan-name">{{ clan.name }}</span>
                  <span class="clan-founder">始祖: {{ clan.founder }}</span>
                </div>

                <!-- 族谱树 -->
                <div class="clan-tree">
                  <div v-for="member in clan.members.slice(0, 3)" :key="member.code" class="tree-node"
                    :class="member.relationship">
                    <span class="node-gen">第{{ member.generation }}代</span>
                    <span class="node-name" :title="member.name">{{ member.name }}</span>
                    <span class="node-boards">{{ member.peakBoards }}板</span>
                  </div>
                  <div v-if="clan.members.length > 3" class="tree-more">
                    等{{ clan.members.length }}位成员...
                  </div>
                </div>

                <!-- 族谱荣耀 -->
                <div class="clan-glory">
                  <div class="glory-item" title="总连板数">
                    <span class="glory-icon">📊</span>
                    {{ clan.glory.totalBoards }}
                  </div>
                  <div class="glory-item" title="最高连板">
                    <span class="glory-icon">🏆</span>
                    {{ clan.glory.maxBoards }}
                  </div>
                  <div class="glory-item" title="真龙数量">
                    <span class="glory-icon">👑</span>
                    {{ clan.glory.goldenDragons }}
                  </div>
                  <div class="glory-item" title="平均寿命">
                    <span class="glory-icon">⏳</span>
                    {{ clan.glory.avgLifespan.toFixed(1) }}h
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 龙脉走势 -->
          <div class="dragon-section">
            <div class="section-header">
              <h4>⚡ 龙脉走势</h4>
              <span class="header-count">{{ dragonVeins.length }}脉</span>
              <button class="view-more" @click="showAllVeins" v-if="dragonVeins.length > 3">查看全部</button>
            </div>

            <div class="veins-list">
              <div v-for="vein in dragonVeins.slice(0, 3)" :key="vein.id" class="vein-card">
                <div class="vein-header">
                  <span class="vein-name">{{ vein.name }}</span>
                  <span class="vein-intensity-badge" :style="{ background: getIntensityColor(vein.intensity) }">
                    {{ vein.intensity }}%
                  </span>
                </div>

                <!-- 强度条 -->
                <div class="intensity-bar">
                  <div class="intensity-fill" :style="{
                    width: vein.intensity + '%',
                    background: getIntensityColor(vein.intensity)
                  }"></div>
                </div>

                <!-- 历代龙头 -->
                <div class="vein-leaders">
                  <div v-for="(leader, idx) in vein.leaders.slice(0, 3)" :key="leader.code" class="leader-node">
                    <span class="leader-order">{{ idx + 1 }}代</span>
                    <span class="leader-name" :title="leader.name">{{ leader.name }}</span>
                    <span class="leader-boards">{{ leader.boards }}板</span>
                  </div>
                </div>

                <!-- 时间轴 -->
                <div class="vein-timeline">
                  <div class="timeline-start">{{ formatDate(vein.startTime) }}</div>
                  <div class="timeline-bar">
                    <div class="timeline-progress" :style="{
                      width: getVeinProgress(vein) + '%'
                    }"></div>
                  </div>
                  <div class="timeline-end">{{ vein.endTime ? formatDate(vein.endTime) : '进行中' }}</div>
                </div>

                <!-- 当前阶段 -->
                <div class="vein-phase-tag" :class="vein.phase">
                  {{ vein.phase }}期
                </div>
              </div>
            </div>
          </div>

          <!-- 龙气预言 -->
          <div class="dragon-section">
            <div class="section-header">
              <h4>🔮 龙气预言</h4>
              <span class="header-count">{{ prophecies.length }}条</span>
            </div>

            <div class="prophecies-list">
              <div v-for="prophecy in prophecies.slice(0, 3)" :key="prophecy.code" class="prophecy-card">
                <div class="prophecy-header">
                  <span class="prophecy-name">{{ prophecy.name }}</span>
                  <span class="prophecy-time">{{ formatTime(prophecy.timestamp) }}</span>
                </div>
                <div class="prophecy-body">
                  <span class="prophecy-from">{{ getStageName(prophecy.fromStage) }}</span>
                  <span class="prophecy-arrow">→</span>
                  <span class="prophecy-to">{{ getStageName(prophecy.toStage) }}</span>
                  <span class="prophecy-confidence">{{ prophecy.confidence }}%</span>
                </div>
                <div class="prophecy-reason">{{ prophecy.reason }}</div>
                <div class="prophecy-target">目标价: ¥{{ formatPrice(prophecy.targetPrice) }}</div>
              </div>
            </div>
          </div>

          <!-- 龙气波动 -->
          <div class="dragon-section">
            <div class="section-header">
              <h4>📊 龙气波动</h4>
              <span class="header-count">实时</span>
            </div>
            <div class="wave-container">
              <canvas ref="waveCanvas" width="400" height="80"></canvas>
            </div>
          </div>

          <!-- 最后更新时间 -->
          <div class="last-update">
            最后更新: {{ formatTime(lastUpdate) }}
          </div>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { dragonLifecycle, LIFECYCLE_STAGES } from '@/services/DragonLifecycle'
import { EventManager } from '@/utils/eventManager'
import { usePanel } from '@/composables/usePanel'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
const { panelRef, panelStyle } = usePanel({
  name: 'DragonThronePanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  onClose: () => emit('close')
})

// ========== 数据状态 ==========
const loading = ref(false)
const lastUpdate = ref(Date.now())

// 龙族数据
const dragonClans = ref<any[]>([])
const dragonVeins = ref<any[]>([])
const prophecies = ref<any[]>([])
const dragonQiMap = ref<Map<string, any>>(new Map())

// 从生命周期服务获取数据
const activeLeaders = ref<any[]>([])
const confirmedLeaders = ref<any[]>([])

// 筛选
const dragonFilter = ref('all')

// 图表
const dragonChartCanvas = ref<HTMLCanvasElement>()
const waveCanvas = ref<HTMLCanvasElement>()

// ========== 刷新数据 ==========
const refresh = async () => {
  loading.value = true
  try {
    debugLog('[DragonThronePanel] 刷新数据...')

    // 1. 获取龙头数据
    activeLeaders.value = dragonLifecycle.getActiveLeaders?.() || []
    confirmedLeaders.value = dragonLifecycle.getConfirmedLeaders?.() || []

    // 2. 获取族谱
    if (dragonLifecycle.getAllDragonClans) {
      dragonClans.value = dragonLifecycle.getAllDragonClans()
    }

    // 3. 获取龙脉
    if (dragonLifecycle.getActiveDragonVeins) {
      dragonVeins.value = dragonLifecycle.getActiveDragonVeins()
    }

    // 4. 获取预言
    if (dragonLifecycle.getProphecies) {
      prophecies.value = dragonLifecycle.getProphecies()
    }

    // 5. 获取龙气值
    const codes = activeLeaders.value.map(l => l.code)
    if (dragonLifecycle.getDragonQiBatch) {
      const qiMap = dragonLifecycle.getDragonQiBatch(codes)
      dragonQiMap.value = qiMap
    } else {
      codes.forEach(code => {
        const qi = dragonLifecycle.getDragonQi?.(code)
        if (qi) dragonQiMap.value.set(code, qi)
      })
    }

    lastUpdate.value = Date.now()

    debugLog('[DragonThronePanel] 数据刷新完成', {
      活跃龙头: activeLeaders.value.length,
      族谱: dragonClans.value.length,
      龙脉: dragonVeins.value.length,
      预言: prophecies.value.length
    })

    // 绘制图表
    await nextTick()
    drawDragonChart()
    drawWaveChart()

  } catch (error) {
    console.error('[DragonThronePanel] 刷新失败:', error)
  } finally {
    loading.value = false
  }
}

// ========== 计算属性 ==========

// 所有龙头（带龙气值）
const allDragons = computed(() => {
  return activeLeaders.value.map(leader => {
    const qi = dragonQiMap.value.get(leader.code) || generateDefaultQi(leader)
    const clan = dragonClans.value.find(c => c.members?.some((m: any) => m.code === leader.code))
    const vein = dragonVeins.value.find(v => v.stocks?.includes(leader.code))
    const prophecy = prophecies.value.find(p => p.code === leader.code)

    return {
      leader,
      qi,
      clan,
      vein,
      prophecy
    }
  }).sort((a, b) => (b.qi?.value || 0) - (a.qi?.value || 0))
})

// 统计信息
const dragonStats = computed(() => {
  const dragons = allDragons.value

  return {
    golden: dragons.filter(d => d.qi?.level === '真龙').length,
    purple: dragons.filter(d => d.qi?.level === '准龙').length,
    avgQi: Math.round(dragons.reduce((sum, d) => sum + (d.qi?.value || 0), 0) / (dragons.length || 1)),
    veins: dragonVeins.value.filter(v => !v.endTime).length,
    total: dragons.length
  }
})

// 龙气等级分布
const qiLevels = computed(() => {
  const dragons = allDragons.value

  return [
    { name: '真龙', count: dragons.filter(d => d.qi?.level === '真龙').length, color: '#ffd700' },
    { name: '准龙', count: dragons.filter(d => d.qi?.level === '准龙').length, color: '#b8860b' },
    { name: '蛟龙', count: dragons.filter(d => d.qi?.level === '蛟龙').length, color: '#f97316' },
    { name: '潜龙', count: dragons.filter(d => d.qi?.level === '潜龙').length, color: '#60a5fa' },
    { name: '凡龙', count: dragons.filter(d => d.qi?.level === '凡龙').length, color: '#9ca3af' }
  ]
})

// 筛选后的龙
const filteredDragons = computed(() => {
  let dragons = allDragons.value

  if (dragonFilter.value !== 'all') {
    dragons = dragons.filter(d => d.qi?.level === dragonFilter.value)
  }

  return dragons.slice(0, 20).map((dragon, index) => ({
    ...dragon,
    rank: index + 1
  }))
})

// 热门龙脉
const topDragonVeins = computed(() => {
  return dragonVeins.value
    .filter(v => !v.endTime)
    .sort((a, b) => b.intensity - a.intensity)
    .slice(0, 5)
})

// 是否有真龙
const hasGoldenDragon = computed(() => {
  return allDragons.value.some(d => d.qi?.level === '真龙')
})

// 朝代标题
const dynastyTitle = computed(() => {
  const goldenCount = allDragons.value.filter(d => d.qi?.level === '真龙').length
  if (goldenCount >= 3) return '盛世·三龙聚首'
  if (goldenCount >= 2) return '鼎盛·双龙戏珠'
  if (goldenCount >= 1) return '真龙现世'
  return '潜龙勿用'
})

// ========== 工具函数 ==========
// ========== 缺失的工具函数 ==========

/**
 * 获取族谱代数
 */
function getClanGen(code: string): number {
  for (const clan of dragonClans.value) {
    const member = clan.members?.find((m: any) => m.code === code)
    if (member) return member.generation
  }
  return 1
}

/**
 * 获取族谱关系
 */
function getClanRelationship(code: string): string {
  for (const clan of dragonClans.value) {
    const member = clan.members?.find((m: any) => m.code === code)
    if (member) return member.relationship
  }
  return '旁系'
}

/**
 * 获取龙头荣耀
 */
function getLeaderGlory(leader: any): string[] {
  const glories: string[] = []

  if (leader.genetics?.rating === 'SSS') glories.push('万古无一')
  else if (leader.genetics?.rating === 'SS') glories.push('千古留名')
  else if (leader.genetics?.rating === 'S') glories.push('一代天骄')

  const maxBoards = leader.stages?.reduce((max: number, s: any) =>
    Math.max(max, s.continuousDays || 0), 0) || 0

  if (maxBoards >= 10) glories.push('十全十美')
  else if (maxBoards >= 7) glories.push('七星高照')
  else if (maxBoards >= 5) glories.push('五福临门')

  return glories
}

// ========== 自动刷新相关 ==========
const autoRefresh = ref(true)
const refreshTimer = ref<NodeJS.Timeout>()

/**
 * 切换自动刷新
 */
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value

  if (autoRefresh.value) {
    startAutoRefresh()
    // 可以加个 toast 提示
  } else {
    stopAutoRefresh()
  }
}

/**
 * 启动自动刷新
 */
function startAutoRefresh() {
  stopAutoRefresh()

  refreshTimer.value = setInterval(() => {
    if (props.visible && autoRefresh.value) {
      refresh()
    }
  }, 30000) // 30秒刷新一次
}

/**
 * 停止自动刷新
 */
function stopAutoRefresh() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = undefined
  }
}

// ========== 事件处理 ==========
const handleRefresh = async () => {
  await refresh()
}

const showAllClans = () => {
  EventManager.emit('dragon:show-clans')
}

const showAllVeins = () => {
  EventManager.emit('dragon:show-veins')
}

// ========== 错误状态 ==========
const error = ref<string | null>(null)

// 修改 refresh 函数，添加错误处理
const refresh = async () => {
  loading.value = true
  error.value = null

  try {
    debugLog('[DragonThronePanel] 刷新数据...')

    // 1. 获取龙头数据
    activeLeaders.value = dragonLifecycle.getActiveLeaders?.() || []
    confirmedLeaders.value = dragonLifecycle.getConfirmedLeaders?.() || []

    // 2. 获取族谱
    if (dragonLifecycle.getAllDragonClans) {
      dragonClans.value = dragonLifecycle.getAllDragonClans()
    }

    // 3. 获取龙脉
    if (dragonLifecycle.getActiveDragonVeins) {
      dragonVeins.value = dragonLifecycle.getActiveDragonVeins()
    }

    // 4. 获取预言
    if (dragonLifecycle.getProphecies) {
      prophecies.value = dragonLifecycle.getProphecies()
    }

    // 5. 获取龙气值
    const codes = activeLeaders.value.map(l => l.code)
    if (dragonLifecycle.getDragonQiBatch) {
      const qiMap = dragonLifecycle.getDragonQiBatch(codes)
      dragonQiMap.value = qiMap
    } else {
      codes.forEach(code => {
        const qi = dragonLifecycle.getDragonQi?.(code)
        if (qi) dragonQiMap.value.set(code, qi)
      })
    }

    lastUpdate.value = Date.now()

    debugLog('[DragonThronePanel] 数据刷新完成', {
      活跃龙头: activeLeaders.value.length,
      族谱: dragonClans.value.length,
      龙脉: dragonVeins.value.length,
      预言: prophecies.value.length
    })

    // 绘制图表
    await nextTick()
    drawDragonChart()
    drawWaveChart()

  } catch (err) {
    console.error('[DragonThronePanel] 刷新失败:', err)
    error.value = err instanceof Error ? err.message : '未知错误'
  } finally {
    loading.value = false
  }
}



// 生成默认龙气值
function generateDefaultQi(leader: any): any {
  const score = leader.genetics?.totalScore || 60
  return {
    value: score * 8,
    level: score >= 85 ? '真龙' : score >= 75 ? '准龙' : score >= 65 ? '蛟龙' : '潜龙',
    color: '#9ca3af',
    sources: [],
    trend: '平稳'
  }
}

// 获取等级百分比
function getLevelPercentage(level: string): number {
  const count = allDragons.value.filter(d => d.qi?.level === level).length
  const total = allDragons.value.length || 1
  return (count / total) * 100
}

// 获取强度颜色
function getIntensityColor(intensity: number): string {
  if (intensity >= 80) return '#f97316'
  if (intensity >= 60) return '#fbbf24'
  if (intensity >= 40) return '#4ade80'
  return '#60a5fa'
}

// 获取趋势箭头
function getTrendArrow(trend: string): string {
  const map: Record<string, string> = {
    '上升': '↑',
    '平稳': '→',
    '下降': '↓'
  }
  return map[trend] || '→'
}

// 获取徽章文字颜色
function getBadgeTextColor(bgColor: string): string {
  const darkColors = ['#b8860b', '#8b6914', '#6b7280']
  return darkColors.includes(bgColor) ? '#fff' : '#000'
}

// 获取阶段名称
function getStageName(stage: string): string {
  return LIFECYCLE_STAGES[stage.toUpperCase()]?.name || stage
}

// 获取阶段图标
function getStageIcon(stage: string): string {
  return LIFECYCLE_STAGES[stage.toUpperCase()]?.icon || '🐉'
}

// 获取龙脉位置
function getVeinPosition(vein: any): number {
  const start = vein.startTime
  const now = Date.now()
  const dayMs = 24 * 60 * 60 * 1000
  return Math.min(95, Math.max(5, ((now - start) / (7 * dayMs)) * 100))
}

// 获取龙脉进度
function getVeinProgress(vein: any): number {
  if (vein.endTime) return 100
  const start = vein.startTime
  const now = Date.now()
  const dayMs = 24 * 60 * 60 * 1000
  return Math.min(100, ((now - start) / (14 * dayMs)) * 100)
}

// 格式化价格
function formatPrice(price: number): string {
  if (!price) return '-'
  if (price > 100) return price.toFixed(0)
  if (price > 10) return price.toFixed(1)
  return price.toFixed(2)
}

// 格式化时间
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
}

// 格式化日期
function formatDate(timestamp: number): string {
  const date = new Date(timestamp)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

// ========== 绘图函数 ==========

function drawDragonChart() {
  if (!dragonChartCanvas.value) return
  const ctx = dragonChartCanvas.value.getContext('2d')
  if (!ctx) return

  const width = 400
  const height = 100
  ctx.clearRect(0, 0, width, height)

  const veins = topDragonVeins.value
  if (veins.length < 2) return

  // 绘制网格
  ctx.strokeStyle = '#b8860b20'
  ctx.lineWidth = 0.5
  for (let i = 0; i <= 4; i++) {
    const y = (i / 4) * height
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }

  // 绘制曲线
  ctx.beginPath()
  ctx.strokeStyle = '#f97316'
  ctx.lineWidth = 2

  veins.forEach((vein, i) => {
    const x = (i / (veins.length - 1)) * width
    const y = height - (vein.intensity / 100) * height
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()

  // 绘制点
  veins.forEach((vein, i) => {
    const x = (i / (veins.length - 1)) * width
    const y = height - (vein.intensity / 100) * height

    ctx.beginPath()
    ctx.fillStyle = getIntensityColor(vein.intensity)
    ctx.arc(x, y, 5, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()

    ctx.fillStyle = '#fff'
    ctx.font = 'bold 8px Arial'
    ctx.textAlign = 'center'
    ctx.fillText(vein.intensity + '%', x, y - 10)
  })
}

function drawWaveChart() {
  if (!waveCanvas.value) return
  const ctx = waveCanvas.value.getContext('2d')
  if (!ctx) return

  const width = 400
  const height = 80
  ctx.clearRect(0, 0, width, height)

  // 绘制网格
  ctx.strokeStyle = '#b8860b20'
  ctx.lineWidth = 0.5
  for (let i = 0; i <= 4; i++) {
    const y = (i / 4) * height
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }

  // 绘制波动
  const goldenDragons = allDragons.value
    .filter(d => d.qi?.level === '真龙')
    .slice(0, 3)

  const colors = ['#ffd700', '#f97316', '#ef4444']

  goldenDragons.forEach((dragon, idx) => {
    if (!dragon) return

    ctx.beginPath()
    ctx.strokeStyle = colors[idx % colors.length]
    ctx.lineWidth = 1.5

    for (let i = 0; i <= 20; i++) {
      const x = (i / 20) * width
      const time = Date.now() * 0.001
      const wave = Math.sin(i * 0.3 + time + idx) * 15
      const baseY = height - ((dragon.qi?.value || 500) / 1000) * height
      const y = baseY + wave

      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
  })

  // 如果没有真龙，绘制平均线
  if (goldenDragons.length === 0) {
    const avgQi = dragonStats.value.avgQi
    ctx.beginPath()
    ctx.strokeStyle = '#b8860b'
    ctx.lineWidth = 1
    ctx.setLineDash([5, 3])
    const y = height - (avgQi / 1000) * height
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
    ctx.setLineDash([])
  }
}

// ========== 事件处理 ==========

const close = () => {
  emit('close')
  emit('update:visible', false)
}

const showDragonDetail = (leader: any) => {
  EventManager.emit('dragon:show-detail', {
    code: leader.code,
    name: leader.name
  })
}

// ========== 生命周期 ==========
onMounted(() => {
  refresh()

  const unsub = EventManager.on('dragon:lifecycle-updated', () => {
    if (props.visible) {
      refresh()
    }
  })

  onUnmounted(() => {
    unsub()
  })
})

watch(() => props.visible, (visible) => {
  if (visible) {
    refresh()
  }
})

// 监听数据变化，更新图表
watch([dragonVeins, allDragons], () => {
  if (props.visible) {
    nextTick(() => {
      drawDragonChart()
      drawWaveChart()
    })
  }
}, { deep: true })
</script>

<style scoped>
/* 之前的样式保持不变，添加以下新样式 */

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: #b8860b;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #b8860b20;
  border-top-color: #b8860b;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 16px;
}

.loading-text {
  font-size: 14px;
  color: #b8860b;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
  color: #ef4444;
}

.error-icon {
  font-size: 32px;
  margin-bottom: 12px;
}

.error-text {
  font-size: 14px;
  margin-bottom: 16px;
}

.retry-btn {
  padding: 8px 24px;
  background: #ef4444;
  border: none;
  border-radius: 20px;
  color: white;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.retry-btn:hover {
  background: #dc2626;
  transform: translateY(-1px);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: #b8860b80;
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.empty-text {
  font-size: 12px;
}

.last-update {
  padding: 12px 24px;
  text-align: right;
  font-size: 10px;
  color: #b8860b80;
  border-top: 1px solid #b8860b20;
}

/* 确保按钮在加载状态下不可点击 */
.btn-icon:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-icon:disabled:hover {
  background: none;
  transform: none;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.text-golden {
  color: #ffd700;
  text-shadow: 0 0 10px rgba(255, 215, 0, 0.5);
}

/* 龙气等级分布 */
.dragon-distribution {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dist-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dist-label {
  min-width: 40px;
  font-size: 11px;
  font-weight: 600;
}

.dist-label.golden {
  color: #ffd700;
}

.dist-label.purple {
  color: #b8860b;
}

.dist-label.red {
  color: #f97316;
}

.dist-label.blue {
  color: #60a5fa;
}

.dist-label.gray {
  color: #9ca3af;
}

.dist-bar {
  flex: 1;
  height: 6px;
  background: #2a2f40;
  border-radius: 3px;
  overflow: hidden;
}

.dist-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.dist-fill.golden {
  background: linear-gradient(90deg, #ffd700, #b8860b);
}

.dist-fill.purple {
  background: linear-gradient(90deg, #b8860b, #8b6914);
}

.dist-fill.red {
  background: linear-gradient(90deg, #f97316, #ef4444);
}

.dist-fill.blue {
  background: linear-gradient(90deg, #60a5fa, #3b82f6);
}

.dist-fill.gray {
  background: linear-gradient(90deg, #9ca3af, #6b7280);
}

.dist-count {
  min-width: 30px;
  font-size: 11px;
  font-weight: 600;
  color: #ffd700;
  text-align: right;
}

/* 龙气等级颜色 */
.dragon-真龙 .dragon-aura {
  opacity: 0.5;
}

.dragon-准龙 .dragon-aura {
  opacity: 0.3;
}

.dragon-蛟龙 .dragon-aura {
  opacity: 0.2;
}

/* 族谱关系 */
.clan-relationship {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 10px;
  margin-left: auto;
}

.clan-relationship.嫡系 {
  background: #ffd70020;
  color: #ffd700;
}

.clan-relationship.旁系 {
  background: #b8860b20;
  color: #b8860b;
}

.clan-relationship.联姻 {
  background: #ef444420;
  color: #ef4444;
}

/* 传承链 */
.clan-succession {
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid #b8860b40;
}

.succession-title {
  font-size: 10px;
  color: #b8860b;
  margin-bottom: 6px;
}

.succession-chain {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
}

.chain-node {
  color: #ffd700;
}

.chain-arrow {
  color: #b8860b;
}

/* 龙脉评级 */
.vein-rating {
  position: absolute;
  bottom: 12px;
  right: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 9px;
  font-weight: 600;
}

.vein-rating.S级龙脉 {
  background: #f9731620;
  color: #f97316;
  border: 1px solid #f97316;
}

.vein-rating.A级龙脉 {
  background: #fbbf2420;
  color: #fbbf24;
  border: 1px solid #fbbf24;
}

.vein-rating.B级龙脉 {
  background: #4ade8020;
  color: #4ade80;
  border: 1px solid #4ade80;
}

.vein-rating.C级龙脉 {
  background: #60a5fa20;
  color: #60a5fa;
  border: 1px solid #60a5fa;
}

/* 龙脉时间轴 */
.vein-timeline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 9px;
}

.timeline-start,
.timeline-end {
  color: #b8860b;
  min-width: 40px;
}

.timeline-bar {
  flex: 1;
  height: 4px;
  background: #2a2f40;
  border-radius: 2px;
  overflow: hidden;
}

.timeline-progress {
  height: 100%;
  background: #ffd700;
  border-radius: 2px;
}

/* 龙脉强度徽章 */
.vein-intensity-badge {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
  color: #000;
}

/* 查看全部按钮 */
.view-more {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid #b8860b40;
  border-radius: 16px;
  color: #b8860b;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.view-more:hover {
  background: #b8860b20;
  border-color: #b8860b;
}

/* 加载动画 */
.rotating {
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

/* 响应式调整 */
@media (max-width: 640px) {
  .dragon-stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .clans-grid {
    grid-template-columns: 1fr;
  }

  .dragon-list {
    max-height: 300px;
  }
}

.dragon-throne-panel {
  position: fixed;
  width: 800px;
  max-width: 95vw;
  max-height: 85vh;
  background: linear-gradient(145deg, #1a1f2e, #0f1319);
  border: 2px solid #b8860b;
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 30px rgba(255, 215, 0, 0.3);
  z-index: 10010;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #e5e7eb;
  position: relative;
}

/* 龙纹背景 */
.dragon-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" opacity="0.05"><path d="M20,50 Q35,20 50,50 T80,50" stroke="%23b8860b" fill="none" stroke-width="2"/><circle cx="30" cy="45" r="3" fill="%23b8860b"/><circle cx="70" cy="55" r="3" fill="%23b8860b"/></svg>');
  background-repeat: repeat;
  pointer-events: none;
}

/* 面板头部 */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(to right, #2a1f0f, #1a150a);
  border-bottom: 2px solid #b8860b;
  position: relative;
  z-index: 1;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-icon {
  font-size: 28px;
  filter: drop-shadow(0 0 10px gold);
}

.panel-header h3 {
  margin: 0;
  font-size: 18px;
  background: linear-gradient(135deg, #ffd700, #b8860b);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 700;
  letter-spacing: 2px;
}

.dragon-badge {
  padding: 4px 12px;
  background: linear-gradient(135deg, #b8860b, #8b6914);
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

/* 龙气总览 */
.dragon-overview {
  padding: 20px 24px;
  background: rgba(0, 0, 0, 0.3);
  border-bottom: 1px solid #b8860b40;
}

.dragon-chart {
  position: relative;
  height: 100px;
  margin-bottom: 16px;
}

.dragon-chart canvas {
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 12px;
}

.chart-markers {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
}

.vein-marker {
  position: absolute;
  top: -20px;
  transform: translateX(-50%);
  text-align: center;
}

.vein-name {
  display: block;
  font-size: 10px;
  color: #b8860b;
  white-space: nowrap;
}

.vein-phase {
  display: block;
  font-size: 8px;
  padding: 2px 4px;
  border-radius: 10px;
  background: #2a1f0f;
}

.vein-phase.萌芽 {
  color: #86efac;
}

.vein-phase.发展 {
  color: #fbbf24;
}

.vein-phase.高潮 {
  color: #f97316;
}

.vein-phase.衰退 {
  color: #ef4444;
}

.dragon-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat-item {
  text-align: center;
  padding: 8px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 12px;
  border: 1px solid #b8860b40;
}

.stat-label {
  display: block;
  font-size: 11px;
  color: #b8860b;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #ffd700;
  text-shadow: 0 0 10px rgba(255, 215, 0, 0.5);
}

/* 龙气列表 */
.dragon-section {
  padding: 16px 24px;
  border-bottom: 1px solid #b8860b40;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h4 {
  margin: 0;
  font-size: 14px;
  color: #b8860b;
  letter-spacing: 1px;
}

.header-count {
  padding: 2px 8px;
  background: #2a1f0f;
  border-radius: 12px;
  font-size: 11px;
  color: #ffd700;
}

.header-tabs {
  display: flex;
  gap: 8px;
}

.tab-btn {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid #b8860b40;
  border-radius: 16px;
  color: #b8860b;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: #b8860b20;
  border-color: #b8860b;
}

.tab-btn.active {
  background: #b8860b;
  color: #000;
  border-color: #b8860b;
}

/* 龙卡 */
.dragon-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 400px;
  overflow-y: auto;
}

.dragon-card {
  position: relative;
  background: linear-gradient(145deg, #1e2538, #151b2a);
  border: 1px solid #b8860b40;
  border-radius: 16px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.3s;
  overflow: hidden;
}

.dragon-card:hover {
  border-color: #b8860b;
  transform: translateY(-2px);
  box-shadow: 0 10px 20px rgba(184, 134, 11, 0.2);
}

.dragon-aura {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  opacity: 0.3;
}

.dragon-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.dragon-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dragon-rank {
  font-size: 14px;
  font-weight: 700;
  color: #b8860b;
}

.dragon-code {
  font-family: monospace;
  color: #ffd700;
  font-size: 14px;
}

.dragon-name {
  font-size: 16px;
  font-weight: 600;
}

.dragon-qi-badge {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  color: #000;
  box-shadow: 0 0 15px currentColor;
}

/* 龙气槽 */
.dragon-qi-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.qi-label {
  font-size: 11px;
  color: #b8860b;
  min-width: 40px;
}

.qi-track {
  flex: 1;
  height: 8px;
  background: #2a2f40;
  border-radius: 4px;
  overflow: hidden;
}

.qi-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.qi-level {
  font-size: 11px;
  font-weight: 600;
  min-width: 40px;
}

/* 龙气来源 */
.dragon-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.source-tag {
  padding: 4px 10px;
  background: #2a1f0f;
  border-radius: 16px;
  font-size: 10px;
  color: #b8860b;
  display: flex;
  align-items: center;
  gap: 4px;
}

.source-value {
  color: #ffd700;
  font-weight: 600;
}

/* 龙族信息 */
.dragon-clan,
.dragon-vein {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 11px;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 12px;
}

.clan-icon,
.vein-icon {
  font-size: 12px;
}

.clan-name,
.vein-name {
  color: #b8860b;
}

.clan-gen {
  color: #ffd700;
  margin-left: auto;
}

/* 荣耀称号 */
.dragon-glory {
  margin-bottom: 8px;
  padding: 4px 8px;
  background: linear-gradient(90deg, #b8860b20, transparent);
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.glory-icon {
  font-size: 12px;
}

.glory-title {
  font-size: 11px;
  font-weight: 600;
  color: #ffd700;
}

/* 龙气趋势 */
.dragon-trend {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 11px;
}

.trend-label {
  color: #b8860b;
}

.trend-value {
  padding: 2px 8px;
  border-radius: 12px;
}

.trend-value.上升 {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

.trend-value.平稳 {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
}

.trend-value.下降 {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.trend-arrow {
  margin-left: 4px;
  font-size: 12px;
}

/* 预言 */
.dragon-prophecy {
  background: rgba(184, 134, 11, 0.1);
  border: 1px dashed #b8860b;
  border-radius: 12px;
  padding: 10px;
  margin-bottom: 12px;
}

.prophecy-content {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.prophecy-icon {
  font-size: 14px;
}

.prophecy-text {
  flex: 1;
  font-size: 12px;
  color: #ffd700;
}

.prophecy-confidence {
  padding: 2px 6px;
  background: #b8860b;
  border-radius: 10px;
  font-size: 10px;
  color: #000;
}

.prophecy-detail {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #b8860b;
}

.risk-level.低 {
  color: #4ade80;
}

.risk-level.中 {
  color: #fbbf24;
}

.risk-level.高 {
  color: #ef4444;
}

/* 成就徽章 */
.dragon-achievements {
  display: flex;
  gap: 8px;
}

.achievement-badge {
  padding: 2px 8px;
  background: linear-gradient(135deg, #b8860b, #8b6914);
  border-radius: 12px;
  font-size: 9px;
  color: #fff;
}

/* 族谱卡片 */
.clans-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.clan-card {
  background: linear-gradient(145deg, #1e2538, #151b2a);
  border: 1px solid #b8860b40;
  border-radius: 12px;
  padding: 12px;
}

.clan-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #b8860b40;
}

.clan-name {
  font-size: 13px;
  font-weight: 600;
  color: #ffd700;
}

.clan-founder {
  font-size: 10px;
  color: #b8860b;
}

.clan-tree {
  margin-bottom: 12px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 11px;
  position: relative;
  padding-left: 16px;
}

.tree-node::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 8px;
  height: 1px;
  background: #b8860b40;
}

.tree-node.嫡系::after {
  content: '嫡';
  position: absolute;
  right: 0;
  font-size: 8px;
  color: #ffd700;
}

.tree-node.旁系::after {
  content: '旁';
  position: absolute;
  right: 0;
  font-size: 8px;
  color: #b8860b;
}

.node-gen {
  color: #b8860b;
  min-width: 40px;
}

.node-name {
  flex: 1;
}

.node-boards {
  color: #ffd700;
}

.tree-more {
  padding: 4px 0;
  font-size: 10px;
  color: #b8860b;
  text-align: center;
}

.clan-glory {
  display: flex;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid #b8860b40;
}

.glory-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #b8860b;
}

/* 龙脉卡片 */
.veins-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.vein-card {
  background: linear-gradient(145deg, #1e2538, #151b2a);
  border: 1px solid #b8860b40;
  border-radius: 12px;
  padding: 12px;
  position: relative;
}

.vein-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.vein-name {
  font-size: 13px;
  font-weight: 600;
  color: #ffd700;
}

.vein-intensity {
  padding: 2px 8px;
  background: #2a1f0f;
  border-radius: 12px;
  font-size: 11px;
  color: #b8860b;
}

.intensity-bar {
  height: 6px;
  background: #2a2f40;
  border-radius: 3px;
  margin-bottom: 12px;
  overflow: hidden;
}

.intensity-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.vein-leaders {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.leader-node {
  flex: 1;
  text-align: center;
  padding: 4px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  font-size: 10px;
}

.leader-order {
  display: block;
  color: #b8860b;
  margin-bottom: 2px;
}

.leader-name {
  display: block;
  font-weight: 600;
  margin-bottom: 2px;
}

.leader-boards {
  display: block;
  color: #ffd700;
}

.vein-phase-tag {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
}

.vein-phase-tag.萌芽 {
  background: #4ade8020;
  color: #4ade80;
}

.vein-phase-tag.发展 {
  background: #fbbf2420;
  color: #fbbf24;
}

.vein-phase-tag.高潮 {
  background: #f9731620;
  color: #f97316;
}

.vein-phase-tag.衰退 {
  background: #ef444420;
  color: #ef4444;
}

/* 预言列表 */
.prophecies-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prophecy-card {
  background: linear-gradient(145deg, #1e2538, #151b2a);
  border: 1px solid #b8860b40;
  border-radius: 12px;
  padding: 10px;
}

.prophecy-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.prophecy-name {
  font-size: 12px;
  font-weight: 600;
  color: #ffd700;
}

.prophecy-time {
  font-size: 10px;
  color: #b8860b;
}

.prophecy-body {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 11px;
}

.prophecy-from {
  color: #ef4444;
}

.prophecy-arrow {
  color: #b8860b;
}

.prophecy-to {
  color: #4ade80;
}

.prophecy-confidence {
  margin-left: auto;
  padding: 2px 6px;
  background: #b8860b;
  border-radius: 10px;
  font-size: 9px;
  color: #000;
}

.prophecy-reason {
  font-size: 10px;
  color: #b8860b;
  margin-bottom: 4px;
}

.prophecy-target {
  font-size: 10px;
  color: #ffd700;
}

/* 波动图 */
.wave-container {
  height: 80px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 12px;
  overflow: hidden;
}

.wave-container canvas {
  width: 100%;
  height: 100%;
}

/* 滚动条 */
.dragon-list::-webkit-scrollbar {
  width: 4px;
}

.dragon-list::-webkit-scrollbar-track {
  background: #1a1f2e;
}

.dragon-list::-webkit-scrollbar-thumb {
  background: #b8860b;
  border-radius: 2px;
}

.dragon-throne-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  z-index: 10000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}

.dragon-throne-panel {
  position: absolute;
  /* 移除 fixed 定位，改为 absolute */
  width: 800px;
  max-width: 95vw;
  max-height: 85vh;
  margin-top: 60px;
  /* 顶部留出一些空间 */
  background: linear-gradient(145deg, #1a1f2e, #0f1319);
  border: 2px solid #b8860b;
  border-radius: 24px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8), 0 0 30px rgba(255, 215, 0, 0.3);
  z-index: 10010;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: #e5e7eb;
  position: relative;
}

/* 修改生命周期面板的遮罩层（保持一致） */
.lifecycle-panel-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  z-index: 10000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}

.lifecycle-panel {
  position: absolute;
  width: 520px;
  max-width: 95vw;
  max-height: 85vh;
  margin-top: 60px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(20px);
  animation: slideIn 0.2s ease;
  color: #e5e7eb;
}
</style>
