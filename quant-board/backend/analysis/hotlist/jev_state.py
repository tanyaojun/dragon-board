# -*- coding: utf-8 -*-
"""jev state 构建器。

历史：阶段 1（情绪回放 REJECT）与阶段 2（五维打标 REJECT）的构建器已随证伪清理
（2026-09-28，数据可再生，判定留档 hotlist-jev/*.md）；仅保留阶段 3 驱动打标所需。
2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事（纯原始证据，零规则输出，零预测问）。
fail-visible 约定见 quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §8。
"""
import math
from collections import Counter

# score 锚点：0-100 共 10 档（jev score 上限 10 档）。
# 与 services/jev/jev_client.py::SCORE_ANCHORS 同源，两侧勿单方修改。
SCORE_ANCHORS_10 = ["0", "11", "22", "33", "44", "56", "67", "78", "89", "100"]

_INDEX_KEYS = ("sh", "hs300", "zz500", "zz1000")
# 2026-10-22 语料口径修复（jev-slot-corpus-caliber-fix-preregistration.md §2.1）：
# 指数行升 7 只——indexExtra 三指数（szcz/cybz/kc50，帧 10-20 起）消费 + changePct 渲染口径。
_INDEX_EXTRA_KEYS = ("szcz", "cybz", "kc50")
# 渲染顺序对齐 relay v7 D2：沪指、深成指、沪深300、中证500、中证1000、创业板指、科创50
_INDEX_RENDER_ORDER = ("sh", "szcz", "hs300", "zz500", "zz1000", "cybz", "kc50")
# 真连板口径单一事实源 = THS 连板层五池（hotspot_focus，池身份=高度；与 providers._LADDER_POOL_KEYS 同集）
_LADDER_POOL_KEYS = ("one", "two", "three", "four", "high")
_LIFECYCLE_KEYS = ("ignition", "expansion", "crowded", "reversal", "cooling", "unknown")
# 压缩行生命周期键位（2026-10-22 次级修复 C：补「反转」——sequence_stage 退潮判据弹药）
_LIFECYCLE_COMPACT_KEYS = ("ignition", "expansion", "crowded", "reversal", "cooling")
_LEADER_LIMIT = 8
_ZT_EPS = 0.999
# 2026-07-03 前旧帧 continuousBoards 键（board1..board4plus）→ 现行 yiban..sibanPlus。
# 旧 schema 未归一化曾把 07-01 09:30 的 board1=7/board2=3 算成「涨停 0」（2026-10-22
# 日级语料审计 P0-5）：buckets 是原始计数，归一化是补口径不是造数。
_LEGACY_BOARD_ALIASES = {
    "yiban": ("yiban", "board1"),
    "erban": ("erban", "board2"),
    "sanban": ("sanban", "board3"),
    "sibanPlus": ("sibanPlus", "board4plus", "board4Plus"),
}

# 五档/形态 criteria（v2 口径；_DAY_PATTERN_CRITERIA 为日级 day_pattern 消费的八类路径判据基）
# v2.5（2026-10-05）：尾盘偷袭自 low_recover 分流单列——「盘中已转强」与「收盘前才转强」对次日含义不同。
_DAY_PATTERN_CRITERIA = {
    "steady_strong": "全天强势主导（多数时段发酵/高潮）",
    "steady_weak": "全天弱势主导（多数时段退潮/冰点）",
    "rally_fade": "冲高回落：早中盘走强、尾盘转弱",
    "low_recover": "低开修复：早盘弱、盘中修复转强（临近收盘最后一至两帧才转强的判尾盘偷袭）",
    "late_rescue": "尾盘偷袭：全天多数时段弱势主导（涨停数/梯队低迷、跌多涨少），"
                   "临近收盘最后一至两帧才修复转强——修复成色待验证，与低开修复（盘中已转强）区分",
    "wide_swing": "剧烈反复：强弱多次交替",
    "narrow_range": "窄幅平淡：无明确方向、温度低位徘徊",
    "unclear": "证据不足，无法归纳",
}


def _score_question(instructions: str) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": list(SCORE_ANCHORS_10)}


# ── 问题集 v2（2026-10-02 梳理提案 P2-P4，docs/hotlist-jev/jev-sentiment-questionset-review.md）──
# 打标链四轮试点的方法论回灌：判据绑可数证据（近20日参照坐标系）、拥挤改离散归层（score 无方差已证）、
# 温度保连续分但题干锚定参照系。2026-10-02 V1 退役裁决：v1 题目常量随 v1 链删除（git 历史留档）。

_STAGE_CRITERIA_V2 = {
    "ice": "冰点：涨停数处于近20日参照低位（低于p20）、跌停或大跌股增多、赚钱效应殆尽、普遍观望",
    "start": "启动：从弱势基线修复——涨停数回升越过参照低位、试探性连板重现、新进热榜资金转活跃",
    "ferment": "发酵：赚钱效应扩散——涨停数升向参照中位以上、连板梯队成形、涨跌分布向涨侧倾斜",
    "climax": "高潮：全面亢奋——涨停数/连板高度接近或超过参照p80、涨停潮普涨、拥挤形态显现",
    "retreat": "退潮：从强势转弱——高位焦点股走弱或断板、炸板率抬升、涨停数自高位回落",
}
# 日级判据与槽级同文（历史 replace("当前","今日全天") 实证为空操作——判据文本不含"当前"，
# 日级语义由题干「综合今日全天」承载）；2026-10-05 M3 改直拷贝，行为逐字不变。
_DAY_STAGE_CRITERIA_V2 = dict(_STAGE_CRITERIA_V2)

_CROWDING_CRITERIA_V2 = {
    "top_acceleration": "高位集体加速：最高连板梯队今日仍在上攻/高度处于参照高位（≥p80）刷新，焦点高位股继续涨停，无明显断板",
    "late_seal_weakness": "封板质量弱化：炸板率高于参照 p50 或较参照明显抬升、封板率走低，涨停数虽多但封板不干脆（判据只用叙事已给出的炸板率/封板率，不要求涨停时间信息）",
    "breadth_climax": "广度高潮：涨停数/连板家数处于参照高位（≥p80），且炸板率未高于参照 p50（封板质量尚可）",
    # v2.5（2026-10-05）：出清状态单列——「从未拥挤」与「日内拥挤后缓解」语义不同，此前混装于 no_crowding。
    # 判据只锚叙事已给证据（当日已走帧 vs 当前帧 vs 参照分位），跨日拥挤对比无同源证据不入判据（v2.1 超证据判读教训）。
    "crowd_clearing": "拥挤解除（日内出清）：当日早些帧曾处于拥挤形态——涨停数或连板高度触及参照高位（≥p80），"
                      "而当前/收盘帧证据显示缓解——涨停数或最高板自当日高位明显回落、或炸板率自高位明显回落，"
                      "且赚钱效应未死（跌停/大跌未堆积，非单边退潮）",
    "no_crowding": "无拥挤迹象：涨停数低于参照 p50 或题材分散、炸板率不高于参照 p50，高位股无明显集体行为；"
                   "注意：当日/近端均未触及参照高位的日子判本层，日内触及高位后回落判 crowd_clearing",
    "insufficient_evidence": "证据不足：叙事证据无法支撑上述任何一层的判定，不强行归类（注：判定各层所需的涨停数、连板梯队、炸板率、封板率及参照分位均已在叙事中给出，通常不应落入本层）",
}

_TEMP_INSTR_V2 = ("当前短线情绪温度（0=彻底冰点，100=极度亢奋）。"
                  "以【近20日参照】段的分位刻度为坐标系：当前证据相对近20日的位置决定落点，不凭绝对语感")
_CROWD_INSTR_V2 = ("结合【当前帧】与【当日已走帧】证据及【近20日参照】，当前高位拥挤处于哪种形态？"
                   "只判当下形态，不预测后市；各档判据须锚定叙事中的涨停数、连板梯队、炸板率、封板率证据；"
                   "若叙事中【涨停与炸板】证据缺失，判 insufficient_evidence")


def _stage_question_v2(instructions: str) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": dict(_STAGE_CRITERIA_V2)}


