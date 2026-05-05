from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric and numeric not in (float("inf"), float("-inf")) else default


def _normalize_theme_name(value: Any) -> str:
    name = str(value or "").strip()
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
    if len(shorter) < 3 or shorter not in longer:
        return False
    return len(shorter) / len(longer) >= 0.75


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _theme_name(stock: dict[str, Any]) -> str:
    explicit = str(stock.get("mainTheme") or stock.get("main_theme") or "").strip()
    if explicit:
        return explicit
    themes = _list(stock.get("themes"))
    first = themes[0] if themes and isinstance(themes[0], dict) else {}
    return str(first.get("name") or first.get("themeName") or "").strip()


def _theme_role(stock: dict[str, Any]) -> str:
    explicit = str(stock.get("themeRole") or stock.get("theme_role") or "").strip()
    if explicit:
        return explicit
    themes = _list(stock.get("themes"))
    first = themes[0] if themes and isinstance(themes[0], dict) else {}
    return str(first.get("role") or "").strip()


def _theme_contribution(stock: dict[str, Any]) -> float:
    direct = stock.get("themeContribution", stock.get("theme_contribution"))
    if direct is not None:
        return _num(direct)
    themes = _list(stock.get("themes"))
    first = themes[0] if themes and isinstance(themes[0], dict) else {}
    return _num(first.get("themeContribution"))


def _factor_from_sector(sector: dict[str, Any]) -> dict[str, Any]:
    metadata = sector.get("metadata") if isinstance(sector.get("metadata"), dict) else {}
    metadata_factor = metadata.get("themeFactor") if isinstance(metadata.get("themeFactor"), dict) else {}
    return {**metadata_factor, **sector}


def _find_sector_factor(frame: dict[str, Any], theme_name: str) -> dict[str, Any]:
    if not theme_name:
        return {}
    for sector in _list(frame.get("sectors") or frame.get("sectorRows") or frame.get("entities")):
        if not isinstance(sector, dict):
            continue
        names = [
            str(sector.get("entityName") or ""),
            str(sector.get("themeName") or ""),
            str(sector.get("name") or ""),
        ]
        if any(_is_same_theme_name(name, theme_name) for name in names):
            return _factor_from_sector(sector)
    return {}


def build_theme_candidate_support(frame: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    main_theme = _theme_name(stock)
    factor = _find_sector_factor(frame, main_theme)
    role = _theme_role(stock)
    heat = _num(stock.get("themeHeat", stock.get("theme_heat")))
    contribution = _theme_contribution(stock)
    momentum = _num(factor.get("momentumScore", factor.get("momentum_score")))
    correlation = _num(factor.get("correlationScore", factor.get("correlation_score")))
    crowding = _num(factor.get("crowdingRisk", factor.get("crowding_risk")))
    rotation_state = str(factor.get("rotationState") or factor.get("rotation_state") or "")

    score = heat * 0.35 + min(18, contribution) * 2.0 + momentum * 0.15 + correlation * 0.12
    if role == "leader":
        score += 12
    elif role == "core":
        score += 8
    elif role == "follower":
        score += 4
    if rotation_state == "mainline":
        score += 12
    elif rotation_state == "inflow":
        score += 7
    elif rotation_state in {"outflow", "cooling"}:
        score -= 10
    score -= max(0.0, crowding - 60) * 0.35

    reasons: list[str] = []
    risk_flags: list[str] = [str(item) for item in _list(stock.get("themeRiskFlags") or stock.get("theme_risk_flags"))]
    if main_theme:
        reasons.append(f"题材: {main_theme}")
    if rotation_state == "mainline":
        reasons.append("题材处于主线")
    elif rotation_state == "inflow":
        reasons.append("题材资金流入")
    if role:
        reasons.append(f"题材角色: {role}")
    if momentum >= 70:
        reasons.append("题材动量强")
    if correlation >= 65:
        reasons.append("板块联动较强")
    if crowding >= 70:
        risk_flags.append("题材拥挤风险高")

    return {
        "mainTheme": main_theme,
        "themeHeat": heat,
        "themeContribution": contribution,
        "themeRole": role,
        "themeSupportScore": round(_clamp(score), 2),
        "riskFlags": list(dict.fromkeys(risk_flags)),
        "reasons": list(dict.fromkeys(reasons)),
    }


def build_theme_support_index(frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for stock in _list(frame.get("stocks")):
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        if code:
            output[code] = build_theme_candidate_support(frame, stock)
    return output
