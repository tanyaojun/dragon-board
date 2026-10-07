# 四投票信号语料 · 模型A 第二轮输出逐字归档（2026-10-07，用户执行投喂）

**投喂**：同会话续贴 `voting-signals-modelA-round2-prompt.md` 第二轮 user 消息（含 R1 读数）。
**审定**：见 `reasoning-corpus-voting-signals.md` §12.2（结论：通过零硬幻觉；6 项审定修正跑前冻结）。

---

> 接收三项勘误并纳入设计：① **vp 无 S / 真实上限 3.55 / cs 正票是 S 结构守门（127/127 实证）**——该事实直接进入 T2 的 S 供给护栏、T4 正态的 S 解锁通道、T5b 的量级评估；② 我的 [0.69, 0.83] 区间端点复核：0.83（无 cs 组合）成立，0.69 实为 **cs B** 组合下限，含 cs A 的组合下限应为 ≈0.59——已按勘误修正，不再沿用旧标注；③ E11 口径修正：cs 末对跨日 12.5% ≈ 日帧基率（1/10），即跨日 delta 恰好落在「每日首帧」人群上、**无超比例污染**——T1 的 A1 臂预期受影响面 ≈ 日首帧人群，考题从「污染是否普遍」收窄为「隔夜 delta 的方向后验是否劣于日内 delta」。

---

# 共享基建（五案公用，任何行为步之前先跑）

**B0 基线步（每案门判据的第一步）**：当日跑同代际（G1 落默认后）全窗 replay 一次 + Track 1 基线一次，产出绝对锚（三窗 saEx、per-dim excess、tier 分布、Track 1 wrxpf/笔数），登记 config_hash。五案相对线全部挂 B0；语料旧绝对锚（含 N1）一律只作方向先验（§4.4 代际纪律）。

**D1 合并诊断 pass**：扩展 `diagnose_voting_signals_exposure.py` 一次跑 951 帧（R1 参照 159s），承载 T1/T3/T4/T5 全部前置读数。统一 schema：

```
主表（stock-frame 级，在 R1 输出上加列）：
  frame_index, code, trading_date, slot_time,
  regime_bucket,                      # R1 meta regime 列；二分映射见依赖①
  len_bucket ∈ {len1, len2_3, len4_8, len9_21, len22p},
  fallback_frame(bool),               # len<22
  dual_mom_disagree(bool),            # profile.composite 与 momentumScore 符号不一致（E3 口径）
  res_status, res_tier, res_direction, rank_tier, rank_direction,
  cs_tier, vp_tier, vp_direction, synergy_tier,      # 基线档
  h8_ret_8f, h8_sign,                 # 沿用 harness 现行实现（§7-3 缺口，不重定义）
  # T1 分层长表行（dim×feature 展开）：
  feature ∈ {cs_delta_last, res_short, rank_p3, rank_p5, rank_p8, rank_p13, rank_p21,
             res_mid, res_path, macd_raw, ma_diff},
  trigger ∈ {cross_day, same_day_gap, same_day_adjacent},   # R1 diff 端点异日语义
  feature_value, tier_consumes(bool),
  # T3：
  warming_eligible(bool: len4_8 ∧ res insufficient ∧ market_ctx_ok), market_ctx_ok(bool),
  warming_sim{direction, tier_cap, vote, synergy_tier_sim, crossed_B(bool), crossed_A(bool)},
  # T4：persist_eligible_n3/n5/n10（已有列）, persist_stratum ∈ {eligible_n5, B_not_eligible, other},
  # T5：new_entry(bool), entry_pct, entry_strength, chg, vr,
  confirm_pass_v10/v125/v150(bool), would_be_S_b1(bool), would_be_S_b2(bool),
  len1_rank_tier, len1_rank_vote     # 实测替代读码（§2.2 截断）

jump 事件表（R1 已有，加列）：
  trigger_type ∈ {cross_day, same_day}, h8_outcome,
  confirm_pass_v10/v125/v150, chg_bucket, vr_bucket

聚合视图：dim×feature×trigger×regime → {n, h8_excess_mean}；各 arm 的 baseline→arm tier 迁移矩阵
```