# 题目判据演进号（2026-10-02 用户裁决：所有消费 jev 返回结果的二改方案按版本分段）。
# 判据/选项文字任何变更必须递增并同步 compute 落库；库里缺失该字段的文档=旧代产物（口径未知，fail-visible）。
# 实测断层（2026-10-02）：7/8 月旧判据与 9 月 v2.4 重跑批拥挤三层概率合计月均值 0.088/0.207/0.416，不可跨代对比。
# v2.5（2026-10-05 用户裁决「按思路先修改一版」，复跑与否待定）：①crowding 增「拥挤解除」档（出清状态
# 不再与 no_crowding 混装，五层→六层）；②day_pattern 增「尾盘偷袭」并收窄 low_recover（七类→八类）。
QUESTION_SET_VERSION = "v2.5"


JEV_SLOT_QUESTIONS = {
    "frame_stage": _stage_question_v2("仅凭【当前帧】证据，以【近20日参照】为坐标系，判断当前A股短线热榜情绪处于哪一档？"),
    "sequence_stage": _stage_question_v2("结合【当日已走帧】证据序列（含当前帧），以【近20日参照】为坐标系，判断当前情绪处于哪一档？"),
    "temperature": _score_question(_TEMP_INSTR_V2),
    "crowding": {"type": "choice", "instructions": _CROWD_INSTR_V2, "criteria": dict(_CROWDING_CRITERIA_V2)},
}

JEV_DAY_QUESTIONS = {
    "day_stage": {
        "type": "choice", "instructions": "综合今日全天连续帧证据，以【近20日参照】为坐标系，今日短线热榜情绪总体处于哪一档？",
        "criteria": dict(_DAY_STAGE_CRITERIA_V2),
    },
    "day_pattern": {
        "type": "choice", "instructions": "今日全天情绪路径属于哪种形态？",
        "criteria": dict(_DAY_PATTERN_CRITERIA),
    },
    "day_temperature": _score_question("今日全天" + _TEMP_INSTR_V2),
    "day_crowding": {"type": "choice",
                     "instructions": "综合今日全天连续帧证据及【近20日参照】，今日收盘时高位拥挤处于哪种形态？只判当下形态，不预测后市",
                     "criteria": dict(_CROWDING_CRITERIA_V2)},
}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _normalized_continuous_boards(boards: dict) -> dict:
    """现行/旧 schema 连板桶归一（只做键位映射，缺失保持 None，不补 0）。"""
    out: dict[str, int | None] = {}
    for key, aliases in _LEGACY_BOARD_ALIASES.items():
        value = None
        for alias in aliases:
            raw = boards.get(alias)
            if _finite(raw):
                value = int(raw)
                break
        out[key] = value
    return out


def derive_true_ladder_from_pools(pools: dict | None) -> dict | None:
    """THS 连板层五池（hotspot_focus）→ 真连板梯队（连板口径单一事实源，2026-10-22）。

    池身份=高度（one=1板…four=4板），high 池条目 continue_day_cnt=精确高度（10-16
    新华传媒 600825=11 连板、10-21 four 池三只=4 连板，均与 jiuyan_streak_map 交叉
    吻合）。区间口径 maxBoard（limit_up_pool continue_day=「N天M板」跨度 M）冒充连板
    是 10-21 「最高 7 连板」事故根因，本函数是修正后的取值入口。

    取数规则（宁缺毋猜）：
    - 任一池缺失/不 ok → None（relay 审查 #8 同规：半池不可用不冒充全量）；
    - 五池全零 → None（**无法区分「池未就绪」与「真无涨停」**——09:30 开盘池未就绪与
      冰点日同样是全零，任一种按 0 连板呈现都会把未就绪读数伪装成权威口径；review
      P2-3 裁决。真无涨停日的连板语义由叙事「真连板未采集」降级位承载）；
    - high 池有条目但高度字段缺失 → 池身份下限 5（≥5 板可知，精确值不可知）。

    返回 {"boards": {one..high 池计数}, "maxBoard": 真连板最高板}；pools 非法 → None。
    """
    if not isinstance(pools, dict):
        return None
    counts: dict[str, int] = {}
    max_board = 0
    for key, height in (("one", 1), ("two", 2), ("three", 3), ("four", 4)):
        pool = pools.get(key)
        if not isinstance(pool, dict) or pool.get("ok") is not True:
            return None
        items = pool.get("items")
        counts[key] = len([i for i in items if isinstance(i, dict)]) if isinstance(items, list) else 0
        if counts[key]:
            max_board = max(max_board, height)
    high = pools.get("high")
    if not isinstance(high, dict) or high.get("ok") is not True:
        return None
    high_items = [i for i in (high.get("items") or []) if isinstance(i, dict)] \
        if isinstance(high.get("items"), list) else []
    counts["high"] = len(high_items)
    for item in high_items:
        cnt = item.get("continue_day_cnt")
        if _finite(cnt) and int(cnt) > max_board:
            max_board = int(cnt)
    if high_items and max_board < 5:
        max_board = 5
    if sum(counts.values()) == 0:
        return None
    return {"boards": counts, "maxBoard": max_board}


def _calc_trin(up_count: int, down_count: int, up_turnover: float, down_turnover: float) -> float | None:
    """热榜 TRIN（Arms Index）：广度比 / 量能比。任一分母不可算返回 None（不发明数值）。"""
    if (up_count <= 0 or down_count <= 0 or up_turnover <= 0 or down_turnover <= 0):
        return None
    return round((up_count / down_count) / (up_turnover / down_turnover), 3)


