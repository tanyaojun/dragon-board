# Phase R2 实证报告：rotation_regime 阈值化与判定链稳定性定版

- 日期：2026-09-26
- 数据窗：2026-07-06 ~ 09-24（54 个 daily 收盘横截面交易日；7 月仅 15 天在 daily 类型内）
- 代码版本：main `9b6227a9`（runner，含 regime 口径修正）/ `4a3da04a`（mainline_stability）/ `cb1bcca2`（regime）
- 报告产物：`quant-board/data/reports/theme-r2-regime.json`（gitignore，不提交）
- **样本量声明**：54 天探索性描述统计，非正式判定；阈值与平滑配置的正式定版需 R3 收益对照与更多积累。

## 0. 执行摘要

1. **regime 双轴设计需要重构**：默认阈值下 49/53 天落 chaotic，rotating 态在全部 9 组阈值下均为 0 天——rank Top10 口径下 rot（轮动速度）与 entropy（霸榜频率熵）**正相关**（快换手必然多题材进榜→熵高），"快+聚"（rotating）与"慢+散"两个对角象限天然稀疏。entropy_hi 是唯一有效杠杆（0.85/0.90/0.95 → concentrated 0/4/11 天），rot_hi 在 0.60-0.80 完全不敏感。
2. **判定链稳定性定版数据完整，呈现明确的"稳定-收益权衡"**：无平滑 Top3 距离 0.9094 / 超额 +0.0395；window_n5 最稳（0.6509）但超额最差（-0.0040）；hysteresis 略稳（0.8962）且超额最高（+0.0512）；EMA（0.7868 / -0.0432）。滞后即代价：越稳的名单换头越慢。
3. **引擎口径"主线不明"实锤**：rotationSummary.mainLines 空值率 **79.5%**（39 个 half_hour 15:00 帧中 31 天引擎判定无主线）；引擎 rotationState=mainline 仅 8 天，与判定链 Top3 的 Jaccard 相似度仅 0.1667——两套 mainline 口径严重分歧。
4. regime × market_phase 联合分布**部分支持修正假设**：concentrated 4 天全部落在 cooling 相位（慢轮动+集中↔退潮 ✓）；但 cooling 相位下 24/39 天仍是 chaotic——**退潮 ≠ 慢轮动**，退潮期题材换手依然很快，"弱"体现在赚钱效应而非名单换手。
5. MainlineScore Top1 的按月切换率 0.88-0.93（全程几乎日日换），与 rank 口径 Top1 的 9 月切换率 0.294（AI硬件霸榜）形成鲜明对照——判定链排序与热度 rank 排序是两套分歧巨大的"主线"定义，接线前必须先回答"信号层用哪一套"。

## 1. 判定链稳定性 × 次期收益（双指标四配置）

| 配置 | Top3 距离↓稳 | Top1 切换率↓稳 | max 名单长 | T+1 超额 | 胜率 |
|---|---|---|---|---|---|
| none（无平滑） | 0.9094 | 0.9057 | 3 | **+0.0395** | 0.5094 |
| ema_a05 | 0.7868 | 0.8113 | 3 | -0.0432 | 0.4717 |
| window_n5 | **0.6509** | **0.5283** | 3 | -0.0040 | 0.4528 |
| hysteresis_k3_exit5 | 0.8962 | 0.9057 | 4 | **+0.0512** | 0.5094 |

（距离=1−Jaccard 相似度，越低越稳；超额=Top3 等权 T+1 change −全题材等权 T+1 change，n≈53）

- **none 距离 0.9094 与 R1 相似度 0.0906 精确互补**（1−0.0906），两阶段口径互洽。
- **平滑-收益权衡**：window_n5 把切换率从 0.91 压到 0.53，代价是超额从 +0.04 转负（滞后换头错过新主线）；hysteresis 以最小稳定化代价保住最高超额——**滞回的"只松进不让出"结构在收益上最优**，与游资"龙头不轻易下车"的经验一致，但 0.051/天的超额在 53 天样本上无统计显著性，不能据此定版。
- **定版提案**（一次一候选）：R3 用 hysteresis_k3_exit5 作为唯一候选进收益对照（敏感性参数 k/exit_rank 扫描另批），window_n5 保留为对照臂；EMA 不推荐（稳定性中等且收益最差，滞后与平滑双重缺点）。
- maxlen=4（hysteresis）验证了"缺分保留名单可超 k"的诊断项有效；本窗无数据中断日，未出现极端膨胀。

