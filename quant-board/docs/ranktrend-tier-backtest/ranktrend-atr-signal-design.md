# ATR 真实波动均值回归信号设计（2026-08-17，v2 审计修订，后端已实现）

> 状态：**设计定稿 + 后端已实现（2026-08-17 TDD）**——已按对抗性审计修订（v2）：
> 缺帧断档处理、ATR 算法口径明确为简单均值、S 档阈值、MA20 样本门槛、验证按 direction 分组、
> bar 口径（单帧 TR≈0 风险）、引用位置修正
> 实现：`backend/analysis/ranktrend/atr_mean_reversion.py`（纯函数）+ `engine.py` replay 挂载
> （`observation.atrMeanReversion`，断档重置/缺帧计数/截断）；测试 `tests/test_atr_mean_reversion.py`
> （16 用例，144 相关测试全绿，golden 不漂移）
> 待办：区分度验证（buy/sell 分组）→ 前端【波动】列（four-dimension-column-plan.md Phase 2）
> 主题：新增【ATR 真实波动均值回归】信号指标，补足四维（共振/趋势/量价/周期）缺失的
> **波动幅度维度**
> 用户判断（2026-08-17）：趋势/动量/量价/环境四维信号已具备，但缺核心指标 **ATR 真实波动均值回归**，
> 该信息可能潜藏在共振/量价信号中未被发掘。
> 关联：现有 ATR 仅用于回测退出结构（`backend/core/backtest/execution.py::TradeSimulator._atr_of`，
> 止损/止盈价 = entry ∓ 倍数×ATR(14)，缺 high/low 回退固定 %）；信号维度（engine.py/volume_price.py）
> 无波动幅度因子。

## 1. 现状确认（为什么缺 ATR 维度）

| 维度 | 生产函数 | 因子构成 | 含波动幅度？ |
|---|---|---|---|
| 共振 resonance | `engine.py analyze_rank_resonance` | 排名路径（relativeMomentum/acceleration/persistence）+ Jump 事件 + reversal penalty | ❌ 排名/路径类 |
| 趋势 rankTrend | `engine.py analyze_momentum_signals + calculate_macd` | 多周期动量（rank 百分位变化）+ MACD + 零线交叉 | ❌ rank 变化，非价格波幅 |
| 量价 volumePrice | `volume_price.py compute_volume_price_score` | 涨跌方向 + volumeRatio（量比）+ zljzb/zlje（资金）象限 | ❌ 量/资金/涨跌 |
| 周期 lifecycle | `engine.py _lifecycle_tier` | 环境门（点火/扩散/拥挤/反转/冷却） | ❌ 环境标签 |
| synergy | `volume_price.py::_synergy_tier` | 上述投票合并 | ❌ |

结论：**四维信号全部基于排名/涨跌/量/资金，无"价格相对波动幅度的偏离"维度**。ATR 信息
（真实波动幅度）仅在回测退出结构中使用，未进入信号/观察层——用户判断成立。

## 2. 信号定义

**核心思想**：价格偏离其波动通道（均值 ± k×ATR）过远时，预期向均值回归——
超买（close ≫ 均值）→ 回归卖信号；超卖（close ≪ 均值）→ 回归买信号。
与现有"追强"信号（共振 Jump/趋势动量追涨）**互补**：ATR 信号捕捉超买超卖回摆机会。

### 2.1 数据输入（个股跨帧序列）

- 需要：个股连续帧的 `(high, low, close)` 序列（快照级 bar）。
- 字段回退顺序（复用回测引擎 `execution.py` 口径）：
  - high：`high` → `highPrice` → `dayHigh`
  - low：`low` → `lowPrice` → `dayLow`
  - close：`close` → `closePrice` → `lastPrice` → `lastTradePrice` → `price`
