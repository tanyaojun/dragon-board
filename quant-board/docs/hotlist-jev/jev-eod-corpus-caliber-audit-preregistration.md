# 日级 EOD 情绪语料口径审计与修复预注册

> 2026-10-22 起草。触发：用户要求参照
> `jev-slot-corpus-caliber-fix-preregistration.md` 的审计与修复方法论，对日级 EOD
> 情绪语料做全面盘点，给出优化建议和方案。
> 本役审计阶段为**只读 + 离线 dry-run**；用户 2026-10-22「确认，请执行」后落地
> 代码修复、存量代际打标、15:00 EOD 幂等触发，并按第二轮裁决重放 10-20/10-21
> 两个 EOD（真实 jev 2 次）。
> 状态：**已实施（v2.6 题目升代）**；执行记录见 §11，第二轮裁决修订见 §12。

## 0. 结论先行

1. **日级语料不是槽级语料的简单汇总**：它由「逐帧压缩行 + 当日累计」构成，
   **没有收盘帧全量证据**；而 `day_crowding` / `day_stage` 判据明确引用
   封板率、焦点高位股、题材分散——语料没有供给。按 AGENTS §1.2-6 的归因顺序，
   这是继①原料供给之后的**②题目设计层缺陷**，槽级修复没有覆盖。
2. **72 篇 EOD 全部 `status=ok`，但只有 9 篇在旧口径下「无缺失」**：
   52 篇至少一帧涨停证据缺失，56 篇至少一帧指数缺失，8 篇缺预期槽位或没有
   15:00 收盘帧。`status=ok` 只表示 jev 返回完整，不表示日级语料充分。
3. **28/72 篇的「最高连板峰值」与 15:00 帧真连板不一致**：
   10-19 声称 12 板（真 3 板）、10-21 声称 7 板（真 4 板）、10-14 声称 11 板
   （真 4 板）。另 21 篇 15:00 帧没有真连板可核。日级头部结论被区间口径系统性污染。
4. **72/72 EOD 文档 `evidenceRaw=None`**；且 07-01 15:00 帧的 `limitSummary`
   是 10-02 14:03 回填、EOD 文档是 10-02 11:52 生成——**历史 EOD 语料无法从
   当前帧复现**，不知道模型当时到底看到了什么。
5. **旧 `continuousBoards` 键未归一化**：当前代码仍会把 07-01 09:30 的
   `board1=7 / board2=3` 算成「涨停 0」——伪 0 在日级/回放链仍是活缺陷。
6. **最终裁决**（2026-10-22 第二轮）：补观察层（`evidenceRaw`/帧覆盖/结构化质量）、
   真连板 as-of、旧 schema 归一、当日累计、锚样本、代际标记与展示同步；
   **不补【收盘帧证据】块**，改为删减 `day_crowding` 判据中的封板率/焦点高位股/
   题材分散引用，`QUESTION_SET_VERSION` 升 **v2.6**；`corpusCaliberVersion` 切换日
   **2026-10-22**。

## 1. 审计范围与事实源

| 项 | 内容 |
|---|---|
| 代码 | `backend/analysis/hotlist/jev_state.py`、`backend/services/jev/jev_sentiment_compute.py`、`backend/snapshot_collector/service.py` |
| 集合 | `hotlist_jev_sentiment`（slot 671 / eod 72）、`snapshot_frames`、`snapshot_stock_rows`、`market_daily_amount`、`market_true_ladder` |
| 真值源 | 帧 `limitSummary.thsPools.pools`（THS 连板层五池）、`jiuyan_streak_map`（slot 修复已交叉核验）、15:00 帧涨跌/封板质量/触板回撤、`market_daily_amount` |
| 方法 | 库内只读盘点 + `compute_and_upsert_for_day(dry_run=True)` 离线 dry-run（monkeypatch 外部 THS 拉取，零 jev） |

## 2. 盘点事实

### 2.1 文档基数与代际

| 维度 | 事实 |
|---|---|
| EOD 文档 | 72 篇，`status=ok` 72/72 |
| 来源 | `sentiment_v2_pilot` 41、`sentiment_pilot` 21、`collector` 8、`manual` 2 |
| 版本 | `questionSetVersion=None` 41 篇（2026-07-01 → 08-31）；`v2.5` 31 篇（2026-09-01 → 10-21） |
| `evidenceRaw` | **0/72**（全部 None） |
| `anchoredSlotTime` | 15:00 69 篇；14:00 1 篇；13:30 1 篇；09:30 1 篇 |
| 答案分布 | legacy：day_crowding `insufficient_evidence` 29/41；v2.5：`late_seal_weakness` 13、`breadth_climax` 7、`no_crowding` 7、`top_acceleration` 3、`crowd_clearing` 1、`insufficient_evidence` 0 |

**代际不可直接比较**：41 篇 legacy 既无版本号，又处于帧覆盖最差的 7–8 月；
31 篇 v2.5 的语料供给也随日期变化。任何下游统计（`diagnose_jev_day_axis`、
`diagnose_jev_temp_crowding`、相位研究）若按 `kind=eod,status=ok` 直接聚合，
都在混代。

### 2.2 帧覆盖与证据质量（按 EOD 交易日逐日核对）

