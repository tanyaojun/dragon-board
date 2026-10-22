# 热榜帧级情绪（slot 级 jev）语料口径修复预注册

> 2026-10-22 起草，用户裁决「采纳裁决建议，请执行」后开火。触发：用户报 10-21 14:00 槽
> 文档两类错误——①「指数与量能」缺科创50/创业板指；②「最高 7 连板」不正确（真连板
> 实际 4 板）。逐字段核对 narrativeRaw 后证实两项，另发现四项次级缺陷（C-F）。
> 归因（AGENTS §1.2-6 顺序）：全部落在①原料/语料供给层；题目设计（②）与协议解析层
> （③，`scores.temperature` = 5.31/9×100=59 换算正确）无新发现。
> 方法论与蓝本：`jev-relay-caliber-fix-preregistration.md`（2026-10-16 relay 口径事故
> 同族病灶在 slot 链的残留，本役即该预注册 §2.5「帧消费方留独立轨道」留下的尾巴）。

## 1. 审计结论（2026-10-21 14:00 帧，双源/多源交叉核验）

ground truth 源：帧 `indices.indexExtra`（库内直查）、THS 连板层五池
（`snapshot_frames.limitSummary.thsPools.pools`，hotspot_focus 真连板口径）、
`jiuyan_streak_map`（韭研 N==M 自证 + 封板链回溯）。

| # | 语料现值 | 修正值（实证） | 根因（代码定位） |
|---|---|---|---|
| 1 | 指数 4 只（沪指/沪深300/中证500/中证1000，点位口径） | **7 只**（+深成指/创业板指/科创50；帧 10-20 起已存 indexExtra：cybz -1.37%、kc50 +0.27%） | `jev_state._INDEX_KEYS` 只消费顶层 4 键，`indexExtra` 整块被滤掉——「采了被丢」与 relay v7 D2a 的 `providers._INDEX_ALIASES` 丢键同病，丢的位置在 jev 消费端 |
| 2 | 「最高 7 连板」（当前帧+已走帧 10:00 起每行+近20日锚 p20=5/p50=6/p80=10） | **4 连板**（603278/002724/600178 三只四连板；连板层 four=3/two=12/three=1 与 streak map 分布 3/12/1 完全吻合；7=断板股区间跨度 M） | `continuousBoards.maxBoard` 取 THS limit_up_pool `continue_day`=区间口径（`providers.py:2096-2108`）；relay §2.1 已裁决真连板单一事实源，帧契约不动、slot 消费方未切——**主坐标系（近20日锚）同被污染** |
| C | 已走帧压缩行生命周期只打 点火/扩散/拥挤/冷却 | 当前帧段有「反转 12」，压缩行不可见 | `format_evidence_line:410` 生命周期键位表漏 reversal；sequence_stage 退潮判据最需要的反转抬升轨迹（9→12）整段丢失 |
| D | 焦点个股 8 条全带「热度 0」 | 库内 232/232 行 heat=0（上游无供给），排序退化为 rank | 「热度 0」×8 纯噪音（v7 总纲「不该有的一个都不要喂」），且未披露 |
| E | 涨停原因只列 5 条无口径 | 36 只涨停股有 reason（全部唯一、计数恒 1） | `most_common(5)` 任意截断且未披露「36 只中列 5」 |
| F | 【数据质量】写「无缺失」 | indexExtra 被丢、heat 全 0、真连板区间口径冒充，三项均未进 degradedSources | fail-visible 在这三处分支缺席 |

## 2. 口径裁决（六项，用户 2026-10-22 采纳）

1. **指数行升 7 指数，渲染口径统一 changePct**（对齐 relay v7 D2）：消费
   `frame.indices.indexExtra`（szcz/cybz/kc50）落 `evidenceRaw.indices.indexExtra`
   透传 + `evidenceRaw.indexPct`（顶层 4 键 changePct 伴生，帧 10-16 起有）。
   渲染顺序 沪指/深成指/沪深300/中证500/中证1000/创业板指/科创50；changePct 缺失
   （10-16 前历史帧）降级点位呈现（fail-visible，不补 0）。历史帧无 indexExtra
   （10-20 前）→ 4 指数降级 + degraded 披露「三指数该帧未采集」。
