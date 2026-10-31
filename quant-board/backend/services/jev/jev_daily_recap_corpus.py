# -*- coding: utf-8 -*-
"""复盘日报语料拼装层（jev daily recap，题目集 v2 / 模板 v3 / 语料 state v3）。

设计/预登记：quant-board/docs/hotlist-jev/jev-daily-recap-design.md（§9/§10/§11）。
- 生态位（2026-10-31 用户裁决）：环境判断已由 EOD 情绪链/连板情绪链/题材龙头链回答，
  日报**只做链间收敛成隔日计划**——4 道计划题（基调+仓位/打法/回避/验证信号），
  主攻方向由题材龙头方向块机械派生（不问 AI），短叙事段删除（复述数字无参考含义）；
- 语料包 = state v3（两页事实 + emotion + KPL 综述 + 连板情绪判定 + EOD 结构化判定
  + 题材方向块 + 量能 + 晋级率，缺料 ok:false 透传）+ 4 道 choice 题（判据**只引用
  state 已有字段**，与机械判同数）+ 单 call 输出合同；
- 本模块纯函数零 IO 零外呼：state 各块由 operations 层装载（monkeypatch 边界）。

纪律：pytest 一律 mock，禁真调用（硬红线 §1.2#7）；缺料不伪造（fail-visible，§4.0）。
"""
from __future__ import annotations

from typing import Any

# 版本戳（换代必须登记 jev-daily-recap-design.md；跨代不可比）
RECAP_TEMPLATE_VERSION = 3          # v3：成文只剩结论/计划两段，短叙事删除
QUESTION_SET_VERSION_RECAP = "v2"   # v2：4 道计划题（环境题全删，判据直引语料字段）

# 题目 choices 预登记（判据与机械判同数；改一处须同步文档 §11）
PLAN_BIAS_CHOICES = ("进攻", "均衡", "防守", "空仓观望", "insufficient_evidence")
PLAY_STYLE_CHOICES = ("龙头核心", "低位首板", "分歧低吸", "只看不追", "insufficient_evidence")
AVOID_FOCUS_CHOICES = ("高位断板承接", "追高打板", "弱势板块补跌", "无明确回避",
                       "insufficient_evidence")
KEY_WATCH_CHOICES = ("晋级率修复", "炸板率回落", "量能维持", "高位股承接",
                     "insufficient_evidence")

RECAP_UNKNOWN = "未判定"

# 机械判阈值（与 build_questions 的 criteria 文案同数；改一处须同步文档并登记设计文档）
_PLAN_LIMITDOWN_EMPTY = 50    # 空仓观望：跌停家数线
_PLAY_LEADER_MIN = 6.0        # 龙头核心：龙头强度分（0-10 原始分）线
_AVOID_BIGFACE = 3            # 高位断板承接：大面家数线
_AVOID_ZHABAN = 20            # 追高打板：炸板家数线
_AVOID_ENDING_BOARDS = 2      # 弱势板块补跌：衰竭板块数线
_WATCH_PROMOTION = 30.0       # 晋级率修复：今日晋级率%（低于则隔日验证修复）
_IGNITING_DEPTHS = ("igniting", "fermenting")

_STRONG_MOMENTUM = ("accelerating", "holding")
_BROKEN_LADDER = ("inverted", "sparse")


# ---------------------------------------------------------------- 机械判视图（state → 扁平锚点）

def _mech_view(state: dict[str, Any]) -> dict[str, Any]:
    """state 包 → 机械判扁平视图（None=缺料不伪造；RULES 与 criteria 均只消费本视图字段）。"""
    summary = (state or {}).get("summary") or {}
    r = summary.get("rise") or {}
    d = summary.get("dieban") or {}
    shapes = r.get("shapes") or {}
    relay = (state or {}).get("relayJudgment") or {}
    answers = relay.get("answers") or {}
    eod = (state or {}).get("eodJudge") or {}
    boards = ((state or {}).get("themeBoards") or {}).get("boards") or []
    amount = (state or {}).get("marketAmount") or {}
    promo = (state or {}).get("promotion") or {}
    return {
        "no_material": bool((r.get("noData")) and (d.get("noData"))),
        "limit_down": d.get("limitDownCount"),
        "big_face": shapes.get("big_face"),
        "zha_ban": shapes.get("zha_ban"),
        "high_close": shapes.get("high_close"),
        # 连板情绪链判定（v7.1 档位 token 原值）
        "money_effect": answers.get("money_effect"),
        "relay_phase": answers.get("relay_phase"),
        "relay_momentum": answers.get("relay_momentum"),
        "ladder_health": answers.get("ladder_health"),
        "leader_strength": relay.get("leaderStrengthScore"),
        # EOD 结构化判定
        "risk_level": eod.get("riskLevel"),
        # 题材方向块
        "igniting_strong": any(b.get("continuation") == "strong_extend"
                               and b.get("depth") in _IGNITING_DEPTHS for b in boards),
        "ending_boards": sum(1 for b in boards if b.get("continuation") == "ending"),
        "attack_boards": [str(b.get("board")) for b in boards
                          if b.get("continuation") == "strong_extend" and b.get("board")],
        # 量能 / 晋级率
        "change1d": amount.get("change1d"),
        "promotion_rate": promo.get("rate"),
    }


