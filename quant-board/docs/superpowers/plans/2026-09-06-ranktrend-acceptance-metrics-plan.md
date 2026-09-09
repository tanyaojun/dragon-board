# 验收口径与噪音度量实施计划（WP3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"门控翻转率"做成显式指标（WP2 去噪效果基线）、把 h1 单一口径验收升级为 h4/h8 + 持有到收盘 + 成本敏感性扫描（four_dim pf 1.0377 距盈亏平衡线近，成本假设微调可能翻转结论）、统一"四维/五维"历史命名为"5 投票维 + 1 环境门"。

**Architecture:** 3.2 是只读诊断脚本（diagnose_* 惯例：argparse + MongoRepository.load_frame_bundles + replay 后统计 + JSON 落盘），**先于 WP2 实施以产出基线**（排序已获用户确认）；3.1 在 `OutcomeEvaluator` 就近扩展 hold-to-close 模式 + 成本网格扫描脚本 + `fallbackSlippageRate` 缺口定值；3.3 文档加勘误注记（不重写历史正文）+ 前端只改文案不改逻辑。

**Tech Stack:** Python 3 / pytest / MongoDB 只读；前端 Vue 3 + TypeScript（仅文案）。

**Spec:** `quant-board/docs/superpowers/specs/2026-09-06-ranktrend-acceptance-metrics-design.md`

**前置：** 无硬前置。3.2（Task 1-3）须在 WP2（`2026-09-06-ranktrend-gate-denoise-plan.md`）编码前完成并产出基线数字；Task 4-6 与 WP2 无依赖可并行。

## Global Constraints

- **只读诊断**：3.2/3.1 脚本不写库、不改引擎行为；fail-visible（样本不足/字段缺失结构化报告，不静默）。
- **不重算历史结论、不回改已固化报告数字**；fallbackSlippageRate 定值属"声明口径切换点"，需在文档显式声明。
- 不改 `tier_monotonicity` 硬约束达标线（MIN_SA_EXCESS_ACCURACY=0.05 不动）；不改策略参数默认值（成本扫描只出弹性表）。
- 测试位置：`quant-board/tests/*.py`；pytest 只跑相关子集（先 `--collect-only`，全量有挂起问题）。
- 前端文案改动只动文案与对应测试断言，不动逻辑；验证 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- commit 风格 `feat(ranktrend):` / `docs(ranktrend):` / `refactor(ranktrend):` 中文描述。

## 源文件坐标（执行者必读）

| 内容 | 位置 |
|---|---|
| OutcomeEvaluator.evaluate | `quant-board/backend/core/backtest/evaluator.py:92`（签名 `evaluate(frames, signals, horizons)`，**返回 dict 报告**：`horizons`（每 horizon 分组统计）/`bToATransitionRate`/`dDecayRate`/`buyBaselineComparison`；`_outcome` L133-161 返回行字段 = `code/entrySnapshotId/horizon/found/rankDelta/percentileDelta/priceReturn/maxDrawdown/stayedTop20/stayedTop50`，**价格来源 `frames[i]["stocks"][j]["price"]`，纯价差无成本**） |
| signal 必需字段 | `code`/`snapshotId`/`candidateTier`/`stage`/`regime`/`rankTrend.decision.final.signal`（evaluator.py:95/115/122-131 消费） |
| DEFAULT_TRADE_CONFIG | `quant-board/backend/core/backtest/config.py:5-57`（slippageRate=0.001、feeRate=0.0003、stampTaxRate=0.0005；**无 fallbackSlippageRate**） |
| fallbackSlippageRate 消费点 | `quant-board/backend/core/backtest/execution.py:1091-1092`（`fillFallbackMode` 默认 "fallback_penalized" 时 `slippage += float(config.get("fallbackSlippageRate") or 0)`——现运行时默认 0） |
| TradeSimulator 真实入口 | `quant-board/backend/core/backtest/execution.py:35` `TradeSimulator().run(frames, signals, config_patch)`；报告字段 `profitFactor/winRate/totalReturn/tradeCount/maxDrawdown`（diagnose_signal_return_gap.py L105-110 即在读取） |
| tier_forward_returns | `quant-board/backend/analysis/ranktrend/research/tier_monotonicity.py:77`（horizon 已参数化；h1 由调用方传 horizon=1，见 `operations/optimize_core_signal_parameters.py:92-95`） |
| 诊断脚本惯例 | `quant-board/backend/operations/diagnose_signal_return_gap.py`（argparse --dataset/--start/--end/--out；import 分两行：`from backend.data.repositories.mongo_repository import MongoRepository` + `from backend.data.repositories.repository_factory import get_runtime_mongodb_database`；L58-65 取数用 `projection="ranktrend"` + `fields=BACKTEST_RANKTREND_STOCK_FIELDS`；`signalCount` 与 `frameCount` 分开打印——**replay 返回的 signals 是每帧×每股一条，条数 ≈ 帧数 × 池内股票数**） |
| replay 入口（诊断脚本用） | `backend/analysis/ranktrend/engine/runtime.py:852` `engine.replay(frames, meta={...})`，返回 list[dict] 按帧序追加 |
| signals 单条结构 | signal 顶层含 `code/snapshotId/tradingDate/slotTime`（runtime.py:1274-1277）+ `rankTrend` 分析包 |
| veto / 降档 / regime 的字段路径 | veto：`signal["rankTrend"]["cycle"]["decision"]["action"] == "veto"`（**后端 decision 无 veto 布尔键**，键集合 = action/confidence/reasons/discovery/evidence；反证锚点 `tests/test_ranktrend_engine.py:276`）；B/D 降档：`observation["synergy"]["tierReasons"]` 精确锚点 `re.fullmatch(r"周期 [BD] 环境降档")`（volume_price.py:364-367 逐字 `"周期 {lc_tier} 环境降档"`；**勿用子串匹配**——WP2 抑制文案含"环境降档"后缀会误配）；regime：`runtime.py:826` `strategy.regime.reasons` 旁 regime dict 的 `state` |
| four_dim pf 1.0377 出处 | `quant-board/docs/ranktrend-tier-backtest/ranktrend-lifecycle-layer-rearchitecture-design.md:149` §7 |
| 验收口径声明落点 | `quant-board/docs/ranktrend-tier-backtest/ranktrend-signal-tier-backtest-plan.md`（执行时先读结构，就近放验收口径节） |
| 勘误注记对象 | `quant-board/docs/ranktrend-tier-backtest/overfitting-audit.md` §2.1（L14，把 lifecycle 列为"投票"行处） |
| 前端"四维"文案（rg 命中 7 文件，已核实全为注释/JSDoc/测试标题字符串） | `src/stores/ui.ts`、`src/components/common/DataTable.vue`、`src/components/common/__tests__/DataTable.test.ts`、`src/services/dataLoader/DataLoaderFacade.ts`、`src/services/rankTrend/types.ts`、`src/services/rankTrend/tierDisplay.ts`、`src/services/rankTrend/__tests__/tierDisplay.test.ts` |

