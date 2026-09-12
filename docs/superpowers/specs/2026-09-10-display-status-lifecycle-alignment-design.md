# 展示状态口径统一设计(displayStatus 以生命周期 5 态为主轴)

> 状态:设计已确认(2026-09-10 用户确认方案 C + 冷却强资修正) · 对抗性升级 · **U1–U4 已裁决(2026-09-10,见 §9.7)** · 实施计划按裁决更新
> 触发:生命周期阶段(周期列 5 态)与热榜情绪面板"全池状态结构"(8 类)展示语义偏差较大,
> 同一市场状态下"周期列满屏反转/冷却,面板转弱预警=0、新入观察/样本不足占 2/3"。
> 配套实施计划:`docs/superpowers/plans/2026-09-10-display-status-lifecycle-alignment.md`(含 §9 衍生的补丁 P1–P9)。

## 1. 问题与根因

两条计算链,中间隔一道被多轮优化改动的门控层:

- **周期列(5 态)**:`analyze_cycle`(纯排名轨迹)→ `cycle.stage`(ignition/expansion/crowded/reversal/cooling)→ `observation.lifecycle.stage` → 周期列(点火/扩散/拥挤/反转/冷却)。
- **全池状态结构(8 类)**:`cycle.stage → lifecycle_decision → compose_analysis_candidate_tier(× 动量阈值 × regime 环境门 × 风险压力 × gate 去噪 K 帧确认)→ candidateTier → compute_display_status(+ synergy/sampleStatus/强资金)→ displayStatus.label(8 类)→ 快照帧 join → statusCounts`。

根因:**displayStatus 以 candidateTier(交易候选资格)为主键,不是"当前状态描述"**。生命周期层多轮优化(regime 门 2026-08-18/19、阈值参数化 08-16、gate 去噪 2026-09)全部作用于该门控,门控收紧后大量个股落入 N_NEUTRAL → 展示状态被推向"新入观察",面板分布随优化漂移,与周期列脱钩。

次要偏差:
- 历史样本 <2 的新股 `cycle.stage` 兜底 "cooling" → 周期列显示"冷却",面板却按 `sampleStatus=insufficient` 显示"样本不足"(同股不同判)。
- `statusSourceCounts`(displayStatus join vs fallback 接管)后端有记录、面板不透出。
- 面板顶部"当前周期"(市场级情绪五阶段:冰点/启动/发酵/高潮/退潮)与个股生命周期 5 态命名混淆。

## 2. 目标与非目标

**目标**:面板 8 类成为生命周期 5 态的确定性细化(资金/样本修正层),**5 态 → 8 类方向可校验对账**;后续生命周期门控优化不再改变展示分布。

> 对抗性修订(§9.2 A1):原表述"两边永远可对账"不成立。8 类 ← 5 态是**多对一**(reversal 与 cooling 同落"转弱预警"),且修正层(样本不足/资金背离/风险升级)可改写任意 stage 的落点,因此**8 类计数无法反向还原 5 态计数**。对账只能以 per-row `cycle.stage` 真值为锚做**单向一致性**校验;反向不可还原本身也要作为显式合同固化在测试里。

**非目标**:不改 cycle/candidateTier/synergy 引擎计算(RankTrend golden 引擎零漂移);不改 statusCounts 8 标签枚举、快照合同、API 字段——**U1-a 裁决:stage 缺失不新增第 9 类标签,只在 `tooltip` 与 `statusSourceCounts` 计数上透出**;不改候选分层交易语义。

## 3. 新级联合同(后端 golden:`compute_display_status`)

> ⚠️ **本节已废弃（2026-09-10 同日，由 §10 对抗性升级推翻）**。三层修正级联会把 `cycle.stage`
> 主轴信息**覆盖**掉：实测 978 帧 / 220,736 行证明 `label` 无法反推 `stage`（`样本不足` 跨 4 个
> stage、`转弱预警` 跨 3 个），且 8 类中 `主升确认`/`资金背离`/`新入观察` 从未出现。
> **生效契约见 §10（displayStatus 退役为纯投影）**；落地设计见
> `docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`。
> 保留本节仅为追溯历史决策，**实施时不得引用本节**（配套 plan 曾引用本节，是 8 类长期偏离 §10 的直接原因）。

按序判定,命中即返回;label/classKey/tooltip 输出结构不变:

```
1. 样本质量门:  meta.sampleQuality.status == insufficient(兼容 flat meta.sampleStatus 回退)
               或 无效行情                                     → 样本不足
2. 风险修正层:  synergy.state == 风险升级                           → 转弱预警
               synergy.state == 存疑 且 zljzb ≤ 0                  → 资金背离
3. stage 主轴:  ignition   → 点火观察
               expansion  → 主升确认
               crowded    → 高位拥挤
               reversal   → 转弱预警
               cooling    → 强资金(zlje>0 且 zljzb≥8)且量能承接
                            (volumePrice.signalTier ∈ {A,B})     → 强资确认
                            否则                                  → 转弱预警
4. stage 缺失:  强资金且量能承接 → 强资确认(tooltip 追加"阶段数据缺失");
              否则                                              → 新入观察(tooltip=结构化原因)
5. 兜底:                                                            → 新入观察(原 tooltip)
```

