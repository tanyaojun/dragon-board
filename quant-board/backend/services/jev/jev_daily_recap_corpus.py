# -*- coding: utf-8 -*-
"""复盘日报语料拼装层（jev daily recap，2026-10-31 用户裁决预登记）。

设计/预登记：quant-board/docs/hotlist-jev/jev-daily-recap-design.md。
- 语料包 = state（上涨/下跌复盘可数事实 + 情绪链锚点，全部可数）+ 5 道 choice 题
  （判据只引用 state 已有字段，v2.1 教训）+ 单 call 输出合同（call_jev/parse_jev_response）；
- 成文 = 版本化模板 × 槽位值 + 短叙事预写文段库（NARRATIVE_LIBRARY，§1 实现裁决：
  jev 题型合同只见 choice/score，自由文本题型未验证 → 短叙事零 jev 措辞）；
- 机械判 = 一致率对照基线 + 兜底（判据与题目 criteria 同数，改一处须同步文档）；
- 本模块纯函数零 IO 零外呼：review 字典/情绪锚点由 operations 层装载（monkeypatch 边界）。

纪律：pytest 一律 mock，禁真调用（硬红线 §1.2#7）；缺料不伪造（fail-visible，§4.0）。
"""
from __future__ import annotations

from typing import Any

# 版本戳（换代必须登记 jev-daily-recap-design.md；跨代不可比）
RECAP_TEMPLATE_VERSION = 1
QUESTION_SET_VERSION_RECAP = "v1"

# 归层档位（choices 集预登记；机械判与题目 criteria 同数）
RECAP_SHAPE_CHOICES = ("强势延续", "分歧加剧", "退潮防守", "冰点修复", "混沌轮动",
                       "insufficient_evidence")
MONEY_STYLE_CHOICES = ("接力为主", "低吸为主", "观望为主", "insufficient_evidence")
PLAN_BIAS_CHOICES = ("进攻", "均衡", "防守", "insufficient_evidence")
RISK_FLAG_CHOICES = ("高风险", "中风险", "低风险", "insufficient_evidence")
FOCUS_FALLBACK = "空仓观望"

RECAP_UNKNOWN = "未判定"

# 机械判阈值（与 _questions 的 criteria 文案同数，改一处须同步文档并登记设计文档）
_R_RATIO_STRONG = 2.0      # 涨跌比强市线
_R_BOTH_HOT = 10           # 两旺线：池内涨/跌家数
_R_LIMITDOWN_DEFENSE = 5   # 跌停家数退潮线
_R_BIGFACE_WATCH = 5       # 大面家数观望/高风险线
_R_LIMITDOWN_RISK = 10     # 跌停家数高风险线
_R_STREAK = 3              # 梯队高度线（连涨/连跌）

_SHAPE_ORDER = ("big_face", "zha_ban", "fade", "high_close", "tail_dive",
                "up", "down", "flat")
_SHAPE_CN = {"big_face": "大面", "zha_ban": "炸板", "fade": "冲高回落",
             "high_close": "强势", "tail_dive": "尾盘跳水", "up": "上涨",
             "down": "下跌", "flat": "平盘"}

# rise topBoards 里的兕底桶：无板块归属，不得作为主攻方向档位（评审 2026-10-31）
_UNSEGMENTED_BOARD = "未分板块"


# ---------------------------------------------------------------- 纯函数：事实压缩

def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _shape_counts(stocks: list[dict[str, Any]]) -> dict[str, int]:
    """stocks[].shape 形态计数（None=封板/缺料不计入；缺失保持缺失不伪造）。"""
    counts = {k: 0 for k in _SHAPE_ORDER}
    for s in stocks or []:
        shape = (s or {}).get("shape")
        if shape in counts:
            counts[shape] += 1
    return counts


