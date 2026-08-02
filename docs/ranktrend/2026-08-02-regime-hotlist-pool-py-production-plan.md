# RankTrend regime 热榜池口径 + Python 单侧生产实施计划（P2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 RankTrend 市场环境 regime 改为热榜池五因子口径，并将整条 golden 链（technical/cycle/risk/decision/observation/strategy/executionStrategy/regime/jump）收敛到 Python 单侧生产，TS 前端只消费结果，实现 TS/Python golden 完全一致。

**Architecture:** Python 端在现有 `backend/analysis/ranktrend.py` golden 链上补齐 observation/executionStrategy 输出并重写 `market_regime()` 为五因子；新增 `POST /api/ranktrend/analyze` 批量分析 API，`GET /api/snapshots/frames` 每帧附带 regime。TS 端 `RankTrendAnalyzer`/`RankTrendSignalService`/`RankTrendObservationService` 改为消费 API 结果，删除本地 golden 链实现；后端不可用时显示"分析不可用"，不保留第二份实现。resonance/jump 应用层留 TS（live-only），P3 再迁。

**Tech Stack:** FastAPI（Python）、MongoDB repository、Redis 缓存、Vue3/TypeScript、Vitest、pytest。

**设计文档：** `docs/ranktrend/2026-08-02-regime-hotlist-pool-py-production-design.md`

---

## 全局约定

- Python 工作目录：`D:\dragon-board\quant-board`，测试命令：`.\.venv\Scripts\python.exe -m pytest backend/tests/<file> -q`。
- TS 工作目录：`D:\dragon-board`，RankTrend 验证：`pnpm test:ranktrend`、`pnpm typecheck:ranktrend`。
- 每个 Task 独立 commit，只 add 该 Task 涉及的文件；不把无关改动混入。
- regime 五因子权重为"基线 v1"，样本验证后冻结（见 Phase 8）；冻结前不改权重。
- 新代码必须符合现有代码风格：Python 保持模块清晰，TS 无分号单引号 printWidth 100。

## Phase 0：基线确认

### Task 0.1：确认改动前测试基线

**Files:** 无

- [ ] **Step 1: 运行 TS RankTrend 测试**

Run: `pnpm test:ranktrend --reporter=basic`
Expected: 24 个文件全部通过（当前 265 用例），记录退出码 0。

- [ ] **Step 2: 运行 QuantBoard 后端测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 现有测试全部通过，记录退出码 0 与失败数。

- [ ] **Step 3: 记录 git 基线**

Run: `git -C D:\dragon-board status --short`
Expected: 记录当前未提交文件清单（应有上一轮已确认的 `RankTrendObservationService.ts` 及其测试，如有其它用户改动则列出并避让）。

## Phase 1：Python regime 五因子

### Task 1.1：写 market_regime 五因子失败测试

**Files:**
- Create: `quant-board/backend/tests/test_market_regime.py`

- [ ] **Step 1: 创建测试文件**

```python
from backend.analysis.ranktrend import market_regime


def _frame(stocks, sentiment=None):
    return {
        "stocks": stocks,
        "marketContext": {
            "sentiment": sentiment or {"phaseName": "启动"},
        },
    }


def test_strong_pool_regime():
    frame = _frame(
        [
            {"change": 5.0, "volumeRatio": 1.6, "zlje": 100, "zljzb": 0.2},
            {"change": 10.0, "volumeRatio": 1.8, "zlje": 80, "zljzb": 0.1},
            {"change": -1.0, "volumeRatio": 0.9, "zlje": -20, "zljzb": -0.1},
            {"change": 3.0, "volumeRatio": 1.3, "zlje": 50, "zljzb": 0.05},
            {"change": 9.9, "volumeRatio": 2.0, "zlje": 120, "zljzb": 0.3},
        ],
        {"phaseName": "高潮期"},
    )
    result = market_regime(frame)
    assert result["state"] == "strong"
    assert any("池内上涨" in r for r in result["reasons"])
    assert any("池内涨停" in r for r in result["reasons"])


def test_weak_pool_regime_not_saved_by_full_market():
    # 全A 涨停数很高，但热榜池内部转弱：不能因为全A 给强环境
    frame = {
        "stocks": [
            {"change": -2.0, "volumeRatio": 0.8, "zlje": -10, "zljzb": -0.05},
            {"change": -3.0, "volumeRatio": 0.7, "zlje": -15, "zljzb": -0.08},
            {"change": -1.0, "volumeRatio": 0.9, "zlje": 0, "zljzb": 0.0},
            {"change": -4.0, "volumeRatio": 0.6, "zlje": -30, "zljzb": -0.2},
            {"change": 1.0, "volumeRatio": 1.0, "zlje": 5, "zljzb": 0.01},
        ],
        "marketContext": {
            "sentiment": {"phaseName": "退潮期"},
            "marketStats": {"ztCount": 120, "dtCount": 1, "upCount": 3000, "downCount": 1800, "totalAmo": 1.5e12},
        },
    }
    result = market_regime(frame)
    assert result["state"] in ("weak", "retreat")
    assert "涨停120" not in result["reasons"]


def test_pool_share_factors_are_used():
    frame = _frame(
        [
            {"change": 2.0, "volumeRatio": 1.5, "zlje": 100, "zljzb": 0.2},
            {"change": -1.0, "volumeRatio": 0.8, "zlje": -10, "zljzb": -0.1},
        ]
    )
    result = market_regime(frame)
    assert any("热榜资金正向" in r for r in result["reasons"])
    assert any("量能活跃" in r for r in result["reasons"])


def test_no_stocks_returns_neutral_with_reason():
    result = market_regime({"stocks": [], "marketContext": {}})
    assert result["state"] == "normal"
    assert result["score"] == 50
    assert result["reasons"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_market_regime.py -q`
