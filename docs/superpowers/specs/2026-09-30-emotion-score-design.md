# 规则情绪连续评分体系（路线 B）— 设计规格 v3

- 日期：2026-09-30（v3 同日修订：吸收对抗性审计结论，见 `2026-09-30-emotion-score-audit.md`；v2 同日：吸收用户两决策——①直接切换 EOD 主定义，不设并行观察期；②等权评分进回测平台验证）
- 状态：v3 已审计修订；**T1.5 重放校准已完成（2026-09-30，报告 `2026-09-30-emotion-score-calibration.md`：_CALIB 已替换、压制条款已删除、五档实测全部可达）**；B4（score=None）按用户裁决采用方案 B（null+跳过+诊断）。待用户确认后进 T2。
- 决策背景：2026-09-30 用户裁决——布尔级联的结构性缺陷（阈值无验证、高潮档数学不可达、五档退化为双档开关、确认机制压制当下状态）不可接受，「刻意保守不能成为不尊重客观事实的理由」；现行 EOD 级联结论已确认有瑕疵，直接切换分数驱动

---

## 1. 设计原则（对"拍脑袋参数"的结构性解法）

1. **分数先行**：主输出是连续情绪分 `score`（0-100），档位只是分数的映射显示层。映射边界可调而评分结构不变——从此不存在"数学上不可达的档位"。
2. **分段边界 = 历史分位一次性校准**：每个因子的子分分段边界取自 1066 槽历史分布的实测分位（本文 §4 给出全部数值），写入配置常量并注明来源。**不再有任何无出处的 magic number**；后续调整是显式的配置变更（可审计、可 diff）。
3. **每维贡献可分解**：任何一次评分都能回答"为什么是这个数"——输出必须附带各维子分明细，缺失维度显式降级（权重归一化至其余维度）。
4. **零规则档位依赖**：评分消费原始/聚合证据（与 jev 聚合器同源），**不读** resolve_stage 的任何输出。
5. **B1 并行观察 → B2 切换裁决**：不动 `sentiment.py` golden 一行代码；评分作为独立轨道并行运行，观察期后由用户裁决档位主定义是否切换。

## 2. 布尔级联的结构性缺陷（实证，2026-09-30）

历史 1066 槽（half_hour）分布 vs 现行门槛：

| 因子 | 历史分布 | 现行门槛 | 失效判定 |
|---|---|---|---|
| crowdedShare | P50=0.021 / P90=0.029 / **P100=0.057** | 高潮需 ≥0.16/0.18/0.28 | **高潮档数学不可达**（历史 0 次） |
| strongMoneyShare | P50=0.026 / P90=0.096 | effective_spread 需 ≥0.08 | ~90% 时间关闭（联合触发率 3.9%） |
| riskShare | P10=0.826 / P50=0.925 | retreat 必要条件 | 系统性高位，形同常开，实际开关落在豁免条款 |
| attackShare | P50=0.037 / P90=0.130 | 发酵路径需 ≥0.12 | 11% 时间可达 |
| 昨日承接 failedOrWeakRate | P25-P90 恒 = 1.0 | 参与 retreat/ferment 语义 | 口径宽到无区分度，死因子 |

确认档位分布：启动 492（46%）/ 退潮 520（49%）/ 发酵 54（5%）/ **高潮 0** / 冰点 0 —— 五档退化双档开关。

强资判据（zljzb≥8）出处：前端 tooltip 口径沿用（代码注释自述），git 历史无验证记录，用途漂移三轮成为档位核心参数。

## 3. 评分体系

### 3.1 维度与子分（8 维，等权起步）

每维映射为子分 0-100（分段线性，边界 = 下方分位校准值），合成 `score = Σ(子分 × 权重)`，等权 1/8 起步：

