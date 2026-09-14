# RankTrend 生命周期环境门否决权重化 + 分层结构重构设计方案

> 状态：**brainstorming 草案（待用户确认关键决策）** · 2026-09-14
> 修订：**2026-09-14 对抗性审计修订版**——审计发现（1 Critical + 6 Important + 5 Minor）已全部
> 落入本文：§5 gate_off 锚点重设计为三点等价链（原"复现 −61% 读数"不可实现）、§3.1 参数定稿
> （删冗余 vote 字段、bool 改路径枚举、soft 合成语义精确化）、§5 判定卡 C5 重定义为结构守恒
> 约束、§5.1 补剂量-后果映射表、§4.3 前置验证补 score 直方图与 veto 覆盖率分析、§4.2 补展示分
> 权重复扫承诺、§0.4 预期管理、§0.5 关联文档声明。
> 修订 2：**2026-09-14 二轮 review 修复**——C5 改按 trial 组分作用域（e 组 vp 面约束）、
> §2.3 票权口径纠正（combo_three_quarter 为 res/rank/cs ×0.75，vp 维持 1.0）、§4.2.1/§7
> 发布面定稿（gateAction 为唯一可能新增字段，path/gateScore 均复用既有字段）、§2.1/§4.3
> 表述精确化、trial 预算补记。
> 触发：用户命题（长测复盘）——① 生命周期阶段作为环境门不作买卖投票，但周期 D/E 直接
> 降档/否决总档买卖信号，否决权过大且武断（拍脑袋式），未经回测验证强干预，要求按
> 趋势/总档权重阈值优化模式（阶段 22/23）重新设计优化方案；② 生命周期分层 A/B/C/D
> 经多轮长测证明对方向信号无正向贡献率，要求综合分析分层结构是否合理并给出优化方案。
> 方法论基准：阶段 22（趋势五权重实证）/ 阶段 23.9（总档四维票权重扫描）——参数化
> （默认值=原值 golden 不漂移）→ 单变量 5 档剂量扫描 → 组合 → Track 2 判定卡（C1-C5
> 三窗）→ 用户决策 → 落默认。

## 0. 结论先行

1. **问题 1 定性成立**：E 档短路否决与 B/D 降档是 `_synergy_tier`（volume_price.py:321/
   379）内两处结构硬编码，从未参数化、从未进入任何扫描。阶段 22 判定卡 C5 逐位 veto Δ=0
   的注记就是直接证据——"veto 走 lifecycle 层一票否决、不经五权重合成（**结构性不敏感**，
   非数据异常）"；阶段 23 B 组扫的是 lifecycle_decision 的**输入阈值族**（该决策的原料），
   门控**形态本身**（否决/降档/强度）不在任何参数空间里。它是当前合成链**唯二结构短路之一，
   且位阶最高**（lc E 强制 E 档封顶；另一处 vp E→D 只强制 D，见 §3.2 同构位）：名义上不投票，
   实际干预强度是离散 0/1 跳变、无剂量曲线。
2. **但"否决权过大"≠"应取消"**：阶段 23.8 整维归零对照（no_lc_gate）saEx
   −61.0%/−48.8%/−49.4% 三窗一致——环境门是当前 saEx 的第一支柱。正确方向不是移除，
   而是**保留干预、改造形态、权重化扫描**：把拍脑袋的 0/1 干预变成扫描出来的连续标量。
3. **问题 2 定性成立**：A/B/C/D(E) 作为**方向分层**不合理（无 S 档、A/B 反转、A 档
   oos2 转负、D/E/B 统计退化、阈值坐标下降已证伪"可修复"）；但作为**环境/风险标签**
   有真实价值（veto 卖侧保护 + cooling 降档，两者相对贡献未分离，见 §2.3）。重构方向：
   伪方向标尺退役（降级为展示投影），合成/门控消费改走"连续环境分 + 可调迁移函数"。