| 问题 | 天数 | 说明 |
|---|---|---|
| 至少一帧缺 `limitSummary` 有效证据 | 52 | 含 07-06/07/09 全帧缺失；09-01 有 5/10 帧缺失 |
| 至少一帧缺指数（4 主指数 + indexExtra） | 56 | 早期帧 `indices={}`；部分帧只有 `changePct` 无 `change` |
| 全帧缺指数 | 3 | 07-06、07-07、07-09 |
| 缺预期槽位或没有 15:00 | 8 | 07-06（4帧，末槽14:00）、07-07（3帧，13:30）、07-09（1帧，09:30）、07-13、07-20、07-23（3帧）、07-27（1帧）、09-11（6帧，缺13:00–14:30） |
| 旧口径下「无缺失」 | **9/72** | 09-30、10-08、10-09、10-13、10-14、10-15、10-16、10-20、10-21，全部 v2.5 |
| 数据质量行声称「两市总成交额缺失」 | 63 | 其中 10-12、10-19 的【当日累计】已给出成交额——质量行是假阴性 |

几个实证：

- **09-11**：只有 6 帧，缺 13:00–14:30，`status=ok`，`day_pattern=low_recover`。
  叙事没有任何「缺 4 槽」披露。
- **07-09**：只有 09:30 一帧，`status=ok`，`day_pattern=unclear`。
  「全天」日级判断建立在单帧上，却没有覆盖度标识。
- **10-19**：只有一帧缺指数，质量行只写「指数缺失」；不告诉模型/用户是哪一槽、
  缺的是主指数还是三指数。

### 2.3 语料结构与判据对照

`build_day_jev_state` 的现行结构（`jev_state.py:803`）：

```
头部 → 【近20日参照】 → 【逐帧证据】（format_evidence_line 压缩行）
     → 【当日累计】（新进/淘汰、主力净额、峰值、两市额）
     → 【数据质量】（字符串去重）
```

逐帧压缩行（`format_evidence_line`）**有**：7 指数、涨停数、真/区间最高板、
炸板率、五桶涨跌、TRIN、量能同期、主力净额、新进淘汰、昨涨停承接、
生命周期五键、强资/风险。

**没有**（但槽位当前帧段有）：

| 证据 | 对应判据 | 后果 |
|---|---|---|
| 封板率 `fengbanRate` | `late_seal_weakness`「炸板率高于参照 p50、封板率走低」 | 判据引用语料没有的证据；10-21 模型仍选 `late_seal_weakness`（0.66），但收盘帧实际封板率 72.46% 未被供给 |
| 封板质量 `sealQuality`（一字/秒板、硬板、开板重封、重封率、平均成功率） | 「封板不干脆」 | 无法判断封板质量，只剩炸板率单信号 |
| 触板回撤 `drawdown` | 高位股走弱/撤退压力 | 日级缺这一层 |
| 焦点个股 `leaders`（名称/题材/涨幅/涨停/生命周期） | `top_acceleration`「焦点高位股继续涨停」、`retreat`「高位焦点股走弱或断板」 | 判据点名「焦点高位股」，语料没有 |
| 涨停原因 `reasons` / 题材分布 | `no_crowding`「题材分散」 | 判据点名「题材分散」，语料没有 |
| 收盘帧逐项全量 | `day_crowding`「收盘时高位拥挤形态」 | 日级拥挤问题问了收盘态，却不给收盘帧全量证据 |

> 结论：`day_crowding` 是「收盘态」问题，但日级语料只给压缩行 + 累计摘要。
> 这不是措辞问题，是**题目判据与语料供给不一致**，属于 slot 修复未覆盖的②层。

### 2.4 真连板与锚

- 日级现行代码在 slot 修复后已改用 `maxTrueBoard`（`build_day_jev_state:820-830`），
  但**存量 72 篇叙事全部是旧口径**：0 篇含「真连板」字样。
- 用 15:00 帧五池重算真连板，与叙事「最高连板峰值 N 板」对比：
  - **28/72 不一致**；
  - **21/72** 的 15:00 帧没有五池可核；
  - 仅 23/72 一致。
- 实证：
  - 10-19：叙事 12 板，真 3 板；
  - 10-21：叙事 7 板，真 4 板（与 slot 14:00 事故同源）；
  - 10-14：叙事 11 板，真 4 板；
  - 10-15：叙事 11 板，真 5 板；
  - 10-20：叙事 6 板，真 4 板；
  - **10-16：叙事 11 板，真 11 板**（新华传媒 600825）——真口径不是一律下调，
    必须逐日核验，不能一刀切减。
- 锚同口径重算后，10-21 的「最高连板」由
  `p20=5 / p50=6 / p80=10（末值 6）` 变为
  `p20=4 / p50=5 / p80=7（末值 4）`。这会直接改变 `day_stage`/`day_crowding`
  的相对位置判读；存量答案是在污染锚下产生的。
- 日级「峰值」口径另有隐患：`build_day_jev_state` 对所有帧的 `maxTrueBoard`
  取 max，但历史回放中早盘帧通常没有真连板；只有 15:00 一帧时，它仍写
  「最高真连板峰值」——**用收盘值冒充全日峰值**。

### 2.5 历史回放的 as-of 污染

`_resolve_slot_true_ladder`（`jev_sentiment_compute.py:292`）在
`trading_date < today` 时对**每个槽位**调用 `_fetch_true_ladder(date)`，
返回该日 **EOD 收盘态**。因此历史日 EOD 重算时：

```
09:30｜...｜最高 4 连板｜...   ← 实际是 15:00 收盘态
10:00｜...｜最高 4 连板｜...
...
15:00｜...｜最高 4 连板｜...
```

槽位修复对单槽回放用 `_note_slot_ladder_caliber` 披露「真连板取该日收盘连板层」，
但日级把这条披露收进一行【数据质量】，**逐帧行仍以 as-of 形式呈现收盘态**。
日级语料的「轨迹」因此被抹平：早盘的真连板演变不可见。

