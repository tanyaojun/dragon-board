# 个股热度模块说明

## 1. 模块目标

个股热度模块的目标不是把八合一热榜原样展示一次，而是给项目提供一个独立、可复用、可调参的 `stock hotness` 服务能力。

它的职责只有三件事：

1. 计算个股热度
2. 把热度结果写回 `DataLayer`
3. 供真龙复盘、快照、面板等模块消费


## 2. 目录结构

```text
src/services/hotness/
├─ StockHotnessCalculator.ts
├─ StockHotnessConfigService.ts
├─ index.ts
└─ __tests__/
   └─ StockHotnessCalculator.test.ts
```

### 2.1 `StockHotnessCalculator.ts`

负责核心热度计算。

### 2.2 `StockHotnessConfigService.ts`

负责热度参数管理。

### 2.3 `index.ts`

统一对外导出入口，避免调用方直接跨文件引用内部实现。

### 2.4 `__tests__/StockHotnessCalculator.test.ts`

用于锁住热度计算公式和边界行为。


## 3. 和主服务的数据交互

主链路如下：

```text
dataLoader.mergeData()
  -> calculateStockHotnessUpdates(...)
  -> dataLayer.updateStockHotness(...)
  -> merge back to stocks
  -> snapshot / dragon / UI consume
```

### 3.1 `dataLoader`

负责把个股基础字段准备好，然后触发热度计算。

### 3.2 `DataLayer`

负责存储和读取热度结果。

### 3.3 真龙模块

真龙模块不自己重算热度，只消费：

- `stock.hotness`
- `stock.popularity`
- `stock.popularityChange`
- `stock.themeHeat`

### 3.4 快照与面板

快照 builder 会把热度字段带进快照，面板直接展示，不重复定义。


## 4. 为什么 `avgRank` 不能直接等于 `hotness`

`avgRank` 只是多平台排名位置的汇总。

它能说明：

- 这只票在多少平台被讨论
- 排名整体靠前还是靠后

但它不能完整代表：

- 热度覆盖面
- 人气绝对值
- 人气变化速度
- 题材配合度
- 连板和身位强化

因此当前模块的原则是：

- `avgRank` 是热度因子之一
- 但绝不能直接替代 `hotness`


## 5. 热度计算逻辑

当前个股热度是综合值，不是单字段拷贝。

主输入包括：

- `avgRank / avgRankNum`
- 覆盖平台数 `platforms`
- `popularity`
- `popularityChange`
- `leadStatus / leadTimes`
- `boardHeight / continuousDays / highDays`
- `turnoverRate`
- `themeHeat`

计算目标是同时回答：

1. 这只票有没有被广泛关注
2. 关注度是在扩散还是衰减
3. 这种关注度有没有被题材和身位强化


## 6. 输出字段

当前模块对外最核心的输出就是：

- `hotness`

但实际业务使用时，通常会与这些字段组合使用：

- `popularity`
- `popularityChange`
- `mainTheme`
- `themeHeat`
- `themeLevel`


## 7. 维护原则

1. 热度模块独立，不嵌进真龙模块内部
2. 热度可以调参，但不能无限加因子
3. 热度结果必须能回放，不依赖面板临时状态
4. 真龙模块只能消费热度结果，不能把热度公式再写一遍


## 8. 关联文档

- `docs/stock-hotness-tuning-manual.md`
- `docs/dragon-review-maintenance-guide.md`
