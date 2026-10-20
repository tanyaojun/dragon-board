<!-- src/components/panels/JevNarrativePanel.vue -->
<!-- 独立 JEV 叙事面板（2026-10-08）：与热榜情绪面板完全脱钩，只消费 jev 独立观察轨道
     （hotlist_jev_sentiment，GET /api/hotlist-jev/series|range）。
     解耦硬边界：不引用 sentiment-overview（jev+规则同包）、review-list（对照规则分）、
     hotlistSentimentApi 与规则 EOD（hotlist_sentiment emotionScore）任何字段；后端零改动。
     展示宗旨：叙事全文与返回结果无截断全量呈现（方格/温度计/ECharts/原文/原始 JSON），
     缺失一律 fail-visible（'--' / 结构化标注），不伪造档位、0 分或概率分布。 -->
<template>
  <Teleport to="body">
    <div v-if="visible" class="jev-narrative-panel" :style="panelStyle" ref="panelRef">
      <div class="panel-header">
        <div class="header-left">
          <h3>🌡️ JEV 叙事 <span class="version-badge">v1.0</span></h3>
          <span v-if="seriesDate" class="time-badge">{{ seriesDate }}</span>
          <span v-if="eodDoc" class="time-badge ok" title="日级总体（盘后固定）已落库">EOD 已生成</span>
          <span v-else-if="!loading" class="time-badge warn" title="该日 jev EOD 文档未落库或未生成">EOD 未生成</span>
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
            @click="switchTab(tab.key)">
            {{ tab.icon }} {{ tab.label }}
          </button>
        </div>
      </div>

      <div class="panel-content">
        <div v-if="loading && !loaded" class="state-block"><span class="spinner"></span>正在加载 jev 叙事轨道…</div>
        <div v-else-if="loadError && !loaded" class="state-block error">
          ⚠️ {{ loadError }}
          <button class="retry-btn" @click="loadAll">重试</button>
        </div>
        <div v-else-if="!loaded" class="state-block">暂无 jev 叙事数据（独立采集轨道，可能未开启）</div>

        <template v-else>
          <div class="toolbar">
            <div class="time-range-selector">
              <button v-for="win in TIME_WINDOWS" :key="win.key" class="time-btn"
                :class="{ active: windowKey === win.key }" @click="setWindow(win.key)">
                {{ win.label }}
              </button>
            </div>
            <div class="date-selector" v-if="dayDocs.length">
              <button v-for="day in dayDocs" :key="day.tradingDate" class="time-btn date-btn"
                :class="{ active: selectedDate === day.tradingDate }" @click="selectDate(day.tradingDate)">
                {{ day.tradingDate.slice(5) }}
              </button>
            </div>
          </div>

          <!-- ① 叙事概览：三段式阅读动线（现在→日内演化→EOD 口径），无重复无仲裁
               （视觉语言对齐热榜情绪面板：色用在文字/色点/细进度条上，不用大面积饱和底色） -->
          <section v-show="view === 'grid'" class="tab-pane">
            <div v-if="degradedReason" class="note-line warn-line">⚠️ jev 轨道降级：{{ degradedReason }}</div>
            <div v-if="!latestSlot && !eodDoc" class="empty-row">该日无 jev 文档</div>
            <template v-else>
              <div class="stage-hero" :style="{ borderLeftColor: stageColor(latestSlotStageName) }">
                <div class="hero-label">JEV 市场热度计 · 最新槽 {{ latestSlot?.slotTime || seriesDate }}</div>
                <div class="hero-stage" :style="{ color: stageColor(latestSlotStageName) }">{{ latestSlotStageName ?? '档位缺失' }}</div>
                <div class="hero-meta">
                  <span v-if="latestFrameName && latestFrameName !== latestSlotStageName" class="overview-chip overview-chip-warn"
                    title="当前帧档与日内序列档分歧：瞬时冲击信号">当前帧·{{ latestFrameName }}</span>
                  <span v-if="latestCrowding?.layerName" class="overview-chip" :class="{ 'overview-chip-warn': latestCrowding.warn }">拥挤·{{ latestCrowding.layerName }}</span>
                  <span v-if="latestConfidence?.hesitant" class="overview-chip overview-chip-warn">⚠️置信 P{{ Math.round((latestProbability ?? 0) * 100) }}% 犹豫</span>
                  <span v-if="anchorRange" class="overview-chip overview-chip-muted" :title="anchorRange">锚 {{ anchorRange }}</span>
                </div>
                <div class="hero-score-bar">
                  <span class="hero-score-num">{{ latestTemperature ?? '--' }}</span>
                  <div class="hero-score-track">
                    <div class="hero-score-fill" :style="{ width: `${latestTemperature ?? 0}%`, background: tempGradient(latestTemperature) }"></div>
                  </div>
                  <span class="hero-score-hint">温度 0-100</span>
                </div>
                <div v-if="latestCrowdingProb != null" class="hero-score-bar">
                  <span class="hero-score-num">{{ Math.round(latestCrowdingProb * 100) }}</span>
                  <div class="hero-score-track">
                    <div class="hero-score-fill" :style="{ width: `${latestCrowdingProb * 100}%`, background: crowdingRiskGradient() }"></div>
                  </div>
                  <span class="hero-score-hint">拥挤抗风险 0-100（拥挤三层概率合计）</span>
                </div>
                <div v-else-if="latestSlot" class="hero-score-bar hero-score-missing">
                  <span class="hero-score-hint">拥挤不可用（归层分布缺失，归层名见 chip）</span>
                </div>
                <div v-if="latestProbability != null" class="hero-score-bar">
                  <span class="hero-score-num">P{{ Math.round(latestProbability * 100) }}%</span>
                  <div class="hero-score-track">
                    <div class="hero-score-fill" :style="{ width: `${latestProbability * 100}%`, background: confidenceGradient(latestProbability) }"></div>
                  </div>
                  <span class="hero-score-hint">置信 0-100</span>
                </div>
                <div v-else-if="latestSlot" class="hero-score-bar hero-score-missing">
                  <span class="hero-score-hint">置信不可用（{{ latestConfidence?.noDistribution ? 'score 型无分布' : '答案缺失' }}）</span>
                </div>
                <div class="hero-summary">{{ heroSummary }}</div>
              </div>

              <div class="sub-block">
                <div class="block-header">
                  <span class="block-title">📍 当日逐槽 · 日内演化</span>
                  <span class="section-count">{{ slots.length }} 槽</span>
                </div>
                <div v-if="!slotCards.length" class="empty-row">该日无槽位文档</div>
                <div v-else class="slot-cards">
                  <div v-for="card in slotCards" :key="card.slotTime" class="slot-card"
                    :class="{ degraded: card.degraded, 'no-data': card.noData }" :title="card.title">
                    <div class="slot-card-head">
                      <span>{{ card.slotTime }}</span>
                      <span v-if="card.degraded" class="slot-card-flag">降级</span>
                      <span v-else-if="card.noData" class="slot-card-flag">无数据</span>
                    </div>
                    <div class="slot-card-stage" :style="{ color: stageColor(card.seqName) }">{{ card.seqName ?? '--' }}</div>
                    <div class="slot-card-nums">
                      <span :style="{ color: tempColor(card.temp) }">🌡 {{ card.temp ?? '--' }}</span>
                      <span class="slot-card-layer"><span class="legend-dot" :style="{ background: crowdingColor(card.layer) }"></span>{{ card.layerName ?? '--' }}</span>
                    </div>
                    <div class="slot-card-sub">
                      <template v-if="card.frameName && card.frameName !== card.seqName">帧分歧：{{ card.frameName }} · </template>{{ card.pText }}
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="dayDocs.length" class="sub-block">
                <div class="block-header">
                  <span class="block-title">🗓️ 日级窗口（EOD 口径）</span>
                  <span class="section-count">{{ dayDocs.length }} 日</span>
                </div>
                <div class="overview-chips">
                  <span v-if="eodDayStageName" class="overview-chip">EOD 档位·{{ eodDayStageName }}</span>
                  <span v-if="dayPatternName" class="overview-chip">路径·{{ dayPatternName }}</span>
                  <span v-if="eodCrowdingPoint?.layerName" class="overview-chip" :class="{ 'overview-chip-warn': eodCrowdingPoint.warn }">拥挤·{{ eodCrowdingPoint.layerName }}</span>
                  <span v-if="dayTemperature != null" class="overview-chip">日级温度·{{ dayTemperature }}</span>
                </div>
                <div class="trend-chart" ref="dayChartRef"></div>
                <div v-if="missingDays.length" class="note-line warn-line">
                  ⚠️ 窗口缺失 {{ missingDays.length }} 日（无任何 jev 文档）：{{ missingDays.map((d) => d.tradingDate.slice(5)).join('、') }}
                </div>
                <div v-if="rangeDegradedCount" class="note-line warn-line">⚠️ 窗口内降级/无数据文档 {{ rangeDegradedCount }} 份</div>
              </div>
            </template>
          </section>

          <!-- ② 温度计：SVG 温度计 + 锚分位卡 + 温度曲线（ECharts）+ 研究注记 -->
          <section v-show="view === 'thermometer'" class="tab-pane">
            <div v-if="ecosystemBreak" class="break-card" title="涨停生态断层：家数掉出常态带+涨跌均衡+量能不缩（§十三，反弹在即）">
              ⚡ 涨停生态断层日 · {{ ecosystemBreak.ztCount }} 家（常态带 P20={{ ecosystemBreak.p20 }}）
              · 涨跌比 {{ ecosystemBreak.advDecRatio }}（均衡）
              · 量能 {{ Math.round(ecosystemBreak.amountYi) }} 亿（昨 {{ Math.round(ecosystemBreak.prevAmountYi) }} 亿，未缩）
              —— 反弹在即信号（全月 1-2 次）
            </div>
            <div class="thermo-row">
              <div class="thermo-card">
                <div class="thermo-title">最新槽温度<template v-if="latestSlot"> · {{ latestSlot.slotTime }}</template></div>
                <svg class="thermo-svg" viewBox="0 0 76 232" aria-hidden="true">
                  <rect x="24" y="12" width="18" height="176" rx="9" class="thermo-tube" />
                  <rect x="27.5" :y="thermoTubeY(latestTemperature)" width="11" :height="thermoTubeH(latestTemperature)"
                    rx="5.5" :fill="tempColor(latestTemperature)" />
                  <g v-for="tick in THERMO_TICKS" :key="tick">
                    <line x1="42" :y1="thermoTickY(tick)" x2="48" :y2="thermoTickY(tick)" class="thermo-tick" />
                    <text x="52" :y="thermoTickY(tick) + 3.5" class="thermo-tick-text">{{ tick }}</text>
                  </g>
                  <circle cx="33" cy="204" r="16" :fill="tempColor(latestTemperature)" class="thermo-bulb" />
                  <text x="33" y="209" class="thermo-bulb-text">{{ latestTemperature ?? '--' }}</text>
                </svg>
                <div class="thermo-caption" :style="{ color: stageColor(latestSlotStageName) }">
                  {{ latestSlotStageName ?? '档位缺失' }}
                </div>
              </div>
              <div class="thermo-card">
                <div class="thermo-title">EOD 日级温度</div>
                <svg class="thermo-svg" viewBox="0 0 76 232" aria-hidden="true">
                  <rect x="24" y="12" width="18" height="176" rx="9" class="thermo-tube" />
                  <rect x="27.5" :y="thermoTubeY(dayTemperature)" width="11" :height="thermoTubeH(dayTemperature)"
                    rx="5.5" :fill="tempColor(dayTemperature)" />
                  <g v-for="tick in THERMO_TICKS" :key="tick">
                    <line x1="42" :y1="thermoTickY(tick)" x2="48" :y2="thermoTickY(tick)" class="thermo-tick" />
                    <text x="52" :y="thermoTickY(tick) + 3.5" class="thermo-tick-text">{{ tick }}</text>
                  </g>
                  <circle cx="33" cy="204" r="16" :fill="tempColor(dayTemperature)" class="thermo-bulb" />
                  <text x="33" y="209" class="thermo-bulb-text">{{ dayTemperature ?? '--' }}</text>
                </svg>
                <div class="thermo-caption" :style="{ color: stageColor(eodDayStageName) }">
                  {{ eodDayStageName ?? (eodDoc ? '档位缺失' : 'EOD 未生成') }}
                </div>
              </div>
              <div class="anchor-panel">
                <div class="anchor-title">📐 近20日参照（判读坐标系）<template v-if="anchorRange"> · {{ anchorRange }}</template></div>
                <div v-if="!anchorMetrics.length" class="empty-row">锚段缺失或未解析出分位（fail-visible，不虚构坐标系）</div>
                <div v-else class="anchor-grid">
                  <div v-for="metric in anchorMetrics" :key="metric.metric" class="anchor-card">
                    <div class="anchor-metric">{{ metric.metric }}</div>
                    <div v-if="metric.note" class="anchor-note">⚠️ {{ metric.note }}</div>
                    <template v-else>
                      <div class="anchor-quantiles">
                        <span class="anchor-q">p20 <b>{{ metric.p20 }}</b></span>
                        <span class="anchor-q">p50 <b>{{ metric.p50 }}</b></span>
                        <span class="anchor-q">p80 <b>{{ metric.p80 }}</b></span>
                      </div>
                      <div class="anchor-last">{{ metric.lastDate?.slice(5) }} {{ metric.lastValue }}{{ metric.unit ?? '' }}</div>
                    </template>
                  </div>
                </div>
                <div class="anchor-footnote">score 还原口径：10 档锚点期望值 / 9 × 100（jev score 协议）</div>
              </div>
              <div v-if="ecoBreadthZone" class="anchor-panel"
                title="生态宽度 U 形（§十三，8/9 月复现）：低宽度积极/中宽度回避/高宽度顺势——展示侧读数，交易条款未裁决">
                <div class="anchor-title">📶 生态宽度 U 形分区（展示侧读数）</div>
                <div class="eco-breadth-row">
                  <span class="eco-zone-badge" :data-zone="ecoBreadthZone.zone">{{ ecoBreadthZone.zoneText.split('：')[0] }}</span>
                  <span class="eco-breadth-text">今日涨停 <b>{{ ecoBreadthZone.count }}</b> 家（{{ ecoBreadthZone.source }}<template
                    v-if="ecoBreadthZone.anchorText">，锚末值 {{ ecoBreadthZone.anchorText }}</template>）</span>
                </div>
                <div class="eco-breadth-zone">{{ ecoBreadthZone.zoneText.split('：')[1] }}</div>
                <div class="anchor-footnote">U 形后验=§十三生态宽度三档（8/9 月复现）；交易条款未裁决，不构成操作指令</div>
              </div>
            </div>
            <div class="note-line research-line">
              🔎 研究注记：槽级温度带 REVERSE 信号（高读数含反向含义，勿当顺势信号）；温度与规则分水平差≈口径差（市场热度计 vs
              池内质量计），排序一致性随锚深上升（ρ 0.246→0.572）。
            </div>
            <div v-if="!thermoPoints.length" class="empty-row">暂无温度数据</div>
            <div v-else class="trend-chart" ref="thermoChartRef"></div>
          </section>

          <!-- ③ 拥挤度：ECharts 柱状图（置信度页签同语言：窗口自适应历史维度+指标开关）+ waffle 最新槽归层 + 层迁移 + 窗口层统计 -->
          <section v-show="view === 'crowding'" class="tab-pane">
            <!-- 缺失日披露放在数据分支之外：整窗全缺时也必须可见（fail-visible，同置信度页签语言） -->
            <div v-if="windowKey !== '1d' && missingDays.length" class="note-line warn-line">
              ⚠️ 窗口缺失 {{ missingDays.length }} 日（无任何 jev 文档，图中无此柱）：{{ missingDays.map((d) => d.tradingDate.slice(5)).join('、') }}
            </div>
            <div v-if="!crowdingBarPoints.length" class="empty-row">该日无拥挤数据</div>
            <template v-else>
              <div class="indicator-selector">
                <button v-for="ind in CROWDING_BARS_INDICATORS" :key="ind.key" class="indicator-btn"
                  :class="{ active: crowdingBarIndicators.includes(ind.key) }"
                  @click="toggleCrowdingBar(ind.key)">
                  {{ ind.icon }} {{ ind.label }}
                </button>
              </div>
              <div class="trend-chart" ref="crowdingBarChartRef"></div>
              <div class="crowding-stats">
                <div class="sub-block-title">窗口层统计</div>
                <div class="stats-grid">
                  <div class="stat-card">
                    <div class="stat-label">{{ crowdingDetail?.layerStatsLabel ?? '当日槽位层统计' }}</div>
                    <div class="stat-body">
                      <template v-if="crowdingDetail?.layerStatsData">
                        <span v-for="layerKey in CROWDING_ORDER" :key="layerKey" class="stat-item"
                          :style="{ color: crowdingColor(layerKey) }">
                          {{ CROWDING_NAMES[layerKey] }} {{ crowdingDetail.layerStatsData.counts[layerKey] ?? 0 }}
                        </span>
                        <span class="stat-item muted">逃生 {{ crowdingDetail.layerStatsData.escapeCount }}/{{ crowdingDetail.layerStatsData.total }}<template
                            v-if="crowdingDetail.layerStatsData.escapeRate != null">（{{ Math.round(crowdingDetail.layerStatsData.escapeRate * 100) }}%）</template></span>
                      </template>
                      <span v-else class="stat-item muted">该日无槽位文档（层统计不可算）</span>
                    </div>
                  </div>
                  <div class="stat-card">
                    <div class="stat-label">窗口 EOD 层统计（{{ dayDocs.length }} 日）</div>
                    <div class="stat-body">
                      <span v-for="layerKey in CROWDING_ORDER" :key="layerKey" class="stat-item"
                        :style="{ color: crowdingColor(layerKey) }">
                        {{ CROWDING_NAMES[layerKey] }} {{ windowLayerStats.counts[layerKey] ?? 0 }}
                      </span>
                      <span class="stat-item muted">逃生 {{ windowLayerStats.escapeCount }}/{{ windowLayerStats.total }}<template
                          v-if="windowLayerStats.escapeRate != null">（{{ Math.round(windowLayerStats.escapeRate * 100) }}%）</template></span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="crowding-hero">
                <div class="crowding-latest">
                  <div class="sub-block-title">{{ crowdingDetail?.waffleTitle ?? '最新槽归层' }}</div>
                  <template v-if="crowdingDetail?.point">
                    <div class="crowding-layer-name" :style="{ color: crowdingColor(crowdingDetail.point.layer) }">
                      {{ crowdingDetail.point.layerName ?? '归层缺失' }}
                      <span v-if="crowdingDetail.point.warn" class="warn-badge">毒层警示</span>
                    </div>
                    <div v-if="crowdingDetail.point.probabilities" class="waffle-block">
                      <div class="waffle-grid">
                        <span v-for="(sq, index) in waffleSquares(crowdingDetail.point.probabilities)" :key="index"
                          class="waffle-square" :style="{ background: sq }"></span>
                      </div>
                      <div class="waffle-legend">
                        <span v-for="entry in waffleLegend(crowdingDetail.point.probabilities)" :key="entry.name"
                          class="waffle-legend-item">
                          <span class="legend-dot" :style="{ background: entry.color }"></span>{{ entry.name }} {{ entry.pctText }}
                        </span>
                      </div>
                    </div>
                    <div v-if="crowdingDetail.point.confidence != null || crowdingDetail.point.probability != null"
                      class="crowding-meta">
                      <template v-if="crowdingDetail.point.probability != null">P{{ Math.round(crowdingDetail.point.probability * 100) }}%</template>
                      <template v-if="crowdingDetail.point.confidence != null"> · 模型置信 {{ Math.round(crowdingDetail.point.confidence * 100) }}%</template>
                      <template v-if="crowdingDetail.point.probability != null && crowdingDetail.point.probability < JEV_HESITANT_THRESHOLD">
                        · ⚠️ 低置信（&lt;{{ Math.round(JEV_HESITANT_THRESHOLD * 100) }}% 犹豫阈值）
                      </template>
                    </div>
                  </template>
                  <div v-else class="empty-row">归层缺失（降级/无数据，不伪造）</div>
                </div>
                <div class="crowding-strip-block">
                  <div class="sub-block-title">层迁移（相邻槽变化）</div>
                  <div v-if="!crowdingDetail?.transitions.length" class="empty-row">暂无层迁移（当日全程同层或数据不足）</div>
                  <div v-else class="transition-list">
                    <div v-for="(t, index) in crowdingDetail.transitions" :key="index" class="transition-item">
                      <span class="time-badge">{{ t.atSlot }}</span>
                      <span :style="{ color: crowdingColor(t.from) }">{{ t.fromName ?? '缺失' }}</span>
                      →
                      <span :style="{ color: crowdingColor(t.to) }">{{ t.toName }}</span>
                    </div>
                  </div>
                  <div class="crowding-legend">
                    <span v-for="layerKey in CROWDING_ORDER" :key="layerKey" class="waffle-legend-item">
                      <span class="legend-dot" :style="{ background: crowdingColor(layerKey) }"></span>{{ CROWDING_NAMES[layerKey] ?? layerKey }}<template v-if="WARN_LAYERS.has(layerKey)"> ⚠️</template>
                    </span>
                  </div>
                </div>
              </div>
              <div class="note-line research-line">
                🔎 研究注记：拥挤=v2 离散归层（连续分已实证无方差退役）；top_acceleration / late_seal_weakness 为 fwdWorst
                实证毒层；insufficient_evidence 逃生应趋近 0（判据已锚定近20日参照），持续偏高属异常需排查锚供给；
                柱=所选层概率（top1，柱色=归层色）、拥挤抗风险线=三层概率合计（概览 hero 同口径），
                多日窗口取每日 EOD 日级归层（day_crowding），随顶部窗口切换历史维度；缺失与「无数据」如实标注不补 0；
                点击柱体切换下方详情卡口径（槽位层统计/归层分布/层迁移跟随选中点，白描边=选中柱，默认最新，同热榜情绪 jev 观察轨道交互）。
              </div>
            </template>
          </section>

          <!-- ④ 置信度：槽位 × 问题置信 ECharts 柱状图（热榜情绪·历史对比页签同语言：指标开关+柱+线）+ 派生指标 -->
          <section v-show="view === 'confidence'" class="tab-pane">
            <!-- 缺失日披露放在数据分支之外：整窗全缺时也必须可见（fail-visible，同叙事概览语言） -->
            <div v-if="windowKey !== '1d' && missingDays.length" class="note-line warn-line">
              ⚠️ 窗口缺失 {{ missingDays.length }} 日（无任何 jev 文档，图中无此柱）：{{ missingDays.map((d) => d.tradingDate.slice(5)).join('、') }}
            </div>
            <div v-if="!confidenceBarsPoints.length" class="empty-row">该日无置信数据</div>
            <template v-else>
              <div class="indicator-selector">
                <button v-for="ind in confBarsActiveQuestions" :key="ind.key" class="indicator-btn"
                  :class="{ active: confidenceBarIndicators.includes(ind.key) }"
                  @click="toggleConfidenceBar(ind.key)">
                  {{ ind.icon }} {{ ind.label }}
                </button>
              </div>
              <div v-if="!confidenceBarsSeries.length" class="empty-row">暂无置信序列（至少保留一个指标）</div>
              <div v-else class="trend-chart" ref="confidenceBarsChartRef"></div>
              <div class="stats-grid">
                <div v-for="stat in confidenceStats" :key="stat.label" class="stat-card">
                  <div class="stat-label">{{ stat.label }}</div>
                  <div class="stat-body">
                    <span class="stat-item">{{ stat.value }}</span>
                    <span class="stat-item muted">{{ stat.sub }}</span>
                  </div>
                </div>
              </div>
              <!-- 答案分布明细：choice 全分布 + score 锚点（返回结果全量呈现，2026-10-08 评审补齐） -->
              <div class="dist-block">
                <div class="sub-block-title">答案分布明细（choice 全分布 + score 锚点）</div>
                <div class="doc-selector">
                  <button class="time-btn" :class="{ active: distKey === 'eod' }" :disabled="!eodDoc"
                    @click="distKey = 'eod'">📌 EOD</button>
                  <button v-for="slot in slots" :key="slot.slotTime || ''" class="time-btn"
                    :class="{ active: distKey === slot.slotTime }" @click="distKey = slot.slotTime || ''">{{ slot.slotTime }}</button>
                </div>
                <div v-if="!distDoc" class="empty-row">选择槽位或 EOD 查看答案分布</div>
                <div v-else class="dist-grid">
                  <div v-for="row in distRows" :key="row.key" class="dist-card">
                    <div class="dist-head">
                      <span class="dist-label">{{ row.label }}</span>
                      <span class="dist-choice" :style="row.tone ? { color: row.tone } : undefined">{{
                        row.choiceName ?? (row.score != null ? `锚期望 ${row.score}` : '--') }}</span>
                      <span class="dist-meta">
                        <template v-if="row.confidence != null">置信 {{ Math.round(row.confidence * 100) }}%</template>
                        <template v-if="row.probability != null"> · P{{ Math.round(row.probability * 100) }}%</template>
                        <template v-if="row.margin != null"> · margin {{ (row.margin * 100).toFixed(0) }}</template>
                        <template v-if="row.entropy != null"> · 熵 {{ row.entropy.toFixed(2) }}</template>
                        <template v-if="row.hesitant"> · ⚠️ 犹豫</template>
                      </span>
                    </div>
                    <div v-if="row.legend.length" class="dist-legend">score 锚点：{{ row.legend.join(' / ') }}</div>
                    <div v-if="row.rows.length" class="dist-rows">
                      <div v-for="opt in row.rows" :key="opt.key" class="dist-row">
                        <span class="dist-row-name">{{ opt.name }}</span>
                        <span class="dist-bar-wrap"><span class="dist-bar"
                          :style="{ width: `${opt.pct ?? 0}%`, background: opt.color }"></span></span>
                        <span class="dist-row-pct">{{ opt.pct == null ? '--' : `${opt.pct}%` }}</span>
                      </div>
                    </div>
                    <div v-if="row.isScore" class="dist-score-note">{{ row.scoreNoDist
                      ? 'score 型未携带锚点分布（缺失如实标注，不伪造）'
                      : 'score 型分布=10 档锚点概率（锚期望 / 9 × 100 = 还原温度分）' }}</div>
                  </div>
                </div>
              </div>
              <div class="note-line research-line">
                🔎 研究注记：choice 答案携带 probabilities/confidence；score 型答案（温度）实测同样携带 10 档锚点分布 + 模型置信
                （2026-10-02 生产库 100% 覆盖；锚期望 / 9 × 100 = 还原温度分），柱=P（top 概率）、温度线=C（模型置信，不套 P 犹豫阈值色），
                margin/熵/逐题模型置信进 tooltip，缺失与「无分布」如实标注不补 0；犹豫阈值 60%（top 概率，choice 题），与热榜情绪面板口径一致；
                多日窗口取每日 EOD 日级答案（日级档/日温度/日拥挤，路径形态进 tooltip），随顶部窗口切换历史维度。
              </div>
            </template>
          </section>

          <!-- ⑤ 叙事全文：narrativeRaw 无截断分段全量呈现 -->
          <section v-show="view === 'narrative'" class="tab-pane">
            <div class="doc-selector">
              <button class="time-btn" :class="{ active: focusKind === 'eod' }" :disabled="!eodDoc"
                @click="setFocus('eod')">📌 EOD 日级</button>
              <button v-for="slot in slots" :key="slot.slotTime || ''" class="time-btn"
                :class="{ active: focusKind === 'slot' && focusSlotTime === slot.slotTime }"
                @click="setFocus('slot', slot.slotTime)">{{ slot.slotTime }}</button>
            </div>
            <div v-if="!focusDoc" class="empty-row">选择槽位或 EOD 查看叙事全文</div>
            <template v-else>
              <div class="narrative-meta">
                <span class="time-badge">{{ focusDoc.tradingDate }} {{ focusDoc.kind === 'eod' ? 'EOD' : focusDoc.slotTime }}</span>
                <span v-if="focusDoc.status === 'degraded'" class="time-badge warn">降级：{{ focusDoc.errorCode || '' }} {{ focusDoc.errorDetail || '' }}</span>
                <span v-else-if="focusDoc.status === 'no_data'" class="time-badge warn">无数据：{{ focusDoc.errorDetail || '' }}</span>
                <span v-if="focusDoc.model" class="time-badge">🤖 {{ focusDoc.model }}</span>
                <span v-if="narrativeText" class="time-badge">全文 {{ narrativeText.length }} 字</span>
                <span v-if="usageText" class="time-badge">tokens {{ usageText }}</span>
                <span v-if="focusDoc.latencyMs != null" class="time-badge">{{ focusDoc.latencyMs }}ms</span>
                <span v-if="focusDoc.historyAnchorRange" class="time-badge" :title="focusDoc.historyAnchorRange">锚 {{ focusDoc.historyAnchorRange }}</span>
              </div>
              <div class="narrative-body">
                <div v-if="!narrativeText" class="empty-row">narrativeRaw 缺失（旧文档/降级路径可能未保存叙事）</div>
                <template v-else>
                  <pre v-if="narrativeProjection.header" class="narrative-header-line">{{ narrativeProjection.header }}</pre>
                  <div v-for="section in narrativeProjection.sections" :key="section.title" class="narrative-section">
                    <div class="narrative-section-title">【{{ section.title }}】</div>
                    <div v-if="section.title === '近20日参照' && anchorMetrics.length" class="anchor-grid inline">
                      <div v-for="metric in anchorMetrics" :key="metric.metric" class="anchor-card">
                        <div class="anchor-metric">{{ metric.metric }}</div>
                        <div v-if="metric.note" class="anchor-note">⚠️ {{ metric.note }}</div>
                        <template v-else>
                          <div class="anchor-quantiles">
                            <span class="anchor-q">p20 <b>{{ metric.p20 }}</b></span>
                            <span class="anchor-q">p50 <b>{{ metric.p50 }}</b></span>
                            <span class="anchor-q">p80 <b>{{ metric.p80 }}</b></span>
                          </div>
                          <div class="anchor-last">{{ metric.lastDate?.slice(5) }} {{ metric.lastValue }}{{ metric.unit ?? '' }}</div>
                        </template>
                      </div>
                    </div>
                    <pre class="narrative-text">{{ section.lines.join('\n') }}</pre>
                  </div>
                </template>
              </div>
            </template>
          </section>

          <!-- ⑥ 原始返回：responseRaw / questionsRaw / evidenceRaw / 元信息全量呈现 -->
          <section v-show="view === 'raw'" class="tab-pane">
            <div class="doc-selector">
              <button class="time-btn" :class="{ active: focusKind === 'eod' }" :disabled="!eodDoc"
                @click="setFocus('eod')">📌 EOD 日级</button>
              <button v-for="slot in slots" :key="slot.slotTime || ''" class="time-btn"
                :class="{ active: focusKind === 'slot' && focusSlotTime === slot.slotTime }"
                @click="setFocus('slot', slot.slotTime)">{{ slot.slotTime }}</button>
            </div>
            <div v-if="!focusDoc" class="empty-row">选择槽位或 EOD 查看原始返回</div>
            <template v-else>
              <div class="raw-meta">
                <span v-for="item in rawMetaItems" :key="item.label" class="raw-meta-item">
                  <span class="raw-meta-label">{{ item.label }}</span>{{ item.value ?? '--' }}
                </span>
              </div>
              <details class="raw-block" open>
                <summary>信封元信息（responseRaw.result 元数据）</summary>
                <pre v-if="rawEnvelopeText" class="raw-json">{{ rawEnvelopeText }}</pre>
                <div v-else class="empty-row">responseRaw 缺失（降级/旧文档路径未保存）</div>
              </details>
              <details class="raw-block" :open="!rawResponseText">
                <summary>模型原始返回 responseRaw（完整）</summary>
                <pre v-if="rawResponseText" class="raw-json">{{ rawResponseText }}</pre>
                <div v-else class="empty-row">responseRaw 缺失（降级/旧文档路径未保存）</div>
              </details>
              <details class="raw-block">
                <summary>下发题集 questionsRaw（对照题目演进）</summary>
                <pre v-if="rawQuestionsText" class="raw-json">{{ rawQuestionsText }}</pre>
                <div v-else class="empty-row">questionsRaw 缺失</div>
              </details>
              <details class="raw-block">
                <summary>结构化证据 evidenceRaw（槽位文档）</summary>
                <template v-if="evidenceGroups.length">
                  <div v-for="group in evidenceGroups" :key="group.key" class="evidence-group">
                    <div class="evidence-group-title">{{ group.key }}</div>
                    <pre class="raw-json">{{ group.text }}</pre>
                  </div>
                </template>
                <div v-else class="empty-row">evidenceRaw 缺失（EOD 文档不落证据、旧文档可能缺失）</div>
              </details>
            </template>
          </section>

          <!-- ⑦ 涨停复盘：打标轨道研究↔展示同步（个股四题 + 日级相位哨兵，独立读口 fail-visible；表格语言对齐池换手 2026-10-04） -->
          <section v-show="view === 'limitup'" class="tab-pane">
            <div v-if="limitUpLoading" class="empty-row">涨停复盘加载中…</div>
            <div v-else-if="limitUpError" class="state-block error">
              ⚠️ {{ limitUpError }}
              <button class="retry-btn" @click="selectedDate && ensureLimitUp(selectedDate)">重试</button>
            </div>
            <div v-else-if="!selectedDate" class="empty-row">窗口内无选中交易日</div>
            <div v-else-if="limitUpDay?.noData" class="empty-row">{{ limitUpDay.reason ?? '该日无涨停打标文档' }}</div>
            <template v-else-if="limitUpDay">
              <div class="limitup-phase-card">
                <div class="limitup-phase-title">🛡️ 日级相位哨兵 · {{ limitUpDay.date }}</div>
                <div class="limitup-phase-band">{{ limitUpDay.phase ? (JEV_PHASE_BAND_NAMES[limitUpDay.phase.band ?? ''] ?? limitUpDay.phase.band) : '未判（哨兵未跑或缺失）' }}</div>
                <div v-if="limitUpDay.phase?.probabilities" class="limitup-phase-probs">
                  <span v-for="(prob, key) in limitUpDay.phase.probabilities" :key="key" class="limitup-prob-chip">
                    {{ JEV_PHASE_BAND_NAMES[String(key)] ?? key }} {{ Math.round(Number(prob) * 100) }}%
                  </span>
                </div>
              </div>
              <div class="limitup-phase-note">
                相位分线列口径：{{ limitUpHasStockPhase ? '个股自身相位位（市场哨兵带见上方卡片）' : '日级哨兵带（市场级，当日未跑个股相位）' }}
              </div>
              <div class="limitup-header">
                <div class="limitup-filters">
                  <button class="limitup-filter-btn" :class="{ active: limitUpDriverFilter === '' }"
                    @click="limitUpDriverFilter = ''">全部 {{ limitUpDay.summary.total }}</button>
                  <button v-for="(count, key) in limitUpDay.summary.label" :key="`l-${key}`" class="limitup-filter-btn"
                    :class="{ active: limitUpDriverFilter === String(key) }" @click="limitUpDriverFilter = String(key)">
                    {{ JEV_DRIVER_NAMES[String(key)] ?? key }} {{ count }}
                  </button>
                </div>
                <span class="limitup-stats">显示 {{ filteredLimitUpStocks.length }} / {{ limitUpDay.summary.total }} 只</span>
              </div>
              <div class="limitup-controls">
                <div class="search-box">
                  <input type="text" v-model="limitUpSearch" placeholder="搜索股票代码或名称..." class="search-input" />
                  <span v-if="limitUpSearch" class="search-clear" @click="limitUpSearch = ''">✕</span>
                </div>
                <div class="sort-controls">
                  <select v-model="limitUpSortKey" class="sort-select">
                    <option value="phase">相位档</option>
                    <option value="rank">热榜排名</option>
                    <option value="labelConf">驱动置信</option>
                    <option value="phaseConf">相位置信</option>
                    <option value="name">名称</option>
                    <option value="code">代码</option>
                    <option value="label">驱动</option>
                    <option value="depth">深度</option>
                    <option value="freshness">新鲜度</option>
                    <option value="buySide">买盘逻辑</option>
                    <option value="board">板块</option>
                  </select>
                  <button class="sort-btn" @click="limitUpSortDesc = !limitUpSortDesc">
                    {{ limitUpSortDesc ? '↓ 降序' : '↑ 升序' }}
                  </button>
                </div>
              </div>
              <div class="limitup-table-container" v-if="filteredLimitUpStocks.length">
                <table class="limitup-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th class="sortable" @click="setLimitUpSort('name')">名称{{ limitUpSortMark('name') }}</th>
                      <th class="sortable" @click="setLimitUpSort('code')">代码{{ limitUpSortMark('code') }}</th>
                      <th class="sortable" @click="setLimitUpSort('label')">驱动{{ limitUpSortMark('label') }}</th>
                      <th class="sortable" @click="setLimitUpSort('labelConf')">驱动置信{{ limitUpSortMark('labelConf') }}</th>
                      <th class="sortable" @click="setLimitUpSort('depth')">深度{{ limitUpSortMark('depth') }}</th>
                      <th class="sortable" @click="setLimitUpSort('freshness')">新鲜度{{ limitUpSortMark('freshness') }}</th>
                      <th class="sortable" @click="setLimitUpSort('buySide')">买盘逻辑{{ limitUpSortMark('buySide') }}</th>
                      <th class="sortable" @click="setLimitUpSort('board')">板块{{ limitUpSortMark('board') }}</th>
                      <th class="sortable" @click="setLimitUpSort('rank')">热榜{{ limitUpSortMark('rank') }}</th>
                      <th class="sortable" @click="setLimitUpSort('phase')">相位分线{{ limitUpSortMark('phase') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(stock, i) in filteredLimitUpStocks" :key="stock.code">
                      <td class="num">{{ i + 1 }}</td>
                      <td>{{ stock.name ?? '--' }}</td>
                      <td><span class="limitup-code">{{ stock.code }}</span></td>
                      <td>{{ stock.label ? (JEV_DRIVER_NAMES[stock.label] ?? stock.label) : '--' }}</td>
                      <td class="num">{{ topProbability(stock.labelProbabilities, stock.label) }}</td>
                      <td>{{ stock.catalystDepth ? (JEV_DEPTH_NAMES[stock.catalystDepth] ?? stock.catalystDepth) : '--' }}</td>
                      <td>{{ stock.freshness ? (JEV_FRESHNESS_NAMES[stock.freshness] ?? stock.freshness) : '--' }}</td>
                      <td>{{ stock.buySideLogic ? (JEV_BUYSIDE_NAMES[stock.buySideLogic] ?? stock.buySideLogic) : '--' }}</td>
                      <td>{{ stock.board ?? '--' }}</td>
                      <td class="num">{{ stock.inHotlist ? `#${stock.rank ?? '--'}` : '未进' }}</td>
                      <td class="num" :title="stockPhaseCellTitle(stock)">{{ stockPhaseCell(stock) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-else class="empty-row">该驱动类型下暂无个股</div>
            </template>
          </section>

          <!-- 题材龙头：v2 题目集 + 实际投喂语料可见性（2026-10-20） -->
          <section v-show="view === 'themeLeader'" class="tab-pane">
            <div v-if="themeLeaderLoading" class="empty-row">题材龙头投喂加载中…</div>
            <div v-else-if="themeLeaderError" class="state-block error">
              ⚠️ {{ themeLeaderError }}
              <button class="retry-btn" @click="selectedDate && ensureThemeLeaders(selectedDate)">重试</button>
            </div>
            <div v-else-if="!selectedDate" class="empty-row">窗口内无选中交易日</div>
            <div v-else-if="themeLeaderDay?.no_data" class="empty-row">
              {{ themeLeaderDay.date }} 无题材龙头投喂记录（该日未跑 16:20 槽位或未回填）
            </div>
            <template v-else-if="themeLeaderDay">
              <div class="tl-meta">
                <span class="tl-meta-chip">题目集 {{ themeLeaderDay.versions ? Object.keys(themeLeaderDay.versions).join('/') : '-' }} · {{ themeLeaderDay.questionSetHash ?? '-' }}</span>
                <span class="tl-meta-chip">原料 {{ themeLeaderDay.ammoVersion ?? '-' }}</span>
                <span class="tl-meta-chip">共 {{ themeLeaderDay.count }} 只</span>
                <span class="tl-meta-chip" :class="{ warn: themeLeaderDay.gatedCount > 0 }">证据门覆盖 {{ themeLeaderDay.gatedCount }}</span>
                <span class="tl-meta-chip">结局已封 {{ themeLeaderDay.sealedCount }}/{{ themeLeaderDay.count }}</span>
                <span v-for="(n, origin) in themeLeaderDay.origins" :key="`o-${origin}`" class="tl-meta-chip"
                  :class="{ warn: origin === 'backfill' }">
                  {{ origin === 'backfill' ? '回填（含未来信息）' : '前瞻' }} {{ n }}
                </span>
              </div>
              <div v-if="themeLeaderDay.mixedVersions" class="tl-warn-row">
                ⚠️ 该日存在多代际标签（{{ Object.entries(themeLeaderDay.versions).map(([v, n]) => `${v}=${n}`).join('，') }}），跨代不可比较
              </div>
              <div class="limitup-controls">
                <div class="search-box">
                  <input type="text" v-model="themeLeaderSearch" placeholder="搜索代码/名称/板块..." class="search-input" />
                  <span v-if="themeLeaderSearch" class="search-clear" @click="themeLeaderSearch = ''">✕</span>
                </div>
                <div class="sort-controls">
                  <select v-model="themeLeaderOriginFilter" class="sort-select">
                    <option value="">全部来源</option>
                    <option value="live">仅前瞻</option>
                    <option value="backfill">仅回填</option>
                  </select>
                </div>
              </div>
              <div class="limitup-table-container" v-if="filteredThemeLeaders.length">
                <table class="limitup-table tl-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>板块</th>
                      <th>龙头</th>
                      <th>连板</th>
                      <th>封板</th>
                      <th>家数</th>
                      <th>续板概率</th>
                      <th>档位</th>
                      <th>模型原答</th>
                      <th>催化阶段</th>
                      <th>题材证据</th>
                      <th>同桶基线</th>
                      <th>结局</th>
                      <th>语料</th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(row, i) in filteredThemeLeaders" :key="row.code">
                      <tr :class="{ 'tl-row-backfill': row.sampleOrigin === 'backfill' }">
                        <td class="num">{{ i + 1 }}</td>
                        <td>{{ row.board ?? '-' }}</td>
                        <td>{{ row.name ?? '-' }} <span class="limitup-code">{{ row.code }}</span></td>
                        <td class="num">{{ row.streak ?? '-' }}</td>
                        <td class="num">{{ row.time ?? '-' }}</td>
                        <td class="num">{{ row.boardN ?? '-' }}</td>
                        <td class="num">{{ themeContinueProb(row) }}</td>
                        <td>
                          <span :class="['tl-choice', `tl-choice-${row.choice ?? 'none'}`]">
                            {{ THEME_LEADER_CHOICE_NAMES[row.choice ?? ''] ?? row.choice ?? '-' }}
                          </span>
                        </td>
                        <td :title="row.gate?.label ?? ''">
                          <template v-if="row.modelChoice && row.modelChoice !== row.choice">
                            <span class="tl-overridden">{{ THEME_LEADER_CHOICE_NAMES[row.modelChoice] ?? row.modelChoice }}</span>
                            <span class="tl-gate-tag">{{ THEME_GATE_NAMES[row.gate?.reason ?? ''] ?? row.gate?.reason }}</span>
                          </template>
                          <span v-else class="tl-same">同档位</span>
                        </td>
                        <td>{{ row.catalystStage ?? '-' }}</td>
                        <td :title="(row.evidenceEventTitles ?? []).join('\n')">
                          {{ row.evidenceIndustry ?? (row.evidenceMissingReason ? `缺失：${THEME_GATE_NAMES[row.evidenceMissingReason] ?? row.evidenceMissingReason}` : '已映射') }}
                        </td>
                        <td class="num" :title="`窗口 ${row.baselineMeta?.start ?? '-'} ~ ${row.baselineMeta?.end ?? '-'}（${row.baselineMeta?.rows ?? 0} 样本）`">
                          {{ row.baselineKey ?? '-' }}
                        </td>
                        <td class="num">
                          <span v-if="row.outcomeSealedNextDay === null" class="tl-unsealed">未封</span>
                          <span v-else-if="row.outcomeSealedNextDay" class="tl-win">续板</span>
                          <span v-else class="tl-lose">未续</span>
                        </td>
                        <td>
                          <button class="retry-btn" @click="toggleThemeNarrative(row.code)">
                            {{ themeLeaderOpenCode === row.code ? '收起' : '查看' }}
                          </button>
                        </td>
                      </tr>
                      <tr v-if="themeLeaderOpenCode === row.code" class="tl-narrative-row">
                        <td colspan="14">
                          <div class="tl-narrative-title">实际投喂语料（{{ row.questionSetVersion }} · {{ row.questionSetHash }}）</div>
                          <pre v-if="themeLeaderNarratives[row.code]?.missing" class="tl-narrative">（该档未存投喂语料：旧文档或降级路径未落 narrative；可重跑后回看）</pre>
                          <pre v-else class="tl-narrative">{{ themeLeaderNarratives[row.code]?.narrative ?? '加载中…' }}</pre>
                          <div v-if="row.modelChoice && row.modelChoice !== row.choice" class="tl-gate-note">
                            证据门覆盖：模型原答 {{ THEME_LEADER_CHOICE_NAMES[row.modelChoice] ?? row.modelChoice }}
                            → 落库 {{ THEME_LEADER_CHOICE_NAMES[row.choice ?? ''] ?? row.choice }}
                            （{{ row.gate?.label ?? row.gate?.reason ?? '证据缺失' }}）
                          </div>
                        </td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
              <div v-else class="empty-row">该筛选下暂无龙头</div>
            </template>
          </section>
        </template>
      </div>
    </div>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  fetchHotlistJevLimitUpLabels,
  fetchHotlistJevThemeLeaders,
  fetchHotlistJevRange,
  fetchHotlistJevSeries,
  JEV_BUYSIDE_NAMES,
  JEV_CROWDING_NAMES,
  JEV_CROWDING_WARN_LAYERS,
  JEV_PATTERN_NAMES,
  JEV_PATTERN_ORDER,
  JEV_DEPTH_NAMES,
  JEV_DRIVER_NAMES,
  JEV_FRESHNESS_NAMES,
  JEV_PHASE_BAND_NAMES,
  JEV_STOCK_PHASE_NAMES,
  JEV_STAGE_NAMES,
  JEV_STAGE_ORDER,
  jevChoiceName,
  jevCrowdingProbability,
  jevScore,
} from '@/services/hotlist/hotlistJevApi'
import {
  anchorMetricsOfDoc,
  confidenceMetrics,
  crowdingTimeline,
  crowdingTransitions,
  countDegradedDocs,
  JEV_HESITANT_THRESHOLD,
  layerStats,
  LIMITUP_SORT_DEFAULT_DESC,
  parseNarrativeSections,
  sortLimitUpStocks,
  trimRangeWindow,
  type JevAnchorMetric,
  type JevConfidenceMetrics,
  type JevCrowdingPoint,
  type JevCrowdingTransition,
  type JevNarrativeProjection,
  type LimitUpSortKey,
} from '@/services/hotlist/jevNarrativeProjection'
import type {
  HotlistJevDoc,
  HotlistJevDayEntry,
  HotlistJevLimitUpDay,
  HotlistJevLimitUpStock,
  HotlistJevMissingDay,
  HotlistJevThemeLeaderDay,
  HotlistJevThemeLeaderRow,
} from '@/types/hotlistJev'

const props = defineProps<{ visible: boolean; triggerRect?: DOMRect | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const TABS = [
  { key: 'grid', label: '叙事概览', icon: '🧮' },
  { key: 'thermometer', label: '温度计', icon: '🌡️' },
  { key: 'crowding', label: '拥挤度', icon: '🧲' },
  { key: 'confidence', label: '置信度', icon: '🎯' },
  { key: 'narrative', label: '叙事全文', icon: '📜' },
  { key: 'raw', label: '原始返回', icon: '🧾' },
  { key: 'limitup', label: '涨停复盘', icon: '🏷️' },
  { key: 'themeLeader', label: '题材龙头', icon: '👑' },
] as const
type ViewKey = (typeof TABS)[number]['key']

const view = ref<ViewKey>('grid')
const loading = ref(false)
const loaded = ref(false)
const loadError = ref<string | null>(null)

// ---------- 时间窗与日期选择（窗口语义同热榜面板：1d=日内槽位，多日=EOD 日线） ----------
const TIME_WINDOWS = [
  { key: '1d', label: '1天', days: 1 },
  { key: '3d', label: '3日', days: 3 },
  { key: '1w', label: '1周', days: 5 },
  { key: '1m', label: '10日', days: 10 },
  { key: '30d', label: '30日', days: 30 },
] as const
type WindowKey = (typeof TIME_WINDOWS)[number]['key']
const windowKey = ref<WindowKey>('1d')
const windowDays = computed(() => TIME_WINDOWS.find((win) => win.key === windowKey.value)?.days ?? 1)

// ---------- jev 轨道数据（独立采集轨道；缺失/降级如实标注） ----------
const dayDocs = ref<HotlistJevDayEntry[]>([])
const missingDays = ref<HotlistJevMissingDay[]>([])
const daysLoaded = ref(0)
const rangeDegradedCount = ref(0)
const rangeError = ref<string | null>(null)
let rangeReqId = 0

const selectedDate = ref('')
const slots = ref<HotlistJevDoc[]>([])
const eodDoc = ref<HotlistJevDoc | null>(null)
const seriesDate = ref('')
const seriesError = ref<string | null>(null)
let seriesReqId = 0

const degradedReason = computed(() => rangeError.value || seriesError.value)
const missingDaysTitle = computed(
  () => missingDays.value.map((day) => `${day.tradingDate}：${day.reason ?? '无 jev 文档'}`).join('\n'),
)

async function ensureRange(days: number): Promise<boolean> {
  if (daysLoaded.value > 0 && dayDocs.value.length) {
    if (days === daysLoaded.value) return true
    if (days < daysLoaded.value) {
      // 窗口收缩：按快照交易日历就地裁剪缓存，内容必须随窗口变化（2026-10-08 评审修复）
      const trimmed = trimRangeWindow(days, { days: dayDocs.value, missingDays: missingDays.value })
      dayDocs.value = trimmed.days
      missingDays.value = trimmed.missingDays
      daysLoaded.value = days
      rangeDegradedCount.value = countDegradedDocs(dayDocs.value)
      return true
    }
  }
  const reqId = ++rangeReqId
  try {
    const result = await fetchHotlistJevRange(days)
    if (reqId !== rangeReqId) return false
    if (result.degraded) {
      rangeError.value = result.reason || 'jev 多日序列不可用'
      return false
    }
    dayDocs.value = result.days
    missingDays.value = result.missingDays
    rangeDegradedCount.value = result.degradedCount ?? 0
    daysLoaded.value = days
    rangeError.value = null
    return true
  } catch (err) {
    if (reqId === rangeReqId) rangeError.value = err instanceof Error ? err.message : '加载 jev 多日序列失败'
    return false
  }
}

async function ensureSeries(date?: string): Promise<boolean> {
  const reqId = ++seriesReqId
  try {
    const result = await fetchHotlistJevSeries(date || undefined)
    if (reqId !== seriesReqId) return false
    if (result.degraded) {
      // fail-visible：降级时清空旧日期数据，防止残留 slots 以新选中日期高亮误读
      slots.value = []
      eodDoc.value = null
      seriesDate.value = ''
      seriesError.value = result.reason || 'jev 单日序列不可用'
      return false
    }
    slots.value = result.slots
    eodDoc.value = result.eod
    seriesDate.value = result.date || ''
    seriesError.value = null
    return true
  } catch (err) {
    if (reqId === seriesReqId) seriesError.value = err instanceof Error ? err.message : '加载 jev 单日序列失败'
    return false
  }
}

async function loadAll() {
  if (loading.value) return
  loading.value = true
  loadError.value = null
  try {
    await ensureRange(windowDays.value)
    const targetDate = selectedDate.value || dayDocs.value[dayDocs.value.length - 1]?.tradingDate || ''
    await ensureSeries(targetDate || undefined)
    if (targetDate && !selectedDate.value) selectedDate.value = targetDate
    if (!focusSlotTime.value) focusSlotTime.value = latestSlotTime()
    loaded.value = !!slots.value.length || !!eodDoc.value || !!dayDocs.value.length
    // 全部读口不可用且无任何数据：错误态 + 重试（degraded 原因如实透出，不是“暂无数据”）
    if (!loaded.value) loadError.value = degradedReason.value || '窗口内无任何 jev 文档'
  } finally {
    loading.value = false
  }
}

function latestSlotTime(): string | null {
  return slots.value.length ? (slots.value[slots.value.length - 1]?.slotTime ?? null) : null
}

// ---------- 涨停复盘（打标轨道研究↔展示同步 2026-10-03；独立读口 fail-visible；表格语言对齐池换手 2026-10-04） ----------
const limitUpDay = ref<HotlistJevLimitUpDay | null>(null)
const limitUpLoading = ref(false)
const limitUpError = ref<string | null>(null)
const limitUpDriverFilter = ref('')
const limitUpSearch = ref('')
const limitUpSortKey = ref<LimitUpSortKey>('phase')
const limitUpSortDesc = ref(false)
let limitUpReqId = 0

async function ensureLimitUp(date: string) {
  if (!date || (limitUpDay.value?.date === date && !limitUpError.value)) return
  const reqId = ++limitUpReqId
  limitUpLoading.value = true
  limitUpError.value = null
  try {
    const result = await fetchHotlistJevLimitUpLabels(date)
    if (reqId !== limitUpReqId) return
    if (result.degraded || !result.day) {
      limitUpError.value = result.reason || '涨停复盘读口不可用'
      limitUpDay.value = null
    } else {
      limitUpDay.value = result.day
    }
  } finally {
    if (reqId === limitUpReqId) limitUpLoading.value = false
  }
}

watch([view, selectedDate], ([tab, date]) => {
  if (tab === 'limitup' && date) void ensureLimitUp(date)
})

// ---------- 题材龙头（v2 题目集投喂可见性，2026-10-20） ----------
// 存在理由：v2 判据与实际投喂语料必须在前端可见（AGENTS §1.2-5 研究↔展示同步）。
// 落库口径（过门后）与模型原答**双显**；回填样本（sampleOrigin=backfill）单独打标，
// 因为它含语料未来信息，不得当结论看。
const themeLeaderDay = ref<HotlistJevThemeLeaderDay | null>(null)
const themeLeaderLoading = ref(false)
const themeLeaderError = ref<string | null>(null)
const themeLeaderSearch = ref('')
const themeLeaderOriginFilter = ref('')
/** 展开查看投喂语料的个股 code（空=未展开） */
const themeLeaderOpenCode = ref('')
const themeLeaderNarratives = ref<Record<string, { narrative?: string | null; questionsRaw?: Record<string, unknown> | null; missing?: boolean }>>({})
let themeLeaderReqId = 0

const THEME_LEADER_CHOICE_NAMES: Record<string, string> = {
  high_ge65: '高 ≥65%',
  mid_45_65: '中 45-65%',
  low_25_45: '低 25-45%',
  verylow_lt25: '很低 <25%',
  insufficient: '证据不足',
}

const THEME_GATE_NAMES: Record<string, string> = {
  board_unmapped: '板块未映射',
  corpus_not_collected: '语料未采集',
  no_content_no_event: '无正文且无事件',
}

const filteredThemeLeaders = computed(() => {
  const rows = themeLeaderDay.value?.leaders ?? []
  const kw = themeLeaderSearch.value.trim().toLowerCase()
  return rows.filter((row) => {
    if (themeLeaderOriginFilter.value && row.sampleOrigin !== themeLeaderOriginFilter.value) return false
    if (!kw) return true
    return `${row.code}${row.name ?? ''}${row.board ?? ''}`.toLowerCase().includes(kw)
  })
})

function themeContinueProb(row: HotlistJevThemeLeaderRow): string {
  const probs = row.probabilities ?? {}
  if (!probs.insufficient || probs.insufficient < 0.999) {
    const sum = Object.entries(probs).reduce((acc, [key, val]) => (key === 'insufficient' ? acc : acc + Number(val)), 0)
    if (sum > 0) return `${Math.round(sum * 100)}%`
  }
  // P2 修复（2026-10-20 review）：门强制 insufficient（quality<1）与模型自判 insufficient
  // 都按「其余四档归一」显示，括号回退模型原答的双口径废除——统一为归一四档，无分可归
  // （模型也没答）时显「-」，原答在展开行「证据门覆盖」处双显（预登记口径不变）。
  return '-'
}

async function ensureThemeLeaders(date: string) {
  if (!date || (themeLeaderDay.value?.date === date && !themeLeaderError.value)) return
  const reqId = ++themeLeaderReqId
  themeLeaderLoading.value = true
  themeLeaderError.value = null
  themeLeaderOpenCode.value = ''
  // P1 修复（2026-10-20 review）：语料缓存必须按日隔离——连板股同 code 跨日重现时，
  // 旧缓存会让 B 日抽屉显示 A 日语料全文，且标题挂 B 日代际戳（内容与代际错配）。
  themeLeaderNarratives.value = {}
  try {
    const result = await fetchHotlistJevThemeLeaders(date)
    if (reqId !== themeLeaderReqId) return
    if (result.degraded || !result.day) {
      themeLeaderError.value = result.reason || '题材龙头读口不可用'
      themeLeaderDay.value = null
    } else {
      themeLeaderDay.value = result.day
    }
  } finally {
    if (reqId === themeLeaderReqId) themeLeaderLoading.value = false
  }
}

async function toggleThemeNarrative(code: string) {
  if (themeLeaderOpenCode.value === code) {
    themeLeaderOpenCode.value = ''
    return
  }
  themeLeaderOpenCode.value = code
  if (themeLeaderNarratives.value[code] || !selectedDate.value) return
  const result = await fetchHotlistJevThemeLeaders(selectedDate.value, true)
  if (result.degraded || !result.day) {
    // P2 修复（§4.0）：读口失败显式可重试，不伪装「加载中」
    themeLeaderNarratives.value = {
      ...themeLeaderNarratives.value,
      [code]: { narrative: null, questionsRaw: null, missing: true },
    }
    themeLeaderError.value = result.reason || '题材龙头读口不可用'
    return
  }
  const row = result.day.leaders.find((item) => item.code === code)
  // 命中但无 narrative（旧档/降级未保存）也明示缺失，不留永久中间态
  themeLeaderNarratives.value = {
    ...themeLeaderNarratives.value,
    [code]: row
      ? { narrative: row.narrative, questionsRaw: row.questionsRaw, missing: row.narrative == null }
      : { narrative: null, questionsRaw: null, missing: true },
  }
}

watch([view, selectedDate], ([tab, date]) => {
  if (tab === 'themeLeader' && date) void ensureThemeLeaders(date)
})

// 换日重置驱动过滤与搜索：不同日驱动类型集合可能不同，残留过滤会让列表假性为空
watch(selectedDate, () => {
  limitUpDriverFilter.value = ''
  limitUpSearch.value = ''
})

const filteredLimitUpStocks = computed(() => {
  let stocks = limitUpDay.value?.stocks ?? []
  if (limitUpDriverFilter.value) {
    stocks = stocks.filter((stock) => stock.label === limitUpDriverFilter.value)
  }
  const kw = limitUpSearch.value.trim().toLowerCase()
  if (kw) {
    stocks = stocks.filter((stock) =>
      (stock.name ?? '').toLowerCase().includes(kw) || stock.code.includes(kw))
  }
  return sortLimitUpStocks(stocks, limitUpSortKey.value, limitUpSortDesc.value)
})

// 表头点击排序：同列再点反转方向，换列按该维度默认方向（置信类降序在前）
function setLimitUpSort(key: LimitUpSortKey) {
  if (limitUpSortKey.value === key) {
    limitUpSortDesc.value = !limitUpSortDesc.value
  } else {
    limitUpSortKey.value = key
    limitUpSortDesc.value = LIMITUP_SORT_DEFAULT_DESC[key]
  }
}

function limitUpSortMark(key: LimitUpSortKey): string {
  if (limitUpSortKey.value !== key) return ''
  return limitUpSortDesc.value ? ' ↓' : ' ↑'
}

// 相位分线=日级哨兵带（相位是市场级判定，当日个股同值；哨兵缺失如实 '--'）
const limitUpPhaseName = computed(() => {
  const band = limitUpDay.value?.phase?.band
  return band ? (JEV_PHASE_BAND_NAMES[band] ?? band) : '--'
})

// 个股相位分线（2026-10-04 试点）：该股自身本轮行情位置；试点日已跑但个别降级如实「未判」，
// 未跑日整列回落日级哨兵带（市场级 fallback），口径注记随动防混读
const limitUpHasStockPhase = computed(() =>
  (limitUpDay.value?.stocks ?? []).some((stock) => !!stock.stockPhasePosition))

function stockPhaseCell(stock: HotlistJevLimitUpStock): string {
  if (stock.stockPhasePosition) {
    return JEV_STOCK_PHASE_NAMES[stock.stockPhasePosition] ?? stock.stockPhasePosition
  }
  return limitUpHasStockPhase.value ? '未判' : limitUpPhaseName.value
}

function stockPhaseCellTitle(stock: HotlistJevLimitUpStock): string {
  if (stock.stockPhasePosition) {
    const prob = stock.stockPhaseProbabilities?.[stock.stockPhasePosition]
    const pct = typeof prob === 'number' ? ` ${Math.round(prob * 100)}%` : ''
    return `个股自身相位位${pct}（判据：连板高度主锚+封板质量分歧修正）`
  }
  return limitUpHasStockPhase.value ? '个股相位当日判读失败（fail-visible）' : '日级哨兵带（市场级 fallback）'
}

function topProbability(probs: Record<string, number> | null, choice: string | null): string {
  if (!choice) return '--'
  const prob = probs?.[choice]
  return typeof prob === 'number' ? `${Math.round(prob * 100)}%` : '--'
}

async function setWindow(key: WindowKey) {
  if (windowKey.value === key) return
  windowKey.value = key
  await ensureRange(windowDays.value)
  // 窗口缩小时选中日可能出窗，回落最新日
  if (selectedDate.value && !dayDocs.value.some((day) => day.tradingDate === selectedDate.value)) {
    await selectDate(dayDocs.value[dayDocs.value.length - 1]?.tradingDate || '')
  }
  nextTick(() => renderAllCharts())
}

async function selectDate(date: string) {
  if (!date || selectedDate.value === date) return
  selectedDate.value = date
  await ensureSeries(date)
  focusSlotTime.value = latestSlotTime()
  nextTick(() => renderAllCharts())
}

function setFocus(kind: 'slot' | 'eod', slotTime?: string | null) {
  focusKind.value = kind
  if (kind === 'slot') focusSlotTime.value = slotTime ?? null
}

function switchTab(key: ViewKey) {
  view.value = key
  nextTick(() => renderAllCharts())
}

watch(
  () => props.visible,
  (visible) => {
    if (visible && !loaded.value && !loading.value) {
      loadAll().then(() => nextTick(() => renderAllCharts()))
    } else if (visible && loaded.value) {
      // 关闭→重开路径：容器被 v-if 重建，旧 echarts 实例已 stale，需重建图表
      nextTick(() => renderAllCharts())
    }
  },
  { immediate: true },
)

function close() {
  emit('close')
}

const panelStyle = computed(() => {
  const rect = props.triggerRect
  if (!rect) return { top: '100px', right: '20px' }
  const width = 960
  const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2))
  return { left: `${left}px`, top: `${Math.min(rect.bottom + 8, window.innerHeight - 520)}px` }
})

// ---------- 颜色语义（档位冷热/温度渐变/拥挤层色/置信梯度） ----------
const STAGE_COLORS: Record<string, string> = {
  冰点: '#4a90e2',
  退潮: '#7f8c8d',
  启动: '#ffb142',
  发酵: '#ff7f50',
  高潮: '#ff4757',
}
const CROWDING_NAMES = JEV_CROWDING_NAMES
const WARN_LAYERS = JEV_CROWDING_WARN_LAYERS
const CROWDING_ORDER = ['top_acceleration', 'late_seal_weakness', 'breadth_climax', 'crowd_clearing', 'no_crowding', 'insufficient_evidence']
const CROWDING_COLORS: Record<string, string> = {
  top_acceleration: '#ff4757',
  late_seal_weakness: '#ff9f43',
  breadth_climax: '#f39c12',
  crowd_clearing: '#4a90e2',
  no_crowding: '#2ed573',
  insufficient_evidence: '#7f8c8d',
}
const THERMO_TICKS = [0, 20, 40, 60, 80, 100]

function stageColor(name: string | null): string {
  return (name != null && STAGE_COLORS[name]) || 'var(--text-secondary)'
}

function crowdingColor(key: string | null): string {
  return (key != null && CROWDING_COLORS[key]) || 'transparent'
}

/** 温度 0-100 → 蓝(210°)→红(0°) 色相插值；缺失灰 */
function tempColor(value: number | null): string {
  if (value == null) return '#7f8c8d'
  const hue = Math.max(0, Math.min(210, 210 - 2.1 * value))
  return `hsl(${hue.toFixed(0)}, 72%, 52%)`
}

// ---------- 温度计 SVG 几何 ----------
const TUBE_TOP = 12
const TUBE_HEIGHT = 176

function thermoTickY(tick: number): number {
  return TUBE_TOP + TUBE_HEIGHT * (1 - tick / 100)
}

function thermoTubeY(value: number | null): number {
  if (value == null) return TUBE_TOP + TUBE_HEIGHT
  return TUBE_TOP + TUBE_HEIGHT * (1 - Math.max(0, Math.min(100, value)) / 100)
}

function thermoTubeH(value: number | null): number {
  if (value == null) return 0
  return TUBE_HEIGHT * (Math.max(0, Math.min(100, value)) / 100)
}

// ---------- 总览投影（hero 大卡 + 紧凑卡行，视觉对齐热榜情绪面板） ----------
const latestFrameName = computed(() => jevChoiceName(latestSlot.value, 'frame_stage'))
const latestConfidence = computed(() => confidenceMetrics(latestSlot.value?.answers?.sequence_stage))
const latestProbability = computed(() => latestConfidence.value.probability)
// 拥挤抗风险轴：拥挤三层概率合计（hotlistJevApi 唯一数值口径，透明聚合不伪造）
const latestCrowdingProb = computed(() => jevCrowdingProbability(latestSlot.value, 'crowding'))
const dayPatternName = computed(() => (eodDoc.value ? jevChoiceName(eodDoc.value, 'day_pattern') : null))
const heroSummary = computed(() => {
  const raw = latestSlot.value?.narrativeRaw
  // fail-visible 判据=narrativeRaw 整体缺失才标缺失；无【】导语但段头开头的旧文档不算缺失
  if (!raw) return '叙事缺失（降级/旧文档）'
  return parseNarrativeSections(raw).header || raw.slice(0, 60)
})

function tempGradient(value: number | null): string {
  if (value == null) return 'transparent'
  return `linear-gradient(90deg, ${tempColor(0)}, ${tempColor(value)})`
}

function confidenceColor(value: number | null): string {
  if (value == null) return '#7f8c8d'
  if (value >= 0.8) return '#2ed573'
  if (value >= JEV_HESITANT_THRESHOLD) return '#ffb142'
  return '#ff4757'
}

/** 置信进度条填充：灰→阈值语义色的起点渐变 */
function confidenceGradient(value: number | null): string {
  if (value == null) return 'transparent'
  return `linear-gradient(90deg, rgba(127, 140, 141, 0.35), ${confidenceColor(value)})`
}

/** 拥挤抗风险轴填充：绿（安全）→黄→红（拥挤）固定风险语义渐变，宽度=拥挤概率 */
function crowdingRiskGradient(): string {
  return 'linear-gradient(90deg, #2ed573, #ffb142 55%, #ff4757)'
}

function crowdingRiskColor(value: number | null): string {
  if (value == null) return '#7f8c8d'
  if (value >= 0.7) return '#ff4757'
  if (value >= 0.4) return '#ffb142'
  return '#2ed573'
}

interface SlotCard {
  slotTime: string
  frameName: string | null
  seqName: string | null
  temp: number | null
  layer: string | null
  layerName: string | null
  pText: string
  degraded: boolean
  noData: boolean
  title: string
}

const slotCards = computed<SlotCard[]>(() =>
  slots.value.map((slot) => {
    const metrics = confidenceMetrics(slot.answers?.sequence_stage)
    const answer = slot.answers?.crowding
    const layer = answer && answer.type === 'choice' ? answer.choice ?? null : null
    return {
      slotTime: slot.slotTime || '--',
      frameName: jevChoiceName(slot, 'frame_stage'),
      seqName: jevChoiceName(slot, 'sequence_stage'),
      temp: jevScore(slot, 'temperature'),
      layer,
      layerName: layer ? (CROWDING_NAMES[layer] ?? layer) : null,
      pText:
        metrics.probability != null
          ? `P${Math.round(metrics.probability * 100)}%`
          : metrics.noDistribution
            ? '无分布'
            : '--',
      degraded: slot.status === 'degraded',
      noData: slot.status === 'no_data',
      title: [
        slot.slotTime,
        slot.status === 'degraded' ? `降级：${slot.errorCode || ''} ${slot.errorDetail || ''}`.trim() : '',
        `帧 ${jevChoiceName(slot, 'frame_stage') ?? '--'}`,
        `序列 ${jevChoiceName(slot, 'sequence_stage') ?? '--'}`,
        `温度 ${jevScore(slot, 'temperature') ?? '--'}`,
      ]
        .filter(Boolean)
        .join(' · '),
    }
  }),
)

// ---------- 温度计投影 ----------
const latestSlot = computed(() => (slots.value.length ? slots.value[slots.value.length - 1] : null))
const latestTemperature = computed(() => jevScore(latestSlot.value, 'temperature'))
const latestSlotStageName = computed(() => jevChoiceName(latestSlot.value, 'sequence_stage'))
const dayTemperature = computed(() => jevScore(eodDoc.value, 'day_temperature'))
const eodDayStageName = computed(() => (eodDoc.value ? jevChoiceName(eodDoc.value, 'day_stage') : null))

const focusKind = ref<'slot' | 'eod'>('slot')
const focusSlotTime = ref<string | null>(null)

const focusDoc = computed<HotlistJevDoc | null>(() => {
  if (focusKind.value === 'eod') return eodDoc.value
  if (focusSlotTime.value == null) return latestSlot.value
  return slots.value.find((slot) => slot.slotTime === focusSlotTime.value) ?? latestSlot.value ?? null
})

interface ThermoPoint {
  label: string
  value: number | null
  stage: string
  status: string
}

const thermoPoints = computed<ThermoPoint[]>(() => {
  if (windowKey.value === '1d') {
    return slots.value.map((slot) => ({
      label: slot.slotTime || '--',
      value: jevScore(slot, 'temperature'),
      stage: jevChoiceName(slot, 'sequence_stage') ?? '',
      status: slot.status || 'ok',
    }))
  }
  return dayDocs.value.map((day) => ({
    label: day.tradingDate.slice(5),
    value: day.eod ? jevScore(day.eod, 'day_temperature') : null,
    stage: day.eod ? (jevChoiceName(day.eod, 'day_stage') ?? '') : '',
    status: day.eod ? 'ok' : 'no_data',
  }))
})

// ---------- 拥挤度投影 ----------
const crowdingPoints = computed(() => crowdingTimeline(slots.value))
const latestCrowding = computed(() =>
  crowdingPoints.value.length ? crowdingPoints.value[crowdingPoints.value.length - 1] : null)
/** EOD 日级归层点（day_crowding；点击联动详情与选中日概览 chip 共用） */
function crowdingPointOfEodDoc(doc: HotlistJevDoc): JevCrowdingPoint {
  const answer = doc.answers?.day_crowding
  const choice = answer && answer.type === 'choice' ? answer.choice ?? null : null
  const probabilities = answer && answer.type === 'choice' ? answer.probabilities ?? null : null
  const probability =
    choice != null && probabilities && typeof probabilities[choice] === 'number'
      ? (probabilities[choice] as number)
      : null
  return {
    slotTime: 'EOD',
    status: doc.status || 'ok',
    layer: choice,
    layerName: choice ? (CROWDING_NAMES[choice] ?? choice) : null,
    warn: choice != null && WARN_LAYERS.has(choice),
    probability,
    confidence:
      answer && answer.type === 'choice' && typeof answer.confidence === 'number' ? answer.confidence : null,
    probabilities,
  }
}

const eodCrowdingPoint = computed<JevCrowdingPoint | null>(() =>
  eodDoc.value ? crowdingPointOfEodDoc(eodDoc.value) : null,
)
const crowdingTransitionList = computed(() => crowdingTransitions(crowdingPoints.value))
const daySlotLayerStats = computed(() => layerStats(slots.value, 'slot'))
const windowLayerStats = computed(() =>
  layerStats(dayDocs.value.map((day) => day.eod).filter((eod): eod is HotlistJevDoc => !!eod), 'eod'))

// ---------- 拥挤度柱状图投影（置信度页签同语言：窗口自适应历史维度） ----------
// 柱=所选层概率（top1，柱色=归层色）；线=拥挤抗风险（三层概率合计，概览 hero 同口径）
const CROWDING_BARS_INDICATORS = [
  { key: 'probability', label: '所选层概率', icon: '📊', type: 'bar' },
  { key: 'risk', label: '拥挤抗风险', icon: '🛡️', type: 'line', color: '#ff9f43' },
] as const
type CrowdingBarKey = (typeof CROWDING_BARS_INDICATORS)[number]['key']

interface CrowdingBarPoint {
  /** 点击联动唯一键：1天=slotTime（EOD 列='EOD'）；多日=完整 tradingDate */
  key: string
  label: string
  degraded: boolean
  noData: boolean
  /** 多日窗口：EOD 文档未生成（与单题答案缺失可区分） */
  eodMissing?: boolean
  layer: string | null
  layerName: string | null
  warn: boolean
  /** 所选层概率（top1，百分数 0-100；缺失 null 断柱不补 0） */
  probability: number | null
  /** 拥挤抗风险=三层概率合计（百分数 0-100，hero 同口径） */
  risk: number | null
  /** 模型置信（百分数） */
  confidence: number | null
  margin: number | null
  entropy: number | null
  /** 全层概率分布（tooltip 摘要用） */
  probabilities: Record<string, number> | null
}

const crowdingBarPoints = computed<CrowdingBarPoint[]>(() => {
  const ofDoc = (doc: HotlistJevDoc, key: string, label: string, isEod: boolean): CrowdingBarPoint => {
    const answerKey = isEod ? 'day_crowding' : 'crowding'
    const answer = doc.answers?.[answerKey]
    const metrics: JevConfidenceMetrics = confidenceMetrics(answer)
    const choice = answer && answer.type === 'choice' ? answer.choice ?? null : null
    const probabilities = answer && answer.type === 'choice' ? answer.probabilities ?? null : null
    const topProb =
      choice != null && probabilities && typeof probabilities[choice] === 'number' ? probabilities[choice] : null
    const riskRaw = jevCrowdingProbability(doc, answerKey)
    return {
      key,
      label,
      degraded: doc.status === 'degraded',
      noData: doc.status === 'no_data',
      layer: choice,
      layerName: choice ? (CROWDING_NAMES[choice] ?? choice) : null,
      warn: choice != null && WARN_LAYERS.has(choice),
      probability: topProb != null ? Math.round(topProb * 100) : null,
      risk: riskRaw != null ? Math.round(riskRaw * 100) : null,
      confidence: metrics.confidence != null ? Math.round(metrics.confidence * 100) : null,
      margin: metrics.margin,
      entropy: metrics.entropy,
      probabilities,
    }
  }
  if (windowKey.value === '1d') {
    const out = slots.value.map((slot) => ofDoc(slot, slot.slotTime || '--', slot.slotTime || '--', false))
    if (eodDoc.value) out.push(ofDoc(eodDoc.value, 'EOD', 'EOD', true))
    return out
  }
  // 多日窗口：每日 EOD 日级归层（与叙事概览日级柱图同数据源；EOD 未生成日整列断线如实标注）
  return dayDocs.value.map((day) =>
    day.eod
      ? ofDoc(day.eod, day.tradingDate, day.tradingDate.slice(5), true)
      : {
          key: day.tradingDate,
          label: day.tradingDate.slice(5),
          degraded: false,
          noData: false,
          eodMissing: true,
          layer: null,
          layerName: null,
          warn: false,
          probability: null,
          risk: null,
          confidence: null,
          margin: null,
          entropy: null,
          probabilities: null,
        },
  )
})

const crowdingBarIndicators = ref<CrowdingBarKey[]>(CROWDING_BARS_INDICATORS.map((indicator) => indicator.key))

function toggleCrowdingBar(key: CrowdingBarKey) {
  const current = crowdingBarIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白（同历史对比页签）
    crowdingBarIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    crowdingBarIndicators.value = CROWDING_BARS_INDICATORS.map((indicator) => indicator.key).filter(
      (k) => current.includes(k) || k === key,
    )
  }
  nextTick(() => renderCrowdingBarChart())
}

// ---------- 点击联动详情（jev 观察轨道页签同语言：点柱选点，详情卡默认最新、选中键失配回落最新） ----------
const selectedCrowdingKey = ref<string | null>(null)

/** 解析后的实际选中键：1天默认=最新槽（非 EOD 列）；多日默认=最新日；点击键失效（跨窗口换代）回落默认 */
const crowdingSelectedKey = computed<string | null>(() => {
  const points = crowdingBarPoints.value
  if (!points.length) return null
  const hit = selectedCrowdingKey.value ? points.find((p) => p.key === selectedCrowdingKey.value) : null
  if (hit) return hit.key
  if (windowKey.value === '1d') {
    const slotPoints = points.filter((p) => p.key !== 'EOD')
    return (slotPoints.length ? slotPoints[slotPoints.length - 1] : points[points.length - 1]).key
  }
  return points[points.length - 1].key
})

interface CrowdingDetailState {
  /** waffle 卡标题：默认「最新槽归层 · 15:00」；点击后「{slotTime|EOD} 归层」「{MM-DD} 归层 · …」 */
  waffleTitle: string
  /** waffle 归层点（JevCrowdingPoint 同构；null=选中点无任何归层文档，如实占位） */
  point: JevCrowdingPoint | null
  /** 槽位层统计卡标题：1天=「当日槽位层统计」；多日=「{MM-DD} 槽位层统计」 */
  layerStatsLabel: string
  /** 选中点日粒度槽位层统计；null=该日无槽位文档（统计不可算，如实标注） */
  layerStatsData: ReturnType<typeof layerStats> | null
  transitions: JevCrowdingTransition[]
}

const crowdingDetail = computed<CrowdingDetailState | null>(() => {
  if (!crowdingBarPoints.value.length) return null
  const selectedKey = crowdingSelectedKey.value
  if (windowKey.value === '1d') {
    // 1天窗口：waffle 跟随选中槽/EOD；层统计与层迁移固定当日 slots 口径（换日由顶部日期按钮承担）
    const slotPoints = crowdingPoints.value
    const point =
      selectedKey === 'EOD'
        ? eodCrowdingPoint.value
        : slotPoints.find((p) => p.slotTime === selectedKey) ??
          (slotPoints.length ? slotPoints[slotPoints.length - 1] : eodCrowdingPoint.value)
    const isLatestSlot = point != null && slotPoints.length > 0 && point === slotPoints[slotPoints.length - 1]
    return {
      waffleTitle: point == null
        ? '归层缺失'
        : point.slotTime === 'EOD' || (isLatestSlot && !slotPoints.length)
          ? 'EOD 归层'
          : isLatestSlot
            ? `最新槽归层 · ${point.slotTime}`
            : `${point.slotTime} 归层`,
      point,
      layerStatsLabel: '当日槽位层统计',
      layerStatsData: daySlotLayerStats.value,
      transitions: crowdingTransitionList.value,
    }
  }
  // 多日窗口：点击某日柱 → 该日 slots 驱动槽位层统计/最新槽 waffle/层迁移（dayDocs 每日含完整槽位文档）
  const day = dayDocs.value.find((d) => d.tradingDate === selectedKey) ?? dayDocs.value[dayDocs.value.length - 1] ?? null
  if (!day) return null
  const daySlotPoints = crowdingTimeline(day.slots)
  const dayLatest = daySlotPoints.length ? daySlotPoints[daySlotPoints.length - 1] : null
  const dayEodPoint = day.eod ? crowdingPointOfEodDoc(day.eod) : null
  return {
    waffleTitle: `${day.tradingDate.slice(5)} 归层 · ${dayLatest ? dayLatest.slotTime : 'EOD'}`,
    point: dayLatest ?? dayEodPoint,
    layerStatsLabel: `${day.tradingDate.slice(5)} 槽位层统计`,
    layerStatsData: day.slots.length ? layerStats(day.slots, 'slot') : null,
    transitions: crowdingTransitions(daySlotPoints),
  }
})

/** waffle 方格：每层概率 × 100 格按层色填充；概率合计不足 1 时剩余格留空（如实呈现未归一分布） */
function waffleSquares(probabilities: Record<string, number>): string[] {
  const squares: string[] = []
  for (const key of CROWDING_ORDER) {
    const value = probabilities[key]
    const count = typeof value === 'number' && value > 0 ? Math.round(value * 100) : 0
    for (let i = 0; i < count; i += 1) squares.push(CROWDING_COLORS[key] ?? '#7f8c8d')
  }
  while (squares.length < 100) squares.push('transparent')
  return squares.slice(0, 100)
}

function waffleLegend(
  probabilities: Record<string, number>,
): Array<{ name: string; color: string; pctText: string }> {
  return CROWDING_ORDER.map((key) => {
    const value = probabilities[key]
    return {
      name: CROWDING_NAMES[key] ?? key,
      color: CROWDING_COLORS[key] ?? '#7f8c8d',
      pctText: typeof value === 'number' ? `${Math.round(value * 100)}%` : '--',
    }
  })
}

// ---------- 置信度投影（ECharts 柱状图，展现形式对齐热榜情绪·历史对比页签） ----------
// 1天窗口=槽位级四题（X=槽位）；多日窗口=EOD 日级三题（X=交易日）——随顶部窗口选择器自动切换历史维度
// 柱=choice 题 P（top 概率）；线=score 题 C（模型置信，不套 P 概率语义）——同历史对比「柱+线双语言」的口径区分
const CONF_BARS_INDICATORS = [
  { key: 'frame_stage', label: '当前帧档', icon: '📊', type: 'bar', color: '#ffd700' },
  { key: 'sequence_stage', label: '序列档', icon: '📈', type: 'bar', color: '#ff7f50' },
  { key: 'temperature', label: '温度(score)', icon: '🌡️', type: 'line', color: '#4a90e2' },
  { key: 'crowding', label: '拥挤归层', icon: '⭕', type: 'bar', color: '#2ed573' },
] as const
// 日级题目（多日窗口）：EOD 文档三题，与叙事概览日级柱图同数据源；day_pattern 名进 tooltip 不上图
const CONF_BARS_DAILY_INDICATORS = [
  { key: 'day_stage', label: '日级档', icon: '📈', type: 'bar', color: '#ff7f50' },
  { key: 'day_temperature', label: '日温度', icon: '🌡️', type: 'line', color: '#4a90e2' },
  { key: 'day_crowding', label: '日拥挤', icon: '⭕', type: 'bar', color: '#2ed573' },
] as const

type ConfidenceBarKey = (typeof CONF_BARS_INDICATORS)[number]['key'] | (typeof CONF_BARS_DAILY_INDICATORS)[number]['key']
type ConfidenceBarType = 'bar' | 'line'

interface ConfidenceBarQuestion {
  key: ConfidenceBarKey
  label: string
  icon: string
  type: ConfidenceBarType
  color: string
}

interface ConfidenceBarCell {
  kind: 'choice' | 'score' | 'missing'
  /** 柱/线取值：choice=P top 概率、score=C 模型置信（百分数 0-100）；缺失/无分布 null，断线不补 0 */
  value: number | null
  choiceName: string | null
  confidence: number | null
  margin: number | null
  entropy: number | null
  hesitant: boolean
  noDist: boolean
}

interface ConfidenceBarPoint {
  label: string
  degraded: boolean
  cells: Partial<Record<ConfidenceBarKey, ConfidenceBarCell>>
  /** 多日窗口：EOD 文档未生成（日级答案整体缺失，与单题答案缺失可区分） */
  eodMissing?: boolean
  /** 多日窗口：路径形态名（day_pattern，只进 tooltip） */
  patternName?: string | null
}

const confBarsActiveQuestions = computed<readonly ConfidenceBarQuestion[]>(() =>
  windowKey.value === '1d' ? CONF_BARS_INDICATORS : CONF_BARS_DAILY_INDICATORS,
)

function confidenceChoiceName(questionKey: string, choice: string | null): string | null {
  if (!choice) return null
  const names = questionKey.includes('crowding') ? CROWDING_NAMES : JEV_STAGE_NAMES
  return names[choice] ?? choice
}

function confidenceCellOf(
  questionKey: string,
  answer: Parameters<typeof confidenceMetrics>[0],
): ConfidenceBarCell {
  const metrics: JevConfidenceMetrics = confidenceMetrics(answer)
  if (metrics.kind === 'missing') {
    return {
      kind: 'missing', value: null, choiceName: null,
      confidence: null, margin: null, entropy: null, hesitant: false, noDist: false,
    }
  }
  return {
    kind: metrics.kind,
    value:
      metrics.kind === 'score'
        ? metrics.confidence != null
          ? Math.round(metrics.confidence * 100)
          : null
        : metrics.probability != null
          ? Math.round(metrics.probability * 100)
          : null,
    choiceName: confidenceChoiceName(questionKey, metrics.choice),
    confidence: metrics.confidence,
    margin: metrics.margin,
    entropy: metrics.entropy,
    hesitant: metrics.hesitant,
    noDist: metrics.noDistribution,
  }
}

const confidenceBarsPoints = computed<ConfidenceBarPoint[]>(() => {
  if (windowKey.value === '1d') {
    return slots.value.map((slot) => {
      const cells: Partial<Record<ConfidenceBarKey, ConfidenceBarCell>> = {}
      for (const question of CONF_BARS_INDICATORS) {
        cells[question.key] = confidenceCellOf(question.key, slot.answers?.[question.key])
      }
      return { label: slot.slotTime || '--', degraded: slot.status === 'degraded', cells }
    })
  }
  // 多日窗口：EOD 日级答案（与叙事概览日级柱图同数据源；EOD 未生成日整列断线如实标注）
  return dayDocs.value.map((day) => {
    const eod = day.eod
    const cells: Partial<Record<ConfidenceBarKey, ConfidenceBarCell>> = {}
    for (const question of CONF_BARS_DAILY_INDICATORS) {
      cells[question.key] = confidenceCellOf(question.key, eod?.answers?.[question.key])
    }
    return {
      label: day.tradingDate.slice(5),
      degraded: eod?.status === 'degraded',
      cells,
      eodMissing: !eod,
      patternName: eod ? (jevChoiceName(eod, 'day_pattern') ?? null) : null,
    }
  })
})

const confidenceBarIndicators = ref<ConfidenceBarKey[]>(CONF_BARS_INDICATORS.map((question) => question.key))

// 窗口 1天↔多日 切换时题目集合整体换代：当前选择含已换代旧题时重置为全选；
// 同为多日档（3日↔1周↔30日）题目集合相同，保留用户开关状态（图表重渲染由 setWindow 的 renderAllCharts 负责）
watch(windowKey, () => {
  const activeKeys = confBarsActiveQuestions.value.map((question) => question.key)
  const current = confidenceBarIndicators.value
  if (!current.every((key) => activeKeys.includes(key))) {
    confidenceBarIndicators.value = [...activeKeys]
  }
})

const confidenceBarsSeries = computed(() =>
  confBarsActiveQuestions.value.filter((question) => confidenceBarIndicators.value.includes(question.key)),
)

function toggleConfidenceBar(key: ConfidenceBarKey) {
  const current = confidenceBarIndicators.value
  if (current.includes(key)) {
    if (current.length === 1) return // 至少保留一个序列，避免图表空白（同历史对比页签）
    confidenceBarIndicators.value = current.filter((k) => k !== key)
  } else {
    // 按声明顺序重排，保持图例顺序稳定
    confidenceBarIndicators.value = confBarsActiveQuestions.value
      .map((question) => question.key)
      .filter((k) => current.includes(k) || k === key)
  }
  nextTick(() => renderConfidenceBarsChart())
}

const confidenceStats = computed(() => {
  if (windowKey.value === '1d') {
    const probs: number[] = []
    for (const point of confidenceBarsPoints.value) {
      const cell = point.cells.sequence_stage
      if (cell && cell.kind === 'choice' && !cell.noDist && cell.value != null) probs.push(cell.value)
    }
    const avg = probs.length ? Math.round(probs.reduce((a, b) => a + b, 0) / probs.length) : null
    const hesitant = probs.filter((value) => value < Math.round(JEV_HESITANT_THRESHOLD * 100)).length
    return [
      { label: '序列档平均 P', value: avg != null ? `${avg}%` : '--', sub: `${probs.length}/${slots.value.length} 槽有分布` },
      { label: '犹豫槽（P<60%）', value: String(hesitant), sub: `阈值 ${Math.round(JEV_HESITANT_THRESHOLD * 100)}%` },
      { label: 'score 型槽', value: `${slots.value.filter((slot) => slot.answers?.temperature?.type === 'score').length}`, sub: '温度题=锚点分布+模型置信口径' },
    ]
  }
  // 多日窗口：EOD 日级均值口径（热榜情绪·历史对比页签统计卡同语言）
  const stageProbs: number[] = []
  const crowdProbs: number[] = []
  for (const point of confidenceBarsPoints.value) {
    const stage = point.cells.day_stage
    if (stage && stage.kind === 'choice' && !stage.noDist && stage.value != null) stageProbs.push(stage.value)
    const crowd = point.cells.day_crowding
    if (crowd && crowd.kind === 'choice' && !crowd.noDist && crowd.value != null) crowdProbs.push(crowd.value)
  }
  const avgOf = (values: number[]) => (values.length ? Math.round(values.reduce((a, b) => a + b, 0) / values.length) : null)
  const avgStage = avgOf(stageProbs)
  const avgCrowd = avgOf(crowdProbs)
  const total = dayDocs.value.length
  return [
    { label: '日级档平均 P', value: avgStage != null ? `${avgStage}%` : '--', sub: `${stageProbs.length}/${total} 日有分布` },
    { label: '犹豫日（P<60%）', value: String(stageProbs.filter((value) => value < Math.round(JEV_HESITANT_THRESHOLD * 100)).length), sub: `阈值 ${Math.round(JEV_HESITANT_THRESHOLD * 100)}%` },
    { label: '日拥挤平均 P', value: avgCrowd != null ? `${avgCrowd}%` : '--', sub: `${crowdProbs.length}/${total} 日有分布` },
  ]
})

// ---------- 答案分布明细（choice 全分布 + score 锚点；返回结果全量呈现） ----------
interface DistRow {
  key: string
  label: string
  isScore: boolean
  /** score 型且确实未携带锚点分布（note 文案分叉） */
  scoreNoDist: boolean
  choice: string | null
  choiceName: string | null
  tone: string
  probability: number | null
  confidence: number | null
  margin: number | null
  entropy: number | null
  hesitant: boolean
  score: number | null
  legend: string[]
  rows: Array<{ key: string; name: string; pct: number | null; color: string }>
}

const DIST_QUESTIONS: Record<'slot' | 'eod', Array<{ key: string; label: string }>> = {
  slot: [
    { key: 'frame_stage', label: '当前帧档' },
    { key: 'sequence_stage', label: '序列档' },
    { key: 'temperature', label: '温度' },
    { key: 'crowding', label: '拥挤归层' },
  ],
  eod: [
    { key: 'day_stage', label: '日级档' },
    { key: 'day_pattern', label: '路径形态' },
    { key: 'day_temperature', label: '日温度' },
    { key: 'day_crowding', label: '日拥挤' },
  ],
}

const distKey = ref('')

const distDoc = computed<HotlistJevDoc | null>(() => {
  if (distKey.value === 'eod') return eodDoc.value
  if (distKey.value) return slots.value.find((slot) => slot.slotTime === distKey.value) ?? null
  // 缺省跟随叙事焦点（同一文档双入口，不重复选择）
  return focusDoc.value
})

function choiceToneOf(questionKey: string, choiceKey: string | null): string {
  if (!choiceKey) return ''
  if (questionKey.includes('crowding')) return CROWDING_COLORS[choiceKey] ?? '#9aa0a6'
  if (questionKey === 'day_pattern') return '#4a90e2'
  const name = JEV_STAGE_NAMES[choiceKey] ?? choiceKey
  return STAGE_COLORS[name] ?? '#9aa0a6'
}

/** 锚点条色（温度冷热语义：锚0=冷蓝 → 锚9=热红，与温度计色阶同语言） */
function anchorTone(anchor: string): string {
  const index = Number(anchor)
  if (!Number.isFinite(index)) return '#9aa0a6'
  return `hsl(${Math.max(0, 210 - 21 * index).toFixed(0)}, 72%, 52%)`
}

function distRowOf(doc: HotlistJevDoc, kind: 'slot' | 'eod', question: { key: string; label: string }): DistRow {
  const answer = doc.answers?.[question.key]
  const metrics = confidenceMetrics(answer)
  const order = question.key === 'day_pattern'
    ? JEV_PATTERN_ORDER
    : question.key === 'crowding'
      ? CROWDING_ORDER
      : JEV_STAGE_ORDER
  const names = question.key === 'day_pattern' ? JEV_PATTERN_NAMES : question.key === 'crowding' ? CROWDING_NAMES : JEV_STAGE_NAMES
  // score 型（温度）分布键=锚点 "0"-"9"（2026-10-02 实测生产 100% 携带）；choice 型按规范选项顺序展开
  const isScoreRow = answer?.type === 'score'
  const scoreAnswer = answer && answer.type === 'score' ? answer : null
  const legend: Record<string, string> = scoreAnswer?.legend ?? {}
  const probabilities = answer && (answer.type === 'choice' || answer.type === 'score') ? answer.probabilities ?? {} : {}
  const rows = isScoreRow
    ? Object.keys(probabilities)
        .sort((a, b) => Number(a) - Number(b))
        .map((anchor) => ({
          key: anchor,
          name: `${legend[anchor] ?? anchor}分`,
          pct: typeof probabilities[anchor] === 'number' ? Math.round((probabilities[anchor] as number) * 1000) / 10 : null,
          color: anchorTone(anchor),
        }))
    : order
        .filter((optionKey) => optionKey in probabilities || optionKey === metrics.choice)
        .map((optionKey) => ({
          key: optionKey,
          name: names[optionKey] ?? optionKey,
          pct: typeof probabilities[optionKey] === 'number' ? Math.round((probabilities[optionKey] as number) * 1000) / 10 : null,
          color: choiceToneOf(question.key, optionKey),
        }))
  return {
    key: question.key,
    label: question.label,
    isScore: metrics.kind === 'score',
    scoreNoDist: metrics.kind === 'score' && metrics.noDistribution,
    choice: metrics.choice,
    choiceName: metrics.choice != null ? (names[metrics.choice] ?? metrics.choice) : null,
    tone: choiceToneOf(question.key, metrics.choice),
    probability: metrics.probability,
    confidence: metrics.confidence,
    margin: metrics.margin,
    entropy: metrics.entropy,
    hesitant: metrics.hesitant,
    score: scoreAnswer && typeof scoreAnswer.score === 'number' ? scoreAnswer.score : null,
    legend: Object.entries(legend)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([, value]) => String(value)),
    rows,
  }
}

