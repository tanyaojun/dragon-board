# SP5 实施计划与交接——jev 日级情绪叙事研究（温度机会轴 × 拥挤风险轴）

**日期**：2026-10-01（SP4 收尾对话产出交接）
**性质**：writing-plans 交接文档——下一对话以此开启 SP5。
**状态**：**待开启**（前置：SP4 T5 走廊已在跑，不阻塞 SP5 证据研究；新臂上场受挑战者预算约束）。
**用户裁决（2026-10-01，四点）**：
1. jev 日级叙事需落库——**勘误后已确认无需补**：day_temperature/day_crowding 一直在库（eod `scores` 下，113/113 全覆盖），此前"未落库"为 T-jev 读错字段名误诊；
2. 历史不补，靠增量数据后续验证；
3. jev 叙事阈值**禁止照抄规则文档四带**——不同故事、不同数据源、不同标定；
4. **SP5 核心假设（用户提出）**：温度值代表正向机会（可加仓进攻），拥挤值代表高位风险（需减仓规避），两轴都需要**锚定点与出入场判定点**，形态对标相位轴与四带阶梯。

---

## 1. 前序阶段结论总账（SP5 的地基，全部有产物/台账背书）

| 阶段 | 结论 | 对 SP5 的约束 |
|---|---|---|
| M3/M4 ladder v1 | 四带阶梯（冷<40 满 / 40-60 禁入 / ≥60 三成，前日 EOD 定相）= champion：拦损 α 集中在弱势带禁入；全窗 fresh 读数 35 笔 +61.56% mdd -1.66%（对照 baseline 54 笔 +21.67% -4.87%）；正式台账 C7 记录 +49.1%（差异=eod 代际，对账结论见 SP4 状态头） | 水平带阶梯机制已被证明；SP5 两轴对标此形态但**阈值必须自标定** |
| 2D 双维阶梯 | **否定收口**：水平带×Δ 双维帧级无分离（p 0.29-0.73 全不带） | **前车之鉴**：温度×拥挤组合阶梯不可先验假设成立，必须单轴证据先行、组合后置 |
| 5 带细分 | 否定收口（冷带内无异质性，p=0.653） | 分带粒度以证据为准，不预设越细越好 |
| 上移加仓 T0 | **否定收口**：升级态帧无优势（仅 7 个样本帧） | **"加仓进攻"有否定先例**——温度轴的"加仓"端必须先过帧级+交易层证据门，否则先做"低温减仓"（防守向） |
| SP3 slot as-of | 达标：同槽新鲜读 > 前日 EOD（slot_then_prev_eod 载体已落地） | 时点选择的方法论基础：同槽/日内信息优于前日 |
| SP4 相位源切换 | jev 同槽 sequence_stage 作相位源（C4：+0.095pp p=0.0013）；jev_seq_v1 臂上岗走 10-12 月样本外走廊；9 月短窗与全窗三臂对照已存档 | 挑战者预算 ≤2 占用中（exit_v1+jev_seq_v1）；SP5 新臂一律排队 |
| T-jev2 温度/拥挤 | **槽级温度 Q4vsQ1 +0.206pp p=2e-05（全场最强帧级信号，热→强）**；拥挤两 level 无分离（H1 读数）；前日日温全窗负向 = 跨月分位 Simpson 伪影（逐月 5/6 正向）；槽温↔规则分 Spearman 0.717（信息大部分共享，增量在时点） | 温度轴有真实信号；**拥挤"无分离"结论仅对 H1 读数成立**（见 §3 读数错配）；标定窗分位数：槽温 p25/50/75=24.9/32.6/45.9，日温=31.6/43.1/54.0（min15/max77），日拥挤=19.1/25.2/29.8，槽拥挤=16.2/20.9/26.2 |
| jev 轨道设计 §13 | jev 结论经相位定义层进研究开关（默认关）；不直接进信号引擎；标签落库即冻结；规则口径降级 fallback | SP5 全程适用；日级字段=`scores.day_temperature/day_crowding`（113/113） |
| jev_band_v1（已预登记排队） | 槽级温度带阶梯：温度 ≤24.9 → 0.3 / 其余 1.0 / 缺标签放行；载体 source=jev_temp_band 已实现+测试 | SP5 若产出日级带候选，同模板排队；**不得与 jev_band_v1 重复**（那是槽级冷端防守） |

## 2. 数据与资产现状（SP5 直接可用）

