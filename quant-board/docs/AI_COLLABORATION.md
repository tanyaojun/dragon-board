# AI 协作规范

本文是 QuantBoard 项目的固定协作合同。后续 AI 助手进入项目时，必须先读本文件和 [README.md](README.md)，再根据任务读取相关专题文档。

## 当前首期方案

- 项目目标：把 dragon-board 的 `rankTrend` TypeScript 分析链落地为 Python 后端可回测、可优化、可展示的 QuantBoard。
- Golden 标准：`src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/*`、`src/type/rankTrendDefaults.ts`。
- 当前主链：QuantBoard 负责参数研究、回测、优化、交易模拟和报告展示。
- 参数优化口径：优化是 `backend/optimization/**` 独立模块，负责搜索方法、目标函数、异步任务状态和实验记录；它调用回测引擎执行 trial，但不得把搜索逻辑塞回 `backend.core.backtest`。
- 优化方法口径：正式搜索方法只有 `grid`、`random`、`bayesian`、`tpe`。`method=bayesian` 是 Optuna `GPSampler` 高斯过程优化；`method=tpe` 对应 Optuna `TPESampler`。`method=optuna_tpe` 只作为后端兼容别名保留，不在前端和 CLI 展示为独立方法。
- 优化任务口径：`POST /api/optimizations/rank-trend` 异步返回 `status=running` 和 `runId`；`GET /api/optimizations/{run_id}` 只返回 `running`、`completed` 或 `failed`。
- Dragon Board 根项目只提供实时看板、快照数据与 Python golden 结果的消费展示（不再导出 golden、不保留本地 golden 链算法）。
- 默认快照：`snapshot_type=half_hour`。
- 可选快照：`quarter_hour` 可用于细颗粒度研究，但必须显式选择，不能替代默认口径。
- Fusion 候选池历史语义：`GET /api/backtests/{run_id}/fusion-projections` 以 `ranktrend_early_big_move_v3_lifecycle_fusion` 为唯一策略锚点，必须基于 `signals + trades + tradeEvents/openPositions` 构建 projection rows；不得按股票代码把整次回测粗暴折叠成一条。
- 存储主链：当前运行主库是 MongoDB（单主链 + R2 对象备份）。**2026-09-29 起 SQLite/Supabase 运行链代码已物理删除**，旧 API/CLI 由 410 桩直接返回；`storage_backend` 默认 mongodb，sqlite 仅剩显式 opt-in 的一次性诊断口。回测/生产写库只入 `dragon_board_quant`，pytest 数据只入 `dragon_board_test` + Redis pytest 前缀。实施状态以 [mongodb-migration-plan.md](mongodb-migration-plan.md) 为准。
- 当前同步批次：MongoDB 模式不再登记 SQLite/Supabase `sync_outbox`，不再运行 Supabase 自动同步、`push-backup`、`prune-backup` 或 SQLite 90 天明细归档作为生产链路；旧 API/CLI 在 Mongo 模式下应返回 410 或拒绝执行。
- MongoDB 替换 IndexedDB/SQLite 的当前切口：Dragon Board 正式写入和读取仍只通过 QuantBoard 后端 API；`POST /api/snapshots/ingest` 写入 MongoDB，`GET /api/snapshots/frames`、`/api/snapshots/records`、`/api/snapshots/stock-rows`、`/api/snapshots/sector-rows` 从 MongoDB 读取并保持 camelCase 字段合同。IndexedDB 和历史 JSON 只作为迁移前来源，不再作为正式 fallback。
- 题材映射当前切口：Dragon Board `ThemeDataService` 正式读口调用 QuantBoard `GET /api/themes/mapping`，数据来自 MongoDB 题材集合；旧 `themeDATA.db` 和旧浏览器 `ThemeDataDB/theme_mapping` 只作为迁移源或审计参考。
- failover 当前切口：不保留 SQLite + Supabase 运行时降级路径。MongoDB 不可用时正式接口必须结构化失败，不返回空列表或 `backup_only` 伪装成功。
- 题材模块 V2：Dragon Board 快照会写入稳定题材列，QuantBoard 回测会生成 `ThemeCandidateSupport`。默认 `useThemeFactorForExecution=false`，题材只做候选解释；只有显式开启时才参与置信度调整和拥挤风险降级。
- 题材模块 V12 目标：ThemeTrend 作为与 RankTrend 并列的 QuantBoard 研究链，承接题材趋势、题材共振回测、优化、API/CLI 和报告合同。当前已进入可运行主链；剩余深化项为 TS golden 多场景自动导出与 walk-forward/样本外报告（bayesian/tpe 搜索器已于 2026-05-03 `0e6de8e5` 接入，`2026-09-26-themetrend-v12-upgrade-design.md` §9 勘误）。
- V12 Phase 1 已完成：ThemeTrend 研究数据合同（`ThemeFactorFrame`、`ThemeStockExposureFrame`、`ThemeSignalRow`、`ThemeQualityReport`）、研究结果集合/表、`ThemeResearchRepository` 和 `ThemeResearchService`（从正式快照事实回放构建题材研究帧，不修改题材基础映射）。所有记录均保留完整溯源链，质量门禁返回结构化失败。
- V12 存储口径：MongoDB 模式下 ThemeTrend 新研究结果进入 MongoDB 研究集合；旧 research SQLite 和 `themeDATA.db` 只作为迁移前历史口径，不再作为运行主库。
- V12 边界：Dragon Board 根项目不新增回测平台；共振策略以 RankTrend 候选为主，ThemeTrend 只能辅助排序、置信度、拥挤风险降级和解释，不得独立制造买入信号。
- V12 策略口径：`theme_rotation`、`leader_theme_confirmation`、`hotlist_theme_confluence` 必须在执行信号中保留独立入场、降级、过滤和解释字段；Dragon Board 只展示 QuantBoard 研究摘要，不在根项目实现交易模拟。
- L2 资金流口径：`estimated_l1` 只允许作为观察指标；正式资金流回测必须使用 `broker_l2` 或 `official_l2`，并在质量门禁中保留 `capital_flow_source`、`capital_flow_confidence`、`money_flow_estimated`。
- 后端快照采集器：`backend/snapshot_collector/` 已正式切换为生产快照主链，写入 `dragonboard_live`。由**独立进程** `backend/collector_main`（默认端口 8001）承载调度器，经 DragonBoardLauncher 作为核心启动项管理；8000 Quant API 进程不再启动采集调度器（避免双采/争锁）。写入 live 数据集需显式设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=1`、`QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live` 和 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1`，CLI 预检和 quality gate 才会放行；任意其它 dataset 仍被拒绝。Dragon Board 前端已默认关闭正式快照自动写库，手动诊断入口保留。该模块的改动必须通过以下测试链路验证：
  - 后端 pytest：`tests/snapshot_collector/`（2026-09-29 起测试按领域归档到 tests/ 子目录，覆盖 models、slots、providers、builder、quality_gate、state、service、service_factory、routes 和 repository 合同）
  - python-bridge 接口测试：`python -m unittest discover python-bridge -p "test_*.py"`（覆盖 `GET /api/quotes/snapshot?codes=...` 行情接口）
  - MongoDB 审计命令：`.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour`
