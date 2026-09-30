# T1.5 校准报告 — 连续情绪评分 jev 口径重放（1068 槽实测）

- 日期：2026-09-30
- 执行：`backend/operations/emotion_score_calibration_replay.py`（只读生产库 dragon_board_quant，全程 find 无写入）
- 背景：审计报告 `2026-09-30-emotion-score-audit.md` B1/B3——_CALIB 原值出处为规则链 metrics 口径，与评分输入（jev 聚合口径）存在系统性差异
- 样本：hotlist_sentiment 槽位文档全清单 1068 槽（2026-04-15 ~ 09-30，half_hour；交接文档所称 1066 槽 + 09-29/30 新增），scoreNone = 0

---

## 1. 核心结论

1. **五档全部健康可达（路线 B 核心承诺实证达成）**。新 `_CALIB` + 删除压制条款 + slope 接线形态下，1068 槽重放档位分布：

| 档位 | 槽数 | 占比 | 旧级联确认分布（对照） |
|---|---|---|---|
| 冰点 | 261 | 24.4% | **0**（旧口径不可达） |
| 启动 | 389 | 36.4% | 492（46%） |
| 退潮 | 194 | 18.2% | 520（49%，兜底档） |
| 发酵 | 159 | 14.9% | 54（5%） |
| 高潮 | 65 | 6.1% | **0**（旧口径数学不可达） |

2. **高潮压制条款删除的数据支撑（审计 B3 终稿）**：score≥75 的 65 槽中 64 槽 riskRowsPct>70——若保留压制条款，高潮档回到 0.09%（1 槽），二次不可达坐实。已按用户裁决删除（`emotion_score.py` 的 `_RISK_ROWS_CLIMAX_SUPPRESS` 与压制分支移除，`map_stage` 签名简化为 `(score, slope)`）。

3. **B1 口径错位实证**：upRatio jev 口径（pct≥0 含平盘）P50=0.592 vs 规则链口径（change>0）P50=0.561，系统性偏高约 3 个百分点；attackShare/riskShare/trin/yhPositive 两口径收敛（join 率≈100%）。_CALIB 已全部替换为 jev 口径实测值。

4. **映射边界 75/60/40 经实测分布核对保持不变**：score 分布 P25=32.0 / P50=43.3 / P75=57.9 / P90=69.7 / P95=75.8——五档覆盖结构合理（高潮 6.1% 为稀有事件档，退潮 18.2% 不再兜底）。

## 2. 重放中的新发现与修复：历史行无 pctChange

- 2026-04-15 ~ 07-03 导入的历史行（约 470 槽，44%）只有 `change` 无 `pctChange`——首轮重放该批槽 upRatio 全 0、TRIN 全缺（涨跌分布废）。
- 修复：`collect_slot_evidence` 增加 `pctChange → change` 字段回退（数值口径一致性实证：两字段并存的 12.1 万行中不匹配率 0.71%），回退行数进 `quality.degradedSources`（fail-visible）。生产行（07-06 起）均有 pctChange，**对 jev 轨道现行叙事零影响**，历史重放/T5 重算受益。
- 测试：`test_collect_slot_evidence_change_fallback_for_legacy_rows`。

## 3. _CALIB 替换对照

锚定模式统一：主维 P10→10 / P25→25 / P50→50 / P75→75 / P95→95（反向维镜像）。

| 维度 | v2（规则链口径/设计值） | v3（jev 口径实测） | 样本 |
|---|---|---|---|
| upRatio | P50=0.561→50 | P50=0.5921→50 | 1068 |
| attackShare | P50=0.037→30（锚 P75→50） | P50=0.0375→30 | 1068 |
| riskShare（反向） | P10=0.826→90 | P10=0.8253→90 | 1068 |
| trin（反向） | P5=0.505→90 | P5=0.5056→90 | 1053 |
| yhPositive | P50=0.643→50 | P50=0.6429→50 | 1067 |
| riskRowsPct（反向） | 设计值（60→50） | **P50=93.98→50**（实测远高于设计） | 1068 |
| ztCount | 设计值（45→60） | P50=42→50 | **198 真信号槽** |
| maxBoard | 设计值（4→50） | P50=5→50 | 198 |
| zhabanRate（反向） | 设计值（30→45） | P50=25.39→50 | 198 |
| amountVsSame | 设计值 | 设计值保留（历史帧无 totalAmount，n=0） | 0 |

**样本局限（fail-visible 披露）**：
- limitStruct 三维真信号样本仅 198 槽（2026-07-30~09-30，18.6%）；另 349 槽 limitSummary 接口失败期假 0 已剔除（`ztCount` 有值但全日恒 0）。待样本积累后重校准（spec v3 §9）。
- limitStruct 缺失 520/1068（48.7%）→ 这些槽 7 维降级合成（skippedDims 可见），符合缺维降级设计。
- amountVsSame 全部缺失，7/8 维状态将持续到 totalAmount 积累 ≥20 交易日。
- trin 缺失 15 槽、yhPositive 缺失 1 槽（单边市场/无昨日行，聚合器 fail-visible 正常工作）。

## 4. 维度双计相关性（审计 S3/S4 裁决数据）

| 维度对 | Pearson | 裁决 |
|---|---|---|
| riskRowsPct × riskShare | **0.8225** | 高相关但 <0.95：保留等权两维进 T2（分母 total/judgeable 有信息差），回测平台消融后再议合并 |
| upRatio × attackShare | **0.2244** | 低相关（审计预期"结构性正相关"被证伪）：无重叠问题，S4 关闭 |

## 5. 其他断言（审计 N2/N3/清单项 4）

- **join 率**：P5=1.0、min=0.849（1 槽）——fallback 率≈0，规则口径 vs jev 口径的 fallback 行差异实际可忽略。
- **change vs pctChange**：并存的 12.1 万行中不匹配（>0.01）863 行（0.71%）——回退无语义漂移。
- **zhabanRate 量纲**：P50=25.4、max=52.5——百分数量纲确认（N3 断言通过）。

## 6. 代码变更清单（T1.5）

| 文件 | 变更 |
|---|---|
| `backend/analysis/hotlist/emotion_score.py` | _CALIB 全量替换为 jev 口径实测；删除高潮压制条款（B3）；`compute_emotion_score(evidence, slope)` 增加 slope 参数（B2 接线入口，stageCandidate 与 rawStage 同源 S10）；`map_stage(score, slope)` 签名简化 |
| `backend/analysis/hotlist/jev_state.py` | collect_slot_evidence 增加 pctChange→change 回退 + degraded 注记（历史行兼容） |
| `backend/operations/emotion_score_calibration_replay.py` | 新增（只读重放工具，重校准复用，spec v3 §9） |
| `tests/hotlist/test_emotion_score.py` | 8 测试：新增 slope 接线（B2）与全缺返回 None 用例；压制断言随删除移除 |
| `tests/hotlist/test_jev_state.py` | 新增 change 回退用例 |

验证：`pytest tests/hotlist/ -q` 全绿（211 passed）。

## 7. 下一步（T2 待用户确认后执行）

链切换按 plan v3 Task 2 执行：slope 接线（`_collect_intraday_state` 扩展 scorePoints）、score=None 方案 B（null+跳过+诊断）、stageCandidate 与 rawStage 同值、legacyCascadeStage 对照面、ingest 扩字段（T3）。
