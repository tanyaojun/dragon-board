# Jev 热榜情绪双问题观察轨道 — 设计文档（方向重置版）

- 日期：2026-10-08
- 状态：设计已确认（2026-10-08 用户方向重置 + 四点拍板），待实施
- 取代：本目录 2026-09-28 轨道的「golden 对照验证」路线；历史阶段文档（design/phase1-3 报告）降级为档案，其结论不再约束本设计
- 关联：`docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md`（规则轨道 rawStage/stage 双轨合同，与 jev 轨道并列、互不写入）

---

## 1. 方向重置（为什么推翻重来）

2026-10-08 用户裁决：**之前的路线犯了循环论证错误**——把规则情绪五档（golden）当作「正确答案」评判 jev 回答的对错。而情绪周期从未进入回测链路，规则算法和因子本身未经验证，golden 不是 ground truth。因此：

- 阶段 1 的 REJECT 判定（混淆矩阵、45% 一致率、92% 错位）**方法论作废**；其保留的工程教训只有两条且与本方向无关地成立：数值 state 无归纳力（→ 必须叙事化）、`/ai/run` 通道事实（直调、≈$0.0001/次、1.1s、余额 ≈$9.97）。
- jev 与规则轨道是**两个并列的观察者**，无预设权威。谁的判定更符合盘面实际情况，就采用谁——**裁决方式 = 用户在前端热榜情绪面板上盘中对照论证**，不设自动评判体系、不做回测。
- 2026-09-28 当日已按用户指令清理的代码/数据不复活；2026-10-08 上午一版实施（叙事携带规则轨迹 + ruleStage 对照）已整体回退，git 工作区已核对干净。

## 2. 用户四点拍板（2026-10-08）

| # | 决策 |
|---|---|
| D1 | 序列粒度 = half_hour 10 槽（09:30–15:00） |
| D2 | 裁决方式 = **前端热榜情绪面板直接展现 jev 结论**，供用户盘中分析论证；不做人工抽样标注体系、不做语义一致性自动校验 |
| D3 | 不做长历史回放（不是回测），只分析**最近三个交易日**的结果，保证上线即有可看数据 |
| D4 | 旧方案整体回退重写，之前的假设和分析全部作废 |

## 3. jev 回答的两个问题（每槽一次调用，四问）

| # | key | 问题 | 输入 | 类型 |
|---|---|---|---|---|
| Q1 | `frame_stage` | 仅凭**当前帧**证据，当前情绪处于五档哪一档？ | 当帧证据叙事（不含前序帧、不含任何规则算法输出） | choice 五档 |
| Q2 | `sequence_stage` | 结合**当日已落库连续帧**证据序列（含当前帧），当前情绪处于哪一档？ | 当日早于本槽各帧的压缩证据行 + 当帧证据叙事 | choice 五档 |

附两个描述性 score：`temperature`（短线情绪温度 0-100）、`crowding`（高位拥挤度 0-100）。

**盘后日级固定**（daily 15:30 快照触发，四问）：`day_stage`（今日总体情绪五档）、`day_pattern`（路径形态七类）、`day_temperature`、`day_crowding`。

**零预测性问题**：全部问题为描述性，无任何 noul 前瞻问；questionsRaw 落库可审计。

五档 criteria（边际方向语义，沿用阶段 0 已验证表述）：
`ice` 冰点：赚钱效应殆尽，涨停稀少跌停增多，普遍观望 / `start` 启动：从弱势基线开始修复，试错资金进场，局部热点出现 / `ferment` 发酵：赚钱效应扩散，涨停与连板增多，热点扩散 / `climax` 高潮：全面亢奋，涨停潮普涨，拥挤明显 / `retreat` 退潮：从强势转弱，高位股集体走弱，炸板增多。

`day_pattern` 七类：`steady_strong` 全天强势主导（多数时段发酵/高潮）、`steady_weak` 全天弱势主导（多数时段退潮/冰点）、`rally_fade` 冲高回落、`low_recover` 低开修复、`wide_swing` 强弱多次交替、`narrow_range` 窄幅平淡、`unclear` 证据不足无法归纳。

## 4. 证据原料（全部已落库核实，全部为原始证据/计数聚合，零规则五档输出）

