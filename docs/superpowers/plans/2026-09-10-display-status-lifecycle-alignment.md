# 展示状态口径统一（displayStatus 以 lifecycle.stage 主轴）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 面板 8 类状态成为生命周期 5 态的确定性细化（样本/资金/风险修正层），candidateTier 完全退出展示状态生产，前端删除本地兜底级联只消费后端数据。

**Architecture:** 后端 `compute_display_status` 重写为「样本质量门 → 风险修正层 → stage 主轴 → 兜底」级联（修复 `meta.sampleQuality.status` 读取 bug）；TS `statusClassifier.ts` 收敛为纯消费 + label 映射；DataTable 周期列补样本不足显示；DragonBreathPanel 透出 statusSourceCounts。引擎（cycle/candidateTier/synergy 计算）零改动，golden 零漂移。

**Tech Stack:** Python（FastAPI 后端纯函数）+ pytest；Vue 3 `<script setup>` + TypeScript + Vitest；playwright-cli 浏览器验收。

**Spec:** `docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md`（§3 新级联合同、§4 配套修正、§5 前端纯消费、§7 测试策略）

## Global Constraints

- **golden 引擎零漂移**：不修改 `engine/runtime.py`、`analyze_cycle`、`compose_analysis_candidate_tier`、synergy 计算；只改 `trend/display_status.py` 这个消费侧纯函数。
- **8 标签枚举与输出结构不变**：`主升确认/点火观察/强资确认/新入观察/高位拥挤/资金背离/转弱预警/样本不足`；`displayStatus = {label, classKey, tooltip}` 结构不变；`statusCounts`/`snapshot_analysis.displayStatus`/join 链路合同零变更。
- **candidateTier 不参与展示状态生产**（前后端一致）；reversal 无条件转弱预警；cooling 保留强资修正（`zlje>0 且 zljzb≥8` 且 `volumePrice.signalTier ∈ {A,B}` → 强资确认）。
- **前端不兜底**：TS 删除本地级联，后端 displayStatus 缺失时返回结构化未知态 `{label:'未知', classKey:'unknown', tooltip:'后端 displayStatus 缺失（旧缓存/离线）。'}`。
- **quant-board 全量 pytest 挂起**（test_archive_research.py 卡死，本机已知）：只用 collect-only + 相关子集验证。
- **TDD 顺序不可跳过**：每个任务先写/改测试 → 跑 RED → 实现 → 跑 GREEN → 提交。
- **bash cwd 会重置**：每条命令显式 `cd /d/dragon-board/...` 前缀；pytest 用 `./.venv/Scripts/python.exe`。
- **禁止** `rm -rf`、`git reset --hard`、批量删除；一次只删明确路径文件。
- 全程中文沟通；每个任务独立 commit（不携带用户未提交的无关改动：`.claude/settings*.json`、`src/stores/ui.ts`、`quant-board/backend/operations/optimize_gate_denoise_parameters.py`、`quant-board/docs/ranktrend-tier-backtest/*`、`quant-board/backend/analysis/ranktrend/research/regime_saex.py`、`quant-board/backend/operations/diagnose_*.py`、`quant-board/tests/test_regime_saex.py`）。

---

### Task 1: 后端 compute_display_status 重写（TDD，含 sampleQuality.status bug 修复）

**Files:**
- Rewrite: `quant-board/backend/analysis/ranktrend/trend/display_status.py`（现 97 行）
- Rewrite: `quant-board/tests/test_display_status.py`（现 90 行 8 用例）

**Interfaces:**
- Consumes: `analysis` dict（`meta.sampleQuality.status` / `meta.sampleStatus`(legacy) / `cycle.stage` / `observation.synergy.state` / `observation.volumePrice.signalTier` / `strategy.candidateTier`（仅透传给前端，不参与判定））+ `stock` dict（`zlje`/`zljzb`/`price`/`latestPrice`/`lastPrice`/`close`/`turnover`）。
- Produces: `compute_display_status(analysis: dict, stock: dict) -> dict[str, str]`，键 `label/classKey/tooltip`，签名不变（调用点 `backend/api/ranktrend_routes.py:453-455` 零改动）。
- 供 Task 2 对账测试消费：纯 stage 批次的 8 类聚合可对账回 5 态。

- [ ] **Step 1: 重写测试文件（RED）**

用以下内容完整替换 `quant-board/tests/test_display_status.py`：

