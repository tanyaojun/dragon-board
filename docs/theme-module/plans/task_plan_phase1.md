# Phase 1 实施计划：情绪相位 × 题材动量有效性（条件层第一个假设）

- 日期：2026-09-26
- 设计依据：`docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md` §5.3/§6.1 Track 因子线 Phase 1；R3 findings 的分层结果（市场状态主导收益）是本假设的直接动机。
- 研究假设（用户实盘经验 + §5.3）：**题材动量因子的有效性依赖情绪相位**——情绪有利期高动量题材延续占优，情绪退潮期动量失效或反转。
- 纪律：TDD；探索性结论不落默认；fail-visible（相位/情绪缺失日如实打标）；非交易时段运行。

## 接口事实（2026-09-26 实测，勿凭记忆修改）

1. **momentumScore**：daily hot_theme rows（7-06~09-24，13,433 行）覆盖 **100%**；change 同 100%。动量因子直接消费落库值，不重算。
2. **market_phase**：half_hour 15:00 帧 `rotationSummary.marketPhase`，53 天覆盖 39（74%）；daily 帧恒 unknown 勿用。R3 已实证 cooling 为窗内主导相位。
3. **limitSummary 槽位结构（本次探查实证，修正 R1 口径认知）**：half_hour 类型的 9 月帧 slotTime 只到 **15:00**（无 15:30）；R1 所称"15:30 收盘槽"在 **daily 类型**。逐槽 ztCount 有值率（9 月 18 天）：09:30 14/18、10:00 12/18、11:00 4/18、13:00 4/17、14:00 3/17、15:00 5/18——盘中 THS 源空洞多，回退必须跨类型合并。
4. **合并回退口径（本计划定版）**：`daily:15:30` 优先 → half_hour 尾盘倒序（15:00→…→11:00），**排除 09:30/10:00**（Phase 0 实证首槽 THS 池未建满 ztCount 偏低）。实测覆盖：9 月弱势段 **16/18**（R1 仅 8/18）、全窗 **38/54 交易日（70%）**。
5. **情绪核心连续变量**：炸板率 `zhaban.rate`（负向：越高越差）+ 连板高度 `continuousBoards.maxBoard`（正向）+ ztCount。方向在 runner 内显式声明。
6. **spearman**：`ranktrend/research/tier_monotonicity.py:234` 已有 `_spearman`（ranktrend 域私有）——题材域自写同口径纯函数（含并列平均秩），不跨域 import 私有函数。

## 非目标

- 不改采集器/写入链（limitSummary 回退是**研究读取口径**，写入侧原始状态照旧保存）；
- 不动 momentumScore 生产口径；不做参数扫描；不落任何默认值；
- Phase 2（拥挤度口径）、Phase 3（D2/D3/F1）不在本批。

## Task 1：情绪取数 + 秩相关小模块（TDD）

**文件**：`backend/analysis/theme/sentiment_slots.py`、`backend/analysis/theme/rank_ic.py`（新建）；测试 `quant-board/tests/test_theme_sentiment_slots.py`（新建，两模块合并一个测试文件）。

1. `pick_sentiment_snapshot(daily_1530, half_hour_slots) -> dict`：
   - 输入：该日 daily 15:30 帧 limitSummary（或 None）+ 该日 half_hour 各槽 limitSummary 列表 `[(slotTime, limitSummary)]`；
   - 回退序：daily:15:30 → half_hour 槽位倒序（排除 09:30/10:00）→ 不可得 `{"status": "insufficient"}`；
   - 输出：`{"status": "ok", "source": "daily:15:30|half_hour:15:00|...", "zhabanRate", "maxBoard", "ztCount"}`，字段缺失保持 None 不伪造；
   - limitSummary 结构容错：`zhaban.rate`/`zhaban.count`、`continuousBoards.maxBoard`、顶层 `ztCount` 兜底（与探查脚本同口径）。
2. `spearman_rank_ic(xs, ys) -> float | None`：并列平均秩 + Pearson on ranks；n<2 或全并列返回 None；已知答案校验（完全单调=±1.0、反序=-1.0、并列秩场景、n<2 None）。

**验收**：`pytest tests/test_theme_sentiment_slots.py -q` 全绿。

## Task 2：Phase 1 验证 runner + 真实数据运行

**文件**：`backend/operations/diagnose_sentiment_momentum_phase1.py`（新建，范式同 diagnose_theme_r3_variants.py）；产物 `data/reports/theme-phase1-sentiment-momentum.json`（gitignore）。

1. **样本构建**：daily rows（momentumScore/change，54 天）→ per day 横截面 momentumScore 五分位（Q1 低→Q5 高）；前向收益 = 次日该题材等权 change（T+1，末日无次日则丢弃并计数）。
2. **条件分组两维**：
   - 维 A 情绪相位：market_phase（Task 2 内取 half_hour 15:00 帧）；None 日单列 `phase_unknown`；
   - 维 B 情绪强度：pick_sentiment_snapshot 的 zhabanRate，按窗内中位数分高/低两组（炸板率高=情绪差，方向显式声明）；maxBoard/ztCount 作附加诊断输出。
3. **统计输出**（per 组）：
   - Q5−Q1 日均收益差与胜率（Q5 均值 > Q1 均值 的天数占比）；
   - spearman rank IC（momentumScore vs T+1 change，per day）均值与 IC>0 天数占比；
   - 每组 n<3 天 → `insufficient_sample` 打标（fail-visible，不输出 0）。
4. **判定语义（探索性）**：假设"有利相位（rising/climax/低炸板率组）Q5−Q1 差与 IC 显著高于不利相位（cooling/ice/高炸板率组）"——只报告方向与幅度差异，不做显著性检验声明、不落默认。
5. 附加输出：两维覆盖率核对（与接口事实比对）、Q5−Q1 差的按月分布（极端月感知）。

**验收**：真实数据跑通落 JSON；控制台摘要打印两维分组对照表。

## Task 3：findings 报告 + 文档回写 + 记忆

1. `docs/theme-module/2026-09-26-phase1-findings.md`：假设裁决（方向性）、两维对照、覆盖率、样本量声明、局限；
2. 设计文档 §10 追加 Phase 1 完成状态与结论；
3. 更新持久记忆 `themetrend-upgrade-plan.md`；
4. 提交分组：Task 1 模块 / Task 2 runner / Task 3 报告，各自独立 commit。

## 风险与回退

- **相位组极不平衡**（窗内 cooling 主导、climax/rising 组样本极小）→ 如实报告 insufficient，Phase 1 结论强度以 cooling vs 其余组对比为主；
- **limitSummary 回退槽的盘中值代表性**（11:00-14:30 有值帧的 ztCount 反映盘中池状态而非收盘）→ source 字段逐日落报告，消费方可见取数来源；
- 回退为纯新增文件 + 新 runner，回退 = revert 对应提交，无既有行为耦合。