> 对抗性修订(§9.2/§9.4):
> - 第 1 步字段必须写 `meta.sampleQuality.status`。原文档写 flat `meta.sampleStatus`,而引擎真实写入位置是 `meta.sampleQuality.status`(`engine/runtime.py` sample_status → `"sampleQuality": {..., "status": ...}`),照原文实现会**保留"insufficient 门在主链恒不触发"的 bug**。本设计同时修复该 bug 并保留 flat 回退以兼容历史 fixture。
> - 无效行情判据 = **价格类字段(price/latestPrice/lastPrice/close,取首个有值者)非有限或 ≤0**;成交额 `turnover` 非有限或 <0;`turnover == 0` **视为有效**(集合竞价)。原文"价格/成交额非有限非正"与实施计划测试(`turnover=0 → 主升确认`)矛盾,以本节为准。
> - **U3-a 裁决(已定稿)**:删除旧实现的 `synergy.state == 启动确认 → 点火观察` 分支。原因:该分支与 stage 主轴并行,且在 stage 缺失时产出"伪点火观察";删除后 `stage 缺失 + 启动确认 + 非强资金` → `新入观察`(带结构化原因 tooltip)。该行为在 §7 写死测试并注释 `U3-a`。

语义要点(已确认决策):
- **candidateTier 完全退出展示状态生产**,回归纯交易资格语义。
- reversal/cooling 拆分处理:reversal 无条件转弱预警;cooling 保留强资修正(均值回归反弹股的资金确认仍在,不误报防守)。
- 风险修正层优先于 stage 主轴(风险优先原则;资金背离可覆盖点火/扩散,与现有 TS `hotAttention && moneyWeak` 分支语义一致)。
- 强资金/量能承接判据复用现有 `_is_strong_money` + `_is_volume_supported`。
- 边界:cycle.stage 缺失/非法枚举值 → 走第 4 步(不伪造 stage);synergy 缺失 → 跳过第 2 步;zljzb 缺失/NaN → 不触发资金背离。
- **U1-a 裁决**:stage 缺失/非法时**保持 8 类标签**(不新增第 9 类),通过 (i) `tooltip` 结构化原因、(ii) 面板单列计数 `statusSourceCounts.stageMissing` 两条通道满足 fail-visible。

**字段缺失语义矩阵(§9.3 B2 补充,必须实现为显式行为,不得隐式默认)**:

| 字段 | 缺失/异常 | 语义 | 依据 |
| --- | --- | --- | --- |
| `meta.sampleQuality.status` | 缺失 | 回退读 flat `meta.sampleStatus`,再缺则按 `ok` | 历史 fixture 兼容;引擎真实字段见上 |
| `cycle.stage` | 缺失 / 非法枚举 | 跳过 stage 主轴,走第 4/5 步;**tooltip 必须带结构化原因**;仅当该行确实由第 4 步兜底(label ∈ {新入观察, 强资确认})时计入 `statusSourceCounts.stageMissing`(U1-a + F1 收紧) | fail-visible:缺失不得伪装成"无信号" |
| `observation.synergy` | 缺失 | 跳过风险修正层 | 独立轨道降级,不牵连 stage |
| `stock.zljzb` | 缺失 / 非有限 | 不触发资金背离(非"≤0") | 缺失 ≠ 流出 |
| `price/latestPrice/lastPrice/close` | 全部缺失 | 不判无效行情 | 缺失 ≠ 无效;不得因此归零或改判 |
| `turnover` | 缺失 | 不判无效行情;`0` 为有效 | 集合竞价语义 |
| `observation.volumePrice.signalTier` | 缺失 | 量能承接=false(不产强资确认) | 独立轨道降级 |

**stage 缺失的可辨识性(U1-a 裁决,已定稿)**:非目标禁止改 8 类枚举,缺失行仍落在 8 类之内,通过两条通道满足"可辨识 + 结构化原因":

1. **tooltip 结构化原因**(后端 `compute_display_status` 第 4 步):固定文案
   `阶段数据缺失或非法,未参与主轴判定(按新入观察兜底)。`,不得输出与业务态同形的"无明确信号,继续观察";该行走"强资金+量能承接 → 强资确认"时,tooltip 追加 `阶段数据缺失` 前缀以保持可辨识。第 5 步纯兜底(理论不可达)保留原 tooltip。
2. **面板单列计数**(`statusSourceCounts.stageMissing`):join 层(`_join_display_status`)在注入 `displayStatusLabel` 的同址就地注入 row 字段 `displayStatusReason='stage_missing'`;纯函数 `resolve_stock_status` / `build_day_metrics_from_sorted` 统计进 `statusSourceCounts.stageMissing`;`DragonBreathPanel.vue` 在来源注释追加 `阶段缺失 K`,缺字段(旧 EOD 文档)时整段隐藏,不做硬门禁。
   - 该字段属**后端超集可选字段**:不改变 `statusCounts` 8 类枚举,也不改变既有字段语义;TS 侧 `src/types/hotlistSentiment.ts` 的 `statusSourceCounts` 增补可选 `stageMissing?: number`,原有 `displayStatus`/`fallback` 保持必填语义不变。
   - **判定口径(F1 收紧,已定稿)**:`is_stage_missing_fallback(analysis, label)` = stage 缺失/非法(与 §3 第 4 步同一枚举实现,禁止第二套)**且** label ∈ `STAGE_MISSING_LABELS = {新入观察, 强资确认}`。只按 stage 计数会把"被样本门/风险层接管"的行(如 `sampleQuality=insufficient` → `样本不足`)误计入 K,使 K 无法与 8 类分布对账;收紧后 K 恰好等于"新入观察 + 强资确认中来自 stage 缺失的部分"。

## 4. 配套修正

1. **周期列样本不足显示**(DataTable.vue):`meta.sampleQuality.status === 'insufficient'` 时周期列显示"样本不足"(中性样式,排序归 neutral),不再显示误导性默认"冷却"。
2. **面板来源透出**(DragonBreathPanel.vue):全池状态结构底部增加"golden 判定 N / fallback 接管 M / 阶段缺失 K"(消费 `statusSourceCounts` 的 `displayStatus` / `fallback` / `stageMissing`;缺字段时隐藏,不做硬门禁)。
3. **文案区分**(可选):面板顶部"当前周期"改"市场情绪阶段",与个股生命周期区分。

## 5. 前端只消费后端生产数据(删除本地兜底级联)

