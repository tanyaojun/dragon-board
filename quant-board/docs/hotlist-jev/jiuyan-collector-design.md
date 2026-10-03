# 韭研公社异动采集器设计（v1，2026-10-02 确认稿）

**性质**：brainstorming 产出（四项裁决：12:00+15:30 两次采集 / 先落库后接线 / 回填 9 月 / token 缓存+失效才铸）。
**目的**：韭研公社（jiuyangongshe.com）异动数据作为 jev/规则分的**结构证据原料**——板块分组、涨停时间、连板数、人工解析全文，补"规则分没有结构视角"的短板（2026-10-01 原料排查结论）。

## 0. 已验证事实（2026-10-02 实测，详见记忆 hotlist-jev-project）

- 主数据端点 `POST https://web-api.jiuyangongshe.com/jystock-app/api/v1/action/field`，body `{"date":"YYYY-MM-DD","pc":1}` → ~85KB：`data[]` 板块（name/count/list[]：code/name/article.action_info{涨停时间 time/连板 num/price/day/reason/expound 解析全文}）。
- 请求头三件套：`platform: 3` + `timestamp`（ISO Z 秒级）+ `token`。**token = 页内 `globalThis.nR4xKp7mQa($nuxt.$store.state.mQ7vL2xR9a, Date.now())` 生成**，确定性纯函数、与 body 无关、秒级截断；**实测新鲜度 ≥2 分钟**（同 token 重放返回真数据）。
- 认证：`SESSION` cookie（可读非 httpOnly，已入 `.env.local JIUYAN_SESSION=`）+ token 缺一不可（假 token→errCode 110；无 token→110；有 token 无 cookie→登录失效）。
- 匿名 GET `https://www.jiuyangongshe.com/action/YYYY-MM-DD` 可得页面 HTML（含 SSR digest，公开）。
- **token 算法是字节码 VM 混淆 + 环境反篡改**：Node 提取跑 VM 被反篡改拦截（调用栈指纹检查），**浏览器页内调用是唯一已证生成路径**——token 铸造必须走浏览器（playwright），Node sidecar 路线已证伪废弃。
- 站点更新节奏：交易日 12:00、15:30 前各一次（站点公告）；历史日期可查。

## 1. 架构归属

8001 采集器（snapshot_collector scheduler 支线，asyncio.to_thread，与快照采集互不阻塞）。采集、存储、读口三层分离：

| 组件 | 文件 | 职责 |
|---|---|---|
| fetch/parse 纯函数层 | `backend/operations/jiuyan_fetch.py` | digest 提取、API 调用（requests）、响应解析、fail-visible |
| token 铸造 | `backend/operations/jiuyan_mint.py`（T6 批） | playwright headless + 持久 profile（`data/jiuyan_browser_profile/`），页内调全局函数取 token；首次 headful 扫码 |
| 存储层 | `backend/operations/jiuyan_store.py` | `jiuyan_action` 集合读写（date:kind 键控，幂等 upsert） |
| 回填 CLI | `backend/operations/jiuyan_backfill.py` | `--month YYYY-MM`，3-5s 间隔，分批铸 token |
| 调度支线 | `backend/snapshot_collector/scheduler.py` | 交易日 12:05（midday）/ 15:35（final）各一次，每日 ≤2 次 |
| 读口 | `backend/api/hotlist_jev_routes.py` | `GET /api/hotlist-jev/jiuyan-action?date=` |
| 前端 | jev 第 7 页签最小卡 | 按日折叠、板块分组、解析全文 |

## 2. 存储（独立集合——微信爬虫教训：不碰上游集合）

集合 `jiuyan_action`，`_id = "<date>:<kind>"`（kind=midday/final，两文档互不覆盖，重采幂等覆盖同键）：

```json
{ "_id": "2026-09-30:final", "kind": "jiuyan_action",
  "tradingDate": "2026-09-30", "updateKind": "final",
  "counts": {"all": 64, "recommend": 5},
  "fields": [{"name": "医药医疗", "count": 10,
              "stocks": [{"code": "sz000504", "name": "南华生物", "price": 12.42,
                          "time": "10:22:42", "num": "9天5板", "day": 5,
                          "reason": null, "expound": "解析全文", "articleId": "…",
                          "likeCount": 12}]}],
  "quality": {"degradedSources": [], "tokenSource": "cache|minted|manual"},
  "fetchedAt": "…iso" }
```

