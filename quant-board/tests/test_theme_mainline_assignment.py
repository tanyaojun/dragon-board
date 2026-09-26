"""主线题材归属判定链已知答案校验（Phase R1，设计文档 §5.5）。"""

from backend.analysis.theme.mainline_assignment import (
    assign_main_theme,
    mainline_scores,
)


def _rows():
    """三题材横截面：heat 与 momentum 同序，ztCount 反序，fund 仅两题材有。"""
    return [
        {"entityKey": "AI", "heatLevel": 90.0, "momentumScore": 80.0, "ztCount": 5, "fundScore": 70.0},
        {"entityKey": "机器人", "heatLevel": 70.0, "momentumScore": 60.0, "ztCount": 10, "fundScore": 50.0},
        {"entityKey": "芯片", "heatLevel": 50.0, "momentumScore": 40.0, "ztCount": 2},  # 无 fundScore
    ]


class TestMainlineScores:
    def test_scores_ordered_by_dominant_factors(self):
        scores = mainline_scores(_rows())
        assert scores["AI"]["status"] == "ok"
        # AI 在 heat(最高)/momentum(最高)/fund(最高) 三因子 percentile=1.0，ztCount 最低=0
        # 机器人 heat/momentum 居中 0.5、ztCount 最高 1.0、fund 最低 0
        # 芯片 heat/momentum 最低 0、ztCount 最低 0、fund 缺失（权重重分配）
        assert scores["AI"]["score"] > scores["机器人"]["score"] > scores["芯片"]["score"]

    def test_missing_factor_redistributes_weight_and_flags(self):
        scores = mainline_scores(_rows())
        # 芯片缺 fundScore：coverage = (0.40+0.25+0.20)/(0.40+0.25+0.20+0.15)
        assert scores["芯片"]["status"] == "degraded"
        assert abs(scores["芯片"]["factorCoverage"] - 0.85) < 1e-6
        assert "fundScore" not in scores["芯片"]["factorsUsed"]

    def test_all_factors_missing_is_insufficient(self):
        scores = mainline_scores([{"entityKey": "X", "heatLevel": None}])
        assert scores["X"]["status"] == "insufficient"
        assert scores["X"]["score"] is None

    def test_nan_and_inf_factors_excluded(self):
        scores = mainline_scores([
            {"entityKey": "A", "heatLevel": float("nan"), "momentumScore": 80.0, "ztCount": 3, "fundScore": 60.0},
            {"entityKey": "B", "heatLevel": 70.0, "momentumScore": float("inf"), "ztCount": 3, "fundScore": 60.0},
        ])
        # A 的 heatLevel / B 的 momentumScore 缺失 → 双方 degraded，但其余因子仍出分
        assert scores["A"]["status"] == "degraded"
        assert scores["B"]["status"] == "degraded"
        assert scores["A"]["score"] is not None and scores["B"]["score"] is not None

    def test_duplicate_entity_key_flagged(self):
        scores = mainline_scores([
            {"entityKey": "A", "heatLevel": 90.0, "momentumScore": 80.0, "ztCount": 5, "fundScore": 70.0},
            {"entityKey": "A", "heatLevel": 10.0, "momentumScore": 20.0, "ztCount": 1, "fundScore": 30.0},
        ])
        assert "duplicate_entity" in scores["A"].get("qualityFlags", [])

    def test_empty_rows_return_empty_dict(self):
        assert mainline_scores([]) == {}

    def test_single_theme_gets_neutral_percentile(self):
        scores = mainline_scores([{"entityKey": "AI", "heatLevel": 88.0, "momentumScore": 55.0, "ztCount": 3, "fundScore": 60.0}])
        assert scores["AI"]["score"] == 50.0  # 唯一题材 percentile 归中


class TestAssignMainTheme:
    def _scores(self):
        return {
            "AI": {"score": 90.0, "status": "ok"},
            "机器人": {"score": 55.0, "status": "ok"},
            "芯片": {"score": 54.5, "status": "ok"},
        }

    def test_highest_score_wins(self):
        result = assign_main_theme(["芯片", "AI", "机器人"], self._scores())
        assert result["mainTheme"] == "AI"
        assert result["mainThemeReason"] == "mainline_score"
        assert abs(result["scoreGap"] - 35.0) < 1e-6

    def test_tie_broken_by_reason_text(self):
        result = assign_main_theme(
            ["AI", "芯片"],
            self._scores(),
            reason_text="芯片+算力 涨停",
        )
        # AI 90 vs 芯片 54.5 差 35.5 > EPS=2，不该触发消歧——仍是 AI
        assert result["mainTheme"] == "AI"

        scores_close = {"AI": {"score": 60.0, "status": "ok"}, "芯片": {"score": 59.0, "status": "ok"}}
        result2 = assign_main_theme(["AI", "芯片"], scores_close, reason_text="芯片 涨停")
        assert result2["mainTheme"] == "芯片"
        assert result2["mainThemeReason"] == "tie_break_reason"

    def test_fallback_when_no_scored_theme(self):
        result = assign_main_theme(["冷门题材"], self._scores(), fallback_theme="冷门题材")
        assert result["mainTheme"] == "冷门题材"
        assert result["mainThemeReason"] == "fallback"
        assert "fallback" in result["qualityFlags"]

    def test_unassigned_when_no_themes_at_all(self):
        result = assign_main_theme([], self._scores())
        assert result["mainTheme"] is None
        assert result["mainThemeReason"] == "unassigned"

    def test_gap_equal_to_eps_does_not_tie_break(self):
        # gap 恰为 2.0（== EPS）不满足 gap < eps，即使原因命中第二名也不消歧
        scores = {"AI": {"score": 60.0, "status": "ok"}, "芯片": {"score": 58.0, "status": "ok"}}
        result = assign_main_theme(["AI", "芯片"], scores, reason_text="芯片 涨停")
        assert result["mainTheme"] == "AI"
        assert result["mainThemeReason"] == "mainline_score"

    def test_tie_break_only_considers_top3(self):
        # 第 4 名命中原因文本不消歧：hits 只在 ranked[:3] 内找
        scores = {
            "甲": {"score": 60.0, "status": "ok"},
            "乙": {"score": 59.0, "status": "ok"},
            "丙": {"score": 58.0, "status": "ok"},
            "丁": {"score": 57.0, "status": "ok"},
        }
        result = assign_main_theme(["甲", "乙", "丙", "丁"], scores, reason_text="丁 涨停")
        assert result["mainTheme"] == "甲"
        assert result["mainThemeReason"] == "mainline_score"

    def test_tie_break_matches_normalized_theme_label(self):
        # 后缀剥除：候选"算力概念"归一为"算力"，原因文本"算力 涨停"子串命中
        scores = {"AI": {"score": 60.0, "status": "ok"}, "算力概念": {"score": 59.0, "status": "ok"}}
        result = assign_main_theme(["AI", "算力概念"], scores, reason_text="算力 涨停")
        assert result["mainTheme"] == "算力概念"
        assert result["mainThemeReason"] == "tie_break_reason"
        assert "tie_break:算力概念" in result["qualityFlags"]
