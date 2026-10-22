# -*- coding: utf-8 -*-
"""题材层 pilot 离线评估（**零 jev 调用**，只读库 + 只读历史结局）。

做什么：把 `hotlist_jev_theme_leader_labels` 里某交易日的龙头投喂结果，与**次一交易日**
`jiuyan_action:{next}:final` 的真实封板集合 join，回填 `outcomeSealedNextDay`，并给出
同桶对照指标（题集 v1 / §6 验收门槛的口径）。

不做什么：
- 不调用任何模型（AGENTS §1.2-7）；不改题集/叙事；
- 不因样本量不足而下结论：验收要求 ≥20 个交易日（≈240 龙头样本），
  单日只作「观察」，脚本会显式打印该项。

口径要点（与 `theme_leader_baseline` / `theme_leader_ammo` 同源，不自造）：
- 封板集合 = `sealed_and_info()`（触板−THS炸板二分）；
- 次日 THS 池缺失 → 该末日结局为未知（`None`），fail-visible，不计入率；
- 历史基准率 = 投喂时记录的同窗口 `build_rows(start, end)` + `combo_rates`，
  逐级回退顺序与 `baseline_line` 一致（组合桶 → 连板高度桶 → 板块家数桶 → 总体）；
- 模型单点概率 = `theme_leader_ammo.continue_point_estimate()`（档位中值加权）。

用法：
  ./.venv/Scripts/python.exe scripts/theme_leader_pilot_eval.py --date 2026-10-19
  ./.venv/Scripts/python.exe scripts/theme_leader_pilot_eval.py --date 2026-10-19 --write-outcome

注意：进程内其他模块（div-events 等）可能向 stdout 打噪声行，**JSON 消费者请从首个 `{` 起解析**
（`json.loads(stdout[stdout.index('{'):])`，与 `schedule._settle_previous_theme_leader_day` 同口径）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hotlist.theme_leader_ammo import (  # noqa: E402
    board_count_bucket,
    combo_key,
    combo_rates,
    continue_point_estimate,
    group_rates,
    streak_bucket,
)
from backend.operations.theme_leader_baseline import (  # noqa: E402
    build_rows,
    sealed_and_info,
    trading_dates,
)

COLLECTION = "hotlist_jev_theme_leader_labels"
# 验收门槛（预登记 §6）：同桶高/低概率组真实连板率差 ≥ 15pp，且 Brier 优于同桶基线
ACCEPTANCE_GAP_PP = 15.0
ACCEPTANCE_MIN_TRADING_DAYS = 20


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()


def next_trading_date(db, date: str) -> str | None:
    """韭研 final 文档交易日轴上的下一个交易日（无则 None，fail-visible）。"""
    end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
    later = [d for d in trading_dates(db, date, end) if d > date]
    return later[0] if later else None


def baseline_rate_lookup(rows: list[dict], min_combo_n: int = 5):
    """同桶基准率查询（逐级回退顺序与 baseline_line 完全一致）+ 总体率。"""
    combos = combo_rates(rows, min_combo_n)
    streaks = group_rates(rows, lambda r: streak_bucket(r.get("streak")))
    counts = group_rates(rows, lambda r: board_count_bucket(r.get("boardN")))
    n_all = len(rows)
    cont_all = sum(1 for r in rows if r.get("continued"))
    overall = (cont_all / n_all) if n_all else None

    def lookup(baseline_bucket: str) -> tuple[float | None, str, int]:
        """`baseline_bucket` = 投喂时存的原始结构 JSON（审计用）。

        注意：组合桶的查键必须用 `combo_key()` 从结构现算（`streak3|n5-7|early<=10:00` 这类串），
        不能拿结构 JSON 当键——拿错会静默退化成“只用连板高度档”，让同桶对照失真。
        """
        try:
            bucket = json.loads(baseline_bucket or "{}")
        except json.JSONDecodeError:
            bucket = {}
        key = combo_key(bucket) if bucket else ""
        combo = combos.get(key)
        if combo:
            return combo["rate"], f"同桶[{key}]", combo["n"]
        sb = streaks.get(streak_bucket(bucket.get("streak")))
        if sb:
            return sb["rate"], f"连板高度[{streak_bucket(bucket.get('streak'))}]", sb["n"]
        cb = counts.get(board_count_bucket(bucket.get("boardN")))
        if cb:
            return cb["rate"], f"板块家数[{board_count_bucket(bucket.get('boardN'))}]", cb["n"]
        return overall, "总体", n_all

    return lookup


def _metrics(samples: list[dict]) -> dict:
    """单代际指标（同桶基线对照 / 分档 / 同桶聚合）。样本不足不下结论由调用方把关。"""
    n = len(samples)
    m: dict = {"n": n, "actualContinue": sum(1 for s in samples if s["outcome"]),
               "actualRate": (sum(1 for s in samples if s["outcome"]) / n) if n else None}
    scored = [s for s in samples if s["modelProb"] is not None]
    m["scored"] = len(scored)
    m["gatedShare"] = (sum(1 for s in samples if s.get("gate")) / n) if n else None
    m["insufficientShare"] = (sum(1 for s in samples if s["modelProb"] is None) / n) if n else None
    if scored:
        m["meanModelProb"] = sum(s["modelProb"] for s in scored) / len(scored)
        m["brierModel"] = sum((s["modelProb"] - int(s["outcome"])) ** 2 for s in scored) / len(scored)
        bl = [s for s in scored if s["baselineRate"] is not None]
        if bl:
            m["meanBaselineRate"] = sum(s["baselineRate"] for s in bl) / len(bl)
            m["brierBaseline"] = sum((s["baselineRate"] - int(s["outcome"])) ** 2 for s in bl) / len(bl)
            m["brierDelta"] = m["brierModel"] - m["brierBaseline"]
        high = [s for s in scored if s["choice"] == "high_ge65"]
        low = [s for s in scored if s["choice"] in ("low_25_45", "verylow_lt25")]
        m["highGroup"] = {"n": len(high),
                          "rate": (sum(1 for s in high if s["outcome"]) / len(high)) if high else None}
        m["lowGroup"] = {"n": len(low),
                         "rate": (sum(1 for s in low if s["outcome"]) / len(low)) if low else None}
        if high and low and m["highGroup"]["rate"] is not None and m["lowGroup"]["rate"] is not None:
            m["highLowGapPp"] = (m["highGroup"]["rate"] - m["lowGroup"]["rate"]) * 100
        by_bucket: dict[str, list[dict]] = {}
        for s in scored:
            # 同桶键聚合（不是结构 JSON 原串：按原串聚合会碎成 n=1 且与对照表不同粒度）
            by_bucket.setdefault(s.get("bucketKey") or "", []).append(s)
        m["perBucket"] = [{
            "bucket": k, "n": len(v),
            "actualRate": sum(1 for s in v if s["outcome"]) / len(v),
            "meanModelProb": sum(s["modelProb"] for s in v) / len(v),
            "codes": [s["code"] for s in v],
        } for k, v in sorted(by_bucket.items(), key=lambda kv: -len(kv[1]))]
    return m


def _next_day_board_n(db, board: str | None, next_date: str | None) -> int | None:
    """次日该板块封板家数（题材延续性结局锚；次日 final 缺失 → None，不伪造 0）。

    域假设（2026-10-23 实证）：韭研 final 只落当日有封板的板块（fields 内 stocks 恒非空，
    10-21→10-22 有 7 个零封板板块整组消失）——按 name 精确匹配查无 = 当日 0 家封板，
    返回 0 是事实不是伪造。"""
    if not board or not next_date:
        return None
    doc = db["jiuyan_action"].find_one({"_id": f"{next_date}:final"}, {"fields": 1}) or {}
    for field in doc.get("fields") or []:
        if str(field.get("name") or "") == str(board):
            return len([s for s in (field.get("stocks") or []) if s])
    return 0 if doc.get("fields") else None


def evaluate(db, date: str, write_outcome: bool = False) -> dict:
    col = db[COLLECTION]
    labels_all = list(col.find({"tradingDate": date}))
    # v3：status=skipped（非题材粗分桶，v3 起不纳入判定范围）不足 degraded 也不进名册——
    # 单独计数透出（它们本来就没有答案，混进 degradedShare 会把「按设计排除」读成「通道故障」）。
    labels = [d for d in labels_all if d.get("status") != "skipped"]
    not_theme_skipped = len(labels_all) - len(labels)
    if not labels:
        return {"ok": False,
                "error": f"{date} 无投喂记录（先跑 theme_leader_label）",
                "date": date, "notThemeSkipped": not_theme_skipped}

    nxt = next_trading_date(db, date)
    sealed_next = info_meta = None
    if nxt:
        sealed_next, _info, info_meta = sealed_and_info(db, nxt)

    rows: list[dict] = []
    skipped: list[str] = []
    for doc in labels:
        code = str(doc.get("code") or "")
        if sealed_next is None:
            outcome = None
            reason = f"次日 {nxt} 不可判定（THS 池缺失或次日文档未采）" if nxt else "无次日交易日数据"
        else:
            outcome = code in sealed_next
            reason = ""
        if outcome is None:
            skipped.append(f"{code}{doc.get('name') or ''}: {reason}")
        if write_outcome:
            board_n_next = _next_day_board_n(db, doc.get("board"), nxt)
            col.update_one({"_id": doc["_id"]}, {"$set": {
                "outcomeSealedNextDay": outcome,
                "outcomeBoardNNextDay": board_n_next,
                "outcomeMeta": {
                    "nextDate": nxt,
                    "source": f"jiuyan_action:{nxt}:final → sealed_and_info",
                    "thsPoolFound": bool(sealed_next is not None
                                            and (info_meta or {}).get("thsPoolFound")),
                    "computedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
            }})
        rows.append({"doc": doc, "outcome": outcome})

    meta = (labels[0].get("baselineMeta") or {})
    base = build_rows(db, meta.get("start"), meta.get("end")) if meta.get("start") else {"rows": []}
    lookup = baseline_rate_lookup(base["rows"])

    # P2 修复（2026-10-20 review）：degraded（jev 通道没答上来，answers={}）不得混进模型
    # 指标口径——与 _label_one「不得把『没答上来』写成 insufficient」同一原则；
    # 指标只取 status=ok，degraded 单独计数 degradedShare（fail-visible，不静默混入）。
    degraded_docs = [r["doc"] for r in rows
                     if r["doc"].get("status") not in (None, "ok")]
    ok_rows = [r for r in rows if r["doc"].get("status") in (None, "ok")]

    # 已封样本（进指标）与全量名册（进展示；未封也逐只列出，不因结局未知而隐去）
    samples = [_sample_row(r["doc"], bool(r["outcome"]), lookup)
               for r in ok_rows if r["outcome"] is not None]
    roster = [_sample_row(r["doc"], None if r["outcome"] is None else bool(r["outcome"]), lookup)
              for r in rows]

    n = len(samples)
    actual = sum(1 for s in samples if s["outcome"])
    out: dict = {
        "ok": True,
        "date": date,
        "nextDate": nxt,
        "labeled": len(labels),
        "notThemeSkipped": not_theme_skipped,
        "evaluable": n,
        "skipped": skipped,
        "degradedCount": len(degraded_docs),
        "degradedShare": (len(degraded_docs) / len(rows)) if rows else None,
        "actualContinue": actual,
        "actualRate": (actual / n) if n else None,
        "baselineWindow": {"start": meta.get("start"), "end": meta.get("end"),
                           "rows": len(base["rows"])},
        "samples": samples,
        "roster": roster,
        # 形状契约：早返回（无次日/全体未封）也补齐全部键，摘要打印不得因缺键崩
        # （2026-10-20 实测：`--date 2026-10-20` 当日跑 → KeyError: mixedVersions）
        "versions": {}, "mixedVersions": False, "scored": 0, "perBucket": [],
        "origins": {}, "mixedOrigins": False,
        "degradedCount": 0, "degradedShare": None,
    }
    out["acceptance"] = {
        "minTradingDays": ACCEPTANCE_MIN_TRADING_DAYS,
        "minTradingDaysMet": False,
        "gapPpRequired": ACCEPTANCE_GAP_PP,
        "gapPpObserved": None,
        "verdict": "pilot 单日观察：样本远不足，只累积不下结论（预登记 §6）",
    }
    if not n:
        out["note"] = "无可判定样本：次日结局未知，按 fail-visible 不下任何结论"
        return out

    # 按来源分组：**回填样本不与前瞻混评**（H1 回填可能看到「当时还不存在」的语料 → 泄漏风险，
    # 预登记 §11）。单独出 `originMetrics`，合计指标只对 live 出，避免把泄漏当能力。
    origins: dict[str, list[dict]] = {}
    for s in samples:
        origins.setdefault(s.get("sampleOrigin") or "live", []).append(s)
    out["origins"] = {o: len(v) for o, v in origins.items()}
    out["mixedOrigins"] = len(origins) > 1
    if out["mixedOrigins"]:
        out["originMetrics"] = {o: _metrics(v) for o, v in origins.items()}
    samples_live = origins.get("live") or []
    samples_eval = samples_live if samples_live else samples

    # 按代际分组：**跨代不混评**（题集/判据换代后含义不同；v1 的 gate 字段不存在）
    versions: dict[str, list[dict]] = {}
    for s in samples_eval:
        versions.setdefault(s.get("questionSetVersion") or "unknown", []).append(s)
    out["versions"] = {ver: len(rows_v) for ver, rows_v in versions.items()}
    out["mixedVersions"] = len(versions) > 1
    if out["mixedVersions"]:
        out["versionMetrics"] = {ver: _metrics(rows_v) for ver, rows_v in versions.items()}
        out["note"] = ("本日存在多代际标签 → 只出各代际分组指标，**不给跨代合计**"
                       "（预登记：跨代不可比）")
        out["scored"] = sum(m["scored"] for m in out["versionMetrics"].values())
    else:
        out.update(_metrics(samples_eval))
    if out["mixedOrigins"]:
        out["note"] = ("含回填样本（sampleOrigin=backfill）：合计指标**只对 live 前瞻样本**出，"
                       "回填样本见 originMetrics（可能含语料泄漏，不得进验收）")

    out["tradingDaysCovered"] = 1
    out["acceptance"] = {
        "minTradingDays": ACCEPTANCE_MIN_TRADING_DAYS,
        "minTradingDaysMet": False,
        "gapPpRequired": ACCEPTANCE_GAP_PP,
        "gapPpObserved": out.get("highLowGapPp"),
        "verdict": "pilot 单日观察：样本远不足，只累积不下结论（预登记 §6）",
    }
    return out


def _sample_row(doc: dict, outcome: bool | None, lookup) -> dict:
    """单只样本行；`outcome=None` = 结局未封（fail-visible，不进指标）。"""
    ans = (doc.get("answers") or {}).get("leader_nextday_continue") or {}
    point, insuff = continue_point_estimate(ans.get("probabilities") or {})
    b_rate, b_label, b_n = lookup(doc.get("baselineBucket"))
    return {
        "code": doc.get("code"), "name": doc.get("name"), "board": doc.get("board"),
        "choice": ans.get("choice"),
        "modelProb": point, "insufficientMass": insuff,
        "baselineKey": doc.get("baselineKey"),
        "questionSetVersion": doc.get("questionSetVersion"),
        # 样本代际：live=当日挂链前瞻；backfill=事后补跑（可能看到当时不存在的语料 → 单独统计）
        "sampleOrigin": doc.get("sampleOrigin") or "live",
        "gate": (doc.get("gate") or {}).get("reason"),
        "baselineRate": b_rate, "baselineLevel": b_label, "baselineN": b_n,
        # v5：题材层三层判断（旧代文档 catalystStage 保留回读；不跨代映射）
        "themeSpeculationDepth": doc.get("themeSpeculationDepth"),
        "themeContinuation": doc.get("themeContinuation"),
        "leaderHeadroom": doc.get("leaderHeadroom"),
        "catalystStage": doc.get("catalystStage"),
        # 题材延续性结局锚：次日该板块封板家数（None=未回填/不可判）
        "outcomeBoardNNextDay": doc.get("outcomeBoardNNextDay"),
        # `bucket` = 结构 JSON（审计字段，不可当键）；`bucketKey` = 同桶键（与 baseline 对照同粒度）
        "bucket": doc.get("baselineBucket"),
        "bucketKey": doc.get("baselineKey") or _combo_key_of(doc),
        "structure": doc.get("structure"),
        "outcome": outcome,
    }


def _combo_key_of(doc: dict) -> str:
    """从结构现算同桶键（`structure` 是审计字段，混用会静默退化成只用连板高度档）。"""
    struct = doc.get("structure")
    if isinstance(struct, str):
        try:
            struct = json.loads(struct)
        except json.JSONDecodeError:
            struct = None
    return combo_key(struct) if isinstance(struct, dict) else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--write-outcome", action="store_true", help="把 outcomeSealedNextDay 回填到标签文档")
    ap.add_argument("--json", action="store_true", help="打印完整 JSON（默认打印摘要）")
    args = ap.parse_args()
    out = evaluate(_db(), args.date, write_outcome=args.write_outcome)
    if args.json or not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    rate = "结局未封" if out["actualRate"] is None else f"{out['actualRate']:.1%}"
    nxt = out["nextDate"] or "无次日交易日（结局未封）"
    print(f"[{out['date']} → 次日 {nxt}] 投喂 {out['labeled']} 只；可判定 {out['evaluable']} 只；"
          f"实际次日续板 {out['actualContinue']} 只（{rate}）")
    if out["skipped"]:
        print("  fail-visible 未判定：", "; ".join(out["skipped"]))
    if out["mixedOrigins"]:
        print(f"  来源分组：{out['origins']}（合计指标只算 live 前瞻；回填见 originMetrics）")
    if out["mixedVersions"]:
        print(f"  代际分组：{out['versions']}（跨代不混评，详见 --json 的 versionMetrics）")
    elif out.get("scored"):
        print(f"  模型均概率 {out.get('meanModelProb', 0):.1%}；同桶基线均 {out.get('meanBaselineRate', 0):.1%}；"
              f"Brier 模型 {out.get('brierModel', 0):.3f} vs 基线 {out.get('brierBaseline', 0):.3f}"
              f"（Δ{out.get('brierDelta', 0):+.3f}；正=模型更差）")
        hg, lg = out.get("highGroup") or {}, out.get("lowGroup") or {}
        print(f"  高概率档 n={hg.get('n', 0)} 实际 {(hg.get('rate') or 0):.1%} | "
              f"低概率档 n={lg.get('n', 0)} 实际 {(lg.get('rate') or 0):.1%} | "
              f"差 {out.get('highLowGapPp', float('nan')):.1f}pp（门槛 {ACCEPTANCE_GAP_PP}pp）")
        print(f"  insufficient 占比 {out['insufficientShare']:.1%}"
              + (f"（其中确定性门强制 {out['gatedShare']:.1%}）" if out.get("gatedShare") else ""))
    print("\n逐只明细（模型 vs 同桶基线 vs 实际；未封也列出）：")
    for s in out.get("roster") or []:
        prob = "insufficient" if s["modelProb"] is None else f"{s['modelProb']:.2f}"
        b = "n/a" if s["baselineRate"] is None else f"{s['baselineRate']:.2f}({s['baselineLevel']},n={s['baselineN']})"
        print(f"  {str(s['code']):6s} {str(s['name'] or ''):6s} {str(s['board'] or ''):8s} "
              f"模型 {prob:12s} 基线 {b:34s} 实际 "
              f"{'未封' if s['outcome'] is None else ('续板' if s['outcome'] else '未续')} "
              f"深度={s.get('themeSpeculationDepth')} 延续={s.get('themeContinuation')} "
              f"空间={s.get('leaderHeadroom')} 次日板块家数={s.get('outcomeBoardNNextDay')}")
    if out.get("perBucket"):
        print("\n同桶聚合：")
        for pb in out["perBucket"]:
            print(f"  {pb['bucket']}  n={pb['n']} 实际 {pb['actualRate']:.1%} 模型均 {pb['meanModelProb']:.1%} {pb['codes']}")
    print(f"\n验收：{out['acceptance']['verdict']}")


if __name__ == "__main__":
    main()
