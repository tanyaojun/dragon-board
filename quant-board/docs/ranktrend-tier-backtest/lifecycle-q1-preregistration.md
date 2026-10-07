# 生命周期 Q1 预登记合同：价量证据喂入（2026-10-07 起草，判定线冻结于跑数前）

> 合同地位：Q1（语料 §6 主线——price_changes/amount_history 已采集并传入 `_build_signal`，但 `analyze_cycle`
> 不消费）的预登记。前置诊断已跑（`backend/operations/diagnose_lifecycle_q1_price_volume.py`，2026-10-07，
> 全窗 2026-04-15~10-07，21.5 万序列步/33,743 跨日步，JSON 产物 `data/reports/lifecycle-q1-price-volume-diagnosis{,-vr}.json`）。
> 流程：本合同起草 → 用户过目 → Opus 4.8 审定 → 用户裁决开跑 → 才动生产判据。
> 审定纪律同 P1/P3（语料 §11.2）：算术与事实引用逐条可核，硬幻觉=驳回。
>
> **修订版 v1.1（2026-10-07）**：按 Opus 审定回执 R1-R9 必改项修订（R1 注入人群冻结/R2 提交线补全/
> R3 靶数可复算口径/R4 分离度线按机制重定义/R5 Track1 补窗与 maxDD 容差/R6 考题·成本·harness·市况·
> 依赖声明/R7 frozen 口径标注/R8 C-c1 字面矛盾修复/R9 臂数口径）；建议级采纳 6 项（3.4% rel 单位、
> 机械化选臂规则、S/A 档计数披露、proxy drop/spike 分列、P 与 lifecycleVelocityMin=18 关系注记、
> golden 措辞对齐）+D5 措辞修正。R2/R4/R5 判定线增补随本版冻结（当前未跑数，不构成跑后调线）。

## 〇、诊断事实（合同依据，全部已归档可复核）

- **D1 靶子规模**：跨日步 33,743（占 15.7%）；其中排名大跳（|Δpct|≥10 分位点）**≈2.1 万步**。
  可复算口径：drop 靶 11,334（`D_dv_overlap.dv_on_target_gap_rank_drop` 5,459+5,320+555）+ spike 有价格
  方向 9,075（`B_gap_price_cross.gap_rank_spike_ge_pos.ALL` 6,374+2,701）+ spike 价平 ≈443 ≈ **20,852**。
- **D2 可填充率**：跨日步价格证据 100% 可用；volumeRatio 口径量证据 77.3% 可用（价+量齐备）。
- **D3 价格方向分辨力（核心效度证据）**：跨日排名大跌步（n=10,570），价升组后续 ≤3 步排名回升 +5.36
  分位点（77.1% 回升）vs 价跌组 +3.55（72.8%），差 **+2.31 [CI 1.86~2.76]**；排名大升方向差 **+2.04
  [CI 1.58~2.50]**；同日对照分离 +2.48 [CI 1.98~2.99]——分辨力是普适的（价×排名时序背离），非跨日特异。
  注记：两组绝对回升均大正数（排名均值回归基线），分辨力看差值；fwd 含当日日内恢复效应。
- **D4 量证据口径**：amount 粗算量比存在日内时点污染（跨日步 amount=当日累计 vs 基准=昨日尾盘累计），
  **禁用**；volumeRatio（行情源量比，risk 已消费同字段）干净口径分离：价升组中位 1.18 vs 价跌组 0.77，
  价跌组 p25=0.02（极端缩量/一字板形态左尾）。
- **D5 dv 重叠率（步骤 0）**：Q1 靶子步几乎全部已被 dv（priceRankDivergence）单帧版覆盖——落入 dv
  枚举档（A/B/C/D 四态 + unknown 档；drop 靶内 5,459 price_lead_warn + 5,320 confirm_down + 555 unknown）
  。**Q1 不新造价×排名因子**。dv 三缺口=Q1 全部增量：①效度从未验证（D3 补上）②投票权重 0.0 纯观察
  ③无量输入。
- **D6 dv 现状缺陷**：dv 无 temporalGap 防御——跨日步 rankDir 即隔夜跳变（rank_down 18,253 步）；
  现权重 0.0 无害，接线（C-a）时必须一并修。
- **D7 dv 复刻自证**：step 级复刻与真函数 430 抽样零 mismatch。

## 一、机制一（C-c + C-b 合流）：gap 帧价量虚拟动量证据

### C-c1 开关、注入人群与形态

- 新 config 开关：`lifecycleGapPriceVolumeMode: str = "off"`，枚举 `("off", "direction_gate")`。
  off=现行为（G1 语义原样，默认零行为、golden 不漂移=第一断言）。
