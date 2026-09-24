# 市场情绪阶段多帧确认平滑实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `hotlist_sentiment` 增加按当日原始截面序列重放的两槽确认阶段，同时在数据库、API 和界面完整保留每槽原始判定。

**Architecture:** `resolve_stage` 继续产生唯一权威截面值 `rawStage`；新增独立纯函数从严格早于当前槽的历史 `rawStage` 加本帧值重放出确认 `stage`。收集层分别维护日内 `stageShares` 证据与阶段确认证据，写口统一落三字段，API 和 UI 同时暴露确认值、原始值和历史质量状态。

**Tech Stack:** Python 3 / FastAPI / MongoDB / pytest / Vue 3 / TypeScript / Vitest / Playwright

**Spec:** `docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md`

**工作区纪律:** 当前主工作区已有用户未提交源码修改。执行前先核对 `git status --short`；每次只暂存本任务明确文件，不使用 `git add -A`、`git commit -a`、`git reset --hard` 或 `git checkout --`。

---

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `quant-board/backend/analysis/hotlist/stage_confirm.py` | 新增无 I/O 的确认状态机，避免修改 golden 对齐的 `sentiment.py` |
| `quant-board/backend/services/theme/hotlist_sentiment_compute.py` | 按当前槽因果截断收集 `points` 与 `rawStagePoints`，暴露历史质量 |
| `quant-board/backend/operations/hotlist_sentiment.py` | 将截面结果投影为三字段，并让所有生产写口共用该投影 |
| `quant-board/backend/api/hotlist_routes.py` | ingest 字段合同和 Redis cache version |
| `src/types/hotlistSentiment.ts` | 新字段类型 |
| `src/components/panels/DragonBreathPanel.vue` | 确认阶段、原始轨迹和截面证据的双轨展示 |
| `quant-board/operations/replay_stage_confirm.py` | 回放原始序列，报告降噪、延迟与质量计数 |

---

### Task 1: 纯函数确认状态机

**Files:**

- Create: `quant-board/backend/analysis/hotlist/stage_confirm.py`
- Test: `quant-board/tests/test_hotlist_stage_confirm.py`

- [ ] **Step 1: 写失败测试**

创建 `quant-board/tests/test_hotlist_stage_confirm.py`：

```python
from backend.analysis.hotlist.stage_confirm import confirm_stage


def test_first_frame_confirms_immediately() -> None:
    confirmed, state = confirm_stage([("09:30", "退潮")], 2)
    assert confirmed == "退潮"
    assert state == {
        "pending": False,
        "pendingStage": None,
        "pendingSince": None,
        "confirmSlots": 2,
    }


def test_single_candidate_is_pending_with_start_slot() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "退潮"), ("10:30", "高潮")], 2
    )
    assert confirmed == "退潮"
    assert state["pending"] is True
    assert state["pendingStage"] == "高潮"
    assert state["pendingSince"] == "10:30"


def test_two_consecutive_candidates_switch() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "高潮")], 2
    )
    assert confirmed == "高潮"
    assert state["pending"] is False
    assert state["pendingSince"] is None


def test_candidate_change_restarts_count() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "发酵"), ("11:00", "发酵")], 2
    )
    assert confirmed == "发酵"
    assert state["pending"] is False


def test_revert_to_confirmed_clears_candidate() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "退潮")], 2
    )
    assert confirmed == "退潮"
    assert state["pending"] is False


def test_slots_one_is_raw_passthrough() -> None:
    points = [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "发酵")]
    confirmed, state = confirm_stage(points, 1)
    assert confirmed == "发酵"
    assert state["pending"] is False


def test_empty_sequence_is_defensive_empty_result() -> None:
    confirmed, state = confirm_stage([], 2)
    assert confirmed == ""
    assert state["pending"] is False
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_stage_confirm.py -q
```

Expected: collection error，`backend.analysis.hotlist.stage_confirm` 不存在。

- [ ] **Step 3: 实现最小状态机**

创建 `quant-board/backend/analysis/hotlist/stage_confirm.py`：

