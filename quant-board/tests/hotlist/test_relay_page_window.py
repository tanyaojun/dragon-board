# -*- coding: utf-8 -*-
"""relay_page 判定明细页前端守卫测试（2026-10-18 用户裁决版）。

需求（浏览器页 http://127.0.0.1:8008 · 判定明细页）：
1. 日期区间控件回到「两个日期控件 + 近1月/近3月/全部三个按钮」原生形态，
   位置在**页头**；删除临时加的 4 日期 / 1 按钮 / 按钮后的文字说明控件。
2. 明细表删除 tokens / 判定时间两列，新增「龙头强度」列。
3. 表头筛选新增「分区」「龙头强度」两个下拉。
4. 「判定明细」标题后不再有大段文字说明；标题字号与其他页一致（不放大）。
   （2026-10-19 用户裁决：四页（相位分线/分带观察/板块与龙头/判定明细）页头**整块**
   ——粗体标题 + 小字辅助行（hint/provenance/说明段）+ 命令面板 + 分隔线——全部删除；
   手动刷新入口改由滞后黄条 / 未就绪提示内置按钮提供。）
5. 点列表行 → 页头 KPI 卡联动到该日；KPI 第三行改为**档位描述**（该档位意味着什么），
   不再显示「量化比率口径」这类统计口径文字。
6. （2026-10-19 用户裁决）页名「判定明细」→「**涨停分析**」；其日级表右上原计数
   「59 / 59 日（全库 109）」改为**分页控件**，每页上限 20 条，右侧只报总页数「共 X 页」
   （筛选/区间/排序变更回第 1 页，越界自动 clamp；分页只切展示行，KPI/分带/相位口径不变）。

本测试是**静态源码守卫**（无浏览器、零网络、零 jev 调用，AGENTS §1.2-7）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_PAGE = Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js(html: str) -> str:
    m = re.search(r"<script>([\s\S]*)</script>", html)
    assert m, "relay_page 应含唯一 <script> 块"
    return m.group(1)


def _fn(js: str, name: str) -> str:
    """取一个顶层函数的函数体文本（按花括号配对截到函数结尾，不向下一个函数溢出）。"""
    start = js.index(f"function {name}(")
    brace = js.index("{", start)
    depth = 0
    for i in range(brace, len(js)):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
    raise AssertionError(f"未找到 {name} 的函数结尾")


def _const(js: str, name: str) -> str:
    """取一个顶层 const 的声明语句（到第一个分号）。"""
    start = js.index(f"const {name} = ")
    end = js.index(";", start)
    return js[start : end + 1]


def _const_block(js: str, name: str) -> str:
    """取一个顶层 `const NAME = {...};` 对象字面量文本（按花括号配对，不向下溢出）。"""
    start = js.index(f"const {name} = ")
    brace = js.index("{", start)
    depth = 0
    for i in range(brace, len(js)):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[start : i + 1]
    raise AssertionError(f"未找到 {name} 的对象字面量结尾")



# ── 需求 1：页头 = 2 日期 + 3 按钮；无多余控件与文字说明 ─────────────────────
def test_range_bar_is_two_inputs_three_buttons(js: str):
    """rRangeBar(): 2 个日期控件 + 近1月/近3月/全部 三按钮。"""
    bar = _fn(js, "rRangeBar")
    assert bar.count('type="date"') == 2, "应有 2 个日期控件"
    # 三个预设按钮由 pbtn() 生成
    for kind, txt in (("m1", "近1月"), ("m3", "近3月"), ("all", "全部")):
        assert f"pbtn('{kind}', '{txt}')" in bar, f"缺按钮 {txt}"
    assert "<button" in bar, "按钮模板应在 rRangeBar 内（pbtn）"
    # 不保留月份控件（用户明确不要）
    assert 'type="month"' not in js, "不应再有月份控件"


def test_range_bar_semantics_follow_original(js: str):
    """回归：原作者语义必须保留（2026-10-18 BUG 复盘）。

    BUG1 结束框留空语义：end=null 时输入框显示最新交易日（而不是空壳）。
    BUG2 预设按钮必须回填日期框：winMount 的焦点守卫不得拦到按钮焦点。
    BUG3 默认近1月：序列未到位时不得把空态钉死。
    """
    bar = _fn(js, "rRangeBar")
    assert "rg.end || last" in bar, "BUG1: 结束框应回落最新交易日，不能留空壳"
    assert "min=" not in bar and "max=" not in bar, "不应给 date 控件加 min/max"
    assert 'class="sep"' in bar, "两个日期控件之间应有分隔符"

    mount = _fn(js, "winMount")
    assert "ae.type === 'date'" in mount, \
        "BUG2: 焦点守卫只能拦日期控件自身，不能拦按钮"
    assert "rangeRefresh();" in _fn(js, "rPreset"), "预设按钮必须触发重绘"
    assert "rangeRefresh();" in _fn(js, "rRange"), "日期变更必须触发重绘"
    # renderRelayTab 内必须重新挂载区间控件（否则按钮改了 state 而控件不回填）
    assert "winMount()" in _fn(js, "renderRelayTab"), "renderRelayTab 应重新挂载区间控件"

    rs = _fn(js, "rangedSeries")
    assert "if (!s.length) return []" in rs, "BUG3: 序列未到位时不得固化空态默认值"
    assert "defaultRange()" in rs, "BUG3: 默认区间应与预设回退同源（近1月）"
    assert "getMonth() - (kind === 'm1' ? 1 : 3)" in _fn(js, "presetRange"), "默认区间应为近1月"


def test_range_bar_mounted_in_relay_tabbar(html: str, js: str):
    """2026-10-18 用户裁决：区间控件挂在子页切换栏（tabbar）右侧，五子页共用。"""
    # 不在判定明细页头了
    seg = html[html.index('id="rv-detail"'):]
    seg = seg[: seg.index("</section>")]
    assert 'id="rangeBarHost"' not in seg, "BUG: 区间控件应已从判定明细页头移走"
    # 改挂在 tab 行
    setview = _fn(js, "setView")
    assert 'id="rangeBarHost"' in setview, "tab 行应含区间控件挂载点"
    assert "winMount()" in setview, "tabbar 重建后应回填区间控件"
    assert "winBar" not in js, "旧 winBar 控件应整体删除"
    assert ".winbar" not in html, "旧 winbar 样式应删除"
    # 控件仍由渲染周期挂载（五子页都走 renderRelayTab）
    rt = _fn(js, "renderRelayTab")
    assert "winMount()" in rt, "区间控件应由 renderRelayTab 挂载"


def test_detail_filter_bar_has_no_date_controls(js: str):
    """筛选条里不再有日期区间控件（已上提页头）。"""
    rt = _fn(js, "renderRelayTab")
    assert "rRangeBar()" not in rt, "筛选条不应再渲染 rRangeBar"
    assert 'type="date"' not in rt


# ── 需求 2：表格列 ─────────────────────────────────────────────────────────
def test_table_columns_drop_tokens_time_add_leader(js: str):
    """表头：去 tokens/判定时间，加龙头强度（共 9 列）。"""
    rt = _fn(js, "renderRelayTab")
    head = rt[rt.index('$(\'relayTable\').innerHTML'):]
    assert "tokens" not in head, "表头不应再含 tokens 列"
    assert "判定时间" not in head, "表头不应再含判定时间列"
    assert "龙头强度" in head, "表头应含龙头强度列"
    assert "节点" in head and "wzsB" in rt, "表头应含弱转强节点列（2026-10-21 立项）"
    assert 'colspan="10"' in rt, "展开详情行 colspan 应为 10（加节点列后）"
    assert 'rWzsSel' in js, "节点筛选下拉必须接线"
    assert "'weak', '弱']" in js and "'strong', '强']" in js and "'wzs', '弱转强']" in js,         "节点筛选枚举必须三态（弱/弱转强/强，2026-10-22 用户裁决）"
    assert "w.state === 'wzs'" in rt and "w.state === 'strong'" in rt,         "节点徽标须按 state 分支（wzs/strong）"
    assert "if (w.state === 'weak')" in rt, "弱徽标须显式分支（审查 nit：未知枚举不 fall-through 伪装成弱）"
    assert "STATE.wzsBaseline" in js, "全史延续率必须现算透传（审查 SF-2：禁止硬编码快照数字）"
    assert "3/18" not in js, "延续率快照数字不得硬编码在前端"
    # 行体不再渲染 token 数 / computedAt 单元格
    assert "input_tokens" not in rt and "output_tokens" not in rt
    assert "computedAt" not in rt


# ── 需求 3：新增两个筛选下拉 ───────────────────────────────────────────────
def test_zone_filter_keys_are_complete_and_unique(js: str):
    """分区筛选：枚举与 zoneKey 必须覆盖 ZONE_DEF 全部键，不得手抄导致分叉。

    2026-10-18 BUG 复盘：zoneKey 曾只手抄 toxic/ice/green 三个 label，
    mid/neutral/na 全归 'other'，两个「中性」选项永远筛不出结果。
    另：枚举曾手写两份 label，两个选项都叫「中性」，用户无法区分。
    """
    # zoneKey 不再是手写 label→key 三元表达式
    zk = _fn(js, "zoneKey")
    assert "=== '毒带观察' ?" not in zk, "BUG: zoneKey 不得再手抄 label 映射"
    assert "ZONE_KEY_OF" in zk, "zoneKey 应由 ZONE_DEF 反查键"
    assert "Object.keys(ZONE_DEF)" in js, "键集合应直接取自 ZONE_DEF"

    # 枚举由 ZONE_DEF 派生（不得再手写 label 字面量数组）
    zfl = _const(js, "ZONE_FILTER_LIST")
    assert "ZONE_DEF[k].label" in zfl, "BUG: 分区枚举应派生自 ZONE_DEF，不得手抄"
    assert "'绿灯区'" not in zfl and "'中性区'" not in zfl, "枚举不得硬编码 label"
    # 六个键都要在枚举里
    for k in ("green", "toxic", "mid", "neutral", "ice", "na"):
        assert f"'{k}'" in zfl, f"分区枚举缺键 {k}"


def test_zone_filter_actually_matches_each_option(js: str, tmp_path):
    """**行为**回归：把 zoneOf/zoneKey/枚举真实源码抽出来在 Node 里跑，
    断言六个键都能分别命中样本日（不是只断言字样）。

    变异测试已验：把 zoneKey 改回手抄版，mid/neutral 立即变成 'other' 归零 → FAIL。
    """
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        _const(js, "ZONE_DEF"),
        _const(js, "ZONE_KEY_OF"),
        _fn(js, "zoneKey"),
        _fn(js, "zoneOf"),
        "const days = [",
        "  { relayIndex: 70, dayTemperature: 80 },   // green",
        "  { relayIndex: 50, dayTemperature: 60 },   // toxic (40-60 ∧ 温≥56)",
        "  { relayIndex: 50, dayTemperature: 30 },   // mid (40-60 ∧ 温<56)",
        "  { relayIndex: 50, dayTemperature: null }, // mid (温度缺不判毒)",
        "  { relayIndex: 30, dayTemperature: 10 },   // neutral (25-40)",
        "  { relayIndex: 10, dayTemperature: 10 },   // ice (<25)",
        "  { relayIndex: null, dayTemperature: null }, // na",
        "];",
        "const keys = days.map(d => zoneKey(zoneOf(d)));",
        "console.log(JSON.stringify(keys));",
    ])
    script = tmp_path / "zone_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got == ["green", "toxic", "mid", "mid", "neutral", "ice", "na"], (
        f"分区键派生不符：{got}（mid/neutral 不得归 other）")
    # 六个键互不相同（不得出现两个选项指向同一键 / 同一 label）
    assert len(set(got)) == 6, "分区键应两两可区分"


def test_two_new_filters_zone_and_leader(js: str):
    """筛选条增加「分区」「龙头强度」两个下拉，且状态可重置。"""
    rt = _fn(js, "renderRelayTab")
    bar = rt[rt.index("bar.innerHTML"):]
    assert "rZoneSel()" in bar, "应有分区筛选"
    assert "rLeaderSel()" in bar, "应有龙头强度筛选"
    assert "rZoneSel" in js and "rLeaderSel" in js
    # 分区筛选与 zoneOf 同源（不另抄阈值）
    assert "zoneKey(zoneOf(r)) === f.zone" in rt
    assert "leaderBandOf(r) === f.leader" in rt
    # rClear 重置新字段
    clear = _fn(js, "rClear")
    assert "zone: ''" in clear and "leader: ''" in clear


# ── 需求 4：标题后无大段说明、字号一致 ─────────────────────────────────────
# 2026-10-19 用户裁决（截图）：四页页头粗体标题（<h2>）与 tab 名重复，全部删除；
# 功能性内容（区间 hint / 产物 provenance / 重跑按钮 / 数据来源说明）一律保留。
def test_four_views_have_no_bold_page_titles(html: str):
    """相位分线 / 分带观察 / 板块与龙头 / 判定明细 四页不得再有页头（含 <h2> 与整块辅助行）。"""
    bounds = [('id="rv-phase"', 'id="rv-bands"'), ('id="rv-bands"', 'id="rv-leaders"'),
              ('id="rv-leaders"', 'id="rv-detail"'), ('id="rv-detail"', "</section>")]
    for anchor, end in bounds:
        seg = html[html.index(anchor):]
        seg = seg[: seg.index(end)]
        assert "<h2" not in seg, f"{anchor} 页头粗体标题应已删除（与 tab 名重复）"
        assert 'class="page-head"' not in seg, f"{anchor} 整块页头（标题+小字辅助行）应已删除"
        assert 'class="ph-line"' not in seg, f"{anchor} 页头分隔线应已删除"
    # 其它工作台页（总览/涨停复盘/连板行情）不在本次范围，标题保留
    assert html.count("<h2>") >= 3, "非 relay 子页的页头标题不应被误删"


def test_removed_page_head_leaves_no_dead_hooks(html: str, js: str):
    """删整块后不得留悬空钩子：挂载点/写入语句/命令面板全部清掉，刷新入口仍在。"""
    for gone in ('id="phaseChartHint"', 'id="diagProvenance"', 'id="bandCmd"'):
        assert gone not in html, f"悬空挂载点 {gone} 应已删除"
    for dead in ("$('phaseChartHint')", "$('diagProvenance')", "function showBandCmd(",
                 "$('bandCmd')", ".cmdbox", ".tabchip"):
        assert dead not in html, f"悬空引用 {dead} 应已删除（含死 CSS）"
    detail = html[html.index('id="rv-detail"'):]
    detail = detail[: detail.index("</section>")]
    assert "<p" not in detail, "判定明细页头说明应已删除"
    # 手动刷新逃生口不得随之丢失：滞后黄条 / 未就绪提示内仍带按钮
    assert "bandRefreshBtn()" in _fn(js, "bandRefreshWarnHtml")
    assert "bandRefreshBtn()" in js[js.index("const bandDiagMissing"):js.index("const bandRefreshBusy")]
    assert "function bandRefresh(" in js, "刷新实现与入口不应被删"


# ── 需求 5：点行联动 KPI + 档位描述 ────────────────────────────────────────
def test_row_click_links_kpi_to_date(js: str):
    """relayRow 设置 relayFocus，renderRelayKpi 优先用它。"""
    row = _fn(js, "relayRow")
    assert "STATE.relayFocus" in row, "点行应记录 focus 日期"
    kpi = _fn(js, "renderRelayKpi")
    assert "STATE.relayFocus" in kpi, "KPI 应优先读行选日期"
    assert "行选" in kpi, "应在卡上明示行选日期"
    # 取消选中（再点同一行）回落到日期框/最新日
    assert "STATE.relayFocus === key ? null : key" in row


def test_row_click_selects_only_caret_toggles_panel(html: str, js: str):
    """2026-10-18 用户裁决：点行=只选中（KPI 跟随）；展开/收敛只归左侧三角。

    回归点：以前 relayRow 里同时改 openKey（点行即展开 JEV 结果），
    现拆为 relayRow（只动 relayFocus）+ relayToggle（只动 openKey）。
    """
    row = _fn(js, "relayRow")
    assert "openKey" not in row, "BUG: 点行不得再动展开态（不得改 openKey）"
    assert "relayDocs" not in row, "BUG: 点行不得再触发 JEV 文档拉取"
    assert "renderRelayTab()" in row, "点行仍需重绘（KPI 联动）"

    tog = _fn(js, "relayToggle")
    assert "STATE.detailUi.relay" in tog and "openKey" in tog, "三角应控展开态"
    assert "relayFocus" not in tog, "BUG: 三角不得改动选中态"
    # 懒拉实现已抽到 relayDocFetch（2026-10-18 review B6：失败哨兵/重试要单点）；
    # 这里守的是「三角展开确实会触发 JEV 存档拉取」这一行为契约。
    assert "relayDocFetch(" in tog, "三角展开时懒拉当日 JEV 存档（走 relayDocFetch）"
    assert "relay-index?days=1" in _fn(js, "relayDocFetch"), "拉取实现应在 relayDocFetch 内"

    # 行内三角：stopPropagation（不触发选中切换）+ 指向 relayToggle
    rt = _fn(js, "renderRelayTab")
    assert "event.stopPropagation(); relayToggle(" in rt, \
        "三角点击必须 stopPropagation 并调 relayToggle"
    assert 'onclick="relayRow(' in rt, "整行仍有选中 handler"
    assert "lg-row.open .lg-caret{transform:rotate(90deg)}" in html, \
        "展开时三角应旋转（视觉反馈）"


def test_kpi_third_line_is_tier_description(js: str):
    """KPI 第三行为档位描述，不是统计口径文字。"""
    kpi = _fn(js, "renderRelayKpi")
    for d in ("PHASE_DESC", "MOM_DESC", "LADDER_DESC", "MONEY_DESC", "THEME_DESC", "leaderDesc"):
        assert d in kpi, f"KPI 应使用 {d}"
    # 旧口径语义文案已删
    for stale in ("量化比率口径", "主锚三日链", "晋级/断板/溢价", "近5日榜", "最高板地位", "今日 vs 昨日"):
        assert stale not in js, f"旧统计口径文案应删除：{stale}"


def test_ladder_balanced_displayed_and_filterable(js: str):
    """v7 ladder_health 新增 balanced 过渡档，前端三面同步（2026-10-20 用户需求）。

    背景：v7 D7-1 给 ladder_health 补了 balanced 档（中位偏薄未断层：二板/三板+比率
    0.5-1.5 且梯队总量处参照正常带，权威全文 = jev_relay_ammo.QUESTIONS_RELAY），
    relay index 已可能产出该值。前端 KPI 徽标 / 涨停分析表 / 梯队结构卡 / 折线 tooltip
    共用 LADDER_CN，漏加即显示英文原文，且筛选枚举（Object.entries(LADDER_CN) 派生）
    也无该项——四角同源，补一处全通。
    """
    # ① 中文类型（筛选下拉枚举同源派生，含 balanced 即自动可筛）
    m = re.search(r"const LADDER_CN = \{[^}]*\}", js)
    assert m and "balanced:" in m.group(0), "LADDER_CN 应含 balanced 中文类型（筛选枚举同源）"
    assert "ladder: Object.entries(LADDER_CN)" in js, "筛选枚举应派生自 LADDER_CN（balanced 自动可筛）"
    # ② 摘要描述（读口失败时的回落，漏加即 tooltip 回落空）
    m = re.search(r"const LADDER_DESC = \{[\s\S]*?\};", js)
    assert m and "balanced:" in m.group(0), "LADDER_DESC 应含 balanced 摘要描述"
    # ③ 徽标色：ladderB 对 balanced 显式配色（该档属健康带——未断层未倒挂、总量正常，非警示非证据缺失）
    lb = re.search(r"const ladderB = [^\n]+", js)
    assert lb and "balanced" in lb.group(0), "ladderB 应对 balanced 显式配色"


def test_desc_tables_declare_summary_not_verbatim(js: str):
    """档位描述表必须自我声明为「摘要」且回落机制存在（review B1，2026-10-18 用户裁决）。

    历史 BUG：注释曾声称「逐字取自题目集 criteria」，实际 21 条中 15 条被缩略（含 4 处可数阈值），
    而守卫测试只在页面自身文本里找子串（同源断言，题目集改了不会红）。
    现已改为：权威全文走 GET /api/hotlist-jev/relay-questions（单一事实源 = QUESTIONS_RELAY），
    页面静态表仅作回落，且注释必须如实声明「摘要」。
    """
    # 注释不得再声称「逐字」
    assert "逐字取自" not in js, "BUG: 摘要表注释不得再声称逐字取自题目集"
    assert "摘要" in js and "非逐字" in js, "注释应如实声明为摘要"
    # 全文走读口，页面引用之（SSOT 链路）
    assert "relay-questions" in js, "页面应从 /relay-questions 拉取 criteria 全文"
    assert "STATE.criteria" in js, "全文应存 STATE.criteria"
    assert "tierDesc(" in js, "KPI 第三行应走 tierDesc（全文优先、摘要回落）"
    assert "critTip(" in js, "判定明细行应有题目全文 tooltip"


def test_relay_questions_route_serves_question_set_criteria():
    """跨源守卫（review B1 的真正 oracle）：读口下发的 criteria 必须逐键等于题目集原文。

    题目集改判据 → 本测试立即红（页面 tooltip/KPI 消费同一读口，无需改测试）。
    零网络零 Mongo：TestClient 进程内，route 只 import 常量（§1.2-7）。
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY

    client = TestClient(app)
    r = client.get("/api/hotlist-jev/relay-questions")
    assert r.status_code == 200, "relay-questions 读口应可用"
    body = r.json()
    assert body.get("ok") is True
    got = body["questions"]
    expected = {qid: spec["criteria"] for qid, spec in QUESTIONS_RELAY.items()
                if spec.get("type") == "choice" and isinstance(spec.get("criteria"), dict)}
    assert got == expected, "读口 criteria 与题目集不一致（SSOT 红线）"
    # 关键阈值必须在全文里（防再次被缩略）
    assert "二板家数 ≤ 三板+的一半" in got["ladder_health"]["fracture"]
    assert "三板+/二板比率 ≥ 1" in got["ladder_health"]["inverted"]
    assert "top3 重合 1-2" in got["theme_pulse"]["rotation"]


