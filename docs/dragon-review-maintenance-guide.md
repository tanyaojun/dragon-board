# 真龙复盘维护手册

## 1. 文档定位

这份文档服务于两个目标：

1. 帮后续维护者快速看懂 `src/services/dragon/` 这套真龙复盘引擎到底怎么跑。
2. 帮排障时快速判断问题是在数据输入、战场识别、领导权判定，还是面板展示层。

这份手册不讨论“旧龙头打分器”的设计。当前模块的唯一目标是：

- 识别真龙
- 拆穿高标
- 识破热度陷阱

系统输出不是单榜，而是四类结果：

- `trueLeaders`
- `heightBoard`
- `attentionBoard`
- `pseudoLeaderGraveyard`

外加两个辅助结构：

- `battlefields`
- `transitions`


## 2. 总体设计

### 2.1 龙头不再等于最高、最热、分数最高

当前真龙定义是：

> 在真实战场中率先发动、带出跟随、穿越分歧、收盘仍掌握领导权的股票。

因此系统必须显式区分三件事：

- 高标：身位概念
- 热度：关注度概念
- 龙头：领导权概念

对外只保留 5 个角色：

- `MARKET_CORE`
- `THEME_CORE`
- `SPACE_CORE`
- `TREND_CORE`
- `EMOTION_CORE`

对外还保留 6 个领导权分类：

- `TRUE_LEADER`
- `THEME_COMMANDER`
- `CARRY_PROXY`
- `HEIGHT_ONLY`
- `HEAT_ONLY`
- `PSEUDO_LEADER`

规则是：

- 先判 `authority`
- 再判 `role`

不允许反过来。


## 3. 模块目录结构

当前真龙复盘主目录：

```text
src/services/dragon/
├─ BattlefieldBuilder.ts
├─ CandidatePoolBuilder.ts
├─ DragonReviewService.ts
├─ FrameNormalizer.ts
├─ LeadershipAuthorityEngine.ts
├─ RegimeClassifier.ts
├─ ReviewComposer.ts
├─ SessionSegmenter.ts
├─ TradeabilityEngine.ts
├─ helpers.ts
├─ labels.ts
├─ types.ts
└─ index.ts
```

各文件职责如下。

### 3.1 `types.ts`

统一定义真龙模块的全部核心类型，包括：

- `ReviewFrame`
- `BattlefieldRecord`
- `CandidateRecord`
- `LeaderRecord`
- `PseudoLeaderRecord`
- `LeaderTransition`
- `DragonReviewResult`

这是整个模块的数据契约层。UI、导出、DataLayer、服务之间都依赖它。

### 3.2 `helpers.ts`

放所有跨模块共享的基础工具和排序逻辑，包括：

- 时间解析
- 板高推断
- 题材引用规范化
- 净资金计算
- `battlefieldPriorityScore`
- `sortBattlefields`

凡是“多个文件都会用到”的纯函数，都应该优先落在这里。

### 3.3 `labels.ts`

统一中文标签映射层，包括：

- 角色标签
- 领导权标签
- 市场环境标签
- 战场类型标签
- 缺失数据标签

UI 不应该自己硬编码枚举中文。统一从这里走。

### 3.4 `FrameNormalizer.ts`

把散落在快照体系里的不同时间粒度数据拉平成统一的 `ReviewFrame[]`。

输入来源包括：

- 刻钟快照
- 半小时快照
- 整点快照
- 日级快照
- 收盘态

输出保证：

- 统一字段
- 统一时间轴
- 统一热榜样本结构

### 3.5 `SessionSegmenter.ts`

把 `ReviewFrame[]` 切成三段：

- `early`
- `mid`
- `late`

切分规则是固定的：

- 前 30% 为 `early`
- 中间 40% 为 `mid`
- 后 30% 加收盘态为 `late`

### 3.6 `RegimeClassifier.ts`

只负责判断当日复盘环境，不直接产龙。

输出值包括：

- `MAINLINE_ADVANCE`
- `MULTI_FRONT_CONTEST`
- `HIGH_LEVEL_HUG`
- `REPAIR_ATTEMPT`
- `ROTATION_NO_CORE`
- `DISTRIBUTION_DECAY`

环境只作为约束，不作为龙头结论本身。

### 3.7 `BattlefieldBuilder.ts`

负责从市场里构建“可竞争战场”。

战场只允许三类：

