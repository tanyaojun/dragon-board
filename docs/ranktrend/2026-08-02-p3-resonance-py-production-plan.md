# RankTrend P3 实施计划：resonance/jump 收敛 Python + TS 零算法收尾

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 P2 留在 TS 的 live-only 观察计算（resonance、观察面板横截面）收敛到 Python，TS 实现零算法（只留展示投影、持仓状态/通知与"分析不可用"）；jump 判定保留前端应用层但事件输入全部来自 Python。

**Architecture:** Python `backend/analysis/ranktrend.py` 新增 `analyze_rank_resonance`（移植 TS resonanceAnalyzer）；analyze API 每帧计算横截面基准（`marketMedianShortChange`）并输出每股 `rankTrend.resonance`。TS 删除 `resonanceAnalyzer.ts` 与 `applyResonanceFinals`/横截面计算，共振轨/主表共振列读 Python 输出。

**Tech Stack:** FastAPI（Python）、MongoDB、Vue3/TypeScript、Vitest、pytest。

**设计文档：** `docs/ranktrend/2026-08-02-regime-hotlist-pool-py-production-design.md` §12

---

## 进度状态（2026-08-02）

| Phase | 状态 |
| --- | --- |
| Phase A Python resonance 移植 + analyze API 输出 | 进行中 |
| Phase B TS 消费切换与删除 | 待做 |
| Phase C 收尾（golden 确认、浏览器验收） | 待做 |

## Phase A：Python resonance 移植 + analyze API 输出

### Task A1：移植 analyze_rank_resonance

**Files:**
- Create: `quant-board/backend/tests/test_resonance_analyzer.py`
- Modify: `quant-board/backend/analysis/ranktrend.py`

- [ ] **Step 1: 写失败测试（对齐 TS resonanceAnalyzer 合同）**

```python
from backend.analysis.ranktrend import analyze_rank_resonance


def _jump(direction="hold", events=None):
    return {"direction": direction, "event": "jump" if events else "none", "events": events or []}


def test_established_buy_resonance():
    percentiles = [20, 22, 25, 28, 32, 37, 43, 50, 58, 67]
    result = analyze_rank_resonance({
        "percentiles": percentiles,
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 5.0,
        "marketSampleCount": 200,
        "jump": _jump("buy", [{"index": 7, "direction": "surge", "magnitude": 20}]),
    })
    assert result["status"] == "ok"
    assert result["direction"] == "buy"
    assert result["historyState"] == "established"
    assert result["marketMedianShortChange"] == 5.0


def test_insufficient_when_market_sample_low():
    result = analyze_rank_resonance({
        "percentiles": [20, 22, 25, 28, 32, 37, 43, 50, 58, 67],
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 5.0,
        "marketSampleCount": 5,
        "jump": _jump(),
    })
    assert result["status"] == "insufficient"
    assert result["score"] == 0


def test_new_entry_path():
    result = analyze_rank_resonance({
        "percentiles": [95.2],
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 1.0,
        "marketSampleCount": 200,
        "jump": _jump("buy", [{"index": 0, "direction": "surge", "magnitude": 10}]),
        "entry": {"isNew": True, "currentAttentionPercentile": 95.2},
    })
    assert result["status"] == "ok"
    assert result["historyState"] == "new_entry"
    assert result["direction"] == "buy"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_resonance_analyzer.py -q`
Expected: FAIL——`ImportError: cannot import name 'analyze_rank_resonance'`。

- [ ] **Step 3: 实现（移植 TS resonanceAnalyzer）**

在 `ranktrend.py` 新增：