def test_band_cuts_match_diagnostic_script(js: str, tmp_path):
    """跨语言 SSOT 守卫（review B3）：前端分带切口必须等于诊断脚本 BANDS/BAND_TXT。

    把页面 bandKeyOf 真实源码抽出在 node 里跑，期望值**从脚本常量推导**（非手打），
    脚本改切口 → 本测试红；页面手改切口 → 同样红。
    死副本 BANDS_DEF/BAND_TXT/bandOfIdx 已删，不得复活。
    """
    from scripts.jev_relay_band_diagnostic import BANDS, BAND_TXT as SCRIPT_BAND_TXT

    # 脚本侧锚定（若脚本改口径，这里先红，提醒同步页面）
    assert BANDS == [(0, 25), (25, 40), (40, 60), (60, 101)]
    assert SCRIPT_BAND_TXT[(60, 101)] == "≥60"

    # 页面侧：不再有第二/第三份副本
    for gone in ("BANDS_DEF", "BAND_TXT", "bandOfIdx"):
        code_refs = [l for l in js.splitlines()
                     if gone in l and not l.strip().startswith("//")]
        assert not code_refs, f"BUG: 副本 {gone} 应保持删除（残留：{code_refs[:2]}）"

    # 行为验证：bandKeyOf 抽源码跑 node，期望值由脚本 BANDS 推导
    if shutil.which("node") is None and not os.environ.get("RELAY_PAGE_GUARD_ALLOW_NO_NODE"):
        pytest.fail("行为守卫需要 node；确认无 node 请显式设 RELAY_PAGE_GUARD_ALLOW_NO_NODE=1")
    m = re.search(r"const bandKeyOf = ([^;]+);", js)
    assert m, "应有 bandKeyOf 定义"
    harness = "\n".join([
        f"const bandKeyOf = {m.group(1)};",
        # 期望表由脚本 BANDS 推导：每带下界归本带、上界-1 归本带、上一带下界归上一带
        "const expect = {};",
        *[f"expect[{lo}] = '{SCRIPT_BAND_TXT[(lo, hi)]}'; expect[{hi - 1}] = '{SCRIPT_BAND_TXT[(lo, hi)]}';"
          for lo, hi in BANDS],
        "expect[null] = null; expect[NaN] = null;",
        "const out = {};",
        "for (const k of Object.keys(expect)) out[k] = bandKeyOf(k === 'null' ? null : Number(k));",
        "console.log(JSON.stringify(out));",
    ])
    script = tmp_path / "band_probe.js"
    script.write_text(harness, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    for lo, hi in BANDS:
        name = SCRIPT_BAND_TXT[(lo, hi)]
        assert got[str(lo)] == name and got[str(hi - 1)] == name, \
            f"页面 bandKeyOf 与脚本切口不一致：{name} 边界 [{lo},{hi}) → {got}"
    assert got["null"] is None and got["NaN"] is None, "空值应归 null（fail-visible，不伪装缺失）"


def test_leader_bands_single_source_and_anchored(js: str):
    """龙头强度切口单表化（review B2）：leaderDesc 只查表，切点⊆SCORE_ANCHORS_10。"""
    ld = _fn(js, "leaderDesc")
    assert "LEADER_BANDS.find" in ld, "BUG: leaderDesc 应只查 LEADER_BANDS 表"
    # 不再另写一份 if 切口链
    assert not re.search(r"if \(v >= \d+\) return", ld), "BUG: leaderDesc 不得再内联阈值"
    # 切点必须取自题目集锚点序（jev_state.SCORE_ANCHORS_10，字符串元素）
    from backend.analysis.hotlist.jev_state import SCORE_ANCHORS_10
    bands = re.findall(r"\['(\d+)-(\d+)", _const(js, "LEADER_BANDS"))
    cuts = {int(lo) for lo, _ in bands}
    assert cuts <= {int(a) for a in SCORE_ANCHORS_10}, \
        f"切点 {cuts} 必须都是题目集锚点 {SCORE_ANCHORS_10}"
    assert "0-11" in _const(js, "LEADER_BANDS") and "78-100" in _const(js, "LEADER_BANDS")


def test_preset_buttons_highlight_and_toggle_back(html: str, js: str):
    """预设段高亮 + 再点恢复上次区间（2026-10-18 用户需求）。"""
    bar = _fn(js, "rRangeBar")
    # 按钮带 on 类与 data-preset，供高亮/回写
    assert 'data-preset="${kind}"' in bar, "预设按钮应带 data-preset"
    assert "presetOn(kind) ? 'on'" in bar, "预设按钮应挂 on 高亮类"
    assert "#rangeBarHost button.on" in html, "应有按钮高亮样式"

    # 高亮以「区间等价」判定（单一事实源，不靠死标志位）
    assert "function activePreset()" in js
    assert "sameRange(rg, presetRange(k))" in js, "高亮应由区间等价推出"
    assert "function presetRange(kind)" in js, "预设区间应与 rPreset 同式重算"

    # 再点恢复：存回退点，再点取回
    pre = _fn(js, "rPreset")
    assert "presetOn(kind)" in pre, "rPreset 应判断当前是否已亮"
    assert "STATE.relayBack = rg ?" in pre, "点新预设前应存回退点"

    # 手改日期 → 预设取消高亮，但回退点保留（再点能回手改区间）
    rr = _fn(js, "rRange")
    assert "STATE.relayPreset = null" in rr, "手改日期应取消预设高亮"
    assert "STATE.relayBack" not in rr, "手改日期不应清掉回退点"

    # 焦点守卫不得让按钮亮态变脏（日期框持焦时按钮类要同步）
    mount = _fn(js, "winMount")
    assert "classList.toggle('on', presetOn(" in mount, \
        "日期框持焦时也应同步预设按钮高亮"


def test_preset_toggle_actually_restores_previous_range(js: str, tmp_path):
    """**行为**回归（不是字样检查）：抽出 presetRange/sameRange/activePreset/rPreset
    的真实源码，在 Node 里跑一遍四步序列，断言「再点→回上次区间」。

    2026-10-18 实证：把 rPreset 的撤销分支改成回「全部」时，纯字样断言检不出，
    这段真实执行能立即暴露（变异测试已验证）。
    """
    if shutil.which("node") is None:  # 无 node 环境则跳过（不阻断其它用例）
        pytest.skip("node 不可用")

    # 把相关函数与常量拼成一段可执行脚本（STATE 用最小桩，不涉 DOM/网络）
    src = "\n".join([
        _fn(js, "ymdLocal"),
        _fn(js, "presetRange"),
        _const(js, "sameRange"),
        _fn(js, "activePreset"),
        _fn(js, "defaultRange"),
        _const(js, "presetOn"),
        _fn(js, "rPreset"),
        "const STATE = { series: [] };",
        "let renderRelayTab = () => {}, renderCharts = () => {};",
        "let rangeRefresh = () => {};",
        "STATE.series = [{ tradingDate: '2026-10-16' }];",
        "STATE.relayRange = null; STATE.relayBack = null; STATE.relayPreset = null;",
    ])
    harness = "\n".join([
        src,
        "const out = [];",
        # ① 默认近1月
        "STATE.relayRange = defaultRange(); out.push(activePreset());",
        # ② 点近3月 → 亮近3月
        "rPreset('m3'); out.push(activePreset());",
        # ③ 再点近3月（已亮）→ 回退到①的近1月
        "rPreset('m3'); out.push(activePreset());",
        # ④ 点全部 → 亮；再点点全部 → 回退到①的近1月（不跳空）
        "rPreset('all'); rPreset('all'); out.push(activePreset());",
        # ⑤ 再点近1月（已亮且无回退点）→ 稳定在近1月，不得变成两态开关
        "rPreset('m1'); rPreset('m1'); out.push(activePreset()); out.push(JSON.stringify(STATE.relayRange));",
        # ⑥ 手改日期 → 三个按钮全不亮
        "STATE.relayRange = { start: '2026-09-01', end: null }; out.push(activePreset());",
        # ⑦ 手改后点近1月 → 亮近1月；再点 → 回手改区间（不亮）
        "rPreset('m1'); rPreset('m1'); out.push(activePreset()); out.push(STATE.relayRange.start);",
        "console.log(JSON.stringify(out));",
    ])
    script = tmp_path / "preset_probe.js"
    script.write_text(harness, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got == ["m1", "m3", "m1", "m1", "m1", '{"start":"2026-09-17","end":null}', None, None, "2026-09-01"], (
        f"预设高亮/再点回退行为不符：{got}\n"
        "期望：默认近1月 → 点近3月亮 → 再点回近1月 → 全亮再点回近1月 → "
        "近1月再点保持稳定 → 手改不亮 → 手改后点近1月亮、再点回手改区间")


def test_kpi_date_only_on_first_card(js: str):
    """2026-10-18 用户需求：日期只在一张卡上大字显示，其余卡不得重复。

    回归点：以前每张卡的标题旁都带一遍「行选 10-15」，纯噪声。
    """
    kpi = _fn(js, "renderRelayKpi")
    # 日期大字元素只有一处
    assert kpi.count('class="kpi-day"') == 1, "大字日期应只出现一次（首卡）"
    # 共用卡工厂（其余 5 张）不再拼 scope
    card_line = [l for l in kpi.splitlines() if "const card =" in l][0]
    assert "${scope}" not in card_line, "BUG: 其余卡仍在重复拼日期标记"
    # 首卡仍标出来源（行选/最新），fail-visible
    assert "行选" in kpi and "最新" in kpi
    assert "kpi-src-tag" in kpi, "来源应用小标签展示而非逐卡重复"
    # 非首卡的标题不得内嵌 scope
    for k in ("接力相位", "边际方向", "梯队结构", "接力钱效", "题材脉络", "龙头强度", "分区定位"):
        assert f"{k}${{scope}}" not in kpi, f"{k} 卡不应再重复日期标记"


def test_topbar_has_refresh_but_no_realtime(html: str):
    """2026-10-18 用户裁决：恢复顶栏【刷新】，删除右上角【实时】。"""
    top = html[html.index('class="topbar"'):]
    top = top[: top.index("</header>")]
    assert ">刷新<" in top, "顶栏应有【刷新】按钮"
    assert "loadAll()" in top, "【刷新】应触发 loadAll"
    assert ">实时<" not in top, "BUG: 右上角【实时】按钮应已删除"
    assert "primary" not in top, "顶栏不应再有 primary 按钮"


def test_range_is_global_across_relay_subpages(js: str):
    """2026-10-18 用户需求：日期区间是全局筛选条件，四个子页联动。

    机制保证：rRange/rPreset → rangeRefresh() → 4 个子页 render；子页都吃
    bandAgg → winBandDays → rangedSeries（同一把尺子）。
    """
    for fn in ("rRange", "rPreset"):
        assert "rangeRefresh()" in _fn(js, fn), f"{fn} 必须触发全局刷新"

    rr = _fn(js, "rangeRefresh")
    for view in ("renderRelayTab", "renderCharts", "renderRelayAnalysis"):
        assert view + "()" in rr, f"rangeRefresh 应重绘 {view}"

    # 4 个子页都从同一个聚合入口取数（不得各自算一套区间）
    ra = _fn(js, "renderRelayAnalysis")
    assert "bandAgg()" in ra, "子页应统一走 bandAgg"
    for panel in ("renderPhasePanel", "renderPhaseMatrix", "renderMoneyPanel",
                  "renderZoneHits", "renderDiagPanel"):
        assert panel + "(agg)" in ra, f"{panel} 应用同一聚合"
    # bandAgg 默认行源即区间行源（无人传参时同样联动）
    assert "winBandDays()" in _fn(js, "bandAgg"), "bandAgg 默认应取区间行"
    assert "rangedSeries()" in _fn(js, "winBandDays"), "区间行应与判定明细同源"

    # 不得再有重复定义（旧的无参 renderRelayAnalysis 会与新版抢渲染）
    assert js.count("function renderRelayAnalysis()") == 1, "renderRelayAnalysis 应只定义一次"


def test_kpi_scope_falls_back_when_day_missing(js: str):
    """所选日无存档时回落区间最新一日并标注（fail-visible，不置空）。"""
    kpi = _fn(js, "renderRelayKpi")
    assert "fallback" in kpi and "最新" in kpi


# ── 相位分线页（2026-10-18 用户需求）────────────────────────────────────────
def test_phase_chart_has_hover_tooltip(js: str):
    """指数分区折线图加 tooltip（悬停卡片 + 十字线），不靠原生 <title>。"""
    dc = _fn(js, "drawRelayChart")
    assert 'class="ch-wrap"' in dc, "图表应包在定位容器内（tooltip 绝对定位）"
    assert 'class="ch-tip"' in dc, "应有 tooltip 卡片元素"
    assert 'class="ch-hit"' in dc and "ch-cursor" in dc and "ch-focus" in dc, \
        "应有命中层 + 十字线 + 焦点圈"
    # 命中层必须真的裱进 SVG（否则循环里拼了但不渲染）
    assert 'class="ch-hits">${hits}</g>' in dc, "命中层应拼入 SVG"
    assert "wireChartTip(id)" in dc, "应绑定悬停交互"
    # 数据缝在 data-* 上（9 个当日档位字段，顺序与 LBL 对齐）
    assert 'data-d="' in dc and "data-x=" in dc
    for k in ("PHASE_CN[r.relayPhase]", "MOM_CN[r.relayMomentum]", "LADDER_CN[r.ladderHealth]",
              "MONEY_CN[r.moneyEffect]", "THEME_CN[r.themePulse]", "z.label"):
        assert k in dc, f"tooltip 数据应含 {k}"

    wt = _fn(js, "wireChartTip")
    assert "mouseenter" in wt and "mouseleave" in wt, "应绑定 mouseenter/mouseleave"
    assert "getBoundingClientRect" in wt, "应做 SVG→像素换算（viewBox 缩放）"
    assert "offsetWidth" in wt, "应防 tooltip 溢出右边界"


def test_phase_chart_tooltip_css_present(html: str):
    """tooltip 样式必须存在（否则悬停卡不可见）。"""
    assert ".ch-wrap{position:relative}" in html
    assert ".ch-tip{display:none;position:absolute" in html
    assert ".ch-tip-d{" in html and ".ch-tip-r{" in html


def test_phase_segment_detail_table_removed(js: str):
    """删除「相位分段明细」表；相位统计表保留。"""
    rp = _fn(js, "renderPhasePanel")
    # 只看代码（去掉注释行），避免注释里提到表名造成误报
    code = "\n".join(l for l in rp.splitlines() if not l.strip().startswith("//"))
    assert "相位分段明细" not in code, "BUG: 相位分段明细表应已删除"
    assert "segBody" not in code, "分段明细的行构造应一并删除"
    assert "<th>区间</th>" not in code, "分段明细表头应已删除"
    assert "段内次日溢价A" not in code, "分段明细列应已删除"
    # 相位统计表（当日相位 → 次日变化）保留
    assert "相位统计（当日相位 → 次日变化）" in code, "相位统计表应保留"
    # 分布图保留；且 #phaseSegs 的输出不得再含任何表格（分段明细已删）
    assert "dist-wrap" in code and code.count("barChart(") >= 2, "相位/钱效分布图应保留"
    seg_assign = code[code.index("el.innerHTML"):]
    seg_assign = seg_assign[: seg_assign.index("const st = {}")]
    assert "<table" not in seg_assign, "BUG: #phaseSegs 不应再渲染任何表格（分段明细已删）"
    assert seg_assign.count("dist-card") == 2, "应只留两张分布图卡"


# ── 分带观察合并页（2026-10-18 用户裁决：钱效分带 + 毒带观察 + 分带实测 三合一）──
def test_relay_views_merged_to_three(js: str):
    """连板指数只剩 3 个子页：相位分线 / 分带观察 / 判定明细。"""
    rv = _const(js, "RELAY_VIEWS")
    assert "'phase'" in rv and "'bands'" in rv and "'detail'" in rv
    for gone in ("'money'", "'toxic'"):
        assert gone not in rv, f"BUG: 子页 {gone} 应已合并进分带观察"
    assert "分带观察" in rv, "合并页名应为「分带观察」"


def test_merged_page_holds_all_three_sections(html: str):
    """三个原页面内容必须全部落在同一个 rv-bands 容器内（不得丢块）。"""
    assert 'id="rv-money"' not in html, "BUG: 钱效分带页容器应已删除"
    assert 'id="rv-toxic"' not in html, "BUG: 毒带观察页容器应已删除"
    seg = html[html.index('id="rv-bands"'):]
    seg = seg[: seg.index("<!-- ⑤") if "<!-- ⑤" in seg else seg.index('id="rv-detail"')]
    # 三大区块的标题与全部子挂载点
    for t in ("钱效分带", "40-60 毒带 · 冰点 · 绿灯"):
        assert t in seg, f"合并页应含区块「{t}」"
    for el in ("moneyRibbon", "moneyStats", "moneyDiag", "moneyHint",
               "hitChips", "hitTable", "hitHint",
               "diagBands", "diagZones", "diagCorr",
               "diagWarn", "phaseMatrix"):
        assert f'id="{el}"' in seg, f"合并页应含挂载点 #{el}"


def test_merged_page_render_functions_unchanged(js: str):
    """合并只改归属与标题，三个渲染函数必须都还在（且仍被统一调用）。"""
    for fn in ("renderMoneyPanel", "renderZoneHits", "renderDiagPanel", "renderPhaseMatrix"):
        assert f"function {fn}(" in js, f"渲染函数 {fn} 应保留"
    ra = _fn(js, "renderRelayAnalysis")
    for fn in ("renderMoneyPanel(agg)", "renderZoneHits(agg)", "renderDiagPanel(agg)",
               "renderPhaseMatrix(agg)"):
        assert fn in ra, f"合并页应统一调用 {fn}"


def test_merged_page_section_headers(html: str):
    """合并页内各区块用 .sec-h 做分级标题（否则三段无分隔）。"""
    seg = html[html.index('id="rv-bands"'):]
    seg = seg[: seg.index('id="rv-detail"')]
    assert seg.count('class="sec-h"') >= 2, "应有钱效分带 / 毒带观察两个区块标题"
    assert ".sec-h{" in html, "应有 .sec-h 样式"
    assert seg.count('class="card"') >= 4, "三个区块 + 交叉表应各自独立成卡"


# ── 批次3（review B6）：前端状态错误哨兵与焦点清理 ────────────────────────

def test_relay_doc_fetch_distinguishes_failure_from_empty(js: str):
    """懒拉失败必须与「服务端确认无档」可区分，且失败可重试（review B6，AGENTS §4.0）。

    旧实现 `relayDocs[key] = null` 同时承担「占位」「已拉无档」「拉取失败」三种语义，
    catch 里也写 null —— 失败与空结果同形，且 `!== undefined` 判定让该日永不重试，
    读者看到的是静默回落的瘦行（无法得知完整存档其实没拉回来）。
    """
    fetch = _fn(js, "relayDocFetch")
    # 失败写独立哨兵，不再与 null(无档) 合流
    assert "__err" in fetch, "失败必须写 {__err:true} 哨兵，不得与 null 同形"
    assert "{ __err: true }" in fetch or "{__err:true}" in fetch.replace(" ", "")
    # 占位态不得复用 null
    assert re.search(r"relayDocs\[key\]\s*=\s*null", fetch) is None, \
        "占位不得再写 null（会与已拉无档混淆）"
    # 失败可重试：入口按「已拉完（非 err）」才短路
    assert "relayDocIsErr" in fetch, "重试判定应走 relayDocIsErr"
    # 入口必须真的被 relayToggle 调用（否则哨兵写好也没人重拉）
    assert "relayDocFetch(" in _fn(js, "relayToggle")
    # 错误可见：detailHtml 显式渲染失败 + 重试按钮，不静默回落瘦行
    dh = _fn(js, "detailHtml")
    assert "docErr" in dh and "拉取失败" in dh and "重试拉取" in dh
    # relayEntryOf 透出错误标志
    assert "docErr" in _fn(js, "relayEntryOf")


def test_jump_date_clears_relay_focus(js: str):
    """换日必须清选中态（review B6）：否则 KPI 仍联动到一个不在当前区间/已过期的前一日行。"""
    jd = _fn(js, "jumpDate")
    assert "STATE.relayFocus = null" in jd, "jumpDate 应清 STATE.relayFocus"
    assert "loadAll()" in jd


def test_band_have_matches_diagnostic_script(js: str):
    """页面 bandAgg 的 have 口径须与诊断脚本同式（review P2-1）。

    旧版页面 `o.premA != null`（仅 premA），脚本 `premA is not None or promo is not None`（或）；
    同一张卡里「有次日实测 N 日」（产物 evaluated）与「可实测 N 日」（页面重算）会不一致，
    且注释谎称「口径与 measurable 同」。
    """
    agg = _fn(js, "bandAgg")
    assert re.search(r"premA\s*!=\s*null\s*\|\|\s*o?\.?promo\s*!=\s*null", agg), \
        "bandAgg 的 have 应为 premA 或 promo（与脚本同式）"


def test_load_all_flags_ok_false_degradation(js: str):
    """HTTP200+ok:false 必须亮红，不得当空序列静默展示（review P2-3，§4.0）。"""
    la = _fn(js, "loadAll")
    assert "ok === false" in la, "loadAll 应检查 series.ok === false"
    assert "读库降级" in la or "bad" in la


def test_relay_doc_fetch_treats_ok_false_as_error(js: str):
    """懒拉的 HTTP200+ok:false 也要走失败哨兵（可重试），不得显示为「确认无档」（review P2-3）。"""
    fetch = _fn(js, "relayDocFetch")
    assert "ok === false" in fetch, "relayDocFetch 应把 ok:false 视为失败"
    assert "__err" in fetch


# ── 2026-10-18 分区术语收敛（review：同页两套分区撞名）────────────────────
# 页面并存两套**不同**分区：
#   ZONE_DEF  = 判定分区（判定明细分区列 / 表头筛选 / KPI / 毒带清单）
#   ZONES_DEF = 五区赔率分区（分带观察的赔率表，切口与脚本 ZONE_* 逐字同源）
# 两套切口不同（40-60∧T 叠加 vs 25-55/55-60），却共用「中性/绿灯/毒带」等词，
# 用户看到筛选枚举「中性 40-60」而在赔率表里找不到对应行。守卫：label 集合不得相交。

def _zone_def_labels(js: str) -> set[str]:
    body = _const_block(js, "ZONE_DEF")
    return {m for m in re.findall(r"label:'([^']+)'", body)}


def _zones_def_labels(js: str) -> set[str]:
    block = js[js.index("const ZONES_DEF = ["):]
    block = block[:block.index("];")]
    return set(re.findall(r"\['([^']+)'", block))


def test_zone_systems_use_disjoint_labels(js: str):
    """判定分区（ZONE_DEF）与赔率分区（ZONES_DEF）的 label 必须不相交（防术语撞车）。"""
    a, b = _zone_def_labels(js), _zones_def_labels(js)
    assert a, "ZONE_DEF 应有 label"
    assert b, "ZONES_DEF 应有 label"
    overlap = a & b
    assert not overlap, f"两套分区 label 撞车：{sorted(overlap)}"
    # 具体回归：判定分区不得再叫裸「中性 40-60」（与赔率表的 25-55 覆盖重叠区间却同名）
    assert "中性 40-60" not in a, "判定分区 label 应是带限定的『中性带 40-60』"


def test_zone_systems_are_labeled_as_different_partitions(js: str):
    """UI 必须显式声明两套分区不是同一套切口（否则读者会互相找对应行）。"""
    assert "判定分区" in js, "应标注判定分区"
    assert "赔率分区" in js, "应标注赔率分区"
    # 赔率表表头/周边须点明与判定分区不同源
    assert re.search(r"赔率分区[^<]{0,40}(非|≠|不同)", js) or "判据分区（非赔率分区）" in js, \
        "应说明两套分区的关系"


def test_zone_def_cuts_unchanged_by_rename(js: str):
    """改名不得改切口（回归）：判定分区边界仍是 60 / 40∧T56 / 40 / 25。"""
    zo = _fn(js, "zoneOf")
    for cut in ("idx >= 60", "idx < 25", "idx >= 40 && t != null && t >= 56", "idx >= 40"):
        assert cut in zo, f"zoneOf 切口漂移：缺 {cut}"


def test_zones_def_still_matches_script_zone_cuts(js: str):
    """赔率分区切口须仍与脚本 ZONE_* 逐字同源（改名不得动切口）。"""
    from scripts.jev_relay_band_diagnostic import (ZONE_AVOID, ZONE_GREEN, ZONE_MID,
                                                   ZONE_RED, ZONE_SEMI)
    labels = _zones_def_labels(js)
    for name, _ in (ZONE_GREEN, ZONE_SEMI, ZONE_MID, ZONE_AVOID, ZONE_RED):
        assert name in labels, f"ZONES_DEF 缺脚本切口 {name}"


def test_band_panel_labels_sample_scope_as_within_range(js: str):
    """分带观察的 n 必须标注「区间内」（否则与产物全窗口 n 直接对比会误判为数字错）。

    守点必须钉在**五区/赔率表自身**的渲染处（区间内重算 n + 与全窗口产物不可比的声明），
    不能靠同函数里其它文案（如「区间内天数」）假绿。
    """
    rdp = _fn(js, "renderDiagPanel")
    # 1) 五区表前必须有区间内 n 的口径声明
    assert re.search(r"区间内重算：\$\{agg\.have\.length\}", rdp), \
        "五区表应显式给出区间内可实测日数"
    # 2) 必须声明与离线产物（全窗口）不可直接比较
    assert "不可直接比较" in rdp or "不可比" in rdp, "应声明与离线产物 n 不可比"
    assert "全窗口" in rdp, "应点明产物是全窗口口径"


# ── v6（2026-10-19）：板块与龙头子视图（预注册 jev-relay-sector-leader-preregistration.md）─
def test_leaders_view_wired_as_own_subview(html: str, js: str):
    """新增「板块与龙头」为独立子视图（≤ 2 卡），且在 renderRelayTab 周期内渲染。"""
    assert "['leaders', '板块与龙头'" in _const(js, "RELAY_VIEWS"), "RELAY_VIEWS 缺 leaders 子视图"
    seg = html[html.index('id="rv-leaders"'):]
    seg = seg[: seg.index('id="rv-detail"')]
    assert seg.count('<div class="card"') == 2, "该子页应守「每页 ≤2 卡」规则"
    assert 'id="sectorChain"' in seg and 'id="leaderStruct"' in seg, "两卡挂载点缺失"
    assert "renderLeaders()" in _fn(js, "renderRelayTab"), "子视图须在 renderRelayTab 周期内渲染"


def test_leaders_single_source_and_old_gen_fail_visible(js: str):
    """龙头/板块卡只读存档 relayStructure（与叙事同源）；旧代无字段必须显式可见。"""
    rl = _fn(js, "renderLeaders")
    assert "relayStructure" in rl, "必须读存档 relayStructure，禁止前端重算"
    assert "旧代" in rl and "字段缺失" in rl, "旧代文档无 relayStructure 应显式标注"
    # 不得用 '-' / 空串佯装缺失（AGENTS §4.0）
    assert "未采集" in rl, "应写明未采集而非静默置空"
    assert "relayDocFetch" in rl, "选中行未预入缓存时应懒拉且可重试"
    assert "relayDocIsErr" in rl, "拉取失败与确实无档必须可区分"


def test_leaders_constants_are_single_source_with_backend(js: str):
    """前端泛板块/依据文案/状态文案必须与后端同源（防口径漂移）。

    2026-10-19 review P2：原守卫只比「键集」，文案值改了仍会绿；且 STATUS_CN 完全未守卫。
    """
    from backend.operations.jev_relay_index import (_PSEUDO_BOARDS, _SECTOR_BASIS_CN,
                                                   _STATUS_CN)

    decl = _const(js, "PSEUDO_BOARDS")
    names = set(re.findall(r"'([^']+)'", decl[decl.index("["): decl.index("]")]))
    assert names == set(_PSEUDO_BOARDS), f"泛板块集合与后端不同源：{names} vs {set(_PSEUDO_BOARDS)}"

    block = _const_block(js, "SECTOR_BASIS_CN")
    keys = set(re.findall(r"^\s*(\w+):", block, re.M))
    assert keys == set(_SECTOR_BASIS_CN), \
        f"主线依据键集不同源：{keys} vs {set(_SECTOR_BASIS_CN)}"
    for k, v in _SECTOR_BASIS_CN.items():
        assert f"{k}: '{v}'" in block, f"主线依据文案不同源：{k} → {v}"

    sblock = _const_block(js, "STATUS_CN")
    for k, v in _STATUS_CN.items():
        assert f"{k}: '{v}'" in sblock, f"更替状态文案不同源：{k} → {v}"


def test_leaders_chain_uncomputable_not_rendered_as_zero(js: str):
    """段A 链不可算时必须渲染「不可算」而非 0（§4.0 伪 0，前端口径与后端同规）。"""
    rl = _fn(js, "renderLeaders")
    assert "chain.ok" in rl and "chainReason" in rl, "前端必须读 chain.ok/reason"
    assert "不可算" in rl, "不可算路径必须显式可见"
    assert "历史不足" in rl, "d2/d1 缺失时列头不得回落裸键 d2/d1"


def test_leaders_render_executes_uncomputable_chain(tmp_path, js: str):
    """真执行 renderLeaders（node 探针）：链不可算不得渲染 0、sameStock=null 不得误判。

    2026-10-19 review P1 前端侧锁：静态字符串断言看不出「0 只 vs 0只」这类差异，此处真跑一次。
    """
    src = "\n".join([
        _const_block(js, "SECTOR_BASIS_CN"),
        _const(js, "PSEUDO_BOARDS"),
        _const_block(js, "STATUS_CN"),
        _const(js, "rangeTextOf"),
        _const(js, "streakText"),
        "const esc = v => v == null ? '' : String(v);",
        _fn(js, "relayDocIsErr"),
        _fn(js, "leadersKey"),
        _fn(js, "renderLeaders"),
        "const host = {};",
        "const $ = id => (host[id] = host[id] || { innerHTML: '', textContent: '' });",
        "globalThis.STATE = { relayFocus: null, series: [],",
        "  day: { tradingDate: '2026-09-30', relayIndex: 50 },",
        "  relayDocs: { '2026-09-30': { tradingDate: '2026-09-30', questionSetVersion: 'v6',",
        "    relayStructure: { dates: { d2: '2026-09-28', d1: '2026-09-29', d0: '2026-09-30' },",
        "      chain: { ok: false, reason: '2026-09-28/2026-09-29 \u97ed\u7814 final \u7f3a\u5931' },",
        "      sectors: [{ name: '\u7532\u677f\u5757', d2: null, d1: null,",
        "        d0: { count: 2, maxBoardText: '4\u59294\u677f' }, survivors: null, survivorNames: [],",
        "        promoted: null, top3Streak: 0,",
        "        dragon: { role: '\u9f99\u4e00', code: '600101', name: '\u7532A', boards: 4, days: 4, streak: 4, time: '09:30' } }],",
        "      mainline: { name: '\u7532\u677f\u5757', basis: 'chain_na', survivors: null, holdings: [],",
        "        d0Count: 2, d0MaxBoardText: '4\u59294\u677f', pseudoExcluded: null },",
        "      totalLeader: { code: '600101', name: '\u7532A', rangeText: '4\u59294\u677f', streak: 4,",
        "        sector: '\u7532\u677f\u5757', time: '09:30', pull: 2, rank: null },",
        "      sentimentLeader: null, sameStock: null, leaderIsMainlineDragon: null,",
        "      genesis: { firstBoardDate: '2026-09-28', tradingDaysAgo: 1, breaks: 0, streak: 4,"
        " degraded: '韭研区间 4天4板 的首板日 09-28 早于韭研池史起点（2026-05-06 起），无法校验' },",
        "      succession: null, degraded: [] } } },",
        "};",
        "globalThis.rangedSeries = () => [];",
        "globalThis.relayDocFetch = () => {};",
        "renderLeaders();",
        "const a = $('sectorChain').innerHTML, b = $('leaderStruct').innerHTML;",
        "const h = $('sectorChainHint').textContent;",
        "if (/0\u53ea/.test(a)) throw new Error('\u4f2a 0 \u6cc4\u9732: ' + a);",
        "if (!a.includes('\u4e0d\u53ef\u7b97\uff08')) throw new Error('\u5b58\u6d3b/\u664b\u7ea7 \u672a\u4e0d\u53ef\u7b97: ' + a);",
        "if (!a.includes('\u97ed\u7814 final \u7f3a\u5931')) throw new Error('\u4e0d\u53ef\u7b97\u672a\u5e26\u539f\u56e0: ' + a);",
        "if (!h.includes('\u4e09\u65e5\u94fe\u4e0d\u53ef\u7b97')) throw new Error('\u4f9d\u636e\u672a\u62ab\u9732: ' + h);",
        "if (!b.includes('\u4e0d\u53ef\u5224')) throw new Error('sameStock=null \u672a\u515c\u4f4f: ' + b);",
        "if (!b.includes('\u9996\u677f 09-28\uff081 \u4e2a\u4ea4\u6613\u65e5\u524d\uff09')) throw new Error('\u8bde\u751f\u8f68\u8ff9\u6587\u6848: ' + b);",
        # §14.6：首板日可算但不可核 → 理由必须同排展示（旧实现只在「不可算」分支显示，静默丢因）
        "if (!b.includes('早于韭研池史起点')) throw new Error('不可核理由未展示: ' + b);",
        "console.log('OK');",
    ])
    script = tmp_path / "leaders_render_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"渲染探针失败：{cp.stderr}\n{cp.stdout}"
    assert cp.stdout.strip() == "OK"


def test_leaders_helper_behaviour(tmp_path, js: str):
    """区间文案/真连板文案纯函数：不可验不得回落区间板数。"""
    src = "\n".join([
        _const(js, "rangeTextOf"),
        _const(js, "streakText"),
        "console.log(JSON.stringify([",
        "  rangeTextOf(null, null), rangeTextOf(1, 1), rangeTextOf(4, 4),",
        "  rangeTextOf(8, 16), rangeTextOf(3, null),",
        "  streakText(4), streakText(null), streakText(undefined),",
        "]));",
    ])
    script = tmp_path / "leaders_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got == ["首板", "首板", "4天4板", "16天8板", "3板", 4, "不可算", "不可算"], \
        f"文案派生不符：{got}"


# ── 2026-10-19：判定明细详情卡【重跑】按钮（单日复跑，网络抖动恢复）──────────
def test_relay_rerun_button_in_relay_detail_head(js: str):
    """【重跑】置于【详细信息】左侧；仅 relay 日级卡提供；进行中禁用（成本护栏）。"""
    dh = _fn(js, "detailHtml")
    assert "重跑" in dh and "relayRerun(" in dh, "判定明细详情卡应有【重跑】按钮"
    assert "view === 'relay'" in dh, "重跑仅 relay 日级卡提供（单日=连板指数日判定）"
    assert dh.index("${rerunBtn}<button") < dh.index(">详细信息</button>"), \
        "重跑按钮必须在【详细信息】左侧"
    assert "disabled" in dh and "STATE.rerunBusy" in dh, "重跑进行中应禁用（防并发重复计费）"


def test_relay_rerun_flow_and_endpoint(js: str, html: str):
    """重跑：二次确认 → POST 复跑写口（force）→ 丢弃旧档 → 刷新序列 + 重拉当日档。"""
    rr = _fn(js, "relayRerun")
    assert "window.confirm" in rr, "真实模型调用须二次确认"
    assert "/api/hotlist-jev/relay-index/rerun" in rr, "应 POST 单日复跑写口"
    assert "force" in rr, "应默认 force 重判"
    assert "if (STATE.rerunBusy) return" in rr, "并发护栏：同时只允许一次重跑"
    assert "delete STATE.relayDocs[key]" in rr, "旧 degraded 存档须丢弃重拉"
    assert "loadAll()" in rr and "relayDocFetch(" in rr, "重跑后刷新序列与当日完整存档"
    # 结果落卡片内 banner（fail-visible，不弹阻断式 alert）
    dh = _fn(js, "detailHtml")
    assert "rerunMsg" in rr and "rerunMsg" in dh
    assert "rerunMsg.key === e.key" in dh, "重跑结果按 entry 显示在详情卡内"
    assert "async function jpost(" in js and "jpost(" in rr, "应有 jpost 助手"
    assert ".lg-toggle button.rerun" in html, "重跑按钮样式缺失"


def test_relay_page_post_proxy_supports_rerun():
    """页面 :8008 必须能透传 POST（否则重跑按钮 405）；超时须覆盖退避重试预算。

    2026-10-19 评审 F7：旧值 180s < 退避预算最坏 ≈5×60+52≈352s，会先截断导致
    「页面报失败而 :8000 实际仍在跑并可能写库成功」→ 用户重试白烧第二次真实模型调用。
    """
    import re as _re
    from backend.services.jev.jev_client import JEV_RETRY_DELAYS

    src = (_PAGE.parents[1] / "serve_relay_page.py").read_text(encoding="utf-8")
    assert '@app.post("/api/hotlist-jev/{rest:path}")' in src, "缺 POST 透传路由"
    assert "proxy_post" in src
    m = _re.search(r"_POST_PROXY_TIMEOUT_SECONDS\s*=\s*(\d+)", src)
    assert m, "缺 _POST_PROXY_TIMEOUT_SECONDS（POST 透传须显式超时，不用默认 20s/180s 魔数）"
    worst = (len(JEV_RETRY_DELAYS) + 1) * 60 + sum(JEV_RETRY_DELAYS)   # 5 次尝试×60s 读超时 + 退避
    assert int(m.group(1)) >= worst, \
        f"透传超时 {m.group(1)}s 须≥退避预算 {worst}s（否则截断→用户重试→白烧第二次模型调用）"


def test_relay_rerun_executes_post_and_refresh(js: str, tmp_path):
    """**行为**回归（node 探针）：真跑 relayRerun，断言请求体/刷新链/旧档丢弃/取消路径。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        _fn(js, "relayRerun"),
        "globalThis.window = { confirm: () => true };",
        "const STATE = { rerunBusy: null, rerunMsg: null,",
        "  relayDocs: { '2026-10-19': { tradingDate: '2026-10-19', status: 'degraded' } } };",
        "const calls = [];",
        "const renderRelayTab = () => calls.push(['render']);",
        "const jpost = (path, body) => { calls.push(['post', path, body]);",
        "  return Promise.resolve({ ok: true, relayIndex: 40.7, relayPhase: 'bottoming' }); };",
        "const loadAll = () => { calls.push(['loadAll']); return Promise.resolve(); };",
        "const relayDocFetch = k => calls.push(['fetch', k]);",
        "(async () => {",
        "  relayRerun('2026-10-19');",
        "  await new Promise(r => setTimeout(r, 10));",
        "  window.confirm = () => false;",
        "  relayRerun('2026-10-18');",   # 取消：不得再发请求
        "  console.log(JSON.stringify({ calls, busy: STATE.rerunBusy,",
        "    msg: STATE.rerunMsg, docs: Object.keys(STATE.relayDocs) }));",
        "})();",
    ])
    script = tmp_path / "rerun_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    posts = [c for c in got["calls"] if c[0] == "post"]
    assert len(posts) == 1, f"取消后不得再发请求：{got['calls']}"
    assert posts[0][1] == "/api/hotlist-jev/relay-index/rerun"
    assert posts[0][2] == {"date": "2026-10-19", "force": True}
    assert any(c[:1] == ["loadAll"] for c in got["calls"]), "成功后应刷新序列"
    assert ["fetch", "2026-10-19"] in got["calls"], "应重拉当日完整存档"
    assert got["busy"] is None, "完成后应清进行中状态"
    assert got["msg"]["ok"] is True and got["msg"]["key"] == "2026-10-19"
    assert "2026-10-19" not in got["docs"], "旧存档应被丢弃（触发重拉）"


# ── 2026-10-19：当日逐槽详情卡【重跑】按钮（单槽复跑，网络抖动恢复）──────────
def test_slot_rerun_button_in_slot_detail_head(js: str):
    """slot 帧级卡与 EOD 日级卡都有【重跑】，同样位于【详细信息】左侧。"""
    dh = _fn(js, "detailHtml")
    assert "slotRerun(" in dh, "槽位详情卡应有【重跑】按钮"
    assert "view === 'slot'" in dh and "e.kind === 'slot'" in dh, "帧级 slot 卡可复跑"
    assert "e.kind === 'eod'" in dh and "eodRerun(" in dh, "EOD 日级卡也应可复跑"
    assert dh.index("${rerunBtn}<button") < dh.index(">详细信息</button>"), \
        "重跑按钮必须在【详细信息】左侧"
    assert "STATE.rerunBusy" in dh and "disabled" in dh


def test_slot_rerun_flow_and_endpoint(js: str):
    """单槽复跑：确认 → POST /slots/rerun（带 tradingDate/slotTime/snapshotType/datasetId）→ loadAll。"""
    sr = _fn(js, "slotRerun")
    assert "window.confirm" in sr, "真实模型调用须二次确认"
    assert "/api/hotlist-jev/slots/rerun" in sr, "应 POST 单槽复跑写口"
    assert "tradingDate" in sr and "slotTime" in sr and "snapshotType" in sr and "datasetId" in sr, \
        "请求体必须带全四元组（防 quarter_hour 槽被按 half_hour 重判）"
    assert "d.snapshotType || 'half_hour'" in sr, "snapshotType 缺字段回落 half_hour"
    assert "if (STATE.rerunBusy) return" in sr, "并发护栏（与 relay 重跑共用）"
    assert "STATE.slotEntries" in sr, "应按 key 从 slotEntries 取回槽文档"
    assert "loadAll()" in sr, "重跑后刷新当日全部槽"
    assert "rerunMsg" in sr


def test_slot_rerun_executes_post_and_refresh(js: str, tmp_path):
    """**行为**回归（node 探针）：真跑 slotRerun，断言请求体/刷新/取消路径。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        _fn(js, "slotRerun"),
        "globalThis.window = { confirm: () => true };",
        "const KEY = 'dragonboard_live:half_hour:2026-10-19:10:00';",
        "const STATE = { rerunBusy: null, rerunMsg: null, slotEntries: [",
        "  { key: KEY, kind: 'slot', doc: { tradingDate: '2026-10-19', slotTime: '10:00',",
        "    snapshotType: 'half_hour', datasetId: 'dragonboard_live', status: 'degraded' } }] };",
        "const calls = [];",
        "const renderSlots = () => calls.push(['render']);",
        "const jpost = (path, body) => { calls.push(['post', path, body]);",
        "  return Promise.resolve({ ok: true, status: 'ok', slot: { scores: { temperature: 61.2 } } }); };",
        "const loadAll = () => { calls.push(['loadAll']); return Promise.resolve(); };",
        "(async () => {",
        "  slotRerun(KEY);",
        "  await new Promise(r => setTimeout(r, 10));",
        "  window.confirm = () => false;",
        "  slotRerun(KEY);",
        "  console.log(JSON.stringify({ calls, busy: STATE.rerunBusy, msg: STATE.rerunMsg }));",
        "})();",
    ])
    script = tmp_path / "slot_rerun_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    posts = [c for c in got["calls"] if c[0] == "post"]
    assert len(posts) == 1, f"取消后不得再发请求：{got['calls']}"
    assert posts[0][1] == "/api/hotlist-jev/slots/rerun"
    assert posts[0][2] == {"tradingDate": "2026-10-19", "slotTime": "10:00",
                           "snapshotType": "half_hour", "datasetId": "dragonboard_live"}
    assert any(c[:1] == ["loadAll"] for c in got["calls"]), "成功后应刷新当日槽"
    assert got["busy"] is None and got["msg"]["ok"] is True