| # | 维度 | 方向 | 分段边界（1066 槽校准） | 来源 |
|---|---|---|---|---|
| 1 | 广度 upRatio | 越高越强 | P10=0.385→10 / P25=0.470→25 / P50=0.561→50 / P75=0.662→75 / P95=0.800→95（线性插值） | metrics.layers.all.upRatio |
| 2 | 攻击占比 | 越高越强 | P50=0.037→30 / P75=0.082→50 / P90=0.130→70 / P95=0.171→85 / P99=0.254→95 | metrics.activeOpportunityShare |
| 3 | 风险占比（反向） | 越低越强 | P10=0.826→90 / P50=0.925→50 / P90=0.978→10（线性插值） | metrics.riskShare |
| 4 | 热榜 TRIN（反向） | ≤0.70→90 / 0.96→50 / ≥1.68→10 | metrics.layers.all.hotTrin |
| 5 | 昨日承接正收益率 | 越高越强 | P10=0.438→10 / P50=0.643→50 / P90=0.848→90 | metrics.limitEvidence.yesterdayHotLimit |
| 6 | 涨停结构 | 涨停家数 / 最高板 / 炸板率 合成子分 | 帧级 limitSummary + 池内涨停 |  |
| 7 | 量能同期 vsSamePct | 越高越强 | 节后积累分布后校准；**初期缺失即跳过该维** | evidence.totalAmount |
| 8 | 行级标记占比（反向风险） | 风险预警占比越低越强 | 首日分布后校准；初期缺失跳过 | evidence.rowFlags |

- 维度缺失 → 跳过该维、权重归一化，`degradedDims` 记录缺失（fail-visible）。
- 第 6 维子分 = 涨停家数分（60%）+ 最高板分（25%）+ 炸板率反向分（15%），边界随实施用同批历史校准。
- 第 7/8 维：设计值边界先行，**数据可得即参与合成（缺则跳过权重归一化）**；分布积累 ≥20 交易日后重校准（v3 修订：与实现一致，fail-visible 有数据即用）。
- **v3 审计修订（B1）→ T1.5 已完成**：_CALIB 已全部替换为 jev 聚合口径实测分位（1068 槽重放 2026-09-30，含 pctChange→change 历史行回退修复），出处与样本局限见 `2026-09-30-emotion-score-calibration.md`；limitStruct 三维为 198 真信号槽实测（样本局限已披露）、amountVsSame 保留设计值待积累。

### 3.2 输出合同

```jsonc
{
  "score": 62.5,                    // 连续情绪分（0-100）；证据全缺时为 null（见 §3.4）
  "dims": {                          // 每维子分与原始值（可分解审计）
    "upRatio": {"raw": 0.524, "sub": 47.2},
    "trin": {"raw": 0.98, "sub": 47.8},
    "...": {}
  },
  "skippedDims": ["amountVsSame"],   // 缺失跳过维度
  "stageCandidate": "发酵",           // 本帧映射档位（含斜率修正）——与文档 rawStage 同值（v3：同源合同，防两值不一致）
  "computedAt": 1759..., "version": "score-v1"
}
```

### 3.3 档位映射（显示层，B1 初版设计值）

五档语义（EMOTION_STAGE_RULES intent）在单轴分数上无法区分「退潮」与「冰点」（同为低分但方向不同）——B1 采用 **score 主导 + 斜率/风险修正** 的映射：

- `score ≥ 75`：高潮
- `60 ≤ score < 75`：发酵
- `40 ≤ score < 60`：启动
- `score < 40` 且当日 score 斜率向下（较上一槽）→ 退潮；斜率平/向上 → 冰点
- **v3 审计修订（B2）：斜率接线必须落地**——当日逐槽 score 序列（`_collect_intraday_state` 扩展收集）提供 `slope = score − prev_score`；prev 缺失（当日首槽/旧文档）→ `slope=None` → 判冰点 + diagnostics（跨日重置语义：无日内下落证据不判退潮）。
- **v3 审计修订（B3）→ 终稿：高潮压制条款已删除**（T1.5 实测 riskRowsPct 历史 P10=84.7 系统性高位，保留则 score≥75 的 65 槽被压 64 槽、高潮档二次不可达；score 本身已含风险两维，三重惩罚无必要）。score≥75 的槽 100% 判高潮。
- **映射边界经 T1.5 score 实测分布核对保持 75/60/40**：五档历史可达率 冰点 24.4% / 启动 36.4% / 退潮 18.2% / 发酵 14.9% / 高潮 6.1%（旧级联确认分布：高潮 0、冰点 0）。

