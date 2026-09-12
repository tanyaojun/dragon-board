# displayStatus 退役为纯投影（stage 主轴）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `displayStatus` 从"8 类分类层"退役为 `cycle.stage` 的纯投影 `{stage, label, tooltip}`，分布由 `statusCounts`（8 类）改为 `stageCounts`（5 态 + `unknown`），使恒等式 `sum(stageCounts) == 全池行数` 成立。

**Architecture:** 后端 `display_status.py` 删除三层修正级联，只做 stage → 词表直映射（cooling 强资金承接降级为 tooltip 追加）；计数锚定 `analysis.cycle.stage` 黄金真值而不是 displayStatus 存在性；前端 `statusClassifier.ts` 收敛为三字段纯消费，`DragonBreathPanel` 由 8 格改 6 格；历史数据用现成的两条 CLI 重投影。**golden 引擎（cycle / candidateTier / synergy）零改动。**

**Tech Stack:** Python 3.13 + FastAPI + MongoDB（QuantBoard `backend/`，pytest）；Vue 3 + TypeScript + Vite（根项目 `src/`，vitest + vue-tsc）；Playwright（真实浏览器验收）。

**Spec:** `docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`
**上游裁决:** `docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md` §10（§3 已标废弃）

---

## 文件结构（决策锁定）

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `quant-board/backend/analysis/ranktrend/trend/display_status.py` | stage → `{stage,label,tooltip}` 纯投影 + 词表单一来源 | **重写** |
| `quant-board/backend/analysis/hotlist/sentiment.py` | EOD `metrics.layers.*.stageCounts` 生产 | 改计数 |
| `quant-board/backend/operations/hotlist_sentiment.py` | EOD 文档组装（`build_hotlist_sentiment_document`） | 改入参名 |
| `quant-board/backend/services/theme/hotlist_sentiment_compute.py` | join 注入 `stage`；读口摘要改 `stageCounts` | 改 |
| `quant-board/backend/services/snapshot_analysis_service.py` | `_insufficient_entries` 产出"无阶段行" | 改 |
| `quant-board/tests/test_display_status.py` | 直映射矩阵合同 | **重写** |
| `quant-board/tests/test_display_status_reconciliation.py` | 恒等式 | **重写** |
| `quant-board/tests/test_snapshot_analysis_insufficient.py` | 无阶段行语义 | 改断言 |
| `src/services/rankTrend/statusClassifier.ts` | 三字段纯消费 | **重写** |
| `src/services/rankTrend/types.ts` | `displayStatus` 三字段 | 改 |
| `src/services/apiService.ts` | `SnapshotAnalysisEntry` 12 字段对齐 | 改 |
| `src/types/hotlistSentiment.ts` | `stageCounts`/`stageShares`；删 `stageMissing` | 改 |
| `src/components/panels/DragonBreathPanel.vue` | 全池结构 6 格 | 改 |
| `src/components/common/DataTable.vue` | 周期列词表与后端同源 | 改 |
| `src/components/panels/RankTrendPanel.vue` | 三字段消费 | 改 |

**验证命令约定**

- 后端（在 `D:\dragon-board\quant-board`）：`.\.venv\Scripts\python.exe -m pytest tests/<file> -q --tb=short -p no:cacheprovider`
- 前端（在 `D:\dragon-board`）：`pnpm exec vitest run <file>`；类型检查 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json`
- **禁止**在 quant-board 跑全量 pytest（`tests/test_archive_research.py` 会挂起）

---

### Task 0: 前置确认 —— 回测侧 `statusCounts` 耦合

**Files:**
- Inspect: `quant-board/backend/core/backtest/engine.py:144`
- Inspect: `quant-board/backend/core/_archive/backtest_legacy.py:1008`

- [ ] **Step 1: 读两处产出点**

Run: `rg -n "status_counts|statusCounts" quant-board/backend/core/backtest/engine.py quant-board/backend/core/_archive/backtest_legacy.py`
Expected: 看到 `"statusCounts": status_counts` 及其上游 `status_counts` 的构造代码

- [ ] **Step 2: 判定回测是否依赖 8 类标签**

判断标准（逐条回答，写进本 Task 的提交说明）：

1. `status_counts` 的构造是否来自 `compute_display_status` / `displayStatus.label`？若是 → 8 类被删后回测会拿到 `{stage,label}`（label 变 5 态词）→ **需连带改**。
2. 是否被回测指标/报告消费（`efficacy` / `audit` / 前端回测页）？若只写进 journal 不参与计算 → **可暂留并加 TODO 注释**。
3. 若是 `_archive/` 路径 → **不修改**（归档代码），只在本计划记录。

- [ ] **Step 3: 记录结论并提交**

Run: `cd D:\dragon-board && git add -A && git commit -m "chore(displayStatus): record backtest statusCounts coupling before stage projection"`

Expected: 提交成功；提交说明含 Step 2 的三条判定结果。**若判定为"需连带改"，先停下来向用户报告范围再继续 Task 1。**

---

### Task 1: 后端 `display_status.py` 重写为纯投影

**Files:**
- Modify（整体替换）: `quant-board/backend/analysis/ranktrend/trend/display_status.py`
- Rewrite: `quant-board/tests/test_display_status.py`

- [ ] **Step 1: 写失败测试（RED）**

用以下内容**完整替换** `quant-board/tests/test_display_status.py`：

```python
# -*- coding: utf-8 -*-
"""displayStatus 纯投影合同（spec: docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md §3）。

displayStatus 只是 cycle.stage 的展示投影：{stage, label, tooltip}。
无分类层、无修正类、无 classKey；cooling 强资金承接只追加 tooltip，不改 label/stage。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.display_status import (
    STAGE_ENUM,
    STAGE_LABELS,
    STAGE_UNKNOWN_LABEL,
    compute_display_status,
    is_stage_missing,
    stage_of,
)


@pytest.mark.parametrize("stage", list(STAGE_ENUM))
def test_label_is_stage_projection(stage: str) -> None:
    result = compute_display_status({"cycle": {"stage": stage}}, {})
    assert result["stage"] == stage
    assert result["label"] == STAGE_LABELS[stage]
    assert result["tooltip"]


@pytest.mark.parametrize("missing", [None, "", "unknown", "IGNITION", 7])
def test_missing_or_invalid_stage_projects_to_none_and_unknown_label(missing) -> None:
    analysis = {} if missing is None else {"cycle": {"stage": missing}}
    result = compute_display_status(analysis, {})
    assert result["stage"] is None
    assert result["label"] == STAGE_UNKNOWN_LABEL
    assert result["tooltip"]
    assert is_stage_missing(analysis) is True


def test_no_class_key_in_contract() -> None:
    result = compute_display_status({"cycle": {"stage": "crowded"}}, {})
    assert set(result) == {"stage", "label", "tooltip"}


def test_cooling_strong_support_only_touches_tooltip() -> None:
    stock = {"zlje": 1000.0, "zljzb": 12.0}
    analysis = {
        "cycle": {"stage": "cooling"},
        "observation": {"volumePrice": {"signalTier": "A"}},
    }
    with_support = compute_display_status(analysis, stock)
    without_support = compute_display_status({"cycle": {"stage": "cooling"}}, {})
    assert with_support["stage"] == without_support["stage"] == "cooling"
    assert with_support["label"] == without_support["label"]
    assert with_support["tooltip"] != without_support["tooltip"]
    assert with_support["tooltip"].startswith(without_support["tooltip"])


def test_non_cooling_stage_never_gets_strong_support_note() -> None:
    stock = {"zlje": 1000.0, "zljzb": 12.0}
    analysis = {"cycle": {"stage": "ignition"}, "observation": {"volumePrice": {"signalTier": "A"}}}
    assert compute_display_status(analysis, stock)["tooltip"] == compute_display_status(
        {"cycle": {"stage": "ignition"}}, {}
    )["tooltip"]


@pytest.mark.parametrize("bad", [None, [], "str", 3.4])
def test_as_dict_tolerates_bad_shapes(bad) -> None:
    result = compute_display_status(bad, bad)
    assert result["stage"] is None
    assert result["label"] == STAGE_UNKNOWN_LABEL


def test_stage_of_returns_empty_for_missing() -> None:
    assert stage_of({}) == ""
    assert stage_of({"cycle": None}) == ""
    assert stage_of({"cycle": {"stage": "ignition"}}) == "ignition"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_display_status.py -q --tb=line -p no:cacheprovider`
Expected: FAIL —— `ImportError: cannot import name 'STAGE_LABELS'`（旧实现没有词表，且仍返回 `classKey`）

- [ ] **Step 3: 实现（GREEN）**

用以下内容**完整替换** `quant-board/backend/analysis/ranktrend/trend/display_status.py`：

```python
# -*- coding: utf-8 -*-
"""displayStatus 纯投影（2026-09-10 口径统一：生命周期 stage 主轴，spec §3/§10）。