```python
from __future__ import annotations

from collections.abc import Sequence


STAGE_CONFIRM_SLOTS_DEFAULT = 2


def confirm_stage(
    raw_points: Sequence[tuple[str, str]],
    confirm_slots: int = STAGE_CONFIRM_SLOTS_DEFAULT,
) -> tuple[str, dict[str, object]]:
    """按输入顺序重放阶段滞回；调用方负责提供已按槽位升序且因果截断的序列。"""
    slots = max(1, int(confirm_slots))
    state: dict[str, object] = {
        "pending": False,
        "pendingStage": None,
        "pendingSince": None,
        "confirmSlots": slots,
    }
    points = [(str(slot), str(stage).strip()) for slot, stage in raw_points if str(stage).strip()]
    if not points:
        return "", state

    confirmed = points[0][1]
    pending_stage: str | None = None
    pending_since: str | None = None
    pending_count = 0

    for slot_time, raw_stage in points[1:]:
        if raw_stage == confirmed:
            pending_stage = None
            pending_since = None
            pending_count = 0
            continue
        if raw_stage == pending_stage:
            pending_count += 1
        else:
            pending_stage = raw_stage
            pending_since = slot_time
            pending_count = 1
        if pending_count >= slots:
            confirmed = raw_stage
            pending_stage = None
            pending_since = None
            pending_count = 0

    if pending_stage is not None:
        state.update(
            pending=True,
            pendingStage=pending_stage,
            pendingSince=pending_since,
        )
    return confirmed, state
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: Task 1 Step 2 的命令。

Expected: `7 passed`。

- [ ] **Step 5: 提交本任务文件**

```powershell
git add quant-board/backend/analysis/hotlist/stage_confirm.py quant-board/tests/test_hotlist_stage_confirm.py
git commit -m "feat(hotlist-sentiment): add causal stage confirmation state machine"
```

---

### Task 2: 因果截断地收集两条独立日内轨道

**Files:**

- Modify: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`
- Test: `quant-board/tests/test_hotlist_sentiment_backfill.py`

- [ ] **Step 1: 为边界条件写失败测试**

在 `quant-board/tests/test_hotlist_sentiment_backfill.py` 追加：

```python
def test_collect_intraday_state_is_causal_and_excludes_both_eod_shapes() -> None:
    from backend.services.theme.hotlist_sentiment_compute import _collect_intraday_state

    db = FakeMongoDb()
    db["hotlist_sentiment"].rows = [
        {"_id": "d1:half_hour:2026-06-04:09:30", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "09:30", "rawStage": "退潮"},
        {"_id": "d1:half_hour:2026-06-04:10:00", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "10:00", "rawStage": "高潮"},
        {"_id": "d1:half_hour:2026-06-04:11:00", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "11:00", "rawStage": "发酵"},
        {"_id": "d1:half_hour:2026-06-04", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "15:00", "stage": "启动"},
        {"_id": "legacy-eod", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "EOD", "stage": "冰点"},
    ]

    state = _collect_intraday_state(db, "d1", "half_hour", "2026-06-04", before_slot="10:30")

    assert state["rawStagePoints"] == [("09:30", "退潮"), ("10:00", "高潮")]
    assert state["historyStatus"] == "complete"


def test_collect_intraday_state_keeps_points_and_stage_tracks_independent() -> None:
    from backend.services.theme.hotlist_sentiment_compute import _collect_intraday_state

    db = FakeMongoDb()
    db["hotlist_sentiment"].rows = [
        {"_id": "d1:half_hour:2026-06-04:09:30", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "09:30",
         "metrics": {"layers": {"all": {"stageShares": {"cooling": 0.7}}}}},
        {"_id": "d1:half_hour:2026-06-04:10:00", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "10:00", "rawStage": "高潮"},
    ]

    state = _collect_intraday_state(db, "d1", "half_hour", "2026-06-04", before_slot="10:30")

    assert [point["slotTime"] for point in state["points"]] == ["09:30"]
    assert state["rawStagePoints"] == [("10:00", "高潮")]


def test_collect_intraday_state_marks_legacy_fallback() -> None:
    from backend.services.theme.hotlist_sentiment_compute import _collect_intraday_state

    db = FakeMongoDb()
    db["hotlist_sentiment"].rows = [
        {"_id": "d1:half_hour:2026-06-04:09:30", "datasetId": "d1", "snapshotType": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "09:30", "stage": "退潮"},
    ]
    state = _collect_intraday_state(db, "d1", "half_hour", "2026-06-04", before_slot="10:00")
    assert state["rawStagePoints"] == [("09:30", "退潮")]
    assert state["historyStatus"] == "legacy_fallback"
    assert state["diagnostics"]


def test_collect_intraday_state_read_failure_is_visible() -> None:
    from backend.services.theme.hotlist_sentiment_compute import _collect_intraday_state

    class BrokenCollection:
        def find(self, query=None, projection=None):
            raise RuntimeError("boom")

    db = FakeMongoDb()
    db.collections["hotlist_sentiment"] = BrokenCollection()
    state = _collect_intraday_state(db, "d1", "half_hour", "2026-06-04", before_slot="10:00")
    assert state["points"] == []
    assert state["rawStagePoints"] == []
    assert state["historyStatus"] == "unavailable"
    assert "boom" in state["diagnostics"][0]
```