- 任一帧缺 high/low/close（全字段 None）→ **该帧不累积**，并计数 `missingBars`（fail-visible）。
- **断档处理（审计修订）**：TR 公式含 `|high_i − close_{i−1}|`——若相邻已累积帧的时间跨度
  超过 1 个 slot（跨 tradingDate、或该股缺席中间帧），跨时间连接会产生人为膨胀 TR →
  ATR 虚高 → deviation 系统性压缩。规则：**帧间隔 > 1 slot（或跨 tradingDate）即重置该股序列**
  （只保留当前帧重新起算），并计数 `gapResets`（fail-visible）。
- replay 新增 `_stock_bars_by_code: dict[code, list[(high, low, close)]]`（跨帧累积，
  截断 `atrMaxHistoryBars` 防内存增长）。
- **bar 口径（审计修订）**：直接以逐帧快照 high/low/close 作 bar（与回测引擎
  `atr_history_by_code` 同口径）。注意：单帧快照内 high≈low≈close（瞬时价），
  TR 可能系统性偏小（TR≈0）——该口径下 ATR 反映的是**跨帧（slot 间）波动**而非盘中波幅；
  如需要"日级/盘中真实波幅"，用 `atrAggregateByDay`/`atrBucketBySlot`（按 tradingDate/slot
  分桶：桶内 max high / min low / last close）切换，默认不启用（保持与回测同口径）。

### 2.2 算法

```
TR(i) = max(high_i − low_i, |high_i − close_{i−1}|, |low_i − close_{i−1}|)
ATR(N) = TR 的**简单均值**（审计修订：明确与现有 `_atr_of` 一致——`sum(TR[-N:])/N`，
        样本 < N+1 帧返回 None；不用 Wilder 平滑，避免与回测退出结构口径漂移）
ref(M) = close 的 M 周期简单均值，M 默认 20
deviation = (close − ref) / ATR        # ATR 归一化偏离度（无单位、跨个股可比）
```

> **样本门槛（审计修订）**：ATR 需 ≥ `atrPeriod+1` 帧；ref(MA) 需 ≥ `atrRefPeriod` 帧。
> 两者取**交集**——不足 `max(atrPeriod+1, atrRefPeriod)` 帧 → `status=insufficient`（unknown），
> 避免"ATR 可用而 MA 不可用"的未定义行为。

### 2.3 信号判定

| 条件 | direction | 语义 | 强度 |
|---|---|---|---|
| deviation ≥ +k（k 默认 2.0） | **sell** | 超买，回归预期 | `score = 50 + min(50, |deviation|×15)`（0-100） |
| deviation ≤ −k | **buy** | 超卖，回归预期 | 同上（对称） |
| 其余 | hold | 通道内 | score 随 |deviation| 线性映射 |

- **score 语义（审计修订）**：score 仅表偏离强度（|deviation|），**不表方向强弱、不表可交易性**
  （buy/sell 对称）。A 股无做空 + 涨停封板不可卖：sell 信号仅提示"超买、回归风险"，不构成
  可交易动作；buy 信号须警惕"趋势破裂接飞刀"（见 §6）。
- **fail-visible**：样本 < `max(atrPeriod+1, atrRefPeriod)` 帧、或 ATR=0/None、或 ref=0/None
  → `status=insufficient`、direction=hold、score=0、`signalTier=unknown`（**不归零不伪装**）。
- 快照频率口径：默认**逐帧快照 bar（跨 slot 波动）**；如需日级 ATR 可加
  `atrAggregateByDay`/`atrBucketBySlot` 开关（按 tradingDate/slot 分桶）——文档注明口径差异。

### 2.4 输出契约（对齐现有维度）

```python
{
  "status": "ok" | "insufficient",
  "direction": "buy" | "sell" | "hold",
  "score": float,            # 0-100，对齐量价/共振分
  "deviation": float | None, # ATR 归一化偏离度
  "atr": float | None,       # 当前 ATR 值（诊断用）
  "ref": float | None,       # 当前参考均值（诊断用）
  "missingBars": int,        # 序列中缺 high/low 的帧数（fail-visible）
  "reasons": list[str],      # 如 ["超卖：deviation=-2.6，回归预期"]
  "signalTier": "S|A|B|C|D|E|unknown",  # 档位（见 2.5）
}
```

