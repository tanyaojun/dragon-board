# W2-2 预登记合同：价格确认门泛化（rank/res buy 降档门 v1 单帧形态，2026-10-08 起草，判定线冻结于跑数前）

> 合同地位：结构重设计计划 W2-2 案行为步预登记。形态裁定=语料包 v2 审定（2026-10-08，
> `voting-signals-corpus-v2-review.md`）：**降档确认门**（收缩面），W2-2 优先于 W2-1。
> 前置四项已跑两项：④靶人群 h8 **四窗 4/4 强同向过线**（判定见 §〇，`voting-signals-w2x-gates.json`
> w22 分节）；①W2-1 分桶先验过线但 W2-1 自身靶人群分解无靶已挂起（与本case无依赖冲突）；
> ②冗余面（dv/pm 共线率）=trial 前置补跑条款（§四 C-6）；③θ 自然分界=涨跌零界（读数锚充分，
> 分位谱在档）。
> 流程：本合同（AI 备料）→ 用户过目/审定 → 用户裁决开跑；落默认仍须用户裁决。

## 〇、机制事实与前置判定（全部可复核）

- **立项读数（前置④，预声明线冻结于跑数前：w22|sa|low−high ≤ −0.01 且 ≥3 窗同向）**：
  rank base buy ∧ S/A 帧按当帧 change 分层（low=change<0 / high=≥0，涨跌自然分界零回看），
  h8 excess_mean（分位桶校正）——decision **low −0.0665（n=1,014）vs high +0.0006（n=3,857），
  差 −0.0671**；midgap −0.1095；oos1 −0.0753；oos2 −0.0981。**四窗 4/4 强同向，量级为线值 6-10 倍**；
  res 侧同构（res buy ∧ S/A）：−0.0376/−0.0729/−0.0296/−0.0320 四窗全负。低 change 桶不是
  「没有超额」而是显著负超额=灾难性人群，降档门有巨大靶。
- **触发面**：low 桶占 rank S/A buy 帧 decision 窗 20.8%（1,014/4,871）——门改判面充足
  （>2% 零效应线无虞）。
- **θ 读数锚**：rank S/A 帧 change 分位谱（decision，n=6,667）：p10 −2.28 / p25 +0.69 /
  p50 +5.16 / p75 +9.99 / p90 +10.82——中位 buy 帧当帧涨 5%+（热榜涨停语境），change<0 是
  明确少数派异类，0 界=业务自然分界。
- **机制事实**：`_rank_trend_tier`：base buy ∧ |combined|≥StrongMin(0.5)→S / ≥ConfirmMin(0.25)→A；
  `_synergy_tier` 消费 `_vote(rank_tier, rank_dir) × tierSynergyRankVote(0.75)`——降 S/A→B 使票值
  1.0/0.7→0.7 强度+保留 buy 方向（非弃权，与 W1-1 abstain 不同族）。res 侧同构
  （`_resonance_tier` buy 档 S/A）。门只降档不改方向、不触 C/D 弃权语义。
- **形态依据**：「独立票死、门活」（pm/dv 票证伪×2，vp E 短路/jump 门验证×2，语料 §13.2-7）；
  本case=收缩面降档（「扩档拉动≠判别改善」先验的镜像安全侧）。

## 一、考题（本轮判定要回答的三个问题）

1. 价格确认门（低 change buy 降档）能否在交易面无损前提下改善信号面判别（C1）？
2. 剂量形态：rank 单门 vs rank+res 双门（res 侧靶面 4.5 倍于 rank 侧）哪个更优？
3. 结构面：S/A 面收缩幅度、synergy 档位迁移、与市况的交互（强市门误杀面 vs 退潮门保护面）。

## 二、候选臂（冻结，跑后不得加臂；共 2 剂量臂 + 1 基线臂 = 3 次 replay + 2 Track 1）

新 config 开关（单参三态，默认 off=现行为零行为、golden 不漂移=第一断言）：
`tierConfirmPriceGateMode: str = "off"`，枚举 `("off", "rank", "rank_res")`。
门判据（两臂同款）：**维 buy ∧ 维 S/A ∧ 当帧 change < 0 → 降 B**（θ=0 冻结；单帧形态，
3 帧方向确认等多帧形态留后续合同——一次一候选）。

| 臂 | overrides | 语义 |
|---|---|---|
| baseline | `{}` | B0 自证（默认 config = G1 cross_day；锚 0.1450/0.0983/0.1172 逐位断言） |
| g_rank | `{"tierConfirmPriceGateMode": "rank"}` | rank 门：rank buy ∧ S/A ∧ change<0 → B |
| g_rank_res | `{"tierConfirmPriceGateMode": "rank_res"}` | rank 门 + res 门（res buy ∧ S/A ∧ change<0 → B，同判据） |

- **消费面唯一**：tier 合成层（`assemble_observation` 侧或 engine `_build_signal` 维 tier 就位点）——
  接线为「门改写」形态（观测层 `_rank_trend_tier`/`_resonance_tier` 本体不动，档位原始语义保留、
  reasons 增「价格确认门降档」标注 fail-visible）；rank/vp/cs 投票面其余零改动。
