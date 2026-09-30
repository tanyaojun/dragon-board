# 审计报告 — 规则情绪连续评分体系（路线 B）T2 前对抗性审计

- 日期：2026-09-30
- 审计对象：`docs/superpowers/specs/2026-09-30-emotion-score-design.md`（v2）+ `docs/superpowers/plans/2026-09-30-emotion-score-plan.md` + T1 交付物（`emotion_score.py` commit 028bae8a）
- 审计立场：以"攻穿这个方案"为目标，全部结论以代码/数据取证为准（非观点）
- 审计方法：通读 spec/plan/交接文档 → 按交接 §5 清单 10 项逐一攻防 → 对关键疑点下钻到源码级核对（`sentiment.py` / `jev_state.py` / `emotion_score.py` / `stage_confirm.py` / `operations/hotlist_sentiment.py` / `hotlist_sentiment_compute.py` / `risk.py` / `hotlist_routes.py` / T1 测试）
- 结论：**方案方向成立（分数先行 + 历史分位校准 + legacy 对照面 + 确认机制复用），但存在 4 个阻塞项，其中 B1（校准口径错位）足以让"无 magic number"承诺落空。T2 前须插入重放校准任务（T1.5）。**

---

## 一、阻塞项（不解决不得进 T2）

### B1. 校准口径错位：_CALIB 分位数是规则链口径，评分输入是 jev 聚合口径

**取证**：

- spec §3.1 来源列明确写 `metrics.layers.all.upRatio` / `metrics.activeOpportunityShare` / `metrics.riskShare`——1066 槽分位数取自 `hotlist_sentiment` 文档 metrics，即**规则链口径**（`sentiment.py::build_day_metrics_from_sorted`）。
- T1 实现的评分输入是 `collect_slot_evidence`（jev 聚合口径，`jev_state.py`）。两口径存在**系统性差异**：

| 维度 | 规则链口径（校准出处） | jev 聚合口径（评分输入） | 差异方向 |
|---|---|---|---|
| upRatio | `change > 0` 才算涨，平盘归 flat（sentiment.py:329-336） | `pct >= 0` 即进 up0（jev_state.py:162-163），**平盘算涨** | jev 口径系统性偏高（平盘行占比通常 5-15%） |
| riskShare / attackShare / strongMoney | 分子含 fallback 行（`derive_fallback_row_signals` 旧启发式：资金背离=zlje<0 or zljzb<=-8…，sentiment.py:433-443） | 分子**仅 join 命中行**（analysis 缺失直接 `continue`，jev_state.py:225-227），fallback 行计入分母不计入分子 | jev 比率被稀释，方向与幅度取决于 fallback 率 |
| hotTrin | `change>0 / change<0` 分桶 | `pct>0 / pct<0` 分桶 | 两口径一致（平盘都不进桶）✓ |

**后果**：评分用 jev 口径的 upRatio 喂规则口径的校准边界 → 子分系统性偏高 → score 系统性偏高 → 档位系统性偏移。spec 原则 2（"不再有任何无出处的 magic number"）的形式达成了，实质没有——边界数值对应的不是喂进来的那个分布。

**修复（新 Task T1.5）**：写只读重放脚本（生产库 dragon_board_quant，snapshot_frames + snapshot_stock_rows + snapshot_analysis，09-07 起 1066 槽），用 `collect_slot_evidence` + `compute_emotion_score` 全量重放，产出：

1. **jev 口径全维分位数表** → 替换 `_CALIB`（这是与实现一致的唯一正确校准）；
2. **score 实测分布 + 五档可达率**（高潮/退潮/冰点历史可达次数——直接检验路线 B 是否重蹈"五档退化双档开关"）；
3. riskRowsPct 与 riskShare、upRatio 与 attackShare 的相关系数（S3/S4 裁决依据）；
4. join 命中率（fallback 率——若 >10% 需向用户上报口径裁决）；
5. `change` 与 `pctChange` 字段一致性断言、`zhabanRate` 量纲断言（百分数 vs 小数）。

**注意**：历史帧无 `totalAmount` 字段（jev_state.py:125 明示），重放时 amountVsSame 维全缺 → skip，符合 fail-visible；待生产积累后校准。

