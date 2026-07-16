# 同花顺 L2 API 字段分析报告

> 分析日期：2026-07-16
> 测试样本：14 只股票（603127 昭衍新药 / 000938 紫光股份 / 002156 通富微电 / 002185 华天科技 / 600664 哈药股份 / 002384 东山精密 / 002747 埃斯顿 / 603538 美诺华 / 600584 长电科技 / 000977 浪潮信息 / 000063 中兴通讯 / 000725 京东方A / 002261 拓维信息 / 000566 海南海药）
> 代理端点：`proxy-server/routes/bigOrder.js`

---

## 1. API 概览

本项目通过 `proxy-server` 封装了两个同花顺 L2 上游接口：

| 代理路由 | 上游 URL | 用途 |
|---|---|---|
| `GET /api/big-order/ths-detail` | `https://vaserviece.10jqka.com.cn/Level2/index.php?op=mainMonitorDetail&stockcode={code}` | 逐笔大单明细 + 主力资金摘要 + 分钟涨跌幅 |
| `GET /api/big-order/main-monitor` | `https://apphwhq.longhuvip.com/w1/api/index.php?a=GetMainMonitor_w30&c=StockYiDongKanPan&...` | 龙虎 VIP 大单监控（数组格式，支持分页） |

---

## 2. ths-detail：逐笔大单明细接口

### 2.1 顶层响应