4. **预期管理（立项前必读）**：阶段 12 K 实验（veto 触发覆盖率下降 → saEx 三窗一致受损、
   决策窗单调恶化）
   与 23.8 归零对照（全拆 → saEx 腰斩）共同指向"软化很可能受损"。本方案最可能的结局是
   **证伪软化、坐实 hard 形态、补齐剂量曲线存档**（§5.3.2）——方案 A 的主要交付物是
   **认知闭环（补齐 23.9 未竟的方法论缺口）+ 为方案 B 铺路**，而非性能提升。应以该预期立项。
5. **关联文档**：本方案承接并部分取代 `ranktrend-lifecycle-layer-rearchitecture-design.md`
   （2026-08-16）——该前案的方案 A（four_dim 入场主轴）已落地为当前交易层入场判定
   （execution.py:499-513，walk-forward 7/7 段胜基线），其 §2.1/§2.2 证据表与本方案 §2.2
   同源；本方案在其"生命周期降级为环境门"方向上继续推进**门控形态**与**分层结构**两步，
   前案不再单独更新。

## 1. 现状还原：D/E 干预的全部消费面（4 面）

| # | 消费面 | 位置 | 行为 |
|---|---|---|---|
| 1 | 总档合成 | `ranking/volume_price.py` `_synergy_tier` :321 | `lc_tier=="E"` → 直接返回 "E"（"周期一票否决"短路，票值无关）；`lc_tier∈{B,D}` → S→A/A→B 降一档（:379） |
| 2 | 候选池 | `engine/runtime.py` :809 / :471 | action=veto → candidateTier 锁 N_NEUTRAL（阻止进 A/B 候选池） |
| 3 | 交易层 | `core/backtest/execution.py` :499/:511 | 入场：synergy tier ∈{S,A} + zljzb≥0 + `lifecycle.veto` 非否决（对 four_dim 与总档 E 面构成双重锁）；出场：synergy D/E 走 synergyExitOnDanger / synergyDowngradeSteps 计数 |
| 4 | 确认链 | `engine/runtime.py` :1152（WP2a） | veto 与 B/D 降档 K 帧确认（K=1 默认直通；K=2/3 阶段 12 已证伪） |

同构位（同类未验证 0/1 干预，顺带纳入扫描）：`vp_tier=="E" → 总档 "D"`（量价出货
硬风险短路，volume_price.py:323）。

**触发结构（阶段 23.2 层 1 实测，rawHits 口径）**：veto 8.4%（其中 stage=reversal
驱动 8816/11003，HighRisk 压力路径占比小）；B/D 降档实际改判 4.3%；合计 ~12.7% 帧被
环境门改判。档位分布：D 76.4%（cooling 主导）/ A 13.9% / E 8.4% / B 1.2%，无 S 档。

## 2. 证据链

### 2.1 干预形态从未被验证（问题 1 证据）

- 阶段 22 C5：三档权重提案 veto 翻转率逐位 Δ=0——五权重面结构性碰不到 veto；
- 阶段 23 B 组：扫的是 lifecycle_decision 输入阈值（MidLongCommitmentMin 等 13 阈值），
  门控形态（短路否决 vs 负票 vs 惩罚）不在参数空间；
- 动过门控的实验有两类，均不覆盖**形态强度轴**：
  ① 23.8 归零对照（全拆，−61%）——证明价值存在，但没有强度梯度；
  ② 阶段 12 K=2/3 确认链（veto 翻转率 0.127→0.023→0.010，决策窗 saEx
  0.0811→0.0539→0.0454 单调恶化、OOS 两窗一致受损，oos2 K=2→3 微反弹 0.0230→0.0279
  非严格单调）——动的是**触发覆盖率**（哪些帧触发），且已证伪；
- 结果：E 否决 = 无穷大负干预（票值无关短路），B/D 降档 = 固定 −1 档跳变，两者都
  没有"剂量-响应"曲线，与阶段 22/23 确立的"剂量扫描找甜点"方法论存在方法论缺口。

### 2.2 A/B/C/D(E) 无方向贡献率（问题 2 证据，多轮独立实证同向）