def _top_stocks(stocks: list[dict[str, Any]], n: int, reverse: bool) -> list[dict[str, Any]]:
    """头部名单简表（按涨跌幅排序取前 n；缺涨跌幅的行排末位，如实保留）。"""
    rows = [s for s in (stocks or []) if (s or {}).get("pctChange") is not None]
    rows.sort(key=lambda s: s["pctChange"], reverse=reverse)
    return [{"code": s.get("code"), "name": s.get("name"), "board": s.get("board"),
             "pctChange": s.get("pctChange"), "shape": s.get("shape"),
             "streak": s.get("streak")} for s in rows[:n]]


def collect_review_facts(rise: dict[str, Any] | None,
                         dieban: dict[str, Any] | None) -> dict[str, Any]:
    """两页复盘字典 → 可数事实包（纯函数）。缺页/损坏 → 该页 noData=true + degraded 登记。"""
    degraded: list[dict[str, str]] = []

    def _page(doc: dict[str, Any] | None, tag: str) -> dict[str, Any]:
        if not isinstance(doc, dict) or doc.get("ok") is not True:
            degraded.append({"source": tag, "reason": "review_doc_unavailable", "action": "page_absent"})
            return {"noData": True}
        if doc.get("noData") is True:
            # ok=True 但 noData=True（当日无快照行/未到截点）：结构化原因必须透传，
            # 否则 pilot 门2（degraded 天数占比）系统性低估 noData 日（评审 Major-1，2026-10-31）
            degraded.append({"source": tag, "reason": str(doc.get("reason") or "page_no_data"),
                             "action": "page_no_data"})
        for item in doc.get("degraded") or []:
            degraded.append({"source": tag, "reason": f"{item.get('scope')}: {item.get('reason')}",
                             "action": "passthrough"})
        return doc

    rise_doc = _page(rise, "rise")
    dieban_doc = _page(dieban, "dieban")

    def _g(doc: dict[str, Any], *path: str) -> Any:
        cur: Any = doc
        for p in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur

    rise_pool = _g(rise_doc, "pool") or {}
    rise_pos = _g(rise_doc, "positive") or {}
    rise_full = _g(rise_doc, "fullRise") or {}
    dieban_pool = _g(dieban_doc, "pool") or {}
    dieban_neg = _g(dieban_doc, "negative") or {}
    full_market = _g(dieban_doc, "fullMarket") or {}

    rise_stocks = rise_doc.get("stocks") if isinstance(rise_doc.get("stocks"), list) else []
    dieban_stocks = dieban_doc.get("stocks") if isinstance(dieban_doc.get("stocks"), list) else []
    rise_shapes = _shape_counts(rise_stocks)
    dieban_shapes = _shape_counts(dieban_stocks)

    return {
        "rise": {
            "noData": bool(rise_doc.get("noData")),
            "poolUp": _num(rise_pool.get("up")),
            "poolDown": _num(rise_pool.get("down")),
            "ratio": _num(rise_pool.get("ratio")),
            "riseCount": _num(rise_full.get("count")),
            "strong": _num(rise_pool.get("strong")),
            "streak2": _num(rise_pool.get("streak2")),
            "maxStreak": _num(rise_pool.get("maxStreak")),
            "netInflowTotal": _num(rise_pos.get("netInflowTotal")),
            "topBoards": (rise_pos.get("topBoards") or [])[:5],
            "topStocks": _top_stocks(rise_stocks, 5, reverse=True),
            "shapes": rise_shapes,
        },
        "dieban": {
            "noData": bool(dieban_doc.get("noData")),
            "poolUp": _num(dieban_pool.get("up")),
            "poolDown": _num(dieban_pool.get("down")),
            "limitDownCount": _num(full_market.get("count")),
            "deepDrop": _num(dieban_pool.get("deepDrop")),
            "oneWord": _num(dieban_pool.get("oneWord")),
            "streak2": _num(dieban_pool.get("streak2")),
            "maxStreak": _num(dieban_pool.get("maxStreak")),
            "netOutflowTotal": _num(dieban_neg.get("netOutflowTotal")),
            "topBoards": (dieban_neg.get("topBoards") or [])[:5],
            "topStocks": _top_stocks(dieban_stocks, 5, reverse=False),
            "shapes": dieban_shapes,
        },
        "degradedSources": degraded,
    }


