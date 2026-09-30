# 分相位验收设计与实施计划——对抗性审计报告

**审计对象**：
- `ranktrend-phase-acceptance-design.md`（设计，2026-09-30）
- `ranktrend-phase-acceptance-plan.md`（实施计划，2026-09-30，commit b6ef9eaa）

**审计方式**：文档声明逐条对照仓库实测——git 历史（3ba3c8b3 等）、`config/ranktrend-observation-pool.yaml`、`config/ranktrend-anchors.json`、L1 台账与长测文档锚点文本、`t6-runs-formal/{1,2}-summary.json` 字段级核对、frames gzip（`exit-frames-...-20260327-20260930.json.gz`）流式结构统计、Mongo `hotlist_sentiment` 只读 count/distinct、`track1_lifecycle_gate_trade.py` wrxpf 口径核对、计划内嵌代码与内嵌测试的静态推演。全程只读，未改任何源码与数据。

**审计日期**：2026-10（设计/计划定稿于 2026-09-30，B-202610 收官同日之后）。

---

## 0. 总体判定

**设计文档**：方向与纪律框架成立（分相位双线北极星、失败分支为正式产出、诚实边界、资源纪律保留），与项目硬约束（golden 不动、只读、一次一候选落默认）无冲突。**有条件通过**——需修正引用失准与文档体系同步缺口（I5/I6）。

**实施计划**：**不通过，需修订后再执行**。四项 Critical 发现中，C1（计划内测试必然失败）与 C2（54 笔口径断裂）直接证明计划内代码与 Expected 从未实际运行验证；C3/C4（编辑锚点失准）会让 Phase 0 封存在第一步就卡住。计划的"验证总表"（4+4+3 passed、54 笔切片、观察池 rg 无输出）三处 Expected 与实测不符——按 verification-before-completion 纪律，这些数字就是本计划的验收线，目前全部不可达或失真。

| 级别 | 数量 | 编号 |
|---|---|---|
| Critical（阻断执行或结论失效） | 4 | C1-C4 |
| Important（削弱结论效力，须修） | 7 | I1-I7 |
| Minor（建议项） | 10 | M1-M10 |

---

## 1. Critical 发现

### C1. Task 6 计划内测试 `test_monthly_discrimination_requires_two_months` 必然失败——计划代码与计划测试自相矛盾

**证据**（均为计划文档内嵌代码，静态推演）：

实现（`monthly_discrimination`）：
```python
if len(a) < 2 or len(b) < 2:
    continue
```

测试数据：2026-05 月 offense=2 天（05-04/05-05）、defense=1 天（05-06）→ `len(b)=1 < 2`，整月被 `continue`；2026-06 月 offense=1 天（06-01）、defense=2 天（06-02/06-03）→ `len(a)=1 < 2`，整月被 `continue`。两个月都不产出行，`rows == []`，断言 `len(rows) == 2` 与 `all(r["offenseMean"] > r["defenseMean"] ...)` 必然失败。

**影响**：
- Task 6 Step 4 "Expected: 3 passed" 不可达；验证总表"4+4+3 passed"错误。
- 直接证明计划中"最小实现+测试"没有经过一次真实运行——TDD 计划的红绿循环是纸面的，其余两份测试代码（Task 3/5）的可信度同样需要打折（本审计静态推演它们可以过，但执行时仍须真实跑）。
- 附带 fail-visible 违规：月度样本不足被静默跳过，报告不记录"哪些月因 n<2 缺席"，若所有月都跳过，`discriminationH1` 为空数组且无结构化原因。

**修法**：测试数据改为两侧各 ≥2（如 05 月加一天 defense、06 月加一天 offense）；实现补"跳过月份清单"输出；或门槛降为两侧各 ≥1 并披露 n。

### C2. "54 笔交易"与代码实际消费数组不一致：`trades` 65/61 行 vs `tradeCount`/`roundTripTrades` 54

**实测**（`data/reports/b-202610/t6-runs-formal/`）：

| 文件 | tradeCount | len(trades) | len(roundTripTrades) | openPositions |
|---|---|---|---|---|
| 1-summary.json | 54 | **65** | 54 | 4 |
| 2-summary.json | 54 | **61** | 54 | 3 |

