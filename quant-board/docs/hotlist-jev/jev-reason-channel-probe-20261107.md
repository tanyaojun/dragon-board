# jev 平台 reason 输出通道调研（2026-11-07，5 探针定案）

## 背景

P1-1（C1 偏离义务可审计化）需要模型在 answer 对象附 `reason` 字段。11-06 生产重跑
（16 调用，v15）实证：state 尾部协议注被完全忽略，`answerReasons` 全空。本文记录
2026-11-07 的探针调研（总成本 5 次调用 ≈1.7k tokens，草稿题集非生产），结论**定案**：

## 结论：jev 平台（jev-1.14.0）不存在任何 reason 输出通道

| # | 通道 | 结果 |
|---|---|---|
| 1 | state 尾部协议注（P1-1 原方案） | 生产 16 调用实证：忽略 |
| 2 | state 头部「最高优先级」注 | 忽略（探针，374→432 input tokens） |
| 3 | questions 顶层附加键（如 responsePolicy 字符串） | **422**：`Input should be a valid dictionary`——平台对 questions 逐键 schema 校验，每键必须是题对象 |
| 4 | questions 题内附加键（answerReasonPolicy） | 请求通过但模型忽略（answers 仍只有固定四键） |
| 5 | 题面硬性要求附 reason（instructions 明示"缺 reason 视为无效"） | answers 仍只有 `{type, choice, confidence, probabilities}`——**answer schema 服务端强制，模型无能力输出额外字段** |
| 6 | text 自由题型 | 400 Invalid request——不支持 |

历史文档互证（`hotlist-jev-sentiment-design.md` §通道事实）：请求合同只有
`{state, questions}`，模型强制拒绝 messages/stream 等字段，无 system/preamble 通道。

## 处置（P1-1 改道，用户裁决"先调研"+"采纳建议"）

- **撤**：state 协议注（无效负载）与 `auditFlag=missing_reason` 标记（永不满足，无信号）。
- **立**：程序侧偏离审计——`theme_leader_label._anchor_deviation_audit`：读叙事
  「结构基线」行最细同桶率（样本<8 回退按连板高度桶，与规则①同口径），映射中枢桶，
  与模型档位比对，偏离≥1 档 → `auditFlag=deviation_from_anchor`（纯落库审计元数据，
  不覆盖答案、不进门、不改状态）。档位位移本身可程序计算，审计关注点从
  「理由是否合规」退到「偏离是否过多」（分布层面监控）。
- **保留**：`answerReasons` 容错透传（平台未来放开 answer schema 时零改动接住）。
- **观察指标**（`theme_leader_seal_stats.anchor_observations`，P2-3）：insufficient
  概率质量均值 / 最细桶 vs 高度桶读数差 / 偏离行数分布——登记不下结论，判据变更走预登记。
- 若未来需要模型自证理由：唯一可行路径是把「偏离必须降置信（confidence ≤0.5）」
  写进题面（confidence 在 answer schema 内，程序可验证）——属判据变更，走 v16 预登记。