fail-visible：缺源记 degradedSources，不伪造 0。**不写入 theme_stock_mappings 等任何上游集合。**

## 3. token 管理（缓存 + 失效才铸）

- **【2026-10-02 用户红线修订】token 缓存不再落 MongoDB**（原 `jiuyan_meta` 集合已 drop）：机密/凭据禁止入业务库，静态凭据=SESSION（`.env.local JIUYAN_SESSION=`），**动态铸造 token 缓存=Redis**（键 `<prefix>:jiuyan:minted-token`，24h TTL 兜底，authFailed 时显式删除；Redis 不可用 fail-visible 返回无缓存）。存储层 `jiuyan_store.get_cached_token/save_token/clear_cached_token`。
- 采集流程：读缓存 token → `count-pc` 便宜探针（errCode 0 → 用；110 → 铸新）；
- **铸造路径**：T1-T5 期=手动（AI 在 ZCode 浏览器页内生成后写入 meta）；T6 批=playwright 自动（headless + 持久 profile，首次 headful 扫码；digest 与 token 同页可得）；
- 会话过期症状=新 token 仍"登录失效"→ 浏览器重扫码 → 更新 profile。

## 4. 采集时点与回填

- 交易日 **12:05（midday）+ 15:35（final）**，每日 ≤2 次；非交易日跳过（trading calendar）。
- 回填：`jiuyan_backfill.py --month 2026-09`，21 交易日 × final × 3-5s 间隔；token 每 10 请求重铸保险。

## 5. 第一版边界（先落库后接线）

✅ 采集、落库、读口 API、jev 页签最小卡、9 月回填。
❌ 不接进 jev 槽位叙事（数据质量审阅后另行批准）；不下载涨停简图 PNG；不碰规则分与引擎。

## 6. 风险登记

| 风险 | 处置 |
|---|---|
| 站点签名/VM 变更 → token 铸失败 | fail-visible 告警；playwright 页内调用对算法内部变更天然免疫，页面结构变更才需修 |
| 会话过期 | 重扫码；失效症状与处置见 §3 |
| 站点条款（人工内容禁商业转载） | 个人研究用途、注明来源、不公开分发原文 |
| midday/final 内容差异未知 | 两版都存，回填后对比审阅 |
| playwright 新依赖部署分量 | 隔离在 T6 单独批；此前手动铸不影响主线 |

## 7. 实施顺序（TDD，每步验收提交）

- **T1** fetch/parse 纯函数层 + 固定样本测试；
- **T2** 存储层（幂等/降级测试）；
- **T3** 回填 CLI + 9 月回填 + spot-check（南华生物 09-30 在库、字段齐）；
- **T4** 调度支线 + 8001 重启；
- **T5** 读口 API + jev 页签最小卡；
- **T6** playwright 自动铸（另批）。

## 7. 登录与会话运行事实（2026-10-03 补采 5-8 月实测）

- **单会话策略（实测证实）**：账号新登录会踢掉所有旧会话——.env.local SESSION「过期」的根因即此（用户在他处重新登录）。运行纪律：**账号只保持一处 canonical 登录**；凡在他处登录，必须同步更新 .env.local 并重启 8001。
- **鉴权 cookie = 可见 SESSION**：document.cookie/devtools 里非 HttpOnly 的 SESSION（base64，48 字符）即鉴权级，python `Cookie: SESSION=<值>` 单值配方（§2 已验证配方）继续有效；此前 python 链「登录失效」全部是会话刚被踢的时序假象，非 httpOnly 缺失。`sl_session`/`admin` 等伴随 cookie 不需要。
- **每日查阅配额（新发现）**：errCode=9「您今天的查阅次数已达到上限」——单日约 150+ 次 field/count 查阅后触发（2026-10-03 补采 98 天时实测，08-27/28/31 三天待次日配额刷新后 --skip-existing 补齐）。**实时采集（≈4-6 次/日）远低于限额**；批量回填需控节奏分日执行。
- **T6 持久 profile 升级为根治项**：playwright 固定档案（`data/jiuyan_browser_profile/`）保持账号登录态，铸 token 与取数均在页内完成——canonical 登录收敛到档案一处，.env.local SESSION 不再是单点；在此之前以「.env.local + 单处登录纪律」运行。
