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
    _assert_clean(AL.auction_push_line(push, codes=["603135"]), "auction_push_line(个股)")
    _assert_absent(AL.auction_push_line([]), "auction_push_line(无推送)")
    bid = [{"label": "中重科技", "item": {"bidding_pct": 3.05, "bidding_amount": 1.2e8,
                                          "bidding_turnover": 1.8, "bidding_net": 2e7},
            "peers": [{"name": "天普股份", "pct": 10.0, "amount": 1.2e8}]}]
    _assert_clean(AL.auction_bid_line(bid), "auction_bid_line")
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
