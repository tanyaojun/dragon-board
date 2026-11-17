# 竞价试盘 KPL 直采——窗内定案预登记（2026-11-16 周一）

> 状态：**预登记（改代码前的合同定案窗口）**。前置勘察见
> `auction-trial-source-survey-20261114.md`（WzsLinker 合同已冻结、直连探针 §2 两发
> 周六空列表、明确「停止盲探」）。本文件按红线 9 先写预算后开火。
> 窗口：2026-11-16（周一）09:14–09:30，集合竞价 09:15–09:25、09:25 冻结。

## 0. 目标与决策树

目标：竞价试盘数据源从 WzsLinker 中转（api-auction.php）切换为 KPL 直采
（socket/HTTP），实时落 `auction_trial_raw`（行形状与现链一致），下游
（打标链 trial_line 投喂 + 前端读口）零改动或最小改动。

```
周一窗内定案 → 命中哪条路？
├─ A. HTTP DaBanList Type=7 返回试盘整页（含 first/first_add/max/last/end_time）
│     → 直采=HTTP 窗内轮询（频控预算重写）→ parse_trial_payload 适配新载荷格式
├─ B. socket 2103 pidType=7（试盘页）有推送且 quotas 含试盘列
│     → 直采=:8002 collector 增订阅 → 快照→试盘行构造器 → persist_trial_raw 复用
├─ C. 两路都只有部分字段 → 以 socket 为主 + HTTP 补齐，或保留 WzsLinker 兜底（临时迁移态）
└─ D. 全部失败 → 维持 WzsLinker 现状（现状即回退态），记录实测证据，停止盲探
```

## 1. 桌面预演结论（2026-11-15 周六离线完成，零上游成本）

### 1.1 已证实

- **下游链全通**：`fetch_auction_trial`（WzsLinker）→ `persist_trial_raw`
  （auction_trial_raw，_id=日期）→ 打标链 trial_line 投喂 → `/api/hotlist-jev/auction-trial`
  读口 → 页面。直采只要产出同形 rows，下游不动。
- **WzsLinker 参照帧在手**：11-13 全页 95 行（缓存裸读即命中，历史档不可变，
  合同内零上游）。字段语义：金额=元、比例=小数（×100 为百分数）、时间=原串。
- **socket 基建现成**：:8002 collector 默认订阅 `daban_list_pids=(8,0,6,1,2,3)`
  （8=集合竞价），260→610 认证/0x40 setup 订阅/拟人节奏/重连防线全部在产；
  `KPL_DEBUG=<文件>` 环境变量可全帧 hex 落盘（双向）。
- **存档保留完整 quotas×28 原始数组**：11-13 bid_ 通道 293 只（kpl_daban_pool
  日档，archiver 60s 轮询合并快照）。
- **列映射（双样本对齐）**：jj_percent↔bidding_pct、jj_amount↔bidding_amount、
  jj_turnover↔bidding_turnover、price↔price、percent↔pct、bk_name↔plate 基本对上。

### 1.2 关键缺口（决定探测方案）

- **试盘专属字段在 2103 pid=8 中无列**：first_amount/first_add/max_amount/
  last_amount/end_time/start_time 六项在 quotas 28 列无对应（605255 quotas[19..27]
  全空；20/27 为未破译列但值型不符）。试盘页 tab type=7（act=1，page_id=1015）
  大概率是**独立请求**，不在现有 daban 页签族。
- **时点语义差异待裁决**（窗内 App 同屏对拍）：605255 WzsLinker jj_percent=4.78
  vs 存档 bidding_pct=9.99851（存档快照时点晚于 09:25 冻结，字段为当下态而非
  冻结态）；zt_buy_amount=9,301,319 vs max_amount=9,610,000/last_amount=8,980,000
  （委买额是时变值，试盘字段是窗内统计值）。
- **circulated_value（9.43 亿）≠ real_float（24.7 亿）**（605255）：口径存疑，
  窗内对拍裁决（流通盘口径差异 or 字段映射错位）。

## 2. 工具清单

### 2.1 已有（零开发）

