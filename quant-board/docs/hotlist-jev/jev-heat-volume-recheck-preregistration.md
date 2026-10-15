# jev 热度维 + 量价维独立判读 预登记（试点第四/五维；**V2 = 逻辑推理题集**）

> **版本链**：V1（2026-10-15，复现题集）→ **V2（2026-10-15 当天升版，逻辑推理题集）**。
> V1 判据原文与设计理由**原样保留在 §十一**，不删不改写（用户要求「已落盘的方案文档不能丢弃」）；
> §〇-§十 为 V2 生效口径。改动即改门，已按流程登记待确认。

> 性质：**新题集试点草案**（判据冻结件候选 + 语料同源合同 + runner + 测试，已落地待冻结）。
> 状态：**V2 判据已按用户裁决落码（判据/测试/读口/前端全部升版），待用户逐字确认后开火**；
> dry-run 已在真实库通过（零 jev 调用）；**V1 从未开火**（零调用、零落档），故不存在需要覆盖的旧读数。
> 边界不变：jev 与规则引擎=**并列观察者**（2026-10-08 裁决）——不回写引擎、不进 synergy 投票、
> 不进候选池、不进交易路径；本试点只产出「jev 独立读数 vs 引擎读数」的对照台账。

## §〇 V2 定位：为什么把复现题改成逻辑推理题（用户裁决 2026-10-15）

引擎的这两个锚是**纯确定性算术**，不是加权共识：
- **热度**：`observation.crossSection` = percentile（末项分位）+ percentileDelta（末项−前项）
  + relativeToMarket（末项−市场 median percentile）三个数过阈值 → A/B/C/D/unknown
  （`trend/cross_section.py` 的 `compute_cross_section` + `_tier_from`）；
- **量价**：`observation.volumePrice` = change × volumeRatio × zljzb 三项交叉 →
  score(0-100) + quadrant + signalTier（`ranking/volume_price.py` 的
  `compute_volume_price_score` + `_volume_price_tier`）。

所以本题集的科学定位是**协议层健康度阴性对照**：
- 复现类问题（`heat_tier` / `volume_tier` / `volume_quadrant` / `volume_score`）给
  **显式门槛表**、要求 jev 逐条复现——复现率接近 100% 证明协议层可靠；
  复现失败则分歧本身就是「LLM 执行确定性规则的能力」测量；
- 语义类问题（`heat_direction` / `volume_direction`）是引擎**没有**的语义层
  （引擎只给涨跌方向 up/down/neutral，不给「是否支持做多」），**无引擎锚**、只落档等 T+1 检验。

## §一 同源验证（零 token，开工前已通过）

用本题集同款取数 + 衍生 + 引擎同一函数复算，与库里存档逐股比对（2026-10-14 15:00）：

| 维度 | 结果 |
|---|---|
| 热度（percentile / percentileDelta / signalTier） | **244/244 全匹配** |
| 量价（score / quadrant / signalTier，amount_ratio=None） | **244/244 全匹配** |

**关键前置发现（引擎侧缺口，已记账不动引擎）**：引擎生产链
`observation.amountRatio` **恒 None**——2026-08-18 G3 加的「成交额量比」这条判据
（`compute_amount_ratio`）在快照分析链从未生效。本题集**严格同源不用该字段**，
叙事里显式注明「not provided」（fail-visible，不静默缺料）。

## §二 语料合同（同源，零第二实现）

| 块 | 内容 | 来源 |
|---|---|---|
| 1 注意力出现序列 | 该股最近 ≤50 次进榜出现的 attention 分位 + 相邻出现差 | `attention_rank_lookup`+`percentile_rank`（engine/primitives.py），窗口语义同引擎（跨日，末项=判读帧）；取数**复用共振 pilot 原语** |
| 2 横截面衍生 | percentile / percentileDelta / relativeToMarket / 持续高位窗口均值 | `heat_derived()` 按 `compute_cross_section` 的同一输入衍生（**不含档位判定**，档位由引擎函数算或 jev 复现） |
| 3 市场基准 | market median percentile / 横截面样本数 / 池大小 | `frame_market_median` / `frame_market_median_percentile`（engine/runtime.py） |
| 4 帧行原始事实 | change / volumeRatio / zlje / zljzb | snapshot_stock_rows 判读帧行（`compute_volume_price_score` 的同一输入） |
| 5 引擎同款衍生 | 涨跌停标记、涨幅八档方向分 | `_is_limit_up` / `_is_limit_down` / `_direction_bucket`（ranking/volume_price.py，可复现算术衍生） |
| 6 质量自标 | 缺出现/缺字段如实列出 | snapshot_stock_rows |