```python
# -*- coding: utf-8 -*-
"""display_status 后端状态分类单测（2026-09-10 口径统一：lifecycle.stage 主轴）。

合同见 docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md §3：
candidateTier 退出展示状态生产；样本质量门读 meta.sampleQuality.status（修复原
flat meta.sampleStatus 读取 bug）；风险修正层优先于 stage 主轴；cooling 保留强资修正。
"""
from itertools import product

import pytest

from backend.analysis.ranktrend.display_status import compute_display_status

_UI_KNOWN_KEYS = {
    "main_confirmed",
    "ignition_watch",
    "weakening",
    "new_watch",
    "crowded",
    "money_divergence",
    "strong_money",
    "insufficient",
}


def _analysis(
    *,
    stage=None,
    sample_quality=None,
    flat_sample_status=None,
    synergy_state=None,
    signal_tier=None,
    candidate_tier=None,
):
    meta = {}
    if sample_quality is not None:
        meta["sampleQuality"] = {"status": sample_quality}
    if flat_sample_status is not None:
        meta["sampleStatus"] = flat_sample_status
    observation = {}
    if synergy_state is not None:
        observation["synergy"] = {"state": synergy_state}
    if signal_tier is not None:
        observation["volumePrice"] = {"signalTier": signal_tier}
    analysis = {"meta": meta, "observation": observation}
    if stage is not None:
        analysis["cycle"] = {"stage": stage}
    if candidate_tier is not None:
        analysis["strategy"] = {"candidateTier": candidate_tier}
    return analysis


def _stock(**kw):
    base = {"price": 10.0, "turnover": 5e8, "zlje": 0.0, "zljzb": 1.0}
    base.update(kw)
    return base


def test_sample_quality_gate_reads_nested_sample_quality_field():
    # 引擎真实字段是 meta.sampleQuality.status（engine/runtime.py sample_status）；
    # 原实现只读 flat meta.sampleStatus，insufficient 门在主链恒不触发——本用例锁修复。
    r = compute_display_status(
        _analysis(stage="cooling", sample_quality="insufficient", candidate_tier="A_MAIN"),
        _stock(zlje=1e8, zljzb=12.0),
    )
    assert r["label"] == "样本不足"
    assert r["classKey"] == "insufficient"


def test_legacy_flat_sample_status_still_honored():
    # 历史 fixture 兼容：flat meta.sampleStatus 仍作为回退读取
    r = compute_display_status(_analysis(stage="expansion", flat_sample_status="insufficient"), _stock())
    assert r["label"] == "样本不足"


def test_sample_gate_wins_over_strong_money_and_volume():
    r = compute_display_status(
        _analysis(sample_quality="insufficient", signal_tier="A"),
        _stock(zlje=6.8e8, zljzb=21),
    )
    assert r["label"] == "样本不足"


def test_invalid_quote_maps_to_insufficient():
    assert compute_display_status(_analysis(stage="expansion"), _stock(price=0))["label"] == "样本不足"
    assert compute_display_status(_analysis(stage="expansion"), _stock(turnover=-1))["label"] == "样本不足"
    # 集合竞价成交额 0 不算无效行情
    r = compute_display_status(_analysis(stage="expansion"), _stock(turnover=0))
    assert r["label"] == "主升确认"


def test_risk_upgrade_beats_stage_axis():
    r = compute_display_status(_analysis(stage="expansion", synergy_state="风险升级"), _stock())
    assert r["label"] == "转弱预警"


def test_doubt_with_negative_zljzb_maps_to_money_divergence():
    # 风险修正层覆盖 stage 主轴（存疑 + 主力净流出，即使 expansion）
    r = compute_display_status(_analysis(stage="expansion", synergy_state="存疑", signal_tier="A"), _stock(zlje=1e8, zljzb=-9))
    assert r["label"] == "资金背离"


def test_doubt_without_zljzb_keeps_stage_axis():
    # zljzb 缺失/为正 → 不触发资金背离，落回 stage 主轴
    r = compute_display_status(_analysis(stage="expansion", synergy_state="存疑"), _stock())
    assert r["label"] == "主升确认"
    r2 = compute_display_status(_analysis(stage="expansion", synergy_state="存疑", signal_tier="A"), _stock(zlje=1e8, zljzb=9))
    assert r2["label"] == "主升确认"


@pytest.mark.parametrize(
    "stage,label,class_key",
    [
        ("ignition", "点火观察", "ignition_watch"),
        ("expansion", "主升确认", "main_confirmed"),
        ("crowded", "高位拥挤", "crowded"),
        ("reversal", "转弱预警", "weakening"),
    ],
)
def test_stage_axis_mapping(stage, label, class_key):
    r = compute_display_status(_analysis(stage=stage), _stock())
    assert r["label"] == label
    assert r["classKey"] == class_key


def test_cooling_without_support_maps_to_weakening():
    r = compute_display_status(_analysis(stage="cooling"), _stock())
    assert r["label"] == "转弱预警"


def test_cooling_with_strong_money_and_volume_maps_to_strong_money():
    r = compute_display_status(
        _analysis(stage="cooling", signal_tier="B"),
        _stock(zlje=2.4e8, zljzb=18),
    )
    assert r["label"] == "强资确认"
    assert r["classKey"] == "strong_money"
    assert "注意力轨迹回落" in r["tooltip"] and "资金确认仍在" in r["tooltip"]


def test_cooling_strong_money_requires_volume_support():
    # 强资金但量能不承接（D=走弱）→ 转弱预警
    r = compute_display_status(_analysis(stage="cooling", signal_tier="D"), _stock(zlje=2.4e8, zljzb=18))
    assert r["label"] == "转弱预警"


def test_cooling_volume_support_alone_not_enough():
    # 量能承接但非强资金（zljzb < 8 或 zlje ≤ 0）→ 转弱预警
    assert compute_display_status(_analysis(stage="cooling", signal_tier="A"), _stock(zlje=1e8, zljzb=7))["label"] == "转弱预警"
    assert compute_display_status(_analysis(stage="cooling", signal_tier="A"), _stock(zlje=-1e7, zljzb=12))["label"] == "转弱预警"


def test_missing_stage_with_strong_money_and_volume():
    # stage 缺失：资金确认兜底为强资确认
    r = compute_display_status(_analysis(signal_tier="A"), _stock(zlje=6.8e8, zljzb=21))
    assert r["label"] == "强资确认"


def test_missing_stage_falls_back_to_new_watch():
    # stage 缺失且无资金确认 → 新入观察（fail-visible，不伪造 stage）
    r = compute_display_status(_analysis(), _stock())
    assert r["label"] == "新入观察"
    assert r["classKey"] == "new_watch"


def test_invalid_stage_enum_falls_back():
    # 非法枚举值等同缺失，走第 4/5 步
    r = compute_display_status(_analysis(stage="garbage"), _stock())
    assert r["label"] == "新入观察"


def test_candidate_tier_never_drives_display_status():
    # 合同核心：candidateTier 完全退出展示状态生产
    assert compute_display_status(_analysis(stage="cooling", candidate_tier="A_MAIN"), _stock())["label"] == "转弱预警"
    assert compute_display_status(_analysis(stage="cooling", candidate_tier="D_EXIT_RISK"), _stock(zlje=2.4e8, zljzb=18))["label"] == "转弱预警"
    assert compute_display_status(_analysis(stage="expansion", candidate_tier="N_NEUTRAL"), _stock())["label"] == "主升确认"
    assert compute_display_status(_analysis(candidate_tier="C_CROWDED"), _stock())["label"] == "新入观察"


def test_ui_class_keys_stay_in_known_whitelist():
    stages = ["ignition", "expansion", "crowded", "reversal", "cooling", None]
    tiers = ["A_MAIN", "D_EXIT_RISK", None]
    states = ["启动确认", "风险升级", "存疑", "主升确认", None]
    for stage, tier, state in product(stages, tiers, states):
        analysis = _analysis(stage=stage, candidate_tier=tier, synergy_state=state)
        stock = _stock(zlje=6.8e8, zljzb=21)
        key = compute_display_status(analysis, stock)["classKey"]
        assert key in _UI_KNOWN_KEYS, f"stage={stage} tier={tier} state={state} -> {key}"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_display_status.py -v
```

预期：FAIL/ERROR（新级联用例失败：candidateTier 仍驱动、sampleQuality.status 不被读取等；旧实现里 `test_stage_axis_mapping` 等大量失败）。

- [ ] **Step 3: 重写实现（GREEN）**

用以下内容完整替换 `quant-board/backend/analysis/ranktrend/trend/display_status.py`：

