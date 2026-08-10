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
- **评分公式（50 基准 + 方向八档±15 + 量价交叉 + 资金±15，clamp 0-100）**：
  - 方向（涨跌幅八档，对称）：涨停/跌停（板块阈值 9.8/19.8/29.8）±15；7%+ ±12；5-7% ±10；3-5% ±8；2-3% ±6；1-2% ±4；0.5-1% ±2；0-0.5% ±1；平盘 0
  - 量价交叉（量比幅度 + 板块涨停语境）：缩量涨停 +25；缩量上涨（非涨停）+10~15；温和放量上涨（1.05≤vr≤2）+10~15；过度放量（vr>2.5）-15~-20（出货）；缩量下跌 -10；放量下跌 -20；常态 ±5
  - 资金：净占比 zljzb 0<≤20 → +min(15, zljzb×3)；zljzb>20 → -min(15, 10+(zljzb-20)×0.5)（对倒出货）；zljzb<0 → -min(15, |zljzb|×3)；缺失按 zlje 符号 ±5
  - 例：缩量涨停+流入 = 93；放量上涨+流入（vr=1.5）≈ 85；缩量上涨+流入 ≈ 65；放量下跌+流出 ≈ 5
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

---

# 阶段 2：四象观察面板（2026-08-09 晚定稿）

## 8. 目标

把量价从「孤立评分」升级为**四象协同的验证轴**：阶段（纲）× 量能（验证）为核心，技术/共振协同，量价最终**影响共振路径结果分数**（后端 API 层修正，用户选 A）并进候选池分层。三轨观察面板扩容为**四象观察面板**（新增【量能协同】页）。

## 9. 量价分统一（后端生产，与三轨数据链路一致）

- **量价分 = 行情列表【量价】分同一公式**（`computeVolumePriceScore` 同口径：方向 + 量价交叉 + 资金 + 板块涨停，0-100），**由后端生产**为 `observation.volumePrice = { score, direction, quadrant, reasons }`，与 `observation.rankTrend / lifecycle` 并列。
- **前端只消费**（删本地计算），数据链路与三轨一致：后端 `/api/ranktrend/analyze` → observation 字段 → RankTrendSignalService 投影 `_volumePriceScore/_volumePriceDirection/_volumePriceQuadrant/_volumePriceReasons` → DataTable 量价列 / 四象面板读取。
- 放弃独立「阶段×量能矩阵分」（避免第三套量价分）；矩阵语义（点火/扩散放量=启动、拥挤/反转放量=出货）移入四象协同状态机（§10）。

## 10. 四象协同状态机（后端生产 `observation.synergy`）

```
状态：启动确认 / 主升确认 / 风险升级 / 退潮 / 存疑（输入：阶段 rail + 量价分 + 技术 + 共振）
- 启动确认：点火/扩散 + 量价分 ≥ 75 + 技术 buy + 共振 ↑
- 主升确认：扩散 + 量价分 ≥ 75 + 技术 buy + 共振 ↑
- 风险升级：拥挤/反转 + 量价分 ≤ 40 或 资金对倒
- 退潮：降温 + 量价分 ≤ 40
- 存疑：其余（共振↑但量价分低 = 无量虚涨 / 技术 buy 但量价证伪等）
输出：observation.synergy = { state, reasons[四维各自贡献/背离], hardWarn: bool }
```

## 11. 后端生产（A 方案，动 golden 输出合同）

- Python 移植量价评分（`compute_volume_price_score`，同 TS 口径：方向/量价交叉/资金/板块涨停），在逐股循环（ranktrend_routes.py:358-386）产出 `observation["volumePrice"]`。
- 共振修正（`_apply_resonance_final` :449-465）：
  - `resonance["rawScore"] = 原始排名动量分`（保留，面板对比）
  - `resonance["score"] = clamp(resonance.score + (vpScore−50)×0.15, 0, 100)`（修正后，消费默认；权重 0.15 = 满分 ±7.5，避免高分堆积——0.6/0.3 时共振高分占比过高）
  - `decision.final.confidence = 修正后 score`；量价分 ≤ 40 且 direction=buy → final 降级 hold
- 协同状态 `observation["synergy"]`（§10）后端产出。
- **golden 对齐**：更新 golden case（resonance.score 语义 + 新 observation.volumePrice/synergy 字段）+ pytest。前端 `_resonancePct`（RankTrendSignalService:212 读 resonance.score）自动消费修正后分数。

## 12. 前端消费改造（只消费，不生产）

- `RankTrendSignalService.precomputeDisplayFields`：投影 `_volumePriceScore/_volumePriceDirection/_volumePriceQuadrant/_volumePriceReasons`（读 observation.volumePrice）；`_synergyState/_synergyReasons`（读 observation.synergy）。
- `volumePriceValidation.ts`：**删除前端 `computeVolumePriceScore` 本地计算**（后端生产）；保留类型/标签/分类纯函数（classifyVolumeRatio 用于量比列颜色，classifyVolumePriceQuadrant 若后端已产则删）。
- `DataTable.vue`：量价列改读 `_volumePriceScore`（无 rankTrend 时 `--`，与三轨一致）；tooltip 读 `_volumePriceReasons`。
- 四象观察面板：`RankTrendObservationPanel.vue` 改名，`ObservationTrack` 扩 `'volumePrice'`，tracks 增 `{ id: 'volumePrice', index: '04', label: '量能协同' }`；第 4 页展示：量价分（与列表一致）+ 共振 rawScore vs score 对比 + 四象协同状态/依据。

## 13. 候选池消费

- `v5FusionExecutionContract` 加协同状态观察项（读 observation.synergy）：启动/主升确认 → 加分（候选提升）；风险升级 → warn（降级 watch_candidate 不否决）；退潮/存疑 → 中性。fail-visible（缺 synergy → 中性不惩罚）。

## 14. 文件清单

| 类型 | 文件 |
|---|---|
| 后端 | `ranktrend_routes.py`（量价评分 + observation.volumePrice + 共振修正 + observation.synergy）、新增量价评分/协同测试、golden case 更新 |
| 前端 | `rankTrend/types.ts`（ObservationTrack + observation 契约）、`RankTrendSignalService.ts`（投影 _volumePrice*/_synergy*）、`DataTable.vue`（量价列读后端字段）、`RankTrendObservationPanel.vue`（改名 + 第 4 页）、`volumePriceValidation.ts`（删本地计算）、`v5FusionExecutionContract.ts`（观察项）、相应测试 |
| 文档 | 本文件（阶段 2 章节） |

## 15. 验证

1. 后端 pytest（golden case 对齐 + 量价评分/共振修正/协同状态用例）。
2. 前端 vitest 全量 + vue-tsc（量价列读后端字段、四象面板第 4 页、候选池观察项）。
3. 浏览器验收（playwright-cli）：四象面板第 4 页渲染、量价分与列表一致、共振修正前后对比、协同状态、无 Console 错误。
4. 不做：回测/优化（协同分进回测属后续独立项）。