| 证据 | 来源 | 结论 |
|---|---|---|
| 语义校准 769 帧/156647 信号 | 主计划 §5.4（阶段 3 同源数据，commit `40ddc7f`） | lifecycle 无 S；A +0.055 < B +0.097 反转；rankTrend 对照组达标 |
| 生命周期分层 vs RankTrend 匹配度 | 阶段 6 s7（0.4973 载体：rearchitecture 文档 §2.1 证据表） | A_MAIN h8 0.514 < S/A 基线 0.5272；D 状态 h8 0.5264（预测反弹，均值回归）；stage=reversal 0.4973（无预测力）；唯一有效状态机信号 D→B 跃迁 0.5198 |
| 阈值坐标下降搜索 | lifecycle-threshold-optimization-design §8.2 | best=baseline：A 档混杂全部 allow×ignition/expansion 高分位帧（均值回归拖累）、B 档低分位天然高——**分位结构性差异，阈值不可调** |
| 层 1 事件级区分度 | 阶段 23.2 | A +0.036/+0.030/**−0.0006**（逐窗衰减，oos2 转负）；D/E/B saEx=None（统计退化） |
| 6-07 审计 | `docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md` | "生命周期分层实现不能继续被当成可靠买卖标签……不适合作为硬入场、硬过滤或独立买卖系统" |

### 2.3 环境门的真实价值构成（正面证据，重构不能丢的部分）

- no_lc_gate 三窗 −61%/−48.8%/−49.4%（23.8）：门控干预（否决+降档）是 saEx 第一支柱；
- **待验假设（非已证事实）**：干预价值可能集中在负向过滤（reversal 否决、cooling 降档），
  但 23.8 是 veto+降档**一起拆**的，两者相对贡献从未分离——且与阶段 6 证据存在真实张力：
  D 档帧预测反弹（h8 0.5264，均值回归）、D_EXIT_RISK 退出被证在均值回归区过早离场，
  意味着 **cooling 降档完全可能是负价值**（对入场排序而言）。§5.1 c1 组（降档关闭）
  正是裁决点，先验如实登记两种可能；
- "环境门有价值"与"分层无方向贡献"两个命题同时成立、互不矛盾；
- 结构事实（23.8 + 23.9.1）：res/rank/cs 票权已参数化并落 0.75、vp 参数化后维持 1.0
  （combo_three_quarter，23.9.1 落默认；23.8 归零对照实测于落默认前的 1.0 票权基线），
  唯独 lifecycle 以结构短路形式持有无限大话语权——修复它正是补齐 23.9 的未竟部分。

## 3. 方案 A：环境门干预形态权重化（问题 1 主方案，先行）

### 3.1 参数化设计（默认值 = 现行为，golden 不漂移）

```python
# RankTrendConfig 新增（草案命名，实施时定稿；名称已核对未占用）
lifecycleGateMode: str = "hard"         # hard=现行为（E 短路否决 + B/D 降一档）
                                        # soft=负票/惩罚形态 | off=全拆（评估锚）
lifecycleVetoPathMode: str = "all_soft" # 仅 soft 生效，veto 双路径分流：
                                        # all_soft=两路都转负票 |
                                        # reversal_hard=reversal 保留硬否决、HighRisk 转负票（d1）|
                                        # highrisk_hard=HighRisk 保留硬否决、reversal 转负票（d2）
lifecycleVetoVoteStrength: float = 1.5  # soft：E 帧 v_final = v_raw − strength 后重走阈值阶梯
lifecycleDowngradePenalty: float = 0.5  # soft：B/D 帧且首评 ∈ {S,A} 时 v −= penalty 后重走阶梯
```

（原草案 `tierSynergyLifecycleVote`/`lifecycleHardVetoKeepHighRisk` 两字段废弃：
前者与 vetoVoteStrength 语义重叠且乘法组合下默认 0 会静默归零干预；后者单一 bool
无法表达 d1/d2 两个方向。）

**soft 模式合成语义（实施 spec，TDD 按此逐条断言）**：

1. **E 帧（action=veto）**：按 lifecycle decision 驱动路径分流（分流口径与 23.2 的
   8816/11003 统计同源：stage=reversal vs HighRisk 压力路径）——
   - 命中 `*_hard` 保留侧 → 保持现行为（短路返回 "E"）；
   - 转负票侧 → `v_final = v_raw − lifecycleVetoVoteStrength`，**先**继续走 vp E→D
     短路检查（volume_price.py:323 先后顺序保持不变：soft 模式下 E-lifecycle 帧若
     vp_tier=="E" 仍返回 "D"），再走阈值阶梯落档。"否决"变"重罚"：D 线（≤−1.0）
     仍可达，两/三票强同向可部分对冲。
2. **B/D 帧降档替换**：先按 v_raw 正常落档；**仅当首评 ∈ {S,A}** 时 `v −= penalty`
   重走阶梯。B/C/D 帧不受 penalty 影响（作用域与现降档一致：现降档也只作用于已达
   S/A 的帧）。
3. **边界映射预登记（剂量曲线的一部分，判定时不得误读）**：
   - penalty=0.5：v=2.0（S）→ 1.5 → **B（跳过 A，两档下坠）**；v=3.0（S）→ 2.5 → A；
   - strength=1.5：v_raw=2.0 → 0.5 → C；v_raw=3.5 → 2.0 → A（仅近乎全票一致可达）。
4. `_validate_tier_constraints` 增加 fail-fast：strength/penalty 负值、mode/pathMode
   非法枚举。

### 3.2 同构位顺带扫描

`volumePriceGateMode`（vp E→D 短路，形态参数：off=移除短路 / soft=改负票）作为附加
trial 组——同一 harness、一行 patch，避免留下第二处未验证硬干预。

### 3.3 范围声明（一次只动一个面，避免无法归因）

本方案**只动总档合成面（#1）的直接逻辑**。候选池面（#2）与交易层**入场腿**（#3 的
`lifecycle.veto` 检查）保持现行为（`lifecycle.veto` 标志照常发布）。**须如实声明的
间接泄漏**：交易层**出场腿**（synergyExitOnDanger / downgradeSteps）消费 synergy
tier 分布，soft/off 模式下 E 帧落 D/B/C 会改变出场触发——该效应归入 §5.2 交易层复核
口径，不构成范围破坏。WP2a 确认链（#4）自动跟随（确认的是 lc tier/action 值，消费
语义不变）。若合成面判定卡通过且需继续放开，第二轮再以 `lifecycleVetoBlocksCandidatePool: bool`
等开关扫描 #2/#3 入场腿——两轮各自的效应可归因。

## 4. 方案 B：分层结构重构——双轴 + 连续环境分（问题 2 主方案，A 之后）

### 4.1 诊断结论

A/B/C/D(E) 单轴混装了三件正交的事：**路径**（ignition/expansion/crowded/cooling/
reversal 排名动力学标签）、**风险动作**（veto/caution/allow/exit_watch）、**伪方向序**
（A>B>C>D>E 暗示的方向梯度）。前两件有真实信息（§2.3），第三件被 §2.2 证伪。
候选真实信息含量集中在三个可测点：reversal→veto（卖侧保护）、cooling→D 降档
（**价值方向未定，见 §2.3**）、allow×ignition/expansion→A（弱正且衰减）；
B（1.2%）与 C（中性）几乎无独立信息。

### 4.2 重构设计

1. **发布轴拆分（按现状实测 runtime.py:414-421 定稿）**：observation.lifecycle **已发布**
   `stage`（5 态路径）与 `score`（0-100）——`path`/`gateScore` 为既有字段复用，零新增；
   **唯一可能新增的字段是 `gateAction`**（4 态 veto/caution/allow/exit_watch；现仅发布
   veto bool，runtime.py:417）。实施时二选一定稿：① lifecycle 新增 gateAction 字段
   （快照 payload 增字段，触发 §7 同步义务）；② 不新增，展示/门控消费改读
   cycle.decision.action（零 payload 变更，推荐先按 ② 评估）；
   现有 `signalTier`（A/B/C/D/E）保留为**纯展示投影**（从 path×action 派生，TS 合同
   零破坏，展示口径渐进迁移）；
2. **gateScore 复用现有字段，不新增发布面**：即 `observation.lifecycle.score`
   （`compose_observation_scores` 四因子分 stageFitness/pathCommitment/momentumConfirmation/
   riskSafety，runtime.py:416 已发布 0-100）——不造新因子、不加发布字段（不触发快照
   payload 变更义务），先验证它作为门控输入的方向内容；
   **参数台账连带义务（方案 B 全量推进时）**：lifecycleWeights 四因子权重在阶段 23.3
   被裁"signal-neutral 展示层冗余、不做深扫"、23.9 硬编码清点登记为"展示面未扫描"——
   一旦成为门控输入，该分类**失效**，权重轴重新进入信号参数空间：L1 台账状态须从
   "展示面"变更为"门控输入（未扫描）"，并补权重扫描计划后方可全量实施；
3. **门控迁移函数参数化**（方案 A soft 模式的自然延伸）：`vetoFloor`（score 低于此 →
   负票强度全额）/ `downgradeKnee`（低于此 → 半额惩罚）两阈值 + §3.1 强度参数，
   把"stage 标签驱动"换成"连续分驱动"，否决/降档从离散跳变变成带剂量曲线的函数。

### 4.3 方案 B 前置验证（只读，零行为变化，可与方案 A 同批先做）

按序三步，任一失败即触发收缩条款：

1. **步骤 0（分布可行性）**：先出 decision 窗 `lifecycle.score` 直方图——若单桶
   >60% 帧则 5 等宽桶不可用，改分位桶并在报告注明；
2. **方向内容**：按桶算 h1 saEx 单调性与每桶样本量（分位桶基线桶内重算），对比
   A/B/C/D(E) 档位的 saEx（多数 None）——单调且样本充足 → 连续分有 A/B/C/D(E) 没有
   的方向内容，支持 §4.2 推进；不单调 → 连续化救不了方向面，方案 B 收缩为"展示语义
   澄清"（退役伪方向标尺、双轴发布），门控保持标签驱动但走方案 A 权重化；
3. **覆盖率/一致性（防"单调性通过但保护已丢"）**：环境门价值主体走负向过滤与出场
   （saEx 部分测不到，阶段 12 K 实验已证明 veto 触发帧含真实信息）。以 "score ≤ t"
   扫描阈值 t，对现 action=veto 信号集（decision 窗 rawHits 11003，约 655 帧）算
   召回率/假阳率曲线；
   合理阈值下召回 <80% 即判"分数低尾不承载 veto 信息"，门控迁移条款收缩（保持标签
   驱动）。同时注明：score 驱动对出场通道（synergyExitOnDanger）的影响 saEx 不可见，
   与方案 A 同样适用 §5.2 Track 1 复核义务。

## 5. 实证设计（复用阶段 22/23 harness 模式）

- harness：`backend/operations/evaluate_lifecycle_gate_form.py`（TDD；trial 级缓存
  resume；`assert_not_frozen` 8 月冻结守卫；测试 `tests/test_lifecycle_gate_form_harness.py`）；
- 窗口与锚：decision 04-15~07-31 / oos1 08-15~31 / oos2 09-01~12；
- **锚点体系（审计修订：原"gate_off 复现 −61% 读数"不可实现——23.8 读数实测于落默认前
  的 1.0 票权基线（22.8 锚），当前默认已是 combo_three_quarter 0.75 票权（23.9.1 锚），
  票流分布不同，同一次全拆的相对读数必然漂移）。改为三点等价链：**

| 锚 | 配置 | 验收 |
|---|---|---|
| 锚 1 新基线 | 默认 `RankTrendConfig()` | 三窗逐位复现 23.9.1 锚（decision 0.1044 / oos1 0.0918 / oos2 0.0933） |
| 锚 2 旧票权基线 | patch res/rank/cs=1.0（vp 本就 1.0） | 三窗逐位复现 22.8 锚（decision 0.0939 / oos1 0.0854 / oos2 0.0737） |
| 锚 3 等价性验证 | 锚 2 + `lifecycleGateMode=off` | 三窗**逐位复现** 23.8 no_lc_gate 读数（相对锚 2 −61.0%/−48.8%/−49.4%） |

锚 3 不逐位一致 = mode=off（config 路径）与 23.8 wrapper 注入的删除面存在实现差异，
**先修再继续**（这正是交叉验证的目的）。全部正式 trial 在锚 1 新基线上跑。
- 判定：Track 2 判定卡 C1-C5 同构 + regime 四桶 + **S+A 触发率漂移** + 样本量/passHard
  （防 23.9 ×0.5 档式统计崩溃）+ **C5 重定义（见下）**；
- **判定卡口径修订**：
  - **C3**：passHard 按 decision 窗计（阶段 23 惯例；当前默认 oos1/oos2 passHard 非 True
    为既有口径，不作判定项）；
  - **C5 重定义**：本方案的干预对象就是 veto/bd——其翻转是**处理效应**而非稳定性缺陷，
    原口径自动失效。改为**按 trial 组分作用域的结构守恒约束**（处理集之外的帧 synergy
    档位三窗逐位零翻转，同时是各模式实现正确性的最强断言）：
    lc 面 trial（a 锚 / b / c / d）→ 非 lc E/B/D 帧（~87.3%）零翻转；
    vp 面 trial（e1a/e1b）→ 非 `vp_tier=="E"` 帧零翻转（vp 短路处理集与 lc tier 无关，
    可落在 lc A/C 帧上，不得套用 lc 约束）；
    组合 trial（p1-p2）→ 两组约束取并；
    veto/bd 翻转率降级为处理效应观测量（报告展示，不判定）。

### 5.1 trial 表（审计修订：展开计数歧义 + 补剂量-后果映射）

**剂量-后果映射（解读规则，预登记）**——当前票权下 max v = res 0.75×1.2 + rank
0.75×1.2 + vp 1.0×1.2 + cs 0.75×1.0 = **3.75**（A 线 2.0 / S 线 3.0 / D 线 −1.0，
config.py:318-320）。E 帧 A 档可达条件 v_raw ≥ 2.0 + strength：

| strength | A 档可达条件（占 max） | 入场侧效果 |
|---|---|---|
| 0.375（b0） | ≥2.375（63%） | 真软化（最可及档） |
| 0.75（b1） | ≥2.75（73%） | 真软化 |
| 1.5（b2） | ≥3.5（93%，近乎全票一致） | 近似硬否决 |
| 2.25（b3） | ≥4.25 > 3.75 **不可达** | **入场侧 ≡ 硬否决**，只剩出场/排序差异 |

**解读规则**：b3 ≈ baseline 不得读成"软化无害"（它入场侧没软化）；b0/b1 才是软化
观测点；b2/b3 的读数主要刻画**出场/排序通道**。若 b0/b1 受损而 b3 无损，结论收敛为
"软化受损、维持 hard"。

| 组 | trial | patch | 目的 |
|---|---|---|---|
| 锚 | a0 baseline / a1 锚2 / a2 gate_off(锚2) / a3 gate_off(新基线) | 见锚点体系 | 锚点复现 + 等价性验证 + 新基线下界参照 |
| veto 剂量 | b0-b3 | mode=soft，pathMode=all_soft，strength ∈ {0.375, 0.75, 1.5, 2.25}（0.75 票权步长 ±半档） | E 否决 → 负票的剂量曲线（找甜点） |
| 降档形态 | c1 / c2a / c2b | 降档关闭 / penalty=0.25 / penalty=0.5 | 降档跳变 vs 连续惩罚 + §2.3 裁决 cooling 降档价值方向 |
| 混合路径 | d1 / d2 | pathMode=reversal_hard（reversal 硬 + HighRisk 负票）/ pathMode=highrisk_hard（反向） | 区分两条 veto 路径（8816/11003 为 reversal） |
| 同构位 | e1a / e1b | volumePriceGateMode=off / =soft | vp E→D 短路验证（可交叉参照 23.8 no_vp，其同时移除了 vp E→D——但 no_vp 还归零全部 vp 票，读数不可直接对数，仅方向参照） |
| 组合 | p1-p2 | 上述有正读数单变量组合 | Track 2 判定卡 |

trial 预算：锚 4 + b 4 + c 3 + d 2 + e 2 + p 2 = **17 组 × 3 窗 ≈ 51 次 replay**
（对照：阶段 22 共 57 次、阶段 23 为 55 trial/窗）。

### 5.2 交易层复核（saEx 口径盲区，必做）

veto 形态改变直接动 entry/exit（synergy tier 分布平移 → synergyExitOnDanger /
downgradeSteps / S,A 入场池），而 saEx harness 测不到交易层效应（阶段 23.5 对
decisionReversal* 的同类裁定）。判定卡通过的候选必须追加 Track 1 交易模拟
（winRate×pf 对照当前默认基线）后才进用户决策。环境门价值主体可能在出场通道
（§4.3 步骤 3 同款盲区），Track 1 是软/硬形态裁决的最终口径。

### 5.3 先验风险（如实声明）

1. **S/A 触发率回灌**：软化 veto/降档必然抬升 S/A 触发率，与阶段 22/23 全部已采纳
   改动（收紧触发、提升排序质量）方向相反——若 saEx 改善只是"触发面扩大"的稀释效应，
   绝对量级表会暴露（C1 用相对 +3% 线、绝对量级与分位桶质量双查）；
2. **两条独立的"软化受损"先验**：① no_lc_gate −61%（23.8）说明门的主体价值大概率
   来自硬否决对少数高杠杆帧的拦截；② 阶段 12 K=2/3：仅把 veto 触发覆盖率从 12.7%
   降到 2.3%/1.0%，决策窗 saEx 即 0.0811→0.0539→0.0454 单调恶化，OOS 两窗同向——
   **被滤掉的"单帧噪声 veto"里含真实信息**。负票形态可能测出"任何软化都受损"——
   这也是有效结论（证伪本方案、坐实现状形态），届时问题 1 的答案收敛为"否决权已经过
   归零对照 + 覆盖率双重验证、维持 hard，但补齐剂量曲线存档"（§0.4 预期管理）；
3. 展示面：synergy tier E 帧减少 → 前端"周期一票否决"徽章出现频率下降，属预期行为。

## 6. 关键决策点（待用户确认）

1. **推进顺序**：推荐 方案 B 前置验证（只读、半天）→ 方案 A harness 扫描 → 判定卡
   → 交易层复核 → 用户决策落默认；方案 B 全量实施视前置验证结果另立项。
   **预期重申**：最可能结局是证伪软化、坐实 hard（§0.4），立项价值在认知闭环；
2. **veto 剂量轴档位**：b0-b3 四档（{0.375, 0.75, 1.5, 2.25}，0.75 票权步长 ±半档），
   b0 为审计修订新增的低剂量可及档；是否需要 ±外扩档；
3. **候选池面/交易层入场腿**是否同轮放开（推荐第二轮，保持归因清晰；出场腿经 §5.2
   复核覆盖）；
4. **同构位** vp E→D 短路是否同轮扫描（推荐同轮，成本低）；
5. **顺序依赖（新增）**：23.9.1 挂起的"9 月全月复验"（10 月上旬）可能移动 combo_three_quarter
   基线锚——若复验改变默认口径，本方案 harness 三窗锚需重跑复核后再出判定卡。建议本方案
   扫描安排在 9 月全月数据入库后、与复验同批或紧随其后执行。

## 7. 复现与回退边界

- 方案 A/B 前置验证均为只读评估，零默认值改动，无需回退；
- 若判定卡通过并落默认：回退 = config 字段还原（mode=hard / 权重 0）或整体 revert；
  config_hash 天然区分两代口径，历史快照不迁移不重算；
- 相关文档同步义务：
  - L1 参数档案（`ranktrend-l1-param-ledger.md`）——含方案 B 全量时四因子权重状态
    从"展示面"变更为"门控输入（未扫描）"（§4.2.2）；
  - 本目录主计划（实施时挂阶段 24）；
  - `docs/ranktrend-observation-discrete-tiers-design.md`（tier 语义）；
  - `ranktrend-lifecycle-layer-rearchitecture-design.md` 头部补"由本方案承接"注记
    （§0.5，前案停止单独更新）；
  - 发布面（随 §4.2.1 定稿同步）：path=复用 `stage`、gateScore=复用 `score`（§4.2.2）
    均零新增、无 payload 变更义务；**gateAction 为唯一可能新增的字段**——若选 §4.2.1
    ①（新增字段），按 AGENTS.md §8 同批检查 `database-migration-plan.md` /
    `architecture.md` / `api-cli.md`；若选 ②（消费 cycle.decision.action 不新增），
    无 payload 变更义务。

## 8. 实施记录（2026-09-14 完成，两轮扫描 + Track 1 全链闭环）

**实施偏差（一项，如实声明）**：§3.1 单一 `lifecycleGateMode` 枚举实施时拆为
`lifecycleVetoGateMode` / `lifecycleDowngradeGateMode` 两个正交开关——§5.1 trial 表的
b 组（只动 veto 剂量）与 c 组（只动降档形态）要求单变量归因，单枚举会把两轴绑死；
trial 语义与本方案完全一致，其余字段/校验/语义按 §3.1 逐条落地（TDD 39+18 用例，
全量 pytest 2247 passed，默认行为零漂移）。

**执行结果摘要**（完整记录见主计划阶段 24）：

| 步骤 | 结果 |
|---|---|
| 锚点等价链（§5） | a0/a1/a2 三点三窗全部逐位复现（23.9.1 / 22.8 / 23.8 no_lc_gate 锚）——config 路径 mode=off ≡ 23.8 wrapper 注入 |
| C5 结构守恒（§5 重定义） | 全部 trial 三窗零违反 |
| 方案 B 前置验证（§4.3） | 方向内容 FAIL（score 分桶 saEx U 形，spearman −0.1）→ **收缩为展示语义澄清**；veto 覆盖 PASS（t=50 recall 0.838） |
| veto 剂量轴（b0-b3） | 软化 decision 单调受损；b2/b3 零效应（负票不进链）——**维持 hard** |
| 降档形态轴（c1-c5） | penalty 1.0 三窗逐位=baseline（数学等价硬降档，交叉验证）；U 型峰=1.0≡hard——**维持 hard**；c2b decision +3.5% 为 OOS 双负单窗假阳 |
| 路径分流（d1/d2） | 三窗逐位零效应 |
| vp 同构位（e1a/e1b） | e1a(off) saEx +9.8/−3.0/+33.4 PASS_CANDIDATE；e1b(soft) 逐位=baseline |
| 组合 p2=e1a×b1 | saEx 三窗全正 +6.7/+2.7/+39.3% PASS_CANDIDATE |
| **Track 1 交易复核（§5.2）** | **e1a/p2 主窗（decision，144-164 笔）wrxpf 0.470→0.319（−32%）、maxDD −18%→−32%——否决**；oos2 +64% 为 22 笔小样本 |

**最终判定**：p2/e1a 判 OBSERVE 不落默认，**维持 hard 现行为**（零默认值改动）。§0.4
预期管理兑现：交付物为认知闭环——用户"否决权武断"命题经三轴剂量曲线 + Track 1 完整
证伪，三处 0/1 干预均为数据验证后的局部最优。p2 入观察池（复核触发：9 月全月复验，
与 23.9.1 同批）；方案 B 展示语义澄清未立项。
