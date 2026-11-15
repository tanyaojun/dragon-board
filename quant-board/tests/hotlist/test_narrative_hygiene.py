# -*- coding: utf-8 -*-
"""jev 语料叙事卫生红线测试（AGENTS §1.2-8，2026-11-09 龙江交通语料污染复盘）。

红线：投喂 jev 的语料叙事文本只放数据事实与最简缺失标注（「不可考」/「未生成」）；
口径说明、校准声明、采集/统计窗口注、判据指引等**开发注释一律禁止进叙事**——它们
随每次构建叙事重新注入而反复堆积，浪费 token 且干扰 jev 判定。开发口径只允许留在：
- 代码注释/文档字符串；
- 结构化落库字段（window_note / poolMissing / evidenceMissingReason 等审计载荷）；
- docs/。

本测试对全部叙事行构建函数用代表性输入逐行断言黑名单短语缺席；未来新增叙事行
（或改行文）被本测试拦住，防止污染再次堆积。黑名单新增词条须同步 AGENTS §1.2-8。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_event_digest as D
from backend.analysis.hotlist import theme_leader_ammo as A

# 开发注释黑名单：出现任一子串即违规。「不可考」「未生成」「非收盘帧」「单位待校验」
# 「弱匹配」「数据时点」「原始值」等数据事实/缺失标注不在黑名单内。
FORBIDDEN = (
    "程序直读",
    "供校准参考",
    "不作判据",
    "统计窗口",
    "未标注",
    "不自算",
    "原样透出",
    "原样 ",
    "未落库",
    "采集帧",
    "抓取",
    "不代表无催化",
    "≠",
    "事实披露",
    "非方向信号",
    "非当日重问",
    "两源口径差",
    "口径自证",
    "如实标注",
    "注意：",
    "断流/见顶",
    "本行不适用",
    "截断",
    "（另 ",
    "近并列",
    "口径哨兵",
    "fail-visible",
    "状态机",
    "匹配方式",
    "弱匹配",
    "最近记录日",
    "梯队串",
    "全窗",
    "日历源",
    "取数日",
    "节点",
    "层1",
    "层2",
    "拉取失败",
    "KPL直播播报",
)


def _assert_clean(text: str | None, ctx: str) -> None:
    if text is None:
        return   # 缺数据 → 整行缺席，同样合规（AGENTS §1.2-8）
    assert isinstance(text, str) and text, f"{ctx}: 出行必须非空"
    hits = [w for w in FORBIDDEN if w in text]
    assert not hits, f"{ctx}: 语料叙事含开发注释 {hits}\n---\n{text}\n---"


def _assert_absent(text: str | None, ctx: str) -> None:
    """缺数据/无信息量场景：必须整行缺席（None），不留占位。"""
    assert text is None, f"{ctx}: 缺数据应整行缺席，实际出行：\n---\n{text}\n---"


# ── 市场情绪周期语料段（relay v8 融合，2026-11-12）────────────────────

class _McCol:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, q, projection=None):
        return self._doc


class _McDb:
    def __init__(self, doc):
        self._c = _McCol(doc)

    def __getitem__(self, k):
        return self._c


def _mc_doc(events):
    return {"_id": "2026-11-11:MARKET_CYCLE", "state": "wzs", "daysInState": 2,
            "transition": {"from": "ice", "to": "wzs"}, "events": events,
            "ceiling": {"maxBoard": 7, "threePlusN": 6, "prevCeiling20": 11},
            "anchor": {"main": {"code": "002578", "name": "闽发铝业", "height": 7,
                                "poolDay": "2026-11-10", "leaderSealedToday": False},
                       "growth": {"code": "301697", "name": "贝特利", "height": 3,
                                  "poolDay": "2026-11-06", "leaderSealedToday": True}}}


def test_hygiene_market_cycle_lines_all_event_variants():
    from backend.operations import jev_relay_index as R
    variants = [
        [],
        [{"type": "highTolerance", "code": "002578", "name": "闽发铝业", "subtype": "rebound"}],
        [{"type": "highCollapse", "code": "600111", "name": "昨龙", "subtype": "1day"}],
        [{"type": "spaceBreakthrough", "maxBoard": 8, "prevCeiling": 7,
          "stocks": [{"code": "600825", "name": "新华传媒"}]}],
        [{"type": "spaceCompress", "maxBoard": 3, "lowStreak": 2, "maxBoardThreshold": 4}],
    ]
    for evs in variants:
        lines = R.market_cycle_lines(_McDb(_mc_doc(evs)), "2026-11-11")
        assert lines and lines[0] == "【市场情绪周期】"
        for ln in lines:
            _assert_clean(ln, f"market_cycle_lines(events={evs})")
    # 缺档 → 整段缺席（fail-visible，3 题落 insufficient_evidence）
    assert R.market_cycle_lines(_McDb(None), "2026-11-11") == []


def test_hygiene_prev_phase_line_all_variants():
    """v9 昨日相位软参照行（relay-v9 §五）：全相位中文变体过黑名单；无开发注释。"""
    from backend.operations import jev_relay_index as R
    for ph, cn in R._PHASE_CN.items():
        for dip in (1, 3, 12):
            _assert_clean(f"昨日相位：{cn} · 已持续 {dip} 日", f"prev_phase({ph},{dip})")
        _assert_clean(f"昨日相位：{cn}", f"prev_phase({ph},no_dip)")


# ── 个股画像行族（theme_leader_ammo） ────────────────────────────────

GENE_ITEM = {"stock_id": "000525", "gene": {"zt_count": 4, "premium5_count": 1,
                                            "next_day_red_pct": 50, "first_seal_pct": 100,
                                            "first_broken_pct": 0, "lianban_pct": 50},
             "raw": [4, 1, 50, 100, 0, 50], "window_note": "上游未标注统计窗口",
             "same_day": True, "fetched_date": "2026-11-09"}

SEAL_ITEM = {"zt_tur": 77237472.0, "max_zt_tur": 407660096.0,
             "real_float": 4422390777.0, "real_turnover": 14.31,
             "main_net": 148080233.0, "amount": 593597266.0, "price": "",
             "pool_state": "sealed", "last_seen_ts": 1794119726.2,
             "zt_time": 1793929260.0, "last_zt_time": 1793929260.0}


def test_hygiene_structure_facts_line():
    ln = A.structure_facts_line({"streak": 2, "ladderFollowers": 4, "leaderSealedToday": True},
                                {"state": "mainrise", "stateCn": "主升"})
    _assert_clean(ln, "structure_facts_line")


def test_hygiene_gene_line_all_variants():
    _assert_clean(A.zt_gene_line([{"label": "主板龙一 X", "item": GENE_ITEM}]),
                  "zt_gene_line(同日)")
    backfill = dict(GENE_ITEM, same_day=False, fetched_date="2026-11-10")
    _assert_clean(A.zt_gene_line([{"label": "主板龙一 X", "item": backfill}]),
                  "zt_gene_line(回填)")
    _assert_absent(A.zt_gene_line([{"label": "主板龙一 X", "item": {}}]),
                   "zt_gene_line(缺语料 → 整行缺席)")


def test_hygiene_notice_count_line_all_variants():
    item = {"counts": {"announcement": 2, "report": 0, "news": None},
            "upstream_date": "20261109",
            "window_note": "计数统计窗口上游未标注（公告/研报/新闻计数原样透出，不自算不反推）"}
    _assert_clean(A.notice_count_line([{"label": "主板龙一 X", "item": item,
                                        "poolMissing": None}]),
                  "notice_count_line(公告≥1)")
    # 后端取不到 → 整行缺席，不留一个字（用户 2026-11-10 裁决）
    _assert_absent(A.notice_count_line([{"label": "主板龙一 X", "item": None,
                                         "poolMissing": "no_notice_corpus"}]),
                   "notice_count_line(取不到)")
    # 无判读信息量（公告/研报均 0，仅新闻计数）→ 整行缺席
    _assert_absent(A.notice_count_line([{"label": "主板龙一 X", "item": {
        "counts": {"announcement": 0, "report": 0, "news": 1},
        "upstream_date": "20261109"}}]),
        "notice_count_line(0/0/1 无信息量)")


def test_hygiene_theme_heat_line_all_variants():
    themes = [{"id": "80001", "name": "光伏", "number": 96.5},
              {"id": "80002", "name": "次新", "number": None}]
    _assert_clean(A.theme_heat_line([{"label": "主板龙一 X", "themes": themes,
                                      "poolMissing": None}]),
                  "theme_heat_line(含非数值 number)")
    # 缺语料/不在池/题材库为空 → 整行缺席
    _assert_absent(A.theme_heat_line([{"label": "主板龙一 X", "themes": None,
                                       "poolMissing": "no_theme_corpus"}]),
                   "theme_heat_line(缺语料)")


def test_hygiene_seal_quality_line_all_variants():
    _assert_clean(A.seal_quality_line([{"label": "主板龙一 X", "item": SEAL_ITEM,
                                        "frameAt": "21:11"}]),
                  "seal_quality_line(正常)")
    _assert_clean(A.seal_quality_line([{"label": "主板龙一 X", "item": SEAL_ITEM,
                                        "frameAt": "14:35"}]),
                  "seal_quality_line(非收盘帧)")
    # 单位待校验（题面 v16 引用的固定字样，数据事实，允许）但不带「无法自证」类口径注
    bad_unit = dict(SEAL_ITEM, zt_tur=5e11, real_float=4.4e9)   # 越界带
    line = A.seal_quality_line([{"label": "龙一 X", "item": bad_unit, "frameAt": "15:00"}])
    _assert_clean(line, "seal_quality_line(越界带)")
    _assert_clean(A.seal_quality_line([{"label": "主板龙一 X", "item": None,
                                        "frameAt": None, "unsealed": True}]),
                  "seal_quality_line(未封板，判读事实保留)")
    _assert_absent(A.seal_quality_line([{"label": "主板龙一 X", "item": None,
                                         "frameAt": None,
                                         "poolMissing": "no_archive"}]),
                   "seal_quality_line(缺档 → 整行缺席)")
    conflict = A.seal_quality_line([{"label": "主板龙一 X", "item": dict(SEAL_ITEM),
                                     "frameAt": "14:35", "unsealed": True}])
    _assert_clean(conflict, "seal_quality_line(未封板/池档矛盾)")


def test_hygiene_lhb_line_all_variants():
    facts = {"ok": True, "stocks": [
        {"code": "601188", "name": "龙江交通", "main_net_yuan": 2.7e7,
         "main_buy_yuan": 9.0e7, "main_sell_yuan": -3.8e7, "reason": "日涨幅偏离"}]}
    # 缺数据（取数失败/榜单未生成）→ 整行缺席
    _assert_absent(A.lhb_line({"ok": False, "empty_structured": True,
                               "order_sign_count": 3, "stocks": []}, codes=["601188"]),
                   "lhb_line(榜单未生成)")
    _assert_absent(A.lhb_line({"ok": False, "reason": "fetch_failed: boom"},
                              codes=["601188"]),
                   "lhb_line(取数失败)")
    _assert_absent(A.lhb_line(None, codes=["601188"]), "lhb_line(无数据)")
    _assert_clean(A.lhb_line(facts, codes=["300001"]), "lhb_line(相关个股 0 只，验证后缺席)")
    _assert_clean(A.lhb_line(facts, codes=["601188"]), "lhb_line(上榜)")
    # C（2026-11-11）：席位/机构兜底行只列已取得事实，无开发注释
    seat_facts = {"ok": False, "list_ok": True, "stock_ok": True,
                  "empty_structured": True, "groups": [], "stocks": [],
                  "stock_board": {"601188": {"name": "龙江交通", "buy_in": 2.4e8,
                                              "join_num": 3, "turnover": 12.5}},
                  "agency": {"601188": {"name": "龙江交通", "buy_in": -1.1e8,
                                         "join_num": 2, "turnover": 8.0}}}
    _assert_clean(A.lhb_line(seat_facts, codes=["601188"]),
                  "lhb_line(席位/机构兜底)")


def test_hygiene_reason_and_driver_cross_lines():
    _assert_clean(A.limitup_reason_line(
        [{"label": "主板龙一 龙江交通",
          "item": {"zt": "冰雪经济+中俄贸易受益", "plate": "冰雪产业"}}]),
        "limitup_reason_line")
    _assert_absent(A.limitup_reason_line([{"label": "主板龙一 龙江交通", "item": None}]),
                   "limitup_reason_line(缺原因 → 整行缺席)")
    _assert_absent(A.driver_cross_line(None),
                   "driver_cross_line(缺席 → 整行缺席)")
    _assert_absent(A.plate_strength_line({"ok": False, "reason": "unmatched"}),
                   "plate_strength_line(未匹配 → 整行缺席)")
    _assert_absent(A.plate_strength_line(
        {"ok": False, "reason": "fetch_failed: http 502"}),
        "plate_strength_line(接口异常 → 整行缺席)")
    _assert_clean(A.plate_strength_line({"ok": True, "rank": 3, "total": 100,
                                         "strength": 980, "pct": 2.1,
                                         "name": "冰雪经济"}),
                  "plate_strength_line(正常)")


def test_hygiene_plate_series_line():
    rank = [{"date": "2026-11-09", "strength": 31837, "main_net": -4.8e10,
             "amount": -4.0e11, "pct": 1.0, "pct": 1.0}]
    zt = [{"date": "2026-11-09", "zt_num": 16,
           "lz_info": "大业股份,0,2连板"}]
    _assert_clean(A.plate_series_line(rank, zt, plate_name="机器人概念",
                                      label_date="2026-11-09"),
                  "plate_series_line(正常，哨兵告警不进叙事)")
    _assert_clean(A.plate_series_line([], [], plate_name="X",
                                      label_date="2026-11-09",
                                      zt_fetch_error="http 502"),
                  "plate_series_line(拉取失败)")


def test_hygiene_live_and_market_summary_lines():
    _assert_clean(A.kpl_live_line(
        [{"time": "09:31", "comment": "冰雪产业异动拉升，龙江交通高开秒板"}],
        board="冰雪经济", total=54, window="09:15~15:00"),
        "kpl_live_line(命中)")
    _assert_clean(A.kpl_live_line([], board="冰雪经济", total=54,
                                  window="09:15~15:00"),
                  "kpl_live_line(无播报，验证后缺席)")
    _assert_absent(A.kpl_live_line([], board="冰雪经济",
                                   unavailable="实时流不可回放"),
                   "kpl_live_line(不可用 → 整行缺席)")
    _assert_clean(A.market_summary_line(
        {"comment": "三大指数高开震荡，收盘成交不足1.5万亿"}),
        "market_summary_line")


# ── 完整叙事（行序装配不得引入注释） ─────────────────────────────────

def test_hygiene_leader_and_sector_narrative_assembly():
    lines = {
        "theme_heat_line": "题材热度（KPL 题材库）：主板龙一 X=题材库语料不可考",
        "gene_line": "涨停基因：主板龙一 X=涨停6次、次日红盘100%",
        "reason_line": "涨停原因：主板龙一 龙江交通=冰雪经济",
        "notice_count_line": "公告计数（KPL 公告/研报/新闻）：主板龙一 X：公告 0/研报 0/新闻 1",
        "lhb_facts_line": "龙虎榜：--（当日分组榜单未生成）",
        "facts_line": "结构事实：周期状态=主升｜今日已封板=是",
    }
    text = A.build_leader_narrative(
        date="2026-11-09", market_line="涨停 53 家", structure="结构行", baseline="结构基线：…",
        evidence_block="【题材证据】\n题材语料未采集。", leader_name="龙江交通",
        leader_code="601188", **lines)
    _assert_clean(text, "build_leader_narrative")
    sector = A.build_sector_narrative(
        date="2026-11-09", market_line="涨停 53 家", structure="结构行", baseline="结构基线：…",
        evidence_block="【题材证据】\n板块级催化：产业树未映射（「冰雪经济」）",
        board="冰雪经济", reason_line="涨停原因：主板龙一 龙江交通=冰雪经济",
        lhb_facts_line="龙虎榜：--（当日分组榜单未生成）")
    _assert_clean(sector, "build_sector_narrative")


# ── 题材证据块（theme_event_digest，含未采集/未映射/热度序列形态） ────

class _FakeCol:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    def find(self, query=None, projection=None):
        return list(self.docs)

    def find_one(self, query=None, projection=None, sort=None):
        return self.docs[0] if self.docs else None

    def count_documents(self, query=None):
        return len(self.docs)


class _FakeDb:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _FakeCol())


def test_hygiene_theme_evidence_block_empty_corpus():
    out = D.build_theme_evidence_block(_FakeDb(), board_name="冰雪经济",
                                       date="2026-11-09")
    _assert_clean(out["text"], "evidence_block(语料未采集)")


def test_hygiene_theme_evidence_block_unmapped_and_heat_series():
    db = _FakeDb()
    db.cols["jiuyan_ai_industry"] = _FakeCol([])
    out = D.build_theme_evidence_block(db, board_name="冰雪经济", date="2026-11-09")
    _assert_clean(out["text"], "evidence_block(未映射+热度序列空)")


def test_hygiene_theme_evidence_block_with_content():
    db = _FakeDb()
    db.cols["jiuyan_ai_industry"] = _FakeCol([
        {"code": "0400", "name": "冰雪经济", "level": 1, "hot": 9.43,
         "content": "2026年10月13日，黑龙江省冰雪旅游推介会举行。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-11-09"}])
    out = D.build_theme_evidence_block(db, board_name="冰雪经济", date="2026-11-09")
    _assert_clean(out["text"], "evidence_block(有催化正文)")


def test_hygiene_20261111_new_lines():
    """2026-11-11 语料缺口补全新行（①→④）：黑名单零命中；缺数据整行缺席。"""
    rank_item = {"zt": "冰雪经济+中俄贸易受益", "plate": "冰雪产业", "rank": 15,
                 "rank_total": 5575, "rank_top": ["美邦服饰"], "zt_group": "2板",
                 "fx": "异动提醒", "jc": "股东拟减持", "jj": "", "pledge": ""}
    entries = [{"label": "主板龙一 龙江交通", "item": rank_item},
               {"label": "双创龙一 斯迪克", "item": None}]
    _assert_clean(A.limitup_reason_line(entries), "limitup_reason_line(热点摘引)")
    _assert_clean(A.popularity_rank_line(entries), "popularity_rank_line")
    _assert_clean(A.risk_profile_line(entries), "risk_profile_line")
    _assert_clean(A.bid_line([{"label": "主板龙一 龙江交通",
                               "item": {"bidding_pct": 4.32, "bidding_amount": 1.23e7}}]),
                  "bid_line")
    _assert_clean(A.board_zhaban_line({"zhabanN": 3}, detail=[
        {"name": "某股", "zt_time": 1794119726.2, "open_time": None}]),
        "board_zhaban_line(明细升级)")
    _assert_clean(A.board_dt_line([], lane_ok=True), "board_dt_line(验证缺席)")
    _assert_clean(A.board_dt_line(["A 股"], lane_ok=True), "board_dt_line(名单)")
    _assert_clean(A.lhb_forecast_line(
        [{"label": "待判龙一 603278", "item": {"stock_name": "某股", "hot_val": 35214,
                                               "hot_change": 1234,
                                               "main_net_amount": 1.48e8}}],
        lane_ok=True), "lhb_forecast_line")
    _assert_clean(A.lhb_realtime_line(
        [{"label": "相关个股 603278", "item": {"name": "某股"}}], lane_ok=True),
        "lhb_realtime_line")
    _assert_clean(A.zt_big_order_line(
        [{"label": "主板龙一 某股", "item": {"zt_tur": 77237472, "buy_tur": 100}}]),
        "zt_big_order_line")
    _assert_clean(A.bf_reason_line(
        [{"label": "主板龙一 某股", "item": {"desc": "光伏订单放量"}}]),
        "bf_reason_line")
    _assert_clean(A.abnormal_price_line(
        [{"label": "主板龙一 某股", "item": {"next_day_zf": 3.21}}]),
        "abnormal_price_line")
    _assert_clean(A.related_plate_line(
        [{"label": "主板龙一 某股", "board": "机器人", "knownThemes": [],
          "item": {"plates": [{"plate_name": "人形机器人", "plate_inc_rate": -1.63,
                               "stock_inc_rate": None}]}}]),
        "related_plate_line")
    # 缺数据 → 整行缺席
    _assert_absent(A.lhb_forecast_line([{"label": "X", "item": None}], lane_ok=False),
                   "lhb_forecast_line(无档)")
    _assert_absent(A.lhb_realtime_line([{"label": "X", "item": None}], lane_ok=False),
                   "lhb_realtime_line(无档)")
    _assert_absent(A.board_dt_line([], lane_ok=False), "board_dt_line(无档)")
    _assert_absent(A.bid_line([{"label": "X", "item": None}]), "bid_line(缺竞价)")


def test_hygiene_v17_sector_judgment_and_base_rate_lines():
    """v17 两新叙事行接入 §1.2-8 强制黑名单回归（review m3）；缺数据整行缺席。"""
    ans = {"theme_speculation_depth": {"choice": "fermenting", "confidence": 0.68},
           "theme_continuation": {"choice": "strong_extend", "confidence": 0.92}}
    _assert_clean(A.sector_judgment_line(ans), "sector_judgment_line")
    _assert_clean(A.base_rate_line({"n": 143, "ratePct": 21.7, "start": "2026-10-23",
                                    "end": "2026-11-10",
                                    "sealed": {"n": 100, "ratePct": 26.6},
                                    "broken": {"n": 43, "ratePct": 5.9}}),
                  "base_rate_line")
    _assert_absent(A.sector_judgment_line(None), "sector_judgment_line(缺判答)")
    _assert_absent(A.sector_judgment_line(
        {"theme_speculation_depth": {"choice": "insufficient"},
         "theme_continuation": {"choice": "insufficient"}}),
        "sector_judgment_line(双侧 insufficient)")
    _assert_absent(A.base_rate_line(None), "base_rate_line(无已结算行)")


def test_hygiene_auction_leader_vA1_lines():
    """竞价龙头 vA1 新叙事行接入 §1.2-8 强制黑名单回归（预登记 auction-leader-vA1）。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    push = [{"time": "09:15", "comment": "竞价看龙头：机器人中重科技",
             "stocks": [{"code": "603135", "name": "中重科技", "pct": 3.05,
                         "board": "机器人", "boardRaw": "机器人"}]}]
    _assert_clean(AL.auction_push_line(push), "auction_push_line")
    # 时点语义标注（2026-11-13 用户裁决）：双时点并存消解矛盾锚，措辞属市场机制语义
    pl = AL.auction_push_line(push)
    assert pl.startswith("竞价看龙头推送（09:15 试盘价）："), pl
    _assert_clean(AL.auction_push_line(push, codes=["603135"]), "auction_push_line(个股)")
    _assert_absent(AL.auction_push_line([]), "auction_push_line(无推送)")
    bid = [{"label": "中重科技", "item": {"bidding_pct": 3.05, "bidding_amount": 1.2e8,
                                          "bidding_turnover": 1.8, "bidding_net": 2e7},
            "peers": [{"name": "天普股份", "pct": 10.0, "amount": 1.2e8}]}]
    _assert_clean(AL.auction_bid_line(bid), "auction_bid_line")
    assert AL.auction_bid_line(bid).startswith("竞价（09:25 匹配价）："), "双时点语义标注"
    assert "额 1.20亿" in AL.auction_bid_line(bid), "peers 竞价额入叙事（身位题判据证据）"
    _assert_absent(AL.auction_bid_line([{"label": "X", "item": None}]), "auction_bid_line(缺竞价)")
    _assert_clean(AL.auction_structure_line(
        {"streak": 2, "sealedPrev": True, "ztTime": "09:41", "gain10": 21.5},
        prev_date="2026-11-12"), "auction_structure_line")
    _assert_absent(AL.auction_structure_line(None, prev_date="2026-11-12"),
                   "auction_structure_line(全缺)")
    _assert_clean(AL.auction_board_structure_line(
        [{"streak": 2, "sealedPrev": True}, {"streak": 1, "sealedPrev": True}],
        prev_date="2026-11-12"), "auction_board_structure_line")
    _assert_clean(AL.auction_base_rate_line(
        {"n": 40, "rate": 32.5, "start": "2026-11-13", "end": "2026-11-20"}),
        "auction_base_rate_line")
    _assert_absent(AL.auction_base_rate_line(None), "auction_base_rate_line(无已结算)")
    narr = AL.build_auction_leader_narrative(
        date="2026-11-13", prev_date="2026-11-12", market_line="盘面事实：测试",
        leader_name="中重科技", leader_code="603135", board="机器人",
        push_line=AL.auction_push_line(push, codes=["603135"]),
        bid_line=AL.auction_bid_line(bid),
        structure=AL.auction_structure_line({"streak": 2, "sealedPrev": True},
                                            prev_date="2026-11-12"),
        base_rate=AL.auction_base_rate_line({"n": 40, "rate": 32.5}),
        evidence_block="题材证据块：测试")
    _assert_clean(narr, "build_auction_leader_narrative")
    sec = AL.build_auction_sector_narrative(
        date="2026-11-13", prev_date="2026-11-12", market_line="盘面事实：测试",
        board="机器人", push_line=AL.auction_push_line(push),
        board_structure=AL.auction_board_structure_line(
            [{"streak": 2, "sealedPrev": True}], prev_date="2026-11-12"),
        evidence_block="题材证据块：测试")
    _assert_clean(sec, "build_auction_sector_narrative")


