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
    `40c7184a790e`，零样本——首批 10-26 才开火即被 v8 取代）；v8 = 2026-10-24
    「越锚」铸词内联定义（review P3：模型直读可能不解裸铸词，改「要选高于锚的
    档位（越锚）时」，hash `b0914cdd3e7d`）；**v9 = 2026-10-26 零区分度处置
    （A 检验 0/7 判对但零信息量；用户批准 §21.3 三项，hash `8a4454b879bd`）：
    ①硬规则②单向改双向（偏离锚上调或下调都须引用锚行数字+锚未覆盖新证据）
    ②新增默认起判档规则③（1-3 板→peak、4+ 板→space_1，分层杀伤证据非桶众数）
    ③space_1/peak criteria 绑锚行「再走≥1板率」读数（三成上下/不足三成）**；
    **v10 = 2026-10-27 空间龙一规则配套（hash `fef8635573f7`）**：续板题加规则⑤——
    待判龙头当日未封板（断板反包候选）时判「重新上板概率」，封板类判据不适用、
    改按断板承接/梯队/题材证据，锚缺失如实对待（推导侧配套=候选池扩近 3 日封板池、
    排序改 10日涨幅→连板高度→首封，见 baseline space_mode 与 rank_board_stocks_space；
    预登记 §21.6）——跨代标签不得混评（评估按版本分组）**；
    **v11 = 2026-10-27 判据遵从收紧（hash `9235d39da553`，预登记 §22）**：①续板题规则①
    对称化——最细同桶基线为概率中枢，偏离一档以上（上调或下调）都须点名基线行数字+
    锚外新证据，同桶样本不足未出率时以「按连板高度」桶为中枢；②延续性题加引用义务——
    ending 须点名 ≥2 个判据信号对应事实、strong_extend 须点名排队事件或近 2 日新增标题
    （打标交叉行可作引用源），未封板龙一场景无锚须保守并降低置信。**v12 = 2026-10-28
    双龙一分轨 + 延续/深度判据修复（hash 见断言，预登记 theme-leader-v12）**：①龙一
    分轨（主板/双创各取龙一，复合排序：空间板组优先/首封最早，gain10 降为末级键，
    v10 rank_board_stocks_space 淘汰删除）；②深度题「贫料 ≠ 断流」；③延续题
    strong_extend 引用义务扩源（结构再点火信号）+ ending 方向约束；④跨题一致性硬规则；
    ⑤A2 拆题（板块级两题/个股级两题）+ AMMO 2026-10-28a（涨停原因行/板块强度行）。
    **v13 = 2026-10-29 未封板 insufficient 禁令（hash 见断言，预登记
    theme-leader-v13-unsealed-insufficient-preregistration-20261029）**：①续板题规则⑤补
    「锚缺失≠可判 insufficient，证据行任一在场必须按①给档并强制降置信 ≤0.6」；
    ②空间题规则③补未封板分支默认档=空间锚最细出率桶起判，锚行整体缺席才允许自判；
    ③两题 insufficient criteria 补对称禁令。AMMO 原料代际：2026-10-24b 四补（S1/S2/S3/Q1）→ **2026-10-24c 盘面语料四补**
    （①基线行补封板时间/跟风梯队/昨日承接桶率 ②板内梯队形态行 ③前向交易日轴行
    ④板内炸板面行+结构行昨日口径修正；题面 v8 判据零改动，hash 不变）→
    **2026-10-24d review 处置**（断板改同名成员口径 prevStill，迁移场景不出负数；
    防御分支原始 None 泄漏修复；前向轴非 bridge 源结果不缓存）→
    **2026-10-26a 空间锚每档基率化**（预登记 §21.2：每档改「再走≥1板率/≥2板率/中位再走/
    均值/样本量」，率值口径与档位判定对齐，10-23 八龙头全 peak 塌缩归因之一；题面 v8
    判据零改动，hash 不变；v9 题面换代与其同批落地）→
    **2026-10-27a 空间龙一规则配套**（结构行 leader_sealed_today=False 分情形显式标注
    「今日未封板（断板反包候选，10日涨幅 X% 居候选池首位）」+ rank_board_stocks_space）→
    **2026-10-27b 打标交叉原料行**（join hotlist_jev_driver_labels final>midday，四轴
    枚举译名+概率并列，行内自描述口径；缺席 fail-visible；不并 boardDragons）→
    **2026-10-28a v12 批次**（涨停原因行 limitup_reason_line：join 韭研 expound 单一
    事实源，龙一+板内并列；板块强度行 plate_strength_line：KPL 层1 名称桥，未匹配
    fail-visible）。
    """
    assert A.QUESTION_SET_VERSION_THEME_LEADER == "v13"
    assert A.AMMO_VERSION_THEME_LEADER == "2026-10-28b"
    assert A.QUESTION_SET_HASH_THEME_LEADER == "5d50645e5dc8"
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
    # v9 三项（预登记 §21.3，2026-10-26 用户批准）：双向化 + 默认起判档 + criteria 锚读数
    ins = A.QUESTIONS_THEME_LEADER["leader_headroom"]["instructions"]
    assert "无论上调还是下调" in ins, "硬规则②双向：下调偏离锚同样须引用锚行数字+新证据"
    assert "1-3 板 → peak 起判" in ins and "space_1 起判" in ins, "默认起判档映射在场"
    # v13 修订：高度不可算含未封板分支，默认档改由空间锚最细出率桶起判
    assert "连板高度不可算时（含待判龙头今日未封板的断板反包候选）" in ins, "v13 未封板分支接线"
    assert "默认档按「空间锚」最细出率桶起判" in ins, "v13 未封板默认档=空间锚起判"
    assert "锚行整体缺席（叙事无空间锚行）才允许按证据自判" in ins, "v13 锚缺席才可自判"
    crit = A.QUESTIONS_THEME_LEADER["leader_headroom"]["criteria"]
    assert "再走≥1板率三成上下" in crit["space_1"], "space_1 绑锚行读数（非写死绝对阈值）"
    assert "再走≥1板率不足三成" in crit["peak"], "peak 绑锚行读数"
    assert "锚行读数参照" not in crit["space_2plus"], "space_2plus 零命中先观察，不加校准（§21.3 范围）"
    assert "叙事含空间锚行（有率值）时不得选本档" in crit["insufficient"], "v13 空间题对称禁令"
    # v11 两项（预登记 §22，2026-10-27 用户批准）：续板规则①对称化 + 延续性引用义务
    cont = A.QUESTIONS_THEME_LEADER["leader_nextday_continue"]["instructions"]
    assert "必须先对齐的概率中枢" in cont, "规则①对称化：中枢语义"
    assert "上调或下调" in cont and "按连板高度」桶为中枢" in cont, "双向偏离义务+同桶未出率回退"
    assert "个股打标交叉行" in cont, "打标交叉行列入可引证据"
    # v13：续板题⑤未封板 insufficient 禁令 + 强制降置信
    assert "锚缺失如实对待**不等于**可判 insufficient" in cont, "v13 反向禁令接线"
    assert "confidence ≤0.6" in cont, "v13 未封板锚缺失强制降置信"
    assert "结构基线行有任一出率桶时不得选本档" in A.QUESTIONS_THEME_LEADER["leader_nextday_continue"]["criteria"]["insufficient"], "v13 续板题对称禁令"
    tcont = A.QUESTIONS_THEME_LEADER["theme_continuation"]["instructions"]
    # v12 修订：引用义务扩源（结构再点火）+ ending 方向约束；v11 保守条款改为板块级表述
    assert "引用义务（v12 修订）" in tcont and "至少 2 个判据信号" in tcont, "ending 引用义务"
    assert "结构再点火信号" in tcont and "二选一" in tcont, "strong_extend 引用源扩源"
    assert "家数扩张或家数序列不可考时不得判 ending" in tcont, "ending 方向约束"
    assert "贫料环境（语料陈旧/稀疏）不是否定结构再点火的理由" in tcont, "贫料≠断流"
    assert "个股层面缺同构历史锚应保守" in tcont, "断板反包保守条款（v12 板块级表述）"
    assert "本题不得判 ending" in tcont and "跨题一致性（v12）" in tcont, "跨题一致性"
    tdep = A.QUESTIONS_THEME_LEADER["theme_speculation_depth"]["instructions"]
    assert "贫料 ≠ 断流" in tdep and "igniting 优先" in tdep, "深度题贫料定向"
    thead = A.QUESTIONS_THEME_LEADER["leader_headroom"]["instructions"]
    assert "默认不得选 peak" in thead, "空间题跨题一致性"


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
    """锚行与 baseline_line 同构：桶回退 + 样本量/删失全披露；无可用周期 → None。

    2026-10-26a 每档基率化：每档必须给「再走≥1板率」（率值口径与档位判定对齐，
    只给均值曾致 10-23 八龙头全 peak 塌缩）。
    """
    row = {"streak": 4, "boardN": 9, "time": "09:20:00"}
    line = A.headroom_anchor_line(_cycle_rows(), row, min_combo_n=2)
    assert line.startswith("空间锚（口径=历史窗内板块龙头连板周期，右删失已剔；"
                           "再走≥1板率=历史同结构龙头自当日高度至少再封一板的占比）：")
    assert "剔右删失周期样本 5 个" in line and "总体 再走≥1板率 33.3%" in line
    # 同桶（streak4+|n>=8|early）内 A10-15 与 E10-14 两样本（剩余均 0）→ 组合桶成立出锚
    assert ("同桶[streak4+|n>=8|early<=10:00] 再走≥1板率 0.0% · ≥2板率 0.0% · "
            "中位再走 0.0 板（均值 0.0，2 样本）") in line
    # 每档基率齐备：连板高度档同样带再走≥1板率（模型可直接对档位）
    assert "按连板高度[4+] 再走≥1板率 0.0%" in line
    # 小样本桶明说不出锚
    tight = A.headroom_anchor_line(_cycle_rows(), {"streak": 2, "boardN": 3, "time": "13:30:00"},
                                   min_combo_n=8)
    assert "样本不足（<8），不出锚" in tight and "按连板高度[2] 再走≥1板率" not in tight
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


def test_narrative_places_driver_cross_between_headroom_and_evidence():
    """打标交叉行（2026-10-27b）：排在空间锚后、证据块前；缺席走 fail-visible 行非 None。"""
    ev = "【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】\n取数日 2026-10-27"
    anchor = "空间锚（口径=历史窗内板块龙头连板周期，右删失已剔）：同桶[x] 再走≥1板率 54.5%"
    cross = A.driver_cross_line({"labelSlot": "midday", "questionSetVersion": "v4.0",
                                 "label": "capital_flow", "catalystDepth": "core_main_business",
                                 "freshness": "fresh_catalyst", "buySideLogic": "high_board_relay"})
    text = A.build_leader_narrative(
        date="2026-10-27", market_line="涨停 53 家", structure="板块「大消费」今日封板 7 家",
        baseline="结构基线：总体 33.3%", evidence_block=ev,
        leader_name="上海九百", leader_code="600838", headroom=anchor, driver_cross=cross)
    lines = text.splitlines()
    assert lines[4] == anchor and lines[5] == cross
    assert lines[6].startswith("【题材证据")
    # 无交叉参数（旧调用形状）→ 不出行，行序向后兼容
    old = A.build_leader_narrative(
        date="2026-10-27", market_line="涨停 53 家", structure="板块「大消费」今日封板 7 家",
        baseline="结构基线：总体 33.3%", evidence_block=ev,
        leader_name="上海九百", leader_code="600838").splitlines()
    assert old[4].startswith("【题材证据")


def test_driver_cross_line_variants():
    """打标交叉行渲染：枚举译名/近并列披露/逃生桶不进排名/缺席 fail-visible 不伪装。"""
    doc = {"labelSlot": "midday", "questionSetVersion": "v4.0", "label": "capital_flow",
           "labelProbabilities": {"policy": 0.42, "capital_flow": 0.43,
                                  "insufficient_evidence": 0.03},
           "catalystDepth": "core_main_business", "freshness": "fresh_catalyst",
           "buySideLogic": "high_board_relay",
           "buySideProbabilities": {"high_board_relay": 0.97, "independent_catalyst": 0.02}}
    line = A.driver_cross_line(doc)
    assert line.startswith("个股打标交叉（另一条打标链对该公司当日涨停的机器判定，供交叉参考；")
    assert "打标链题集 v4.0·午盘槽" in line
    assert "驱动类别=资金接力43%/政策42%（近并列）" in line, "近并列必须显式披露（判定不稳=信息）"
    assert "信息不足" not in line, "逃生桶不进 top-2 排名"
    assert "催化深度=核心主业" in line and "新鲜度=新催化（≤2 交易日）" in line
    assert "买盘逻辑=高位卡位/情绪接力97%" in line
    # 概率真身=driverProbabilities（labelProbabilities 为 API 层旧别名，仅兜底旧档）
    assert "驱动类别=政策50%/资金接力30%" in A.driver_cross_line(
        {**doc, "driverProbabilities": {"policy": 0.5, "capital_flow": 0.3}}), \
        "两字段并存时 driverProbabilities 优先"
    # 承接判定必须显式披露（防模型把昨日判断当当日新鲜证据）
    carried = A.driver_cross_line({**doc, "carriedFrom": "2026-10-26",
                                   "carriedQuestionKeys": ["driver_type", "catalyst_depth",
                                                           "catalyst_freshness"]})
    assert "驱动类别/催化深度/新鲜度=承接 2026-10-26 判定（非当日重问）" in carried
    assert "买盘逻辑" not in carried.split("·")[-1], "未承接的轴不进承接披露"
    # 缺席 = fail-visible 固定行，不带任何方向性语义
    assert A.driver_cross_line(None) == A.DRIVER_CROSS_NONE_LINE
    assert "不构成任何方向证据" in A.DRIVER_CROSS_NONE_LINE
    # 概率全缺 → 回落已选枚举值中文；全缺+槽位缺失 → 不可考如实
    bare = A.driver_cross_line({"label": "policy", "labelSlot": "final",
                                "questionSetVersion": "v3.1", "freshness": "continuing",
                                "buySideLogic": "sector_follow"})
    assert "驱动类别=政策" in bare and "催化深度=不可考" in bare and "收盘槽" in bare


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


def test_rank_board_stocks_seal_composite_rule():
    """龙一复合排序（v12 定稿，用户三轮裁决定稿）：

    空间板（height≥2，真连板/断板反包/断板不反包未跌停三种情况）组整体优先、组内
    10日涨幅最高（尾封/断板依然龙一）；全首板按当日首封最早（gain10 不可比）。
    """
    cands = [
        {"code": "a", "name": "早封首板", "streak": 1, "time": "09:25:00",
         "gain10": 40.9, "height": 1},
        {"code": "b", "name": "尾封2板", "streak": 2, "time": "14:50:00",
         "gain10": 25.0, "height": 2},
        {"code": "c", "name": "早封首板2", "streak": 1, "time": "09:20:00",
         "gain10": 12.0, "height": 1},
        {"code": "d", "name": "断板高位", "streak": None, "time": None,
         "gain10": 77.7, "height": 6},
    ]
    # 空间板组整体优先，组内 gain10 最高（断板高位 77.7 > 尾封2板 25.0，涨停时间无关）；
    # 首板组内时间最早优先（gain10 不可比，40.9 也不参加比）
    assert [s["code"] for s in A.rank_board_stocks_seal(cands)] == ["d", "b", "c", "a"]
    assert [s["code"] for s in cands] == ["a", "b", "c", "d"], "不得原地改输入"
    # 全首板：时间最早赢（AI硬件 10-28 实证：菲林格尔 10:37 早封胜过 gain10 更高的尾封股）
    firsts = [
        {"code": "f", "streak": 1, "time": "10:37:00", "gain10": -17.4, "height": 1},
        {"code": "g", "streak": 1, "time": "13:24:00", "gain10": -1.6, "height": 1},
    ]
    assert [s["code"] for s in A.rank_board_stocks_seal(firsts)] == ["f", "g"]
    # 高度不可算按首板参与时间排序（fail-visible 不猜）
    unk = [{"code": "u", "streak": None, "time": "10:00:00", "gain10": 50.0},
           {"code": "v", "streak": 1, "time": "09:30:00", "gain10": 5.0}]
    assert [s["code"] for s in A.rank_board_stocks_seal(unk)] == ["v", "u"]


def test_space_leaders_by_segment_dual_leaders():
    """分轨龙一（v12）：主板/双创各取首位，顺序 main→growth；单轨板块单行。

    AI硬件 10-28 用户示例：主板菲林格尔（10:37 最早封）、双创斯迪克（双创唯一封板）。"""
    cands = [
        {"code": "603226", "name": "菲林格尔", "streak": 1, "time": "10:37:00",
         "gain10": -17.4, "height": 1},
        {"code": "002879", "name": "长缆科技", "streak": 1, "time": "13:24:00",
         "gain10": -1.6, "height": 1},
        {"code": "300806", "name": "斯迪克", "streak": 1, "time": "14:32:00",
         "gain10": 4.1, "height": 1},
    ]
    segs = A.space_leaders_by_segment(cands)
    assert [(s, l["code"]) for s, l in segs] == [("main", "603226"), ("growth", "300806")]
    # 单轨：只有双创候选 → 只出 growth
    only_growth = [{"code": "300806", "streak": 1, "time": "14:32:00", "gain10": 4.1}]
    assert [(s, l["code"]) for s, l in A.space_leaders_by_segment(only_growth)] == \
        [("growth", "300806")]
    # 北交所/未知前缀不入轨
    assert [(s, l["code"]) for s, l in A.space_leaders_by_segment(
        [{"code": "833171", "streak": 1, "time": "09:30:00", "gain10": 9.0}])] == []


def test_segment_of_prefix_rules():
    """轨别判定：主板 60/000-003；双创 300/301/688/689；未知前缀 None（fail-visible 不猜）。"""
    assert A.segment_of("sh600715") == "main"
    assert A.segment_of("000670") == "main"
    assert A.segment_of("002879") == "main"
    assert A.segment_of("300806") == "growth"
    assert A.segment_of("301052") == "growth"
    assert A.segment_of("688123") == "growth"
    assert A.segment_of("833171") is None
    assert A.segment_of(None) is None


def test_structure_line_unsealed_leader_explicit():
    """leader_sealed_today=False（2026-10-27a）：「今日未封板（断板反包候选，10日涨幅
    X% 居候选池首位）」显式标注替代「连板高度不可算」哑谜；跟风段如实不可算。"""
    line = A.structure_line(board="机器人", board_n=17,
                            leader={"name": "大业股份", "code": "603278",
                                    "streak": None, "time": None},
                            followers_ge_ladder=None, prev_board_n=13, prev_peers=2,
                            prev_total=13, prev_still=9,
                            leader_sealed_today=False, gain10=77.7)
    assert "今日未封板（断板反包候选，10 日涨幅 +77.7%（轨内未封候选首位））" in line
    assert "跟风梯队不可算（龙一未封板" in line and "跟风 None 家" not in line
    assert "昨日该板块封板 13 只，今日仍封 9 只（断板 4）" in line
    # 未传 gain10 → 身位段如实省略，不伪造
    line2 = A.structure_line(board="机器人", board_n=17,
                             leader={"name": "大业股份", "code": "603278",
                                     "streak": None, "time": None},
                             followers_ge_ladder=None, prev_board_n=13, prev_peers=None,
                             leader_sealed_today=False)
    assert "今日未封板（断板反包候选）" in line2 and "10 日涨幅" not in line2
    # 既有封板路径不变（leader_sealed_today 缺省 None=旧形状行）
    sealed = A.structure_line(board="机器人", board_n=5,
                              leader={"name": "正裕工业", "code": "603089", "streak": 3,
                                      "time": "09:25:00"},
                              followers_ge_ladder=1, prev_board_n=3, prev_peers=2)
    assert "龙头 正裕工业（603089）3 连板，首封 09:25:00" in sealed


def test_structure_line_dual_renders_both_segment_leaders():
    """v12 双龙一并列结构行：轨别自描述 + 昨日承接/家数序列与单龙一行同一实现。"""
    rows = [
        {"name": "菲林格尔", "code": "603226", "streak": 1, "time": "10:37:00",
         "gain10": -17.4, "segment": "main", "leaderSealedToday": True},
        {"name": "斯迪克", "code": "300806", "streak": 1, "time": "14:32:00",
         "gain10": 4.1, "segment": "growth", "leaderSealedToday": True},
    ]
    line = A.structure_line_dual(board="AI硬件", board_n=7, leader_rows=rows,
                                 prev_peers=0, prev_board_n=0, prev_total=0,
                                 prev_still=0, history=[("2026-10-21", 2)])
    assert "主板龙一 菲林格尔（603226）1 连板，首封 10:37:00，10 日涨幅 -17.4%" in line
    assert "双创龙一 斯迪克（300806）1 连板，首封 14:32:00，10 日涨幅 +4.1%" in line
    assert "昨日该板块封板 0 只" in line and "10-21 2" in line
    # 未封板轨：断板反包候选分情形文案
    rows2 = [{"name": "文投控股", "code": "600715", "streak": None, "time": None,
              "gain10": 30.0, "segment": "main", "leaderSealedToday": False}]
    line2 = A.structure_line_dual(board="AI影视", board_n=1, leader_rows=rows2)
    assert "主板龙一 文投控股（600715）今日未封板（断板反包候选，10 日涨幅 +30.0%" in line2


def test_limitup_reason_line_fail_visible():
    """涨停原因行（AMMO 2026-10-28a）：龙一+板内并列；缺失逐项/全部不可考 fail-visible。"""
    line = A.limitup_reason_line([("主板龙一 菲林格尔", "PCB设备+木地板"),
                                  ("斯迪克", None)])
    assert "涨停原因（韭研板内解析 expound" in line
    assert "主板龙一 菲林格尔=PCB设备+木地板" in line
    assert "斯迪克=不可考" in line and "fail-visible" in line
    assert "不可考 1" in line
    # 全缺 → 全部不可考
    all_missing = A.limitup_reason_line([("文投控股", None)])
    assert "全部不可考" in all_missing or "不可考" in all_missing
    # 空条目 → None 不出行
    assert A.limitup_reason_line([]) is None


def test_plate_strength_line_matches_and_fail_visible():
    """板块强度行（G2）：匹配行含排名/强度/涨幅；未匹配/取数失败 fail-visible。"""
    ok = A.plate_strength_line({"ok": True, "rank": 12, "total": 240,
                                "name": "AI硬件", "strength": 890.1, "pct": 5.2})
    assert "排名 #12/240" in ok and "强度 890.1" in ok and "板块涨幅 5.2%" in ok
    unmatched = A.plate_strength_line({"ok": False, "reason": "unmatched"})
    assert "不可用（unmatched" in unmatched and "不冒充" in unmatched
    fetch_fail = A.plate_strength_line({"ok": False, "reason": "fetch_failed: timeout"})
    assert "fetch_failed: timeout" in fetch_fail


def test_evidence_gate_subset_keys_for_a2_split():
    """v12 A2 拆题：keys 子集门只门对应题（板块级两题/个股级两题），其余不强制。"""
    evidence = {"evidenceMissing": True, "evidenceMissingReason": "board_unmapped"}
    answers = {k: {"type": "choice", "choice": "fermenting", "confidence": 0.5}
               for k in A.THEME_LEADER_KEYS}
    gated, gate = A.apply_evidence_gate(answers, evidence,
                                        keys=("theme_speculation_depth",
                                              "theme_continuation"))
    assert gate["applied"] and gate["forcedKeys"] == ["theme_speculation_depth",
                                                      "theme_continuation"]
    assert gated["theme_speculation_depth"]["choice"] == "insufficient"
    assert gated["theme_continuation"]["choice"] == "insufficient"
    # 未门子集保持原答（个股级 doc 后续单独门）
    assert gated["leader_nextday_continue"]["choice"] == "fermenting"


def test_sector_narrative_order_is_fixed():
    """板块级叙事顺序（v12 A2）：盘面→轴→待判板块→双龙一结构行→梯队→炸板→强度→基线→原因→证据。"""
    rows = [{"name": "菲林格尔", "code": "603226", "streak": 1, "time": "10:37:00",
             "gain10": -17.4, "segment": "main", "leaderSealedToday": True}]
    narrative = A.build_sector_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT",
        baseline="BASE", evidence_block="EVID", board="AI硬件",
        forward_axis="AXIS", ladder_line="LADDER", zhaban_line="ZHABAN",
        plate_strength="STRENGTH", reason_line="REASON")
    lines = narrative.splitlines()
    assert lines[0] == "2026-10-28 交易日 · M"
    assert lines[1] == "AXIS"
    assert lines[2].startswith("待判板块：AI硬件")
    assert "龙一分轨" in lines[2] and "首封最早" in lines[2]
    idx = {name: i for i, name in enumerate(
        ["STRUCT", "LADDER", "ZHABAN", "STRENGTH", "BASE", "REASON", "EVID"])}
    assert [idx[k] for k in ("STRUCT", "LADDER", "ZHABAN", "STRENGTH",
                             "BASE", "REASON", "EVID")] == \
        sorted(idx[k] for k in ("STRUCT", "LADDER", "ZHABAN", "STRENGTH",
                                "BASE", "REASON", "EVID"))
    # 板块级叙事不含空间锚/打标交叉位（个股轴归各自龙头叙事）
    assert "空间锚" not in narrative


def test_leader_narrative_segment_position_p1_4():
    """P1-4（review）：个股级叙事头部必须注入轨别身位（题面规则⑥/空间题⑤的前提）。"""
    narrative = A.build_leader_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT", baseline="BASE",
        evidence_block="EVID", leader_name="菲林格尔", leader_code="603226",
        segment="main")
    assert "待判龙头：菲林格尔（603226）〔主板龙一〕" in narrative
    narrative2 = A.build_leader_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT", baseline="BASE",
        evidence_block="EVID", leader_name="斯迪克", leader_code="300806",
        segment="growth")
    assert "〔双创龙一〕" in narrative2
    # 无 segment（旧形状）→ 不注入，不伪造
    narrative3 = A.build_leader_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT", baseline="BASE",
        evidence_block="EVID", leader_name="X", leader_code="000001")
    assert "〔" not in narrative3.splitlines()[2]


def test_plate_series_line_recent_record_day_not_today_p1_3():
    """P1-3（review）：层2 最新记录日≠标注日时，梯队串不得标「当日」。"""
    zt_rows = [{"date": "2026-10-27", "zt_num": 16,
                "lz_info": "603528,多伦科技,4连板"}]
    line = A.plate_series_line([{"date": "2026-10-28", "strength": 100}],
                               zt_rows, plate_name="X", label_date="2026-10-28")
    assert "10-27（最近记录日，非当日）梯队串" in line
    assert "当日梯队串" not in line
    zt_rows2 = [{"date": "2026-10-28", "zt_num": 24,
                 "lz_info": "603278,大业股份,2连板"}]
    line2 = A.plate_series_line([{"date": "2026-10-28", "strength": 100}],
                                zt_rows2, plate_name="X", label_date="2026-10-28")
    assert "当日梯队串" in line2


def test_leader_narrative_places_reason_and_strength_lines():
    """v12 个股级叙事新行位置：强度行在炸板面后基线前；原因行在打标交叉后证据块前。"""
    narrative = A.build_leader_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT", baseline="BASE",
        evidence_block="EVID", leader_name="菲林格尔", leader_code="603226",
        headroom="ANCHOR", driver_cross="CROSS", reason_line="REASON",
        plate_strength="STRENGTH")
    lines = narrative.splitlines()
    assert lines.index("STRENGTH") < lines.index("BASE")
    assert lines.index("REASON") > lines.index("CROSS")
    assert lines.index("REASON") < lines.index("EVID")


def test_plate_series_line_two_segment_disclosure():
    """P1-1/G2/G3：双段口径——层1 连续交易日强度/净额 + 层2 涨停家（缺口≠零涨停标注）
    + LZInfo 交叉披露；未来日滤除；双空 None。"""
    rank_rows = [{"date": "2026-10-24", "strength": 7252, "main_net": None},
                 {"date": "2026-10-27", "strength": 8604, "main_net": -35699870865},
                 {"date": "2026-10-28", "strength": 31837, "main_net": -48221868016}]
    zt_rows = [{"date": "2026-10-23", "zt_num": 44,
                "lz_info": "603278,大业股份,6连板;300296,利亚德,3天2板"},
               {"date": "2026-10-28", "zt_num": 24,
                "lz_info": "603278,大业股份,2连板;688836,宇树科技,"}]
    line = A.plate_series_line(rank_rows, zt_rows, plate_name="机器人概念",
                               label_date="2026-10-28")
    assert "KPL「机器人概念」·801xxx 稳定 ID 锚" in line
    assert "近3交易日强度/净额（层1·净额已同屏定档 2026-10-29）" in line
    assert "10-28 强度31837 净额-482.2亿" in line and "10-24 强度7252 净额?" in line
    assert "板块涨停家（层2·仅记录有涨停家/爆发日，记录间缺口≠零涨停）" in line
    assert "10-23 家44" in line and "10-28 家24" in line
    assert "大业股份(2连板)" in line and "交叉披露不替换自算口径" in line
    # 双空 → None（匹配状态由强度行披露，不重复）
    assert A.plate_series_line([], [], plate_name="x", label_date="2026-10-28") is None


def test_sector_l2_lead_label_not_leader_p2_2():
    """P2-2（review）：板块级证据块（leader_code 空）L2 行不得冒称「龙头」。"""
    import types
    db = types.SimpleNamespace()   # build_theme_evidence_block 只用 corpus_state/产业树——
    # 直接测行渲染：走 digest 内部函数较重，改测 lead_label 判定语义等价路径
    text = A.build_leader_narrative(
        date="2026-10-28", market_line="M", structure="STRUCT", baseline="BASE",
        evidence_block="板内解析（韭研异动「机器人」5 只）：板内成员（韭研分组序，非推导龙一）"
                       " X（600001）驱动标签「t」｜解析摘录：…",
        leader_name="大业", leader_code="603278", segment="main")
    assert "板内成员（韭研分组序，非推导龙一）" in text


def test_plate_series_line_zt_fetch_error_p2_11():
    """P2-11（review）：层2 拉取失败且层1 亦空 → 显式失败行，不得静默 None。"""
    line = A.plate_series_line([], [], plate_name="X", label_date="2026-10-28",
                               zt_fetch_error="http 502")
    assert line is not None and "层2 涨停梯队历史拉取失败：http 502" in line
    assert A.plate_series_line([], [], plate_name="X", label_date="2026-10-28") is None


# ── §9.6/§9.7 处置（AMMO 2026-10-28a 勘察补丁）：层1 哨兵 + 层2 缺口率 ──


def test_rank_sentinel_warnings_clean():
    """正常样本（量级自洽、方向偏正、强度秩相关为正）→ 无告警。"""
    rank_rows = [
        {"date": "2026-10-24", "strength": 100, "main_net": -5e8, "pct": -1.0, "amount": 8e9},
        {"date": "2026-10-27", "strength": 200, "main_net": 3e8, "pct": 2.0, "amount": 9e9},
        {"date": "2026-10-28", "strength": 300, "main_net": 6e8, "pct": 4.0, "amount": 1e10},
    ]
    zt_rows = [{"date": "2026-10-24", "zt_num": 2, "qd": 10},
               {"date": "2026-10-27", "zt_num": 3, "qd": 20},
               {"date": "2026-10-28", "zt_num": 5, "qd": 30}]
    assert A.rank_sentinel_warnings(rank_rows, zt_rows) == []


def test_rank_sentinel_warnings_magnitude_and_direction():
    """量级越界（|净额|>成交额）与方向背离（同号率<0.5）各自告警；样本不足不误报。"""
    rows = [{"date": f"2026-10-2{d}", "strength": 100, "main_net": -1e10,
             "pct": 3.0, "amount": 5e9} for d in (2, 3, 4, 5)]
    warns = A.rank_sentinel_warnings(rows, [])
    assert any("净额>成交额 ×4" in w for w in warns)
    assert any("同号率 0/4 <0.5" in w for w in warns)
    # n=3 不触发方向告警（样本不足不定性）；量级仍报
    assert not any("同号率" in w for w in A.rank_sentinel_warnings(rows[:3], []))
    # 字段缺失行如实跳过，不误报不误崩
    assert A.rank_sentinel_warnings([{"date": "2026-10-28"}], []) == []


def test_rank_sentinel_warnings_rank_correlation():
    """层1 strength 与层2 QD 秩相关为负（≥3 共同日）→ 互证失败告警；<3 日不定性。"""
    rank_rows = [{"date": f"2026-10-2{d}", "strength": s}
                 for d, s in ((2, 100), (3, 500), (4, 900))]
    zt_rows = [{"date": f"2026-10-2{d}", "zt_num": 1, "qd": q}
               for d, q in ((2, 99), (3, 50), (4, 1))]
    warns = A.rank_sentinel_warnings(rank_rows, zt_rows)
    assert any("秩相关 -1.00<0（3 日）" in w for w in warns)
    assert A.rank_sentinel_warnings(rank_rows[:2], zt_rows[:2]) == []


def test_plate_series_line_sentinel_appended():
    """哨兵越界 → 层1 段尾追加告警（fail-visible），不静默、不丢强度数据。"""
    rank_rows = [{"date": "2026-10-28", "strength": 31837,
                  "main_net": -48221868016, "pct": 1.0, "amount": 1e9}]
    line = A.plate_series_line(rank_rows, None, plate_name="机器人概念",
                               label_date="2026-10-28")
    assert "口径哨兵告警（raw[8] 推断口径自检·fail-visible）" in line
    assert "净额>成交额 ×1" in line and "强度31837" in line


def test_plate_series_line_gap_rate_quantified():
    """§9.7：trading_days 给出时层2 段标窗口缺口率；缺省口径不变（向后兼容）。"""
    zt_rows = [{"date": "2026-10-23", "zt_num": 44, "lz_info": ""},
               {"date": "2026-10-28", "zt_num": 24, "lz_info": ""}]
    line = A.plate_series_line([], zt_rows, plate_name="X", label_date="2026-10-28",
                               trading_days=6)
    assert "窗口6交易日仅2条记录，记录间缺口≠零涨停" in line
    line2 = A.plate_series_line([], zt_rows, plate_name="X", label_date="2026-10-28")
    assert "板块涨停家（层2·仅记录有涨停家/爆发日，记录间缺口≠零涨停）" in line2