帧窗口 = 最近 280 个 half_hour 帧（`ANALYZE_FULL_MARKET_LOAD_LIMIT` 同值）。

**黑名单（叙事零出现，机验+人工双查）**：signalTier / synergy / finalSignal / compScore /
compRank / lifecycle / cooling / ignition / voteDirection / temperature / crowding /
量比结论 / resonance_direction / trendDirection / 引擎 quadrant 与 score 结论 /
引擎热度 tier 结论——判定产物一律不喂，只喂原始事实与可复现算术衍生。

## §三 判据（冻结件候选；逐字=代码文本，改一字=改门）

**热度维两问**（集合 `hotlist_jev_heat_recheck_pilot`，`_id={date}:{slot}:{code}:HEA`）：

1. `heat_tier`（choice A/B/C/D/unknown）——**复现题**，显式门槛表按序短路：
   delta 有效时 ①A: pct≥85 ∧ delta≥+5；②B: pct≥50 ∧ delta≥+15；③D: pct≤15 ∧
   delta≤−5；④C: pct≤50 ∧ delta≤−15；⑤B: pct≥70（绝对档）；⑥C: pct≤30；⑦C: 其余。
   delta 缺失（首帧/单点）时：pct≥85→B / pct≥70→B / pct≤15→C / 其余→C。
   pct 缺失或非法 → unknown。**①-④必须成对才升级/降级**。
2. `heat_direction`（choice buy/sell/hold/insufficient）——**语义题无锚**，两步走：
   ①relativeToMarket 符号；②percentileDelta 符号与幅度。同向为正→buy、同向为负→sell、
   一正一负或两者幅度都在 ±2 内→hold。口径铁律：buy/sell 只表示相对关注度升降，
   **绝不表示可买入性**。

**量价维四问**（集合 `hotlist_jev_volume_recheck_pilot`，`_id={date}:{slot}:{code}:VPQ`）：

1. `volume_tier`（choice A/B/C/D/E/unknown）——**复现题**，显式门槛表按序短路：
   第0步 unknown（涨幅/量比缺失或量比≤0）；第1步 **E**（主力净占比 > +10 对倒出货，
   或 涨幅>0 且量比>2.5 过度放量）；第2步 C（涨停 ∧ 量比≤0.95 缩量涨停封板）；
   第3步 放量上涨分支（涨幅>0 ∧ 量比≥1.05）：主力净占比>0（或缺失而净额>0）→A，否则→B；
   第4步 C（涨幅>0 ∧ 量比≤0.95，或 0.95<量比<1.05 中态）；第5步 D（涨幅<0）。
   **涨幅绝对大小不影响档位**（涨幅档位分只进 score）——这是最容易写错的一条，
   判据里用加粗钉死。
2. `volume_quadrant`（choice rise_volume/rise_shrink/normal/fall_volume/fall_shrink）
   ——**复现题**：按涨跌符号 × 量比区间（≥1.05 放量 / ≤0.95 缩量 / 之间中态）判。
3. `volume_direction`（choice buy/sell/hold/insufficient）——**语义题无锚**：
   「量价配合是否支持做多」。封板不可交易性须单独说明（涨停买不进、跌停卖不出）。
4. `volume_score`（score 0-100，10 档锚点）——**复现题**：涨幅八档方向分 + 放量幅度 +
   主力净占比正负，参照尺 0-26 非常弱 / 27-49 较弱 / 50-66 中等 / 67-84 强 / 85-100 非常强；
   **强度不得与方向矛盾**。

## §四 预检 riskFlag（与引擎不可算线同口径）

- 热度：percentile 缺失 → **data_insufficient**（引擎同口径 unknown）；delta 缺失 →
  **partial**（首帧/单点，绝对档可判、delta 确认路径不可达）；
- 量价：change 或 volumeRatio 缺失、或 volumeRatio ≤ 0 → **data_insufficient**
  （引擎同款早退，score=None/signalTier=unknown）；
- 两维**独立预检**（热度不足不牵连量价，反之亦然）；预检不足不调用、落留痕。

## §五 对照锚与台账（纯读，零 jev 调用；`--ledger`）

