# crossSection 追强 × ATR 波动校准：过热/超卖回归观察信号设计（2026-08-23，v2 修正版）

> 状态：**研究方案定稿（brainstorming，未实现）**。v1 方向为"percentile 回归（逆向）"，2026-08-23
> 发现与现有 `backend/analysis/ranktrend/cross_section.py` **重复**：该模块已用
> `relativeToMarket = percentile − 市场 median percentile`（即 v1 的 `pct_dev`）并按 A/B/C/D 定档，
> **且已进 synergy 第 5 维投票**（`tierSynergyCrossSectionVote=1.0`，追强方向，2026-08-17 用户决策，实证 +10%/+237%）。
> v1 若做逆向（percentile 回归）等于反向使用一个已实证有效的因子 → 大概率无增量甚至抵消。
> → **v2 修正**：不建独立 percentile 回归维度，改为**复用现有 crossSection（追强，进 synergy 不动它）
> + ATR 波动做"过热/超卖回归校准"**，产出第五观察维【波动】（不进 synergy）。
> 验证通过前前端【波动】列维持不启用（同 ATR 先例，fail-visible）。
> 关联：`ranktrend-atr-signal-design.md`（旧 ATR 失效 §8）、`ranktrend-four-dimension-column-plan.md`（【波动】列 Phase 2）、
> `cross_section.py`（percentile 追强，已实现）、`engine.py`。

## 1. 背景与问题

旧 ATR 均值回归（`observation.atrMeanReversion`）失效根因：**信息空间错位**——rankTrend 引擎输入是
横截面相对排名（`rank/percentile`，由 `avgRankNum` 派生），价格涨跌只是投影结果（标签），不是特征；
旧 ATR 用 `(close−ref)/ATR`（个股绝对价格通道偏离）当特征，等于在结果/标签上做信号 → buy/sell saEx≈0（§8.2）。

**v2 关键洞察**：percentile−median 这个量**已有**引擎实现（crossSection，追强、进 synergy）并验证有效；
因此"回归"维度应**叠加在现有 crossSection 上**（给强势股加"过热回归风险"、给弱势股加"超卖回升观察"），
而非另建逆向维度。

## 2. 决策记录（brainstorming 一问一答，用户确认）

1. **角色**：第五观察维【波动】**融合信号**（不进 synergy——方向与四维追强相反，同 lifecycle/ATR 观察先例）。
2. **percentile 口径**：不新算 percentile 回归，**复用现有 `crossSection`**（`relativeToMarket=percentile−market median`，A/B/C/D 追强，已进 synergy 第 5 维——**不动它**）。
3. **ATR 校准机制**：离散加权分档（percentile/crossSection 天然高频抖动，连续线性加权放大噪声）。
4. **ATR 波动指标**：`pct_vol = ATR/close`（价格百分比波动，跨股可比）。
5. **ATR 数据口径**：**收盘准 ATR**（`TR'=|Δclose|`，close-only，100% 数据；规避 high/low 28% 缺口）。
6. **加权形态**：**二维查表定档**（crossSection 档 × ATR 波动档 → 过热/超卖 S/A/B/C，方向信号）。
7. **字段承载**：**替换 `observation.atrMeanReversion`**（【波动】列继续消费同字段，语义改为融合校准）。
8. **判定表**（用户确认）：见 §3.3。

## 3. 信号定义

### 3.1 crossSection 档（维度 A，复用，不入本信号计算只作输入）

```
crossSection.signalTier：A/B/C/D（percentile − market median 相对强弱，追强，已进 synergy 第 5 维）
本信号只读该档位作为"追强/追弱"输入，不修改、不进 synergy 额外投票。
```

### 3.2 ATR 波动档（维度 B，收盘准 ATR）

```
pct_vol = ATR_close_only / close        # TR'=|Δclose|，atrRefPeriod 窗口
波动档（相对当帧全体股票 pct_vol 统计分位）：
  < P33  → 低波（缩量）     P33-P67 → 中波     > P67 → 高波（放量）
```

### 3.3 二维查表定档（方向信号，用户确认）