Expected: FAIL——`assert "池内上涨" in reasons` 失败（现实现输出"涨停/跌停/涨跌扩散"等全A原因）。

### Task 1.2：实现五因子 market_regime

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend.py:830`（`market_regime` 函数整体替换）

- [ ] **Step 1: 替换 market_regime 实现**

```python
REGIME_STAGE_ADJUST = {"高潮": 8, "发酵": 5, "启动": 0, "退潮": -6, "冰点": -8}
REGIME_STRONG_SCORE = 70.0
REGIME_NORMAL_SCORE = 50.0
REGIME_WEAK_SCORE = 30.0
REGIME_LIMIT_UP_CHANGE = 9.8
REGIME_LIMIT_UP_BASE_SHARE = 0.08


def market_regime(frame: dict[str, Any]) -> dict[str, Any]:
    """热榜池口径五因子市场环境：池内上涨占比、涨停强度、量能活跃、资金正向、情绪阶段参考。

    全A 涨跌家数/成交额不再进入打分（分化行情下与热榜池赚钱效应脱节）。
    """
    context = frame.get("marketContext") or {}
    payload = context.get("payload") or {}
    sentiment = context.get("sentiment") or payload.get("sentiment") or {}
    stocks = [s for s in (frame.get("stocks") or []) if isinstance(s, dict)]
    pool_size = len(stocks)
    score = 50.0
    reasons: list[str] = []

    phase = str(sentiment.get("phaseName") or sentiment.get("phase") or "").strip()
    if phase.endswith("期"):
        phase = phase[:-1]
    if pool_size == 0:
        return {"state": "normal", "score": 50.0, "reasons": ["市场环境数据不足，按中性处理"]}

    up_count = sum(1 for s in stocks if float(s.get("change") or 0) > 0)
    up_share = up_count / pool_size
    score += clamp((up_share - 0.5) * 40, -20, 20)
    reasons.append(f"池内上涨{up_share * 100:.0f}%")

    limit_count = sum(1 for s in stocks if float(s.get("change") or 0) >= REGIME_LIMIT_UP_CHANGE)
    limit_share = limit_count / pool_size
    score += clamp((limit_share - REGIME_LIMIT_UP_BASE_SHARE) * 80, -15, 25)
    reasons.append(f"池内涨停{limit_share * 100:.0f}%")

    if any(s.get("volumeRatio") is not None for s in stocks):
        active_share = sum(1 for s in stocks if float(s.get("volumeRatio") or 0) >= 1.2) / pool_size
        score += clamp((active_share - 0.35) * 10, -5, 7)
        reasons.append(f"量能活跃{active_share * 100:.0f}%")
    if any(s.get("zlje") is not None for s in stocks):
        money_share = sum(1 for s in stocks if float(s.get("zlje") or 0) > 0) / pool_size
        score += clamp((money_share - 0.5) * 20, -10, 10)
        reasons.append(f"热榜资金正向{money_share * 100:.0f}%")

    if phase:
        score += REGIME_STAGE_ADJUST.get(phase, 0)
        reasons.append(f"情绪阶段{phase}")

    score = clamp(score, 0, 100)
    state = (
        "strong" if score >= REGIME_STRONG_SCORE
        else "normal" if score >= REGIME_NORMAL_SCORE
        else "weak" if score >= REGIME_WEAK_SCORE
        else "retreat"
    )
    return {"state": state, "score": round(score, 1), "reasons": reasons}
```

- [ ] **Step 2: 运行测试确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_market_regime.py -q`
Expected: PASS（4 个用例）。

- [ ] **Step 3: 确认现有关联测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿。若既有测试断言旧全A regime 输出，更新该断言为五因子输出（属于本 Task 范围）。

- [ ] **Step 4: Commit**

Run:
```powershell
git -C D:\dragon-board add quant-board/backend/analysis/ranktrend.py quant-board/backend/tests/test_market_regime.py
git -C D:\dragon-board commit -m "feat: RankTrend regime 改为热榜池五因子口径"
```

## Phase 2：Python observation / executionStrategy 补齐

### Task 2.1：移植 observation 组合器

**Files:**
- Create: `quant-board/backend/tests/test_observation_scores.py`
- Modify: `quant-board/backend/analysis/ranktrend.py`（新增 `compose_observation_scores`，放在 `compose_decision` 之后）

- [ ] **Step 1: 写失败测试**

```python
from backend.analysis.ranktrend import compose_observation_scores


def test_lifecycle_opportunity_weights():
    result = compose_observation_scores({
        "technical": {"momentumProfile": {"short": 15, "mid": 15, "acceleration": 8}},
        "cycle": {
            "stage": "expansion",
            "metrics": {"rankPathCommitment": 1.0},
            "decision": {"action": "allow", "reasons": []},
        },
        "risk": {"pressure": 0.0},
        "decision": {"base": {"signal": "buy", "combinedScore": 0.6}},
    })
    assert result["lifecycle"]["stage"] == "expansion"
    assert result["lifecycle"]["score"] == 100
    assert result["lifecycle"]["veto"] is False
    assert result["rankTrend"]["direction"] == "buy"
    assert result["rankTrend"]["score"] == 60


def test_veto_keeps_score_and_marks_reason():
    result = compose_observation_scores({
        "technical": {"momentumProfile": {"short": 0, "mid": 0, "acceleration": 0}},
        "cycle": {
            "stage": "crowded",
            "metrics": {"rankPathCommitment": 0.5},
            "decision": {"action": "veto", "reasons": ["生命周期进入反转路径"]},
        },
        "risk": {"pressure": 0.5},
        "decision": {"base": {"signal": "hold", "combinedScore": 0}},
    })
    assert result["lifecycle"]["veto"] is True
    assert result["lifecycle"]["reasons"] == ["生命周期进入反转路径"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_observation_scores.py -q`
