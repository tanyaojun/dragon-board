# 竞价试盘残留四项归因与解决方案（2026-11-19）

> 状态：**两项裁决已定（①退役 3006 lane ②B KPL 直连盯盘 Type=7），待主计划落地后实施**。
> 用户设计哲学：PC 全面对齐 KPL App、单主链、不以补丁方式多源化（3006+TDX 双源+分散数据集不可维护）。主计划（密度+存储）见
> `auction-trial-density-storage-fix-plan-20261119.md`，由另一会话实施中；本文四项均
> **排在主计划落地之后**，避免同文件并发写（collector/archiver/facts/routes）。
> 方法：红线 9 先读 App 反编译源码（`.tmp_review/c2_src|main_src|jadx_out_signsvc`）+
> 多日 DB 实证交叉；不盲探、不统计拟合下协议结论。

## 残留 1：会话 ~39s `eof_clean` —— 定性「正常 TTL 轮转」，关闭寿命攻坚

**归因（已定案，README §3.4/§3.8 + sub-registry-refactor-plan P4）**：
- `eof_clean` = 服务端正常 TTL 轮转，非拒绝/风控杀连（今日 `ka_mode=none`、零 rst/1002 升级）。
- App 自身就活在频繁重连里：`SocketReaderThread` 读超时 **20s 自断**、`ReconnectManager`
  退避表 `{0,1,2,4,8,15,30}s`、auth 缓存 token 秒级重做、重连后订阅重建（§3.8 源码）。
- **客户端无心跳**（全 proto 无心跳消息；唯一 kind1=服务端→客户端单向无需应答，我方
  `_dispatch` fmt=heartbeat 仅计数=App msg22 同款 skip）；610 保活重发第 5 次→1106 确定性
  杀连，P4 已裁决 `KPL_KA_MODE=off`（off 3/3 >120s 零错误）。
- 39s vs 60-90s 档差异属 §3.4 机器人检测对 setup 节拍的响应档（午后档），**无新源码证据
  支持客户端可延长**；追寿命=盲探（红线 9 禁）。

**方案（无需裁决，纯观测/容忍）**：
1. 宣布轮转正常，**删除「会话寿命攻坚」代办**；重连链+setup 全量补订（已落地）即 App 同款兑底。
2. 全 lane 轮转容忍化：pid8 由主计划 B（3s 重请求）容忍；2103 pid1 推送 ~10s<39s 天然容忍；
   3006 竞价 lane 退役（残留 2）；2203/2013 推送 cadence 已验证。
3. 增 fail-visible 观测（status）：会话寿命分档计数 + 每 lane `last_push_ts/max_gap_s`，
   max_gap 超阈（如 pid8>15s、pid1>30s）结构化告警不静默；回归测试「轮转后各 lane 自愈」。
4. 不做任何协议/节拍改动。

## 残留 2：3006 竞价 lane 零捕获 —— lane 今日刚上线未经验证，方案=先窗内验证再定去留

**时间线（git 实证，纠正早先「退役」误判）**：
- `_capture_auction_price`（仅浏览器面现有 3006 流、零新增订阅）= 11-18 16:27 e06b2782。
- `_feed_auction_lane`（pid8 成员→3006 补订 lane）= **11-19 13:44 f0324f19**，今日提交，
  **从未在竞价窗运行**（今早进程无 lane；12:33 进程早于提交）。故「零捕获」是 lane 未上线的
  必然结果，不是 lane 失败的证据。
- 11-17/18 n15=0/n25>0 属**无 lane 时代**浏览器面捕获：只证明浏览器面在 09:15 没收到 3006，
  **不能外推 lane 会失败**（早先据此退役=混淆证据，已纠正）。

**源码语义（背景，非退役依据）**：3006 在 App 用于连续交易底栏
（`StockInfoBottomSelectBar.D()`，c2_src readtab）；App 竞价页个股行情走 2103 pid8。但底栏
在盘前亦显示竞价指示价，3006 对已订阅股在竞价窗是否推送**尚无窗内实证**——这正是 lane 要
验证的假设（红线 9：探针/观测只验证假设，不盲探）。

