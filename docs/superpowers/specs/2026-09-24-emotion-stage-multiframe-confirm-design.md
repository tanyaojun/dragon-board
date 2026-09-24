# 市场情绪阶段多帧确认平滑——设计规格

- 日期：2026-09-24
- 状态：**方向与默认值已裁决；对抗性审计已修订，待按实施计划执行**
- 关联：`2026-09-10-displaystatus-stage-projection-design.md`（stage 主轴口径）、`docs/热榜情绪分析器方案.md`（历史方案）
- 作者：AI 协作产出（brainstorming + 对抗性审计修订）

---

## 1. 核心目标

盘中“市场情绪阶段”（退潮/高潮/发酵/启动/冰点）目前按每槽最新帧截面独立判定，单槽指标突变会让阶段来回翻转。本立项增加当日多帧确认：候选阶段连续出现 `N` 个可观察槽位后才切换确认阶段，默认 `N=2`。原始截面判定必须逐槽保存、通过 API 返回并在界面可见；平滑只增加确认投影，不修正、覆盖或隐藏原始结果。范围限于 `hotlist_sentiment` 文档与消费投影，不修改 RankTrend golden、`resolve_stage` 级联条件或阈值。

## 2. 当前事实与问题

| 链路 | 当前事实 | 本立项处理 |
| --- | --- | --- |
| 截面判定 | `backend/analysis/hotlist/sentiment.py::resolve_stage` 按单槽 tape/money/expansion/risk/continuity 判五态 | 保持原样，输出写入 `rawStage` |
| 槽位写入 | collector、lazy compute、盘后 backfill、recompute 均可生成情绪文档 | 所有写口共用同一确认投影 |
| 历史/补写 | 任意过去槽位可以被重算，数据库中可能已存在更晚槽位 | 确认历史严格截断到当前槽之前，禁止未来数据污染 |
| 历史 EOD | 旧 EOD 文档可能使用日级 `_id`，但 `slotTime` 仍是 `HH:MM` | `_id` 与 `slotTime` 双条件排除 EOD |
| 日内轨迹 | 前端当前读取 `doc.stage` | 改为显式展示原始截面；确认阶段另行标注 |
| 手工导入 | `/api/hotlist-sentiment/ingest` 由 Pydantic 模型筛选字段 | 新字段必须进入模型，禁止静默丢弃 |

问题不是截面算法错误，而是“瞬时判断”和“日内确认趋势”共用一个字段。修订后的合同显式保留两条轨道：`rawStage` 是截面事实，`stage` 是可重放的确认投影。

## 3. 设计约束

1. **单一事实源**：`rawStage` 唯一来源仍是后端 `resolve_stage`；确认阶段只由后端纯函数从当日 `rawStage` 序列派生，前端不重算。
2. **fail-visible**：部分槽缺字段、历史读取失败、旧文档回退或非标准槽位不会删除已有文档，也不会让 API/UI 整体返回空结果；异常进入 `stageConfirmState.historyStatus` 和 `diagnostics`。
3. **因果顺序**：计算槽位 `T` 时只能消费 `slotTime < T` 的记录，再把本次 `T` 的截面追加一次。重试、乱序补写和历史回填不得读到未来槽位。
4. **同帧只计一次**：EOD 是锚定最新帧的日级投影，不是新的观察槽。若 EOD 锚定 `14:30`，确认序列只出现一次 `14:30`。
5. **独立轨道降级**：`stageShares` 缺失不影响 `rawStage` 确认；`rawStage` 缺失也不删除有效 `stageShares` 趋势点。
6. **回退等价**：`HOTLIST_STAGE_CONFIRM_SLOTS=1` 时，每个文档均有 `stage == rawStage`、`pending=false`。
7. **跨日重置**：昨日阶段不参与今日计数；每日首个可用槽直接确认。

## 4. 字段合同

`hotlist_sentiment` 槽位文档与 EOD 文档新增：

```jsonc
{
  "stage": "退潮",             // 确认阶段：顶部卡片与需要稳定阶段的消费方读取
  "rawStage": "高潮",          // 本帧截面判定：原始事实，必须保存和透传
  "stageConfirmState": {
    "pending": true,
    "pendingStage": "高潮",
    "pendingSince": "11:00",
    "confirmSlots": 2,
    "historyStatus": "complete"
  }
}
```

`historyStatus` 枚举：

