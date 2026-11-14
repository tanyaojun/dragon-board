# 竞价龙头链盘前题材催化原料扩充预登记（A→B→C，2026-11-14）

> 状态：**已获用户裁决实施**（2026-11-14 会话，三阶段顺序全实施；C 不等 A+B 审计门控）。
> 性质：**纯语料供给扩充**，题面 hash（`QUESTION_SET_HASH_AUCTION_LEADER`）全程不动；
> ammo 版本随阶段换代 d→e（A）→f（B）→g（C）。17:30 题材龙头链零变化。
> 一切自动化测试 mock jev / 零网络（AGENTS §1.2-7）；真实 HTTP 仅限本文登记的探针。

## 0. 背景与裁决记录（2026-11-14 用户确认）

- 目标：为 09:26 竞价龙头打标链补齐「隔夜→早盘」题材催化原料窗口（09:26 前可读）。
- 实施顺序 **A→B→C 三阶段全实施**（用户裁决；Phase 0 审计只作基线，不作门控）：
  - **A**：KPL 盘前二次刷新（09:05 加槽，同源同鉴权，最便宜）；
  - **B**：韭研早报（`timeline/news`）复活为**晨间窗专属**语料源，只供 09:26 竞价链；
  - **C**：同花顺 7×24 隔夜快讯兜底层（新源，红线 9 先探针登记预算再接线）。
- **单一事实源裁决（对 2026-10-23 方案 A 的晨间窗例外）**：KPL 仍是 17:30 题材链
  事件层唯一权威源（不变）；韭研早报是独立语料类型（人工编辑隔夜汇总，粒度与
  KPL 逐事件全文不重叠，10-23 勘察 §8.1 实测），以新集合单源接入、只供竞价链；
  分层披露不融合、不跨源仲裁。**不复活 `timeline/list` 日历**（KPL 日历是超集），
  **不复活已 drop 的 `jiuyan_timeline` 集合**。

## 1. Phase 0 基线审计（2026-11-14 实测，零 token 零网络，只读生产库）

| 池 | 样本 | 结论 |
|---|---|---|
| `kpl_topic_events`（92 条） | KPL「今日炒」事件池实际**清晨 ~06:40-07:50 定稿发布**；11-03 日常链上线后早间事件 13/13 全部 08:45 槽准时入库；9 条「迟到」全为 10-23 链上线前回填/周末伪影 | **事件供给在 09:26 基本无缺口**；09:05 槽为防御 08:45-09:25 发布窗 |
| `kpl_theme_news`（84 条） | 82/84 发布于 09:26 后；早间发布样本仅 1 条（11-03 09:21 发布、11:46 才入库） | **08:45–09:25 有真实但低频缺口**（A 阶段覆盖对象） |
| 竞价 doc（12 条，11-13 vA1 代） | `evidence` 字段全空（旧代未存储），0 事件/0 新闻命中系旧代产物+匹配层问题，非供给层证据 | 基线命中口径以后续 `diagnose_theme_ammo_hits` 回放为准 |

基线用途：C 上线 ≥5 交易日后同口径回放对比晨间窗催化命中率，结果回填本文 §6。

## 2. Phase A — KPL 盘前二次刷新（09:05）

- `_THEME_CORPUS_ATTEMPTS` 增 `(09:05, "preopen2", ("kpl",))`；复用既有 kpl 分派
  （列表+详情全量 collect），子进程超时 480s → 最坏 09:13 结束 < 09:26；08:45 槽
  最坏 08:53 结束无重叠；60s 轮询 + done-set 语义不变。
- 预算：`KPL_THEME_DAILY_CALL_BUDGET=40` 四槽共享不变；`skippedByBudget` 既有
  fail-visible；连续两日含 `news_detail` 才另案上调（沿用 2026-11-02 裁决规则）。
- ammo 换代 `2026-11-14e`（hash 不动）；题材链不换代（11:45/16:10 本就收全当日条目，
  17:30 读口供给等价不变）。
- 验收：实跑一日 09:05 槽出现 `firstSeenDate` 首见条目；`skippedByBudget` 无异常。

## 3. Phase B — 韭研早报（晨间窗专属源）

### B0 探针（登记：≤2 发 `timeline/news`，间隔 ≥20s，零 jev token）

