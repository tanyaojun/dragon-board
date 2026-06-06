"""RankTrend 简单回测：四信号 AND 入场 + 四条件 OR 出场。

不经过 compose_decision / compose_strategy / entry_signal 中间层，
直接从原始信号判断入场和出场。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine


@dataclass
class SimpleRankTrendConfig:
    """只搜索动量周期和 MACD 参数。"""

    momentum_periods: list[int] | None = None
    macd_fast: int | None = None
    macd_slow: int | None = None
    macd_signal: int | None = None


def _rank_config(simple: SimpleRankTrendConfig | None = None) -> RankTrendConfig:
    c = RankTrendConfig()
    simple = simple or SimpleRankTrendConfig()
    if simple.momentum_periods:
        c.momentumPeriods = list(simple.momentum_periods)
        n = len(simple.momentum_periods)
        c.momentumWeights = [1.0 / n] * n
        step = 12 / n
        c.buyThresholds = [5 + i * step for i in range(n)]
        c.sellThresholds = [-(5 + i * step) for i in range(n)]
    if simple.macd_fast is not None:
        c.macdFast = simple.macd_fast
    if simple.macd_slow is not None:
        c.macdSlow = simple.macd_slow
    if simple.macd_signal is not None:
        c.macdSignal = simple.macd_signal
    return c


def _entry_conditions(signal: dict[str, Any]) -> bool:
    """四入场条件 AND：仅前50名内排名大幅上升 + 多周期 BUY + MACD 金叉 + 置信度 > 90。"""
    rt = signal.get("rankTrend")
    if not isinstance(rt, dict):
        return False
    meta = rt.get("meta") or {}
    technical = rt.get("technical") or {}
    decision = rt.get("decision") or {}

    # 排名前 50 且大幅上升（窗口内至少提升 80 位）
    rank = float(signal.get("rank", 999))
    if rank > 50:
        return False
    if float(meta.get("rawChange") or 0) < 80:
        return False
    # 多周期动量 BUY
    sigs = technical.get("signals") or {}
    if sigs.get("direction", {}).get("signal") != "buy":
        return False
    if sigs.get("acceleration", {}).get("signal") != "buy":
        return False
    # MACD 金叉
    if (technical.get("macd") or {}).get("cross") != "golden":
        return False
    # 置信度 > 90
    if float(((decision.get("final") or {}).get("confidence") or 0)) < 90:
        return False
    return True


def _exit_conditions(
    signal: dict[str, Any] | None,
    code: str,
    frame_stocks_codes: set[str],
) -> tuple[bool, str]:
    """四出场条件 OR。"""

    # 3. 退出热榜池
    if code not in frame_stocks_codes:
        return True, "退出热榜池"

    if signal is None:
        return False, ""

    rt = signal.get("rankTrend")
    if not isinstance(rt, dict):
        return False, ""

    technical = rt.get("technical") or {}
    meta = rt.get("meta") or {}
    decision = rt.get("decision") or {}

    # 1. 排名大幅下降
    raw_change = float(meta.get("rawChange") or 0)
    if raw_change < -50:
        return True, f"排名大幅下降({raw_change:.0f})"

    # 2. 多周期动量转 sell：direction 和 acceleration 同时 sell，置信度 > 70
    sigs = technical.get("signals") or {}
    if sigs.get("direction", {}).get("signal") == "sell" and sigs.get("acceleration", {}).get("signal") == "sell":
        if float(((decision.get("final") or {}).get("confidence") or 0)) >= 70:
            return True, "多周期动量同时转卖"

    # 4. MACD 死叉
    if (technical.get("macd") or {}).get("cross") == "death":
        return True, "MACD 死叉"

    return False, ""


def _stock_price(frame: dict[str, Any], code: str) -> float:
    """在帧中找到指定股票的 price。"""
    for s in frame.get("stocks", []):
        if str(s.get("code") or "") == code:
            p = float(s.get("price") or s.get("lastTradePrice") or 0)
            if p > 0:
                return p
    return 0.0


def run_simple_backtest(
    frames: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """执行简单回测。

    入場：四信号 AND，next_bar 成交
    出场：四条件 OR，next_bar 成交
    """
    signals_by_frame: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sig in signals:
        signals_by_frame[sig.get("snapshotId", "")].append(sig)

    frame_stocks: dict[int, set[str]] = {}
    for i, frame in enumerate(frames):
        frame_stocks[i] = {str(s.get("code") or "") for s in frame.get("stocks", [])}

    trades: list[dict[str, Any]] = []
    positions: dict[str, dict[str, Any]] = {}
    entered_today: str = ""  # 每天最多开一仓

    for idx, frame in enumerate(frames):
        sid = frame.get("snapshotId", "")
        frame_signals = signals_by_frame.get(sid, [])
        stocks_in_frame = frame_stocks.get(idx, set())
        trading_date = str(frame.get("tradingDate") or "")
        if trading_date != entered_today:
            entered_today = ""

        # ── 出场检查 ──
        for code, pos in list(positions.items()):
            stock_sig = next((s for s in frame_signals if s.get("code") == code), None)
            should_exit, reason = _exit_conditions(stock_sig, code, stocks_in_frame)

            if should_exit and idx > pos["frameIndex"]:
                exit_price = _stock_price(frame, code)
                if exit_price <= 0 and idx + 1 < len(frames):
                    exit_price = _stock_price(frames[idx + 1], code)
                if exit_price <= 0:
                    continue  # 无法定价，跳过这帧

                gross_ret = (exit_price - pos["entryPrice"]) / pos["entryPrice"]
                net_ret = gross_ret - 0.0011
                trades.append({
                    "code": code, "name": pos.get("name", ""),
                    "entryDate": pos["entryDate"], "exitDate": frame.get("tradingDate", ""),
                    "entrySlot": pos["entrySlot"], "exitSlot": frame.get("slotTime", ""),
                    "entryPrice": round(pos["entryPrice"], 4),
                    "exitPrice": round(exit_price, 4),
                    "grossReturn": round(gross_ret, 4),
                    "netReturn": round(net_ret, 4),
                    "holdingBars": idx - pos["frameIndex"],
                    "exitReason": reason,
                    "rank": pos.get("rank"),
                    "entryRawChange": pos.get("rawChange"),
                    "entryConfidence": pos.get("confidence"),
                })
                del positions[code]

        # ── 入场检查 ──
        if entered_today or len(positions) >= 3:
            continue  # 每天最多开一仓，同时最多持有 3 只

        for sig in frame_signals:
            code = sig.get("code", "")
            if code in positions:
                continue

            if not _entry_conditions(sig):
                continue

            # next_bar：下一个帧该股票的 price
            entry_price = 0.0
            if idx + 1 < len(frames):
                entry_price = _stock_price(frames[idx + 1], code)
            if entry_price <= 0:
                entry_price = float(sig.get("price") or 0)
            if entry_price <= 0:
                continue

            rt = sig.get("rankTrend", {})
            entered_today = trading_date
            positions[code] = {
                "frameIndex": idx,
                "entryPrice": entry_price,
                "entryDate": frame.get("tradingDate", ""),
                "entrySlot": frame.get("slotTime", ""),
                "name": sig.get("name", ""),
                "code": code,
                "rank": float(sig.get("rank", 0)),
                "rawChange": float((rt.get("meta") or {}).get("rawChange", 0)),
                "confidence": float(((rt.get("decision") or {}).get("final") or {}).get("confidence", 0)),
            }
            break  # 同帧只取第一个满足条件的信号

    # ── 强制平仓 ──
    if frames and positions:
        last_frame = frames[-1]
        for code, pos in positions.items():
            exit_price = _stock_price(last_frame, code)
            if exit_price <= 0:
                exit_price = pos["entryPrice"]
            gross_ret = (exit_price - pos["entryPrice"]) / pos["entryPrice"]
            net_ret = gross_ret - 0.0011
            trades.append({
                "code": code, "name": pos.get("name", ""),
                "entryDate": pos["entryDate"], "exitDate": last_frame.get("tradingDate", ""),
                "entrySlot": pos["entrySlot"], "exitSlot": "强制平仓",
                "entryPrice": round(pos["entryPrice"], 4),
                "exitPrice": round(exit_price, 4),
                "grossReturn": round(gross_ret, 4),
                "netReturn": round(net_ret, 4),
                "holdingBars": len(frames) - pos["frameIndex"] - 1,
                "exitReason": "强制平仓",
                "rank": pos.get("rank"),
                "entryRawChange": pos.get("rawChange"),
                "entryConfidence": pos.get("confidence"),
            })

    return _summarize(trades, len(signals))


def _summarize(trades: list[dict[str, Any]], signal_count: int) -> dict[str, Any]:
    if not trades:
        return {
            "ok": True, "totalReturn": 0, "sharpe": None, "maxDrawdown": 0,
            "winRate": 0, "tradeCount": 0, "signalCount": signal_count,
            "avgNetReturn": 0, "trades": [],
        }
    net_returns = [t["netReturn"] for t in trades]
    wins = [r for r in net_returns if r > 0]
    total_ret = sum(net_returns)
    avg_ret = total_ret / len(trades)
    std_ret = (sum((r - avg_ret) ** 2 for r in net_returns) / len(net_returns)) ** 0.5 if len(net_returns) > 1 else 0
    sharpe = (avg_ret / std_ret) if std_ret > 0 else 0
    peak, drawdown, cum = 0.0, 0.0, 0.0
    for r in net_returns:
        cum += r
        peak = max(peak, cum)
        drawdown = min(drawdown, cum - peak)
    return {
        "ok": True, "totalReturn": round(total_ret, 4),
        "sharpe": round(sharpe, 4), "maxDrawdown": round(drawdown, 4),
        "winRate": round(len(wins) / len(trades), 4),
        "tradeCount": len(trades), "signalCount": signal_count,
        "avgNetReturn": round(avg_ret, 4), "trades": trades,
    }


def scan_params(
    frames: list[dict[str, Any]],
    param_grid: list[SimpleRankTrendConfig] | None = None,
) -> list[dict[str, Any]]:
    if param_grid is None:
        param_grid = _default_grid()
    results = []
    for cfg in param_grid:
        rc = _rank_config(cfg)
        signals = RankTrendPythonEngine(rc).replay(frames)
        r = run_simple_backtest(frames, signals)
        r["config"] = {
            "momentumPeriods": rc.momentumPeriods,
            "macdFast": rc.macdFast, "macdSlow": rc.macdSlow, "macdSignal": rc.macdSignal,
        }
        results.append(r)
    results.sort(key=lambda r: r["totalReturn"], reverse=True)
    return results


def _default_grid() -> list[SimpleRankTrendConfig]:
    grids = []
    for periods in [[3, 5, 8], [5, 8, 13, 21], [3, 5, 8, 13, 21]]:
        for fast, slow, sig in [(12, 21, 9), (8, 21, 5), (13, 34, 8)]:
            grids.append(SimpleRankTrendConfig(
                momentum_periods=periods, macd_fast=fast, macd_slow=slow, macd_signal=sig,
            ))
    return grids
