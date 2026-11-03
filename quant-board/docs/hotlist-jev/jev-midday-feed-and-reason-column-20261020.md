# 涨停复盘【原因】列 + 午盘投喂槽位 + 连板股重复打标取证（2026-10-20）

> **2026-11-03 状态注记**：本文 §2 的「12:30 午盘投喂」已由用户裁决**移除**——午盘只采
> 名单（12:05 落 `jiuyan_action`，供盘中读口兑底），不投喂不打标；投喂打标统一在 16:00
> 盘后链 `jiuyanLabel` 步全量执行（单日每股一次幂等保留，供手动/回填兼容）。调度层
> `run_jiuyan_midday_label_once` / `jiuyan_midday_label_enabled` / `_JIUYAN_MIDDAY_LABEL_AT` /
> `_MIDDAY_LABEL_TIMEOUT_SECONDS` 已删除，`JIUYAN_MIDDAY_LABEL_ENABLED` 开关随删除一并失效；
> 随投喂移除，盘中 `ratePct20d` 读的存量 midday 反包板池不再自动日更（如需重算走
> `rewrap-pool-backfill --slot midday`）；其余内容（【原因】列、
> 伪午盘拒绝口径）仍然有效。下文按 2026-10-20 当时口径阅读。

> 用户需求三条（原文）：
> 1. 涨停复盘表格增加【原因】字段，取值是异动解析第一行（例：大业股份 603278 →
>    「人形机器人(金属腱绳)+商业航天+光伏+轮胎」）；
> 2. 12:00 从 jiuyangongshe.com 获取的午盘涨停数据，设 12:30 调度任务投喂给 jev 打标，
>    16:00 收盘涨停投喂时幂等跳过——一只涨停股票数据单日不能重复投喂；
> 3. 多日连板股票每日打标重复浪费 token：以大业股份 603278 为例（当日三连板），检查前两个
>    交易日投喂给 jev 的问题集与返回结果是否完全一致，若一致给出优化建议和方案。
>
> 本文记录 1、2 的落地口径与 3 的取证结论 + 优化方案。3 的**方案未实施**（属判据/成本改动，
> 需预登记与用户点头，见 §5）。

---

## 1. 【原因】列（已实施）

| 项 | 口径 |
| --- | --- |
| 取值 | 韭研 `jiuyan_action.fields[].stocks[].expound` 的**第一条非空行**（= 异动解析首行） |
| 单一事实源 | `backend/operations/jev_label_jiuyan.expound_reason()`（生产/读口/测试共用，禁第二套解析） |
| 读口 | `GET /api/hotlist-jev/limitup-labels` → 每行 `reason`；不在韭研名单的个股不挂该键（与 `boards` 同口径） |
| 缺失 | `expound` 空时才回退同义字段 `reason`（历史 schema 有此键，实测恒为 None）；两者皆空 → `None`，前端显示 `-`（不伪造原因） |
| 展示 | relay_page【涨停复盘】表新增【原因】列（封板列之后、驱动列之前）：列宽 260px 省略 + `title` 全量首行；行展开 `colspan` 11→12 |

实测核对（603278 大业股份，2026-10-16 / 10-19 / 10-20 三份名单）：

```
expound 首行 = 人形机器人（金属腱绳）+商业航天+光伏+轮胎
次行起      = 1、公司主营业务以胎圈钢丝…（逐条核实段落，不进原因列）
```

## 2. 午盘投喂槽位（已实施）

### 2.1 调度位置

| 时点 | 动作 | 承载进程 |
| --- | --- | --- |
| 12:05 | `jiuyan_action:{date}:midday` 午盘涨停名单采集（既有） | snapshot_collector（8001）`run_jiuyan_loop` |
| **12:30** | **`--slot midday` 投喂 jev**（新增：`schedule.run_jiuyan_midday_label_once`） | 同上（`asyncio.to_thread` 起子进程，隔离模型调用） |
| 15:35 | `jiuyan_action:{date}:final` 收盘涨停名单采集（既有） | 同上 |
| 16:00 | 盘后链 `jiuyanLabel` 步（既有）→ 午盘已投喂个股**自动幂等跳过** | QuantBoard After Market 计划任务 |

开关：`JIUYAN_MIDDAY_LABEL_ENABLED`（默认开；`=0` 关闭午盘投喂，收盘链行为不变）。

