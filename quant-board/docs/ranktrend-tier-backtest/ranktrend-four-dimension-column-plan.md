# 行情主页【四维+波动】列实现方案（前端消费后端 signalTier）

> 命名注记（2026-09-06，WP3.1）：本文"四维"为历史命名；当前口径为 **5 投票维（res/rank/vp/cs + 热榜情绪）+ 1 环境门（lifecycle）**，lifecycle 不进投票、以 veto/降档影响合成。

> 主题：行情主页（`DataTable.vue`）展示后端生产的离散档位信号——**四维合并（共振/趋势/量价/周期）
> + 波动观察列（ATR 均值回归，第五观察维，不进 synergy 投票）**
> 状态：**展示形态按 2026-08-29 产品决策冻结**——共振/趋势/量价/周期列保持“方向 + 连续分值”，
> 不恢复各维档位徽章；总体 synergy 仍按现有列展示。档位字段继续由后端生产并供 tooltip/诊断消费。
> 2026-08-16 按生命周期区分度结论优化；2026-08-17 按用户决策修订：
> **ATR 波动列为独立观察列（Phase 2，验证未通过不启用），synergy 保持四维不变**
> 前置：后端五维观察 `signalTier`（共振/趋势/量价/周期/ATR）+ 四维合并 `synergy` 由 Python golden
> 生产（`engine.py`/`volume_price.py`/`ranktrend_routes.py`），前端只消费；ATR 维度已实现
> 但**区分度验证未通过（buy/sell saEx≈0，文档 `ranktrend-atr-signal-design.md` §8）**，波动列不启用
> 关联：回测方案见 `ranktrend-signal-tier-backtest-plan.md`；档位规则见 `ranktrend-observation-discrete-tiers-design.md`；
> ATR 信号设计见 `ranktrend-atr-signal-design.md`

## 1. 背景与目标

1. 现状：行情主页 `src/components/common/DataTable.vue` 的共振/趋势/量价/周期列展示方向箭头 + 连续分（`observation-cell`）；后端同时生产各维 `signalTier`/`tierReasons` 与 synergy 档位，供 tooltip 和诊断使用。
2. 目标（2026-08-29 冻结）：四个观察列继续保持**方向箭头 + 连续分值**，不渲染各维档位徽章；档位缺失时仍按连续分回退，数据不足显示 `--`。周期继续按环境门语义展示。
3. **新增【波动】观察列（v2，Phase 2）**：ATR 均值回归（`observation.atrMeanReversion`）作为**第五观察维独立展示**（方向箭头 + 徽章 + deviation），**不进 synergy 投票**（synergy 保持四维合并）——参照 lifecycle 环境门先例（观察/环境角色不进方向投票）。Phase 1 不实现该列（后端未生产字段），Phase 2 后端实现并验证区分度后落地。
4. 约束：前端只消费后端已产字段，不在前端重算档位；不改动后端生产逻辑（回测方案的参数化/下沉属另一任务，互不阻塞——前端消费的是现有已产字段）。

## 2. 字段合同确认（后端已生产，只读消费）

| 位置（前端读取路径） | 字段 | 类型 | 生产函数 |
|---|---|---|---|
| `stock.rankTrend.resonance` | `signalTier` / `tierReasons` | string / string[] | `engine.py _resonance_tier` |
| `stock.rankTrend.observation.rankTrend` | `signalTier` / `tierReasons` | string / string[] | `engine.py _rank_trend_tier` |
| `stock.rankTrend.observation.volumePrice` | `signalTier` / `tierReasons` | string / string[] | `volume_price.py _volume_price_tier` |
| `stock.rankTrend.observation.lifecycle` | `signalTier` / `tierReasons` | string / string[] | `engine.py _lifecycle_tier` |
| `stock.rankTrend.observation.synergy` | `signalTier` / `tierReasons` | string / string[] | `ranktrend_routes.py _synergy_tier`（实际生产 `volume_price.py::_synergy_tier`） |
| `stock.rankTrend.observation.atrMeanReversion`（**Phase 2 前端列，后端已实现但验证未通过**） | `signalTier` / `tierReasons` / `direction` / `deviation` | string / string[] / string / float | `engine.py analyze_atr_mean_reversion`（`backend/analysis/ranktrend/atr_mean_reversion.py`，**2026-08-17 已实现并挂载**；区分度验证 buy/sell saEx≈0 未通过 + high/low 数据缺口 28%，**【波动】列不启用**，详见 `ranktrend-atr-signal-design.md` §8） |