### 2.5 档位规则（对齐 S/A/B/C/D/E 离散口径）

| 条件 | 档位 | reasons 示例 |
|---|---|---|
| deviation ≤ −k 且 |deviation| ≥ 3.0（绝对偏离，审计修订） | S | 深度超卖，强回归预期 |
| deviation ≤ −k | A | 超卖，回归预期 |
| deviation ≥ +k 且 |deviation| ≥ 3.0 | S（反向标注 sell） | 深度超买 |
| deviation ≥ +k | A（sell） | 超买，回归预期 |
| 通道内且 |deviation| ≥ 0.5×k | C | 回归途中 |
| 通道内且 |deviation| < 0.5×k | B | 均值附近（中性） |
| 样本不足/ATR/ref 缺失 | unknown | 数据不足，不归零 |

> **S 档阈值修订说明（审计）**：原 `atrDeepK=2.5` 语义为 2.5×k=5.0，逐帧快照 bar 下极罕见
> （且 score 在 |dev|=3.33 已封顶 100 与档位错位）——改为**绝对偏离 ≥3.0**，与 score 封顶
> 区间一致。`atrDeepK` 参数保留为相对倍数但默认按绝对偏离 3.0 校准（实现时二选一，默认绝对）。

> 注：档位语义与现有维度不同（ATR 是**逆向/回归**信号，A 档 = 超买超卖机会而非追强确认）；
> 展示时需标注"回归"标签，避免与共振/趋势的 A 档语义混淆（参照 lifecycle 环境门先例）。

## 3. 配置参数（RankTrendConfig 扩展，默认值=行业标准，golden 不漂移）

| 参数 | 默认 | 说明 |
|---|---|---|
| `atrPeriod` | 14 | ATR 周期（简单均值，复用 _atr_of 默认） |
| `atrRefPeriod` | 20 | close 参考均值周期 |
| `atrChannelK` | 2.0 | 通道倍数（偏离阈值） |
| `atrDeepDeviation` | 3.0 | S 档绝对偏离阈值（审计修订，替代 2.5×k 相对式） |
| `atrMaxHistoryBars` | 60 | 历史 bar 截断窗口（防内存） |
| `atrGapResetBars` | 2 | 断档重置阈值（帧间隔 ≥ N 个 slot 即重置序列；跨 tradingDate 恒重置） |
| `atrAggregateByDay` | False | 是否按日聚合（False=逐帧快照 bar，与回测同口径） |
| `atrBucketBySlot` | False | 是否按 slot 分桶聚合（桶内 max high/min low/last close） |

## 4. 接入点与实现路径

1. **新模块** `backend/analysis/ranktrend/atr_mean_reversion.py`（纯函数，可单测）：
   - `true_ranges(bars)` → TR 序列
   - `atr_of(bars, period)` → ATR（从 `execution.py` 抽公共纯函数，回测与信号共用，**行为不漂移**）
   - `analyze_atr_mean_reversion(bars, config)` → 2.4 契约
2. **engine.py replay**：新增 `_stock_bars_by_code` 累积（框架同回测引擎 `atr_history_by_code`），
   每帧对在榜个股计算 ATR 信号，挂载 `technical.atrMeanReversion` / `observation.atrMeanReversion`。
3. **不进 synergy 投票（初始）**：ATR 为逆向/回归信号，与追强投票方向天然相反，
   直接并入会污染现有 synergy 语义——**初始独立观察维度**，验证区分度后再决定是否纳入
   合并权重（届时需 golden 合同变更流程）。
