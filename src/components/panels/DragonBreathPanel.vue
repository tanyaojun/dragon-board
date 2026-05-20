<!-- src/components/panels/DragonBreathPanel.vue -->
<!-- 纯响应式版本：只依赖 dataLayer，面板统一显示五阶段情绪周期 -->

<template>
  <div v-show="visible" class="breath-panel" :style="panelStyle" ref="panelRef">
    <!-- 头部 -->
    <div class="panel-header">
      <div class="header-left">
        <div class="panel-kicker">DRAGON BREATH</div>
        <h3>龙息市场情绪</h3>
        <div class="stats-badge" v-if="marketData">
          <span :class="marketData.upCount >= marketData.downCount ? 'up-text' : ''">
            {{ formatNumber(marketData.upCount) }}涨
          </span>
          <span class="dot">•</span>
          <span :class="marketData.downCount > marketData.upCount ? 'down-text' : ''">
            {{ formatNumber(marketData.downCount) }}跌
          </span>
        </div>
      </div>
      <div class="panel-actions">
        <button class="btn-icon action-refresh" @click.stop="refresh" :class="{ loading }" title="刷新" aria-label="刷新">
          刷新
        </button>
        <button class="btn-icon" @click.stop="exportData" title="导出数据" aria-label="导出数据">
          导出
        </button>
        <button class="btn-icon close-btn" @click.stop="handleClose" title="关闭" aria-label="关闭">关闭</button>
      </div>
    </div>

    <!-- 情绪卡片 - 五阶段情绪周期 -->
    <div class="sentiment-card" :class="`stage-${displaySentiment.stageClass}`">
      <div class="sentiment-main">
        <div class="sentiment-left">
          <div class="sentiment-stage-badge" :style="{ borderColor: stageColor }">
            <span class="stage-badge-icon"></span>
          </div>
          <div class="sentiment-info">
            <span class="sentiment-label">当前周期</span>
            <div class="sentiment-phase">
              {{ displaySentiment.stageName }}
            </div>
            <div class="sentiment-risk" :class="`risk-${displaySentiment.riskLevel}`">
              <span class="risk-dot"></span>
              {{ displaySentiment.riskLevel }}风险
            </div>
            <div class="sentiment-suggestion">{{ displaySentiment.suggestion || '暂无建议' }}</div>
          </div>
        </div>
        <div class="sentiment-stats">
          <div class="stat-row">
            <span class="stat-label">涨停</span>
            <span class="stat-value up-text">{{ marketData.ztCount }}</span>
            <span class="stat-sub">炸板 {{ marketData.zhaban?.count || 0 }}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">跌停</span>
            <span class="stat-value down-text">{{ marketData.dtCount }}</span>
            <span class="stat-sub">封板 {{ marketData.zhaban?.fengbanRate?.toFixed(0) || 0 }}%</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">连板</span>
            <span class="stat-value up-text">
              {{ marketData.limitData.yiban }}/{{ marketData.limitData.erban }}/{{
                marketData.limitData.sanban
              }}+{{ marketData.limitData.sibanPlus }}
            </span>
            <span class="stat-sub">最高 {{ marketData.limitData.sibanPlus || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 标签页 -->
    <div class="panel-tabs">
      <button class="tab-btn" :class="{ active: view === 'overview' }" @click="view = 'overview'">
        市场概览
      </button>
      <button class="tab-btn" :class="{ active: view === 'hotlist' }" @click="view = 'hotlist'">
        热榜情绪
      </button>
      <button class="tab-btn" :class="{ active: view === 'limit' }" @click="view = 'limit'">
        连板分析
      </button>
      <button class="tab-btn" :class="{ active: view === 'money' }" @click="view = 'money'">
        资金流向
      </button>
      <button class="tab-btn" :class="{ active: view === 'plates' }" @click="view = 'plates'">
        热点板块
      </button>
      <button class="tab-btn" :class="{ active: view === 'factors' }" @click="view = 'factors'">
        龙息因子
      </button>
    </div>

    <!-- 内容区域 -->
    <div class="panel-content" ref="contentRef">
      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span>加载市场数据...</span>
      </div>

      <!-- 错误状态 -->
      <div v-else-if="error" class="error-state">
        <span class="error-icon">⚠️</span>
        <span>{{ error }}</span>
        <button class="retry-btn" @click="loadData">重试</button>
      </div>

      <template v-else>
        <!-- 市场概览视图 -->
        <div v-if="view === 'overview'" class="overview-view">
          <!-- 情绪指标网格 -->
          <div class="metrics-grid">
            <div class="metric-item metric-primary">
              <span class="metric-label">上涨家数</span>
              <span class="metric-value up-text">{{ marketData.upCount }}</span>
              <span class="metric-percent">{{ upRatio }}%</span>
            </div>
            <div class="metric-item metric-primary">
              <span class="metric-label">下跌家数</span>
              <span class="metric-value down-text">{{ marketData.downCount }}</span>
              <span class="metric-percent">{{ downRatio }}%</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">涨停家数</span>
              <span class="metric-value up-text">{{ marketData.ztCount }}</span>
              <span class="metric-percent">昨日 {{ formatNullableCount(marketData.previousMarketStats?.ztCount) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">跌停家数</span>
              <span class="metric-value down-text">{{ marketData.dtCount }}</span>
              <span class="metric-percent">昨日 {{ formatNullableCount(marketData.previousMarketStats?.dtCount) }}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">总成交额</span>
              <span class="metric-value">{{ formatAmount(marketData.totalAmo) }}</span>
              <span class="metric-percent" :class="marketData.amoDiff >= 0 ? 'up-text' : 'down-text'">
                {{ marketData.amoDiff >= 0 ? '+' : '' }}{{ formatAmount(marketData.amoDiff) }}
              </span>
            </div>
            <div class="metric-item">
              <span class="metric-label">量比</span>
              <span class="metric-value">{{ marketData.volumeRatio?.toFixed(2) || '--' }}</span>
              <span class="metric-percent">昨涨停 {{ formatPercent(marketData.yesterdayZtPerformance) }}</span>
            </div>
          </div>

          <!-- 涨跌比例图 -->
          <div class="ratio-section">
            <div class="ratio-header">
              <span class="ratio-title">市场宽度分布</span>
              <div class="ratio-values">
                <span class="up-text">上涨 {{ upRatio }}%</span>
                <span class="dot">|</span>
                <span class="down-text">下跌 {{ downRatio }}%</span>
              </div>
            </div>
            <div class="ratio-bar-container">
              <div class="ratio-bar">
                <div class="ratio-bar-up" :style="{ width: upRatio + '%' }"></div>
                <div class="ratio-bar-down" :style="{ width: downRatio + '%' }"></div>
              </div>
            </div>
          </div>

          <!-- 指数表现 -->
          <div class="indices-section">
            <div class="section-title">主要指数</div>
            <div class="indices-grid">
              <div v-for="item in indexItems" :key="item.key" class="index-item">
                <span class="index-name">{{ item.name }}</span>
                <span class="index-value" :class="getChangeClass(item.value)">
                  {{ formatPercent(item.value) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 热榜情绪视图 -->
        <div v-if="view === 'hotlist'" class="hotlist-view">
          <div v-if="hotListSentimentLoading && !hotListSentiment" class="mini-loading">正在分析热榜情绪...</div>
          <div v-else-if="hotListSentimentError && !hotListSentiment" class="error-state compact">
            <span class="error-icon">⚠️</span>
            <span>{{ hotListSentimentError }}</span>
            <button class="retry-btn" @click="loadHotListSentiment">重试</button>
          </div>
          <template v-else-if="hotListSentiment">
            <div v-if="hotListSentimentLoading" class="hotlist-refresh-status">正在刷新热榜情绪...</div>
            <div class="hotlist-stage-card" :class="`stage-${hotListStage.classKey}`">
              <div class="hotlist-stage-main">
                <span class="hotlist-stage-label">热榜情绪</span>
                <span class="hotlist-stage-value">{{ hotListStage.name }}</span>
                <span class="hotlist-confidence">置信 {{ hotListSentiment.confidence }}%</span>
              </div>
              <div class="hotlist-summary">{{ hotListSentiment.summary }}</div>
            </div>

            <div class="hotlist-section research-hotlist-card">
              <div class="section-title">ThemeTrend 共振解释</div>
              <div class="research-status">{{ themeResearch.statusText }}</div>
              <div class="research-lines">
                <span>{{ themeResearch.hotlistConfluenceText }}</span>
                <span>{{ themeResearch.riskText }}</span>
              </div>
              <div v-if="hotlistThemeResearchItems.length" class="theme-research-stock-grid">
                <div
                  v-for="item in hotlistThemeResearchItems"
                  :key="item.code"
                  class="theme-research-stock"
                  :class="{ noise: item.noise }"
                >
                  <div class="research-stock-main">
                    <span class="research-stock-name">{{ item.name }}</span>
                    <span class="research-stock-score">{{ item.confluenceScore }}</span>
                  </div>
                  <div class="research-stock-sub">
                    <span>{{ item.themeName || '无题材' }}</span>
                    <span>{{ item.themeRole }}</span>
                  </div>
                  <div class="research-stock-reason">
                    {{ item.filterReason || item.entryReason }}
                  </div>
                </div>
              </div>
            </div>

            <div class="metrics-grid hotlist-metrics">
              <div class="metric-item">
                <span class="metric-label">热榜池</span>
                <span class="metric-value">{{ hotListToday?.total || 0 }}</span>
                <span class="metric-percent" :class="getDeltaClass(hotListComparison?.totalChange1d)">
                  昨比 {{ formatSignedInt(hotListComparison?.totalChange1d) }}
                </span>
              </div>
              <div class="metric-item">
                <span class="metric-label">全池上涨</span>
                <span class="metric-value up-text">{{ formatShare(hotListToday?.upRatio) }}</span>
                <span class="metric-percent">{{ hotListToday?.upCount || 0 }}涨 / {{ hotListToday?.downCount || 0 }}跌</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">热榜TRIN</span>
                <span class="metric-value" :class="getTrinClass(hotListToday?.hotTrin)">
                  {{ formatTrin(hotListToday?.hotTrin) }}
                </span>
                <span class="metric-percent">{{ getTrinText(hotListToday?.hotTrin) }}</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">留榜率</span>
                <span class="metric-value">{{ formatShare(hotListComparison?.top100RetainRateFromYesterday) }}</span>
                <span class="metric-percent">昨日全池</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">强资+点火</span>
                <span class="metric-value up-text">
                  {{ hotListActiveOpportunityCount }}
                </span>
                <span class="metric-percent">{{ formatShare(hotListActiveOpportunityShare) }}</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">风险压力</span>
                <span class="metric-value down-text">{{ hotListToday?.riskCount || 0 }}</span>
                <span class="metric-percent">{{ formatShare(hotListToday?.riskShare) }}</span>
              </div>
            </div>

            <div class="hotlist-section">
              <div class="section-title">📌 分层结构</div>
              <div class="history-grid layer-grid">
                <div v-for="item in hotListLayerItems" :key="item.label" class="history-item">
                  <span class="history-label">{{ item.label }}</span>
                  <span class="history-main">{{ item.upRatio }}</span>
                  <span class="history-sub">
                    机会 {{ item.activeOpportunity }} · 拥挤 {{ item.crowded }} · 风险 {{ item.risk }}
                  </span>
                  <span class="history-sub">TRIN {{ item.trin }} · 均涨 {{ item.avgChange }}</span>
                </div>
              </div>
            </div>

            <div class="hotlist-section">
              <div class="section-title">📈 涨停证据</div>
              <div class="history-grid limit-evidence-grid">
                <div v-for="item in hotListLimitEvidenceItems" :key="item.label" class="history-item">
                  <span class="history-label">{{ item.label }}</span>
                  <span class="history-main">{{ item.main }}</span>
                  <span class="history-sub">{{ item.sub }}</span>
                </div>
              </div>
              <div class="history-extra">
                <span>全市场涨停 {{ hotListMarketLimitEvidence?.ztCount || 0 }} 只</span>
                <span>全市场炸板 {{ hotListMarketLimitEvidence?.zhabanCount || 0 }} 只</span>
                <span>THS炸板池 {{ hotListMarketLimitEvidence?.thsPools?.failedCount || 0 }} 只</span>
                <span>涨停股回撤榜 {{ hotListMarketLimitEvidence?.thsPools?.drawdownCount || 0 }} 只</span>
                <span>封板率 {{ formatPercentValue(hotListMarketLimitEvidence?.fengbanRate) }}</span>
              </div>
            </div>

            <div class="hotlist-section">
              <div class="section-title">📊 全池状态结构</div>
              <div class="status-distribution">
                <div v-for="item in hotListStatusItems" :key="item.label" class="status-item">
                  <div class="status-row">
                    <span class="status-label">{{ item.label }}</span>
                    <span class="status-count">{{ item.count }}</span>
                  </div>
                  <div class="status-bar">
                    <div class="status-bar-fill" :class="`status-${item.classKey}`" :style="{ width: item.shareText }"></div>
                  </div>
                  <span class="status-share">{{ item.shareText }}</span>
                </div>
              </div>
            </div>

            <div class="hotlist-section">
              <div class="section-title">🗓️ 三日对比</div>
              <div class="history-grid">
                <div v-for="item in hotListHistoryItems" :key="item.label" class="history-item">
                  <span class="history-label">{{ item.label }}</span>
                  <span class="history-main">{{ item.total }}</span>
                  <span class="history-sub">
                    强资 {{ item.strongMoney }} · 拥挤 {{ item.crowded }} · 风险 {{ item.risk }}
                  </span>
                </div>
              </div>
              <div class="history-extra">
                <span>今日新入全池 {{ hotListComparison?.newTop100Count || 0 }} 只</span>
                <span>新入强资 {{ hotListComparison?.newTop100StrongMoneyCount || 0 }} 只</span>
                <span>昨日强资留榜 {{ formatShare(hotListComparison?.yesterdayStrongRetainRate) }}</span>
                <span>昨日强票均涨 {{ formatPercent(hotListYesterdayStrongPerformance?.avgChange) }}</span>
                <span>昨日强票正收益 {{ formatShare(hotListYesterdayStrongPerformance?.positiveRate) }}</span>
                <span>昨日强票转弱 {{ formatShare(hotListYesterdayStrongPerformance?.weakeningRate) }}</span>
              </div>
            </div>

            <div class="hotlist-evidence-grid">
              <div class="hotlist-section">
                <div class="section-title">✅ 强证据</div>
                <ul class="evidence-list">
                  <li v-for="signal in hotListSentiment.signals" :key="signal">{{ signal }}</li>
                </ul>
              </div>
              <div class="hotlist-section">
                <div class="section-title">⚠️ 风险提示</div>
                <ul class="evidence-list">
                  <li v-for="warning in hotListSentiment.warnings" :key="warning">{{ warning }}</li>
                </ul>
              </div>
            </div>
          </template>
          <div v-else class="empty-state">暂无热榜情绪数据</div>
        </div>

        <!-- 连板分析视图 -->
        <div v-if="view === 'limit'" class="limit-view">
          <!-- 连板统计卡片 -->
          <div class="limit-stats-grid">
            <div class="limit-stat-card">
              <span class="limit-label">一板</span>
              <span class="limit-value up-text">{{ marketData.limitData.yiban }}</span>
              <span class="limit-sub">昨日 {{ marketData.yesterdayLimit?.yiban || 0 }}</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">二板</span>
              <span class="limit-value up-text">{{ marketData.limitData.erban }}</span>
              <span class="limit-sub">晋级率 {{ erbanRate }}%</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">三板</span>
              <span class="limit-value up-text">{{ marketData.limitData.sanban }}</span>
              <span class="limit-sub">晋级率 {{ sanbanRate }}%</span>
            </div>
            <div class="limit-stat-card">
              <span class="limit-label">四板+</span>
              <span class="limit-value up-text">{{ marketData.limitData.sibanPlus }}</span>
              <span class="limit-sub">晋级率 {{ sibanPlusRate }}%</span>
            </div>
          </div>

          <!-- 连板分布柱状图 -->
          <div class="limit-distribution">
            <div class="section-title">📊 连板分布</div>
            <div class="limit-bars">
              <div v-for="(item, index) in limitBarData" :key="index" class="limit-bar-item">
                <div class="limit-bar" :style="{ height: item.height + 'px' }">
                  <span class="limit-bar-value">{{ item.count }}</span>
                </div>
                <span class="limit-bar-label">{{ item.label }}</span>
              </div>
            </div>
          </div>

          <!-- 炸板分析 -->
          <div class="zhaban-section">
            <div class="zhaban-header">
              <span class="zhaban-title">💥 炸板分析</span>
              <span class="zhaban-rate">{{ (marketData.zhaban?.rate || 0).toFixed(2) }}%</span>
            </div>
            <div class="zhaban-bar">
              <div class="zhaban-bar-fill" :style="{ width: (marketData.zhaban?.rate || 0) + '%' }"></div>
            </div>
            <div class="zhaban-stats">
              <span>炸板: {{ marketData.zhaban?.count || 0 }} 家</span>
              <span>封板: {{ marketData.zhaban?.ztCount || 0 }} 家</span>
              <span>封板率: {{ marketData.zhaban?.fengbanRate?.toFixed(2) || 0 }}%</span>
            </div>
          </div>

          <!-- 晋级率分析 -->
          <div class="promotion-section">
            <div class="section-title">📈 晋级率</div>
            <div class="promotion-grid">
              <div class="promotion-item">
                <span class="promotion-label">一进二</span>
                <span class="promotion-value">{{ erbanRate }}%</span>
              </div>
              <div class="promotion-item">
                <span class="promotion-label">二进三</span>
                <span class="promotion-value">{{ sanbanRate }}%</span>
              </div>
              <div class="promotion-item">
                <span class="promotion-label">三进四</span>
                <span class="promotion-value">{{ sibanPlusRate }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 资金流向视图 -->
        <div v-if="view === 'money'" class="money-view">
          <!-- 主力资金 -->
          <div class="money-section">
            <div class="section-title">💰 主力资金</div>
            <div class="money-main">
              <div class="money-item large">
                <span class="money-label">主力净额</span>
                <span class="money-value" :class="(marketData.moneyFlow?.main || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.moneyFlow?.main) }}
                </span>
              </div>
              <div class="money-item">
                <span class="money-label">散户净额</span>
                <span class="money-value" :class="(marketData.moneyFlow?.retail || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.moneyFlow?.retail) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 资金流向图 -->
          <div class="flow-section">
            <div class="section-title">📊 资金流向比例</div>
            <div class="flow-chart">
              <div class="flow-bar">
                <div class="flow-bar-in" :style="{
                  width: getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo) + '%',
                }">
                  <span class="flow-label" v-if="getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo) > 10">
                    主力
                    {{
                      getFlowPercent(marketData.moneyFlow?.main, marketData.totalAmo).toFixed(1)
                    }}%
                  </span>
                </div>
                <div class="flow-bar-out" :style="{
                  width: getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo) + '%',
                }">
                  <span class="flow-label"
                    v-if="getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo) > 10">
                    散户
                    {{
                      getFlowPercent(marketData.moneyFlow?.retail, marketData.totalAmo).toFixed(1)
                    }}%
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 超大单资金 -->
          <div class="super-money-section">
            <div class="section-title">💎 超大单资金</div>
            <div class="super-money-grid">
              <div class="super-money-item">
                <span class="label">超大单净额</span>
                <span class="value" :class="(marketData.cddje || 0) >= 0 ? 'up-text' : 'down-text'">
                  {{ formatAmount(marketData.cddje) }}
                </span>
              </div>
              <div class="super-money-item">
                <span class="label">超大单占比</span>
                <span class="value">{{ marketData.cddjzb?.toFixed(2) || 0 }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 热点板块视图 -->
        <div v-if="view === 'plates'" class="plates-view">
          <div class="plates-list">
            <div v-for="plate in hotPlates" :key="plate.id" class="plate-item"
              :class="{ active: selectedPlate === plate.id }" @click="selectPlate(plate.id)">
              <div class="plate-header">
                <span class="plate-name">{{ plate.name }}</span>
                <span class="plate-change" :class="plate.pcp >= 0 ? 'up-text' : 'down-text'">
                  {{ plate.pcp > 0 ? '+' : '' }}{{ plate.pcp.toFixed(2) }}%
                </span>
                <span class="plate-count">{{ plate.stockCount }}家</span>
              </div>
              <div class="plate-desc">{{ plate.desc }}</div>
              <div class="plate-stocks" v-if="selectedPlate === plate.id">
                <div v-for="stock in (plate.stocks as any[])" :key="stock.code" class="plate-stock">
                  <span class="stock-code">{{ stock.code }}</span>
                  <span class="stock-name">{{ stock.name }}</span>
                  <span class="stock-change" :class="(stock.change || 0) >= 0 ? 'up-text' : 'down-text'">
                    {{ (stock.change || 0) > 0 ? '+' : '' }}{{ (stock.change || 0).toFixed(2) }}%
                  </span>
                </div>
              </div>
            </div>
            <div v-if="hotPlates.length === 0" class="empty-state">暂无热点板块数据</div>
          </div>
        </div>

        <!-- 龙息因子视图 -->
        <div v-if="view === 'factors'" class="factors-view">
          <div class="factors-header">
            <h4>🔥 龙息因子 ({{ breathFactors.length }})</h4>
            <span class="factor-tip">原始结构证据，仅用于解释阶段</span>
          </div>

          <!-- 因子卡片网格 -->
          <div class="factors-grid" v-if="breathFactors.length > 0">
            <div v-for="factor in breathFactors" :key="factor.id" class="factor-card">
              <div class="factor-header">
                <span class="factor-name">{{ factor.name }}</span>
                <span class="factor-state" :class="getFactorStateClass(factor)">
                  {{ getFactorStateText(factor) }}
                </span>
              </div>
              <div class="factor-raw" :style="{ color: getFactorValueColor(factor.rawValue, factor.id) }">
                {{ formatRawValue(factor.rawValue, factor.unit) }}
              </div>
              <div class="factor-desc">{{ factor.description }}</div>
            </div>
          </div>

          <!-- 操作建议卡片 -->
          <div class="suggestions-card">
            <div class="suggestions-header">
              <span class="suggestions-icon">💡</span>
              <span class="suggestions-title">操作建议</span>
            </div>
            <ul class="suggestions-list">
              <li v-for="(suggestion, index) in suggestions" :key="index">
                {{ suggestion }}
              </li>
            </ul>
          </div>
        </div>
      </template>
    </div>

    <!-- 底部 -->
    <div class="panel-footer">
      <span class="update-time">更新: {{ formatTime(marketData.timestamp) }}</span>
      <span class="dot">•</span>
      <span class="source-info">数据源: 通达信/选股通</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/logger'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import {
  hotListSentimentAnalyzer,
  type HotListDayMetrics,
  type HotListSentimentResult,
  type HotListStatusLabel,
} from '@/services/hotlist/HotListSentimentAnalyzer'
import type { SnapshotFrameBundle } from '@/services/snapshot/types'
import { FORMAL_SNAPSHOT_READ_POLICY } from '@/services/snapshot/readPolicy'
import { snapshotFacade } from '@/services/snapshot/facade'
import {
  EMOTION_PHASE_BY_VALUE,
  EMOTION_PHASE_LIST,
  type UnifiedEmotionStage,
} from '@/types/emotion'
import { usePanel } from '@/composables/usePanel'
import {
  buildHotlistThemeResearchItems,
  buildThemeResearchExplanation,
  loadThemeResearchExplanation,
  type HotlistThemeResearchItem,
  type ThemeResearchExplanation,
} from '@/services/theme/themeResearchSummary'

type EmotionStageClassKey = 'ice' | 'start' | 'ferment' | 'climax' | 'retreat'

interface FactorItem {
  id: string
  name: string
  rawValue: number
  unit: string
  description: string
}

interface DisplayEmotionStage {
  name: UnifiedEmotionStage
  classKey: EmotionStageClassKey
  color: string
  gradient: string
  icon: string
  suggestion: string
}

interface DisplaySentiment {
  stage: UnifiedEmotionStage
  stageName: UnifiedEmotionStage
  stageClass: EmotionStageClassKey
  riskLevel: string
  suggestion: string
}

const EMOTION_STAGE_NAMES: UnifiedEmotionStage[] = ['冰点', '启动', '发酵', '高潮', '退潮']
const EMOTION_STAGE_CONFIG = EMOTION_PHASE_LIST.reduce(
  (record, phase) => {
    record[phase.name as UnifiedEmotionStage] = {
      name: phase.name as UnifiedEmotionStage,
      classKey: phase.value as EmotionStageClassKey,
      color: phase.color,
      gradient: phase.gradient,
      icon: phase.icon,
      suggestion: phase.suggestion,
    }
    return record
  },
  {} as Record<UnifiedEmotionStage, DisplayEmotionStage>,
)

const props = defineProps<{
  visible: boolean
  triggerRect?: DOMRect
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

// ========== 面板定位 ==========
function handleClose() {
  emit('update:visible', false)
  emit('close')
}

const { panelRef, panelStyle } = usePanel({
  name: 'DragonBreathPanel',
  visible: props.visible,
  triggerRect: props.triggerRect,
  triggerSelectors: ['[title*="龙息分析"]'],
  onClose: handleClose,
})

// ========== 状态 ==========
const loading = ref(false)
const error = ref<string | null>(null)
const view = ref<'overview' | 'hotlist' | 'limit' | 'money' | 'plates' | 'factors'>('factors')
const selectedPlate = ref<number | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const unsubscribeFns: (() => void)[] = []
const hotListSentiment = ref<HotListSentimentResult | null>(null)
const hotListSentimentLoading = ref(false)
const hotListSentimentError = ref<string | null>(null)
const themeResearch = ref<ThemeResearchExplanation>(buildThemeResearchExplanation({ available: false, reason: 'not_loaded' }))
let hotListSentimentTimer: ReturnType<typeof setTimeout> | null = null
let hotListSentimentRetryCount = 0



// ========== 从 dataLayer 获取数据 ==========

// 市场数据
const marketData = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const marketData = breath?.marketData || {}

  return {
    upCount: marketData.upCount ?? 0,
    downCount: marketData.downCount ?? 0,
    ztCount: marketData.ztCount ?? 0,
    dtCount: marketData.dtCount ?? 0,
    largeCapChange: marketData.largeCapChange ?? 0,
    microCapChange: marketData.microCapChange ?? 0,
    passRate: marketData.passRate ?? { to2: 0, to3: 0, to4: 0 },
    limitData: marketData.limitData ?? { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
    yesterdayLimit: marketData.yesterdayLimit ?? {},
    previousMarketStats: marketData.previousMarketStats ?? null,
    zhaban: marketData.zhaban ?? {},
    moneyFlow: marketData.moneyFlow ?? {},
    totalAmo: marketData.totalAmo ?? 0,
    amoDiff: marketData.amoDiff ?? 0,
    volumeRatio: marketData.volumeRatio ?? 0,
    indices: marketData.indices ?? {},
    cddje: marketData.cddje ?? 0,
    cddjzb: marketData.cddjzb ?? 0,
    yesterdayZtPerformance: marketData.yesterdayZtPerformance,
    thsLimitUpPools: marketData.thsLimitUpPools ?? null,
    timestamp: marketData.timestamp ?? Date.now(),
  }
})

// 情绪数据
const sentiment = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const sent = breath?.sentiment || {}
  const stage = resolveDisplayEmotionStage(sent)

  return {
    stage: stage.name,
    stageName: stage.name,
    stageClass: stage.classKey,
    riskLevel: sent.riskLevel || '中',
    suggestion: sent.suggestion || stage.suggestion,
  }
})

function resolveDisplayEmotionStage(source: any): DisplayEmotionStage {
  const candidates = [
    source?.stage,
    source?.stageName,
    source?.cycleStage,
    source?.emotionStage,
    source?.phaseName,
    source?.phase,
  ]

  for (const candidate of candidates) {
    const stage = normalizeEmotionStage(candidate)
    if (stage) return EMOTION_STAGE_CONFIG[stage]
  }

  return EMOTION_STAGE_CONFIG.启动
}

function getDisplayEmotionStage(value?: unknown): DisplayEmotionStage {
  const stage = normalizeEmotionStage(value)
  return stage ? EMOTION_STAGE_CONFIG[stage] : EMOTION_STAGE_CONFIG.启动
}

function normalizeEmotionStage(value?: unknown): UnifiedEmotionStage | null {
  if (typeof value !== 'string') return null
  const raw = value.trim()
  const name = raw.endsWith('期') ? raw.slice(0, -1) : raw
  if ((EMOTION_STAGE_NAMES as string[]).includes(name)) return name as UnifiedEmotionStage

  const valueNameMap: Record<string, UnifiedEmotionStage> = {
    ice: '冰点',
    start: '启动',
    ferment: '发酵',
    climax: '高潮',
    retreat: '退潮',
  }
  const byValue = EMOTION_PHASE_BY_VALUE[raw.toLowerCase()]
  return valueNameMap[raw.toLowerCase()] || (byValue?.name as UnifiedEmotionStage | undefined) || null
}

// 龙息因子数据（9个因子统一显示）
const breathFactors = computed(() => {
  const breath = (dataLayer as any).state?.analysis?.breath
  const factors = breath?.factors || []

  const factorNameMap: Record<string, string> = {
    promotionRate: '晋级率',
    yesterdayZtAvgChange: '昨日涨停表现',
    ztCount: '涨停数',
    dtCount: '跌停数',
    zhabanRate: '炸板率',
    maxContinuousDays: '连板高度',
    upDownRatio: '涨跌比',
    volumeRatio: '量比',
    tdxEmotion: '通达信情绪',
  }

  const factorUnitMap: Record<string, string> = {
    promotionRate: '%',
    yesterdayZtAvgChange: '%',
    ztCount: '家',
    dtCount: '家',
    zhabanRate: '%',
    maxContinuousDays: '天',
    upDownRatio: '倍',
    volumeRatio: '',
    tdxEmotion: '',
  }

  const factorDescMap: Record<string, string> = {
    promotionRate: '昨日涨停今日继续涨停的比例（加权平均）',
    yesterdayZtAvgChange: '昨日涨停股今日平均涨幅',
    ztCount: '当日涨停家数，反映进攻意愿',
    dtCount: '当日跌停家数，反映市场风险',
    zhabanRate: '炸板率越低，涨停质量越高',
    maxContinuousDays: '市场最高连板天数',
    upDownRatio: '上涨家数/下跌家数',
    volumeRatio: '今日成交量/昨日成交量',
    tdxEmotion: '通达信专业情绪指标',
  }

  return factors.map((factor: any) => {
    return {
      id: factor.id,
      name: factorNameMap[factor.id] || factor.name || '未知因子',
      rawValue: factor.rawValue ?? 0,
      unit: factorUnitMap[factor.id] || '',
      description: factorDescMap[factor.id] || factor.description || '暂无描述',
    }
  })
})

// 热点板块
const hotPlates = computed(() => {
  const hotThemes = dataLayer.getHotThemes?.() || []
  return hotThemes.slice(0, 5).map((theme: any, index: number) => ({
    id: theme.id || index,
    name: theme.name,
    pcp: theme.heatScore > 3000 ? 3.5 : theme.heatScore > 1500 ? 1.5 : -0.5,
    stockCount: theme.stockCount || 0,
    desc: getThemeDescription(theme),
    stocks: [],
  }))
})

const hotListComparison = computed(() => hotListSentiment.value?.metrics.comparison ?? null)
const hotListToday = computed<HotListDayMetrics | null>(() => hotListComparison.value?.today ?? null)
const hotListLimitEvidence = computed(() => hotListSentiment.value?.metrics.limitEvidence ?? null)
const hotListMarketLimitEvidence = computed(() => hotListLimitEvidence.value?.market ?? null)
const hotListYesterdayStrongPerformance = computed(
  () => hotListComparison.value?.yesterdayStrongPerformance ?? null,
)
const hotListActiveOpportunityCount = computed(() => {
  const counts = hotListToday.value?.statusCounts
  if (!counts) return 0
  return hotListToday.value?.activeOpportunityCount ?? counts['强资确认'] + counts['点火观察']
})
const hotListActiveOpportunityShare = computed(() => {
  const sampleSize = hotListToday.value?.topN || 0
  return sampleSize ? hotListActiveOpportunityCount.value / sampleSize : 0
})

const hotlistThemeResearchItems = computed<HotlistThemeResearchItem[]>(() =>
  buildHotlistThemeResearchItems(dataLayer.getStocks() as Array<Record<string, any>>, themeResearch.value, 6),
)

const hotListStage = computed(() => getDisplayEmotionStage(hotListSentiment.value?.stage))

const displaySentiment = computed<DisplaySentiment>(() => {
  if (view.value === 'hotlist' && hotListSentiment.value) {
    return {
      stage: hotListStage.value.name,
      stageName: hotListStage.value.name,
      stageClass: hotListStage.value.classKey,
      riskLevel: hotListSentiment.value.riskLevel || getStageRiskLevel(hotListStage.value.name),
      suggestion: hotListSentiment.value.summary || hotListStage.value.suggestion,
    }
  }

  return sentiment.value
})

const hotListStatusOrder: Array<{ label: HotListStatusLabel; classKey: string }> = [
  { label: '主升确认', classKey: 'main' },
  { label: '点火观察', classKey: 'ignition' },
  { label: '强资确认', classKey: 'strong' },
  { label: '新入观察', classKey: 'new' },
  { label: '高位拥挤', classKey: 'crowded' },
  { label: '资金背离', classKey: 'divergence' },
  { label: '转弱预警', classKey: 'weakening' },
  { label: '样本不足', classKey: 'insufficient' },
]

const hotListStatusItems = computed(() => {
  const today = hotListToday.value
  if (!today) return []
  return hotListStatusOrder.map((item) => ({
    ...item,
    count: today.statusCounts[item.label] || 0,
    shareText: formatShare(today.statusShares[item.label] || 0),
  }))
})

const hotListLayerItems = computed(() => {
  const layers = hotListSentiment.value?.metrics.layers
  if (!layers) return []

  return [
    { label: '前20', metrics: layers.top20 },
    { label: '前50', metrics: layers.top50 },
    { label: '前100', metrics: layers.top100 },
  ].map(({ label, metrics }) => ({
    label,
    upRatio: formatShare(metrics.upRatio),
    activeOpportunity: `${metrics.activeOpportunityCount} / ${formatShare(metrics.activeOpportunityShare)}`,
    crowded: `${metrics.crowdedCount} / ${formatShare(metrics.crowdedShare)}`,
    risk: `${metrics.riskCount} / ${formatShare(metrics.riskShare)}`,
    trin: formatTrin(metrics.hotTrin),
    avgChange: formatPercent(metrics.avgChange),
  }))
})

const hotListLimitEvidenceItems = computed(() => {
  const evidence = hotListLimitEvidence.value
  if (!evidence) return []
  const intersection = evidence.intersection
  const yesterdayHotLimit = evidence.yesterdayHotLimit

  return [
    {
      label: '全池涨停',
      main: `${intersection.top100LimitUpCount}只`,
      sub: `占比 ${formatShare(intersection.top100LimitUpShare)} · 近涨停 ${intersection.top100NearLimitUpCount}只`,
    },
    {
      label: '连板高度',
      main: `${intersection.top100MaxBoardHeight || 0}板`,
      sub: `二板以上 ${intersection.top100Board2PlusCount}只`,
    },
    {
      label: '昨日热榜涨停',
      main: `${yesterdayHotLimit.count}只`,
      sub: `留榜 ${yesterdayHotLimit.retainedTop100Count}只 · 均涨 ${formatPercent(yesterdayHotLimit.avgChange)}`,
    },
    {
      label: '涨停持续性',
      main: formatShare(yesterdayHotLimit.positiveRate),
      sub: `走弱/失败 ${formatShare(yesterdayHotLimit.failedOrWeakRate)}`,
    },
  ]
})

const hotListHistoryItems = computed(() => {
  const comparison = hotListComparison.value
  if (!comparison) return []

  const toItem = (label: string, metrics?: HotListDayMetrics | null) => ({
    label,
    total: metrics ? `${metrics.total}只` : '--',
    strongMoney: metrics?.statusCounts['强资确认'] ?? 0,
    crowded: metrics?.statusCounts['高位拥挤'] ?? 0,
    risk: metrics ? metrics.statusCounts['资金背离'] + metrics.statusCounts['转弱预警'] : 0,
  })

  return [
    toItem('T 今日', comparison.today),
    toItem('T-1 昨日', comparison.yesterday),
    toItem('T-2 前日', comparison.dayBefore),
  ]
})

// ========== 五阶段情绪显示 ==========
const currentStage = computed(() => getDisplayEmotionStage(displaySentiment.value.stage))
const stageColor = computed(() => currentStage.value.color)

function getStageRiskLevel(stage: UnifiedEmotionStage): string {
  if (stage === '退潮') return '高'
  if (stage === '高潮') return '中'
  if (stage === '冰点') return '中'
  return '中'
}

// ========== 计算属性 ==========
const totalStocks = computed(() => marketData.value.upCount + marketData.value.downCount)
const upRatio = computed(() =>
  totalStocks.value ? ((marketData.value.upCount / totalStocks.value) * 100).toFixed(2) : '0',
)
const downRatio = computed(() =>
  totalStocks.value ? ((marketData.value.downCount / totalStocks.value) * 100).toFixed(2) : '0',
)

const erbanRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.yiban) return '0.00'
  return ((marketData.value.limitData.erban / marketData.value.yesterdayLimit.yiban) * 100).toFixed(2)
})

const sanbanRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.erban) return '0.00'
  return ((marketData.value.limitData.sanban / marketData.value.yesterdayLimit.erban) * 100).toFixed(2)
})

const sibanPlusRate = computed(() => {
  if (!marketData.value.yesterdayLimit?.sanban) return '0.00'
  return ((marketData.value.limitData.sibanPlus / marketData.value.yesterdayLimit.sanban) * 100).toFixed(2)
})

// 连板柱状图数据
const limitBarData = computed(() => {
  const maxCount = Math.max(
    marketData.value.limitData.yiban,
    marketData.value.limitData.erban,
    marketData.value.limitData.sanban,
    marketData.value.limitData.sibanPlus,
  )

  return [
    {
      label: '一板',
      count: marketData.value.limitData.yiban,
      height: maxCount > 0 ? (marketData.value.limitData.yiban / maxCount) * 60 : 20,
    },
    {
      label: '二板',
      count: marketData.value.limitData.erban,
      height: maxCount > 0 ? (marketData.value.limitData.erban / maxCount) * 60 : 20,
    },
    {
      label: '三板',
      count: marketData.value.limitData.sanban,
      height: maxCount > 0 ? (marketData.value.limitData.sanban / maxCount) * 60 : 20,
    },
    {
      label: '四板+',
      count: marketData.value.limitData.sibanPlus,
      height: maxCount > 0 ? (marketData.value.limitData.sibanPlus / maxCount) * 60 : 20,
    },
  ]
})