### 2.6 历史语料不可复现

- 72/72 EOD 文档 `evidenceRaw=None`，只有 `narrativeRaw`/`responseRaw`。
- 07-01 15:00 帧当前 `limitSummary.source=ths_hist_backfill`，
  `capturedAt=2026-10-02T06:03:57Z`（14:03 +08）；EOD `computedAt` 为
  2026-10-02 11:52 +08。**EOD 先于回填生成**，当前帧不是模型当时看到的帧。
- 结果：无法审计「当时的语料 → 答案」因果；也无法判断 07-01 的
  `day_stage=ice` 是真实盘面还是「涨停 0 伪 0 + 指数缺 + 锚缺失」造成的。

## 3. 逐项缺陷与处置建议

### P0 — 正确性 / fail-visible

| # | 缺陷 | 实证 | 根因（代码定位） | 处置 |
|---|---|---|---|---|
| P0-1 | EOD 不落结构化证据 | 72/72 `evidenceRaw=None`；历史帧已回填，无法复现 | `compute_and_upsert_for_day` 的 doc 构造 `evidenceRaw: None`（`jev_sentiment_compute.py:596-604`；no_data/degraded 分支同样） | 新增 EOD `evidenceRaw`（逐帧摘要 + 收盘帧 + 覆盖度 + 质量），additive |
| P0-2 | 日级无收盘帧全量证据，判据引用未供给证据 | `day_crowding` 判据点名封板率/焦点高位股/题材分散；日级语料全无 | `build_day_jev_state` 只拼 `format_evidence_line`；未复用 `_format_current_evidence_section` | 第二轮裁决：**不补收盘帧块**，改为删减 `day_crowding` 判据引用并升 v2.6；详见 §4.2/§12 |
| P0-3 | 峰值用区间口径 + 历史回放注入收盘态 | 10-19 12 vs 真 3；10-21 7 vs 真 4；历史回放每帧都是收盘态 | 旧叙事用 `maxBoard`；`_resolve_slot_true_ladder:316-320` 对每个历史槽查 EOD | 峰值改真连板并标覆盖；历史日只允许 15:00 取 EOD 真连板，早盘不现查、不冒充 |
| P0-4 | 帧覆盖不披露 | 8 天缺槽/无 15:00；07-09 仅 1 帧仍 ok | `_slots_of_date` 只返回实际帧，不与 `_half_hour_slots()` 比；`build_day_jev_state` 无缺槽参数 | 新增 `frameCoverage`（expected/present/missing/lastSlot/hasClose），进叙事与落库 |
| P0-5 | 旧 `continuousBoards` schema 伪 0 | 07-01 09:30 原始 board1=7/board2=3，当前代码 `ztCount=0` | `collect_slot_evidence:260-270` 只读 yiban…，`zt` 回退 `sum(... or 0)`=0 | 归一化 `board1/board2/board3/board4plus`；仅当至少一个桶为数值时才求和，否则 None |
| P0-6 | 数据质量字符串去重、无槽位/计数 | 10-12、10-19 累计有成交额，质量行却说缺失；09-01 5 帧缺涨停只写一次 | `build_day_jev_state:809-813` 的 `if item not in degraded` | 结构化质量计数（按槽位、按证据种类、按收盘/盘中分离），叙事用摘要 |

### P1 — 语义 / 汇总

| # | 缺陷 | 处置 |
|---|---|---|
| P1-1 | 【当日累计】不完整：缺收盘/峰值涨停数、收盘炸板率/封板率、收盘封板质量、as-of 槽位 | 增加收盘摘要；「主力净额」标注截至槽位 |
| P1-2 | 昨日成交额基线只取昨日 15:00 帧，缺 `market_daily_amount` 回退 | 与今日同源回退；缺失如实标 |
| P1-3 | 锚只报 p20/p50/p80，不报每个指标有效样本数/来源 | 指标行追加「有效样本 N/20」；最高连板标注来源覆盖（槽文档/帧/参考集合/None） |
| P1-4 | 日级删去了槽级「昨涨停承接」等全量行，但 `day_pattern` 判据依赖末段强弱 | 收盘帧全量块已覆盖；保持压缩行承载轨迹 |
| P1-5 | 槽级降级噪音泄漏到日级：`热度字段未采集` 出现在不渲染焦点个股的日叙事 | v2.6 日级不渲染焦点个股 → 热度降级项一律不进日级质量段（已修） |
| P1-6 | 压缩行生命周期全零不标缺 | 压缩行追加 `(缺N)`，或全缺时写「生命周期缺」 |

### P2 — 代际 / 运维 / 展示

| # | 缺陷 | 处置 |
|---|---|---|
| P2-1 | 41 篇 legacy 无 `questionSetVersion`，与 v2.5 混用 | 不伪造版本；新增 `corpusCaliber` 派生标记（`legacy_unversioned` / `pre_eod_fix` / `eod-2026-10-22`）；下游按代过滤 |
| P2-2 | 日级 EOD 由 `daily` 快照触发，不保证 15:00 已到 | 落库 `hasCloseFrame`；展示角标；可选：15:00 帧到达后幂等重跑 EOD |
| P2-3 | 前端 EOD 卡只显示答/分，看不到覆盖度/收盘缺失 | 增加覆盖度/降级角标；与 §1.2-5 文档-展示同步义务一致 |

## 4. 口径裁决建议（建议采纳）