def collect_slot_evidence(*, frame: dict | None, rows: list, yesterday_rows: list,
                          analysis_by_code: dict, slot_time: str,
                          yesterday_same_slot_total_amount: float | None = None,
                          daily_total_amount_fallback: float | None = None,
                          true_ladder: dict | None = None) -> dict:
    """单帧原始证据聚合（纯函数，无 IO）。

    输入仅原始数据：帧（limitSummary/indices）、行情行（pctChange/zlje/turnover/rank/reason）、
    昨日行、个股生命周期 analysis（displayStatus.stage）。**零规则五档输出**。
    yesterday_same_slot_total_amount = 昨日同一槽位帧的两市总成交额（同期量能对比基线）。
    daily_total_amount_fallback = market_daily_amount 参考集合的当日两市额（TDX 综指口径）；
    仅 15:00 槽且帧缺 indices.totalAmount 时回填 amount（09-30 前历史帧无该字段，重算保护），
    totalAmount.source=market_daily_amount_reference 标记来源（fail-visible，与帧活数据可分辨）。
    true_ladder（2026-10-22 真连板口径）= 计算层供给的外部真连板梯队（derive_true_ladder_from_pools
    输出形状 + source 键）。优先级：帧连板层五池（15:00/EOD 帧 as-of 派生）> 外部供给
    （盘中槽 ths_live / 已存槽文档 as-of 复用 / 历史日 ths_date_eod）。均不可得 → 真连板
    字段缺席 + degraded 披露，区间 maxBoard 原样保留（emotion_score 消费，零漂移）。
    fail-visible：缺源记 quality.degradedSources，保持 None/缺失，不伪造 0。
    indices.change 为涨跌额点数（帧现口径）；indexPct 为顶层 4 键 changePct 伴生
    （10-16 起帧有，渲染口径）；indices.indexExtra 为三指数帧镜像位（10-20 起）。
    totalAmount 为两市当日累计成交额（元）。
    """
    from backend.analysis.hotlist.sentiment import build_yesterday_hot_limit_evidence, derive_row_flags

    degraded: list[str] = []

    # ── 帧级：指数（4+3，changePct 伴生）+ 涨停/炸板/连板（区间+真连板）+ 两市总成交额 ──
    indices: dict = {}
    index_pct: dict = {}
    index_extra: dict = {}
    total_amount: float | None = None
    total_amount_source: str | None = None
    limit = {"ztCount": None, "maxBoard": None, "boards": {},
             "zhabanCount": None, "zhabanRate": None, "fengbanRate": None}
    if frame is None:
        degraded.append("指数缺失（帧缺失）")
        degraded.append("涨停证据缺失（帧缺失）")
    else:
        frame_indices = frame.get("indices") if isinstance(frame.get("indices"), dict) else {}
        for key in _INDEX_KEYS:
            entry = frame_indices.get(key)
            if isinstance(entry, dict):
                if _finite(entry.get("change")):
                    indices[key] = entry["change"]
                if _finite(entry.get("changePct")):
                    index_pct[key] = entry["changePct"]
        # indexExtra 三指数（深成指/创业板指/科创50）帧镜像位透传（relay v7 D2a 同款嵌套位）
        extra_raw = frame_indices.get("indexExtra")
        if isinstance(extra_raw, dict):
            for key in _INDEX_EXTRA_KEYS:
                entry = extra_raw.get(key)
                if isinstance(entry, dict) and (_finite(entry.get("change")) or _finite(entry.get("changePct"))):
                    index_extra[key] = {
                        "change": entry.get("change") if _finite(entry.get("change")) else None,
                        "changePct": entry.get("changePct") if _finite(entry.get("changePct")) else None,
                    }
        if index_extra:
            indices["indexExtra"] = index_extra
        if not any(key in indices for key in _INDEX_KEYS):
            degraded.append("指数缺失")
        # 三指数逐键缺席披露（fail-visible）：整体缺席（10-20 前历史帧）与部分失败都要报，
        # 不得让创业板指/科创50 静默消失（review P2-2）
        has_core = any(key in indices for key in _INDEX_KEYS)
        missing_extra = [name for key, name in
                         (("szcz", "深成指"), ("cybz", "创业板指"), ("kc50", "科创50"))
                         if key not in index_extra]
        if missing_extra and (has_core or index_extra):
            # 全指数块缺失时只报「指数缺失」（不叠加三指数逐键噪音）
            degraded.append("三指数缺席：" + "、".join(missing_extra))
        total_entry = frame_indices.get("totalAmount")
        if isinstance(total_entry, dict) and _finite(total_entry.get("amount")):
            total_amount = float(total_entry["amount"])
        else:
            degraded.append("两市总成交额缺失（历史帧无该字段）")
        # 15:00 槽=全日累计，历史帧缺 indices.totalAmount（09-30 才接线）时可用 market_daily_amount
        # 参考集合（TDX 综指口径）回填，重算不再冲掉锚量能坐标（2026-10-06 根治，源标记 fail-visible）；
        # 非 15:00 槽的盘中累计无法用日额近似，保持 None。
        if total_amount is None and slot_time == "15:00" and _finite(daily_total_amount_fallback):
            total_amount = float(daily_total_amount_fallback)
            total_amount_source = "market_daily_amount_reference"
            degraded.append("两市总成交额回退 market_daily_amount 参考（15:00=全日累计）")
        ls = frame.get("limitSummary") if isinstance(frame.get("limitSummary"), dict) else {}
        boards = ls.get("continuousBoards") if isinstance(ls.get("continuousBoards"), dict) else {}
        zhaban = ls.get("zhaban") if isinstance(ls.get("zhaban"), dict) else {}
        normalized_boards = _normalized_continuous_boards(boards)
        limit["boards"] = normalized_boards
        limit["maxBoard"] = boards.get("maxBoard") if _finite(boards.get("maxBoard")) else None
        limit["zhabanCount"] = zhaban.get("count") if _finite(zhaban.get("count")) else None
        limit["zhabanRate"] = zhaban.get("rate") if _finite(zhaban.get("rate")) else None
        limit["fengbanRate"] = zhaban.get("fengbanRate") if _finite(zhaban.get("fengbanRate")) else None
        zt = zhaban.get("ztCount") if _finite(zhaban.get("ztCount")) else None
        if zt is None:
            # 伪 0 防线（2026-10-22 日级审计 P0-5）：只有至少一个桶是数值才求和；
            # 全 None（现代帧未就绪）或旧 schema 已归一后仍有数值桶 → 可算。
            numeric_buckets = [v for v in normalized_boards.values() if v is not None]
            if numeric_buckets:
                zt = sum(numeric_buckets)
        limit["ztCount"] = zt
        if zt is None:
            degraded.append("涨停证据缺失")
        # 真连板口径（2026-10-22）：帧连板层五池 as-of 派生优先（15:00/EOD 帧），
        # 外部供给（true_ladder）兜底（盘中槽）；区间 maxBoard 原样保留（emotion 链消费）
        ths_pools = ls.get("thsPools") if isinstance(ls.get("thsPools"), dict) else {}
        pools = ths_pools.get("pools") if isinstance(ths_pools.get("pools"), dict) else None
        frame_ladder = derive_true_ladder_from_pools(pools)
        ladder = frame_ladder if frame_ladder is not None else (
            true_ladder if isinstance(true_ladder, dict) else None)
        if ladder is not None and _finite(ladder.get("maxBoard")):
            boards_ladder = ladder.get("boards") if isinstance(ladder.get("boards"), dict) else {}
            high_n = int(boards_ladder.get("high") or 0)
            four_n = int(boards_ladder.get("four") or 0)
            limit["trueBoards"] = {
                "yiban": int(boards_ladder.get("one") or 0),
                "erban": int(boards_ladder.get("two") or 0),
                "sanban": int(boards_ladder.get("three") or 0),
                "sibanPlus": four_n + high_n,
                "high": high_n,
            }
            limit["maxTrueBoard"] = int(ladder["maxBoard"])
            if frame_ladder is not None:
                limit["trueBoardSource"] = "frame_ths_ladder"
            else:
                limit["trueBoardSource"] = str(ladder.get("source") or "external")
        else:
            # 中性措辞：池缺失/上游请求失败/外部供给畸形在 collect 层不可分辨，
            # 具体上游错误由计算层日志承载（review P2-3），此处不做归因误导
            degraded.append("真连板未采集（连板层不可用）")
        # 封板质量 + 触板回撤池（2026-10-02 弹药扩展接线，回测过验见 ths-limitup-arsenal-audit.md）；
        # 帧无该块（历史帧/上游失败）则键缺席，fail-visible 不伪造
        sq = ls.get("sealQuality") if isinstance(ls.get("sealQuality"), dict) else {}
        if sq:
            limit["sealQuality"] = {k: sq.get(k) for k in
                                    ("byzCount", "hardCount", "rottenCount", "rottenShare", "avgSucRate")}
        dd = ls.get("drawdown") if isinstance(ls.get("drawdown"), dict) else {}
        if dd:
            limit["drawdown"] = {k: dd.get(k) for k in
                                 ("count", "avgDrawdownPct", "deepestDrawdownPct")}

    # ── 行级：涨跌分布（五桶互斥 + 缺失计数）+ 热榜 TRIN（量价确认，自算不读规则文档）──
    breadth = {"total": len(rows), "limitUp": 0, "up5": 0, "up0": 0,
               "down0": 0, "down5": 0, "pctMissing": 0}
    fund = {"zljeSum": None, "zljePos": 0, "zljeNeg": 0, "zljeMissing": 0}
    fund_total = 0.0
    fund_seen = 0
    # TRIN 原料：change>0 涨/<0 跌（与规则链同分桶），按行 turnover（成交额）分向合计；
    # TRIN = (涨家/跌家) / (涨向额/跌向额)，任一分母不可算（含单边）保持 None，不发明数值。
    trin_up_count = trin_down_count = 0
    trin_up_turnover = trin_down_turnover = 0.0
    pct_fallback_rows = 0
    for row in rows:
        pct = row.get("pctChange")
        if not _finite(pct) and _finite(row.get("change")):
            # 2026-07-03 前导入的历史行只有 change（校准重放 T1.5 实证）：字段回退，
            # 数值口径与 pctChange 一致（全库不匹配率 0.7%）；回退行数 fail-visible。
            pct = row.get("change")
            pct_fallback_rows += 1
        price, lup = row.get("price"), row.get("limitUpPrice")
        is_zt = (_finite(price) and _finite(lup) and float(price) >= float(lup) * _ZT_EPS)
        row_turnover = row.get("turnover")
        if _finite(pct):
            pct = float(pct)
            if is_zt:
                breadth["limitUp"] += 1
            elif pct >= 5:
                breadth["up5"] += 1
            elif pct >= 0:
                breadth["up0"] += 1
            elif pct > -5:
                breadth["down0"] += 1
            else:
                breadth["down5"] += 1
            if _finite(row_turnover):
                if pct > 0:
                    trin_up_count += 1
                    trin_up_turnover += float(row_turnover)
                elif pct < 0:
                    trin_down_count += 1
                    trin_down_turnover += float(row_turnover)
        else:
            breadth["pctMissing"] += 1
        zlje = row.get("zlje")
        if _finite(zlje):
            fund_total += float(zlje)
            fund_seen += 1
            if zlje > 0:
                fund["zljePos"] += 1
            elif zlje < 0:
                fund["zljeNeg"] += 1
        else:
            fund["zljeMissing"] += 1
    if fund_seen:
        fund["zljeSum"] = fund_total
    if pct_fallback_rows:
        degraded.append(f"pctChange 缺失 {pct_fallback_rows} 行（回退 change）")
    breadth["trin"] = _calc_trin(trin_up_count, trin_down_count, trin_up_turnover, trin_down_turnover)
    breadth["upTurnover"] = round(trin_up_turnover, 2) if trin_up_turnover else None
    breadth["downTurnover"] = round(trin_down_turnover, 2) if trin_down_turnover else None

    # ── 跨日：新进/淘汰 + 昨日涨停今日表现 ──
    today_codes = {str(row.get("code")) for row in rows if row.get("code")}
    if yesterday_rows:
        yesterday_codes = {str(row.get("code")) for row in yesterday_rows if row.get("code")}
        turnover = {"newCount": len(today_codes - yesterday_codes),
                    "droppedCount": len(yesterday_codes - today_codes)}
        # top_n=None = 全池口径（有意区别于规则链的池大小截断：jev 看全量昨日涨停承接）
        yesterday_limit = build_yesterday_hot_limit_evidence(yesterday_rows, rows, None)
    else:
        turnover = {"newCount": None, "droppedCount": None}
        yesterday_limit = None
        degraded.append("昨日行缺失")

    # ── 个股生命周期分布（displayStatus.stage，与规则链 join 同源口径）──
    lifecycle = {key: 0 for key in _LIFECYCLE_KEYS}
    lifecycle_missing = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        stage = analysis.get("displayStatus", {}).get("stage") if isinstance(analysis, dict) else None
        if isinstance(stage, str) and stage in lifecycle:
            lifecycle[stage] += 1
        else:
            lifecycle_missing += 1
    if rows and lifecycle_missing == len(rows):
        degraded.append("生命周期join缺失")

    # ── 行级标记：强资确认/风险预警（derive_row_flags 唯一来源，不重写判据）──
    # 行级形态判定（强资=冷却阶段强资金且量能承接；风险=反转/冷却未确认/共振存疑且主力占比转负），
    # 是规则五档的上游特征而非档位本身；只喂计数不给比率与阈值语义（保留 jev 独立解读空间）。
    strong_money_rows = 0
    risk_rows = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        if not isinstance(analysis, dict):
            continue
        flags = derive_row_flags(analysis, row)
        if flags.get("strongMoney"):
            strong_money_rows += 1
        if flags.get("risk"):
            risk_rows += 1
    row_flags = {"strongMoney": strong_money_rows, "risk": risk_rows,
                 "judgeable": len(rows) - lifecycle_missing}

    # ── 两市总成交额同期对比（当日累计 vs 昨日同一槽位累计，TDX lastcuramo 的快照等价物）──
    amount_vs_same_pct: float | None = None
    if total_amount is not None and _finite(yesterday_same_slot_total_amount) and yesterday_same_slot_total_amount > 0:
        amount_vs_same_pct = round((total_amount / float(yesterday_same_slot_total_amount) - 1) * 100, 1)

    # ── 焦点个股与涨停原因分布 ──
    # 热度降噪（2026-10-22 次级修复 D）：上游热度无供给（10-21 实证 232/232 行 heat=0）
    # 时按榜单名次排序、删「热度 0」噪音并披露；有供给时保持热度序。
    has_heat = any(_finite(r.get("heat")) and float(r["heat"]) > 0
                   for r in rows if isinstance(r, dict))

    def _sort_key(row):
        if has_heat:
            # 热度非数值行按 0 处理（review P3-4：混类型行不得 TypeError 一票否决全帧证据）
            heat = float(row["heat"]) if _finite(row.get("heat")) else 0.0
            return (-heat, row.get("rank") or 9999)
        return (row.get("rank") or 9999,)

    if rows and not has_heat:
        degraded.append("热度字段未采集（焦点个股按榜单名次）")
    leaders = []
    for row in sorted((r for r in rows if isinstance(r, dict)), key=_sort_key)[:_LEADER_LIMIT]:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        stage = analysis.get("displayStatus", {}).get("stage") if isinstance(analysis, dict) else None
        price, lup = row.get("price"), row.get("limitUpPrice")
        leaders.append({
            "name": row.get("name") or row.get("code"),
            "theme": row.get("mainTheme"),
            "pct": row.get("pctChange"),
            "zt": bool(_finite(price) and _finite(lup) and float(price) >= float(lup) * _ZT_EPS),
            "stage": stage if isinstance(stage, str) and stage else None,
            "heat": row.get("heat"),
        })
    reason_counter = Counter(
        str(row.get("reason")).strip() for row in rows
        if isinstance(row.get("reason"), str) and row.get("reason").strip())
    reasons = [[reason, count] for reason, count in reason_counter.most_common(5)]
    reasons_total = sum(reason_counter.values())

    return {
        "slotTime": slot_time,
        "indices": indices,
        "indexPct": index_pct,
        "limit": limit,
        "breadth": breadth,
        "fund": fund,
        "turnover": turnover,
        "yesterdayLimit": yesterday_limit,
        "lifecycle": lifecycle,
        "lifecycleMissing": lifecycle_missing,
        "rowFlags": row_flags,
        "totalAmount": {"amount": total_amount, "vsSamePct": amount_vs_same_pct,
                        "yesterdaySame": yesterday_same_slot_total_amount
                        if _finite(yesterday_same_slot_total_amount) else None,
                        "source": total_amount_source},
        "leaders": leaders,
        "reasons": reasons,
        "reasonsTotal": reasons_total,
        "quality": {"degradedSources": degraded},
    }