| 读数 | 锚 | 指标 |
|---|---|---|
| heatTier | 引擎 crossSection.signalTier | 复现一致率 |
| volumeTier | 引擎 volumePrice.signalTier | 复现一致率 |
| volumeQuadrant | 引擎 volumePrice.quadrant | 复现一致率 |
| volumeScore | 引擎 volumePrice.score | 强度分带一致率 |
| heatDirection / volumeDirection | **无锚** | 只统计分布，**不进一致率** |

缺对照锚/任一侧 insufficient 单列，不计入分母（fail-visible）。

## §六 落地形态与版本戳

| 件 | 位置 |
|---|---|
| 弹药纯函数层（两题集 + 衍生 + 预检 + 叙事，零 IO） | `backend/analysis/hotlist/jev_heat_volume_ammo.py` |
| runner（取数复用共振原语 + 编排 + 落两集合 + 台账） | `backend/operations/jev_heat_volume_recheck.py` |
| 测试（20 例全 fake，零 IO 零调用） | `tests/hotlist/test_jev_heat_volume_recheck.py` |
| 读口 | `backend/services/jev/jev_quotes_review.py`（`jev.hea`/`jev.vpq`/`heaAgree`/`vpqAgree`、`summary.heat`/`summary.volumePrice`、`heatSlots`/`volumeSlots`/`heatSlotNote`/`volumeSlotNote`，帧锁定同 LC 规） |
| 前端（就地改造，不新增列） | `backend/relay_page/index.html`【热度】【量价】两列：有判读→jev 读数（档位徽标 + 语义方向/象限 chip），无判读→回落引擎档位徽标；KPI「HEA 热度复核」「VPQ 量价复核」两卡；`jev热度档`/`jev量价档` 筛选；可排序；行展开第五/六张 lg-card |
| 版本戳 | `QUESTION_SET_VERSION_HEAT_RECHECK="v1"`、`QUESTION_SET_VERSION_VOLUME_RECHECK="v1"`、`HEAT_AMMO_VERSION="2026-10-15a"`、`VOLUME_AMMO_VERSION="2026-10-15a"`（独立戳） |

runner 纪律与前四维一致：默认 dry-run 零调用；`--fire` 且 token 才真实调用
（AGENTS §1.2-7）；done-skip **按题集代际**，同 _id 整档覆盖；**无抽样帽**；
data_insufficient 留痕不调用；ok/degraded 一律存完整 envelope + 引擎对照锚快照；
`--dim heat|volume|both` 支持单维跑。

## §七 验证门与预算（开火前冻结）

- 门1 叙事完整性：各块全呈现，缺口 fail-visible，黑名单零出现（有机验测试）；
- 门2 **同源复算**（已通过，零 token）：热度 244/244、量价 244/244（§一）；
- 门3 人工盘感抽验：≥5 例（含全部复现分歧例）交用户对照；
- 预算（10-14 实测人口）：候选 **244 例**（热度预检不足 0、量价预检不足 5）；
  叙事体量远小于共振/趋势（无 50 行跨日序列），单例热度 ≈0.6k、量价 ≈0.7k tok
  → 两维合计 **≈32 万 tok ≈ $0.03/日**；单次运行熔断缺省 200k（两维合计）。

## §八 已知分歧源（跑前登记，防过度解读）

1. **弱信号区的阈值差**：热度 A 档需「高位 ∧ 上升」成对，10-14 全市场弱 → 引擎 A 档
   **0 只**（C 157 / B 75 / D 12）。若 jevv 判出 A，即 100% 分歧——这是市场环境 +
   阈值形状的共同结果，不是判错；
2. **量价档位与涨幅解耦**：引擎档位不看涨幅大小（只看符号+量比+资金），
   而人直觉「涨 3% 才叫放量上涨」——判据已用加粗句钉死，仍是最可能的混淆点；
3. **封板帧**：一字板/缩量涨停在引擎是 C 档（封板不可交易），jevv 可能按「涨了」判 A/B；
4. **语义题无锚**：heatDirection/volumeDirection 不进一致率，只用 T+1 胜率检验；
5. **引擎 amountRatio 缺口**（§一）：本题集不用该字段，故「成交额放量资金」这条证据
   两边都没有——若日后引擎修好，需重新评估是否入叙事（=改门，走预登记）。

## §九 回退