def rule_recap_shape(facts: dict[str, Any]) -> str:
    """复盘归层机械判（优先级从上到下；与 RECAP_QUESTIONS.recap_shape criteria 同数）。

    两页全缺 → insufficient_evidence；任一页可用即按可数锚点判（缺的字段视为不满足该分支）。
    """
    r, d = facts["rise"], facts["dieban"]
    if r["noData"] and d["noData"]:
        return "insufficient_evidence"
    pool_up, pool_down = r["poolUp"], r["poolDown"]   # 两旺口径：采集池涨/跌家数（同页）
    ratio, big_face, zha_ban = r["ratio"], r["shapes"]["big_face"], r["shapes"]["zha_ban"]
    high_close = r["shapes"]["high_close"]
    limit_down, max_streak_r = d["limitDownCount"], r["maxStreak"]
    max_streak_d = d["maxStreak"]
    if (ratio is not None and ratio >= _R_RATIO_STRONG
            and big_face <= zha_ban
            and max_streak_r is not None and max_streak_r >= _R_STREAK):
        return "强势延续"
    if (pool_up is not None and pool_up >= _R_BOTH_HOT
            and pool_down is not None and pool_down >= _R_BOTH_HOT
            and big_face > 0 and high_close > 0):
        return "分歧加剧"
    if ((big_face > high_close)
            and limit_down is not None and limit_down >= _R_LIMITDOWN_DEFENSE):
        return "退潮防守"
    if (max_streak_d is not None and max_streak_d >= _R_STREAK
            and pool_up is not None and pool_down is not None
            and pool_up >= pool_down):
        return "冰点修复"
    return "混沌轮动"


def rule_money_style(facts: dict[str, Any]) -> str:
    """赚钱效应档位机械判（与 money_style criteria 同数）。"""
    r, d = facts["rise"], facts["dieban"]
    if r["noData"] and d["noData"]:
        return "insufficient_evidence"
    ratio, big_face = r["ratio"], r["shapes"]["big_face"]
    if ratio is not None and ratio >= _R_RATIO_STRONG and big_face == 0:
        return "接力为主"
    if ((big_face >= _R_BIGFACE_WATCH)
            or (d["limitDownCount"] is not None and d["limitDownCount"] >= _R_LIMITDOWN_RISK)):
        return "观望为主"
    return "低吸为主"


def rule_plan_bias(recap_shape: str) -> str:
    """隔日计划倾向机械判（与 plan_bias criteria 同数：强势延续→进攻；退潮防守→防守；其余→均衡）。"""
    if recap_shape == "强势延续":
        return "进攻"
    if recap_shape == "退潮防守":
        return "防守"
    if recap_shape == "insufficient_evidence":
        return "insufficient_evidence"
    return "均衡"


def rule_focus_direction(facts: dict[str, Any]) -> str:
    """主攻方向机械判：rise 正向板块 top1（空名单/兕底桶「未分板块」→ 空仓观望）。"""
    boards = facts["rise"]["topBoards"]
    for b in boards:
        name = str(b.get("board") or "")
        if name and name != _UNSEGMENTED_BOARD:
            return name
    return FOCUS_FALLBACK


def rule_risk_flag(facts: dict[str, Any]) -> str:
    """风险档位机械判（与 risk_flag criteria 同数）。"""
    r, d = facts["rise"], facts["dieban"]
    if r["noData"] and d["noData"]:
        return "insufficient_evidence"
    big_face, limit_down = r["shapes"]["big_face"], d["limitDownCount"]
    if big_face >= _R_BIGFACE_WATCH or (limit_down is not None and limit_down >= _R_LIMITDOWN_RISK):
        return "高风险"
    if big_face == 0 and limit_down == 0 and (r["ratio"] is not None and r["ratio"] >= _R_RATIO_STRONG):
        return "低风险"
    return "中风险"


