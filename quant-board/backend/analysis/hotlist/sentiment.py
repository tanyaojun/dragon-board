"""热榜情绪纯函数——TS HotListSentimentAnalyzer 的 Python 等价实现（唯一权威口径）。

移植源: src/services/hotlist/HotListSentimentAnalyzer.ts（golden 对齐基线见
quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json）。
纯函数：不做 I/O、不持有 db 句柄；缺失/NaN 按 fail-visible 输出标注，不伪造状态。

2026-09-10 口径统一（spec: docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md）：
**8 类展示分类层已删除**，规则引擎不再以 8 类 label 作判据，改为消费 join 层注入的一等字段派生标记
（等价内联，用户裁决 B1）：

- `displayStatusStage`：`cycle.stage`（5 态，缺失/非法 → `None`）
- `displayStatusStrongMoney`：原「强资确认」判据（`cooling` + 强资金 + 量能承接）
- `displayStatusRisk`：原「资金背离 + 转弱预警」判据

判据等价对照（因此 `stage`/`signals`/`warnings`/`riskLevel` 不变）：
  昨强 = stage ∈ {ignition, expansion} 或 displayStatusStrongMoney（旧：主升确认+点火观察+强资确认）
  拥挤 = stage == crowded（旧：高位拥挤）
  风险 = displayStatusRisk（旧：资金背离+转弱预警）
  强资 = displayStatusStrongMoney（旧：强资确认）

对外分布改为 `stageCounts`/`stageShares`（5 态 + unknown）；`statusCounts`（8 类）与展示用派生指标
（`activeOpportunityCount`/`opportunityCount`/`riskCount`/`crowdedCount` 及各自 share）已删除。
规则引擎仍需要的四个量（`activeOpportunityShare`/`strongMoneyShare`/`riskShare`/`crowdedShare`）
按 stage 桶等价重定义，**仅作规则输入，不进展示层**。

**本轮不动**：`signals`/`warnings` 文案中的 8 类措辞（如“强资确认与点火观察…”）保持原样——它们
是纯展示文本、不参与判据；改文案会改变 golden 的 signals/warnings 期望值，属独立后续专项。
"""
from __future__ import annotations

import math
import re
from typing import Any

from backend.analysis.ranktrend.display_status import STAGE_ENUM, STAGE_LABELS, STAGE_UNKNOWN_LABEL

# TS: src/config/constants.ts LIMIT_UP_CONFIG
_LIMIT_THRESHOLDS = {"MAIN": 9.8, "GEM": 19.8, "STAR": 19.8, "NORTH": 29.8}
_CHANGE_TOLERANCE = 0.5

# 对外分布键：5 态 + unknown（stage 缺失/非法）。词表单一来源在 display_status。
STAGE_KEYS: tuple[str, ...] = (*STAGE_ENUM, "unknown")
STAGE_LABEL_BY_KEY: dict[str, str] = {**STAGE_LABELS, "unknown": STAGE_UNKNOWN_LABEL}


def to_number(value: Any) -> float:
    # TS: toNumber —— Number(value)，NaN→0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def normalize_code(value: Any) -> str:
    return str(value or "").strip()


def get_rank(stock: dict, fallback_index: int) -> int:
    # TS: getRank —— compRank ?? rank，>0 有效
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    return int(rank) if rank > 0 else fallback_index + 1


def sort_rows(rows: list[dict] | None) -> list[dict]:
    # TS: sortByRank —— 过滤无 code，按 rank 升序
    filtered = [row for row in (rows or []) if normalize_code(row.get("code"))]
    return sorted(filtered, key=lambda row: get_rank(row, 9999))


def get_trusted_volume_ratio(stock: dict) -> float:
    # TS: getTrustedVolumeRatio（VolumeRatioTrust.ts L1-12）逐分支对齐：
    # value 非有限或 <=0 → 0；meta 缺失（None/0/''）→ 原值直通（视为已收盘可信）；
    # meta 存在（含空 dict，TS 中空对象为 truthy）→ 仅 status=='fresh' 返回原值，否则 0
    value = to_number(stock.get("volumeRatio"))
    if value <= 0:
        return 0.0
    meta = stock.get("volumeRatioMeta")
    if not meta and not isinstance(meta, dict):
        return value
    status = meta.get("status") if isinstance(meta, dict) else None
    return value if status == "fresh" else 0.0


def limit_threshold(code: str) -> float:
    # TS: StockUtils.getLimitThreshold —— 688/689→STAR，30→GEM，43/8/92→NORTH，其余 MAIN；无 ST 特判
    normalized = str(code or "").strip()
    padded = normalized.zfill(6)
    if padded.startswith("688") or padded.startswith("689"):
        return _LIMIT_THRESHOLDS["STAR"]
    if padded.startswith("30"):
        return _LIMIT_THRESHOLDS["GEM"]
    if padded.startswith("43") or padded.startswith("8") or padded.startswith("92"):
        return _LIMIT_THRESHOLDS["NORTH"]
    return _LIMIT_THRESHOLDS["MAIN"]


def check_limit_status(change: float, code: str) -> dict:
    # TS: StockUtils.checkLimitStatus —— isAlmostLimitUp = change >= threshold.up - tolerance*3
    threshold = limit_threshold(code)
    tolerance = _CHANGE_TOLERANCE
    return {
        "isLimitUp": change >= threshold - tolerance,
        "isLimitDown": change <= -threshold + tolerance,
        "isAlmostLimitUp": change >= threshold - tolerance * 3,
        "isAlmostLimitDown": change <= -threshold + tolerance * 3,
        "threshold": {"up": threshold, "down": -threshold},
    }


def _entry_reason(stock: dict) -> str:
    # TS: classifyEntryReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitUp"]:
        return "limit_up"
    if to_number(stock.get("zlje")) > 0 or to_number(stock.get("zljzb")) > 0:
        return "strong_money"
    if get_trusted_volume_ratio(stock) > 2:
        return "new_high_volume"
    return "rank_surge"


def _exit_reason(stock: dict) -> str:
    # TS: classifyExitReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitDown"]:
        return "limit_down"
    if change < -3:
        return "weakening"
    return "rank_out_of_range"


def compute_turnover(today_rows: list[dict], yesterday_rows: list[dict]) -> dict:
    # TS: computeTurnover L291-320
    today = sort_rows(today_rows)
    yesterday = sort_rows(yesterday_rows)
    today_codes = {normalize_code(row.get("code")) for row in today}
    yesterday_codes = {normalize_code(row.get("code")) for row in yesterday}
    new_entries = [row for row in today if normalize_code(row.get("code")) not in yesterday_codes]
    eliminated = [row for row in yesterday if normalize_code(row.get("code")) not in today_codes]
    return {
        "previousPoolSize": len(yesterday),
        "currentPoolSize": len(today),
        "retainedFromYesterday": sum(1 for row in today if normalize_code(row.get("code")) in yesterday_codes),
        "newEntries": [normalize_code(row.get("code")) for row in new_entries],
        "eliminated": [normalize_code(row.get("code")) for row in eliminated],
        "newEntryDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "entryReason": _entry_reason(row),
            }
            for index, row in enumerate(new_entries)
        ],
        "eliminatedDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "exitReason": _exit_reason(row),
            }
            for index, row in enumerate(eliminated)
        ],
    }


