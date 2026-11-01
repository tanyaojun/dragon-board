# 板块节点 V2d 预登记：量能锚影子列 + 池外晋级影子列 + 首板分支收紧（v3 判据）

> 2026-10-30 立项。背景：sector-nodes 二期审计盘点（4 项悬空）后用户两项裁决：
> ①量能锚 + 池外晋级**合并一代际**影子实施；②首板分支「数学平凡真」**本轮一并收紧**
> （SECTOR_NODE_VERSION 升 v3，用户批准=本预登记批准，同 v2-criteria 流程）。
> 判据文本以 `analysis/hotlist/sector_nodes.py::classify_board_day` 为逐字事实
> （jev P0-1 纪律：改代码必须同步回改本文）。
> 单位校准实测（2026-10-31，对拍 10-30 最新交易日棒）：本地 vipdoc amount 与线上 pytdx amount **同单位（元）、
> 重叠日逐值相同**（600519/002242/300750 三股对拍）；vol 仍差 ×100（手 vs 股，既有记载）。

## 依据数据

- **量能锚缺口**：V2b 回放研究（`sector-agg-replay-study-20261024.md` §三）已证红盘率
  是佐证维度非充分判据；PDF「巨额投入」锚自 V2 起 `_daily_bars` 无 amount 字段而缺席，
  为二期最大数据缺口。
- **池外晋级影响面扩大**：v1 §六.3 审计 P3 登记的「晋级归属静默丢弃」在 v2 资金先手
  分支（同样消费 promN）后不再是纯观察项——promN 系统性偏小 → 退潮更易命中、
  弱转强（含资金先手分支）更难命中。
- **首板平凡真实测**：v1 §七.4 登记，回填 33 日实测 2 次「昨日首板=0」命中
  （09-30 机器人、10-13 大消费）均为今日首板 ≥3 的健康换血。

## 条款 1：量能锚影子列（aggN10.amountSum，不进判据）

- 数据管道：`_local_daily_bars` 取 `<IIIIIfII` 布局 index5 amount；`_online_daily_bars`
  取 pytdx df `amount`；线上补尾合并带 amount，系数走重叠日期中位比值
  （`_online_amount_factor`，兜底 1.0 标 assumed，provenance `_TAIL_AMOUNT_SOURCE`，
  溯源并入 `bars_source_provenance().tailAmountCalib`）。
- 统计：`sector_agg.aggregate_day` 新增 amountSum（当日有棒成员当日成交额合计，元）、
  amountQuotedN、amountAbsentN（棒在而 amount 缺，不伪 0）；缺棒成员剔除同 missingN 惯例。
- 落库：rows[].aggN10 增 amountSum/amountQuotedN/amountAbsentN；`AGG_VERSION="2026-10-31a"`。
- 前端：rv-nodes 展开卡加「成交额（亿元，N10 成员）」行 + absentN 披露；不参与节点徽章。
- **不进判据**（改门须新代际 + 用户逐条批准）。

## 条款 2：池外晋级影子列（rows[].promOutOfPool，不进判据）

- `_promotion_by_board`：昨日封板但不在昨日韭研 pool 的晋级股不再 `continue` 丢弃，
  按**今日韭研 cur_pool 首个板块**归属（与 prev pool 同款「首个板块」口径镜像）；
  今日池亦无 → `unattributed` 名单进 meta（fail-visible，不硬塞板块行）。
- rows[] 增 promOutOfPoolN / promOutOfPoolGe2；>0 时 notes 加
  「池外晋级 N 家（封板但未入昨日韭研池，按今日池首板块归属）」。
- meta 增 promOutOfPoolTotal（= 板块归属 + 未归属，unattributed 也是池外晋级）/ 
  promOutOfPoolUnattributed。in-pool promN/promGe2 逐字不变。
- promN 判据语义（是否并入池外家数）**留待影子对照后新代际裁决**，本代际不动。

## 条款 3：弱转强首板分支收紧（判据改动，SECTOR_NODE_VERSION="v3"，已批准）

v1 首板分支 `first_ok`：

> 原：`prev_shape_first is not None and first >= 2 * prev_shape_first`
> 新：`prev_shape_first is not None and prev_shape_first >= 1 and first >= max(2 * prev_shape_first, 3)`