设计 §5/§7.3 与计划 Goal/Task 5 测试注释/Task 5 Step 4 Expected/验证总表全部以"历史全窗 54 笔"为研究事实；但 `phase_trade_slice.main()` 消费的是 `.get("trades")`——1-summary 实际 65 行。54 对应的是 `roundTripTrades`/`tradeCount` 口径（两文件同为 54）。

**影响**：
- Task 5 Step 4 Expected "stdout 打出 54 笔的三候选切片"与代码行为（65 笔）直接矛盾；
- 两个数组口径不同（65 行 trades 含 exit 分片/强平等记录），wrxpf/胜率切片读数取决于用哪个数组——M1 交易层方向证据的样本口径未定义；
- 设计 §7.3 "54 笔切片后每相位 20-40 笔"的样本推算随之失真。

**修法**：明确消费 `roundTripTrades`（与"54 笔"口径一致）或改口径声明为 65/61 并解释两者差异；Expected 数字同步修正。

### C3. Task 2 Step 1 编辑锚点不存在：`# 一级参数台账` 标题在实际文件中不存在

**实测**：`ranktrend-l1-param-ledger.md` 首个标题行为 `# RankTrend L1 自由参数定值档案`。计划指示"在 `# 一级参数台账`（首个标题行）之后插入"——锚点文本不存在，执行者要么停下要么自由发挥，封存注记落位不可控。

**修法**：锚点改为实际标题 `# RankTrend L1 自由参数定值档案`。

### C4. Task 2 Step 3 替换串与 §27.9 实际文本不匹配（缺 `**` 粗体标记）

**实测**（长测文档 L3564）：实际文本为 `产出 **B-202611 阶段计划**：\`ranktrend-b-202611-plan.md\`（同目录）`；计划给出的替换目标是 `B-202611 阶段计划：\`ranktrend-b-202611-plan.md\`（同目录）`（无 `**`）。精确文本替换（edit oldText）会因不匹配而失败。

**修法**：按实际文本（含 `**`）重写替换串；执行时先 `grep -n` 确认。

---

## 2. Important 发现

### I1. `lag_check` 滞后性检验的语义与设计判据方向相反，且测不出真正的"滞后"

代码计算的是 `corr(相位(d), 收益(d+lag))`，lag∈[0,5]。按互相关惯例，argmax>0 表示**相位领先收益 lag 步**（对实盘恰恰是有预测价值的属性）；而代码注释与 `acceptable = best <= 3` 把 argmax>0 解释为"相位落后于收益（坏）"。真正的"相位落后于收益"（坏属性）对应负 lag（corr(相位(d), 收益(d−k)) 最大），代码根本没有计算负 lag。后果：

- 设计 §5 出口判据"相位切换滞后收益拐点 ≤3 交易日，实盘可跟随"这一关，实现既测不出要测的东西，又可能把最有预测力的领先相位误判为不合格；
- 注释称"次日收益序列"，实际 `ys.append(rets[d0])` 是当日收益——文档内自相矛盾；
- lag 单位是"有效样本步"而非交易日（跨周末、缺档日失真）；
- `corr` 不看显著性：相位与收益负相关（反指）时各 lag 相关均负，argmax 随机落位，`acceptable` 可能仍为 True。

**修法**：改为对称 lag 区间（如 −5..+5）的互相关，明确 argmax 符号的语义映射（负=相位滞后、正=相位领先），并加相关强度/显著性门槛；或按设计本意直接检测"收益拐点 vs 相位切换"的时间差。

### I2. `monthly_discrimination` 的 `pass` 判据缺方向检查

设计出口判据要求"好相位 forward return **高于**差相位……且方向在 ≥2 个独立月份一致"。实现 `pass = (p < 0.05) or (abs(ma - mb) >= 0.02)`——只看绝对差，offense 均亏 3%、defense 均赚 3% 的月份同样 `pass=True`。且不产出"方向一致月数"汇总，"≥2 独立月份方向一致"无自动支撑，全靠人工读表（Task 7 人工判读可补救，但自动字段与判据背离）。