# ── 2026-10-19：日级 EOD 情绪卡【重跑】按钮（单日 EOD 复跑，网络抖动恢复）──────
def test_eod_rerun_flow_and_endpoint(js: str):
    """EOD 复跑：确认 → POST /eod/rerun（带 tradingDate/snapshotType/datasetId）→ loadAll。"""
    er = _fn(js, "eodRerun")
    assert "window.confirm" in er, "真实模型调用须二次确认"
    assert "/api/hotlist-jev/eod/rerun" in er, "应 POST 日级 EOD 复跑写口"
    assert "tradingDate" in er and "snapshotType" in er and "datasetId" in er
    assert "d.snapshotType || 'half_hour'" in er, "snapshotType 缺字段回落 half_hour"
    assert "if (STATE.rerunBusy) return" in er, "并发护栏（与 relay/slot 重跑共用）"
    assert "x.kind === 'eod'" in er, "应从 slotEntries 取 kind=eod 的当日 EOD 文档"
    assert "loadAll()" in er, "重跑后刷新当日 EOD"
    assert "rerunMsg" in er
    # 与 relay/slot 同用统一 busy/msg（全局互斥）
    assert "STATE.rerunBusy = key" in er and "STATE.rerunMsg =" in er


def test_eod_row_displays_frame_coverage_badge(js: str):
    """2026-10-22 日级语料修复：EOD 行显式展示收盘帧/覆盖度缺口（fail-visible 不静默）。"""
    rs = _fn(js, "renderSlots")
    assert "frameCoverage" in rs, "EOD 行应消费后端 frameCoverage 字段"
    assert "无收盘帧" in rs and "覆盖" in rs, "缺收盘帧/缺槽位应显示角标"
    assert "无帧" in rs, "全无帧不得说成「缺收盘帧」"
    assert "历史证据未落档" in rs, "存量未落 evidenceRaw 的文档须显式标记"


