# 仓位管理专项 SP2 实施计划——出场端相位耦合泛化 + 动态调仓（只减不加）

**日期**：2026-10-01
**性质**：writing-plans 产出（章程 `ranktrend-position-management-charter.md` §4 SP2 的任务级计划）。
**状态**：待用户放行执行（前置：SP1 已执行完毕，待 review 提交）。
**范围**：① C8 泛化为 per-band 出场参数表（`phaseExitCoupling` v2）；② `phaseRebalance` 持仓中带下移减仓（Q2 裁决纳入，只减不加 v1）；③ 脉拍 A/B 臂接线与归因扩展。对应假设族预登记：SP2-EXIT-strong-tighten、SP2-REBAL-v1（地图基线 §7）。
**非目标**：加码/金字塔（方案 α 裁决 2026-10-01：v1 只减不加；上移加仓以 SP2-REBAL-ADD-OBS 观察臂 frame-level 证据先行，成立后另立提案）；ladder champion v1 变更；sentiment_2b 定义线变更；vol 轴接引擎。

---

## 代码事实基线（2026-10-01 核实，execution.py 行号为当前 HEAD+SP1 后）

| 事实 | 位置 | SP2 含义 |
|---|---|---|
| `exitTpMultiplier`（C8 冷带定档）已在 3 处 TP 消费点统一生效 | `_exit_prices` L757 / `_rank_exit_triggered` L1193 / `_exit_reason` L1557 | TP 倍率泛化=换盖章来源，消费点已齐 |
| **maxHoldingBars 有 4 处消费点** | L303（价格退出路径 max_holding_exit）/ L1189（_rank_exit_triggered）/ L1219（另一 exit-trigger）/ L1551（_exit_reason 标注） | per-band 持有覆盖必须走单一解析 helper，4 处全换——C8「接线错位」教训的直接应用 |
| breakeven：`breakevenTrailing` + `breakevenThreshold` + 粘性 `pos["breakevenActivated"]` | `_exit_prices` L775-780 | per-band BE 阈值=盖章 `exitBreakevenThreshold`，_exit_prices 回退 config |
| 卖出走 `_match_order(side="sell", requested_quantity)`，部分成交已支持（quantity < pos.quantity 时减仓保留仓位，成本基线按股均摊 L383） | L375-392 | rebalance 部分减仓复用同一撮合（滑点/涨跌停/费用自动一致） |
| T+1 门：入场当日不评估退出 | L216 | rebalance 必须同门（当日买入不可当日调减） |

## T1 per-band 出场参数表（`phaseExitCoupling` v2）

TDD 先行。设计：

```python
trade_config["phaseExitCoupling"] = {
    "mode": "per_band",   # 新模式；cold_tp_widen 保留为兼容模式（行为不变，回归锚在案）
    "bands": {            # 键=四带标签（与 _phase_context.band 同源）；缺带=全默认
        "强60-80": {"tpMultiplier": 0.8, "maxHoldingBars": 30, "breakevenThreshold": 0.015},
        "冷10-40": {"tpMultiplier": 1.5},
    },
    "eodScores": {...},   # 与既有约定一致（入场日定档用前日分）
}
```

| # | 改动 | 要点 |
|---|---|---|
| T1.1 | 测试先行：`tests/backtest/test_phase_exit_coupling_v2.py` | per_band 解析/缺带回退/非法值回退（fail-visible）；盖章→消费端到端；**cold_tp_widen 回归锚逐位不变**（既有 4 个 C8 测试不破） |
| T1.2 | `execution.py`：入场盖章扩展 | 入场带已知（SP1 entryPhase.band）→ 查 bands 表 → 盖 `exitTpMultiplier`（复用）/ `exitBreakevenThreshold`（新）/ `exitMaxHoldingBars`（新）；无规则=不盖（golden 不变） |
| T1.3 | `execution.py`：`_effective_max_holding_bars(pos, config)` 单一解析 helper | 4 处消费点（L303/L1189/L1219/L1551）全部改走 helper；`pos.exitMaxHoldingBars` 优先，回退 config.maxHoldingBars |
| T1.4 | `_exit_prices`：BE 阈值读 `pos.exitBreakevenThreshold`（回退 config.breakevenThreshold） | 消费点单一（_exit_prices 已是 BE 唯一闸门） |

