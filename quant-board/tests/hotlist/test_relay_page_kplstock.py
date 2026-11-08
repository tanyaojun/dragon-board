# -*- coding: utf-8 -*-
"""relay_page【个股行情】单页化守卫（2026-11-08 用户需求）。

需求：工作台「KPL 行情」下原六入口（集合竞价/即将涨停/风向标/涨停池/炸板池/跌停池）
合并为**一个【个股行情】页**——左板块列表不变，右个股列表左上方按钮切换模式。

本测试是**静态源码守卫**（无浏览器、零网络、零 jev 调用，AGENTS §1.2-7）：
保证「六页是否又被拆回独立侧栏入口」「六套渲染器是否仍写各自 DOM 前缀（导致共用面板
只有第一种模式能渲染）」这类回退能被立即发现。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_PAGE = Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html"
_OLD_PAGES = ["kplbid", "kplsoon", "kplvane", "kplzt", "kplzb", "kpldt"]
_MODE_TITLES = ["集合竞价", "即将涨停", "风向标", "涨停池", "炸板池", "跌停池"]


@pytest.fixture(scope="module")
def html() -> str:
    return _PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js(html: str) -> str:
    m = re.search(r"<script>([\s\S]*)</script>", html)
    assert m, "relay_page 应含唯一 <script> 块"
    return m.group(1)


def _fn(js: str, name: str) -> str:
    """取一个顶层函数文本（花括号配对截断，不向下一个函数溢出）。"""
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


def test_sidebar_has_single_kplstock_entry(js: str):
    nav = js[js.index("const NAV = ["): js.index("// ════", js.index("const NAV = ["))]
    assert "['kplstock', '个股行情'" in nav
    for old in _OLD_PAGES:
        assert f"'{old}'" not in nav, f"旧独立页入口回退：{old}"
    crumb = js[js.index("const VIEW_CRUMB = {"): js.index("function renderSidebar")]
    assert "kplstock: ['个股行情']" in crumb
    for old in _OLD_PAGES:
        assert f"{old}: [" not in crumb, f"VIEW_CRUMB 仍保留旧页键：{old}"


def test_single_section_with_shared_dom(html: str):
    assert html.count('<section id="tab-kplstock"') == 1
    for old in _OLD_PAGES:
        assert f'id="tab-{old}"' not in html, f"旧页面 section 回退：tab-{old}"
        assert f"#tab-{old} " not in html, f"CSS 仍引用旧页面：tab-{old}"
    # 六模式共用一套 DOM（左表/右表/统计/日期/横幅/两处过滤框）
    for el in ["kplStockModeBtns", "kplStockPlateTable", "kplStockStockTable", "kplStockStats",
               "kplStockDate", "kplStockBanner", "kplStockPlateSearch", "kplStockSearch", "kplStockSource"]:
        assert html.count(f'id="{el}"') == 1, f"{el} 应唯一存在（共用 DOM）"


def test_daban_pages_share_kplstock_prefix(js: str):
    pages = js[js.index("const DABAN_PAGES = {"): js.index("let kplDabanPoll")]
    assert pages.count("p: 'kplStock'") == len(_OLD_PAGES)
    for old, prefix in [("kplbid", "kplBid"), ("kplsoon", "kplSoon"), ("kplvane", "kplVane"),
                        ("kplzt", "kplZt"), ("kplzb", "kplZb"), ("kpldt", "kplDt")]:
        assert f"p: '{prefix}'" not in pages, f"{old} 仍写独立 DOM 前缀 {prefix}"


def test_mode_buttons_order_and_default(js: str):
    views = re.search(r"const DABAN_VIEWS = \[([^\]]*)\];", js)
    assert views, "缺 DABAN_VIEWS"
    order = re.findall(r"'([a-z]+)'", views.group(1))
    assert order == _OLD_PAGES, f"DABAN_VIEWS 顺序={order}（按钮序=用户列表序）"
    titles = re.findall(r"title: '([^']+)'", js[js.index("const DABAN_PAGES = {"): js.index("let kplDabanPoll")])
    assert titles[:len(_MODE_TITLES)] == _MODE_TITLES, f"模式标题={titles}"
    page = re.search(r"const DABAN_PAGE = '([a-z]+)';", js)
    assert page and page.group(1) == "kplstock"
    default = re.search(r"const DABAN_DEFAULT_MODE = '([a-z]+)';", js)
    assert default and default.group(1) in _OLD_PAGES, "默认模式必须是六模式之一"
    chrome = _fn(js, "kplStockChrome")
    assert "DABAN_VIEWS.map(" in chrome and "kplStockModeBtns" in chrome, "按钮应由 DABAN_VIEWS 单一来源生成"
    # 进页按当前模式（首次=默认模式）取快照
    setview = _fn(js, "setView")
    assert "kplDabanEnter(KPL.dabanView || DABAN_DEFAULT_MODE)" in setview


def test_daban_on_guard_used_by_all_modes(js: str):
    on = _fn(js, "dabanOn")
    assert "STATE.view === DABAN_PAGE && KPL.dabanView === view" in on
    for name in ["kplDabanRender", "kplZtRender", "kplPoolRender", "kplBidRender"]:
        body = _fn(js, name)
        assert "dabanOn(" in body, f"{name} 未用模式守卫（切模式会写到旧面板）"
    assert "STATE.view !== view" not in js and "STATE.view === view" not in js, "仍残留单页化前的视图守卫"
    # 涨停池专属拉取（排行/2203 原因/档案懒取）只在涨停池为当前模式时重渲染
    for name in ["kplZtEnsureReasons", "kplZtArchPump"]:
        assert "dabanOn('kplzt')" in _fn(js, name)


def test_poll_and_ws_only_trigger_current_mode(js: str):
    enter = _fn(js, "kplDabanEnter")
    assert "STATE.view !== DABAN_PAGE" in enter, "轮询存活判据应只认单页"
    assert "kplDabanFetch(KPL.dabanView)" in enter, "轮询应只拉当前模式"
    assert "kplStockChrome()" in enter, "进页/切模式应回填按钮态与日期框"
    ws = js[js.index("case 'daban_stocks'"):]
    ws = ws[: ws.index("break;")]
    assert "STATE.view === DABAN_PAGE" in ws and "DABAN_PAGES[KPL.dabanView].pid" in ws


def test_mode_switch_isolation(js: str):
    sw = _fn(js, "kplStockSetMode")
    assert "KPL.dabanView = mode" in sw
    for el in ["kplStockPlateSearch", "kplStockSearch"]:
        assert el in sw, f"切模式应清空瞬时过滤词：{el}"
    assert "kplDabanEnter(mode)" in sw and "kplRenderMarketKpi()" in sw
    # 历史逐日回退只在当前模式回填共享日期框
    arch = _fn(js, "kplDabanArchiveHistory")
    assert "dabanOn(view) && $(conf.p + 'Date')" in arch, "非当前模式的回退不应覆盖共享日期框"


def test_kpi_date_follows_current_mode(js: str):
    kpi = _fn(js, "kplKpiDate")
    assert "STATE.view === DABAN_PAGE" in kpi
    assert "KPL.dabanMode[v] === 'history'" in kpi and "KPL.dabanDate[v]" in kpi
    assert "DABAN_VIEWS.includes(STATE.view)" not in kpi, "KPI 日期不应再按旧独立页键取"


def test_live_no_snapshot_falls_back_to_local_archive(html: str, js: str):
    """实时读口无 2103 快照时不得把页面烘成空白（AGENTS §4.0）：
    回退本地日档（≤7 天）并显式标注回退交易日，轮询继续跑实时。"""
    assert "dabanFallback: {}" in js, "缺回退标记状态"
    fb = _fn(js, "kplDabanLiveFallback")
    assert "DABAN_ARCHIVE_VIEWS.includes(view)" in fb, "无存档通道的视图（即将涨停/风向标）不应冒领回退"
    assert "snap.ok" in fb and "snap.fromArchive" in fb, \
        "已有实时帧优先展示；历史态写入的存档快照不得挡住回退（评审 R3-P1，防存档伪装成实时）"
    assert "Date.now() - fb.at < 60000" in fb, "4s 轮询下回退扫档需节流（评审 R3-P2：断言节流表达式本身）"
    assert "{fallback: true" in fb, "应复用逐日回退存档链并带 fallback 标记"
    fetch = _fn(js, "kplDabanFetch")
    assert "kplDabanLiveFallback(view, r)" in fetch and "!hist" in fetch
    assert "KPL.dabanFallback[view] = null" in fetch, "实时恢复后应清回退标记"
    assert "dabanFetching[view]" in fetch and "finally" in fetch, \
        "拉取需在飞互斥且保证释放（评审 R3-P2：WS 触发与轮询不并发扫档）"
    # 逐日回退：回退态不改历史选日/日期框（仍算实时），只记录回退日
    arch = _fn(js, "kplDabanArchiveHistory")
    assert "opts" in arch and "fallback" in arch
    assert "KPL.dabanFallback[view] = r.ok" in arch
    assert "back && !fallback" in arch, "回退态不得回填历史选日（否则被当成历史模式停轮询）"
    assert "fromArchive = true" in arch, "存档写入需打标（回实时后不被当实时帧）"
    # 统计行/页头显式标注回退日，不伪装「实时」；标注随历史态门控
    label = _fn(js, "kplDabanModeLabel")
    assert "回退存档" in label and "dabanFallback" in label
    for name in ["kplDabanRender", "kplZtRender", "kplPoolRender", "kplBidRender"]:
        assert "kplDabanModeLabel(" in _fn(js, name), f"{name} 统计行未用回退标签"
    chrome = _fn(js, "kplStockChrome")
    assert "回退存档" in chrome, "页头数据源应标注回退日"
    assert "dabanMode[view] !== 'history'" in chrome, "页头回退标注需随历史态门控（评审 R3-P2）"
    assert "kplStockChrome()" in _fn(js, "kplDabanDateChange"), "切历史需刷页头（评审 R3-P2）"


def test_degraded_banner_throttled(js: str):
    """同一降级消息不得被 4s 轮询刷成数十条状态栏错误（2026-11-08 现场 22 条）。"""
    assert "dabanBannerAt: {}" in js
    banner = _fn(js, "kplDabanBanner")
    assert "KPL.dabanBannerAt[key]" in banner and "60000" in banner