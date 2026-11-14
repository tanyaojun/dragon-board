# 竞价试盘语料源勘察（2026-11-14）

> 状态：**源已定位，直连合同待窗内定案**。本文是原料层补充（竞价龙头链 vA3 候选）
> 的前置勘察，不含代码改动。触发：11-13 天普股份复盘（见
> `auction-leader-vA1-preregistration-20261113.md` 案例讨论）用户裁决「原料层优先，
> 补充竞价试盘信息源」，并授权单发探针定位来源。

## 1. 结论

截图（WzsLinker 悟者胜·聚合页 → 集合竞价 → 涨停竞价/竞价分析AI）的试盘数据
**上游 = 开盘啦（KPL）App「盯盘」页 HTTP API**，WzsLinker 仅作服务端缓存代理。
与本项目已接的 `c=HomeDingPan`（实时 Radar）/ `c=HisHomeDingPan`（HisDaBanList /
HisDaBanHeadInfo）同控制器族；socket 2103（DaBanStockListResp）的 HTTP 孪生为
`a=DaBanList`（2023 公开合同：`Type/PidType/Order/st/Is_st`，见 §3）。

证据链：
1. 页面 JS：`集合竞价-02涨停竞价.html` / `010JingJia/集合竞价-01竞价分析AI.html`
   → `AuctionHistoryCommon.request({page:"limit_up_bidding"|"auction_analysis",
   variant:"7",date})` → `/companys/api-auction.php`（`auction-history-common.js`）。
2. 代理响应（11-13 缓存，saved_at 2026-11-13T23:41） envelope = KPL 标准
   `code=10000/msg=succ`，`data.title="盯盘"`，`tab_list=[试盘 type=7（act=1）,
   涨停 type=1, 跌停 type=3, 强势股 type=6, 潜力榜 type=5, 曾涨停 type=2, 曾跌停 type=4]`，
   `stock_list.head_info.sort_key` = `max_amount / jj_percent / percent / last_amount /
   first_amount / first_add / end_time / bk_name / price / start_time / jj_turnover /
   jj_amount / circulated_value / pre_percent`（page_id=1015）。
3. 非交易日请求 11-14 → `is_fallback=true`「当前为非交易日，已展示前一个交易日数据」
   （11-14 周六），代理按交易日历门控、每日盘后落缓存。
4. 本项目题材语料三端点本就逆向自 `wzslinker.top/companys/js/longhuvip-proxy-common.js`
   （`kpl_theme_fetch.py` 头注），同源同族。

## 2. 直连探针日志（红线 9 预算：KPL 既有 HTTP 源，共 2 发 POST，≥2s 间隔由
`kpl_ranking_service._post_form` 锁保证，无重试循环；用户显式授权「打一发」）

| # | 时间 | 端点 | 参数 | 结果 |
|---|------|------|------|------|
| 1 | 11-14 ~10:03（周六） | apphwhq 实时 | `a=DaBanList&c=HomeDingPan&Type=7&Order=1&st=100&Is_st=1&apiv=w48` + 五件套凭据 | errcode=0（参数被接受，非 1020），`{list:[],day,ttag}` 空 |
| 2 | 11-14 ~10:04 | apphis 历史 | `a=HisDaBanList&c=HisHomeDingPan&Type=7&PidType=8&Day=2026-11-13&apiv=w30` + 凭据 | errcode=0，`day=2026-11-14`（Day 被忽略）、list 空 |

判读：两发均非参数错（无 1020），空列表与「周六非交易日实时无数据」一致；
但**试盘页签的精确直连合同未定案**——哪个 a= 返回含 head_info/tab_list 的整页
cell 格式载荷、历史 Day 参数在哪组 apiv/参数下生效，均待实测。
**停止盲探**（红线 9）；定案路径见 §5。

## 3. 已知合同参照（公开逆向资料，待窗内核对）

- 2023 公开页面（cybergoat520/company `打板.html`、55188 方珏专栏）：
  实时 `apphq … a=DaBanList&c=HomeDingPan&Type={4,6}&PidType={0,1,2,4}&Order=1&st=1000&Is_st=1`；
  历史 `apphis … a=HisDaBanList&c=HisHomeDingPan&Type=…&PidType=…&Day=YYYY-MM-DD&apiv=w30`。
  旧版 Type 语义（4=即将涨停/炸板、6=涨停/自然涨停）与当前 tab_list（7=试盘、1=涨停…）
  **不同代际**，不可直接套用。
- 本仓 `kpl_ranking_service.get_daban_list_history` 实测：apiv=w48 下 HisDaBanList
  严格白名单（仅 Day）；§2 探针 2 显示 apiv=w30 下 Type/PidType 被接受但 Day 失效——
  白名单形态随 apiv 变化，需窗内逐组定案。
- 响应行格式两族：统一数组位（DaBanList/HisDaBanList，`_parse_daban_history_row`
  同族）vs cell 格式（WzsLinker 所见整页载荷，`{text,color,rank,param}`）。

