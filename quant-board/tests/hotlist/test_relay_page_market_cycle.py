# -*- coding: utf-8 -*-
"""情绪周期页合并守卫（2026-11 用户裁决，原 test_relay_page_market_cycle 重写）。

背景：原「连板情绪」（detail）改名「情绪周期」，原独立「情绪周期」（cycle）子页签删除，
其监控表「天花板/≥3板/主板龙一/双创龙一/事件」五列迁入 detail 日级表；同日表新增
v8 市场周期融合三题列（转折质量/周期强度/前瞻风险）。

钉住六件事（静态抽取函数体断言 + node 沙箱行为探针，零网络零 jev 调用，AGENTS §1.2-7）：
1. 合并注册：RELAY_VIEWS detail=情绪周期、cycle 子页签/rv-cycle 容器删除、cycleFetch 仍接线；
2. 日级表 16 列：原 8 列 + 融合三题 3 列 + 监控表迁入 5 列，展开行 colspan=16；
3. 周期五列按 tradingDate 合并 market-cycle series；龙一命运徽章只看自身
   leaderSealedToday（封/断），缺档显—（fail-visible 不伪造）；读失败原因页内披露；
4. 置信度 tooltip 化：detail 表与页头 KPI 不再出可见 P 芯片，悬停字段值读取；
5. 日期列版本徽章删除，题集版本迁入详情卡 title（非最新代琥珀警示语义保留）；
6. cycleFetch 走 market-cycle 读口（days=400 覆盖「全部」区间），失败结构化透出不闪断。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _const(html: str, name: str) -> str:
    start = html.index(f"const {name} = ")
    end = html.index(";", start)
    return html[start:end + 1]


def _arrow(html: str, name: str) -> str:
    """取多行箭头函数 const（按花括号配对，首个分号在函数体内，不能截断）。"""
    start = html.index(f"const {name} = ")
    i = html.index("{", start)
    depth = 0
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 2]   # 含结尾分号
        i += 1
    raise AssertionError(f"const {name} 花括号不配平")


# ── 1. 合并注册 ──────────────────────────────────────────────────────────────
def test_cycle_merged_into_detail_view():
    rv = _const(HTML, "RELAY_VIEWS")
    assert "'detail', '情绪周期'" in rv, "detail 子页应改名「情绪周期」"
    assert "'cycle'" not in rv, "原 cycle 独立子页签应删除"
    assert "'连板情绪'" not in rv, "旧页名不应残留"
    assert 'id="rv-cycle"' not in HTML, "rv-cycle 容器应删除"
    assert 'id="cycleTable"' not in HTML and 'id="cycleHead"' not in HTML
    assert "function renderCycle(" not in HTML, "renderCycle 应随页面删除"
    assert "cycleFetch(date);" in HTML, "中央数据处理器仍接线 cycleFetch（周期五列数据源）"
    assert 'id="rv-detail"' in HTML and 'id="relayTable"' in HTML
    assert 'class="relay-wrap"' in HTML, "16 列宽表须有横向滚动容器"
    assert ".relay-wrap::-webkit-scrollbar" in HTML, "滚动条样式在场"
    assert 'id="relayCycleHint"' in HTML, "周期列覆盖度/降级披露挂载点在场"


# ── 2. 日级表 16 列 ──────────────────────────────────────────────────────────
def test_detail_table_sixteen_columns():
    rt = _fn(HTML, "renderRelayTab")
    head = rt[rt.index("$('relayTable').innerHTML"):]
    # 评审 P2-7：精确钉住表头列名序列与数量（防第 17 列忘改 colspan / OR 支路弱断言）
    head_line = head[:head.index("\n")]
    labels = [a or b for a, b in re.findall(r"th\('([^']+)'|<th>([^<]+)</th>", head_line)]
    assert labels == ["日期", "指数", "分区", "相位", "边际", "节点", "梯队", "钱效",
                      "转折质量", "周期强度", "前瞻风险",
                      "天花板", "≥3板", "主板龙一", "双创龙一", "事件"], \
        f"表头 16 列序列不符：{labels}"
    assert 'colspan="16"' in rt, "展开详情行与空态 colspan 应为 16"
    assert 'colspan="8"' not in rt, "旧 8 列 colspan 不应残留"
    # 融合三题列：值源 relay 存档顶层字段 + answers 置信度，词表/配色单源
    for k in ("r.turnQuality", "r.cycleIntensity", "r.riskAhead",
              "MC_TURN_CN", "MC_INTENSITY_CN", "MC_RISK_CN",
              "turn_quality", "cycle_intensity", "risk_ahead"):
        assert k in rt, f"融合三题列缺 {k}"
    assert "v8 前旧代" in rt, "旧代档无三题值须显式披露（代际区分非缺判）"


# ── 3. 周期五列合并 + fail-visible ───────────────────────────────────────────
def test_cycle_columns_merged_by_trading_date():
    rt = _fn(HTML, "renderRelayTab")
    assert "STATE.cycleData" in rt and "cycleMap" in rt, "周期列须从 cycleData 合并"
    assert "String(s.tradingDate)" in rt, "按 tradingDate 建映射"
    assert "ceil.maxBoard" in rt and "ceil.threePlusN" in rt, "天花板/≥3板取 ceiling"
    assert rt.count("cycleAnchorCell(") == 2, "主板/双创龙一两列都走 cycleAnchorCell"
    assert "cy.anchor && cy.anchor.main" in rt and "cy.anchor && cy.anchor.growth" in rt
    assert "CYCLE_EV_MARK" in rt, "事件列用四事件标记词表"
    assert "cycMiss" in rt and "market-cycle 读口失败" in rt, \
        "未覆盖/读失败显 — 并 tooltip 注明原因（fail-visible 不伪 0）"
    assert "周期列加载中，覆盖度未知" in rt and "周期列待取数" in rt, \
        "加载中/未取数不得提前断言「无存档」（评审 P2-1）"
    assert "relayCycleHint" in rt and "degradedCount" in rt, "覆盖度/降级日数页内披露"


def test_cycle_event_vocab():
    assert "spaceBreakthrough: '↑突破'" in HTML and "spaceCompress: '↓压缩'" in HTML
    assert "highCollapse: '✗崩塌'" in HTML and "highTolerance: '✓宽容'" in HTML


def test_cycle_anchor_badge_own_status_fail_visible():
    fn = _fn(HTML, "cycleAnchorCell")
    assert "leaderSealedToday === true" in fn, "封徽章只看龙一自身状态"
    assert "leaderSealedToday === false" in fn, "断徽章只看龙一自身状态"
    assert "—" in fn, "缺档显—（fail-visible 不伪造）"


def test_cycle_fetch_api_and_fail_visible():
    fn = _fn(HTML, "cycleFetch")
    assert "/api/hotlist-jev/market-cycle?days=400" in fn, \
        "走 market-cycle 读口且 days=400 与 relay-index 同窗（覆盖「全部」区间）"
    assert "market_cycle_read_failed" in fn, "失败结构化透出"
    assert "STATE.cycleData.api" in fn, "后台刷新失败保留旧数据（不闪断不清空）"
    assert fn.count("renderRelayTab()") >= 2, "取数前后重绘日级表合并周期列"
    assert "if (!bg) renderRelayTab();" in fn, \
        "后台静默刷新免预绘（评审 P2-4：减少展开卡焦点打断）"
    assert "sbLog" in fn, "读失败进底部状态栏"


def test_setview_rerenders_on_actual_subview_switch():
    """评审 P2-5：KPI 置信度 tooltip 模式保鲜防线——子视图实际切换时 setView 须重绘；
    同视图回填（loadAll 尾部）不重绘（评审 P2-4：轮询路径单次重建）。"""
    sv = _fn(HTML, "setView")
    assert "renderRelayTab()" in sv, "进 relay 子页须重绘（KPI tooltip 模式保鲜）"
    assert "prevRelayView !== STATE.relayView" in sv, "仅子视图实际切换才重绘"


# ── 4. 置信度 tooltip 化 ─────────────────────────────────────────────────────
def test_confidence_tooltip_in_detail_table():
    rt = _fn(HTML, "renderRelayTab")
    assert "confChip(" not in rt, "情绪周期表不得再出可见置信芯片"
    assert "confAttr(" in rt and "critConfTip(" in rt, "置信度改悬停字段值读取"
    ct = _arrow(HTML, "critConfTip")
    assert "confTitle(conf)" in ct and "critText(qid, choice)" in ct, \
        "判据全文与置信度合并进同一 tooltip"


def test_confidence_tooltip_in_kpi_only_on_detail_view():
    kpi = _fn(HTML, "renderRelayKpi")
    assert "STATE.relayView === 'detail'" in kpi, "tooltip 模式只作用于情绪周期子视图"
    assert "confChip(c)" in kpi, "其余子视图保持可见芯片（cf 分支）"
    assert "cv(conf)" in kpi, "tooltip 模式下置信度挂 .v 元素 title"


def test_conf_helpers_behaviour(tmp_path):
    """node 探针：confTitle/confAttr/critConfTip 纯函数行为（零网络）。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        "const esc = v => String(v == null ? '' : v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/\"/g,'&quot;');",
        _const(HTML, "confPct"),
        _const(HTML, "CONF_LOW"),
        _const(HTML, "CONF_OK"),
        _arrow(HTML, "confTitle"),
        _arrow(HTML, "confAttr"),
        "const STATE = { criteria: { relay_phase: { relay_heat: '判据全文X' } } };",
        _arrow(HTML, "critText"),
        _arrow(HTML, "critConfTip"),
        "console.log(JSON.stringify({",
        "  hi: confTitle(0.62), low: confTitle(0.2), nil: confTitle(null), nan: confTitle(NaN),",
        "  attr: confAttr(0.62), attrNil: confAttr(null),",
        "  both: critConfTip('relay_phase', 'relay_heat', '相位', null, 0.62),",
        "  confOnly: critConfTip('relay_phase', 'unknown', '相位', null, 0.5),",
        "  critOnly: critConfTip('relay_phase', 'relay_heat', '相位', null, null),",
        "  none: critConfTip('relay_phase', 'unknown', '相位', null, null),",
        "}));",
    ])
    script = tmp_path / "conf_tip_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got["hi"] == "模型置信度 P62"
    assert "两可" in got["low"] and "P20" in got["low"]
    assert got["nil"] == "" and got["nan"] == ""
    assert got["attr"] == ' title="模型置信度 P62"' and got["attrNil"] == ""
    assert "判据全文X" in got["both"] and "模型置信度 P62" in got["both"]
    assert got["confOnly"] == ' title="模型置信度 P50"'
    assert "判据全文X" in got["critOnly"] and "置信度" not in got["critOnly"]
    assert got["none"] == ""