def test_hygiene_board_belong_push_concept_suffix():
    """2026-11-13 裁决：板块归属=韭研板块名 + 推送概念事实并列（非开发注释）。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    narr = AL.build_auction_leader_narrative(
        date="2026-11-13", prev_date="2026-11-12", market_line="盘面事实：测试",
        leader_name="日出东方", leader_code="603366", board="寒潮",
        push_line=None, bid_line=None, structure=None, ladder_line=None,
        base_rate=None, sector_judgment=None, theme_heat_line=None,
        push_board="光伏", evidence_block="【题材证据】\n测试")
    _assert_clean(narr, "board_belong_push_suffix")
    assert "板块归属：寒潮（竞价推送概念：光伏）" in narr


def test_hygiene_auction_no_unverifiable_noise():
    """2026-11-13 用户裁决：竞价链叙事与题面禁「不可考」——缺位字段/整行缺席，不留噪声。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    import json as _json
    # 叙事全参缺位（market_line/structure/bid_line/board 全 None）→ 无一行占位噪声
    narr = AL.build_auction_leader_narrative(
        date="2026-11-13", prev_date=None, market_line=None,
        leader_name="中重科技", leader_code="603135", board=None,
        push_line=None, bid_line=None, structure=None, ladder_line=None,
        base_rate=None, sector_judgment=None, theme_heat_line=None,
        push_board=None, evidence_block="题材证据块：测试")
    assert "不可考" not in narr
    assert "板块归属" not in narr, "板块缺席 = 整行缺席"
    assert "昨日（" not in narr, "无 T−1 = 市场行缺席"
    # 结构行缺 prev_date / 缺字段 → 缺位段不出现
    assert AL.auction_structure_line({"sealedPrev": False}, prev_date=None) is None
    ln = AL.auction_structure_line({"sealedPrev": False}, prev_date="2026-11-12")
    assert "连板" not in ln and "不可考" not in ln
    # 竞价行缺字段 → 缺位字段不出现
    bid = [{"label": "中重科技", "item": {"bidding_pct": 3.05}}]
    bl = AL.auction_bid_line(bid)
    assert "不可考" not in bl and "竞价涨幅 +3.05%" in bl
    # 题面措辞同步：竞价三新题无「不可考」（theme_continuation 为 v17 复用共享对象，
    # 题面属题材链裁决范围，本轮不动，保持 is 同一对象身份）
    for qk in ("auction_leader_seal_today", "leader_catalyst_hardness", "auction_seat_durability"):
        assert "不可考" not in _json.dumps(AL.QUESTIONS_AUCTION_LEADER[qk], ensure_ascii=False)
    # 2026-11-13f review G1/G4：竞价专项禁词集（全局 FORBIDDEN 属 theme 链裁决不动）：
    # 「不可算」（theme 共享梯队行占位段经消费点过滤，见 test_auction_leader_label），
    # 补源/来源注类新词（只在 corpusState/代码注释，禁渗叙事）。
    # G3（记录裁决）：基础率锚行「窗 {start}~{end}」是锚样本人群日期=数据事实，
    # 与 v17 base_rate_line 同款先例，不入禁词；若未来加严需用户显式裁决。
    auction_forbidden = ("不可算", "补源", "腾讯", "tencent_auction", "榜外补")
    narr2 = AL.build_auction_leader_narrative(
        date="2026-11-13", prev_date="2026-11-12", market_line=None,
        leader_name="中重科技", leader_code="603135", board="机器人",
        push_board="机器人",
        push_line="竞价看龙头推送：09:15 中重科技 +3.00%",
        bid_line="竞价：中重科技 竞价涨幅 +3.05% 竞价成交额 0.10亿",
        structure="昨日（2026-11-12）结构：连板 2 板，昨日封板",
        ladder_line="昨日（2026-11-12）板块梯队形态：首板 3 家 / 2板 1 家",
        base_rate="竞价封板基础率：历史竞价龙头当日封板率 50.0%（2 样本，窗 2026-11-06~2026-11-12）",
        sector_judgment=None, theme_heat_line=None,
        evidence_block="题材证据块：测试")
    for w in auction_forbidden:
        assert w not in narr2, f"竞价叙事含禁词 {w}"
    assert "板块归属：机器人" in narr2


