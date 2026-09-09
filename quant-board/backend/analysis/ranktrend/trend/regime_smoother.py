"""Regime score 平滑包装（WP2b）。

market_regime 纯函数本体不动：本包装只在其输出 dict 上做 EMA 与 strong 边界迟滞。
直通条件（alpha>=1 且迟滞关）原样返回同一 dict——引擎侧可据引用相等短路，保证零行为变化。
state 迟滞仅作用于 strong↔非 strong 边界（门禁 regimeGateStrongBan 仅消费 strong）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.trend.risk import (
    REGIME_NORMAL_SCORE,
    REGIME_STRONG_SCORE,
    REGIME_WEAK_SCORE,
)


class RegimeSmoother:
    def __init__(
        self,
        alpha: float = 1.0,
        hysteresis: bool = False,
        strong_enter: float = REGIME_STRONG_SCORE,
        strong_exit_band: float = 5.0,
        normal_enter: float = REGIME_NORMAL_SCORE,
        weak_enter: float = REGIME_WEAK_SCORE,
    ) -> None:
        self._alpha = float(alpha)
        self._hysteresis = bool(hysteresis)
        self._strong_enter = float(strong_enter)
        self._strong_exit = float(strong_enter) - float(strong_exit_band)
        self._normal_enter = float(normal_enter)
        self._weak_enter = float(weak_enter)
        self._ema: float | None = None
        self._prev_state: str | None = None

    def reset(self) -> None:
        self._ema = None
        self._prev_state = None

    def smooth(self, regime: dict[str, Any]) -> dict[str, Any]:
        if self._alpha >= 1.0 and not self._hysteresis:
            return regime  # 直通：同一引用，零行为变化
        raw_score = float(regime.get("score") or 0.0)
        self._ema = raw_score if self._ema is None else self._alpha * raw_score + (1.0 - self._alpha) * self._ema
        smoothed = dict(regime)
        smoothed["score"] = self._ema
        # spec §2b：state 由 EMA 后的分数判定，阈值与 market_regime 同源（70/50/30）。
        # 历史（2026-09-09 2c 扫描发现）：首版实现 state=raw_state 原样透传，致 α 轴
        # 扫描全档与 baseline 逐位一致；现改为整体重判，迟滞带仅在 strong 退出侧叠加。
        state = (
            "strong" if self._ema >= self._strong_enter
            else "normal" if self._ema >= self._normal_enter
            else "weak" if self._ema >= self._weak_enter
            else "retreat"
        )
        if self._hysteresis:
            prev = self._prev_state
            if prev == "strong" and self._ema >= self._strong_exit and state != "strong":
                state = "strong"  # 迟滞带内保持
        self._prev_state = state
        smoothed["state"] = state
        reasons = list(regime.get("reasons") or [])
        reasons.append(f"regime score EMA 平滑生效（α={self._alpha:g}）")
        smoothed["reasons"] = reasons
        return smoothed