- 通达信 L2 能力边界以当前 bridge 源码验证结果为准，不得把五档 L1 描述成官方客户端级 L2；任何 L2 相关功能描述必须标注已验证的 bridge 能力来源。

## 工作边界

当任务明确限定为文档时：

- 只修改 `quant-board/docs/**`。
- 不修改 `quant-board/backend/**`、`quant-board/frontend/**`、根项目 `src/**`。
- 如发现代码和文档不一致，先记录在文档中，不主动改代码。

当任务允许实现时：

- 先定位现有模块和测试，再做最小改动。
- 不回滚、不覆盖他人正在修改的文件。
- 如果发现未跟踪或已修改文件，默认认为是用户或其他协作者的工作成果。

## 回答风格

- 全程中文。
- 结论先行，说明问题、原因、改法、影响面。
- 面向个人开发者，Python 后端概念要解释清楚，尽可能展开相关教学。
- 不用空泛建议；每次输出都要能指导下一步实现或验收。

## backend 目录归档要求（2026-08-07 重构后）

QuantBoard `backend/` 已完成目录规范化，**新增/修改代码必须按领域归档**：

```text
backend/
├── analysis/       # 分析算法层（纯函数优先）
│   ├── ranktrend/  # RankTrend golden 引擎（engine.py）与观察/回测辅助
│   └── theme/      # 题材领域算法：heat / momentum / daily_series /
│                   #   momentum_config / momentum_validation / support / trend / rotation
├── services/       # 业务服务编排层（有 I/O）
│   ├── backtest_service.py / optimization_service.py / golden_service.py /
│   │   audit_service.py / efficacy.py / checkpoint.py / _shared.py
│   ├── theme/      # 题材领域服务：fund_cache / heat_service / mapping_refresh / mapping_scheduler
│   └── market/     # 市场资金领域服务：fund_scheduler / fund_stream
├── api/            # HTTP 路由层（*_routes.py，不含业务逻辑）
├── core/           # 领域核心：回测引擎、交易规则、组合
├── data/           # 数据访问层：schema、仓库、repository
├── optimization/   # 参数搜索与优化
├── market_proxy/   # 外部数据代理（akshare/httpx）
├── snapshot_collector/  # 快照采集
└── snapshot_derivation/ # 快照派生/投影
```

归档硬约束（违反即视为结构违规）：

1. **算法 → `analysis/`，服务 → `services/`，路由 → `api/`**：三者分离，算法保持纯函数可单测，服务负责 I/O 编排，路由只做适配。
2. **禁止**把新代码散落到 `backend/` 根目录（历史遗留的 `theme_*.py`、`market_*.py`、`services.py` 已全部归入子目录）。
3. **禁止**新增巨型服务单文件（如原 2971 行 `services.py`）；服务按类/职责拆分到 `services/` 子模块。
4. **RankTrend 算法必须放 `backend/analysis/ranktrend/`**（golden 引擎 `engine.py`）；**题材算法必须放 `backend/analysis/theme/`**。
5. 新增测试就近放置；涉及归档目录调整时，必须先跑全量 pytest 确认无 import 断裂。

## 硬约束

