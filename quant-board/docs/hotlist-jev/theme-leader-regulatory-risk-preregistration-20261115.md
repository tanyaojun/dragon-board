# 题材龙头/竞价龙头语料 · 监管风险（严重异动/重点监控）接入预登记（2026-11-15）

> 状态：预登记 + 用户裁决已确认（2026-11-15）。探针实锤后本文 §2 列序定档，实施按 §3-§7。
> 上游截图：KPL App「开盘 › 异动提醒」页（严重异动 / 热门股偏离值 / 重点监控 三页签）。
> 红线遵循：AGENTS §1.2-5（文档/展示同步）、§1.2-7（测试禁真调用）、§1.2-8（叙事卫生/整行缺席）、
> §1.2-9（频控预算）、§4.0（fail-visible）。

## 0. 背景与用户裁决

题材龙头打标链事件层（`theme_event_digest` 消费 KPL 题材事件/新闻/日历）只含利好催化；
风险侧仅有 2203 伴生公司级风险画像（减持/解禁/质押/fx）。监管收紧周期下，**交易所级监管事实**
（重点监控期、严重异动、停牌/复牌、偏离值空间、涨停即触发严重异动预测）缺失，直接影响
「次日续板」判定（涨停=触发监管=续板意愿压制）。

用户裁决（2026-11-15）：
1. **五组全进叙事**（监管期/历史监管/近期严重异动/今日触发/明日触发）；
2. **先按日采集**（每日 1 槽，收盘后 **17:00**——2026-11-15 用户裁决由 15:10 改；手动 CLI 可补）；
3. **竞价链同批接入**（auction_leader_ammo/auction_leader_label）；
4. **前端页面同步增加**（relay_page 新页 + 个股行情池行 badge）。

与 socket 2030（abn，个股详情页横幅，口径未钉死暂停渲染）**不是一类数据**：2030=单股实时
偏离横幅；本链=市场级监管列表（HTTP）。不构成并行双轨（§1.2-1）。

## 1. 源合同（反编译实锤，`.tmp_review/main_src/sources`）

页面类 `deviation/activity/AbnormalAlertActivity` → `SevereAbnormalFragment` / `MonitorListFragment`；
请求构造 `SevereAbnormalPresenter.java:232-246`、`ox0.java:6876/6947`。全部 HTTP POST form
（`HttpUtils`，非 socket），`c=StockBidYiDong`，公共参数同 `KPL_APP_BASE_PARAMS` 出口
（游客 UserID/Token=0 优先，1001 时回退现役凭据）。

| # | 分组 | 域 | a | 参数 | 响应键（SerializedName 实锤） |
|---|---|---|---|---|---|
| 1 | 严重异动·今日+明日触发（当日） | apphq | `GetPianLiZhi_W46` | — | `{Day, Time, List_Today, List_Tormorow}`（上游拼写 Tormorow） |
| 2 | 严重异动·今日+明日（历史日） | apphis | `GetYDTPZFPL_W46` | `Day` | 同 #1 |
| 3 | 近期严重异动 | apphis | `GetYDTPZFPL_W46_HisAll` | `Day, IsZT, Status?, Index, st` | `{List_His, List_His_Total}` |
| 4 | 重点监控·监管期 | apphq | `GetYDTP_ZDJK_Today` | — | `DateListEntity<hh0>`（外层键探针定档） |
| 5 | 重点监控·历史 | apphq/apphis | `GetYDTP_ZDJK_His` | `Day?`（空=HQ） | 同 #4 |

行语义已钉死：
- `hh0`（`MonitorListAdapter.java:104-134`）：`c`=代码、`d`=名称、`b`=监控开始、`a`=监控结束、`f`=监管期标志。
- 严重异动行（`ar0.c`，今日组，≥14 列）：`[0]`代码、`[1]`名称、`[10]`板块标签串、`[11]=="1"`→重点监控；
  显示列 `[3][5][6][9][12][10][19]`。**响应全为预格式化字符串**（"17.90%"/"10日100%"/日期串），
  无 ×10000 缩放陷阱——原样落库原样渲染，不自算（避开 2030 式口径悬案）。