- [ ] **Step 2: 运行测试并确认 RED**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_sentiment_backfill.py -q -k collect_intraday_state
```

Expected: `_collect_intraday_state` 不存在或合同不匹配。

- [ ] **Step 3: 用结构化返回替换 `_collect_intraday_history`**

在 `quant-board/backend/services/theme/hotlist_sentiment_compute.py` 中实现：

```python
def _collect_intraday_state(
    db: Any,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    *,
    before_slot: str,
) -> dict[str, Any]:
    eod_id = f"{dataset_id}:{snapshot_type}:{trading_date}"
    points: list[dict[str, Any]] = []
    raw_stage_points: list[tuple[str, str]] = []
    diagnostics: list[str] = []
    legacy_count = 0
    try:
        rows = db["hotlist_sentiment"].find(
            {
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": {"$ne": "EOD"},
            },
            {"_id": 1, "slotTime": 1, "stage": 1, "rawStage": 1,
             "metrics.layers.all.stageShares": 1},
        )
        for row in rows:
            if str(row.get("_id") or "") == eod_id:
                continue
            slot_time = str(row.get("slotTime") or "")
            if len(slot_time) != 5 or slot_time[2] != ":":
                diagnostics.append(f"stage_confirm_nonstandard_slot:{slot_time or '<missing>'}")
                continue
            if slot_time >= before_slot:
                continue
            shares = (((row.get("metrics") or {}).get("layers") or {}).get("all") or {}).get("stageShares")
            if isinstance(shares, dict) and shares:
                points.append({"slotTime": slot_time, "stageShares": shares})
            raw_stage = str(row.get("rawStage") or "").strip()
            if not raw_stage:
                raw_stage = str(row.get("stage") or "").strip()
                if raw_stage:
                    legacy_count += 1
            if raw_stage:
                raw_stage_points.append((slot_time, raw_stage))
        points.sort(key=lambda item: item["slotTime"])
        raw_stage_points.sort(key=lambda item: item[0])
        if legacy_count:
            diagnostics.append(f"stage_confirm_legacy_fallback:{legacy_count}")
        status = "legacy_fallback" if legacy_count else "complete" if raw_stage_points else "empty"
        return {
            "points": points,
            "rawStagePoints": raw_stage_points,
            "historyStatus": status,
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        return {
            "points": [],
            "rawStagePoints": [],
            "historyStatus": "unavailable",
            "diagnostics": [f"stage_confirm_history_unavailable:{type(exc).__name__}:{exc}"],
        }
```

不要让 stage 是否存在决定 `points` 是否保留；两个列表必须独立追加。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: Task 2 Step 2 的命令。

Expected: 4 个新增测试通过。

- [ ] **Step 5: 提交本任务文件**

```powershell
git add quant-board/backend/services/theme/hotlist_sentiment_compute.py quant-board/tests/test_hotlist_sentiment_backfill.py
git commit -m "feat(hotlist-sentiment): collect causal raw stage history"
```

---

### Task 3: 文档投影三字段并锁定 EOD 同帧语义

**Files:**

- Modify: `quant-board/backend/operations/hotlist_sentiment.py`
- Test: `quant-board/tests/test_hotlist_sentiment_backfill.py`

- [ ] **Step 1: 写文档投影失败测试**

在 `quant-board/tests/test_hotlist_sentiment_backfill.py` 追加测试；使用 `monkeypatch` 固定截面输出，避免用被测确认函数计算期望值：

```python
def _fake_sentiment_result(stage: str) -> dict:
    return {
        "stage": stage, "riskLevel": "中", "confidence": 60, "summary": f"{stage}截面摘要",
        "metrics": {"topN": 0, "layers": {"all": {"total": 0, "topN": 0,
            "upRatio": 0, "hotTrin": None, "stageCounts": {}, "stageShares": {}}},
            "comparison": {"top100RetainRateFromYesterday": None,
                "top100RetainRateFromDayBefore": None},
            "limitEvidence": {"intersection": {"top100LimitUpShare": 0}},
            "transitionCounts": {}},
        "turnover": {"newEntries": [], "eliminated": []},
        "signals": [], "warnings": [], "statusSourceCounts": {"displayStatus": 0, "fallback": 0},
        "missingEvidence": [],
    }


def test_document_persists_raw_and_pending_state(monkeypatch) -> None:
    import backend.operations.hotlist_sentiment as module

    monkeypatch.setattr(module, "compute_hotlist_sentiment", lambda *args, **kwargs: _fake_sentiment_result("高潮"))
    doc = module.build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-04",
        frame={"snapshotId": "s1030", "slotTime": "10:30", "timestamp": 1}, stocks=[{"code": "000001"}],
        slot_time="10:30", current_slot="10:30",
        stage_history={"rawStagePoints": [("09:30", "退潮"), ("10:00", "退潮")],
            "historyStatus": "complete", "diagnostics": []}, stage_confirm_slots=2,
    )
    assert doc["stage"] == "退潮"
    assert doc["rawStage"] == "高潮"
    assert doc["stageConfirmState"]["pendingStage"] == "高潮"
    assert doc["stageConfirmState"]["pendingSince"] == "10:30"
    assert doc["summary"] == "高潮截面摘要"