### 3.4 score=None 槽的档位语义（v3 新增；方案待用户终裁决）

evidence 全缺（帧缺/行全缺）→ `score=null`：

- **方案 B（审计推荐）**：`rawStage=null`，确认重放跳过该槽（confirm_stage 已有缺失槽过滤语义），`stage` = 当日已确认值；当日无可确认档位时 `stage=null` + `stageConfirmState.historyStatus` 标注 + diagnostics。下游已验证安全：`risk.py:134` stage=None → phase="" → regime score 不加不减；符合 09-24 spec「不得用空串/0/默认阶段掩盖缺失」。
- 方案 A（回退 legacyCascadeStage）：级联在缺证时输出的是降级伪值而非诚实缺失，且确认序列混入级联口径——审计反证不推荐。
- 无论何案：`rawStage`/`stage` **禁止出现字符串 "None"**（`str(None)` 污染确认序列）。

## 4. 架构与落库（v2：直接切换）

```
规则情绪链（compute_hotlist_sentiment / build_hotlist_sentiment_document）
  └─ 新增 emotion_score 模块：collect_slot_evidence 同源聚合（frame/rows/yesterday_rows/analysis_by_code）
      → compute_emotion_score（分段映射 + 等权合成 + 缺维降级）
      → score → 档位映射 + 分数域确认 → 文档 stage/rawStage/stageConfirmState/emotionScore
旧 resolve_stage 降级为 legacy 对照面（legacyCascadeStage 字段保留输出，函数不删）
回测 replay：新旧档位对照（regime/分层影响量化）
```

- **评分结果内嵌 `hotlist_sentiment` 文档**：`emotionScore` 子文档（score/dims/skippedDims），与档位同源同槽位；**新 collection 不再需要**（v1 并行观察方案废弃）。
- **golden 触点**：`build_hotlist_sentiment_document` 内档位来源切换 + 新增字段——这是 v2 的实质修改，按 §5 切换与回退方案执行；`sentiment.py` 的 resolve_stage 函数本体不删（legacy 对照）。
- **无 gate**：切换即部署；回退 = 调用点切回级联（保留函数，回退成本一次部署）。
- **原料复用**：`collect_slot_evidence` 同源聚合（含 TRIN/总额同期/强资风险标记等全部新原料），评分模块不重复取数；昨日同期总额等自动随行。
- **下游兼容**：`stage` 仍为五档枚举（RankTrend risk.py stage_adjust / 前端 / jev ruleStage 对照零合同变更）；API 缓存版本 v2 → v3（emotionScore 新字段）。

## 5. 切换方案（v2：直接切换，不设并行观察期）

用户裁决：现行级联已确认瑕疵，EOD 档位主定义**直接切换**为分数驱动；等权评分进回测平台验证。

### 5.1 stage 字段来源切换（消费合同不变）

- `stage` 仍是五档枚举（冰点/启动/发酵/高潮/退潮），RankTrend 策略层 `risk.py:134` 的 `stage_adjust` 消费合同不变；**变化的是判档来源**。
- 新来源：`score → 档位映射`（§3.3）+ **确认复用 `stage_confirm.confirm_stage` 档位滞回**（v3 审计修订，S1：v2 的「连续 2 槽越过映射边界 + ±5 防抖带」表述废弃——实际机制是 rawStage=映射档位后直接复用既有确认状态机，重放语义/因果截断/跨日重置/EOD 同帧计一次全部天然保持，状态机零改动；「V 型不吞转折截面」的实质 = 分数连续性减少候选翻转次数，确认延迟语义与 09-24 机制一致）。
- `rawStage` = 本帧 score 映射档位（无平滑，截面事实；score=None 时为 null，见 §3.4）；`stage` = 平滑确认档位。
- `stageConfirmState` 字段形状不变（pending/pendingStage/pendingSince/confirmSlots/historyStatus），语义平移到分数域——前端零改动。
- **旧级联保留为对照面**：新增 `legacyCascadeStage` 字段存旧 resolve_stage 输出（对照与 diff 审计），resolve_stage 函数保留不删，调用点切至新映射。
- 新增 `emotionScore` 子文档进 `hotlist_sentiment` 文档（score/dims/skippedDims，可分解审计）；API 缓存版本 v2 → v3；**ingest 模型 `HotListSentimentPayload` 白名单同步增加 `emotionScore`/`legacyCascadeStage`**（v3 审计修订 S2，禁止静默丢弃）。