| 层 | 字段/来源 |
|---|---|
| 帧级 | `snapshot_frames.limitSummary`：continuousBoards（一/二/三/四连以上分桶 + maxBoard）、zhaban（count/rate/fengbanRate/ztCount）；`indices`（sh/hs300/zz500/zz1000 change） |
| 行级 | `snapshot_stock_rows`：pctChange（涨跌家数分布）、`zlje`/`zljzb`（东财主力净额/净占比，随半小时帧持久化）、rank/heat、reason（THS 涨停原因）、price/limitUpPrice（涨停判定） |
| 跨日 | 昨日涨停今日表现：`build_yesterday_hot_limit_evidence`（analysis/hotlist/sentiment.py 纯函数，输入仅今昨原始行）→ count/avgChange/positiveRate/weakeningRate/failedOrWeakRate；新进/淘汰（今昨 codes 对比） |
| 生命周期 | `snapshot_analysis.displayStatus.stage`（ignition/expansion/crowded/reversal/cooling/unknown）逐槽分布与槽间计数迁移（join 与规则链同源同口径） |
| 焦点个股 | 热度 top ≤8：名称/题材/涨幅/涨停/生命周期态 |

补充事实：displayStatus join 由采集后处理链同步保证命中（analyze 先落库）；主力资金历史仅有快照点位值（半小时粒度），无 tick 历史——对情绪判定够用。

## 5. State / 叙事设计（state = 纯叙事字符串）

- **槽位 state**（≤4,000 字符）：头部（日期/槽位）→【当前帧证据】（市场层/热榜结构/主力资金/昨日涨停承接/生命周期/焦点个股，全量明细）→【当日已走帧证据】（早于本槽各帧逐行压缩：时间｜指数｜涨停·炸板·最高板｜涨跌家数｜主力净额合计与家数｜新进淘汰｜生命周期计数｜昨涨停承接）→【数据质量】（缺失如实列出）。
- **日级 state**（≤6,000 字符）：头部 → 逐帧压缩证据行（同上格式，含 15:00）→【当日累计】（全日新进/淘汰、主力净额合计、最高连板演变）→【数据质量】。
- 缺字段保持缺失、如实叙述；禁止 0 值伪装（fail-visible 红线）。**输入零规则输出**：不读 `hotlist_sentiment`，不携带规则 stage/summary/signals（防锚定、防循环论证）。

## 6. 落库合同（collection `hotlist_jev_sentiment`，此前已 drop，本次新建）

**槽位文档** `_id={datasetId}:half_hour:{tradingDate}:{slotTime}`：
`kind="slot"`、`origin`（collector/manual/replay）、`asOf`、`evidenceRaw`（当帧聚合证据，结构化）、`narrativeRaw`、`questionsRaw`、`responseRaw`、`answers`（frame_stage/sequence_stage 概率分布）、`scores`（temperature/crowding 0-100 还原）、`usage`/`latencyMs`/`model`、`status`（ok/degraded/no_data）、`errorCode`/`errorDetail`、`quality.degradedSources`、`computedAt`。

**eod 文档** `_id={datasetId}:half_hour:{tradingDate}:eod`：`kind="eod"`、`anchoredSlotTime`（当日最新已采槽）、answers 含 day_stage/day_pattern、其余同上。

幂等 `replace_one(upsert=True)`；**不写任何规则档位字段**，两轨对照只发生在前端并列展示与事后分析层。

## 7. 架构与数据流

```
8001 collector 半小时帧落库
  └─ _run_post_persist_chain 第 4 步（gate=JEV_SENTIMENT_ENABLED 默认关；fail-visible 不阻断）
      └─ snapshot_type == half_hour → 槽位评判（Q1+Q2 四问）→ 槽位文档
daily 15:30 快照落库 → 日级评判（四问）→ eod 文档（盘后固定）
8000：POST /api/hotlist-jev/evaluate（手动，不受 gate 限制）+ GET /api/hotlist-jev/series（读口）
operations/jev_sentiment_replay.py：最近 3 个交易日回放（D3，≈$0.003）
前端 DragonBreath 热榜情绪面板：规则轨道（现有）+ jev 轨道并列展示
```

- 前序帧证据**每次从快照库直算**（frames + rows + analysis join），不依赖 jev 自己的历史文档——回放/乱序/补写天然幂等，无因果截断问题（只取 slotTime < 当前槽）。
- deduped 采集不触发链（沿用现有语义）；force 重采幂等覆盖。