// 操作建议
const suggestions = computed(() => {
  const list: string[] = []

  if (currentStage.value) {
    list.push(`${currentStage.value.icon} ${currentStage.value.suggestion}`)
  }

  const promotionRate = breathFactors.value.find((f: FactorItem) => f.id === 'promotionRate')?.score || 0
  const ztCount = marketData.value.ztCount
  const dtCount = marketData.value.dtCount
  const zhabanRate = marketData.value.zhaban?.rate || 0

  if (promotionRate >= 8) {
    list.push('📈 晋级率得分≥8分，接力情绪极强')
  } else if (promotionRate >= 6) {
    list.push('📊 晋级率得分≥6分，接力情绪良好')
  } else if (promotionRate < 4) {
    list.push('📉 晋级率得分不足4分，接力情绪冰点')
  }

  if (ztCount > 80) {
    list.push('📈 涨停家数超过80家，市场接近高潮')
  } else if (ztCount > 50) {
    list.push('📊 涨停家数超过50家，市场情绪较好')
  } else if (ztCount < 20) {
    list.push('📉 涨停家数不足20家，市场接近冰点')
  }

  if (dtCount > 30) {
    list.push('⚠️ 跌停家数超过30家，市场风险较大')
  } else if (dtCount > 10) {
    list.push('📉 跌停家数超过10家，亏钱效应明显')
  }

  if (zhabanRate > 50) {
    list.push('💥 炸板率超过50%，追高风险极大')
  } else if (zhabanRate > 40) {
    list.push('⚠️ 炸板率超过40%，打板需谨慎')
  } else if (zhabanRate < 20) {
    list.push('✅ 炸板率低于20%，封板质量较好')
  }

  return [...new Set(list)].slice(0, 5)
})

