# ThemeTrend 202610 终判批次方案（B-202610 ThemeTrend 分册，Wave 2）

- 日期：2026-09-27
- 状态：**已定稿**（D1-D3 三决策点用户当日裁决，见 §4.2 裁决记录）；前置代码层全部就绪（S3 硬层已参数化）
- 定位：**B-202610 总方案（`quant-board/docs/ranktrend-tier-backtest/ranktrend-202610-rerun-plan.md`）的分册**。两域共享批次日历、数据落地检查点、资源纪律、消费台账与产物格式；判定口径、候选集、窗口与落默认机制按域分册，不合并。
- 上游：`2026-09-26-themetrend-v12-upgrade-design.md`（§6.1 双轨）、`plans/task_plan_phase4.md`（接线与扫描设计）
- 纪律：`skills/ranktrend-signal-research/SKILL.md`（M3 窗口消费折扣、隔离 runner、dry-run、一次一候选）

## 1. 批次日历（两波合一）

| 波次 | 时间 | 内容 | 数据依赖 |
|---|---|---|---|
| **Wave 1（RankTrend）** | **2026-10-03** | B-202610 正式复跑（9 月全月，锚/判定卡/观察池裁决，见总方案） | 09-28/29/30 三交易日落库 |
| **共享检查点** | 2026-10-03（同日） | 两域数据落地核验（§2.1，国庆休市时段执行，资源友好） | 同上 |
| **Wave 2 初判（ThemeTrend）** | **约 2026-10-21** | P4-1 数据积累确认（10 月 ≥10 个交易日）→ 扫描先行 trial | 10-08 起开市满 10 交易日（仓库日历事实源：mootdx holiday_bridge 缓存 + TDX 在线日历双重确认 10-08 为 10 月首个交易日，10-01/02/05/06/07 休市；10 月共 17 个交易日） |
| **Wave 2 终判（ThemeTrend）** | **10 月底～11 月初** | P4-2～P4-5 全量扫描 + 三窗重跑 + verdict 存档 | 10 月全月落库 |

时序无冲突：B-202610 的 oos2u 止于 09-30，**不触碰 10 月帧**；本分册终判窗（09-28 起）在 B-202610 执行后仍严格未消费。

## 2. 与总方案的共享层

### 2.1 数据落地检查点（2026-10-03，两域共用一章）

1. 9 月全月帧落库核验（09-28/29/30 到帧，服务 Wave 1）；
2. **theme_daily_factors 调度器状态核对**：状态端点 `themeDailyFactors` 的 lastResult，auto catch-up 是否补齐 09-28/29/30；
3. **heatLevel 落库稳定性核对**（phase4 计划 §5.1-4）：9 月末三个交易日 + 10 月首批日（10-08）的 heatLevel 落库率（8 月曾为 0%；9 月恢复约 78% 为 daily 口径——按本档 >20% 缺失降级线，9 月口径本身已近触线，如实披露；half_hour 口径抽样 09-14~18 约 88%，两者口径不同不混用）；若 10 月仍 >20% 缺失，heatLevelStreak 的 Q5−Q1 复验降级为 OBSERVE；
4. 10 月首批日（10-08）落地后复核一次调度器与帧量，作 Wave 2 初判的启动门槛。

### 2.2 资源纪律（沿用总方案 §7.7）

多 trial 扫描一律隔离 runner（沿用 R3b 范式：自切片 frames + dry-run + 单进程）；禁止并行 ≥2 个回测进程；交易时段不排大批次；10 月假期为理想执行窗。

### 2.3 消费台账（首次跨域统一登记）

| 窗口 | 域内状态 | 登记 |
|---|---|---|
| 2026-07-06 ~ 08-31 | theme 已消费（Phase 1/2/3 + R1/R2 + 收敛批） | 折扣窗 tw1 |
| 2026-09-01 ~ 09-24 | theme 已消费（R3/R3b + Phase 1-3） | 折扣窗 tw2 |
| 2026-09-28 ~ 09-30 | theme 未消费（B-202610 属 RankTrend 域消费此三日，不触 theme 域判定） | 终判窗 T 的前段 |
| 2026-10-08 ~ 10-31 | 两域均未消费 | 终判窗 T 主段；**本批执行后登记为 theme 已消费**，RankTrend 后续批次引用须折扣 |
| decision/oos1/oos2/oos2u | RankTrend 域（见总方案 §2.1） | 不变 |

