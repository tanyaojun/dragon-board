# 引擎性能优化立项 Handoff（回测搜索提速，2026-09-23）

> 本文件是**新对话立项交接**用。卖点规则化研究主线见
> `exit-rules-scan-plan.md`（本文件只管引擎性能优化这一层）。
>
> **✅ 已执行（2026-09-23 晚）**：层 1（lifecycle/rank_shock 有界窗口 +
> evaluator._group_stats 单遍分组，逐位一致三重复现验证）与层 2（dryRun 开关 +
> runner --dry-run）均已落地；全窗 dry-run 单 trial 520s（基线 ~20 分钟）。
> 结果与证据详见 `exit-rules-scan-plan.md` "2026-09-23 晚 引擎提速执行" 小节。
> **✅ 验收复盘收口（2026-09-24 凌晨）**：硬门槛 4 条全部满足——护栏先落地 ✓ /
> 全窗逐位一致（dry-run 双轮 + 持久化 run bt_91a356067c9e4704（839s）经原版逐位
> 脚本与锚 run 一致）✓ / pnpm 合同 ✓ / 全量 pytest 2572 passed 零新失败 ✓。
> 数值目标如实披露：6-trial 批次实测 9.7 分钟（<15 分钟达成）、dry-run 单 trial
> 分钟级（hit ≈1 分钟）达成；**全窗单 trial <5 分钟子目标未达**（最优实测
> dry-run ≈5.3-6.3 分钟，受逐位一致约束下 replay 固有成本所限）。详见
> `exit-rules-scan-plan.md` "2026-09-24 凌晨 verification-before-completion 复盘收口"。

## 必读（新会话第一步）

1. `D:\dragon-board\AGENTS.md`、`D:\dragon-board\SKILLS.md`（项目强制）。
2. `quant-board/docs/ranktrend-tier-backtest/exit-rules-scan-plan.md` 的
   "搜索引擎提速：信号缓存批量模式（cProfile 驱动）"章节（本任务的 profile 数据与已完成部分）。
3. `skills/ranktrend-signal-research/SKILL.md`（golden 纪律：参数化不漂移、逐位复现）。

## 背景

卖点扫描单 trial（全窗 1011 帧 half_hour，dragonboard_live 2026-03-27~09-21）约 20 分钟，
6 trial 批次约 2 小时；用户期望进阶到分钟级。本会话已完成的提速（不重复做）：

- **本地 frames**：`exit-frames-export.py` 导出 `quant-board/data/exit-scan-frames-*.json.gz`
  （1011 帧 / 138.7MB），runner `--local-frames` 读本地——零 MongoDB 大读。
  LOCAL-FRAMES PARITY 已验证（本地 == Mongo 直读逐位一致）。加载 138MB gzip json 约 60s。
- **信号缓存批量模式**：runner `--batch`——同进程串行多 trial + monkeypatch
  `RankTrendPythonEngine.replay` 进程内缓存（键=RankTrendConfig repr）。小窗口验证
  PASS（缓存命中路径与独立进程结果逐位一致，正确性无污染）。
  **但全窗实测反例（2026-09-23 晚）**：批量 5 trial 中 trial1 20 分钟、trial2
  （缓存命中）反而 31 分钟——**cProfile 小窗口的"信号占 60-75%"不能外推全窗**；
  全窗下 efficacy 计算 / 五表落库 / result 大 JSON 序列化的占比显著（未被小窗口
  profile 的过滤行覆盖），且 5GB 进程在 ~2.8GB 空闲内存下疑似换页放大。
  层 2 的 dry-run（跳过落库与序列化）因此从"锦上添花"升级为**必做项**——
  建议先做层 2（改动小、收益直接），再做层 1（算法优化）。
- **cProfile 实测**（小窗口，工具 `exit-profile-trial.py`）：信号计算占单 trial
  **60-75%**——`engine/runtime.py:1104 _build_signal` 25998 次调用（cumtime ~74s），
  `trend/lifecycle.py:9 analyze_cycle` 24s，`lifecycle.py:42 cycle_metrics`
  **764768 次调用**（约每 _build_signal 29 次，即每票每帧重复重算周期指标）。
  撮合（TradeSimulator）与 Mongo 拉取都不是大头。

## 立项目标（两层，按序）

### 层 1：`_build_signal` / lifecycle 算法级优化（大头上限最高）

- 现象：`cycle_metrics` 76 万次调用 = 每票每帧全量重算 lifecycle 周期指标；
  同票相邻帧的序列前缀高度重叠，存在明显的**缓存/增量计算**机会
  （例如按 (code, 序列长度/末帧) 记忆化，或逐票预计算一次周期指标表）。
