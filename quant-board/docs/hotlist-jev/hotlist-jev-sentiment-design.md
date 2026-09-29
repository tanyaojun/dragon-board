# Jev 当日热榜情绪观察轨道 — 设计文档

> **状态更新（2026-10-08）**：本档的阶段 1 REJECT 判定方法论已作废——它以规则档位（golden）为
> "正确答案"评判 jev，属循环论证（情绪周期未进回测链路，规则算法与因子未经验证）。jev 与规则
> 改为**并列观察者**，新方向见 `hotlist-jev-emotion-observe-design.md`（双问题观察轨道，已实施）。
> 本档保留为 2026-09-28 阶段 0-3 的历史档案；其中仍有效的工程事实：/ai/run 通道、数值 state 无
> 归纳力（叙事化必要）、通道成本。

- 日期：2026-09-28
- 状态：设计已确认（D1/D2/D3 三决策点用户拍板），阶段 0 进行中
- 决策记录：D1=档位 criteria 用英文枚举+中文说明、落库存双语；D2=盘中每 half_hour 槽位 +3 分钟触发（10 次/日）+ 15:05 复盘 1 次 + 手动 API；D3=state 不携带上一槽规则档位，jev 为纯独立观察者。

## 1. 背景与目标

用 Cloudflare 统一模型目录的 `typesafe/jev`（结构化评估模型，Noul/Choice/Score 三原语，零数据保留，输入 $0.042/百万 token）对**当日热榜情绪**做独立于现有规则链路的概率化评估。核心动机：

- 现有规则情绪桶（五档级联）是布尔阈值判定，无概率、无前瞻；jev 提供校准概率（升温/退潮概率、情绪温度、拥挤度），做**平行观察轨道**。
- 不依赖快照槽位数据：直接消费后端进程内已有的**实时**入口（六平台热榜 600s 轮询、THS 涨停/炸板/大面池 30s TTL、akshare 指数 10s TTL），快照仅用于阶段 1 历史回放。
- 成本可忽略：state 约 4K token × 11 次/日 ≈ 5 万 token/日 ≈ $0.002/日。

## 2. 非目标

- 不修改 `analysis/hotlist/sentiment.py` 任何一行（golden 锁定）；现有六页签情绪看板口径不变。
- 第一版不做前端改动；jev 结果不进信号、不进交易路径、不参与规则判定。
- 不做自动改默认值；是否升级为辅助特征由用户在阶段 3 数据裁决。

## 3. 口径基线（现有事实，勿改）

| 项 | 口径 | 位置 |
|---|---|---|
| 市场情绪五档 | `ice/start/ferment/climax/retreat`（冰点/启动/发酵/高潮/退潮），级联顺序 retreat→climax→ferment→start→ice 兜底 | `quant-board/backend/analysis/hotlist/sentiment.py:1098-1188`；前端 `src/types/emotion.ts:13` |
| 个股生命周期五态 | `ignition/expansion/crowded/reversal/cooling`（点火/扩散/拥挤/反转/冷却）+ `unknown`（无阶段，缺失不设门） | `quant-board/backend/analysis/ranktrend/trend/display_status.py:29-40` |
| 实时热榜 | `GET /api/{platform}/hot`，行字段 code/name/rank/price/pctChange/volume/amount/turnover/heat，600s 轮询 | `backend/api/market_data_routes.py:129`、`backend/market_proxy/hotlists.py` |
| 涨停池 | THS dataapi 涨停/炸板/大面池 + 板数高度层，30s TTL | `backend/market_proxy/limitup.py` |
| 指数 | akshare-sina，10s TTL | `backend/market_proxy/indices.py` |
| 快照槽位 | half_hour 10 槽 09:30–15:00；anchoredSlotTime 锚定帧 | `backend/snapshot_collector/slots.py:24-62` |
| 外部 HTTP 惯例 | httpx.AsyncClient 单例 + 进程/Redis TTL 缓存 + `{"ok":false,"degraded":true,"errorCode":...}` 打标 | `backend/api/market_data_routes.py:166-178` 模式 |
| Mongo 落库惯例 | repository_factory 取运行时 db；service 封装 `replace_one(upsert=True)` | `backend/services/theme/hotlist_sentiment_service.py:21-43` 模式 |

## 4. 架构

