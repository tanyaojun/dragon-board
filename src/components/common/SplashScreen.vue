<!-- src/components/common/SplashScreen.vue -->
<!-- 龙抬头·启动界面 | 潜龙出渊动画版 -->

<template>
  <transition name="fade" @after-leave="onAfterLeave">
    <div v-if="visible" class="splash-screen" :class="themeClass" :style="progressStyle">
      <!-- 龙鳞背景动画 -->
      <div class="dragon-scale-bg">
        <div v-for="i in 81" :key="i" class="scale" :style="{ '--i': i }"></div>
      </div>
      
      <!-- 主视觉：升龙图 -->
      <div class="dragon-container">
        <!-- 龙珠（进度指示器） -->
        <div class="dragon-pearl" :class="{ 'pulse': progress < 100 }">
          <div class="pearl-core">
            <span class="pearl-icon">{{ pearlIcon }}</span>
          </div>
          <div class="pearl-glow"></div>
        </div>
        
        <!-- 龙身（进度条） -->
        <div class="dragon-body">
          <div class="dragon-progress" :style="{ width: progress + '%' }">
            <div class="progress-glow"></div>
          </div>
        </div>
        
        <!-- 龙头（根据进度变化） -->
        <div class="dragon-head" :class="headStage">
          <span class="head-icon">{{ headIcon }}</span>
          <div class="head-shadow"></div>
        </div>
      </div>
      
      <!-- 状态文字 -->
      <div class="dragon-text">
        <h2 class="title">
          <span class="title-chinese">龙头看板</span>
          <span class="title-english">DRAGON BOARD</span>
        </h2>
        
        <div class="status-container">
          <span class="status-icon">{{ statusIcon }}</span>
          <span class="status-text">{{ displayStatus }}</span>
        </div>
        
        <!-- 龙语提示（随机显示） -->
        <div class="dragon-whisper" v-if="progress < 100">
          {{ currentWhisper }}
        </div>
        
        <!-- 进度百分比 -->
        <div class="progress-percent">
          <span class="percent-number">{{ Math.floor(progress) }}</span>
          <span class="percent-symbol">%</span>
        </div>
      </div>
      
      <!-- 底部龙纹 -->
      <div class="dragon-pattern">
        <svg width="200" height="40" viewBox="0 0 200 40" fill="none">
          <path d="M0 20 Q 25 0, 50 20 T 100 20 T 150 20 T 200 20" 
                stroke="currentColor" 
                stroke-width="2" 
                stroke-dasharray="4 4"
                class="wave-line"/>
        </svg>
      </div>
      
      <!-- 版本号 -->
      <div class="version-tag">
        <span class="version-icon">🐉</span>
        v6.0.0 · 龙抬头
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  visible: boolean
  progress: number
  status: string
}>()

const progressStyle = computed(() => ({
  '--progress': String(Math.max(0, Math.min(100, props.progress))),
}))

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update:progress', value: number): void
  (e: 'update:status', value: string): void
}>()

// 龙语库
const dragonWhispers = [
  "🐉 潜龙在渊，待时而动",
  "🔥 龙息凝聚，蓄势待发",
  "👀 龙睛开启，洞察先机",
  "✨ 龙鳞舒展，金光乍现",
  "🌊 龙游四海，数据汇聚",
  "⚡ 龙爪出鞘，快人一步",
  "💫 龙珠璀璨，算法加持",
  "🎯 龙威赫赫，精准出击",
  "🌈 龙腾九天，势不可挡",
  "🌟 见龙在田，利见大人"
]

// 随机龙语
const currentWhisper = ref(dragonWhispers[0])

// 轮播龙语
let whisperInterval: ReturnType<typeof setInterval>

onMounted(() => {
  // 每3秒更换一句龙语
  whisperInterval = setInterval(() => {
    const randomIndex = Math.floor(Math.random() * dragonWhispers.length)
    currentWhisper.value = dragonWhispers[randomIndex]
  }, 3000)
})