| 工具 | 位置 | 用途 |
|------|------|------|
| HTTP 现役凭据 + POST 锁 | `kpl_ranking_service._post_form` + `theme.mapping_refresh.KPL_APP_BASE_PARAMS`（五件套公共出口，禁另拷） | 探针矩阵发射，≥2s 间隔锁保证 |
| socket 采集会话 | `kpl_collector_service`（生产 :8002 常驻） | pid=8 集合竞价实时流（对拍基准） |
| 帧级抓取 | `KPL_DEBUG=<文件>` 环境变量（collector 收发帧 hex 追加落盘） | socket 探测会话全帧留痕 |
| 2103 解码器 | `kpl_daban_protocol`（2103 Req/Resp、quotas 列名表） | 帧解析 + 试盘列比对 |
| 参照帧 | WzsLinker `?page=limit_up_bidding&date=…` 缓存裸读 | 09:26 冻结态黄金参照（零上游） |
| 对拍原料 | kpl_daban_pool bid_ 通道（293 只×28 列） | 列映射交叉验证 |
| 下游链 | `auction_trial_fetch.persist_trial_raw` / 读口 / 页面 | 直采产出同形 rows 即插即用 |

### 2.2 窗口前预制（已落码 2026-11-14，三脚本均 --selftest PASS；脚本在仓库根 tmp/，
不进 git、用完即删）

> 落码后勘误：socket 试探会话运行期内 collector 内建重连防线照常工作（生产级
> 退避+短命连击计数），进程级不追加手动重连；预登记「≤2 连接」语义=单次运行
> --fire 只起一个服务实例、失败不手动重试。

1. **HTTP 探针脚本**（`tmp/probe_http_auction.py`，--selftest PASS）：
   - 读 `KPL_APP_BASE_PARAMS` 公共出口，`_post_form` 发射，单发 JSON 全文落
     `tmp/probe/<seq>_<tag>.json` + 时间戳与 http 状态；
   - **硬门**：仅交易日 09:20–09:35 接受 `--fire`（防误触）；无重试循环；
   - 预注册弹射序列（见 §3 表）。
2. **socket 试探会话**（`tmp/probe_socket_auction.py`，--selftest PASS，含 pid=7
   订阅帧编码验证 + 服务实例构造验证）：
   - `kpl_collector_service` 实例化 `daban_list_pids=(7, 8)`（7=试盘 tab_id，
     **未知是否合法**——服务器不认则无帧，零风险试探）、`human_delay=True`、
     `enforce_trading_hours=True`、`KPL_DEBUG` 全帧落盘；09:14 前连上，
     09:30 主动断开销毁；≤2 连接上限；
   - 与生产 :8002 完全隔离（独立进程/独立 KPL_DEBUG 文件），失败不影响生产链。
3. **对拍脚本**（`tmp/probe_reconcile.py`，--selftest PASS，含列映射假设算法
   fixture 验证）：四方按 6 位代码 join——
   ① WzsLinker 缓存裸读（09:26 后）② HTTP 探针响应 ③ socket pid=7 帧（若有）
   ④ :8002 pid=8 快照（`GET 127.0.0.1:8002/api/kpl/daban-list?pid_type=8`，
   本机读零上游）→ 逐字段 diff 表，输出列映射假设与残差清单。
4. **App 同屏对拍记录表**：用户手机 KPL 盯盘页试盘页签 09:20/09:24/09:26 三个
   时点截图（首开/首加/峰值/撤后/结束时间），与探针值逐股核对。

**周一操作序**：09:14 `python tmp/probe_socket_auction.py --fire`（建连到 09:30）
→ 09:20/09:24 用户手机截图 → 09:25:30
`python tmp/probe_http_auction.py --fire --date 2026-11-16`（S1-S5 依序）→ 09:26
`python tmp/probe_reconcile.py --date 2026-11-16`（四方 join 出报告）。

## 3. 探针预算表（红线 9：先写预算后开火，无重试循环）

| # | 端点 | 参数 | 预期 | 弹射时点 |
|---|------|------|------|----------|
| S1 | apphwhq `a=DaBanList&c=HomeDingPan` | `Type=7&Order=1&st=100&Is_st=1&apiv=w48` | 交易日应有数据（周六空=非交易日态）；看行格式（数组位 vs cell） | 09:25:30 |
| S2 | 同上 | `Type=7&Order=1&st=100&Is_st=1&apiv=w30` | apiv 白名单差异核对 | 09:25:35 |
| S3 | 同上 | `Type=7&PidType=7&Order=1&st=100&Is_st=1&apiv=w48` | 试盘 tab_id 直传试探 | 09:25:40 |
| S4 | apphis `a=HisDaBanList&c=HisHomeDingPan` | `Type=7&PidType=8&Day=2026-11-16&apiv=w30` | 历史 Day 生效组核对（w30 下 Type/PidType 被接受但 Day 曾失效） | 09:26:00 |
| S5 | apphis `a=HisDaBanList&c=HisHomeDingPan` | `Day=2026-11-16&apiv=w48` | 已知合同对照组（应返真数据）——验证凭据/限频状态 | 09:26:05 |
| S6 | 保留 | 视 S1–S5 结果定（如 `a=DaBanHeadInfo` 族取 head_info/tab_list） | — | — |