```
[8000 后端进程内实时数据] hotlists / limitup pools / indices
   │  新模块 analysis/hotlist/jev_state.py：压缩为 state（≤5K token）
   ▼
[CF Worker 桥 jev-bridge]（quant-board/workers/jev-bridge/，约 30 行）
   │  POST /evaluate {payload} → env.AI.run('typesafe/jev', payload)
   │  x-bridge-token 共享 secret 鉴权 + 简单限频；REST 直调已证死锁（见 §10）
   ▼
[jev 轨道（后端）] services/jev/jev_client.py：httpx 调桥，degraded 打标
   调度：盘中每槽 +3min（错开快照采集）+ 15:05 复盘 + POST /api/hotlist-jev/evaluate 手动
   落库：Mongo collection hotlist_jev_sentiment（replace_one upsert，_id={datasetId}:{snapshotType}:{tradingDate}:{slotKey}）
```

### 单一事实源三问（门禁，必答）

1. **新增还是消除双源**：新增一条双源（规则档 vs jev 档），须登记进 `docs/single-source-of-truth-architecture.md` 盘点表。
2. **权威侧**：情绪档位权威=规则情绪桶（golden）；jev 轨道自声明为独立观察者/研究面，只落库、只展示、不回写。
3. **前端零改动是否原理性不可达**：第一期前端零改动成立（纯后端落库）；后续前端只加消费 API 读取，不自算，无独立演化风险。

## 5. State 设计（≤5K token，四层）

```jsonc
{
  "asOf": "2026-09-28T10:33+08:00", "slot": "1030+3",
  "market": {
    "indices": {"sh": 0.8, "cyb": 1.2},            // 实时指数 pct
    "zt": 68, "dt": 5, "zhabanRate": 0.15,          // 涨停/跌停/炸板率
    "promotionRate": 0.62, "upRatio": 0.71          // 晋级率/涨跌比
  },
  "lifecycle": {
    "counts": {"ignition": 18, "expansion": 9, "crowded": 4, "reversal": 3, "cooling": 2, "unknown": 1},
    "migration": {"new": 5, "dropped": 3, "up": 2},  // vs 上一槽（生命周期迁移，非档位锚定）
    "stagePct": {"crowded": [3.1, -1.2]}             // 各阶段内个股 pct 采样
  },
  "stocks": [   // top 12~18：热度榜∩涨停池优先；8 字段/只
    {"n": "XX股份", "s": "ignition", "pct": 9.98, "spd": 3.2, "zt": true, "lb": 2, "heat": 95, "th": "算力"}
  ],
  "hotlist": {"platforms": 6, "entries": 143, "newEntries": 22},
  "quality": {"dataAge": "2min", "degraded": []}     // 数据新鲜度/降级如实随行
}
```

- 生命周期枚举直接用英文值（D1 同源）；**不带上一槽规则档位**（D3，防锚定污染）。
- 个股行来源：最新实时热榜（多平台合并现有口径）∩ 涨停池，取热度 top；生命周期态优先取快照锚定帧最新 stage，实时行无 stage 时如实 `unknown`，不伪造。

## 6. Questions 设计（第一期五问）

| type | key | 内容 | 期望输出 |
|---|---|---|---|
| choice | `stage` | criteria: ice(冰点)/start(启动)/ferment(发酵)/climax(高潮)/retreat(退潮) + 中文说明 | 五档概率分布 |
| noul | `heating_30m` | 未来 30 分钟情绪升温概率 | 概率 |
| noul | `retreat_eod` | 收盘前明显退潮（炸板潮/高位批量开板）概率 | 概率 |
| score | `temperature` | 短线情绪温度 0-100 | 分数 |
| score | `crowding` | 高位拥挤度 0-100 | 分数 |

- choice/score schema **已定案（2026-09-28 实测）**：choice.criteria=`{label: 说明}` 对象；score.criteria=**字符串锚点数组（≤10 档）**，返回 score=锚点下标的概率加权期望 + legend + 全档位概率分布（温度/拥挤度用 10 档 0-100 锚点，后端按 idx/9×100 还原，天然拿到校准直方图）；score 档位超 10 报 `Too many score levels`。
- 响应包络：`{result:{state:"Completed", result:{model:"jev-1.13.0", answers:{<key>:{type, choice|noul|score, probabilities?, confidence?, legend?}}, usage:{input_tokens,output_tokens}}}, gatewayMetadata:{keySource:"Unified"}}`；落库存原始响应。

## 7. 落库与 API

