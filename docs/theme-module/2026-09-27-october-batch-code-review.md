# 10 月批次前置接线 Code Review + 方案文档审计（双 subagent）

- 日期：2026-09-27
- 审查对象：工作区未提交改动（Path B 注入通道 + 优化器接线 + typed 修复 + 75 硬层参数化 + 10 月批次方案文档，12 文件 +702/−22 基线）
- 审查方式：**双独立 subagent**（pi CLI `-p` 非交互，`--exclude-tools edit,write` 只读，thinking high）：①Code Reviewer（spec→quality 清单 + 全仓消费点 rg 核对）；②文档审计员（事实-代码一致性 + Mongo 统计复算 + 仓库日历事实源核对 + 跨文档一致性）
- 对标先例：`2026-09-26-r2-r3-phase1-code-review.md`、`2026-09-27-persistence-rebuild-code-review.md`

## 1. 结论

**修复后通过 → 已全部修复，564 passed。**
Code Review：0 Critical / 5 Important（全部已修）/ 7 Minor（5 修 2 登记）/ 5 观察项。
文档审计：1 重大（F1 日历，已修）/ 2 中（F2/F3，已修）/ 1 轻（F4，已修）/ 1 提示项（F5，计数口径统一）。

## 2. Code Review 发现与处置

| # | 级别 | 发现 | 处置 |
|---|---|---|---|
| I-1 | Important | `_match_daily_factor_row` 双键同中不同值时结果依赖 set 迭代序（PYTHONHASHSEED），不可复现（实测 seed 3/6/7/11/15 → 取 5，其余 → 取 3） | **已修**：匹配序固定 themeName 优先、themeId 补位（去重保序），docstring 写明禁止 set 迭代序 |
| I-2 | Important | "双键同中"测试浅合并丢键（`{**a, **b}` 外层日期键覆盖），双键路径从未真正执行，假覆盖 | **已修**：重写为手工嵌套 dict（robot=5 / 机器人=3 并存），断言 themeName 优先语义 |
| I-3 | Important | 第七处硬编码 75 残留：leader_theme_confirmation 分支 `crowding < 75` 未参数化，"单旋钮"合同对该策略不成立 | **已修**：参数化；全仓 `rg "crowding >= 75\|crowding < 75"` 归零（confluence_score>=75 为另一量纲，保留） |
| I-4 | Important | `load_daily_persistence_inputs` 吞异常：非 Mongo/读失败/无行三成因折叠为 `persistence_daily_key_missing`，读库挂了被报成"没采到数据"，且无日志——低于 `_theme_gating_inputs` 自己立下的三分模板标准 | **已修**：改返回 `(mapping, source_flags)` 二元组，三成因分别打 `persistence_source_unavailable:storage_backend_not_mongodb` / `:{exc}`（同步 logger.warning）/ `persistence_source_no_rows`；backtest 两路径透出进 qualityReport.warnings，优化器新增 `dailyFactorSourceFlags` 结果键 |
| I-5 | Important | S4 扫描"optimizer 双通道"表述失实：`score_theme_trend` 只读 factors 不读 signals.score，weight 变化对 optimizer 目标零判别力，会跑出"零敏感"假象 | **已修**：分册 S4 通道改写为"payload runner + 产出 score 外部 IC 面板"，写明判据非 PnL |
| M-1 | Minor | design doc §10 引用旧帮手名 `_theme_daily_persistence_inputs` | **已修**：改 `daily_factors_service.load_daily_persistence_inputs` |
| M-2 | Minor | `dailyFactors` 键随 factors 泄漏进持久化产物（result_json/themeTrend.factors，仅 weight>0 路径） | **已修**：信号构建后 `factor.pop("dailyFactors", None)` + 泄漏断言测试 |
| M-3 | Minor | "golden v15 未 bump"作主证据偏弱（golden 只断言 factors/exposures，不含 signals） | **已修**：设计文档补括注（信号层零漂移由 known-answer 与逐位一致用例钉住） |
| M-4 | Minor | research 持久层（SQL 白名单 / mongo `_theme_signal_doc`）无 qualityFlags 字段，typed 修复只到内存/API 层 | **登记待办**（phase4 §5.1-2）：research 接注入前必须先补持久层字段 |
| M-5 | Minor | 探测函数对字符串数值（"0.5"）不敏感，与 from_patch 数值化口径不一致 | **已修**：`float(value)` 可析即算（bool 除外）+ 用例 |
| M-6 | Minor | confluence 路径接线零测试（`_confluence_execution_signals` 第六消费点） | **已修**：补静态方法直调用例（阈值 35 → D_EXIT_RISK） |
| M-7 | Minor | loader 假定 `days` 已排序（`days[0], days[-1]`） | **已修**：函数内 `sorted(days)` 防御 |