1. `rankTrend` Python（`backend/analysis/ranktrend/engine.py`）是 golden 生产事实标准，TS 前端只消费其输出。
2. QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
3. 默认 `snapshot_type` 是 `half_hour`。
4. `quarter_hour` 是可选项，不是默认项。
5. 回测和优化必须保存 `random_seed`、`config_hash`、`dataset_id`、`snapshot_type`、`strategy_version`。
6. 数据质量门禁失败必须结构化返回，不允许静默吞掉。
7. Python 端 rankTrend 输出字段即 golden 合同（`RankTrendAnalysisResult`），TS 消费方按该合同校验。
8. 前端展示不得把 `finalSignal` 当成唯一交易结论，应优先展示状态、候选分层、风险、样本质量和交易解释。
9. MongoDB 主库、备份恢复、禁用旧维护入口、快照入库和 API/CLI 合同变更，必须同批更新对应文档。
10. Dragon Board 前端不得直连 MongoDB 或 Supabase；正式快照写库必须走 QuantBoard 后端 API。正式快照判重以后端 `dataset_id + snapshot_id` 为准，不得再以浏览器 IndexedDB 记录存在性作为正式保存条件。
11. 不得重新引入 Supabase `snapshots.payload` 兼容备份方案，也不得恢复 SQLite/Supabase 运行时 failover。
12. Supabase、旧 Parquet 归档和 SQLite archive retention 只属于迁移前历史口径；MongoDB 主库明细不得因旧 retention/归档任务被删除。
13. 不得把回测、优化、Golden 或报告大 JSON 重新塞进 Supabase Free 版备份链路；MongoDB 模式下新研究结果进入 MongoDB 研究集合。
14. DuckDB 只能作为后端只读归档查询引擎，不允许新增前端可传 SQL 的接口。
15. IndexedDB 替换已经进入 MongoDB 后端读写口阶段；后续不得恢复浏览器 IndexedDB 作为正式读写 fallback，历史数据只作为迁移源或审计参考。
16. 迁移 DataLayer 的 IndexedDB 读写入口时，不得删除或重命名 `SnapshotRecord`、`SnapshotFrameBundle`、`SnapshotStockRow`、`SnapshotSectorRow` 已有字段；MongoDB 后端 API 必须承接字段并以 camelCase 返回。
17. 删除 IndexedDB 历史前必须先完成后端迁移收口与人工验收，确认 MongoDB 正式集合行数/文档数与迁移源一致；不要把浏览器端旧 IndexedDB 校验/补齐入口当成正式合同。正式快照缓存默认关闭后，不得重新在 `DataLayer` 或 `snapshotFacade` 正式读写口恢复 IndexedDB fallback；QuantBoard 后端不可用时正式读取必须显式失败。
18. 优化结果只生成候选参数，不得自动写回 Python、TypeScript、API、CLI、前端表单或文档默认值；CLI 必须支持 `tpe` 和异步提交 `--no-wait` 口径。`optuna_tpe` 仅作为后端兼容别名。
19. 题材因子不得绕过 RankTrend 独立制造买入信号；执行开关开启时也只能辅助已有候选分层。
20. 题材基础映射新增或更新必须进入 QuantBoard MongoDB 题材集合；不得重新把浏览器 IndexedDB 或旧 `themeDATA.db` 当成运行主库，也不得把题材静态映射混入快照事实集合或研究集合。
21. V12 ThemeTrend 回测、优化、signals、quality report 和报告结果在 MongoDB 模式下必须归属 MongoDB 研究集合；不得进入 Supabase 或旧 `themeDATA.db`。
22. 新增 ThemeTrend API/CLI 合同时必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`，默认 `snapshot_type=half_hour`，`quarter_hour` 只能显式传入。
23. 文档或实现涉及 ThemeTrend 时，必须区分“已完成能力”和“V12 目标/拟新增合同/首批落地”，不得把计划中的接口描述成已上线事实。
24. 资金流策略正式回测不得默认消费 L1 估算主力资金；如显式允许 `estimated_l1`，报告必须标注实验口径和高风险。
25. `trade_journal` 在 fusion 候选池语义中只能作为 execution overlay，不得反推 `triggered_wait_entry`、`active_holding`、`exit_signaled` 或 `closed`。

## 推荐执行流程

1. 定位：用 `rg` 或目录列表确认相关文件。
2. 对齐：确认当前任务涉及哪篇 docs 专题文档。
3. 计划：说明要改什么、为什么、影响哪些文件。
4. 落地：只改必要范围。
5. 验证：文档任务至少检查链接、关键词和文件列表；代码任务运行相关测试。
6. 总结：列出改动文件、验证结果、剩余风险。

## 文档维护规则

- README 只放总览、索引和首期硬约束。
- 专题细节写入对应文档，不把所有内容堆到 README。
- 修改默认值、策略合同、API 合同时，必须同步更新交叉引用文档。
- 修改存储、同步、快照入库、数据库表字段、恢复策略或 API/CLI 请求响应字段时，必须同批更新 [mongodb-migration-plan.md](mongodb-migration-plan.md)、[architecture.md](architecture.md)、[api-cli.md](api-cli.md) 和必要的用户/路线图文档。若只涉及迁移前 SQLite/Supabase 历史说明，再同步 [database-migration-plan.md](database-migration-plan.md)。
- 发现旧文档把 Dragon Board 根项目描述为回测平台时，必须删除或改为当前 QuantBoard 口径。

## 给后续 AI 的上下文提示

开始新任务时优先阅读：

1. [README.md](README.md)
2. [mongodb-migration-plan.md](mongodb-migration-plan.md)，如果任务涉及当前存储、同步、快照入库、恢复或 API/CLI 合同
3. [ranktrend-golden.md](ranktrend-golden.md)
4. [ranktrend-python-port.md](ranktrend-python-port.md)
5. 与任务直接相关的专题文档

如果用户要求实现首期功能，推荐顺序是：

1. 数据导入与质量门禁；
2. golden case 生成与校验；
3. Python rankTrend 移植；
4. 回测引擎；
5. API/CLI；
6. 前端展示；
7. 参数优化。

---

## 阶段多帧确认字段合同（2026-09-24）

`hotlist_sentiment` 文档新增三个字段：`rawStage`（本帧截面事实，`resolve_stage` 输出，唯一权威真值）、
`stage`（确认投影——当日「严格早于当前槽」的截面序列 + 本帧一次，重放 `stage_confirm.confirm_stage`
滞回；候选阶段连续 `confirmSlots` 槽复现才切换，默认 2）、`stageConfirmState`
（`pending` / `pendingStage` / `pendingSince` / `confirmSlots` / `historyStatus`，枚举
complete / empty / legacy_fallback / unavailable）。`summary`/`riskLevel`/`confidence`/
`signals`/`warnings` 仍是本帧截面证据，不按确认阶段二次计算。

关键语义：EOD 与其锚定槽同帧只计一次（结果一致）；历史重算按当前槽因果截断，未来槽不得污染；
旧文档以 `rawStage ?? stage` 兼容读取（`legacy_fallback` 计数进 `diagnostics`）；
EOD 双形态排除（日级 `_id` 与 `slotTime="EOD"`）；独立轨道降级（`stageShares` 缺失不影响
阶段序列，反之亦然）。

读写与回退：四个生产写口（lazy compute、`compute_and_upsert_for_slot`、`run_for_date`、
`run_for_date_slots`）与 `/api/hotlist-sentiment/ingest` 共用同一投影；ingest 未提供确认字段时
不伪造（`exclude_none`）。series/slots 响应合同变化已升 Redis 缓存版本 `v2`（共享常量
`_HOTLIST_SENTIMENT_CACHE_VERSION`）。回退：`HOTLIST_STAGE_CONFIRM_SLOTS=1` 逐槽等价
（`stage == rawStage`），非法配置回裁决默认 2 并落诊断；不删除任何历史字段或文档。

## 路线 B 连续情绪评分（2026-09-30）

EOD 档位主定义已从布尔级联切换为**连续评分驱动**（设计 `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（仓库根路径，下同）
v3 + 审计 `2026-09-30-emotion-score-audit.md` + 校准 `2026-09-30-emotion-score-calibration.md`；迁移与典型日对照
`docs/hotlist-jev/emotion-score-migration-report.md`）：