- **日级叙事分数**：113 个 eod 冻结文档（2026-04-15→09-30），`hotlist_jev_sentiment kind=eod status=ok` → `scores.day_temperature / scores.day_crowding`（100% 覆盖）；配套 day_stage/day_pattern。
- **槽级叙事分数**：1070 个槽文档，`scores.temperature/crowding`（100% 覆盖）。
- **规则分对照轴**：`hotlist_sentiment` emotionScore（同槽 + EOD），正交性检验用（已知：槽温↔规则分 0.717、日温↔前日规则分 0.526、槽拥挤↔规则分 0.281 接近正交）。
- **帧级 H1 诊断框架**：`backend/operations/diagnose_jev_temp_crowding.py`（四口径分带 + Spearman，可扩展）；`diagnose_jev_phase_caliber.py`（两档口径）。
- **载体先例**：`execution.py` `_jev_phase_factor`（两因子制）/ `_jev_temp_band_factor`（温度带）；ladder 模式；`attribution_stats` 已泛化 jev_ 前缀分源。
- **回测对照**：`diagnose_jev_seq_backtest.py --start/--end/--out`（三臂 A/B，带自检退出码 3=INVALID）。
- **标签冻结**：`jev_phase_label_run.py`（--force 版本自增）；走廊程序在 SP4 状态头。

## 3. 方法论红线与教训（SP5 必读）

1. **读数错配警示（本轮最重要洞察）**：T-jev2 用 H1（下槽收益）测拥挤得"无分离"——**不等于拥挤轴无信号**。用户假设"拥挤=高位风险→减仓"是**回撤端**假设，正确读数是风险类：后续 N 槽最大不利偏移（MAE）、持有期回撤、池内高标回落幅度。SP5 证据门必须**按轴配读数**：温度轴用收益类（H1/持有收益），拥挤轴用回撤类。用错读数会错杀真信号。
2. **2D 前车之鉴**：温度×拥挤组合阶梯先验不成立，单轴证据先行，组合后置且需独立证据门。
3. **加仓否定先例**：温度"加仓进攻"端必须先证明"高温优于中温"（不只是"高温优于低温"），否则先做防守向（低温减仓，即已预登记的 jev_band_v1 思路的日级版）。
4. **Simpson 教训**：跨月混合分位会翻转方向（前日日温全窗负 vs 逐月 5/6 正）——日级研究**必须逐月分析** + 固定标定窗阈值（冻结，禁按月重标定）。
5. **阈值禁抄四带**（用户裁决）：LLM 分数标定未知，一律样本分位数自标定 + 冻结。
6. **预算与晋升**：挑战者 ≤2（现占 exit_v1+jev_seq_v1；队列 jev_band_v1/rebal_v1/slot_v1）；晋升=章程 §6（≥2 样本外月同向 + ≥30 笔 + 回撤改善 + 用户终审）；in-sample 证据只立候选不翻默认。
7. **fail-visible / 冻结 / 不入信号引擎**：全程沿用 §13 消费纪律。

## 4. SP5 研究问题定义（三问）

- **Q-温度（机会轴）**：日级温度（前日 as-of）能否划出"进攻带"——带内入场/持有收益显著优于带外？锚定点=温度带界（分位数冻结）；判定点=带界穿越 + 确认机制（是否需要连续 N 日滞后确认，对照 stage_confirm 思想，防单日噪声）。
- **Q-拥挤（风险轴）**：日级拥挤（前日或当日最新已采槽 as-of）能否划出"防守带"——带内**回撤类读数**（MAE/持有期最大回撤/高标回落）显著恶化？判定点=拥挤带界触发**减仓/出场**（天然走 exit 端，参照 exit_v1 per_band 载体先例），而非入场端。
- **Q-两轴关系**：温度与拥挤是否正交（槽级仅 0.387 相关）？能否构成"温度定进攻档位 + 拥挤定防守闸门"的**分工双轴**（而非 2D 交叉矩阵——后者已被否定）？分工双轴=两个独立单轴开关的组合使用，不建交叉带。

## 5. 建议任务分解（草案，下个对话按此细化执行）

