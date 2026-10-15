# jev 趋势维独立判读 预登记（试点第三维；参照共振 pilot 同构）— 2026-10-15

> 性质：**新题集试点草案**（判据冻结件候选 + 语料同源合同 + runner + 测试，已落地待冻结）。
> 状态：**判据待用户逐字确认；未确认前零开火**（dry-run 已在真实库通过，零 jev 调用）。
> 用户裁决（2026-10-14）：「参照共振步骤改趋势」。
> 边界不变：jev 与规则引擎=**并列观察者**（2026-10-08 裁决）——不回写引擎、不进 synergy 投票、
> 不进候选池、不进交易路径；本试点只产出「jev 独立读数 vs 引擎读数」的对照台账。

## §〇 为什么趋势能第三个拆（原料自足性，开工前已核实）

- **引擎趋势维吃的不是 TDX 日线**，而是与共振维**完全相同的那条「跨日最近 ≤50 次进榜出现」
  分位序列**：`analyze_technical(percentiles, config, fallback)` 的 MA5/MA10、MACD(13/21/8)、
  MA 快慢线(10/20)、momentum 全算在这条序列上（`trend/technical.py`）；
- 序列不足（< `get_technical_min_computable_samples` = macdSlow+1 = **22 次出现**）时，
  **引擎自身降级**到 `fallback_signals`，主证据换成判读帧行字段
  （displayChange / stockChange / volumeRatio / zlje / zljzb）——两种模式的原料都在
  snapshot_frames / snapshot_stock_rows 里，**零外部依赖、零第二实现**；
- **对照锚干净**：`observation.rankTrend.direction` 取 `compose_decision` 的
  **base.signal**（技术面五分量加权和的信号），cycle/risk 只改写 `final`——所以锚就是纯技术面
  读数，与本题集语义严格对齐（分歧不来自锚污染）。

## §一 口径铁律（本题集第一铁律，写进 instructions）

引擎趋势的 buy/sell/hold 是「该股**注意力在序列上的技术面方向**」（10-14 实测：引擎 buy 125 /
sell 83 / hold 36），**不是「这只票能不能买」**。可买入性是 VOTE/LC 线的事。判据若混进
「值不值得买」语义，对照即刻失真——故 instructions 里用加粗句钉死。

## §二 语料合同（同源，五块；runner 零第二实现）

| 块 | 内容 | 来源 | 同源保证 |
|---|---|---|---|
| 1 注意力出现序列 | 该股最近 ≤50 次进榜出现的 attention 分位 + 相邻出现差 | `attention_rank_lookup`+`percentile_rank`（engine/primitives.py） | **同一函数**；窗口语义同引擎：最近 ≤50 次出现的前缀（跨日，末项=判读帧） |
| 2 派生读数 | MA5/MA10 及快慢关系、MACD DIF/DEA/柱值/金叉死叉、MA 快慢线多空状态与交叉、momentum 短/中/长/加速度/shock | `moving_average`/`calculate_macd`/`calculate_ma_cross`/`momentum_profile`（trend/technical.py） | **同一函数**现算（可复现算术衍生，非判定产物）；不可算分量如实 None，不伪造 0 |
| 3 判读帧行字段 | displayChange（=末项−前项分位差，与 runtime 同式）/ stockChange / volumeRatio / zlje / zljzb | snapshot_stock_rows（判读帧行） | 引擎 `fallback_signals` 的同一输入（同键同源） |
| 4 入榜状态 | 是否序列首个出现 + 当前分位 | 现算 | 与引擎 `entry.isNew` 同口径 |
| 5 质量自标 | 缺出现/缺字段如实列出 | snapshot_stock_rows | — |

帧窗口 = 最近 280 个 half_hour 帧（`ANALYZE_FULL_MARKET_LOAD_LIMIT` 同值）。
取数原语**直接复用共振 pilot**（`jev_resonance_recheck.rolling_frames / appearance_series`）——
三维的引擎输入是同一条序列，取数只有一份。

**黑名单（叙事零出现，测试机验）**：signalTier / synergy / finalSignal / compScore / compRank /
lifecycle / cooling / ignition / voteDirection / temperature / crowding / 量比结论 /
resonance_direction / trendDirection——判定产物一律不喂，只喂原始事实与可复现算术衍生。

## §三 判据（冻结件候选；逐字=代码文本，改一字=改门）

题集两问（一次调用，`hotlist_jev_trend_recheck_pilot`）：

1. `trend_direction`（choice：buy/sell/hold/insufficient + confidence）
   - **两步走**：第一步数五个分量的共识（①MA5 vs MA10；②MACD 交叉与柱值符号；③MA 快慢线
     10/20 多空状态与交叉；④momentum short/mid 符号；⑤判读帧行字段方向）；
     第二步定方向：**同向分量 ≥2 且反向分量 ≤1 → 该方向**；反向同理；互相抵消或同向不足
     2 个 → hold；数据不可用 → insufficient。
   - 分量共识门与引擎 `compose_decision` 的 `decisionMinAgreement=2` /
     `decisionMaxOpposition=1` **同构**（逻辑结构，不是权重复现）；
   - 序列深度 <22 次出现时，MA/MACD/MA交叉多数不可算（原料块如实标注），**⑤帧行字段是主证据**；