- `THEME`
- `STYLE`
- `INDEPENDENT`

当前实现里，战场来源被严格限制，避免再出现“题材库存全变战场”的情况。

### 3.8 `CandidatePoolBuilder.ts`

负责在每个战场里缩出小候选池。

原则是：

- 每个战场最多 5 个候选
- 先保留“像龙的东西”
- 真伪判断交给后面的领导权引擎

### 3.9 `LeadershipAuthorityEngine.ts`

这是全模块最核心的文件。

它做三件事：

1. 跑四道门
2. 做战场内 duel
3. 给出 `authority / role / graveyard`

### 3.10 `TradeabilityEngine.ts`

把“真龙成立”和“能不能追”彻底拆开。

输出：

- `tradeability`
- `chaseRisk`

### 3.11 `ReviewComposer.ts`

把前面所有中间结果收敛成最终结构：

- 三榜
- 一墓地
- 一时间线
- 复盘摘要

### 3.12 `DragonReviewService.ts`

模块总调度入口。

它负责：

- 串联 8 段主链路
- 缓存上一版复盘结果
- 回写 `DataLayer.review`
- 通过事件总线通知 UI 更新


## 4. 文件之间怎么互相引用

主调用链如下：

```text
App / RefreshCoordinator
  -> DragonReviewService
    -> FrameNormalizer
    -> SessionSegmenter
    -> RegimeClassifier
    -> BattlefieldBuilder
    -> CandidatePoolBuilder
    -> LeadershipAuthorityEngine
    -> TradeabilityEngine
    -> ReviewComposer
      -> DataLayer.updateReviewData(...)
        -> DragonHeadPanel.vue
```

关键依赖关系：

- `DragonReviewService` 是 orchestrator，其它 8 个模块都不应该反向依赖它。
- `BattlefieldBuilder`、`CandidatePoolBuilder`、`FrameNormalizer` 会读 `DataLayer`。
- `ReviewComposer` 不应该读 UI，也不应该写事件。
- `DragonHeadPanel.vue` 只消费 `DragonReviewResult`，不参与业务判断。


## 5. 真龙到底怎么得来

### 5.1 第一步：统一帧

先把多时间粒度快照统一成 `ReviewFrame[]`。

每帧至少包含：

- `hotlist`
- `sectors`
- `marketStats`
- `sentiment`

如果这些字段缺失，最后会反映为：

- `missingData`
- `reviewCompleteness = partial`

#### 盘中和收盘不是一个判定时点

这条必须写死。

真龙复盘引擎虽然能在交易时段跑，但盘中结果和收盘结果不是同一种东西。

盘中通常只有：

- 刻钟快照
- 半小时快照
- 整点快照

这时经常还没有：

- 完整 `close frame`
- 日级快照

所以交易时段更适合看：

- 哪些战场正在形成
- 哪些票像高标样本
- 哪些票只是热度样本

不适合过早下这些结论：

- 市场总龙头已经确认
- `trueLeaders` 一定完整
- `MARKET_CORE / THEME_CORE / TREND_CORE` 最终已经稳定

换句话说：

- 盘中可以看“候选和样本”
- 收盘后再看“确认和归因”

如果当天还没保存日级快照，或者 `reviewCompleteness = partial`，优先把结果当作“临时复盘态”，不要当最终真龙结论。

### 5.2 第二步：切三段

真龙不是看一个瞬间，而是看跨段表现。

系统把一天拆成：

- 早段：点火与先手
- 中段：分歧与承接
- 尾段：收盘领导权

### 5.3 第三步：先建战场，再看个股

系统不允许直接全市场扫出“分数最高一只”。

正确路径必须是：

1. 先确认有没有值得看的战场
2. 再确认每个战场里谁有领导权

### 5.4 第四步：缩候选池

每个战场最多留下 5 只候选。

候选只是“有资格进审”，不是龙头。

### 5.5 第五步：跑四道门

四道门是硬门槛。

#### Gate A 战场门

要求：

- 战场不能是 `WEAK`
- 纯风格战场不能直接产真龙

#### Gate B 因果门

要求候选更像“发动原因”，不是“热度结果”。

核心观察：

- 启动是否领先
- 早段是否已进前二
- 后续是否带出跟风
- 题材热度是否在其后扩散

#### Gate C 分歧门

要求候选经历真实检验。

核心观察：

