# quant-board/backend/tests/test_theme_resonance_fusion.py
from backend.analysis.theme_momentum import (
    THEME_ADJUSTMENT_MAX,
    fuse_theme_resonance,
    stock_theme_exposure,
)


def _theme(theme_id, heat, rank, rotation="neutral", eligible=True, crowding_risk=30.0):
    return {
        "entityType": "hot_theme",
        "themeId": theme_id,
        "themeName": f"{theme_id}概念板块",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "crowdingRisk": crowding_risk,
        "metadata": {"rankEligible": eligible},
    }


def _stock(code, themes, change=3.0, theme_role="", lead_status="", main_theme=""):
    return {
        "code": code,
        "themes": themes,
        "change": change,
        "themeRole": theme_role,
        "leadStatus": lead_status,
        "mainTheme": main_theme,
    }


def _frame_momentum(cross_section_ok=True, theme_scores=None):
    return {
        "themes": {theme_id: {"status": "ok", "score": score, "direction": "buy"}
                   for theme_id, score in (theme_scores or {"A": 80.0}).items()},
        "marketThemeMedianShortChange": 1.0,
        "themeSampleCount": 25,
        "crossSectionOk": cross_section_ok,
        "qualityFlags": [] if cross_section_ok else ["theme_cross_section_insufficient"],
    }


def test_exposure_picks_highest_heat_theme_and_role():
    # 单一题材时 themeRole 直接复用；heatScore 最高者为主题材
    stock = _stock("000001", ["高热概念"], theme_role="leader")
    exposure = stock_theme_exposure(
        stock,
        [_theme("低热", 40.0, 2, eligible=False), _theme("高热", 80.0, 1), _theme("其他", 60.0, 3)],
    )
    assert exposure is not None
    assert exposure["themeId"] == "高热"
    assert exposure["role"] == "leader"
    assert exposure["roleWeight"] == 1.0


def test_exposure_returns_none_without_mapping():
    stock = _stock("000001", [])
    assert stock_theme_exposure(stock, [_theme("T2", 80.0, 1)]) is None


def test_fusion_insufficient_when_cross_section_bad_keeps_base_score():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["T2"]), [_theme("T2", 80.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(cross_section_ok=False))
    assert fused["score"] == 60
    assert fused["theme"]["status"] == "insufficient"
    assert "theme_cross_section_insufficient" in fused["theme"]["reasons"]


def test_fusion_missing_mapping_keeps_base_score():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    fused = fuse_theme_resonance(base, None, _frame_momentum())
    assert fused["score"] == 60
    assert fused["theme"]["status"] == "insufficient"
    assert "theme_mapping_missing" in fused["theme"]["reasons"]


def test_fusion_adjustment_bounded_and_direction_preserved():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"]), [_theme("A", 90.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 100.0}))
    assert fused["theme"]["status"] == "ok"
    assert fused["direction"] == "buy"
    assert fused["score"] > 60
    assert abs(fused["theme"]["adjustment"]) <= THEME_ADJUSTMENT_MAX


def test_fusion_lifecycle_penalty_for_follower_in_cooling():
    base = {"status": "ok", "direction": "buy", "score": 80, "label": "强"}
    exposure = stock_theme_exposure(
        _stock("000001", ["A"], theme_role="follower"),
        [_theme("A", 90.0, 1, rotation="cooling", crowding_risk=90.0)],
    )
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 40.0}))
    assert fused["score"] < 80
    assert fused["theme"]["themeLifecycle"] == "cooling"


def test_exposure_main_theme_priority():
    stock = _stock("000001", ["AI", "半导体"], main_theme="AI概念")
    exposure = stock_theme_exposure(
        stock,
        [
            _theme("半导体", 90.0, 1),
            _theme("AI", 88.0, 2),
        ],
    )
    assert exposure is not None
    assert exposure["themeId"] == "AI"


def test_exposure_role_fallback_when_matched_theme_not_main_theme():
    # themeRole 属于 mainTheme 的语义；匹配到非 mainTheme 题材时回退 heat/change 规则
    stock = _stock("000001", ["半导体", "人工智能"], theme_role="leader", main_theme="人工智能概念")
    exposure = stock_theme_exposure(
        stock,
        [
            _theme("半导体", 90.0, 1),
            _theme("白酒", 60.0, 2),
        ],
    )
    # mainTheme "人工智能概念" 未出现在帧内，降级取匹配题材中 heatScore 最高 = 半导体
    assert exposure["themeId"] == "半导体"
    # 匹配题材非 mainTheme，themeRole=leader 不得直接复用
    assert exposure["role"] != "leader"


def test_exposure_name_variant_matching():
    # 后缀变体：stock themes 用 "区块链技术"，sector 用 "区块链产业"，均应归一为 "区块链"
    stock = _stock("000001", ["区块链技术"])
    exposure = stock_theme_exposure(stock, [_theme("区块链", 80.0, 1)])
    assert exposure is not None
    assert exposure["themeId"] == "区块链"


def test_fusion_direction_sell_flips_momentum():
    base = {"status": "ok", "direction": "sell", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 90.0, 1)])
    frame = _frame_momentum(theme_scores={"A": 90})
    frame["themes"]["A"]["direction"] = "sell"
    fused = fuse_theme_resonance(base, exposure, frame)
    assert fused["direction"] == "sell"
    assert fused["theme"]["themeMomentumDirection"] == "sell"
    assert fused["theme"]["status"] == "ok"


def test_fusion_direction_hold_no_flip():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 50.0, 1)])
    frame = _frame_momentum(theme_scores={"A": 50})
    frame["themes"]["A"]["direction"] = "hold"
    fused = fuse_theme_resonance(base, exposure, frame)
    assert fused["theme"]["themeMomentumDirection"] == "hold"
    assert fused["direction"] == "buy"


def test_fusion_lifecycle_bonus_for_leader_in_mainline():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(
        _stock("000001", ["A"], theme_role="leader"),
        [_theme("A", 90.0, 1, rotation="mainline")],
    )
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 50}))
    assert fused["theme"]["adjustment"] >= 5.0


def test_fusion_keeps_base_score_visible():
    base = {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}
    exposure = stock_theme_exposure(_stock("000001", ["A"], theme_role="leader"), [_theme("A", 90.0, 1)])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 100}))
    assert fused["baseScore"] == 60
    assert fused["score"] != fused["baseScore"]


def test_fusion_crowding_missing_skips_penalty_with_flag():
    base = {"status": "ok", "direction": "buy", "score": 80, "label": "强"}
    stock = _stock("000001", ["A"], theme_role="follower")
    exposure = stock_theme_exposure(stock, [_theme("A", 90.0, 1, rotation="cooling", crowding_risk=float("nan"))])
    fused = fuse_theme_resonance(base, exposure, _frame_momentum(theme_scores={"A": 40.0}))
    assert fused["theme"]["status"] == "ok"
    assert "crowding_risk_missing" in fused["theme"]["reasons"]