**修法**：`pass` 增加 `ma > mb` 方向条件；报告补 `directionConsistentMonths` 汇总字段。

### I3. 区分度检验的样本层与设计声明不符：设计承诺"信号层百万级样本"，实现是日级 ~113 样本

设计 §7.3："区分度主证据用信号层百万级样本，交易层只做方向确认"。实现 `daily_forward_returns` 每日输出 1 个池等权收益，`monthly_discrimination` 按月分组每月约 20 个日样本——帧级（1073 帧）与股票级（~25 万行）样本完全未被使用。在 n≈20/月的日级样本上，p<0.05 判据的统计效力远低于设计声称，M1 出口判据与实现脱节。

**修法**：要么实现帧级/股票级前向收益检验（贴合设计承诺），要么修订设计 §7.3 的样本量声明并解释降级原因（如日级聚合是为抑制帧间自相关——这本身是合理理由，但必须写出来）。

### I4. Task 1 Step 1 的 rg 检查 Expected 错误：实测有 2 处命中

`rg -l "observation-pool" backend/ scripts/ tests/` 实测命中：
- `tests/research/test_track2_candidates_harness.py:48`（docstring 提及"observation-pool O2 baselineNote"）
- `backend/operations/scan_repool_sample_floor.py:5`（注释提及观察池路径）

两处均为文档性引用，无任何代码解析该 YAML——计划的语义结论（"B-202610 批次为人工执行，无 runner 解析此文件"）成立，但 Expected"无输出"错误，且计划规定"若有输出，停下向用户报告再继续"——执行者会被迫无谓停机。

**修法**：Expected 改为"仅注释/docstring 命中可放行；若发现解析消费（yaml.load/读取该路径）才停"，或改用更精确的检查（如 `rg -l "ranktrend-observation-pool.yaml" backend/ scripts/` 并逐条人工确认非解析用途）。

### I5. 帧数据事实偏差：实际 1073 帧/120 交易日（含 7 个无情绪文档日、非标槽与日线回填合成帧），非"1071 帧全窗"

实测（frames gzip 流式统计）：
- 帧级 `marketStats` 计数 = **1073**（计划称 1071）；
- distinct tradingDate = **120 日**（04-15 → 09-30）；文件名"20260327"是数据集窗口参数，实际首帧 2026-04-15，且早期帧 `captureMode=synthesized / source=cross_type_backfill`（由 daily 快照回填合成，donor 元数据在 `marketContext.metadata.backfill`）；
- Mongo `hotlist_sentiment` half_hour 口径 1184 文档/113 日（04-15 起，全部含 `emotionScore.score`）——**120−113=7 个交易日有帧无情绪文档**，sentiment 候选在这 7 日（约 60+ 帧）会打 unknown；
- 存在非标准槽（股票行级 09:03/12:35/13:44/14:27/14:31/15:30），帧分布不均匀；
- 无 `slotTime="EOD"` 帧（EOD 计数 0）——`daily_forward_returns` 取"最大 slotTime"为末槽不会被 EOD 干扰，这点计划是安全的。

**影响**：
- Task 4 Step 2 Expected"unknown 帧仅限 04-15 前不存在——实际 04-15 起全覆盖应为 0 或极少"不成立：04-15 前根本没有帧，unknown 实际来自中段 7 个缺文档日；
- Task 4 Expected"各 1071 帧计入"数字错（1073）；
- h1=+1 帧、h8=+8 帧在非均匀帧分布下不严格等于"次日首槽/次日同槽"（Expected"h8 相应少 1 日"过度简化）；
- 回填合成帧的 `emotionValue`/`price` 与真实 half_hour 槽的可比性未披露——设计 §7.4 只披露了"情绪评分覆盖 113 日短于全窗"，未披露"帧侧早期是 daily 回填"这一对称事实，诚实边界有缺口。

**修法**：数据事实表更新为实测值（1073 帧/120 日/7 缺档日/合成帧披露）；M1 报告诚实边界模板补两条（合成帧可比性、7 缺档日 unknown 分布）。

### I6. 封存动作清单缺"SKILLS.md 与 skill 正文的同步"——封存后文档体系自相矛盾