### B2. 退潮档不可达：slope 无输入路径（高潮档覆辙的镜像缺陷）

**取证**：`emotion_score.py:148` 调 `map_stage(score, risk_rows_pct_for_map)` **从不传 slope** → 真实链路低分恒判"冰点"，退潮档 0 次可达。`map_stage` 纯函数本身有 slope 参数且测试覆盖（test_map_stage_by_score），缺的是**接线**——spec §3.3"较上一槽斜率"需要当日逐槽 score 序列，纯函数拿不到，plan 未列该接线点。

**修复**：T2 接线时 `_collect_intraday_state` 扩展收集当日早槽 `emotionScore.score`（scorePoints），当前槽 `slope = score − prev_score`；prev 缺失（当日首槽 / 旧文档无 emotionScore）→ `slope=None` → 判冰点 + diagnostics 标注（跨日重置语义下"无日内下落证据不判退潮"合理，见 N9）。补接线层测试（含 prev 缺失分支）。

### B3. 高潮压制条款三重问题：无出处阈值 + 分母漂移 fallback + 二次不可达风险

**取证**（`emotion_score.py`）：

1. `_RISK_ROWS_CLIMAX_SUPPRESS = 70.0` 无出处——违反 spec 原则 2，正是本方案要消灭的东西；
2. L145-147 fallback：`risk_rows_pct` 缺失时用 `risk_share * 100`——分母从 judgeable 漂移到 total，且 jev 口径 riskShare 分子不含 fallback 行而分母含（被稀释）；
3. riskRowsPct 历史分布未知。riskShare（同分子不同分母的姊妹口径）历史 P50=0.925 系统性高位——riskRowsPct 大概率同样 >70 常态 → **score≥75 恒被压制 → 高潮档二次不可达**；
4. 结构性重复惩罚：score 已含 riskShare + riskRowsPct 两维风险信息（等权 2/8），压制条款是第三次惩罚。

**修复**：T1.5 重放实测 riskRowsPct 分布后三选一（向用户展示数据再定）：a) 删除压制条款（score≥75 本身已隐含风险维低——**审计倾向**）；b) 阈值改实测分位并注明出处；c) 保留设计值但必须先证伪"系统性 >70"。fallback 链（L145-147）随裁决一并处理或删除（缺 riskRowsPct → 不压制 + skippedDims 已可见）。

### B4. score=None 槽的档位语义未定义（交接清单项 1）

**取证**：spec/plan 均未写 evidence 全缺（score=None）时 `stage`/`rawStage` 是什么。`build_hotlist_sentiment_document:653` 现取 `str(result["stage"])`——若直接平移会造出字符串 `"None"` 污染确认序列。

**两案攻防**：

- 方案 A（交接文档倾向：回退 legacyCascadeStage + diagnostics）：**反证**——resolve_stage 在证据缺失时输出的是级联条件判 False 后落到的**降级伪值**（如"启动"），比 null 更不诚实；且确认序列混入级联口径槽，破坏"分数驱动档位"单一口径。
- 方案 B（审计推荐）：`rawStage=null` + 确认重放跳过该槽（`confirm_stage` 已有缺失槽过滤语义，stage_confirm.py:32）+ diagnostics；当日无可确认档位时 `stage=null`。**已验证下游安全**：`risk.py:134` `stage=None → phase="" → 不加分不减分`；09-24 spec 明文"API 不得用空串/0/默认阶段掩盖缺失"——null + 结构化诊断正是其要求。前端 T4 补 null 渲染（"评分不可用"）。

**待用户裁决**（交接已表达倾向 A，审计给出反向论证供重议）。

---

## 二、建议项（spec/plan 修订点）

### S1. 确认机制三处表述不一致 → 统一为"复用 confirm_stage 档位滞回"

spec §5.1 写"score 连续 2 槽越过映射边界（带宽 ±5 防抖）"、plan T1 写 `confirm_stage_by_score(score, prev_state, boundary_band=5)`，而 T1 实际交付（交接 §6 明示）是**复用 `stage_confirm.confirm_stage` 对映射档位序列做滞回**。三方案语义不同。审计裁决：复用滞回正确（已实证 61.5% 抖动减少、状态机零改动、"V 型不吞截面"的实质是分数连续性减少候选翻转而非新防抖带）。spec §5.1/§7 验收 4、plan T1 同步修订，删除 ±5 防抖带表述。