---

### Task 1: 门控翻转统计纯函数

**Files:**
- Create: `quant-board/backend/analysis/ranktrend/research/gate_flip_stats.py`
- Test: `quant-board/tests/test_gate_flip_stats.py`（新建）

**Interfaces:**
- Consumes: signals 序列（replay 输出 list[dict]，**每帧×每股一条**，元素含 `rankTrend.cycle.decision.action`、`rankTrend.observation.synergy.tierReasons`、regime state）。
- Produces（Task 2 CLI 依赖）:
  - `extract_gate_states(signal: dict) -> dict`：返回 `{"veto": bool, "bd_downgrade": bool, "regime_state": str}`；veto 读 `decision["action"] == "veto"`（后端无 veto 布尔键）；bd_downgrade 用精确锚点 `re.fullmatch(r"周期 [BD] 环境降档", reason)`（**勿用子串匹配**——WP2 抑制文案"…环境降档 单帧确认未达…"会被子串误配，跨计划协同约定）；字段缺失时 fail-visible 值：veto=False、bd_downgrade=False、regime_state=""（由调用方统计"缺失计数"）。
  - `count_gate_flips(states_by_code: dict[str, list[dict]], regime_states: list[str]) -> dict`：
    - 输入：per-code 有序状态序列（按帧时间序）+ 市场级 regime state 序列（**同帧全股票同 state，须由调用方按 snapshotId 去重后传入**，避免同一翻转按股票数重复计数）。
    - 输出 `{"comparable_pairs": int, "flip_counts": {"veto": int, "bd_downgrade": int, "regime_state": int}, "flip_rates": {...同键 float}, "per_code": {code: {...}}, "missing_fields": int}`；相邻对可比条件：两帧状态字段均非缺失；翻转率 = 翻转数 / 可比对数（除零得 0.0 并在 missing 计数体现）。
  - `top_flip_codes(per_code: dict, key: str, n: int = 10) -> list[tuple[str, int]]`：按指定键翻转数降序 Top-N。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.research.gate_flip_stats import (
    count_gate_flips,
    extract_gate_states,
    top_flip_codes,
)


def _signal(veto: bool, bd: bool, regime: str) -> dict:
    reasons = ["周期 D 环境降档"] if bd else []
    action = "veto" if veto else "confirm"
    return {
        "rankTrend": {
            "cycle": {"decision": {"action": action, "reasons": []}},
            "observation": {"synergy": {"tierReasons": reasons}},
            "strategy": {"regime": {"state": regime, "reasons": []}},
        }
    }


def test_extract_gate_states_reads_three_sources():
    states = extract_gate_states(_signal(veto=True, bd=True, regime="strong"))
    assert states == {"veto": True, "bd_downgrade": True, "regime_state": "strong"}


def test_extract_gate_states_missing_fields_fail_visible():
    states = extract_gate_states({})
    assert states["veto"] is False
    assert states["bd_downgrade"] is False
    assert states["regime_state"] == ""           # 空串 = 缺失，由统计侧计入 missing


def test_extract_gate_states_suppression_reason_not_counted_as_downgrade():
    """跨计划协同：WP2 抑制文案不得被精确锚点误判为真实 B/D 降档。"""
    signal = {"rankTrend": {
        "cycle": {"decision": {"action": "confirm", "reasons": []}},
        "observation": {"synergy": {"tierReasons": ["周期 D 环境降档 单帧确认未达（1/2），暂缓"]}},
        "strategy": {"regime": {"state": "normal", "reasons": []}},
    }}
    assert extract_gate_states(signal)["bd_downgrade"] is False


def test_count_flips_counts_adjacent_changes():
    seq = [_signal(False, False, "normal"), _signal(True, False, "normal"),
           _signal(True, True, "weak"), _signal(False, True, "weak")]
    result = count_gate_flips(
        {"000001": [extract_gate_states(sig) for sig in seq]},
        ["normal", "normal", "weak", "weak"],            # 市场级 regime 序列（与帧一一对应）
    )
    assert result["comparable_pairs"] == 3
    assert result["flip_counts"]["veto"] == 2            # F→T、T→F
    assert result["flip_counts"]["bd_downgrade"] == 1    # F→T
    assert result["flip_counts"]["regime_state"] == 1    # normal→weak（市场级，不按 code 重复计数）
    assert result["flip_rates"]["veto"] == 2 / 3


def test_count_flips_missing_field_pair_not_comparable():
    seq = [_signal(False, False, "normal"),
           {"rankTrend": {"cycle": {"decision": {"action": "confirm", "reasons": []}}}}]  # 无 strategy.regime
    result = count_gate_flips({"000001": [extract_gate_states(sig) for sig in seq]}, [])
    assert result["comparable_pairs"] == 0
    assert result["missing_fields"] == 1                 # regime_state 缺失的对


def test_count_flips_regime_market_level_series():
    result = count_gate_flips({}, ["strong", "strong", "normal", "normal", "weak"])
    assert result["flip_counts"]["regime_state"] == 2
    assert result["comparable_pairs"] == 4


def test_top_flip_codes_sorted_desc():
    per_code = {"a": {"veto": 3, "bd_downgrade": 0, "regime_state": 0},
                "b": {"veto": 5, "bd_downgrade": 1, "regime_state": 0},
                "c": {"veto": 1, "bd_downgrade": 2, "regime_state": 0}}
    assert top_flip_codes(per_code, "veto", n=2) == [("b", 5), ("a", 3)]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_flip_stats.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_flip_stats.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