onUnmounted(() => {
  clearInterval(whisperInterval)
})

// 主题类（跟随系统主题）
const themeClass = computed(() => {
  const hour = new Date().getHours()
  return hour >= 6 && hour < 18 ? 'theme-light' : 'theme-dark'
})

// 龙头阶段
const headStage = computed(() => {
  if (props.progress < 30) return 'stage-dormant'      // 潜龙
  if (props.progress < 60) return 'stage-rising'       // 升龙
  if (props.progress < 90) return 'stage-soaring'      // 飞龙
  return 'stage-ascended'                               // 天龙
})

// 龙头图标
const headIcon = computed(() => {
  if (props.progress < 30) return '🐲'      // 潜龙
  if (props.progress < 60) return '🐉'      // 升龙
  if (props.progress < 90) return '🔥'      // 龙息
  return '✨'                                // 飞升
})

// 龙珠图标
const pearlIcon = computed(() => {
  if (props.progress < 30) return '⚪'
  if (props.progress < 60) return '🟡'
  if (props.progress < 90) return '🔴'
  return '💫'
})

// 状态图标
const statusIcon = computed(() => {
  const status = props.status.toLowerCase()
  if (status.includes('加载')) return '📦'
  if (status.includes('分析')) return '🧠'
  if (status.includes('初始化')) return '⚙️'
  if (status.includes('准备')) return '✅'
  if (status.includes('完成')) return '🎉'
  if (status.includes('失败')) return '❌'
  return '🐉'
})

// 美化后的状态文字
const displayStatus = computed(() => {
  const status = props.status
  // 映射为更生动的表达
  const statusMap: Record<string, string> = {
    '初始化中...': '龙睛开启',
    '加载八平台热榜数据...': '八荒探路',
    '加载热榜行情数据...': '热榜寻龙',
    '获取全市场股票列表...': '龙宫点将',
    '加载全市场行情数据': '龙游四海',
    '合并数据...': '龙鳞归位',
    '加载题材数据...': '题材觉醒',
    '初始化题材分析...': '龙脉勘探',
    '分析题材关联...': '龙气追踪',
    '同步题材数据...': '龙息同步',
    '更新数据合并...': '龙魂融合',
    '初始化算法中心...': '龙珠蓄能',
    '建立服务连接...': '龙脉贯通',
    '加载热榜数据...': '热浪来袭',
    '加载数据到表格...': '龙盘虎踞',
    '等待题材数据就绪...': '潜龙待时',
    '分析龙头...': '龙首之争',
    '算法预热中...': '龙珠温养',
    '初始化股票仓库...': '龙宫点卯',
    '准备就绪': '🐉 飞龙在天'
  }
  
  return statusMap[status] || status
})

// 动画结束
const onAfterLeave = () => {
  emit('update:visible', false)
}
</script>

