# 真龙复盘 V4 清理说明

## 1. 文档目的

这份文档记录的是 V4 落地阶段做过的结构性清理，方便后续维护者理解为什么很多旧字段和旧命名不能再回来了。


## 2. 这次清理的核心目标

不是“升级旧龙头分析器”，而是彻底切断下面这条旧路径：

- 分数高
  -> 级别高
  -> 视为龙头

V4 改成：

- 先建战场
- 再缩候选池
- 再过四道门
- 再做战场内 duel
- 先给 `authority`
- 再给 `role`


## 3. 命名层清理

### 3.1 为什么不再用 `leader-review`

`leader-review` 容易让语义变形，而且和“真龙复盘”不统一。

统一后的口径是：

- 服务目录：`src/services/dragon/`
- 服务实例：`dragonReviewService`
- 结果类型：`DragonReviewResult`

### 3.2 为什么旧别名必须清掉

如果同时保留：

- `leaderReviewService`
- `dragonReviewService`

很容易出现：

- 同一份结果两套入口
- 调试日志混乱
- 刷新链依赖配置不一致


## 4. 字段层清理

以下旧字段不能再参与龙头结论：

- `leaderScore`
- `leaderLevel`
- `isSectorLeader`

原因很简单：

- 它们来自旧打分器
- 语义上和 V4 的 `authority / role / battlefields` 不兼容
- 会让旧逻辑借尸还魂


## 5. 面板层清理

龙头相关页面必须统一成真龙复盘口径，不允许再混用旧术语。

这意味着：

- 不直接显示旧分数
- 不直接显示旧级别
- 不把高标榜叫成龙头榜
- 不把热度榜当成领导权榜


## 6. 导出层清理

导出结构必须围绕复盘结果，而不是旧龙头筛选结果。

导出优先字段：

- `marketCore`
- `trueLeaders`
- `heightBoard`
- `attentionBoard`
- `pseudoLeaderGraveyard`
- `battlefields`
- `transitions`
- `summaryLines`


## 7. 快照层清理

真龙模块不直接读旧散装字段，而是尽可能走快照体系。

原因：

- 可回放
- 可重建
- 可复盘
- 多次重跑结果更稳定


## 8. 热度层清理

个股热度不是直接照搬八合一热榜平均排名。

正确结构应该是：

- 个股热度模块独立
- `hotness` 和 `themeHeat` 分层
- 真龙模块只消费结果，不直接在里面重造热度公式


## 9. 这一版之后不该再做的事

1. 不要再给真龙模块加“总分”
2. 不要再让旧 `leaderScore` 参与任何龙头输出
3. 不要把风格标签直接当题材战场
4. 不要把所有高位票都叫高标核心
5. 不要把所有高热票都叫情绪龙头


## 10. 关联文档

- `docs/dragon-review-maintenance-guide.md`
- `docs/dragon-review-source-walkthrough.md`
- `docs/dragon-review-case-replay-templates.md`