```python
RESONANCE_SHORT_WINDOW_BARS = 3
RESONANCE_MID_WINDOW_BARS = 8
RESONANCE_PATH_WINDOW_BARS = 8
RESONANCE_MIN_SERIES_POINTS = RESONANCE_MID_WINDOW_BARS + 1
RESONANCE_MIN_MARKET_SAMPLE_COUNT = 20


def _positive(value: float) -> float:
    return max(0.0, value)


def _resonance_label(score: float) -> str:
    if score >= 85:
        return "非常强"
    if score >= 67:
        return "强"
    if score >= 50:
        return "中等"
    if score >= 27:
        return "较弱"
    return "非常弱"


def _resonance_insufficient(reason: str, market_median_short_change: float) -> dict[str, Any]:
    return {
        "status": "insufficient",
        "direction": "hold",
        "score": 0,
        "label": "样本不足",
        "relativeMomentum": 0,
        "acceleration": 0,
        "persistence": 0,
        "jumpFreshness": 0,
        "reversalPenalty": 0,
        "historyState": "established",
        "marketMedianShortChange": market_median_short_change,
        "reasons": [reason],
    }


def analyze_rank_resonance(input: dict[str, Any]) -> dict[str, Any]:
    """共振强度（移植 TS resonanceAnalyzer）：相对动量/加速度/持续性/Jump 新鲜度/反转惩罚。"""
    percentiles = [float(p) for p in (input.get("percentiles") or [])]
    market_median_short_change = float(input.get("marketMedianShortChange") or 0)
    market_sample_count = int(input.get("marketSampleCount") or 0)
    jump = input.get("jump") or {}
    entry = input.get("entry") or {}
    sample_quality = input.get("sampleQuality") or {}
    is_new_entry = entry.get("isNew") is True
    current_attention_percentile = float(entry.get("currentAttentionPercentile") or 0)

    if sample_quality.get("timelineValid") is False:
        return _resonance_insufficient("快照时间轴不完整", market_median_short_change)
    if is_new_entry:
        if not math.isfinite(current_attention_percentile):
            return _resonance_insufficient("新入榜关注度无效", market_median_short_change)
        if not math.isfinite(market_median_short_change) or market_sample_count < RESONANCE_MIN_MARKET_SAMPLE_COUNT:
            return _resonance_insufficient("横截面有效样本不足", market_median_short_change)
        jump_events = jump.get("events") or []
        jump_freshness = 1.0 if jump_events else 0.0
        entry_strength = clamp((current_attention_percentile - 50) / 25, 0, 1)
        score = round(100 * clamp(0.7 * entry_strength + 0.3 * jump_freshness, 0, 1))
        return {
            "status": "ok",
            "direction": "buy" if entry_strength > 0 else "hold",
            "score": score,
            "label": _resonance_label(score),
            "relativeMomentum": entry_strength,
            "acceleration": 0,
            "persistence": 0,
            "jumpFreshness": jump_freshness,
            "reversalPenalty": 0,
            "historyState": "new_entry",
            "marketMedianShortChange": market_median_short_change,
            "reasons": [f"新入榜关注度 {round(current_attention_percentile)}"],
        }
    if len(percentiles) < RESONANCE_MIN_SERIES_POINTS or any(not math.isfinite(p) for p in percentiles):
        return _resonance_insufficient("排名序列不足或无效", market_median_short_change)
    if sample_quality.get("status") == "insufficient":
        return _resonance_insufficient("快照样本不足", market_median_short_change)
    if not math.isfinite(market_median_short_change) or market_sample_count < RESONANCE_MIN_MARKET_SAMPLE_COUNT:
        return _resonance_insufficient("横截面有效样本不足", market_median_short_change)

    last_index = len(percentiles) - 1
    short_start_index = last_index - RESONANCE_SHORT_WINDOW_BARS
    mid_start_index = last_index - RESONANCE_MID_WINDOW_BARS
    short_bars = last_index - short_start_index
    mid_bars = last_index - mid_start_index
    short_change = percentiles[last_index] - percentiles[short_start_index]
    mid_change = percentiles[last_index] - percentiles[mid_start_index]
    relative_momentum = clamp((short_change - market_median_short_change) / 15, -1, 1)
    acceleration = clamp((short_change - (mid_change * short_bars) / mid_bars) / 15, -1, 1)

    path_percentiles = percentiles[-(RESONANCE_PATH_WINDOW_BARS + 1):]
    changes = [path_percentiles[i + 1] - path_percentiles[i] for i in range(len(path_percentiles) - 1)]
    path_direction = 1 if (short_change or mid_change) > 0 else -1 if (short_change or mid_change) < 0 else 0
    directional_changes = [
        value for value in changes
        if path_direction != 0 and (1 if value > 0 else -1 if value < 0 else 0) == path_direction
    ]
    persistence = len(directional_changes) / len(changes) if changes else 0
    if len(changes) > 1:
        direction_switch_rate = sum(
            1 for i in range(1, len(changes))
            if math.copysign(1, changes[i]) != 0 and math.copysign(1, changes[i - 1]) != 0
            and math.copysign(1, changes[i]) != math.copysign(1, changes[i - 1])
        ) / (len(changes) - 1)
    else:
        direction_switch_rate = 0
    recent_peak = max(path_percentiles)
    percentile_drawdown = max(0, recent_peak - percentiles[last_index])
    reversal_penalty = clamp(0.6 * direction_switch_rate + 0.4 * percentile_drawdown / 20, 0, 1)

    jump_events = jump.get("events") or []
    latest_event = jump_events[-1] if jump_events else None
    jump_freshness = math.exp(-(last_index - int(latest_event["index"])) / 3) if latest_event else 0
    direction_score = relative_momentum + acceleration + 0.2 * path_direction * persistence
    base_direction = "buy" if direction_score > 0.1 else "sell" if direction_score < -0.1 else "hold"
    has_reverse_jump = (
        (base_direction == "buy" and jump.get("direction") == "sell")
        or (base_direction == "sell" and jump.get("direction") == "buy")
    )
    direction = jump.get("direction") if jump.get("event") == "jump" and has_reverse_jump else base_direction

    directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
    directional_acceleration = -acceleration if direction == "sell" else acceleration
    raw_score = (
        0.35 * _positive(directional_momentum)
        + 0.25 * _positive(directional_acceleration)
        + 0.2 * persistence
        + 0.2 * jump_freshness
        - 0.2 * reversal_penalty
    )
    score = round(100 * clamp(raw_score, 0, 1))
    return {
        "status": "ok",
        "direction": direction,
        "score": score,
        "label": _resonance_label(score),
        "relativeMomentum": round(relative_momentum, 6),
        "acceleration": round(acceleration, 6),
        "persistence": round(persistence, 6),
        "jumpFreshness": round(jump_freshness, 6),
        "reversalPenalty": round(reversal_penalty, 6),
        "historyState": "established",
        "marketMedianShortChange": market_median_short_change,
        "reasons": [
            f"相对动量 {round(relative_momentum * 100)}",
            f"加速度 {round(acceleration * 100)}",
            f"路径持续性 {round(persistence * 100)}%",
        ],
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_resonance_analyzer.py -q`
Expected: PASS（3 个用例）。

