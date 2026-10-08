# RankTrend 四投票信号（共振/趋势/热度/量价）· 推理语料包（2026-10-07 组装）

**用途**：投喂强推理模型（本轮主=GPT-OSS-120B 脚本通道，备=Claude Opus 4.x 手动投喂），对**五位信号中除生命周期（环境门，上一轮已完成，见 `reasoning-corpus-lifecycle-stage.md`）外的四个投票维**——共振（resonance）/趋势（rankTrend）/热度（crossSection）/量价（volumePrice）——及其**汇合点 `_synergy_tier`** 做深度归因与优化研讨。

**触发命题（用户 2026-10-07）**：按生命周期阶段同款「语料投喂和优化流程」，把五位信号的其他四个【共振】【趋势】【热度】【量价】也优化一轮。

**为什么合并一份语料（组装者决定，须告知模型）**：四维在同一函数 `_synergy_tier`（`ranking/volume_price.py:329`）投票合成 synergy 档位，票权/档位强度/阈值线互相耦合（例：tierSynergyVoteStrengths 只乘 res/rank/vp 三票，cs 走独立强度表），拆开投喂会丢跨维交互。本轮四维共用一套消费链与实证底座，但**归因与提案须逐维分别给出**（见 §0 任务卡）。

**语料组装时的命题修正（须随语料告知模型，防其基于错误前提推理）**：

- 四维**不是「从未优化过」**——参数面已被大量扫描，且多处实证落默认：
  1. **共振**：12 参数阶段 7（2026-08-17）walk-forward 全扫；D-b 频率轴（MinMarketSampleCount/MidWindowBars）与 D-c label 阈值判零效应/跨窗矛盾；`optimize_resonance_parameters.py` 坐标下降跑过（产出不写回）；G4 Jump 确认门 2026-09-15 断线修复后真实生效（§4.1-D）。
  2. **趋势**：多周期动量 18 项 2026-08-17 参数化扫描；阶段 13（2026-09-09）MACD 周期族/死叉侧/zeroWeights 补扫全部冗余；P5（2026-09-15）漏网参数补扫；**五权重两层实证重定义落默认（阶段 22.8，57 次全量 replay）**；MA 因子阶段 17→21.8 评估后 maWeight 落默认 0.37。
  3. **热度**：票权 G2 实证落默认 1.0→阶段 23.9 降权 0.75；阈值族 P1-a 37 trial **默认即跨窗权衡峰**；强度表阶段 25 方案 B 13 trial **现值即峰**；persist 持续高位路径 H1 成立/H2 证伪维持关闭。
  4. **量价**：7 参数阶段 9 扫描；fund10（AbnormalFundRatio 20→10）2026-09-15 落默认；批 2 打分阶梯 24 参数阶段 25 方案 C-b 判**零效应冗余**；amount 族 P4 判零效应。
  5. **汇合面**：票权 23.9 两轮扫描 combo_three_quarter 落默认 + Track 1 交易层直验；B 档强度 0.8→0.7（B-202610 O3）落默认；三线（strong/weak/reverse）P2 复扫维持。
- **从未被做过的**（与生命周期轮同判）：各维的**结构级重设计**——输入特征集（哪条原料进判据）、档位判定结构、投票语义（方向主导×档位幅度的混合）、缺票/缺证据的处理语义、跨维信息架构（谁与谁冗余）。这是本轮推理的真实空间。
- GPT-OSS 已知幻觉率高（crowding 审定 5 幻觉全弃先例）→ 语料自包含 + 模型输出全部按「假设」处理，逐条人工核对后才可能进入验证。

**边界**：本包只做语料预处理，不改任何生产代码与判据；模型输出不构成改动授权；任何采纳的改动走正常流程（参数化 diff → replay/回测验证 → 用户裁决）。

---

## §0 任务卡（投喂开场，粘给模型）

你是量化交易系统评审专家。下面是一套 A 股短线系统里**四个投票信号维**（共振/趋势/热度/量价）与其汇合点（synergy 总档）的完整语料（代码逐字 + 全部已知实证 + 历史裁决）。系统对它们的定位是**方向信号**（与上一轮已审定的生命周期「环境门」正交：生命周期 E 否决/B·D 降档在票和之外干预，语料 §2.5）。你的任务：

1. **逐维归因诊断**：对四个维**分别**回答「它的方向判据还有多少可挖的区分度」，按固定顺序归因并排序：
   ①**原料/输入**（共振/趋势/热度全部只吃注意力排名序列，量价只吃当帧标量——是原料本身信息量到顶，还是有用原料没喂进判据？注意序列在时间上不规则：缺帧跳过、差分可跨日，§1.1）
   → ②**定义/判据设计**（窗口/阈值/档位结构/缺票语义/权重面）
   → ③**下游消费形态**（投票语义、票权、档位强度、阶梯线、saEx 只看 S/A 的盲区 §4.4）
   → 最后才是 ④**结构重设计**。
   每条归因必须引用语料证据（§编号），禁止无证据断言。**另加一问（跨维）**：四维里哪些互相冗余（如趋势 momentum_profile vs 共振 relative_momentum 同源）、哪些信息缺口没有任何维覆盖（对照 §1.1 原料矩阵）？
2. **优化提案 ≤5 条**，分级给出：
   - **L1 参数/阈值级**（现有 replay harness 即可验证）——注意 §4.2 已证伪清单很大，若仍提已扫参数面上的提案，必须说明为何能绕开已登记根因（零效应/跨窗矛盾/默认即峰），否则不要提；
   - **L2 结构级**（特征增删 / 档位判定改造 / 缺票语义调整 / 投票语义调整——需预登记 + 专项 harness）；
   - **L3 重设计级**（换信号本体/换维度架构——需先立项论证，只给论证不给实现）。
   每条提案必须包含：具体改法（伪代码或伪判据）、预期改变 §4 中哪些历史读数、验证设计（窗口/样本量/判定线）、失效风险与回退方式、**为什么它不在 §4.2 已证伪清单里**。
3. **反面检查**：显式列出你认为语料证据不足、内部矛盾、或需要先补数据/读代码才能判断的点（没有就写「无」）。

**反幻觉铁律**：
- 只允许使用本语料推理；引用结论必须标注 §编号；
- 禁止编造字段名、数字、外部文献、本语料没有的代码；不确定就写「未知/证据不足」；
- 若你认为语料内部自相矛盾，显式指出（会被逐条人工核对，抓出真矛盾有额外价值）；
- 禁止朝已知结论拟合：优化目标是「结构信号区分度 + 交易层 wrxpf」，不是「把某个历史读数调好看」；
- 市况依赖是本系统多次复现的教训（§4.4）：任何提案必须回答「它在强情绪期和退潮期分别会怎样」。

---

## §1 系统与数据上下文

| 项 | 事实 |
|---|---|
| 引擎 | QuantBoard Python RankTrend 引擎（`quant-board/backend/analysis/ranktrend/`，golden 生产事实标准）；TS 前端同构消费 |
| 数据 | 盘中快照帧，`snapshot_type=half_hour`（每交易日约 10 帧，09:30–15:00 每半小时）；回测数据集 `dragonboard_live` |
| 池规模 | 热榜池每帧 ≈200 只（八平台热榜合并 avgRankNum 综合排名决定池子，769 帧时代 ≈204 只/帧） |
| 证据窗口 | decision 2026-04-15~07-31 / oos1 08-15~08-31 / oos2 09-01~09-12（三窗是本系统既有锚体系）；**8 月自 2026-08-19 冻结为独立复核窗，任何参数不得再以 8 月为调参依据**（§4.4） |
| 五位信号框架 | **4 个股投票维（res/rank/vp/cs）+ 生命周期环境门（lc，E 否决/B·D 降档）+ 2 关闭观察维（pm 价格动量/dv 量名背离，票权 0.0）**；官方口径原文为「5 投票维（res/rank/vp/cs + 热榜情绪）+ 1 环境门」（`ranktrend-four-dimension-column-plan.md:5`）——第 5 维「热榜情绪」是市场级门（regime，正交，§3#2），个股视角投票维为 4。**勘误注记（模型A 审定轮 2026-10-07）**：本行原误写「5 投票维（res/rank/vp/cs）」4 代号配 5 之数，模型A 反面检查抓出，主会话对照原档核实为口径混写 |
| 词表 | 各维 signalTier 字母表**不同维不同**：res=S/A/B/C/D/unknown（无 E）；rank=S/A/B/C/D；cs=A/B/C/D/unknown（无 S/E）；**vp=unknown/E/C/A/B/D（无 S——模型B 审定轮 2026-10-07 抓出，原误记全体含 S/E）**；synergy 总档 S/A/B/C/D/E；候选分层 A_MAIN/B_IGNITION/C_CROWDED/D_EXIT_RISK/N_NEUTRAL |
| 上一轮已定事实 | 生命周期 G1 时间正规化已落默认（2026-10-07，`lifecycleTimeGapStrictness="cross_day"`）——**当前基线代际已变**（§4.4）；P3 诊断证据（跨日假动量）对本轮四维的适用性是公开问题（§6-Q1） |

### §1.1 输入序列构造与各维原料矩阵

每帧对每只股票：取该股在**当帧热榜**里的注意力排名 `rank`（avgRankNum 升序重排名次）与其百分位 `percentile`，滚动最近 50 帧拼成序列 `ranks[]`/`percentiles[]`。**关键实现原文**（`engine/primitives.py:64`）：

```python
def percentile_rank(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100
```

重排名（`engine/primitives.py:70` `attention_rank_lookup` 摘要）：过滤 avgRankNum>0，按 (avgRankNum, code) 升序重排，`percentile`=该序号换算百分位（**100=榜单第 1 名**）；综合排名只决定池子大小不参与百分位。

**输入语义要点（推理必读）**：

1. **缺帧直接跳过、不插值**：股票出入池使序列在时间上不规则——`percentiles[-1]-percentiles[-2]`（热度 delta）、共振 short/mid 差分、趋势 [3,5,8,13,21] 动量、MACD/MA 的全窗 EMA/均值**全部建立在序号口径上，元素间可能跨缺口甚至跨交易日**。生命周期 P3 诊断已实证「跨日差分制造假动量」（velocity>18 帧 42% 为跨日缺口 origin，ER=3.33，见 `reasoning-corpus-lifecycle-stage.md` §12），但 G1 修复**只落在生命周期的 cycle metrics**（`lifecycle.py` analyze_cycle 内），**其余四维的差分没有任何时间正规化**（代码事实：`cross_section.py:142` delta、`runtime.py:680-681` short/mid_change、`technical.py:8-17` period_momentum 均直接序列下标差）。
2. **池总规模逐帧时变（≈200 有波动）**：percentile 是相对量、rank 是绝对量。四维中只有热度/趋势/共振吃 percentile（相对口径），量价不吃排名。
3. replay/replay 链路序列末项就是当帧真值；live 链路热度维有「权威 pct 复制尾」处理（`runtime.py:1354-1355` 注释），对回测证据无影响。
4. **同一 `_replay_stock` 里现成有 `price_changes`（涨跌幅序列）、`amount_history`（成交额序列）**，帧里还有 `volumeRatio/zlje/zljzb/change` 当帧标量——四维里只有量价吃了标量与成交额量比；**价格序列目前只进关闭的观察维 pm（票权 0）与 dv（票权 0）**（接线 `runtime.py:1368/1383`），三个排名系信号维（res/rank/cs）全部没有价格/资金原料。

**各维原料矩阵**（谁吃什么，推理第一轴）：

| 维 | 原料 | 时间结构 | 缺票/缺证据出口 |
|---|---|---|---|
| 共振 res | percentiles 序列 + 市场横截面 median 短变化（4 市场帧窗）+ Jump 事件（全序列累计）+ 新入榜标记 | 序列序偏移 3/8 bars + 8 bar 路径窗 | 6 个 insufficient 出口（§2.1），signalTier="unknown" 票=0 |
| 趋势 rank | percentiles 序列（**唯一原料**）；序列不足时 fallback 吃当帧标量 displayChange/stockChange/volumeRatio/zlje/zljzb | [3,5,8,13,21] 序偏移动量 + MACD 全窗 EMA + MA10/20 | 样本 < max(periods)+1=22 → fallback_signals；hold=C 档 |
| 热度 cs | percentiles 序列最后两帧（delta）+ 当前帧 + 市场 median percentile | **单帧差分** + persist 窗（默认关） | percentile 不可得 → unknown 票=0；首帧缺 delta → 降级绝对档 |
| 量价 vp | 当帧标量 change/volumeRatio/zlje/zljzb + amount_ratio（成交额 5 帧均量比） | 当帧 + 5 帧均额 | change/vr 缺失或 vr≤0 → unknown 票=0；amount 缺失不参与（fail-visible） |
| （对照）pm/dv | price_changes 序列 / price×rank 单帧交叉 | — | 票权 0.0 纯观察（实证负贡献关闭，§4.2-E） |

---

## §2 算法定义（源码逐字）

> 全部源码来自 `backend/analysis/ranktrend/engine/runtime.py`、`trend/technical.py`、`trend/cross_section.py`、`ranking/volume_price.py`、`engine/config.py` 当前工作区状态。逐字引用（个别长函数因排版删节 boilerplate/辅助函数，删节处标注行号与一句话语义，逐 token 语义未动）。

### §2.0 汇合点：`_synergy_tier`（`ranking/volume_price.py:329-466`）——四维投票合成

门控枚举校验与非法值 fail-fast（:360-373，lifecycle/vp 三组 gate mode 枚举 + 非负校验）删节。核心逐字：

```python
    lc_e_negative_vote = False
    if lc_tier == "E":
        if veto_mode == "hard" or (veto_mode == "soft" and _lc_veto_keep_hard(c, lc_veto_path)):
            return "E", ["周期一票否决"]
        if veto_mode == "soft":
            lc_e_negative_vote = True

    vp_e_forced_vote: float | None = None
    if vp_tier == "E":
        if vp_gate_mode == "hard":
            return "D", ["量价出货硬风险"]
        strengths = getattr(c, "tierSynergyVoteStrengths") or []
        e_strength = strengths[_VOTE_STRENGTH_ORDER.index("E")] if len(strengths) == 6 else _VOTE_STRENGTH_FALLBACK["E"]
        vp_weight = float(getattr(c, "tierSynergyVolumePriceVote", 1.0) or 0.0)
        vp_e_forced_vote = 0.0 if vp_gate_mode == "off" else -e_strength * vp_weight

    _CS_STRENGTH_ORDER = ("A", "B", "C", "D")  # 强度值 2026-09-14 参数化（config.tierSynergyCsStrengths）
    cs_strengths = list(getattr(c, "tierSynergyCsStrengths") or [])
    _CS_STRENGTH = dict(zip(_CS_STRENGTH_ORDER, cs_strengths)) if len(cs_strengths) == 4 else {"A": 1.0, "B": 0.5, "C": -0.5, "D": -1.0}

    def _vote(tier: str | None, direction: str | None) -> float:
        if tier in ("unknown", None) or not direction:
            return 0.0
        strengths = getattr(c, "tierSynergyVoteStrengths") or []
        strength = strengths[_VOTE_STRENGTH_ORDER.index(tier)] if tier in _VOTE_STRENGTH_ORDER and len(strengths) == 6 else _VOTE_STRENGTH_FALLBACK.get(tier, 0.0)
        if direction in ("buy", "up"):
            return strength
        if direction in ("sell", "down"):
            return -strength
        return 0.0

    v = (
        _vote(res_tier, res_dir) * float(getattr(c, "tierSynergyResonanceVote", 1.0) or 0.0)
        + _vote(rank_tier, rank_dir) * float(getattr(c, "tierSynergyRankVote", 1.0) or 0.0)
        + (_vote(vp_tier, vp_dir) * float(getattr(c, "tierSynergyVolumePriceVote", 1.0) or 0.0) if vp_e_forced_vote is None else vp_e_forced_vote)
    )
    cs_weight = float(getattr(c, "tierSynergyCrossSectionVote", 0.0) or 0.0)
    if cs_weight and cs_tier and cs_tier in _CS_STRENGTH:
        v += _CS_STRENGTH[cs_tier] * cs_weight
    pm_weight = float(getattr(c, "tierSynergyPriceMomentumVote", 0.0) or 0.0)
    if pm_weight and pm_tier and pm_tier in _CS_STRENGTH:
        v += _CS_STRENGTH[pm_tier] * pm_weight
    dv_weight = float(getattr(c, "tierSynergyDivergenceVote", 0.0) or 0.0)
    if dv_weight and dv_tier and dv_tier in _CS_STRENGTH:
        v += _CS_STRENGTH[dv_tier] * dv_weight

    gate_reasons: list[str] = []
    if lc_e_negative_vote:
        v -= veto_strength
        gate_reasons.append("周期否决负票（soft）")
    if vp_e_forced_vote is not None and vp_gate_mode == "soft":
        gate_reasons.append("量价出货负票（soft）")

    def _ladder(vote_sum: float) -> tuple[str, list[str]]:
        if vote_sum >= c.tierSynergyVoteStrong + 1:
            return "S", ["方向一致强买（档位加权高分）"]
        if vote_sum >= c.tierSynergyVoteStrong:
            return "A", ["方向一致强买"]
        if vote_sum >= c.tierSynergyVoteWeak:
            return "B", ["方向分歧，弱买"]
        if vote_sum <= c.tierSynergyVoteReverse:
            return "D", ["反向"]
        return "C", ["无明确方向"]

    tier, reasons = _ladder(v)
    reasons = reasons + gate_reasons
    if lc_tier in ("B", "D") and tier in ("S", "A"):
        if downgrade_mode == "hard":
            tier = "A" if tier == "S" else "B"
            reasons = reasons + [f"周期 {lc_tier} 环境降档"]
        elif downgrade_mode == "soft":
            first_tier = tier
            tier, _ = _ladder(v - downgrade_penalty)
            if tier != first_tier:
                reasons = reasons + [f"周期 {lc_tier} 环境惩罚（{first_tier}→{tier}，soft）"]
    return tier, reasons
```

