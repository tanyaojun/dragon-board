# -*- coding: utf-8 -*-
"""WzsLinker 试盘 raw 日档工具（历史档案读写；2026-11-17 已退役出链）。

**2026-11-17 用户裁决**：判据链主链 = KPL socket 官方推送序列（pid=8 竞价池实时页），
WzsLinker（第三方非官方代理，11-16 实证故障）**退役出链**——live 采集函数
fetch_auction_trial 已删，判据链零依赖（auction_leader_label.run 主链守卫测试锁定）。

本模块保留：auction_trial_raw 日档（COLLECTION_TRIAL_RAW，11-16/11-17 对拍参考档）
的读写工具（persist_trial_raw/normalize_trial_time/parse_trial_payload），
供 scripts/backfill_auction_trial_raw.py（历史档案回填）与
scripts/auction_trial_raw_normalize_times.py（时间列规范化）使用。
历史合同存档（Wzs api-auction.php，勘察 §6）：GET {TRIAL_HOST}?page=limit_up_bidding
&date=YYYY-MM-DD；rank=数值原值（金额=元、比例=小数）；actual_date ≠ 请求日 → rows
清空（跨日冒充 = 叙事假事实）。
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

TRIAL_HOST = "http://wzslinker.top/companys/api-auction.php"   # 已退役（历史合同存档）
REQUEST_TIMEOUT_SECONDS = 10
COLLECTION_TRIAL_RAW = "auction_trial_raw"   # 全量日档（_id=日期，2026-11-14 用户裁决）

_PCT_KEYS = ("jj_percent", "percent", "pre_percent", "jj_turnover")
_AMT_KEYS = ("max_amount", "last_amount", "first_amount", "first_add",
             "jj_amount", "circulated_value")
_TIME_KEYS = ("start_time", "end_time")
_ROW_KEYS = ("code", "max_amount", "jj_percent", "percent", "last_amount",
             "first_amount", "first_add", "end_time", "bk_name", "price",
             "start_time", "jj_turnover", "jj_amount", "circulated_value",
             "pre_percent")


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _num(rank: object) -> float | None:
    try:
        f = float(rank)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f


def normalize_trial_time(val: object) -> object | None:
    """时间归一化：上游存在 hh:mm:ss 与 HHMMSS 双格式（60 日档 4% 为无冒号，
    2026-11-14 基率探针发现）。HHMMSS → hh:mm:ss；已带冒号原样；不可判原样返回
    （fail-visible：不猜、不丢，乱入叙事由渲染器防御）。"""
    s = str(val or "").strip()
    if not s:
        return None
    if ":" in s:
        return s
    digits = s.replace(".", "")
    if digits.isdigit() and len(digits) in (5, 6):
        digits = digits.zfill(6)
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"
    return s


def _cell_val(cell: dict, key: str) -> object | None:
    """cell → 语义值：比例 rank×100、金额 rank 原值；时间归一化；rank 缺位 → None（缺位不出现）。"""
    rank = cell.get("rank")
    if key in _PCT_KEYS:
        f = _num(rank)
        return None if f is None else round(f * 100.0, 4)
    if key in _AMT_KEYS:
        return _num(rank)
    if key in _TIME_KEYS:
        return normalize_trial_time(rank)
    s = str(rank or "").strip()          # bk_name/price 等字符串列：rank 即原值
    return s or None


def parse_trial_payload(data: dict, date: str) -> dict:
    """信封 → 结构化载荷（纯函数，离线可测）。actual_date ≠ date → rows 清空（守卫）。"""
    if not data.get("success"):
        return {"state": "api_error", "message": str(data.get("message") or "")[:120],
                "actual_date": data.get("actual_date"), "rows": {}, "n_rows": 0}
    actual = str(data.get("actual_date") or "")
    saved_at = data.get("saved_at")
    base = {"state": "ok" if actual == date else "fallback",
            "actual_date": actual, "saved_at": saved_at,
            "fetched": bool(data.get("fetched")),
            "is_fallback": bool(data.get("is_fallback")),
            "message": str(data.get("message") or "")[:120]}
    if actual != date:
        return {**base, "rows": {}, "n_rows": 0}
    try:
        sl = data["data"]["data"]["stock_list"]
        head = sl.get("head_info") or []
        raw_list = sl.get("list") or []
        keys = [str(h.get("sort_key") or "") for h in head]
        # review 2026-11-14 finding-1：列对齐纯位置（cell 无列级指纹），契约守卫必须
        # 顺序敏感——head_info 缺失或 sort_key 序 ≠ 合同列序时错位风险下不得冒充
        # 事实（错误数据比丢数据更糟，§4.0），结构化 parse_error + 指纹留痕。
        # 首列合同别名：stock_id（上游）= code（语义）。
        if not keys or keys[0] not in ("code", "stock_id") or keys[1:] != list(_ROW_KEYS[1:]):
            return {**base, "state": "parse_error",
                    "error": f"schema_drift: keys={keys}", "rows": {}, "n_rows": 0}
        rows: dict = {}
        obs = {"headSortKeys": keys, "dropped": 0, "duplicateCodes": 0}
        for raw in raw_list:
            if not raw or not isinstance(raw[0], dict):
                obs["dropped"] += 1
                continue
            code = str((raw[0].get("param") or {}).get("code") or "")
            cells = dict(zip(["code", *keys[1:]], raw))
            row: dict = {}
            for key in _ROW_KEYS[1:]:
                val = _cell_val(cells.get(key) or {}, key)
                if val is not None:
                    row[key] = val
            if not code or not row:
                obs["dropped"] += 1
                continue
            if code in rows:
                obs["duplicateCodes"] += 1
            rows[code] = row
        return {**base, "rows": rows, "n_rows": len(rows), "obs": obs}
    except (KeyError, TypeError) as exc:
        return {**base, "state": "parse_error", "error": f"{type(exc).__name__}: {exc}",
                "rows": {}, "n_rows": 0}


def persist_trial_raw(db, date: str, result: dict) -> dict:
    """试盘 raw 全量日档落库（2026-11-14 用户裁决：单集合 auction_trial_raw，_id=日期）。

    §4.0：采集链路必须保存原始记录——全量 rows（~百只/日 × 15 列语义值）+ 信封
    元数据一次写入，幂等覆盖（重跑/回填可回放）。写入口径：仅 state=ok（
    actual_date 守卫已验证当日）——fallback/api_error/http_error/parse_error 无
    当日有效载荷不落（跨日冒充禁令；失败留痕在 label doc trialState，不覆盖
    已有好档）。空 rows + ok = 「当日全市场无试盘个股」事实，照写（nRows=0）。
    """
    if "rows" not in result or result.get("state") != "ok":
        return {"persisted": False,
                "reason": f"skip:{result.get('state') or 'no_payload'}"}
    try:
        doc = {"tradingDate": date, "source": "wzslinker_auction",
               "state": result.get("state"), "actualDate": result.get("actual_date"),
               "savedAt": result.get("saved_at"), "fetched": result.get("fetched"),
               "isFallback": result.get("is_fallback"), "message": result.get("message"),
               "rows": result.get("rows") or {}, "nRows": result.get("n_rows") or 0,
               "obs": result.get("obs"),
               "persistedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        db[COLLECTION_TRIAL_RAW].replace_one({"_id": date}, doc, upsert=True)
        return {"persisted": True, "nRows": doc["nRows"]}
    except Exception as exc:   # noqa: BLE001 — 红线 9：结构化留痕不抛，不阻断投喂
        return {"persisted": False,
                "reason": f"persist_error:{type(exc).__name__}: {str(exc)[:80]}"}