| # | 任务 | 要点 | 验收 |
|---|---|---|---|
| T1 | 日级两轴标定与分布分析（只读诊断） | 113 日 day_temperature/day_crowding：全窗+逐月分布、分位数、跨月稳定性（秩相关/分布漂移）、与 emotionScore/槽温的秩相关；温度与拥挤的相关矩阵 | 产物 jev-day-axis-calibration.json；两轴独立性结论 |
| T2 | 证据门——**按轴配读数**（只读诊断） | 温度轴：前日日温分带 → 帧级 H1 + 逐月（复用 T-jev2 框架）；拥挤轴：前日/同日日拥挤分带 → **回撤类读数**（帧池 MAE、后续 N 槽累计最不利偏移）+ 交易层持仓回撤对照；各自逐月一致性 | 产物 jev-day-axis-evidence.json；预登记门：温度轴 ≥2 月同向显著；拥挤轴回撤分离 ≥2 月同向 |
| T3 | 锚定点与出入场判定设计（文档预登记） | 带界冻结（标定窗分位数）；穿越确认机制（滞后 N 日/槽，防抖）；温度轴→入场端因子（冷温减仓起步，加仓端仅当 T2 证明"高温>中温"）；拥挤轴→出场/减仓端（phaseExitCoupling 通道） | 预登记文档：阈值/因子表/as-of 纪律/确认参数，全部冻结 |
| T4 | 载体实现（TDD） | source=jev_day_temp_band（入场端，参照 jev_temp_band）+ 拥挤出场判定（phaseExitCoupling 新 mode 或独立开关）；golden 锚；归因分源 | pytest 全绿；无键逐位不变 |
| T5 | 排队与走廊 | 新臂按预算排队（当前队列已有 jev_band_v1——SP5 日级臂与它关系：槽级冷端 vs 日级全带，需用户裁决合并或并行排队）；10 月起脉拍/月度对照 | 晋升按章程 §6 |

## 6. 风险登记

- **信息共享风险**：槽温↔规则分 0.717——日级温度与规则分相关性待 T1 实测；若日温也高相关，SP5 的增量论证必须落在"时点/形态"而非"信息源"。
- **拥挤轴可能真无信号**：若 T2 回撤类读数仍无分离 → 诚实收口，拥挤降级为纯披露字段。
- **加仓端否定先例**：温度"加仓"端证据不足时绝不硬上（T0 教训）。
- **LLM 非确定性**：日级分数随文档冻结；前向积累的新文档与旧标定窗可能漂移——月度漂移抽检程序沿用 SP4 T5。
- **多重比较**：两轴×多阈值×多读数的选择效应——预登记唯一主读数 + 其余为敏感性，走廊样本外才是裁决。

## 7. 关键文件与命令速查

```
# 诊断（只读，可随时跑）
cd quant-board
./.venv/Scripts/python.exe -m backend.operations.diagnose_jev_temp_crowding          # 四口径分带+秩相关
./.venv/Scripts/python.exe -m backend.operations.diagnose_jev_seq_backtest --start ... --end ... --out ...
# 回放（前向积累日级文档；禁全量重放扰动冻结标签）
./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 1
# 标签（冻结纪律）
./.venv/Scripts/python.exe -m backend.operations.jev_phase_label_run --out data/reports/phase-monitor/phase-labels-jev-v3.json --fallback data/reports/phase-monitor/phase-labels-v2.json [--force]
# 脉拍（月度走廊）
./.venv/Scripts/python.exe -m backend.operations.phase_pulse --month YYYY-MM
```

- 章程：`ranktrend-position-management-charter.md`（§3.1 相位源演进 / §5.6 预算 / §6 门槛）
- 地图台账：`ranktrend-phase-map-baseline.md` §7（全部候选收口记录）
- SP4 计划：`ranktrend-position-sp4-plan.md`（状态头 = 当前完整状态 + 排队候选 jev_band_v1 预登记）
- jev 设计：`docs/hotlist-jev/hotlist-jev-emotion-observe-design.md` §13（相位源授权条款）
- 引擎载体：`backend/core/backtest/execution.py`（`_jev_phase_factor` / `_jev_temp_band_factor` / ladder）
- token：`quant-board/.env.local` `JEV_CF_TOKEN=`（不入仓）

---

**给下一个对话的开场指引**：先读本文件 + SP4 状态头 + 地图台账 §7，然后从 T1（日级两轴标定）开始——只读诊断、零成本、直接产出温度/拥挤两轴的"锚定点"证据基础。用户假设按证据推进：温度轴的"加仓进攻"端与拥挤轴的"减仓防守"端分别过各自证据门后才立载体，任何一步不达标即诚实收口。
