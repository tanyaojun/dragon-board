# -*- coding: utf-8 -*-
"""题材层「板块龙头隔日连板」弹药纯函数层（2026-10-20 用户裁决「从 L3 开始做」后续步）。

分层边界（AGENTS §2.2：算法→analysis、服务/取数→operations）：
- 本文件**只放纯函数**：分桶/龙头排序/题集常量/叙事拼装/基准率汇总；无 DB、无网络、无模型。
- 取数与 jev 调用编排在 `backend/operations/theme_leader_label.py`；
- 基线脚本 `scripts/theme_leader_sustain_baseline.py` 也 import 本文件的分桶与排序，
  **分桶口径只有一份**（改这里=改基线=改投喂，不允许第二套）。

为什么先要「结构基准率」：实测 2026-08-01~10-19（50 交易日 / 341 个板块龙头样本）纯结构特征
已把次日连板率从总体 34.3% 拉到 83.3%（4板+|≥8家|早封）。题集里必须把同桶历史基准率摆给模型，
否则无法判断「模型是否只是复述结构特征」——验收门槛也因此定为「同桶 ≥15pp 提升」（§预登记）。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from backend.analysis.hotlist.jev_driver_ammo import _questions_hash

# ── 代际戳 ──
# 题集/口径任何一字变更必须换代（跨代不可比）。v1 = 2026-10-20 定版（龙头隔日连板两题）；
# v2 = 2026-10-20 晚确定性证据门；v3 = 2026-10-22 归因修复（早报段落级匹配 + L2 板内解析
# 纳入证据 + 门条件收窄为「L3 与 L2 均无可用证据」+ 非题材粗分桶不纳入判定范围）；
# v6 = 2026-10-23 四题判据增档；**v7 = 2026-10-24 置信度归因后空间题加历史锚规则**
# （14 只 v6 样本实测空间题 conf 均值 0.435 全场最差且无锚——判据加「锚必须先对」
# 硬规则，criteria 各档门不动；同批语料四补见 AMMO 2026-10-24b）；
# **v8 = 2026-10-24 空间题「越锚」铸词内联定义**（6b008b85 review P3：模型直读可能
# 不解裸铸词，改「要选高于锚的档位（越锚）时」——v7 仅 1 条样本（榕基 10-23 档，
# 页面重跑产生，保留作历史参照），此刻换代弃置成本最小且验收窗保持单代际，
# 推翻 review「并入下一自然换代点」原注；详见预登记 §17）。
# **v9 = 2026-10-26 零区分度处置**（A 检验 0/7 判对但零信息量；用户批准 §21.3 三项，
# AMMO 2026-10-26a 率值锚行配套）：①硬规则②单向改双向——偏离锚（上调或下调）都
# 须引用锚行具体数字+锚未覆盖新证据；②新增默认起判档规则③（按连板高度：1-3 板→peak、
# 4+ 板→space_1，依据=分层杀伤证据非桶众数，随 v9 冻结）；③space_1/peak criteria 绑
# 锚行「再走≥1板率」读数（三成上下/不足三成），非写死绝对阈值。
# **v10 = 2026-10-27 空间龙一规则配套**（用户裁决：龙一=10日涨幅最高，非真连板——
# 10-26 正裕 3 板卡位次日跌停 vs 大业断板反包 +8% 实证）：①续板题加规则⑤——待判龙头
# 当日未封板（断板反包候选）时判「重新上板概率」，封板类判据不适用、改按断板承接/
# 梯队/题材证据，锚缺失如实对待；②推导侧配套见 theme_leader_baseline（候选池扩近 3 日
# 封板池）与结构行未封板显式标注（AMMO 2026-10-27a）。
# **v11 = 2026-10-27 判据遵从收紧**（10-26 双案例：上海九百按判据应判 weak_extend 却判
# ending（三信号只中新闻断流一条）、大业无新鲜催化判 strong_extend 0.89 次日未续；
# 已结算 8 行对账=低档 5/5 全对、中档 1/3 无区分度，归因=锚定不对称+延续性题零引用义务，
# 预登记 §22，2026-10-27 用户批准）：①续板题规则①对称化——最细同桶基线为概率中枢，
# 偏离一档以上（上调或下调）都须点名基线行数字+锚外新证据，同桶样本不足未出率时以
# 「按连板高度」桶为中枢；②延续性题加引用义务——ending 须点名 ≥2 个判据信号对应
# 事实、strong_extend 须点名排队事件或近 2 日新增标题（打标交叉行可作引用源），
# 未封板龙一场景无锚须保守并降低置信。
QUESTION_SET_VERSION_THEME_LEADER = "v11"
# 原料代际：板块结构（触板−炸板二分、真连板）+ 题材语料（韭研产业树 + 开盘啦题材事件/
# 新闻（Kword 标签）/日历 + 题材热度序列 + 板内解析）。
# 2026-10-24a（语料精简+匹配收紧，2026-10-24 用户批准；题集 v6 冻结不动）：
# ① 删叙事重复头行 corpus_line（采集日/节点数/条数与证据块头完全重复）；
# ② 题材新闻与前瞻日历双空时合并为一行无匹配行；③ 事件正文剥确定性电头；
# ④ 共享子串锚加泛词黑名单（「应用」级泛词不再充当锚）。ALIASES 不加：
# kword 词表核验（29 个 distinct 标签，2026-10-24）无字面等价缺口——近义标签
# （算力概念/算力 等）已由包含匹配覆盖，新闻层瓶颈是供给稀疏（全题材 1-5 条/日），不是词表。
# 2026-10-24b（置信度提升批次，2026-10-24 用户批准四项；与题集 v7 同批换代）：
# S1 结构行加近 5 日板块封板家数序列（判据「扩张中/萎缩」从两点变形状）；
# S2 题材热度序列窗 5→10 日（「断流/见顶」需要更长窗）；S3 龙头驱动标签第二匹配通道
# （板块名命中错位宏观节点时补对口催化，只并列披露不替换）；Q1 新增空间锚行
# （历史连板周期自当日高度剩余板数分布，右删失剔除）。
# 2026-10-24c（盘面语料四补，2026-10-24 用户批准；对照韭研个股链 v3.2「判据点名
# 要、语料缺席」盘点；题面 v8 判据零改动）：①基线行补透出封板时间/跟风梯队/昨日承接
# 三组单维桶率（此前已算仅落审计）；②板内梯队形态行（首板/2板/3板+分布+次高连板差，
# climax 判据「首板潮/中军成形/高标分化」直接可读）；③前向交易日轴行（「未来 1-2 个
# 交易日」跨周末可数，日历源三级降级显式标注）；④板内炸板面行（今日/昨日触板未封，
# 板内口径同触板二分）+ 结构行昨日口径修正（prevBoardN 语义=昨日封板且今日仍封，
# 旧文案误写为「昨日封板 N 只」吞掉断板数，本版以 prevTotal−prevBoardN 显式出断板）。
# 2026-10-24d（review 处置，2026-10-24）：断板改同名成员口径——新增 prevStill（昨日同名板块
# 封板股中今日仍封数，prevTotal−prevStill 恒 ≥0）；旧实现用 prevBoardN（今日成员交集，含昨日
# 他板块迁入股），迁移场景减出负数甚至「昨日封 0 仍封 2」自相矛盾。同时修防御分支原始 None
# 泄漏（「今日仍封 None 只」→「今日仍封不可考」）。
# 2026-10-26a（空间锚每档基率化，2026-10-26 用户批准；预登记 §21.2）：Q1 空间锚行每档
# 只给「平均再走 X 板」（实测全 <1 板）与档位语义（space_1≈1 板/peak=顶部）粒度错配，
# 10-23 八龙头全 peak 塌缩归因之一——改为每档「再走≥1板率/≥2板率/中位再走/均值/样本量」，
# 率值口径与档位判定直接对齐；题面 v8 判据零改动，hash 不变。
# 2026-10-27a（空间龙一规则配套，2026-10-27 用户裁决；预登记 §21.6）：①结构行
# leader_sealed_today=False 分情形——「待判龙一 X（code）今日未封板（断板反包候选，
# 10 日涨幅 +Y% 居候选池首位）」替代「连板高度不可算」哑谜，跟风段如实改不可算；
# ②新增 rank_board_stocks_space（10日涨幅→连板高度→首封），历史窗口/基线仍用旧
# rank_board_stocks（口径分代见 §21.6）。题面 v10（续板题规则⑤）同批换代。
# 2026-10-27b（打标交叉原料行，2026-10-27 用户批准并入 v11 批次；预登记 §22）：
# 新增 driver_cross_line——join hotlist_jev_driver_labels（final 优先、midday 兜底、
# 槽位显式标注、双缺 fail-visible 出「无当日个股打标记录」），四轴（驱动类别 top-2/
# 催化深度/新鲜度/买盘逻辑）枚举译名+概率并列，行内自描述口径（个股级机器判定·供交叉
# 参考）。动机=题材语料空窗时给延续性/续板题一个结构化引用锚（10-26 上海九百/大业
# 双病案），并从个股侧补题材关键词匹配漏供给。只并待判龙头个股行，**不并 boardDragons**
# （真连板口径推导，与 v10 空间龙一双口径，单一事实源红线）。题面 v11 同批换代。
AMMO_VERSION_THEME_LEADER = "2026-10-27b"


# ── 分桶（唯一口径：基线脚本与投喂叙事共用） ──
def streak_bucket(s: Any) -> str:
    """真连板高度分桶（None=不可算）。"""
    if s is None:
        return "unknown"
    try:
        n = int(s)
    except (TypeError, ValueError):
        return "unknown"
    if n <= 1:
        return "1"
    if n == 2:
        return "2"
    if n == 3:
        return "3"
    return "4+"


def board_count_bucket(n: Any) -> str:
    """板块当日封板家数分桶。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "unknown"
    if v >= 8:
        return ">=8"
    if v >= 5:
        return "5-7"
    if v >= 3:
        return "3-4"
    return "1-2"