### 2.2 单日每股只投喂一次

幂等不靠新状态表，靠既有文档主键：

- 两个槽位共用 `_id={date}:{code}` 与同一 done 判据（`tradingDate=date, status=ok`）；
- 午盘投喂成功的个股 → 16:00 收盘运行打印 `skippedLabeled=N` 并跳过（测试
  `test_run_midday_then_final_skips_same_stock` 锁定「午盘 1 只 + 收盘只补午后新股 + 再跑零调用」）；
- `--force`（口径代际重放）是唯一例外，不受幂等约束（手工回填语义）。

### 2.3 午盘叙事的证据边界（fail-visible，AGENTS §4.0）

午盘只有「韭研午盘名单 + TDX 日线/5 分钟棒（当日为盘中未收值）」，因此
`build_midday_narrative` 只写午盘确实拿得到的证据，缺的一律写明不可得，**不拿昨日/盘中近似值冒充收盘口径**：

| 弹药 | 收盘槽位 | 午盘槽位 |
| --- | --- | --- |
| 盘面事实行（涨停/跌停/炸板率/梯队/最高板） | 15:00 帧 | **午盘不可得**（帧未生成） |
| THS 封板梯队/封板质量/炸板二分 | 15:00 帧 | **午盘不可得**（改用韭研 `N天M板` 口径披露） |
| 个股位置轴/板序 | 收盘日线棒 | 当日棒未生成 → **午盘不可得**（实测 12:30 本地 vipdoc 仍无当日棒），不拿 T-1 冒充当日 |
| 当日板型（首触/炸板波次/末封） | 5 分钟棒判定 | **午盘不可判**（直接标注） |
| 韭研异动解析全文 / 板块地位 | ✅ | ✅（板块家数为「已触板」口径并注明） |

文档侧留痕：标签文档新增 `labelSlot`（midday/final）、`jiuyanSourceId`、`jiuyanFetchedAt`；
读口透传 `labelSlot`/`jiuyanFetchedAt`；relay_page 行内以【午盘】徽标 + 时点 title 标注
（读者可分辨「这条标签是午盘还是收盘投喂的」，不会把午盘档当收盘档）。

### 2.4 顺带发现的数据缺陷：伪午盘文档

`{date}:midday` 只在 12:05 采集；但采集进程若在收盘后才启动，「午盘尝试」会立即用**收盘数据**
补写 midday 文档。实测：

| 交易日 | midday `fetchedAt` | 名单 | 说明 |
| --- | --- | --- | --- |
| 2026-10-13 | 12:06:31 | 54 只 | 真午盘 |
| 2026-10-14 | **20:22:04** | 57 只 | 与 final 逐字相同（伪午盘） |
| 2026-10-15 | 12:05:39 | 37 只 | 真午盘 |
| 2026-10-16 | **15:20:44** | 100 只 | 伪午盘 |
| 2026-10-19 | **20:04:07** | 63 只 | 伪午盘 |
| 2026-10-20 | 12:06:00 | 65 只 | 真午盘 |

因此 `midday_source_state()` 用 `fetchedAt` 的 HH:MM 卡窗（11:00–13:30）：窗口外一律
`skipped / midday_doc_not_noon` 并交收盘链投喂。**这条是午盘投喂的前置护栏，不是可选优化**——
否则「午盘投喂」实际会把收盘名单冒充午盘证据，且会在 16:00 之前就锁死当日标签。
（采集侧「重启后补写伪午盘文档」的根因修复不在本次范围，另行立项。）

- 残余风险（如实告知）：12:30 时 TDX 当日日线棒通常尚未写入，午盘叙事的**位置轴/板序**两项
  实际缺席，模型主要靠「解析正文 + N天M板 + 板块地位 + 热榜」判；若认为证据不足，把
  `JIUYAN_MIDDAY_LABEL_ENABLED=0` 即回到纯收盘投喂。

### 2.5 成本与回滚

- 成本：午盘名单 ≈65 只 ≈ 单日 ≈20 万 tokens（全库实测均值 3310 tokens/只，≈237k/日）；
  收盘链只为「午后新涨停 + 午盘名单外」的个股付费，合计**不超过**原先单次收盘投喂的量级。
- 回滚：`JIUYAN_MIDDAY_LABEL_ENABLED=0` 一行即可停午盘投喂，无需回退代码；已投喂的午盘文档
  `labelSlot=midday` 可查可审计。
