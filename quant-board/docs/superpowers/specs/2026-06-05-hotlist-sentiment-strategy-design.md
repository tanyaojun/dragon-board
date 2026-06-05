# 热榜情绪替换市场情绪——策略改造设计

## 动机

当前 RankTrend 策略的 `compose_strategy()` 使用 `market_regime()`（全市场情绪宽度：涨跌比、涨停数、情绪阶段）作为生命周期分层的辅助判断。但热榜股票池的短期走势更多取决于**股民对"这只票"的情绪共识**，而非整体市场的温度。

已知：
- `DragonBreathAnalyzer`（全市场情绪）和 `HotListSentimentAnalyzer`（热榜情绪）在 TypeScript 端已并行存在，共享五阶段语言
- 热榜情绪分析器从未接入 Python 回测/策略管线
- L1 方向精度 37-39% 持续低于 50% 随机基准，说明整体市场情绪对热榜个股的短期方向缺乏区分力

本设计用热榜情绪**完全替换**市场情绪在策略决策中的角色。

## 范围

- 新建 MongoDB 集合 `hotlist_sentiment`，按交易日存储热榜情绪数据
- TypeScript 端改造 `HotListSentimentAnalyzer`：全池覆盖、新增 turnover 进出明细、每日收盘写入 MongoDB
- Python 端新增读取路径，在 `compose_strategy()` 中用热榜情绪替换 `market_regime()`
- 历史数据回填 2026-04-16 至今所有交易日

## 非范围

- 不删除 `market_regime()`（保留为诊断参考）
- 不改变 `compose_decision()` 的信号合成公式
- 不改变 RankTrend 其他分析模块
- 不修改 DragonBreathAnalyzer 的核心逻辑

---

## 1. 数据模型——MongoDB `hotlist_sentiment`

独立集合，一条文档 = 一个交易日。按 `tradingDate` 查询。

```json
{
  "_id": "2026-06-05",
  "tradingDate": "2026-06-05",
  "snapshotType": "half_hour",
  "computedAt": 1717574400,

  "stage": "高潮",
  "riskLevel": "低",
  "confidence": 78,
  "summary": "热榜情绪处于高潮阶段，资金积极向涨方集中，涨停交集率持续上升",

  "metrics": {
    "poolSize": 218,
    "allPoolUpRatio": 0.48,
    "hotTrin": 0.82,
    "retentionRate1d": 0.73,
    "retentionRate2d": 0.58,
    "limitIntersectionRate": 0.18,
    "newEntryCount": 31,
    "eliminatedCount": 24
  },

  "turnover": {
    "previousPoolSize": 225,
    "currentPoolSize": 218,
    "retainedFromYesterday": 187,
    "newEntries": ["000xxx", "600xxx"],
    "eliminated": ["300xxx", "002xxx"],
    "newEntryDetails": [
      {
        "code": "000xxx",
        "name": "某某科技",
        "rank": 45,
        "changePct": 9.8,
        "entryReason": "limit_up"
      }
    ],
    "eliminatedDetails": [
      {
        "code": "300xxx",
        "name": "某某股份",
        "rank": 215,
        "changePct": -3.2,
        "exitReason": "rank_out_of_range"
      }
    ]
  },

  "signals": ["热榜资金向涨方倾斜", "涨停交集率上升", "新进品种以强资确认为主"],
  "warnings": ["前日强势股持续性偏弱"]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `stage` | string | 统一五阶段：冰点/启动/发酵/高潮/退潮 |
| `riskLevel` | string | 低/中/高 |
| `confidence` | number | 0-100 信心分 |
| `summary` | string | 人类可读摘要 |
| `metrics.poolSize` | int | 当日热榜池总数 |
| `metrics.allPoolUpRatio` | float | 全池上涨比例 |
| `metrics.hotTrin` | float | 热榜 TRIN（上涨成交额/下跌成交额），<1 偏强 |
| `metrics.retentionRate1d` | float | 一日留榜率 |
| `metrics.retentionRate2d` | float | 两日留榜率 |
| `metrics.limitIntersectionRate` | float | 热榜与涨停交集率 |
| `metrics.newEntryCount` | int | 新进股票数 |
| `metrics.eliminatedCount` | int | 淘汰股票数 |
| `turnover` | object | 每日进出明细 |
| `turnover.newEntryDetails[].entryReason` | string | 进榜原因：limit_up / strong_money / rank_surge / new_high_volume |
| `turnover.eliminatedDetails[].exitReason` | string | 出榜原因：rank_out_of_range / weakening / limit_down |

---

## 2. TypeScript 计算层改造

文件：`src/services/hotlist/HotListSentimentAnalyzer.ts`

### 2.1 全池覆盖

`buildLayerMetrics` 新增 `all` 层，覆盖当日热榜全池 200+ 只股票。计算逻辑（upRatio、hotTrin、statusCounts）不变，仅输入范围放大。

### 2.2 新增 turnover 计算

新增 `computeTurnover(todayStocks, yesterdayStocks)` 方法，对比两日股票池：

- `entryReason` 分类：limit_up（涨停首板）、strong_money（主力净流入前 20%）、rank_surge（排名跳升 ≥50 位）、new_high_volume（量比 > 2）
- `exitReason` 分类：rank_out_of_range（排名跌出热榜）、weakening（转弱预警）、limit_down（跌停）

### 2.3 每日收盘触发

新增 `persistToMongoDB(result, tradingDate)` 方法，将分析结果写入 MongoDB `hotlist_sentiment` 集合。触发时机：检测到今日最后一帧 half_hour 快照（≥15:00）到达后自动执行。

### 2.4 历史回填脚本

一次性脚本，遍历 2026-04-16 ~ 今所有交易日的 `snapshot_frames`，取每日最后一帧热榜数据作为输入，逐日计算并写入。

---

## 3. Python 策略层接入

### 3.1 新增 Repository

文件：`backend/data/hotlist_sentiment_repo.py`

```python
class HotListSentimentRepository:
    def __init__(self, mongo_db):
        self._collection = mongo_db["hotlist_sentiment"]
        self._cache: dict[str, dict | None] = {}

    def get_by_date(self, trading_date: str) -> dict | None:
        if trading_date not in self._cache:
            self._cache[trading_date] = self._collection.find_one(
                {"tradingDate": trading_date}
            )
        return self._cache[trading_date]
