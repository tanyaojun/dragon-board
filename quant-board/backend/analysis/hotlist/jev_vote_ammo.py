# -*- coding: utf-8 -*-
"""行情列表五维信号 jev 复核双题集弹药纯函数层（vote_confirm + lifecycle_recheck）。

预登记（判据冻结件唯一来源）：docs/hotlist-jev/jev-vote-confirm-lifecycle-recheck-preregistration.md
（2026-10-12 用户五裁决后落方案，判据文本经用户逐字确认）。

归档边界（对齐 jev_driver_ammo/jev_relay_ammo 模式）：题目常量、叙事组装、预检 riskFlag、
对照锚映射、确定性抽样、EOD 补齐读法全部纯函数（零 IO、可单测）；Mongo 取数与 jev 调用
编排留 operations/jev_vote_confirm.py runner。本文件不得新增任何 IO。

红线：
- 判据任何一字变更=改门，须重走预登记+用户点头（判据冻结件逐字=QUESTIONS_* 代码文本，
  开火后只能文档向代码回写）；
- riskFlag 为 runner 侧预检字段（2026-10-12 用户裁决 1：数据性不足不进人口不调用，
  判读性含糊由 probabilities 平铺+confidence 低值如实表达）；
- EOD 补齐读法只补行情原始字段，不拼引擎档位（同帧一致性边界，预登记 §四）。
"""
from __future__ import annotations

from typing import Any

# ── 版本戳（预登记 §五：独立戳，cycle v5 旧债不重犯）──
QUESTION_SET_VERSION_VOTE_CONFIRM = "v1"
QUESTION_SET_VERSION_LIFECYCLE_RECHECK = "v1"
# 原料代际戳（本链自有：snapshot_analysis 五维载荷 + EOD 补齐读法口径；与打标链 AMMO_VERSION 无关）。
# b 代（2026-10-12）：原料跨日化——叙事增「近10日排名轨迹」行（同 slot 历史帧定格），
# 判据「多日/峰值」引用获得可数锚（铁律 3/4 补原料方向修复，判据文本零改动 hash 不变）；
# a 代（2026-10-12a）= 无跨日行旧料（9-10 月全量 4145 例留档不回写，跨代对照按戳分段）。
VOTE_AMMO_VERSION = "2026-10-12b"

# ── 题集 A：vote_direction（方向投票 jev 二次确认，三态纯净，无逃生口——裁决 1）──
QUESTIONS_VOTE_CONFIRM: dict[str, dict] = {
    "vote_direction": {
        "type": "choice",
        "instructions": ("以下是行情列表某股票当日收盘槽的方向投票读数：四维信号（共振/趋势/热度/量价）"
                         "各自的档位、方向、分数与理由，以及原始行情证据行（涨幅/量比/主力净额/换手/"
                         "当日排名轨迹）与环境门注记。请判断：该股当日方向投票整体应读作 buy、sell 还是 hold？"
                         "判定以「给出明确方向的维数与档位强度对比」为主锚（buy 维与 sell 维各几票、"
                         "最高档位在哪侧），并用原始证据行校验方向一致性。特别注意："
                         "①档位 unknown 或数据不足的维不计票（叙事中已如实标注）；"
                         "②环境门只注记不参与投票；"
                         "③原始证据与投票读数明显矛盾时（如读数偏多但当日放量下跌、排名大幅回落，"
                         "或读数偏空但缩量上涨、排名大幅走高），以原始证据为准。"
                         "只依据所给信息判断，不预测后市。"),
        "criteria": {
            "buy": ("多方：≥2 个有向维（共振/趋势/量价）方向为 buy，且无 A/S 档 sell 反票；"
                    "热度档 A/B 正票可作佐证；原始证据行同向（涨幅为正、排名走高、主力未大幅流出）"),
            "hold": ("观望：有向维方向互相冲突（buy 与 sell 各 ≥1）且无更高档位一侧主导；"
                     "或全部有向维方向为 hold/unknown；原始证据行无方向（涨跌互现、排名横走）"),
            "sell": ("空方：≥2 个有向维方向为 sell；或任一维 A/S 档 sell 反票未被足够档位的 buy 票覆盖；"
                     "或量价档 E（出货硬风险）；原始证据行同向（放量下跌、排名大幅回落、主力净流出）"),
        },
    },
}