2. `trend_strength`（score 0-100，10 档锚点）
   - 正贡献=同向分量数量与幅度；负贡献=反向分量牵制、序列反复翻转（shock 大）、临近交叉；
   - 参照尺与引擎 label 同口径：0-26 非常弱 / 27-49 较弱 / 50-66 中等 / 67-84 强 / 85-100 非常强；
   - **强度不得与方向矛盾**（方向 buy 但同向分量不足 → 强度 ≤30）。

全文见 `backend/analysis/hotlist/jev_trend_ammo.py` 的 `QUESTIONS_TREND_RECHECK`
（测试 `test_criteria_frozen_shape` 钉死形状与口径铁律句）。

## §四 预检 riskFlag（与引擎两条模式同口径）

- `bars ≥ 22` → **series 模式**（level=ok）：技术面可算，主证据=序列+派生读数；
- `2 ≤ bars < 22` → **fallback 模式**（level=partial）：引擎同款降级，主证据=帧行字段；
- `bars < 2` → `data_insufficient`：连「末项−前项」都不可算，两条模式都无证据 → 不调用落留痕。

## §五 对照锚与台账（纯读，零 jev 调用；`--ledger`）

- 方向：jev `trendDirection` ↔ 引擎 `observation.rankTrend.direction`（同帧同股）逐股直比
  → agree/diverge + 按日 + **按模式（series/fallback）分列**；
- 强度：jev `trendScore` 与引擎 `score` 按同一标尺分桶比对；
- 缺对照锚/任一侧 insufficient 单列，**不计入一致率**（fail-visible，不用分母掩盖）。

## §六 落地形态与版本戳

| 件 | 位置 |
|---|---|
| 弹药纯函数层（题目常量/预检/派生读数/叙事组装，零 IO） | `backend/analysis/hotlist/jev_trend_ammo.py` |
| runner（取数复用共振原语 + 编排 + 落库 + 台账） | `backend/operations/jev_trend_recheck.py` |
| 集合 | `hotlist_jev_trend_recheck_pilot`，`_id={date}:{slot}:{code}:THD` |
| 版本戳 | `QUESTION_SET_VERSION_TREND_RECHECK="v1"`、`TREND_AMMO_VERSION="2026-10-15a"`（独立戳） |
| 测试 | `tests/hotlist/test_jev_trend_recheck.py`（16 例全 fake，零 IO 零 jev 调用） |
| 前端展示（就地改造，不新增列） | `backend/relay_page/index.html`【趋势】列：有判读→jev 读数（多头/震荡/空头 + 强度 + 模式），无判读→回落引擎档位徽标；KPI「TRD 趋势复核」卡、`jev趋势` 筛选、可排序、行展开第四张 lg-card；读口 `backend/services/jev/jev_quotes_review.py` 增 `jev.trd` / `jev.trdAgree` / `summary.trend` / `trendSlots` / `trendSlotNote`（帧锁定，与 LC 同规） |

runner 纪律与双题集/共振一致：默认 dry-run 零调用；`--fire` 且 token 才真实调用
（AGENTS §1.2-7）；done-skip **按题集代际**（改门重跑不挡）；**无抽样帽**；
data_insufficient 留痕不调用；`answers` 原样包 + confidence 升顶层 + responseRaw ok/degraded
一律存完整 envelope + 引擎对照锚快照。

## §七 验证门与预算（开火前冻结）

- 门1 叙事完整性：五块全呈现，缺口 fail-visible 如实标注，黑名单零出现（有机验测试）；
- 门2 **同源复算**（已通过，零 token）：用本题集同款取数+派生+`compose_decision` 复算
  `base.signal`，与库里 `observation.rankTrend.direction` 逐股比对 →
  **242/242 全匹配、0 mismatch、0 缺锚**（2026-10-14 15:00 全池）；
- 门3 人工盘感抽验：≥5 例（含全部 diverge 例）交用户对照；
- 预算（10-14 实测人口）：候选 **242 例**（series 模式 187 / fallback 模式 55）+ 预检不足 2；
  单例 ≈4.1k tok（叙事含 50 行序列）→ **≈99 万 tok/日 ≈ $0.09/日**；
  单次运行熔断缺省 150k（全量回填显式放宽）。

## §八 已知分歧源（跑前登记，防过度解读）

1. **口径边界差**：引擎 direction 由五分量加权和 + `combined ≥ ±0.12` 阈值 + 共识门机械判定，
   jev 按判据语义判——边界案例（combined 接近阈值）的系统性分歧属校准差，台账单列；
2. **模式差**：fallback 模式（<22 次出现）引擎用帧行字段加权，jev 同样以帧行字段为主证据，
   但分量解释空间更大——故台账**按模式分列**，不混桶；
3. **序列末项口径**：live API 链有「复制尾+去尾」历史修复，快照分析链同帧跳过——
   本题集取数与快照分析链同口径（已由门2 的 242/242 复算实证）；
4. **强度标尺**：jev score 与引擎 score 不同标定过程，分桶比对之外的绝对差不做解读。

## §九 回退

ammo / runner / 集合 / 测试 / 前端列改造全部独立新增（读口为纯增量字段），`git revert` 单笔即回退；
不触碰引擎、快照集合、双题集既有集合与文档。

## §十 待用户确认（确认后才开火）

1. 判据全文（§三）逐字确认或修改；
2. 判读帧默认 15:00 是否接受（趋势需 ≥22 次出现，午盘帧多为 fallback 模式）；
3. 台账按模式分列（§五）是否够用；
4. 开火范围：先单日（10-14）试点，还是直接挂每日盘后链（schedule 同款步）。
