# RankTrend 参数缺口补扫立项方案（六案，2026-09-15，对抗性审计修订 v2）

> 状态：**已实施完毕（2026-09-15 当日完成）**。六案执行结果固化于
> `ranktrend-longterm-backtest-plan.md` 阶段 26 与 L1 台账 §15：全部零默认值改动；
> 唯一观察池候选 vsB_070（Track 2 三卡全过 + Track 1 中性 +0.9%）；方法论主发现 =
> saEx 口径的 S/A 档统计集边界（B/C/D 迁移不可见，P1/P2/P3 三处实证），
> 交易层口径课题清单见长测计划 §26.8。本方案正文保留立项时口径，执行细节以阶段 26 为准。
> 来源：2026-09-15 对照
> `ranktrend-longterm-backtest-plan.md` 阶段 1-25 与 `backend/analysis/ranktrend/engine/config.py`
> 全量字段的缺口盘点（用户采纳）。六案各自独立立项、独立 harness、独立判定，
> 全程遵守 `skills/ranktrend-tier-longterm-test/SKILL.md` 8 步流程 + Track 2 判定卡 + Track 1 交易复核双纪律。
> 各案完成后按 skill 步骤 6 固化为长测计划阶段 26+，并同步 L1 台账。
>
> **v2（2026-09-15 对抗性审计修订）**：经三路只读核查（代码断言 / 长测计划交叉引用 /
> skill+台账+实施状态）后修订——P1-0 删除无效轴、P2-0 重写为消费面核实、P2-a 修正
> C 档注释并与阶段 25 提案显式协调、粗扫口径对齐 skill 5 档强制（用户确认）、harness
> 预检纪律补全。逐项对照见文末修订记录；审计期间核实为真的断言不再重复标注。

## 0. 总纲（六案共用纪律）

**基线锚**：每案 harness 首跑 baseline 三窗必须逐位复现 fund10 锚
（§25.7：decision 0.1120 / oos1 0.0880 / oos2 0.0951），不复现即停（配置漂移）。
历史监控对照值（§23.8 C 档 62.5%、§11.5 A 档样本 500、20.7%/3.6%、12-14% Jump 票占比等）
**均为 fund10 落默认（阶段 25）之前口径，各案首跑必须同批重测，不直接引用旧数**。

**窗口纪律**：decision 2026-04-15~07-31 / OOS-1 08-15~08-31 / OOS-2 09-01~09-12；
FINAL(08-01~08-14) 冻结（`assert_not_frozen` 守卫）。三窗权威定义在
`backend/operations/evaluate_ts_factor_weights.py:56-60`（`data_windows.py` 只承载
train/val/test/final 与冻结守卫）——**各新 harness 统一从该定义 import 或抽共享常量，
禁止各案复制日期字面量**。OOS-2 已被阶段 24/25 部分消费，各案结论标注"窗口已消费"
（M3 折扣，§25.6），最终裁决与 9 月全月复验（10 月上旬）同批。

**验收口径（双轨制，§19.3/§19.6）**：Track 2 判定卡 C1（decision saEx rel ≥ +3%）∧
C2（OOS ≥1 窗同向为正）∧ C3（passHard 不降）= PASS_CANDIDATE；C4（regime 四桶
降幅 ≤0.01）/ C5（veto/bd 翻转升幅 ≤+0.01）为附加卡。落默认前最后一步必须
Track 1 交易复核（rank_trend_candidate 默认交易配置，M2 样本量门槛 30 笔，
`track1_dimension_power.py` TRADE_COUNT_FLOOR）——e1a 教训：saEx 假阳候选由交易层
拦截（阶段 24 首例）。

**两轮制（§23.1 口径，5 档版）**：粗扫（**每参数单变量 5 档**含当前默认，对齐
SKILL.md 第 2 步强制口径与验收标准；§23.1 的 3 档粗筛先例不再沿用）→ 精扫（仅显著者：
剂量曲线 + 组合 + 判定卡）。结构性惰性（各档逐位一致）即收口（D-b ms 轴 /
§23.4 HighRiskPressureMin 形态）；**消费面核实先于扫描**：凡代码可证 signal-neutral
的参数直接按 §23.3 A 组 zero_effect 模式收口——代码消费面事实为主证据，对照 trial
仅作验证（P4-0/P5-0/E 强度三处已按此先行收口，见各案）。二值开关（如
requireMacdGoldenCross）不适用 5 档口径，1 组对照即可。

