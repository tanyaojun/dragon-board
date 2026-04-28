<!-- src/components/panels/EmotionMonitorPanel.vue -->

<template>
  <Teleport to="body">
    <div v-if="visible" class="emotion-panel" :style="panelStyle" ref="panelRef">
      <!-- 头部 -->
      <div class="panel-header">
        <div class="header-left">
          <span class="panel-icon">🌬️</span>
          <div class="header-title">
            <h3>情绪监控中心</h3>
            <span class="version-badge">v2.0.0</span>
          </div>
        </div>
        <div class="header-actions">
          <button class="btn-icon" @click="refresh" :class="{ rotating: loading }" title="刷新">
            <span class="icon">↻</span>
          </button>
          <button class="btn-icon" @click="exportData" title="导出数据">📥</button>
          <button class="btn-icon" @click="showHealthReport" title="健康报告">🏥</button>
          <button class="btn-icon close" @click="close" title="关闭">✕</button>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载情绪数据...</span>
      </div>

      <template v-else>
        <!-- 当前情绪卡片 - 优化版 -->
        <div class="current-emotion-card" :style="{ background: phaseGradient }">
          <div class="emotion-header">
            <div class="emotion-left">
              <div class="emotion-icon-wrapper" :style="{ background: phaseColor + '40' }">
                <span class="emotion-icon">{{ phaseIcon }}</span>
              </div>
              <div class="emotion-info">
                <div class="emotion-phase">
                  <span>{{ currentPhase?.name || '未知' }}</span>
                  <span class="emotion-score-badge">{{ currentEmotion?.overall?.toFixed(0) || 0 }}分</span>
                </div>
                <div class="emotion-tags">
                  <span class="emotion-risk" :class="`risk-${currentEmotion?.riskLevel || '中'}`">
                    {{ currentEmotion?.riskLevel || '中' }}风险
                  </span>
                  <span class="emotion-tag" v-if="currentEmotion?.themeImpact">
                    <span class="tag-dot" :style="{ background: getImpactColor(currentEmotion.themeImpact) }"></span>
                    题材影响 {{ currentEmotion.themeImpact > 0 ? '+' : ''
                    }}{{ currentEmotion.themeImpact?.toFixed(1) }}
                  </span>
                </div>
              </div>
            </div>
            <div class="emotion-stats-mini">
              <div class="stat-item">
                <span class="stat-label">涨停</span>
                <span class="stat-value">{{ marketData?.ztCount || 0 }}</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <span class="stat-label">跌停</span>
                <span class="stat-value">{{ marketData?.dtCount || 0 }}</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <span class="stat-label">炸板</span>
                <span class="stat-value">{{ marketData?.zhaban?.rate?.toFixed(0) || 0 }}%</span>
              </div>
            </div>
          </div>
          <div class="emotion-suggestion">
            <span class="quote-mark">“</span>
            {{ currentPhase?.suggestion || currentEmotion?.suggestion || '暂无建议' }}
            <span class="quote-mark">”</span>
          </div>
          <div class="emotion-footer">
            <div class="update-time">
              <span class="dot"></span>
              {{ formatTime(currentEmotion?.timestamp) }} 更新
            </div>
            <div class="hot-themes">
              <span class="fire">🔥</span> 热门题材 {{ currentEmotion?.hotThemesCount || 0 }}个
            </div>
          </div>
        </div>

        <!-- 统计卡片 - 增强版 -->
        <div class="stats-grid">
          <div class="stat-card" @click="activeTab = 'phases'">
            <div class="stat-icon" style="background: rgba(255, 215, 0, 0.1); color: #ffd700">
              📊
            </div>
            <div class="stat-content">
              <span class="stat-label">情绪阶段</span>
              <span class="stat-value">{{ phaseCount }}种</span>
            </div>
          </div>
          <div class="stat-card" @click="activeTab = 'history'">
            <div class="stat-icon" style="background: rgba(46, 213, 115, 0.1); color: #2ed573">
              📈
            </div>
            <div class="stat-content">
              <span class="stat-label">分析次数</span>
              <span class="stat-value">{{ totalAnalysisCount }}</span>
            </div>
          </div>
          <div class="stat-card" @click="activeTab = 'adjustments'">
            <div class="stat-icon" style="background: rgba(255, 71, 87, 0.1); color: #ff4757">
              ⚖️
            </div>
            <div class="stat-content">
              <span class="stat-label">权重调整</span>
              <span class="stat-value">{{ totalAdjustments }}</span>
            </div>
          </div>
          <div class="stat-card" @click="activeTab = 'performance'">
            <div class="stat-icon" style="background: rgba(52, 152, 219, 0.1); color: #3498db">
              ⏱️
            </div>
            <div class="stat-content">
              <span class="stat-label">性能指标</span>
              <span class="stat-value">{{ apiStats.length }}项</span>
            </div>
          </div>
        </div>

        <!-- 标签页 - 优化版 -->
        <div class="panel-tabs">
          <button v-for="tab in tabs" :key="tab.value" class="tab-btn" :class="{ active: activeTab === tab.value }"
            @click="activeTab = tab.value">
            <span class="tab-icon">{{ tab.icon }}</span>
            <span class="tab-label">{{ tab.label }}</span>
            <span v-if="tab.count" class="tab-count">{{ tab.count }}</span>
          </button>
        </div>

        <!-- 内容区域 -->
        <div class="panel-content">
          <!-- 阶段分布视图 -->
          <div v-if="activeTab === 'phases'" class="phases-view">
            <div class="phase-distribution">
              <div class="section-header">
                <h4>🎯 情绪阶段分布</h4>
                <span class="section-desc">近{{ emotionHistory.length }}次分析</span>
              </div>
              <div class="distribution-chart">
                <div v-for="(stat, phase) in sortedPhaseStats" :key="phase" class="distribution-item">
                  <div class="distribution-label">
                    <span class="phase-color" :style="{ background: getPhaseColor(phase) }"></span>
                    <span class="phase-name">{{ phase }}</span>
                  </div>
                  <div class="distribution-bar-container">
                    <div class="distribution-bar" :style="{
                      width: (stat.count / totalAnalysisCount) * 100 + '%',
                      background: getPhaseColor(phase),
                    }">
                      <span class="bar-percent" v-if="stat.count / totalAnalysisCount > 0.1">
                        {{ ((stat.count / totalAnalysisCount) * 100).toFixed(0) }}%
                      </span>
                    </div>
                  </div>
                  <div class="distribution-value">
                    <span class="phase-count">{{ stat.count }}次</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="phase-details">
              <h4>📋 阶段详情</h4>
              <div class="phase-grid">
                <div v-for="(stat, phase) in sortedPhaseStats" :key="phase" class="phase-detail-card">
                  <div class="phase-header" :style="{ background: getPhaseColor(phase) }">
                    <span class="phase-icon">{{ getPhaseIcon(phase) }}</span>
                    <span class="phase-title">{{ phase }}</span>
                  </div>
                  <div class="phase-body">
                    <div class="detail-row">
                      <span>出现次数</span>
                      <span class="detail-value">{{ stat.count }}次</span>
                    </div>
                    <div class="detail-row">
                      <span>平均情绪</span>
                      <span class="detail-value">{{ stat.avgScore.toFixed(1) }}分</span>
                    </div>
                    <div class="detail-row">
                      <span>情绪范围</span>
                      <span class="detail-value">{{ getPhaseMinScore(phase) }} - {{ getPhaseMaxScore(phase) }}</span>
                    </div>
                    <div class="detail-features">
                      <span v-for="feature in getPhaseFeatures(phase)" :key="feature" class="feature-tag">
                        {{ feature }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 因子影响视图 -->
          <div v-if="activeTab === 'factors'" class="factors-view">
            <div class="factors-impact">
              <div class="section-header">
                <h4>📊 情绪因子权重</h4>
                <span class="section-desc">当前配置</span>
              </div>
              <div class="factors-list">
                <div v-for="factor in emotionFactors" :key="factor.id" class="factor-impact-item">
                  <div class="factor-header">
                    <div class="factor-info">
                      <span class="factor-name">{{ factor.name }}</span>
                      <span class="factor-desc">{{ getFactorDesc(factor.id) }}</span>
                    </div>
                    <span class="factor-weight">{{ (factor.currentWeight * 100).toFixed(0) }}%</span>
                  </div>
                  <div class="factor-bar-container">
                    <div class="factor-bar" :style="{
                      width: factor.currentWeight * 100 + '%',
                      background: getFactorColor(factor.id),
                    }"></div>
                  </div>
                  <div class="factor-stats">
                    <div class="factor-stat">
                      <span class="stat-label">累计调整</span>
                      <span class="stat-value" :class="{
                        positive: factor.totalDelta > 0,
                        negative: factor.totalDelta < 0,
                      }">
                        {{ factor.totalDelta > 0 ? '+' : ''
                        }}{{ (factor.totalDelta * 100).toFixed(1) }}%
                      </span>
                    </div>
                    <div class="factor-stat">
                      <span class="stat-label">调整次数</span>
                      <span class="stat-value">{{ factor.adjustCount }}次</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="phase-impact">
              <h4>🔄 阶段影响分析</h4>
              <div class="phase-impact-grid">
                <div v-for="(adjustments, phase) in phaseAdjustments" :key="phase" class="phase-impact-card">
                  <div class="phase-impact-header" :style="{
                    background: getPhaseColor(phase) + '20',
                    borderLeft: `3px solid ${getPhaseColor(phase)}`,
                  }">
                    <span class="phase-icon">{{ getPhaseIcon(phase) }}</span>
                    <span class="phase-name">{{ phase }}</span>
                  </div>
                  <div class="phase-impact-body">
                    <div v-for="(delta, factorId) in adjustments" :key="factorId" class="impact-row">
                      <span class="factor-name">{{ getFactorShortName(factorId) }}</span>
                      <span class="impact-value" :class="{ up: delta > 0, down: delta < 0 }">
                        {{ delta > 0 ? '+' : '' }}{{ (delta * 100).toFixed(1) }}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 历史趋势视图 -->
          <div v-if="activeTab === 'history'" class="history-view">
            <div class="trend-chart">
              <div class="section-header">
                <h4>📈 情绪分数趋势</h4>
                <div class="trend-stats-mini">
                  <span class="trend-high">▲ {{ maxHistoryScore.toFixed(1) }}</span>
                  <span class="trend-low">▼ {{ minHistoryScore.toFixed(1) }}</span>
                  <span class="trend-avg">● {{ avgHistoryScore.toFixed(1) }}</span>
                </div>
              </div>
              <div class="chart-container" ref="chartContainer">
                <div v-for="(item, index) in emotionHistory"
                  :key="`${item.timestamp}-${item.phase}-${index}-${Math.random()}`" class="chart-bar-wrapper"
                  :style="{ height: (item.score / 100) * 140 + 'px' }">
                  <div class="chart-bar" :style="{
                    background: getPhaseColor(item.phase),
                    height: '100%',
                  }" :title="`${item.phase}: ${item.score.toFixed(1)}分\n${formatTime(item.timestamp)}`">
                    <span class="bar-score" v-if="emotionHistory.length < 30">{{
                      item.score.toFixed(0)
                      }}</span>
                  </div>
                </div>
              </div>
              <div class="chart-footer">
                <span class="time-label">{{ formatTime(emotionHistory[0]?.timestamp) }}</span>
                <span class="time-label">{{
                  formatTime(emotionHistory[emotionHistory.length - 1]?.timestamp)
                  }}</span>
              </div>
            </div>

            <div class="history-stats">
              <div class="stat-row">
                <span>当前趋势</span>
                <span class="trend-indicator" :class="{ up: trend > 0, down: trend < 0, stable: trend === 0 }">
                  <span v-if="trend > 0">↗ 上升中</span>
                  <span v-else-if="trend < 0">↘ 下降中</span>
                  <span v-else>→ 平稳</span>
                  <span class="trend-value">({{ trend > 0 ? '+' : '' }}{{ trend.toFixed(2) }})</span>
                </span>
              </div>
              <div class="stat-row">
                <span>波动幅度</span>
                <span class="stat-value">{{ (maxHistoryScore - minHistoryScore).toFixed(1) }}分</span>
              </div>
              <div class="stat-row">
                <span>数据样本</span>
                <span class="stat-value">{{ emotionHistory.length }}个</span>
              </div>
            </div>
          </div>

          <!-- 调整记录视图 -->
          <div v-if="activeTab === 'adjustments'" class="adjustments-view">
            <div class="adjustments-timeline">
              <div class="section-header">
                <h4>⏱️ 最近权重调整</h4>
                <span class="section-desc">共 {{ totalAdjustments }} 次</span>
              </div>
              <div class="timeline-list">
                <div v-for="adj in recentAdjustments" :key="adj.timestamp" class="timeline-item">
                  <div class="timeline-marker" :class="{ up: adj.delta > 0, down: adj.delta < 0 }">
                    <span class="marker-icon">{{ adj.delta > 0 ? '↑' : '↓' }}</span>
                  </div>
                  <div class="timeline-content">
                    <div class="timeline-header">
                      <span class="timeline-time">{{ formatTimeShort(adj.timestamp) }}</span>
                      <span class="timeline-reason">{{ adj.reason }}</span>
                    </div>
                    <div class="timeline-body">
                      <span class="factor-name">{{ getFactorName(adj.factorId) }}</span>
                      <span class="weight-change" :class="{ up: adj.delta > 0, down: adj.delta < 0 }">
                        {{ (adj.oldWeight * 100).toFixed(1) }}% →
                        {{ (adj.newWeight * 100).toFixed(1) }}%
                        <span class="change-badge">
                          {{ adj.delta > 0 ? '+' : '' }}{{ (adj.delta * 100).toFixed(1) }}%
                        </span>
                      </span>
                    </div>
                  </div>
                </div>
                <div v-if="recentAdjustments.length === 0" class="empty-state">
                  <span class="empty-icon">📭</span>
                  <span class="empty-text">暂无调整记录</span>
                </div>
              </div>
            </div>

            <div class="adjustments-summary">
              <h4>📊 调整统计</h4>
              <div class="summary-grid">
                <div class="summary-item">
                  <span class="summary-label">上调次数</span>
                  <span class="summary-value up">{{ upAdjustments }}</span>
                </div>
                <div class="summary-item">
                  <span class="summary-label">下调次数</span>
                  <span class="summary-value down">{{ downAdjustments }}</span>
                </div>
                <div class="summary-item">
                  <span class="summary-label">平均幅度</span>
                  <span class="summary-value">{{ avgAdjustmentDelta.toFixed(1) }}%</span>
                </div>
                <div class="summary-item">
                  <span class="summary-label">最大调整</span>
                  <span class="summary-value">{{ maxAdjustmentDelta.toFixed(1) }}%</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 性能指标视图 -->
          <div v-if="activeTab === 'performance'" class="performance-view">
            <!-- 系统健康状态 -->
            <div class="health-status" :class="healthStatus">
              <div class="health-icon">
                {{ healthStatus === 'healthy' ? '✅' : healthStatus === 'warning' ? '⚠️' : '🔴' }}
              </div>
              <div class="health-info">
                <div class="health-title">系统健康状态</div>
                <div class="health-desc">
                  {{
                    healthStatus === 'healthy'
                      ? '良好'
                      : healthStatus === 'warning'
                        ? '注意'
                        : '警告'
                  }}
                </div>
              </div>
              <div class="health-issues" v-if="healthIssues.length">
                <div v-for="issue in healthIssues.slice(0, 2)" :key="issue" class="health-issue">
                  {{ issue }}
                </div>
              </div>
            </div>

            <!-- API 性能统计 -->
            <div class="api-performance">
              <div class="section-header">
                <h4>🌐 API 性能</h4>
                <span class="section-desc">P95响应时间</span>
              </div>
              <div class="api-list" v-if="apiStats.length">
                <div v-for="api in apiStats.slice(0, 5)" :key="api.name" class="api-item">
                  <div class="api-header">
                    <span class="api-name">{{ getApiShortName(api.name) }}</span>
                    <span class="api-count">{{ api.count }}次</span>
                  </div>
                  <div class="api-bars">
                    <div class="api-bar-container">
                      <div class="api-bar avg-bar" :style="{ width: Math.min((api.avgTime / 1000) * 100, 100) + '%' }"
                        :title="`平均: ${api.avgTime.toFixed(0)}ms`"></div>
                    </div>
                    <div class="api-bar-container">
                      <div class="api-bar p95-bar" :style="{ width: Math.min((api.p95Time / 1000) * 100, 100) + '%' }"
                        :title="`P95: ${api.p95Time.toFixed(0)}ms`"></div>
                    </div>
                  </div>
                  <div class="api-stats">
                    <span class="api-stat" :class="{ warn: api.p95Time > 500 }">
                      P95: {{ api.p95Time.toFixed(0) }}ms
                    </span>
                    <span class="api-stat" :class="{ success: api.successRate > 95 }">
                      成功率: {{ api.successRate.toFixed(1) }}%
                    </span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-data">
                <span class="empty-icon">🌐</span>
                <span class="empty-text">暂无API性能数据</span>
              </div>
            </div>

            <!-- 缓存统计 -->
            <div class="cache-stats">
              <div class="section-header">
                <h4>⚡ 缓存统计</h4>
                <span class="section-desc">{{ cacheStats.size }}项</span>
              </div>
              <div class="cache-grid" v-if="Object.keys(cacheStats.byType || {}).length">
                <div v-for="(type, name) in cacheStats.byType" :key="name" class="cache-type-item">
                  <div class="cache-type-header">
                    <span class="cache-type-name">{{ name }}</span>
                    <span class="cache-type-rate" :class="getHitRateClass(type.hitRate)">
                      {{ type.hitRate.toFixed(1) }}%
                    </span>
                  </div>
                  <div class="cache-type-bar">
                    <div class="cache-type-fill" :style="{
                      width: type.hitRate + '%',
                      background: getHitRateColor(type.hitRate),
                    }"></div>
                  </div>
                  <div class="cache-type-stats">
                    <span>命中: {{ type.hits }}</span>
                    <span>未命中: {{ type.misses }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-data">
                <span class="empty-icon">💾</span>
                <span class="empty-text">暂无缓存数据</span>
              </div>
            </div>

            <!-- 组件健康状态 -->
            <div class="component-health" v-if="componentStatus.length">
              <div class="section-header">
                <h4>🧩 组件状态</h4>
                <span class="section-desc">{{ healthyComponents }}/{{ componentStatus.length }} 健康</span>
              </div>
              <div class="component-list">
                <div v-for="comp in componentStatus.slice(0, 5)" :key="comp.name" class="component-item"
                  :class="comp.status">
                  <span class="component-name">{{ comp.name }}</span>
                  <span class="component-status" :class="comp.status">
                    {{ comp.status === 'healthy' ? '✅' : comp.status === 'warning' ? '⚠️' : '❌' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 慢操作列表 -->
            <div class="slow-operations" v-if="slowOperations.length">
              <div class="section-header">
                <h4>🐢 慢操作</h4>
                <span class="section-desc">{{ slowOperations.length }}个</span>
              </div>
              <div class="slow-list">
                <div v-for="op in slowOperations" :key="op.name + op.time" class="slow-item">
                  <span class="slow-name">{{ op.name }}</span>
                  <span class="slow-duration" :class="{ 'very-slow': op.duration > 1000 }">
                    {{ op.duration }}
                  </span>
                  <span class="slow-time">{{ op.time }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 数据链条视图 -->
          <div v-if="activeTab === 'datachain'" class="datachain-view">
            <!-- 数据链条摘要 -->
            <div class="chain-summary" :class="dataChainHealth">
              <div class="summary-header">
                <span class="summary-icon">
                  {{
                    dataChainHealth === 'healthy'
                      ? '✅'
                      : dataChainHealth === 'degraded'
                        ? '⚠️'
                        : '🔴'
                  }}
                </span>
                <span class="summary-text">{{ dataChainSummary }}</span>
              </div>
              <div class="summary-stats">
                <div class="stat">
                  <span class="label">总节点</span>
                  <span class="value">{{ chainStats.totalNodes }}</span>
                </div>
                <div class="stat">
                  <span class="label">总边</span>
                  <span class="value">{{ chainStats.totalEdges }}</span>
                </div>
                <div class="stat">
                  <span class="label">总数据流入</span>
                  <span class="value">{{ chainStats.totalDataIn }}次</span>
                </div>
                <div class="stat">
                  <span class="label">总数据流出</span>
                  <span class="value">{{ chainStats.totalDataOut }}次</span>
                </div>
              </div>
            </div>

            <!-- 数据源层 -->
            <div class="chain-layer">
              <div class="layer-header">
                📡 数据源层 ({{ Object.keys(dataChain.sources).length }})
              </div>
              <div class="layer-grid" v-if="Object.keys(dataChain.sources).length">
                <div v-for="(source, id) in dataChain.sources" :key="id" class="layer-card source">
                  <div class="card-header">
                    <span class="card-title">{{ id }}</span>
                    <span class="card-badge"
                      :class="getHitRateClass((source.successCount / source.fetchCount) * 100 || 0)">
                      {{ ((source.successCount / source.fetchCount) * 100 || 0).toFixed(0) }}%
                    </span>
                  </div>
                  <div class="card-metrics">
                    <div class="metric">
                      <span class="metric-label">请求</span>
                      <span class="metric-value">{{ source.fetchCount }}</span>
                    </div>
                    <div class="metric">
                      <span class="metric-label">成功率</span>
                      <span class="metric-value" :class="getHitRateClass((source.successCount / source.fetchCount) * 100 || 0)
                        ">
                        {{ ((source.successCount / source.fetchCount) * 100 || 0).toFixed(1) }}%
                      </span>
                    </div>
                    <div class="metric">
                      <span class="metric-label">P95</span>
                      <span class="metric-value" :class="source.p95ResponseTime > 500 ? 'warn' : 'good'">
                        {{ source.p95ResponseTime.toFixed(0) }}ms
                      </span>
                    </div>
                    <div class="metric">
                      <span class="metric-label">数据量</span>
                      <span class="metric-value">{{ formatBytes(source.totalBytes) }}</span>
                    </div>
                  </div>
                  <div v-if="source.failReason" class="card-error">⚠️ {{ source.failReason }}</div>
                </div>
              </div>
              <div v-else class="empty-data">
                <span class="empty-icon">📡</span>
                <span class="empty-text">暂无数据源</span>
              </div>
            </div>

            <!-- 缓存层 - 直接从 cacheStats 显示 -->
            <div class="chain-layer">
              <div class="layer-header">
                💾 缓存层 ({{ Object.keys(cacheStats.byType || {}).length }})
              </div>
              <div class="layer-grid" v-if="Object.keys(cacheStats.byType || {}).length">
                <div v-for="(stats, name) in cacheStats.byType" :key="name" class="layer-card cache">
                  <div class="card-header">
                    <span class="card-title">{{ name }}</span>
                    <span class="card-badge" :class="getHitRateClass(stats.hitRate)">
                      {{ stats.hitRate.toFixed(1) }}%
                    </span>
                  </div>
                  <div class="card-metrics">
                    <div class="metric">
                      <span class="metric-label">命中/未命中</span>
                      <span class="metric-value">{{ stats.hits }}/{{ stats.misses }}</span>
                    </div>
                    <div class="metric">
                      <span class="metric-label">命中率</span>
                      <span class="metric-value" :class="getHitRateClass(stats.hitRate)">
                        {{ stats.hitRate.toFixed(1) }}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-data">
                <span class="empty-icon">💾</span>
                <span class="empty-text">暂无缓存数据</span>
              </div>
            </div>

            <!-- 瓶颈和警告 -->
            <div v-if="dataChain.health.bottlenecks.length" class="chain-bottlenecks">
              <div class="bottleneck-header">🔴 性能瓶颈</div>
              <ul class="bottleneck-list">
                <li v-for="b in dataChain.health.bottlenecks" :key="b">{{ b }}</li>
              </ul>
            </div>

            <div v-if="dataChain.health.warnings.length" class="chain-warnings">
              <div class="warning-header">⚠️ 警告</div>
              <ul class="warning-list">
                <li v-for="w in dataChain.health.warnings" :key="w">{{ w }}</li>
              </ul>
            </div>
          </div>
        </div>
      </template>

      <!-- 底部 -->
      <div class="panel-footer">
        <div class="footer-left">
          <span class="update-dot" :style="{ background: phaseColor }"></span>
          <span class="update-text">数据更新: {{ formatTime(lastUpdate) }}</span>
        </div>
        <div class="footer-right">
          <span class="source-badge">龙息分析器 v2.3.0</span>
          <span class="health-badge" :class="healthStatus">
            {{ healthStatus === 'healthy' ? '健康' : healthStatus === 'warning' ? '注意' : '警告' }}
          </span>
        </div>
      </div>

      <!-- 健康报告弹窗 -->
      <div v-if="showHealthModal" class="health-modal" @click.self="showHealthModal = false">
        <div class="health-modal-content">
          <div class="health-modal-header">
            <h4>🏥 系统健康报告</h4>
            <button class="close-btn" @click="showHealthModal = false">✕</button>
          </div>
          <div class="health-modal-body">
            <div class="health-summary" :class="healthStatus">
              <div class="health-score">
                {{
                  healthStatus === 'healthy' ? '100' : healthStatus === 'warning' ? '70' : '40'
                }}分
              </div>
              <div class="health-status-text">
                {{
                  healthStatus === 'healthy'
                    ? '系统运行良好'
                    : healthStatus === 'warning'
                      ? '部分指标需关注'
                      : '需要立即处理'
                }}
              </div>
            </div>

            <div class="health-section" v-if="healthIssues.length">
              <h5>⚠️ 发现的问题</h5>
              <ul class="issue-list">
                <li v-for="issue in healthIssues" :key="issue">{{ issue }}</li>
              </ul>
            </div>

            <div class="health-section" v-if="healthSuggestions.length">
              <h5>💡 优化建议</h5>
              <ul class="suggestion-list">
                <li v-for="suggestion in healthSuggestions" :key="suggestion">{{ suggestion }}</li>
              </ul>
            </div>

            <div class="health-section">
              <h5>📊 关键指标</h5>
              <div class="key-metrics">
                <div class="metric-item">
                  <span class="metric-label">缓存命中率</span>
                  <span class="metric-value" :class="getHitRateClass(cacheStats.hitRate * 100)">
                    {{ (cacheStats.hitRate * 100).toFixed(1) }}%
                  </span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">API P95</span>
                  <span class="metric-value">{{ apiP95.toFixed(0) }}ms</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">内存使用</span>
                  <span class="metric-value">{{ formatBytes(memoryUsage) }}</span>
                </div>
                <div class="metric-item">
                  <span class="metric-label">情绪阶段</span>
                  <span class="metric-value" :style="{ color: phaseColor }">
                    {{ currentPhase?.name || '未知' }}
                  </span>
                </div>
              </div>
            </div>

            <div class="health-footer">
              <span>报告时间: {{ formatTime(Date.now()) }}</span>
              <span>运行时长: {{ formatUptime(systemUptime) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { algorithmManager } from '@/services/Algorithm'
import { EventManager } from '@/utils/eventManager'
import { AppEvents, MARKET_PHASES } from '@/types'
import { usePanel } from '@/composables/usePanel'
import { performanceMonitor } from '@/services/performanceMonitor'

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const close = () => {
  emit('update:visible', false)
  emit('close')
}

// ========== 使用 usePanel ==========
const { panelRef, panelStyle } = usePanel({
  name: 'EmotionMonitorPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="情绪监控"]', '[title*="情绪"]'],
  onClose: close,
})

// ========== 状态 ==========
const loading = ref(false)
const activeTab = ref<
  'phases' | 'factors' | 'history' | 'adjustments' | 'performance' | 'datachain'
>('phases')
const lastUpdate = ref(Date.now())
const chartContainer = ref<HTMLElement | null>(null)
const showHealthModal = ref(false)

// 情绪数据
const currentEmotion = ref<any>(null)
const marketData = ref<any>(null)
const emotionHistory = ref<any[]>([])
const emotionStats = ref<Record<string, { count: number; avgScore: number }>>({})
const adjustmentHistory = ref<any[]>([])

// 性能数据
const apiStats = ref<any[]>([])
const cacheStats = ref<any>({ hitRate: 0, byType: {} })
const healthStatus = ref<'healthy' | 'warning' | 'critical'>('healthy')
const healthIssues = ref<string[]>([])
const healthSuggestions = ref<string[]>([])
const componentStatus = ref<any[]>([])
const slowOperations = ref<any[]>([])
const systemUptime = ref(0)
const memoryUsage = ref(0)
const apiP95 = ref(0)

// 标签页配置
const tabs = [
  { value: 'phases', icon: '📊', label: '阶段分布' },
  { value: 'factors', icon: '⚖️', label: '因子影响' },
  { value: 'history', icon: '📈', label: '历史趋势' },
  { value: 'adjustments', icon: '🔧', label: '调整记录' },
  { value: 'performance', icon: '⏱️', label: '性能监控' },
  { value: 'datachain', icon: '🔗', label: '数据链条' },
]
// ========== 从 MARKET_PHASES 常量获取阶段信息 ==========
const currentPhase = computed(() => {
  if (!currentEmotion.value?.phase) return null
  return Object.values(MARKET_PHASES).find((p) => p.name === currentEmotion.value.phase)
})

const phaseColor = computed(() => {
  return currentPhase.value?.color || '#95a5a6'
})

// 添加数据链条相关的 ref
const dataChain = ref<any>({
  sources: {},
  processors: {},
  calculators: {},
  caches: {},
  presentations: {},
  health: { overall: 'healthy', bottlenecks: [], warnings: [] },
})
const dataChainHealth = ref('healthy')
const dataChainSummary = ref('等待数据...')
const chainStats = ref({
  totalNodes: 0,
  totalEdges: 0,
  totalDataIn: 0,
  totalDataOut: 0,
})

// 加载数据链条
const loadDataChain = () => {
  try {
    const report = performanceMonitor.getDataChainReport?.()
    if (report) {
      dataChain.value = report
      dataChainHealth.value = report.health.overall
      dataChainSummary.value = report.summary

      const stats = performanceMonitor.getDataChainStats?.()
      if (stats) {
        chainStats.value = stats
      }
    }
  } catch (e) {
    console.warn('[EmotionMonitorPanel] 加载数据链条失败', e)
  }
}

const phaseGradient = computed(() => {
  return currentPhase.value?.gradient || 'linear-gradient(135deg, #2c3e50, #34495e)'
})

const phaseIcon = computed(() => {
  return currentPhase.value?.icon || '🌬️'
})

// ========== 计算属性 ==========
const phaseCount = computed(() => Object.keys(emotionStats.value).length)

const totalAnalysisCount = computed(() =>
  Object.values(emotionStats.value).reduce((sum, stat) => sum + stat.count, 0),
)

const totalAdjustments = computed(() => adjustmentHistory.value.length)

const avgEmotionScore = computed(() => {
  const total = emotionHistory.value.reduce((sum, item) => sum + item.score, 0)
  return emotionHistory.value.length ? total / emotionHistory.value.length : 0
})

const maxHistoryScore = computed(() =>
  Math.max(...emotionHistory.value.map((item) => item.score), 0),
)

const minHistoryScore = computed(() =>
  Math.min(...emotionHistory.value.map((item) => item.score), 100),
)

const avgHistoryScore = computed(() => {
  const scores = emotionHistory.value.map((item) => item.score)
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0
})

const trend = computed(() => {
  if (emotionHistory.value.length < 2) return 0
  const recent = emotionHistory.value.slice(-5)
  const first = recent[0]?.score || 0
  const last = recent[recent.length - 1]?.score || 0
  return last - first
})

const sortedPhaseStats = computed(() => {
  return Object.entries(emotionStats.value)
    .sort(([, a], [, b]) => b.count - a.count)
    .reduce(
      (acc, [key, value]) => {
        acc[key] = value
        return acc
      },
      {} as Record<string, { count: number; avgScore: number }>,
    )
})

const upAdjustments = computed(() => adjustmentHistory.value.filter((adj) => adj.delta > 0).length)

const downAdjustments = computed(
  () => adjustmentHistory.value.filter((adj) => adj.delta < 0).length,
)

const avgAdjustmentDelta = computed(() => {
  const total = adjustmentHistory.value.reduce((sum, adj) => sum + Math.abs(adj.delta), 0)
  return adjustmentHistory.value.length ? (total / adjustmentHistory.value.length) * 100 : 0
})

const maxAdjustmentDelta = computed(() => {
  if (adjustmentHistory.value.length === 0) return 0
  const max = Math.max(...adjustmentHistory.value.map((adj) => Math.abs(adj.delta)))
  return max * 100
})

// 健康组件数量
const healthyComponents = computed(() => {
  return componentStatus.value.filter((c) => c.status === 'healthy').length
})

// 情绪因子列表
const emotionFactors = computed(() => {
  const weights = algorithmManager.getFactorWeights().filter((w) => w.id.startsWith('breath'))

  const adjustments = adjustmentHistory.value
  const factorStats: Record<string, { totalDelta: number; count: number }> = {}

  adjustments.forEach((adj) => {
    if (!factorStats[adj.factorId]) {
      factorStats[adj.factorId] = { totalDelta: 0, count: 0 }
    }
    factorStats[adj.factorId].totalDelta += adj.delta
    factorStats[adj.factorId].count++
  })

  return weights.map((w) => ({
    id: w.id,
    name: getFactorName(w.id),
    currentWeight: w.weight,
    totalDelta: factorStats[w.id]?.totalDelta || 0,
    adjustCount: factorStats[w.id]?.count || 0,
  }))
})

// 阶段调整配置
const phaseAdjustments = computed(() => {
  return {
    冰点期: { contrarian: 0.03, compRank: 0.01, breathDtCount: 0.02, themeHeat: -0.02 },
    启动期: { themeHeat: 0.01, compRank: 0.01, breathPassRate: 0.02 },
    发酵期: { themeHeat: 0.02, themeMomentum: 0.02, zlje: 0.01, continuousDays: -0.01 },
    高潮期: {
      continuousDays: 0.02,
      breathPhase: 0.01,
      breathZtCount: 0.01,
      zlje: -0.01,
      themeHeat: -0.01,
    },
    退潮期: { breathDtCount: 0.02, breathZhabanRate: 0.02, zlje: -0.02 },
    震荡期: { themeHeat: -0.01, compRank: -0.01, breathUpDownRatio: 0.01 },
    活跃期: { themeHeat: 0.02, themeMomentum: 0.02, breathZtCount: 0.01 },
    平稳期: { themeHeat: 0.01, breathUpDownRatio: 0.01, breathPhase: -0.01 },
    低迷期: { breathDtCount: 0.01, breathZhabanRate: 0.01, themeHeat: -0.02 },
  }
})

const recentAdjustments = computed(() => adjustmentHistory.value.slice(0, 20))

// ========== 工具函数 ==========
const getImpactColor = (impact: number): string => {
  if (impact > 20) return '#ff4757'
  if (impact > 10) return '#ffa502'
  if (impact > 0) return '#2ed573'
  return '#7f8c8d'
}

const getPhaseIcon = (phase: string): string => {
  const phaseInfo = Object.values(MARKET_PHASES).find((p) => p.name === phase)
  return phaseInfo?.icon || '🌬️'
}

const getPhaseColor = (phase: string): string => {
  const phaseInfo = Object.values(MARKET_PHASES).find((p) => p.name === phase)
  return phaseInfo?.color || '#7f8c8d'
}

const getPhaseFeatures = (phase: string): string[] => {
  const phaseInfo = Object.values(MARKET_PHASES).find((p) => p.name === phase)
  return phaseInfo?.features || []
}

const getFactorName = (id: string): string => {
  const names: Record<string, string> = {
    breathPhase: '龙息阶段',
    breathZtCount: '涨停数',
    breathDtCount: '跌停数',
    breathZhabanRate: '炸板率',
    breathFengbanRate: '封板率',
    breathPassRate: '晋级率',
    breathMaxDays: '最高连板',
    breathUpDownRatio: '涨跌比',
    breathEmotionValue: '情绪值',
    breathMarketScore: '市场总分',
    contrarian: '逆势因子',
    compRank: '综合排名',
    themeHeat: '题材热度',
    themeMomentum: '题材动量',
    zlje: '主力资金',
    continuousDays: '连板天数',
  }
  return names[id] || id
}

const getFactorDesc = (id: string): string => {
  const descs: Record<string, string> = {
    breathPhase: '当前市场阶段',
    breathZtCount: '涨停家数',
    breathDtCount: '跌停家数',
    breathZhabanRate: '炸板比例',
    breathFengbanRate: '封板比例',
    breathPassRate: '晋级成功率',
    breathMaxDays: '最高连板',
    breathUpDownRatio: '涨跌家数比',
    breathEmotionValue: '通达信情绪',
    breathMarketScore: '综合评分',
  }
  return descs[id] || ''
}

const getFactorShortName = (id: string): string => {
  const names: Record<string, string> = {
    breathPhase: '阶段',
    breathZtCount: '涨停',
    breathDtCount: '跌停',
    breathZhabanRate: '炸板',
    breathFengbanRate: '封板',
    breathPassRate: '晋级',
    breathMaxDays: '连板',
    breathUpDownRatio: '涨跌比',
    breathEmotionValue: '情绪',
    breathMarketScore: '总分',
    contrarian: '逆势',
    compRank: '排名',
    themeHeat: '热度',
    themeMomentum: '动量',
    zlje: '主力',
    continuousDays: '连板',
  }
  return names[id] || id
}

const getFactorColor = (id: string): string => {
  const colors: Record<string, string> = {
    breathPhase: '#9b59b6',
    breathZtCount: '#2ecc71',
    breathDtCount: '#e74c3c',
    breathZhabanRate: '#f39c12',
    breathFengbanRate: '#3498db',
    breathPassRate: '#1abc9c',
    breathMaxDays: '#e67e22',
    breathUpDownRatio: '#95a5a6',
    breathEmotionValue: '#d35400',
    breathMarketScore: '#16a085',
    contrarian: '#ff7f50',
    compRank: '#ffa502',
    themeHeat: '#ff4757',
    themeMomentum: '#ff6b81',
    zlje: '#00b894',
    continuousDays: '#0984e3',
  }
  return colors[id] || '#ffa502'
}

const getApiShortName = (name: string): string => {
  if (name.includes('/api/quotes')) return '行情'
  if (name.includes('/api/theme')) return '题材'
  if (name.includes('/api/kpl')) return 'KPL'
  if (name.includes('/api/tdx')) return '通达信'
  return name.split('/').pop() || name
}

const getHitRateClass = (rate: number): string => {
  if (rate >= 80) return 'good'
  if (rate >= 50) return 'normal'
  return 'warn'
}

const getHitRateColor = (rate: number): string => {
  if (rate >= 80) return '#2ecc71'
  if (rate >= 50) return '#f1c40f'
  return '#e67e22'
}

const getPhaseMaxScore = (phase: string): string => {
  const phaseData = emotionHistory.value.filter((item) => item.phase === phase)
  return phaseData.length ? Math.max(...phaseData.map((item) => item.score)).toFixed(1) : '0'
}

const getPhaseMinScore = (phase: string): string => {
  const phaseData = emotionHistory.value.filter((item) => item.phase === phase)
  return phaseData.length ? Math.min(...phaseData.map((item) => item.score)).toFixed(1) : '100'
}

const formatTime = (timestamp?: number): string => {
  if (!timestamp) return '--:--'
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

const formatTimeShort = (timestamp?: number): string => {
  if (!timestamp) return '--'
  const diff = Math.floor((Date.now() - timestamp) / 60000)
  if (diff < 1) return '刚刚'
  if (diff < 60) return diff + '分钟前'
  return Math.floor(diff / 60) + '小时前'
}

const formatUptime = (ms: number): string => {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (days > 0) return `${days}天 ${hours % 24}小时`
  if (hours > 0) return `${hours}小时 ${minutes % 60}分钟`
  if (minutes > 0) return `${minutes}分钟 ${seconds % 60}秒`
  return `${seconds}秒`
}

const formatBytes = (bytes: number): string => {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / (1024 * 1024)).toFixed(1) + 'MB'
}

// ========== 加载性能数据 ==========
const loadPerformanceData = () => {
  try {

    // 获取 API 统计
    apiStats.value = performanceMonitor.getApiStats(10)

    // 获取缓存统计
    cacheStats.value = performanceMonitor.getCacheStats()

    // 获取系统健康状态
    const health = performanceMonitor.checkSystemHealth()
    healthStatus.value = health.status
    healthIssues.value = health.issues
    healthSuggestions.value = health.suggestions

    // 获取组件状态
    componentStatus.value = performanceMonitor.getAllComponentStatus()


    // 获取慢操作
    slowOperations.value = performanceMonitor.getSlowestOperations(5).map((op) => ({
      name: op.name,
      duration: op.duration + 'ms',
      time: new Date(op.timestamp).toLocaleTimeString(),
    }))

    // 获取系统信息
    systemUptime.value = performanceMonitor.getSystemUptime()
    const memory = performanceMonitor.getMemoryInfo()
    if (memory) {
      memoryUsage.value = memory.usedJSHeapSize
    }

    // 计算 API P95 平均值
    const p95Values = apiStats.value.map((a) => a.p95Time).filter((v) => v > 0)
    if (p95Values.length) {
      apiP95.value = p95Values.reduce((a, b) => a + b, 0) / p95Values.length
    }

    loadDataChain()

    debugLog('[EmotionMonitorPanel] 性能数据加载完成')
  } catch (e) {
    console.warn('[EmotionMonitorPanel] 加载性能数据失败', e)
  }
}

// ========== 数据加载 ==========
const loadData = () => {
  loading.value = true

  try {
    // 获取当前情绪和市场数据
    currentEmotion.value = dragonBreathAnalyzer.getMarketSentiment()
    marketData.value = dragonBreathAnalyzer.getMarketData()

    // 从 performanceMonitor 获取情绪历史
    const perfMonitor = algorithmManager.getPerfMonitor?.()
    if (perfMonitor && typeof perfMonitor.getEmotionHistory === 'function') {
      emotionHistory.value = perfMonitor.getEmotionHistory(50)
    } else {
      emotionHistory.value = dragonBreathAnalyzer.getHistory?.() || []
    }

    // 情绪统计
    if (emotionHistory.value.length > 0) {
      const stats: Record<string, { count: number; avgScore: number }> = {}
      emotionHistory.value.forEach((item) => {
        const phase = item.phase || '未知'
        const score = item.score || 0

        if (!stats[phase]) {
          stats[phase] = { count: 0, avgScore: 0 }
        }
        stats[phase].count++
        stats[phase].avgScore =
          (stats[phase].avgScore * (stats[phase].count - 1) + score) / stats[phase].count
      })
      emotionStats.value = stats
    }

    // 获取调整历史
    adjustmentHistory.value = algorithmManager.getWeightAdjustmentHistory?.() || []

    // 加载性能数据
    loadPerformanceData()

    lastUpdate.value = Date.now()
  } catch (error) {
    console.error('[EmotionMonitorPanel] 加载失败:', error)
  } finally {
    loading.value = false
  }
}

const refresh = () => {
  loadData()
  EventManager.emit(AppEvents.UI.TOAST, {
    message: '🔄 数据已刷新',
    duration: 1000,
    type: 'info',
  })
}

const exportData = () => {
  const data = {
    exportTime: new Date().toISOString(),
    currentEmotion: currentEmotion.value,
    emotionStats: emotionStats.value,
    emotionHistory: emotionHistory.value,
    adjustmentHistory: adjustmentHistory.value,
    performance: {
      apiStats: apiStats.value,
      cacheStats: cacheStats.value,
      healthStatus: healthStatus.value,
      healthIssues: healthIssues.value,
    },
  }

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `情绪监控_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)

  EventManager.emit(AppEvents.UI.TOAST, {
    message: '📥 数据已导出',
    duration: 1500,
    type: 'success',
  })
}

const showHealthReport = () => {
  loadPerformanceData() // 刷新数据
  showHealthModal.value = true
}

const loadEmotionHistory = () => {
  emotionHistory.value = performanceMonitor.getEmotionHistory(50)
}

// ========== 防抖处理 ==========
let loadDataTimeout: ReturnType<typeof setTimeout> | null = null
const DEBOUNCE_DELAY = 300

const debouncedLoadData = () => {
  if (loadDataTimeout) {
    clearTimeout(loadDataTimeout)
  }
  loadDataTimeout = setTimeout(() => {
    loadData()
    loadDataTimeout = null
  }, DEBOUNCE_DELAY)
}

// ========== 生命周期 ==========
onMounted(() => {
  if (props.visible) {
    loadData()
    // 强制加载性能数据
    setTimeout(() => {
      loadPerformanceData()
    }, 1000)

    // 记录面板渲染
    performanceMonitor.recordPresentation(
      'EmotionMonitorPanel',
      performance.now() - startTime,
      Date.now() - (currentEmotion.value?.timestamp || Date.now()),
    )
  }

  loadEmotionHistory()

  // 监听事件
  EventManager.on(AppEvents.BREATH.UPDATED, debouncedLoadData)
  EventManager.on('algorithm:weights-adjusted', debouncedLoadData)
  EventManager.on('threshold-multipliers-updated', debouncedLoadData)
  EventManager.on('performance:updated', loadPerformanceData)
})

onUnmounted(() => {
  if (loadDataTimeout) {
    clearTimeout(loadDataTimeout)
    loadDataTimeout = null
  }
  EventManager.off(AppEvents.BREATH.UPDATED, debouncedLoadData)
  EventManager.off('algorithm:weights-adjusted', debouncedLoadData)
  EventManager.off('threshold-multipliers-updated', debouncedLoadData)
  EventManager.off('performance:updated', loadPerformanceData)
})

// 监听 visible 变化
watch(
  () => props.visible,
  (val) => {
    if (val) {
      debouncedLoadData()
    }
  },
)
</script>

<style scoped>
/* 原有样式保持不变，添加新样式 */

.health-badge {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
}

.health-badge.healthy {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
  border: 1px solid rgba(46, 213, 115, 0.3);
}

.health-badge.warning {
  background: rgba(255, 165, 2, 0.2);
  color: #ffa502;
  border: 1px solid rgba(255, 165, 2, 0.3);
}

.health-badge.critical {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.3);
}

/* 性能视图样式 */
.performance-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.health-status {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 16px;
  border-left: 4px solid;
}

.health-status.healthy {
  border-left-color: #2ed573;
}

.health-status.warning {
  border-left-color: #ffa502;
}

.health-status.critical {
  border-left-color: #ff4757;
}

.health-icon {
  font-size: 24px;
}

.health-info {
  flex: 1;
}

.health-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.health-desc {
  font-size: 12px;
  color: var(--text-secondary);
}

.health-issues {
  font-size: 11px;
  color: #ffa502;
  max-width: 200px;
}

.health-issue {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* API 性能样式 */
.api-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.api-item {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 12px;
}

.api-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.api-name {
  font-weight: 600;
  color: var(--text-primary);
}

.api-count {
  font-size: 10px;
  color: var(--text-tertiary);
}

.api-bars {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}

.api-bar-container {
  flex: 1;
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
}

.api-bar {
  height: 100%;
  border-radius: 3px;
}

.avg-bar {
  background: #3498db;
}

.p95-bar {
  background: #e67e22;
}

.api-stats {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
}

.api-stat.warn {
  color: #e67e22;
}

.api-stat.success {
  color: #2ed573;
}

/* 缓存统计样式 */
.cache-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.cache-type-item {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 12px;
}

.cache-type-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.cache-type-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
  text-transform: capitalize;
}

.cache-type-rate {
  font-size: 12px;
  font-weight: 600;
}

.cache-type-rate.good {
  color: #2ed573;
}

.cache-type-rate.normal {
  color: #f1c40f;
}

.cache-type-rate.warn {
  color: #e67e22;
}

.cache-type-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 8px;
}

.cache-type-fill {
  height: 100%;
  border-radius: 2px;
}

.cache-type-stats {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-tertiary);
}

/* 组件状态样式 */
.component-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.component-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.component-item.healthy {
  border-left: 3px solid #2ed573;
}

.component-item.warning {
  border-left: 3px solid #ffa502;
}

.component-item.error {
  border-left: 3px solid #ff4757;
}

.component-name {
  font-size: 11px;
  color: var(--text-primary);
}

.component-status {
  font-size: 12px;
}

/* 慢操作样式 */
.slow-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.slow-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  font-size: 11px;
}

.slow-name {
  flex: 1;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.slow-duration {
  font-family: monospace;
  color: #e67e22;
}

.slow-duration.very-slow {
  color: #ff4757;
  font-weight: 600;
}

.slow-time {
  color: var(--text-tertiary);
  font-size: 10px;
}

/* 健康报告弹窗 */
.health-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10020;
  backdrop-filter: blur(5px);
}

.health-modal-content {
  width: 400px;
  max-width: 90vw;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  overflow: hidden;
}

.health-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.health-modal-header h4 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
}

.health-modal-body {
  padding: 20px;
  max-height: 60vh;
  overflow-y: auto;
}

.health-summary {
  text-align: center;
  padding: 20px;
  margin-bottom: 20px;
  background: var(--bg-secondary);
  border-radius: 16px;
}

.health-summary.healthy {
  background: linear-gradient(135deg, rgba(46, 213, 115, 0.1), transparent);
}

.health-summary.warning {
  background: linear-gradient(135deg, rgba(255, 165, 2, 0.1), transparent);
}

.health-summary.critical {
  background: linear-gradient(135deg, rgba(255, 71, 87, 0.1), transparent);
}

.health-score {
  font-size: 48px;
  font-weight: bold;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.health-status-text {
  font-size: 16px;
  color: var(--text-secondary);
}

.health-section {
  margin-bottom: 20px;
}

.health-section h5 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: var(--text-title);
}

.issue-list,
.suggestion-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-secondary);
  font-size: 12px;
}

.issue-list li,
.suggestion-list li {
  margin-bottom: 6px;
}

.key-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.metric-item {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 12px;
  text-align: center;
}

.metric-label {
  display: block;
  font-size: 10px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 16px;
  font-weight: bold;
  color: var(--text-primary);
}

.metric-value.good {
  color: #2ed573;
}

.metric-value.normal {
  color: #f1c40f;
}

.metric-value.warn {
  color: #e67e22;
}

.health-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 16px;
  margin-top: 16px;
  border-top: 1px solid var(--border-color);
  font-size: 10px;
  color: var(--text-tertiary);
}

.emotion-panel {
  position: fixed;
  width: 720px;
  max-width: calc(100vw - 40px);
  max-height: 85vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  z-index: 10007;
  font-size: 13px;
  overflow: hidden;
  backdrop-filter: blur(20px);
  animation: slideIn 0.25s cubic-bezier(0.2, 0, 0, 1);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-15px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-icon {
  font-size: 24px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-highlight);
  letter-spacing: 0.5px;
}

.version-badge {
  padding: 2px 8px;
  background: rgba(255, 215, 0, 0.15);
  color: var(--color-highlight);
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
  border: 1px solid rgba(255, 215, 0, 0.3);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  border-radius: 10px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.btn-icon.close:hover {
  border-color: #ff4757;
  color: #ff4757;
}

.rotating {
  animation: rotate 1s infinite linear;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px;
  gap: 20px;
}

.loading-spinner {
  width: 44px;
  height: 44px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s infinite cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 当前情绪卡片 - 优化版 */
.current-emotion-card {
  margin: 16px 20px 20px;
  padding: 20px;
  border-radius: 20px;
  color: white;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3);
  position: relative;
  overflow: hidden;
}

.current-emotion-card::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 0%, transparent 70%);
  pointer-events: none;
}

.emotion-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.emotion-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.emotion-icon-wrapper {
  width: 56px;
  height: 56px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.emotion-icon {
  font-size: 32px;
}

.emotion-info {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.emotion-phase {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: bold;
  letter-spacing: 0.5px;
}

.emotion-score-badge {
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 12px;
  font-weight: normal;
  backdrop-filter: blur(4px);
}

.emotion-tags {
  display: flex;
  gap: 8px;
}

.emotion-risk {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 20px;
  font-weight: 500;
  backdrop-filter: blur(4px);
}

.risk-低 {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
  border: 1px solid rgba(46, 213, 115, 0.3);
}

.risk-中 {
  background: rgba(255, 165, 2, 0.2);
  color: #ffa502;
  border: 1px solid rgba(255, 165, 2, 0.3);
}

.risk-高 {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.3);
}

.emotion-tag {
  font-size: 11px;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 6px;
  backdrop-filter: blur(4px);
}

.tag-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
}

.emotion-stats-mini {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 30px;
  backdrop-filter: blur(4px);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-item .stat-label {
  font-size: 9px;
  opacity: 0.7;
}

.stat-item .stat-value {
  font-size: 14px;
  font-weight: bold;
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: rgba(255, 255, 255, 0.2);
}

.emotion-suggestion {
  padding: 14px 16px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.5;
  margin-bottom: 16px;
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  gap: 8px;
}

.quote-mark {
  font-size: 18px;
  opacity: 0.5;
  font-family: serif;
}

.emotion-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  opacity: 0.8;
}

.update-time {
  display: flex;
  align-items: center;
  gap: 6px;
}

.update-time .dot {
  width: 6px;
  height: 6px;
  background: #2ed573;
  border-radius: 3px;
  animation: pulse 2s infinite;
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }
}

.hot-themes {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 统计卡片 - 优化版 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 0 20px 20px;
}

.stat-card {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--border-color);
  transition: all 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.stat-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-content .stat-label {
  font-size: 10px;
  color: var(--text-secondary);
}

.stat-content .stat-value {
  font-size: 18px;
  font-weight: bold;
  color: var(--text-primary);
}

/* 标签页 - 优化版 */
.panel-tabs {
  display: flex;
  gap: 8px;
  padding: 0 20px 16px;
}

.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 8px;
  border: none;
  background: var(--bg-secondary);
  border-radius: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 10px rgba(255, 215, 0, 0.3);
}

.tab-icon {
  font-size: 16px;
}

.tab-count {
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 12px;
  font-size: 10px;
}

/* 内容区域 */
.panel-content {
  padding: 0 20px 20px;
  max-height: calc(85vh - 280px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-color) transparent;
}

.panel-content::-webkit-scrollbar {
  width: 4px;
}

.panel-content::-webkit-scrollbar-track {
  background: transparent;
}

.panel-content::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 2px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: var(--color-highlight);
}

/* 阶段分布视图 */
.phases-view,
.factors-view,
.history-view,
.adjustments-view {
  padding: 4px 0;
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
  color: var(--text-primary);
  font-weight: 600;
}

.section-desc {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-secondary);
  border-radius: 12px;
}

.distribution-chart {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 24px;
}

.distribution-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.distribution-label {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 90px;
}

.phase-color {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}

.phase-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.distribution-bar-container {
  flex: 1;
  height: 28px;
  background: var(--bg-primary);
  border-radius: 14px;
  overflow: hidden;
  position: relative;
}

.distribution-bar {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 10px;
  transition: width 0.3s;
}

.bar-percent {
  font-size: 10px;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  font-weight: 500;
}

.distribution-value {
  min-width: 60px;
  text-align: right;
}

.phase-count {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.phase-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.phase-detail-card {
  background: var(--bg-secondary);
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  transition: all 0.2s;
}

.phase-detail-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
}

.phase-header {
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: white;
}

.phase-icon {
  font-size: 16px;
}

.phase-title {
  font-size: 13px;
  font-weight: 600;
}

.phase-body {
  padding: 12px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-bottom: 8px;
}

.detail-row span:first-child {
  color: var(--text-secondary);
}

.detail-value {
  font-weight: 600;
  color: var(--text-primary);
}

.detail-features {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.feature-tag {
  padding: 2px 6px;
  background: rgba(255, 215, 0, 0.1);
  border: 1px solid rgba(255, 215, 0, 0.2);
  border-radius: 4px;
  font-size: 9px;
  color: var(--color-highlight);
}

/* 因子影响视图 */
.factors-impact,
.phase-impact {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 24px;
}

.factors-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.factor-impact-item {
  background: var(--bg-primary);
  border-radius: 14px;
  padding: 14px;
  border: 1px solid var(--border-color);
}

.factor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.factor-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.factor-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.factor-desc {
  font-size: 10px;
  color: var(--text-tertiary);
}

.factor-weight {
  font-size: 16px;
  font-weight: bold;
  color: var(--color-highlight);
}

.factor-bar-container {
  height: 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 12px;
}

.factor-bar {
  height: 100%;
  transition: width 0.3s;
}

.factor-stats {
  display: flex;
  justify-content: space-between;
}

.factor-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.factor-stat .stat-label {
  font-size: 10px;
  color: var(--text-tertiary);
}

.factor-stat .stat-value {
  font-size: 12px;
  font-weight: 600;
}

.factor-stat .stat-value.positive {
  color: #ff4757;
}

.factor-stat .stat-value.negative {
  color: #2ed573;
}

.phase-impact-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.phase-impact-card {
  background: var(--bg-primary);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.phase-impact-header {
  padding: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}

.phase-impact-header .phase-icon {
  font-size: 14px;
}

.phase-impact-header .phase-name {
  font-size: 12px;
  color: var(--text-primary);
}

.phase-impact-body {
  padding: 10px;
}

.impact-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-bottom: 6px;
}

.impact-value {
  font-weight: 600;
}

.impact-value.up {
  color: #ff4757;
}

.impact-value.down {
  color: #2ed573;
}

/* 历史趋势视图 */
.trend-chart {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
}

.trend-stats-mini {
  display: flex;
  gap: 12px;
}

.trend-high {
  color: #ff4757;
  font-size: 11px;
}

.trend-low {
  color: #2ed573;
  font-size: 11px;
}

.trend-avg {
  color: var(--color-highlight);
  font-size: 11px;
}

.chart-container {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 160px;
  padding: 10px 0;
  margin: 10px 0;
  border-bottom: 1px solid var(--border-color);
}

.chart-bar-wrapper {
  flex: 1;
  min-width: 4px;
  display: flex;
  align-items: flex-end;
  transition: height 0.3s;
}

.chart-bar {
  width: 100%;
  border-radius: 3px 3px 0 0;
  position: relative;
  transition: all 0.2s;
  min-height: 4px;
}

.chart-bar:hover {
  opacity: 0.9;
  transform: scaleX(1.05);
  box-shadow: 0 -2px 8px rgba(255, 215, 0, 0.3);
}

.bar-score {
  position: absolute;
  top: -16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.chart-footer {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-tertiary);
  padding: 4px 0;
}

.history-stats {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 16px;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border-color);
}

.stat-row:last-child {
  border-bottom: none;
}

.stat-row span:first-child {
  color: var(--text-secondary);
  font-size: 12px;
}

.trend-indicator {
  font-size: 12px;
  font-weight: 600;
}

.trend-indicator.up {
  color: #ff4757;
}

.trend-indicator.down {
  color: #2ed573;
}

.trend-indicator.stable {
  color: var(--text-secondary);
}

.trend-value {
  font-size: 10px;
  opacity: 0.7;
  margin-left: 4px;
}

/* 调整记录视图 */
.adjustments-timeline {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 20px;
}

.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.timeline-item {
  display: flex;
  gap: 16px;
}

.timeline-marker {
  width: 24px;
  height: 24px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  margin-top: 2px;
}

.timeline-marker.up {
  background: rgba(255, 71, 87, 0.1);
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.3);
}

.timeline-marker.down {
  background: rgba(46, 213, 115, 0.1);
  color: #2ed573;
  border: 1px solid rgba(46, 213, 115, 0.3);
}

.timeline-content {
  flex: 1;
  background: var(--bg-primary);
  border-radius: 14px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 10px;
  color: var(--text-tertiary);
}

.timeline-body {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.weight-change {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}

.weight-change.up {
  color: #ff4757;
}

.weight-change.down {
  color: #2ed573;
}

.change-badge {
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 10px;
  font-size: 10px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px;
  gap: 12px;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.empty-text {
  font-size: 12px;
}

.adjustments-summary {
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 20px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 12px;
}

.summary-item {
  background: var(--bg-primary);
  border-radius: 12px;
  padding: 12px;
  text-align: center;
  border: 1px solid var(--border-color);
}

.summary-label {
  display: block;
  font-size: 10px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.summary-value {
  font-size: 16px;
  font-weight: bold;
}

.summary-value.up {
  color: #ff4757;
}

.summary-value.down {
  color: #2ed573;
}

/* 底部 */
.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 10px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.update-dot {
  width: 8px;
  height: 8px;
  border-radius: 4px;
}

.update-text {
  color: var(--text-tertiary);
}

.source-badge {
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}

.datachain-view {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 4px 0;
}

.chain-summary {
  padding: 16px;
  border-radius: 12px;
  background: var(--bg-secondary);
}

.chain-summary.healthy {
  border-left: 4px solid #2ed573;
}

.chain-summary.degraded {
  border-left: 4px solid #ffa502;
}

.chain-summary.critical {
  border-left: 4px solid #ff4757;
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.summary-icon {
  font-size: 20px;
}

.summary-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.summary-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.stat .label {
  font-size: 10px;
  color: var(--text-tertiary);
}

.stat .value {
  font-size: 16px;
  font-weight: bold;
  color: var(--text-primary);
}

.chain-layer {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 16px;
}

.layer-header {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-title);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.layer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 12px;
}

.layer-card {
  background: var(--bg-primary);
  border-radius: 10px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.layer-card.source {
  border-left: 3px solid #3498db;
}

.layer-card.processor {
  border-left: 3px solid #9b59b6;
}

.layer-card.calculator {
  border-left: 3px solid #e67e22;
}

.layer-card.cache {
  border-left: 3px solid #2ecc71;
}

.layer-card.presentation {
  border-left: 3px solid #f1c40f;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.card-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-badge {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 500;
}

.card-badge.active,
.card-badge.healthy {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
}

.card-badge.degraded,
.card-badge.warning {
  background: rgba(255, 165, 2, 0.2);
  color: #ffa502;
}

.card-badge.failed,
.card-badge.critical {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
}

.card-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.metric {
  display: flex;
  flex-direction: column;
}

.metric-label {
  font-size: 9px;
  color: var(--text-tertiary);
  margin-bottom: 2px;
}

.metric-value {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.metric-value.good {
  color: #2ed573;
}

.metric-value.warn {
  color: #e67e22;
}

.metric-value.danger {
  color: #ff4757;
}

.card-error {
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(255, 71, 87, 0.1);
  border-radius: 6px;
  color: #ff4757;
  font-size: 10px;
}

.card-hotkeys {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.hotkey-title {
  font-size: 9px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}

.hotkey-item {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  margin-bottom: 4px;
}

.hotkey-name {
  color: var(--text-secondary);
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hotkey-count {
  color: var(--color-highlight);
  font-weight: 500;
}

.chain-bottlenecks,
.chain-warnings {
  padding: 16px;
  border-radius: 12px;
  background: var(--bg-secondary);
}

.bottleneck-header {
  color: #ff4757;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.warning-header {
  color: #ffa502;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.bottleneck-list,
.warning-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-secondary);
  font-size: 11px;
}

.bottleneck-list li,
.warning-list li {
  margin-bottom: 4px;
}

.empty-data {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px;
  background: var(--bg-secondary);
  border-radius: 16px;
  color: var(--text-tertiary);
  gap: 10px;
}

.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.empty-text {
  font-size: 12px;
}
</style>
