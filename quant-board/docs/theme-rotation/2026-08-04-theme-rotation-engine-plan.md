# 题材/板块轮动引擎（后端重写）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 QuantBoard 后端新增唯一权威的题材轮动引擎（rotationState/lifecycle/rotationScore/rotationSummary），采集落库时写入 `snapshot_sector_rows` 与 frame，前端与 theme_trend/theme_support 全部改为消费后端落库结果，删除前端本地轮动计算。

**Architecture:** 引擎分四层——纯函数因子层（`factors.py`）→ 纯函数状态机（`lifecycle.py`）→ 组合引擎（`engine.py`）→ 有 I/O 的历史读取与落库接入（`history.py` + collector `_persist_one` 注入点）。引擎只依赖 `snapshot_sector_rows`/`snapshot_stock_rows` 跨槽位历史序列（MongoDB），不依赖进程内存，补采/重启/回测均可重放；历史或字段不足时输出 `null + reasons[] + qualityFlags`，绝不阻断已有数据入库。

**Tech Stack:** Python 3.11 / FastAPI / pymongo（同步，经 `asyncio.to_thread` 移出事件循环）/ pytest；前端 Vue 3 + TypeScript（仅消费映射，不计算）；验证命令：`quant-board\.venv\Scripts\python.exe -m pytest`、`pnpm test`、`vue-tsc`、Playwright。

---

## 已确认的设计选择（2026-08-04 用户已批准）

1. **历史窗口**：默认 8 槽（约 4 小时）滚动窗口；按 `timestamp` 升序取当前槽之前的最近 8 个槽，跨日自然衔接；不足 3 槽时不输出状态（`null + reason`）。
2. **连板/晋级**：第一版就做基础连板聚合（最高板/梯队/晋级率），数据缺失时显式降级（`qualityFlags`），不阻断其他因子。
3. **输出落点**：rotationState/lifecycle/rotationScore/reasons/factorBreakdown 写入 `snapshot_sector_rows`；`rotationSummary` 写入 frame；回测/theme_trend/theme_support/前端同源读取。
4. **fail-visible 硬约束**：引擎异常、历史不足、字段缺失都不得阻止快照入库；原始数据照存，质量问题写入 frame 的 `metadata.derivation.qualityIssues` 与 sector row 的 `qualityFlags`。

## 外部审计修订（2026-08-04，见 `2026-08-04-theme-rotation-engine-audit.md`）

本版计划已吸收审计的 4 个阻塞 + 8 个高危 + 主要中危问题：

- **C1** `rotationSummary` 落库必须 camelCase：`MarketRotationSummary.to_camel_dict()`（Task 1 实现）。
- **C2** `theme_trend.LIFECYCLES` 扩展新词汇 + `_build_factor` 回测路径透传落库 lifecycle（Task 8）。
- **C3** `backendRead.ts` 停止剥除 `rotationSummary.mainLines`（Task 9）。
- **C4** `market_phase_for` 增加 cooling/neutral 分支（Task 3）。
- **H1** 跨日基线：`history.py` 用交易日历回溯前一交易日，上一槽股票按 `slot_time` 精确查询（Task 5）。
- **H2** Supabase schema + homomorphic 映射同步新列（Task 10）。
- **H3** `algorithmVersion` 标识引擎版本，消费端按版本分支（Task 8/9）。
- **H4** SQLite 旧读路径仅在 rotationSummary 无 `algorithmVersion` 时合并 `rotation_main_line`（Task 10）。
- **H5** 前端全部 rotationSummary/rotationState 消费者兼容审计（Task 9）。
- **H6** flow 持续性 streak 由 engine 从历史序列计算传入（Task 2/4）。
- **H7** 引擎测试夹具与断言对齐代码（Task 4）。
- **H8** 主线判定按设计双条件：横向 z-score Top3 且 资金集中度 Top3（Task 4）。
- **H9** 晋级率用字符串比较 + 主题内分母（Task 2）。
- **9.3 硬缺口**：板块超额显式降级；股票归集按 `themes` 列表 + `mainTheme` 归一化（Task 4）；flow streak 引擎计算（Task 4）。
- **M1-M12**：见各 Task 内联修正（min_factors 生效、转移约束、neutral 兜底、join 精度、API 过滤、测试 mock、类型可选化等）。

## 文件结构

**新增（后端引擎）**

- `quant-board/backend/analysis/theme_rotation/__init__.py` — 包导出（`ThemeRotationEngine`、`ThemeRotationConfig`、`ThemeRotationService`）
- `quant-board/backend/analysis/theme_rotation/config.py` — 配置：窗口/权重/阈值（唯一参数来源）
- `quant-board/backend/analysis/theme_rotation/models.py` — 输出合同 dataclass
- `quant-board/backend/analysis/theme_rotation/factors.py` — 五组因子纯函数
- `quant-board/backend/analysis/theme_rotation/lifecycle.py` — 主题/市场状态机纯函数
- `quant-board/backend/analysis/theme_rotation/engine.py` — 组合引擎（无 I/O）
- `quant-board/backend/analysis/theme_rotation/history.py` — 历史槽位读取（I/O，注入 repo）
- `quant-board/backend/analysis/theme_rotation/service.py` — 运行时服务：历史加载 + 引擎计算 + 落库 enrichment（异步，I/O 走 `asyncio.to_thread`）
- `quant-board/backend/api/theme_rotation_routes.py` — `GET /api/theme-rotation/summary`

**修改（后端接入）**

- `quant-board/backend/snapshot_collector/repository_port.py` — 增加 `list_snapshot_sector_rows` / `list_snapshot_stock_rows` 协议方法
- `quant-board/backend/snapshot_collector/service_factory.py` — `_MongoSnapshotCollectorRepository` 实现新增方法
- `quant-board/backend/snapshot_collector/service.py` — `_persist_one` 注入轮动 enrichment（可注入 fake，异常不阻断）
- `quant-board/backend/main.py` — 注册 theme_rotation 路由
- `quant-board/backend/analysis/theme_trend.py` — 优先消费 sector rows 落库的 rotationState/lifecycle，缺时才走旧推导并打标记
- `quant-board/backend/analysis/theme_support.py` — 增加 lifecycle/rotationScore 可选证据

**新增/修改（前端，只消费）**

- `src/services/theme/backendRotationAdapter.ts`（新增）— 后端 rotationSummary → 前端 `RotationAnalysis` 展示映射（纯投影，无计算）
- `src/services/theme/ThemeRotationEngine.ts` — 删除本地状态机，改为引用 adapter（或删除并由 adapter 取代，见 Task 9）
- `src/services/theme/ThemeFacade.ts` — `getRotationSummary()` 读后端结果
- `src/services/theme/ThemeRuntimeCoordinator.ts` — 停止本地 `buildThemeRotationSummary` 调用
- `src/services/theme/ThemeFactorEngine.ts` — 删除本地 rotationState/persistence 推导，改透传
- `src/components/panels/SectorRotation.vue`、`SectorPanel.vue` — 消费后端 rotationSummary
- `src/types/core.ts` — `RotationAnalysis` 扩展可选字段（lifecycle/rotationScore/mainlineConcentration/evidence）

**测试**

- `quant-board/tests/test_theme_rotation_config.py`、`test_theme_rotation_factors.py`、`test_theme_rotation_lifecycle.py`、`test_theme_rotation_engine.py`、`test_theme_rotation_history.py`、`test_theme_rotation_service.py`、`test_theme_rotation_api.py`、`test_theme_rotation_collector_integration.py`
- 前端：`src/services/theme/__tests__/backendRotationAdapter.test.ts`、既有 `ThemeFacade/ThemeRuntimeCoordinator` 测试同步更新

---

## 公共约定（所有任务通用）

- 数值工具：缺失保持缺失，禁止用 0 伪装；跨题材截面指标统一用「中位数 + MAD」的稳健 z 值再映射 0-100。
- 主题键：`_theme_key(row) = row.get("themeId") or row.get("entityKey") or row.get("id")`；名称匹配回退 `entityName/themeName`。
- 提交粒度：每个 Task 一个 commit，消息前缀 `feat(theme-rotation): ...` / `refactor(theme): ...`。
- 运行环境：后端命令都在 `D:\dragon-board\quant-board` 下执行，解释器 `.\.venv\Scripts\python.exe`。

---

## Task 1: theme_rotation 包、配置与输出模型

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/__init__.py`
- Create: `quant-board/backend/analysis/theme_rotation/config.py`
- Create: `quant-board/backend/analysis/theme_rotation/models.py`
- Test: `quant-board/tests/test_theme_rotation_config.py`

### config.py（完整内容）

```python
"""题材轮动引擎配置：默认参数唯一来源。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThemeRotationConfig:
    """轮动引擎默认参数。窗口/权重/阈值均可按数据集覆盖。"""

    window_slots: int = 8
    min_slots_for_state: int = 3
    min_factors_for_score: int = 3

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "strength": 0.30,
            "flow": 0.25,
            "breadth": 0.20,
            "crowding": 0.15,
            "lifecycle": 0.10,
        }
    )

    # ── 主题生命周期阈值（lifecycle.py） ──
    ice_heat: float = 40.0
    ice_momentum: float = 40.0
    emerging_heat_min: float = 40.0
    expanding_heat: float = 60.0
    climax_heat: float = 80.0
    climax_crowding: float = 75.0
    climax_max_board: int = 7
    cooling_momentum: float = 35.0
    cooling_negative_inflow_streak: int = 2

    # ── 主线判定 ──
    mainline_top_n: int = 3
    concentration_top_n: int = 3

    # ── 市场阶段（lifecycle.py） ──
    market_ice_max_board: int = 3
    market_ice_min_zt_count: int = 30
    market_rising_min_board: int = 7
    market_climax_max_board: int = 10
    market_climax_min_concentration: float = 0.80
    market_chaos_min_rotation_speed: float = 60.0
    market_neutral_max_rotation_speed: float = 40.0
    market_cooling_theme_ratio: float = 0.35
    market_cooling_negative_inflow_ratio: float = 0.50
    min_mainline_z_rank: int = 3
    min_mainline_concentration_rank: int = 3

    algorithm_version: str = "theme_rotation_v2"
```

### models.py（完整内容）

```python
"""题材轮动输出合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThemeFactorScores:
    """单个题材在当前槽的五组因子得分（0-100，缺失为 None）。"""

    theme_id: str
    theme_name: str
    strength: float | None = None
    flow: float | None = None
    breadth: float | None = None
    crowding: float | None = None
    lifecycle: float | None = None
    missing: list[str] = field(default_factory=list)

    def available(self) -> list[str]:
        """返回非缺失因子名，用于权重归一化。"""
        return [key for key in ("strength", "flow", "breadth", "crowding", "lifecycle")
                if getattr(self, key) is not None]


@dataclass
class ThemeRotationStatus:
    """单个题材的轮动输出（写入 sector row）。"""

    theme_id: str
    theme_name: str
    rotation_state: str | None = None
    lifecycle: str | None = None
    rotation_score: float | None = None
    rank: int = 0
    rank_change: int = 0
    heat_trend: float | None = None
    flow_trend: float | None = None
    breadth_trend: float | None = None
    crowding_trend: float | None = None
    mainline_concentration_rank: int | None = None
    reasons: list[str] = field(default_factory=list)
    factor_breakdown: dict[str, float | None] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class MarketRotationSummary:
    """市场级轮动摘要（写入 frame.rotationSummary）。"""

    market_phase: str = "unknown"
    rotation_speed: float | None = None
    mainline_concentration: float | None = None
    max_board_height: int | None = None
    main_lines: list[dict[str, Any]] = field(default_factory=list)
    inflow_themes: list[str] = field(default_factory=list)
    outflow_themes: list[str] = field(default_factory=list)
    suggestion: str = ""
    computed_at: int = 0
    algorithm_version: str = "theme_rotation_v2"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_camel_dict(self) -> dict[str, Any]:
        """序列化为消费端统一的 camelCase 合同（审计 C1：禁止 snake_case 落库）。"""
        return {
            "marketPhase": self.market_phase,
            "rotationSpeed": self.rotation_speed,
            "mainlineConcentration": self.mainline_concentration,
            "maxBoardHeight": self.max_board_height,
            "mainLines": self.main_lines,
            "inflowThemes": self.inflow_themes,
            "outflowThemes": self.outflow_themes,
            "suggestion": self.suggestion,
            "computedAt": self.computed_at,
            "algorithmVersion": self.algorithm_version,
            "evidence": self.evidence,
        }


@dataclass
class ThemeRotationResult:
    """引擎一次计算的完整输出。"""

    statuses: list[ThemeRotationStatus] = field(default_factory=list)
    market: MarketRotationSummary = field(default_factory=MarketRotationSummary)
    quality_issues: list[str] = field(default_factory=list)
    frames_used: int = 0


@dataclass
class HistorySlot:
    """一个历史槽位（来自 MongoDB，供引擎消费）。"""

    timestamp_ms: int
    trading_date: str
    sector_rows: list[dict[str, Any]] = field(default_factory=list)
    stock_rows: list[dict[str, Any]] | None = None


@dataclass
class RotationHistory:
    """历史读取结果。"""

    slots: list[HistorySlot] = field(default_factory=list)
    source: str = "mongodb"
```

### `__init__.py`

```python
"""题材轮动引擎：rotationState/rotationSummary 的唯一生产者。"""

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.models import (
    HistorySlot,
    MarketRotationSummary,
    RotationHistory,
    ThemeRotationResult,
    ThemeRotationStatus,
)