const distRows = computed<DistRow[]>(() => {
  const doc = distDoc.value
  if (!doc) return []
  const kind: 'slot' | 'eod' = doc.kind === 'eod' ? 'eod' : 'slot'
  return DIST_QUESTIONS[kind].map((question) => distRowOf(doc, kind, question))
})

// ---------- 叙事全文投影 ----------
const narrativeProjection = computed<JevNarrativeProjection>(() => parseNarrativeSections(focusDoc.value?.narrativeRaw))
const narrativeText = computed(() => focusDoc.value?.narrativeRaw || '')
const anchorMetrics = computed<JevAnchorMetric[]>(() => anchorMetricsOfDoc(focusDoc.value))

/** 涨停生态断层标注（§十三；当前选中日 EOD 文档的 diagnostics.ecosystemBreak） */
const ecosystemBreak = computed(() => {
  const diag = eodDoc.value?.diagnostics?.ecosystemBreak
  return diag?.isBreak ? diag : null
})

/** 生态宽度 U 形三段分区（2026-10-04 裁决 10，展示侧读数）：
 *  自变量=当日涨停家数（规则算 ecoBreadth，缺则降级用锚 lastValue），切点=叙事锚涨停数 p20/p80。
 *  U 形后验（§十三，8/9 月复现）：低宽度=反弹在即多发区观察积极 / 中宽度=历史读数最差观望回避 / 高宽度=顺势但警惕拥挤。 */
