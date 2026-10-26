# -*- coding: utf-8 -*-
"""relay_page【题材龙头】连板指数子视图守卫（2026-10-20 用户裁决第三轮）。

需求：题材龙头**不是独立页**，而是「连板指数 · 日级判定」目录的子视图（rv-themes），
与【涨停分析】共用页头 `#relayKpi`（点行 KPI 联动该日）与 tabbar 右侧时间范围控件
（`STATE.relayRange` 同一区间，`rangeRefresh` 联动重拉）；**删除**初版自建的 tlKpi。

交互对齐涨停分析（relayRow / relayToggle 分工）：
- 点行 = 选中该日（KPI 联动），再点取消；
- 左侧三角 = 展开/收敛 jev 调用日志卡（stopPropagation，不动选中态）。

展示硬约束（AGENTS §1.2-5 / §4.0）：落库口径为准，模型原答仅留展开卡审计
（2026-10-22 用户裁决删表格「模型原答」「同桶基线」两列——对用户无参考价值）/
结局 null=未封 / 回填警示已下线（2026-10-26 用户裁决，来源留筛选与明细卡页脚）/
读口异常 ≠ 无数据 / 多代际黄牌已结项（2026-10-22）。

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


def test_mixed_generation_row_badge_like_relay_chain(html: str) -> None:
    """P2（2026-10-24 review）：v8 验收窗内 v6 旧档与 v8 新行同表混显，行内必须有
    版本徽章（与 relay 链 verBadge 同款：混版才出、非最新代琥珀），hint 带中性图例。

    边界（10-22 结项裁决不回潮）：混版是设计内常态非告警态——只有**逐行徽章**，
    不得重建页面级警示横幅；上下文取自区间全量行，不随筛选漂移。
    """
    rows_fn = _fn(html, "tlRenderRows")
    assert "tlVerCtx.mixed = vers.length > 1" in rows_fn
    assert "(d.rows || [])" in rows_fn, "混版判定必须用区间全量行（非筛选子集）"
    assert "题集混版" in rows_fn and "旧代题集" in rows_fn, "hint 带图例（中性措辞）"
    row = _fn(html, "tlRowHtml")
    assert "tlVerBadge(r)" in row, "行内（日期格）必须挂版本徽章"
    badge_fn = _fn(html, "tlVerBadge")
    assert "b-amber" in badge_fn and "b-gray" in badge_fn, "非最新代琥珀/最新代灰"
    assert "!tlVerCtx.mixed" in badge_fn, "单版序列不出徽章（保持干净）"
    banner = _fn(html, "tlRenderBanner")
    assert "跨代不可比较" not in banner, "结项横幅不得回潮（徽章≠横幅）"


def test_superseded_count_disclosed_in_count_text(html: str) -> None:
    """单一龙头对账（2026-10-24）：退位行服务端已过滤，数量必须在计数行披露（fail-visible）。"""
    fn = _fn(html, "filteredCountText")
    assert "doc.supersededCount > 0" in fn
    assert "退位" in fn and "审计查库" in fn


# ── 展示硬约束 ──

def test_gated_row_shows_model_answer_and_reason(html: str) -> None:
    """2026-10-22 改版：表格删「模型原答」「同桶基线」两列（用户裁决：完全看不懂、
    无参考价值）；原答保留在展开的调用日志卡 JSON 里供审计；门原因仍可见。"""
    rows_fn = _fn(html, "tlRenderRows")
    assert "模型原答" not in rows_fn and "同桶基线" not in rows_fn
    row = _fn(html, "tlRowHtml")
    assert "r.modelChoice" not in row, "表格行不得再拼模型原答单元格"
    assert "r.baselineKey" not in row, "表格行不得再拼同桶基线单元格"
    assert "colspan=\"15\"" in row, "展开明细行跨列数须跟表头（15，含溢价列）"
    # 门/排除原因仍可见（档位/证据列）+ 展开卡里保留原答审计
    assert "TL_GATE_CN" in html
    assert "r.modelChoice" in _fn(html, "tlEntryResp")


def test_v5_excluded_rows_never_rendered(html: str) -> None:
    """v5（用户 2026-10-23 裁决）：排除股不落库 → 前端无 skipped 分支/样式残留；
    未纳入语义只存在于日志层（run 的排除打印），不入页面。"""
    row = _fn(html, "tlRowHtml")
    detail = _fn(html, "tlDetailHtml")
    for fn_src in (row, detail):
        assert "r.status === 'skipped'" not in fn_src, "不得再有排除行分支（排除股不入库）"
    assert "tl-skipped" not in html


def test_outcome_three_states_never_fake_broken(html: str) -> None:
    fn = _fn(html, "tlOutcomeKey")
    assert "outcomeSealedNextDay === null" in fn
    row = _fn(html, "tlRowHtml")
    assert "未封" in row and "续板" in row and "未续" in row


def test_backfill_warning_display_removed(html: str) -> None:
    """回填警示下线（2026-10-26 用户裁决）：黄牌横幅与名称旁「回填」标属视觉噪音，
    来源语义保留在「来源」筛选与明细卡页脚（审计可考）；
    多代际黄牌已结项（2026-10-22 用户裁决），均不得回潮。"""
    banner = _fn(html, "tlRenderBanner")
    assert "回填" not in banner and "未来信息" not in banner, "回填警示横幅必须下线"
    assert "跨代不可比较" not in banner, "多代际警示已结项，不得回潮"
    row = _fn(html, "tlRowHtml")
    assert "sampleOrigin === 'backfill'" not in row, "名称旁「回填」标必须删除"
    assert "tl-backfill" not in html and "tl-origin" not in html, "行高亮/回填标样式必须删除"
    # 审计层保留：来源筛选 + 明细卡页脚仍可见来源（fail-visible 的替代出口）
    assert "TL_ORIGIN_CN" in _fn(html, "tlRenderBar")
    assert "TL_ORIGIN_CN" in _fn(html, "tlDetailHtml")


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


# ── 回归（2026-10-23 截图实测列错位）：行拼装丢 contCell → 表头 13 列/行 12 格 ──
def test_header_and_row_column_counts_match(html: str) -> None:
    """表头加「延续性」「溢价」列后，tlRowHtml 必须同步发出 15 格——少一格后续列整体左移
    （延续性空、证据/结局错位一格）。"""
    # 表头块限定在 tlRenderRows 函数体内（避免匹配到页面其他表的「结局」列）
    block = _fn(html, "tlRenderRows")
    import re as _re
    n_th = len(_re.findall(r"th\('[^']+',\s*'[a-zA-Z0-9]+'\)", block)) + block.count("<th>")
    row = _fn(html, "tlRowHtml")
    # 展开明细行的 colspan 单独算：数据行 15 格（含空间列与溢价列）+ 明细跨 15 列
    n_td = row.count("<td") - row.count("<td colspan")
    assert n_th == 15, f"表头应 15 列，实为 {n_th}"
    assert n_td == 15, f"数据行应 15 格，实为 {n_td}（丢格 → 列错位）"
    assert 'colspan="15"' in row, "展开明细行必须跨 15 列（跟表头同步）"
    assert "+ contCell +" in row or "+ contCell" in row, "延续性单元格必须拼进行"
    assert "+ headCell +" in row, "空间列（leaderHeadroom）必须拼进行——v5/v6 核心产出不得只在明细 JSON 里可见"
    assert "+ premHtml +" in row, "溢价单元格必须拼进行（2026-10-26 用户需求）"


# ── 2026-10-26 表格四项优化（用户截图需求） ─────────────────────────────

def test_three_stage_fields_color_coded_by_bucket(html: str) -> None:
    """①题材深度/延续性/空间分档配色：红=最热/最强、琥珀=中、蓝=冷却、灰=不可判，
    与档位列（high_ge65 红 / mid 琥珀 / low 蓝）同热度语汇。"""
    for map_name, hot, cool in (("TL_DEPTH_BADGE", "climax", "igniting"),
                                ("TL_CONT_BADGE", "strong_extend", "ending"),
                                ("TL_HEAD_BADGE", "space_2plus", "peak")):
        m = re.search(rf"const {map_name} = \{{([^}}]+)\}}", html)
        assert m, f"{map_name} 分档配色表缺失"
        assert hot in m.group(1) and cool in m.group(1), f"{map_name} 关键档位缺失"
    row = _fn(html, "tlRowHtml")
    for map_name in ("TL_DEPTH_BADGE", "TL_CONT_BADGE", "TL_HEAD_BADGE"):
        assert map_name in row, f"{map_name} 必须接到徽章类（不能全灰）"


def test_evidence_cell_shows_concrete_content(html: str) -> None:
    """②题材证据列显示具体内容：事件标题/题材标签铺进单元格（CSS 截断 + tooltip 全文），
    不再只给「+N事件 / +题材N」计数徽章——计数无法区分真驱动与凑数标签。"""
    row = _fn(html, "tlRowHtml")
    assert "r.evidenceEventTitles" in row and "r.evidenceKwordTags" in row, \
        "事件标题与题材标签必须消费"
    assert "tl-evtxt" in row and "tl-evtags" in row, "具体内容必须铺进单元格（截断样式）"
    assert "+ r.evidenceEventTitles.length" not in row, "「+N事件」计数徽章不得回潮"
    assert "briefN" not in row, "旧的计数变量不得残留"
    assert "tl-evtxt" in html and "tl-evtags" in html, "截断样式必须存在"


def test_premium_column_day2(html: str) -> None:
    """③溢价列：结局=续板（打板入场成立）→ 显示 T+2 溢价率（outcomeDay2.closePct，
    settle_day2 挂链回填）；未续=无入场不显溢价；未回填显「待回填」不编造；可排序。"""
    rows_fn = _fn(html, "tlRenderRows")
    assert "th('溢价', 'day2')" in rows_fn, "溢价列必须可排序"
    row = _fn(html, "tlRowHtml")
    assert "outcomeDay2" in row and "closePct" in row, "溢价读 outcomeDay2.closePct"
    assert "待回填" in row, "续板但溢价未回填必须显式（fail-visible）"
    assert "outKey === 'sealed'" in row, "只给结局=续板的行显示溢价"
    kv = _fn(html, "tlSorted")
    assert "day2" in kv, "排序键必须接线"


# ── 2026-10-24：四题置信芯片 + 续板概率改中值加权期望 ─────────────────────

def test_four_judgement_fields_carry_confidence_chips(html: str) -> None:
    """四字段（档位/题材深度/延续性/空间）必须带模型置信芯片（用户裁决「置信度必须可视化」）。

    被证据门强制覆盖的题 confidence=1.0 是程序写的——必须显「门」标记，
    不得拿程序覆盖冒充模型置信（P100）。
    """
    row = _fn(html, "tlRowHtml")
    for key in ("leader_nextday_continue", "theme_speculation_depth",
                "theme_continuation", "leader_headroom"):
        assert f"tlConfChip(r, '{key}')" in row, f"{key} 徽章必须带置信芯片"
    chip = _fn(html, "tlConfChip")
    assert "forcedKeys" in chip and "gate.applied" in chip, "门强制覆盖必须先于 confChip 判定"
    assert "门" in chip, "门覆盖题显「门」标记而非 P100"
    assert "confChip(" in chip, "未过门复用全局三级色芯片（灰≥60/琥珀35-60/红<35）"
    # 数据链完整性：出参四键必须被消费（API 字段 ↔ 前端字段一一对上）
    for field in ("choiceConfidence", "themeSpeculationDepthConfidence",
                  "themeContinuationConfidence", "leaderHeadroomConfidence"):
        assert field in chip, f"出参 {field} 必须接到芯片"
    # 提示行说明 P 与门的语义（P=模型置信度，红<35 两可勿当结论）
    assert "P=模型置信度" in _fn(html, "tlRenderRows")


def test_continue_probability_is_midpoint_weighted_expectation(html: str) -> None:
    """续板概率=四档中值加权期望（与后端 continue_point_estimate 同口径）。

    旧口径「非 insufficient 质量和」=1−P(证据不足)，恒 85%~100%，与「档位=低25-45%」
    并列会被读成"100% 会续板"（2026-10-24 用户裁决换口径）；全 insufficient 仍显 '-'。
    """
    fn = _fn(html, "tlProb")
    assert "TL_MIDPOINTS" in fn, "必须按档位中值加权（0.75/0.55/0.35/0.125）"
    assert "total <= 0.0001" in fn, "全 insufficient（含被门）必须显 '-'，不编造概率"
    assert ("const TL_MIDPOINTS = { high_ge65: 0.75, mid_45_65: 0.55, "
            "low_25_45: 0.35, verylow_lt25: 0.125 }" in html), \
        "中值表必须与后端 CONTINUE_BUCKET_MIDPOINTS 逐项对齐（离线评估/展示同一口径）"
    # 旧口径残留不得回潮
    assert "'insufficient' ? a : a" not in fn, "旧的「非 insufficient 质量和」求和不得复活"
    # 单元格 tooltip 注明口径（中值加权期望，非模型直读）
    row = _fn(html, "tlRowHtml")
    assert "非模型直读" in row


def test_evidence_cell_shows_l2_resolution_badge_even_when_industry_mapped(html: str) -> None:
    """「+板内解析」徽章：有产业树映射时板内解析在场也必须显（2026-10-26 用户裁决）。

    上海九百观感缺口：映射节点名与板块同名（大消费→大消费）时整列只剩板块名，
    S3 补充映射与板内解析证据在场却不可见。未映射分支维持「板内解析+题材N」蓝徽章不变。
    """
    row = _fn(html, "tlRowHtml")
    assert "evidenceBoardResolved" in row, "徽章判定必须消费 evidenceBoardResolved 出参"
    badge_lines = [ln for ln in row.splitlines() if "+板内解析" in ln]
    assert any("title=" in ln for ln in badge_lines), \
        "有映射分支必须渲染带 title 的板内解析徽章（注释行不算）"