def seal_time_bucket(t: Any) -> str:
    """封板时间分桶（无时间=unknown）。"""
    s = str(t or "")[:5]
    if len(s) != 5 or s[2] != ":":
        return "unknown"
    if s <= "10:00":
        return "early<=10:00"
    if s <= "13:00":
        return "mid<=13:00"
    return "late>13:00"


def ladder_bucket(n: Any) -> str:
    """板块内跟风（真连板 >= 龙头-1）家数分桶（cap 3）。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "unknown"
    return str(min(v, 3))


def prev_peer_bucket(prev_peers: Any) -> str:
    """昨日同板块其它封板股家数分桶（None=昨日不可考）。"""
    if prev_peers is None:
        return "prev_unknown"
    v = int(prev_peers)
    if v == 0:
        return "prev0"
    if v <= 2:
        return "prev1-2"
    return "prev3+"


def _time_key(t: Any) -> str:
    s = str(t or "")[:5]
    return s if len(s) == 5 and s[2] == ":" else "99:99"


def rank_board_stocks(stocks: list[dict]) -> list[dict]:
    """板块内排序：真连板最高 → 封板时间最早（None 垫底）。龙一=首位。

    输入 `[{code, name?, time?, streak?}]`；纯排序不改输入。
    2026-10-27 起仅作历史窗口/回退口径（baseline 构建等）；**当日标注龙一改用
    `rank_board_stocks_space`**（用户裁决：真连板卡位股 ≠ 空间龙一，10-26 正裕 3 板
    卡位次日跌停 vs 大业断板反包 +8% 实证）。
    """
    return sorted(stocks, key=lambda s: (-(s.get("streak") or 0), _time_key(s.get("time"))))


def rank_board_stocks_space(candidates: list[dict]) -> list[dict]:
    """空间龙一排序（2026-10-27 用户裁决）：10 日涨幅最高 → 真连板高度 → 首封最早。

    候选池=当日封板池 ∪ 近 3 日封板池（同板块；覆盖断板反包——空间龙一断板日仍须在列，
    10-26 大业即靠昨日池入候选）。`gain10` 缺失垫底（None 当 -inf）；调用方保证候选池
    至少一只可算涨幅，否则整板块 fail-visible 跳过（用户裁决）。纯排序不改输入。
    """
    return sorted(candidates, key=lambda s: (
        -(s["gain10"] if s.get("gain10") is not None else float("-inf")),
        -(s.get("streak") or 0),
        _time_key(s.get("time")),
    ))


def combo_key(row: dict) -> str:
    """结构组合桶键（与基线脚本一致：streak|boardN|sealTime）。"""
    return (f"streak{streak_bucket(row.get('streak'))}"
            f"|n{board_count_bucket(row.get('boardN'))}"
            f"|{seal_time_bucket(row.get('time'))}")


def _rate(rows: list[dict]) -> tuple[int, int, float | None]:
    n = len(rows)
    cont = sum(1 for r in rows if r.get("continued"))
    return cont, n, (round(cont / n, 4) if n else None)


def group_rates(rows: list[dict], key_fn: Callable[[dict], str]) -> dict[str, dict]:
    """按 key_fn 分桶统计次日连板率（升序键）。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[str(key_fn(r))].append(r)
    return {k: {"cont": c, "n": n, "rate": p}
            for k, v in sorted(buckets.items())
            for c, n, p in [_rate(v)]}


