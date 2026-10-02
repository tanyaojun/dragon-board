# -*- coding: utf-8 -*-
"""SP3+ D-jev：jev 第二口径 vs 规则 rawStage 分歧挖掘（只读诊断；jev 是调试信号不是判决）。

D-jev1 一致率矩阵：jev frame_stage/sequence_stage（五档）× 规则 rawStage（五档），逐槽；
        日级 day_stage vs EOD rawStage。
D-jev2 分歧日清单：逐槽列 jev 档/温度 vs 规则档/分数，供用户盘后对原始证据复核
        （仲裁权=用户+前向盘面，章程 §8-2 纪律；分歧=调试信号不是判决）。
规则枚举映射：启动=start 发酵=ferment 高潮=climax 退潮=retreat 冰点=ice。
产物 data/reports/phase-monitor/jev-divergence.json。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

OUT = Path("data/reports/phase-monitor/jev-divergence.json")
CN2EN = {"启动": "start", "发酵": "ferment", "高潮": "climax", "退潮": "retreat", "冰点": "ice"}
TIERS = ["ice", "start", "ferment", "climax", "retreat"]


def main() -> int:
    month_filter = None
    if "--month" in sys.argv:
        month_filter = sys.argv[sys.argv.index("--month") + 1]
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]

    # ① jev 槽位文档（status=ok）
    jev_slots: dict[tuple[str, str], dict] = {}
    jev_days: dict[str, dict] = {}
    for doc in db["hotlist_jev_sentiment"].find({"status": "ok"}):
        date, slot = str(doc.get("tradingDate") or ""), str(doc.get("slotTime") or "")
        if month_filter and not date.startswith(month_filter):
            continue
        ans = doc.get("answers") or {}
        date, slot = str(doc.get("tradingDate") or ""), str(doc.get("slotTime") or "")
        if doc.get("kind") == "slot" and ans.get("frame_stage"):
            jev_slots[(date, slot)] = {
                "frame": ans["frame_stage"].get("choice"),
                "sequence": (ans.get("sequence_stage") or {}).get("choice"),
                "confidence": (ans.get("frame_stage") or {}).get("confidence"),
                "temperature": (doc.get("scores") or {}).get("temperature"),
                "crowding": (doc.get("scores") or {}).get("crowding"),
            }
        elif doc.get("kind") == "day" and ans.get("day_stage"):
            jev_days[date] = {"dayStage": ans["day_stage"].get("choice"),
                              "dayPattern": (ans.get("day_pattern") or {}).get("choice")}

    # ② 规则槽位 rawStage（五档）+ 情绪分
    rules_slots: dict[tuple[str, str], dict] = {}
    rules_eod: dict[str, dict] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "rawStage": 1, "emotionScore.score": 1},
    ):
        raw = CN2EN.get(str(doc.get("rawStage") or ""))
        es = doc.get("emotionScore")
        score = float(es["score"]) if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        entry = {"rawStage": raw, "score": score}
        if str(doc.get("slotTime") or "") == "EOD":
            rules_eod[str(doc.get("tradingDate") or "")] = entry
        else:
            rules_slots[(str(doc.get("tradingDate") or ""), str(doc.get("slotTime")))] = entry

    # ③ D-jev1 槽位一致率矩阵
    def matrix(stage_key: str) -> dict:
        mat = {r: {j: 0 for j in TIERS} for r in TIERS}
        n = 0
        for (d, s), jev in sorted(jev_slots.items()):
            rr = rules_slots.get((d, s))
            if not rr or not rr.get("rawStage") or not jev.get(stage_key):
                continue
            mat[rr["rawStage"]][jev[stage_key]] += 1
            n += 1
        agree = sum(mat[t][t] for t in TIERS)
        return {"n": n, "agreeRate": round(agree / n, 4) if n else None, "matrix": mat}

    # ④ D-jev2 分歧清单（按日期排序）
    div_rows = []
    for (d, s), jev in sorted(jev_slots.items()):
        rr = rules_slots.get((d, s))
        if not rr or not rr.get("rawStage") or not jev.get("frame"):
            continue
        agree = rr["rawStage"] == jev["frame"]
        div_rows.append({
            "date": d, "slot": s, "agree": agree,
            "jevFrame": jev["frame"], "jevSequence": jev.get("sequence"),
            "rulesStage": rr["rawStage"], "rulesScore": rr.get("score"),
            "temperature": jev.get("temperature"), "crowding": jev.get("crowding"),
            "jevConfidence": jev.get("confidence"),
        })
    div_only = [r for r in div_rows if not r["agree"]]
    diverge_shapes = Counter((r["rulesStage"], r["jevFrame"]) for r in div_only)

    day_rows = []
    for d, jd in sorted(jev_days.items()):
        re = rules_eod.get(d)
        if re and re.get("rawStage"):
            day_rows.append({"date": d, "jevDayStage": jd.get("dayStage"),
                             "jevDayPattern": jd.get("dayPattern"),
                             "rulesEodStage": re["rawStage"],
                             "agree": re["rawStage"] == jd.get("dayStage")})

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "D-jev 分歧挖掘：jev 第二口径 vs 规则 rawStage（分歧=调试信号，仲裁=用户+前向盘面）",
                 "note": "当前仅覆盖 jev 已落库日期（全窗回放待 JEV_CF_TOKEN 后执行）"},
        "slotFrame": matrix("frame"),
        "slotSequence": matrix("sequence"),
        "dayLevel": {"n": len(day_rows),
                     "agreeRate": round(sum(1 for r in day_rows if r["agree"]) / len(day_rows), 4) if day_rows else None,
                     "rows": day_rows},
        "divergenceShapes": {f"rules:{k[0]} -> jev:{k[1]}": v for k, v in diverge_shapes.most_common()},
        "divergenceRows": div_only,
        "allRows": div_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"jevSlotDocs": len(jev_slots), "jevDayDocs": len(jev_days),
                      "frameMatrix": report["slotFrame"], "sequenceMatrix": report["slotSequence"],
                      "dayAgree": report["dayLevel"]["agreeRate"],
                      "topDivergences": report["divergenceShapes"]}, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