def test_eod_coverage_note_outside_table_and_counts_empty_slots(js: str):
    """审查 P2-1/P3-1：覆盖提示放表格外；缺槽位与空证据帧分别披露。"""
    re_ = _fn(js, "renderEod")
    assert "$('eodCovNote').innerHTML = covNote" in re_, "提示须注入表格外容器"
    assert "covNote + head + rows" not in re_, "不得把 div 塞进 table.innerHTML"
    assert "emptySlots" in re_ and "空证据帧" in re_, "空证据帧须独立披露"
    assert "missingSlots.length" in re_, "缺槽位须独立计数"
    assert "eodCovNote" in js, "页面须提供表格外提示容器"


def test_eod_rerun_executes_post_and_refresh(js: str, tmp_path):
    """**行为**回归（node 探针）：真跑 eodRerun，断言请求体/刷新/取消路径。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        _fn(js, "eodRerun"),
        "globalThis.window = { confirm: () => true };",
        "const KEY = 'dragonboard_live:half_hour:2026-10-19:EOD';",
        "const STATE = { rerunBusy: null, rerunMsg: null, slotEntries: [",
        "  { key: KEY, kind: 'eod', doc: { tradingDate: '2026-10-19', snapshotType: 'half_hour',",
        "    datasetId: 'dragonboard_live', kind: 'eod', status: 'degraded' } }] };",
        "const calls = [];",
        "const renderSlots = () => calls.push(['render']);",
        "const jpost = (path, body) => { calls.push(['post', path, body]);",
        "  return Promise.resolve({ ok: true, status: 'ok', eod: { scores: { day_temperature: 55.9 } } }); };",
        "const loadAll = () => { calls.push(['loadAll']); return Promise.resolve(); };",
        "(async () => {",
        "  eodRerun(KEY);",
        "  await new Promise(r => setTimeout(r, 10));",
        "  window.confirm = () => false;",
        "  eodRerun(KEY);",
        "  console.log(JSON.stringify({ calls, busy: STATE.rerunBusy, msg: STATE.rerunMsg }));",
        "})();",
    ])
    script = tmp_path / "eod_rerun_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    posts = [c for c in got["calls"] if c[0] == "post"]
    assert len(posts) == 1, f"取消后不得再发请求：{got['calls']}"
    assert posts[0][1] == "/api/hotlist-jev/eod/rerun"
    assert posts[0][2] == {"tradingDate": "2026-10-19", "snapshotType": "half_hour",
                           "datasetId": "dragonboard_live"}
    assert any(c[:1] == ["loadAll"] for c in got["calls"]), "成功后应刷新当日 EOD"
    assert got["busy"] is None and got["msg"]["ok"] is True


# ── 2026-10-19：【分带观察】滞后/缺失改为一键刷新按钮（零模型调用）──────────────
def test_band_refresh_button_replaces_manual_command(js: str, html: str):
    """滞后/失败不再是页内横幅，而是：文字进底部状态栏 + console，页内保留一键刷新按钮
    （2026-10-31 用户裁决：主窗口不打横幅/大段文本，AGENTS 同规）。"""
    warn = _fn(js, "bandRefreshWarnHtml")
    assert "分带表与当前序列不同步" in warn, "滞后提示文案保留（走状态栏，不页内渲染）"
    assert "sbLog('warn'" in warn and "[分带观察]" in warn, "滞后提示须进底部状态栏（2026-10-31 裁决）"
    assert "sbLog('error'" in warn, "刷新失败须进底部状态栏"
    assert "console.log" in warn, "日志尾部进浏览器 console（不页内大段文本）"
    assert "bandRefreshBtn()" in warn, "页内保留一键刷新按钮（唯一控件）"
    assert "banner" not in warn and "innerHTML" not in warn, "页内不再渲染横幅文本"
    assert "重跑 scripts/jev_relay_band_diagnostic.py --emit-json" not in js, \
        "手敲命令行的说明应已被按钮取代"
    # 未生成时的提示同样带按钮（缺失场景可一键补齐）
    assert "bandRefreshBtn()" in js[js.index("const bandDiagMissing"):js.index("const bandRefreshBusy")]
    # 2026-10-19 用户裁决：页头整块（含命令面板）已删除；手工命令文案仍留在
    # bandDiagMissing 的后端 hint 回退里，且后端 hint 自带 cwd 指引
    assert "function showBandCmd(" not in html, "页头删除后命令面板连同其触发按钮一并移除"


def test_band_refresh_flow_and_endpoints(js: str):
    """刷新流程：确认 → POST 后台任务 → 5s 轮询 → 完成 loadAll；失败保留旧表 + 结构化原因。"""
    br = _fn(js, "bandRefresh")
    assert "window.confirm" in br, "重算耗时 5–9 分钟，须二次确认"
    assert "'/api/hotlist-jev/relay-band/refresh'" in br, "应 POST 刷新写口"
    assert "bandRefreshBusy()" in br, "并发护栏：任务在跑时不重复起"
    assert "pollBandRefresh()" in br or "bandRefreshAdopt(" in br, "起任务成功后进入轮询"
    poll = _fn(js, "pollBandRefresh")
    assert "jget('/api/hotlist-jev/relay-band/refresh')" in poll, "轮询读任务状态"
    assert "5000" in poll, "轮询间隔 5s"
    assert "st.ok" in poll and "loadAll()" in poll, "完成后重取新表"
    assert "error" in poll, "失败原因须结构化透出（fail-visible）"
    assert "running" in poll, "运行中继续轮询"
    # 按钮：运行中禁用 + 显示已耗时
    btn = js[js.index("const bandRefreshBtn"):js.index("function bandRefreshWarnHtml")]
    assert "disabled" in btn and "bandElapsed" in btn
    # renderDiagPanel 改用统一 banner
    dp = _fn(js, "renderDiagPanel")
    assert "renderBandRefreshWarn()" in dp
    # already_running 不得当失败：接管在跑任务继续轮询（2026-10-19 用户报错修复）
    assert "'already_running'" in br and "bandRefreshAdopt" in br, \
        "双击/多标签/刷新重入 → 接管在跑任务，不报错"
    assert "pollBandRefresh()" in _fn(js, "bandRefreshAdopt")
    # 先占位再确认：防 confirm 弹窗期间重复点击 → 并发 POST 得到 already_running
    assert br.index("STATE.bandRefresh = { running: true, startedAt: null }") \
        < br.index("window.confirm"), "应在弹确认前先置忙占位"
    # 页面加载/切日期时接管后端在跑任务（刷新页面不断链）
    assert "bandRefreshSync()" in _fn(js, "loadAll")
    assert "/api/hotlist-jev/relay-band/refresh" in _fn(js, "bandRefreshSync")
    # 后端无任务记录（服务重启）→ 明确原因，不给 `exit null` 类无信息量文案
    assert "任务状态丢失" in poll


def test_band_refresh_executes_post_and_polls(js: str, tmp_path):
    """**行为**回归（node 探针）：真跑 bandRefresh，断言请求体/轮询接线/并发护栏。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        "const bandRefreshBusy = () => !!(STATE.bandRefresh && STATE.bandRefresh.running);",
        "const STATE = { bandRefresh: null, bandRefreshTimer: null };",
        "globalThis.window = { confirm: () => true };",
        "const calls = [];",
        "const renderBandRefreshWarn = () => calls.push(['render', STATE.bandRefresh && STATE.bandRefresh.running]);",
        "const pollBandRefresh = () => calls.push(['poll', STATE.bandRefresh && STATE.bandRefresh.running]);",
        "const jpost = (p, b) => { calls.push(['post', p, b]);",
        "  return Promise.resolve({ ok: true, running: true, startedAt: '2026-10-19T10:00:05', pid: 7 }); };",
        _fn(js, "bandRefreshAdopt"),
        _fn(js, "bandRefresh"),
        "(async () => {",
        "  bandRefresh();",
        "  await new Promise(r => setTimeout(r, 20));",
        "  const first = JSON.parse(JSON.stringify(STATE.bandRefresh));",
        "  globalThis.window.confirm = () => false;",
        "  bandRefresh();   // 已在跑 → 并发护栏拦下：不得再发请求，也不得清掉在跑状态",
        "  console.log(JSON.stringify({ calls, first, state: STATE.bandRefresh }));",
        "})();",
    ])
    script = tmp_path / "band_refresh_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    posts = [c for c in got["calls"] if c[0] == "post"]
    assert len(posts) == 1, f"并发期不得重复起任务：{got['calls']}"
    assert posts[0][1] == "/api/hotlist-jev/relay-band/refresh" and posts[0][2] == {}
    assert any(c[:1] == ["poll"] and c[1] is True for c in got["calls"]), "起任务后应轮询"
    assert got["first"]["running"] is True and got["first"]["startedAt"] == "2026-10-19T10:00:05"
    assert got["state"] == got["first"], "在跑状态不得被重复点击清掉"