| crossSection 档 \ ATR 波动档 | 低波（缩量） | 中波 | 高波（放量） |
|---|---|---|---|
| **A/B（强，追强）** | A（温和强势） | B | **B/C（过热回归风险，sell 警示）** |
| **C/D（弱）** | **A/B（超卖回升观察，buy 机会）** | C | C（弱+放量，回避） |

- **过热回归**：强（A/B）+ 中/高波 → 放量过热、回归风险（sell/警示）。
- **超卖回升**：弱（C/D）+ 低波 → 缩量企稳、回升观察（buy/机会）。
- 其余 hold；数据不足/波动不可用 → `unknown`（fail-visible 不归零不伪装）。
- 档位 S/A/B/C/unknown（观察维，不设 D/E）；**不进 synergy**。

## 4. 输出契约（替换 `observation.atrMeanReversion`，对齐现有维度）

```python
{
  "status": "ok" | "insufficient",
  "direction": "buy" | "sell" | "hold",     # buy=超卖回升观察 / sell=过热回归警示
  "score": float,                            # 档位映射 0-100（回测扫描标定）
  "crossTier": str | None,                   # crossSection 档（A/B/C/D，输入）
  "volTier": str | None,                     # 波动档（low/mid/high）
  "pctVol": float | None,                    # 收盘准 ATR 波动率 (ATR/close)
  "atr": float | None,                       # 收盘准 ATR（诊断）
  "signalTier": "S|A|B|C|unknown",
  "reasons": list[str],                      # 如 ["横截面强势 + 放量，过热回归风险"]
  "dataQuality": {...},                      # crossSection/atr 覆盖率，fail-visible
}
```

> 前端 `getAtrSignal/getAtrDirection/getAtrTier/getAtrDeviation` 读 `observation.atrMeanReversion`；
> **语义变更**：原"价格通道偏离"改为"crossSection×波动 过热/超卖"；前端显示方向箭头 + 档位徽章 + 数值 + "回归"标签。

## 5. 参数（默认，回测可扫描）

| 参数 | 默认 | 说明 |
|---|---|---|
| 波动分位切分 | P33 / P67 | 波动档 低/中/高 切分 |
| `atrRefPeriod` | 20 | close 参考窗口（收盘准 ATR） |
| `atrMaxHistoryBars` | 60 | 历史 bar 截断（防内存） |

## 6. 接入点与实现路径（TDD）

1. **新纯函数模块** `backend/analysis/ranktrend/cross_section_vol_overheat.py`：
   - `pct_vol(bars)` → 收盘准 ATR 波动率（复用 `atr_of` close-only 降级）
   - `analyze_cross_section_overheat(cross_tier, vol_tier, config)` → §4 契约（二维查表，无 I/O 纯函数）
2. **engine.py replay**：挂载/替换 `observation.atrMeanReversion`（输入现有 `crossSection.signalTier` + 本帧 ATR 波动档）。
3. **不进 synergy 投票**（方向与四维追强相反，同 lifecycle/ATR 观察角色）。
4. **测试**（黄金 case）：`(A,high)→B(过热)`、`(D,low)→A(超卖)`、`(A,low)→A(温和)`、`(C,mid)→C`、数据不足→unknown（fail-visible）、高频抖动下档位稳定。

## 7. 验证计划与采纳门槛（同 ATR §5 口径，buy/sell 分组）

1. **区分度（buy/sell 分开）**：`tier_forward_returns` 按 direction 过滤，分别看 h1/h8 saEx、passHard、单调性——**禁止 buy/sell 混合**。
2. **与 baseline 对比（关键）**：融合信号 vs **单独 crossSection**（现有追强，已进 synergy）、**单独 ATR 波动**——证明**融合 > 单用**（否则无增量）。
3. **正交性**：与 crossSection/共振/趋势档位交叉分布；**趋势 regime 假回归检查**（单边上/下跌中"过热/超卖"的假信号占比）。
4. **样本外**：train/validation 段稳定（同 §8.5 流程）。
5. **采纳门槛**：融合（buy/sell 分别）saEx **显著高于**单独 crossSection/单独 ATR baseline 且样本外稳定 + 正交性成立 → 才升级前端【波动】列（届时走 golden 变更流程，不写回默认值原则不变；未通过则维持不启用）。