def derive_focus_direction(state: dict[str, Any]) -> str:
    """主攻方向 = 题材龙头方向块机械派生（strong_extend 板块；空 → 空仓观望）。

    2026-10-31 用户裁决：方向问题删出题集——题材龙头/板块龙头链已给出带证据的方向，
    AI 再选一遍是用粗证据覆盖细证据。
    """
    attack = _mech_view(state)["attack_boards"]
    return attack[0] if attack else "空仓观望"


# ---------------------------------------------------------------- 机械判（与 criteria 同数）

def rule_plan_bias(v: dict[str, Any]) -> str:
    """隔日基调+仓位档机械判（判据与 build_questions.plan_bias 同数）。"""
    if v["no_material"] or v["money_effect"] is None:
        return "insufficient_evidence"
    if v["money_effect"] == "losing":
        if v["ladder_health"] in _BROKEN_LADDER or (v["limit_down"] is not None
                                                    and v["limit_down"] >= _PLAN_LIMITDOWN_EMPTY):
            return "空仓观望"
        return "防守"
    if v["money_effect"] == "strong" and v["relay_momentum"] in _STRONG_MOMENTUM \
            and v["risk_level"] != "高":
        return "进攻"
    return "均衡"


def rule_play_style(v: dict[str, Any]) -> str:
    """参与打法机械判（判据与 build_questions.play_style 同数）。"""
    if v["no_material"] or v["money_effect"] is None:
        return "insufficient_evidence"
    if v["ladder_health"] == "pyramid" and v["money_effect"] in ("strong", "neutral") \
            and v["leader_strength"] is not None and v["leader_strength"] >= _PLAY_LEADER_MIN:
        return "龙头核心"
    if v["relay_phase"] == "divergence" and v["money_effect"] == "neutral":
        return "分歧低吸"
    if v["igniting_strong"] and v["money_effect"] != "losing":
        return "低位首板"
    return "只看不追"


def rule_avoid_focus(v: dict[str, Any]) -> str:
    """回避重点机械判（判据与 build_questions.avoid_focus 同数；优先级从上到下）。"""
    if v["no_material"]:
        return "insufficient_evidence"
    if (v["big_face"] is not None and v["big_face"] >= _AVOID_BIGFACE) \
            or (v["limit_down"] is not None and v["limit_down"] >= _PLAN_LIMITDOWN_EMPTY):
        return "高位断板承接"
    if (v["zha_ban"] is not None and v["zha_ban"] >= _AVOID_ZHABAN) \
            or (v["zha_ban"] is not None and v["high_close"] is not None
                and v["zha_ban"] > v["high_close"]):
        return "追高打板"
    if v["ending_boards"] >= _AVOID_ENDING_BOARDS:
        return "弱势板块补跌"
    return "无明确回避"


def rule_key_watch(v: dict[str, Any]) -> str:
    """隔日验证信号机械判（判据与 build_questions.key_watch 同数；今日数据缺口项优先）。"""
    if v["no_material"]:
        return "insufficient_evidence"
    if v["promotion_rate"] is not None and v["promotion_rate"] < _WATCH_PROMOTION:
        return "晋级率修复"
    if v["zha_ban"] is not None and v["zha_ban"] >= _AVOID_ZHABAN:
        return "炸板率回落"
    if v["change1d"] is not None and v["change1d"] < 0:
        return "量能维持"
    return "高位股承接"


# 对外入口统一收 state 包（内部先扁平化为机械判视图）
RULES = {"plan_bias": lambda state: rule_plan_bias(_mech_view(state)),
         "play_style": lambda state: rule_play_style(_mech_view(state)),
         "avoid_focus": lambda state: rule_avoid_focus(_mech_view(state)),
         "key_watch": lambda state: rule_key_watch(_mech_view(state))}


# ---------------------------------------------------------------- 纯函数：事实压缩

