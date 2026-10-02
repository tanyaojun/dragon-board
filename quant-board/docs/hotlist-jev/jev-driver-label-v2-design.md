# jev 涨停打标 v2 设计（韭研弹药版，2026-10-02 确认稿）

**性质**：brainstorming 产出（四项裁决：目标=先修复验证再谈接线 / 节奏=试点先行 / 方案=三轴搭车版 / 判定只用心照链命中子集）。
**背景**：阶段3 全窗报告（phase3-driver-report.md）判定 INSUFFICIENT——驱动分组轴是真信号（Kruskal p=0.0007、连板率极差 19.5pct），但 Noul（催化-主业匹配）轴废了：低组(<0.3) 仅 2.7%，IQR 仅 0.19，高低组差 0.44pct p=0.30 不显著。伤根已定位：旧叙事仅 285 字（THS reason 106 字+题材映射截断），jev 不知道公司主业是什么，只能把几乎全部股票打在 0.7 附近。
**弹药**：jiuyan_action 9 月回填 21 天 1516 只涨停股，异动解析（expound）覆盖率 100%，每条约 440 字结构化列点：催化事件（带日期）+ 公司既有主业描述 + 参股/子公司关系——恰好补上 Noul 轴缺失的原料。

## 0. 侦察事实（2026-10-02 实测）

- jiuyan_action final 21 天：每日 41~110 只（中位 69）；`day`（连板高度）分布：首板 1147 / 2板 140 / 3板 79 / ≥4板 150；`time`（首次涨停时间）09:25 一字板 → 15:00 尾盘板。
- `code` 带交易所前缀（sh600825），剥前缀后与 snapshot_stock_rows join 率 **72.8%**（1103/1516）——27% 是"涨停但未进热榜"的股票。
- 旧调用成本（hotlist_jev_driver_labels.usage）：input≈966 + output≈99 tokens/次，model jev-1.13.0。叙事加长到 ~500 字后按 ~1400 tokens/次估算。
- 韭研解析可直接替代旧叙事的全部原料（THS reason + 题材映射），旧字段不再喂。

## 1. 目标与判定门（预登记，先冻结再开火）

主目标=修复 Noul 轴；副目标=复验驱动分组轴。三门：

| 门 | 判据 | 对旧链基线 |
|---|---|---|
| 门1 Noul 修复（主） | 分布展开：IQR≥0.30 且低组(<0.3)占比≥15%；且 高组(>0.7)−低组(<0.3) 次日 pct 差≥2pct 方向为正 且 Mann-Whitney p<0.05 | 旧链 IQR 0.19、低组 2.7%、差 0.44pct p=0.30 |
| 门2 驱动分组复验 | Kruskal p<0.05（n≥8 组）且 连板率极差≥15pct | 阶段3 全窗 p=0.0007 / 极差 19.5pct |
| 门3 freshness 增值 | 观察项不设硬门：三类分布 + 与次日表现方向一致性 | 无 |

附**迁移矩阵**（净效应测量）：同股同日新旧 driver_type 混淆矩阵 + Noul 分位对比——直接回答"韭研原料改变了 jev 哪些判断"。

**单月市况风险预登记**：9 月是缩量市（N15 九月读数 p=0.50 先例）。若门2 p 不显著但七类排序方向与阶段3 全窗一致 → INSUFFICIENT-扩窗复验（10 月弹药每日自动积累后终判），不判 REJECT。门1 不依赖市况分组，9 月样本足够判。

## 2. 口径

- **population** = 韭研当日 final 全量涨停名单（含未进热榜的 27%——标签库要完整；打标时"未进热榜"如实写入叙事，本身是判别信号）。
- **判定语料** = 心照链命中子集（有次日 snapshot_stock_rows pctChange 的部分，72.8%），与阶段3 口径连续。
- 次日表现口径沿用阶段3：次日最晚槽 pctChange；连板近似=次日 pct≥9.8；|次日pct|>21 剔除（除权）。

## 3. 叙事构建（jiuyan_action → 部队口粮）

```
新华传媒（600825）：7天7板，首次涨停 09:25:00，热榜第3名，板块：公告。
异动解析（韭研公社）：
{expound 全文，约 440 字，催化事件逐条+公司主业描述}
```

- 连板高度：`day≥2` → `{day}天{day}板`；`day` 缺失 → `首板`（fail-visible 如实标注，不伪造）。
- 涨停时间：`time` 空 → `涨停时间未提供`。
- 热榜排名：剥前缀 code 当日快照链取最优（min）rank；未命中 → `未进热榜`。
- 旧 THS reason 与题材映射**不再喂**（expound 已覆盖，省 token）。
- 落点：`backend/analysis/hotlist/jev_state.py` 新函数 `build_jiuyan_label_narrative`，与旧 `build_driver_label_narrative` 并列。

## 4. 任务派发（runner）