## 8. 风险与边界

- **与 crossSection 追强方向互补而非抵消**：synergy 保持 crossSection 追强第 5 维；本信号只做观察（不进 synergy），避免对冲。
- **高波降档误伤真趋势（假阴）**：强（A/B）+ 高波可能正是趋势强确认，标"过热"会误警——区分度验证查假阴占比。
- **收盘准 ATR 口径**：用 Δclose 反映跨 slot 波动，非真实 high/low 波幅——数字与日线 ATR 不同，注明。
- **percentile/crossSection 高频抖动**：离散分档规避单帧跳变放大；仍需验证档位稳定性。
- **替换字段语义变更**：`observation.atrMeanReversion` 语义从"价格通道回归"→"crossSection×波动 过热/超卖"；前端显示值改读 `crossTier`/`volTier`（fail-visible 容错）。

## 9. 结论与归档

- v2 用**现有 crossSection（追强，进 synergy）+ ATR 波动（过热/超卖校准）**做第五观察维【波动】融合信号，
  复用已实证的 percentile 信息、避免与 crossSection 对冲；验证通过前前端列不启用。
- 核心修正：从"percentile 回归（逆向，与 crossSection 重复）"转为"crossSection 追强 × ATR 过热/超卖校准"（复盘：brainstorming 探索上下文时漏查 `cross_section.py`，经用户提示修正）。
- 下一步（验证通过后走 golden 变更流程）；验证未通过则归档，方向为"波动率状态因子"（非方向回归）。

## 10. 区分度验证结果（2026-08-23，任务2，阻断性结论）

**背景**：按 §7 执行区分度验证（引擎 replay + 现有 `tier_monotonicity.tier_forward_returns` 分位桶基线，
**buy/sell 分组**，未自造收益指标；window 2026-07-01~2026-08-14，dataset=dragonboard_live，269 帧/41515 信号，
ATR 可用子集 15314，约 36.9%）。比较 `fusion`（crossSection×ATR 过热/超卖校准）、`crossSection`（追强）、`atr`（旧价格通道回归）。

**同域（ATR 可用子集）结果——verdict**：

| direction/horizon | fusion saEx | crossSection saEx | atr saEx | fusion 更强？ |
|---|---|---|---|---|
| buy h1 | **-0.0126** | +0.0138 | +0.0539(passHard, n=2887→44 子样本) | ❌ 均不优 |
| buy h8 | **-0.033** | +0.0121 | +0.0495 | ❌ 均不优 |
| sell h1 | **-0.0187** | +0.0175 | -0.0123 | ❌ 均不优 |
| sell h8 | **-0.0099** | +0.016 | -0.099 | ❌ 不优于 cs；✅ 优于 atr（但 atr 本身差） |

**结论（阻断性）**：
1. 融合信号的 buy/sell **方向区分度未显著高于两个单基线**（saEx 全为负、均未达 0.05 硬阈值）；
   `crossSection` 追强是同域内更稳的正增量来源——**融合无增量价值**。
2. **池构成效应 caveat**：全池表面 fusion buy h1 saEx=+0.022（看似正），因其选中样本（C/D 弱势+缩量）
   本身处于中低分位、全池基线偏低所致；同域内转负(-0.0126)。**全池正增量为假象**。
3. **采纳门槛未满足** → **前端【波动】列维持不启用**，`observation.atrMeanReversion`（本方案替换后语义）
   不升级、不写回默认值；`cross_section_vol_overheat.py` 保留为诊断/观察纯函数（验证脚本
   `quant-board/scripts/ranktrend_overheat_validation.py`，报告 `data/reports/ranktrend-overheat-validation.json`）。
4. ATR 子样本统计力弱（buy 仅 44，因 ATR 需 20 帧连续 + 热榜轮动 + 仅 36.9% 覆盖）——如需再验，先补齐
   high/low 或改用收盘准 ATR 全量覆盖后重验；但当前证据已提示融合方向信号结构性无增量。
5. **Task 3（engine 挂载）不做**——验证门控未通过。

> v2 spec 定稿 + 任务1 纯函数/单测 + 任务2 验证 harness 均已提交；结论为研究性负结果，如实归档（fail-visible）。