- 总预算：**HTTP ≤6 发/日**（含保留弹），间隔 ≥2s（`_post_form` 锁保证）；
- socket 独立试探会话 **≤2 连接**，09:14 建连、09:30 前主动断开；
- 生产 :8002 不加试盘页签（试探会话隔离），生产链照常；
- 全部失败 = D 决策（维持 WzsLinker），当日不再追加弹射，证据落档后停止。

## 4. 窗口分镜（09:14–09:30）

| 时点 | 动作 | 责任 |
|------|------|------|
| 09:14 前 | socket 试探会话建连（认证+setup 订阅 pid=7,8），KPL_DEBUG 落盘开始；确认生产 :8002 存活、archiver bid 通道在轮询 | AI |
| 09:15–09:24 | 观察 pid=7 是否有帧；pid=8 帧持续落盘（竞价过程态） | AI |
| 09:20 / 09:24 | 用户手机 KPL 试盘页签截图（同屏对拍基准） | 用户 |
| 09:25:30–09:26:05 | HTTP 探针矩阵 S1→S5 依序弹射，逐发落盘 | AI |
| 09:26:10 | WzsLinker 缓存裸读（冻结态黄金参照，零上游）；:8002 pid=8 快照本机拉取 | AI |
| 09:26–09:35 | 对拍脚本跑四方 join，产出：① 直采可行性结论（A/B/C/D 决策）② 列映射表 ③ 字段语义残差清单 | AI |
| 09:35 后 | 决策落档（本文件追加「定案结果」节）；D 则证据封存 | AI |

## 5. 定案后的代码改造落点（预设计，窗内不动手）

| 落点 | A 路（HTTP 直采） | B 路（socket 2103 pid=7） |
|------|------------------|--------------------------|
| 采集器 | 新增 KPL 直采 fetcher（窗内轮询+退避上限+status 频控字段，红线 9 全套） | :8002 collector 增 pid=7 订阅（独立开关） |
| 解析 | `parse_trial_payload` 适配新载荷格式（数组位/cell 双格式） | 新增试盘行构造器（quotas→trial 字段映射） |
| 落库 | 复用 `persist_trial_raw`（行形状不变，source 字段改直采标识） | 同左 |
| 打标链 | `auction_leader_label` 改**档优先**（读 auction_trial_raw，陈旧才上游兜底） | 同左 |
| 页面 | 零改动（读口档驱动） | 零改动 |
| WzsLinker | 保留 ≤1 周对拍后退役（单一事实源：双轨=临时迁移态，退役=删代码+git） | 同左 |
| 频控预算 | 重写台账（轮询 QPS 上限/日发数上限/status 观测字段） | 会话型订阅（天然符合红线 9 订阅优先） |

## 6. 回退与安全

- 现状即回退态：WzsLinker 链全程不动，直采探针全部隔离在生产链之外；
- socket 试探会话独立进程，任何失败不影响 :8002 生产会话（重连螺旋防线各自独立）；
- 探针产物全部落 `tmp/`（gitignore），用完即删；有保留价值的证据表进本文档；
- 若 S1–S6 全空/非预期格式：当日不追加弹射，维持现状，把实测证据（errcode/格式）
  追加至勘察 §2，等下一交易日或改攻 MITM（另行预登记）。

## 7. 定案结果（2026-11-16 窗内实测，决策 D：维持 WzsLinker，直采合同未定案）

### 7.1 弹射台账（6/6 预算用完，未追加）