def test_document_switches_after_second_candidate(monkeypatch) -> None:
    import backend.operations.hotlist_sentiment as module

    monkeypatch.setattr(module, "compute_hotlist_sentiment", lambda *args, **kwargs: _fake_sentiment_result("高潮"))
    doc = module.build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-04",
        frame={"snapshotId": "s1100", "slotTime": "11:00", "timestamp": 2}, stocks=[{"code": "000001"}],
        slot_time="11:00", current_slot="11:00",
        stage_history={"rawStagePoints": [("09:30", "退潮"), ("10:30", "高潮")],
            "historyStatus": "complete", "diagnostics": []}, stage_confirm_slots=2,
    )
    assert doc["stage"] == "高潮"
    assert doc["rawStage"] == "高潮"
    assert doc["stageConfirmState"]["pending"] is False


def test_unavailable_history_keeps_raw_and_diagnostic(monkeypatch) -> None:
    import backend.operations.hotlist_sentiment as module

    monkeypatch.setattr(module, "compute_hotlist_sentiment", lambda *args, **kwargs: _fake_sentiment_result("发酵"))
    doc = module.build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-04",
        frame={"snapshotId": "s1000", "slotTime": "10:00", "timestamp": 1}, stocks=[{"code": "000001"}],
        slot_time="10:00", current_slot="10:00",
        stage_history={"rawStagePoints": [], "historyStatus": "unavailable",
            "diagnostics": ["stage_confirm_history_unavailable:RuntimeError:boom"]}, stage_confirm_slots=2,
    )
    assert doc["stage"] == doc["rawStage"] == "发酵"
    assert doc["stageConfirmState"]["historyStatus"] == "unavailable"
    assert doc["diagnostics"] == ["stage_confirm_history_unavailable:RuntimeError:boom"]
```

- [ ] **Step 2: 运行测试并确认 RED**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_sentiment_backfill.py -q -k "document_persists_raw or document_switches or unavailable_history"
```

Expected: `stage_history` / `stage_confirm_slots` 参数不存在或新字段缺失。

- [ ] **Step 3: 接入纯函数并保留截面字段语义**

在 `build_hotlist_sentiment_document` 的 `current_slot` 后增加：

```python
    stage_history: dict[str, Any] | None = None,
    stage_confirm_slots: int = 2,
```

在 `compute_hotlist_sentiment(...)` 后增加：

```python
    from backend.analysis.hotlist.stage_confirm import confirm_stage

    raw_stage_value = str(result["stage"])
    history = stage_history or {
        "rawStagePoints": [], "historyStatus": "empty", "diagnostics": []
    }
    history_status = str(history.get("historyStatus") or "empty")
    prior_points = list(history.get("rawStagePoints") or [])
    current_stage_slot = str(current_slot or frame.get("slotTime") or slot)
    points = [(current_stage_slot, raw_stage_value)] if history_status == "unavailable" else [
        *prior_points, (current_stage_slot, raw_stage_value)
    ]
    confirmed_stage, confirm_state = confirm_stage(points, stage_confirm_slots)
    confirm_state["historyStatus"] = history_status
```

返回字典改为：

```python
        "stage": confirmed_stage or raw_stage_value,
        "rawStage": raw_stage_value,
        "stageConfirmState": confirm_state,
```

并将诊断初值改为：

```python
        "diagnostics": list(history.get("diagnostics") or []),
```

`summary/riskLevel/confidence/signals/warnings` 继续来自 `result`，其合同是本帧截面证据；不要根据确认阶段二次计算。

- [ ] **Step 4: 增加 EOD 与锚定槽等价测试**

再追加：

```python
def test_eod_does_not_count_anchored_frame_twice(monkeypatch) -> None:
    import backend.operations.hotlist_sentiment as module

    monkeypatch.setattr(module, "compute_hotlist_sentiment", lambda *args, **kwargs: _fake_sentiment_result("高潮"))
    common = dict(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-04",
        frame={"snapshotId": "s1030", "slotTime": "10:30", "timestamp": 1}, stocks=[{"code": "000001"}],
        current_slot="10:30", stage_history={"rawStagePoints": [("09:30", "退潮")],
            "historyStatus": "complete", "diagnostics": []}, stage_confirm_slots=2,
    )
    slot_doc = module.build_hotlist_sentiment_document(**common, slot_time="10:30")
    eod_doc = module.build_hotlist_sentiment_document(**common)
    assert slot_doc["stage"] == eod_doc["stage"] == "退潮"
    assert slot_doc["stageConfirmState"] == eod_doc["stageConfirmState"]
```

- [ ] **Step 5: 运行新增测试并确认 GREEN**

Run: Task 3 Step 2 的命令，去掉 `-k` 过滤后运行整个测试文件。

Expected: 全部通过。

- [ ] **Step 6: 提交本任务文件**

```powershell
git add quant-board/backend/operations/hotlist_sentiment.py quant-board/tests/test_hotlist_sentiment_backfill.py
git commit -m "feat(hotlist-sentiment): persist raw and confirmed stage projections"
```

---

### Task 4: 四个生产编排入口共用因果历史

**Files:**

