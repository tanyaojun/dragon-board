# 日度情绪一句话（jev daily line）设计与预登记（2026-10-08，用户裁决"可以，请继续"）

## 0. 一句话

前端热榜情绪面板「市场情绪阶段」hero 区新增一行当日读数，例：
**「节后首日情绪高开低走收弱势带，策略基线无入场」**。

句子 = 版本化模板 × 槽位值。**jev 只做一道选择题（日内形态归层），永不生成措辞**——
措辞漂移被结构性消灭（2026-10-03 jev score 分布归因措辞漂移教训）。

## 1. 槽位分解与事实源

| 槽位 | 例值 | 来源 | 为什么不给 jev |
| --- | --- | --- | --- |
| 日历标签 | 节后首日 | 规则：与上一 EOD 交易日间隔 ≥4 天（跨周末=3 天不触发） | 可数事实 |
| **日内形态** | 高开低走 | **jev choice 归层**（规则机械判兜底+交叉核对） | 唯一无规则单一事实源的语感题 |
| 收盘带 | 弱势带 | 引擎 `band_of_score`（execution.py BAND_TAGS 唯一来源） | 让 jev 重判=制造第二事实源 |
| 策略动作 | 无入场 | 脉拍步当月 tradeCount（phase_monitor pulse 文档） | 数据事实 |

## 2. 语料包三层（打标链七教训逐条对齐）

### 2.1 state 原料（教训5：叙事要给锚点，全部可数）

- 当日曲线：盘中 slot 情绪分序列（**不含 EOD 槽**，EOD 是 15:00 的衍生锚，重复计入会污染 min/max）
  → 派生特征值：`open / close(来源标注 eod|last_slot) / peak / peakTime / trough / troughTime / range /
  openPos / closePos / peakPos / troughPos`（Pos=在日内振幅中的位置 0-1，peakPos/troughPos=时刻序位 0-1）
- 参照锚：昨日 EOD、近 20 个 EOD 分的**当日分位**（as-of 仅取 < 当日，无前视；数据源同 `phase_pulse.load_eod_scores`）
- 引擎/策略事实：EOD 分、带 tag+展示名、当月脉拍 tradeCount
- 日历：`calendarFlag` + `prevEodGapDays`
- fail-visible：盘中槽 <5 或缺值 → `degradedSources` 结构化标注，shape 直接 unknown（不烧 jev——原料不齐时 jev 只能选逃生口，省预算且避免超证据判读）；缺失保持缺失，不伪造 0

### 2.2 questions（教训1/2/4/6：单道 choice 题、判据锚可数物、不设 score 题）

```python
DAILY_SHAPE_QUESTION = {
  "daily_shape": {
    "type": "choice",
    "instructions": "根据今日热榜情绪分曲线特征（开盘/收盘/峰值/谷值的日内位置与时刻序位），今日全天情绪路径属于哪种形态？只描述当日已发生曲线，不预测后市。",
    "criteria": {
      "高开低走": "开盘分处日内振幅前30%（openPos≥0.7）且收盘处后35%（closePos≤0.35）且峰值出现在前半段（peakPos≤0.5）",
      "低开高走": "开盘处后30%（openPos≤0.3）且收盘处前35%（closePos≥0.65）且谷值出现在前半段（troughPos≤0.5）",
      "冲高回落": "开盘不在极端高位（openPos<0.7）且峰值在前半段（peakPos≤0.5）且收盘落到下半区（closePos≤0.5）",
      "探底回升": "开盘不在极端低位（openPos>0.3）且谷值在前半段（troughPos≤0.5）且回升收在上半区（closePos≥0.5）且收盘不在峰值位（closePos<0.9）",
      "单边走强": "一路走高：收盘与峰值均在日内尾段（closePos≥0.9 且 peakPos≥0.9）且较开盘显著走高（closePos−openPos≥0.3）且开盘不在低位（openPos>0.3）",
      "窄幅震荡": "日内振幅过窄（range<8分），方向特征不可辨",
      "insufficient_evidence": "曲线槽位不足或关键字段缺失（通常不应落入：state 已给出全部特征值）",
    },
  }
}
```

**v2.1 教训落实**：判据只引用 state 已有字段（openPos/closePos/peakPos/troughPos/range），
零引用语料外的证据（如首封时间——v2.1 曾因引用语料没有的证据导致逃生口 33%）。
规则机械判与题目判据同数；机械判顺序即优先级：窄幅 → 高开低走 → 低开高走 → 冲高回落 →
单边走强 → 探底回升 → unknown（单边走强先于探底回升：收在峰值位的 V 型反弹归单边走强）。

### 2.3 输出合同