| # | 弹射 | 实测结果 | 判读 |
|---|------|---------|------|
| S1 | apphwhq DaBanList Type=7 w48（09:25:37） | errcode=0、day=2026-11-16 正确、list=[[37×"longhuvip.com"]] | 参数被接受但**返回占位垃圾**（非试盘数据） |
| S2 | 同 S1、apiv=w30 | 同上垃圾 | 同上 |
| S3 | 同 S1、+PidType=7 | 同上垃圾 | 同上 |
| S4 | apphis HisDaBanList w30 Type=7 PidType=8 Day | 1020 | 与 S5 间隔 5s，疑共享分钟级限频（已知合同「超频 1020」），**不确定为参数错** |
| S5 | apphis HisDaBanList w48 Day（10-27 已知好合同） | 1020 | 同上限频窗口内，结果不可信 |
| S6 | **对照组** apphwhq DaBanList **Type=1**（涨停池必有数据，09:35） | errcode=0、同样 37×域名垃圾 | **垃圾非 Type=7 特有，端点级问题**（DaBanList 族对我们缺参数/会话被风控打标），Type=7 假设证伪 |

### 7.2 socket pidType=7 试探（独立会话 09:12-09:30）

- 服务端**接受** pidType=7（无 error 帧、Resp.pidType=7 回带），全程 91 帧全部空
  items——2103 协议族不含试盘页数据（或试盘页不在 2103 cmd 上）；
- 生产 pid=8（集合竞价）同窗正常：142 只含竞价全字段——**socket 直采集合竞价已
  在产**（现有链，非新增）。

### 7.3 WzsLinker 当日故障（依赖风险的实证）

- 09:26 打标链窗内试盘拉取 `http_error:TimeoutError`（trialState 落档 fail-visible，
  第三源缺席、trialStrength=null，双源照常选龙 5 龙一 8 ok——兑底设计按预期工作）；
- 09:33 人工裸读仍超时；域名根 0.4s 可达，api-auction.php 连**历史档也超时**
  → 故障在 WzsLinker→KPL 上游拉取链（与今晨 ths_flash 300s 超时同族）；
- api-auction 前端 JS（auction-history-common.js）与 longhuvip-proxy-common.js
  均只暴露前端→代理合同（page/variant/date/refresh、endpoint 名录），**代理→KPL
  上游映射在服务端，无从逆推**。

### 7.4 结论与后续

1. **决策 D**：DaBanList 族（socket 2103 + HTTP）均不含试盘页数据；试盘页真源头
   是 WzsLinker 服务端代理的未知 KPL 端点（code=10000/tab_list/stock_list 信封族，
   非 DaBanList 族）。维持 WzsLinker 合同（存量链不动）；
2. **今日数据缺口**：试盘语料/页面今日档缺席（fail-visible）；若代理恢复，手工
   `fetch_auction_trial('2026-11-16')`→`persist_trial_raw` 补档，再 force 重跑
   竞价链可恢复 trialStrength（第三源日档回读已设计）；
3. **下一步（需新预登记）**：真源头合同需 MITM KPL App 盯盘页（抓 api-auction
   上游请求）或用户与 WzsLinker 站长渠道确认代理转发参数；本预登记工具链
   （tmp/probe_*.py 三脚本+对拍框架）可复用于第二窗口；
4. **既有资产固化**：pid=8 集合竞价 socket 直采已在产，若「实时页面看竞价过程」
   需求优先于试盘字段，可直接消费现有 :8002 流（bidding_pct/amount/turnover 全字段）。

### 7.5 后续落地（同日实施，f064983c）

用户裁决升级为「页面实时看竞价过程 + 事实采集」：WzsLinker 试盘字段拿不到，
改用 pid=8 socket 流自建**竞价过程事实**：
- **采集**：kpl_bidding_series 新集合，collector 单写者推送即落库（2103 pid=8
  合并快照），双层窗门（09:10-09:35）、tick ≥5s 节流、压缩行；
- **读口**：`GET /api/hotlist-jev/auction-bidding-series`（ticks + 逐股
  first/max/last 观测值派生，不冒充试盘字段语义）；
- **页面**：【竞价试盘】实时过程区（5s 本机轮询零 KPL 外呼），窗态机
  pre/live/frozen/ended；
- **语义边界**：首开/首加/峰值/撤后余额是 KPL 服务端委托簿统计，自建序列只能
  产出**观测值事实**（首帧/峰值/末帧委买额与竞价涨幅），两者语义不等价，
  不冒充；打标链消费待后续预登记。