**扫描纪律**：全程零默认值改动、golden 不漂移；list 字段同步 `_STRATEGY_LIST_KEYS`
（已核对：buyThresholds/sellThresholds/tierSynergyVoteStrengths/momentumDirectionShareBoost/
momentumAccelShareBoost 均在白名单，search_space.py:266-282）；一次一候选落默认；
新参数化字段登记 L1 台账（逐项登记，不依赖 §12 的"~90 项"统括）。

**harness 预检纪律（各案通用，审计新增）**：
1. **list 长度断言**：`tierSynergyVoteStrengths` 必须 len==6——`_vote` 在长度不符时
   **静默回退旧硬编码 fallback**（volume_price.py:405-406），trial 会假绿且用的是旧值；
   buyThresholds/sellThresholds 保持 5 元素（from_patch 对 list 长度零校验，短 list 是
   运行期 IndexError、长 list 静默截断）；未来扫 `tierSynergyCsStrengths` 须 len==4。
2. **线序断言（P3 专用）**：from_patch 对 regime 三线与 risk Sell/Hold 顺序**无校验**，
   乱序 patch 在 elif 链静默退化不报错——P3 harness 必须断言
   `regimeStrongScore > regimeNormalScore > regimeWeakScore`、各族 `SellMin > HoldMin`。
3. **单变量拆分**：每个参数独立成轴，禁止两参数打包同一行（skill L31 明确"不是打包"）。

**推进顺序**：

| 批次 | 案 | 理由 |
|---|---|---|
| 第一批（可并行） | P4、P5、P6 | 最小/补漏/只读诊断先行，含多个"收口型"前置 |
| 第二批 | P1、P2 | 需前置参数化（P1-0）或消费面核实记录（P2-0） |
| 第三批 | P3 | 与 regime 分桶耦合最强，建议与 9 月全月复验（10 月上旬）同批 |

---

## 方案 P1：cs 档位定义阈值扫描（7 阈值 + 1 处硬编码参数化）

**缺口**：`crossSectionStrongMin(85)/StrongDeltaUp(5)/MidMin(50)/MidDeltaUp(15)/
MidMax(50)/MidDeltaDown(−15)/WeakMax(15)/WeakDeltaDown(−5)`（`trend/cross_section.py::_tier_from`
消费）阶段 10 设计值直接落默认，从未剂量扫描。cs 的 A 档可达性（§18 核心痛点；
参数名表述见 §10.2）与 C 档 62.5% 系统性负票流（§23.8）都由这组边界决定。

**P1-0 前置参数化（TDD）**：代码核查发现 `_tier_from` 另有一处硬编码绝对线——中位分支
`percentile >= 70 → B`（且首帧降级分支复用 70）。参数化为 `crossSectionStrongAbsMin(70.0)`
（默认=原值，golden 不漂移）+ 测试锚。list 字段无。
**审计修订（原拟的 `crossSectionWeakAbsMax(30.0)` 取消）**：`percentile <= 30` 为**无效轴**
——`<=30 → C` 与中位兜底分支同返回 C 档（cross_section.py:86-91），首帧分支亦然
（:95-99），任何取值只改 tierReasons 文案、不改 signalTier。按消费面核实直接归档
（归档记录进长测计划），**不参数化、不进扫描、不登记台账**。

**P1-a 粗扫**（37 trial × 3 窗，单变量 5 档，focus synergy + crossSection）：

| 参数 | 档位 |
|---|---|
| crossSectionStrongMin | 80 / 82.5 / **85** / 87.5 / 90 |
| crossSectionStrongDeltaUp | 3 / 4 / **5** / 6 / 8 |
| crossSectionMidMin | 40 / 45 / **50** / 55 / 60 |
| crossSectionMidDeltaUp | 10 / 12 / **15** / 20 / 25 |
| crossSectionMidMax | 40 / 45 / **50** / 55 / 60 |
| crossSectionMidDeltaDown | −10 / −12 / **−15** / −20 / −25 |
| crossSectionWeakMax | 10 / 12.5 / **15** / 17.5 / 20 |
| crossSectionWeakDeltaDown | −3 / −4 / **−5** / −6 / −8 |
| crossSectionStrongAbsMin（新） | 60 / 65 / **70** / 75 / 80 |