# ── 题集 B：lifecycle_stage_recheck（环境门阶段诊断复核，五段纯净，无逃生口——裁决 1）──
QUESTIONS_LIFECYCLE_RECHECK: dict[str, dict] = {
    "lifecycle_stage_recheck": {
        "type": "choice",
        "instructions": ("以下是行情列表某股票的生命周期判定原料：当日逐槽排名轨迹、生命周期度量"
                         "（排名速度/加速度/热区停留天数/近期最佳名次/距峰回撤/排名路径承诺度）、"
                         "动量与风险读数、前一交易日阶段，以及规则判读块（仅供复核）。请判断："
                         "该股当前处在自身行情生命周期的哪一段？判段以「排名轨迹的位置与走向」为主锚"
                         "（当日名次在窗口内的位置、全天走高还是走低、较昨日升降），并用动量与风险读数校准。"
                         "特别注意：①点火与扩散的分界在启动的新鲜度（排名刚自低位起升 vs 已在高位持续走强）；"
                         "②拥挤与反转的分界在高位是否出现回落证据（仍在高位区停留但未回落=拥挤，"
                         "已自峰回撤且动能转负=反转）；③降温是既无低位起升也无高位滞留/回落证据的默认态。"
                         "只依据所给信息判断，不预测后市。"),
        "criteria": {
            "ignition": ("点火：排名自低位明显起升（速度与加速度同为正，当前分位尚不高/近期最佳名次尚浅/"
                         "热区停留少）"),
            "expansion": ("扩散：排名在较高位置持续走强（速度为正且当前分位高，加速度或热区停留或最佳名次"
                          "佐证延续）"),
            "crowded": ("拥挤：排名停留高位区多日但已无上升动能（速度趋平或转负）且距峰回撤很小——高位滞留"),
            "reversal": ("反转：自近期峰值明显回撤（距峰回撤读数抬升）且动能转负（速度为负或加速大幅下行）"
                         "——高位回落"),
            "cooling": "降温：排名处于中低位且无起升证据，高位滞留与回落证据均不满足",
        },
    },
}

# ── 展示标签（叙事层中文）──
STAGE_ZH = {"ignition": "点火", "expansion": "扩散", "crowded": "拥挤",
            "reversal": "反转", "cooling": "降温"}
ACTION_ZH = {"allow": "放行", "caution": "谨慎", "veto": "一票否决", "exit_watch": "退出观察"}

# ── 对照锚（预登记 §一裁决 2 / §二·五：机械可算，冻结）──
SYNERGY_DIRECTION_MAP = {"S": "buy", "A": "buy", "B": "buy",
                         "C": "hold", "D": "sell", "E": "sell"}

VOTE_DIMS = ("resonance", "rankTrend", "crossSection", "volumePrice")

# EOD 补齐读法只补行情原始字段（预登记 §四：引擎档位不可跨帧拼接）
BACKFILL_FIELDS = ("change", "volumeRatio", "zlje", "turnoverRate", "amount")

