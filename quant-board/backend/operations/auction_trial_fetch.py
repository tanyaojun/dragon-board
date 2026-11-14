# -*- coding: utf-8 -*-
"""竞价试盘源采集器（WzsLinker api-auction.php，合同定案 2026-11-14，勘察 §6）。

合同（冻结）：GET {TRIAL_HOST}?page=limit_up_bidding&date=YYYY-MM-DD[&refresh=1]
- 响应信封：success/actual_date/is_fallback/fetched/saved_at/message/dates；
- 数据：data.data.stock_list.head_info（sort_key 列语义）+ list（数组位 cell={text,rank}）；
- **rank = 数值原值**：金额=元、比例=小数（×100 才是百分数）、时间=原串（勘察 §6.1）；
- 历史 date：代理档案不可变、refresh 被忽略（11-14 实测）；当日 refresh=1 强制上游拉取
  （refresh_requested 回显；非交易日自动短路 fetched:false——代理自节流）。

频控预算（红线 9，勘察 §6.4 台账）：盘中 ≤2 发/日 = 先裸读（缓存命中零上游），
saved_at 陈旧（>TRIAL_STALE_SECONDS）才补 1 发 refresh=1；单次会话无重试循环，
失败结构化返回不抛。守卫：actual_date ≠ 请求日 → rows 清空（回退数据不得冒充当日，
跨日冒充 = 叙事假事实，天普 11-12 池漏档同级教训）。
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

TRIAL_HOST = "http://wzslinker.top/companys/api-auction.php"
REQUEST_TIMEOUT_SECONDS = 10
TRIAL_STALE_SECONDS = 120          # 裸读缓存龄上限（页面轮询节奏 60s 的 2 倍容差）
MAX_ATTEMPTS = 2                   # 红线 9：裸读 + 至多 1 发 refresh，无重试循环
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


def _saved_at_age(saved_at: object, now: float | None = None) -> float | None:
    """信封 saved_at 龄：兼容 +08:00/Z 偏移；naive 按 CST 合同（review finding-3，
    不依赖宿主机时区）。不可判 → None（宁缺毋猜，不补拉不冒充新鲜）。"""
    s = str(saved_at or "")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))   # 信封合同 = CST
    return (now if now is not None else time.time()) - dt.timestamp()


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


def fetch_auction_trial(date: str, *, now: float | None = None) -> dict:
    """当日试盘载荷采集（单会话 ≤2 发：裸读 → 陈旧才补 1 发 refresh；失败结构化返回）。"""
    attempts: list[dict] = []
    result: dict | None = None
    refresh = False
    for _ in range(MAX_ATTEMPTS):
        url = f"{TRIAL_HOST}?page=limit_up_bidding&date={date}"
        if refresh:
            url += "&refresh=1"
        try:
            data = _http_get_json(url)
        except Exception as exc:  # noqa: BLE001 — 红线 9：结构化记录，不重试
            return {"state": f"http_error:{type(exc).__name__}", "rows": {}, "n_rows": 0,
                    "attempts": attempts, "message": str(exc)[:120]}
        result = parse_trial_payload(data, date)
        attempts.append({"refresh": refresh, "state": result["state"],
                         "fetched": result.get("fetched"),
                         "saved_at": result.get("saved_at")})
        if result["state"] != "ok":
            break
        age = _saved_at_age(result.get("saved_at"), now=now)
        if age is None or age <= TRIAL_STALE_SECONDS or refresh:
            break          # 新鲜 / 龄不可判（宁缺毋猜）/ 已补拉过 → 收手
        refresh = True     # 陈旧 → 至多补 1 发强制刷新
    return {**(result or {}), "attempts": attempts}
