# relay v11 预注册：语料×题目集匹配度修复（2026-11-17）

> 状态：**已实施，待开火观察**（历史档不回填）。
> 触发：v10 实跑档（2026-11-17 重跑）语料×7 题判据逐条匹配度审计，用户裁决「全部修复」（M1 取 a 案）。
> 前代：relay-v10-corpus-slim-preregistration-20261117.md（同日，题集 8→7 + 语料精简）。
> 纪律：AGENTS §1.2-6（归因顺序 原料→题目→协议→重设计）、§1.2-1（单一事实源）、§4.0（fail-visible）、§1.2-8（叙事卫生）。

## 一、审计发现与裁决

| 编号 | 层 | 发现 | 裁决修法 |
|---|---|---|---|
| M1 | 题目 | ladder_health balanced/sparse/fracture 引用「参照正常带/低位带/参照腰斩」，但分位刻度只有 4 轴（晋级率/炸板家数/断板中位/隔日溢价），**梯队无独立分位**，`_money_hist_series` 不产梯队序列 | **a 案**：判据措辞改锚已有证据（涨停家数分位 + 昨日梯队分布），零新原料；instructions 明示「梯队无独立分位刻度」 |
| M2 | 原料 | divergence「高位分歧炸占比升高」无昨日归因对照（较昨日行只有炸板/反复开板家数） | 较昨日行补「高位分歧 a→b 家（占炸板 X%→Y%）」，单源 `hotlist_jev_zhaban_labels` 昨日档（已落库，零重算）；占比直给（评审 P2-1：只给家数在分母变动时方向会读反，同帧分母零新原料）；判据措辞同步「占比较昨日升高」；昨日档缺/今日未覆盖 → 「高位分歧较昨日不可算」（防伪 0：不出 3→0 数值对照） |
| M3 | 单源 | 题材演化行尾「（主线延续）」纯按 top3 重合≥2 判定，与 `relay_structure.mainline` 权威主线**同词两源**（11-17 实档：大消费 vs 半导体冲突） | 措辞改「top3 延续」；「主线」唯一权威保持 relay_structure（板块接力链/升位关系行消费） |
| M4 | 原料 | money strong/losing、phase relay_heat/collapse 共 4 处判据消费「大面占断板比」阈值（10%/30%），叙事只给家数需心算，与「数据已算好勿自行心算」指令矛盾 | 晋级与断板行补「（占断板 N%）」，单源 cur_stats；与反复开板占比同款口径 |
| O1 | 题目 | money_effect instructions「样本门槛见预注册 §2.3」——模型读不到外部文档 | 删指针半句；行为规则（叙事标「样本不足」不得作依据）保留 |
| O2 | 题目 | launch/divergence「最高板≤/≥参照中位」——语料给最高板**分位**不给中位 | 改「最高板分位≤P50/≥P50」，与 bottoming「≤P20」表述统一 |
| O3 | 重复 | 炸板面尾「冲刺未封 N 家」与盘面事实行「含冲刺 N 家」逐字重复（C 类残留） | 删主行侧（含不可算分支）；盘面事实共享行不动（坐标系红线）。**F1 旧 schema 降级行保留冲刺段**（评审 P2-2：旧帧无 items → rushingCount=None → 盘面事实行不渲染冲刺段，降级行是 16 个回放日冲刺家数唯一披露点，删则静默丢同帧已有数据违 §4.0） |
| O4 | 孤儿 | 「涨停池烂板 N 家（占 N%）」与「炸板股收盘涨幅中位」7 题判据+instructions 零引用（grep 实证） | 烂板段整行删（`_seal_quality` 读函数随删，sealQuality 结构化仍在帧）；中位删、**大面保留**（instructions 显式消费「炸板股大面」）；降级行针表同步「炸板股收盘涨幅→炸板股大面」 |

## 二、代际与不变量

- `QUESTION_SET_VERSION_RELAY` v10→**v11**（判据措辞三处变动按代际纪律升代；v10 今日已实跑消费，不就地改）。
- **阈值零变动**：7 题档位枚举、SCORE_ANCHORS_10、wzs/分带/market_cycle 判据、所有数值阈值（75%/0.5/1.5/10%/30%/P20/P50/P80 等）原样。
- 历史 v10/v9 档不回填不回改；跨代对比须注记代际。
- 共享函数（market_facts_line/limitup_sequence_line/sequence_line_from_bars）本轮**零触碰**。
- 结构化字段零删除：relayStructure（mainline/sustain/degraded）、rewrap 池快照、sealQuality/rushing 帧字段全保留；删的只是叙事行。
- 前端零改动：relay_page 泛型渲染叙事原文与 struct，无硬编码「主线延续/烂板/冲刺」消费（grep 实证）。

