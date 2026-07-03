from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict, fields
from typing import Any

from backend.analysis.theme_heat import compute_theme_heat

LIFECYCLES = {
    "ignition",
    "expansion",
    "mainline",
    "crowded",
    "divergence",
    "cooling",
    "reversal",
    "neutral",
}

STRATEGY_VERSION = "theme-trend-v12"
FACTOR_VERSION = "theme-factor-v12"
SIGNAL_VERSION = "theme-signal-v12"


@dataclass
class ThemeFactorFrame:
    themeId: str = ""
    themeName: str = ""
    heatScore: float = 0.0
    momentumScore: float = 0.0
    breadthScore: float = 0.0
    fundScore: float | None = 0.0
    leadershipScore: float = 0.0
    correlationScore: float = 0.0
    crowdingRisk: float = 0.0
    persistenceScore: float = 0.0
    rotationState: str = "neutral"
    rank: int = 0
    qualityFlags: list[str] = field(default_factory=list)
    lifecycle: str = "neutral"

    # 多帧增强字段（由 replay_sequence 填充）
    consecutiveFrames: int = 0
    prevLifecycle: str = ""
    lifecycleTransition: str = ""

    # 研究溯源字段
    datasetId: str = ""
    snapshotId: str = ""
    snapshotType: str = "half_hour"
    tradingDate: str = ""
    slotTime: str = ""
    strategyVersion: str = STRATEGY_VERSION
    configHash: str = ""
    randomSeed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThemeStockExposureFrame:
    code: str = ""
    themeId: str = ""
    themeName: str = ""
    role: str = "unknown"
    roleScore: float = 0.0
    exposureWeight: float = 0.0
    themeContribution: float = 0.0
    riskPenalty: float = 0.0
    reasons: list[str] = field(default_factory=list)

    datasetId: str = ""
    snapshotId: str = ""
    snapshotType: str = "half_hour"
    tradingDate: str = ""
    slotTime: str = ""
    strategyVersion: str = STRATEGY_VERSION
    configHash: str = ""
    randomSeed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThemeSignalRow:
    themeId: str = ""
    themeName: str = ""
    signal: str = "watch"
    risk: str = "none"
    lifecycle: str = "neutral"
    score: float = 0.0

    datasetId: str = ""
    snapshotId: str = ""
    snapshotType: str = "half_hour"
    tradingDate: str = ""
    slotTime: str = ""
    strategyVersion: str = STRATEGY_VERSION
    configHash: str = ""
    randomSeed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThemeQualityReport:
    passed: bool = True
    severity: str = "pass"
    researchGrade: str = "research_ready"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    frameCount: int = 0
    themeCount: int = 0
    stockCount: int = 0
    themeCoverage: float = 0.0

    datasetId: str = ""
    snapshotType: str = "half_hour"
    strategyVersion: str = STRATEGY_VERSION
    configHash: str = ""
    randomSeed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThemeTrendConfig:
    minFrames: int = 1
    minStocksPerFrame: int = 1
    minSectorsPerFrame: int = 1
    crowdedRiskThreshold: float = 80
    mainlineHeatThreshold: float = 75
    mainlineMomentumThreshold: float = 70
    expansionMomentumThreshold: float = 60
    ignitionMomentumThreshold: float = 50
    coolingMomentumThreshold: float = 35
    reversalMomentumThreshold: float = 25

    @classmethod
    def from_patch(cls, patch: dict[str, Any] | None = None) -> "ThemeTrendConfig":
        config = cls()
        if not patch:
            return config
        for key, value in patch.items():
            if hasattr(config, key):
                setattr(config, key, value)
        config.minFrames = max(1, int(config.minFrames))
        config.minStocksPerFrame = max(0, int(config.minStocksPerFrame))
        config.minSectorsPerFrame = max(0, int(config.minSectorsPerFrame))
        return config


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _int(value: Any, default: int = 0) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(float(numeric)) else numeric


def _round(value: float) -> float:
    return round(value, 2)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _name(value: Any) -> str:
    return str(value or "").strip()


def _normalize_theme_name(value: Any) -> str:
    name = _name(value)
    for suffix in ("概念板块", "概念", "板块"):
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