> **路径口径**：位置列给出**前端读取路径**（`getRankTrendAnalysis(stock) = stock.rankTrend`，`DataTable.vue:1075`；resonance 已按 `rankTrend.resonance` 读取，`DataTable.vue:815`）。后端组装术语为 `analysis.resonance`（顶层）与 `analysis.observation.*`（`ranktrend_routes.py:378-409`），实现 getter 时**以本表前端路径为准，勿照抄后端路径**。

档位枚举（全局统一）：`S / A / B / C / D / E / unknown`。`unknown` 表示样本不足/数据缺失，前端显示 `--`，**不归零、不伪装**（fail-visible-data-pipelines）。

> 注意：`signalTier` 为可选字段（后端可能因版本/降级缺失），前端读取必须**容错缺字段**：
> 当前 UI 无论字段是否存在均保持方向箭头 + 连续分；缺失时不显示档位，不把数据归零。

## 2.1 优化说明（2026-08-16，基于生命周期区分度结论）

**数据结论**（`ranktrend-lifecycle-threshold-optimization-design.md` §8.2，坐标下降搜索证明）：
lifecycle 档位（A/B/C/D/E）**无方向区分度**——A（优选路径 ignition/expansion）h8 excess 0.0092
**反低于** B（谨慎）0.0228，且该关系是分位结构性差异（A 高分位混杂被均值回归拉低），阈值不可调。

**对展示的影响（本方案优化点）**：
1. **周期列不做方向色徽章**——原方案把四列统一升级为方向徽章，会误导用户以为 lifecycle 的
   A/B 档有方向强弱语义；实际 A 档股票 h8 表现弱于 B 档。改为**环境门标签**：显示 stage
   中文名（点火/扩散/拥挤/反转/冷却）+ 环境色（veto=红实心、反转/拥挤=橙、冷却=灰），
   悬停注明"生命周期为环境门，不预测方向，仅参与 synergy 环境修正/否决"；
2. **【四维】synergy 总档列置末**（用户确认列顺序）：synergy 是唯一有方向区分度的合并信号
   （阶段 3：S/A/B excess 单调 0.088/0.039/-0.006），作为总档展示在周期列之后；
3. **悬停明细**：四维明细中 lifecycle 标注"环境门"，synergy reasons 展示四维投票构成
   （如 `共振S · 趋势A · 量价B · 周期[环境]`），缺维显示 `-`；
4. 共振/趋势/量价三列保持方向箭头 + 连续分，不增加档位徽章；方向区分度结果只用于诊断和回测。

### 2.2 ATR 波动观察列决策（2026-08-17，用户确认）

**决策**：ATR 均值回归信号（`observation.atrMeanReversion`）作为**第五观察维独立展示**
（【波动】列），**不进 synergy 投票——synergy 保持四维合并**。

依据：
1. **信息正交**：ATR 是价格相对波动通道的偏离（`deviation=(close−ref)/ATR`），与四维
   （排名/涨跌/量比/资金/环境）无重叠（`ranktrend-atr-signal-design.md` §5.2 正交性验证计划）；
2. **方向相反**：ATR 是**逆向/回归**信号（超买 sell/超卖 buy），与共振/趋势/量价的**追强**
   方向天然相反——直接并入五维投票会造成 synergy 自相矛盾（同一天 ATR 超买 sell、
   共振追强 buy）；