- Collection `hotlist_jev_sentiment`，文档：`_id="{datasetId}:{snapshotType}:{tradingDate}:{slotKey}"`、slotKey（"1030+3"/"eod"）、asOf、stateRaw（全量）、questionsRaw、responseRaw、latencyMs、usage、status（ok/degraded）、errorCode/errorDetail、datasetId/snapshotType/tradingDate 全套审计字段。
- API（阶段 2）：`POST /api/hotlist-jev/evaluate`（手动触发）、`GET /api/hotlist-jev/series?date=`（读口，Redis TTL 60s + 依赖失效）。前端消费后置。

## 8. Fail-visible 行为（红线）

- Worker 超时 / HTTP 非 2xx / 响应缺 answers / confidence 异常 → 落库 `status=degraded` + 结构化 errorCode + 原始错误文本，**绝不伪造中性档/0 分/空结果**。
- 实时数据部分缺失（如某平台热榜挂）→ state 照常构建，`quality.degraded` 列出缺失源，jev 照跑。
- 全源无实时数据（非交易时段/全挂）→ 本轮 `status=no_data` 明确落库，不静默跳过。
- 现有情绪链路对 jev 零依赖；桥挂掉对系统无感（降级打标）。
- 开关默认关：`JEV_SENTIMENT_ENABLED=false`（沿用门控默认关惯例），用户显式开启。

## 9. 分阶段与验收

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| 0 可行性 | REST 终验 + Worker 桥部署 + 假 state 实测 | Go/No-Go：免费计划能否跑通（无 Free-plan 拦截、无绑卡）、中文 instructions 有效、延迟/单次消耗实测 | **GO（2026-09-28 终版）：用户充值 $10 统一积分后全项过验；免费前提修正为 ≈$0.0001/次，见 §12** |
| 1 回放验证 | 历史快照锚定帧重建 state 回放近 20-40 交易日；jev 档位 vs 规则档位 vs 次日晋级率/溢价 | 对比报告（信息增量结论），数据说话 | **REJECT（2026-09-28，phase1-replay-report.md）：三版迭代（数值 state→limitEvidence 兜底+叙事层→criteria 口径对齐）后仍无信息增量——jev 从结构化数值归纳市场阶段能力弱，档位系统性错位且无预测价值；机制保留（vote=0），重启候选方向见报告 §4** |
| 2 盘中旁观 | 调度上线（默认关→用户开），只落库打标，与现有链路隔离 | 连续 5 交易日轨道数据 + degraded 率 < 阈值 | 待阶段 1 过 |
| 3 用户裁决 | 是否作辅助特征，一次一候选走研究纪律 | — | 未启动 |

## 10. 已知技术事实（2026-09-28 实测）

- jev 绕过免费计划门禁：REST chat/completions 直调时错误来自模型执行层（schema 校验），非 "not available on Free plan"。
- REST 死锁：OpenAI 兼容网关强制要求 `messages`，模型强制拒绝 `messages`/`stream`/`max_tokens`（只认 `state`+`questions`）；`/ai/run/typesafe/jev` 返回 7000 无路由。唯一官方调用方式=Worker 绑定 `env.AI.run`（模型页明示"绑定不需要 API 令牌"）。
- REST 终验（2026-09-28，阶段 0 Task 1）：A `/ai/v1/responses`=网关不要求 messages 且可透传 state/questions，但网关自动注入 `stream` 字段被模型拒绝（HTTP 400 invalid_prompt）；B chat+`messages:[]`=死锁复现（模型拒 messages 字段本身，与内容无关）；C chat+messages 无 stream=同样拒 messages+stream；D `/ai/run/typesafe/jev`=7000 无路由。**四变体全死，Worker 绑定为唯一通道，已定案。**
- choice.criteria 是 `{label: description}` 对象非数组；state 支持 string|object|any[]|null。
- 模型版本样例响应 `model: "jev-1.13.0"`，provider model `jev-latest`。

## 11. 未决问题（以用户充值决策为前提）

- score 类型问题的 min/max 语义（充值后 Task 4 探测）。
- 中文 instructions 的评估质量（充值后双语对照验证）。
- 统一计费积分最低充值额度（面板查看）。

## 12. 阶段 0 终局结论（2026-09-28）

**判定：对"免费"前提 = NO-GO；技术通道 = 全通（条件 GO）。**