- 位置：`backend/analysis/ranktrend/engine/runtime.py`（`_build_signal`）、
  `backend/analysis/ranktrend/trend/lifecycle.py`（`analyze_cycle`/`cycle_metrics`）。
- **硬门槛（不可绕过）**：`backend/analysis/ranktrend/engine.py` 是 RankTrend golden
  **生产事实标准**（AGENTS.md §4.2），任何优化必须输出逐位一致：
  1. **先建护栏再动代码**：固化代表性帧集（覆盖多 stage/regime/insufficient/缺字段
     路径）的 replay 输出快照（全字段），优化前后逐位比对；现有
     `tests/test_ranktrend_golden_alignment.py` 是起点但维度不足，需扩充。
  2. 优化完成后，全窗同 payload 与优化前 run 用
     `exit-default-replication-verify.py` 逐位比对（trades + equity）。
  3. `pnpm test:ranktrend` + `pnpm typecheck:ranktrend`（TS 消费合同不回归）。
  4. 全量 pytest 无新失败（基线：archive_research ×2 既有环境失败）。
- 默认行为不变：任何缓存/加速开关不改变无配置路径的输出。

### 层 2：扫描专用 dry-run 模式（跳过落库）

- 现状：`run_ranktrend` 尾部固定做 `save_backtest_run/trades/equity/signals/quality`
  五表写入 + `dumps_json_field(result)` 大 JSON gzip 序列化——扫描 trial 不需要持久层。
- 设计：payload 开关（如 `dry_run: true`，**默认 false 不改现有 API 合同**）→
  跳过 save_* 与 result_json 序列化，`_summary_response` 直接返回（含 trades 数组
  供归因——扫描分析脚本需从返回体取 trades，而不是读 Mongo）。
- 注意：dry-run 只开放给 harness/optimization 链；正式回测不受影响。

## 现有基建（直接复用，勿重造）

| 工具 | 路径（quant-board/docs/ranktrend-tier-backtest/ 下） |
| --- | --- |
| 隔离 runner（单 trial / `--batch` 批量 + 信号缓存） | `exit-scan-trial-runner.py` |
| frames 本地导出 | `exit-frames-export.py` |
| 逐位验证（两 run 的 trades+equity） | `exit-default-replication-verify.py` |
| cProfile 工具 | `exit-profile-trial.py` |
| 本地 frames 数据 | `quant-board/data/exit-scan-frames-dragonboard_live-half_hour-20260327-20260921.json.gz` |

## 基线与验收

- **耗时基线**：全窗单 trial ~20 分钟（信号 ~12-15 + 撮合落库 ~5-8）；小窗口
  （09-01~09-21）trial ~2.5 分钟（含加载 60s）；信号缓存命中后 trial 边际 ~5-7 分钟。
- **验收**：
  1. golden 护栏先落地并逐位通过（先于任何引擎代码改动）；
  2. 优化后全窗同 payload 逐位一致（护栏 + 复现双验证）；
  3. 提速实测披露：目标全窗 trial < 5 分钟；层 1+2 组合后扫描批次（6 trial）
     < 15 分钟、dry-run 单 trial 分钟级；
  4. 全量 pytest 无新失败 + `test_ranktrend_golden_alignment` 扩充用例全绿。
- **纪律**：优化结果不改变任何默认参数与业务口径；memory
  `exit-rules-scan-progress` / `optimization-scan-memory-explosion-incident` 同步更新。

## 环境坑（实测，Windows + Git Bash）

- **内存**：全窗回测进程峰值 4.4GB（本地 frames）~8.3GB（含 result 大对象），系统
  15GB——**禁止并行 ≥2 个回测进程**（曾发生 8.4GB RSS 全系统换页冻结事故，
  见 memory `optimization-scan-memory-explosion-incident`）。
- **交易时段**（9:30-11:30 / 13:00-15:00）不排大批次、不重启 8000（行情链承载中）。
- 多 trial 扫描一律走隔离 runner `--batch`；禁止经 8000 API 连续跑批。
- 8000 由用户看门狗守护：wrapper 报 failed 不代表进程死，以 `netstat` 为准。
- `/tmp` 不可用（临时文件放仓库内用完删）；`rg` 输出在 Git Bash 有转义 bug；
  MongoDB 服务会停（管理员 `net start MongoDB`）。
- 后台批量 bash 完成哨兵：轮询 runids.json 存在性即可。
