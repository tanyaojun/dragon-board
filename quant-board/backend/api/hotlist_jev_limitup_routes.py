# -*- coding: utf-8 -*-
"""涨停打标轨道读口（研究↔展示同步 2026-10-03）。

- GET /api/hotlist-jev/limitup-labels?date=YYYY-MM-DD：单日读口——
  个股四题标签（driver/depth/freshness/buySide + 概率 + 韦研/热榜语境）
  + 日级相位哨兵 + 分布小结；该日无文档 no_data=true（fail-visible，不伪造空成功）。

纯读；聚合逻辑见 services/jev/jev_limitup_labels（独立路由文件，避开 hotlist_jev_routes 在途改动）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory
from backend.services.jev.jev_limitup_labels import collect_limitup_labels

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/limitup-labels")
def get_limitup_labels(date: str, with_raw: int = 0) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        # with_raw=1（relay_page 调用日志展开用）：个股条目附带 narrative/questionsRaw 等
        # 原始调用字段；默认 0 保持既有合同（根前端消费方零变化）
        result = collect_limitup_labels(db, date, with_raw=bool(with_raw))
        # 2026-10-10 增补：梯队分布（韭研主源双源口径，只增字段向后兼容）
        try:
            from backend.operations.jev_label_jiuyan import _jiuyan_ladder
            ladder = _jiuyan_ladder(db, date)
            if ladder:
                result["ladder"] = {k: v for k, v in ladder.items() if not k.startswith("_")}
                result["ladderPoolTotal"] = ladder.get("_poolTotal")
                # 漏标计数透传公开键（fail-visible：日级漏标面可见，不再只留在 _ 私有键）
                result["ladder"]["dayUnmarked"] = ladder.get("_dayUnmarked")
                result["ladder"]["dayUnmarkedPrev"] = ladder.get("_dayUnmarkedPrev")
        except Exception:
            result["ladder"] = None  # 梯队失败不阻断标签读口（fail-visible）
        # 2026-10-10 增补：个股高度/封板时间/板块 + 漏标连板标记
        # （join 抽 jev_label_jiuyan.jiuyan_board_info，与 _jiuyan_ladder 同口径；
        #   失败/降级置结构化旗标，不阻断主读口，前端据旗标注记高度口径状态）
        try:
            from backend.operations.jev_label_jiuyan import jiuyan_board_info, jiuyan_streak_map
            board_info, meta = jiuyan_board_info(db, date)
            if not meta.get("jiuyanFinalFound"):
                result["boardJoinDegraded"] = "jiuyan_final_missing"
            elif not meta.get("thsPoolFound"):
                # 今日炸板池缺失 → 触板名单无法二分，涨停口径退化为触板口径（最严重，优先暴露）
                result["boardJoinDegraded"] = "ths_pool_missing"
            elif not meta.get("prevPoolFound"):
                # 昨日池轴缺失 → 漏标判定不可用，漏标股会落回首板口径（必须可见）
                result["boardJoinDegraded"] = "prev_pool_missing"
            elif meta.get("prevThsPoolFound") is False:
                # 昨日炸板池缺失 → 漏标判定不可信（宁漏标不误标，已置空 prev_sealed）
                result["boardJoinDegraded"] = "prev_ths_pool_missing"
            for stock in result.get("stocks") or []:
                info = board_info.get(str(stock.get("code") or "")[-6:])
                if info:
                    stock["boards"] = info["boards"]
                    # 2026-10-15 增补：days=num「N天M板」的 N（跨度天数），与 boards 一并透传，
                    # 前端「高度」列拼「N天M板」（5天5板）；None=num 不可解析，前端回落「M板」不猜天数
                    stock["days"] = info.get("days")
                    stock["limitUpTime"] = info["limitUpTime"]
                    stock["boardName"] = info["boardName"]
                    if info.get("boardUnmarked"):
                        stock["boardUnmarked"] = True
                    if info.get("zhaban"):
                        stock["zhaban"] = True
                        if info.get("openNum") is not None:
                            stock["openNum"] = info["openNum"]
                    if info.get("excluded"):
                        stock["excluded"] = info["excluded"]
            # 2026-10-19 增补（用户报障：涨停复盘 KPI 四板以上/最高板显示的是空间最高板）：
            # 真连板口径与 market_metrics/quotes-review 同源 jiuyan_streak_map（N==M 直取 /
            # N>M 回溯 / num=None→首板 1；断板回溯不可算→None 不冒充；今日炸板→None）。
            # boards 保留「N天M板」空间口径作注记；KPI 分桶/筛选/排序改吃 streak。
            streaks = jiuyan_streak_map(db, date)
            for stock in result.get("stocks") or []:
                code6 = str(stock.get("code") or "")[-6:]
                if code6 in streaks:
                    stock["streak"] = streaks[code6]
            # THS 炸板池总数（含韭研未收录股，炸板卡「榜外」差额注记用）
            if meta.get("thsZhabanTotal") is not None:
                result["thsZhabanTotal"] = meta["thsZhabanTotal"]
            # 2026-10-12 增补：板块领涨（龙一/二/三，与 relay 题材梯队表同规 dragon_rows 单源）。
            # 板块键=board_info 的 boardName（同出自韭研 final fields.name，缺失回退打标 ctx board）；
            # final 缺失 → 空 map → 行内空数组，前端显示 '-'（降级面由 boardJoinDegraded 注记）
            # 2026-10-15：dragon_rows 增带 code，前端据此只渲染与本行 code 相同的那条龙序
            # （「领涨」列从「板块龙一二三全列」改为「本股身位」，非领涨股显示 '-'）
            from backend.operations.jev_label_jiuyan import jiuyan_board_dragons
            dragons = jiuyan_board_dragons(db, date)
            for stock in result.get("stocks") or []:
                stock["boardDragons"] = dragons.get(
                    stock.get("boardName") or stock.get("board") or "") or []
        except Exception as exc:  # noqa: BLE001 — 辅助 join 失败不阻断主读口（fail-visible 结构化旗标）
            result["boardJoinError"] = f"board_join_failed: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