def test_hygiene_review_20261113f_fixes():
    """2026-11-13f review 修复回归：evidence 空名不掏占位、负额渲染量级一致。"""
    from backend.analysis.hotlist import theme_event_digest as TD
    from backend.analysis.hotlist import theme_leader_ammo as TA

    class _EmptyDb:
        def __getitem__(self, name):
            class _C:
                def find(self, *a, **k):
                    return []
                def find_one(self, *a, **k):
                    return None
            return _C()

    blk = TD.build_theme_evidence_block(_EmptyDb(), board_name="", date="2026-11-13",
                                        leader_code="603135", sealed_codes=None)
    assert "产业树未映射" not in blk["text"], "空名段 = 整段缺席（finding-4）"
    # 负额渲染（finding-3）：负亿/负万与正额同口径判门
    assert TA._fmt_amount_yuan(-2.5e8) == "-2.50亿"
    assert TA._fmt_amount_yuan(-5e5) == "-50.0万"
    assert TA._fmt_amount_yuan(2.5e8) == "2.50亿"


def test_hygiene_auction_leader_vA2_dragon_line():
    """vA2 龙序行/锚构成/板结构入选措辞接入 §1.2-8 黑名单回归（预登记 vA2 §5）。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    roles = [{"board": "半导体", "role": "龙一", "boards": 4, "days": 4,
              "time": "09:30", "sealedN": 3},
             {"board": "机器人", "role": "龙二", "boards": 2, "days": 2,
              "time": "09:35", "sealedN": 5, "zhaban": True}]
    ln = AL.auction_dragon_line(roles, prev_date="2026-11-12")
    _assert_clean(ln, "auction_dragon_line")
    assert ln.startswith("昨日（2026-11-12）韭研涨停分组龙序："), ln
    _assert_absent(AL.auction_dragon_line([], prev_date="2026-11-12"),
                   "auction_dragon_line(无龙序)")
    _assert_clean(AL.auction_base_rate_line(
        {"n": 40, "rate": 32.5, "nPush": 25, "nJiuyan": 15,
         "start": "2026-11-13", "end": "2026-11-20"}), "auction_base_rate_line(构成)")
    bs = AL.auction_board_structure_line(
        [{"streak": 2, "sealedPrev": True}], prev_date="2026-11-12")
    _assert_clean(bs, "auction_board_structure_line(入选)")
    assert "入选 1 只" in bs


def test_auction_question_texts_no_calibration_leak():
    """vA3 §2 纪律（2026-11-14 裁决）：题面禁嵌历史基数率/校准措辞——题面随每次投喂
    重复注入，嵌率烧 token 且形成锚定偏差；校准梯度只进预登记文档与评估层。
    档位定义百分比（45%-65%/<25% 等）不在禁列。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL3
    banned_words = ("基率", "回测", "校准", "抽样", "分桶")
    banned_stats = ("70%", "73%", "41%", "36%", "18%", "74%", "72%", "34%", "35%",
                    "15%", "19%", "22%", "13%", "12%", "23%", "61%", "78%", "44%",
                    "14%", "4%",
                    # 60 日复校新数（base-rate-60d-evaluation §2/§3，同入禁列；
                    # "5%" 与档位定义 "95%" 子串碰撞不单列，由其余禁数覆盖）
                    "76%", "43%", "16%", "75%", "48%", "34%", "11%", "77%")
    for key, q in AL3.QUESTIONS_AUCTION_LEADER.items():
        txt = q["instructions"] + "".join(q["criteria"].values())
        for w in banned_words:
            assert w not in txt, f"{key} 题面含校准措辞 {w!r}"
        for s in banned_stats:
            assert s not in txt, f"{key} 题面嵌基数率 {s!r}"