1. **EOD 文档落 `evidenceRaw`**：存逐帧 evidence 摘要（与 slot `evidenceRaw` 同构）
   + `close`（收盘帧完整 evidence）+ `frameCoverage` + `quality`。这是审计/回放的
   唯一凭据，必须在本役补上。存量 72 篇不伪造 `evidenceRaw`；可标注
   `evidenceRawUnavailable=true`。
2. **不增加【收盘帧证据】块**（2026-10-22 第二轮用户裁决）：日级叙事保持
   「逐帧压缩行 + 当日累计」；改为删减 `day_crowding` 判据中的封板率、焦点高位股、
   题材分散引用，题目升 **v2.6**。槽级判据与槽位当前帧段不变（槽级证据仍在）。
3. **真连板 as-of 与峰值标签**：
   - 当前日：优先已存槽文档 `evidenceRaw.limit.maxTrueBoard`（真 as-of）；
     15:00 帧连板层优先；早盘缺则 `真连板该帧未采集`，**不现查**。
   - 历史日：只允许 15:00 槽取 `ths_date_eod`；其余槽不现查。若只有收盘帧有真连板，
     写「收盘真连板 N 板」，不写「全日峰值」；若覆盖 ≥ 全部预期槽，
     才写「全日真连板峰值 N 板（M/M 帧覆盖）」。
   - 区间 `maxBoard` 保留为标注，不参与峰值口径。
4. **帧覆盖与质量结构化**：
   - `expectedSlots`（`SLOT_TIMES["half_hour"]`）、`presentSlots`、`missingSlots`、
     `lastSlot`、`hasCloseFrame`、`skippedFrames`（frame 缺失/rows 空）。
   - 质量按证据种类计数：`indicesMissingSlots`、`limitMissingSlots`、
     `amountMissingSlots`、`lifecycleMissingRows`、`heatMissing`；
     叙事输出「N/M 帧缺指数（槽位…）」等，不再做字符串去重。
   - 盘中帧的「两市额缺失（历史帧无该字段）」不要与收盘帧的缺失混在一起：
     收盘有回退值时写「盘中 N 帧无量能字段；15:00 已用参考回填」。
5. **旧 schema 归一化**：`board1→yiban`、`board2→erban`、`board3→sanban`、
   `board4plus/board4Plus→sibanPlus`；`ztCount` 缺失时仅对数值桶求和，
   否则 None。禁止再出现「有 board1/board2 却报涨停 0」。
6. **当日累计增强**：
   - 收盘帧涨停数、收盘炸板率/封板率；
   - 全日最高涨停数（按帧）、最高真连板（带覆盖）；
   - 主力净额/新进淘汰标注「截至收盘帧」或「截至末帧 hh:mm」；
   - 昨日成交额基线允许 `market_daily_amount` 回退，缺失标缺；
   - 封板质量/触板回撤/焦点个股/涨停原因**不进日级**（v2.6 裁决）。
7. **锚样本披露**：每个指标行追加有效样本数（如「涨停数：p20=…（有效 19/20，缺 09-23）」）；
   最高连板另标来源覆盖。保留现有首行 `historyAnchorRange` 合同，避免前端 chip 漂移。
8. **代际边界**：新增 `corpusCaliberVersion`（`legacy_unversioned` /
   `v2.5_pre_eod_fix` / `eod-2026-10-22`），随 EOD 落库；`QUESTION_SET_VERSION`
   升 **v2.6**（日级判据删减）。跨代统计以 2026-10-22 为界；
   legacy 41 篇与 v2.5_pre_eod_fix 31 篇不参与新口径统计。
9. **题目升 v2.6**：`day_crowding` 判据删除封板率、焦点高位股、题材分散引用，
   保留涨停数/连板梯队/炸板率/参照分位；槽级 `crowding` 判据文本不变
   （槽位当前帧段仍供给这些证据），但同盖 v2.6 戳。
10. **触发与展示**：EOD 落库记录 `hasCloseFrame`；15:00 half_hour 到达后幂等重跑
    EOD，daily 15:30 触发对「同代 + ok + 收盘帧完整」文档直接复用（不重复烧调用）；
    前端对 `hasCloseFrame=false` 或覆盖不足显示角标；不阻断写库/展示。

## 5. 落库字段变更（additive-only）

EOD 文档 `hotlist_jev_sentiment` 新增：

```text
evidenceRaw: {
  frameCoverage: {
    expectedSlots: [...], presentSlots: [...], missingSlots: [...],
    lastSlot: "15:00"|"14:00"|..., hasCloseFrame: bool,
    frameCount: int, expectedCount: int, skippedFrames: [{slot, reason}]
  },
  frames: [ {slotTime, indices, indexPct, limit, breadth, fund, turnover,
             yesterdayLimit, lifecycle, lifecycleMissing, rowFlags,
             totalAmount, quality} ... ],          # 与 slot evidenceRaw 同构
  close: { ...同上 + leaders + reasons + reasonsTotal... },  # 审计用；v2.6 不进模型叙事
  summary: {
    peakZt: int|null, closeZt: int|null, peakTrueBoard: int|null,
    trueBoardFrames: int, trueBoardCoverage: "close_only"|"full"|"partial"|"none",
    closeZhabanRate: float|null, closeFengbanRate: float|null
  }
}
corpusCaliberVersion: "eod-2026-10-22"
frameCoverage: { ...同上（顶层冗余，便于查询） }
evidenceRawUnavailable: true        # 仅存量回填标记，不用于新文档
```

不删除/不改名任何既有字段；`answers`/`scores`/`responseRaw`/`narrativeRaw`
合同不变。存量 72 篇不回写 `evidenceRaw`；只允许加 `corpusCaliberVersion`
（legacy 标记）与 `evidenceRawUnavailable=true`，需另行裁决。

