"""方案 C'（2026-08-23）：全市场最新帧 analyze 的历史窗 load_limit 提升到
ANALYZE_FULL_MARKET_LOAD_LIMIT=280（实测 P90，dragonboard_live half_hour 当前帧活跃股
95% 以上历史出现 ≥50 次），替代旧 200 帧——旧窗口对 P90 活跃股不足（200 帧内约 36 次 < 50），
导致 macd/momentum 序列不完整。

本测试：验证全市场 latest analyze（无 frame_keys、codes 为空/大批量）调用 repo.load_frame_bundles
时 limit=ANALYZE_FULL_MARKET_LOAD_LIMIT（而非旧 200）。
"""
import pytest
from fastapi import HTTPException

from backend.api import ranktrend_routes


class FakeRepo:
    def __init__(self):
        self.calls = {}

    def load_frame_bundles(self, *args, **kwargs):
        self.calls["limit"] = kwargs.get("limit")
        return []


def test_full_market_analyze_uses_full_market_load_limit():
    repo = FakeRepo()
    # 全市场 latest analyze（无 frame_keys、codes 空）→ limit 应为 FULL_MARKET_LOAD_LIMIT
    with pytest.raises(HTTPException):
        ranktrend_routes._load_frames_for_analysis(
            repo, "ds", "half_hour", [], None, codes=None
        )
    assert repo.calls["limit"] == ranktrend_routes.ANALYZE_FULL_MARKET_LOAD_LIMIT
    assert ranktrend_routes.ANALYZE_FULL_MARKET_LOAD_LIMIT >= 200
