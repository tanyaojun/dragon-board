"""轮动度量纯函数已知答案校验（Phase R1）。"""

from backend.analysis.theme.rotation.measures import (
    dedup_limit_count,
    mainline_persistence,
    rank_entropy,
    rotation_speed,
)


class TestRotationSpeed:
    def test_identical_top_lists_speed_zero(self):
        result = rotation_speed([{"a", "b", "c"}, {"a", "b", "c"}])
        assert result["status"] == "ok"
        assert result["mean"] == 0.0
        assert result["series"][0]["value"] == 0.0

    def test_disjoint_top_lists_speed_one(self):
        result = rotation_speed([{"a", "b", "c"}, {"d", "e", "f"}])
        assert result["status"] == "ok"
        assert result["series"][0]["value"] == 1.0

    def test_half_overlap(self):
        result = rotation_speed([{"a", "b", "c", "d"}, {"c", "d", "e", "f"}])
        # 交集 2 / 并集 6 → jaccard 1/3 → speed 2/3
        assert abs(result["series"][0]["value"] - 0.6667) < 1e-4

    def test_insufficient_when_fewer_than_two_days(self):
        assert rotation_speed([{"a"}])["status"] == "insufficient"

    def test_empty_day_breaks_series_but_keeps_rest(self):
        result = rotation_speed([{"a", "b"}, {"a", "b"}, set(), {"a", "b"}, {"a", "b"}])
        # 空集日两侧转移均无信息：流入缺失日与流出缺失日都标 insufficient
        assert result["series"][1]["status"] == "insufficient"
        assert result["series"][2]["status"] == "insufficient"
        # 缺口后首个可比转移正常计算，整体保留可计算部分
        assert result["series"][3]["value"] == 0.0
        assert result["status"] == "ok"
        assert result["mean"] == 0.0


class TestMainlinePersistence:
    def test_constant_mainline_zero_switches(self):
        result = mainline_persistence({"d1": "AI", "d2": "AI", "d3": "AI"})
        assert result["status"] == "ok"
        assert result["switches"] == 0
        assert result["streaks"] == [3]
        assert result["switch_rate"] == 0.0

    def test_daily_rotation_max_switches(self):
        result = mainline_persistence({"d1": "AI", "d2": "机器人", "d3": "AI"})
        assert result["switches"] == 2
        assert result["streaks"] == [1, 1, 1]
        assert result["switch_rate"] == 1.0

    def test_none_day_breaks_segment_without_counting_switch(self):
        result = mainline_persistence({"d1": "AI", "d2": None, "d3": "机器人"})
        # d2 缺失：AI 段结束记 streak=1，d3 新段不计切换
        assert result["switches"] == 0
        assert result["streaks"] == [1, 1]

    def test_switch_rate_none_when_no_comparable_transition(self):
        result = mainline_persistence({"d1": "AI", "d2": None})
        assert result["status"] == "ok"
        assert result["switch_rate"] is None
        assert result["comparable_transitions"] == 0

    def test_insufficient_no_known_mainline(self):
        assert mainline_persistence({"d1": None})["status"] == "insufficient"


class TestRankEntropy:
    def test_single_theme_monopoly_zero_entropy(self):
        # 按实现签名 rank_entropy(top_counts) 调用（计划已知不一致已修正：去掉 total_days）
        result = rank_entropy({"AI": 10})
        assert result["status"] == "ok"
        assert result["entropy"] == 0.0
        assert result["normalized"] == 0.0

    def test_uniform_distribution_normalized_one(self):
        # 4 题材各霸榜天数相同 → 均匀分布，归一化熵=1
        result = rank_entropy({"a": 3, "b": 3, "c": 3, "d": 3})
        assert result["status"] == "ok"
        assert abs(result["normalized"] - 1.0) < 1e-4

    def test_insufficient_empty(self):
        assert rank_entropy({})["status"] == "insufficient"

    def test_zero_count_filtered_out(self):
        result = rank_entropy({"a": 5, "b": 0})
        assert result["status"] == "ok"
        assert result["k_themes"] == 1
        assert result["normalized"] == 0.0


class TestDedupLimitCount:
    def test_inflation_ratio_counts_overlap(self):
        # 3 只涨停股，其中 000988 属 AI 与芯片两题材 → 重复计数总和 4，守恒 3
        repeat = {"AI": {"000988", "002335"}, "芯片": {"000988", "301171"}}
        owner = {"000988": "AI", "002335": "AI", "301171": "芯片"}
        result = dedup_limit_count(repeat, owner)
        assert result["status"] == "ok"
        assert result["repeat_total"] == 4
        assert result["dedup_total"] == 3
        assert result["dedup_by_theme"] == {"AI": 2, "芯片": 1}
        assert abs(result["inflation_ratio"] - 4 / 3) < 1e-4

    def test_insufficient_empty_owner(self):
        result = dedup_limit_count({"AI": {"x"}}, {})
        assert result["status"] == "insufficient"
        assert result["dedup_total"] == 0