- Modify: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`
- Modify: `quant-board/backend/operations/hotlist_sentiment.py`
- Test: `quant-board/tests/test_hotlist_sentiment_backfill.py`
- Test: `quant-board/tests/test_hotlist_sentiment_collector_hook.py`
- Test: `quant-board/tests/test_hotlist_sentiment_after_market.py`

- [ ] **Step 1: 写未来槽不污染过去槽的集成测试**

在 `test_hotlist_sentiment_collector_hook.py` 中增加一个测试：预置 `09:30=退潮` 与未来 `11:00=高潮` 情绪文档，固定 `10:00` 截面为高潮，调用 `compute_and_upsert_for_slot(..., slot_time="10:00")` 后断言 `10:00` 仍是 pending 的退潮，而不是被 `11:00` 提前确认。期望值直接写死：

```python
assert doc["rawStage"] == "高潮"
assert doc["stage"] == "退潮"
assert doc["stageConfirmState"]["pending"] is True
assert doc["stageConfirmState"]["pendingSince"] == "10:00"
```

测试通过 monkeypatch `backend.operations.hotlist_sentiment.compute_hotlist_sentiment` 返回 Task 3 的 `_fake_sentiment_result("高潮")` 等价完整字典，不调用 `confirm_stage` 生成期望值。

- [ ] **Step 2: 写顺序回填与乱序回填结果一致测试**

为同一组三个槽 `09:30=退潮、10:00=高潮、10:30=高潮` 建两个 FakeMongo：一个按时间写入，一个先放 `10:30` 再重算 `09:30/10:00/10:30`。最终逐槽断言：

```python
assert [(d["slotTime"], d["stage"], d["rawStage"]) for d in ordered_docs] == [
    (d["slotTime"], d["stage"], d["rawStage"]) for d in out_of_order_docs
]
```

- [ ] **Step 3: 运行测试并确认 RED**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_sentiment_collector_hook.py tests\test_hotlist_sentiment_backfill.py -q -k "future_slot or write_order"
```

Expected: 未来槽进入历史或编排入口尚未传 `stage_history`。

- [ ] **Step 4: 增加 fail-visible 环境变量解析**

在 `hotlist_sentiment_compute.py` 增加：

```python
def _stage_confirm_config() -> tuple[int, str | None]:
    import os

    raw = os.environ.get("HOTLIST_STAGE_CONFIRM_SLOTS", "2")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 2, f"stage_confirm_invalid_config:{raw!r}:fallback=2"
    if value < 1:
        return 2, f"stage_confirm_invalid_config:{raw!r}:fallback=2"
    return value, None
```

非法值回到裁决默认值 2，并把原因追加进文档 `diagnostics`；不能静默退化为 1。

- [ ] **Step 5: 修改四个入口**

对 `_compute_and_persist`、`compute_and_upsert_for_slot`、`run_for_date`、`run_for_date_slots` 使用同一顺序：

```python
current_stage_slot = str(frame.get("slotTime") or slot_time)
intraday_state = _collect_intraday_state(
    db, dataset_id, snapshot_type, trading_date, before_slot=current_stage_slot
)
confirm_slots, config_diagnostic = _stage_confirm_config()
if config_diagnostic:
    intraday_state["diagnostics"].append(config_diagnostic)
```

传给文档构造器：

```python
intraday_history=intraday_state["points"],
current_slot=current_stage_slot,
stage_history=intraday_state,
stage_confirm_slots=confirm_slots,
```

EOD 与槽位入口都以帧的实际 `slotTime` 作为 `before_slot/current_slot`，不要使用 `EOD` 哨兵。删除旧 `_collect_intraday_history` 的所有调用；确认 `rg -n "_collect_intraday_history" quant-board/backend` 无结果。

- [ ] **Step 6: 测试配置边界和四入口字段合同**

新增测试覆盖环境变量缺省 `2`、合法 `1/3`、非法字符串、`0` 和负数；非法值必须是 `(2, diagnostic)`。现有 collector、after-market、backfill tests 增加断言：

```python
assert doc["rawStage"]
assert doc["stage"]
assert doc["stageConfirmState"]["confirmSlots"] == expected_slots
```

- [ ] **Step 7: 运行情绪写链测试**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest `
  tests\test_hotlist_stage_confirm.py `
  tests\test_hotlist_sentiment_backfill.py `
  tests\test_hotlist_sentiment_backfill_slots.py `
  tests\test_hotlist_sentiment_collector_hook.py `
  tests\test_hotlist_sentiment_after_market.py `
  tests\test_hotlist_sentiment_intraday.py `
  tests\test_hotlist_sentiment_recompute.py -q
```

Expected: exit code 0，无失败。

- [ ] **Step 8: 提交本任务文件**

```powershell
git add quant-board/backend/services/theme/hotlist_sentiment_compute.py quant-board/backend/operations/hotlist_sentiment.py quant-board/tests/test_hotlist_sentiment_backfill.py quant-board/tests/test_hotlist_sentiment_collector_hook.py quant-board/tests/test_hotlist_sentiment_after_market.py
git commit -m "feat(hotlist-sentiment): wire causal confirmation across all writers"
```

---

### Task 5: ingest 与缓存合同

**Files:**

