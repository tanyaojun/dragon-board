---
name: ranktrend-signal-research
description: RankTrend 信号参数长测与因子算法研发统一流程（合并原 ranktrend-tier-longterm-test 与 four-dim-algorithm-research，2026-09-16）——Track A 参数线（盘点参数化 → 5 档扫描 → 三层判定语义）/ Track B 因子算法线（设计 → 区分度 → 接线 → 边际贡献）/ 月度复验批次模式（窗口推进、已落默认栈回退复核、观察池裁决）。统一收口：Track 2 判定卡 C1-C5 → saEx 盲区检查 → Track 1 交易复核终判 → 六类判定 → 一次一候选落默认。含 harness 工程范式 8 项、锚代际纪律、窗口消费折扣（M3）。实践记录见 quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md（阶段 0-26）；批次化复跑范例见同目录 ranktrend-202610-rerun-plan.md。
---

# RankTrend 信号研究统一流程（参数长测 × 因子算法 × 月度复验）

## Overview

对 RankTrend 信号的一切实证研究走统一闭环：**共享前置纪律 → 双轨执行（Track A 参数线 / Track B 因子算法线）→ 统一收口（Track 2 判定卡 → saEx 盲区检查 → Track 1 交易复核终判 → 六类判定 → 一次一候选落默认）**。

两轨的分界（沿用原两 skill 语义）：

- **Track A 参数线**（原 `ranktrend-tier-longterm-test`）：已有维度的参数怎么调——阈值、权重数值、剂量；
- **Track B 因子算法线**（原 `four-dim-algorithm-research`）：加不加因子/开不开投票/怎么门控——投票维度、观察因子、门控规则、评估口径。

实践证据：两轨共享约 70% 纪律，且边界天然渗透（阶段 17 MA 因子算法线立项、判定卡收口；阶段 23/24 参数扫描实为门控结构论证）——故合并为单 skill，收口纪律只有一份。

**事实源约定**：长测结论与锚读数以 `ranktrend-longterm-backtest-plan.md` 文档记录为唯一事实源；`data/reports/` 本地报告是易失运行产物，不作为分析依据与对照物。

## 触发条件

- **Track A**：既有维度参数优化（"调参/搜索/长测"）、新维度参数首次盘点；
- **Track B**：新增/修改 synergy 投票维度、观察因子（priceMomentum/priceRankDivergence/amountRatio 类）、投票权重结构、regime 门控（regime 禁放、Jump 确认、weak 放开）、评估口径争议；
- **月度复验批次**：月度数据全量落库后的定期复跑——已落默认栈复核、观察池裁决、复核触发统一收批（范例：`ranktrend-202610-rerun-plan.md`）。

## 第 0 步 共享前置纪律（两轨共用，每次必须确认）

1. **golden 锁基线**：改动前先跑 `pytest tests/test_ranktrend_golden_alignment.py`；参数化默认值 = 原硬编码（golden 不漂移）是第一步验收。
2. **数据窗口纪律**：固定三窗 decision / oos1 / oos2 + 8 月 FINAL 冻结（08-01~08-14）；任何参数/因子决策禁止引用 8 月数据，扫描前 `assert_not_frozen(frames, purpose="scan")`（resume 路径同样执行）；8 月只允许 `purpose="report"` 最终呈现。
3. **窗口消费折扣（M3）**：harness 扫过的窗口即"已消费"，其结论标注折扣；最终裁决窗必须用未消费帧。窗口定义与消费状态随批次方案推进（范例：B-202610 的 oos2 全月 + oos2u 未消费子窗双披露，判定读数以 oos2u 为准）。
4. **极端行情月感知**（第一轮最大教训）：7 月股灾月污染 validation 导致候选被错误降级——样本外异常先问市场状态，单独跑干净窗口交叉验证，不直接判参数无效。
5. **参数化不漂移**：硬编码阈值先参数化进 `RankTrendConfig`（默认值=原值）；list 字段必须同步 `search_space._STRATEGY_LIST_KEYS` 白名单（否则搜索映射失败/误导到 trade_config）；新增测试 = 默认值断言 + 参数生效测试。
6. **fail-visible**：数据异常显式处理（0/None/NaN/样本不足 → None/unknown），不吞不伪造；数据质量缺口打标记不阻断（采集与分析都不做质量阻断）。
7. **机理优先**：热榜池内相对强弱口径（排名/横截面）有效，绝对口径（全市场/价格/金额）冗余或噪声（G1 价格动量 −32%、dv 投票 −25% 实证）——新因子先问"是否与排名信息冗余"。
8. **优化结果永不自动写回默认值**；落默认只能由用户决策触发（一次一候选）。

