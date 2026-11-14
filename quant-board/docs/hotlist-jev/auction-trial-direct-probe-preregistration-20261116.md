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

## 7. 定案结果（窗内填写）

> 待 2026-11-16 09:35 后填写：决策（A/B/C/D）、弹射台账实测结果、列映射表、
> 字段语义裁决（jj_percent 时点 / circulated_value 口径 / zt_buy_amount vs max/last）。
