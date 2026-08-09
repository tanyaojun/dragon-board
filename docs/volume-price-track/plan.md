# 量价关系 × 三指标结合（方案 2 + 展示）实施计划

> 状态：展示层已实施（2026-08-09）；信号层（候选池观察项）待后续执行。
> 关联前置：volumeRatio 口径统一为 golden 三日 + 当日相对阈值（`docs/volume-price-track` 前置改动见
> `src/services/market/volume_ratio_service.py`、`src/utils/volumeRatio.ts`）。

## 1. 目标

把【共振强度】【排名趋势】【生命周期】三个排名/情绪维度指标与量价关系结合：

1. **展示层**：表格新增「量价配合」四象限列 + 三指标行内「量价确认」标记，让"量价对不上"的问题一眼可见。
2. **信号层**：新增「量价验证」轨，作为候选池决策观察项（fail 不否决，只降可信度并给出结构化原因）。

约束：不动 Python golden（`quant-board/backend/analysis/ranktrend/engine.py` 零改动）；fail-visible（量价缺失 → noData 标记 + 原因，三指标照常输出）；不引入新的硬门禁。

## 2. 已确定口径（2026-08-09 定稿）

| 维度 | 口径 |
|---|---|
| 放量/缩量 | **绝对阈值（golden 3 日口径）**：量比 ≥ 1.05 放量、≤ 0.95 缩量（量比 = 当前量 / 近 3 日同期均量 × 交易进度，>1 即放量，业务语义清晰）。**放弃**相对阈值（中位数×倍数）——实证盛达资源 000603 量比 1.11（>1，放量）被中位数×1.5 误判为常态 |
| 资金 | `zlje > 0 && (zljzb 缺失时仅 zlje) > 0` → 资金配合；`zlje <= 0` → 资金背离；zlje 缺失 → noData |
| 四象限 | `change` 方向 × 放缩量：放量上涨 / 缩量上涨 / 放量下跌 / 缩量下跌 |

## 2.1 评分权重依据（stock_rows 日级快照，5/10/20 交易日实证）

| 量价组合 | 5日次日上涨/涨停 | 10日 | 20日 | 结论 |
|---|---|---|---|---|
| 全样本 | 77.9% / 17.6% | 59.7% / 12.8% | 55.3% / 11.3% | — |
| 放量上涨 | 74.1% / 17.2% | 61.2% / 13.4% | 59.4% / 13.5% | 中等 |
| 缩量上涨 | 82.2% / 21.2% | 70.5% / 17.6% | 67.1% / 19.1% | **热榜池涨停板效应，不取** |
| 缩量上涨+资金流出 | 86.5% / 28.8% | 74.6% / 23.8% | 68.8% / 25.0% | 一字板/封死，不可回测 |
| **缩量下跌** | 51.4% / 5.7% | 52.2% / 7.1% | **43.7% / 4.8%** | **三窗口一致最弱 → 重扣** |
| 放量下跌 | 74.5% / 5.9% | 60.8% / 7.2% | 58.4% / 6.2% | 上涨率高但涨停率最低 → 扣分 |

**结论**：热榜池内"缩量上涨强"是涨停板效应（不可交易复现），多头端取行业共识语义；风险端（缩量下跌最弱、放量下跌涨停率最低）数据稳健，直接采用。资金流出组胜率系统性低于流入组（5/5 天）→ 资金 ±15。

## 3. 展示层（任务 1，已实施）

### 3.1 新增「量价配合」四象限列（DataTable）