设计 §4/§5 宣布"取代旧长测体系的月度批次模式（阶段 0-27 + B-202610 范式）"、废除判定卡五条件自动收口/观察池状态机/锚代际推进仪式/L1 复核登记/月度批次三件同步。但：

- 根 `SKILLS.md` §2.4（ranktrend-signal-research）仍规定"月度复验按批次方案先行（范例 `ranktrend-202610-rerun-plan.md`），不再单点开批"，统一收口流程仍是现行纪律；
- `skills/ranktrend-signal-research/SKILL.md` 正文同样以批次模式为现行章程；
- Phase 0（Task 1/2）只封存观察池 YAML、L1 台账、长测文档三处，无 SKILLS.md/skill 正文更新动作。

封存执行后，skill 层会继续驱动一个已被官方废除的月度批次模式（下次任何 agent 按 SKILLS.md §2.4 行事就会违背本设计）。另：SKILLS.md 写"阶段 0-26"（现为 0-27），本就需要随封存一并校正。

**修法**：Phase 0 增加 Task：更新 `SKILLS.md` §2.4 与 `skills/ranktrend-signal-research/SKILL.md`——保留参数化/锚/golden/资源纪律等仍然有效的条款，将月度批次三件同步、判定卡唯一收口、观察池状态机标注为"已被分相位验收体系取代（2026-09-30），见设计文档"，并登记新体系的 fail-visible/标签重打纪律。

### I7. 交易层切片的日级众数标签存在轻微前视偏差，未在诚实边界披露

`dailyByMajority` 用全日帧众数（含 15:00 末槽）定型当日相位，而 `slice_trades` 把它 join 到 `entryTradingDate`——入场可能发生在日内任意槽（如 10:30），等于用"日末才可知的信息"标注"日中入场"。M1 作为方向性验证可容忍，但 `phase_labeler` docstring 声称"as-of 无未来函数（只消费当前帧及之前可得数据）"与该用法冲突，且 Task 7 报告模板的诚实边界未含此条。**修法**：报告模板补披露；或改用"入场前帧的众数"（entryTime 可定位入场槽，帧级标签现成）。

---

## 3. Minor 发现

| # | 发现 | 说明与建议 |
|---|---|---|
| M1 | `wrxpf_of` 的 `float(t.get("netReturn") or 0)` | None→0 静默伪装缺失（违反 fail-visible"缺失保持缺失"）。本次实测 54/65 笔 netReturn 均非空，风险未兑现；建议缺失计数进读数或在 join 时剔除并标注 |
| M2 | 手工 `mannwhitneyu` 无 tie 校正 | 等权池日收益可并列（尤其合成帧同价）；p<0.05 是出口判据线，边界样本可能翻判。建议补平均秩+tie 校正，或确认 .venv 有 scipy 后直接用 `scipy.stats.mannwhitneyu` |
| M3 | `phase_label_run` 产物无溯源元数据 | 本地易失 JSON 建议自描述：datasetId/snapshotType/frames 文件名+帧数/生成时间/git commit，便于月度监控对账 |
| M4 | Mongo 直连硬编码 `mongodb://127.0.0.1:27017` | operations 已有硬编码先例（`wechat_info_diff_ingest.py`、`jev_label_driver.py`），不算偏离惯例；只读直连 `dragon_board_quant` 符合设计 §7.6"不占 8000 队列"。可选改走 settings |
| M5 | 计划"范围裁定（设计文档 §6）"引用失准 | 设计 §6 是"文档体系"；范围/里程碑裁定实际在 §5 与文首"取代"声明 |
| M6 | Task 3 测试未覆盖平票分支 | `daily_phase_from_frames` 注释宣称"平票取更保守（defense 优先）"，`_TIE_BREAK` 实现正确，但测试数据（2:1）不触发平票路径——补 offense/defense 1:1 平票用例 |
| M7 | 计划头部 REQUIRED SUB-SKILL 引用 | `superpowers:subagent-driven-development` 未在项目 SKILLS.md 登记；项目 e2e 验收另有"主代理单线程"纪律。不阻断，执行时按项目实际可用技能裁剪 |
| M8 | 情绪文档数 1184 vs AI_COLLABORATION 的 1182 | 1182 为全量重算时点数，其后新增 2 文档至 1184；非错误，但两处数字漂移建议在 M1 报告引用时注明时点 |
| M9 | 设计 M2 引用 `evaluate_gate` 底座 | 实测 `evaluate_gate` 仅定义于 `backend/operations/optimize_gate_denoise_parameters.py`（非公共 harness 库）；`track1_lifecycle_gate_trade.py` 存在。M2 立项时需核实复用面是否如设计预期，属 M2 期风险登记项 |
| M10 | gen7/锚名一致性 | 设计"gen7=当前引擎默认基准"与计划/实测 `currentGeneration=gen-2026-09-30-midlong-x30`（第七代三参组合锚，git 9ca651e1/9f96c9f）一致，无冲突；仅记录核实结论 |

