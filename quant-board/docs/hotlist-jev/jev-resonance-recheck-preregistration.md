# jev 共振维独立判读 预登记（试点：synergy 四维拆开独立判读的第一维）— 2026-10-14

> 性质：**新题集试点草案**（判据冻结件候选 + 语料同源合同 + runner + 测试，已落地待冻结）。
> 状态：**判据待用户逐字确认；未确认前零开火**（dry-run 已在真实库通过，零 jev 调用）。
> 用户裁决（2026-10-14）：「LC 能单独判读，为什么共振不能？先以共振为试点，把题目集先做出来」。
> 边界不变：jev 与规则引擎=**并列观察者**（2026-10-08 裁决）——不回写引擎、不进 synergy 投票、
> 不进候选池、不进交易路径；本试点只产出「jev 独立读数 vs 引擎读数」的对照台账。

## §〇 为什么是共振先拆

- 四维里**共振的原料最自足**：只依赖「该股注意力分位序列 + 全池基准」，不碰价格/量价/板型，
  与 LC 的「排名轨迹 + 度量」同属「单股自身行为」类证据，独立判读不借别的维度的结论；
- **趋势/热度本质是确定性算术**（MA/MACD、池内分位），jev 重判=用模型复现算术，增量信息少，
  更适合做「抓算术失效案例」而不是整维替代——留作第二/第三批评估；
- **量价**语料也自足（v4 八块里已现成），列第二批候选。

## §一 口径铁律（本题集第一铁律，写进 instructions）

引擎共振的 buy/sell/hold 是「**注意力相对全池的动能方向**」（10-14 实测 244 只里引擎给
buy 125 只、sell 83 只、hold 36 只），**不是「这只票能不能买」**。可买入性是 VOTE/LC 线的
事。判据若混进「值不值得买」语义，对照即刻失真——故 instructions 里用加粗句钉死。

## §二 语料合同（同源，五块；runner 零第二实现）

| 块 | 内容 | 来源 | 同源保证 |
|---|---|---|---|
| 1 注意力出现序列 | 该股最近 ≤50 次进榜出现的 attention 分位（0-100）+ 相邻出现差 + 跳变标记 | `attention_rank_lookup`+`percentile_rank`（engine/primitives.py）、`detect_rank_jumps`（engine/runtime.py） | **同一函数**；窗口语义同引擎：`_build_code_attention_series` + `prefix=bars[:pos+1]`，**跨日、最近 50 次出现**（不是当日 10 槽——第一版取数取错成当日槽，dry-run 立刻暴露：insufficient 95 vs 引擎 28，已修正为 30 vs 28） |
| 2 市场基准 | 判读帧前 4 帧窗口全池注意力分位变化中位数 + 池内分位中位数 + 池大小 + 有效样本 | `frame_market_median` / `frame_market_median_percentile`（engine/runtime.py） | 同一函数 |
| 3 入榜状态 | 是否序列首个出现（新入榜）+ 当前分位 | 现算 | 与引擎 `entry.isNew` 同口径 |
| 4 质量自标 | 缺字段（avgRankNum 等）如实列出 | snapshot_stock_rows | — |
| 5 引擎对照锚（**只落档不进叙事**） | 同帧 `snapshot_analysis.analysis.resonance` 的 direction/score/signalTier/label/status | 只读快照 | 台账机械可算 |

帧窗口 = 最近 280 个 half_hour 帧（`ANALYZE_FULL_MARKET_LOAD_LIMIT` 同值）。

**黑名单（叙事零出现，测试机验）**：signalTier / synergy / finalSignal / compScore / compRank /
lifecycle / cooling / ignition / voteDirection / temperature / crowding / 量比 / 主力净额 / 涨停 /
跌停——判定产物一律不喂，只喂原始事实与可复现算术衍生（v4-material 同规）。

## §三 判据（冻结件候选；逐字=代码文本，改一字=改门）