- 探针目的：确认端点/认证链存活；实测早报发布时点（校准首槽时点）；取样本进测试夹具。
- 结果（2026-11-14 14:28 实测，第 1 发）：**端点存活**，auth=cache+minted（Redis 会话缓存
  + playwright 铸 token），errCode=0；返回 8 个未来日历块（2026-11-16→11-27，共 20 条，
  limit=20 为条数上限）——**当日（11-14）块未在场**（旧夹具与 2026-10-20 实测确认早报项
  随当日块下发，标题「早报」或正文「1、热点事件」开头）；发布时点/晨间在场性无法在
  午后探针实测，由上线后首个交易日三尝试槽实测（not_published 状态封底，fail-visible）。
  样本落 `data/backups/jiuyan-timeline-news-probe-20261114.json`（gitignored）。
- 第 2 发预算保留未用（当日块缺席非 limit 参数问题，不发无效探测）。
- **停摆规则**：端点已死 / 认证自愈后仍失败 → B 阶段 fail-visible 停摆上报等裁决，不静默换源。
- 首槽时点校准：维持 08:30/08:50/09:10 三尝试（发布时点未实测，按保守 earliest 校准；
  首个交易日若 08:30/08:50 均 not_published 而早报实际更晚发布，按实测平移首槽）。

### B1 采集/存储（代码自 git `3fde9716` 恢复，不重写、不建版本化文件名）

- `jiuyan_theme_fetch.py` 恢复 `PATH_TIMELINE_NEWS`/`parse_timeline_news(_response)`，
  适配为只提取当日早报项（`is_briefing` 语义：标题 ∈ BRIEFING_TITLES 或正文以
  「1、热点事件」开头）；不恢复 `timeline/list`。
- 新编排 `operations/jiuyan_morning_collect.py`（CLI `--date/--dry-run`；stdout 复用
  既有共享标记 `THEME_COLLECT_RESULT_JSON:`，分派器单一解析实现）：resolve_auth →
  共享额度护栏（`jiuyan_api_calls`，source 键 `timeline_news_morning`，日预算 12 不变、
  早报 ≤3 次/日）→ 1 次 POST → 解析 → 落库；authFailed 清缓存 force_refresh 自愈一次；
  errCode=9（短时限流）60s 退避重试一次；当日 ok 档已在库 → 短路 skipped 零 HTTP；
  未发布 → 结构化 `state=not_published`（非失败，等下一尝试槽）。
- 存储：`jiuyan_theme_store.py` 增 `COLLECTION_MORNING="jiuyan_morning_report"`，
  `_id={date}`，title/content 原文/paragraphs（编号短句切段）/fetchedAt/firstSeenAt
  （不覆盖）/quality.tokenSource/state；幂等 upsert，空载荷不覆盖已存内容。

### B2 调度

- 尝试槽 08:30/08:50/09:10（collectors=("jiuyan_morning",)，超时 240s）；每槽独立
  done 标记（state key `theme:morning{n}`，与韭研裸 kind 命名空间隔离），采集器自身
  DB 短路保证幂等；首槽时点按 B0 探针实测发布时点校准（首槽=max(08:30, 发布+5min)，
  尝试 ≤3 次、末次 ≤09:15）。`scheduler.status()` 增 `jiuyanMorning` 观测字段。
- 开关 `JIUYAN_MORNING_COLLECT_ENABLED` 默认 "1"。

### B3 消费（digest 可选节，默认关，题材链字节级零变化）

- `build_theme_evidence_block` 增 `include_morning: bool=False`（镜像 `l2_fallback_date`
  先例）：True 时读当日早报档，按板块关键词对 paragraphs 做确定性包含匹配
  （复用 `board_keywords`/共享子串锚），仅命中段渲染 `早盘催化（韭研早报 {date}）：…`
  （节合计 ≤600 字，仅子串级命中标「弱匹配」）；返回 `morningState`
  （ok/no_hit/not_published/missing/fetch_failed/rate_limited/auth_failed/late/disabled）
  + `morningDate`。`late`（评审修复 2026-11-14）：ok 档 `fetchedAt` 晚于当日 09:26
  （进程重启后补跑槽可能采到晚间才发布的早报）→ 不渲染防前视，与快讯侧截止对齐；
  无时点字段的 legacy 档放行。