**oos1/8 月冻结的合同级预注册**：C2 主判定线统一取 **oos2**；oos1 全部读数照登、不作 gate（保守执行冻结纪律；若主会话追认 oos1 可 gate，按原判定卡重评——见依赖③）。

**统一纪律**：全部行为改动 config 默认=原值/off、一次一候选、不自动写回默认（§5-1）；五案全部带 Track 1（均涉 B/C/D 迁移或入场档位，saEx 盲区 §4.3-4）；本文全部为待验证假设，不构成改动授权。

---

# T1 四维时间正规化（L2，第一优先）

**1. 考题**：注意力序列的隔夜分量对方向判据是净噪声还是净信号——按相邻差分类（跨日对置 NaN+标记 / 同日重基）与长窗类（隔夜剔除调整序列）分别隔离后，受影响帧的方向后验与交易层结果是否优于现状？

**2. 门判据**（第一步=B0 定锚）：
- **假设验证线（monitor 线）**：受影响帧子集（该 arm 下 tier 或 direction 翻转的帧）arm 口径 h8 excess − 基线同帧 h8 excess ≥ **+0.03**；
- **落默认候选线**：C1（decision saEx rel ≥+3%）∧ C2（oos2 同向正；oos1 照登）∧ C3（passHard 不降）；
- **no-regression**：全窗 saEx ≥−1%；res 参与率 ≥55%（基线 67%，A2/B2 臂适用）；Track 1 wrxpf rel ≥0（**必带**：A1 臂产生 C↔B 迁移、A2/B2 产生 unknown 与 B/C/D 迁移，全部在 saEx 盲区）；
- **终止**：passHard 任窗崩；res 参与率 <55%；Track 1 wrxpf <−5%；
- **归档路径**（非终止）：受影响子集 |差|<0.01 且翻转率 <1% → 该 arm 无效应归档。

**3. 窗口与数据**：decision/oos1/oos2 三窗 + 951 帧全窗（D1 与 arm replay 同覆盖）；不另加窗。

**4. 诊断步 schema**：D1 长表行 `feature×trigger` + 聚合视图 `h8_excess_mean`（按 regime 分列）；前置结论表=本轮 R1 已出（跨日占比矩阵），D1 补的是**各 trigger 层的 h8 后验分层**与 fallback/dual_mom_disagree 两个混淆分层列。诊断步先于行为步出报告：若 cross_day 层 h8 不劣于 same_day 层（差 ≥−0.01），对应 arm 降级为 monitor_only（隔夜是信号的证据）。

**5. 行为改动步 trial 设计**（单变量=各自的正规化规则，一次一候选，顺序执行）：

| 臂 | 对象 | 改法（伪判据） | 理由 |
|---|---|---|---|
| A1 | cs delta（12.5%） | `if last_pair.cross_day: delta=None; tag temporalGap` → 走既有绝对档分支 | G1 模式直接移植；受影响面≈日首帧人群（基率口径） |
| A2 | res short（34.0%） | 同日重基：`short_change = p[-1] − p[j]`，j=3 偏移窗内最近同日元素；无同日对（日首帧）→ NaN+tag → resonance insufficient | 纯 NaN 会咬掉 34% 覆盖（与 H1 在场价值冲突），重基把损失压到日首帧 |
| B1 | rank 动量 p5/p8/p13/p21 | 调整序列 `p_adj[t]=p_adj[t-1]+same_day_diff(t)`（隔夜差分记 0，累计平移剔除），动量在 p_adj 上重算；**两档顺序剂量**：B1a 仅 p5/p8（名义日内窗、54.6%/81.0% 意外跨日）→ B1b 全周期 [3,5,8,13,21]（p13/p21≈1.3-2.1 日动量，隔夜是否计入即考题本身） | 选型论证见下 |
| B2 | res mid + res path + MACD/MA | res mid 同调整序列口径（窗口内同日累计差分；日首帧无同日对→mid NaN→acceleration 记 0+tag）；res path 的 changes 列表**剔除隔夜对**（分子分母同剔）；MACD/MA 的 EMA 在 p_adj 上重算 | 补全覆盖；MACD 族钝感先验（<±0.25%，§4.2 趋势①）预期效应小 |