4. **测试**：
   - 单元：已知序列 TR/ATR golden case（含跳空/极限值）；缺 high/low → missingBars 计数 +
     insufficient；样本 < `max(N+1, atrRefPeriod)` → unknown（fail-visible）；
   - **断档/跳帧 case（审计修订）**：帧间隔 > `atrGapResetBars` slot 或跨 tradingDate →
     序列重置 + gapResets 计数，TR 不被跨时间连接膨胀（构造"剔除中间帧"序列断言 ATR 不变小）；
   - **单帧快照 bar 口径 case（审计修订）**：high≈low≈close 序列 → TR≈0、ATR 极小 →
     deviation 应显式处理（denom 极小 → 信号 suppressed/unknown 而非 NaN/无穷）；
   - 信号层：tier 统计（h1/h8 saEx、passHard、单调性，同阶段 3 口径）
   - 样本外：chronological train/validation 复核（同 §8.5 流程）

## 5. 验证计划与验收

1. **区分度（按 direction 分组，审计修订）**：本池为共振 Jump/追强强势股，close 长期 > MA20，
   ATR 信号将**几乎恒为超买 sell**；而 A 股无做空、涨停封板不可卖，sell 不可交易；超卖 buy
   只出现在趋势破裂暴跌（接飞刀）。因此：
   - **buy 与 sell 分开统计**（`tier_forward_returns` 按 signal.direction 过滤），分别看
     h1/h8 saEx、passHard、单调性——**禁止 buy/sell 混合单调统计**（会把"超买后次日回调"
     误判为回归兑现）；
   - 显式统计 buy/sell 样本占比与可交易性（sell 占比过高说明信号与池子不匹配，需重设计）；
2. **与现有维度正交性**：ATR 信号与共振/趋势档位的交叉分布——若 ATR 的超卖 buy 与
   共振 S/A（追强）高度重叠，说明信息冗余（需去重设计）；若互补（ATR 超卖时共振多为
   D/低档），则增量价值明确；**趋势 regime 假信号检查**（审计修订）：单边下跌/上涨趋势中
   deviation 持续超阈值的"假回归"占比；
3. **样本外**：train/validation 段区分度稳定性（同 §8.5 流程）；
4. **采纳门槛**：区分度（buy/sell 分别） + 样本外稳定 + 正交性验证通过后，才评估纳入
   synergy 投票（golden 变更流程，不写回默认值原则不变）。

## 6. 风险与边界

- **high/low 数据缺失**：部分历史快照缺 high/low（回测已见回退固定 %）——ATR 信号按
  missingBars 计数，样本不足 → unknown，不伪造；
- **断档 TR 膨胀（审计修订）**：缺帧/缺席导致的跨时间连接会使 TR 人为膨胀 → ATR 虚高 →
  deviation 系统性压缩——由 `atrGapResetBars` 序列重置兜底（§2.1）；
- **单帧快照 bar TR≈0（审计修订）**：逐帧瞬时 high≈low≈close → TR 系统性偏小、ATR 极小、
  deviation 分母趋零——信号 suppressed/unknown（不产生 NaN/无穷），或启用
  `atrBucketBySlot` 桶内真实波幅；
- **快照频率与日 ATR 口径**：逐帧 bar 的 TR 反映**跨 slot 波动**，与日线 ATR 数值不同
  （默认逐帧，`atrAggregateByDay`/`atrBucketBySlot` 可切换，文档注明）；
- **与追强信号方向冲突**：ATR 卖追强买回落——独立观察期避免误导，展示需"回归"标注；
- **ATR 对极端波动敏感**：跳空/涨跌停帧 TR 极大，ATR 突变——可用截断（cap TR 于
  3× 历史 ATR）或 rely on 简单均值自然衰减，默认不截断（文档注明取舍）。

## 7. 结论

- ATR 均值回归是四维信号外的**独立波动维度**，数据（high/low/close 多字段回退）与算法
  （`_atr_of` 可复用）均具备，实现成本低；