"""门控翻转率统计（WP3.2）——纯函数，供 diagnose_gate_flip_rate.py 调用。

三类门控状态逐帧提取 + 相邻帧翻转计数：lifecycle veto（per-stock，action=="veto"）、
synergy B/D 降档（per-stock，tierReasons 精确锚点——WP2 抑制文案含"环境降档"后缀，
必须 fullmatch 精确匹配，跨计划协同约定）、regime state（市场级，调用方按 snapshotId 去重）。
字段缺失按 fail-visible 计入 missing_fields，不静默丢弃。
"""
from __future__ import annotations

import re
from typing import Any

_BD_DOWNGRADE_PATTERN = re.compile(r"周期 [BD] 环境降档")


def extract_gate_states(signal: dict[str, Any]) -> dict[str, Any]:
    rank_trend = signal.get("rankTrend") if isinstance(signal, dict) else None
    cycle = (rank_trend or {}).get("cycle") or {}
    decision = cycle.get("decision") or {}
    observation = (rank_trend or {}).get("observation") or {}
    synergy = observation.get("synergy") or {}
    strategy = (rank_trend or {}).get("strategy") or {}
    regime = strategy.get("regime") or {}
    tier_reasons = synergy.get("tierReasons") or []
    return {
        "veto": str(decision.get("action") or "") == "veto",
        "bd_downgrade": any(_BD_DOWNGRADE_PATTERN.fullmatch(str(reason)) for reason in tier_reasons),
        "regime_state": str(regime.get("state") or ""),
    }


def _flips(series: list[Any]) -> int:
    return sum(1 for prev, curr in zip(series, series[1:]) if prev != curr)


def count_gate_flips(states_by_code: dict[str, list[dict[str, Any]]], regime_states: list[str]) -> dict[str, Any]:
    """regime state 是市场级状态（同帧全 code 相同）——只按市场级序列统计一次，不按 code 重复计数。"""
    per_code: dict[str, dict[str, int]] = {}
    comparable_pairs = 0
    missing_fields = 0
    totals = {"veto": 0, "bd_downgrade": 0, "regime_state": _flips(regime_states)}
    for code, states in states_by_code.items():
        veto_series = [bool(state.get("veto")) for state in states]
        bd_series = [bool(state.get("bd_downgrade")) for state in states]
        regime_series = [str(state.get("regime_state") or "") for state in states]
        missing_fields += sum(1 for value in regime_series if not value)
        pairs = sum(
            1 for prev, curr in zip(regime_series, regime_series[1:]) if prev and curr
        )
        comparable_pairs += pairs
        counts = {
            "veto": _flips(veto_series),
            "bd_downgrade": _flips(bd_series),
            "regime_state": 0,  # 市场级状态不在 per-code 视图重复计数
        }
        per_code[code] = counts
        totals["veto"] += counts["veto"]
        totals["bd_downgrade"] += counts["bd_downgrade"]
    market_pairs = max(len(regime_states) - 1, 0)
    comparable_pairs = max(comparable_pairs, market_pairs)
    flip_rates = {
        key: (value / comparable_pairs if comparable_pairs else 0.0)
        for key, value in totals.items()
    }
    return {
        "comparable_pairs": comparable_pairs,
        "flip_counts": totals,
        "flip_rates": flip_rates,
        "per_code": per_code,
        "missing_fields": missing_fields,
    }


def top_flip_codes(per_code: dict[str, dict[str, int]], key: str, n: int = 10) -> list[tuple[str, int]]:
    return sorted(
        ((code, int(counts.get(key) or 0)) for code, counts in per_code.items()),
        key=lambda item: (-item[1], item[0]),
    )[: max(n, 0)]
```

- [ ] **Step 4: 测试通过 + 提交**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_flip_stats.py -v`
Expected: 全部 PASS。

```bash
git add quant-board/backend/analysis/ranktrend/research/gate_flip_stats.py quant-board/tests/test_gate_flip_stats.py
git commit -m "feat(ranktrend): 门控翻转率统计纯函数（veto/B-D 降档/regime state 三源）"
```

---

### Task 2: diagnose_gate_flip_rate.py CLI

**Files:**
- Create: `quant-board/backend/operations/diagnose_gate_flip_rate.py`
- Test: `quant-board/tests/test_diagnose_gate_flip_rate.py`（新建，仅测纯编排函数，不连库）

**Interfaces:**
- Consumes: Task 1 两个纯函数；`MongoRepository(...).load_frame_bundles(dataset_id, snapshot_type="half_hour", start_date=..., end_date=...)`（import 与取数照抄 `diagnose_signal_return_gap.py` L42-65：import 分两行 + `projection="ranktrend"` + `fields=BACKTEST_RANKTREND_STOCK_FIELDS`）；`engine.replay(frames, meta={...})` 返回 list[dict]，**每帧×每股一条**，signal 顶层有 `code/snapshotId/tradingDate/slotTime`（runtime.py:1274-1277）。
- Produces:
  - `collect_flip_report(signals: list[dict]) -> dict`：从 replay 产物组装——per-code 状态序列按 `signal["code"]` 分组（replay 追加序 = 帧序，不再与 frames zip）；market 级 regime 序列按 `snapshotId` 去重保序（同帧全股票同 state，不按股票数重复计数）；stage 分桶用 `signal["slotTime"]`（早盘 ≤10:30 / 午盘 11:00-13:30 / 尾盘 ≥14:00，桶名 morning/mid/late）。返回 Task 1 `count_gate_flips` 结构 + `{"stage_flip_rates": {...}, "frame_count": 去重帧数, "signal_count": N, "code_count": M}`。
  - CLI：`python -m backend.operations.diagnose_gate_flip_rate --dataset <id> [--snapshot-type half_hour] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out <path>]`。输出 JSON 落盘（默认 `quant-board/data/reports/gate_flip_rate_<dataset>_<start>_<end>.json`，目录不存在则创建）+ 控制台摘要（frameCount/signalCount 分开打印、总翻转率、stage 分布）。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.operations.diagnose_gate_flip_rate import collect_flip_report