**长窗类选型论证**（任务要求三选一）：选**隔夜剔除（调整序列）**，弃另两者——①按日边界拆分重算使同名义偏移的真实时距随时段漂移（日首帧与日尾帧同参数不同跨度），引入新的时距不均匀，治一病生一病；②日级聚合摧毁 MACD/MA 结构（50 帧窗≈5 交易日，EMA 13/21 在日级无意义）且丢弃全部盘中粒度，实为 L3 重设计非正规化；③隔夜剔除保持偏移/阈值/档位结构不变，**隔夜分量是唯一被隔离的变量**，与单变量纪律和归因可达性一致。fallback 帧（36.5%）无差分结构、天然不在干预面；dual_mom_disagree 作分层列不干预（18% 分歧面另案）。

**6. 回退与开关**：`crossDayDiffPolicy` 单 config（默认 `"off"`=原行为），各臂取值 `cs_nan`/`res_short_sameday`/`momentum_overnight_strip`/`long_ema_strip`；回退=置 off。

**7. 成本**：B0（共享）+ D1（共享）+ 5 个行为运行 ×（replay+Track 1）≈ **10 当量**，分钟级/次。

**8. 复用 harness**：`diagnose_lifecycle_scale_gap.py`（tradingDate/slotTime 配对 + temporalGap 语义，A1/A2 标记基建）；`diagnose_voting_signals_exposure.py`（D1 扩展）；`evaluate_dimension_voting_power.py`（arm 后 per-dim excess）；`track1_dimension_power.py`（Track 1）。**新写**：引擎内三个策略分支与 p_adj 构造（config 开关），harness 侧无新框架。

**9. 依赖声明**：①same_day_gap（同日非相邻 14.4%）**不在本轮干预面**（边界预注册，只分层）；②h8 公式沿用现行实现（§7-3）；③regime 二分映射未定前分桶读数空缺、不 gate；④「跨日是噪声」是待证假设，R1 占比读数不预设方向。

**10. 市况分桶**：强情绪期隔夜延续多→隔夜分量含真信号→剔除预期持平或略损；退潮期隔夜断裂多→预期增益集中（P3 类比）。分桶验证：全部门判据读数按 regime_bucket 分列；预注册裁决规则：**两桶同向→全局候选；反向→挂起并出适用域声明，不做 regime 条件开票**（避免新增拟合面、撞 hard 为峰先验 §4.2 汇合面③）。

---

# T2 jumpConfirm 剂量（R3）

**1. 考题**：确认门 vr 轴 1.0→1.25/1.5 收紧后，放行 jump 事件的方向质量与 S 档纯度是否单调提升，且 S 供给（res S 9.5%、synergy S 127 帧）仍在可判区间？

**2. 门判据**（第一步=B0 定锚；N1 为 B-202610 代际方向先验，不作锚）：
- **主判定线**：C1（decision saEx rel ≥+3%）∧ C2（oos2 同向正）∧ C3（passHard 不降）；
- **S 纯度线**：arm res-S 子集 h8 excess ≥ 基线 res-S −0.01；
- **no-regression**：Track 1 wrxpf rel ≥0（终判；S/A 是入场门票，直接影响入场池）；jump 放行率下降幅度只登记不 gate（预期 ↓）；
- **护栏（升档条件，非目标）**：res S 帧 ≥7,157（=14,314×50%，decision 口径）∧ synergy S ≥64 帧 ∧ Track 1 S/A ≥30 笔（M2）；**1.25 过护栏才跑 1.5**（护栏崩则 1.5 必然更差，终止升档，1.25 转 monitor_only）；
- **终止**：passHard 任窗崩；Track 1 wrxpf <−5%。