def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _shape_counts(stocks: list[dict[str, Any]]) -> dict[str, int]:
    """stocks[].shape 形态计数（None=封板/缺料不计入；缺失保持缺失不伪造）。"""
    counts = {k: 0 for k in ("big_face", "zha_ban", "fade", "high_close", "tail_dive",
                             "up", "down", "flat")}
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
            "shapes": _shape_counts(rise_stocks),
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
            "shapes": _shape_counts(dieban_stocks),
        },
        "degradedSources": degraded,
    }


# ---------------------------------------------------------------- 题料包 / state

def build_questions(state: dict[str, Any]) -> dict[str, Any]:
    """4 道计划题（题目集 v2，单 call）。判据只引用 state 已有字段（与 RULES 机械判同数）。

    2026-10-31 用户裁决：环境判断题（复盘归层/赚钱效应档位）全删——EOD 情绪链与连板
    情绪链已回答；主攻方向由题材龙头方向块机械派生，不再设题。
    """
    v = _mech_view(state)
    return {
        "plan_bias": {
            "type": "choice",
            "instructions": (
                "综合 EOD 情绪结构化判定（state.eodJudge：score/stage/riskLevel）、连板情绪判定"
                "（state.relayJudgment.answers：money_effect/relay_momentum/ladder_health）、"
                "全市场跌停家数（state.summary.dieban.limitDownCount），隔日交易计划总基调与仓位档？"
                "只给档位，不给个股与点位。"
            ),
            "criteria": {
                "进攻": "money_effect=strong 且 relay_momentum=accelerating/holding 且 riskLevel≠高（可上仓位）",
                "均衡": "money_effect=neutral；或 strong 但 riskLevel=高（半仓防守性参与）",
                "防守": "money_effect=losing 且 ladder_health=pyramid 且 跌停<50（轻仓试错）",
                "空仓观望": "money_effect=losing 且（ladder_health=inverted/sparse 或 跌停≥50）",
                "insufficient_evidence": "EOD/连板情绪与两页复盘原料均缺失",
            },
        },
        "play_style": {
            "type": "choice",
            "instructions": (
                "隔日参与打法：结合梯队健康（ladder_health）、赚钱效应（money_effect）、"
                "龙头强度分（state.relayJudgment.leaderStrengthScore，0-10）、题材阶段"
                "（state.themeBoards.boards 的 continuation/depth）选择。只选打法，不给个股。"
            ),
            "criteria": {
                "龙头核心": "ladder_health=pyramid 且 money_effect=strong/neutral 且 leaderStrengthScore≥6",
                "低位首板": "题材点火（continuation=strong_extend 且 depth=igniting/fermenting）且 money_effect≠losing",
                "分歧低吸": "relay_phase=divergence 且 money_effect=neutral",
                "只看不追": "以上不满足（亏钱效应主导/题材衰竭）",
                "insufficient_evidence": "连板情绪与题材方向块原料均缺失",
            },
        },
        "avoid_focus": {
            "type": "choice",
            "instructions": (
                "隔日回避重点：根据形态计数（大面/炸板/强势）、全市场跌停家数、衰竭板块名单"
                "（state.themeBoards.boards 中 continuation=ending）。只选最优先一项。"
            ),
            "criteria": {
                "高位断板承接": "大面≥3 或 全市场跌停≥50",
                "追高打板": "炸板≥20 或 炸板>强势",
                "弱势板块补跌": "continuation=ending 的板块≥2",
                "无明确回避": "以上均不满足",
                "insufficient_evidence": "两页复盘与题材方向块原料均缺失",
            },
        },
        "key_watch": {
            "type": "choice",
            "instructions": (
                "隔日最该验证的信号（今日数据缺口项）：晋级率（state.promotion.rate）、"
                "炸板计数、量能变化（state.marketAmount.change1d）、高位股表现。只选一项。"
            ),
            "criteria": {
                "晋级率修复": "promotion.rate<30（今日晋级率已显著走低）",
                "炸板率回落": "炸板≥20（且晋级率未显著走低）",
                "量能维持": "marketAmount.change1d<0（已缩量，验证能否维持）",
                "高位股承接": "以上不满足，但大面≥3 或 跌停≥30",
                "insufficient_evidence": "晋级率/量能锚点缺失",
            },
        },
    }