- 列 `key: 'volumePriceQuadrant'`，`label: '量价'`，置于排名趋势列旁。
- **列内文本参照三指标列「方向 + 数值」**：↑/↓ 为涨跌方向，数值为**量价综合评估值 0-100**（`computeVolumePriceScore`，**回测直接消费该数字**）；完整四象限语义（放量上涨等）由颜色（quadrant-*）与 tooltip 承载。确认/存疑标记只进 tooltip，不填入列值。
- **评分公式（50 基准 + 方向±10 + 量价交叉 + 资金±15 + 组合+10，clamp 0-100）**：
  - 方向：涨 +10 / 跌 -10（弱权重）
  - 量价交叉：放量上涨 +20 / 缩量上涨 -10 / 放量下跌 -20 / **缩量下跌 -15** / 常态 0（风险端数据稳健，多头端行业共识）
  - 资金：配合 +15 / 背离 -15（数据实证 5/5 天流出组胜率低）
  - 组合加成：放量上涨 + 资金配合 +10（数据最优组合）
  - 例：放量上涨+流入 = 100；缩量上涨+流入 = 65；缩量下跌+流出 = 10；放量下跌+流出 = 5
- **绝对阈值**：放量 ≥ 1.05；缩量 ≤ 0.95（量比 >1 即放量，业务语义清晰）。
- 颜色：放量上涨 `#ff4757`、缩量上涨 `#ffb142`、放量下跌 `#4a90e2`、缩量下跌 `#7f8c8d`、量能常态中性色；量价数据不足 → `--`（不伪造）。
- **展示风格/tooltip 参照三指标观察列**：使用 `observation-cell` 容器，hover 走 `showConfidenceTooltip(field='volumePriceQuadrant')`，
  tooltip 为 `getFieldTooltip` 新增分支（【量价配合】：综合评估/涨跌/量能/资金/评分分解（三项具体分值+该股数据）/依据），与共振/排名趋势/生命周期同格式；
  量价配合不依赖 rankTrend 分析，跳过「暂无信号」兜底拦截。
- **不依赖中位数基准**（绝对阈值，量比 >1 放量 / <1 缩量）；后端不再落库 volumeRatioMedian，前端无拉帧/本地回退代码（2026-08-09 晚清理）。

## 2.2 评分权重定稿（2026-08-09 晚，按用户确认）

**缩量涨停最优、过度放量/高净占比判出货**（连续化）：

| 维度 | 规则 |
|---|---|
| 方向 | 涨 +min(15, change×1.5)；跌 -min(15, \|change\|×1.5) |
| **量价（涨停阈值按板块，复用 `liveLimitState.resolveLiveLimitState`）** | 主板 10% / 创业板·科创板 20%（300/301/688/689） / 北交所 30%（8/4/9 开头） |
| 缩量涨停（vr<0.95 且达板块涨停） | **+25**（封板惜售，好票） |
| 缩量上涨（非涨停） | +10~15 |
| 温和放量上涨（1.05≤vr≤2） | +10~15 |
| 放量过大（2<vr≤2.5）→ 渐扣；**过度放量（vr>2.5）** | **−15~−20（出货风险）** |
| 缩量下跌 / 放量下跌 | −10 / −20 |
| **资金** | 0<zljzb≤20 → +min(15, zljzb×3)；**zljzb>20 → −10~−15（净占比异常高，疑似对倒出货，不奖反罚）**；zljzb<0 → −流出；缺失按 zlje 符号 ±5 |

**实测（2026-08-09）**：哈药 600664 缩量涨停 vr=0.75 但净占比 53.83%（出货）→ 75 分；盛达 000603 放量涨停 vr=1.11 净占比 5.97% → 91 分；热榜池 100 分 10 只（从档位式 91 只降下来），40-90 区间铺开。
**板块验证**：创业板 20% 涨停（300363 20.02%）正确识别涨停级；创业板 12% 不误判涨停（单测覆盖）。

### 3.2 三指标行内「量价确认」标记（已移除，改为独立列方案）

- **初版曾把中文确认标记塞进三指标数值列，破坏紧凑可读性，已撤回**（2026-08-09 视觉修正）。
- 现行：三指标数值列保持纯数字/箭头（`↑5%` + macd `▲▼`），**不混入中文**；量价配合状态统一由「量价配合」四象限列表达（3.1）。
- 确认状态（confirmed/suspect/conflict）逻辑保留在 `volumePriceValidation.ts::classifyVolumePriceConfirmation`，供信号层（候选池观察项）使用，不在表格行内展示。

## 4. 信号层（任务 2，待执行）

