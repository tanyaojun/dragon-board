# 五维综合评分口径唯一化：前端全面消费后端 golden（compScore/compRank/avgRankNum 双实现收敛）设计

> 状态：设计已确认（2026-09-21 用户裁决方向 A「口径唯一」+ 六节设计整体通过）；实施完成（2026-09-21，实施计划 `docs/superpowers/plans/2026-09-21-comprehensive-rank-golden-convergence.md`，提交 c7119887/3ceadf54/76ab655b/e0e24b6b，`pnpm test` 134 文件 1087 用例、`pnpm test:ranktrend` 171 用例、两类 typecheck 全绿）。实施期勘误见 §4 末尾注。
> 触发：`docs/single-source-of-truth-architecture.md` §3 盘点表第 6 行——五维综合评分是 2026-09-21 源码盘点确认的唯一活跃双源；§5 P1 要求裁决后立项。
> 前序：`docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md`（池源替换已上线实测，帧行自带后端 golden 排名，是本方案的数据前提）。
> 依据：`AGENTS.md` §4.1/§4.2/§10/§11、`skills/single-source-of-truth/SKILL.md`（三问见 §1）、`skills/fail-visible-data-pipelines/SKILL.md`（降级语义见 §4）。

## 1. 背景与双源现状（2026-09-21 逐行复核）

同一公式、两处实现、权重逐值一致（0.45/0.25/0.1/0.12/0.08，OPTIMAL_TURNOVER=15，TURNOVER_SIGMA=10）：

| 侧 | 位置 | 状态 |
| --- | --- | --- |
| 前端 | `src/services/dataLoader/ComprehensiveRankEngine.ts`（均榜 `calculateAverageRank` L63-95 + 五维 `calculateComprehensiveRanks` L97-150 + `rankMergedStocks` L152-170），经 `StockMergeCoordinator.ts:88` 每次 merge 活跃调用 | 列表排名 100% 来源；2026-08-24 回滚注记（`StockMergeCoordinator.ts:84-88`） |
| 后端（golden） | `quant-board/backend/analysis/ranktrend/ranking/comprehensive_rank.py` `compute_comprehensive_scores`（`snapshot_collector/providers.py:1047` `_rank_rows` 调用入库；`ranktrend/__init__.py` legacy 别名映射 `comprehensive_rank` → `.ranking.comprehensive_rank`） | 快照/研究/回测链唯一口径 |

关键事实：09-21 池源替换后帧行已自带 golden 排名字段，但 `framePoolSource.ts:83-99` `buildFrameSeedStock` **有意丢弃**它们（排名字段保持占位，注释记录 08-24 回滚口径）；`RankTrendSignalService.ts:222-224` 确认 analyze 不注入/回填。08-24 回滚理由「后端覆盖不全导致历史无记录股票无排名」已被池源替换消解（列表 membership = 帧池全集）。

**单一事实源三问（skill 门禁）**：

1. 消除还是保留双源？——**彻底消除**（方向 A，用户裁决）：前端删除本地计算，任何链路只认后端 golden。
2. 权威侧与收敛路径？——权威侧 = QuantBoard 后端快照行；收敛路径 = 帧池种子行透传 golden 字段，前端零计算；一次到位，无过渡双轨。
3. 「前端零改动」是否原理性不可达？——不适用：本方案的前端改动就是目标本身（翻转 `buildFrameSeedStock` 占位语义 + 删引擎）。

## 2. 目标与非目标

**目标**

- 前端列表 compScore/compRank/rank/avgRankNum 与后端快照行**同口径同代际**（展示 = 快照历史 = 回测研究）。
- 删除 `ComprehensiveRankEngine.ts` 全部计算链及测试；列表排序改按 golden compRank 稳定排序。
- 降级链（`hotlist-merged` / `startup-bundle`）行**无排名**：不本地伪造，原始数据 + provenance/qualityFlags 如实透出（fail-visible）。

**非目标**