ammo / runner / 两集合 / 测试 / 读口增量字段 / 前端两列改造全部独立新增，
`git revert` 单笔即回退；不触碰引擎、快照集合、前四维既有集合与文档。

## §十 待用户确认（确认后才开火）

1. 判据全文（§三）逐字确认或修改——尤其量价档位表「涨幅不影响档位」与热度档位表；
2. 判读帧默认 15:00 是否接受；
3. 语义题（direction）无锚、只落档等 T+1，是否接受这个设计；
4. 开火范围：先单日（10-14）试点，还是直接挂每日盘后链（schedule 同款步）。


---

## §十一 V1 留档（2026-10-15 原始复现题集；用户要求不得丢弃）

> V1 判据原文如下，**逐字保留作历史留档**。V2 将其中 4 道**纯算术复现题降级为基线**
> （tier/quadrant 原样保留，`volume_score` 整题下线），并新增 4 道**逻辑推理题**作主体。
> V1 从未开火：零 jev 调用、零落档，故升版不产生任何需要覆盖或迁移的旧读数。

### V1 科学定位（原文）

引擎的这两个锚是**纯确定性算术**，不是加权共识：
- **热度**：percentile（末项分位）+ percentileDelta（末项−前项）
  + relativeToMarket（末项−市场 median percentile）三个数过阈值 → A/B/C/D/unknown
  （`trend/cross_section.py` 的 `compute_cross_section` + `_tier_from`）；
- **量价**：`observation.volumePrice` = change × volumeRatio × zljzb 三项交叉 →
  score(0-100) + quadrant + signalTier（`ranking/volume_price.py` 的
  `compute_volume_price_score` + `_volume_price_tier`）。

所以 V1 题集的科学定位是**协议层健康度阴性对照**：复现类问题给**显式门槛表**、要求 jev
逐条复现——复现率接近 100% 证明协议层可靠；复现失败则分歧本身就是「LLM 执行确定性规则的
能力」测量。语义类问题（direction）是引擎**没有**的语义层，**无引擎锚**、只落档等 T+1 检验。

### V1 题集（6 题；复现 4 + 语义 2）

| 维度 | 题 | 类型 | V2 处置 |
|---|---|---|---|
| 热度 | `heat_tier` | 复现（A/B/C/D/unknown 显式门槛表，7 条按序短路 + delta 缺失降级路径） | **保留为基线**（判据原文不动） |
| 热度 | `heat_direction` | 语义（buy/sell/hold/insufficient，两步走） | 保留为语义问 |
| 量价 | `volume_tier` | 复现（A/B/C/D/E/unknown 门槛表，0-5 步按序短路） | **保留为基线**（判据原文不动） |
| 量价 | `volume_quadrant` | 复现（五象限，边界闭区间） | **保留为基线**（判据原文不动） |
| 量价 | `volume_direction` | 语义（是否支持做多，无锚） | 保留为语义问 |
| 量价 | `volume_score` | 复现（0-100 强度，10 档锚点） | **整题下线**（最纯的算术查表，jev 无优势；强度语义由 `volume_cause` 覆盖） |

### V1 已知分歧源（跑前登记，V2 仍部分适用）

1. **弱信号区的阈值差**：热度 A 档需「高位 ∧ 上升」成对，10-14 全市场弱 → 引擎 A 档 **0 只**
   （C 157 / B 75 / D 12）。若 jev 判出 A，即 100% 分歧——市场环境 + 阈值形状的共同结果；
2. **量价档位与涨幅解耦**：引擎档位不看涨幅大小（只看符号+量比+资金），人直觉「涨 3% 才叫
   放量上涨」——V2 已在 `volume_cause` 判据里用加粗句钉死「涨幅的绝对大小不影响归因」；
3. **封板帧**：一字板/缩量涨停在引擎是 C 档（封板不可交易），jevv 可能按「涨了」判 A/B；
4. **语义题无锚**：direction 不进一致率，只用 T+1 胜率检验；
5. **引擎 amountRatio 缺口**：本题集不用该字段，故「成交额放量资金」这条证据两边都没有。

### V1 版本戳（留档）

`QUESTION_SET_VERSION_HEAT_RECHECK="v1"`、`QUESTION_SET_VERSION_VOLUME_RECHECK="v1"`、
`HEAT_AMMO_VERSION="2026-10-15a"`、`VOLUME_AMMO_VERSION="2026-10-15a"`。
V2 已换代际：题集 v2 / ammo 2026-10-15b（done-skip 按代际，旧代际文档不挡新代际）。