# ── 5. 版本徽章：日期列删除 → 详情卡 title ───────────────────────────────────
def test_version_badge_moved_to_detail_card_title():
    rt = _fn(HTML, "renderRelayTab")
    assert "verBadge" not in rt, "日期列版本徽章应删除"
    assert "questionSetVersion" not in rt, "日期列不再拼版本号"
    dh = _fn(HTML, "detailHtml")
    assert "verTag" in dh and "view === 'relay'" in dh, "版本徽标只挂 relay 详情卡"
    title_seg = dh[dh.index("const head ="):dh.index("const meta =")]
    assert "${verTag}" in title_seg, "版本号须在详情卡 title（lg-title）内"
    assert "d.questionSetVersion === curVer ? 'b-gray' : 'b-amber'" in dh, \
        "非最新代琥珀警示（原混代际守卫语义保留）"
    assert "题集版本" in dh, "foot 题集版本全文保留（旧档「未知（旧文档）」披露不丢）"


def test_cycle_anchor_cell_behaviour(tmp_path):
    """node 探针：龙一命运徽章封/断/缺档三态。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        "const esc = v => String(v == null ? '' : v);",
        _fn(HTML, "cycleAnchorCell"),
        "console.log(JSON.stringify({",
        "  sealed: cycleAnchorCell({code:'600101',name:'甲A',leaderSealedToday:true}),",
        "  broken: cycleAnchorCell({code:'600101',name:'甲A',leaderSealedToday:false}),",
        "  unknown: cycleAnchorCell({code:'600101',name:'甲A'}),",
        "  missing: cycleAnchorCell(null),",
        "}));",
    ])
    script = tmp_path / "cycle_anchor_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert "甲A" in got["sealed"] and ">封<" in got["sealed"]
    assert ">断<" in got["broken"]
    assert "封" not in got["unknown"] and "断" not in got["unknown"]
    assert got["missing"] == '<span style="color:var(--muted2)">—</span>'