Expected: FAIL——`ImportError: cannot import name 'compose_observation_scores'`。

- [ ] **Step 3: 实现（对齐 TS observationScoreComposer）**

```python
STAGE_FITNESS = {"expansion": 1.0, "ignition": 0.8, "crowded": 0.35, "cooling": 0.2, "reversal": 0.0}


def compose_observation_scores(input: dict[str, Any]) -> dict[str, Any]:
    momentum = input["technical"]["momentumProfile"]
    cycle = input["cycle"]
    risk = input["risk"]
    base = input["decision"]["base"]
    signed_score = clamp(float(base.get("combinedScore") or 0), -1, 1)
    momentum_confirmation = (
        0.3 * clamp(float(momentum.get("short") or 0) / 15, 0, 1)
        + 0.45 * clamp(float(momentum.get("mid") or 0) / 15, 0, 1)
        + 0.25 * clamp(float(momentum.get("acceleration") or 0) / 8, 0, 1)
    )
    factors = {
        "stageFitness": STAGE_FITNESS.get(str(cycle["stage"]), 0.0),
        "pathCommitment": clamp(float(cycle.get("metrics", {}).get("rankPathCommitment") or 0), 0, 1),
        "momentumConfirmation": clamp(momentum_confirmation, 0, 1),
        "riskSafety": 1 - clamp(float(risk.get("pressure") or 0), 0, 1),
    }
    lifecycle_score = (
        0.35 * factors["stageFitness"]
        + 0.25 * factors["pathCommitment"]
        + 0.2 * factors["momentumConfirmation"]
        + 0.2 * factors["riskSafety"]
    )
    lifecycle_reasons = cycle.get("decision", {}).get("reasons")
    return {
        "rankTrend": {
            "direction": str(base.get("signal") or "hold"),
            "score": round(abs(signed_score) * 100),
            "signedScore": signed_score,
        },
        "lifecycle": {
            "stage": cycle["stage"],
            "score": round(clamp(lifecycle_score, 0, 1) * 100),
            "veto": cycle.get("decision", {}).get("action") == "veto",
            "reasons": list(lifecycle_reasons) if isinstance(lifecycle_reasons, list) else [],
            "factors": factors,
        },
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_observation_scores.py -q`
Expected: PASS（2 个用例）。

### Task 2.2：_build_signal 输出合同补齐 observation / strategy / executionStrategy

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend.py:1194`（`_build_signal`）

- [ ] **Step 1: 写失败测试（合同字段）**

```python
from backend.analysis.ranktrend import RankTrendConfig, analyze_technical, analyze_cycle, analyze_risk, analyze_cycle_with_risk, compose_decision, compose_analysis_candidate_tier, compose_strategy, compose_observation_scores


def test_signal_contract_contains_observation_and_both_strategies():
    percentiles = [30 + i for i in range(35)]
    ranks = [120 - i for i in range(35)]
    config = RankTrendConfig()
    technical = analyze_technical(percentiles, config, {"stockChange": 1.0, "volumeRatio": 1.2, "zlje": 10, "zljzb": 0.1})
    cycle = analyze_cycle(ranks, percentiles)
    risk = analyze_risk(percentiles[-1], technical, cycle, 10, 0.1, 1.2)
    cycle = analyze_cycle_with_risk(cycle, risk, technical.get("momentumProfile"))
    decision = compose_decision(technical, cycle, risk, config)
    regime = {"state": "normal", "score": 50, "reasons": []}
    strategy = compose_analysis_candidate_tier(technical, cycle, risk, regime)
    execution = compose_strategy(technical, cycle, risk, None, config)
    observation = compose_observation_scores({
        "technical": technical, "cycle": cycle, "risk": risk, "decision": decision,
    })
    assert {"candidateTier", "action", "regime"} <= set(strategy)
    assert {"candidateTier", "action", "hotlist"} <= set(execution)
    assert {"rankTrend", "lifecycle"} <= set(observation)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_observation_scores.py -q`
Expected: PASS（该测试只验证组合器合同，用于锁定签名；若通过则继续，若导入失败则先修正导入路径）。

- [ ] **Step 3: 改造 _build_signal 输出**

在 `_build_signal` 中，将原来的"按 candidate_tier_mode 二选一"改为同时输出两个分层，并新增 observation：

```python
        strategy = compose_analysis_candidate_tier(technical, cycle, risk, regime)
        execution_strategy = compose_strategy(technical, cycle, risk, frame.get("hotlistSentiment"), config=self.config)
        observation = compose_observation_scores({
            "technical": technical,
            "cycle": cycle,
            "risk": risk,
            "decision": decision,
        })
        rank_trend = {
            "meta": { ... 保持原有 ... },
            "technical": technical,
            "jump": jump,
            "cycle": cycle,
            "risk": risk,
            "decision": decision,
            "observation": observation,
            "strategy": strategy,
            "executionStrategy": execution_strategy,
        }
