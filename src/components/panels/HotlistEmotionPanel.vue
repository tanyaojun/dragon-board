<!-- src/components/panels/HotlistEmotionPanel.vue -->
<!-- 独立热榜情绪面板（2026-09-24）：与 DragonBreathPanel 完全脱钩，只消费热榜池口径
     （docs/hotlist-emotion-panel/01-口径梳理.md 全量）。展现方式对齐 SectorPanel/SectorDetail
     的界面语言（panel-header / 页签行 / 指标卡 / 表格），配色全部走主题 CSS 变量，随亮暗主题。 -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="hotlist-emotion-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <h3>📊 热榜情绪 <span class="version-badge">v{{ version }}</span></h3>
          <span v-if="dataTimeLabel" class="time-badge" :title="timeBadgeTitle">{{ dataTimeLabel }}</span>
          <span v-if="missingDays.length" class="time-badge warn" :title="missingDaysTitle">
            窗口缺失 {{ missingDays.length }} 日
          </span>
        </div>
        <div class="panel-actions">
          <button class="btn-icon" :class="{ loading }" :disabled="loading" title="刷新" @click="loadAll">
            <span :class="{ 'rotate-animation': loading }">🔄</span>
          </button>
          <button class="btn-icon" title="关闭" @click="close">✕</button>
        </div>
      </div>

      <div class="panel-tabs">
        <div class="tabs-left">
          <button v-for="tab in TABS" :key="tab.key" class="tab-btn" :class="{ active: view === tab.key }"
            @click="view = tab.key">
            {{ tab.icon }} {{ tab.label }}
          </button>
        </div>
      </div>

      <div class="panel-content">
        <div v-if="loading && !doc" class="state-block"><span class="spinner"></span>正在加载热榜情绪…</div>
        <div v-else-if="loadError && !doc" class="state-block error">
          ⚠️ {{ loadError }}
          <button class="retry-btn" @click="loadAll">重试</button>
        </div>
        <div v-else-if="!doc" class="state-block">暂无热榜情绪数据</div>

        <template v-else>
          <!-- ① 热榜概览（含涨停证据三容器 + 证据与风险 + 数据诊断 + EOD 文档明细） -->
          <section v-show="view === 'overview'" class="tab-pane">
            <div class="stage-hero" :class="`stage-tone-${stageTone}`">
              <div class="hero-main">
                <div class="hero-label">市场情绪阶段</div>
                <div class="hero-stage">{{ confirmedStageName }}</div>
                <div class="hero-meta">
                  <span class="risk-chip" :class="`risk-${riskTone}`">{{ doc.riskLevel }}风险</span>
                  <span class="conf-chip">盘面置信 {{ doc.confidence }}%</span>
                  <!-- 相位 chip（2026-09-30 分相位验收）：sentiment_2b 两档，口径源=phase_label_run CANDIDATES -->
                  <span v-if="phaseChip" class="phase-chip" :class="`phase-chip-${phaseChip.kind}`"
                    :title="phaseChip.title">{{ phaseChip.label }}</span>
                  <span v-if="pendingBadge" class="pending-chip"
                    :title="`盘中出现「${pendingBadge.rawStage}」迹象（自 ${pendingBadge.pendingSince} 起），连续 ${pendingBadge.confirmSlots} 槽成立后切换`">
                    情绪波动：现{{ pendingBadge.rawStage }}迹象
                  </span>
                  <span v-if="jevLatestSequenceName" class="jev-chip"
                    :class="{ 'jev-chip-clickable': !!jevHeroNarrative, 'jev-chip-open': jevHeroNarrativeOpen }"
                    :title="jevLatestTitle" @click="toggleJevHeroNarrative">
                    🤖 jev 日内序列 {{ jevLatestSequenceName }}<template
                      v-if="jevLatestProbability != null">（P{{ Math.round(jevLatestProbability * 100) }}%<template
                        v-if="jevHesitant">，犹豫</template>）</template><template
                      v-if="jevLatestFrameName && jevLatestFrameName !== jevLatestSequenceName">｜当前帧 {{ jevLatestFrameName }}</template><template
                      v-if="jevLatestTemperature != null">｜温 {{ jevLatestTemperature }}·挤 {{ jevLatestCrowding ?? '--' }}</template><template
                      v-if="jevHeroNarrative">｜📜 叙事 {{ jevHeroNarrativeOpen ? '▴' : '▾' }}</template>
                  </span>
                </div>
                <!-- jev 叙事全文（2026-09-30 用户裁决：叙事放概览 chip 位置，点击展开） -->
                <div v-if="jevHeroNarrativeOpen && jevHeroNarrative" class="jev-hero-narrative">
                  <div class="jev-hero-narrative-head">📜 {{ jevLatestNarrativeMeta }}</div>
                  <pre class="jev-narrative-text">{{ jevHeroNarrative }}</pre>
                </div>
                <!-- 路线 B 连续情绪分（2026-09-30）：stage 主定义的来源分数，可分解审计 -->
                <div v-if="emotionScoreValue != null" class="hero-score-bar" :title="emotionScoreTooltip">
                  <span class="hero-score-num">{{ emotionScoreValue }}</span>
                  <div class="hero-score-track">
                    <div class="hero-score-fill" :style="{ width: emotionScorePctText }"></div>
                  </div>
                  <span class="hero-score-hint">连续情绪分 0-100</span>
                </div>
                <div v-else-if="doc.emotionScore" class="hero-score-bar hero-score-missing"
                  title="证据全缺，本槽评分不可用（skippedDims 全维，见数据诊断）">
                  <span class="hero-score-hint">情绪分不可用</span>
                </div>
                <!-- 情绪概览双条（2026-10-02 立项）：市场热度计与规则分并读，口径不同不做换算 -->
                <div v-if="sentimentOverviewEod" class="hero-score-bar overview-gauge" :title="overviewGaugeTooltip">
                  <span class="hero-score-num">{{ sentimentOverviewEod.dayTemperature ?? '--' }}</span>
                  <div class="hero-score-track">
                    <div class="hero-score-fill overview-fill" :style="{ width: overviewTemperaturePctText }"></div>
                  </div>
                  <span class="hero-score-hint">市场热度计 0-100</span>
                </div>
                <!-- 概览条被守卫隐藏时透出结构化原因（读口失败/未落库降级/日期错配），不静默消失 -->
                <div v-else-if="overviewHiddenReason" class="hero-score-bar hero-score-missing"
                  :title="overviewHiddenReason">
                  <span class="hero-score-hint">市场热度计不可用：{{ overviewHiddenReason }}</span>
                </div>
                <div v-if="sentimentOverviewEod" class="overview-chips">
                  <span v-if="overviewStageName" class="overview-chip">档位·{{ overviewStageName }}</span>
                  <span v-if="overviewCrowdingName" class="overview-chip" :class="{ 'overview-chip-warn': overviewCrowdingWarn }">拥挤·{{ overviewCrowdingName }}</span>
                  <span v-if="overviewDiffText" class="overview-chip">{{ overviewDiffText }}</span>
                  <span v-if="overviewAnchorHint" class="overview-chip overview-chip-muted">{{ overviewAnchorHint }}</span>
                </div>
                <div class="hero-summary">盘面证据：{{ doc.summary }}</div>
              </div>
            </div>

            <div class="metrics-grid">
              <div v-for="card in primaryCards" :key="card.label" class="metric-card">
                <div class="metric-icon">{{ card.icon }}</div>
                <div class="metric-content">
                  <div class="metric-label">{{ card.label }}</div>
                  <div class="metric-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>

            <div class="funds-grid">
              <div v-for="card in fundCards" :key="card.label" class="fund-card">
                <div class="fund-icon">{{ card.icon }}</div>
                <div class="fund-content">
                  <div class="fund-label">{{ card.label }}</div>
                  <div class="fund-value" :class="card.toneClass">{{ card.value }}</div>
                </div>
              </div>
            </div>

            <div class="stats-grid">
              <div v-for="card in statCards" :key="card.label" class="stat-card">
                <div class="stat-icon">{{ card.icon }}</div>
                <div class="stat-value" :class="card.toneClass">{{ card.value }}</div>
                <div class="stat-label">{{ card.label }}</div>
              </div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('pool', $event)">
              <div class="block-header">
                <span class="block-title">🔥 热榜池涨停交集</span>
                <span class="section-count">{{ intersectionCards.length }}</span>
              </div>
              <div class="grid-4">
                <div v-for="item in intersectionCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('market', $event)">
              <div class="block-header">
                <span class="block-title">🌐 全市场背景（非热榜池口径）</span>
                <span class="section-count">{{ marketCards.length }}</span>
              </div>
              <div class="grid-6">
                <div v-for="item in marketCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
              <div v-if="marketEvidenceNote" class="note-line">{{ marketEvidenceNote }}</div>
            </div>

            <div class="sub-block clickable" @click="openLimitStocks('yesterday', $event)">
              <div class="block-header">
                <span class="block-title">📜 昨日热榜涨停表现</span>
                <span class="section-count">{{ yesterdayLimitCards.length }}</span>
              </div>
              <div class="grid-6">
                <div v-for="item in yesterdayLimitCards" :key="item.label" class="fund-card">
                  <div class="fund-content">
                    <div class="fund-label">{{ item.label }}</div>
                    <div class="fund-value" :class="item.toneClass">{{ item.value }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div class="evidence-columns two">
              <div class="sub-block">
                <div class="block-title up-text">✅ 强证据</div>
                <ul class="evidence-list">
                  <li v-for="signal in doc.signals" :key="signal">{{ signal }}</li>
                  <li v-if="!doc.signals.length" class="empty-row">暂无强证据</li>
                </ul>
              </div>
              <div class="sub-block">
                <div class="block-title down-text">⚠️ 风险提示</div>
                <ul class="evidence-list">
                  <li v-for="warning in doc.warnings" :key="warning">{{ warning }}</li>
                  <li v-if="!doc.warnings.length" class="empty-row">暂无风险提示</li>
                </ul>
              </div>
            </div>
            <div v-if="diagnostics.length" class="diag-block">
              <span class="diag-tag">数据诊断</span>
              <span v-for="item in diagnostics" :key="item" class="diag-item">{{ item }}</span>
            </div>

            <!-- EOD 文档明细（2026-09-25）：文档全字段分组完整展示；未归类字段兜底透出（fail-visible）。
                 标题即折叠按钮（2026-09-25 用户裁决）：默认折叠，点开展开全部明细 -->
            <div class="sub-block doc-full-block">
              <div class="block-header">
                <button class="block-title doc-collapse-btn" :class="{ expanded: !docFullCollapsed }"
                  :title="docFullCollapsed ? '展开文档全部明细' : '折叠文档明细'"
                  @click="docFullCollapsed = !docFullCollapsed">
                  <span class="doc-collapse-arrow">▶</span> EOD 文档明细
                </button>
                <span class="section-count">{{ docFull.groups.length }} 组</span>
              </div>
              <div v-show="!docFullCollapsed" class="doc-full-content">
              <div v-for="group in docFull.groups" :key="group.title" class="doc-group">
                <div class="doc-group-title">{{ group.title }}</div>
                <div class="doc-grid">
                  <div v-for="row in group.rows" :key="group.title + row.label" class="doc-field"
                    :class="{ 'doc-field-wide': row.wide }">
                    <span class="doc-label">{{ row.label }}</span>
                    <span class="doc-value" :class="row.tone">{{ row.value }}</span>
                  </div>
                </div>
              </div>
              <div v-for="table in docFull.tables" :key="table.title" class="doc-group">
                <div class="doc-group-title">{{ table.title }}</div>
                <div class="doc-table-scroll">
                  <table class="doc-table">
                    <thead>
                      <tr>
                        <th class="doc-table-corner">{{ table.rowLabel }}</th>
                        <th v-for="col in docDayColumns" :key="col.label">{{ col.label }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="line in table.rows" :key="line.label">
                        <th class="doc-table-rowhead">{{ line.label }}</th>
                        <td v-for="col in docDayColumns" :key="col.key" class="doc-table-cell"
                          :class="docCellTone(line.m ? line.m[col.key] : null, col.fmt)">
                          {{ fmtDocValue(line.m ? line.m[col.key] : null, col.fmt) }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div v-if="docFull.remaining.length" class="doc-group">
                <div class="doc-group-title">未归类字段（文档结构新增时自动透出）</div>
                <div class="doc-remaining">
                  <div v-for="item in docFull.remaining" :key="item.path" class="doc-remaining-row">
                    <span class="doc-label">{{ item.path }}</span>
                    <span class="doc-value">{{ item.value }}</span>
                  </div>
                </div>
              </div>
              </div>
            </div>
          </section>

          <!-- ② 分层结构（ECharts：多日分层对比，语言同情绪趋势/历史对比；超大单净额全 0 不展示） -->
          <section v-show="view === 'layers'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in LAYER_RANGES" :key="range.key" class="time-btn"
                :class="{ active: layersRange === range.key }" @click="setLayersRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="layer in LAYERS" :key="layer.key" class="indicator-btn"
                :class="{ active: layersLayer === layer.key }" @click="setLayersLayer(layer.key)">
                🧱 {{ layer.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in LAYER_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: layersIndicators.includes(ind.key) }" @click="toggleLayerIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="layersNote" class="note-line">{{ layersNote }}</div>
            <div v-if="!layerPoints.length" class="empty-row">暂无分层数据</div>
            <template v-else>
              <div class="trend-chart" ref="layersChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in layerStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

          <!-- ③b 池换手（分池+出池合并明细，成分股列表风格） -->
          <section v-show="view === 'turnover'" class="tab-pane">
            <div class="sub-block">
              <div class="block-title">🔁 池换手汇总</div>
              <!-- 汇总卡（2026-09-25 用户裁决）：阶段迁移 metric-card 风格，5 列一行 -->
              <div class="turnover-grid">
                <div v-for="card in turnoverSummaryCards" :key="card.label" class="metric-card">
                  <div class="metric-icon">{{ card.icon }}</div>
                  <div class="metric-content">
                    <div class="metric-label">{{ card.label }}</div>
                    <div class="metric-value">{{ card.value }}<span class="metric-unit">只</span></div>
                  </div>
                </div>
              </div>
            </div>
            <div class="to-header">
              <div class="to-filters">
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'all' }"
                  @click="turnoverFilter = 'all'">全部</button>
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'entry' }"
                  @click="turnoverFilter = 'entry'">新入</button>
                <button class="to-filter-btn" :class="{ active: turnoverFilter === 'exit' }"
                  @click="turnoverFilter = 'exit'">剔除</button>
              </div>
              <span class="to-stats">
                新入 {{ entryDetails.length }} · 剔除 {{ exitDetails.length }} · 显示 {{ filteredTurnoverRows.length }} 只
              </span>
            </div>
            <div class="to-table-container" v-if="filteredTurnoverRows.length">
              <table class="to-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>代码</th>
                    <th>名称</th>
                    <th>涨跌幅</th>
                    <th>排名</th>
                    <th>变动</th>
                    <th>变动原因</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in filteredTurnoverRows" :key="`${row.kind}-${row.code}`"
                    :class="{ 'entry-row': row.kind === 'entry' }">
                    <td>{{ i + 1 }}</td>
                    <td><span class="to-code">{{ row.code }}</span></td>
                    <td>{{ resolveStockName(row) }}</td>
                    <td class="num change" :class="row.changePct >= 0 ? 'up-text' : 'down-text'">
                      {{ row.changePct > 0 ? '+' : '' }}{{ (row.changePct || 0).toFixed(2) }}%
                    </td>
                    <td class="num">{{ row.rank }}</td>
                    <td>
                      <span class="to-kind-badge" :class="row.kind === 'entry' ? 'entry' : 'exit'">
                        {{ row.kind === 'entry' ? '新入' : '剔除' }}
                      </span>
                    </td>
                    <td>
                      <span class="to-reason" :title="row.reasonDetail || ''">{{ row.reasonDetail || '--' }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-row">暂无换手明细</div>
          </section>

          <!-- ④ 阶段分布（左环形图 + 右排序明细列表） -->
          <section v-show="view === 'structure'" class="tab-pane">
            <div class="sub-block">
              <div class="block-header">
                <span class="block-title">🧭 全池阶段分布（今日快照池）</span>
                <span class="section-count">{{ formatNullableCount(allLayer?.topN) }}</span>
              </div>
              <div v-if="stagePieData.length" class="stage-layout">
                <div class="stage-pie">
                  <div ref="stageChartRef" class="stage-pie-canvas"></div>
                  <div class="stage-pie-center">
                    <span class="stage-pie-total">{{ stageTotal }}</span>
                    <span class="stage-pie-unit">总样本</span>
                  </div>
                </div>
                <div class="stage-detail">
                  <div v-for="item in stageList" :key="item.key" class="stage-row">
                    <span class="stage-dot" :style="{ background: item.color }"></span>
                    <span class="stage-name">{{ item.name }}</span>
                    <div class="stage-bar"><div class="stage-bar-fill" :style="{ width: item.pctText, background: item.color }"></div></div>
                    <span class="stage-count">{{ item.count }}</span>
                    <span class="stage-pct">{{ item.pctText }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="empty-row">暂无阶段分布数据</div>
            </div>
            <div class="sub-block">
              <div class="block-header">
                <span class="block-title">🔀 阶段迁移（降序前 6）</span>
              </div>
              <div v-if="transitionItems.length" class="transition-grid">
                <div v-for="item in transitionItems" :key="item.key" class="metric-card">
                  <div class="metric-icon">🔀</div>
                  <div class="metric-content">
                    <div class="metric-label">{{ item.text }}</div>
                    <div class="metric-value">{{ item.count }}<span class="metric-unit">次</span></div>
                  </div>
                </div>
              </div>
              <div v-else class="empty-row">暂无迁移数据</div>
            </div>
            <div class="sub-block">
              <div class="block-title">🧾 判定来源</div>
              <div class="chip-wrap">
                <span class="chip">golden 判定 {{ statusSource.displayStatus }}</span>
                <span class="chip">fallback 接管 {{ statusSource.fallback }}</span>
                <span v-for="item in diagnostics" :key="item" class="chip diag">{{ item }}</span>
              </div>
            </div>
          </section>

          <!-- ⑤ 历史对比（ECharts：池流转/留榜/强票表现多日趋势，语言同情绪趋势） -->
          <section v-show="view === 'compare'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in COMPARE_RANGES" :key="range.key" class="time-btn"
                :class="{ active: compareRange === range.key }" @click="setCompareRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in COMPARE_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: compareIndicators.includes(ind.key) }" @click="toggleCompareIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="compareNote" class="note-line">{{ compareNote }}</div>
            <div v-if="!comparePoints.length" class="empty-row">暂无历史对比数据</div>
            <template v-else>
              <div class="trend-chart" ref="compareChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in compareStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

          <!-- ⑥ 情绪趋势（ECharts：SectorDetail 历史趋势图表语言——时间范围 + 阶段铺底 + 指标开关 + 图下统计卡） -->
          <section v-show="view === 'track'" class="tab-pane">
            <div class="time-range-selector">
              <button v-for="range in TIME_RANGES" :key="range.key" class="time-btn"
                :class="{ active: timeRange === range.key }" @click="setTimeRange(range.key)">
                {{ range.label }}
              </button>
            </div>
            <div class="indicator-selector">
              <button v-for="ind in TREND_INDICATORS" :key="ind.key" class="indicator-btn"
                :class="{ active: trendIndicators.includes(ind.key) }" @click="toggleTrendIndicator(ind.key)">
                {{ ind.icon }} {{ ind.label }}
              </button>
            </div>
            <div v-if="trackNote" class="note-line">{{ trackNote }}</div>
            <div v-if="!trendPoints.length" class="empty-row">暂无趋势数据</div>
            <template v-else>
              <div class="trend-chart" ref="trendChartRef"></div>
              <div class="trend-stats-grid">
                <div v-for="card in trendStats" :key="card.label" class="trend-stat-card">
                  <div class="stat-label">{{ card.label }}</div>
                  <div class="stat-value">{{ card.value }}</div>
                  <div class="stat-time">{{ card.sub }}</div>
                </div>
              </div>
            </template>
          </section>

          <!-- ⑦ jev 观察轨道（2026-09-30 独立页签，与情绪趋势并列）：独立 AI 评判，仅供对照论证；
               图表语言同情绪趋势（时间范围 + 指标开关 + 阶段铺底 + 统计卡，温度紫柱/拥挤度黄柱/置信蓝线） -->
          <section v-show="view === 'jev'" class="tab-pane">
            <div v-if="jevDegradedReason" class="note-line">
              jev 轨道不可用：{{ jevDegradedReason }}（独立采集轨道，可能未开启）
            </div>
            <template v-else>
              <div class="note-line">🤖 jev 观察轨道（AI 独立评判 · 仅供对照论证）· 共 {{ jevPoints.length }} 帧</div>
              <div class="time-range-selector">
                <button v-for="range in TIME_RANGES" :key="range.key" class="time-btn"
                  :class="{ active: jevTimeRange === range.key }" @click="setJevTimeRange(range.key)">
                  {{ range.label }}
                </button>
              </div>
              <div class="indicator-selector">
                <button v-for="ind in JEV_INDICATORS" :key="ind.key" class="indicator-btn"
                  :class="{ active: jevIndicators.includes(ind.key) }" @click="toggleJevIndicator(ind.key)">
                  {{ ind.icon }} {{ ind.label }}
                </button>
              </div>
              <div v-if="jevNote" class="note-line">{{ jevNote }}</div>
              <div v-if="!jevPoints.length" class="empty-row">暂无 jev 评判数据（独立采集轨道，可能未开启）</div>
              <template v-else>
                <div class="trend-chart" ref="jevChartRef"></div>
                <!-- 详情卡（2026-09-30 用户裁决：常驻图表下方，默认选最新帧；图表点选联动） -->
                <div v-if="jevDetail" class="jev-detail">
                  <div class="jev-detail-head">
                    <span class="jev-detail-title">🔍 {{ jevDetail.title }}</span>
                    <span class="jev-detail-badges">
                      <span v-if="jevDetail.status === 'degraded'" class="jev-detail-flag">降级</span>
                      <span v-else-if="jevDetail.status === 'no_data'" class="jev-detail-flag">无数据</span>
                      <span v-if="jevDetail.model" class="jev-detail-meta">{{ jevDetail.model }}</span>
                      <span v-if="jevDetail.computedLabel" class="jev-detail-meta">{{ jevDetail.computedLabel }}</span>
                      <span v-if="jevDetail.latencyMs != null" class="jev-detail-meta">{{ jevDetail.latencyMs }}ms</span>
                      <span v-if="jevDetail.tokens" class="jev-detail-meta">{{ jevDetail.tokens }}</span>
                    </span>
                  </div>
                  <div class="jev-detail-grid">
                    <div v-for="choice in jevDetail.choices" :key="choice.key" class="jev-detail-cell">
                      <div class="jev-detail-cell-label">
                        {{ choice.label }}<template v-if="choice.confidence != null"> · 置信 {{ Math.round(choice.confidence * 100) }}%</template>
                      </div>
                      <div class="jev-detail-cell-value" :style="choice.tone ? { color: choice.tone } : undefined">
                        {{ choice.choiceName || '缺失' }}<template v-if="choice.probability != null">（P{{ Math.round(choice.probability * 100) }}%）</template>
                      </div>
                      <div v-if="choice.rows.length" class="jev-prob-rows">
                        <div v-for="row in choice.rows" :key="row.key" class="jev-prob-row">
                          <span class="jev-prob-name">{{ row.name }}</span>
                          <span class="jev-prob-bar-wrap"><span class="jev-prob-bar"
                            :style="{ width: `${row.pct ?? 0}%`, background: row.color }"></span></span>
                          <span class="jev-prob-pct">{{ row.pct === null ? '--' : `${row.pct}%` }}</span>
                        </div>
                      </div>
                    </div>
                    <!-- 分数合并为通栏紧凑条：与概率条格同行会被行高拉伸出大片留白（2026-09-30 修复） -->
                    <div class="jev-detail-cell jev-detail-scores">
                      <div v-for="score in jevDetail.scores" :key="score.label" class="jev-score-item">
                        <span class="jev-detail-cell-label">{{ score.label }}（0-100）</span>
                        <span class="jev-detail-cell-value">{{ score.value ?? '--' }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-if="jevDetail.qualityNotes.length" class="jev-detail-quality">
                    ⚠️ {{ jevDetail.qualityNotes.join('；') }}
                  </div>
                </div>
                <div class="trend-stats-grid">
                  <div v-for="card in jevStats" :key="card.label" class="trend-stat-card">
                    <div class="stat-label">{{ card.label }}</div>
                    <div class="stat-value">{{ card.value }}</div>
                    <div class="stat-time">{{ card.sub }}</div>
                  </div>
                </div>
                <div v-if="jevTimeRange === '1d' && jevEodRow && jevEodRow.dayName" class="jev-eod">
                  📌 日级总体（盘后固定）：{{ jevEodRow.dayName }}<template
                    v-if="jevEodRow.patternName"> · {{ jevEodRow.patternName }}</template><template
                    v-if="jevEodRow.temperature != null"> · 温度 {{ jevEodRow.temperature }}</template><template
                    v-if="jevEodRow.crowding != null"> · 拥挤 {{ jevEodRow.crowding }}</template>
                </div>
              </template>
              <!-- 复核工作台（W1 辅助线 2026-10-01）：jev 对照规则分的分歧/异议/边界人工复核；
                   裁决落库（POST review-ruling）喂 W4 五档映射方向维修订 -->
              <div class="jev-review">
                <div class="jev-review-head">
                  <span class="jev-review-title">🧾 复核工作台</span>
                  <span class="jev-review-legend">A 分歧仲裁 · B 退潮段异议 · C 边界日</span>
                  <span class="jev-review-progress">已裁 {{ reviewRuled }}/{{ reviewTotal }}</span>
                  <button class="time-btn" @click="loadReviewList(true)">刷新</button>
                  <button class="time-btn jev-review-toggle" :class="{ active: hideRuled }"
                    @click="hideRuled = !hideRuled">{{ hideRuled ? '☑ 隐藏已核' : '☐ 隐藏已核' }}</button>
                </div>
                <div v-if="reviewLoading" class="note-line">复核清单加载中…（首次生成需读历史帧，稍慢）</div>
                <div v-else-if="reviewError" class="note-line">⚠️ {{ reviewError }}</div>
                <div v-else-if="!visibleReviewDays.length" class="empty-row">
                  {{ hideRuled && reviewDays.length ? '待复核已清零（已核项已隐藏，关掉开关可查看）' : '暂无复核项' }}
                </div>
                <div v-else class="jev-review-days">
                  <div v-for="day in visibleReviewDays" :key="day.date" class="jev-review-day">
                    <button class="jev-review-day-head" @click="toggleReviewDay(day.date)">
                      <span>{{ openReviewDays.has(day.date) ? '▾' : '▸' }} {{ day.date }}</span>
                      <span class="jev-review-day-meta">{{ day.items.length }} 项 · 待复核 {{ day.pending }}</span>
                    </button>
                    <div v-if="openReviewDays.has(day.date)" class="jev-review-items">
                      <div v-for="item in day.items" :key="item.id" class="jev-review-item">
                        <button class="jev-review-item-head" @click="toggleReviewItem(item.id)">
                          <span class="jev-review-type" :data-type="item.type">{{ item.type }}</span>
                          <span class="jev-review-slot">{{ item.slot }}</span>
                          <span class="jev-review-vs">{{ reviewItemSummary(item) }}</span>
                          <span v-if="item.dayRet != null" class="jev-review-dayret" :class="{ neg: (item.dayRet ?? 0) < 0 }">
                            当日 {{ ((item.dayRet ?? 0) * 100).toFixed(2) }}%
                          </span>
                          <span class="jev-review-status" :data-status="item.ruling.status">{{ reviewStatusText[item.ruling.status] }}</span>
                        </button>
                        <div v-if="openReviewItems.has(item.id)" class="jev-review-item-body">
                          <table v-if="item.type === 'A'" class="jev-review-slots">
                            <thead>
                              <tr><th>槽位</th><th>规则档位</th><th>分数</th><th>Δ斜率</th><th>jev 档位</th><th>置信</th></tr>
                            </thead>
                            <tbody>
                              <tr v-for="row in reviewDaySlotRows(item)" :key="row.slot">
                                <td>{{ row.slot }}</td>
                                <td>{{ row.ruleCn || '--' }}</td>
                                <td>{{ row.score ?? '--' }}</td>
                                <td>{{ row.slope == null ? '--' : (row.slope > 0 ? '+' : '') + row.slope }}</td>
                                <td>{{ row.jevName || '--' }}</td>
                                <td>{{ row.conf == null ? '--' : `${Math.round(row.conf * 100)}%` }}</td>
                              </tr>
                            </tbody>
                          </table>
                          <pre v-if="item.narrativeHead" class="jev-narrative-text jev-review-narrative">{{ item.narrativeHead }}</pre>
                          <div class="jev-review-actions">
                            <button v-for="opt in reviewRulingOptions" :key="opt.status" class="indicator-btn"
                              :class="{ active: item.ruling.status === opt.status }" @click="ruleReviewItem(item, opt.status)">
                              {{ opt.label }}
                            </button>
                          </div>
                          <input v-model="reviewNoteDrafts[item.id]" class="jev-review-note"
                            placeholder="备注（可选，随下一次裁决提交）" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <!-- 韭研公社异动卡（W-jiuyan 2026-10-02）：板块/涨停时间/连板/人工解析，jev 结构证据原料 -->
              <div class="jev-review">
                <div class="jev-review-head">
                  <span class="jev-review-title">📈 韭研异动</span>
                  <span class="jev-review-legend">板块 · 涨停时间 · 连板 · 人工解析（jiuyangongshe.com）</span>
                  <span v-if="jiuyanDoc" class="jev-review-progress">{{ jiuyanDoc.updateKind === 'final' ? '全日' : '午间' }} {{ jiuyanDoc.totalStocks }} 只</span>
                  <button class="time-btn" @click="loadJiuyanAction(jiuyanSelectedDate || undefined)">刷新</button>
                </div>
                <div class="time-range-selector" v-if="jiuyanDates.length">
                  <button v-for="entry in jiuyanDates.slice(0, 12)" :key="entry.date" class="time-btn"
                    :class="{ active: jiuyanSelectedDate === entry.date }" @click="loadJiuyanAction(entry.date)">
                    {{ entry.date.slice(5) }}
                  </button>
                </div>
                <div v-if="jiuyanLoading" class="note-line">韭研数据加载中…</div>
                <div v-else-if="jiuyanError" class="note-line">⚠️ {{ jiuyanError }}</div>
                <div v-else-if="!jiuyanDoc" class="empty-row">该日无韭研异动数据</div>
                <div v-else class="jev-review-days">
                  <div v-for="field in jiuyanDoc.fields" :key="field.name" class="jev-review-day">
                    <button class="jev-review-day-head" @click="toggleJiuyanField(field.name)">
                      <span>{{ openJiuyanFields.has(field.name) ? '▾' : '▸' }} {{ field.name }}</span>
                      <span class="jev-review-day-meta">{{ field.count }} 只</span>
                    </button>
                    <div v-if="openJiuyanFields.has(field.name)" class="jev-review-items">
                      <div v-for="stock in field.stocks" :key="stock.code + (stock.articleId || '')" class="jev-review-item">
                        <button class="jev-review-item-head" @click="toggleJiuyanStock(stock.code + (stock.articleId || ''))">
                          <span class="jev-review-slot">{{ stock.time || '--' }}</span>
                          <span class="jev-review-vs">
                            {{ stock.name }}<template v-if="stock.num">（{{ stock.num }}）</template>
                            <template v-if="stock.price != null"> {{ stock.price }}</template>
                          </span>
                          <span class="jev-review-dayret" v-if="stock.likeCount != null">👍 {{ stock.likeCount }}</span>
                        </button>
                        <div v-if="expandedJiuyanStock === stock.code + (stock.articleId || '')" class="jev-review-item-body">
                          <pre class="jev-narrative-text jev-review-narrative">{{ stock.expound || '（无解析）' }}</pre>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </section>

          <!-- ⑧ 相位验收（2026-09-30 分相位验收体系前端可见化，设计 ranktrend-phase-frontend-design.md） -->
          <section v-show="view === 'phase'" class="tab-pane">
            <div class="phase-note">
              🎯 相位定义 sentiment_2b：连续情绪分 ≥60 进攻相位 / &lt;60 防守相位。<strong>今日相位：{{ todayPhaseText }}</strong>　<strong>建议新仓仓位：{{ todayAdvice }}</strong>
            </div>

            <div v-if="phaseLoading" class="state-block"><span class="spinner"></span>正在加载相位数据…</div>
            <div v-else-if="phaseError" class="state-block error">
              ⚠️ {{ phaseError }}
              <button class="retry-btn" @click="loadPhaseData">重试</button>
            </div>
            <template v-else>
              <div class="phase-chart-card">
                <div class="section-title">相位历史时间线（EOD 情绪分 × 相位着色）</div>
                <div v-if="!phaseHistoryDegraded && phaseHistoryDays.length" ref="phaseChartEl"
                  class="phase-chart"></div>
                <div v-else class="state-block">
                  {{ phaseHistoryDegraded ? `⚠️ 相位历史不可用：${phaseHistoryReason}` : '暂无相位历史数据' }}
                </div>
              </div>

              <div class="phase-chart-card">
                <div class="section-title">
                  🫀 本月至今脉拍（gate off 基线，分带按前日 EOD 分）<template v-if="phasePulseText.value !== '未跑'">——{{ phasePulseText.value }}</template>
                </div>
                <div v-if="phasePulseText.value === '未跑'" class="state-block">
                  phase_pulse --month 当前月（盘后链每个交易日 18:00 自动跑，也可手动）
                </div>
                <div v-else-if="!pulseBandRows.length" class="state-block">脉拍产物无分带数据（旧版产物，重跑即升级）</div>
                <div v-else class="phase-pulse-rows">
                  <div v-for="b in pulseBandRows" :key="b.tag" class="jev-prob-row phase-pulse-row"
                    :title="`${b.tag}：${b.trades} 笔｜累计 ${b.sumPct.toFixed(1)}%`">
                    <span class="jev-prob-name phase-band-name">{{ b.tag }}
                      <span v-if="b.weak" class="phase-band-badge">弱势</span></span>
                    <span class="jev-prob-bar-wrap phase-band-track"><span class="jev-prob-bar"
                      :style="{ width: `${b.barPct}%`, background: b.color }"></span></span>
                    <span class="phase-band-val" :style="{ color: b.color }">{{ b.avgText }}</span>
                    <span class="phase-band-trades">{{ b.trades }} 笔</span>
                  </div>
                </div>
                <div v-if="phasePulseAbLine" class="phase-pulse-ab">{{ phasePulseAbLine }}</div>
                <div v-if="phasePulseChallengerRows.length" style="margin-top: 6px;">
                  <div class="section-title">挑战者臂（预算 ≤2，章程 §5.6）</div>
                  <div v-for="c in phasePulseChallengerRows" :key="c.name" class="phase-pulse-ab">
                    <template v-if="c.degraded">⚠️ {{ c.name }}：{{ c.reason }}</template>
                    <template v-else>{{ c.name }}：{{ c.tradeCount ?? '--' }} 笔 {{ c.sumPct.toFixed(1) }}%<template
                      v-if="c.rebalance !== null">｜调仓清仓 {{ c.rebalance }} 笔</template></template>
                  </div>
                </div>

                <div v-if="phasePulseAccRows.length" class="phase-pulse-acc">
                  <div class="section-title">分带累积（C6 证据，每月末自动入档）</div>
                  <table class="phase-months-table">
                    <thead>
                      <tr><th>月份</th><th>冷10-40</th><th>弱势40-60</th><th>强60-80</th><th>总笔数</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in phasePulseAccRows" :key="row.month">
                        <td>{{ row.month }}</td>
                        <td v-for="c in row.cells" :key="c.tag"
                          :style="{ color: c.avgPct == null ? '' : c.avgPct >= 0 ? '#ff4757' : '#2ed573' }">
                          {{ c.avgPct == null ? '--' : `${c.avgPct >= 0 ? '+' : ''}${c.avgPct}%/笔` }}
                          <span class="phase-band-trades">（{{ c.trades }} 笔）</span>
                        </td>
                        <td>{{ row.tradeCount }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </template>
          </section>

        </template>
      </div>

      <!-- 涨停池明细面板（Teleport 自身挂 body，层级 10007 高于本面板） -->
      <HotlistLimitStocksPanel v-if="limitStocksDetail" :visible="limitStocksDetail.visible"
        :initial-kind="limitStocksDetail.kind" :summary="doc?.metrics?.limitEvidence ?? null"
        :trigger-rect="limitStocksDetail.rect" @close="limitStocksDetail = null" />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { dataLayer } from '@/services/DataLayer'
import {
  fetchHotlistSentimentSeries,
  fetchHotlistSentimentSlots,
  type HotlistLimitStockKind,
  type HotlistSentimentMissingDay,
} from '@/services/hotlist/hotlistSentimentApi'
import {
  fetchHotlistJevRange,
  fetchHotlistJevSeries,
  fetchHotlistSentimentOverview,
  fetchJiuyanAction,
  fetchJevReviewList,
  JEV_CROWDING_LAYERS,
  JEV_CROWDING_NAMES,
  JEV_CROWDING_WARN_LAYERS,
  JEV_PATTERN_NAMES,
  JEV_PATTERN_ORDER,
  JEV_STAGE_NAMES,
  JEV_STAGE_ORDER,
  jevChoiceConfidence,
  jevChoiceName,
  jevChoiceProbability,
  jevCrowdingName,
  jevCrowdingProbability,
  jevScore,
  postJevReviewRuling,
} from '@/services/hotlist/hotlistJevApi'
import type {
  HotlistJevDayEntry,
  HotlistJevDoc,
  HotlistJevMissingDay,
  JiuyanActionDoc,
  JevReviewDay,
  JevReviewItem,
  JevReviewRulingStatus,
  HotlistSentimentOverviewResult,
} from '@/types/hotlistJev'
import { fetchPhaseHistory, fetchPhaseMonitorBoard } from '@/services/hotlist/phaseApi'
import type {
  PhaseHistoryDay,
  PhaseNorthstarDoc,
  PhasePulseDoc,
} from '@/types/phaseMonitor'
import HotlistLimitStocksPanel from '@/components/panels/HotlistLimitStocksPanel.vue'
import {
  HOT_LIST_STAGE_LABELS,
  type HotListSentimentDayDoc,
  type HotListStageKey,
} from '@/types/hotlistSentiment'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const TABS = [
  { key: 'overview', label: '热榜概览', icon: '📊' },
  { key: 'layers', label: '分层结构', icon: '🧱' },
  { key: 'turnover', label: '池换手', icon: '🔁' },
  { key: 'structure', label: '阶段分布', icon: '🧭' },
  { key: 'compare', label: '历史对比', icon: '🗓️' },
  { key: 'track', label: '情绪趋势', icon: '📈' },
  { key: 'jev', label: 'jev 观察轨道', icon: '🤖' },
  { key: 'phase', label: '相位验收', icon: '🎯' },
] as const
type ViewKey = (typeof TABS)[number]['key']

const ENTRY_REASON_TEXT: Record<string, string> = {
  limit_up: '涨停入选', strong_money: '强资入选', rank_surge: '排名跃升', new_high_volume: '放量新高',
}
const EXIT_REASON_TEXT: Record<string, string> = {
  rank_out_of_range: '跌出榜单', weakening: '转弱', limit_down: '跌停',
}
// 阶段冷热两档（交易者语感）：分歧小标据此给「短暂走高/短暂回落/盘中波动」
const STAGE_HEAT: Record<string, number> = { 冰点: 0, 退潮: 0, 启动: 1, 发酵: 2, 高潮: 3 }

const view = ref<ViewKey>('overview')
const loading = ref(false)
const loadError = ref<string | null>(null)
const doc = ref<HotListSentimentDayDoc | null>(null)
const slots = ref<HotListSentimentDayDoc[]>([])
const slotsTradingDate = ref('')
const slotsDegradedReason = ref<string | null>(null)
const missingDays = ref<HotlistSentimentMissingDay[]>([])
// ---------- jev 观察轨道（独立 AI 评判，只读对照；缺失/降级如实展示，不进信号） ----------
const jevSlots = ref<HotlistJevDoc[]>([])
const jevEod = ref<HotlistJevDoc | null>(null)
const sentimentOverview = ref<HotlistSentimentOverviewResult | null>(null)
const jevDegradedReason = ref<string | null>(null)
const jevSeriesDate = ref('')

// ---------- 复核工作台（W1 辅助线 2026-10-01）：jev 对照规则分的人工复核面，裁决落库喂 W4 ----------
const reviewDays = ref<JevReviewDay[]>([])
const reviewTotal = ref(0)
const reviewRuled = ref(0)
const reviewLoading = ref(false)
const reviewError = ref<string | null>(null)
const reviewLoadedOnce = ref(false)
const openReviewDays = ref<Set<string>>(new Set())
const openReviewItems = ref<Set<string>>(new Set())
const reviewNoteDrafts = ref<Record<string, string>>({})
// 隐藏已核（2026-10-01 用户指令）：默认开，裁完一条自动消失；关掉可回看全部
const hideRuled = ref(true)

/** 按开关过滤后的日列表：隐藏非 pending 项，清空的日整日隐藏 */
const visibleReviewDays = computed(() => {
  if (!hideRuled.value) return reviewDays.value
  return reviewDays.value
    .map(day => {
      const items = day.items.filter(item => item.ruling.status === 'pending')
      return { ...day, items, pending: items.length }
    })
    .filter(day => day.items.length > 0)
})

const reviewStatusText: Record<JevReviewRulingStatus, string> = {
  pending: '未裁', rule_right: '规则对', jev_right: 'jev 对', ambiguous: '模糊', consistent: '一致',
}
const reviewRulingOptions: Array<{ status: JevReviewRulingStatus; label: string }> = [
  { status: 'rule_right', label: '✅ 规则对' },
  { status: 'jev_right', label: '✅ jev 对' },
  { status: 'ambiguous', label: '❓ 模糊' },
  { status: 'pending', label: '↩️ 重置' },
]

function toggleReviewDay(date: string): void {
  const next = new Set(openReviewDays.value)
  if (next.has(date)) next.delete(date)
  else next.add(date)
  openReviewDays.value = next
}

function toggleReviewItem(id: string): void {
  const next = new Set(openReviewItems.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  openReviewItems.value = next
}

/** 摘要行：A=全天档位混合（日级仲裁）；B/C=规则侧（档位/分数/斜率 或 边界分）vs jev 侧 */
function reviewItemSummary(item: JevReviewItem): string {
  if (item.type === 'A') {
    return `全天：规则 ${item.rule.stageSummary || '--'} vs jev ${item.jev.stageSummary || '--'}`
  }
  if (item.type === 'C') {
    return `规则分 ${item.rule.score ?? '--'}（贴 ${item.rule.nearEdge ?? '?'} 边界）vs jev 日级 ${
      item.jev.dayStage ? (JEV_STAGE_NAMES[item.jev.dayStage] ?? item.jev.dayStage) : '--'
    }`
  }
  const slope = item.rule.slope != null ? ` Δ${item.rule.slope > 0 ? '+' : ''}${item.rule.slope}` : ''
  const conf = item.jev.confidence != null ? ` P${Math.round(item.jev.confidence * 100)}%` : ''
  const temp = item.jev.temperature != null ? ` 温${Math.round(item.jev.temperature)}` : ''
  return `规则 ${item.rule.stageCn || item.rule.stage || '--'} ${item.rule.score ?? '--'}${slope} vs jev ${
    item.jev.stage ? (JEV_STAGE_NAMES[item.jev.stage] ?? item.jev.stage) : '--'
  }${conf}${temp}`
}

/** A 类日级展开：全天槽位对照表（规则分数/斜率 vs jev 档位/置信） */
function reviewDaySlotRows(item: JevReviewItem): Array<{
  slot: string; ruleCn?: string | null; score?: number | null; slope?: number | null;
  jevName?: string | null; conf?: number | null;
}> {
  const jevBySlot = new Map((item.jev.slots ?? []).map(row => [row.slot, row]))
  return (item.rule.slots ?? []).map(row => {
    const j = jevBySlot.get(row.slot)
    return {
      slot: row.slot,
      ruleCn: row.stageCn,
      score: row.score,
      slope: row.slope,
      jevName: j?.stage ? (JEV_STAGE_NAMES[j.stage] ?? j.stage) : null,
      conf: j?.confidence ?? null,
    }
  })
}

async function loadReviewList(force = false): Promise<void> {
  if (reviewLoading.value) return
  if (reviewLoadedOnce.value && !force) return
  reviewLoading.value = true
  reviewError.value = null
  const result = await fetchJevReviewList()
  reviewLoading.value = false
  if (result.degraded) {
    reviewError.value = result.reason || '复核清单不可用'
    return
  }
  reviewDays.value = result.days
  reviewTotal.value = result.total
  reviewRuled.value = result.ruled
  reviewLoadedOnce.value = true
  if (openReviewDays.value.size === 0) {
    const firstPending = result.days.find(day => day.pending > 0)
    if (firstPending) openReviewDays.value = new Set([firstPending.date])
  }
}

async function ruleReviewItem(item: JevReviewItem, status: JevReviewRulingStatus): Promise<void> {
  const note = reviewNoteDrafts.value[item.id] ?? ''
  const ok = await postJevReviewRuling(item, status, note)
  if (!ok) {
    reviewError.value = `裁决写入失败：${item.id}（可重试）`
    return
  }
  reviewError.value = null
  item.ruling = { status, note, ruledAt: new Date().toISOString() }
  const day = reviewDays.value.find(d => d.date === item.date)
  if (day) day.pending = day.items.filter(i => i.ruling.status === 'pending').length
  reviewRuled.value = reviewDays.value.reduce(
    (acc, d) => acc + d.items.filter(i => i.ruling.status !== 'pending').length, 0)
}

// ---------- 韭研公社异动卡（W-jiuyan 2026-10-02）：板块/涨停时间/连板/人工解析，纯读 ----------
const jiuyanDoc = ref<JiuyanActionDoc | null>(null)
const jiuyanDates = ref<Array<{ date: string; kinds: string[] }>>([])
const jiuyanSelectedDate = ref('')
const jiuyanLoading = ref(false)
const jiuyanError = ref<string | null>(null)
const openJiuyanFields = ref<Set<string>>(new Set())
const expandedJiuyanStock = ref<string | null>(null)

function toggleJiuyanField(name: string): void {
  const next = new Set(openJiuyanFields.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  openJiuyanFields.value = next
}

function toggleJiuyanStock(key: string): void {
  expandedJiuyanStock.value = expandedJiuyanStock.value === key ? null : key
}

async function loadJiuyanAction(date?: string): Promise<void> {
  if (jiuyanLoading.value) return
  jiuyanLoading.value = true
  jiuyanError.value = null
  const result = await fetchJiuyanAction(date)
  jiuyanLoading.value = false
  if (result.degraded) {
    jiuyanError.value = result.reason || '韭研数据不可用'
    if (result.dates.length) jiuyanDates.value = [...result.dates].reverse()
    return
  }
  jiuyanDates.value = [...result.dates].reverse()
  jiuyanDoc.value = result.doc
  jiuyanSelectedDate.value = result.doc?.tradingDate || date || ''
  if (result.doc && openJiuyanFields.value.size === 0 && result.doc.fields.length) {
    const biggest = [...result.doc.fields].sort((a, b) => b.count - a.count)[0]
    if (biggest) openJiuyanFields.value = new Set([biggest.name])
  }
}

const version = '6.0.0'

function close() {
  emit('close')
}

// ---------- 涨停池明细面板（热榜概览三容器点击进入，SectorPanel→SectorDetail 交互语言） ----------
const limitStocksDetail = ref<{ visible: boolean; kind: HotlistLimitStockKind; rect: DOMRect | null } | null>(null)

function openLimitStocks(kind: HotlistLimitStockKind, event?: MouseEvent) {
  const rect = event ? (event.currentTarget as HTMLElement).getBoundingClientRect() : null
  limitStocksDetail.value = { visible: true, kind, rect }
}

const panelStyle = computed(() => {
  const rect = props.triggerRect
  // 无触发源（导航标签打开）时落到视口内默认位置，与 usePanel 的 fallback 一致
  if (!rect) return { top: '100px', right: '20px' }
  const width = 960
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2))
  return { left: `${left}px`, top: `${Math.min(rect.bottom + 8, window.innerHeight - 520)}px` }
})

async function loadAll() {
  if (loading.value) return
  loading.value = true
  loadError.value = null
  try {
    const [series, slotResult, jevResult, overviewResult] = await Promise.all([
      fetchHotlistSentimentSeries(3),
      fetchHotlistSentimentSlots().catch((err) => ({
        items: [], tradingDate: '', degraded: true, reason: err?.message || '加载失败',
      })),
      fetchHotlistJevSeries().catch(() => ({
        date: '', slots: [], eod: null, degraded: true, reason: '加载失败',
      })),
      fetchHotlistSentimentOverview().catch(() => ({
        ok: false, date: null, jev: null, rule: null, degraded: true, reason: '加载失败',
      })),
    ])
    if (series.degraded || !series.items.length) {
      doc.value = null
      loadError.value = series.reason || '热榜情绪数据暂不可用'
      missingDays.value = series.missingDays
      slots.value = []
      return
    }
    missingDays.value = series.missingDays
    const latestDoc = series.items[series.items.length - 1]
    doc.value = latestDoc
    // 仅在缓存仍是最初 3 日窗口时覆盖：用户已切更长档位（loaded>3）时覆盖会让
    // 长窗口静默降级（seriesDaysLoaded 只增不减），此时保留长窗口缓存不动
    if (seriesDaysLoaded.value <= 3) {
      seriesDocs.value = series.items
      seriesDaysLoaded.value = 3
      seriesMissingDays.value = series.missingDays
    }
    slots.value = slotResult.items
    slotsTradingDate.value = slotResult.tradingDate
    slotsDegradedReason.value = slotResult.degraded ? slotResult.reason : null
    jevSlots.value = jevResult.slots
    jevEod.value = jevResult.eod
    jevDegradedReason.value = jevResult.degraded ? jevResult.reason : null
    jevSeriesDate.value = jevResult.date
    // 概览与 hero 规则分对齐同一交易日：无参取最新，日期不一致（概览领先/当日未落库）时
    // 按 doc 交易日补拉一次；仍缺则守卫隐藏、占位条透出原因
    let alignedOverview = overviewResult
    if (alignedOverview.ok && latestDoc.tradingDate && alignedOverview.date !== latestDoc.tradingDate) {
      alignedOverview = await fetchHotlistSentimentOverview(latestDoc.tradingDate)
    }
    sentimentOverview.value = alignedOverview
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '加载失败'
    doc.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible && !doc.value) loadAll()
  },
  { immediate: true },
)

// ---------- jev 观察轨道展示投影（缺失返回 null，不伪造档位/0 分） ----------
const jevLatest = computed(() =>
  jevSlots.value.length ? jevSlots.value[jevSlots.value.length - 1] : null)
const jevLatestSequenceName = computed(() =>
  jevLatest.value ? jevChoiceName(jevLatest.value, 'sequence_stage') : null)
const jevLatestFrameName = computed(() =>
  jevLatest.value ? jevChoiceName(jevLatest.value, 'frame_stage') : null)
const jevLatestProbability = computed(() =>
  jevLatest.value ? jevChoiceProbability(jevLatest.value, 'sequence_stage') : null)
// jev 犹豫度：top 概率 < 0.6 视为低置信档位，显式透传给论证者（避免把低置信判定当强信号）
const jevHesitant = computed(() =>
  jevLatestProbability.value != null && jevLatestProbability.value < 0.6)
const jevLatestTemperature = computed(() =>
  jevLatest.value ? jevScore(jevLatest.value, 'temperature') : null)
// 拥挤=离散归层 choice（V1 连续分退役），展示中文归层名
const jevLatestCrowding = computed(() =>
  jevLatest.value ? jevCrowdingName(jevLatest.value, 'crowding') : null)
const jevLatestTitle = computed(() => {
  const slot = jevLatest.value
  if (!slot) return ''
  const parts = [`槽位 ${slot.slotTime || '--'}`]
  if (slot.model) parts.push(`模型 ${slot.model}`)
  if (slot.status === 'degraded') parts.push(`降级：${slot.errorCode || ''} ${slot.errorDetail || ''}`)
  return parts.join(' · ')
})
// ---------- jev 叙事（2026-09-30 用户裁决：叙事全文放概览 chip 位置，点击展开） ----------
const jevHeroNarrativeOpen = ref(false)
const jevHeroNarrative = computed(() => jevLatest.value?.narrativeRaw || '')
const jevLatestNarrativeMeta = computed(() => {
  const slot = jevLatest.value
  if (!slot) return ''
  const parts = [`${slot.tradingDate || jevSeriesDate.value || ''} ${slot.slotTime || ''} 帧`.trim()]
  if (slot.model) parts.push(`模型 ${slot.model}`)
  const narrative = slot.narrativeRaw || ''
  if (narrative) parts.push(`全文 ${narrative.length} 字`)
  const degraded = slot.quality?.degradedSources ?? []
  if (degraded.length) parts.push(`⚠️ 缺失：${degraded.join('；')}`)
  return parts.join(' · ')
})
function toggleJevHeroNarrative() {
  if (!jevHeroNarrative.value) return
  jevHeroNarrativeOpen.value = !jevHeroNarrativeOpen.value
}
const jevEodRow = computed(() => {
  if (!jevEod.value) return null
  return {
    dayName: jevChoiceName(jevEod.value, 'day_stage'),
    patternName: jevChoiceName(jevEod.value, 'day_pattern'),
    temperature: jevScore(jevEod.value, 'day_temperature'),
    crowding: jevCrowdingName(jevEod.value, 'day_crowding'),
  }
})

// ---------- 基础格式化（fail-visible：缺失显示 --，不伪造 0） ----------
function formatNullableCount(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : '--'
}
function formatShare(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '--'
}
function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}
function formatTrin(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--'
}
function formatMoney(value?: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return String(Math.round(value))
}

// ---------- 顶层口径 ----------
const confirmedStageName = computed(() => doc.value?.stage ?? '--')
const stageTone = computed(() => {
  const heat = STAGE_HEAT[doc.value?.stage ?? ''] ?? 1
  return heat >= 2 ? 'hot' : heat >= 1 ? 'warm' : 'cold'
})
// ---------- 路线 B 连续情绪分（emotion-score-design v3 §3.2）----------
const emotionScoreValue = computed(() => {
  const score = doc.value?.emotionScore?.score
  return typeof score === 'number' && Number.isFinite(score) ? score : null
})
const emotionScorePctText = computed(
  () => `${Math.max(0, Math.min(100, emotionScoreValue.value ?? 0))}%`,
)
const sentimentOverviewEod = computed(() => {
  const result = sentimentOverview.value
  if (!result?.ok || !result.jev || result.jev.status !== 'ok') return null
  // 日期一致性守卫：概览 EOD 与 hero 规则分必须同一天，错配时整条隐藏（不并排错日数据）
  if (!doc.value?.tradingDate || result.date !== doc.value.tradingDate) return null
  return result.jev
})
// 概览条被守卫隐藏时的原因透出（fail-visible）：各分支与 sentimentOverviewEod 的隐藏条件一一对应
const overviewHiddenReason = computed(() => {
  const result = sentimentOverview.value
  if (!result || sentimentOverviewEod.value) return null
  if (!doc.value?.tradingDate) return '规则分文档缺交易日，无法对齐概览日期'
  if (!result.ok) return result.reason || '读口不可用'
  if (!result.jev || result.jev.status !== 'ok') return result.reason || '概览 EOD 缺失或降级'
  if (result.date !== doc.value.tradingDate) return `概览最新日期 ${result.date || '未知'} 与规则分日期不一致`
  return null
})
const overviewTemperaturePctText = computed(
  () => `${Math.max(0, Math.min(100, sentimentOverviewEod.value?.dayTemperature ?? 0))}%`,
)
const overviewStageName = computed(() => {
  const stage = sentimentOverviewEod.value?.dayStage
  return stage ? JEV_STAGE_NAMES[stage] ?? stage : null
})
const overviewCrowdingName = computed(() => {
  const layer = sentimentOverviewEod.value?.dayCrowding
  return layer ? JEV_CROWDING_NAMES[layer] ?? layer : null
})
const overviewCrowdingWarn = computed(() =>
  JEV_CROWDING_WARN_LAYERS.has(sentimentOverviewEod.value?.dayCrowding ?? ''),
)
const overviewDiffText = computed(() => {
  const temp = sentimentOverviewEod.value?.dayTemperature
  const ruleScore = sentimentOverview.value?.rule?.score
  if (temp == null || ruleScore == null) return null
  const delta = Math.round(temp - ruleScore)
  return delta === 0 ? '与规则分持平' : `较规则分 ${delta > 0 ? '+' : ''}${delta}`
})
const overviewAnchorHint = computed(() => {
  const range = sentimentOverview.value?.jev?.historyAnchorRange
  return range ? `锚 ${range.split('，')[0] ?? range}` : null
})
const overviewGaugeTooltip = computed(() => {
  if (!sentimentOverviewEod.value) return ''
  const parts = ['市场热度计：全市场涨停/连板/炸板锚定近 20 交易日分位（热读=广度高）',
                 '与左侧连续情绪分（池内质量计，风险维度权重高）口径不同，双表并读不做换算']
  const anchor = sentimentOverview.value?.jev?.historyAnchorRange
  if (anchor) parts.push(`锚窗口：${anchor}`)
  return parts.join('；')
})
const emotionScoreTooltip = computed(() => {
  const emotion = doc.value?.emotionScore
  if (!emotion) return ''
  const parts = Object.entries(emotion.dims ?? {}).map(([name, detail]) => `${name} ${detail.sub}`)
  const skipped = (emotion.skippedDims ?? []).length ? `；缺失跳过：${(emotion.skippedDims ?? []).join('、')}` : ''
  const slope = emotion.slope != null ? `；较上一有效槽 ${emotion.slope > 0 ? '+' : ''}${emotion.slope}` : ''
  return `情绪分构成（可分解审计）：${parts.join('、')}${skipped}${slope}`
})
const riskTone = computed(() => (doc.value?.riskLevel === '高' ? 'high' : doc.value?.riskLevel === '低' ? 'low' : 'mid'))
const pendingBadge = computed(() => {
  const state = doc.value?.stageConfirmState
  if (!state?.pending || !doc.value?.rawStage) return null
  return {
    rawStage: doc.value.rawStage,
    pendingSince: state.pendingSince || '--',
    confirmSlots: state.confirmSlots,
  }
})
const diagnostics = computed(() => doc.value?.diagnostics ?? [])
const statusSource = computed(() => doc.value?.metrics.statusSourceCounts ?? { displayStatus: 0, fallback: 0 })
const turnover = computed(
  () => doc.value?.turnover ?? { previousPoolSize: 0, currentPoolSize: 0, retainedFromYesterday: 0, newEntries: [], eliminated: [], newEntryDetails: [], eliminatedDetails: [] },
)
// 名称兜底（2026-09-24）：采集行 name 可能为 "-" 占位，用行情列表名称回填展示
const stockNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const stock of dataLayer.getStocks()) {
    const name = stock.name?.trim() ?? ''
    if (stock.code && name && name !== '-') map.set(stock.code, name)
  }
  return map
})
function resolveStockName(row: { code: string; name?: string | null }): string {
  const raw = (row.name || '').trim()
  if (raw && raw !== '-') return raw
  return stockNameMap.value.get(row.code) || raw || '-'
}
const entryDetails = computed(() => turnover.value.newEntryDetails ?? [])
const exitDetails = computed(() => turnover.value.eliminatedDetails ?? [])
const eliminatedCount = computed(() => turnover.value.eliminated?.length ?? 0)

// 池换手汇总卡（2026-09-25：chips 改阶段迁移 metric-card 风格，数值来源与原 chips 一致）
const turnoverSummaryCards = computed(() => [
  { icon: '📤', label: '昨池', value: formatNullableCount(turnover.value.previousPoolSize) },
  { icon: '📥', label: '今池', value: formatNullableCount(turnover.value.currentPoolSize) },
  { icon: '🔁', label: '留存', value: formatNullableCount(turnover.value.retainedFromYesterday) },
  { icon: '🆕', label: '新入', value: formatNullableCount(doc.value?.metrics.comparison.newTop100Count ?? null) },
  { icon: '🚪', label: '剔除', value: formatNullableCount(eliminatedCount.value) },
])

// 池换手明细（分池+出池合并单表）：新入在前按涨幅降序，剔除在后按排名升序
const turnoverFilter = ref<'all' | 'entry' | 'exit'>('all')
const mergedTurnoverRows = computed(() => {
  const entries = entryDetails.value
    .slice()
    .sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0))
    .map((row) => ({ ...row, kind: 'entry' as const, reasonDetail: ENTRY_REASON_TEXT[row.entryReason] || row.entryReason }))
  const exits = exitDetails.value
    .slice()
    .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
    .map((row) => ({ ...row, kind: 'exit' as const, reasonDetail: EXIT_REASON_TEXT[row.exitReason] || row.exitReason }))
  return [...entries, ...exits]
})
const filteredTurnoverRows = computed(() =>
  turnoverFilter.value === 'all'
    ? mergedTurnoverRows.value
    : mergedTurnoverRows.value.filter((row) => row.kind === turnoverFilter.value),
)
const comparison = computed(() => doc.value?.metrics.comparison ?? null)
const allLayer = computed(() => doc.value?.metrics.layers.all ?? null)

