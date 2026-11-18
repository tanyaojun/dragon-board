# -*- coding: utf-8 -*-
"""三态 dayStatus 读口透传守卫（2026-11-18 天普案遗留闭环）。

显示层三态徽章/留空依赖读口透传 dayStatus；投影漏字段＝显示层回退推断板
（复活废弃口径）。源串守卫与 test_relay_page_sector_nodes 同款（零 DB 零 jev）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_limitup_route_projects_day_status():
    src = (ROOT / "backend/api/hotlist_jev_limitup_routes.py").read_text(encoding="utf-8")
    assert '"dayStatus": (d.get("structure") or {}).get("dayStatus")' in src, \
        "涨停表读口须透传三态 dayStatus（停牌/数据洞显示层不得推断板）"


def test_cycle_series_projects_anchor_day_status():
    src = (ROOT / "backend/api/hotlist_jev_routes.py").read_text(encoding="utf-8")
    assert '"anchor.main.dayStatus": 1' in src
    assert '"anchor.growth.dayStatus": 1' in src, \
        "情绪周期锚徽章依赖 dayStatus 投影（漏字段＝停/? 徽章静默缺失）"