def _timestamp(frame: dict[str, Any]) -> float:
    return _num(frame.get("timestamp") or frame.get("ts"))


def _sector_rows(frame: dict[str, Any]) -> list[dict[str, Any]]:
    rows = frame.get("sectors") or frame.get("sectorRows") or frame.get("entities")
    return [item for item in _list(rows) if isinstance(item, dict)]


def _stock_rows(frame: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list(frame.get("stocks")) if isinstance(item, dict)]


def _theme_context(frame: dict[str, Any]) -> dict[str, Any]:
    context = frame.get("themeContext")
    return context if isinstance(context, dict) else {}


def _theme_rows_for_quality(frame: dict[str, Any]) -> list[dict[str, Any]]:
    sectors = _sector_rows(frame)
    if sectors:
        return sectors
    context = _theme_context(frame)
    return [item for item in _list(context.get("themes")) if isinstance(item, dict)]


def _theme_context_frames(frame: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    context = _theme_context(frame)
    themes = [item for item in _list(context.get("themes")) if isinstance(item, dict)]
    if not themes:
        return None
    stocks = _stock_rows(frame)
    stock_by_code = {str(stock.get("code") or ""): stock for stock in stocks}
    theme_stocks = context.get("themeStocks") if isinstance(context.get("themeStocks"), dict) else {}
    stock_themes = context.get("stockThemes") if isinstance(context.get("stockThemes"), dict) else {}
    rotation = context.get("rotationAnalysis") if isinstance(context.get("rotationAnalysis"), dict) else {}
    correlations = context.get("correlations") if isinstance(context.get("correlations"), dict) else {}
    fund_rows = context.get("funds") if isinstance(context.get("funds"), dict) else {}
    previous_factors = context.get("previousFactors") if isinstance(context.get("previousFactors"), dict) else {}

    market_themes = [
        {
            **theme,
            "stocks": [str(code) for code in _list(theme_stocks.get(_name(theme.get("id") or theme.get("themeId"))))],
        }
        for theme in themes
    ]
    snapshot = compute_theme_heat(
        themes=market_themes,
        quotes=stock_by_code,
        funds={str(code): row for code, row in fund_rows.items() if isinstance(row, dict)},
        previous_factors={
            str(theme_id): factor
            for theme_id, factor in previous_factors.items()
            if isinstance(factor, dict)
        },
        computed_at=int(_timestamp(frame)),
        mapping_version=_name(context.get("mappingVersion") or "theme-context"),
    )

    factors = [dict(item) for item in snapshot["factors"] if item.get("rankEligible")]
    exposures: list[dict[str, Any]] = []
    for factor in factors:
        theme_id = _name(factor.get("themeId"))
        theme_name = _name(factor.get("themeName"))
        codes = [str(code) for code in _list(theme_stocks.get(theme_id))]
        factor["rotationState"] = _ts_rotation_state(rotation, theme_id, theme_name)
        factor["lifecycle"] = _infer_lifecycle({**factor, "lifecycle": ""}, ThemeTrendConfig())
        for code in codes:
            exposure = _build_ts_runtime_exposure(
                code=code,
                factor=factor,
                stock=stock_by_code.get(code),
                stock_theme_ids=[str(item) for item in _list(stock_themes.get(code))],
                correlation=correlations.get(theme_id) if isinstance(correlations.get(theme_id), dict) else None,
            )
            if exposure:
                exposures.append(exposure)

    return factors, exposures


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    return False


def build_theme_quality_report(frames: list[dict[str, Any]] | Any) -> dict[str, Any]:
    valid_frames = [frame for frame in _list(frames) if isinstance(frame, dict)]
    errors: list[str] = []
    warnings: list[str] = []

    if not valid_frames:
        errors.append("empty_frames")
    elif len(valid_frames) < 2:
        warnings.append("low_sample")

    timestamps = [_timestamp(frame) for frame in valid_frames]
    if any(timestamps[index] < timestamps[index - 1] for index in range(1, len(timestamps))):
        warnings.append("time_order_invalid")

    if any(_has_non_finite(frame) for frame in valid_frames):
        warnings.append("illegal_numeric_value")

    for frame in valid_frames:
        if len(_stock_rows(frame)) < 1:
            warnings.append("missing_stock_data")
        if len(_theme_rows_for_quality(frame)) < 1:
            warnings.append("missing_theme_data")
            break

    return {
        "blocked": bool(errors),
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "frameCount": len(valid_frames),
        "stockCount": sum(len(_stock_rows(frame)) for frame in valid_frames),
        "themeCount": sum(len(_theme_rows_for_quality(frame)) for frame in valid_frames),
    }


def _sector_theme_name(sector: dict[str, Any]) -> str:
    return _name(sector.get("themeName") or sector.get("entityName") or sector.get("name"))


def _sector_theme_id(sector: dict[str, Any], theme_name: str) -> str:
    explicit = _name(sector.get("themeId") or sector.get("entityKey") or sector.get("entity_key"))
    return explicit or theme_name


def _ts_round(value: float, digits: int = 0) -> float:
    return round(value, digits)


def _ts_clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _ts_rotation_state(rotation: dict[str, Any], theme_id: str, theme_name: str) -> str:
    def matches(item: Any) -> bool:
        return isinstance(item, dict) and (_name(item.get("themeId")) == theme_id or _is_same_theme_name(item.get("themeName") or item.get("name"), theme_name))

    if any(matches(item) for item in _list(rotation.get("mainLines"))):
        return "mainline"
    if any(matches(item) for item in _list(rotation.get("quickRotation"))):
        return "quick"
    if any(matches(item) for item in _list(rotation.get("inflowThemes"))):
        return "inflow"
    if any(matches(item) for item in _list(rotation.get("outflowThemes"))):
        return "cooling" if rotation.get("marketPhase") in {"distribution", "falling"} else "outflow"
    return "neutral"


def _ts_correlated_role(correlation: dict[str, Any] | None, code: str) -> str:
    stocks = correlation.get("stocks") if isinstance(correlation, dict) and isinstance(correlation.get("stocks"), dict) else {}
    item = stocks.get(code) if isinstance(stocks.get(code), dict) else {}
    role = _name(item.get("role"))
    return role if role in {"leader", "follower"} else ""


def _ts_role_for(code: str, stock: dict[str, Any] | None, factor: dict[str, Any], correlation: dict[str, Any] | None) -> str:
    correlated = _ts_correlated_role(correlation, code)
    if correlated:
        return correlated
    if "龙" in _name((stock or {}).get("leadStatus")):
        return "leader"
    if factor["heatScore"] >= 70 and _num((stock or {}).get("change")) >= 5:
        return "core"
    if factor["heatScore"] >= 45 and _num((stock or {}).get("change")) > 0:
        return "follower"
    if factor["heatScore"] < 20 or _num((stock or {}).get("change")) < -5:
        return "noise"
    return "independent"


def _ts_role_score(role: str, stock: dict[str, Any] | None) -> float:
    change = _num((stock or {}).get("change"))
    lead_times = _num((stock or {}).get("leadTimes"))
    if role == "leader":
        return _ts_clamp(82 + min(12, lead_times * 4) + max(0, change - 8))
    if role == "core":
        return _ts_clamp(68 + max(0, change))
    if role == "follower":
        return _ts_clamp(52 + max(0, change) * 0.8)
    if role == "independent":
        return 34.0
    return 12.0


def _ts_exposure_source(factor: dict[str, Any], stock_theme_ids: list[str]) -> str:
    if factor.get("source") == "mixed":
        return "mixed"
    return "static" if factor["themeId"] in stock_theme_ids else "realtime"


def _ts_exposure_reasons(factor: dict[str, Any], role: str) -> list[str]:
    reasons: list[str] = []
    if factor["rotationState"] == "mainline":
        reasons.append("题材处于主线")
    elif factor["rotationState"] == "inflow":
        reasons.append("题材资金流入")
    elif factor["rotationState"] == "quick":
        reasons.append("题材快速轮动")
    if factor["heatScore"] >= 70:
        reasons.append("题材热度强")
    if factor["leadershipScore"] >= 55:
        reasons.append("题材有龙头带动")
    if factor["correlationScore"] >= 65:
        reasons.append("板块联动较强")
    if factor["crowdingRisk"] >= 55:
        reasons.append("题材拥挤风险偏高")
    if role == "leader":
        reasons.append("个股是题材龙头")
    if role == "core":
        reasons.append("个股是题材核心跟随")
    return reasons


def _build_ts_runtime_exposure(
    code: str,
    factor: dict[str, Any],
    stock: dict[str, Any] | None,
    stock_theme_ids: list[str],
    correlation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    role = _ts_role_for(code, stock, factor, correlation)
    role_score = _ts_role_score(role, stock)
    risk_penalty = 8 if factor["crowdingRisk"] >= 70 else 4 if factor["crowdingRisk"] >= 50 else 0
    exposure_weight = {"leader": 1, "core": 0.82, "follower": 0.62, "independent": 0.38}.get(role, 0.15)
    contribution = _ts_clamp(
        _ts_round((factor["heatScore"] * 0.1 + role_score * 0.08 + factor["persistenceScore"] * 0.03 - risk_penalty) * exposure_weight, 1),
        0,
        18,
    )
    if role == "noise" and contribution < 1:
        return None
    return {
        "code": code,
        "themeId": factor["themeId"],
        "themeName": factor["themeName"],
        "role": role,
        "roleScore": _ts_round(role_score),
        "exposureWeight": _ts_round(exposure_weight, 2),
        "themeContribution": contribution,
        "riskPenalty": risk_penalty,
        "reasons": _ts_exposure_reasons(factor, role),
        "source": _ts_exposure_source(factor, stock_theme_ids),
        "themeScore": factor["heatScore"],
        "qualityFlags": factor["qualityFlags"],
    }


def _quality_flags(factor: dict[str, Any], config: ThemeTrendConfig) -> list[str]:
    flags = [str(item) for item in _list(factor.get("qualityFlags") or factor.get("themeQualityFlags"))]
    if factor["crowdingRisk"] >= config.crowdedRiskThreshold:
        flags.append("crowding_risk_high")
    if factor["breadthScore"] <= 0:
        flags.append("breadth_missing")
    return list(dict.fromkeys(flags))


def _infer_lifecycle(factor: dict[str, Any], config: ThemeTrendConfig) -> str:
    explicit = _name(factor.get("lifecycle"))
    if explicit in LIFECYCLES:
        return explicit

    rotation_state = _name(factor["rotationState"])
    heat = _num(factor["heatScore"])
    momentum = _num(factor["momentumScore"])
    breadth = _num(factor["breadthScore"])
    fund = _num(factor["fundScore"])
    crowding = _num(factor["crowdingRisk"])
    persistence = _num(factor["persistenceScore"])
    correlation = _num(factor["correlationScore"])

    if crowding >= config.crowdedRiskThreshold:
        return "crowded"
    if rotation_state in LIFECYCLES:
        return rotation_state
    if momentum <= config.reversalMomentumThreshold and fund >= 60:
        return "reversal"
    if momentum <= config.coolingMomentumThreshold or rotation_state in {"outflow", "cooling"}:
        return "cooling"
    if heat >= config.mainlineHeatThreshold and momentum >= config.mainlineMomentumThreshold and persistence >= 65:
        return "mainline"
    if momentum >= config.expansionMomentumThreshold and breadth >= 55:
        return "expansion"
    if momentum >= config.ignitionMomentumThreshold and fund >= 55:
        return "ignition"
    if correlation < 35 and heat >= 65:
        return "divergence"
    return "neutral"


def _build_factor(sector: dict[str, Any], config: ThemeTrendConfig) -> dict[str, Any]:
    theme_name = _sector_theme_name(sector)
    factor = {
        "themeId": _sector_theme_id(sector, theme_name),
        "themeName": theme_name,
        "heatScore": _round(_clamp(_num(sector.get("heatScore", sector.get("hotScore"))))),
        "momentumScore": _round(_clamp(_num(sector.get("momentumScore")))),
        "breadthScore": _round(_clamp(_num(sector.get("breadthScore")))),
        "fundScore": _round(_clamp(_num(sector.get("fundScore", sector.get("capitalScore"))))),
        "leadershipScore": _round(_clamp(_num(sector.get("leadershipScore")))),
        "correlationScore": _round(_clamp(_num(sector.get("correlationScore")))),
        "crowdingRisk": _round(_clamp(_num(sector.get("crowdingRisk")))),
        "persistenceScore": _round(_clamp(_num(sector.get("persistenceScore")))),
        "rotationState": _name(sector.get("rotationState") or sector.get("rotation_state") or "neutral"),
        "rank": _int(sector.get("rank"), 0),
        "qualityFlags": [],
        "lifecycle": "neutral",
    }
    factor["lifecycle"] = _infer_lifecycle(factor | {"lifecycle": sector.get("lifecycle")}, config)
    factor["qualityFlags"] = _quality_flags(factor | sector, config)
    return factor


def _stock_theme(stock: dict[str, Any]) -> tuple[str, str, float]:
    explicit = _name(stock.get("mainTheme") or stock.get("themeName"))
    role = _name(stock.get("themeRole") or stock.get("role"))
    contribution = _num(stock.get("themeContribution"))
    themes = _list(stock.get("themes"))
    first = themes[0] if themes and isinstance(themes[0], dict) else {}
    theme_name = explicit or _name(first.get("name") or first.get("themeName"))
    return theme_name, role or _name(first.get("role")), contribution or _num(first.get("themeContribution"))


def _find_factor(factors: list[dict[str, Any]], theme_name: str) -> dict[str, Any] | None:
    for factor in factors:
        if _is_same_theme_name(factor["themeName"], theme_name):
            return factor
    return None


def _role_score(role: str) -> float:
    return {"leader": 100.0, "core": 78.0, "follower": 48.0}.get(role, 35.0)


def _build_exposure(stock: dict[str, Any], factors: list[dict[str, Any]]) -> dict[str, Any] | None:
    theme_name, role, contribution = _stock_theme(stock)
    factor = _find_factor(factors, theme_name)
    if not factor:
        return None

    role_score = _role_score(role)
    risk_penalty = _round(max(0.0, factor["crowdingRisk"] - 70) * 0.35)
    exposure_weight = _round(_clamp((role_score * 0.45 + contribution * 2.5 + factor["heatScore"] * 0.25) - risk_penalty))
    reasons = [f"role:{role or 'unknown'}"]
    if factor["lifecycle"] == "mainline":
        reasons.append("theme:mainline")
    if risk_penalty > 0:
        reasons.append("risk:crowded")

    return {
        "code": _name(stock.get("code")),
        "themeId": factor["themeId"],
        "themeName": factor["themeName"],
        "role": role or "unknown",
        "roleScore": _round(role_score),
        "exposureWeight": exposure_weight,
        "themeContribution": _round(contribution),
        "riskPenalty": risk_penalty,
        "reasons": reasons,
    }


def _build_signal(factor: dict[str, Any]) -> dict[str, Any]:
    lifecycle = factor["lifecycle"]
    if lifecycle == "crowded":
        signal = "risk"
        risk = "crowded"
    elif lifecycle in {"mainline", "expansion", "ignition"}:
        signal = lifecycle
        risk = "none"
    elif lifecycle in {"cooling", "reversal"}:
        signal = "reduce"
        risk = lifecycle
    else:
        signal = "watch"
        risk = "none"
    return {
        "themeId": factor["themeId"],
        "themeName": factor["themeName"],
        "signal": signal,
        "risk": risk,
        "lifecycle": lifecycle,
        "score": _round(
            factor["heatScore"] * 0.25
            + factor["momentumScore"] * 0.25
            + factor["breadthScore"] * 0.15
            + _num(factor["fundScore"]) * 0.15
            + factor["leadershipScore"] * 0.2
            - factor["crowdingRisk"] * 0.15
        ),
    }


class ThemeTrendPythonEngine:
    strategyVersion = "theme-trend-v12"
    factorVersion = "theme-factor-v12"
    signalVersion = "theme-signal-v12"

    def replay(
        self,
        frames: list[dict[str, Any]] | Any,
        config: ThemeTrendConfig | dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_config = config if isinstance(config, ThemeTrendConfig) else ThemeTrendConfig.from_patch(config)
        report = build_theme_quality_report(frames)
        valid_frames = [frame for frame in _list(frames) if isinstance(frame, dict)]
        if report["blocked"]:
            return self._result([], [], [], report, meta)

        latest = max(valid_frames, key=_timestamp)
        ts_runtime = _theme_context_frames(latest)
        if ts_runtime:
            factors, exposures = ts_runtime
        else:
            factors = [_build_factor(sector, resolved_config) for sector in _sector_rows(latest)]
            factors.sort(key=lambda item: item["rank"] if item["rank"] > 0 else 999999)

            exposures = []
            unmatched_stocks = 0
            for stock in _stock_rows(latest):
                exposure = _build_exposure(stock, factors)
                if exposure is not None:
                    exposures.append(exposure)
                elif _stock_theme(stock)[0]:
                    unmatched_stocks += 1

            if unmatched_stocks > 0:
                report["warnings"].append("unmatched_theme_stock")
                report["warnings"] = list(dict.fromkeys(report["warnings"]))

        signals = [_build_signal(factor) for factor in factors]
        return self._result(factors, exposures, signals, report, meta)

    def replay_typed(
        self,
        frames: list[dict[str, Any]] | Any,
        config: ThemeTrendConfig | dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ThemeTrendResult:
        raw = self.replay(frames, config, meta)
        return _to_typed_result(raw, meta)

    def replay_sequence(
        self,
        frames: list[dict[str, Any]] | Any,
        config: ThemeTrendConfig | dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """多帧回放：逐帧计算因子，同时追踪题材生命周期在帧间的迁移和持续性。"""
        resolved_config = config if isinstance(config, ThemeTrendConfig) else ThemeTrendConfig.from_patch(config)
        report = build_theme_quality_report(frames)
        valid_frames = sorted(
            [frame for frame in _list(frames) if isinstance(frame, dict)], key=_timestamp
        )
        if report["blocked"]:
            return self._result([], [], [], report, meta)

        all_factors: list[dict[str, Any]] = []
        all_exposures: list[dict[str, Any]] = []
        all_signals: list[dict[str, Any]] = []
        theme_tracker: dict[str, dict[str, Any]] = {}
        extra_warnings: list[str] = []

        for i, frame in enumerate(valid_frames):
            snapshot_id = str(frame.get("snapshotId") or "")
            trading_date = str(frame.get("tradingDate") or "")
            slot_time = str(frame.get("slotTime") or "")

            frame_factors = [
                _build_factor(sector, resolved_config) for sector in _sector_rows(frame)
            ]
            frame_factors.sort(key=lambda item: item["rank"] if item["rank"] > 0 else 999999)

            for factor in frame_factors:
                theme_id = factor["themeId"]
                prev = theme_tracker.get(theme_id)
                consecutive = (prev.get("consecutiveFrames", 0) + 1) if prev else 1
                prev_lifecycle = prev.get("lifecycle") if prev else None
                current_lifecycle = factor["lifecycle"]

                factor["snapshotId"] = snapshot_id
                factor["tradingDate"] = trading_date
                factor["slotTime"] = slot_time
                factor["consecutiveFrames"] = consecutive
                factor["prevLifecycle"] = prev_lifecycle or ""
                factor["lifecycleTransition"] = (
                    f"{prev_lifecycle}>{current_lifecycle}"
                    if prev_lifecycle and prev_lifecycle != current_lifecycle
                    else ""
                )
                # 多帧持久性评分（与 TS golden log1p 公式对齐）
                factor["persistenceScore"] = _round(
                    _clamp(
                        min(92.0, 18.0 + math.log1p(consecutive) * 28.0 + min(5, consecutive) * 6.0)
                    )
                )
                # 用多帧 persistenceScore 重新推断生命周期（跨帧升级路径）
                factor["lifecycle"] = _infer_lifecycle(factor, resolved_config)

                # 追踪状态（供后续帧使用）
                # heatScore/momentumScore 预留：未来热度趋势分析、动量背离检测
                # firstSeen 预留：题材首次出场帧索引
                theme_tracker[theme_id] = {
                    "lifecycle": factor["lifecycle"],
                    "consecutiveFrames": consecutive,
                    "heatScore": factor["heatScore"],
                    "momentumScore": factor["momentumScore"],
                    "firstSeen": prev.get("firstSeen", i) if prev else i,
                }

                all_factors.append(factor)

            frame_exposures: list[dict[str, Any]] = []
            unmatched_stocks = 0
            for stock in _stock_rows(frame):
                exposure = _build_exposure(stock, frame_factors)
                if exposure is not None:
                    exposure["snapshotId"] = snapshot_id
                    exposure["tradingDate"] = trading_date
                    exposure["slotTime"] = slot_time
                    frame_exposures.append(exposure)
                elif _stock_theme(stock)[0]:
                    unmatched_stocks += 1

            if unmatched_stocks > 0:
                extra_warnings.append("unmatched_theme_stock")

            all_exposures.extend(frame_exposures)

            for sig in [_build_signal(factor) for factor in frame_factors]:
                sig["snapshotId"] = snapshot_id
                sig["tradingDate"] = trading_date
                sig["slotTime"] = slot_time
                all_signals.append(sig)

        # 合并额外警告到质量报告，不去原地修改 build_theme_quality_report 返回值
        if extra_warnings:
            report["warnings"] = list(dict.fromkeys(report.get("warnings", []) + extra_warnings))
        else:
            report["warnings"] = list(dict.fromkeys(report.get("warnings", [])))
        return self._result(all_factors, all_exposures, all_signals, report, meta)

    def replay_sequence_typed(
        self,
        frames: list[dict[str, Any]] | Any,
        config: ThemeTrendConfig | dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ThemeTrendResult:
        raw = self.replay_sequence(frames, config, meta)
        return _to_typed_result(raw, meta)

    def _result(
        self,
        factors: list[dict[str, Any]],
        exposures: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        quality_report: dict[str, Any],
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = {
            "factors": factors,
            "exposures": exposures,
            "signals": signals,
            "qualityReport": quality_report,
            "strategyVersion": self.strategyVersion,
            "factorVersion": self.factorVersion,
            "signalVersion": self.signalVersion,
        }
        if meta:
            result["meta"] = dict(meta)
        return result


@dataclass
class ThemeTrendResult:
    factors: list[ThemeFactorFrame] = field(default_factory=list)
    exposures: list[ThemeStockExposureFrame] = field(default_factory=list)
    signals: list[ThemeSignalRow] = field(default_factory=list)
    qualityReport: ThemeQualityReport = field(default_factory=ThemeQualityReport)
    strategyVersion: str = STRATEGY_VERSION
    factorVersion: str = FACTOR_VERSION
    signalVersion: str = SIGNAL_VERSION
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factors": [item.to_dict() for item in self.factors],
            "exposures": [item.to_dict() for item in self.exposures],
            "signals": [item.to_dict() for item in self.signals],
            "qualityReport": self.qualityReport.to_dict(),
            "strategyVersion": self.strategyVersion,
            "factorVersion": self.factorVersion,
            "signalVersion": self.signalVersion,
            **({"meta": self.meta} if self.meta else {}),
        }


def _to_typed_result(raw: dict[str, Any], meta: dict[str, Any] | None) -> ThemeTrendResult:
    qr = raw.get("qualityReport", {})
    factor_fields = {item.name for item in fields(ThemeFactorFrame)}
    exposure_fields = {item.name for item in fields(ThemeStockExposureFrame)}
    signal_fields = {item.name for item in fields(ThemeSignalRow)}
    return ThemeTrendResult(
        factors=[ThemeFactorFrame(**{key: value for key, value in item.items() if key in factor_fields}) for item in raw.get("factors", [])],
        exposures=[ThemeStockExposureFrame(**{key: value for key, value in item.items() if key in exposure_fields}) for item in raw.get("exposures", [])],
        signals=[ThemeSignalRow(**{key: value for key, value in item.items() if key in signal_fields}) for item in raw.get("signals", [])],
        qualityReport=ThemeQualityReport(
            passed=not qr.get("blocked", False),
            severity="fail" if qr.get("blocked") else ("warn" if qr.get("warnings") else "pass"),
            researchGrade="degraded" if qr.get("warnings") else "research_ready",
            issues=qr.get("errors", []),
            warnings=qr.get("warnings", []),
            frameCount=qr.get("frameCount", 0),
            themeCount=qr.get("themeCount", 0),
            stockCount=qr.get("stockCount", 0),
        ),
        strategyVersion=raw.get("strategyVersion", STRATEGY_VERSION),
        factorVersion=raw.get("factorVersion", FACTOR_VERSION),
        signalVersion=raw.get("signalVersion", SIGNAL_VERSION),
        meta=dict(meta) if meta else {},
    )
