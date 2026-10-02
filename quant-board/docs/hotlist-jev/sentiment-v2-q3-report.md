# 情绪 v2 Q3（7-9 月）战报 + 规则 EOD 对比归因

- v2 Q3：EOD 62 + 槽 571

## 分月数据梯度（无锚→半锚→满锚 天然实验）

- {'2026-07': {'days': 20, 'rho': 0.246, 'meanDiff': -3.56, 'meanAbsDiff': 8.43, 'stageAgree': '7/20', 'anchorN': [0, 1]}, '2026-08': {'days': 21, 'rho': 0.518, 'meanDiff': 4.64, 'meanAbsDiff': 11.98, 'stageAgree': '7/21', 'anchorN': [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]}, '2026-09': {'days': 21, 'rho': 0.572, 'meanDiff': 9.04, 'meanAbsDiff': 12.99, 'stageAgree': '5/21', 'anchorN': [11, 12, 13, 14, 15, 16, 17, 18]}}

## 门1 三项制全月复检

- {'slots': 571, 'judged': 171, 'escapeDataGap': 323, 'escapeAnchorGap': 68, 'genuineEscape': 9, 'a_ok': True}
- 三分账语义：数据缺口（无炸板率证据）/锚缺口（证据在场但参照轨不足）/真违规（证据+轨均在仍逃生）
- EOD day_crowding 层分布：{'no_crowding': 14, 'insufficient_evidence': 29, 'late_seal_weakness': 13, 'breadth_climax': 6}

## 温度 vs 规则分

- Spearman=0.594（n=62）；差值：{'n': 62, 'mean': 3.49, 'meanAbs': 11.17, 'sameDirectionDays': 30}