- **注入人群（冻结）**：跨日步 ∧ |ΔrankPct|≥10（即 D1 靶子 ≈2.1 万步，与 D3 效度验证人群严格对齐；
  R1 裁定：不做全跨日步外推注入——D3 分辨力只在 |Δpct|≥10 验证过，人群外注入属未验证外推）。
- 主形态 **direction_gate**：G1 语义在两类步上分开表述（R8 字面矛盾修复）：
  - **证据可用步**（注入人群内，当日 `change` 与 `volumeRatio` 均有限且命中下表前两行）：
    该步动量位**由 proxy 驱动（不沿袭前帧）**——`metrics.rankVelocity = velocity_proxy` 参与判定，
    stage/raw 判定吃该 proxy 值；`acceleration`/`rankShock` 维持 NaN→null（单帧价格方向构造不出
    加速度，不伪造多帧证据）；输出 metrics 增 `gapPriceVolumeProxy: true` 标记（fail-visible）。
  - **证据缺步**（人群外跨日步、价平、量缺失、vr 低于门）：**维持 G1 现状**——动量三分量置缺
    （None→null）+ temporalGap 标记 + raw 沿袭前帧。
  - off 模式：全步维持 G1 现状。

| 价量交叉（注入人群步，当日口径） | velocity_proxy |
|---|---|
| change > 0 且 volumeRatio ≥ vrGate | +P（分位点当量，剂量臂） |
| change < 0（volumeRatio 任意有限值） | −P |
| 其余（价平/量缺失/vr 低于门） | 维持 G1 现状（证据缺，None） |

- **红线三条**：①hot_streak/best/drawdown 跨缺口累积不动（G3 剂量禁区，同 G1 合同）；②acceleration/
  rankShock 维持 NaN→null（含证据可用步——只有 rankVelocity 单分量被 proxy 驱动）；③输出 metrics 增
  `gapPriceVolumeProxy: true` 标记（fail-visible：虚拟证据来源可辨，展示层与回放器可区分真差分与代理）。
- **P 剂量量级注记**：P ∈ {3, 5, 8} 分位当量均低于 `lifecycleVelocityMin=18`——proxy 不制造
  「velocity>18」型高阈值触发；效应路径=中性 0（G1 置缺步风险侧按 0 中性）与有向证据之差，经
  stage 边界/滞回/温度类低阈值判据传导，预期效应量级为小剂量微调。

### C-c2 设计依据与边界

- 依据 D3：价格方向在跨日排名大跳步有真实分辨力（+2.31 显著），且价跌组含极端缩量左尾（D4）——
  「价跌一律 −P、价升须放量确认」的非对称门是数据形态的直接映射（价跌的证据无需量确认：
  D4 中价跌组量比中位 0.77 且 25% 步 ≤0.02，方向本身已是退潮证据；价升组须排除无量假升）。
- 与 G1 的关系（防翻案声明）：G1 废的是**排名差分冒充当日动量**；本机制注入的是**当日价格方向**
  独立证据源。G1 的 veto 收益（−6.8% rel 降幅）侵蚀监控见 C-4.3。
- P5/双轴重设计、G2（non_adjacent）不在本合同范围内，均不动。

### C-b 量证据（机制一内的调节维度）

- volumeRatio 口径（D4），阈值臂：`vrGate ∈ {1.0, 1.5, 2.0}`（行情源量比语义：当日累计均量 vs 近 5 日）。
- 「价跌 + 极端缩量（volumeRatio ≤ 0.1）」= 疑似一字板形态，单列观察列（不进判定线，
  防止把「卖不掉」误读成「健康缩量」——形态语义未裁决前只披露）。

## 二、机制二（C-a）：dv 效度化接线

### C-a1 前置修复（接线前必做）

- dv 计算接入 temporalGap：相邻序列元素跨日时 `compute_price_rank_divergence` 归 `unknown`
  （rankDir=None）+ tierReasons 标注「跨日缺口步，背离不可判定」（fail-visible）。
  消除 D6 缺陷（隔夜跳变不再进 dv 的 rankDir）。

### C-a2 剂量臂

- `tierSynergyDivergenceVote: 0.0 → {0.25, 0.5, 0.75}`（cs 同量级封顶 0.75；pm=0.0 负贡献关闭为反面参照）。
- 前提：机制一 off 状态下单独评定 dv 权重的边际（两机制效应可分离，防混同归因）。

## 三、判定框架（两机制共用，跑数前冻结）

### C-1 窗口与代际

