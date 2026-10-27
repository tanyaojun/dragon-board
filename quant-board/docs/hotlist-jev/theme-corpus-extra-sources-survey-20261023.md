# 题材语料多源扩充勘察：开盘啦题材事件/新闻/日历 + 同花顺快讯（2026-10-23）

> 用户需求：目前只有 jiuyangongshe.com 一个语料事件源，评估新增 开盘啦题材/东财题材/
> 同花顺财经快讯/7×24 快讯 等源，给定聚合入口 `wzslinker.top`（盘前资讯工具目录），
> 浏览全貌 → 评估可否做语料补充 → 抓包找接口。
>
> 纪律：本轮**零 jev 调用、零 token**，仅对外部站点做约 12 次**单发** HTTP 探测（间隔 ≥2s，
> 未触发任何限流）；证据存 `data/backups/kpl-corpus-probe-20261022/`（gitignored）。
> **本轮未接任何源、未改任何代码**——接源属口径变更（预登记 §5 曾裁决「单源纪律」），
> 须用户裁决后再立预注册实施。

## 0. 结论先行

| 源 | 实测可用性 | 对题材语料的价值 | 建议 |
|---|---|---|---|
| **开盘啦 `c=Topic`（题材事件）** | ✅ 已打通（两路：列表+详情） | ★★★ **最高**：每日题材事件 + 全文 + 来源 + 时间戳 + 热度；10-21 就有「泽连斯基和谈」事件（正是俄乌重建当日催化的同源事实） | **第一优先接** |
| **开盘啦 `ThemeNews GetList`（题材新闻流）** | ✅ 已打通 | ★★★ 每条自带 **Kword 题材标签** + 关联个股 + 涨跌幅——**板块↔事件关联是现成的**，省掉名字匹配 | **接**（与 Topic 同批） |
| **开盘啦 `ThemeNews GetList Type=3`（题材日历）** | ✅ 已打通 | ★★☆ 前瞻事件（日期+类型+关联个股）；与韭研 timeline 重叠度高，可作交叉验证/备胎 | 可接，低成本 |
| **同花顺 7×24 快讯** `news.10jqka.com.cn/tapp/news/push/stock/` | ✅ 已打通 | ★★☆ title+digest 全文+tag；但**无题材结构化标签**，需关键词匹配（复用 v3 早报段落匹配思路） | 二期（兜底快讯层） |
| 东财题材（wzslinker 页） | ❌ 混淆 JS 未还原接口 | ？ | 暂缓（价值/成本比差） |
| 724.guzhang.com（7×24 聚合页） | 仅 iframe 包装 | ☆ 无文档接口、第三方稳定性差 | 不接 |
| 优品题材（wzslinker 页） | 未深挖（混淆） | ？ | 暂缓 |

**关键判断**：开盘啦是**已在用的源**——项目已有三个 longhuvip 端点在生产（题材树
`c=Theme&a=InfoGet` → `theme_stock_mappings`、热榜 GetHotPHB、龙虎榜），Token/DeviceID/
UserID 常量现成（`theme/mapping_refresh.py`）。新增 Topic/ThemeNews 属**同一账号体系同一
鉴权链扩端点**，不是引入陌生源；且它补的恰好是归因报告（§4/§G3）确认的结构性缺口：
**事件驱动型题材的当日板块级催化 + 题材标签**。

## 1. wzslinker.top 全貌（72 款工具目录）

该站是「网页联动炒股软件」工具集（开源：github.com/LibertyZero10/WzSLinker），
`tools.html` 按分类列源。「盘前资讯」分类与我们相关的子页：

| 子页 | 形态 | 数据源 |
|---|---|---|
| 7×24快讯 | iframe 包装 `724.guzhang.com` | 第三方聚合（股掌网），无文档接口 |
| **开盘啦题材** | 自研页（混淆 JS） | 直连 longhuvip 三端点（见 §2） |
| 东财题材 | 自研页（混淆 JS） | 东财接口未还原 |
| 韭研日历 | 链接韭研 App 页 | 已在用 |
| 优品题材 | 自研页（混淆） | 未深挖 |
| 同花快讯 | 自研页（混淆 JS） | 同花顺 flash news（已独立验证，见 §3） |

注意：wzslinker 本身只是**目录/包装层**，真正的语料源是它背后的 longhuvip/10jqka——
我们直接对源站接，不经过该站（少一层依赖）。

## 2. 开盘啦题材三件套（实测通过，2026-10-23）

> 来源：`wzslinker.top/companys/js/longhuvip-proxy-common.js`（未混淆，端点映射全量暴露）。
> 鉴权参数复用项目已有常量（`mapping_refresh.py` 的 Token/DeviceID/UserID/VerSion）。

### 2.1 题材事件（`c=Topic&a=InfoList` / `InfoGet`）——最高价值

```
GET https://applhb.longhuvip.com/w1/api/index.php
    ?Index=0&PhoneOSNew=2&VerSion=5.16.0.3&a=InfoList&apiv=w38&c=Topic&st=15
    &UserID=...&Token=...&DeviceID=...
→ {"List":[{"Day":"2026-10-21","List":[
     {"ID":"2497","Title":"中办、国办发布《关于推动科技创新和产业创新深度融合的意见》",
      "HotVal":65441,"IsVote":"1","Time":"1792581805"}, ...
```

- 列表：按日分组的题材事件（**每日开盘前的「今日炒/明日炒」事件池**，带热度值）；
- 详情 `a=InfoGet&ID=2498` → `Content`（**全文**）+ `Source`（来源：央视新闻）+
  `Time`（精确到秒）+ `HotVal` + `Num`（关注数）：

```
Title: 泽连斯基：愿在保留至少75%领土控制权的基础上达成和平协议
Content: 央视新闻10月21日消息，乌克兰总统泽连斯基…"现在我们必须冻结（战线）…"
Source: 央视新闻   Time: 2026-10-21 23:34:48   HotVal: 38840
```