- 不改后端算法、权重、快照采集节奏与任何 API/集合（复用现有 frames/stock-rows 字段，无新增——「没有新接口能不能工作」：能）。
- 不改个股热度 8 分量结构（仅 avgRankNum 输入切换为 golden 值）。
- 不动 09-21 池源替换的 provenance/降级/注脚机制。
- 不触碰用户未提交文件（`DataTable.vue` 及其测试等，见 git status）；字段名不变，DataTable 消费不受影响。

## 3. 架构与数据流改造点（全部在根项目 `src/`）

| # | 改造点 | 说明 |
| --- | --- | --- |
| 1 | `framePoolSource.ts` `buildFrameSeedStock` | 透传 golden 排名字段：`avgRankNum`、`compScore`、`compRank`、`platforms`、`missingFields`、`qualityFlags`；`avgRank` 展示串由 golden `avgRankNum` 格式化派生（纯展示格式化，非计算）。**字段映射：前端 `rank` := 后端 `compRank`**（两者语义本就相同——compScore 降序 + code 稳定序——映射后 `rank` 消费方零改动；注意不可照抄后端 `rank` 字段，后端 `rank` 是 avgRankNum 序，语义不同） |
| 2 | `StockMergeCoordinator.ts` | 删除 `rankMergedStocks` 调用；8 平台 rank 字段（emRank 等）保留实时合并但降级为**纯展示字段**（原始平台数据，非计算输入）；`getRankField` 迁移为本文件内部工具（rg 确认唯一消费方）；merge 后排序按 `compRank ?? DEFAULT_RANK` + code 稳定排序；08-24 回滚注记改写为收敛注记 |
| 3 | `RankTrendSignalService.ts:222-224` | 注记同步为收敛口径（保持不覆盖本地值的行为，此时「本地值」已即 golden 值） |
| 4 | 排序消费方 | `ui.ts` compRank 排序字段、`stock.ts`（`?? 9999`）、`FrameNormalizer`（`|| 999`）、`CandidatePoolBuilder`/`BattlefieldBuilder`（`|| 999`）等既有回退保留不动 |
| 5 | `framePoolSource.ts` `applyGoldenFieldsToMerged`（审查 C1 修复，2026-09-21） | 帧池模式每轮 merge 后用最新帧行**刷新既有行** golden 字段子集——种子只补缺失会使 golden 冻结在首次入池帧、降级恢复后不回填；golden 字段清单单一源 `applyGoldenFields`（种子与刷新共用，防两处漂移） |

## 4. 降级语义（后端/帧池不可用，fail-visible）

- 降级行 compRank/compScore/avgRankNum 保持 undefined，**不伪造、不本地重算**；名称/价格/8 平台 rank 等原始数据照常展示。
- 可见性三层：`poolSource` provenance 批级标记（已有）+ 行级 `qualityFlags`/`missingFields`（golden 行自带；降级行如实缺省）+ 面板注脚复用 09-21 机制，注明「降级期间无综合排名」。
- **NaN 加固**（本方案唯一新增防御）：`BusinessRules.ts:149` `100 - stock.compRank * 5` 在 compRank undefined 时产生 NaN——改显式 `?? DEFAULT_RANK` 回退，先写失败测试再修（TDD）。其余消费方既有 `|| 999`/`?? 9999`/`isFinite` 回退逐一 rg 复核，实施时以测试锁定。
- hotness：`StockHotnessCalculator` 已有 `isValidRank` 守卫，avgRankNum 缺失时 avgRank 分量按无效剔除（既有测试确认，不新增结构）。
- 降级模式 `platforms` 保持 `createEmptyMergedStock` 占位 0（引擎已删不再重算），hotness 的 platformCoverage 分量随之归零；`poolSource` provenance 已打标，影响随降级面如实透出（审查 M2 补记）。