<style scoped>
.splash-screen {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--splash-bg, #0a0c0e);
  color: var(--splash-text, #e6e6e6);
  font-family: 'Noto Serif SC', 'Ma Shan Zheng', system-ui, sans-serif;
  overflow: hidden;
}

/* 主题变量 */
.theme-light {
  --splash-bg: linear-gradient(135deg, #f5f0e6 0%, #e8e0d0 100%);
  --splash-text: #2c3e50;
  --splash-accent: #c49a6c;
  --splash-glow: rgba(196, 154, 108, 0.3);
  --scale-color: rgba(196, 154, 108, 0.1);
}

.theme-dark {
  --splash-bg: linear-gradient(135deg, #0f1215 0%, #1a1e24 100%);
  --splash-text: #e6e6e6;
  --splash-accent: #ffd700;
  --splash-glow: rgba(255, 215, 0, 0.3);
  --scale-color: rgba(255, 215, 0, 0.05);
}

/* 龙鳞背景 */
.dragon-scale-bg {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 150vmax;
  height: 150vmax;
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  grid-template-rows: repeat(9, 1fr);
  gap: 2px;
  opacity: 0.3;
  animation: rotateScale 60s linear infinite;
}

.scale {
  background: var(--scale-color);
  clip-path: polygon(50% 0%, 100% 30%, 80% 100%, 20% 100%, 0% 30%);
  transition: all 0.3s ease;
  animation: scaleGlow 4s ease-in-out infinite;
  animation-delay: calc(var(--i) * 0.05s);
}

@keyframes rotateScale {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to { transform: translate(-50%, -50%) rotate(360deg); }
}

@keyframes scaleGlow {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 0.8; background: var(--splash-accent); }
}

/* 龙容器 */
.dragon-container {
  position: relative;
  width: 400px;
  height: 200px;
  margin-bottom: 40px;
  z-index: 10;
}

/* 龙珠 */
.dragon-pearl {
  position: absolute;
  top: 0;
  left: 0;
  width: 60px;
  height: 60px;
  transform: translateX(calc(var(--progress, 0) * 3.4px));
  transition: transform 0.3s ease;
  z-index: 3;
}

.pearl-core {
  position: absolute;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle at 30% 30%, #fff, var(--splash-accent));
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  box-shadow: 0 0 30px var(--splash-glow);
}

.pearl-glow {
  position: absolute;
  top: -10px;
  left: -10px;
  right: -10px;
  bottom: -10px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--splash-glow) 0%, transparent 70%);
  animation: pearlPulse 2s ease-in-out infinite;
}

@keyframes pearlPulse {
  0%, 100% { transform: scale(1); opacity: 0.5; }
  50% { transform: scale(1.2); opacity: 0.8; }
}

.pulse {
  animation: pearlFloat 1.5s ease-in-out infinite;
}

@keyframes pearlFloat {
  0%, 100% { transform: translateX(calc(var(--progress, 0) * 3.4px)) translateY(0); }
  50% { transform: translateX(calc(var(--progress, 0) * 3.4px)) translateY(-10px); }
}

/* 龙身（进度条） */
.dragon-body {
  position: absolute;
  top: 25px;
  left: 30px;
  width: 340px;
  height: 10px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  overflow: hidden;
  backdrop-filter: blur(5px);
  border: 1px solid var(--splash-accent);
}

.dragon-progress {
  position: relative;
  height: 100%;
  background: linear-gradient(90deg, 
    var(--splash-accent) 0%,
    #ffd700 50%,
    #ffaa00 100%
  );
  transition: width 0.3s ease;
  border-radius: 10px;
}

.progress-glow {
  position: absolute;
  top: 0;
  right: 0;
  width: 20px;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.5));
  filter: blur(5px);
  animation: progressGlow 1.5s linear infinite;
}

@keyframes progressGlow {
  from { transform: translateX(-20px); }
  to { transform: translateX(340px); }
}

/* 龙头 */
.dragon-head {
  position: absolute;
  top: -10px;
  left: 0;
  width: 80px;
  height: 80px;
  transform: translateX(calc(var(--progress, 0) * 3.4px - 20px));
  transition: transform 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 4;
}

.head-icon {
  font-size: 50px;
  filter: drop-shadow(0 0 20px var(--splash-glow));
  animation: headBob 2s ease-in-out infinite;
}

@keyframes headBob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.head-shadow {
  position: absolute;
  bottom: -10px;
  width: 60px;
  height: 10px;
  background: radial-gradient(ellipse at center, rgba(0,0,0,0.3) 0%, transparent 70%);
  border-radius: 50%;
  animation: shadowScale 2s ease-in-out infinite;
}

@keyframes shadowScale {
  0%, 100% { transform: scale(1); opacity: 0.3; }
  50% { transform: scale(1.2); opacity: 0.5; }
}

/* 龙头阶段特效 */
.stage-dormant .head-icon {
  filter: drop-shadow(0 0 10px #4a90e2);
}

.stage-rising .head-icon {
  filter: drop-shadow(0 0 20px #f5a623);
  animation: headRise 1.5s ease-in-out infinite;
}

@keyframes headRise {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-15px) scale(1.1); }
}