**对照现有缺口**：归因报告 §4（南矿集团案例）确认「事件驱动型题材的当日板块级催化」
是韭研产业树/日历的结构性盲区——开盘啦 Topic 流**正好**把这类事件当日收进池
（10-21 泽连斯基事件、10-21 英伟达 GTC、中办国办意见，均带热度）。与韭研早报
（当日一次性、429 字、无热度无个股）相比：**分日分事件、逐条全文、带热度与关注数**。

### 2.2 题材新闻流（`apparticle.longhuvip.com c=ThemeNews&a=GetList`）

```
Type=-1（全部）→ 50 条：{"CID":7938,
  "Title":"Meta未来支出承诺总额达8250亿美元涉及AI算力、数据中心及能源基础设施",
  "Kword":"AI算力基建",                       ← 题材标签（现成的板块关联！）
  "Source":"开盘啦","TimeStamp":1792681975,
  "Stocks":[{"Code":"603019","Name":"中科曙光","Rate":0.29,"SetTop":1}, ...]}
```

- **Kword 即题材标签**：事件↔题材↔个股三级关联现成，不需要再做「板块名 ↔ 事件文本」
  的确定性匹配（韭研侧最费劲的一步）；
- `SetTop`/`Rate`：个股置顶标记与当日涨跌幅（可作为「事件受益股当日表现」结构事实）。

### 2.3 题材日历（`GetList&Type=3`）

```
{"PID":4803,"Brief":"2026年欧洲肿瘤内科学会(ESMO)大会将于10月23日至27日举行",
 "Date":"2026-10-23","TagName":"会议","ColorType":"2","Stocks":[]}
```

- 与韭研 `timeline` 高重叠（GTC/ESMO 两边都有）；价值在**交叉验证**与**冗余兜底**
  （韭研日历是单点：一次限流/空载荷当天就没有前瞻层）。

### 2.4 接入成本评估（零 token，纯采集）

| 项 | 评估 |
|---|---|
| 鉴权 | **零新增**：复用 `mapping_refresh.py` 的 Token/DeviceID/UserID（同一账号体系） |
| 存储 | 复用 `jiuyan_theme_store` 模式：`_id={date}:{sha1(title)[:12]}`、`firstSeenAt` 不覆盖、`contentHash` 追新 |
| 证据块 | `theme_event_digest` 新增「开盘啦题材事件」节（每条带 来源/时间戳/热度，fail-visible） |
| 匹配 | Kword 题材标签直接对板块名做归一匹配（确定性），事件正文走 v3 早报段落同款共享子串规则 |
| 限流 | 开盘啦限流特性**未实测**（本轮仅 4 次请求全成功）；沿用 §5.3 纪律（串行+间隔+退避+计数+日护栏） |
| 风险 | ①Token 有效性依赖 mapping_refresh 的现役账号（若其过期则两处同挂）；②开盘啦把部分数据迁 TCP/protobuf（社区实证 267 板块列表走 Socket），Topic/ThemeNews HTTP 端点现可用但需监控，挂了要有结构化缺口披露而非静默 |

## 3. 同花顺 7×24 快讯（实测通过）

```
GET https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=30
→ {"code":"200","data":{"list":[{"id","title","digest","tag":"A股",
   "tags":[{"id":"21103","name":"A股"}],"ctime","source","url"}...]}}
```

- 全文 digest + 时间戳 + 分页（seq 翻页）；**无题材标签、无个股关联**（stock/field 多为空）；
- 定位：**兜底快讯层**——KPL Topic 没覆盖到的突发事件（如「英国恢复大口径火炮生产」
  10-22 在库，军工/俄乌重建相关），靠 v3 早报段落同款的确定性关键词匹配进证据块；
- 优先级低于开盘啦（结构化程度差一档），建议二期。

## 4. 不接/暂缓的源与理由

| 源 | 理由 |
|---|---|
| 724.guzhang.com | 第三方聚合 iframe，无接口文档，稳定性/可持续性差；其内容与 KPL/THS 高重叠 |
| 东财题材 | wzslinker 页混淆未还原；东财公开 push2 系已部分在用（跌停池），题材资讯类接口需另行抓包，价值密度低于开盘啦 |
| 财联社电报 | 预登记 §5 已裁决不接（多源口径漂移）；本次无新证据推翻该结论的必要 |

## 5. 口径裁决点（接源前必须先裁决）

预登记 §5 的红线是「**只接一个权威源，不许多源混采冒充催化**」。本次建议**有条件放开**，
纪律如下（实施须另立预注册）：

1. **分层披露，不融合**：证据块按来源分节（韭研产业树 / 韭研早报 / 开盘啦题材事件 /
   开盘啦题材新闻），每条带 来源+时间戳（+热度），**绝不跨源合并成一条"催化"**；
   模型自己看多源，消费端不做源间仲裁；
2. **单一事实源不破坏**：题材判定/评估口径仍以题集 v3 判据为准，新源只是**证据供给**；
   代际戳随题集换代（v4），旧代不回改不混评；
3. **fail-visible 全链路**：任一源当日缺档/限流 → 证据块标注「来源 X 当日未采集」，
   不用另一源静默补位冒充；采集健康度进 `jiuyanTheme`（改名或并列 `themeCorpus`）状态；
4. **别名/映射纪律不变**：Kword→板块名映射只做确定性归一（含式/共享子串），不加语义猜测；
   `NOT_A_THEME` 粗分桶排除逻辑对新源同样生效（公告/新股事件不投喂）。

## 6. 建议实施顺序（待裁决）