RULES = {"recap_shape": rule_recap_shape, "money_style": rule_money_style,
         "plan_bias": lambda facts: rule_plan_bias(rule_recap_shape(facts)),
         "focus_direction": rule_focus_direction, "risk_flag": rule_risk_flag}


# ---------------------------------------------------------------- 题料包 / state

def build_questions(facts: dict[str, Any]) -> dict[str, Any]:
    """5 道 choice 题（单 call；focus_direction choices = rise 正向板块 top8 + 空仓观望，动态）。

    判据只引用 state.summary 已有字段（v2.1 教训）；阈值与 RULES 机械判同数。
    """
    boards = [str(b.get("board")) for b in facts["rise"]["topBoards"]
              if b.get("board") and str(b.get("board")) != _UNSEGMENTED_BOARD]
    focus_choices = boards[:8] + [FOCUS_FALLBACK]
    return {
        "recap_shape": {
            "type": "choice",
            "instructions": (
                "根据今日上涨/下跌复盘可数事实（采集池涨跌家数与比、形态计数 大面/炸板/冲高回落/强势/"
                "尾盘跳水、连涨连跌梯队高度、全市场跌停家数），今日全天属于哪种复盘归层？"
                "只描述当日已发生事实，不预测后市。"
            ),
            "criteria": {
                "强势延续": f"采集池涨跌比≥{_R_RATIO_STRONG:g} 且 大面≤炸板 且 连涨高度≥{_R_STREAK}",
                "分歧加剧": f"两旺：池内涨≥{_R_BOTH_HOT} 且 跌≥{_R_BOTH_HOT}，且 大面>0 且 强势>0（形态分化）",
                "退潮防守": f"大面>强势 且 全市场跌停≥{_R_LIMITDOWN_DEFENSE}",
                "冰点修复": f"连跌高度≥{_R_STREAK}（负反馈梯队仍在）且 池内涨≥跌（修复）",
                "混沌轮动": "以上判据均不满足：涨跌均衡、无主导形态",
                "insufficient_evidence": "上涨与下跌两页复盘原料均缺失",
            },
        },
        "money_style": {
            "type": "choice",
            "instructions": "根据形态面与资金锚点（大面/炸板计数、采集池涨跌比、主力净流入流出），今日赚钱效应属于哪种档位？",
            "criteria": {
                "接力为主": f"涨跌比≥{_R_RATIO_STRONG:g} 且 大面=0（无亏钱效应，接力有溢价）",
                "观望为主": f"大面≥{_R_BIGFACE_WATCH} 或 全市场跌停≥{_R_LIMITDOWN_RISK}（亏钱效应显著）",
                "低吸为主": "其余：不满足接力/观望判据（形态分化但亏钱效应未主导）",
                "insufficient_evidence": "上涨与下跌两页复盘原料均缺失",
            },
        },
        "plan_bias": {
            "type": "choice",
            "instructions": "基于今日复盘归层（recap_shape 语义），隔日交易计划倾向哪个档位？只给倾向档位，不给个股与点位。",
            "criteria": {
                "进攻": "recap_shape=强势延续",
                "均衡": "recap_shape=分歧加剧/冰点修复/混沌轮动",
                "防守": "recap_shape=退潮防守",
                "insufficient_evidence": "recap_shape=insufficient_evidence",
            },
        },
        "focus_direction": {
            "type": "choice",
            "instructions": "隔日主攻方向：从今日上涨复盘正向板块锚点（state.summary.rise.topBoards）中选择，或空仓观望。只选方向，不给个股。",
            "criteria": {c: f"state.summary.rise.topBoards 板块锚点：{c}" for c in boards[:8]}
            | {FOCUS_FALLBACK: "上涨名单空/板块锚点缺失/无明确方向"},
        },
        "risk_flag": {
            "type": "choice",
            "instructions": "隔日风险档位：根据大面计数与全市场跌停家数判断。",
            "criteria": {
                "高风险": f"大面≥{_R_BIGFACE_WATCH} 或 全市场跌停≥{_R_LIMITDOWN_RISK}",
                "低风险": f"大面=0 且 跌停=0 且 涨跌比≥{_R_RATIO_STRONG:g}",
                "中风险": "其余",
                "insufficient_evidence": "上涨与下跌两页复盘原料均缺失",
            },
        },
    }