## Track A 参数长测线（4 步）

### A1 参数盘点
沿调用链找出该维度**全部参数**：已 config 字段 + 硬编码字面量；按第 0 步纪律 5 参数化。

### A2 逐参数 5 档扫描
- 每参数分别 5 档候选（含当前默认），**单变量扫描**——不是打包 3 组配置（用户明确偏好）；list 参数整体缩放（×0.8~1.2）；
- 评估口径：`tier_forward_returns`（h1，可扩展 h8）→ synergy saEx（主）+ 关注维 saEx；
- **三层判定语义**（阶段 26 固化）：真惰性（各档完全一致=冗余，仅平移 score/confidence）/ **saEx 盲区**（只迁移负票/中性档的阈值线 saEx 结构性不可见——盲区候选直接转 Track 1 终判，阶段 24 e1a 首例：saEx 三窗全正但交易层 −32%）/ saEx 活跃（单调上升且非单点尖峰 = 真实可调参数）；
- 判定看**单调性/峰值稳定性**，非单点；先列假设与判定标准再跑数据，不预设结论（方向 A/B/C 三连否定教训）。

### A3 组合验证
显著参数（通常 1-2 个）+ 档位层有效参数组合（如 fund10+over2、jump25+fresh06）；组合不成立（样本外恶化放大）也要记录——证伪证据。

### A4 批次对照
扫描结论进当前批次方案统一裁决（不再单点开批），对照基线显式声明（已落默认项会改变 baseline，跨批比较必须声明口径）。

## Track B 因子算法线（5 步）

### B1 因子设计
参数化（同 A1 纪律）；字段语义命名（如 `priceRankChangeMin`）；数据异常 fail-visible。

### B2 区分度验证
- `tier_forward_returns(dimension=…)` 分档 exAcc / excessMeanFutureReturn；A 档样本 n<500 结论降级观察项（双强共振 n=264 先例）；
- **0.05 单维验收线只管档位语义**（双轨制边界，阶段 19.3）：单维区分度 ≠ 组合晋升证据；
- 投票维度先验证独立区分度，再验证边际贡献（加投票 vs 不加）。

### B3 投票/门控接线
新维度进 `compute_synergy_state` 档位；`tier_monotonicity.py DIMENSION_PATHS` 登记（否则分档统计不可见）；门控改 `compose_analysis_candidate_tier`（ban 分支）；保留旧规则回退开关；新字段自动进信号缓存键。

### B4 边际贡献论证
留一/半权/剂量曲线（阶段 17 MA 因子范式）；多档/多态实证看单调性，非单点；正贡献 → 候选默认值（等用户决策）；负贡献/冗余 → `vote=0` 关闭观察（机制保留，记录实证），不删实现。

### B5 golden 回归 + 全量测试
`test_ranktrend_golden_alignment` + `test_market_regime` + `test_ranktrend_engine` + 相关新测试全绿；行为变更必须 golden 显式断言。

## 统一收口（两轨共用，7 步）

### 1. Track 2 判定卡（信号层）
C1 决策窗 saEx 相对 ≥+3%；C2 至少一个 OOS 窗同向为正；C3 passHard 不降（**一票否决**）；C4 regime 四桶降幅 ≤0.01；C5 翻转率升幅 ≤0.01。**C1∧C2∧C3 = PASS_CANDIDATE**。

### 2. saEx 盲区检查
候选先过三层判定语义（A2）；涉及负票/中性档迁移的阈值线、regime 状态内指标、决策反转类信号默认按盲区处理，直接转 Track 1 终判。

### 3. Track 1 交易复核（交易层终判）
wrxpf = winRate×profitFactor 主窗复核 + 30 笔样本门槛 + 入场集合漂移卡；PASS_CANDIDATE 与盲区候选必跑；Track 1 否决优先于 Track 2 通过（e1a 原则）。