1. **P1：开盘啦题材事件 + 题材新闻流接入**（同一批）：
   `operations/kpl_theme_collect.py`（拉取/解析/存储，复用鉴权常量与限流纪律）→
   调度挂 08:45 盘前槽 → `theme_event_digest` 新增两节 → 题集 v4（证据块变更须换代）；
   预估采集 0 token，打标叙事 +300~600 字/条（Kword 事件流比早报更短更结构化，增量有限）。
2. **P2：开盘啦题材日历**（与韭研 timeline 双源并列披露，交叉验证）。
3. **P3：同花顺快讯兜底层**（关键词匹配消费，二期观察 KPL 覆盖缺口后再定）。
4. 观察项：开盘啦 HTTP 端点限流/迁 TCP 风险监控（`errcode!=0` 结构化披露）。

## 7. 复跑命令（全部零 token）

```bash
# 开盘啦题材事件列表 / 详情（单发，勿连发）
curl -s "https://applhb.longhuvip.com/w1/api/index.php?Index=0&PhoneOSNew=2&VerSion=5.16.0.3&a=InfoList&apiv=w38&c=Topic&st=15&UserID=397605&Token=df9cadb87bbba7d04e9fcbaa2aa229b3&DeviceID=548d826f-a2a7-301a-b148-920f31f15331" -H "User-Agent: Mozilla/5.0"
curl -s "https://applhb.longhuvip.com/w1/api/index.php?PhoneOSNew=2&VerSion=5.16.0.3&a=InfoGet&apiv=w38&c=Topic&ID=2498&UserID=397605&Token=df9cadb87bbba7d04e9fcbaa2aa229b3&DeviceID=548d826f-a2a7-301a-b148-920f31f15331" -H "User-Agent: Mozilla/5.0"
# 题材新闻流（Type=-1 全部 / Type=3 日历）
curl -s "https://apparticle.longhuvip.com/w1/api/index.php?apiv=w39&PhoneOSNew=2&VerSion=5.18.0.1&c=ThemeNews&a=GetList&Type=-1&st=50&Index=0&UserID=397605&Token=df9cadb87bbba7d04e9fcbaa2aa229b3&DeviceID=548d826f-a2a7-301a-b148-920f31f15331" -H "User-Agent: Mozilla/5.0"
# 同花顺 7×24 快讯
curl -s "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=30" -H "User-Agent: Mozilla/5.0"
```

**证据**：`data/backups/kpl-corpus-probe-20261022/`（kpl_topic_list/topic_get/news_all/news_cal/
ths_flash/proxy_common.js/wzs_home）。

## 8. 追问裁决：与韭研（投资日历+产业库）的重叠实测（2026-10-23）

> 用户裁决方向：**只要单一源，不要兜底源**。用已抓样本 vs 生产库做严格匹配
> （归一后包含≥6字 / 共享子串≥4字且同日 / 共享≥6字；脚本与产物在
> `data/backups/kpl-corpus-probe-20261022/overlap_check_strict.py`）。

### 8.1 重叠矩阵（实测数字）

| 语料层 | 开盘啦 | 韭研 | 重叠判定（实测） |
|---|---|---|---|
| **前瞻日历** | Type=3：50 条，覆盖到 11-17 | timeline 前瞻 13 条 | **高重叠，KPL≈超集**：韭研 13 条中 ~11 条 KPL 也有（ESMO/金蝶/东盟峰会/算电展/FOMC/欧央行/日央行/成品油…）；KPL 另多 ~40 条韭研没有（PMI、三季报截止、错峰生产、AMD/苹果财报、进博会、互联网之光…）。注意 KPL 日历 **0/50 带关联个股**（个股关联在新闻流，不在日历） |
| **当日事件** | Topic：49 条/近16日（逐条全文+来源+热度+关注数） | 早报：1 条/日（429 字汇总，~5 个题材归因短句，无全文无热度） | **事实重叠、粒度不重叠**：泽连斯基和谈/GTC 两边都有，但早报是一段话汇总、KPL 是逐事件全文；49 条事件中与韭研 timeline 标题可严格对应的仅 2 条（其余为韭研完全没承载的：业绩披露汇总、盘前概要、国家数据集团成立等） |
| **题材新闻流** | 50 条/页，带 **Kword 题材标签**（去重 29 个）+ 关联个股+涨跌幅 | **无对应物** | **不重叠**：韭研没有任何「事件→题材标签→受益股」的逐日流。Kword 与产业树节点名可确定性映射的约 8~24/30（取决于匹配松紧），俄乌重建/AR眼镜/算电协同/硅料/AI视频 等产业树无对应 |
| **产业库（催化正文）** | 无对应端点（Theme 详情是另一形态且已在用） | 产业树 768 节点 | **不重叠**：产业树独有，保留 |

### 8.2 单一源裁决（✅ 已裁决=方案 A，2026-10-23 实施，见预登记 §13）

「每类语料一个权威源」的纪律不破坏——**事件语料层二选一**（✅ 用户裁决选方案 A，当日实施完毕：
KPL 采集链 + digest v4 + 题集 v4 `56dbb0709335` + 韭研 timeline 退役归档 drop +
调度 08:45/16:10 接线；详见 `theme-leader-nextday-preregistration-20261020.md` §13）：

- **方案 A（推荐）：事件层唯一源 = 开盘啦（Topic 事件 + ThemeNews 新闻流 + Type=3 日历，同一源三个面）**，
  **韭研 timeline（日历+早报）退役**（停采集、删消费、证据块去掉早报段/既定事件两节）。
  依据：前瞻日历 KPL 是韭研超集（多 4 倍条目）；当日事件 KPL 逐条全文+热度严格强于早报汇总；
  新闻流是韭研没有的维度。**韭研继续供：异动库（板块分组+逐股解析=v3 L2 层，不可替代）+ 产业树
  （板块催化静态摘要）**——两源各管一层、零重叠。