## 2. rotation_regime 阈值化

### 2.1 默认阈值（rot_hi=0.70 / entropy_hi=0.90）下的逐日分布

- chaotic 49 / concentrated 4 / rotating 0；切换 chaotic→concentrated ×2、concentrated→chaotic ×1。
- concentrated 集中在 9 月中下旬（9-15/16、9-23/24）——与 R1"9 月下旬收敛"的方向一致，但**9 月 18 天中仅 4 天**被判集中。
- 9 月大部分天仍 chaotic 的机理：rank Top1（AI硬件）虽稳定，但 Top2-10 次级题材换手极快（10 日窗口内 40+ 题材进过榜→频率熵 0.96>0.90）——**"主线集中"只体现在 Top1，Top2-10 层面仍快轮动**。三态的两轴无法捕捉"头部稳定+腰部快轮动"这种市场结构。
- **MainlineScore 口径诊断**（附加输出）：53 天全部 chaotic——判定链 Top3 日日换血（距离 0.91 饱和超阈值），进一步证明它不能作 regime 输入。

### 2.2 3×3 阈值敏感性

| entropy_hi \ rot_hi | 0.60 | 0.70 | 0.80 |
|---|---|---|---|
| 0.85 | 全 chaotic | 全 chaotic | 全 chaotic |
| 0.90 | 49/4/0 | 49/4/0 | 49/4/0 |
| 0.95 | 42/11/0 | 42/11/0 | 42/11/0 |

（格式：chaotic/concentrated/rotating 天数）

- **entropy_hi 是唯一杠杆**；rot_hi 三档结果完全相同——entropy<0.85 的天数为 0，而 concentrated 的约束瓶颈在 entropy 轴，这些天的 rot 全部 <0.60，rot_hi 阈值失去作用。
- **rotating 全组 0 天是结构性发现**：rank Top10 口径下 rot 与 entropy 正相关（快换手⇔多题材进榜⇔熵高），"快+聚"对角天然稀疏。**双轴 regime 的设计前提（两轴独立刻画轮动）不成立**，三态中 rotating 形同虚设。
- **R3 重构方向提案**（不在本轮实施）：rot 轴改为 Top1 稳定性（rank Top1 连续天数）或 mainlineConcentration（引擎已有），entropy 轴保留频率熵——两轴相关性才会下降；或直接用引擎 rotationState 六值 + market_phase 做状态空间，避免自造第三套状态体系（single-source-of-truth 三问）。

## 3. regime × market_phase 联合分布（half_hour 15:00 帧口径）

| regime \ marketPhase | cooling | chaos | rising | climax | falling | None |
|---|---|---|---|---|---|---|
| chaotic（49 天） | 24 | 7 | 2 | 1 | 1 | 14 |
| concentrated（4 天） | 4 | 0 | 0 | 0 | 0 | 0 |

- concentrated 4 天全部 cooling——**修正假设"慢轮动+集中↔退潮"在该方向上成立**；
- 但反向不成立：cooling 相位下 24/39 天（62%）仍是 chaotic——**退潮期题材名单换手并不慢**。市场相位（情绪）与轮动速度是两个低相关维度，设计文档 §5.3 的双维门控中两者应独立采集而非互相推导；
- marketPhase 的 daily 帧恒 unknown（37/43）、真值只在 half_hour 15:00 帧（53 帧覆盖）——数据口径事实已固化在 runner。

## 4. 引擎口径对照

- **mainLines 空值率 79.5%**：引擎的 mainline 判定（热度 z-rank Top3 ∧ 资金集中度 Top3 双 Top3 门槛）在 54 天里 31 天判定"当日无主线"——用户"主线不明"的体感在引擎口径得到量化证实，且这是全程现象而非弱势段特有。
- 引擎 mainline 天（8 天）与判定链 Top3 的重合度仅 0.1667——引擎 mainline 要求"热度 ∧ 资金集中度"双 Top3（门槛高、名单小），判定链 Top3 是 MainlineScore 单分序（门槛低、日日换）。**两套口径回答的不是同一个问题**：前者是"严格意义的主线是否存在"，后者是"合成因子的前三名"。R3 设计轮动补涨信号（SG2）时必须明确消费哪一套，不得混用。
- rotationState 六值（cooling/emerging/inflow/mainline/neutral/outflow）仅落 half_hour；题材级 rotationState 在 daily 类型全缺（0/13,433）——日频消费 rotationState 需取 half_hour 15:00 槽。

