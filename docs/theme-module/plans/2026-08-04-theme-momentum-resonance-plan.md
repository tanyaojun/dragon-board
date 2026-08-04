# 题材动量（板块共振）接入 RankTrend OBSERVATION 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 RankTrend OBSERVATION 共振路径增加题材动量（板块共振）维度：Python 从已落库 `snapshot_sector_rows` 计算题材动量，并入个股共振分数（有限调节 ±15 + 生命周期门禁），前端只消费展示。

**Architecture:** 新增纯计算模块 `theme_momentum.py`（题材强度序列 → 六因子镜像动量 → 每股题材暴露 → 融合调节）；analyze 路由的帧组装带上 `hotThemes` 与股票 `themes` 字段，输出帧级 `themeContext` 与每股 `analysis.resonance.theme`；前端 OBSERVATION 共振轨与 DataTable tooltip 展示。无新 MongoDB 集合 / 无新 API / 无新 CLI；题材数据不足时保留原共振分数并输出结构化原因（fail-visible）。

**Tech Stack:** Python FastAPI（quant-board/backend）、Vue 3 + TypeScript（Dragon Board）、pytest、Vitest、Playwright。

**设计文档：** `docs/theme-module/2026-08-04-theme-momentum-resonance-design.md`（已确认：基分保留 + 有限调节；题材序列用 heatScore；主题材取所属题材 heatScore 最高者；文档放 docs/theme-module/）。

---

## Task 1: Python 题材动量纯函数 + 单测

**Files:**
- Create: `quant-board/backend/analysis/theme_momentum.py`
- Test: `quant-board/backend/tests/test_theme_momentum.py`

- [ ] **Step 1: 写失败测试（序列构建 + 动量公式 + 横截面不足）**

```python
# quant-board/backend/tests/test_theme_momentum.py
import math

import pytest

from backend.analysis.theme_momentum import (
    THEME_CROSS_SECTION_MIN,
    build_theme_strength_series,
    compute_theme_momentum_series,
)


def _theme(theme_id, heat, rank, rotation="neutral", eligible=True, extra=None):
    item = {
        "entityType": "hot_theme",
        "themeId": theme_id,
        "themeName": f"{theme_id}概念板块",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "metadata": {"rankEligible": eligible},
    }
    if extra:
        item.update(extra)
    return item


def _frame(index, theme_rows):
    return {
        "tradingDate": "2026-08-04",
        "slotTime": f"{index:02d}:00",
        "type": "half_hour",
        "timestamp": index,
        "stocks": [],
        "hotThemes": theme_rows,
    }


def test_series_keeps_only_rank_eligible_finite_heat():
    frames = [
        _frame(0, [
            _theme("A", 50.0, 1),
            _theme("B", math.nan, 2),
            _theme("C", 40.0, 3, eligible=False),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["A"]
    assert series["A"][0][:2] == (0, 50.0)


def test_momentum_series_mirrors_resonance_bounds():
    themes = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
    # T0 持续升温，其余横盘
    frames = []
    for idx in range(12):
        rows = [_theme("T0", 40.0 + idx * 2.0, 1)]
        rows += [_theme(f"T{i}", 50.0, i + 1) for i in range(1, 25)]
        frames.append(_frame(idx, rows))
    result = compute_theme_momentum_series(frames)
    frame = result["frames"][-1]
    assert frame["themeSampleCount"] >= THEME_CROSS_SECTION_MIN
    assert frame["qualityFlags"] == []
    momentum = frame["themes"]["T0"]
    assert momentum["status"] == "ok"
    assert 0 <= momentum["score"] <= 100
    assert momentum["direction"] == "buy"
    assert momentum["relativeMomentum"] > 0


def test_momentum_series_insufficient_cross_section():
    frames = [_frame(idx, [_theme(f"T{i}", 50.0, i + 1) for i in range(5)]) for idx in range(12)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themeSampleCount"] < THEME_CROSS_SECTION_MIN
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_skips_short_history_theme():
    frames = [_frame(idx, [_theme("A", 50.0 + idx, 1), _theme("B", 50.0, 2)]) for idx in range(12)]
    # B 只在前 4 帧出现，之后缺槽
    for idx in range(4, 12):
        frames[idx]["hotThemes"] = [_theme("A", 50.0 + idx, 1)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert "B" not in frame["themes"]
    assert "A" in frame["themes"]


def test_momentum_series_all_nan_heat_is_insufficient():
    frames = [
        _frame(idx, [_theme("A", math.nan, 1), _theme("B", math.nan, 2)]) for idx in range(12)
    ]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"] == {}
    assert frame["themeSampleCount"] == 0
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_jump_by_rank_only():
    # heatScore 恒定，但第 10 帧 rank 从 8 跳到 1（提升 >= 3 槽）
    frames = []
    for idx in range(12):
        rank = 8 - (3 if idx >= 10 else 0)
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, rank)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    momentum = frame["themes"]["T0"]
    assert momentum["jumpFreshness"] > 0


def test_momentum_series_rank_missing_uses_heat_jump():
    # rank 全部缺失，heatScore 单帧提升 >= 15 触发 Jump
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, None) for i in range(25)]
        rows[0] = _theme("T0", 50.0 if idx < 9 else 70.0, None)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"]["T0"]["jumpFreshness"] > 0


def test_momentum_series_reversal_penalty_adds_cooling_bonus():
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, 1, rotation="cooling")
        frames.append(_frame(idx, rows))
    momentum = compute_theme_momentum_series(frames)["frames"][-1]["themes"]["T0"]
    assert momentum["reversalPenalty"] == pytest.approx(0.2)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_momentum.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.analysis.theme_momentum'`）

- [ ] **Step 3: 实现纯函数**