## 4. 天普股份（605255）11-13 试盘原始行（KPL 数据，经 WzsLinker 缓存取得）

| 字段 | 值 | 字段 | 值 |
|------|-----|------|-----|
| max_amount 最大额 | 961万 | start_time 开始试盘 | 09:15:01 |
| jj_percent 竞价涨幅 | **+4.78%** | end_time 结束试盘 | **09:18:13** |
| percent 涨幅 | +10.00% | jj_turnover 竞价换手 | 0.15% |
| last_amount 最终额 | 898万 | jj_amount 竞价成交 | 1398万 |
| first_amount 首开额 | 756万 | circulated_value 流通值 | 94.29亿 |
| first_add 首加额 | 40万 | pre_percent 昨涨幅 | **+10.00%** |
| price 现价 | 73.82 | bk_name 题材 | 半导体(3) |

对复盘的三个直接含义：
1. **昨涨幅 +10.00%** = 第三独立源确认 11-12 封板 → 结构行「昨日未封板」假事实
   定案为 KPL 池档漏档（池为截断排序榜，缺席≠未封板）。
2. **试盘阶段匹配仅 +4.78%、试盘单 09:18:13 撤单**（09:15–09:20 可撤窗内）→
   天普并非「从头一字」，一字涨停形成于 09:20–09:25 不可撤窗的真实委托。
   试盘源的核心增量 = 区分「假试盘→真封」/「硬一字」/「试盘后撤单回落」
   （对照大胜达：试盘 +6.73% @09:19:51 → 收盘 +1.97%）。
3. **jj_amount 1398万 / jj_turnover 0.15%**（与流通值 94.29亿自洽）vs bid 通道
   竞价成交额 0 / 换手 0 → bid 通道零值疑似上游缺省 0，试盘源可交叉校准六件套。

语义警示（投喂前必须窗内核实）：
- end_time=09:25:00 的股 jj_percent==收盘涨幅；end_time<09:20 的股 jj_percent=
  **试盘结束时点匹配涨幅** → jj_* 是 end_time 时点快照，非必然 09:25 冻结值。
  叙事行必须显式标注时点（同 09:15 试盘价 / 09:25 匹配价标注纪律）。
- circulated_value（流通值 94.29亿）≠ bid 通道 real_float（实际流通 24.74亿），
  口径不同，派生比率不得混用。
- first_amount/first_add/max_amount/last_amount 的精确语义（首笔涨停价试盘单额/
  首笔加仓额/峰值/撤单前余额）待窗内与 App 同屏核对，不猜语义入叙事。

## 5. 待办（定案路径，不再盲探）

~~原定案路径（MITM/KPL 直连探针）~~ → **2026-11-14 经 WzsLinker 前端合同逆向已全部定案，见 §6**；
KPL 直连探针 A/B/C 取消（接入走 WzsLinker，零新增 KPL 暴露）。

## 6. 合同定案（2026-11-14，WzsLinker 前端逆向 + 缓存读实证，零 KPL 暴露）

### 6.1 端点合同

```
GET http://wzslinker.top/companys/api-auction.php?page=limit_up_bidding&date=YYYY-MM-DD[&refresh=1]
```

- 客户端合同（auction-history-common.js 定案）：仅 page/variant/date/refresh 四参；
  涨停竞价页真实调用 `{page:"limit_up_bidding", date}` **不带 variant**（勘察早期记录的
  variant:"7" 系误读；variant=7 实测 404 语义「不支持的数据变体」）；
- 响应信封：`success / actual_date / is_fallback（回退最近成功交易日） / fetched
  （本次已写入本地缓存=代理实时拉了上游） / saved_at / dates[]（可用历史日全列表） /
  data（KPL 原始信封 code=10000）`；
- 数据形态：KPL cell 格式整页载荷，`data.data.stock_list.head_info`（15 列 sort_key）
  + `list`（数组位，cell={text, rank, color, param}）；
- **rank = 数值原值**：金额=元（961万→9610000）、比例=小数（+4.78%→0.0478、换手
  0.15%→0.0015）、时间=原串——金额/涨幅解析零猜测，渲染直接用 rank；
  **接线警示：jj_percent/jj_turnover rank 是小数比例，须 ×100 后才与百分数语义对齐**。

### 6.2 能力实证（缓存读，fetched:false 未触发上游）

| 能力 | 证据 |
|---|---|
| 历史回看 | `dates[]` 覆盖 2026-06-29 起全部交易日；11-12 缓存 88 行、11-13 缓存 95 行完整试盘数据 | 
| 盘中刷新 | 涨停竞价页 60s 轮询此接口且不带 refresh → 代理盘中自更新缓存（**缓存龄待周一竞价时段 1 发验证**） |
| 强制上游 | refresh=1 → fetched:true 回显（周一备用，不默认开） |
| 行格式 | 15 列表头（stock_id + 14 业务列，勘误 2026-11-14：旧记 16 列系夹具裁剪前误记，与 §4 天普行逐列吻合） |