def _signal(code: str, sid: str, slot: str, action: str, regime: str, bd: bool = False) -> dict:
    """replay 产物真实形状：顶层 code/snapshotId/slotTime + decision.action（无 veto 布尔键）。"""
    reasons = ["周期 D 环境降档"] if bd else []
    return {
        "code": code, "snapshotId": sid, "tradingDate": "2026-06-05", "slotTime": slot,
        "rankTrend": {
            "cycle": {"decision": {"action": action, "reasons": []}},
            "observation": {"synergy": {"tierReasons": reasons}},
            "strategy": {"regime": {"state": regime, "reasons": []}},
        },
    }


def test_collect_flip_report_groups_by_code_and_dedupes_regime():
    # 2 帧 × 2 股 = 4 条信号（replay 真实形状：每帧每股一条）
    signals = [
        _signal("000001", "s1", "10:00", "confirm", "normal"),
        _signal("000002", "s1", "10:00", "confirm", "normal"),
        _signal("000001", "s2", "14:30", "veto", "weak"),
        _signal("000002", "s2", "14:30", "confirm", "weak"),
    ]
    report = collect_flip_report(signals)
    assert report["signal_count"] == 4
    assert report["frame_count"] == 2                    # regime 按 snapshotId 去重
    assert report["code_count"] == 2
    assert report["flip_counts"]["veto"] == 1            # 仅 000001 第二帧 veto
    assert report["flip_counts"]["regime_state"] == 1    # 市场级 normal→weak 只计一次
    assert set(report["stage_flip_rates"].keys()) == {"morning", "late"}