```

带内存缓存，一次回测最多 34 次 MongoDB 查询。

### 3.2 `compose_strategy()` 改造

函数签名变更：`regime: dict` → `hotlist: dict | None`

五阶段映射规则：

| 热榜阶段 | riskLevel | 策略行为 |
|---|---|---|
| 高潮 | 低/中 | 全开：A_MAIN + B_IGNITION 均可入场 |
| 发酵 | 低/中 | 正常：A_MAIN + B_IGNITION 按默认阈值入场 |
| 启动 | 任意 | 仅点火：仅 B_IGNITION 允许，A_MAIN 暂缓 |
| 退潮 | 任意 | 退场：只允许 D_EXIT_RISK 卖出，禁止新入场 |
| 冰点 | 任意 | 冰封：禁止一切入场 |

缺失数据时 `hotlist` 为 `None`，函数内部视为空 `{}`，所有字段取默认值，不影响其他判断分支。

### 3.3 接入 replay 管线

`RankTrendPythonEngine.replay()` 启动时预加载全量热榜情绪，注入每帧的 `compose_strategy()` 调用。

---

## 4. 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `src/services/hotlist/HotListSentimentAnalyzer.ts` | 修改 | 全池覆盖、turnover 计算、MongoDB 写入 |
| `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts` | 修改 | 新增全池/turnover 用例 |
| `quant-board/backend/data/hotlist_sentiment_repo.py` | 新建 | MongoDB 查询封装 |
| `quant-board/backend/analysis/ranktrend.py` | 修改 | `compose_strategy()` 签名+逻辑改造 |
| `quant-board/backend/core/backtest/strategy.py` | 修改 | 调用方适配新签名 |
| `quant-board/backend/core/backtest/execution.py` | 修改 | 调用方适配 |
| `quant-board/backend/services.py` | 修改 | replay 管线注入热榜情绪 |
| `quant-board/backend/cli.py` | 修改 | CLI 回测命令注入热榜情绪 |
| `quant-board/tests/` | 修改 | 适配签名变更，新增热榜情绪相关测试 |
| 历史回填脚本 | 新建 | 一次性批量处理 |

## 5. 验收标准

1. `hotlist_sentiment` 集合包含 2026-04-16 ~ 今所有交易日数据
2. `compose_strategy()` 不再调用 `market_regime()`
3. Python 端 28 核心测试 + 7 策略测试全部通过
4. H2 基线（half_hour/next_bar）可正常执行，不报错
5. 新增至少 3 个测试覆盖热榜情绪映射逻辑（高潮入场/冰点禁止/缺失处理）
