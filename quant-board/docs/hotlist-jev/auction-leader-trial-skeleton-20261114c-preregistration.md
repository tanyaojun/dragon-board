# 竞价试盘源接入 骨架预登记（2026-11-14c）

> 性质：**原料层增量2 骨架**——试盘行渲染器注册 + `corpusState.trialState` 留痕合同 +
> 探针脚本升级（2→3 发分段预算）。**直连合同未定案，采集链不接线**：
> `build_one(trial=None)` 恒 `trialState=contract_pending`、叙事无试盘行，
> narrative 实际输出与 2026-11-14b 完全一致（题面 hash 不动）。
> 前置勘察：`auction-trial-source-survey-20261114.md`（源定位 + 天普原始行 + 语义警示）。

## 1. 本轮落地

| 项 | 内容 | 文件 |
|---|---|---|
| 渲染器 | `auction_trial_line(trial)`：纯数据事实行，缺位字段不出现、零值不投喂、全缺整行缺席；叙事插入位 = push（09:15 试盘价）→ **试盘** → bid（09:25 匹配价）→ 结构（时间序） | `auction_leader_ammo.py` |
| 时点纪律 | `jj_percent/jj_amount/jj_turnover` 是 end_time 时点快照：start/end 任一缺 → 三列整组不出（时点不可锚=事实不可出）；end≥09:25 标「竞价全程匹配」，早于标「{end} 时点」 | 同上（docstring 冻结） |
| 语义护栏 | first/first_add/max/last_amount 待窗内与 App 同屏核对，只出 App 原名数值不解释含义；`pre_percent` 不进叙事（结构行已覆盖昨日事实） | 同上 |
| 留痕合同 | `corpusState.trialState = {"state":"contract_pending"}`（骨架期）/ `{"state":"ok","source","fetchedAt","prevPercentCross"}`（定案后）；与 bid 六件套的交叉校准只进 `prevPercentCross`/后续 `bidCrossCheck` 结构化字段，不进叙事 | `auction_leader_label.py` |
| 版本 | `AMMO_VERSION_AUCTION_LEADER = 2026-11-14c`（schema 增量 + 渲染器注册；语料零变化，题面 hash 不动） | `auction_leader_ammo.py` |

## 2. 探针预算（红线 9，单日分段门控 + 当日幂等门）

> **2026-11-14 晚更新：KPL 直连探针 A/B/C 取消**——WzsLinker 前端合同逆向已全部定案
> （勘察 §6）：历史回看实锤（dates[] 全交易日，11-12/88 行已落盘）、rank 数值原值、
> 页面 60s 轮询证明盘中自更新。接入改走 WzsLinker（题材语料同族基建，零新增 KPL
> 暴露）；周一仅需 WzsLinker 缓存龄验证 ≤2 发。本脚本保留作为未来 KPL 直连
> 降级备选的定案工具，不再按原计划发射。

`scripts/auction_trial_contract_probe.py`，dry 默认零外呼；`--confirm-budget` 实弹：

| 候选 | 时段 | 端点 | 目标 | 预算 |
|---|---|---|---|---|
| A 窗内实时 | 09:15–09:25 | apphwhq `DaBanList&Type=7` (w48) | 有无数据、行格式（数组位 vs cell） | 1 发/日 |
| B 窗尾留存 | 09:26–09:30 | 同 A | 竞价结束后行是否留存（生产采集可否压窗尾拿定格快照） | 1 发/日 |
| C 历史回看 | 与 B 同次 | apphis `HisDaBanList&Type=7&PidType=8&Day` (w30) | 历史 Day 是否生效（历史原料可否盘后补拉） | 1 发/日 |

- 时段外/周末一律拒绝实弹（11-14 周六两发空证明窗外空列表不可判读）；dump 已存在即幂等拒绝；
- 空结果/参数错结构化记录后停止，禁止追加候选；定案优先路径仍是 MITM 对照。

## 3. 接线清单（2026-11-14 晚已实施，Monday=生产日）