def build_state(date: str, facts: dict[str, Any], emotion: dict[str, Any],
                kpl_wrap: dict[str, Any] | None = None,
                relay_judgment: dict[str, Any] | None = None) -> dict[str, Any]:
    """state 包：summary（两页事实）+ emotion 锚点 + KPL 15:00 盘播报 + 连板情绪判定（state v2）。

    - degradedSources 只在顶层保留一份（summary 内剔除，不重复投喂，开火前文本清理 2026-10-31）；
    - kpl_wrap / relay_judgment 由 operations 层装载（IO 边界），缺料带 ok:false+reason（fail-visible）；
      语料增补登记设计文档 §9（2026-10-31 用户裁决：每日一句不补）。"""
    state = {
        "date": date,
        "summary": {k: v for k, v in facts.items() if k != "degradedSources"},
        "emotion": {
            "eod": emotion.get("eod"),
            "prevEod": emotion.get("prevEod"),
            "eod20dPercentile": emotion.get("eod20dPercentile"),
            "bandTag": emotion.get("bandTag"),
            "bandLabel": emotion.get("bandLabel"),
            "dailyLineSentence": emotion.get("dailyLineSentence"),
            "dailyShape": emotion.get("dailyShape"),
        },
        "degradedSources": facts.get("degradedSources") or [],
    }
    # 语料 v2 增补（2026-10-31 用户裁决）：KPL 直播 15:00 大盘综述 + 连板情绪判定结果。
    # 缺料 ok:false 原样透传（fail-visible），operations 层已同步登记 degraded。
    state["kplWrap"] = kpl_wrap if isinstance(kpl_wrap, dict) else {"ok": False, "reason": "kpl_wrap_unavailable"}
    state["relayJudgment"] = relay_judgment if isinstance(relay_judgment, dict) \
        else {"ok": False, "reason": "relay_judgment_unavailable"}
    return state


# ---------------------------------------------------------------- 成文模板（版本化）

def _slot(value: Any, unit: str = "") -> str:
    if value is None:
        return "暂缺"
    if isinstance(value, float) and value.is_integer():
        value = int(value)          # 计数类槽位 4.0 → 4（浮点整值不带小数尾巴）
    return f"{value}{unit}"


def _yi(value: Any) -> str:
    """金额（元）→ 亿元槽；缺→暂缺。"""
    n = _num(value)
    return f"{round(n / 1e8, 2)}亿" if n is not None else "暂缺"