# ── 2026-11-14 盘前催化增量 B/C 新叙事节（早报/快讯）黑名单回归 ──
# 预登记 §B3/§C3 合同：新叙事行必须过本黑名单；缺席=整行零字。

def _morning_ok_doc():
    return {"_id": "2026-11-14", "kind": "jiuyan_morning_report", "date": "2026-11-14",
            "state": "ok", "title": "早报",
            "content": "1、热点事件\n1）物理AI：英伟达GTC大会11月14日在柏林举行。",
            "paragraphs": ["1、热点事件",
                           "1）物理AI：英伟达GTC大会11月14日在柏林举行。"],
            "fetchedAt": "2026-11-14T08:31:00", "quality": {"tokenSource": "cache+minted"}}


def _flash_docs():
    return [{"_id": "2026-11-13:2001", "kind": "ths_flash", "id": "2001", "seq": "3001",
             "title": "物理AI产业链获大额订单", "digest": "物理AI产业链获大额订单",
             "ctimeEpoch": 1763023800, "ctimeDate": "2026-11-13", "ctimeHHMM": "21:30",
             "source": "", "stocks": [], "tags": ["AI"], "firstSeenDate": "2026-11-14"}]


def test_hygiene_evidence_block_morning_flash_rendered():
    """早报节/快讯节命中渲染：逐行过黑名单；匹配口径只进结构化字段。"""
    db = _FakeDb()
    db.cols["jiuyan_morning_report"] = _FakeCol([_morning_ok_doc()])
    db.cols["ths_flash"] = _FakeCol(_flash_docs())
    out = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_morning=True, include_flash=True)
    assert "早盘催化（韭研早报 2026-11-14）：" in out["text"]
    assert "隔夜快讯（同花顺7×24）：" in out["text"]
    for line in out["text"].splitlines():
        _assert_clean(line, "evidence_block(早报+快讯渲染)")
    # 口径留痕只在结构化字段，不进叙事
    assert out["morningHits"][0]["matchHow"] and out["flashHits"][0]["matchHow"]
    assert "matchHow" not in out["text"] and "弱匹配" not in out["text"]