### Task A2：analyze API 输出横截面基准与每股 resonance

**Files:**
- Modify: `quant-board/backend/api/ranktrend_routes.py`（`_analyze_frames`）
- Test: `quant-board/backend/tests/test_ranktrend_analyze_api.py`

- [ ] **Step 1: 写失败测试（resonance 与 marketMedianShortChange 输出）**

在 `test_ranktrend_analyze_api.py` 追加：

```python
def test_analyze_returns_resonance_and_market_median(monkeypatch):
    frames = [{
        "tradingDate": f"2026-08-0{day}",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": day,
        "rows": [
            {"code": "002279", "rank": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            {"code": "000001", "rank": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    } for day in range(1, 5)]
    monkeypatch.setattr("backend.data.repository_factory.get_runtime_mongodb_database", lambda: object())
    monkeypatch.setattr("backend.main.create_repository", lambda db, enable_backup=True: FakeRepo(frames))
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-04 14:00"],
    })
    assert response.status_code == 200
    frame = response.json()["frames"][0]
    assert "marketMedianShortChange" in frame
    assert frame["stocks"][0]["analysis"]["resonance"]["status"] in ("ok", "insufficient")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_ranktrend_analyze_api.py -q`
Expected: FAIL——响应无 `marketMedianShortChange`/`resonance` 字段。

- [ ] **Step 3: 实现横截面基准与 resonance 注入**

`_analyze_frames` 改为：先按帧收集每只股票百分位序列，计算每帧横截面基准，再为每股注入 resonance：

```python
def _percentile(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _frame_market_median(frames: list[dict[str, Any]], index: int) -> tuple[float | None, int]:
    """当前帧与前 3 个市场帧公共股票的短周期百分位变化中位数（横截面基准）。"""
    start = max(0, index - 3)
    window = frames[start:index + 1]
    if len(window) < 4:
        return None, 0
    current = {str(s.get("code")): s for s in window[-1].get("stocks", []) if s.get("rank", 0) > 0}
    first = {str(s.get("code")): s for s in window[0].get("stocks", []) if s.get("rank", 0) > 0}
    changes: list[float] = []
    for code, stock in current.items():
        first_stock = first.get(code)
        if not first_stock:
            continue
        current_pct = _percentile(float(stock.get("rank") or 0), len(window[-1].get("stocks", [])))
        first_pct = _percentile(float(first_stock.get("rank") or 0), len(window[0].get("stocks", [])))
        changes.append(current_pct - first_pct)
    if len(changes) < 20:
        return None, len(changes)
    return _median(changes), len(changes)
```

