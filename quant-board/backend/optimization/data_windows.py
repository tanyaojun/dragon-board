# -*- coding: utf-8 -*-
"""标准数据窗口划分（防过拟合 A/B 落地，2026-08-19）。

窗口口径（769 帧 half_hour，2026-04-15 ~ 2026-08-14）：

- TRAIN  = 2026-04-15 ~ 2026-05-31（291 帧）——调参主窗口
- VAL    = 2026-06-01 ~ 2026-06-30（209 帧）——阶段内验证（单调性/峰值稳定性）
- TEST   = 2026-07-01 ~ 2026-07-31（159 帧）——含 7 月股灾，风险对照
- FINAL  = 2026-08-01 ~ 2026-08-14（110 帧）——**冻结最终验证集**：
  任何参数/因子决策禁止使用 FINAL 做调整依据，仅允许最终报告呈现
  （此前 8 月已被 G1-G7/方向 A-C 反复使用——自 2026-08-19 起冻结为验证集）。

约束：
- 参数决策只能看 TRAIN+VAL+TEST（walk-forward 滚动，见 rolling_windows）；
- FINAL 只读，用于验收报告；新参数上线前必须过 FINAL 但不得因 FINAL 结果回改参数。
"""
from __future__ import annotations

from typing import Iterator

TRAIN_START = "2026-04-15"
TRAIN_END = "2026-05-31"
VAL_START = "2026-06-01"
VAL_END = "2026-06-30"
TEST_START = "2026-07-01"
TEST_END = "2026-07-31"
FINAL_START = "2026-08-01"
FINAL_END = "2026-08-14"

# ---- RankTrend 复跑批次窗口（B-202610 口径，2026-09-16 用户裁决）----
# decision = in-sample 锚定窗（train+val+test 全域）；
# oos1 与 FINAL 冻结窗无缝衔接；FINAL 冻结纪律对四窗全部适用（assert_not_frozen）。
# oos2 = 9 月全月（09-13 前的帧已被阶段 0-26 harness 消费，结论须标注"含已消费帧"折扣）；
# oos2u = 09-13~09-30 未消费裁决子窗——判定卡 OOS 判定读数以此为准（M3 窗口消费折扣）。
# oos2u 消费禁令（2026-09-16 起）：09-13 后产生的帧除批次执行外不得跑结论性扫描
# （只读数据质量盘点不受限）；见 docs/ranktrend-tier-backtest/ranktrend-202610-rerun-plan.md §2.1。
DECISION_START = "2026-04-15"
DECISION_END = "2026-07-31"
OOS1_START = "2026-08-15"
OOS1_END = "2026-08-31"
OOS2_START = "2026-09-01"
OOS2_END = "2026-09-30"
OOS2U_START = "2026-09-13"
OOS2U_END = "2026-09-30"

WINDOWS: dict[str, tuple[str, str]] = {
    "train": (TRAIN_START, TRAIN_END),
    "val": (VAL_START, VAL_END),
    "test": (TEST_START, TEST_END),
    "final": (FINAL_START, FINAL_END),
    "decision": (DECISION_START, DECISION_END),
    "oos1": (OOS1_START, OOS1_END),
    "oos2": (OOS2_START, OOS2_END),
    "oos2u": (OOS2U_START, OOS2U_END),
}

_FROZEN_WINDOW = "final"


def in_window(frame: dict, start: str, end: str) -> bool:
    d = str(frame.get("tradingDate") or "")
    return start <= d <= end


def split_window(frames: list[dict], window: str) -> list[dict]:
    """按标准窗口名切分帧（window 取值 WINDOWS 的键）。"""
    start, end = WINDOWS[window]
    return [f for f in frames if in_window(f, start, end)]


def rolling_windows(
    frames: list[dict],
    train_start: str = TRAIN_START,
    test_end: str = TEST_END,
) -> Iterator[dict[str, list[dict]]]:
    """滚动 walk-forward 窗口（4-5 月 train / 6 月 val / 7 月 test）。

    每个候选参数评估必须按此序列滚动：候选在 TRAIN 校准 → VAL 单调性检查 →
    TEST 样本外确认；全部通过后才允许看 FINAL（只读，不回改）。
    禁止越窗（如直接拿 7 月调参、8 月确认）。
    """
    yield {
        "train": [f for f in frames if in_window(f, train_start, TRAIN_END)],
        "val": split_window(frames, "val"),
        "test": split_window(frames, "test"),
    }


def assert_not_frozen(frames: list[dict], purpose: str) -> None:
    """守卫：禁止把 FINAL（8 月）窗口用作参数决策依据。

    参数扫描/定值评估前调用；若传入的 frames 包含 FINAL 帧且 purpose 非报告用途则抛错。
    """
    final = [f for f in frames if in_window(f, FINAL_START, FINAL_END)]
    if final and purpose != "report":
        raise ValueError(
            f"8 月冻结窗口（FINAL {FINAL_START}~{FINAL_END}）禁止用于参数决策（purpose={purpose}）；"
            f"仅最终报告可用（purpose='report'）"
        )