// ========== 工具函数 ==========
function getThemeDescription(theme: any): string {
  if (theme.heatScore > 3000) return '🔥 热门题材，多股涨停'
  if (theme.heatScore > 1500) return '🌟 题材发酵，资金关注'
  if (theme.momentum > 20) return '📈 题材升温，趋势向上'
  if (theme.momentum < -20) return '📉 题材降温，注意风险'
  return '⚖️ 题材等待启动信号'
}

function getFactorValueColor(value: number, factorId?: string): string {
  if (!factorId) {
    if (value >= 70) return '#ff4757'
    if (value >= 50) return '#ffa502'
    if (value >= 30) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'ztCount') {
    if (value >= 80) return '#ff4757'
    if (value >= 50) return '#ffa502'
    if (value >= 30) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'dtCount') {
    if (value <= 5) return '#2ed573'
    if (value <= 10) return '#ffa502'
    if (value <= 20) return '#3498db'
    return '#ff4757'
  }

  if (factorId === 'zhabanRate') {
    if (value <= 20) return '#2ed573'
    if (value <= 30) return '#3498db'
    if (value <= 40) return '#ffa502'
    return '#ff4757'
  }

  if (factorId === 'promotionRate' || factorId === 'yesterdayZtAvgChange') {
    if (value >= 40) return '#ff4757'
    if (value >= 30) return '#ffa502'
    if (value >= 20) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'maxContinuousDays') {
    if (value >= 5) return '#ff4757'
    if (value >= 4) return '#ffa502'
    if (value >= 3) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'upDownRatio') {
    if (value >= 2) return '#ff4757'
    if (value >= 1.5) return '#ffa502'
    if (value >= 1) return '#3498db'
    return '#7f8c8d'
  }

  if (factorId === 'volumeRatio') {
    if (value >= 1.2) return '#ff4757'
    if (value >= 1.0) return '#ffa502'
    if (value >= 0.8) return '#3498db'
    return '#7f8c8d'
  }

  if (value >= 70) return '#ff4757'
  if (value >= 50) return '#ffa502'
  if (value >= 30) return '#3498db'
  return '#7f8c8d'
}