---

## 4. 合规性核对（对照 AGENTS.md / AI_COLLABORATION / fail-visible / TDD / 单一事实源）

| 项 | 判定 | 说明 |
|---|---|---|
| Golden 不动、引擎/config 零改动 | ✓ | 计划声明并保持"全程只读"；M1 全部新建文件，无引擎触碰 |
| 目录归档（operations/tests/research） | ✓ | 与现有 `backend/operations/` harness 惯例、`tests/research/` 现存测试模式（含 `sys.path.insert(parents[2])`）一致 |
| 生产/测试库边界 | ✓（附注） | M1 脚本只读直连 `dragon_board_quant`（CLI，非 pytest），不触 conftest 的 `dragon_board_test` 护栏；无写操作 |
| fail-visible | 部分 | unknown 相位不伪造 ✓、切片 unknown 桶保留 ✓；但 C1 跳月无痕、M1 netReturn or 0、I5 缺档日 unknown 分布未披露 |
| TDD | 形式 ✓ / 实质受损 | Task 3/5/6 有红绿循环与就近测试；但 C1 证明计划代码未真实运行过，Expected 数字不可信 |
| 一次一候选落默认、优化结果不自动写回 | ✓ | 设计纪律保留条款明确；M1 不产参数写回 |
| 单一事实源 | ✓ | 消费 Mongo `hotlist_sentiment`（后端事实源）与后端回测产物，不新建双源；标签 JSON 是研究衍生品 |
| 资源纪律（串行/不占 8000/frames 本地化） | ✓ | 复用 B-202610 本地 frames gzip，Mongo 只读，无 optimization 队列占用 |
| 文档体系同步（AI_COLLABORATION §文档维护规则） | ✗ | I6：封存未含 SKILLS.md/skill 正文同步，体系自相矛盾 |
| Git 纪律（明确路径 add、逐任务 commit） | ✓ | 计划 commit 步骤均 `git add <明确文件>`，符合 AGENTS §1 |

---

## 5. 事实核查表（文档声明 vs 仓库实测）