def combo_rates(rows: list[dict], min_n: int = 5) -> dict[str, dict]:
    """结构组合桶率（样本 < min_n 的不出，避免给模型 1-2 样本的假高率）。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[combo_key(r)].append(r)
    return {k: {"cont": c, "n": n, "rate": p}
            for k, v in sorted(buckets.items()) if len(v) >= min_n
            for c, n, p in [_rate(v)]}


def summarize_rows(rows: list[dict], min_combo_n: int = 5) -> dict:
    """基线汇总（口径与 scripts/theme_leader_sustain_baseline.py 逐项一致）。"""
    cont, n, rate = _rate(rows)
    return {
        "leaders": n, "continued": cont, "rate": rate,
        "byStreak": group_rates(rows, lambda r: streak_bucket(r.get("streak"))),
        "byBoardCount": group_rates(rows, lambda r: board_count_bucket(r.get("boardN"))),
        "bySealTime": group_rates(rows, lambda r: seal_time_bucket(r.get("time"))),
        "byFollowers": group_rates(rows, lambda r: ladder_bucket(r.get("ladderFollowers"))),
        "byPrevPeers": group_rates(rows, lambda r: prev_peer_bucket(r.get("prevPeers"))),
        "combo": combo_rates(rows, min_combo_n),
    }


# ── 题集（v1 定版，判据冻结：改动必须换代 + 预登记） ──
QUESTIONS_THEME_LEADER = {
    "theme_speculation_depth": {
        "type": "choice",
        "instructions": "仅依据所给证据（题材热度序列、产业树催化正文、题材事件与热度、"
                        "题材新闻 Kword 分布、前瞻日历、板块梯队结构），判断该题材当前的"
                        "**炒作深度/所处阶段**。只判题材层面阶段，不预测个股。判据要点："
                        "事件与新闻的新增密度（热度序列是否断流/见顶）、板块梯队形态"
                        "（首板潮/中军成形/高标分化）、龙头高度与板块家数变化。"
                        "证据不足的判定边界（v6 收紧）：仅当语料未采集，或产业树未映射 + "
                        "题材事件/新闻近 5 日均无痕迹 + 板内解析亦不可用**三层同时成立**"
                        "才判 insufficient。特别地：事件/新闻零痕迹而板块当日仍有涨停，"
                        "= 「无新增催化的纯资金/情绪驱动」信号，**不是证据缺失**——"
                        "高标孤军高度领先判 climax，板块家数同步萎缩判 ebbing，"
                        "不得借 insufficient 逃避归类。",
        "criteria": {
            "igniting": "启动期：题材由近 1-2 日新事件/新催化点燃，板块以首板为主、"
                        "家数扩张中，尚无连板梯队",
            "fermenting": "发酵期：事件/新闻持续新增（热度序列未见顶回落），2-3 板中军成形，"
                          "板块家数维持或增长",
            "climax": "高潮期：龙头高度显著领先（≥4 板）而板块开始分化——家数回落、"
                      "跟风断板增多、新闻/事件密度见顶回落",
            "ebbing": "退潮期：事件与新闻断流（热度序列连续走低）、板块家数萎缩、"
                      "龙头断板或出现大面",
            "insufficient": "证据不足：仅当语料未采集，或产业树/题材事件·新闻/板内解析"
                            "三层同时无该板块痕迹。事件新闻断流本身是 climax/ebbing 的"
                            "判据信号，不是证据不足",
        },
    },
    "theme_continuation": {
        "type": "choice",
        "instructions": "仅依据所给证据，判断该题材炒作的**延续性**：接下来 1-2 个交易日，"
                        "题材层面（板块整体，不是单指龙头）还能否继续炒作？判据要点："
                        "未来 1-3 日既定事件是否排队（前瞻日历）、题材事件/新闻是否仍在新增、"
                        "催化是否被其他题材分流稀释、板块梯队是否完整。"
                        "证据不足的判定边界（v6 收窄）：与程序门同口径——产业树未映射 + "
                        "事件/新闻无痕 + 板内解析不可用三层同时成立才判 insufficient。"
                        "无新增催化但板块仍活跃 = 存量惯性 → weak_extend；"
                        "分化/退潮信号明确 → ending——零痕迹不是 insufficient 的理由。"
                        "引用义务（v11）：判 ending 须在理由中点名至少 2 个判据信号"
                        "（新闻断流/家数萎缩/龙头分歧）在叙事中的对应事实——只有单一信号"
                        "时按存量惯性归 weak_extend，不得凭单一信号判结束；判 strong_extend "
                        "须点名排队中的既定事件或近 2 日新增的题材事件/新闻标题"
                        "（「个股打标交叉」行的新鲜度/买盘逻辑判定可作引用源），"
                        "仅凭板块家数多/龙头身位强不足以为强延续；待判龙头今日未封板"
                        "（断板反包候选）时缺少同构历史锚与当日封板质量证据，本题应保守"
                        "判断并降低置信，未封板身位本身不构成强延续证据。",
        "criteria": {
            "strong_extend": "强延续：有未落地的既定事件排队或题材事件/新闻持续新增，"
                             "梯队完整，预计板块还能炒 ≥2 个交易日",
            "weak_extend": "弱延续：仅存量情绪惯性，无明显新增催化，预计板块炒作 ≤1 个交易日",
            "ending": "临近结束：高潮分化/退潮信号明确（新闻断流+家数萎缩+龙头分歧），"
                      "题材层面随时收束",
            "insufficient": "证据不足：仅当语料未采集或三层证据（产业树/事件·新闻/板内解析）"
                            "同时无痕迹；无催化零痕迹时按存量惯性与分化信号归类",
        },
    },
    "leader_nextday_continue": {
        "type": "choice",
        "instructions": "仅依据所给证据（板块结构、封板质量、题材证据与前瞻事件、同桶历史基准率），"
                        "判断该板块龙头在**次一交易日**继续封板（涨停）的概率落在哪一档？"
                        "只判概率档位，不预测价格、不给出买卖建议。四条硬规则："
                        "①同桶历史基准率是必须先对齐的概率中枢——取叙事「结构基线」行中最细"
                        "同桶（方括号条件最全且已出率，即样本≥8 的那行）；偏离中枢一档以上"
                        "（上调或下调）都必须在理由中点名所依据的基线行具体数字，并给出锚未"
                        "覆盖的新证据（当日新催化、承接突变、封板质量异常等），不得凭感觉移动"
                        "档位；若最细同桶样本不足未出率，以「按连板高度」桶为中枢；"
                        "②题材证据（产业树催化、题材事件/题材新闻、前瞻日历、板内个股解析、"
                        "个股打标交叉行）"
                        "有明确日期与新鲜度时，其权重高于结构特征；"
                        "③关键证据缺失（语料未采集、板块在产业树/题材事件均无可用证据、"
                        "板块结构不可考）必须判 insufficient，不得用结构特征硬填空档；"
                        "④此规则由程序强制：当叙事「题材证据」标注证据缺失（产业树未映射且"
                        "题材事件与板内解析亦无可用证据）时，无论你给出何档，落库一律覆盖为 "
                        "insufficient（原答另存备查）——所以此时请直接选 insufficient，"
                        "不要用结构特征凑档位；⑤若叙事标注待判龙头**今日未封板**（断板反包"
                        "候选），本题=判断其次日**重新上板**的概率：封板质量/封板时间类结构"
                        "判据不适用，改按断板后承接（板内炸板面、昨日仍封数）、板块梯队与"
                        "题材证据判断；未封板龙一通常没有同构历史锚，此时以证据为主，锚缺失"
                        "如实对待、不得编造基准。",
        "criteria": {
            "high_ge65": "高概率 ≥65%：结构位置强（连板高度领先 + 封板早 + 板块家数多）"
                         "且题材有当日/近两日新催化（含题材事件/题材新闻新增），"
                         "或未来 1-2 日有既定事件",
            "mid_45_65": "中等 45%-65%：结构与题材一强一弱，或与同桶历史基准率同档",
            "low_25_45": "偏低 25%-45%：结构位置一般（封板偏晚/板块家数少/跟风薄），"
                         "或题材为老催化且近期无新增",
            "verylow_lt25": "很低 <25%：结构示警（板块家数少 + 封板晚 + 无梯队）"
                            "且题材无催化或已明显退潮",
            "insufficient": "证据不足：关键证据缺失（语料未采集、产业树与题材事件与板内解析均无"
                            "该板块证据、板块结构不可考），不强行归类",
        },
    },
    "leader_headroom": {
        "type": "choice",
        "instructions": "综合前三题的判断（题材炒作深度、题材延续性、次日续板概率）与该龙头"
                        "在题材内的身位（是否龙一/总龙头、高度领先度、封板质量），判断该龙头"
                        "**还有多少上涨空间**——在当前连板高度之上还能再走几个板。"
                        "注意：这是空间判断，不是次日概率判断——强延续题材的龙一通常仍有空间，"
                        "退潮题材的高标即使次日勉强封板也缺乏空间。硬规则：①关键证据缺失必须判 "
                        "insufficient；②叙事若提供「空间锚」行（历史同结构龙头自当日高度的"
                        "再走≥1板率/≥2板率/中位分布），它是必须先对的基准——若你的理由仅为"
                        "「身位强/题材强」这类与锚同源的结构特征，应选与锚一致的档位；无论上调"
                        "还是下调，偏离锚的档位都必须在理由中引用锚行的具体数字，并给出锚未"
                        "覆盖的新证据（当日新催化、身位显著领先、封板质量显著占优等）；"
                        "③默认起判档（按龙头当日连板高度）：1-3 板 → peak 起判、4 板及以上 → "
                        "space_1 起判——依据=历史同高度再走≥1板率（1-3 板桶仅一到三成、4+ 桶"
                        "约三成七）与主线核心退潮日照续的分层杀伤证据，非桶众数；连板高度不可算"
                        "时无默认档，按 ② 对锚判断；默认档只是起点，偏离仍须按 ② 引用锚行"
                        "数字并给新证据。",
        "criteria": {
            "space_2plus": "仍有 ≥2 板空间：题材强延续（发酵期）且该龙头是身位无可替代的"
                           "龙一/总龙头，梯队与催化双支撑",
            "space_1": "还有约 1 板空间：题材尚可延续或龙头身位尚可，但催化新鲜度、"
                       "梯队完整性有一项已走弱（锚行读数参照：历史同高度再走≥1板率"
                       "三成上下）",
            "peak": "空间已尽：题材退潮/临近结束，或龙头身位被替代/催化断流，"
                    "当前高度大概率就是顶部（锚行读数参照：同高度再走≥1板率不足三成）",
            "insufficient": "证据不足：仅当语料未采集或三层证据（产业树/事件·新闻/板内解析）"
                            "同时无痕迹",
        },
    },
}
QUESTION_SET_HASH_THEME_LEADER = _questions_hash(QUESTIONS_THEME_LEADER)

# 承接题集的最小单位（与驱动链同规：题目原文不改写）——本层暂不做承接（首版只判独立基线）。
THEME_LEADER_KEYS = tuple(QUESTIONS_THEME_LEADER)

# 档位中值（**仅供离线评估**：把模型返回的档位概率分布折算成单点概率算 Brier/校准；
# 不参与叙事、不下发给模型，避免把"我们自己的解读"混进题面）。
# `insufficient` 不给中值：评估时单独统计其质量并在其余四档上归一化，不拿"不足"当低概率。
CONTINUE_BUCKET_MIDPOINTS = {
    "high_ge65": 0.75,
    "mid_45_65": 0.55,
    "low_25_45": 0.35,
    "verylow_lt25": 0.125,
}


# 确定性「证据缺失」门（v2 引入，v3 收窄触发条件；纯函数，无 IO）。
# 触发只用**结构化**的缺失标志（`theme_event_digest` 返回的 `evidenceMissing`），不从叙事文字反推。
# v3 口径：`evidenceMissing` = L3（产业树/日历）与 L2（板内解析/早报段落）**均无**可用证据。
GATE_REASON_LABELS = {
    "corpus_not_collected": "题材语料未采集",
    # v2 历史档（10-08~10-22 落库）沿用旧名，保留标签供前端/审计回读：
    "board_unmapped": "板块未映射（韭研产业树无同名/包含节点，不代表无催化）",
    "industry_tree_unmapped": "产业树未映射且题材事件/板内解析均无可用证据",
    "no_content_no_event": "已映射但正文为空且无可用事件",
}


def apply_evidence_gate(answers: Any, evidence: Any) -> tuple[Any, dict]:
    """证据缺失 → **全部判定题**强制 insufficient（原答原样存 gate 元数据）。

    v1 单日 pilot 实测缺口：未映射板块的催化题判了 insufficient，但同一份证据下
    概率题仍给 0.34/0.34/0.26/0.18——规则③只写在题面，靠模型自觉。v2 改为代码强制
    （仅概率题）；v5 起题集扩为四题（深度/延续性/概率/空间），**无证据时四题全部门**——
    无题材证据却判「发酵期/强延续/空间≥2板」与「无证据却给 0.34」是同一类失效。
    """
    ev = evidence if isinstance(evidence, dict) else {}
    gate: dict[str, Any] = {"applied": False, "reason": None}
    if not isinstance(answers, dict) or not ev.get("evidenceMissing"):
        return answers, gate
    reason = str(ev.get("evidenceMissingReason") or "unknown")
    prev_prob = answers.get("leader_nextday_continue") if isinstance(
        answers.get("leader_nextday_continue"), dict) else {}
    gate.update({"applied": True, "reason": reason,
                 "label": GATE_REASON_LABELS.get(reason, reason),
                 "modelChoice": prev_prob.get("choice"),
                 "modelProbabilities": prev_prob.get("probabilities"),
                 "forcedKeys": []})
    out = dict(answers)
    for key in QUESTIONS_THEME_LEADER:
        prev = out.get(key) if isinstance(out.get(key), dict) else {}
        if prev.get("choice") == "insufficient":
            continue                      # 模型已自判不足，无须覆盖
        forced = {"type": "choice", "choice": "insufficient", "confidence": 1.0,
                  "gateReason": reason}
        if key == "leader_nextday_continue":
            forced["probabilities"] = {"insufficient": 1.0}
        out[key] = forced
        gate["forcedKeys"].append(key)
    return out, gate


def continue_point_estimate(probabilities: Any) -> tuple[float | None, float]:
    """档位概率分布 → (单点概率, insufficient 质量)。

    四档按其给出的概率加权求期望（不是取 argmax 档中值），其余四档质量归一化；
    归一化后质量为 0（全判 insufficient）时返回 (None, mass) —— 不编造概率。
    """
    probs = probabilities if isinstance(probabilities, dict) else {}
    mass = float(probs.get("insufficient") or 0.0)
    parts = {k: float(probs.get(k) or 0.0) for k in CONTINUE_BUCKET_MIDPOINTS}
    total = sum(parts.values())
    if total <= 0:
        return None, mass
    return sum(v * CONTINUE_BUCKET_MIDPOINTS[k] for k, v in parts.items()) / total, mass


# ── 叙事拼装（纯字符串，IO 全在 operations 层） ──
def baseline_line(rows: list[dict], row: dict, min_combo_n: int = 5) -> str:
    """该龙头所在结构桶的历史基准率行（组合桶样本不足时逐级回退，全部标注样本量）。

    2026-10-24c：补透出 `bySealTime`/`byFollowers`/`byPrevPeers` 三组单维桶率（此前
    `summarize_rows` 已算、仅落审计不喂模型）。verylow 判据「板块家数少+封板晚+无梯队」
    三维度现在语料都有对应率；各维独立出率（组合桶样本不足时不再整体丢失封板时间维度）。
    回退顺序：组合桶 → 连板高度 → 板块家数 → 封板时间 → 跟风梯队 → 昨日承接 → 总体；
    任一档样本 < min_combo_n 都明示样本量，让模型知道这条基准率的可信度（不隐藏小样本）。
    """
    combo = combo_rates(rows, min_combo_n).get(combo_key(row))
    parts: list[str] = []
    if combo:
        parts.append(f"同桶[{combo_key(row)}] 历史次日连板率 {combo['rate']:.1%}（{combo['n']} 样本）")
    else:
        parts.append(f"同桶[{combo_key(row)}] 样本不足（<{min_combo_n}），不出率")
    sk = streak_bucket(row.get("streak"))
    sb = group_rates(rows, lambda r: streak_bucket(r.get("streak"))).get(sk)
    if sb:
        parts.append(f"按连板高度[{sk}] {sb['rate']:.1%}（{sb['n']} 样本）")
    ck = board_count_bucket(row.get("boardN"))
    cb = group_rates(rows, lambda r: board_count_bucket(r.get("boardN"))).get(ck)
    if cb:
        parts.append(f"按板块家数[{ck}] {cb['rate']:.1%}（{cb['n']} 样本）")
    tk = seal_time_bucket(row.get("time"))
    tb = group_rates(rows, lambda r: seal_time_bucket(r.get("time"))).get(tk)
    if tb and tk != "unknown":
        parts.append(f"按封板时间[{tk}] {tb['rate']:.1%}（{tb['n']} 样本）")
    fk = ladder_bucket(row.get("ladderFollowers"))
    fb = group_rates(rows, lambda r: ladder_bucket(r.get("ladderFollowers"))).get(fk)
    if fb and fk != "unknown":
        parts.append(f"按跟风梯队[{fk}] {fb['rate']:.1%}（{fb['n']} 样本）")
    pk = prev_peer_bucket(row.get("prevPeers"))
    pb = group_rates(rows, lambda r: prev_peer_bucket(r.get("prevPeers"))).get(pk)
    if pb and pk != "prev_unknown":
        parts.append(f"按昨日承接[{pk}] {pb['rate']:.1%}（{pb['n']} 样本）")
    cont, n, rate = _rate(rows)
    if n:
        parts.append(f"总体 {rate:.1%}（{n} 样本）")
    return "结构基线（口径=触板−THS炸板二分 + 真连板；历史窗口内板块龙头样本）：" + "；".join(parts)


# ── 空间题历史锚（Q1，2026-10-24b 置信度归因后加）────────────────────────────
# 归因（v6 两日 14 只实测）：空间题 conf 均值 0.435 全场最差且**无任何历史锚**——续板题有
# 同桶基准率，空间题全凭模型相对判断。「连板周期」= 同一 code 在 date 相邻交易日且
# streak 严格 +1 的连续段；自当日高度的剩余板数 = 段尾 streak − 当日 streak。
# 右删失：段尾样本次日仍封板（continued=True）但样本流断（让位龙头/THS 缺失），周期未
# 确认终结 → 整段剔除并披露，不把未知终点当 0 剩余。streak None（真连板不可算）不进锚。


def _leader_cycles(rows: list[dict]) -> tuple[list[tuple[dict, int]], int]:
    """历史龙头-日样本 → [(样本行, 自当日高度剩余板数), ...] + 右删失样本数。"""
    dates_axis = sorted({str(r.get("date")) for r in rows if r.get("date")})
    nxt_of = {d: dates_axis[i + 1] for i, d in enumerate(dates_axis[:-1])}
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        code = str(r.get("code") or "")
        if code and isinstance(r.get("streak"), int):
            by_code[code].append(r)
    kept: list[tuple[dict, int]] = []
    censored = 0

    def _close(seg: list[dict]) -> None:
        nonlocal censored
        if not seg:
            return
        if seg[-1].get("continued") is not False:   # 次日仍封/结局不可考 = 周期未确认终结
            censored += len(seg)
            return
        end_streak = seg[-1]["streak"]
        for s in seg:
            kept.append((s, end_streak - int(s["streak"])))

    for samples in by_code.values():
        samples.sort(key=lambda r: str(r.get("date")))
        seg: list[dict] = []
        for s in samples:
            if (seg and str(s.get("date")) == nxt_of.get(str(seg[-1].get("date")))
                    and s.get("streak") == seg[-1]["streak"] + 1):
                seg.append(s)
            else:
                _close(seg)
                seg = [s]
        _close(seg)
    return kept, censored


def headroom_anchor_line(rows: list[dict], row: dict, min_combo_n: int = 8) -> str | None:
    """空间题历史锚行（与 baseline_line 同构的桶回退；样本量与删失全披露）。

    历史 rows 为空 / 无可用周期 → None（叙事不出行：没有锚时题面锚规则不触发，
    模型自行判断——fail-visible，不编造基准）。
    2026-10-26a 每档基率化：此前每档只给「平均再走 X 板」（实测全 <1 板）+ ≥2 板率，
    与档位语义（space_1≈1 板/peak=顶部）粒度错配——10-23 八龙头全 peak 塌缩归因之一。
    改为每档给「再走≥1板率/≥2板率/中位再走/均值/样本量」：率值口径与档位判定直接对齐
    （≥1板率低→peak 侧，≥1板率高→space_侧），均值降为参考量；题面判据零改动。
    """
    from statistics import median

    kept, censored = _leader_cycles(rows)
    if not kept:
        return None

    def _stat(pairs: list[tuple[dict, int]]) -> str:
        vals = [float(v) for _, v in pairs]
        n = len(vals)
        return (f"再走≥1板率 {sum(1 for v in vals if v >= 1) / n:.1%} · ≥2板率 "
                f"{sum(1 for v in vals if v >= 2) / n:.1%} · 中位再走 {median(vals):.1f} 板"
                f"（均值 {sum(vals) / n:.1f}，{n} 样本）")

    parts: list[str] = []
    ck = combo_key(row)
    combo_pairs = [p for p in kept if combo_key(p[0]) == ck]
    if len(combo_pairs) >= min_combo_n:
        parts.append(f"同桶[{ck}] {_stat(combo_pairs)}")
    else:
        parts.append(f"同桶[{ck}] 样本不足（<{min_combo_n}），不出锚")
    sk = streak_bucket(row.get("streak"))
    streak_pairs = [p for p in kept if streak_bucket(p[0].get("streak")) == sk]
    if len(streak_pairs) >= min_combo_n:
        parts.append(f"按连板高度[{sk}] {_stat(streak_pairs)}")
    cen = (f"；剔右删失周期样本 {censored} 个（次日仍封但样本流断，周期未确认终结）"
           if censored else "")
    return ("空间锚（口径=历史窗内板块龙头连板周期，右删失已剔；"
            "再走≥1板率=历史同结构龙头自当日高度至少再封一板的占比）："
            + "；".join(parts) + f"；总体 {_stat(kept)}{cen}")


def structure_line(*, board: str, board_n: int, leader: dict, followers_ge_ladder: int,
                   prev_board_n: int | None, prev_peers: int | None,
                   prev_total: int | None = None,
                   prev_still: int | None = None,
                   history: list[tuple[str, int]] | None = None,
                   leader_sealed_today: bool | None = None,
                   gain10: float | None = None) -> str:
    """该板块当日结构事实行（不含预测）。

    `history`（S1，2026-10-24b）= 近 5 日 (date, boardN) 序列：深度/延续题判据
    「家数扩张中/萎缩」此前只有今日/昨日两点，序列才看得出形状。缺口日如实不列。
    `prev_total`（2026-10-24c）= 昨日该板块封板总数：此前叙事把 `prev_board_n`（语义=
    昨日封板且今日仍封）误写成「昨日该板块封板 N 只」，断板数被吞——本版修正口径，
    断板 = prev_total − prev_board_n 显式给出；prev_total 不可考（板块改名/昨日池缺失）
    时如实写不可考，不拿仍封数冒充总数。
    `prev_still`（2026-10-24d）= 昨日**同名板块**封板股中今日仍封数，断板 = prev_total −
    prev_still 按它算（恒 ≥0）——2026-10-24 review 处置：prev_board_n 是今日成员交集，
    含昨日他板块迁入股，迁移场景减出负数甚至「昨日封 0 仍封 2」自相矛盾；prev_still
    缺席（手造/旧形状行）时退回 prev_board_n 口径，差值为负则不出断板数只说不可算。
    `leader_sealed_today=False`（2026-10-27 空间龙一规则，v10 题面配套）= 待判龙一当日
    未封板（断板反包候选）——显式标注替代「连板高度不可算/时间不可考」的哑谜，并给
    10 日涨幅身位（排序依据）；模型按 v10 题面⑤分情形判「重新上板概率」。
    """
    unsealed = leader_sealed_today is False
    if unsealed:
        leader_txt = f"待判龙一 {leader.get('name')}（{leader.get('code')}）今日未封板（断板反包候选"
        if gain10 is not None:
            leader_txt += f"，10 日涨幅 {gain10:+.1f}% 居候选池首位"
        leader_txt += "）"
    else:
        streak = leader.get("streak")
        streak_txt = f"{streak} 连板" if streak else "连板高度不可算"
        time_txt = str(leader.get("time") or "时间不可考")
        leader_txt = (f"龙头 {leader.get('name')}（{leader.get('code')}）"
                      f"{streak_txt}，首封 {time_txt}")
    still_txt = (f"今日仍封 {prev_still} 只" if isinstance(prev_still, int)
                 else (f"今日仍封 {prev_board_n} 只" if isinstance(prev_board_n, int)
                       else "今日仍封不可考"))
    if prev_peers is None:
        prev_txt = "昨日同板块不可考"
    elif isinstance(prev_still, int) and prev_total is not None:
        prev_txt = (f"昨日该板块封板 {prev_total} 只，{still_txt}"
                    f"（断板 {prev_total - prev_still}）")
    elif prev_total is None:
        prev_txt = f"昨日该板块封板总数不可考（{still_txt}）"
    else:
        duan = prev_total - prev_board_n if isinstance(prev_board_n, int) else None
        duan_txt = (f"断板 {duan}" if duan is not None and duan >= 0 else "断板不可算")
        prev_txt = f"昨日该板块封板 {prev_total} 只，{still_txt}（{duan_txt}）"
    hist_txt = ""
    if history:
        seq = " · ".join(f"{d[5:]} {n}" for d, n in history)
        hist_txt = f"；近 {len(history)} 日该板块封板家数（旧→新，缺口日不列）：{seq}"
    elif history is not None and not history:
        hist_txt = "；近数日家数序列不可考（历史日该板块名无收录或 THS 池缺失）"
    follow_txt = (f"板块内真连板≥{max(1, ((leader.get('streak') or 1)) - 1)} 的跟风 "
                  f"{followers_ge_ladder} 家"
                  if isinstance(followers_ge_ladder, int)
                  else "跟风梯队不可算（龙一未封板，梯队见板块梯队形态行）")
    return (f"板块「{board}」今日封板 {board_n} 家；{leader_txt}；{follow_txt}；"
            f"{prev_txt}{hist_txt}")


def board_ladder_line(row: dict) -> str | None:
    """板内梯队形态行（2026-10-24c）：首板潮/中军成形/高标分化直接可读。

    深度题 climax 判据点名「板块梯队形态（首板潮/中军成形/高标分化）」「龙头高度显著
    领先」，此前语料只有封板总数与跟风数两点。`ladderShape` 缺席（旧代行/极端缺失）→
    None 不出行；次高连板 None=板内无其它可算真连板（孤军），如实写不可考。
    """
    shape = row.get("ladderShape")
    if not isinstance(shape, dict):
        return None
    seg = (f"板块梯队形态：首板 {shape.get('first', 0)} 家 / 2板 {shape.get('two', 0)} 家 / "
           f"3板+ {shape.get('threePlus', 0)} 家")
    unk = shape.get("unknown", 0)
    if unk:
        seg += f"（另有 {unk} 只连板高度不可算）"
    leader_streak = row.get("streak")
    second = row.get("secondStreak")
    if isinstance(leader_streak, int) and isinstance(second, int):
        seg += f"；龙头 {leader_streak} 板，次高 {second} 板（领先 +{leader_streak - second}）"
    elif isinstance(leader_streak, int):
        seg += f"；龙头 {leader_streak} 板，次高 不可考（板内无其它可算真连板）"
    else:
        seg += "；龙头连板高度不可算"
    return seg


def board_zhaban_line(row: dict) -> str | None:
    """板内炸板面行（2026-10-24c）：分化/退潮的板内证据。

    climax 判据「跟风断板增多」、ebbing「龙头断板或出现大面」此前只有全市场炸板率，
    板内触板未封（韭研曾触板−THS炸板二分同口径，剔 ST/北交所）缺席。昨日数不可考
    （昨日池缺失/板块改名）时只出今日，如实不列对比。
    """
    z = row.get("zhabanN")
    if not isinstance(z, int):
        return None
    seg = f"板内炸板面：今日触板未封 {z} 家"
    pz = row.get("prevZhabanN")
    if isinstance(pz, int):
        seg += f"（昨日 {pz} 家）"
    return seg


# ── 打标交叉行（AMMO 2026-10-27b，用户批准；预登记 §22） ──
# 枚举短名（与 jev_driver_ammo 判据中文名对齐，压缩为一词便于行内并列）。
DRIVER_LABEL_CN = {
    "policy": "政策", "order_earnings": "订单业绩", "product_event": "产品事件",
    "ma_restructure": "重组并购", "industry_cycle": "行业周期",
    "capital_flow": "资金接力", "concept_stretch": "蹭概念",
    "insufficient_evidence": "信息不足",
}
DRIVER_DEPTH_CN = {
    "core_main_business": "核心主业", "new_business_scaling": "新业务放量",
    "new_business_early": "新业务早期", "equity_or_affiliate": "股权关联",
    "concept_assembly": "概念组装", "insufficient_evidence": "信息不足",
}
DRIVER_FRESHNESS_CN = {
    "fresh_catalyst": "新催化（≤2 交易日）", "continuing": "老催化续命",
    "none": "无明确催化", "unclear": "日期不可考",
}
DRIVER_BUYSIDE_CN = {
    "independent_catalyst": "自身独立催化", "sector_follow": "板块联动跟随",
    "high_board_relay": "高位卡位/情绪接力", "pure_sentiment": "纯情绪修复",
    "insufficient": "信息不足",
}
DRIVER_CROSS_NONE_LINE = (
    "个股打标交叉：无当日个股打标记录（该股不在打标名单或槽位未落，"
    "仅指此行缺席，不构成任何方向证据）"
)
# 承接披露映射（打标链 carriedQuestionKeys 题键 → 交叉行轴名）：
# 解析正文与前一日逐字相同时打标链不重问（carriedFrom=前一日），交叉行必须如实标注
# 「承接判定」——新鲜度等轴是昨日判断，不是当日重问（防模型把承接值当当日新鲜证据）。
DRIVER_CARRY_AXIS_CN = {
    "driver_type": "驱动类别", "catalyst_depth": "催化深度",
    "catalyst_freshness": "新鲜度", "buy_side_logic": "买盘逻辑",
}


def _top2(probabilities: Any, cn: dict[str, str]) -> str:
    """top-2 枚举短名+整数百分比并列；逃生桶（insufficient 系）不进排名，为空返回空串
    （调用方兜底用已选枚举值，全缺「不可考」，不编 0）。两档比值 ≥0.9 标「近并列」——
    近并列本身是信息（判定不稳），必须披露。"""
    if not isinstance(probabilities, dict):
        return ""
    items = [(cn.get(str(k), str(k)), float(v)) for k, v in probabilities.items()
             if isinstance(v, (int, float)) and v > 0 and k not in ("insufficient_evidence", "insufficient")]
    items.sort(key=lambda kv: -kv[1])
    items = items[:2]
    if not items:
        return ""
    tie = len(items) == 2 and items[0][1] > 0 and items[1][1] / items[0][1] >= 0.9
    seg = "/".join(f"{name}{v:.0%}" for name, v in items)
    return f"{seg}（近并列）" if tie else seg


def _enum_cn(value: Any, cn: dict[str, str]) -> str:
    if not value:
        return "不可考"
    return cn.get(str(value), str(value))


def driver_cross_line(label_doc: dict | None) -> str:
    """个股打标交叉行（AMMO 2026-10-27b）：join 打标链当日该股判定，零调用纯原料。

    行内自描述口径（模型每次都是第一次见「打标交叉」这个词）：另一条打标链对该公司
    当日涨停的机器判定，供交叉参考；四轴=驱动类别 top-2/催化深度/新鲜度/买盘逻辑，
    枚举译名+概率并列。槽位显式（final=收盘槽、midday=午盘槽）；打标链题集版本一并
    披露（v3.1/v4.0 校准代际不同）。label_doc=None → fail-visible 缺席行（不伪装成
    「无催化」等任何方向性结论）。
    """
    if not label_doc:
        return DRIVER_CROSS_NONE_LINE
    slot = str(label_doc.get("labelSlot") or "")
    slot_cn = {"final": "收盘槽", "midday": "午盘槽"}.get(slot, slot or "槽位不可考")
    qs = str(label_doc.get("questionSetVersion") or "版本不可考")
    head = (f"个股打标交叉（另一条打标链对该公司当日涨停的机器判定，供交叉参考；"
            f"打标链题集 {qs}·{slot_cn}）：")
    # 驱动类别概率真身=driverProbabilities（labelProbabilities 为 API 层旧别名，兜底旧档）
    label_seg = _top2(label_doc.get("driverProbabilities")
                      or label_doc.get("labelProbabilities"), DRIVER_LABEL_CN) \
        or _enum_cn(label_doc.get("label"), DRIVER_LABEL_CN)
    buyside_seg = _top2(label_doc.get("buySideProbabilities"), DRIVER_BUYSIDE_CN) \
        or _enum_cn(label_doc.get("buySideLogic"), DRIVER_BUYSIDE_CN)
    parts = [
        f"驱动类别={label_seg}",
        f"催化深度={_enum_cn(label_doc.get('catalystDepth'), DRIVER_DEPTH_CN)}",
        f"新鲜度={_enum_cn(label_doc.get('freshness'), DRIVER_FRESHNESS_CN)}",
        f"买盘逻辑={buyside_seg}",
    ]
    tail = ""
    carried_set = {DRIVER_CARRY_AXIS_CN[k] for k in
                   (label_doc.get("carriedQuestionKeys")
                    or label_doc.get("carriedAnswers") or {})
                   if k in DRIVER_CARRY_AXIS_CN}
    carried = [a for a in ("驱动类别", "催化深度", "新鲜度", "买盘逻辑") if a in carried_set]
    if carried:
        frm = label_doc.get("carriedFrom")
        tail = f" · {'/'.join(carried)}=承接 {frm or '上一交易日'} 判定（非当日重问）"
    return head + " · ".join(parts) + tail


def build_leader_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, leader_name: str,
                           leader_code: str, headroom: str | None = None,
                           forward_axis: str | None = None,
                           ladder_line: str | None = None,
                           zhaban_line: str | None = None,
                           driver_cross: str | None = None) -> str:
    """投喂给 jev 的完整叙事（顺序固定，便于逐字复现与回归比对）。

    evidence_block 由 `theme_event_digest.build_theme_evidence_block` 生成（fail-visible 文本），
    其头部已含语料采集日/节点数/条数与新鲜度（含未采集分支），2026-10-24a 起不再单列
    corpus_line 行（原两处信息完全重复，纯 token 浪费）；evidence_block 必须原样嵌入，
    不得在 runner 里二次改写。`headroom`（2026-10-24b Q1）= 空间题历史锚行，排在基线后、
    证据块前；None（无历史样本/无可用周期）不出行。
    2026-10-24c 三行：`forward_axis`（前向交易日轴，紧跟盘面行后）、`ladder_line`
    （板内梯队形态）、`zhaban_line`（板内炸板面），均 None 不出行（旧调用形状不变）。
    `driver_cross`（AMMO 2026-10-27b）= 个股打标交叉行，排在空间锚后、证据块前；
    None 不出行（打标缺席由 driver_cross_line 出 fail-visible 缺席行，不走本参数）。
    """
    lines = [
        f"{date} 交易日 · {market_line}",
    ]
    if forward_axis:
        lines.append(forward_axis)
    lines.append(f"待判龙头：{leader_name}（{leader_code}）")
    lines.append(structure)
    if ladder_line:
        lines.append(ladder_line)
    if zhaban_line:
        lines.append(zhaban_line)
    lines.append(baseline)
    if headroom:
        lines.append(headroom)
    if driver_cross:
        lines.append(driver_cross)
    lines.append(evidence_block)
    return "\n".join(lines)