- **判档来源**：`emotion_score.compute_emotion_score`（8 维等权连续分 0-100，jev 聚合口径 1068 槽实测校准，
  缺维跳过权重归一化）→ `map_stage`（≥75 高潮 / 60-75 发酵 / 40-60 启动 / <40 按当日斜率分退潮·冰点；
  高潮压制条款已删除）→ 分数域确认（复用 `stage_confirm.confirm_stage` 滞回，confirmSlots 语义不变）。
- **字段合同**：`rawStage`=本帧映射档位（含斜率；证据全缺时 null——方案 B 不伪造档位）；`stage`=确认投影；
  新增 `emotionScore` 子文档（score/dims/skippedDims/computedAt/slope/version，可分解审计；其中
  `stageCandidate` 与 rawStage 同值）与 `legacyCascadeStage`（旧级联截面对照面，`resolve_stage` 函数保留不删）。
- **斜率**：`_collect_intraday_state.scorePoints` 因果收集当日早槽 `emotionScore.score`，slope=上一有效槽差；
  prev 缺失（首槽不标）落 `emotion_slope_unavailable:prev_score_missing` 诊断；score 全缺落
  `emotion_score_unavailable:slot=<槽位>` 诊断且确认序列跳过该槽（含 historyStatus=unavailable
  分支，禁字符串 "None"）。
- **evidence 取数降级**：写口的 analysis_by_code/昨日同期总额读取失败降级为空 +
  `emotion_evidence_load_failed:*` 诊断，不阻断写库（部分来源失败仍落档，fail-visible）。
- **写口与缓存**：四个写口 evidence parts（yesterday_rows 复用 previous_day_stocks；analysis_by_code 与昨日同期
  总额复用 jev 服务层取数）共用同一投影；series/slots 缓存版本 `v3`；ingest 白名单含
  `emotionScore`/`legacyCascadeStage`（禁止静默丢弃）。
- **历史与回退**：113 交易日 1182 文档已全量重算（新口径，幂等脚本 `backend/operations/emotion_score_recompute.py`）；
  回退 = 调用点切回级联 + 历史 stage 从 `legacyCascadeStage` 重算恢复。策略层消费不变（`risk.py stage_adjust`
  仍读五档枚举），regime 影响量化见 `docs/hotlist-jev/emotion-score-regime-diff-report.md`（EOD 层 meanDiff +2.44，
  68% 天数受影响）。校准重校准触发条款见设计 v3 §9。

## jev 热榜情绪观察轨道（2026-10-08）

独立观察轨道，设计唯一来源 `docs/hotlist-jev/hotlist-jev-emotion-observe-design.md`（方向重置版）：