- 是否跨两个 segment 保持核心位置
- 是否只是连续一字孤勇

#### Gate D 收盘门

要求收盘仍有领导权。

核心比较字段：

- `boardHeight`
- `leadStatus`
- 资金净额
- 封单/承接
- 题材带动

### 5.6 第六步：战场内 duel

不是加权总分，而是维度判胜。

固定 7 个 duel 维度：

- `initiative`
- `height`
- `acceptance`
- `capitalRecognition`
- `carryEffect`
- `segmentPersistence`
- `closeIntegrity`

每个维度只允许：

- `win`
- `tie`
- `lose`

真龙确认条件：

- 四道门全过
- 对核心 challenger 至少赢 4 项
- 没有 fatal negative

### 5.7 第七步：给 authority

这里才真正产生结论。

规则简化如下：

- `TRUE_LEADER`
  - 四门全过
  - duel 取胜
  - 无 fatal negative
- `THEME_COMMANDER`
  - 战场门、因果门、收盘门通过
  - 但分歧门或 duel 压制力不够
- `CARRY_PROXY`
  - 更像承载主线，不像发动主线
- `HEIGHT_ONLY`
  - 高度有了，领导权没有
- `HEAT_ONLY`
  - 热度有了，领导权没有
- `PSEUDO_LEADER`
  - 一度像龙，最后没成

### 5.8 第八步：给 role

`role` 必须建立在 `authority` 之后。

例如：

- `THEME_CORE` 只能来自 `TRUE_LEADER / THEME_COMMANDER`
- `MARKET_CORE` 只能从 `TRUE_LEADER` 中选
- `EMOTION_CORE` 可以由 `HEAT_ONLY` 承担，但不进真龙榜


## 6. 三榜、一墓地、一时间线怎么产出

### 6.1 真龙榜

只收 `authority === TRUE_LEADER`

### 6.2 高标榜

收：

- `roles` 包含 `SPACE_CORE`
- 或 `authority === HEIGHT_ONLY`

### 6.3 热度榜

不是八合一热榜原样搬运。

只收满足这两个条件的样本：

1. 个股真的很热
2. 所在战场是有效战场

### 6.4 墓地

不是垃圾桶。

只有“真的像过龙、后来失位”的样本才进墓地。

### 6.5 时间线

时间线不是只记录真龙。

它也会记录：

- 高标候选入池
- 热度票转弱
- 主导权切换
- 市场总龙头替换


## 7. 龙头复盘面板怎么吃数据

面板文件：

- `src/components/panels/DragonHeadPanel.vue`

它只做展示层，不做业务判断。

主要消费字段：

- 概览区：`marketCore / summaryLines / missingData`
- 真龙榜：`trueLeaders`
- 高标榜：`heightBoard`
- 热度榜：`attentionBoard`
- 墓地：`pseudoLeaderGraveyard`
- 战场：`battlefields`
- 时间线：`transitions`

当前面板的关键展示原则：

- 纯中文口径
- 战场按“主战场优先”排序
- 参与者显示“名字 + 代码”
- 缺失数据映射成中文标签

### 7.1 `列表` 和 `分角色` 不是同一个口径

这是当前最容易被误读的地方。

`列表` 视图是“复盘样本池”，会把这些来源合并展示：

- `trueLeaders`
- `heightBoard`
- `attentionBoard`

每条记录都应该带来源标签：

- `真龙榜`
- `高标榜`
- `热度榜`

它的用途是：

- 盘中快速扫样本
- 看今天到底是“真龙少”，还是“高标和热度多”

它不是：

- 角色统计页
- 真龙总数页

`分角色` 视图则只看“确认真龙”。

它的统计来源应该是：

- `trueLeaders`

而且按 `roles.includes(role)` 计数，不是简单按 `primaryRole` 单计一列。

原因很简单：

- 一个确认真龙可以同时带多个角色
- `primaryRole` 只是它当前主显示角色
- 不能因为它主显示成 `SPACE_CORE`，就把其它角色信息吃掉

### 7.2 为什么会看到一堆 `SPACE_CORE`

这不一定说明后台只算出了空间龙头。

当前引擎里，`SPACE_CORE` 是最容易被挂上的角色之一，因为它主要反映：

- 板高
- 跨段命中
- 身位存在感

而 `THEME_CORE / TREND_CORE / EMOTION_CORE` 需要更强的附加条件。