---

## §十二 V2 升版记录（2026-10-15）

**触发**：用户原话「我在想，热度（其实应该是相对强度）和量价是纯算术题，交给规则引擎计算
可能更合适，jev 模型的强项应该是逻辑推理，能不能把这两个题集改成逻辑判断题呢？」
裁决：「可以，但已经落盘的热度+量价题集方案文档不能丢弃，直接升版逻辑推理题V2」。

**V2 题集（9 题 = 4 逻辑主问 + 2 语义问 + 3 复现基线）**：

| 维度 | 题 | 类型 | 锚 |
|---|---|---|---|
| 热度 | `heat_attribution` | **逻辑主问**：个体强 vs 全池普涨（分母效应归因），三步走 | 复算锚 `attributionAnchor` |
| 热度 | `heat_evolution` | **逻辑主问**：序列形态（刚发酵/高位平稳/退潮/低位平稳/反复） | 复算锚 `evolutionAnchor` |
| 热度 | `heat_direction` | 语义问（相对关注度升降，无锚） | 无 |
| 热度 | `heat_tier` | 复现基线（V1 原文） | 引擎 `crossSection.signalTier` |
| 量价 | `volume_cause` | **逻辑主问**：量价配合主导因素（疑似出货/资金流出/四象限/中态） | 复算锚 `causeAnchor` |
| 量价 | `volume_tradability` | **逻辑主问**：可交易性（封板/资金异常/正常） | 复算锚 `tradabilityAnchor` |
| 量价 | `volume_direction` | 语义问（是否支持做多，无锚） | 无 |
| 量价 | `volume_tier` | 复现基线（V1 原文） | 引擎 `volumePrice.signalTier` |
| 量价 | `volume_quadrant` | 复现基线（V1 原文） | 引擎 `volumePrice.quadrant` |

**两个硬条件（V2 设计铁律）**：
1. 逻辑题只吃**该股自身多帧序列 + 全池聚合量**（市场中位数/样本数/池大小）——项目铁律
   「单股观察层不得获得对照池其他个股数据」不破；
2. 逻辑题答案必须能从**同一输入机械复算出锚**（ammo 的 `heat_attribution_anchor` /
   `heat_evolution_anchor` / `volume_cause_anchor` / `volume_tradability_anchor` 纯函数，
   runner 现算后落档）——逻辑题不是开放题，jev 判对=推理成功、判错=推理失败。

**V2 阈值门（判据文本与锚复算共用同一组常量，杜绝两套口径）**：

| 题 | 门 |
|---|---|
| `heat_attribution` | abs(relativeToMarket) < 15 → follow_market；否则 percentile 与 50 分界定个体侧/市场侧 |
| `heat_evolution` | 末 3 次有效出现；极差 ≥25 volatile → 升幅 ≥+8 且末项 ≥60 igniting → 跌幅 ≤−8 fading → 高位极差 ≤10 sustaining / 低位极差 ≤10 dormant；<3 次 insufficient |
| `volume_cause` | 净占比 >+10 或（涨幅>0 且量比>2.5）→ over_volume_exhaustion；净占比 ≤−5 → fund_outflow；再按涨跌符号 × 量比区间四象限；平盘/中态 neutral |
| `volume_tradability` | 涨停 → limit_up_blocked；跌停 → limit_down_blocked；净占比 >+10 或（涨幅>0 且量比>2.5）→ abnormal_fund_flow；其余 tradable。**封板优先于资金异常** |

**V2 落码清单**：
- `backend/analysis/hotlist/jev_heat_volume_ammo.py`：题集换代 + 4 个锚纯函数 + 阈值常量；
  `strength_band` 随 score 题下线一并删除（不留死码）；
- `backend/operations/jev_heat_volume_recheck.py`：`build_population` 现算四锚并入 cand；
  落档 `heatAttribution/heatEvolution/volumeCause/volumeTradability` + 四个 anchor 字段；
  `build_ledger` 改 V2 指标（主问对锚 / 次问对锚 / 基线对引擎 / 语义只落分布）；