**方案（裁决①已定：退役；执行排在 B 窗内验证通过后，避免替换源未证明先拆兜底）**：
1. **明日窗让 lane 实跑**：主计划 B 落地+重启 :8002（加载 f0324f19）后，lane 随首 pid8 burst
   （B 后 ≤09:15:10）入队补订 3006；观察 `auct15_ok/auct25_ok` + `auction_lane`
   （universe_n/subscribed_n/sub_frames/send_drops）+ 09:25 前 3006 push/resp 到达。
2. **方案对比定案（B 优于 3006 lane，3006 被完全覆盖）**：3006 只携 price/inc_rate，
   **无 zt_buy_amount**→六件套（first/first_add/max/last/start/end）只有 B 能解；pct0915
   pid8 自带 bidding_pct（已验证推送，B 后 ≤09:15:10）不劣于 3006 未验证的窗内推送；
   pct0925 TDX 已全宇宙权威，3006 s0925 重复。3006 无独占优势且是额外 ≤800 股订阅面
   （红线 1/10）。**彻底解决完整集=B+TDX+DingPan(残留3B)**，3006 不在其中。
3. **分支裁决（窗后）**：B 验证通过 → **退役 3006 lane**（单主链，删供料/补订/捕获，保留
   浏览器面 3006），pct0915 权威=series_first、pct0925=TDX，同轮同步 tooltip/测试/README
   （红线 5）；仅当 B 窗内失败才暂留 lane 作兜底。
3. 顺带核查状态异常：`auction_lane.subscribed_n=922>cap800` 且 `date=""/sub_frames=0` 的
   跨日重置语义（`_auction_subscribed` 是否随日重置），窗内一并验证。
4. s0925 TDX 回补权威不受影响（只填缺失不覆盖 live）。

## 残留 3：掉池股撮合终值（Wzs 1925万/0.58%）—— 两选项，默认维持现裁决

**现状裁决（§7.17，commit ea132612）**：`auction_trial_raw` 整集合退役（归档 backups）、
Wzs 采集路径删除；单主链=官方 socket 序列派生；掉池股=col10 窗内末帧**虚拟观测**+派生换手，
逐行 src 披露（≠撮合终值，已接受）。

**选项 A（推荐，维持裁决）**：虚拟观测+披露即终态；撮合等价非交易判据必需。残留 3 关闭。
**选项 B（已裁决，2026-11-19 用户：全面对齐 App、单主链、不补丁多源）**：
接盯盘 Type=7 为终值权威，**接入走 KPL 直连而非 Wzs 代理**（用户质询「socket 达不到实时？」
后核实修正）：
- **socket 实时达标**（B 后 3s），需 HTTP 终值源是覆盖缺口非速率：掉池股离 pid8 池、
  socket 无撮合终值/服务端六件套/end_time；App 自身亦用盯盘 HTTP(Type=7) 补此块。
- **直连基建已存在**：`auction_bidding_direct.py`（11-16 MITM 冻结）直采
  `apphwhq.kaipanla.com … a=MorningBiddingList&c=HomeDingPan&Type=4`，17 列与 pid8 同源，
  复用 `_post_form` 全局 ≥2s 锁+五件套。survey §6.3「走 Wzs 零新增暴露」已被 11-16 直连
  Type=4 超越，**Type=7 直连不新增暴露类**，且无代理缓存龄/假期冒充档问题 → Wzs 退出接入路径。
- **预登记 1 发盘后探针**：kaipanla `HomeDingPan&Type=7`（同 Type=4 客户端），验证含掉池股
  （603324）撮合终值、冻结 Type=7 列映射（info 数组位 vs Wzs cell 需实抓核对）；通过才 wiring。
- 预算：盘后 1 次/日（≤MAX_PAGES 页，全局 2s 锁）；落 `kpl_auction_matched` 单日档；
  trio 投影顶层 `dingpan_postmatch`，虚拟降为过程视图；单主链=matched 档为终值权威（红线 1）。
- 同轮同步 facts/routes/relay tooltip/测试；频控预算注释+status 观测。
**终态单主链（App 对齐）= pid8 socket（过程，B 密度）+ KPL 直连盯盘 Type=7（终值）**；
3006 退役、TDX 降应急兜底（仅披露，不作共权威）、Wzs 代理退出。

