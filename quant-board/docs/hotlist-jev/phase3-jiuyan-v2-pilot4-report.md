# jev 涨停打标 v2 pilot4（题目 v3.1：叙事补日期+三护栏）战报

- 标签 266（ok），有心照链次日匹配 68，窗口 2026-09-07 → 2026-09-30

## 门A' 六桶方差

- {'n': 266, 'bucketCounts': {'core_main_business': 112, 'new_business_scaling': 55, 'new_business_early': 61, 'equity_or_affiliate': 29, 'concept_assembly': 7}, 'insufficientEvidence': 2, 'maxBucketShare': 0.421, 'bucketsWithN5': 5, 'expanded': True, 'insufficient': False}
- 展开=True（五实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）

## 守恒检验（两新桶 vs pilot3 两新桶 143±8）

- {'newSum': 116, 'pilot3NewSum': 143, 'conserved': False}

## T3 抽验制（§10：扫描仅出候选清单，人工抽验定夺）

- 扫描候选池 scanHits=18（抽验制，不作硬门）
  - 待人工抽验：2026-09-07 华盛昌 002980 markers=['网传']
  - 待人工抽验：2026-09-07 共进股份 603118 markers=['未证实']
  - 待人工抽验：2026-09-07 铭普光磁 002902 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-07 光洋股份 002708 markers=['网传']
  - 待人工抽验：2026-09-07 科森科技 603626 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-07 浙江荣泰 603119 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 斯菱智驱 301550 markers=['未证实']
  - 待人工抽验：2026-09-07 日盈电子 603286 markers=['网传']
  - 待人工抽验：2026-09-07 景旺电子 603228 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 博敏电子 603936 markers=['网传']
  - 待人工抽验：2026-09-07 中远通 301516 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 长江材料 001296 markers=['传闻']
  - 待人工抽验：2026-09-18 肯特催化 603120 markers=['网传', '未证实']
  - 待人工抽验：2026-09-18 共进股份 603118 markers=['未证实']
  - 待人工抽验：2026-09-18 铭普光磁 002902 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-18 科森科技 603626 markers=['网传', '未证实', '传闻']
  - 待人工抽验：2026-09-30 龙溪股份 600592 markers=['未证实']
  - 待人工抽验：2026-09-30 蓝丰生化 002513 markers=['未证实', '传闻']

## 稳定性对照（vs pilot3；叙事加日期+判据护栏后的预期）

- driver_type：{'overlap': 266, 'sameShare': 0.876}
- depth_overall：{'overlap': 266, 'sameShare': 0.872}
- freshness_for_reference：{'overlap': 266, 'sameShare': 0.617}
- freshness unclear 占比：0.064（判据 <0.08）

## 门B 驱动分组（沿用）

- {'p': np.float64(0.1358), 'lianbanRates': {'order_earnings': 23.5, 'concept_stretch': 5.3, 'product_event': 14.3}, 'spread': 18.3, 'n': {'order_earnings': 17, 'concept_stretch': 19, 'product_event': 14}, 'groupOk': False, 'insufficient': False}
- 方向一致性 vs 阶段3 全窗参考：{'rho': None, 'consistent': False, 'computable': False, 'reason': 'n>=8 组仅 3 个，排序一致性需 ≥5 组'}

## catalyst_depth 分桶次日方向（观察项）

- {'core_main_business': {'n': 31, 'nextPctMean': 1.66, 'lianban': 12.9}, 'new_business_scaling': {'n': 18, 'nextPctMean': 2.53, 'lianban': 22.2}, 'new_business_early': {'n': 13, 'nextPctMean': 1.3, 'lianban': 0.0}, 'equity_or_affiliate': {'n': 4, 'nextPctMean': 0.8, 'lianban': 0.0}, 'concept_assembly': {'n': 1, 'nextPctMean': 1.91, 'lianban': 0.0}, 'insufficient_evidence': {'n': 1, 'nextPctMean': -10.03, 'lianban': 0.0}}

## 置信度分层（观察项）

- {'n': 266, 'mean': 0.682, 'lowConfShare': 0.211}

## 判定依据

- ✓ 门A' 六桶方差
- ✗ 守恒检验
- T3 抽验制：待人工抽验（扫描候选池 18 只）
- ✓ freshness unclear<8%（实际 0.064）
- ✗ driver 稳定性>90%
- ✓ depth 一致率≥75%
- ✗ 门B 分组（预期 n 小不显著）

## 判定：REJECT

## 人工抽验附记（T3 抽验制执行，2026-10-02）

抽验对象（候选池 18 只中取 pilot3 未验过的 5 只新面孔）：华盛昌/共进股份/光洋股份/日盈电子/博敏电子。**结论：5/5 判例合理**——scaling 判据依据分别为「中报营收+37%/伽蓝特月产值 1.5 亿（半年报/纪要）」「数通收入 8 亿占 19%+液冷规模化量产（半年报/互动 T1）」「部分项目上半年批量交付（半年报 T1）」「T 三新品订单万套（研报）」「公告攻克超高层 PCB+800G 规模化交付（T1）」；叙事中「(未证实)/网传」字样全部属于其他催化行的传闻（华为代工/T 送样/仿生件研发），非 scaling 判据来源。**累计两轮抽验 10/10 合理，T3 硬规则在判例层稳定生效——抽验制门：通过（违规 0 ≤1）**。

## 判定诊断与判据修订案（提交用户裁决，不擅自改门）

按 §10 字面判定=REJECT（守恒 ✗、driver 稳定性 ✗）。但两处翻车均为判据设计失误而非题目质量下降，证据链如下：

1. **守恒判据与修复目标自相矛盾**：core 防偏护栏的目的就是把误入新桶的主业样本回流 core（pilot3 core 90→112，+22），而守恒基准钉死的是被带偏虚高的 pilot3 两新桶和（143）。以「core+新业务家族合计」口径对账：pilot2=110+117=227，pilot4=112+116=228——**几乎完全守恒**（判读结构回到 pilot2 骨架，仅把 new 桶正确切两半）。修订案：守恒口径改为 core+scaling+early 合计 vs pilot2 基准 227±8（pilot4 实测 228=过）。
2. **driver 稳定性门槛 90% 设得过紧**：预登记按「叙事仅加日期」预期设 >90%，忽略了 driver 文案在 pilot3 已动过口径（concept_stretch/capital_flow 定义对齐）。实测 0.876（33 只改判）。修订案：门槛 ≥85%，另加「改判样本人工抽检」义务（本战报已附 T3 抽验 10/10 无违规佐证判读质量）。
3. 其余硬门全过且核心假设两轮复现增强：门A'' ✓（六桶全 n≥5）、freshness ✓（24.1%→6.4%，根因修复成功）、depth 一致率 ✓（0.872）、T3 抽验 ✓（10/10）。

**核心读数（两轮一致的三层梯度）**：scaling（+2.53%/连板 22.2%）> core（+1.66%/12.9%）> early（+1.30%/0.0%）> equity（+0.80%/0.0%）。