**投票语义要点**：
- 三主维票 = `strength(tier) × dir_sign`（方向主导：D/E 档 buy 仍正票）× 票权；cs/pm/dv 票 = 档位自带符号（A/B 正、C/D 负）× 独立强度表 × 票权——**cs 的 C 档天然负票 −0.5×0.75=−0.375**，即「无强势证据」的股票从第 5 维吃一张固定负票；
- 当前默认票权 res/rank/cs=0.75、vp=1.0；`tierSynergyVoteStrengths=[1.2,1.0,0.7,0.5,1.0,1.0]`（S/A/B/C/D/E）；A 线 2.0、S 线 3.0（=strong+1）、B 线 1.0、D 线 −1.0。**勘误注记（模型B 审定轮 2026-10-07，主会话代码核实为真）**：本节原写「max vote=3.75、三主维全 S 同 buy（0.9+0.9+1.2）恰好够」——把 vp 按 S 档强度 1.2 计入，但 `_volume_price_tier` 的字母表**无 S**（§2.4），vp 最高 A 档（票 1.0×1.0）。**真实上限 = res S(0.9)+rank S(0.9)+vp A(1.0)+cs A(0.75)=3.55**；且**无 cs 正票时上限 2.8<3.0 → synergy S 档结构上要求 cs 投 A/B 正票（cs 是 S 的守门维，与 §4.3-2 的 C 档负票叠加放大 Q4）**；
- 两处结构短路（默认 hard）：lc E → 直接 E；**vp E → 直接 D（「量价出货硬风险」，位阶高于票和）**；
- VoteStrengths 只乘 res/rank/vp 三票（`volume_price.py:415-418`），cs 走 `tierSynergyCsStrengths` 独立映射（P2-0 消费面核实）。

### §2.1 共振 resonance（`engine/runtime.py:514-748`）

模块常量 fallback（:514-518）：`RESONANCE_SHORT/MID/PATH_WINDOW_BARS=3/8/8`、`MIN_SERIES=MID+1`、`MIN_MARKET_SAMPLE=20`（现值全读 config）。

**Jump 事件检测**（`detect_rank_jumps`，`runtime.py:112-205`，逐字核心）：

```python
def detect_rank_jumps(percentiles, ranks=None, delta_pct=10.0, reset_lookback=3, sustain_count=2):
    """内生阈值排名跳跃检测。
    持续追踪累计排名百分位变化，当 |累计变化| > delta 时触发事件。
    核心原理：波动爆发（来回震荡）的累计变化互相抵消，达不到阈值；
    只有不可逆的趋势性移动才会触发。"""
    if len(percentiles) < 3:
        return {"event": "none", "direction": "hold", ...}  # 结构省略（全默认值）
    ref = percentiles[0]
    events: list[dict[str, Any]] = []
    for i, p in enumerate(percentiles):
        cum_change = p - ref
        if abs(cum_change) > delta_pct:
            events.append({
                "index": i,
                "direction": "surge" if cum_change > 0 else "collapse",
                "magnitude": round(abs(cum_change), 2),
                "overshoot": round(abs(cum_change) - delta_pct, 2),
                "percentile": round(p, 2),
            })
            # 重置到近期均价而非当前极值，防止极端值误触反向事件
            lookback = min(reset_lookback, i + 1)
            ref = sum(percentiles[i - lookback + 1 : i + 1]) / lookback
    if not events:
        return {"event": "none", "direction": "hold", ..., "cumulativeChange": round(cum, 2)}
    latest = events[-1]
    surge_count = sum(1 for e in events if e["direction"] == "surge")
    collapse_count = sum(1 for e in events if e["direction"] == "collapse")
    sustained = surge_count >= sustain_count or collapse_count >= sustain_count
    direction = "buy" if latest["direction"] == "surge" else "sell"
    mag = latest["magnitude"]; overshoot = latest["overshoot"]
    mag_factor = min(1.0, mag / max(delta_pct * 2, 1))
    overshoot_factor = min(1.0, overshoot / max(delta_pct, 1))
    sustain_bonus = 0.20 if sustained else 0
    confidence = clamp(55 + 25 * mag_factor + 15 * overshoot_factor + 20 * sustain_bonus, 50, 95)
    return {"event": "jump", "direction": direction, "signal": direction, "magnitude": ..., "overshoot": ...,
            "delta": delta_pct, "sustained": sustained, "confidence": ..., "eventCount": len(events),
            "surgeCount": surge_count, "collapseCount": collapse_count, "rankMagnitude": ...,
            "events": [{"index": e["index"], "direction": e["direction"], "magnitude": e["magnitude"]} for e in events]}
```

生产调用（`runtime.py:1233/1245`）：`jump = detect_rank_jumps(percentiles, ranks, config.jumpDeltaPct=15.0, config.jumpResetLookback=3, config.jumpSustainCount=2)` → `jump = _confirm_jump(jump, stock, config)`。

**Jump 价格/量确认门**（`_confirm_jump`，`runtime.py:208-258` 摘要）：buy 需 `change ≥ jumpConfirmChangeMin(3.0)` 且 `volumeRatio ≥ jumpConfirmVolumeRatioMin(1.0)`；sell 需 `change ≤ −3.0` 且 vr≥1.0；不满足 → direction 降级 hold + events 内 direction 同步降级（2026-08-19 P0-1 口径一致）+ `unconfirmedReasons` 记录（fail-visible）。**断线史**：2026-08-17 上线至 2026-09-15 修复前，确认分支只匹配 "up"/"down" 而生产枚举是 buy/sell——10936 事件全部无条件放行，门从未实际过滤；修复后真实生效（代际效应见 §4.1-D）。

**市场横截面上下文**（`frame_market_median`，`runtime.py:39-57`，逐字）：

```python
def frame_market_median(frames, index):
    """当前帧与前第 3 个市场帧公共股票的 attention 百分位变化中位数；sampleCount = 当前帧横截面股票数。
    窗口不足 4 帧 / 公共样本 <20 → 返回 None（横截面不可算，fail-visible）。"""
    start = max(0, index - 3)
    window = frames[start : index + 1]
    current = frame_cross_section(window[-1])
    sample_count = len(current)
    if len(window) < 4 or not current:
        return None, sample_count
    first = frame_cross_section(window[0])
    changes: list[float] = []
    for code, current_pct in current.items():
        first_pct = first.get(code)
        if first_pct is not None:
            changes.append(current_pct - first_pct)
    if len(changes) < 20:
        return None, sample_count
    return median_of(changes), sample_count
```

（`frame_cross_section` = 该帧 `{code: percentile_rank}` 表，`runtime.py:36`。）market_ctx 在 replay 逐帧构造（`runtime.py:958`），存在时才计算共振（`runtime.py:1390`）——阶段 3 修复方向 1 后 replay 链路共振参与投票。**残留硬编码注记（模型B 审定轮 2026-10-07）**：本函数窗口三处字面量（`index−3` 回看、`len(window)<4`、公共股 `<20`）**未参数化**——`<20` 与 config.resonanceMinMarketSampleCount 是两个独立判定（后者在 analyze_rank_resonance 内），勿混。

**主函数**（`analyze_rank_resonance`，`runtime.py:603-748`）——六个 insufficient 出口（timeline 无效/新入榜关注度无效/横截面样本不足×2/排名序列不足或无效/快照样本不足，:619-673）结构相同（status="insufficient"、signalTier="unknown"），逐字核心：

新入榜分支（`isNew = len(percentiles)==1`，:623-661）：

```python
    if is_new_entry:
        ...
        jump_events = jump.get("events") or []
        jump_freshness = 1.0 if jump_events else 0.0
        entry_strength = clamp((current_attention_percentile - 50) / c.resonanceEntryStrengthScale, 0, 1)
        score = round(100 * clamp(c.resonanceNewEntryWeights[0] * entry_strength + c.resonanceNewEntryWeights[1] * jump_freshness, 0, 1))
        if jump_freshness >= c.tierResonanceJumpFreshnessMin and entry_strength > 0:
            _tier, _tier_reasons = "S", ["Jump 事件驱动，排名跳跃式上升"]
            # 审定注记（模型A 轮 2026-10-07，主会话代码核实为真）：本 S 分支为死代码——
            # 新入榜 len==1 < detect_rank_jumps 的 len>=3 门槛（runtime.py:137）⇒ events 恒空
            # ⇒ jump_freshness 恒 0.0 < 0.5，S 永不可达；新入榜首帧最高 A 档（entry_strength>=0.3）。
        elif entry_strength >= c.tierResonanceEntryStrengthMin:
            _tier, _tier_reasons = "A", ["新入榜关注度较强"]
        elif entry_strength > 0:
            _tier, _tier_reasons = "B", ["新入榜关注度较弱"]
        else:
            _tier, _tier_reasons = "C", ["新入榜关注度中性"]
        return {"status": "ok", "direction": "buy" if entry_strength > 0 else "hold", "score": score,
                "label": ..., "relativeMomentum": entry_strength, "acceleration": 0, "persistence": 0,
                "jumpFreshness": jump_freshness, "reversalPenalty": 0, "historyState": "new_entry", ...,
                "signalTier": _tier, "tierReasons": _tier_reasons}
```

常规分支（:675-748，逐字）：

```python
    last_index = len(percentiles) - 1
    short_start_index = last_index - c.resonanceShortWindowBars
    mid_start_index = last_index - c.resonanceMidWindowBars
    short_bars = last_index - short_start_index
    mid_bars = last_index - mid_start_index
    short_change = percentiles[last_index] - percentiles[short_start_index]
    mid_change = percentiles[last_index] - percentiles[mid_start_index]
    relative_momentum = clamp((short_change - market_median_short_change) / c.resonanceMomentumScale, -1, 1)
    acceleration = clamp((short_change - (mid_change * short_bars) / mid_bars) / c.resonanceAccelerationScale, -1, 1)

    path_percentiles = percentiles[-(c.resonancePathWindowBars + 1):]
    changes = [path_percentiles[i + 1] - path_percentiles[i] for i in range(len(path_percentiles) - 1)]
    path_direction = 1 if (short_change or mid_change) > 0 else -1 if (short_change or mid_change) < 0 else 0
    directional_changes = [
        value for value in changes
        if path_direction != 0 and (1 if value > 0 else -1 if value < 0 else 0) == path_direction
    ]
    persistence = len(directional_changes) / len(changes) if changes else 0
    if len(changes) > 1:
        direction_switch_rate = sum(
            1 for i in range(1, len(changes))
            if math.copysign(1, changes[i]) != 0 and math.copysign(1, changes[i - 1]) != 0
            and math.copysign(1, changes[i]) != math.copysign(1, changes[i - 1])
        ) / (len(changes) - 1)
    else:
        direction_switch_rate = 0
    recent_peak = max(path_percentiles)
    percentile_drawdown = max(0, recent_peak - percentiles[last_index])
    reversal_penalty = clamp(c.resonanceReversalSwitchWeight * direction_switch_rate + c.resonanceReversalDrawdownWeight * percentile_drawdown / c.resonanceReversalDrawdownScale, 0, 1)

    jump_events = jump.get("events") or []
    latest_event = jump_events[-1] if jump_events else None
    jump_freshness = math.exp(-(last_index - int(latest_event["index"])) / c.resonanceJumpFreshnessDecay) if latest_event else 0
    direction_score = relative_momentum + acceleration + c.resonancePathDirectionWeight * path_direction * persistence
    base_direction = "buy" if direction_score > c.resonanceDirectionThreshold else "sell" if direction_score < -c.resonanceDirectionThreshold else "hold"
    has_reverse_jump = (
        (base_direction == "buy" and jump.get("direction") == "sell")
        or (base_direction == "sell" and jump.get("direction") == "buy")
    )
    direction = jump.get("direction") if jump.get("event") == "jump" and has_reverse_jump else base_direction

    directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
    directional_acceleration = -acceleration if direction == "sell" else acceleration
    raw_score = (
        c.resonanceWeights[0] * _positive(directional_momentum)
        + c.resonanceWeights[1] * _positive(directional_acceleration)
        + c.resonanceWeights[2] * persistence
        + c.resonanceWeights[3] * jump_freshness
        - c.resonanceWeights[4] * reversal_penalty
    )
    score = round(100 * clamp(raw_score, 0, 1))
    _tier, _tier_reasons = _resonance_tier(direction, persistence, jump.get("event"), jump_freshness, reversal_penalty, config)
```

（输出含 relativeMomentum/acceleration/persistence/jumpFreshness/reversalPenalty/marketMedian*/signalTier 等，:727-748。）

**档位判定**（`_resonance_tier`，`runtime.py:550-570`，逐字）：

```python
def _resonance_tier(direction, persistence, jump_event, jump_freshness, reversal_penalty, config=None):
    c = config or RankTrendConfig()
    if reversal_penalty >= c.tierResonanceReversalPenaltyMin:
        return "D", [f"反转惩罚高 {round(reversal_penalty * 100)}%"]
    if jump_event == "jump" and direction == "buy" and jump_freshness >= c.tierResonanceJumpFreshnessMin:
        return "S", ["Jump 事件驱动，排名跳跃式上升"]
    if direction == "buy" and persistence >= c.tierResonancePersistenceMin:
        return "A", ["方向确认 + 路径持续"]
    if direction == "buy":
        return "B", ["方向确认但路径持续不足"]
    if direction == "hold":
        return "C", ["中性"]
    return "D", ["共振衰竭/反向"]
```

**关键代码事实**：`resonanceWeights`（raw_score 五权重）与 `resonanceLabelThresholds`（label 阈值）**只影响 score/label 展示面，不影响 signalTier 与投票**——`_resonance_tier` 只消费 (direction, persistence, jump_event, jump_freshness, reversal_penalty) 五输入（D-c 实证 zero_effect 同判）。

### §2.2 趋势 rankTrend（`trend/technical.py` + `engine/runtime.py:274-365`）

**多周期动量数据**（`momentum_data`，`technical.py:209-225`，逐字）：

```python
def momentum_data(percentiles, config):
    if len(percentiles) < max(config.momentumPeriods) + 1:
        return None
    values = [period_momentum(percentiles, period) for period in config.momentumPeriods]
    prev_values = [prev_period_momentum(percentiles, period) for period in config.momentumPeriods]
    score = 0.0
    for index, value in enumerate(values):
        buy = config.buyThresholds[index]
        sell = config.sellThresholds[index]
        weight = config.momentumWeights[index]
        if value >= 0:
            score += math.tanh(value / max(1e-6, abs(buy))) * 100 * weight
        else:
            score -= math.tanh(abs(value) / max(1e-6, abs(sell))) * 100 * weight
    score = clamp(score, -100, 100)
    signal = "buy" if score >= config.momentumScoreThreshold else "sell" if score <= -config.momentumScoreThreshold else "hold"
    return {"values": values, "prevValues": prev_values, "score": score, "signal": signal,
            "confidence": clamp(50 + abs(score) * config.momentumConfidenceSlope, 50, 95)}
```

