# L2 预登记合同：成交额量比喂量价档位判定（v1.1，2026-10-07 起草 / 2026-10-08 按审定回执修订，判定线冻结于跑数前）

> 合同地位：结构重设计计划（`ranktrend-vote-structure-redesign-plan.md`）W0-2 达线后的 L2 行为步预登记
> （用户 2026-10-07 深夜裁决三立项之一「amount 喂 tier L2 立项」）。AI 备料，**并入语料包 v2 走双模型
> 审定（用户亲自投喂，已完成 2026-10-08）→ 用户裁决开跑**，才动生产判据。审定结论=有条件通过
> （3 必改+2 建议，v1.1 全部落实，归档 `voting-signals-corpus-v2-review.md`）。
> 审定纪律同 Q1（算术与事实引用逐条可核，硬幻觉=驳回）。立项依据读数
> `data/reports/voting-signals-amount-leverage-w02.json`（台账 §20）。
> **v1.1 修订映射（跑前补全，非调线）**：A1 接线依赖声明 / A2 Track1 补 oos2 披露 / A3 oos1 止损带
> （建议采纳）/ A5 市况分桶 retreat 桶样本量下限 / A4 a-b 腿配对披露+按月可算率+b 臂方向标注（建议采纳）。

## 〇、机制事实（代码级，全部可复核）

- **根因**（语料 §4.2 量价①）：`amount_ratio`（成交额量比，`compute_amount_ratio`，G3 2026-08-18 接线）
  只进 `compute_volume_price_score` 的 score 加减分（≥`amountRatioHigh(1.5)` 加分 / ≤`amountRatioLow(0.5)`
  减分），**不进 `_volume_price_tier` 档位判定**——tier 只吃 quadrant+fund_score+reasons
  （volume_price.py:105-120）。W0-2 `vp_tier_drift`=0 逐帧自证此前提成立。
- **实证**（W0-2 预声明判定线达线，四窗一致单调）：可算帧 h8 分层（excess_mean，分位桶基线校正后）
  ——decision 窗放量(≥1.5) **−0.0127** / 中间带 +0.0043 / 缩量(≤0.5) **+0.0146**（high−low=0.0273）；
  midgap −0.0072/+0.0015/+0.0227；oos1 −0.0145/−0.0020/+0.0364；oos2 −0.0078/−0.0021/+0.0338。
  **放量帧排名 8 帧后验走弱、缩量帧走强，四窗无一例外**——「放量资金」在热榜语境是退潮保护信号，
  与 vp E 短路 −32% wrxpf 保护（§2.0/24.4）、SP5 温度轴 REVERSE、C6 弱势带同族。
- **可算率**：decision 72.4%（全窗 81.4%；7 月 23.8%=补采缺口月、4 月 64.4%=序列起点无基准，
  5/6/8/9 月 93-96%）——「amount 进 tier」在 decision 主判定窗覆盖 ≥7 成股帧，非贫料环境。
- **现有档位结构**（`_volume_price_tier`，按序短路）：①E=对倒出货/过度放量 reasons 硬风险；
  ②C=缩量涨停（信号真但不可交易）；③A/B=quadrant=="rise_volume"（放量上涨，fund_score>0 → A
  否则 B）；④C=rise_shrink/normal；⑤D=fall_*。
- **消费面**：tier 进 `_synergy_tier` 投票（`_vote(vp_tier, vp_dir) × tierSynergyVolumePriceVote(1.0)`）
  + E 硬短路否决（volume_price.py:383）。tier 降档 → vp 票值降 → synergy 档位阶梯重排。
- **暴露度**：可算帧中 ar≥1.5 占 15.8%、ar≤0.5 占 13.6%（decision 窗）；ar 分布 p10-p90 =
  0.353/0.853/1.179/1.372/1.627（中位 1.18，量纲健康）。

## 一、考题（本轮判定要回答的三个问题）

1. 撤回「放量上涨」的档位奖励（A/B 降档）能否在交易面无损（Track 1 wrxpf 相对 ≥0）前提下改善
   信号面判别（C1）？——机制预期是收缩面保护向（A/B 面↓），价值形态与 vp E 短路同族。
2. 剂量形态：单边撤回放量奖励 vs 双向门（+缩量升档）哪个更优？缩量升档是扩张面进攻向，
   先验不利（Q1 C-a 扩档拉动教训：S/A 帧膨胀而 excess 反向），带上它为完整测量「缩量最好」读数，
   阴性也归档。
3. 结构面：vp tier 分布迁移（A/B/C 档计数变化）与 synergy S/A 面传导；放量降档是否误伤强情绪期
   （市况分桶预注册）。

## 二、候选臂（冻结，跑后不得加臂；共 2 剂量臂 + 1 基线臂 = 3 次 replay + 2 Track 1）