- `--confirm-budget` 预算护栏保留：排程链常态携带（本次用户裁决=挂链批准），手工多日回填仍必须显式确认。

## 3. 连板股每日重复打标取证（603278）

### 3.1 问题集：**完全一致**

| 交易日 | questionSetHash | questionSetVersion | questionsRaw | ammoVersion |
| --- | --- | --- | --- | --- |
| 2026-10-16 | `b8bb2a3da29f` | v3 驱动四题 | 相同 | 2026-10-11a |
| 2026-10-19 | `b8bb2a3da29f` | v3 驱动四题 | 相同 | 2026-10-16a |

`questionsRaw` 逐字相等、`questionSetHash` 相同 → 判据代际没变（原料代际 ammoVersion 变了，
但解析全文那段原料没变）。

### 3.2 返回结果：**判定一致，概率不一致**

| 题 | 2026-10-16 | 2026-10-19 |
| --- | --- | --- |
| driver_type | concept_stretch（**0.77**） | concept_stretch（**0.84**） |
| catalyst_depth | core_main_business（**0.42**，new_business_early 0.39） | core_main_business（**0.46**，同名 0.38） |
| catalyst_freshness | continuing | continuing |
| buy_side_logic | sector_follow（**0.78**） | sector_follow（**0.99**） |

即：四项 `choice` 完全一致，概率分布小幅上移；`answers` 整体 `!=`（置信度/概率不同）。

### 3.3 叙事文本：13 行里 6 行逐字相同

两日叙事同为 13 行，逐行比对：

| 行 | 内容 | 是否逐字相同 |
| --- | --- | --- |
| 0 | 盘面事实行 | 否（当日盘面变） |
| 1 | 该股行（涨停价/时间/热榜） | 否 |
| 2 | 身位（THS 梯队/首封/主力净额） | 否 |
| 3 | 个股位置轴 | 否 |
| 4 | 板序 | 否 |
| 5 | 当日板型 | 否 |
| 6 | 板块地位 | 否 |
| 7 | 「韭研解析全文：」 | **是** |
| 8 | 解析首行（=涨停原因） | **是** |
| 9-12 | 解析 1/2/3/4 条核实段 | **是（4 行）** |

**全库同口径统计**（2026-09-01~10-19，29 个打标交易日，2079 个个股日文档，688 万 tokens）：

| 口径 | 数值 |
| --- | --- |
| 相邻交易日「同一只股」样本对 | 437 对 |
| 其中解析全文逐字相同 | 235 对（**53.8%**） |
| 解析相同里四项标签完全相同 | 121 对（**51.5%**） |
| 解析相同里仅买盘逻辑不同 | 53 对（**22.6%**） |
| 连板股相邻日对 | 339 对；解析逐字同 **51.3%**；其中四项标签全同 **52.9%** |
| 连板股叙事中「解析全文块」占字符比 | 中位 **57.2%** / 均值 54.2% |
| 连板股叙事中「与昨日逐字相同的行」占比 | 中位 **50.0%** / 均值 48.5% |
| 逐日实付均值 | 72 只/日、237k tokens/日、3310 tokens/只 |

### 3.4 归因（按 AGENTS §1.2-6 顺序）

1. **原料供给**：韭研对同一只股在连板期间**不重写解析正文**（603278 三天首行与四条核实段逐字相同）
   → 输入证据约一半是复用昨日原文。
2. **题目设计**：题目集逐字相同是**正确**的（同一判据、同一代际）；问题不在题干，而在
   「同一份证据被重复投喂」。
3. **协议/解析层**：无字段丢失（`answers`/概率/置信度都完整落库）。
4. 结论：**不是题目缺陷，是原料复用 + 每日盲投**。优化应作用在「投喂触发条件」与「叙事复用」，
   而不是重写题目集（重写会切断跨代可比性，须另走预登记）。

## 4. 优化建议与方案（2026-10-20 用户裁决：**采纳 A+B 并已实施**）

> 实施记录：`backend/analysis/hotlist/jev_carry_forward.py`（纯函数层）+
> `backend/operations/jev_label_jiuyan.py`（`carry_decision` 接入 `run()`/`_label_one`），
> 测试 `tests/hotlist/test_jev_carry_forward.py`（8 例：签名归一/压缩/准入 8 种 reason/
> 只问买盘/证据变化回退全量/开关与 --force）。默认开，`JEV_CARRY_FORWARD_ENABLED=0` 或
> `--no-carry-forward` 关闭。**B 的压缩范围经实测收窄**（见下），原估算 -9% 已修正。