def test_hygiene_evidence_block_morning_flash_absent_zero_lines():
    """语料无档/未命中：整行零字（无空头节头、无占位）。"""
    db = _FakeDb()
    out = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_morning=True, include_flash=True)
    assert "早盘催化" not in out["text"] and "隔夜快讯" not in out["text"]
    assert out["morningState"] == "missing" and out["flashState"] == "missing"
    for line in out["text"].splitlines():
        _assert_clean(line, "evidence_block(缺席)")


# ── 2026-11-15 监管风险行（预登记 theme-leader-regulatory-risk）黑名单回归 ──

def test_hygiene_regulatory_risk_line():
    """监管风险行：五组事实渲染过黑名单；缺数据整行缺席（§1.2-8）。"""
    hit = {
        "monitor_current": {"stock_id": "605255", "stock_name": "天普股份",
                            "start_date": "2026-11-13", "end_date": "2026-11-26"},
        "monitor_history": {"stock_id": "605255", "stock_name": "天普股份",
                            "start_date": "2026-10-01", "end_date": "2026-10-14"},
        "recent": [{"stock_id": "605255", "stock_name": "天普股份",
                    "abnormal_date": "2026-11-16", "suspended_flag": True,
                    "resume_date": "2026-11-19", "monitor_flag": True,
                    "triggered_flag": False, "period": None},
                   {"stock_id": "605255", "stock_name": "天普股份",
                    "abnormal_date": "2026-11-11", "suspended_flag": False,
                    "resume_date": None, "monitor_flag": False,
                    "triggered_flag": True, "period": "30日200%"}],
        "today": {"stock_id": "600327", "stock_name": "大东方", "trigger_pct": 7.8,
                  "space_pct": 17.83, "period": "10日100%", "streak_tag": "昨5连板"},
        "tomorrow": {"stock_id": "301578", "stock_name": "辰奕智能", "trigger_pct": 17.9,
                     "space_pct": 17.9, "period": "10日100%", "streak_tag": None},
    }
    line = A.regulatory_risk_line([{"label": "主板龙一", "hit": hit}])
    _assert_clean(line, "regulatory_risk_line(五组渲染)")
    assert "重点监控(2026-11-13~2026-11-26)" in line
    assert "停牌 预计复牌2026-11-19" in line
    assert "今日涨停即触发严重异动" in line and "明日涨停即触发严重异动" in line
    assert "昨5连板" in line and "历史重点监控" in line
    # 缺位字段不补 0：trigger_pct 缺失 → 该段不带触发涨幅
    hit2 = {"today": {"stock_id": "600327", "stock_name": "大东方",
                      "trigger_pct": None, "space_pct": None, "period": None}}
    l2 = A.regulatory_risk_line([{"label": "x", "hit": hit2}])
    _assert_clean(l2, "regulatory_risk_line(缺位)")
    assert "触发涨幅" not in l2 and "0%" not in l2
    # 整行缺席纪律
    _assert_absent(A.regulatory_risk_line([]), "regulatory_risk_line(空entries)")
    _assert_absent(A.regulatory_risk_line([{"label": "x", "hit": {}}]),
                   "regulatory_risk_line(空hit)")
    _assert_absent(A.regulatory_risk_line([{"label": "x", "hit": None}]),
                   "regulatory_risk_line(None hit)")


