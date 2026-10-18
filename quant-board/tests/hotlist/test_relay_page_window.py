# -*- coding: utf-8 -*-
"""relay_page 判定明细页前端守卫测试（2026-10-18 用户裁决版）。

需求（浏览器页 http://127.0.0.1:8008 · 判定明细页）：
1. 日期区间控件回到「两个日期控件 + 近1月/近3月/全部三个按钮」原生形态，
   位置在**页头**；删除临时加的 4 日期 / 1 按钮 / 按钮后的文字说明控件。
2. 明细表删除 tokens / 判定时间两列，新增「龙头强度」列。
3. 表头筛选新增「分区」「龙头强度」两个下拉。
4. 「判定明细」标题后不再有大段文字说明；标题字号与其他页一致（不放大）。
5. 点列表行 → 页头 KPI 卡联动到该日；KPI 第三行改为**档位描述**（该档位意味着什么），
   不再显示「量化比率口径」这类统计口径文字。

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
    assert 'colspan="9"' in rt, "展开详情行 colspan 应为 9"
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
def test_detail_head_has_no_long_description(html: str):
    """判定明细页头只有 h2（无 <p> 长说明），且 h2 不单独放大。"""
    seg = html[html.index('id="rv-detail"'):]
    seg = seg[: seg.index("</section>")]
    head = seg[: seg.index('class="ph-line"')]
    assert "<p" not in head, "页头不应再有大段文字说明"
    # 字号：与其它页共用 .page-head h2（20px），不额外覆盖
    assert "font-size" not in head.split("<h2")[1].split(">")[0]


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
               "diagBands", "diagZones", "diagCorr", "diagProvenance",
               "diagWarn", "bandCmd", "phaseMatrix"):
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