function getFactorStateText(factor: FactorItem): string {
  const value = Number(factor.rawValue)
  if (!Number.isFinite(value)) return '缺失'

  switch (factor.id) {
    case 'promotionRate':
      if (value >= 28) return '接力强'
      if (value >= 12) return '接力修复'
      return '接力弱'
    case 'yesterdayZtAvgChange':
      if (value >= 3) return '承接强'
      if (value >= 0) return '承接一般'
      return '承接弱'
    case 'ztCount':
      if (value >= 80) return '进攻强'
      if (value >= 40) return '进攻修复'
      return '进攻弱'
    case 'dtCount':
      if (value <= 5) return '风险低'
      if (value <= 15) return '风险中'
      return '风险高'
    case 'zhabanRate':
      if (value <= 20) return '封板强'
      if (value <= 35) return '分歧中'
      return '分歧高'
    case 'maxContinuousDays':
      if (value >= 5) return '高度强'
      if (value >= 3) return '高度修复'
      return '高度弱'
    case 'upDownRatio':
      if (value >= 1.8) return '宽度强'
      if (value >= 0.8) return '宽度中'
      return '宽度弱'
    case 'volumeRatio':
      if (value >= 1.2) return '放量'
      if (value >= 0.9) return '平量'
      return '缩量'
    case 'tdxEmotion':
      if (value >= 70) return '偏热'
      if (value >= 40) return '中性'
      return '偏冷'
    default:
      return '观察'
  }
}

function getFactorStateClass(factor: FactorItem): string {
  const text = getFactorStateText(factor)
  if (text.includes('强') || text === '放量' || text === '风险低') return 'positive'
  if (text.includes('弱') || text.includes('高') || text === '缩量' || text === '偏冷') return 'negative'
  return 'neutral'
}

function formatRawValue(value: number, unit: string): string {
  if (value === undefined || value === null) return '--'
  if (unit === '%') return value.toFixed(2) + '%'
  if (unit === '家') return Math.round(value) + '家'
  if (unit === '天') return Math.round(value) + '天'
  if (unit === '倍') return value.toFixed(0) + '倍'
  return value.toFixed(2)
}

function selectPlate(plateId: number) {
  selectedPlate.value = selectedPlate.value === plateId ? null : plateId
}

function loadData() {
  // 纯响应式，不需要手动加载
}

function refresh() {
  dragonBreathAnalyzer.refresh()
  loadHotListSentiment()
  loadThemeResearch()
}

function scheduleHotListSentimentLoad() {
  if (hotListSentimentTimer) clearTimeout(hotListSentimentTimer)
  hotListSentimentTimer = setTimeout(() => {
    loadHotListSentiment()
  }, 300)
}

function scheduleHotListSentimentRetry() {
  if (hotListSentimentRetryCount >= 6) return
  hotListSentimentRetryCount += 1
  if (hotListSentimentTimer) clearTimeout(hotListSentimentTimer)
  hotListSentimentTimer = setTimeout(() => {
    loadHotListSentiment()
  }, 800)
}

async function loadHotListSentiment() {
  hotListSentimentLoading.value = true
  hotListSentimentError.value = null

  try {
    const stocks = dataLayer.getStocks()
    if (!Array.isArray(stocks) || stocks.length === 0) {
      hotListSentiment.value = null
      hotListSentimentError.value = '等待当前热榜池数据...'
      scheduleHotListSentimentRetry()
      return
    }

    hotListSentimentRetryCount = 0
    const historicalBundles = await snapshotFacade.listSnapshotFrameBundles({
      type: 'daily',
      allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
      excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
      sort: 'desc',
      limit: 3,
    })

    const today = formatLocalDate(new Date())
    const historical = historicalBundles
      .filter((bundle: SnapshotFrameBundle) => bundle.tradingDate !== today)
      .slice(0, 2)

    hotListSentiment.value = hotListSentimentAnalyzer.analyze({
      stocks,
      yesterday: historical[0] || null,
      dayBefore: historical[1] || null,
      marketData: marketData.value,
    })
  } catch (err: any) {
    console.warn('[DragonBreathPanel] 热榜情绪分析失败:', err)
    hotListSentimentError.value = err?.message || '热榜情绪分析失败'
  } finally {
    hotListSentimentLoading.value = false
  }
}

async function loadThemeResearch() {
  themeResearch.value = await loadThemeResearchExplanation()
}