__all__ = [
    "ThemeRotationConfig",
    "ThemeRotationEngine",
    "HistorySlot",
    "MarketRotationSummary",
    "RotationHistory",
    "ThemeRotationResult",
    "ThemeRotationStatus",
]
```

### 测试 `quant-board/tests/test_theme_rotation_config.py`

```python
from backend.analysis.theme_rotation.config import ThemeRotationConfig


def test_default_config_contract():
    cfg = ThemeRotationConfig()
    assert cfg.window_slots == 8
    assert cfg.min_slots_for_state == 3
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9
    assert set(cfg.weights) == {"strength", "flow", "breadth", "crowding", "lifecycle"}
    assert cfg.algorithm_version == "theme_rotation_v2"


def test_config_thresholds_are_in_expected_ranges():
    cfg = ThemeRotationConfig()
    assert 0 < cfg.ice_heat < cfg.expanding_heat < cfg.climax_heat <= 100
    assert cfg.mainline_top_n >= 1
    assert cfg.cooling_negative_inflow_streak >= 1
```

- [ ] **Step 1**: 创建上述 4 个文件（`__init__.py` 中 `engine` 的导入在 Task 4 落地前会失败——先用占位 `ThemeRotationEngine` 类放在 `engine.py`：`class ThemeRotationEngine: pass`）。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_config.py -q`，预期 2 passed。
- [ ] **Step 3**: 提交 `feat(theme-rotation): add config and output models`。

---