- Modify: `quant-board/backend/api/hotlist_routes.py`
- Test: `quant-board/tests/test_hotlist_sentiment_api.py`
- Test: `quant-board/tests/test_hotlist_sentiment_series_api.py`
- Test: `quant-board/tests/test_hotlist_sentiment_slots_api.py`

- [ ] **Step 1: 写 ingest 往返失败测试**

在 `test_hotlist_sentiment_api.py` 的 POST payload 加：

```python
"rawStage": "高潮",
"stageConfirmState": {
    "pending": True,
    "pendingStage": "高潮",
    "pendingSince": "11:00",
    "confirmSlots": 2,
    "historyStatus": "complete",
},
"diagnostics": ["stage_confirm_legacy_fallback:1"],
```

并断言写库文档逐字段相等。再加旧 payload 测试，断言未提供字段时不伪造 `stageConfirmState`。

- [ ] **Step 2: 运行 API 测试并确认 RED**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_sentiment_api.py -q
```

Expected: 新字段被 Pydantic 丢弃。

- [ ] **Step 3: 扩展 Pydantic 合同并提升缓存版本**

在 `HotListSentimentPayload` 增加：

```python
    rawStage: str | None = None
    stageConfirmState: dict[str, Any] | None = None
    diagnostics: list[str] = Field(default_factory=list)
```

写入改为：

```python
get_hotlist_sentiment_service(...).upsert(payload.model_dump(exclude_none=True))
```

将 series 与 slots cache version 同时从 `v1` 升为 `v2`，并提取共享常量：

```python
_HOTLIST_SENTIMENT_CACHE_VERSION = "v2"
```

- [ ] **Step 4: 锁定缓存命中透传**

series/slots API 测试分别预置含三字段的缓存响应，断言命中时 `rawStage`、`stageConfirmState.pendingSince` 和 `cache.hit=True` 均保留；未命中 MongoDB 路径同样断言三字段。

- [ ] **Step 5: 运行 API 测试并确认 GREEN**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_hotlist_sentiment_api.py tests\test_hotlist_sentiment_series_api.py tests\test_hotlist_sentiment_slots_api.py -q
```

Expected: exit code 0。

- [ ] **Step 6: 提交本任务文件**

```powershell
git add quant-board/backend/api/hotlist_routes.py quant-board/tests/test_hotlist_sentiment_api.py quant-board/tests/test_hotlist_sentiment_series_api.py quant-board/tests/test_hotlist_sentiment_slots_api.py
git commit -m "feat(hotlist-sentiment): preserve confirmation fields through APIs"
```

---

### Task 6: 前端双轨展示

**Required skill at execution:** `frontend-design`，随后使用项目级 `skills/playwright-cli/SKILL.md` 与 `skills/e2e-verification/SKILL.md` 做真实浏览器验收。

**Files:**

- Modify: `src/types/hotlistSentiment.ts`
- Modify: `src/components/panels/DragonBreathPanel.vue`
- Test: `src/components/panels/__tests__/DragonBreathPanel.test.ts`

- [ ] **Step 1: 增加类型合同**

在 `HotListSentimentResult` 与 `HotListSentimentDayDoc` 增加：

```typescript
rawStage?: UnifiedEmotionStage
stageConfirmState?: {
  pending: boolean
  pendingStage?: UnifiedEmotionStage | null
  pendingSince?: string | null
  confirmSlots: number
  historyStatus: 'complete' | 'empty' | 'legacy_fallback' | 'unavailable'
}
```

注释明确：`stage` 是确认值；`summary/riskLevel/confidence/signals/warnings` 是当前截面证据。

- [ ] **Step 2: 写结构与兼容失败测试**

在 `DragonBreathPanel.test.ts` 增加源码合同断言：

```typescript
expect(source).toContain('rawStage || doc.stage')
expect(source).toContain('confirmedStage')
expect(source).toContain('pendingSince')
expect(source).toContain('当前截面证据')
expect(source).toContain('截面置信')
expect(source).toContain('stage-confirm-pending')
```

现有旧文档兼容测试继续要求可选链，不允许直接访问 `rawStage` 或 `stageConfirmState.pendingStage`。

- [ ] **Step 3: 运行测试并确认 RED**

```powershell
Set-Location D:\dragon-board
pnpm vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts
```

Expected: 新展示合同断言失败。

- [ ] **Step 4: 修改顶部阶段卡片**

新增 computed：

```typescript
const hotListStagePending = computed(() => {
  const doc = hotListSentiment.value
  const state = doc?.stageConfirmState
  if (!state?.pending || !doc?.rawStage) return null
  return {
    rawStage: doc.rawStage,
    pendingStage: state.pendingStage || doc.rawStage,
    pendingSince: state.pendingSince || '--',
    confirmSlots: state.confirmSlots,
  }
})
```

顶部继续以 `hotListStage` 展示确认值；把置信文本改为 `截面置信`，摘要前增加“当前截面证据：”。pending 角标 title 必须包含原始阶段、起始槽和阈值。