```python
# quant-board/backend/analysis/theme_momentum.py
"""题材动量（板块共振）纯计算。

从 snapshot sector rows（entityType=hot_theme）的题材因子序列计算多帧相对动量，
并为每股生成题材暴露与共振调节。本模块不访问 HTTP/MongoDB/缓存，输出确定性结果。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

# 固定参数（与个股共振 analyze_rank_resonance 对齐；不做参数搜索）
THEME_SHORT_WINDOW_BARS = 3
THEME_MID_WINDOW_BARS = 8
THEME_PATH_WINDOW_BARS = 8
THEME_JUMP_DECAY_BARS = 3
THEME_JUMP_RANK_SLOTS = 3
THEME_JUMP_HEAT_DELTA = 15.0
THEME_CROSS_SECTION_MIN = 20
THEME_SERIES_MIN_BARS = THEME_MID_WINDOW_BARS + 1
THEME_MOMENTUM_VERSION = "theme-momentum-v1"

# 融合参数（固定常量，不做参数搜索）
THEME_ADJUSTMENT_SCALE = 0.3
THEME_ADJUSTMENT_MAX = 15.0
THEME_LIFECYCLE_BONUS = 5.0
THEME_LIFECYCLE_PENALTY_MAX = 10.0
THEME_LIFECYCLE_PENALTY_DENOM = 10.0

ROLE_WEIGHTS = {
    "leader": 1.0,
    "core": 0.82,
    "follower": 0.62,
    "independent": 0.38,
    "noise": 0.15,
}
LIFECYCLE_BOOST = {"mainline", "expansion", "ignition"}
LIFECYCLE_PENALTY = {"crowded", "divergence", "cooling", "reversal"}
REVERSAL_LIFECYCLES = {"cooling", "outflow", "divergence"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _theme_id(theme: dict[str, Any]) -> str:
    return str(theme.get("themeId") or theme.get("entityKey") or theme.get("code") or "").strip()


def _theme_rank_eligible(theme: dict[str, Any]) -> bool:
    metadata = theme.get("metadata")
    if isinstance(metadata, dict) and metadata.get("rankEligible") is not None:
        return bool(metadata.get("rankEligible"))
    return bool(theme.get("rankEligible", True))


def _normalize_theme_name(value: Any) -> str:
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块", "技术", "产业", "经济", "行业", "主题"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _is_same_theme_name(left: Any, right: Any) -> bool:
    left_name = _normalize_theme_name(left)
    right_name = _normalize_theme_name(right)
    if not left_name or not right_name:
        return False
    if left_name == right_name:
        return True
    shorter, longer = sorted((left_name, right_name), key=len)
    return len(shorter) >= 3 and shorter in longer and len(shorter) / len(longer) >= 0.75


def build_theme_strength_series(
    frames: list[dict[str, Any]],
) -> dict[str, list[tuple[int, float, int | None]]]:
    """每题材按 (frame_index, heatScore, rank) 记录；仅 rankEligible 且 heatScore 有限。

    rank 缺失时记 None（题材 Jump 仍可用 heatScore 判定）。"""
    series: dict[str, list[tuple[int, float, int | None]]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for theme in frame.get("hotThemes") or []:
            if not isinstance(theme, dict):
                continue
            if str(theme.get("entityType") or "hot_theme") != "hot_theme":
                continue
            theme_id = _theme_id(theme)
            heat = _num(theme.get("heatScore"), math.nan)
            if not theme_id or not math.isfinite(heat) or not _theme_rank_eligible(theme):
                continue
            rank = theme.get("rank")
            try:
                rank_int = int(rank) if rank is not None else None
            except (TypeError, ValueError):
                rank_int = None
            series[theme_id].append((frame_index, heat, rank_int))
    return {theme_id: bars for theme_id, bars in series.items() if bars}


def _theme_momentum_for(
    theme_id: str,
    values: list[float],
    ranks: list[int | None],
    market_median: float | None,
    rotation_state: str,
) -> dict[str, Any]:
    last = len(values) - 1
    short_change = values[last] - values[last - THEME_SHORT_WINDOW_BARS]
    mid_change = values[last] - values[last - THEME_MID_WINDOW_BARS]
    relative_momentum = (
        _clamp((short_change - market_median) / 15.0, -1, 1)
        if market_median is not None
        else 0.0
    )
    acceleration = _clamp(
        (short_change - mid_change * THEME_SHORT_WINDOW_BARS / THEME_MID_WINDOW_BARS) / 15.0,
        -1,
        1,
    )
    path = values[-(THEME_PATH_WINDOW_BARS + 1):]
    changes = [path[index + 1] - path[index] for index in range(len(path) - 1)]
    path_direction = 1 if (short_change or mid_change) > 0 else -1 if (short_change or mid_change) < 0 else 0
    directional = [
        change
        for change in changes
        if path_direction != 0 and (1 if change > 0 else -1 if change < 0 else 0) == path_direction
    ]
    persistence = len(directional) / len(changes) if changes else 0.0
    switch_rate = 0.0
    if len(changes) > 1:
        signs = [1 if change > 0 else -1 if change < 0 else 0 for change in changes]
        switch_rate = sum(
            1
            for index in range(1, len(signs))
            if signs[index] != 0 and signs[index - 1] != 0 and signs[index] != signs[index - 1]
        ) / (len(signs) - 1)
    recent_peak = max(path)
    drawdown = max(0.0, recent_peak - values[last])
    reversal_penalty = _clamp(0.6 * switch_rate + 0.4 * drawdown / 20.0, 0, 1)
    if rotation_state in REVERSAL_LIFECYCLES:
        reversal_penalty = _clamp(reversal_penalty + 0.2, 0, 1)

    jump_index: int | None = None
    for index in range(last, max(0, last - 12), -1):
        heat_jump = values[index] - values[index - 1] >= THEME_JUMP_HEAT_DELTA
        rank_jump = (
            ranks[index] is not None
            and ranks[index - 1] is not None
            and int(ranks[index]) <= int(ranks[index - 1]) - THEME_JUMP_RANK_SLOTS
        )
        if heat_jump or rank_jump:
            jump_index = index
            break
    jump_freshness = (
        math.exp(-(last - jump_index) / THEME_JUMP_DECAY_BARS) if jump_index is not None else 0.0
    )

    direction_score = relative_momentum + acceleration + 0.2 * path_direction * persistence
    direction = "buy" if direction_score > 0.1 else "sell" if direction_score < -0.1 else "hold"
    directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
    directional_acceleration = -acceleration if direction == "sell" else acceleration
    raw_score = (
        0.35 * max(0.0, directional_momentum)
        + 0.25 * max(0.0, directional_acceleration)
        + 0.2 * persistence
        + 0.2 * jump_freshness
        - 0.2 * reversal_penalty
    )
    return {
        "themeId": theme_id,
        "status": "ok",
        "direction": direction,
        "score": round(100 * _clamp(raw_score, 0, 1)),
        "relativeMomentum": round(relative_momentum, 6),
        "acceleration": round(acceleration, 6),
        "persistence": round(persistence, 6),
        "jumpFreshness": round(jump_freshness, 6),
        "reversalPenalty": round(reversal_penalty, 6),
        "shortChange": round(short_change, 4),
        "midChange": round(mid_change, 4),
    }


def compute_theme_momentum_series(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """逐帧计算题材动量；返回 frames 列表（与输入等长）。"""
    series = build_theme_strength_series(frames)
    results: list[dict[str, Any]] = []
    for frame_index in range(len(frames)):
        prefix_by_theme: dict[str, tuple[list[float], list[int | None]]] = {}
        for theme_id, bars in series.items():
            prefix = [bar for bar in bars if bar[0] <= frame_index]
            if len(prefix) >= THEME_SERIES_MIN_BARS:
                prefix_by_theme[theme_id] = (
                    [bar[1] for bar in prefix],
                    [bar[2] for bar in prefix],
                )
        short_changes: list[float] = []
        for theme_id, (values, _ranks) in prefix_by_theme.items():
            if len(values) >= THEME_SHORT_WINDOW_BARS + 1:
                short_changes.append(values[-1] - values[-1 - THEME_SHORT_WINDOW_BARS])
        market_median = _median(short_changes)
        cross_section_ok = market_median is not None and len(short_changes) >= THEME_CROSS_SECTION_MIN
        rotation_by_theme: dict[str, str] = {}
        for theme in frames[frame_index].get("hotThemes") or []:
            if isinstance(theme, dict):
                rotation_by_theme[_theme_id(theme)] = str(theme.get("rotationState") or "neutral")
        themes_out: dict[str, dict[str, Any]] = {}
        for theme_id, (values, ranks) in prefix_by_theme.items():
            themes_out[theme_id] = _theme_momentum_for(
                theme_id,
                values,
                ranks,
                market_median if cross_section_ok else None,
                rotation_by_theme.get(theme_id, "neutral"),
            )
        results.append({
            "themes": themes_out,
            "marketThemeMedianShortChange": market_median,
            "themeSampleCount": len(short_changes),
            "crossSectionOk": cross_section_ok,
            "qualityFlags": [] if cross_section_ok else ["theme_cross_section_insufficient"],
        })
    return {"frames": results, "version": THEME_MOMENTUM_VERSION}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_momentum.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme_momentum.py quant-board/backend/tests/test_theme_momentum.py
git commit -m "feat(theme-momentum): add pure theme momentum series and momentum scoring"
```

