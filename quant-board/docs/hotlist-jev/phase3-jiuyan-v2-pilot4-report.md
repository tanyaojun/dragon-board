# jev 涨停打标 v2 pilot4（题目 v3.1：叙事补日期+三护栏）战报

- 标签 266（ok），有心照链次日匹配 68，窗口 2026-09-07 → 2026-09-30

## 门A' 六桶方差

- {'n': 266, 'bucketCounts': {'core_main_business': 112, 'new_business_scaling': 55, 'new_business_early': 61, 'equity_or_affiliate': 29, 'concept_assembly': 7}, 'insufficientEvidence': 2, 'maxBucketShare': 0.421, 'bucketsWithN5': 5, 'expanded': True, 'insufficient': False}
- 展开=True（五实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）

## 守恒检验（core+新家族 vs pilot2 基准 227±8，修订口径）

- {'familySum': 228, 'pilot2FamilyTotal': 227, 'conserved': True}

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
- ✓ 守恒检验（）
- T3 抽验制：✓ 已抽验通过（扫描候选池 18 只）
- ✓ freshness unclear<8%（实际 0.064）
- ✓ driver 稳定性≥85%（修订）
- ✓ depth 一致率≥75%
- ✗ 门B 分组（预期 n 小不显著）

## 判定：INSUFFICIENT