def _parse_board_height_text(value: Any) -> int:
    # TS: parseBoardHeightText —— "首板"→1，正则 (\d+)\s*(?:连?板|天|日)?
    raw = str(value or "").strip()
    if not raw:
        return 0
    if "首板" in raw:
        return 1
    match = re.search(r"(\d+)\s*(?:连?板|天|日)?", raw)
    return int(to_number(match.group(1))) if match else 0


def _raw_board_height(stock: dict) -> int:
    # TS: getRawBoardHeight
    continuous_days = to_number(stock.get("continuousDays"))
    candidates = [
        to_number(stock.get("boardHeight")),
        to_number(stock.get("highDays")),
        continuous_days if continuous_days > 1 else 0,
        _parse_board_height_text(stock.get("lianbanStr")),
        _parse_board_height_text(stock.get("lianban")),
    ]
    return int(max(candidates))


def _has_limit_up_marker(stock: dict) -> bool:
    # TS: hasLimitUpMarker
    return bool(
        str(stock.get("firstZtTime") or "").strip()
        or str(stock.get("lastZtTime") or "").strip()
        or str(stock.get("first_limit_up_time") or "").strip()
        or str(stock.get("last_limit_up_time") or "").strip()
        or _raw_board_height(stock) > 0
    )


def _has_stock_zhaban_signal(stock: dict) -> bool:
    # TS: hasStockZhabanSignal
    return bool(
        stock.get("isZhaban") is True or stock.get("zhaban") is True
        or stock.get("openedLimit") is True or stock.get("limitOpened") is True
        or stock.get("failedLimitUp") is True or stock.get("isFailedLimitUp") is True
    )


def get_stock_limit_signal(stock: dict) -> dict:
    # TS: getStockLimitSignal L362-378
    code = normalize_code(stock.get("code"))
    status = check_limit_status(to_number(stock.get("change")), code)
    has_marker = _has_limit_up_marker(stock)
    board_height = max(_raw_board_height(stock), 1 if status["isLimitUp"] or has_marker else 0)
    return {
        "isLimitUp": status["isLimitUp"],
        "isAlmostLimitUp": status["isAlmostLimitUp"],
        "isLimitDown": status["isLimitDown"],
        "threshold": status["threshold"]["up"],
        "boardHeight": board_height,
        "isBoard2Plus": board_height >= 2,
        "hasLimitMarker": has_marker,
    }


def _has_limit_up_evidence(stock: dict) -> bool:
    signal = get_stock_limit_signal(stock)
    return signal["isLimitUp"] or signal["hasLimitMarker"]


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _resolve_sample_size(rows: list[dict], top_n: int | None) -> int:
    if top_n and top_n > 0:
        return min(len(rows), int(top_n))
    return len(rows)


def _calculate_hot_trin(up_count: int, down_count: int, up_turnover: float, down_turnover: float) -> float | None:
    # TS: calculateHotTrin —— 注意与旧 operations/_hot_trin 不同：turnover 取原值分桶
    if up_count <= 0 or down_count <= 0 or up_turnover <= 0 or down_turnover <= 0:
        return None
    return (up_count / down_count) / (up_turnover / down_turnover)


def build_day_metrics_from_sorted(sorted_rows: list[dict], top_n: int, trading_date: str | None = None) -> dict:
    # TS: buildDayMetricsFromSorted L458-546；分布经 resolve_row_stage（5 态 + unknown）。
    # statusSourceCounts 为后端超集约定（非 TS HotListDayMetrics 字段），series 文档透出。
    top = sorted_rows[:top_n]
    stage_counts = {key: 0 for key in STAGE_KEYS}
    # 规则引擎需要的三个行级量（原 8 类派生，现按 stage / 注入标记等价重定义；仅作规则输入）
    strong_money = risk_rows = crowded_rows = 0
    status_source = {"displayStatus": 0, "fallback": 0}

    up_count = down_count = flat_count = 0
    up_turnover = down_turnover = total_turnover = 0.0
    main_net = super_net = change_sum = 0.0
    near_limit_up = high_gain = high_turnover = 0

    for stock in top:
        change = to_number(stock.get("change"))
        turnover = to_number(stock.get("turnover"))
        turnover_rate = to_number(stock.get("turnoverRate"))
        stage_key, row_strong, row_risk, row_fallback = resolve_row_signals(stock, sorted_rows, status_source)
        # spec「fallback 行归 unknown 桶」：展示桶与规则输入解耦 —— fallback 行即使启发式
        # 判出 crowded/cooling 也归 unknown 展示桶，规则输入（下方 strong/crowded 计数）仍按判据计。
        stage_counts["unknown" if row_fallback else stage_key] += 1
        if row_strong and stage_key == "cooling":
            # 结构保证：strong_money ⊆ cooling 判定行（按 stage_key 口径，非展示桶——fallback
            # 强资行 stage_key=cooling 但桶为 unknown，仍须进 strongMoneyShare 保持 B1 等价）。
            # 同时兜住注入标记与 stage 不一致的行，确保 active = ignition + expansion + 强资 不双计。
            strong_money += 1
        if row_risk:
            risk_rows += 1
        if stage_key == "crowded":
            crowded_rows += 1
        total_turnover += turnover
        main_net += to_number(stock.get("zlje"))
        super_net += to_number(stock.get("cddje"))
        change_sum += change
        if change > 0:
            up_count += 1
            up_turnover += turnover
        elif change < 0:
            down_count += 1
            down_turnover += turnover
        else:
            flat_count += 1
        if get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            near_limit_up += 1
        if change >= 7:
            high_gain += 1
        if turnover_rate >= 10:
            high_turnover += 1

    total = len(top)
    stage_shares = {key: _safe_divide(stage_counts[key], total) for key in STAGE_KEYS}
    # 规则输入四量（等价重定义；不对外展示）：
    #   activeOpportunityShare = (ignition + expansion + 强资) / total（旧：主升+点火+强资）
    #   riskShare              = risk 行 / total                  （旧：资金背离 + 转弱预警）
    #   crowdedShare           = crowded / total                  （旧：高位拥挤）
    #   strongMoneyShare       = 强资 / total                     （旧：强资确认）
    active = stage_counts["ignition"] + stage_counts["expansion"] + strong_money
    risk = risk_rows
    crowded = crowded_rows
    result = {
        "tradingDate": trading_date,
        "total": len(sorted_rows),
        "topN": total,
        "upCount": up_count,
        "downCount": down_count,
        "flatCount": flat_count,
        "upRatio": _safe_divide(up_count, total),
        "downRatio": _safe_divide(down_count, total),
        "hotTrin": _calculate_hot_trin(up_count, down_count, up_turnover, down_turnover),
        "totalTurnover": total_turnover,
        "upTurnover": up_turnover,
        "downTurnover": down_turnover,
        "mainNetAmount": main_net,
        "superNetAmount": super_net,
        "avgChange": _safe_divide(change_sum, total),
        "nearLimitUpCount": near_limit_up,
        "highGainCount": high_gain,
        "highTurnoverCount": high_turnover,
        "stageCounts": stage_counts,
        "stageShares": stage_shares,
        # 规则输入（不进展示层）：名称保持规则侧既有用法，语义按 stage 桶 / 注入标记等价重定义
        "activeOpportunityShare": _safe_divide(active, total),
        "strongMoneyShare": _safe_divide(strong_money, total),
        "riskShare": _safe_divide(risk, total),
        "crowdedShare": _safe_divide(crowded, total),
    }
    result["statusSourceCounts"] = status_source
    return result