`statusClassifier.ts` 收敛为纯消费 + label 映射,前端不做任何状态逻辑计算:

- `getRankTrendDisplayStatus` 仅直通后端 `rankTrend.displayStatus`;缺失(旧缓存/离线)时返回
  结构化未知态 `{label:'未知', classKey:'unknown', tooltip:'后端 displayStatus 缺失(旧缓存/离线)'}`,
  不做本地分类(fail-visible:缺失原因结构化透出,不伪造本地结论)。
- 删除兜底级联及其专属计算:`buildRankTrendStatusContext`(全市场分位前端自算)、
  `buildRankTrendStatusContextFromMarketPercentiles`、`classifyVolumeConfirmation`、
  `isStrongMoney`/`isMoneyWeak`/`isHighCrowded`/`isHotAttention`、`FALLBACK_STATUS_CONTEXT`、
  无效行情本地判、tier 分支级联与注释块优先级表。
- 保留纯展示投影(仅重排后端字段,不产生新判断):`CYCLE_LABELS`、`CANDIDATE_TIER_*`、
  `SAMPLE_QUALITY_LABELS`、`RISK_LABELS`、`getRankTrendDisplayBreakdown` 的 tooltip 组装。
- 消费方同步:`RankTrendPanel.vue` 移除 statusContext 构建与传参;`compat.ts` re-export 清单同步收敛。

**行为差异必须显式登记(§9.5 E2/E3)**:删除前端本地判 ≠ 语义等价。至少登记以下差异并逐条判定"接受/补齐":
1. 无效行情本地判被删除 → 后端 `turnover==0` 视为有效,若前端旧口径判 `0` 无效,则"0 成交额行"的展示状态会变化;
2. `marketPercentiles` 本地自算被删除 → 缺该字段时旧口径可自算兜底,新口径只能直通后端结果;
3. 后端缺 `displayStatus` 时旧口径由本地级联兜底,新口径显示"未知";
4. 未核实的同链路消费点(`src/services/apiService.ts`、`src/services/snapshot/**`、`src/components/common/SplashScreen.vue` 均出现 `displayStatus`)必须在改造前逐个核实归属:属同一链路则补进计划 Files 与验证,否则记录"已核实无关"。
5. **U4-a 裁决**:直通时 `classKey` 缺省回退值统一为 `'unknown'`,不再用 `'n_neutral'`(后者与已删除的 candidateTier 命名撞车,且不在 8 类白名单内)。`RISK_LABELS` / `RISK_CLASS_KEYS` 已有 `unknown → 数据不足 / risk-unknown`,风险栏不会因此误报"正常"。

## 6. 兼容与历史数据

- 8 标签枚举/输出结构不变 → statusCounts、snapshot_analysis.displayStatus、join 链路**字段合同**零变更。
- 旧 `hotlist_sentiment` EOD 文档不重算(lazy compute 只算最新日),新旧分布不可直接比;如需可比,可手动跑既有 backfill `run_for_date` 刷新(可选,不默认)。
- 上线后面板分布预期显著变化:转弱预警/主升确认/点火观察回升,新入观察大降——属修正而非回归。

> 对抗性修订(§9.4 C3):"字段合同零变更"≠"语义口径零变更"。`snapshot_analysis.displayStatus` 是逐帧落库的历史值,改造后不会重算,因此**同一视图内会混排两种口径**(历史帧 = candidateTier 口径、新帧 = stage 口径);`hotlist_sentiment` EOD 同理。
> **U2-b 裁决(已定稿)**:不新增口径版本字段、不新增混排提示。代价显式承担并写进交付报告:(i) 同股前后不一致时无法自证原因;(ii) 面板跨日/跨缓存对比不可比;(iii) 用户质疑时只能回到本文档 §6 与 spec 版本解释。Task 7 的"已知风险"必须逐条列出这三点,不得只写"分布预期变化"。
> 上线判据(§9.2 A3,替代"预期显著变化"这种不可证伪表述):首个完整交易日必须记录并对比改造前后同帧的 `statusCounts` / `statusShares` / `statusSourceCounts` 实测值,量化差异来源(修正类占比 vs 主轴类占比),并核验 `statusSourceCounts.fallback` 的口径是否与新级联一致(§9.5 E1)。

## 7. 测试策略(TDD)

- `test_display_status.py`(现 8 用例)按 §3 重写:stage 主轴逐态映射、reversal 与 cooling 分叉(含强资修正正反例)、风险修正优先序、candidateTier 不再驱动、无效行情(含 `turnover==0` 有效边界)、边界缺失(见 §3 字段缺失矩阵逐行覆盖)。
- **对账测试(§9.2 A2 修订)**:不再使用"输入=输出"的同义反复写法。要求 rows **携带 per-row `cycle.stage` 真值与修正标记**,然后断言:(i) 每个 8 类标签的来源 stage 集合 ⊆ 映射表(点火观察⊆{ignition}、主升确认⊆{expansion}、高位拥挤⊆{crowded}、转弱预警⊆{reversal,cooling});(ii) 主轴类计数 + 修正类计数(样本不足/资金背离/强资确认)+ 兜底类计数 = rows 总数;(iii) **不可逆性合同**:weakening 计数 ≠ reversal/cooling 任一单态计数,任何"从 8 类还原 5 态"的实现都应被判失败。
- **U3-a 行为变更测试**:`synergy.state=启动确认` + stage 缺失 + 非强资金 → 期望 `新入观察` 且 tooltip 含结构化原因(旧实现为"点火观察"),测试注释标注 `U3-a:旧分支已删除`。
- **U1-a 可辨识性测试**:后端正例——stage 缺失行 `label ∈ 8 类`、tooltip 含 `阶段数据缺失`;后端计数——join 注入 `displayStatusReason='stage_missing'` 后 `statusCounts` 统计出 `statusSourceCounts.stageMissing`;边界——`stage='garbage'` 与 `stage` 缺失同判。
- `statusClassifier.test.ts`:改为消费合同测试——后端 displayStatus 有值直通(label/classKey/tooltip 透传)、`classKey` 缺省 → `'unknown'`、缺失返回结构化未知态、breakdown 纯 label 映射;删除全部本地级联用例。
- `DataTable.test.ts`:周期列样本不足显示与排序归类。
- `RankTrendPanel.test.ts`(38 行)必须纳入 Files 并明确其断言是否依赖 statusContext/breakdown 行为。
- sentiment golden fixtures 零变化的前提是**fallback 路径的口径未变**;需核实 `fallback_status_label`(sentiment.py L329)口径并与新级联对照,若不一致则必须显式声明"golden 覆盖的是 fallback 口径",避免乐观通过。