待探针定档：明日组/近期组列序（`ar0.a/b` dump 跳过）、`IsZT/Status` 过滤器取值、ZDJK 外层键。

## 2. 探针定档（P0，2026-11-15 实弹 8 发全 errcode=0，游客凭据可用）

预算执行：8 发、串行间隔 ≥3s、失败不重试。raw 证据已摘要本节，`tmp/` 脚本与 jsonl 用完即删。

**列序定档（与 App 截图逐项交叉，2026-11-13 日样本）**：

触发组（`List_Today`/`List_Tormorow`，20 列）：
`[0]`代码 `[1]`名称 `[2]`周期标签(「10日100%」/「30日200%」) `[3]`涨幅%(今日组=当日涨幅；明日组=次日涨幅占位0)
`[4]`连板标签(「昨5连板」) `[5]`触发异动涨幅% `[6]`股票价格(元原样) `[7]`当日触发偏离值空间%(今日组渲染列)
`[8]`状态文本(「未触发异动」/「触发严重异动」) `[9]`次日触发偏离值空间%(明日组渲染列) `[10]`板块标签串
`[11]`重点监控标志(1=是) `[12]`周期标签复述 `[13]`触发价(未钉死,raw 留档不渲染) `[14..16]`raw
`[17]`复牌日期(「0000-00-00」=无) `[18]`异动日期 `[19]`偏离基准价(raw 留档不渲染)。
交叉证据：九阳 `[3]=0.38↔0.38%`、`[5]=0.41↔0.41%`、`[7]=0.04↔0.04%`；闽发 `[3]=-9.93↔-9.93%`；
大东方 `[4]=昨5连板`、`[7]=17.83↔17.83%`；辰奕明日组 `[5]=17.9↔17.90%`、`[9]=17.9↔17.90%`、`[6]=42.23↔42.23`。
百分比=上游数值原样+%后缀（与截图一致），价格元原样；`[13]/[19]` 不渲染（未钉死不伪精度）。

近期组（`List_His`，20 列，日期降序，`List_His_Total`=542 需分页 Index）：
`[0]`代码 `[1]`名称 `[2]`周期标签或状态文本(停牌股=「股票价格异常波动达到停牌核查」) `[8]`状态文本
`[10]`板块标签串 `[11]`重点监控标志 `[15]`触发严重异动标志 `[16]`停牌标志 `[17]`预计复牌日期 `[18]`异动日期；
其余数值列未钉死→raw 留档不渲染。交叉：天普 `[18]=2026-11-16`、`[17]=2026-11-19`、`[16]=1`、`[11]=1` ↔ 截图
「26-11-16 停牌 预计复牌11-19 重点监控」。**过滤器 IsZT 语义可疑（IsZT=2 与 0 同总）→ 不用过滤器，
客户端按 `[15]/[16]` 标志派生**；日采 Index=0,1 两页（60 行，日期降序覆盖近期窗）。

监控组（`List`，≥5 列）：`[0]`代码 `[1]`名称 `[2]`监控开始 `[3]`监控结束 `[4]`类型标志(raw)。
交叉：监管期 5 条 ↔ 截图（海洋王/大业/福新转债/新华传媒/天普）。

**覆盖边界（如实披露）**：`GetYDTP_ZDJK_His`（HQ 无 Day 与 HIS 带 Day 两形态均实测）仅返回有限窗
（1 条凡拓数创），截图历史 3 条疑为 App 客户端累积展示——历史监管组**上游给多少落多少**，
不伪造完整历史；叙事监管事实以监管期+近期严重异动（含重点监控标志）为主承载。
`GetYDTPZFPL_W46` 历史日 `List_Tormorow` 恒空（明日预测仅当日 HQ 有）——历史回填该组结构化空态。

**日采端点组合（5 发/日）**：HQ `GetPianLiZhi_W46`(today+tomorrow) + HIS `GetYDTPZFPL_W46_HisAll`
Index=0/1(2 发) + HQ `GetYDTP_ZDJK_Today` + HQ `GetYDTP_ZDJK_His`。CLI 历史日：severe 改 HIS
`GetYDTPZFPL_W46`、recent 带 Day、monitor_history 改 HIS 带 Day（monitor_current 仍 HQ，as-of 语义注记）。

