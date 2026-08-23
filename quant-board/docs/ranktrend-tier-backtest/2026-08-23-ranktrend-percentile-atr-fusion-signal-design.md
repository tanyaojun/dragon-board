# Percentile 回归 × ATR 波动校准：融合方向信号设计（2026-08-23，brainstorming 定稿）

> 状态：**研究方案定稿（brainstorming，未实现）**——在 `ranktrend-atr-signal-design.md`（ATR 均值回归
> 信号，buy/sell 区分度未通过 → 不启用）基础上**重构信号输入空间**：弃用价格维度（close/ATR 通道），
> 改用**横截面 percentile 回归**（用户判断：排名百分位才是 rankTrend 精髓，价格涨跌只是结果）。
> 本方案为**融合方向信号**，**验证未通过前前端【波动】列维持不启用**（同 ATR 先例，fail-visible）。
> 关联：`ranktrend-atr-signal-design.md`（旧 ATR 设计+§8 失效验证）、前端四维列计划
> `ranktrend-four-dimension-column-plan.md`（【波动】列 Phase 2）、`engine.py`（percentile 维度）。

## 1. 背景与问题

旧 ATR 均值回归信号（`observation.atrMeanReversion`）失效根因：**信息空间错位**。
- rankTrend 引擎输入是**横截面相对排名**：`rank / percentile`（由 `avgRankNum` 平均关注度排名派生），
  单位统一、跨股可比；价格涨跌只是**投影结果（标签）**，不是特征。
- 旧 ATR 用 `deviation=(close−ref)/ATR`（个股绝对价格通道偏离）当**特征**，等于在结果/标签上做信号，
  与引擎无关，故 buy/sell saEx≈0（§8.2：tune 参数、口径穷尽仍无区分度，属结构性结论）。

**用户判断**：centile 回归（横截面）与传统 ATR 价格涨跌超买/超卖应**融合**，而非二选一——这是全新课题，
不可简单下定论。"排名百分位变化本身就是高波动（单帧排名涨跌几十个身位很正常）"→ 融合用**离散分档**而非连续线性加权。

## 2. 决策记录（brainstorming 一问一答，用户确认）

1. **角色**：融合**方向信号**——percentile 回归给方向+强度，ATR 只做波动/置信校准。
2. **percentile 回归口径**：**排名中位数校准**（`pct_dev = current_pct − 当帧市场排名中位 percentile`），
   **弃用 z-score 自适应**（percentile 有界 [0,100]，历史 std z-score 统计不适配，且把趋势股误判过热）。
3. **ATR 校准机制**：离散加权分档（替代连续线性——percentile 天然高频抖动，连续加权会放大噪声）。
4. **ATR 波动指标**：`pct_vol = ATR/close`（价格百分比波动，跨股可比；ATR 绝对值不可比）。
5. **ATR 数据口径**：**收盘准 ATR**（`TR'=|Δclose|`，close-only，100% 数据；规避 high/low 28% 缺口）。
6. **加权形态**：**二维查表定档**（percentile 强度档 × ATR 波动档 → 最终 S/A/B/C，方向不变）。
7. **字段承载**：**替换 `observation.atrMeanReversion`**（【波动】列继续消费同字段，语义改为 percentile 回归+波动校准）。

## 3. 信号定义

### 3.1 percentile 回归（方向 + 强度档，横截面排名中位数校准）

```
pct_dev = current_percentile − frame_market_median_percentile(当帧)
方向：pct_dev ≥ +k → 横截面超买（sell，回归预期）
      pct_dev ≤ −k → 横截面超卖（buy，回归预期）
      其余           → hold
强度档：|pct_dev| ∈ [k, 2k)  → B（弱偏离）
                [2k, 3k) → A（中偏离）
                ≥ 3k     → S（强偏离）
```
- `current_percentile`：该股当前帧 percentile（权威历史帧复用，同 `_load_frames_for_analysis` 口径）。
- `frame_market_median_percentile`：当帧全体覆盖股 percentile 的中位数（engine 已有）。天然去市场 beta。

### 3.2 ATR 波动档（收盘准 ATR）

```
pct_vol = ATR_close_only / close        # TR'=|Δclose|，atrRefPeriod 窗口
波动档（相对当帧全体股票 pct_vol 统计分位）：
  < P33  → 低波动（回归确定）
  P33-P67 → 中波动
  > P67  → 高波动（趋势延续风险）
```

### 3.3 二维查表定档（方向不变，波动调档）

| percentile 强度档 \ 波动档 | 低波动 | 中波动 | 高波动 |
|---|---|---|---|
| 强偏离（S 基线） | **S** | A | B |
| 中偏离（A 基线） | A | B | C |
| 弱偏离（B 基线） | B | C | C |

- `|pct_dev| < k` → hold；数据不足 / 波动不可用 → `unknown`（fail-visible，不归零不伪装）。
- 超卖 buy 侧对称；档位 S/A/B/C/unknown（观察维，不设 D/E）。

## 4. 输出契约（替换 `observation.atrMeanReversion`，对齐现有维度）