## 6. 不同步范围（列披露）

| 轨道/消费 | 处理 |
|---|---|
| `emotion_score` 规则链 | 零改动；它不消费 jev EOD 语料 |
| `hotlist_sentiment` 规则情绪链 | 零改动 |
| slot 级 jev 语料/题目 | 槽级判据文本不改；slot 修复已落地 1b3ea22c；10-22 后同盖 v2.6 戳 |
| 存量 72 篇 EOD `narrativeRaw`/`answers` | 除 10-20/10-21 按第二轮裁决重放外，其余 70 篇不回放、不覆盖 |
| `diagnose_jev_day_axis` / `temp_crowding` / `phase_caliber` | 结论需按代重审；代码是否加版本过滤另行裁决 |
| 前端 EOD 卡 | 已补覆盖度角标（P2-3）：根面板 hero overview chips + relay EOD 行/表头；见 §11 |
| `QUESTION_SET_VERSION` | 升 `v2.6`（日级 day_crowding 判据删减；槽级判据文本不变但同戳） |

## 7. 验收基准（离线 dry-run，零 jev）

### 7.1 10-21 目标叙事

已用当前代码 + monkeypatch 外部 THS 拉取做 dry-run，确认以下变化：
- 7 指数 changePct（沪指/深成指/沪深300/中证500/中证1000/创业板指/科创50）；
- 15:00 行「最高 4 连板」，早盘行「最高区间 7 板」（不再冒充连板）；
- 【当日累计】「收盘真连板 4 板（仅收盘帧有真连板）」；
- 锚变为 `最高连板 p20=4 / p50=5 / p80=7（末值 4）`；
- 生命周期压缩行含「反转」。

**v2.6 目标**（第二轮裁决）：
- **不出现**【收盘帧证据】/封板质量/触板回撤/焦点个股/涨停原因（日级不喂）；
- 逐帧压缩行保留封板率与炸板率（判据可用），【当日累计】含收盘涨停 50、
  收盘炸板率/封板率、收盘真连板 4 板（仅收盘帧）、全日最高涨停；
- 【帧覆盖】10/10；【数据质量】写明「早盘 9 帧真连板未采集（收盘帧可得）」，
  不再泄漏「热度字段未采集」；
- `day_crowding` 判据已是 v2.6 删减版（无封板率/焦点高位股/题材分散）。

### 7.2 交叉核验

- 10-16：真连板 11 = 区间 11（新华传媒），不得被误降；
- 10-19：真连板 3，叙事应写「收盘真连板 3 板」，而非「峰值 12 板」；
- 07-01 09:30：旧 schema 归一后 `ztCount=10`、梯队 7/3，不得再是 0；
- 07-09：`frameCoverage 1/10, hasCloseFrame=false`，叙事明确「日级判读仅基于 09:30，
  不是全天口径」；
- 09-11：缺 13:00–14:30，叙事列出缺失槽；
- 10-12/10-19：质量行不得再声称成交额缺失（累计已给出）。

### 7.3 测试（TDD，全部「revert 即红」）

- `tests/hotlist/test_jev_state.py`：
  - 日级**不**含收盘帧全量块（v2.6）但含收盘累计事实；
  - 日级无收盘帧时 `hasCloseFrame=false` + 明确降级；
  - 日级真连板覆盖标签（close_only / full）；
  - 旧 schema 归一化 + 伪 0 防线；
  - 质量计数按槽位，不再字符串去重；
  - 日级不再泄漏 heat 噪音；
  - v2.6 day_crowding 判据不含封板率/焦点高位股/题材分散。
- `tests/hotlist/test_jev_sentiment_compute.py`：
  - EOD 文档落 `evidenceRaw`/`frameCoverage`/`corpusCaliberVersion`；
  - 历史日只对 15:00 取 EOD 真连板，早盘不现查；
  - 昨日成交额基线回退；
  - 缺失槽位/无 15:00 进文档。
- `tests/hotlist/test_jev_anchor_escape_alert.py`：锚样本披露不破坏现有告警字段。
- `tests/hotlist/test_hotlist_jev_api.py`：series/eod 响应保持向后兼容（新增字段不破坏旧字段）。