const ecoBreadthZone = computed(() => {
  const breadth = eodDoc.value?.diagnostics?.ecoBreadth
  const limitAnchor = anchorMetrics.value.find(
    (m) => m.metric.includes('涨停') && m.p20 != null && m.p80 != null,
  )
  const count = breadth?.ztCount ?? null
  const anchorText = limitAnchor ? `${limitAnchor.lastDate?.slice(5) ?? ''} ${limitAnchor.lastValue} 家` : null
  const value = count ?? (limitAnchor?.lastValue != null ? Number(limitAnchor.lastValue) : null)
  if (value == null || !Number.isFinite(value)) return null
  const p20 = limitAnchor?.p20 != null ? Number(limitAnchor.p20) : breadth?.p20 ?? null
  const p80 = limitAnchor?.p80 != null ? Number(limitAnchor.p80) : null
  if (p20 == null || p80 == null) return null
  const zone = value < p20 ? 'low' : value > p80 ? 'high' : 'mid'
  const zoneText = zone === 'low'
    ? `低位带（<p20=${p20}）：反弹在即多发区，观察积极`
    : zone === 'high'
      ? `高位带（>p80=${p80}）：顺势区间，警惕拥挤`
      : `中位带（p20=${p20}~p80=${p80}）：历史读数最差，观望回避`
  return {
    count: value,
    source: breadth ? '规则算（detect_ecosystem_break）' : '叙事锚末值（降级）',
    zone,
    zoneText,
    anchorText,
    isBreak: breadth?.isBreak === true,
  }
})
const anchorRange = computed(() => focusDoc.value?.historyAnchorRange ?? null)
const usageText = computed(() => {
  const usage = focusDoc.value?.usage
  if (!usage) return ''
  const parts: string[] = []
  if (typeof usage.input_tokens === 'number') parts.push(`in ${usage.input_tokens}`)
  if (typeof usage.output_tokens === 'number') parts.push(`out ${usage.output_tokens}`)
  return parts.join(' / ')
})

