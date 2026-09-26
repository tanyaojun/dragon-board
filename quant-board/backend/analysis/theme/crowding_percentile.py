"""分位数拥挤度小模块（Phase 2 研究纯函数，设计文档 §5.1 D1）。

现有 crowdingRisk 是纯瞬时合成（量比溢价 + 高涨股占比，heat.py `_crowding_risk`），
无历史基线；本模块提供 D1 的分位数口径原料（研究侧）：
  theme_amount_share   题材成交额占采集池比重（一股多题材重复计入，白名单口径）
  theme_turnover_mean  题材成员换手率等权均值（缺位成员跳过）
  rolling_percentile   当日值在含当日的 trailing 观测窗内的弱占比分位（0-100），
                       观测数 < min_periods 输出 None（不伪造 50 中性值）
  combine_equal_weight 两序列等权合成（单侧缺失取另一侧）
fail-visible：缺日/缺成员如实 None/跳过，不伪造、不中断。研究参数（window/
min_periods）由 Phase 2 runner 对照后提案，不落默认。
"""

from __future__ import annotations

MIN_PERIODS_DEFAULT = 10
WINDOW_DEFAULT = 60


def theme_amount_share(
    stock_amounts: dict[str, float],
    theme_members: dict[str, set[str]],
) -> dict[str, float]:
    """题材成员股 amount 和 / 当日采集池 amount 总和。

    一股多题材重复计入是既定白名单口径（各题材份额独立、全题材份额和可 >1）；
    池外成员计 0（分母仍是池总和）。池总和 <= 0 或无数据 → {}。
    """
    pool_total = sum(v for v in stock_amounts.values() if v is not None)
    if pool_total <= 0:
        return {}
    out: dict[str, float] = {}
    for theme, codes in theme_members.items():
        member_sum = sum((stock_amounts.get(code) or 0.0) for code in codes)
        out[theme] = member_sum / pool_total
    return out


def theme_turnover_mean(
    stock_turnover: dict[str, float | None],
    theme_members: dict[str, set[str]],
) -> dict[str, float | None]:
    """题材成员换手率等权均值；无任何可用成员 → None（不伪造 0）。"""
    out: dict[str, float | None] = {}
    for theme, codes in theme_members.items():
        vals = [stock_turnover[c] for c in codes if stock_turnover.get(c) is not None]
        out[theme] = sum(vals) / len(vals) if vals else None
    return out


def rolling_percentile(
    values: dict[str, float | None],
    *,
    window: int = WINDOW_DEFAULT,
    min_periods: int = MIN_PERIODS_DEFAULT,
) -> dict[str, float | None]:
    """逐日弱占比分位：当日值在 trailing window 个有值观测（含当日）中 <= 当日的占比×100。

    日期按字典序升序；缺失日（None）输出 None 且不入窗（trailing 观测=有值观测）；
    窗内观测数 < min_periods → None。全并列时弱占比 = 100（<= 口径，显式声明）。
    设计目标 window=60（一年分位数不可行，Phase 0 裁决 60 日起步）。
    """
    if window < 1 or min_periods < 1:
        raise ValueError(f"window/min_periods must be >= 1, got window={window}, min_periods={min_periods}")
    if min_periods > window:
        raise ValueError(f"min_periods must be <= window, got min_periods={min_periods}, window={window}")
    out: dict[str, float | None] = {}
    hist: list[float] = []
    for d in sorted(values):
        v = values[d]
        if v is None:
            out[d] = None
            continue
        hist.append(float(v))
        if len(hist) < min_periods:
            out[d] = None
            continue
        win = hist[-window:]
        cur = win[-1]
        le = sum(1 for x in win if x <= cur)
        out[d] = le / len(win) * 100.0
    return out


def combine_equal_weight(
    p1: dict[str, float | None],
    p2: dict[str, float | None],
) -> dict[str, float | None]:
    """两序列等权合成；单侧 None 取另一侧，双侧 None → None（不伪造）。"""
    out: dict[str, float | None] = {}
    for d in sorted(set(p1) | set(p2)):
        a = p1.get(d)
        b = p2.get(d)
        if a is None and b is None:
            out[d] = None
        elif a is None:
            out[d] = float(b)
        elif b is None:
            out[d] = float(a)
        else:
            out[d] = (float(a) + float(b)) / 2.0
    return out