.stage-soaring .head-icon {
  filter: drop-shadow(0 0 30px #ff4d4d);
  animation: headSoar 1s ease-in-out infinite;
}

@keyframes headSoar {
  0%, 100% { transform: translateY(-5px) rotate(-5deg); }
  50% { transform: translateY(-20px) rotate(5deg); }
}

.stage-ascended .head-icon {
  filter: drop-shadow(0 0 40px gold);
  animation: headAscend 0.8s ease-in-out infinite;
}

@keyframes headAscend {
  0%, 100% { transform: translateY(-10px) scale(1.1); }
  50% { transform: translateY(-25px) scale(1.2); }
}

/* 文字区域 */
.dragon-text {
  text-align: center;
  z-index: 10;
  position: relative;
}

.title {
  margin-bottom: 30px;
}

.title-chinese {
  display: block;
  font-size: 48px;
  font-weight: 700;
  background: linear-gradient(135deg, var(--splash-accent), #ffd700);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: 0 0 30px var(--splash-glow);
  letter-spacing: 8px;
  animation: titleGlow 2s ease-in-out infinite;
}

@keyframes titleGlow {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.2); }
}

.title-english {
  display: block;
  font-size: 16px;
  letter-spacing: 12px;
  color: var(--splash-text);
  opacity: 0.6;
  margin-top: 8px;
  text-transform: uppercase;
}

.status-container {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 20px;
}

.status-icon {
  font-size: 24px;
  animation: statusSpin 3s linear infinite;
}

@keyframes statusSpin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.status-text {
  font-size: 20px;
  font-weight: 500;
  color: var(--splash-text);
  text-shadow: 0 0 10px var(--splash-glow);
}

.dragon-whisper {
  font-size: 16px;
  color: var(--splash-accent);
  opacity: 0.8;
  margin-bottom: 20px;
  font-style: italic;
  height: 24px;
  animation: whisperFade 3s ease-in-out;
}

@keyframes whisperFade {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 0.8; transform: translateY(0); }
}

.progress-percent {
  font-size: 36px;
  font-weight: 300;
}

.percent-number {
  font-size: 72px;
  font-weight: 700;
  color: var(--splash-accent);
  text-shadow: 0 0 20px var(--splash-glow);
}

.percent-symbol {
  font-size: 36px;
  opacity: 0.6;
  margin-left: 4px;
}

/* 底部龙纹 */
.dragon-pattern {
  position: absolute;
  bottom: 40px;
  left: 0;
  width: 100%;
  display: flex;
  justify-content: center;
  color: var(--splash-accent);
  opacity: 0.3;
}

.wave-line {
  animation: waveMove 3s linear infinite;
}

@keyframes waveMove {
  from { stroke-dashoffset: 0; }
  to { stroke-dashoffset: 100; }
}

/* 版本号 */
.version-tag {
  position: absolute;
  bottom: 20px;
  right: 20px;
  font-size: 12px;
  color: var(--splash-text);
  opacity: 0.5;
  display: flex;
  align-items: center;
  gap: 4px;
}

.version-icon {
  font-size: 14px;
  animation: versionBounce 2s ease-in-out infinite;
}

@keyframes versionBounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.5s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 响应式 */
@media (max-width: 768px) {
  .dragon-container {
    width: 300px;
    height: 150px;
  }
  
  .dragon-body {
    width: 240px;
    left: 30px;
  }
  
  .title-chinese {
    font-size: 36px;
  }
  
  .title-english {
    font-size: 12px;
    letter-spacing: 8px;
  }
  
  .status-text {
    font-size: 16px;
  }
  
  .percent-number {
    font-size: 48px;
  }
}

@media (max-width: 480px) {
  .dragon-container {
    width: 260px;
  }
  
  .dragon-body {
    width: 200px;
    left: 30px;
  }
  
  .title-chinese {
    font-size: 28px;
    letter-spacing: 4px;
  }
}
</style>