- [ ] **Step 5: 修改日内轨迹为原始主值 + 确认辅值**

组装行时：

```typescript
const rawStage = getDisplayEmotionStage(doc.rawStage || doc.stage)
const confirmedStage = getDisplayEmotionStage(doc.stage)
return {
  // 其余字段保持不变
  stage: rawStage.name,
  stageClass: rawStage.classKey,
  confirmedStage: confirmedStage.name,
  confirmedStageClass: confirmedStage.classKey,
  stagePending: Boolean(doc.stageConfirmState?.pending),
}
```

轨迹模板主标签写“截面 {{ item.stage }}”；当 `item.confirmedStage !== item.stage` 时增加“确认 {{ item.confirmedStage }}”。不要用空字符串或默认“启动”伪装缺失；旧文档通过 `rawStage || stage` 兼容。

- [ ] **Step 6: 增加 pending 样式并运行测试/类型检查**

样式沿用现有金融工作台颜色层级，使用边框和文本区分，不只依赖颜色。

```powershell
Set-Location D:\dragon-board
pnpm vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 两条命令 exit code 0。

- [ ] **Step 7: 提交本任务文件**

```powershell
git add src/types/hotlistSentiment.ts src/components/panels/DragonBreathPanel.vue src/components/panels/__tests__/DragonBreathPanel.test.ts
git commit -m "feat(frontend): show raw and confirmed emotion stages"
```

---

### Task 7: 回放证据与正式文档

**Files:**

- Modify: `quant-board/operations/replay_stage_confirm.py`
- Modify: `quant-board/docs/database-migration-plan.md`
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`
- Modify: `docs/热榜情绪分析器方案.md`
- Modify: `docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md`

- [ ] **Step 1: 修订回放输入合同**

查询投影同时读取 `rawStage` 与 `stage`，序列取值必须是：

```python
raw_stage = str(doc.get("rawStage") or doc.get("stage") or "").strip()
used_legacy_fallback = not bool(doc.get("rawStage")) and bool(doc.get("stage"))
```

排除两类 EOD，并按交易日/槽位排序。脚本输出：raw switches、confirmed switches、reduction、confirmed transition evidence、average/max delay、absorbed singletons、legacy fallback count、invalid slot count。另运行 `confirm_slots=1` 并逐槽断言与 raw 序列相同。

- [ ] **Step 2: 增加回放脚本测试**

将统计纯函数提取为可传入文档列表的函数；测试至少覆盖：

- 新文档优先 `rawStage`，即使 `stage` 已平滑；
- 旧文档回退 `stage` 并增加 fallback 计数；
- 日级 `_id` 的旧 EOD 与 `slotTime=EOD` 都被排除；
- 阈值 2 的最大延迟为一个可观察槽；
- 阈值 1 逐槽等价。

- [ ] **Step 3: 运行回放并更新报告**

```powershell
Set-Location D:\dragon-board\quant-board
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe operations\replay_stage_confirm.py
Remove-Item Env:PYTHONPATH
```

Expected: 报告明确列出实际交易日数。若仍为 14 日，保留 14 日边界；不得写成 110 天。61.5% 只作为历史基线，最终数字以新脚本输出为准。

- [ ] **Step 4: 同步正式文档**

各文档统一说明：

- `rawStage` 是截面事实，`stage` 是确认投影；
- `stageConfirmState` 字段与 historyStatus 枚举；
- EOD 同帧只计一次、历史重算按当前槽截断；
- ingest/series/slots 合同；
- `HOTLIST_STAGE_CONFIRM_SLOTS=1` 的回退语义；
- 历史重算与缓存版本变化。

- [ ] **Step 5: 文档一致性扫描**

```powershell
Set-Location D:\dragon-board
$docPaths = @(
  'docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md',
  'docs/superpowers/plans/2026-09-24-emotion-stage-multiframe-confirm.md',
  'quant-board/docs/database-migration-plan.md', 'quant-board/docs/architecture.md',
  'quant-board/docs/api-cli.md', 'quant-board/docs/AI_COLLABORATION.md', 'docs/热榜情绪分析器方案.md'
)
$required = @('rawStage', 'stageConfirmState', 'pendingSince', 'historyStatus',
  'HOTLIST_STAGE_CONFIRM_SLOTS', 'EOD', 'ingest', 'cache', 'Playwright')
$missing = foreach ($name in $required) {
  if (-not (Select-String -Path $docPaths -Pattern $name -SimpleMatch -Quiet)) { $name }
}
if ($missing) { throw ('文档合同缺失: ' + ($missing -join ', ')) }
Write-Output 'document consistency PASS'
```

Expected: 输出 `document consistency PASS`；字段合同关键字在两份文档中均可定位。

- [ ] **Step 6: 提交本任务文件**

只暂存上述明确文档、脚本和对应测试后提交。

---

### Task 8: 全量验证、迁移演练与真实浏览器验收

**Required skill at execution:** `verification-before-completion`；浏览器阶段由主代理读取并执行 `skills/playwright-cli/SKILL.md` 和 `skills/e2e-verification/SKILL.md`。