- 缺席=整行零字（§1.2-8）；`corpus_state` ok 语义不变（§4.0 部分异常不阻断）；
  `NOT_A_THEME` 粗分桶排除；新叙事行过 `test_narrative_hygiene` 黑名单。

### B4 竞价接线 + 代际 + 展示（同轮，§1.2-5）

- 个股/板块两处 builder 传 `include_morning=True`；corpusState 增 `morningState/morningDate`；
  证据读口 `/api/hotlist-jev/auction-leaders` 证据块同传 flag（展示=投喂）；
  `diagnose_theme_ammo_hits` 增 flag 复现竞价口径；单只重跑 `corpusFrozen` 既有冻结覆盖。
- ammo → `2026-11-14f`（hash 不动）。
- relay ln 子视图增 `morningState` 缺席徽章（镜像 bidBad）；测试断言同轮。

### B5 测试（全 mock、零网络、零 jev）

parse（git 恢复夹具+探针样本）/ collect（预算跳过、自愈、限流退避、not_published、
空不覆盖、短路幂等）/ digest（默认关逐字回归、命中渲染、弱匹配、600 字上限、缺席、
NOT_A_THEME）/ 竞价（morningState 落库、冻结重跑叙事逐字一致）/ 调度（三槽+短路）/
版本戳+卫生+relay 徽章。凭据隔离沿用 `tests/operations/conftest.py` autouse。

### B6 验收

- 连续 ≥3 个交易日早报档 09:26 前在库；命中文档叙事出现早报节；缺席徽章正确。
- 文档同步：本文 + 10-23 勘察 §8.2 退役注记（晨间例外指针）+ fetch/collect docstring。

## 4. Phase C — 同花顺 7×24 隔夜快讯（兜底层）

### C0 探针+预算登记（红线 9 先行；登记：≤3 发，间隔 ≥2s）

- 复探 `GET https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=50`
  （2026-10-23 勘察 §3 已实证形状）：确认存活/翻页/频控形态。
- 结果（2026-11-14 14:45 实测，3 发：page1 / page2 / page1 重发，间隔 ≥3s）：
  三发全 HTTP 200 + code=200；50 条/页（字段 id/seq/title/digest/ctime(epoch 秒)/
  stock(JSON 数组)/tag(JSON 数组)）；`page=2` 有效翻页；重发内容有差异系实时流更新
  （新条目顶入），**未见限流征兆**。样本落
  `data/backups/ths-flash-probe-20261114.json`（gitignored）。
- 日预算 `THS_FLASH_DAILY_CALL_BUDGET` 默认 8（两尝试槽 × ≤3 页 + 退避重试），
  计数集合 `ths_api_calls`（`_id={fetchDate}`，逐页计数含退避重试）；探针未发现限流，
  仍按预算保守接线；上调须另裁决。

### C1 采集/存储/调度

- 新三件套 `operations/ths_flash_fetch.py / ths_flash_collect.py / ths_flash_store.py`
  （镜像 kpl_theme_* 分层；stdout 复用共享标记）：集合 `ths_flash`
  （`_id={date}:{id}`，title/digest/ctime/source/url/tags/firstSeenAt/firstSeenDate）；
  每尝试 ≤3 页、回溯至 ctime < T−1 15:00 即停；失败 60s 退避一次；无凭据、无 socket、
  无轮询风暴；当日窗口已覆盖即短路零 HTTP。
- 调度两尝试槽 08:50/09:10（超时 180s，state key `theme:flash{n}`）；
  `scheduler.status()` 增 `thsFlash`；开关 `THS_FLASH_COLLECT_ENABLED` 默认 "1"。

### C2 消费+接线+代际+展示

- digest 增 `include_flash: bool=False`：读窗口 [T−1 15:00, 当日 09:26) 条目，板块
  关键词对 title+digest 确定性包含匹配（无题材标签，命中即「弱匹配」标注），≤3 条×260 字，
  节名 `隔夜快讯（同花顺7×24）：` 带 ctime 前缀（来源以节名统一标注，评审修复
  2026-11-14 措辞收窄）；返回 `flashState`；缺席整行零字。窗口为**半开区间
  [T−1 15:00, 09:26)**（评审修复：恰 09:26:00 条目不含）。
- 竞价两 builder 传 `include_flash=True`；corpusState 增 `flashState`；证据读口/诊断工具
  同传；ammo → `2026-11-14g`（hash 不动）；relay ln 增 flashState 徽章+测试。

