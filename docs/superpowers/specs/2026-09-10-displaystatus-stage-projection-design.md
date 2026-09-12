# displayStatus 退役为纯投影（stage 主轴）设计

> 状态：设计已确认（2026-09-10 用户逐节确认：后端契约 / 计数契约 / 前端与验收）
> 触发：热榜池 8 类状态与个股生命周期 5 态**未完全映射** —— 实测 978 帧 / 220,736 行证明 `label` 无法反推 `stage`
> 上游裁决：`docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md` **§10**（本设计是**落地 §10**，不是新方向）
> 配套实施计划：由 writing-plans 生成（本 spec 通过用户评审后）

## 1. 问题与根因

### 1.1 实测证据（`snapshot_analysis` 全量聚合，978 帧 / 220,736 行）

| `cycle.stage` \ `displayStatus.label` | 转弱预警 | 样本不足 | 强资确认 | 高位拥挤 | 点火观察 | 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| cooling | 173,100 | 33,136 | 8,364 | — | — | 214,608 |
| reversal | 5,877 | 26 | — | — | — | 5,903 |
| crowded | 1,285 | 45 | — | 1,877 | — | 3,207 |
| ignition | — | 191 | — | — | 104 | 295 |
| expansion | — | — | — | — | — | **0** |

三条硬事实：

1. **`label` 反推不出 `stage`**：`样本不足` 跨 4 个 stage、`转弱预警` 跨 3 个 → 8 类的信息量**低于** 5 态。
2. **8 类里 3 类是死类**：`主升确认` / `资金背离` / `新入观察` 在 220,736 行中**一次未出现**；`expansion` 态本身也从未产出。
3. **修正层做成了"覆盖"而非"叠加"**：`cooling` 的 33,136 行被样本门替换成"样本不足"、`crowded` 的 1,285 行被风险层替换成"转弱预警" → **stage 信息被丢弃**。

### 1.2 根因：同一份 spec 两套口径，实现跟了被推翻的那套

| 位置 | 内容 | 性质 |
| --- | --- | --- |
| 原 spec §3（L30-63） | 三层修正级联（样本门 → 风险层 → stage 主轴 → 兜底）→ 8 类 | **旧方案** |
| 原 spec §10（L289+） | displayStatus 退役为纯投影；`label ≡ STAGE_LABELS[stage]`；6 格分布；"不做 modifiers、不做第七八类" | **最终裁决** |
| 实施 plan L7 | 直接引用 §3 的级联表述 | 导致实现停在 §3 |

**§3 从未被标注废弃**，是实现偏离的直接原因。本设计落地 §10 的同时，给 §3 补废弃标注（已在本批完成）。

### 1.3 为什么"补一张映射表"救不了

原 spec §10.1 原文：

> 8 类中全部语义在 analysis 里本就有一等字段归属：阶段 → `cycle.stage`；强资承接 → `zlje/zljzb` + `volumePrice.signalTier`；风险升级/存疑 → `observation.synergy.state`；样本质量 → `meta.sampleQuality`。**把一等字段复制成第二套"状态分类"就是病灶本身。**

因此方向是**删除分类层**，不是重新设计映射。

## 2. 目标与非目标

**目标**

- `displayStatus` 成为 `cycle.stage` 的**纯投影**（不再有独立分类逻辑）。
- 每行满足 `label == STAGE_LABELS[stage]`（`stage` 缺失/非法 → `"无阶段"`）。
- 分布改为 **6 格** `stageCounts`，恒等式 `sum(stageCounts) == 全池行数` 成立。
- 后续生命周期引擎优化不再改变展示分布（展示层无自有逻辑）。

**非目标**

- **不改** `cycle` / `candidateTier` / `synergy` 引擎计算（RankTrend golden 零漂移）。
- **不改**快照帧合同（`snapshot_frames` / `snapshot_stock_rows`）。
- **不做** modifiers / 修正栏 / 第 7-8 个状态格（§10.1 用户裁决）。
- **不做**读口向后兼容（§10.3：唯一消费者是自家前端，同批改完）。

## 3. 后端契约

### 3.1 新契约（`quant-board/backend/analysis/ranktrend/trend/display_status.py` 重写）