### 7.6 真源头合同定案（同日，雷电模拟器 mitmproxy 实抓）

用户开启雷电模拟器后 MITM 抓包成功（CA bind-mount 系统信任 + 全局代理）：
- **KPL 现行 API 域 = *.kaipanla.com**（longhuvip.com 为旧代际，对 DaBanList 族
  一律返回 37×域名占位垃圾——上午六发矩阵垃圾之谜解开）；
- **试盘页源头 = POST apphwhq.kaipanla.com/w1/api/index.php，form
  a=MorningBiddingList&c=HomeDingPan&Type=4&PidType=0&Order=1&st=100&Index=0
  + 五件套+凭据**，响应 errcode=0/info=统一数组位 17 列行，翻页 100+14=114 只
  （实测）；委买额/竞价净额/竞价成交额三列与 :8002 pid=8 快照逐值吻合；
- **落地**：`auction_bidding_direct.py` 直采器（分页≤5 页+fail-visible）→
  kpl_morning_bidding_raw 日档（source=kpl_direct_morning_bidding）；打标链窗内
  09:25-09:30 采集一次（mblState 入 corpusState）；竞价过程事实行
  （bidding_series_line）入个股叙事（观测值口径，行文无开发注释，hygiene 过）；
  AMMO 2026-11-15d（纯语料供给换代，题面 hash 不动）；
- **未破译列**：col9/col10/col13/col14/col15（疑似首开/首加/峰值/撤后语义）
  保原名不猜，待明日窗内 App 同屏对拍后补名。

### 7.7 未破译列对拍定案（同日午间，WzsLinker 今日实时缓存截图 + 库存 11-13 真值）

- **试盘六字段=计算值定案**（用户裁决确认）：首开/首加/峰值/最终额是 WzsLinker
  对委买额自采序列的统计（首帧/首加/峰值/末帧），非 KPL 推送字段——与
  §1.2「委买额是时变值」单样本猜测互相印证；我方 kpl_bidding_series
  （socket 5s tick）自 2026-11-17 起可计算同语义观测值（bidding_series_line 已上线）；
- **col4=最终额**：今日 WzsLinker 21 行对拍，竞价涨停开盘股 8/8 比值 1.001-1.021；
  非涨停开盘股离散（0.22-1.97，口径不同不混用）；
- **col9≠首开/峰值**（95 只 11-13 真值分布证伪）：首开≥最终 62%、峰值≥最终 100%，
  而 col9≥col4 仅 7%；今日 21 行对拍 col9/首开 0.04-1.02 无一稳定；
- **col13/col14/col15=主力净额/主力买/主力卖**（盘中实时累计）：col13=col14+col15
  114/114 精确成立；两帧对比 109/114 在变；最强风口 H5 页同名 UI 标签佐证；
- **col10=col8 重复**（114/114）；col4/col8/col9/col10 为竞价冻结态
  （10:44/11:07 两帧 114/114 不变）；
- **col9 主假设=09:20 撤后余额**（可撤申报阶段结束时点委买额）：21 行散点形态
  全部吻合假墙撤单潮（TCL 首开 9.98亿→col9 0.42亿→最终 1.83亿；北纬 6.47→0.63→5.57）；
  定案路径=窗内多帧采集（col9 应 09:20 冻结、col4 变到 09:25）——已落地
  `collect_mbl_frame_series`（kpl_mbl_series，archiver 60s 轮询挂载，窗 09:15-09:26，
  帧≤15/日，红线 9 预算注释在函数头）；2026-11-17 窗内首采验证；
- **#3 今日补档收口**：api-auction.php 至守护 7/8 次仍超时（WzsLinker 网页展示的
  是其自家实时缓存，php 导出口未恢复），今日试盘 raw 按预算放弃；MBL 直采已覆盖
  冻结态同语义字段（col4=最终额/col8=成交/col5=竞价涨幅），首开/首加/峰值自明日起
  由我方序列自算，不再依赖 WzsLinker。

### 7.8 评审修复补记（2026-11-16 双 reviewer 评审后）

- `GET /api/hotlist-jev/auction-bidding-series` 读口消费方已接（2026-11-16）：
  relay_page 竞价龙头明细卡新增「竞价过程」节（alSeriesSectionHtml）——展开行时
  惰性拉取、按日缓存；absent/无该股 tick 如实展示；首帧竞价涨幅→委买额峰值→末帧
  观测值链（口径留 title 提示，不参与判定）。今日（11-16）无序列档，展示缺席态；
  11-17 窗内 collector 首采后自动生效。