（`period_momentum(p, n) = p[-1] − p[-1-n]`，`prev_period_momentum = p[-2] − p[-2-n]`，`technical.py:8-17`——**纯序列序差分**。）

**三分量信号**（`analyze_momentum_signals`，`technical.py:228-301`，核心逐字）：

```python
    period_scores = [normalize_signed(values[i], buy[i], abs(sell[i])) for i in range(count)]
    direction_raw = sum(period_scores[i] * weights[i] for i in range(count))
    positive_share = weighted_share(period_scores, weights, lambda score, _: score > 0)
    negative_share = weighted_share(period_scores, weights, lambda score, _: score < 0)
    share_boost = config.momentumDirectionShareBoost
    direction_score = clamp(direction_raw * (share_boost[0] + share_boost[1] * max(positive_share, negative_share)), -1, 1)
    long_window = period_scores[-min(2, len(period_scores)):]
    long_oppose_buy = len(long_window) == 2 and all(score <= -config.momentumLongOpposeThreshold for score in long_window)
    long_oppose_sell = len(long_window) == 2 and all(score >= config.momentumLongOpposeThreshold for score in long_window)
    direction_signal = "hold"
    if direction_score >= config.momentumDirectionThreshold and positive_share >= config.momentumSignalShareMin and not long_oppose_buy:
        direction_signal = "buy"
    elif direction_score <= -config.momentumDirectionThreshold and negative_share >= config.momentumSignalShareMin and not long_oppose_sell:
        direction_signal = "sell"

    accelerations = [values[i] - prev_values[i] for i in range(count)]
    accel_scores = [normalize_signed(accelerations[i], buy[i], abs(sell[i])) for i in range(count)]
    accel_raw = sum(accel_scores[i] * weights[i] for i in range(count))
    short_scores = accel_scores[:min(2, len(accel_scores))]
    accel_boost = config.momentumAccelShareBoost
    accel_score = clamp(accel_raw * (accel_boost[0] + accel_boost[1] * average([abs(score) for score in short_scores])), -1, 1)
    accel_signal = "hold"
    if accel_score >= config.momentumAccelThreshold and any(score > 0 for score in short_scores):
        accel_signal = "buy"
    elif accel_score <= -config.momentumAccelThreshold and any(score < 0 for score in short_scores):
        accel_signal = "sell"

    # zeroCross：trigger = values[0]（最短周期 3）上穿/下穿 0，confirm = values[1]（周期 5）同向
    if count >= 2:
        trigger_now = values[0]
        trigger_prev = prev_values[0]
        confirm_score = normalize_signed(values[1], buy[1], abs(sell[1]))
        trigger_strength = min(1, abs(normalize_signed(trigger_now, buy[0], abs(sell[0]))))
        confirm_strength = min(1, abs(confirm_score))
        zero_weights = config.momentumZeroWeights
        if trigger_prev <= 0 < trigger_now and confirm_score >= -config.momentumZeroConfirmThreshold:
            zero_signal = "buy"
            zero_score = clamp(zero_weights[0] * trigger_strength + zero_weights[1] * max(0, confirm_strength), -1, 1)
        elif trigger_prev >= 0 > trigger_now and confirm_score <= config.momentumZeroConfirmThreshold:
            zero_signal = "sell"
            zero_score = -clamp(zero_weights[0] * trigger_strength + zero_weights[1] * max(0, confirm_strength), 0, 1)
        strong_confirm = ((zero_signal == "buy" and confirm_score > config.momentumZeroStrongConfirmThreshold)
                          or (zero_signal == "sell" and confirm_score < -config.momentumZeroStrongConfirmThreshold))
        zero_conf = signal_confidence(zero_score, config.momentumZeroStrongConfirmBonus if strong_confirm else 0)
```

（normalize_signed = 值/阈值线性归一到 [−1,1] 截断，`primitives.py`；confidence 公式删节处只进 confidence 不进信号。）

**MACD**（`calculate_macd`，`technical.py:38-90`，结构+判据逐字）：EMA(fast=13)/EMA(slow=21) 之差 dif、dea=EMA(dif, signal=8)、hist=2(dif−dea)；交叉检测 `prev_dif<=prev_dea and dif>dea → golden`（反向 death）；`warm_gaps = hist_series[macdSlow-1:]/2`（预热后）、lookback=`min(max(macdSignal,3), len)`、`gap_scale=avg(|lookback|)`；golden strong 需 `hist>0 and gap>0 and gap>prev_gap and hist>=prev_hist and strong_gap>=0.2 and gap >= max(1e-6, gap_scale*0.18)`；death valid 需 `hist<0 and gap<0 and (|gap| >= gap_scale*0.12 or strong_gap>=0.18)`；rawScore=±`clamp(0.7*strong_gap + 0.3*impulse, 0, 1)`（strong_gap/impulse 均为 tanh(gap/gap_scale) 形态）。**输入是排名百分位序列而非价格**。

**MA 交叉**（`calculate_ma_cross`，`technical.py:93-127`，判据逐字）：fast=均值(percentiles[-10:])、slow=均值(percentiles[-20:])；样本 < slow_period → state="unknown" 不伪造；交叉帧 rawScore=+1/−1（golden/death），非交叉帧 0——**二值事件型分量**。

**动量画像**（`momentum_profile`，`technical.py:130-153`，逐字——喂生命周期/候选池，不进趋势投票）：

```python
    short_periods = [1, 3, 5]
    mid_periods = [5, 8, 13]
    long_periods = [13, 21]
    short = avg_mom(short_periods)
    mid = avg_mom(mid_periods)
    long = avg_mom(long_periods)
    acceleration = average([short - avg_prev(short_periods), mid - avg_prev(mid_periods)])
    shock = rank_shock(percentiles, 10)
    composite = clamp(0.35 * short + 0.4 * mid + 0.25 * long + 0.2 * acceleration, -100, 100)
```

（`rank_shock(p, lookback)` = 末位速度对末 lookback 个速度差的 z 分数，clamp ±5，`technical.py:156-171`。）

**决策合成**（`compose_decision`，`runtime.py:274-322`，逐字核心）：

```python
    components = [
        {"signal": technical["signals"]["direction"]["signal"], "rawScore": clamp(technical["signals"]["direction"]["score"], -1, 1), "weight": config.directionWeight},
        {"signal": technical["signals"]["acceleration"]["signal"], "rawScore": clamp(technical["signals"]["acceleration"]["score"], -1, 1), "weight": config.accelerationWeight},
        {"signal": technical["signals"]["zeroCross"]["signal"], "rawScore": clamp(technical["signals"]["zeroCross"]["score"], -1, 1), "weight": config.crossWeight},
        {"signal": cross_signal(technical["macd"]["cross"]), "rawScore": clamp(technical["macd"]["rawScore"], -1, 1), "weight": config.macdWeight},
    ]
    if config.maWeight > 0:
        ma_cross = technical.get("maCross") or {}
        components.append({"signal": cross_signal(str(ma_cross.get("cross") or "none")),
                           "rawScore": clamp(float(ma_cross.get("rawScore") or 0.0), -1, 1), "weight": config.maWeight})
    combined = sum(c["rawScore"] * c["weight"] for c in components)
    positive = sum(c["weight"] * max(c["rawScore"], 0) for c in components)
    negative = sum(c["weight"] * max(-c["rawScore"], 0) for c in components)
    buy_count = len([c for c in components if c["signal"] == "buy"])
    sell_count = len([c for c in components if c["signal"] == "sell"])
    base = "hold"
    macd_golden = technical["macd"]["cross"] == "golden"
    if buy_count >= config.decisionMinAgreement and sell_count <= config.decisionMaxOpposition and combined >= config.buyScoreThreshold:
        if config.requireMacdGoldenCross and not macd_golden:
            base = "hold"
        else:
            base = "buy"
    elif sell_count >= config.decisionMinAgreement and buy_count <= config.decisionMaxOpposition and combined <= config.sellScoreThreshold:
        base = "sell"
```

（confidence 公式与风险惩罚/reversal 降级 hold 见 :311-322，只影响 confidence/final 不改 base。）**五权重当前默认：direction 0.06 / acceleration 0.04 / cross 0.24 / macd 0.29 / ma 0.37（和恒=1，阶段 22.8 实证落默认）——连续分量 direction/acceleration 合计只剩 0.10，决策几乎由三个事件型二值分量（zeroCross 交叉/MACD 交叉/MA 交叉）驱动。**

**档位判定**（`_rank_trend_tier`，`runtime.py:353-365`，逐字）：

```python
def _rank_trend_tier(base_signal, combined, config=None):
    c = config or RankTrendConfig()
    if base_signal == "hold":
        return "C", ["中性"]
    if base_signal == "sell":
        return "D", ["趋势转弱/反向"]
    a = abs(combined)
    if a >= c.tierRankTrendStrongMin:
        return "S", ["强趋势，加权强度远超阈值"]
    if a >= c.tierRankTrendConfirmMin:
        return "A", ["趋势确认"]
    return "B", ["弱趋势，勉强越过阈值"]
```

**fallback**（`fallback_signals`，`technical.py:325-400`，结构摘要）：序列不足 22 帧时用当帧标量（displayChange/stockChange/volumeRatio/zlje/zljzb）加权合成 direction/acceleration/zeroCross 三分量的兜底信号（权重 `fallback*Weights` 全参数化），末行 `weighted([(display, 0.45), (price, 0.35), (capital, 0.2)]) * 100` 为 momentumScore——**趋势维唯一的非排名原料入口**。

### §2.3 热度 crossSection（`trend/cross_section.py`）

档位判定（`_tier_from`，`cross_section.py:63-102`，逐字）：

```python
def _tier_from(percentile, delta, persist, c):
    if delta is not None:
        if percentile >= c.crossSectionStrongMin and delta >= c.crossSectionStrongDeltaUp:
            return "A", ["高位 + 热度排名上升（横截面强势确认）"]
        if (persist is not None and percentile >= c.crossSectionPersistMin and persist[1] >= c.crossSectionPersistMeanMin):
            return "A", [f"持续高位（近{persist[0]}帧均值 {persist[1]:.1f}）"]
        if percentile >= c.crossSectionMidMin and delta >= c.crossSectionMidDeltaUp:
            return "B", ["中位之上 + 热度显著上升"]
        if percentile <= c.crossSectionWeakMax and delta <= c.crossSectionWeakDeltaDown:
            return "D", ["低位 + 热度排名下降（横截面弱势确认）"]
        if percentile <= c.crossSectionMidMax and delta <= c.crossSectionMidDeltaDown:
            return "C", ["热度排名显著下降"]
        if percentile >= c.crossSectionStrongAbsMin:
            return "B", ["横截面高位"]
        if percentile <= 30:
            return "C", ["横截面低位"]
        # 中位区间 + 无明显变化：保守偏弱（无强势证据）
        return "C", ["中位区间无强势证据"]
    # 首帧缺 delta：绝对档降级，不给 A/D
    if percentile >= c.crossSectionStrongMin:
        return "B", ["高位但缺 delta 确认（首帧）"]
    if percentile >= c.crossSectionStrongAbsMin:
        return "B", ["横截面高位（首帧缺 delta）"]
    if percentile <= c.crossSectionWeakMax:
        return "C", ["低位但缺 delta 确认（首帧）"]
    return "C", ["中位区间无强势证据（首帧缺 delta）"]
```

主函数（`compute_cross_section`，`cross_section.py:105-163`，核心逐字）：

```python
    delta: float | None = None
    if len(percentiles) >= 2:
        prev = _finite(percentiles[-2])
        if prev is not None:
            delta = percentile - prev
    # 持续高位窗口（方案2）：近 N 帧全部合法才计算均值（证据不足不伪造持续性）。
    persist: tuple[int, float] | None = None
    persist_frames = int(_finite(getattr(config, "crossSectionPersistFrames", 0)) or 0)
    if persist_frames >= 2:
        window = [_finite(v) for v in percentiles[-persist_frames:]]
        values = [v for v in window if v is not None]
        if len(values) == persist_frames:
            persist = (persist_frames, sum(values) / persist_frames)
    market = _finite(market_median)
    relative = percentile - market if market is not None else None
    tier, reasons = _tier_from(percentile, delta, persist, config)
```

**数学边界（config.py:126-130 原文注记）**：`delta = pct[-1] − pct[-2] ≤ 100 − pct[-1]`，**pct > 95 的强势股（榜首 pct=100）永远无法满足 A 档 delta≥5 上升确认**——强势体现在「持续停留高位」而非「继续上升」。persist 路径为此而设但默认关（Frames=0，§4.2-C）。**残留硬编码**：`percentile <= 30` 低位线（与中位兜底同返回 C，无效轴，审计 I-1 归档不参数化）。

### §2.4 量价 volumePrice（`ranking/volume_price.py`）

板块涨停幅度（`_daily_limit_pct`，:41-57）：创业板/科创板（300/301/688/689 前缀）19.8、北交所（8/4/9 前缀）29.8、主板 9.8（ST 同板块阈值，数据口径非可调参数）。

方向八档（`_direction_bucket`，:72-90 判据）：涨停 `chg >= 板块阈值` → ±buckets[0]；否则按 `volumePriceDirectionThresholds=[7,5,3,2,1,0.5]` 边界取 buckets[1..7] 对称 ±，平盘 0。

**评分主函数**（`compute_volume_price_score`，:123-257，核心逐字）：

