# W1-1 预登记合同：共振 D∧buy 倒挂票修复（2026-10-07 起草，判定线冻结于跑数前）

> 合同地位：结构重设计计划（`ranktrend-vote-structure-redesign-plan.md`）W1-1 案的预登记。
> 流程：本合同起草（AI 备料）→ 用户过目 → 外部模型审定（用户亲自投喂，A/B 对比制可选）→
> 用户裁决开跑 → 才动生产判据。审定纪律同 Q1（算术与事实引用逐条可核，硬幻觉=驳回）。
> **实施前置阻塞：Q1 并行线 trial 运行中（config.py 缠绕）——接线须待 Q1 线收官，本合同先行走审定流程。**

## 〇、机制事实（代码级，全部可复核）

- **D 档两条路径**（`runtime._resonance_tier`，按序短路）：
  1. `reversal_penalty ≥ tierResonanceReversalPenaltyMin(0.6)` → D（「反转惩罚高 X%」）——**与方向无关**，
     先于所有 buy 分支判定；
  2. 方向 sell（落空分支）→ D（「共振衰竭/反向」）。
- **D∧buy ⟺ 路径 1（reversal_penalty 驱动）**：方向 buy 时唯一 D 来源是路径 1（方向 sell 才能落进
  路径 2）。**推论：计划候选 c（仅 reversal_penalty 驱动的 D 弃权）与候选 b（衰竭 D∧buy 弃权）在当前
  机制下数学等价**——本合同并案处理（见 §二），计划「≤3 档」按两臂执行。
- **倒挂算术**（`volume_price._synergy_tier._vote`）：vote = 强度 × 方向符号 × 维权重。
  `tierSynergyVoteStrengths=[1.2, 1.0, 0.7, 0.5, 1.0, 1.0]`（S/A/B/C/D/E）、
  `tierSynergyResonanceVote=0.75` → **D∧buy = 1.0×0.75 = +0.75 > B∧buy = 0.7×0.75 = +0.525**。
  衰竭档（D 语义=反转惩罚高）比健康弱确认档（B）投出更高的正票=方向主导设计（2026-08-15 v4）的副作用。
- **暴露度**：D1 实测 res D∧buy 占 6.6% 帧（`data/reports/voting-signals-d1.json`，951 帧口径）。
- **守门维背景**：synergy S 档 127 帧（0.08%）127/127 靠 cs 正票撑进（corpus §12 结构发现）——
  res 侧 D∧buy 修正在 S 档边缘的挤出效应须显式披露（S/A 计数变化表，防「档位扩容拉动 excess」误读）。

## 一、考题（本轮判定要回答的三个问题）

1. 修正 D∧buy 倒挂票能否在交易面无损（Track 1 wrxpf 相对 ≥0）前提下改善信号面判别（C1）？
2. 剂量形态：封顶到 B（保留部分方向票）vs 弃权（票 0）哪个更优？
3. 结构面：修正对 S/A 档计数与 res 迁移矩阵的影响（D∧buy 帧 6.6% 中多少降档/弃权，synergy 档位
   如何迁移，S 档守门结构是否被破坏）？

## 二、候选臂（冻结，跑后不得加臂；共 2 剂量臂 + 1 基线臂 = 3 次 replay + 2 Track 1）

新 config 开关（单参三态，默认 off=现行为零行为、golden 不漂移=第一断言）：
`tierSynergyResonanceDbuyMode: str = "off"`，枚举 `("off", "cap_b", "abstain")`。

| 臂 | overrides | 语义 |
|---|---|---|
| baseline | `{}` | B0 自证（默认 config = G1 cross_day；锚 0.1450/0.0983/0.1172 逐位断言） |
| a_cap_b | `{"tierSynergyResonanceDbuyMode": "cap_b"}` | D∧buy 票值封顶 B：res 投票处强度取
  `min(D 强度, B 强度)=0.7`（B 强度读 `tierSynergyVoteStrengths` 表不硬编码，防强度表改动错位）→
  vote +0.525；`_resonance_tier` 不变（展示层 D 档语义保留，dv 式观察资产不动） |
| b_abstain | `{"tierSynergyResonanceDbuyMode": "abstain"}` | D∧buy 弃权：res 投票处 vote=0（档位展示
  语义不变）；**D∧sell（路径 2「真反向 D」）票 −0.75 不动**——反向确认仍有效（计划原文保留） |

- **消费面唯一**：`_synergy_tier` 内 res 维投票点（`_vote(res_tier, res_dir) × res 权重` 处加分支）；
  rank/vp/cs 维不触及（rank D=base sell 无 buy 向；vp/cs 无方向票语义）。
- **不撞证伪论证**（计划原文）：票权/强度表轴已扫（§15.2）的是「档位强度值」，本case改的是
  「D∧buy 组合语义」（该组合从未被单独测量）；res 归零臂受损 23-55% 证明维度在票，动一个子组合≠归零。
- **选臂规则（机械化，冻结）**：两臂独立判定；若均过提交线，取 C-4.1 三窗均值相对改善更大者为
  提交候选，另一臂如实披露不静默丢弃。

## 三、判定框架（跑数前冻结）

### W1-1.1 窗口与 population

