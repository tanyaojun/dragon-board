# 校准漂移监控设计（D 项，2026-10-08；冻结线经 audit P2-4 预登记「P10-P95 偏移>10 分触发」用户裁决进入 D）

## 0. 一句话

盘后链新增 advisory 步 `calibDriftMonitor`：滚动窗口对比存量文档各维 raw 分布与 `_CALIB`
分位锚，|漂移|>10 分告警落库——校准失真从「不可见」变「主动暴露」，并作为月度重校准
与第八维重启（A-① 冻结门）的就绪探测器。

## 1. 冻结判定线

```
窗口     = 最近 20 个交易日的全部非 EOD 槽位文档（按 tradingDate 升序取尾 20 日）
检测维   = 有 stored raw 的 6 维（upRatio/attackShare/riskShare/trin/yhPositive/riskRowsPct）
           limitStruct raw 恒 null（复合维）→ 结构性排除（limitation 登记，非静默）
锚定网格 = 主维 {P10/P25/P50/P75/P95 → 10/25/50/75/95}；
           反向维镜像网格 {P10/P25/P50/P75/P90 → 90/75/50/25/10}（P90 代 P95——权威源=
           .tmp/emotion-score-calibration.json 1068 槽分布与 _CALIB 锚点逐位对照确认：
           riskShare 0.9777=P90→10、trin 0.5056=P5→90/1.6815=P90→10；首跑曾用 100−P 镜像
           公式致反向维虚高告警，已修正并登记）
漂移     = _interp(_CALIB[dim], 窗口该维锚分位 raw 值) − 锚定期望分
告警     = 任一维任一锚分位 |漂移| > 10 分（冻结线）
持续漂移 = 同维同分位沿月度快照逐月回看，连续 ≥3 个月同向超阈 → sustained=true
           （市况结构变化候选，仅立项依据——触发后走一次性重定基预登记，监控仍不改锚；
           streak ≥2 即登记供早期观察；缺上月快照 fail-visible 登记 prevMonthsFound）
最小样本 = 窗口内该维有效 raw < 30 → 该维 skip（fail-visible 登记，不算告警）
就绪通知 = market_daily_amount 有 vsSamePct 的文档数 ≥20 → amountVsSame 重校准就绪
           （口径注：该 vsSamePct=相邻交易日对日级，槽级口径是否需另采由重校准预登记裁决）
```

- 单一事实源：直接 import `emotion_score._CALIB/_interp`，零曲线副本（对照：record_amount_vs_same
  为记录用复制了 CURVE_DESIGN，本监控不复制）；
- 幂等落库：`phase_monitor` `kind=calib_drift, _id=calib_drift:<YYYY-MM>` 月度 upsert（窗口/漂移/
  告警/就绪/生成时间全量随每次运行刷新，无历史快照膨胀）；
- advisory 语义：失败/跳过不翻转盘后链 ok；门控=当日 EOD 存在（与脉拍同门控）。

## 2. 月度重校准节奏（流程启用，非本次代码）

- 触发：①监控告警（任一维 maxAbsDrift>10）②月度例检（每月首个交易日报告人工过目）；
- 执行：重算尾窗分位锚 → 新旧 `_CALIB` diff → score 回放（EOD 档位迁移量）→ golden 对照 →
  用户裁决后才改曲线（评分口径变更，预登记制，监控本身只探测不重写）；
- 第八维重启路径：就绪通知 ready + 重校准曲线 → 随预登记重放一并裁决（A-① 冻结门重启条件）。

## 3. 验收

- 纯函数单测（分位插值/漂移/告警/最小样本/排除维）+ 假库 run 测试 + 排程步门控测试；
- 落地后真实跑一次 `--apply` 出当月首份漂移快照。

## 4. 首跑快照（2026-10-08，窗口 09-03~10-08 ×196 槽，已落库 calib_drift:2026-10）

**告警 9 条（真实分布漂移，月度重校准立项依据）**：riskRowsPct 全分位一致正向
（P50 +32.4 / P75 +20.2 / P90 +18.3：窗口中位 86.4 vs 校准期 94.0）、riskShare 同向
（P50 +24.4：0.864 vs 0.925）、attackShare P75 +11.6、trin P10 −11.8——近 20 日风险维
系统性回落。upRatio 9.3 / yhPositive 9.9 未过线。amountVsSame 就绪通知 ready（150 日）。
首跑镜像公式 bug 已修（见 §1 锚定网格注记）。