**3. 窗口与数据**：三窗+951 全窗；oos1 照登不 gate（共享预注册）。

**4. 诊断步 schema**：D1 jump 表加列 `confirm_pass_v125/v150, chg_bucket, vr_bucket, trigger_type, h8_outcome`；聚合：放行集按 vr_bucket 的 h8 单调性、chg 轴假阴性（fail_chg_only 31,196 桶）的 trigger_type 分布。

**5. 行为改动步**：单轴两候选，`jumpConfirmVolumeRatioMin` 1.0→{1.25 → 1.5}，一次一候选，顺序执行（升档受护栏门控，不受 C1 门控——1.25 保护栏但失 C1 时 1.5 仍可跑）。**chg 轴本轮不开**，洗掉「不干净」的预注册判据（D1 落数）：① fail_chg_only 桶的 h8 劣质若集中在 cross_day 触发事件（时间口径伪影），且 T1 落地后伪影消除→chg 轴可另立合同；② vr 通过事件的 chg 剂量-h8 无单调→chg 无剂量信息，永久关闭。两读数齐前 chg 轴挂起（N1「不干净」+ fail_chg_only 是最大单一桶 29.7% 的矛盾由这两列裁决，不猜）。

**6. 回退与开关**：config 单值回 1.0。

**7. 成本**：2 候选 ×（replay+Track 1）= **4 当量**。

**8. 复用 harness**：`diagnose_voting_signals_exposure.py`（jump 表扩展）；`evaluate_dimension_voting_power.py`；`track1_dimension_power.py`。缺：无（该参数历史上已有同类 trial 管道，§15.6/§16）。

**9. 依赖声明**：①N1 代际（先验不作锚）；②oos1 gate 资格（共享预注册③）；③若 T1 先落默认且 jump 事件 trigger 语义变化，B0 需重跑（顺序声明：T2 排 T1 后或各自独立代际）。

**10. 市况分桶**：量能轴教训（9 月有效 8 月失效，§4.4）——强情绪期 vr 普遍高→门近全开、两剂量差异小；退潮期 vr 低→门收紧最狠、护栏最先在退潮期触发。预期增益与护栏风险都集中在退潮期，分桶读数以退潮期为第一视图；两桶反向→挂起（同 T1 规则）。

---

# T3 共振 warming 补票（R4）

**1. 考题**：len∈[4,8] 共振缺票帧（len2-8 实测 16.2%，[4,8] 精确占比待 D1）是信息空洞还是正确弃权——以同日最低差分+市场基准化补票（档位上限 B、只投非负票、默认 off）后，warming 子集方向后验与 Track 1 wrxpf 是否不劣于基线？

**2. 门判据**（第一步=B0）：
- **假设验证线**：warming 子集（arm 给票帧）方向 h8 excess **>0**（新票必须优于随机方向）；
- **落默认候选线**：C1 ∧ C2（oos2）∧ C3 + Track 1 wrxpf rel ≥0；
- **no-regression**：全窗 saEx ≥−1%；基线 S/A 帧合并 h8 ≥基线−0.01（防 B 档堆积稀释 S/A 构成）；res 参与率变化只登记（预期 67%→约 75-83%）；
- **终止**：W1 warming h8 ≤0 → 假设证伪，W2 取消；Track 1 wrxpf <−5%；passHard 崩。

**3. 窗口与数据**：三窗+951 全窗。

**4. 诊断步 schema**：D1 列 `warming_eligible, market_ctx_ok, warming_sim{direction, tier_cap, vote, synergy_tier_sim, crossed_B, crossed_A}`；聚合：len_bucket×regime → {n, warming_h8_excess, crossed_B_rate, crossed_A_rate}。**前置读数**：[4,8] 占比与 warming 帧 market_ctx 可用率——低于 3% 或可用率 <80% 则重议（不猜数）。