- 新脚本 `backend/operations/jev_label_jiuyan.py`，旧 `jev_label_driver.py` 一字不动。
- 落库新集合 `hotlist_jev_driver_labels_v2`，`_id={date}:{code}`，origin=`driver_label_jiuyan`，幂等 upsert + `--skip-existing` 断点续跑（N15 37 小时事故教训）。
- 问题集三轴：
  1. `driver_type` 七选一——定义文案**原样沿用**旧链（可逐股对齐）；
  2. `business_match` (noul 0-1)——定义**原样沿用**；
  3. `catalyst_freshness` 新轴四选一：`fresh_catalyst`（今日新催化）/ `continuing`（老催化续命，近 3-30 天事件延续）/ `none`（无明确催化，资金情绪带动）/ `unclear`（信息不足，不强行归类——fail-visible）。
- 附加落库 `jiuyanContext`：{board, day, time, inHotlist, rank}；usage/latencyMs/model/status(ok|degraded) 沿用旧链结构。
- workers=2 线程池 + 单次重试，与旧链一致。

## 5. 战果判定报告

`backend/operations/jev_label_jiuyan_report.py` → `docs/hotlist-jev/phase3-jiuyan-v2-report.md`：

- 门1/门2/门3 读数 + 判定（PASS_CANDIDATE / INSUFFICIENT-扩窗 / REJECT，语义同阶段3）；
- 迁移矩阵（v1×v2 同股同日 driver_type 混淆表 + Noul 分位对比，仅重合日样本）；
- 全表自动生成，判定函数独立可测，**方向语义单测必须锁**（gate_verdict 反转事故教训）。

## 6. 节奏与成本账

| 阶段 | 动作 | 花费 |
|---|---|---|
| T0 | 构建器+runner+判定报告+测试落地，--dry-run 验证叙事 | 0 |
| T1 试点 | 3 天全量名单（09-05 108 只 + 09-18 61 只 + 09-30 64 只 = 233 只）→ 立即出 Noul 分布读数 | ≈33 万 tokens |
| 验收门 | 用户裁决：Noul 展开（IQR≥0.30 且低组≥15%）→ 放行 T2；未展开 → 调问题集再试点，全量不开火 | — |
| T2 全量 | 9 月剩余 18 天 ≈1283 只 | ≈210 万 tokens |
| T3 终判 | 三门报告+迁移矩阵 → 用户过目 | 0 |

日常增量接线（10 月起盘后自动打当日）不在本轮——验证过关后按"再谈接线"裁决另行立项。

## 7. 第一版边界

- 不动旧链集合与脚本；不接相位/题材/交易体系（验证过关另行立项）；不做 10 月增量调度。
- midday 采集暂不用于打标（final 为准）；jieyan 解析缺失日 fail-visible 跳过并日志披露，不伪造空跑成功。

## 8. 重铸试点预登记（2026-10-02，用户裁决"重铸 Noul"后先冻结再开火）

T1 试点战报（e2192bbf）：门1 REJECT——Noul 0-1 轴在韭研全量弹药下仍无方差（全量 IQR=0.20、<0.3 仅 2/266），与旧薄弹药（IQR=0.19）同形态；判定为**题目构造问题**（涨停催化几乎总与业务沾边，0-1 关联度天生无方差）。用户裁决重铸，product=`catalyst_depth`（催化落点深度五选一）替换 `business_match`（noul 0-1），driver_type 与 catalyst_freshness 原样不动（叙事不变、两轴不动 → pilot1/pilot2 同股同题可做稳定性对照）。

**判据（先冻结）**：

| 门 | 判据 | 说明 |
|---|---|---|
| 门A depth 轴方差（主） | 四个实质桶（core_main_business / new_growing_business / equity_or_affiliate / concept_assembly）每桶 n≥5，且实质桶中最大桶占比 <70%；insufficient_evidence 占比 ≤15%（逃生口不得滥用） | 手判 28 只分层样本预估分布 ≈50%/36%/7%/7% |
| 门B 驱动分组保留 | 沿用原门2：Kruskal p<0.05（n≥8 组）且连板率极差≥15pct；单月不显著但与阶段3 全窗排序 Spearman ρ≥0.5 一致 → INSUFFICIENT-扩窗 | driver_type 题目未动 |
| 稳定性对照 | pilot2 vs pilot1（备份集合 hotlist_jev_driver_labels_v2_pilot1，266 条）：driver_type / freshness sameShare——观察项不设硬门 | 叙事与题目均未动，同股应高复现 |
| 分桶次日方向 | catalyst_depth 各桶次日 pct 均值/连板率——观察项无硬门，让数据说话 | 1=持续性逻辑 / 2=期权弹性 / 3=情绪溢价 / 4=纯博弈 |

**判定映射**：门A+门B 全过=PASS_CANDIDATE（进入 T2 全量决策）；门A 过门B 不过=INSUFFICIENT（按方向一致性区分扩窗/存疑）；门A 不过=REJECT（重铸失败，题目回炉）。试点样本=同 pilot1 三天（09-07/09-18/09-30，266 只，≈37 万 tokens），重跑覆盖主集合前已备份 pilot1。
