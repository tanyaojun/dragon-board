# jev 涨停打标 v2 重铸试点（pilot2，catalyst_depth）战报

- 标签 266（ok），有心照链次日匹配 68，窗口 2026-09-07 → 2026-09-30

## 门A catalyst_depth 轴方差（主）

- {'n': 266, 'bucketCounts': {'core_main_business': 110, 'new_growing_business': 117, 'equity_or_affiliate': 27, 'concept_assembly': 9}, 'insufficientEvidence': 3, 'maxBucketShare': 0.44, 'substantiveBucketsWithN5': 4, 'expanded': True, 'insufficient': False}
- 展开=True（四实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）

## 门B 驱动分组保留

- {'p': np.float64(0.1232), 'lianbanRates': {'order_earnings': 23.5, 'concept_stretch': 5.9, 'product_event': 9.5}, 'spread': 17.6, 'n': {'order_earnings': 17, 'concept_stretch': 17, 'product_event': 21}, 'groupOk': False, 'insufficient': False}
- 方向一致性 vs 阶段3 全窗参考：{'rho': None, 'consistent': False, 'computable': False, 'reason': 'n>=8 组仅 3 个，排序一致性需 ≥5 组'}

## 稳定性对照（pilot2 vs pilot1，观察项）

- driver_type：{'overlap': 266, 'sameShare': 0.947}
- catalyst_freshness：{'overlap': 266, 'sameShare': 0.947}

## catalyst_depth 分桶次日方向（观察项，无硬门）

- {'core_main_business': {'n': 29, 'nextPctMean': 2.46, 'lianban': 13.8}, 'new_growing_business': {'n': 32, 'nextPctMean': 1.55, 'lianban': 12.5}, 'equity_or_affiliate': {'n': 5, 'nextPctMean': 1.65, 'lianban': 0.0}, 'concept_assembly': {'n': 1, 'nextPctMean': -10.0, 'lianban': 0.0}, 'insufficient_evidence': {'n': 1, 'nextPctMean': -10.03, 'lianban': 0.0}}

## catalyst_freshness 分布（观察）

- {'continuing': 191, 'fresh_catalyst': 29, 'unclear': 41, 'none': 5}

## 判定依据

- ✓ 门A depth 轴方差
- ✗ 门B 驱动分组（p<0.05 且 极差≥15pct）
- 稳定性/分桶方向=观察项（无硬门）

## 判定：INSUFFICIENT