- MBL 直采错误路径加固（评审 blocker 1/2）：errcode≠0 / info 非列表 → 结构化
  错误态；部分页失败已取回 rows 落库带 partial=true；非 ok 且 0 行不覆盖好档；
  MAX_PAGES 耗尽 truncated=true；attempts 原生数组、fetchedAt CST 时间戳。
- relay_page 实时区门控修复：程序回填（当日值）不再触发历史档隐藏。

### 7.9 WzsLinker 退役计划落地（2026-11-16 复盘代办 item11「今日必须解决」）

**结论：试盘第三源不再依赖 WzsLinker 非官方代理端点**。官方端点路线（App 请求体
加密、社区公开资料 66 接口无试盘族）今日证伪后，按 §7.7 用户裁决走自建派生：

- **新模块** `backend/operations/auction_trial_derive.py`：`derive_trial_rows_from_series`
  ——kpl_bidding_series（socket pid=8 官方序列，5s tick）→ 试盘语义行。口径：
  jj_percent=末帧 bidding_pct；first/last/max_amount=首/末/峰值帧 zt_buy_amount；
  jj_amount=末帧 bidding_amount（board_amt Σ口径）；pre_percent=None（roster 链
  分母=代码口径 limit，与 WzsLinker 昨涨停行 pre_percent=limit 数学等价，测试
  `test_derive_equivalence_ratio_math` 锁定）；universe=序列内委买额>0 的股。
- **等价性锚点**：11-13 真值 605255 last_amount=8980000 == MBL col4 精确一致
  （委买额同语义）；posture=首末帧比较同语义。
- **打标链源序**（auction_leader_label.run）：自建派生（纯库读零外呼）→
  WzsLinker 窗内 fetch（降级为迁移期回退，仅派生缺席时触发）→ auction_trial_raw
  日档回读。派生可用时零 WzsLinker 外呼（红线 9 预算进一步收缩）。
- **历史验证（11-13 真值 95 只，落地当日补跑）**：派生形态（pre_percent=None +
  bk_name 保留）走完整 roster vs WzsLinker 真值形态——映射 74/74 一致、板块归属
  差异 0、入选集合 {002148, 603666} 与 rank 完全一致；唯一差异 002148 jjRatio
  70.5 vs 70.15（preseal 分母 pre_percent≠limit 的 0.5% 微差，tier/rank 不变）。
  **验证命中要害并已修复**：初版派生行缺 bk_name → 桥接失败 mappedN=0 第三源
  静默死亡；修复=同日 kpl_morning_bidding_raw col11 板块 join 注入 bk_name
  （plateJoinedN/plateMissing 结构化留痕）。pytest 版等价性测试因护栏（test 库
  无档）跳过，生产库验证以上表为准。