## 5. 按月抖动分解（判定链 Top3/Top1，无平滑 vs 滞回）

| 月份 | none: Top3 距离 | none: Top1 切换率 | hysteresis: Top3 距离 | hysteresis: Top1 切换率 |
|---|---|---|---|---|
| 2026-07 | 0.9571 | 0.9286 | 0.9429 | 0.9286 |
| 2026-08 | 0.9500 | 0.9000 | 0.9250 | 0.9000 |
| 2026-09 | 0.8412 | 0.8824 | 0.8000 | 0.8824 |

- 判定链 Top1 切换率全程 0.88-0.93（三配置同），**9 月没有因 AI硬件 rank 霸榜而改善**——MainlineScore 的排序与 rank 排序在 Top1 上几乎完全不同步，判定链的"第一名"日日更换。
- hysteresis 在 9 月把距离从 0.841 压到 0.800（全窗 0.896 vs 0.909）——改善幅度小，因为距离饱和点在"名单每天只保留 1-2 个老成员"的层面。
- **结论强化**：MainlineScore 合成分数本身（横截面 percentile 排序）的日间抖动是首要问题，平滑候选只能缓解不能根治；根治方向是分数合成层的结构改造（如改用 rank 稳健合成、或对原料因子先做日间平滑再合成）——列为 R3 候选。

## 6. 数据口径修正记录（本次执行固化）

1. **regime 两轴必须用 rank 字段 Top10**（R1 锚点口径）：MainlineScore Top3 名单距离≈0.91 饱和超 rot_hi，作 regime 输入恒 chaotic 无区分度（Task 4 核对发现，提交 `9b6227a9` 修正，MainlineScore 口径保留为附加诊断）。
2. daily 帧的 rotationSummary.marketPhase 恒 unknown，真值在 half_hour 15:00 帧（53 帧覆盖 62%）；rotationSummary.mainLines/mainlineConcentration 同在 half_hour 帧。
3. 题材级 rotationState 仅落 half_hour（六值：cooling/emerging/inflow/mainline/neutral/outflow）；daily 类型全缺。
4. transition_counts 返回 tuple 键不可直接 json 序列化——runner 用 `transitions_to_json` 转 'a->b' 字符串键（Task 2 备忘落实）。
5. 7 月 daily 类型仅覆盖 15 天（4 天 15:30 + 11 天 15:00 回退槽），7 月上旬 sector rows 未落 daily 类型——跨月对比时 7 月口径弱于 8-9 月。

## 7. 局限

- 54 天样本、单一行情周期（7-9 月），regime 阈值的稳健性结论不能外推到未见图景（如单边牛市）；
- 次期超额收益以 T+1 change 等权近似，未计交易成本与涨停买不进约束，不能与实盘预期直接换算；
- rolling 窗口（rot 5 日/entropy 10 日）为研究初始值，未做窗口敏感性；
- 判定链平滑候选的参数（alpha/window/exit_rank）均为单值，未扫描；
- market_phase 联合分布中 phase=None 14 天按字面键如实计数，未做回退填充。

## 8. 下一步（R3 / Phase 1 输入）

1. **R3 主线**：轮动补涨策略变体对照回测（SG1/SG2/SG3），消费 hysteresis_k3_exit5 平滑名单（本报告定版提案）；同时把"引擎 mainline 口径 vs 判定链口径"的选择作为 R3 设计的前置决策提交用户；
2. **R3 候选**：MainlineScore 合成层结构改造（rank 稳健合成 / 原料因子先平滑）以根治抖动——优先级高于继续调平滑参数；
3. **regime 体系重构提案（需用户裁决）**：双轴 regime 的 rotating 不可达 + 两轴相关，建议改为"引擎 rotationState/market_phase + Top1 稳定性"的组合状态，或直接登记引擎口径为轮动状态的单一事实源（`skills/single-source-of-truth` 三问：自造第三套状态体系的必要性不成立）；
4. **Phase 1 解锁项**：limitSummary 覆盖修复（回退取值或 KPL 补源）仍待办。