| 声明（出处） | 实测 | 判定 |
|---|---|---|
| b-202611 计划已删，git 3ba3c8b3 留档（设计 §4） | commit 存在且即 B-202611 制定；文件已不存在 | ✓ |
| 观察池 9 项 in_default（计划 Task 1） | `grep -c "status: in_default"` = 9 | ✓ |
| 观察池三组 sealedNote 覆盖 31 条目（计划 Task 1） | 实际 31 个 `id:`，逐一比对全部在计划清单内 | ✓ |
| L1 台账标题 `# 一级参数台账`（计划 Task 2） | 实际 `# RankTrend L1 自由参数定值档案` | ✗ C3 |
| §27.9 替换串（计划 Task 2 Step 3） | 实际文本含 `**B-202611 阶段计划**：`（粗体） | ✗ C4 |
| 长测文档标题 `# 四维信号长期回测计划与性能优化方案` | 一致 | ✓ |
| 锚 `gen-2026-09-30-midlong-x30`（计划 Task 2） | `currentGeneration` 一致 | ✓ |
| 情绪 1184 文档/113 日/自 04-15（计划数据事实表） | count=1184、distinct 113 日、min=04-15、1184 全含 score、EOD=113 | ✓（M8 注记） |
| frames 1071 帧全窗（计划） | 帧级 marketStats 计数 1073；120 交易日；首帧 04-15（文件名 20260327 为窗口参数） | ✗ I5 |
| 帧自带 `marketStats.emotionValue`（如 −0.0115） | 首帧实测 −0.011506…，字段存在 | ✓ |
| stocks 行含 `code`/`price` | 实测样例 `"code": "600105"`, `"price": 37.51` | ✓ |
| frames 无 EOD 槽 | `"slotTime": "EOD"` 计数 0 | ✓ |
| trades 带 entryTradingDate/entryTime/regime/netReturn | 1-summary 全 65 行四字段零缺失 | ✓ |
| regime 四桶 | 实测枚举 weak=31/retreat=15/normal=11/strong=8 | ✓ |
| 历史全窗 54 笔交易 | tradeCount=roundTripTrades=54；trades=65/61 | ✗ C2 |
| wrxpf = winRate × profitFactor 口径 | `track1_lifecycle_gate_trade.py:58` 一致 | ✓ |
| `track1_lifecycle_gate_trade` 底座存在 | `backend/operations/track1_lifecycle_gate_trade.py` 存在 | ✓ |
| `evaluate_gate` 底座存在 | 仅 `optimize_gate_denoise_parameters.py` 内定义 | ~（M9） |
| rg observation-pool 无输出 | 2 处 docstring/注释命中 | ✗ I4 |
| Python 3.13 | .venv 3.13.12 | ✓ |
| tests/research/ 目录与测试模式 | 已存在，模式一致 | ✓ |

---

## 6. 修正建议（按优先级）

**执行计划前必须修（对应 Critical）**：
1. C1：修 `monthly_discrimination` 测试数据或门槛逻辑，补跳过月披露；全计划三份内嵌代码先在本地真实跑一遍红绿再定稿（这是对"计划内代码必须已验证"的最低要求）。
2. C2：裁定交易层数组口径（建议 `roundTripTrades`=54，与文档口径一致），同步修 Task 5 代码、测试注释与全部 Expected。
3. C3/C4：修正两处编辑锚点为实际文本。

**执行计划前应当修（对应 Important）**：
4. I1：滞后性检验改为对称 lag 互相关或拐点对齐检测，修正方向语义与 acceptable 判定。
5. I2：`pass` 加方向条件，补方向一致月数汇总。
6. I3：实现帧级/股票级区分度检验，或在设计中明示降级为日级样本并说明理由。
7. I4：rg 检查 Expected 改为"注释命中放行、解析消费才停"。
8. I5：数据事实表更新为 1073 帧/120 日/7 缺档日，披露合成帧；Task 4 Expected 同步修正。
9. I6：Phase 0 增补 SKILLS.md §2.4 与 skill 正文的封存同步任务。
10. I7：报告模板诚实边界补"日级众数标签对日中入场的前视"。

**可选改进（Minor）**：M1-M10 按上表逐项处理；M1（netReturn or 0）与 M2（tie 校正）建议随 Critical 一并修，成本低。

**设计文档侧**：修正 M5 引用失准；在 §7 诚实边界补 I5/I7 两条；M9 登记进 M2 立项前置核查清单。

---

## 7. 审计边界与未验证项

- 未实际执行计划内任何测试/脚本（审计为只读静态推演 + 数据实测）；"测试必然失败"的结论基于确定性静态推演（C1 的分支行为无随机性）。
- 未逐行核对 `track1_lifecycle_gate_trade.py` 的 win/pf 细部口径与计划 `wrxpf_of` 的完全等价性（仅核对 wrxpf=winRate×pf 主公式）。
- 未验证 .venv 是否安装 scipy（M2 建议的前置）。
- 未审计 2-summary.json 与 1-summary 的 run 差异语义（t6 两个 run 的用途），仅确认两者 tradeCount 同为 54。
- Mongo 查询为只读 count/distinct，未做任何写操作；frames gzip 为流式读取，未落任何产物。
- 本报告未修改设计/计划原文；按 AI_COLLABORATION"文档任务只改 docs"边界，所有代码级修正建议均指向"修订计划文档"而非直接改码。