```python
STAGE_ENUM = ("ignition", "expansion", "crowded", "reversal", "cooling")   # 保留

STAGE_LABELS = {                    # 新增：展示词表**后端单源**，前端只消费
    "ignition": "点火",
    "expansion": "扩散",
    "crowded": "拥挤",
    "reversal": "反转",
    "cooling": "冷却",
}
STAGE_UNKNOWN_LABEL = "无阶段"

STAGE_TOOLTIPS = {
    "ignition": "点火启动，观察是否扩散。",
    "expansion": "扩散确认，趋势向上。",
    "crowded": "注意力拥挤高位，追高风险上升。",
    "reversal": "排名反转回落，注意风险。",
    "cooling": "注意力冷却消退。",
}
STRONG_SUPPORT_NOTE = "资金承接仍强。"


def compute_display_status(analysis, stock) -> dict:
    """stage 纯投影：{stage, label, tooltip}。无分类层、无修正类。"""
    stage = stage_of(analysis)
    stage = stage if stage in STAGE_ENUM else None          # 非法枚举 → None
    label = STAGE_LABELS[stage] if stage else STAGE_UNKNOWN_LABEL
    tooltip = STAGE_TOOLTIPS.get(stage) or "生命周期阶段缺失或非法，无法判定。"
    # cooling 且强资金 + 量能承接 → 仅 tooltip 追加（不进分类、不进计数，§10.2）
    if stage == "cooling" and _is_strong_money(stock) and _is_volume_supported(analysis):
        tooltip += STRONG_SUPPORT_NOTE
    return {"stage": stage, "label": label, "tooltip": tooltip}
```

### 3.2 删除清单

三层修正级联；`_STATUS`（8 类 label/classKey/tooltip 表）；`_STAGE_KEYS`；`_make`；`_make_stage_missing`；
`STAGE_MISSING_LABELS`；`STAGE_MISSING_TOOLTIP`；`_STAGE_MISSING_PREFIX`；`is_stage_missing_fallback`；`_sample_status`。

### 3.3 继承清单

`_as_dict`（形状归一）；`_is_strong_money`；`_is_volume_supported`；`is_stage_missing`（供 `unknown` 判据）；`STAGE_ENUM`；
§9 基础设施（数据层 after-save 钩子 / `analysis_worker` / backfill / recompute / 读口缓存失效）。

### 3.4 `_is_invalid_quote` 的处理（已确认）

**保留函数定义，不参与投影**。理由：纯投影下"无效行情"不再改判状态（否则又制造第二套结论）；保留定义供周期列灰框/诊断复用，spec 注明"当前无消费方，不得在展示链路重新启用"。

## 4. 计数契约

| 项 | 现状（8 类） | 落地后 |
| --- | --- | --- |
| 每行 `analysis.displayStatus` | `{label, classKey, tooltip}` | `{stage, label, tooltip}` |
| EOD 文档分布字段 | `statusCounts`（8 类，产自 `backend/analysis/hotlist/sentiment.py:291`） | `stageCounts`：`{ignition, expansion, crowded, reversal, cooling, unknown}` |
| 来源计数 | `{displayStatus, fallback, stageMissing}` | `{displayStatus, fallback}`（**删 `stageMissing`**） |
| 恒等式 | 无（多对一，不可反推） | `sum(stageCounts) == 全池行数`；每行 `label == STAGE_LABELS[cycle.stage]` |
| 样本质量差的股票 | 单列为一类并从 stage 分布**挖出** | **计入其 stage 桶**，不挖掉；质量由周期列灰框（`meta.sampleQuality.status === 'insufficient'`）承载 |

**判据**

- `unknown`：`is_stage_missing(analysis)` 为真（`cycle.stage` 缺失或非法枚举）。
- `fallback`：该行**没有** `snapshot_analysis` 记录（analysis 覆盖缺失）。
- **fallback 行归 `unknown` 桶**：真 fallback 行取不到 `cycle.stage`，无法归入任何具体态。此处与原 spec §10.3 "fallback 行同样按 `cycle.stage` 计入" 的表述有差异 —— 以本 spec 为准（§10.3 那句隐含"fallback 行也带 stage"，实测不成立）。

