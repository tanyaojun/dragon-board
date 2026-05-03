from __future__ import annotations

from typing import Any

from backend.core.backtest.metrics import _round_or_none, average, share


def find_frame_index(frames: list[dict[str, Any]], snapshot_id: str) -> int:
    return next((idx for idx, frame in enumerate(frames) if frame.get("snapshotId") == snapshot_id), -1)


def find_stock(frame: dict[str, Any] | None, code: str) -> dict[str, Any] | None:
    if not frame:
        return None
    return next((row for row in frame.get("stocks", []) if str(row.get("code")) == code), None)


def build_frame_lookup(frames: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "index_by_snapshot_id": {str(frame.get("snapshotId")): idx for idx, frame in enumerate(frames)},
        "stock_by_frame_code": [
            {str(row.get("code")): row for row in frame.get("stocks", []) if row.get("code") is not None}
            for frame in frames
        ],
    }


def percentile(rank: float, total: int) -> float:
    return ((total - rank + 1) / total) * 100 if total else 0.0


def momentum_bucket(signal: dict[str, Any]) -> str:
    momentum = (((signal.get("rankTrend") or {}).get("strategy") or {}).get("momentum") or {})
    if not isinstance(momentum, dict):
        return "momentum缺失"

    short = float(momentum.get("short") or 0)
    mid = float(momentum.get("mid") or 0)
    long = float(momentum.get("long") or 0)
    acceleration = float(momentum.get("acceleration") or 0)
    shock = float(momentum.get("shock") or 0)

    short_bucket = "short强" if short >= 3 else "short弱" if short <= -3 else "short中"
    mid_bucket = "mid强" if mid >= 4 else "mid弱" if mid <= -3 else "mid中"
    long_bucket = "long高位" if long >= 4 else "long非高位"
    acceleration_bucket = "accel正" if acceleration >= 0 else "accel负"
    shock_bucket = "shock高" if abs(shock) >= 1.5 else "shock低"
    return f"{short_bucket}/{mid_bucket}/{long_bucket}/{acceleration_bucket}/{shock_bucket}"