```

注意：`strategy` 现在必须带 `regime` 字段供消费端使用；`compose_analysis_candidate_tier` 返回时在返回 dict 中补 `"regime": regime`（Python 端与 TS `composeCandidateTier` 输出一致）。

- [ ] **Step 4: 运行全量后端测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿。若有 golden/replay 断言引用旧 `strategy` 结构，按新合同更新断言。

- [ ] **Step 5: Commit**

Run:
```powershell
git -C D:\dragon-board add quant-board/backend/analysis/ranktrend.py quant-board/backend/tests/test_observation_scores.py
git -C D:\dragon-board commit -m "feat: Python 补齐 observation 与 executionStrategy 输出合同"
```

## Phase 3：Python analyze API + frames regime

### Task 3.1：新增 POST /api/ranktrend/analyze

**Files:**
- Create: `quant-board/backend/api/ranktrend_routes.py`
- Modify: `quant-board/backend/main.py`（挂载 router）
- Create: `quant-board/backend/tests/test_ranktrend_analyze_api.py`

- [ ] **Step 1: 写失败 API 测试**

```python
from fastapi.testclient import TestClient
from backend.main import app


client = TestClient(app)


def test_analyze_requires_supported_payload(monkeypatch):
    monkeypatch.setattr("backend.main.create_repository", lambda *a, **k: None)
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "bad_type",
        "codes": [],
    })
    assert response.status_code == 400
    assert "unsupported snapshot_type" in response.text
```

注意：若仓库/缓存不可用，测试应验证 503 或结构化错误（`ok: false` + errorCode），不得返回 200 空结果。

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_ranktrend_analyze_api.py -q`
Expected: FAIL——`404 Not Found`（路由不存在）。

- [ ] **Step 3: 实现 router**

```python
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend import RankTrendGoldenReplayEngine
from backend.data import repository_factory
from backend.data.repository import create_repository

router = APIRouter(tags=["ranktrend-analyze"])

SUPPORTED_SNAPSHOT_TYPES = {"quarter_hour", "half_hour", "hourly", "daily"}


def _parse_frame_key(value: str) -> tuple[str, str]:
    parts = value.split(" ", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(status_code=400, detail=f"invalid frame_key: {value}")
    return parts[0], parts[1]


@router.post("/api/ranktrend/analyze")
def analyze_ranktrend(
    payload: dict[str, Any],
    db=Depends(lambda: repository_factory.get_runtime_database()),
) -> dict[str, Any]:
    snapshot_type = str(payload.get("snapshotType") or "half_hour")
    if snapshot_type not in SUPPORTED_SNAPSHOT_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    dataset_id = str(payload.get("datasetId") or "dragonboard_live")
    codes = [str(c) for c in (payload.get("codes") or [])]
    frame_keys = [str(k) for k in (payload.get("frameKeys") or [])]
    current_frame = payload.get("currentFrame")
    repo = create_repository(db, enable_backup=False)
    engine = RankTrendGoldenReplayEngine(repo, dataset_id=dataset_id, snapshot_type=snapshot_type)
    frames = engine.analyze_frames(
        codes=codes,
        frame_keys=frame_keys or None,
        current_frame=current_frame,
    )
    return {"ok": True, "frames": frames, "source": "py_golden", "issues": []}
```

在 `backend/analysis/ranktrend.py` 的 `RankTrendGoldenReplayEngine` 中新增 `analyze_frames()`：

```python
    def analyze_frames(
        self,
        codes: list[str] | None = None,
        frame_keys: list[str] | None = None,
        current_frame: dict[str, Any] | None = None,
        window_size: int = 50,
    ) -> list[dict[str, Any]]:
        """批量分析指定帧：返回每帧 regime + 每股 golden 链输出。"""
        frames = self._load_frames_for_analysis(frame_keys, current_frame)
        if not frames:
            raise RuntimeError("no frames available for analyze")
        output: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            history_start = max(0, index - window_size + 1)
            history = frames[history_start:index + 1]
            regime = market_regime(frame)
            signals = []
            for stock in frame.get("stocks", []):
                code = str(stock.get("code") or "")
                if codes and code not in codes:
                    continue
                signal = self._replay_stock(stock, frame, history, history_start, regime, {})
                if signal:
                    signals.append({"code": code, "analysis": signal.get("rankTrend")})
            output.append({
                "frameKey": f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip(),
                "regime": regime,
                "totalCount": len(frame.get("stocks", [])),
                "stocks": signals,
            })
        return output
```

其中 `_load_frames_for_analysis` 负责：有 `current_frame` 时把内存 stocks 组装为最新帧并追加到历史帧之后；`frame_keys` 指定时按 `tradingDate + slotTime` 过滤（可复用 repository 现有 `load_frame_bundles`/`load_rank_series` 能力，逐帧构造 `{tradingDate, slotTime, stocks}` 结构，stocks 字段名与 `_build_signal` 消费一致）。

- [ ] **Step 4: main.py 挂载 router**

在 `backend/main.py` 顶部 import 区追加：

```python
from backend.api.ranktrend_routes import router as ranktrend_router
```

在 `app.include_router(...)` 区追加：

```python
app.include_router(ranktrend_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_ranktrend_analyze_api.py -q`
Expected: PASS。

### Task 3.2：frames API 每帧附 regime

**Files:**
- Modify: `quant-board/backend/main.py:518`（`list_snapshot_frames`）

- [ ] **Step 1: 写失败测试**

在 `quant-board/backend/tests/test_ranktrend_analyze_api.py` 追加：