> **实施与审查期勘误（2026-09-21）**
>
> 1. **BusinessRules NaN 防御未实施**：核实该文件被 `tsconfig.app.json` 显式排除且全仓库零 import（`StockContext` 亦未声明 `compRank`），属未挂载历史遗留文件，非活跃消费方；活跃 compRank 消费方（`stores/stock.ts`、`dragon/CandidatePoolBuilder`、`BattlefieldBuilder`、`FrameNormalizer`、`config/factors`、`exportService`、`DataFreshness`）已逐一核实全部自带安全回退（`|| 999`/`?? 9999`/`isFinite` 守卫），不存在 NaN 污染路径。此为设计阶段盘点疏漏（rg 命中即列为消费面，未核实排除清单）。
> 2. **§8 代价模型修正（审查 C1，Critical）**：初版实现种子只补缺失，golden 实际冻结在股票首次入池帧、降级恢复后不回填——「帧内冻结 ≤30min」不成立（实为会话内冻结）。已修复：帧池模式每轮 merge 后以最新帧行刷新既有行 golden 字段子集（`applyGoldenFieldsToMerged`，§3 改造点 5），裁决代价口径据此成立；真实行刷新语义由单测锁定。
> 3. **fundPenetration 占位口径**：种子行缺失时保持 `createEmptyMergedStock` 既有占位 0（非 undefined），与「缺失不伪造」的边界一致——占位 0 是引擎时代既有约定，不属本轮伪造。
> 4. **§3 改造点 4 路径勘误**：排序消费方 `ui.ts` 实际为 `src/stores/ui.ts`。
> 5. **spec §6.1 真实帧 fixture 在初版实施中被自备用例替代**（审查 I1），已补真实帧合同锁（见 §6.1 落地记录）。

## 5. 删除与保留清单（rg 逐符号核实）

- **删除**：`ComprehensiveRankEngine.ts` + `__tests__/ComprehensiveRankEngine.test.ts`（逐文件删除）；`src/types/config.ts` 的 `COMPREHENSIVE_WEIGHTS`/`PENALTY_SCORE`/`OPTIMAL_TURNOVER`/`TURNOVER_SIGMA`（消费方仅引擎 + 定义 + `config.test.ts`）及 `types/index.ts` 对应 re-export；`config.test.ts` 对应用例。
- **保留**：`DEFAULT_RANK`（`framePoolSource` 占位、排序回退、coordinator 仍消费）；hotness/factors/algorithms 配置结构。
- 注：禁批量删除规则适用——逐个明确路径删除；整批改动单批提交、可 `git revert` 回退。

## 6. 测试与对齐验证（TDD：先锁行为再改）

1. `framePoolSource.test.ts`：seed 行透传 golden 字段——用真实 frames API 一帧做 fixture 逐位断言（golden 对齐验证：前端读到 = 后端行）。【落地记录 2026-09-21：已用当日 15:00 收盘帧真实行（600127/002185/000636）做合同锁 fixture，含种子逐位一致与既有行刷新逐位一致两组用例（审查 I1 修复）】
2. 合并链：帧池模式 compRank 来自后端行、无本地重算；`compRank ?? DEFAULT_RANK` + code 稳定排序。
3. 降级行：无排名不被伪造、provenance/qualityFlags 可诊断、消费方回退无 NaN（含 `BusinessRules` 新用例，先红后绿）。
4. hotness：avgRankNum 缺失时 8 分量仍可计算且 avgRank 分量剔除。
5. 验证命令：`pnpm test` + `pnpm test:ranktrend` + `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。QuantBoard 后端零改动，不跑 pytest。

## 7. 文档同步与上线验证

- `docs/single-source-of-truth-architecture.md`：§3 表第 6 行 → ✅ 已收敛（2026-09-21 用户裁决方向 A）；§5 P1 标记完成并记录裁决。
- `StockMergeCoordinator` / `RankTrendSignalService` 注记同批更新（收敛口径与裁决日期）。
- **首个交易日人工验证**（AGENTS §11 必查清单）：盘中对比前端列表 compRank 与 `GET /api/snapshots/frames` 同帧值逐位一致；观察降级注脚如实透出；不只看页面渲染，须对账数据本体。

## 8. 风险声明

- 主列表排名帧内冻结 ≤30 分钟（用户裁决接受的代价）；热榜轮动期间排名不动，价格/涨跌幅仍实时。
- 删除面较大（引擎 + 四常量 + 测试），但均为口径唯一化的必然后果；字段名不变，面板/表格消费零改动；回退方式 = 单批提交 `git revert`。
- `DataTable.vue` 等用户未提交文件不触碰；若其测试引用被删常量（当前 rg 显示无），实施时发现再呈报。