def build_transition_counts(rows: list[dict]) -> dict[str, int]:
    """阶段迁移计数（2026-09-16）：join 层注入的 cycleTransition 原样计数，按次数降序。

    只统计 golden join 行（join 层对无 analyze 产物行注入 None）；fallback 行不计入，
    避免旧口径混入迁移分布。键为后端原始迁移串（"a->b" 或单段 "a"=阶段延续）。
    """
    counts: dict[str, int] = {}
    for row in rows:
        transition = row.get("cycleTransition")
        if isinstance(transition, str) and transition.strip():
            counts[transition.strip()] = counts.get(transition.strip(), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def build_layer_metrics(rows: list[dict], trading_date: str | None = None) -> dict:
    # TS: buildLayerMetrics L731-739
    sorted_rows = sort_rows(rows)
    return {
        "top20": build_day_metrics_from_sorted(sorted_rows, 20, trading_date),
        "top50": build_day_metrics_from_sorted(sorted_rows, 50, trading_date),
        "top100": build_day_metrics_from_sorted(sorted_rows, 100, trading_date),
        "all": build_day_metrics_from_sorted(sorted_rows, len(sorted_rows), trading_date),
    }


def derive_fallback_row_signals(stock: dict) -> tuple[str, bool, bool]:
    """无 join 记录时的行信号（原 `fallback_status_label` 判据的**等价**改写）。

    返回 `(stage, strong_money, risk)`。为什么必须保留这套判据（B1 等价内联的前提）：golden
    fixture 的输入行只有原始行情字段（无 displayStatus），旧链路由 `fallback_status_label`
    得出 8 类 label，规则引擎再据此算 `activeOpportunityShare`/`riskShare`/`crowdedShare`/
    `strongMoneyShare`。分类层删除后这些量改由 stage + 标记表达，所以这里把旧判据**逐条等价**映射：

    - 旧「资金背离」→ `risk=True`（无 stage 信息 → stage 归 `unknown`）
    - 旧「高位拥挤」→ `stage="crowded"`
    - 旧「强资确认」→ `stage="cooling", strong=True`（与 display_status 的 cooling 强资判据一致）
    - 旧「新入观察」/「样本不足」→ `unknown`（旧口径里两者都不是 lifecycle 阶段）

    等价性由 golden case 守护（stage/riskLevel/signals/warnings/confidence 期望值不变）。
    """
    change = to_number(stock.get("change"))
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    zlje = to_number(stock.get("zlje"))
    zljzb = to_number(stock.get("zljzb"))
    cddje = to_number(stock.get("cddje"))
    cddjzb = to_number(stock.get("cddjzb"))
    volume_ratio = get_trusted_volume_ratio(stock)
    turnover_rate = to_number(stock.get("turnoverRate"))
    strong_money = zlje > 0 and zljzb >= 8 and (cddje > 0 or cddjzb >= 3)
    money_weak = zlje < 0 or zljzb <= -8 or (cddje < 0 and cddjzb <= -3)
    high_position = change >= 8 or rank <= 30
    overheated = high_position and (volume_ratio >= 1.8 or turnover_rate >= 10)
    if money_weak and (rank <= 80 or change > 0):
        return "unknown", False, True    # 旧「资金背离」
    if overheated:
        return "crowded", False, False   # 旧「高位拥挤」
    if strong_money:
        return "cooling", True, False    # 旧「强资确认」
    return "unknown", False, False       # 旧「新入观察」/「样本不足」


def resolve_row_signals(
    stock: dict,
    context_rows: list[dict],
    status_source: dict | None = None,
) -> tuple[str, bool, bool, bool]:
    """行的 `(stage, strong_money, risk, is_fallback)`。

    优先用 join 层注入的三个标记（`displayStatusStage` / `displayStatusStrongMoney` /
    `displayStatusRisk`）；无任何 join 记录时落到 `derive_fallback_row_signals`（与旧 8 类逐条等价）。
    来源计数：join 命中 → `displayStatus`；无记录（或 annotate 补齐的 fallback 行，带
    `_stageFromFallback` 标记）→ `fallback`（fail-visible，可辨源）。

    第 4 分量 `is_fallback` 供计量层分桶：spec 规定 fallback 行的展示桶一律归 `unknown`，
    但规则输入（strongMoneyShare 等）仍按判据计，因此 stage 分量保留 fallback 启发式的
    原始判定（crowded/cooling），由调用方决定是否进展示桶。
    """
    if stock.get("_stageFromFallback"):
        # annotate 补齐的 fallback 行（注入过等价 stage/标记）：来源仍计 fallback。
        # 原始行情字段未被 annotate 改写，按 fallback 判据重算结果稳定。
        if status_source is not None:
            status_source["fallback"] += 1
        stage, strong, risk = derive_fallback_row_signals(stock)
        return stage, strong, risk, True
    stage = stock.get("displayStatusStage")
    if isinstance(stage, str) and stage in STAGE_ENUM:
        if status_source is not None:
            status_source["displayStatus"] += 1
        return stage, is_strong_money_row(stock), is_risk_row(stock), False
    if isinstance(stock.get("displayStatusLabel"), str) and stock.get("displayStatusLabel"):
        # 有记录但 stage 缺失（unknown 投影）→ 归 unknown，仍算 join 命中
        if status_source is not None:
            status_source["displayStatus"] += 1
        return "unknown", is_strong_money_row(stock), is_risk_row(stock), False
    if status_source is not None:
        status_source["fallback"] += 1
    stage, strong, risk = derive_fallback_row_signals(stock)
    return stage, strong, risk, True


def resolve_row_stage(stock: dict, context_rows: list[dict], status_source: dict | None = None) -> str:
    """行的 stage key（5 态或 `unknown`）—— `resolve_row_signals` 的第一个分量。"""
    return resolve_row_signals(stock, context_rows, status_source)[0]


def annotate_rows_with_signals(rows: list[dict] | None) -> None:
    """给每行就地补齐三个规则标记（幂等）。

    规则引擎（`is_strong_money_row` / `is_risk_row` / `is_yesterday_strong_row`）统一读这三个标记，
    避免各规则自建第二套判据。join 层（`_join_display_status`）已在写入前注入；本函数是**幂等补齐**：
    缺标记的行（golden fixture 这类只有行情字段的输入）按 `derive_fallback_row_signals` 等价补上。
    """
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("displayStatusStrongMoney"), bool) and isinstance(
            row.get("displayStatusRisk"), bool
        ):
            continue
        stage, strong, risk, is_fallback = resolve_row_signals(row, rows or [], None)
        current_stage = row.get("displayStatusStage")
        if not (isinstance(current_stage, str) and current_stage in STAGE_ENUM):
            row["displayStatusStage"] = stage if stage in STAGE_ENUM else None
        row["displayStatusStrongMoney"] = strong
        row["displayStatusRisk"] = risk
        if is_fallback:
            # provenance 标记：该行的 stage/标记来自 fallback 等价判据（非 join 记录）。
            # resolve_row_signals 据此把来源仍计为 fallback（而非被注入的 stage 骗成
            # displayStatus），build_day_metrics 据此把展示桶归 unknown（spec：fallback
            # 行归 unknown 桶）。幂等性由上方“双标记已存在即跳过”保证。
            row["_stageFromFallback"] = True