确认机制边界正面结论（交接清单项 2）：跨日重置/当日首槽直接确认/因果截断——`confirm_stage` 重放语义全部天然保持，`prev_state` 无需存储（序列重放模式），分数域平移 = rawStage 来源切换，状态机零改动。**交接预期成立。**

### S2. ingest 合同缺口：HotListSentimentPayload 白名单须加新字段

取证：`hotlist_routes.py:27-44` 字段白名单无 `emotionScore` / `legacyCascadeStage` → 手工导入静默丢弃（违反 09-24 spec"新字段必须进入模型，禁止静默丢弃"）。plan T3 明确列出（文件同在影响面，但须写明是 Payload 模型扩展而非仅缓存版本号）。

### S3. 风险双计（清单项 3 前半）：riskShare 与 riskRowsPct 分子同源、等权 2/8

攻防：两维分母不同（total vs judgeable），信息有差异；但相关性必然高，等权下"风险"实际权重 25%，超过任何其他维。处置：T1.5 重放输出两维相关系数，**>0.95 时向用户提请合并为一维**；T2 先保留等权（用户已裁决"等权进回测平台验证"）。

### S4. 广度/攻击重叠（清单项 3 后半）：upRatio 与 attackShare 分子结构性正相关

ignition/expansion 行大多 `pct>=0`，是 up 子集。处置同 S3：重放输出相关系数，留回测平台消融裁决，T2 不动。

### S5. 强资判据保留（清单项 8）：保留 strongMoney 进 attackShare 分子

理由：计数聚合口径（行数，非阈值判档）；`derive_row_flags` 是 jev 轨道/规则链/评分三方同一判据来源（sentiment.py:592，单一来源注释明确）；zljzb≥8 作为判据虽弱，作为行级计数无害。替换为 zlje 合计分位会改变"行占比"维度语义且引入新的未验证口径。记录于 spec，回测平台可消融。

### S6. 校准循环性（清单项 4）：增加重校准触发条款

spec 增补：确认档位分布再次极端退化（某档历史 0 次 / 单档占比 >80%）或新增 ≥20 交易日分布时，人工评审重校准；校准工具 = T1.5 重放脚本复用。不设自动重校准（与项目人工审计文化一致）。

### S7. 回退方案修正（清单项 5/6）：回退成本 = 一次部署 + 一次历史重算

T5 重算会改写历史 `stage` → 单纯切回调用点只回退"现在"，历史文档已是新口径，RankTrend as-of 消费（runtime.py `_ensure_hotlist_sentiment` 逐帧取 ≤ 帧时点最新文档）拿到的历史序列不回退。修正：回退 = 调用点切回（部署）+ 历史 stage 从 `legacyCascadeStage` 一次性重算恢复。**可执行前提已满足**：legacyCascadeStage 自 T2 起逐槽落库（重算也产出）。spec §5.3/§6 修订。

策略层回退确认（清单项 5）：`risk.py` 消费合同不变（五档枚举），切回即恢复旧档位序列；regime score 为纯函数重算，可回放验证。回退路径在策略链上成立。

### S8. T6 对照基线定义（清单项 6）

重算后旧"确认投影"不在任何单字段里。定义：**旧链基线 = `confirm_stage(legacyCascadeStage 当日序列)` 重放重建**（legacyCascadeStage = 旧级联截面 = 旧 rawStage 值）。T6 报告须写明该重建步骤，对照三方：旧确认投影 vs 新 stage（分数确认）vs 新 rawStage。

### S9. 第 7/8 维启用时机：spec 与实现不一致 → spec 向代码对齐

spec §3.1 写"积累 ≥20 交易日后启用"，实现是"有值即参与、缺则 skip + skippedDims"（emotion_score.py:126-129）。修订 spec：设计值边界先行、fail-visible 有数据即用、分布积累后重校准——与代码一致，也符合用户裁决文化。