- **§7.9a 今日双验证补记（2026-11-16 下午，trial 84 + MBL 114 冻结态实算）**

  **验证 2：MBL col11 vs 试盘页 bk_name 命名族——完全不同族，无法精确互推**。
  23 重叠股字符串一致 0/23：bk_name=试盘页主板块归类（单值粗粒度：光伏/医药/
  消费(1)），col11=KPL 概念标签串（双值顿号：稀土永磁、中特估/零售、谷子经济）。
  桥接归同等效：整串过桥 5/23 归属差异（含 2 None）；顿号拆分逐 token 过桥
  14/23 差异（含 6 None）——两策略都无法复原。且 trial bk 自身桥接产物可疑
  （基建(1)→海峡两岸、算力(1)→海峡两岸、光伏→半导体，suggest_for 模糊引擎），
  两边都是模糊近似、无真值。**结论：板块归属漂移是派生源固有属性**（量化：
  漂移 14-18/23 量级），bk_name join 只解决 mappedN=0 静默死亡，不等价。

  **验证 3：last 语义偏移 → posture 翻转与入选传导（实算）**。trial.last vs
  MBL col4：涨停开盘股 6 重叠 0 翻转（比值 1.00-1.02）；非涨停开盘 17 只
  **5 翻转（29%，4×maintain→decrease、1×decrease→maintain）**。入选传导四态
  模拟：S0 真值形态 {002187}；S1 last→col4 {}（002187 posture 翻转掉出）；
  S2 宇宙扩大(+91 MBL-only) {002187, 002748 新入}；S3 联合 {002748}。
  **两个偏移（last 语义 + 宇宙扩大）各自独立改变入选集合**。

  **§7.11 2026-11-17 窗内实测日（首采 + col9 定案 + 打标链首日真跑）**

  - **col9 判约定案：主假设证伪**。六帧（09:15:55→09:26:02，158/153/37/42/49/93 行）
    实测：col9 09:20 前恒 0，09:20:18 起从零单调累计（002685: 0→93.5M→187.4M→
    205.4M→216.1M）——是 **09:20 参照的累计量**而非「撤后余额/冻结量」；post-09:20
    帧间 27/33 不冻结直接否决余额假设。语义未破译，保 col9 原名（语义不猜）。
    附带锚定：**col4 ≈ socket zt_buy_amount**（300750/002916/002010/300191/300433
    多只精确相等）；**col10 ≈ col8 非严格重复**（帧间时点采样差，修正 11-16 单帧
    「重复」结论）。MBL 列表 09:20 后 158→37 剧变（9:20 不可撤单后榜单重组，与
    集合竞价规则一致）。
  - **序列首采成功但密度为 server-bound**。kpl_bidding_series 5 ticks（09:15:57/
    09:16:37/09:24:10/09:24:53/09:32:10，n=30→49→78）。「预期 250-300 tick」证伪：
    pid=8 页订阅序已最优（pids=(8,0,6,1,2,3) 排最前），但服务端推送=订阅爆发式
    （每会话首 ~40s 1-2 页推送）+更新稀疏，且会话 ~50s TTL（已知服务端行为）。
    红线 9 禁止重订阅轮询，无合规客户端加密手段。**修正预期：每会话 1-2 tick ×
    会话数（今日 5）**；first@09:15:57/last@09:24:53 覆盖关键相位，max 为稀疏采样
    观测值（口径 §7.9 已登记）。collector 会话短命重连（sessions 8+，10054 RST）
    为已知 TTL 模式，帧日志确认服务端 0x20 心跳存在。
  - **打标链首日真跑（全部真实数据）**：自建派生源 66 行（tickN=4，plateJoinedN=51，
    MBL col11 join 实际生效）→ trial_strength_roster mappedN=59/unmappedN=7 →
    **selectedN=1：002419 天虹股份（大消费）jjRatio=92.59 posture=decrease rank=1**——
    posture 来自真实 tick（first 209M→last 53M 撤减）。trialStrengthState/seriesState
    （stock_absent 600715）结构化留痕全部就位。MBL 09:25 冻结采集 93 行 ok。
  - **对拍缺边（待裁决）**：派生源非空 → WzsLinker 窗内回退未触发（门控设计如此，
    省外呼）→ 11-17 无 WzsLinker 真值档。选项：a) 明日窗内手动补采一次 WzsLinker
    做同窗对拍（一次性外呼，需预登记）b) 接受派生链为单主链，对拍以 11-16 真值
    形态静态对比（S0-S3 模拟已录 §7.9a）为准。
  - relay 读口三态验收：11-17 ok（stockFacts 78）/ 11-15 absent+reason / 600715
    stock_absent——fail-visible 合同成立。

  **§7.12 2026-11-17 双源对拍（退役验收门裁决：不通过）**

  当日 09:41 手动补采 WzsLinker 真值档（100 行，saved_at 新鲜）；派生档 4 tick
  生产口径（≤09:27 截断）。重叠仅 29/100。

  - **① 逐股（29 重叠）**：posture 翻转 **6/29**——涨停开盘 **3/4**（002451/
    002685/600881 全部 maintain→decrease，first比 2.08-3.50 驱动）；非涨停 3/25
    （002771/301279 反向，last比 4.48-5.48 陈旧尾帧）。值层：first比 涨停开盘
    1.19-3.50（首 tick 09:15:57 晚于拉升段）；last比 0.12-9.81 离散（掉池股末帧
    停在掉出时刻）；max比 中位 0.94 尚可；jj_percent 涨停开盘 Δ=0、非涨停最大
    Δ=21.09（陈旧尾帧）。
  - **② roster**：Wzs 形态 mappedN=71 **selectedN=0**（hotBoards 大消费 267M/16）；
    派生形态 mappedN=59 **selectedN=1**（002419 天虹 大消费 202M/8，与今晨打标链
    一致）。**入选分歧**。
  - **根因定性（结构性，非可修 bug）**：① first 基线不可复原——Wzs first=KPL 官方
    09:15:00 起算，我方首 tick 09:15:57（09:15 建连门禁+订阅爆发时序），涨停开盘
    股拉升段被跳过 → first 系统性偏高 → 假性撤减；② last 陈旧——掉池股末帧时点
    不定；③ 宇宙不同——66 vs 100（重叠 29），mid50_95 分位带与 boardAmt 分母随
    宇宙漂移。
  - **窗收 bug（已修，ad8e15b1）**：序列窗 09:35 收口混入 09:32 开盘后连续竞价
    tick（zt_buy regime 变），重导出 last 被污染（selectedN 1→0 实证）。修复：
    SERIES_WINDOW → 09:27 + collector 粗门同步 + derive 迟到 tick 防御过滤
    （lateTicksFiltered 计数）+ 回归测试。
  - **裁决项（留用户）**：方案 C（推荐）=分工制——roster 判据链回 WzsLinker 主源
    （KPL 官方口径），派生序列链专职前端「竞价过程」观测（已上线）；源序改回
    Wzs→日档→派生（派生仅 Wzs 缺席日降级观测，明示口径）。方案 A=接受派生口径
    （first=09:15:57 基线重定义，涨停开盘撤减误判 3/4，不建议）。方案 B=字段级
    混合拼接（时点对齐复杂，不建议）。

  **明日双源对拍裁决维度（升级）**：①逐股 last/posture 翻转率（真实 tick 首
  帧非代理）②boardAmt/中热档漂移（宇宙 114 vs 84）③板块归属漂移分布 ④入选
  集合差异。裁决项（用户）：接受派生源三重漂移（推荐——分组权威=韭研板块体系，
  KPL bk_name 本就是模糊桥；且非涨停开盘股 last 语义上我方 col4/官方冻结值
  更接近 roster「撤减」本意）or 保留 WzsLinker 用于板块归属（混合形态，违背
  退役目标）or 缩派生宇宙至 trial 84 同款（需宇宙判据，无官方来源）。