- **定位**：Cloudflare `typesafe/jev` 从纯原始市场证据回答两问（当前帧五档 + 当日连续帧序列五档），
  盘后固定日级总体；与规则情绪轨道是**并列观察者**（无预设权威，golden 不当 ground truth——
  2026-10-08 用户裁决推翻旧验证路线），裁决方式=用户在前端热榜情绪面板盘中对照论证。
- **红线**：聚合/叙事/文档零规则五档输出（不读 `hotlist_sentiment`）；零预测问题（无 noul）；
  三态 ok/degraded/no_data 不伪造；采集链第 4 步失败只记 warning 绝不阻断；gate
  `JEV_SENTIMENT_ENABLED` 默认关；只落库只展示不回写、不进信号不进交易路径。
- **改动边界**：改叙事/问题/合同先改 design 文档；`jev_client.py` 是 N15 保留件勿轻动；
  token 走 `JEV_CF_TOKEN` 环境变量不入仓；pytest 数据只入 `dragon_board_test`。

## KPL Socket 实时行情链路（2026-10-27）

协议合同、运维 runbook 与已知限制唯一来源：[kpl-socket/README.md](kpl-socket/README.md)
（逆向攻坚过程记录在 `hotlist-jev/socket-push-handoff-20261026.md`，勿当运行手册）。

- **定位**：KPL（开盘啦）私有 socket 协议的 PC 复刻链路——610 白盒签名认证、3001 板块 /
  3006 个股订阅、0x60 推送帧解析、:8002 采集服务、:8000 `/api/kpl/*` REST+WS 代理转发、
  浏览器实时面板。已上线实测（个股 000001 平安银行、板块 801044/885423 到流）。
- **红线 1（测试禁真实连接）**：pytest 一律全 mock（FakeCodec/FakeSocket），
  零真实 KPL 连接、零真实 WBE 调用；真实连接只走预登记的人工运维诊断路径。
- **红线 2（App 保活）**：模拟器内开盘啦 App 必须保持正常可用；不 force-stop；
  注入用 wrap prop 保持清空；PC 客户端与 App 同时在线实测互不踢。
- **红线 3（单实例纪律）**：serve_kpl_socket 残留旧实例会与新实例采集线程互踢
  （会话 ~6s 循环断连）；启动前确认唯一进程对（venv launcher+child 双 PID）。
- **协议事实**：认证命令号是 **610 不是 601**；260 challenge 每连接随机；pb tag 是 varint
  （f100→a2 06）；价格 ×10000 整数缩放；服务器会话寿命与认证速度相关（非固定 TTL），
  稳定性合同=2s 重连链而非单连接长寿命；keepalive 必须递增 seq（重复 seq 立即断连）。
- **订阅注册表重构（2026-11-17，P0-P3 已实施）**：RE 定案当前 App 版本不发 211 SubReqs
  （仅 proto+ack 展开在）；实际订阅=单帧 0x40+ext attr2=subId（hint=cmd）+客户端注册表，
  权威 subId/topic 取 ack attr2/attr3，退订=402/pkg 0x50。已落地：`kpl_sub_registry.py`
  注册表（替代旧 _resub_cache，单一事实源）+ 220 选择性重发 + 402 退订（flag 默认关）
  + 211 批量信封（KPL_SUB_BATCH 默认 direct，会话级熔断回退）；全 mock 418 passed，
  direct 订阅帧形态逐字节零变更。**探针全部开火裁决（2026-11-17）**：211 item.data
  必须 GCM（明文→2008 杀连），仅 hqDaban 全局族可批（2103/2203/2013 批内拒
  2000/cmd 110），收益 ~7 帧/会话不抵风控面 → 保持 direct 不启用；批内盘中推送
  交付==direct 实弹验证；402 语义钉死（ack=28B 状态块，subIds 按 seq 取原请求，
  退订推送即停差分成立，KPL_UNSUB_ENABLED 仍默认关——per-stock 共享 subId 误退阻塞已实现唯一 subId hint 修复（KPL_SUB_UNIQUE_ID 门控，待 uid/uidcmd 探针裁决，方案 §12）；**P4：610 重发第 5 次
  →1106 确定性杀连（受控实验 3/3 中位 67s），off 3/3 零错误 >120s →
  默认已切 KPL_KA_MODE=off**。方案唯一来源
  [kpl-socket/sub-registry-refactor-plan.md](kpl-socket/sub-registry-refactor-plan.md)
  （§1.3 裁决/§7.1 下午盘/§11 开火记录）。
- **已知缺陷与待办（2026-10-27 待办轮已全部收口）**：3006 负数 varint 已修复（`_signed64` 补码还原）；
  3001 quotas 关键位语义已独立源核实（[0]板块标签/[1]最新价(板块=点位)/[2]涨跌幅%/[3]成交额/
  [7]-[9]主力流入流出净额，东财接口交叉对照精确匹配）；signsvc readline 阻塞已改守护读线程
  +deadline 取行；WS 中继已有 mock 测试。条件性遗留：261/262 反作弊轮（服务器从未下发，触发再接）
  与 token 失效轮换（详见 kpl-socket 文档 §四/§八）。
- **凭据红线（2026-10-27 提交前脱敏）**：KPL_USER_ID/KPL_TOKEN 代码零默认值（默认游客 userId=0），
  正式账户值只走环境变量注入（本地参考值存 gitignored 的 `.tmp_review/kpl_credentials.env`）；
  任何 KPL 凭据/token/盐值不得入仓。
