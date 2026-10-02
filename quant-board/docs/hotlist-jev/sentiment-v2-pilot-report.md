# 情绪判定问题集 v2 pilot 战报

- v2 文档 183（槽 166 + EOD 17），窗口 2026-09-07 → 2026-09-30
- **执行失误登记**：开火未按预登记收窄三天窗口，全窗 17 交易日 183 调用 ≈24 万 tokens（超支约 19 万），门判据按全窗样本计算

## 门1 crowding 归层方差（主）

- {'n': 183, 'layerCounts': {'top_acceleration': 9, 'late_seal_weakness': 95, 'breadth_climax': 5, 'no_crowding': 11}, 'insufficientEvidence': 63, 'maxLayerShare': 0.519, 'expanded': False, 'insufficient': False}
- 展开=False（四实质层合计≥85% 且 最大层≤70% 且 逃生口≤10%）

## 门2 temperature 方差不降

- {'stdV2': 12.86, 'stdV1': 13.81, 'ratio': 0.931, 'ok': True, 'insufficient': False}（配对 n=166）
- v2 温度十分位直方：{0: 3, 10: 3, 20: 19, 30: 44, 40: 59, 50: 27, 60: 6, 70: 5}

## 门3 五档漂移登记（观察项）

- frame_stage 新旧一致率：{'n': 0, 'sameShare': None}

## 门4 EOD 同构

- {'eodN': 17, 'layersWithSample': 3, 'ok': True}（EOD day_crowding 层分布：{'top_acceleration': 1, 'late_seal_weakness': 8, 'breadth_climax': 1}）

## 抽验（硬门）

- 待人工亲读 ≥5 文档（叙事-判例对齐）

## 判定依据

- ✗ 门1 crowding 归层方差
- ✓ 门2 temperature 方差不降
- ✓ 门4 EOD 同构
- 门3 观察项；抽验 待执行

## 判定：REJECT（门1 翻车，根因已诊断）

## 门1 根因诊断（2026-10-02，零成本）

逃生口按槽位分布：09:30=53%、10:00-11:30=35%、13:00-14:30=31%、15:00=24%——全槽位均匀，非早盘数据薄。根因=**判据要了叙事里没有的证据**：late_seal_weakness 判据引用"涨停时间较近日后移/尾盘板占比"，但证据链（evidenceRaw）只有涨停数/连板梯队/炸板率/封板率，无首封时间分布——jev 拒绝超证据判读（fail-visible 正确行为），判据超供给是我的设计失误。

**v2.1 修正预登记**：crowding 判据全部改锚叙事已有证据（炸板率/封板率 vs 参照段分位、连板梯队形态、涨停数 vs 参照），删除一切涨停时间引用；instructions 显式声明"所需证据均已在叙事与参照段给出"。重试点=同三天 36 调用 ≈5 万 tokens（预登记原范围），门判据不变。