// ---------- 原始返回投影 ----------
const rawMetaItems = computed(() => {
  const doc = focusDoc.value
  if (!doc) return []
  return [
    { label: 'status', value: doc.status ?? null },
    { label: 'errorCode', value: doc.errorCode ?? null },
    { label: 'errorDetail', value: doc.errorDetail ?? null },
    { label: 'model', value: doc.model ?? null },
    { label: 'asOf', value: doc.asOf ?? null },
    { label: 'anchoredSlotTime', value: doc.anchoredSlotTime ?? null },
    { label: 'datasetId', value: doc.datasetId ?? null },
    { label: 'snapshotType', value: doc.snapshotType ?? null },
    { label: 'computedAt', value: doc.computedAt != null ? new Date(doc.computedAt * 1000).toISOString() : null },
    { label: 'latencyMs', value: doc.latencyMs != null ? String(doc.latencyMs) : null },
    { label: 'origin', value: doc.origin ?? null },
    { label: 'tokens', value: usageText.value || null },
  ]
})

function prettyJson(value: unknown): string | null {
  if (value == null || typeof value !== 'object') return null
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return null
  }
}

const rawResponseText = computed(() => prettyJson(focusDoc.value?.responseRaw))
const rawQuestionsText = computed(() => prettyJson(focusDoc.value?.questionsRaw))
const rawEnvelopeText = computed(() => {
  const envelope = focusDoc.value?.responseRaw
  if (!envelope || typeof envelope !== 'object') return null
  const meta = (envelope as { result?: Record<string, unknown> }).result
  if (!meta || typeof meta !== 'object') return null
  const picked: Record<string, unknown> = {}
  for (const key of ['state', 'model', 'usage', 'errors']) {
    if (key in meta) picked[key] = meta[key]
  }
  return Object.keys(picked).length ? JSON.stringify(picked, null, 2) : null
})

