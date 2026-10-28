# 审查完成 — 所有目标文件已阅读完毕。正在撰写最终报告。

## 审查
审查对象：quant-board 未提交 v12 改动（12 文件，+1678/−289），对照预登记 `theme-leader-v12-dual-leader-preregistration-20261028.md`。以下所有问题均已从源码逐行核实；未运行测试（只读审查，见验收报告中的命令清单）。

### 正确项（有证据）
- **ST板块漏排修复正确**：`theme_event_digest.py:66-74` 原始名+归一名双口径；`test_theme_leader_label.py:701-710` 回归钉住；行政桶排除链路（run 内 `digest.is_not_a_theme`）测试覆盖 3 桶零调用、零落库（`test_theme_leader_label.py:713-750`）。
- **A2 拆题编排总体正确**：done 集合区分龙头/板块 doc（`theme_leader_label.py:800-810`，sector 判定用 `docKind`，code=None 不污染 done codes）；预算护栏对 built_all 逐条 `estimate_tokens(chars)` 聚合，v12 叙事变长由 f(chars) 上界自然覆盖；`--confirm-budget` 门、通道中止、outcome/auditFlag 重跑携带（`theme_leader_label.py:712-714`）均保留并有测试。
- **证据门子集化正确**：`apply_evidence_gate(..., keys=...)`（`theme_leader_ammo.py:499-541`）缺省全题、子集只门对应题，测试钉住（`test_theme_leader_ammo.py:686-699`）。
- **对账分轨语义与预登记 §2.2 一致**：带 segment 行按 (board,segment) 对账；legacy 行（segment 字段缺失）仅在板块已有分轨现任且 code 不在现任时退位（`theme_leader_label.py:463-520`）；sector doc（docKind/code=None）双重排除；退位不删除、幂等。
- **读口合并/回退**：sector doc 按 (date,board) 合入深度/延续、legacy 行回退自有值、`or {}` None 防护保留、`answerReasons`/`auditFlag`/`sectorQuestionSetVersion` 透出（`hotlist_jev_limitup_routes.py:204-340`）。
- **回顾预防（Look-ahead）防护到位**：序列行 rank/zt 均严格 ≤ 标注日（`theme_leader_ammo.py:766-771`，测试钉未来日滤除）；直播历史日结构化降级、归档优先（`test_theme_leader_label.py:1014-1036`）；基线窗不含当日不变。
- **fail-visible 分支齐全**：强度行（unmatched/fetch_failed/缺字段不可考）、直播行（unavailable/空流/无命中三分支）、原因行（逐项/全部不可考）、层1 缺日跳过、层2 缺口≠零涨停标注，均有实现与测试。
- 结算排除 code=None：`schedule.py:433,440`、`theme_leader_pilot_eval.py:161,323` 正确；页面 null 行确认为 ：8000 未重启（磁盘读口代码正确），非代码 bug。

### 发现的问题

**P0-1 近 3 日封板池去重保留「最旧」封板日高度，多日连板断板候选 height 系统性低估**
- 位置：`theme_leader_baseline.py:141-153`（`have` 跨日累积去重）+ `:175-179,199-202`（histStreak→height）。
- 证据：`pool_dates` 来自 `trading_dates_before(date,3)` 升序（`theme_leader_label.py:437-441`），循环按 d-3→d-1 顺序，`pcode not in have` 使同一 code 只保留**首次**（最旧池日）的 `histStreak`。例：股票 d-3 首板、d-1 二板、今日断板未跌停 → histStreak=1 → height=1 → 落入首板组，丢失空间板组资格；3 板断板股同理塌成 1。这正是 v12「近 3 日**最近**封板日高度取大」（预登记 §2.1 修订三）要覆盖的主场景（连板股几乎都连封多日）。
- 复现：`day_leader_rows(space_mode=True, pool_dates=[d3,d2,d1])`，code 在 d3/d1 均封板、streak 递增 → 断言 height 应为 d1 的 streak，实际为 d3 的。现测试只用单池日（`test_day_leader_rows_space_mode_unsealed_leader` 用 `["2026-10-23"]`），未钉此路径。
- 最小修法：`for pd in reversed(pool_dates)`（新→旧，先见即最近），或重复出现时覆盖 histStreak；补多池日回归测试。
- **这是 v12 核心规则的取数 bug，会直接选错龙一并烧错 jev 调用 → 阻塞开火。**