### 6.3 接入判定修订

1. **接入路径改 WzsLinker**：与题材语料三端点同族同基建（`kpl_theme_fetch.py`
   逆向先例），零新增 KPL 直连暴露（红线 9 初衷）；KPL 直连仅作未来降级备选，
   合同不再主动探。2. **试盘源准入 = 涨停价试盘单**：605255@11-12 不在榜（09:47 才封板，
   竞价未顶板）——试盘源是补充切面，不能替代池档。3. jj_percent 时点语义双样本自证：
   end=09:25:00（华东重机）jj==收盘涨幅；end=09:19:51（大胜达）jj=试盘结束匹配涨幅。
4. first/first_add/max/last 金额语义仍以 App 同屏核对为准（行内自洽性已强支持
   「首开=首笔涨停价委托/首加=追加/max=峰值/last=撤单后余额」，但不猜语义入叙事）。
5. **工作台消费层已上线（2026-11-14；分组口径同日二次澄清 + 桥接链补全）**：relay_page
   【竞价试盘】页（KPL 行情组）——后端纯读口 `GET /api/hotlist-jev/auction-trial`
   （auction_trial_raw + stock_names 名称 join，零上游外呼，页面轮询不占 WzsLinker
   预算）；左板块=**韭研板块**（用户裁决：未入打标分组不单独成组、不管有没有打标），
   个股-板块联动；归属链四级：① 当日涨停打标分组（多组各计一次）② 产业树一级节点
   （jiuyan_board）③ **板块名称桥**（bk_name 归一 → theme_industry_mapping →
   sector_industry_mapping → suggest_for 同引擎实时建议；排查结论：原桥 202 条构建于
   KPL 252 名录，未覆盖打板页 bk_name 词表；**词表已入治理闭环（同日，见
   theme-governance-p1p4-implementation-20261025.md §五B）：--rebuild-daban 日终挂链
   + 43 条新桥落库 + 读口 bridgeUnmapped fail-visible**）④ 近 60 日打标链涨停分组最近归属兑底
   （事件桶公告/其他不入）；四级全 miss → 「未分板块」行（2026-11-06 裁决不回推
   bk_name）。11-13 档实测：未分板块 48→24 只（桥 13 + 打标链兑底 11 救回；剩余 24
   只历史仅公告/其他事件桶或从未打标，产业树上无节点可归）；右表列 tooltip 内嵌
   §4 语义警示（end_time 时点/流通值口径/金额语义待核）。

   **残留未分类根因裁决（2026-11-14 用户问「能否清历史 60 日档降到个位数」后的排查结论）：
   不能，也无需**。① 读口每次请求实时用最新桥/映射重算全 60 日档，「未分板块」不是
   过期派生值，历史 bk_name 为原始采集记录不可改写；② 残留 24 只×17 词在三层目标库
   （108 节点成分快照 / 150 一级类目正文树 / 62 个近 60 日打标链分组词）均无父桶——
   jiuyan 产业库是题材向而非全市场行业分类，环保族（环保/水务/污水处理/固废处理/
   大气治理/节能/水利建设）、软件、机械设备、电力设备、装修、高铁轨交、工程咨询、羊年
   等标准板块/事件词无处可连，按「语义不猜」裁决保留 fail-visible；③ 可确定性固化仅 3 词
   已 --set 落库（化纤→化工标准化子类；家电→大消费、葡萄酒→大消费沿用伞桶先例
   外贸/体育/电子烟→大消费），实测桥未收录 17→14 词、未分板块 24→21 只，仍两位数。
   后续若要继续压缩需用户裁决伞桶映射或接受 KPL 原词成组（后者违反 2026-11-06
   不回推 bk_name 裁决，须显式改裁决）。

### 6.4 WzsLinker 预算台账（红线 9）

| 日期 | 发数 | 性质 |
|---|---|---|
| 11-14 | 静态 JS/HTML ×4 | 页面合同逆向 |
| 11-14 | api-auction.php ×2 | variant=7 拒（无上游触发）+ 11-13 缓存读（fetched:false） |
| 11-14 | api-auction.php ×2 | 11-12 / 11-13 缓存读落盘存档（data/backups/probe/） |
| 11-14 | api-auction.php ×60 | 60 交易日窗口回填（scripts/backfill_auction_trial_raw.py，单发/日 ×2s 间隔，全 fetched:false 缓存读，60/60 落 auction_trial_raw 零失败；用户裁决授权） |
| 周一 11-16 | **≤2 发** | 竞价时段缓存龄验证（date=今日，读 saved_at/数据时点；refresh=1 仅备用） |
| 之后 | 盘中 ≤1 发/日（TTL ≥60s）+ 盘后历史补拉宽预算 | 与页面轮询节奏一致，不高于正常用户 |