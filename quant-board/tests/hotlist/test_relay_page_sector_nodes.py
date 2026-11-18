# -*- coding: utf-8 -*-
"""板块节点龙头列徽章口径守卫（2026-11-12 用户截图修复）。

钉住三件事：
1. 未封龙一高度位显区间高度 N天M板（台账 days/boards），旧「断板反包」琥珀徽章删除；
   缺档显「高度不可考」（fail-visible，不伪造板数）；
2. 续/断徽章只看今日龙一自身状态（leader.dayStatus，旧档回落 leaderSealedToday/
   streak），不得再消费 leaderState（=昨日龙一今日状态，节点判据口径）贴在今日
   龙一名旁（日出东方 4 板被误贴断板事故）；
3. leaderState 保留在展开卡「昨日龙一今日状态」（判据口径披露不删）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HTML = (Path(__file__).resolve().parents[2]
        / "backend" / "relay_page" / "index.html").read_text(encoding="utf-8")


def _fn(html: str, name: str) -> str:
    """按花括号配平抽取函数体（与 test_relay_page_theme_leaders 同规）。"""
    start = html.index("function " + name + "(")
    i = html.index("{", start)
    depth = 0
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
        i += 1
    raise AssertionError(f"function {name} 花括号不配平")


def test_nodes_leader_height_uses_range_not_rewrap_badge():
    fn = _fn(HTML, "renderNodes")
    assert "断板反包</span>" not in fn, "高度位旧琥珀徽章必须删除（用户判不正确）"
    assert "b-amber" not in fn, "龙头列不再用琥珀徽章占高度位"
    assert "ld.days + '天' + ld.boards + '板'" in fn, "未封龙一显 N天M板"
    assert "ld.boards + '板'" in fn, "days 缺回落 M板（不伪造天数）"
    assert "高度不可考" in fn, "区间高度缺档 fail-visible"
    assert "截至最近封板日" in fn, "tooltip 披露 num 截至 poolDay 口径"


def test_nodes_leader_state_badge_own_status_not_prev_leader():
    fn = _fn(HTML, "renderNodes")
    assert "const ls = r.leaderState" not in fn, \
        "续/断徽章不得消费昨日龙一状态（今/昨龙一常不同股）"
    assert "ld.dayStatus" in fn, "优先台账今日龙一自身状态（day_status_of 单源）"
    assert "leaderSealedToday === false ? 'broken'" not in fn, \
        "2026-11-18 天普案：旧档回退不得从 false 推 broken（分辨不了停牌/数据洞，复活废弃口径）"
    assert "'sealed' : 'unknown'" in fn, "旧档无 dayStatus 仅 sealed 可推，其余 unknown（? 徽章 fail-visible）"
    assert "ld.streak >= 2" in fn, "封板且真连板≥2 才贴续（首板不贴）"
    assert "停牌不算断板" in fn, "suspended 显停不显断板（v4 裁决）"


def test_nodes_detail_card_keeps_prev_leader_state_disclosure():
    fn = _fn(HTML, "renderNodes")
    assert "昨日龙一今日状态" in fn, "判据口径在展开卡显式披露（主语明确）"
    assert "r.leaderState ?" in fn, "leaderState 披露不删（节点判据可审计）"


def test_cycle_anchor_and_limitup_column_three_state_disclosure():
    """2026-11-18 天普案：三态 None 不得静默缺徽章/误标断板（显示层 fail-visible）。"""
    fn = _fn(HTML, "cycleAnchorCell")
    assert "a.dayStatus === 'suspended'" in fn and ">停</span>" in fn
    assert "a.dayStatus === 'unknown'" in fn and ">?</span>" in fn
    assert "r.dayStatus === 'suspended'" in HTML, "涨停表连板列停牌披露留空"
    assert "旧档无 dayStatus" in HTML, "梯队表旧档中性口径（不得误标今日未封板）"