def _fmt_yi(value) -> str:
    """元 → 亿（带符号，2 位小数）；非数返回 缺。"""
    return f"{float(value) / 1e8:+.2f}亿" if _finite(value) else "缺"


_LIFECYCLE_NAMES = {"ignition": "点火", "expansion": "扩散", "crowded": "拥挤",
                    "reversal": "反转", "cooling": "冷却", "unknown": "未知"}
_INDEX_NAMES = {"sh": "沪指", "szcz": "深成指", "hs300": "沪深300", "zz500": "中证500",
                "zz1000": "中证1000", "cybz": "创业板指", "kc50": "科创50"}


def _index_bits(ev: dict) -> list[str]:
    """7 指数渲染位（2026-10-22 口径修复 A）：changePct 口径，点位为缺失降级。

    顶层 4 键 pct 优先（indexPct）→ 点位（indices）；三指数走 indices.indexExtra 镜像位。
    10-16 前历史帧无 changePct、10-20 前无 indexExtra → 对应位降级/缺席，不补 0。
    """
    idx = ev.get("indices") or {}
    pct = ev.get("indexPct") or {}
    extra = idx.get("indexExtra") if isinstance(idx.get("indexExtra"), dict) else {}
    bits: list[str] = []
    for key in _INDEX_RENDER_ORDER:
        name = _INDEX_NAMES[key]
        if key in _INDEX_KEYS:
            if _finite(pct.get(key)):
                bits.append(f"{name} {pct[key]:+.2f}%")
            elif _finite(idx.get(key)):
                bits.append(f"{name} {idx[key]:+.2f}点")
        else:
            entry = extra.get(key) or {}
            if _finite(entry.get("changePct")):
                bits.append(f"{name} {entry['changePct']:+.2f}%")
            elif _finite(entry.get("change")):
                bits.append(f"{name} {entry['change']:+.2f}点")
    return bits


def _ladder_bits(limit: dict, *, compact: bool) -> list[str]:
    """连板渲染位（2026-10-22 口径修复 B）：真连板口径，区间高度降级为标注。

    真连板可得 → 「最高 N 连板」；不可得 → 「最高区间 M 板」（compact 行）/「最高 M 板
    （区间跨度口径）」+ 降级位。杜绝区间跨度冒充连板（10-21「最高 7 连板」事故）。
    取舍：compact（已走帧/逐帧压缩行）在真连板可得时不附区间标注——序列段优先连板
    语义与篇幅，区间观察保留在当前帧段（review P3-2 已披露的设计取舍）。
    """
    bits: list[str] = []
    if limit.get("maxTrueBoard") is not None:
        bits.append(f"最高 {int(limit['maxTrueBoard'])} 连板")
        return bits
    if limit.get("maxBoard"):
        bits.append(f"最高区间 {int(limit['maxBoard'])} 板" if compact
                    else f"最高 {int(limit['maxBoard'])} 板（区间跨度口径）")
    return bits