## Task 2: factors.py —— 五组截面/序列因子（纯函数）

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/factors.py`
- Test: `quant-board/tests/test_theme_rotation_factors.py`

### factors.py（完整内容）

```python
"""五组轮动因子：全部纯函数，输入为跨槽位 sector/stock rows，输出 0-100 或 None。"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def robust_z(value: float, values: list[float]) -> float:
    """稳健 z-score：(value - median) / (MAD + 1e-9)。"""
    if not values:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values]) if len(values) > 1 else 0.0
    return (value - median) / (mad + 1e-9)


def z_to_score(z: float, slope: float = 16.7) -> float:
    """稳健 z 映射到 0-100：z=0 → 50。"""
    return _clamp(50.0 + slope * z)


def linear_slope(values: list[float]) -> float | None:
    """按槽位序号做最小二乘斜率（每槽单位）。"""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denom


def strength_score(
    row: dict[str, Any],
    history_heats: list[float],
    all_current_heats: list[float],
    market_change: float | None,
    prev_zt_count: float | None,
) -> tuple[float | None, list[str]]:
    """强度/动量：heat、横向 z、heat 斜率、涨停动能、板块超额。"""
    missing: list[str] = []
    heat = _num(row.get("heatScore"))
    if heat is None:
        missing.append("heatScore")
        return None, missing
    heat_score = _clamp(heat)

    z = robust_z(heat, all_current_heats)
    cross_z_score = z_to_score(z)

    series = [*history_heats, heat]
    slope = linear_slope(series)
    slope_score = _clamp(50.0 + (slope or 0.0) * 20.0)

    zt_count = _num(row.get("ztCount"), 0.0) or 0.0
    zt_delta = zt_count - (prev_zt_count or 0.0)
    zt_score = _clamp(zt_count * 6.0 + max(0.0, zt_delta) * 10.0)

    theme_change = _num(row.get("change"))
    if theme_change is not None and market_change is not None:
        excess_score = _clamp(50.0 + (theme_change - market_change) * 12.0)
    else:
        missing.append("excess")
        excess_score = None

    parts: list[float] = []
    weights: list[float] = []
    for value, weight in ((heat_score, 0.30), (cross_z_score, 0.20), (slope_score, 0.20), (zt_score, 0.15)):
        parts.append(value)
        weights.append(weight)
    if excess_score is not None:
        parts.append(excess_score)
        weights.append(0.15)
    total_w = sum(weights)
    score = sum(p * w for p, w in zip(parts, weights)) / total_w
    return _clamp(score), missing


def flow_score(
    row: dict[str, Any],
    inflow_series: list[float | None],
    all_current_inflows: list[float],
    positive_streak: int,
) -> tuple[float | None, list[str]]:
    """资金：主力净流入、加速度、集中度、持续性。"""
    missing: list[str] = []
    inflow = _num(row.get("mainNetInflow"))
    if inflow is None:
        missing.append("mainNetInflow")
        return None, missing

    inflow_z = z_to_score(robust_z(inflow, all_current_inflows))

    deltas: list[float] = []
    for prev in inflow_series[-3:]:
        if prev is not None:
            deltas.append(inflow - prev)
    if deltas:
        total_delta = sum(deltas)
        accel_score = _clamp(50.0 + (1.0 if total_delta >= 0 else -1.0) * min(30.0, abs(total_delta) * 3.0))
    else:
        missing.append("flowAcceleration")
        accel_score = None

    positive = [v for v in all_current_inflows if v and v > 0]
    total_positive = sum(positive)
    if total_positive > 0:
        share = inflow / total_positive
        concentration_score = _clamp(share * 300.0)
    else:
        missing.append("flowConcentration")
        concentration_score = None

    persistence_score = _clamp(positive_streak * 20.0)

    parts = [inflow_z, persistence_score]
    weights = [0.35, 0.20]
    if accel_score is not None:
        parts.append(accel_score)
        weights.append(0.25)
    if concentration_score is not None:
        parts.append(concentration_score)
        weights.append(0.20)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def breadth_score(
    row: dict[str, Any],
    prev_row: dict[str, Any] | None,
    theme_stocks: list[dict[str, Any]],
    prev_theme_stocks: list[dict[str, Any]] | None,
) -> tuple[float | None, list[str]]:
    """宽度/结构：板块宽度、晋级率、连板梯队、龙头集中度。"""
    missing: list[str] = []
    breadth = _num(row.get("breadthScore"))
    if breadth is None:
        missing.append("breadthScore")
        return None, missing

    prev_breadth = _num(prev_row.get("breadthScore")) if prev_row else None
    breadth_change = (breadth - prev_breadth) if prev_breadth is not None else 0.0
    breadth_change_score = _clamp(50.0 + breadth_change * 4.0)

    boards = sorted(
        (int(_num(s.get("boardHeight"), 0) or 0) for s in theme_stocks),
        reverse=True,
    )
    if boards:
        max_board = boards[0]
        second_board = boards[1] if len(boards) > 1 else 0
        ladder_score = _clamp(max_board * 12.0 + max(0, max_board - second_board) * 6.0)
    else:
        missing.append("boardHeight")
        ladder_score = None

    promotion_score: float | None = None
    if prev_theme_stocks:
        prev_zt = [
            s for s in prev_theme_stocks
            if str(s.get("leadStatus") or "").strip() == "涨停" or (_num(s.get("change"), 0) or 0) >= 9.5
        ]
        continuation = [s for s in theme_stocks if int(_num(s.get("boardHeight"), 0) or 0) >= 2]
        if prev_zt:
            promotion_score = _clamp((len(continuation) / len(prev_zt)) * 150.0)
        else:
            missing.append("promotion")
    else:
        missing.append("promotion")

    stock_count = len(theme_stocks)
    leader_count = sum(1 for s in theme_stocks if str(s.get("leadStatus") or "").find("龙") >= 0)
    leader_score = _clamp((leader_count / stock_count) * 150.0) if stock_count else None
    if leader_score is None:
        missing.append("leaderCount")

    parts = [breadth, breadth_change_score]
    weights = [0.30, 0.20]
    if ladder_score is not None:
        parts.append(ladder_score)
        weights.append(0.25)
    if promotion_score is not None:
        parts.append(promotion_score)
        weights.append(0.15)
    if leader_score is not None:
        parts.append(leader_score)
        weights.append(0.10)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def crowding_score(
    row: dict[str, Any],
    crowding_series: list[float],
    theme_stocks: list[dict[str, Any]],
) -> tuple[float | None, list[str]]:
    """拥挤/风险：crowdingRisk、拥挤变化、量能高分位偏离。"""
    missing: list[str] = []
    crowding = _num(row.get("crowdingRisk"))
    if crowding is None:
        missing.append("crowdingRisk")
        return None, missing

    base = _clamp(crowding)
    if len(crowding_series) >= 2:
        change = crowding - crowding_series[-2]
    elif len(crowding_series) == 1:
        change = crowding - crowding_series[0]
    else:
        change = 0.0
    change_score = _clamp(50.0 + change * 2.0)

    ratios = sorted(_num(s.get("volumeRatio")) for s in theme_stocks if _num(s.get("volumeRatio")) is not None)
    if ratios:
        p90 = ratios[min(len(ratios) - 1, int(len(ratios) * 0.9))]
        volume_score = _clamp(p90 * 40.0)
    else:
        missing.append("volumeRatio")
        volume_score = None

    parts = [base, change_score]
    weights = [0.50, 0.30]
    if volume_score is not None:
        parts.append(volume_score)
        weights.append(0.20)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def lifecycle_score(
    prev_lifecycle: str | None,
    rank_changes: list[int],
) -> tuple[float | None, list[str]]:
    """轮动位置：状态连续性与 rank 波动。"""
    missing: list[str] = []
    if prev_lifecycle is None:
        missing.append("prevLifecycle")
        continuity = 50.0
    else:
        continuity = {"ice": 30.0, "emerging": 70.0, "expanding": 100.0, "climax": 70.0, "cooling": 30.0}.get(prev_lifecycle, 50.0)

    if rank_changes:
        mean_abs = sum(abs(r) for r in rank_changes) / len(rank_changes)
        rank_vol = _clamp(100.0 - mean_abs * 8.0)
    else:
        missing.append("rankHistory")
        rank_vol = None

    if rank_vol is None:
        return _clamp(continuity), missing
    return _clamp(continuity * 0.6 + rank_vol * 0.4), missing


def combine_scores(
    scores: ThemeFactorScoresLike,
    weights: dict[str, float],
    min_factors: int = 3,
) -> float | None:
    """按可用因子归一化权重求 rotationScore；可用因子 < min_factors 返回 None（M1 生效）。"""
    available = scores.available()
    if len(available) < min_factors:
        return None
    total_w = sum(weights[k] for k in available)
    if total_w <= 0:
        return None
    return _clamp(sum(getattr(scores, k) * weights[k] for k in available) / total_w)


from typing import Protocol


class ThemeFactorScoresLike(Protocol):
    def available(self) -> list[str]: ...
```

### 测试 `quant-board/tests/test_theme_rotation_factors.py`

```python
import math

from backend.analysis.theme_rotation.factors import (
    breadth_score,
    crowding_score,
    flow_score,
    lifecycle_score,
    linear_slope,
    robust_z,
    strength_score,
)


def _row(**overrides):
    base = {"themeId": "BKAI", "themeName": "人工智能", "heatScore": 70.0, "ztCount": 5,
            "change": 3.0, "mainNetInflow": 2.0, "breadthScore": 60.0,
            "crowdingRisk": 50.0, "rank": 1}
    base.update(overrides)
    return base


def test_linear_slope_ascending():
    assert abs(linear_slope([10.0, 20.0, 30.0]) - 10.0) < 1e-9


def test_robust_z_median_mad():
    assert abs(robust_z(60.0, [50.0, 60.0]) - 1.0) < 1e-9


def test_strength_score_high_heat():
    score, missing = strength_score(
        _row(heatScore=80.0, ztCount=6, change=5.0),
        history_heats=[60.0, 70.0],
        all_current_heats=[40.0, 80.0],
        market_change=1.0,
        prev_zt_count=3,
    )
    assert score is not None and 60 <= score <= 100
    assert "heatScore" not in missing


def test_strength_score_missing_heat_returns_none():
    score, missing = strength_score(_row(heatScore=None), [], [], 1.0, None)
    assert score is None
    assert "heatScore" in missing


def test_flow_score_missing_inflow_returns_none():
    score, missing = flow_score(_row(mainNetInflow=None), [2.0], [2.0, 3.0], 1)
    assert score is None
    assert "mainNetInflow" in missing


def test_breadth_score_promotion_degraded_when_no_history():
    score, missing = breadth_score(_row(breadthScore=70.0), None, [], None)
    assert score is not None
    assert "boardHeight" in missing
    assert "promotion" in missing


def test_breadth_score_promotion_uses_theme_scoped_denominator():
    current = [_row(breadthScore=70.0, boardHeight=2)]
    prev_theme = [
        {"code": "600001", "leadStatus": "涨停", "change": 9.6},
        {"code": "600002", "leadStatus": "", "change": 3.0},
    ]
    score, missing = breadth_score(current[0], None, current, prev_theme)
    # 主题内昨日涨停 1 只、今日连板 1 只 → 晋级率 100% → 150 上限
    assert score is not None and 100 <= score <= 150
    assert "promotion" not in missing


def test_crowding_score_missing_risk_returns_none():
    score, missing = crowding_score(_row(crowdingRisk=None), [50.0], [])
    assert score is None
    assert "crowdingRisk" in missing


def test_lifecycle_score_without_prev_is_neutral_with_flag():
    score, missing = lifecycle_score(None, [])
    assert score == 50.0
    assert "prevLifecycle" in missing
    assert "rankHistory" in missing


def test_combine_scores_min_factors_gate():
    from backend.analysis.theme_rotation.factors import combine_scores
    from backend.analysis.theme_rotation.models import ThemeFactorScores

    scores = ThemeFactorScores(theme_id="BKAI", theme_name="人工智能", strength=80.0, flow=None)
    assert combine_scores(scores, {"strength": 0.3, "flow": 0.25, "breadth": 0.2,
                                   "crowding": 0.15, "lifecycle": 0.1}) is None
    scores.breadth = 60.0
    scores.crowding = 50.0
    combined = combine_scores(scores, {"strength": 0.3, "flow": 0.25, "breadth": 0.2,
                                       "crowding": 0.15, "lifecycle": 0.1})
    assert combined is not None
```

- [ ] **Step 1**: 创建 `factors.py` 与测试文件。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_factors.py -q`，预期 10 passed。
- [ ] **Step 3**: 提交 `feat(theme-rotation): add cross-sectional and time-series factor functions`。

---

## Task 3: lifecycle.py —— 主题生命周期 / 轮动状态 / 市场阶段（纯函数）

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/lifecycle.py`
- Test: `quant-board/tests/test_theme_rotation_lifecycle.py`

### lifecycle.py（完整内容）

```python
"""主题生命周期、轮动方向与市场阶段状态机（纯函数，阈值来自 ThemeRotationConfig）。"""

from __future__ import annotations

import math
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig


def _num(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def lifecycle_for(
    row: dict[str, Any],
    prev_lifecycle: str | None,
    cfg: ThemeRotationConfig,
) -> tuple[str, list[str]]:
    """按设计 §5.1 判定主题生命周期，返回 (state, reasons)。"""
    heat = _num(row.get("heatScore"))
    momentum = _num(row.get("momentumScore"))
    crowding = _num(row.get("crowdingRisk"))
    inflow = row.get("mainNetInflow")
    positive_streak = int(_num(row.get("positiveInflowStreak"), 0))
    negative_streak = int(_num(row.get("negativeInflowStreak"), 0))
    max_board = int(_num(row.get("maxBoardHeight"), 0))
    reasons: list[str] = []

    if heat >= cfg.climax_heat and (crowding >= cfg.climax_crowding or max_board >= cfg.climax_max_board):
        reasons.append(f"heat={heat:.0f}≥{cfg.climax_heat:.0f}且拥挤≥{cfg.climax_crowding:.0f}或最高连板≥{cfg.climax_max_board}")
        state = "climax"
    elif momentum < cfg.cooling_momentum or (inflow is not None and negative_streak >= cfg.cooling_negative_inflow_streak):
        reasons.append(f"momentum={momentum:.0f}<{cfg.cooling_momentum:.0f}或连续{cfg.cooling_negative_inflow_streak}槽资金流出")
        state = "cooling"
    elif heat >= cfg.expanding_heat and crowding < cfg.climax_crowding:
        reasons.append(f"heat={heat:.0f}≥{cfg.expanding_heat:.0f}且拥挤<{cfg.climax_crowding:.0f}")
        state = "expanding"
    elif heat >= cfg.emerging_heat_min and momentum >= cfg.ice_momentum:
        reasons.append("资金由负转正，动量回暖" if positive_streak >= 1 else "heat 回到观察区间")
        state = "emerging"
    elif heat < cfg.ice_heat or momentum < cfg.ice_momentum:
        reasons.append(f"heat={heat:.0f}<{cfg.ice_heat:.0f}或momentum={momentum:.0f}<{cfg.ice_momentum:.0f}")
        state = "ice"
    else:
        reasons.append("数据不足，中性观察")
        state = "neutral"

    # 转移约束（M2/设计 §5.1）：非相邻跳变钳制到相邻中间态。
    if prev_lifecycle and state != prev_lifecycle:
        adjacency = {
            "ice": {"emerging"},
            "emerging": {"ice", "expanding", "cooling"},
            "expanding": {"emerging", "climax", "cooling"},
            "climax": {"expanding", "cooling"},
            "cooling": {"expanding", "emerging", "ice"},
            "neutral": {"ice", "emerging", "expanding"},
        }
        if prev_lifecycle not in adjacency or state not in adjacency[prev_lifecycle]:
            if state == "climax" and prev_lifecycle in {"ice", "emerging", "neutral"}:
                state, reasons = "expanding", [*reasons, "transition_clamped: ice/emerging→climax 非相邻，钳制到 expanding"]
            elif state == "ice" and prev_lifecycle in {"climax", "expanding"}:
                state, reasons = "cooling", [*reasons, "transition_clamped: climax/expanding→ice 非相邻，钳制到 cooling"]
            else:
                reasons = [*reasons, f"transition_clamped: {prev_lifecycle}→{state} 非相邻，钳制到 neutral"]
                state = "neutral"
    return state, reasons


def rotation_state_for(
    lifecycle: str,
    momentum: float,
    is_mainline: bool,
    inflow_positive: bool,
) -> str:
    """在设计 §5.2 的 lifecycle 之上叠加方向与主线性。"""
    if lifecycle == "cooling":
        return "cooling"
    if lifecycle == "emerging":
        return "emerging"
    if lifecycle == "ice":
        return "neutral"
    if lifecycle in ("expanding", "climax"):
        return "mainline" if is_mainline else "inflow"
    if momentum < 50.0:
        return "outflow"
    if inflow_positive:
        return "inflow"
    return "neutral"


def market_phase_for(
    *,
    max_board_height: int,
    rotation_speed: float | None,
    mainline_count: int,
    mainline_concentration: float | None,
    total_zt_count: int,
    cooling_theme_ratio: float | None = None,
    negative_inflow_theme_ratio: float | None = None,
    cfg: ThemeRotationConfig,
) -> str:
    """按设计 §5.3 判定市场阶段（含 cooling/neutral 兜底，审计 C4/M3）。"""
    if mainline_concentration is not None and mainline_concentration >= cfg.market_climax_min_concentration and max_board_height >= cfg.market_rising_min_board:
        return "climax"
    if max_board_height >= cfg.market_climax_max_board:
        return "climax"
    if (
        (cooling_theme_ratio is not None and cooling_theme_ratio >= cfg.market_cooling_theme_ratio)
        or (negative_inflow_theme_ratio is not None and negative_inflow_theme_ratio >= cfg.market_cooling_negative_inflow_ratio)
    ):
        return "cooling"
    if max_board_height <= cfg.market_ice_max_board and total_zt_count < cfg.market_ice_min_zt_count:
        return "ice"
    if cfg.market_rising_min_board <= max_board_height <= cfg.market_climax_max_board - 1 and mainline_count >= 1:
        return "rising"
    if rotation_speed is not None and rotation_speed >= cfg.market_chaos_min_rotation_speed and mainline_count == 0:
        return "chaos"
    if rotation_speed is not None and rotation_speed < cfg.market_neutral_max_rotation_speed and mainline_count == 0:
        return "neutral"
    return "chaos"


def rotation_speed_score(rank_changes: list[int]) -> float | None:
    """全市场 rank turnover 映射 0-100。"""
    if not rank_changes:
        return None
    mean_abs = sum(abs(r) for r in rank_changes) / len(rank_changes)
    return _clamp(mean_abs * 8.0)


def mainline_concentration(heats: list[float], top_n: int = 3) -> float | None:
    """Top-N heat 占比，区分抱团（高）与发散（低）。"""
    if not heats or sum(heats) <= 0:
        return None
    top = sorted(heats, reverse=True)[:top_n]
    return round(sum(top) / sum(heats), 4)
```

### 测试 `quant-board/tests/test_theme_rotation_lifecycle.py`

```python
from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.lifecycle import (
    lifecycle_for,
    mainline_concentration,
    market_phase_for,
    rotation_speed_score,
    rotation_state_for,
)

CFG = ThemeRotationConfig()


def _row(**overrides):
    base = {"heatScore": 70.0, "momentumScore": 60.0, "crowdingRisk": 50.0,
            "mainNetInflow": 1.0, "positiveInflowStreak": 2,
            "negativeInflowStreak": 0, "maxBoardHeight": 3}
    base.update(overrides)
    return base


def test_lifecycle_climax():
    state, reasons = lifecycle_for(_row(heatScore=85.0, crowdingRisk=80.0), "expanding", CFG)
    assert state == "climax"
    assert reasons


def test_lifecycle_cooling_by_momentum():
    state, _ = lifecycle_for(_row(momentumScore=30.0), "expanding", CFG)
    assert state == "cooling"


def test_lifecycle_cooling_by_negative_streak():
    state, _ = lifecycle_for(_row(heatScore=90.0, momentumScore=80.0, negativeInflowStreak=2), "expanding", CFG)
    assert state == "cooling"


def test_lifecycle_expanding():
    state, _ = lifecycle_for(_row(heatScore=70.0), "expanding", CFG)
    assert state == "expanding"


def test_lifecycle_emerging():
    state, _ = lifecycle_for(_row(heatScore=45.0, positiveInflowStreak=1), "ice", CFG)
    assert state == "emerging"


def test_lifecycle_ice():
    state, _ = lifecycle_for(_row(heatScore=30.0, momentumScore=30.0), "emerging", CFG)
    assert state == "ice"


def test_lifecycle_transition_clamped():
    state, reasons = lifecycle_for(_row(heatScore=85.0, crowdingRisk=80.0), "ice", CFG)
    assert state == "expanding"
    assert any("transition_clamped" in reason for reason in reasons)


def test_rotation_state_mainline():
    assert rotation_state_for("expanding", 70.0, True, True) == "mainline"
    assert rotation_state_for("cooling", 20.0, True, False) == "cooling"
    assert rotation_state_for("expanding", 70.0, False, True) == "inflow"
    assert rotation_state_for("neutral", 45.0, False, False) == "outflow"


def test_market_phase():
    assert market_phase_for(max_board_height=8, rotation_speed=30.0, mainline_count=2,
                            mainline_concentration=0.5, total_zt_count=60, cfg=CFG) == "rising"
    assert market_phase_for(max_board_height=2, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=10, cfg=CFG) == "ice"
    assert market_phase_for(max_board_height=11, rotation_speed=70.0, mainline_count=1,
                            mainline_concentration=0.7, total_zt_count=80, cfg=CFG) == "climax"
    assert market_phase_for(max_board_height=5, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=50,
                            cooling_theme_ratio=0.4, cfg=CFG) == "cooling"
    assert market_phase_for(max_board_height=5, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=50, cfg=CFG) == "neutral"


def test_rotation_speed_and_concentration():
    assert rotation_speed_score([3, -3, 4]) == 8 * (10 / 3)
    assert mainline_concentration([90.0, 10.0], 1) == 0.9
    assert mainline_concentration([]) is None
```

- [ ] **Step 1**: 创建 `lifecycle.py` 与测试文件。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_lifecycle.py -q`，预期 11 passed。
- [ ] **Step 3**: 提交 `feat(theme-rotation): add lifecycle and market phase state machine`。

---

## Task 4: engine.py —— 组合引擎（无 I/O）

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/engine.py`（替换 Task 1 的占位）
- Test: `quant-board/tests/test_theme_rotation_engine.py`

### engine.py（完整内容）

```python
"""组合引擎：把当前槽 + 历史槽位计算为 ThemeRotationResult（无 I/O）。"""

from __future__ import annotations

import math
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.factors import (
    breadth_score,
    combine_scores,
    crowding_score,
    flow_score,
    lifecycle_score,
    robust_z,
    strength_score,
)
from backend.analysis.theme_rotation.lifecycle import (
    lifecycle_for,
    mainline_concentration,
    market_phase_for,
    rotation_speed_score,
    rotation_state_for,
)
from backend.analysis.theme_rotation.models import (
    HistorySlot,
    MarketRotationSummary,
    ThemeFactorScores,
    ThemeRotationResult,
    ThemeRotationStatus,
)


def _theme_key(row: dict[str, Any]) -> str:
    return str(
        row.get("themeId")
        or row.get("entityKey")
        or row.get("id")
        or row.get("themeName")
        or row.get("entityName")
        or ""
    ).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _market_change(indices: dict[str, Any] | None) -> float | None:
    if not isinstance(indices, dict):
        return None
    changes = [_num(v.get("change")) for v in indices.values() if isinstance(v, dict) and _num(v.get("change")) is not None]
    if not changes:
        return None
    return sum(changes) / len(changes)


def _normalize_theme_label(value: str) -> str:
    """与 projection._normalize_theme_label 同口径：去掉概念/板块后缀（9.3-③ 归一化）。"""
    text = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _stock_theme_labels(stock: dict[str, Any]) -> list[str]:
    """从 stock rows 的 themes 列表 + mainTheme 提取归一化题材标签（无 themeIds 的替代）。"""
    labels: list[str] = []
    raw = stock.get("themes")
    if isinstance(raw, list):
        labels.extend(str(item) for item in raw)
    main_theme = str(stock.get("mainTheme") or "")
    if main_theme and main_theme not in labels:
        labels.append(main_theme)
    return [_normalize_theme_label(label) for label in labels if str(label).strip()]


def _filter_theme_stocks(
    rows: list[dict[str, Any]] | None,
    key: str,
    name: str,
) -> list[dict[str, Any]] | None:
    """把上一槽股票按主题过滤（晋级率分母为主题内昨日涨停，审计 9.5）。"""
    if not rows:
        return None
    wanted = {_normalize_theme_label(key), _normalize_theme_label(name)}
    return [stock for stock in rows if wanted & set(_stock_theme_labels(stock))]


class ThemeRotationEngine:
    """跨槽位序列计算轮动状态；历史不足或字段缺失时输出 None + reasons，不伪造。"""

    def __init__(self, config: ThemeRotationConfig | None = None) -> None:
        self.config = config or ThemeRotationConfig()

    def compute(
        self,
        current_sector_rows: list[dict[str, Any]],
        history_slots: list[HistorySlot],
        current_stock_rows: list[dict[str, Any]],
        indices: dict[str, Any] | None = None,
        computed_at: int = 0,
        trading_date: str | None = None,
    ) -> ThemeRotationResult:
        cfg = self.config
        quality_issues: list[str] = []
        if len(history_slots) + 1 < cfg.min_slots_for_state:
            quality_issues.append(
                f"insufficient_history: 当前1槽+历史{len(history_slots)}槽<{cfg.min_slots_for_state}槽，不输出轮动状态"
            )

        # ── 汇总历史序列（按主题） ──────────────────────────────────────
        histories: dict[str, dict[str, Any]] = {}  # key -> {heats, inflows, crowdings, ranks, prev_row, prev_lifecycle, prev_slot_stocks}
        ordered_slots = sorted(history_slots, key=lambda s: s.timestamp_ms)
        for slot in ordered_slots:
            for row in slot.sector_rows:
                key = _theme_key(row)
                bucket = histories.setdefault(key, {
                    "heats": [], "inflows": [], "crowdings": [], "ranks": [],
                    "prev_row": None, "prev_lifecycle": None, "prev_slot_stocks": None,
                })
                heat = _num(row.get("heatScore"))
                if heat is not None:
                    bucket["heats"].append(heat)
                inflow = _num(row.get("mainNetInflow"))
                if inflow is not None:
                    bucket["inflows"].append(inflow)
                crowding = _num(row.get("crowdingRisk"))
                if crowding is not None:
                    bucket["crowdings"].append(crowding)
                rank = _num(row.get("rank"))
                if rank is not None:
                    bucket["ranks"].append(int(rank))
                bucket["prev_row"] = row
                bucket["prev_lifecycle"] = str(row.get("lifecycle") or "") or None
                bucket["prev_slot_stocks"] = slot.stock_rows

        # ── 截面参照 ────────────────────────────────────────────────────
        all_heats = [_num(r.get("heatScore")) for r in current_sector_rows if _num(r.get("heatScore")) is not None]
        all_inflows = [_num(r.get("mainNetInflow")) for r in current_sector_rows if _num(r.get("mainNetInflow")) is not None]
        market_change = _market_change(indices)
        stock_by_theme: dict[str, list[dict[str, Any]]] = {}
        for stock in current_stock_rows:
            for label in _stock_theme_labels(stock):
                stock_by_theme.setdefault(label, []).append(stock)

        statuses: list[ThemeRotationStatus] = []
        rank_changes: list[int] = []
        for row in sorted(current_sector_rows, key=lambda r: int(_num(r.get("rank"), 999999) or 999999)):
            key = _theme_key(row)
            name = str(row.get("themeName") or row.get("entityName") or key)
            hist = histories.get(key, {
                "heats": [], "inflows": [], "crowdings": [], "ranks": [],
                "prev_row": None, "prev_lifecycle": None, "prev_slot_stocks": None,
            })
            theme_stocks = (
                stock_by_theme.get(_normalize_theme_label(key))
                or stock_by_theme.get(_normalize_theme_label(name))
                or []
            )

            current_inflow = _num(row.get("mainNetInflow"))
            streak_series = [*hist["inflows"], current_inflow] if current_inflow is not None else hist["inflows"]
            positive_streak, negative_streak = _inflow_streaks(streak_series)

            strength, s_missing = strength_score(
                row, hist["heats"], all_heats, market_change,
                _num(hist["prev_row"].get("ztCount")) if hist["prev_row"] else None,
            )
            flow, f_missing = flow_score(
                row, hist["inflows"], all_inflows, positive_streak,
            )
            prev_theme_stocks = _filter_theme_stocks(hist["prev_slot_stocks"], key, name)
            breadth, b_missing = breadth_score(
                row, hist["prev_row"], theme_stocks, prev_theme_stocks,
            )
            crowding, c_missing = crowding_score(row, hist["crowdings"], theme_stocks)
            lifecycle, l_missing = lifecycle_score(
                hist["prev_lifecycle"],
                [int(_num(r.get("rank"), 0) or 0) - int(_num(row.get("rank"), 0) or 0) for r in [hist["prev_row"]] if hist["prev_row"]],
            )

            scores = ThemeFactorScores(
                theme_id=key,
                theme_name=name,
                strength=round(strength, 2) if strength is not None else None,
                flow=round(flow, 2) if flow is not None else None,
                breadth=round(breadth, 2) if breadth is not None else None,
                crowding=round(crowding, 2) if crowding is not None else None,
                lifecycle=round(lifecycle, 2) if lifecycle is not None else None,
                missing=s_missing + f_missing + b_missing + c_missing + l_missing,
            )
            rotation_score = combine_scores(scores, cfg.weights, cfg.min_factors_for_score)

            enough_history = (len(hist["heats"]) + 1) >= cfg.min_slots_for_state
            prev_lifecycle = hist["prev_lifecycle"]
            if enough_history:
                theme_max_board = max(
                    (int(_num(s.get("boardHeight"), 0) or 0) for s in theme_stocks),
                    default=0,
                )
                lifecycle_row = {
                    **row,
                    "positiveInflowStreak": positive_streak,
                    "negativeInflowStreak": negative_streak,
                    "maxBoardHeight": theme_max_board,
                }
                lifecycle_state, life_reasons = lifecycle_for(lifecycle_row, prev_lifecycle, cfg)
            else:
                lifecycle_state = None
                life_reasons = ["历史不足，不判定生命周期"]

            rank = int(_num(row.get("rank"), len(statuses) + 1) or (len(statuses) + 1))
            prev_rank = int(_num(hist["prev_row"].get("rank"), 0) or 0) if hist["prev_row"] else 0
            rank_change = (prev_rank - rank) if prev_rank else 0
            rank_changes.append(rank_change)

            heat_trend = round(linear_slope_heat(hist["heats"], _num(row.get("heatScore"))), 2) if enough_history else None
            flow_trend = round(flow_summary(hist["inflows"], _num(row.get("mainNetInflow"))), 2) if hist["inflows"] else None
            breadth_trend = round(breadth_trend_value(hist["prev_row"], row), 2) if hist["prev_row"] else None
            crowding_trend = round(crowding_trend_value(hist["crowdings"], _num(row.get("crowdingRisk"))), 2) if hist["crowdings"] else None

            status = ThemeRotationStatus(
                theme_id=key,
                theme_name=name,
                rotation_state=None,
                lifecycle=lifecycle_state,
                rotation_score=round(rotation_score, 1) if rotation_score is not None else None,
                rank=rank,
                rank_change=rank_change,
                heat_trend=heat_trend,
                flow_trend=flow_trend,
                breadth_trend=breadth_trend,
                crowding_trend=crowding_trend,
                reasons=life_reasons,
                factor_breakdown={
                    "strength": scores.strength,
                    "flow": scores.flow,
                    "breadth": scores.breadth,
                    "crowding": scores.crowding,
                    "lifecycle": scores.lifecycle,
                },
                quality_flags=sorted(set(scores.missing)),
            )
            statuses.append(status)

        # ── 主线判定（设计 §5.2：横向 z-score Top3 且 资金集中度 Top3） ──
        theme_rows = {_theme_key(r): r for r in current_sector_rows}
        heat_zs = {key: robust_z(_num(r.get("heatScore"), 0.0), all_heats) for key, r in theme_rows.items()}
        z_rank = {
            key: index
            for index, (key, _) in enumerate(
                sorted(heat_zs.items(), key=lambda kv: -kv[1]), start=1
            )
        }
        positive_total = sum(v for v in all_inflows if v and v > 0)
        inflow_share = {
            key: (_num(r.get("mainNetInflow"), 0.0) / positive_total)
            for key, r in theme_rows.items()
        } if positive_total > 0 else {}
        conc_rank = {
            key: index
            for index, (key, _) in enumerate(
                sorted(inflow_share.items(), key=lambda kv: -kv[1]), start=1
            )
        }
        mainline_candidates = [
            s for s in statuses
            if s.lifecycle in ("expanding", "climax")
            and s.rotation_score is not None
            and z_rank.get(s.theme_id, 999) <= cfg.min_mainline_z_rank
            and conc_rank.get(s.theme_id, 999) <= cfg.min_mainline_concentration_rank
        ]
        mainline_candidates.sort(key=lambda s: -(s.rotation_score or 0))
        mainline_keys = {s.theme_id for s in mainline_candidates[: cfg.mainline_top_n]}
        for status in statuses:
            if status.lifecycle not in ("expanding", "climax"):
                continue
            is_mainline = status.theme_id in mainline_keys
            status.mainline_concentration_rank = conc_rank.get(status.theme_id)
            status.rotation_state = rotation_state_for(
                status.lifecycle or "neutral",
                _num(_row_for(current_sector_rows, status.theme_id).get("momentumScore")) if _row_for(current_sector_rows, status.theme_id) else 50.0,
                is_mainline,
                (_num(_row_for(current_sector_rows, status.theme_id).get("mainNetInflow"), 0) or 0) > 0,
            )
        for status in statuses:
            if status.rotation_state is not None or status.lifecycle is None:
                continue
            row = _row_for(current_sector_rows, status.theme_id) or {}
            status.rotation_state = rotation_state_for(
                status.lifecycle or "neutral",
                _num(row.get("momentumScore"), 50.0),
                False,
                (_num(row.get("mainNetInflow"), 0) or 0) > 0,
            )

        # ── 市场摘要 ────────────────────────────────────────────────────
        max_board = max(
            (int(_num(s.get("boardHeight"), 0) or 0) for s in current_stock_rows),
            default=0,
        )
        total_zt = sum(int(_num(r.get("ztCount"), 0) or 0) for r in current_sector_rows)
        speed = rotation_speed_score(rank_changes) if rank_changes else None
        concentration = mainline_concentration(all_heats, cfg.mainline_top_n) if all_heats else None
        cooling_count = sum(1 for s in statuses if s.rotation_state == "cooling")
        cooling_theme_ratio = cooling_count / len(statuses) if statuses else None
        negative_inflow_count = sum(1 for r in current_sector_rows if (_num(r.get("mainNetInflow")) or 0) < 0)
        negative_inflow_theme_ratio = (
            negative_inflow_count / len(current_sector_rows) if current_sector_rows else None
        )
        market_phase = (
            market_phase_for(
                max_board_height=max_board,
                rotation_speed=speed,
                mainline_count=len([s for s in statuses if s.rotation_state == "mainline"]),
                mainline_concentration=concentration,
                total_zt_count=total_zt,
                cooling_theme_ratio=cooling_theme_ratio,
                negative_inflow_theme_ratio=negative_inflow_theme_ratio,
                cfg=cfg,
            )
            if enough_history_market(ordered_slots, cfg)
            else "unknown"
        )

        mainlines = [
            {
                "themeId": s.theme_id,
                "themeName": s.theme_name,
                "rotationScore": s.rotation_score,
                "rotationState": s.rotation_state,
                "rankChange": s.rank_change,
            }
            for s in statuses
            if s.rotation_state == "mainline"
        ]
        summary = MarketRotationSummary(
            market_phase=market_phase,
            rotation_speed=speed,
            mainline_concentration=concentration,
            max_board_height=max_board,
            main_lines=mainlines,
            inflow_themes=[s.theme_id for s in statuses if s.rotation_state == "inflow"],
            outflow_themes=[s.theme_id for s in statuses if s.rotation_state in ("outflow", "cooling")],
            suggestion=_suggestion_for(market_phase, mainlines),
            computed_at=computed_at,
            algorithm_version=cfg.algorithm_version,
            evidence={
                "framesUsed": len(ordered_slots) + 1,
                "qualityIssues": quality_issues,
                "historyLagSlots": 1,
                "crossDayBaseline": bool(
                    ordered_slots and any(s.trading_date != trading_date for s in ordered_slots)
                ),
            },
        )
        return ThemeRotationResult(
            statuses=statuses,
            market=summary,
            quality_issues=quality_issues,
            frames_used=len(ordered_slots) + 1,
        )


def _row_for(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for row in rows:
        if _theme_key(row) == key:
            return row
    return None


def _inflow_streaks(series: list[float]) -> tuple[int, int]:
    """从序列尾部数连续正/负净流入（不可同时为两者）。"""
    positive = 0
    negative = 0
    for value in reversed(series):
        if value > 0:
            if negative:
                break
            positive += 1
        elif value < 0:
            if positive:
                break
            negative += 1
        else:
            break
    return positive, negative


def linear_slope_heat(history: list[float], current: float | None) -> float | None:
    from backend.analysis.theme_rotation.factors import linear_slope
    if current is None:
        return None
    return linear_slope([*history, current])


def flow_summary(inflows: list[float], current: float | None) -> float | None:
    if current is None:
        return None
    series = [*inflows, current]
    return round(sum(series[-3:]) / len(series[-3:]), 4) if series else None


def breadth_trend_value(prev: dict[str, Any] | None, row: dict[str, Any]) -> float | None:
    from backend.analysis.theme_rotation.factors import _num
    if prev is None:
        return None
    p = _num(prev.get("breadthScore"))
    c = _num(row.get("breadthScore"))
    if p is None or c is None:
        return None
    return round(c - p, 2)


def crowding_trend_value(history: list[float], current: float | None) -> float | None:
    if current is None:
        return None
    return round(current - history[-1], 2) if history else None


def enough_history_market(ordered_slots: list[HistorySlot], cfg: ThemeRotationConfig) -> bool:
    return (len(ordered_slots) + 1) >= cfg.min_slots_for_state


def _suggestion_for(market_phase: str, mainlines: list[dict[str, Any]]) -> str:
    base = {
        "ice": "冰点期：等待题材企稳",
        "chaos": "混沌轮动期：控制仓位，观察资金方向",
        "rising": "主线上升期：跟踪主线题材",
        "climax": "高潮期：注意拥挤和分化",
        "cooling": "退潮期：规避降温题材",
        "unknown": "历史不足：暂不判定市场阶段",
    }
    names = "、".join(m["themeName"] for m in mainlines[:3])
    return f"{base.get(market_phase, '')} 主线：{names}" if names else base.get(market_phase, "")
```

### 测试 `quant-board/tests/test_theme_rotation_engine.py`

```python
from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.models import HistorySlot


def _sector(theme_id, name, rank, heat, momentum=60, crowding=50, inflow=1.0, zt=3, change=2.0, breadth=60):
    return {
        "themeId": theme_id, "themeName": name, "entityKey": theme_id, "rank": rank,
        "heatScore": heat, "momentumScore": momentum, "crowdingRisk": crowding,
        "mainNetInflow": inflow, "positiveInflowStreak": 2, "negativeInflowStreak": 0,
        "ztCount": zt, "change": change, "breadthScore": breadth, "maxBoardHeight": 2,
    }


def _stock(code, board_height, lead_status, themes, change=9.6):
    return {"code": code, "boardHeight": board_height, "leadStatus": lead_status,
            "themes": themes, "change": change}


def _history(timestamps=(1000, 2000), heat=50.0):
    return [
        HistorySlot(
            timestamp_ms=ts,
            trading_date="2026-08-04",
            sector_rows=[
                _sector("BKAI", "人工智能", 2, heat, inflow=1.0),
                _sector("BKAG", "机器人", 3, heat - 10, inflow=0.5),
            ],
        )
        for ts in timestamps
    ]


def test_engine_insufficient_history_no_state():
    engine = ThemeRotationEngine()
    result = engine.compute(
        [_sector("BKAI", "人工智能", 1, 80.0)],
        [],
        [],
        computed_at=3000,
    )
    assert result.statuses[0].rotation_state is None
    assert result.statuses[0].lifecycle is None
    assert any("insufficient_history" in q for q in result.quality_issues)


def test_engine_sufficient_history_mainline():
    engine = ThemeRotationEngine()
    current = [
        _sector("BKAI", "人工智能", 1, 85.0, momentum=80, crowding=70, inflow=3.0, zt=8),
        _sector("BKAG", "机器人", 2, 45.0, momentum=45, inflow=-1.0, zt=1),
    ]
    stocks = [
        _stock("600001", 8, "涨停", ["BKAI"]),
        _stock("600002", 2, "", ["BKAG"]),
    ]
    result = engine.compute(current, _history(), stocks, indices={}, computed_at=3000)
    by_key = {s.theme_id: s for s in result.statuses}
    assert by_key["BKAI"].lifecycle == "climax"
    assert by_key["BKAI"].rotation_state == "mainline"
    assert by_key["BKAI"].mainline_concentration_rank == 1
    assert by_key["BKAG"].rotation_state == "emerging"
    assert result.market.mainline_concentration is not None
    assert result.market.evidence["framesUsed"] == 3


def test_engine_rotation_score_present():
    engine = ThemeRotationEngine()
    result = engine.compute(
        [_sector("BKAI", "人工智能", 1, 80.0)],
        _history(),
        [_stock("600001", 3, "涨停", ["BKAI"])],
        indices={"sh000001": {"change": 1.0}},
        computed_at=3000,
    )
    assert result.statuses[0].rotation_score is not None
    assert result.market.rotation_speed == 8
    assert result.market.market_phase != "unknown"
```

- [ ] **Step 1**: 用上方 `engine.py` 替换占位实现，创建测试文件。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_engine.py -q`，预期 3 passed。
- [ ] **Step 3**: 提交 `feat(theme-rotation): add composition engine over slot history`。

> 说明（H6 修订）：`positiveInflowStreak`/`negativeInflowStreak` 由 engine 从历史 inflow 序列计算
> （`_inflow_streaks`）后传入 `flow_score` 与 `lifecycle_for`，不依赖 sector row 字段（该字段无生产者）；
> `maxBoardHeight` 由 engine 从当前槽主题内股票 boardHeight 计算。

---

## Task 5: history.py + repository port 扩展（历史读取）

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/history.py`
- Modify: `quant-board/backend/snapshot_collector/repository_port.py`
- Modify: `quant-board/backend/snapshot_collector/service_factory.py`
- Test: `quant-board/tests/test_theme_rotation_history.py`

### repository_port.py 增加协议方法（追加到 `SnapshotRepository`）

```python
    def list_snapshot_sector_rows(
        self,
        dataset_id: str,
        snapshot_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        entity_type: str | None = None,
        sort: str = "asc",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """返回 ``{"rows": [...], "source": "mongodb"}``，行按 timestamp 升序。"""
        ...

    def list_snapshot_stock_rows(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
        slot_time: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sort: str = "asc",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """返回 ``{"rows": [...], "source": "mongodb"}``。"""
        ...
```

### service_factory.py `_MongoSnapshotCollectorRepository` 实现

```python
    def list_snapshot_sector_rows(
        self,
        dataset_id: str,
        snapshot_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        entity_type: str | None = None,
        sort: str = "asc",
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._mongo.list_snapshot_sector_rows(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=start_date,
            end_date=end_date,
            entity_type=entity_type,
            sort=sort,
            limit=limit,
        )

    def list_snapshot_stock_rows(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
        slot_time: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sort: str = "asc",
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._mongo.list_snapshot_stock_rows(
            dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            slot_time=slot_time,
            start_date=start_date,
            end_date=end_date,
            sort=sort,
            limit=limit,
        )
```

> 已核对（2026-08-04）：`mongo_repository.list_snapshot_stock_rows` 支持 `trading_date/slot_time/start_date/end_date/sort/limit`；`list_snapshot_sector_rows` 支持 `start_date/end_date/entity_type/sort/limit`，与上述透传一致。

### history.py（完整内容）

```python
"""历史槽位读取：从 MongoDB 加载当前槽之前的最近 N 个槽（sector rows + 最近槽 stock rows）。"""

from __future__ import annotations

import datetime
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.models import HistorySlot, RotationHistory
from backend.snapshot_collector.trading_calendar import is_trading_day


def previous_trading_day(value: str) -> str:
    """返回 *value*（YYYY-MM-DD）之前最近的交易日（审计 H1 跨日基线）。"""
    current = datetime.date.fromisoformat(value)
    probe = current - datetime.timedelta(days=1)
    while not is_trading_day(probe.isoformat()):
        probe -= datetime.timedelta(days=1)
    return probe.isoformat()


class RotationHistoryService:
    """有 I/O 的历史读取；repo 实现 SnapshotRepository 协议（测试可注入 fake）。"""

    def __init__(
        self,
        repo: Any,
        config: ThemeRotationConfig | None = None,
        previous_trading_day_fn: Any = None,
    ) -> None:
        self._repo = repo
        self.config = config or ThemeRotationConfig()
        self._previous_trading_day = previous_trading_day_fn or previous_trading_day

    def load(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        current_timestamp_ms: int,
        window: int | None = None,
    ) -> RotationHistory:
        window = window or self.config.window_slots
        end_date = trading_date
        start_date = self._previous_trading_day(trading_date)  # 跨日基线（H1）
        sector_result = self._repo.list_snapshot_sector_rows(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=start_date,
            end_date=end_date,
            entity_type="hot_theme",
            sort="asc",
            limit=None,  # 日期范围有界，不做行数截断（M4）
        )
        rows = sector_result.get("rows") or []
        slots_by_ts: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            ts = int(row.get("timestamp") or 0)
            if ts <= 0 or ts >= current_timestamp_ms:
                continue
            slots_by_ts.setdefault(ts, []).append(row)
        ordered = sorted(slots_by_ts.items())[-window:]

        stock_rows = None
        if ordered:
            last_slot_rows = ordered[-1][1]
            last_slot = last_slot_rows[0]
            stock_result = self._repo.list_snapshot_stock_rows(
                dataset_id,
                snapshot_type=snapshot_type,
                trading_date=str(last_slot.get("tradingDate") or trading_date),
                slot_time=str(last_slot.get("slotTime") or ""),
                sort="asc",
                limit=None,
            )
            stock_rows = stock_result.get("rows") or []

        slots: list[HistorySlot] = []
        for index, (ts, slot_rows) in enumerate(ordered):
            is_last = index == len(ordered) - 1
            slots.append(
                HistorySlot(
                    timestamp_ms=ts,
                    trading_date=str(slot_rows[0].get("tradingDate") or ""),
                    sector_rows=slot_rows,
                    stock_rows=stock_rows if is_last else None,
                )
            )
        return RotationHistory(slots=slots, source=str(sector_result.get("source") or "mongodb"))
```

### 测试 `quant-board/tests/test_theme_rotation_history.py`

```python
from backend.analysis.theme_rotation.history import RotationHistoryService


class FakeRepo:
    def __init__(self, sector_rows, stock_rows):
        self._sector = sector_rows
        self._stock = stock_rows

    def list_snapshot_sector_rows(self, dataset_id, snapshot_type, start_date=None, end_date=None,
                                  entity_type=None, sort="asc", limit=None):
        return {"rows": self._sector, "source": "fake"}

    def list_snapshot_stock_rows(self, dataset_id, snapshot_type, trading_date=None, slot_time=None,
                                 start_date=None, end_date=None, sort="asc", limit=None):
        rows = self._stock
        if slot_time:
            rows = [row for row in rows if row.get("slotTime") == slot_time]
        return {"rows": rows, "source": "fake"}


def _sector(ts, key="BKAI", heat=60):
    return {"timestamp": ts, "slotTime": f"slot{ts}", "tradingDate": "2026-08-04", "entityKey": key,
            "entityType": "hot_theme", "themeId": key, "heatScore": heat, "rank": 1}


def _stock(ts, code="600001"):
    return {"timestamp": ts, "slotTime": f"slot{ts}", "tradingDate": "2026-08-04", "code": code, "boardHeight": 3}


def test_load_filters_current_and_orders():
    repo = FakeRepo(
        [_sector(1000), _sector(2000), _sector(3000)],
        [_stock(1000), _stock(2000)],
    )
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 3000, window=8)
    assert [s.timestamp_ms for s in history.slots] == [1000, 2000]
    assert history.slots[0].stock_rows is None
    assert history.slots[1].stock_rows == [_stock(2000)]


def test_load_window_caps_slots():
    repo = FakeRepo([_sector(1000 + i * 100) for i in range(12)], [])
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 999999, window=4)
    assert len(history.slots) == 4


def test_load_no_history():
    repo = FakeRepo([], [])
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 3000)
    assert history.slots == []
```

- [ ] **Step 1**: 先核对 `mongo_repository.list_snapshot_stock_rows` 实际签名；不一致则调整 service_factory 调用。
- [ ] **Step 2**: 创建 `history.py`、修改 port 与 factory、创建测试。
- [ ] **Step 3**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_history.py -q`，预期 3 passed；再运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_snapshot_collector_service.py -q` 确认 port 扩展未破坏现有 fake。
- [ ] **Step 4**: 提交 `feat(theme-rotation): add history slot loader and repository port methods`。

---

## Task 6: 采集主链接入（service.enrich + _persist_one 注入）

**Files:**
- Create: `quant-board/backend/analysis/theme_rotation/service.py`
- Modify: `quant-board/backend/snapshot_collector/service.py`
- Test: `quant-board/tests/test_theme_rotation_service.py`、`quant-board/tests/test_theme_rotation_collector_integration.py`

### service.py（完整内容）

```python
"""轮动运行时服务：历史读取 → 引擎计算 → 写入 sector_rows/frame（I/O 走 to_thread）。"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.history import RotationHistoryService
from backend.snapshot_derivation.models import SnapshotBundle