```python
    chg = _finite(change)
    vr = _finite(volume_ratio)
    if chg is None or vr is None or vr <= 0:
        return {"score": None, "direction": None, "quadrant": None,
                "reasons": ["量价数据不足（涨跌/量比缺失），不评估"], "signalTier": "unknown", ...}
    direction = "up" if chg > 0 else "down" if chg < 0 else "neutral"
    direction_score = _direction_bucket(code, chg, c)

    limit_up = _is_limit_up(code, chg)
    limit_down = _is_limit_down(code, chg)
    volume_score = 0.0
    if chg > 0:
        if vr <= c.volumePriceShrinkRatio:            # vr<=0.95
            volume_score = (c.volumeScoreUpShrinkLimitUp if limit_up
                else min(c.volumeScoreUpCap, c.volumeScoreUpShrinkBase + (c.volumePriceShrinkRatio - vr) * c.volumeScoreUpShrinkSlope))
        elif vr <= c.volumePriceMildRatio:            # 0.95<vr<=1.05
            volume_score = c.volumeScoreUpMildLimitUp if limit_up else c.volumeScoreUpMildNormal
        elif vr <= c.volumePriceNormalRatio:          # 1.05<vr<=2
            volume_score = min(c.volumeScoreUpCap, c.volumeScoreUpNormalBase + (vr - 1) * c.volumeScoreUpNormalSlope)
        elif vr <= c.volumePriceOverVolumeRatio:      # 2<vr<=2.5
            volume_score = max(c.volumeScoreUpOverFloor, c.volumeScoreUpOverBase - (vr - 2) * c.volumeScoreUpOverSlope)
        else:                                          # vr>2.5
            volume_score = -min(c.volumeScoreUpExcessCap, c.volumeScoreUpExcessBase + (vr - c.volumePriceOverVolumeRatio) * c.volumeScoreUpExcessSlope)
    elif chg < 0:
        if vr > c.volumePriceMildRatio:
            volume_score = c.volumeScoreDownOverMild
        elif vr >= c.volumePriceShrinkRatio:
            volume_score = c.volumeScoreDownShrink
        else:
            volume_score = c.volumeScoreDownLimitDown if limit_down else c.volumeScoreDownNormal

    ratio = _finite(zljzb)
    inflow = _finite(zlje)
    fund_score = 0.0
    if ratio is not None and ratio > c.volumePriceAbnormalFundRatio:      # >10 对倒出货
        fund_score = -min(c.fundScoreCap, c.fundScoreDumpBase + (ratio - c.volumePriceAbnormalFundRatio) * c.fundScoreDumpSlope)
    elif ratio is not None and ratio > 0:
        fund_score = min(c.fundScoreCap, ratio * c.fundScoreNetSlope)
    elif ratio is not None and ratio < 0:
        fund_score = -min(c.fundScoreCap, abs(ratio) * c.fundScoreNetSlope)
    elif ratio is None and inflow is not None:
        fund_score = c.fundScoreInOutStep if inflow > 0 else -c.fundScoreInOutStep if inflow < 0 else 0.0

    score = round(_clamp(c.volumePriceBase + direction_score + volume_score + fund_score))

    volume_state = "up" if vr >= c.volumePriceMildRatio else "down" if vr <= c.volumePriceShrinkRatio else "normal"
    quadrant = None
    if chg > 0:
        quadrant = "rise_volume" if volume_state == "up" else "rise_shrink" if volume_state == "down" else "normal"
    elif chg < 0:
        quadrant = "fall_volume" if volume_state == "up" else "fall_shrink" if volume_state == "down" else "normal"
    else:
        quadrant = "normal"

    reasons: list[str] = []
    if limit_up and vr <= c.volumePriceShrinkRatio:
        reasons.append("缩量涨停（封板不可买）")
    elif vr <= c.volumePriceShrinkRatio and chg > 0:
        reasons.append("缩量上涨（惜售/无量涨）")
    elif vr > c.volumePriceOverVolumeRatio and chg > 0:
        reasons.append("过度放量上涨（疑似出货）")
    elif vr > c.volumePriceMildRatio and chg > 0:
        reasons.append("放量上涨（量价配合）")
    elif vr > c.volumePriceMildRatio and chg < 0:
        reasons.append("放量下跌（风险）")
    elif vr < c.volumePriceShrinkRatio and chg < 0:
        reasons.append("缩量下跌（无量阴跌）")
    if ratio is not None and ratio > c.volumePriceAbnormalFundRatio:
        reasons.append("主力净占比异常高（疑似对倒出货）")
    elif ratio is not None and ratio > 0:
        reasons.append("主力净流入")
    elif ratio is not None and ratio < 0:
        reasons.append("主力净流出")

    amount_score = 0.0
    ar = _finite(amount_ratio)
    if ar is not None and ar > 0:
        if ar >= c.amountRatioHigh:
            amount_score = c.amountScoreStep
            reasons.append(f"成交额放量资金（量比 {ar:.2f} ≥ {c.amountRatioHigh}）")
        elif ar <= c.amountRatioLow:
            amount_score = -c.amountScoreStep
            reasons.append(f"成交额缩量资金（量比 {ar:.2f} ≤ {c.amountRatioLow}）")
        score = round(_clamp(score + amount_score))
    elif ar is not None and ar <= 0:
        reasons.append("成交额数据缺失（amount=0，不参与量价资金判定）")
```

**档位判定**（`_volume_price_tier`，:105-120，逐字——注意由 reasons 字符串匹配驱动）：

```python
def _volume_price_tier(quadrant, fund_score, reasons):
    if quadrant is None:
        return "unknown", ["量价数据不足"]
    joined = " ".join(reasons)
    if "对倒出货" in joined or "过度放量" in joined:
        return "E", ["硬风险：对倒出货/过度放量"]
    if "缩量涨停" in joined:
        return "C", ["缩量涨停封板，买不进，不可交易"]  # 信号真但执行不可交易，降出强档
    if quadrant == "rise_volume" and fund_score > 0:
        return "A", ["放量上涨 + 资金流入"]
    if quadrant == "rise_volume":
        return "B", ["放量上涨，量价配合"]
    if quadrant in ("rise_shrink", "normal"):
        return "C", ["缩量上涨/常态"]
    return "D", ["放量下跌/缩量下跌"]
```

**成交额量比**（`compute_amount_ratio`，:260-285，判据）：当前帧成交额 / 前 N=5 帧平均成交额（剔 0/None，非有限→None fail-visible，当前为 0→None）。

**协同状态机**（`compute_synergy_state`，:528-588，判据逐字摘要——喂候选池，非投票）：

```python
    if stage in ("ignition", "expansion") and high_vp and tech_buy and res_up:
        state = "启动确认" if stage == "ignition" else "主升确认"
    elif stage in ("ignition", "expansion") and high_vp and tech_buy and cs_strong:   # cs A 补共振缺失
        state = "启动确认" if stage == "ignition" else "主升确认"
    elif stage in ("crowded", "reversal") and (low_vp or fund_suspect or cs_weak):
        state = "风险升级"
    elif stage == "cooling" and low_vp:
        state = "退潮"
    else:
        state = "suspect"   # 含「共振↑但量价分低（无量虚涨）」「技术 buy 但量价证伪」标注
```

（high_vp = score≥75（synergyHighVp）、low_vp = score≤40（synergyLowVp）、fund_suspect = zljzb>10、cs_strong=A、cs_weak=D；state 输出给候选池，hardWarn=风险升级。）

### §2.5 参数总表（config 默认值，`engine/config.py`）

**共振**（:86-100, 352-355，全部参数化）：

| 参数 | 默认 | 参数 | 默认 |
|---|---|---|---|
| resonanceShort/Mid/PathWindowBars | 3/8/8 | resonanceReversalSwitchWeight | 0.6 |
| resonanceMinMarketSampleCount | 20 | resonanceReversalDrawdownWeight | 0.4 |
| resonanceMomentumScale | 15.0 | resonanceReversalDrawdownScale | 20.0 |
| resonanceAccelerationScale | 15.0 | resonanceJumpFreshnessDecay | 3.0 |
| resonancePathDirectionWeight | 0.2 | resonanceEntryStrengthScale | 25.0 |
| resonanceDirectionThreshold | 0.1 | resonanceNewEntryWeights | [0.7, 0.3] |
| resonanceWeights（展示面 only） | [0.35,0.25,0.2,0.2,0.2] | resonanceLabelThresholds（展示面） | [85,67,50,27] |
| tierResonanceReversalPenaltyMin | 0.6 | jumpDeltaPct / ResetLookback / SustainCount | 15.0 / 3 / 2 |
| tierResonanceJumpFreshnessMin | 0.5 | jumpConfirmChangeMin / VolumeRatioMin | 3.0 / 1.0 |
| tierResonancePersistenceMin | 0.6 | resonanceVolumePriceWeight（API final 修正） | 0.15 |
| tierResonanceEntryStrengthMin | 0.3 | — | — |

**趋势**（:9-16, 19-45, 66-71, 268-278, 356-357）：

| 组 | 字段=默认值 |
|---|---|
| 动量核心 | momentumPeriods=[3,5,8,13,21]，momentumWeights=[0.15,0.2,0.25,0.25,0.15]，buyThresholds=[5,8,13,21,34]，sellThresholds=[−5,−8,−13,−21,−34] |
| 三分量判据 | momentumDirectionThreshold=0.2，momentumSignalShareMin=0.6，momentumLongOppose/AgreeThreshold=0.25/0.15，momentumDirectionShareBoost=[0.5,0.5]，momentumAccelThreshold=0.18，momentumAccelShareBoost=[0.7,0.3]，momentumScoreThreshold=35，momentumConfidenceSlope=0.45（confidence-only，P5-0 dead output） |
| zeroCross | momentumZeroWeights=[0.7,0.3]，momentumZeroConfirmThreshold=0.15，momentumZeroStrongConfirmThreshold=0.15，momentumZeroStrongConfirmBonus=5.0（confidence-only 零效应） |
| MACD | macdFast/Slow/Signal=13/21/8，macdGoldenStrongGapMin=0.2，macdGoldenGapScaleRatio=0.18，macdDeathGapScaleRatio=0.12，macdDeathStrongGapMin=0.18，macdRawScoreWeights=[0.7,0.3]，requireMacdGoldenCross=False |
| MA | maFastPeriod/maSlowPeriod=10/20，maWeight=0.37（阶段 22.8 落默认），maCrossTrendBuy=False |
| 决策五权重 | directionWeight=0.06，accelerationWeight=0.04，crossWeight=0.24，macdWeight=0.29（+ma 0.37，和恒=1；from_patch 自动归一化+校验） |
| 阈值 | buyScoreThreshold=0.12，sellScoreThreshold=−0.12，decisionMinAgreement=2，decisionMaxOpposition=1 |
| 档位 | tierRankTrendStrongMin=0.5，tierRankTrendConfirmMin=0.25 |
| fallback | fallbackDirectionThreshold=0.2，fallbackAccelThreshold=0.18，fallbackZeroDisplayMin=0.15，fallbackZeroVolumeBand=0.2，fallbackDisplay/PriceNormScale=8.0/6.0，fallbackVolumeTanhScale=0.75，fallbackDirection/Accel/Zero/CapitalWeights=[0.4,0.3,0.2,0.1]/[0.55,0.25,0.2]/[0.5,0.35,0.15]/[0.6,0.4] |
| **残留硬编码（无 config 字段）** | momentum_profile 周期组 [1,3,5]/[5,8,13]/[13,21] 与 composite 权重 0.35/0.4/0.25/0.2；rank_shock lookback=10（momentum_profile 内）；fallback momentumScore 权重 [0.45,0.35,0.2]（:399）；MACD warm_gaps lookback `min(max(macdSignal,3),…)`（:60）；analyze_technical 的 ma5/ma10 显示均线（:305-306） |

**热度**（:113-133, 172，全部参数化）：crossSectionStrongMin=85 / StrongDeltaUp=5 / MidMin=50 / MidDeltaUp=15 / WeakMax=15 / WeakDeltaDown=−5 / MidMax=50 / MidDeltaDown=−15 / StrongAbsMin=70（P1-0 参数化）/ PersistFrames=0（关）/ PersistMin=90 / PersistMeanMin=85；票权 tierSynergyCrossSectionVote=0.75；强度表 tierSynergyCsStrengths=[1.0,0.5,−0.5,−1.0]（cs/pm/dv 共用）。残留硬编码：`pct<=30` 无效轴 1 处。

**量价**（:102-111, 137-139, 171, 182-206, 290-292, 332）：

| 组 | 字段=默认值 |
|---|---|
| 基础 | volumePriceBase=50.0，volumePriceOverVolumeRatio=2.5，volumePriceAbnormalFundRatio=10.0（fund10 落默认，原 20），volumePriceShrinkRatio=0.95，volumePriceMildRatio=1.05，volumePriceNormalRatio=2.0 |
| 方向 | volumePriceDirectionBuckets=[15,12,10,8,6,4,2,1]，volumePriceDirectionThresholds=[7,5,3,2,1,0.5] |
| 打分阶梯批 2（24 参数，零效应归档） | volumeScoreUpShrinkLimitUp=8 / UpShrinkBase=10 / UpShrinkSlope=15 / UpCap=15 / UpMildLimitUp=10 / UpMildNormal=5 / UpNormalBase=10 / UpNormalSlope=5 / UpOverBase=15 / UpOverSlope=10 / UpOverFloor=5 / UpExcessBase=15 / UpExcessSlope=10 / UpExcessCap=20 / DownOverMild=−20 / DownShrink=−5 / DownLimitDown=−15 / DownNormal=−10 / fundScoreCap=15 / DumpBase=10 / DumpSlope=0.5 / NetSlope=3.0 / InOutStep=5.0 / amountScoreStep=5.0 |
| amount | amountRatioPeriod=5.0，amountRatioHigh=1.5，amountRatioLow=0.5（**未扫描**，冻结前窗口零差异） |
| 协同/门 | synergyLowVp=40.0，synergyHighVp=75.0，volumePriceGateMode="hard"，tierSynergyVolumePriceVote=1.0 |
| **残留硬编码** | 板块涨停幅度表 19.8/29.8/9.8 与前缀表（数据口径）；compute_synergy_state reasons 文案内嵌阈值「≥75/≤40」（与 config 同值双写） |

**汇合面**（:169-179, 327-344, 358-360）：tierSynergyResonanceVote=0.75，tierSynergyRankVote=0.75，tierSynergyVolumePriceVote=1.0，tierSynergyCrossSectionVote=0.75，tierSynergyPriceMomentumVote=0.0，tierSynergyDivergenceVote=0.0；tierSynergyVoteStrengths=[1.2,1.0,**0.7**,0.5,1.0,1.0]（S/A/B/C/D/E；B 档 0.8→0.7 B-202610 落默认）；tierSynergyVoteStrong=2.0 / Weak=1.0 / Reverse=−1.0；lifecycle 门控参数见上一轮语料 §2.7（默认 hard/hard/hard）。

---

## §3 消费链（四维结果被谁吃、怎么吃）

### #1 synergy 投票与组装（`assemble_observation`，`volume_price.py:469-525`）

逐帧每股：`vp = compute_volume_price_score(...)` → `observation.synergy = compute_synergy_state(...)` → `_synergy_tier(res.signalTier/direction, rankTrend.signalTier/direction, vp.signalTier/direction, lc_tier, cs_tier, pm_tier, dv_tier)` 覆写 `observation.synergy.signalTier`。接线在引擎侧（`runtime.py:1417`）；API 单股链路同源（`ranktrend_routes.py:484-490`）。**共振仅在 market_ctx 存在时计算**（`runtime.py:1390`；阶段 3 修复后 replay 补共振）。

### #2 候选池（`compose_strategy` / `compose_analysis_candidate_tier`，`runtime.py:431-511/771-871`）

- A_MAIN 判定链含 `trend_buy`：`technical.signals.direction=="buy" or acceleration=="buy" or macd.cross=="golden" or maCrossTrendBuy`（:445，OR 链）；B_IGNITION 用 momentum.short/acceleration 阈值（tierB*）；
- `synergy.state`（启动/主升确认、风险升级、退潮）喂候选分层叙事；A_MAIN/B_IGNITION 默认 action=watch（阶段 6 用户口径，不作为默认入场投票）；
- 市场级 regime 门（strong 禁 A/B）先于个股（正交，不在本轮范围）。

### #3 交易层（`core/backtest/execution.py`）

**入场三锁**（默认策略 rank_trend_candidate / 研究对照 rank_trend_four_dim，`execution.py:1033-1046` 注释原文：「入场 = synergy S/A（四维投票方向一致）+ 资金 zljzb≥0 + 非生命周期 veto（环境门）」；`_is_four_dim_entry_signal` :790-814 判据：tier∈{S,A} ∧ zljzb≥0（缺字段 False 不伪造）∧ 非 veto，且 regime≠retreat）。**synergy 档位是唯一入场门票——B 档票（vote∈[1.0,2.0)）不可入场。**
**出场腿**：synergy D/E → `synergyExitOnDanger`/`downgradeSteps` 计数退出（:387/930-939）；D_EXIT_RISK 与弱势状态同帧等效。
**trendReversal 入场**（trend_reversal_jump 策略，:1026-1032）：低位弱转强+排名 jump+大幅度，h8 winRate 0.5212 组合（magMin=20/freshMin=0）。
**API final 覆写**（`ranktrend_routes.py:490→729-758`，**仅 API 单股链路，replay/回测不走**）：`decision.final = resonance.direction/score`，resonance.score 经量价修正 `score + (vpScore−50)×0.15`（clamp 0-100）；resonance insufficient → final=hold/0；**resonance buy 但 vp≤40 → final 降级 hold（量价证伪）**。即 API 展示的最终信号=共振方向（量价修正后），与回测入场用的 synergy 档位是两条不同消费链。

### #4 前端展示

各维 signalTier 前端只读消费（主表共振/趋势/热度/量价列）；展示形态 2026-08-29 冻结为「方向+连续分」，档位仅 tooltip（`ranktrend-four-dimension-column-plan.md` §2）。

---

## §4 实证全景（全部已归档读数；来源=L1 台账 `ranktrend-l1-param-ledger.md` §1-§18 + 长测计划 + 上一轮语料 §11/§12）

### §4.1 正向证据（各维有真实贡献的读数）