验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/hotlist/test_jev_state.py tests/hotlist/test_jev_sentiment_compute.py tests/hotlist/test_jev_anchor_escape_alert.py tests/hotlist/test_hotlist_jev_api.py -q
```

## 8. 实施顺序（建议）

| 阶段 | 内容 | 验收 |
|---|---|---|
| A 观察层 | EOD `evidenceRaw`/`frameCoverage`/`quality`/`corpusCaliberVersion`；质量计数 | 新 EOD 文档可审计；存量标记不伪造 |
| B 语料层 | **不补收盘帧块**；真连板 as-of/峰值标签；旧 schema 归一；当日累计；锚样本；`day_crowding` 判据升 v2.6 删减 | 10-21 dry-run 目标；07-01/07-09/10-19 交叉核验 |
| C 代际/展示 | legacy 标记；15:00 幂等触发 + daily 复用；EOD 覆盖度角标；文档同步 | 前端真实浏览器验收（playwright-cli）；文档-展示一致 |
| D 重放 | 仅 **10-20/10-21** 两个 EOD（第二轮裁决） | 真实 jev 2 次；产出 v2.6 文档并抽验 |

## 9. 回放与预算（第二轮裁决已确认）

- **只重放 10-20/10-21 两个 EOD**（用户裁决），不重放其余 70 篇；
- 每篇日级叙事 ≈ 3–5k input tokens，2 篇预算上限约 1 万 input tokens；
  真实调用走用户确认后的开火路径（AGENTS §1.2-7：pytest 禁调真实 jev）；
- 重放前备份两篇旧 EOD 到 `data/backups/`；重放后 `origin=replay`、
  `questionSetVersion=v2.6`、`corpusCaliberVersion=eod-2026-10-22`；
- 其余 70 篇只打代际标记，不补 `evidenceRaw`、不重算 `answers`。

## 10. 用户裁决（2026-10-22 已确认）

1. **升 v2.6**：不补【收盘帧证据】块，删减 `day_crowding` 判据中的封板率/
   焦点高位股/题材分散引用；
2. 存量 72 篇加 `corpusCaliberVersion`/`evidenceRawUnavailable` 标记（已执行）；
3. 历史日接受「早盘不现查、只标收盘真连板」（已实现）；
4. 15:00 帧到达后幂等重跑 EOD（已实现；daily 对完整 EOD 复用，避免重复调用）；
5. 重放范围：**只跑 10-20、10-21 两日**（已执行，见 §12）。

---

原问题留档：

1. 是否按 §4 补齐【收盘帧证据】块（推荐），还是改为删减 `day_crowding` 判据
   中对封板率/焦点高位股/题材分散的引用（需升 v2.6）？
2. 存量 72 篇是否只加 `corpusCaliberVersion`/`evidenceRawUnavailable` 标记
   （推荐），还是完全不动？
3. 历史日真连板：是否接受「早盘不现查、只标收盘真连板」（推荐，as-of 安全），
   还是允许「收盘态回填 + 逐帧标注」？
4. 是否在 15:00 帧到达后幂等重跑 EOD（P2-2），还是只落 `hasCloseFrame` 角标？
5. 重放范围：仅 10-20/10-21，还是 9 个干净日抽样；预算上限。

## 11. 执行记录（2026-10-22，用户「确认，请执行」）

### 11.1 代码/合同

| 文件 | 落地内容 |
|---|---|
| `backend/analysis/hotlist/jev_state.py` | 旧 `board1..board4plus` 归一 + 伪 0 防线；`format_evidence_line` 补封板率/生命周期缺数；当前帧段标题参数化 + 参考回填披露；日级【帧覆盖】+ 当日累计（**不补收盘帧全量块**）；质量按槽位/种类计数；真连板峰值覆盖标签（full/close_only/partial/none）；锚有效样本 + 来源覆盖；changePct-only 帧不再误报「指数缺失」；`day_crowding` v2.6 判据删减 |
| `backend/services/jev/jev_sentiment_compute.py` | EOD 落 `evidenceRaw`/`frameCoverage`/`corpusCaliberVersion="eod-2026-10-22"`；历史日仅 15:00 允许 EOD 真连板现查；昨日成交额 `market_daily_amount` 回退；锚取数链返回来源；`reuse_if_complete`（daily 复用完整 EOD） |
| `backend/snapshot_collector/service.py` | 15:00 half_hour 到达后幂等重跑 EOD；daily 触发对同代/ok/收盘完整文档复用 |
| `backend/api/hotlist_jev_routes.py` | `sentiment-overview` 透出 `anchoredSlotTime`/`frameCoverage`/`corpusCaliberVersion`/`evidenceRawUnavailable` |
| `src/types/hotlistJev.ts` | 新增 `HotlistJevFrameCoverage` 与 EOD 覆盖度/代际字段 |
| `src/components/panels/HotlistEmotionPanel.vue` | hero overview chips 覆盖度角标（缺收盘帧/缺槽位，不静默） |
| `backend/relay_page/index.html` | EOD 行角标 + EOD 卡顶部覆盖提示 |
| `backend/operations/tag_eod_corpus_caliber.py` | 存量 EOD additive 打标（幂等）；不改叙事/答案 |

### 11.2 存量迁移

- dry-run：72 篇待打标，41 `legacy_unversioned` + 31 `v2.5_pre_eod_fix`；
- `--apply`：已打标 72 篇；幂等重跑待打标 0；
- 复核：72 篇 `narrativeRaw` 全部保留；`evidenceRaw` 仍为 None（不伪造），
  `evidenceRawUnavailable=true`。

### 11.3 验证

- `pytest tests/hotlist tests/operations -q`：**1302 passed**（第二轮增补 v2.6/15:00 用例后）；
- `pnpm vitest run src/components/panels/__tests__/HotlistEmotionPanel.test.ts`：29 passed；
- `pnpm test`：143 files / 1219 tests 全通过；但收尾有 1–6 条 theme 服务异步
  unhandled rejection（`themeSummariesOrdering` / `ThemeRuntimeCoordinator`，单独跑该文件 6/6
  通过）——本次改动未触碰 theme 链，属并行运行既有噪音，单独记录不掩盖；
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过；
- 真实浏览器（playwright-cli，2026-10-22）：
  - 根看板 5173 热榜情绪面板：0 console errors；注入 `frameCoverage`
    （`hasCloseFrame=false`）后 hero chips 出现「EOD 缺收盘帧（末帧 14:00）」；
  - relay 页 8008：EOD 行出现「无收盘帧」角标、EOD 卡顶部出现
    「⚠️ 日级语料覆盖：缺 15:00 收盘帧（末帧 14:00）（覆盖 9/10）」；仅 favicon 404
    环境噪音；
  - 截图：`../.playwright-cli/page-2026-10-22T01-07-36-386Z.png`（根面板）、
    `../.playwright-cli/page-2026-10-22T01-05-33-626Z.png`（relay）。

### 11.4 离线 dry-run 对照

- **10-21**：7 指数 changePct；**无收盘帧全量块**（v2.6）；
  【帧覆盖】10/10；【当日累计】收盘涨停 50、收盘炸板率 28%、收盘封板率 72%、
  收盘真连板 4 板（仅收盘帧有真连板）、全日最高涨停 50；质量段
  「早盘 9 帧真连板未采集（收盘帧可得）」且无热度噪音；锚最高连板
  `p20=4/p50=5/p80=7`，来源「15:00帧 17 / 参考集合 3」。
- **10-16**：真连板 11 板（未误降）；主指数 changePct-only 帧不再误报「指数缺失」，
  质量段改「三指数缺席 9/10 帧」。
- **07-09**：帧 1/10、无收盘帧，叙事显式「日级判读非全天口径」。
- **07-01 09:30**（旧 schema 单测）：`ztCount=10`、梯队 7/3，不再是伪 0。

### 11.5 明确未做（列披露）

- 除 10-20/10-21 外，其余 70 篇存量 EOD 不重放（无 evidenceRaw、语料残缺）；
- 测试全 mock；真实 jev 仅用于第二轮裁决授权的 10-20/10-21 两篇 EOD；
- 新 EOD 文档将在下一交易日收盘/15:00 帧到达后自然生成并首次携带
  `evidenceRaw`/`frameCoverage`/v2.6 叙事；届时需在前端复核一次真实数据角标。

## 12. 第二轮裁决执行记录（2026-10-22，用户「请执行裁决项修改」）

### 12.1 五项裁决落地

| # | 裁决 | 落地 |
|---|---|---|
| 1 | **升 v2.6**（不补收盘帧块，删减 day_crowding 判据） | `QUESTION_SET_VERSION="v2.6"`；新增 `_DAY_CROWDING_CRITERIA_V26`，删除封板率/焦点高位股/题材分散引用，槽级判据文本不变；`build_day_jev_state` 不渲染【收盘帧证据】/封板质量/回撤/焦点/原因，保留压缩行+当日累计 |
| 2 | 存量 72 篇加代际标记 | 已 `--apply`：41 `legacy_unversioned` + 31 `v2.5_pre_eod_fix`；`evidenceRawUnavailable=true`；叙事/答案未动；10-20/10-21 重放后为新代，最终保留 70 篇标记 |
| 3 | 历史日早盘不现查、只标收盘真连板 | `allow_historical_eod_ladder=False` 对非 15:00 槽生效；`_stored_doc_ladder` 保留落档来源，日级早盘拒绝复用 `ths_date_eod` 存档；重放结果 `trueBoardCoverage=close_only` |
| 4 | 15:00 帧到达后幂等重跑 EOD | `snapshot_collector` 在 half_hour 15:00 后调用 `compute_and_upsert_for_day`；daily 触发传 `reuse_if_complete=True`，对「同代+ok+收盘帧完整」EOD 直接复用，避免重复真实调用 |
| 5 | 只重放 10-20/10-21 | `backend/operations/jev_eod_replay.py` 已执行；两篇 EOD 覆盖为 v2.6/origin=replay；旧文档已导出 `data/backups/` |

### 12.2 重放结果（真实 jev，4 次调用）

第一次重放后发现：10-20/10-21 的早盘 **槽文档**是 10-22 09:00 单槽回放产物，其
`trueBoardSource=ths_date_eod`；日级复用存档把收盘态当成逐帧 as-of（10/10 帧真连板）。
按第 3 项裁决修正后重放一次，最终结果：

| 日期 | status | day_temperature | day_stage | day_pattern | day_crowding | trueBoardCoverage | 帧覆盖 |
|---|---|---|---|---|---|---|---|
| 2026-10-20 | ok | 57.6 | ferment | wide_swing | late_seal_weakness | close_only | 10/10，收盘帧 15:00 |
| 2026-10-21 | ok | 50.3 | ferment | rally_fade | late_seal_weakness | close_only | 10/10，收盘帧 15:00 |

- 两篇均 `questionSetVersion=v2.6`、`corpusCaliberVersion=eod-2026-10-22`、
  `origin=replay`、`evidenceRaw` 完整；重放覆盖后，代际标记现存 **70 篇**
  （41 `legacy_unversioned` + 29 `v2.5_pre_eod_fix`），10-20/10-21 已是新代；
- 叙事无【收盘帧证据】块；10-21 早盘行「最高区间 7 板」、15:00「最高 4 连板」、
  累计「收盘真连板 4 板（仅收盘帧有真连板）」；质量段「早盘 9 帧真连板未采集」；
- 总用量：input ≈ 18,711 tokens / output ≈ 1,002 tokens（含第一次被修正前作废的
  2 次调用）；备份文件：
  `data/backups/jev-eod-replay-20261022-093612.json`（原始 v2.5 两篇）、
  `data/backups/jev-eod-replay-20261022-093825.json`（第一次 v2.6 中间态两篇）。

### 12.3 验证

- `pytest tests/hotlist tests/operations -q`：**1302 passed**；
- `pytest tests/hotlist tests/operations tests/snapshot_collector -q`：
  **1898 passed**（含 15:00 触发 EOD 回归）；
- 前端热榜面板 29 passed；`vue-tsc` 通过；真实浏览器角标验收沿用 §11.3
  （覆盖度角标逻辑未受 v2.6 判据删减影响）；
- 10-20/10-21 真实 EOD 已在前端可读（`sentiment-overview` 返回 v2.6、覆盖度完整）；
  relay 页 10-21 实测：`v2.6` / `eod-2026-10-22` / 10/10 覆盖 / dayTemp 50.3，
  覆盖完整故不出现缺口角标（仅 favicon 404 环境噪音）；
  截图 `D:\dragon-board\.playwright-cli\page-2026-10-22T01-52-09-039Z.png`。

### 12.4 残余（列披露，不在本次裁决范围）

- `day_stage.retreat` 判据仍含「高位焦点股走弱或断板」；日级不供给个股名单，
  暂由昨涨停承接/生命周期计数代理。若后续要求逐字锚定，需再升题目代际。
- 10-20/10-21 的 slot 文档仍为 v2.5（本次只重放 EOD）；day 语料不再消费其
  `ths_date_eod` 早盘真连板，故不影响本次 EOD 口径。
- 重放使用真实 jev，模型答案非确定性；本次观测差异（如 10-21 day_temperature
  59.6→50.3、day_pattern wide_swing→rally_fade）同时受语料/判据/随机性影响，
  不单独归因于 v2.6。

## 13. 第三轮独立审查处置（2026-10-22，用户「安排subagent code review，修复后提交」）

两个只读 reviewer 分别审查后端主链与前端契约；无 P0/P1。确认问题与处置：

| 编号 | 严重度 | 问题 | 处置 |
|---|---|---|---|
| 后端 P2-1 | P2 | 历史非收盘槽若帧池为 `ths_hist_backfill`，`_frame_has_true_ladder` 捷径在 as-of 守卫之前返回，收盘态连板可冒充早盘 as-of | 新增 `_frame_ladder_backfilled`/`_frame_ladder_allowed`；非 15:00 槽不采信回填帧池，`collect_slot_evidence` 走 None + degraded 披露；日级复用 `allow_frame_ladder` 同步阻断外部供给捷径；新增回归用例 |
| 后端 P3-1 | P3 | 帧缺 `snapshotId` 被误标 `rows_empty` | 先判 snapshotId，返回 `snapshot_missing`；新增用例 |
| 后端 P3-2 | P3 | EOD no_data 返回无 `reason`，collector warning 渲染 `None` | 两条 no_data 路径补 `reason`/`errorDetail`；collector 回退 `errorDetail`；新增 collector 接线用例 |
| 后端 P3-3 | P3 | `build_day_jev_state` docstring 仍写「增加【收盘帧证据】」，与 v2.6 相反 | docstring 改为 v2.6 口径 |
| 后端 P3-6 | P3 | 重放脚本无测试；dry-run 不显示现有 EOD 代际，重复 `--apply` 会烧调用 | 新增 `tests/operations/test_jev_eod_replay.py`；dry-run 打印现有 status/qver/corpus/收盘帧/day_temp |
| 后端 P3-7 | P3 | collector 层仅覆盖 15:00 ok 路径 | 新增 15:00 no_data warning 与 daily `reuse_if_complete=True` 接线用例 |
| 前端 P2-1 | P2 | relay EOD 覆盖提示 `<div>` 塞进 `<table>.innerHTML`，被匿名表格压成单列 | 新增 `#eodCovNote` 表格外容器，`renderEod` 分离注入 |
| 前端 P2-2 | P2 | 主面板 `missing || empty` 把帧缺失与证据空折叠成「缺 N 帧」 | 抽 `formatJevCoverageHint` 纯函数：缺槽位/空证据分开计数并给位置；新增 2 组运行级单测 |
| 前端 P3-1 | P3 | relay EOD 卡不提示空证据帧 | `renderEod` 纳入 `emptyEvidenceSlots` 并独立披露 |
| 前端 P3-2 | P3 | no_data 全无帧被角标说成「无收盘帧」 | `frameCount===0` 分支显示「无帧」/「当日无帧」 |
| 前端 P3-3 | P3 | 覆盖角标测试仅静态字符串断言 | 新增 `formatJevCoverageHint` 真实分支单测；浏览器注入三种形态复核 |
| 前端 P3-5 | P3 | `evidenceRawUnavailable` 只透 API，UI 未消费 | 主面板角标「历史证据未落档」；relay EOD 行徽标 + 卡顶提示 |