### 4.1 量价验证轨（`src/services/rankTrend/volumePriceValidation.ts`）

```ts
type VolumePriceStatus = 'confirmed' | 'suspect' | 'conflict' | 'noData'
interface VolumePriceValidationResult {
  status: VolumePriceStatus
  reasons: string[]
  quadrant: VolumePriceQuadrant | null
  fund: 'support' | 'divergent' | 'noData'
  volume: 'up' | 'down' | 'normal' | 'noData'
}
```

- 组合：共振↑ + 资金配合 + 放量 → confirmed；共振↑ + 资金背离/缩量 → suspect（标记不停产）；
  生命周期 crowded/reversal + 资金流出 → conflict（风险升级）。
- 复用 `statusClassifier.ts::classifyVolumeConfirmation`（healthy/weak/overheated/divergent，横截面 P50/P70/P85）
  作为基础量价信号，组合逻辑叠加方向/生命周期；口径差异大时量能子信号独立用 `classifyVolumeRatio`。

### 4.2 预计算缓存字段（`RankTrendSignalService.ts::precomputeDisplayFields`）

- 新增 `_volumePriceStatus/_volumePriceReasons/_volumePriceQuadrant`（`_` 前缀缓存字段，DataTable/排序/导出直接读）。

### 4.3 候选池观察项（`v5FusionExecutionContract.ts::evaluateV5FusionEntry`）

- 新增 `buildLiveGateCheck({ key: 'volume_price_confirmation', hardBlock: false, status })`：
  - confirmed → pass（考虑加入 `hasRecallSignal` 白名单提升 auto_add）
  - suspect/conflict → warn（自动降级 watch_candidate，不否决）
  - noData → pass（缺数据不惩罚）

## 5. 文件清单

| 类型 | 文件 | 阶段 |
|---|---|---|
| 新增 | `src/services/rankTrend/volumePriceValidation.ts` | 展示层（纯函数）+ 信号层（组合） |
| 修改 | `src/components/common/DataTable.vue`（列 + tooltip + 样式） | 展示层 ✅ |
| 修改 | `src/services/dataLoader/RankTrendSignalService.ts`（预计算缓存字段） | 信号层 |
| 修改 | `src/services/rankTrend/v5FusionExecutionContract.ts`（观察项） | 信号层 |
| ~~删除~~ | ~~`src/services/volumeRatioMedian.ts`~~（绝对阈值后不再需要，2026-08-09 晚已删除） | — |
| 修改 | `src/config/constants.ts`（标签常量） | 展示层 ✅ |
| 新增 | `src/services/rankTrend/__tests__/volumePriceValidation.test.ts` | 各阶段 |
| 修改 | `src/components/common/__tests__/DataTable.test.ts`（源码断言） | 展示层 ✅ |
| 新增 | `docs/volume-price-track/plan.md` | 本文件 |

## 6. 验证

1. Vitest 全量 + `vue-tsc`；量价验证单测（四象限边界、缺失字段、confirmed/suspect/conflict/noData 全分支）。
2. `v5FusionExecutionContract` 测试：warn 降级 watch_candidate、confirmed 不阻断（信号层）。
3. 浏览器验收（playwright-cli）：四象限列渲染、行内标记、tooltip reasons、Console 无错误、无横向溢出。
4. 不做：Python `engine.py` 改动、回测/优化。

## 7. 风险与边界

- 量价数据缺失 → `score=null` 降级（不报错、不伪造）。
- `classifyVolumeConfirmation`（P50/P70/P85）与量价绝对阈值（量比 >1/<1）口径差异需在信号层复用前对齐验证。
- **板块涨停边界**（复用 `liveLimitState.resolveLiveLimitState`）：9 开头 B 股（900xxx 沪 B）会被 fallback 判为北交所 30%（既有代码缺陷，热榜池无 B 股，影响忽略）；无 ST 标记（ST 股 5% 涨停无法判断）——两者记录待数据源补齐后处理。
- 排序/列宽/主题沿用现有模式，不引入新依赖。
- 四象限列暂不参与排序（保持最小改动），后续需要时按象限 rank 排。