```python
def test_frames_include_regime_when_computable(monkeypatch):
    from backend.analysis.ranktrend import market_regime
    monkeypatch.setattr("backend.analysis.ranktrend.market_regime", lambda frame: {
        "state": "normal", "score": 50, "reasons": ["mock"],
    })
    monkeypatch.setattr("backend.main.create_repository", lambda *a, **k: None)
    response = client.get("/api/snapshots/frames")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        for frame in response.json()["frames"]:
            assert "regime" in frame
```

- [ ] **Step 2: 运行确认失败**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_ranktrend_analyze_api.py -q`
Expected: 至少存在断言失败（frame 无 regime 字段），或仓库不可用时走 503 分支（此时检查实现路径的静态合同）。

- [ ] **Step 3: 实现 frames regime 注入**

在 `list_snapshot_frames` 的 `load_response()` 内，`frames` 从 `repo.load_frame_bundles(...)` 返回后、返回响应前，对每个 frame 注入 regime：

```python
        from backend.analysis.ranktrend import market_regime
        for frame in frames:
            frame["regime"] = market_regime({
                "stocks": frame.get("rows") or frame.get("stocks") or [],
                "marketContext": {
                    "sentiment": frame.get("sentiment"),
                    "marketStats": frame.get("marketStats"),
                },
            })
```

`load_frame_bundles` 的 bundle 已含 `rows/hotlist/stocks` 和 `sentiment/marketStats`，无需额外 DB 查询。

- [ ] **Step 4: 运行全量后端测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿。

- [ ] **Step 5: Commit**

Run:
```powershell
git -C D:\dragon-board add quant-board/backend/api/ranktrend_routes.py quant-board/backend/main.py quant-board/backend/analysis/ranktrend.py quant-board/backend/tests/test_ranktrend_analyze_api.py
git -C D:\dragon-board commit -m "feat: 新增 ranktrend analyze API 与 frames regime 输出"
```

## Phase 4：TS 消费切换

### Task 4.1：apiService 新增 analyzeRankTrend

**Files:**
- Modify: `src/services/apiService.ts`
- Test: `src/services/__tests__/apiService.test.ts`

- [ ] **Step 1: 写失败测试（URL 与方法）**

```ts
it('posts ranktrend analyze payload to /api/ranktrend/analyze', async () => {
  const postSpy = vi.spyOn(apiService, 'post').mockResolvedValue({ ok: true, frames: [], source: 'py_golden', issues: [] })
  await apiService.analyzeRankTrend({ datasetId: 'dragonboard_live', snapshotType: 'half_hour', codes: ['002279'] })
  expect(postSpy).toHaveBeenCalledWith('/api/ranktrend/analyze', expect.objectContaining({
    snapshotType: 'half_hour',
    codes: ['002279'],
  }), expect.objectContaining({ context: 'quant-board' }))
})
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm exec vitest run src/services/__tests__/apiService.test.ts -t "analyze" --reporter=basic`
Expected: FAIL——`apiService.analyzeRankTrend is not a function`。

- [ ] **Step 3: 实现方法**

在 `apiService.ts` 的 `getRankTrendRankSeries` 之后新增：

```ts
/** 调用 QuantBoard Python 批量分析：返回每帧 regime + 每股 golden 链输出 */
async analyzeRankTrend(payload: {
  datasetId?: string
  snapshotType: string
  codes?: string[]
  frameKeys?: string[]
  currentFrame?: {
    tradingDate: string
    slotTime: string
    stocks: Array<Record<string, unknown>>
  }
}, options?: RequestConfig) {
  return this.post<{
    ok: boolean
    frames: Array<{
      frameKey: string
      regime: { state: string; score: number; reasons: string[] }
      totalCount: number
      stocks: Array<{ code: string; analysis: Record<string, unknown> }>
    }>
    source: string
    issues: string[]
  }>(`/api/ranktrend/analyze`, {
    datasetId: payload.datasetId || 'dragonboard_live',
    snapshotType: payload.snapshotType,
    codes: payload.codes || [],
    frameKeys: payload.frameKeys || [],
    currentFrame: payload.currentFrame,
  }, {
    context: 'quant-board',
    priority: 'high',
    retries: 1,
    timeout: 15000,
    cache: false,
    throwOnHttpError: true,
    ...options,
  })
}
```

- [ ] **Step 4: 运行确认通过**

Run: `pnpm exec vitest run src/services/__tests__/apiService.test.ts -t "analyze" --reporter=basic`
Expected: PASS。

### Task 4.2：RankTrendAnalyzer 改造为消费 analyze API

**Files:**
- Modify: `src/services/RankTrendAnalyzer.ts`
- Test: `src/services/__tests__/RankTrendAnalyzer.test.ts`

- [ ] **Step 1: 写失败测试（消费 API + analysisUnavailable）**

```ts
it('consumes py golden analysis and marks analysisUnavailable on API failure', async () => {
  const payload = { codes: ['002279'], snapshotType: 'half_hour' }
  const apiSpy = vi.spyOn(apiService, 'analyzeRankTrend')
    .mockResolvedValue({
      ok: true,
      frames: [{
        frameKey: 'current:1',
        regime: { state: 'strong', score: 80, reasons: [] },
        totalCount: 200,
        stocks: [{ code: '002279', analysis: { strategy: { candidateTier: 'A_MAIN' }, meta: { code: '002279' } } }],
      }],
      source: 'py_golden',
      issues: [],
    })
  const result = await rankTrendAnalyzer.getRankTrends(new Map([['002279', 1]]), {
    preferRemoteAnalysis: true,
    ...payload,
  })
  expect(apiSpy).toHaveBeenCalled()
  expect(result.get('002279')?.strategy?.candidateTier).toBe('A_MAIN')
  expect(result.get('002279')?.meta?.analysisSource).toBe('py_golden')

  apiSpy.mockRejectedValue(new Error('backend offline'))
  const fallback = await rankTrendAnalyzer.getRankTrends(new Map([['002279', 1]]), {
    preferRemoteAnalysis: true,
    ...payload,
  })
  expect(fallback.get('002279')?.meta?.analysisSource).toBe('analysis_unavailable')
  expect(fallback.get('002279')?.meta?.analysisUnavailableReason).toContain('backend offline')
})
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm exec vitest run src/services/__tests__/RankTrendAnalyzer.test.ts -t "analysisUnavailable" --reporter=basic`
Expected: FAIL。

- [ ] **Step 3: 实现消费路径**

`getRankTrends` 在现有序列组装之后，新增远程分析分支：

```ts
    if (options.preferRemoteAnalysis !== false) {
      const stocks = (typeof dataLayer.getStocks === 'function' ? dataLayer.getStocks() : []) as any[]
      const currentFrameStocks = stocks
        .filter((s: any) => rankMap.has(String(s.code)))
        .map((s: any) => ({
          code: String(s.code),
          rank: Number(s.compRank || s.rank) || 0,
          avgRankNum: Number(s.avgRankNum) || 0,
          change: Number(s.change) || 0,
          volumeRatio: Number(s.volumeRatio) || 0,
          zlje: Number(s.zlje) || 0,
          zljzb: Number(s.zljzb) || 0,
          platforms: Number(s.platforms) || 0,
        }))
      try {
        const remote = await apiService.analyzeRankTrend({
          datasetId: options.datasetId,
          snapshotType: options.preferredSnapshotType || DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          codes: Array.from(rankMap.keys()),
          currentFrame: {
            tradingDate: new Date().toISOString().slice(0, 10),
            slotTime: currentFrameKey,
            stocks: currentFrameStocks,
          },
        })
        if (remote?.ok && remote.frames?.[0]) {
          const frameResult = remote.frames[0]
          const byCode = new Map(frameResult.stocks.map((item) => [item.code, item.analysis]))
          for (const [code, result] of results) {
            const analysis = byCode.get(code)
            if (analysis) {
              result.meta = { ...result.meta, ...analysis.meta, analysisSource: 'py_golden' as const }
              result.technical = analysis.technical
              result.cycle = analysis.cycle
              result.risk = analysis.risk
              result.decision = analysis.decision
              result.observation = analysis.observation
              result.strategy = analysis.strategy
              result.executionStrategy = analysis.executionStrategy
              result.jump = analysis.jump
            }
          }
          return results
        }
      } catch (error) {
        for (const result of results.values()) {
          result.meta = {
            ...result.meta,
            analysisSource: 'analysis_unavailable' as const,
            analysisUnavailableReason: errorMessage(error),
          }
        }
        return results
      }
    }
