# jev 涨停打标 v2（韭研弹药版）战果判定报告

- 标签 266（ok），有心照链次日匹配 68，窗口 2026-09-07 → 2026-09-30

## 门1 Noul 修复（主）

- 分布（次日语料子集）：{'n': 68, 'p25': 0.67, 'p75': 0.79, 'iqr': 0.12, 'lowShare': 0.0, 'expanded': False, 'insufficient': False}
- 分布（全量标签对照）：{'n': 266, 'p25': 0.59, 'p75': 0.79, 'iqr': 0.2, 'lowShare': 0.0075, 'expanded': False, 'insufficient': False}
- 效果（高>0.7 vs 低<0.3，diff=mean(high)−mean(low)）：{'nHigh': 42, 'nLow': 0, 'diff': None, 'p': None, 'effectOk': False, 'insufficient': True}
- 展开=False effectOk=False

## 门2 驱动分组复验

- {'p': np.float64(0.0388), 'lianbanRates': {'order_earnings': 25.0, 'concept_stretch': 5.0, 'product_event': 10.5}, 'spread': 20.0, 'n': {'order_earnings': 16, 'concept_stretch': 20, 'product_event': 19}, 'groupOk': True, 'insufficient': False}
- 方向一致性 vs 阶段3 全窗参考：{'rho': None, 'consistent': False}

## 门3 catalyst_freshness 观察（无硬门）

- {'continuing': {'n': 57, 'nextPctMean': 1.57}, 'fresh_catalyst': {'n': 6, 'nextPctMean': 1.3}, 'none': {'n': 1, 'nextPctMean': -2.35}, 'unclear': {'n': 4, 'nextPctMean': 3.6}}

## 连板 vs 首板分层（韭研 day 字段）

- {'连板': {'n': 19, 'lianban': 21.1, 'nextPctMean': 1.18}, '首板': {'n': 49, 'lianban': 8.2, 'nextPctMean': 1.77}}

## 迁移矩阵（v1 旧链 × v2 新链，同股同日）

- {'overlap': 162, 'sameLabel': 64, 'sameShare': 0.395, 'cross': {'capital_flow': {'concept_stretch': 2, 'product_event': 1, 'policy': 1}, 'concept_stretch': {'order_earnings': 18, 'concept_stretch': 39, 'ma_restructure': 5, 'product_event': 20, 'industry_cycle': 8, 'policy': 3, 'capital_flow': 5}, 'industry_cycle': {'industry_cycle': 4, 'concept_stretch': 2, 'policy': 1, 'ma_restructure': 1, 'order_earnings': 1}, 'ma_restructure': {'order_earnings': 3, 'product_event': 3, 'ma_restructure': 5, 'concept_stretch': 1}, 'order_earnings': {'concept_stretch': 3, 'industry_cycle': 4, 'product_event': 3, 'order_earnings': 5, 'ma_restructure': 1, 'policy': 1}, 'policy': {'order_earnings': 1, 'concept_stretch': 1, 'industry_cycle': 1}, 'product_event': {'product_event': 11, 'order_earnings': 2, 'concept_stretch': 4, 'ma_restructure': 1, 'industry_cycle': 1}}, 'noulQuantiles': {'v1': {'p25': 0.58, 'p50': 0.7, 'p75': 0.77}, 'v2': {'p25': 0.62, 'p50': 0.72, 'p75': 0.8}}}

## 判定依据

- ✗ 门1 分布展开（IQR≥0.30 且 低组≥15%）
- ✗ 门1 效果（差≥2pct 正向 且 p<0.05）
- ✓ 门2 分组（p<0.05 且 极差≥15pct）
- 门3 观察项（无硬门）

## 判定：REJECT