# RankTrend Live Gate Shadow Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一条 research-only 的 shadow audit 链路，在最近一周 `half_hour` 快照上逐帧审计 RankTrend live 候选前置门槛，解释漏票来源并输出“硬门槛 vs 排序项”建议，不改当前 live 自动入池逻辑。

**Architecture:** 先在 Python 分析层新增纯函数模块，显式拆分 `jump gate` 与 `fusion gate`，定义正交 shadow 变量矩阵、逐票归因和排序诊断。然后在 `services.py` 中新增一个只读审计服务，负责加载 `dragonboard_live` frame、对 baseline 与需要单独回放的 delta 变体分别调用 `RankTrendPythonEngine.replay_frame_at()`、聚合最近一周逐帧结果。最后通过 CLI 暴露命令，并把命令合同同步到 `api-cli.md`。

**Tech Stack:** Python 3, QuantBoard backend services, Mongo/Repository facade, pytest, argparse, Markdown docs

---

## File Map

- Create: `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
  - 纯分析模块，定义正交 shadow 变量矩阵、`jump/fusion` 双层 gate 判断、focus 样本归因、排序诊断和聚合摘要 helper
- Modify: `quant-board/backend/services.py`
  - 新增 `RankTrendLiveGateAuditService`，加载最近一周 frame，按 baseline + delta 独立 replay 逐帧产出统一 JSON 报告
- Modify: `quant-board/backend/cli.py`
  - 新增 `audit-ranktrend-live-gates` CLI 命令，支持 `dataset-id / snapshot-type / start-date / end-date / focus-code / output`
- Create: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`
  - 覆盖纯分析模块、服务聚合逻辑、delta replay 语义和 CLI parser/command wiring
- Modify: `quant-board/docs/api-cli.md`
  - 记录新 CLI 命令的用途、参数、示例、输出结构与 research-only 边界

---

## 默认变体矩阵约束

实现前先锁定以下约束，后续代码与测试必须围绕它：

```python
DEFAULT_SHADOW_VARIANTS = (
    ShadowVariant(key="baseline", label="baseline"),
    ShadowVariant(
        key="delta_12_5",
        label="delta=12.5",
        jump_delta_pct=12.5,
        requires_separate_replay=True,
    ),
    ShadowVariant(
        key="delta_10",
        label="delta=10",
        jump_delta_pct=10.0,
        requires_separate_replay=True,
    ),
    ShadowVariant(key="confidence_85", label="jump>=85", min_jump_confidence=85.0),
    ShadowVariant(key="confidence_80", label="jump>=80", min_jump_confidence=80.0),
    ShadowVariant(key="change_no_gate", label="change不硬拦", require_change_lt_6=False),
    ShadowVariant(key="allow_degraded", label="允许degraded", allow_degraded_sample=True),
    ShadowVariant(key="tier_no_gate", label="不卡tier", require_tier_gate=False),
    ShadowVariant(
        key="recall_first",
        label="召回优先全放",
        jump_delta_pct=10.0,
        min_jump_confidence=80.0,
        require_change_lt_6=False,
        allow_degraded_sample=True,
        require_tier_gate=False,
        requires_separate_replay=True,
    ),
)
```

硬要求：

- 单变量变体只改一项参数
- `delta_12_5 / delta_10 / recall_first` 必须标记 `requires_separate_replay=True`
- 移除 `accdelta_optional`
- 报告 `meta` 必须显式说明：当前 live 数据里 `accDelta` 普遍缺失，acceleration gate 实际主要依赖 `acceleration`

---

### Task 1: 写纯分析模块并锁定正交 shadow 变量矩阵