## 残留 4：Wzs end_time/final 精确判据 —— 随残留 3 消解

- 选项 B：matched 档直接携带服务端 end_time/final，**无需逆向 Wzs 判据**（同源上行）。
- 选项 A：保持披露语义（start/end=观测首末帧，tooltip 已存在）；Wzs 判据为其自采统计，
  不在 App 源码、无源码依据不盲探（红线 9）。残留 4 在 A 下为「已披露接受项」，关闭攻坚。

## 实施顺序与裁决清单

顺序：主计划落地+重启 → 明日窗 lane 实跑验证（残留 2）→ 窗后按证据定保留/退役 →
残留 1 观测 → 残留 3/4 按裁决②（A 关闭/B 预登记）。
裁决①（已定）：退役 3006 lane（单主链对齐 App）；执行排在 B 窗内验证通过后。
裁决②（已定）：B，KPL 直连盯盘 Type=7（kaipanla，复用 auction_bidding_direct），盘后 1 次/日；
Wzs 代理退出接入路径。先预登记探针冻结列映射再 wiring。
冲突护栏：collector/archiver/facts/routes/relay 归主计划会话（已落地）；window_check 于
主计划落地后由本会话清理；本会话另改干净文件（mapping_refresh/kpl_theme_fetch/
auction_trial_derive/auction_leader_label）。

**本会话已实施（2026-11-19，不提交留审查）**：derive 消费权威链对齐 App 单主链——
pct0915=pid8 series_first（3006 存档权威移除）；pct0925/jj_percent/jj_amount/jj_turnover/
end_time=Type=7(`kpl_auction_matched`)→TDX 应急（MBL/bid/末帧退出 jj 链）；头注/测试同轮
同步（test_auction_trial_derive 31 过、auction 全子集 282 过）；mapping_refresh 过期 wzs
注释/CLI help 清理。**跨会话合同**：`kpl_auction_matched.rows[code]={pct,price,amount,
turnover,end_time}`；主计划探针冻结 Type=7 列映射后按此落库，derive 自动优先
`dingpan_postmatch`，未落库回退 TDX 应急。3006 lane 退役与 Type=7 采集 wiring 归主计划会话。

## 附：wzslinker 代理全量清理台账（2026-11-19 用户裁决：全部直连，代理随时断链=单点故障）

**活数据路径·已清理（本会话）**：
1. `services/theme/mapping_refresh.py` `WZS_THEME_DIRECTORY_URL`+`_fetch_wzs_theme_directory`
   （kpl_theme_data.js 目录提示源）→ **退役**：删 URL/ fetch，`_apply_theme_directory_diff`
   改结构化退役披露；新 ID/改名回落盲扫(directory_scan_ahead)+官方 InfoGet（成分主体本就直连）。
   如需确定性目录发现，另立直连 KPL 题材目录探针（不盲探）。

**活数据路径·已清理（主计划落地后本会话）**：
2. `scripts/auction_window_check.py` `_wzs_compare`→`_matched_compare`(--matched)：删 wzs URL，
   改读本地 `kpl_auction_matched`（KPL 直连终值档），纯本地零外呼；档未落地结构化披露
   不伪 0；--date 2026-11-19 --matched 运行验证通过。

**非活依赖·标注已纠（本会话）**：
3. `operations/kpl_theme_fetch.py` 头注：实际调用本就 KPL 直连（applhb/apparticle），wzs 仅逆向来源注释→澄清。
4. `operations/auction_trial_derive.py` 头注「Wzs 回退源」→「KPL 直连盯盘 Type=7 终值权威」。
5. `operations/auction_leader_label.py` source 标签 `wzslinker_auction`→`kpl_auction_trial`（无下游断言）。

**披露文本·归主计划会话**：relay_page tooltip 提及 Wzs 语义属口径披露（非 fetch），随 C 同轮同步。

**复核**：`rg -n "wzslinker.top|_fetch_wzs|_wzs_compare|WZS_.*URL|--wzs" backend scripts --glob *.py`
→ **0 命中**（wzs 活依赖全清）。编译/运行验证通过。
