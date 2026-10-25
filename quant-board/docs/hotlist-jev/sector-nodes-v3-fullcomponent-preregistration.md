# 板块节点 V3 预登记：全成分增强（静态成分聚合对照列 + 扩散信号）

> 2026-10-25 立项，用户三拍板：①首拉全量 108 次 stock-tree；②刷新频率=每周全量；
> ③成分口径=**全量纳入+披露关联强度**（0.01% 级股权关联股也进，与韭研页面同口径，
> 影子期先看分布再议过滤）。前置链路（V1 节点表 / V2 活跃聚合 / V2c 盘中脉冲）
> 判据零改动——本预登记只加**影子对照列**，不进 classify_board_day。

## 一、目标场景

V2 的 aggN10（近 10 日涨停并集聚合）衡量「**强势股群体**」当日表现；V3 补
「**整个产业概念股**」当日表现（aggStatic，韭研产业库全成分）。两列之差=**扩散度**
观察位：

| 形态 | aggN10 红盘 | aggStatic 红盘 | 解读（中性展示，影子期不做判定） |
|---|---|---|---|
| 独角戏 | 高 | 低 | 强度集中在活跃股，未扩散到全成分 |
| 普涨 | 高 | 高 | 全成分跟涨，真发酵 |
| 轮动接替 | 低 | 高 | 高位活跃股退、低位全成分起 |

## 二、成分归档口径（冻结，V3-1）

- 端点（2026-10-25 实测定形）：`POST /jystock-app/api/v1/ai/industry/stock-tree`
  body `{"code": 一级code}`（GET 被 405 拒）；返回该产业全树，成分挂各级
  `stock_list[]`。
- 展平：同股多节点出现取 `shares_range` 最高人次（关联最强口径）；
  `stock_code` 归一 6 位纯数字（sz/sh/bj 前缀剥离），非 6 位剔除计 invalidN。
- 落库：集合 `jiuyan_industry_stocks`，`_id=一级code`，快照式
  {batchDate, stocks[], stockN, stocksDigest, prevDiff{added,removed},
  prevBatchDate, changedAt}。**prevDiff 只存摘要不存全量旧版**——完整历史不可
  重放，登记为已知局限（读数行级 batchDates 披露口径）。
- 编排：`jiuyan_theme_collect --stock-tree`（断点续拉=跳过当日已成功；串行
  20s 间隔 + errCode=9 退避 60s 重试 1 次；空成分按失败不落假成功）。
- **刷新频率（拍板项②的等价实现）**：周日无交易日挂链 → 改为交易日 16:10
  调度守卫「距最新成功批次 ≥7 自然日则 Popen 挂跑全量」（节假日自动顺延；
  首拉后下个触发窗≈8 天）。预算 env `JIUYAN_STOCKTREE_WEEKLY_BUDGET`（默认
  120=108+产业树 1+重试余量）；开关 `JIUYAN_STOCKTREE_WEEKLY_ENABLED=0`。