监控项（每 trial 必出）：cs 档位分布迁移（A/B/C/D 占比——A 档样本量对照 §11.5
触发线 500、C 档负票流体量对照 §23.8 基线 62.5%——**两者均 fund10 前口径，首跑重测**）、
S+A 触发率、C5 翻转率。

**P1-b 精扫**：显著参数组合，预期主轴 `StrongMin × StrongDeltaUp`（§18 数学边界
delta ≤ 100−pct 直接由这两参数决定，A 可达性杠杆）+ persist 路径交叉对照 1 组
（`crossSectionPersistFrames` 从默认 0=关闭 **置 3 开启**替代路径——trial 档位，非现值）。
判定卡 C1-C5 + Track 1 交易复核。

**收口**：现值即峰 → "已扫、现值最优"收口（§25.2 同款）；单调显著 → 判定卡；
档位分布剧变的档位（如 A 档塌缩或 C 档翻倍）即使 saEx 改善也标注结构代价。

**影响文件**：`trend/cross_section.py`（P1-0）+ `tests/test_cross_section*.py` +
新 harness `backend/operations/evaluate_cs_tier_thresholds.py` + 测试 + L1 台账
（StrongAbsMin 扫后登记）+ 长测计划（含 WeakAbsMax 无效轴归档记录）。

---

## 方案 P2：总档阈值阶梯标定（VoteStrengths 5 值 + Strong/Weak/Reverse 新语义复扫）

**缺口**：① `tierSynergyVoteStrengths [1.2,1.0,0.8,0.5,1.0,1.0]`（S/A/B/C/D/E 档位
强度）批 1 参数化后未扫描；② 总档三线 `tierSynergyVoteStrong(2.0)/Weak(1.0)/
Reverse(−1.0)` 的 §4.2 结论是**旧 vote 语义**（票取方向不取档位）下得出——且实为
**两线结论**（Strong 2→3 影响交易但变差、Reverse −1→0 改档位分布不影响交易；
`tierSynergyVoteWeak` 全文无任何记载，连旧语义都没扫过）。v4 档位加权 + cs 第 5 维 +
0.75 票权落地后三线均从未复扫。

**P2-0 前置消费面核实（只读；2026-09-15 审计已完成，记录在案）**：
- `tierSynergyVoteStrengths` 在 `_synergy_tier` 中**只乘 res/rank/vp 三票**
  （ranking/volume_price.py:415-418）；cs 票走独立映射 `tierSynergyCsStrengths`
  （:420-422，C/D 档为负票 −0.5/−1.0）；S/A/B 缩放不触及任何维度的 C/D/E 档票。
- **初稿的"数学等价"假设作废**：S/A/B 强度缩放 ≠ 三轴票权缩放（覆盖面不同：票权缩放
  包含 cs 全票与全部档位）；原 B2 式单对照对（×0.75 逐位一致即收口 S/A/B）一并删除
  ——单剂量点零效应不能判子轴冗余（§23.3 真实标准 = 代码消费面事实 + 多档逐位
  零效应；§23.4 decisionReversal* 反例：决策面参数 saEx 零效应 ≠ 冗余）。
- S/A/B/C/D 直接进 5 档粗扫；E 强度按消费面收口（见下表）。

**与阶段 25 平行方案的协调（审计新增）**：`ranktrend-dimension-trade-review-cs-strength-proposal.md`
（阶段 25 方案 A-D，2026-09-15 实施完成）已扫 `tierSynergyCsStrengths`（13 trial 全
OBSERVE、现值即峰收口），其 §3.1 以"阶段 23 钝感结论 + 阶梯为门控骨架"为由明确不动
三线。**本案复扫三线的依据显式接管该排除理由**：§4.2 两线结论出自旧 vote 语义，v4
档位加权 + cs 第 5 维 + 0.75 票权落地后未复扫（Weak 线更是从未扫过）——"钝感"结论
的语义前提已不成立。引用方案 B 结论时注意其 harness 锚为 23.9.1 旧基线
（0.1044/0.0918/0.0933），与本案 fund10 锚（0.1120/0.0880/0.0951）不同口径。

**P2-a 粗扫**（33 trial × 3 窗，单变量 5 档，focus synergy）：