**5. 行为改动步**（沿用 P4 骨架 + 两处保守化）：
- 判据：`len∈[4,8] ∧ market_ctx_ok：short_change=同日子窗差分（与 T1-A2 同口径，自洽不依赖其裁决）；relative_momentum=(short_change−market_median_short_change)/scale；direction 按 base 阈值；tier：buy→cap 档，hold/sell→C 票 0（**短窗不做负向票**——负向证据弱，且出场 D 线已由 vp D −1.0 主导，避免短窗负票污染出场通道）；historyState="warming"`；
- 剂量（单变量=warming 开关，cap 为剂量，顺序执行）：**W1 cap C（票 +0.375）→ W2 cap B（票 +0.525）**；W2 仅在 W1 过假设验证线后跑（剂量响应）；len∈[2,3] 维持 insufficient（单帧差分与 cs delta 同源，无增量——跨维冗余 1）。

**6. 回退与开关**：`resonanceWarmingEnabled` 默认 off；`resonanceWarmingTierCap` 默认 none。

**7. 成本**：2 剂量 ×（replay+Track 1）= **4 当量**。

**8. 复用 harness**：`diagnose_voting_signals_exposure.py`（warming 模拟列）；`evaluate_dimension_voting_power.py`；`track1_dimension_power.py`（**必带**，B/C 迁移盲区）。**新写**：引擎 warming 分支（config 开关）。

**9. 依赖声明**：①len[4,8] 占比未知（D1 出，不猜）；②market_ctx 可用率（D1）；③H1 只证「全部缺票移除为负」，不构成选择性补票为正的证据——方向性假设；④与 T1-A2 的同日口径语义对齐（已内嵌，无顺序依赖）。

**10. 市况分桶**：强情绪期新入榜流量大→warming 暴露与增益窗口；退潮期新入榜少且假突破多→warming 方向质量预期更差，退潮期 h8 为第一风险视图；两桶反向→挂起（warming 票上限 B 不可入场，直接交易风险受控，但 B/C 迁移影响出场与叙事）。

---

# T4 cs 持续高位独立档 A_PERSIST（R5，两阶段）

**1. 考题**：持续高位人群（pct≥90 ∧ 近5帧均值≥85，实测 8.2%）当前混在 cs B 档——它相对非 eligible 的 B 档是否有独立方向后验区分度，若有，独立档三态强度（正/零/负）哪一态被信号与交易层结果支持？

**2. 门判据**（第一步=B0）：
- **阶段1（观察，零行为）**：`h8_excess(eligible_n5) − h8_excess(B_not_eligible)`：**≥+0.02 → 正态优先；≤−0.02 → 负态优先（持续高位=拥挤负信号）；|差|<0.02 → 归档不进阶段2**；分桶同读，两桶反号→阶段2 挂起；
- **阶段2·零态**（强度 +0.5=现 B 票值，票逐位不变的纯标签）：验收=全窗信号+Track 1 逐位一致 + 前端/候选词表同步（工程验收非统计验收）；
- **阶段2·正态**（+1.0，票 +0.75=A 级）：C1 ∧ C2（oos2）∧ C3 ∧ Track 1 wrxpf ≥0 ∧ S 纯度（合并 res-S h8 ≥基线−0.01）；**S 供给读数必带**（cs 正票是 S 结构守门——A_PERSIST +0.75 可为持续高位股解锁新 synergy S，主通道预期 ΔS>0，只登记不 gate）；
- **阶段2·负态**（−0.5，票 −0.375）：saEx 盲区（负票 B/C/D 迁移）→ **Track 1 为终判** wrxpf ≥0 ∧ C3；
- **终止**：passHard 崩；Track 1 <−5%；正态下 S+A Track 1 笔数 <30。

**3. 窗口与数据**：三窗+951 全窗；N 固定 5（R1 N3/N5/N10=8.7%/8.2%/7.2% 取中，N3/N10 只作诊断分层不作剂量）。

**4. 诊断步 schema**：D1 列 `persist_eligible_n3/n5/n10`（已有）+ `persist_stratum` + h8；聚合：persist_stratum×regime → {n, h8_excess}；阶段2 加 arm 列 `cs_tier_arm, cs_vote_arm, synergy_tier_arm, S_new_frames`。