## Task 2: 每股题材暴露与共振融合 + 单测

**Files:**
- Modify: `quant-board/backend/analysis/theme_momentum.py`（追加暴露与融合函数）
- Test: `quant-board/backend/tests/test_theme_resonance_fusion.py`

- [ ] **Step 1: 写失败测试（主题材选择/角色/不足降级/调节边界/方向不变）**

```python
# quant-board/backend/tests/test_theme_resonance_fusion.py
from backend.analysis.theme_momentum import (
    THEME_ADJUSTMENT_MAX,
    fuse_theme_resonance,
    stock_theme_exposure,
)


def _theme(theme_id, heat, rank, rotation="neutral", eligible=True, crowding_risk=30.0):
    return {
        "entityType": "hot_theme",
        "themeId": theme_id,
        "themeName": f"{theme_id}概念板块",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "crowdingRisk": crowding_risk,
        "metadata": {"rankEligible": eligible},
    }


def _stock(code, themes, change=3.0, theme_role="", lead_status="", main_theme=""):
    return {
        "code": code,
        "themes": themes,
        "change": change,
        "themeRole": theme_role,
        "leadStatus": lead_status,
        "mainTheme": main_theme,
    }


def _frame_momentum(cross_section_ok=True, theme_scores=None):
    return {
        "themes": {theme_id: {"status": "ok", "score": score, "direction": "buy"}
                   for theme_id, score in (theme_scores or {"A": 80.0}).items()},
        "marketThemeMedianShortChange": 1.0,
        "themeSampleCount": 25,
        "crossSectionOk": cross_section_ok,
        "qualityFlags": [] if cross_section_ok else ["theme_cross_section_insufficient"],
    }


def test_exposure_picks_highest_heat_theme_and_role():
    # 单一题材时 themeRole 直接复用；heatScore 最高者为主题材
    stock = _stock("000001", ["高热概念"], theme_role="leader")
    exposure = stock_theme_exposure(
        stock,
        [_theme("低热", 40.0, 2, eligible=False), _theme("高热", 80.0, 1), _theme("其他", 60.0, 3)],
    )
    assert exposure is not None
    assert exposure["themeId"] == "高热"
    assert exposure["role"] == "leader"
    assert exposure["roleWeight"] == 1.0


def test_exposure_returns_none_without_mapping():
    stock = _stock("000001", [])
    assert stock_theme_exposure(stock, [_theme("T2", 80.0, 1)]) is None


def test_fusion_insufficient_when_cross_section_bad_keeps_base_score():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["T2"]), [_theme("T2", 80.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(cross_section_ok=False))
    assert fused["score"] == 60
    assert fused["theme"]["status"] == "insufficient"
    assert "theme_cross_section_insufficient" in fused["theme"]["reasons"]


def test_fusion_missing_mapping_keeps_base_score():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    fused = fuse_theme_resonance(base, None, _frame_momentum())
    assert fused["score"] == 60
    assert fused["theme"]["status"] == "insufficient"
    assert "theme_mapping_missing" in fused["theme"]["reasons"]


def test_fusion_adjustment_bounded_and_direction_preserved():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"]), [_theme("A", 90.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 100.0}))
    assert fused["theme"]["status"] == "ok"
    assert fused["direction"] == "buy"
    assert fused["score"] > 60
    assert abs(fused["theme"]["adjustment"]) <= THEME_ADJUSTMENT_MAX


def test_fusion_lifecycle_penalty_for_follower_in_cooling():
    base = {"status": "ok", "direction": "buy", "score": 80, "label": "强"}
    exposure = stock_theme_exposure(
        _stock("000001", ["A"], theme_role="follower"),
        [_theme("A", 90.0, 1, rotation="cooling", crowding_risk=90.0)],
    )
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 40.0}))
    assert fused["score"] < 80
    assert fused["theme"]["themeLifecycle"] == "cooling"


def test_exposure_main_theme_priority():
    stock = _stock("000001", ["AI", "半导体"], main_theme="AI概念")
    exposure = stock_theme_exposure(
        stock,
        [
            _theme("半导体", 90.0, 1),
            _theme("AI", 88.0, 2),
        ],
    )
    assert exposure is not None
    assert exposure["themeId"] == "AI"


def test_exposure_role_fallback_when_matched_theme_not_main_theme():
    # themeRole 属于 mainTheme 的语义；匹配到非 mainTheme 题材时回退 heat/change 规则
    stock = _stock("000001", ["半导体", "人工智能"], theme_role="leader", main_theme="人工智能概念")
    exposure = stock_theme_exposure(
        stock,
        [
            _theme("半导体", 90.0, 1),
            _theme("白酒", 60.0, 2),
        ],
    )
    # mainTheme "人工智能概念" 未出现在帧内，降级取匹配题材中 heatScore 最高 = 半导体
    assert exposure["themeId"] == "半导体"
    # 匹配题材非 mainTheme，themeRole=leader 不得直接复用
    assert exposure["role"] != "leader"


def test_exposure_name_variant_matching():
    # 后缀变体：stock themes 用 "区块链技术"，sector 用 "区块链产业"，均应归一为 "区块链"
    stock = _stock("000001", ["区块链技术"])
    exposure = stock_theme_exposure(stock, [_theme("区块链", 80.0, 1)])
    assert exposure is not None
    assert exposure["themeId"] == "区块链"


def test_fusion_direction_sell_flips_momentum():
    base = {"status": "ok", "direction": "sell", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 90.0, 1)])
    frame = _frame_momentum(theme_scores={"A": 90})
    frame["themes"]["A"]["direction"] = "sell"
    fused = fuse_theme_resonance(base, exposure, frame)
    assert fused["direction"] == "sell"
    assert fused["theme"]["themeMomentumDirection"] == "sell"
    assert fused["theme"]["status"] == "ok"


def test_fusion_direction_hold_no_flip():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 50.0, 1)])
    frame = _frame_momentum(theme_scores={"A": 50})
    frame["themes"]["A"]["direction"] = "hold"
    fused = fuse_theme_resonance(base, exposure, frame)
    assert fused["theme"]["themeMomentumDirection"] == "hold"
    assert fused["direction"] == "buy"


def test_fusion_lifecycle_bonus_for_leader_in_mainline():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(
        _stock("000001", ["A"], theme_role="leader"),
        [_theme("A", 90.0, 1, rotation="mainline")],
    )
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 50}))
    assert fused["theme"]["adjustment"] >= 5.0


def test_fusion_keeps_base_score_visible():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 90.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 100}))
    assert fused["baseScore"] == 60
    assert fused["score"] != fused["baseScore"]


def test_fusion_crowding_missing_skips_penalty_with_flag():
    base = {"status": "ok", "direction": "buy", "score": 80, "label": "强"}
    stock = _stock("000001", ["A"], theme_role="follower")
    exposure = stock_theme_exposure(stock, [_theme("A", 90.0, 1, rotation="cooling", crowding_risk=float("nan"))])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 40.0}))
    assert fused["theme"]["status"] == "ok"
    assert "crowding_risk_missing" in fused["theme"]["reasons"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_resonance_fusion.py -q`