所以有两种完全不同的情况：

1. 列表里很多样本带 `SPACE_CORE`
   这通常只是说明今天高标样本多，不代表它们都是真龙。
2. 分角色里确认真龙几乎都只有 `SPACE_CORE`
   这才说明后台角色派发可能偏向“高度优先”，需要继续检查引擎逻辑。

先分清这两种情况，再排障。


## 8. 模块和外部服务的数据交互

### 8.1 `DataLayer`

真龙模块最终回写到 `DataLayer.review`。

核心字段：

- `marketCore`
- `trueLeaders`
- `heightBoard`
- `attentionBoard`
- `pseudoLeaderGraveyard`
- `battlefields`
- `transitions`
- `summaryLines`

### 8.2 `dataLoader`

负责把个股主字段补齐给真龙模块用，比如：

- `themes`
- `mainTheme`
- `themeHeat`
- `themeLevel`
- `hotness`
- `leadStatus`
- `lianbanStr`
- `turnoverRate`

### 8.3 `sectorAnalyzer`

负责题材热度、热门题材和题材映射同步。

真龙模块的题材战场判断高度依赖它。

### 8.4 `snapshot`

真龙模块不直接抓原始平台接口，而是优先消费快照体系。

这保证了：

- 可回放
- 可复盘
- 多次重建结果更稳定


## 9. 常见故障排查

### 9.1 交易时间看不到真龙

先不要急着判代码错。

按这个顺序检查：

1. 现在是不是还在交易时段
2. `reviewCompleteness` 是不是 `partial`
3. `FrameNormalizer` 是否还没有拿到 `close frame`
4. 当日日级快照是否尚未保存

如果上面任何一条成立，那么：

- `marketCore` 为空是允许的
- `trueLeaders` 很少甚至为空也是允许的
- 更应该看 `heightBoard / attentionBoard / battlefields`

换句话说，盘中“算不出龙头”很多时候不是 bug，而是判定时点还没到。

### 9.2 真龙榜一直空

先看三个方向：

1. `FrameNormalizer` 是否拿到足够帧
2. `BattlefieldBuilder` 是否把所有战场都判成 `WEAK`
3. `LeadershipAuthorityEngine` 是否四道门过严

### 9.3 高标榜为空

优先看：

- `boardHeight / highDays / continuousDays` 是否从快照或扩展数据正确回填
- `CandidatePoolBuilder` 是否把高标样本吞没到热度样本里

### 9.4 热度榜全是热榜搬运

说明 `ReviewComposer` 的热度过滤坏了。

正确逻辑必须同时看：

- 个股热度信号
- 战场有效性

### 9.5 分角色几乎全是空间龙头

先不要直接改引擎，按这个顺序查：

1. 你看的到底是 `列表` 还是 `分角色`
2. 列表里的样本来源是不是大多来自 `高标榜`
3. 这些票的 `authority` 是不是主要是 `CARRY_PROXY / HEIGHT_ONLY`
4. 只有在 `分角色` 里确认真龙也几乎都只剩 `SPACE_CORE` 时，才继续查后台

后台重点看两处：

- `LeadershipAuthorityEngine.deriveRoles()`
- `ReviewComposer.heightBoard`

如果只是列表里 `SPACE_CORE` 很多，那多半是口径问题，不是计算问题。

### 9.6 战场数量失控

先查：

- `BattlefieldBuilder` 的题材入池条件
- 战场上限是否生效
- 是否把所有强势股挂过的题材都硬建场

### 9.7 面板中英文混排

优先检查：

- `labels.ts`
- `DragonHeadPanel.vue`

UI 层不应该直接渲染英文枚举。


## 10. 修改守则

后续继续迭代时，必须守住这些边界：

1. 不允许回到“全市场统一打分出龙头”
2. 不允许让热度或高标绕过 `authority` 直接成为龙头
3. 不允许 UI 直接参与判定逻辑
4. 不允许 `ReviewComposer` 里回填业务判断
5. 不允许把墓地做成普通失败样本垃圾桶
6. 不允许把战场恢复成题材库存列表


## 11. 相关阅读

- `docs/dragon-review-source-walkthrough.md`
- `docs/dragon-review-case-replay-templates.md`
- `docs/dragon-review-v4-cleanup-2026-04-22.md`
- `docs/stock-hotness-module-guide.md`
- `docs/stock-hotness-tuning-manual.md`
