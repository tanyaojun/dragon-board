"""SG 轮动交易信号算子（Phase R3，设计文档 §5.4，纯函数，不写库不改默认值）。

三信号统一输出合同 {date: bool | None}：True=当日触发；False=可判定但未触发；
None=不可判定（无前置证据/序列断链），不伪造。日期按字典序累计；None 日断链
（与 regime.top1_streaks / transition_counts 同口径），断链后首个已知日因前日
状态不可知输出 None。

- SG1 RRG 象限迁移：lagging→improving（低位启动）、weakening→leading（回封主线）；
- SG2 rotationState 切换：outflow→inflow、neutral→inflow 首日切换；
- SG3 资金转正初现：连续非正（≤0）后首次满足连续 positive_min_days 天 >0 的首日。
"""

from __future__ import annotations

from backend.analysis.theme.daily_series import virtual_index

RRG_LEADING = "leading"
RRG_WEAKENING = "weakening"
RRG_LAGGING = "lagging"
RRG_IMPROVING = "improving"

SG1_MIGRATION_PAIRS = frozenset({("lagging", "improving"), ("weakening", "leading")})
SG2_SWITCH_PAIRS = frozenset({("outflow", "inflow"), ("neutral", "inflow")})


def rrg_quadrants(changes: list[float], benchmark_changes: list[float]) -> list[str | None]:
    """题材日 change 序列 vs 基准日 change 序列 → 逐日 RRG 象限（首日动量不可知 → None）。

    RS 线 = 题材虚拟指数 / 基准虚拟指数；RS 动量 = RS 日差分。
    象限（含边界：RS>=1 记强势、动量>=0 讱上行）：leading / weakening / lagging / improving。
    长度不一致截短到较小长度；基准指数非正（极端 -100% 累乘）时该日 RS 不可算 → None。
    """
    n = min(len(changes), len(benchmark_changes))
    theme_index = virtual_index([float(c) for c in changes[:n]])
    bench_index = virtual_index([float(c) for c in benchmark_changes[:n]])
    out: list[str | None] = []
    prev_rs: float | None = None
    for ti, bi in zip(theme_index, bench_index):
        if bi <= 0:
            out.append(None)
            prev_rs = None
            continue
        rs = ti / bi
        if prev_rs is None:
            out.append(None)
            prev_rs = rs
            continue
        momentum = rs - prev_rs
        if rs >= 1.0:
            out.append(RRG_LEADING if momentum >= 0 else RRG_WEAKENING)
        else:
            out.append(RRG_IMPROVING if momentum >= 0 else RRG_LAGGING)
        prev_rs = rs
    return out


def _migration_flags(state_by_day: dict[str, str | None], pairs: frozenset[tuple[str, str]]) -> dict[str, bool | None]:
    """相邻已知日状态对 ∈ pairs → 触发；首日与断链后首日 → None。"""
    flags: dict[str, bool | None] = {}
    prev: str | None = None
    have_prev = False
    for d in sorted(state_by_day):
        cur = state_by_day[d]
        if cur is None:
            flags[d] = None
            have_prev = False
            continue
        flags[d] = (prev, cur) in pairs if have_prev else None
        prev = cur
        have_prev = True
    return flags


def sg1_rrg_migration_flags(quadrants_by_day: dict[str, str | None]) -> dict[str, bool | None]:
    """逐日 RRG 象限 → 目标迁移（§5.4 两种）触发日标记。"""
    return _migration_flags(quadrants_by_day, SG1_MIGRATION_PAIRS)


def sg2_rotation_switch_flags(state_by_day: dict[str, str | None]) -> dict[str, bool | None]:
    """逐日题材 rotationState → 资金流入首日切换（outflow/neutral→inflow）标记。"""
    return _migration_flags(state_by_day, SG2_SWITCH_PAIRS)


def sg3_inflow_turn_positive_flags(
    inflow_by_day: dict[str, float | None],
    *,
    positive_min_days: int = 1,
) -> dict[str, bool | None]:
    """逐日净流入（mainNetInflow）→ 转正初现日标记。

    触发 = 正段前最近已知值 ≤0（有前置证据）且当日恰为该正段内连续第
    positive_min_days 天正值；历史尽头或断链后的正段无前置证据 → None；
    positive_min_days>=1，非法值拒绝。
    """
    if positive_min_days < 1:
        raise ValueError(f"positive_min_days must be >= 1, got {positive_min_days}")
    flags: dict[str, bool | None] = {}
    pos_run = 0
    seg_evidence = False
    seen_any = False
    for d in sorted(inflow_by_day):
        v = inflow_by_day[d]
        if v is None:
            flags[d] = None
            pos_run = 0
            seg_evidence = False
            seen_any = False
            continue
        if v > 0:
            pos_run += 1
            flags[d] = None if not seen_any else (pos_run == positive_min_days and seg_evidence)
        else:
            flags[d] = False
            pos_run = 0
            seg_evidence = True
        seen_any = True
    return flags
