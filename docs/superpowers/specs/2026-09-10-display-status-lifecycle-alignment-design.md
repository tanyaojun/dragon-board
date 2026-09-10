# 展示状态口径统一设计(displayStatus 以生命周期 5 态为主轴)

> 状态:设计已确认(2026-09-10 用户确认方案 C + 冷却强资修正) · 待实施计划
> 触发:生命周期阶段(周期列 5 态)与热榜情绪面板"全池状态结构"(8 类)展示语义偏差较大,
> 同一市场状态下"周期列满屏反转/冷却,面板转弱预警=0、新入观察/样本不足占 2/3"。

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

**目标**:面板 8 类成为生命周期 5 态的确定性细化(资金/样本修正层),两边永远可对账;后续生命周期门控优化不再改变展示分布。

**非目标**:不改 cycle/candidateTier/synergy 引擎计算(RankTrend golden 引擎零漂移);不改 statusCounts 8 标签枚举、快照合同、API 字段;不改候选分层交易语义。

## 3. 新级联合同(后端 golden:`compute_display_status`)

按序判定,命中即返回;label/classKey/tooltip 输出结构不变:

```
1. 样本质量门:  meta.sampleStatus == insufficient                  → 样本不足
2. 风险修正层:  synergy.state == 风险升级                           → 转弱预警
               synergy.state == 存疑 且 zljzb ≤ 0                  → 资金背离
3. stage 主轴:  ignition   → 点火观察
               expansion  → 主升确认
               crowded    → 高位拥挤
               reversal   → 转弱预警
               cooling    → 强资金(zlje>0 且 zljzb≥8)且量能承接
                            (volumePrice.signalTier ∈ {A,B})     → 强资确认
                            否则                                  → 转弱预警
4. stage 缺失:  强资金且量能承接 → 强资确认;否则                     → 新入观察
5. 兜底:                                                            → 新入观察
```

语义要点(已确认决策):
- **candidateTier 完全退出展示状态生产**,回归纯交易资格语义。
- reversal/cooling 拆分处理:reversal 无条件转弱预警;cooling 保留强资修正(均值回归反弹股的资金确认仍在,不误报防守)。
- 风险修正层优先于 stage 主轴(风险优先原则;资金背离可覆盖点火/扩散,与现有 TS `hotAttention && moneyWeak` 分支语义一致)。
- 强资金/量能承接判据复用现有 `_is_strong_money` + `_is_volume_supported`。
- 无效行情(价格/成交额非有限非正)→ 样本不足(TS 兜底已有,后端补齐同判)。
- 边界:cycle.stage 缺失/非法枚举值 → 走第 4 步(fail-visible,不伪造 stage);synergy 缺失 → 跳过第 2 步;zljzb 缺失 → 不触发资金背离。

## 4. 配套修正

1. **周期列样本不足显示**(DataTable.vue):`meta.sampleQuality.status === 'insufficient'` 时周期列显示"样本不足"(中性样式,排序归 neutral),不再显示误导性默认"冷却"。
2. **面板来源透出**(DragonBreathPanel.vue):全池状态结构底部增加"golden 判定 N / fallback 接管 M"(消费已有 `statusSourceCounts`,缺字段时隐藏,不做硬门禁)。
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
- 消费方同步:`RankTrendPanel.vue` 移除 statusContext 构建与传参(已核实为兜底专属,
  消费方仅此一处);`compat.ts` re-export 清单同步收敛。

## 6. 兼容与历史数据

- 8 标签枚举/输出结构不变 → statusCounts、snapshot_analysis.displayStatus、join 链路合同零变更。
- 旧 `hotlist_sentiment` EOD 文档不重算(lazy compute 只算最新日),新旧分布不可直接比;如需可比,可手动跑既有 backfill `run_for_date` 刷新(可选,不默认)。
- 上线后面板分布预期显著变化:转弱预警/主升确认/点火观察回升,新入观察大降——属修正而非回归。

## 7. 测试策略(TDD)

- `test_display_status.py`(现 8 用例)按 §3 重写:stage 主轴逐态映射、reversal 与 cooling 分叉(含强资修正正反例)、风险修正优先序、candidateTier 不再驱动、无效行情、边界缺失。
- 新增对账测试:同一 analysis 批次内,8 类计数按映射聚合(剔除样本不足/资金背离/风险升级修正)后 = 5 态计数。
- `statusClassifier.test.ts`:改为消费合同测试——后端 displayStatus 有值直通(label/classKey/tooltip 透传)、缺失返回结构化未知态、breakdown 纯 label 映射;删除全部本地级联用例。
- `DataTable.test.ts`:周期列样本不足显示与排序归类。
- sentiment golden fixtures 零变化(已验证不含 displayStatusLabel,走 fallback 路径)。

## 8. 影响面与文档同步

- 代码:`quant-board/backend/analysis/ranktrend/trend/display_status.py`、`src/services/rankTrend/statusClassifier.ts`、`src/services/rankTrend/compat.ts`、`src/components/panels/RankTrendPanel.vue`、`src/components/common/DataTable.vue`、`src/components/panels/DragonBreathPanel.vue`(及 sentiment TS 类型若缺 `statusSourceCounts`)。
- 文档:`docs/ranktrend/lifecycle-layering-contract.md`(展示状态节重写为新级联+对账关系);检查 `quant-board/docs/ranktrend-python-port.md` displayStatus 相关节。
- 验证:quant-board `pytest`(collect-only + display_status/sentiment/snapshot_analysis 子集,规避全量挂起);根项目 `pnpm test`(相关子集)+ `vue-tsc`。