const dataTimeLabel = computed(() => {
  const slot = doc.value?.slotTime
  const anchored = doc.value?.anchoredSlotTime
  if (!doc.value) return ''
  return slot === 'EOD' ? `${doc.value.tradingDate} · 锚定 ${anchored || '--'}` : `${doc.value.tradingDate} ${slot}`
})
const timeBadgeTitle = computed(() => {
  const parts = [`snapshotId: ${doc.value?.snapshotId || '--'}`]
  if (doc.value?.stageConfirmState) parts.push(`historyStatus: ${doc.value.stageConfirmState.historyStatus}`)
  return parts.join('\n')
})
const missingDaysTitle = computed(() =>
  missingDays.value.map((d) => `${d.tradingDate || '未知日期'}：${d.reason || '缺失'}`).join('；'),
)

// 概览三级卡组（SectorDetail 概览结构）：主指标 2×2 大卡 + 资金中卡 + 统计小卡
const primaryCards = computed(() => {
  const layer = allLayer.value
  if (!layer) return []
  return [
    { icon: '📈', label: '上涨占比', value: formatShare(layer.upRatio), toneClass: 'up' },
    { icon: '📉', label: '下跌占比', value: formatShare(layer.downRatio), toneClass: 'down' },
    { icon: '⚖️', label: '热榜 TRIN', value: formatTrin(layer.hotTrin), toneClass: '' },
    { icon: '💰', label: '主力净额', value: formatMoney(layer.mainNetAmount), toneClass: (layer.mainNetAmount ?? 0) >= 0 ? 'up' : 'down' },
  ]
})
const fundCards = computed(() => {
  const layer = allLayer.value
  if (!layer) return []
  return [
    { icon: '🔥', label: '近涨停', value: formatNullableCount(layer.nearLimitUpCount), toneClass: '' },
    { icon: '🚀', label: '高涨幅≥7%', value: formatNullableCount(layer.highGainCount), toneClass: '' },
    { icon: '🌀', label: '高换手≥10%', value: formatNullableCount(layer.highTurnoverCount), toneClass: '' },
  ]
})
const statCards = computed(() => {
  const layer = allLayer.value
  const comp = comparison.value
  if (!layer) return []
  return [
    { icon: '📊', label: '参与统计', value: formatNullableCount(layer.topN), toneClass: '' },
    { icon: '🆕', label: '今日新入', value: formatNullableCount(comp?.newTop100Count ?? null), toneClass: '' },
    { icon: '💪', label: '新入强资', value: formatNullableCount(comp?.newTop100StrongMoneyCount ?? null), toneClass: '' },
    { icon: '🔁', label: '昨日强资留榜', value: formatShare(comp?.yesterdayStrongRetainRate ?? null), toneClass: '' },
  ]
})