class ThemeRotationService:
    """把轮动结果写入 SnapshotBundle（派生后的 sector_rows/frames），异常不阻断入库。"""

    def __init__(
        self,
        repo: Any,
        config: ThemeRotationConfig | None = None,
        engine: ThemeRotationEngine | None = None,
        previous_trading_day_fn: Any = None,
    ) -> None:
        self.config = config or ThemeRotationConfig()
        self._history = RotationHistoryService(repo, self.config, previous_trading_day_fn)
        self._engine = engine or ThemeRotationEngine(self.config)

    async def enrich_bundle(
        self,
        bundle: SnapshotBundle,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        slot_timestamp_ms: int,
        computed_at: int,
    ) -> None:
        """加载历史、计算轮动、就地修改 bundle.sector_rows 与 bundle.frames。"""
        try:
            if not bundle.sector_rows:
                # 9.6-⑤：theme_heat 全源不可用 → sectors=[]，显式标注而非静默
                self._record_issue(bundle, "theme_rotation_no_sector_input: sectors empty")
                return
            history = await asyncio.to_thread(
                self._history.load,
                dataset_id,
                snapshot_type,
                trading_date,
                slot_timestamp_ms,
            )
            current_sector_rows = list(bundle.sector_rows)
            current_stock_rows = list(bundle.stock_rows)
            frame = (bundle.frames or [{}])[0]
            indices = frame.get("indices") if isinstance(frame, dict) else None
            result = self._engine.compute(
                current_sector_rows,
                history.slots,
                current_stock_rows,
                indices=indices,
                computed_at=computed_at,
                trading_date=trading_date,
            )
            self._apply(result, bundle)
        except Exception as exc:  # fail-visible：轮动失败不得阻断快照入库
            self._record_issue(bundle, f"theme_rotation_failed: {type(exc).__name__}: {exc}")

    def _apply(self, result, bundle: SnapshotBundle) -> None:
        from backend.analysis.theme_rotation.engine import _theme_key

        status_by_key = {s.theme_id: s for s in result.statuses}
        for row in bundle.sector_rows:
            status = status_by_key.get(_theme_key(row))
            if status is None:
                continue
            # M12：仅在引擎有明确判定时覆盖，避免把前端透传值覆成 None
            if status.rotation_state is not None:
                row["rotationState"] = status.rotation_state
            else:
                flags = list(row.get("qualityFlags") or [])
                if "rotation_history_insufficient" not in flags:
                    flags.append("rotation_history_insufficient")
                row["qualityFlags"] = flags
            if status.lifecycle is not None:
                row["lifecycle"] = status.lifecycle
            if status.rotation_score is not None:
                row["rotationScore"] = status.rotation_score
            row["heatTrend"] = status.heat_trend
            row["flowTrend"] = status.flow_trend
            row["breadthTrend"] = status.breadth_trend
            row["crowdingTrend"] = status.crowding_trend
            row["rankChange"] = status.rank_change
            row["mainlineConcentrationRank"] = status.mainline_concentration_rank
            row["reasons"] = status.reasons
            row["factorBreakdown"] = status.factor_breakdown
            flags = list(row.get("qualityFlags") or [])
            for flag in status.quality_flags:
                if flag not in flags:
                    flags.append(flag)
            row["qualityFlags"] = flags

        for frame in bundle.frames:
            # C1：必须 camelCase 落库（消费端/历史旧行均为 camelCase）
            # L5：只覆盖 frame 顶层 rotationSummary，不动 themeContext.rotationAnalysis（迁移期兼容）
            frame["rotationSummary"] = result.market.to_camel_dict()

        derivation = self._derivation_meta(bundle, result)
        for frame in bundle.frames:
            metadata = dict(frame.get("metadata") or {})
            derivation_meta = dict(metadata.get("derivation") or {})
            derivation_meta["algorithmVersion"] = self.config.algorithm_version
            derivation_meta["rotationEvidence"] = derivation
            metadata["derivation"] = derivation_meta
            frame["metadata"] = metadata

    @staticmethod
    def _derivation_meta(bundle: SnapshotBundle, result) -> dict[str, Any]:
        return {
            "framesUsed": result.frames_used,
            "marketPhase": result.market.market_phase,
            "qualityIssues": list(result.quality_issues),
        }

    @staticmethod
    def _record_issue(bundle: SnapshotBundle, message: str) -> None:
        for frame in bundle.frames:
            metadata = dict(frame.get("metadata") or {})
            derivation_meta = dict(metadata.get("derivation") or {})
            issues = list(derivation_meta.get("qualityIssues") or [])
            issues.append(message)
            derivation_meta["qualityIssues"] = issues
            metadata["derivation"] = derivation_meta
            frame["metadata"] = metadata