题集两问（一次调用，`hotlist_jev_resonance_recheck_pilot`）：

1. `resonance_direction`（choice：buy/sell/hold/insufficient + confidence）
   - 主锚：短窗（最后 3 次出现）分位变化 **− 市场基准中位数** 的符号与幅度；加速度同向性；
     路径持续性；反转惩罚（自峰值回撤 ≥10pt / 方向翻转频率）；跳变标记（surge/collapse，
     逆向跳变以跳变为准）；序列深度 <9 次出现时序列不作主证据并降置信；
   - `insufficient` 仅限数据不可用；证据冲突=hold。
2. `resonance_strength`（score 0-100，10 档锚点）
   - 正贡献=相对动量幅度/加速度/持续性/跳变新鲜度；负贡献=反转惩罚；
   - 参照尺与引擎 label 同口径：0-26 非常弱 / 27-49 较弱 / 50-66 中等 / 67-84 强 / 85-100 非常强。

全文见 `backend/analysis/hotlist/jev_resonance_ammo.py` 的 `QUESTIONS_RESONANCE_RECHECK`
（测试 `test_criteria_frozen_shape` 钉死形状与口径铁律句）。

## §四 预检 riskFlag（与引擎 insufficient 条件同口径，阈值读引擎 config）

- `data_insufficient`（不调用，落留痕文档）：出现次数 <9（`resonanceMidWindowBars+1`）、
  或市场基准有效样本 <20（`resonanceMinMarketSampleCount`）、或时间轴不完整、
  或**无 attention 序列**（avgRankNum 缺失，引擎同口径跳过——本题集显式留痕不静默消失，§4.0）；
- `partial`（仍判）：缺字段等次要缺口；
- `ok`：原料齐备。

## §五 对照锚与台账（纯读，零 jev 调用；`--ledger`）

- 方向：jev `resonance_direction` ↔ 引擎 `resonance.direction` 逐股直比 → agree/diverge + 按日；
- 强度：jev `resonanceScore` 与引擎 `score` 按同一标尺分桶比对；
- 缺对照锚/任一侧 insufficient 单列（`missingAnchor` / `jevInsufficient` / `engineInsufficient`），
  **不计入一致率**（fail-visible，不用分母掩盖）。

## §六 落地形态与版本戳

| 件 | 位置 |
|---|---|
| 弹药纯函数层（题目常量/预检/叙事组装，零 IO） | `backend/analysis/hotlist/jev_resonance_ammo.py` |
| runner（取数+预检+编排+落库+台账） | `backend/operations/jev_resonance_recheck.py` |
| 集合 | `hotlist_jev_resonance_recheck_pilot`，`_id={date}:{slot}:{code}:RES` |
| 版本戳 | `QUESTION_SET_VERSION_RESONANCE_RECHECK="v1"`、`RESONANCE_AMMO_VERSION="2026-10-14a"`（独立戳） |
| 测试 | `tests/hotlist/test_jev_resonance_recheck.py`（18 例全 fake，零 IO 零 jev 调用） |
| 前端展示（就地改造，不新增列） | `backend/relay_page/index.html`【共振】列：有判读→jev 读数（走强/同步/走弱 + 强度分带色），无判读→回落引擎档位徽标；KPI「RES 共振复核」卡、`jev共振` 筛选、可排序、行展开第三张 lg-card（读数摘要 + 请求/响应/原始 JSON）；读口 `backend/services/jev/jev_quotes_review.py` 增 `jev.res` / `jev.resAgree` / `summary.resonance` / `resonanceSlots` / `resonanceSlotNote`（帧锁定，与 LC 同规） |

runner 纪律与双题集一致：默认 dry-run 零调用；`--fire` 且 token 才真实调用（AGENTS §1.2-7）；
done-skip 幂等；**无抽样帽**（2026-10-14 用户裁决）；data_insufficient 留痕不调用；
`answers` 原样包 + confidence 升顶层 + responseRaw ok/degraded 一律存完整 envelope。

