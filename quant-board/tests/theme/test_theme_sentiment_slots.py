"""Phase 1 小模块已知答案校验：情绪取数回退（sentiment_slots）+ Spearman 秩相关（rank_ic）。"""

from backend.analysis.theme.rank_ic import spearman_rank_ic
from backend.analysis.theme.sentiment_slots import pick_sentiment_snapshot


def _ls(zt=None, rate=None, max_board=None):
    zhaban = {}
    if zt is not None:
        zhaban["ztCount"] = zt
    if rate is not None:
        zhaban["rate"] = rate
    ls = {"zhaban": zhaban} if zhaban else {}
    if max_board is not None:
        ls["continuousBoards"] = {"maxBoard": max_board}
    return ls or None


class TestPickSentimentSnapshot:
    def test_daily_1530_has_priority(self):
        daily = _ls(zt=60, rate=0.22, max_board=5)
        hh = [("15:00", _ls(zt=50, rate=0.30)), ("14:00", _ls(zt=40))]
        snap = pick_sentiment_snapshot(daily, hh)
        assert snap["status"] == "ok" and snap["source"] == "daily:15:30"
        assert snap["ztCount"] == 60 and snap["zhabanRate"] == 0.22 and snap["maxBoard"] == 5

    def test_falls_back_to_latest_half_hour_slot(self):
        hh = [("15:00", None), ("14:30", _ls(zt=45, rate=0.31)), ("11:00", _ls(zt=44))]
        snap = pick_sentiment_snapshot(None, hh)
        assert snap["status"] == "ok" and snap["source"] == "half_hour:14:30"
        assert snap["ztCount"] == 45

    def test_excludes_early_slots(self):
        # 仅 09:30/10:00 有值 → 不可取（首槽 THS 池未建满，Phase 0 实证）
        hh = [("10:00", _ls(zt=20)), ("09:30", _ls(zt=5))]
        assert pick_sentiment_snapshot(None, hh)["status"] == "insufficient"

    def test_slot_order_not_input_order(self):
        # 无序输入也按槽位时间倒序取最近有值槽
        hh = [("11:00", _ls(zt=44)), ("15:00", _ls(zt=50)), ("13:30", _ls(zt=46))]
        snap = pick_sentiment_snapshot(None, hh)
        assert snap["source"] == "half_hour:15:00" and snap["ztCount"] == 50

    def test_missing_fields_stay_none_not_fabricated(self):
        snap = pick_sentiment_snapshot(_ls(zt=60), [])
        assert snap["status"] == "ok"
        assert snap["ztCount"] == 60
        assert snap["zhabanRate"] is None and snap["maxBoard"] is None

    def test_empty_inputs_insufficient(self):
        assert pick_sentiment_snapshot(None, [])["status"] == "insufficient"
        assert pick_sentiment_snapshot(_ls(zt=60), None)["status"] == "ok"

    def test_top_level_ztcount_fallback(self):
        # 顶层 ztCount 兜底（部分帧无 zhaban 子对象）
        snap = pick_sentiment_snapshot({"ztCount": 33}, [])
        assert snap["status"] == "ok" and snap["ztCount"] == 33

    def test_all_none_fields_treated_as_valueless_frame(self):
        # limitSummary 存在但关键字段全缺 → 该帧不可作回退来源
        hh = [("15:00", {"foo": 1}), ("14:00", _ls(zt=41))]
        snap = pick_sentiment_snapshot(None, hh)
        assert snap["source"] == "half_hour:14:00" and snap["ztCount"] == 41


class TestSpearmanRankIc:
    def test_perfect_monotonic(self):
        assert spearman_rank_ic([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == 1.0
        assert spearman_rank_ic([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == -1.0

    def test_ties_use_average_ranks(self):
        # xs=[1,2,2,3] 秩=[1,2.5,2.5,4]；ys 秩=[1,2,3,4]。
        # 平均秩下严格单调但有并列 ≠ 1.0（标准 Spearman 定义）：cov=4.5, var_x=4.5, var_y=5
        assert abs(spearman_rank_ic([1.0, 2.0, 2.0, 3.0], [7.0, 8.0, 9.0, 10.0]) - 0.9486832980505138) < 1e-9

    def test_all_ties_returns_none(self):
        assert spearman_rank_ic([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None

    def test_too_few_observations(self):
        assert spearman_rank_ic([1.0], [2.0]) is None
        assert spearman_rank_ic([], []) is None

    def test_known_mixed_case(self):
        # 经典教科书序列：xs=[1,2,3,4,5], ys=[1,3,2,5,4] → rho=0.8
        assert abs(spearman_rank_ic([1, 2, 3, 4, 5], [1, 3, 2, 5, 4]) - 0.8) < 1e-9
