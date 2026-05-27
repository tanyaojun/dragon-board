# Phase A-C 收尾 + 测试补齐 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task.

**Goal:** 补齐 L1 熔断、L3 跨期追踪，以及 code review 发现的测试缺口。

**Architecture:** services.py 新增两个纯函数（meltdown check + trend check），CLI 在读 JSONL 历史后调用，结果写入 checkpoint 记录。

**Design doc:** `quant-board/docs/optimization-long-task/2026-05-26-longtest-v2-design.md`

---

## File Map

| Task | File | Action |
|---|---|---|
| 1 | `quant-board/backend/services.py` | 新增 `read_checkpoint_history()` |
| 2 | `quant-board/backend/services.py` | 新增 `check_layer1_meltdown()` + `check_layer3_trend()` |
| 3 | `quant-board/backend/cli.py` | 接入熔断和追踪到 `cmd_run_longtest_baselines` |
| 4 | `quant-board/tests/test_money_flow_quality_gate.py` | 补 compute_alignment / signal_efficacy 边界测试 |
| 5 | `quant-board/tests/test_quant_board.py` | 补熔断 + 追踪集成测试 |

---

### Task 1: read_checkpoint_history()

**File:** `quant-board/backend/services.py`

读取 JSONL 文件，返回最近 N 条 checkpoint 记录。

```python
def read_checkpoint_history(
    jsonl_path: str | Path,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Read recent checkpoint records from long_test_runs.jsonl."""
    path = Path(jsonl_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json_loads(line.strip())
                if record and record.get("checkpointId"):
                    records.append(record)
            except Exception:
                continue
    return records[-limit:] if len(records) > limit else records
```

---

### Task 2: check_layer1_meltdown() + check_layer3_trend()

**File:** `quant-board/backend/services.py`

```python
def check_layer1_meltdown(
    history: list[dict[str, Any]],
    label_filter: str = "H1_half_hour_current_bar",
) -> dict[str, Any]:
    """Check if Layer 1 has been red for 3+ consecutive checkpoints (meltdown)."""
    if len(history) < 3:
        return {"meltdown": False, "consecutiveRedPeriods": 0, "diagnostics": "insufficient_history"}

    statuses: list[str] = []
    for record in history:
        baselines = record.get("baselines") or []
        baseline = next((b for b in baselines if b.get("label") == label_filter), None)
        if not baseline:
            continue
        l1 = baseline.get("layer1SignalEfficacy") or {}
        statuses.append(str(l1.get("layer1Status") or "unknown"))

    # Count consecutive red from most recent
    consecutive_red = 0
    for status in reversed(statuses):
        if status == "red":
            consecutive_red += 1
        else:
            break

    return {
        "meltdown": consecutive_red >= 3,
        "consecutiveRedPeriods": consecutive_red,
        "statuses": statuses[-6:],
        "recommendation": (
            "触发策略结构性复审：连续 3 期方向精度不达标，建议检查市场状态归属、信号有效性和执行方式"
            if consecutive_red >= 3
            else None
        ),
    }


def check_layer3_trend(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check Layer 3 alignment trend across recent checkpoints."""
    if len(history) < 2:
        return {"greenLight": False, "diagnostics": "insufficient_history"}

    statuses: list[str] = []
    for record in history[-2:]:
        l3 = record.get("layer3Alignment") or {}
        statuses.append(str(l3.get("alignmentStatus") or "unknown"))

    consecutive_sufficient = all(s == "sufficient" for s in statuses)

    return {
        "greenLight": consecutive_sufficient,
        "recentStatuses": statuses,
        "recommendation": (
            "连续 2 期对齐充足，Layer 3 绿灯"
            if consecutive_sufficient
            else None
        ),
    }
```

---

### Task 3: Wire into CLI

**File:** `quant-board/backend/cli.py`

In `cmd_run_longtest_baselines()`, after Layer 3 alignment is computed, add:

```python
    # Cross-period checks
    jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
    history = read_checkpoint_history(jsonl_path, limit=6)

    # L1 meltdown check
    l1_meltdown_h1 = check_layer1_meltdown(history, "H1_half_hour_current_bar")
    if l1_meltdown_h1.get("meltdown"):
        print(f"  ⚠️  L1 meltdown: {l1_meltdown_h1['consecutiveRedPeriods']} consecutive red periods on H1")

    # L3 trend check
    l3_trend = check_layer3_trend(history)
    if l3_trend.get("greenLight"):
        print(f"  ✅ L3 trend: 2 consecutive sufficient alignments → green light")

    result["crossPeriod"] = {
        "layer1MeltdownH1": l1_meltdown_h1,
        "layer3Trend": l3_trend,
    }
```