1. ✅ 采集器 `backend/operations/auction_trial_fetch.py`：裸读 1 发 → saved_at 龄
   >120s 才补 1 发 refresh=1（≤2 发封顶，无重试）；actual_date 守卫（回退数据
   不得冒充当日）；解析层 rank 单位定案（金额=元、比例 ×100、时间=串）。
2. ✅ run() 接线：仅 [09:25,09:30) 窗（试盘行已定格，与 bid 补源同窗）、dry-run
   零外呼；入选股命中 → 叙事试盘行 + trialState=ok+采集观测；未命中/窗外/失败 →
   no_row / skipped_out_of_window / fetch_failed 留痕，整行缺席不伪造。
3. ✅ 试盘行金额渲染：亿/万双门槛（≥1亿才用亿），避免共享 formatter 100万门槛
   的 X.XX亿 非零显零误导；「961万」上游串原样透传。
4. ⬜ `corpusState.bidCrossCheck`：jj_amount/jj_turnover vs bid 通道零值交叉（P2 盲区）。
5. ✅ 离线回放验收：11-13 真实缓存 trimmed fixture（tests/operations/fixtures/）
   全链回放（解析/守卫/条件 refresh/runner 接线），HTTP 全 mock 零外呼。

**周一 11-16 无实验、直接生产**：晨间 run 自带新鲜度自证（saved_at/fetched/attempts
落 trialState），缓存龄不再是前置实验而是生产质量字段；若窗内发现代理缓存陈旧，
refresh=1 兜底已内置。盘后用实跑 doc 的 trialState 复盘缓存龄实况。

## 4. vA3 题目层候选条款（试盘维度，原料先行、换代预登记后生效）

- **假试盘→真封 vs 硬一字**：试盘涨幅（end_time 时点）+ 首开/首加额 vs 09:25 匹配涨幅
  背离 → 封板题一字板分支的原料（P2/Q1 配套）；
- **可撤窗撤单时点**：end_time < 09:20（可撤窗内结束试盘）→ 试盘单撤出 vs 真实委托；
- **首开→最终额增减**：试盘资金持续性事实；
- 以上均以「叙事行已供给该证据」为前提（判据引用与供给对齐纪律），试盘行缺席时
  对应题目判据自动降级，不得要求叙事不存在的证据。

## 5. 验收（2026-11-14 实测）

- 新增 `tests/hotlist/test_auction_trial_line.py`（8 例：天普样本逐字、时点组抑制、
  竞价全程匹配标注、数值格式化、零值/缺席、pre_percent 不进叙事、行序、缺席整行）全绿；
- `test_auction_leader_label` 41 绿（新增 trialState contract_pending/接线用例）；
- version stamps / narrative hygiene 全绿（试盘行进卫生黑名单回归，未触发词条）；
- 探针 dry 模式验证时段选择与预算 JSON。已知 HEAD 既有失败（与本增量无关）：
  relay_page 4 例（`evidenceBoardResolved` JS 内容断言，见 20261114b 预登记 §4）。
## 附记（2026-11-14 深夜用户裁决追加）：raw 全量日档落库

- 骨架期 raw 全量 rows（~百只/日 × 15 列）仅内存选行后丢弃，撞 §4.0「采集链路必须
  保存原始记录」——已补：`persist_trial_raw`（`auction_trial_fetch.py`）单集合日档
  `auction_trial_raw`（_id=日期），仅 state=ok 落（actual_date 守卫后；空 rows +
  ok = 「当日全市场无试盘」事实照写 nRows=0；fallback/api_error/http_error 不落，
  留痕仍在 label doc trialState，不覆盖好档）；runner 窗内接线，`persistState` 进
  `corpusState.trialState`（fail-visible）。
- 历史回填：`scripts/backfill_auction_trial_raw.py`（单发/日、无 refresh——历史档案
  不可变、陈旧补拉逻辑不适用；2s 间隔、断点续跑、--confirm-budget 门）。60 交易日
  窗口（2026-08-14..11-13）实弹 60/60 全落零失败，5520 行原始记录入库自持。
- 预算台账更新见勘察文档 §6.4（+60 发缓存读）。