def test_collect_flip_report_empty_inputs_fail_visible():
    report = collect_flip_report([])
    assert report["frame_count"] == 0 and report["code_count"] == 0 and report["signal_count"] == 0
    assert report["flip_rates"] == {"veto": 0.0, "bd_downgrade": 0.0, "regime_state": 0.0}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_diagnose_gate_flip_rate.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_diagnose_gate_flip_rate.py -v`

- [ ] **Step 3: 实现（编排 + CLI；库加载与 replay 部分照抄 diagnose_signal_return_gap.py 的取数与 replay 调用形态，执行时打开该文件对齐 import 与参数名）**

```python
"""门控翻转率诊断（WP3.2，只读）——WP2 去噪效果的基线/对比度量。

用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_gate_flip_rate \
    --dataset <dataset_id> [--start 2026-08-01] [--end 2026-08-31] [--out <path>]

只读不写库；样本不足或字段缺失在报告中显式计数（fail-visible），不静默。
signals 为 replay 产物：每帧×每股一条，per-code 序列按 signal["code"] 分组，
market 级 regime 按 snapshotId 去重（同帧全股票同 state）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.research.gate_flip_stats import (
    count_gate_flips,
    extract_gate_states,
)


def _stage_bucket(slot_time: str) -> str:
    if not slot_time:
        return "mid"
    if slot_time <= "10:30":
        return "morning"
    if slot_time >= "14:00":
        return "late"
    return "mid"


def collect_flip_report(signals: list[dict[str, Any]]) -> dict[str, Any]:
    per_code_states: dict[str, list[dict[str, Any]]] = defaultdict(list)
    regime_by_snapshot: dict[str, str] = {}
    stage_sequences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:  # replay 追加序 = 帧序
        states = extract_gate_states(signal)
        code = str(signal.get("code") or "")
        if code:
            per_code_states[code].append(states)
        sid = str(signal.get("snapshotId") or "")
        if sid and states["regime_state"] and sid not in regime_by_snapshot:
            regime_by_snapshot[sid] = states["regime_state"]
        stage_sequences[_stage_bucket(str(signal.get("slotTime") or ""))].append(
            (sid, states)
        )
    report = count_gate_flips(dict(per_code_states), list(regime_by_snapshot.values()))
    stage_flip_rates = {}
    for bucket, pairs in stage_sequences.items():
        # 桶内 regime 序列同样按 snapshotId 去重（同帧多股同 state，不重复计数）
        bucket_regime: dict[str, str] = {}
        for sid, states in pairs:
            if sid and states["regime_state"] and sid not in bucket_regime:
                bucket_regime[sid] = states["regime_state"]
        sub = count_gate_flips({"all": [s for _, s in pairs]}, list(bucket_regime.values()))
        stage_flip_rates[bucket] = sub["flip_rates"]
    report["stage_flip_rates"] = stage_flip_rates
    report["frame_count"] = len(regime_by_snapshot)
    report["signal_count"] = len(signals)
    report["code_count"] = len(per_code_states)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="门控翻转率诊断（只读）")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.analysis.ranktrend.engine import RankTrendPythonEngine
    from backend.data.repositories.mongo_repository import MongoRepository
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.data.repositories.ranktrend_fields import BACKTEST_RANKTREND_STOCK_FIELDS

    repository = MongoRepository(get_runtime_mongodb_database())
    frames = repository.load_frame_bundles(
        args.dataset,
        snapshot_type=args.snapshot_type,
        start_date=args.start,
        end_date=args.end,
        projection="ranktrend",
        fields=BACKTEST_RANKTREND_STOCK_FIELDS,
    )
    if not frames:
        print(json.dumps({"error": "no_frames_loaded", "dataset": args.dataset}), file=sys.stderr)
        return 1
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, meta={})
    report = collect_flip_report(signals)
    report["dataset"] = args.dataset
    report["snapshotType"] = args.snapshot_type
    report["start"] = args.start
    report["end"] = args.end
    out_path = Path(args.out) if args.out else Path("data/reports") / (
        f"gate_flip_rate_{args.dataset}_{args.start or 'all'}_{args.end or 'all'}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frameCount={report['frame_count']} signalCount={report['signal_count']} codes={report['code_count']}", file=sys.stderr)
    print(json.dumps(report["flip_rates"], ensure_ascii=False))
    print(f"report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

（`load_frame_bundles` 的实际参数名、`projection="ranktrend"` + `fields=BACKTEST_RANKTREND_STOCK_FIELDS` 取数瘦身、`BACKTEST_RANKTREND_STOCK_FIELDS` 的实际 import 路径，以 `diagnose_signal_return_gap.py` L42-65 现文为准对齐——默认 `projection="full"` 会连 sectors/entities 一起装载，8 月全量帧体积明显偏大。execution 时打开该文件照抄 L42-65 的 import 与参数名。）

- [ ] **Step 4: 测试通过 + 真实数据冒烟**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_diagnose_gate_flip_rate.py -v`
Expected: PASS。
真实数据（8 月冻结段）冒烟：`cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_gate_flip_rate --dataset <默认数据集> --start 2026-08-01 --end 2026-08-31`，人工复核 JSON 结构（数据集 id 用 `python -m backend.cli list-datasets` 查询）。**该输出即 WP2 前基线，归档保留。**

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/operations/diagnose_gate_flip_rate.py quant-board/tests/test_diagnose_gate_flip_rate.py
git commit -m "feat(ranktrend): 门控翻转率诊断 CLI（WP2 基线度量，只读 fail-visible）"
```

---

### Task 3: WP2 前基线归档

**Files:**
- Create: `quant-board/data/reports/gate_flip_rate_<dataset>_2026-08-01_2026-08-31.json`（Task 2 产物，运行数据目录默认 gitignore，**归档副本放 `quant-board/docs/ranktrend-tier-backtest/gate-flip-baseline-2026-08.md`**）
- Create: `quant-board/docs/ranktrend-tier-backtest/gate-flip-baseline-2026-08.md`

- [ ] **Step 1: 运行并归档基线数字**

对 8 月冻结段跑 Task 2 CLI，把关键数字抄录到 `gate-flip-baseline-2026-08.md`：

```markdown
# 门控翻转率基线（WP2 前，2026-08 冻结段）

- 生成：`python -m backend.operations.diagnose_gate_flip_rate --dataset <id> --start 2026-08-01 --end 2026-08-31`
- 总翻转率：veto=<数字> / bd_downgrade=<数字> / regime_state=<数字>（comparable_pairs=<数字>）
- per-code Top-10（veto）：<表格或列表>
- stage 分布：morning=<数字> mid=<数字> late=<数字>
- 备注：WP2（K/α/迟滞扫描）完成后用同参数段重跑对比；本基线基于 lookahead 未修复数据（WP1c 前），
  扫描结论引用时注意口径。
```

- [ ] **Step 2: 提交**

```bash
git add quant-board/docs/ranktrend-tier-backtest/gate-flip-baseline-2026-08.md
git commit -m "docs(ranktrend): 门控翻转率 WP2 前基线归档（2026-08 冻结段）"
```

---

### Task 4: hold-to-close 评估口径（OutcomeEvaluator 扩展）

**Files:**
- Modify: `quant-board/backend/core/backtest/evaluator.py`（`evaluate` L92-119、`_horizon` L121-131、`_outcome` L133-161，新增 `_last_entry_index`）
- Test: `quant-board/tests/test_outcome_hold_to_close.py`（新建）

**Interfaces:**
- Consumes: 现有 `evaluate(frames, signals, horizons) -> dict`（返回键 `horizons/bToATransitionRate/dDecayRate/buyBaselineComparison`）、`_horizon(frames, signals, horizon, lookup) -> dict`（键 `horizon/byTier/byStage/byRegime/...`）、`_outcome(frames, signal, horizon, lookup) -> dict`（行字段 `code/entrySnapshotId/horizon/found/rankDelta/percentileDelta/priceReturn/maxDrawdown/stayedTop20/stayedTop50`）、`build_frame_lookup`（evaluator.py:8-25）。
- Produces:
  - `evaluate(frames, signals, horizons, include_hold_to_close: bool = False)`：True 时返回 dict 追加键 `holdToClose` = `_horizon` 同构分组报告（`horizon` 标识为字符串 `"hold_to_close"`），future 定位为**同一 tradingDate 最后一帧**；False 时 `holdToClose` 为 None，其余计算路径零变化。
  - `_outcome(..., last_entry_index: dict[str, int] | None = None)`：可选第 5 参，仅 `horizon == "hold_to_close"` 时生效——`future = last_entry_index[entry 帧的 tradingDate]`；entry 帧缺失 tradingDate → `future = len(frames)` 越界走现有 `found=False` 行（fail-visible）；entry 即尾帧 → `future == entry`，`priceReturn == 0.0` 自然成立，不加特判。
  - 新增静态方法 `_last_entry_index(frames) -> dict[str, int]`：tradingDate → 当日最后帧的下标（按 frames 顺序末次出现）。
  - **口径声明**：与现有 horizons 口径完全同构（同一 `_outcome` 路径、**无成本纯价差**——成本评估归 TradeSimulator，本口径只做信号质量分层），仅出场点改为同日尾帧。调用方 `engine.py:42` 本期不改默认，Task 6 文档声明启用方式。
  - 注意：`horizon` 行字段在此口径下是字符串 `"hold_to_close"`（现有口径为 int），下游 `_stats` 不读 horizon 值，无兼容问题。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.core.backtest.evaluator import OutcomeEvaluator, build_frame_lookup


def _frame(snapshot_id: str, date: str, prices: dict[str, float]) -> dict:
    return {
        "snapshotId": snapshot_id,
        "tradingDate": date,
        "stocks": [{"code": code, "price": price, "rank": 3} for code, price in prices.items()],
    }


def _signal(code: str, snapshot_id: str) -> dict:
    return {
        "code": code,
        "snapshotId": snapshot_id,
        "candidateTier": "A_MAIN",
        "stage": "10:00",
        "regime": "normal",
        "rankTrend": {"decision": {"final": {"signal": "buy"}}},
    }


def _frames():
    return [
        _frame("s1", "2026-06-05", {"000001": 10.0, "000002": 20.0}),
        _frame("s2", "2026-06-05", {"000001": 10.5, "000002": 21.0}),
        _frame("s3", "2026-06-05", {"000001": 11.0, "000002": 22.0}),  # 06-05 尾帧
        _frame("s4", "2026-06-08", {"000001": 12.0, "000002": 25.0}),  # 跨日不参与
    ]


def test_hold_to_close_exit_at_same_day_last_frame():
    frames = _frames()
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s1"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is True
    assert row["horizon"] == "hold_to_close"
    assert row["priceReturn"] == 0.1  # 10.0 → 11.0（s3），跨日 s4 的 12.0 不参与


def test_hold_to_close_entry_at_last_frame_is_zero_return():
    frames = _frames()
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s3"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is True
    assert row["priceReturn"] == 0.0


def test_hold_to_close_missing_trading_date_fails_visible():
    frames = [{"snapshotId": "s1", "stocks": [{"code": "000001", "price": 10.0, "rank": 3}]}]
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s1"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is False  # 缺 tradingDate 无法定位尾帧 → 样本不足结构


def test_evaluate_hold_to_close_group_report_and_default_off():
    frames = _frames()
    signals = [_signal("000001", "s1"), _signal("000002", "s1")]
    evaluator = OutcomeEvaluator()
    result = evaluator.evaluate(frames, signals, [1], include_hold_to_close=True)
    a_main = next(r for r in result["holdToClose"]["byTier"] if r["groupKey"] == "A_MAIN")
    assert a_main["foundCount"] == 2
    assert a_main["avgPriceReturn"] == 0.1  # 000001 +10%、000002 +10%
    default_result = evaluator.evaluate(frames, signals, [1])
    assert default_result["holdToClose"] is None  # 默认关闭，现行为零变化
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_outcome_hold_to_close.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_outcome_hold_to_close.py -v`
Expected: FAIL（`_outcome` 不接受第 5 参 / `evaluate` 不接受 `include_hold_to_close`）。

- [ ] **Step 3: 实现（evaluator.py，四处最小改动）**

`evaluate`（L92）签名与返回 dict（L107）：

```python
    def evaluate(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], horizons: list[int], include_hold_to_close: bool = False) -> dict[str, Any]:
        # ... lookup/reports/b_to_a/d_outcomes 全部不动 ...
        hold_to_close = None
        if include_hold_to_close:
            hold_to_close = self._horizon(frames, signals, "hold_to_close", lookup, self._last_entry_index(frames))
        return {
            "horizons": reports,
            "holdToClose": hold_to_close,
            "bToATransitionRate": share(len(b_to_a), len(b_signals)),
            # ... 其余键不动 ...
        }
```

新增静态方法（`_outcome` 之后）：

```python
    @staticmethod
    def _last_entry_index(frames: list[dict[str, Any]]) -> dict[str, int]:
        last: dict[str, int] = {}
        for idx, frame in enumerate(frames):
            trading_date = str(frame.get("tradingDate") or "")
            if trading_date:
                last[trading_date] = idx  # 顺序末次出现 = 当日最后帧
        return last
```

`_horizon`（L121）透传：

```python
    def _horizon(self, frames, signals, horizon, lookup, last_entry_index: dict[str, int] | None = None) -> dict[str, Any]:
        pairs = [(signal, self._outcome(frames, signal, horizon, lookup, last_entry_index)) for signal in signals]
        # ... 分组部分全部不动 ...
```

`_outcome`（L133）签名与 future 定位：

```python
    def _outcome(self, frames, signal, horizon, lookup, last_entry_index: dict[str, int] | None = None) -> dict[str, Any]:
        code = str(signal["code"])
        entry = lookup["index_by_snapshot_id"].get(str(signal["snapshotId"]), -1)
        if horizon == "hold_to_close" and last_entry_index is not None:
            entry_frame = frames[entry] if entry >= 0 else None
            entry_date = str((entry_frame or {}).get("tradingDate") or "")
            future = last_entry_index.get(entry_date, len(frames)) if entry_date else len(frames)
        else:
            future = entry + horizon
        # ... current/target/收益计算/返回行 全部不动（found=False 越界分支自然兜底）...
```

- [ ] **Step 4: 回归（evaluator 既有测试 + 默认关闭零变化）**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_outcome_hold_to_close.py -v && .venv/Scripts/python.exe -m pytest tests/ -k "evaluator or outcome" -v`
Expected: 全部 PASS（默认 `include_hold_to_close=False` 时计算路径零变化，仅返回 dict 多 `holdToClose: None` 键）。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/core/backtest/evaluator.py quant-board/tests/test_outcome_hold_to_close.py
git commit -m "feat(ranktrend): OutcomeEvaluator hold-to-close 评估口径（同日尾帧强制出场，默认关闭，无成本与 horizons 同构）"
```

---

### Task 5: fallbackSlippageRate 定值 + 成本敏感性扫描脚本

**Files:**
- Modify: `quant-board/backend/core/backtest/config.py:5-57`（DEFAULT_TRADE_CONFIG 补 `fallbackSlippageRate`）
- Create: `quant-board/backend/operations/diagnose_cost_sensitivity.py`
- Test: `quant-board/tests/test_cost_sensitivity.py`（新建）

**Interfaces:**
- Consumes: `execution.py:1091-1092` 现有消费逻辑（不改）；TradeSimulator 真实入口 `TradeSimulator().run(frames, signals, config_patch)`（execution.py:35），报告字段 `profitFactor/winRate/totalReturn/tradeCount/maxDrawdown`；`execution.py:883 _lifecycle_decision_action` 的 veto 门/`execution.py:510-512` four_dim 入场 veto 门（扫描口径说明用，不改）。
- Produces:
  - `DEFAULT_TRADE_CONFIG["fallbackSlippageRate"] = 0.001`（快照退化成交罚金与基础 slippage 同量级；**口径声明落 Task 6 文档**）。
  - `run_cost_grid(frames, signals, base_config: dict, grid: dict | None = None) -> list[dict]`：默认网格 `slippageRate ∈ {0.0005, 0.001, 0.002} × feeRate ∈ {0.0003, 0.0006}`，每格以 base_config 复制 + 覆盖两参数调 `TradeSimulator().run(frames, signals, config_patch)`，返回行 `{"slippageRate": float, "feeRate": float, "profitFactor": float, "winRate": float, "totalReturn": float, "tradeCount": int}`（字段名与报告实际字段一致；单格异常记 `{"error": ...}` 行继续网格，fail-visible）。
  - CLI：`python -m backend.operations.diagnose_cost_sensitivity --dataset <id> [--start] [--end] [--out]`，JSON 落盘默认 `data/reports/cost_sensitivity_<dataset>_<start>_<end>.json`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.core.backtest.config import DEFAULT_TRADE_CONFIG


def test_default_trade_config_has_fallback_slippage_rate():
    assert "fallbackSlippageRate" in DEFAULT_TRADE_CONFIG
    assert float(DEFAULT_TRADE_CONFIG["fallbackSlippageRate"]) == 0.001


def test_run_cost_grid_covers_2x2_min_grid():
    from backend.operations.diagnose_cost_sensitivity import run_cost_grid

    grid = {"slippageRate": [0.001, 0.002], "feeRate": [0.0003]}
    # frames/signals 用最小合成序列；TradeSimulator 不可用字段允许 None（fail-visible）
    rows = run_cost_grid([], [], dict(DEFAULT_TRADE_CONFIG), grid=grid)
    assert len(rows) == 2
    assert {row["slippageRate"] for row in rows} == {0.001, 0.002}
    assert {row["feeRate"] for row in rows} == {0.0003}
```

（空 frames/signals 下 TradeSimulator 的行为——返回空报告还是抛错——执行时核实；抛错则在 `run_cost_grid` 内捕获该格记 `{"error": ...}` 行继续网格，fail-visible。）

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_cost_sensitivity.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_cost_sensitivity.py -v`

- [ ] **Step 3: 实现**

`config.py` DEFAULT_TRADE_CONFIG 内（slippageRate 相邻处）：

```python
    "fallbackSlippageRate": 0.001,  # 快照退化成交（fillFallbackMode=fallback_penalized）额外滑点罚
```

`diagnose_cost_sensitivity.py`（编排 + CLI，取数/replay 与 Task 2 同款惯例）：

```python
"""成本敏感性扫描（WP3.1，只读）——验证近盈亏平衡结论（如 four_dim pf 1.0377）对成本的弹性。