const evidenceGroups = computed(() => {
  const evidence = focusDoc.value?.evidenceRaw
  if (!evidence || typeof evidence !== 'object') return []
  return Object.entries(evidence)
    .filter(([, value]) => value != null)
    .map(([key, value]) => ({ key, text: prettyJson(value) ?? String(value) }))
})

// ---------- ECharts（温度曲线 / 拥挤堆叠 / 置信趋势 / 日级柱图） ----------
const thermoChartRef = ref<HTMLElement | null>(null)
const crowdingBarChartRef = ref<HTMLElement | null>(null)
const confidenceBarsChartRef = ref<HTMLElement | null>(null)
const dayChartRef = ref<HTMLElement | null>(null)
let thermoChart: echarts.ECharts | null = null
let crowdingBarChart: echarts.ECharts | null = null
let confidenceBarsChart: echarts.ECharts | null = null
let dayChart: echarts.ECharts | null = null

interface StageRunPoint {
  label: string
  stage: string
}

/** 档位铺底 markArea（连续同档合并；同热榜情绪面板铺底语言，温度/日级柱图共用） */
function buildStageMarkArea(
  points: StageRunPoint[],
): Array<[Record<string, unknown>, Record<string, unknown>]> {
  const markAreaData: Array<[Record<string, unknown>, Record<string, unknown>]> = []
  let runStage = ''
  let runStart = ''
  let runEnd = ''
  let runLen = 0
  const flushRun = () => {
    const color = STAGE_COLORS[runStage]
    if (color && runLen > 0) {
      markAreaData.push([
        {
          xAxis: runStart,
          itemStyle: { color: `${color}1a` },
          label: { show: runLen >= 2, position: 'insideTop', fontSize: 9, color, formatter: runStage },
        },
        { xAxis: runEnd },
      ])
    }
    runLen = 0
  }
  for (const point of points) {
    if (point.stage !== runStage) {
      flushRun()
      runStage = point.stage
      runStart = point.label
    }
    runEnd = point.label
    runLen += 1
  }
  flushRun()
  return markAreaData
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function initChart(container: HTMLElement | null, existing: echarts.ECharts | null): echarts.ECharts | null {
  if (!container) return null
  // 容器被 v-if 重建后旧实例的 DOM 已分离：dispose 后必须重建并返回新实例供调用方回写引用，
  // 否则滞留的已 dispose 实例会让后续渲染永远早退（评审修复：饼图一次 1d↔多日往返后消失）
  if (existing && existing.getDom() !== container) {
    existing.dispose()
    return echarts.init(container)
  }
  return existing ?? echarts.init(container)
}

function renderThermoChart() {
  const points = thermoPoints.value
  const chart = initChart(thermoChartRef.value, thermoChart)
  if (!chart || !points.length) return
  thermoChart = chart
  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')
  const markAreaData = buildStageMarkArea(points)

  const series: echarts.SeriesOption[] = [
    windowKey.value === '1d'
      ? {
          name: '温度', type: 'bar', barWidth: 10,
          data: points.map((point) => (point.status === 'no_data' ? null : point.value)),
          itemStyle: { color: (params: { dataIndex: number }) => tempColor(points[params.dataIndex]?.value ?? null) },
          markArea: { silent: true, data: markAreaData },
        }
      : {
          name: '日级温度', type: 'line', smooth: true, connectNulls: false,
          data: points.map((point) => point.value),
          lineStyle: { color: '#9b59b6', width: 2 },
          itemStyle: { color: '#9b59b6' },
          markArea: { silent: true, data: markAreaData },
        },
  ]
  chart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '15%', bottom: '12%', containLabel: true },
      tooltip: {
        trigger: 'axis', confine: true,
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex: number } | undefined
          const point = first ? points[first.dataIndex] : undefined
          if (!point) return ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.label}</div>`,
            `<div style="color:${STAGE_COLORS[point.stage] ?? textColor};margin-bottom:4px;">档位：${point.stage || '缺失'}</div>`,
            `<div>温度：${point.value == null ? '--' : Math.round(point.value)}</div>`,
            point.status === 'no_data' ? '<div style="color:#f39c12;">无数据</div>' : '',
          ].join('')
        },
      },
      xAxis: {
        type: 'category', data: points.map((point) => point.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: {
        type: 'value', min: 0, max: 100, name: '温度（0-100）',
        nameTextStyle: { color: textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
        axisLabel: { color: textColor },
      },
      series,
      backgroundColor: 'transparent',
    },
    { notMerge: true },
  )
  chart.resize()
}

function renderCrowdingBarChart() {
  const points = crowdingBarPoints.value
  const chart = initChart(crowdingBarChartRef.value, crowdingBarChart)
  if (!chart || !points.length) return
  crowdingBarChart = chart
  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')
  const indicators = crowdingBarIndicators.value
  const selectedKey = crowdingSelectedKey.value
  const series: echarts.SeriesOption[] = []
  if (indicators.includes('probability')) {
    // 柱色=归层色（六层图例参照）；归层缺失/无数据灰柱或断柱，不伪造；选中柱白描边（点击联动详情反馈）
    series.push({
      name: '所选层概率', type: 'bar', barWidth: 12,
      itemStyle: { color: '#9aa0a6' },
      data: points.map((point) => ({
        value: point.noData ? null : point.probability,
        itemStyle: {
          color: point.layer ? (CROWDING_COLORS[point.layer] ?? '#9aa0a6') : '#9aa0a6',
          ...(point.key === selectedKey ? { borderColor: '#ffffff', borderWidth: 2 } : {}),
        },
      })),
    })
  }
  if (indicators.includes('risk')) {
    series.push({
      name: '拥挤抗风险', type: 'line', smooth: true, connectNulls: false,
      symbol: 'circle', symbolSize: 5,
      data: points.map((point) => (point.noData ? null : point.risk)),
      lineStyle: { color: '#ff9f43', width: 2 }, itemStyle: { color: '#ff9f43' },
    })
  }
  if (series.length) {
    series[0].markLine = {
      silent: true, symbol: 'none',
      data: [{ yAxis: Math.round(JEV_HESITANT_THRESHOLD * 100) }],
      lineStyle: { color: '#ff4757', type: 'dashed', width: 1 },
      label: { color: '#ff4757', fontSize: 9, formatter: `犹豫阈值 ${Math.round(JEV_HESITANT_THRESHOLD * 100)}%` },
    }
  }
  chart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '12%', bottom: '12%', containLabel: true },
      tooltip: {
        trigger: 'axis', confine: true,
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex: number } | undefined
          const point = first ? points[first.dataIndex] : undefined
          if (!point) return ''
          const layerColor = point.layer ? (CROWDING_COLORS[point.layer] ?? textColor) : textColor
          const head = [
            `<div style="font-weight:600;margin-bottom:4px;">${point.label}${point.degraded ? ' · ⚠️降级' : ''}</div>`,
            point.eodMissing ? '<div style="color:#f39c12;">EOD 未生成</div>' : '',
            point.noData ? '<div style="color:#f39c12;">无数据</div>' : '',
            `<div style="color:${layerColor};margin-bottom:4px;">归层：${point.layerName ?? '缺失'}${point.warn ? ' ⚠️毒层' : ''}</div>`,
          ].join('')
          const rows = CROWDING_BARS_INDICATORS.filter((indicator) => indicators.includes(indicator.key)).map((indicator) => {
            const value = indicator.key === 'probability' ? point.probability : point.risk
            return `<div>${indicator.label}：${value == null ? '--' : `P${value}%`}</div>`
          })
          const bits = [
            point.confidence != null ? `置信 ${point.confidence}%` : '',
            point.margin != null ? `margin ${(point.margin * 100).toFixed(0)}` : '',
            point.entropy != null ? `熵 ${point.entropy.toFixed(2)}` : '',
          ].filter(Boolean)
          const distribution = point.probabilities
            ? `<div style="color:${textColor};">${CROWDING_ORDER.map((key) => {
                const value = point.probabilities?.[key]
                return `${CROWDING_NAMES[key] ?? key} ${typeof value === 'number' ? `${Math.round(value * 100)}%` : '--'}`
              }).join(' · ')}</div>`
            : ''
          return [head, ...rows, bits.length ? `<div>${bits.join(' · ')}</div>` : '', distribution].join('')
        },
      },
      legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: textColor, fontSize: 10 } },
      xAxis: {
        type: 'category', data: points.map((point) => point.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: {
        type: 'value', min: 0, max: 100, name: 'P / 合计（%）',
        nameTextStyle: { color: textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
        axisLabel: { color: textColor },
      },
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留（同历史对比页签）
    { notMerge: true },
  )
  // 点选联动（jev 观察轨道页签同交互，命中面更宽）：zrender 层 click + x 像素最近列 snap——
  // 窄柱（barWidth 12）点在柱间空隙也按最近列响应，避免「看着点了柱却没反应」；off 先行防重复渲染累积 handler
  chart.getZr().off('click')
  chart.getZr().on('click', (event: { offsetX?: number }) => {
    if (typeof event.offsetX !== 'number') return
    const index = chart.convertFromPixel({ xAxisIndex: 0 }, event.offsetX)
    if (typeof index !== 'number' || !Number.isFinite(index)) return
    const nearest = points[Math.round(index)]
    if (nearest) {
      selectedCrowdingKey.value = nearest.key
      nextTick(() => renderCrowdingBarChart()) // 重渲染以刷新选中柱白描边高亮
    }
  })
  chart.resize()
}

function renderConfidenceBarsChart() {
  const points = confidenceBarsPoints.value
  const chart = initChart(confidenceBarsChartRef.value, confidenceBarsChart)
  if (!chart || !points.length) return
  confidenceBarsChart = chart
  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')
  const indicators = confidenceBarIndicators.value
  const questions = confBarsActiveQuestions.value
  const isDaily = windowKey.value !== '1d'
  const series: echarts.SeriesOption[] = []
  for (const question of questions) {
    if (!indicators.includes(question.key)) continue
    // null（答案缺失/无分布）直传图表断线断柱，不补 0（fail-visible，同历史对比页签）
    const data = points.map((point) => point.cells[question.key]?.value ?? null)
    series.push(
      question.type === 'line'
        ? {
            name: question.label, type: 'line', smooth: true, connectNulls: false,
            symbol: 'circle', symbolSize: 5, data,
            lineStyle: { color: question.color, width: 2 }, itemStyle: { color: question.color },
          }
        : { name: question.label, type: 'bar', barWidth: 12, data, itemStyle: { color: question.color } },
    )
  }
  if (series.length) {
    series[0].markLine = {
      silent: true, symbol: 'none',
      data: [{ yAxis: Math.round(JEV_HESITANT_THRESHOLD * 100) }],
      lineStyle: { color: '#ff4757', type: 'dashed', width: 1 },
      label: { color: '#ff4757', fontSize: 9, formatter: `犹豫阈值 ${Math.round(JEV_HESITANT_THRESHOLD * 100)}%` },
    }
  }
  chart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '12%', bottom: '12%', containLabel: true },
      tooltip: {
        trigger: 'axis', confine: true,
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex: number } | undefined
          const point = first ? points[first.dataIndex] : undefined
          if (!point) return ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.label}${point.degraded ? ' · ⚠️降级' : ''}</div>`,
            ...questions.filter((question) => indicators.includes(question.key)).map((question) => {
              const cell = point.cells[question.key]
              if (!cell) return ''
              if (cell.kind === 'missing') return `<div>${question.label}：答案缺失</div>`
              if (cell.noDist) return `<div>${question.label}：无分布（score 型未携带锚点分布）</div>`
              const bits = [`${question.label}：${question.type === 'line' ? 'C' : 'P'}${cell.value == null ? '--' : `${cell.value}%`}`]
              if (cell.choiceName) bits.push(cell.choiceName)
              if (question.type !== 'line' && cell.confidence != null) bits.push(`置信 ${Math.round(cell.confidence * 100)}%`)
              if (cell.margin != null) bits.push(`margin ${(cell.margin * 100).toFixed(0)}`)
              if (cell.entropy != null) bits.push(`熵 ${cell.entropy.toFixed(2)}`)
              if (cell.hesitant) bits.push('⚠️犹豫')
              return `<div>${bits.join(' · ')}</div>`
            }),
            // 多日窗口附注：路径形态名 + EOD 未生成显式标注（同叙事概览日级柱图语言）
            ...(isDaily && point.patternName ? [`<div>路径：${point.patternName}</div>`] : []),
            ...(isDaily && point.eodMissing ? ['<div style="color:#f39c12;">EOD 未生成</div>'] : []),
          ].join('')
        },
      },
      legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: textColor, fontSize: 10 } },
      xAxis: {
        type: 'category', data: points.map((point) => point.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: {
        type: 'value', min: 0, max: 100, name: 'P / C（%）',
        nameTextStyle: { color: textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
        axisLabel: { color: textColor },
      },
      series,
      backgroundColor: 'transparent',
    },
    // 指标开关减少序列时必须整体替换，merge 模式下旧序列会残留（同历史对比页签）
    { notMerge: true },
  )
  chart.resize()
}