### 4. 六类判定
| 类别 | 处置 |
|---|---|
| PASS_CANDIDATE | 进用户决策队列 |
| OBSERVE | 观察池登记（绑定代际、触发条件、对照基线） |
| REJECT | 记录结论，不采纳 |
| 证伪 | 记录（含翻案时旧结论标注作废，如"§9.4 作废以 §9.5 为准"） |
| 冗余 | 记录，可移除调参入口 |
| 缺复核 | 扩数据/条件触发后重判，进观察池 |

### 5. 落默认流程（仅用户决策后）
一次一候选（独立 commit，避免交互污染归因）→ TDD → 端到端锚逐位复现 → `strategy_version`/`ranktrend_version` 提升 → TS 契约/文档同批同步 → 回退路径写明 → 第一个上线日人工核对实际入库数据。

### 6. 已落默认后复核 = 回退 trial
已入默认栈的项，隔离其持续贡献用"**单项还原**"对照（patch = 还原旧值），不是晋升期的 baseline vs 候选（阶段 27 批次 R1-R4 范式）。

### 7. 文档 + 台账 + 观察池
- 结论（含证伪/否定）写入长测文档对应阶段；L1 定值档案 `ranktrend-l1-param-ledger.md` 同步（commit/数据窗口/样本外状态）；涉 8 月污染历史如实更新 `overfitting-audit.md`；
- 观察池登记：候选/状态/证据指针/触发条件/代际绑定/对照基线（结构化文件，不散落文档小节）；
- 前端链路同步（若涉展示）：展示口径与算法口径分离要文档化；
- 提交纪律：conventional commits，中文描述含实证依据，一组逻辑一个 commit。

## 月度复验批次模式

数据逐月累积后，把散落的复核触发统一收批，替代"边开发边回测"：

1. **批次方案先行**：窗口定义（含 oos2/oos2u 双披露口径）、已落默认栈回退 trial 清单、观察池裁决清单、待立项评估清单——先成文再开跑（范例：`ranktrend-202610-rerun-plan.md`）；
2. **批次顺序**：数据质量只读盘点 → 新代际锚建立（baseline 三窗全量）→ 已落默认栈回退复核 → 观察池裁决 → 待立项评估 → 单一批次报告收口；
3. **锚代际纪律**：代际变更（如 Jump 门修复）使历史 trial 全部过期——新代际第一个动作是重建三窗锚；观察池候选证据必须绑定代际，跨代际比较显式声明；
4. **产出三件**：批次判定报告（`data/reports/<batch-id>/`）+ 长测文档阶段 N + 观察池/锚注册表/L1 同步。

## harness 工程范式 8 项（新 harness 必查清单）

1. WINDOWS import 零日期字面量（窗口常量单点维护）；
2. `_assert_overrides_applied` 逐键断言（防 override 静默失效产出假结论）；
3. `assert_not_frozen` 无条件执行（含 resume 路径）；
4. trial 级缓存 resume（断点续跑）；
5. `_save` 剥离 `__frames__`（防 GB 级报告文件）；
6. 锚 trial 级即时 raise（baseline 失配立刻失败，不跑完全批再报）；
7. `--extra-trial/--extra-arm` 扩展位（组合/Track 1 对照不另起脚本）；
8. M2 样本门槛（n<500 结论降级观察，披露样本量）。

## 关键文件索引

- 引擎/config：`quant-board/backend/analysis/ranktrend/engine.py`（RankTrendConfig + compose）
- 投票/档位：`quant-board/backend/analysis/ranktrend/volume_price.py`（compute_synergy_state）
- 分档统计：`quant-board/backend/analysis/ranktrend/tier_monotonicity.py`（DIMENSION_PATHS）
- 冻结守卫：`quant-board/backend/optimization/data_windows.py`（assert_not_frozen）
- 测试基准：`quant-board/tests/test_ranktrend_golden_alignment.py`（golden 不漂移）
- 事实源/档案：`quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`（阶段 0-26 结论与锚读数）、`ranktrend-l1-param-ledger.md`、`overfitting-audit.md`
- 批次范例：`quant-board/docs/ranktrend-tier-backtest/ranktrend-202610-rerun-plan.md`（B-202610）