## 3. 采集与存储（P1）

- 新协议层 `backend/services/kpl_regulatory_risk.py`：fetch（5 端点，逐端点 try/except 互不连带）
  + 纯解析器（行→具名字段，缺位 None，raw 原样留档；空列表=真零与未采集区分）。
- **单写者** `DabanPoolArchiver`（:8000）新增 `regulatory` lane：交易日 **17:00 后每日 1 次**
  （15:00 收盘终值；早于 16:10 竞价结局回填与 17:30 题材投喂；次日 09:26 竞价投喂消费前日档
  `List_Tormorow`=当日触发预测）。非交易日不采；进程重启错过时点当轮自愈补采。
- **频控预算（§1.2-9）**：5 发/日、**无重试**（review m3 裁决：部分端点失败当日定格+
  `reg_states` 留痕，全源失败不写、下一轮自愈；方向保守不违反频控）；日预算上限
  `KPL_REGULATORY_DAILY_CALL_BUDGET` 默认 10，**发弹前**预留预期发数门控
  （`used + REGULATORY_EXPECTED_CALLS > budget` 即 skip，archiver/CLI 同款，review M2/m2）；
  计数入 `kpl_api_calls calls.regulatory`（失败同样计数，dry-run 同样计数不写库）。
- 存储：`kpl_daban_pool` 日档字段级 `$set` 新前缀 `reg_`：`reg_date/reg_ts/reg_groups`
  （today/tomorrow/recent/monitor_current/monitor_history 五列表）`/reg_by_code`（代码索引）
  `/reg_states`（逐端点 ok/errcode/reason）`/reg_dropped`（畸形行计数，review m4）
  `/reg_archived_at`。降级不覆盖旧档；空载荷=降级不是成功。空代码行保留+`no_code`
  标记（不静默丢，不进 by_code 索引）。
- 读口：`load_regulatory_corpus(db, date)`（archiver 内，同 load_* 模式）+
  `GET /api/kpl/regulatory?date=`（kpl_proxy_routes，:8000 直读日档）。
- 手动 CLI：`python -m backend.operations.kpl_regulatory_collect --date YYYY-MM-DD [--dry-run]`
  （同一 archive 写路径；`--date` 格式+历法校验先于发弹（review m1）；dry-run 只打印不写库但同样计数）。
- status 观测（review m3 按实现修订）：archiver status 顶层 `regulatoryEnabled/regulatorySlot/
  regulatoryBudget` + `lastResult.regulatory`（ok/reason/note/date）；逐端点 states 与
  budget 计数经读口载荷 / `kpl_api_calls` 观测。

## 4. 叙事合同（P2，题面 hash 零改动，纯语料供给换代）

- `theme_leader_ammo.regulatory_risk_line(entries)` 纯函数：entries=[{label, hit}]，
  hit=reg_by_code 索引项。行文只放数据事实，例：
  `监管风险：主板龙一 天普股份605255 重点监控(2026-11-13~2026-11-26)；严重异动26-11-16 停牌 预计复牌11-19；大东方600327 今日涨停即触发严重异动(触发涨幅7.80% 10日100% 偏离空间17.83%)`
  - 监控段：`重点监控(开始~结束)`；历史监管同段加「历史」前缀；
  - 近期严重异动段：日期+状态（停牌/预计复牌/触发严重异动）+重点监控标签；
  - 今日/明日触发段：`今日/明日涨停即触发严重异动(触发涨幅X 空间Y)`——上游字符串原样，条件事实不伪装既成；
  - 逐字段非空才出段；全部缺→整行 None（§1.2-8）；lane 降级→None + 结构化留痕。
- 行序：个股叙事紧跟 `risk_line` 后（`abnormal_price_line` 前）；板块叙事同位（双龙一+板内成员 scope，
  同 lhb 行 `_lhb_codes_roles` 口径）；竞价两叙事追加于 `notice_count_line` 后。