```

> `SnapshotBundle` 与 `MarketRotationSummary` 的 dataclass 为 `dict` 互转：`dict(result.market.__dict__)` 可序列化（`evidence` 为 dict、`main_lines` 为 list[dict]，无 dataclass 嵌套问题）。

### snapshot_collector/service.py 注入

1. `__init__` 增加参数：

```python
        theme_rotation_service: Any = None,
```

并在 `__init__` 尾部赋值 `self._theme_rotation_service = theme_rotation_service`。

2. `_persist_one` 中 `derived = SnapshotDerivationService().derive(fact)` 之后、`bundle = derived.to_ingest_bundle()` 之前插入：

```python
        if self._theme_rotation_service is not None:
            await self._theme_rotation_service.enrich_bundle(
                derived,
                dataset_id=dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                slot_timestamp_ms=slot_timestamp,
                computed_at=actual_ts,
            )
```

3. `service_factory.create_snapshot_collector_service` 在构造时传入真实 `ThemeRotationService`（懒加载，避免导入环：在函数内 `from backend.analysis.theme_rotation.service import ThemeRotationService`）。

### 测试 `quant-board/tests/test_theme_rotation_service.py`

```python
import pytest

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.service import ThemeRotationService
from backend.snapshot_derivation.models import SnapshotBundle