- **方案 B（零改动）：维持韭研为唯一事件源，不接新源**。代价：放弃 Kword 标签/热度/事件粒度/
  日历 4 倍覆盖；但注意 **v3 早报段落匹配已把最痛的缺口（俄乌重建当日催化）补上**，
  B 的残余缺口比接入前小得多。

### 8.3 换源的迁移代价（方案 A 须一并裁决）

1. **历史变浅**：KPL Topic 端点 `st=15` 只回看 **~16 日**（实测 09-23→10-22）；
   韭研早报 10-08 起在库。换源后事件语料历史起点后退约 1 周（对只向前累积的验收无影响）。
2. **v3 早报段落匹配改造**：换成 Kword 标签匹配（更简单——标签是现成的），
   题集 v3→v4 换代；`corpus_state`/`jiuyanTheme` 健康度、`theme_event_digest` 的
   早报/既定事件两节同步改。
3. **韭研采集停采**：`jiuyan_theme_collect` 的 timeline_news/timeline_list 两源下线
   （industry 产业树保留），日调用预算从 3 次降为 1-2 次，限流压力反而下降。
4. **早报「新增重点监控」段丢失**（实测多数日为「暂无」，价值低）。

## 9. 精选板块勘察（2026-10-25 追加：题材周期换源方向）

> 背景：题材周期 v1（98b201b9/9c64b37a）已 revert，用户裁定命题要继续只能换数据源，
> 指定探索 `wzslinker.top` 首页的「精选板块」页。本轮**零 jev 调用、零 token**，
> 对外单发 HTTP 探测约 20 次（间隔 ≥2s，未触发限流）。
> 证据存 `data/backups/kpl-corpus-probe-20261025/`（gitignored）。

### 9.0 结论先行

「精选板块」不是又一个资讯源，而是 **KPL（开盘啦）板块强度监控的三层数据全套**：
逐日板块强度榜（历史回看 ≥1 年）+ 板块成分股明细（自带连板状态与龙头梯队标签）+
**逐日板块爆发事件史（KPL 预计算好「爆发日+当日板块涨停数+强度+龙头梯队串」）**。
第三层直接就是题材周期状态机要的原料——**龙头轨迹被 KPL 预先算好了**。
且全部端点 **POST Token=0/UserID=0 即可通，零凭据**（比现役 c=Topic 链的账号依赖还轻）。

| 数据层 | 端点（真实源，全部实测通过） | 历史能力 | 对题材周期的价值 |
|---|---|---|---|
| 板块强度排行 | `c=ZhiShuRanking&a=RealRankingInfo`（POST，apphwhq） | **Type=1+Date 按日查史，实测 2025-10-15 起有数（≥1 年）** | ★★★ 四阶段状态机的主轴：逐日强度序列划 emerging/igniting/weakening |
| 板块爆发历史 | `c=ZhiShuKLine&a=GetDayBaseFaceListZDEvnArt&StockID=801xxx&IsBoom=1`（GET，apphis） | 逐日爆发事件史，Index 0/10/20 分页 | ★★★ **现成的龙头轨迹**：每行=爆发日+ZTNum（当日板块涨停数）+QD（强度）+LZInfo（龙头梯队串「大业股份，5连板」）+LZInfo_ZF（梯队涨幅） |
| 成分股明细 | wzslinker 代理 `kpl_zhishu_stock_list_w8_cur&PlateID=…&REnd=0930/1500`（真实端点未还原，见 9.3） | REnd 双截面（竞价 09:30 vs 收盘 15:00） | ★★☆ 板内个股级：连板状态（field 23「5天3板/6连板」）+ 梯队标签（field 24「龙一~龙N」）+ 概念串 + 热度 |
| 天梯数 | `c=HisHomeDingPan&a=DailyLimitIndex&Day=…`（GET，apphis） | 按日 | ★☆ 情绪/梯队辅助（字段语义待对齐，10-23 返回 [70,9,1,0,2]） |
| 指定日涨停表现 | `c=HisHomeDingPan&a=DailyLimitPerformance&Day=…&Type=4&PidType=1&st=1000`（GET，apphis） | 按日 | ★☆ 涨停池备胎（info 结构待解析，首轮取到 0 行） |
| 个股→板块映射 | `c=Theme&a=InfoGR`（POST，applhb，Token=0） | 全表 | ★★☆ 与现役 `theme_stock_mappings` 同源互证 |

### 9.1 页面与接口还原过程

1. `wzslinker.top` 首页是混淆壳，`tools.html` 列出「精选板块」子页：
   `companys/KPL/3.0/KPL-07精选板块.html`（页题「KPL · 板块监控 v2.0」）；
   相邻相关页：KPL-06 精选+百日轮动、KPL-08 精选导出、KPL-03 题材库。
2. 页面 JS 混淆，但请求层 `longhuvip-proxy-common.js` 未混淆：仅含 6 个直连端点
   （Topic/ThemeNews 系，即 §2 已接的三件套）；
   **精选板块另有专用端点走自家 `api-proxy.php`（服务端映射，不开源）**。
   浏览器实测页面流量（performance resource 172 条）：页面只调两个代理端点——
   `kpl_real_ranking_info_cur&st=80`（板块排行）与
   `kpl_zhishu_stock_list_w8_cur&PlateID=…&REnd=0930/1500`（每板块成分股双截面，82 个板块 ×2）。
3. 真实端点还原不走猜参数，两条路拼出：
   - **用户提供 Apifox 文档站** `immgpzl8u9.apifox.cn`（开盘啦接口抓包读数，llms.txt 可导出 md）；
   - Gitee `mikasama/add_system` README（ZhiShuRanking 参数集 + 返回字段部分释义）。
   - 关键姿势（Apifox 透露）：**POST form + Token=0/UserID=0 免账号**；历史主机 `apphis.longhuvip.com` 支持 `Day=/Date=` 按日查史。