- [ ] **Step 1: 后端专项测试**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest `
  tests\test_hotlist_stage_confirm.py `
  tests\test_hotlist_sentiment_compute.py `
  tests\test_hotlist_sentiment_backfill.py `
  tests\test_hotlist_sentiment_backfill_slots.py `
  tests\test_hotlist_sentiment_after_market.py `
  tests\test_hotlist_sentiment_intraday.py `
  tests\test_hotlist_sentiment_recompute.py `
  tests\test_hotlist_sentiment_api.py `
  tests\test_hotlist_sentiment_series_api.py `
  tests\test_hotlist_sentiment_slots_api.py `
  tests\test_hotlist_sentiment_collector_hook.py `
  tests\test_hotlist_sentiment_asof_provider.py `
  tests\test_snapshot_collector_post_persist.py -q
```

Expected: exit code 0，无失败。

- [ ] **Step 2: QuantBoard 后端全量**

```powershell
Set-Location D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0。不得预先豁免已知失败；若环境失败，记录完整命令、退出码和失败项，不能声称全量通过。

- [ ] **Step 3: 根前端测试与类型检查**

```powershell
Set-Location D:\dragon-board
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 两条命令 exit code 0。

- [ ] **Step 4: dry-run 历史重算**

使用现有 hotlist backfill/recompute 入口对至少一个包含多次翻转的交易日 dry-run，输出每槽 `slotTime/rawStage/stage/stageConfirmState`。断言：

- `10:00` 的结果不受已存在 `11:00` 影响；
- EOD 与锚定槽相同；
- 所有原始槽仍可查询；
- 单槽异常不会使其他槽消失。

- [ ] **Step 5: 应用迁移时按快照槽升序重算**

迁移目标槽必须来自 `snapshot_frames`，不能只枚举现有 `hotlist_sentiment`，否则缺失槽永远不会补齐。每个交易日按 `slotTime` 升序调用 `compute_and_upsert_for_slot`，最后重算 EOD。写入前记录日期/槽位数；单槽失败记录错误并继续，完成后输出失败清单。

- [ ] **Step 6: API 验收**

```powershell
$series = Invoke-RestMethod 'http://127.0.0.1:8000/api/hotlist-sentiment/series?dataset_id=dragonboard_live&days=1'
$slots = Invoke-RestMethod 'http://127.0.0.1:8000/api/hotlist-sentiment/slots?dataset_id=dragonboard_live'
$series.items[-1] | Select-Object stage,rawStage,stageConfirmState,diagnostics
$slots.items | Select-Object slotTime,stage,rawStage,stageConfirmState
```

Expected: 新字段存在；原始槽位没有因质量状态而消失；缓存命中再次请求仍返回同样字段。

- [ ] **Step 7: Playwright 真实浏览器验收**

主代理启动或复用明确属于 `D:\dragon-board` 的本地服务，检查 DragonBreath 热榜情绪视图：

1. 顶部显示确认阶段。
2. pending 时显示原始阶段、起始槽与确认阈值。
3. 摘要和置信度明确标注为当前截面。
4. 日内轨迹逐槽显示 rawStage，确认值不同时同时显示确认阶段。
5. 桌面和移动视口无横向溢出或遮挡。
6. 浏览器控制台无新增错误。

保存必要截图到测试产物目录，不提交截图到仓库。验收由主代理完成。

- [ ] **Step 8: 最终 diff 与工作区核对**

```powershell
Set-Location D:\dragon-board
git diff --check
git diff --stat
git status --short
```

人工确认没有覆盖用户已有修改、没有运行产物进入提交范围，并分别报告主工作区状态；若执行时使用隔离 worktree，还必须单独报告该 worktree 的 `git status --short`。

---

## Self-Review 记录

1. **Spec 覆盖**：因果时间上界与乱序重算由 Task 2/4；旧 EOD 双排除由 Task 2；三字段与 EOD 同帧由 Task 3；四写口由 Task 4；ingest/cache 由 Task 5；双轨 UI 与截面语义由 Task 6；回放证据和正式文档由 Task 7；全量/真实浏览器验收由 Task 8。
2. **Fail-visible**：历史读取失败、legacy fallback、非法配置和非标准槽均返回已有数据并附诊断；`points` 与 `rawStagePoints` 独立降级；只有没有当前原始记录时才允许报告无数据。
3. **类型一致性**：纯函数输入为 `Sequence[tuple[str, str]]`；收集层键为 `rawStagePoints`；文档字段统一为 `rawStage`、`stageConfirmState.pendingStage/pendingSince/confirmSlots/historyStatus`；TS 使用相同命名。
4. **测试独立性**：关键集成测试写死预期阶段，不调用被测状态机生成期望值；覆盖真实 `A→B→B`、未来槽污染、乱序回填和 EOD 同帧。
5. **回退**：阈值 1 逐槽等价；旧文档通过 `rawStage ?? stage` 读取；不删除历史字段或文档。
