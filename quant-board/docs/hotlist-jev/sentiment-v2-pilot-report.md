# 情绪判定问题集 v2 pilot 战报（v2.1 重试点语料）

- v2 文档 33（槽 30 + EOD 3），三天试点窗口 2026-09-07/18/30（§7 v2.1 判据）
- **执行失误登记**：开火未按预登记收窄三天窗口，全窗 17 交易日 183 调用 ≈24 万 tokens（超支约 19 万），门判据按全窗样本计算

## 门1 crowding 归层方差（主）

- {'n': 33, 'layerCounts': {'top_acceleration': 0, 'late_seal_weakness': 0, 'breadth_climax': 3, 'no_crowding': 15}, 'insufficientEvidence': 15, 'maxLayerShare': 0.455, 'expanded': False, 'insufficient': False}
- 展开=False（四实质层合计≥85% 且 最大层≤70% 且 逃生口≤10%）

## 门2 temperature 方差不降

- {'stdV2': 12.67, 'stdV1': 11.28, 'ratio': 1.123, 'ok': True, 'insufficient': False}（配对 n=30）
- v2 温度十分位直方：{10: 1, 20: 1, 30: 2, 40: 2, 50: 12, 60: 10, 70: 2}

## 门3 五档漂移登记（观察项）

- frame_stage 新旧一致率：{'n': 30, 'sameShare': 0.467}

## 门4 EOD 同构

- {'eodN': 3, 'layersWithSample': 2, 'ok': True}（EOD day_crowding 层分布：{'breadth_climax': 1, 'no_crowding': 2}）

## 抽验（硬门）

- 待人工亲读 ≥5 文档（叙事-判例对齐）

## 判定依据

- ✗ 门1 crowding 归层方差
- ✓ 门2 temperature 方差不降
- ✓ 门4 EOD 同构
- 门3 观察项；抽验 待执行

## 判定：REJECT（抽验完成后定稿）

---

# v2.4 重试点战报：正向反馈四判据全过（2026-10-02，§10 预登记）

- ①两例失准（09-07 14:30、09-18 11:00）均已转落逃生口 ✓
- ②证据在场语料逃生口 **0/18**（v2.4 只纠正缺证据档，在场判读与 v2.3 逐位一致=无漂移）✓
- ③判例抽验沿用 v2.3 结论（13:00 breadth_climax 边界裁量正确、09-30 14:00 按轨）无新增失准 ✓
- ④层分布无异常漂移 ✓（在场语料 no_crowding 15 + breadth_climax 3）

**逃生口分账（本轮最有价值的读数）**：30 槽中 15 个是 v1 证据链"涨停与炸板：缺失"档（9 月中下旬 limitSummary 系统性缺口）——全部如实落逃生口，0 例瞎判。拥挤轴在 9 月的可判语料=18/30 槽，可判率缺口是 v1 数据供给问题（与题目无关），10 月起增量证据若补齐则自动恢复。

**门1 三项制：PASS**（(a) 0/18≤10% (b) 抽验无系统性失准 (c) 锚满窗 49/51/54）。门2 ✓ 1.123、门4 ✓。**判定：PASS_CANDIDATE → 正向反馈成立 → 开 9 月全月（§10 用户裁决）**。