| # | 证据 | 读数 | 来源 |
|---|---|---|---|
| A | **热度开票**（cs 第 5 维，2026-08-17 G2） | all syn +10% / 8 月 +237%（→票权 1.0 落默认；**注记：定值引用了 8 月数据，属台账 §6「8 月污染历史」登记项，8 月已冻结**）；阶段 23.9 降权 1.0→0.75：+6.2/+13.7/+3.0 | 台账 §5/§12 |
| B | **三票权 combo_three_quarter 落默认**（res/rank/cs 1.0→0.75） | 判定卡 C1 +11.2% / oos +7.5%/+26.6%，C1-C5 全过；**Track 1 交易层直验：wrxpf 0.4702 vs 旧 1.0 票权 0.2913（−38%）**；归零臂（任一维票权=0）受损 23~55%（res/rank/vp/cs 四臂）无翻转 | 台账 §14.1 + config:165-168 注释 |
| C | **量价 fund10**（AbnormalFundRatio 20→10） | 三窗 +7.3/−4.1/+1.9%（判定卡过），Track 1 decision wrxpf +2.9%（oos2 23 笔观察级 −39%）；端到端新锚 0.1120/0.0880/0.0951 逐位复现 | 台账 §14.4 |
| D | **G4 Jump 确认门断线修复**（2026-09-15） | 修复后 decision syn saEx 0.1120→**0.1323（+18.1%）**，passHard 保持；**降级率 80.42%**（84496/105064 事件缺价格/量确认被降级 hold 不进共振票）、放行 19.58%、jumpVoteShare 10.95%——修复属 bug fix 使已评审设计生效，非落默认判定卡流程；两参剂量扫描修复后代际重新立项（遗留） | 台账 §15.6 |
| E | **趋势五权重实证重定义**（阶段 22.8，57 次全量 replay） | p2_aggressive 落默认：directionWeight 0.24→0.06（loo 去除 +13.9%/+17.0% 两窗）、acceleration 0.20→0.04（唯一三窗一致负 +2.6/+7.0/+6.8%）、cross 0.16→0.24、macd→0.29、ma→0.37；Track 2 判定卡 PASS_CANDIDATE（C1 +12.5%、C2 oos 双窗 +30.0%/+28.9%） | 台账 §10 |
| F | **B 档票强度 0.8→0.7**（B-202610 O3） | Track 2 全卡过（C1 +5.97% ∧ 三 OOS 全正）+ Track 1 oos2 全月 80 笔中性 | 台账 §16/§17 |
| G | **vp E→D 出货短路是真保护**（阶段 24.4 Track 1） | e1a 放开（off）新增 20 笔 wr/pf 显著更差，主窗 wrxpf −32%、maxDD 加深——「出货硬风险挡在入场池外」价值方向已验证 | 上一轮语料 §11.1 旁证 |
| H | 档位区分度基线（阶段 3 语义校准 769 帧） | rankTrend 维 S/A/B 档 excess **+0.064/+0.037/−0.013**（档位读数非三窗）；synergy 合并 S/A/B **+0.088/+0.039/−0.006**（达标，靠四维合并） | 上一轮语料 §4.1-A（B3 勘误后口径） |
| I | **N1 Jump 确认紧侧线索**（B-202610） | jumpConfirmVolumeRatioMin 1.25/1.5 三窗全正（oos2 +5.35/+6.90%）→ monitor_only 立项建议；chg 轴不干净 | 台账 §16 |
| J | 共振 H1 保护机制（D-a 反事实） | 回收缺票共振（全部判 insufficient）反事实三窗全负——**共振维「在场」有正贡献**；H2 线索：NaN median 帧若强行给值 exAcc +5.7%（代码级课题） | 台账 §14.5 |

### §4.2 负向/已证伪清单（提案不得撞枪口，除非有新结构理由并显式论证）

| 维 | 已证伪/判冗余 | 证据 |
|---|---|---|
| 共振 | ① label 阈值 ×0.5/×2 与 resonanceWeights：**zero_effect**（只进展示分）；② MinMarketSampleCount 20→10/40：**结构性惰性**（缺票帧由 NaN median 拦截非计数）；③ MidWindowBars 6/10：跨窗矛盾（mid6 oos2 −18.3% 反向；mid10 双 OOS 正但 decision −0.7% 不过 C1）；④ 12 参数阶段 7 walk-forward 全扫后维持默认 | 台账 §1/§14.5 |
| 趋势 | ① MACD 周期族（fast/slow/signal 各档）、死叉侧两参、macdRawScoreWeights、momentumZeroWeights：**冗余**（各档 score 波动 <±0.25%，跨窗方向矛盾）；② momentumZeroStrongConfirmBonus、momentumScoreThreshold(25↔45)：**零效应**（confidence-only / 档位区间不可达）；③ requireMacdGoldenCross 开启 decision −9.4%；④ accel 0.26 曾单调显著但 8.5 样本外否决；⑤ buyThresholds 镜像缩放：decision 全负、oos1 剂量正但跨窗矛盾不达 C1；⑥ maCrossTrendBuy：冗余（MA 金叉帧 65-68% 已被 trend_buy OR 链覆盖）；⑦ direction 侧默认已证最优（阶段 22 loo） | 台账 §2/§2b/§15.5/§2c |
| 热度 | ① 阈值族 P1-a 37 trial：**默认即跨窗权衡峰**（StrongAbsMin 收紧 decision 正但 oos 双大负；StrongMin_80 唯一 C1 过线但 C2 失败）；② MidMax/MidDeltaDown：**真惰性**（三窗 cs 档位分布逐位 identical）；③ WeakMax/WeakDeltaDown：**C/D 归类活跃但下游零传导**（weakMax_20 D 档 +26% 而 A/B 桶逐位不动——效应链终止于投票输入，B/C/D 迁移 saEx 盲区 §4.4）；④ 强度表方案 B 13 trial：现值即峰（csC 两侧全负、csD 结构惰性、csA OOS 全负、csB_025 C3 硬门失败）；⑤ persist 路径 H2 证伪（vs delta_A 0.087 量级差距，合并稀释 A 档跌破 0.05 线）维持关闭 | 台账 §15.1/§14.2/§8 |
| 量价 | ① 批 2 打分阶梯 24 参数：**10/10 零效应（结构性）**——全部为分值幅度面，×正缩放不改符号/阈值比较，档位决定面=4 个 ratio 阈值；② amount 族（amountScoreStep 等）：**zero_effect**（amount_score→score 而 `_volume_price_tier` 不消费 score；decision 窗 amount 可算率仅 **6.12%** 低杠杆，oos2 95.82% 排除假惰性）；③ OverVolumeRatio 2.5：基线漂移失效（0.0/−22.2/−34.5%）；④ fund10+over2 组合：观察池方向未恢复维持挂起；⑤ MildRatio：跨窗矛盾 OBSERVE | 台账 §14.3/§15.4/§14.4 |
| 汇合面 | ① 三线 P2 复扫：Strong 线 2.25/2.5 档（收紧，默认 2.0；S 线=strong+1=3.0）saEx 剂量升（+4.5/+23.8%）但 passHard 三窗全崩 + oos2 负——维持；S 档强度 vsS_100 三窗全正但 C3 档位单调性违反；A/C/D/E 强度各轴全负/反向/无信号——**维持**（台账 §15.2 行首「当前值 3」为 S 线口径混写，config 代码事实=2.0，本语料以代码为准）；② weak/reverse 线：saEx 盲区非惰性（B 档 ±51%、D 档 +21% 分布迁移）→ Track 1 口径课题挂起（§15.7）；③ 软化门控（lc soft/off、vp soft/off）：阶段 24 全轴 hard 为峰（vp off 信号面 +9.8/−3.0/+33.4% 但 Track 1 主窗 wrxpf −32% 被否决，见 G） | 台账 §15.2/§13 |
| 关闭维 | pm（价格动量）投票实证负 all −32%；dv（量名背离）投票实证负 −25%——两维票权 0.0 关闭观察 | 台账 §5 |

### §4.3 结构性事实（代码级，推理必读）

1. **共振缺票结构**（D-a 结构普查）：res 真实投票率 72-79%（三窗）；缺票主导=排名序列不足（13-15%）+ NaN median/样本 <20；新入榜帧走独立分支（单帧即判，不需要历史）。
2. **投票语义不对称**：cs 的 C 档（「无强势证据」兜底，覆盖中位区间大片面积）吃固定负票 −0.5×0.75=−0.375，而 A/B 才有正票——热度维对「平庸」股票系统性投负票；趋势 hold=C 档但票=strength(0.5)×dir_sign(hold)=**0**（hold 方向不投票），共振 hold 同理票 0。**同为「无方向」，cs 投负票、res/rank 弃权**。
3. **vp 档位与评分脱钩**：`_volume_price_tier` 只吃 quadrant+fund_score+reasons 字符串；score（0-100 连续分）只喂 compute_synergy_state（≥75/≤40 门）与 API final 修正——**打分阶梯 24 参数零效应的根因**。E 档由 reasons 字符串匹配（「对倒出货」/「过度放量」）驱动——文案改动会改档位（结构性脆弱，谁改 reasons 谁改行为）。
4. **saEx 盲区**：saEx=S/A 两档合并加权 excess，**B/C/D 档完全不在统计集**——凡只迁移负票/中性档的改动 saEx 结构性不可见（P2 方法论主发现；weak_150 使 B 档腰斩 12181→5962 而 S/A 桶逐位不动为实证）。
5. **时序不规则未覆盖四维**：§1.1-1——P3 诊断（ER=3.33）实证 lifecycle 序列的跨日假动量，但修复只落 lifecycle；四维的 delta/动量/EMA 无时间正规化（未测的开放面，非已证伪）。
6. **双动量体系**：趋势投票用 momentum_data（[3,5,8,13,21] 加权 tanh），候选池/生命周期用 momentum_profile（[1,3,5]/[5,8,13]/[13,21] composite 0.35/0.4/0.25/0.2）——同源不同式，冗余/矛盾面未测。
7. **market median 短变化的窗口**：resonance 的市场基准=当前帧 vs 前第 3 市场帧公共股中位数（≈1.5 小时前的横截面），且要求 ≥20 公共股——池子小时变与公共股存活率影响基准质量（未测）。

### §4.4 指标口径卡与系统性教训

- **saEx** = S/A 两档合并加权 excessDirectionAccuracy（盲区见 §4.3-4）；**wrxpf** = winRate × profitFactor（交易层终判）；**h8** = 8 帧后视窗口区分度。
- 判定卡（补扫批）：C1 decision saEx rel ≥+3% ∧ C2 OOS ≥1 窗同向为正 ∧ C3 decision passHard 不降；交易层 M2 门槛 30 笔。
- **锚代际**（重要）：第四代四窗锚 0.1323/0.0862/0.0841/0.0534（B-202610）；第七代 0.1472/0.1016/0.0981/0.0698（三参落默认后）；**2026-10-07 生命周期 G1 落默认后再变（trial 读数 0.1450/0.0983/0.1172）**——新 trial 必须同代际相对线，绝对锚引用须注代际；10 月帧字段大回填（e77907bb/cacf4ab8）致旧绝对锚不可复现是已登记教训。
- **8 月冻结纪律**：8 月自 2026-08-19 冻结为独立复核窗；组 5 参数（cs 票权/regime）定值曾引用 8 月（污染历史登记）——热度票权的 +237% 读数属该代际，复验时注意。
- **市况依赖教训**（多次复现）：低开回避条款 7-9 月有效、4-6 月高涨期反向；量能轴 9 月有效 8 月失效；卖点规则市况依赖四次复现。任何四维改动必须分市况检验。
- 归因顺序纪律：偏差先查 ①原料 → ②判据设计 → ③协议/解析/消费 → 最后才是方案重设计。

---

## §5 硬约束（提案必须遵守）

1. **golden 锁基线**：引擎 golden 以 `analysis/ranktrend/engine.py` 为生产事实标准；任何阈值改动走「参数化、默认值=原值、零行为变化」，新值只作候选配置验证，**不自动写回默认**（一次一候选、用户裁决后落默认）。
2. **角色裁决**：四维保持方向投票维语义；pm/dv 维持票权 0 关闭观察（要打开须先过与既有维的冗余/增量检验）；生命周期门控保持环境门（上一轮已裁）。
3. **评估链**：信号层（tier 区分度/excess 单调性，全窗 replay）→ 判定卡三窗（C1/C2/C3）→ **Track 1 交易模拟（wrxpf）终判**（saEx 对 B/C/D 迁移与出场通道盲区，§4.3-4）；候选池/叙事层改动另需展示同步（§3#2）。
4. **fail-visible**：缺数据/低样本/类型残缺必须显式暴露（unknown/None），不得用 0 或空结果伪装（现有 insufficient/unknown 出口是合规基线）。
5. **改动透明可回退**：config diff 优先；config_hash 区分代际；禁版本化文件名；新 trial 用同代际相对线。
6. **禁拟合**：不朝已知标签日/已知好读数调参；8 月冻结纪律；新特征走「分位化→次日后验对齐→数据里找自然分界→逐月验稳定」，并检验市况适用域。

---

## §6 未决问题（推理主目标，逐条归因后提案）

- **Q1 时间正规化泛化**：P3 诊断已实证 lifecycle 序列 velocity>18 帧 42% 为跨日假动量（ER=3.33）；四维全部吃同一条不规则序列（§1.1-1、§4.3-5）——cs delta（单帧差分最直接暴露）、resonance short/mid（3/8 序偏移）、趋势动量/MACD/MA（更长窗）。**哪些维受害最深？**MACD/MA 全窗 EMA 可能被稀释、单帧 delta 最敏感——请按暴露度排序并设计诊断步（注意：G1 修复后基线已变，诊断须在新代际上跑；lifecycle G1 的 temporalGap 标记基础设施可复用）。
- **Q2 共振的缺票与门**：13-15% 排名序列不足缺票 + H1 已证「在场有价值」；G4 修复后 80.42% Jump 事件被确认门降级——**门是否过紧**（N1 显示 vr 收紧反而三窗全正，方向上与「门太紧」矛盾，怎么调和？）；新入榜分支单帧即判（isNew=len==1）的 entry_strength 只用当帧横截面 pct——新入榜第二天（len=2，macd/动量全 0）发生了什么？
- **Q3 趋势维的原料与结构**：rank-only 时序 + 五权重后 0.90 权重在三个二值交叉事件上（§2.2 注）——连续动量信息被压缩到 0.10 是「实证最优」还是「结构天花板」？momentumProfile（另一套动量，喂候选池/lifecycle）与投票动量的双体系冗余面在哪？fallback（22 帧以下走当帧标量）覆盖的帧占比多少、行为是否已验？
- **Q4 热度的不对称负票**：cs C 档兜底吃 −0.375 固定负票（§4.3-2）而 res/rank hold 弃权——这个不对称是设计（横截面平庸=相对弱）还是缺陷？A 档数学边界（pct>95 delta 永不可达）+ persist H2 证伪后，榜首强势股长期拿 B 档（绝对线 70）是否系统性压低其 synergy？cs 维的 tier 分布未入语料（§7-2），提案前是否须先诊断分布？
- **Q5 量价的档位结构**：tier 只吃 quadrant+fund>0+reasons 字符串（§4.3-3）——「放量上涨+资金流入=A」里 fund_score 只要 >0（哪怕 +0.1）就 A；score 与档位脱钩是否有信息浪费（score 只喂 state 门 75/40）？E 门字符串驱动的脆弱性是否应结构化（判定与文案分离）？amount 可算率 6.12% 下 amount 维度的真实杠杆？
- **Q6 汇合面剩余空间**：票权 0.75/0.75/1.0/0.75 + B 档 0.7 已落默认后，**投票面的自由度还剩多少**（结构下限：三轴同减 ≤0.5 时 S/A 塌缩）？max 3.75 / S 线 3.0 的边际：S 档需三主维几乎全 S 同向——S 档稀缺是特性还是票权人为压低？weak/reverse 线的 Track 1 课题（挂起）值不值得本轮带走？
- **Q7 评估口径缺口**：B/C/D 迁移 saEx 不可见 → 任何「负票/中性档」类提案的 trial 设计必须带 Track 1；per-dim excess（res/vp/cs 各自 S/A 档读数）未入语料（§7-1）——归因前是否先补 per-dim 基线诊断（1 次 replay 导出可得）？
- **Q8 市况分桶**：四维在强情绪期/退潮期的票权/阈值是否应差异化（教训多次复现）——差异化投票的预注册面怎么设计才能不撞「门控形态 hard 为峰」的先验？

---

## §7 诚实缺口（本语料没有的，按「未知」处理，禁止臆测）