def test_band_refresh_adopts_already_running(js: str, tmp_path):
    """**行为**回归（node 探针）：后端返回 already_running → 接管在跑任务继续轮询，不报错。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        "const bandRefreshBusy = () => !!(STATE.bandRefresh && STATE.bandRefresh.running);",
        "const STATE = { bandRefresh: null, bandRefreshTimer: null };",
        "globalThis.window = { confirm: () => true };",
        "const calls = [];",
        "const renderBandRefreshWarn = () => {};",
        "const pollBandRefresh = () => calls.push(['poll', STATE.bandRefresh && STATE.bandRefresh.running]);",
        "const jpost = () => { calls.push(['post']);",
        "  return Promise.resolve({ ok: false, reason: 'already_running', running: true,",
        "    startedAt: '2026-10-19T18:05:36' }); };",
        _fn(js, "bandRefreshAdopt"),
        _fn(js, "bandRefresh"),
        "(async () => {",
        "  bandRefresh();",
        "  await new Promise(r => setTimeout(r, 20));",
        "  console.log(JSON.stringify({ calls, state: STATE.bandRefresh }));",
        "})();",
    ])
    script = tmp_path / "band_refresh_adopt_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert any(c[:1] == ["poll"] and c[1] is True for c in got["calls"]), \
        "already_running 应立即接管轮询"
    assert got["state"]["running"] is True
    assert got["state"]["startedAt"] == "2026-10-19T18:05:36", "沿用后端真实启动时间"
    assert not got["state"].get("error"), "不得标为失败"


# ── 2026-10-19 用户裁决：页名「判定明细」→「涨停分析」+ 表计数改分页（每页 ≤20 条）──
def test_detail_view_renamed_to_limitup_analysis(js: str, html: str):
    """子页名改为「涨停分析」（导航/面包屑/tab 共用 RELAY_VIEWS，故一处即全改）。"""
    rv = _const(js, "RELAY_VIEWS")
    assert "'detail', '涨停分析'" in rv, "子页名应为「涨停分析」"
    assert "'判定明细'" not in rv, "页名不应再叫「判定明细」"
    assert "<!-- ⑤ 涨停分析" in html, "页区块注释应同步改名"
    assert "RELAY_VIEWS.map" in _const(js, "NAV") or "RELAY_VIEWS" in js
    # 行内展开的判定明细卡（单日七题全文）沿用原名：不得连卡片一起改名
    assert "判定明细" in js, "行内判定明细卡（题面/判据）应保留原名，只改页名"


def test_detail_table_paged_20_per_page(js: str):
    """原「59 / 59 日（全库 109）」计数改为分页控件；表体按页切片，KPI 仍吃全量。"""
    rt = _fn(js, "renderRelayTab")
    assert "RELAY_PAGE_SIZE = 20" in js, "每页上限 20 条"
    assert "relayPageSlice(rows, STATE.relayPage)" in rt, "表体须按页切片"
    assert "pageRows.map(" in rt, "应渲染当前页行（不再一次性渲染全部）"
    assert "relayPager(pg.page, pg.total)" in rt, "筛选条应渲染分页控件"
    assert "STATE.relayPage = pg.page" in rt, "越界/筛选后须回写 clamp 后的页码"
    assert "全库 ${STATE.series.length}" not in js, "原计数文案应已被分页取代"
    # 分页不得改口径：KPI / 龙头 / 分带仍吃筛选集全量
    assert "renderRelayKpi(shown)" in rt and "renderRelayKpi(pageRows)" not in rt
    assert "renderLeaders()" in rt
    # 跳页 select 须豁免筛选条焦点守卫，否则页码/禁用态会陈旧
    assert "!ae.classList.contains('pgjump')" in rt
    assert 'class="pgjump"' in js


def test_detail_table_paging_resets_on_view_change(js: str):
    """筛选 / 清除 / 区间（含预设）/ 排序变更 → 回第 1 页。"""
    for fname in ("rSet", "rClear", "rangeRefresh", "setRelaySort"):
        assert "STATE.relayPage = 1" in _fn(js, fname), f"{fname} 应重置页码"
    assert "relayPage: 1," in js, "STATE 应初始化 relayPage"


def test_detail_table_pagination_math(js: str, tmp_path):
    """**行为**回归（node 探针）：页数/切片/越界 clamp/控件禁用态/跳页接线。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        "const STATE = { relayPage: 1 };",
        "function renderRelayTab(){ STATE.renders = (STATE.renders || 0) + 1; }",
        _const(js, "RELAY_PAGE_SIZE"),
        _fn(js, "relayPageTotal"),
        _fn(js, "relayPageSlice"),
        _fn(js, "relayPager"),
        _fn(js, "rPage"),
        "const rows = Array.from({length: 59}, (_, i) => i);",
        "const s1 = relayPageSlice(rows, 1), s3 = relayPageSlice(rows, 3);",
        "const s99 = relayPageSlice(rows, 99), s0 = relayPageSlice(rows, 0);",
        "const p1 = relayPager(1, 3), p3 = relayPager(3, 3);",
        "const pone = relayPager(1, 1);",
        "rPage(5);",
        "console.log(JSON.stringify({",
        "  totals: [relayPageTotal(0), relayPageTotal(20), relayPageTotal(21), relayPageTotal(100)],",
        "  s1: {p: s1.page, t: s1.total, n: s1.rows.length, first: s1.rows[0], last: s1.rows[19]},",
        "  s3: {p: s3.page, n: s3.rows.length, first: s3.rows[0], last: s3.rows[s3.rows.length-1]},",
        "  s99: {p: s99.page, n: s99.rows.length}, s0: {p: s0.page, n: s0.rows.length},",
        "  p1: {prevOff: p1.includes('rPage(0)\" disabled'), nextOn: p1.includes('rPage(2)\">下一页 ›'),",
        "       sel: p1.includes('value=\"1\" selected'), totalTxt: p1.includes('共 3 页'),",
        "       noDays: !p1.includes('共 59 日') && !p1.includes('每页 20')},",
        "  p3: {nextOff: p3.includes('rPage(4)\" disabled'), prevOn: p3.includes('rPage(2)\">‹ 上一页')},",
        "  pone: {noNav: !pone.includes('pgjump') && !pone.includes('‹ 上一页'),",
        "         txt: pone.includes('共 1 页')},",
        "  state: STATE.relayPage, renders: STATE.renders}));",
    ])
    script = tmp_path / "relay_pager_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got["totals"] == [1, 1, 2, 5], "页数 = ceil(n/20)，空集至少 1 页"
    assert got["s1"] == {"p": 1, "t": 3, "n": 20, "first": 0, "last": 19}, "每页 20 条"
    assert got["s3"] == {"p": 3, "n": 19, "first": 40, "last": 58}, "末页取余数，不丢行"
    assert got["s99"]["p"] == 3 and got["s99"]["n"] == 19, "越界页码 clamp 到末页"
    assert got["s0"]["p"] == 1 and got["s0"]["n"] == 20, "非法页码回第 1 页"
    assert got["p1"]["prevOff"] and got["p1"]["nextOn"], "首页：上一页禁用、下一页可用"
    assert got["p1"]["sel"] and got["p1"]["totalTxt"], "跳页器默认选中当前页，右侧报总页数"
    assert got["p1"]["noDays"], "右侧不再列日数/每页条数（2026-10-19 用户裁决：改「共 X 页」）"
    assert got["p3"]["nextOff"] and got["p3"]["prevOn"], "末页：下一页禁用、上一页可用"
    assert got["pone"]["noNav"] and got["pone"]["txt"], "单页：无翻页件，只显示「共 1 页」"
    assert got["state"] == 5 and got["renders"] == 1, "rPage 只写页码并触发一次重绘"


