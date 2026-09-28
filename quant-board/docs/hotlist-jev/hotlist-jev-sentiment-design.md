# Jev 当日热榜情绪观察轨道 — 设计文档

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

- choice/score 的确切 schema 以阶段 0 探测为准（已知 choice.criteria 为 `{label: 说明}` 对象；score 的 min/max 表达待探）。
- 响应格式（截图样本）：`{model, answers: {<key>: {type, choice|noul|score, confidence?, probabilities?}}}`；落库存原始响应。

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
| 0 可行性 | REST 终验 + Worker 桥部署 + 假 state 实测 | Go/No-Go：免费计划能否跑通（无 Free-plan 拦截、无绑卡）、中文 instructions 有效、延迟/单次消耗实测 | **进行中** |
| 1 回放验证 | 历史快照锚定帧重建 state 回放近 20-40 交易日；jev 档位 vs 规则档位 vs 次日晋级率/溢价 | 对比报告（信息增量结论），数据说话 | 待阶段 0 Go |
| 2 盘中旁观 | 调度上线（默认关→用户开），只落库打标，与现有链路隔离 | 连续 5 交易日轨道数据 + degraded 率 < 阈值 | 待阶段 1 过 |
| 3 用户裁决 | 是否作辅助特征，一次一候选走研究纪律 | — | 未启动 |

## 10. 已知技术事实（2026-09-28 实测）

- jev 绕过免费计划门禁：REST chat/completions 直调时错误来自模型执行层（schema 校验），非 "not available on Free plan"。
- REST 死锁：OpenAI 兼容网关强制要求 `messages`，模型强制拒绝 `messages`/`stream`/`max_tokens`（只认 `state`+`questions`）；`/ai/run/typesafe/jev` 返回 7000 无路由。唯一官方调用方式=Worker 绑定 `env.AI.run`（模型页明示"绑定不需要 API 令牌"）。
- choice.criteria 是 `{label: description}` 对象非数组；state 支持 string|object|any[]|null。
- 模型版本样例响应 `model: "jev-1.13.0"`，provider model `jev-latest`。

## 11. 未决问题

- score 类型问题的 min/max 语义（阶段 0 探测）。
- 用户 API 令牌当前仅 Workers AI:Edit，部署 Worker 需 Workers Scripts:Edit——阶段 0 由用户补权限或手动部署（代码由 AI 提供）。
- workers.dev 子域名是否在帐户上启用（部署时确认）。
- 中文 instructions 的评估质量（阶段 0 用双语对照验证）。