- `prev_first≥1` 消除「昨日首板=0 时 ×2 恒真、龙头确认被架空」的平凡真（v1 §七.4）；
- 「今日首板≥3」下限保留两条实测健康换血样本（09-30 机器人、10-13 大消费）；
- 龙头续板分支不受影响；basis 文本注明「V2d 收紧」可区分。
- 影响面实测前置：全史重跑对拍（零 token），预期改档≈0；若 >0 逐组列表人工过目后再回填。
- 冻结件回改：v1 §七.4 勘误闭环（本预登记落地即闭环）。

## 影响面实测（2026-10-31 回填后对账，v2 快照 vs v3 重算，2306 board-days）

- **收紧直接改档 2 处（0.09%，预期 ≈0 达标）**：06-15 公告 wzs→weakening、
  09-30 机器人 wzs→normal——均为「龙头断板 + 昨日首板=0 恒真」的平凡真路径被裁
  （09-30 机器人正是 v1 §七.4 登记样本之一，收紧确实改变该边界语义，已获批准）。
  首板分支收紧后存活 15 处（含 10-13 大消费）；资金先手分支 61 处零回归。
- **链传导 2 处**：06-16 公告（昨日节点链变化后资金先手命中）、06-12 公告（mainline
  分位条件，原料驱动）。
- **原料漂移 16 处（与判据文本无关）**：源池（THS/韭研 final）在原 v2 回填（10-24/25）
  后有更新（count hist / 晋级链 / 分位随之变化），典型：09-04/09-07 地产行从缺失到
  在场（池修复）、06-16 半导体 fermenting（n2 读数变化）。这些档位不涉 wzs 判据，
  节点链自愈；如对某组有异议可单日 `--day` 重算（回填幂等）。
- **量能影子列**：2278/2278 个 aggN10 可判行全部有 amountSum（含 degraded 日除外）。
- **池外晋级影子列**：全史 promOutOfPoolTotal=0、unattributed=0——「封板但未入昨日
  韭研池」的晋级股在现有数据下不存在，口径无影响面；影子列保留作前向观察。

## review 修复（2026-10-31 当轮，fresh-context reviewer 复审后逐项采纳）

- **P2-1**：`_online_daily_bars` 原把缺失/NaN amount 铸 0（`or 0`），使尾棒合并的
  「保留缺失」分支生产不可达、缺额尾棒以伪 0 混入 amountSum（违 §4.0）——改为
  **缺失/NaN 省略键**（`math.isnan` 守卫），与合并处注释语义对齐。
- **P2-2**：补两个解析缝测试——本地 lday `<IIIIIfII` index5=amount / index6=vol
  （打包字节 fixture）、线上 df amount 列取值（含 NaN/缺列省略键）。
- **P3-1**：注释统一 amountAbsentN（消 amountCoverage/amountMissingN 残留）。
- **P3-2**：随 P2-1 一并解决（NaN 不再穿透）。
- **P3-3**：test_jev_bars_online_tail fixture 清理补 `_TAIL_AMOUNT_SOURCE.clear()`。
- **P3-4**：promOutOfPoolTotal 定义并入 unattributed（上文条款 2 已改），
  补 settle_day meta 断言（链不可算 → None 不伪 0）+ Total 含未归属用例。

## 待裁项（登记不裁）

1. 量能锚/池外晋级进判据：凭影子分布与对照数据走新代际预登记。
2. jev 板块节点题（LLM 对照）：条件触发（规则试点与盘感分歧），继续挂起。
3. aggStatic 低关联过滤：等影子分布可看再裁。
4. 双日期源键错位 / 参照日缺失注记 elif 链（v1 §六.6/7）：低风险观察项，维持。

## 验收

- pytest 专项（全 mock，禁真实 TDX/jev 外呼）：本地 lday amount 解析、线上 df amount、
  amount factor、缺棒剔除不伪 0、amountSum 手算对拍；池外晋级分流/今日池归属/
  unattributed 披露/notes 触发；首板收紧 prev_first=0 不命中、prev_first=1 今日 2 不命中、
  今日 3 命中、龙头分支不受影响、既有 v2 分支零回归。
- 全史回填重算（量能 + 池外晋级 + v3 判据同批），改档对账后 API 抽查。
- 浏览器验收用户本人做（展开卡成交额行 + 池外晋级注记）。