```python
{
  "status": "ok" | "insufficient",   # 数据不足/异常
  "direction": "buy" | "sell" | "hold",
  "score": float,          # 档位映射 0-100（对齐量价/共振分）；映射公式回测扫描标定，方向不变
  "pctDev": float | None,  # percentile 相对市场排名中位偏离
  "baseTier": str | None,  # percentile 强度档（S/A/B）
  "pctVol": float | None,  # 收盘准 ATR 波动率 (ATR/close)
  "volTier": str | None,   # 波动档（low/mid/high）
  "atr": float | None,     # 收盘准 ATR（诊断）
  "signalTier": "S|A|B|C|unknown",
  "reasons": list[str],    # 如 ["横截面上超买：pctDev=25.3，低波动→回归确认"]
  "dataQuality": {...},    # percentile/atr 覆盖率，fail-visible
}
```

> 前端 `getAtrSignal/getAtrDirection/getAtrTier/getAtrDeviation` 读 `observation.atrMeanReversion`；
> **语义变更点**：原 `deviation`（价格偏离）改为 `pctDev`（rank 中位偏离），前端【波动】列显示值需
> 改读 `pctDev` / `volTier`（视觉仍为方向箭头 + 档位徽章 + 数值 + "回归"标签）。

## 5. 参数（默认，回测可扫描调优）

| 参数 | 默认 | 说明 |
|---|---|---|
| `pctDevThresholdK`（k） | 15.0 | pct_dev 阈值（percentile 百分点；过热/过冷触发线，替代旧 ATR 的 atrChannelK=2.0） |
| 波动分位切分 | P33 / P67 | 波动档 低/中/高 切分 |
| `atrRefPeriod` | 20 | close 参考均值范围（收盘准 ATR 窗口） |
| `atrMaxHistoryBars` | 60 | 历史 bar 截断（防内存） |
| `atrAggregateByDay` / `atrBucketBySlot` | False | default 逐帧快照 bar（与回测同口径） |

## 6. 接入点与实现路径（TDD）

1. **新纯函数模块** `backend/analysis/ranktrend/percentile_mean_reversion.py`：
   - `percentile_deviation(pct, market_median)` → pct_dev
   - `atr_close_only_vol(bars)` → pct_vol（复用 `atr_of` close-only 降级）
   - `analyze_percentile_mean_reversion(pct, market_median, bars, config)` → §4 契约
2. **engine.py replay**：挂载/替换 `observation.atrMeanReversion`（改为 percentile 回归+波动校准二维查表）。
3. **不进 synergy 投票**（方向与四维追强相反，同 lifecycle 观察角色）。
4. **测试**（黄金 case）：已知 pct_dev/波动档 → 查表定档；数据不足 → unknown fail-visible；
   percentile 单帧剧烈跳变 → 离散档稳定（不因线性加权放大）；超买/超卖对称性。

## 7. 验证计划与采纳门槛（同 ATR §5 口径，buy/sell 分组）

1. **区分度（buy/sell 分开）**：`tier_forward_returns` 按 direction 过滤，分别看 h1/h8 saEx、passHard、
   单调性——**禁止 buy/sell 混合统计**（会把"超买后回调"误判为回归兑现）。
2. **与单独 baseline 对比（关键）**：融合方向信号 vs **单独 percentile 回归**、**单独 ATR 波动** 的区分度，
   证明 **融合 > 单用**（否则融合无增量价值，正交但无用）。
3. **正交性**：与共振/趋势档位交叉分布；**趋势 regime 假信号检查**（单边上/下跌 trend 中持续超买的"假回归"占比）。
4. **样本外**：train/validation 段区分度稳定性（同 §8.5 流程）。
5. **采纳门槛**：融合方向（buy/sell 分别）saEx **显著高于** 单用 baseline 且样本外稳定 + 正交性成立
   → 才升级前端【波动】列（届时走 golden 变更流程，不写回默认值原则不变；未通过则维持不启用）。

## 8. 风险与边界

- **与四维追强方向相反**：独立观察维，不进 synergy（同 lifecycle 先例），展示"回归"标签避免误导。
- **高波动降档误伤真趋势（假阴）**：percentile 过热 + 高波动可能正是趋势强确认，降档会漏——区分度验证
  需专门查"假阴"占比（趋势 regime）。
- **收盘准 ATR 口径**：用 Δclose 反映**跨 slot 波动**，非真实 high/low 波幅——数字与日线 ATR 不同，文档注明。
- **percentile 高频抖动**：离散分档（而非连续加权）正是为此设计，避免单帧跳变放大；但仍需验证档位稳定性。
- **替换字段语义变更**：`observation.atrMeanReversion` 语义从"价格通道回归"变为"percentile 回归+波动校准"，
  前端【波动】列显示值改读 `pctDev`/`volTier`；旧字段消费方需同步适配（fail-visible 容错）。

## 9. 结论与归档

- 本方案是 rankTrend 的**第五观察维【波动】**融合方向信号：percentile 回归（横截面排名中位数校准）给方向+强度档，
  ATR 收盘准波动给波动档，二维查表定档；**验证通过前前端【波动】列不启用**（同 ATR 先例）。
- 核心创新：把"超买/超卖回归"从**价格空间**迁移到**横截面 percentile 空间**（用户判断的 rankTrend 精髓），
  并用**离散分档**规避 percentile 高频抖动。
- 下一步（验证通过后走 golden 变更流程）；验证未通过则归档，方向为"波动率状态因子"（非方向回归）。