```python
# -*- coding: utf-8 -*-
"""状态分类 displayStatus 后端生产（2026-09-10 口径统一：lifecycle.stage 主轴）。

2026-08-23 G2 版本以 candidateTier（交易候选资格）为主键；生命周期门控多轮优化
（regime 环境门/动量阈值/gate 去噪）收紧后大量个股落入 N_NEUTRAL，展示状态漂移成
"新入观察"，与周期列 5 态（analyze_cycle 纯排名轨迹）脱钩。现按 spec 重构：
candidateTier 完全退出展示状态生产，lifecycle.stage 成为主轴——面板 8 类成为 5 态的
确定性细化（样本/资金/风险修正层），后续门控优化不再改变展示分布。

spec: docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md §3

级联（按序判定，命中即返回；label/classKey/tooltip 输出结构不变）：
  1. 样本质量门: meta.sampleQuality.status=insufficient（兼容 flat meta.sampleStatus）
     或无效行情（价格非有限/≤0、成交额非有限/<0）           → 样本不足
  2. 风险修正层: synergy.state=风险升级                      → 转弱预警
                synergy.state=存疑 且 zljzb ≤ 0              → 资金背离
  3. stage 主轴: ignition   → 点火观察
                expansion  → 主升确认
                crowded    → 高位拥挤
                reversal   → 转弱预警
                cooling    → 强资金+量能承接 → 强资确认；否则 → 转弱预警
  4. stage 缺失/非法: 强资金+量能承接 → 强资确认；否则        → 新入观察（fail-visible，不伪造 stage）
  5. 兜底                                                    → 新入观察

  注：原实现读 flat meta.sampleStatus，而引擎真实写入 meta.sampleQuality.status
  （engine/runtime.py sample_status），insufficient 门在主链恒不触发——本版一并修复。
"""
from __future__ import annotations

import math
from typing import Any

_STATUS = {
    "insufficient": ("样本不足", "insufficient", "历史样本不足，暂不判定状态。"),
    "weakening": ("转弱预警", "weakening", "撤退/转弱信号，注意风险。"),
    "crowded": ("高位拥挤", "crowded", "高位拥挤，警惕回落。"),
    "main_confirmed": ("主升确认", "main_confirmed", "主升扩散确认，趋势向上。"),
    "ignition_watch": ("点火观察", "ignition_watch", "点火启动，观察是否扩散。"),
    "strong_money": ("强资确认", "strong_money", "资金明显介入，但趋势样本仍需确认，重点看后续留榜和资金持续。"),
    "money_divergence": ("资金背离", "money_divergence", "热度仍在但主力资金不支撑，警惕诱多。"),
    "new_watch": ("新入观察", "new_watch", "无明确信号，继续观察。"),
}

_STAGE_KEYS = {
    "ignition": "ignition_watch",
    "expansion": "main_confirmed",
    "crowded": "crowded",
    "reversal": "weakening",
}


def _make(key: str) -> dict[str, str]:
    label, class_key, tooltip = _STATUS[key]
    return {"label": label, "classKey": class_key, "tooltip": tooltip}


def _is_strong_money(stock: dict[str, Any]) -> bool:
    """强资金：主力净额 > 0 且 zljzb ≥ 8%（原 G2 口径不变）。"""
    try:
        zlje = float(stock.get("zlje"))
        zljzb = float(stock.get("zljzb"))
    except (TypeError, ValueError):
        return False
    return zlje > 0 and zljzb >= 8


def _is_volume_supported(analysis: dict[str, Any]) -> bool:
    """量能承接：volumePrice.signalTier ∈ {A 放量上涨+资金流入, B 放量上涨/量价配合}，
    排除过热(E 对倒/过度放量)与走弱(D)。"""
    vp = (analysis.get("observation") or {}).get("volumePrice") or {}
    return str(vp.get("signalTier") or "") in ("A", "B")


def _finite_non_positive(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number <= 0
    except (TypeError, ValueError):
        return False


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _is_invalid_quote(stock: dict[str, Any]) -> bool:
    """无效行情：价格类字段非有限/≤0（字段存在时），或成交额非有限/<0（0 允许，集合竞价）。"""
    price = next(
        (stock[k] for k in ("price", "latestPrice", "lastPrice", "close") if _has_value(stock.get(k))),
        None,
    )
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


def _sample_status(analysis: dict[str, Any]) -> str:
    # 引擎真实字段是 meta.sampleQuality.status；flat meta.sampleStatus 为历史 fixture 兼容回退。
    meta = analysis.get("meta") or {}
    quality = meta.get("sampleQuality") if isinstance(meta.get("sampleQuality"), dict) else {}
    return str(quality.get("status") or meta.get("sampleStatus") or "ok")


def compute_display_status(
    analysis: dict[str, Any],
    stock: dict[str, Any],
) -> dict[str, str]:
    """基于后端已有 golden 字段生产 displayStatus（label/classKey/tooltip）。"""
    observation = analysis.get("observation") or {}
    synergy = observation.get("synergy") or {}

    # 1. 样本质量门（数据质量声明优先，强资金/量能不豁免）
    if _sample_status(analysis) == "insufficient" or _is_invalid_quote(stock):
        return _make("insufficient")

    # 2. 风险修正层（风险优先于机会）
    state = str(synergy.get("state") or "")
    if state == "风险升级":
        return _make("weakening")
    if state == "存疑" and _finite_non_positive(stock.get("zljzb")):
        return _make("money_divergence")

    # 3. stage 主轴（candidateTier 已退出展示状态生产）
    stage = str((analysis.get("cycle") or {}).get("stage") or "")
    if stage == "cooling" and _is_strong_money(stock) and _is_volume_supported(analysis):
        return {
            "label": _STATUS["strong_money"][0],
            "classKey": _STATUS["strong_money"][1],
            "tooltip": "注意力轨迹回落，但资金确认仍在，继续看后续留榜与承接。",
        }
    stage_key = _STAGE_KEYS.get(stage)
    if stage_key:
        return _make(stage_key)

    # 4/5. stage 缺失或非法枚举：资金确认后兜底（fail-visible，不伪造 stage）
    if _is_strong_money(stock) and _is_volume_supported(analysis):
        return _make("strong_money")
    return _make("new_watch")
```

注意：`strategy.candidateTier` 仍随 `analysis` 透传给前端（`ranktrend_routes.py:455` 附加逻辑不变），只是本函数不再读它。

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_display_status.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 跑相邻子集防回归**

```bash
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py tests/test_snapshot_analysis.py tests/test_snapshot_analysis_service.py -v
```

预期：PASS（已核实：sentiment golden fixtures 不含 displayStatusLabel，走 fallback 路径，零变化；test_snapshot_analysis.py:50 / test_snapshot_analysis_service.py:96 只断言 displayStatus 键存在，不断言 label 内容，新级联下照常通过）。

- [ ] **Step 6: Commit**

```bash
cd /d/dragon-board && git add quant-board/backend/analysis/ranktrend/trend/display_status.py quant-board/tests/test_display_status.py
git commit -m "refactor(ranktrend): displayStatus 重写为 lifecycle.stage 主轴级联——candidateTier 退出展示状态生产（spec §3，修复 sampleQuality.status 读取 bug）"
```

---

### Task 2: 8 类 ↔ 5 态对账测试（防止两套口径再漂移）

**Files:**
- Create: `quant-board/tests/test_display_status_reconciliation.py`

**Interfaces:**
- Consumes: Task 1 的 `compute_display_status`；`backend.analysis.hotlist.sentiment` 的 `sort_rows` / `build_day_metrics_from_sorted`（现 L40/L228）与 `STATUS_LABELS`（L17）。
- Produces: 面板 `statusCounts`（8 类）按映射聚合 = 周期列 5 态计数的对账合同测试。映射：`主升确认=expansion`、`点火观察=ignition`、`高位拥挤=crowded`、`转弱预警=reversal+cooling(无承接)`；修正类（样本不足/资金背离/强资确认）单列可见，不并入 5 态。