## 8. 影响面与文档同步

- 代码:`quant-board/backend/analysis/ranktrend/trend/display_status.py`、`quant-board/backend/services/theme/hotlist_sentiment_compute.py`(stage_missing join)、`quant-board/backend/analysis/hotlist/sentiment.py`(计数)、`src/services/rankTrend/statusClassifier.ts`、`src/services/rankTrend/compat.ts`、`src/types/hotlistSentiment.ts`、`src/components/panels/RankTrendPanel.vue`、`src/components/common/DataTable.vue`、`src/components/panels/DragonBreathPanel.vue`。
- 文档:`docs/ranktrend/lifecycle-layering-contract.md`(展示状态节重写为新级联+对账关系+本 §3 的缺失矩阵与可辨识性);检查 `quant-board/docs/ranktrend-python-port.md` displayStatus 相关节;新增 `statusSourceCounts.stageMissing` 属后端超集可选字段,需在 `quant-board/docs` 的 sentiment 专题文档同步。
- 验证:quant-board `pytest`(collect-only + display_status/sentiment/snapshot_analysis 子集,规避全量挂起);根项目 `pnpm test`(相关子集)+ `vue-tsc`;UI 改动按 `skills/e2e-verification/SKILL.md` + `skills/playwright-cli/SKILL.md` 做真实浏览器验收。

## 9. 对抗性审查与升级(2026-09-10)

审查基准:`AGENTS.md` §4.0/§4.1/§11、`skills/fail-visible-data-pipelines/SKILL.md`、当前工作区源码实测。

### 9.1 源码核对结果(事实基线)

| 文档断言 | 核对结论 |
| --- | --- |
| 后端生产函数位置 `trend/display_status.py` | ✅ 存在(97 行),包入口经 `ranktrend/__init__.py` 惰性映射 `.trend.display_status` |
| 调用点 `ranktrend_routes.py:453-455` | ✅ 一致(`analysis["displayStatus"] = compute_display_status(analysis, stock)`) |
| 引擎写 flat `meta.sampleStatus`(故 insufficient 门恒不触发) | ✅ 成立:`engine/runtime.py` 只写 `meta.sampleQuality.status`,flat 字段缺失 → `sample_status` 恒为 `ok` |
| 旧实现以 candidateTier 为主键 | ✅ 成立(L69-72) |
| 旧实现含 `synergy.state=启动确认 → 点火观察` 分支 | ✅ 成立(L75-76),新级联删除(U3-a 裁决,见 §3/§9.4 C1) |
| `statusClassifier.ts` 540 行 → 现 541 行 | ✅ 一致 |
| `statusClassifier.test.ts` 717 行 | ✅ 一致 |
| `compat.ts:4-14` export 块 | ✅ 一致(第 4–13 行) |
| `types.ts` `executionStrategy?` L354 / 追加点 L355 | ✅ 一致(文件 364 行,`RankTrendAnalysisResult` 起于 L211) |
| `hotlistSentiment.ts:184` 已有 `statusSourceCounts` | ✅ 一致(文件 193 行;字段为可选) |
| `DataTable.vue` L179 模板 / L886-887 / L890-895 / `.lifecycle-env-cooling` L3161 | ✅ 一致 |
| `sentiment.py` `STATUS_LABELS` L17 / `sort_rows` L40 / `build_day_metrics_from_sorted` L228 | ✅ 一致 |
| `statusSourceCounts` 由后端生成并落库 | ✅ 成立(`sentiment.py:301/911`、`operations/hotlist_sentiment.py:384`) |
| **本设计 §3 第 1 步字段名** | ❌ **不一致**:原文写 flat `meta.sampleStatus`,与实施计划/引擎真实字段冲突 → 已就地修订 |

结论:引用型断言(路径、行号、字段)基本可靠,可直接作为实施依据;**语义型断言**存在 3 处实质偏差(§3 第 1 步字段、无效行情口径、可对账方向),均已就地修订。

### 9.2 设计层缺陷

- **A1 目标不可达(已修订 §2)**:5 态 → 8 类是**多对一 + 修正覆盖**,反向不可还原。原"两边永远可对账"会给用户与后续维护者错误预期。
- **A2 对账测试同义反复(已修订 §7)**:实施计划 Task 2 把 `compute_display_status` 的输出当输入喂给计数函数,再断言计数等于输入分布——它只能证明"计数器与映射函数自洽",**无法发现映射漂移**(真漂移会同时改变两侧)。必须改为携带 stage 真值的单向一致性 + 不可逆性合同。
- **A3 修正层优先级缺量化判据(已修订 §6)**:`存疑 + zljzb ≤ 0 → 资金背离` 会在 expansion/ignition 上大面积改判("存疑"是常见态),而 §6 只有"预期显著变化"这类不可证伪表述,违反 `AGENTS.md` §11 第 5 条(上线首日必须查实际库,不只看状态 API)。

### 9.3 与项目硬约束的冲突