```

注意：该分支保留现有 `computeStockRankTrend` 组装出的 per-code `results`（用于 live-only series 与 meta），远程成功时覆盖 golden 字段；失败时仅打标，不调用本地 pipeline。`DEFAULT_RANK_TREND_SNAPSHOT_TYPE` 从 `@/types/rankTrendDefaults` 导入。

- [ ] **Step 4: 运行确认通过**

Run: `pnpm exec vitest run src/services/__tests__/RankTrendAnalyzer.test.ts -t "analysisUnavailable" --reporter=basic`
Expected: PASS。

### Task 4.3：RankTrendSignalService 消费 Python jump、保留 resonance

**Files:**
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
- Test: `src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`

- [ ] **Step 1: 写失败测试（jump 消费 Python 输出）**

```ts
it('applies jump signals from py golden jump events without local redetection', async () => {
  const stock = {
    code: '002279',
    rankTrend: {
      meta: { code: '002279', analysisSource: 'py_golden' },
      jump: { event: 'jump', direction: 'buy', confidence: 80, events: [{ direction: 'surge' }] },
    },
  }
  const detectorSpy = vi.spyOn(jumpSignalService, 'evaluateJumpSignal')
  rankTrendSignalService['applyJumpSignals']([stock])
  expect(detectorSpy).not.toHaveBeenCalled()
})
```

若该测试难以直接断言，改为断言 `applyJumpSignals` 在 `rankTrend.jump.event === 'jump'` 时产生持仓登记（mock 持仓 store），且不调用本地 `detectRankJumps`。

- [ ] **Step 2: 运行确认失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts -t "py golden" --reporter=basic`
Expected: FAIL（当前仍本地重算）。

- [ ] **Step 3: 改造 applyJumpSignals**

把 `applyJumpSignals` 内对每只股票的 jump 判定从"基于 percentiles 重算"改为"优先消费 `rankTrend.jump`（Python 输出）；本地重算路径删除"。保留持仓登记/通知/退出逻辑不变。

- [ ] **Step 4: 运行确认通过 + 保留 resonance 回归**

Run: `pnpm test:ranktrend --reporter=basic`
Expected: 全绿（含既有 resonance 用例）。

- [ ] **Step 5: Commit**

Run:
```powershell
git -C D:\dragon-board add src/services/apiService.ts src/services/RankTrendAnalyzer.ts src/services/dataLoader/RankTrendSignalService.ts src/services/__tests__/apiService.test.ts src/services/__tests__/RankTrendAnalyzer.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts
git -C D:\dragon-board commit -m "feat: TS 实时链路消费 Python golden 分析结果"
```

## Phase 5：观察面板消费切换

### Task 5.1：RankTrendObservationService 改读 frame.regime 与 analyze API