### 5.2 回测平台验证（等权评分）

- replay 链新旧对照：`legacyCascadeStage` vs `stage`（score 驱动）对 regime score（risk.py stage_adjust）与候选分层的影响 diff 报告；
- 回测框架下以等权评分为情绪输入跑策略回放，量化档位序列变化的影响范围——目的是**量化切换影响**，非验证正收益（用户已裁决收益验证是拟合弯路）。

### 5.3 历史重算

切换合并后全量重算（backfill slots 模式 + EOD），产出新旧档位 diff 报告；重算前 dry-run。重算同时写入 `legacyCascadeStage`（旧级联重放值），保证回退可执行与 T6 对照基线可得。

### 6. B1 → B2 裁决条件（v2 废弃并行观察期，改为切换后验证）

1. 切换合并后全量重算完成，新旧档位 diff 报告产出；
2. 回测平台新旧对照报告产出（regime/分层影响量化）；
3. 用户审阅 diff 后确认切换生效；若回测影响不可接受可回退——**回退 = 调用点切回级联（一次部署）+ 历史 stage 从 `legacyCascadeStage` 一次性重算恢复（v3 审计修订 S7：T5 已改写历史 stage，仅切调用点只回退「现在」不回退历史，RankTrend as-of 消费的历史序列须随重算恢复）**。

## 7. 验收标准（v3）

1. 评分可分解：任一文档可从 dims 还原 score（等权合成断言）；
2. 缺维度降级：删任意维度输入 → skippedDims 记录、score 归一化重算、不伪造；
3. 历史回放：1066 槽 + 全部 EOD 重算成功，新旧档位 diff 报告产出；
4. 分数域确认：复用 confirm_stage 滞回（2 槽），单槽越界被吸收语义与 09-24 机制一致；V 型转折在分数层可见（分数谷底可观测），确认档位切换延迟 ≤1 可观察槽（v3 修订 S1：删除 ±5 防抖带表述）；
5. **score=None 槽：rawStage/stage 为 null（或当日已确认值），无字符串 "None"，diagnostics 结构化标注，策略层 regime 不加不减（v3 新增 B4）**；
6. **退潮/冰点可区分：接线后当日斜率可用，T5 重算报告中退潮档可达次数 > 0（v3 新增 B2）**；
7. 采集链隔离：评分失败仅 warning；
8. 策略层消费兼容：hotlistSentiment.stage 仍为五档枚举，replay 回归通过。

## 8. 明确不做

- 不做次日收益/正收益验证（用户裁决：拟合弯路；验证锚 = 分段校准透明 + 回测影响量化 + 用户盘感审查）；
- 不删除 resolve_stage 函数（降级为 legacy 对照面）；
- 不改五档枚举与 stage 字段合同（策略层/前端零合同变更）。

## 9. 重校准触发条款（v3 新增，S6）

分段边界与档位映射锚定历史分位，市场结构变化后会漂移。触发人工评审重校准的条件（任一）：

1. 确认档位分布再次极端退化：某档历史 0 次，或单档占比 > 80%；
2. 新增 ≥ 20 交易日分布可供重校准（此时 `amountVsSame`/`riskRowsPct` 等设计值边界一并转正）。

重校准工具 = T1.5 重放脚本复用；边界变更以配置 diff 呈现（可审计），不做自动重校准。