新 config 开关（单参三态，默认 off=现行为零行为、golden 不漂移=第一断言）：
`volumePriceAmountTierMode: str = "off"`，枚举 `("off", "high_demote", "both")`。
门限**复用现有** `amountRatioHigh(1.5)` / `amountRatioLow(0.5)`（W0-2 分层读数即按此两档测得，
零新阈值参数=不拍脑袋）。

| 臂 | overrides | 语义 |
|---|---|---|
| baseline | `{}` | B0 自证（默认 config = G1 cross_day；锚 0.1450/0.0983/0.1172 逐位断言） |
| a_high_demote | `{"volumePriceAmountTierMode": "high_demote"}` | **放量奖励撤回**：可算帧
  ar ≥ amountRatioHigh ∧ quadrant=="rise_volume" → 档位降一档（A→B、B→C）；C/D/E/unknown
  与其余 quadrant 零改动。语义=「放量上涨」的 A/B 奖励撤回（奖励错发，h8 后验差） |
| b_both | `{"volumePriceAmountTierMode": "both"}` | **双向门**：a 臂全部语义 +
  ar ≤ amountRatioLow ∧ quadrant ∈ ("rise_shrink","normal")（即现 C 档）→ 升 B。语义=缩量
  惜售升档；**扩张面先验不利，对照臂**（若 a 过 b 不过=升档腿侵蚀，若 b 过 a 不过=升档腿独立有效） |

- **消费面唯一**：`compute_volume_price_score` 内 `_volume_price_tier(quadrant, fund_score, reasons)`
  调用处（volume_price.py:243）——`_volume_price_tier` 加可选入参（`amount_ratio`/`tier_mode`/
  两门限，None/off 恒走原路径零行为）；E 短路（①）与缩量涨停 C（②）分支优先级**不动**
  （硬风险语义高于 amount 门；缩量涨停帧语义特殊不参与升档）。score 链零改动（本case纯 tier 面）。
- **不撞已证伪面**：amount_score 进 score 的参数轴（amountScore* 族）§15 扫过=零效应，本case
  改的是「amount 进 tier 判定」（该路径从未存在过）；W2-2 价格确认门是 res/rank 维的门，
  本case是 vp 维自己的 tier 判定，无原料冲突。
- **选臂规则（机械化，冻结）**：两臂独立判定；若均过提交线，取 C-4.1 三窗均值相对改善更大者为
  提交候选，另一臂如实披露不静默丢弃。

## 三、判定框架（跑数前冻结）

### L2-1 窗口与 population

- T2 runner 同款：全窗 **2026-04-15 ~ 2026-09-12（951 帧）**，decision 04-15~07-31 / oos1 08-15~08-31 /
  oos2 09-01~09-12；B0 锚=G1 代际 **0.1450/0.0983/0.1172**（population=09-12 帧截止与锚同源；
  baseline 逐位自证 PASS 为跑数前置断言，不 PASS 全臂读数作废）。
- 立项读数（W0-2）为 1071 帧全窗口径（end=10-07），仅作立项依据不作判定口径——两口径差异如实披露。
- 信号面：各窗序列长度 ≥2 股帧（harness 现口径）；交易面：Track 1 decision 窗成交笔。

### L2-2 判定卡（继承计划判定线，跑后不调；v1.1 补 A2/A3/A5）

- **C1**：decision saEx 相对基线 ≥ +3%；
- **C2**：oos2 同向正（oos1 照登不设线）；
- **C3**：passHard 不降；
- **A3 止损带（v1.1 采纳）**：oos1 saEx 相对基线 < −5% → 该臂终止（gross-damage floor，T2 先例），
  不再进入提交候选；
- **Track 1 终判（v1.1 按 A2 扩）**：decision wrxpf 相对基线 ≥ 0（涉 tier 面必带；maxDD 容差 ≤ 基线）
  + **oos2 Track 1 披露义务**（基线在档：76 笔 / wrxpf 0.1660 / maxDD −0.1817；小样本只披露不设线，
  wrxpf 相对基线 < −5% 须显式解释交用户裁决，不得静默合并——Q1 v1.1 R5 判例同款）；
- **触发率披露（审定判定卡骨架通用条款）**：门改判帧数占比 =0 → 判零效应阴性不提交；<2% →
  如实标注「触面过小，效应量解释受限」（Q1 C-c 零效应教训）；
- **市况分桶（v1.1 按 A5 修）**：strong vs retreat 预注册对比对（market_regime state 仅报告列）——
  **retreat 桶 n<50 股帧时降级为只披露不挂起**（全窗 retreat 仅 29 帧，小样本反号判据会随机触发；
  强市期放量降档可能错杀=本case高危项的判读以 strong 桶与 decision 全人群为主）；