### C3 验收

- 隔夜窗覆盖与命中展示同 B；窗口过滤（含 09:26 截止防回放前视）测试锁定。

## 5. 失败模式（fail-visible 矩阵）

| 情形 | 行为 |
|---|---|
| A 槽 KPL 失败 | status 降级留痕；09:26 链照用 08:45 档，不重试不阻塞 |
| B 早报未发布 | not_published → 下一尝试槽；3 次后 corpusState 披露，叙事零字，链照常 |
| B 鉴权失败/限流/铸 token 失败 | 自愈一次/退避一次后 morningState=fetch_failed/rate_limited；Redis 宕机沿用「每次现铸」退化 |
| C THS 失败 | 退避一次后 flashState 披露；链照常 |
| 任一采集失败 | **绝不阻塞 09:26 打标**（采集与打标解耦，打标只读库） |
| 单只重跑 | corpusFrozen 复用晨间原件，杜绝盘后重建前视 |
| 历史日 backfill | morning/flash=missing + `sampleOrigin=backfill`，不得当前瞻结论 |

## 6. 上线后验收记录（回填区）

- 〔C 上线 ≥5 交易日后回填：晨间窗催化命中率 vs §1 基线〕
- 〔首日监控（评审登记项，非缺陷）：核对 `ths_flash_meta.oldestCtime` 与窗口起点
  T−1 15:00 的距离——若隔夜窗 >150 条（两槽各 ≤3 页）到不了窗口起点，meta 恒 failed
  且 15:00 起点段永久缺；不足时另裁决加页/预算，勿静默上调。同窗观测
  `morningState=late` 频次（早报发布时点实测）。〕

## 7a. 评审修复记录（2026-11-14 双 reviewer 并行评审，verdict 均 OK with notes）

| # | 级别 | 处置 |
|---|---|---|
| 1 | P1 | THS 预算预检不含退避重试可突破日预算 → 改为**每次 HTTP 前预算准入**（含重试），总调用严格 ≤ 预算；耗尽即停落 meta failed |
| 2 | P1 | THS 子进程超时 180s < 真实最坏 270s（最坏路径 meta 永不落档）→ 300s + 注释修正核算 |
| 3 | P1 | 新叙事节未过 hygiene 黑名单回归 → test_narrative_hygiene 补渲染/缺席两例 |
| 4 | P1 | diagnose CLI flag 死参数 → `--include-morning/--include-flash` 接线 |
| 5 | P2 | 早报读口无 09:26 截止（与快讯不对称）→ `late` 迟到档不渲染（防补跑前视） |
| 6 | P2 | 快讯读口 `$lte` 违反半开区间 → `$lt` + 恰 09:26:00 边界测试 |
| 7 | P2 | dry-run 写生产预算计数 → 两个新采集器 dry-run 完全只读 |
| 8 | P2 | 早报 docstring「3 次/槽」与实际最坏 4 次不符 → 修正 + 准入语义说明 |
| 9 | P2 | digest 读口 except 静默折叠 → logger.warning 留痕 |
| 10 | P2 | corpusState 落库无断言 → 个股+板块 missing 透传断言（含 flashDate 补落） |
| 11 | P2 | legacy 证据读口未传 flag → 同传 True |
| 12 | P2 | 枚举注释/文档漂移（auth_failed 缺、C2 来源措辞）→ 修正 |

## 7. 验证命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/snapshot_collector/test_theme_corpus_slots.py `
  tests/operations/test_jiuyan_morning_collect.py tests/operations/test_ths_flash_collect.py `
  tests/operations/test_auction_leader_label.py tests/hotlist/test_theme_event_digest.py `
  tests/hotlist/test_narrative_hygiene.py tests/hotlist/test_jev_version_stamps.py `
  tests/api/test_auction_leader_route.py tests/hotlist/test_relay_page_auction_leaders.py
# 再跑全量 pytest。已知 HEAD 既有 4 例失败（3adbf31b「韦研板块粗桶对照层」引入，与本计划
# 无关，已用干净 worktree 复验）：jev_dieban_review/jev_rise_review 各 1 例（jiuyanBoard
# 多 rootMapped 键）、operations_schedule 1 例（after-market steps 多 industryAliasBridge）、
# dual_strength_syna_harness 1 例（空窗 error 语义）。
```
