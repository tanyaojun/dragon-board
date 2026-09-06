"""门控多帧确认状态机（WP2a）。

纯状态、无 I/O：per-key 连续计数 + 已确认值记忆。默认 K=1 直通 = 现行为。
状态生命周期归引擎实例/请求级持有；replay 入口必须 reset()（两次 replay 互不污染）。
"""
from __future__ import annotations

from typing import Dict


def gate_reason(label: str, streak: int, required: int) -> str:
    return f"{label} 单帧确认未达（{streak}/{required}），暂缓"


class GateConfirmState:
    """布尔门（veto）与值门（lc_tier B/D）共用的连续 K 帧确认状态机。"""

    def __init__(self, required_frames: int = 1) -> None:
        self._required = max(int(required_frames), 1)
        self._streaks: Dict[str, int] = {}
        self._confirmed: Dict[str, str] = {}

    @property
    def required_frames(self) -> int:
        return self._required

    def reset(self) -> None:
        self._streaks.clear()
        self._confirmed.clear()

    def streak(self, key: str) -> int:
        return self._streaks.get(key, 0)

    def confirm(self, key: str, *, condition: bool) -> bool:
        if self._required <= 1:
            return bool(condition)
        if not condition:
            self._streaks[key] = 0
            return False
        self._streaks[key] = self.streak(key) + 1
        return self._streaks[key] >= self._required

    def confirmed_value(
        self,
        key: str,
        value: str,
        *,
        when_in: tuple[str, ...],
        default: str,
    ) -> str:
        if self._required <= 1 or value not in when_in:
            if value not in when_in:
                self._streaks[key] = 0
                self._confirmed[key] = value
            return value
        self._streaks[key] = self.streak(key) + 1
        if self._streaks[key] >= self._required:
            self._confirmed[key] = value
            return value
        return self._confirmed.get(key, default)