// ---------- 分层结构（ECharts：多日分层对比，语言同历史对比；超大单净额全 0 不展示） ----------
const LAYERS = [
  { key: 'top20', label: '前20' },
  { key: 'top50', label: '前50' },
  { key: 'top100', label: '前100' },
  { key: 'all', label: '全池' },
] as const
type LayerKey = (typeof LAYERS)[number]['key']
// 分层结构时间范围：1天=最新交易日盘中半小时槽位（slots 接口对非交易日自动回落上一交易日），
// 3日/1周/1月=日线 EOD 终值
const LAYER_RANGES = [
  { key: '1d', label: '1天' },
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type LayerTimeRange = (typeof LAYER_RANGES)[number]['key']
const layersRange = ref<LayerTimeRange>('1d')
const layersLayer = ref<LayerKey>('all')
const layersChartRef = ref<HTMLElement | null>(null)
let layersChart: echarts.ECharts | null = null

// 指标开关：% 类走 % 轴，计数走数量轴，TRIN/金额各占独立轴
const LAYER_INDICATORS = [
  { key: 'upRatio', label: '涨占比', icon: '📈' },
  { key: 'downRatio', label: '跌占比', icon: '📉' },
  { key: 'avgChange', label: '平均涨幅', icon: '💹' },
  { key: 'trin', label: 'TRIN', icon: '⚖️' },
  { key: 'nearLimitUp', label: '近涨停', icon: '🔥' },
  { key: 'highGain', label: '高涨幅≥7%', icon: '🚀' },
  { key: 'highTurnover', label: '高换手≥10%', icon: '🌀' },
  { key: 'mainNet', label: '主力净额', icon: '💰' },
] as const
type LayerIndicatorKey = (typeof LAYER_INDICATORS)[number]['key']
// 默认四维（2026-09-28 用户裁决）：涨/跌占比 + 平均涨幅 + TRIN
const layersIndicators = ref<LayerIndicatorKey[]>(['upRatio', 'downRatio', 'avgChange', 'trin'])

// 每日/每槽位所选分层的数值点：null 缺失直传图表断线，不补 0。
// 1天=slots 最新交易日盘中槽位（label=槽位时间）；多日=series 日线 EOD 文档（label=交易日 MM-DD）
const layerPoints = computed(() => {
  const days = RANGE_DAYS[layersRange.value]
  const intraday = days === 1
  const source = intraday ? slots.value : seriesDocs.value.slice(-days)
  if (!source.length) return []
  const pct = (rate?: number | null) => (typeof rate === 'number' ? Math.round(rate * 1000) / 10 : null)
  return source.map((item, index) => {
    const m = item.metrics?.layers?.[layersLayer.value]
    return {
      label: intraday
        ? item.slotTime || `slot-${index}`
        : (item.tradingDate || '').slice(5) || `d-${index}`,
      title: intraday ? item.slotTime || `slot-${index}` : item.tradingDate || `d-${index}`,
      stage: item.stage,
      sample: m?.topN ?? null,
      upRatioPct: pct(m?.upRatio),
      downRatioPct: pct(m?.downRatio),
      avgChange: typeof m?.avgChange === 'number' ? m.avgChange : null,
      trin: typeof m?.hotTrin === 'number' ? m.hotTrin : null,
      nearLimitUp: m?.nearLimitUpCount ?? null,
      highGain: m?.highGainCount ?? null,
      highTurnover: m?.highTurnoverCount ?? null,
      mainNet: typeof m?.mainNetAmount === 'number' ? m.mainNetAmount : null,
    }
  })
})

function setLayersRange(range: LayerTimeRange) {
  if (layersRange.value === range) return
  layersRange.value = range
  void ensureSeriesDays(RANGE_DAYS[range]).then(() => nextTick(() => renderLayersChart()))
}

function setLayersLayer(layer: LayerKey) {
  if (layersLayer.value === layer) return
  layersLayer.value = layer
  nextTick(() => renderLayersChart())
}

function toggleLayerIndicator(key: LayerIndicatorKey) {
  const current = layersIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    layersIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    layersIndicators.value = LAYER_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderLayersChart())
}