def format_evidence_line(ev: dict) -> str:
    """单帧证据压缩行（槽位已走段与日级逐帧段共用）。缺项如实写缺。"""
    parts = [str(ev.get("slotTime") or "?")]
    idx_bits = _index_bits(ev)
    parts.append("·".join(idx_bits) if idx_bits else "指数缺")
    limit = ev.get("limit") or {}
    lim_bits = []
    if limit.get("ztCount") is not None:
        lim_bits.append(f"涨停 {int(limit['ztCount'])}")
    lim_bits.extend(_ladder_bits(limit, compact=True))
    if limit.get("zhabanRate") is not None:
        lim_bits.append(f"炸板率 {float(limit['zhabanRate']):.0f}%")
    elif limit.get("zhabanCount") is not None:
        lim_bits.append(f"炸板 {int(limit['zhabanCount'])} 家")
    if limit.get("fengbanRate") is not None:
        lim_bits.append(f"封板率 {float(limit['fengbanRate']):.0f}%")
    parts.append("·".join(lim_bits) if lim_bits else "涨停证据缺")
    breadth = ev.get("breadth") or {}
    breadth_bit = (f"涨跌 涨停{breadth.get('limitUp', 0)}/涨5+{breadth.get('up5', 0)}"
                   f"/涨{breadth.get('up0', 0)}/跌{breadth.get('down0', 0)}/大跌{breadth.get('down5', 0)}")
    if breadth.get("pctMissing"):
        breadth_bit += f"(缺{breadth['pctMissing']})"
    trin = breadth.get("trin")
    if trin is not None:
        breadth_bit += f"｜TRIN {float(trin):.2f}"
    amount = ev.get("totalAmount") or {}
    if amount.get("vsSamePct") is not None:
        amount_suffix = "（参考回填）" if amount.get("source") == "market_daily_amount_reference" else ""
        breadth_bit += f"｜量能同期{amount['vsSamePct']:+.0f}%{amount_suffix}"
    parts.append(breadth_bit)
    fund = ev.get("fund") or {}
    if fund.get("zljeSum") is not None:
        fund_bit = f"主力净额 {_fmt_yi(fund['zljeSum'])}(正{fund.get('zljePos', 0)}负{fund.get('zljeNeg', 0)})"
        if fund.get("zljeMissing"):
            fund_bit += f"缺{fund['zljeMissing']}"
        parts.append(fund_bit)
    else:
        parts.append("主力净额缺")
    turnover = ev.get("turnover") or {}
    if turnover.get("newCount") is not None:
        parts.append(f"新进 {turnover['newCount']}·淘汰 {turnover['droppedCount']}")
    else:
        parts.append("新进淘汰缺")
    yl = ev.get("yesterdayLimit")
    if isinstance(yl, dict) and yl.get("count"):
        yl_bits = [f"昨涨停承接 {int(yl['count'])} 只"]
        if yl.get("avgChange") is not None:
            yl_bits.append(f"均{float(yl['avgChange']):+.2f}%")
        if yl.get("positiveRate") is not None:
            yl_bits.append(f"红盘率{float(yl['positiveRate']) * 100:.0f}%")
        parts.append("·".join(yl_bits))
    else:
        parts.append("昨涨停承接缺")
    lifecycle = ev.get("lifecycle") or {}
    lifecycle_bit = "·".join(f"{_LIFECYCLE_NAMES[k]} {lifecycle.get(k, 0)}"
                             for k in _LIFECYCLE_COMPACT_KEYS)
    lifecycle_missing = int(ev.get("lifecycleMissing") or 0)
    if lifecycle_missing:
        lifecycle_bit += f"(缺{lifecycle_missing})"
    parts.append(lifecycle_bit)
    row_flags = ev.get("rowFlags") or {}
    if row_flags and row_flags.get("judgeable"):
        parts.append(f"强资{row_flags.get('strongMoney', 0)}·风险{row_flags.get('risk', 0)}")
    return "｜".join(parts)