- **护栏（继承 T2 半数线）**：res S 档计数 ≥ 7185（14,370×50%）、synergy S 档计数 ≥ 64（127×50%）；
- **披露义务（本case特有，v1.1 按 A4 扩）**：vp tier 分布迁移表（A/B/C/D/E 档计数，a 臂预期
  A+B 面↓、若反升=实现有误须查；**b 臂另预期 C 档面↓B 档面↑**，与 a 臂对称披露）；b−a 臂
  **同帧改判集差异配对披露**（两臂共享 a 腿，仅配对差可分离升档腿贡献）；`vp_tier_drift` 自证列
  （off 臂恒 0）；可算率分窗分月表沿用 W0-2（**decision 窗按月列必附**——7 月 23.8% 贫料月
  的效应稀释面）。

### L2-3 准入与止损

- ≥1 臂同时过 C1+C2+C3+Track 1+护栏 → 提交用户裁决落默认（一次一候选，按选臂规则）；
- 全 FAIL → 阴性结果如实登记（台账+语料），不硬上、不调线重跑；
- 任一臂 C1 过但 Track 1 < 0 → 判不晋升（保护向机制若伤交易面=证伪其保护语义）。

## 四、实施与验证纪律

- **接线面（v1.1 按 A1 补依赖声明）**：`config.py` 新增 `volumePriceAmountTierMode`（含枚举校验入
  `_validate_tier_constraints` 同环）+ `volume_price.py` `_volume_price_tier` 分支（off 恒走原路径=
  零行为）；`assemble_observation` → `compute_volume_price_score` 的 amount_ratio 入参已在生产链
  （runtime:1462 → observation.amountRatio），零新序列传递。
  **接线前置依赖（A1）**：config.py / volume_price.py 当前为 P5 并行线未提交改动共享面
  （`lifecycle-p5-preregistration.md` 活进程先例）——**本case接线待 P5 线收官解锁，W1-1 同款处置**；
  golden 快照为二进制 gz 无法与 P5 改动手术分离，解锁前不重录。
- **测试纪律**：新开关默认 off 零行为=第一断言（三窗 saEx 逐位一致）；三态谓词单测（边界含等号：
  ar≥1.5 含 1.5/ar≤0.5 含 0.5；None 不可算帧不参与；E/缩量涨停优先级不被 amount 门改写；
  b 臂升档只触 rise_shrink/normal 的 C）；专项测试不触发真实模型调用；golden 快照预期零漂移
  （至多 configRepr 新增一行文本），重录+逐字段 diff 审查。
- **harness**：复用 `evaluate_voting_signals_t2.py` 骨架新建 `evaluate_vote_l2_vp_amount.py`
  （不触引擎文件）；Track 1 复用既有 track1 runner extra-arm 口径；vp tier 迁移矩阵在 runner 内
  baseline vs 臂逐帧比对。
- **成本**：3 replay（≈6 分钟/次）+ 2 Track 1 + 迁移矩阵复算，全本地 CPU，≈40 分钟墙钟，
  零 API 成本、零模型调用（AGENTS §1.2-7 合规）。
- **依赖声明**：无新数据链、无新集合、无新外部调用；amount_ratio 生产链已通（W0-2 自证）。
- **回退路径**：`volumePriceAmountTierMode="off"` 单开关回基线；晋升落默认后亦可以此回退。

## 五、流程

1. 本合同（AI 备料完成）→ 并入语料包 v2 → 用户投喂双模型审定（输出已归档
   `voting-signals-corpus-v2-review.md`，2026-10-08：**有条件通过，A1/A2/A5 必改+A3/A4 建议，
   v1.1 已全部落实**）
2. → **v1.1 修订登记完毕，待用户裁决开跑**（授权覆盖=接线→专项测试→trial→判定→登记→提交；
   落默认仍须用户裁决；接线另受 P5 收官解锁约束，见 §四 A1）
3. 任何判定线修改=新合同版本重新走审定（跑后调线=违规；v1.1 属审定者要求的跑前补全，非调线）。

## 六、起草者自报风险（供审定攻击）

① **混杂面**：放量帧聚集高分位（P5 D1：crowded 93% 落 pct 最高带）——W0-2 excess 已做分位桶
基线校正（桶内减基线），但「高带内放量更差」不等于「放量是独立负信号」（可能与高带拥挤交互），
trial 才是真判定；② **剂量轴未扫**：门限冻结 1.5/0.5 复用 score 阈值（有 W0-2 读数锚），
但 tier 面的最优门限可能≠score 面的（本合同只测现有阈值形态，剂量面重开须新合同）；③ b 臂升档
扩张面的稀释风险（Q1 C-a 教训），阴性概率不低——价值在完整测量「缩量最好」的投票面含义；
④ effect 量级预期小（可算帧 72% × 触发面 15.8%，其中仅 rise_volume 象限子集真正改档），
C1 +3% 线可能不达，阴性归档防重复立项；⑤ 缩量涨停/对倒出货等特殊帧的 reasons 优先级若实现时
被 amount 门穿插（顺序 bug），E/C 语义破坏——专项测试已列守卫断言；⑥ 四窗单调性来自
excess_mean 口径，saEx（S/A excess 合并）人群不同，立项读数与判定读数的人群差异如实披露。
