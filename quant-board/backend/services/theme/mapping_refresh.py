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
import logging
import os
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

# 非机密公共参数（apiv/VerSion 组合为 2026-11-08 实测可用口径，随端点保留在代码）。
# 机密凭据（UserID/DeviceID/Token）不进代码（红线 §1.2.3）：只进 quant-board/.env.local
# （gitignored），键名 QUANT_BOARD_KPL_APP_USERID / _DEVICEID / _TOKEN。换绑路径
# （2026-11-15 首次换绑实测）：雷电模拟器（LDPlayer9，adb root）已登录 App 内提取——
# UserID/Token 取 databases/UserRelate.db UserInfo 表（Token 有效期同表可查），
# DeviceID 取 shared_prefs/device.xml uid；提取后改 .env.local 三行即可，重启后端生效。
_LONGHUVIP_PARAMS = {
    "a": "InfoGet",
    "apiv": "w43",
    "c": "Theme",
    "PhoneOSNew": "1",
    "VerSion": "5.22.0.2",
}

# .env.local 加载（backend.core.settings 导入时也会加载，这里幂等补载保证独立导入
# 本模块时凭据同样在场；已存在的 os.environ 不覆盖）。
from backend.core.settings import BASE_DIR, _load_env_file

_load_env_file(BASE_DIR / ".env.local")

_KPL_APP_USERID = os.environ.get("QUANT_BOARD_KPL_APP_USERID", "").strip()
_KPL_APP_DEVICEID = os.environ.get("QUANT_BOARD_KPL_APP_DEVICEID", "").strip()
_KPL_APP_TOKEN = os.environ.get("QUANT_BOARD_KPL_APP_TOKEN", "").strip()
if not (_KPL_APP_USERID and _KPL_APP_DEVICEID and _KPL_APP_TOKEN):
    logging.getLogger(__name__).warning(
        "KPL App 凭据缺失（QUANT_BOARD_KPL_APP_USERID/_DEVICEID/_TOKEN 未配置于 "
        "quant-board/.env.local）：登录态端点将结构化降级（login_expired），不伪装数据")

# 开盘啦共用鉴权身份（UserID/DeviceID/Token）的**公共出口**：kpl_theme_fetch 等同账号
# 体系端点从这里取，禁止另拷一份凭据常量（单一事实源；Token 失效只改 .env.local 一处）。
KPL_APP_BASE_PARAMS = {
    **_LONGHUVIP_PARAMS,
    "UserID": _KPL_APP_USERID,
    "DeviceID": _KPL_APP_DEVICEID,
    "Token": _KPL_APP_TOKEN,
}

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
# 2026-11-19 用户裁决：全部 KPL 直连，wzslinker 代理一律清理（代理随时断链=单点故障）。
# 原 wzs 题材目录 dump（kpl_theme_data.js）仅作「新 ID/改名」提示源，成分主体本就走
# 官方 InfoGet 直连；现退役该第三方提示源，新 ID/改名发现回落盲扫
# （directory_scan_ahead）+ 官方 InfoGet，结构化披露不伪装（fail-visible）。


def _apply_theme_directory_diff(database: Any, repo: Any, result: Any) -> None:
    """目录 diff 提示源已退役（2026-11-19 全直连裁决，wzs 目录 dump 清理）。

    无第三方目录源；新 ID/改名发现由盲扫（directory_scan_ahead）+ 官方 InfoGet 承担。
    保留 result 字段结构化披露退役状态，不影响主刷新（fail-visible 不伪装）。
    """
    result.directory_diff_attempted = True
    result.directory_diff_error = (
        "wzs_directory_hint_retired: 全直连裁决清理第三方目录源；"
        "新ID/改名回落盲扫+官方InfoGet")


def _fetch_theme_detail(theme_id: str) -> dict[str, Any] | None:
    """调用 longhuvip API 获取单个题材的完整数据。"""
    # 凭据随公共出口注入（2026-11-15 凭据外移 .env.local 后，_LONGHUVIP_PARAMS 不再自带
    # UserID/DeviceID/Token；登录态校验端点拒游客，缺失会批量 errcode≠0 → directoryDiffFailedIds 膨胀）
    params = {
        **_LONGHUVIP_PARAMS,
        **{k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")},
        "ID": str(theme_id),
    }
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

    # 从 StockList 提取 tags + 题材内热度（HotNum：KPL 个股在该题材的当日人气，
    # 治理 P3 2026-10-25 前被丢弃；落库供主题材判定/审计，缺失=无该字段不伪造）
    hot_by_code: dict[str, int] = {}
    for item in stock_list:
        code = str(item.get("StockID") or "").strip()
        hot = item.get("HotNum")
        if code and isinstance(hot, (int, float)) and not isinstance(hot, bool):
            hot_by_code[code] = int(hot)
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
                "hot": hot_by_code.get(code),
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
        # 目录 diff（提示源已退役 2026-11-19 全直连裁决；回落盲扫+官方 InfoGet）
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
    3. 目录 diff（提示源已退役 2026-11-19 全直连裁决）：原第三方目录对照→现结构化退役披露，新 ID/改名
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

    # 3. 目录 diff（提示源已退役）：新 ID/改名回落盲扫+官方 InfoGet，
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
                    help="只跑目录 diff（提示源已退役→结构化披露；新 ID/改名靠盲扫+官方 InfoGet）")
    args = ap.parse_args(argv)
    out = refresh_theme_stock_mappings(diff_only=args.diff_only)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