def resolve_stock_status(stock: dict, context_rows: list[dict], status_source: dict | None = None) -> str:
    """兼容壳（旧 8 类 API）：返回 stage 对应的展示 label。

    分类层删除后 8 类 label 不再存在，本函数只做 stage → 词表映射，供尚未迁移的调用点/测试使用；
    新代码请用 `resolve_row_stage`。
    """
    return STAGE_LABEL_BY_KEY[resolve_row_stage(stock, context_rows, status_source)]


def is_strong_money_row(stock: dict) -> bool:
    """原「强资确认」判据。

    优先读 join 层注入的 `displayStatusStrongMoney`；行上没有该标记时（golden fixture 这类
    只有行情字段的输入）按 `derive_fallback_row_signals` 的等价判据现算。
    """
    flag = stock.get("displayStatusStrongMoney")
    if isinstance(flag, bool):
        return flag
    return derive_fallback_row_signals(stock)[1]


def is_risk_row(stock: dict) -> bool:
    """原「资金背离 + 转弱预警」判据。同上：优先读注入标记，否则等价 fallback 现算。"""
    flag = stock.get("displayStatusRisk")
    if isinstance(flag, bool):
        return flag
    return derive_fallback_row_signals(stock)[2]


def is_yesterday_strong_row(stock: dict) -> bool:
    """原「主升确认 + 点火观察 + 强资确认」判据（昨强）。

    `displayStatusStage` 存在（含显式 `None`）时以它为准；完全无标记时用等价 fallback 现算。
    """
    if "displayStatusStage" in stock:
        stage = stock.get("displayStatusStage")
        return bool(stage in ("ignition", "expansion")) or is_strong_money_row(stock)
    fallback_stage, fallback_strong, _ = derive_fallback_row_signals(stock)
    return bool(fallback_stage in ("ignition", "expansion")) or fallback_strong


def fallback_status_label(stock: dict) -> str:
    # TS: getFallbackHistoricalStatus L395-417
    change = to_number(stock.get("change"))
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    zlje = to_number(stock.get("zlje"))
    zljzb = to_number(stock.get("zljzb"))
    cddje = to_number(stock.get("cddje"))
    cddjzb = to_number(stock.get("cddjzb"))
    volume_ratio = get_trusted_volume_ratio(stock)
    turnover_rate = to_number(stock.get("turnoverRate"))
    strong_money = zlje > 0 and zljzb >= 8 and (cddje > 0 or cddjzb >= 3)
    money_weak = zlje < 0 or zljzb <= -8 or (cddje < 0 and cddjzb <= -3)
    high_position = change >= 8 or rank <= 30
    overheated = high_position and (volume_ratio >= 1.8 or turnover_rate >= 10)
    if money_weak and (rank <= 80 or change > 0):
        return "资金背离"
    if overheated:
        return "高位拥挤"
    if strong_money:
        return "强资确认"
    if change >= 3 or rank <= 100:
        return "新入观察"
    return "样本不足"


def derive_row_flags(analysis: dict | None, row: dict) -> dict:
    """从 `analysis` 派生规则层需要的两个判据标记（**唯一来源**，与 display_status 同判据）。

    为什么放在这里：热榜行自身只有 `zlje`/`zljzb`（无 `cycle.stage`、无 `volumePrice.signalTier`），
    而规则引擎（昨强/强资/拥挤/风险）需要 8 类时代的等价判据——因此由 join 层调本函数**算一次**
    并注入行（`displayStatusStrongMoney` / `displayStatusRisk`），避免规则层自建第二套。

    - `strong_money`：原「强资确认」= `stage == cooling` 且强资金且量能承接（合同判据表；
      stage 门控必须显式判断——否则非 cooling 阶段的强资行会在 activeOpportunityShare 里双计）
    - `risk`：原「资金背离 + 转弱预警」= stage == reversal，或 cooling 且非强资，或资金背离
      （`synergy.state == 存疑` 且 `zljzb <= 0`）
    """
    from backend.analysis.ranktrend.display_status import _is_strong_money, _is_volume_supported

    data = analysis if isinstance(analysis, dict) else {}
    stage = ((data.get("cycle") or {}) if isinstance(data.get("cycle"), dict) else {}).get("stage")
    strong = bool(stage == "cooling" and _is_strong_money(row) and _is_volume_supported(data))
    synergy = ((data.get("observation") or {}) if isinstance(data.get("observation"), dict) else {}).get("synergy")
    synergy_state = (synergy or {}).get("state") if isinstance(synergy, dict) else None
    money_divergence = str(synergy_state or "") == "存疑" and zljzb_le_zero(row)
    return {
        "strongMoney": strong,
        "risk": bool(stage == "reversal" or (stage == "cooling" and not strong) or money_divergence),
    }


def zljzb_le_zero(row: dict) -> bool:
    try:
        return float(row.get("zljzb")) <= 0
    except (TypeError, ValueError):
        return False


def _empty_ths_pools() -> dict:
    # TS: createEmptyThsPoolsEvidence
    return {
        "source": "ths-limitup-pools", "degraded": False, "errors": [],
        "poolCounts": {"one": 0, "two": 0, "three": 0, "four": 0, "high": 0, "failed": 0, "rushing": 0, "drawdown": 0},
        "failedCount": 0, "rushingCount": 0, "drawdownCount": 0,
        "drawdownRiskLabel": "涨停股回撤榜", "maxDrawdown": None, "avgDrawdown": None,
    }