- [ ] **Step 1: 写对账测试**

创建 `quant-board/tests/test_display_status_reconciliation.py`：

```python
# -*- coding: utf-8 -*-
"""对账测试：展示状态 8 类按映射聚合 = 生命周期 5 态计数（spec §7）。

面板 statusCounts 与周期列 stage 分布必须可对账，防止两套口径再漂移。
纯 stage 批次（无样本/资金/风险修正）：点火观察→ignition、主升确认→expansion、
高位拥挤→crowded、转弱预警→reversal+cooling；修正类（样本不足/资金背离/
强资确认）与兜底类（新入观察）单列可见，不并入 5 态。
"""
from backend.analysis.hotlist.sentiment import build_day_metrics_from_sorted, sort_rows
from backend.analysis.ranktrend.display_status import compute_display_status


def _label(stage, sample_quality="ok", synergy_state=None, zljzb=1.0, signal_tier=None):
    analysis = {
        "meta": {"sampleQuality": {"status": sample_quality}},
        "observation": {"synergy": {"state": synergy_state} if synergy_state else {}},
        "cycle": {"stage": stage},
    }
    if signal_tier:
        analysis["observation"]["volumePrice"] = {"signalTier": signal_tier}
    return compute_display_status(analysis, {"zlje": 1e8, "zljzb": zljzb})["label"]


def _counts(labels):
    rows = [
        {"code": f"00000{i + 1}", "compRank": i + 1, "displayStatusLabel": label}
        for i, label in enumerate(labels)
    ]
    return build_day_metrics_from_sorted(sort_rows(rows), len(rows))["statusCounts"]


def test_pure_stage_batch_aggregates_back_to_stage_counts():
    counts = _counts(
        _label(stage)
        for stage in ["ignition", "ignition", "expansion", "crowded", "reversal", "cooling"]
    )
    assert counts["点火观察"] == 2
    assert counts["主升确认"] == 1
    assert counts["高位拥挤"] == 1
    assert counts["转弱预警"] == 2  # reversal 1 + cooling 1（无强资承接）
    for label in ("强资确认", "新入观察", "资金背离", "样本不足"):
        assert counts[label] == 0


def test_correction_labels_stay_visible_without_polluting_stage_axis():
    counts = _counts(
        [
            _label("reversal", sample_quality="insufficient"),          # 修正类：样本不足
            _label("expansion", synergy_state="存疑", zljzb=-9.0),      # 修正类：资金背离
            _label("expansion"),                                        # 主轴：主升确认
            _label("cooling", signal_tier="A", zljzb=12.0),             # cooling 强资修正
        ]
    )
    assert counts["样本不足"] == 1   # 修正类可见，不并入转弱预警
    assert counts["资金背离"] == 1   # 修正类可见，不并入主升确认
    assert counts["主升确认"] == 1
    assert counts["强资确认"] == 1   # cooling 强资修正单列
    assert counts["转弱预警"] == 0
```

- [ ] **Step 2: 跑测试**

```bash
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_display_status_reconciliation.py -v
```

预期：PASS（依赖 Task 1 已落地；若失败说明 Task 1 级联与对账合同有出入，回到 Task 1 修）。

- [ ] **Step 3: Commit**

```bash
cd /d/dragon-board && git add quant-board/tests/test_display_status_reconciliation.py
git commit -m "test(ranktrend): 补 8 类↔5 态对账合同测试——纯 stage 批次聚合可对账、修正类单列可见（spec §7）"
```

---

### Task 3: 前端纯消费收敛（statusClassifier.ts 删兜底级联 + compat.ts + RankTrendPanel.vue）

**Files:**
- Modify: `src/services/rankTrend/types.ts`（RankTrendAnalysisResult 增加可选 `displayStatus` 字段，约 L355 前后）
- Rewrite: `src/services/rankTrend/statusClassifier.ts`（540 行 → 约 130 行）
- Modify: `src/services/rankTrend/compat.ts:4-14`（re-export 清单收敛）
- Modify: `src/components/panels/RankTrendPanel.vue`（L335-338 imports、L674 签名、L681 调用、L784-787 statusContext 构建）
- Rewrite: `src/services/rankTrend/__tests__/statusClassifier.test.ts`（717 行 → 约 120 行）

**Interfaces:**
- Consumes: 后端 `analysis.displayStatus`（Task 1 生产）。
- Produces: `getRankTrendDisplayStatus(rankTrend?: RankTrendAnalysisResult | null): RankTrendDisplayStatus`（单参！直通+未知态）；`getRankTrendDisplayBreakdown(rankTrend?): RankTrendDisplayBreakdown`（单参！字段与现版完全一致：`qualityLabel/qualityBadgeLabel/showQualityBadge/cycleLabel/tierLabel/displayStatusLabel/candidateTierKey/candidateTierLabel/riskLabel/tooltip/classKeys{quality,cycle,tier,displayStatus,risk}`）。RankTrendPanel 消费 `breakdown.tierLabel/classKeys.tier/displayStatusLabel/riskLabel/qualityLabel/cycleLabel`（L710-715，零改动）。
- 删除的导出：`buildRankTrendStatusContext`、`buildRankTrendStatusContextFromMarketPercentiles`、`classifyVolumeConfirmation`、`type RankTrendStatusContext`、`type VolumeConfirmation`（已核实消费方仅 compat.ts re-export、RankTrendPanel.vue、statusClassifier.test.ts 自身）。

- [ ] **Step 1: 重写 statusClassifier.test.ts（RED）**