- scope：个股=待判龙一+boardCodes 相关个股；板块=双龙一+boardCodes。
- 结构化留痕：label doc 增 `regulatoryState` {laneOk, reason, hitCodes}（审计/前端用，不进叙事）。
- 取数单一源：`theme_leader_label.fetch_regulatory_corpus`（auction 链复用，禁第二套）。
- 版本：`AMMO_VERSION_THEME_LEADER` → `2026-11-15a`；`AMMO_VERSION_AUCTION_LEADER` → `2026-11-15a`。
- 卫生：新行过 `tests/hotlist/test_narrative_hygiene.py` FORBIDDEN 黑名单 + 缺席纪律用例。

## 5. 前端合同（P3）

- relay_page 侧栏「KPL 行情」组新增 `kplreg`「监管风险」页：日期选择（默认最新日档）+ 刷新 +
  五分组表（监管期/历史监管/近期严重异动/今日触发/明日触发），列=代码/名称/标签/上游字符串列；
  降级横幅 fail-visible（未采集/部分端点失败逐组标注）。
- 个股行情六模式池行 badge 增「监」「异」「停」（同源 reg_by_code，进页懒取一次，失败不阻断池渲染）。
- 叙事原文渲染自动带新行（relay 叙事卡原样展示）。

## 6. 测试合同（全 mock，红线 7）

- `backend/services/__tests__/test_kpl_regulatory_risk.py`：解析器 fixture（列映射/缺位 None/
  空列表真零/短行 partial/raw 留档）、fetch 逐端点隔离、pytest 护栏。
- `test_kpl_daban_archiver.py` 增：regulatory lane 部分失败仍落库且不连带它 lane、降级不覆盖、
  日槽门控（17:00 前不采/每日一次/非交易日 skip；16:59 边界用例）。
- `tests/hotlist/test_narrative_hygiene.py` 增：新行黑名单零命中 + 缺数据整行缺席。
- `tests/operations/test_theme_leader_label.py` / `test_auction_leader_label.py` 增：mock corpus →
  叙事含监管行；lane 缺失→行缺席且 regulatoryState 留痕。
- 验收：`cd quant-board && .\.venv\Scripts\python.exe -m pytest`（全量）+ 前端人工验收（relay 新页）。

## 7. 文档同步（§1.2-5）

- 本文 §2 探针定档回填；`docs/kpl-socket/stock-detail-sources-20261108.md` §二表增 5 端点行；
- `docs/kpl-socket/README.md` 索引提及（如需要）；前端展示与叙事同批上线。

## 8. 实施记录（2026-11-15 同日落地）

- P1：`services/kpl_regulatory_risk.py`（fetch/parse）+ archiver `regulatory` lane
  （17:00 日槽/预算/隔离/幂等）+ `operations/kpl_regulatory_collect.py` CLI +
  `GET /api/kpl/regulatory` 读口。探针后修正：触发标志位=[15]（非 [14]）。
- P2：`theme_leader_ammo.regulatory_risk_line` + 两叙事 builder 行序（risk_line 后）；
  `theme_leader_label`/`auction_leader_label` 接线（fetch 单一源复用）+ `regulatoryState`
  落库白名单；AMMO 双戳 → 2026-11-15a（题面 hash 不动）。
- P3：relay_page 新页 `kplreg`（五组表+日期+降级横幅）+ 个股行情四渲染器池行
  badge（监/停/异/触，仅池生效日有档才渲染，不跨日归因）。
- 测试：新增 `test_kpl_regulatory_risk.py`（12 用例）+ archiver lane 5 用例 +
  hygiene 监管行回归 + theme/auction 接线 4 用例；子集 234 过；**全量 5230 过 / 1 失败**
  （`tests/research/test_dual_strength_syna_harness.py::test_analyze_window_fail_visible_on_empty`，
  数据依赖型既有环境失败：期望空窗但本地测试库有帧；research 模块本轮零改动）。
- 待用户验收：重启 :8000 后读口/新页生效（本轮不重启用户服务）；下一交易日 17:00
  槽自动首采，或 CLI `python -m backend.operations.kpl_regulatory_collect` 手动补采。
- 2026-11-15 用户裁决：槽改 17:00；同日 CLI 手动补 2026-11-13 档（5 发，日预算内）。