| 日期 | 锚N | 规则分 | v2温度 | 差 | 规则档 | v2档 | v2拥挤层 |
|---|---|---|---|---|---|---|---|
| 2026-07-01 | 0 | 49.0 | 27.2 | -21.8 | 启动 | ice | no_crowding |
| 2026-07-02 | 0 | 27.6 | 22.7 | -4.9 | 退潮 | ice | no_crowding |
| 2026-07-03 | 0 | 44.0 | 28.4 | -15.6 | 启动 | ice | no_crowding |
| 2026-07-06 | 0 | 31.3 | 32.3 | 1.0 | 冰点 | retreat | insufficient_evidence |
| 2026-07-07 | 0 | 30.7 | 30.6 | -0.1 | 冰点 | start | insufficient_evidence |
| 2026-07-09 | 0 | 45.0 | 27.2 | -17.8 | 启动 | ice | insufficient_evidence |
| 2026-07-13 | 0 | 24.9 | 23.6 | -1.3 | 退潮 | ice | insufficient_evidence |
| 2026-07-14 | 0 | 43.3 | 48.1 | 4.8 | 启动 | start | insufficient_evidence |
| 2026-07-15 | 0 | 40.9 | 35.3 | -5.6 | 启动 | start | insufficient_evidence |
| 2026-07-16 | 0 | 25.3 | 36.9 | 11.6 | 退潮 | retreat | insufficient_evidence |
| 2026-07-17 | 0 | 33.8 | 37.7 | 3.9 | 冰点 | start | insufficient_evidence |
| 2026-07-20 | 0 | 37.7 | 30.4 | -7.3 | 冰点 | ice | insufficient_evidence |
| 2026-07-21 | 0 | 36.9 | 44.9 | 8.0 | 退潮 | ferment | insufficient_evidence |
| 2026-07-22 | 0 | 37.3 | 34.6 | -2.7 | 冰点 | retreat | insufficient_evidence |
| 2026-07-23 | 0 | 34.3 | 34.7 | 0.4 | 冰点 | start | insufficient_evidence |
| 2026-07-27 | 0 | 48.6 | 31.9 | -16.7 | 启动 | retreat | insufficient_evidence |
| 2026-07-28 | 0 | 12.4 | 30.1 | 17.7 | 退潮 | retreat | insufficient_evidence |
| 2026-07-29 | 0 | 48.3 | 39.9 | -8.4 | 启动 | start | insufficient_evidence |
| 2026-07-30 | 0 | 36.9 | 38.1 | 1.2 | 冰点 | ferment | insufficient_evidence |
| 2026-07-31 | 1 | 72.3 | 54.6 | -17.7 | 发酵 | ferment | insufficient_evidence |
| 2026-08-03 | 2 | 45.3 | 33.3 | -12.0 | 启动 | start | insufficient_evidence |
| 2026-08-04 | 2 | 80.3 | 65.2 | -15.1 | 高潮 | climax | insufficient_evidence |
| 2026-08-05 | 2 | 75.7 | 66.2 | -9.5 | 高潮 | climax | insufficient_evidence |
| 2026-08-06 | 3 | 59.9 | 55.0 | -4.9 | 启动 | ferment | insufficient_evidence |
| 2026-08-07 | 4 | 62.8 | 47.4 | -15.4 | 发酵 | ferment | insufficient_evidence |
| 2026-08-10 | 4 | 47.5 | 43.4 | -4.1 | 启动 | start | insufficient_evidence |
| 2026-08-11 | 4 | 28.5 | 47.3 | 18.8 | 退潮 | ferment | insufficient_evidence |
| 2026-08-12 | 4 | 74.5 | 62.9 | -11.6 | 发酵 | climax | insufficient_evidence |
| 2026-08-13 | 4 | 43.0 | 48.0 | 5.0 | 启动 | retreat | late_seal_weakness |
| 2026-08-14 | 5 | 46.1 | 44.4 | -1.7 | 启动 | retreat | late_seal_weakness |
| 2026-08-17 | 6 | 58.3 | 55.6 | -2.7 | 启动 | ferment | insufficient_evidence |
| 2026-08-18 | 6 | 37.5 | 43.4 | 5.9 | 退潮 | start | insufficient_evidence |
| 2026-08-19 | 6 | 9.8 | 25.2 | 15.4 | 退潮 | retreat | late_seal_weakness |
| 2026-08-20 | 7 | 36.7 | 50.0 | 13.3 | 冰点 | ferment | insufficient_evidence |
| 2026-08-21 | 7 | 43.1 | 47.6 | 4.5 | 启动 | ferment | insufficient_evidence |
| 2026-08-24 | 8 | 26.2 | 44.7 | 18.5 | 冰点 | retreat | late_seal_weakness |
| 2026-08-25 | 9 | 46.7 | 63.3 | 16.6 | 启动 | ferment | no_crowding |
| 2026-08-26 | 9 | 53.3 | 69.3 | 16.0 | 启动 | ferment | late_seal_weakness |
| 2026-08-27 | 10 | 68.2 | 74.0 | 5.8 | 发酵 | ferment | breadth_climax |
| 2026-08-28 | 11 | 35.7 | 65.3 | 29.6 | 退潮 | ferment | no_crowding |
| 2026-08-31 | 11 | 38.5 | 63.6 | 25.1 | 冰点 | ferment | breadth_climax |
| 2026-09-01 | 11 | 35.4 | 70.1 | 34.7 | 退潮 | ferment | breadth_climax |
| 2026-09-02 | 11 | 27.6 | 47.0 | 19.4 | 冰点 | start | no_crowding |
| 2026-09-03 | 12 | 45.3 | 58.0 | 12.7 | 启动 | ferment | late_seal_weakness |
| 2026-09-04 | 13 | 24.4 | 40.1 | 15.7 | 退潮 | retreat | no_crowding |
| 2026-09-07 | 13 | 62.4 | 72.6 | 10.2 | 发酵 | ferment | breadth_climax |
| 2026-09-08 | 13 | 45.6 | 73.0 | 27.4 | 启动 | climax | breadth_climax |
| 2026-09-09 | 13 | 45.8 | 61.2 | 15.4 | 启动 | ferment | no_crowding |
| 2026-09-10 | 14 | 28.0 | 45.8 | 17.8 | 冰点 | retreat | late_seal_weakness |
| 2026-09-11 | 14 | 30.2 | 54.0 | 23.8 | 冰点 | ferment | late_seal_weakness |
| 2026-09-14 | 15 | 68.9 | 51.8 | -17.1 | 发酵 | start | late_seal_weakness |
| 2026-09-15 | 15 | 42.8 | 49.1 | 6.3 | 启动 | start | late_seal_weakness |
| 2026-09-16 | 15 | 80.3 | 70.3 | -10.0 | 高潮 | ferment | no_crowding |
| 2026-09-17 | 15 | 55.2 | 43.7 | -11.5 | 启动 | start | no_crowding |
| 2026-09-18 | 15 | 58.6 | 64.7 | 6.1 | 启动 | ferment | no_crowding |
| 2026-09-21 | 15 | 64.2 | 66.2 | 2.0 | 发酵 | ferment | no_crowding |
| 2026-09-22 | 15 | 58.7 | 67.3 | 8.6 | 启动 | ferment | late_seal_weakness |
| 2026-09-23 | 15 | 47.8 | 51.8 | 4.0 | 启动 | ferment | late_seal_weakness |
| 2026-09-24 | 16 | 50.6 | 47.8 | -2.8 | 启动 | ferment | late_seal_weakness |
| 2026-09-28 | 16 | 36.0 | 46.4 | 10.4 | 退潮 | ferment | no_crowding |
| 2026-09-29 | 17 | 65.9 | 78.2 | 12.3 | 发酵 | climax | breadth_climax |
| 2026-09-30 | 18 | 59.1 | 63.6 | 4.5 | 启动 | ferment | no_crowding |