def build_market_limit_evidence(market_data: dict | None) -> dict:
    # TS: buildMarketLimitEvidence L586-607
    if not market_data:
        return {
            "ztCount": 0, "zhabanCount": 0, "fengbanRate": 0,
            "board1": 0, "board2": 0, "board3": 0, "board4Plus": 0,
            "maxContinuousDays": 0, "thsPools": _empty_ths_pools(),
        }
    zhaban = market_data.get("zhaban") if isinstance(market_data.get("zhaban"), dict) else {}
    limit_data = market_data.get("limitData") if isinstance(market_data.get("limitData"), dict) else {}
    board1 = to_number(limit_data.get("yiban"))
    board2 = to_number(limit_data.get("erban"))
    board3 = to_number(limit_data.get("sanban"))
    board4_plus = to_number(limit_data.get("sibanPlus"))
    fallback_max_days = 4 if board4_plus > 0 else 3 if board3 > 0 else 2 if board2 > 0 else 1 if board1 > 0 else 0
    return {
        "ztCount": to_number(market_data.get("ztCount")),
        "zhabanCount": to_number(zhaban.get("count")),
        "fengbanRate": to_number(zhaban.get("fengbanRate")),
        "board1": board1, "board2": board2, "board3": board3, "board4Plus": board4_plus,
        "maxContinuousDays": to_number(market_data.get("maxContinuousDays")) or fallback_max_days,
        "thsPools": market_data.get("thsLimitUpPools") if isinstance(market_data.get("thsLimitUpPools"), dict) else _empty_ths_pools(),
    }


def build_limit_intersection_evidence(sorted_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildLimitIntersectionEvidence L613-643
    top20 = sorted_rows[:20]
    top50 = sorted_rows[:50]
    top100 = sorted_rows[: _resolve_sample_size(sorted_rows, top_n)]
    near = board2plus = 0
    max_height = 0
    zhaban = 0
    for stock in top100:
        signal = get_stock_limit_signal(stock)
        if signal["isAlmostLimitUp"]:
            near += 1
        if signal["isBoard2Plus"]:
            board2plus += 1
        max_height = max(max_height, signal["boardHeight"])
        if _has_stock_zhaban_signal(stock):
            zhaban += 1
    limit_up = sum(1 for stock in top100 if _has_limit_up_evidence(stock))
    size = len(top100)
    return {
        "top20LimitUpCount": sum(1 for stock in top20 if _has_limit_up_evidence(stock)),
        "top50LimitUpCount": sum(1 for stock in top50 if _has_limit_up_evidence(stock)),
        "top100LimitUpCount": limit_up,
        "top100LimitUpShare": _safe_divide(limit_up, size),
        "top100NearLimitUpCount": near,
        "top100Board2PlusCount": board2plus,
        "top100MaxBoardHeight": max_height,
        "top100ZhabanCount": zhaban,
        "top100ZhabanShare": _safe_divide(zhaban, size),
    }


def build_yesterday_hot_limit_evidence(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayHotLimitEvidence L656-712
    empty = {"count": 0, "retainedTop100Count": 0, "avgChange": None, "positiveRate": None, "weakeningRate": None, "failedOrWeakRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_limit_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if _has_limit_up_evidence(row) and normalize_code(row.get("code"))
    ]
    if not yesterday_limit_codes:
        return empty

    matched = retained = positive = weakening = failed_or_weak = 0
    change_sum = 0.0
    for code in yesterday_limit_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            failed_or_weak += 1
            continue
        change = to_number(stock.get("change"))
        is_risk = is_risk_row(stock)
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or is_risk:
            weakening += 1
        if change <= 0 or is_risk or not get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            failed_or_weak += 1
    return {
        "count": len(yesterday_limit_codes),
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningRate": _safe_divide(weakening, len(yesterday_limit_codes)),
        "failedOrWeakRate": _safe_divide(failed_or_weak, len(yesterday_limit_codes)),
    }


def build_limit_evidence(today_rows: list[dict], yesterday_rows: list[dict], top_n: int | None, market_data: dict | None) -> dict:
    # TS: buildLimitEvidence L714-725
    return {
        "market": build_market_limit_evidence(market_data),
        "intersection": build_limit_intersection_evidence(today_rows, top_n),
        "yesterdayHotLimit": build_yesterday_hot_limit_evidence(yesterday_rows, today_rows, top_n),
    }


def build_yesterday_strong_performance(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayStrongPerformance L754-814
    empty = {"count": 0, "matchedCount": 0, "retainedTop100Count": 0, "avgChange": None,
             "positiveCount": 0, "positiveRate": None, "weakeningCount": 0, "weakeningRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    strong_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if is_yesterday_strong_row(row) and normalize_code(row.get("code"))
    ]
    if not strong_codes:
        return empty

    matched = retained = positive = weakening = 0
    change_sum = 0.0
    for code in strong_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            continue
        change = to_number(stock.get("change"))
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or is_risk_row(stock):
            weakening += 1
    return {
        "count": len(strong_codes),
        "matchedCount": matched,
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveCount": positive,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningCount": weakening,
        "weakeningRate": _safe_divide(weakening, len(strong_codes)),
    }


def build_comparison(stocks: list[dict], yesterday_rows: list[dict], day_before_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildComparison L816-892
    today_rows = sort_rows(stocks)
    yesterday_sorted = sort_rows(yesterday_rows)
    day_before_sorted = sort_rows(day_before_rows)
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_sorted, top_n)
    day_before_size = _resolve_sample_size(day_before_sorted, top_n)

    today = build_day_metrics_from_sorted(today_rows, today_size)
    yesterday = build_day_metrics_from_sorted(yesterday_sorted, yesterday_size) if yesterday_sorted else None
    day_before = build_day_metrics_from_sorted(day_before_sorted, day_before_size) if day_before_sorted else None

    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_top_codes = {normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]}
    day_before_top_codes = {normalize_code(row.get("code")) for row in day_before_sorted[:day_before_size]}
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}

    retain_from_yesterday = len([code for code in today_top_codes if code in yesterday_top_codes])
    retain_from_day_before = len([code for code in today_top_codes if code in day_before_top_codes])
    new_top_codes = [code for code in today_top_codes if code not in yesterday_top_codes]
    new_strong = sum(
        1 for code in new_top_codes
        if code in today_by_code and is_strong_money_row(today_by_code[code])
    )
    yesterday_strong_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if is_strong_money_row(row) and normalize_code(row.get("code"))
    ]
    yesterday_crowded_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if row.get("displayStatusStage") == "crowded" and normalize_code(row.get("code"))
    ]
    yesterday_strong_retain = (
        _safe_divide(len([code for code in yesterday_strong_codes if code in today_top_codes]), len(yesterday_strong_codes))
        if yesterday_strong_codes else None
    )
    yesterday_crowded_risk = sum(
        1 for code in yesterday_crowded_codes
        if code in today_by_code and is_risk_row(today_by_code[code])
    )
    return {
        "today": today,
        "yesterday": yesterday,
        "dayBefore": day_before,
        "totalChange1d": today["total"] - yesterday["total"] if yesterday else None,
        "totalChange2d": today["total"] - day_before["total"] if day_before else None,
        "top100RetainFromYesterday": retain_from_yesterday,
        "top100RetainFromDayBefore": retain_from_day_before,
        "top100RetainRateFromYesterday": _safe_divide(retain_from_yesterday, yesterday_size or today_size),
        "top100RetainRateFromDayBefore": _safe_divide(retain_from_day_before, day_before_size or today_size),
        "newTop100Count": len(new_top_codes),
        "newTop100StrongMoneyCount": new_strong,
        "yesterdayStrongRetainRate": yesterday_strong_retain,
        "yesterdayCrowdedRiskCount": yesterday_crowded_risk,
        "yesterdayStrongPerformance": build_yesterday_strong_performance(yesterday_sorted, today_rows, top_n),
    }