- 调用计数进 `jiuyan_api_calls`（source=industry_stock_tree，与异动端点
  /action/* 两套独立日额度互不影响，2026-10-20 实测）。

## 三、板块名映射（冻结，V3-2）

对拍基线（2026-10-25，近 20 交易日 52 板块名 vs 产业库 108 一级节点）：
24 自动可映射 / 2 多义 / 26 未收录（其中约 6 个为「公告/其他/新股/次新」类
非产业桶）。

- 规则：停用词（公告/其他/新股/次新/ST/B股/转债）直接未收录 → 精确同名
  exact → 双向包含唯一 contains → 双向包含多命中 **multi-union 全并集**
  （action 粗粒度板块天然跨产业细分，如 机器人 → 国产机器人+特斯拉机器人+
  机器人零部件+四足机器人/机器狗）→ 其余未收录。
- 集合 `sector_industry_mapping`：`_id=action板块名` {industryCodes,
  industryNames, matchType, mappedAt}。auto 行由 `--rebuild`（扫近 20 交易日
  板块名）幂等重建；**manual 行（`--set 板块=产业1,产业2`）不被覆盖**；
  产业库换名录后失配 auto 行删除（不留脏映射）。
- 未收录板块照常出节点行，aggStatic 标「产业库未收录」（fail-visible）。

## 四、静态聚合口径（冻结，V3-3）

- **与 aggN10 完全同式同棒链**：复用 `sector_agg.aggregate_day`（pctMean/
  pctMedian/redRatio/memberN/quotedN/missingN 同表），成员=映射产业全成分
  并集（去重取关联最强），日线棒同走 `_daily_bars`（本地 vipdoc 优先+线上
  补尾，进程缓存重叠股零重复 IO）。
- 行级挂载：`rows[].aggStatic = {mapped, …stats, industries[], batchDates[],
  sharesMedian}`；未映射 {mapped:false, reason}。aggExtraRows 同样挂载
  （「未收录」本身是观察信息）。meta 增 aggStaticVersion / staticMapped /
  staticUnmapped。`AGG_STATIC_VERSION="2026-10-25a"`。
- 前端：主表加「全成分」列（与聚合涨幅并排）；展开卡两列对照+扩散差值行
  （红盘率差，中性文案）；hint 加映射摘要。

## 五、已知局限（如实登记）

1. **前视回放**：产业库为活库（无历史），历史回填日读到的是「当前批次成分」
   ——2026-10-25 之前的日子 aggStatic 属前视口径，行级 batchDates 披露；
   攒批次后自然消除。
2. **低关联噪声**：全成分含 0.01% 级股权关联股，pctMean 被无关股稀释趋近
   大盘均值——redRatio 判别力预期更强；sharesMedian 披露成分关联度，
   过滤与否凭影子期分布再裁（改口径须新版本戳+用户批准）。
3. **覆盖面**：产业库 108 节点覆盖约半数 action 板块（新题材入库滞后），
   周刷 + rebuild 重放自动跟进。
4. **快照原子性**：108 板块分批落库（断点续拉），跨板块 batchDate 可能差
   一日（挂跑中断时），读数层按行级 batchDates 披露不掩盖。

## 六、验收

- pytest 专项：`test_jiuyan_industry_stocks.py`（归档链 15 用例，含 errCode=110
  重铸自愈两例）、`test_sector_industry_map.py`（映射+静态列 10 用例）、既有
  sector_nodes / jiuyan_theme_collect 零回归。
- 首拉冒烟：108/108 ok、成分规模分布合理、`jiuyan_api_calls` 计数=108。
- 映射冒烟：`--rebuild`（默认全史扫描域）后板块映射清单人工过目（多义并集
  逐条可读）。
- settle_day 冒烟：单日重算落库，aggStatic 已映射/未收录/缺棒三态抽查。
- 浏览器验收用户本人做（全成分列+展开卡对照）。

## 七、review 修复（2026-10-25 当轮，用户令确认修复）

- P2 周频守卫在途互斥：当日日志文件存在且 mtime=今日 → skip（拦 15:35 手工
  挂跑未完时 16:10 守卫双 Popen 并发；完成态仍由批次年龄判定覆盖）。
- P3-1 动态预算：守卫 Popen 传 `--budget 当日已用+110`（防 collect_once 先用
  N 次后固定 120 把周刷挤成连续顺延）。
- P3-2 时长注记：_static_rows_compute docstring 登记「手工重算历史日且 vipdoc
  未更新 → 线上补尾膨胀，先跑盘后下载或 JEV_BARS_ONLINE_TAIL=0」（生产
  sectorNodes 步在盘后下载后跑，本地命中毫秒级）。
- P3-3 rebuild 扫描域默认全史（days=0）：近 20 日窗口会让更老板块 auto 行在
  产业库换名录后静默残留。
- P4：验收用例数 13→15 勘正、collect_stock_tree docstring 预算说明对齐
  代码（max 默认放行）、rebuild 空串过滤防 mapped 虚增。