class FakeRepo:
    def list_snapshot_sector_rows(self, **kwargs):
        return {
            "rows": [
                {"timestamp": 1000, "tradingDate": "2026-08-04", "entityKey": "BKAI", "themeId": "BKAI",
                 "themeName": "人工智能", "heatScore": 60.0, "momentumScore": 55.0, "crowdingRisk": 40.0,
                 "mainNetInflow": 1.0, "rank": 1},
                {"timestamp": 2000, "tradingDate": "2026-08-04", "entityKey": "BKAI", "themeId": "BKAI",
                 "themeName": "人工智能", "heatScore": 65.0, "momentumScore": 60.0, "crowdingRisk": 45.0,
                 "mainNetInflow": 1.5, "rank": 1},
            ],
            "source": "fake",
        }

    def list_snapshot_stock_rows(self, **kwargs):
        return {"rows": [], "source": "fake"}


@pytest.mark.asyncio
async def test_enrich_writes_rotation_fields():
    bundle = SnapshotBundle(
        frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "indices": {}, "metadata": {}}],
        sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "themeName": "人工智能", "rank": 1,
                      "heatScore": 80.0, "momentumScore": 70.0, "crowdingRisk": 50.0,
                      "mainNetInflow": 2.0, "positiveInflowStreak": 2, "negativeInflowStreak": 0,
                      "ztCount": 5, "change": 3.0, "breadthScore": 60.0}],
        stock_rows=[],
    )
    svc = ThemeRotationService(FakeRepo(), previous_trading_day_fn=lambda date: "2026-08-03")
    await svc.enrich_bundle(
        bundle,
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-08-04",
        slot_timestamp_ms=3000,
        computed_at=3000,
    )
    row = bundle.sector_rows[0]
    assert row.get("rotationState") is not None  # 3 槽历史足够，输出真实状态
    assert "rotation_history_insufficient" not in (row.get("qualityFlags") or [])
    assert "reasons" in row
    assert bundle.frames[0]["rotationSummary"]["algorithmVersion"] == "theme_rotation_v2"


@pytest.mark.asyncio
async def test_enrich_engine_failure_does_not_block_save():
    class BoomEngine(ThemeRotationEngine):
        def compute(self, *args, **kwargs):
            raise RuntimeError("boom")

    bundle = SnapshotBundle(
        frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "metadata": {}}],
        sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "heatScore": 70.0}],
        stock_rows=[],
    )
    svc = ThemeRotationService(
        FakeRepo(),
        engine=BoomEngine(),
        previous_trading_day_fn=lambda date: "2026-08-03",
    )
    await svc.enrich_bundle(
        bundle, dataset_id="dragonboard_live", snapshot_type="half_hour",
        trading_date="2026-08-04", slot_timestamp_ms=3000, computed_at=3000,
    )
    issues = bundle.frames[0]["metadata"]["derivation"]["qualityIssues"]
    assert any("theme_rotation_failed" in issue for issue in issues)
    assert bundle.sector_rows[0]["themeId"] == "BKAI"  # 原始数据保留
```

### 测试 `quant-board/tests/test_theme_rotation_collector_integration.py`（完整内容）

```python
import pytest

from backend.snapshot_collector.models import CollectorRunRequest
from backend.snapshot_collector.quality_gate import QualityResult
from backend.snapshot_collector.service import SnapshotCollectorService
from backend.snapshot_derivation.models import SnapshotBundle
from backend.snapshot_derivation.service import SnapshotDerivationService
from backend.snapshot_collector.models import MarketDataContext


class FakeRepo:
    def snapshot_exists(self, dataset_id, snapshot_id):
        return False

    def save_snapshot_ingest(self, dataset, records, frames, stock_rows, sector_rows, idempotency_key=None):
        return {"status": "ok", "deduped": False}

    def replace_snapshot_ingest(self, dataset, records, frames, stock_rows, sector_rows, idempotency_key=None):
        return {"status": "ok", "deduped": False}

    def insert_run(self, run):
        pass


class FakeRotationService:
    def __init__(self):
        self.calls = []

    async def enrich_bundle(self, bundle, **kwargs):
        self.calls.append(kwargs)
        bundle.frames[0]["rotationSummary"] = {"marketPhase": "rising"}


def _normalized(req):
    frame = req.bundle["frames"][0]
    return (
        {"id": req.dataset_id},
        [],
        [frame],
        [{"code": "600001", "name": "测试"}],
        req.bundle["sectorRows"],
        "idem-key-1",
    )


def _ok_quality(**kwargs):
    return QualityResult(ok=True, blocking_issues=[], warnings=[], source_counts={"ok": 1, "failed": 0})


@pytest.mark.asyncio
async def test_persist_one_invokes_rotation_service(monkeypatch):
    rotation = FakeRotationService()

    def fake_derive(fact):
        return SnapshotBundle(
            frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "metadata": {}, "indices": {}}],
            sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "rank": 1, "heatScore": 80.0}],
            stock_rows=[{"code": "600001", "name": "测试"}],
        )

    monkeypatch.setattr(SnapshotDerivationService, "derive", fake_derive)

    service = SnapshotCollectorService(
        repo=FakeRepo(),
        collect_fn=lambda *a, **k: (MarketDataContext(), None),
        normalize_fn=_normalized,
        quality_fn=_ok_quality,
        theme_rotation_service=rotation,
    )
    request = CollectorRunRequest(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-08-04",
        slot_time="15:00",
    )
    result = await service._persist_one(request, MarketDataContext(), None)
    assert result.status == "completed"
    assert len(rotation.calls) == 1
    assert rotation.calls[0]["dataset_id"] == "dragonboard_live"
    assert rotation.calls[0]["snapshot_type"] == "half_hour"
```

> 已核对（2026-08-04）：`MarketDataContext()` 全字段有默认工厂；`CollectorRunRequest(dataset_id, snapshot_type, trading_date, slot_time, dry_run=False, force=False)`；`QualityResult(ok, blocking_issues, warnings, source_counts)`——上方测试构造可直接使用。

- [ ] **Step 1**: 创建 `service.py` 与两个测试文件。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_service.py tests/test_theme_rotation_collector_integration.py -q`，预期 3 passed。
- [ ] **Step 3**: 运行既有快照服务测试 `.\\.venv\\Scripts\\python.exe -m pytest tests -k "snapshot_collector" -q --ignore=tests/test_snapshot_collector_bridge_provider.py --ignore=tests/test_snapshot_collector_contract.py`，预期无新增失败。
- [ ] **Step 4**: 提交 `feat(theme-rotation): wire engine into collector persist path with fail-visible semantics`。

---

## Task 7: API —— GET /api/theme-rotation/summary

**Files:**
- Create: `quant-board/backend/api/theme_rotation_routes.py`
- Modify: `quant-board/backend/main.py`
- Test: `quant-board/tests/test_theme_rotation_api.py`

### theme_rotation_routes.py（完整内容）

```python
"""题材轮动只读 API：返回最新 frame.rotationSummary 与带轮动状态的 sector rows。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.data.repository_factory import get_runtime_mongodb_database

router = APIRouter(prefix="/api/theme-rotation", tags=["theme-rotation"])


@router.get("/summary")
def theme_rotation_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
    slot_time: str | None = None,
) -> dict[str, Any]:
    """返回最近一个含 rotationSummary 的 frame 及其 sector rows 轮动状态。"""
    db = get_runtime_mongodb_database()
    query: dict[str, Any] = {
        "datasetId": dataset_id,
        "type": snapshot_type,
        # M6：过滤引擎产出的 rotationSummary（含 algorithmVersion），避免空 dict 命中
        "rotationSummary.algorithmVersion": {"$exists": True},
    }
    if trading_date:
        query["tradingDate"] = trading_date
    if slot_time:
        query["slotTime"] = slot_time
    frame_doc = db["snapshot_frames"].find_one(query, sort=[("timestamp", -1)])
    if not frame_doc:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "status": "error",
                    "error": "no theme rotation summary found for the given filters"},
        )

    sector_rows = list(
        db["snapshot_sector_rows"].find(
            {"datasetId": dataset_id, "snapshotId": frame_doc["snapshotId"],
             "entityType": "hot_theme"},
        ).sort([("rank", 1)])
    )
    return {
        "ok": True,
        "status": "ok",
        "data": {
            "frame": {
                "snapshotId": frame_doc["snapshotId"],
                "tradingDate": frame_doc.get("tradingDate"),
                "slotTime": frame_doc.get("slotTime"),
                "timestamp": frame_doc.get("timestamp"),
                "rotationSummary": frame_doc.get("rotationSummary"),
            },
            "statuses": [_public_sector(row) for row in sector_rows],
        },
    }


def _public_sector(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "themeId", "themeName", "entityKey", "entityName", "rank", "rankChange",
        "rotationState", "lifecycle", "rotationScore", "heatTrend", "flowTrend",
        "breadthTrend", "crowdingTrend", "mainlineConcentrationRank", "reasons",
        "factorBreakdown", "qualityFlags",
    )
    return {key: row.get(key) for key in keys if key in row}
```

### main.py 注册

```python
from backend.api.theme_rotation_routes import router as theme_rotation_router
# 在其它 include_router 后追加：
app.include_router(theme_rotation_router)
```

### 测试 `quant-board/tests/test_theme_rotation_api.py`