1. per-dim 档位 excess：res/vp/cs 各自 S/A/B 档的 h8/saEx 读数未入语料（只有 rankTrend 三数 H 与 synergy 合并数）。
2. 各维 signalTier 的帧级分布占比（如 cs A/B/C/D 各占比、vp A-E 各占比）未入语料，只有局部迁移数（B 档 12181→5962、D 档 6477→8170 等）。
3. h8 读数的精确公式与超额基线口径（同上一轮缺口）。
4. 逐股序列样例（含各维判档转折点的前后文）未附——如推理需要，可从 replay 导出补充。
5. TS 前端同构实现与 Python 的一致性状态未入语料（golden 主链以 Python 为准）。
6. fallback 路径（<22 帧）覆盖的帧占比、及新入榜次日（len=2）各维行为读数未入语料。
7. momentum_profile vs momentum_data 双动量体系的一致率/冲突率未测。
8. synergy state（启动/主升/风险升级/退潮/suspect）帧占比与候选池传导率未入语料。
9. G4 修复后 jumpConfirm 两参剂量扫描（修复代际）未跑（台账 §26.10 遗留 2 登记）。
10. 阶段 23 B 组 lifecycle_decision 13 阈值逐档读数（同上一轮缺口，不阻塞本轮）。

---

## §8 输出格式合同

1. **理解复述**（≤12 条，每条标 §来源，四维至少各 1 条 + 汇合点 1 条）——这是承重墙自查，先做；
2. **逐维归因诊断**（§0 任务 1：四维各自 ①→④ 排序 + 跨维冗余/缺口一问）；
3. **优化提案**（≤5 条，按 §0 分级 L1/L2/L3）：每条含改法/预期读数变化/验证设计/失效风险/回退/不撞 §4.2 的论证/市况适用域回答；
4. **证据不足与矛盾清单**（没有写「无」）；
5. 明确声明哪些提案只是「值得预登记验证的假设」，不要把假设写成结论。

---

## §9 投喂模板与用法

### §9.1 system 文本（存为 `voting-signals-review-system.txt`）

```text
你是量化系统评审专家。遵守项目归因纪律：模型/规则输出与预期偏差时，归因顺序固定
①原料/输入供给 → ②判据与算法定义 → ③下游消费形态 → 最后才是方案重设计。
禁止无数据支撑的方案重设计；所有优化方向必须给出验证方法（replay/回测/样本需求）与回退方式。
不做正收益拟合（用户裁决：拟合是弯路）；改动必须透明可回退。
反幻觉：只允许使用用户提供的语料推理，引用须标 §编号；禁止编造字段/数字/文献；
不确定写「未知/证据不足」；发现语料内部矛盾要显式指出。
```

### §9.2 user 文本骨架（存为 `voting-signals-review-prompt.txt`）

```text
以下是 A 股短线系统「四个投票信号维（共振/趋势/热度/量价）+ synergy 汇合点」的完整语料
（代码逐字 + 全部已知实证）。请按语料 §0 任务卡与 §8 输出格式合同作答（一问一答通道，
一轮出齐四件：理解复述 + 逐维归因 + 提案 + 证据不足清单）。

【语料】
<粘贴本文档 §1-§8 全文（§0 任务卡含在语料内，位于最前）>
```

### §9.3 执行命令（GPT-OSS-120B 脚本通道）

```bash
# 令牌：env CLOUDFLARE_API_KEY 或 quant-board/.env.local（脚本自动回落）
python scripts/gptoss_questionset_review.py \
  --system voting-signals-review-system.txt \
  --prompt voting-signals-review-prompt.txt \
  --out gptoss-voting-signals-a1.md --effort high --timeout 600
```

成本量级：语料约 30-40k input tokens + 4-8k output（workers-ai gpt-oss-120b 计费口径，单次成本量级 $0.01-0.1，估算值）。

### §9.4 审定纪律（沿用两轮先例）

1. **承重墙抽验**：模型复述里的代码行为/阈值数字/字段名逐字对照本仓库（runtime.py/technical.py/cross_section.py/volume_price.py/config.py）——复述逐字通过才可信其归因；
2. 幻觉条目**全弃**（crowding 先例：5 幻觉全弃、真归因 1 条采纳）；
3. 模型提案 = 假设，进入验证须：预登记（考题/窗口/判定线/样本量）→ 用户点头 → 只读 replay → Track 1 → 用户裁决；
4. 语料-代码漂移若被模型抓出（先例：上轮 B1-B5 四处勘误），主会话核实后当轮勘误本文件。

### §9.5 Opus 4.x 备选投喂

全文（§0-§8）直接粘贴即可；建议要求「先承重复述、再逐维归因、最后提案」三段输出，反幻觉同款 system。若 GPT-OSS 一轮后归因深度不足（只复述不深挖）或幻觉率过高，换 Opus 是正确升级路径（上轮即如此）。

---

## §10 组装来源

| 材料 | 路径 |
|---|---|
| 算法源码 | `quant-board/backend/analysis/ranktrend/engine/runtime.py`（共振/Jump/market median/组装）、`trend/technical.py`（趋势全链）、`trend/cross_section.py`（热度）、`ranking/volume_price.py`（量价+synergy 汇合）、`engine/config.py`（参数全集）、`engine/primitives.py`（percentile/归一化）、`api/ranktrend_routes.py`（API final 覆写）、`core/backtest/execution.py`（入场三锁/出场） |
| 证据文档 | `docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md` §1-§18（参数台账全史）、`ranktrend-longterm-backtest-plan.md`（阶段 12/17/21-27）、`ranktrend-param-gap-scan-plan.md`、`ranktrend-vote-semantics-improvement.md`、`ranktrend-four-dimension-column-plan.md` |
| 上轮语料 | `reasoning-corpus-lifecycle-stage.md`（§4.1-A 档位基线、§11/§11.1 审定先例、§12 G1 落默认代际） |
| 诊断 harness | `backend/operations/`：`evaluate_dimension_voting_power.py`、`diagnose_resonance_vote_structure.py`、`evaluate_resonance_participation.py`、`evaluate_cs_tier_thresholds.py`、`evaluate_cs_strengths.py`、`evaluate_trend_leftover_parameters.py`、`evaluate_synergy_tier_thresholds.py`、`evaluate_vp_signal_parameters.py`、`track1_dimension_power.py` |
| 范式先例 | `docs/hotlist-jev/reasoning-corpus-eod-emotion.md`（§7 审定流程与反幻觉纪律） |

---

## §11 审定战报（2026-10-07，双模型 A/B 对比轮，用户亲自执行）

**执行事实**：①GPT-OSS 脚本通道两发——第一发撞 reasoning 吃光服务端默认输出上限（finish_reason=length、content=null，day_pattern 轮同款坑），脚本补 `--max-tokens`（默认 65535）后第二发完整（22,343 in / 7,141 out）：复述 12/12 干净，但提案层 P2（开 persist）**硬撞 §4.2 已证伪清单**却声称「未在清单中」、P1/P3 预期数字凭空（80.42% 误用为「S 档误降级率」）——按已知画像（复述干净/提案幻觉）弃提案层；②用户裁决弃 Opus（费用）改走 Sonnet 5（脚本通道 `scripts/claude_review.py`，gateway 对 urllib TLS 签名 403/1010 须 curl 子进程；adaptive thinking 吃 ~2/3 输出预算，max_tokens 须 ≥24k；首发 32,205 in/16,000 out $0.224 截断产出前半），后续 AI 两次违规自行重跑/续跑被用户当场取消（成本纪律事件，记忆 external-model-call-notify-first 已升级：计费调用 AI 只备料、重试逐次点头、截断先本地诊断）；③最终用户以**同一份被投喂界面截断的语料**（§2.2 后半~§2.3 `_tier_from` 主体缺失，界面留痕「Diff 预览已截断：省略 139 行」）亲自跑两个不同厂商高端模型 A/B，条件公平。

**审定结论**：两份均通过（复述各 12/12 零硬幻觉、提案均不撞已证伪清单、假设声明合规）；**对比裁定：模型A 综合略优，模型B 赢在最狠一刀**——

- **A 独有代码级发现 3 项（主会话逐一对码核实为真）**：①新入榜 S 档死分支（len==1 → Jump 无事件 → freshness 恒 0 < 0.5，S 永不可达，已注记 §2.1）；②warming 窗空洞（len∈[2,8] 全 insufficient 票 0，与缺票 13-15% 主体对上）；③cs 的 relative 结构性 ≈ pct−50（帧内 percentile 均匀分布 ⇒ market median percentile ≈50.25，未喂档位损失有限）。另提出 strength 表语义倒挂（res D∧buy 票 +0.75 > B∧buy +0.525，v4「方向主导」设计意图与衰竭语义的真实张力）。
- **B 独有抓漏 2 项（核实为真，已当轮勘误）**：①**vp 档位字母表无 S** → 语料 §2.0「max vote=3.75 / 三主维全 S=3.0」算术错误（真实上限 3.55），且**无 cs 正票时上限 2.8<3.0 ⇒ synergy S 档结构上要求 cs 投 A/B 正票（cs 是 S 守门维）**。**主会话自纠（复核后）**：vp-无 S 证伪的仅是「三主维全 S=3.0」表述本身；模型A 票权塌缩区间端点 [0.69, 0.83] 对应真实组合（0.69=res S+rank S+vp A+cs B=2.9k+1.0 达 3.0；0.83=res S+rank S+vp A 无 cs=2.4k+1.0 达 3.0），仅「含 cs A 的组合下限」标签措辞有偏（全组合枚举下限 ≈0.59=res S+rank S+vp A+cs A=3.4k+1.0 达 3.0）——对比裁定首版称「区间被错误前提污染」过头，勘误；②`frame_market_median` 窗口三处字面量（index−3/len<4/公共股<20）未参数化，其中 <20 与 resonanceMinMarketSampleCount 是两个独立判定。
- 提案面重合度大（vp fund 分层、vp 判定/文案解耦、价格确认门泛化 L3 两家独立收敛）；A 独有 P1 时间正规化诊断包（对准语料头号开放问题 Q1）与 P5 评估基础设施（恰为 B 的 L3 立项前置）；B 独有 L1-2 两参联合剖面+降级归因分解计数器（优于 A 单轴）与 persist 独立档两阶段重开（论证不撞 H2 证伪的「合并」形态）。
- 各自小 slip：A 两处（weak_150/weakMax_20 trial 归属混写；被 vp-S 错误前提污染的区间端点）；B 一处（「14 参数未验」中 directionThresholds 6 个实为台账 §14.3 已判零效应，其自标注「需 verify」诚实）。

**语料勘误 4 处（当轮完成）**：§1 词表（各维 tier 字母表逐维列明+vp 无 S）；§1 五位信号框架（「5 投票维」4 代号口径混写→4 个股投票维+市场级热榜情绪门，A 抓出）；§2.0（max vote 3.75→3.55+S 守门维结论，B 抓出）；§2.1（新入榜死分支注记+frame_market_median 硬编码注记）。

**提案裁定（全部=假设，进验证须预登记+用户点头；合并采用 A 骨架+B 仪器）**：

| # | 合并提案 | 来源 | 裁定建议 |
|---|---|---|---|
| R1 | **四维时间正规化暴露度诊断包**（一次 replay 导出：cs delta/res short-mid/rank 动量+MACD/MA 的跨日触发占比与档位翻转率 + fallback 帧占比 + 双动量一致/冲突率 + per-dim tier 分布与 S/A/B excess + res D∧buy 帧占比 + jump 降级归因分解〔fails_change_only/vr_only/both 计数器〕+ fund_score 直方图〔A 档分层候选区间〕+ persist_eligible 观察标记群体后验） | A-P1+P5 ⊕ B-L1-2 分解器 ⊕ B-L2-1 阶段1 ⊕ 双方直方图前置 | ✅ **第一优先**：零行为、单次 replay、同时解锁 Q1/Q2/§7-1/2/6/7 与其余全部提案的前置读数 |
| R2 | **vp 两步走**：①判定/文案解耦（数值布尔标志驱动 E/C 档，全窗逐位回归守护）②A 档资金条件分层 fundTierAMin（默认 0=零行为，候选由 R1 直方图定） | A-P3 ⊕ B-L1-1/L2-2 | ✅ ①可独立预登记（纯工程）；②依赖 R1 直方图 |
| R3 | **jumpConfirm 剂量**：R1 归因分解读数 → vr 轴 {1.25,1.5} 单轴 trial（N1 方向、一次一候选），chg 轴仅在分解显示其主导且方向干净时开 | A-P2 ⊂ B-L1-2 | ✅ 依赖 R1；判定卡+Track 1+预登记 S 档样本下限（<基线 30% 即停） |
| R4 | **res warming 补票**（len∈[4,8] 最低差分档、上限 B、保留市场基准化、默认 off） | A-P4 | ⚠️ 依赖 R1 的 len∈[2,8] 帧占比与后验读数（占比 <3% 放弃） |
| R5 | **cs persist 独立档阶段 2**（A_PERSIST 不并入 A、强度方向三态开放） | B-L2-1 阶段2 | ⚠️ 依赖 R1 的 persist_eligible 群体后验（负/零/正三态同测） |
| R6 | 价格确认门泛化（res/rank/cs 核心判据接 Jump-confirm 式价格门） | A/B-L3 同收敛 | 论证级：R1 的「jump 放行事件按 price 分位后验分层」列是立项前置 |
| R7 | 新入榜 S 死分支修复 + strength 倒挂裁决 | A 发现 | 结构事实登记：修不修属行为变化，须单独预登记+用户裁决；R1 的 D∧buy 占比列先行 |

**建议执行顺序**：R1 一次诊断 replay（分钟级）→ 读数裁决 R2②/R3/R4/R5/R7 分批预登记 → R6 视 R1 后验分层立项。**开跑等用户裁决**（预登记合同可由主会话按十字段模板草拟，第二轮模型审定为可选、须用户点头才调用）。

### §12.0 R1 诊断包预登记（2026-10-07 用户令「开跑」，跑数前冻结）

**考题**：四投票信号的时间正规化暴露度与结构读数——跨日差分在 cs delta / res short·mid / rank 各投票消费周期上的触发占比是否达到立项线；jump 确认门降级的轴归因；R2②/R4/R5 的前置占比读数；B 的「S 守门维」结构断言实证。

**窗口与 population**：frames 2026-04-15~09-12（half_hour，dragonboard_live，projection=ranktrend）；窗口分桶 decision/midgap/oos1/oos2 同 P1/P3 诊断；**主判定 population=decision 窗、序列 ≥2 股帧**（cs delta 需 ≥2）；len=1 帧单独计入新入榜桶。

**产出 schema**（`data/reports/voting-signals-exposure-diagnosis.json`，字段冻结）：
- `exposure`：cs_last_pair/res_short_start/res_mid_start/res_path_win/rank_period_{3,5,8,13,21}/zero_trigger(3)/zero_confirm(5) 各自 {n, cross_day_share, non_adjacent_share}；MACD/MA 上下文列（series 跨日帧占比=报告列无线）。
- `jump_decomposition`：{event_jump_n, pass, fail_chg_only, fail_vr_only, fail_both}（chg/vr 轴分开评估，现行阈值 3.0/1.0）。
- `tier_distribution`：res/rank/vp/cs/synergy 各维 signalTier 计数（decision 与全窗）。
- `s_gate_check`：synergy S 帧中 cs_tier∈{A,B} 计数 vs ∉ 计数（结构断言预期 ∉=0）。
- `len_buckets`：{1, 2_8, 9_21, ge22} 占比（warming/fallback 面）。
- `momentum_consistency`：momentumProfile.composite 符号 vs momentumScore 符号一致率；profile.short 符号 vs res.relativeMomentum 符号一致率。
- `res_structure`：D∧buy 帧占比；参与率（对照 D-a 72-79%）。
- `fund_histogram`：quadrant=rise_volume 且 fund>0 帧的 fund_score 分布（p25/p50/p75）+ <{0.5,1,2,3,5} 占比。
- `persist_eligible`：N∈{3,5,10}（pct≥90 ∧ 近N均值≥85）帧占比。