用以下内容完整替换 `src/services/rankTrend/__tests__/statusClassifier.test.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { getRankTrendDisplayBreakdown, getRankTrendDisplayStatus } from '../statusClassifier'
import type { RankTrendAnalysisResult } from '../types'

// 2026-09-10 口径统一：前端只消费后端 displayStatus，不做任何本地分类。
// 本文件是消费合同测试：直通、未知态、breakdown 纯 label 映射。
function createRankTrend(input: {
  tier?: NonNullable<RankTrendAnalysisResult['strategy']>['candidateTier']
  sampleStatus?: NonNullable<RankTrendAnalysisResult['meta']['sampleQuality']>['status']
  stage?: RankTrendAnalysisResult['cycle']['stage']
  displayStatus?: { label: string; classKey?: string; tooltip?: string }
}): RankTrendAnalysisResult {
  const analysis = {
    meta: {
      code: '300001',
      currentRank: 18,
      currentPercentile: 80,
      change: 3,
      rawChange: 0,
      updateTime: 1,
      sampleQuality: {
        snapshotType: 'half_hour' as const,
        sampleCount: 30,
        requiredSampleCount: 30,
        status: input.sampleStatus ?? ('ok' as const),
        delayedCount: 0,
        restoredCount: 0,
      },
    },
    technical: {
      movingAverage: { ma5: 0, ma10: 0, trend: 'steady' as const },
      macd: { dif: 0, dea: 0, histogram: 0, cross: 'none' as const, rawScore: 0, confirmed: false },
      signals: {
        direction: { signal: 'hold' as const, confidence: 50, score: 0 },
        acceleration: { signal: 'hold' as const, confidence: 50, score: 0 },
        zeroCross: { signal: 'hold' as const, confidence: 50, score: 0 },
      },
      momentumScore: 0,
      momentumProfile: { short: 0, mid: 0, long: 0, acceleration: 0, shock: 0, composite: 0 },
    },
    cycle: {
      rawStage: input.stage ?? ('cooling' as const),
      stage: input.stage ?? ('cooling' as const),
      previousStage: null,
      transition: 'cooling',
      confidence: 50,
      metrics: {
        rankVelocity: 0,
        rankAcceleration: 0,
        rankShock: 0,
        hotZoneStreak: 0,
        bestRecentRank: 18,
        drawdownFromPeak: 0,
        rankPathCommitment: 0,
      },
      entryAdvice: { bias: 'watch' as const, allowed: false, reason: '' },
    },
    risk: {
      overheat: { score: 0, signal: 'hold' as const, severity: 0 },
      divergence: { score: 0, signal: 'hold' as const, severity: 0 },
      pressure: 0,
      synergy: 0,
    },
    decision: {
      base: { signal: 'hold' as const, confidence: 50, combinedScore: 0, scoreMargin: 0 },
      final: { signal: 'hold' as const, confidence: 50 },
    },
    strategy: {
      regime: { state: 'normal' as const, score: 55, reasons: [] },
      momentum: { short: 0, mid: 0, long: 0, acceleration: 0, shock: 0, composite: 0 },
      candidateTier: input.tier ?? ('N_NEUTRAL' as const),
      action: 'hold' as const,
      reasons: [],
    },
  } as RankTrendAnalysisResult
  if (input.displayStatus) {
    ;(analysis as any).displayStatus = input.displayStatus
  }
  return analysis
}

describe('getRankTrendDisplayStatus（后端直通）', () => {
  it('有后端 displayStatus 时逐字透传 label/classKey/tooltip', () => {
    const status = getRankTrendDisplayStatus(
      createRankTrend({
        tier: 'A_MAIN',
        displayStatus: { label: '主升确认', classKey: 'main_confirmed', tooltip: '主升扩散确认，趋势向上。' },
      }),
    )
    expect(status).toEqual({ label: '主升确认', classKey: 'main_confirmed', tooltip: '主升扩散确认，趋势向上。' })
  })

  it('后端 classKey 缺省时回退 n_neutral', () => {
    const status = getRankTrendDisplayStatus(createRankTrend({ displayStatus: { label: '强资确认' } }))
    expect(status.classKey).toBe('n_neutral')
    expect(status.tooltip).toBe('')
  })

  it('后端缺失时返回结构化未知态，不做本地分类（fail-visible）', () => {
    const status = getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }))
    expect(status.label).toBe('未知')
    expect(status.classKey).toBe('unknown')
    expect(status.tooltip).toContain('displayStatus 缺失')
  })

  it('candidateTier 不再驱动前端展示状态（无 displayStatus → 未知，不是主升确认）', () => {
    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' })).label).toBe('未知')
    expect(getRankTrendDisplayStatus(null).label).toBe('未知')
  })
})

describe('getRankTrendDisplayBreakdown（纯 label 映射）', () => {
  it('把后端 displayStatus 拆成三栏投影，tier 与风险独立表达', () => {
    const breakdown = getRankTrendDisplayBreakdown(
      createRankTrend({
        tier: 'A_MAIN',
        sampleStatus: 'ok',
        stage: 'expansion',
        displayStatus: { label: '主升确认', classKey: 'main_confirmed', tooltip: '主升扩散确认，趋势向上。' },
      }),
    )
    expect(breakdown.qualityLabel).toBe('样本OK')
    expect(breakdown.showQualityBadge).toBe(false)
    expect(breakdown.qualityBadgeLabel).toBe('')
    expect(breakdown.cycleLabel).toBe('扩散')
    expect(breakdown.tierLabel).toBe('主升候选')
    expect(breakdown.displayStatusLabel).toBe('主升确认')
    expect(breakdown.riskLabel).toBe('正常')
    expect(breakdown.classKeys.quality).toBe('quality-ok')
    expect(breakdown.classKeys.cycle).toBe('cycle-expansion')
    expect(breakdown.classKeys.tier).toBe('candidate-main')
    expect(breakdown.classKeys.displayStatus).toBe('main_confirmed')
    expect(breakdown.classKeys.risk).toBe('risk-normal')
    expect(breakdown.tooltip).toContain('样本：样本OK')
    expect(breakdown.tooltip).toContain('周期：扩散')
    expect(breakdown.tooltip).toContain('生命周期：主升候选')
    expect(breakdown.tooltip).toContain('原始分层：A_MAIN / 主升候选')
    expect(breakdown.tooltip).toContain('展示状态：主升确认')
  })

  it('未知态时风险标签表达数据不足，不误报正常', () => {
    const breakdown = getRankTrendDisplayBreakdown(createRankTrend({ tier: 'A_MAIN' }))
    expect(breakdown.displayStatusLabel).toBe('未知')
    expect(breakdown.riskLabel).toBe('数据不足')
    expect(breakdown.classKeys.displayStatus).toBe('unknown')
    expect(breakdown.classKeys.risk).toBe('risk-unknown')
    expect(breakdown.tooltip).toContain('后端 displayStatus 缺失')
  })

  it('缺少 RankTrend 时质量标记样本不足、周期为空，不伪造生命周期', () => {
    const breakdown = getRankTrendDisplayBreakdown(null)
    expect(breakdown.qualityLabel).toBe('样本不足')
    expect(breakdown.cycleLabel).toBe('-')
    expect(breakdown.tierLabel).toBe('未知')
    expect(breakdown.displayStatusLabel).toBe('未知')
    expect(breakdown.riskLabel).toBe('数据不足')
    expect(breakdown.classKeys.quality).toBe('quality-insufficient')
    expect(breakdown.classKeys.cycle).toBe('cycle-empty')
  })

  it('sampleQuality 缺失时标记样本未知', () => {
    const rankTrend = createRankTrend({ tier: 'A_MAIN' })
    delete rankTrend.meta.sampleQuality
    const breakdown = getRankTrendDisplayBreakdown(rankTrend)
    expect(breakdown.qualityLabel).toBe('样本未知')
    expect(breakdown.classKeys.quality).toBe('quality-unknown')
  })
})
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /d/dragon-board && pnpm exec vitest run src/services/rankTrend/__tests__/statusClassifier.test.ts
```