- trial 全窗重放 **2026-04-15 ~ 2026-10-07**；窗口沿用 P3 合同定义：
  decision 04-15~07-31（主判定）/ midgap 08-01~08-14 / oos1 08-15~08-31（主判定）/
  oos2 09-01~09-12（主判定）；**附加窗 g1era 09-13~10-07（G1 生效代际新数据，只披露不设线）**。
  **frozen=midgap∪oos1=08-01~08-31**（冻结段过程指标对账——veto 翻转率 0.1376 / bd_downgrade 0.0834
  ——用全 8 月口径，语料 §6-I；R7 修订：不得把该对账数字错标成 midgap 单独口径）。
- 全部对照臂与剂量臂在同一数据代际同窗重放，用同代际相对线（G1 判定同款；跨代际绝对对照已失效，
  台账 §18 登记）。

### C-2 判定 population 预声明

- 信号面：decision 窗、序列长度 ≥2 的股帧（与 P3 合同同 population）。
- 交易面：Track 1（harness 现有口径，decision 窗成交笔）。

### C-3 剂量臂清单（冻结，跑后不得加臂；共 **13 剂量臂 + 1 基线臂 = 14 次 replay**）

1. baseline：G1 on（cross_day）+ Q1 全 off（=当前生产默认）
2. C-a 单独：dv 权重 {0.25, 0.5, 0.75} × 机制一 off（3 剂量臂）
3. C-c 单独：direction_gate × vrGate {1.0, 1.5, 2.0} × P {3, 5, 8} 分位点当量（9 剂量臂）
4. C-a × C-c 最优组合复测（1 剂量臂）。**机械化选臂规则（冻结）**：C-a 最优=3 臂中 C-4.1 三窗均值
   相对改善最大且过无害线者；C-c 最优=9 臂同规则；组合臂=两最优直接组合（不再搜参）；若组合臂
   C-4.1/4.2 劣于两单独臂中的更优者，提交候选=单独臂更优者（组合臂仅作交互项披露）。

### C-4 判定线（相对线，容差沿用 G1 合同；R2/R4/R5 增补随 v1.1 冻结）

- **C-4.1 信号面（saEx）两道线**：
  - 无害线：decision/oos1/oos2 三窗中 ≥2 窗 saEx 相对基线 ≥ +0.0000，且无一窗 < −0.005。
  - **提交线（R2 补全）**：三窗均值相对改善 ≥ +0.002，且 ≥1 窗 ≥ +0.003。
  - 负效应线：三窗均值 < −0.003 → 判负效应（该臂止损）。
  - 全臂均未达提交线 → 零效应，阴性登记不提交。
  - 披露义务：各臂 vs 基线的 S/A 档帧计数变化如实列表（防「档位扩容拉动 excess」被误读为判据变准）。
- **C-4.2 交易面（Track 1；R5 补全）**：
  - 主判定：decision 窗 wrxpf 相对基线 ≥ −0.003。
  - maxDD 容差：**≤ 基线**（不得恶化）。
  - 附加窗：oos2 与 g1era 的 Track1 结果**如实披露不设提交线**；若 oos2 wrxpf 相对基线 < −0.005，
    即使 C-4.1 过线也须显式解释并交用户裁决，不得静默合并。
  - 笔数变化如实披露。
- **C-4.3 G1 收益侵蚀监控（不设线，必须披露）**：veto 触发率相对基线的变化量、其中跨日步贡献的
  翻转方向分解（解除/新增各多少，**按 gap_rank_drop / gap_rank_spike 分列**）；若 veto 触发率回升超过
  G1 降幅的一半（**>3.4% rel**，R1 合同 −6.8% rel 之半），即使 C-4.1/4.2 过线也须在提交说明中显式
  解释并交用户裁决，不得静默合并。
- **C-4.4 分辨力不反转（Q1 特有；R4 按机制重定义）**：
  - C-c（direction_gate）臂：在**注入人群**（跨日步 ∧ |Δpct|≥10）内复算 D3 口径「价升 vs 价跌」组
    后续 ≤3 步排名走向分离度，不得收窄至基线分离的 50% 以下（机制不能反向伤害自己的证据来源）。
  - C-a（dv 权重）臂：本线**不适用**（机制二不消费价量证据，注入人群分离度对该臂是常量，无信息量）；
    C-a 臂证据健康由 C-4.1/4.2 + C-4.5 判定线承担。
- **C-4.5 准入与止损**：≥1 个剂量组合同时过 C-4.1（无害线+提交线）+C-4.2 → 提交用户裁决落默认；
  全 FAIL → 阴性结果如实登记（台账+语料），不硬上、不调线重跑。

### C-5 统计规格

- 聚块 bootstrap：按 code 重采样，10,000 次，seed=20261007 冻结于脚本常量；CI 95%。
- 指标口径卡沿用 G1 判定（saEx=S/A 两档合并 excessDirectionAccuracy；wrxpf=winRate×profitFactor）。

## 四、实施与验证纪律