**Files:**
- Modify: `src/services/rankTrend/RankTrendObservationService.ts`
- Test: `src/services/rankTrend/__tests__/RankTrendObservationService.test.ts`

- [ ] **Step 1: 写失败测试（历史帧 regime 来自 frame.regime）**

在现有"历史帧按该帧已落库 marketStats 重算"用例之后新增：

```ts
it('历史帧 regime 以 Python frame.regime 为准，不再本地计算', async () => {
  // frameKeys 为真实日期，mock listSnapshotFrames 返回带 regime 的帧
  // 断言 frames[0].analysis?.strategy?.regime 等于 frame.regime
  // 且 listSnapshotFrames 之后不再调用 analyzeMarketRegime
})
```

测试骨架沿用现有用例的 mock 模式（`getLatestAnalysisSeries`、`listSnapshotStockRows`、`listSnapshotFrames`），断言 `regime.state` 等于 frame 附带的 regime，并 `vi.spyOn` 验证本地 `analyzeMarketRegime` 未被调用。

- [ ] **Step 2: 运行确认失败**

Run: `pnpm exec vitest run src/services/rankTrend/__tests__/RankTrendObservationService.test.ts --reporter=basic`
Expected: FAIL。

- [ ] **Step 3: 改造观察服务**

- 删除 `resolveHistoricalRegime`/`hasRegimeMaterial` 本地计算与 `analyzeMarketRegime` import；
- 历史帧 regime 直接取 `frame.regime`（`listSnapshotFrames` 返回的新字段）；缺失时置 `historical_regime_unavailable` 中性降级（保留 fail-visible）；
- 历史帧的 technical/cycle/risk/decision/observation/strategy 改为通过 `apiService.analyzeRankTrend({ codes: [code], frameKeys: [key] })` 批量获取并合并到 `analysis`；API 失败时该帧标记 `analysis_unavailable` 且不展示伪造结果；
- 保留 resonance 轨的横截面计算（live-only，P3 迁）。

- [ ] **Step 4: 运行确认通过**

Run: `pnpm exec vitest run src/services/rankTrend/__tests__/RankTrendObservationService.test.ts --reporter=basic`
Expected: PASS。

### Task 5.2：面板"分析不可用"状态

**Files:**
- Modify: `src/components/panels/RankTrendObservationPanel.vue`
- Test: `src/components/panels/__tests__/RankTrendObservationPanel.test.ts`

- [ ] **Step 1: 写失败测试（analysis_unavailable 渲染）**

断言当 `meta.analysisSource === 'analysis_unavailable'` 时面板显示"分析不可用"+ 原因文本，且技术/生命周期轨不渲染伪造分数。

- [ ] **Step 2: 运行确认失败 → 实现 → 确认通过**

Run: `pnpm exec vitest run src/components/panels/__tests__/RankTrendObservationPanel.test.ts --reporter=basic`
Expected: 先 FAIL，实现后 PASS。

- [ ] **Step 3: Commit**

Run:
```powershell
git -C D:\dragon-board add src/services/rankTrend/RankTrendObservationService.ts src/components/panels/RankTrendObservationPanel.vue src/services/rankTrend/__tests__/RankTrendObservationService.test.ts src/components/panels/__tests__/RankTrendObservationPanel.test.ts
git -C D:\dragon-board commit -m "feat: 观察面板消费 Python regime/分析结果并支持分析不可用状态"
```

## Phase 6：删除 TS 本地实现与测试清理

### Task 6.1：删除本地 golden 链文件与相关测试