3. **先例**：参照 lifecycle 环境门（观察/否决角色，不进方向投票），ATR 初始为纯观察列；
4. **验证路径**：区分度（buy/sell 分组）与正交性验证通过后，再评估 ATR 角色
   （独立否决条件/观察权重），届时走 golden 变更流程（不写回默认值原则）。

**展示**：方向箭头（超买 ↑sell / 超卖 ↓buy）+ 档位徽章 + deviation 数值 + "回归"标签，
与四维列同构；`unknown` 显示 `--`；**Phase 2 后端实现前该列不渲染**（字段缺失 → 列隐藏，
fail-visible）。

## 3. TS 类型补充（`src/services/rankTrend/types.ts`）

1. 新增档位类型：

```ts
/** 四维观察信号离散档位（后端 Python golden 生产，前端只消费） */
export type RankTrendSignalTier = 'S' | 'A' | 'B' | 'C' | 'D' | 'E' | 'unknown'

/** 档位命中规则原文（后端 tierReasons） */
export type RankTrendTierReasons = string[]
```

2. 各接口补可选字段（不破坏现有消费）：

```ts
export interface RankTrendObservationScores {
  rankTrend: {
    direction: RankSignalDirection
    score: number
    signedScore: number
    signalTier?: RankTrendSignalTier   // 新增
    tierReasons?: RankTrendTierReasons // 新增
  }
  lifecycle?: {
    // ...现有字段
    signalTier?: RankTrendSignalTier   // 新增
    tierReasons?: RankTrendTierReasons // 新增
  }
  volumePrice?: RankTrendVolumePrice   // 见下
  synergy?: RankTrendSynergy           // 见下
}

export interface RankTrendVolumePrice {
  score: number | null
  direction: 'up' | 'down' | 'neutral' | null
  quadrant: 'rise_volume' | 'rise_shrink' | 'fall_volume' | 'fall_shrink' | 'normal' | null
  reasons: string[]
  breakdown?: { direction: number; volume: number; fund: number }
  signalTier?: RankTrendSignalTier   // 新增
  tierReasons?: RankTrendTierReasons // 新增
}

export interface RankTrendSynergy {
  state: '启动确认' | '主升确认' | '风险升级' | '退潮' | '存疑' | 'noData'
  hardWarn: boolean
  reasons: string[]
  signalTier?: RankTrendSignalTier   // 新增
  tierReasons?: RankTrendTierReasons // 新增
}

// Phase 2（ATR 波动观察列，后端实现后启用；synergy 不消费该字段）
export interface RankTrendAtrMeanReversion {
  status: 'ok' | 'insufficient'
  direction: 'buy' | 'sell' | 'hold' | null
  score: number | null
  deviation: number | null
  signalTier?: RankTrendSignalTier   // 新增
  tierReasons?: RankTrendTierReasons // 新增
}

export interface RankTrendResonance {
  // ...现有字段（direction/score/label 等）
  signalTier?: RankTrendSignalTier   // 新增（前端挂 stock.rankTrend.resonance，对应后端 analysis.resonance 顶层字段）
  tierReasons?: RankTrendTierReasons // 新增
}
```

3. 读取辅助（放 `RankTrendObservationService` 或 DataTable 内，建议服务层）：

```ts
export function getSynergyTier(stock: any): { tier: RankTrendSignalTier | null; reasons: string[]; detail: ... } {
  const syn = stock?.rankTrend?.observation?.synergy
  if (!syn || !syn.signalTier) return { tier: null, reasons: [] }
  // 同时收集四维各自 tier 供悬停明细
}
```

## 4. DataTable.vue 改造

### 4.1 列定义

- 现有四列（`DataTable.vue:334-337`）label 不变，列宽略增以容纳徽章：
  - `resonanceIntensity: '52px' → '78px'`
  - `rankTrendStrength: '52px' → '78px'`
  - `volumePriceQuadrant: '52px' → '78px'`
  - `lifecycleOpportunity: '64px' → '86px'`（环境门标签，宽度容纳 stage 中文名）