- **B1 缺失伪装(已按 U1-a 定稿)**:`stage` 缺失/非法 → 原方案输出 `新入观察(无明确信号,继续观察)`,把**数据异常伪装成正常业务状态**,与 `fail-visible-data-pipelines` "缺失值保持缺失、不得用其他状态伪装"直接冲突。受"8 类枚举不变"约束,裁决为**标签不变 + tooltip 结构化原因 + `statusSourceCounts.stageMissing` 单列计数**(§3)。
- **B2 字段缺失语义未定义(已补 §3 矩阵)**:原设计的边界只覆盖 stage/synergy/zljzb,未定义价格类字段与 `turnover` 缺失时的语义,而实现依赖 `price/latestPrice/lastPrice/close` 的首个有值者。必须先定合同再实现,否则"缺失"会被隐式当作"有效"或"无效"。
- **B3 同股两判未闭环**:周期列改用 `sampleQuality.status` 判"样本不足"与 displayStatus 样本门**同源** ✅;但 `stage` 兜底 cooling 的判据(出现序列长度)与 `sampleQuality` **不同源**,因此仍会出现"周期列=冷却 / 展示状态=强资确认"。这不是缺陷,但必须在文档与 UI 文案中写明解读方式,否则与 §2 的"确定性细化"宣称冲突。

### 9.4 未声明的行为变更

- **C1 删除 `synergy.state=启动确认 → 点火观察`(已裁决 U3-a:删除)**:旧分支有测试覆盖,新级联完全移除。在 "stage 缺失 + synergy=启动确认 + 非强资金" 下,旧=点火观察、新=新入观察。裁决理由:该分支与 stage 主轴并行且会产出"伪点火观察";§3 已声明,§7 已写死测试。
- **C2 `turnover=0` 口径矛盾(已修订 §3)**:原文"成交额非有限非正"vs 计划测试"0 视为有效"。
- **C3 历史口径混排(已修订 §6,U2-b 裁决)**:`snapshot_analysis.displayStatus` / `hotlist_sentiment` EOD 不重算 → 同一视图内混排两种口径,且**不加字段区分**(裁决 b),代价与解释路径写入 §6 与交付报告。

### 9.5 覆盖缺口

- **E1 fallback 口径未定义**:`resolve_stock_status`(sentiment.py L316)在缺 `displayStatusLabel` 时走 `fallback_status_label`(L329),并计入 `statusSourceCounts.fallback`。设计只要求"透出计数",**未规定 fallback 必须与新级联同口径**。若 fallback 仍是旧口径,面板 8 类分布 = 两种口径之和,对账必然破功。必须核实并在 §4.2 写明(或强制 fallback 收敛为同一纯函数)。
- **E2 消费点未穷尽**:`displayStatus` 在 `src/services/apiService.ts`、`src/services/snapshot/**`、`src/components/common/SplashScreen.vue` 也有出现,但实施计划 Files 未列。改造前逐个核实归属,避免遗漏消费点导致"删了但没删干净/删错了"。
- **E3 测试文件遗漏**:`src/components/panels/__tests__/RankTrendPanel.test.ts`(38 行)在验收步骤被运行却不在 Files 中。
- **E4 回退方案缺失**:未写"上线后分布不可接受"的回退步骤(单 commit/Task 已具备 revert 基础,需写明顺序与影响面)。
- **E5 项目级流程未引用**:浏览器验收需按 SKILLS.md §7.2 引用 `skills/e2e-verification/SKILL.md` 与 `skills/playwright-cli/SKILL.md`。

### 9.6 计划体量风险(对照 AGENTS.md §11)

实施计划正文 1200+ 行并内联全部测试与实现全文。§11 的教训是"设计文档要短、实施计划要更短";内联全文还会制造**第二真相源**:实现一旦与文档代码块偏离,文档即失真。要求:内联代码块仅作首版草稿,落地后以源码为唯一事实,偏离时必须回写文档或删除内联块(至少加"以源码为准"声明)。

### 9.7 决策项与裁决记录(2026-09-10 用户裁决)

| 编号 | 问题 | 裁决 | 落地位置 |
| --- | --- | --- | --- |
| **U1** | `stage` 缺失/非法如何呈现 | **(a)** 保持 8 类标签 + `tooltip` 结构化原因 + 面板单列计数(不破枚举) | §3 语义要点与可辨识性段、§3 矩阵、§4.2、§7、plan P1/P4/P9 |
| **U2** | 历史帧口径混排是否加标识/提示 | **(b)** 仅文档声明不可比,不加字段、不加 UI 提示 | §6 对抗性修订段、plan P4/P6 |
| **U3** | `synergy.state=启动确认` 旧分支 | **(a)** 删除并在 §3 声明 | §3 级联注与语义要点、§7、plan P1 |
| **U4** | 直通时 `classKey` 缺省回退值 | **(a)** 改 `'unknown'` | §5 行为差异第 5 条、§7、plan P3 |

遗留复核项(非决策,必须在实施前核实并记录结论):E1 `fallback_status_label` 口径、E2 三处未核实消费点归属。

### 9.8 修订记录

第一轮(对抗性审查):

1. §2 目标:"两边永远可对账" → "5 态 → 8 类单向可校验;反向不可还原"。
2. §3 第 1 步字段:`meta.sampleQuality.status`(兼容 flat 回退),并明确这是 bug 修复。
3. §3 无效行情:`价格非有限或 ≤0`、`成交额非有限或 <0`(`0` 有效)。
4. §3 新增"字段缺失语义矩阵"与"stage 缺失可辨识性要求"。
5. §5 新增"行为差异登记"与"未核实消费点清单"。
6. §6 新增"历史口径混排"与"上线判据"。
7. §7 对账测试改为单向一致性 + 不可逆性合同,并补 fallback 口径核实要求。
8. §8 补项目级浏览器验收 skill 引用。

第二轮(U1–U4 裁决回写,本轮):

