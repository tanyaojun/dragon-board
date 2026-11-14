# -*- coding: utf-8 -*-
"""竞价试盘源合同定案探针（2026-11-14c 预登记，勘察文档 auction-trial-source-survey §5）。

目的：下一交易日分两个时段验证 KPL 盯盘「试盘」页签（Type=7）三件事：
  A 窗内实时（09:15–09:25）：实时 DaBanList Type=7 是否有数据、行格式（数组位 vs cell）；
  B 窗尾留存（09:26–09:30）：竞价结束后实时行是否留存（决定生产采集可否压到窗尾拿
    已定格完整快照，仍在 live 消费窗内）；
  C 历史回看（与 B 同次运行）：HisDaBanList Type=7 + Day=上一交易日 是否生效
    （决定历史日试盘原料可否盘后补拉，频控放宽）。

红线 9 预算（单日分段门控、无重试循环）：
- A/B/C 各 ≤1 发/日；分段按当前时刻自动选择（A 时段只发 A；B 时段发 B+C）；
  其余时刻一律拒绝实弹（窗外/周末列表空无法区分「无数据」vs「窗外清空」，
  11-14 周六两发空已证明，禁止盲探）；
- 当日幂等门：dump 文件已存在 → 拒绝再发（提示读已有 raw）；
- ≥2s 间隔由 kpl_ranking_service._post_form 锁保证；
- 空结果/参数错一律结构化记录后停止，禁止追加候选或重发；
- 定案优先路径 = MITM 对照 App 真实请求，本探针是兜底验证。

用法：
  dry（默认，零外呼）：  ./.venv/Scripts/python.exe scripts/auction_trial_contract_probe.py
  实弹（对应时段）：      ... --confirm-budget
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.kpl_ranking_service import (  # noqa: E402
    _HOST_HISTORY, _HOST_REALTIME, _UA_STOCKS, _post_form,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS  # noqa: E402

SEG_A = ("09:15", "09:25")        # 窗内实时（半成品快照，行在竞价中更新）
SEG_BC = ("09:26", "09:30")       # 窗尾留存 + 历史回看
PROBE_BUDGET = {"A": 1, "B": 1, "C": 1}   # 红线 9：各 1 发/日
DUMP_DIR = Path("data/backups/probe")


def _hhmm_now() -> str:
    return time.strftime("%H:%M")


def _in_seg(seg: tuple[str, str]) -> bool:
    return seg[0] <= _hhmm_now() < seg[1]


def _creds() -> dict:
    return {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}


def _summarize(tag: str, data: dict) -> dict:
    rows = data.get("list") or []
    d = data.get("data") if isinstance(data.get("data"), dict) else {}
    sl = d.get("stock_list") or {}
    hit = None
    for r in rows:
        if isinstance(r, list) and r and str(r[0]) == "605255":
            hit = [c.get("text") if isinstance(c, dict) else c for c in r]
            break
    return {"candidate": tag, "errcode": data.get("errcode"),
            "keys": list(data.keys())[:12],
            "day_echo": data.get("day") or d.get("date"),
            "n_rows": len(rows) or len(sl.get("list") or []),
            "head_sort_keys": [h.get("sort_key") for h in (sl.get("head_info") or [])],
            "row_605255": hit}


def _fire(tag: str, host: str, params: dict) -> dict:
    try:
        return _summarize(tag, _post_form(host, params, _UA_STOCKS))
    except Exception as exc:  # noqa: BLE001 — 结构化记录后停止，不重试
        return {"candidate": tag, "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser(description="竞价试盘源合同定案探针")
    ap.add_argument("--confirm-budget", action="store_true",
                    help="实弹护栏（缺省 dry 零外呼，AGENTS §1.2-7 同款纪律）")
    ap.add_argument("--prev-trade-date", default=None,
                    help="候选 C 的 Day（缺省今日前一交易日，需人工指定 YYYY-MM-DD）")
    args = ap.parse_args()

    today = time.strftime("%Y-%m-%d")
    seg_a, seg_bc = _in_seg(SEG_A), _in_seg(SEG_BC)
    plan = {"now": time.strftime("%H:%M:%S"), "date": today,
            "segments": {"A": SEG_A, "BC": SEG_BC}, "budget": PROBE_BUDGET,
            "candidates": [
                "A realtime apphwhq a=DaBanList&c=HomeDingPan&Type=7 (w48)",
                "B realtime same, run 09:26-09:30 (retention check)",
                "C history  apphis  a=HisDaBanList&c=HisHomeDingPan&Type=7&PidType=8"
                "&Day=<prev trade date> (w30)"]}
    if not args.confirm_budget:
        print("PROBE_DRY_JSON:" + json.dumps(plan, ensure_ascii=False))
        return

    if not seg_a and not seg_bc:
        print(f"时段外（{_hhmm_now()}）拒绝实弹：A 需 {SEG_A}、B/C 需 {SEG_BC}；"
              f"窗外列表空无法区分「无数据」vs「窗外清空」，禁止盲探（红线 9）")
        raise SystemExit(2)

    results: list[dict] = []
    creds = _creds()
    if seg_a:
        dump = DUMP_DIR / f"auction_trial_contract_{today}_a.json"
        if dump.exists():
            print(f"A 段当日已发射（{dump}），幂等门拒绝重发；读已有 raw 即可")
            raise SystemExit(2)
        results.append(_fire("A", _HOST_REALTIME,
                             {"a": "DaBanList", "c": "HomeDingPan", "Type": 7, "Order": 1,
                              "st": 100, "Is_st": 1, "apiv": "w48", "VerSion": "6.3.20.2",
                              "PhoneOSNew": 1, "Red": 0, **creds}))
    if seg_bc:
        dump = DUMP_DIR / f"auction_trial_contract_{today}_bc.json"
        if dump.exists():
            print(f"B/C 段当日已发射（{dump}），幂等门拒绝重发；读已有 raw 即可")
            raise SystemExit(2)
        results.append(_fire("B", _HOST_REALTIME,
                             {"a": "DaBanList", "c": "HomeDingPan", "Type": 7, "Order": 1,
                              "st": 100, "Is_st": 1, "apiv": "w48", "VerSion": "6.3.20.2",
                              "PhoneOSNew": 1, "Red": 0, **creds}))
        time.sleep(2.0)
        day = args.prev_trade_date or today   # Day 参数生效性本身是探针目标之一
        results.append(_fire("C", _HOST_HISTORY,
                             {"a": "HisDaBanList", "c": "HisHomeDingPan", "Type": 7,
                              "PidType": 8, "Order": 1, "st": 100, "Is_st": 1,
                              "Day": day, "apiv": "w30", "VerSion": "6.3.20.2",
                              "PhoneOSNew": 1, "Red": 0, **creds}))

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"probedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": results}
    dump.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("PROBE_RESULT_JSON:" + json.dumps(payload, ensure_ascii=False))
    print(f"raw 落盘：{dump}")


if __name__ == "__main__":
    main()