```python
from fastapi.testclient import TestClient

from backend.main import app


class FakeFrameDb:
    def __init__(self, frames, sectors):
        self._frames = frames
        self._sectors = sectors

    def find_one(self, query, sort=None):
        # M6：仅当查询要求 algorithmVersion 且存在帧时返回
        if "rotationSummary.algorithmVersion" not in query:
            return None
        return self._frames[0] if self._frames else None

    def __getitem__(self, name):
        if name == "snapshot_sector_rows":
            return _FakeSectorCollection(self._sectors)
        raise KeyError(name)


class _FakeSectorCollection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, query):
        return self

    def sort(self, key_or_list):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


def _patch_db(monkeypatch, frames, sectors):
    import backend.api.theme_rotation_routes as routes
    monkeypatch.setattr(routes, "get_runtime_mongodb_database", lambda: FakeFrameDb(frames, sectors))


def test_theme_rotation_summary_missing_returns_404(monkeypatch):
    _patch_db(monkeypatch, [], [])
    client = TestClient(app)
    resp = client.get(
        "/api/theme-rotation/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour",
                "trading_date": "1999-01-01"},
    )
    assert resp.status_code == 404


def test_theme_rotation_summary_envelope_shape(monkeypatch):
    _patch_db(
        monkeypatch,
        frames=[{
            "snapshotId": "half_hour:2026-08-04:15:00",
            "tradingDate": "2026-08-04",
            "slotTime": "15:00",
            "timestamp": 1000,
            "rotationSummary": {
                "marketPhase": "rising",
                "mainLines": [],
                "algorithmVersion": "theme_rotation_v2",
            },
        }],
        sectors=[{
            "themeId": "BKAI", "themeName": "人工智能", "rank": 1,
            "rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0,
        }],
    )
    client = TestClient(app)
    resp = client.get(
        "/api/theme-rotation/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour",
                "trading_date": "2026-08-04"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frame"]["rotationSummary"]["marketPhase"] == "rising"
    assert data["statuses"][0]["rotationState"] == "mainline"
```

> M7 修复：路由测试用 monkeypatch 替换 `get_runtime_mongodb_database`，不触达真实库（pytest 下访问 `dragon_board_quant` 会抛 RuntimeError）。FakeFrameDb 的 `find_one` 简化实现按算法版本键过滤；实现时以 pymongo 语义对齐。

- [ ] **Step 1**: 创建路由文件、注册、创建测试。
- [ ] **Step 2**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_rotation_api.py -q`。
- [ ] **Step 3**: 提交 `feat(theme-rotation): add read-only summary API`。

---

## Task 8: theme_trend / theme_support 消费对齐

**Files:**
- Modify: `quant-board/backend/analysis/theme_trend.py`
- Modify: `quant-board/backend/analysis/theme_support.py`
- Test: `quant-board/tests/test_theme_trend_engine.py`、`quant-board/tests/test_theme_support.py`（追加用例）

### theme_trend.py 改动

0. **C2 词汇兼容（回测/重放路径必须同源）**：

   - `theme_trend.py:9-18` 的 `LIFECYCLES` 扩展新词表：

```python
LIFECYCLES = {
    "ignition", "expansion", "mainline", "crowded", "divergence",
    "cooling", "reversal", "neutral",
    # theme_rotation_v2 词表（审计 C2，engine 落库值直接透传）
    "ice", "emerging", "expanding", "climax", "inflow", "outflow",
}
```

   - `_infer_lifecycle`（line 475 起）无需改判定逻辑：`explicit in LIFECYCLES` 命中即透传；
     `rotation_state in LIFECYCLES` 分支让新 rotationState（inflow/outflow/emerging）成为 lifecycle 兜底。
   - `_build_factor`（line 505 起）已传 `sector.get("lifecycle")` 作为 explicit——扩展词表后，
     回测/重放路径直接透传落库 lifecycle，不再重推导成旧词表。

1. `_theme_context_frames`（line 235 起，内部 275-276 行）中，把：

```python
        factor["rotationState"] = _ts_rotation_state(rotation, theme_id, theme_name)
        factor["lifecycle"] = _infer_lifecycle({**factor, "lifecycle": ""}, ThemeTrendConfig())
```

改为：

```python
        persisted = _ts_persisted_rotation(factor, frame)
        if persisted is not None:
            factor["rotationState"], factor["lifecycle"], factor["rotationScore"] = persisted
        else:
            factor["rotationState"] = _ts_rotation_state(rotation, theme_id, theme_name)
            factor["lifecycle"] = _infer_lifecycle({**factor, "lifecycle": ""}, ThemeTrendConfig())
            flags = list(factor.get("themeQualityFlags") or [])
            if "rotationState_local_fallback" not in flags:
                flags.append("rotationState_local_fallback")
            factor["themeQualityFlags"] = flags
```

2. 新增辅助函数（放在 `_ts_rotation_state` 之前）：

```python
def _ts_persisted_rotation(factor: dict[str, Any], frame: dict[str, Any]) -> tuple[str, str, float | None] | None:
    """优先消费 sector rows 落库的轮动字段；无则返回 None 走旧推导。"""
    theme_id = _name(factor.get("themeId"))
    theme_name = _normalize_theme_name(_name(factor.get("themeName")))
    for sector in _sector_rows(frame):
        sid = _sector_theme_id(sector, theme_name)
        sname = _normalize_theme_name(_name(sector.get("themeName") or sector.get("entityName")))
        if (theme_id and sid == theme_id) or (theme_name and sname and _is_same_theme_name(sname, theme_name)):
            state = _name(sector.get("rotationState"))
            lifecycle = _name(sector.get("lifecycle"))
            if state or lifecycle:
                score = _num(sector.get("rotationScore"), -1.0)
                return (
                    state or "neutral",
                    lifecycle or _infer_lifecycle({**factor, "lifecycle": ""}, ThemeTrendConfig()),
                    score if score >= 0 else None,
                )
    return None
```

> 已核对（2026-08-04）：`_theme_context_frames(frame)` 内可直接访问 `frame`；`_sector_rows`（line 213）、`_sector_theme_id`（line 339）、`_normalize_theme_name`（line 190）、`_is_same_theme_name`（line 198）均为现有辅助函数，直接复用。

> H3 说明：新帧 sector rows 必有落库 rotationState（`_ts_persisted_rotation` 命中），旧帧无
> rotationState 才走 `_ts_rotation_state` 旧推导并打 `rotationState_local_fallback` 标记；
> 引擎帧不会落到旧推导分支，迁移期混排可经 `algorithmVersion` 区分。

### theme_support.py 改动

在 `build_theme_candidate_support` 中，读取 `factor` 的 rotationScore/lifecycle 并作为可选证据：

```python
    rotation_score = _num(factor.get("rotationScore"))
    lifecycle = str(factor.get("lifecycle") or "")
    if rotation_score is not None:
        score += min(10, max(0, rotation_score - 60) * 0.25)
    if lifecycle == "climax":
        if "题材拥挤风险高" not in risk_flags:
            risk_flags.append("题材轮动高潮风险")
    elif lifecycle in {"emerging", "expanding"} and "题材处于主线" not in reasons:
        reasons.append(f"题材生命周期: {lifecycle}")
```

### theme_momentum.py 改动（M9：新词表 boost/penalty 映射）

`LIFECYCLE_BOOST/PENALTY`（line 38-39）扩展：

```python
LIFECYCLE_BOOST = {"mainline", "expansion", "ignition", "expanding", "emerging"}
LIFECYCLE_PENALTY = {"crowded", "divergence", "cooling", "reversal", "climax", "outflow"}
REVERSAL_LIFECYCLES = {"cooling", "outflow", "divergence", "climax"}
```

`tests/test_theme_momentum.py` 追加：engine 词表行为断言——`expanding`/`emerging` 进 boost、
`climax`/`outflow` 进 penalty、`cooling` 保持 reversal。

### 测试追加

`tests/test_theme_trend_engine.py` 追加：

```python
def test_ts_factors_prefer_persisted_rotation_state():
    from backend.analysis.theme_trend import _theme_context_frames

    frame = {
        "timestamp": 1785807000000,
        "themeContext": {
            "themes": [{"id": "BKAI", "themeId": "BKAI", "themeName": "人工智能"}],
            "themeStocks": {"BKAI": ["600001"]},
            "stockThemes": {"600001": ["BKAI"]},
            "rotationAnalysis": {"mainLines": []},
        },
        "stocks": [{"code": "600001", "change": 5.0, "themeIds": ["BKAI"]}],
        "sectors": [{
            "themeId": "BKAI", "entityKey": "BKAI", "themeName": "人工智能",
            "rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0,
        }],
    }
    factors, _ = _theme_context_frames(frame)
    assert factors
    factor = next(f for f in factors if f.get("themeId") == "BKAI")
    assert factor["rotationState"] == "mainline"
    assert factor["lifecycle"] == "expanding"
    assert "rotationState_local_fallback" not in (factor.get("themeQualityFlags") or [])
```

`tests/test_theme_support.py` 追加：

```python
def test_candidate_support_uses_rotation_score_and_lifecycle():
    from backend.analysis.theme_support import build_theme_candidate_support

    frame = {
        "sectors": [{
            "themeId": "BKAI", "themeName": "人工智能",
            "rotationState": "mainline", "lifecycle": "climax", "rotationScore": 80.0,
            "momentumScore": 70.0, "correlationScore": 60.0, "crowdingRisk": 75.0,
        }],
    }
    stock = {"mainTheme": "人工智能", "themeHeat": 70.0, "themeContribution": 60.0,
             "themeRole": "leader", "change": 9.8, "themeRiskFlags": []}
    support = build_theme_candidate_support(frame, stock)
    assert "题材轮动高潮风险" in support.get("riskFlags", [])
    assert support.get("score", 0) >= 70
```

- [ ] **Step 1**: 已核对函数名与辅助函数；直接按上方代码实现。
- [ ] **Step 2**: 实施 theme_trend/theme_support 改动与测试。
- [ ] **Step 3**: 运行 `.\\.venv\\Scripts\\python.exe -m pytest tests/test_theme_trend_engine.py tests/test_theme_support.py -q`。
- [ ] **Step 4**: 提交 `refactor(theme): consume persisted rotationState from sector rows`。

---

## Task 9: 前端只消费后端结果

**Files:**
- Create: `src/services/theme/backendRotationAdapter.ts`
- Modify: `src/services/snapshot/backendRead.ts`（C3：停止剥除 `rotationSummary.mainLines`）
- Modify: `src/services/rotationService.ts`（M11：localStorage 只存后端提供字段）
- Modify: `src/services/dragon/BattlefieldBuilder.ts`、`src/services/RegimeClassifier.ts`、
  `src/services/CandidateAnalysisService.ts`、`src/services/CandidateDiscoveryService.ts`、
  `src/services/CandidateJournalService.ts`（H5：可选字段守卫）
- Modify: `src/services/theme/ThemeFacade.ts`
- Modify: `src/services/theme/ThemeRuntimeCoordinator.ts`
- Modify: `src/services/theme/ThemeFactorEngine.ts`
- Modify: `src/components/panels/SectorRotation.vue`、`src/components/panels/SectorPanel.vue`
- Modify: `src/types/core.ts`
- Test: `src/services/theme/__tests__/backendRotationAdapter.test.ts`、既有 theme 前端测试同步更新

### backendRead.ts 改动（C3）

`listSnapshotFrames`（backendRead.ts:88-110）当前把 `rotationSummary` 里的 `mainLines` 剥掉。
改为保留（引擎/历史行都含 mainLines）：

```typescript
      ({ rows: _rows, hotlist: _hotlist, entities: _entities, sectors: _sectors, hotThemes: _hotThemes, rotationSummary, ...frame }) => ({
        ...frame,
        rotationSummary: rotationSummary && typeof rotationSummary === 'object' ? rotationSummary : undefined,
      }),
```

同步更新 `backendRead.test.ts:283/301` 中断言（原先断言剥掉后为 `{}` 的用例改为断言 mainLines 保留）。

### backendRotationAdapter.ts（完整内容）

```typescript
import type { RotationAnalysis, MarketPhaseType, ThemeRotationStatus } from '@/types/core'

type BackendStatus = {
  themeId?: string
  themeName?: string
  rotationScore?: number | null
  rotationState?: string
  rankChange?: number | null
}

/** 后端 rotationSummary → 前端 RotationAnalysis 的纯投影（无计算）。 */
export function mapBackendRotationSummary(
  backend: Record<string, any> | null | undefined,
): RotationAnalysis | null {
  // 仅接受引擎产出（H3：按 algorithmVersion 区分迁移期混排）
  if (!backend || typeof backend !== 'object' || !backend.algorithmVersion) return null
  const phase = mapMarketPhase(backend.marketPhase)
  const mainLines: ThemeRotationStatus[] = (backend.mainLines || []).map((item: BackendStatus, i: number) =>
    statusFromBackend(item, i + 1, true),
  )
  return {
    timestamp: backend.computedAt || Date.now(),
    inflowThemes: (backend.inflowThemes || []).map((id: string, i: number) =>
      statusFromBackend({ themeId: id, themeName: id, rotationState: 'inflow' }, i + 1, false),
    ),
    outflowThemes: (backend.outflowThemes || []).map((id: string, i: number) =>
      statusFromBackend({ themeId: id, themeName: id, rotationState: 'outflow' }, i + 1, false),
    ),
    mainLines,
    quickRotation: [],
    rotationSpeed: backend.rotationSpeed ?? undefined,
    marketPhase: phase,
    summary: {
      mainLineCount: mainLines.length,
      inflowCount: (backend.inflowThemes || []).length,
      outflowCount: (backend.outflowThemes || []).length,
      topInflow: (backend.inflowThemes || [])[0] || '',
      topOutflow: (backend.outflowThemes || [])[0] || '',
      suggestion: backend.suggestion || '',
      strongCount: mainLines.filter((m) => m.strength === 'strong').length,
      topStrength: mainLines[0]?.themeName || '',
    },
    mainlineConcentration: backend.mainlineConcentration ?? undefined,
    maxBoardHeight: backend.maxBoardHeight ?? undefined,
    algorithmVersion: backend.algorithmVersion,
    evidence: backend.evidence,
  }
}