观察项（登记不修）：dataset_id 耦合（注入按回测 dataset_id 查因子，本地 bundle 数据集将全量 key_missing——并入分册 §2.1 检查点核对）；as-of 精确当日匹配与 gating 同一既定近似；`score_theme_trend` 读 factors 不存在的 `risk` 键（前存量）；循环依赖逐一核对无环；文档统计数字抽核一致。

## 3. 文档审计发现与处置

| # | 级别 | 发现 | 处置 |
|---|---|---|---|
| F1 | 重大 | "10-09 起开市"与仓库双日历事实源矛盾：mootdx holiday_bridge 缓存（fetchedAt 09-27）+ TDX 在线日历一致确认 **10-08（周四）为交易日**（10-01/02/05/06/07 休市）→ 台账"10-09~10-31"留下一日无主缺口、初判日期偏晚 | **已修**：全档 10-09 → 10-08（日历/台账/主段/首批日四处），初判日 10-22 → 10-21，标注事实源；10 月交易日 17 |
| F2 | 中 | 台账"09-28~09-30（B-202610 亦不触及）"措辞歧义——B-202610 恰恰消费此三日（RankTrend 域） | **已修**：改"theme 未消费（B-202610 属 RankTrend 域消费此三日，不触 theme 域判定）" |
| F3 | 中 | "9 月恢复 78-88%"中 88% 无出处（78% 为 findings daily 口径；88% 为 half_hour 抽样另一口径），且 78% 缺失 22% 恰近自设 >20% 降级线未说明 | **已修**：双口径分开标注 + 边界关系如实披露 |
| F4 | 轻 | S4 括注"日计数 p50=3/p75=7/max=15"漏"正值段"限定（全样本 p50=0） | **已修**：补"正值段"+ >0 占 8.4% |
| F5 | 提示 | trend.py 注释"三处硬编码"（按位置）vs 文档"六消费点"（按比较点）计数口径并存 | **已修**：统一为"七处比较点（trend.py 1 + backtest_service 6，I-3 后）" |

审计确认一致项：参数名/payload 键/函数名全部与代码相符；四组 Mongo 统计精确复现（245/245、99.30%、n=12462/8.35%/p50=3/p75=7/p90=10/max=15、125034 行/509 帧/56 交易日）；tw1/tw2/T 窗口自洽；三文档（总方案桥接/phase4 §3/设计文档 §10）数字与状态一致；S1-S4 通道标注与代码事实相符（gating 参数不走 ThemeTrendConfig；optimizer 无执行层）。

## 4. 验证

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/ -q -k "theme or rank_ic or optimization"   # 564 passed
```

golden v15 未 bump（注：golden 断言 factors/exposures；信号层零漂移由 known-answer 与逐位一致用例钉住）。修复后全仓 `rg "crowding >= 75|crowding < 75"`（backtest_service + trend.py）归零。

## 5. 审查方式披露

双 subagent 经 pi CLI 非交互拉起，审查者与实现者上下文隔离（仅共享需求文档指针与事实性实现描述，未共享实现推理过程）；只读约束经 `--exclude-tools edit,write` 强制。两报告结论独立形成后由主代理统一处置，处置记录见 §2/§3。