# ── 2026-10-19 评审（frontend-ui lane）修复守卫 ────────────────────────────────
def test_pager_updates_even_when_filter_select_holds_focus(js: str):
    """F-minor-1：筛选 select 持焦跳过整条 bar 重建时，分页节点必须单独刷新（否则页码陈旧）。"""
    rt = _fn(js, "renderRelayTab")
    assert 'id="relayPager"' in js, "pager 须有独立挂载点"
    assert "const pgEl = $('relayPager'); if (pgEl) pgEl.innerHTML = relayPager(pg.page, pg.total);" in rt


def test_band_warn_banner_does_not_duplicate_missing_notice(js: str):
    """F-minor-2：表缺失时 bandDiagMissing() 已给警示+按钮，本处不得再重复一条。"""
    warn = _fn(js, "bandRefreshWarnHtml")
    assert "离线分带表未就绪" not in warn, "缺失提示只由 bandDiagMissing 呈现（避免同屏两条重复警示）"
    assert "if (!lag && !st.running && !st.error)" in warn, "无滞后/无任务/无失败时页内不渲染任何提示"


# ── 2026-10-19 用户报障：涨停复盘 KPI 真连板口径 ─────────────────────────────
def test_review_kpi_height_buckets_use_streak_not_space_boards(js: str):
    """KPI 高度四卡/最高板/高度筛选/排序/高度列必须吃 streakOf（真连板），
    不得再用空间板数 s.boards 冒充（7天4板曾被计成「四板」）。"""
    kpi = _fn(js, "lfRenderKpi")
    assert "streakOf" in kpi, "KPI 分桶须走 streakOf（真连板单源）"
    for old in ["s.boards === 2", "s.boards === 3", "(s.boards || 0) >= 4",
                "Math.max(m, s.boards || 1)"]:
        assert old not in kpi, f"KPI 仍残留空间口径分桶：{old}"
    assert "真连板未定" in kpi, "streak null（回溯不可算）须单列注记（fail-visible）"
    m = _fn(js, "labelMatches")
    assert "streakOf" in m and "(s.boards || 0) < 4" not in m, "高度筛选须吃真连板"
    assert "function streakOf(s){ return s.streak === undefined ? (s.boards || null) : s.streak; }" in js, \
        "streakOf 须保留 undefined→boards 回落（旧档/join 缺失不新增猜数）"


# ── 2026-10-20 用户需求：新增【跌停复盘】页；2026-10-31 页名更「下跌复盘」并新增【上涨复盘】页 ──
def test_dieban_page_registered_like_limitup_review(html: str, js: str):
    """侧栏/面包屑/载入链/挂载点齐备，展示骨架与涨停复盘同源（KPI 条+板块 chips+筛选条+表）。"""
    assert "['dieban', '下跌复盘'," in js, "侧栏须有【下跌复盘】入口"
    assert "['rise', '上涨复盘'," in js, "侧栏须有【上涨复盘】入口"
    assert "dieban: ['下跌复盘']" in js, "面包屑须含下跌复盘"
    assert "rise: ['上涨复盘']" in js, "面包屑须含上涨复盘"
    assert 'id="tab-dieban"' in html, "须有 tab-dieban 区块"
    seg = html[html.index('id="tab-dieban"'):]
    seg = seg[: seg.index("</section>")]
    for hook in ('class="page-head"', "<h2>下跌复盘</h2>",
                 'id="diebanHint"', 'id="diebanKpi"', 'id="diebanBoardRow"',
                 'id="diebanFilterBar"', 'id="diebanTable"'):
        assert hook in seg, f"跌停复盘页缺展示骨架：{hook}"
    assert 'id="diebanBanner"' not in html, "横幅宿主须删除（降级走底部状态栏，2026-10-31 裁决）"
    assert 'class="kpi-strip" id="diebanKpi"' in seg, "KPI 条须复用涨停复盘的 kpi-strip 样式"
    assert 'class="lf-bar" id="diebanFilterBar"' in seg, "筛选条须复用 lf-bar 样式"
    load = _fn(js, "loadAll")
    assert "/api/hotlist-jev/dieban-review" in load, "loadAll 须拉取下跌复盘读口"
    assert "renderDieban()" in load, "loadAll 须触发下跌复盘重绘"
    assert "/api/hotlist-jev/rise-review" in load, "loadAll 须拉取上涨复盘读口"
    assert "renderRise()" in load, "loadAll 须触发上涨复盘重绘"
    # 读口失败不得静默当空页：catch 必须带 reason
    assert "dieban_read_failed" in load and "rise_read_failed" in load