**判定线（冻结，跑后不得调）**：
| 线 | 判据 | 动作 |
|---|---|---|
| Q1 立项 | cs_last_pair 或 res_short_start 或任一 rank 投票周期 cross_day_share ≥15%（decision 窗） | 立项四维时间正规化 L2 预登记（合同带 h8 分层差前置步） |
| Q1 归档 | 上述全部 <5% | 该轴归档关闭 |
| Q1 观察带 | 5-15% | 读数进第二轮合同，由合同自带 h8 前置步裁决 |
| R2② 非空 | rise_volume∧fund>0 帧中 fund<1.0 占比 ≥10% | fundTierAMin 分层 trial 可预登记（候选 0.5/1.0/1.5） |
| R2② 惰性 | 该占比 <3% | 缓议（MidMax 型结构性惰性风险） |
| R4 立项 | len∈[2,8] 股帧占比 ≥3% | warming 补票可预登记 |
| R4 放弃 | <3% | 放弃 |
| R5 立项 | persist_eligible(N=5) ≥1% | 阶段2 可预登记（三态强度） |
| R5 放弃 | <0.3% | 放弃 |
| S-gate 自证 | synergy S 帧 cs∉{A,B} 计数 ≠0 | 我的接线 bug，自证失败重修脚本，不得引用该读数 |

**自证线**：①engine `replay_frame_at` 3 帧逐股四维 tier+synergy match ≥98%；②res 参与率对照 D-a 72-79%±5pp（超差登记不断案——sampleQuality 简化为恒过的时间线检查，可能高估参与率）；③vp E 档占比 sanity（个位数量级）。

**成本**：单次 pass（预计 <10 分钟，零 API/零 config 写回/零行为变化）；per-dim h8/excess 不在本包（属评估 harness 改造，进各合同前置步）。

### §12.1 R1 诊断读数（2026-10-07 执行，951 帧 / 217,582 股帧 / 158.9s；报告 `data/reports/voting-signals-exposure-diagnosis.json` 本地不入库）

**自证**：首跑 res 与引擎 13.6% 假 mismatch——根因=`replay_frame_at` 不传 market_ctx（resonance 恒缺失），改用带 market_ctx 的 `engine.replay` 切片末帧对照后**五维+synergy 692/692 逐股 100% 一致**（自证线 ①过）。②res 参与率 decision 67.0%：与 D-b「分母=全部信号」口径 69.0% 差 2pp（D-a 72-79% 是「有 res 数据」分母，口径注记 §4.3-1 原文已有）——对上，非漂移。③vp E 档 19.9% **超出我预估的个位数量级**——引擎逐位一致证明读数真实，预估线错而非计算错，如实登记。

**Q1 时间正规化暴露度（decision 窗，跨日=diff 端点元素异日）**：

| 维度·周期 | n | 跨日占比 | 同日非相邻 |
|---|---|---|---|
| cs delta（末对） | 125,566 | **12.5%** | 14.4% |
| rank p3 / zero 触发 | 116,223 | **35.4%** | 38.2% |
| rank p5 / zero 确认 | 109,361 | **54.6%** | 56.4% |
| rank p8 / res mid / res path 窗 | 101,138 | **81.0%** | 81.3% |
| rank p13 / p21（MACD EMA 基元） | 90,051/76,205 | **100%** | 100% |
| res short（3 偏移） | 101,138 | **34.0%** | 34.0% |

四窗一致（oos2 略高 1-3pp）。**判定线命中：立项 L2**。注意语义：跨日≠必然错误（p13/p21 ≈1.3-2.1 日动量，隔夜跳空是否该计入是其合同要回答的考题，G1 的「相邻差分置 NaN」模式不能直接搬——长周期动量无「相邻对」结构，需自己的正规化设计）。

**jump 确认门降级分解（decision）**：105,064 事件 = 放行 20,568（**19.58% 与台账 §15.6 逐位吻合，交叉验证接线**）+ fail_chg_only 31,196（29.7%）+ fail_vr_only 15,130（14.4%）+ fail_both 38,170（36.3%）——**chg 轴涉及 66.0%、vr 轴涉及 50.7%，chg-only ≈ vr-only 的 2.1 倍**；降级主力是 chg 轴。三 OOS 窗结构一致（chg-only 均 ~39-40%）。

**档位分布（decision，150,671 股帧）**：rank C 85.1%/A 4.1%/B 3.6%/D 6.9%/**S 0.3%**；vp D 26.2%/unknown 22.6%/C 19.6%/**E 19.9%**/A 6.5%/B 5.2%；cs C 54.4%/B 27.2%/unknown 12.9%/D 4.3%/**A 1.1%**；res **D 37.2%**/unknown 33.0%/S 9.5%/B 9.8%/A 4.5%/C 5.8%；synergy C 44.4%/D 39.1%/B 8.8%/E 6.8%/A 0.7%/**S 0.08%（127 帧）**。

**S 守门维实证（B 断言）**：synergy S 共 127 帧，cs∉{A,B} 计数 **0**——PASS，结构断言成立（且 cs A 仅 1.1% ⇒ S 档 127 帧里 cs B 是绝大多数正票来源）。

**其他结构读数**：len 桶（decision）：len1 3.7% / **len2-8 16.2%（warming，R4 过线）** / len9-21 16.6% / ≥22 50.6%；persist_eligible N3/N5/N10 = 8.7%/**8.2%**/7.2%（R5 过线）；res D∧buy 帧占比 **6.6%**（A 的 strength 倒挂担忧有实体——每帧投 +0.75 正票）；双动量一致率：profile.composite vs momentumScore 符号 91.8%、profile.short vs res.relativeMomentum 82.4%（双体系 8-18% 分歧面真实存在）；fund 直方图（rise_volume∧fund>0，n=11,711）：p25=6.3/p50=14.1/p75=15.0，fund<1.0 占比 **7.7%**（R2② 线 3-10% → **缓议**，候选阈值 0.5/1.5 只能动 5-11% 的 A 候选，收益上限薄）；MACD/MA 上下文：len≥22 股帧 100% 多日序列（长窗跨日渗入无处不在，与 p13/p21=100% 一致）。

**判定线对照（§12.0 冻结，未调线）**：Q1=立项 L2 ✓；R2②=缓议（7.7%∈[3%,10%)）✓；R4=可预登记（16.2%≥3%）✓；R5=可预登记（8.2%≥1%）✓；S-gate 自证 PASS ✓。**进入第二轮合同范围：时间正规化 L2 / jump 剂量（R3）/ warming（R4）/ persist（R5）/ 死分支修复（R7）；R2② 缓议不进本轮，R6 论证级不进本轮。**

### §12.2 第二轮合同审定（2026-10-07，模型A 输出归档 `voting-signals-modelA-round2-output.md`；用户执行投喂）

**审定结论：通过，零硬幻觉**。三处勘误全数正确接收并纳入设计（含 ③ 的口径自纠——把 cs 12.5% 按日帧基率解读为「无超比例污染」并把 A1 考题收窄，比主会话原表述更精确）；十字段齐备、算术复验（T3 票值 C=+0.375/B=+0.525、T4 三态 +0.75/0/−0.375、T5b 合成事件机械上恰好激活死分支条件、成本合计 32=2+1+10+4+4+6+5）；选型论证（隔夜剔除 vs 日界拆分 vs 日级聚合）三选一论证成立；oos2-only 改良线为保守选择。**判定线全部冻结，以下为跑前修正（主会话核实后的合同补全，非跑后调线）**：

1. **T1 p_adj 消费面泄漏（最重要）**：`technical` 的 `signals`/`macd.histogram` 同时进投票（compose_decision）与**风险通道**（risk.py:22-28 overheat 加减项 → lifecycle HighRisk veto/决策置信惩罚/compose_strategy 退出门槛），`momentumProfile` 进候选池（runtime:438/779）+ 展示分（:390）+ lifecycle 决策动量（:1172）。若 p_adj 直喂 analyze_technical，B1/B2 臂将连带改动 lifecycle veto/候选池构成——单变量被污染。**修正（G1 先例镜像：生命周期轮落默认时对 risk 动量分量做了中性化防御）**：T1 全部行为臂实施**风险通道隔离双算**——adj 序列只喂 `momentum_data`/`calculate_macd`/`calculate_ma_cross`（投票链：signals→compose_decision→rank tier）；`analyze_risk` 吃**原序列** technical（防御通道不吃时间正规化）；`momentum_profile`/候选池 trend_buy/lifecycle momentum 参数/observation scores 全保持原序列。实施=analyze_technical 增可选 adj 参数（纯函数双算，成本可忽略）。B1 臂对象笔误以 B1b 文字为准（全周期 [3,5,8,13,21] 含 p3）。
2. **T2 护栏数修正**：res S 基线用 R1 精确计数 **14,370**（合同写 14,314 系用四舍五入 9.5% 反推）→ 护栏 = **7,185**；synergy S ≥64（127/2）无误。
3. **T4 零态实施陷阱预登记**：`_synergy_tier` 的票映射 `cs_tier in _CS_STRENGTH`（A/B/C/D 四键）对 "A_PERSIST" 不命中 → **静默零票**（§15 list-shape 同类陷阱，config.py:526-537 守卫注释原文「长度不符会静默回退」同族）。零态「逐位一致」验收会抓住，但实施清单必须显式：扩展映射 A_PERSIST→0.5 于 `_CS_STRENGTH` 消费处（或等价分支），并把该陷阱写进 T4 阶段2 验收步骤。
4. **T1-A1 × T4 跨合同交互**：persist 判定位于 `_tier_from` 的 `delta is not None` 分支内——A1 落默认后跨日首帧（delta=None）**persist 路径不可达**；若 A1 与 T4 都晋升，A_PERSIST 在日首帧人群失效，两案合并复验时须覆盖该交互（登记，不阻塞本轮）。
5. **T1/A1-A2 的 S 供给护栏补列**：S 守门维实证（127/127 cs∈{A,B}）⇒ A1 砍跨日首帧的 cs A 供给、A2 砍日首帧的 res S 供给，都可能压 synergy S（现仅 127 帧）。T1 增登记列：**各臂 synergy S 帧数迁移**（预期下降，只登记；S 归零或 <50% 基线触发复议再评估，不当场终止）。
6. **D1 schema 修正**：R1 报告**无 per-frame regime 列**（合同写「R1 meta regime 列」系误记，R1 脚本未算 market_regime）——D1 新增 `market_regime(frame)` 逐帧计算（一行）；**二分映射提案（待用户追认）**：保留 strong/normal/weak/retreat 四态分列，预注册对比对=**strong vs retreat**（normal/weak 作上下文列不进「两桶同向」裁决），防映射自由度成为新拟合面。

**oos1 资格追认（建议，待用户确认）**：合同预注册 C2=oos2 主线（改良线，因 8 月污染历史保守）；oos1 经 no-regression 三窗/全窗线**隐含 gate**（与生命周期轮 G2「oos1 贴线差 0.0001 FAIL」判例一致——冻结的意义是 holdout 评估而非禁用）。追认后按此执行，开跑后不得改。

**待用户裁决三件**：①上述修正 1-6 采纳（建议全采纳，均为跑前合同补全）；②oos1 追认（建议按上文混合方案）；③开跑范围与顺序——建议 B0+D1 先行（共享基建，本地零模型调用），行为步按 T1（A1→A2→B1a→B1b→B2）→T5a（零行为逐位验证）→T2→T3→T4→T5b 顺序，任一环节判定线触发终止即停。

### §12.3 行为步执行报告（2026-10-07，用户三裁决后开跑：修正全采纳/oos1 追认/按序执行）

**B0 锚自证**：T2 runner 默认 config 三窗逐位复现生命周期轮 G1 锚 **0.1450/0.0983/0.1172**（首跑曾用 oos2 全月口径致 0.1057≠0.1172，已定位=锚的 population 是 09-12 帧截止（生命周期轮 loader 口径），非 data_windows 名义全月——population 与锚同口径复现后逐位 PASS）。Track 1 基线（同日 14:25 报告）：decision 172 笔 wrxpf 0.4140 / oos2 76 笔 0.1660。

**D1 合并诊断（1,071 帧至 09-30，报告 `data/reports/voting-signals-d1.json`）核心读数**：
- **T1 判定（前置步裁决）**：跨日分量 h8 后验**优于**日内——cs_delta CD +0.0350 vs SDa −0.0005；res_short +0.0169 vs −0.0064；rank_p3 +0.0175 vs −0.0037；p5/p8 零差；p13/p21 全跨日（序列内无同日对可比）。**「隔夜=噪声」假设被数据反杀：五臂全部按合同前置判据降级 monitor_only，行为步不跑**（隔夜跳空在热榜语境=注意力延续信号，与 lifecycle 的跨日假动量方向相反——两序列同原料不同维消费的分化是本轮最重要的结构发现）；
- **T3 前置**：warming buy 帧 h8 excess +0.0142>0 过线（strong +0.0279/retreat +0.0783 同向正、weak −0.0164 登记）；len4-8 占 10.0%、eligible 13,982、buy 票 4,416、crossed_B 298/crossed_A 28/sim_S 0；
- **T4 阶段1**：eligible_n5 excess +0.0367 vs B_not_eligible +0.0149，**diff +0.0218 过 +0.02 线，strong/retreat 同向** → 正态优先（retreat diff +0.105 最强）；
- **T5**：len1 5,631 帧，P(pct>50)=13.7%、P(确认门 v1.0)=19.3%、would_S_b2=61、**would_syn_S_b2=0**（61 帧全被 len1 的 cs≤B 封顶在 2.8<3.0）→ **T5-b 归档**（结构封顶，非样本不足）；
- jump 表：fail_chg_only 桶跨日占比低于同日相邻（chg 轴伪影假设不成立方向），chg 轴维持挂起。

**行为步判定（判定卡 C1∧C2(oos2)∧C3；全部存档不晋升）**：

| trial | decision | oos1 | oos2 | 判定 |
|---|---|---|---|---|
| T2 vr125 | +1.4% | +0.4% | **+9.8%** | FAIL_C1（护栏全过：resS 14,192≥7,185、synS 127≥64；Track 1 decision wrxpf 0.4057 vs 0.4140=−2.0% 未过 no-regression 但未触 −5% 终止）→ **monitor_only 观察池**（N1 同款命运，oos2 连续两代双位数正登记） |
| T2 vr150 | −0.4% | +8.3% | +10.3% | FAIL_C1（升档合同条款执行：护栏过但 C1 不过） |
| T3 W1 cap C | −1.0% | +5.2% | 0.0% | FAIL_C1（oos2 逐位=基线：warming 票未改变任何 oos2 synergy 档位） |
| T3 W2 cap B | −2.0% | +3.2% | 0.0% | FAIL_C1（剂量加深 decision 更伤，方向一致） |
| T4 t4pos +0.75 | **−11.7%** | +19.3% | +2.6% | FAIL_C1 重伤否决——**D1 h8 分层好 ≠ 加权后 saEx 好**（cs 票加码改变票和分布，eligible 高位股推过的 S/A 边际帧 h8 不佳；saEx 结构性教训 §4.3-4 的镜像案例）；synS 127→136（S 解锁通道存在但质量不支持） |
| T4 t4zero +0.5 | 0.0% | 0.0% | 0.0% | **PASS_IDENTICAL**（纯标签逐位一致工程验收过；A_PERSIST 枚举与映射落地待用户裁决是否保留） |
| T4 t4neg −0.5 | −2.1% | +8.1% | **−13.3%** | FAIL_C1 |
| T5a 删死分支 | — | — | — | **零行为验证 PASS**（三窗 saEx 与删除前逐位一致+ranktrend 全量 644 绿；两测试锚更新至 T5a 语义：函数级直注 events 也不再判 S） |

**实施与配置沉淀（全部默认 off=零行为，golden 已重录 configRepr 指纹+场景输出零漂移）**：
- `resonanceWarmingEnabled=False` / `resonanceWarmingTierCap="none"`（枚举校验 none/C/B）+ runtime warming 分支（同日锚重基/市场基准化/cap 档/只投 buy）+ `_build_signal` 传 timeKeys；
- `crossSectionPersistIndependentTier=False` / `tierSynergyCsPersistStrength=0.5` + cross_section A_PERSIST 独立档（固定 N=5，delta-A 之后原 B 之前）+ `_synergy_tier` cs 消费处显式 A_PERSIST 分支（§12.2 修正 3 陷阱防范：不扩 _CS_STRENGTH dict）+ compute_synergy_state 叙事不消费（预注册边界）；
- T5a：新入榜 S 死分支删除（runtime.py，注释登记 G4 先例风险）；
- 新 harness：`diagnose_voting_signals_exposure.py`（R1+D1 双模式）、`evaluate_voting_signals_t2.py`、`evaluate_voting_signals_t3_t4.py`；golden 快照重录一次（configRepr 新增字段文本）。