def _format_current_evidence_section(ev: dict, *, title: str = "【当前帧证据】") -> str:
    lines = [title]
    idx_bits = _index_bits(ev)
    # 指数×量能同行（2026-09-30 用户建议）：强化「指数方向 × 总体量能」组合语义的可见性
    amount = ev.get("totalAmount") or {}
    amount_bit = ""
    if amount.get("amount") is not None:
        source_bit = "（market_daily_amount 参考回填）" if \
            amount.get("source") == "market_daily_amount_reference" else ""
        if amount.get("vsSamePct") is not None:
            direction = "放量" if amount["vsSamePct"] >= 0 else "缩量"
            amount_bit = f"；两市总成交额 {_fmt_yi(amount['amount'])}（较昨日同期{direction} {abs(amount['vsSamePct']):.0f}%）{source_bit}"
        else:
            amount_bit = f"；两市总成交额 {_fmt_yi(amount['amount'])}（昨日同期缺失）{source_bit}"
    lines.append("指数与量能：" + ("、".join(idx_bits) if idx_bits else "指数缺失") + amount_bit)
    limit = ev.get("limit") or {}
    boards = limit.get("boards") or {}
    true_boards = limit.get("trueBoards") or {}
    lim_bits = []
    if limit.get("ztCount") is not None:
        lim_bits.append(f"涨停 {int(limit['ztCount'])} 家")
    if limit.get("maxTrueBoard") is not None:
        # 真连板口径（2026-10-22）：梯队用连板层真值；区间高度高于真连板时随行标注
        lim_bits.append(f"最高 {int(limit['maxTrueBoard'])} 连板（真连板）")
        if any(true_boards.get(k) is not None for k in ("yiban", "erban", "sanban", "sibanPlus")):
            lim_bits.append(f"（一板{true_boards.get('yiban', 0) or 0}/二板{true_boards.get('erban', 0) or 0}"
                            f"/三板{true_boards.get('sanban', 0) or 0}/四板以上{true_boards.get('sibanPlus', 0) or 0}"
                            f"，真连板口径）")
        if _finite(limit.get("maxBoard")) and int(limit["maxBoard"]) > int(limit["maxTrueBoard"]):
            lim_bits.append(f"另有断板股区间高度最高 {int(limit['maxBoard'])} 板（跨度口径，非连板）")
    else:
        lim_bits.extend(_ladder_bits(limit, compact=False))
        if limit.get("ztCount") is not None:
            lim_bits.append("真连板该帧未采集")
    if limit.get("maxTrueBoard") is None and \
            any(boards.get(k) is not None for k in ("yiban", "erban", "sanban", "sibanPlus")):
        lim_bits.append(f"（一板{boards.get('yiban', 0) or 0}/二板{boards.get('erban', 0) or 0}"
                        f"/三板{boards.get('sanban', 0) or 0}/四板以上{boards.get('sibanPlus', 0) or 0}"
                        f"，区间跨度口径）")
    if limit.get("zhabanCount") is not None:
        lim_bits.append(f"炸板 {int(limit['zhabanCount'])} 家")
    if limit.get("zhabanRate") is not None:
        lim_bits.append(f"炸板率 {float(limit['zhabanRate']):.0f}%")
    if limit.get("fengbanRate") is not None:
        lim_bits.append(f"封板率 {float(limit['fengbanRate']):.0f}%")
    lines.append("涨停与炸板：" + ("、".join(lim_bits) if lim_bits else "缺失"))
    if (ev.get("slotTime") == "09:30" and limit.get("ztCount") == 0
            and not any(boards.get(k) for k in ("yiban", "erban", "sanban", "sibanPlus"))):
        # 09:30 开盘伪 0（5-9 月 15/98 帧）：池未就绪的概率远大于真实 0 涨停，注记提醒谨慎采信
        lines.append("（09:30 开盘时点：涨停池可能未就绪，上述 0 值谨慎采信）")
    # 封板质量 + 触板回撤池（2026-10-02 接线；块缺席=历史帧/上游失败，不伪造）
    sq = limit.get("sealQuality") or {}
    sq_bits = []
    if sq.get("byzCount") is not None or sq.get("rottenCount") is not None:
        sq_bits.append(f"一字/秒板 {sq.get('byzCount') or 0} 家、硬板 {sq.get('hardCount') or 0} 家、"
                       f"开板重封 {sq.get('rottenCount') or 0} 家")
        if sq.get("rottenShare") is not None:
            sq_bits.append(f"重封率 {float(sq['rottenShare']) * 100:.0f}%")
    if sq.get("avgSucRate") is not None:
        sq_bits.append(f"该批个股平均历史封板成功率 {float(sq['avgSucRate']) * 100:.0f}%")
    if sq_bits:
        lines.append("封板质量：" + "、".join(sq_bits))
    dd = limit.get("drawdown") or {}
    if dd.get("count") is not None:
        dd_bits = [f"大幅回撤 {int(dd['count'])} 家"]
        if dd.get("avgDrawdownPct") is not None:
            dd_bits.append(f"平均回撤 {float(dd['avgDrawdownPct']):.1f}%")
        if dd.get("deepestDrawdownPct") is not None:
            dd_bits.append(f"最深 {float(dd['deepestDrawdownPct']):.1f}%")
        lines.append("触板回撤池：" + "、".join(dd_bits))
    breadth = ev.get("breadth") or {}
    missing_bit = f"（涨幅缺失 {breadth['pctMissing']}）" if breadth.get("pctMissing") else ""
    lines.append(f"涨跌分布：共 {breadth.get('total', 0)} 只——涨停 {breadth.get('limitUp', 0)}、"
                 f"涨≥5% {breadth.get('up5', 0)}、涨0~5% {breadth.get('up0', 0)}、"
                 f"跌0~5% {breadth.get('down0', 0)}、跌≥5% {breadth.get('down5', 0)}{missing_bit}")
    trin = breadth.get("trin")
    if trin is not None:
        up_t, down_t = breadth.get("upTurnover"), breadth.get("downTurnover")
        side = "涨势放量" if trin < 1 else "量价背离（涨势缩量或跌势放量）"
        lines.append(f"热榜TRIN：{float(trin):.2f}（{side}；涨向成交 {_fmt_yi(up_t)} vs 跌向成交 {_fmt_yi(down_t)}）")
    else:
        lines.append("热榜TRIN：不可算（单边或成交额缺失）")
    fund = ev.get("fund") or {}
    if fund.get("zljeSum") is not None:
        lines.append(f"主力资金：净额合计 {_fmt_yi(fund['zljeSum'])}（正 {fund.get('zljePos', 0)} 家"
                     f"/负 {fund.get('zljeNeg', 0)} 家/缺失 {fund.get('zljeMissing', 0)} 家）")
    else:
        lines.append("主力资金：缺失")
    turnover = ev.get("turnover") or {}
    if turnover.get("newCount") is not None:
        lines.append(f"新进淘汰：新进 {turnover['newCount']}、淘汰 {turnover['droppedCount']}（对比昨日）")
    else:
        lines.append("新进淘汰：缺失（昨日行缺失）")
    yl = ev.get("yesterdayLimit")
    if isinstance(yl, dict) and yl.get("count"):
        yl_bits = [f"{int(yl['count'])} 只"]
        if yl.get("avgChange") is not None:
            yl_bits.append(f"平均 {float(yl['avgChange']):+.2f}%")
        if yl.get("positiveRate") is not None:
            yl_bits.append(f"红盘率 {float(yl['positiveRate']) * 100:.0f}%")
        if yl.get("weakeningRate") is not None:
            yl_bits.append(f"转弱率 {float(yl['weakeningRate']) * 100:.0f}%")
        if yl.get("failedOrWeakRate") is not None:
            yl_bits.append(f"失败或走弱率 {float(yl['failedOrWeakRate']) * 100:.0f}%")
        lines.append("昨日涨停今日表现：" + "、".join(yl_bits))
    else:
        lines.append("昨日涨停今日表现：缺失")
    lifecycle = ev.get("lifecycle") or {}
    missing = ev.get("lifecycleMissing") or 0
    missing_bit = f"（缺失 {missing}）" if missing else ""
    lines.append("池内生命周期：" + "、".join(
        f"{_LIFECYCLE_NAMES[k]} {lifecycle.get(k, 0)}" for k in _LIFECYCLE_KEYS) + missing_bit)
    row_flags = ev.get("rowFlags") or {}
    if row_flags and row_flags.get("judgeable"):
        judgeable = row_flags["judgeable"]
        sm, risk = row_flags.get("strongMoney", 0), row_flags.get("risk", 0)
        lines.append(f"行级标记：资金确认 {sm} 只（冷却阶段强资金且量能承接，攻击强度，占可判定 {round(sm / judgeable * 100)}%）"
                     f"/ 风险预警 {risk} 只（反转、冷却未确认、或共振存疑且主力净占比转负，撤退压力，占可判定 {round(risk / judgeable * 100)}%）")
    leaders = ev.get("leaders") or []
    if leaders:
        leader_bits = []
        for leader in leaders:
            pct = leader.get("pct")
            bits = [str(leader.get("name") or "?"),
                    str(leader.get("theme") or "题材缺"),
                    f"{float(pct):+.2f}%" if _finite(pct) else "涨幅缺"]
            if leader.get("zt"):
                bits.append("涨停")
            if leader.get("stage"):
                bits.append(_LIFECYCLE_NAMES.get(leader["stage"], str(leader["stage"])))
            # 热度降噪（2026-10-22 D）：上游无供给时不渲染「热度 0」噪音
            if _finite(leader.get("heat")) and float(leader["heat"]) > 0:
                bits.append(f"（热度 {leader['heat']}）")
            leader_bits.append("／".join(bits))
        lines.append("焦点个股：" + "；".join(leader_bits))
    reasons = ev.get("reasons") or []
    if reasons:
        # 原因口径（2026-10-22 E）：披露「有原因个股 N 只，原因列前 5 类」——reasons 是
        # distinct 原因聚合，非个股清单，措辞按「类」表述避免「列前 5 只」歧义（review P3-5）
        total = ev.get("reasonsTotal")
        prefix = "涨停原因" if not (_finite(total) and int(total) > len(reasons)) else \
            f"涨停原因（有原因个股 {int(total)} 只，原因列前 {len(reasons)} 类）"
        lines.append(prefix + "：" + "、".join(f"{reason} ×{count}" for reason, count in reasons))
    return "\n".join(lines)


def build_history_anchor(stats: list, window: int = 20) -> str:
    """近 N 交易日收盘统计 → 【近20日参照】段（问题集 v2 的坐标系，P1）。

    stats = [{date, ztCount, maxTrueBoard, amountYi, zhabanRate}, ...] 升序、仅含严格早于当日的日期
    （as-of 无前视，由调用方保证）。分位=idx 法（与 diagnose_jev_temp_crowding 同式）。
    指标样本 <8 时该指标如实标注"历史样本不足"，不伪造刻度（fail-visible）。
    """
    def _q(vals, p):
        s = sorted(vals)
        return s[min(len(s) - 1, max(0, int(p * (len(s) - 1))))]

    def _metric(name, key, fmt):
        entries = [(s["date"], s[key]) for s in stats if isinstance(s.get(key), (int, float))]
        if len(entries) < 8:
            return f"{name} 历史样本不足（{len(entries)} 日）"
        vals = [v for _, v in entries]
        q20, q50, q80 = _q(vals, 0.2), _q(vals, 0.5), _q(vals, 0.8)
        last_date, last = entries[-1]
        # 标注实际样本日期：最近历日缺数时 vals[-1] 可能是更早的值，写"昨日"会误标
        # 2026-10-22 日级审计 P1-3：8..19 样本时旧实现静默用薄样本，补「有效 N/20」披露
        sample_bit = f"，有效样本 {len(entries)}/{window}" if len(entries) < window else ""
        return (f"{name}：p20={fmt(q20)} / p50={fmt(q50)} / p80={fmt(q80)}"
                f"（{last_date} {fmt(last)}）{sample_bit}")

    if not stats:
        return "【近20日参照】历史参照缺失（无可用历史槽文档）——判读时如实按绝对证据处理，不得虚构对比。"
    lines = [
        f"【近20日参照】（{stats[0]['date']} → {stats[-1]['date']}，{len(stats)} 个交易日收盘统计，判读坐标系）",
        _metric("涨停数", "ztCount", lambda v: f"{int(v)} 家"),
        # 2026-10-22 真连板口径：锚「最高连板」改 maxTrueBoard（区间 maxBoard 10-21 前污染主坐标系）
        _metric("最高连板", "maxTrueBoard", lambda v: f"{int(v)} 板"),
        _metric("两市成交额", "amountYi", lambda v: f"{v:.0f} 亿"),
        _metric("炸板率", "zhabanRate", lambda v: f"{v:.0f}%"),
    ]
    # 真连板锚来源覆盖（2026-10-22 日级审计 P1-3）：同一指标跨四源，不披露来源等于
    # 让模型把「槽文档/帧/参考集合」混成一份匿名分位。
    sources = Counter(str(s.get("maxTrueBoardSource")) for s in stats
                      if s.get("maxTrueBoardSource"))
    if sources:
        names = {"slot_doc": "槽文档", "frame_15": "15:00帧",
                 "market_true_ladder": "参考集合", "none": "缺"}
        lines.append("最高连板来源：" + " / ".join(
            f"{names.get(key, key)} {count}" for key, count in sources.items()))
    return "\n".join(lines)