Import additions at top of cli.py:
```python
from backend.services import (..., read_checkpoint_history, check_layer1_meltdown, check_layer3_trend)
```

---

### Task 4: Unit test coverage

**File:** `quant-board/tests/test_money_flow_quality_gate.py`

Add:

```python
def test_compute_signal_efficacy_empty_signals() -> None:
    from backend.services import compute_signal_efficacy
    result = compute_signal_efficacy([], [])
    assert result["diagnostics"] == "no_signals"
    assert result["directionAccuracy"] is None

def test_compute_signal_efficacy_no_next_frame() -> None:
    from backend.services import compute_signal_efficacy
    signals = [{"snapshotId": "s_last", "code": "000001", "price": 10.0,
                "rankTrend": {"meta": {"sampleQuality": {"tier": "A_MAIN"}}}}]
    frames = [{"snapshotId": "s_last", "stocks": [{"code": "000001", "price": 10.0}]}]
    result = compute_signal_efficacy(signals, frames)
    assert result["aMainSamples"] == 0  # no next frame to check

def test_compute_alignment_unavailable_without_mongodb() -> None:
    from backend.services import compute_alignment
    class FakeRepo:
        pass
    result = compute_alignment(FakeRepo(), ["bt_test"])
    assert result["alignmentStatus"] == "unavailable"

def test_compute_alignment_empty_run_ids() -> None:
    from backend.services import compute_alignment
    class FakeRepo:
        def list_journal_entries(self, **kw):
            return []
    result = compute_alignment(FakeRepo(), [])
    assert result["journalExecutedCount"] == 0

def test_compute_execution_quality_with_history() -> None:
    from backend.services import compute_execution_quality
    h1 = {"totalReturn": 0.03, "tradeCount": 10, "maxDrawdown": -0.02}
    h2 = {"totalReturn": 0.01, "tradeCount": 12, "maxDrawdown": -0.03}
    history = [
        {"h1Summary": {"totalReturn": 0.04}, "h2Summary": {"totalReturn": 0.02}},
        {"h1Summary": {"totalReturn": 0.03}, "h2Summary": {"totalReturn": 0.01}},
        {"h1Summary": {"totalReturn": 0.02}, "h2Summary": {"totalReturn": 0.03}},  # H1 < H2
        {"h1Summary": {"totalReturn": 0.05}, "h2Summary": {"totalReturn": 0.01}},
    ]
    result = compute_execution_quality(h1, h2, history=history)
    assert result["directionRatio"] == 0.75  # 3/4 H1 >= H2
```

---

### Task 5: Integration test

**File:** `quant-board/tests/test_quant_board.py`

```python
def test_layer1_meltdown_detects_consecutive_red() -> None:
    from backend.services import check_layer1_meltdown
    history = [
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
    ]
    result = check_layer1_meltdown(history)
    assert result["meltdown"] is True
    assert result["consecutiveRedPeriods"] == 3

def test_layer1_meltdown_resets_on_green() -> None:
    from backend.services import check_layer1_meltdown
    history = [
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "green"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
    ]
    result = check_layer1_meltdown(history)
    assert result["meltdown"] is False
    assert result["consecutiveRedPeriods"] == 1

def test_layer3_trend_detects_consecutive_sufficient() -> None:
    from backend.services import check_layer3_trend
    history = [
        {"layer3Alignment": {"alignmentStatus": "sufficient"}},
        {"layer3Alignment": {"alignmentStatus": "sufficient"}},
    ]
    result = check_layer3_trend(history)
    assert result["greenLight"] is True

def test_layer3_trend_insufficient_history() -> None:
    from backend.services import check_layer3_trend
    result = check_layer3_trend([])
    assert result["greenLight"] is False
    assert result["diagnostics"] == "insufficient_history"
```

---

### Verification

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "meltdown or trend or empty_signals or no_next_frame or unavailable_without_mongodb or empty_run_ids or with_history" -v
```

Expected: all new tests pass, existing tests continue to pass.