| 参数 | 档位 |
|---|---|
| tierSynergyVoteStrong | 1.5 / 1.75 / **2.0** / 2.25 / 2.5 |
| tierSynergyVoteWeak | 0.5 / 0.75 / **1.0** / 1.25 / 1.5 |
| tierSynergyVoteReverse | −1.5 / −1.25 / **−1.0** / −0.75 / −0.5 |
| VoteStrengths[S] | 1.0 / 1.1 / **1.2** / 1.3 / 1.4 |
| VoteStrengths[A] | 0.8 / 0.9 / **1.0** / 1.1 / 1.2 |
| VoteStrengths[B] | 0.6 / 0.7 / **0.8** / 0.9 / 1.0 |
| VoteStrengths[C] | 0.0 / 0.25 / **0.5** / 0.75 / 1.0（res/rank/vp 三维 C 档票强度；**注意 cs 维 C 档负票流由 tierSynergyCsStrengths 决定**，已由阶段 25 方案 B 扫描收口 OBSERVE 现值即峰——旧锚口径） |
| VoteStrengths[D] | 0.5 / 0.75 / **1.0** / 1.25 / 1.5 |
| VoteStrengths[E] | **收口免扫**：hard 门早退（volume_price.py:383-389，仅 volumePriceGateMode=soft 消费），默认门形态下结构性惰性；登记"soft 模式时生效" |

约束：`reverse ≤ weak < strong` 由 from_patch fail-fast 兜底（config.py:511），harness
预检跳过非法组合；**VoteStrengths patch 必须 len==6**（否则 `_vote` 静默回退旧硬编码，
trial 假绿——见总纲预检纪律 1）。C=0.0 档为"关闭 res/rank/vp C 档票"剂量点，用于测
该三票 C 档净贡献方向。

监控：v_final 分布 vs A 线 2 的结构关系（§23.9 结构下限：三轴减权 ≤0.5 时
S/A 塌缩——强度/线位同属该结构面，防止单变量扫进塌缩区）。

**P2-b 精扫**：显著档位 × 线位 2 轴小网格 + 与现票权 0.75 组合的交互检查。
判定卡 + Track 1。

**预期与风险**：可能大范围"逐位一致"（强度变化不跨阈值线）——按结构性惰性收口
并**明确记录结构边界**（哪些档位强度在哪个线位组合下才活跃），本身就是 23.9
"结构下限"发现的补全；**但结论只写"当前线位/票权配置下不活跃"，不引申"子轴冗余"**
（§23.3/§23.4 口径）。

**影响文件**：新 harness `evaluate_synergy_tier_thresholds.py` + 测试 + L1 台账
（三线扫后逐项登记）+ 长测计划。

---

## 方案 P3：regime/risk 核心线位扫描（8+1 线位，批 3 的阈值比较面）

**缺口**：批 3 区域（config.py:192-251：risk 阶梯 34 项 + regime 打分 23 项 = 57 项，
2026-09-14 参数化；初稿"55 项"为近似，长测计划无此清点编号）未扫描。
**范围控制：不扫全量**——slope/cap/weights 属分值幅度面（C-b 经验：×正缩放不改
符号/阈值比较，预期冗余），本轮只扫**阈值比较面** 8 线位：`regimeStrongScore(70)/
NormalScore(50)/WeakScore(30)`、`riskOverheatSellMin(70)/HoldMin(45)`、
`riskDivergenceSellMin(65)/HoldMin(40)`、`riskSynergyOverheatSevMin(0.65)`
（div_sev `riskSynergyDivergenceSevMin(0.6)` 视粗扫活跃度补）。

**P3-0 前置活跃度诊断（只读，可能砍掉大半扫描）**：
1. regime 三线 ±10 扰动下四态分布迁移（信号级 state 计数 + 档位迁移量）——
   若某线移动 <1% 档位赋值（§12.3 α 平滑同款钝感形态；判据与读数留痕备查），
   判惰性免扫；
2. riskOverheatSellMin/HoldMin、riskDivergenceSellMin/HoldMin、riskSynergy 双门的
   触发率现状——**基本不触发**的门判结构性惰性（§23.4 HighRiskPressureMin 0.75
   形态；注意原文口径：pressure 分支是唯一活跃 veto 路径、×0.5 有读数，非"从不
   触发"），扫描免跑；并按 §23.7 登记**重扫触发条件**（门因 risk 链改动变活跃即重扫）。

**P3-a 粗扫**（活跃线位各 5 档；9 线位全活跃上限 37 trial，P3-0 砍后预期 ≤25）：

