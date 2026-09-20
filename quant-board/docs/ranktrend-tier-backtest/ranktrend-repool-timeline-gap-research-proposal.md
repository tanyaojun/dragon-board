# 出池回池股票 timeline gap 容忍参数化研究立项

> 状态：已立项（2026-09-20 用户裁决，走 `skills/ranktrend-signal-research` 统一流程）
> 类别：Track B（序列连续性门控 / 评估口径）+ Track A（gap 阈值参数化）交叉
> 观察池登记：`config/ranktrend-observation-pool.yaml` → `P_repool_timeline_gap`（kind: proposal）
> 关联：全池状态结构口径（`docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md` §11）

## 1. 背景与用户场景

频繁出入热榜池的股票，回池后周期列长期显示「样本不足」，用户判定不合理（2026-09-20，以
002440 闰土股份为例：7 月多次入池、09-01 最后出现、09-20 回池，中断 19 天）。

实测证据（2026-09-20）：

- 002440 历史快照行：34 行，最后出现 2026-09-01，中断 19 天后回池；
- 带 `currentFrame` 的探针请求复现：`meta.sampleQuality.status=insufficient`（reasons/timelineValid 均为 None——非 timeline 断裂分支，而是序列不足分支）；
- 前端显示链：`DataTable.isLifecycleSampleInsufficient` 读 `meta.sampleQuality.status` 优先覆盖 stage 标签（2026-09-10 口径统一设计：数据质量声明优先于 stage 兜底，防同股两判）；
- 排序侧已按用户裁决归末组（ui.ts `b94e6f84`），观感问题已缓解，本课题解决**判定可用性**本身。

## 2. 问题定义

出池回池股票在序列重建期内 `meta.sampleQuality=insufficient` → 周期/趋势判定不可用。
判定本身是 golden 的诚实行为（fail-visible：拒绝用断裂历史伪装结论），**本课题不质疑判定诚实性**，
研究的问题是：**重建期长度是否可通过「容忍中断历史做降级判定」显著缩短，且不劣化交易层质量**。

## 3. 判定链盘点（A1 精确盘点已完成，2026-09-20）

| # | 判定点 | 位置 | 当前行为 |
| --- | --- | --- | --- |
| 1 | 趋势/动量轨道 sample_status 三档 | `engine/runtime.py:1235-1238` | `len(percentiles) >= momentum_min_samples` → ok；`>= 5` → degraded；否则 insufficient |
| 2 | 共振轨道 timeline 门 | `engine/runtime.py:615-619` | `timelineValid is False` → 共振 insufficient（**实测确认引擎无任何写入 timelineValid=False 的代码点**——该字段仅透传，恒 True） |
| 3 | 新进热榜单点分支 | `api/ranktrend_routes.py:230-240` | 历史无记录 → 单点序列 → insufficient |
| 4 | 双窗结构 | `api/ranktrend_routes.py:77-87` | 序列窗 280 帧 vs 分析帧窗 30 帧；`series_by_code` 只用于新股判定与 current 帧注入，**不进引擎** |

### A1 关键结论（修正立项预设）

1. **percentiles 的唯一来源 = replay 帧窗内实际出现**（`runtime.py:_replay_stock`，`window_size=50`，逐帧查该股出现才 append）。不存在显式 gap/timeline 断裂判定——**insufficient 是「帧窗（50）内实际出现次数 <5」的隐式结果**。出池 >50 帧（约 3.3 个交易日）→ 帧窗内零出现 → percentiles 仅当前帧 1 点 → insufficient。
2. **`momentum_min_samples` = max(2, max(momentumPeriods)+1) = 22**（momentumPeriods 默认 [3,5,8,13,21]）。三档门槛 22/5。
3. **重建期真实长度 ≈ 5 个出现帧（约 2.5 个交易日）**：回池股攒够 5 点即升 degraded——`isLifecycleSampleInsufficient` 只查 insufficient，**degraded 股票显示真实 stage**。因此「样本不足」仅覆盖出池 >3.3 交易日且回池后前 5 帧内的股票。
4. **补桥（用中断前历史预填序列）升格为结构变更**：序列消费方（ATR gap 重置、共振 path window、momentum 多周期）全部假设「序列点 = 真实出现帧」——伪造连续帧索引的桥点会系统性扭曲这些消费方；携带真实 gap 的桥点需要 280 帧坐标系传入引擎并让帧窗裁剪理解桥点，接口与语义双重变更。实现路线（三落点）需批次评审裁决，不做单点实现。