`call_jev` + `parse_jev_response(expected_keys={"daily_shape"})`（jev_client 既有合同）：
非 Completed / 缺题 → degraded，不伪造默认档；答案不在 choices 集 → 按无效答案 degraded。

## 3. 句子模板（单一事实源，版本化）

```
v1: {calendar}{情绪}{shape}收{band}，策略基线{action}
```

- `shape=unknown` 时省略形态子句（「节后首日情绪收弱势带，…」）；calendar 为空时自然前移
- `action`: tradeCount=0 → 无入场；>0 → 入场N笔；**None（当月 pulse 文档缺失）→ 读数暂缺**（不伪造）
- 模板常量 `SENTENCE_TEMPLATE_VERSION` 进代码（git 即历史）；改措辞必须升版本并在本文档登记
- 带词表 `SENTENCE_BAND_WORDS`（已实现登记）：键=引擎 BAND_TAGS（测试锁死键集合同步），值=句内用词
  「低温带/弱势带/高温带/极热带」——与 PULSE_BAND_LABELS（带展示名「××期」）是两套展示字典，均以引擎 tag 为单一事实源
- 参照锚护栏（已实现登记）：`eod_percentile` 历史样本 <8 返回 None 并登记 `eod20d_sample_small`（v2.2 教训：锚窗口不足不硬给）；
  历史 EOD 值为 None 的日期被剔除时登记 `prior_eod_none_dropped: n`
- jev 失败/缺席/无效 → 规则机械判 shape 兜底，`shapeSource=rule_fallback` + 结构化 degradedReasons；前端显示「规则」角标（§4.0 不阻断不伪装）；
  共享解析层意外异常（call/parse 炸穿）同样捕获降级为 `call_parse_exception` → 兑底，不丢当日句子

## 4. 挂链与存储

- 盘后链（16:00）新增 advisory 步 `jevDailyLine`（schedule.py）：门控=当日 EOD 情绪文档存在（与脉拍同门控）；
  子进程 `python -m backend.operations.jev_daily_line --date <d> --apply`；失败/跳过不翻转整体 ok；
  Mongo 入库新鲜度校验同其它步（phase_monitor `line:<date>` updatedAt）
- 产物：`phase_monitor` 集合 `kind=daily_line, _id=line:<date>`（`persist_daily_line`，幂等 upsert）
- 读口：`GET /api/phase-monitor/board` 增 `dailyLine`（最新一条；无文档时 `dailyLineMissingReason` 结构化说明）
- 前端展示：热榜情绪面板【热榜概览】「市场情绪阶段」大字（退潮/冰点/启动/发酵/高潮）后缀一行 📈 句子，
  面板挂载（overview 页签 immediate）即拉 board 数据
- 凭据：`JEV_CF_TOKEN`（.env.local，settings 已加载）+ `JEV_CF_ACCOUNT`（缺省 DEFAULT_ACCOUNT_ID）；
  token 缺失 → 不调用，规则兜底 + degradedReason 登记，**不 crash 排程链**

## 5. 预算与开火纪律（硬红线 §1.2#7）

- 调用频次：**每交易日 1 次**（EOD 后随盘后链），单调用 ≈1-2k tokens，月 ≈22 次
- **测试与 dry 模式零真调用**：CLI 不带 `--apply` 只算规则+拼句+打印（`skippedJev=true`）；
  pytest 一律 mock `call_jev` / fixture 回放
- 预登记开火记录：2026-10-08 用户裁决通过本设计（含 pilot 预算确认），排程链 16:00 起自动开火即本预登记的执行路径
- pilot 判据（前 3 个交易日，2026-10-09 起的自然交易日记账）：

| 门 | 判据 | 性质 |
| --- | --- | --- |
| 门1 形态一致率（主） | jev shape 与规则机械判一致率 ≥80%（分歧逐例按 原料→题目→解析 顺序归因，硬红线 §1.2#6） | 硬门 |
| 门2 degraded 率 | degraded 天数占比 ≤1/3 | 硬门 |
| 抽验 | 人工亲读 ≥3 天 state-答案-句子 对齐 | 硬门 |

- 门判不过 → 停开火回设计（不直接改判据迁就结果）；连过 → 转常态运行，月度在脉拍报告复盘时抽验

## 6. 已知边界

- 带标签沿用 PULSE_BAND_LABELS 展示名；情绪分序列缺日（如 EOD 在而盘中槽缺）按 degraded 处理，句子仍出（无形态子句）
- `daily_shape` 与 jev_state `day_pattern`（P5 挂起中）无口径关系，互不引用；若未来 day_pattern 复活需回头对齐