### 9.2 板块强度排行（题材周期主轴，实测 2026-10-25）

```
POST https://apphwhq.longhuvip.com/w1/api/index.php   (Host: apphwhq)
Content-Type: application/x-www-form-urlencoded; charset=utf-8
  Index=0&Order=1&PhoneOSNew=2&Type=2&VerSion=5.13.0.1&ZSType=7
  &a=RealRankingInfo&apiv=w35&c=ZhiShuRanking&st=80&Token=0&UserID=0
→ {"list":[["801159","机器人概念",36926,3.382,0.757,546381598172,...], ...]  实时（Type=2）

  Type=1 + Date=2026-10-23 → 同结构按日查史（apphis 主机亦可）
```

> **2026-10-27 晨复测勘误**：「apphis 主机亦可」不再成立——apphis 同参数返空
> （`{"list":[],"Count":0,"Day":…,"errcode":"0"}`，冷却 35s 仍空），排行（含 Type=1
> 查史）必须走 **apphwhq**（`kpl_ranking_service.py` 已按此实现）。另实测 apphwhq
> 深历史（2026-10-20 及更早）返空且 `Day` 被钳到 `["2026-10-26"]` = 免费端点有滚动
> 保留窗（近数交易日），「≥1 年深史」当日未复现，引用前须当日复测。

- 行字段 19 个，Gitee 释义：[0]=板块代码、[1]=板块名称、[2]=**板块强度**、
  [5]=板块成交额、[6]=板块净值；[3]=涨幅%、[8]≈主力净额（负）、[10]≈流通市值，
  其余待对齐（样本存证据目录）；
- `st` 最大 80，`Index` 分页（Gitee：每日 240 个板块需翻页取全）；
- **历史回看实测 ≥1 年**（2025-10-15 有数；2026-08-15 报 1020 系周六非交易日）；
- `ZSType=7`（板块类型族）其它取值未测。

### 9.3 板块爆发历史（本轮最大发现：龙头轨迹是现成的）

```
GET https://apphis.longhuvip.com/w1/api/index.php
    ?Index=0&IsBoom=1&PhoneOSNew=2&StockID=801159&Type=0
    &VerSion=5.16.0.5&a=GetDayBaseFaceListZDEvnArt&apiv=w38&c=ZhiShuKLine&st=10
    User-Agent: ad
→ {"StockID":"801159","List":[
   {"ID":"43091","Title":"英伟达升级Isaac通用机器人开发平台…","IsBoom":"1",
    "Date":"2026-10-22","ZTNum":"13","QD":"7252",
    "LZInfo":"603278,大业股份,5连板;003021,兆威机电,4天2板;301502,…",
    "LZInfo_ZF":"14.51;83.39;54.00"}, …]}
```

- 每行 = 该题材的一次**爆发日记录**：催化标题（Title）+ 爆发日期 + 当日板块涨停家数（ZTNum）
  + 当日强度（QD）+ **龙头梯队串 LZInfo**（`代码,名称,连板状态` 分号串，连板状态含
  「5连板/4天2板/首板」= 断板反包口径已由 KPL 判好）+ 梯队当日涨幅（LZInfo_ZF）；
- 样本实测：机器人概念 10-22/10-20/10-19/9-07/9-03/8-11 六次爆发，跨度 ≥2.5 个月
  （`st=10` 只取前 10，`Index` 0/10/20 分页应可取全史）；
- **对状态机的意义**：v1 被推倒的原因之一是 THS 封板二分口径的工程反复（9c64b37a revert）；
  这里 KPL 直接给出「题材×日期×涨停数×龙头梯队」的成品序列，emerging（涨停≥4）、
  龙头标杆（≥3板）、断板反包（「5天3板」）、weakening（爆发间隔拉长+ZTNum 衰减）
  四类判据的原料全部在场，且**天然带历史（回放/回填免重算）**。

### 9.4 成分股明细（走 wzslinker 代理，真实端点未还原）

```
GET http://wzslinker.top/companys/api-proxy.php?type=longhuvip
    &endpoint=kpl_zhishu_stock_list_w8_cur&PlateID=801159&REnd=1500
    （REnd=0930 = 竞价截面；页面同时拉两截面做竞价→收盘对比）
→ {"list":[300 行 × 70 字段]}
```

关键列（0 起）：0 代码、1 名称、2 属性（游资/基金）、4 **概念串**、5 涨幅%、6 涨停幅（20/10）、
7 成交额、8 换手?、10 流通市值、11-13 资金流、23 **连板状态**（「6连板/5天3板/首板」）、
24 **板块内梯队标签（「龙一」~「龙N」）**、58 个股热度。完整样本见证据目录。

**未还原说明**（按阴性结果纪律如实记录，非终局）：代理名 `kpl_zhishu_stock_list_w8`
强烈暗示真实端点为 `c=ZhiShuStockList` 系；已试 POST `c=ZhiShuStockList&a=StockList(/StockList_W8,
apiv w8/w38)` × PlateID/REnd/Index/st 组合，均 `errcode 1020 参数出错`（端点存在、参数集未对上），
公开网络无该接口名记录。**出路**：① 继续抓包还原（App 抓包或页面混淆 JS 反混淆）；
② 生产先走 wzslinker 代理（第三方个人站点依赖，需 fail-visible + 降级链 + 自建转发缓存）。

### 9.5 与现役链的关系（口径不冲突）

- **板块 ID 同体系**：801xxx PlateID 与现役 `c=Theme&a=InfoGet` 题材树
  （`theme_stock_mappings`）同一套 KPL 指数 ID——爆发历史/强度排行可直接挂靠
  §theme-data-governance 的 18 对挂靠映射与产业库节点，无需二次映射；
