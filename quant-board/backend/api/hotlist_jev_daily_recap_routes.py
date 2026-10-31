# -*- coding: utf-8 -*-
"""复盘日报读口（JEV 叙事工作台【复盘日报】页，2026-10-31）。

- GET /api/hotlist-jev/daily-recap?date=YYYY-MM-DD：读 `hotlist_jev_daily_recap` 当日文档
  （完整投影，含 text/summary/语料块，供选中日叙事表格与详情卡）。
- GET /api/hotlist-jev/daily-recap?start=&end=：区间列表模式（轻量投影，一天一行，供
  日期列表；与连板情绪页 series 同构）。只列 ok 文档；缺参 → 422；读库异常 → 502。
- 纯读零副作用、零 jev 调用：日报由 operations.jev_daily_recap（盘后 CLI/排程链）产出落库。
- 单日缺文档 → {ok, missing:true, missingReason}（fail-visible，不空伪装 §4.0）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])

_MISSING_REASON = ("当日复盘日报未生成（盘后链未执行 / pilot 期未到 / 非交易日；"
                   "原料不足日不产出不伪造，fail-visible）")

_QUESTIONS = ("plan_bias", "play_style", "avoid_focus", "key_watch")


def _light_row(doc: dict[str, Any]) -> dict[str, Any]:
    """区间列表行投影：日期 + 四题档位与来源 + 一致数 + 版本（不投影 text/summary 重载荷）。"""
    answers = doc.get("answers") or {}
    rule = doc.get("ruleAnswers") or {}
    agree, tot = 0, 0
    row: dict[str, Any] = {"date": doc.get("date") or doc.get("_id")}
    for q in _QUESTIONS:
        a = answers.get(q) or {}
        row[q] = a.get("choice")
        row[f"{q}Source"] = a.get("source")
        tot += 1
        if a.get("choice") is not None and a.get("choice") == rule.get(q):
            agree += 1
    row.update({
        "agree": agree, "questionTotal": tot,
        "questionSetVersion": doc.get("questionSetVersion"),
        "templateVersion": doc.get("templateVersion"),
        "skippedJev": doc.get("skippedJev"),
        "generatedAt": doc.get("generatedAt"),
    })
    return row


@router.get("/daily-recap")
def get_daily_recap(date: str | None = None, start: str | None = None,
                    end: str | None = None) -> Any:
    if not date and not (start and end):
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date or start/end"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        col = db["hotlist_jev_daily_recap"]
        if start and end:
            docs = list(col.find({"_id": {"$gte": start, "$lte": end}, "ok": True}))
            docs.sort(key=lambda d: str(d.get("_id")))
            return {"ok": True, "start": start, "end": end,
                    "series": [_light_row(d) for d in docs]}
        doc = col.find_one({"_id": date})
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
    if not doc or doc.get("ok") is not True:
        return {"ok": True, "date": date, "missing": True, "missingReason": _MISSING_REASON}
    doc.pop("_id", None)
    return {"ok": True, "date": date, "missing": False, "report": doc}