**本轮总裁决建议（待用户）**：五案行为步全部不晋升——①T1 归档 monitor_only（隔夜分量是信号的证据，四维时间正规化立项关闭）；②T2 vr125 入观察池（连续两代 oos2 双正，待下代际复验）；③T3/T4 存档（warming 零伤害但无收益；A_PERSIST 三态全不过）；④T5a 保留（零行为代码卫生）；⑤T5b 归档（结构封顶）。四信号结构与 R1/D1 全部读数已沉淀，后续研究入口=D1 报告+本节判定表。

## §13 语料包 v2（W2 前置增量投喂材料，2026-10-07 深夜组装；投喂由用户亲自执行）

> v2 地位：v1（§0-§9 材料+§11 战报+§12 执行）的**增量包**——投喂时 §0-§12 全文给模型，本节为新增。
> 待审定主项：W2-1/W2-2 预登记方向 + amount L2 合同（`vote-l2-vp-amount-tier-preregistration.md`）。
> 已裁决项（披露供复核，非待审）：rank 共识面 L2 否决（§13.3）、W1-1 开跑（合同已冻结，判定 §13.3 占位）。
> 审定纪律不变（§8 输出格式合同+算术/事实逐条可核+硬幻觉=驳回；Q1/P5 Opus 审定同款）。

### §13.0 v2 投喂开场（粘给模型的增量任务卡）

你是第二轮审定模型。第一轮（§11）的 A/B 结论已执行：五案全不晋升、结构发现已沉淀（§12.3）。
本轮请你审定三个待办的方向性材料：
1. **W2-1 隔夜延续特征**与 **W2-2 价格确认门泛化**（§13.4 命题原文）——形态选择、剂量面、
   与既有证据的相容性、预登记合同起草要点；
2. **amount 喂 tier L2 合同**（§13.5 要点+全文归档 `vote-l2-vp-amount-tier-preregistration.md`）——
   臂设计/判定线/风险自报的攻击面（算术逐条复核，硬幻觉=驳回）；
3. **rank 共识面否决判定复核**（§13.3）——前置诊断四窗反向是否足以否决，反向命题
   （差一票作负向信号）的处置是否恰当。
输出格式：逐项「复述承重墙→归因四步→可执行提案（含预登记判定线建议）」，硬幻觉自查表附末。

### §13.1 三裁决后全局态势（2026-10-07 深夜）

- **Q1 价量喂入**：15 臂全 FAIL 阴性登记零默认改动（台账 §22）——C-a dv 三臂全灭（扩档拉动
  非判别改善，「效度验证→给权重」路径证伪）+C-c direction_gate 零效应；两大结构事实=P 剂量轴退化
  （±P 只经符号起作用，+P 点不着点火路径）+gap 补位证据无害但无效。
- **P5 双轴 allow 分位带门**（并行线，同晚用户授权）：接线+golden 已完成、trial baseline 臂自证过
  （saEx=0.14503 与 G1 锚一致）后进程中断悬置中——恢复续跑/处置由其线负责。
- **用户三裁决**（「Q1已闭环，请执行以上3项」）：①amount L2 立项 ②rank 阈值面 L2 立项 ③W1-1 开跑。
  执行结果：①合同备料完成（§13.5）；②前置诊断阴性否决（§13.3）；③W1-1 harness 备好，
  接线待 P5 收官解锁（config.py 纠缠先例处置）。
- **当前五维票位实态不变**：res/rank/cs 0.75 + vp 1.0（E 硬短路）+ pm/dv 0.0（W0-1 摘除已授权待执行）
  + lc 环境门。

### §13.2 结构发现沉淀（v1 §12.3 之后新增，全部已归档可复核）

1. **cs 守门维**：synergy S 档 127 帧（0.08%）127/127 靠 cs 正票撑进——S 档是 cs 单点依赖结构；
2. **synergy S 数学边界**：len1 帧 cs≤B 顶死 2.8<3.0（T5b）——新入榜结构性够不着 S；
3. **D∧buy 倒挂**：res 衰竭档（reversal_penalty≥0.6）方向 buy 时投 +0.75 > B +0.525（方向主导
   设计副作用），此类帧 6.6%——W1-1 修复 trial 进行中（判定见 §13.3 占位）；
4. **双动量分歧**：momentum_data（投票）vs momentum_profile（候选池/lifecycle）同源不同式，
   符号分歧 18%（n=76,142）——W3-1 合一候选（待 P5/Q1 后解锁）；
5. **fallback 覆盖 36.5%**：rank 维三分之一帧吃当帧标量 fallback（ln 短序列质量差）；
6. **跨日分量后验优于日内**（T1 反杀）：隔夜=注意力延续信号——W2-1 的直接依据；
7. **「独立票死、门活」**（pm/dv vs vp E/jump 门）：价格类信息作加性票被证伪两次
   （Q1 C-a dv 三臂+T4），作确认门/短路有效（vp E −32% wrxpf、jump 门修复 +18.1%）——
   W2-2 的形态约束：泛化「门」不新造「票」；
8. **扩档拉动≠判别改善**（Q1 C-a 结构事实②）：S/A 帧膨胀而 excess 反向——任何「升档/加票」
   形态的先验负面证据；W1-1 abstain 臂与 amount 缩量升档臂都是扩张面，判定须盯档位计数披露。

### §13.3 W0/W1 读数汇总（判定已出的全列，W1-1 占位）

| 项 | 判定 | 关键读数 |
|---|---|---|
| W0-2 amount 杠杆重估 | **达线立项→合同备料完成（§13.5）** | 可算率 decision 72.4%（旧前提 6.12% 被回填推翻）；h8 分层四窗一致单调：放量(≥1.5) −0.0127 / 缩量(≤0.5) +0.0146（decision），|max|=0.0273；`vp_tier_drift`=0（tier 不消费 score 自证） |
| W1-2 rank 稀疏票 | **达立项线→前置诊断→阴性否决归档** | 差一票占 C 档 31.9%（四窗稳定）达 10% 线；但 W1-2.1 前置诊断（预声明线 ≥+0.01）：dbuy1−c_rest 四窗 4/4 反向（decision −0.0219）=差一票帧是 h8 后验更差人群，共识门槛挡下=正确设计；分数轴无支持（近阈值 0.5%+0.18 OOS 旧账）。覆盖面与不覆盖姿势（反向命题=负向信号观察线索）见 `vote-l2-rank-consensus-preregistration.md` |
| W1-1 res D∧buy 倒挂票 | **trial 收官：全臂 FAIL_C1 阴性登记，零默认改动（2026-10-08）** | B0 三窗逐位自证 PASS；cap_b rel −0.58%/+1.98%/+0.49%、abstain −0.10%/+0.15%/+1.05%（C1 线 +3% 双臂不过，C2/C3 双过）；护栏满值（resS 14,370/synS 127/res 分布逐位一致）；**S 档守门 127/127 两臂全保**（守门维未破坏）；改判面 cap_b 6.1%/abstain 44%；**Track1 双正**：wrxpf +5.27%/+4.28%+maxDD 双改善+174 笔——「倒挂票修正收益在交易面不在信号面」，与 P5 a3 对照发现跨线互证；重开唯一合法路径=新合同以 Track1 为主判定面重新预登记；市况 strong 降/retreat 逐位相同（改判不触 retreat 桶）非反号 |
| W0-1 删 pm/dv 死票位 | **已授权，W1-1 提交后顺路补做** | C-a 三臂全灭后 dv 维持观察位（权重 0.0），摘除与「保持观察位」结论一致；验收=全窗信号+Track 1 逐位一致+测试绿+golden 重录 |

### §13.4 W2 命题（计划原文摘录，待双模型审定形态）

- **W2-1 隔夜延续特征**（T1 反杀直接长出的新票位）：跨日分量方向后验优于日内（cs_delta CD +0.0350
  vs SD −0.0005 等）——「昨日末帧→今日首帧跳空方向」本身是未消费信号。形态三选（由审定定）：
  ①第 8 加性维（跳空方向×幅度分位）；②cs 维 delta 语义扩展（隔夜/日内分开计票）；③确认门形态
  （跳空作 res/rank buy 的放大器非独立票——吸取 pm/dv「独立票失败、门有效」教训）。
  市况假设：强情绪期隔夜延续（信号）、退潮期隔夜断裂（噪声）——分桶预注册，反向即挂起。
  风险=10 月行情单一代际、需逐月验稳定。
- **W2-2 价格确认门泛化**（res/rank 接通用价格门）：价格「独立票」死（pm/dv）但「门」活（vp E 短路
  −32% wrxpf、jump 门修复 +18.1%）——把「排名说涨，价格认不认」从 Jump 专属泛化。形态候选：
  rank buy 档需当帧 change≥θ（或 price_changes 3 帧方向确认）才保 S/A，否则降 B；res 同构；
  θ 分位化找自然分界。关键前置=与 dv/priceMomentum 观察维冗余面测定（生命周期 P2 教训：同族原料
  先测重叠率）；与 rank 稀疏诊断联动（门加在 15% 方向票上）。
- **审定要回答**：①两案各自的形态选择与理由（独立票/门/放大器的判定框架）；②剂量面与预登记
  判定线建议；③与 §13.2 八条结构发现的相容性冲突；④优先级（若只能跑一个先跑谁）；⑤反对立项
  的理由（若认为证据不足，明说缺什么数据）。

### §13.5 amount L2 合同要点（待审定主项；全文 `vote-l2-vp-amount-tier-preregistration.md`）

- 机制：`volumePriceAmountTierMode` off/high_demote/both——主臂=放量奖励撤回（ar≥1.5 ∧ rise_volume
  → A→B/B→C），对照臂=双向门（+ar≤0.5 ∧ rise_shrink/normal 的 C → 升 B）；门限复用
  amountRatioHigh/Low 零新阈值；E 短路/缩量涨停 reasons 优先级不动；score 链零改动（纯 tier 面）。
- 判定卡：C1 ≥+3% ∧ C2 oos2 同向正 ∧ C3 passHard 不降 + Track1 wrxpf ≥0（maxDD 容差）+ 护栏
  （resS≥7185/synS≥64）+ vp tier 分布迁移披露（a 臂预期 A+B 面↓反升=实现错误）+ 市况分桶
  （strong vs retreat 反号挂起=本case高危项）。
- 自报风险六条见合同 §六（混杂面/剂量轴未扫/升档稀释/效应量小/顺序 bug/口径人群差异）。

## §14 语料包 v2 审定战报（2026-10-08，用户亲自投喂执行；输出归档 `voting-signals-corpus-v2-review.md`）

### §14.1 审定结论与落实状态

| 待审项 | 审定结论 | 落实 |
|---|---|---|
| W2-1/W2-2 方向 | **形态裁定=降档确认门（收缩面）**：W2-2 立项优先；W2-1 取形态③且方向翻转为收缩面，否①（第 8 加性维撞「独立票死」）、否/延后②（cs delta 语义扩展，与 W3-2 同维互相污染归因应合并设计）；三形态先验矩阵=加性票（证伪×2）＜升档放大器（扩档先验负）＜降档门（验证×2） | 前置判定见 §14.2/§14.3 |
| amount L2 合同 | **有条件通过（算术逐条复核全 ✓）**：A1 接线依赖声明/A2 Track1 补 oos2 披露/A5 retreat 桶 n<50 降级三项必改+A3 oos1 止损带/A4 a-b 腿配对披露两项建议；预期管理=触面乘积下 C1 大概率不达，阴性归档路径合法 | **合同 v1.1 已落实全部五项**（跑前补全非调线），待用户裁决开跑（接线另待 P5 收官解锁） |
| rank 共识面否决 | **维持**（四重强度：预声明线机械执行/样本量大/双口径同向/反向幅度超线值）；反向命题保持观察线索地位（同一数据不可双重消费+三重冗余面未测+oos2 幅度衰减 5 倍）；未来立项补强条件已登记 | 已按审定补强条件更新否决登记 |

- **审定硬幻觉自查**：档案静态比对逐位一致（含一处舍入差如实注明）；语料转引项与台账交叉印证。
- **通用判定卡条款沉淀（审定提出，后续门类合同全款继承）**：触发率披露（门改判 <2% 或 =0 →
  零效应阴性不提交，Q1 C-c 教训成文化）+retreat 桶 n<50 股帧降级只披露（29 帧小样本反号会随机
  触发；注意口径=帧数≠股帧样本数，retreat 29 帧×百股=数百 cell 样本，下限按股帧计）。

### §14.2 W2-1 前置判定：市况先验过线、靶人群分解无靶 → **挂起**

- **市况分桶先验（零成本直读 w12r JSON t1 cell，预声明挂起条款）**：decision 窗四桶
  CD−SDa（n 加权）全部为正——strong +0.0355 / normal +0.0281 / weak +0.0122 / **retreat +0.0083**
  （retreat 桶股帧 n=356-1,459 远超 50 下限）；挂起条款「退潮桶 CD≈SD」不触发。强市区分度 4 倍于
  退潮=与市况假设方向一致，但无一桶反号。
- **靶人群分解（形态③门真靶，`voting-signals-w2x-gates.json` w21 分节）**：跨日首帧 ∧ buy 帧
  延续（cs_delta>0）vs 断裂（≤0）的 h8——**res 侧大样本零区分**（断裂 n=16,050，
  brk−cont=+0.0017/+0.0056/+0.0018/−0.0018 四窗零散）；**rank 侧微样本**（buy∧跨日∧断裂四窗
  合计仅 43 帧，decision 主判定窗反向 +0.0517）。
- **判定：挂起（非阴性否决）**——T1「跨日帧的 cs_delta 有信息（CD>SDa）」不蕴含「跨日帧内部
  断裂符号有判别力」，后者实测为零/微样本不可判。前置诊断省掉一个注定零效应的 trial（审定
  「反对立项理由」中「触面 12.5% 天花板+假设未验」两条以更硬的形式应验）。
- **不覆盖姿势（防阴性终局）**：断裂定义的其他形态（幅度分位而非符号）；断裂×市况/其他维交互；
  「延续→升档」反向形态（撞扩档先验未测）；新代际复验。

### §14.3 W2-2 前置判定：四窗 4/4 强同向过线 → **立项合同备料完成**

- **靶人群 h8（预声明线 w22|sa|low−high ≤ −0.01 且 ≥3 窗同向）**：rank buy ∧ S/A 帧按当帧
  change low(<0)/high(≥0) 分层——decision **low −0.0665（n=1,014）vs high +0.0006（n=3,857），
  差 −0.0671**；midgap −0.1095/oos1 −0.0753/oos2 −0.0981，**四窗 4/4 全负，量级为线值 6-10 倍**；
  res 侧同构 −0.0376/−0.0729/−0.0296/−0.0320 全负。低 change buy 帧不是无超额而是显著负超额。
- **触发面**：low 占 rank S/A buy 帧 20.8%（decision）；change 分位谱 p50=+5.16（半数 buy 帧
  当帧涨 5%+，low 是明确异类少数派，0 界=自然分界）。
- **合同**：`vote-w22-price-gate-preregistration.md`（判定线冻结于跑数前）——单参三态
  `tierConfirmPriceGateMode` off/rank/rank_res，门=「维 buy ∧ S/A ∧ change<0 → 降 B」（θ=0 单帧
  形态，3 帧确认留后续）；判定卡=审定骨架全款（C1/C2/C3+oos1 止损带+Track1 双窗+触发率+retreat
  降级+护栏半数线+S/A 面变化披露+迁移矩阵）；序贯条款=W1-1 落默认后 g_rank_res 臂须复验；
  冗余面（dv/pm 共线率）=trial 前置补跑（共线 >80% 重新评估并披露后才开 trial）；接线待 P5 收官。
- **执行注记（诚实登记）**：首跑 W2-2 列时 h8s 取值置于赋值前（跨帧残留静默错位一格），
  发现后废跑重计（废数据已删，文件头已注记防再犯）；W2-1/W2-2 两列同脚本一次 replay 出数。