设计要点（`docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`）：

- displayStatus 只是 `cycle.stage` 的**展示投影**：`{stage, label, tooltip}`；
- `label ≡ STAGE_LABELS[stage]`，stage 缺失/非法 → `stage=None` + `label="无阶段"`；
- **没有分类层**：不存在 8 类 label/classKey、不存在样本门/风险修正层/兜底类；
- cooling 且强资金 + 量能承接 → **只追加 tooltip**，不改变 label/stage、不进任何计数；
- 词表（`STAGE_LABELS` / `STAGE_TOOLTIPS`）是**单一来源**：前端只消费后端产出的 label，
  不得自维护第二套映射（历史教训：前端 `CYCLE_LABELS` 用"降温"、DataTable 用"冷却"，两套词）。

为什么删除分类层：实测 978 帧 / 220,736 行证明 8 类无法反推 stage（`样本不足` 跨 4 个 stage、
`转弱预警` 跨 3 个），8 类中 3 类从未出现，且修正层用互斥 return **覆盖**了 stage 主轴信息 ——
"把一等字段（cycle.stage / synergy.state / meta.sampleQuality / zlje+signalTier）复制成第二套状态分类
就是病灶本身"。上游裁决见 spec §10.1。
"""
from __future__ import annotations

import math
from typing import Any

# 生命周期 5 态枚举（stage 主轴唯一判据；join 层与本模块共用，禁止各写一套）
STAGE_ENUM = ("ignition", "expansion", "crowded", "reversal", "cooling")

# 展示词表（单一来源）：前端只消费，不自维护
STAGE_LABELS: dict[str, str] = {
    "ignition": "点火",
    "expansion": "扩散",
    "crowded": "拥挤",
    "reversal": "反转",
    "cooling": "冷却",
}

STAGE_UNKNOWN_LABEL = "无阶段"

STAGE_TOOLTIPS: dict[str, str] = {
    "ignition": "点火启动，观察是否扩散。",
    "expansion": "扩散确认，趋势向上。",
    "crowded": "注意力拥挤高位，追高风险上升。",
    "reversal": "排名反转回落，注意风险。",
    "cooling": "注意力冷却消退。",
}

STAGE_UNKNOWN_TOOLTIP = "生命周期阶段缺失或非法，无法判定。"

STRONG_SUPPORT_NOTE = "资金承接仍强。"

_PRICE_KEYS = ("price", "latestPrice", "lastPrice", "close")


def _as_dict(value: Any) -> dict[str, Any]:
    """形状归一：非 dict（None/list/str/数值）一律视为空 dict。

    纯函数必须对非法输入形状容错——否则单股异常形状会沿调用链抛错，而调用点没有 try 兜底。
    """
    return value if isinstance(value, dict) else {}


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _finite_non_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number <= 0


def _is_invalid_quote(stock: dict[str, Any]) -> bool:
    """无效行情判据（**当前无消费方，不得在展示链路重新启用**）。

    纯投影下"无效行情"不再改判展示状态 —— 否则又会制造第二套结论。保留定义供周期列灰框 /
    诊断复用；展示状态只认 `cycle.stage`。

    判据：价格类字段（首个有值者）非有限或 ≤0，或成交额非有限/<0。
    缺失 ≠ 无效（字段全缺时不判无效）；`turnover == 0` 视为有效（集合竞价）。
    """
    stock = _as_dict(stock)
    price = next((stock[k] for k in _PRICE_KEYS if _has_value(stock.get(k))), None)
    if _has_value(price):
        try:
            number = float(price)
        except (TypeError, ValueError):
            return True
        if not math.isfinite(number) or number <= 0:
            return True
    if _has_value(stock.get("turnover")):
        try:
            number = float(stock["turnover"])
        except (TypeError, ValueError):
            return True
        if not math.isfinite(number) or number < 0:
            return True
    return False


def _is_strong_money(stock: dict[str, Any]) -> bool:
    """强资金：主力净额 > 0 且 zljzb ≥ 8%（口径沿用，仅用于 cooling 的 tooltip 提示）。"""
    stock = _as_dict(stock)
    try:
        zlje = float(stock.get("zlje"))
        zljzb = float(stock.get("zljzb"))
    except (TypeError, ValueError):
        return False
    return zlje > 0 and zljzb >= 8


def _is_volume_supported(analysis: dict[str, Any]) -> bool:
    """量能承接：`volumePrice.signalTier ∈ {A, B}`（排除过热 E 与走弱 D）。缺失 → False。"""
    vp = _as_dict(_as_dict(analysis).get("observation")).get("volumePrice")
    return str(_as_dict(vp).get("signalTier") or "") in ("A", "B")


def stage_of(analysis: dict[str, Any]) -> str:
    return str(_as_dict(_as_dict(analysis).get("cycle")).get("stage") or "")


def is_stage_missing(analysis: dict[str, Any]) -> bool:
    """stage 缺失或非法枚举。join 层与前端一律复用本判据，禁止第二套枚举实现。"""
    return stage_of(analysis) not in STAGE_ENUM


def compute_display_status(analysis: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    """stage 纯投影：`{stage, label, tooltip}`。

    `is_stage_missing(analysis)` 与本函数等价：stage 为空串或非法枚举时 `stage=None`、
    `label=STAGE_UNKNOWN_LABEL`。join 层与前端不得再写第二套枚举判断。
    """
    raw_stage = stage_of(analysis)
    stage = raw_stage if raw_stage in STAGE_ENUM else None
    if stage is None:
        return {"stage": None, "label": STAGE_UNKNOWN_LABEL, "tooltip": STAGE_UNKNOWN_TOOLTIP}
    tooltip = STAGE_TOOLTIPS.get(stage) or STAGE_UNKNOWN_TOOLTIP
    # cooling 且强资金 + 量能承接：仅 tooltip 追加，不改 label/stage、不进计数
    if stage == "cooling" and _is_strong_money(stock) and _is_volume_supported(analysis):
        tooltip = f"{tooltip}{STRONG_SUPPORT_NOTE}"
    return {"stage": stage, "label": STAGE_LABELS[stage], "tooltip": tooltip}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_display_status.py -q --tb=short -p no:cacheprovider`
Expected: PASS（全绿）

- [ ] **Step 5: 提交**

Run: `cd D:\dragon-board && git add quant-board/backend/analysis/ranktrend/trend/display_status.py quant-board/tests/test_display_status.py && git commit -m "refactor(displayStatus): project stage instead of 8-class cascade"`

---

### Task 2: 后端计数契约（`stageCounts` 替换 `statusCounts`）

**Files:**
- Modify: `quant-board/backend/analysis/hotlist/sentiment.py`（约 L291 附近）
- Modify: `quant-board/backend/operations/hotlist_sentiment.py`（`build_hotlist_sentiment_document`，L306 起）
- Modify: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`（`_join_display_status` L52-100、`_status_source_summary` L111-132）
- Rewrite: `quant-board/tests/test_display_status_reconciliation.py`

- [ ] **Step 1: 定位锚点**

Run: `cd D:\dragon-board\quant-board; rg -n "status_counts|statusCounts|statusMissing|status_source" backend/analysis/hotlist/sentiment.py backend/operations/hotlist_sentiment.py backend/services/theme/hotlist_sentiment_compute.py`
Expected: 命中 `sentiment.py:291`、`operations/hotlist_sentiment.py` 的 `status_counts=` 形参、`hotlist_sentiment_compute.py:122-127` 与 `:931`（面板侧为前端）

- [ ] **Step 2: 写失败测试（RED）**

用以下内容**完整替换** `quant-board/tests/test_display_status_reconciliation.py`：

```python
# -*- coding: utf-8 -*-
"""计数契约：stageCounts 锚定 cycle.stage 黄金真值（spec §4）。

