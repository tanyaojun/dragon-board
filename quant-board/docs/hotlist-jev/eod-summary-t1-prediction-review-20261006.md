# 验证档案：subagent 对抗性审查 + 数据资产盘点与 TDX 补齐（2026-10-06）

> 触发：用户对 v1 结论保留意见，裁定「subagent 分别做 code review 与数据资产盘点（mootdx 5 分钟线补齐），然后分季度复跑」。
> 本文档归档两个 subagent 的报告全文要点与产物位置；复跑结果见 `eod-summary-t1-prediction-report.md`（v2）。

## 一、代码审查（subagent A，对抗性+独立复算）

**总判定：站得住（4 项 P1，均不动摇结论方向）**。脚本复跑与报告 14 组核心数字逐一相符；统计实现与 scipy 交叉验证零误差；无前视、无幸存者偏差。

### P0 判定点：amount 语义（实测确认累计额，C9/C9b 公式成立）
抽 08-20/09-29 两日四帧全部股票实测：单调不减违反 0 只；15:00/09:30 均值比 4.0/86.1（分槽语义应 ≈1）。

### P1 发现（全部已在 v2 复跑中处置）
| # | 发现 | 实测证据 | 处置 |
| --- | --- | --- | --- |
| P1-1 | H1 条件②阈值「≤−5%」在比率单位（pm/am−1，基线 −0.455）下 **49/49 永真**，H1 实际二条件驱动 | amount 窗 49 日 C9 分布：中位 −0.50、max −0.32 | 修订 3 重定标：②改 C9m（对昨日半场比值差，居中 0），另附分位数式读法 |
| P1-2 | C9/H1 实际窗口 07-14 起 49 日，宽于冻结的 8-9 月口径未留痕；C9 vs Y6 宽窗 +0.30 → 冻结窗 +0.041（窗口敏感） | 冻结窗复算 | 扩窗后 C9-Y6 全窗 +0.11 n=98，标注窗口敏感 |
| P1-3 | 07-21 全帧零额伪值（13:00/15:00 帧 197/214 行 amount=0）穿透覆盖门，主表 6 格带伪极值点（C9=−1.0） | 帧级实测 | 覆盖门改「0/负不算有效」；07-20→07-21 对用 TDX 个股 5 分钟线修复（n=227，Y4 −0.75%/Y5 +3.49%/Y6 3.1%） |
| P1-4 | 偏相关两套窗口不公允（C6 全窗 +0.064 → amount 窗 +0.211），给了 C9b 不公平优势 | 同窗复算 | v2 偏相关统一同窗（n=98）：全部 \|partial ρ\|≤0.091 |

### P2 发现（已处置/留痕）
- 多重比较计数依赖共享 rng（22/60 独立 seed 下为 23/60）→ v2 每格独立 seed。
- 预登记家底数勘误：EOD 132=全 snapshotType 混计（half_hour=113）；同槽多文档/5 分钟细槽在其它 snapshotType 下，half_hour scope 无重复（去重逻辑为无害防护）；9-11 精确相等占比 99.4%（100% 的是 08-10）。
- 价格靶 sid 全或无白丢 07-03/07-22 → v2 按靶放宽 + snapshot_frames 兜底（找回 10 帧）。
- 报告措辞：Y5 列 ρ 范围实为 −0.14~+0.18（「0.11~0.15」不准）；「方向转正」应为「强度约 3 倍」（4-6 月本就 +0.067）；C7 与 C1 是中等相关（ρ=0.574）非高度共线。
- 交易日历桥接风险：07-08/07-10/07-24 三个非假日 weekday 零文档（采集停摆嫌疑），当前 0 配对实际受损，v2 加守卫披露。
- 审查产物：`quant-board/.tmp_review/review1..7*.py`（独立验证脚本，保留可复跑）。

## 二、数据资产盘点与 mootdx 补齐（subagent B，全程只读）

### 盘点
- **槽位缺口**：59/1130 槽无文档（有文档无分 0 例），10 个缺口日；其中 49 槽**原料帧也不在**——池级情绪分 mootdx 无法补（情绪引擎链路产物，非数据回填范畴）；04-15 的 9 槽与 07-06 15:00 帧行在（10 帧已由 sid 兜底找回用于价格靶）。
- **字段矩阵（15:00 帧 ≥80% 行覆盖）**：price 110/113 全窗；amount 仅 07-13→09-30（56 日）；**turnover 110/113 全窗且与 amount 逐行全等**（复跑实测 120676/120676）——等价前推成立；pctChange 真缺口仅 07-01/02/03。
- **现成市场级源**：hotlist_jev_sentiment totalAmount 仅 07-01 起且 9 月曾被重算冲掉（**2026-10-06 已根治**：market_daily_amount 参考集合=单一事实源 + collect_slot_evidence 15:00 槽回退，replace_one 重算不再丢锚量能坐标，9 月 20 文档已恢复 59/59 有效）；marketStats.totalAmo 4-6 月全旬有值但 23/71 日低估 3-36%（只配粗参照）。
- **帧级 indices.totalAmount**：仅 09-30 接线日，其余全缺。

### 补齐产物（`quant-board/data/backups/eod-t1-backfill/`，gitignored）
- `index_5min_daily.json`：TDX 上证综指 999999+深证综指 399106 5 分钟线派生，116/116 交易日（04-15→09-30）两市 AM/PM/total 成交额+指数开/收/昨收；与 jev 回填 39/39 ±2% 一致、09-30 indices 对账 1.4%。
- `stale_days_repair.json`：7 个前收价污染日 627/631 股修复（4 只 920xxx 北交所不支持+2 停牌如实列缺）；修复后真相分化：08-12 实为高开 +1.11%、08-28 实为低开 −1.86%（污染时全为 ≈0）。
- `zero_day_0721_repair.json`：07-20→07-21 零额帧对修复（本档案整合阶段补跑），n=227，Y4 −0.75%/Y5 +3.49%/Y6 3.1%，TDX/Mongo 收盘核对 225/227。
- 可复跑脚本与盘点明细同目录（`backfill_index_5min.py`、`repair_stale_days.py`、`repair_zero_day_0721.py`、`inventory*.py`）。

