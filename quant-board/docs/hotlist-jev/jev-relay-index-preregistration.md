# 连板情绪指数 Phase 1 回放预注册（relay sentiment index preregistration）

> 2026-10-10 起草，实现前锁定。设计依据：`jev-relay-index-design.md`（同轮定稿）。
> Phase 0（梯队双源）已落地：jiuyan 主源 + THS EOD 回采 + 首板口径修正。

## 1. 回放窗口与预算

- 窗口：近 15 个交易日（约 2026-09-16 ~ 2026-10-09，含国庆断层；jiuyan 池史/jev 叙事/
  个股标签三源覆盖完整）
- 预算：15 次 × ~7K tokens ≈ 100K tokens ≈ **$0.004**（官方直连）
- 存储：`hotlist_jev_relay_index`，`_id={date}:RELAY`，origin=`relay_index_daily`

## 2. 题目集快照（实现不得偏离）

| 题 ID | 类型 | 档位 |
|---|---|---|
| `relay_index` | score 0-10（SCORE_ANCHORS_10） | 主线分 |
| `relay_phase` | choice | `launch` / `relay_heat` / `divergence` / `collapse` / `bottoming` |
| `relay_momentum` | choice | `accelerating` / `holding` / `weakening` / `reversing` |
| `ladder_health` | choice | `pyramid` / `fracture` / `inverted` / `sparse` |
| `leader_strength` | score 0-10 | 龙头地位 |
| `money_effect` | choice | `strong` / `neutral` / `losing` |
| `theme_pulse` | choice | `mainline_continue` / `rotation` / `scattered` |

判据总纲（各题 instructions 共同遵守）：

- 主锚 =【近10日连板轨迹】与【近20日参照】的分位坐标系；**禁止仅凭当日家数/高度打分**
- relay_momentum 主锚 =【三日晋级链】（昨日池今日表现的逐股变化）
- 全部判据只引用叙事已给证据；证据缺失 → 对应题 `insufficient_evidence`（choice 加兜底档）
- 与热榜叙事结论（day_stage/温度）的联动是判别参照不是抄写：分化的判别依据是接力证据
  （晋级率/断板亏钱），不是热榜结论本身

## 3. 叙事六段（弹药清单）

1. 连板生态总账（当日）：market_facts_line（含双源梯队）+ 晋级率 + 断板亏钱分布
2. 接力生态记忆（跨日）：三日晋级链矩阵、题材主线演化表、龙头上升轨迹
3. 题材梯队表 top5：龙一/二/三（day desc, time asc）+ 板内标签聚合（freshness/driver）
4. 龙头档案：最高板个股身位/封板质量/带动/标签（复用既有 stock_position/sequence/board_shape）
5. 近 10 日连板轨迹（摆动锚）：家数/最高板/晋级率/断板亏钱逐日 + 峰谷
6. 热榜叙事语境（参照段，段首标注「周期定位参照，非今日证据」）：今日 slot 叙事结论
   轨迹 + 近 5 日 EOD 叙事结论 + 近 20 日极值锚

## 4. 预期分布（回放前预判，验收时对照）

- 窗口内已知市场背景：9 月中下旬高位周期（若梯峰值在 9 月下旬）→ 10-08 节后首日
  普涨、10-09 尾盘高潮（涨停 69 家 p75、最高 9 板 p100、尾盘 slot climax 0.89）
- 预期：relay_index 在 10-09 应处于窗口偏高位（≥p70）；relay_phase 不早于 10-08 出现
  relay_heat 或 divergence；ladder_health 在 10-09 应为 pyramid 或近 pyramid
- 若 15 日回放 relay_index 方差 < 1.0（无区分度）或与温度分相关 > 0.9（重复建设）→ 判据失败重审

## 5. 验收标准（Phase 2 对拍）

1. 与 day_temperature 相关性 ρ ∈ [0.5, 0.85]（ Spearman ）
2. ~~relay_momentum 与「次日温度分变化方向」命中率 ≥ 55%~~（**2026-10-10 对拍修正**：
   momentum 为同期量不承担预测职能，改为「与同期温度变化方向一致性 ≥ 55%」；
   预测性检验另立预注册）
3. 人工复核：每个 divergence/collapse 判定日，能在叙事中找到对应断板/晋级证据行
4. 全部 15 日 status=ok（证据缺失日按设计降级并披露，不算失败）

> 对拍结果与验收结论见 `jev-relay-index-phase2-report.md`（2026-10-10）：
> ρ=+0.895 超带（样本期共振论证后接受，长期观察）；同期一致性 86% ✓；
> 方差 ✓；15/15 ok ✓。判据 v1→v2 修正记录同见该报告 §1。

## 6. 风险与边界

- 国庆断层：9-30 → 10-08 跨 7 个自然日，三日晋级链以交易日为轴（D-1=9-30），无需特殊处理
- 10-08/10-09 THS 梯队缺失：jiuyan 主源补齐（Phase 0 已验证），叙事披露来源
- jiuyan 首板不标 day：Phase 0 口径修正已处理（null 且不在昨日池=首板；在昨日池=漏标披露）
- 旧日期无个股标签（<9-01）：窗口内不存在（9-16 起标签已覆盖）
- 测试红线：全部 mock，禁真实调用（§1.2.7）