`_analyze_frames` 在每股循环中，用 `signal.get("rankTrend")` 的序列重建百分位并调用 `analyze_rank_resonance`：

```python
def _analyze_frames(engine: RankTrendPythonEngine, frames: list[dict[str, Any]], codes: list[str]) -> list[dict[str, Any]]:
    signals_by_frame = engine.replay(frames, warmup_count=1)
    by_key: dict[str, list[dict[str, Any]]] = {}
    for signal in signals_by_frame:
        key = f"{signal.get('tradingDate')} {signal.get('slotTime')}".strip()
        by_key.setdefault(key, []).append(signal)
    # 每股跨帧百分位序列（用于 resonance 横截面与个股序列）
    series_by_code: dict[str, list[float]] = {}
    for frame in frames:
        total = len(frame.get("stocks", []))
        for stock in frame.get("stocks", []):
            code = str(stock.get("code") or "")
            rank = float(stock.get("rank") or 0)
            if code and rank > 0 and total > 0:
                series_by_code.setdefault(code, []).append(_percentile(rank, total))
    output: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        key = f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip()
        regime = market_regime(frame)
        market_median, market_sample_count = _frame_market_median(frames, index)
        stocks_out: list[dict[str, Any]] = []
        for signal in by_key.get(key, []):
            code = str(signal.get("code") or "")
            if codes and code not in codes:
                continue
            analysis = signal.get("rankTrend") or {}
            percentiles = series_by_code.get(code, [])
            jump = analysis.get("jump") or {}
            sample_quality = (analysis.get("meta") or {}).get("sampleQuality") or {}
            resonance = analyze_rank_resonance({
                "percentiles": percentiles,
                "sampleQuality": {
                    "status": sample_quality.get("status") or "insufficient",
                    "timelineValid": sample_quality.get("timelineValid", True),
                },
                "marketMedianShortChange": market_median if market_median is not None else float("nan"),
                "marketSampleCount": market_sample_count,
                "jump": {
                    "direction": jump.get("direction") or "hold",
                    "event": jump.get("event") or "none",
                    "events": jump.get("events") or [],
                },
                "entry": {"isNew": len(percentiles) == 1, "currentAttentionPercentile": percentiles[-1] if percentiles else 0},
            })
            analysis["resonance"] = resonance
            stocks_out.append({"code": code, "analysis": analysis})
        output.append({
            "frameKey": key,
            "regime": regime,
            "marketMedianShortChange": market_median,
            "marketSampleCount": market_sample_count,
            "totalCount": len(frame.get("stocks", [])),
            "stocks": stocks_out,
        })
    return output
```

- [ ] **Step 4: 运行确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_ranktrend_analyze_api.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

Run:
```powershell
git -C D:\dragon-board add quant-board/backend/analysis/ranktrend.py quant-board/backend/api/ranktrend_routes.py quant-board/backend/tests/test_resonance_analyzer.py quant-board/backend/tests/test_ranktrend_analyze_api.py
git -C D:\dragon-board commit -m "feat: Python 移植 resonance 并输出横截面基准"
```

## Phase B：TS 消费切换与删除

### Task B1：RankTrendSignalService 消费 Python resonance

**Files:**
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
- Test: `src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`

- [ ] **Step 1: 写失败测试（resonance 直接来自 Python，不再本地计算）**

```ts
it('keeps py golden resonance and only overrides decision.final display', async () => {
  const stock = {
    code: '002279',
    rankTrend: {
      meta: { code: '002279', analysisSource: 'py_golden' },
      resonance: { status: 'ok', direction: 'buy', score: 88 },
      decision: { final: { signal: 'hold', confidence: 50 } },
    },
  }
  rankTrendSignalService['applyResonanceFinals']([stock], new Set(['002279']))
  expect(stock.rankTrend.resonance.score).toBe(88)
  expect(stock.rankTrend.decision.final.signal).toBe('buy')
  expect(stock.finalSignal).toBe('buy')
})
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts -t "py golden resonance" --reporter=basic`
Expected: FAIL（当前会本地重算覆盖 resonance）。

