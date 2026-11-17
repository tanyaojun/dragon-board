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
  8 bidding_amount(竞价成交额) / 9 col9(未破译,09:20后累计量) / 10 col10(col8近似重复) /
  11 plate(板块) / 12 circulated_value(流通市值) / 13 col13(未破译) /
  14 col14(未破译) / 15 col15(未破译) / 16 state(连板态「首板/4连板」)

频控预算（红线 9）：POST 走 _post_form 全局 ≥2s 锁；单次采集 ≤MAX_PAGES 页；
调用时点=打标链竞价窗内一次（冻结态快照），页面/读口只读库不触发上游。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

KBL_MBL_HOST = "https://apphwhq.kaipanla.com/w1/api/index.php"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"
_TZ_CST = timezone(timedelta(hours=8))
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
    truncated = False
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
        errcode = data.get("errcode")
        if errcode is not None and errcode not in (0, "0"):
            attempts.append({"index": index, "state": f"kpl_errcode:{errcode}",
                             "message": str(data.get("msg") or "")[:120]})
            return {"state": f"kpl_errcode:{errcode}", "rows": all_rows,
                    "n_rows": len(all_rows), "pages": page, "attempts": attempts,
                    "message": str(data.get("msg") or "")[:120]}
        rows_raw = data.get("info")
        if not isinstance(rows_raw, list):
            attempts.append({"index": index, "state": "parse_error:info_not_list",
                             "got": type(rows_raw).__name__})
            return {"state": "parse_error:info_not_list", "rows": all_rows,
                    "n_rows": len(all_rows), "pages": page, "attempts": attempts,
                    "message": f"info type={type(rows_raw).__name__}"}
        page_rows = parse_mbl_rows(rows_raw)
        all_rows.update(page_rows)
        meta = {k: data.get(k) for k in ("day", "time", "status") if data.get(k) is not None}
        attempts.append({"index": index, "state": "ok", "n_rows": len(page_rows)})
        if len(rows_raw) < page_size or not page_rows:
            break
    else:   # 页数耗尽且末页仍满页 → 无法确认全量（审计可见）
        truncated = True
    return {"state": "ok", "rows": all_rows, "n_rows": len(all_rows),
            "pages": len(attempts), "attempts": attempts, "truncated": truncated,
            **meta}


def persist_morning_bidding_raw(db: Any, date: str, result: dict[str, Any]) -> dict[str, Any]:
    """真源头日档落库（_id=日期，rows 键=6 位代码）。

    红线 1：空档（ok 且 0 行=当日无竞价股）也是事实照写；部分页失败但已取回 rows
    时同样落库并打 partial=true 质量标记；非 ok 且 0 行不写（不覆盖同日既有好档）。
    """
    rows = result.get("rows") or {}
    state = result.get("state")
    partial = bool(state and state != "ok")
    now = datetime.now(_TZ_CST).isoformat(timespec="seconds")
    doc = {"_id": date, "date": date, "source": "kpl_direct_morning_bidding",
           "rows": rows, "n_rows": len(rows),
           "pages": result.get("pages"), "day": result.get("day"),
           "time": result.get("time"), "status": result.get("status"),
           "state": state, "partial": partial,
           "truncated": bool(result.get("truncated")),
           "attempts": result.get("attempts") or [],
           "fetchedAt": now, "updatedAt": now}
    db[COLLECTION_MBL_RAW].replace_one({"_id": date}, doc, upsert=True)
    return {"ok": True, "collection": COLLECTION_MBL_RAW, "n_rows": len(rows),
            "partial": partial, "state": state}


def collect_auction_bidding_direct(db: Any, date: str) -> dict[str, Any]:
    """采集+落库一体（打标链竞价窗内调用；dry-run 由调用方短路）。"""
    result = fetch_morning_bidding_list()
    out = {k: result.get(k) for k in ("state", "n_rows", "pages", "day", "time",
                                      "status", "message") if result.get(k) is not None}
    out["attempts"] = result.get("attempts") or []
    out["truncated"] = bool(result.get("truncated"))
    # 红线 1：ok 照写（含当日无股空档事实）；非 ok 但有部分 rows 也写（partial 标记
    # 在 persist 内）；非 ok 且 0 行不写、不覆盖既有好档
    if result.get("state") == "ok" or result.get("rows"):
        out["persistState"] = persist_morning_bidding_raw(db, date, result)
    return out


def load_morning_bidding_raw(db: Any, date: str) -> dict[str, dict] | None:
    """日档读（纯库读）；无档返回 None（调用方 fail-visible）。"""
    doc = db[COLLECTION_MBL_RAW].find_one({"_id": date})
    if not doc:
        return None
    return doc.get("rows") or {}

# ══════ 窗内多帧采集（2026-11-17 col9 判约定案：主假设证伪，09:20 后累计量）══════
# 频控预算（红线 9）：仅竞价窗 09:15-09:26 内、随 archiver 60s 轮询每轮一帧；
# 帧数硬上限 ≤15/日（≈窗内 11 轮 + 余量），每帧 2 POST（100/页翻页），走 _post_form
# ≥2s 全局锁；窗外/非交易日静默跳过（fail-visible 进返回态）。
COLLECTION_MBL_SERIES = "kpl_mbl_series"
MBL_FRAME_MAX = 15
MBL_WINDOW = ("09:15", "09:26")


def _in_mbl_window(now: Any) -> bool:
    hm = now.strftime("%H:%M")
    return MBL_WINDOW[0] <= hm <= MBL_WINDOW[1]


def collect_mbl_frame_series(db: Any, date: str, now: Any = None) -> dict[str, Any]:
    """窗内一帧 MBL（raw 数组态）追加进 kpl_mbl_series（时变行为观测档）。

    2026-11-17 六帧判约定案：col9 主假设（09:20 撤后余额）证伪——09:20 前恒 0、09:20:18 起从零单调累计（002685: 0→93M→187M→205M→216M），为 09:20 参照的累计量非余额，语义未破译保 colN 原名（§7.7）；col4≈socket zt_buy_amount（多只精确相等锚定）；col10≈col8 非严格重复（帧间时点采样差）。
    通道保留供后续语义勘察。
    """
    from datetime import datetime as _dt
    now = now or _dt.now()
    if not _in_mbl_window(now):
        return {"state": "skipped_out_of_window", "window": list(MBL_WINDOW)}
    doc = db[COLLECTION_MBL_SERIES].find_one({"_id": date}) or {}
    frames = doc.get("frames") or []
    if len(frames) >= MBL_FRAME_MAX:
        return {"state": "skipped_budget_exhausted", "frames": len(frames)}
    res = fetch_morning_bidding_list()
    if res.get("state") != "ok":
        return {"state": res.get("state"), "message": res.get("message"),
                "frames": len(frames)}
    raw_rows = [r["raw"] for r in res["rows"].values()]
    frame = {"ts": now.isoformat(timespec="seconds"), "n_rows": len(raw_rows),
             "day": res.get("day"), "rows": raw_rows}
    db[COLLECTION_MBL_SERIES].update_one(
        {"_id": date},
        {"$set": {"date": date, "updatedAt": now.isoformat(timespec="seconds")},
         "$push": {"frames": {"$each": [frame], "$slice": -MBL_FRAME_MAX}}},
        upsert=True)
    return {"state": "ok", "frameN": len(frames) + 1, "n_rows": len(raw_rows)}