1. **jev 不免费（铁证）**：统一端点 `POST /accounts/{acc}/ai/run`（带不带 `cf-aig-gateway-id` 头均同）+ 正确 payload `{"model":"typesafe/jev","input":{state,questions}}` → HTTP 402 `Insufficient balance; add money to your gateway or use BYOK`（code 2021）。第三方转售模型按 token 积分计费（模型页 $0.042/1M input tokens），**免费计划的 10,000 neurons/天只覆盖 @cf 系模型，jev 零免费额度**。对照实验：同路径 llama（@cf 系）当日免费 neurons 耗尽报 429（code 4006），二元计费结构实锤。
2. **通道已打通（唯一正确姿势）**：统一端点在 `api.cloudflare.com`（CN 网络实测畅通），模型放 body.model、输入包 `input` 字段、网关用 `cf-aig-gateway-id: default` 头路由（帐户已有 default 网关，面板可查日志）。**此姿势下无需 Worker 桥**——§4 架构若用户选择充值推进，则简化为后端直连 `/ai/run`；jev-bridge Worker（已部署 jev-bridge.tanny.workers.dev）保留为备用，但 workers.dev 域名被 GFW SNI 封锁（同 IP 对照实验实锤），本机不可达，仅边缘内部可用。
3. **用户侧澄清**：AI Gateway 免费套案的 "200K events/day" 是日志事件额度（超出仅日志采样），与调用额度无关，对本项目（~11 次/日）完全无影响。
4. **成本估算（若充值推进）**：state ~4K token × 11 次/日 ≈ 5 万 token/日 ≈ **$0.002/日（约 $0.06/月）**，最低充值额（面板显示 $0.00 积分）可用数年。
5. **wrangler 本地 dev 的 remote AI binding 对所有模型报 InferenceUpstreamError（21s 后 internal error）**——与模型无关的 dev 代理层问题，判定与计费门禁在 binding 路径的表现可能相关，未深究（已不影响结论）。
6. **后续**：阶段 1-3 全部以用户"是否充值"决策为门。若充值：先跑 Task 4 探测（score schema/中文判别/延迟实测）再进回放。

## 13. 阶段 0 终版实测（2026-09-28 用户充值 $10 积分后，GO）

- **五问全量一次通过**：object state（市场层+生命周期计数+3 只股票行+热榜+质量）1,121 input token / 124 output token，**五问并发返回 1.11s，单次 ≈$0.0001**（$10 积分 ≈ 十万次，完全免疫成本）。
- **中文判别力**：紧急文本 noul=0.98 / 平静文本 noul=0.02；退潮特征描述 → choice=retreat P=0.82 conf=0.78；混合行情 object state → stage=ferment P=0.65 + 温度直方图（峰值 67-89 档）+ 拥挤度直方图，全部合理。
- **score 定案**：criteria=字符串锚点数组（≤10 档），score=锚点下标期望，附 legend + 全档位概率——后端用 10 档 0-100 锚点，`temperature/100 = score_idx/9`，天然获得校准分布。
- **积分不解锁计划门禁 @cf 模型**：glm-5.3-flash 仍 403 Free plan（文档"credits 解锁付费模型"的说法对 /ai/run 路径不成立）。
- 探测总消耗 <$0.002；当日免费 neurons 已耗尽（429，按天重置）不影响 jev（走积分）。
- 阶段 1 启动条件满足：Task 4 探测完成，schema/端点/成本全部锁定。


## 14. 数据与代码清理注记（2026-09-28，用户指令）

- **已 drop**：hotlist_jev_sentiment（330）、hotlist_jev_stock_labels（660）、hotlist_jev_driver_labels（9,223）——三者均可再生（阶段1 ≈$0.05 / 阶段2 ≈$0.02 / 阶段3 重打 ≈$0.35），判定数字已留档本目录报告；WiredTiger drop 即时释放空间，全库碎片扫描无 compact 候选。
- **已移除代码**：阶段1（jev_replay.py / jev_replay_report.py / build_replay_state 及辅助）、阶段2（jev_label_stocks.py / jev_label_report.py / build_stock_config_narrative）、jev-bridge Worker（仓内代码 + 已部署实例，REST 通道定型后无用）。
- **N15 保留件**：jev_client.py（统一 /ai/run 通道）、build_driver_label_narrative、jev_label_driver.py、jev_label_driver_report.py——扩窗复验（B-202610 N15）直接续跑，标签重建后判定复算。