Expected: FAIL（`ImportError: cannot import name 'fuse_theme_resonance'`）

- [ ] **Step 3: 追加实现（`theme_momentum.py` 文件末尾追加）**

```python
def _matches_theme(value: str, theme: dict[str, Any]) -> bool:
    if _theme_id(theme) == value:
        return True
    return _is_same_theme_name(value, str(theme.get("themeName") or theme.get("name") or ""))


def _theme_name(theme: dict[str, Any]) -> str:
    return str(theme.get("themeName") or theme.get("name") or _theme_id(theme))


def _role_for(stock: dict[str, Any], theme: dict[str, Any], matched_main_theme: bool) -> str:
    explicit = str(stock.get("themeRole") or "").strip().lower()
    # themeRole 是股票级字段，只在匹配题材就是 mainTheme（或股票仅属单一题材）时可信
    if explicit in ROLE_WEIGHTS and (matched_main_theme or len(stock.get("themes") or []) <= 1):
        return explicit
    if "龙" in str(stock.get("leadStatus") or ""):
        return "leader"
    heat = _num(theme.get("heatScore"))
    change = _num(stock.get("change"))
    if heat >= 70 and change >= 5:
        return "core"
    if heat >= 45 and change > 0:
        return "follower"
    if heat < 20 or change < -5:
        return "noise"
    return "independent"


def stock_theme_exposure(
    stock: dict[str, Any],
    frame_themes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """主题材选择：mainTheme 优先，未命中时取所属题材中 heatScore 最高者。

    无映射或均不匹配时返回 None。"""
    stock_theme_values = [str(item) for item in (stock.get("themes") or []) if str(item)]
    if not stock_theme_values:
        return None
    valid = [
        theme for theme in frame_themes
        if isinstance(theme, dict) and _theme_rank_eligible(theme)
    ]
    if not valid:
        return None

    main_theme_value = str(stock.get("mainTheme") or "").strip()
    primary: dict[str, Any] | None = None
    matched_main_theme = False
    if main_theme_value:
        for theme in valid:
            if _matches_theme(main_theme_value, theme):
                primary = theme
                matched_main_theme = True
                break
    if primary is None:
        candidates = [
            theme for theme in valid
            if any(_matches_theme(value, theme) for value in stock_theme_values)
        ]
        if not candidates:
            return None
        primary = max(candidates, key=lambda theme: _num(theme.get("heatScore"), -1.0))

    role = _role_for(stock, primary, matched_main_theme)
    role_weight = ROLE_WEIGHTS.get(role, 0.15)
    contribution = _num(stock.get("themeContribution"), role_weight * 60.0)
    crowding_raw = primary.get("crowdingRisk")
    crowding_risk: float | None = None
    if isinstance(crowding_raw, (int, float)):
        numeric = float(crowding_raw)
        crowding_risk = numeric if math.isfinite(numeric) else None
    return {
        "themeId": _theme_id(primary),
        "themeName": _theme_name(primary),
        "role": role,
        "roleWeight": role_weight,
        "themeContribution": round(contribution, 2),
        "heatScore": _num(primary.get("heatScore")),
        "rotationState": str(primary.get("rotationState") or "neutral"),
        "crowdingRisk": crowding_risk,
        "matchedMainTheme": matched_main_theme,
        "reasons": [f"theme:{_theme_id(primary)}"],
    }


def fuse_theme_resonance(
    base_resonance: dict[str, Any] | None,
    exposure: dict[str, Any] | None,
    frame_momentum: dict[str, Any] | None,
) -> dict[str, Any]:
    """把题材动量并入个股共振。返回带 theme 子对象的共振结果。

    - 题材数据不足：theme.status=insufficient + reasons，baseScore 原样保留。
    - 有数据：score = clamp(base + adjustment + lifecycleBonus - lifecyclePenalty, 0, 100)，
      direction 不变，label 由调用方按新分数刷新。
    - resonance.baseScore 始终保留调节前分数，供审计与前端对比。"""
    fused = dict(base_resonance or {})
    theme_out: dict[str, Any] = {"status": "insufficient", "reasons": []}
    base_score = _num(fused.get("score"))
    fused["baseScore"] = round(base_score, 0)
    if not frame_momentum or not frame_momentum.get("crossSectionOk"):
        theme_out["reasons"].append("theme_cross_section_insufficient")
    elif exposure is None:
        theme_out["reasons"].append("theme_mapping_missing")
    else:
        momentum = (frame_momentum.get("themes") or {}).get(exposure["themeId"])
        if momentum is None or momentum.get("status") != "ok":
            theme_out["reasons"].append("theme_momentum_insufficient")
        else:
            adjustment = _clamp(
                (momentum["score"] - 50.0) * exposure["roleWeight"] * THEME_ADJUSTMENT_SCALE,
                -THEME_ADJUSTMENT_MAX,
                THEME_ADJUSTMENT_MAX,
            )
            lifecycle_bonus = 0.0
            lifecycle_penalty = 0.0
            extra_reasons: list[str] = []
            if exposure["rotationState"] in LIFECYCLE_BOOST and exposure["role"] in {"leader", "core"}:
                lifecycle_bonus = THEME_LIFECYCLE_BONUS
            if exposure["rotationState"] in LIFECYCLE_PENALTY and exposure["role"] != "leader":
                if exposure.get("crowdingRisk") is None:
                    extra_reasons.append("crowding_risk_missing")
                else:
                    lifecycle_penalty = min(
                        THEME_LIFECYCLE_PENALTY_MAX,
                        _num(exposure.get("crowdingRisk")) / THEME_LIFECYCLE_PENALTY_DENOM,
                    )
            theme_out = {
                "status": "ok",
                "themeId": exposure["themeId"],
                "themeName": exposure["themeName"],
                "role": exposure["role"],
                "roleWeight": round(exposure["roleWeight"], 2),
                "themeMomentumScore": momentum["score"],
                "themeMomentumDirection": momentum["direction"],
                "themeLifecycle": exposure["rotationState"],
                "themeContribution": exposure["themeContribution"],
                "adjustment": round(adjustment + lifecycle_bonus - lifecycle_penalty, 2),
                "reasons": exposure["reasons"] + [f"题材动量 {momentum['score']}"] + extra_reasons,
            }
            fused["score"] = round(
                _clamp(base_score + adjustment + lifecycle_bonus - lifecycle_penalty, 0, 100),
                0,
            )
    fused["theme"] = theme_out
    return fused
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_momentum.py tests/test_theme_resonance_fusion.py -q`
Expected: PASS（22 passed）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme_momentum.py quant-board/backend/tests/test_theme_resonance_fusion.py
git commit -m "feat(theme-momentum): add stock theme exposure and bounded resonance fusion"
```

## Task 3: repository 让 ranktrend projection 带 hotThemes 与股票题材字段

**Files:**
- Modify: `quant-board/backend/data/mongo_repository.py`（`load_frame_bundles` ~185 行；`_stock_rows_by_snapshot` ranktrend 投影）
- Modify: `quant-board/backend/data/repository.py`（`load_frame_bundles` ~571/607 行；`_stock_rows_by_snapshot` ranktrend 分支）
- Test: `quant-board/backend/tests/test_repository_theme_projection.py`

- [ ] **Step 0: 确认 SnapshotStockRowModel 现有列（已核验，无需 migration）**

`quant-board/backend/data/models.py` 的 `SnapshotStockRowModel` 已包含：

```text
themes_json        Text   default "[]"
theme_contribution Float  nullable
theme_role         String(32) nullable
lead_status        String(40) nullable
```

ranktrend 投影补充的 `themes/mainTheme/themeRole/themeContribution/leadStatus` 全部可映射到现有列（`mainTheme` 由 TS/Python 侧从 `themes` 首个题材名推导，不新增列）。无需数据库 migration。

- [ ] **Step 1: 写失败测试**

```python
# quant-board/backend/tests/test_repository_theme_projection.py
"""ranktrend projection 必须返回 hotThemes 与股票 themes，供题材动量计算。"""
import pytest