9. §3:级联第 4 步写入 tooltip 结构化原因;新增 U3-a 删除声明与 U1-a 两条通道;可辨识性段定稿(含 `statusSourceCounts.stageMissing` 与 `displayStatusReason='stage_missing'` 的注入/统计口径)。
10. §4.2:来源注释扩展为"golden 判定 N / fallback 接管 M / 阶段缺失 K"。
11. §5:行为差异新增第 5 条(U4-a `classKey → 'unknown'`)。
12. §6:U2-b 裁决落地(不加字段/不加提示,代价与解释路径逐条写入交付报告);§7 补 U3-a 与 U1-a 的写死测试;§8 影响面补 `hotlist_sentiment_compute.py` / `sentiment.py` / `hotlistSentiment.ts` 与 sentiment 专题文档。

### 9.9 实施前核实结论(2026-09-10,只读调查;兑现 §9.7 的遗留复核项)

**E1 fallback 口径(已核实)——是第三方启发式,与任何一版展示口径都不同源**

`fallback_status_label`(`quant-board/backend/analysis/hotlist/sentiment.py:329-351`)是一套独立启发式:输入 `change / compRank(rank) / zlje / zljzb / cddje / cddjzb / volumeRatio / turnoverRate`,**不读** `cycle.stage` / `synergy.state` / `candidateTier` / `sampleQuality`;输出虽落在 8 类标签内,但**不可能产出** 点火观察 / 主升确认 / 转弱预警(缺 stage 信息)。结论:

- 面板 `statusCounts` = 新 stage 口径(displayStatus) + 第三方量价启发式(fallback) 之和;对账只覆盖 displayStatus 侧。
- fallback 接管部分必须在注释中标注"(旧口径)"且**不计入新级联对账**(plan P4 已按此写死)。
- 其"样本不足"判据(`change < 3 and compRank > 100`)与 §3 的 `sampleQuality` 门**不同源**,面板"样本不足"计数实际混了两种含义——文档与 tooltip 不得声称二者等价。
- 附带发现:`resolve_stock_status`(L316-326)把"displayStatus 缺失"与"label 非法"合并计入同一个 `fallback`,无法区分。不阻塞本设计,**本轮不改**,记录为可选改进(如拆 `fallbackMissing` / `fallbackInvalid`)。

**E2 displayStatus 消费点归属(已核实)**

| 位置 | 归属结论 |
| --- | --- |
| `src/components/common/SplashScreen.vue:45/174` | **无关**:同名局部 computed(`props.status` → 启动页文案"龙睛开启"),与展示状态链路无任何关系 |
| `src/services/apiService.ts:127-130` | **同链路**:`SnapshotAnalysisEntry.displayStatus?: { label?, classKey?, tooltip? }` 类型定义 |
| `src/services/apiService.ts:565-580` | **同链路**:`getSnapshotAnalysis`(`GET /api/snapshots/analysis`)读口 |
| `src/services/snapshot/snapshotAnalysisReader.ts` | **同链路**:`loadSnapshotAnalysis` 透传 `analysis[code].displayStatus`(fail-visible:`{ok:false, analysis:{}}`) |
| `src/services/snapshot/**` 其余生产代码 | 无 `displayStatus` 引用(仅上述 reader 与其测试) |

关键结论:

1. `loadSnapshotAnalysis` **目前只有测试在调用,生产代码无调用方** → 历史帧 displayStatus 当前不会流入 `stock.rankTrend`;`getRankTrendDisplayStatus` 的入参实际只有 live analyze 链路。Task 3 的消费面因此仍限于 `RankTrendPanel`。
2. **`SnapshotAnalysisEntry.displayStatus`(三字段全可选)与将在 `RankTrendAnalysisResult` 新增的 `displayStatus`(plan Task 3 为三字段全必填)是两处重复形状定义**。Task 3 必须显式声明二者关系(复用同一类型,或注明可空差异),否则将来把 `loadSnapshotAnalysis` 接进 `stock.rankTrend` 时会丢字段或类型不匹配。

**实现与验证结果(2026-09-10,GREEN 达成)**