> 口径澄清（phase4 计划 §5.1-1 的落地规则）：**拥挤度分位对终判窗 T 无口径污染**——rolling 60 交易日自 10 月中旬回溯不早于 07 下旬，min_periods=10 下 10 月初读数仅用 09 月以来观测，全部处于 amountShare 可观测段（07-06 后）；tw1/tw2 复跑若引用 7 月上旬分位值，按 `amount_unobservable` 标记打折披露。无需截窗，无需新标记。

### 2.4 产物格式（对标 b-202610）

verdict 文档章节：判定卡汇总表 / 扫描 trial 明细 / 数据质量章（§2.1 产出）/ 已消费窗折扣披露章 / 一次一候选落默认记录。落 `docs/theme-module/`（题材域首份成册 verdict，对标 `exit-scan-batch*-verdict.md`）。

## 3. 窗口定义（本分册）

```text
tw1 : 2026-07-06 ~ 08-31   （已消费 → 全部读数带折扣标记）
tw2 : 2026-09-01 ~ 09-24   （已消费 → 折扣标记）
T   : 2026-09-28 ~ 10-31   （未消费终判窗；判定读数以 T 为准）
      前段 09-28~09-30（3 交易日，**已裁决纳入**）
      主段 10-08 起（≥10 交易日初判门槛，P4-1）
```

回测自包含性说明：theme 合成分原料为逐帧 sector rows 预计算值（momentumScore/heatScore 等），T 窗切片回放无 RankTrend 式 29 帧 warm-up 问题；多帧 persistenceScore 已弃用不影响；门控读逐帧 15:00 marketPhase，自包含。

## 4. 批次前裁决点与就绪度

### 4.1 就绪度清单（代码层）

| 项 | 状态 |
|---|---|
| 情绪门控 + 拥挤度分位门控机制（默认关，payload 可传） | ✅ Phase 4 接线层 |
| persistenceScoreWeight 全链（config + payload + 优化器 parameterGrid + typed flags） | ✅ 2026-09-27 Path B |
| 日频因子注入通道（replay_sequence daily_factors，双键 themeName 对齐 245/245） | ✅ 2026-09-27 |
| 优化器探测/装载（`_grid_requests_daily_factors`，一次装载全 trial 复用） | ✅ 2026-09-27 |
| 拥挤度分位跨 07-06 口径 | ✅ 已裁决（§2.3：终判窗天然无污染） |
| 数据积累 / 三窗边界 | ⏳ 按设计等 10 月（§1 日历） |

### 4.2 决策点裁决记录（2026-09-27 用户确认，方案定稿）

| # | 决策 | 裁决 |
|---|---|---|
| **D1** | 拥挤度分位"替换 vs 并列" | **并列门控扫描**（S2 = threshold × penalty）；替换口径作为新候选挂后续批——需新合成分形态与量纲语义，不与阈值扫描同批 |
| **D2** | 75 硬层 / 60 起扣接线缺口 | **拆两半**：①75 硬层已参数化（`ThemeTrendConfig.crowdedHardLayerThreshold` 默认 75.0 + payload 键 `crowdingHardLayerThreshold`，信号层+执行层共七处硬编码比较点单旋钮，含 leader/confluence 分支——code review I-3 补齐；逐位不变测试钉住）——S3 可扫；②**60 起扣移出本批**：属 momentum v2 惩罚项，v2 分数不在回测合成分内（诊断通道），扫它对 PnL 零效应，挂先验通道裁决后再议 |
| **D3** | 终判窗 T 前段 | **纳入 09-28~09-30**（theme 域严格未消费，+3 交易日样本，与 Wave 1 数据检查点同日核验） |

## 5. 扫描清单（P4-3，全部 dry-run 隔离 runner）