## 4. 研究假设（先立标准后跑数据）

- **H1（主假设）**：对中断回池股票，用「中断前历史 + 当前点」做**降级判定**（confidence 打折 / 档位上限 cap / 单独 tier 前缀），交易层质量不劣于「insufficient 不可用」，且显著缩短重建期。
- **H2（参数假设）**：timeline gap 容忍阈值（单位与落点待 A1 确认：帧 gap 或日 gap）参数化后存在非端点档位，在判定卡上不劣于现状。
- **H0（反面假设，必须正面检验）**：中断前历史与当前市场结构脱节（题材轮动、排名结构重排），用旧历史判定 = 用 19 天前的点火伪装今天的点火——若 H0 成立，维持现状（insufficient 是正确行为），转**展示语义**方案（中性化显示 / 重建进度）。

## 5. 扫描设计（A2，按 A1 修正后的参数空间）

参数空间按 A1 结论重定义（原「gap 阈值」参数不存在——判定是隐式的出现次数三档）：

- **参数 β（三档门槛，首选）**：degraded 门槛 5 → 5 档扫描（如 3/4/5/7/10）——回池股更早进入 degraded（有判定）；insufficient 门槛 22 亦为候选参数（需评估 momentum 多周期在高噪声短序列上的档位质量）；
- **参数 α（分析帧窗 window_size，次选）**：50 → 5 档（50/80/120/200/280）——帧窗加长让出池更久的股票保留残段序列；代价：每帧序列更长的跨中断连接（TR 膨胀防护已有 gap 重置，需验证有效性）；
- **补桥方案（结构变更）**：三落点选项（api 层序列注入 / replay 预填 / sample_status 计数放宽）的侵入度与序列消费方适配矩阵，作为设计决策点进批次评审，不在本研究内单点实现；
- 评估口径：`tier_forward_returns`（h1/h8）→ synergy saEx + lifecycle 维 saEx；**信号覆盖面变化（insufficient/degraded → 判定）是本课题特有的第一观察项**——新增判定样本的分布与质量单独出报告；
- 三层判定语义适用：本课题候选**天然涉及 saEx 盲区**（insufficient 行不参与档位统计，放开后进入统计的变化不是阈值迁移而是样本集扩张）→ 直接按盲区候选处理，终判必跑 Track 1（wrxpf + 30 笔门槛）。

## 6. 窗口与代际纪律

- 三窗 decision/oos1/oos2 + 8 月 FINAL 冻结；扫描前 `assert_not_frozen`；
- 证据代际绑定当前默认栈（Jump 修复后代际，见 `config/ranktrend-anchors.json`）；B-202610 批次重判后更新；
- 本课题排期：进批次待立项评估清单（B-202610 或下一批），不单点开批。

## 7. 展示侧联动（算法口径与展示口径分离）

- 参数化落地前，展示维持 2026-09-20 口径：样本不足排序归末组、标签显示「样本不足」；
- 若 H1/H2 成立落默认，展示层同步评估「样本不足 → 重建期降级判定」的显示语义（`isLifecycleSampleInsufficient` 读点不变，status 语义由引擎侧演进）；
- 若 H0 成立维持现状，展示层可选中性化（「样本不足」→ 中性「--」+tooltip），与算法课题解耦单独决策。

## 8. 交付物清单（执行时）

1. A1 精确盘点补全（本文件 §3 两个待确认项 + 参数现状表）；
2. 参数化 commit（默认值=原值 + 默认值断言测试 + 参数生效测试，golden alignment 全绿）；
3. 5 档扫描报告（`data/reports/<batch-id>/`）+ 长测文档阶段 N；
4. Track 2 判定卡 + 盲区检查 + Track 1 终判记录；
5. 六类判定结论 + L1 台账同步 + 观察池状态更新。
