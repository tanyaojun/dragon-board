"""边际 Spearman IC 已知答案测试（因子口径收敛批 TaskB）。

边际 IC = 候选因子秩对基准秩 OLS 残差后与 forward 的秩相关——回答
"候选因子在基准之上是否仍有增量信息"（Phase 3 裁决标准的统计实现）。
"""

from __future__ import annotations

import pytest

from backend.analysis.theme.rank_ic import marginal_spearman_ic


class TestMarginalSpearmanIC:
    def test_known_answer_hand_computed_residual(self) -> None:
        """手算已知答案：b=[1,2,3,4]，r=[2,1,4,3] → OLS 残差 [0.4,-1.2,1.2,-0.4]，
        forward=[3,1,4,2] 按残差升序 → 边际 IC = 1.0（朴素 IC 仅 0.8）。"""
        factor = [2.0, 1.0, 4.0, 3.0]
        baseline = [1.0, 2.0, 3.0, 4.0]
        forward = [3.0, 1.0, 4.0, 2.0]
        ic = marginal_spearman_ic(factor, baseline, forward)
        assert ic == pytest.approx(1.0)
        from backend.analysis.theme.rank_ic import spearman_rank_ic

        assert spearman_rank_ic(factor, forward) == pytest.approx(0.8)

    def test_factor_identical_to_baseline_returns_none(self) -> None:
        """候选与基准秩完全共线 → 残差全等 → 无边际信息 → None（不伪造 0）。"""
        assert marginal_spearman_ic([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [3.0, 1.0, 2.0]) is None

    def test_none_pairs_dropped_and_min_samples(self) -> None:
        # 任一侧缺失 → 该观测成对剔除
        ic = marginal_spearman_ic(
            [2.0, None, 4.0, 3.0, 1.0],
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [3.0, 1.0, None, 4.0, 2.0],
        )
        assert ic is None or isinstance(ic, float)
        # 剔除后 n<3 → None
        assert (
            marginal_spearman_ic(
                [2.0, None, None], [1.0, 2.0, 3.0], [3.0, None, None]
            )
            is None
        )
        assert marginal_spearman_ic([1.0, 2.0], [1.0, 2.0], [2.0, 1.0]) is None

    def test_length_mismatch_returns_none(self) -> None:
        assert marginal_spearman_ic([1.0, 2.0, 3.0], [1.0, 2.0], [1.0, 2.0, 3.0]) is None