def test_dieban_page_fail_visible_banner(js: str):
    """读口不可用/降级/盘中口径/无数据都要显式标注，不用空表冒充。

    2026-10-30 用户裁决：报错黄条页内删除，读口不可用只进底部状态栏
    （dbRenderBanner 的 ok===false 分支改为 sbLog + 不渲染）；口径/降级说明条保留。
    """
    banner = _fn(js, "dbRenderBanner")
    for key in ("ok === false", "D.degraded", "noData"):
        assert key in banner, f"banner 缺 fail-visible 分支：{key}"
    assert "'[下跌复盘] '" in banner and "sbLog('error', tag" in banner, "读口不可用须进底部状态栏"
    assert "sbLog('warn', tag + msgs.join" in banner, "降级原因须进底部状态栏（2026-10-31 裁决）"
    assert "banner amber" not in banner and "innerHTML" not in banner, "页内不得再渲染任何横幅"
    render = _fn(js, "renderDieban")
    assert "D.ok === false" in render and "D.noData" in render, "无数据/读口失败须走空态分支"
    # 读口不可用 ≠ 当日无负反馈：两个空态文案必须分开（不得把读失败说成「无数据」）
    assert "读口不可用：未取到名单" in render and "当日无任何可用原始记录" in render
    assert "当日无负反馈记录" not in render, "旧文案把读失败与真无数据混为一谈"
    # 新增披露字段必须在 banner/KPI 有消费（否则等于没披露）
    for key in ("full_market_count_disputed", "streak_lookback", "countDisputed"):
        assert key in (banner if key != "countDisputed" else _fn(js, "dbRenderKpi")),             f"新披露字段未被消费：{key}"
    assert "未落库" not in js, "页面/注释不得再称全市场逐股未落库（§1.2-5 展示须随结论同步）"


def test_rise_page_registered_like_dieban_review(html: str, js: str):
    """2026-10-31 用户需求：新增【上涨复盘】页（全市场涨幅>5% 未涨停；样式与下跌复盘同源）。

    - 侧栏/面包屑/tab 区块/载入链/挂载点齐备；
    - 行展开走 lgRow('rise') 通用链（STATE.riseUi/riseEntries），detailHtml 分支到 rsDetailHtml；
    - 读口失败不得静默当空页（catch 带 reason + 状态栏）。
    """
    assert "['rise', '上涨复盘'," in js, "侧栏须有【上涨复盘】入口"
    assert "rise: ['上涨复盘']" in js, "面包屑须含上涨复盘"
    assert 'id="tab-rise"' in html, "须有 tab-rise 区块"
    seg = html[html.index('id="tab-rise"'):]
    seg = seg[: seg.index("</section>")]
    for hook in ('class="page-head"', "<h2>上涨复盘</h2>",
                 'id="riseHint"', 'id="riseKpi"', 'id="riseBoardRow"',
                 'id="riseFilterBar"', 'id="riseTable"'):
        assert hook in seg, f"上涨复盘页缺展示骨架：{hook}"
    assert 'id="riseBanner"' not in html, "横幅宿主须删除（降级走底部状态栏，2026-10-31 裁决）"
    assert 'class="kpi-strip" id="riseKpi"' in seg, "KPI 条须复用 kpi-strip 样式"
    banner = _fn(js, "rsRenderBanner")
    for key in ("ok === false", "D.degraded", "noData"):
        assert key in banner, f"rise banner 缺 fail-visible 分支：{key}"
    assert "'[上涨复盘] '" in banner and "sbLog('error', tag" in banner, "读口不可用须进底部状态栏"
    assert "sbLog('warn', tag + msgs.join" in banner, "降级原因须进底部状态栏（2026-10-31 裁决）"
    assert "banner amber" not in banner and "innerHTML" not in banner, "页内不得再渲染任何横幅"
    render = _fn(js, "renderRise")
    assert "D.ok === false" in render and "D.noData" in render, "无数据/读口失败须走空态分支"
    assert "读口不可用：未取到名单" in render and "当日无任何可用原始记录" in render
    detail = _fn(js, "detailHtml")
    assert "rsDetailHtml" in detail, "detailHtml 须分支到上涨复盘行展开"
    lg_entries = _fn(js, "lgEntries")
    assert "STATE.riseEntries" in lg_entries, "行展开条目路由须含 rise"


def test_recap_daily_page_registered_and_statusbar_only(html: str, js: str):
    """2026-10-31 预登记（jev-daily-recap-design.md）：【复盘日报】页（纯读落库文档）。

    2026-10-31 用户裁决版式（七点）：KPI 卡条 + 成文叙事表格（lg-tree 分组字段）+
    题目集/投喂语料收进涨停复盘同款详情卡（lg-card，详细信息/原始 JSON 切换）+
    无横幅（问题走底部状态栏）+ 日期随顶栏全局控件。
    """
    assert "['recap', '复盘日报'," in js, "侧栏须有【复盘日报】入口"
    assert "recap: ['复盘日报']" in js, "面包屑须含复盘日报"
    assert 'id="tab-recap"' in html, "须有 tab-recap 区块"
    seg = html[html.index('id="tab-recap"'):]
    seg = seg[: seg.index("</section>")]
    for hook in ('<h2>复盘日报</h2>', 'id="recapHint"', 'id="recapBody"',
                 'id="recapKpi"', 'id="recapDetailBody"', '<details'):
        assert hook in seg, f"复盘日报页缺展示骨架：{hook}"
    assert "非交易信号" in seg, "页头须声明非交易信号"
    assert "banner" not in seg.lower(), "复盘日报页不得有横幅宿主"
    # 2026-10-31 裁决：日期列表版式（连板情绪同构）——区间条 + 逐日列表 + 行展开
    for hook in ('id="recapRangeBar"', 'id="recapTable"', 'id="recapListHint"'):
        assert hook in seg, f"复盘日报页缺日期列表骨架：{hook}"
    load = _fn(js, "loadAll")
    assert "rcSeriesFetch()" in load, "loadAll 须拉取区间 series"
    assert "function rcRangeBar()" in js and "function rcPreset(" in js, "区间条（近1月/近3月/全部）须存在"
    assert "function rcRow(" in js and "rcRowFetch(" in js, "行展开懒拉完整档须存在"
    assert "'/api/hotlist-jev/daily-recap'" in load, "loadAll 须拉复盘日报读口"
    assert "renderRecap();" in load, "loadAll 须触发复盘日报重绘"
    render = _fn(js, "renderRecap")
    assert "RC_TAG = '[复盘日报] '" in js, "状态栏前缀常量须存在"
    for key in ("D.ok === false", "D.missing", "R.degraded"):
        assert key in render, f"renderRecap 缺 fail-visible 分支：{key}"
    assert "sbLog('error', RC_TAG" in render and "sbLog('info', RC_TAG" in render \
        and "sbLog('warn', RC_TAG" in render, "异常/缺文档/降级须分级进底部状态栏"
    # 版式七点守卫：KPI 卡条 / 叙事表格（treeHtml 分组）/ 详情卡（详细信息+原始JSON切换）
    assert "$('recapKpi')" in render, "renderRecap 须渲染 KPI 卡条"
    assert "treeHtml(_rcFactTree(R), '')" in render and "treeHtml(_rcPlanTree(R), '')" in render, \
        "成文须为叙事表格（分组字段树）"
    detail = _fn(js, "rcDetailCardHtml")
    assert "rcMode('detail', event)" in detail and "rcMode('raw', event)" in detail, \
        "详情卡须有 详细信息/原始 JSON 切换（涨停复盘同款）"
    assert "lg-card" in detail and "lg-meta" in detail and "lg-foot" in detail, \
        "详情卡须复用 lg-card 范式"
    assert "treeHtml(stateTree, '')" in detail, "投喂语料须以字段树展示"
    assert "narrative" not in render + detail, "短叙事已删（题目集 v2 裁决），不得回流"