**`_insufficient_entries` 语义调整**（`backend/services/snapshot_analysis_service.py`）

该函数（本批次新加）原先把"算不出排名序列"的股票落成「样本不足」类。分类层删除后改为产出**无阶段行**：

```python
{"cycle": None,
 "meta": {"code": code, "sampleQuality": {"status": "insufficient", "timelineValid": False}},
 "observation": {"status": "insufficient"},
 "displayStatus": {"stage": None, "label": "无阶段", "tooltip": "..."}}
```

效果：这类股票诚实落在 `unknown` 桶，`statusSourceCounts.displayStatus +1`（有投影记录），不再伪装成某个状态。**不得**把它们伪装成具体 stage。

## 5. 前端契约

| 文件 | 变更 |
| --- | --- |
| `src/services/rankTrend/statusClassifier.ts` | `getRankTrendDisplayStatus` → `{stage, label, tooltip}`；删 8 类 `RISK_LABELS`/`RISK_CLASS_KEYS` 与级联；`UNKNOWN_STATUS` 保留（**displayStatus 整体缺失** → `label="未知"`，与"有记录但 stage 缺失 → 无阶段"区分） |
| `src/services/rankTrend/types.ts`、`compat.ts` | 新增共享三字段类型 `RankTrendDisplayStatus`；`RankTrendAnalysisResult.displayStatus` 与快照 analysis 条目收敛为同一形状 |
| `src/components/common/DataTable.vue` | 周期列显示 `label`（与面板同词同源）；样本不足灰框判据不变（`meta.sampleQuality.status === 'insufficient'`）；排序方向组 `ignition/expansion=buy`、`crowded/reversal/cooling=sell`、`unknown=hold` |
| `src/components/panels/DragonBreathPanel.vue` | 全池状态结构改 **6 格**：点火 / 扩散 / 拥挤 / 反转 / 冷却 / 无阶段；底部保留覆盖率行（golden 判定 N / fallback 接管 M）；**删修正栏** |
| `src/components/panels/RankTrendPanel.vue` | 6 格文案与词表同源 |
| `src/types/hotlistSentiment.ts` | `stageCounts` 类型；移除 `stageMissing` |

## 6. 数据迁移

顺序不可反（②依赖①的产物）：

```powershell
# ① 重投影 978 帧的 displayStatus（结构由 3 字段替代 8 类）
.\.venv\Scripts\python.exe -m backend.cli snapshot-analysis-backfill `
  --dataset-id dragonboard_live --snapshot-type half_hour `
  --start-date 2026-01-01 --limit 0 --workers 6 --apply

# ② 重算 142 天 EOD 文档（statusCounts → stageCounts）
.\.venv\Scripts\python.exe -m backend.cli hotlist-sentiment-recompute `
  --dataset-id dragonboard_live --snapshot-type half_hour --days 0 --apply