## 三、整合复跑（本档案结论指向）

修订 3 复跑（扩窗+修复+重定标）结果见报告 v2：**EOD 保持现任被加强（Y4 +0.32→+0.36），「C9b 缩量→高开砸 +0.40」被扩窗推翻（全窗 +0.08，Q2 −0.04/Q3 +0.20，窗口伪象）**，H1 修正口径后仍样本不足（1/105 触发）。用户保留意见的三个疑点两个坐实（窗口伪象、H1 阈值失义），一个（池缺口可补性）确认为不可补并给出边界。

## 四、7 月前行字段缺口回填处置（2026-10-06 用户令「可回填的都回填」）

**盘点**（half_hour 行，≤06-30，116,549 行）：`open/preClose/high/low/limitUpPrice/amount/moneyFlow` 全 0%，`pctChange` ~31%，`turnover/price/volume` ~97-98%。

**消费方风险扫描后分两类**：
- **已回填（本轮执行，snapshot_row_daily_prices_v1）**：`open`←TDX 日线开盘（无任何计算链消费方）；`preClose`←行内派生（price+change，与投影层生产规则逐字一致，覆盖 ~97%）+ TDX 前收回退（19 行）。写 113,206 行，来源标记 backfillMeta（fail-visible），不建备份集合（只填 NULL 可平凡复原），migration_audit 留痕。交叉核对：派生 vs TDX 前收 93.7% 一致，6.3% 不一致呈标准除权谱（分红送转季，派生=交易所口径更优）。回填后 preClose 回算抽检 3,000 行 0 超差；7 月及以后零误触。
- **~~有意不补~~ → 已补齐并同批重生成（2026-10-06 用户裁决「补，情绪分/时间线重算，深谷/高位点重算」，见 §五）**：~~amount/high/low/limitUpPrice/pctChange~~；唯 `indices.totalAmount`（帧级）仍不补——回填它会给 4-6 月激活 amountVsSame 第八维而 7-9 月帧依旧缺失，评分维度跨月分裂；除非 7-9 月同批回填并重校准全部阈值（C6/C9/C10 均按现口径锚定），否则维持不补。
- **不可补**：`moneyFlow`/盘口（bid1/depth10）/firstZtTime 早段（无历史证据源）。

工具：`backend/operations/backfill_row_daily_prices.py`（dry-run→apply 幂等，TDX 断点缓存 data/backups/row-price-backfill/，156 个北交所/无 K 线代码失败清单已落盘）。

## 五、计算输入补齐+研究基线同批重生成（2026-10-06 用户裁决执行记录）

1. **回填 v2**（`backfill_row_daily_prices.py`，version=snapshot_row_daily_prices_v2）：`high/low`←TDX as-traded 日线 112,944 行、`amount`←turnover（12 万行逐行全等实证）113,018 行、`pctChange`←price+preClose 派生 426 行（**勘误：pctChange 实际仅缺 3.2%（3,769 行），§四「~31%」系盘点把 0.0 平盘行误计为缺失+一次探针查错 snapshotType 帧，两处口径已修正**）。六字段终态覆盖 96.9-97.1%（天花板=price 覆盖）。审计两条补登（apply 进程 stdout 截断+工具撞 (opType,idempotencyKey) 唯一索引，写库完整性由覆盖率核对确认）。
2. **级联派生**：既有 `snapshot_field_backfill`（backup=False 遵红线）→ `limitUp/DownPrice` 97.1%、`amplitude` 96.9%、`lastTradePrice` 99.6%、`zljzb` 100%。
3. **情绪分/时间线重算**：4-6 月 51 个 EOD 文档全部重算（`_compute_and_persist` 生产路径）+500 个槽位文档重建。旧值归档 `data/backups/sentiment-prejuly-recompute/`（NDJSON，mongoexport 不在 PATH，python NDJSON 等价归档）。**变化幅度：分数均值 +4.8（-2.4~+9.5），无 ≥15 分跳变，档位翻转 3 天**（05-21/06-05 退潮→启动、06-17 发酵→启动）。7-9 月分数未触碰（口径连续）。
4. **深谷/高位点重验**：c9/c10 各 6 个月台账全部重建。**新发现 4-6 月深谷两处**：05-14 EOD=29.1（3 日反弹 +26.3 ✓）、06-23 EOD=26.0（+51.4 ✓）——重算前 4-6 月从未低于 30；高峰台账 04-09 全部重建（04/07 无高峰为真实判定）。**研究注记：深谷状态信号（EOD<25/30 阈值族）的 4-6 月历史账本已按新分数重建，既有 runbook 中引用 4-6 月具体分数/谷位的段落为重算前快照**。
5. **golden 重生成**：主用例 `rank_trend_default` 已按回填后全量数据重录（create_baseline，source=python_current_output，100/100），validate **passed（0 issues）**。`rank_trend_default_tmp_no_macd_gate` 为 ts_golden_import 来源的临时用例，**未重生成、当前 validate 失败（预期内）**——处置（删除/重导出）留用户。旧用例已归档 `data/backups/golden-cases-archive-20261006/`。
6. **测试**：hotlist 专项 292 绿（本轮数据/工具变更不触测试路径，测试走 dragon_board_test 隔离库）。