用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_cost_sensitivity \
    --dataset <dataset_id> [--start 2026-08-01] [--end 2026-08-31] [--out <path>]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_GRID = {"slippageRate": [0.0005, 0.001, 0.002], "feeRate": [0.0003, 0.0006]}


def run_cost_grid(
    frames: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    base_config: dict[str, Any],
    grid: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    from backend.core.backtest.execution import TradeSimulator

    grid = grid or DEFAULT_GRID
    rows: list[dict[str, Any]] = []
    for slippage in grid.get("slippageRate", []):
        for fee in grid.get("feeRate", []):
            config = copy.deepcopy(base_config)
            config["slippageRate"] = float(slippage)
            config["feeRate"] = float(fee)
            try:
                report = TradeSimulator().run(frames, signals, config) or {}
                rows.append({
                    "slippageRate": float(slippage),
                    "feeRate": float(fee),
                    "profitFactor": report.get("profitFactor"),
                    "winRate": report.get("winRate"),
                    "totalReturn": report.get("totalReturn"),
                    "tradeCount": report.get("tradeCount"),
                })
            except Exception as exc:  # 单格失败不中断网格（fail-visible 记行）
                rows.append({"slippageRate": float(slippage), "feeRate": float(fee), "error": str(exc)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="成本敏感性扫描（只读）")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
    from backend.data.repositories.mongo_repository import MongoRepository
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.data.repositories.ranktrend_fields import BACKTEST_RANKTREND_STOCK_FIELDS

    repository = MongoRepository(get_runtime_mongodb_database())
    frames = repository.load_frame_bundles(
        args.dataset,
        snapshot_type=args.snapshot_type,
        start_date=args.start,
        end_date=args.end,
        projection="ranktrend",
        fields=BACKTEST_RANKTREND_STOCK_FIELDS,
    )
    if not frames:
        print(json.dumps({"error": "no_frames_loaded", "dataset": args.dataset}), file=sys.stderr)
        return 1
    signals = _replay_signals(frames)
    rows = run_cost_grid(frames, signals, dict(DEFAULT_TRADE_CONFIG))
    out_path = Path(args.out) if args.out else Path("data/reports") / (
        f"cost_sensitivity_{args.dataset}_{args.start or 'all'}_{args.end or 'all'}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False)[:2000])
    print(f"report -> {out_path}", file=sys.stderr)
    return 0


def _replay_signals(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    return RankTrendPythonEngine().replay(frames, meta={})


if __name__ == "__main__":
    raise SystemExit(main())
```

（`TradeSimulator().run(frames, signals, config_patch)` 入口与报告字段 `profitFactor/winRate/totalReturn/tradeCount/maxDrawdown` 已核实为 execution.py 现文；config_patch 与 `DEFAULT_TRADE_CONFIG` 的合并语义执行时打开 `execution.py:35` 附近 `run` 方法确认——若 `run` 只接受部分覆盖 patch，按其实际合并行为传参。）

- [ ] **Step 4: 测试通过 + fallback 定值回归**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_cost_sensitivity.py -v && .venv/Scripts/python.exe -m pytest tests/ -k "execution or trade or simulator" -v`
Expected: 全部 PASS；fallbackSlippageRate 定值 0.001 后，凡覆盖 `fillFallbackMode=fallback_penalized` 成交路径的既有测试若断言成交价/滑点数字变化，**更新断言数字并在 commit message 声明口径变更**（这是预期中的行为变化点，不是回归）。

- [ ] **Step 5: 真实数据冒烟 + 提交**

8 月冻结段跑一次 CLI（four_dim 或默认策略口径），人工复核弹性表结构。

```bash
git add quant-board/backend/core/backtest/config.py quant-board/backend/operations/diagnose_cost_sensitivity.py quant-board/tests/test_cost_sensitivity.py
git commit -m "feat(ranktrend): fallbackSlippageRate 定值 0.001 + 成本敏感性网格扫描脚本"
```

---

### Task 6: 验收口径声明文档 + 历史文档勘误注记

**Files:**
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-signal-tier-backtest-plan.md`（验收口径节，执行时先读文档结构就近落位）
- Modify: `quant-board/docs/ranktrend-tier-backtest/*overfitting-audit*`（§2.1 处加注记）
- Read: `quant-board/docs/ranktrend-tier-backtest/ranktrend-lifecycle-layer-rearchitecture-design.md` §7（pf 1.0377 上下文，声明中引用）

- [ ] **Step 1: 验收口径声明（signal-tier-backtest-plan 验收口径节追加）**

```markdown
## 验收口径声明（2026-09-06，WP3.1）

- **h1 降级为诊断口径**（本征尺度）：h1 帧间噪音敏感度过高，不再作为策略/门控验收的唯一依据。
- **策略/门控验收口径 = h4/h8（日内多档）+ 持有到收盘（hold-to-close）**：
  - h4/h8：`tier_forward_returns(horizon=4/8)` 与 `OutcomeEvaluator.evaluate(horizons=[1,3,5,10])` 并行输出。
  - hold-to-close：`OutcomeEvaluator.evaluate(..., include_hold_to_close=True)`，entry 帧 → 同 tradingDate 尾帧强制出场。
- **成本敏感性**：近盈亏平衡结论（four_dim pf 1.0377，lifecycle-layer-rearchitecture §7）引用前必须附
  `diagnose_cost_sensitivity` 弹性表；`fallbackSlippageRate` 自本声明起显式定值 0.001
  （此前运行时默认 0，快照退化成交未计罚金——口径切换点，历史数字不回改）。
- 8 月冻结纪律适用：口径切换不重算历史结论，仅声明切换点与新旧口径映射。
```

- [ ] **Step 2: overfitting-audit §2.1 勘误注记 + L1 档案/计划文档标题加注**

在该文档 §2.1（lifecycle 被列为"投票"维处）紧随其后加注（不改正文）：

```markdown
> 勘误（2026-09-06）：本节成文时的"四维"表述为历史命名。当前口径为 **5 投票维（res/rank/vp/cs + 热榜情绪）
> + 1 环境门（lifecycle）**；lifecycle 不参与投票，以 veto/降档方式影响总档信号合成（环境门语义）。
```

再执行 `rg -ln "四维" quant-board/docs/ranktrend-tier-backtest/`，对命中"四维 column plan"等标题/条目的文档（L1 档案、相关计划文档）在对应标题行下加一行新旧命名映射注记（格式同上，不批量重命名文件、不改标题原文）。

- [ ] **Step 3: 提交**

```bash
git add quant-board/docs/ranktrend-tier-backtest/
git commit -m "docs(ranktrend): 验收口径声明（h1 降诊断口径 + hold-to-close + 成本敏感性）与四维命名勘误注记"
```

---

### Task 7: 前端"四维"命名同步（只改文案）

**Files:**
- Modify: `src/stores/ui.ts`、`src/components/common/DataTable.vue`、`src/services/dataLoader/DataLoaderFacade.ts`、`src/services/rankTrend/types.ts`、`src/services/rankTrend/tierDisplay.ts`（以 rg 实际命中与语境为准）
- Modify: `src/components/common/__tests__/DataTable.test.ts`、`src/services/rankTrend/__tests__/tierDisplay.test.ts`（对应断言同步）

- [ ] **Step 1: 逐处核对语境**

Run: `rg -n "四维" src/ --type ts --type-add 'vue:*.vue' -t vue`
对每处命中判断：是"四维信号/四维评分"类命名表述 → 改为"5 投票维 + 1 环境门"（或上下文更顺的等价表述，如表格列头空间受限用"投票维×5+环境门"）；是无关的"四维矩阵/四象限"类表述 → 不动。**只改文案字符串与注释，不改任何标识符、字段名、逻辑分支。**

- [ ] **Step 2: 同步测试断言**

两个测试文件中与被改文案对应的断言字符串同步；其余断言不动。

- [ ] **Step 3: 验证**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false && pnpm test -- src/services/rankTrend/__tests__/tierDisplay.test.ts src/components/common/__tests__/DataTable.test.ts`
Expected: 类型检查零错误；两个测试文件全绿。

- [ ] **Step 4: 提交**

```bash
git add src/stores/ui.ts src/components/common/DataTable.vue src/services/dataLoader/DataLoaderFacade.ts src/services/rankTrend/types.ts src/services/rankTrend/tierDisplay.ts src/components/common/__tests__/DataTable.test.ts src/services/rankTrend/__tests__/tierDisplay.test.ts
git commit -m "refactor(ranktrend): 前端四维历史命名同步为 5 投票维 + 1 环境门（仅文案）"
```

---

## 验证总清单

- `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_flip_stats.py tests/test_diagnose_gate_flip_rate.py tests/test_outcome_hold_to_close.py tests/test_cost_sensitivity.py -v` 全绿。
- 8 月冻结段基线 JSON + `gate-flip-baseline-2026-08.md` 归档完成（WP2 前置达成）。
- 成本敏感性弹性表对 8 月段产出（four_dim pf 1.0377 稳健性佐证）。
- 前端 `vue-tsc` 零错误 + 两个前端测试文件绿。

## 风险与回退

- 三类产物（脚本/口径/文案）相互独立，逐 Task revert 净移除。
- `fallbackSlippageRate` 定值是唯一改变现行为的点（fallback 成交价变差 → pf 类数字可能下移）：文档声明口径切换点；如需回退，将该键从 DEFAULT_TRADE_CONFIG 移除即回到运行时默认 0（消费逻辑未改）。
- 翻转率/成本脚本只读不写库，无生产风险；`evaluate` 扩展默认关闭（返回 dict 仅多 `holdToClose: None` 键，JSON 序列化向后兼容），计算路径零变化。
- hold-to-close 口径为**无成本纯价差**（与现有 horizons 同一 `_outcome` 路径）；成本评估归 TradeSimulator/成本扫描，两个口径不混用——Task 6 文档显式声明，避免读数时误当含成本收益。
- 翻转率报告的 stage 桶统计是分桶近似（桶内 per-code 序列合并计翻转），per-code 精确翻转以主报告 `flip_counts` 为准——归档文档中注明。
- 前端只动文案字符串，vue-tsc + 定向测试覆盖。