def compose_recap_text(date: str, facts: dict[str, Any], emotion: dict[str, Any],
                       slots: dict[str, Any]) -> dict[str, str]:
    """模板 v1 成文（纯函数）。slots = 各题最终档位（jev 或机械判兜底后的值）。

    槽缺失显式「暂缺」，不伪造 0（fail-visible）；措辞改动必须升 RECAP_TEMPLATE_VERSION。
    """
    r, d = facts["rise"], facts["dieban"]
    rs = r["shapes"]
    eod20 = emotion.get("eod20dPercentile")
    conclusion = (
        f"【复盘结论】{slots.get('recap_shape') or RECAP_UNKNOWN}（{slots.get('money_style') or RECAP_UNKNOWN}）。"
        f"全市场上涨{_slot(r['riseCount'], '家')}、跌停{_slot(d['limitDownCount'], '家')}，"
        f"采集池涨跌比{_slot(r['ratio'])}；形态面：大面{rs['big_face']}·炸板{rs['zha_ban']}"
        f"·冲高回落{rs['fade']}·强势{rs['high_close']}·尾盘跳水{rs['tail_dive']}。"
        f"情绪分{_slot(emotion.get('eod'))}（{_slot(emotion.get('bandLabel'))}，"
        f"20日分位{_slot(eod20, '%')}）。"
    )
    ds = d["shapes"]
    plan = (
        f"【隔日交易计划】倾向{slots.get('plan_bias') or RECAP_UNKNOWN}，"
        f"主攻方向{slots.get('focus_direction') or RECAP_UNKNOWN}。"
        f"风险档：{slots.get('risk_flag') or RECAP_UNKNOWN}"
        f"（锚点：大面{rs['big_face']}、跌停{_slot(d['limitDownCount'])}、"
        f"连跌高度{_slot(d['maxStreak'])}）。观察参考，非交易信号，不构成投资建议。"
    )
    return {"conclusion": conclusion, "plan": plan, "narrative": _narrative(facts, emotion, slots)}


# 短叙事文段库 v1（每档 recap_shape 一段预写短文；{槽位}插值；改措辞升 NARRATIVE_LIBRARY_VERSION）
NARRATIVE_LIBRARY_VERSION = 1
_NARRATIVE_TPL = {
    "强势延续": "今日多头结构完好：采集池涨跌比{ratio}，大面零星（{bigFace}家）而强势收高位{highClose}家，连涨梯队最高{maxStreakRise}板。资金接力意愿在，隔日顺着{focus}方向做强势股的持续性，忌追泛泛跟风。",
    "分歧加剧": "今日涨跌两旺（池内涨{poolUp}/跌{poolDown}），大面{bigFace}家与强势{highClose}家并存，市场在主线内部剧烈换手。分歧日的纪律是不抢分歧半山腰，等隔日方向再表态。",
    "退潮防守": "今日亏钱效应主导：大面{bigFace}家压过强势{highClose}家，全市场跌停{limitDown}家，主力净流出{netOut}。退潮期现金为王，隔日以防守为主，不抄下跌中继。",
    "冰点修复": "连跌梯队仍在（最高{maxStreakFall}连跌）但上涨家数已回升（涨{poolUp}/跌{poolDown}），冰点后有修复迹象。修复初日先看量能确认，隔日轻仓试错强修复方向{focus}。",
    "混沌轮动": "今日涨跌均衡、无主导形态（大面{bigFace}家、炸板{zhaBan}家、强势{highClose}家），板块锚点分散。混沌期降低频率，隔日以{focus}为观察样本，不重仓表态。",
    "insufficient_evidence": "本日复盘原料不足，两页名单存在缺口，机械归层不可用；成文仅保留可数事实，隔日计划因缺锚未给出档位判断。",
}


def _narrative(facts: dict[str, Any], emotion: dict[str, Any], slots: dict[str, Any]) -> str:
    """短叙事 = NARRATIVE_LIBRARY 选段 + 可数事实插值（零 jev 措辞，§1 实现裁决）。"""
    shape = slots.get("recap_shape")
    tpl = _NARRATIVE_TPL.get(shape)
    if tpl is None:  # 未判定/未知档位：不硬编故事，落不足段
        tpl = _NARRATIVE_TPL["insufficient_evidence"]
    r, d = facts["rise"], facts["dieban"]
    rs = r["shapes"]
    return tpl.format(
        ratio=_slot(r["ratio"]), bigFace=rs["big_face"], zhaBan=rs["zha_ban"],
        highClose=rs["high_close"], maxStreakRise=_slot(r["maxStreak"]),
        maxStreakFall=_slot(d["maxStreak"]), poolUp=_slot(r["poolUp"]),
        poolDown=_slot(r["poolDown"]), limitDown=_slot(d["limitDownCount"]),
        netOut=_yi(d["netOutflowTotal"]), focus=slots.get("focus_direction") or RECAP_UNKNOWN,
    )