预期：FAIL（现实现没有 displayStatus 时返回本地级联结果「主升确认」等，而非未知态；`getRankTrendDisplayStatus(null)` 现返回「样本不足」）。

- [ ] **Step 3: types.ts 增加可选 displayStatus 字段**

在 `src/services/rankTrend/types.ts` 的 `RankTrendAnalysisResult` 接口内、`executionStrategy?: RankTrendStrategyResult`（L354）之后追加：

```ts
  // 展示状态（2026-09-10 口径统一）：后端 compute_display_status 生产，前端只消费不分类
  displayStatus?: {
    label: string
    classKey: string
    tooltip: string
  }
```

- [ ] **Step 4: 重写 statusClassifier.ts（GREEN）**

用以下内容完整替换 `src/services/rankTrend/statusClassifier.ts`：

```ts
import type { RankTrendAnalysisResult } from './types'

export interface RankTrendDisplayStatus {
  label: string
  classKey: string
  tooltip: string
}

export interface RankTrendDisplayBreakdown {
  qualityLabel: string
  qualityBadgeLabel: string
  showQualityBadge: boolean
  cycleLabel: string
  tierLabel: string
  displayStatusLabel: string
  candidateTierKey: string
  candidateTierLabel: string
  riskLabel: string
  tooltip: string
  classKeys: {
    quality: string
    cycle: string
    tier: string
    displayStatus: string
    risk: string
  }
}

// 2026-09-10 口径统一（docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md §5）：
// 前端只消费后端生产的 displayStatus（lifecycle.stage 主轴），本地级联已删除；
// 后端缺失（旧缓存/离线）时返回结构化未知态，fail-visible，不伪造本地结论。
const UNKNOWN_STATUS: RankTrendDisplayStatus = {
  label: '未知',
  classKey: 'unknown',
  tooltip: '后端 displayStatus 缺失（旧缓存/离线）。',
}

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

const CYCLE_LABELS: Record<string, string> = {
  ignition: '启动',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '降温',
}

const RISK_LABELS: Record<string, string> = {
  crowded: '拥挤风险',
  money_divergence: '资金背离',
  weakening: '转弱预警',
  insufficient: '数据不足',
  unknown: '数据不足',
}

const RISK_CLASS_KEYS: Record<string, string> = {
  crowded: 'risk-crowded',
  money_divergence: 'risk-money_divergence',
  weakening: 'risk-weakening',
  insufficient: 'risk-insufficient',
  unknown: 'risk-unknown',
}

export function getRankTrendDisplayStatus(
  rankTrend?: RankTrendAnalysisResult | null,
): RankTrendDisplayStatus {
  // 后端直通：analysis.displayStatus 由 Python compute_display_status 生产（lifecycle.stage 主轴）。
  const backendStatus = rankTrend?.displayStatus
  if (backendStatus && typeof backendStatus.label === 'string') {
    return {
      label: backendStatus.label,
      classKey: backendStatus.classKey ?? 'n_neutral',
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
  const stage = rankTrend?.cycle?.stage ?? ''
  const candidateTierKey = rankTrend?.strategy?.candidateTier ? String(rankTrend.strategy.candidateTier) : ''
  const candidateTierLabel = candidateTierKey ? CANDIDATE_TIER_LABELS[candidateTierKey] ?? candidateTierKey : '-'
  const tierLabel = candidateTierKey ? CANDIDATE_TIER_SHORT_LABELS[candidateTierKey] ?? candidateTierKey : status.label
  const qualityLabel = SAMPLE_QUALITY_LABELS[sampleStatus] ?? '样本未知'
  const showQualityBadge = false
  const qualityBadgeLabel = ''
  const cycleLabel = stage ? CYCLE_LABELS[stage] ?? String(stage) : '-'
  const riskLabel = RISK_LABELS[status.classKey] ?? '正常'
  const tooltip = [
    `样本：${qualityLabel}`,
    `周期：${cycleLabel}`,
    `生命周期：${tierLabel}`,
    candidateTierKey ? `原始分层：${candidateTierLabel}` : '',
    `展示状态：${status.label}`,
    `实时风险：${riskLabel}`,
    status.tooltip,
  ].filter(Boolean).join('\n')

  return {
    qualityLabel,
    qualityBadgeLabel,
    showQualityBadge,
    cycleLabel,
    tierLabel,
    displayStatusLabel: status.label,
    candidateTierKey,
    candidateTierLabel,
    riskLabel,
    tooltip,
    classKeys: {
      quality: `quality-${sampleStatus}`,
      cycle: stage ? `cycle-${stage}` : 'cycle-empty',
      tier: candidateTierKey ? CANDIDATE_TIER_CLASS_KEYS[candidateTierKey] ?? 'candidate-unknown' : status.classKey,
      displayStatus: status.classKey,
      risk: RISK_CLASS_KEYS[status.classKey] ?? 'risk-normal',
    },
  }
}
```

- [ ] **Step 5: compat.ts re-export 清单收敛**

`src/services/rankTrend/compat.ts` 的 L4-14 export 块整体替换为：

```ts
export {
  getRankTrendDisplayBreakdown,
  getRankTrendDisplayStatus,
  type RankTrendDisplayBreakdown,
  type RankTrendDisplayStatus,
} from './statusClassifier'
```

- [ ] **Step 6: RankTrendPanel.vue 去 statusContext**

6a. L335-338 import 块（删除 buildRankTrendStatusContext / buildRankTrendStatusContextFromMarketPercentiles / type RankTrendStatusContext 三行，保留 getRankTrendDisplayBreakdown）：

```ts
  getRankTrendDisplayBreakdown,
```

6b. L670-675 `buildPanelStockView` 签名去掉第 4 参，L681 调用改单参：

```ts
function buildPanelStockView(
  stock: any,
  analysis: RankTrendResult | null,
  rank: number,
): PanelStockView {
```

```ts
  const breakdown = getRankTrendDisplayBreakdown(analysis)
```

6c. L784-787 删除 statusContext 构建，改回三参调用：

```ts
    currentStock.value = buildPanelStockView(sourceStock, analysis, rank)
```

- [ ] **Step 7: 跑测试 + 类型检查确认 GREEN**