- `tests/hotlist/test_jev_heat_volume_recheck.py`：22 例（`test_criteria_frozen_shape` 钉
  V2 形状 + `test_logic_question_anchors_are_reproducible` 钉四锚机验 +
  `test_logic_question_anchors_share_thresholds_with_criteria_text` 钉阈值同源 +
  `test_ledger_missing_anchor_is_fail_visible` 钉缺锚 fail-visible）；
- `backend/services/jev/jev_quotes_review.py`：`jev.hea/jv.vpq` 改 V2 字段；`heaAgree/vpqAgree`
  = 主问对复算锚；summary.heat/volumePrice 增 attributions/evolutions/causes/tradability
  分布 + attrAgree/attrDiverge/evolAgree/evolDiverge/causeAgree/causeDiverge/
  tradAgree/tradDiverge/tierAgree/tierDiverge；
- `backend/relay_page/index.html`：【热度】列改「归因徽标 + 形态 chip」，【量价】列改
  「主因徽标 + 可交易性 chip」，**列数仍 17、colspan=17 不变**；筛选改 `jev热度归因`/
  `jev量价主因`；KPI 文案改「归因对锚 / 主因对锚」；行展开第五/六张卡改「归因复算 /
  主因复算」摘要；33 项渲染冒烟全过；
- `tests/hotlist/test_hotlist_jev_api.py`：seed 与断言同步 V2。

**V2 待跑**：同源验证已通过（热度 244/244、量价 244/244，§一，零 token）；dry-run 已通过
（池 244 → 候选 244，热度预检不足 0 / 量价预检不足 5，零调用）；**未开火，等用户逐字确认**。

**V2 验收口径不变**：复现一致率 / 归因对锚率都**不是**验收指标；验收指标是
**隔日胜率 × 盈亏比**（与共振/趋势同规）。V2 的真正价值在 T+1：引擎不算「这个高位是个体
还是普涨」「这形态还能不能延续」「封板买不买得进」，jev 判出来后由次日收益检验谁对。

---

## §十三 V2 首日跑 + 归因（2026-10-14 15:00，已开火）

**跑法**：`--day 2026-10-14 --slot 15:00 --fire --workers 4`，分三段跑（熔断 140 万 →
补跑 100 万 → 收尾 2.5 万）。**覆盖 244/244**：热度 244 ok / 0 degraded；
量价 239 ok + 5 预检不足留痕 / 0 degraded；missingAnchor 0、jevInsufficient 0。
**总消耗 2,367,049 tokens**（热度 ≈4.8k/例——叙事含 50 行跨日出现序列；量价 ≈1k/例；
单例合计 ≈5k，比预估 1.3k 高 4 倍，预算修正见 §十四）。

### 台账（`--ledger`，零 jev 调用）

| 题 | 一致 | 分歧 | 一致率 |
|---|---|---|---|
| `heatAttribution`（逻辑主问·分母效应归因） | 242 | 2 | **99.2%** |
| `heatEvolution`（逻辑主问·序列形态） | 171 | 60 | **74.0%** |
| `volumeCause`（逻辑主问·量价主因） | 239 | 0 | **100.0%** |
| `volumeTradability`（逻辑主问·可交易性） | 239 | 0 | **100.0%** |
| `heatTier`（复现基线） | 244 | 0 | 100.0% |
| `volumeTier`（复现基线） | 239 | 0 | 100.0% |
| `volumeQuadrant`（复现基线） | 239 | 0 | 100.0% |

### 归因（零成本纯读库）

1. **复现基线 100% 全对**（tier/quadrant，引擎分布 B75/C157/D12 与 D130/E31/A48/B12/C18）→
   协议层完全可靠，jev 执行确定性规则满分。**这证明 V2 逻辑题的成绩差异不是协议层噪声、
   不是解析丢字段**——同一个模型同一份 envelope，复现题全对、逻辑题有分歧。
2. **归因题仅 2 例分歧，且是同一枚硬币的两面（边界裁量）**：
   300476 rel=−14.959、600105 rel=+14.959，双双差 **0.041** 就到 ±15 门 → 锚判 follow_market，
   jev 分别判 individual_weak / individual_strong（方向相反但对称）。jev 在边界上倾向「硬拆」，
   锚按门归「个体/市场不可分」。**不是推理失败，是连续→离散的阈值裁量**（与共振 v2、趋势维
   完全同构）；门 15 只造成 0.8% 分歧，选得合理。