| 参数 | 档位 |
|---|---|
| regimeStrongScore | 60 / 65 / **70** / 75 / 80 |
| regimeNormalScore | 30 / 40 / **50** / 60 / 70（70 与 Strong 默认相切：单变量不违序） |
| regimeWeakScore | 10 / 20 / **30** / 40 / 50（50 与 Normal 默认相切，同上） |
| riskOverheatSellMin | 50 / 60 / **70** / 80 / 90 |
| riskOverheatHoldMin | 25 / 35 / **45** / 55 / 65 |
| riskDivergenceSellMin | 45 / 55 / **65** / 75 / 85 |
| riskDivergenceHoldMin | 20 / 30 / **40** / 50 / 60 |
| riskSynergyOverheatSevMin | 0.45 / 0.55 / **0.65** / 0.75 / 0.85 |
| riskSynergyDivergenceSevMin（视活跃度补） | 0.4 / 0.5 / **0.6** / 0.7 / 0.8 |

约束（审计新增）：from_patch 对 regime 三线与 risk Sell/Hold 顺序**无校验**（config.py
仅校验 tierSynergy 系）——harness 预检断言 `StrongScore > NormalScore > WeakScore`、
各族 `SellMin > HoldMin`；相切档位进入 P3-b 组合前重新断言。

**特别监控（本案例独有）**：strong 线移动直接改变 strong 桶的边界与样本量——
阶段 14 已证 strong 双峰（塌陷/强劲并存），线位移动会重新划分两峰；且 strong
禁入门（banStrongA/B=True）的禁入面随线移动放大/缩小。每 trial 必出 regimeView
分状态视图（阶段 16 基建）+ 禁入触发率。

**P3-b 精扫**：显著线位剂量曲线 + 四桶不恶化 + 判定卡 + Track 1。

**关联课题**：本案例 serve P4 分状态门控（§14.4 后续课题）的前置标定——若
strong 线位移动能分离塌陷/强劲 strong，产出直接喂给该课题的设计评审。

**影响文件**：新 harness `evaluate_regime_risk_thresholds.py` + 测试 + L1 台账
（线位未逐项登记，扫后逐项补登记）+ 长测计划。

---

## 方案 P4：vp 欠账（amountRatio 3 参数）

**缺口**：G3 成交额量比三参数 `amountRatioPeriod(5)/High(1.5)/Low(0.5)`
（`ranking/volume_price.py:233-238/273` 消费）2026-08-18 落地，§9.2 扫描在其之前，
从未覆盖。

**P4-0 前置诊断（一步只读）**：amountRatio 生效率重测（G3 落地时可算 20.7%/增强生效
3.6%，fund10 前口径）——若现数据窗口重测可算率仍 <30%，粗扫照跑但结论标注低杠杆。

**P4-1 前置收口（审计升级：原"疑似"已由代码核实证实，2026-09-15）**：
`synergyLowVp(40)/synergyHighVp(75)`（volume_price.py:556-557 消费）的消费链已核实：
`compute_synergy_state` 仅产 `observation.synergy`（hardWarn 全后端**零消费方**，
仅 runtime.py:1397 展示标注与 gate_flip_stats 研统计读取）；`risk["synergy"]` 双门来自
`analyze_risk` 独立 severity 合成（risk.py:67，该门经 decisionRiskPenaltyWeights 进
决策面、活跃）——与 compute_synergy_state 不同源。**按 §23.3 A 组 zero_effect 模式
以代码消费面事实直接收口**（代码事实为主证据），不进剂量扫描、无需对照 trial；
收口记录（含代码证据行号）进长测计划。

**P4-a 粗扫**（13 trial × 3 窗，单变量 5 档，focus synergy + volumePrice）：
amountRatioPeriod 2/3/**5**/8/13、amountRatioHigh 1.1/1.3/**1.5**/2.0/2.5、
amountRatioLow 0.2/0.35/**0.5**/0.65/0.8。

**P4-b 精扫**：显著者 + 判定卡 + Track 1。注意新基线已含 fund10（§25.7），
本扫描即在其上，无需再对照旧基线。

**影响文件**：新 harness `evaluate_vp_amount_ratio.py` + 测试 + L1 台账 + 长测计划
（含 P4-1 收口记录）。

---

## 方案 P5：趋势漏网（buyThresholds/sellThresholds + 5 momentum 参数 + requireMacdGoldenCross）