from backend.data.mongo_repository import MongoRepository


class FakeCollection:
    def __init__(self, rows):
        self._rows = list(rows)

    def find(self, query, projection=None):
        return self

    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def __iter__(self):
        yield from self._rows

    def count_documents(self, query):
        return 0


class FakeDb:
    def __init__(self, collections):
        self._collections = {
            name: FakeCollection(rows) for name, rows in collections.items()
        }

    def __getitem__(self, name):
        return self._collections[name]


def _frames():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "type": "half_hour",
        "tradingDate": "2026-08-04",
        "slotTime": "10:00",
        "timestamp": 1,
    }]


def _sector_rows():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "entityType": "hot_theme",
        "entityKey": "T1",
        "entityName": "T1概念板块",
        "heatScore": 80.0,
        "rank": 1,
        "rotationState": "mainline",
        "crowdingRisk": 30.0,
        "metadata": {"rankEligible": True},
    }]


def _stock_rows():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "code": "000001",
        "name": "平安银行",
        "rank": 1,
        "avgRankNum": 1.0,
        "change": 3.0,
        "volumeRatio": 1.2,
        "zlje": 10.0,
        "zljzb": 0.1,
        "themes": ["T1概念板块"],
        "mainTheme": "T1概念板块",
        "themeRole": "follower",
        "themeContribution": 30.0,
        "leadStatus": "",
    }]