- 新增列（**紧跟周期列之后**，`group: 'comprehensive'`；用户确认列顺序 synergy 置末）：

```ts
{ key: 'atrMeanReversion', label: '波动', group: 'comprehensive', always: true }, // Phase 2：ATR 观察列（后端未实现前不渲染）
{ key: 'synergyTier', label: '四维', group: 'comprehensive', always: true },      // 合并总档置末
// COLUMN_WIDTHS:
atrMeanReversion: '72px',  // 方向箭头 + 徽章 + deviation（如 ↓2.4）
synergyTier: '64px',
```

### 4.2 单元格模板

**共振/趋势/量价三列升级**（以共振列为模板，三列同构；周期列不同，见下）：

```html
<template v-else-if="col.key === 'resonanceIntensity'">
  <div class="observation-cell" @click.stop="openObservationPanel(stock, 'resonance')"
    @mouseenter="showTierTooltip($event, stock, 'resonanceIntensity')"
    @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
    <template v-if="getResonanceCellValue(stock) != null">
      <span :class="getResonanceCellClass(stock)">
        {{ getDirectionArrow(getResonanceDirection(stock)) }}
      </span>
      <span v-if="getResonanceTier(stock)" :class="tierBadgeClass(getResonanceTier(stock))">
        {{ getResonanceTier(stock) }}
      </span>
      <span :class="getResonanceCellClass(stock)">{{ getResonanceCellValue(stock) }}%</span>
    </template>
    <span v-else class="trend-steady">--</span>
  </div>
</template>
```

**周期列改为环境门标签**（不做方向徽章——§2.1 优化）：显示 stage 中文名 + 环境色，veto 红角标：

```html
<template v-else-if="col.key === 'lifecycleOpportunity'">
  <div class="observation-cell lifecycle-cell" @click.stop="openObservationPanel(stock, 'lifecycle')"
    @mouseenter="showTierTooltip($event, stock, 'lifecycleOpportunity')"
    @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
    <template v-if="getLifecycleStage(stock) != null">
      <span v-if="getLifecycleVeto(stock)" class="lifecycle-veto-badge" title="生命周期一票否决">否决</span>
      <span :class="lifecycleEnvClass(getLifecycleStage(stock))">{{ lifecycleStageLabel(getLifecycleStage(stock)) }}</span>
    </template>
    <span v-else class="trend-steady">--</span>
  </div>
</template>
```

**新增【波动】列（Phase 2，ATR 观察列——后端实现后启用；方向箭头 + 徽章 + deviation）**：

```html
<template v-else-if="col.key === 'atrMeanReversion'">
  <div class="observation-cell atr-cell"
    @click.stop="openObservationPanel(stock, 'atr')"
    @mouseenter="showTierTooltip($event, stock, 'atrMeanReversion')"
    @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
    <template v-if="getAtrSignal(stock) != null">
      <span :class="getAtrCellClass(stock)" :title="getAtrDirectionLabel(stock) + '：回归预期'">
        {{ getDirectionArrow(getAtrDirection(stock)) }}
      </span>
      <span v-if="getAtrTier(stock)" :class="tierBadgeClass(getAtrTier(stock))">
        {{ getAtrTier(stock) }}
      </span>
      <span :class="getAtrCellClass(stock)">{{ getAtrDeviation(stock) }}</span>
    </template>
    <span v-else class="trend-steady">--</span>
  </div>
</template>
```

> **Phase 2 说明**：后端 `observation.atrMeanReversion` 未实现前，该列定义存在但
> **列渲染函数检测字段缺失时跳过该列**（列配置按数据可用性过滤），不显示空列（fail-visible）。

**新增【四维】列**（synergy 档位徽章，置末）：

