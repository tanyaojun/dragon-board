# 新题材正文采集预登记（2026-11-02）

> 状态：已探明端点、待实施。判据与消费语义改动均在本文件预登记，实施前用户已裁决「进入正文抓包和立项」。

## 一、背景与动机

新题（`kpl_theme_news`）现有原料：标题、Kword 题材标签（约七成条目为空）、ZSName 官方板块归属（约三成覆盖，2026-11-02 裁决①已接入）、关联股。当日新题如「轨道算力」（标题不含任何板名词、Kword 空、ZSName 空），其催化细节（SpaceX 轨道数据中心长文）只存在于**正文**。正文缺失时该类新题只能靠标题锚兜底，漏配即真漏。

## 二、端点（已实证）

- `POST/GET https://apparticle.longhuvip.com/w1/api/index.php`（与列表同 host 同 base 参数）
- `c=ThemeNews & a=GetInfo & NewsID={cid} & st=1`
- **参数名必须是 `NewsID`**（实证 `InfoID/CID/ID` 均只返回空壳 `{Info:{Coll:0}}`）
- 响应 `Info`：`CID, Title, Source, TimeStamp, Kword, KwordDesc, ZSCode, ZSName?(未见于detail), IsChoice, Statu, Coll, Comm, Stocks, Content(HTML)`

## 三、采集方案（预算制，同 topic_detail 模式）

1. `fetch_news_detail(cid)` → `{ok, detail:{content, kwordDesc, zsCode, isChoice, ...}}`；失败结构化、计入 `detailFailures`（fail-visible，同事件详情）。
2. `collect_once` 中 detail 阶段：对**当日窗内 news 条目**（`eventDate==fetch_date`）逐条拉 detail；预算不足整节跳过并 `skippedByBudget` 标注（现行为：`topic_detail` 同款）。
3. 存储：`kpl_theme_news` 文档新增 `contentHtml`（原始 HTML 单主链，消费端剥标签）、`kwordDesc`、`zsCode`、`isChoice`；空详情不覆盖已存内容（同 `test_empty_detail_never_overwrites_content` 惯例）。
4. 回填：一次性脚本对存量近 3 日条目回填 detail（确定性重放，零 jev token）。

## 四、预算

- 计入 `kpl_api_calls` 同一日预算（`KPL_THEME_DAILY_CALL_BUDGET`，默认 20）。news detail 数量≈每日新增条目数（实测 50/轮但**当日新条目**约 10-30）。
- **裁决点（默认方案 A）**：日预算 20 → 40；若连续两日 `skippedByBudget` 含 `news_detail` 再上调。
- KPL 直连调用，**零 jev token**，不触红线 §1.2-7。

## 五、消费语义（预登记裁决项）

1. **匹配**：正文剥 HTML 后进入 `_anchor_hit` 兜底层（在标题锚之后）：命中标注 `正文锚`，按 2026-10-28 裁决语义这是**弱匹配**（标题未命中），显式标「弱匹配（仅正文级关联）」——与事件通道同款，防泛科技通稿误配。
2. **叙事**：正文**不进叙事行**（v12 事件块同款裁决，防 token 爆炸）；证据可见性走既有 `evidenceNewsTitles`（已镜像）。
3. **ZSCode**：只存不用（备将来板块代码互认）；`KwordDesc`/`IsChoice` 只存不用，待后续裁决。
4. **测试**：全程 mock（红线 §1.2-7）；断言：detail 失败不阻断主源、空不覆盖、弱匹配标注、预算跳过标注。

## 六、验收

- 实跑一轮：`kpl_theme_news` 当日条目 contentHtml 覆盖率 ≥90%（detailFailures 单列）。
- 回放「轨道算力」：`轨道算力` 板块经正文锚命中且带弱匹配标注；`match_kpl_news` 回归不回退。
- 全量 pytest 通过；relay/`/theme-leaders` 合同不变（只增字段）。
