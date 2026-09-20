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

## 3. 判定链盘点（A1 初盘点，两项待精确确认）

| # | 判定点 | 位置 | 当前行为 |
| --- | --- | --- | --- |
| 1 | 趋势/动量轨道 sample_status 三档 | `engine/runtime.py:1235-1238` | `len(percentiles) >= momentum_min_samples` → ok；`>= 5` → degraded；否则 insufficient |
| 2 | 共振轨道 timeline 门 | `engine/runtime.py:615-619` | `timelineValid is False` → 共振 insufficient |
| 3 | 新进热榜单点分支 | `api/ranktrend_routes.py:230-240` | 历史无记录 → 单点序列 → insufficient（fail-visible 注释） |
| 4 | 双窗结构 | `api/ranktrend_routes.py:77-87` | 序列窗 280 帧（全量）vs 分析帧窗 `ANALYZE_MAX_TRACK_WINDOW=30`；序列构建在截断**之前**（280 帧历史进入 series） |

待 A1 精确确认：

- replay 中 `percentiles` 的实际来源（`series_by_code` 复制尾直接消费，还是逐帧累积）——决定 gap 参数化的落点是「序列构建层」还是「轨道判定层」；
- 周期轨道的序列长度要求（15 点）与 insufficient 的传导路径（`cycle.stage` 在样本不足时的兜底行为）；
- `momentum_min_samples` 当前默认值与 config 字段名。

## 4. 研究假设（先立标准后跑数据）

- **H1（主假设）**：对中断回池股票，用「中断前历史 + 当前点」做**降级判定**（confidence 打折 / 档位上限 cap / 单独 tier 前缀），交易层质量不劣于「insufficient 不可用」，且显著缩短重建期。
- **H2（参数假设）**：timeline gap 容忍阈值（单位与落点待 A1 确认：帧 gap 或日 gap）参数化后存在非端点档位，在判定卡上不劣于现状。
- **H0（反面假设，必须正面检验）**：中断前历史与当前市场结构脱节（题材轮动、排名结构重排），用旧历史判定 = 用 19 天前的点火伪装今天的点火——若 H0 成立，维持现状（insufficient 是正确行为），转**展示语义**方案（中性化显示 / 重建进度）。

## 5. 扫描设计（A2，A1 确认落点后细化）

- gap 容忍阈值 5 档单变量扫描（含现状 = 0 容忍为对照档），每档独立 commit-able 参数（默认值=原值，golden 不漂移）；
- 评估口径：`tier_forward_returns`（h1/h8）→ synergy saEx + lifecycle 维 saEx；**信号覆盖面变化（insufficient → 判定）是本课题特有的第一观察项**——新增判定样本的分布与质量单独出报告；
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
