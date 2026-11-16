# -*- coding: utf-8 -*-
"""竞价列表 KPL 直采器（真源头合同，2026-11-16 MITM 定案）。

合同（冻结，雷电模拟器 mitmproxy 实抓 + st=100 独立重放验证）：
- POST https://apphwhq.kaipanla.com/w1/api/index.php（**kaipanla.com 现行代际域**；
  longhuvip.com 为旧代际，对 DaBanList 族一律返回占位垃圾——2026-11-16 六发矩阵实证）；
- form body: a=MorningBiddingList&c=HomeDingPan&Type=4&PidType=0&Order=1&st=N&Index=M
  + 五件套（apiv=w48/VerSion=6.3.20.2/PhoneOSNew=1/Red=0/DeviceID）+ 凭据（UserID/Token）；
- 响应：{"info": [[行]], "day", "time", "status", "ttag", "errcode":"0"}，
  行=统一数组位 17 列（与 socket 2103 pid=8 同源同族：委买额/竞价净额/竞价成交额
  三字段已与 :8002 快照逐值吻合）；
- 翻页：Index 按页长偏移，rows < st 即末页（2026-11-16 实测 100+14=114 只）。

17 列语义（已对齐 ↔ socket pid=8 具名字段；未对齐列保留原名 colN 不猜）：
  0 code / 1 name / 2 price / 3 pct(实时涨幅) / 4 zt_buy_amount(委买额) /
  5 bidding_pct(竞价涨幅) / 6 bidding_net(竞价净额) / 7 bidding_turnover(竞价换手) /
  8 bidding_amount(竞价成交额) / 9 col9(未破译) / 10 col10(未破译) /
  11 plate(板块) / 12 circulated_value(流通市值) / 13 col13(未破译) /
  14 col14(未破译) / 15 col15(未破译) / 16 state(连板态「首板/4连板」)

频控预算（红线 9）：POST 走 _post_form 全局 ≥2s 锁；单次采集 ≤MAX_PAGES 页；
调用时点=打标链竞价窗内一次（冻结态快照），页面/读口只读库不触发上游。
"""
from __future__ import annotations

import json
from typing import Any

REQUEST_TIMEOUT_SECONDS = 10
KBL_MBL_HOST = "https://apphwhq.kaipanla.com/w1/api/index.php"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"
MAX_PAGES = 5

# 17 列具名映射（未破译列保原名，语义待窗内 App 同屏对拍后补）
_COLUMN_NAMES = ("code", "name", "price", "pct", "zt_buy_amount", "bidding_pct",
                 "bidding_net", "bidding_turnover", "bidding_amount", "col9",
                 "col10", "plate", "circulated_value", "col13", "col14", "col15",
                 "state")


def _post(url: str, params: dict[str, Any]) -> dict[str, Any]:
    from backend.services.kpl_ranking_service import _UA_STOCKS, _post_form
    return _post_form(url, params, _UA_STOCKS)


def _base_params() -> dict[str, Any]:
    from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS
    out = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    out.update({"apiv": "w48", "VerSion": "6.3.20.2", "PhoneOSNew": 1, "Red": 0})
    return out


def parse_mbl_rows(info: list[list[Any]]) -> dict[str, dict]:
    """统一数组位行 → {code6: 具名字段 dict}（保留 raw 全行；缺列如实缺）。"""
    rows: dict[str, dict] = {}
    for raw in info or []:
        if not isinstance(raw, list) or not raw:
            continue
        c6 = str(raw[0])[-6:] if raw[0] is not None else ""
        if not c6:
            continue
        rec: dict[str, Any] = {"code": c6}
        for i, name in enumerate(_COLUMN_NAMES):
            rec[name] = raw[i] if i < len(raw) else None
        rec["raw"] = list(raw)
        rows[c6] = rec
    return rows


def fetch_morning_bidding_list(page_size: int = 100, max_pages: int = MAX_PAGES) -> dict[str, Any]:
    """真源头分页拉全量（≤max_pages 页；rows < page_size 即末页）。失败结构化返回。"""
    all_rows: dict[str, dict] = {}
    attempts: list[dict] = []
    meta: dict[str, Any] = {}
    for page in range(max_pages):
        index = page * page_size
        params = _base_params()
        params.update({"a": "MorningBiddingList", "c": "HomeDingPan", "Type": 4,
                       "PidType": 0, "Order": 1, "st": page_size, "Index": index})
        try:
            data = _post(KBL_MBL_HOST, params)
        except Exception as exc:  # noqa: BLE001 — 红线 9：结构化记录不重试
            attempts.append({"index": index, "state": f"http_error:{type(exc).__name__}",
                             "message": str(exc)[:120]})
            return {"state": f"http_error:{type(exc).__name__}", "rows": all_rows,
                    "n_rows": len(all_rows), "pages": page, "attempts": attempts,
                    "message": str(exc)[:120]}
        rows_raw = data.get("info") or []
        page_rows = parse_mbl_rows(rows_raw)
        all_rows.update(page_rows)
        meta = {k: data.get(k) for k in ("day", "time", "status") if data.get(k) is not None}
        attempts.append({"index": index, "state": "ok", "n_rows": len(page_rows)})
        if len(rows_raw) < page_size or not page_rows:
            break
    return {"state": "ok", "rows": all_rows, "n_rows": len(all_rows),
            "pages": len(attempts), "attempts": attempts, **meta}


def persist_morning_bidding_raw(db: Any, date: str, result: dict[str, Any]) -> dict[str, Any]:
    """真源头日档落库（_id=日期，rows 键=6 位代码；仅 ok 态写，空档也是事实）。"""
    rows = result.get("rows") or {}
    doc = {"_id": date, "date": date, "source": "kpl_direct_morning_bidding",
           "rows": rows, "n_rows": len(rows),
           "pages": result.get("pages"), "day": result.get("day"),
           "time": result.get("time"), "status": result.get("status"),
           "fetchedAt": json.dumps(result.get("attempts") or [], ensure_ascii=False),
           "updatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds")}
    db[COLLECTION_MBL_RAW].replace_one({"_id": date}, doc, upsert=True)
    return {"ok": True, "collection": COLLECTION_MBL_RAW, "n_rows": len(rows)}


def collect_auction_bidding_direct(db: Any, date: str) -> dict[str, Any]:
    """采集+落库一体（打标链竞价窗内调用；dry-run 由调用方短路）。"""
    result = fetch_morning_bidding_list()
    out = {k: result.get(k) for k in ("state", "n_rows", "pages", "day", "time",
                                      "status", "message") if result.get(k) is not None}
    out["attempts"] = result.get("attempts") or []
    if result.get("state") == "ok":
        out["persistState"] = persist_morning_bidding_raw(db, date, result)
    return out


def load_morning_bidding_raw(db: Any, date: str) -> dict[str, dict] | None:
    """日档读（纯库读）；无档返回 None（调用方 fail-visible）。"""
    doc = db[COLLECTION_MBL_RAW].find_one({"_id": date})
    if not doc:
        return None
    return doc.get("rows") or {}
