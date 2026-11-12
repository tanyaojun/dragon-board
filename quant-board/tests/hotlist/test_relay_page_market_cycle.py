# -*- coding: utf-8 -*-
"""市场情绪周期子页签沙箱守卫（第4课 P2，预登记 market-cycle-preregistration-20261112.md）。

钉住四件事（test_relay_page_sector_nodes 同规，静态抽取函数体断言）：
1. 子页签注册（RELAY_VIEWS cycle + rv-cycle 容器 + 中央处理器 cycleFetch 接线）；
2. 监控表四态词表 + 四事件标记 + 并列参照列（relay相位/大盘wzs/规则档，无预设权威）；
3. 龙一命运徽章只看自身 leaderSealedToday（封/断），缺档显—（fail-visible 不伪造）；
4. cycleFetch 走 market-cycle 读口，失败结构化透出（不闪断不清空）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

HTML = (Path(__file__).resolve().parents[2]
        / "backend" / "relay_page" / "index.html").read_text(encoding="utf-8")


def _fn(html: str, name: str) -> str:
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


def test_cycle_subtab_registered_and_wired():
    assert "['cycle', '情绪周期', '🌡️']" in HTML, "RELAY_VIEWS 须含情绪周期子页签"
    assert 'id="rv-cycle"' in HTML, "rv-cycle 容器在场"
    assert "cycleFetch(date);" in HTML, "中央数据处理器接线 cycleFetch"
    assert 'id="cycleTable"' in HTML and 'id="cycleHead"' in HTML


def test_cycle_state_and_event_vocab():
    assert "loss: '亏钱'" in HTML and "ice: '冰点'" in HTML
    assert "wzs: '弱转强'" in HTML and "gain: '赚钱'" in HTML
    assert "spaceBreakthrough: '↑突破'" in HTML and "spaceCompress: '↓压缩'" in HTML
    assert "highCollapse: '✗崩塌'" in HTML and "highTolerance: '✓宽容'" in HTML
    assert "市场情绪监控表" in HTML, "第4课核心工具标题"


def test_cycle_monitoring_table_reference_no_preset_authority():
    fn = _fn(HTML, "renderCycle")
    assert "CYCLE_STATE_CN" in fn and "CYCLE_EV_MARK" in fn
    assert "relayPhase" in fn and "marketWzs" in fn and "ruleStage" in fn, \
        "并列参照三源（relay相位/大盘wzs/规则档）进监控表"
    assert "无预设权威" in fn, "裁决1A：参照并列无预设权威"
    assert "daysInState" in fn, "days-in-state 披露（Q3 wzs 无超时）"


def test_cycle_anchor_badge_own_status_fail_visible():
    fn = _fn(HTML, "cycleAnchorCell")
    assert "leaderSealedToday === true" in fn, "封徽章只看龙一自身状态"
    assert "leaderSealedToday === false" in fn, "断徽章只看龙一自身状态"
    assert "—" in fn, "缺档显—（fail-visible 不伪造）"


def test_cycle_fetch_api_and_fail_visible():
    fn = _fn(HTML, "cycleFetch")
    assert "/api/hotlist-jev/market-cycle" in fn, "走 market-cycle 读口"
    assert "market_cycle_read_failed" in fn, "失败结构化透出"
    assert "STATE.cycleData.doc" in fn, "后台刷新失败保留旧数据（不闪断不清空）"