- **与 §8 方案 A 不冲突**：方案 A 的事件语料层（Topic/ThemeNews）是「催化文本」供给；
  本节是「板块行情+龙头轨迹」供给，两个正交层。精选板块补的正是题材周期命题的
  **行情结构层**，而韭研/KPL 事件流是**催化归因层**；
- 零凭据（Token=0）意味着采集链可以完全脱离账号体系（比 c=Topic 链更稳），但
  55188 论坛 2024-2025 多帖反映开盘啦持续收紧接口——免鉴权姿势可能随时被加锁，
  实施必须 fail-visible（errcode 结构化披露）+ 降级链（THS 涨停池备胎）。

### 9.6 风险与待办（接源前必须裁决/实测）

1. **限流特性未实测**（本轮 20 次单发全成功）；沿用 §5.3 串行+间隔+退避+日护栏纪律；
2. 天梯数返回 [70,9,1,0,2] 字段语义待对齐；排行 19 字段仅 5 个有权威释义；
3. 成分股真实端点未还原（9.4 两条出路）；历史强度最早可回看到哪天未测下界
   （2025-10-15 已有数，实施时一次性二分测下界）；
4. `ZSType` 其它取值（行业/细分？）未测——若含细分板块层，对「真细分挂大类」
   挂靠治理是额外收益；
5. 若立项：采集挂 8001 盘后链（16:20 槽现成），按日存 `plate_strength`/
   `plate_boom_history` 两集合，历史一次性回填（≥1 年）后题材周期 v2 立预登记。

### 9.7 复跑命令（全部零 token；单发间隔 ≥2s）

```bash
# ① 板块强度排行（实时 Type=2 / 历史 Type=1+Date；apphwhq 与 apphis 双主机均可）
curl -s -X POST "https://apphwhq.longhuvip.com/w1/api/index.php" -H "User-Agent: ad" \
  -H "Content-Type: application/x-www-form-urlencoded; charset=utf-8" \
  --data "Index=0&Order=1&PhoneOSNew=2&Type=2&VerSion=5.13.0.1&ZSType=7&a=RealRankingInfo&apiv=w35&c=ZhiShuRanking&st=80&Token=0&UserID=0"
# ② 板块爆发历史（StockID=KPL 板块 ID；Index 0/10/20 分页）
curl -s "https://apphis.longhuvip.com/w1/api/index.php?Index=0&IsBoom=1&PhoneOSNew=2&StockID=801159&Type=0&VerSion=5.16.0.5&a=GetDayBaseFaceListZDEvnArt&apiv=w38&c=ZhiShuKLine&st=10" -H "User-Agent: ad"
# ③ 天梯数（按日）
curl -s "https://apphis.longhuvip.com/w1/api/index.php?Day=2026-10-23&PhoneOSNew=2&VerSion=5.16.0.5&a=DailyLimitIndex&apiv=w38&c=HisHomeDingPan" -H "User-Agent: ad"
# ④ 成分股明细（经 wzslinker 代理，真实端点未还原）
curl -s "http://wzslinker.top/companys/api-proxy.php?type=longhuvip&endpoint=kpl_zhishu_stock_list_w8_cur&PlateID=801159&REnd=1500" -H "User-Agent: Mozilla/5.0" -H "Referer: http://wzslinker.top/companys/KPL/3.0/KPL-07精选板块.html"
# ⑤ 个股→板块映射（POST Token=0）
curl -s -X POST "https://applhb.longhuvip.com/w1/api/index.php" -H "User-Agent: ad" \
  -H "Content-Type: application/x-www-form-urlencoded; charset=utf-8" \
  --data "PhoneOSNew=2&Token=0&UserID=0&VerSion=5.16.0.5&a=InfoGR&apiv=w38&c=Theme"
```

### 9.8 抓取落库机制实测（2026-10-25 二轮，含 ID 桥裁决）

**分页与规模（全部实测）**：

| 层 | 分页语义 | 单日/单题材请求量 | 历史深度 |
|---|---|---|---|
| 强度排行 | `Index`=偏移，`st≤80`/页；当日**恰好 240 板块=3 发**（Index240 返空） | 3 发/日；回填 3发×交易日 | 按日 `Type=1+Date`，实测 2024-06-17 有数（≥2.4 年，下界未探底） |
| 爆发历史 | `IsBoom=0` 拉**全量日度记录**（每行自带 isBoom 标志，非过滤器）；`st=100`+Index 分页 | 301 条=4 发/题材；~240 题材≈1000 发一次性回填 | 机器人全史至 **2020-02-06（6.5 年）**；301 条=有记录的事件日，非全交易日 |
| 成分股 | wzslinker 代理 82 板块×2 截面 | 164 发/日（依赖第三方站点） | 仅当日盘中态，无历史 |

**关键口径**：KPL 的 isBoom 是自有爆发判定——10-23 机器人 44 家涨停标非爆发、10-22 13 家反而爆发；
落库必须原样存 `isBoom` 原始值，禁止自作主张按涨停数重算。

**ID 桥裁决（本轮最重要结论）**：题材树 ID（`84/392` 系，库内 themes 与 wzslinker
`kpl_theme_data.js` 目录 dump 完全同源 251/251 全交集）与板块指数 ID（`801xxx`）是两套体系：

1. **官方桥不存在**：题材详情 InfoGet（342KB 全字段）无指数 ID；指数端点 `c=ZhiShu&a=InfoGet`
   1020；名称匹配率仅 **47/170（28%）**——801 体系含大量地域（上海市/浙江）、业绩（再融资/
   中报增长）类指数，且粒度为聚合级（801159「机器人概念」在题材树无同名节点，树里是
   人形机器人/智元/外骨骼等细分族）；