## 8. Fail-visible 边界

- 证据部分缺失：叙事如实记缺失项，`quality.degradedSources` 落库，jev 照跑。
- 当帧帧/行全缺（槽位）或当日无任何帧（日级）：落 `status=no_data` 文档，显式不静默。
- jev 调用失败/超时（30s）/非 Completed/402/缺 token：落 `status=degraded` + errorCode/errorDetail + 原始响应，绝不伪造档位/0 分。
- 采集链隔离：jev 步骤异常只进 run doc warnings；gate 关闭跳过不告警（与 analysis 开关同语义）。
- 规则轨道一行代码不动：`sentiment.py` / `stage_confirm.py` / `hotlist_sentiment` 合同零漂移。

## 9. 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `JEV_SENTIMENT_ENABLED` | `false` | 采集链自动触发门控 |
| `JEV_CF_TOKEN` | — | Cloudflare token（不入仓；本机 shell 可从 `~/.pi/agent/models.json` providers.cloudflare.apiKey 取） |
| `JEV_CF_ACCOUNT` | `921cf15176f84c90ea49865334af32c6` | 账户 ID |

成本：10 槽 + 1 日级 = 11 次/日 ≈ $0.001/日。

## 10. 前端展现（DragonBreath 热榜情绪面板）

1. **顶部情绪卡**：现有规则确认阶段旁并列 jev 判定——`frame_stage`（Q1，标「当前帧」）与 `sequence_stage`（Q2，标「日内序列」），两者不同时分别标注；温度/拥挤分数随卡显示；
2. **日内轨迹**：现有确认阶段轨迹 + jev 槽位判定轨迹（第二标记层），分歧槽位肉眼可辨；
3. **日级总体**：eod 存在时展示 day_stage/day_pattern/日级温度/拥挤；
4. degraded/no_data 如实标注含原因，绝不显示伪值；旧文档/无数据正常渲染。
5. 展示是**观察面**：不进信号、不进交易路径、不回写规则轨道；是否采用由用户盘中论证后另行裁决。

## 11. 阶段划分与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| A | 证据聚合器 + questions 常量 + 叙事构建器（纯函数 TDD） | 叙事含全部原料层；缺源降级不伪造；questions 常量无 noul（测试冻结） |
| B | 编排服务 + 采集链挂接 + evaluate API（TDD） | ok/degraded/no_data 三态合同；幂等 upsert；gate 分支；异常仅 warning |
| C | series 读 API + 最近 3 交易日回放 runner | 3 天槽位 + eod 文档齐全；degraded 率与成本报告 |
| D | 前端类型/API 客户端/面板双轨展示（TDD + vue-tsc + Playwright 真实浏览器验收） | 桌面+移动视口双轨并列可见、分歧可辨、无伪值、控制台无新增错误 |
| E | gate 开启试运行一个交易日 + 文档同步 | 全链自动产出 10 槽 + eod；面板盘中可用；单一事实源登记（并列观察者措辞）+ architecture/api-cli/AI_COLLABORATION 同步 + 旧 design 文档加取代注记 |

## 12. 文件清单

| 文件 | 职责 |
|---|---|
| `backend/analysis/hotlist/jev_state.py` | `collect_slot_evidence()` 聚合器、`build_slot_jev_state()` / `build_day_jev_state()` 叙事、questions 常量（driver 叙事保留） |
| `backend/services/jev/jev_sentiment_compute.py` | 编排：快照取数 → 聚合 → 叙事 → `call_jev` → 解析 → upsert；gate/token；`run_jev_post_persist()` 链分派 |
| `backend/snapshot_collector/service.py` | `_run_post_persist_chain` 第 4 步挂接 |
| `backend/api/hotlist_jev_routes.py` | evaluate + series 路由，注册 main.py |
| `backend/operations/jev_sentiment_replay.py` | 最近 3 交易日回放 CLI |
| `src/types/hotlistJev.ts`、`src/services/hotlist/hotlistJevApi.ts`、`src/components/panels/DragonBreathPanel.vue` | 前端类型/客户端/双轨展示 |
| `tests/hotlist/*`、`tests/snapshot_collector/test_snapshot_collector_post_persist.py`、面板组件测试 | 全链测试 |
