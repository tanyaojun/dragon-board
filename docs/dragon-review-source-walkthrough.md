# 真龙复盘源码主链路走读

## 1. 这份文档看什么

这份文档专门回答三个问题：

1. 真龙复盘从哪里进来
2. 8 段主链路按什么顺序跑
3. 数据最后怎么落到 `DataLayer` 和 `DragonHeadPanel.vue`


## 2. 入口层

### 2.1 应用启动入口

应用侧真龙复盘入口在：

- `src/App.vue`

启动时会直接调用：

- `dragonReviewService.runFullUpdate()`

这保证真龙复盘不是“点开面板才算一次”，而是刷新链路里就会重建。

### 2.2 刷新协调器入口

统一刷新链路在：

- `src/services/RefreshCoordinator.ts`

当前顺序是：

1. `dataLoader`
2. `sectorAnalyzer`
3. `dragonBreathAnalyzer`
4. `dragonReviewService`
5. `algorithmManager`

这里的含义很关键：

- 先把个股、题材、情绪都准备好
- 再做真龙复盘
- 最后算法中心再吃这批结果


## 3. 核心 orchestrator

总调度器在：

- `src/services/dragon/DragonReviewService.ts`

这个文件里最关键的方法是：

- `runFullUpdate()`
- `rebuildReview()`
- `syncData()`

`rebuildReview()` 是整个真龙链的主入口。


## 4. 8 段主链路

### 4.1 `FrameNormalizer`

文件：

- `src/services/dragon/FrameNormalizer.ts`

职责：

- 从快照体系读取多粒度数据
- 统一成 `ReviewFrame[]`
- 输出 `reviewDate / frames / missingData`

这里是第一层质量门。

如果这里拿不到：

- 日级快照
- 盘中帧
- 收盘帧

那后面所有判断都会降级。

### 4.2 `SessionSegmenter`

文件：

- `src/services/dragon/SessionSegmenter.ts`

职责：

- 把当天的 `ReviewFrame[]` 划分成 `early / mid / late`

这一步之后，所有“先手、分歧、收盘领导权”的判断才有基础。

### 4.3 `RegimeClassifier`

文件：

- `src/services/dragon/RegimeClassifier.ts`

职责：

- 给当天市场打上环境标签

典型输出：

- `MAINLINE_ADVANCE`
- `MULTI_FRONT_CONTEST`
- `ROTATION_NO_CORE`

这一步不产龙，但它会影响摘要、判断阈值和对结果的解释。

### 4.4 `BattlefieldBuilder`

文件：

- `src/services/dragon/BattlefieldBuilder.ts`

职责：

- 基于热门题材、轮动主线、联动性、独立强股建战场

当前实现里有几个关键约束：

- 题材战场上限
- 风格战场上限
- 独立战场上限
- 总战场上限

目的是防止“什么都叫战场”。

### 4.5 `CandidatePoolBuilder`

文件：

- `src/services/dragon/CandidatePoolBuilder.ts`

职责：

- 对每个战场缩出最多 5 个候选
- 构建 `StockArc`

`StockArc` 是这一步的核心中间结构，它记录：

- 哪几段出现过
- 早段排位
- 尾段排位
- 跟风数变化
- 题材排名提升
- 热度、人气、板高峰值

### 4.6 `LeadershipAuthorityEngine`

文件：

- `src/services/dragon/LeadershipAuthorityEngine.ts`

职责：

1. 跑四道门
2. 战场内 duel
3. 判 `authority`
4. 产墓地

这是最重要的判断引擎。

### 4.7 `TradeabilityEngine`

文件：

- `src/services/dragon/TradeabilityEngine.ts`

职责：

- 给每只样本补 `tradeability`
- 给每只样本补 `chaseRisk`

这里解决的是：

- 它可能是真龙
- 但它也可能完全不能追

### 4.8 `ReviewComposer`

文件：

- `src/services/dragon/ReviewComposer.ts`

职责：

- 排序
- 去重
- 选 `marketCore`
- 生成三榜一墓地一时间线
- 拼 `summaryLines`

这是最终结果装配层。


## 5. 输入数据从哪里来

### 5.1 个股基础字段

主要来自：

- `src/services/dataLoader.ts`
- `src/services/DataLayer.ts`

关键字段包括：

- `themes`
- `mainTheme`
- `themeHeat`
- `themeLevel`
- `hotness`
- `leadStatus`
- `boardHeight`
- `highDays`
- `continuousDays`

### 5.2 题材热度和热门题材

主要来自：

- `src/services/sectorAnalyzer.ts`

它会负责：

- 更新题材指标
- 更新热门题材列表
- 把题材同步回个股

### 5.3 快照输入

真龙复盘主要依赖：

- `src/services/snapshot/`

尤其是快照 builder 产出的：

- `hotlist`
- `hotThemes`
- `sectors`
- `marketStats`


## 6. 输出怎么回写

### 6.1 回写 `DataLayer`

在 `DragonReviewService.syncData()` 里，最终结果会回写到：

- `dataLayer.updateReviewData(...)`

回写后，`DataLayer.review` 成为统一数据源。

### 6.2 事件通知

回写后还会发两个事件：

- `AppEvents.DRAGON.UPDATED`
- `AppEvents.DRAGON.CHANGED`

第一个事件用于整份复盘刷新。

第二个事件用于时间线和细粒度变动通知。


## 7. 面板怎么吃数据

面板文件：

- `src/components/panels/DragonHeadPanel.vue`

当前面板的数据读取方式是：

- 首次打开时直接从 `dragonReviewService.getLatestReview()` 拿
- 后续通过 `AppEvents.DRAGON.UPDATED` 监听刷新

面板内部的主要计算只有展示层逻辑：

- `tabs`
- `statCards`
- `stockDisplayName`
- `battlefieldLeaderCode`

它不会自己重新判龙。


## 8. 建议断点位置

如果后续要排障，建议优先在这几个点打断：

### 8.1 帧是否正常

- `FrameNormalizer.normalize()`

看：

- `frames.length`
- `missingData`

### 8.2 战场是否正常

- `BattlefieldBuilder.build()`

看：

- 进入 `themeSeeds` 的题材数
- 最终 `battlefields.length`
- `dominance`

### 8.3 候选池是否正常

- `CandidatePoolBuilder.build()`

看：

- 每个战场 `candidateCodes`
- `challengerCodes`
- `followerCodes`

### 8.4 四道门是否正常

- `LeadershipAuthorityEngine.evaluate()`

看：

- `gateA / gateB / gateC / gateD`
- `fatalNegatives`
- `duelResults`

### 8.5 最终榜单是否正常

- `ReviewComposer.compose()`

看：

- `trueLeaders`
- `heightBoard`
- `attentionBoard`
- `pseudoLeaderGraveyard`
- `transitions`


## 9. 常见问题和定位方向

### 9.1 战场明显不对

优先查：

- `BattlefieldBuilder`
- `sectorAnalyzer`
- `themeHeat / persistentDays / correlation`

### 9.2 热度榜全变零

优先查：

- `dataLoader` 是否把 `hotness`、`themeHeat`、`mainTheme` 回写到了个股字段
- `snapshot builders` 是否把这些字段带进了快照

### 9.3 墓地数量异常膨胀

优先查：

- `LeadershipAuthorityEngine`
- `ReviewComposer`

看是否把普通高标或普通热票也扔进了墓地。

### 9.4 时间线一直为空

优先查：

- `LeaderRecord.timeline`
- `ReviewComposer.buildTransitions`


## 10. 关联文档

- `docs/dragon-review-maintenance-guide.md`
- `docs/dragon-review-case-replay-templates.md`