**缺口**：① `buyThresholds/sellThresholds`（[5,8,13,21,34] 负镜像；`trend/technical.py:211-217/
239-241` 消费——**tanh 归一化尺度**：`tanh(value/abs(threshold))` 与 `normalize_signed`，
不是"buy/sell 触发线"；效应为连续幅度面，会改变下游 momentumScoreThreshold 的比较
输入）长测主链从未扫描，§13 审计清点漏列（§13 清的是决策层
buyScoreThreshold/sellScoreThreshold，与此不同名，勿混淆）；
② §8.4 参数化 18 项但 5 档表只扫 8 项（本节另漏 10 项，其中 5 项已由 §13 补扫：
死叉侧 deathScale/deathStrong/rawW、zeroCross zeroW/bonus），剩 5 项漏网即
`momentumLongAgreeThreshold(0.15)/momentumDirectionShareBoost([0.5,0.5])/
momentumAccelShareBoost([0.7,0.3])/momentumScoreThreshold(35)/momentumConfidenceSlope(0.45)`；
③ `requireMacdGoldenCross`（默认 False；runtime.py:299 消费）从未作为开关 trial 评估。

**P5-0 前置收口与消费面核实**：
- `momentumConfidenceSlope`（technical.py:220 仅进 momentum_data 的 confidence 键）
  ——**审计已确认该 confidence 键全后端零读取方**（dead output，比"confidence-only"
  更强）：按 §23.3 A 组以代码事实直接收口，不进扫描、无需对照 trial；
- `momentumDirectionShareBoost/AccelShareBoost` 消费面已核实（technical.py:245-246/
  261-262）：乘性位置 `raw × (b0 + b1×share)`，份额和=1，乘子范围 [b0, 1]——按份额
  比例设计档位（见下表）；
- 可选（TDD）：为 from_patch 补 buyThresholds/sellThresholds 长度=5 守卫
  （当前零校验，短 list 运行期 IndexError、长 list 静默截断）。

**P5-a 粗扫**（23 trial × 3 窗）：

| 参数 | 档位 |
|---|---|
| buyThresholds/sellThresholds（list 镜像同步缩放，各档独立 trial） | ×0.5 / ×0.75 / **×1.0** / ×1.25 / ×1.5 + 快半档 [3,5,8,13,21] 对照 |
| momentumLongAgreeThreshold | 0.05 / 0.10 / **0.15** / 0.20 / 0.25 |
| momentumScoreThreshold | 25 / 30 / **35** / 40 / 45 |
| momentumDirectionShareBoost | [0.3,0.7] / [0.4,0.6] / **[0.5,0.5]** / [0.6,0.4] / [0.7,0.3] |
| momentumAccelShareBoost | [0.5,0.5] / [0.6,0.4] / **[0.7,0.3]** / [0.8,0.2] / [0.9,0.1] |
| requireMacdGoldenCross | **False** / True（二值开关，1 对照，不适用 5 档口径） |

约束：buyThresholds/sellThresholds 与 momentumPeriods 按 index 对齐，扫描保持
5 元素长度不变（from_patch 零校验，越界风险见总纲预检纪律 1）；负值侧镜像同步缩放；
浮点档位（×0.5 → [2.5,4,6.5,10.5,17]）在 tanh 尺度语义下合法。

**P5-b 精扫**：显著者 + 与已落默认 p2 五权重的交互 1 组 + 判定卡 + Track 1。

**先验提示（审计修正）**：§8.4 已证 **direction 侧**阈值默认最优（方向阈值 0.2、
LongOppose 0.25 默认最优）；**accel 侧恰相反**——momentumAccelThreshold 0.26 是
唯一单调显著档，靠 §8.5 样本外否决才维持默认 0.18（"未被替换"≠"被证明最优"）。
本案对 accel 侧先验取**中性**，防"现值即峰"预期污染解读；buyThresholds/
sellThresholds 为 tanh 尺度参数（连续幅度面），预期**剂量曲线**而非结构性惰性——
是本案例唯一全新语义面。

**影响文件**：新 harness `evaluate_trend_leftover_parameters.py` + 测试 + L1 台账
（5 参数扫后逐项登记）+ 长测计划（含 momentumConfidenceSlope 收口记录）。

---

## 方案 P6：ATR + Jump 确认（因子级验证，four-dim-algorithm-research 口径）