## §七 验证门与预算（开火前冻结）

- 门1 叙事完整性：五块全呈现，缺口 fail-visible 如实标注，黑名单零出现（有机验测试）；
- 门2 同源校验：本题集 insufficient 集合 vs 引擎 insufficient 集合的差集 ≤5% 并逐例归因
  （10-14 实测：本题集 30 / 引擎 28，差 2 例=300651、510300，均为尾盘进池、引擎 analyze
  重跑时序列更长——**待排查登记项**，不作为通过项）；
- 门3 人工盘感抽验：≥5 例（含全部 diverge 例）交用户对照；
- 预算（10-14 实测人口）：候选 214 例 × ≈1.6k tok ≈ **34 万 tok/日 ≈ $0.03/日**；
  单次运行熔断缺省 150k（全量回填显式放宽，同双题集先例）。

## §七·跑 首日执行记录（2026-10-14，用户批准开火）

- 命令：`--resonance-day 2026-10-14 --slot 15:00 --workers 4 --token-fuse 6000000 --fire`
  → **214 ok / 0 degraded / 30 data_insufficient 留痕 / 869,414 tokens**（覆盖 244/244）。
- **预算修正（预估失手）**：原估 34 万 tok（按 LC 单例 1.6k 推），实际单例 **≈4.06k**——
  叙事含 50 行跨日出现序列（LC 叙事只有当日 ≤10 行），体量 5 倍。**后续日预算按 4.1k/例计**
  （全池日 ≈ 88 万 tok ≈ $0.08/日）。
- 台账（`--ledger`，零调用）：方向 agree 104 / diverge 110 = **48.6%**；强度分带
  agree 112 / diverge 102；missingAnchor 0。jev 读数 sell 176 / buy 25 / hold 13。
- **零成本归因（纯读库重算，未烧 token、未改判据）**：最大分歧源 = jev sell × 引擎 buy
  **93 例**；这 93 例里 **65 例短窗超额为正**（均值 +5.9，即原料说「相对走强」）、jev 却判
  sell（强度均值仅 4.7）→ **jev 未跟随判据主锚①（超额符号）**，被其他锚压倒或未做减法；
  且引擎 buy 组按 score 全分桶 jev 都偏 sell（与引擎强度无关）→ 排除「引擎低分边界案例」
  单一解释。一致的组则完全贴合主锚（buy×buy 17/22 超额为正；sell×sell 66/80 超额为负）。
  **归因落点=题目/判据锚定层（§1.2-6 第②步），非协议解析层（0 degraded、confidence/
  score 分布正常）**。候选根因（待裁，未改）：a) 判据③反转惩罚在 50 根长序列上几乎必然触发
  （分位波动大、必有近期峰值），把 buy 全否；b) 模型未执行①的「减市场基准」减法；
  c) 判据②持续性在长序列上天然低分。修法=改门，须预登记+用户逐字确认后才重跑。

## §八 已知分歧源（跑前登记，防过度解读）

1. **口径边界差**：引擎 direction 由 clamped 加权和 >0.1 阈值机械判定，jev 按判据语义判——
    边界案例（|超额|接近 0）的系统性分歧属校准差，台账单列「边界带」样本；
2. **引擎侧 jump 覆盖**：引擎 direction 可被逆向 jump 事件整体改写，jev 只把跳变当证据之一；
3. **no-attention-series**：avgRankNum 缺失股引擎静默跳过、本题集留痕，两侧人口差即此处；
4. **强度标尺**：jev score 与引擎 score 不同标定过程，分桶比对之外的绝对差不做解读。
5. **首日实证（2026-10-14，48.6% 一致率）**：jev 明显偏 sell（176/214）且最大分歧源是
   「引擎 buy × jev sell」93 例；其中 65 例原料短窗超额为正 → jev 未跟随主锚①（详见 §七·跑）。

## §九 回退