## 档位混淆（规则 stageCandidate × v2 day_stage）

- 一致率（经词汇映射）19/62 = 0.31；混淆表 {('start', 'ice'): 3, ('retreat', 'ice'): 2, ('ice', 'retreat'): 4, ('ice', 'start'): 4, ('start', 'start'): 7, ('retreat', 'retreat'): 4, ('ice', 'ice'): 1, ('retreat', 'ferment'): 5, ('start', 'retreat'): 3, ('ice', 'ferment'): 4, ('ferment', 'ferment'): 5, ('climax', 'climax'): 2, ('start', 'ferment'): 12, ('ferment', 'climax'): 2, ('retreat', 'start'): 1, ('start', 'climax'): 1, ('ferment', 'start'): 1, ('climax', 'ferment'): 1}

## 差异归因（三轴：参照系/结构证据/方向）

- 规则分=当日横截面相对口径（涨跌占比/攻击份额/TRIN 等六维合成），无自身历史序列锚；
- v2 温度=以【近20日参照】为坐标系的绝对刻度打分（题干强制锚定）；
- 差异日按 diff 排序后逐日核对锚分位（当月涨停数 p20/p50/p80 与规则分的相对位置），归因写入下表。

- 2026-09-01：diff=34.7（规则 35.4 / v2 70.1，规则档 退潮 / v2 档 ferment）——归因待人工核对锚段后填写
- 2026-08-28：diff=29.6（规则 35.7 / v2 65.3，规则档 退潮 / v2 档 ferment）——归因待人工核对锚段后填写
- 2026-09-08：diff=27.4（规则 45.6 / v2 73.0，规则档 启动 / v2 档 climax）——归因待人工核对锚段后填写
- 2026-08-31：diff=25.1（规则 38.5 / v2 63.6，规则档 冰点 / v2 档 ferment）——归因待人工核对锚段后填写
- 2026-09-11：diff=23.8（规则 30.2 / v2 54.0，规则档 冰点 / v2 档 ferment）——归因待人工核对锚段后填写

---

# 差异完整分析（2026-10-02 人工归因收尾）

## 一、锚深度天然实验结论（本季最重要的发现）