**5. 行为改动步**：阶段1 零行为（复用 R1 列）；阶段2 单变量=A_PERSIST 强度，三态各一候选（正 +1.0 / 零 +0.5 / 负 −0.5），执行顺序=阶段1 定向的优先态先跑，零态并行做工程验收，反向态仅在优先态过线后作对照；**不并入 A**（H2 前例：合并稀释 A 档跌破 0.05 线，§4.2 热度⑤）。

**6. 回退与开关**：`crossSectionPersistFrames` 保持默认 0 不动；新开关 `crossSectionPersistIndependentTier` 默认 off；`tierSynergyCsPersistStrength` 三态为候选值。

**7. 成本**：阶段1 在 D1 内（0 增量）；阶段2 ≤3 态 ×（replay+Track 1）≈ **6 当量**。

**8. 复用 harness**：`diagnose_voting_signals_exposure.py`（persist 列+h8 分层）；`evaluate_dimension_voting_power.py`；`track1_dimension_power.py`。**新写**：A_PERSIST tier 枚举与投票映射分支；**预注册消费边界**：A_PERSIST 不进 `compute_synergy_state` 的 cs_strong(A)/cs_weak(D) 判定（叙事层零改动，§3#2）。

**9. 依赖声明**：①H2 的 0.05/0.087 读数属旧代际，只作「不并入 A」的设计先验；②强度表方案 B 先例（§4.2 热度④）扫的是既有 A/B/C/D 档强度值，A_PERSIST 是新人群新参数，不撞但记 csA OOS 全负先验；③S 解锁量级依赖 rank/vp 同帧票分布（D1 基线列可算，不猜）。

**10. 市况分桶**：三态本质是市况假设的投票化——强情绪期持续高位=主升延续（正态预期受益）vs 退潮期=拥挤见顶（负态预期受益，B 的警告）。分桶验证：阶段1 两桶 h8 差分列；**两桶反号→三态均不作全局候选**，挂起并预注册 regime 条件叙事（不条件开票）。

---

# T5 新入榜 S 死分支处置（R7）

**1. 考题**：a) 删除不可达的新入榜 S 条件是否零行为（逐位一致验证）？b) 带既有价格/量确认门的「入榜即事件」能否为 S 供给（127 帧、0.08%）提供不稀释 S 桶质量的增量？

**2. 门判据**：
- **a（零行为）**：验收=951 帧全窗五维+synergy 输出与基线**逐位一致**（含 tier/reasons/score），无统计线；
- **b（第一步=B0）**：C1 ∧ C2（oos2）∧ C3 ∧ Track 1 wrxpf ≥0；**S 纯度双线**：b 新增 res-S 帧 h8 ≥ 既有 res-S −0.01，且合并后 res-S ≥基线−0.01；S 供给 Δsynergy S 帧数登记（上侧不设硬线，稀释线+Track 1 终判）；终止：passHard 崩；Track 1 <−5%；S 桶稀释超线。

**3. 窗口与数据**：三窗+951 全窗。

**4. 诊断步 schema**：D1 列 `new_entry, entry_pct, entry_strength, chg, vr, confirm_pass_v10/v125/v150, would_be_S_b1/b2, len1_rank_tier, len1_rank_vote`；聚合：P(entry_pct>50)、P(confirm_pass)、would-be S 量级、would-be synergy S 量级（用 len1 实测 rank/vp 票堆叠模拟）。

