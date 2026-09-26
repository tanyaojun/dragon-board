# Phase R3b 实施计划：SG1 收盘槽序列口径修正 + 三变体复跑对照

- 日期：2026-09-26
- 背景：R3 核心结论"主线不明环境下轮动补涨占优不成立"（chase -8.02% vs 基线 +1.71%）建立在 SG1 结构性 0 触发的缺陷上——chase 实际只由 SG2/SG3 驱动。本批修正 SG1 序列源后复跑三变体，检验结论是否站得住。
- 纪律：TDD；一次一变量（只动 SG1 序列源，SG2/SG3/tier 决策/进场规则/默认参数全不动）；fail-visible；复跑在非交易时段（周六）。

## 接口事实（2026-09-26 生产库实测，勿凭记忆修改）

1. **SG1 失败根因**：`run_theme_trend` 装载 frames 无日期过滤——真实回测日历 = 库内全部 half_hour 帧（**2026-04-15 ~ 09-24，107 个 15:00 帧日**，5-6 月有帧但题材行空洞）；而 daily 题材行 7 月仅 15 天（3,878 行，4 月仅 70 行）→ `sg1_complete` 要求全帧日完整 → 248 题材全败、SG1 全 None。
2. **15:00 槽 hot_theme 行**：**58 天 change 全覆盖**（4-15..9-24；4 月 4 天每天约 10 题材、5-6 月零覆盖、7-9 月约 54 天连续）；mainNetInflow 有值 9,577 行（SG3 的 15:00 口径是后续可选项，本批不动）。
3. **load_frame_bundles(projection="full") 的 entities = 库内原始 sector rows dict（含 change）**——SG1 序列可从 frames 直接构建，零额外查询。
4. **题材解锁测量**：248 题材有 15:00 change 观测；严格出勤（span 内无缺勤）**227 题材**；事件驱动分段 248/248（238 单段 + 10 双段）。选严格出勤语义（贴近原 sg1_complete 设计，不压缩缺失日）。
5. **测试夹具兼容**：make_theme_sg_bundle 的 sectors 无 change 字段 → SG1 序列不可构建 → 全 None（与现状一致），既有 3 个 API 用例预期不变。

## 语义定版（SG1 收盘槽序列，R3b）

1. 源：frames 15:00 帧的题材 entities change（黑名单过滤 rotation_main_line，与 SG2 同款循环收集）。
2. SG1 日历 = 有 ≥1 个题材 15:00 change 的交易日（实测 58 天）。
3. 每题材 series = [first_obs, last_obs] span 内的全部 SG1 日历日，**要求全出勤**（缺勤 → 整题材 insufficient，计入 sg1_insufficient_count，SG1 全 None）。
4. **截断规则**：series 内相邻日历日自然日间隔 >7 天（4-5 月空洞类）→ series 截断为最后一个断点之后；截断后 <2 天 → insufficient。
5. 基准 = SG1 日历日全题材 15:00 change 等权均值，与题材 series 同窗对齐（两端虚拟指数同基起步）。
6. 输出合同不变：{date: {sg1: bool|None}}——None=不可判定（题材未观测日 / insufficient 题材）；不伪造 False。

## 非目标

- SG3 口径切换（15:00 mainNetInflow 有 7 月下旬缺口修复潜力，另批一次一变量）；
- 既有三策略、chase/hybrid tier 决策、进场规则、默认参数零改动；
- 不做参数扫描；不动 SG2。

## Task 1：SG1 序列源切换（TDD）

**文件**：`backend/services/backtest_service.py`（_theme_sg_inputs 内部）；测试 `quant-board/tests/test_theme_backtest.py`（追加直测用例）。

- 新增直测（合成 frames 双题材 change 序列，svc = BacktestService(None)，SQLite 环境 daily 查询返回空 → SG3 全 None 不干扰）：
  ①lagging→improving 迁移触发（A=[-10,-2,+3] vs B=[0,0,0]）；②无 change 的 entities（现夹具形态）→ SG1 全 None；③span 内缺勤 → 整题材 insufficient + 计数 flag；④>7 天空洞截断后重算（断点后首日 None）；⑤单观测题材 insufficient。
- 既有 3 个 API 用例（chase/hybrid/baseline）零改动回归。
- **验收**：pytest tests/ -q -k "theme" 全绿。

## Task 2：三变体复跑对照（真实数据）

- `diagnose_theme_r3_variants.py` 原样复跑（--seed 20260430 同 R3 基线）；产物 `data/reports/theme-r3-variants-r3b.json`（--out 参数）。
- 对照基线（R3 findings）：chase -8.02%/PF 0.72、hybrid +3.32%/PF 1.16、基线 +1.71%；SG 触发分布对照（SG1 从 0 触发 → 实测天数）。
- 核对点：SG1 触发日数与高频题材是否合理；hybrid 门控分布是否漂移；内存纪律（串行+gc，照旧）。

## Task 3：findings + 文档回写 + 记忆

1. `docs/theme-module/2026-09-26-phase-r3b-findings.md`：SG1 修正后三变体对照结论（核心问题：chase 跑输是否因信号集残缺）、SG1 触发分布、与 R3 基线逐项对照、样本量声明；
2. 设计文档 §10 回写；更新持久记忆 `themetrend-upgrade-plan.md`；
3. 提交分组：Task 1 代码+测试 / Task 2 报告 JSON 不提交（gitignore）复跑结论进 findings / Task 3 文档，各自独立 commit。

## 风险与回退

- SG1 解锁后 chase 交易频次上升 → 结果波动属预期，逐项与基线对照如实报告；
- 严格出勤仍排除 21 题材（insufficient 计数可见）；
- 回退 = revert Task 1 提交（_theme_sg_inputs 单方法内改动，既有三策略路径零触碰）。