2. **连板语义切真连板，区间高度 M 降级为标注**（对齐 relay §2.1/§2.2）：
   - 真连板单一事实源 = THS 连板层五池（hotspot_focus，池身份=高度，high 池条目
     `continue_day_cnt`=精确高度；10-21/10-16 双日实证与 `jiuyan_streak_map` 一致）。
   - 叙事「最高 N 连板」「梯队（一板/二板/三板/四板以上）」一律真连板口径；区间
     `maxBoard` 高于真连板时随行标注「另有断板股区间高度最高 M 板（跨度口径，非连板）」，
     杜绝两个「最高板」自相矛盾（relay 审查 #10 教训）。
   - **盘中供给**：连板层五池仅 ≥15:00 帧入采（风控成本），盘中槽在计算层经
     `get_ths_pools(date, keys=连板层)` 现查（服务层 250ms 节流+退避负缓存+TTL 已有）。
     as-of 保护：优先级 帧池（15:00）→ 已存 v2 槽文档 `evidenceRaw.limit`（当日已走帧
     重collect时复用落档 as-of 值，**不现查**——现查返回 now-state 会污染历史帧）→
     当日**当前时钟槽**现查（上海时钟 now ≤ 槽时刻 + 10 分钟容差；超窗=已走槽被回补/
     重跑，一律 None 降级不现查）→ 历史日按日期查（EOD 态，回放口径，degraded 披露）→
     None 降级。跨事件循环安全：现查不共享进程单例 AsyncClient（连接池绑定首次循环，
     跨循环复用实测 RuntimeError），每次调用新建专用 client + 模块级结果缓存（TTL 300s）
     （详见 §6 #1）。
   - **任一池缺失/不 ok → 整体不可算返 None**（relay 审查 #8 同规）；连板层全零且
     ztCount>0（池未就绪）→ None 不冒充 0 连板。
3. **锚同口径重算**：`build_history_stats_calendar` 的「最高连板」改 `maxTrueBoard`，
   取数链 15:00 v2 槽文档 `evidenceRaw.limit.maxTrueBoard`（本役后生产自供）→
   15:00 帧连板层五池（10-10 起入采，7 日在窗）→ **参考集合 `market_true_ladder`**
   （新，`backfill_true_ladder` 工具逐日回填，同源 THS 连板层——同源采样铁律）→
   None（<8 样本如实标「历史样本不足」）。
4. **`evidenceRaw.limit.maxBoard` 值不动**（区间口径原样保留）：消费方
   `emotion_score._CALIB["maxBoard"]` 校准曲线按区间口径标定（1081 槽实测），帧契约
   与 emotion 评分链零漂移——独立轨道，是否切真连板另行预注册（relay §4 同款披露）。
   帧 `continuousBoards` 契约不动（方向 v4/vote pilot 另有消费）。
5. **次级修复**：C 已走帧生命周期行补「反转」；D heat 全零时焦点个股按 rank 排序、
   删「热度 0」噪音、degraded 披露「热度字段未采集」；E 涨停原因行披露「有原因个股
   N 只，列前 5」；F indexExtra 缺席/真连板未采集/热度未采集全部进 degradedSources。
6. **判据零改动**：`QUESTION_SET_VERSION` 仍 v2.5（本役是原料修正不是题目变更）；
   语料口径切换日 2026-10-22（跨代对比时以本日期为界，防 v2.4 式跨代混比）。

## 3. 落库字段变更（additive-only，快照/文档合同）

`hotlist_jev_sentiment` 槽文档 `evidenceRaw` 增量：

- `indices.indexExtra`：`{szcz:{change,changePct}, cybz:{...}, kc50:{...}}` 帧透传；
- `indexPct`：顶层 4 键 changePct（缺失键缺席）；
- `limit.trueBoards`：`{yiban,erban,sanban,sibanPlus,high}`（真连板口径；sibanPlus=四板+高位）；
- `limit.maxTrueBoard`：真连板最高板；`limit.trueBoardSource`：`frame_ths_ladder`/
  `ths_live`/`stored_doc`/`ths_date_eod`/`external`（外部供给未标来源时的兜底枚举）；
- `reasonsTotal`：有 reason 行数；
- `maxBoard`（区间）与既有键零变动。

新参考集合 `market_true_ladder`：`_id`="YYYY-MM-DD"，
`{maxTrueBoard, boards:{one,two,three,four,high}, source:"ths_ladder_backfill", fetchedAt}`。

## 4. 不同步范围（列披露）