def extract_history_anchor_range(anchor: str) -> str | None:
    """【近20日参照】首行括号内区间（面板锚 chip 用）。

    仅当首行严格以「【近20日参照】（」开头、以「）」结尾时截取；历史参照缺失等
    非标准首行不做定长硬切（[len(prefix):-1] 在缺失行上会错位产出半截句），回退 None。
    """
    first_line = anchor.split("\n", 1)[0]
    prefix = "【近20日参照】（"
    if first_line.startswith(prefix) and first_line.endswith("）"):
        return first_line[len(prefix):-1] or None
    return None


def build_slot_jev_state(*, trading_date: str, slot_time: str, current: dict,
                         priors: list, missing_slots: list | None = None,
                         history_anchor: str = "") -> str:
    """槽位叙事 state（Q1 当前帧 + Q2 当日序列共用一次调用的输入）。

    priors = 当日早于本槽各帧的 evidence（升序）；missing_slots = 预期槽位中无帧的槽。
    零规则输出：输入输出均不含规则五档/摘要/信号。
    """
    degraded = list((current.get("quality") or {}).get("degradedSources") or [])
    if missing_slots:
        degraded.append("缺失槽位：" + "、".join(missing_slots))
    prior_lines = [format_evidence_line(ev) for ev in priors if isinstance(ev, dict)]
    lines = [
        f"{trading_date} {slot_time} 时点快照（A股短线热榜情绪观察，原始市场证据）。",
        history_anchor,
        _format_current_evidence_section(current),
        "【当日已走帧证据】\n" + ("\n".join(prior_lines) if prior_lines else "（本日暂无更早已落库帧）"),
        "【数据质量】" + ("；".join(degraded) if degraded else "无缺失") + "。",
    ]
    return "\n".join(line for line in lines if line)[:4000]


def _day_frame_coverage(evidences: list, *, expected_slots: list | None = None,
                        present_slots: list | None = None,
                        skipped_frames: list | None = None) -> dict:
    """日级帧覆盖（2026-10-22 日级审计 P0-4）：预期/实际/缺失/无证据/收盘帧。"""
    evidence_slots = [str(ev.get("slotTime")) for ev in evidences if isinstance(ev, dict)]
    if present_slots is None:
        present_slots = evidence_slots
    present = sorted({str(s) for s in present_slots})
    expected = sorted({str(s) for s in (expected_slots if expected_slots is not None else present)})
    missing = [s for s in expected if s not in present]
    empty = [dict(x) for x in (skipped_frames or []) if isinstance(x, dict)]
    last_slot = present[-1] if present else (evidence_slots[-1] if evidence_slots else None)
    return {
        "expectedSlots": expected,
        "presentSlots": present,
        "evidenceSlots": evidence_slots,
        "missingSlots": missing,
        "emptyEvidenceSlots": empty,
        "lastSlot": last_slot,
        "hasCloseFrame": bool(evidence_slots) and evidence_slots[-1] == "15:00",
        "frameCount": len(present),
        "evidenceCount": len(evidence_slots),
        "expectedCount": len(expected),
    }


def summarize_day_evidence(evidences: list, *, expected_slots: list | None = None,
                           present_slots: list | None = None,
                           skipped_frames: list | None = None) -> dict:
    """日级证据摘要（叙事与 evidenceRaw 共用，单一事实源）。

    trueBoardCoverage 语义：`full`=全部预期帧都有真连板；`close_only`=仅 15:00
    收盘帧有真连板（历史回放）；`partial`=有真连板但覆盖不足（可能低估）；
    `none`=无真连板（区间口径降级）。
    """
    evidences = [ev for ev in evidences if isinstance(ev, dict)]
    coverage = _day_frame_coverage(
        evidences, expected_slots=expected_slots, present_slots=present_slots,
        skipped_frames=skipped_frames)
    close = evidences[-1] if coverage["hasCloseFrame"] else None
    close_limit = (close.get("limit") or {}) if close else {}
    true_items = []
    zt_vals = []
    range_vals = []
    for ev in evidences:
        lim = ev.get("limit") or {}
        mtb = lim.get("maxTrueBoard")
        if _finite(mtb):
            true_items.append((str(ev.get("slotTime")), int(mtb)))
        mb = lim.get("maxBoard")
        if _finite(mb):
            range_vals.append(int(mb))
        zt = lim.get("ztCount")
        if _finite(zt):
            zt_vals.append(int(zt))
    expected_count = coverage["expectedCount"] or 0
    true_frames = len(true_items)
    if not true_items:
        true_coverage = "none"
    elif (expected_count and true_frames >= expected_count
          and coverage["frameCount"] == expected_count
          and coverage["hasCloseFrame"]
          and not coverage["emptyEvidenceSlots"]):
        true_coverage = "full"
    elif true_frames == 1 and true_items[0][0] == "15:00" and coverage["hasCloseFrame"]:
        true_coverage = "close_only"
    else:
        true_coverage = "partial"
    close_amount = (close.get("totalAmount") or {}).get("amount") if close else None
    close_amount_source = (close.get("totalAmount") or {}).get("source") if close else None
    close_deg = ((close.get("quality") or {}).get("degradedSources") or []) if close else []
    return {
        "frameCoverage": coverage,
        "peakZt": max(zt_vals) if zt_vals else None,
        "closeZt": int(close_limit["ztCount"]) if _finite(close_limit.get("ztCount")) else None,
        "peakTrueBoard": max(v for _, v in true_items) if true_items else None,
        "peakRangeBoard": max(range_vals) if range_vals else None,
        "trueBoardFrames": true_frames,
        "trueBoardCoverage": true_coverage,
        "closeZhabanRate": close_limit.get("zhabanRate") if _finite(close_limit.get("zhabanRate")) else None,
        "closeFengbanRate": close_limit.get("fengbanRate") if _finite(close_limit.get("fengbanRate")) else None,
        "closeAmount": close_amount if _finite(close_amount) else None,
        "closeAmountSource": close_amount_source,
        "closeHeatMissing": any(s.startswith("热度字段未采集") for s in close_deg),
    }


def _true_board_peak_bit(summary: dict) -> str:
    peak = summary.get("peakTrueBoard")
    if peak is not None:
        frames = summary["trueBoardFrames"]
        expected = summary["frameCoverage"]["expectedCount"] or frames
        if summary["trueBoardCoverage"] == "close_only":
            return f"收盘真连板 {int(peak)} 板（仅收盘帧有真连板）"
        if summary["trueBoardCoverage"] == "full":
            return f"全日真连板峰值 {int(peak)} 板（{frames}/{expected} 帧有真连板）"
        return f"真连板峰值 {int(peak)} 板（{frames}/{expected} 帧有真连板，可能低估）"
    range_peak = summary.get("peakRangeBoard")
    if range_peak:
        return f"最高区间板峰值 {int(range_peak)} 板（真连板未采集）"
    return "最高连板峰值 缺"


def _format_frame_coverage(coverage: dict) -> str:
    first = coverage["presentSlots"][0] if coverage["presentSlots"] else "无"
    text = (f"帧 {coverage['frameCount']}/{coverage['expectedCount']}"
            f"（{first}–{coverage['lastSlot'] or '无'}，收盘帧 "
            f"{'15:00' if coverage['hasCloseFrame'] else '缺'}）")
    if coverage["missingSlots"]:
        text += "；缺失槽位：" + "、".join(coverage["missingSlots"])
    if coverage["emptyEvidenceSlots"]:
        text += "；无证据帧：" + "、".join(
            f"{x.get('slot')}({x.get('reason') or 'unknown'})"
            for x in coverage["emptyEvidenceSlots"])
    return text