- **打板/情绪事件流（2026-10-28 增补）**：同一链路扩展 0x40 通道 7 个 cmd（2114/2115/2116/
  2118/2119/2120+2121/2126）的订阅、pb 解析（`kpl_daban_protocol.py`）与结构化事件
  （zd_stat/market_overview/plate_strength/zt_situation/zt_stocks/dt_stocks/wind_vane），
  面板增补情绪仪表盘；盘中 30 分钟实测秒级事件全到流（封单变化 2137/状态翻转 6/情绪刷新 462），
  App UI 同屏对照 real_zt=44/real_dt=3 精确一致。协议合同详见 kpl-socket 文档 §九；
  2120/2121 请求 orderType 必须 4；模拟器依赖拆解（签名层单点绑定/架构已隔离 codec）同 §9.5。
- **白盒签名 PC 化（2026-10-28）**：签名层摆脱 adb/模拟器运行时依赖——`backend/services/kpl_pcemu/`
  用 unicorn x86-32 模拟 libauthSign_x86.so（WBE/ENC/DEC 全套），`KPL_CODEC=pc|adb` 双轨
  （pc 默认，adb 为 signsvc 兑底对照）。实测：WBE 4/4 组、ENC/DEC 9/9 项与设备 ground truth
  逐字节一致；:8002 PC 轨完成 610 认证全事件流到流。硬事实：JNI 槽位以 JDK jni.h 为准
  （SetByteArrayRegion=208，曾错标 205 是输出全零真根因，「白盒未预热」为误判）；门位
  0x38597C/0x38597D 显式置位；imp_free 必须真实回收（否则数百次调用后堆耗尽）；工件三件套
  在 gitignored 的 `data/kpl_pcemu/`，`scripts/extract_kpl_pcemu.py` 提取。协议合同见
  kpl-socket README §十；**pytest 禁止加载真实 ELF**（test_kpl_pc_codec.py 全 mock）。
- **打板个股列表三页验收收口（2026-10-28）**：工作台【集合竞价/即将涨停/风向标】socket 2103 实时
  （pidType 8/0/6，7 页订阅）+ HisDaBanList 历史回放两链实链验收通过——WS 270 事件/75s 全型到流、
  pid8 竞价快照 183 项零缺口且与 App 同屏基线逐项一致、pid9 降级路径结构化；HisDaBanList 1020
  异常解除（实为参数白名单：Day 外多传任意键即 1020，见 README §11.4 修订；缓存按日共享，
  30s 内三页签最多 1 发上游；空列表/历史 note 均 fail-visible 透出）；历史行列语义
  独立源核对收口（pos4/13/17 精确一致，pos14/15 实际流通口径自洽；pos29/pos18-32 默认集合内
  无法核对待抓包）。前端修复：会话 TTL 关闭时 server error 1106（cmd=110 紧邻 close，会话期数据
  全量到流）结构化白名单（ev.server.code===1106）+ msg 形态正则双保险，均只计统计不上横幅
  （lastError 经 /api/kpl/status 可查）。**2026-11-06 盘中探针修订：该信号已由 1106 变为 1002**
  （75s/601 事件/8 会话：每会话必以 {'code':1002,'msg':'连接错误：1002'} 紧跟 closed by server
  收尾，推送流全程健康），白名单同步扩为 code∈{1106,1002}；另修 kplErrKey 双引号 JSON 形态
  （server-only 双发事件）归一缺失导致的成对重复日志。
- **龙虎榜链路（2026-10-29 三期）**：2112 会不会上龙虎榜预测 + 3004 RealtimeLHB 双 socket
  链 + HisBeOnTheLHB 历史回看全开火验证（预登记探针，证据 .tmp_review/lhb*_probe_*）。
  关键坑：**HisBeOnTheLHB 的 a/c 与 D1 参数顺序互换**（mo0.d 第一参数→c 第二参数→a，
  记反即 1020）；**龙虎榜 int64 资金字段=元原样无缩放**（双源交叉验证证伪 ×10000
  假设，mainBuy+mainSell=mainNetAmount 卖出记负，口径=盘中主力大单非席位额，
  docs/kpl-socket/lhb-scaling-verification.md）。collector 开关 daban_lhb/lhb_realtime
  默认关、独立于 daban_subs；最小订阅面会话寿命极短（1002 循环），生产与 daban_subs
  同开。读口 /api/kpl/lhb-forecast|lhb-realtime|lhb-history|lhb-sale +
  /api/market/lhb-seat-dates|lhb-seat-detail|lhb-day-detail|lhb-branch-detail（东财
  datacenter-web，2026-10-30 用户解禁：个股席位明细 KPL 无源——同日开火阴性
  GetBusinessList/GetStockList 加 StockID 被静默忽略，dex 全枚举 LongHuBang 域 5 端点无
  StockID；akshare 库仍不用，httpx 直连）；:8008 龙虎榜🏆页签 **2026-10-30 二次改版**：
  左=个股/营业部页签切换（板块行情同款），右=席位前五（个股模式=选中股买卖前 5 席位；
  营业部反查模式=选中营业部当日买卖个股，名称归一+相似度匹配）；个股列表列名
  涨幅/价格/换手率%（2 位小数）+ 默认仅显有席位上榜股（可切全部）+ 搜索/市场筛选/
  表头排序（涨停复盘同款）；**2026-10-30 晚读数入口修正**：当日实时左列表主源改
  GetStockList 实际上榜名单（83 只，App 同源；原 2112 预测池 30 只被席位过滤剩 17
  为入口错误）；BuyIn 语义修正=净买入（与 App 净买入列逐分一致）；JEV 事实段供给 jev_lhb_ammo.py
  （纯事实组装，禁喂清单合规）；题材龙头语料同源接入（AMMO 2026-10-30a，
  theme_leader_ammo.lhb_line 按龙一+板内成员过滤，预登记 §23；2026-10-30b 分页修复
  st=300、2026-10-30c 席位/机构扩维、2026-10-30d 语料精简（AMMO 换代，共享行同步
  打标链）、2026-10-30e 15:00 收盘总结行+经济/产业板块名后缀桥、2026-10-30f 直播
  只收板块相关时间点+来源注记删（共享行同步打标链）、2026-10-30g 括号注释清理
  （工程/方法论注删，防误读锚保留），预登记 §23 补记）。协议合同详见
  kpl-socket 文档 §十三。
