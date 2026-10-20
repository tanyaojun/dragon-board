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
# 题集/口径任何一字变更必须换代（跨代不可比）。v1 = 2026-10-20 定版（龙头隔日连板两题）。
QUESTION_SET_VERSION_THEME_LEADER = "v2"
# 原料代际：板块结构（触板−炸板二分、真连板）+ 题材语料（产业树催化 + 投资日历）。
AMMO_VERSION_THEME_LEADER = "2026-10-20b"


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
    """
    return sorted(stocks, key=lambda s: (-(s.get("streak") or 0), _time_key(s.get("time"))))


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
    "leader_nextday_continue": {
        "type": "choice",
        "instructions": "仅依据所给证据（板块结构、封板质量、题材证据与前瞻事件、同桶历史基准率），"
                        "判断该板块龙头在**次一交易日**继续封板（涨停）的概率落在哪一档？"
                        "只判概率档位，不预测价格、不给出买卖建议。四条硬规则："
                        "①同桶历史基准率是必须先超的基准——若你的理由仅为「连板高/封板早/板块家数多」"
                        "这类与基准率同源的结构特征，请选与基准率同一档，不得凭感觉上调；"
                        "②题材证据有明确日期与新鲜度时，其权重高于结构特征；"
                        "③关键证据缺失（语料未采集、板块未映射、板块结构不可考）必须判 insufficient，"
                        "不得用结构特征硬填空档；"
                        "④此规则由程序强制：当叙事「题材证据」行标注未映射/未采集/无正文且无事件时，"
                        "无论你给出何档，落库一律覆盖为 insufficient（原答另存备查）——"
                        "所以此时请直接选 insufficient，不要用结构特征凑档位。",
        "criteria": {
            "high_ge65": "高概率 ≥65%：结构位置强（连板高度领先 + 封板早 + 板块家数多）"
                         "且题材有当日/近两日新催化，或未来 1-2 日有既定事件",
            "mid_45_65": "中等 45%-65%：结构与题材一强一弱，或与同桶历史基准率同档",
            "low_25_45": "偏低 25%-45%：结构位置一般（封板偏晚/板块家数少/跟风薄），"
                         "或题材为老催化且近期无新增",
            "verylow_lt25": "很低 <25%：结构示警（板块家数少 + 封板晚 + 无梯队）"
                            "且题材无催化或已明显退潮",
            "insufficient": "证据不足：关键证据缺失（语料未采集、板块未映射、板块结构不可考），"
                            "不强行归类",
        },
    },
    "catalyst_stage": {
        "type": "choice",
        "instructions": "以所给「题材证据」为准，判断该板块当前催化处于哪个阶段？"
                        "只依据所给证据打标，不预测后市。正文更新日期与事件日期不可考时判 insufficient。",
        "criteria": {
            "new_today": "今日新增催化：板块催化正文更新日期=当日，或前瞻事件在今日/次日落地",
            "ongoing": "既有催化持续发酵：催化正文更新在近 3-10 个交易日，"
                       "或未来 3 日内有既定事件排队",
            "stale": "催化陈旧：板块催化正文更新距今 >10 个交易日且未来 3 日无既定事件",
            "none": "无催化：该板块在产业树无催化正文且无相关既定事件（纯资金/情绪驱动）",
            "insufficient": "证据不足：语料未采集或板块未映射，不强行归类",
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


# 确定性「证据缺失」门（v2，用户 2026-10-20 裁决；纯函数，无 IO）。
# 触发只用**结构化**的缺失标志（`theme_event_digest` 返回的 `evidenceMissing`），不从叙事文字反推。
GATE_REASON_LABELS = {
    "corpus_not_collected": "题材语料未采集",
    "board_unmapped": "板块未映射（韭研产业树无同名/包含节点，不代表无催化）",
    "no_content_no_event": "已映射但正文为空且未来无既定事件",
}


def apply_evidence_gate(answers: Any, evidence: Any) -> tuple[Any, dict]:
    """证据缺失 → 强制 `leader_nextday_continue` 判 insufficient（原答原样存 gate 元数据）。

    v1 单日 pilot 实测缺口：未映射板块的 `catalyst_stage` 判了 insufficient，但同一份证据下
    概率题仍给 0.34/0.34/0.26/0.18——规则③只写在题面，靠模型自觉。v2 改为代码强制。
    """
    ev = evidence if isinstance(evidence, dict) else {}
    gate: dict[str, Any] = {"applied": False, "reason": None}
    if not isinstance(answers, dict) or not ev.get("evidenceMissing"):
        return answers, gate
    reason = str(ev.get("evidenceMissingReason") or "unknown")
    key = "leader_nextday_continue"
    prev = answers.get(key) if isinstance(answers.get(key), dict) else {}
    gate.update({"applied": True, "reason": reason,
                 "label": GATE_REASON_LABELS.get(reason, reason),
                 "modelChoice": prev.get("choice"),
                 "modelProbabilities": prev.get("probabilities")})
    out = dict(answers)
    out[key] = {"type": "choice", "choice": "insufficient", "confidence": 1.0,
                "probabilities": {"insufficient": 1.0}, "gateReason": reason}
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

    回退顺序：组合桶 → 连板高度桶 → 板块家数桶 → 总体；任一档样本 < min_combo_n 都明示样本量，
    让模型知道这条基准率的可信度（不隐藏小样本）。
    """
    combo = combo_rates(rows, min_combo_n).get(combo_key(row))
    parts: list[str] = []
    if combo:
        parts.append(f"同桶[{combo_key(row)}] 历史次日连板率 {combo['rate']:.1%}（{combo['n']} 样本）")
    else:
        parts.append(f"同桶[{combo_key(row)}] 样本不足（<{min_combo_n}），不出率")
    sb = group_rates(rows, lambda r: streak_bucket(r.get("streak"))).get(streak_bucket(row.get("streak")))
    if sb:
        parts.append(f"按连板高度[{streak_bucket(row.get('streak'))}] {sb['rate']:.1%}（{sb['n']} 样本）")
    cb = group_rates(rows, lambda r: board_count_bucket(r.get("boardN"))).get(
        board_count_bucket(row.get("boardN")))
    if cb:
        parts.append(f"按板块家数[{board_count_bucket(row.get('boardN'))}] {cb['rate']:.1%}（{cb['n']} 样本）")
    cont, n, rate = _rate(rows)
    if n:
        parts.append(f"总体 {rate:.1%}（{n} 样本）")
    return "结构基线（口径=触板−THS炸板二分 + 真连板；历史窗口内板块龙头样本）：" + "；".join(parts)