function statusFromBackend(item: BackendStatus, rank: number, isMainLine: boolean): ThemeRotationStatus {
  const state = item.rotationState || (isMainLine ? 'mainline' : 'neutral')
  const direction =
    state === 'mainline' || state === 'inflow' || state === 'emerging'
      ? 'inflow'
      : state === 'outflow' || state === 'cooling'
        ? 'outflow'
        : 'neutral'
  const score = item.rotationScore ?? undefined
  return {
    themeId: item.themeId || '',
    themeName: item.themeName || item.themeId || '',
    rank,
    rankChange: item.rankChange ?? undefined,
    rotationScore: score,
    isMainLine,
    direction,
    persistentDays: undefined,
    strength: score != null && score >= 70 ? 'strong' : score != null && score >= 45 ? 'medium' : 'weak',
    relatedThemes: undefined,
    topReasons: [],
    // 后端 v1 不提供资金/宽度明细：保持 undefined，缺失不伪造（M10）
    inflow: undefined,
    outflow: undefined,
    netInflow: undefined,
    avgChange: undefined,
    totalTurnover: undefined,
    ztCount: undefined,
    stockCount: undefined,
    strengthScore: undefined,
  }
}

function mapMarketPhase(phase: string | undefined): MarketPhaseType {
  switch (phase) {
    case 'ice': return 'ice'
    case 'rising': return 'rising'
    case 'climax': return 'climax'
    case 'cooling': return 'falling'
    case 'chaos': return 'accumulation'
    case 'neutral': return 'accumulation'
    default: return 'accumulation'
  }
}
```

### ThemeFacade.ts / ThemeRuntimeCoordinator.ts 改动

- `ThemeFacade.getRotationSummary()`：改为返回缓存的后端映射结果（`backendRotationSummary` 模块级缓存），不再调用 `buildThemeRotationSummary`。
- `ThemeRuntimeCoordinator.executeWithFactors`：删除 `buildThemeRotationSummary(...)` 分支，改为 `const rotationSummary = mapBackendRotationSummary(backendRotation)`，其中 `backendRotation` 来自刷新时传入的最新 frame.rotationSummary（来源见下）；`previousRotation/previousSignature` 逻辑删除。
- `ThemeRotationEngine.ts`：删除本地状态机函数；文件改为 `export { mapBackendRotationSummary } from './backendRotationAdapter'` 兼容旧导入，并在 Task 9 完成后由引用方全部切到 adapter，随后删除该文件。
- `ThemeFactorEngine.ts`：删除 `rotationState`/`persistence` 的本地推导；`factor.rotationState` 透传 API sector factor 中已有的值，无则 `undefined`。
- `SectorRotation.vue`/`SectorPanel.vue`：`rotationData` 优先级改为 `frame.rotationSummary`（经 snapshot backendRead 已能拿到）→ `themeFacade.getRotationSummary()`；不再回退到本地计算。

> **后端 rotationSummary 到前端的通道**：快照 frame 读取走 `src/services/snapshot/backendRead.ts`（已含 `GET /api/snapshots/frames`），新增 frame.rotationSummary 字段后直接透出；`ThemeRuntimeCoordinator` 的刷新来源保持现有数据流，仅把「轮动计算」替换为「读取 + 映射」。面板启动时若后端无 rotationSummary，显示"后端暂无轮动结果"空态，不本地补算。

### types/core.ts 扩展（M10：缺失保持缺失，字段可选化）

`ThemeRotationStatus` 中后端 v1 不提供的字段改为可选（adapter 不再造 0 值）：

```typescript
export interface ThemeRotationStatus {
  themeId: string
  themeName: string
  rank: number
  rankChange?: number
  direction: RotationDirection
  strength: RotationStrength
  persistentDays?: number
  isMainLine: boolean
  relatedThemes?: Array<{ id: string; name: string; correlation: number }>
  inflow?: number
  outflow?: number
  netInflow?: number
  avgChange?: number
  totalTurnover?: number
  ztCount?: number
  stockCount?: number
  rotationScore?: number
  strengthScore?: number
  topReasons?: string[]
  /* ...保留既有可选字段（volumeRatio 等）不变 */
}
```

`RotationAnalysis` 追加/调整：

```typescript
  /** 轮动速度；后端无数据时为 undefined（缺失不伪造） */
  rotationSpeed?: number
  /** 后端算法版本（有值时表示来自后端引擎） */
  algorithmVersion?: string
  /** 主线集中度（Top3 heat 占比） */
  mainlineConcentration?: number
  /** 全市场最高连板 */
  maxBoardHeight?: number
  /** 引擎证据（framesUsed / qualityIssues） */
  evidence?: { framesUsed?: number; qualityIssues?: string[] }
```

### 前端测试

`src/services/theme/__tests__/backendRotationAdapter.test.ts`：

```typescript
import { describe, expect, it } from 'vitest'
import { mapBackendRotationSummary } from '../backendRotationAdapter'

describe('mapBackendRotationSummary', () => {
  it('maps rising phase with mainlines', () => {
    const mapped = mapBackendRotationSummary({
      marketPhase: 'rising',
      rotationSpeed: 42,
      mainlineConcentration: 0.36,
      maxBoardHeight: 8,
      mainLines: [{ themeId: 'BKAI', themeName: '人工智能', rotationScore: 78 }],
      inflowThemes: ['BKAG'],
      outflowThemes: [],
      suggestion: '主线上升期',
      algorithmVersion: 'theme_rotation_v2',
    })
    expect(mapped?.marketPhase).toBe('rising')
    expect(mapped?.mainLines[0].themeName).toBe('人工智能')
    expect(mapped?.algorithmVersion).toBe('theme_rotation_v2')
  })

  it('returns null for empty backend payload', () => {
    expect(mapBackendRotationSummary(null)).toBeNull()
    expect(mapBackendRotationSummary({})).toBeNull() // 无 algorithmVersion 视为非引擎产出（H3）
  })
})
```

- [ ] **Step 1**: 创建 adapter 与类型扩展，写 adapter 测试。
- [ ] **Step 2**: 修改 backendRead.ts（C3 保留 mainLines）并更新其测试；修改 ThemeFacade/ThemeRuntimeCoordinator/ThemeFactorEngine/两个面板，删除本地计算。
- [ ] **Step 3（H5 消费者兼容审计）**：对 `BattlefieldBuilder.ts:222/253/344-345`、`RegimeClassifier.ts:12`、`CandidateAnalysisService.ts:419`、`CandidateDiscoveryService.ts:223`、`CandidateJournalService.ts:639`、`ThemeRiskDashboard.vue:398/417/424`、`ThemeCorrelationPanel.vue:872` 逐一加可选字段守卫：`rotationSpeed ?? 0` 仅用于展示；`netInflow/ztCount/stockCount` 为 undefined 时跳过对应打分/分类分支并在原因里标注"后端未提供"，禁止用 0 参与计算。
- [ ] **Step 4（M11）**：`rotationService.ts` 的 `saveHotThemesToLocalStorage` 只保存后端提供的字段（undefined 字段省略），不再写占位值；`analyzeAll` 在 `result.rotationSummary` 为空时沿用 `emptyAnalysis()` 并标记来源缺失。
- [ ] **Step 5**: 运行 `pnpm test` 与 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- [ ] **Step 6**: 浏览器验收：启动 8000 后端 + `pnpm dev`，用 Playwright 打开 SectorRotation 面板，确认显示后端 marketPhase/主线列表、无控制台错误、无本地计算痕迹（见 Task 10 验证清单）。
- [ ] **Step 7**: 提交 `refactor(theme): frontend consumes backend rotation results only`。

---

## Task 10: 文档同步与全量验证

**Files:**
- Modify: `quant-board/docs/architecture.md`、`quant-board/docs/api-cli.md`（新增 /api/theme-rotation/summary 与 sector rows 新字段）
- Modify: `quant-board/backend/data/supabase_schema.sql`、`quant-board/backend/data/supabase_homomorphic.py`（H2：新列与映射）
- Modify: `quant-board/backend/data/repository.py`（H4：SQLite 旧读路径只在无 algorithmVersion 时合并 rotation_main_line）
- Modify: `quant-board/docs/theme-rotation/2026-08-04-theme-rotation-engine-design.md`（状态改为已实施，若实现与设计有偏差则如实修订）
- Modify: `quant-board/docs/database-migration-plan.md`（快照 sector rows 字段与 Supabase 同构变更）

### H2：Supabase 同构（AGENTS.md 4.2 硬约束）

`supabase_schema.sql` 的 `snapshot_sector_rows` 增加列：

```sql
lifecycle varchar(32),
rotation_score numeric,
heat_trend numeric,
flow_trend numeric,
breadth_trend numeric,
crowding_trend numeric,
mainline_concentration_rank integer,
reasons jsonb,
factor_breakdown jsonb
```

`supabase_homomorphic.py` 的 `_sector_to_row`（line 881 起）与 `_sector_from_row`（line 1053 起）
同步加映射：`lifecycle`/`rotation_score`/`heat_trend`/`flow_trend`/`breadth_trend`/
`crowding_trend`/`mainline_concentration_rank`/`reasons`（json.dumps）/`factor_breakdown`（json.dumps），
读回时反向 json.loads。`rotation_state` 既有列保留。

### H4：SQLite 旧读路径防护

`backend/data/repository.py`（约 638-647 行）当前无条件用 `rotation_main_line` 行覆盖
`rotationSummary.mainLines`。改为仅在 `rotationSummary` 无 `algorithmVersion` 时合并（历史兼容），
引擎帧的 mainLines 不被顶掉：

```python
            rotation_summary = item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else None
            if rotation_summary:
                if rotation_summary.get("algorithmVersion"):
                    item["rotationSummary"] = rotation_summary
                else:
                    item["rotationSummary"] = {**rotation_summary, "mainLines": main_lines}
            elif main_lines:
                item["rotationSummary"] = {"mainLines": main_lines}
```

> 已核对（2026-08-04）：当前 frames API（`main.py:528`）在 `storage_backend=mongodb` 时走
> MongoRepository（rotationSummary 透传、无 rotation_main_line 合并）；SQLite `repository.py`
> 为历史路径。两处都加防护，避免未来切换后端时回归。

- [ ] **Step 1**: 更新架构/API 文档：`snapshot_sector_rows` 新增 `rotationState/lifecycle/rotationScore/heatTrend/flowTrend/breadthTrend/crowdingTrend/rankChange/mainlineConcentrationRank/reasons/factorBreakdown`；frame 新增 `rotationSummary`；API 文档新增 `/api/theme-rotation/summary`。
- [ ] **Step 2**: 实施 H2（Supabase 加列 + homomorphic 映射）与 H4（SQLite 防护），同步 `database-migration-plan.md`。
- [ ] **Step 3**: 全量后端测试：`cd D:\dragon-board\quant-board; .\.venv\Scripts\python.exe -m pytest tests -q --ignore=tests/test_snapshot_collector_bridge_provider.py --ignore=tests/test_snapshot_collector_contract.py`（存量两个失败文件另立专项，不在本任务范围）。
- [ ] **Step 4**: 前端全量：`pnpm test`、`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- [ ] **Step 5**: 真机验证一个交易槽位：8000 后端运行中手动触发一次采集（`POST /api/snapshot-collector/run-once`），用 Mongo 抽查 `snapshot_sector_rows` 的 `rotationState/lifecycle/rotationScore` 非空、frame 的 `rotationSummary` 键为 camelCase 且含 `algorithmVersion`、`metadata.derivation.qualityIssues` 无 `theme_rotation_failed`；Supabase 备份表核对新列有值。
- [ ] **Step 6**: 补采回归：`snapshot-collector-backfill` 跑一次当日缺槽，确认走同一 enrichment 路径。
- [ ] **Step 7**: 提交 `docs(theme-rotation): sync architecture/api/db docs, supabase homomorphic, sqlite mainlines guard`。

---

## 风险与回退

- **风险 1（引擎不阻断入库）**：`enrich_bundle` 全程 try/except，异常只写 qualityIssues，原始数据照存——符合 fail-visible。
- **风险 2（历史窗口跨日）**：已实现前一交易日回溯（H1）；若实测跨日基线失真，只改 `history.py` 的日期范围/分组逻辑，不动因子层。
- **风险 3（权重主观性）**：默认权重来自调研共识，先出可解释版本；权重集中在一个 config 文件，后续敏感性分析只改 config。
- **风险 4（theme_trend 双轨）**：有落库 rotationState 时用落库值；旧数据走旧推导并打 `rotationState_local_fallback` 标记，不改变旧帧行为。
- **风险 5（前端无后端数据）**：显示空态 + 提示，绝不本地补算（杜绝两套结果）。
- **风险 6（昨日涨停溢价/亏钱效应）**：v1 不消费 `frame.limitSummary.yesterdayZt`（缺昨日涨停表现数据时显式降级）；市场阶段 `cooling` 依赖资金/动量退化信号与主题 cooling 计数，不作为 v1 硬输入。后续接入昨日溢价时只需扩展 engine 输入与 `market_phase_for`。
- **已知限制（审计 L1/L2/L3）**：因子系数为调研共识初值，需历史回放做敏感性验证后再固化（权重集中 config 一处）；`_theme_key` 回退 themeName 时同名不同主题会合并（先按 themeId/entityKey 优先）；题材数少时 MAD≈0 由 `+1e-9` 兜底，z 近似 0。
- **回退**：每个 Task 独立 commit；引擎可整体关闭（`_persist_one` 的 `theme_rotation_service=None`），数据链路不受影响。

## 验证命令速查

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_rotation_factors.py tests/test_theme_rotation_lifecycle.py tests/test_theme_rotation_engine.py tests/test_theme_rotation_history.py tests/test_theme_rotation_service.py tests/test_theme_rotation_api.py -q
cd D:\dragon-board
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```