**Files:**
- Delete（git 保留历史，可回退）：
  - `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
  - `src/services/rankTrend/technicalSignalAnalyzer.ts`
  - `src/services/rankTrend/attentionCycleAnalyzer.ts`
  - `src/services/rankTrend/riskSignalAnalyzer.ts`
  - `src/services/rankTrend/candidateTierComposer.ts`
  - `src/services/rankTrend/executionCandidateTierComposer.ts`
  - `src/services/rankTrend/resultComposer.ts`
  - `src/services/rankTrend/observationScoreComposer.ts`
  - `src/services/rankTrend/marketRegimeAnalyzer.ts`
  - `src/services/rankTrend/jumpDetector.ts`
- 删除对应的 `__tests__/*.test.ts`（technicalSignalAnalyzer/attentionCycleAnalyzer/riskSignalAnalyzer/candidateTierComposer/executionCandidateTierComposer/resultComposer/observationScoreComposer/marketRegimeAnalyzer/jumpDetector/runRankTrendAnalysisPipeline）。
- Modify: `src/services/rankTrend/utils.ts`（移除仅供 golden 链使用的窗口函数，保留 resonance/jump 需要部分）

**删除约束：** 每次删除一个明确路径的文件（项目禁止批量删除命令）；使用 `git rm` 逐个提交。

- [ ] **Step 1: 先确认没有业务代码再引用被删文件**

Run: `rg -n "runRankTrendAnalysisPipeline|technicalSignalAnalyzer|attentionCycleAnalyzer|riskSignalAnalyzer|candidateTierComposer|executionCandidateTierComposer|resultComposer|observationScoreComposer|marketRegimeAnalyzer|jumpDetector" src --glob '!**/__tests__/**'`
Expected: 无业务引用（Phase 4/5 已完成消费切换）；如有遗漏引用，先修。

- [ ] **Step 2: 逐个删除文件与测试**

Run（示例，逐个执行）:
```powershell
git -C D:\dragon-board rm src/services/rankTrend/runRankTrendAnalysisPipeline.ts
git -C D:\dragon-board rm src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts
```

重复直到清单完成。

- [ ] **Step 3: 清理 utils.ts 只供 golden 的导出**

删除 `getMacdMinSamples/getMomentumMinSamples/getTechnicalMinComputableSamples/getTechnicalMinSamples` 等仅 golden 链使用的函数（先 `rg` 确认无引用）。

- [ ] **Step 4: 全量验证**

Run: `pnpm test:ranktrend --reporter=basic`
Expected: 通过；若有遗留测试引用被删模块，删除对应测试。

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 退出码 0。

### Task 6.2：全量回归

- [ ] **Step 1: 运行全量前端测试**

Run: `pnpm test --reporter=basic`
Expected: 116 个文件全部通过。

- [ ] **Step 2: 运行全量后端测试**

Run: `cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全绿。

- [ ] **Step 3: Commit**

Run:
```powershell
git -C D:\dragon-board add -u src/services/rankTrend
git -C D:\dragon-board commit -m "refactor: 删除 TS 本地 golden 链实现，统一消费 Python 输出"
```

## Phase 7：golden 方向文档反转

### Task 7.1：更新文档合同

**Files:**
- Modify: `AGENTS.md`（4.2）
- Modify: `quant-board/docs/ranktrend-golden.md`
- Modify: `quant-board/docs/ranktrend-python-port.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`

- [ ] **Step 1: 更新 AGENTS.md 4.2**

把"TypeScript `src/services/RankTrendAnalyzer.ts` ... 是 Python 移植的 golden 标准"改为"RankTrend golden 以 Python `quant-board/backend/analysis/ranktrend.py` 为生产事实标准，TS 前端只消费 `POST /api/ranktrend/analyze` 与 frames API 输出；TS 不再保留本地 golden 链算法实现"。

- [ ] **Step 2: 更新 quant-board/docs/ranktrend-golden.md**

来源与校验方向反转：golden case 由 Python 生成，TS 消费校验；删除"TS 是唯一 golden 来源"表述。

- [ ] **Step 3: 更新 quant-board/docs/ranktrend-python-port.md**

对齐目标从"复刻 TS"改为"Python 自身合同 + 跨语言消费契约校验"。

- [ ] **Step 4: 更新 quant-board/docs/AI_COLLABORATION.md**

同步 golden 方向与 API 合同（analyze API、frames regime）。

- [ ] **Step 5: Commit**

Run:
```powershell
git -C D:\dragon-board add AGENTS.md quant-board/docs/ranktrend-golden.md quant-board/docs/ranktrend-python-port.md quant-board/docs/AI_COLLABORATION.md
git -C D:\dragon-board commit -m "docs: RankTrend golden 方向反转，Python 为生产事实标准"
```

## Phase 8：回测基线对比与浏览器验收

### Task 8.1：新旧 regime 分层基线对比

**Files:** 无（运行 QuantBoard 回测）

- [ ] **Step 1: 记录旧基线**

从现有回测结果导出 regime 分层分布（strong/normal/weak/retreat × A_MAIN/B_IGNITION/C_CROWDED/D_EXIT_RISK/N_NEUTRAL），保存到 `quant-board/data/reports/`（不提交大产物，写结论到 `docs/ranktrend/`）。

- [ ] **Step 2: 重跑同区间回测**

用相同 dataset/strategy/config 重跑，导出新分层分布；对比 A/B 准入数量变化、regime 分布变化。

- [ ] **Step 3: 样本外抽查**

在分化行情样本（全A 跌多涨少但热榜题材走强的交易日）抽查 regime 状态，确认不再被全A 压制；把抽查结论写入 `docs/ranktrend/` 文档。

- [ ] **Step 4: 冻结权重与阈值**

用户确认对比结果后，把五因子权重/阈值从"基线 v1"冻结为正式值（冻结后不再调整），并同步到设计文档与 Python 常量。

### Task 8.2：浏览器验收

**Files:**
- Run: Playwright（项目 `playwright-cli` 或 e2e 现有模式）

- [ ] **Step 1: 启动依赖服务**

后端 `quant-board`（8000）、proxy（3000）、前端 dev（5173）。

- [ ] **Step 2: 验收主表与观察面板**

- 主表候选分层显示 Python 输出（`source: py_golden`）；
- 观察面板历史帧 regime 与当前帧 regime 数值一致、不出现"历史帧市场环境未单独持久化"旧文案；
- 控制台无错误。

- [ ] **Step 3: 验收离线场景**

停止 8000 后刷新页面：主表/观察面板显示"分析不可用"+ 原因，不展示伪造分层/生命周期；恢复服务后自动恢复。

- [ ] **Step 4: 记录结果**

把验收结果（截图路径、控制台结论、离线行为）写入 `docs/ranktrend/` 进度文档，并运行 `git diff --check`。

## 自审记录

- 覆盖检查：设计文档 13 节均有对应 Phase/Task（regime 五因子→Phase 1；py 生产/API→Phase 2/3；TS 消费与删除→Phase 4/5/6；golden 反转→Phase 7；验证/回测→Phase 8）。
- 类型一致性：`analysisSource: 'py_golden' | 'analysis_unavailable'` 字段在 Task 4.2/5.1/5.2 使用一致；`frame.regime` 在 Task 3.2/5.1 一致；Python `compose_observation_scores` 输出键名与 TS observationScoreComposer 一致。
- 无占位符：所有实现步骤均给出代码或明确改造点；唯一待冻结项（权重/阈值）有明确冻结触发点（Phase 8 Task 8.1 Step 4）。