**验收**：`pytest tests/backtest -q` 全绿（含 C8 回归锚）；无 phaseExitCoupling 键时 run 输出与 SP1 基线逐位相同（新增 golden 锚用例）。

## T2 动态调仓（`phaseRebalance`，v1：仅下移入冷→清仓）

极简参数化（2 个语义开关，防过拟合）。**规则由历史反事实验证选定**（2026-10-01 用户授权数据说话，产物 `downgrade-rule-variants.json`）：

- →弱 转移不动作：强→弱 18 笔不动作 +30.19% 完胜减半（+25.50%）/清仓（+20.46%）——降档多为瞬时噪声；
- 仅下移入 冷10-40 → 清仓：任意→冷 11 笔不动作 −30.54%，减半/清仓均救回 ~4pp（−26.24/−26.47，噪声级差异，取清仓=参数更简+退潮兑现语义+尾部更保守）；
- 极热→弱 原争议格：n=1（清仓 +0.50%/减半 −2.01%/不动 −4.52%），无统计权重，在新规则下与所有 →弱 一致不动作；
- 冷带入场的持仓豁免（慢牛区机制，回归冷带不清仓）。

```python
trade_config["phaseRebalance"] = {
    "enabled": true,          # 缺省 false = golden 逐位不变
    "eodScores": {...},
    "actOn": "into_cold_clear",  # 仅前日带下移入 冷10-40 → 次帧清仓；其余下移/上移不动作
    "coldEntryExempt": true,     # 入场带=冷的持仓豁免（慢牛区机制）
}
```

| # | 改动 | 要点 |
|---|---|---|
| T2.1 | 测试先行：`tests/backtest/test_phase_rebalance.py` | 触发矩阵（入场带×当前带：仅 **X→冷** 触发，→弱/→强/上移均不动作）；冷带入场豁免；T+1 当日不触发；清仓数量/成本按全量、成交行 reason=`相位调仓(入冷清仓)`；同带粘性不重复触发；**golden 锚：无 phaseRebalance 键逐位不变** |
| T2.2 | `execution.py`：逐帧持仓循环加 rebalance 评估（**实现位置=should_exit 链之后、breakBoard 之前**——同帧信号/价格退出胜出，调仓只捕获未退出持仓；计划初稿写「退出评估之前」已回写更正） | 当前带=_phase_context 前日分 as-of；仅 前日带=冷 且 入场带≠冷 时清仓（v1 规则）；走 `_match_order("sell", 全量)`（滑点/费用/涨跌停自动一致）；成交行 reason=`相位调仓(入冷清仓)`，带 rebalanceFrom/rebalanceTo 标注；trade_events 同步；费用如实计入 |
| T2.3 | 归因：成交行携带 `rebalance` 子文档 | {fromBand, toBand, factor}——脉拍 attribution 可分轴归因的前提 |
| T2.4 | **上移加仓观察臂（SP2-REBAL-ADD-OBS，不接引擎）** | 新增诊断脚本 `backend/operations/diagnose_band_upgrade_add.py`（沿 diagnose_* 惯例，只读）：对「入场带=冷10-40 且当前帧带升入 强60-80/极热≥80」的持仓段统计帧级池 forward 收益 + 交易层双口径，对照「入场冷带且未升级」；判据=升级段 forward 期望显著为正且 ≥ 未升级对照（Mann-Whitney 或均值差，沿 phase_quality_report 口径）→ 达标才允许 SP3 提出上移加仓引擎提案；产物落 phase-monitor，结论转录地图基线 §7 |

**验收**：`pytest tests/backtest -q` 全绿；模拟场景断言「强/极热带入场→前日转冷带→次日清仓；→弱 转移不动作；冷带入场→任何切换不动」。