| 轨道 | 消费 | 处理 |
|---|---|---|
| emotion_score 连续评分 | `limit.maxBoard`（区间校准曲线） | 不修，独立轨道（§2.4） |
| 规则情绪链（theme/hotlist_sentiment_compute） | 帧 `limitSummary` 直读 | 帧契约不动，零漂移 |
| 方向 v4 / vote-confirm pilot | 帧帧 `maxBoard` | 不修（relay §4 既定） |
| pilot 锚（jev_sentiment_pilot / jev_crowding_score_pilot） | `build_history_stats`（2026-10-22 review P2-1 发现，§6 修） | **已同步修**：改读 `maxTrueBoard`（不回退区间 maxBoard，混口径禁入同一条分位序列），缺值 None 样本不足如实标注 |
| pilot 槽产物真连板（jev_sentiment_pilot.compute_slot） | `collect_slot_evidence` 未传 true_ladder（review P2-2 发现，§6 修） | **已同步修**：接 `_resolve_slot_true_ladder` 供给链（历史 pilot 日期走按日查 EOD 态，当日走时间窗守卫） |
| 历史帧回填 indexExtra | 帧缺该字段 | 不回填；10-20 前槽文档叙事 4 指数降级 |
| 10-22 前存量槽文档 | narrativeRaw 旧口径 | 不回放语料；回放（重算）需真 jev 调用，走预算确认 |

## 5. 验收基准（零 jev 调用 dry-run 对照）

10-21 14:00 dry-run（`compute_and_upsert_for_slot(dry_run=True)`）叙事应显示：

- 「指数与量能」7 指数 changePct：沪指/深成指/沪深300/中证500/中证1000/创业板指 -1.37%/科创50 +0.27%；
- 「最高 4 连板（真连板）」+ 梯队「（一板…/二板12/三板1/四板以上3，真连板口径）」
  + 「另有断板股区间高度最高 7 板」标注；
- 已走帧压缩行「最高 4 连板」（as-of：当日早槽复用落档值）与生命周期行含「反转」；
- 焦点个股无「热度 0」；涨停原因带「有原因个股 36 只，列前 5」；
- 近20日锚「最高连板」为真连板分位（回填后 20 日样本齐）。

交叉核验：真连板 vs `jiuyan_streak_map` 逐日一致（回填参考集合时抽 2 日对照）；
锚 maxTrueBoard vs 15:00 帧连板层一致。

## 6. 2026-10-22 提交前 code review（3 个 subagent 平行对抗审查）与修复

提交 1b3ea22c 后审查，落表处置。逐项标注「修复前会产生什么」。

### 修掉的问题