- [ ] **Step 3: 改造 applyResonanceFinals**

删除本地横截面/`analyzeRankResonance` 计算：`applyResonanceFinals` 只做展示投影——
用 `stock.rankTrend.resonance` 覆盖 `decision.final` 与 `finalSignal/finalConfidence`
（resonance 由 Python 输出，`insufficient` 时 final 为 `hold/0`）。

- [ ] **Step 4: 运行确认通过 + 相关测试适配**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts --reporter=basic`
Expected: PASS（适配依赖本地 resonance 计算的用例）。

### Task B2：观察面板删除本地横截面计算

**Files:**
- Modify: `src/services/rankTrend/RankTrendObservationService.ts`
- Test: `src/services/rankTrend/__tests__/RankTrendObservationService.test.ts`

- [ ] **Step 1: 写失败测试（resonance 轨读 Python 输出）**

断言观察服务不再调用本地横截面（mock 下 `marketMedianShortChange` 来自 analyze API 返回），
且 `resonance` 字段来自 Python 输出。

- [ ] **Step 2: 运行确认失败 → 实现 → 确认通过**

删除 `calculateMarketMedian/buildFrameCrossSections` 与横截面读取（`listSnapshotStockRows`
的 cross-section 调用），`marketMedianShortChange` 读 analyze API 的帧级输出；resonance 轨数据
来自 `analysis.resonance`。

### Task B3：删除 resonanceAnalyzer.ts 与测试清理

**Files:**
- Delete: `src/services/rankTrend/resonanceAnalyzer.ts`
- Delete: `src/services/rankTrend/__tests__/resonanceAnalyzer.test.ts`

- [ ] **Step 1: 确认无业务引用**

Run: `rg -n "resonanceAnalyzer|analyzeRankResonance" src --glob '!**/__tests__/**'`
Expected: 无业务引用（Task B1/B2 已完成消费切换）。

- [ ] **Step 2: 删除文件**

Run: `git -C D:\dragon-board rm src/services/rankTrend/resonanceAnalyzer.ts src/services/rankTrend/__tests__/resonanceAnalyzer.test.ts`

### Task B4：全量验证

- [ ] **Step 1: 前端全量**

Run: `pnpm test --reporter=basic`；Expected: 全绿。

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；Expected: 退出码 0。

- [ ] **Step 2: 后端全量**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`；Expected: 全绿。

- [ ] **Step 3: Commit**

Run:
```powershell
git -C D:\dragon-board add -A src/services/rankTrend src/services/dataLoader/RankTrendSignalService.ts
git -C D:\dragon-board commit -m "refactor: TS 消费 Python resonance，删除本地横截面与 resonanceAnalyzer"
```

## Phase C：收尾

### Task C1：golden 方向完成态确认

- [ ] **Step 1: 更新设计/计划文档**

确认 `docs/ranktrend/2026-08-02-regime-hotlist-pool-py-production-plan.md` 的 P3 进度表、
设计文档 §12 标注"已实施"；`AGENTS.md`/golden 文档无需再改（P2 已反转）。

- [ ] **Step 2: Commit**

Run: `git -C D:\dragon-board add docs/ranktrend; git -C D:\dragon-board commit -m "docs: P3 完成态记录"`

### Task C2：浏览器验收（合并 Phase 8 待办）

- [ ] **Step 1: 启动服务并验收**

启动 Quant API（8000，已跑新代码）、proxy（3000）、前端 dev（5173）；验收主表共振列与
观察面板共振轨显示 Python 输出；离线场景显示"分析不可用"。

- [ ] **Step 2: 记录结果到 `docs/ranktrend/`**

## 自审记录

- 覆盖检查：设计 §12 各节均有对应 Task（resonance 移植→A1；analyze API 输出→A2；
  TS 消费/删除→B1/B2/B3；验证→B4；golden 确认→C1；浏览器→C2）。
- 类型一致性：`marketMedianShortChange`/`marketSampleCount` 帧级字段在 A2/B2 一致；
  `resonance` 字段合同（status/direction/score/label/六因子/reasons）A1 与 TS 原合同一致。
- 无占位符：实现步骤均给出代码；唯一待办（浏览器验收）有明确验收路径。