**性质声明**：不是调参案——ATR 是"观察因子信息量从未验证"（阶段 10 crossSection
同款流程：先区分度、后谈参数）；Jump 确认是"设计值从未复验"（D-a 推翻
"Jump 事件为 0 无影响"旧口径后，确认阈值面需要重看）。本案例不触发 Track 1
交易复核（不进投票、无落默认候选时），判定按观察因子标准。

**P6-a ATR 区分度验证（只读）**：
1. **数据可用性先行**（skill 教训 6，SKILL.md L122）：`atrAggregateByDay=False`
   逐帧口径下 high/low 覆盖率重测——曾因 high/low 缺失 28% 使 ATR 全 unknown；
   unknown >50% → 判"数据不足"收口，不调参；
2. 区分度验证：`research/tier_monotonicity.py` DIMENSION_PATHS 已含 atr（:29）——
   ATR 档位分布 + h1 exAcc + A 档样本门槛（阶段 10 口径：exAcc 正 + 样本 ≥ 门槛）。

**P6-b ATR 参数扫描（仅当 P6-a 有区分度）**：单变量 5 档——`atrChannelK
1.5/1.75/**2.0**/2.25/2.5`、`atrDeepDeviation 2.0/2.5/**3.0**/3.5/4.0`、
`atrRefPeriod 10/15/**20**/25/30`；判定按观察因子标准（不进投票，vote 维度不新增），
若区分度显著再按 four-dim-algorithm-research 走"是否进投票"的数据驱动决策。

**P6-c Jump 确认阈值**：两单轴各 5 档（`jumpConfirmChangeMin 1/2/**3**/4/5` ×
`jumpConfirmVolumeRatioMin 0.6/0.8/**1.0**/1.25/1.5`；4+4+1 = **9 trial × 3 窗**，
交互组合留精扫）+ unconfirmed 降级率监控（G4 语义：runtime.py:208-252，不满足降
hold+unconfirmed、事件保留不删）；对照 D-a 的 Jump 票占比 12-14% 基线
（**fund10 前口径，首跑重测**），验证确认阈值松紧对 res 维方向票质量的影响。

> **执行后记（2026-09-15）**：P6-c smoke 首跑发现确认门消费面断线（生产枚举 buy/sell
> 不在 up/down 匹配内，10936 事件全放行，详见长测计划 §26.7 / L1 §15.6），两轴扫描
> zero_effect 收口。**当日用户决策"请修复"**：`_confirm_jump` 已改按生产枚举 buy/sell
> 匹配（TDD 全程，影响面 130 测试全绿），G4 门真实生效；jumpConfirm 两参 5 档扫描在
> 修复后代际重新立项（与 9 月全月复验同批评估）。

**影响文件**：只读诊断脚本 `diagnose_atr_discrimination.py` + 新 harness
`evaluate_jump_confirm_parameters.py` + 测试 + L1 台账（atr 三参未逐项登记，扫后补登记）
+ 长测计划。

---

## 0.1 未决问题

1. **P3-0 活跃度诊断**可能砍掉 risk 侧大半线位（惰性收口，按 §23.7 登记重扫触发）；
2. **P6-a 数据可用性**决定 ATR 案是否直接收口；
3. **三线复扫与阶段 25 提案立场**：P2 协调段已显式接管"阶段 23 钝感"排除理由
   （旧语义前提不成立）；若用户最终认可提案立场（维持不复扫），砍 P2 三线 3 行、
   只扫 VoteStrengths 5 值（33→21 trial）；
4. 全部 PASS_CANDIDATE 的落默认裁决与 9 月全月复验（23.9.1 / §25.6 挂起项）同批
   （10 月上旬），避免多候选叠加污染归因；
5. OOS-2 窗口消费折扣（M3）：各案结论仅作方向证据，最终裁决窗用 09-13 之后未消费帧；
6. P2-a 若三窗大范围逐位一致，按结构性惰性收口并记录结构边界，**结论限定"当前
   线位/票权配置下不活跃"**，不引申"子轴冗余"。

---

## 修订记录（2026-09-15 对抗性审计，v1 → v2）

审计方式：三路只读核查（代码断言 / `ranktrend-longterm-backtest-plan.md` 交叉引用 /
skill+L1 台账+实施状态），未修改任何代码；本文件为本次任务唯一改动。
事实断言核查结果：30+ 项参数名/默认值/行号/锚值/窗口/代号引用全部属实，"未实施"属实。