```bash
cd /d/dragon-board && pnpm exec vitest run src/services/rankTrend/__tests__/statusClassifier.test.ts src/components/panels/__tests__/RankTrendPanel.test.ts
cd /d/dragon-board && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

预期：测试 PASS；vue-tsc 0 error（若报 statusContext 相关错误，说明还有遗漏消费点，按报错逐个清理——只允许删，不允许重建兜底）。

- [ ] **Step 8: Commit**

```bash
cd /d/dragon-board && git add src/services/rankTrend/types.ts src/services/rankTrend/statusClassifier.ts src/services/rankTrend/compat.ts src/components/panels/RankTrendPanel.vue src/services/rankTrend/__tests__/statusClassifier.test.ts
git commit -m "refactor(ranktrend): 前端展示状态收敛为纯消费——删除本地兜底级联与 statusContext，缺失返回结构化未知态（spec §5）"
```

---

### Task 4: DataTable 周期列样本不足显示（中性样式 + 排序归 hold）

**Files:**
- Modify: `src/components/common/DataTable.vue`（模板 L179-182、helpers L886-895、CSS L3167 后）
- Modify: `src/components/common/__tests__/DataTable.test.ts`（L152 断言 + 新增用例）

**Interfaces:**
- Consumes: `getRankTrendAnalysis(stock)`（DataTable 已 import）；`meta.sampleQuality.status === 'insufficient'`（后端 golden 字段）。
- Produces: 周期列三态渲染：样本不足（虚线灰框）→ stage 环境门标签 → `--`；`getLifecycleDirection` 对样本不足返回 `'hold'`；tooltip 阶段行同步显示「样本不足」。

- [ ] **Step 1: 更新源合同测试（RED）**

`src/components/common/__tests__/DataTable.test.ts` L152 断言替换：

```ts
    expect(source).toContain('v-else-if="getLifecycleStage(stock) != null"')
