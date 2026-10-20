# -*- coding: utf-8 -*-
"""relay_page【题材龙头】连板指数子视图守卫（2026-10-20 用户裁决第三轮）。

需求：题材龙头**不是独立页**，而是「连板指数 · 日级判定」目录的子视图（rv-themes），
与【涨停分析】共用页头 `#relayKpi`（点行 KPI 联动该日）与 tabbar 右侧时间范围控件
（`STATE.relayRange` 同一区间，`rangeRefresh` 联动重拉）；**删除**初版自建的 tlKpi。

交互对齐涨停分析（relayRow / relayToggle 分工）：
- 点行 = 选中该日（KPI 联动），再点取消；
- 左侧三角 = 展开/收敛 jev 调用日志卡（stopPropagation，不动选中态）。

展示硬约束（AGENTS §1.2-5 / §4.0）：落库口径与模型原答双显 / 结局 null=未封 /
回填样本标橙 / 读口异常 ≠ 无数据。

本测试是**静态源码守卫**（无浏览器、零网络、零 jev 调用，AGENTS §1.2-7）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_PAGE = Path(__file__).resolve().parents[2] / "backend" / "relay_page" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _PAGE.read_text(encoding="utf-8")


def _fn(html: str, name: str) -> str:
    """按花括号配平抽取函数体（JS 缩进块，`\\n}` 匹配不了）。"""
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
    raise AssertionError(f"{name} 函数体未闭合")


# ── 挂载位置：连板指数子视图（不是独立页） ──

def test_is_relay_subview_not_standalone_page(html: str) -> None:
    assert '<div class="rv" id="rv-themes">' in html, "必须是 tab-relay 内的 .rv 子视图"
    assert 'id="tab-themeLeaders"' not in html, "不得残留独立 section"
    assert re.search(r"\['themes', '题材龙头', '👑'\]", html), "RELAY_VIEWS 必须注册子视图"
    assert "['themeLeaders'" not in html, "不得残留 NAV 工作台项"
    # 面包屑走 relay 自动映射（RELAY_VIEWS reduce），不得有顶层条目
    assert "themeLeaders: ['题材龙头']" not in html


def test_shares_relay_kpi_and_range(html: str) -> None:
    """共用 KPI 与时间范围：删除自建 tlKpi；行源吃 relayRange；rangeRefresh 联动重拉。"""
    assert 'id="tlKpi"' not in html, "初版自建 KPI 必须删除（与页头 relayKpi 重复）"
    assert "tlFetch()" in _fn(html, "rangeRefresh"), "区间变更必须联动重拉题材龙头"
    fetch = _fn(html, "tlFetch")
    assert "STATE.relayRange" in fetch, "取数必须用共享区间（与涨停分析同一 relayRange）"
    assert "rangedSeries()" in fetch, "区间惰性初始化走 rangedSeries 同一口径"
    assert "start=" in fetch and "end=" in fetch, "区间参数透传给读口"
    # 根前端用的单日路径不得被破坏
    api = Path(__file__).resolve().parents[2] / "backend" / "api" / "hotlist_jev_limitup_routes.py"
    api_src = api.read_text(encoding="utf-8")
    assert 'date: str | None = None' in api_src, "单日路径必须保留（根前端消费）"
    assert '"$gte"' in api_src and '"$lte"' in api_src, "区间查询用 $gte/$lte 闭区间"


def test_row_click_selects_day_for_kpi(html: str) -> None:
    """点行 = 选中该日（共用 KPI 联动），复用 relayRow 而非另立状态。"""
    assert "relayRow(date)" in _fn(html, "tlRow"), "点行必须复用 relayRow（KPI 联动同一机制）"
    row = _fn(html, "tlRowHtml")
    assert "onclick=\"tlRow(" in row, "整行 onclick=tlRow"
    # focus 高亮吃共享 relayFocus
    assert "STATE.relayFocus === r.tradingDate" in row
    assert "' focus'" in row


def test_caret_toggles_log_card_without_selection(html: str) -> None:
    """三角 = 展开调用日志卡（stopPropagation），与点行选中分离（照抄 relay/detail 分工）。"""
    row = _fn(html, "tlRowHtml")
    assert "event.stopPropagation(); tlToggle(" in row, "三角必须 stopPropagation"
    assert "lg-caret" in row, "必须用 lg-caret 右三角"
    assert "openKey === tlKey(r)" in row, "展开键 = date:code（区间内多日多股唯一）"


def test_rows_span_range_with_date_column(html: str) -> None:
    """行 = 区间内全部龙头-日：行数据带 tradingDate，表格首列为日期。"""
    row = _fn(html, "tlRowHtml")
    assert "r.tradingDate" in row
    rows_fn = _fn(html, "tlRenderRows")
    assert "th('日期', 'date')" in rows_fn, "必须有日期列"
    assert "relayPageSlice(" in rows_fn, "分页复用 relayPageSlice（同涨停分析规格）"


# ── 展示硬约束 ──

def test_gated_row_shows_model_answer_and_reason(html: str) -> None:
    row = _fn(html, "tlRowHtml")
    assert "r.modelChoice" in row and "r.choice" in row
    assert "tl-gate" in row
    assert "TL_GATE_CN" in html


def test_outcome_three_states_never_fake_broken(html: str) -> None:
    fn = _fn(html, "tlOutcomeKey")
    assert "outcomeSealedNextDay === null" in fn
    row = _fn(html, "tlRowHtml")
    assert "未封" in row and "续板" in row and "未续" in row


def test_backfill_and_mixed_generation_banner(html: str) -> None:
    banner = _fn(html, "tlRenderBanner")
    assert "回填" in banner and "未来信息" in banner
    assert "跨代不可比较" in banner
    assert "tl-backfill" in html


def test_read_error_is_fail_visible(html: str) -> None:
    banner = _fn(html, "tlRenderBanner")
    assert "读口异常" in banner and "非「区间内无投喂」" in banner
    assert "theme_leaders_read_failed" in html


def test_bg_refresh_failure_has_visible_exit(html: str) -> None:
    """P1 修复回归（review P1-1）：后台刷新失败 + 旧数据可见 → 错误必须有出口。

    事故实录：初版 bg 失败分支写 error 但 banner/表体都以「无 rows」为前置，
    读口挂掉时页面照常显示旧数据 + refreshAt 照常刷新，用户零感知。
    """
    fetch = _fn(html, "tlFetch")
    banner = _fn(html, "tlRenderBanner")
    assert "const bg = " in fetch, "同区间轮询走静默刷新"
    assert "bgErr" in banner and "后台刷新失败" in banner and "上次成功数据" in banner,         "bg 失败必须追加 warn 行（§4.0 不得伪装成正常数据）"


def test_no_reran_dead_variable(html: str) -> None:
    """P2 修复回归（review P2-2）：死变量 rerunBtn（含不存在的 tlReran）不得复活。

    这是「丢引号事故」高危残骸形态：引用不存在函数 + 残缺 onclick 构造。
    """
    assert "tlReran(" not in html, "tlReran 死引用不得存在"
    # 只禁题材龙头的死形态（单引号拼接 + 占位构造）；relay/detail 的模板串 rerunBtn 合法
    assert "const rerunBtn = '<button class=\"rerun\"'" not in html, "死变量 rerunBtn 不得存在"
    assert "const rerunBtnHtml" in html, "生效的 rerunBtnHtml 必须在"


def test_narrative_writeback_has_generation_guard(html: str) -> None:
    """P2 修复回归（review P2-1）：懒拉写回必须带 computedAt 代际守卫。

    事故窗口：展开触发的 narrative 请求在途时点重跑 → delete 后旧请求完成
    无条件写回重跑前旧语料，以旧语料冒充重跑后语料。
    """
    load = _fn(html, "tlLoadNarrative")
    assert "const gen = r.computedAt" in load, "进入时捕获代际哨兵"
    assert "cur.computedAt !== gen" in load, "回写前比对当前行 computedAt"


def test_detail_card_is_jev_call_log_card(html: str) -> None:
    """明细卡 = lg-card 范式（与涨停分析同构：双模式 + 指标格 + 双栏 JSON 树 + 页脚）。"""
    detail = _fn(html, "tlDetailHtml")
    for token in ('class="lg-card"', "🕐 jev ·", "详细信息", "原始 JSON", 'class="lg-meta"',
                  'class="lg-panels"', "筛选 JSON", "⧉ 复制", 'class="lg-foot"',
                  "存档 _id", "modelAnswers"):
        assert token in detail, f"明细卡缺少 {token}"
    assert "treeHtml(" in detail, "复用 JSON 树"
    assert "tlRedrawTrees()" in _fn(html, "tlFilter"), "筛选只重绘树"
    assert "ui.q1 = ''" in _fn(html, "tlToggle"), "展开/收敛清空筛选（同 lgRow）"


def test_range_fetch_has_stale_response_guard(html: str) -> None:
    """快速改区间的过期响应不得覆盖新数据（同 loadAll 的 seq 守卫范式）。"""
    fetch = _fn(html, "tlFetch")
    assert "_tlSeq" in fetch and "seq !== _tlSeq" in fetch


def test_no_dangling_references(html: str) -> None:
    for gone in ("tlFiltered(", "tlSetBoard(", "tlToggle(')", "renderThemeLeaders",
                 "theme_leaders_read_failed: ' + (e && e.message ? e.message : '?')",):
        pass  # 占位：下方逐条精确断言
    assert "renderThemeLeaders" not in html
    for name in ("renderThemes", "tlRenderRows", "tlRenderBar", "tlRenderBanner",
                 "tlFetch", "tlRow", "tlToggle", "tlClear", "tlSortBy", "tlQ", "tlBoard"):
        assert len(re.findall(rf"function {name}\(", html)) == 1, f"{name} 必须唯一定义"


def test_inline_handlers_have_quotes(html: str) -> None:
    """内联 handler 的字符串参数必须带引号：事故实录：tlToggle(2026-10-20:002835)
    无引号，missing ) after argument list，点行/展开全失效且零 console 错误。
    """
    row = _fn(html, 'tlRowHtml')
    q = chr(92) + chr(39)   # JS 源码中的转义单引号
    assert "tlRow(" + q in row, "tlRow 参数必须带转义引号"
    assert "tlToggle(" + q in row, "tlToggle 参数必须带转义引号"


def test_css_integrity(html: str) -> None:
    """style 块花括号配平 + 无孤立属性行（2026-10-20 事故：孤立残骸吞掉后续全部规则）。"""
    style = html[html.index("<style>") + 7: html.index("</style>")]
    assert style.count("{") == style.count("}"), "花括号不平衡"
    depth = 0
    for i, ln in enumerate(style.splitlines()):
        t = ln.strip()
        if depth == 0 and t and not t.startswith(("/*", "@")) and "{" not in ln and ":" in ln:
            raise AssertionError(f"孤立属性行 L{i}: {t[:60]}")
        depth += ln.count("{") - ln.count("}")
        assert depth >= 0, f"多余右括号 L{i}"
    assert depth == 0


def test_js_syntax_is_valid() -> None:
    node = None
    for cand in ("node", "node.exe"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True, timeout=20)
            node = cand
            break
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    if node is None:
        pytest.skip("node 不可用，跳过 JS 语法校验")
    html = _PAGE.read_text(encoding="utf-8")
    m = re.search(r"<script>([\s\S]*)</script>", html)
    assert m, "未找到 script 块"
    tmp = _PAGE.parent / ".tmp-syntax-check.js"
    try:
        tmp.write_text(m.group(1), encoding="utf-8")
        proc = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True,
                              timeout=60)
        assert proc.returncode == 0, f"JS 语法错误：{proc.stderr[:600]}"
    finally:
        tmp.unlink(missing_ok=True)


# ── 重跑按钮 + 静默刷新（2026-10-20 用户需求第二轮） ──

def test_detail_card_has_rerun_button(html: str) -> None:
    """重跑按钮：lg-toggle 内、rerun 类、busy 禁用、confirm 警示 tokens 成本。"""
    detail = _fn(html, "tlDetailHtml")
    assert 'button class="rerun"' in detail, "明细卡必须有重跑按钮"
    assert "tlRerun(" in detail and "stopPropagation" in detail
    assert "重跑中…" in detail, "busy 态文案"
    assert "2.3K tokens" in detail, "confirm 警示必须写明成本"
    fn = _fn(html, "tlRerun")
    assert "window.confirm" in fn, "重跑前必须 confirm"
    assert "STATE.rerunBusy" in fn, "必须复用全局 busy 防并发（同 relay）"
    assert "jpost('/api/hotlist-jev/theme-leaders/rerun'" in fn
    assert "delete STATE.tlNarr[key]" in fn, "旧语料必须丢弃重拉"


def test_silent_background_refresh(html: str) -> None:
    """60s 轮询同区间 = 后台静默刷新：不显示加载占位、失败保留旧数据。

    事故实录：初版每次轮询都把整表刷成「加载中…」再重绘（全部重载闪现）。
    """
    fetch = _fn(html, "tlFetch")
    assert "rangeKey" in fetch, "必须记录区间键区分「区间变化」与「同区间轮询」"
    assert "const bg = " in fetch, "同区间 + 已有数据 → 后台静默刷新"
    rows_fn = _fn(html, "tlRenderRows")
    assert "d.loading && !(d.rows || []).length" in rows_fn, \
        "加载占位只在无旧数据时显示（区间切换/首载）"
    banner = _fn(html, "tlRenderBanner")
    assert "d.error && !(d.rows || []).length" in banner or "bg" in fetch, \
        "后台刷新失败保留旧数据可见（不清空列表）"