- **选臂规则（机械化，冻结）**：两臂独立判定；均过提交线取三窗均值 rel 改善大者，另一臂如实披露。
- **与 W1-1 序贯交互（审定相容性 #3）**：W1-1（res D∧buy 票修正）若先落默认，本case res 门
  靶人群变化 → 本case判定读数登记时标注「W1-1 落默认后 g_rank_res 臂须复验」条款。

## 三、判定框架（跑数前冻结）

### W2-2.1 窗口与 population

- T2 runner 同款：全窗 **2026-04-15 ~ 2026-09-12（951 帧）**，decision / oos1 / oos2 三窗；
  B0 锚=0.1450/0.0983/0.1172（baseline 逐位自证 PASS 为跑数前置断言，不 PASS 全臂读数作废）。
- 信号面：各窗序列长度 ≥2 股帧；交易面：Track 1 decision 窗成交笔。

### W2-2.2 判定卡（审定骨架全款，跑后不调）

- **C1**：decision saEx 相对基线 ≥ +3%；
- **C2**：oos2 同向正（oos1 照登不设线）；
- **C3**：passHard 不降；
- **oos1 止损带**：oos1 saEx 相对基线 < −5% → 该臂终止（gross-damage floor，审定 A3 同款）；
- **Track 1 终判**：decision wrxpf 相对基线 ≥ 0（maxDD 容差 ≤ 基线）+ oos2 Track 1 披露
  （小样本只披露，< −5% rel 显式交裁不静默合并——A2 同款）；
- **触发率披露**：门改判帧数 =0 → 判零效应阴性不提交；<2% → 标注触面过小（Q1 C-c 教训）；
- **市况分桶**：strong vs retreat 对比对；retreat 桶 n<50 股帧 → 降级只披露不挂起（A5 同款）；
- **护栏（继承 T2 半数线）**：res S 档计数 ≥ 7185、synergy S 档计数 ≥ 64——本case降档直接动
  S/A 面，半数线为结构护栏；另披露 S/A 帧计数变化表（预期 S/A 面↓、B 面↑，方向反升=实现错误）；
- **侵蚀监控（不设线，必须披露）**：门改判帧的 synergy 档位迁移矩阵（S→B/A→B 计数）、
  low 桶帧在基线中的 saEx 贡献占比（门的「拆除面」价值分解）。

### W2-2.3 准入与止损

- ≥1 臂同时过 C1+C2+C3+Track 1+护栏 → 提交用户裁决落默认（一次一候选，按选臂规则）；
- 全 FAIL → 阴性结果如实登记，不硬上、不调线重跑；
- 任一臂 C1 过但 Track 1 < 0 → 判不晋升。

## 四、实施与验证纪律

- **接线依赖**：config.py / engine 文件当前为 P5 并行线未提交改动共享面——**接线待 P5 线收官
  解锁（W1-1/amount L2 同款处置）**；golden 二进制 gz 同款约束。
- **测试纪律**：默认 off 零行为=第一断言（三窗 saEx 逐位一致）；三态谓词单测（θ 边界含等号：
  change=0 → 不降档归 high；S/B 档不触；res 门只在 rank_res 态生效；direction sell/D 档不触）；
  专项测试不触发真实模型调用；golden 预期零漂移（至多 configRepr +1 行），重录+逐字段 diff 审查。
- **harness**：复用 `evaluate_vote_w11_res_dbuy.py` 骨架新建 `evaluate_vote_w22_price_gate.py`
  （迁移矩阵/市况分桶/逐臂 checkpoint 全件复用）；冗余面（审定前置②）：trial 前补跑一次诊断列
  （low 桶帧 × dv 四态 × pm 方向交叉计数，复用本诊断脚本框架；共线率 >80% 须重新评估门独立增量
  并向用户披露后才开 trial）。
- **成本**：3 replay + 2 Track 1 + 冗余面诊断一次，全本地 CPU ≈50 分钟墙钟，零 API 成本。
- **回退路径**：`tierConfirmPriceGateMode="off"` 单开关回基线。

## 五、起草者自报风险（供审定/用户攻击）

① **单帧门对涨停帧的误伤面**：p50 change=+5.16 说明半数 buy 帧涨 5%+，low 桶是「涨不动」异类——
但涨停封板帧 change 大、不会被门触，误伤面主要是「排名抢跑+价格暂弱」帧，其后验已实测为灾难
（−0.067），门语义=「等价格确认再给 S/A」，与用户盘感「低点新鲜度」判例同向；② **外推风险**：
jump 门 +18.1% 是 Jump 专属人群的读数，泛化到全部 buy S/A 帧的迁移效应 trial 才回答（审定如实
列明的反对理由）；③ effect 量级预期大（拆除面 20.8% × 桶内差 −0.067）但 saEx 是 S/A 合并 excess，
门把最差 20% 移出 S/A 后剩余 S/A 的 excess 是否升仍是未知（可能「剩下的都是好的」稀释逆转），
C1 +3% 不保证；④ res 门靶面大（4,531 帧 decision）但 res 侧桶差（−0.038）小于 rank 侧（−0.067），
双门臂的边际增量可能被 rank 门稀释（配对披露可分离）；⑤ **θ=0 单帧门的假信号敏感度**：
change 缺失帧（不可算）门的处理=不触发（fail-visible 计数），与 W0-2 amount 口径一致。