function renderDayChart() {
  const days = dayDocs.value
  const chart = initChart(dayChartRef.value, dayChart)
  if (!chart || !days.length) return
  dayChart = chart
  const textColor = cssVar('--text-secondary', '#9aa0a6')
  const borderColor = cssVar('--border-color', '#333333')
  const points = days.map((day) => {
    const eod = day.eod
    const metrics = eod ? confidenceMetrics(eod.answers?.day_stage) : null
    return {
      label: day.tradingDate.slice(5),
      temp: eod ? jevScore(eod, 'day_temperature') : null,
      p: metrics && metrics.probability != null ? Math.round(metrics.probability * 100) : null,
      crowd: eod ? jevCrowdingProbability(eod, 'day_crowding') : null,
      stage: eod ? (jevChoiceName(eod, 'day_stage') ?? '') : '',
      pattern: eod ? (jevChoiceName(eod, 'day_pattern') ?? '') : '',
    }
  })
  chart.setOption(
    {
      grid: { left: '8%', right: '8%', top: '18%', bottom: '16%', containLabel: true },
      tooltip: {
        trigger: 'axis', confine: true,
        formatter: (params: unknown) => {
          const list = Array.isArray(params) ? params : [params]
          const first = list[0] as { dataIndex: number } | undefined
          const point = first ? points[first.dataIndex] : undefined
          if (!point) return ''
          return [
            `<div style="font-weight:600;margin-bottom:4px;">${point.label}</div>`,
            `<div style="color:${STAGE_COLORS[point.stage] ?? textColor};margin-bottom:4px;">档位：${point.stage || '缺失'}</div>`,
            `<div>日级温度：${point.temp == null ? '--' : Math.round(point.temp)}</div>`,
            `<div>日级拥挤：${point.crowd == null ? '--' : `P${Math.round(point.crowd * 100)}%`}</div>`,
            `<div>序列档置信：${point.p == null ? '--' : `P${point.p}%`}</div>`,
            point.pattern ? `<div>路径：${point.pattern}</div>` : '',
            point.stage === '' ? '<div style="color:#f39c12;">EOD 未生成</div>' : '',
          ].join('')
        },
      },
      legend: { bottom: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: textColor, fontSize: 10 } },
      xAxis: {
        type: 'category', data: points.map((point) => point.label),
        axisLabel: { color: textColor, fontSize: 10, rotate: 30 },
        axisLine: { lineStyle: { color: borderColor } },
      },
      yAxis: {
        type: 'value', min: 0, max: 100, name: '分值（0-100）',
        nameTextStyle: { color: textColor, fontSize: 9 },
        splitLine: { lineStyle: { color: borderColor, type: 'dashed' } },
        axisLabel: { color: textColor },
      },
      series: [
        {
          // 图例代表色（旧面板温度紫柱）；柱体实际色=分值语义渐变
          name: '日级温度', type: 'bar', barWidth: 12,
          itemStyle: { color: '#9b59b6' },
          data: points.map((point) => ({
            value: point.temp,
            itemStyle: { color: tempColor(point.temp) },
          })),
          markArea: { silent: true, data: buildStageMarkArea(points) },
        },
        {
          name: '日级档置信', type: 'bar', barWidth: 12,
          itemStyle: { color: '#4a90e2' },
          data: points.map((point) => ({
            value: point.p,
            itemStyle: { color: confidenceColor(point.p != null ? point.p / 100 : null) },
          })),
        },
        {
          name: '日级拥挤', type: 'bar', barWidth: 12,
          itemStyle: { color: '#ff9f43' },
          data: points.map((point) => ({
            value: point.crowd != null ? Math.round(point.crowd * 100) : null,
            itemStyle: { color: crowdingRiskColor(point.crowd) },
          })),
        },
      ],
      backgroundColor: 'transparent',
    },
    { notMerge: true },
  )
  chart.resize()
}