```html
<template v-else-if="col.key === 'synergyTier'">
  <div class="observation-cell synergy-tier-cell"
    @mouseenter="showTierTooltip($event, stock, 'synergyTier')"
    @mousemove="moveConfidenceTooltip($event)" @mouseleave="hideConfidenceTooltip">
    <span v-if="getSynergyTier(stock)" :class="tierBadgeClass(getSynergyTier(stock))">
      {{ getSynergyTier(stock) }}
    </span>
    <span v-else class="trend-steady">--</span>
  </div>
</template>
```

### 4.3 读取与工具函数

- 复用现有 `getRankTrendAnalysis(stock) = stock.rankTrend`（`DataTable.vue:1075`）读取 `observation`。
- 新增 `getResonanceTier/getRankTrendTier/getVolumePriceTier/getSynergyTier(stock)` 四个方向档 getter（缺字段返回 null，回退纯连续分展示）。
- **ATR getter（Phase 2）**：`getAtrSignal(stock)`（读 `observation.atrMeanReversion`，缺字段返回 null → 列隐藏/`--`）、`getAtrDirection/getAtrTier/getAtrDeviation(stock)`、`getAtrDirectionLabel(stock)`（超买/超卖）、`getAtrCellClass(stock)`（复用方向色：超买同 sell 绿/超卖同 buy 红）。
- 周期列工具：`getLifecycleStage`（已有，`DataTable.vue:804`）、`getLifecycleVeto(stock)`（读 lifecycle.veto 布尔）、`lifecycleStageLabel(stage)`（stage→中文：ignition=点火/expansion=扩散/crowded=拥挤/reversal=反转/cooling=冷却）、`lifecycleEnvClass(stage, veto)`（环境色：veto=红实心、crowded/reversal=橙、cooling=灰、ignition/expansion=中性）。
- `showTierTooltip`：扩展 `confidenceTooltip` 机制（`DataTable.vue:201-203`），content 拼 `tierReasons` 全文；四维列悬停显示合并 reasons + 四维明细（如 `共振S · 趋势A · 量价B · 周期[环境门]`），缺维显示 `-`；**波动列悬停（Phase 2）**：显示 ATR reasons + 标注"回归信号，不进 synergy 投票，仅观察"；周期列悬停注明"生命周期为环境门，不预测方向，仅参与 synergy 环境修正/否决"。
- `tierBadgeClass(tier)`：返回档位徽章样式类（§4.4）。

### 4.4 徽章样式（与现有观察色系对齐，`DataTable.vue:2649-2670`）

```css
/* 档位徽章 */
.tier-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin: 0 3px;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  line-height: 18px;
}
.tier-s  { color: #ff4757; background: rgba(255, 71, 87, 0.14); border: 1px solid rgba(255, 71, 87, 0.5); }   /* 强信号（同 buy 红） */
.tier-a  { color: #ff6b81; background: rgba(255, 107, 129, 0.12); border: 1px solid rgba(255, 107, 129, 0.4); } /* 确认 */
.tier-b  { color: #ff9f43; background: rgba(255, 159, 67, 0.12);  border: 1px solid rgba(255, 159, 67, 0.4); }  /* 弱确认（同 crowded 橙） */
.tier-c  { color: #95a5a6; background: rgba(149, 165, 166, 0.12); border: 1px solid rgba(149, 165, 166, 0.4); } /* 中性（同 hold 灰） */
.tier-d  { color: #2ed573; background: rgba(46, 213, 115, 0.12);  border: 1px solid rgba(46, 213, 115, 0.4); }  /* 反向/回避（同 sell 绿） */
.tier-e  { color: #fff; background: #e74c3c; border: 1px solid #c0392b; box-shadow: 0 0 6px rgba(231, 76, 60, 0.6); } /* 硬风险：实心警示 */
.tier-unknown { color: #7f8c8d; background: transparent; border: 1px dashed #7f8c8d; }                          /* 数据不足：虚线占位 */
```