function exportData() {
  const exportData = {
    exportTime: new Date().toISOString(),
    sentiment: sentiment.value,
    marketData: marketData.value,
    hotListSentiment: hotListSentiment.value,
    factors: breathFactors.value,
    hotPlates: hotPlates.value,
    suggestions: suggestions.value,
  }

  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `龙息数据_${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function formatNumber(num: number): string {
  if (num >= 10000) return (num / 10000).toFixed(2) + '万'
  return num.toString()
}

function formatNullableCount(value?: number | null): string {
  return Number.isFinite(Number(value)) ? String(Number(value)) : '--'
}

function formatAmount(amount?: number): string {
  if (!amount && amount !== 0) return '--'
  const yi = Math.abs(amount) / 100000000
  const sign = amount >= 0 ? '' : '-'
  if (yi >= 10000) return sign + (yi / 10000).toFixed(2) + '万亿'
  return sign + yi.toFixed(0) + '亿'
}

function formatPercent(value?: number | null): string {
  if (value === undefined || value === null) return '--'
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%'
}

function formatPercentValue(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return '--'
  return Number(value).toFixed(0) + '%'
}

function formatShare(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return '--'
  return `${(Number(value) * 100).toFixed(0)}%`
}

function formatTrin(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return '--'
  return Number(value).toFixed(2)
}

function getTrinClass(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return ''
  if (value < 1) return 'up-text'
  if (value > 1.15) return 'down-text'
  return ''
}

function getTrinText(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return '样本不足'
  if (value < 1) return '承接偏强'
  if (value > 1.15) return '承接偏弱'
  return '承接均衡'
}

function formatSignedInt(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return '--'
  const rounded = Math.round(Number(value))
  return `${rounded >= 0 ? '+' : ''}${rounded}`
}

function getDeltaClass(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return ''
  return value > 0 ? 'up-text' : value < 0 ? 'down-text' : ''
}

function formatLocalDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function getChangeClass(value?: number): string {
  if (!value) return ''
  return value > 0 ? 'up-text' : value < 0 ? 'down-text' : ''
}

function getFlowPercent(value: number, total: number): number {
  if (!total || total === 0) return 0
  return Math.min(100, (Math.abs(value) / total) * 100)
}

function formatTime(timestamp: number): string {
  if (!timestamp) return '--:--:--'
  const date = new Date(timestamp)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

// 计算属性：所有指数数据（包含名称和值）
const indexItems = computed(() => {
  const items: Array<{ name: string; value: number; key: string }> = []

  // 从 marketData.indices 中获取
  const indices = marketData.value.indices
  if (indices && typeof indices === 'object') {
    Object.entries(indices).forEach(([key, value]) => {

      // 检查 value 的结构
      if (value && typeof value === 'object' && 'change' in value) {
        const change = (value as any).change
        if (change !== undefined && change !== null) {
          items.push({
            key,
            name: getIndexName(key),
            value: change
          })
        }
      }
    })
  }

  // 添加大票
  const largeCapChange = marketData.value.largeCapChange
  if (largeCapChange !== undefined && largeCapChange !== null) {
    debugLog('添加大票:', largeCapChange)
    items.push({
      key: 'largeCapChange',
      name: '大票',
      value: largeCapChange
    })
  }

  // 添加微盘
  const microCapChange = marketData.value.microCapChange
  if (microCapChange !== undefined && microCapChange !== null) {
    debugLog('添加微盘:', microCapChange)
    items.push({
      key: 'microCapChange',
      name: '微盘',
      value: microCapChange
    })
  }

  debugLog('[DragonBreathPanel] indexItems 结果:', items)
  return items
})

// 指数名称映射
function getIndexName(key: string): string {
  const names: Record<string, string> = {
    sh: '上证指数',
    hs300: '沪深300',
    zz500: '中证500',
    zz1000: '中证1000',
    largeCapChange: '大票',
    microCapChange: '微盘',
    bjs: '北证',
  }
  return names[key] || key
}

// ========== 生命周期 ==========
onMounted(() => {
  debugLog('[DragonBreathPanel] 挂载')

  const unsubBreath = dataLayer.subscribe('analysis.breath', () => { })
  unsubscribeFns.push(unsubBreath)

  const unsubHotThemes = dataLayer.subscribe('theme.hotThemes', () => { })
  unsubscribeFns.push(unsubHotThemes)

  const unsubStocks = dataLayer.subscribe('merged.stocks', () => {
    scheduleHotListSentimentLoad()
  })
  unsubscribeFns.push(unsubStocks)

  loadHotListSentiment()
  loadThemeResearch()
})

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      scheduleHotListSentimentLoad()
      loadThemeResearch()
    }
  },
)

watch(view, (nextView) => {
  if (nextView === 'hotlist') {
    scheduleHotListSentimentLoad()
    loadThemeResearch()
  }
})

onUnmounted(() => {
  debugLog('[DragonBreathPanel] 卸载')
  if (hotListSentimentTimer) clearTimeout(hotListSentimentTimer)
  unsubscribeFns.forEach(fn => fn())
})
</script>
<style scoped>
:root {
  --color-red: #ff4757;
  --color-orange: #ffa502;
  --color-blue: #3498db;
  --color-green: #2ed573;
  --color-purple: #9b59b6;
  --color-gray: #7f8c8d;
  --color-highlight: #ffa502;
}

.breath-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.factor-unit {
  font-size: 10px;
  color: var(--text-secondary);
  margin-left: 2px;
}

/* 空状态 */
.empty-state {
  grid-column: span 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  color: var(--text-secondary);
  font-size: 12px;
  gap: 12px;
  background: var(--bg-secondary);
  border-radius: 12px;
  border: 1px dashed var(--border-color);
}

.empty-icon {
  font-size: 40px;
  opacity: 0.5;
  filter: grayscale(0.5);
}

.breath-panel {
  position: fixed;
  width: 520px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stats-badge {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  font-size: 10px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}

.panel-header h3 {
  margin: 0;
  font-size: 15px;
  color: #ff7f50;
}

.panel-actions {
  display: flex;
  gap: 6px;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-icon:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: #ff7f50;
}

.btn-icon.active {
  color: #2ed573;
  border-color: #2ed573;
}

.btn-icon.loading {
  animation: pulse 1s infinite;
}

.sentiment-stats {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
  background: rgba(0, 0, 0, 0.15);
  padding: 10px 12px;
  border-radius: 8px;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}

.stat-label {
  width: 40px;
  font-size: 11px;
  opacity: 0.8;
  color: white;
}

.stat-value {
  font-weight: bold;
  min-width: 40px;
  text-align: right;
  font-size: 14px;
}

.stat-value.up-text {
  color: #ff4757;
}

.stat-value.down-text {
  color: #2ed573;
}

.stat-sub {
  font-size: 9px;
  opacity: 0.7;
  min-width: 45px;
  text-align: right;
  color: rgba(255, 255, 255, 0.7);
}

/* 情绪卡片 */
.sentiment-card {
  margin: 16px;
  padding: 16px;
  border-radius: 12px;
  color: white;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  background: linear-gradient(135deg, #1e3c5a, #2980b9);
}

.sentiment-card.stage-ice {
  background: linear-gradient(135deg, #1e2b3a, #2c3e50);
}

.sentiment-card.stage-start {
  background: linear-gradient(135deg, #1e3c5a, #2980b9);
}

.sentiment-card.stage-ferment {
  background: linear-gradient(135deg, #b45f06, #f39c12);
}

.sentiment-card.stage-climax {
  background: linear-gradient(135deg, #a52613, #e74c3c);
}

.sentiment-card.stage-retreat {
  background: linear-gradient(135deg, #4a235a, #8e44ad);
}

.sentiment-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.sentiment-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.sentiment-stage-badge {
  width: 60px;
  height: 60px;
  border-radius: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.35);
  transition: box-shadow 0.3s;
  flex-shrink: 0;
}

.stage-badge-icon {
  font-size: 30px;
  line-height: 1;
}

.sentiment-info {
  flex: 1;
}

.sentiment-phase {
  font-size: 18px;
  font-weight: bold;
  margin-bottom: 4px;
}

.sentiment-risk {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.2);
  margin-bottom: 6px;
}

.risk-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
}

.risk-低 .risk-dot {
  background: #2ed573;
}

.risk-中 .risk-dot {
  background: #ffa502;
}

.risk-高 .risk-dot {
  background: #ff4757;
}

.sentiment-suggestion {
  font-size: 12px;
  opacity: 0.9;
}

/* 标签页 */
.panel-tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px 12px;
}

.tab-btn {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 11px;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--color-highlight);
  color: #000;
  font-weight: 500;
}

.panel-content {
  padding: 0 16px 16px;
  max-height: calc(80vh - 240px);
  overflow-y: auto;
}

/* 市场概览 - 6宫格 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.metric-item {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  border: 1px solid var(--border-color);
}

.metric-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.metric-value {
  display: block;
  font-size: 18px;
  font-weight: bold;
  line-height: 1.2;
  margin-bottom: 2px;
}

.metric-percent {
  font-size: 9px;
  color: var(--text-secondary);
}

/* 涨跌比例图 */
.ratio-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.ratio-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.ratio-title {
  font-size: 12px;
  color: var(--text-secondary);
}

.ratio-values {
  display: flex;
  gap: 8px;
  font-size: 11px;
}

.dot {
  opacity: 0.3;
}

.ratio-bar-container {
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.ratio-bar {
  display: flex;
  height: 8px;
  background: var(--bg-primary);
}

.ratio-bar-up {
  height: 100%;
  background: linear-gradient(90deg, #ff4757, #ff6b81);
  transition: width 0.3s;
}

.ratio-bar-down {
  height: 100%;
  background: linear-gradient(90deg, #2ed573, #7bed9f);
  transition: width 0.3s;
}

/* 指数表现 */
.indices-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.section-title {
  font-size: 12px;
  font-weight: bold;
  margin-bottom: 12px;
  color: #ff7f50;
}

.indices-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.index-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 6px;
  text-align: center;
}

.index-name {
  display: block;
  font-size: 9px;
  color: var(--text-secondary);
  margin-bottom: 2px;
}

.index-value {
  font-size: 11px;
  font-weight: bold;
}

/* 热榜情绪 */
.hotlist-view {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mini-loading {
  padding: 24px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

.hotlist-refresh-status {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  padding: 6px 10px;
  border: 1px solid rgba(255, 165, 2, 0.35);
  border-radius: 6px;
  background: rgba(12, 18, 28, 0.92);
  color: var(--color-highlight);
  font-size: 11px;
  font-weight: 600;
  pointer-events: none;
}

.error-state.compact {
  padding: 24px 12px;
}

.hotlist-stage-card {
  border-radius: 10px;
  padding: 14px;
  border: 1px solid var(--border-color);
  background: linear-gradient(135deg, rgba(52, 152, 219, 0.18), rgba(52, 152, 219, 0.06));
}

.hotlist-stage-card.stage-ice {
  background: linear-gradient(135deg, rgba(127, 140, 141, 0.24), rgba(127, 140, 141, 0.08));
}

.hotlist-stage-card.stage-start {
  background: linear-gradient(135deg, rgba(52, 152, 219, 0.24), rgba(52, 152, 219, 0.08));
}

.hotlist-stage-card.stage-ferment {
  background: linear-gradient(135deg, rgba(243, 156, 18, 0.24), rgba(243, 156, 18, 0.08));
}

.hotlist-stage-card.stage-climax {
  background: linear-gradient(135deg, rgba(255, 71, 87, 0.24), rgba(255, 165, 2, 0.1));
}

.hotlist-stage-card.stage-retreat {
  background: linear-gradient(135deg, rgba(155, 89, 182, 0.24), rgba(155, 89, 182, 0.08));
}

.research-hotlist-card {
  border: 1px solid rgba(46, 213, 115, 0.28);
}

.research-status,
.research-lines,
.research-stock-sub,
.research-stock-reason {
  font-size: 11px;
  color: var(--text-secondary);
}

.research-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0 10px;
}

.theme-research-stock-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.theme-research-stock {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px;
}

.theme-research-stock.noise {
  border-color: rgba(255, 165, 2, 0.45);
}

.research-stock-main,
.research-stock-sub {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.research-stock-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.research-stock-score {
  font-size: 13px;
  font-weight: 700;
  color: #2ed573;
}

.research-stock-reason {
  margin-top: 5px;
  line-height: 1.35;
}

.hotlist-stage-main {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.hotlist-stage-label,
.hotlist-confidence {
  font-size: 11px;
  color: var(--text-secondary);
}

.hotlist-stage-value {
  font-size: 20px;
  font-weight: bold;
  color: var(--text-primary);
}

.hotlist-summary {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.hotlist-metrics {
  margin-bottom: 0;
}

.hotlist-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.status-distribution {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px 12px;
}

.status-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px;
  gap: 4px 8px;
  align-items: center;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  grid-column: 1 / -1;
  min-width: 0;
}

.status-label {
  color: var(--text-secondary);
  font-size: 11px;
}

.status-count {
  color: var(--text-primary);
  font-weight: 600;
}

.status-bar {
  height: 5px;
  background: var(--bg-primary);
  border-radius: 999px;
  overflow: hidden;
}

.status-bar-fill {
  height: 100%;
  border-radius: 999px;
}

.status-share {
  font-size: 10px;
  color: var(--text-secondary);
  text-align: right;
}

.status-main {
  background: #ff4757;
}

.status-ignition {
  background: #ffa502;
}

.status-strong {
  background: #3498db;
}

.status-new {
  background: #2dd4bf;
}

.status-crowded {
  background: rgba(255, 255, 255, 0.85);
}

.status-divergence {
  background: #9b59b6;
}

.status-weakening {
  background: #2ed573;
}

.status-insufficient {
  background: #7f8c8d;
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.history-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
}

.history-label {
  display: block;
  color: var(--text-secondary);
  font-size: 10px;
  margin-bottom: 4px;
}

.history-main {
  display: block;
  font-weight: bold;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.history-sub {
  display: block;
  color: var(--text-secondary);
  font-size: 9px;
  line-height: 1.4;
}

.history-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 10px;
}

.history-extra span {
  background: var(--bg-primary);
  border-radius: 999px;
  padding: 3px 8px;
}

.hotlist-evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.evidence-list {
  margin: 0;
  padding-left: 16px;
  color: var(--text-secondary);
  line-height: 1.6;
  font-size: 11px;
}

/* 连板统计卡片 */
.limit-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.limit-stat-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  border: 1px solid var(--border-color);
}

.limit-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.limit-value {
  display: block;
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 2px;
}

.limit-sub {
  font-size: 9px;
  color: var(--text-secondary);
}

/* 连板分布柱状图 */
.limit-distribution {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.limit-bars {
  display: flex;
  justify-content: space-around;
  align-items: flex-end;
  height: 100px;
  padding: 10px 0;
}

.limit-bar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 40px;
}

.limit-bar {
  width: 30px;
  background: linear-gradient(180deg, #ff7f50, #ff4757);
  border-radius: 4px 4px 0 0;
  position: relative;
  margin-bottom: 8px;
  transition: height 0.3s;
}

.limit-bar-value {
  position: absolute;
  top: -16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  color: var(--text-secondary);
}

.limit-bar-label {
  font-size: 10px;
  color: var(--text-secondary);
}

/* 炸板分析 */
.zhaban-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.zhaban-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.zhaban-title {
  font-size: 12px;
  font-weight: bold;
  color: #ff7f50;
}

.zhaban-rate {
  font-size: 16px;
  font-weight: bold;
  color: #ff4757;
}

.zhaban-bar {
  height: 6px;
  background: var(--bg-primary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.zhaban-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #ff7f50, #ff4757);
  transition: width 0.3s;
}

.zhaban-stats {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-secondary);
}

/* 晋级率 */
.promotion-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.promotion-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.promotion-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
}

.promotion-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.promotion-value {
  font-size: 14px;
  font-weight: bold;
  color: var(--color-highlight);
}

/* 资金流向 */
.money-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.money-main {
  display: flex;
  gap: 12px;
}

.money-item {
  flex: 1;
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 10px;
}

.money-item.large {
  flex: 2;
}

.money-label {
  display: block;
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.money-value {
  font-size: 14px;
  font-weight: bold;
}

/* 资金流向图 */
.flow-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
}

.flow-bar {
  display: flex;
  height: 30px;
  background: var(--bg-primary);
  border-radius: 15px;
  overflow: hidden;
}

.flow-bar-in {
  height: 100%;
  background: linear-gradient(90deg, #ff4757, #ff6b81);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  transition: width 0.3s;
}

.flow-bar-out {
  height: 100%;
  background: linear-gradient(90deg, #3498db, #5dade2);
  display: flex;
  align-items: center;
  padding-left: 8px;
  transition: width 0.3s;
}

.flow-label {
  color: white;
  font-size: 10px;
  font-weight: bold;
  white-space: nowrap;
}

/* 超大单资金 */
.super-money-section {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--border-color);
}

.super-money-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.super-money-item {
  background: var(--bg-primary);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.super-money-item .label {
  font-size: 10px;
  color: var(--text-secondary);
}

.super-money-item .value {
  font-size: 12px;
  font-weight: bold;
}

/* 热点板块 */
.plates-view {
  height: 100%;
}

.plates-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plate-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.plate-item:hover {
  background: var(--bg-hover);
  border-color: var(--color-highlight);
}

.plate-item.active {
  border-color: var(--color-highlight);
  background: var(--bg-hover);
}

.plate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.plate-name {
  font-weight: bold;
  color: var(--text-title);
  font-size: 12px;
}

.plate-change {
  font-size: 11px;
  font-weight: bold;
  margin-left: auto;
}

.plate-count {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 10px;
}

.plate-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.plate-stocks {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
}

.plate-stock {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 11px;
}

.plate-stock .stock-code {
  color: var(--text-secondary);
  font-family: monospace;
}

.plate-stock .stock-name {
  flex: 1;
  color: var(--text-primary);
}

.plate-stock .stock-change {
  min-width: 60px;
  text-align: right;
  font-weight: bold;
}

/* 底部 */
.panel-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-header);
  font-size: 9px;
  color: var(--text-secondary);
}

.up-text {
  color: #ff4757 !important;
}

.down-text {
  color: #2ed573 !important;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  gap: 16px;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  gap: 12px;
}

.error-icon {
  font-size: 32px;
}

.retry-btn {
  padding: 8px 16px;
  background: var(--color-highlight);
  border: none;
  border-radius: 20px;
  color: #000;
  font-size: 12px;
  cursor: pointer;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes pulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.5;
  }
}

.dot {
  opacity: 0.5;
}

/* 龙息因子视图 */
.factors-view {
  padding: 4px 0;
}

.factors-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 0 4px;
}

.factors-header h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.factors-header h4::before {
  content: '🌬️';
  font-size: 16px;
}

.factor-count {
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  color: var(--color-highlight);
}

/* 因子卡片网格 */
.factors-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.factor-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.factor-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  border-color: var(--color-highlight);
}

/* 卡片顶部装饰条 */
.factor-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-highlight), transparent);
  opacity: 0.5;
}

.factor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.factor-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-title);
  letter-spacing: 0.3px;
}

.factor-value {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 6px;
  line-height: 1.2;
  font-family: 'JetBrains Mono', monospace;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.factor-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  line-height: 1.4;
  min-height: 28px;
  opacity: 0.8;
}

.factor-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.factor-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 操作建议卡片 */
.suggestions-card {
  background: linear-gradient(135deg, #2a2a2a, #1a1a1a);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  margin-top: 20px;
  position: relative;
  overflow: hidden;
}

.suggestions-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-highlight), #ffd700, transparent);
}

.suggestions-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.suggestions-icon {
  font-size: 20px;
  filter: drop-shadow(0 2px 4px rgba(255, 165, 2, 0.3));
}

.suggestions-title {
  font-size: 14px;
  font-weight: bold;
  color: var(--color-highlight);
}

.suggestions-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-primary);
}

.suggestions-list li {
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.suggestions-list li::marker {
  color: var(--color-highlight);
}

.factor-state {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-primary);
  border-radius: 12px;
  color: var(--text-secondary);
}

.factor-state.positive {
  color: #2ed573;
}

.factor-state.neutral {
  color: #ffa502;
}

.factor-state.negative {
  color: #ff4757;
}

/* 因子提示标签 */
.factor-tip {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  padding: 2px 8px;
  border-radius: 12px;
}


.factor-raw {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
  font-family: monospace;
  margin-bottom: 8px;
}

/* 响应式调整 */
@media (max-width: 480px) {
  .factors-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.factor-desc {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 10px;
  line-height: 1.4;
  min-height: 32px;
}

/* High-contrast trading terminal redesign */
.breath-panel {
  --breath-bg: #070b11;
  --breath-panel: #0d131d;
  --breath-panel-2: #111925;
  --breath-panel-3: #151f2d;
  --breath-line: #334155;
  --breath-line-soft: #223044;
  --breath-text: #f8fafc;
  --breath-strong: #ffffff;
  --breath-muted: #cbd5e1;
  --breath-dim: #94a3b8;
  --breath-accent: #f59e0b;
  --breath-red: #ff4d64;
  --breath-green: #22e58f;
  --breath-blue: #38bdf8;
  width: min(720px, calc(100vw - 32px));
  max-height: min(84vh, 860px);
  background: var(--breath-bg);
  border: 1px solid #3b4658;
  border-radius: 10px;
  box-shadow: 0 28px 70px rgba(0, 0, 0, 0.72);
  color: var(--breath-text);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.breath-panel::before {
  display: none;
}

.panel-header,
.panel-footer,
.sentiment-card,
.panel-tabs,
.panel-content {
  position: relative;
  z-index: 1;
}

.panel-header {
  align-items: center;
  padding: 16px 18px;
  border-bottom: 1px solid var(--breath-line-soft);
  background: #0a0f17;
}

.header-left {
  align-items: flex-start;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.panel-kicker {
  color: var(--breath-accent);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.panel-header h3 {
  color: var(--breath-strong);
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0;
}

.panel-header h3::before {
  content: ' ';
  display: inline-block;
  width: 6px;
  height: 20px;
  margin-right: 10px;
  border-radius: 2px;
  vertical-align: -3px;
  background: var(--breath-accent);
}

.stats-badge {
  gap: 9px;
  padding: 4px 9px;
  background: #111827;
  border-color: var(--breath-line);
  border-radius: 6px;
  color: var(--breath-text);
  font-size: 12px;
  font-weight: 700;
}

.panel-actions {
  gap: 8px;
}

.btn-icon {
  width: auto;
  min-width: 52px;
  height: 34px;
  padding: 0 12px;
  border-color: var(--breath-line);
  border-radius: 6px;
  background: var(--breath-panel-2);
  color: var(--breath-text);
  font-size: 12px;
  font-weight: 700;
  touch-action: manipulation;
}

.btn-icon:hover,
.btn-icon:focus-visible {
  background: #1e293b;
  border-color: var(--breath-accent);
  color: var(--breath-strong);
  outline: 2px solid rgba(245, 158, 11, 0.28);
  outline-offset: 2px;
}

.action-refresh {
  background: var(--breath-accent);
  border-color: var(--breath-accent);
  color: #111827;
}

.close-btn {
  color: var(--breath-muted);
}

.sentiment-card {
  margin: 16px 18px 12px;
  padding: 16px;
  border: 1px solid var(--breath-line);
  border-radius: 8px;
  box-shadow: none;
  background: var(--breath-panel);
}

.sentiment-card.stage-ice {
  border-left: 5px solid #94a3b8;
}

.sentiment-card.stage-start {
  border-left: 5px solid var(--breath-blue);
}

.sentiment-card.stage-ferment {
  border-left: 5px solid var(--breath-accent);
}

.sentiment-card.stage-climax {
  border-left: 5px solid var(--breath-red);
}

.sentiment-card.stage-retreat {
  border-left: 5px solid #a78bfa;
}

.sentiment-main {
  align-items: stretch;
}

.sentiment-left {
  min-width: 0;
}

.sentiment-stage-badge {
  width: 76px;
  height: 76px;
  border: 2px solid var(--breath-accent);
  border-radius: 50%;
  background: conic-gradient(from 220deg, var(--breath-accent), transparent 62%, var(--breath-line) 0);
  position: relative;
}

.stage-badge-icon {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--breath-bg);
}

.stage-badge-icon::after {
  content: '';
  display: block;
  width: 18px;
  height: 18px;
  margin: 17px;
  border-radius: 50%;
  background: currentColor;
  color: var(--breath-accent);
}

.sentiment-label {
  color: var(--breath-muted);
  font-size: 12px;
  font-weight: 700;
}

.sentiment-phase {
  margin-bottom: 8px;
  color: var(--breath-strong);
  font-size: 30px;
  font-weight: 800;
  line-height: 1.1;
}

.sentiment-risk {
  padding: 4px 10px;
  background: #1f2937;
  color: var(--breath-strong);
  font-weight: 800;
}

.sentiment-suggestion {
  max-width: 390px;
  color: var(--breath-muted);
  font-size: 13px;
  line-height: 1.6;
}

.sentiment-stats {
  min-width: 230px;
  gap: 0;
  padding: 0;
  border: 1px solid var(--breath-line-soft);
  border-radius: 8px;
  background: #0a0f17;
}

.stat-row {
  display: grid;
  grid-template-columns: 48px minmax(70px, 1fr) 68px;
  gap: 10px;
  padding: 11px 12px;
  border-bottom: 1px solid var(--breath-line-soft);
}

.stat-row:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.stat-label,
.stat-sub {
  color: var(--breath-muted);
}

.stat-value {
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.panel-tabs {
  gap: 8px;
  padding: 0 18px 14px;
  overflow-x: auto;
}

.tab-btn {
  flex: 0 0 auto;
  min-width: 80px;
  min-height: 36px;
  padding: 8px 12px;
  border: 1px solid var(--breath-line-soft);
  border-radius: 6px;
  background: #0d131d;
  color: var(--breath-muted);
  font-size: 12px;
  font-weight: 800;
}

.tab-btn:hover {
  background: #172033;
  color: var(--breath-text);
}

.tab-btn.active {
  background: var(--breath-accent);
  border-color: var(--breath-accent);
  color: #111827;
  box-shadow: none;
}

.panel-content {
  padding: 0 18px 18px;
  max-height: calc(84vh - 258px);
  scrollbar-color: rgba(255, 179, 92, 0.52) rgba(255, 255, 255, 0.06);
}

.metrics-grid,
.limit-stats-grid,
.super-money-grid,
.indices-grid,
.history-grid,
.theme-research-stock-grid,
.hotlist-evidence-grid,
.factors-grid {
  gap: 10px;
}

.metric-item,
.limit-stat-card,
.index-item,
.promotion-item,
.money-item,
.super-money-item,
.history-item,
.theme-research-stock,
.factor-card {
  border: 1px solid var(--breath-line-soft);
  border-radius: 8px;
  background: var(--breath-panel-2);
  box-shadow: none;
}

.metric-item {
  padding: 13px 14px;
  text-align: left;
}

.metric-primary {
  background: #141f2d;
  border-color: #40516a;
}

.metric-label,
.limit-label,
.money-label,
.history-label,
.index-name,
.promotion-label,
.factor-tip,
.plate-desc,
.research-status,
.research-lines,
.research-stock-sub,
.research-stock-reason,
.history-sub,
.metric-percent,
.limit-sub {
  color: var(--breath-muted);
}

.metric-value,
.limit-value,
.money-value,
.history-main,
.index-value,
.promotion-value,
.factor-raw {
  color: var(--breath-text);
  font-variant-numeric: tabular-nums;
}

.metric-label {
  margin-bottom: 8px;
  color: var(--breath-muted);
  font-size: 12px;
  font-weight: 750;
}

.metric-value {
  margin-bottom: 5px;
  color: var(--breath-strong);
  font-size: 28px;
  font-weight: 800;
}

.metric-percent {
  color: var(--breath-muted);
  font-size: 12px;
  font-weight: 700;
}

.ratio-section,
.indices-section,
.hotlist-section,
.limit-distribution,
.zhaban-section,
.promotion-section,
.money-section,
.flow-section,
.super-money-section,
.suggestions-card {
  border: 1px solid var(--breath-line-soft);
  border-radius: 8px;
  background: var(--breath-panel);
  box-shadow: none;
}

.section-title,
.ratio-title,
.zhaban-title,
.suggestions-title {
  color: var(--breath-accent);
  font-size: 12px;
  font-weight: 850;
}

.ratio-bar-container,
.status-bar,
.zhaban-bar,
.factor-bar {
  background: rgba(2, 6, 23, 0.48);
}

.ratio-bar {
  height: 12px;
}

.ratio-bar-up,
.flow-bar-in {
  background: linear-gradient(90deg, #ff3f5f, #ff8a8f);
}

.ratio-bar-down {
  background: linear-gradient(90deg, #22c55e, #74f2b3);
}

.flow-bar-out {
  background: linear-gradient(90deg, #2563eb, #7dd3fc);
}

.hotlist-stage-card {
  border: 1px solid var(--breath-line-soft);
  border-left: 4px solid var(--breath-blue);
  border-radius: 8px;
  background: var(--breath-panel-2);
}

.hotlist-stage-value {
  color: var(--breath-strong);
  font-size: 22px;
}

.hotlist-summary,
.evidence-list {
  color: var(--breath-text);
}

.research-hotlist-card {
  border-color: #2f6f55;
}

.status-bar {
  height: 7px;
}

.history-extra span,
.factor-tip,
.factor-state,
.plate-count {
  background: #182337;
  border: 1px solid var(--breath-line-soft);
}

.limit-bar {
  width: 32px;
  border-radius: 7px 7px 2px 2px;
  background: linear-gradient(180deg, var(--breath-accent), var(--breath-red));
  box-shadow: 0 8px 18px rgba(255, 93, 108, 0.18);
}

.flow-bar {
  height: 34px;
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.52);
}

.plate-item {
  border: 1px solid var(--breath-line-soft);
  border-radius: 8px;
  background: var(--breath-panel-2);
}

.plate-item:hover,
.plate-item.active {
  background: #182337;
  border-color: var(--breath-accent);
}

.plate-name,
.research-stock-name,
.factor-name {
  color: var(--breath-text);
}

.suggestions-card {
  margin-top: 16px;
  border-color: #5a4524;
  background: #15130f;
}

.suggestions-icon {
  display: none;
}

.suggestions-list li {
  color: var(--breath-text);
}

.loading-state,
.error-state,
.mini-loading,
.empty-state {
  border: 1px solid var(--breath-line-soft);
  border-radius: 8px;
  background: var(--breath-panel-2);
  color: var(--breath-text);
}

.loading-spinner {
  border-color: rgba(148, 163, 184, 0.18);
  border-top-color: var(--breath-accent);
}

.retry-btn {
  border-radius: 8px;
  background: var(--breath-accent);
  color: #111827;
  font-weight: 700;
}

.panel-footer {
  justify-content: space-between;
  padding: 10px 18px 12px;
  border-top-color: var(--breath-line-soft);
  background: #0a0f17;
  color: var(--breath-muted);
  font-size: 11px;
  font-weight: 700;
}

.up-text {
  color: var(--breath-red) !important;
}

.down-text {
  color: var(--breath-green) !important;
}

@media (max-width: 680px) {
  .breath-panel {
    width: min(100vw - 18px, 560px);
    max-height: 88vh;
  }

  .panel-header {
    gap: 12px;
  }

  .sentiment-main,
  .money-main {
    flex-direction: column;
  }

  .sentiment-stats {
    min-width: 0;
  }

  .metrics-grid,
  .indices-grid,
  .history-grid,
  .limit-stats-grid,
  .status-distribution,
  .theme-research-stock-grid,
  .hotlist-evidence-grid,
  .factors-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 430px) {
  .panel-header {
    flex-direction: column;
  }

  .panel-actions {
    align-self: stretch;
  }

  .btn-icon {
    flex: 1;
  }

  .metrics-grid,
  .indices-grid,
  .history-grid,
  .limit-stats-grid,
  .status-distribution,
  .theme-research-stock-grid,
  .hotlist-evidence-grid,
  .factors-grid,
  .promotion-grid,
  .super-money-grid {
    grid-template-columns: 1fr;
  }
}
</style>
