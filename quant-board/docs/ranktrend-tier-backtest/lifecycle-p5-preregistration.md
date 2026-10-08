# 生命周期 P5 预登记合同：双轴重设计·allow 腿分位带门（2026-10-07 起草，判定线冻结于跑数前）

> 合同地位：P5（语料 §11 Opus 首轮提案「双轴重设计」裁定论证级合规；前置四项诊断本轮补跑）的预登记。
> 前置诊断：`backend/operations/diagnose_lifecycle_p5_dual_axis.py`（2026-10-07，全窗 04-15~10-07 一次默认
> replay，22.6 万信号/decision 窗 124,026 帧，JSON `data/reports/lifecycle-p5-dual-axis-diagnosis.json`）。
> 流程：诊断 → 本合同（判定线冻结）→ 接线（默认 off 零行为）→ trial → 判定 → 台账/语料登记 → 提交；
> 落默认仍须用户裁决。Opus 审定材料已备（本合同+诊断 JSON），由用户执行外部审定（外部模型调用纪律）。
> 审定纪律同 Q1（lifecycle-q1-preregistration.md 先例）：算术与事实引用逐条可核，硬幻觉=驳回。

## 〇、诊断事实（P5 前置四项，全部已归档可复核）

- **D0 双轴语义修正（先裁决再设计）**：Opus 提案的「双轴」在本仓语境=path 轴（stage 5 态）× action 轴
  （veto/caution/allow/exit_watch）。实测两轴**近完全映射**（D4 交叉表：veto←reversal 7711+cooling 2070 /
  caution←cooling 93706 / allow←ignition+expansion 全部 / exit_watch←crowded 全部；action×pct MI=0.2465 ≈
  stage×pct 0.2894）——拆轴本身无新增信息量。真正的信息增量在 **(分位带 × 动量档) 对 stage/action 的
  2D 再划分**（D3 单元格），即「非单调离散门」的落点是 allow 腿的分位带门，不是发布面拆轴。
- **D1 stage×pct 列联（结构根因定量版）**：MI=0.2894（shuffle 基线 0.0002±0.0000，n=124,026）。
  crowded 93% 落 pct 最高带、ignition 在 pct0-4 带**合计 3%**（低位点火帧结构性地不存在——recovery
  谓词 pct≥50/best≤25/hot≥2 门控）——「tier 构成由分位带决定」（§4.1-E）实锤，stage 标签不可作方向标尺。
- **D2 stage×velocity 重叠**：ignition p50=+5.23 / expansion p50=+2.46 / crowded p50=0.0 / reversal
  p50=−0.61，但 cooling 跨全带（p10=−9.08/p90=+5.27）——单动量轴不可分，须与分位带联用。
- **D3 2D 单元格（门的重画依据）**：pct0-2 带 fwd8 几乎全正（+0.08~+1.37），pct4-9 带几乎全负；
  **up_fast（velocity>5）自 pct5 带起全面恶化**（pct5 −0.81 / pct6 −1.20 / pct7 −1.76），up_slow 自
  pct7-8 带恶化（−0.19/−0.88/−0.63）。fwd1 呈强均值回归基线（pct0 带 +10），结构信号看 fwd8。
  score 分位桶：b1（27-34）fwd1=+2.40 单峰，b3/b4（48+）单调恶化（−1.27/−2.63）——旧语料 U 形
  （saEx 口径）未复现为 U；高分位恶化与 SP5 温度轴 REVERSE / C6 弱势带 / W0-2 放量最差同族互证。
- **D4 action 面信息**：veto 帧 fwd1=−1.73（保护方向正确，阶段 12 K 实验+vp E 短路 −32% 同族旁证，
  **veto 腿不动**）；**allow 帧 fwd1=−1.47/fwd8=−0.46，比 caution（+0.40/+0.06）差**——allow 腿放行的
  ignition/expansion 帧聚集高分位（D1），实际在放行追高帧；exit_watch −0.91（crowded 专用，不动）。
- **D5 与既有裁决的相容**：c1 读数（关降档 decision −39.4%/oos1 −34.4% rel）证实降档腿正价值——
  本机制把 allow→caution 是**顺着已证实正价值腿扩容**，方向相容；坐标下降 §4.1-E「阈值不可调」被
  绕开（不改 raw_stage 阈值，改 stage→action 的映射层）。

## 一、机制：allow 腿分位带门（非单调离散门）

### P5-a1 开关与形态

