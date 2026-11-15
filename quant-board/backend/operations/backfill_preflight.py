# -*- coding: utf-8 -*-
"""回填前置检查：依赖链存档健康度（2026-11-16，11-12 事故复盘裁决落地）。

背景（docs/hotlist-jev/sector-nodes-gain10-backfill-void-incident-20261116.md）：
2026-11-12 00:27 的 sector_nodes --backfill 在「gain10 取不到（固定 15 根棒）+ TDX
不可用」下把 ≤11-04 历史档静默清空；随后 relay v8 换代回填又把降级语料烙进 20 个
交易日的 LLM 答案。两次事故的直接诱因都是**回填前没有核对依赖链存档健康度**。

定位（fail-visible 边界，skill 强制边界 + 不可逆覆盖豁免）：
- 本模块只做**读侧结构化报告**：逐日列出上游 final/THS 池/依赖档/增益可达性状态，
  质量问题全部透出，不静默、不伪造 0；
- 确定性重算链（sector_nodes）重跑本身就是修复手段 → 只报告不阻断；
- **烧 token 的 LLM 重放（relay）且依赖档坏账时默认阻断**——重跑不可逆（原答案
  将被非确定性覆盖且语料是降级版，烧了 token 也产不出完整口径）；`--allow-unhealthy`
  显式越过（操作者知情决策，越过时报告仍完整落 stdout）。

供接线：sector_nodes --backfill / jev_relay_index --relay-day --force /
market_cycle --backfill。生产 schedule 单日路径不接（零开销、且单日依赖当日健康
由盘后链自身的 fail-visible 字段披露）。
"""
from __future__ import annotations

from typing import Any

EXIT_BLOCKED = 3   # 阻断退出码（区别于 argparse 的 2 / 运行失败的 1）


def _final_found(db: Any, date: str) -> bool:
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields.stocks.code": 1})
    return any(f.get("stocks") for f in (doc or {}).get("fields") or [])


def _ths_found(db: Any, date: str, dataset_id: str) -> bool:
    from backend.operations.jev_label_jiuyan import _ths_failed_items
    _items, found = _ths_failed_items(db, date, dataset_id)
    return found


def _ledger_rows(db: Any, date: str, version: str) -> dict[str, Any] | None:
    """板块节点档健康摘要；档缺失/非 ok/版本不符 → None（消费方=梯队表将回退口径）。"""
    doc = db["hotlist_jev_sector_nodes"].find_one(
        {"_id": f"{date}:SECTOR_NODES"},
        {"version": 1, "status": 1, "rows.board": 1})
    if doc is None or doc.get("status") != "ok" \
            or str(doc.get("version") or "") != version:
        return None
    return {"rows": len(doc.get("rows") or [])}


def _gain_sample(db: Any, date: str, dataset_id: str, sample: int = 3) -> dict[str, Any]:
    """增益可达性抽检（11-12 事故的直接信号）：取当日 final 前 sample 只股跑
    fetch_gains10，None 占比 >0.5 = TDX 不可用或棒窗覆盖不到 → 回填将全板块跳过。"""
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"}, {"fields.stocks.code": 1})
    codes: list[str] = []
    for f in (doc or {}).get("fields") or []:
        for s in f.get("stocks") or []:
            c = str(s.get("code") or "")[-6:]
            if c and c not in codes:
                codes.append(c)
        if len(codes) >= sample:
            break
    if not codes:
        return {"tried": 0, "noneRatio": None, "reason": "final 无个股（跳过抽检）"}
    from backend.operations.tdx_daily_bars import fetch_gains10
    gains = fetch_gains10(codes[:sample], date)
    tried = len(codes[:sample])
    none_n = sum(1 for v in gains.values() if v is None)
    return {"tried": tried, "noneRatio": round(none_n / tried, 2) if tried else None}


