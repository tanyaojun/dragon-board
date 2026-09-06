"""Regime score 平滑包装（WP2b）。

market_regime 纯函数本体不动：本包装只在其输出 dict 上做 EMA 与 strong 边界迟滞。
直通条件（alpha>=1 且迟滞关）原样返回同一 dict——引擎侧可据引用相等短路，保证零行为变化。
state 迟滞仅作用于 strong↔非 strong 边界（门禁 regimeGateStrongBan 仅消费 strong）。
"""
from __future__ import annotations

from typing import Any


class RegimeSmoother:
    def __init__(
        self,
        alpha: float = 1.0,
        hysteresis: bool = False,
        strong_enter: float = 70.0,
        strong_exit_band: float = 5.0,
    ) -> None:
        self._alpha = float(alpha)
        self._hysteresis = bool(hysteresis)
        self._strong_enter = float(strong_enter)
        self._strong_exit = float(strong_enter) - float(strong_exit_band)
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
        raw_state = str(regime.get("state") or "")
        state = raw_state
        if self._hysteresis:
            prev = self._prev_state
            if self._ema >= self._strong_enter:
                state = "strong"
            elif prev == "strong" and self._ema >= self._strong_exit:
                state = "strong"  # 迟滞带内保持
            # 其余情况沿用 market_regime 原值
        self._prev_state = state
        smoothed["state"] = state
        reasons = list(regime.get("reasons") or [])
        reasons.append(f"regime score EMA 平滑生效（α={self._alpha:g}）")
        smoothed["reasons"] = reasons
        return smoothed