```json
{
  "errorcode": 0,
  "msg": "ok",
  "title": { ... },
  "list": [ ... ],
  "pricechange": [ ... ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `errorcode` | number | 0 = 成功，非 0 = 错误 |
| `msg` | string | 错误描述，成功时为 `"ok"` |
| `title` | object | 当日主力资金摘要（7 个字段） |
| `list` | array | 逐笔大单明细列表（数十到数千条不等） |
| `pricechange` | array | 分钟级涨跌幅序列（盘中 121 条 = 09:30~11:30） |

### 2.2 `title` — 主力资金摘要（7 字段）

| 字段 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `stockcode` | string | `"002384"` | 6 位股票代码 |
| `stockname` | string | `"东山精密"` | 股票简称 |
| `price` | string | `"269.05"` | 当日最新价（字符串，需 `parseFloat`） |
| `profit` | string | `"2.50%"` / `"-5.99%"` | 当日涨跌幅，含 `%` 和正负号 |
| `mainbuy` | string | `"80.84亿"` | 主力买入总额（含中文单位：亿/万/元），当日累计 |
| `mainsell` | string | `"65.9亿"` | 主力卖出总额（含中文单位：亿/万/元），当日累计 |
| `istrade` | boolean | `true` | 是否在交易时段内（盘中 = true，收盘后 = false） |

**关键业务规律：**

- `mainbuy - mainsell` = 主力净流入（正 = 净买入，负 = 净卖出）
- 单位有 `亿` / `万` / `元` 三种，必须做解析。`proxy-server` 中 `parseChineseAmount()` 已处理此逻辑（[bigOrder.js:75-85](../../proxy-server/routes/bigOrder.js#L75-L85)）。
- 14 只股票实测：主力净流入与涨跌幅高度正相关。紫光股份净流入 +20.26 亿 +8.92%，华天科技净流出 -2.82 亿 -9.13%。

### 2.3 `list` — 逐笔大单明细（8 字段）

| 字段 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `nature` | string | `"主力主买"` | 大单性质标签，核心字段（详见下方分类） |
| `tradetype` | string | `"1"` | 交易方向：`1` = 买入方向，`2` = 卖出方向 |
| `volume` | string | `"562手"` | 成交量，单位"手"（1 手 = 100 股），含中文后缀 |
| `avgprice` | string | `"38.7151"` | 成交均价（元），保留 4 位小数 |
| `value` | string | `"218万"` | 成交额（文本格式，含中文单位），用于前端展示 |
| `money` | number | `2175787` | 成交额（纯数字，元），用于计算 |
| `ctime` | string | `"11:29:59"` | 成交时间（HH:mm:ss） |
| `otime` | string | `"11:29:59"` | 发生时间（HH:mm:ss），通常与 ctime 相同 |

#### `nature` 四种类型（14 只股票共 30,383 条数据统计）

| nature | tradetype | 语义 | 占比 |
|---|---|---|---|
| `主力主买` | 1 | **主动买入**：主力以卖一价或更高价主动吃进（aggressor） | ~27.3% |
| `主力被买` | 1 | **被动买入**：主力挂买单在买盘，被卖方成交（passive） | ~22.5% |
| `主力主卖` | 2 | **主动卖出**：主力以买一价或更低价主动砸出（aggressor） | ~28.2% |
| `主力被卖` | 2 | **被动卖出**：主力挂卖单在卖盘，被买方成交（passive） | ~22.0% |

**区分逻辑：**
- **"主"字**（主买/主卖）= 主力是主动发起方（aggressor），在追价
- **"被"字**（被买/被卖）= 主力是被动方（passive），在挂单等待
- `tradetype` 和 `nature` 方向一致：1 = 买入方向，2 = 卖出方向

### 2.4 `pricechange` — 分钟级涨跌幅序列

| 字段 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `"1"` | string | `"202607160930"` | 分钟时间戳（YYYYMMDDHHmm），09:30~11:30 共 121 条 |
| `{内部ID}` | number | `-2.7864` | 该分钟的实时涨跌幅（%）。Key 名 `2525646` 是 THS 内部固定常量，与实际股票代码无关 |

**验证：**
- 华天科技（-9.13%）：波动范围 **-10.00 ~ -6.01**，与全天大跌吻合
- 海南海药（+10.10%）：波动范围 **+2.52 ~ +10.10**，与涨停吻合
- 京东方A（-2.66%）：波动范围 **-3.13 ~ -0.16**，与小幅下跌吻合
- 所有 14 只股票的 pricechange key 名均为 `2525646`，但值随股票不同而变化

---

## 3. main-monitor：龙虎 VIP 大单监控接口

### 3.1 顶层响应

```json
{
  "List": [["2","1784172599","562","2175787","38.7151","2026-07-16 11:29:59"], ...],
  "param": ["30万","50万","100万","300万","1000万"],
  "Is_param": 0,
  "Total": 12360,
  "ttag": 0.003623,
  "errcode": "0"
}
```

### 3.2 字段说明

| 字段 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `List` | array | 见下方 | 逐笔大单数组，每条 6 个元素 |
| `param` | string[] | `["30万","50万","100万","300万","1000万"]` | 大单资金阈值档位（5 档可选） |
| `Is_param` | number | `0` | 是否启用资金阈值筛选（0 = 默认 30 万起，1 = 使用 Money 参数指定） |
| `Total` | number | `12360` | 符合条件的大单总笔数（当日全量） |
| `ttag` | number | `0.0036` | 服务端处理耗时（秒） |
| `errcode` | string | `"0"` | 错误码，`"0"` = 成功 |

### 3.3 `List` 每行结构

每条记录是固定 6 元素的数组：`[tradetype, unixTimestamp, volume, money, price, datetime]`

| 索引 | 类型 | 示例 | 含义 |
|---|---|---|---|
| `[0]` | string | `"1"` | **交易类型**（4 值：1/2/3/4） |
| `[1]` | string | `"1784172597"` | Unix 时间戳（秒） |
| `[2]` | string | `"150"` | 成交量（手） |
| `[3]` | string | `"580500"` | 成交额（元） |
| `[4]` | string | `"38.70"` | 成交均价（元） |
| `[5]` | string | `"2026-07-16 11:29:57"` | 成交时间（YYYY-MM-DD HH:mm:ss） |

### 3.4 `tradetype` 四值含义

`main-monitor`（longhuvip.com）的 `tradetype` 是上游原生 4 值编码。与 `ths-detail` 的 2 值 tradetype + nature 文本是两套独立体系，来自不同上游。

#### 参考：C# THSBigOrder 工具中的 Type 映射

C# 工具 `ThsPayloadParser.ParseOrder()` 将 ths-detail 的 `nature` 文本转为数值 Type（参见 `tools/THSBigOrder/Parsing/ThsPayloadParser.cs:135-146`）：

| nature 原文 | C# Type | 方向 | `BigOrderItem` 语义 |
|---|---|---|---|
| `主力被卖` | `1` | 卖出方 | `IsSell = true`（被动卖，aggressor=买方） |
| `主力主买` | `2` | 买入方 | `IsBuy = true`（主动买，aggressor=主力） |
| `主力被买` | `3` | 买入方 | `IsBuy = true`（被动买，aggressor=卖方） |
| `主力主卖` | `4` | 卖出方 | `IsSell = true`（主动卖，aggressor=主力） |

`CalculateMarkers` 中进一步体现了"谁驱动成交"的视角：Type 4+3 归为卖方驱动（卖压），Type 2+1 归为买方驱动（买压）。

> **注意：** 以上是 C# 工具对 `ths-detail` 的**内部转换规则**。`main-monitor` 的 `tradetype` 是 longhuvip.com 上游原生编码，两者编号体系可能相同也可能不同，尚未在同花顺官方文档中找到确认。

### 3.5 分页验证与真实页大小限制

2026-07-16 用 000938（紫光股份，Total=12,360）测试分页：

- Page1（index=0，limit=30）：时间范围 11:29:34 ~ 11:29:59，types=[1,2,3,4]
- Page2（index=30，limit=30）：时间范围 11:29:10 ~ 11:29:32，types=[1,2,3,4]
- 两页之间 **0 条重复**，时间连续递减（逆序返回，最新在前）

后续全量接入实测发现：`st` 不能安全放大到 500。请求 `st=300/400/500` 时，接口可能只返回约 `30/18/0~26` 条，但 `Total` 仍是完整当日总量，例如 `List=26、Total=17044`。

因此：

- 稳定上游页大小固定为 `200`。
- 有 `Total` 时不能用 `List.length < st` 作为成功结束条件。
- 累计数量未达到 `Total` 却出现短页，应判定为截断失败并保留已有完整 stale。
- 分页必须串行；并发分页实测会触发上游限流或异常。
- 正式聚合路径使用 POST `application/x-www-form-urlencoded`，单次完整加载复用同一个 DeviceID；当前 proxy 的 GET/逐请求 DeviceID 属于待改造现状。
- `Total≈17044` 时约需 86 页。proxy 同步聚合的完整重建预算为 45 秒，WinForms 对该结构化端点使用独立 60 秒超时；不能继续复用当前共享 15 秒超时。
- 响应中的 `param` 档位不能证明 API 只接受这些 money 值。旧 proxy 路由保持当前 numeric money 兼容，不新增 allowlist 400；新的 canonical 全天快照端点固定 `money=0`。

完整根因、修复规则和回归测试见 [THSBigOrder 双数据源调试复盘](../ths-big-order-debug/2026-07-16-debug-retrospective.md)。

### 3.6 14 只股票全量验证（2026-07-16）

| 股票 | Total | 返回 | 有效 | types |
|---|---|---|---|---|
| 603127 昭衍新药 | 4,516 | 10 | 10 | 1,3,4 |
| 000938 紫光股份 | 12,360 | 10 | 10 | 1,2,3,4 |
| 002156 通富微电 | 13,216 | 10 | 10 | 1,2,3,4 |
| 002185 华天科技 | 7,310 | 10 | 10 | 1,2,3,4 |
| 600664 哈药股份 | 1,279 | 10 | 10 | 3,4 |
| 002384 东山精密 | 22,529 | 10 | 10 | 1,2,3,4 |
| 002747 埃斯顿 | 3,023 | 10 | 10 | 1,2,3,4 |
| 603538 美诺华 | 2,598 | 10 | 10 | 1,2,3,4 |
| 600584 长电科技 | 10,179 | 10 | 10 | 1,2,3,4 |
| 000977 浪潮信息 | 8,809 | 10 | 10 | 1,2,3,4 |
| 000063 中兴通讯 | 9,949 | 10 | 10 | 1,3,4 |
| 000725 京东方A | 8,614 | 10 | 10 | 1,2,3,4 |
| 002261 拓维信息 | 2,622 | 10 | 10 | 1,2,3,4 |
| 000566 海南海药 | 1,026 | 10 | 10 | 3,4 |

**结论：14/14 全部成功，0 失败，0 条无效数据。** API 稳定可用。

---

## 4. ths-detail vs main-monitor 对比

| 维度 | ths-detail | main-monitor |
|---|---|---|
| 上游 | `vaserviece.10jqka.com.cn` | `apphwhq.longhuvip.com` |
| 数据格式 | 对象数组（8 字段/条） | 嵌套数组（6 元素/条） |
| tradetype | 2 值（`1`/`2`） | 4 值（`1`/`2`/`3`/`4`） |
| 主动性区分 | `nature` 文本字段（主力主买/被买等） | tradetype 直接编码 |
| 资金摘要 | ✅ `title` 含 mainbuy/mainsell/price/profit | ❌ 无摘要 |
| 分钟涨跌幅 | ✅ `pricechange` 121 条 | ❌ 无 |
| 分页支持 | ❌ 单次返回全部（最多数千条） | ✅ `Index` + `limit` |
| 资金筛选 | ❌ 固定逻辑 | ✅ `Money` 参数 + 5 档阈值 |
| 总笔数 | 需统计 list.length | ✅ `Total` 字段 |
| 数据传输效率 | 较低（JSON 对象冗余 key） | 较高（紧凑数组） |

---

## 5. 与 TDX L2 行情数据的互补关系

### 5.1 本质区别

| 维度 | THS L2 | TDX L2（通达信） |
|---|---|---|
| **数据性质** | 大单资金流向（逐笔成交分析） | 市场深度（买卖盘口 + 逐笔成交） |
| **核心回答** | "谁在买/卖？多少钱？什么方向？" | "挂单有多深？买卖价差多少？" |
| **上游** | 同花顺 HTTP API | 通达信 TCP 行情服务器（port 7709/7719） |
| **当前状态** | ✅ 可用（HTTP 代理） | ⚠️ L1 (7709) 可用，真 L2 十档 (7719) 未完成 |

### 5.2 TDX 当前提供的数据（python-bridge / mootdx）

**行情数据（来自 `normalize_quote_row`）：**
- `code`, `name`, `lastPrice`, `changePct`, `changeAmount`
- `volume`, `amount`, `open`, `high`, `low`, `preClose`
- `tdxBuyVolume`, `tdxSellVolume`, `tdxCurrentVolume`（TDX 特有内外盘数据）

**盘口深度（来自 `normalize_depth_row`）：**
- `bids`: 买盘档位（价格 + 量），当前 5 档
- `asks`: 卖盘档位（价格 + 量），当前 5 档
- 理论上 7719 端口支持十档，但尚未跑通

### 5.3 结论：不可替代，应互补

**THS L2 不能替代 TDX L2，因为两者提供完全不同维度的数据：**

- THS L2 告诉你**资金行为**：主力在做什么方向，主动性如何，净流入多少
- TDX L2 告诉你**市场结构**：买卖盘的挂单深度，多空力量在盘口上的分布

两者的关系类似于：
- THS L2 = "谁在打这场仗，火力有多猛"（资金流向分析）
- TDX L2 = "战场地形和兵力部署"（盘口深度分析）

**建议策略：**
1. **保持双源并行**：THS L2 做资金面分析，TDX 做盘口深度和实时行情
2. **THS L2 优先级更高**：对热榜/龙头识别场景，主力资金流向比盘口深度更有直接决策价值
3. **TDX L2（十档 + 逐笔）仍值得推进**：对于需要精确盘口分析、价差套利等高级场景不可替代
4. **短期可降级 TDX 优先级**：鉴于 THS L2 已能提供主力资金流向这一核心维度，TDX 7719 十档深度可适度延后

---

## 6. 代理层封装说明

`proxy-server/routes/bigOrder.js` 中已实现：

| 端点 | 缓存策略 | 备注 |
|---|---|---|
| `GET /api/big-order/ths-detail` | `ProcessMemoryCache`，TTL = 30s，stale = 180s | 单只股票逐笔大单明细 |
| `GET /api/quotes/ths-money-flow` | `Redis` 优先 → `ProcessMemoryCache` 回退，TTL = 60s，stale = 300s | 批量股票资金流摘要（并发 2 + 熔断 5） |
| `GET /api/big-order/main-monitor` | 无缓存（直通上游） | 龙虎 VIP 大单监控，支持 `limit`/`money`/`index` 参数 |
| `GET /api/big-order/all-day` | 无缓存（分页聚合） | 遍历分页获取全天大单数据 |

BigOrder Redis TTL、Longhu 全天快照和增量头部刷新改造方案见 [BigOrder Redis TTL 缓存设计](../ths-big-order-debug/big-order-redis-cache-design.md)。

上表描述当前源码现状。目标方案新增 `GET /api/big-order/longhu/all-day` 结构化端点，并返回明确的 `sessionDate`、`fetchedAt/servedAt`、technical stale 与 UI stale 元数据；在实现落地前不能把目标端点写成“已实现”。