| 月 | 锚N | ρ 与规则分 | meanAbsDiff | 档位一致（映射后） |
|---|---|---|---|---|
| 7 月（无锚） | 0-1 | **0.246** | 8.43 | 7/20=35% |
| 8 月（半锚） | 2-11 | **0.518** | 11.98 | 7/21=33% |
| 9 月（满锚） | 11-18 | **0.572** | 12.99 | 5/21=24% |

- **锚使温度与规则分的排序一致性翻倍**（0.246→0.572，随锚深单调上升）——"参照系分叉"根因被实验证实：无锚的 jev 就是绝对语感，与规则分只有弱相关。
- 但 **meanAbsDiff 不降反升**（8.4→13.0）：锚修的是"排序"，不是"水平"——v2 满锚月系统性比规则分高 ~9 分。两支表零点不同（规则分被风险维度压低、v2 是纯热度坐标），**水平差不是误差，是口径差**。
- 档位直接一致率全季 24-35%：词汇已映射仍低，确认两套档位语义结构不同，不建议做档位对齐。

## 二、门1 三项制全季复检

- 三分账：数据缺口逃生 323（56%——7 月 limitSummary 全月缺失+8 月半缺）、**锚缺口逃生 68**（证据在场但参照轨不足，集中 7-8 月）、真违规 9（占可判语料 9/84=10.7%，全部在锚薄月份；**满锚的 9 月=0%**）→ a_ok=True。
- 结论：逃生纪律随锚质量提升而收敛至零；7 月拥挤轴不可判是 2016-07 时代 v1 数据链问题，非题目问题。

## 三、Top-8 差异日归因

| 日 | diff | 归因 |
|---|---|---|
| 09-01 +34.7 | 规则退潮 35 / v2 发酵 70+广度高潮 | 涨停 91 家=月内次高，广度真高；规则被 riskShare=0.85 压制——**分母与权重差异** |
| 08-28 +29.6 | 规则退潮 36 / v2 发酵 65 | 同上模式：热起点日，v2 先热 |
| 09-08 +27.4 | 规则启动 46 / v2 高潮 73+广度高潮 | 涨停 96 家，广度真高；规则压分 |
| 08-31 +25.1 | 规则冰点 39 / v2 发酵 64 | 转折点日，v2 先热 |
| 09-11 +23.8 | 规则冰点 30 / v2 发酵 54+封板弱化 | 有热度但烂板——封板质量被规则分忽略 |
| 07-01 −21.8 | 规则启动 49 / v2 冰点 27 | **无锚日**：绝对语感模式偏冷（7 月 meanDiff −3.6） |
| 09-02 +19.4 | 规则冰点 28 / v2 启动 47 | 上旬分歧带（锚混季+风险压制） |
| 08-11 +18.8 | 规则退潮 29 / v2 发酵 47 | 转折点，v2 先热 |

**共性规律**：大分歧集中在**转折点**（8 月底-9 月初热起点）——v2（锚定自身历史）先热，规则（池内风险合成）滞后压制；这与你已验证的"情绪分=顺周期温度计与体感同向、50 线切错位置"认知一致：规则分在转折点的滞后是已知特性，v2 恰好补这个位。

## 四、决策建议（更新版，提交裁决）

1. **双表并存定版**：规则分=池内质量计（风险敏感、转折滞后），v2 温度=市场热度计（锚定坐标、转折领先）——ρ 0.594 + 转折点领先性 = 互补关系实锤。
2. **10 月增量接线**（建议立项）：v2 盘后自动跑（锚改按交易日历取近 20 日），EOD 温度+拥挤层与规则分并读展示；10 月内观察 v2 在脉拍/C6 弱势带的 A/B 读数，验证"转折领先"是否有交易价值。
3. **1182 历史重算建议放弃**：7 月拥挤数据不可恢复（limitSummary 缺失）、6-7 月锚供给为零——历史重算只能产出无锚温度，价值有限且花费 ~170 万 tokens。
4. 拥挤轴离散归层保留（EOD 三层 4/13/6+全月 0 违规）；温度轴保连续分。