2. **成分重叠桥成立（治理层同款判据，双例验证）**：801159 机器人概念→重叠 ≥0.40 共 7 个
   题材全是同族（物理AI0.68/智元0.56/人形0.46/AGV0.45…）；803029 物理AI→物理AI概念 0.61
   断崖第二档 0.42——双峰形态与 theme-data-governance 挂靠判据一致；
3. **桥的语义**：801 指数（聚合）↔ 题材细分族，**一对多挂靠**（方向=指数挂题材族，与治理层
   「细分挂大类」互补）；地域/业绩类指数天然挂不上（重叠趋零），等效 NOT_A_THEME 排除；
4. **桥的软依赖**：801 成分股目前只能走 wzslinker 代理（层3 直连未还原）——建桥需每指数
   拉一次成分（~170 发一次性），第三方依赖须 fail-visible；且 300 股/板块疑为代理截断值，
   完整成分可能更大（重叠率分母被低估）。

**限流未压测**：全程约 45 发单发间隔 ≥2s 零失败；1000 发级回填前必须 50 发小批试水。

### 9.9 层3 直连还原：KPL-Win7+.exe 逆向成果（2026-10-25 三轮，用户提供的代理桥 exe）

> 用户提供 `D:\TDX外挂\KPL盘中精选板块+个股\KPL-Win7+.exe`（作者凯闻李忠）。PyInstaller
> (Python 3.8) 打包，`pyinstxtractor`+手工 PYZ 提取（472 模块）+xdis 常量/结构还原。
> 提取产物归档 `data/backups/kpl-corpus-probe-20261025/exe_pyz_extracted/`。

**exe 架构**：Flask 本地 HTTP(:5000) + TLS Socket 客户端（`hwsockapp.longhuvip.com:1400`，
appconfig.ini 带心跳 10s/init 包/UUID）+ blackboxprotobuf 盲解码。本地 API：
`get_hot_block_list(_his)` / `get_block_stock_list(_his)` / `get_tradeday_list`。

**逆向决定性发现（路由函数常量全量还原）**：

1. **热门板块列表不走 Socket**：exe 直接 POST `apphq/apphis.longhuvip.com` 的
   `a=RealRankingInfo&c=ZhiShuRanking&apiv=w21`——与 §9.2 我们已打通的端点相同（免凭据）；
2. **历史成分股走 HTTP（层3 历史版=官方直连，已实测打通）**：

```
POST https://apphis.longhuvip.com/w1/api/index.php
  Type=6&Order=1&Index=<页偏移>&st=80&PlateID=<801xxx>&Date=YYYYMMDD|YYYY-MM-DD
  &a=ZhiShuStockList_W8&c=ZhiShuRanking&PhoneOSNew=2&old=1&apiv=w21
  &DeviceID=<uuid>&VerSion=5.13.0.0&UserID=<现役>&Token=<现役>   ← 需现役凭据（零凭据返回空）
  UA: Dalvik/2.1.0 (Linux; U; Android 9; ...)
→ {"list":[[300行×70字段]]}  # 与 wzslinker 代理逐字段一致；Index=80 翻页正常；2026-07-01 有数据
```

> **2026-10-27 晨勘误（st 上限）**：层3 `st` 并无 80 上限——实测 st=300 回 300 行、
> st=1000 单发回全量 800 行（机器人概念当日成员名单）。`kpl_ranking_service` 终版采用
> **真·按页取数**（用户二次裁决）：一页 = 一次上游请求（st=100&Index=行偏移，边界
> 实测续接不重叠），切板块/翻页各只发一枪，首屏 ~2-3s、翻页 <1s。注意原始名单是
> 超集（机器人概念 1296 只），App 页「共300只（显示前300只）」是 KPL 自己的展示截断。

   之前 1020 的根因：**c 控制器搞错**（应为 `ZhiShuRanking` 而非 `ZhiShuStockList`）；
3. **当日实时成分股走 Socket**（我们不需要复刻）：帧 `40 <len> <seq> | 09 C5 00 00 03 02 09 C5 |
   protobuf{1:bkcode,2:Type=6,3:Order=1,4:Index,7:st}`，cmd_id=0x09C5(2501)，响应 cmd 0x6871
   hqList 推送流——盘后采集用历史接口（Date=当日）即可覆盖，Socket 通道留作盘中实时升级项；
4. 交易日历：exe 用东财上证日K（`15.push2his.eastmoney.com`）取交易日——不必复刻。

**结论：三层全部官方直连可自建 API**——层1/层2 免凭据（apphwhq/apphis），层3 用现役
KPL 凭据（`mapping_refresh.py` 公共出口，单一事实源），wzslinker 第三方依赖彻底解除。
当日成分股建议直接用层3 历史接口 Date=当日（盘后语义更稳，避免复刻 Socket+心跳+seq 协议）。

### 9.10 Socket 实时通道复刻结果：协议已还原，会话已死（2026-10-25 四轮）

> 目标：情绪周期「日内弱转强」需要盘中帧级数据，评估 Socket 推送（hwsockapp:14000）可行性。

**协议复刻（已完整，零猜测）**：帧=3 字节头（pkg_id+len 大端）；心跳 `10 00 00`；init=appconfig.ini
硬编码包（f1=UUID/设备指纹、f3=版本、f5=32hex 签名、f8=99）；请求=`40 <len> <seq2B> <cmd2B>
00 00 03 02 <cmd> + protobuf{1:bkcode,2:Type,3:Order,4:Index,7:st}`；推送=0x60 包每 ~3s
一帧，体=`+hqList|<订阅串>`+cmd 响应块+protobuf 行（含毫秒时间戳递增字段）。自写探针
TLS(TLS1.3) 直连成功，协议层全部按预期工作。