- `compute_display_status` 已重写为 §3 级联(含 cooling 无承接 → 转弱预警、无效行情判据、U1-a tooltip 结构化原因、U3-a 删除启动确认分支),并导出 `is_stage_missing` / `stage_of` / `STAGE_ENUM` 供 join 层复用(枚举判定唯一实现)。
- P9 链路落地:`_join_display_status` 注入 `rows[].displayStatusReason='stage_missing'`(判据复用 `is_stage_missing`),`resolve_stock_status` 累加 `statusSourceCounts.stageMissing`,两处初始化(sentiment.py `build_day_metrics_from_sorted` / stage evidence)同步补键 → `statusSourceCounts` 现为 `{displayStatus, fallback, stageMissing}` 三键。
- 验证:`pytest tests/test_display_status.py` → **25 passed**;相邻子集(display_status / hotlist_sentiment_compute / hotlist_sentiment_backfill / snapshot_analysis / snapshot_analysis_service)→ **69 passed**;`pytest --collect-only -q` → **2007 collected / exit 0**。
- 执行中发现:`statusSourceCounts` 新键命中既有**精确等值断言**(`tests/test_hotlist_sentiment_compute.py:235`),已同步为三键;**后续任何改该字段的任务必须先 grep 等值断言**,不能只跑"相关文件"。
- **前端(Task 3/4/5 与 P4/P9-4)已完成**:`statusClassifier.ts` 收敛为纯消费(删除兜底级联与 `buildRankTrendStatusContext*` / `classifyVolumeConfirmation` / `RankTrendStatusContext` / `VolumeConfirmation`),`types.ts` 增 `displayStatus?`(并注明与 `SnapshotAnalysisEntry.displayStatus` 的重复形状关系),`compat.ts` re-export 收敛,`RankTrendPanel.vue` 去掉 `statusContext`,`DataTable.vue` 周期列样本不足显示(含排序归中性),`DragonBreathPanel.vue` 三通道来源注释 + "市场情绪阶段"文案,`hotlistSentiment.ts` 增 `stageMissing?: number`,并新增 `src/components/panels/__tests__/DragonBreathPanel.test.ts` 来源文案单测。
- 验证(后端):`test_display_status.py` + `test_display_status_reconciliation.py` → **28 passed**;六文件子集 → **72 passed**;`--collect-only -q` → **2010 collected / exit 0**。
- 验证(前端):`vitest run`(statusClassifier / DataTable / RankTrendPanel / DragonBreathPanel) → **45 passed**;`vue-tsc --noEmit -p tsconfig.app.json` → **0 error**。
- 浏览器验收(Task 7):真实 chromium 渲染 `http://localhost:5173`(脚本与截图在 gitignored 的 `.playwright-cli/task7-*`)→ 面板底部渲染 `golden 判定 0 / fallback 接管（旧口径）235`、顶部文案 "市场情绪阶段"、控制台 0 报错;周期列"样本不足"仅一次采样命中(16 个),其余为 `--`,受主表数据加载时序影响 **未获确定性结论(待复验)**;"阶段缺失 K"按设计未出现(当前字段缺失)。
- **验收结论修正(2026-09-10 主代理复核)**:上条**只证明代码已编译进 bundle,不能证明用户可见效果**。复核实测:`.breath-panel` 默认 `v-show=false`(不点开整块 `display:none`)、`.status-source-note` 当时 **DOM count=0**、`sentiment-label` 文本确已是"市场情绪阶段"、周期列 16 个 `.lifecycle-env-insufficient` —— 当时**唯一**可见变化是行情主页那 16/237 行。更关键:`golden 判定 0` **不是** E1/U2-b 的"实证",而是 `snapshot_analysis` 集合为空(analyze 持久化只挂 `POST /api/snapshots/ingest` 后台任务,而日常采集由 `snapshot_collector` 直写库、绕过该路由;实测该集合 0 文档)——**本改动当时零可见效果**。
- **修复后实测(2026-09-10 补跑 + 重算,用户本地执行)**:`snapshot-analysis-backfill --limit 1 --apply` → `totalWritten=235`/`elapsedSeconds=18.5`;`hotlist-sentiment-recompute --apply` → `before {displayStatus:235,fallback:0,stageMissing:5}` → **`after {displayStatus:235,fallback:0,stageMissing:0}`**。8 类与 5 态**严格对账**:`转弱预警 220`(=cooling 213 − 强资确认 5 + reversal 12)、`强资确认 5`、`高位拥挤 3` + `样本不足 6`(=crowded 9)、`点火观察 1`(=ignition 1),合计 235。
- **修复中发现的真实缺陷(已修)**:`persist_snapshot_analysis` 原先只落 `observation/displayStatus/meta/resonance`、**未落 `cycle`** → join 侧 `is_stage_missing` 恒真 → `stageMissing=5` 是**假阳性**(退化成"新入观察+强资确认"的行数)。已补 `cycle` 落库 + 测试断言,重算后 K 归 0;新增 CLI `snapshot-analysis-backfill` / `hotlist-sentiment-recompute`(默认 dry-run),重算前旧文档备份进 `hotlist_sentiment_recompute_backup`。
- **仍未做(遗留)**:① analyze 持久化未接进采集链路(新帧仍无 displayStatus,需长期方案);② 周期列"样本不足"渲染在数据稳定时仍未复验。
- **code review 修复(2026-09-10,F1–F6 + 测试缺口全部落地)**:F1 —— `stageMissing` 判据收紧为"确实由第 4 步兜底"(新增 `is_stage_missing_fallback` + `STAGE_MISSING_LABELS`,join 层复用);F2 —— `display_status` 全链路 `_as_dict` 形状归一,非法输入不再抛异常(调用点无 try);F3/F4/F5 —— 注释登记(DataTable 判据前提 / 第 9 个 classKey 的有意选择 / "（旧口径）"硬编码文案的风险与同步点);F6 —— 前端源码契约测试的跨行正则收敛为稳定结构串断言;测试补 6 项(阶段缺失+insufficient 不计入、`STAGE_MISSING_LABELS` 契约、`is_stage_missing` 枚举契约、非法形状健壮性、前端 label 非 string)。

---

## 10. 根因重构:删除分类层,状态 = stage(2026-09-10 第二轮,推翻 §3 与整个 8 类体系)

> **状态:已确认(用户裁决)。本节为当前唯一有效设计;§3 级联、8 类 label、U1-a、fallback 启发式分类职能全部废弃。**

### 10.1 根因结论(为什么 8 类体系整体删除)

方案C(§3)的本质是**以 5 态为原料、经三层修正塌缩出 8 类**。生产逐股对账(2026-09-10 15:30 快照,235 只)证明两套分类永远不同构:

| cycle.stage | → 8 类 label | 数量 |
| --- | --- | --- |
| crowded | 高位拥挤 | 3 |
| **crowded** | **转弱预警(风险升级改写)** | **6** |
| cooling | 转弱预警 202 / 样本不足 6 / 强资确认 5 | 213 |
| reversal | 转弱预警 | 12 |
| ignition | 点火观察 | 1 |

后果:周期列显示原始 `crowded`(拥挤)的 6 只,面板只把 3 只算"高位拥挤"——**任何映射、正交栏、对账等式都只是管理不一致,不是消除不一致**。且 §9.1 的实测对账等式被证伪:`转弱预警 220 = cooling 213 − 强资确认 5 + reversal 12` 是数字巧合(真实构成 `202 + 12 + 6`),`样本不足 6 = crowded 9` 完全错误(样本不足 6 全来自 cooling)。