def structure_line(*, board: str, board_n: int, leader: dict, followers_ge_ladder: int,
                   prev_board_n: int | None, prev_peers: int | None) -> str:
    """该板块当日结构事实行（不含预测）。"""
    time_txt = str(leader.get("time") or "时间不可考")
    streak = leader.get("streak")
    streak_txt = f"{streak} 连板" if streak else "连板高度不可算"
    prev_txt = ("昨日同板块不可考" if prev_peers is None
                else f"昨日该板块封板 {prev_board_n if prev_board_n is not None else '?'} 只，"
                     f"其中 {prev_peers} 只今日仍封板")
    return (f"板块「{board}」今日封板 {board_n} 家；龙头 {leader.get('name')}（{leader.get('code')}）"
            f"{streak_txt}，首封 {time_txt}；板块内真连板≥{max(1, (streak or 1) - 1)} 的跟风 "
            f"{followers_ge_ladder} 家；{prev_txt}")


def build_leader_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, corpus_line: str, leader_name: str,
                           leader_code: str) -> str:
    """投喂给 jev 的完整叙事（顺序固定，便于逐字复现与回归比对）。

    evidence_block 由 `theme_event_digest.build_theme_evidence_block` 生成（fail-visible 文本）；
    corpus_line 说明语料时点与新鲜度；两者都必须原样嵌入，不得在 runner 里二次改写。
    """
    return "\n".join([
        f"{date} 交易日 · {market_line}",
        f"待判龙头：{leader_name}（{leader_code}）",
        structure,
        baseline,
        corpus_line,
        evidence_block,
    ])