ammo / runner / 集合 / 测试全部独立新增，`git revert` 单笔即回退；不触碰引擎、快照集合、
双题集既有集合与文档（本文件为唯一新增文档）。

## §十 待用户确认（确认后才开火）

1. 判据全文（§三）逐字确认或修改；
2. 判读帧默认 15:00 是否接受（引擎共振需 ≥9 次出现，午盘帧天然 insufficient）；
3. 台账口径（§五）是否够用，要不要加「分 tier 的 diverge 归因」列；
4. 开火范围：先单日（10-14）试点，还是直接挂每日盘后链（schedule `jevVoteRecheck` 同款步）。

## §十一 首日结果待裁（2026-10-14，用户已批准开火）

1. **48.6% 一致率是否可接受**（并列观察者定位下，diverge 本身不是失败，但 93 例集中在
   「原料说走强、jev 说走弱」且未跟随主锚，属题目问题不是口径差）；
2. 是否修判据（候选根因 a/b/c 见 §七·跑）后重跑 10-14（重跑=改门，须预登记+逐字确认）；
3. 是否维持现状只作观察（列位照常显示 jev 读数 + diverge 台账），等第二个交易日再判。

---

## §十二 二跑记录（v2 改门，2026-10-14；用户批准「按建议执行」）

- **改门内容（用户批准范围=修根因 b + a）**：①判据改成显式三步（第一步算超额 → 第二步阈值门定方向 →
  第三步修正只改置信/只把 buy 降为 hold，**不得反向制造方向**）；②**超额值由 runner 同款纯函数现算后
  直接喂进叙事**（`short_window_excess`，市场基准块首行 `USE AS-IS`），不让模型自己做减法；
  ③反转惩罚/持续性降级为「只否决 buy、不得单独制造 sell」；④强度题加「不得与第一步方向矛盾」。
  版本戳 v2 / `2026-10-14b`；runner done-skip **按题集代际**（旧代际 ok 文档不挡新代际，同 `_id`
  整档覆盖，单一事实源不留双轨）；doc 新增 `shortExcess`（判据第一步输入落档，归因可机械复算）。
- **二跑**：`--resonance-day 2026-10-14 --slot 15:00 --workers 4 --token-fuse 6000000 --fire`
  → **214 ok / 0 degraded / 30 留痕 / 945,020 tokens**（v1 读数被 v2 同 _id 覆盖）。
- **台账**：方向 agree **58 / diverge 156 = 27.1%**（v1 48.6%）；强度分带 112/102 = 52.3%（未变）。
- **归因（零成本，用新落的 `shortExcess` 机械复算）**：**改门本身完全生效**——
  jev 硬违规（越门反向：X≥+5 却 sell / X≤−5 却 buy）**1/214 = 0.5%**，而引擎同口径越门
  **19/214 = 8.9%**。一致率下降的真实机制：jev 严格走阈值门后，
  **|X|<5（与池子同步）的 103 只 jev 全判 hold**（判据第二步要求），而引擎在这 103 只里给了
  **buy 61 / sell 36 / hold 6**——引擎 direction 门槛是 clamped 加权和 >0.1（含加速度/跳变/
  持续性/反转惩罚多分量），远比 jev 的 ±5 门松。**27.1% = 「单锚可解释读数」vs「低门槛综合
  加权和」的系统性口径差被暴露**，不是 jev 判错（v1 的 48.6% 反而是两个综合判据偶然碰撞）。
- **待裁（未再改门）**：①接受 27.1% 作口径差基线，jev 读数按「并列观察者」照常展示
  （其价值在可复算：103 只「引擎说 buy/sell 但注意力与池子同步」是可拿 T+1 检验的断言）；
  ②把 jev 门从 ±5 收紧/放松到接近引擎灵敏度（但那样 jev 退化为复现算术，失去独立判读意义）；
  ③台账加「引擎 buy 但 jev hold 且 X_flat」专项计数（=61 例，最大分歧源，需预登记口径变更）。