```

**预期**：每行 `displayStatus` 为 3 字段；EOD 文档 `stageCounts` 六桶之和 = 全池行数；`statusSourceCounts = {displayStatus, fallback}`。

## 7. 测试与验收

1. **后端单测（重写 `quant-board/tests/test_display_status.py`）**：直映射矩阵（5 态 + null → `label`/`stage`/`tooltip`）；stage 缺失/非法 → `stage=None` + `label="无阶段"`；cooling 强资金承接 → tooltip 追加且**不改变 label/stage**；`_as_dict` 形状健壮性；删除原 8 类级联用例。
2. **计数测试（重写 `quant-board/tests/test_display_status_reconciliation.py`）**：恒等式 `sum(stageCounts) == 行数`；重算后与当日 `cycle.stage` 分布逐桶相等（fixture：`ignition 1 / expansion 0 / crowded 9 / reversal 12 / cooling 213 / unknown 0`）。
3. **前端**：`vitest`（statusClassifier 纯消费、DragonBreathPanel 6 格、DataTable 与面板同词）；`vue-tsc --noEmit -p tsconfig.app.json` 0 error；`pnpm test` 全绿。
4. **真实浏览器验收（`playwright-cli`，必须）**：面板 6 格数值 ≡ 行情表周期列逐股 stage 同池统计（**逐股核对，不接受只对合计**）；控制台 0 报错。
5. **文档**：`docs/ranktrend/lifecycle-layering-contract.md` 展示状态节重写为恒等式（删除被证伪的等式）；`quant-board/docs/api-cli.md`（新 `displayStatus` 结构 + `stageCounts` + 迁移指引）；`quant-board/docs/architecture.md` 口径同步。

## 8. 与旧口径的对照（迁移检查表）

| 旧 | 新 |
| --- | --- |
| `label` 8 类（含 `classKey`） | `label` ≡ `STAGE_LABELS[stage]`（5 态 + 无阶段），无 `classKey` |
| `statusCounts`（8 类） | `stageCounts`（5 态 + `unknown`） |
| `statusSourceCounts.stageMissing` | 删除；阶段缺失体现在 `stageCounts.unknown` |
| `样本不足` 独立成类并从分布挖出 | 计入其 stage 桶；质量由周期列灰框承载 |
| `强资确认` 独立类 | cooling 的 tooltip 追加"资金承接仍强。" |
| `转弱预警`（跨 3 态覆盖） | 由 `reversal` / `cooling` 各自的 stage 词表表达 |
| `fallback_status_label` 启发式 | 先断消费、保留函数；历史重算完成后删除 |

## 9. 风险与耦合点

| 风险 | 说明与处理 |
| --- | --- |
| **回测侧也消费 8 类** | `quant-board/backend/core/backtest/engine.py:144` 与 `core/_archive/backtest_legacy.py:1008` 同样产出 `statusCounts`。实施前必须确认其语义（回测是否依赖 8 类标签），**不得盲目删除**；若回测需要独立口径，须在计划中单列一步并加测试 |
| `expansion` 长期为 0 | 引擎现状（978 帧无产出），"扩散"格会诚实显示 0；非本设计引入 |
| 无阶段占比 | `_insufficient_entries` 覆盖的行（无有效 `avgRankNum`，全库约 1/5 的行有此特征）会进入 `unknown` 桶，面板"无阶段"格占比可能显著 —— 这是 fail-visible 的正确表现，需在验收时确认数值并写入文档 |
| 前端旧缓存 | 前端若命中旧的 `displayStatus` 8 类缓存，会走 `UNKNOWN_STATUS`；迁移后需确认面板无"未知"残留 |
| 读口无兼容 | §10.3 明确不做读口兼容；实施必须前后端同批（用户已选路径 A） |

## 10. 变更清单（文件级）

**后端**：`analysis/ranktrend/trend/display_status.py`（重写）、`analysis/hotlist/sentiment.py:291`（`statusCounts` → `stageCounts`）、`operations/hotlist_sentiment.py:306`（EOD 文档构建）、`services/theme/hotlist_sentiment_compute.py`（join 注入 stage/label；删 `stageMissing`）、`services/snapshot_analysis_service.py`（`_insufficient_entries` 语义）

**后端测试**：`tests/test_display_status.py`（重写）、`tests/test_display_status_reconciliation.py`（重写）、`tests/test_hotlist_sentiment_compute.py`（计数断言）、`tests/test_snapshot_analysis_insufficient.py`（语义调整）、`tests/test_snapshot_analysis_service.py`

**前端**：`src/services/rankTrend/statusClassifier.ts`、`types.ts`、`compat.ts`、`src/types/hotlistSentiment.ts`、`src/components/common/DataTable.vue`、`src/components/panels/RankTrendPanel.vue`、`src/components/panels/DragonBreathPanel.vue`

**前端测试**：`src/services/rankTrend/__tests__/statusClassifier.test.ts`、`src/components/common/__tests__/DataTable.test.ts`、`src/components/panels/__tests__/RankTrendPanel.test.ts`、`src/components/panels/__tests__/DragonBreathPanel.test.ts`

**文档**：`docs/ranktrend/lifecycle-layering-contract.md`、`quant-board/docs/api-cli.md`、`quant-board/docs/architecture.md`、原 spec §3 废弃标注（已完成）