8 类中全部语义在 analysis 里本就有一等字段归属:阶段 → `cycle.stage`;强资承接 → `zlje/zljzb` + `volumePrice.signalTier`;风险升级/存疑 → `observation.synergy.state`;样本质量 → `meta.sampleQuality`。把一等字段复制成第二套"状态分类"就是病灶本身。**用户裁决:删除整个分类层,不做修正栏、不做 modifiers、不做任何第七八类。**

### 10.2 新契约:`displayStatus` 退役为纯投影

```json
{ "stage": "crowded", "label": "拥挤", "tooltip": "注意力拥挤高位,追高风险上升。" }
```

- **`stage`**:`STAGE_ENUM` 5 态或 `null`(缺失/非法)。
- **`label`** ≡ `STAGE_LABELS[stage]`;`stage=null` → `"无阶段"`。**词表单一来源在后端导出,前端只消费、不自维护第二套映射**(前端现有散落映射:DataTable.vue 周期列映射、statusClassifier.ts 候选词表,本轮收敛)。
- **`tooltip`**:阶段说明一句话;cooling 且强资金+量能承接(`zlje>0 且 zljzb≥8` 且 `volumePrice.signalTier ∈ {A,B}`,判据沿用 §3 原文)时拼接"资金承接仍强"提示——**提示只进 tooltip,不进任何分类或计数**。
- **删除清单**:三层修正级联;8 类 `label`/`classKey` 体系(含 `RISK_LABELS`/`RISK_CLASS_KEYS`);`STAGE_MISSING_LABELS`/`is_stage_missing_fallback`(F1 特判随分类层消亡);`fallback_status_label` 价格量启发式的**生产与消费**(hooks+backfill 已保证 analysis 全覆盖,启发式只会制造第二套结论;实现先断消费、保留函数,历史重算完成后删除)。
- **继承清单**:`_as_dict` 形状归一(F2);无效行情判据(`turnover==0` 有效);字段缺失矩阵"缺失≠无效"语义;candidateTier 退出;前端纯消费原则;§9 基础设施(post-save hooks / analysis worker / backfill / recompute / 缓存失效);DataTable 样本不足灰框;面板来源覆盖率行。
- U3-a(启动确认分支)随级联删除自然消亡,不复活。

### 10.3 计数契约(EOD 文档与面板)

```
stageCounts:        { ignition, expansion, crowded, reversal, cooling, unknown }
statusSourceCounts: { displayStatus, fallback }
```

- **`stageCounts` 直接锚定 `analysis.cycle.stage` 黄金真值**,与 displayStatus 存在性无关;`unknown` = stage 缺失/非法。
- **恒等式(替代全部对账测试)**:`sum(stageCounts) == 全池行数`;每行 `label == STAGE_LABELS[cycle.stage]`。面板 5 态分布与周期列 stage 分布在同池时**逐桶相等**——不再存在第二个口径,无需对账。fallback 行(analysis 覆盖缺失的历史残留)同样按 `cycle.stage` 计入 `stageCounts`,仅在 `statusSourceCounts.fallback` 中体现来源。
- **样本不足的股票计入其 stage 桶**,不从分布中挖掉;数据质量由周期列灰框(`meta.sampleQuality.status === 'insufficient'`,判据不变)与个股详情承载,不做面板状态格。
- 旧 `statusCounts`(8 类)字段删除,不做读口兼容(唯一消费者是自家前端);历史 EOD 文档由现成 `hotlist-sentiment-recompute --days 0 --apply` 全量重算,历史 `snapshot_analysis.displayStatus` 由 `snapshot-analysis-backfill --apply` 重跑为新投影结构。

### 10.4 展示层

- **DragonBreathPanel 全池状态结构 = 6 格**:点火 / 扩散 / 拥挤 / 反转 / 冷却 / 无阶段;底部保留"golden 判定 N / fallback 接管 M"覆盖率行。**没有修正栏,没有第 7 个状态格子。**
- **DataTable 周期列**:显示 `label`(与面板同词同源);样本不足灰框保留;周期列排序方向组沿用现有 5 态映射(ignition/expansion=buy,crowded/reversal/cooling=sell,unknown=hold)。
- **statusClassifier.ts**:`getRankTrendDisplayStatus` 返回 `{stage, label, tooltip}`;8 类 `RISK_LABELS`/`RISK_CLASS_KEYS`/`classKey` 全删;`UNKNOWN_STATUS`(displayStatus 缺失→"未知")保留。
- **类型契约**:`RankTrendAnalysisResult.displayStatus` 与 `apiService.SnapshotAnalysisEntry.displayStatus` 收敛为共享三字段类型(P10 同批解决);`hotlistSentiment.ts` 计数类型按 §10.3 重写。

### 10.5 验收(全部可自动化 + 真实浏览器逐股一致)

1. 后端:`compute_display_status` 单测 = 直映射矩阵 + stage 缺失/非法 → `null`/unknown + cooling 强资 tooltip 提示规则 + `_as_dict` 健壮性;旧级联/8 类测试删除。
2. 计数:EOD `sum(stageCounts)==行数`;重算后与当日快照 `cycle.stage` 分布逐桶相等(2026-09-10 15:30 真实分布 fixture:ignition 1 / expansion 0 / crowded 9 / reversal 12 / cooling 213 / unknown 0)。
3. 前端:vitest(statusClassifier 纯消费;面板 6 格文案契约;DataTable 周期列与面板同词);`vue-tsc` 0 error;`pnpm test` 全量绿。
4. **真实浏览器验收(playwright-cli,必须)**:面板 6 格数值 ≡ 行情表周期列逐股 stage 同池统计(**逐股核对,不接受只对合计**);控制台 0 报错。
5. 文档:`lifecycle-layering-contract.md` 展示状态节重写为恒等式(删除被证伪等式);`api-cli.md` displayStatus 新结构 + EOD 新计数 + 重算指引;`architecture.md` 口径同步。