- **C-6 接线面**：`analyze_cycle` 增价量序列入参（`price_changes`/`volume_ratios`，与 time_keys 同模式
  由 runtime 双链+`_analyze_one_stock` 传入——**live/快照落库链必须同步接线**（a44d965f 评审 P1 教训：
  replay 单链接线=两代际口径分裂）；长度不匹配/缺失 → 证据缺+decision reasons 标注（fail-visible，
  沿用 G1 时间键标注模式）。
- **C-7 测试纪律**：一切测试禁触发真实 jev/付费模型调用；新开关默认 off 零行为=第一断言；
  golden 快照默认 off 下**预期零漂移（至多 configRepr 文本行变化）**，`RANKTREND_GOLDEN_SNAPSHOT_REGEN`
  重录+逐字段 diff 审查（预期场景输出变化仅限剂量臂场景）；inline 虚拟证据构造 ↔ analyze_cycle
  逐位一致自证 + 引擎 replay 比对（P3 诊断同款 L0）。
- **C-8 回退路径**：`lifecycleGapPriceVolumeMode="off"` + `tierSynergyDivergenceVote=0.0` 双开关
  patch 回基线，配置面保留为诊断对照臂；无数据删除面。
- **C-9 文档同步**：判定完成同轮内更新台账（§19）+语料（§13 战报）+前端消费面（若 gapPriceVolumeProxy
  需展示）——「文档已改、展示仍旧」即漂移违规（AGENTS §1.2-5）。
- **C-10 尾注假设声明**（起草者自报，供审定攻击）：①P 当量把价格方向映射为分位当量是**信息压缩**
  （丢幅度），方向门 vs 连续映射的形态选择未经比较；②vrGate 三臂是分位粗选，非最优点主张；
  ③D3 分辨力的后续走向含均值回归基线，若「价升组回升」主要是基线效应而非个股特质，
  direction_gate 的增益可能小于 D3 表面幅度；④fwd 含日内恢复效应，跨日步与同日步的 fwd 语义
  不完全同构；⑤D3 为全窗混合市况读数，市况依赖（强情绪期失效先例：低开过滤 4-6 月反转）未分市况复检。
- **C-11 考题、成本、harness、市况、依赖声明（R6 补全）**：
  - 考题（本轮判定要回答的三个问题）：①gap 帧空出的证据位由价量 proxy 补位（机制一），能否在
    交易面无损前提下改善信号面判别？②dv 效度验证后（D3），投票权重给多少（机制二）？③补位后
    G1 的 veto 收益是否被侵蚀、结构如何变化（C-4.3）？
  - 成本估算：14 次 replay × ~6 分钟 ≈ 1.5 小时墙钟（全窗 04-15~10-07，引擎性能优化后单次全窗
    dry-run 5.5-6.5 分钟实测）+ C-4.4 分离度复算 + Track1 交易面评估；全部本地 CPU，零 API 成本、
    零 jev/付费模型调用（AGENTS §1.2-7 合规）。
  - harness 复用清单：`backend/operations/evaluate_lifecycle_scale_gap_trials.py`（P3 trial runner
    同款臂评估骨架）/ `backend/operations/track1_lifecycle_gate_trade.py`（交易面 Track1 口径）/
    `backend/operations/diagnose_lifecycle_q1_price_volume.py`（C-4.4 分离度复算同款复刻链+聚块
    bootstrap）。
  - 市况分桶：同 P3 合同——帧投影无 hotlistSentiment，用 market_regime 池内因子 state
    （strong/normal/weak/retreat）替代热榜情绪 stage，**仅报告列不进判定线**（C-10⑤ 的落地口径）。
  - 依赖声明：帧投影字段 `change`/`volumeRatio`（10 月回填后 vr 77.3% 可用=D2，缺 vr 步按证据缺
    fail-visible 处理）；`price_changes` 已在 `_build_signal` 入参链；无新数据链改动、无新集合、
    无新外部调用。

## 五、审定与开跑流程

1. 本合同 → 用户过目（本轮）
2. → Opus 4.8 审定（算术/事实逐条核，输出归档 `lifecycle-q1-opus-review.md`）——**已完成（2026-10-07，
   有条件通过，R1-R9 已随 v1.1 落实）**
3. → 用户裁决「开跑」（**2026-10-07 用户已令：按回执修正后开跑**）→ 按冻结合同执行：
   接线 → 专项测试 → trial 14 次 replay（13 剂量臂+1 基线臂）→ 判定 → 台账/语料登记 → 提交
4. 任何判定线修改=新合同版本重新走审定（跑后调线=违规）。
5. 判定结果落默认仍须用户裁决（C-4.5）——本授权覆盖到「判定+登记+提交」，不含落默认。