恒等式（替代旧的 8 类对账）：sum(stageCounts) == 全池行数；每行 label == STAGE_LABELS[stage]。
"""
from __future__ import annotations

from backend.analysis.ranktrend.display_status import STAGE_ENUM, STAGE_LABELS, STAGE_UNKNOWN_LABEL
from backend.analysis.hotlist.sentiment import build_stage_counts


def test_stage_counts_covers_all_rows() -> None:
    rows = [
        {"cycle": {"stage": "cooling"}},
        {"cycle": {"stage": "cooling"}},
        {"cycle": {"stage": "reversal"}},
        {"cycle": {"stage": "crowded"}},
        {"cycle": {"stage": "ignition"}},
        {"cycle": {}},                       # 缺失 → unknown
        {"cycle": {"stage": "bogus"}},       # 非法 → unknown
        {},                                  # 无 cycle → unknown
    ]
    counts = build_stage_counts(rows)
    assert set(counts) == {*STAGE_ENUM, "unknown"}
    assert sum(counts.values()) == len(rows)
    assert counts == {
        "ignition": 1, "expansion": 0, "crowded": 1, "reversal": 1, "cooling": 2, "unknown": 3,
    }


def test_stage_label_projection_is_total() -> None:
    for stage in STAGE_ENUM:
        assert STAGE_LABELS[stage]
    assert STAGE_UNKNOWN_LABEL == "无阶段"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_display_status_reconciliation.py -q --tb=line -p no:cacheprovider`
Expected: FAIL —— `ImportError: cannot import name 'build_stage_counts'`

- [ ] **Step 4: 在 `sentiment.py` 实现 `build_stage_counts` 并替换 8 类统计**

在 `quant-board/backend/analysis/hotlist/sentiment.py` 中：

1. 顶部 import 区加：

```python
from backend.analysis.ranktrend.display_status import STAGE_ENUM, is_stage_missing
```

2. 在模块级（与现有 `build_*` 函数并列处）新增：

```python
def build_stage_counts(rows: list[dict]) -> dict[str, int]:
    """按 `analysis.cycle.stage` 统计六桶（5 态 + unknown）。

    锚定 stage 黄金真值而非 displayStatus 存在性（spec §4）：样本质量差的股票**计入其 stage 桶**，
    不从分布里挖掉；stage 缺失/非法归 `unknown`；fallback 行（无 analysis）同样归 `unknown`。
    """
    counts: dict[str, int] = {stage: 0 for stage in STAGE_ENUM}
    counts["unknown"] = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else row
        raw = str(((analysis.get("cycle") or {}) if isinstance(analysis.get("cycle"), dict) else {}).get("stage") or "")
        counts[raw if raw in STAGE_ENUM else "unknown"] += 1
    return counts
```

3. 把原 `"statusCounts": status_counts`（约 L291）改为：

```python
        "stageCounts": build_stage_counts(rows),
```

其中 `rows` 用该函数当前已有的"全池行"变量（实施时按 Step 1 的 grep 结果确认变量名；若原统计基于已 join 的 rows，就传同一个列表）。**同时删除**该文件内所有 `statusMissing` 相关计数（U1-a 的产物随分类层消亡）。

- [ ] **Step 5: 改 `operations/hotlist_sentiment.py` 与 `compute` 侧**

`quant-board/backend/operations/hotlist_sentiment.py`（`build_hotlist_sentiment_document`，L306 起）：

- 形参 `status_counts: ...` → `stage_counts: dict[str, int]`；
- 文档写入处 `"statusCounts": status_counts` → `"stageCounts": stage_counts`。

`quant-board/backend/services/theme/hotlist_sentiment_compute.py`：

- `_join_display_status`（L52-100）改为注入 stage + label：

```python
def _join_display_status(db: Any, dataset_id: str, snapshot_id: str, rows: list[dict]) -> dict[str, Any]:
    """snapshot_analysis.displayStatus → rows[].displayStatusStage/Label（就地注入）。

    fail-visible：查询异常与个股无 displayStatus 分开结构化标注，不静默、不抛出（无质量阻断）。
    分类层删除后**不再有 stageMissing 计数**：阶段缺失直接体现在 stageCounts.unknown。
    """
    try:
        from backend.data.repositories.mongo_repository import MongoRepository

        analysis_by_code = MongoRepository(db).load_snapshot_analysis(
            dataset_id, snapshot_id, [str(row.get("code") or "") for row in rows]
        )
    except Exception as exc:
        return {"joined": 0, "noDisplayStatus": 0, "joinFailed": True, "reason": f"join_failed: {exc}"}
    joined = no_display = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        entry = analysis.get("displayStatus") if isinstance(analysis, dict) else None
        stage = entry.get("stage") if isinstance(entry, dict) else None
        label = entry.get("label") if isinstance(entry, dict) else None
        if isinstance(label, str) and label:
            row["displayStatusLabel"] = label
            row["displayStatusStage"] = stage if isinstance(stage, str) and stage else None
            joined += 1
        else:
            no_display += 1
    return {"joined": joined, "noDisplayStatus": no_display, "joinFailed": False, "reason": None}
```

- `_status_source_summary`（L111-132）改为读 `stageCounts`：

```python
def _status_source_summary(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """重算输出的摘要：stageCounts + 来源计数（不再有 8 类 statusCounts / stageMissing）。"""
    if not isinstance(doc, dict):
        return None
    metrics = doc.get("metrics") if isinstance(doc.get("metrics"), dict) else {}
    all_layer = (metrics.get("layers") or {}).get("all") if isinstance(metrics.get("layers"), dict) else {}
    all_layer = all_layer if isinstance(all_layer, dict) else {}
    return {
        "slotTime": doc.get("slotTime"),
        "computedAt": doc.get("computedAt"),
        "stageCounts": (
            doc.get("stageCounts")
            or metrics.get("stageCounts")
            or all_layer.get("stageCounts")
        ),
        "statusSourceCounts": doc.get("statusSourceCounts") or metrics.get("statusSourceCounts"),
        "stage": doc.get("stage"),
    }
```

同时删除 `_join_warning` 中对 `stageMissing` 的引用（若有）。

- [ ] **Step 6: 跑测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_display_status_reconciliation.py tests/test_hotlist_sentiment_compute.py tests/test_snapshot_analysis_service.py -q --tb=short -p no:cacheprovider`
Expected: `test_display_status_reconciliation.py` PASS；另两个文件里引用了 `statusCounts`/`stageMissing` 的断言会 FAIL —— 逐个改成 `stageCounts`（删掉 `stageMissing` 断言），再重跑至全绿。

- [ ] **Step 7: 提交**

Run: `cd D:\dragon-board && git add quant-board/backend quant-board/tests && git commit -m "refactor(displayStatus): stageCounts replaces 8-class statusCounts"`

---

### Task 3: `_insufficient_entries` 产出"无阶段行"

**Files:**
- Modify: `quant-board/backend/services/snapshot_analysis_service.py`
- Modify: `quant-board/tests/test_snapshot_analysis_insufficient.py`

- [ ] **Step 1: 改测试断言（RED）**

把 `quant-board/tests/test_snapshot_analysis_insufficient.py` 中三处断言改为：

```python
def test_insufficient_entries_project_to_unknown_stage() -> None:
    entries = svc._insufficient_entries(_frame(["300671"]), set())
    analysis = entries[0]["analysis"]
    assert analysis["cycle"] is None
    assert analysis["displayStatus"] == {
        "stage": None,
        "label": "无阶段",
        "tooltip": "生命周期阶段缺失或非法，无法判定。",
    }
    assert analysis["meta"]["sampleQuality"]["status"] == "insufficient"
```

并把原 `displayStatus["label"] == "样本不足"` / `classKey == "insufficient"` 的断言删除。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_analysis_insufficient.py -q --tb=line -p no:cacheprovider`
Expected: FAIL（当前实现落的是"样本不足"类 + `classKey`）

- [ ] **Step 3: 改实现**

`quant-board/backend/services/snapshot_analysis_service.py` 的 `_insufficient_entries` 中，把 `analysis` 构造改为：

```python
        analysis: dict[str, Any] = {
            "cycle": None,                       # 无阶段：诚实落在 stageCounts.unknown
            "meta": {
                "code": code,
                "sampleQuality": {"status": "insufficient", "timelineValid": False},
            },
            "observation": {"status": "insufficient"},
        }
        # displayStatus 必须随 entry 一起落库（hotlist join 只读 analysis.displayStatus）；
        # 分类层已删除 → 直接调纯投影（结果必然是 stage=None / label="无阶段"）
        analysis["displayStatus"] = compute_display_status(analysis, row)
```

并把文件顶部函数内 import 改为：

```python
    from backend.analysis.ranktrend.display_status import compute_display_status
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_analysis_insufficient.py tests/test_snapshot_analysis_service.py tests/test_snapshot_analysis_backfill.py -q --tb=short -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: 提交**

Run: `cd D:\dragon-board && git add quant-board/backend/services/snapshot_analysis_service.py quant-board/tests/test_snapshot_analysis_insufficient.py && git commit -m "refactor(displayStatus): insufficient rows project to unknown stage"`

---

### Task 4: 前端类型 + `statusClassifier.ts` 收敛

**Files:**
- Rewrite: `src/services/rankTrend/statusClassifier.ts`
- Modify: `src/services/rankTrend/types.ts:355-368`
- Modify: `src/services/apiService.ts:127-133`
- Modify: `src/types/hotlistSentiment.ts:7-15,36-37,185`
- Rewrite: `src/services/rankTrend/__tests__/statusClassifier.test.ts`

- [ ] **Step 1: 改类型（先把形状定死）**

`src/services/rankTrend/types.ts`：把 `displayStatus?: { label: string; classKey: string; tooltip: string }`（L364-368）替换为：

```ts
  /**
   * 展示状态（2026-09-10 口径统一，spec §3）：后端 Python `compute_display_status` 生产的
   * stage 纯投影。`stage` 为 5 态之一或 `null`（缺失/非法）；`label ≡ STAGE_LABELS[stage]`
   * （`null` → "无阶段"）。前端只消费，不再自维护词表。
   */
  displayStatus?: RankTrendDisplayStatus
```

并在同文件 import/定义区加：

```ts
/** 后端 displayStatus 三字段投影（单一来源，与 apiService.SnapshotAnalysisEntry 共用形状）。 */
export interface RankTrendDisplayStatus {
  stage: string | null
  label: string
  tooltip: string
}
```

`src/services/apiService.ts`：`SnapshotAnalysisEntry`（L127-133）替换为（补齐后端 12 字段）：

```ts
export interface SnapshotAnalysisEntry {
  /** 后端持久化的 analyze 产物（MongoDB snapshot_analysis），供历史回放/对比。 */
  observation?: Record<string, any>
  displayStatus?: { stage?: string | null; label?: string; tooltip?: string }
  technical?: Record<string, any>
  risk?: Record<string, any>
  strategy?: Record<string, any>
  executionStrategy?: Record<string, any>
  jump?: Record<string, any>
  decision?: Record<string, any>
  cycle?: Record<string, any>
  meta?: Record<string, any>
  resonance?: Record<string, any>
  themeMomentum?: Record<string, any>
}
```

`src/types/hotlistSentiment.ts`：

- L7-15 的 `HotListStatusLabel`（8 类）替换为：

```ts
/** 全池状态结构：生命周期 5 态 + 阶段缺失（spec §4，替代原 8 类 label）。 */
export type HotListStageKey = 'ignition' | 'expansion' | 'crowded' | 'reversal' | 'cooling' | 'unknown'

export const HOT_LIST_STAGE_LABELS: Record<HotListStageKey, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
  unknown: '无阶段',
}
```

- L36-37 替换为：

```ts
  stageCounts: Record<HotListStageKey, number>
  stageShares: Record<HotListStageKey, number>
```

- L185 的 `statusSourceCounts?: { displayStatus: number; fallback: number; stageMissing?: number }` 替换为：

```ts
    statusSourceCounts?: { displayStatus: number; fallback: number }
```

- [ ] **Step 2: 写失败测试（RED）**

用以下内容**完整替换** `src/services/rankTrend/__tests__/statusClassifier.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { getRankTrendDisplayBreakdown, getRankTrendDisplayStatus } from '../statusClassifier'

const withStatus = (displayStatus?: any) => ({ displayStatus }) as any

describe('statusClassifier（纯消费后端 displayStatus 三字段投影）', () => {
  it('后端有 displayStatus 时逐字透传 stage/label/tooltip', () => {
    const status = getRankTrendDisplayStatus(
      withStatus({ stage: 'crowded', label: '拥挤', tooltip: '注意力拥挤高位，追高风险上升。' }),
    )
    expect(status).toEqual({ stage: 'crowded', label: '拥挤', tooltip: '注意力拥挤高位，追高风险上升。' })
  })

  it('stage 为 null 时保留"无阶段"（有记录但阶段缺失）', () => {
    const status = getRankTrendDisplayStatus(withStatus({ stage: null, label: '无阶段', tooltip: 'x' }))
    expect(status.stage).toBeNull()
    expect(status.label).toBe('无阶段')
  })

  it('displayStatus 整体缺失 → 结构化未知（与"无阶段"区分）', () => {
    const status = getRankTrendDisplayStatus(withStatus(undefined))
    expect(status.stage).toBeNull()
    expect(status.label).toBe('未知')
    expect(status.tooltip).toContain('缺失')
  })

  it('label 非字符串视为缺失', () => {
    expect(getRankTrendDisplayStatus(withStatus({ stage: 'crowded', label: 3 })).label).toBe('未知')
  })

  it('breakdown 的周期栏直接消费后端 label，不自维护词表', () => {
    const breakdown = getRankTrendDisplayBreakdown(withStatus({ stage: 'crowded', label: '拥挤', tooltip: 't' }))
    expect(breakdown.displayStatusLabel).toBe('拥挤')
    expect(breakdown.cycleLabel).toBe('拥挤')
    expect(breakdown.classKeys.displayStatus).toBe('stage-crowded')
  })

  it('未知态的 classKey 为 stage-none', () => {
    const breakdown = getRankTrendDisplayBreakdown(withStatus(undefined))
    expect(breakdown.classKeys.displayStatus).toBe('stage-none')
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd D:\dragon-board; pnpm exec vitest run src/services/rankTrend/__tests__/statusClassifier.test.ts`
Expected: FAIL（现实现返回 `{label, classKey, tooltip}`、`classKeys.displayStatus='main_confirmed'`）

- [ ] **Step 4: 重写 `statusClassifier.ts`（GREEN）**

用以下内容**完整替换** `src/services/rankTrend/statusClassifier.ts`：

```ts
import type { RankTrendAnalysisResult, RankTrendDisplayStatus } from './types'

export type { RankTrendDisplayStatus }

export interface RankTrendDisplayBreakdown {
  qualityLabel: string
  qualityBadgeLabel: string
  showQualityBadge: boolean
  cycleLabel: string
  tierLabel: string
  displayStatusLabel: string
  candidateTierKey: string
  candidateTierLabel: string
  tooltip: string
  classKeys: {
    quality: string
    cycle: string
    tier: string
    displayStatus: string
  }
}

// 2026-09-10 口径统一（docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md）：
// displayStatus 是后端 `cycle.stage` 的纯投影 {stage, label, tooltip}，前端不自维护任何词表
// （历史教训：本文件 CYCLE_LABELS 曾用"降温"，而 DataTable 用"冷却"，同一状态两套词）。
// 后端缺失（旧缓存/离线）时返回结构化未知态，fail-visible，不伪造本地结论。
// 注意与"无阶段"区分：`label === '无阶段'` 是"有记录但 stage 缺失"，这里是"完全没有记录"。
const UNKNOWN_STATUS: RankTrendDisplayStatus = {
  stage: null,
  label: '未知',
  tooltip: '后端 displayStatus 缺失（旧缓存/离线）。',
}

export const UNKNOWN_STAGE_CLASS_KEY = 'stage-none'

const CANDIDATE_TIER_LABELS: Record<string, string> = {
  A_MAIN: 'A_MAIN / 主升候选',
  B_IGNITION: 'B_IGNITION / 点火候选',
  C_CROWDED: 'C_CROWDED / 拥挤候选',
  D_EXIT_RISK: 'D_EXIT_RISK / 退出风险',
  N_NEUTRAL: 'N_NEUTRAL / 中性观察',
}

const CANDIDATE_TIER_SHORT_LABELS: Record<string, string> = {
  A_MAIN: '主升候选',
  B_IGNITION: '点火候选',
  C_CROWDED: '拥挤候选',
  D_EXIT_RISK: '退出风险',
  N_NEUTRAL: '中性观察',
}

const CANDIDATE_TIER_CLASS_KEYS: Record<string, string> = {
  A_MAIN: 'candidate-main',
  B_IGNITION: 'candidate-ignition',
  C_CROWDED: 'candidate-crowded',
  D_EXIT_RISK: 'candidate-exit',
  N_NEUTRAL: 'candidate-neutral',
}

const SAMPLE_QUALITY_LABELS: Record<string, string> = {
  ok: '样本OK',
  degraded: '样本降级',
  insufficient: '样本不足',
  unknown: '样本未知',
}

/** stage 的 CSS classKey（无 stage → stage-none）；不再使用 8 类 classKey。 */
export const stageClassKey = (stage: string | null): string => (stage ? `stage-${stage}` : UNKNOWN_STAGE_CLASS_KEY)

export function getRankTrendDisplayStatus(
  rankTrend?: RankTrendAnalysisResult | null,
): RankTrendDisplayStatus {
  // 后端直通：analysis.displayStatus 由 Python compute_display_status 生产（cycle.stage 纯投影）。
  const backendStatus = rankTrend?.displayStatus
  if (backendStatus && typeof backendStatus.label === 'string') {
    return {
      stage: typeof backendStatus.stage === 'string' && backendStatus.stage ? backendStatus.stage : null,
      label: backendStatus.label,
      tooltip: backendStatus.tooltip ?? '',
    }
  }
  return UNKNOWN_STATUS
}

export function getRankTrendDisplayBreakdown(
  rankTrend?: RankTrendAnalysisResult | null,
): RankTrendDisplayBreakdown {
  const status = getRankTrendDisplayStatus(rankTrend)
  const sampleStatus = rankTrend ? rankTrend.meta?.sampleQuality?.status ?? 'unknown' : 'insufficient'
  const candidateTierKey = rankTrend?.strategy?.candidateTier ? String(rankTrend.strategy.candidateTier) : ''
  const candidateTierLabel = candidateTierKey
    ? CANDIDATE_TIER_LABELS[candidateTierKey] ?? candidateTierKey
    : '-'
  const tierLabel = candidateTierKey
    ? CANDIDATE_TIER_SHORT_LABELS[candidateTierKey] ?? candidateTierKey
    : status.label
  const qualityLabel = SAMPLE_QUALITY_LABELS[sampleStatus] ?? '样本未知'
  const cycleLabel = status.label
  const tooltip = [
    `样本：${qualityLabel}`,
    `周期：${cycleLabel}`,
    `生命周期：${tierLabel}`,
    candidateTierKey ? `原始分层：${candidateTierLabel}` : '',
    `展示状态：${status.label}`,
    status.tooltip,
  ]
    .filter(Boolean)
    .join('\n')

  return {
    qualityLabel,
    qualityBadgeLabel: '',
    showQualityBadge: false,
    cycleLabel,
    tierLabel,
    displayStatusLabel: status.label,
    candidateTierKey,
    candidateTierLabel,
    tooltip,
    classKeys: {
      quality: `quality-${sampleStatus}`,
      cycle: status.stage ? `cycle-${status.stage}` : 'cycle-empty',
      tier: candidateTierKey
        ? CANDIDATE_TIER_CLASS_KEYS[candidateTierKey] ?? 'candidate-unknown'
        : stageClassKey(status.stage),
      displayStatus: stageClassKey(status.stage),
    },
  }
}
```

- [ ] **Step 5: 修所有编译错误（消费点）**

Run: `cd D:\dragon-board; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | Select-Object -First 40`
Expected: 列出 `classKeys.risk`、`checkRankTrendBreakdown` 等引用错误 → 逐个处理：

- `src/components/panels/RankTrendPanel.vue:705` 的 `statusClass: breakdown.classKeys.tier` **保持**（`tier` 仍在）；
- 任何引用 `breakdown.classKeys.risk` / `riskLabel` 的地方：删除该字段使用（风险修正层已退出展示）；
- `src/components/common/DataTable.vue:81-82` 测试里的 `classKeys.tier` 断言保持（`tier` 仍在）。

再跑：`cd D:\dragon-board; pnpm exec vitest run src/services/rankTrend/__tests__/statusClassifier.test.ts`
Expected: PASS

- [ ] **Step 6: 提交**

Run: `cd D:\dragon-board && git add src/services/rankTrend/statusClassifier.ts src/services/rankTrend/types.ts src/services/apiService.ts src/types/hotlistSentiment.ts src/services/rankTrend/__tests__/statusClassifier.test.ts && git commit -m "refactor(displayStatus): front-end consumes stage projection only"`

---

### Task 5: `DragonBreathPanel.vue` 全池结构改 6 格

**Files:**
- Modify: `src/components/panels/DragonBreathPanel.vue`（L595 import、L320 CSS 绑定、L871/L900-931 分布区、L991-993 派生指标）
- Modify: `src/components/panels/__tests__/DragonBreathPanel.test.ts`

- [ ] **Step 1: 改测试（RED）**

`src/components/panels/__tests__/DragonBreathPanel.test.ts`：把 L17 的 `stageMissing` 源码断言替换为 6 格断言：

```ts
    it('全池状态结构为 6 格且不含 8 类修正栏', () => {
      const source = readPanelSource()
      expect(source).toMatch(/hotListStageOrder/)
      expect(source).toMatch(/无阶段/)
      expect(source).not.toMatch(/stageMissing/)
      expect(source).not.toMatch(/'强资确认'|'资金背离'|'新入观察'|'主升确认'/)
    })
```

（`readPanelSource` 用该文件已有的源码读取辅助；若原文件用的是别的名字，按现有写法沿用。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd D:\dragon-board; pnpm exec vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts`
Expected: FAIL

- [ ] **Step 3: 改实现**

1. L595 的 import：`HotListStatusLabel` → `HotListStageKey`（来自 `@/types/hotlistSentiment`）。
2. L900-908 的 `hotListStatusOrder`（8 格）整体替换为：

```ts
const hotListStageOrder: Array<{ key: HotListStageKey; classKey: string }> = [
  { key: 'ignition', classKey: 'ignition' },
  { key: 'expansion', classKey: 'expansion' },
  { key: 'crowded', classKey: 'crowded' },
  { key: 'reversal', classKey: 'reversal' },
  { key: 'cooling', classKey: 'cooling' },
  { key: 'unknown', classKey: 'unknown' },
]
```

3. L871 的 `const counts = hotListToday.value?.statusCounts` → `const counts = ...?.stageCounts`。
4. L916-918 的映射项改为：

```ts
    label: HOT_LIST_STAGE_LABELS[item.key],
    count: today.stageCounts[item.key] || 0,
    shareText: formatShare(today.stageShares[item.key] || 0),
```

（并按 `hotListStageOrder` 重命名循环变量；模板里 `status-${item.classKey}` 保持可用，classKey 值改为 6 个 stage 词。）
5. L931 的 `parts.push(\`阶段缺失 ${counts.stageMissing}\`)` **整行删除**（阶段缺失已体现在"无阶段"格）。
6. L991-993 的三个派生指标改为读 stage 桶：

```ts
    strongMoney: metrics?.stageCounts?.cooling ?? 0,
    crowded: metrics?.stageCounts?.crowded ?? 0,
    risk: metrics ? (metrics.stageCounts?.reversal ?? 0) : 0,
```

（`strongMoney`/`risk` 的语义从"8 类计数"变为"stage 桶计数"；如该指标另有业务含义，改为 `--` 并加注释说明已随分类层退出。实施时按 Step 1 的 grep 结果补齐空值保护。）
7. CSS：把 `.status-*` 规则按 6 个 stage 词重排（`status-ignition/expansion/crowded/reversal/cooling/unknown`），删除不再使用的 8 类选择器。

- [ ] **Step 4: 跑测试 + 类型检查**

Run: `cd D:\dragon-board; pnpm exec vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/RankTrendPanel.test.ts`
Expected: PASS（DataTable/RankTrendPanel 若有 8 类断言一并按 Task 6 调整）

Run: `cd D:\dragon-board; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 0 error

- [ ] **Step 5: 提交**

Run: `cd D:\dragon-board && git add src/components/panels/DragonBreathPanel.vue src/components/panels/__tests__/DragonBreathPanel.test.ts && git commit -m "refactor(displayStatus): breath panel shows 6 stage buckets"`

---

### Task 6: `DataTable.vue` 周期列词表与后端同源

**Files:**
- Modify: `src/components/common/DataTable.vue`（`localAttentionStageLabels` 定义处、L811-814、L900）

- [ ] **Step 1: 定位本地词表**

Run: `cd D:\dragon-board; rg -n "localAttentionStageLabels" src/components/common/DataTable.vue`
Expected: 命中定义处与 `getAttentionStageDisplayText`（L811-814）

- [ ] **Step 2: 改词表为后端同源五态词**

把 `localAttentionStageLabels` 的映射改为（与 `STAGE_LABELS` 逐字一致）：

```ts
// 2026-09-10 口径统一（spec §3）：周期列词表必须与后端 STAGE_LABELS 逐字一致，不再自维护第二套
// （历史：本文件用"冷却"而 statusClassifier 用"降温"）。
const localAttentionStageLabels: Record<string, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
}
```

- [ ] **Step 3: 跑测试**

Run: `cd D:\dragon-board; pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts`
Expected: PASS（该文件 L204 的源码断言引用 `getAttentionStageDisplayText`，保持不动）

- [ ] **Step 4: 提交**

Run: `cd D:\dragon-board && git add src/components/common/DataTable.vue && git commit -m "refactor(displayStatus): DataTable stage labels match backend vocabulary"`

---

### Task 7: 数据迁移（重投影 + 重算）

**Files:** 无代码改动；执行两条 CLI

- [ ] **Step 1: 重投影 978 帧的 displayStatus**

Run:
```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli snapshot-analysis-backfill `
  --dataset-id dragonboard_live --snapshot-type half_hour `
  --start-date 2026-01-01 --limit 0 --workers 6 --apply
```
Expected: JSON 输出 `ok=true`、`frameCount=978`、`totalWritten > 0`；进度写 stderr

- [ ] **Step 2: 校验投影结构**

Run:
```powershell
cd D:\dragon-board\quant-board
$code = @'
from pymongo import MongoClient
from backend.core.settings import get_settings
db = MongoClient(get_settings().mongodb_uri)[get_settings().mongodb_database]
doc = db["snapshot_analysis"].find_one({"snapshotId": "half_hour:2026-09-10:15:30"})
print("FIELDS", sorted((doc.get("analysis") or {}).get("displayStatus").keys()))
'@
$code | .\.venv\Scripts\python.exe -
```
Expected: `FIELDS ['label', 'stage', 'tooltip']`

- [ ] **Step 3: 重算 142 天 EOD 文档**

Run:
```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli hotlist-sentiment-recompute `
  --dataset-id dragonboard_live --snapshot-type half_hour --days 0 --apply
```
Expected: `days=142`；每天 `after.stageCounts` 六桶之和 = 全池行数

- [ ] **Step 4: 校验恒等式**

Run:
```powershell
cd D:\dragon-board\quant-board
$code = @'
from pymongo import MongoClient
from backend.core.settings import get_settings
db = MongoClient(get_settings().mongodb_uri)[get_settings().mongodb_database]
bad = []
for doc in db["hotlist_sentiment"].find({"snapshotType": "half_hour", "slotTime": "EOD"}):
    sc = (((doc.get("metrics") or {}).get("layers") or {}).get("all") or {}).get("stageCounts") or {}
    total = (doc.get("metrics") or {}).get("total")
    if total is not None and sum(sc.values()) != total:
        bad.append([doc.get("tradingDate"), sum(sc.values()), total])
print("MISMATCH", bad[:10], "COUNT", len(bad))
'@
$code | .\.venv\Scripts\python.exe -
```
Expected: `MISMATCH [] COUNT 0`

- [ ] **Step 5: 提交迁移记录**

Run: `cd D:\dragon-board && git commit --allow-empty -m "chore(displayStatus): migrate snapshot_analysis projection and hotlist stageCounts"`

---

### Task 8: 验收（含真实浏览器逐股核对）

**Files:** 无代码改动

- [ ] **Step 1: 后端测试子集**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_display_status.py tests/test_display_status_reconciliation.py tests/test_hotlist_sentiment_compute.py tests/test_snapshot_analysis_insufficient.py tests/test_snapshot_analysis_service.py tests/test_snapshot_analysis_backfill.py tests/test_snapshot_read_api.py tests/test_snapshot_post_save_hooks.py -q --tb=short -rf -p no:cacheprovider`
Expected: 全部 PASS

- [ ] **Step 2: 收集检查（确认无 import 断裂）**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest --collect-only -q 2>&1 | Select-Object -Last 3`
Expected: 形如 `2010 tests collected`，exit 0

- [ ] **Step 3: 前端测试与类型检查**

Run: `cd D:\dragon-board; pnpm test`
Expected: 全绿

Run: `cd D:\dragon-board; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 0 error

- [ ] **Step 4: 真实浏览器验收（必须）**

用 `playwright-cli` 打开主看板（`http://localhost:5173`），确认：

1. **DragonBreathPanel 全池状态结构为 6 格**，标签逐字为：点火 / 扩散 / 拥挤 / 反转 / 冷却 / 无阶段；
2. **6 格数值 ≡ 行情表周期列同池逐股统计** —— 逐股核对，不接受只对合计。核对方法：读页面 DOM 取 6 格数值；再从行情表逐行取 `cycle.stage` 统计同一池（池口径 = 面板 `total`）；
3. 底部覆盖率行仍显示 `golden 判定 N / fallback 接管 M`；
4. 周期列遇 `meta.sampleQuality.status === 'insufficient'` 仍有灰框"样本不足"；
5. **控制台 0 报错**；
6. 截图存档到 `docs/superpowers/plans/`（临时产物，验完删除）。

Expected: 6 格数值与逐股统计完全一致；控制台无错误

- [ ] **Step 5: 记录验收证据并提交**

Run: `cd D:\dragon-board && git commit --allow-empty -m "test(displayStatus): acceptance evidence for stage projection"`

---

### Task 9: 文档同步

**Files:**
- Modify: `docs/ranktrend/lifecycle-layering-contract.md`（展示状态节）
- Modify: `quant-board/docs/api-cli.md`（displayStatus 结构 + stageCounts + 迁移指引）
- Modify: `quant-board/docs/architecture.md`（口径同步）

- [ ] **Step 1: 改 `lifecycle-layering-contract.md`**

把展示状态节改写为恒等式口径：

- 删除被证伪的对账等式（`转弱预警 220 = cooling 213 − 强资确认 5 + reversal 12` 等）；
- 写入新恒等式：`sum(stageCounts) == 全池行数`，且每行 `label == STAGE_LABELS[cycle.stage]`；
- 写明"词表单一来源在后端 `STAGE_LABELS`，前端只消费"。

- [ ] **Step 2: 改 `api-cli.md`**

- `GET /api/snapshots/analysis` 小节：`displayStatus` 结构改为 `{stage, label, tooltip}`（stage 可为 null）；
- `hotlist-sentiment-recompute` 小节：输出摘要改为 `stageCounts` / `statusSourceCounts`（删 `statusMissing`）；
- 补一句迁移指引：本结构变更需重跑 `snapshot-analysis-backfill --apply` + `hotlist-sentiment-recompute --days 0 --apply`。

- [ ] **Step 3: 改 `architecture.md`**

把"8 类展示状态"表述改为"生命周期 5 态（+ 无阶段）纯投影"，并注明分类层已按 spec §10 删除。

- [ ] **Step 4: 提交**

Run: `cd D:\dragon-board && git add docs quant-board/docs && git commit -m "docs(displayStatus): stage projection contract and migration"`

---

## Self-Review（写完计划后自查）

**1. Spec 覆盖**

| Spec 节 | 对应 Task |
| --- | --- |
| §3 后端契约（含删除/继承/`_is_invalid_quote`） | Task 1 |
| §4 计数契约（含 `unknown`/`fallback` 归桶/`_insufficient_entries`） | Task 2、Task 3 |
| §5 前端契约 | Task 4、Task 5、Task 6 |
| §6 数据迁移 | Task 7 |
| §7 测试与验收（含 playwright 逐股） | Task 8 |
| §8 新旧对照 | Task 2（`statusCounts` 删除）、Task 3（无阶段行）、Task 5（6 格） |
| §9 风险（回测耦合） | Task 0 |
| §10 变更清单 | 文件结构表覆盖全部条目 |
| §7.5 文档三处 | Task 9 |

**2. 占位符扫描**：所有代码步骤均给出完整代码；仅三处要求实施者"按 grep 结果确认变量名/补齐空值保护"（Task 2 Step 4、Task 4 Step 5、Task 5 Step 3 第 6 项），这些是**读取现状的必须动作**，已给出精确 grep 命令与预期命中，不是"待补细节"。

**3. 类型一致性**：`RankTrendDisplayStatus`（前端）/ `displayStatus` 三字段（后端）/ `HotListStageKey` + `HOT_LIST_STAGE_LABELS`（类型）/ `stageClassKey(stage)` 在 Task 4 定义，Task 5 复用；`build_stage_counts` 在 Task 2 定义并测试；`_insufficient_entries` 在 Task 3 改为调 `compute_display_status` —— 名称前后一致。

**4. 未闭环项（已知，需在上线日人工确认）**

- `expansion` 桶长期为 0（引擎现状）；
- `unknown` 桶在历史帧占比明显（无有效 `avgRankNum` 的行），近期帧接近 0；
- 回测侧 `statusCounts` 的处理结论（Task 0）。
