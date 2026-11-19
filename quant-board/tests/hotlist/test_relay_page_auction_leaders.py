# -*- coding: utf-8 -*-
"""relay_page【竞价龙头】子视图静态守卫（vA1；无浏览器零网络零 jev）。

需求（预登记 auction-leader-vA1 §6）：竞价龙头为连板指数子视图 rv-auction（不是独立页），
与 rv-themes 同构：共用页头 KPI 与时间范围控件、60s 静默轮询、叙事抽屉、重跑按钮、
推送缺席/竞价缺徽章；行源 = labels ∪ 推送 roster（labelMissing 不进表）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_PAGE = Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _PAGE.read_text(encoding="utf-8")


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
    raise AssertionError(f"function {name} unbalanced")


def test_subview_section_and_tab(html):
    assert '<div class="rv" id="rv-auction">' in html
    assert "['auction', '竞价龙头', '⚡']" in html
    for el in ("alBoardRow", "alFilterBar", "alTable"):
        assert f'id="{el}"' in html
    # 2026-11-13 用户裁决：报错/缺档信息不打页内横幅，收底部状态栏
    assert 'id="alBanner"' not in html and 'id="tlBanner"' not in html
    assert "leaderStatusNotice('[竞价龙头] '" in _fn(html, "alRenderBanner")
    helper = _fn(html, "leaderStatusNotice")
    assert "sbLog(level, msg)" in helper and "no_data" in helper
    assert "lf-warn" not in helper, "状态栏路由不得回渲染页内黄条"


def test_fetch_wired_to_range_and_loadall(html):
    assert html.count("alFetch();") >= 2          # loadAll + rangeRefresh
    body = _fn(html, "alFetch")
    assert "/api/hotlist-jev/auction-leaders" in body
    assert "STATE.relayRange" in body             # 共用时间范围
    assert "_alSeq" in body                       # seq 守卫防过期响应


def test_labelmissing_rows_not_in_table(html):
    body = _fn(html, "alRows")
    assert "labelMissing" in body


def test_detail_card_and_rerun(html):
    detail = _fn(html, "alDetailHtml")
    assert "lg-card" in detail and "alRerun" in detail
    rerun = _fn(html, "alRerun")
    assert "/api/hotlist-jev/auction-leaders/rerun" in rerun
    assert "STATE.rerunBusy" in rerun             # 全局防并发烧 token
    narr = _fn(html, "alLoadNarrative")
    assert "with_narrative=1" in narr


def test_absence_badges_fail_visible(html):
    row = _fn(html, "alRowHtml")
    assert "推送缺席" in row and "竞价缺" in row
    assert "待结算" in row                        # 结局 null=待结算，不伪装未封


def test_morning_badge_removed_20261115(html):
    """2026-11-15 用户裁决：早报行内缺席徽章移除（视觉噪声）；morningState 仍留
    corpusState（明细卡原始 JSON）与叙事节，fail-visible 不丢。守卫防徽章回潮。"""
    row = _fn(html, "alRowHtml")
    assert "morningBad" not in row and '">早报' not in row


def test_flash_badge_removed_20261115(html):
    """2026-11-15 用户裁决：快讯行内缺席徽章移除；flashState 仍留 corpusState/叙事。"""
    row = _fn(html, "alRowHtml")
    assert "flashBad" not in row and '">快讯' not in row


def test_choice_cn_and_midpoints(html):
    assert "AL_CHOICE_CN" in html and "AL_MIDPOINTS" in html
    m = re.search(r"const AL_MIDPOINTS = \{([^}]+)\}", html)
    assert m, "AL_MIDPOINTS 常量必须在场"
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location(
        "al_eval", Path(__file__).resolve().parents[2] / "scripts" / "auction_leader_pilot_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    front = json.loads("{" + re.sub(r"([A-Za-z_][A-Za-z0-9_]*):", r'"\1":', m.group(1)) + "}")
    assert front == mod.MIDPOINTS, "前端中值与后端 Brier 中值逐键全等（防漂移）"
    assert "AL_MIDPOINTS" in _fn(html, "alProb")


def test_status_bar_routing_and_nits(html):
    """2026-11-13 裁决 + review nits：报错收状态栏 / 页码重置 / 门中文 / 重跑预算披露。"""
    assert "STATE.alUi.page = 1" in _fn(html, "rangeRefresh")
    assert "TL_GATE_CN" in _fn(html, "alDetailHtml")
    assert "2 次 jev 调用" in _fn(html, "alRerun"), "confirm 须披露板块连带重烧"


def test_dragon_source_removed_vA4(html):
    """vA4（2026-11-15 用户裁决）：韭研龙序第二源退役——韭研龙徽章/龙序/领涨列移除；
    推送缺席徽章保留（仅推送源行）。守卫防回潮。"""
    body = _fn(html, "alRowHtml")
    assert "jiuyan_dragon_t1" not in body and "韭研龙" not in body
    assert "dragonBad" not in body and "r.dragonRoles" not in body
    assert "alLeadRole" not in body and "leadCell" not in body
    assert "srcs.includes('auction_push')" in body


def test_auction_column_count_vA4(html):
    """vA4 删领涨列后竞价表 14 列：表头无领涨、colspan 同步 14（防列数漂移）。"""
    head = _fn(html, "alRenderRows")
    assert "th('领涨'" not in head
    assert 'colspan="14"' in head and 'colspan="15"' not in head
    row = _fn(html, "alRowHtml")
    assert 'colspan="14"' in row and 'colspan="15"' not in row


def test_event_cell_single_source_with_theme(html):
    """2026-11-14 复刻：事件格 = evidenceCellHtml 单源，题材/竞价两页共用同一实现
    （防两处徽章口径漂移）；两页行渲染都必须经它出事件列。"""
    assert html.count("function evidenceCellHtml(") == 1, "事件格必须单一定义（单源）"
    assert "evidenceCellHtml(r, r.tradingDate)" in _fn(html, "tlRowHtml"), "题材龙头行必须经共用事件格（监管徽章=当日档，2026-11-15）"
    assert "evidenceCellHtml(r, (r.corpusState || {}).prevDate)" in _fn(html, "alRowHtml"), "竞价龙头行必须经共用事件格（监管徽章=T−1 收盘档，不跨日归因）"
    ev = _fn(html, "evidenceCellHtml")
    assert "r.evidenceEventTitles" in ev and "r.evidenceNewsTitles" in ev and "r.evidenceKwordTags" in ev, "事件/新闻/题材三徽章同源消费"


def test_trial_strength_source_badge_20261115(html):
    """第三源徽章（预登记 auction-leader-trial-strength-source-preregistration-20261115）：
    「竞价强度」源徽章 title 披露 jj_ratio/板内排名（esc 注入）；推送缺席徽章仅推送源行
    （trial 单源股推送缺席是预期态，不告警——srcs.includes('auction_push') 门控沿用）。"""
    body = _fn(html, "alRowHtml")
    assert "auction_trial_strength" in body and "竞价强度" in body
    assert "r.trialStrength" in body, "title 必须由 trialStrength 拼装 jj_ratio/板内排名"
    assert "esc(trialTxt" in body, "强度 title 注入前必须 esc"
    assert "trialBad" in body


def test_at_live_is_today_backfill_not_history(html):
    """评审 P1 回潮守卫：程序回填（当日值）不得隐藏实时区；仅显式选历史日才隐藏。"""
    body = _fn(html, "atLiveIsToday")
    assert "if (sel) return false" not in body, "vA4 前旧门控（回填即隐藏）禁止回潮"
    assert "sel === today" in body, "门控必须是「选中日 == 今日」比较"


def test_series_section_wired_into_detail(html):
    """竞价过程事实节：读口消费方接线（2026-11-17 起序列产出后生效）。"""
    detail = _fn(html, "alDetailHtml")
    assert "alSeriesSectionHtml(r)" in detail, "明细卡必须挂竞价过程节"
    body = _fn(html, "alSeriesSectionHtml")
    assert "alSeriesEnsure" in _fn(html, "alToggle"), "展开行时必须惰性拉取序列档"
    assert "auction-bidding-series" in _fn(html, "alSeriesEnsure")
    # 缺席必须如实展示（fail-visible，不补 0/不隐藏）
    assert "序列档缺席" in body and "doc.reason" in body
    assert "无该股 tick" in body
    # 观测值非判据口径留在 title 提示，不进行文
    assert "观测值非判据" in body


def test_series_cache_no_refetch(html):
    body = _fn(html, "alSeriesEnsure")
    assert "if (cur && !cur.loading) return" in body, "结果态按日缓存，防重复外呼"


def test_trial_two_pct_columns_20261118(html):
    """竞价涨幅(0915)/开盘涨幅(0925) 两列拆分守卫——映射/表头/排序键/业务语义 tooltip。
    2026-11-19 用户裁决：逐行源子标签删除（画蛇添足致字段溢出）；tooltip 改业务语义。"""
    fn = _fn(html, "atRender")
    assert "aucPctN: atNum(r.pct0915)" in fn
    assert "openPctN: atNum(r.pct0925)" in fn and "openPrN: atNum(r.p0925)" in fn
    assert "lbThSort('竞价涨幅', 'aucPctN'" in fn
    assert "lbThSort('开盘涨幅', 'openPctN'" in fn
    assert "开盘涨幅＝09:25 集合竞价撮合开盘价相对昨收的涨幅" in fn
    assert "stockSort: {key: 'aucPctN', dir: -1}" in html, "默认排序键与竞价涨幅列一致"
    assert "openSrc: r.open0925Src" in fn
    assert "open0925TdxN" in fn, "页头 0925 覆盖计数含 TDX 兜底档（fail-visible）"
    # 子标签已删（用户裁决）：单元格只留值，不再渲染源标签
    assert "kpl-sub>首帧" not in fn and "KPL_BID_TRIO_SRC[r.jjTurnoverSrc]" not in fn


def test_trial_board_mean_label_0925(html):
    """左板均值列标签「开盘涨幅均值」（09:25 口径），与右表 09:15 竞价涨幅区分；
    tooltip 业务语义（2026-11-19 用户裁决：去开发术语）。"""
    fn = _fn(html, "atRender")
    assert "lbThSort('开盘涨幅均值', 'pct'" in fn
    assert "竞价涨幅均值" not in fn
    assert "开盘涨幅均值＝板块成员 09:25 开盘涨幅的平均" in fn


def test_trial_null_last_sort(html):
    """review m3：AT 数值排序 null 恒末尾不随方向翻转（新列高缺位率升序不浮顶）。"""
    fn = _fn(html, "atRender")
    assert "(a[skey] ?? null)" in fn and "(b[skey] ?? null)" in fn
    assert "if (va == null) return 1;" in fn and "if (vb == null) return -1;" in fn
    assert "-Infinity" not in fn


def test_trial_state_coverage_in_stats(html):
    """review n4：trialState 0925/0915 覆盖计数进页头（fail-visible 页面层补齐）。"""
    assert "AT.trialState = (r && r.trialState) || null;" in html
    fn = _fn(html, "atRender")
    assert "Type=7终值" in fn and "0915首帧" in fn and "seriesFirst0915N" in fn
    assert "0915存档" not in fn, "0915 死计数器已随 3006 退役删除（review M1）"


def test_bk_name_src_disclosure_20261119(html):
    """bk_name 来源逐股披露，业务语义（同日榜单/前日榜单/竞价推送；2026-11-19 去源编码）。"""
    assert "题材名来源：" in html
    assert "esc(r.bkNameSrc" in html
    assert "同日榜单" in html and "前日榜单" in html and "竞价推送" in html


def test_trial_jj_tooltip_business_semantics_20261119(html):
    """jj 换手/成交额 + start/end tooltip 业务语义（2026-11-19 用户裁决：去开发术语
    pid8/Type=7/投影状态机/源编码；保留观测值/估算/掉池前非最终/缺失不补零口径提示）；
    逐行源子标签删除（致字段溢出）。"""
    fn = _fn(html, "atRender")
    assert "竞价成交额＝09:25 撮合成交金额（元）" in fn
    assert "掉池股取掉池前最后观测值（非最终撮合值）" in fn
    assert "竞价换手＝09:25 撮合成交量占流通股本的比例" in fn
    assert "按成交额÷流通市值估算" in fn
    assert "缺失（不补零）" in fn
    assert "试盘开始＝首次观测到试盘单的时间" in fn
    assert "试盘结束＝最后观测到试盘单的时间" in fn
    # 开发术语退出试盘表 tooltip（源编码映射 KPL_BID_TRIO_SRC 仍供他处 kplBidTrioTip 用）
    assert "投影状态机" not in fn and "dingpan_postmatch" not in fn
    assert "mbl_postmatch" not in fn and "derived_cap" not in fn
    assert "09:25 冻结 bidding_turnover（MBL→bid）优先" not in html
    assert "09:25 冻结 bidding_amount（MBL→bid）优先" not in html