**Files:**
- Create: `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
- Create: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 先写失败测试，锁定分析层输出必须拆成 jump / fusion 两层，且变体矩阵是正交的**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import (
    DEFAULT_SHADOW_VARIANTS,
    evaluate_shadow_variants,
    summarize_first_failure,
)


def make_signal(**overrides):
    base = {
        "code": "600186",
        "name": "莲花控股",
        "change": 6.0057,
        "accDelta": None,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "confidence": 88.0, "sustained": True},
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "buy"},
                    "zeroCross": {"signal": "buy"},
                },
                "momentumProfile": {
                    "short": 2.17,
                    "mid": 10.41,
                    "long": 1.42,
                    "acceleration": 11.3,
                },
            },
            "meta": {"sampleQuality": {"status": "ok"}},
            "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
            "strategy": {"candidateTier": "N_NEUTRAL"},
        },
    }
    for key, value in overrides.items():
        base[key] = value
    return base


def test_shadow_variants_are_orthogonal_and_split_jump_vs_fusion():
    signal = make_signal()

    result = evaluate_shadow_variants(signal, variants=DEFAULT_SHADOW_VARIANTS)

    assert [variant.key for variant in DEFAULT_SHADOW_VARIANTS] == [
        "baseline",
        "delta_12_5",
        "delta_10",
        "confidence_85",
        "confidence_80",
        "change_no_gate",
        "allow_degraded",
        "tier_no_gate",
        "recall_first",
    ]
    assert result["baseline"]["jump"]["triggered"] is False
    assert result["confidence_85"]["jump"]["triggered"] is True
    assert result["change_no_gate"]["fusion"]["triggered"] is False
    assert result["tier_no_gate"]["fusion"]["triggered"] is False
    assert result["recall_first"]["triggered"] is True
    assert summarize_first_failure(result["baseline"]["jump"]["checks"]) == "jump_confidence"
    assert summarize_first_failure(result["baseline"]["fusion"]["checks"]) == "change_lt_6"
```

- [ ] **Step 2: 再写失败测试，锁定排序诊断只加分不硬 veto，且 meta 会暴露 accDelta 缺失提示**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import (
    build_audit_meta,
    rank_shadow_candidate,
)


