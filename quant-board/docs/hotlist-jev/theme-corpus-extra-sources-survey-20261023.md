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