class OutcomeEvaluator:
    tiers = ["A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL"]

    def distribution(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(signals)
        by_tier = [{"key": tier, "count": len([s for s in signals if s["candidateTier"] == tier]), "share": share(len([s for s in signals if s["candidateTier"] == tier]), total)} for tier in self.tiers]
        by_stage = self._group(signals, "stage")
        by_regime = self._group(signals, "regime")
        daily_map: dict[str, Any] = {}
        for signal in signals:
            date = signal.get("tradingDate") or ""
            daily = daily_map.setdefault(
                date,
                {
                    "tradingDate": date,
                    "total": 0,
                    "tiers": {tier: 0 for tier in self.tiers},
                    "regimes": {"strong": 0, "normal": 0, "weak": 0, "retreat": 0},
                },
            )
            daily["total"] += 1
            daily["tiers"][signal["candidateTier"]] += 1
            daily["regimes"][signal["regime"]] += 1
        weak = [s for s in signals if s["regime"] in ("weak", "retreat")]
        weak_ab = [s for s in weak if s["candidateTier"] in ("A_MAIN", "B_IGNITION")]
        warnings = []
        a_share = share(len([s for s in signals if s["candidateTier"] == "A_MAIN"]), total)
        if a_share > 0.1:
            warnings.append(f"A_MAIN 占比 {a_share * 100:.1f}%，高于 10% 验收警戒线")
        if weak and share(len(weak_ab), len(weak)) > 0.12:
            warnings.append("弱市/退潮环境下 A/B 收缩不充分")
        return {
            "totalSignals": total,
            "byTier": by_tier,
            "byStage": by_stage,
            "byRegime": by_regime,
            "daily": sorted(daily_map.values(), key=lambda item: item["tradingDate"]),
            "weakRetreatABShare": share(len(weak_ab), len(weak)),
            "warnings": warnings,
        }

    def evaluate(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
        lookup = build_frame_lookup(frames)
        reports = [self._horizon(frames, signals, horizon, lookup) for horizon in horizons]
        signal_by_snapshot_code = {f"{s['snapshotId']}:{s['code']}": s for s in signals}
        b_signals = [s for s in signals if s["candidateTier"] == "B_IGNITION"]
        b_to_a = []
        for signal in b_signals:
            idx = lookup["index_by_snapshot_id"].get(str(signal["snapshotId"]), -1)
            next_frame = frames[idx + 1] if idx >= 0 and idx + 1 < len(frames) else None
            next_signal = signal_by_snapshot_code.get(f"{next_frame.get('snapshotId') if next_frame else ''}:{signal['code']}")
            if next_signal and next_signal["candidateTier"] == "A_MAIN":
                b_to_a.append(signal)
        d_signals = [s for s in signals if s["candidateTier"] == "D_EXIT_RISK"]
        d_outcomes = [(s, self._outcome(frames, s, 3, lookup)) for s in d_signals]
        d_decay = [s for s, outcome in d_outcomes if outcome.get("found") and ((outcome.get("rankDelta") or 0) < 0 or (outcome.get("percentileDelta") or 0) < 0)]
        return {
            "horizons": reports,
            "bToATransitionRate": share(len(b_to_a), len(b_signals)),
            "dDecayRate": share(len(d_decay), len(d_signals)),
            "buyBaselineComparison": [
                {
                    "horizon": report["horizon"],
                    "aMain": next((row for row in report["byTier"] if row["groupKey"] == "A_MAIN"), None),
                    "legacyBuy": self._stats("legacyBuy", [(s, self._outcome(frames, s, report["horizon"], lookup)) for s in signals if s["rankTrend"]["decision"]["final"]["signal"] == "buy"]),
                }
                for report in reports
            ],
        }

    def _horizon(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], horizon: int, lookup: dict[str, Any]) -> dict[str, Any]:
        pairs = [(signal, self._outcome(frames, signal, horizon, lookup)) for signal in signals]
        return {
            "horizon": horizon,
            "byTier": self._group_stats(pairs, lambda s: s["candidateTier"], self.tiers),
            "byStage": self._group_stats(pairs, lambda s: s["stage"]),
            "byRegime": self._group_stats(pairs, lambda s: s["regime"]),
            "byTierStage": self._group_stats(pairs, lambda s: f"{s['candidateTier']}/{s['stage']}"),
            "byTierRegime": self._group_stats(pairs, lambda s: f"{s['candidateTier']}/{s['regime']}"),
            "byMomentumBucket": self._group_stats(pairs, momentum_bucket),
        }

    def _outcome(self, frames: list[dict[str, Any]], signal: dict[str, Any], horizon: int, lookup: dict[str, Any]) -> dict[str, Any]:
        code = str(signal["code"])
        entry = lookup["index_by_snapshot_id"].get(str(signal["snapshotId"]), -1)
        future = entry + horizon
        current_frame = frames[entry] if entry >= 0 else None
        future_frame = frames[future] if future < len(frames) else None
        current = lookup["stock_by_frame_code"][entry].get(code) if current_frame else None
        target = lookup["stock_by_frame_code"][future].get(code) if future_frame else None
        if entry < 0 or not current or not target or not current_frame or not future_frame:
            return {"code": signal["code"], "entrySnapshotId": signal["snapshotId"], "horizon": horizon, "found": False, "rankDelta": None, "percentileDelta": None, "priceReturn": None, "maxDrawdown": None, "stayedTop20": False, "stayedTop50": False}
        current_rank = float(current.get("rank") or 0)
        future_rank = float(target.get("rank") or 0)
        entry_price = float(current.get("price") or 0)
        future_price = float(target.get("price") or 0)
        stock_window = [lookup["stock_by_frame_code"][idx].get(code) for idx in range(entry, future + 1)]
        prices = [float((row or {}).get("price") or 0) for row in stock_window]
        prices = [price for price in prices if price > 0]
        return {
            "code": signal["code"],
            "entrySnapshotId": signal["snapshotId"],
            "horizon": horizon,
            "found": True,
            "rankDelta": round(current_rank - future_rank, 2),
            "percentileDelta": round(percentile(future_rank, len(future_frame["stocks"])) - percentile(current_rank, len(current_frame["stocks"])), 2),
            "priceReturn": round((future_price - entry_price) / entry_price, 4) if entry_price > 0 and future_price > 0 else None,
            "maxDrawdown": round((min(prices) - entry_price) / entry_price, 4) if entry_price > 0 and prices else None,
            "stayedTop20": all((row or {}).get("rank", 999) <= 20 for row in stock_window),
            "stayedTop50": all((row or {}).get("rank", 999) <= 50 for row in stock_window),
        }

    def _group(self, signals: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        total = len(signals)
        keys = sorted({str(signal.get(key)) for signal in signals})
        return [{"key": item, "count": len([s for s in signals if str(s.get(key)) == item]), "share": share(len([s for s in signals if str(s.get(key)) == item]), total)} for item in keys]

    def _group_stats(self, pairs: list[tuple[dict[str, Any], dict[str, Any]]], selector, order: list[str] | None = None) -> list[dict[str, Any]]:
        keys = order or sorted({selector(signal) for signal, _ in pairs})
        return [self._stats(key, [(s, o) for s, o in pairs if selector(s) == key]) for key in keys]

    def _stats(self, key: str, items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
        found = [outcome for _, outcome in items if outcome.get("found")]
        return {
            "groupKey": key,
            "sampleCount": len(items),
            "foundCount": len(found),
            "foundRate": share(len(found), len(items)),
            "avgRankDelta": _round_or_none(average([o["rankDelta"] for o in found if o.get("rankDelta") is not None])),
            "avgPercentileDelta": _round_or_none(average([o["percentileDelta"] for o in found if o.get("percentileDelta") is not None])),
            "avgPriceReturn": _round_or_none(average([o["priceReturn"] for o in found if o.get("priceReturn") is not None])),
            "avgMaxDrawdown": _round_or_none(average([o["maxDrawdown"] for o in found if o.get("maxDrawdown") is not None])),
            "stayedTop20Rate": share(len([o for o in found if o.get("stayedTop20")]), len(found)),
            "stayedTop50Rate": share(len([o for o in found if o.get("stayedTop50")]), len(found)),
        }
