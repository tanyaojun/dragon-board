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
| 认证链（登录+铸造） | `backend/operations/jiuyan_auth.py`（2026-10-05） | resolve_auth 编排 / playwright 匿名页铸 token / 账号密码登录换 SESSION / Redis 双缓存 |
| 存储层 | `backend/operations/jiuyan_store.py` | `jiuyan_action` 集合读写（date:kind 键控，幂等 upsert）+ token/session Redis 缓存 |
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
- 采集流程：认证解析（§8）→ `count-pc` 便宜探针（errCode 0 → 用；authFailed → 自愈重试一次）；
- **铸造路径（2026-10-05 起自动化）**：`jiuyan_auth.mint_token_via_browser(date)` = playwright headless chromium 匿名打开异动页，页内调 `globalThis.nR4xKp7mQa($nuxt.$store.state.mQ7vL2xR9a, Date.now())` 直接得 `{timestamp, token}`；无 cookie 调 count-pc 返回 errCode=1「登录失效」而非 110「token无效」= 匿名铸造 token 已过防伪层（当日实测）。T1-T5 期手动铸成为历史，`jiuyan_backfill.py --token` 手动传参路径保留可用。
- 会话过期症状=新 token 仍「登录失效」→ §8 认证链自动重登/静态回退，人工重扫码不再是必经路径。

## 4. 采集时点与回填

- 交易日 **12:05（midday）+ 15:35（final）** 各一次，每日 ≤2 次；非交易日跳过（trading calendar）。
- 回填：`jiuyan_backfill.py --month 2026-09`（**2026-10-05 起 --token 可选：缺省走 `jiuyan_auth.resolve_auth` 自动认证链**；--token/--timestamp 手动路径保留），逐请求 2-5s 间隔；fail-visible 中止后 --skip-existing 续跑。

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
- **每日查阅配额（新发现）**：errCode=9「您今天的查阅次数已达到上限」——单日约 150+ 次 field/count 查阅后触发（2026-10-03 补采 98 天时实测，08-27/28/31 三天待次日配额刷新后 --skip-existing 补齐。**2026-10-05 已补齐，8 月 final 21/21 满覆盖**）。**实时采集（≈4-6 次/日）远低于限额**；批量回填需控节奏分日执行。
- **T6 持久 profile 升级为根治项**：playwright 固定档案（`data/jiuyan_browser_profile/`）保持账号登录态，铸 token 与取数均在页内完成——canonical 登录收敛到档案一处，.env.local SESSION 不再是单点；在此之前以「.env.local + 单处登录纪律」运行。**（2026-10-05 更新：§8 认证链自动化落地后 T6 恒久登录态不再必要——headless 匿名页每次按需铸造即可，T6 恒久 profile 方案搁置）**

## 8. 认证链自动化（2026-10-05 落地，用户裁决：账号密码动态登录替代静态 session）

- **登录接口（2026-10-05 浏览器抓包实测）**：`POST {API_BASE}/user/login`，body `{"phone","password"}` **明文**（无客户端加密）、无前置验证码；但必须携带 token 头（缺/假 → errCode 110，与数据接口同款防伪）。服务端密码规则：8-12 位、必含字母+数字+特殊字符（假账号探针实测回显）。登录响应 errCode=0 时 `Set-Cookie SESSION=...`，requests.Session/响应 Set-Cookie 头双路解析。
- **token 新鲜度=分钟级（2026-10-05 真机实测）**：缓存 ≈20 分钟的旧 token 登录必 110「token无效」；现铸新 token 登录成功——**登录路径一律现场新铸不读缓存**（`resolve_auth` 登录分支）；数据路径复用窗口保守取 5 分钟（`TOKEN_FRESH_SECONDS`，超窗重铸；10-03 批量回填实证单 token 连用 ≥8 分钟有效，上界未知）。Redis 24h TTL 降级为存储上限，真实门=新鲜度检查。
- **凭据来源**：`JIUYAN_PHONE` / `JIUYAN_PASSWORD` 进 `quant-board/.env.local`（静态凭据红线：只进 env，不入 DB/Redis 持久值）。未配置时走静态 `JIUYAN_SESSION` 回退，行为不劣化。
- **动态会话缓存**：Redis 键 `<prefix>:jiuyan:session`，24h TTL 兜底，authFailed 显式删除（与铸造 token 缓存对称，存储层 `jiuyan_store.get_cached_session/save_session/clear_cached_session`）。
- **resolve_auth 编排**（`jiuyan_auth.resolve_auth`）：Redis 缓存（session+token）→ 缓存缺则浏览器铸 token（必要时登录）→ 无凭据则静态 JIUYAN_SESSION 回退 → 全无 fail-visible。source 记账 `<会话源>+<token源>`（cache|login|env + cache|minted）落 `jiuyan_action.quality.tokenSource`。登录失败不静默回退静态会话；静态回退会话不入缓存。
- **采集自愈**：`collect_and_store` authFailed（探针「登录失效」或 field 110）→ 清两缓存 → `resolve_auth(force_refresh=True)`（跳缓存强制重铸/重登）→ 重试一次；仍失败返回原错误并附 `selfHeal` 留痕。
- **单会话互踢（重要运行后果）**：自动登录即 canonical 登录——用户在他处登录会把自动链踢下线（下次采集自愈重登，同时踢掉用户浏览器会话）；凭据上线后 .env.local 静态 SESSION 只是兜底，不再需要每日手工维护。
- **测试**：`tests/operations/test_jiuyan_auth.py`（21）+ `test_jiuyan_collect.py`（6）+ store/回填测试（3+4 新增），全部 mock 禁真调用；真机验证（2026-10-05）：headless 铸造 25s（含冷启动）、无会话探针 errCode=1（token 过防伪层）、假账号登录达服务端密码校验、**真凭据动态登录成功（新 token 登录 → 新会话探针/补采 3 天全过，source=login+minted）**——动态登录链生产验证闭环。