def _aggregate_day_quality(evidences: list, summary: dict) -> list[str]:
    """日级质量聚合（2026-10-22 日级审计 P0-6）：按槽位/证据种类计数，不做字符串去重。

    槽级缺失噪音（盘中每帧「两市额缺失」、非收盘帧热度）不得淹没/冒充日级真实缺失。
    """
    coverage = summary["frameCoverage"]
    total = max(coverage["evidenceCount"], 1)
    idx_slots, limit_slots, amount_slots, true_slots = [], [], [], []
    pct_frames = yesterday_frames = lifecycle_all = 0
    other: Counter = Counter()
    for ev in evidences:
        slot = str(ev.get("slotTime"))
        deg = (ev.get("quality") or {}).get("degradedSources") or []
        if any(s == "指数缺失" or s.startswith("三指数缺席") for s in deg):
            idx_slots.append(slot)
        if any(s == "涨停证据缺失" for s in deg):
            limit_slots.append(slot)
        if any(s.startswith("两市总成交额缺失") for s in deg):
            amount_slots.append(slot)
        if any(s.startswith("真连板未采集") for s in deg):
            true_slots.append(slot)
        if any(s.startswith("pctChange 缺失") for s in deg):
            pct_frames += 1
        if any(s == "昨日行缺失" for s in deg):
            yesterday_frames += 1
        if any(s == "生命周期join缺失" for s in deg):
            lifecycle_all += 1
        for item in deg:
            if item.startswith(("指数缺失", "三指数缺席", "涨停证据缺失", "两市总成交额缺失",
                                "真连板未采集", "pctChange 缺失", "昨日行缺失",
                                "生命周期join缺失", "热度字段未采集")):
                continue
            other[item] += 1

    items: list[str] = []
    if coverage["missingSlots"]:
        items.append("缺失槽位：" + "、".join(coverage["missingSlots"]))
    if coverage["emptyEvidenceSlots"]:
        items.append("无证据帧：" + "、".join(
            f"{x.get('slot')}({x.get('reason') or 'unknown'})"
            for x in coverage["emptyEvidenceSlots"]))
    if not coverage["hasCloseFrame"]:
        items.append(f"无 15:00 收盘帧（末帧 {coverage['lastSlot'] or '无'}；日级判读非全天口径）")
    if idx_slots:
        items.append(f"指数缺失 {len(idx_slots)}/{total} 帧（{'、'.join(idx_slots)}）")
    if limit_slots:
        items.append(f"涨停证据缺失 {len(limit_slots)}/{total} 帧（{'、'.join(limit_slots)}）")
    if amount_slots:
        if summary.get("closeAmount") is not None:
            suffix = "（收盘帧已回填）" if summary.get("closeAmountSource") else "（收盘帧已采集）"
            items.append(f"盘中 {len(amount_slots)} 帧无量能字段{suffix}")
        else:
            items.append(f"两市总成交额缺失 {len(amount_slots)}/{total} 帧；收盘帧亦缺")
    if true_slots:
        if (coverage["hasCloseFrame"] and summary.get("trueBoardCoverage") == "close_only"):
            early = [s for s in true_slots if s != "15:00"]
            items.append(f"早盘 {len(early)} 帧真连板未采集（收盘帧可得）")
        else:
            items.append(f"真连板未采集 {len(true_slots)}/{total} 帧")
    if pct_frames:
        items.append(f"pctChange 回退 {pct_frames} 帧（旧行只有 change）")
    if yesterday_frames:
        items.append(f"昨日行缺失 {yesterday_frames} 帧")
    if lifecycle_all:
        items.append(f"生命周期join缺失 {lifecycle_all} 帧")
    if summary.get("closeHeatMissing"):
        items.append("收盘帧热度字段未采集（焦点个股按榜单名次）")
    for item, count in other.items():
        items.append(item if count == 1 else f"{item} ×{count}")
    return items


def build_day_jev_state(*, trading_date: str, evidences: list,
                        yesterday_close_total_amount: float | None = None,
                        history_anchor: str = "",
                        expected_slots: list | None = None,
                        present_slots: list | None = None,
                        skipped_frames: list | None = None) -> str:
    """日级叙事 state（盘后固定当日总体）。evidences = 全日各帧 evidence 升序。

    2026-10-22 日级语料修复（jev-eod-corpus-caliber-audit-preregistration.md）：
    - 增加【收盘帧证据】全量块（day_crowding 判据所需的封板率/封板质量/回撤/焦点/原因）；
    - 增加【帧覆盖】，缺槽/无 15:00/无证据帧显式披露；
    - 真连板峰值按覆盖度标注（收盘值不冒充全日峰值）；
    - 质量段按槽位/证据种类计数，避免槽级噪音淹没日级真实缺失。
    """
    evidences = [ev for ev in evidences if isinstance(ev, dict)]
    if not evidences:
        return f"{trading_date} 交易日全天热榜情绪证据轨迹：无帧证据。"
    summary = summarize_day_evidence(
        evidences, expected_slots=expected_slots, present_slots=present_slots,
        skipped_frames=skipped_frames)
    coverage = summary["frameCoverage"]
    close = evidences[-1] if coverage["hasCloseFrame"] else None
    last = close if close is not None else evidences[-1]
    last_slot = str(last.get("slotTime") or "?")
    turnover = last.get("turnover") or {}
    fund = last.get("fund") or {}
    peak_bit = _true_board_peak_bit(summary)
    new_bit = f"新进 {turnover['newCount']}" if turnover.get("newCount") is not None else "新进 缺"
    dropped_bit = f"淘汰 {turnover['droppedCount']}" if turnover.get("droppedCount") is not None else "淘汰 缺"

    zt_bits: list[str] = []
    if summary["closeZt"] is not None:
        zt_bits.append(f"收盘涨停 {summary['closeZt']}")
    if summary["peakZt"] is not None and summary["peakZt"] != summary["closeZt"]:
        zt_bits.append(f"全日最高涨停 {summary['peakZt']}")
    if summary["closeZhabanRate"] is not None:
        zt_bits.append(f"收盘炸板率 {float(summary['closeZhabanRate']):.0f}%")
    if summary["closeFengbanRate"] is not None:
        zt_bits.append(f"收盘封板率 {float(summary['closeFengbanRate']):.0f}%")
    zt_bit = "、".join(zt_bits) if zt_bits else "收盘涨停/炸板 缺"

    fund_asof = "" if close is not None else f"（截至 {last_slot}）"
    last_amount = (last.get("totalAmount") or {}).get("amount")
    source_suffix = "（参考回填）" if \
        (last.get("totalAmount") or {}).get("source") == "market_daily_amount_reference" else ""
    amount_asof = "" if close is not None else f"（截至 {last_slot}）"
    amount_bit = f"；两市总成交额 {_fmt_yi(last_amount)}{source_suffix}{amount_asof}"
    if last_amount is not None and _finite(yesterday_close_total_amount) and yesterday_close_total_amount > 0:
        pct = (float(last_amount) / float(yesterday_close_total_amount) - 1) * 100
        amount_bit += f"（较昨日全天{'放量' if pct >= 0 else '缩量'} {abs(pct):.0f}%）"

    lines = [
        f"{trading_date} 交易日全天热榜情绪证据轨迹（A股短线情绪观察，原始市场证据）。",
        history_anchor,
        "【逐帧证据】\n" + "\n".join(format_evidence_line(ev) for ev in evidences),
    ]
    if expected_slots is not None or coverage["missingSlots"] or coverage["emptyEvidenceSlots"] \
            or not coverage["hasCloseFrame"]:
        lines.append("【帧覆盖】" + _format_frame_coverage(coverage))
    if close is not None:
        lines.append(_format_current_evidence_section(close, title="【收盘帧证据】"))
    else:
        lines.append(
            f"【收盘帧证据】\n收盘帧缺失（末帧 {coverage['lastSlot'] or '无'}）；"
            "日级判读非全天口径，结论谨慎采信。")
    lines.append(
        f"【当日累计】{new_bit}、{dropped_bit}（对比昨日）；"
        f"主力净额合计 {_fmt_yi(fund.get('zljeSum'))}{fund_asof}；{zt_bit}；{peak_bit}{amount_bit}")
    quality = _aggregate_day_quality(evidences, summary)
    lines.append("【数据质量】" + ("；".join(quality) if quality else "无缺失") + "。")
    return "\n".join(line for line in lines if line)[:6000]