**P1-1 共享子串锚黑名单缺「经济」，板块强度匹配④会把「X经济」误锚到排名更高的其他「Y经济」**
- 位置：`theme_leader_label.py:154-156`（④ `digest._shared_anchor(base_stripped, nm)`）+ `theme_event_digest.py:167`（`GENERIC_ANCHORS` 无「经济」）。
- 证据：`_shared_anchor("冰雪经济","低空经济")` 返回「经济」（2 字、含汉字、不在黑名单）→ 当板块在 KPL 层1 无精确/包含命中时，会被锚到任意排名更高的「低空经济/银发经济/数字经济」行，行内还以 KPL 名义喂给模型。2026 韭研板块多个「X经济」并存（低空/冰雪/银发），非假设场景。
- 最小修法：`GENERIC_ANCHORS` 增加「经济」（或在强度匹配中砍掉④只留①②③）；补一条「冰雪经济↔低空经济不互锚」测试。

**P1-2 读口 segment_label 版本比较用字符串字典序，v2–v9 旧行被误标 legacy**
- 位置：`hotlist_jev_limitup_routes.py:232-233`：`"legacy" if str(d.get("questionSetVersion") or "") >= "v12" else None`。
- 证据：字典序 `"v9" >= "v12"` 为 True（'9'>'1'），v2..v9 同理；本链 v1–v11 均为真实落库版本（`test_theme_leader_route.py` 夹具即有 v1/v2/v6/v8）。结果是 v2–v9 旧行全部挂「旧口径」徽章，违背代码注释「v11 及以前旧行版本徽章已可辨，不重复标」。
- 最小修法：`int(version[1:]) >= 12`（或维护显式集合）；补读口断言。

**P1-3 序列行「当日梯队串」在层2 最新记录日≠标注日时张冠李戴**
- 位置：`theme_leader_ammo.py:791-794`：`lz = _lz_brief(zt_rows[-1]...)` 后无条件标「**当日**梯队串」。
- 证据：`zt_rows` 是 ≤标注日的**记录日**序列（层2 仅记录有涨停家日，预登记 §9 自证「算力 28 天空窗」）——最新记录日≠当日时（当日常见），昨日甚至更早的 LZInfo 被标成「当日梯队」喂给模型，直接影响延续/首板潮判读。上方 zt 段虽有日期，但「当日」是明确错误声明。
- 最小修法：`zt_rows[-1]["date"] == label_date` 才标「当日」，否则标实际日期或不通行。

**P1-4 个股级叙事未注入轨别身位，题面规则⑥「若叙事标注分轨」触发条件不成立**
- 位置：`theme_leader_ammo.py:build_leader_narrative`（头部固定 `待判龙头：{name}（{code}）`）+ `build_one`（`theme_leader_label.py:524-575`）未传 segment；结构行 `structure_line` 也只写「龙头 X」。
- 证据：预登记 §2.3「个股级=现行叙事 **+ segment 身位**」、§4.2「个股级在『待判龙头』行注明轨别身位」；题面 leader_nextday_continue 规则⑥/leader_headroom ⑤均以「若叙事标注分轨」为前提。当前个股级叙事仅在涨停原因行标签里隐含「主板龙一」（`reason_entries_for_leaders`），头部与结构行无轨别，双轨龙一身位（预登记触发本案的裁决①核心）对模型不可见。
- 最小修法：`build_leader_narrative`/`structure_line` 增加 segment 参数（待判龙头行注「主板龙一/双创龙一」）；narrative 属原料非题面，hash 不变但需 bump `AMMO_VERSION_THEME_LEADER` 并补断言。

**P2-1 「ST 板块」含空格变体仍漏排**：`theme_event_digest.py:66-74`——`is_not_a_theme("ST 板块")`：原名单不等、归一后剥成 "ST" 不在 NOT_A_THEME → False。实测韭研板名无空格，风险低；最小修法：NOT_A_THEME 增加 "ST"（归一后恰为 "ST" 的行政名一并覆盖）。

**P2-2 板块级 doc 证据块 L2「龙头」锚是韭研分组首只成员**：`theme_leader_label.py:601` `leader_code=""` → `board_snapshot` 回退 `stocks[0]`，板内解析行「龙头 X 驱动标签…」展示的是任意成员，且 S3 补充映射由该成员标签驱动，与双龙一结构行可能互相矛盾。建议板块级显式标注「板内成员（非推导龙一）」或锚定 ref 龙一。