- 推荐形态：**通道偏离均值回归**（deviation = (close−ref)/ATR，±k 阈值），初始**独立观察、
  不进 synergy 投票**；
- 下一步：用户确认设计后进入实现（TDD：纯函数 + golden case → replay 挂载 → tier 区分度
  验证 → 样本外复核）。

## 8. 区分度验证结果（2026-08-17，阻断性结论）

**背景**：后端实现完成（§1-§7）后按 §5 验证计划执行区分度验证（全量 769 帧 replay，
buy/sell 分组 h1/h8，正交性，样本外）。验证过程发现并修正 1 个设计缺陷：
**跨 tradingDate 恒重置（v2 §2.1）与 half_hour 数据（每天 10-11 帧 < 20 帧门槛）不兼容
→ 0 信号**。用户决策修正：**跨日不恒重置**（仅帧缺席 ≥ `atrGapResetBars` 重置；隔日跳空
计入 TR 为真实日线 ATR 语义）。修正后信号可用。

**全窗口结果（156647 信号）**：

| 指标 | h1 | h8 |
|---|---|---|
| direction 分布 | hold 99.8% / sell 270 / buy 37 | 同左 |
| tier 分布 | unknown 91.9% / B 10991 / C 1430 / S 195 / A 112 | 同左 |
| **all saEx** | 0.0104（pass=False） | 0.0875（pass=False） |
| **buy saEx** | ≈0.0（S 21/A 16） | ≈0.0 |
| **sell saEx** | ≈0.0（S 170/A 96） | ≈0.0 |

**样本外**：train 段（04-15~07-07）ATR 全部 unknown（**该段无 high/low 数据**）；
validation 段（07-09~08-14）h8 all saEx=0.0684、buy/sell 仍 ≈0。

**正交性**：atr 非 unknown 档位（B/C/S/A）与共振/趋势档位无显著重叠（top 组合
`(B, D)`/`(B, C)` 为主，A/S 极少）——信息正交成立，但样本极少。

**结论（阻断性）**：
1. **buy/sell 回归区分度不存在**：超买/超卖方向信号 h1/h8 saEx≈0、passHard=False——
   设计 v2 §5.1 核心验收（回归兑现）**不成立**；
2. **h8 all saEx 0.0875 为 B/C 档（通道内中性分类）贡献**，非 ATR 均值回归信号增量，
   不构成采纳理由；
3. **数据缺口**：仅 28% 股票有 high/low（且集中在 07-09 后）→ train 段不可验证、unknown
   占比 91.9%——样本外证据不完整；
4. **最终判定**：ATR 均值回归信号**未通过区分度验证 → 不启用前端【波动】列**
   （four-dimension-column-plan.md Phase 2 维持不启用），不写回默认值；
   如需推进：先补齐 high/low 数据采集（全量覆盖），再考虑调整偏离阈值（k=2.0 在当前
   波动水平下 buy/sell 触发率仅 0.2%，或改为波动率收缩形态）后重验。

### 8.1 收盘准 ATR 口径重验（2026-08-17，用户决策）

**背景**：用户质疑"ATR 研究是否一定需要日线 high/low"。分析确认：ATR 核心是波动度量，
不依赖日线 high/low。**实现自适应口径**：`bar_of` 改为 close 必填（close→closePrice→
lastPrice→lastTradePrice→price，100% 数据可用）、high/low 可选（缺失为 None 时
`true_ranges` 降级为 TR'=|Δclose| 收盘准 ATR）——平滑降级而非丢弃（fail-visible）。
测试新增 3 用例（close-only bar/TR 降级/close-only analyze），156 相关测试全绿。

**重验结果（全量 156647 信号；括号为 high/low 旧口径对比）**：