function renderAllCharts() {
  if (view.value === 'thermometer') renderThermoChart()
  if (view.value === 'crowding') renderCrowdingBarChart()
  if (view.value === 'confidence') renderConfidenceBarsChart()
  if (view.value === 'grid') renderDayChart()
}

function handleResize() {
  thermoChart?.resize()
  crowdingBarChart?.resize()
  confidenceBarsChart?.resize()
  dayChart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  thermoChart?.dispose()
  crowdingBarChart?.dispose()
  confidenceBarsChart?.dispose()
  dayChart?.dispose()
  thermoChart = null
  crowdingBarChart = null
  confidenceBarsChart = null
  dayChart = null
})
</script>
<style scoped>
.jev-narrative-panel {
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
  color: var(--text-primary);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.panel-header h3 { margin: 0; font-size: 14px; display: flex; align-items: center; gap: 6px; }
.version-badge {
  font-size: 10px;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1px 6px;
  font-weight: 400;
}
.time-badge {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 2px 8px;
}
.time-badge.ok { color: #2ed573; }
.time-badge.warn { color: #f39c12; }
.panel-actions { display: flex; gap: 6px; }
.btn-icon {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;
  padding: 4px 8px;
  font-size: 12px;
}
.btn-icon:hover { border-color: var(--color-highlight); }
.btn-icon:disabled { opacity: 0.5; cursor: default; }
.btn-icon.loading { opacity: 0.6; cursor: wait; }
.rotate-animation { display: inline-block; animation: jev-rotate 1s linear infinite; }
@keyframes jev-rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.panel-tabs {
  display: flex;
  align-items: center;
  padding: 8px 16px 0;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}
.tabs-left { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; }
.tab-btn {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  padding: 6px 10px;
}
.tab-btn.active { color: var(--text-primary); border-bottom-color: var(--color-highlight); }
.tab-btn:hover { color: var(--text-primary); }

.panel-content {
  padding: 12px 16px 16px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.tab-pane { display: flex; flex-direction: column; gap: 10px; }
.state-block {
  padding: 32px 0;
  text-align: center;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.state-block.error { color: #ff4757; }
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border-color);
  border-top-color: var(--color-highlight);
  border-radius: 50%;
  animation: jev-rotate 0.8s linear infinite;
}
.retry-btn {
  margin-left: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  cursor: pointer;
  padding: 3px 10px;
}

.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.time-range-selector, .date-selector { display: flex; gap: 4px; flex-wrap: wrap; }
.time-btn {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  padding: 3px 10px;
}
.time-btn.active { color: var(--text-primary); border-color: var(--color-highlight); background: var(--bg-primary); }
.time-btn:disabled { opacity: 0.4; cursor: default; }
.date-btn.active { color: var(--color-highlight); }
/* 指标开关（置信度页签，热榜情绪·历史对比页签同语言） */
.indicator-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.indicator-btn {
  padding: 4px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.indicator-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.indicator-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }

.note-line { font-size: 11px; color: var(--text-secondary); }
.note-line.warn-line { color: #f39c12; }
.research-line {
  background: var(--bg-secondary);
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  padding: 6px 10px;
  line-height: 1.6;
}
.empty-row {
  padding: 16px 0;
  text-align: center;
  color: var(--text-secondary);
  font-size: 11px;
}
.sub-block-title { font-size: 12px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.legend-line { font-size: 10px; color: var(--text-secondary); }

/* ---------- 温度计 ---------- */
.thermo-row { display: flex; gap: 12px; align-items: stretch; flex-wrap: wrap; }
.thermo-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.thermo-title { font-size: 11px; color: var(--text-secondary); }
.thermo-svg { width: 76px; height: 232px; }
.thermo-tube { fill: var(--bg-primary); stroke: var(--border-color); }
.thermo-tick { stroke: var(--border-color); stroke-width: 1; }
.thermo-tick-text { fill: var(--text-secondary); font-size: 9px; }
.thermo-bulb { stroke: var(--border-color); }
.thermo-bulb-text { fill: #fff; font-size: 12px; font-weight: 700; text-anchor: middle; }
.thermo-caption { font-size: 12px; font-weight: 600; }

.anchor-panel {
  flex: 1;
  min-width: 260px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
}
.anchor-title { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.anchor-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
.anchor-grid.inline { grid-template-columns: repeat(4, 1fr); margin-bottom: 6px; }
.anchor-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 6px 8px;
}
.anchor-metric { font-size: 11px; font-weight: 600; color: var(--text-primary); }
.anchor-quantiles { display: flex; gap: 8px; margin-top: 3px; flex-wrap: wrap; }
.anchor-q { font-size: 10px; color: var(--text-secondary); }
.anchor-q b { color: var(--text-primary); font-size: 11px; }
.anchor-last { font-size: 10px; color: var(--color-highlight); margin-top: 2px; }
.anchor-note { font-size: 10px; color: #f39c12; margin-top: 3px; }
.anchor-footnote { font-size: 10px; color: var(--text-secondary); margin-top: 6px; }
.eco-breadth-row { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px; color: var(--text-primary); }
.eco-zone-badge {
  flex: none; font-size: 11px; padding: 2px 8px; border-radius: 8px; font-weight: 600;
  background: rgba(138, 143, 152, 0.15); color: var(--text-secondary);
}
.eco-zone-badge[data-zone='low'] { background: rgba(46, 213, 115, 0.15); color: #2ed573; }
.eco-zone-badge[data-zone='mid'] { background: rgba(217, 119, 6, 0.15); color: #f5a623; }
.eco-zone-badge[data-zone='high'] { background: rgba(139, 124, 246, 0.15); color: #8b7cf6; }
.eco-breadth-text b { color: var(--text-primary); }
.eco-breadth-zone { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

/* ---------- 拥挤度 ---------- */
.crowding-hero { display: flex; gap: 12px; flex-wrap: wrap; }
.crowding-latest {
  flex: 1;
  min-width: 260px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
}
.crowding-strip-block {
  flex: 1.2;
  min-width: 300px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
}
.crowding-layer-name { font-size: 16px; font-weight: 700; margin: 4px 0; }
.warn-badge {
  font-size: 10px;
  font-weight: 400;
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.45);
  border-radius: 8px;
  padding: 1px 6px;
  margin-left: 6px;
}
.crowding-meta { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
.waffle-block { margin-top: 6px; }
.waffle-grid {
  display: grid;
  grid-template-columns: repeat(10, 12px);
  grid-auto-rows: 12px;
  gap: 2px;
}
.waffle-square {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  border: 1px solid var(--border-color);
}
.waffle-legend { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.waffle-legend-item { font-size: 10px; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 4px; }
.legend-dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.crowding-legend { display: flex; gap: 10px; flex-wrap: wrap; }
.transition-list { margin-top: 8px; }
.transition-item { font-size: 11px; display: flex; align-items: center; gap: 6px; margin-top: 3px; }
.crowding-stats {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 8px 12px;
}
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; }
.stat-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 6px 10px;
}
.stat-label { font-size: 10px; color: var(--text-secondary); margin-bottom: 3px; }
.stat-body { display: flex; gap: 10px; flex-wrap: wrap; }
.stat-item { font-size: 12px; font-weight: 600; }
.stat-item.muted { color: var(--text-secondary); font-weight: 400; font-size: 10px; }

/* ---------- 叙事全文 / 原始返回 ---------- */
.doc-selector { display: flex; gap: 4px; flex-wrap: wrap; }
.narrative-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.narrative-body {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.narrative-header-line {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: inherit;
  white-space: pre-wrap;
}
.narrative-section { display: flex; flex-direction: column; gap: 4px; }
.narrative-section-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-highlight);
  border-left: 3px solid var(--color-highlight);
  padding-left: 6px;
  margin-top: 4px;
}
.narrative-text {
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
  /* 无截断：全文完整呈现，仅随面板内容区滚动 */
  max-height: none;
}

.raw-meta { display: flex; gap: 8px 14px; flex-wrap: wrap; }
.raw-meta-item { font-size: 11px; color: var(--text-primary); }
.raw-meta-label {
  color: var(--text-secondary);
  margin-right: 4px;
  font-size: 10px;
}
.raw-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 6px 10px;
}
.raw-block summary {
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.raw-json {
  margin: 6px 0 2px;
  font-size: 10px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary);
  max-height: 320px;
  overflow-y: auto;
}
.evidence-group { margin-top: 8px; }
.evidence-group-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-highlight);
}

.trend-chart { width: 100%; height: 240px; }

/* ---------- 总览 sub-block 卡片行（对齐热榜情绪面板） ---------- */
.sub-block {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.block-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.block-title { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.section-count {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1px 8px;
}
.slot-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.slot-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.slot-card.degraded { border-style: dashed; border-color: #f39c12; }
.slot-card.no-data { opacity: 0.5; }
.slot-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
}
.slot-card-flag {
  font-size: 9px;
  color: #f39c12;
  border: 1px solid rgba(243, 156, 18, 0.4);
  border-radius: 6px;
  padding: 0 4px;
  font-weight: 400;
}
.slot-card-stage { font-size: 15px; font-weight: bold; }
.slot-card-nums {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.slot-card-layer { display: inline-flex; align-items: center; gap: 4px; }
.slot-card-sub { font-size: 10px; color: var(--text-secondary); }

/* ---------- 总览页（视觉对齐热榜情绪面板：hero 大卡 + 圆徽指标卡 + 紧凑卡行，色在文字/色点/细条上） ---------- */
.stage-hero {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-left-width: 4px;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hero-label { font-size: 11px; color: var(--text-secondary); }
.hero-stage { font-size: 28px; font-weight: bold; color: var(--text-title); line-height: 1.2; }
.hero-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hero-score-bar { display: flex; align-items: center; gap: 8px; }
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
.hero-score-fill { height: 100%; border-radius: 3px; }
.hero-score-missing .hero-score-hint { color: #f39c12; }
.hero-score-hint { font-size: 10px; color: var(--text-secondary); white-space: nowrap; }
.hero-summary { font-size: 12px; color: var(--text-secondary); }
.overview-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.overview-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}
.overview-chip-warn { color: #ff4757; border-color: rgba(255, 71, 87, 0.45); }
.overview-chip-muted { opacity: 0.75; }
.slot-card-layer { display: inline-flex; align-items: center; gap: 4px; }
.slot-card-sub { font-size: 10px; color: var(--text-secondary); }

/* ---------- 答案分布明细（choice 全分布 + score 锚点） ---------- */
.dist-block { display: flex; flex-direction: column; gap: 8px; }
.dist-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.dist-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
}
.dist-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.dist-label { font-size: 11px; color: var(--text-secondary); }
.dist-choice { font-size: 13px; font-weight: 700; }
.dist-meta { font-size: 10px; color: var(--text-secondary); }
.dist-legend { font-size: 10px; color: var(--text-secondary); margin-top: 4px; }
.dist-rows { margin-top: 6px; display: flex; flex-direction: column; gap: 3px; }
.dist-row { display: grid; grid-template-columns: 76px 1fr 44px; align-items: center; gap: 6px; }
.dist-row-name { font-size: 11px; color: var(--text-primary); text-align: right; }
.dist-bar-wrap {
  display: block;
  height: 10px;
  background: var(--bg-secondary);
  border-radius: 5px;
  overflow: hidden;
}
.dist-bar { display: block; height: 100%; border-radius: 5px; }
.dist-row-pct { font-size: 10px; color: var(--text-secondary); }
.dist-score-note { font-size: 10px; color: var(--text-secondary); margin-top: 4px; }

/* 涨停复盘（打标轨道研究↔展示同步 2026-10-03；表格/过滤行语言对齐池换手 2026-10-04） */
.limitup-phase-card {
  border: 1px solid var(--panel-border, #2a2f3a);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.limitup-phase-title { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.limitup-phase-note { font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; }
.limitup-phase-band { font-size: 22px; font-weight: 600; color: var(--text-primary); }
.limitup-phase-probs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.limitup-prob-chip {
  font-size: 11px;
  border: 1px solid var(--panel-border, #2a2f3a);
  border-radius: 10px;
  padding: 2px 8px;
  color: var(--text-secondary);
}
/* 过滤行（池换手 to-header/to-filter-btn/to-stats 同款） */
.limitup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin: 10px 0;
}
/* 搜索/排序控件（SectorDetail 成分股表同款语言，2026-10-04 用户令） */
.limitup-controls {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.limitup-controls .search-box { position: relative; flex: 1; min-width: 200px; }
.limitup-controls .search-input {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  font-size: 12px;
}
.limitup-controls .search-input:focus { outline: none; border-color: var(--color-highlight); }
.limitup-controls .search-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 0 4px;
}
.limitup-controls .search-clear:hover { color: var(--text-primary); }
.limitup-controls .sort-controls { display: flex; gap: 4px; }
.limitup-controls .sort-select {
  padding: 6px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}
.limitup-controls .sort-select:hover { border-color: var(--color-highlight); }
.limitup-controls .sort-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.limitup-controls .sort-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.limitup-filters { display: flex; gap: 4px; flex-wrap: wrap; }
.limitup-filter-btn {
  padding: 6px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.limitup-filter-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.limitup-filter-btn.active { background: var(--color-highlight); border-color: var(--color-highlight); color: #000; }
.limitup-stats {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 500;
  background: var(--bg-tertiary, var(--bg-secondary));
  border-radius: 8px;
  padding: 8px 12px;
}
/* 明细表（池换手 to-table 同款：容器边框圆角+sticky 表头+固定列宽+行 hover） */
.limitup-table-container {
  max-height: 500px;
  overflow-y: auto;
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
.limitup-table { border-collapse: collapse; font-size: 12px; width: auto; table-layout: auto; }
.limitup-table th:nth-child(1) { width: 44px; }    /* 序号 */
.limitup-table th:nth-child(2) { width: 104px; }   /* 名称 */
.limitup-table th:nth-child(3) { width: 84px; }    /* 代码 */
.limitup-table th:nth-child(4) { width: 92px; }    /* 驱动 */
.limitup-table th:nth-child(5) { width: 80px; }    /* 驱动置信 */
.limitup-table th:nth-child(6) { width: 88px; }    /* 深度 */
.limitup-table th:nth-child(7) { width: 92px; }    /* 新鲜度 */
.limitup-table th:nth-child(8) { width: 92px; }    /* 买盘逻辑 */
.limitup-table th:nth-child(9) { width: 96px; }    /* 板块 */
.limitup-table th:nth-child(10) { width: 64px; }   /* 热榜 */
.limitup-table th:nth-child(11) { width: 116px; }  /* 相位分线 */
.limitup-table th {
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
.limitup-table th.sortable { cursor: pointer; user-select: none; }
.limitup-table th.sortable:hover { color: var(--color-highlight); }
.limitup-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
  color: var(--text-primary);
}
.limitup-table tbody tr:hover { background: var(--bg-hover); }
.limitup-code {
  color: var(--color-highlight);
  text-decoration: underline;
  text-decoration-color: rgba(255, 127, 80, 0.5);
  font-weight: 500;
}
.limitup-table .num { font-variant-numeric: tabular-nums; }

/* 涨停生态断层标注（§十三） */
.break-card {
  border: 1px solid #b45309;
  background: rgba(180, 83, 9, 0.12);
  color: #fbbf24;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  margin-bottom: 10px;
}

/* ── 题材龙头（v2 题目集投喂可见性，2026-10-20） ── */
.tl-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.tl-meta-chip {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  background: rgba(120, 140, 180, 0.18);
  color: var(--text-secondary, #9aa7bd);
}
.tl-meta-chip.warn {
  background: rgba(220, 150, 60, 0.22);
  color: #e0a95c;
}
.tl-warn-row {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-left: 3px solid #e0a95c;
  background: rgba(220, 150, 60, 0.1);
  font-size: 12px;
  color: #e0a95c;
}
.tl-table {
  font-size: 12px;
}
.tl-row-backfill {
  opacity: 0.82;
}
.tl-choice {
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
  background: rgba(120, 140, 180, 0.2);
}
.tl-choice-high_ge65 { background: rgba(220, 90, 90, 0.3); color: #e88; }
.tl-choice-mid_45_65 { background: rgba(220, 170, 60, 0.28); color: #e0b45c; }
.tl-choice-low_25_45 { background: rgba(90, 170, 220, 0.24); color: #7fb6dc; }
.tl-choice-verylow_lt25 { background: rgba(120, 140, 180, 0.22); color: #9aa7bd; }
.tl-choice-insufficient { background: rgba(140, 140, 140, 0.22); color: #9a9a9a; }
.tl-overridden {
  color: #e0a95c;
  margin-right: 4px;
}
.tl-gate-tag {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 6px;
  background: rgba(220, 150, 60, 0.22);
  color: #e0a95c;
}
.tl-same {
  color: var(--text-tertiary, #6b7787);
  font-size: 11px;
}
.tl-win { color: #67c07a; }
.tl-lose { color: #c9757a; }
.tl-unsealed { color: var(--text-tertiary, #6b7787); }
.tl-narrative-row td {
  background: rgba(0, 0, 0, 0.18);
}
.tl-narrative-title {
  font-size: 11px;
  color: #7fb6dc;
  margin-bottom: 4px;
}
.tl-narrative {
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  line-height: 1.55;
  margin: 0;
  padding: 8px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.28);
  color: var(--text-secondary, #b6c0d0);
}
.tl-gate-note {
  margin-top: 6px;
  font-size: 11px;
  color: #e0a95c;
}
</style>