### 13.1 验证

- `pytest tests/hotlist tests/operations tests/snapshot_collector -q`：**1907 passed**；
- `pnpm test`：**143 files / 1221 tests passed**；`vue-tsc` exit 0；
- 真实浏览器（8008 relay）：10-21 完整覆盖无角标；10-19 存量显示「历史证据未落档」；
  注入缺槽位+空证据显示「缺槽位…；空证据帧…」，注入 0 帧显示「无帧」；
  `#eodTable` 直接子节点仅为 `TBODY`，提示位于表格外；仅 favicon 404 环境噪音；
- 真实浏览器（5173 主面板）：注入缺口显示「覆盖 10/10：缺槽位…；空证据 3 帧（…）」，
  存量显示「历史证据未落档」，0 帧显示「EOD 无帧（0/10）」；0 console errors；
- 截图：`.playwright-cli/page-2026-10-22T02-55-02-761Z.png`（relay）、
  `.playwright-cli/page-2026-10-22T02-57-58-584Z.png`（主面板）。

### 13.2 残余

- `jev_eod_replay.py` 仍无「新代自动跳过」开关；dry-run 仅展示代际，是否重复重放由调用者判断。
- relay 页空证据仅列槽位，不带 `reason`（主面板给计数+位置）；逐槽 reason 可在行展开/API 查看。
- 本轮修复未新增真实 jev 调用。