# ---------------------------------------------------------------------------
# Task 4: 5 证据 evaluator + resolveStage 级联 + 主入口（TS L894-1303）
# ---------------------------------------------------------------------------
from decimal import Decimal, ROUND_HALF_UP


def _js_to_fixed(value: float, digits: int = 0) -> str:
    # JS Number.toFixed 等价：对 double 的精确二进制值做四舍五入（ties 取大）。
    # 必须用 Decimal(value)（float 精确展开）而非 Decimal(str(value))：
    # toFixed 语义作用在二进制浮点精确值上，例如 (1.005).toFixed(2) === "1.00"。
    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def _js_num_text(value: Any) -> str:
    # JS 模板字符串 ${number} 等价：整数值 number 不带小数点（98.0 → "98"）。
    # TS 侧 ztCount/zhabanCount 等经 toNumber 后仍是 JS number，插值时整数不出现 ".0"。
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# TS: EMOTION_CYCLE_STAGE_CONFIG.confidenceBase（src/types/emotion.ts L51-75，已逐字核对）
_STAGE_CONFIDENCE_BASE = {"冰点": 56, "启动": 58, "发酵": 62, "高潮": 64, "退潮": 64}
# TS: getEmotionCycleStageSummary —— EMOTION_CYCLE_STAGE_CONFIG.summary（src/types/emotion.ts L51-75 逐字复制）
_STAGE_SUMMARY = {
    "冰点": "机会稀少，风险或弱承接占优，优先控制仓位和交易频率。",
    "启动": "情绪开始修复，新增线索和点火机会增多，但持续性仍待确认。",
    "发酵": "强资金、点火和主线扩散形成合力，交易情绪处于扩散阶段。",
    "高潮": "前排强度和资金承接较强，但拥挤明显，适合强势识别，不宜盲目追高。",
    "退潮": "风险状态升温或强票承接走弱，交易情绪进入防守优先阶段。",
}


def _push_if(target: list[str], condition: bool, text: str) -> None:
    if condition:
        target.append(text)


def _evaluate_tape_strength(today: dict, layers: dict | None) -> dict:
    # TS: evaluateTapeStrength L918-936
    top20 = (layers or {}).get("top20") or today
    top50 = (layers or {}).get("top50") or today
    signals: list[str] = []
    warnings: list[str] = []
    strong = top20["upRatio"] >= 0.65 and top50["upRatio"] >= 0.55 and today["upRatio"] >= 0.55
    firm = top20["upRatio"] >= 0.6 and today["upRatio"] >= 0.48
    weak = today["upRatio"] <= 0.42 or (top20["upRatio"] < 0.5 and top50["upRatio"] < 0.45)
    level = "strong" if strong else "firm" if firm else "weak" if weak else "mixed"
    _push_if(signals, strong, "前20/前50/全池上涨扩散较强")
    _push_if(signals, not strong and firm, "前排上涨修复，全池仍有承接")
    _push_if(signals, today["nearLimitUpCount"] >= 8, f"全池近涨停 {today['nearLimitUpCount']} 只")
    _push_if(signals, today["highGainCount"] >= 18, f"全池高涨幅 {today['highGainCount']} 只")
    _push_if(warnings, weak, f"热榜上涨宽度偏弱，全池上涨 {_js_to_fixed(today['upRatio'] * 100)}%")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_money_acceptance(today: dict) -> dict:
    # TS: evaluateMoneyAcceptance L938-954（isTrinStrong <1 / isTrinWeak >1.15）
    signals: list[str] = []
    warnings: list[str] = []
    level = "neutral"
    trin = today["hotTrin"]
    if trin is None:
        level = "unknown"
    elif trin < 1:
        level = "strong"
        signals.append(f"热榜 TRIN {_js_to_fixed(trin, 2)}，上涨股成交承接占优")
    elif trin > 1.15:
        level = "weak"
        warnings.append(f"热榜 TRIN {_js_to_fixed(trin, 2)}，上涨家数与成交承接不匹配")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_opportunity_expansion(comparison: dict) -> dict:
    # TS: evaluateOpportunityExpansion L956-978
    today = comparison["today"]
    yesterday = comparison.get("yesterday")
    signals: list[str] = []
    warnings: list[str] = []
    active_share = today["activeOpportunityShare"]
    strong_money_share = today["strongMoneyShare"]
    opportunity_rising = bool(yesterday and active_share > yesterday["activeOpportunityShare"] + 0.04)
    broad = active_share >= 0.18 and strong_money_share >= 0.08
    improving = opportunity_rising or comparison["newTop100Count"] >= 25
    scarce = active_share < 0.08
    level = "broad" if broad else "improving" if improving else "scarce" if scarce else "normal"
    _push_if(signals, broad, f"强资确认与点火观察形成扩散，占比 {_js_to_fixed(active_share * 100)}%")
    _push_if(signals, not broad and opportunity_rising, "有效机会占比较昨日改善")
    _push_if(signals, not broad and comparison["newTop100Count"] >= 25, f"今日新入全池 {comparison['newTop100Count']} 只")
    _push_if(warnings, scarce, f"有效机会偏少，占比 {_js_to_fixed(active_share * 100)}%")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_risk_pressure(comparison: dict) -> dict:
    # TS: evaluateRiskPressure L980-1005
    today = comparison["today"]
    yesterday = comparison.get("yesterday")
    signals: list[str] = []
    warnings: list[str] = []
    risk_rising = bool(yesterday and today["riskShare"] > yesterday["riskShare"] + 0.04)
    crowded_rising = bool(yesterday and today["crowdedShare"] > yesterday["crowdedShare"] + 0.04)
    if today["riskShare"] >= 0.35:
        level = "severe"
    elif today["riskShare"] >= 0.2 or risk_rising:
        level = "high"
    elif today["crowdedShare"] >= 0.18 or crowded_rising:
        level = "crowded"
    else:
        level = "low"
    _push_if(warnings, today["riskShare"] >= 0.35, f"风险压力 {_js_to_fixed(today['riskShare'] * 100)}%，资金背离与转弱预警偏高")
    _push_if(warnings, 0.2 <= today["riskShare"] < 0.35, f"风险压力 {_js_to_fixed(today['riskShare'] * 100)}%")
    _push_if(warnings, risk_rising, "资金背离与转弱预警占比上升")
    _push_if(warnings, today["crowdedShare"] >= 0.18, f"高位拥挤 {_js_to_fixed(today['crowdedShare'] * 100)}%")
    _push_if(warnings, crowded_rising, "高位拥挤占比上升")
    _push_if(signals, level == "low", "风险压力暂未扩散")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_continuity(comparison: dict) -> dict:
    # TS: evaluateContinuity L1007-1036
    signals: list[str] = []
    warnings: list[str] = []
    retain_rate = comparison.get("yesterdayStrongRetainRate")
    performance = comparison["yesterdayStrongPerformance"]
    positive_rate = performance.get("positiveRate")
    weakening_rate = performance.get("weakeningRate")
    weak = (weakening_rate is not None and weakening_rate >= 0.45) or (retain_rate is not None and retain_rate <= 0.25)
    strong = (not weak) and (
        (positive_rate is not None and positive_rate >= 0.6) or (retain_rate is not None and retain_rate >= 0.6)
    )
    _push_if(signals, retain_rate is not None and retain_rate >= 0.6, "昨日强资确认留榜率较高")
    _push_if(warnings, retain_rate is not None and retain_rate <= 0.25, "昨日强资确认留榜率偏低")
    _push_if(signals, positive_rate is not None and positive_rate >= 0.6,
             f"昨日强票今日正收益率 {_js_to_fixed((positive_rate or 0) * 100)}%")
    _push_if(warnings, weakening_rate is not None and weakening_rate >= 0.45,
             f"昨日强票转弱或掉榜率 {_js_to_fixed((weakening_rate or 0) * 100)}%")
    return {"level": "weak" if weak else "strong" if strong else "normal", "signals": signals, "warnings": warnings}