def test_dieban_scope_predicates_behaviour(js: str, tmp_path):
    """**行为**回归（node 探针）：负反馈范围谓词与筛选（跌停/连跌/一字/大跌/回撤/下跌）。"""
    if shutil.which("node") is None:
        pytest.skip("node 不可用")
    src = "\n".join([
        _const_block(js, "DB_SCOPE_PRED"),
        _fn(js, "dbMatches"),
        "const rows = [",
        "  {code:'600001', name:'A', board:'算力', pctChange:-10, limitDown:true, oneWordLimitDown:true, deepDrop:true, streak:3, maxDrawdownPct:null},",
        "  {code:'600002', name:'B', board:'算力', pctChange:-8, limitDown:false, oneWordLimitDown:false, deepDrop:true, streak:null, maxDrawdownPct:12.5},",
        "  {code:'600003', name:'C', board:'医药', pctChange:2.5, limitDown:false, oneWordLimitDown:false, deepDrop:false, streak:null, maxDrawdownPct:null},",
        "  {code:'600004', name:'D', board:'医药', pctChange:-3, limitDown:false, oneWordLimitDown:false, deepDrop:false, streak:null, maxDrawdownPct:15},",
        "];",
        "const pick = k => rows.filter(DB_SCOPE_PRED[k]).map(r => r.code);",
        "console.log(JSON.stringify({",
        "  neg: pick('neg'), die: pick('die'), streak: pick('streak'), oneword: pick('oneword'),",
        "  big: pick('big'), draw: pick('draw'), down: pick('down'), all: pick('all'),",
        "  q: rows.filter(r => dbMatches(r, {q:'60000', board:'', scope:'neg', streak:'', draw:''})).length,",
        "  board: rows.filter(r => dbMatches(r, {q:'', board:'医药', scope:'all', streak:'', draw:''})).map(r => r.code),",
        "  streak2: rows.filter(r => dbMatches(r, {q:'', board:'', scope:'neg', streak:'2', draw:''})).map(r => r.code),",
        "  draw10: rows.filter(r => dbMatches(r, {q:'', board:'', scope:'neg', streak:'', draw:'10'})).map(r => r.code),",
        "}));",
    ])
    script = tmp_path / "dieban_scope_probe.js"
    script.write_text(src, encoding="utf-8")
    cp = subprocess.run(["node", str(script)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    assert cp.returncode == 0, f"node 执行失败：{cp.stderr}"
    got = json.loads(cp.stdout.strip())
    assert got["neg"] == ["600001", "600002", "600004"], "负反馈全部=跌停∪大跌∪触板回撤（不含上涨股）"
    assert got["die"] == ["600001"] and got["oneword"] == ["600001"]
    assert got["streak"] == ["600001"], "连跌≥2 只看 streak 天数"
    assert got["big"] == ["600001", "600002"], "大跌≤-7%（含跌停）"
    assert got["draw"] == ["600002", "600004"], "触板回撤只看 THS 回撤幅值"
    assert got["down"] == ["600001", "600002", "600004"], "下跌=跌幅<0"
    assert got["all"] == ["600001", "600002", "600003", "600004"]
    assert got["q"] == 4, "代码搜索命中"
    assert got["board"] == ["600003", "600004"], "板块筛选"
    assert got["streak2"] == ["600001"] and got["draw10"] == ["600002", "600004"]


def test_dieban_table_marks_and_sort_keys(js: str):
    """表格列与排序键成对齐（避免点了表头不生效）；类型徽标覆盖五类负反馈。"""
    rows = _fn(js, "dbRenderRows")
    for key in ("'code'", "'pctChange'", "'streak'", "'ret3d'", "'maxDrawdownPct'",
                "'turnoverRate'", "'volumeRatio'", "'mainNet'"):
        assert key in rows, f"排序键缺失：{key}"
    badges = _fn(js, "dbTypeBadges")
    for label in ("跌停", "一字跌停", "连跌", "大跌", "触板回撤"):
        assert label in badges, f"类型徽标缺：{label}"
    detail = _fn(js, "dbDetailHtml")
    assert "口径与读数" in detail and "读口行 JSON" in detail, "行展开须给口径读数 + 原始行 JSON"
    assert "is_limit_down_pct" in detail, "展开卡须标注跌停判定单一事实源"


# ── 2026-10-20 立项：全市场逐股明细接入（EM/TDX 回填 + 读口合并）────────────────
def test_dieban_full_market_rows_display(js: str):
    """全市场逐股接入后的展示守卫：来源徽标/EM 封板字段/截断与缺文档注记/KPI 主值。"""
    kpi = _fn(js, "dbRenderKpi")
    assert "跌停家数（全市场）" in kpi, "KPI 主值应升级为全市场家数"
    assert "rowsMissing" in kpi and "rowsCount" in kpi, "逐股覆盖（缺/行数）须在副行标注"
    assert "rowsSourceLabel" in kpi, "逐股来源须标注（EM/快照/本地日线跨源）"
    banner = _fn(js, "dbRenderBanner")
    assert "full_market_rows" in banner, "缺逐股文档须进 banner（fail-visible）"
    assert "rowsTruncated" in banner and "rowsBad" in banner, "截断/坏行须显式注记"
    src = _const(js, "dbSrcTxt")
    assert "full_market" in src and "全市场逐股" in src, "来源列须含全市场逐股"
    detail = _fn(js, "dbDetailHtml")
    for field in ("emStreakDays", "openNum", "lastSealTime"):
        assert field in detail, f"行展开须带 EM 封板字段：{field}"
    # 未知不得判否：无一字判据的行必须渲染 null（不是 false）
    assert "s.oneWordLimitDown == null ? null : !!s.oneWordLimitDown" in detail
    # 截取自 renderDieban 真实函数体（旧写法切到文件末尾 → 断言恒真，属空洞守卫）
    hint = _fn(js, "renderDieban")
    assert "全市场逐股" in hint and "fm.rowsMissing" in hint, "hint 须标注逐股覆盖状态"
    assert "countDisputed" in hint, "hint 须标注家数存疑"
    # 读为主非纯读：懒加载写库须在注释/文案里如实说明
    assert "非纯读" in js


# ── 2026-10-20 用户需求：涨停复盘【原因】列（韭研异动解析首行）────────────────────
def test_limitup_reason_column_present(js: str, html: str):
    """表头/行体都须有【原因】列，取值 s.reason（后端 join 解析首行）；
    列宽截断 + title 保全文（不丢数据）；缺失显示 '-' 不伪造。"""
    rows = _fn(js, "lfRenderRows")
    assert "<th>原因</th>" in rows, "表头须有【原因】列"
    assert "s.reason" in rows and "lg-reason" in rows, "行体须渲染 s.reason 并带列样式类"
    assert 'title="${esc(reasonTxt)}"' in rows, "完整原因须进 title（列宽省略不丢数据）"
    assert "韭研异动解析首行缺失" in rows, "缺失时须给 '-' 与可见原因说明（fail-visible）"
    assert ".lg-reason{" in html and "text-overflow:ellipsis" in html, "原因列须限宽省略"


def test_limitup_slot_tag_marks_midday_feed(js: str):
    """驱动列「午盘」徽标已删（2026-10-21 用户裁决：纯多余；槽位口径可追溯性由落库
    labelSlot/jiuyanFetchedAt 字段承担，页面不再逐股贴标；取代 2026-10-20 的在场断言）。"""
    rows = _fn(js, "lfRenderRows")
    assert "slotTag" not in rows and ">午盘</span>" not in rows, "驱动列不得再贴「午盘」徽标"


# ── 2026-10-21 立项 R2：反包 KPI 卡 + 明细行（jev-rewrap-factor-preregistration.md）──
def test_relay_page_has_rewrap_kpi_and_row():
    """反包 KPI 卡（点击筛选 scope=rewrap）必须在场；文字明细行与驱动列「午盘」徽标已删
   （2026-10-21 用户反馈：纯多余，反包详情点击 KPI 卡筛选主表即可见）。"""
    html = (Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html").read_text(encoding="utf-8")
    assert "rewrap: '反包'" in html, "SCOPE_CN 缺反包范围"
    assert "onclick=\"lfScope('rewrap')\"" in html, "KPI 反包卡缺点击筛选"
    assert "午盘触板口径" in html, "反包卡缺口径徽标（触板≠封板）"
    assert 'id="labelRewrapRow"' not in html and "lfRenderRewrap" not in html, "反包池文字行应已删除"
    assert "反包池 " not in html, "反包池文字描述应已删除"
    assert 'slotTag' not in html and ">午盘</span>" not in html, "驱动列「午盘」徽标应已删除"


# ── 温度置信度透出（2026-10-24 题材龙头方法论回灌：score 型答案实测同带 confidence）──

def test_temperature_confidence_in_slots_table_and_eod_row(js: str):
    """总览逐槽表温度列与 EOD 行温度补 confChip，同读 answers.temperature/day_temperature。"""
    rs = _fn(js, "renderSlots")
    # 槽级温度列：与框架阶段/序列/拥挤列同一 confChip 同一来源（answers.temperature.confidence）
    assert "confChip((a.temperature||{}).confidence)" in rs, "温度列须挂模型置信 chip"
    assert "confChip(((e.answers||{}).day_temperature||{}).confidence)" in rs, \
        "EOD 行温度须挂 day_temperature 置信 chip"
    # 温度唯一口径不被回归：数值仍来自 scores（answers.temperature.score 是 0-9 原始档位分，两套刻度禁混）
    assert "s.scores ? s.scores.temperature : null" in rs


def test_temperature_confidence_in_kpi_card_and_eod_window(js: str):
    """KPI「日级温度」卡与 EOD 日级窗口「日级温度」行同源透出置信（后者此前硬编码 null）。"""
    rk = _fn(js, "renderKpis")
    assert "const tempAns = intraday ? (sa.temperature || {}) : (ea.day_temperature || {});" in rk
    assert "${temp ?? '-'}${confChip(tempAns.confidence)}" in rk, "KPI 温度卡须带置信 chip"
    re_ = _fn(js, "renderEod")
    assert "(a[tempKey]||{}).confidence" in re_, "日级窗口温度行不得再硬编码 null 置信"


# ── 连板行情页（2026-10-29 用户裁决：韭研 fields[] 左目录 + 成分股右列表 + KPL 3006 行情；
#    仅内存态不落库；热榜行情页同轮删除）──

def test_lianban_view_wired(html: str, js: str):
    """侧栏入口 + 视图 + 面包屑接线齐备（setView 自动显隐 tab-lianban）。"""
    assert 'id="tab-lianban"' in html, "缺 tab-lianban 视图"
    assert "['lianban', '连板行情'" in html, "侧栏缺连板行情入口"
    assert "lianban: ['连板行情']" in js, "VIEW_CRUMB 缺连板行情"


def test_lianban_board_dir_columns(html: str, js: str):
    """左栏目录七列（2026-10-29 用户需求）：#/板块/家数 + 节点/聚合涨幅/主力净额/成交额。"""
    boards = _fn(js, "lbRenderBoards")
    for col in ("板块", "家数", "节点", "聚合涨幅", "主力净额", "成交额"):
        assert col in boards, f"左栏目录缺「{col}」列"
    # 节点/聚合涨幅复刻板块节点模块（同源合同）：NODE_CN 徽标 + aggN10.pctMean
    assert "NODE_CN[nr.node]" in boards and "NODE_BADGE[nr.node]" in boards
    assert "aggN10.pctMean" in boards, "聚合涨幅应取 aggN10.pctMean（近10日活跃股均值）"
    assert "KQ.MAIN_NET" in boards and "KQ.AMOUNT" in boards, "主力净额/成交额=成员股 quotas 聚合"
    # 节点数据源：sector-nodes 读口（lbLoad 拉取，按 board 名匹配）
    load = _fn(js, "lbLoad")
    assert "sector-nodes" in load, "lbLoad 应拉板块节点读口"
    assert "LB.nodesRows[row.board]" in load, "按 board 名匹配韭研板块"


def test_lianban_layout_left_dir_right_stocks(html: str):
    """左栏板块目录表 + 右栏成分股表（.kpl-layout 左目录右列表，参照 KPL 板块行情）。"""
    assert 'class="kpl-layout"' in html.split('tab-lianban')[1].split('</section>')[0]
    assert 'id="lbBoardTable"' in html and 'id="lbStockTable"' in html
    assert 'id="lbBoardSearch"' in html, "左栏缺板块搜索"


def test_lianban_memory_only_no_persistence(js: str):
    """仅内存态：LB 状态对象无 localStorage/sessionStorage/IndexedDB 写入；读口=jiuyan-action。"""
    for fn_name in ("lbLoad", "lbRenderBoards", "lbRenderStocks", "lbSyncSubscription",
                    "lbEnter", "lbLeave"):
        body = _fn(js, fn_name)
        for bad in ("localStorage", "sessionStorage", "indexedDB"):
            assert bad not in body, f"{fn_name} 不得持久化（{bad}）"
    assert "jiuyan-action" in _fn(js, "lbLoad"), "连板数据读口应为 /api/hotlist-jev/jiuyan-action"
    assert "setInterval" in _fn(js, "lbEnter"), "动态更新应有轮询计时器"
    assert "clearInterval" in _fn(js, "lbLeave"), "离开页签应停计时器"


def test_lianban_kpl_socket_subscription_and_guards(js: str):
    """行情列接入 KPL socket：个股并入共享订阅缓存；3006 口径护栏不猜数。"""
    sub = _fn(js, "lbSyncSubscription")
    assert "lbCode(s.code)" in sub, "订阅码必须经 lbCode 归一化（实测全集带交易所前缀 sz001219）"
    assert "kplSyncStockSubscription" in sub, "板块宇宙已引导时应复用共享订阅缓存"
    assert "stock_ids: codes" in sub, "宇宙未引导时应直接订阅个股清单"
    stocks = _fn(js, "lbRenderStocks")
    assert "lbCode(s.code)" in stocks, "hq 查找键必须用归一化 6 位码"
    assert "KPL.hq.get" in stocks, "行情列应读 3006 KPL.hq 实时覆盖"
    assert "hq.price / 10000" in stocks, "price ×10000 缩放合同（113000=11.30 元）"
    assert "hq.inc_rate / 100" in stocks, "inc_rate ×100 换算合同（125→1.25%）"
    assert "21" in stocks, "涨幅越界护栏（|pct|>21 → '--'，口径异常不猜数）"
    assert "韭研盘口快照价" in stocks, "行情未到流应兑底韭研快照价并标注"
    # 连板列：韭研 num 实测为「X天X板」字符串，纯数字才拼「板」（修「X天X板板」重复后缀）
    assert "/^\\d+$/.test(numRaw) ? numRaw + '板' : numRaw" in stocks


def test_lianban_meta_date_guard(js: str):
    """直达页时 KPL.today 必须补当日（空 date → live-stocks-meta 400 → 领涨/换手/概念永无值）。"""
    enter = _fn(js, "lbEnter")
    assert "!KPL.today" in enter and "KPL.today =" in enter, "lbEnter 缺 KPL.today 兑底"
    meta = _fn(js, "kplLiveFetchStockMeta")
    assert "KPL.today" in meta


def test_lianban_stock_table_fields_match_kpl_sector_page(js: str):
    """右栏个股表字段与 KPL【板块行情】个股列表一致（2026-10-29 用户裁决，非盘点表换页）。"""
    stocks = _fn(js, "lbRenderStocks")
    for col in ("代码", "名称", "地位", "现价", "涨幅%", "换手%", "连板",
                "主力净", "主力买", "主力卖", "量比", "成交额", "概念"):
        assert col in stocks, f"个股表缺 KPL 板块行情同款列「{col}」"
    # 行情值同源：WS 3001 混合流 quotas 优先（与板块行情同源）+ stockMeta 地位/换手/概念
    assert "KPL.items.get(code)" in stocks, "行情应优先读 3001 quotas（KPL.items，与板块行情同源）"
    assert "gv(KQ.MAIN_NET)" in stocks and "gv(KQ.AMOUNT)" in stocks and "gv(KQ.VR)" in stocks
    assert "mv(code, 'rank_title')" in stocks and "mv(code, 'turnover')" in stocks
    assert "mv(code, 'concept')" in stocks, "概念列应来自 live-stocks-meta"
    load = _fn(js, "lbLoad")
    assert "kplLiveFetchStockMeta" in load, "lbLoad 应拉个股 meta（地位/换手/概念）"


def test_quotes_page_fully_removed(html: str, js: str):
    """删除回归锁：热榜行情页（tab-quotes/quotes-review/热榜行情）零残留（2026-10-29 用户裁决）。"""
    assert "tab-quotes" not in html and "热榜行情</h2>" not in html
    assert "quotes-review" not in html
    for name in ("renderQuotes", "quotesMatches", "quotesDetailHtml", "qRenderRows",
                 "quotesFilter", "quotesSlots"):
        assert name not in js, f"{name} 残留"


# ── 底部状态栏（2026-10-29 用户需求：全站警告/错误系统日志 fail-visible）──

def test_status_bar_wired(html: str, js: str):
    """状态栏 DOM + 日志总线接线齐备：console 拦截/window.onerror/unhandledrejection。"""
    assert 'id="sbBar"' in html and 'id="sbPanel"' in html, "状态栏 DOM 缺失"
    for hook in ("console[lv]", "addEventListener('error'", "addEventListener('unhandledrejection'"):
        assert hook in js, f"日志总线缺 {hook} 捕获"
    assert "window.sbLog = sbLog" in js, "应暴露 sbLog 供功能代码调用"


def test_status_bar_capture_first_and_no_html_injection(html: str, js: str):
    """总线安装在 STATE 之前（最早错误也捕获）；错误文本走 textContent 不进 innerHTML。"""
    assert js.index("// ══ 底部状态栏日志总线") < js.index("const STATE = {"), "总线必须先于页面状态安装"
    render_fn = _fn(js, "render")
    # sbRender 内部（bus IIFE 的 render）用 textContent + createElement，不用 innerHTML 拼消息
    assert "sb-msg" in render_fn and ".textContent = e.msg" in render_fn
    # 唯一 innerHTML 用途是固定徽标骨架（无消息内容插值）
    assert "${" not in render_fn, "状态栏 render 不得插值拼 HTML（消息必须 textContent）"


def test_status_bar_fold_throttle(js: str):
    """2026-10-30 刷屏治理：同类（级别+文本）在折叠窗内只累计 ×N，不再逐条新开。"""
    log_fn = _fn(js, "sbLog")
    assert "THROTTLE_MS" in log_fn and "ENTRIES.find" in log_fn and "(e.n > 1 ? '×' + e.n" in log_fn
    # 交易时段感知降级：kplInTradeSession 粗粒度时段仅用于日志分级
    assert "kplInTradeSession" in js, "非交易时段连接错误降级 helper 缺失"
    kb = _fn(js, "kplBanner")
    assert "kplInTradeSession()" in kb and "sbLog(lv" in kb, "kplBanner 未按交易时段分级"
    # 双发归一：CMD_ERROR 两种序列化形态归一为 code+msg 主键
    assert "kplErrKey" in _fn(js, "kplBanner"), "server error 双发未归一"


def test_banner_errors_routed_to_status_bar(js: str):
    """2026-10-30 用户需求：各视图连接/服务端报错横幅同步进底部状态栏（非浏览器 console）。"""
    routed = {
        'kplBanner': '[板块行情]', 'lbBanner': '[连板行情]', 'kplLiveBanner': '[直播]',
        'kplDabanBanner': '[涨停复盘]', 'kplLhbBanner': '[龙虎榜]',
    }
    for fn_name, tag in routed.items():
        body = _fn(js, fn_name)
        assert 'sbLog(' in body and tag in body, f"{fn_name} 未挂接状态栏（缺 {tag} 前缀）"
    # render 类错误分支（读口异常/降级）同样透出（下跌/上涨复盘用 tag 常量 + sbLog 变量调用）
    for tag in ('[题材龙头]', '[板块节点]', '[盘中红盘]'):
        assert f"sbLog('error', '{tag}" in js or f"sbLog('warn', '{tag}" in js, f"{tag} 报错分支未挂状态栏"
    for tag in ('[下跌复盘]', '[上涨复盘]'):
        assert f"'{tag} '" in js and "sbLog('error', tag" in js, f"{tag} 报错分支未挂状态栏"


def test_kpl_banner_only_errors_not_ok(js: str):
    """kplBanner 正常提示（kind='ok'）不上报，只上报 error/warn/info 路径。"""
    body = _fn(js, "kplBanner")
    assert "if (kind !== 'ok'){" in body and "sbLog(lv" in body, "ok 提示不得进错误状态栏"


def test_error_banners_suppressed_page_side(js: str):
    """2026-10-30 用户裁决：报错横幅页内删除，底部状态栏单一出口。

    保留页内的只有：ok 正常提示、口径/降级说明条（dbRenderBanner msgs）、
    无数据中性提示、带重试按钮的存档拉取失败卡。
    """
    kb = _fn(js, "kplBanner")
    assert "if (kind !== 'ok'){ el.style.display = 'none'" in kb, "kplBanner 报错不得页内显示"
    for fn_name, tag in (("lbBanner", "[连板行情]"), ("kplDabanBanner", "[涨停复盘]"),
                         ("kplLhbBanner", "[龙虎榜]"), ("kplLiveBanner", "[直播]")):
        body = _fn(js, fn_name)
        assert "sbLog(" in body and tag in body, f"{fn_name} 须上报状态栏"
        assert "lf-warn" not in body and "✘" not in body, f"{fn_name} 不得再渲染报错横幅"
    tl = _fn(js, "tlRenderBanner")
    assert "题材龙头读口异常：" not in tl and "后台刷新失败（" not in tl, "tl 黄条须删除"
    pulse = _fn(js, "pulseRender")
    assert "读口异常：" not in pulse and "读口降级：" not in pulse, "pulse 黄条须删除"