const LAYER_AXIS_FMT: Record<string, (v: number | null) => string> = {
  涨占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  跌占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  平均涨幅: (v) => (v === null ? '--' : formatPercent(v)),
  TRIN: (v) => formatTrin(v),
  近涨停: (v) => formatNullableCount(v),
  '高涨幅≥7%': (v) => formatNullableCount(v),
  '高换手≥10%': (v) => formatNullableCount(v),
  主力净额: (v) => formatMoney(v),
}

function renderLayersChart() {
  if (!layersChartRef.value || !layerPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (layersChart && layersChart.getDom() !== layersChartRef.value) {
    layersChart.dispose()
    layersChart = null
  }
  if (!layersChart) {
    layersChart = echarts.init(layersChartRef.value)
  }

  const points = layerPoints.value
  const indicators = layersIndicators.value
  const series: any[] = []
  // 涨/跌占比与平均涨幅为柱图（红/绿/蓝，2026-09-28 用户裁决），同走 % 轴并列簇状
  if (indicators.includes('upRatio')) {
    series.push({
      name: '涨占比', type: 'bar', data: points.map((p) => p.upRatioPct),
      itemStyle: { color: '#ff4757' }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('downRatio')) {
    series.push({
      name: '跌占比', type: 'bar', data: points.map((p) => p.downRatioPct),
      itemStyle: { color: '#2ed573' }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('avgChange')) {
    series.push({
      name: '平均涨幅', type: 'bar', data: points.map((p) => p.avgChange),
      itemStyle: { color: '#1e90ff' }, yAxisIndex: 0,
    })
  }
  if (indicators.includes('trin')) {
    series.push({
      name: 'TRIN', type: 'line', data: points.map((p) => p.trin),
      smooth: true, symbol: 'diamond', symbolSize: 4, connectNulls: false,
      lineStyle: { color: '#3498db', width: 1.5, type: 'dashed' }, yAxisIndex: 2,
    })
  }
  if (indicators.includes('nearLimitUp')) {
    series.push({ name: '近涨停', type: 'bar', data: points.map((p) => p.nearLimitUp), itemStyle: { color: '#ff4757' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('highGain')) {
    series.push({ name: '高涨幅≥7%', type: 'bar', data: points.map((p) => p.highGain), itemStyle: { color: '#ff7f50' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('highTurnover')) {
    series.push({ name: '高换手≥10%', type: 'bar', data: points.map((p) => p.highTurnover), itemStyle: { color: '#4a90e2' }, barWidth: 8, yAxisIndex: 1 })
  }
  if (indicators.includes('mainNet')) {
    series.push({ name: '主力净额', type: 'bar', data: points.map((p) => p.mainNet), itemStyle: { color: '#ffb142' }, barWidth: 8, yAxisIndex: 3 })
  }
  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  layersChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = LAYER_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage ?? '']?.fg || textColor
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage || '缺失'} · 样本 ${formatNullableCount(point.sample)}</div>`,
            rows,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: 'TRIN',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '金额',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  layersChart.resize()
}

// 图下统计卡：所选分层多日均值/峰值，缺失 '--'
const layerStats = computed(() => {
  const pts = layerPoints.value
  const avgOf = (values: Array<number | null>) => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  }
  const avgUp = avgOf(pts.map((p) => p.upRatioPct))
  const avgMain = avgOf(pts.map((p) => p.mainNet))
  const avgTrin = avgOf(pts.map((p) => p.trin))
  const nearPeaks = pts.map((p) => p.nearLimitUp).filter((v): v is number => v !== null)
  const maxNear = nearPeaks.length ? Math.max(...nearPeaks) : null
  const unit = layersRange.value === '1d' ? '槽' : '日'
  const sub = pts.length ? `共 ${pts.length} ${unit}` : ''
  return [
    { label: '平均涨占比', value: avgUp === null ? '--' : `${avgUp.toFixed(1)}%`, sub },
    { label: '近涨停峰值', value: maxNear === null ? '--' : String(maxNear), sub },
    { label: '平均主力净额', value: avgMain === null ? '--' : formatMoney(avgMain), sub },
    { label: '平均TRIN', value: avgTrin === null ? '--' : avgTrin.toFixed(2), sub },
  ]
})

const layersNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  if (seriesError.value && RANGE_DAYS[layersRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!layerPoints.value.length) return ''
  if (layersRange.value === '1d') {
    // slots 接口对非交易日回落上一交易日，注记里显式标出实际交易日
    if (slotsDegradedReason.value) return slotsDegradedReason.value
    return slotsTradingDate.value ? `${slotsTradingDate.value} · 盘中半小时一帧，随采集更新` : ''
  }
  return dailyRangeNote(layerPoints.value)
})

// ---------- 涨停证据 ----------
const limitEvidence = computed(() => doc.value?.metrics.limitEvidence ?? null)
const intersectionCards = computed(() => {
  const it = limitEvidence.value?.intersection
  if (!it) return []
  return [
    { label: '全池涨停', value: `${formatNullableCount(it.top100LimitUpCount)}（${formatShare(it.top100LimitUpShare)}）` },
    { label: '近涨停', value: formatNullableCount(it.top100NearLimitUpCount) },
    { label: '二板以上', value: formatNullableCount(it.top100Board2PlusCount) },
    { label: '最高板', value: `${formatNullableCount(it.top100MaxBoardHeight)} 板` },
    { label: '前50 涨停', value: formatNullableCount(it.top50LimitUpCount) },
    { label: '前20 涨停', value: formatNullableCount(it.top20LimitUpCount) },
    { label: '池内炸板', value: `${formatNullableCount(it.top100ZhabanCount)}（${formatShare(it.top100ZhabanShare)}）`, toneClass: 'down' },
  ]
})
const marketCards = computed(() => {
  const market = limitEvidence.value?.market
  if (!market) return []
  const ths = market.thsPools ?? null
  return [
    { label: '全市场涨停', value: formatNullableCount(market.ztCount), toneClass: '' },
    { label: '封板率', value: market.fengbanRate != null ? `${market.fengbanRate.toFixed(0)}%` : '--', toneClass: '' },
    { label: '全市场炸板', value: formatNullableCount(market.zhabanCount), toneClass: 'down' },
    { label: '首板', value: formatNullableCount(market.board1), toneClass: '' },
    { label: '2板', value: formatNullableCount(market.board2), toneClass: '' },
    { label: '3板', value: formatNullableCount(market.board3), toneClass: '' },
    { label: '4板+', value: formatNullableCount(market.board4Plus), toneClass: '' },
    { label: '最高连板', value: `${formatNullableCount(market.maxContinuousDays)} 板`, toneClass: '' },
    { label: 'THS 炸板池', value: ths ? formatNullableCount(ths.failedCount) : '--', toneClass: 'down' },
    { label: 'THS 回撤榜', value: ths ? formatNullableCount(ths.drawdownCount) : '--', toneClass: 'down' },
  ]
})
const marketEvidenceNote = computed(() => {
  const diagnosticsList = diagnostics.value.find((item) => item.includes('limitSummary'))
  return diagnosticsList || '全市场口径来自采集链 limitSummary，仅作背景参考'
})
const yesterdayLimitCards = computed(() => {
  const y = limitEvidence.value?.yesterdayHotLimit
  if (!y) return []
  return [
    { label: '昨日涨停数', value: formatNullableCount(y.count), toneClass: '' },
    { label: '留榜数', value: formatNullableCount(y.retainedTop100Count), toneClass: '' },
    { label: '今日均涨', value: formatPercent(y.avgChange), toneClass: '' },
    { label: '正收益率', value: formatShare(y.positiveRate), toneClass: 'up' },
    { label: '走弱率', value: formatShare(y.weakeningRate), toneClass: 'down' },
    { label: '冲板失败率', value: formatShare(y.failedOrWeakRate), toneClass: 'down' },
  ]
})

// ---------- EOD 文档明细（2026-09-25：文档全字段在热榜概览完整展示） ----------
// 设计：已知字段走中文标签分组/表格；遗漏路径由「未归类字段」兜底透出（fail-visible，
// 后端文档新增字段时无需改本面板即可见）。缺失值一律 '--'，不伪造 0。
type DocFmt =
  | 'text' | 'count' | 'share' | 'pct' | 'percentRaw' | 'money' | 'trin'
  | 'datetime' | 'bool' | 'arrayLen' | 'stageCounts' | 'stageShares' | 'statusSource' | 'transition'
interface DocRow { label: string; value: string; tone?: string; wide?: boolean }
interface DocGroup { title: string; rows: DocRow[] }
interface DocTableLine { label: string; m: Record<string, unknown> | null }
interface DocTable { title: string; rowLabel: string; rows: DocTableLine[] }

function pickDocPath(root: unknown, path: string): unknown {
  let cur: unknown = root
  for (const seg of path.split('.')) {
    if (cur === null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[seg]
  }
  return cur
}

function formatDocDatetime(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '--'
  const ms = value < 1e12 ? value * 1000 : value
  const d = new Date(ms)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function fmtStageCountsCompact(value: unknown): string {
  if (!value || typeof value !== 'object') return '--'
  const counts = value as Record<string, unknown>
  return (Object.keys(HOT_LIST_STAGE_LABELS) as HotListStageKey[])
    .map((key) => `${HOT_LIST_STAGE_LABELS[key]}${typeof counts[key] === 'number' ? counts[key] : '--'}`)
    .join(' ')
}

function fmtStageSharesCompact(value: unknown): string {
  if (!value || typeof value !== 'object') return '--'
  const shares = value as Record<string, unknown>
  return (Object.keys(HOT_LIST_STAGE_LABELS) as HotListStageKey[])
    .map((key) => {
      const v = shares[key]
      return `${HOT_LIST_STAGE_LABELS[key]}${typeof v === 'number' ? `${Math.round(v * 100)}%` : '--'}`
    })
    .join(' ')
}

function fmtStatusSourceCompact(value: unknown): string {
  if (!value || typeof value !== 'object') return '--'
  const src = value as Record<string, unknown>
  const joined = typeof src.displayStatus === 'number' || typeof src.fallback === 'number'
    ? `金标${typeof src.displayStatus === 'number' ? src.displayStatus : '--'}·回退${typeof src.fallback === 'number' ? src.fallback : '--'}`
    : ''
  return joined || '--'
}

function fmtDocValue(value: unknown, fmt: DocFmt): string {
  if (value === undefined || value === null || value === '') return '--'
  const num = typeof value === 'number' ? value : Number(value)
  switch (fmt) {
    case 'count':
      return Number.isFinite(num) ? String(Math.round(num)) : '--'
    case 'share':
      return Number.isFinite(num) ? `${Math.round(num * 100)}%` : '--'
    case 'pct':
      return Number.isFinite(num) ? `${num >= 0 ? '+' : ''}${num.toFixed(2)}%` : '--'
    case 'percentRaw':
      return Number.isFinite(num) ? `${num}%` : '--'
    case 'money':
      return Number.isFinite(num) ? formatMoney(num) : '--'
    case 'trin':
      return Number.isFinite(num) ? num.toFixed(2) : '--'
    case 'datetime':
      return formatDocDatetime(value)
    case 'bool':
      return value === true ? '是' : value === false ? '否' : '--'
    case 'arrayLen':
      return Array.isArray(value) ? String(value.length) : '--'
    case 'stageCounts':
      return fmtStageCountsCompact(value)
    case 'stageShares':
      return fmtStageSharesCompact(value)
    case 'statusSource':
      return fmtStatusSourceCompact(value)
    case 'transition': {
      if (!value || typeof value !== 'object') return '无'
      const entries = Object.entries(value as Record<string, unknown>)
      if (!entries.length) return '无'
      return entries.map(([text, count]) => `${transitionZh(text)}×${String(count)}`).join('；')
    }
    default:
      if (Array.isArray(value)) return value.length ? value.join('；') : '无'
      if (typeof value === 'object') return JSON.stringify(value)
      return String(value)
  }
}

function docCellTone(value: unknown, fmt: DocFmt): string {
  if (fmt !== 'money' && fmt !== 'pct') return ''
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num) || num === 0) return ''
  return num > 0 ? 'up' : 'down'
}

// 截面指标表（三日截面 / 四分层共用列集）：字段缺失显示 --；超大单净额保留（部分历史文档有值）
const docDayColumns: { label: string; key: string; fmt: DocFmt }[] = [
  { label: '样本', key: 'topN', fmt: 'count' },
  { label: '涨家', key: 'upCount', fmt: 'count' },
  { label: '跌家', key: 'downCount', fmt: 'count' },
  { label: '平家', key: 'flatCount', fmt: 'count' },
  { label: '涨占比', key: 'upRatio', fmt: 'share' },
  { label: '跌占比', key: 'downRatio', fmt: 'share' },
  { label: '平均涨幅', key: 'avgChange', fmt: 'pct' },
  { label: 'TRIN', key: 'hotTrin', fmt: 'trin' },
  { label: '主力净额', key: 'mainNetAmount', fmt: 'money' },
  { label: '超大单净额', key: 'superNetAmount', fmt: 'money' },
  { label: '总成交', key: 'totalTurnover', fmt: 'money' },
  { label: '涨成交', key: 'upTurnover', fmt: 'money' },
  { label: '跌成交', key: 'downTurnover', fmt: 'money' },
  { label: '近涨停', key: 'nearLimitUpCount', fmt: 'count' },
  { label: '高涨幅', key: 'highGainCount', fmt: 'count' },
  { label: '高换手', key: 'highTurnoverCount', fmt: 'count' },
  { label: '风险占比', key: 'riskShare', fmt: 'share' },
  { label: '拥挤占比', key: 'crowdedShare', fmt: 'share' },
  { label: '强资占比', key: 'strongMoneyShare', fmt: 'share' },
  { label: '活跃机会', key: 'activeOpportunityShare', fmt: 'share' },
  { label: '阶段分布', key: 'stageCounts', fmt: 'stageCounts' },
  { label: '阶段占比', key: 'stageShares', fmt: 'stageShares' },
  { label: '状态来源', key: 'statusSourceCounts', fmt: 'statusSource' },
  { label: '交易日', key: 'tradingDate', fmt: 'text' },
]

function walkUncoveredDoc(prefix: string, node: unknown, covered: Set<string>, out: { path: string; value: string }[]) {
  if (node === null || typeof node !== 'object' || Array.isArray(node)) {
    if (prefix && !covered.has(prefix)) {
      out.push({ path: prefix, value: fmtDocValue(node, 'text') })
    }
    return
  }
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (covered.has(path)) continue
    walkUncoveredDoc(path, value, covered, out)
  }
}

// 折叠状态（2026-09-25 用户裁决）：标题即折叠按钮，默认已折叠
const docFullCollapsed = ref(true)

const docFull = computed<{ groups: DocGroup[]; tables: DocTable[]; remaining: { path: string; value: string }[] }>(() => {
  const raw = doc.value as unknown as Record<string, unknown> | null
  if (!raw) return { groups: [], tables: [], remaining: [] }
  const groups: DocGroup[] = []
  const covered = new Set<string>()
  const mark = (...paths: string[]) => paths.forEach((p) => covered.add(p))
  const row = (path: string, label: string, fmt: DocFmt = 'text', wide = false): DocRow => {
    mark(path)
    const value = pickDocPath(raw, path)
    return { label, value: fmtDocValue(value, fmt), tone: docCellTone(value, fmt), wide }
  }

  groups.push({
    title: '文档元信息',
    rows: [
      row('datasetId', '数据集'),
      row('snapshotType', '快照类型'),
      row('tradingDate', '交易日'),
      row('slotTime', '文档槽位'),
      row('anchoredSlotTime', '锚定槽位'),
      row('snapshotId', '快照ID', 'text', true),
      row('timestamp', '帧时间', 'datetime'),
      row('computedAt', '计算时间', 'datetime'),
      row('stage', '确认阶段'),
      row('rawStage', '本帧截面阶段'),
      row('riskLevel', '风险等级'),
      row('confidence', '置信度', 'percentRaw'),
      row('missing', '缺失标记', 'bool'),
      row('reason', '缺失原因'),
      row('summary', '盘面证据', 'text', true),
    ],
  })
  // 逐字段 mark（review 2026-09-25）：整树 mark 会吞掉子树内未来新增字段（兜底失效）；
  // 后端 stageConfirmState 新增键时自动落「未归类字段」
  mark(
    'stageConfirmState.pending',
    'stageConfirmState.pendingStage',
    'stageConfirmState.pendingSince',
    'stageConfirmState.confirmSlots',
    'stageConfirmState.historyStatus',
  )
  const confirmState = (pickDocPath(raw, 'stageConfirmState') ?? null) as Record<string, unknown> | null
  groups.push({
    title: '阶段多帧确认',
    rows: [
      { label: '摆动中', value: fmtDocValue(confirmState?.pending, 'bool') },
      { label: '摆动阶段', value: fmtDocValue(confirmState?.pendingStage, 'text') },
      { label: '摆动自', value: fmtDocValue(confirmState?.pendingSince, 'text') },
      { label: '确认槽数', value: fmtDocValue(confirmState?.confirmSlots, 'count') },
      { label: '历史状态', value: fmtDocValue(confirmState?.historyStatus, 'text') },
    ],
  })

  groups.push({
    title: '核心指标（metrics 顶层）',
    rows: [
      row('metrics.poolSize', '池规模', 'count'),
      row('metrics.topN', '参与统计', 'count'),
      row('metrics.allPoolUpRatio', '全池上涨占比', 'share'),
      row('metrics.hotTrin', '热榜 TRIN', 'trin'),
      row('metrics.retentionRate1d', '留存率 1 日', 'share'),
      row('metrics.retentionRate2d', '留存率 2 日', 'share'),
      row('metrics.limitIntersectionRate', '涨停交集占比', 'share'),
      row('metrics.newEntryCount', '新入数', 'count'),
      row('metrics.eliminatedCount', '剔除数', 'count'),
      row('metrics.nearLimitUpCount', '近涨停', 'count'),
      row('metrics.highGainCount', '高涨幅≥7%', 'count'),
      row('metrics.riskShare', '风险占比', 'share'),
      row('metrics.activeOpportunityShare', '活跃机会占比', 'share'),
      row('metrics.strongMoneyShare', '强资占比', 'share'),
      row('metrics.crowdedShare', '拥挤占比', 'share'),
      row('metrics.statusSourceCounts', '状态来源', 'statusSource'),
      row('metrics.transitionCounts', '阶段迁移', 'transition', true),
      row('metrics.missingEvidence', '缺失证据', 'text', true),
    ],
  })

  groups.push({
    title: '三日对比',
    rows: [
      row('metrics.comparison.totalChange1d', '池规模变动 1 日', 'count'),
      row('metrics.comparison.totalChange2d', '池规模变动 2 日', 'count'),
      row('metrics.comparison.top100RetainFromYesterday', '留榜数（对昨日）', 'count'),
      row('metrics.comparison.top100RetainRateFromYesterday', '留榜率（对昨日）', 'share'),
      row('metrics.comparison.top100RetainFromDayBefore', '留榜数（对前日）', 'count'),
      row('metrics.comparison.top100RetainRateFromDayBefore', '留榜率（对前日）', 'share'),
      row('metrics.comparison.newTop100Count', '新入数', 'count'),
      row('metrics.comparison.newTop100StrongMoneyCount', '新入强资数', 'count'),
      row('metrics.comparison.yesterdayStrongRetainRate', '昨日强资留榜率', 'share'),
      row('metrics.comparison.yesterdayCrowdedRiskCount', '昨日拥挤转风险数', 'count'),
    ],
  })

  // 逐字段 mark（review 2026-09-25）：整树 mark 会吞掉子树内未来新增字段
  mark(
    'metrics.comparison.yesterdayStrongPerformance.count',
    'metrics.comparison.yesterdayStrongPerformance.matchedCount',
    'metrics.comparison.yesterdayStrongPerformance.retainedTop100Count',
    'metrics.comparison.yesterdayStrongPerformance.avgChange',
    'metrics.comparison.yesterdayStrongPerformance.positiveCount',
    'metrics.comparison.yesterdayStrongPerformance.positiveRate',
    'metrics.comparison.yesterdayStrongPerformance.weakeningCount',
    'metrics.comparison.yesterdayStrongPerformance.weakeningRate',
  )
  const ysp = (pickDocPath(raw, 'metrics.comparison.yesterdayStrongPerformance') ?? null) as Record<string, unknown> | null
  groups.push({
    title: '昨日强票表现',
    rows: [
      { label: '昨强数量', value: fmtDocValue(ysp?.count, 'count') },
      { label: '今日在榜', value: fmtDocValue(ysp?.matchedCount, 'count') },
      { label: '留榜数', value: fmtDocValue(ysp?.retainedTop100Count, 'count') },
      { label: '平均涨幅', value: fmtDocValue(ysp?.avgChange, 'pct'), tone: docCellTone(ysp?.avgChange, 'pct') },
      { label: '上涨家数', value: fmtDocValue(ysp?.positiveCount, 'count') },
      { label: '正收益率', value: fmtDocValue(ysp?.positiveRate, 'share') },
      { label: '走弱家数', value: fmtDocValue(ysp?.weakeningCount, 'count') },
      { label: '走弱率', value: fmtDocValue(ysp?.weakeningRate, 'share') },
    ],
  })

  const turnoverNode = (raw.turnover ?? null) as Record<string, unknown> | null
  groups.push({
    title: '池换手概况（明细见池换手页签）',
    rows: [
      row('turnover.previousPoolSize', '昨池规模', 'count'),
      row('turnover.currentPoolSize', '今池规模', 'count'),
      row('turnover.retainedFromYesterday', '留存数', 'count'),
      { label: '新入明细', value: `${fmtDocValue(turnoverNode?.newEntries, 'arrayLen')} 只` },
      { label: '剔除明细', value: `${fmtDocValue(turnoverNode?.eliminated, 'arrayLen')} 只` },
    ],
  })
  // 明细四键逐字段 mark（review 2026-09-25）：整树 mark 会吞掉子树内未来新增字段；
  // details 数组在池换手页签展示，新入/剔除 code 列表由上面两行计数展示
  mark('turnover.newEntries', 'turnover.eliminated', 'turnover.newEntryDetails', 'turnover.eliminatedDetails')

  // limitEvidence 三容器已完整展示于本页签上方，signals/warnings/diagnostics 见强证据/风险/诊断块
  mark('metrics.limitEvidence', 'signals', 'warnings', 'diagnostics')

  const comp = (raw.metrics as Record<string, unknown> | undefined)?.comparison as Record<string, unknown> | undefined
  const layers = (raw.metrics as Record<string, unknown> | undefined)?.layers as Record<string, unknown> | undefined
  const tables: DocTable[] = []
  if (comp) {
    mark('metrics.comparison.today', 'metrics.comparison.yesterday', 'metrics.comparison.dayBefore')
    tables.push({
      title: '三日截面指标',
      rowLabel: '截面',
      rows: [
        { label: '今日', m: (comp.today ?? null) as Record<string, unknown> | null },
        { label: '昨日', m: (comp.yesterday ?? null) as Record<string, unknown> | null },
        { label: '前日', m: (comp.dayBefore ?? null) as Record<string, unknown> | null },
      ],
    })
  }
  if (layers) {
    mark('metrics.layers')
    tables.push({
      title: '分层指标（top20 / top50 / top100 / 全池）',
      rowLabel: '分层',
      rows: [
        { label: '前20', m: (layers.top20 ?? null) as Record<string, unknown> | null },
        { label: '前50', m: (layers.top50 ?? null) as Record<string, unknown> | null },
        { label: '前100', m: (layers.top100 ?? null) as Record<string, unknown> | null },
        { label: '全池', m: (layers.all ?? null) as Record<string, unknown> | null },
      ],
    })
  }

  const remaining: { path: string; value: string }[] = []
  walkUncoveredDoc('', raw, covered, remaining)
  return { groups, tables, remaining }
})

// ---------- 阶段分布（ECharts 饼图：全池六态占比） ----------
// 六态配色沿用面板语义色：点火红/扩散橙/拥挤琥珀/反转绿(风险)/冷却蓝(降温)/无阶段灰
const STAGE_PIE_COLORS: Record<string, string> = {
  ignition: '#ff4757',
  expansion: '#ff7f50',
  crowded: '#ffb142',
  reversal: '#2ed573',
  cooling: '#3498db',
  unknown: '#7f8c8d',
}

const stageChartRef = ref<HTMLElement | null>(null)
let stageChart: echarts.ECharts | null = null

// 饼图数据：0 值阶段不进扇区（tooltip/图例随之收敛），缺失字段时列表为空走空态
const stagePieData = computed(() => {
  const all = allLayer.value
  if (!all?.stageCounts) return []
  return (Object.keys(HOT_LIST_STAGE_LABELS) as HotListStageKey[])
    .map((key) => ({ key, name: HOT_LIST_STAGE_LABELS[key], value: all.stageCounts[key] ?? 0 }))
    .filter((item) => item.value > 0)
})

const stageTotal = computed(() => stagePieData.value.reduce((sum, item) => sum + item.value, 0))

// 右侧明细列表：按数量降序，含占比与比例条
const stageList = computed(() => {
  const total = stageTotal.value
  return stagePieData.value
    .map((item) => {
      const pct = total > 0 ? (item.value / total) * 100 : 0
      return { ...item, count: item.value, color: STAGE_PIE_COLORS[item.key] || '#7f8c8d', pctText: `${pct.toFixed(1)}%` }
    })
    .sort((a, b) => b.value - a.value)
})

function renderStageChart() {
  if (!stageChartRef.value || !stagePieData.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (stageChart && stageChart.getDom() !== stageChartRef.value) {
    stageChart.dispose()
    stageChart = null
  }
  if (!stageChart) {
    stageChart = echarts.init(stageChartRef.value)
  }

  const sliceColor = cssVar('--bg-secondary', '#222222')

  stageChart.setOption(
    {
      tooltip: {
        trigger: 'item',
        confine: true,
        formatter: (params: any) =>
          `${params.marker}${params.name}：${params.value}（${params.percent}%）`,
      },
      series: [
        {
          type: 'pie',
          // 细环 + 中心总样本（HTML 覆层），明细走右侧列表
          radius: ['62%', '86%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: sliceColor, borderWidth: 3 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: { scale: true, scaleSize: 5 },
          data: stagePieData.value.map((item) => ({
            name: item.name,
            value: item.value,
            itemStyle: { color: STAGE_PIE_COLORS[item.key] || '#7f8c8d' },
          })),
        },
      ],
      backgroundColor: 'transparent',
    },
    // 数据刷新时整体替换，避免旧扇区残留
    { notMerge: true },
  )
  stageChart.resize()
}
// 迁移键中文表述（行级六态），单段为当日延续；与后端 cycle.transition 原始串 "a->b" 对应
const STAGE_TRANSITION_ZH: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
  unknown: '无阶段',
}

function transitionZh(text: string): string {
  return text
    .split('->')
    .map((segment) => STAGE_TRANSITION_ZH[segment.trim()] || segment)
    .join('→')
}

const transitionItems = computed(() => {
  const counts = doc.value?.metrics.transitionCounts as Record<string, number> | undefined
  if (!counts) return []
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([text, count]) => ({ key: text, text: transitionZh(text), count }))
})

// ---------- 历史对比（ECharts：池流转/留榜/强票表现多日趋势，语言同情绪趋势） ----------
// 时间范围与多日缓存（seriesDocs/ensureSeriesDays）与情绪趋势页签共享
const COMPARE_RANGES = [
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type CompareTimeRange = (typeof COMPARE_RANGES)[number]['key']
const compareRange = ref<CompareTimeRange>('3d')
const compareChartRef = ref<HTMLElement | null>(null)
let compareChart: echarts.ECharts | null = null

// 指标开关：池流转三类走数量轴，留榜/强票表现走 % 轴
const COMPARE_INDICATORS = [
  { key: 'pool', label: '池规模', icon: '📊' },
  { key: 'new', label: '新入', icon: '🆕' },
  { key: 'retainRate', label: '留榜率', icon: '🔁' },
  { key: 'risk', label: '风险数', icon: '⚠️' },
  { key: 'positiveRate', label: '正收益率', icon: '💪' },
  { key: 'weakenRate', label: '转弱率', icon: '📉' },
] as const
type CompareIndicatorKey = (typeof COMPARE_INDICATORS)[number]['key']
const compareIndicators = ref<CompareIndicatorKey[]>(['pool', 'new', 'retainRate'])

// 每日数值点：null 缺失直传图表断线，不补 0
const comparePoints = computed(() => {
  const source = seriesDocs.value.slice(-RANGE_DAYS[compareRange.value])
  if (!source.length) return []
  const pct = (rate?: number | null) => (typeof rate === 'number' ? Math.round(rate * 1000) / 10 : null)
  return source.map((item, index) => {
    const all = item.metrics?.layers?.all
    const counts = all?.stageCounts
    const comp = item.metrics?.comparison
    const strong = comp?.yesterdayStrongPerformance
    return {
      label: (item.tradingDate || '').slice(5) || `d-${index}`,
      title: item.tradingDate || `d-${index}`,
      stage: item.stage,
      pool: all?.topN ?? comp?.today?.topN ?? null,
      newCount: comp?.newTop100Count ?? null,
      retainRatePct: pct(comp?.top100RetainRateFromYesterday),
      risk: counts ? counts.reversal + counts.cooling : null,
      positiveRatePct: pct(strong?.positiveRate),
      weakenRatePct: pct(strong?.weakeningRate),
      strong: strong
        ? {
            count: strong.count ?? null,
            matched: strong.matchedCount ?? null,
            retained: strong.retainedTop100Count ?? null,
            avgChange: typeof strong.avgChange === 'number' ? strong.avgChange : null,
          }
        : null,
    }
  })
})

function toggleCompareIndicator(key: CompareIndicatorKey) {
  const current = compareIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    compareIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    compareIndicators.value = COMPARE_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderCompareChart())
}

async function setCompareRange(range: CompareTimeRange) {
  if (compareRange.value === range) return
  compareRange.value = range
  await ensureSeriesDays(RANGE_DAYS[range])
  nextTick(() => renderCompareChart())
}

const COMPARE_AXIS_FMT: Record<string, (v: number | null) => string> = {
  池规模: (v) => formatNullableCount(v),
  新入: (v) => formatNullableCount(v),
  留榜率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  风险数: (v) => formatNullableCount(v),
  正收益率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  转弱率: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
}

function renderCompareChart() {
  if (!compareChartRef.value || !comparePoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (compareChart && compareChart.getDom() !== compareChartRef.value) {
    compareChart.dispose()
    compareChart = null
  }
  if (!compareChart) {
    compareChart = echarts.init(compareChartRef.value)
  }

  const points = comparePoints.value
  const indicators = compareIndicators.value
  const series: any[] = []
  if (indicators.includes('pool')) {
    series.push({ name: '池规模', type: 'bar', data: points.map((p) => p.pool), itemStyle: { color: '#ffd700' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('new')) {
    series.push({ name: '新入', type: 'bar', data: points.map((p) => p.newCount), itemStyle: { color: '#ff7f50' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('risk')) {
    series.push({ name: '风险数', type: 'bar', data: points.map((p) => p.risk), itemStyle: { color: '#2ed573' }, barWidth: 8, yAxisIndex: 0 })
  }
  if (indicators.includes('retainRate')) {
    series.push({
      name: '留榜率', type: 'line', data: points.map((p) => p.retainRatePct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#4a90e2', width: 2 }, yAxisIndex: 1,
    })
  }
  if (indicators.includes('positiveRate')) {
    series.push({
      name: '正收益率', type: 'line', data: points.map((p) => p.positiveRatePct),
      smooth: true, symbol: 'circle', symbolSize: 5, connectNulls: false,
      lineStyle: { color: '#ff4757', width: 2 }, yAxisIndex: 1,
    })
  }
  if (indicators.includes('weakenRate')) {
    series.push({
      name: '转弱率', type: 'line', data: points.map((p) => p.weakenRatePct),
      smooth: true, symbol: 'diamond', symbolSize: 4, connectNulls: false,
      lineStyle: { color: '#2ed573', width: 1.5, type: 'dashed' }, yAxisIndex: 1,
    })
  }
  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  compareChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = COMPARE_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage ?? '']?.fg || textColor
          const strongLine = point.strong
            ? `<div style="margin-top:4px;color:${textColor};">强票：${formatNullableCount(point.strong.count)} 只 · 可比 ${formatNullableCount(point.strong.matched)} · 留榜 ${formatNullableCount(point.strong.retained)} · 均涨 ${point.strong.avgChange === null ? '--' : formatPercent(point.strong.avgChange)}</div>`
            : ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage || '缺失'}</div>`,
            rows,
            strongLine,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  compareChart.resize()
}

// 图下统计卡：多日均值口径，缺失 '--'
const compareStats = computed(() => {
  const pts = comparePoints.value
  const avgOf = (values: Array<number | null>) => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
  }
  const avgPool = avgOf(pts.map((p) => p.pool))
  const avgNew = avgOf(pts.map((p) => p.newCount))
  const avgRetain = avgOf(pts.map((p) => p.retainRatePct))
  const avgPositive = avgOf(pts.map((p) => p.positiveRatePct))
  const sub = pts.length ? `共 ${pts.length} 日` : ''
  return [
    { label: '平均池规模', value: avgPool === null ? '--' : formatNullableCount(avgPool), sub },
    { label: '平均新入', value: avgNew === null ? '--' : formatNullableCount(avgNew), sub },
    { label: '平均留榜率', value: avgRetain === null ? '--' : `${avgRetain.toFixed(1)}%`, sub },
    { label: '平均正收益率', value: avgPositive === null ? '--' : `${avgPositive.toFixed(1)}%`, sub },
  ]
})

const compareNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  if (seriesError.value && RANGE_DAYS[compareRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!comparePoints.value.length) return ''
  return dailyRangeNote(comparePoints.value)
})

// ---------- 情绪趋势（ECharts：确认阶段铺底 + 指标开关多序列，分歧人话进 tooltip） ----------
function stageDriftText(rawStage: string, confirmedStage: string): string {
  const rawHeat = STAGE_HEAT[rawStage] ?? 1
  const confirmedHeat = STAGE_HEAT[confirmedStage] ?? 1
  if (rawHeat > confirmedHeat) return '短暂走高'
  if (rawHeat < confirmedHeat) return '短暂回落'
  return '盘中波动'
}

// 情绪趋势指标开关（SectorDetail 历史趋势语言：pill 开关式多序列）
const TREND_INDICATORS = [
  { key: 'upRatio', label: '涨占比', icon: '📈' },
  { key: 'attack', label: '攻击', icon: '🚀' },
  { key: 'risk', label: '风险', icon: '⚠️' },
  { key: 'trin', label: 'TRIN', icon: '⚖️' },
  { key: 'pool', label: '池规模', icon: '📊' },
] as const
type TrendIndicatorKey = (typeof TREND_INDICATORS)[number]['key']

// 阶段铺底色：冷→热语义色，10% alpha 底 + 实色标签（与 STAGE_HEAT 冷热语感一致）
const STAGE_TREND_META: Record<string, { bg: string; fg: string }> = {
  冰点: { bg: 'rgba(74, 144, 226, 0.10)', fg: '#4a90e2' },
  退潮: { bg: 'rgba(127, 140, 141, 0.12)', fg: '#7f8c8d' },
  启动: { bg: 'rgba(255, 177, 66, 0.10)', fg: '#ffb142' },
  发酵: { bg: 'rgba(255, 127, 80, 0.12)', fg: '#ff7f50' },
  高潮: { bg: 'rgba(255, 71, 87, 0.10)', fg: '#ff4757' },
}

const trendChartRef = ref<HTMLElement | null>(null)
let trendChart: echarts.ECharts | null = null
const trendIndicators = ref<TrendIndicatorKey[]>(['upRatio', 'attack', 'risk'])

// 时间范围（SectorDetail 历史趋势语言）：1天=日内半小时槽位，3日/1周/1月=日线 EOD 终值
const TIME_RANGES = [
  { key: '1d', label: '1天' },
  { key: '3d', label: '3日' },
  { key: '1w', label: '1周' },
  { key: '1m', label: '1月' },
] as const
type TrendTimeRange = (typeof TIME_RANGES)[number]['key']
const RANGE_DAYS: Record<TrendTimeRange, number> = { '1d': 1, '3d': 3, '1w': 5, '1m': 20 }
const timeRange = ref<TrendTimeRange>('1d')
const seriesDocs = ref<HotListSentimentDayDoc[]>([])
const seriesDaysLoaded = ref(0)
const seriesMissingDays = ref<HotlistSentimentMissingDay[]>([])
const seriesError = ref<string | null>(null)
const seriesLoading = ref(false)

// 每槽位/每日数值点：null 缺失直传图表断线（connectNulls: false），不补 0。
// 1天=slots 日内槽位（label=槽位时间）；多日=series 日线 EOD 文档（label=交易日 MM-DD）
const trendPoints = computed(() => {
  const days = RANGE_DAYS[timeRange.value]
  const intraday = days === 1
  const source = intraday ? slots.value : seriesDocs.value.slice(-days)
  if (!source.length) return []
  return source.map((item, index) => {
    const all = item.metrics?.layers?.all
    const counts = all?.stageCounts
    const rawStage = item.rawStage || item.stage
    const drift = item.stage && rawStage && rawStage !== item.stage ? stageDriftText(rawStage, item.stage) : ''
    return {
      label: intraday
        ? item.slotTime || `slot-${index}`
        : (item.tradingDate || '').slice(5) || `d-${index}`,
      title: intraday ? item.slotTime || `slot-${index}` : item.tradingDate || `d-${index}`,
      stage: item.stage,
      drift,
      driftRaw: rawStage,
      pool: item.metrics?.poolSize ?? all?.total ?? null,
      upRatioPct: typeof all?.upRatio === 'number' ? Math.round(all.upRatio * 1000) / 10 : null,
      attack: counts ? counts.ignition + counts.expansion : null,
      risk: counts ? counts.reversal + counts.cooling : null,
      trin: typeof all?.hotTrin === 'number' ? all.hotTrin : null,
    }
  })
})

// 窗口超过已加载天数时拉更长序列（后端 cap 30 日），缺失日结构化收集不吞掉；
// seriesDocs 缓存与加载态由情绪趋势/历史对比/分层结构三页签共享。
// 代际守卫：快速连切档位时旧响应直接丢弃，最新请求独占缓存写入权
let seriesReqId = 0

async function ensureSeriesDays(days: number) {
  if (days <= seriesDaysLoaded.value) return
  const reqId = ++seriesReqId
  seriesLoading.value = true
  seriesError.value = null
  try {
    const result = await fetchHotlistSentimentSeries(days)
    if (reqId !== seriesReqId) return
    if (result.degraded) {
      seriesError.value = result.reason || '多日序列不可用'
    } else {
      seriesDocs.value = result.items
      seriesDaysLoaded.value = days
      seriesMissingDays.value = result.missingDays
    }
  } catch (err) {
    if (reqId !== seriesReqId) return
    seriesError.value = err instanceof Error ? err.message : '加载多日序列失败'
  } finally {
    if (reqId === seriesReqId) seriesLoading.value = false
  }
}

async function setTimeRange(range: TrendTimeRange) {
  if (timeRange.value === range) return
  timeRange.value = range
  await ensureSeriesDays(RANGE_DAYS[range])
  nextTick(() => renderTrendChart())
}

// 图下统计卡（SectorDetail historyStats 语言：峰值带时间，均值带样本数，缺失 '--'）
const trendStats = computed(() => {
  const pts = trendPoints.value
  const maxOf = (values: Array<number | null>): number | null => {
    const nums = values.filter((v): v is number => v !== null)
    return nums.length ? Math.max(...nums) : null
  }
  const timeOfValue = (pick: (p: (typeof pts)[number]) => number | null, target: number | null): string => {
    if (target === null) return ''
    return pts.find((p) => pick(p) === target)?.label || ''
  }
  const ups = pts.map((p) => p.upRatioPct).filter((v): v is number => v !== null)
  const trins = pts.map((p) => p.trin).filter((v): v is number => v !== null)
  const maxAttack = maxOf(pts.map((p) => p.attack))
  const maxRisk = maxOf(pts.map((p) => p.risk))
  const avgUp = ups.length ? ups.reduce((a, b) => a + b, 0) / ups.length : null
  const avgTrin = trins.length ? trins.reduce((a, b) => a + b, 0) / trins.length : null
  const unit = timeRange.value === '1d' ? '槽' : '日'
  return [
    { label: '平均涨占比', value: avgUp === null ? '--' : `${avgUp.toFixed(1)}%`, sub: ups.length ? `共 ${ups.length} ${unit}` : '' },
    { label: '攻击峰值', value: maxAttack === null ? '--' : String(maxAttack), sub: timeOfValue((p) => p.attack, maxAttack) },
    { label: '风险峰值', value: maxRisk === null ? '--' : String(maxRisk), sub: timeOfValue((p) => p.risk, maxRisk) },
    { label: 'TRIN 均值', value: avgTrin === null ? '--' : avgTrin.toFixed(2), sub: trins.length ? `共 ${trins.length} ${unit}` : '' },
  ]
})

function toggleTrendIndicator(key: TrendIndicatorKey) {
  const current = trendIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    trendIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    trendIndicators.value = TREND_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderTrendChart())
}

// ECharts 画布不解析 CSS 变量，渲染时取计算值（主题切换后下一次渲染生效）
function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// tooltip 内各序列的展示格式（fail-visible：null 显示 --）
const TREND_AXIS_FMT: Record<string, (v: number | null) => string> = {
  涨占比: (v) => (v === null ? '--' : `${v.toFixed(1)}%`),
  攻击: (v) => formatNullableCount(v),
  风险: (v) => formatNullableCount(v),
  TRIN: (v) => formatTrin(v),
  池规模: (v) => formatNullableCount(v),
}

// 阶段铺底：连续同阶段点合并成一段 markArea，≥2 点才显示阶段名，避免窄段文字挤压（两图表共用）
// 路线 B：stage 可为 null（证据全缺槽），该点中断连续段、不铺底
function buildStageMarkArea(
  points: Array<{ label: string; stage: string | null }>,
): Array<[Record<string, unknown>, Record<string, unknown>]> {
  const data: Array<[Record<string, unknown>, Record<string, unknown>]> = []
  let runStage = ''
  let runStart = ''
  let runEnd = ''
  let runLen = 0
  const flushRun = () => {
    const meta = STAGE_TREND_META[runStage]
    if (meta && runLen > 0) {
      data.push([
        {
          xAxis: runStart,
          itemStyle: { color: meta.bg },
          label: { show: runLen >= 2, position: 'insideTop', fontSize: 9, color: meta.fg, formatter: runStage },
        },
        { xAxis: runEnd },
      ])
    }
    runLen = 0
  }
  for (const p of points) {
    if (!p.stage) {
      flushRun()
      continue
    }
    if (runLen > 0 && p.stage === runStage) {
      runEnd = p.label
      runLen += 1
    } else {
      flushRun()
      runStage = p.stage
      runStart = p.label
      runEnd = p.label
      runLen = 1
    }
  }
  flushRun()
  return data
}

function renderTrendChart() {
  if (!trendChartRef.value || !trendPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (trendChart && trendChart.getDom() !== trendChartRef.value) {
    trendChart.dispose()
    trendChart = null
  }
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }

  const points = trendPoints.value
  const indicators = trendIndicators.value
  const series: any[] = []

  if (indicators.includes('upRatio')) {
    series.push({
      name: '涨占比',
      type: 'line',
      data: points.map((p) => p.upRatioPct),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { color: '#ff7f50', width: 2 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(255, 127, 80, 0.25)' },
          { offset: 1, color: 'rgba(255, 127, 80, 0)' },
        ]),
      },
      yAxisIndex: 0,
    })
  }
  if (indicators.includes('attack')) {
    series.push({
      name: '攻击',
      type: 'bar',
      data: points.map((p) => p.attack),
      itemStyle: { color: '#ff4757' },
      barWidth: 8,
      yAxisIndex: 1,
    })
  }
  if (indicators.includes('risk')) {
    series.push({
      name: '风险',
      type: 'bar',
      data: points.map((p) => p.risk),
      itemStyle: { color: '#2ed573' },
      barWidth: 8,
      yAxisIndex: 1,
    })
  }
  if (indicators.includes('trin')) {
    series.push({
      name: 'TRIN',
      type: 'line',
      data: points.map((p) => p.trin),
      smooth: true,
      connectNulls: false,
      lineStyle: { color: '#3498db', width: 1.5, type: 'dashed' },
      symbol: 'diamond',
      symbolSize: 4,
      yAxisIndex: 2,
    })
  }
  if (indicators.includes('pool')) {
    series.push({
      name: '池规模',
      type: 'line',
      data: points.map((p) => p.pool),
      smooth: true,
      connectNulls: false,
      symbol: 'none',
      lineStyle: { color: '#4a90e2', width: 1.5 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(74, 144, 226, 0.15)' },
          { offset: 1, color: 'rgba(74, 144, 226, 0)' },
        ]),
      },
      yAxisIndex: 3,
    })
  }

  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  trendChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          if (!list.length) return ''
          const point = points[list[0].dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = TREND_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage ?? '']?.fg || textColor
          const driftText = point.drift ? `（${point.drift}，当帧判定 ${point.driftRaw}）` : ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            `<div style="color:${stageColor};margin-bottom:4px;">阶段：${point.stage}${driftText}</div>`,
            rows,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: [
        {
          type: 'value',
          name: '涨占比%',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '数量',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: 'TRIN',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
        {
          type: 'value',
          name: '池规模',
          nameTextStyle: { color: textColor, fontSize: 9 },
          splitLine: { show: false },
          axisLabel: { color: textColor },
        },
      ],
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  trendChart.resize()
}

// 具名 handler：卸载时移除，避免面板反复开关累积监听器
function handleChartsResize() {
  if (trendChart) {
    trendChart.resize()
  }
  if (compareChart) {
    compareChart.resize()
  }
  if (layersChart) {
    layersChart.resize()
  }
  if (stageChart) {
    stageChart.resize()
  }
  if (jevChart) {
    jevChart.resize()
  }
}
onMounted(() => {
  window.addEventListener('resize', handleChartsResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', handleChartsResize)
  // 统一释放六图实例（函数声明提升，定义见脚本尾 visible watcher 前）
  disposeAllCharts()
})

// ── 相位验收（2026-09-30 前端可见化，设计 ranktrend-phase-frontend-design.md）──
// 口径锚 sentiment_2b（offense ≥60 / defense <60，2026-10-01 章程 Q1 边界 50→60），唯一口径源=phase_label_run CANDIDATES
const PHASE_THRESHOLD = 60

const phaseHistoryDays = ref<PhaseHistoryDay[]>([])
const phaseHistoryDegraded = ref(false)
const phaseHistoryReason = ref<string | null>(null)
const phaseNorthstar = ref<PhaseNorthstarDoc | null>(null)
const phasePulse = ref<PhasePulseDoc | null>(null)
const phasePulses = ref<PhasePulseDoc[]>([])
const phaseNorthstarMissingReason = ref<string | null>(null)
const phaseLoading = ref(false)
const phaseLoadedOnce = ref(false)
const phaseError = ref<string | null>(null)
const phaseChartEl = ref<HTMLElement | null>(null)
let phaseChartInstance: echarts.ECharts | null = null

const phaseChip = computed(() => {
  const score = emotionScoreValue.value
  if (score == null) return { kind: 'unknown', label: '相位不可用', title: '情绪分缺失，相位无法判定（fail-visible）' }
  return score >= PHASE_THRESHOLD
    ? { kind: 'offense', label: '🔥 进攻相位', title: `连续情绪分 ${score} ≥ ${PHASE_THRESHOLD}（sentiment_2b 进攻相位）` }
    : { kind: 'defense', label: '🛡️ 防守相位', title: `连续情绪分 ${score} < ${PHASE_THRESHOLD}（sentiment_2b 防守相位）` }
})

// 今日相位（第 8 页签页头用；与 overview chip 同源同口径=当前锁定文档情绪分）
const todayPhaseText = computed(() => {
  const score = emotionScoreValue.value
  if (score == null) return '暂不可用（情绪分缺失）'
  return `${score >= PHASE_THRESHOLD ? '进攻' : '防守'}（情绪分 ${score}）`
})

// 今日建议新仓仓位（C7 阶梯③：10-40 满/40-60 零/60+ 三成；口径源=execution.py
// phaseExposureControl ladder 模式，阈值变更两处同改；研究假设待 10 月脉拍验证）
const todayAdvice = computed(() => {
  const score = emotionScoreValue.value
  if (score == null) return '暂不可用'
  if (score < 40) return '满仓（冷带 10-40）'
  if (score < 60) return '不开新仓（弱势带 40-60）'
  return '三成（60+）'
})

const phasePulseText = computed(() => {
  const p = phasePulse.value?.report
  if (!p) return { value: '未跑', detail: '', detail2: '' }
  return { value: `${p.month}｜${p.tradeCount ?? 0} 笔`, detail: '', detail2: '' }
})

const pulseBands = computed(() => Object.entries(phasePulse.value?.report?.bands ?? {}).map(([tag, b]) => ({
  tag,
  trades: b?.trades ?? 0,
  avgPct: b?.avgPerTrade != null ? Number((b.avgPerTrade * 100).toFixed(2)) : null,
  sumPct: (b?.sumNetReturn ?? 0) * 100,
})))

// 渲染行：宽度按 |每笔收益| 归一化，红涨绿跌；弱势行挂徽标
const pulseBandRows = computed(() => {
  const rows = pulseBands.value.map((b) => ({
    ...b,
    weak: b.tag === '弱势40-60',
    color: (b.avgPct ?? 0) >= 0 ? '#ff4757' : '#2ed573',
    avgText: b.avgPct == null ? '--' : `${b.avgPct > 0 ? '+' : ''}${b.avgPct}%`,
  }))
  const maxAbs = Math.max(0.0001, ...rows.map((r) => Math.abs(r.avgPct ?? 0)))
  return rows.map((r) => ({ ...r, barPct: Math.round((Math.abs(r.avgPct ?? 0) / maxAbs) * 100) }))
})

const phasePulseAbLine = computed(() => {
  const ab = phasePulse.value?.report?.ab
  if (!ab || ab.degraded) return ''
  const avoided = ab.bandAvoided
  const delta = ab.delta
  return `A/B 阶梯仓位③（前日定相，champion）：${ab.baseline?.tradeCount ?? '--'} 笔 ${((ab.baseline?.sumNetReturn ?? 0) * 100).toFixed(1)}% → ${avoided?.tradeCount ?? '--'} 笔 ${((avoided?.sumNetReturn ?? 0) * 100).toFixed(1)}%（少亏 ${((delta?.netReturnSaved ?? 0) * 100).toFixed(1)}%）`
})

const phasePulseChallengerRows = computed(() => {
  const list = phasePulse.value?.report?.challengers ?? []
  return list.map((c) => ({
    name: c.name,
    degraded: !!c.degraded,
    reason: c.reason ?? null,
    tradeCount: c.stats?.tradeCount ?? null,
    sumPct: (c.stats?.sumNetReturn ?? 0) * 100,
    rebalance: c.attribution?.rebalanceCount ?? null,
  }))
})

interface PulseBandAccRow {
  month: string
  tradeCount: number
  cells: Array<{ tag: string; trades: number; avgPct: number | null }>
}

// C6 证据逐月累积表：每行=一个月的脉拍，列=三分带（每笔%着色，笔数附注）
const phasePulseAccRows = computed<PulseBandAccRow[]>(() =>
  phasePulses.value.map((doc) => {
    const bands = doc.report?.bands ?? {}
    return {
      month: doc.month,
      tradeCount: doc.report?.tradeCount ?? 0,
      cells: ['冷10-40', '弱势40-60', '强60-80'].map((tag) => ({
        tag,
        trades: bands[tag]?.trades ?? 0,
        avgPct: bands[tag]?.avgPerTrade != null ? Number((bands[tag].avgPerTrade * 100).toFixed(2)) : null,
      })),
    }
  }),
)

async function loadPhaseData(): Promise<void> {
  phaseLoading.value = true
  phaseError.value = null
  try {
    const [history, board] = await Promise.all([fetchPhaseHistory(), fetchPhaseMonitorBoard()])
    if (history.degraded) {
      phaseHistoryDegraded.value = true
      phaseHistoryReason.value = history.reason
      phaseHistoryDays.value = []
    } else {
      phaseHistoryDegraded.value = false
      phaseHistoryReason.value = null
      phaseHistoryDays.value = history.days
    }
    if ('degraded' in board) {
      phaseNorthstar.value = null
      phaseNorthstarMissingReason.value = board.reason
      phasePulse.value = null
    } else {
      phaseNorthstar.value = board.northstar
      phaseNorthstarMissingReason.value = board.northstarMissingReason ?? null
      phasePulse.value = board.pulse ?? null
      phasePulses.value = board.pulses ?? []
    }
  } catch (err) {
    phaseError.value = err instanceof Error ? err.message : '相位数据加载失败'
  } finally {
    phaseLoading.value = false
  }
}

async function ensurePhaseData(): Promise<void> {
  if (phaseLoadedOnce.value) return
  phaseLoadedOnce.value = true
  await loadPhaseData()
}

function renderPhaseChart(): void {
  if (!phaseChartEl.value || phaseHistoryDegraded.value || !phaseHistoryDays.value.length) return
  // 空态 v-if/面板重开会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (phaseChartInstance && phaseChartInstance.getDom() !== phaseChartEl.value) {
    phaseChartInstance.dispose()
    phaseChartInstance = null
  }
  if (!phaseChartInstance) {
    phaseChartInstance = echarts.init(phaseChartEl.value)
  }
  // 时间线窗口：只保留近 3 个月（2026-09-30 用户裁决；全量 113 日仍在 phase-history 读口与标签产物里）
  const PHASE_CHART_MONTHS = 3
  const allDays = phaseHistoryDays.value
  const latest = allDays.length ? allDays[allDays.length - 1]!.tradingDate : ''
  let cutoff = ''
  if (latest) {
    const d0 = new Date(`${latest}T00:00:00`)
    d0.setMonth(d0.getMonth() - PHASE_CHART_MONTHS)
    cutoff = `${d0.getFullYear()}-${String(d0.getMonth() + 1).padStart(2, '0')}-${String(d0.getDate()).padStart(2, '0')}`
  }
  const days = cutoff ? allDays.filter((d) => d.tradingDate >= cutoff) : allDays
  if (!days.length) return
  const areas: Array<[{ xAxis: string }, { xAxis: string }]> = []
  let startIdx = -1
  for (let i = 0; i <= days.length; i++) {
    const d = days[i]
    const colored = !!d && (d.phase === 'offense' || d.phase === 'defense')
    if (startIdx >= 0 && (!colored || d!.phase !== days[startIdx]!.phase)) {
      areas.push([{ xAxis: days[startIdx]!.tradingDate }, { xAxis: days[i - 1]!.tradingDate }])
      startIdx = -1
    }
    if (colored && startIdx < 0) startIdx = i
  }
  phaseChartInstance.setOption({
    grid: { left: 48, right: 16, top: 24, bottom: 56 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: Array<{ name: string; value: number | null; axisValue: string }>) => {
        const p = params[0]
        const day = days.find((d) => d.tradingDate === p.axisValue)
        const phaseName = day?.phase === 'offense' ? '进攻' : day?.phase === 'defense' ? '防守' : '不可用'
        return `${p.axisValue}<br/>情绪分 ${p.value ?? '--'}<br/>相位：${phaseName}`
      },
    },
    xAxis: { type: 'category', data: days.map((d) => d.tradingDate), axisLabel: { rotate: 45, fontSize: 9 } },
    yAxis: { type: 'value', min: 0, max: 100, name: 'EOD 情绪分' },
    series: [
      {
        name: 'EOD 情绪分',
        type: 'line',
        data: days.map((d) => d.eodScore),
        connectNulls: false,
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#8b7cf6' },
        markLine: {
          symbol: 'none',
          silent: true,
          // 弱势区间 40-60（2026-10-01 用户定义；分带测算该带逐月皆亏）
          data: [
            { yAxis: 40, lineStyle: { color: '#d97706', type: 'dashed' }, label: { formatter: '40' } },
            { yAxis: 60, lineStyle: { color: '#d97706', type: 'dashed' }, label: { formatter: '60' } },
          ],
        },
        markArea: {
          silent: true,
          data: [
            // 弱势带横向底色（40-60）
            [
              { yAxis: 40, itemStyle: { color: 'rgba(217,119,6,0.07)' } },
              { yAxis: 60, itemStyle: { color: 'rgba(217,119,6,0.07)' } },
            ],
            // 相位着色段（xAxis 段，研究口径）
            ...areas.map(([a, b]) => [
              { xAxis: a.xAxis, itemStyle: { color: 'rgba(239,68,68,0.08)' } },
              { xAxis: b.xAxis, itemStyle: { color: 'rgba(239,68,68,0.08)' } },
            ]),
          ],
        },
      },
    ],
  })
}

// 页签进入或数据刷新时渲染（v-show 切换后需等 nextTick 拿到可见容器尺寸）
watch(view, (v) => {
  if (v === 'track' && trendPoints.value.length) {
    nextTick(() => renderTrendChart())
  }
  if (v === 'compare' && comparePoints.value.length) {
    nextTick(() => renderCompareChart())
  }
  if (v === 'layers' && layerPoints.value.length) {
    nextTick(() => renderLayersChart())
  }
  if (v === 'structure' && stagePieData.value.length) {
    nextTick(() => renderStageChart())
  }
  if (v === 'phase') {
    void ensurePhaseData().then(() => nextTick(() => renderPhaseChart()))
  }
})
watch(trendPoints, () => {
  if (view.value === 'track') {
    nextTick(() => renderTrendChart())
  }
})
watch(comparePoints, () => {
  if (view.value === 'compare') {
    nextTick(() => renderCompareChart())
  }
})
watch(layerPoints, () => {
  if (view.value === 'layers') {
    nextTick(() => renderLayersChart())
  }
})
watch(stagePieData, () => {
  if (view.value === 'structure') {
    nextTick(() => renderStageChart())
  }
})
// phase 数据到达即渲染（2026-10-01 补）：重试成功路径只更新 phaseHistoryDays，
// view/visible watcher 均不触发 → 无人渲染，容器挂载后空白（同族 BUG 一并修）
watch(phaseHistoryDays, () => {
  if (view.value === 'phase') {
    nextTick(() => renderPhaseChart())
  }
})

// 多日窗口注记（历史对比/情绪趋势多日档共用）：日期区间 + 口径 + 缺失日标注
function dailyRangeNote(pts: Array<{ label: string }>): string {
  const rangeLabel = pts.length > 1 ? `${pts[0].label} ~ ${pts[pts.length - 1].label}` : pts[0].label
  const missingSuffix = seriesMissingDays.value.length ? ` · 窗口缺失 ${seriesMissingDays.value.length} 日` : ''
  return `${rangeLabel} · 日线口径（EOD 终值）${missingSuffix}`
}

const trackNote = computed(() => {
  if (seriesLoading.value) return '正在加载多日序列…'
  // 取数失败只在所选窗口无法满足时提示，不影响已加载窗口的正常展示
  if (seriesError.value && RANGE_DAYS[timeRange.value] > seriesDaysLoaded.value) {
    return `多日序列不可用：${seriesError.value}`
  }
  if (!trendPoints.value.length) return ''
  if (timeRange.value === '1d') {
    if (slotsDegradedReason.value) return slotsDegradedReason.value
    return slotsTradingDate.value ? `${slotsTradingDate.value} · 每半小时一帧，随采集更新` : ''
  }
  return dailyRangeNote(trendPoints.value)
})

// ---------- jev 观察轨道图表（2026-09-30：卡片网格改 ECharts，语言同情绪趋势页签） ----------
// 1天=日内逐槽（序列档 sequence_stage + temperature/crowding/置信）；
// 3日/1周/1月=日线 EOD 日级总体（day_stage + day_temperature/day_crowding/day_stage 置信）。
// 三维度（2026-10-02 用户裁决）：温度紫柱/拥挤度黄柱/置信蓝线——
// 拥挤度=拥挤三层概率合计（v2 离散归层无连续分，旧「拥挤橙柱」按 0-100 分读 score 恒 null 是死序列，深化文档 G2）；
// 置信=序列档/日级档模型 confidence；缺分布/降级/无数据一律 null 不渲染断线，状态与错误码进 tooltip，不伪造 0。
const jevChartRef = ref<HTMLElement | null>(null)
let jevChart: echarts.ECharts | null = null
const jevTimeRange = ref<TrendTimeRange>('1d')
const JEV_INDICATORS = [
  { key: 'temperature', label: '温度', icon: '🌡️' },
  { key: 'crowding', label: '拥挤度', icon: '🧲' },
  { key: 'confidence', label: '置信', icon: '🎯' },
] as const
type JevIndicatorKey = (typeof JEV_INDICATORS)[number]['key']
const jevIndicators = ref<JevIndicatorKey[]>(['temperature', 'crowding', 'confidence'])

// 多日 jev 窗口缓存（与情绪趋势 seriesDocs 同款代际守卫；缺失日结构化收集不吞掉）
const jevDayDocs = ref<HotlistJevDayEntry[]>([])
const jevDaysLoaded = ref(0)
const jevMissingDays = ref<HotlistJevMissingDay[]>([])
const jevSeriesError = ref<string | null>(null)
const jevSeriesLoading = ref(false)
let jevSeriesReqId = 0

async function ensureJevDays(days: number) {
  if (days <= jevDaysLoaded.value) return
  const reqId = ++jevSeriesReqId
  jevSeriesLoading.value = true
  jevSeriesError.value = null
  try {
    const result = await fetchHotlistJevRange(days)
    if (reqId !== jevSeriesReqId) return
    if (result.degraded) {
      jevSeriesError.value = result.reason || 'jev 多日序列不可用'
    } else {
      jevDayDocs.value = result.days
      jevDaysLoaded.value = days
      jevMissingDays.value = result.missingDays
    }
  } catch (err) {
    if (reqId !== jevSeriesReqId) return
    jevSeriesError.value = err instanceof Error ? err.message : '加载 jev 多日序列失败'
  } finally {
    if (reqId === jevSeriesReqId) jevSeriesLoading.value = false
  }
}

async function setJevTimeRange(range: TrendTimeRange) {
  if (jevTimeRange.value === range) return
  jevTimeRange.value = range
  await ensureJevDays(RANGE_DAYS[range])
  nextTick(() => renderJevChart())
}

function toggleJevIndicator(key: JevIndicatorKey) {
  const current = jevIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白
    jevIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    jevIndicators.value = JEV_INDICATORS.map((i) => i.key).filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderJevChart())
}

interface JevPoint {
  /** 选中态键：1天=slotTime，多日=tradingDate（图表点选 ↔ 详情卡联动） */
  key: string
  label: string
  title: string
  /** 序列档（1天）或日级档（多日）中文档位；缺失为 ''（铺底跳过，tooltip 显示档位缺失） */
  stage: string
  /** 日线路径形态（仅多日档，day_pattern） */
  pattern: string
  temperature: number | null
  /** 拥挤度（0-100）=拥挤三层概率合计（模型认为市场处于任一拥挤层的总概率）；缺分布为 null */
  crowding: number | null
  /** 归层判定中文名（tooltip 透出；与柱高口径不同：柱高=三层合计，归层=argmax 单层） */
  crowdingLayer: string | null
  /** 归层是否毒层（top_acceleration/late_seal_weakness） */
  crowdingWarn: boolean
  /** 拥挤三层概率分解文本（如「高位加速 21% + 封板弱化 6%」；缺分布 ''） */
  crowdingBreakdown: string
  /** 模型置信（0-100，序列档/日级档 answer.confidence；缺失 null） */
  confidence: number | null
  /** 档位 top 概率（0-100；tooltip 附注 + 犹豫标记；缺失 null） */
  stageProbability: number | null
  degraded: boolean
  noData: boolean
  /** 降级/无数据/日级未生成的结构化状态（进 tooltip，不伪造分数） */
  statusText: string
}

/** 0-1 概率 → 0-100 图表刻度（缺失 null 透传，不伪造 0；保留 1 位小数去浮点噪声） */
function scale100(value: number | null): number | null {
  return value == null ? null : Math.round(value * 1000) / 10
}

/**
 * 拥挤度柱信息（展示投影）：probability=拥挤三层概率合计（jevCrowdingProbability），
 * 归层判定/毒层警示/三层分解供 tooltip 透出——柱高与归层判定口径不同（合计 vs argmax 单层），两者同屏防误读。
 */
function jevCrowdingPointInfo(
  doc: HotlistJevDoc | null | undefined,
  key: string,
): { probability: number | null; layerName: string | null; warn: boolean; breakdown: string } {
  const answer = doc?.answers?.[key]
  const choice = answer && answer.type === 'choice' ? answer.choice ?? null : null
  const probabilities = answer && answer.type === 'choice' ? answer.probabilities ?? null : null
  const breakdown = !probabilities
    ? ''
    : JEV_CROWDING_LAYERS
        .map((layer) => ({ name: JEV_CROWDING_NAMES[layer] ?? layer, value: probabilities[layer] }))
        .filter((entry): entry is { name: string; value: number } => typeof entry.value === 'number')
        .map((entry) => `${entry.name} ${Math.round(entry.value * 100)}%`)
        .join(' + ')
  return {
    probability: jevCrowdingProbability(doc, key),
    layerName: choice ? (JEV_CROWDING_NAMES[choice] ?? choice) : null,
    warn: choice != null && JEV_CROWDING_WARN_LAYERS.has(choice),
    breakdown,
  }
}

const jevPoints = computed<JevPoint[]>(() => {
  if (jevTimeRange.value === '1d') {
    return jevSlots.value.map((slot, index) => {
      const degraded = slot.status === 'degraded'
      const noData = slot.status === 'no_data'
      const crowd = jevCrowdingPointInfo(slot, 'crowding')
      return {
        key: slot.slotTime || `slot-${index}`,
        label: slot.slotTime || '--',
        title: slot.slotTime || '--',
        stage: jevChoiceName(slot, 'sequence_stage') || '',
        pattern: '',
        temperature: jevScore(slot, 'temperature'),
        crowding: scale100(crowd.probability),
        crowdingLayer: crowd.layerName,
        crowdingWarn: crowd.warn,
        crowdingBreakdown: crowd.breakdown,
        confidence: scale100(jevChoiceConfidence(slot, 'sequence_stage')),
        stageProbability: scale100(jevChoiceProbability(slot, 'sequence_stage')),
        degraded,
        noData,
        statusText: degraded
          ? `降级：${slot.errorCode || ''} ${slot.errorDetail || ''}`.trim()
          : noData
            ? '无数据'
            : '',
      }
    })
  }
  return jevDayDocs.value.map((day, index) => {
    const eod = day.eod
    const crowd = jevCrowdingPointInfo(eod, 'day_crowding')
    return {
      key: day.tradingDate || `d-${index}`,
      label: (day.tradingDate || '').slice(5) || '--',
      title: day.tradingDate || '--',
      stage: eod ? jevChoiceName(eod, 'day_stage') || '' : '',
      pattern: eod ? jevChoiceName(eod, 'day_pattern') || '' : '',
      temperature: eod ? jevScore(eod, 'day_temperature') : null,
      crowding: scale100(crowd.probability),
      crowdingLayer: crowd.layerName,
      crowdingWarn: crowd.warn,
      crowdingBreakdown: crowd.breakdown,
      confidence: scale100(jevChoiceConfidence(eod, 'day_stage')),
      stageProbability: scale100(jevChoiceProbability(eod, 'day_stage')),
      degraded: false,
      noData: !eod,
      statusText: eod ? '' : '日级总体未生成',
    }
  })
})

// 图下统计卡（同 trendStats 语言：均值带样本数、峰值带时间，缺失 '--'）
const jevStats = computed(() => {
  const pts = jevPoints.value
  const unit = jevTimeRange.value === '1d' ? '槽' : '日'
  const card = (
    label: string,
    pick: (p: JevPoint) => number | null,
    stat: 'avg' | 'peak' | 'min',
    suffix = '',
  ) => {
    const nums = pts.map(pick).filter((v): v is number => v !== null)
    if (!nums.length) return { label, value: '--', sub: '' }
    if (stat === 'avg') {
      const avg = nums.reduce((a, b) => a + b, 0) / nums.length
      return { label, value: `${avg.toFixed(0)}${suffix}`, sub: `共 ${nums.length} ${unit}` }
    }
    const value = stat === 'peak' ? Math.max(...nums) : Math.min(...nums)
    return { label, value: `${value}${suffix}`, sub: pts.find((p) => pick(p) === value)?.label || '' }
  }
  return [
    card('平均温度', (p) => p.temperature, 'avg'),
    card('温度峰值', (p) => p.temperature, 'peak'),
    // 拥挤度/置信是概率口径（0-100%），与温度分值（0-100 分）单位不同，带 % 后缀防混读
    card('平均拥挤度', (p) => p.crowding, 'avg', '%'),
    card('拥挤度峰值', (p) => p.crowding, 'peak', '%'),
    card('平均置信', (p) => p.confidence, 'avg', '%'),
    card('最低置信', (p) => p.confidence, 'min', '%'),
  ]
})

// 版本分段守卫（2026-10-02 用户裁决）：窗口内文档题目版本不一致时显式标注；含未知口径
// 旧文档（含整窗旧代产物、1d 档 EOD 与槽位异代）同样标注。判据随版本漂移（实测 7/8/9 月
// 拥挤三层概率合计均值 0.088/0.207/0.416），跨版本对比无效
const jevVersionNote = computed(() => {
  const docs: HotlistJevDoc[] = jevTimeRange.value === '1d'
    ? [...jevSlots.value, ...(jevEod.value ? [jevEod.value] : [])]
    : jevDayDocs.value.map((day) => day.eod).filter((eod): eod is HotlistJevDoc => !!eod)
  if (!docs.length) return ''
  const versions = new Set(docs.map((doc) => doc.questionSetVersion || '未知口径'))
  if (versions.size > 1) {
    return `⚠️ 窗口跨题目判据版本（${[...versions].join('/')}），跨版本对比无效`
  }
  return versions.has('未知口径') ? '⚠️ 窗口文档缺题目版本号（旧代产物，判据口径未知）' : ''
})

const jevNote = computed(() => {
  if (jevSeriesLoading.value) return '正在加载 jev 多日序列…'
  // 取数失败只在所选窗口无法满足时提示，不影响已加载窗口的正常展示
  if (jevSeriesError.value && RANGE_DAYS[jevTimeRange.value] > jevDaysLoaded.value) {
    return `jev 多日序列不可用：${jevSeriesError.value}`
  }
  if (!jevPoints.value.length) return ''
  const versionSuffix = jevVersionNote.value ? ` · ${jevVersionNote.value}` : ''
  if (jevTimeRange.value === '1d') {
    const abnormal = jevSlots.value.filter(
      (s) => s.status === 'degraded' || s.status === 'no_data',
    ).length
    const base = jevSeriesDate.value ? `${jevSeriesDate.value} · 逐槽 AI 评判` : '逐槽 AI 评判'
    const text = abnormal ? `${base} · 异常 ${abnormal} 槽` : base
    return `${text}${versionSuffix}`
  }
  const labels = jevPoints.value.map((p) => p.label)
  const rangeLabel = labels.length > 1 ? `${labels[0]} ~ ${labels[labels.length - 1]}` : labels[0]
  const missingSuffix = jevMissingDays.value.length ? ` · 窗口缺失 ${jevMissingDays.value.length} 日` : ''
  return `${rangeLabel} · 日线口径（EOD 日级总体）${missingSuffix}${versionSuffix}`
})

// tooltip 数值格式（fail-visible：null 显示 --；拥挤度/置信为概率口径带 %）
const JEV_AXIS_FMT: Record<string, (v: number | null) => string> = {
  温度: (v) => (v === null ? '--' : String(Math.round(v))),
  拥挤度: (v) => (v === null ? '--' : `${Math.round(v)}%`),
  置信: (v) => (v === null ? '--' : `${Math.round(v)}%`),
}

function renderJevChart() {
  if (!jevChartRef.value || !jevPoints.value.length) return
  // 空态 v-if 切换会卸载并重挂图表容器：旧实例绑定的 DOM 已分离，必须 dispose 后重建
  if (jevChart && jevChart.getDom() !== jevChartRef.value) {
    jevChart.dispose()
    jevChart = null
  }
  if (!jevChart) {
    jevChart = echarts.init(jevChartRef.value)
  }

  const points = jevPoints.value
  const series: any[] = []
  // 三维度语言（2026-10-02 用户裁决）：温度紫柱 / 拥挤度黄柱 / 置信蓝线；
  // 分数/概率 null 的槽/日柱体与点不渲染（不伪造 0），拥挤度是概率口径非旧 0-100 连续分
  if (jevIndicators.value.includes('temperature')) {
    series.push({
      name: '温度', type: 'bar',
      data: points.map((p) => p.temperature),
      itemStyle: { color: '#9b59b6' },
      barWidth: 8,
    })
  }
  if (jevIndicators.value.includes('crowding')) {
    series.push({
      name: '拥挤度', type: 'bar',
      data: points.map((p) => p.crowding),
      itemStyle: { color: '#f1c40f' },
      barWidth: 8,
    })
  }
  if (jevIndicators.value.includes('confidence')) {
    series.push({
      name: '置信', type: 'line', smooth: true, connectNulls: false,
      data: points.map((p) => p.confidence),
      lineStyle: { color: '#4a90e2', width: 2 },
      itemStyle: { color: '#4a90e2' },
      symbol: 'circle', symbolSize: 5,
    })
  }
  // 序列/日级档位铺底：jev 五档与规则轨道同词汇，直接复用 STAGE_TREND_META 冷热语义色
  if (series.length) {
    series[0].markArea = { silent: true, data: buildStageMarkArea(points) }
  }

  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')

  jevChart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '10%', containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params]
          const point = points[list[0]?.dataIndex]
          if (!point) return ''
          const rows = list
            .map((it: any) => {
              const fmt = JEV_AXIS_FMT[it.seriesName]
              const value = typeof it.value === 'object' ? it.value?.value : it.value
              return `<div>${it.marker}${it.seriesName}：${fmt ? fmt(value ?? null) : String(value)}</div>`
            })
            .join('')
          const stageColor = STAGE_TREND_META[point.stage ?? '']?.fg || textColor
          const stageLine = `<div style="color:${stageColor};margin-bottom:4px;">档位：${point.stage || '缺失'}</div>`
          const patternLine = point.pattern ? `<div style="margin-bottom:4px;">路径：${point.pattern}</div>` : ''
          // 拥挤度柱高=拥挤三层概率合计，与归层判定（argmax 单层）口径不同，两者同透出防误读
          const crowdLine = point.crowdingLayer
            ? `<div style="color:${textColor};">归层：${point.crowdingLayer}${point.crowdingWarn ? ' ⚠️毒层' : ''}${point.crowdingBreakdown ? `（${point.crowdingBreakdown}）` : ''}</div>`
            : ''
          const confLine = point.stageProbability != null
            ? `<div style="color:${textColor};">档位 P ${Math.round(point.stageProbability)}%${point.stageProbability < 60 ? ' · ⚠️犹豫' : ''}</div>`
            : ''
          const statusLine = point.statusText
            ? `<div style="color:#f39c12;margin-bottom:4px;">${point.statusText}</div>`
            : ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.title}</div>`,
            stageLine,
            patternLine,
            statusLine,
            rows,
            crowdLine,
            confLine,
          ].join('')
        },
      },
      legend: {
        data: series.map((s) => s.name),
        bottom: 0,
        itemWidth: 12,
        itemHeight: 8,
        textStyle: { color: textColor, fontSize: 10 },
      },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        name: '分值 / 概率（0-100）',
        nameTextStyle: { color: textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
        axisLabel: { color: textColor },
      },
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留
    { notMerge: true },
  )
  // 点选联动：选中槽位/日期驱动详情卡（off 先行避免重复渲染累积 handler）
  jevChart.off('click')
  jevChart.on('click', (params: any) => {
    const point = points[params.dataIndex]
    if (point) selectedJevKey.value = point.key
  })
  jevChart.resize()
}

// ---------- jev 详情卡（2026-09-30 用户裁决：常驻图表下方，默认选最新帧；概率条两档都展示） ----------
const selectedJevKey = ref<string | null>(null)

interface JevChoiceRow {
  key: string
  name: string
  pct: number | null
  color: string
}

interface JevChoiceDetail {
  key: string
  label: string
  choiceName: string | null
  tone: string
  confidence: number | null
  probability: number | null
  rows: JevChoiceRow[]
}

// 档位色沿用阶段铺底冷热语义；路径形态无冷热语义用中性蓝
const jevStageTone = (name: string) => STAGE_TREND_META[name]?.fg || '#9aa0a6'

function buildJevChoiceDetail(
  key: string,
  label: string,
  doc: HotlistJevDoc | null,
  order: readonly string[],
  nameMap: Record<string, string>,
  colorOf: (name: string) => string,
): JevChoiceDetail {
  const answer = doc?.answers?.[key]
  const choice = answer && answer.type === 'choice' ? answer.choice ?? null : null
  const probabilities = answer && answer.type === 'choice' ? answer.probabilities ?? {} : {}
  const confidence =
    answer && answer.type === 'choice' && typeof answer.confidence === 'number' ? answer.confidence : null
  // 概率行按规范顺序展开（五档冷→热 / 七类路径），缺失键不伪造 0（pct=null 显示 --）
  const rows: JevChoiceRow[] = order
    .filter((k) => k in probabilities || k === choice)
    .map((k) => {
      const name = nameMap[k] ?? k
      const value = probabilities[k]
      return {
        key: k,
        name,
        pct: typeof value === 'number' ? Math.round(value * 1000) / 10 : null,
        color: colorOf(name),
      }
    })
  const top = choice != null ? probabilities[choice] : undefined
  return {
    key,
    label,
    choiceName: choice != null ? nameMap[choice] ?? choice : null,
    tone: choice != null ? colorOf(nameMap[choice] ?? choice) : '',
    confidence,
    probability: typeof top === 'number' ? top : null,
    rows,
  }
}

const jevDetail = computed(() => {
  const pts = jevPoints.value
  if (!pts.length) return null
  // 默认选最新帧；跨档位切回时选中键失配回落最新（如 1天档选 15:00 后切 3日档 → 最新日）
  const point = pts.find((p) => p.key === selectedJevKey.value) ?? pts[pts.length - 1]
  const isDay = jevTimeRange.value !== '1d'
  const doc = isDay
    ? jevDayDocs.value.find((d) => d.tradingDate === point.key)?.eod ?? null
    : jevSlots.value.find((s) => s.slotTime === point.key) ?? null

  const choices = isDay
    ? [
        buildJevChoiceDetail('day_stage', '日级档位', doc, JEV_STAGE_ORDER, JEV_STAGE_NAMES, jevStageTone),
        buildJevChoiceDetail('day_pattern', '路径形态', doc, JEV_PATTERN_ORDER, JEV_PATTERN_NAMES, () => '#4a90e2'),
      ]
    : [
        buildJevChoiceDetail('frame_stage', '当前帧档位', doc, JEV_STAGE_ORDER, JEV_STAGE_NAMES, jevStageTone),
        buildJevChoiceDetail('sequence_stage', '日内序列档位', doc, JEV_STAGE_ORDER, JEV_STAGE_NAMES, jevStageTone),
      ]
  const scores = isDay
    ? [
        { label: '日级温度', value: doc ? jevScore(doc, 'day_temperature') : null },
        { label: '日级拥挤', value: doc ? jevScore(doc, 'day_crowding') : null },
      ]
    : [
        { label: '温度', value: doc ? jevScore(doc, 'temperature') : null },
        { label: '拥挤', value: doc ? jevScore(doc, 'crowding') : null },
      ]

  // 质量注记（fail-visible）：文档缺失/降级错误码/源缺失逐条透出，不吞掉
  const qualityNotes: string[] = []
  if (!doc) {
    qualityNotes.push('该帧 jev 文档缺失')
  } else {
    if (doc.status === 'degraded') {
      qualityNotes.push(`降级：${doc.errorCode || ''} ${doc.errorDetail || ''}`.trim())
    }
    if (doc.status === 'no_data') {
      qualityNotes.push(`无数据：${doc.errorDetail || ''}`.trim())
    }
    for (const item of doc.quality?.degradedSources ?? []) qualityNotes.push(item)
  }
  const usage = doc?.usage ?? null
  const tokens =
    usage && typeof usage.input_tokens === 'number' && typeof usage.output_tokens === 'number'
      ? `tok ${usage.input_tokens}/${usage.output_tokens}`
      : ''
  return {
    key: point.key,
    title: isDay ? `${point.title} · 日级总体（EOD）` : `${point.title} · 槽位评判`,
    status: doc?.status ?? null,
    model: doc?.model ?? null,
    computedLabel: doc?.computedAt
      ? new Date(doc.computedAt * 1000).toLocaleTimeString('zh-CN', { hour12: false })
      : '',
    latencyMs: doc?.latencyMs ?? null,
    tokens,
    choices,
    scores,
    qualityNotes,
  }
})

// 页签进入或数据刷新时渲染（独立页签 v-show 切换后需等 nextTick 拿到可见容器尺寸；
// 图表容器随空态 v-if 重挂需 dispose 重建）
watch(jevPoints, () => {
  if (view.value === 'jev') {
    nextTick(() => renderJevChart())
  }
})
watch(view, (v) => {
  if (v === 'jev' && jevPoints.value.length) {
    nextTick(() => renderJevChart())
  }
  if (v === 'jev') {
    void loadReviewList()
    void loadJiuyanAction()
  }
})

// 统一释放六图实例（2026-10-01）：面板关闭即随根 v-if 销毁容器 DOM，旧实例留着只会对已分离 DOM
// 响应 window resize 产生无害告警；onUnmounted 兜底（原先漏 phase 实例）
function disposeAllCharts(): void {
  trendChart?.dispose()
  compareChart?.dispose()
  layersChart?.dispose()
  stageChart?.dispose()
  jevChart?.dispose()
  phaseChartInstance?.dispose()
  trendChart = null
  compareChart = null
  layersChart = null
  stageChart = null
  jevChart = null
  phaseChartInstance = null
}

// 面板重开补渲染（2026-10-01）：面板根 v-if 关闭时销毁全部图表容器 DOM，而页签与缓存数据不变、
// 上方 view/数据 watcher 均不触发 → 重开停在图表页签时画布空白；打开后按当前页签补一次渲染
//（关闭时实例已统一释放，重开由各渲染器重建；phase 由本次补齐守卫）
watch(() => props.visible, (visible) => {
  if (!visible) {
    disposeAllCharts()
    return
  }
  nextTick(() => {
    if (view.value === 'track' && trendPoints.value.length) renderTrendChart()
    if (view.value === 'compare' && comparePoints.value.length) renderCompareChart()
    if (view.value === 'layers' && layerPoints.value.length) renderLayersChart()
    if (view.value === 'structure' && stagePieData.value.length) renderStageChart()
    if (view.value === 'phase') void ensurePhaseData().then(() => nextTick(() => renderPhaseChart()))
    if (view.value === 'jev' && jevPoints.value.length) renderJevChart()
  })
})
</script>

<style scoped>
/* ========== 面板基础（token 对齐 SectorPanel/SectorDetail，2026-09-24 重写） ========== */
.hotlist-emotion-panel {
  position: fixed;
  width: 960px;
  max-width: calc(100vw - 40px);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 10006;
  font-size: 12px;
  overflow: hidden;
  backdrop-filter: blur(10px);
  color: var(--text-primary);
}

/* ========== 头部 ========== */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-header);
}
.header-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--color-highlight);
  display: flex;
  align-items: center;
  gap: 8px;
}
.version-badge {
  font-size: 10px;
  background: var(--color-highlight);
  color: #000;
  padding: 2px 6px;
  border-radius: 12px;
}
.time-badge {
  font-size: 10px;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  padding: 2px 6px;
  border-radius: 12px;
  cursor: help;
}
.time-badge.warn { color: #ff4757; }
.panel-actions { display: flex; gap: 8px; }
.btn-icon {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-color);
  background: transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-icon:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--color-highlight);
}
.btn-icon:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-icon.loading .rotate-animation { display: inline-block; animation: he-rotate 1s linear infinite; }
@keyframes he-rotate { to { transform: rotate(360deg); } }

/* ========== 页签 ========== */
.panel-tabs {
  display: flex;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}
.tabs-left { display: flex; gap: 4px; flex: 1; }
.tab-btn {
  flex: 1;
  padding: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: 8px;
  font-size: 12px;
  transition: all 0.2s;
}
.tab-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.tab-btn.active { background: var(--color-highlight); color: #000; font-weight: 500; }

/* ========== 内容区 ========== */
.panel-content {
  padding: 20px;
  max-height: calc(80vh - 120px);
  overflow-y: auto;
}
.tab-pane { display: flex; flex-direction: column; gap: 16px; }
.state-block {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 16px; padding: 60px 20px; color: var(--text-secondary);
}
.state-block.error { color: #ff4757; }
.spinner {
  width: 40px; height: 40px; border: 3px solid var(--border-color);
  border-top-color: var(--color-highlight); border-radius: 50%;
  animation: he-rotate 0.8s linear infinite;
}
.retry-btn {
  background: var(--color-highlight); color: #000; border: none;
  border-radius: 16px; padding: 4px 12px; cursor: pointer; font-size: 12px;
}

/* ========== 概览：阶段主卡（info-card 语言） ========== */
.stage-hero {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left-width: 4px;
  border-radius: 12px;
  padding: 16px;
}
/* 情绪冷热左色条（SectorPanel market-phase-card 语言）：hot红/warm琥珀/cold灰 */
.stage-tone-hot { border-left-color: #ff4757; }
.stage-tone-warm { border-left-color: #ffb142; }
.stage-tone-cold { border-left-color: #7f8c8d; }
.hero-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.hero-stage { font-size: 28px; font-weight: bold; color: var(--text-title); line-height: 1.2; margin-bottom: 8px; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.risk-chip, .conf-chip, .pending-chip {
  font-size: 10px; border-radius: 10px; padding: 2px 8px; display: inline-block;
}
.risk-high { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
.risk-mid { background: rgba(255, 177, 66, 0.15); color: #ffb142; }
.risk-low { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.conf-chip { background: var(--bg-primary); border: 1px solid var(--border-color); color: var(--text-secondary); }
.pending-chip {
  background: rgba(255, 177, 66, 0.15);
  color: #ffb142;
  cursor: help;
}
/* 路线 B 连续情绪分（hero 通栏分数条）：数值 + 0-100 进度条 + 可分解 tooltip */
.hero-score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  cursor: help;
}
.hero-score-num {
  font-size: 16px;
  font-weight: bold;
  color: var(--text-title);
  min-width: 34px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.hero-score-track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  overflow: hidden;
}
.hero-score-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #7f8c8d, #ffb142 60%, #ff4757);
}
.hero-score-hint { font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.overview-gauge .hero-score-fill.overview-fill {
  background: linear-gradient(90deg, #2e86de, #54a0ff 60%, #48dbfb);
}
.overview-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
.overview-chip {
  font-size: 10px; padding: 1px 6px; border-radius: 8px;
  border: 1px solid var(--border-color, #d0d0d0); color: var(--text-secondary);
}
.overview-chip-warn { color: #ff6b6b; border-color: #ff6b6b; }
.overview-chip-muted { opacity: 0.65; }
.hero-score-missing .hero-score-hint { color: #7f8c8d; }
.hero-summary { font-size: 12px; color: var(--text-secondary); }

/* ========== 三级卡片体系（SectorDetail 概览结构） ========== */
/* 主指标 4 列大卡：横向 + 48px 圆形图标底座 */
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}
.metric-icon {
  font-size: 28px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 24px;
  flex-shrink: 0;
}
.metric-content { flex: 1; min-width: 0; }
.metric-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: bold; line-height: 1.2; font-variant-numeric: tabular-nums; }
.metric-value.up { color: #ff4757; }
.metric-value.down { color: #2ed573; }
.metric-unit { font-size: 11px; font-weight: normal; color: var(--text-secondary); margin-left: 2px; }
/* 阶段迁移卡（metric-card 语言，3×2） */
.transition-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
/* 池换手汇总卡（同迁移卡语言，5 列一行） */
.turnover-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }

/* 资金/证据中卡 3-4 列：横向 + 32px 圆形底座 */
.funds-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.fund-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.fund-icon {
  font-size: 20px;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  border-radius: 16px;
  flex-shrink: 0;
}
.fund-content { flex: 1; min-width: 0; }
.fund-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 2px; }
.fund-value { font-size: 14px; font-weight: bold; font-variant-numeric: tabular-nums; }
.fund-value.up { color: #ff4757; }
.fund-value.down { color: #2ed573; }

/* 涨停证据容器网格：交集 4 列 / 全市场背景与昨日表现 6 列 */
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }

/* 统计小卡 4 列：竖排居中 */
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}
.stat-icon { font-size: 18px; margin-bottom: 4px; }
.stat-value { font-size: 18px; font-weight: bold; color: var(--text-title); font-variant-numeric: tabular-nums; }
.stat-value.up { color: #ff4757; }
.stat-value.down { color: #2ed573; }
.stat-label { font-size: 10px; color: var(--text-secondary); margin-top: 2px; text-align: center; }

/* ========== 子块（leaders-section 语言） ========== */
.sub-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
}
.block-title { font-size: 14px; font-weight: 500; color: var(--text-title); margin-bottom: 12px; }
/* 热榜概览三容器可点击（sector-card 悬浮语言） */
.sub-block.clickable { cursor: pointer; transition: all 0.2s; }
.sub-block.clickable:hover {
  transform: translateY(-2px);
  border-color: var(--color-highlight);
  box-shadow: 0 4px 12px rgba(255, 177, 66, 0.2);
}
/* 块标题行：标题居左 + 计数徽章居右（SectorDetail section-header 语言） */
.block-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.block-header .block-title { margin-bottom: 0; }
.section-count {
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  font-size: 10px;
  color: var(--text-secondary);
}
.note-line { font-size: 11px; color: var(--text-secondary); margin-top: 8px; }

/* ── jev 观察轨道（2026-10-08）：独立 AI 评判对照，缺失/降级如实展示 ── */
.jev-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--border-color, rgba(255, 255, 255, 0.15));
  border-radius: 10px;
  font-size: 11px;
  color: var(--text-secondary);
  background: rgba(127, 140, 141, 0.08);
}
/* jev 观察轨道：2026-09-30 卡片网格改 ECharts，图表样式复用 .trend-chart，仅保留日级总体行 */
.jev-chip-clickable { cursor: pointer; }
.jev-chip-open { border-color: var(--color-highlight); color: var(--text-primary); }
.jev-hero-narrative {
  margin-top: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
}
.jev-hero-narrative-head { font-size: 10px; color: var(--text-secondary); margin-bottom: 6px; }
.jev-narrative-text {
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
  max-height: 240px;
  overflow-y: auto;
}
.jev-detail {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.jev-detail-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.jev-detail-title { font-weight: 600; color: var(--text-primary); font-size: 12px; }
.jev-detail-badges { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.jev-detail-meta { font-size: 10px; color: var(--text-secondary); }
.jev-detail-flag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  color: #f39c12;
  border: 1px solid rgba(243, 156, 18, 0.45);
}
.jev-detail-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.jev-detail-cell {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
}
/* 分数通栏条：单行内联两组「标签+数值」，高度随内容不再被概率条格拉伸 */
.jev-detail-scores {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 8px 12px;
}
.jev-score-item { display: flex; align-items: baseline; gap: 10px; }
.jev-detail-cell-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 4px; }
.jev-detail-cell-value { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.jev-prob-rows { display: flex; flex-direction: column; gap: 3px; }
.jev-prob-row { display: flex; align-items: center; gap: 6px; font-size: 10px; color: var(--text-secondary); }
.jev-prob-name { width: 40px; flex: none; }
.jev-prob-bar-wrap { flex: 1; height: 6px; background: rgba(127, 140, 141, 0.15); border-radius: 3px; overflow: hidden; }
.jev-prob-bar { display: block; height: 100%; border-radius: 3px; min-width: 0; }
.jev-prob-pct { width: 42px; flex: none; text-align: right; }
.jev-detail-quality { font-size: 10px; color: #f39c12; }
.jev-eod {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-primary);
  padding: 6px 8px;
  border-left: 2px solid rgba(52, 152, 219, 0.6);
}

/* ---------- 复核工作台（W1 辅助线） ---------- */
.jev-review {
  margin-top: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-secondary);
}
.jev-review-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-primary);
}
.jev-review-title { font-weight: 600; }
.jev-review-legend { color: var(--text-secondary); font-size: 11px; }
.jev-review-progress { color: var(--accent-color, #3498db); font-weight: 600; }
.jev-review-toggle { margin-left: auto; }
.jev-review-days { margin-top: 6px; max-height: 420px; overflow-y: auto; }
.jev-review-day-head {
  display: flex;
  justify-content: space-between;
  width: 100%;
  background: none;
  border: none;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
  font-size: 12px;
  padding: 5px 2px;
  cursor: pointer;
  text-align: left;
}
.jev-review-day-meta { color: var(--text-secondary); font-size: 11px; }
.jev-review-items { padding: 2px 0 6px; }
.jev-review-item { margin-top: 4px; }
.jev-review-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-primary);
  font-size: 11.5px;
  padding: 4px 2px;
  cursor: pointer;
  text-align: left;
  flex-wrap: wrap;
}
.jev-review-type {
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  padding: 1px 5px;
  color: #fff;
}
.jev-review-type[data-type='A'] { background: #8e44ad; }
.jev-review-type[data-type='B'] { background: #c0392b; }
.jev-review-type[data-type='C'] { background: #d68910; }
.jev-review-slot { color: var(--text-secondary); min-width: 38px; }
.jev-review-vs { flex: 1; min-width: 200px; }
.jev-review-dayret { font-variant-numeric: tabular-nums; color: #27ae60; }
.jev-review-dayret.neg { color: #c0392b; }
.jev-review-status { font-size: 10px; border-radius: 8px; padding: 1px 7px; border: 1px solid var(--border-color); color: var(--text-secondary); }
.jev-review-status[data-status='rule_right'] { color: #2980b9; border-color: #2980b9; }
.jev-review-status[data-status='jev_right'] { color: #8e44ad; border-color: #8e44ad; }
.jev-review-status[data-status='ambiguous'] { color: #d68910; border-color: #d68910; }
.jev-review-status[data-status='consistent'] { color: #27ae60; border-color: #27ae60; }
.jev-review-slots {
  width: 100%;
  font-size: 11px;
  border-collapse: collapse;
  color: var(--text-primary);
}
.jev-review-slots th, .jev-review-slots td {
  border: 1px solid var(--border-color);
  padding: 2px 6px;
  text-align: left;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
}
.jev-review-slots th { color: var(--text-secondary); background: var(--bg-primary); }
.jev-review-item-body { padding: 4px 8px 8px 26px; }
.jev-review-narrative { max-height: 120px; font-size: 11px; }
.jev-review-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.jev-review-note {
  margin-top: 6px;
  width: 100%;
  font-size: 11px;
  padding: 4px 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
}
.chip-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  font-size: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 2px 8px;
  color: var(--text-secondary);
}
.chip.diag { border-style: dashed; }
.up-text { color: #ff4757; }
.down-text { color: #2ed573; }
.empty-row { color: var(--text-secondary); text-align: center; padding: 8px 0; }

/* ========== 池换手明细（stocks-table 语言） ========== */
.to-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.to-filters { display: flex; gap: 4px; }
.to-filter-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.to-filter-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.to-filter-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.to-stats {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  padding: 8px 12px;
}
.to-table-container {
  max-height: 500px;
  overflow-y: auto;
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
/* 2026-09-25 用户裁决：列宽不用自适应铺满，固定值匹配字段内容宽度（nowrap 内容超出才撑开） */
.to-table { border-collapse: collapse; font-size: 12px; width: auto; table-layout: auto; }
.to-table th:nth-child(1) { width: 44px; }   /* 序号 */
.to-table th:nth-child(2) { width: 84px; }   /* 代码 */
.to-table th:nth-child(3) { width: 108px; }  /* 名称 */
.to-table th:nth-child(4) { width: 92px; text-align: right; } /* 涨跌幅：右对齐同数值 */
.to-table th:nth-child(5) { width: 68px; }   /* 排名 */
.to-table th:nth-child(6) { width: 76px; }   /* 变动 */
.to-table th:nth-child(7) { width: 118px; }  /* 变动原因 */
.to-table th {
  position: sticky;
  top: 0;
  background: var(--bg-header);
  padding: 10px 6px;
  text-align: left;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 2px solid var(--border-color);
  white-space: nowrap;
  z-index: 1;
}
.to-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}
.to-table tbody tr:hover { background: var(--bg-hover); }
.to-table tbody tr.entry-row { border-left: 4px solid #2ed573; }
.to-code {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  font-weight: 500;
}
.to-table .change { font-variant-numeric: tabular-nums; text-align: right; }
.to-table .num { font-variant-numeric: tabular-nums; }
/* 涨红跌绿：特异性压过 td color（与成分股列表一致） */
.to-table .up-text { color: #ff4757; }
.to-table .down-text { color: #2ed573; }
.to-kind-badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
}
.to-kind-badge.entry { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.to-kind-badge.exit { background: rgba(255, 71, 87, 0.15); color: #ff4757; }
.to-reason {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  color: var(--text-secondary);
}

/* ========== 阶段分布（左环形图 + 右排序明细） ========== */
.stage-layout { display: flex; align-items: center; gap: 32px; }
.stage-pie { position: relative; width: 240px; height: 240px; flex-shrink: 0; }
.stage-pie-canvas { position: absolute; inset: 0; }
.stage-pie-center {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  pointer-events: none;
}
.stage-pie-total { font-size: 26px; font-weight: bold; color: var(--text-title); font-variant-numeric: tabular-nums; line-height: 1.2; }
.stage-pie-unit { font-size: 10px; color: var(--text-secondary); margin-top: 2px; }
.stage-detail { flex: 1; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.stage-row { display: flex; align-items: center; gap: 10px; }
.stage-dot { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.stage-name { width: 52px; font-size: 12px; color: var(--text-primary); flex-shrink: 0; }
.stage-bar { flex: 1; height: 6px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.stage-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.stage-count {
  width: 40px; text-align: right; font-size: 12px; font-weight: 600;
  color: var(--text-title); font-variant-numeric: tabular-nums;
}
.stage-pct {
  width: 52px; text-align: right; font-size: 11px; font-weight: 600;
  color: var(--color-highlight); font-variant-numeric: tabular-nums;
}

/* ========== 情绪趋势 / 历史对比 / 分层结构（SectorDetail 历史趋势图表语言，三图表共用） ========== */
.time-range-selector, .indicator-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.time-btn, .indicator-btn {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.time-btn:hover, .indicator-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.time-btn.active, .indicator-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.trend-chart {
  height: 250px;
  width: 100%;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px;
}
.trend-stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.trend-stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}
.trend-stat-card .stat-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 4px; }
.trend-stat-card .stat-value {
  font-size: 18px; font-weight: bold; color: var(--text-title);
  line-height: 1.2; font-variant-numeric: tabular-nums;
}
.trend-stat-card .stat-time { font-size: 9px; color: var(--text-secondary); margin-top: 4px; min-height: 12px; }

/* ========== 证据与风险 ========== */
.evidence-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.evidence-columns.two { align-items: start; }
.evidence-list { margin: 0; padding-left: 16px; line-height: 1.7; font-size: 12px; }
.diag-block {
  display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline;
  border: 1px dashed var(--border-color); border-radius: 8px;
  padding: 8px 12px; font-size: 11px; color: var(--text-secondary);
}
.diag-tag { font-weight: 600; color: #ffb142; }

/* ========== EOD 文档明细（全字段分组展示，2026-09-25） ========== */
.doc-full-block { margin-top: 4px; }
.doc-collapse-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: none; border: none; padding: 0; cursor: pointer;
  color: var(--text-title);
  transition: color 0.15s ease;
}
.doc-collapse-btn:hover { color: var(--color-highlight); }
.doc-collapse-arrow {
  display: inline-block; font-size: 10px; color: var(--text-secondary);
  transition: transform 0.15s ease;
}
.doc-collapse-btn.expanded .doc-collapse-arrow { transform: rotate(90deg); }
.doc-full-content { margin-top: 10px; }
.doc-group { margin-top: 14px; }
.doc-group-title {
  font-size: 12px; font-weight: 600; color: var(--text-secondary);
  padding-bottom: 6px; border-bottom: 1px solid var(--border-color); margin-bottom: 8px;
}
.doc-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px 12px; }
.doc-field {
  display: flex; flex-direction: column; gap: 2px;
  background: var(--bg-tertiary); border-radius: 8px; padding: 8px 10px;
}
.doc-field-wide { grid-column: 1 / -1; }
.doc-label { font-size: 10px; color: var(--text-secondary); }
.doc-value {
  font-size: 13px; font-weight: 600; color: var(--text-title);
  font-variant-numeric: tabular-nums; word-break: break-all; line-height: 1.4;
}
.doc-table-scroll { overflow-x: auto; border: 1px solid var(--border-color); border-radius: 8px; }
.doc-table { width: 100%; border-collapse: collapse; font-size: 11px; white-space: nowrap; }
.doc-table th, .doc-table td {
  padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--border-color);
  font-variant-numeric: tabular-nums;
}
.doc-table thead th {
  position: sticky; top: 0; background: var(--bg-header); color: var(--text-secondary);
  font-weight: 600; font-size: 10px;
}
.doc-table tbody tr:last-child th, .doc-table tbody tr:last-child td { border-bottom: none; }
.doc-table-corner, .doc-table-rowhead {
  text-align: left !important; color: var(--text-title); font-weight: 600;
  background: var(--bg-secondary); position: sticky; left: 0;
}
.doc-remaining {
  display: flex; flex-direction: column; gap: 4px;
  background: var(--bg-tertiary); border-radius: 8px; padding: 10px 12px;
}
.doc-remaining-row {
  display: flex; gap: 10px; align-items: baseline;
  font-size: 11px; font-variant-numeric: tabular-nums;
}
.doc-remaining-row .doc-label { flex: 0 0 auto; font-family: monospace; }
.doc-remaining-row .doc-value { font-size: 11px; font-weight: 400; word-break: break-all; }

@media (max-width: 720px) {
  .doc-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 720px) {
  .evidence-columns { grid-template-columns: 1fr; }
  .metrics-grid, .grid-4 { grid-template-columns: repeat(2, 1fr); }
  .grid-6 { grid-template-columns: repeat(3, 1fr); }
  .trend-stats-grid { grid-template-columns: repeat(2, 1fr); }
  .stage-layout { flex-direction: column; }
  .stage-pie { width: 200px; height: 200px; }
  .hotlist-emotion-panel { width: calc(100vw - 16px); }
  .turnover-grid { grid-template-columns: repeat(2, 1fr); }
}

/* ── 相位验收（第 8 页签 + overview chip，2026-09-30）── */
.phase-chip {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: default;
}
.phase-chip-offense { background: rgba(239, 68, 68, 0.15); color: #ff6b6b; }
.phase-chip-defense { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.phase-chip-unknown { background: rgba(150, 150, 150, 0.15); color: #999; }

.phase-note {
  font-size: 12px;
  color: #8a8f98;
  background: rgba(139, 124, 246, 0.08);
  border-left: 3px solid #8b7cf6;
  padding: 8px 12px;
  border-radius: 4px;
  margin-bottom: 12px;
  line-height: 1.6;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  margin: 12px 0 8px;
  color: #c9cdd4;
}

.phase-chart-card { margin-top: 8px; }
.phase-chart { width: 100%; height: 320px; }

.phase-months-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.phase-months-table th,
.phase-months-table td {
  padding: 6px 8px;
  text-align: left;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.phase-months-table th { color: #8a8f98; font-weight: 500; }
.phase-pass { color: #ff6b6b; font-weight: 600; }
.phase-fail { color: #8a8f98; }

.phase-tone-good { color: #ff6b6b; }
.phase-tone-bad { color: #8a8f98; }

.phase-pulse-ab {
  font-size: 12px;
  color: #c9cdd4;
  background: rgba(139, 124, 246, 0.08);
  border-left: 3px solid #8b7cf6;
  padding: 6px 10px;
  border-radius: 4px;
  margin-top: 8px;
}

.phase-pulse-rows { display: flex; flex-direction: column; gap: 7px; padding: 4px 2px; }
.phase-pulse-row { font-size: 12px; }
.phase-band-name { width: 96px; flex: none; display: flex; align-items: center; gap: 5px; color: var(--text-primary); }
.phase-band-badge {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 8px;
  background: rgba(217, 119, 6, 0.18);
  color: #f5a623;
}
.phase-band-track { height: 10px; border-radius: 5px; }
.phase-band-val { width: 64px; flex: none; text-align: right; font-weight: 600; font-size: 12px; }
.phase-band-trades { width: 44px; flex: none; text-align: right; color: var(--text-secondary); font-size: 11px; }
</style>