def sector_nodes_preflight(db: Any, dates: list[str], dataset_id: str = "",
                           *, gain_sample_dates: int = 2,
                           allow_unhealthy: bool = False) -> dict[str, Any]:
    """sector_nodes --backfill 前置检查。确定性重算：只报告不设档阻断，除
    增益不可达（重跑=事故复现：全板块被跳过、好档被近空档覆盖）默认阻断。

    返回 {chain, dates, missingFinal, missingThs, existingVoid, gainSample,
    blockers, warnings, allowUnhealthy}；blockers 非空且未 allow_unhealthy → 调用方退出。
    """
    dates = sorted(dates)
    missing_final = [d for d in dates if not _final_found(db, d)]
    checkable = [d for d in dates if d not in missing_final]
    missing_ths = [d for d in checkable if not _ths_found(db, d, dataset_id)]
    # 已有档「空档/骤降」签名（11-12 事故产物）：final/THS 在场但档 0 行——重跑即修复，
    # 只透出供审计，不阻断
    existing_void = []
    for d in checkable:
        doc = db["hotlist_jev_sector_nodes"].find_one(
            {"_id": f"{d}:SECTOR_NODES"}, {"rows.board": 1})
        if doc is not None and not (doc.get("rows") or []):
            existing_void.append(d)
    # 增益可达性：抽最早 gain_sample_dates 个 checkable 日（深度最大处最易失败）
    gain_sample = {d: _gain_sample(db, d, dataset_id) for d in checkable[:gain_sample_dates]}
    blockers: list[str] = []
    for d, g in gain_sample.items():
        if g.get("noneRatio") is not None and g["noneRatio"] > 0.5:
            blockers.append(f"{d} gain10 抽检 {g['noneRatio']:.0%} 不可算"
                            f"（TDX 日线不可用或棒窗覆盖不到）——重跑将复现 11-12 事故"
                            f"（全板块跳过、覆盖好档）")
    warnings = []
    if missing_final:
        warnings.append(f"{len(missing_final)} 日无韭研 final，将被跳过: {missing_final[:8]}"
                        + ("…" if len(missing_final) > 8 else ""))
    if missing_ths:
        warnings.append(f"{len(missing_ths)} 日 THS 池缺失，该日将整日 degraded（不可考）: "
                        f"{missing_ths[:8]}" + ("…" if len(missing_ths) > 8 else ""))
    if existing_void:
        warnings.append(f"{len(existing_void)} 日已有档为 0 行（11-12 事故签名，重跑即修复）: "
                        f"{existing_void[:8]}" + ("…" if len(existing_void) > 8 else ""))
    return {"chain": "sector_nodes", "dates": len(dates),
            "missingFinal": missing_final, "missingThs": missing_ths,
            "existingVoid": existing_void, "gainSample": gain_sample,
            "blockers": blockers, "warnings": warnings,
            "allowUnhealthy": allow_unhealthy}


def relay_preflight(db: Any, dates: list[str], *,
                    ledger_version: str, allow_unhealthy: bool = False) -> dict[str, Any]:
    """relay（jev_relay_index --force 重放）前置检查。LLM 重放不可逆：任一目标日
    板块节点档缺失/非 ok/版本不符/0 行 → 梯队表龙一全部回退区间高度口径，烧 token
    也只能产出降级语料 → 默认阻断（--allow-unhealthy 显式越过）。
    """
    dates = sorted(dates)
    missing_final = [d for d in dates if not _final_found(db, d)]
    ledger_bad: list[dict[str, Any]] = []
    for d in dates:
        health = _ledger_rows(db, d, ledger_version)
        if health is None:
            ledger_bad.append({"date": d, "reason": "节点档缺失/非 ok/版本不符"})
        elif health["rows"] == 0:
            ledger_bad.append({"date": d, "reason": "节点档 0 行（11-12 事故签名）"})
    blockers = []
    if ledger_bad:
        summary = "; ".join(f"{x['date']}({x['reason']})" for x in ledger_bad[:6]) \
            + ("…" if len(ledger_bad) > 6 else "")
        blockers.append(f"{len(ledger_bad)} 日板块节点档不可锚定 → 梯队表龙一回退口径、"
                        f"叙事语料降级，重放将把降级答案烙进存档: {summary}")
    warnings = []
    if missing_final:
        warnings.append(f"{len(missing_final)} 日无韭研 final，将被跳过: {missing_final[:8]}"
                        + ("…" if len(missing_final) > 8 else ""))
    return {"chain": "relay", "dates": len(dates), "missingFinal": missing_final,
            "ledgerBad": ledger_bad, "blockers": blockers, "warnings": warnings,
            "allowUnhealthy": allow_unhealthy}


def market_cycle_preflight(db: Any, dates: list[str], dataset_id: str = "",
                           *, allow_unhealthy: bool = False) -> dict[str, Any]:
    """market_cycle --backfill 前置检查（报告型）：其回填链自带 covering fetchers
    （v13 gain10 全缺不降级），故不设档阻断，只透出上游存档状态供审计。"""
    dates = sorted(dates)
    missing_final = [d for d in dates if not _final_found(db, d)]
    checkable = [d for d in dates if d not in missing_final]
    missing_ths = [d for d in checkable if not _ths_found(db, d, dataset_id)]
    warnings = []
    if missing_final:
        warnings.append(f"{len(missing_final)} 日无韭研 final: {missing_final[:8]}"
                        + ("…" if len(missing_final) > 8 else ""))
    if missing_ths:
        warnings.append(f"{len(missing_ths)} 日 THS 池缺失: {missing_ths[:8]}"
                        + ("…" if len(missing_ths) > 8 else ""))
    return {"chain": "market_cycle", "dates": len(dates), "missingFinal": missing_final,
            "missingThs": missing_ths, "blockers": [], "warnings": warnings,
            "allowUnhealthy": allow_unhealthy}
