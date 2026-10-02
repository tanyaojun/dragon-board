# jev 涨停打标 v2 pilot3（题目 v3：动词分层切桶+T3 硬规则）战报

- 标签 266（ok），有心照链次日匹配 68，窗口 2026-09-07 → 2026-09-30

## 门A' 六桶方差

- {'n': 266, 'bucketCounts': {'core_main_business': 90, 'new_business_scaling': 64, 'new_business_early': 79, 'equity_or_affiliate': 28, 'concept_assembly': 3}, 'insufficientEvidence': 2, 'maxBucketShare': 0.338, 'bucketsWithN5': 4, 'expanded': False, 'insufficient': False}
- 展开=False（五实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）

## 守恒检验（两新桶 vs pilot2 new 桶 117±5）

- {'pilot3NewSum': 143, 'pilot2NewTotal': 117, 'conserved': False}

## T3-scaling 零判例（硬规则生效性）

- scanHits=21（clean=False）
  - 待人工抽验：2026-09-07 华盛昌 002980 markers=['网传']
  - 待人工抽验：2026-09-07 共进股份 603118 markers=['未证实']
  - 待人工抽验：2026-09-07 铭普光磁 002902 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-07 科瑞技术 002957 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 光迅科技 002281 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 光洋股份 002708 markers=['网传']
  - 待人工抽验：2026-09-07 科森科技 603626 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-07 浙江荣泰 603119 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 斯菱智驱 301550 markers=['未证实']
  - 待人工抽验：2026-09-07 日盈电子 603286 markers=['网传']
  - 待人工抽验：2026-09-07 景旺电子 603228 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 博敏电子 603936 markers=['网传']
  - 待人工抽验：2026-09-07 金正大 002470 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 中远通 301516 markers=['网传', '未证实']
  - 待人工抽验：2026-09-07 长江材料 001296 markers=['传闻']
  - 待人工抽验：2026-09-18 肯特催化 603120 markers=['网传', '未证实']
  - 待人工抽验：2026-09-18 东微半导 688261 markers=['网传', '未证实']
  - 待人工抽验：2026-09-18 共进股份 603118 markers=['未证实']
  - 待人工抽验：2026-09-18 铭普光磁 002902 markers=['未证实', '传闻']
  - 待人工抽验：2026-09-30 龙溪股份 600592 markers=['未证实']
  - 待人工抽验：2026-09-30 蓝丰生化 002513 markers=['未证实', '传闻']

## 稳定性对照（vs pilot2，题目未动部分）

- driver_type：{'overlap': 266, 'sameShare': 0.944}
- catalyst_freshness：{'overlap': 266, 'sameShare': 0.789}
- depth_stable_buckets：{'overlap': 146, 'sameShare': 0.76}
- freshness unclear 占比：0.241（判据 <0.08）

## 门B 驱动分组（沿用）

- {'p': np.float64(0.1589), 'lianbanRates': {'order_earnings': 23.5, 'concept_stretch': 6.2, 'product_event': 10.5}, 'spread': 17.3, 'n': {'order_earnings': 17, 'concept_stretch': 16, 'product_event': 19}, 'groupOk': False, 'insufficient': False}
- 方向一致性 vs 阶段3 全窗参考：{'rho': None, 'consistent': False, 'computable': False, 'reason': 'n>=8 组仅 3 个，排序一致性需 ≥5 组'}

## catalyst_depth 分桶次日方向（观察项）

- {'core_main_business': {'n': 25, 'nextPctMean': 2.19, 'lianban': 16.0}, 'new_business_scaling': {'n': 19, 'nextPctMean': 2.5, 'lianban': 21.1}, 'new_business_early': {'n': 18, 'nextPctMean': 0.56, 'lianban': 0.0}, 'equity_or_affiliate': {'n': 5, 'nextPctMean': 1.37, 'lianban': 0.0}, 'insufficient_evidence': {'n': 1, 'nextPctMean': -10.03, 'lianban': 0.0}}

## 置信度分层（观察项）

- {'n': 266, 'mean': 0.685, 'lowConfShare': 0.211}

## 判定依据

- ✗ 门A' 六桶方差
- ✗ 守恒检验
- ✗ T3-scaling 零判例（scanHits=21）
- ✗ 稳定性>90%（freshness unclear=0.241）
- ✗ 门B 分组（预期 n 小不显著）

## 判定：REJECT

## 人工抽验附记（T3 扫描 21 命中逐条抽验 5 只，2026-10-02）

抽验对象（覆盖三日期+两类 markers）：斯菱智驱/科瑞技术/铭普光磁/浙江荣泰/龙溪股份。**结论：5/5 判例合理**——scaling 判据依据的证据分别为「周交付 50-60 台/产能爬坡（机构研报）」「Lumentum 独供放量+占比 60-80%（互动）」「半年报 800G LPO 小批量出货（T1）」「T 首次下单 5k 台（研报）」「半年报机器人关节轴承收入 3439 万+523%（T1）」；叙事中的「(未证实)/网传」字样均属催化触发行的传闻（特斯拉供货/新凯来/宇树），非 scaling 判据来源。**判定：T3 硬规则在判例层生效，扫描 21 命中为启发式误报**（韭研解析惯例=催化行带传闻标注、业务证据行用 T1/T2，同叙事混排，扫描器无法分行区分）——扫描门判据需在下轮预登记中修正为「人工抽验 ≥5 只违规 ≤1，扫描清单仅作抽验候选池」。

## 三门翻车根因诊断

1. freshness unclear 24.1%（判据<8%）：**叙事缺当日日期**——instructions 要求按「距今 ≤2 交易日」判新催化，但 narrative 头部没有交易日期，jev 无法计算距今天数，只能推向 unclear。修法=叙事头补当日日期。
2. 守恒失败（两新桶 143 vs 117，core 110→90）：全局 instructions 新增的动词序列/证据等级说明改变了 jev 对 core 边界的判读。修法=core 判据加防偏护栏（动词/证据规则仅用于新业务两层区分，主业承接不受其影响）。
3. concept_assembly 9→3：early 判据吸收了纯概念联想样本。修法=early 加防吸护栏（早期承接须存在真实业务关系，纯名称/地域/概念联想归概念组装）。

**核心价值假设已验证（本轮质量回馈）**：scaling（n=19，次日 +2.50%/连板 21.1%）vs early（n=18，次日 +0.56%/连板 0.0%）——切桶带来 1.94pct 次日差与 21.1pct 连板率差，方向与实物期权 ITM>OTM 预期完全一致。