```

并在 `shows three independent observation columns with dedicated panel tracks` 测试之后新增用例：

```ts
  test('shows insufficient-sample label instead of misleading cooling stage in lifecycle column', () => {
    const source = dataTableSource()

    // 2026-09-10 口径统一（spec §4.1）：样本不足显示数据质量声明，不显示 lifecycle 兜底"冷却"
    expect(source).toContain('v-if="isLifecycleSampleInsufficient(stock)"')
    expect(source).toContain('v-else-if="getLifecycleStage(stock) != null"')
    expect(source).toContain('lifecycle-env-insufficient')
    expect(source).toContain("getRankTrendAnalysis(stock)?.meta?.sampleQuality?.status === 'insufficient'")
    expect(source).toContain('const isLifecycleSampleInsufficient')
    // 排序方向：样本不足按中性处理，不进买入/卖出方向组
    expect(source).toMatch(/const getLifecycleDirection = \(stock: any\) => \{\s*\n\s*if \(isLifecycleSampleInsufficient\(stock\)\) return 'hold'/)
    // tooltip 阶段行同步显示样本不足（与周期列一致，不出现同股两判）
    expect(source).toContain('isLifecycleSampleInsufficient(stock) ? \'样本不足\' : getAttentionStageDisplayText(getLifecycleStage(stock))')
  })
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /d/dragon-board && pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

预期：新用例 FAIL（旧模板只有 `v-if="getLifecycleStage(stock) != null"`，L152 旧断言也会因变成 v-else-if 而 FAIL——这正是修改点）。

- [ ] **Step 3: 实现模板与 helpers（GREEN）**

3a. `src/components/common/DataTable.vue` L179-182 模板块替换为：

```vue
                <!-- 样本不足（2026-09-10 口径统一）：数据质量声明优先于 lifecycle 兜底"冷却"，不再误导 -->
                <template v-if="isLifecycleSampleInsufficient(stock)">
                  <span class="lifecycle-env-insufficient">样本不足</span>
                </template>
                <template v-else-if="getLifecycleStage(stock) != null">
                  <span :class="lifecycleEnvClass(stock)">{{ getLifecycleStageLabel(stock) }}</span>
                </template>
                <span v-else class="trend-steady">--</span>
```

3b. L886-887 `getLifecycleStageLabel` 与其后新增 helper（tooltip 各调用点 L1028/L1178/L1309/L1328 自动同步显示「样本不足」）：

```ts
// 样本不足（2026-09-10 口径统一）：数据质量声明优先于 stage 兜底标签
const isLifecycleSampleInsufficient = (stock: any): boolean =>
  getRankTrendAnalysis(stock)?.meta?.sampleQuality?.status === 'insufficient'

const getLifecycleStageLabel = (stock: any) =>
  isLifecycleSampleInsufficient(stock) ? '样本不足' : getAttentionStageDisplayText(getLifecycleStage(stock))
```

3c. L890-895 `getLifecycleDirection` 增加样本不足守卫：

```ts
const getLifecycleDirection = (stock: any) => {
  if (isLifecycleSampleInsufficient(stock)) return 'hold'
  const stage = getLifecycleStage(stock)
  if (stage === 'ignition' || stage === 'expansion') return 'buy'
  if (stage === 'crowded' || stage === 'reversal' || stage === 'cooling') return 'sell'
  return 'hold'
}
```

- [ ] **Step 4: 补 CSS**

`src/components/common/DataTable.vue` 样式区 `.lifecycle-env-cooling` 规则块（约 L3167）之后追加：

```css
/* 样本不足（2026-09-10 口径统一）：历史样本不足时周期列显示数据质量声明（中性虚线框） */
.lifecycle-env-insufficient {
  color: #8f999c !important;
  font-size: 11px;
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(143, 153, 156, 0.08);
  border: 1px dashed rgba(143, 153, 156, 0.4);
}
```

- [ ] **Step 5: 跑测试确认 GREEN**

```bash
cd /d/dragon-board && pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

预期：全部 PASS（含 L152 改造后的旧用例）。

- [ ] **Step 6: Commit**

```bash
cd /d/dragon-board && git add src/components/common/DataTable.vue src/components/common/__tests__/DataTable.test.ts
git commit -m "feat(ranktrend): 周期列样本不足显示数据质量声明——不再误显示 lifecycle 兜底'冷却'，排序归中性（spec §4.1）"
```

---

### Task 5: DragonBreathPanel 市场情绪阶段文案 + statusSourceCounts 透出

**Files:**
- Modify: `src/components/panels/DragonBreathPanel.vue`（L40 文案、L324 后模板、L918 后 computed、L2189 后 CSS）

**Interfaces:**
- Consumes: `hotListSentiment.value?.metrics?.statusSourceCounts`（`src/types/hotlistSentiment.ts:184` 已有 `?: { displayStatus: number; fallback: number }`，后端 `_metrics_projection` 已透出，无需改类型）。
- Produces: 全池状态结构底部来源注释「golden 判定 N / fallback 接管 M」；缺字段（旧 EOD 文档）时整个注释隐藏，不做硬门禁。

- [ ] **Step 1: 文案区分**

`src/components/panels/DragonBreathPanel.vue` L40：

```vue
            <span class="sentiment-label">市场情绪阶段</span>
```

（市场级情绪五阶段：冰点/启动/发酵/高潮/退潮，与个股生命周期 5 态命名区分，spec §4.3。）

- [ ] **Step 2: 模板加来源注释**

L313-324 `.status-distribution` div 结束后（`</div>` 与 `<div class="hotlist-section">` 的 `</div>` 之间）插入：

```vue
              <div v-if="hotListStatusSourceNote" class="status-source-note">{{ hotListStatusSourceNote }}</div>
```

- [ ] **Step 3: computed**

L918 `hotListStatusItems` 之后追加：

```ts
// 状态来源透出（spec §4.2）：golden 判定 vs fallback 接管；缺字段（旧 EOD 文档）时隐藏
const hotListStatusSourceNote = computed(() => {
  const counts = hotListSentiment.value?.metrics?.statusSourceCounts
  if (!counts) return ''
  return `golden 判定 ${counts.displayStatus} / fallback 接管 ${counts.fallback}`
})
```

- [ ] **Step 4: CSS**

样式区 `.status-share` 规则块（约 L2185-2189）之后追加：

```css
.status-source-note {
  grid-column: 1 / -1;
  margin-top: 2px;
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.85;
}
```

- [ ] **Step 5: 类型检查**

```bash
cd /d/dragon-board && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

预期：0 error。

- [ ] **Step 6: Commit**

```bash
cd /d/dragon-board && git add src/components/panels/DragonBreathPanel.vue
git commit -m "feat(hotlist): 全池状态结构透出 statusSourceCounts（golden 判定/fallback 接管），'当前周期'改'市场情绪阶段'（spec §4.2/§4.3）"
```

---

### Task 6: 文档同步（lifecycle-layering-contract.md 展示状态节重写）

**Files:**
- Modify: `docs/ranktrend/lifecycle-layering-contract.md`（L8 目标第 2 条、L21-34 展示状态节）

**Interfaces:**
- Produces: 新级联合同与对账关系的唯一文档锚点（spec §8）。已核实 `quant-board/docs/ranktrend-python-port.md` 无 displayStatus 引用，不需更新。

- [ ] **Step 1: 重写展示状态节**

`docs/ranktrend/lifecycle-layering-contract.md` L8：

```markdown
2. 展示状态：由后端 `compute_display_status` 独家生产（lifecycle.stage 主轴 + 样本/资金/风险修正层），前端只消费不分类。
```

L21-34 `### 展示状态` 整节替换为：

```markdown
### 展示状态（2026-09-10 口径统一：lifecycle.stage 主轴）

展示状态由后端 `compute_display_status` 独家生产（`analysis.displayStatus`），前端只消费不做本地分类。candidateTier（交易候选资格）不参与展示状态；生命周期门控（regime 环境门/动量阈值/gate 去噪）只影响交易资格，不再影响展示分布。

级联（按序命中即返回）：

1. 样本质量门：`meta.sampleQuality.status=insufficient` 或无效行情 → `样本不足`
2. 风险修正层：`synergy.state=风险升级` → `转弱预警`；`存疑+主力净流出（zljzb≤0）` → `资金背离`
3. stage 主轴：`ignition`→`点火观察`、`expansion`→`主升确认`、`crowded`→`高位拥挤`、`reversal`→`转弱预警`、`cooling`→强资金+量能承接→`强资确认`，否则`转弱预警`
4. stage 缺失/非法：强资金+量能承接→`强资确认`，否则`新入观察`（fail-visible，不伪造 stage）
5. 兜底：`新入观察`

对账关系（对账测试 `quant-board/tests/test_display_status_reconciliation.py`）：`主升确认=expansion`、`点火观察=ignition`、`高位拥挤=crowded`、`转弱预警=reversal+cooling(无承接)`；`样本不足`/`资金背离`/`强资确认`为修正类单列可见；热榜情绪面板透出 `statusSourceCounts`（golden 判定 vs fallback 接管）。

后端缺失（旧缓存/离线）时前端展示 `未知`（classKey `unknown`），不伪造本地结论。
```

- [ ] **Step 2: Commit**

```bash
cd /d/dragon-board && git add docs/ranktrend/lifecycle-layering-contract.md
git commit -m "docs(ranktrend): 生命周期分层合同展示状态节重写——lifecycle.stage 主轴级联与 8 类↔5 态对账关系（spec §8）"
```

---

### Task 7: 全量验证 + 真实浏览器验收

**Files:**
- 无代码改动；只验证。

**Interfaces:**
- Consumes: Task 1-6 全部产出。
- Produces: 验证结论（pytest 子集、vitest 相关文件、vue-tsc、playwright-cli 浏览器验收与对账截图）。

- [ ] **Step 1: 后端相关子集 + collect-only**

```bash
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_display_status.py tests/test_display_status_reconciliation.py tests/test_hotlist_sentiment_compute.py tests/test_hotlist_sentiment_backfill.py tests/test_snapshot_analysis.py tests/test_snapshot_analysis_service.py -v
cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest --collect-only -q 2>&1 | tail -5
```

预期：子集全 PASS；collect-only 无 import 断裂（正常输出收集数量）。**不要跑全量 pytest**（本机 test_archive_research.py 挂起）。

- [ ] **Step 2: 前端相关测试**

```bash
cd /d/dragon-board && pnpm exec vitest run src/services/rankTrend/__tests__/statusClassifier.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/RankTrendPanel.test.ts
```

预期：PASS。

- [ ] **Step 3: 类型检查**

```bash
cd /d/dragon-board && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

预期：0 error。

- [ ] **Step 4: playwright-cli 真实浏览器验收（AGENTS.md 硬性要求）**

启动服务（后端 8000 + 根前端 5173），用 playwright-cli 打开 `http://localhost:5173`，逐项核对并截图：

1. 主表周期列：历史样本不足的个股显示「样本不足」虚线灰框（不是「冷却」），其余显示 5 态环境门标签。
2. 热榜情绪面板「全池状态结构」：8 类分布与主表周期列可对账（转弱预警≈反转+冷却无承接量、修正类单列）；底部出现「golden 判定 N / fallback 接管 M」（无该字段的旧文档日隐藏）。
3. 面板顶部文案为「市场情绪阶段」。
4. 任意个股悬停 tooltip：展示状态行反映新级联语义（如 cooling+强资 → 强资确认）。
5. 控制台无新增报错。

预期：以上全部符合；把截图路径与对账结论写进最终回复。

- [ ] **Step 5: 汇总报告**

最终回复包含：改动摘要（文件清单）、验证结果（各命令真实输出结论）、已知风险（旧 EOD 文档分布与新分布不可直接比、上线后面板分布预期显著变化——转弱预警/主升确认/点火观察回升、新入观察大降，属修正而非回归）。

---

## Self-Review 记录（计划完成时已核对）

- **Spec 覆盖**：§3 → Task 1；§4.1 → Task 4；§4.2/§4.3 → Task 5；§5 → Task 3；§7 → Task 1/2/3/4 测试；§8 → Task 6/7。§6（兼容与历史数据）无需代码任务，落在 Task 7 风险说明。
- **占位符扫描**：无 TBD/TODO；所有代码步骤给出完整可粘贴内容。
- **类型一致性**：`compute_display_status(analysis, stock)` 签名前后端调用点一致；TS `getRankTrendDisplayStatus(rankTrend?)` 单参与 RankTrendPanel 调用点、compat re-export、测试一致；`statusSourceCounts` 字段名与 `hotlistSentiment.ts:184`、`_metrics_projection` 一致。
