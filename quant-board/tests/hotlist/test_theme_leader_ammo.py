# -*- coding: utf-8 -*-
"""题材层龙头题集/弹药纯函数测试（零 IO / 零模型）。

锁定口径：
1. **判据冻结**：题集内容哈希是代际戳，改一个字就必须换代（本测试冻结 v1 的 hash）；
2. **分桶唯一来源**：分桶函数被基线脚本与投喂叙事共用，键必须稳定（改键=历史桶率不可比）；
3. **龙一排序**：真连板最高 → 封板时间最早（时间缺失垫底，但不得把缺失当"最早"）；
4. **基准率透明度**：组合桶样本不足时必须明示"样本不足/样本量"，不得隐藏小样本或给假高率；
5. **叙事顺序固定**：便于逐字复现与回归比对；题材证据缺失的 fail-visible 文本不得被吞掉。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_leader_ammo as A


def test_question_set_frozen_hash_and_versions():
    """题集/原料代际戳冻结：任何判据字面改动都必须显式换代（跨代不可比）。

    代际史：v1 = 2026-10-20（hash `ff010c50200e`，见预登记 §4.2；13 条日标签保留为 v1 代）；
    v2 = 2026-10-20 晚（确定性证据门，hash `985c529fded7`）；v3 = 2026-10-22 归因修复
    （L2 板内解析 + 门收窄，hash `b8c00651de47`）；v4 = 2026-10-23 换源（事件层唯一权威源
    =开盘啦：题材事件/新闻(Kword)/日历，韭研 timeline 退役，hash `56dbb0709335`）；
    v6 = 2026-10-23 四题判据增档（hash `1d098c87e07e`，14 只样本）；v7 = 2026-10-24
    置信度归因后空间题加历史锚规则（空间题 conf 均值 0.435 全场最差且无锚，hash
    `40c7184a790e`，零样本——首批 10-26 才开火即被 v8 取代）；**v8 = 2026-10-24
    「越锚」铸词内联定义**（review P3：模型直读可能不解裸铸词，改「要选高于锚的
    档位（越锚）时」，hash `b0914cdd3e7d`）——**跨代标签不得混评**（评估按版本分组）。
    AMMO 原料代际：2026-10-24b 四补（S1/S2/S3/Q1）→ **2026-10-24c 盘面语料四补**
    （①基线行补封板时间/跟风梯队/昨日承接桶率 ②板内梯队形态行 ③前向交易日轴行
    ④板内炸板面行+结构行昨日口径修正；题面 v8 判据零改动，hash 不变）→
    **2026-10-24d review 处置**（断板改同名成员口径 prevStill，迁移场景不出负数；
    防御分支原始 None 泄漏修复；前向轴非 bridge 源结果不缓存）。
    """
    assert A.QUESTION_SET_VERSION_THEME_LEADER == "v8"
    assert A.AMMO_VERSION_THEME_LEADER == "2026-10-24d"
    assert A.QUESTION_SET_HASH_THEME_LEADER == "b0914cdd3e7d"
    # v5：四题 = 题材炒作深度 → 题材延续性 → 次日概率（校准基线锚）→ 龙头剩余空间；
    # catalyst_stage（v1-v4）被深度题取代，保留为旧代字段回读
    assert A.THEME_LEADER_KEYS == ("theme_speculation_depth", "theme_continuation",
                                   "leader_nextday_continue", "leader_headroom")
    for key in A.THEME_LEADER_KEYS:
        q = A.QUESTIONS_THEME_LEADER[key]
        assert q["type"] == "choice" and q["instructions"] and q["criteria"]
        assert "insufficient" in q["criteria"], "每题必须留证据不足档，禁止逼模型硬填"
    # v7 锚规则只加在空间题 instructions（criteria 门不动，space_2plus 零命中先观察）
    assert "空间锚" in A.QUESTIONS_THEME_LEADER["leader_headroom"]["instructions"]


def test_bucket_functions_stable_keys():
    assert A.streak_bucket(None) == "unknown" and A.streak_bucket("bad") == "unknown"
    assert [A.streak_bucket(v) for v in (1, 2, 3, 4, 9)] == ["1", "2", "3", "4+", "4+"]
    assert [A.board_count_bucket(v) for v in (1, 2, 3, 4, 5, 7, 8, 12)] == \
        ["1-2", "1-2", "3-4", "3-4", "5-7", "5-7", ">=8", ">=8"]
    assert [A.seal_time_bucket(t) for t in ("09:25:00", "10:00:59", "11:30", "13:00", "13:16:47")] == \
        ["early<=10:00", "early<=10:00", "mid<=13:00", "mid<=13:00", "late>13:00"]
    assert A.seal_time_bucket(None) == "unknown" and A.seal_time_bucket("noon") == "unknown"
    assert [A.ladder_bucket(v) for v in (0, 2, 5)] == ["0", "2", "3"]
    assert [A.prev_peer_bucket(v) for v in (None, 0, 1, 3)] == \
        ["prev_unknown", "prev0", "prev1-2", "prev3+"]
    assert A.combo_key({"streak": 3, "boardN": 6, "time": "09:30:00"}) == \
        "streak3|n5-7|early<=10:00"


def test_rank_board_stocks_orders_by_streak_then_time():
    stocks = [
        {"code": "b", "streak": 2, "time": "09:30:00"},
        {"code": "a", "streak": 2, "time": "10:30:00"},
        {"code": "c", "streak": 3, "time": "14:00:00"},
        {"code": "d", "streak": None, "time": "09:00:00"},
        {"code": "e", "streak": 2, "time": None},
    ]
    assert [s["code"] for s in A.rank_board_stocks(stocks)] == ["c", "b", "a", "e", "d"]
    assert [s["code"] for s in stocks] == ["b", "a", "c", "d", "e"], "不得原地改输入"


def _rows():
    def mk(streak, boardN, time, cont):
        return {"streak": streak, "boardN": boardN, "time": time, "continued": cont}
    return [
        mk(4, 9, "09:20:00", True), mk(4, 8, "09:40:00", True), mk(4, 9, "13:30:00", False),
        mk(3, 6, "09:10:00", True), mk(3, 6, "10:05:00", False), mk(3, 5, "11:00:00", True),
        mk(2, 3, "09:00:00", False), mk(1, 1, "14:00:00", False), mk(1, 2, "09:50:00", True),
    ]


def test_rates_and_min_sample_gate():
    rows = _rows()
    assert A.group_rates(rows, lambda r: A.streak_bucket(r["streak"]))["4+"] == \
        {"cont": 2, "n": 3, "rate": 0.6667}
    combo = A.combo_rates(rows, min_n=2)
    assert combo["streak4+|n>=8|early<=10:00"] == {"cont": 2, "n": 2, "rate": 1.0}
    assert "streak1|n1-2|late>13:00" not in combo, "样本 <min_n 的组合桶不得出率"
    s = A.summarize_rows(rows, min_combo_n=2)
    assert s["leaders"] == 9 and s["continued"] == 5 and s["rate"] == 0.5556
    assert set(s) >= {"byStreak", "byBoardCount", "bySealTime", "byFollowers", "byPrevPeers", "combo"}


def test_baseline_line_discloses_small_samples_and_falls_back():
    rows = _rows()
    strong = {"streak": 4, "boardN": 9, "time": "09:20:00"}
    line = A.baseline_line(rows, strong, min_combo_n=2)
    assert "同桶[streak4+|n>=8|early<=10:00] 历史次日连板率 100.0%（2 样本）" in line
    assert "按连板高度[4+]" in line and "按板块家数[>=8]" in line and "总体" in line

    weak = {"streak": 1, "boardN": 2, "time": "09:50:00"}
    line2 = A.baseline_line(rows, weak, min_combo_n=5)
    assert "样本不足（<5），不出率" in line2, "小样本必须明说，不给假高率"
    assert "按连板高度[1]" in line2, "组合桶不足时回退到单维桶（标注样本量）"


def test_baseline_line_surfaces_seal_time_followers_prev_peers_tiers():
    """2026-10-24c：封板时间/跟风梯队/昨日承接三组桶率透出（此前已算仅落审计）。

    verylow 判据「板块家数少+封板晚+无梯队」三维度语料都有对应率；缺字段（旧形状
    历史行）的维如实不出行，不伪造。
    """
    rows = [
        {"streak": 2, "boardN": 5, "time": "09:20:00", "ladderFollowers": 2,
         "prevPeers": 1, "continued": True},
        {"streak": 2, "boardN": 6, "time": "09:30:00", "ladderFollowers": 2,
         "prevPeers": 2, "continued": True},
        {"streak": 3, "boardN": 5, "time": "09:10:00", "ladderFollowers": 2,
         "prevPeers": 0, "continued": False},
        {"streak": 1, "boardN": 2, "time": "14:00:00", "ladderFollowers": 0,
         "prevPeers": None, "continued": False},
    ]
    row = {"streak": 2, "boardN": 5, "time": "09:25:00", "ladderFollowers": 2,
           "prevPeers": 1}
    line = A.baseline_line(rows, row, min_combo_n=8)
    assert "按封板时间[early<=10:00] 66.7%（3 样本）" in line
    assert "按跟风梯队[2] 66.7%（3 样本）" in line
    assert "按昨日承接[prev1-2] 100.0%（2 样本）" in line
    # 旧形状（无 ladderFollowers/prevPeers 字段）→ 两维不出行，不报错不伪造
    legacy = A.baseline_line(_rows(), {"streak": 4, "boardN": 9, "time": "09:20:00"})
    assert "按跟风梯队" not in legacy and "按昨日承接" not in legacy


def test_structure_line_marks_unknown_prev():
    line = A.structure_line(board="机器人", board_n=5,
                            leader={"name": "大业股份", "code": "603278", "streak": 3,
                                    "time": "09:25:00"},
                            followers_ge_ladder=1, prev_board_n=None, prev_peers=None)
    assert "板块「机器人」今日封板 5 家" in line and "3 连板" in line and "首封 09:25:00" in line
    assert "昨日同板块不可考" in line
    assert "家数序列" not in line, "history 未传（None）不出序列段——向后兼容旧调用"

    line2 = A.structure_line(board="机器人", board_n=5,
                             leader={"name": "X", "code": "1", "streak": None, "time": None},
                             followers_ge_ladder=0, prev_board_n=3, prev_peers=1)
    assert "连板高度不可算" in line2 and "时间不可考" in line2
    # 2026-10-24c 口径修正：prev_board_n 语义=昨日封板且今日仍封；prev_total 未传时
    # 不得再把仍封数冒充「昨日封板 N 只」（旧文案吞掉断板数）
    assert "昨日该板块封板总数不可考（今日仍封 3 只）" in line2


def test_structure_line_prev_total_surfaces_duanban():
    """prev_total（2026-10-24c）= 昨日封板总数：断板 = 总数 − 仍封，显式给出。

    2026-10-24d：断板优先用 prev_still（昨日**同名板块**封板股中今日仍封，恒 ≥0）——
    prev_board_n 是今日成员交集（含昨日他板块迁入股），迁移场景减出负数甚至
    「昨日封 0 仍封 2」自相矛盾（2026-10-24 review 实测三例）。
    """
    line = A.structure_line(board="机器人", board_n=5,
                            leader={"name": "大业", "code": "1", "streak": 3, "time": "09:25"},
                            followers_ge_ladder=1, prev_board_n=3, prev_peers=2, prev_total=6)
    assert "昨日该板块封板 6 只，今日仍封 3 只（断板 3）" in line, "无 prev_still 兼容形状退回成员口径"
    # 同名口径：prev_still 在 → 断板 = prevTotal − prevStill（与成员口径的迁入失真无关）
    line_same = A.structure_line(board="AI应用", board_n=7,
                                 leader={"name": "X", "code": "2", "streak": 3, "time": "09:30"},
                                 followers_ge_ladder=2, prev_board_n=4, prev_peers=2,
                                 prev_total=3, prev_still=2)
    assert "昨日该板块封板 3 只，今日仍封 2 只（断板 1）" in line_same, \
        "同名口径：昨日他板块迁入的 2 只不计入仍封/断板（成员口径会算出断板 -1）"
    # 迁移场景无 prev_still（兼容形状）：差值为负 → 断板不可算，不出负数
    line_neg = A.structure_line(board="AI应用", board_n=7,
                                leader={"name": "X", "code": "2", "streak": 3, "time": "09:30"},
                                followers_ge_ladder=2, prev_board_n=4, prev_peers=2,
                                prev_total=3)
    assert "（断板不可算）" in line_neg and "断板 -1" not in line_neg
    # 仍封数缺失（防御分支，生产不可达）→ 断板不可算，不泄漏原始 None
    line2 = A.structure_line(board="机器人", board_n=5,
                             leader={"name": "X", "code": "1", "streak": 2, "time": "09:30"},
                             followers_ge_ladder=0, prev_board_n=None, prev_peers=0,
                             prev_total=6)
    assert "昨日该板块封板 6 只，今日仍封不可考（断板不可算）" in line2
    assert "None" not in line2


def test_board_ladder_line_shape_and_second_streak():
    """板内梯队形态行（2026-10-24c）：首板潮/中军/高标分化直接可读；旧形状行 → None。"""
    row = {"streak": 5, "secondStreak": 3,
           "ladderShape": {"first": 4, "two": 1, "threePlus": 2, "unknown": 1}}
    line = A.board_ladder_line(row)
    assert line == ("板块梯队形态：首板 4 家 / 2板 1 家 / 3板+ 2 家（另有 1 只连板高度不可算）；"
                    "龙头 5 板，次高 3 板（领先 +2）")
    # 孤军：板内无其它可算真连板 → 次高如实不可考
    solo = A.board_ladder_line({"streak": 3, "secondStreak": None,
                                "ladderShape": {"first": 2, "two": 0, "threePlus": 1,
                                                "unknown": 0}})
    assert "次高 不可考（板内无其它可算真连板）" in solo
    # 龙头高度不可算 / 旧代行（无 ladderShape）→ 各自如实
    assert "龙头连板高度不可算" in A.board_ladder_line(
        {"streak": None, "secondStreak": None,
         "ladderShape": {"first": 1, "two": 0, "threePlus": 0, "unknown": 0}})
    assert A.board_ladder_line({"streak": 3}) is None


def test_board_zhaban_line_today_and_prev():
    """板内炸板面行（2026-10-24c）：今日触板未封；昨日不可考只出今日，不伪造对比。"""
    assert A.board_zhaban_line({"zhabanN": 4, "prevZhabanN": 2}) == \
        "板内炸板面：今日触板未封 4 家（昨日 2 家）"
    assert A.board_zhaban_line({"zhabanN": 0}) == "板内炸板面：今日触板未封 0 家"
    assert A.board_zhaban_line({}) is None, "旧代行/字段缺失 → 不出行，不写 0 冒充"


def test_structure_line_renders_board_count_history():
    """S1（2026-10-24b）：近 N 日家数序列让判据「扩张中/萎缩」从两点变形状。

    缺口日（板块名逐日未收录/THS 池缺失）如实不列，不插值；空序列=不可考，不伪装趋势。
    """
    line = A.structure_line(board="机器人", board_n=13,
                            leader={"name": "大业", "code": "1", "streak": 5, "time": "09:30:00"},
                            followers_ge_ladder=0, prev_board_n=1, prev_peers=0,
                            history=[("2026-10-16", 9), ("2026-10-17", 13),
                                     ("2026-10-20", 12), ("2026-10-21", 1), ("2026-10-22", 1)])
    assert "近 5 日该板块封板家数（旧→新，缺口日不列）：10-16 9 · 10-17 13 · 10-20 12 · 10-21 1 · 10-22 1" in line

    empty = A.structure_line(board="机器人", board_n=3,
                             leader={"name": "X", "code": "1", "streak": 1, "time": "10:00:00"},
                             followers_ge_ladder=0, prev_board_n=None, prev_peers=None,
                             history=[])
    assert "家数序列不可考" in empty


def _cycle_rows():
    """龙头-日样本（date 轴 10-13~10-17 五个交易日）：

    - A：2→3→4 板连板周期 10-15 断板（continued=False）→ 终结确认，剩余 2/1/0
    - B：1→2 后让位（10-15 无样本）10-17 又以 3 板出现 → 两段皆右删失（次日仍封/隔日断流）
    - C：单日 1 板次日断 → 终结确认，剩余 0
    - D：1 板（次日仍封=True）→ 删失；隔两日以 2 板出现且次日断 → 终结，剩余 0
    - E：streak +2 跳变（2→4）切段；前段删失、后段终结（板宽 9 家，与查询行同组合桶）
    """
    def mk(code, date, streak, cont, boardN=6, time="09:30:00"):
        return {"code": code, "date": date, "streak": streak, "continued": cont,
                "boardN": boardN, "time": time}
    return [
        mk("A", "2026-10-13", 2, True), mk("A", "2026-10-14", 3, True),
        mk("A", "2026-10-15", 4, False, boardN=9),
        mk("B", "2026-10-13", 1, True), mk("B", "2026-10-14", 2, True),
        mk("B", "2026-10-17", 3, True),
        mk("C", "2026-10-14", 1, False),
        mk("D", "2026-10-13", 1, True), mk("D", "2026-10-16", 2, False),
        mk("E", "2026-10-13", 2, True), mk("E", "2026-10-14", 4, False, boardN=9),
    ]


def test_leader_cycles_segments_and_censoring():
    """周期切段：date 相邻 + streak 严格 +1 才延续；段尾 continued≠False = 右删失整段剔。"""
    kept, censored = A._leader_cycles(_cycle_rows())
    by_key = {(r["code"], r["date"]): v for r, v in kept}
    assert by_key == {("A", "2026-10-13"): 2, ("A", "2026-10-14"): 1, ("A", "2026-10-15"): 0,
                      ("C", "2026-10-14"): 0,
                      ("D", "2026-10-16"): 0, ("E", "2026-10-14"): 0}
    # B 全删失 3；D 前段 1；E 前段 1
    assert censored == 5
    # streak None（真连板不可算）不进锚
    kept2, _ = A._leader_cycles([{"code": "F", "date": "2026-10-13", "streak": None,
                                  "continued": False, "boardN": 3, "time": "09:30:00"}])
    assert kept2 == []


def test_headroom_anchor_line_fallbacks_and_disclosure():
    """锚行与 baseline_line 同构：桶回退 + 样本量/删失全披露；无可用周期 → None。"""
    row = {"streak": 4, "boardN": 9, "time": "09:20:00"}
    line = A.headroom_anchor_line(_cycle_rows(), row, min_combo_n=2)
    assert line.startswith("空间锚（口径=历史窗内板块龙头连板周期，右删失已剔）：")
    assert "剔右删失周期样本 5 个" in line and "总体平均再走" in line
    # 同桶（streak4+|n>=8|early）内 A10-15 与 E10-14 两样本（剩余均 0）→ 组合桶成立出锚
    assert "同桶[streak4+|n>=8|early<=10:00] 历史自当日高度平均再走 0.0 板" in line
    # 小样本桶明说不出锚
    tight = A.headroom_anchor_line(_cycle_rows(), {"streak": 2, "boardN": 3, "time": "13:30:00"},
                                   min_combo_n=8)
    assert "样本不足（<8），不出锚" in tight and "按连板高度[2] 平均再走" not in tight
    # 无历史样本 / 全删失 → None（叙事不出行，不编造基准）
    assert A.headroom_anchor_line([], row) is None
    all_censored = [{"code": "G", "date": "2026-10-13", "streak": 2, "continued": True,
                     "boardN": 5, "time": "09:30:00"}]
    assert A.headroom_anchor_line(all_censored, row) is None


def test_narrative_order_is_fixed_and_keeps_fail_visible_text():
    ev = ("【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】\n"
          "题材语料（韭研产业树 + 开盘啦事件层）未采集（fail-visible：无数据 ≠ 无催化）。\n"
          "板块级催化：未映射（不代表无催化）")
    text = A.build_leader_narrative(
        date="2026-10-19", market_line="涨停 46 家", structure="板块「X」今日封板 2 家",
        baseline="结构基线：总体 32.6%", evidence_block=ev,
        leader_name="东方嘉盛", leader_code="002889")
    lines = text.splitlines()
    assert lines[0].startswith("2026-10-19 交易日 · 涨停 46 家")
    assert lines[1] == "待判龙头：东方嘉盛（002889）"
    assert lines[2] == "板块「X」今日封板 2 家" and lines[3] == "结构基线：总体 32.6%"
    assert lines[4].startswith("【题材证据"), "证据块紧跟结构行（2026-10-24a 起无 corpus_line 头行）"
    assert text.endswith(ev), "证据块必须原样嵌在末尾，不得被 runner 二次改写"
    assert "未映射（不代表无催化）" in text and "未采集" in text


def test_narrative_order_with_2026_10_24c_lines():
    """2026-10-24c 三行固定序：前向轴紧跟盘面行，梯队/炸板面紧跟结构行，均 None 不出行。"""
    ev = "【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】\n取数日 2026-10-23"
    text = A.build_leader_narrative(
        date="2026-10-23", market_line="涨停 81 家",
        forward_axis="交易日轴（前向）：下一交易日 2026-10-26（周一）",
        structure="板块「X」今日封板 3 家",
        ladder_line="板块梯队形态：首板 1 家 / 2板 1 家 / 3板+ 1 家",
        zhaban_line="板内炸板面：今日触板未封 2 家（昨日 0 家）",
        baseline="结构基线：总体 33.9%", evidence_block=ev,
        leader_name="华林证券", leader_code="002945")
    lines = text.splitlines()
    assert lines[0].startswith("2026-10-23 交易日") and lines[1].startswith("交易日轴（前向）")
    assert lines[2] == "待判龙头：华林证券（002945）"
    assert lines[3].startswith("板块「X」") and lines[4].startswith("板块梯队形态")
    assert lines[5].startswith("板内炸板面") and lines[6].startswith("结构基线")
    assert lines[7].startswith("【题材证据")
    # 三行全 None → 回到旧形状（行序向后兼容）
    old = A.build_leader_narrative(
        date="2026-10-23", market_line="涨停 81 家", structure="板块「X」今日封板 3 家",
        baseline="结构基线：总体 33.9%", evidence_block=ev,
        leader_name="华林证券", leader_code="002945").splitlines()
    assert old[1] == "待判龙头：华林证券（002945）" and old[4].startswith("【题材证据")


def test_narrative_places_headroom_anchor_between_baseline_and_evidence():
    """Q1（2026-10-24b）：空间锚行排在基线后、证据块前（固定行序，便于逐字复现）。"""
    ev = "【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】\n取数日 2026-10-23"
    anchor = "空间锚（口径=历史窗内板块龙头连板周期，右删失已剔）：同桶[x] 0.0 板"
    text = A.build_leader_narrative(
        date="2026-10-23", market_line="涨停 81 家", structure="板块「X」今日封板 3 家",
        baseline="结构基线：总体 33.9%", evidence_block=ev,
        leader_name="华林证券", leader_code="002945", headroom=anchor)
    lines = text.splitlines()
    assert lines[3].startswith("结构基线") and lines[4] == anchor
    assert lines[5].startswith("【题材证据"), "锚行紧贴证据块之前，None 时证据块直接跟基线"


def test_evidence_gate_forces_insufficient_and_keeps_model_answer():
    """v2 确定性门：证据缺失 → 概率题强制 insufficient；原答必须留档（不丢模型真实输出）。"""
    answers = {"leader_nextday_continue": {"type": "choice", "choice": "mid_45_65",
                                          "confidence": 0.3, "probabilities": {"mid_45_65": 0.6}},
               "catalyst_stage": {"type": "choice", "choice": "insufficient"}}
    out, gate = A.apply_evidence_gate(answers, {"evidenceMissing": True,
                                                "evidenceMissingReason": "board_unmapped"})
    assert out["leader_nextday_continue"]["choice"] == "insufficient"
    assert out["leader_nextday_continue"]["probabilities"] == {"insufficient": 1.0}
    assert out["leader_nextday_continue"]["gateReason"] == "board_unmapped"
    assert out["catalyst_stage"] == answers["catalyst_stage"], "只覆盖概率题，不动催化题"
    assert gate["applied"] is True and gate["reason"] == "board_unmapped"
    assert gate["modelChoice"] == "mid_45_65" and gate["modelProbabilities"] == {"mid_45_65": 0.6}
    assert "未映射" in gate["label"]


def test_evidence_gate_passes_through_when_evidence_present():
    """有催化正文（哪怕陈旧）→ 不改写：stale 是证据，不是缺失。"""
    answers = {"leader_nextday_continue": {"type": "choice", "choice": "low_25_45"}}
    for ev in ({"evidenceMissing": False, "evidenceMissingReason": None}, {},
               {"evidenceMissing": True}):   # 最后一条：缺失但无原因 → 仍要门住（reason=unknown）
        out, gate = A.apply_evidence_gate(answers, ev)
        if ev.get("evidenceMissing"):
            assert gate["applied"] is True and out["leader_nextday_continue"]["choice"] == "insufficient"
        else:
            assert gate["applied"] is False and out is answers


def test_gate_holds_when_previously_gated_answer_reruns():
    """幂等/重跑安全：已是 insufficient 的答案再过门不报错、不重复覆盖（forcedKeys 不含它）。"""
    out, gate = A.apply_evidence_gate(
        {"leader_nextday_continue": {"type": "choice", "choice": "insufficient"}},
        {"evidenceMissing": True, "evidenceMissingReason": "no_content_no_event"})
    assert gate["applied"] is True and gate["modelChoice"] == "insufficient"
    assert out["leader_nextday_continue"]["choice"] == "insufficient"
    # 模型已自判不足的题不重复覆盖（forcedKeys 不含它）；未作答的其余三题补强制 insufficient
    assert gate["forcedKeys"] == ["theme_speculation_depth", "theme_continuation",
                                  "leader_headroom"]


def test_gate_forces_all_four_questions_in_v5():
    """v5 四题全门：证据缺失时四题全部强制 insufficient（模型已自判不足的题不重复覆盖）；
    forcedKeys 留痕，原答在 modelAnswers 审计。"""
    answers = {"leader_nextday_continue": {"choice": "mid_45_65",
                                          "probabilities": {"mid_45_65": 0.55}},
               "theme_speculation_depth": {"choice": "fermenting"},
               "theme_continuation": {"choice": "insufficient"},
               "leader_headroom": {"choice": "space_1"}}
    out, gate = A.apply_evidence_gate(answers, {"evidenceMissing": True,
                                                "evidenceMissingReason": "industry_tree_unmapped"})
    assert gate["forcedKeys"] == ["theme_speculation_depth", "leader_nextday_continue",
                                  "leader_headroom"], "模型已自判 insufficient 的题不重复覆盖"
    assert out["theme_speculation_depth"]["choice"] == "insufficient"
    assert out["leader_headroom"]["choice"] == "insufficient"
    assert out["theme_continuation"]["choice"] == "insufficient", "原判保留"
    assert out["leader_nextday_continue"]["probabilities"] == {"insufficient": 1.0}
    assert gate["modelChoice"] == "mid_45_65"


def test_gate_reason_labels_cover_v3_and_legacy():
    """门原因标签双代覆盖：v3 新原因（industry_tree_unmapped）与 v2 历史档原因
    （board_unmapped，10-08~10-22 落库文档回读用）都必须有可读标签，不得只留一个。"""
    for reason in ("corpus_not_collected", "board_unmapped", "industry_tree_unmapped",
                   "no_content_no_event"):
        assert reason in A.GATE_REASON_LABELS and A.GATE_REASON_LABELS[reason]
    out, gate = A.apply_evidence_gate(
        {"leader_nextday_continue": {"type": "choice", "choice": "mid_45_65",
                                     "probabilities": {"mid_45_65": 0.55}}},
        {"evidenceMissing": True, "evidenceMissingReason": "industry_tree_unmapped"})
    assert gate["applied"] is True and gate["reason"] == "industry_tree_unmapped"
    assert "产业树未映射" in gate["label"]