**5. 行为改动步**：
- **a（推荐立即执行）**：删除新入榜分支中 `jump_freshness ≥ tierResonanceJumpFreshnessMin` 的 S 条件，档位阶梯收敛为 A/B/C。**为何零行为修复值得做**：①代码-语义对齐（该分支暗示「新入榜可经 jump 得 S」，为假，每个后续维护者付理解税）；②**静默激活风险有先例**——G4 确认门断线一个月无人察觉、10936 事件无门放行（§2.1）；任何未来改动若使 len==1 的 freshness 非零（如调 detect_rank_jumps 最小长度），会**未经评审地激活一条无门 S 通道**；删除死条件强制任何「新入榜得 S」必须走显式 trial（=b）；③成本 1 pass 逐位验证。
- **b（预登记 trial，与 a 不互斥，a 先行）**：`resonanceNewEntrySyntheticJump=on`：合成事件 entry_jump 经**既有确认门**（chg ≥ jumpConfirmChangeMin ∧ vr ≥ jumpConfirmVolumeRatioMin，同 config 值；若 T2 已落新默认则继承——顺序依赖）；S 条件=合成事件确认通过 ∧ entry_strength ≥ 阈值；方向不变（buy iff entry_strength>0）。**两档顺序剂量（保守先行）**：b2 阈值=0.3（对齐新入榜 A 档线，pct≥57.5）→ b1 阈值=0（pct>50）；b1 仅在 b2 过线后跑。
- **量级预估（依赖标注，不猜数）**：len1=3.7% 股帧为上限；真实增量=3.7%×P(pct>50)×P(确认门)——两个 P 均未知（D1 出）；synergy S 解锁量级额外依赖 len1 帧 rank fallback 票（§2.2 截断，D1 len1 切片实测替代读码）。

**6. 回退与开关**：a 无开关（零行为 PR，逐位一致后合入，受 golden 锁基线流程约束）；b `resonanceNewEntrySyntheticJump` 默认 off。

**7. 成本**：a=1 逐位验证 pass；b=2 剂量 ×（replay+Track 1）=4；合计 **5 当量**。

**8. 复用 harness**：逐位一致校验复用 R1 的 replay 对齐链（692/692 那套，harness_common.py）；`diagnose_voting_signals_exposure.py`（new_entry 列）；`track1_dimension_power.py`。**新写**：b 的合成事件分支（config 开关）。

**9. 依赖声明**：①len1 帧 rank fallback 档位映射（代码截断）→ 用 D1 实测分布替代读码；②P(pct>50) 与确认门通过率未知；③与 T2 的 vr 门值继承顺序（T2 先落则 b 用新值）；④b 的语义正当性本身是假设——「入榜+量价确认」等价于「排名跳跃+量价确认」未被任何历史读数支持，属全新候选。

**10. 市况分桶**：强情绪期新入榜多、隔夜跳空大→b 增益窗口但拥挤风险同步升高；退潮期新入榜少、vr 低→确认门过滤更狠、增量预期集中在强情绪期。分桶验证 S 纯度两期分列；退潮期 b 新增 S 的 h8 ≤0 → 适用域挂起。

---

# 成本汇总与总依赖

| 项 | 运行数（分钟级/次） |
|---|---|
| B0 基线（replay+Track 1） | 2（五案共享） |
| D1 合并诊断 | 1（四案共享） |
| T1（5 行为运行 ×2） | 10 |
| T2（2×2） | 4 |
| T3（2×2） | 4 |
| T4（≤3 态 ×2） | ≤6 |
| T5（a 1 + b 2×2） | 5 |
| **合计** | **≈32 次，串行数小时墙钟，全可回退** |

**总依赖清单**：①h8 公式口径（§7-3，沿用现行实现）；②regime 二分映射（D1 前置导出 R1 meta 取值域，未定前分桶读数空缺不 gate）；③oos1 gate 资格（本合同族预注册 oos2 主线，需主会话追认）；④所有未知量（len[4,8] 占比、P(pct>50)、确认门通过率、market_ctx 可用率）由 D1 落数后才进入行为步——**不猜数**；⑤R1 报告 `data/reports/voting-signals-exposure-diagnosis.json` 为 D1 基线输入。

**假设声明**：以上五案全部为待验证假设与预登记合同，不构成改动授权；T1 的「隔夜=噪声」、T3 的「warming 帧有方向信息」、T4 的「持续高位有独立区分度」、T5b 的「入榜+确认 ≈ 跳跃+确认」均为零先验或弱先验命题，判定线冻结后不得回看结果调整；任一读数不支持即按终止/归档条款执行，不因沉没成本续跑。