# 档位序（抽样排序用）
TIER_RANK = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def _finite_num(value: Any) -> float | None:
    """有限数读出：None/非数/NaN → None（fail-visible，不伪造 0）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if v == v else None


def _fmt_num(v: Any, nd: int = 2) -> str:
    n = _finite_num(v)
    return "缺" if n is None else f"{n:.{nd}f}"


# ── 预检 riskFlag（裁决 1 落地：runner 侧，开火前冻结于预登记 §二·四/§三·四）──

def vote_risk_flag(dims: dict[str, Any], missing_evidence: list[str]) -> dict:
    """题集 A 预检。dims={维: signalTier}；有效档位维=非 unknown/None。

    data_insufficient（不调用）：有效维 <2；partial（仍调用）：有效维 2-3 或证据行有缺；
    ok：四维全可算且证据行齐。
    """
    valid = [d for d in VOTE_DIMS if dims.get(d) not in (None, "", "unknown")]
    unknown = [d for d in VOTE_DIMS if dims.get(d) in (None, "", "unknown")]
    if len(valid) < 2:
        return {"level": "data_insufficient",
                "reasons": [f"有效档位维={len(valid)}(<2)"] + [f"unknown维:{d}" for d in unknown]}
    reasons: list[str] = []
    if unknown:
        reasons.append("unknown维:" + ",".join(unknown))
    reasons.extend(missing_evidence or [])
    return {"level": "ok" if not reasons else "partial", "reasons": reasons}


def lifecycle_risk_flag(trajectory_slots: int, metrics_present: bool,
                        missing: list[str]) -> dict:
    """题集 B 预检。data_insufficient（不调用）：当日轨迹槽 <5 或度量块不可算；
    partial：前日阶段/个别度量缺失（missing 列明）；ok：轨迹+度量+前日阶段齐。"""
    if trajectory_slots < 5 or not metrics_present:
        return {"level": "data_insufficient",
                "reasons": [f"轨迹槽={trajectory_slots}(<5)" if trajectory_slots < 5 else "度量块不可算"]}
    return {"level": "ok" if not missing else "partial", "reasons": list(missing or [])}


# ── 对照锚映射 ──

def synergy_direction(synergy_tier: Any) -> str:
    """synergy 档位 → 引擎投票方向（S/A/B→buy、C→hold、D/E→sell）；档位缺失返回空串不计台账。"""
    return SYNERGY_DIRECTION_MAP.get(str(synergy_tier or ""), "")


# ── 确定性抽样（预登记 §六：排序规则冻结，防挑样）──

def vote_buy_sort_key(c: dict) -> tuple:
    """buy 侧（S/A/B）：最高档位数降序 → 共振分数降序 → 代码升序。"""
    high = sum(1 for d in VOTE_DIMS if (c.get("dims") or {}).get(d) in ("S", "A"))
    return (-high, -(_finite_num(c.get("resonanceScore")) or 0.0), str(c.get("code") or ""))


def vote_sell_sort_key(c: dict) -> tuple:
    """sell 侧（D）：量价 E 短路优先 → 代码升序。"""
    vp_e = 0 if (c.get("dims") or {}).get("volumePrice") == "E" else 1
    return (vp_e, str(c.get("code") or ""))


def sample_vote(buy: list[dict], sell: list[dict],
                cap_buy: int = 8, cap_sell: int = 4) -> list[dict]:
    return (sorted(buy, key=vote_buy_sort_key)[:cap_buy]
            + sorted(sell, key=vote_sell_sort_key)[:cap_sell])


def sample_lifecycle(cands: list[dict], cap_igex: int = 5, cap_total: int = 8) -> list[dict]:
    """点火/扩散优先全量至 ≤cap_igex（代码升序），剩余名额给拥挤/反转（stage+代码升序），
    再剩余给 cooling（include_cooling 全量覆盖时；代码升序）。"""
    igex = sorted((c for c in cands if c.get("stage") in ("ignition", "expansion")),
                  key=lambda c: str(c.get("code") or ""))
    late = sorted((c for c in cands if c.get("stage") in ("crowded", "reversal")),
                  key=lambda c: (str(c.get("stage") or ""), str(c.get("code") or "")))
    cooling = sorted((c for c in cands if c.get("stage") == "cooling"),
                     key=lambda c: str(c.get("code") or ""))
    n_igex = min(len(igex), cap_igex)
    n_late = min(len(late), max(0, cap_total - n_igex))
    return (igex[:n_igex] + late[:n_late]
            + cooling[: max(0, cap_total - n_igex - n_late)])


# ── EOD 补齐读法（裁决 3：daily 15:30 帧基准，行情字段缺失处从同日 half_hour 15:00 帧补）──

def backfill_quote_fields(base_row: dict, donor_row: dict | None,
                          sparse_fields: list[str],
                          fields: tuple[str, ...] = BACKFILL_FIELDS) -> tuple[dict, list[str], list[str]]:
    """返回 (补齐后新 dict, 已补字段, 两源皆缺字段)。

    sparse_fields=基准帧级稀疏字段（runner 按帧内 zero/None 占比 ≥0.9 判定，帧级事实而非逐行猜）；
    只补 fields 内行情原始字段，永不触碰引擎档位；两源皆缺保持缺失（fail-visible 不伪造）。
    """
    merged = dict(base_row or {})
    filled: list[str] = []
    still_missing: list[str] = []
    for f in fields:
        if f not in sparse_fields:
            continue
        donor_v = (donor_row or {}).get(f)
        if donor_v is None:
            still_missing.append(f)
            continue
        merged[f] = donor_v
        filled.append(f)
    return merged, filled, still_missing


# ── 叙事组装（纯函数；fail-visible 缺口如实注记，禁伪装）──

def _traj_line(points: list[dict]) -> str:
    """轨迹行：points=[{slot|date, rank, change}]（按时间升序）→ 单行；缺如实标「缺」。
    slot=日内槽位；date=跨日日期（跨日原料，铁律 3/4 补原料方向）。"""
    parts = []
    for t in points:
        label = t.get("slot") or t.get("date") or "?"
        rank = _finite_num(t.get("rank"))
        chg = _finite_num(t.get("change"))
        rank_s = "缺" if rank is None else str(int(rank)) if float(rank).is_integer() else f"{rank:.1f}"
        chg_s = "缺" if chg is None else f"{chg:+.2f}%"
        parts.append(f"{label}:{rank_s},{chg_s}")
    return " → ".join(parts)


# 技术面事件字面值 → 中文（macd.cross/maCross.cross：golden/dead/none）
_EVENT_ZH = {"golden": "金叉", "dead": "死叉", "none": "无"}


def _event_std(v: Any) -> str:
    return _EVENT_ZH.get(str(v or ""), "无")


# 量价 direction 取值域是 up/down/neutral（_vote 语义 up≡buy、down≡sell，ranking/volume_price.py）；
# 叙事展示归一到 buy/sell/hold，与判据用词对齐（非伪造，引擎投票语义原样映射）
_DIR_STD = {"buy": "buy", "up": "buy", "sell": "sell", "down": "sell",
            "hold": "hold", "neutral": "hold"}


def _dir_std(v: Any) -> str:
    return _DIR_STD.get(str(v or ""), "无")


def _tier_reasons(reasons: Any) -> str:
    return "；".join(str(r) for r in reasons) if isinstance(reasons, list) and reasons else "无"


def build_vote_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                         resonance: dict, trend: dict, cross_section: dict,
                         volume_price: dict, trend_events: dict, row: dict,
                         sparse_fields: list[str], trajectory: list[dict],
                         multi_day_trajectory: list[dict] | None = None, gate: dict,
                         synergy_tier: Any) -> str:
    """题集 A 叙事（预登记 §二·二五块）。全部行 fail-visible；引擎块明标「仅供复核」。
    量价方向按引擎投票语义归一（up→buy/down→sell/neutral→hold）；zlje 原始单位=元，叙事除 1e8 折亿。"""
    res_status = str(resonance.get("status") or "unknown")
    zl = _finite_num(row.get("zlje"))
    zl_s = "缺" if zl is None else f"{zl / 1e8:.3f}"
    lines = [
        f"{trading_date} 交易日 {slot} 槽 · {code} {name or ''}".rstrip(),
        "【四维方向投票读数】（规则产出，供复核）",
        (f"共振：档位 {resonance.get('signalTier') or 'unknown'} · 方向 {_dir_std(resonance.get('direction'))}"
         f" · 强度 {_fmt_num(resonance.get('score'), 0)} · 依据 {_tier_reasons(resonance.get('tierReasons'))}"
         + (f"（status={res_status}，证据不足如实标注）" if res_status != "ok" else "")),
        (f"趋势：档位 {trend.get('signalTier') or 'unknown'} · 方向 {_dir_std(trend.get('direction'))}"
         f" · 强度 {_fmt_num(trend.get('score'), 0)} · 依据 {_tier_reasons(trend.get('tierReasons'))}"
         f" · 技术面事件：MACD={_event_std(trend_events.get('macdCross'))}、MA={_event_std(trend_events.get('maCross'))}"),
        (f"热度：档位 {cross_section.get('signalTier') or 'unknown'}"
         f" · 横截面分位 {_fmt_num(cross_section.get('percentile'), 1)}"
         f"（较前槽 {_fmt_num(cross_section.get('percentileDelta'), 1)}）"
         f" · 依据 {_tier_reasons(cross_section.get('tierReasons'))}"),
        (f"量价：档位 {volume_price.get('signalTier') or 'unknown'}"
         f" · 方向 {_dir_std(volume_price.get('direction'))}"
         f" · 象限 {volume_price.get('quadrant') or '数据不足'}"
         f" · 依据 {_tier_reasons(volume_price.get('tierReasons'))}"),
        "【原始行情证据】",
        (f"涨幅 {_fmt_num(row.get('change'))}% · 量比 {_fmt_num(row.get('volumeRatio'))}"
         f" · 主力净额 {zl_s}亿 · 换手 {_fmt_num(row.get('turnoverRate'))}%"
         + (f"（帧级行情字段缺失，取自 half_hour 15:00 补齐：{','.join(sparse_fields)}）" if sparse_fields else "")),
        f"当日排名轨迹（槽:名次,涨幅）：{_traj_line(trajectory)}",
        (f"近10日排名轨迹（日:名次,涨幅）：{_traj_line(multi_day_trajectory or [])}"
         if multi_day_trajectory else "近10日排名轨迹：数据缺口（fail-visible）"),
        (f"【环境门注记】生命周期 {STAGE_ZH.get(str(gate.get('stage')), gate.get('stage') or '缺')}"
         f" · 一票否决={'是' if gate.get('veto') else '否'}（环境门只注记不参与投票）"),
        (f"【待复核判读】规则投票（仅供复核）：四维方向见上 → 综合档位 {synergy_tier or 'unknown'}"),
    ]
    return "\n".join(lines)


def build_lifecycle_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                              trajectory: list[dict], multi_day_trajectory: list[dict] | None = None,
                              metrics: dict, evidence: dict,
                              prev_stage_line: str, stage: Any, action: Any,
                              confidence: Any, reasons: Any) -> str:
    """题集 B 叙事（预登记 §三·二；跨日原料化后判据「多日/峰值」引用有可数锚）。"""
    lines = [
        f"{trading_date} 交易日 {slot} 槽 · {code} {name or ''}".rstrip(),
        f"【当日排名轨迹】（槽:名次,涨幅）{_traj_line(trajectory)}",
        (f"【近10日排名轨迹】（日:名次,涨幅）{_traj_line(multi_day_trajectory or [])}"
         if multi_day_trajectory else "【近10日排名轨迹】数据缺口（fail-visible）"),
        "【生命周期度量】（规则计算读数）",
        (f"排名速度 {_fmt_num(metrics.get('rankVelocity'), 3)} · 排名加速度 {_fmt_num(metrics.get('rankAcceleration'), 3)}"
         f" · 热区停留 {_fmt_num(metrics.get('hotZoneStreak'), 0)} 天 · 近期最佳名次 {_fmt_num(metrics.get('bestRecentRank'), 0)}"
         f" · 距峰回撤 {_fmt_num(metrics.get('drawdownFromPeak'), 2)} 位 · 路径承诺度 {_fmt_num(metrics.get('rankPathCommitment'), 3)}"),
        (f"动量与风险读数：短 {_fmt_num(evidence.get('momentumShort'))} / 中 {_fmt_num(evidence.get('momentumMid'))}"
         f" / 长 {_fmt_num(evidence.get('momentumLong'))} · 动量加速度 {_fmt_num(evidence.get('momentumAcceleration'))}"
         f" · 风险压强 {_fmt_num(evidence.get('riskPressure'), 3)}"),
        f"【前一交易日】{prev_stage_line}",
        (f"【待复核判读】规则判定（仅供复核）：阶段={STAGE_ZH.get(str(stage), stage or '缺')}"
         f" · 动作={ACTION_ZH.get(str(action), action or '缺')} · 置信={_fmt_num(confidence, 0)}"
         f" · 理由={_tier_reasons(reasons)}"),
    ]
    return "\n".join(lines)