def test_rank_shadow_candidate_prefers_stage_and_tier_without_reintroducing_hard_filters():
    scored = rank_shadow_candidate(
        {
            "code": "600186",
            "change": 6.2,
            "rankTrend": {
                "cycle": {"stage": "ignition"},
                "strategy": {"candidateTier": "N_NEUTRAL"},
                "technical": {
                    "macd": {"cross": "none"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                },
            },
        }
    )

    meta = build_audit_meta(acc_delta_present_ratio=0.0)

    assert scored["score"] > 0
    assert "stage:ignition" in scored["reasons"]
    assert "direction:buy" in scored["reasons"]
    assert "zeroCross:buy" in scored["reasons"]
    assert meta["accDeltaPolicy"].startswith("live数据当前缺少accDelta")
```

- [ ] **Step 3: 补边界测试，锁定空信号、缺失字段和 null jump 不会抛异常**

```python
def test_evaluate_shadow_variants_handles_null_and_missing_fields():
    # 空 rankTrend
    result = evaluate_shadow_variants({"code": "000001", "change": 0}, variants=DEFAULT_SHADOW_VARIANTS)
    assert result["baseline"]["triggered"] is False
    assert all(not check["passed"] for check in result["baseline"]["jump"]["checks"])

    # jump 为 null
    signal = make_signal()
    signal["rankTrend"]["jump"] = None
    result = evaluate_shadow_variants(signal, variants=DEFAULT_SHADOW_VARIANTS)
    assert result["baseline"]["triggered"] is False

    # rankTrend 完全缺失
    result = evaluate_shadow_variants({"code": "000001"}, variants=DEFAULT_SHADOW_VARIANTS)
    assert result["baseline"]["triggered"] is False
```

- [ ] **Step 4: 跑测试，确认模块尚不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `backend.analysis.ranktrend_live_gate_shadow_audit` 不存在。

- [ ] **Step 5: 最小实现纯分析模块**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShadowVariant:
    key: str
    label: str
    jump_delta_pct: float = 15.0
    min_jump_confidence: float = 90.0
    require_change_lt_6: bool = True
    allow_degraded_sample: bool = False
    require_tier_gate: bool = True
    requires_separate_replay: bool = False


DEFAULT_SHADOW_VARIANTS = (...)


def evaluate_shadow_variants(
    signal: dict[str, Any],
    variants=DEFAULT_SHADOW_VARIANTS,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    jump_signal = ((signal.get("rankTrend") or {}).get("jump") or {})
    for variant in variants:
        jump_checks, fusion_checks = evaluate_variant_layers(signal, variant)
        jump_triggered = all(check["passed"] for check in jump_checks)
        fusion_triggered = all(check["passed"] for check in fusion_checks)
        output[variant.key] = {
            "variant": variant.key,
            "requiresSeparateReplay": variant.requires_separate_replay,
            "jump": {
                "triggered": jump_triggered,
                "signal": jump_signal,
                "checks": jump_checks,
            },
            "fusion": {
                "triggered": fusion_triggered,
                "checks": fusion_checks,
            },
            "triggered": jump_triggered and fusion_triggered,
        }
    return output


def evaluate_variant_layers(
    signal: dict[str, Any],
    variant: ShadowVariant,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ...


def build_audit_meta(*, acc_delta_present_ratio: float) -> dict[str, Any]:
    return {
        "accDeltaPresentRatio": acc_delta_present_ratio,
        "accDeltaPolicy": (
            "live数据当前缺少accDelta，acceleration gate 实际主要依赖 acceleration"
            if acc_delta_present_ratio <= 0
            else "accDelta 可参与辅助解释，但当前不作为独立 shadow 变体"
        ),
    }
```

`jump_checks` 至少覆盖：

- `jump_event_is_jump`
- `jump_sustained`
- `jump_direction_buy`
- `jump_confidence`
- `technical_direction_buy`
- `technical_acceleration_buy`
- `change_gt_0`
- `not_limit_up`
- `macd_golden`

`fusion_checks` 至少覆盖：

- `short_mid_long_positive`
- `acceleration_or_accdelta`（baseline 使用原始 `acceleration >= 10 || accDelta >= 8`，即使当前 live 数据上 `accDelta` 普遍缺失）
- `change_lt_6`
- `not_limit_up`
- `sample_quality_ok`
- `cycle_not_veto`
- `tier_gate`

- [ ] **Step 6: 重新运行测试，确认纯分析层通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，至少包含 3 个分析层测试通过（正交拆分 + 排序诊断 + 边界防御）。

- [ ] **Step 7: Commit**

```powershell
git add quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py
git commit -m "feat: add ranktrend live gate shadow audit core"
```

---

### Task 2: 装配最近一周逐帧审计服务

**Files:**
- Modify: `quant-board/backend/services.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 写失败测试，锁定服务会分开处理 baseline replay、delta replay，并输出 jump / fusion 双层结果**

```python
from backend.services import RankTrendLiveGateAuditService


class FakeRepo:
    def load_dataset_bundle_slice(
        self,
        dataset_id,
        *,
        snapshot_types=None,
        start_date=None,
        end_date=None,
        max_snapshots=None,
    ):
        frames = [
            {
                "snapshotId": "half_hour:2026-06-09:10:30",
                "timestamp": 1,
                "tradingDate": "2026-06-09",
                "slotTime": "10:30",
                "type": "half_hour",
            }
        ]
        stock_rows = [
            {
                "snapshotId": "half_hour:2026-06-09:10:30",
                "code": "600186",
                "name": "莲花控股",
                "rank": 73,
                "change": 6.0057,
            }
        ]
        return [], frames, stock_rows, []


def test_live_gate_audit_service_exposes_two_layer_results_for_focus_stock(monkeypatch):
    service = RankTrendLiveGateAuditService.__new__(RankTrendLiveGateAuditService)
    service.repo = FakeRepo()

    monkeypatch.setattr(
        service,
        "_replay_frame_signals",
        lambda frames, index, *, jump_delta_pct=15.0: [
            {
                "snapshotId": frames[index]["snapshotId"],
                "tradingDate": frames[index]["tradingDate"],
                "slotTime": frames[index]["slotTime"],
                "code": "600186",
                "name": "莲花控股",
                "change": 6.0057,
                "rankTrend": {
                    "jump": {
                        "event": "jump",
                        "direction": "buy",
                        "confidence": 88.0,
                        "sustained": True,
                    },
                    "technical": {
                        "macd": {"cross": "golden"},
                        "signals": {
                            "direction": {"signal": "buy"},
                            "acceleration": {"signal": "buy"},
                            "zeroCross": {"signal": "buy"},
                        },
                        "momentumProfile": {
                            "short": 2.17,
                            "mid": 10.41,
                            "long": 1.42,
                            "acceleration": 11.3,
                        },
                    },
                    "meta": {"sampleQuality": {"status": "ok"}},
                    "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                    "strategy": {"candidateTier": "N_NEUTRAL"},
                },
            }
        ],
    )

    report = service.run(
        {
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "start_date": "2026-06-03",
            "end_date": "2026-06-09",
            "focus_codes": ["600186"],
        }
    )

    frame = report["focusFindings"][0]["frames"][0]

    assert report["meta"]["datasetId"] == "dragonboard_live"
    assert frame["baselineTriggered"] is False
    assert frame["baselineJumpTriggered"] is False
    assert frame["baselineFusionTriggered"] is False
    assert frame["firstJumpFailure"] == "jump_confidence"
    assert frame["firstFusionFailure"] == "change_lt_6"
```

- [ ] **Step 2: 再写失败测试，锁定 002156 类样本在不同 delta 下可能发生 jump.direction 翻转**

```python
def test_live_gate_audit_service_replays_delta_variants_instead_of_reusing_baseline_jump(monkeypatch):
    service = RankTrendLiveGateAuditService.__new__(RankTrendLiveGateAuditService)
    service.repo = FakeRepo()

    def fake_replay(frames, index, *, jump_delta_pct=15.0):
        direction = "sell" if jump_delta_pct >= 15.0 else "buy"
        confidence = 84.2 if jump_delta_pct >= 15.0 else 78.5
        return [
            {
                "snapshotId": frames[index]["snapshotId"],
                "tradingDate": frames[index]["tradingDate"],
                "slotTime": frames[index]["slotTime"],
                "code": "002156",
                "name": "通富微电",
                "change": 4.21,
                "rankTrend": {
                    "jump": {
                        "event": "jump",
                        "direction": direction,
                        "confidence": confidence,
                        "sustained": True,
                    },
                    "technical": {
                        "macd": {"cross": "golden"},
                        "signals": {
                            "direction": {"signal": "buy"},
                            "acceleration": {"signal": "buy"},
                            "zeroCross": {"signal": "buy"},
                        },
                        "momentumProfile": {
                            "short": 1.8,
                            "mid": 8.5,
                            "long": 1.3,
                            "acceleration": 10.2,
                        },
                    },
                    "meta": {"sampleQuality": {"status": "ok"}},
                    "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                    "strategy": {"candidateTier": "A_MAIN"},
                },
            }
        ]

    monkeypatch.setattr(service, "_replay_frame_signals", fake_replay)

    report = service.run({"dataset_id": "dragonboard_live", "focus_codes": ["002156"]})

    frame = report["focusFindings"][0]["frames"][0]

    assert frame["variantResults"]["baseline"]["jump"]["triggered"] is False
    assert frame["variantResults"]["delta_10"]["jump"]["triggered"] is True
    assert frame["variantResults"]["baseline"]["jump"]["signal"]["direction"] == "sell"
    assert frame["variantResults"]["delta_10"]["jump"]["signal"]["direction"] == "buy"
```

- [ ] **Step 3: 运行测试，确认服务类尚不存在或尚未支持 delta 独立 replay**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `RankTrendLiveGateAuditService` 不存在或输出结构不匹配。

- [ ] **Step 4: 在 `services.py` 中最小实现只读审计服务**

```python
from collections import defaultdict
from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend_live_gate_shadow_audit import (
    DEFAULT_SHADOW_VARIANTS,
    build_audit_meta,
    evaluate_shadow_variants,
    rank_shadow_candidate,
    summarize_first_failure,
)


class RankTrendLiveGateAuditService:
    def __init__(self, session: Session | None):
        self.repo = create_repository(session)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...
        baseline_signals = self._replay_frame_signals(frames, index, jump_delta_pct=15.0)
        variant_signal_map = self._resolve_variant_signals(frames, index, baseline_signals)
        ...

    def _resolve_variant_signals(
        self,
        frames: list[dict[str, Any]],
        index: int,
        baseline_signals: list[dict[str, Any]],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        variant_signals: dict[str, dict[str, dict[str, Any]]] = {}
        for variant in DEFAULT_SHADOW_VARIANTS:
            if not variant.requires_separate_replay:
                continue
            replay_result = self._replay_frame_signals(
                frames, index,
                jump_delta_pct=variant.jump_delta_pct,
            )
            variant_signals[variant.key] = {
                str(s.get("code") or ""): s for s in replay_result
            }
        return variant_signals

    def _replay_frame_signals(
        self,
        frames: list[dict[str, Any]],
        index: int,
        *,
        jump_delta_pct: float = 15.0,
    ) -> list[dict[str, Any]]:
        config = RankTrendConfig(jumpDeltaPct=jump_delta_pct)
        return RankTrendPythonEngine(config).replay_frame_at(frames, index, window_size=50)
```

服务层硬要求：

- `focusFindings` 每帧至少输出：
  - `baselineTriggered`
  - `baselineJumpTriggered`
  - `baselineFusionTriggered`
  - `firstJumpFailure`
  - `firstFusionFailure`
  - `variantResults`
- `variantResults` 必须直接保留 `jump` 与 `fusion` 两层结果
- `variantResults[*].jump.signal` 必须保留该变体回放得到的 jump 原始方向/置信度，便于审计 `direction` 翻转
- delta 变体不得复用 baseline `signal["rankTrend"]["jump"]`
- `accDeltaPresentRatio` 通过扫描所有 stock_rows 的 `accDelta` 字段计算非空比例：`sum(1 for r in all_stock_rows if r.get("accDelta") not in (None, "")) / max(len(all_stock_rows), 1)`
- `meta` 必须包含 `accDeltaPresentRatio` 与 `accDeltaPolicy`

- [ ] **Step 5: 重新运行测试，确认服务层聚合结果通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，服务测试与分析测试同时通过。

- [ ] **Step 6: Commit**

```powershell
git add quant-board/backend/services.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py
git commit -m "feat: add ranktrend live gate shadow audit service"
```

---

### Task 3: 暴露 CLI 命令并支持输出文件

**Files:**
- Modify: `quant-board/backend/cli.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 写失败测试，锁定 parser 和命令 wiring**

```python
from pathlib import Path


def test_cli_exposes_ranktrend_live_gate_audit_command():
    from backend.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id",
            "dragonboard_live",
            "--snapshot-type",
            "half_hour",
            "--start-date",
            "2026-06-03",
            "--end-date",
            "2026-06-09",
            "--focus-code",
            "600186",
            "--focus-code",
            "002156",
            "--output",
            "output/live_gate_audit.json",
        ]
    )

    assert args.dataset_id == "dragonboard_live"
    assert args.snapshot_type == "half_hour"
    assert args.focus_code == ["600186", "002156"]
    assert args.output == "output/live_gate_audit.json"


def test_cli_command_writes_report_json(monkeypatch, tmp_path):
    from backend import cli

    output_path = tmp_path / "audit.json"

    class FakeService:
        def __init__(self, _session):
            pass

        def run(self, payload):
            assert payload["focus_codes"] == ["600186"]
            return {
                "meta": {"datasetId": payload["dataset_id"], "snapshotType": "half_hour"},
                "focusFindings": [],
                "dailySummaries": [],
                "rankingSuggestions": [],
            }

    monkeypatch.setattr(cli, "RankTrendLiveGateAuditService", FakeService)

    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id",
            "dragonboard_live",
            "--focus-code",
            "600186",
            "--output",
            str(output_path),
        ]
    )

    args.func(args)

    assert output_path.exists() is True
    assert '"datasetId": "dragonboard_live"' in output_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行测试，确认 CLI 还未提供该命令**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `audit-ranktrend-live-gates` 未注册。

- [ ] **Step 3: 在 `cli.py` 中新增命令与输出文件支持**

```python
from pathlib import Path
from backend.services import RankTrendLiveGateAuditService


def cmd_audit_ranktrend_live_gates(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "focus_codes": args.focus_code or ["600186", "002156"],
        }
        result = RankTrendLiveGateAuditService(session).run(payload)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print_json(result)
```

CLI 约束：

- 默认 `snapshot_type=half_hour`
- 允许默认 `focus_codes=["600186", "002156"]`，但文档里必须标注这是近期漏票样本的临时默认值
- 不新增任何会修改 live 参数或候选池状态的开关

- [ ] **Step 4: 重新运行 CLI 测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，parser 和命令输出文件测试通过。

- [ ] **Step 5: Commit**

```powershell
git add quant-board/backend/cli.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py
git commit -m "feat: add ranktrend live gate shadow audit cli"
```

---

### Task 4: 同步 CLI 文档并跑最终验证

**Files:**
- Modify: `quant-board/docs/api-cli.md`

- [ ] **Step 1: 在 `api-cli.md` 增补命令说明，明确这是 research-only shadow audit**

````md
### `audit-ranktrend-live-gates`

运行 research-only shadow audit。该命令不会改动 live 自动入池，只会逐帧解释最近一周候选前置门槛的漏票来源。

```powershell
.\.venv\Scripts\python.exe -m backend.cli audit-ranktrend-live-gates `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --start-date 2026-06-03 `
  --end-date 2026-06-09 `
  --focus-code 600186 `
  --focus-code 002156 `
  --output output/live_gate_audit.json
```
````

- [ ] **Step 2: 记录输出结构与特殊说明**

````md
输出包含：

- `meta`
- `focusFindings`
- `dailySummaries`
- `rankingSuggestions`

其中：

- `focusFindings` 逐帧展示 baseline 与各 shadow variant 的 `jump` / `fusion` 两层结果
- `dailySummaries` 比较 baseline 与 shadow 变量的召回变化
- `rankingSuggestions` 只做排序建议，不是正式交易信号
- 默认 `focusCodes=["600186", "002156"]` 只是近期漏票样本的临时默认值
- `meta.accDeltaPolicy` 会提示当前 live 数据里 `accDelta` 缺失，因此 acceleration gate 主要依赖 `acceleration`
````

- [ ] **Step 3: 运行专用测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，审计模块、服务和 CLI 相关测试全部通过。

- [ ] **Step 4: 运行 QuantBoard 后端回归测试的最小集合**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py tests/test_ranktrend_jump_research.py tests/test_quant_board.py -q`

Expected: PASS，无 CLI 注册冲突，无现有 jump research 回归。

- [ ] **Step 5: Commit**

```powershell
git add quant-board/docs/api-cli.md
git commit -m "docs: document ranktrend live gate shadow audit cli"
```

---

## Self-Review

- Spec coverage:
  - 已覆盖最近一周 `half_hour` 审计窗口
  - 已覆盖正交 shadow 变量矩阵
  - 已覆盖 `jump gate` / `fusion gate` 双层输出
  - 已覆盖 delta 单独 replay 语义
  - 已明确 research-only，不修改 live 自动入池
- Placeholder scan:
  - 无 `TODO` / `TBD`
  - 每个任务都写明了文件、测试、命令与预期结果
- Type consistency:
  - 统一使用 `focusFindings / dailySummaries / rankingSuggestions`
  - 统一命令名为 `audit-ranktrend-live-gates`
  - 统一 payload 字段为 `dataset_id / snapshot_type / start_date / end_date / focus_codes`
  - 统一输出 `jump` 与 `fusion` 两层 gate 结果

## Execution Handoff

Plan complete and saved to `quant-board/docs/superpowers/plans/2026-06-09-ranktrend-live-gate-shadow-audit-implementation-plan.md`.

执行顺序固定为：

1. 先按本计划修正文档与测试预期
2. 再使用 `superpowers:subagent-driven-development`
3. 子任务内部严格按 `superpowers:test-driven-development` 执行