| 值 | 含义 | 行为 |
| --- | --- | --- |
| `complete` | 历史槽均有 `rawStage` | 正常重放 |
| `empty` | 当日首槽，无历史 | 当前截面直接确认 |
| `legacy_fallback` | 至少一个旧槽无 `rawStage`，以旧 `stage` 作为当时截面 | 继续重放，同时写诊断 |
| `unavailable` | 历史读取异常 | 当前截面直接确认，同时写结构化诊断 |

当 `pending=false` 时，`pendingStage` 与 `pendingSince` 为 `null`。`pendingSince` 保留，因为它使候选起点无需依赖额外查询即可审计，也能判断连续槽证据是否成立。

现有 `summary`、`riskLevel`、`confidence`、`signals`、`warnings` 仍描述**本帧截面证据**，不参与平滑。前端必须把它们标成“当前截面证据/截面置信”，避免与确认阶段混为一谈。该选择不复制 `resolve_stage` 的摘要和风险算法，也不制造第二套确认口径。

旧文档兼容规则：

- UI 读取原始阶段时使用 `rawStage ?? stage`；这只是旧结构展示兼容，不写回数据库。
- ingest 未提供 `rawStage` 时允许保存旧结构，但不得伪造 `stageConfirmState`；新生产链生成的文档必须同时具有三字段。
- API 不得用空串、`0` 或默认阶段掩盖字段缺失。

## 5. 确认算法

输入是按交易槽位升序排列的 `(slotTime, rawStage)` 序列，且包含当前槽一次。

1. 空序列返回空确认结果，仅供防御；生产文档已有当前截面时不会走到该分支。
2. 第一条截面直接成为确认阶段。
3. 后续截面等于确认阶段时，清空候选。
4. 后续截面不同于确认阶段时：
   - 与当前候选相同：候选计数加一；
   - 与当前候选不同：从本槽开始新候选，`pendingSince=slotTime`；
   - 候选计数达到 `confirmSlots`：切换确认阶段并清空候选；
   - 未达到：保持原确认阶段并标记 pending。
5. 缺槽不插值、不惩罚，也不伪造槽；“连续”是连续可观察记录中的相同候选。
6. 非标准/无法排序的槽位仍保留在数据库和读口，但不进入确认派生，并在 `diagnostics` 标出位置与原因。

### 5.1 时间边界

槽位 `T` 的输入：

```text
当日合法槽位中 slotTime < T 的 rawStage（旧文档回退 stage） + 本次 T 的 rawStage
```

禁止采用“排除当前槽后读取当日全部文档”，因为数据库可能已经有 `T` 之后的记录。

EOD 的输入以 `anchoredSlotTime=T` 为边界：读取 `< T` 的历史，再追加 EOD 当前计算得到的 `T` 截面一次。若对应槽位文档已存在，EOD 与该槽在相同原始输入和阈值下必须得到相同的 `stage/rawStage/stageConfirmState`。

### 5.2 旧 EOD 排除

收集槽位历史时同时排除：

- `_id == "{datasetId}:{snapshotType}:{tradingDate}"`；
- `slotTime == "EOD"`。

这样既覆盖迁移后的 EOD 哨兵，也覆盖 `_id` 为日级、`slotTime` 仍是旧 `HH:MM` 的存量 EOD。

## 6. 读写与展示

### 6.1 后端写口

以下入口必须共用同一“历史收集 + 纯函数确认 + 文档投影”路径：

- `HotListSentimentComputeService._compute_and_persist`
- `compute_and_upsert_for_slot`
- `HotListSentimentBackfillService.run_for_date`
- `HotListSentimentBackfillService.run_for_date_slots`
- `/api/hotlist-sentiment/ingest` 字段透传

历史读取失败时仍保存本次原始截面和可计算字段；确认阶段退化为本次原始阶段，`historyStatus=unavailable`，并将异常原因加入 `diagnostics`。

### 6.2 API 与缓存

series/slots 继续返回数据库原文档，但响应合同变化后必须提升 Redis cache version，避免旧 `v1` 响应遮住新字段。API 测试需覆盖缓存未命中、缓存命中和 ingest 往返。

### 6.3 前端

- 顶部主阶段显示 `stage`（确认阶段）。
- pending 角标显示当前 `rawStage`、候选起点和阈值。
- 顶部 `summary/riskLevel/confidence` 标为当前截面证据。
- 日内轨迹的主阶段显示 `rawStage ?? stage`；当确认阶段不同，再显示“确认：stage”。
- 旧文档缺新字段时正常渲染，不能补成伪造的原始值或确认状态。