3. **演化题是唯一有真实分歧的题（61 例）**，混淆矩阵揭示单一机制——
   **jev 系统性权重「当前位置」，锚权重「变化率」**：
   - `igniting → 0% 一致`（9 例全分歧）：锚看升幅≥+8 判「刚发酵」，jevv 全判 sustaining(8)/
     volatile(1)——它看到的是「已经在高位」；
   - `fading → 45.7%`：分歧主要是 fading→dormant(8)/fading→volatile(8)——jevv 把「掉下来」
     读成「低位平稳」而非「退潮中」；
   - `sustaining → 78.9%`：分歧主要是 sustaining→volatile(17)——jevv 对波动的敏感度高于
     锚的极差门 10；
   - dormant 86.3% / volatile 89.3% / insufficient 100%。
   **哪个权重对，由 T+1 胜率回答，不由一致率回答。**
4. **v4「一字板」教训同款检查**：涨停封死 26 只，`volume_tradability` 题 **100% 正确**
   全部判 limit_up_blocked；但语义题 `volumeDirection` 在其中 **13 只判了 buy**。
   两个读数不矛盾（「量价配合对做多是正贡献」≠「现在买得进」），但**消费方必须同时看
   主因 + 可交易性两个读数**，不能只拿 direction——前端 tooltip/KPI 已同时展示两者。

### 读数分布（无锚，只落档备验）

- 语义题：heatDirection {hold 174, sell 55, buy 15}；volumeDirection {hold 34, buy 123, sell 81, insufficient 1}
- 逻辑主问 jev 侧：heatAttribution {individual_strong 86, individual_weak 86, follow_market 72}；
  heatEvolution {sustaining 98, volatile 58, dormant 54, fading 21, insufficient 13}；
  volumeCause {shrink_down 89, volume_expansion_up 60, volume_expansion_down 32,
  over_volume_exhaustion 31, shrink_up 11, fund_outflow 9, neutral 7}；
  volumeTradability {tradable 193, limit_up_blocked 26, abnormal_fund_flow 16, limit_down_blocked 4}
- 量价 E 档（引擎硬风险）31 只 ↔ jev 主因 over_volume_exhaustion 31 只，**完全对上**。

### 结论

**协议层阴性对照达成**：复现基线 100% 证明算术层可靠、jev 执行无噪声。
**逻辑层裁量暴露**：唯二有分歧的两处（归因边界 2 例、演化权重 61 例）都是
「连续→离散阈值由谁定」的裁量点，与共振 v2/趋势维规律完全一致——**四个判读者四个裁量点，
弱信号环境下离散化结果由门槛形状决定，不由数据决定**。V2 相对 V1 的真实增量：
把「jev 会不会查表」升级成了「jev 与算术在哪些裁量点上分道扬镳」，且这个分岔可机验、
可复现、可按题隔离归因。**验收指标仍是隔日胜率 × 盈亏比**（采集链停摆中，暂无法结算）。

---

## §十四 预算修正（2026-10-14 实测）

| 项 | 预估 | 实测 |
|---|---|---|
| 热度单例 | ≈0.6k tok | **≈4.8k tok**（叙事含 50 行跨日出现序列，体量与共振 pilot 同级） |
| 量价单例 | ≈0.7k tok | **≈1.0k tok** |
| 两维合计/日 | ≈32 万 | **≈237 万 tok/日 ≈ $0.21/日** |

修正原因：热度叙事 = 共振同款 50 行跨日序列（此前按「量价帧行体量」低估了热度）。
**后续热度+量价每日按 240 万 tok 计**；熔断缺省 200k 需显式放宽（本次 140 万 + 100 万 + 2.5 万）。

---

## §十五 Code Review 修正记录（2026-10-15；用户裁决「不跑了，code review，修复后提交」）

用户在首日结果出来后质疑「一致率怎么突然这么高，你不会把答案过拟合了吧」。
CR 结论：**不是数据泄露，但是自证（self-fulfilling）**，用户判断方向正确，本模块原定位
表述失实，已修正。同时修掉 3 个真 bug。

### CR-1 自证（定位失实，已修正表述；非代码 bug）

- **排除数据泄露**：调档 000823 原文叙事核对——热度叙事只含 50 行跨日分位序列 + 三个衍生数
  （percentile/percentileDelta/relativeToMarket）+ 市场基准（median/sampleCount/poolSize）；
  量价叙事只含 change/volumeRatio/zlje/zljzb + 涨跌停标记。**无任何答案/档位/锚值泄露**。