- **语义偏移记录**：派生宇宙（序列委买额可见 ⊇ 试盘页宇宙）大于 WzsLinker 试盘页；
  board_amt 板块热度口径随之放宽，roster 过滤（中热×mid50_95×撤减）不变；
  5s tick 采样粒度粗于 WzsLinker 自采序列，首帧/峰值统计存在粒度差（观测值口径，
  非判据字段，不影响选龙比值分母）。

### 7.10 复盘代办收口（2026-11-16 同日）

- **unmappedN=13 根因定案（正常缺归属，无缺口需补）**：13 只（002218/688479/
  002200/600505/300523/301279/301626/002577/300972/000065/300478/002890/688679）
  全部不在韭研 board_index（2748 只覆盖外，非活跃题材股）、KPL 通用行业名
  （光伏/软件/园林/水电…）不在治理桥/V3 桥与产业树一级节点（108 个题材名）、
  hist 兜底无（从未被打标）；且 13 只 jj_percent ∈ [-0.98, 2.22] 远低于 mid50_95
  档——即便有归属也不会入选，board_amt 影响可忽略。fail-visible 排除设计按
  预期工作；不补「KPL 通用行业名 → 韭研 root」映射（猜测违反「分组=韭研板块名」
  裁决，无韭研归属=如实缺席）。
- **605255 时点语义差异（§1 遗留）裁决关闭**：§7.7 已定案试盘字段=WzsLinker
  委买额自采序列统计值、§7.9 已落地自建派生（比值等价性测试锁定）——「WzsLinker
  jj_percent=4.78 与直采对拍差异」归属为口径差异（时变值统计时点不同），不再
  需要窗内 App 同屏对拍裁决，本项关闭。
- **§7.5「打标链消费待后续预登记」历史行闭合**：该留尾已由 2026-11-15/16 预登记
  （6cdf6423）与落地（5088108e/373767cf/bdf6e329）完成——trialStrength 第三源
  已消费、自建派生已接线，历史行仅存档。
- **今日 MBL raw 档无质量标记字段**：97770025 修复前落库，历史档不补（明日起新
  schema 生效），仅存档知悉。