### 方案 A：连板 carry-forward（推荐，性价比最高）

- 触发条件（证据签名未变才复用）：`code` 相同 + `questionSetHash` 相同 + `解析全文块` 逐字相同
  + `ammoVersion` 相同 + 上一标签日距当日 ≤ N（建议 2）个交易日。
- 复用范围：`driver_type` / `catalyst_depth` / `catalyst_freshness`（= 由解析正文决定的题）；
  **`buy_side_logic` 必须重判**（它吃当日盘面/板块接力结构，实测 22.6% 的同类样本就是它变了）。
- 落库：新建文档不覆盖昨日（仍 `_id={date}:{code}`），字段 `labelSource="carry_forward"`、
  `carriedFrom={date}`、`carriedFields=[...]`、`reevaluatedFields=["buy_side_logic"]`；
  读口/页面显示「承接」徽标，KPI 与分布统计可一键排除承接样本（可追溯，不伪装成当日独立判定）。
- 单 call 改造：只发 `buy_side_logic` 单题 → 输入可复用同一叙事（仍需叙事，token 降幅有限）。
- 收益（按 §3.3 实测）：全跳过口径省 **4.6%**（四项全同组）/ **8.7%**（含仅买盘差异组）；
  若只重判买盘（单题），估算节省 **≈50-60%** 的连板样本输入（连板样本占 23.7% token）
  → 全日节省约 **10-14%**。
- 风险：解析正文不变但市场含义可能变（例如同一题材当日从分歧转一致）；因此**必须**保留
  「买盘逻辑重判 + 相位分线重判」，且承接样本带 `carriedFrom` 供回测分组。

### 方案 B：解析全文去重压缩（与 A 互补）

- **实施口径（比原提案保守）**：承接路径只问 `buy_side_logic`，而它的判据只引用
  「解析中是否存在具体事件行」+ 板块地位/封板时间/连板高度（这些行一律保留）；
  `depth/freshness` 所需业务版图与日期证据已随承接不需要再被问。
  故压缩 = **保留「首行原因 + 事件型事项行」，省略非事件核实段**（并在原处写明省略条数/字数与前一日日期）。
- 实测收益修正：事件行占解析正文 **58%**（中位 59.6%，174 对样本）→ 正文降 ≈4 成、
  叙事降 ≈2 成；叠加 A 的 3 题免判，连板样本 token 降 ≈20%，**全日约 -2%**
  （连板且解析未变的只有 ≈6 只/日）。原提案里「-9%」是「整段正文都不下发」的口径，
  会系统性偏移买盘判定，**已否决**。
- 残余风险与护栏：doc 盖 `labelSource=carry_forward`/`carriedFrom`/`carriedQuestionKeys`/
  `reevaluatedQuestionKeys`/`carriedQuestionSetHash`/`narrativeCompression`；
  统计可一键剔除承接样本；`--force` 重放不受承接影响。

### 方案 C：连板降频（不建议单独使用）

- 规则：连板 ≥2 板的个股，只在「解析正文变化 / 买盘结构变化（板块龙头易主、板块涨停家数骤降） /
  板型恶化（炸板、反复开板）」时重判，否则沿用上一标签日。
- 收益最大（连板样本 23.7% token 可压到 ≈30-40% 剩余），但**丢时序粒度**：连板股恰是叙事最需要
  逐日跟踪的一档，判定时点缺失会让「分歧转一致/一致转分歧」的时序证据断档。建议仅在成本告警时启用。

### 执行顺序（已按此落地）

1. ✅ **A+B 已落地**（承接三题 + 买盘/相位重判 + 事件行保留压缩），字段齐全、可回溯、不碰题干；
2. 下一步不是 C，而是**题材层**（板块催化 × 龙头隔日连板概率）——
   设计、语料盘点与基线见 `theme-leader-nextday-preregistration-20261020.md`；
   真正的 token 大降档来自「只给龙头打标」（237k → ≈40k/日），A+B 只是顺手止血；
3. 方案 C 仅在成本告警时作为降级开关（env 门控，默认关）。

### 验收/防回归要点（任一方案实施时）