- 新 config 开关：`lifecycleAllowBandGateMode: str = "off"`，枚举 `("off", "pct_band", "pct_velocity")`。
  off=现行为（stage→action 映射原样，默认零行为、golden 不漂移=第一断言）。
- **pct_band（1D 门）**：`action=="allow"` 且当前帧 `percentiles[-1] ≥ lifecycleAllowBandGatePctMin`
  → 改写 action="caution"（下游 B 路径：candidateTier 降档/环境门收紧自动跟随），decision reasons
  增标注「高分位放行帧降档（P5 allow 分位带门，pct≥X）」（fail-visible）。
- **pct_velocity（2D 门）**：fast 档（`cycle.metrics.rankVelocity > 5`，D3 的 up_fast 定义）用更低门限
  `lifecycleAllowBandGatePctMinFast`，其余（含 velocity=None 的 gap 步——证据缺按宽松侧，gap 标注已
  fail-visible）用 `lifecycleAllowBandGatePctMin`；命中同 pct_band 改写。
- **干预点（接线面）**：`_build_signal` 内 `analyze_cycle_with_risk` 之后、WP2a gate_confirm 状态机与
  `compose_decision`/`compose_analysis_candidate_tier` 之前——改写后的 action 进入全部下游（含确认
  状态机与两 tier 合成）。veto/exit_watch/action=caution 帧一律不触碰（只动 allow 腿）。
- **红线三条**：①raw_stage/normalize_stage 阈值零改动（§4.1-E 命题域外不碰）；②veto 腿零改动
  （D4+阶段 12 K 实锤的保护腿；trial 判定加「veto 触发数与基线逐位相同」结构守卫）；③不改发布面
  （gateAction 字段/展示投影迁移=gate-redesign-proposal §4.2 的实施工程，待 trial 过线落默认时随行，
  本合同不触发快照 payload 变更义务）。

### P5-a2 剂量臂（冻结，跑后不得加臂；共 5 剂量臂 + 1 基线臂 = 6 次 replay）

1. baseline：全 off（=当前生产默认）
2. A3 保守 1D：pct_band X=7（allow∧pct≥70→caution）
3. A1 中间 1D：pct_band X=6
4. A2 激进 1D：pct_band X=5
5. B1 二维门：fast=5 / slow=7（up_fast 自 pct5 收、up_slow 自 pct7 收，D3 单元格直接映射）
6. B2 二维门：fast=5 / slow=6

- 门限值冻结依据：D3 单元格 fwd8 转负位置（up_fast pct5 / up_slow pct7）；X=6 为两档中间剂量。
  本基准来自 decision 窗同数据——**登记为过拟合风险**（§三 C-10④），oos1/oos2/g1era 窗外判定为防线。

## 二、判定框架（跑数前冻结）

### C-1 窗口与代际

- trial 全窗重放 **2026-04-15 ~ 2026-10-07**；decision 04-15~07-31（主判定）/ oos1 08-15~08-31（主判定）/
  oos2 09-01~09-12（主判定）/ g1era 09-13~10-07（披露不设线）。frozen 中段不对账（本机制无对账基线）。
- 全臂同数据代际同窗重放，同代际相对线（G1/Q1 同款；跨代际绝对对照已失效，台账 §18 登记）。

### C-2 判定 population 预声明

- 信号面：decision 窗、序列长度 ≥2 的股帧（与 P3/Q1 合同同 population）。
- 交易面：Track 1（harness 现有口径，decision 窗成交笔）。

### C-3 判定线（相对线，结构沿用 Q1 v1.1；跑后不得回看调线）

- **C-3.1 信号面（saEx）两道线**：
  - 无害线：decision/oos1/oos2 三窗中 ≥2 窗 saEx 相对基线 ≥ +0.0000，且无一窗 < −0.005。
  - 提交线：三窗均值相对改善 ≥ +0.002，且 ≥1 窗 ≥ +0.003。
  - 负效应线：三窗均值 < −0.003 → 判负效应（该臂止损）。
  - 全臂未达提交线 → 零效应，阴性登记不提交。
  - 披露义务：各臂 vs 基线 S/A 帧计数变化如实列表（本机制预期方向=A 路径帧↓、B 路径帧↑；
    若 A 反升=实现有误须查）。
- **C-3.2 交易面（Track 1）**：decision 窗 wrxpf 相对基线 ≥ −0.003 且 maxDD 不恶化
  （回撤深度负数域：|dd_arm| ≤ |dd_base|）；笔数变化如实披露；oos2 与 g1era Track1 如实披露不设
  提交线，oos2 wrxpf 相对基线 < −0.005 须显式解释并交用户裁决，不得静默合并。