def test_hygiene_auction_trial_strength_lines():
    """第三源两新行（2026-11-15 预登记）：纯数据事实过黑名单；缺数据整行缺席。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    st = {"boardAmt": 2.7e8, "btier": "中热 2-5亿", "jjRatio": 70.0,
          "jjtier": "mid50_95", "posture": "decrease", "rank": 2, "boardTrialN": 9}
    ln1 = AL.auction_board_strength_line("机器人", st)
    _assert_clean(ln1, "auction_board_strength_line")
    assert "Σ2.70亿" in ln1 and "强度档 中热 2-5亿" in ln1 and "板内试盘 9 只" in ln1
    ln2 = AL.auction_trial_selection_line(st)
    _assert_clean(ln2, "auction_trial_selection_line")
    assert "jj_ratio 70%" in ln2 and "mid50_95" in ln2 and "板内强度排名 2" in ln2
    # 缺数据整行缺席（不留占位）
    _assert_absent(AL.auction_board_strength_line(None, st), "board_strength(无板名)")
    _assert_absent(AL.auction_board_strength_line("机器人", None), "board_strength(无载荷)")
    _assert_absent(AL.auction_board_strength_line("机器人", {**st, "boardAmt": None}),
                   "board_strength(缺额)")
    _assert_absent(AL.auction_board_strength_line("机器人", {**st, "boardTrialN": None}),
                   "board_strength(缺家数)")
    _assert_absent(AL.auction_trial_selection_line(None), "trial_selection(无载荷)")
    _assert_absent(AL.auction_trial_selection_line({**st, "jjRatio": None}),
                   "trial_selection(缺强度比)")
    _assert_absent(AL.auction_trial_selection_line({**st, "rank": None}),
                   "trial_selection(缺排名)")
    _assert_absent(AL.auction_trial_selection_line({**st, "posture": "maintain"}),
                   "trial_selection(非撤减)")
    # 锚行第三桶构成（第三源样本在场）
    ln3 = AL.auction_base_rate_line({"n": 10, "rate": 40.0, "nPush": 5, "nJiuyan": 3,
                                     "nTrial": 2, "start": "2026-11-13", "end": "2026-11-14"})
    _assert_clean(ln3, "auction_base_rate_line(三桶)")
    assert "推送 5/韭研龙 3/竞价强度 2" in ln3
