"""longhuvip 题材 API → MongoDB theme_stock_mappings 定时刷新服务。

数据链路：
  longhuvip.com Theme API → 本服务拉取解析 → MongoDB theme_stock_mappings

上游 API:
  https://applhb.longhuvip.com/w1/api/index.php
    ?a=InfoGet&apiv=w43&c=Theme&...&ID=<theme_id>

返回结构:
  - StockList: [{StockID, prod_name, HotNum, Tag: [{Name}]}]
  - ZT: {stockCode: [isNew, ...]}
  - Table: [{Level1: {Name, Stocks: [{StockID, Reason, ...}]}, Level2: [...]}]
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from backend.data.repositories.mongo_theme_repository import MongoThemeRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.core.settings import get_settings

# ── longhuvip API 配置 ─────────────────────────────────────────────────────
_LONGHUVIP_THEME_API = "https://applhb.longhuvip.com/w1/api/index.php"

_LONGHUVIP_PARAMS = {
    "a": "InfoGet",
    "apiv": "w43",
    "c": "Theme",
    "PhoneOSNew": "1",
    "UserID": "397605",
    "DeviceID": "548d826f-a2a7-301a-b148-920f31f15331",
    "VerSion": "5.22.0.2",
    "Token": "df9cadb87bbba7d04e9fcbaa2aa229b3",
}

# 开盘啦共用鉴权身份（UserID/DeviceID/Token）的**公共出口**：kpl_theme_fetch 等同账号
# 体系端点从这里取，禁止另拷一份凭据常量（单一事实源；Token 失效只改这一处）。
KPL_APP_BASE_PARAMS = dict(_LONGHUVIP_PARAMS)

# ── 限速 ────────────────────────────────────────────────────────────────────
_BATCH_SIZE = 10
_BATCH_DELAY_SECONDS = 0.5
_REQUEST_TIMEOUT_SECONDS = 15
_SCAN_TOTAL_TIMEOUT_SECONDS = 60  # 盲扫单轮总时限：50 候选最坏 750s，超时中断保留已扫 cursor 续扫
_DIRECTORY_SCAN_AHEAD = 50

# ── 题材目录提示源（2026-10-25 修复） ──────────────────────────────────────
# 背景：themes 名单自 2026-07-18 起零新增，根因=盲扫「线性前进」假设错误——KPL 在
# **低段补号**新建题材（397-402 连号新建，俄乌重建=402），落在已扫过的空洞区间
# （cursor 已爬到 3496）永久漏掉；HTTP 侧 c=Theme 无列表端点（InfoList/GetList 均
# 9999，题材目录走 App Socket 通道）。
# 方案：wzslinker（开源 github.com/LibertyZero10/WzSLinker）的 KPL 题材库页每日
# 自动生成全量目录 dump（kpl_theme_data.js，251 题材含 ID/Name）。本层拉它做
# **目录提示源**——只用于发现新 ID/改名；成分数据一律仍从 longhuvip 官方 InfoGet
# 拉（数据主体不依赖第三方）。拉取失败 → 结构化降级，盲扫保留兜底。
WZS_THEME_DIRECTORY_URL = "https://wzslinker.top/companys/KPL/kpl_theme_data.js"


def _fetch_wzs_theme_directory(timeout: int = _REQUEST_TIMEOUT_SECONDS) -> list[dict[str, Any]] | None:
    """拉 wzslinker KPL 题材目录 dump → [{ID, Name, ...}]；失败/形状异常返回 None。"""
    import re

    try:
        req = urllib.request.Request(WZS_THEME_DIRECTORY_URL, method="GET",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 — 第三方提示源，任何失败都走降级
        raise RuntimeError(f"wzslinker 目录拉取失败: {exc}") from exc
    m = re.search(r"window\.KPL_THEME_DATA\s*=\s*(\[.*?\])\s*;?\s*$", body, re.S)
    if not m:
        raise RuntimeError("kpl_theme_data.js 形状异常（无 KPL_THEME_DATA 数组）")
    data = json.loads(m.group(1))
    if not isinstance(data, list):
        raise RuntimeError(f"kpl_theme_data.js 非数组: {type(data).__name__}")
    return data


def _apply_theme_directory_diff(database: Any, repo: Any, result: Any) -> None:
    """目录 diff：wzslinker 目录 vs 库内 themes → 新 ID/改名逐个 InfoGet 入库。

    成分数据全部走 longhuvip 官方端点（第三方只贡献 ID/名字清单）。第三方失败
    → result.directoryDiffError 结构化披露，不影响主刷新（fail-visible 不伪装）。
    """
    result.directory_diff_attempted = True
    try:
        directory = _fetch_wzs_theme_directory()
    except RuntimeError as exc:
        result.directory_diff_error = str(exc)
        return
    ours: dict[str, str] = {}
    for t in database["themes"].find({}, {"id": 1, "name": 1}):
        ours[str(t.get("id") or "")] = str(t.get("name") or "")
    for entry in directory:
        if not isinstance(entry, dict):
            continue
        tid = str(entry.get("ID") or "").strip()
        name = str(entry.get("Name") or "").strip()
        if not tid or not name:
            continue
        if tid in ours and ours[tid] == name:
            continue
        # 新 ID 或改名 → 官方端点拉详情入库（成分主体不依赖第三方）
        try:
            api_data = _fetch_theme_detail(tid)
        except Exception as exc:  # noqa: BLE001
            result.directory_diff_failed_ids.append(f"{tid}: {exc}")
            continue
        if api_data is None or not str(api_data.get("Name") or "").strip():
            result.directory_diff_failed_ids.append(f"{tid}: 官方端点空载荷")
            continue
        mappings = _extract_mappings(api_data)
        existed = tid in ours
        old_name = ours.get(tid, "")
        repo.upsert_theme(tid, str(api_data["Name"]).strip(),
                          str(api_data.get("ZSCode") or "").strip())
        if mappings:
            repo.replace_theme_mappings(tid, mappings)
            result.mappings_updated += 1
        if existed and old_name != str(api_data["Name"]).strip():
            result.directory_diff_renamed += 1
        elif not existed:
            result.directory_diff_added += 1
        ours[tid] = str(api_data["Name"]).strip()


def _fetch_theme_detail(theme_id: str) -> dict[str, Any] | None:
    """调用 longhuvip API 获取单个题材的完整数据。"""
    params = {**_LONGHUVIP_PARAMS, "ID": str(theme_id)}
    url = f"{_LONGHUVIP_THEME_API}?{urlencode(params)}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if data.get("errcode") != "0":
                return None
            return data
    except urllib.error.URLError as exc:
        # 网络层错误（DNS / 连接拒绝 / 超时）
        raise RuntimeError(f"网络错误: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"响应解析失败: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"未知错误: {exc}") from exc


# 公开别名：KPL 人气缓存（kpl_hotness_cache）复用同一 API client；
# 本模块内部与既有测试仍使用 _fetch_theme_detail。
fetch_theme_detail = _fetch_theme_detail


def _extract_mappings(api_data: dict[str, Any]) -> list[dict[str, Any]]:
    """从 longhuvip API 返回数据中提取 stockCode → tags/reason 映射。

    返回格式适配 MongoThemeRepository.replace_theme_mappings()：
      [{"stockCode": "000001", "tags": [{"Name": "算力"}], "reason": "算力龙头"}, ...]
    """
    stock_list = api_data.get("StockList") or []
    table = api_data.get("Table") or []
    zt = api_data.get("ZT") or {}

    # 收集每个股票的 tags（从 StockList.Tag）和 reason（从 Table 层级）
    tags_by_code: dict[str, list[dict[str, str]]] = {}
    reason_by_code: dict[str, str] = {}

    # 从 StockList 提取 tags
    for item in stock_list:
        code = str(item.get("StockID") or "").strip()
        if not code:
            continue
        raw_tags = item.get("Tag")
        if isinstance(raw_tags, list):
            names = [
                str(t.get("Name") or "").strip()
                for t in raw_tags
                if isinstance(t, dict) and str(t.get("Name") or "").strip()
            ]
            if names:
                existing = tags_by_code.setdefault(code, [])
                for name in names:
                    if not any(e.get("Name") == name for e in existing):
                        existing.append({"Name": name})

    # 从 Table 层级提取 reason
    def _collect_from_stocks(stocks: list[dict[str, Any]]) -> None:
        for s in stocks:
            code = str(s.get("StockID") or "").strip()
            if not code:
                continue
            reason = str(s.get("Reason") or "").strip()
            if reason and code not in reason_by_code:
                reason_by_code[code] = reason

    for item in table:
        l1 = item.get("Level1") if isinstance(item, dict) else None
        if isinstance(l1, dict) and isinstance(l1.get("Stocks"), list):
            _collect_from_stocks(l1["Stocks"])
        for l2 in item.get("Level2") or []:
            if isinstance(l2, dict) and isinstance(l2.get("Stocks"), list):
                _collect_from_stocks(l2["Stocks"])

    # 合并所有 code
    all_codes: set[str] = set()
    for item in stock_list:
        code = str(item.get("StockID") or "").strip()
        if code:
            all_codes.add(code)
    for code in reason_by_code:
        all_codes.add(code)
    for code in zt:
        all_codes.add(str(code).strip())

    # 构建映射列表
    mappings: list[dict[str, Any]] = []
    for code in sorted(all_codes):
        if not code:
            continue
        mappings.append(
            {
                "stockCode": code,
                "tags": tags_by_code.get(code, []),
                "reason": reason_by_code.get(code, ""),
            }
        )
    return mappings


class ThemeMappingRefreshResult:
    """刷新结果值对象。"""

    def __init__(self) -> None:
        self.themes_total: int = 0
        self.themes_fetched: int = 0
        self.themes_failed: list[str] = []
        self.mappings_updated: int = 0
        self.mappings_cleared: int = 0
        self.total_stocks: int = 0
        self.directory_scan_start: int | None = None
        self.directory_scan_end: int | None = None
        self.directory_scanned: int = 0
        self.directory_added: int = 0
        self.directory_renamed: int = 0
        self.directory_failed_ids: list[str] = []
        self.directory_empty_ids: list[str] = []
        self.directory_scan_cursor: int | None = None
        # 目录 diff（wzslinker 提示源，2026-10-25 修复低段补号漏题）
        self.directory_diff_attempted: bool = False
        self.directory_diff_added: int = 0
        self.directory_diff_renamed: int = 0
        self.directory_diff_failed_ids: list[str] = []
        self.directory_diff_error: str | None = None
        self.errors: list[str] = []
        self.source: str = "longhuvip"
        self.started_at: str = ""
        self.finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": len(self.errors) == 0,
            "source": self.source,
            "themesTotal": self.themes_total,
            "themesFetched": self.themes_fetched,
            "themesFailed": self.themes_failed[:30],
            "themesFailedCount": len(self.themes_failed),
            "mappingsUpdated": self.mappings_updated,
            "mappingsCleared": self.mappings_cleared,
            "totalStocks": self.total_stocks,
            "directoryScanStart": self.directory_scan_start,
            "directoryScanEnd": self.directory_scan_end,
            "directoryScanned": self.directory_scanned,
            "directoryAdded": self.directory_added,
            "directoryRenamed": self.directory_renamed,
            "directoryFailedIds": self.directory_failed_ids[:30],
            "directoryFailedCount": len(self.directory_failed_ids),
            "directoryEmptyIds": self.directory_empty_ids[:30],
            "directoryEmptyCount": len(self.directory_empty_ids),
            "directoryScanCursor": self.directory_scan_cursor,
            "directoryDiffAttempted": self.directory_diff_attempted,
            "directoryDiffAdded": self.directory_diff_added,
            "directoryDiffRenamed": self.directory_diff_renamed,
            "directoryDiffFailedIds": self.directory_diff_failed_ids[:30],
            "directoryDiffFailedCount": len(self.directory_diff_failed_ids),
            "directoryDiffError": self.directory_diff_error,
            "errors": self.errors,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


def refresh_theme_stock_mappings(
    database: Any = None,
    *,
    directory_scan_ahead: int = _DIRECTORY_SCAN_AHEAD,
    diff_only: bool = False,
) -> dict[str, Any]:
    """从 longhuvip 题材 API 刷新 MongoDB theme_stock_mappings 集合。

    流程：
    1. 读取 MongoDB themes 表获取所有题材 ID
    2. 逐批调用 longhuvip API 获取每个题材的成分股
    3. 目录 diff（2026-10-25 修复）：wzslinker 全量目录对照库内，新 ID/改名
       逐个从官方端点拉详情入库——堵「KPL 低段补号 + 盲扫只前进不回头」的
       永久漏题（themes 曾 2026-07-18 起零新增，397-402 六题材漏采三个月）
    4. 按“当前最大题材 ID + 1”往后盲扫 50 个候选 ID，发现有效新题材时自动写入 themes

    `diff_only=True`：跳过存量刷新与盲扫，只跑目录 diff（回填/修复入口）。
    """
    result = ThemeMappingRefreshResult()
    result.started_at = datetime.now(timezone.utc).isoformat()

    if database is None:
        try:
            database = get_runtime_mongodb_database()
        except Exception as exc:
            result.errors.append(f"MongoDB 连接失败: {exc}")
            result.finished_at = datetime.now(timezone.utc).isoformat()
            return result.to_dict()

    repo = MongoThemeRepository(database)

    if diff_only:
        _apply_theme_directory_diff(database, repo, result)
        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result.to_dict()

    # 1. 读取主题列表
    themes = list(database["themes"].find({}).sort([("id", 1)]))
    result.themes_total = len(themes)

    if not themes:
        result.errors.append("MongoDB themes 表为空，请先导入 theme_base_mapping.json")
        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result.to_dict()

    # 2. 逐批拉取 & 写入已有题材
    now = datetime.now(timezone.utc)
    theme_ids = [str(t.get("id") or "") for t in themes if str(t.get("id") or "")]
    total_stocks = 0

    for i in range(0, len(theme_ids), _BATCH_SIZE):
        batch = theme_ids[i : i + _BATCH_SIZE]

        for theme_id in batch:
            try:
                api_data = _fetch_theme_detail(theme_id)
            except Exception as exc:
                result.themes_failed.append(f"{theme_id}: {exc}")
                continue

            if api_data is None:
                result.themes_failed.append(theme_id)
                continue

            mappings = _extract_mappings(api_data)
            if mappings:
                repo.replace_theme_mappings(theme_id, mappings)
                result.mappings_updated += 1
                total_stocks += len(mappings)
            else:
                # 清空该题材的旧映射
                repo.replace_theme_mappings(theme_id, [])
                result.mappings_cleared += 1

            result.themes_fetched += 1

        # 批次间短暂等待
        if i + _BATCH_SIZE < len(theme_ids):
            time.sleep(_BATCH_DELAY_SECONDS)

    result.total_stocks = total_stocks

    # 3. 目录 diff（wzslinker 提示源）：低段补号新题材/改名的确定性发现，
    #    先于盲扫跑（盲扫只管高段前进；两者互补，任一失败互不连坐）
    _apply_theme_directory_diff(database, repo, result)

    # 4. 盲扫新题材：从当前最大题材 ID 的下一位开始探测 directory_scan_ahead 个 ID
    numeric_ids = [int(tid) for tid in theme_ids if tid.isdigit()]
    stored_cursor = repo.get_metadata("directoryScanCursor", "")
    try:
        cursor = int(stored_cursor) if stored_cursor else max(numeric_ids, default=0)
    except (TypeError, ValueError):
        cursor = max(numeric_ids, default=0)
    cursor = max(cursor, max(numeric_ids, default=0))

    scan_count = max(0, int(directory_scan_ahead))
    if scan_count:
        result.directory_scan_start = cursor + 1
        result.directory_scan_end = result.directory_scan_start + scan_count - 1
        candidate_ids = [
            str(value)
            for value in range(result.directory_scan_start, result.directory_scan_end + 1)
        ]

        scan_started_at = time.monotonic()
        last_theme_id: int | None = None
        for index, theme_id in enumerate(candidate_ids):
            # 盲扫单轮总时限：超时中断，保留已扫 cursor 供下一轮继续（避免 750s 长时间阻塞）
            if time.monotonic() - scan_started_at > _SCAN_TOTAL_TIMEOUT_SECONDS:
                break
            result.directory_scanned += 1
            last_theme_id = int(theme_id)
            try:
                api_data = _fetch_theme_detail(theme_id)
            except Exception as exc:
                result.directory_failed_ids.append(f"{theme_id}: {exc}")
                continue

            if api_data is None:
                # errcode != 0（该 ID 无题材，正常空洞）→ 计 empty，不误判为失败
                # （真正的网络/解析失败已在上方 except 计入 directory_failed_ids）
                result.directory_empty_ids.append(theme_id)
                continue

            name = str(api_data.get("Name") or "").strip()
            if not name:
                result.directory_empty_ids.append(theme_id)
                continue

            mappings = _extract_mappings(api_data)
            if not mappings:
                result.directory_empty_ids.append(theme_id)
                continue

            existed = database["themes"].find_one({"id": theme_id}) is not None
            old_name = ""
            if existed:
                old_doc = database["themes"].find_one({"id": theme_id})
                old_name = str((old_doc or {}).get("name") or "").strip()
            repo.upsert_theme(
                theme_id,
                name,
                str(api_data.get("ZSCode") or "").strip(),
            )
            if old_name and old_name != name:
                result.directory_renamed += 1
            if not existed:
                result.directory_added += 1
            repo.replace_theme_mappings(theme_id, mappings)
            result.mappings_updated += 1
            total_stocks += len(mappings)
            result.themes_fetched += 1

            if (index + 1) % _BATCH_SIZE == 0 and index + 1 < len(candidate_ids):
                time.sleep(_BATCH_DELAY_SECONDS)

        result.directory_scan_cursor = (
            last_theme_id if last_theme_id is not None else (result.directory_scan_end - 1)
        )
    else:
        result.directory_scan_cursor = cursor

    result.total_stocks = total_stocks

    # 5. 更新元数据
    result.finished_at = datetime.now(timezone.utc).isoformat()
    version = f"longhuvip-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    repo.set_metadata(version=version, last_update=now.isoformat())

    metadata_values = {
        "directoryScanCursor": result.directory_scan_cursor,
        "directoryRetryIds": [],
        "lastAttemptId": "",
        "lastAttemptStartedAt": result.started_at,
        "lastAttemptAt": result.finished_at,
        "lastStatus": (
            "success"
            if not result.errors and not result.themes_failed and not result.directory_failed_ids
            else "partial"
        ),
        "lastCompleteAt": (
            result.finished_at
            if not result.errors and not result.themes_failed and not result.directory_failed_ids
            else None
        ),
        "lastRefreshAttempt": result.to_dict(),
    }
    for key, value in metadata_values.items():
        database["theme_metadata"].replace_one(
            {"key": key},
            {"key": key, "value": value, "updatedAt": datetime.now(timezone.utc)},
            upsert=True,
        )

    result.finished_at = datetime.now(timezone.utc).isoformat()
    return result.to_dict()


def main(argv: list[str] | None = None) -> int:
    """CLI：`python -m backend.services.theme.mapping_refresh [--diff-only]`。

    常规刷新走调度器（mapping_scheduler 08:30）；本入口供手工回填/修复。
    """
    import argparse

    ap = argparse.ArgumentParser(description="longhuvip 题材映射刷新")
    ap.add_argument("--diff-only", action="store_true",
                    help="只跑目录 diff（wzslinker 提示源→官方 InfoGet 回填新题材/改名）")
    args = ap.parse_args(argv)
    out = refresh_theme_stock_mappings(diff_only=args.diff_only)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