- **C-3.3 结构守卫（P5 特有，硬断言）**：veto 与 exit_watch 触发数与基线**逐位相同**（红线②的
  可检验形式）；action=caution 帧数增幅=allow 降幅（改写守卫）；违反=实现错误，臂作废重查。
- **C-3.4 侵蚀监控（不设线，必须披露）**：降档（lifecycleTier B/D）触发数变化分列；allow→caution
  改写帧数及其 pct 分布；G1 veto 收益不受影响由 C-3.3 间接保证。
- **C-3.5 准入与止损**：≥1 个剂量臂同时过 C-3.1（无害+提交）+C-3.2 → 提交用户裁决落默认；
  全 FAIL → 阴性结果如实登记（台账+语料），不硬上、不调线重跑。

### C-4 统计规格

- 指标口径卡沿用 G1/Q1 判定（saEx=h1 synergy excessDirectionAccuracy；wrxpf=winRate×profitFactor；
  maxDD=TradeSimulator summary 原值）。本机制为确定性映射改写，无 bootstrap 置信面（单次 replay
  逐位确定），显著性由窗外窗（oos1/oos2/g1era）一致性承担。

## 三、实施与验证纪律

- **C-5 接线面**：config 三新字段（mode+两门限）+ `_build_signal` 改写点（单点，无双链问题——
  replay 与 live 链共用 `_build_signal`，天然两代际同口径）；`percentiles[-1]`/`cycle.metrics.rankVelocity`
  就地可得，无新序列传递。
- **C-6 测试纪律**：一切测试禁触发真实 jev/付费模型调用；新开关默认 off 零行为=第一断言；golden
  快照默认 off 下预期零漂移（至多 configRepr 文本行），`RANKTREND_GOLDEN_SNAPSHOT_REGEN` 重录+
  逐字段 diff 审查；三态谓词单测（X 边界含等号/velocity None 走宽松侧/veto·exit_watch·caution 不触碰）+
  `_build_signal` 接线守卫（banded 模式下高分位 allow 帧 action 实际改写）。
- **C-7 回退路径**：`lifecycleAllowBandGateMode="off"` 单开关即回基线；无数据删除面。
- **C-8 文档同步**：判定完成同轮内更新台账（§23）+语料（§14 战报）+前端消费面（若 reasons 新标注
  需展示——decision.reasons 已透传，预计零前端改动）——漂移违规同 AGENTS §1.2-5。
- **C-9 考题/成本/harness/依赖**：考题=①allow 腿的高分位放行是否真是负贡献（拆掉后信号面/交易面
  双验证）②门限带在哪（1D vs 2D 剂量面）③降档腿扩容是否侵蚀 veto 收益（C-3.3 守卫）。成本=
  6 次 replay × ~3-8 分钟 + Track1 ≈ 1 小时墙钟，全本地零 API 成本。harness=复用
  `evaluate_lifecycle_q1_trials.py` 骨架（evaluate_arm/signal_verdict/track1_verdict 直接 import）。
  依赖=零新数据链、零新集合、零外部调用。
- **C-10 尾注假设声明（起草者自报，供审定攻击）**：①门限 X 冻结自 decision 窗诊断=设计泄漏风险，
  oos 窗一致性是唯一防线；②fwd 是排名增量含均值回归基线，D3/D4 的 fwd 结构不直接等价于 saEx 改善
  （saEx 有分位桶基线校正），trial 才是真判定；③D4「allow 比 caution 差」是混合读数（allow 帧的
  fwd 劣势可能全由分位混杂贡献而非「放行错误」），降档是否回收价值待 Track1；④市况依赖未分桶
  （强情绪期热榜动量有效=用户实盘经验，高分位降档可能在强情绪期错杀——若 C-3.1 过而 C-3.2 fail，
  首查市况分层）；⑤stage≈分位带函数的结构根因未动（本机制只绕开不修复，ignition 低位盲区
  （D1：pct0-4 带 3%）仍是后续 P 线候选）。

## 四、流程

1. 诊断（已完成，四件归档）→ 本合同起草（判定线冻结）→ 用户「请执行」已授权全链（2026-10-07）
2. → 接线（默认 off）→ 专项测试 → trial 6 replay → 判定 → 台账/语料登记 → 提交
3. → Opus 审定材料备好（本合同+诊断 JSON），用户执行外部审定后裁决落默认
4. 任何判定线修改=新合同版本重新走审定（跑后调线=违规）。