def build_state(date: str, facts: dict[str, Any], emotion: dict[str, Any],
                kpl_wrap: dict[str, Any] | None = None,
                relay_judgment: dict[str, Any] | None = None,
                eod_judge: dict[str, Any] | None = None,
                theme_boards: dict[str, Any] | None = None,
                market_amount: dict[str, Any] | None = None,
                promotion: dict[str, Any] | None = None) -> dict[str, Any]:
    """state 包（v3）：summary + emotion + KPL 综述 + 连板情绪判定 + EOD 结构化判定
    + 题材方向块 + 量能 + 晋级率。degradedSources 只在顶层一份（不重复投喂）。
    各块缺料 ok:false 透传（operations 层同步登记 degraded；fail-visible）。"""
    def _blk(value: dict[str, Any] | None, reason: str) -> dict[str, Any]:
        return value if isinstance(value, dict) else {"ok": False, "reason": reason}

    return {
        "date": date,
        "summary": {k: v for k, v in facts.items() if k != "degradedSources"},
        "emotion": {
            "eod": emotion.get("eod"),
            "prevEod": emotion.get("prevEod"),
            "eod20dPercentile": emotion.get("eod20dPercentile"),
            "bandTag": emotion.get("bandTag"),
            "bandLabel": emotion.get("bandLabel"),
        },
        "kplWrap": _blk(kpl_wrap, "kpl_wrap_unavailable"),
        "relayJudgment": _blk(relay_judgment, "relay_judgment_unavailable"),
        "eodJudge": _blk(eod_judge, "eod_judge_unavailable"),
        "themeBoards": _blk(theme_boards, "theme_boards_unavailable"),
        "marketAmount": _blk(market_amount, "market_amount_unavailable"),
        "promotion": _blk(promotion, "promotion_unavailable"),
        "degradedSources": facts.get("degradedSources") or [],
    }


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


def compose_recap_text(date: str, state: dict[str, Any], slots: dict[str, Any]) -> dict[str, str]:
    """模板 v3 成文（纯函数）：只余复盘结论 + 隔日交易计划两段（短叙事已删，用户裁决）。

    slots = 各题最终档位（jev 或机械判兜底后的值）；主攻方向由 state 机械派生（derive_focus_direction）。
    槽缺失显式「暂缺/未判定」，不伪造 0（fail-visible）；措辞改动必须升 RECAP_TEMPLATE_VERSION。
    """
    summary = state.get("summary") or {}
    r = summary.get("rise") or {}
    d = summary.get("dieban") or {}
    rs = r.get("shapes") or {}
    ds = d.get("shapes") or {}
    emotion = state.get("emotion") or {}
    v = _mech_view(state)

    conclusion = (
        f"【复盘结论】全市场上涨{_slot(r.get('riseCount'), '家')}、"
        f"跌停{_slot(d.get('limitDownCount'), '家')}，"
        f"采集池涨跌比{_slot(r.get('ratio'))}；"
        f"形态面：大面{v['big_face'] if v['big_face'] is not None else '暂缺'}"
        f"·炸板{v['zha_ban'] if v['zha_ban'] is not None else '暂缺'}"
        f"·冲高回落{ds.get('fade', 0) if isinstance(ds.get('fade'), int) else '暂缺'}"
        f"·强势{v['high_close'] if v['high_close'] is not None else '暂缺'}"
        f"·尾盘跳水{ds.get('tail_dive', 0) if isinstance(ds.get('tail_dive'), int) else '暂缺'}。"
        f"情绪分{_slot(emotion.get('eod'))}（{_slot(emotion.get('bandLabel'))}，"
        f"20日分位{_slot(emotion.get('eod20dPercentile'), '%')}）；"
        f"EOD判定：{_slot((state.get('eodJudge') or {}).get('stage'))}"
        f"·风险级{_slot((state.get('eodJudge') or {}).get('riskLevel'))}；"
        f"晋级率{_slot(v['promotion_rate'], '%')}（{_slot((state.get('promotion') or {}).get('promotedCount'))}"
        f"/{_slot((state.get('promotion') or {}).get('baseCount'))}）；"
        f"量能较昨日{_slot(v['change1d'], '%')}。"
    )
    focus = derive_focus_direction(state)
    plan = (
        f"【隔日交易计划】倾向{slots.get('plan_bias') or RECAP_UNKNOWN}，"
        f"参与方式{slots.get('play_style') or RECAP_UNKNOWN}，"
        f"进攻方向{focus}，"
        f"回避{slots.get('avoid_focus') or RECAP_UNKNOWN}，"
        f"隔日验证{slots.get('key_watch') or RECAP_UNKNOWN}。"
        f"锚点：大面{v['big_face'] if v['big_face'] is not None else '暂缺'}、"
        f"跌停{_slot(d.get('limitDownCount'))}、"
        f"梯队{_slot((state.get('relayJudgment') or {}).get('answers', {}).get('ladder_health') or RECAP_UNKNOWN)}。"
        f"观察参考，非交易信号，不构成投资建议。"
    )
    return {"conclusion": conclusion, "plan": plan}