- T2 runner 同款：全窗 **2026-04-15 ~ 2026-09-12（951 帧）**，decision 04-15~07-31 / oos1 08-15~08-31 /
  oos2 09-01~09-12；B0 锚=G1 代际 **0.1450/0.0983/0.1172**（population=09-12 帧截止与锚同源；
  baseline 逐位自证 PASS 为跑数前置断言，不 PASS 全臂读数作废）。
- 信号面：各窗序列长度 ≥2 股帧（harness 现口径）；交易面：Track 1 decision 窗成交笔。

### W1-1.2 判定卡（继承计划判定线，跑后不调）

- **C1**：decision saEx 相对基线 ≥ +3%；
- **C2**：oos2 同向正（oos1 照登不设线）；
- **C3**：passHard 不降；
- **Track 1 终判**：decision wrxpf 相对基线 ≥ 0（涉入场面必带；maxDD 容差 ≤ 基线）；
- **市况分桶**：strong vs retreat 预注册对比对（market_regime state 仅报告列），两桶反号 → 挂起；
  **【v1.1 澄清 2026-10-08，语料包 v2 审定回执 A5 同款通用条款，非调线】retreat 桶 n<50 股帧时
  降级为只披露不挂起**（小样本反号判据会随机触发；harness 已实现 market_regime 披露列，判定时按此执行）；
- **护栏（继承 T2）**：res S 档计数 ≥ 7185（14,370×50%）、synergy S 档计数 ≥ 64（127×50%）
  —— res 修正直接动 res 档位分布，半数线为结构护栏；
- **披露义务**：S/A 档帧计数变化表 + per-dim res 迁移矩阵（D∧buy 帧在 a/b 臂下的
  vote 变化 × synergy 档位迁移）+ 笔数变化。

### W1-1.3 准入与止损

- ≥1 臂同时过 C1+C2+C3+Track 1+护栏 → 提交用户裁决落默认（一次一候选，按选臂规则）；
- 全 FAIL → 阴性结果如实登记（台账+语料），不硬上、不调线重跑；
- 任一臂 C1 过但 Track 1 < 0 → 按计划「saEx 盲区面大→Track 1 权重高」原则判不晋升。

## 四、实施与验证纪律

- **接线面**：`config.py` 新增 `tierSynergyResonanceDbuyMode`（含枚举校验入 `_validate_tier_constraints`）
  + `volume_price._synergy_tier` res 投票点分支（off 恒走原路径=零行为）。**须待 Q1 线收官后接线**
  （config.py 为 Q1 未提交改动文件；volume_price.py 在 Q1 trial 导入图，trial 中途不动引擎文件）。
- **测试纪律**：新开关默认 off 零行为=第一断言（三窗 saEx 逐位一致）；专项测试不触发真实模型调用；
  golden 快照预期零漂移（至多 configRepr 新增一行文本），重录+逐字段 diff 审查。
- **harness**：复用 `evaluate_voting_signals_t2.py` 骨架（load_frames 951 帧口径/B0 自证/护栏计数/
  sa_excess_of）新建 `evaluate_vote_w11_res_dbuy.py`（不触引擎文件）；Track 1 复用既有 track1 runner
  extra-arm 口径；res 迁移矩阵在 runner 内对照臂逐帧比对（baseline vs 臂的 res vote/synergy tier）。
- **成本**：3 replay（≈6 分钟/次）+ 2 Track 1 + 迁移矩阵复算，全本地 CPU，≈40 分钟墙钟，
  零 API 成本、零模型调用（AGENTS §1.2-7 合规）。
- **市况分桶**：market_regime pool 因子 state（strong/normal/weak/retreat），仅报告列不进判定线。
- **依赖声明**：无新数据链、无新集合、无新外部调用；帧投影字段与 T2 完全同源。
- **回退路径**：`tierSynergyResonanceDbuyMode="off"` 单开关回基线；晋升落默认后亦可以此回退。

## 五、流程

1. 本合同 → 用户过目（本轮）
2. → 外部模型审定（用户亲自投喂；输出归档 `vote-w11-res-dbuy-review.md`）
   **【登记 2026-10-07 深夜】用户裁决「请执行以上3项」开跑授权时未要求先走审定——按合同本节
   流程应为审定后开跑；用户明示简化=跳过外部模型审定直接开跑，在此登记（handoff 交付指示：
   「跳过则在合同登记『用户明示简化』，不阻塞」）。判定线/臂/算术仍以本合同冻结版为准，
   审定材料（本合同+D1 读数）随语料包 v2 归档备查。**
3. → 用户裁决开跑（授权覆盖=接线→专项测试→trial→判定→登记→提交；落默认仍须用户裁决）
4. 任何判定线修改=新合同版本重新走审定（跑后调线=违规）。

## 六、起草者自报风险（供审定攻击）

① 候选 b 弃权对「衰竭但真反弹」帧零票——D∧buy 帧的 h8 后验未测（若后验强正，弃权=丢真信号，
封顶臂是对冲形态）；② 6.6% 帧占比 × 单维票 Δ0.75/0.225，效应量预期小（C1 +3% 线可能不达），
阴性概率不低——本合同价值在证伪归档防重复立项；③ cap_b 读强度表 index 若强度表长度非法会走
fallback（0.7 硬值兜底），接线时须加长度断言；④ res 迁移矩阵只对 951 帧口径成立，落默认后
live 链语义一致性靠 golden+专项测试保证（G1 live 链接线教训）；⑤ 守门维护栏线（7185/64）为
半数粗线，非统计推导。