| 指标 | 收盘口径（新） | high/low 口径（旧） |
|---|---|---|
| direction | buy 14802 / sell 15976（**19.7%**） | buy 37 / sell 270（0.2%，100 倍提升） |
| tier | unknown 59.9% / S 22961 / A 7817 | unknown 91.9% / S 195 / A 112 |
| h1 all saEx | 0.0385（pass=False） | 0.0104 |
| h8 all saEx | 0.0224（pass=False） | 0.0875 |
| **h1/h8 buy saEx** | ≈0（S 10489/A 3892） | ≈0（样本 100 倍） |
| **h1/h8 sell saEx** | ≈0 | ≈0 |
| 样本外 train | h1 0.0426（**train 可验证**） | 全 unknown |
| 样本外 validation | h1 0.0338 / h8 0.0721 | h8 0.0684 |

**重验结论**：
1. **样本提升 100 倍后 buy/sell 仍无区分度**（h1/h8 saEx≈0、passHard=False）——
   **排除"数据不足假象"，确认 ATR 均值回归方向信号本身无增量**；
2. **数据缺口问题缓解**：收盘价全量 → train 段可验证（h1 all 0.0426）、unknown 91.9%→59.9%；
3. **合并档位微弱区分度**：h1 all 0.0385、validation h8 0.0721，但 < 0.05 验收线、
   passHard=False，且 buy/sell 核心信号无贡献；
4. **最终判定维持**：**前端【波动】列不启用**（核心 buy/sell 无区分度是信号问题，非数据问题）；
   后续可选：调整偏离阈值 k（触发率 19.7% 已可调）或波动率收缩形态，再评估是否值得推进。

### 8.2 k 阈值扫描 + 波动率收缩形态评估（2026-08-17，收敛结论）

**k 扫描**（atrChannelK 1.0/1.5/2.0/2.5/3.0，全量 769 帧，收盘口径）：

| k | 触发率 | h1 buy/sell saEx | h8 buy/sell saEx | h1 all saEx |
|---|---|---|---|---|
| 1.0 | 26.1% | ≈0 / ≈0 | ≈0 / ≈0 | 0.0332 |
| 1.5 | 22.5% | ≈0 / ≈0 | ≈0 / ≈0 | 0.0362 |
| 2.0 | 19.6% | ≈0 / ≈0 | ≈0 / ≈0 | 0.0385 |
| 2.5 | 17.0% | ≈0 / ≈0 | ≈0 / ≈0 | 0.0439 |
| 3.0 | 14.7% | None（A 档为空边界） | None | None |

**k 扫描结论**：触发率随 k 单调变化（14.7%~26.1%），但 **buy/sell 回归兑现始终 saEx≈0**——
偏离阈值调整**无法**让 ATR 方向信号产生区分度；合并档位 all h1 随 k 提高微升（0.033→0.044）
仍 < 0.05 验收线且为 B/C 档贡献（非 buy/sell 核心信号）。**k 调整无效**。

**波动率收缩形态评估**：ATR 自身均值回归（`vol_ratio = ATR/mean(ATR[-M:])` 过高 → 收缩预期）
不预测收益方向（无 buy/sell），只预测波动状态——与现有追强四维无方向性冲突，但也**不提供
方向增量**，对 tier 收益区分度贡献存疑，不建议作为 ATR 信号的替代形态。

**最终收敛结论**：
1. ATR 均值回归**方向信号（buy/sell）在该数据/池子下无收益兑现**——k 调参穷尽（1.0-3.0）、
   口径穷尽（真实 TR/收盘 Δclose）均无区分度，属结构性结论；
2. **前端【波动】列不启用**（长期），`observation.atrMeanReversion` 保留为诊断/观察字段
   （fail-visible，unknown 不伪装）；
3. 日线 high/low 采集修复（A1+A3）仍值得做（真实波幅对其它研究/回测退出有用），但
   **不再是 ATR 信号的前置**；
4. ATR 信号研究归档：如需未来重启，方向应为"波动率状态因子"（与共振/趋势组合的非方向
   特征）而非方向回归信号。