| # | 组 | 参数空间 | 通道 | 候选来源依据 |
|---|---|---|---|---|
| S1 | 情绪门控 | phases ∈ {cooling / cooling+ice / cooling+ice+chaos} × penalty ∈ {5,10,15,20} | payload runner（gating 参数走 payload 不走 ThemeTrendConfig） | Phase 1 方向性支持（cooling Q5−Q1 −0.118%/日、IC −0.049） |
| S2 | 拥挤度分位（并列门控） | threshold ∈ {80,90,95} × penalty ∈ {5,10,15}（**替换口径已裁决移出**，挂后续批，见 §4.2-D1） | payload runner | Phase 2 过验（边际 IC −0.063 持续负向） |
| S3 | 75 硬层重定 | threshold ∈ {35,45,55}（**已参数化** `crowdedHardLayerThreshold`，信号层+执行层单旋钮；**60 起扣已裁决移出**见 §4.2-D2） | payload runner（optimizer 只动信号层，对 PnL 无效应，不采用） | Phase 2（量纲差一个数量级、既有阈值零触发） |
| S4 | persistenceScoreWeight | **{0, 0.25, 0.5, 1.0}**（2026-09-27 量纲重推；日计数**正值段** p50=3/p75=7/max=15，>0 仅 8.4%） | **payload runner + 产出 score 外部 IC 面板**（code review I-5：optimizer 的 score_theme_trend 只读 factors 不读 signals.score，weight 变化对其零判别力，不采用；payload runner 侧 weight 亦不进执行层，判据 = T 窗信号 score 的五分位差/IC，非 PnL） | §5.1-2（候选原料 Path B 定版） |

扫描顺序即裁决顺序：S1 → S2 → S3 → S4，一次一候选，每组先跑 tw1/tw2 折扣窗定参数敏感性、再以 T 窗终判（M3）。

## 6. 复验清单（10 月批次顺带，不占扫描资源主线）

| 项 | 触发与动作 |
|---|---|
| hybrid 月度复验 | R3b 观察池候选（+4.15% 三变体最优），绑本批 runId，T 窗重跑对 R3 结论复核 |
| heatLevelStreak Q5−Q1 −0.323 负向复验 | T 窗复现 → 与 D2 夏普动量 / Phase 1 cooling 反转同批归档"退潮预警"语义（纯 IC 研究，吃已落库 daily factors，零新接线） |
| D3 / F1 复验 | 10 月样本扩容后重跑边际 IC（Phase 3 观察池） |
| v2Breadth 边际 −0.083 | 同面板顺带复测（收敛批观察项） |
| SG3 15:00 口径 / D2 反转语义 / 腾讯日 K 回溯 | **不进本批**（另批一次一变量，维持原登记） |

## 7. 判定与落默认纪律

1. 判定读数以 T 窗为准；tw1/tw2 只作敏感性与方向参考（M3 折扣章披露）；
2. 门控/权重候选的通过线：T 窗方向复现 + tier/成交不劣化（门控只降可信不打 tier 的红线不变）+ 样本量披露（T 前段 3 日 + 10 月约 16-17 交易日，须逐项披露有效样本）；
3. 落默认：一次一候选、每项独立 commit、payload/Config 默认值变更走用户决策、回退路径写明；**优化结果永不自动写回默认值**；
4. 全部参数裁决（含 D1/D2 遗留项）汇总进 verdict 文档"待裁决章"，不散落。

## 8. 产出物

| 产出物 | 位置 |
|---|---|
| 数据质量章（两域共享检查点产出） | `data/reports/b-202610/`（Wave 1 同目录，标注 theme 段） |
| 扫描 trial 明细（dry-run summary JSON） | `data/reports/b-202610/theme/` |
| **题材域首份 verdict** | `docs/theme-module/2026-10-themetrend-phase4-verdict.md`（命名随实际） |
| 消费台账更新 | 本文档 §2.3 + phase4 计划回写 |

## 9. 风险与诚实边界

1. **统计效力**：T 窗有效判定样本约 19-20 个交易日（含 09-28~30 前段），对四组扫描各为单一新 OOS 窗，C2 型"多窗同向"验证不可得——判定强度弱于 RankTrend 三窗体系，verdict 须如实标注"单终判窗"；
2. **弱市样本偏倚**：9-10 月若延续弱势，S1（cooling 门控）天然占优——判定卡须携带市场状态构成披露（market_phase × rotation_regime 分布）；
3. **扫描间相关性**：S1/S2/S3 同改 confidence 通道，存在交互；严格做法是全组合扫描（资源不允许），折中为"逐组单独最优 + 最优组合复核一次"，组合复核结果只披露不落默认；
4. **调度器单点**：theme_daily_factors 依赖生产后端 18:30 调度，停机日靠 auto catch-up 自愈——§2.1 检查点是唯一闸口，10 月内停机需人工触发补算。