**结论：此路已死**——①原封 init → 服务端回「**连接错误：2004**」并断开；改版本号（无论
UUID 新旧）→「1102」（签名失效，版本参与签名）；②exe 内 init 包为**作者硬编码抓包值**，
`_send_initialization_message` 只读 config，**无签名生成算法**；③决定性证据：`tls_client.log`
（该机实跑日志）**2026-06-21 20:55 起 exe 本尊已连不上**，同回 2004 反复重试后退出——作者
硬编码会话 6 月已被 KPL 封禁，本机此后无成功记录。要走 Socket 只剩逆向 KPL 安卓 APK 还原
init 签名算法（f5 hash 构造本地穷举 md5/sha1/sha256×常见拼接组合均不中）。

**盘中实时的替代路线（HTTP 轮询，无需 Socket）**：
- 层1 排行 `Type=2` 为盘中实时数据（3 发/240 板块），wzslinker 网页版自己盘中缓存 TTL 也仅
  15s（proxy-common.js）——**官方允许的盘中节奏就是轮询**；
- 层3 成分股 `Date=当日` 盘中拉即实时行情（涨幅/封板/梯队均为当前值）；
- 设计粒度：强度榜高频轮（如 60s/轮=3 发），成分股仅对进入观察名单的热门板块拉（20-80 发/轮、
  事件触发）；与 snapshot 半小时帧对齐 + 分钟级帧落 `plate_strength_intraday` 即可支撑
  「日内弱转强」（板块级判据不需要 tick 级推送；若未来需要封板瞬间级，再立项 APK 逆向）。

### 9.11 Socket 攻坚五轮：新端口/mTLS/协议钥匙全部定位（2026-10-25 深夜，雷电模拟器+Frida+APK 逆向）

> 目标不变：盘中实时推送。五轮攻坚定位了全部协议要素，卡在最后一环（白盒壳反调试+懒加载）。

**新通道拓扑（APK 6.3.20.2 实测）**：
- 新版 KPL 的 Socket 行情走 **`hwsockapp.longhuvip.com:8080`**（不再是 14000）；
- 8080 = **TLS1.3 + mTLS（服务端要求客户端证书）** + 客户端 pin 服务端证书；
- 客户端证书私钥 = **`assets/PrivateKey`（明文 PKCS#8 RSA1024）**——已提取，自签证书
  过服务端 mTLS 握手成功（服务端不 pin 客户端证书链）；
- 但 init 被服务端 RST：身份层拒绝（旧 14000 通道原 init 回「连接错误：2004」明文包，
  改版本号回 1102=签名不匹配——**版本号参与签名**）。

**协议钥匙（libauthSign.so 隐藏 JNI 导出，静态定位成功）**：
```
Java_com_yzj_kaipanh_common_Config_nativeSalt                              ← 盐
Java_com_yzj_kaipanh_newindex_common_socket_ChallengeVM_execEncryptedHex   ← init 签名算子（VM 保护）
Java_com_yzj_kaipanh_newindex_common_socket_ChallengeVM_execHex
Java_com_yzj_kaipanh_newindex_common_socket_SocketHelper_crtFromJNI        ← mTLS 客户端证书
```
包名 `com.yzj.kaipanh.*.socket` 即协议层。**签名算法无需逆向**——这四个函数可被
Frida Java 桥直接调用（当「签名服务」用）。

**动态调用受阻的完整原因链**（五轮实测，均为可复现结论）：
1. APK 白盒壳（`com.kpl.armor` + `MainActivityKt.decodeMsg`）：真 dex 运行时解密，
   jadx 反编译只见 13KB stub，业务类不在磁盘；
2. 业务类**懒加载**：只有进入行情页建立 socket 后 ChallengeVM/SocketHelper 才加载
   （枚举已加载类 = NONE）；
3. **TLS 在 arm 层**：app 自带 arm 库（libauthSign.so 静态链接 openssl），雷电 x86_64+
   houdini 翻译下，x86 Frida hook 系统 libssl/libc 均零流量（已逐层排除：conscrypt Java
   层 hook 成功挂载但零流量、libssl.so hook 挂载零流量、libc connect/send hook 挂载零触发）；
4. attach 主进程会被反调试挂死（Java.perform 永不返回），**spawn 模式 Java 桥可用**；
5. 多进程结构（主进程父子+pushservice 父子）+ app 在 houdini 下频繁崩溃重启，
   frida-server 视图与 adb 视图 pid 不同步。

**破局路径（下次开工直接走）**：
A. spawn KPL → UI 自动导航进行情页（触发 socket 类加载）→ `Java.enumerateClassLoaders`
   找到壳 loader → `Java.ClassFactory.get(loader).use('...ChallengeVM')` →
   **hook execHex 观察真实输入输出**（init 请求参数+签名结果直接现形）→ 依样复刻；
B. 或把模拟器常驻成「签名服务」：frida RPC 暴露 ChallengeVM.execHex，自研客户端
   每次建连前 RPC 调用取签名——不逆向算法、直接用官方算子（mTLS 证书用
   assets/PrivateKey + crtFromJNI）；
C. 环境：需交易日盘中（行情页流量才会建立 socket+类加载）或 root+LSPosed 常驻。

**本轮产物**：`kpl.apk`（6.3.20.2 官方）、`libauthSign.so` 全导出解析、frida-server
16/17 双版本注入环境、恶意服务器 mTLS 验证（证书链不 pin 客户端）、协议钥匙 4 函数定位。
全部脚本与证据在 `.tmp_review`（临时）——固化时移 `data/backups/kpl-corpus-probe-20261025/`。
接口文档来源：[Apifox 开盘啦抓包读数（用户提供）](https://immgpzl8u9.apifox.cn/)、
[Gitee mikasama/add_system 参数释义](https://gitee.com/mikasama/add_system)、
[55188 论坛「开盘啦接口」帖（接口收紧佐证）](https://www.55188.com/topics-1151166.html?page=2)。