def test_ranktrend_projection_includes_hot_themes_and_stock_themes():
    repo = MongoRepository(FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
        "snapshot_sector_rows": _sector_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend")
    assert len(bundles) == 1
    assert bundles[0]["hotThemes"] != []
    assert bundles[0]["hotThemes"][0]["entityType"] == "hot_theme"
    assert bundles[0]["stocks"][0]["themes"] == ["T1概念板块"]
    assert bundles[0]["stocks"][0]["themeRole"] == "follower"

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_repository_theme_projection.py -q`
Expected: FAIL（`bundles[0]["hotThemes"] != []` 断言失败——ranktrend 分支当前置空）

- [ ] **Step 3: 修改 mongo_repository.py**

`load_frame_bundles` 中两处：

```python
        sector_rows_by_snapshot = {} if projection == "ranktrend" else self._sector_rows_by_snapshot(dataset_id, snapshot_ids)
```
改为：
```python
        sector_rows_by_snapshot = self._sector_rows_by_snapshot(dataset_id, snapshot_ids)
```

```python
            if projection == "ranktrend":
                item["entities"] = []
                item["sectors"] = []
                item["hotThemes"] = []
                bundles.append(item)
                continue
```
改为：
```python
            if projection == "ranktrend":
                item["entities"] = []
                item["sectors"] = []
                item["hotThemes"] = [
                    self._sector_entity_to_view(sector)
                    for sector in sector_rows_by_snapshot.get(str(row.get("snapshotId")), [])
                    if sector.get("entityType") == "hot_theme"
                ]
                bundles.append(item)
                continue
```

`_stock_rows_by_snapshot` 的 ranktrend `mongo_projection` 字典增加题材字段，并在 item 构建中输出：

```python
            mongo_projection: dict[str, int] = {
                "_id": 0,
                "snapshotId": 1,
                "code": 1,
                "name": 1,
                "rank": 1,
                "avgRankNum": 1,
                "change": 1,
                "volumeRatio": 1,
                "zlje": 1,
                "zljzb": 1,
                "themes": 1,
                "mainTheme": 1,
                "themeRole": 1,
                "themeContribution": 1,
                "leadStatus": 1,
            }
```
并在该分支 item dict 中追加：`"themes": row.get("themes") or [], "mainTheme": row.get("mainTheme") or "", "themeRole": row.get("themeRole") or "", "themeContribution": row.get("themeContribution"), "leadStatus": row.get("leadStatus") or ""`。

- [ ] **Step 4: 修改 repository.py（SQLite 镜像路径）**

`load_frame_bundles` 中把 sector_query 的守卫去掉（原为 `if projection != "ranktrend":`），让 sector rows 始终加载：

```python
                    sector_query = (
                        select(SnapshotSectorRowModel)
                        .where(
                            SnapshotSectorRowModel.dataset_id == dataset_id,
                            SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
                        )
                        .order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
                    )
                    for row in self.session.scalars(sector_query):
                        sector_rows_by_snapshot[row.snapshot_id].append(self.local_sector_to_bundle_dict(row))
```

ranktrend 分支改为：

```python
            if projection == "ranktrend":
                item["entities"] = []
                item["sectors"] = []
                item["hotThemes"] = [
                    self._sector_entity_to_view(row)
                    for row in sector_rows_by_snapshot.get(frame.snapshot_id, [])
                    if row.get("entityType") == "hot_theme"
                ]
                bundles.append(item)
                continue
```

`_stock_rows_by_snapshot` 的 ranktrend 分支 item 追加：

```python
                                "themes": json_loads(row.themes_json, []),
                                "mainTheme": "",
                                "themeRole": row.theme_role or "",
                                "themeContribution": row.theme_contribution,
                                "leadStatus": row.lead_status or "",
```

（`json_loads` 在 repository.py 已有导入；`themes_json`/`theme_role`/`theme_contribution`/`lead_status` 均为 `SnapshotStockRowModel` 现有列。）

- [ ] **Step 5: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_repository_theme_projection.py -q`
Expected: PASS（1 passed）

- [ ] **Step 6: Commit**

```bash
git add quant-board/backend/data/mongo_repository.py quant-board/backend/data/repository.py quant-board/backend/tests/test_repository_theme_projection.py
git commit -m "feat(theme-momentum): carry hotThemes and stock theme fields in ranktrend projection"
```

## Task 4: analyze 路由接入 themeContext 与 resonance.theme

**Files:**
- Modify: `quant-board/backend/api/ranktrend_routes.py`（`_to_engine_frame`、`_analyze_frames`）
- Test: `quant-board/backend/tests/test_ranktrend_analyze_api.py`（追加题材合同测试）

- [ ] **Step 1: 写失败测试（追加到 test_ranktrend_analyze_api.py）**

```python
def _theme_frames_with_context(count=12, theme_count=25):
    frames = []
    for idx in range(count):
        slot = f"{10 + idx // 2:02d}:{30 if idx % 2 else 0:02d}"
        rows = [{
            "code": "002279",
            "name": "久其软件",
            "rank": 1,
            "avgRankNum": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
            "themes": ["主线概念"],
        }]
        hot_themes = [
            {
                "entityType": "hot_theme",
                "themeId": "T0",
                "themeName": "主线概念板块",
                "heatScore": 40.0 + idx * 5.0,
                "rank": 1,
                "rotationState": "mainline",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
        ]
        hot_themes += [
            {
                "entityType": "hot_theme",
                "themeId": f"T{i}",
                "themeName": f"普通概念{i}",
                "heatScore": 50.0,
                "rank": i + 1,
                "rotationState": "neutral",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
            for i in range(1, theme_count)
        ]
        frames.append({
            "tradingDate": "2026-08-04",
            "slotTime": slot,
            "type": "half_hour",
            "timestamp": idx + 1,
            "rows": rows,
            "stocks": rows,
            "hotThemes": hot_themes,
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        })
    return frames


def test_analyze_includes_theme_context_and_resonance_theme(monkeypatch):
    frames = _theme_frames_with_context()
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-04 15:00"],
    })
    assert response.status_code == 200
    body = response.json()
    frame = body["frames"][0]
    assert "themeContext" in frame
    assert frame["themeContext"]["themeSampleCount"] >= 20
    assert frame["themeContext"]["marketThemeMedianShortChange"] is not None
    stock = frame["stocks"][0]
    theme = stock["analysis"]["resonance"].get("theme")
    assert theme is not None
    assert theme["status"] in ("ok", "insufficient")
    if theme["status"] == "ok":
        assert theme["themeMomentumScore"] > 50
        assert theme["themeLifecycle"] == "mainline"
        assert stock["analysis"]["decision"]["final"]["signal"] in ("buy", "hold")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_analyze_api.py::test_analyze_includes_theme_context_and_resonance_theme -q`
Expected: FAIL（`'themeContext'` 不存在）

- [ ] **Step 3: 修改 ranktrend_routes.py**

1. 导入：
```python
from backend.analysis.theme_momentum import (
    compute_theme_momentum_series,
    fuse_theme_resonance,
    stock_theme_exposure,
)
from backend.analysis.ranktrend import _resonance_label
```

2. `_to_engine_frame` 增加 `"hotThemes": bundle.get("hotThemes") or []`。

3. `_analyze_frames` 开头（`wanted` 定义之后）计算一次：
```python
    momentum_series = compute_theme_momentum_series(frames)
```
帧循环内，`regime` 之后构建帧级题材上下文：
```python
        frame_momentum = momentum_series["frames"][index]
        theme_context = {
            "version": momentum_series["version"],
            "factors": sorted(
                frame_momentum["themes"].values(),
                key=lambda item: -float(item["score"]),
            )[:10],  # 响应只回传 top-10 题材动量摘要，控制体积；内部全量仍参与计算
            "marketThemeMedianShortChange": frame_momentum["marketThemeMedianShortChange"],
            "themeSampleCount": frame_momentum["themeSampleCount"],
            "qualityFlags": frame_momentum["qualityFlags"],
        }
```
`stocks_out` 循环内，把共振融合放在 `_apply_resonance_final` 之前：
```python
            analysis["resonance"] = resonance
            exposure = stock_theme_exposure(stock, frame.get("hotThemes") or [])
            analysis["resonance"] = fuse_theme_resonance(resonance, exposure, frame_momentum)
            if analysis["resonance"].get("status") == "ok":
                analysis["resonance"]["label"] = _resonance_label(analysis["resonance"].get("score"))
            _apply_resonance_final(analysis, analysis["resonance"])
```
（替换原有 `analysis["resonance"] = resonance` 与 `_apply_resonance_final(analysis, resonance)` 两行。）

4. 帧输出 dict 增加 `"themeContext": theme_context`。

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_analyze_api.py -q`
Expected: PASS（新增用例 + 既有用例全绿）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/api/ranktrend_routes.py quant-board/backend/tests/test_ranktrend_analyze_api.py
git commit -m "feat(theme-momentum): emit themeContext and resonance.theme from analyze API"
```

## Task 5: TS 类型与观察服务透传 + 测试

**Files:**
- Modify: `src/services/rankTrend/types.ts`
- Modify: `src/services/rankTrend/RankTrendObservationService.ts`
- Test: `src/services/rankTrend/__tests__/RankTrendObservationService.test.ts`

- [ ] **Step 1: 写失败测试（类型 + 观察服务题材不足 issue）**

在 `RankTrendObservationService.test.ts` 追加（沿用既有 `mockRemoteFrames` 与 `rankTrendAnalyzer.getLatestAnalysisSeries` mock 风格）：

```ts
  it('当前帧题材共振数据不足时按共振轨给出结构化原因', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianShortChange: 0, marketSampleCount: 4 }),
    )
    const currentAnalysis = {
      meta: { code: '002279' },
      resonance: {
        status: 'ok',
        direction: 'buy',
        score: 70,
        label: '强',
        marketMedianShortChange: 1.5,
        marketSampleCount: 25,
        theme: { status: 'insufficient', reasons: ['theme_cross_section_insufficient'] },
      },
    }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    const currentFrame = result.frames.at(-1)
    expect(currentFrame?.issues).toContainEqual(expect.objectContaining({
      code: 'theme_resonance_insufficient',
      track: 'resonance',
    }))
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test:ranktrend`
Expected: FAIL（`theme_resonance_insufficient` issue 未生成；类型 `theme` 未定义）

- [ ] **Step 3: 修改 types.ts**

在 `RankTrendResonance` 接口前新增：

```ts
export interface RankTrendThemeResonance {
  status: 'ok' | 'insufficient'
  themeId?: string
  themeName?: string
  role?: 'leader' | 'core' | 'follower' | 'independent' | 'noise'
  roleWeight?: number
  themeMomentumScore?: number
  themeMomentumDirection?: 'buy' | 'sell' | 'hold'
  themeLifecycle?: string
  themeContribution?: number
  adjustment?: number
  reasons: string[]
}
```

在 `RankTrendResonance` 接口内追加：

```ts
  baseScore?: number // 调节前原始共振分数（Python 融合输出，供审计与前端对比）
  theme?: RankTrendThemeResonance
```

- [ ] **Step 4: 修改 RankTrendObservationService.ts**

`load()` 的帧循环中，`isCurrent` 分支构建 issues 后追加：

```ts
      if (isCurrent && analysis?.resonance?.theme?.status === 'insufficient') {
        issues.push(
          observationIssue(
            'theme_resonance_insufficient',
            `题材共振数据不足: ${analysis.resonance.theme.reasons.join('、')}`,
            { frameKey: key, track: 'resonance' },
          ),
        )
      }
```

- [ ] **Step 5: 运行确认通过**

Run: `pnpm test:ranktrend; pnpm typecheck:ranktrend`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/rankTrend/types.ts src/services/rankTrend/RankTrendObservationService.ts src/services/rankTrend/__tests__/RankTrendObservationService.test.ts
git commit -m "feat(theme-momentum): add theme resonance contract types and observation issue"
```

## Task 6: OBSERVATION 面板与 DataTable tooltip 展示 + 测试

**Files:**
- Modify: `src/components/panels/RankTrendObservationPanel.vue`
- Modify: `src/components/common/DataTable.vue`
- Test: `src/components/panels/__tests__/RankTrendObservationPanel.test.ts`、`src/components/common/__tests__/DataTable.test.ts`

- [ ] **Step 1: 写失败测试（面板共振轨题材因子行 + tooltip 题材段）**

`RankTrendObservationPanel.test.ts` 追加（沿用既有 `source()` helper）：

```ts
test('resonance track includes theme momentum factor rows', () => {
  const panel = source()
  expect(panel).toContain("label: '题材动量'")
  expect(panel).toContain("label: '题材生命周期'")
  expect(panel).toContain("label: '个股角色'")
  expect(panel).toContain("label: '题材调节'")
})
```

`DataTable.test.ts` 追加（沿用既有 `dataTableSource()` helper）：

```ts
test('resonance tooltip includes theme momentum section', () => {
  const source = dataTableSource()
  expect(source).toContain('【题材动量】')
  expect(source).toContain('themeMomentumScore')
  expect(source).toContain('题材数据不足')
})
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- src/components/panels/__tests__/RankTrendObservationPanel.test.ts src/components/common/__tests__/DataTable.test.ts`
Expected: FAIL（源码不含新字符串）

- [ ] **Step 3: 修改 RankTrendObservationPanel.vue**

`resonanceFactors` computed 内，`return [` 数组末尾（`反转惩罚` 行之后）追加：

```ts
    ...(resonance?.theme?.status === 'ok'
      ? [
          {
            label: '题材动量',
            width: percent(((Number(resonance.theme.themeMomentumScore) || 50) - 50) / 50),
            text: signedPercent(((Number(resonance.theme.themeMomentumScore) || 50) - 50) / 50),
            tone: Number(resonance.theme.themeMomentumScore || 0) >= 50 ? 'positive-tone' : 'negative-tone',
          },
          { label: '题材生命周期', width: 0, text: resonance.theme.themeLifecycle || '—', tone: 'neutral-tone' },
          { label: '个股角色', width: 0, text: themeRoleLabel(resonance.theme.role), tone: 'neutral-tone' },
          {
            label: '题材调节',
            width: percent((Number(resonance.theme.adjustment) || 0) / 100),
            text: signedPercent((Number(resonance.theme.adjustment) || 0) / 100),
            tone: Number(resonance.theme.adjustment || 0) >= 0 ? 'positive-tone' : 'negative-tone',
          },
        ]
      : resonance?.theme?.status === 'insufficient'
        ? [{ label: '题材数据', width: 0, text: `不足: ${resonance.theme.reasons.join('、')}`, tone: 'neutral-tone' }]
        : []),
```

并在 `<script setup>` 内新增 role 中文映射 helper：

```ts
function themeRoleLabel(role?: string): string {
  const labels: Record<string, string> = {
    leader: '龙头',
    core: '核心',
    follower: '跟随',
    independent: '独立',
    noise: '噪声',
  }
  return role ? labels[role] || role : '—'
}
```

- [ ] **Step 4: 修改 DataTable.vue tooltip**

`【共振路径】` 段落内，`resonance.status === 'insufficient'` 分支结束后追加：

```ts
  if (resonance.theme) {
    title += '\n【题材动量】\n'
    if (resonance.theme.status === 'ok') {
      title += `题材: ${resonance.theme.themeName || '—'}\n`
      title += `题材动量: ${formatTooltipNumber(resonance.theme.themeMomentumScore, 0)}% · 角色: ${themeRoleLabel(resonance.theme.role)}\n`
      title += `调节: ${(resonance.theme.adjustment ?? 0) >= 0 ? '+' : ''}${formatTooltipNumber(resonance.theme.adjustment, 1)}%\n`
    } else {
      title += `题材数据不足: ${resonance.theme.reasons.join('、')}\n`
    }
  }
```

在 DataTable.vue 的 `<script setup>` 内新增与面板相同的 `themeRoleLabel` helper（若文件内已有 label map，优先并入）：

```ts
function themeRoleLabel(role?: string): string {
  const labels: Record<string, string> = {
    leader: '龙头',
    core: '核心',
    follower: '跟随',
    independent: '独立',
    noise: '噪声',
  }
  return role ? labels[role] || role : '—'
}
```

- [ ] **Step 5: 运行确认通过**

Run: `pnpm test -- src/components/panels/__tests__/RankTrendObservationPanel.test.ts src/components/common/__tests__/DataTable.test.ts; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/components/panels/RankTrendObservationPanel.vue src/components/common/DataTable.vue src/components/panels/__tests__/RankTrendObservationPanel.test.ts src/components/common/__tests__/DataTable.test.ts
git commit -m "feat(theme-momentum): render theme momentum in observation track and tooltip"
```

## Task 7: 题材动量验证函数（基线 vs 调节）+ 单测

**Files:**
- Create: `quant-board/backend/analysis/theme_momentum_validation.py`
- Test: `quant-board/backend/tests/test_theme_momentum_validation.py`

- [ ] **Step 1: 写失败测试**

```python
# quant-board/backend/tests/test_theme_momentum_validation.py
from backend.analysis.theme_momentum_validation import compare_theme_momentum_rolling


def _frame(index, stock_code, themes, heat_rows):
    return {
        "tradingDate": "2026-08-04",
        "slotTime": f"{index:02d}:00",
        "type": "half_hour",
        "timestamp": index,
        "stocks": [{"code": stock_code, "themes": themes, "change": 3.0}],
        "hotThemes": heat_rows,
    }


def _rolling_frames(count=12):
    frames = []
    for idx in range(count):
        hot = [{
            "entityType": "hot_theme",
            "themeId": "T0",
            "themeName": "主线概念板块",
            "heatScore": 40.0 + idx * 5.0,
            "rank": 1,
            "rotationState": "mainline",
            "crowdingRisk": 30.0,
            "metadata": {"rankEligible": True},
        }]
        hot += [{
            "entityType": "hot_theme",
            "themeId": f"T{i}",
            "themeName": f"普通概念{i}",
            "heatScore": 50.0,
            "rank": i + 1,
            "rotationState": "neutral",
            "crowdingRisk": 30.0,
            "metadata": {"rankEligible": True},
        } for i in range(1, 25)]
        frames.append(_frame(idx, "000001", ["主线概念"], hot))
    return frames


def test_compare_rolling_reports_multi_frame_stats():
    frames = _rolling_frames()
    base_resonance_by_frame = [
        {"000001": {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}}
        for _ in frames
    ]
    result = compare_theme_momentum_rolling(frames, base_resonance_by_frame)
    assert result["ok"] is True
    assert result["frameCount"] >= 3
    assert result["adjustedCount"] >= 1
    assert result["insufficientCount"] == 0
    assert result["meanAdjustment"] > 0
    assert result["adjustmentByLifecycle"].get("mainline", 0) > 0
    assert result["directionDistribution"].get("buy", 0) >= 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_momentum_validation.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现验证函数**

```python
# quant-board/backend/analysis/theme_momentum_validation.py
"""题材动量验证：多帧滚动对比基线/调节共振分数与排序位移（研究用，不触回测引擎）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.analysis.theme_momentum import (
    THEME_SERIES_MIN_BARS,
    compute_theme_momentum_series,
    fuse_theme_resonance,
    stock_theme_exposure,
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compare_theme_momentum_rolling(
    frames: list[dict[str, Any]],
    base_resonance_by_frame: list[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """逐帧（bars >= THEME_SERIES_MIN_BARS）滚动对比基线/调节分数与排序位移。

    base_resonance_by_frame 与 frames 等长，每项为 {code: 该帧基础共振}。"""
    momentum_series = compute_theme_momentum_series(frames)
    if not momentum_series["frames"]:
        return {"ok": False, "reason": "empty_frames"}
    aggregate: dict[str, Any] = {
        "adjustedCount": 0,
        "insufficientCount": 0,
        "adjustments": [],
        "rankShifts": [],
        "adjustmentByLifecycle": defaultdict(list),
        "directionDistribution": defaultdict(int),
    }
    per_frame: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if index < THEME_SERIES_MIN_BARS - 1:
            continue
        frame_momentum = momentum_series["frames"][index]
        base_by_code = (
            base_resonance_by_frame[index]
            if index < len(base_resonance_by_frame)
            else {}
        )
        rows: list[dict[str, Any]] = []
        for stock in frame.get("stocks") or []:
            code = str(stock.get("code") or "")
            base = base_by_code.get(code)
            if not base:
                continue
            exposure = stock_theme_exposure(stock, frame.get("hotThemes") or [])
            fused = fuse_theme_resonance(base, exposure, frame_momentum)
            theme = fused.get("theme") or {}
            rows.append({
                "code": code,
                "baseScore": round(float(base.get("score") or 0)),
                "fusedScore": round(float(fused.get("score") or 0)),
                "adjustment": float(theme.get("adjustment") or 0),
                "themeStatus": str(theme.get("status") or "insufficient"),
                "lifecycle": str(theme.get("themeLifecycle") or "neutral"),
                "direction": str(theme.get("themeMomentumDirection") or "hold"),
            })
        rows.sort(key=lambda item: item["fusedScore"], reverse=True)
        base_order = sorted(rows, key=lambda item: item["baseScore"], reverse=True)
        base_index = {item["code"]: position for position, item in enumerate(base_order)}
        for position, item in enumerate(rows):
            aggregate["adjustments"].append(item["adjustment"])
            aggregate["rankShifts"].append(base_index[item["code"]] - position)
            aggregate["adjustmentByLifecycle"][item["lifecycle"]].append(item["adjustment"])
            aggregate["directionDistribution"][item["direction"]] += 1
            if item["themeStatus"] == "ok":
                aggregate["adjustedCount"] += 1
            else:
                aggregate["insufficientCount"] += 1
        per_frame.append({
            "frameKey": f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip(),
            "themeSampleCount": frame_momentum["themeSampleCount"],
            "rows": rows,
        })
    adjustments = aggregate["adjustments"]
    rank_shifts = aggregate["rankShifts"]
    return {
        "ok": True,
        "frameCount": len(per_frame),
        "themeSampleCountMin": min(
            (item["themeSampleCount"] for item in per_frame), default=0
        ),
        "adjustedCount": aggregate["adjustedCount"],
        "insufficientCount": aggregate["insufficientCount"],
        "meanAdjustment": round(_mean(adjustments), 2),
        "meanAbsAdjustment": round(_mean([abs(value) for value in adjustments]), 2),
        "meanAbsRankShift": round(_mean([abs(value) for value in rank_shifts]), 2),
        "maxRankShift": max((abs(value) for value in rank_shifts), default=0),
        "adjustmentByLifecycle": {
            lifecycle: round(_mean(values), 2)
            for lifecycle, values in aggregate["adjustmentByLifecycle"].items()
        },
        "directionDistribution": dict(aggregate["directionDistribution"]),
        "frames": per_frame,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_momentum_validation.py -q`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme_momentum_validation.py quant-board/backend/tests/test_theme_momentum_validation.py
git commit -m "feat(theme-momentum): add multi-frame rolling baseline vs adjusted comparison"
```

> **范围说明（对应设计 §9.1）：** 官方 `POST /api/backtests/theme-confluence` 的"实验组"需要回测引擎支持按题材动量调节候选排序，属于独立研究任务，不在本计划内改回测主链。本计划的验证覆盖：① golden case（Task 1/2/4 单测）；② 多帧滚动"基线 vs 调节"排序对比（Task 7，回答"调节是否系统性改变排序、方向是否与生命周期一致"）；③ 首日 live 观察（Task 9）。theme-confluence A/B 作为 live 观察后的 follow-up 任务另行立项（P1），设计 §9.1 已同步为降级表述。

## Task 8: 文档同步

**Files:**
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/api-cli.md`

- [ ] **Step 1: architecture.md 补充 analyze 响应字段**

在 RankTrend analyze API 相关段落追加：`POST /api/ranktrend/analyze` 响应帧新增 `themeContext`（version/factors/marketThemeMedianShortChange/themeSampleCount/qualityFlags），每股 `analysis.resonance.theme`（status/themeId/themeName/role/roleWeight/themeMomentumScore/themeMomentumDirection/themeLifecycle/themeContribution/adjustment/reasons）；题材动量由 `backend/analysis/theme_momentum.py` 纯函数计算，来源为已落库 `snapshot_sector_rows`，不新增集合。

- [ ] **Step 2: api-cli.md 同步请求/响应示例**

在 analyze 响应示例中补充 `themeContext` 与 `resonance.theme` 字段示例，说明题材不足时 `theme.status=insufficient` 且基础共振分数不变。

- [ ] **Step 3: 检查主题模块索引**

`docs/theme-module/README.md` 已在本任务开始前更新（设计文档与实施计划索引）。如实现期间发生字段/文件名变更，同步修正索引。

- [ ] **Step 4: Commit**

```bash
git add quant-board/docs/architecture.md quant-board/docs/api-cli.md docs/theme-module/README.md docs/theme-module/plans/2026-08-04-theme-momentum-resonance-plan.md
git commit -m "docs(theme-momentum): document analyze themeContext and resonance.theme contract"
```

## Task 9: 全量验证与首日观察清单

**Files:** 无（验收任务）

- [ ] **Step 1: Python 全量**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest -q`
Expected: 全部通过，无新增失败

- [ ] **Step 2: TS 全量**

Run: `pnpm test; pnpm test:ranktrend; pnpm typecheck:ranktrend; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 全部通过

- [ ] **Step 3: 浏览器验收（Playwright）**

启动 QuantBoard 8000 与 Vite 5173，验收：
- OBSERVATION 共振轨渲染题材动量/题材生命周期/个股角色/题材调节四行（有题材数据时）或"题材数据不足 + 原因"；
- DataTable 共振 tooltip 显示【题材动量】段；
- 控制台无错误；桌面视口无横向溢出。

另做一次 analyze 延时对比：改动前基线 vs 改动后（同一 30 帧 Mongo 请求），记录 P95 延时增量；预期额外加载 ~239 行/帧的 sector rows 与 top-10 题材摘要，延时增量应 < 200ms，否则回看 Task 3 的投影字段裁剪。

- [ ] **Step 4: 首日上线人工验证清单**

1. Mongo 直查 `snapshot_sector_rows`：half_hour 槽位连续、`entityType=hot_theme` 行数稳定；
2. `POST /api/ranktrend/analyze` 返回 `themeContext` 非空、`themeSampleCount >= 20`；
3. 共振分布与旧版对比：全表无异常归零，`insufficient` 仅出现在真实缺槽场景；
4. 前端共振列/观察面板渲染与 tooltip 无异常。

- [ ] **Step 5: 风险复核**

- 双动量同质化：调节幅度已限 ±15，golden case 固定，theme-confluence 回测对比记录存档到 `docs/theme-module/`；
- 板块动量拥挤后期失效：生命周期门禁 + 反转惩罚通道已实现；
- 5 分钟 vs 半小时粒度：题材动量只按半小时槽位序列计算，`computedAt` 保留在 metadata 供审计；
- 回退：所有 Python/TS 改动为向后兼容字段扩展，可逐文件回退。