## 三、影响文件

- `backend/analysis/hotlist/jev_relay_ammo.py`：v11 戳 + ladder/phase/money 措辞。
- `backend/operations/jev_relay_index.py`：M2 归因前置+昨日对照（含占比）、M3 措辞、M4 占比、O3/O4 删段（F1 降级行保留冲刺）、`_seal_quality` 死函数删、针表/docstring 同步。
- `backend/operations/jev_label_jiuyan.py`：仅注释同步（nit-1：烂板段消费描述随 O4 陈旧，改「盘面事实行冲刺披露与封板质量结构化消费」；行为零变动）。
- 测试：`test_jev_relay_index.py`（冲刺/烂板/中位缺席改断言 + 降级针 + v11 四专项：hd 对照三态/top3 真锁/F1 混合 schema + 占比断言并入既有测试 + 三处 v11 戳）、`test_jev_version_stamps.py`（v11 + 措辞-供给对齐锁）。
- 本文档。

## 四、验收门

1. 删项缺席：全叙事无「冲刺未封」（主行炸板面段；F1 降级行保留）/「烂板」/「收盘涨幅中位」/「主线延续」。
2. 补供在场：大面占断板比、高位分歧较昨日家数+占炸板比对照（有昨日档时）、top3 延续措辞（overlap≥2 真分支锁）。
3. fail-visible：昨日归因缺/今日未覆盖 → 「高位分歧较昨日不可算」；旧 schema 降级行针表匹配；rottenShare=None 不再触及（原崩溃回归点保留测试）。
4. 全叙事过 `tests/hotlist/test_narrative_hygiene.FORBIDDEN` 黑名单（v10 专项测试继续生效）。
5. 判据措辞-供给对齐锁（test_v11_criteria_wording_matches_corpus_supply）：参照带/参照中位/外部指针零残留。
6. 测试全 mock 零真 jev（§1.2-7）；hotlist+api 全套绿；operations/platform 无回归。
7. 挂链后观察几日相位/钱效/梯队判定有无异常漂移（尤其 ladder_health 改锚后 balanced/sparse 取档）。

## 五、风险与回退

- ladder_health 改锚后「梯队总量」语义由「涨停家数分位+昨日梯队」近似承载——涨停家数与梯队总量口径微差（触板−炸板 vs 封板池），判据已明示参照来源，模型不再引用不存在刻度。
- M2 昨日档依赖 zhaban 打标链日常落库；缺档走不可算分支（不阻断）。
- 回退靠 git（§1.2#2）；历史档 questionSetVersion 天然分代。

## 六、独立评审处置（reviewer 26d35365，fresh-context 只读，结论「需修复后提交」）

| 编号 | 发现 | 处置 |
|---|---|---|
| P1-1 | M3 专项测试空锁：_STOCKS 夹具无 board 键全合并单板块，overlap=1 走不到被改名分支 | **已修**：改 _final_multi 甲/乙两日共同板块夹具，断言「重合 2/3」+「top3 延续」在场 |
| P1-2 | version_stamps:148 auction 戳断言疑混入协作者 WIP | **误报**：HEAD（bc790898，协作者 B9 批次已提交）中该断言与 auction ammo 均已是 2026-11-18b；工作树 diff 仅含本轮两 hunk（git diff 实证），整文件提交原子性成立 |
| P2-1 | M2 只给家数，判据消费占比，分母变动时方向读反 | **已修**：hd_cmp 补「（占炸板 X%→Y%）」，同帧分母 p_n/n，双 >0 除零保护 |
| P2-2 | O3 在旧 schema 日删掉 rushing 唯一披露点（§4.0 张力） | **已修**：F1 降级行单独保留冲刺段（该处不存在重复），主行仍删；docstring/测试/本文档同步 |
| P2-3 | 主函数 F1 分支新后缀零测试 | **已修**：新增今日新 schema+昨日旧 schema 混合夹具专项 |
| nit-1 | jev_label_jiuyan 注释「烂板段消费」陈旧 | **已修**（仅注释，行为零变动） |
| nit-2 | 预注册「四专项」计数措辞 | **已修**（§三） |
| nit-3 | M4 部分覆盖时占比是下界（分子=覆盖样本内大面、分母=全断板） | **不改**：与反复开板占比同款口径，「TDX 覆盖 k/n」同行披露；挂链观察期留意 |

A–H 逐项核对：生产代码逻辑/阈值零变动/删除彻底性（_seal_quality 零调用、_ths_pool_items 仍被 rewrap_pool 单源消费）/三处针串一致/代际戳/全 mock/叙事卫生均通过；证据见评审报告。