- **根因 = 判据文本与锚复算共用同一组阈值常量**（`HEAT_ATTRIBUTION_REL_MIN=15` 等）。
  `_HEAT_ATTRIBUTION_INSTR` 写「|relativeToMarket| < 15 → follow_market」，
  `heat_attribution_anchor()` 用同一个 `HEAT_ATTRIBUTION_REL_MIN` 算答案 → jev 照判据执行即得
  锚值，100% 一致只证明「LLM 能准确执行一段写明的规则」。
- **旁证**：仅有的 2 例归因分歧是 rel=±14.959（差 0.041 到 ±15 门）一左一右对称——
  jev 确实在执行我写进判据的那条 15 的门，只在边界保留了自己的裁量。
- **唯一例外**：`heat_evolution` 判据只给定性描述（「明显往上走且已站上高位」），
  **一个数字都没给**，而锚用显式阈值（极差≥25/升幅≥8/末项≥60/极差≤10）算 →
  其 74.0% 与 61 例分歧是真实的「语义判读 vs 算术判读」裁量差（jev 权重当前位置、
  锚权重变化率）。这是本题集唯一有判读价值的读数。
- **修正动作**（**判据文本一字未改**——与已落档 244 例 v2 数据同代，改文本须升代际并重跑，
  用户未批准）：
  - ammo docstring / 常量表注释 / 锚区注释 / 题集区注释：删去「逻辑主问测的是引擎算术没算的
    结论」「jev 判对=推理成功、判错=推理失败」等失实表述，改为 CR 定位说明；
  - runner `run_heat_volume_day` docstring、`build_ledger` docstring、CLI description；
  - 读口 `_hea_brief`/`_vpq_brief` docstring 与 4 处注释；
  - 前端【热度】【量价】列 tooltip：「jev 热度逻辑判读（V2）」→「jev 热度复核（V2·自证题集）」。
- **最终定位**：本模块 = **协议层阴性对照**（tier/quadrant 对引擎 100%，证明算术层可靠、
  jev 执行无噪声）+ **一次已证伪的设计假设留档**（「纯算术题改逻辑措辞即可测推理」不成立）。
  **读数一律不得用于任何结论**；重跑前必须先改判据文本（删显式阈值）并升题集代际。

### CR-2 多线程 stats 竞争（真 bug，已修）

`run_heat_volume_day` 的 `_work`/`_run_one` 在 `ThreadPoolExecutor(max_workers=4)` 内并发
执行，其中 `stats["data_insufficient"] += 1`、`stats["ok"/"degraded"] += 1`、`tokens += used`
都是非原子读-改-写 → workers>1 时丢计数，**首日 298/187/5 这三个数本身不可信**。
已加 `threading.Lock` 保护全部共享读写（含熔断判断 `if tokens >= fuse`）。
核查另两个新 runner：共振/趋势的 `_work` 不改 stats、stats 在 `ex.map` 返回后串行累加，
**无此问题**（热度/量价 runner 因两维共用一个 `_work` 而引入，属本模块独有）。

### CR-3 台账缺锚口径错误（真 bug，已修）

`build_ledger._tally` 原逻辑 `if anchor not in valid: missingAnchor += 1`。
但 `heat_evolution_anchor()` 在序列有效出现 <3 时返回 `"insufficient"`——
`"insufficient"` 是「锚侧也不可判」，不是「取数缺锚」，却被计进 `missingAnchor`，
把「序列太短」误报成「数据链路缺锚」（fail-visible 反向失真：掩盖真缺锚）。
已三分：jev insufficient → 不计（jevInsufficient 单列）；anchor 缺失/非法 → missingAnchor；
anchor insufficient → **新增 anchorInsufficient 单列**。10-14 实测 anchorInsufficient=0
（该日无锚侧不可判），missingAnchor=0 保持不变，历史读数不受影响。

### CR-4 死代码（已删）

`_VOLUME_SCORE_INSTR`（8 行）在 V2 删除 `volume_score` 题后已无任何引用，删除。
`strength_band` 已随 V2 一并从本模块移除（其他模块不受影响）。

### CR 后验证

- `pytest` 全仓通过（热度/量价 22 例 + 读口/API + platform）；
- 前端 JS 语法 + 渲染冒烟通过（33 项）；
- `--ledger` 纯读复跑一致（missingAnchor 0 / anchorInsufficient 0）。