- E 档（硬风险）用实心警示底，区别于 S 的亮红描边，符合设计文档"E 档警示样式"验收。
- 暗色主题下对比度校验：红/绿/橙/灰均沿用现有 observation 色系（已在使用），E 档白字深红底对比度达标。
- 若暗色主题变量（`--text-primary` 等）存在，优先用主题变量覆盖徽章文字色。
- **波动列（Phase 2）**：复用 `observation-cell` 基础样式；方向色沿用既有（超买=sell 绿、超卖=buy 红）；
  deviation 数值用 `observation-value` 样式；"回归"语义通过悬停 title + reasons 表达（不做额外色徽章，
  避免与四维方向色混淆）。

## 5. 验收

| 项 | 内容 | 验收方式 |
|---|---|---|
| 1 | 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 无错误 |
| 2 | 单元测试 | `pnpm test`：新增 getter/tierBadgeClass 用例 + 缺字段回退用例（`src/components/common/__tests__/` 或 `src/services/rankTrend/__tests__/`） |
| 3 | 浏览器渲染（Playwright） | 行情总览页：观察列保持「方向箭头 + 连续分」；不渲染各维档位徽章；悬停可显示 tierReasons；`unknown` 显示 `--`；无横向溢出、控制台无错误 |
| 4 | 数据回退 | mock 无 `signalTier` 字段的数据，确认回退为纯连续分展示（不渲染徽章、不报错）；**波动列字段缺失 → 列隐藏**（fail-visible，Phase 1 后端未实现即应验证） |
| 5 | 波动列（Phase 2，后端实现后） | mock 含 `observation.atrMeanReversion` 数据：方向箭头 + 徽章 + deviation 渲染；悬停显示"回归信号，不进 synergy 投票，仅观察"；`unknown` 显示 `--`；四维列悬停明细含 `波动[回归]` |

## 6. 实施步骤

**Phase 1（四维升级 + 【四维】总档列，不依赖后端新字段）**：
1. `types.ts` 补 `RankTrendSignalTier` + 四个接口可选字段 + 服务层 getter 与单测。
2. `DataTable.vue`：列定义 + 列宽 + 四列模板升级 + 新增【四维】列模板 + `tierBadgeClass`/`showTierTooltip` + 样式。
3. 单测 + 类型检查 + Playwright 浏览器验收（`skills/playwright-cli/SKILL.md` 流程，dev server `pnpm dev` 与 QuantBoard 后端 `8000` 需可用；若后端不可用则用 mock 数据验收并注明）。
4. 交付前 `verification-before-completion`。

**Phase 2（【波动】ATR 观察列，依赖后端 ATR 信号实现）**：
5. 后端实现 ATR 信号（`ranktrend-atr-signal-design.md` v2：纯函数 golden case → replay 挂载
   `observation.atrMeanReversion` → buy/sell 分组区分度验证 → 样本外复核）。
6. `types.ts` 补 `RankTrendAtr` 接口 + ATR getter 与单测；`DataTable.vue` 启用波动列（列配置按
   字段可用性过滤，缺失即隐藏）。
7. 波动列渲染验收（验收项 5）+ 四维悬停明细含波动。

## 7. 风险与回退

- **字段缺失容错**：后端降级/旧版本无 `signalTier` 时，前端必须回退连续分展示（§4.3 缺字段返回 null），不得渲染空徽章或报错。
- **列宽挤压**：四列各增 ~26px，小屏/横向溢出风险 → Playwright 检查 1280px 视口横向滚动是否正常，必要时缩小徽章字号。
- **与用户未提交改动冲突**：`DataTable.vue` 当前有用户未提交改动（`volumeRatio` 列宽 40→50px，`git diff` 已核对），实现时增量修改、不覆盖该改动。
- **后端参数化/下沉未完成**：本方案消费的是**当前已生产字段**，与回测方案（`ranktrend-signal-tier-backtest-plan.md`）互不阻塞；回测方案落地后前端无需改动（字段名与语义不变）。
- **回退**：删除新增列定义 + 徽章模板 + 样式即可恢复现状，无数据迁移、无 API 合同变化。