- **KPI 两卡历史修复（2026-10-28）**：大盘指数（沪/深/创）/涨跌家数历史模式不再显 "--"——
  新增 `/api/market/index-history`（腾讯 ifzq 日 K）与 `/api/market/breadth-history`
  （东财 push2ex 涨跌分布仅最近交易日可得，本地 data/market_breadth_daily.json 逐日累积，
  更早日期结构化缺数 fail-visible）；服务 `backend/services/market_history_service.py` +
  `test_market_history_service.py`（全 mock）。详见 kpl-socket README §11.4/§11.5。
- **竞价页【竞昨比】列（2026-10-28 用户需求）**：工作台派生列（非 App 原生），
  `竞昨比 = 竞价成交量/昨日成交量×100%`；2103 竞价 quotas 无 量 列（实测 28 位），
  派生口径 `竞价成交量(手)=竞价成交额/(竞价价×100)`、`竞价价=昨收×(1+竞价涨幅/100)`，
  原料读口 `/api/kpl/daban-prev-day-basis`（腾讯 ifzq 日K，param 必须带 sh/sz/bj 前缀；
  按日缓存 12h、失败 10 分钟不重试、missing fail-visible）。口径自洽校验 8/8（竞价成交额/实际流通
  与 2103 竞价换手逐只吻合）。详见 kpl-socket README §11.2。
- **炸板池/跌停池页（2026-11-08 用户需求）**：工作台侧栏「KPL 行情 › 炸板池/跌停池」——
  参照【涨停池】页同构（2103 pidType=2/3，collector 默认订阅面扩为 8/0/6/1/2/3 六页签）；
  读写全部入同一 `kpl_daban_pool` 日档 zb_/dt_ 前缀通道（用户裁决：不新增数据集），
  `DabanPoolArchiver` 单循环四通道顺序落库、单通道失败不连带；跌停池与涨停池同款
  pool_state sealed/broken 标注（broken=打开跌停未回封），炸板池无标注（成员=当日
  曾炸板全集，回封态见涨停池通道）。读口 `/api/kpl/daban-zhaban|daban-dt?date=`；
  前端参照涨停池同构但**按实测上游覆盖选列**（pid=2/3 帧 `zt_reason`/`plate_id` 全空，故左表按
  板块分组、不摆原因/强度/量比；pid=3 无 price/pct，pid=2 无 zt_tur；跌停池状态列仅历史模式展示），
  左表带「全部」行且默认不预选（池小分组碎，不让分组隐藏记录），板块精确段匹配使家数=右表行数；
  「源可用但池为空（0 家）」由后端空档 `empty:true` 透出（不逐日回退到旧日档）；
  缺值一律 '--'（fail-visible）。pytest 四文件 117 passed（全 mock）。
  详见 kpl-socket README §11.1/§11.4/§11.6。
- **打板六页左表「全部」行（2026-11-08 用户需求，参照炸板池）**：涨停池/集合竞价/即将涨停/
  风向标 四页左表首行均增「全部」行（与炸板/跌停池共用 `kplDabanAllSums`：全量按个股去重、
  `sumN` 全缺显 `--`），口径统一：默认选中「全部」不预选分组，点分组筛选、再点取消回「全部」
  （旧「自动选首组 + 点选不取消」已废）；涨停池「全部」行强度/量比显 `--`（板块排行比值
  不可聚合，无源不伪造），主力净额为全量成员合计；左表加 `#` 列，过滤框只筛分组行、不再
  因选中态折叠左表。E2E 四页 33 项断言全通过（家数=右表行数/取消回全量/无 JS 错误）。
- **六页合并为【个股行情】单页（2026-11-08 用户需求）**：侧栏「KPL 行情」下集合竞价/即将涨停/
  风向标/涨停池/炸板池/跌停池六个入口合并为一个【个股行情】页（`kplstock`，图标 🧾）——
  **左板块列表不变，右个股列表左上方新增模式按钮组**（默认涨停池；六模式列集/口径一律沿用
  既有实现，未改字段语义）：`DABAN_PAGES[*].p` 统一为 `kplStock`（共用一套 DOM），页内当前模式
  `KPL.dabanView`，渲染守卫统一 `dabanOn(view)`；侧栏/KPI 条/WS `daban_stocks` 触发/4s 轮询只认
  `DABAN_PAGE`；各模式 live/history/选日、选中分组、列排序各自记忆，搜索/板块过滤词不跨模式继承；
  日期框/数据源/「回实时」跟随当前模式。硬约束不变（缺值 `--`、全缺不烘 0、页缺口/池空如实透出）。
  验证：Playwright 静态页冒烟 13/13（mock 2103 快照，零真实上游与零 jev 调用）。