def _collect_limit_evidence_messages(limit_evidence: dict | None) -> dict:
    # TS: collectLimitEvidenceMessages L1038-1091
    signals: list[str] = []
    warnings: list[str] = []
    if not limit_evidence:
        return {"level": "neutral", "signals": signals, "warnings": warnings}
    market = limit_evidence["market"]
    intersection = limit_evidence["intersection"]
    yesterday_hot = limit_evidence["yesterdayHotLimit"]
    ths = market.get("thsPools") or {}
    _push_if(signals, intersection["top100LimitUpCount"] > 0 or intersection["top100NearLimitUpCount"] > 0,
             f"热榜全池涨停 {intersection['top100LimitUpCount']} 只，近涨停 {intersection['top100NearLimitUpCount']} 只")
    _push_if(signals, intersection["top100Board2PlusCount"] > 0,
             f"热榜全池二板以上 {intersection['top100Board2PlusCount']} 只，最高 {intersection['top100MaxBoardHeight']} 板")
    _push_if(signals, market["ztCount"] > 0,
             f"全市场涨停 {_js_num_text(market['ztCount'])} 只，封板率 {_js_to_fixed(market['fengbanRate'])}%")
    positive = yesterday_hot.get("positiveRate")
    _push_if(signals, positive is not None and positive >= 0.55,
             f"昨日热榜涨停今日正收益率 {_js_to_fixed((positive or 0) * 100)}%")
    _push_if(warnings, intersection["top100ZhabanCount"] > 0, f"热榜全池个股炸板 {intersection['top100ZhabanCount']} 只")
    failed_weak = yesterday_hot.get("failedOrWeakRate")
    _push_if(warnings, failed_weak is not None and failed_weak >= 0.5,
             f"昨日热榜涨停走弱或冲板失败率 {_js_to_fixed((failed_weak or 0) * 100)}%")
    _push_if(warnings, market["zhabanCount"] > 0, f"全市场炸板 {_js_num_text(market['zhabanCount'])} 只，仅作背景参考")
    _push_if(warnings, (ths.get("failedCount") or 0) > 0, f"THS炸板池 {ths.get('failedCount')} 只，仅作全市场炸板补充证据")
    _push_if(warnings, (ths.get("drawdownCount") or 0) > 0,
             f"{ths.get('drawdownRiskLabel')} {_js_num_text(ths.get('drawdownCount'))} 只，不等同于全市场亏钱效应")
    return {"level": "neutral", "signals": signals, "warnings": warnings}


def _resolve_risk_level(risk_pressure: dict, continuity: dict) -> str:
    # TS: resolveRiskLevel L1097-1108
    risk = risk_pressure["level"]
    cont = continuity["level"]
    if risk == "severe" or (risk == "high" and cont == "weak"):
        return "高"
    if risk in ("high", "crowded") or cont == "weak":
        return "中"
    return "低"