## T3 脉拍 A/B 臂接线与归因扩展

| # | 改动 | 要点 |
|---|---|---|
| T3.1 | `phase_pulse.py`：臂装配从硬编码改登记驱动 | 臂清单=gate-off 基线 + ladder champion v1（既有）+ **≤2 个 challenger**（读地图基线 §7 台账 pending 顶部）；`--arms` 参数可显式覆盖；守章程 §5.6 预算 |
| T3.2 | 归因段扩展 | attribution 增 `rebalanceEvents`（次数/分带分布/减仓节省）与出场耦合生效笔数；challenger 臂各自的 attribution 已随 ab[].attribution 存在 |
| T3.3 | 前端脉拍卡兼容 | 新臂键名的降级展示（fail-visible：未知臂不炸卡）——改 `phaseMonitor.ts` 类型 + 面板渲染，vitest 同步 |

**验收**：pytest + 根前端 vitest + vue-tsc；交易时段外实跑一轮 `phase_pulse --month 当月`（基线+champion+≤2 challenger），报告含全臂归因。

## T4 验证与晋升（持续，非开发任务）

- 晋升门槛（章程 §6）：每臂 ≥2 样本外脉拍月同向 + 新增笔数 ≥30 + 回撤改善 + 用户终审；一次一候选翻开关；
- tripwire（章程 §5.5）：challenger 连续 2 月劣于 champion 自动退池；champion 连续 2 月双劣于 gate-off 强制评审；
- 版本线：`phaseExitCoupling` 与 `phaseRebalance` 是独立研究开关（默认关），开发完成≠换代；换代走本计划 T4 门槛，与 ladder 线互斥推进（同期只动一条，章程 §5.7）。

## 回退风险

- **T1**：maxHoldingBars 4 处消费点改动是最大接线风险——单一 helper + 4 处逐点断言测试兜底；回退=移除 helper 改回直读 config（cold_tp_widen 锚全程不破）。
- **T2**：rebalance 是新增交易行为面——T+1/费用/清仓三条边界各有专门测试；回退=开关缺省 false 即整体旁路，生产路径零接触；**规则本身经历史反事实验证选定但属单窗证据，脉拍样本外复核是硬门槛**（→弱不动作的 18 笔证据若在样本外翻转，回到台账重新提名）。
- **资源纪律**：脉拍多臂=多次 BacktestService dry-run，交易时段外执行；臂失败走既有 degraded 路径不阻断基线。

## 执行顺序

T1 → T2 → T3 → T4（T1/T2 独立可并行开发，但同一文件 execution.py——**串行执行**避免写冲突）；全程不碰 sentiment_2b/ladder 配置。

---

**状态头**：T1-T3 已执行完毕（2026-10-01）并经**第二轮独立评审（BLOCK→已修复）**——P0-1：per_band 出场表与 rebalance 完全同类的跨开关静默失效（exit_v1 臂 9 月从未行使、读数作废），已修自包含（_exit_coupling_overrides 从本开关 eodScores 严格前日自解入场带）+ standalone 回归锚；9 月 exit_v1 重跑探针验证：强带入场（600613）三参数齐盖章，当月真无行为差异（holdingBars 5<30、未达 TP）；P2 9 项全部处置（归因优先级声明/rebalanceFromBand 自算落盘/factor 按成交比例/skipped 原因码/eodScores 合并 DB 优先/T+1 判别力构造/计划文字回写/台账口径注记/死代码清理）。全量终态 **3011 passed / 0 failed**，前端 1130 passed + vue-tsc 0 错。其余记录：T1 per_band 出场表（cold_tp_widen 回归锚不破）；T2 phaseRebalance v1（自包含 + 触发矩阵）；T3 脉拍多臂 + 归因扩展 + 前端挑战者卡；9 月 rebal_v1 触发 1 次清仓（当月 −19.96% vs 基线 −18.03%，方向不利 n=1 如实入档）。T4 走廊持续：首点入台账（地图基线 §7），样本外累积至晋升门槛。**未提交，与 SP1 同批待用户 review。**