- **实时无 2103 快照 → 本地存档回退（2026-11-08 现场修复）**：【炸板池/跌停池】实时模式的
  「暂无板块 / 等待 2103 快照到流」+ 状态栏 ×22 `no_daban_list_snapshot(pid_type=2)`。排查结论：
  数据集**有**数据（`kpl_daban_pool._id=2026-11-06` 的 zb_items=14/dt_items=15/bid_items=175），
  读口实拉 ok:true；缺的是 collector **实时帧**——会话被上游频繁重置（~23s/次，261 反作弊 EXEC
  未实现 + 风控期），42 帧 2103 订阅爆发在会话内只回得及前几个页签（pid 2/3 订阅序末位）。
  修复：实时读口非 ok 且该模式无可用实时快照 → 逐日回退本地日档（≤7 天）并显式标注
  「实时无快照·回退存档 YYYY-MM-DD」（统计行/页头），轮询不停、实时恢复即切回；回退态不改
  历史选日/日期框、扫档 60s 节流、同一条降级消息 60s 内只入状态栏一次。无存档通道的
  即将涨停/风向标不冒领回退。未解：261 EXEC 才能修 collector 会话寿命（只影响实时帧覆盖
  度，不影响存档回放与展示）。验证：Playwright 6/6（复现 pid=2/3 无快照 + 11-06 有档）+ pytest
  静态守卫 10/10。
- **风向标空帧抑制（2026-10-28 盘中修复）**：pid 6 上游全 Resp 形态且列表重建窗口高频回空帧
  （14 帧 12 空/2 满），无条件覆盖页缓存致读口恒空——空帧不覆盖非空页缓存（fail-visible 广播保留，
  含回归用例），盘中实测 25 项稳定到流。
- **边界**：该链路是本地单机诊断/观察链路；`serve_kpl_socket.py + kpl_page/` 布局已裁定遵循
  `serve_relay_page.py + relay_page/` 已入库先例（独立进程入口 + 静态页目录），不再迁移。
- **上涨/下跌复盘板块字段 = 韭研产业名（2026-11-06 用户需求）**：`services/jev/jiuyan_board`
  （单一事实源 `jiuyan_industry_stocks` 韭研产业树一级节点周频全成分快照，108 产业/2748 股）；
  board = 韭研产业名（节点 `_id` 升序首个收录）；韭研未收录 → board 置空「未分板块」
  （用户裁决：不回推主题材名，避免单列双口径）；产业库空 → `degraded:jiuyan_board`
  + 响应 `jiuyanBoard` meta 披露；板块 chips/筛选/分布共用 resolved 值。真库对拍
  2026-11-06 上涨名单 20/45 命中。详见 docs/hotlist-jev/jev-dieban-review-design.md §2 板块行。
- **261 反作弊轮作答链实现 + 2203 涨停原因语料落库（2026-11-08 用户需求，同一轮）**：
  ① 261→262：App 口径逐字节对照（`data[0:32]` token 原样回填、`[32:36]`=BE32 `d`、`[36:]`=
  US_ASCII 挑战串 → signsvc `EXEC|<串>|<d>`；应答 262 `pkg 0x30 / flags=(0<<3)|enc / d=0`，ENC
  失败回退明文），EXEC 失败/不可用/非 ASCII 一律 `anti_cheat_error` + 断连（不造假答案，App 同款）；
  代码落在 `kpl_socket_protocol.parse_anti_cheat_261|anti_cheat_challenge|
  build_anti_cheat_ans_262`、`SignSvcAdbCodec.exec`、`KplCollectorService._answer_anti_cheat`
  + status `anti_cheat_rounds`。实测（独立 signsvc 进程四发探针）：任意伪造挑战串均返
  `Long.MIN_VALUE`（`SocketRepository.execEncryptedHex` 先校验偶数长度 hex 再进白盒，伪造密文
  必失败）→ 真机作答只在收到真实 261 时才能验证，而服务端至今未下发（备而不用）。零真实上游
  单测：协议 3 + collector 7。
  ② 2203 涨停原因语料：`archive_reason_corpus` 每轮拉 `:8002/api/kpl/zt-reasons` 写入
  `kpl_daban_pool` 同日档 `reason_items`（按 stock_id 并集、字段随帧刷新、留 `first_ts`），
  原文透传不改写不拼接；日期跟随涨停池快照交易日（周末重推=上一交易日详情），条目 ts 早于
  该日 → `skipped_stale` 不写，无交易日 → `no_pool_date` 不猜；读口
  `GET /api/kpl/daban-reasons?date=`（`load_day(lane='reason')`），`no_archive` 与
  `no_reason_corpus` 严格分开。真库核对：`_id=2026-11-06` 当前 `reason_items=[]` → 读口如实
  `no_reason_corpus`（当日 `/zt-reasons` 本身 `no_zt_reason_snapshot`，短会话下 2203 与 2103
  同病），非缺陷。**jev 侧纪律**：本落库只供原料，接进题面/判据属方案变更须走 hotlist-jev
  预登记；语料 schema 单一事实源=`docs/kpl-socket/README.md §11.6`。测试：archiver 6 + 路由 3。