**P2-3 FakeDb 不支持 `$exists`，legacy 对账分支在测试中恒为真**：`tests/operations/test_theme_leader_label.py:46-68` update_many 遇未知操作符静默放行——`{"segment": {"$exists": False}}`（`theme_leader_label.py:509`）在 FakeDb 下对所有 doc 通过，与真 Mongo 语义分叉，分支正确性零测试保障。建议 FakeDb 实现 `$exists`。

**P2-4 单只重跑修不了 degraded 板块 doc；重跑成本提示过期**：`theme_leader_label.py:823-824` codes 路径 sector_todo 只取 todo 行所在板块且 force 时绕过 done_boards——页面重跑按钮（`routes:380-385` force=True+codes）每次必重烧板块 doc（2 次调用），而页面 confirm 与端点 docstring 仍写「≈2.3K tokens/次」（`index.html` rerun 卡、`routes:355`）；反方向，codes 重跑也修不了「龙头全 ok 但板块 doc degraded」的档（全量跑可自愈）。建议重跑文案与端点注释同步、确认是否必要每次重烧板块 doc。

**P2-5 segment=None 的 v12 龙头 doc 成对账死角**：`_label_one` 写 `"segment": row.get("segment")`（可能 None）——真 Mongo 里 `$exists:False` 不匹配 null 字段、分支①等值也不匹配，此类 doc 永不被对账。生产 space_mode 恒出 main/growth，仅夹具/未知前缀可达；建议 `segment` 为 None 时不写入该键。

**P2-6 spaceErrors 披露口径与预登记 §2.1 有偏差**：`theme_leader_baseline.py:169-171` 仅「整板块全候选缺 gain10」跳过并披露；「整轨全缺按轨披露」未实现——单轨全缺时该轨仍按首封时间出龙一（gain10=None）且无披露。

**P2-7 页面未封板徽章 tooltip 描述与 v12 实现矛盾**：`index.html:2806`「组内/全首板按当日首封最早；仅当轨内无当日封板候选时成龙一」——实现是空间板组内 gain10 最高优先、未封板候选按 gain10 参与组内排序（`rank_board_stocks_seal`+测试 `test_rank_board_stocks_seal_composite_rule`）。

**P2-8 计划内测试未交付**：预登记 S5 的 `test_relay_page_theme_leaders.py`（segment/legacy 徽章）与读口 API 测试（sector 合并/segmentLabel/answerReasons/audit）均未更新；对账分轨+legacy 边界（预登记 §8.1「legacy 行不被自动退位」）、多池日 histStreak 无测试。

**P2-9 文档/注释漂移**：`theme_leader_ammo.py:200-206` `rank_board_stocks` docstring 仍指向已删除的 `rank_board_stocks_space`（红线：改录用删除）；AMMO 头 2026-10-27b 注记块整段重复两次；`AMMO 注记` 中 "digest.AL IASES" 断字（预登记来源如此，代码内 `theme_leader_label.py:152` 同样断字）。

**P2-10 板块-日评估单位未落地**：`theme_leader_pilot_eval.py` 仍按龙头-日评估并把 sector doc 过滤掉（161 行）；预登记 §2.3「延续/深度题样本单位=板块-日」的评估口径未实现（验收窗未开，不阻塞，但需在开窗前补）。

**P2-11 层2 取数失败在序列行无披露出口**：`theme_leader_label.py:852-855` zt fetch 失败→zt_rows=[]，行内只少一段，fetch_failed 原因被丢弃（fail-visible 缺口）；另 `get_plate_daily_history(st=limit≤100)` 与「Count=303 全史」的窗口语义（返回最新 N 还是最旧 N）建议与 App 同屏核对一次——若上游按最旧截断，`past[-5:]` 会喂远古日期。

### 结论（可否进入单条验证）
**暂不可进入。** P0-1 会使多日连板断板候选（v12 主场景）系统性丢失空间板资格、选错龙一，必须先修并补多池日回归测试；建议同批修 P1-1～P1-4（均为小改）后再开火。P2 项不阻塞，可随下自然换代点处置。修完 P0+P1 后：`cd quant-board && .\.venv\Scripts\python.exe -m pytest tests/hotlist/test_theme_leader_ammo.py tests/hotlist/test_theme_event_digest.py tests/operations/test_theme_leader_label.py tests/api/test_theme_leader_route.py tests/hotlist/test_relay_page_theme_leaders.py -q` 全绿即可进入单条验证。