### S10. stageCandidate 与 rawStage 必须同源同值

接线若给 rawStage 传 slope 而 `emotionScore.stageCandidate` 不带，低分槽两值不一致（冰点 vs 退潮）造成合同混乱。修订 spec §3.2：stageCandidate = 本帧映射档位（含斜率修正）= rawStage 同值，仅作嵌入冗余供单文档自审。

---

## 三、记录项（无需改动，备查）

- **N1** `riskLevel` 仍来自级联截面评估（`_evaluate_risk_pressure`）——切换后 riskLevel（级联源）与 stage（分数源）不同源并存；`risk.py:136-141` 消费 riskLevel（regimeRiskHighAdjust）。T2 不动 riskLevel（证据评估非档位），文档说明即可。
- **N2** 快照行 `change` vs `pctChange` 字段：规则链读 change、jev 读 pctChange——T1.5 重放断言一致性（B1 附属）。
- **N3** `zhabanRate` 量纲：_CALIB 假设 0-100 百分数——T1.5 断言。
- **N4** 切换当日确认序列新旧口径混合（早槽旧级联 rawStage + 晚槽分数 rawStage）：一次性，diagnostics 记录，T5 重算后消除。
- **N5** 性能：每槽多一次 `collect_slot_evidence`（内存聚合）+ 当日早槽 score 一次 Mongo 读——collector 半小时节奏可忽略；1066 槽重放一次性分钟级。
- **N6** EOD 与锚定槽一致性（09-24 spec §5.1）：map_stage / confirm_stage 均确定性纯函数，同帧同输入必同输出，断言自然保持。
- **N7** 迁移脚本 `migrate_hotlist_sentiment_slot_eod.py` 只动 slotTime 哨兵与索引，无字段白名单——不受影响（清单项 7 关闭）。
- **N8** 死因子（清单项 9）：failedOrWeakRate 未进评分 ✓（评分用 positiveRate）；_CALIB 全维均有帧级/跨日来源，无其他死因子。关闭。
- **N9** 当日首槽 slope=None → 低分判冰点：跨日重置语义下合理（无日内下落证据不判退潮），diagnostics 标注。与 B2/N4 关联。
- **N10** 写口 evidence parts（清单项 10）：`_compute_and_persist` / `compute_and_upsert_for_slot` 均已有 `previous_day_stocks`（yesterday_rows 复用）与 `_join_display_status`（join 标记已注入行内）；analysis_by_code 映射与昨日同期总额复用 jev 服务层既有模式（`jev_sentiment_compute` 取数段）——T2 三写口逐一接线，plan 已列。

---

## 四、修订后的执行顺序

```
审计报告（本文）→ 用户确认审计结论与待裁决项（B3/B4/S3）
  → T1.5 重放校准（B1 修复 + 可达性验证 + 相关系数产出）
  → 用户审阅重放报告（_CALIB 替换、档位边界/压制条款定稿、B4 语义定稿）
  → T2 链切换 → T3 → T4 → T5 重算（legacyCascadeStage 一并写入）→ T6 对照 → T7
```

T1.5 插入理由：直接切换 + 旧级联"高潮档数学不可达"的教训——**上线前必须实证五档可达**，否则路线 B 以"修复五档退化"立项、以"五档仍退化"收场。成本：一个只读脚本 + 分钟级重放，且其产物（jev 口径校准表）是 T2 的正确性前提。

## 五、待用户裁决清单

| # | 问题 | 审计推荐 |
|---|---|---|
| 1 | B4：score=None 槽 stage 语义——方案 A（回退级联值）vs 方案 B（null+跳过+诊断） | **B**（级联在缺证时输出伪值；null 符合 fail-visible；下游已验证安全） |
| 2 | B3：高潮压制条款——删除 / 实测分位定值 / 保留设计值 | 先看 T1.5 实测分布再定；**倾向删除**（score 已含风险两维，三重惩罚无必要） |
| 3 | S3/S4：维度双计——等权保留进回测消融 / 重放相关系数 >0.95 时合并 | 保留进 T2，重放出相关系数，回测平台消融后裁决 |