## 7. 影响文件

| 文件 | 职责 |
| --- | --- |
| `quant-board/backend/analysis/hotlist/stage_confirm.py` | 新增纯函数确认状态机；不修改 golden 截面级联 |
| `quant-board/backend/services/theme/hotlist_sentiment_compute.py` | 因果截断地收集日内两条独立轨道，返回历史质量状态 |
| `quant-board/backend/operations/hotlist_sentiment.py` | 文档投影及四个编排入口接线 |
| `quant-board/backend/api/hotlist_routes.py` | ingest 新字段与 series/slots 缓存版本 |
| `src/types/hotlistSentiment.ts` | 新字段类型合同 |
| `src/components/panels/DragonBreathPanel.vue` | 确认主值、原始轨迹、截面证据标签 |
| `quant-board/operations/replay_stage_confirm.py` | 从 `rawStage ?? stage` 回放并输出质量/延迟指标 |
| 相关后端、API、前端测试 | 锁定因果顺序、双轨保留和兼容行为 |

实现后还需同步检查 `quant-board/docs/database-migration-plan.md`、`architecture.md`、`api-cli.md`、`AI_COLLABORATION.md` 与 `docs/热榜情绪分析器方案.md`。

## 8. 验收标准

UI 改动交付前由主代理按项目级 Playwright/e2e 流程做真实浏览器验收：检查桌面和移动视口、关键字段、pending 交互、控制台错误和必要截图；单元测试与类型检查不能替代浏览器结果。

### 8.1 自动化合同

1. `A,A,B` 在阈值 2 下输出确认 `A`，pending 候选 `B`，起点为第三槽。
2. `A,A,B,B` 输出确认 `B`，pending 清空。
3. `A,B,C,C` 只确认 `C`；候选改变会重置计数。
4. 阈值 1 下每槽 `stage == rawStage`。
5. 重算 `10:00` 时，数据库中的 `11:00` 不得进入输入；写入顺序不改变 `10:00` 结果。
6. 旧 EOD 不得进入槽位序列；旧槽 `stage` 回退必须显式标为 `legacy_fallback`。
7. 有 `stageShares`、无 stage 的槽仍保留在日内趋势 `points`；有 stage、无 shares 的槽仍进入确认序列。
8. EOD 与其锚定槽同帧只计一次，并得到一致确认结果。
9. 历史读取异常仍写入本帧 rawStage、其他可计算字段和结构化诊断。
10. ingest、series、slots 与缓存命中响应均保留新字段。
11. UI 同时可观察确认阶段与原始截面，旧文档不报错。

### 8.2 历史回放

截至 2026-09-24，标准 `HH:MM` 槽位文档只覆盖 2026-09-07 起的 14 个交易日，不再表述为“110 天日内数据”。基线回放为 39 次原始切换、15 次确认切换，减少 61.5%；该结果仅证明抖动减少，不单独证明趋势识别正确。

上线前报告必须同时给出：

- 原始切换数、确认切换数与减少比例；
- 每次确认切换的连续证据槽；
- 最大/平均确认延迟，默认阈值 2 时应为 1 个可观察槽；
- 单槽候选被吸收次数；
- legacy fallback、缺字段、非标准槽、读取失败计数；
- 阈值 1 与原始序列逐槽完全一致；
- 打乱写入顺序后按槽重算的结果与顺序写入一致。

历史回放脚本在新结构上线后必须优先读取 `rawStage`，只对旧文档回退 `stage`，不能把已平滑的 `stage` 再当作原始真值。

## 9. 回退与迁移

- 即时逻辑回退：`HOTLIST_STAGE_CONFIRM_SLOTS=1`，保留新字段以便观察与审计。
- 结构回退：消费者继续兼容旧文档；不批量删除字段。
- 历史迁移：按交易日、按标准槽位升序重算。即便库中已有未来槽，时间上界仍保证因果一致。
- 生产回填前先 dry-run 输出日期、槽位数、legacy fallback 与异常统计；回填不因单槽异常丢弃其他记录。

## 10. 已裁决事项

1. 采用后端文档层确认投影。
2. 默认 `confirmSlots=2`，环境变量可调。
3. 原始截面与确认阶段双轨保存、双轨可见。
4. 重放式状态机以当前槽为因果边界；EOD 同帧不重复计数。
5. `pendingSince` 保留在合同中。
6. 回放基线通过抖动减少门槛，但实施仍以本规格全部验收项为准。