- 单测（已落）：同一签名 → 承接文档带 `carriedFrom` 且**只问买盘一题**；签名变化 → 全量四题重判；
- 离线重放（**待你裁决**，会消耗 token）：对 2026-09-01~10-19 已标样本抽样，比较
  「压缩叙事 vs 全文叙事」下 `buy_side_logic` 一致率，分歧样本逐条人工看；一致性不达标则回退全文；
- 读口/页面：承接徽标 + KPI 可排除承接；`hotlist_jev_driver_labels` 分布统计口径写明是否含承接；
- 预算：任何真实调用仍需 `--confirm-budget`；离线重放零模型调用。

## 5. 本次改动的验证

```bash
cd quant-board
./.venv/Scripts/python.exe -m pytest tests/hotlist -q
# 新增/改动覆盖：
#   tests/hotlist/test_jev_label_midday_slot.py      午盘槽位 14 例（时点门/幂等/叙事/fail-visible）
#   tests/hotlist/test_jev_board_info.py             expound_reason + 读口 reason
#   tests/hotlist/test_jev_limitup_labels.py         labelSlot/jiuyanFetchedAt 透传
#   tests/hotlist/test_relay_page_window.py          【原因】列 + 午盘徽标 静态守卫
```

手工校验（不影响生产）：

```bash
./.venv/Scripts/python.exe -m backend.operations.jev_label_jiuyan \
    --start 2026-10-20 --end 2026-10-20 --slot midday --dry-run
```

## 6. 部署注意

- 午盘投喂挂在 snapshot_collector（8001）进程内：**需要重启 8001 采集进程**才生效
  （重启后当天若已过 12:30，会自动补跑一次；`midday_source_state` 会拦住伪午盘文档）。
- 16:00 盘后链无需改动（`jiuyanLabel` 步天然幂等跳过午盘已投喂个股）。
- 新增 env：`JIUYAN_MIDDAY_LABEL_ENABLED`（默认 1=开）。

## 7. 2026-10-21 盘中复盘接线补全（v3.2b2，用户报障驱动）

本日盘中复盘链共三步接线，前两步上午完成（board_info/领涨/原因/封板时间兜底 +
`boardJoinSlot=midday` 口径注记），第三步为本轮补全：

### 7.1 报障与根因

用户报障：盘中涨停复盘**连板股全部显示「真连板未定」**。只读生产库复算（10-21 午盘，
`jiuyan_streak_map(allow_midday_fallback=True)`）：51 只全 None——根因是午盘兜底分支
一刀切 `jiuyanFinalFound=False → {code: None}`，把**韭研自证**的直取规则也误杀了。

### 7.2 修法（`jiuyan_streak_map` 午盘兜底分支，10-21 复盘口径）

韭研自证规则不依赖「今日封板」二分，午盘口径照常直取：

| 规则 | 午盘口径 | 依据 |
| --- | --- | --- |
| N==M（纯连板，如 2天2板） | **直取 M** | 韭研 num 自证窗口内每日板（含今日），无需 THS 二分 |
| num=None | **1**（首板口径） | 同 final 规则 |
| N>M（断板反包，如 3天2板） | **维持 None（未定）** | 「至今日」连板需今日封板二分，午盘触板≠封板，不按 M 伪算不猜链 |

fail-visible 三件套不破：口径由 `meta.middayFallbackUsed` / 读口 `boardJoinSlot=midday`
/页面「高度join=午盘名单」注记承担；**transitional 不落缓存**（final+15:00 帧落档后
重算即得终口径，不锁存盘中值）。

10-21 午盘 51 只实测：N==M 直取 12 只（2~4 板）、首板 30 只、N>M 未定 9 只
（002368 3天2板、603636 4天3板等反包股——收盘 final 落档后自动出终值）。

### 7.3 测试与遗留

- `tests/hotlist/test_jev_streak_map.py` 新增 3 用例（自证直取/transitional 不落缓存/N>M 维持 None），先红后绿；`tests/hotlist` **984 passed**。
- 遗留（待裁决）：N>M 反包股若要在盘中给「≥N 板（今日封板待确认）」下界（streakFloor），
  需 streak 值型扩展 + relay_page 前端改列文案，涉及真连板单源消费方（market_metrics 梯队/
  relay/复盘 KPI）合同，另立预注册。
- 部署：uvicorn（8000）/snapshot_collector（8001）需重启生效。