def resolve_stage(comparison: dict, layers: dict | None = None, limit_evidence: dict | None = None) -> dict:
    # TS: resolveStage L1110-1267 —— 级联顺序 retreat → climax → ferment → start → ice，逐条布尔条件不许简化
    today = comparison["today"]
    tape = _evaluate_tape_strength(today, layers)
    money = _evaluate_money_acceptance(today)
    expansion = _evaluate_opportunity_expansion(comparison)
    risk_pressure = _evaluate_risk_pressure(comparison)
    continuity = _evaluate_continuity(comparison)
    limit_messages = _collect_limit_evidence_messages(limit_evidence)
    signals = tape["signals"] + money["signals"] + expansion["signals"] + risk_pressure["signals"] + continuity["signals"] + limit_messages["signals"]
    warnings = tape["warnings"] + money["warnings"] + expansion["warnings"] + risk_pressure["warnings"] + continuity["warnings"] + limit_messages["warnings"]

    change1d = comparison.get("totalChange1d")
    total_expanded = change1d is not None and change1d > 0
    total_shrank = change1d is not None and change1d < 0
    risk_elevated = risk_pressure["level"] in ("high", "severe")
    risk_level = _resolve_risk_level(risk_pressure, continuity)
    tape_weak = tape["level"] == "weak"
    tape_strong = tape["level"] == "strong"
    tape_at_least_firm = tape["level"] in ("strong", "firm")
    money_weak = money["level"] == "weak"
    money_not_weak = money["level"] != "weak"
    money_strong = money["level"] == "strong"
    effective_spread = today["activeOpportunityShare"] >= 0.12 and today["strongMoneyShare"] >= 0.08
    broad_spread = expansion["level"] == "broad"
    high_heat = today["nearLimitUpCount"] >= 10 or (today["highGainCount"] >= 25 and today["highTurnoverCount"] >= 20)
    intersection = (limit_evidence or {}).get("intersection")
    yesterday_hot = (limit_evidence or {}).get("yesterdayHotLimit")
    limit_spread = bool(intersection and (intersection["top100LimitUpCount"] >= 6 or intersection["top100NearLimitUpCount"] >= 10))
    front_limit_hot = bool(intersection and (intersection["top20LimitUpCount"] >= 3 or intersection["top50LimitUpCount"] >= 6))
    limit_height_confirmed = bool(intersection and (intersection["top100Board2PlusCount"] >= 3 or intersection["top100MaxBoardHeight"] >= 3))
    yesterday_limit_weak = bool(
        yesterday_hot and yesterday_hot["count"] >= 3
        and yesterday_hot.get("failedOrWeakRate") is not None and yesterday_hot["failedOrWeakRate"] >= 0.5
    )
    severe_risk_shrink = (
        risk_pressure["level"] == "severe" and total_shrank
        and expansion["level"] != "broad" and money["level"] != "strong"
    )

    _push_if(signals, total_expanded, f"热榜池较上一日扩张 {comparison['totalChange1d']} 只")
    _push_if(warnings, total_shrank, f"热榜池较上一日收缩 {abs(comparison.get('totalChange1d') or 0)} 只")
    _push_if(warnings, risk_level == "高" and not tape_weak and not money_weak,
             "风险等级高，但上涨和成交承接尚未破坏，按阶段主方向处理")

    retreat = (
        severe_risk_shrink
        or (yesterday_limit_weak and risk_elevated and (tape_weak or money_weak))
        or (risk_elevated and (tape_weak or money_weak))
        or (risk_pressure["level"] == "severe" and continuity["level"] == "weak"
            and today["upRatio"] < 0.52 and money["level"] != "strong")
        or (total_shrank and expansion["level"] == "scarce" and today["upRatio"] < 0.5 and (risk_elevated or money_weak))
    )
    if retreat:
        return {"stage": "退潮", "riskLevel": risk_level, "signals": signals,
                "warnings": warnings or ["风险状态占比偏高，先按防守阶段处理"]}

    climax = tape_strong and money_not_weak and (
        (money_strong and high_heat and broad_spread)
        or (front_limit_hot and limit_height_confirmed and today["crowdedShare"] >= 0.16 and broad_spread)
        or (today["nearLimitUpCount"] >= 8 and today["crowdedShare"] >= 0.18 and broad_spread)
        or (today["crowdedShare"] >= 0.28 and today["activeOpportunityShare"] >= 0.22)
    )
    if climax:
        return {"stage": "高潮", "riskLevel": risk_level,
                "signals": signals or ["前排高涨幅与高位拥挤同时增加"],
                "warnings": warnings or ["热度强但追击赔率下降，注意高位兑现风险"]}

    ferment = (
        (expansion["level"] == "broad" or effective_spread or (limit_spread and today["activeOpportunityShare"] >= 0.12))
        and tape_at_least_firm and money_not_weak
    )
    if ferment:
        return {"stage": "发酵", "riskLevel": risk_level,
                "signals": signals or ["强资确认与点火观察形成有效扩散"], "warnings": warnings}

    start = (
        (total_expanded or expansion["level"] == "improving" or comparison["newTop100Count"] >= 25
         or ((intersection or {}).get("top100NearLimitUpCount") or 0) >= 3)
        and today["upRatio"] >= 0.42 and money_not_weak and not tape_weak
    )
    if start:
        return {"stage": "启动", "riskLevel": risk_level,
                "signals": signals or ["热榜新增和机会状态开始改善"], "warnings": warnings}

    return {"stage": "冰点", "riskLevel": risk_level,
            "signals": signals or ["热榜机会状态尚未形成有效扩散"],
            "warnings": warnings or ["强资确认与点火观察偏少，等待下一轮扩散确认"]}


def _calculate_confidence(stage: str, signals: list[str], warnings: list[str]) -> int:
    # TS: calculateConfidence L1269-1273
    base = _STAGE_CONFIDENCE_BASE.get(stage, 58)
    adjustment = min(18, len(signals) * 5) - min(12, len(warnings) * 3)
    return max(45, min(90, base + adjustment))


def compute_hotlist_sentiment(
    stocks: list[dict],
    yesterday: dict | None = None,
    day_before: dict | None = None,
    market_data: dict | None = None,
    top_n: int | None = None,
) -> dict:
    # TS: HotListSentimentAnalyzer.analyze L1276-1303 的 Python 等价主入口
    sorted_stocks = sort_rows(stocks)
    yesterday_rows = sort_rows((yesterday or {}).get("rows") or [])
    day_before_rows = sort_rows((day_before or {}).get("rows") or [])
    # 规则标记幂等补齐（join 层已注入的行不动；golden fixture 这类只有行情字段的输入按
    # derive_fallback_row_signals 等价补齐），保证规则引擎读到同一套判据。
    annotate_rows_with_signals(sorted_stocks)
    annotate_rows_with_signals(yesterday_rows)
    annotate_rows_with_signals(day_before_rows)
    top_n = top_n if top_n and top_n > 0 else None
    sample_size = _resolve_sample_size(sorted_stocks, top_n)
    layers = build_layer_metrics(stocks)
    comparison = build_comparison(stocks, yesterday_rows, day_before_rows, top_n)
    # TS buildComparison 从 snapshot 注入 tradingDate（L833/L836）；Python build_comparison 只收 rows，
    # tradingDate 在编排层回填（Task 3 审查裁决落实，snapshot 缺失时保持 None）。
    if comparison.get("yesterday") and (yesterday or {}).get("tradingDate") is not None:
        comparison["yesterday"]["tradingDate"] = (yesterday or {}).get("tradingDate")
    if comparison.get("dayBefore") and (day_before or {}).get("tradingDate") is not None:
        comparison["dayBefore"]["tradingDate"] = (day_before or {}).get("tradingDate")
    limit_evidence = build_limit_evidence(sorted_stocks, yesterday_rows, top_n, market_data)
    stage_evidence = resolve_stage(comparison, layers, limit_evidence)
    confidence = _calculate_confidence(stage_evidence["stage"], stage_evidence["signals"], stage_evidence["warnings"])

    status_source = {"displayStatus": 0, "fallback": 0}
    for row in sorted_stocks:
        resolve_row_signals(row, sorted_stocks, status_source)

    missing_evidence: list[str] = []
    if not market_data:
        missing_evidence.append("marketData")
    if not yesterday_rows:
        missing_evidence.append("yesterday")

    return {
        "stage": stage_evidence["stage"],
        "riskLevel": stage_evidence["riskLevel"],
        "confidence": confidence,
        # TS: getEmotionCycleStageSummary —— 未知阶段回退启动 summary
        "summary": _STAGE_SUMMARY.get(stage_evidence["stage"]) or _STAGE_SUMMARY["启动"],
        "metrics": {
            "topN": sample_size,
            "layers": layers,
            "comparison": comparison,
            "limitEvidence": limit_evidence,
            "transitionCounts": build_transition_counts(sorted_stocks),
        },
        "turnover": compute_turnover(sorted_stocks, yesterday_rows),
        "signals": stage_evidence["signals"],
        "warnings": stage_evidence["warnings"],
        "statusSourceCounts": status_source,
        "missingEvidence": missing_evidence,
    }