| 项 | 审计结论 | 本版修订 |
|---|---|---|
| I-1 | `crossSectionWeakAbsMax(30)` 为无效轴：≤30 与中位兜底分支同返回 C 档，仅 tierReasons 文案不同（cross_section.py:86-91/95-99），任何取值不改 signalTier | P1-0 只参数化 StrongAbsMin(70)；WeakAbsMax 取消参数化/扫描/台账，无效轴归档记录进长测计划 |
| I-2 | P2-0"数学等价"不成立：Strengths 只乘 res/rank/vp 三票（volume_price.py:415-418），cs 票走独立 CsStrengths 映射（:420-422），C/D/E 档票不随 S/A/B 缩放；单对照对收口越权（§23.3 真实标准 = 消费面事实 + 多档零效应；§23.4 decisionReversal* 反例） | P2-0 重写为消费面核实记录；删除 B2 式对照对；S/A/B/C/D 直接进 5 档粗扫；结论口径限定 |
| I-3 | P2-a `VoteStrengths[C]` 注释误导：§23.8 的 cs C 档负票流主体是 `tierSynergyCsStrengths[C]=−0.5`，非 VoteStrengths[C]；与阶段 25 提案（已扫 CsStrengths、明确不动三线）零协调，且其锚为 23.9.1 旧基线 | C 行注释修正；新增"与阶段 25 平行方案的协调"段（含接管理由与旧锚警示）；未决问题 3 登记 |
| I-4 | SKILL.md 强制每参数 5 档单变量（L31+L105），原案多数轴 3 档且 D/E 打包 | **用户确认对齐 5 档**：全部粗扫轴补足 5 档；D/E 拆行；E 强度按消费面收口（hard 门早退惰性）；二值开关豁免 |
| M-1 | from_patch 无 regime 三线/risk Sell-Hold 顺序校验，乱序静默退化；§23.4 原文为"基本不触发"非"从不触发" | P3 新增线序预检断言；P3-0 措辞收敛 + §23.7 重扫触发登记 |
| M-2 | buyThresholds/sellThresholds 为 tanh 归一化尺度，非"触发线" | P5 缺口语义修正 + 剂量曲线预期 |
| M-3 | "§8.4 已证 direction/accel 默认最优"的 accel 半句不实（0.26 显著、靠样本外否决维持默认） | P5 先验提示修正，accel 侧取中性 |
| M-4 | 历史监控对照值（62.5%/500/20.7%/3.6%/12-14%）均为 fund10 前口径 | 总纲新增"首跑同批重测"纪律，各案标注 |
| M-5 | P6 影响文件缺 L1 台账；三线/regime/risk 线位/atr 三参未逐项登记 | P6 补 L1 台账；总纲"逐项登记、不依赖统括" |
| M-6 | P6-c trial 数算术不清（~7 对不上单变量 5 或全网格 9） | 改两单轴各 5 档 = 9 trial，交互留精扫 |
| M-7 | 三窗权威定义在 evaluate_ts_factor_weights.py:56-60（非 data_windows.py）；"批 3 55 项"实为 config.py:192-251 共 57 项且长测计划无此编号；persist 默认 0=关闭；volume_price.py 在 ranking/ 下；§4.2 仅两线结论 | 总纲补出处 + 禁止复制日期字面量；P3 计数修正；P1-b 表述修正；路径补全；P2 缺口 ② 改两线表述 |
| 加固 | `_vote` 在 len(strengths)!=6 时静默回退旧硬编码 fallback（volume_price.py:405-406），trial 假绿 | 总纲 harness 预检纪律 1 + P2 约束显式化 |
| 顺势收口 | 审计代码核实：synergyLowVp/HighVp 消费链为 observation-face（hardWarn 零消费方、risk["synergy"] 不同源且活跃）；momentumConfidenceSlope 的 confidence 键全后端零读取方 | P4-1 / P5-0 升级为代码事实直接收口，省对照 trial |

**残留风险**：① 各案 trial 预算按 5 档口径上浮（P1 37 / P2 33 / P3 ≤37、P3-0 砍后
预期 ≤25 / P4 13 / P5 23 / P6-c 9），实施时以 P3-0/P6-a 只读诊断先行控总量；
② 本方案的 §23.8/§11.5 等历史读数引用需在首跑重测后才能作为监控对照；
③ 与阶段 25 提案的"三线复扫 vs 维持钝感"立场分歧待用户最终裁决（未决问题 3）。
