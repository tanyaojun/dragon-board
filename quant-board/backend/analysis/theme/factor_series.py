"""因子时间序列小算子（Phase 3 研究纯函数，设计文档 §5.1 D2/D3、§5.2 F1）。

三个候选因子的逐日序列构建器，输入统一为 {date: 值} 观测字典，输出 {date: 值|None}：
  sharpe_momentum       D2 风险调整动量：trailing window 个有值观测的 mean/std（总体 std），
                        std=0 或观测不足 → None（不伪造中性值）
  top_membership_streak D3 动量连续性：逐日连续保持 Top 集合成员的计数；缺勤日 None 断链
                        （同 top1_streaks 口径）、观测但落选归 0
  level_streak          持续性（persistenceScore 重建日级口径，Q1=c）：逐日连续保持
                        value ≥ threshold 的计数；None 日断链、低于阈值归零、断链后
                        首个达标日=1。与 D3 不同型（绝对水平阈值 vs 截面排名成员），
                        两者同面板对照防双持续性因子重复计分
  positive_streak       F1 资金流持续性：连续 >threshold 天数；None 断链、≤threshold 归零、
                        断链后首个正值=1（不回补断点前）
日期按字典序升序推进；缺失日如实 None/不入窗，不伪造、不中断。
"""

from __future__ import annotations


def sharpe_momentum(
    changes_by_day: dict[str, float],
    *,
    window: int = 20,
    min_periods: int = 20,
) -> dict[str, float | None]:
    """D2 风险调整动量：当日值在 trailing window 个有值观测内的 mean/std。

    尺度不变（mean/std 对整体线性变换不敏感），百分数与小数口径的 Sharpe 排序一致；
    std=0（全并列平稳序列）与观测数 <min_periods → None。日期需零填充可排序。
    """
    if window < 1 or min_periods < 1:
        raise ValueError(f"window/min_periods must be >= 1, got window={window}, min_periods={min_periods}")
    if min_periods > window:
        raise ValueError(f"min_periods must be <= window, got min_periods={min_periods}, window={window}")
    out: dict[str, float | None] = {}
    hist: list[float] = []
    for d in sorted(changes_by_day):
        v = changes_by_day[d]
        if v is None:
            out[d] = None
            continue
        hist.append(float(v))
        if len(hist) < min_periods:
            out[d] = None
            continue
        win = hist[-window:]
        n = len(win)
        mean = sum(win) / n
        var = sum((x - mean) ** 2 for x in win) / n
        if var == 0:
            out[d] = None
            continue
        out[d] = mean / (var ** 0.5)
    return out


def top_membership_streak(
    top_by_day: dict[str, set[str]],
    observed_by_day: dict[str, set[str]],
    theme: str,
) -> dict[str, int | None]:
    """D3 动量连续性：theme 逐日连续保持 Top 集合成员的计数。

    以 observed_by_day 的并集日历推进：题材未观测日 → None（断链，下个观测日重计）；
    观测但不在当日 Top 集合（或当日无 Top 集合）→ 0；在集合 → 前值 +1（断链后重计为 1）。
    """
    days = sorted(set(top_by_day) | set(observed_by_day))
    out: dict[str, int | None] = {}
    streak = 0
    broken = True
    for d in days:
        if theme not in observed_by_day.get(d, set()):
            out[d] = None
            broken = True
            continue
        if theme in top_by_day.get(d, set()):
            streak = 1 if broken else streak + 1
            out[d] = streak
            broken = False
        else:
            streak = 0
            out[d] = 0
            broken = False
    return out


def level_streak(
    values_by_day: dict[str, float | None],
    *,
    threshold: float = 70.0,
) -> dict[str, int | None]:
    """持续性（日级，persistenceScore 重建立项 Q1=c）：连续保持 value ≥ threshold 的天数。

    与 top_membership_streak（截面 Top 成员连续）不同型：本算子衡量"持续处于高位
    水平"（绝对阈值），D3 衡量"持续留在头部集合"（相对排名）。
    观测但 value < threshold → 0；≥ threshold → 连续计数，断链后首个达标日=1；
    None 日（有观测无值）→ None 断链。未观测日由调用方填入显式 None（断链），
    不静默跳过——与 D3 的 observed 日历断链语义一致。
    """
    out: dict[str, int | None] = {}
    streak = 0
    broken = True
    for d in sorted(values_by_day):
        v = values_by_day[d]
        if v is None:
            out[d] = None
            broken = True
            continue
        if v >= threshold:
            streak = 1 if broken else streak + 1
            out[d] = streak
            broken = False
        else:
            streak = 0
            out[d] = 0
            broken = False
    return out


def positive_streak(
    values_by_day: dict[str, float | None],
    *,
    threshold: float = 0.0,
) -> dict[str, int | None]:
    """F1 资金流持续性：逐日连续 >threshold 的天数。

    None 日（数据缺失）→ None 断链；值 ≤threshold → 0；>threshold → 连续计数，
    断链后首个正值=1（观测首日即正不回补断点前，与 sg3 前置证据口径同源）。
    """
    out: dict[str, int | None] = {}
    streak = 0
    broken = True
    for d in sorted(values_by_day):
        v = values_by_day[d]
        if v is None:
            out[d] = None
            broken = True
            continue
        if v > threshold:
            streak = 1 if broken else streak + 1
            out[d] = streak
            broken = False
        else:
            streak = 0
            out[d] = 0
            broken = False
    return out