| # | 位置 | 缺陷 | 修复前实证 | 处置 |
|---|---|---|---|---|
| 1 | `jev_sentiment_compute._fetch_true_ladder` | **P1 跨事件循环 client**：进程级单例 httpx.AsyncClient 连接池绑定首次事件循环；jev 后处理链在 `asyncio.to_thread` 新循环复用 → 池请求全部 `RuntimeError: Event loop is closed`，真连板供给链在生产两进程内整体失效 | 实测：主循环用单例后再新循环 → RuntimeError；且 `get_ths_pools` 的 errors 推导对 tuple 调 `.get` 抛 AttributeError，故障无日志 | 每次调用新建专用 client（用完即关）+ 模块级 `_LADDER_FETCH_CACHE`（TTL 300s，只缓存成功）吸收重复请求；实测两次新循环现查均成功 |
| 2 | `_resolve_slot_true_ladder` | **P1 as-of 缺口**：`allow_live` 未校验槽位是否真当前时钟槽——当日早槽被回补/重跑（collector 当槽宕机重算、`/slots/rerun`、全槽重算脚本）时现查 now-state 冒充槽位 as-of | 14:00 槽 15:30 回补 → 写入 15:30 连板态为「14:00 最高 N 连板」，无披露 | 新增 `_slot_is_current`（上海时钟 now ≤ 槽时刻 + 10 分钟容差）；超窗一律 None 降级不现查；测试区分真当前槽与已走槽重跑 |
| 3 | `market_proxy/limitup.get_ths_pools` | **既有 P1**（review 顺带发现）：errors 列表推导把 `(key, dict)` 元组当 dict 用，任一池失败即 AttributeError——失败上报路径整体不可用 | 单池 403 → 整个 get_ths_pools 崩，其余池数据与错误信息全丢 | 解包 `entry[1]`；补 partial-failure 回归测试 |
| 4 | `backfill_true_ladder.plan_backfill` | **P2**：日期窗口可含当日盘中——THS 按日查返回 now-state，`--apply` 入库后被明日锚当 EOD 样本消费（回填侧的口径事故入口） | 盘中跑 `--end=今天` → 盘中连板态入参考集合 | 跳过 `date >= 今日`（计数披露）；补测试 |
| 5 | `_note_slot_ladder_caliber` | **P2**：ths_date_eod 回放口径披露只盖当前槽——priors 与日级逐帧链同样取 EOD 连板层但无标注 | 历史日重放时盘中帧显「最高 N 连板」实为收盘态，模型当 as-of 真值 | 披露下沉到 `_collect_evidence`（priors/day 同享）；当前槽取帧池而 priors 取 EOD 的混合形态也汇入质量段 |
| 6 | `jev_state.collect_slot_evidence` | **P2**：indexExtra 部分缺席不披露（只有整体为空才报）——上游只返深成指时创业板指/科创50 静默消失 | 部分源失败被当成完整 | 逐键比对缺席名并披露（「三指数缺席：创业板指、科创50」） |
| 7 | `derive_true_ladder_from_pools` | **P2**：五池全零且 ztCount=0（09:30 池未就绪同样形态）返回「合法 0 连板」——以权威口径呈现未就绪读数 | 09:30 帧写「最高 0 连板（真连板）」 | 全零一律 None（无法区分未就绪/真无涨停 → 降级披露）；zt_count 参数随之退役 |
| 8 | `jev_state` 侧次级 | P3：热度混类型行 TypeError 一票否决全帧证据；日峰值 `or 0` truthiness；原因「列前 5」措辞歧义；真连板降级归因误导；存储文档畸形炸槽计算 | — | 热度排序 `_finite` 守卫；峰值显式 None 判定；措辞「原因列前 N 类」；降级改中性措辞「连板层不可用」+ 计算层日志承载上游错误；`_stored_doc_ladder` 畸形 → None |
| 9 | `jev_sentiment_pilot.build_history_stats` | **P2**（测试/文档一致性审查）：仍产 `maxBoard` 键，而 `build_history_anchor` 改读 `maxTrueBoard` → pilot `--anchor recent` 锚「最高连板」整行变「历史样本不足」，pilot 重跑写生产集合锚段缺该指标 | 预注册 §4 未列此轨道的改名遗漏消费方 | 改读 `maxTrueBoard`（不回退区间 maxBoard——混口径进同一条分位序列=混采污染） |
| 10 | `jev_sentiment_pilot.compute_slot` | **P2**（同上）：pilot 产物未接真连板供给链，盘中槽产物（写生产集合）真连板恒缺席 + degraded | 预注册 §4 未列 | 接 `_resolve_slot_true_ladder`（历史 pilot 日期走按日查 EOD 态，当日走时间窗守卫） |
| 11 | `tests/conftest.py` | **P2**（同上）：护栏未覆盖 `backfill_true_ladder` 的真网路径（`fetch_many`/`main` 直连 get_limitup_service） | 未来用例调 fetch_many/main 会静默真连 10jqka | 护栏同批打 `backfill_true_ladder.fetch_many` |

### 补的测试（全部验证「revert 即红」）

- `test_limitup_service_throttle`：partial failure → degraded + errors，不崩
- `test_jev_sentiment_compute`：`_slot_is_current` 窗口、当日早槽重跑不现查、存储文档畸形降级、priors EOD 披露进叙事
- `test_jev_state`：全零→None、三指数逐键缺席、日峰值 None 判定、原因措辞、热度序倒排夹具、indexExtra 点位降级分支
- `test_backfill_true_ladder`：当日/未来日跳过、`_LADDER_POOL_KEYS` 三处副本互相对照（单一事实源）

### 审查发现但本次不修（列披露）

- 压缩行在真连板可得时不附区间标注（序列段篇幅取舍，当前帧段保留）
- 梯队桶个别键 None 会以 0 呈现（现代帧恒出全键，实际风险低）
- 池计数取 `len(items)` 而非上游 `total`（现全量返回，分页截断为理论边界）
- 单次槽 compute 新增 Mongo 查询约 80-100 次（priors×stored_doc + 锚日历 20×3）；锚日历结果未在同日多槽间缓存
- `_anchor_max_true_board`/calendar 的 15:00 帧 find_one 无 sort（与既有 `temperature_percentile` 同病，force 重采多帧时取哪份不确定）

## 7. 回放与预算（开火需另行确认）

- 10-20/10-21 槽文档重放（帧已带 indexExtra）≈ 16 篇 × ~4.7k input tokens ≈ 7.5 万
  tokens；更早历史不回放（indexExtra 缺席、真连板为 EOD 回放口径，价值低）。
- 锚历史回填：`backfill_true_ladder --start 2026-09-22 --end 2026-10-09`
  （09-22..10-09 共 13 交易日在 20 日窗内且无帧连板层；THS 按日查，0.8s 间隔，
  约 13×5 池请求）。
