# -*- coding: utf-8 -*-
"""涨停打标轨道读口（研究↔展示同步 2026-10-03）。

- GET /api/hotlist-jev/limitup-labels?date=YYYY-MM-DD：单日读口——
  个股四题标签（driver/depth/freshness/buySide + 概率 + 韦研/热榜语境）
  + 日级相位哨兵 + 分布小结；该日无文档 no_data=true（fail-visible，不伪造空成功）。

纯读；聚合逻辑见 services/jev/jev_limitup_labels（独立路由文件，避开 hotlist_jev_routes 在途改动）。
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory
from backend.api.jev_view_date import resolve_view_date
from backend.services.jev.jev_limitup_labels import PHASE_ORIGIN, collect_limitup_labels

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/limitup-labels")
def get_limitup_labels(date: str, with_raw: int = 0) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        # 盘中回退（2026-10-27 用户裁决）：指定日无打标存档（盘前/非交易日/打标链未跑）
        # → 整体回退 < 指定日最新有档交易日，后续梯队/板块信息/连板/反包 join 全部
        # 跟随生效日同口径，date 字段透出实际生效日 + dateFallback 标记。
        date, date_fallback = resolve_view_date(
            db["hotlist_jev_driver_labels"], date,
            {"origin": {"$ne": PHASE_ORIGIN}})
        # with_raw=1（relay_page 调用日志展开用）：个股条目附带 narrative/questionsRaw 等
        # 原始调用字段；默认 0 保持既有合同（根前端消费方零变化）
        result = collect_limitup_labels(db, date, with_raw=bool(with_raw))
        if date_fallback:
            result["dateFallback"] = date_fallback
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
        # 2026-10-21 用户报障修复：盘中只有 {date}:midday 午盘名单（12:30 投喂槽），
        # final 缺失导致封板时间/原因/高度/领涨四列恒空 → 开启午盘兑底，
        # 并以 boardJoinSlot=midday 显式注记口径（不冒充收盘，§4.0）
        try:
            from backend.operations.jev_label_jiuyan import jiuyan_board_info, jiuyan_streak_map
            board_info, meta = jiuyan_board_info(db, date, allow_midday_fallback=True)
            # 降级优先级：final+midday 双缺 > 今日炸板池缺 > 昨日池缺 > 昨日炸板池缺；
            # 午盘兑底生效时不算「final 缺失」降级（数据在，口径不同，由 boardJoinSlot 注记），
            # 但 THS/prev 池降级仍独立检查（盘中 15:00 池本不存在，必须 fail-visible）
            if meta.get("middayFallbackUsed"):
                result["boardJoinSlot"] = "midday"
            elif not meta.get("jiuyanFinalFound"):
                result["boardJoinDegraded"] = "jiuyan_final_missing"
            if not result.get("boardJoinDegraded"):
                if not meta.get("thsPoolFound"):
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
                    # 涨停原因（2026-10-20 用户需求）：韭研异动解析首行（如 603278
                    # 「人形机器人（金属腱绳）+商业航天+光伏+轮胎」）；缺失 → None（前端 '-'，不伪造）
                    stock["reason"] = info.get("reason")
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
                    if info.get("zhabanResealed"):
                        # 尾盘回封口径注记（2026-10-29）：炸板池命中但收盘价证实回封，
                        # 按涨停计；前端可展示注记（fail-visible，不冒充普通封板）
                        stock["zhabanResealed"] = True
                    if info.get("excluded"):
                        stock["excluded"] = info["excluded"]
            # 2026-10-19 增补（用户报障：涨停复盘 KPI 四板以上/最高板显示的是空间最高板）：
            # 真连板口径与 market_metrics 同源 jiuyan_streak_map（N==M 直取 /
            # N>M 回溯 / num=None→首板 1；断板回溯不可算→None 不冒充；今日炸板→None）。
            # boards 保留「N天M板」空间口径作注记；KPI 分桶/筛选/排序改吃 streak。
            streaks = jiuyan_streak_map(db, date, allow_midday_fallback=True)
            for stock in result.get("stocks") or []:
                code6 = str(stock.get("code") or "")[-6:]
                if code6 in streaks:
                    stock["streak"] = streaks[code6]
            # 反包板池读口（2026-10-21 立项 R2，jev-rewrap-factor-preregistration.md）：
            # KPI 统计 + 池内股标记（前端点击 KPI 卡筛选明细）；口径随 boardJoinSlot——
            # 盘中=午盘触板口径（触板≠封板，与 EOD 不可直接比），盘后=封板口径。
            # 计算单源 = analysis/hotlist/rewrap_pool.build_rewrap_pool（快照集合仅审计）；
            # 失败不阻断主读口（fail-visible：result["rewrap"]=None）
            try:
                from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool
                from backend.operations.rewrap_pool import get_rewrap_pool
                rw_slot = "midday" if result.get("boardJoinSlot") == "midday" else "final"
                rw = build_rewrap_pool(db, date, rw_slot)
                rewrap_set = set(rw.get("rewrapCodes") or [])
                for stock in result.get("stocks") or []:
                    if str(stock.get("code") or "")[-6:] in rewrap_set:
                        stock["rewrap"] = True
                result["rewrap"] = {
                    "slot": rw_slot, "caliber": rw.get("caliber"),
                    "candidate": rw.get("candidateN"), "count": rw.get("rewrapN"),
                    "rate": rw.get("rewrapRate"),
                    "ratePct20d": ((get_rewrap_pool(db, date, rw_slot) or {}).get("ratePct20d")
                                   if rw.get("rewrapRate") is not None else None),
                    "reseal": ({"n": rw.get("resealN"), "total": rw.get("prevFailedN"),
                                "rate": rw.get("resealRate")}
                               if rw.get("prevFailedFound") else None),
                    "missing": rw.get("missing"), "stocks": rw.get("stocks"),
                }
            except Exception as exc:  # noqa: BLE001 — 不阻断主读口，但不得裸吞（审查 SF5）
                import sys as _sys
                print(f"[rewrap] 读口构建失败（fail-visible）: {type(exc).__name__}: {exc}",
                      file=_sys.stderr)
                result["rewrap"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            # THS 炸板池总数（含韭研未收录股，炸板卡「榜外」差额注记用）
            if meta.get("thsZhabanTotal") is not None:
                result["thsZhabanTotal"] = meta["thsZhabanTotal"]
            # 2026-10-12 增补：板块领涨（龙一/二/三，与 relay 题材梯队表同规 dragon_rows 单源）。
            # 板块键=board_info 的 boardName（同出自韭研 final fields.name，缺失回退打标 ctx board）；
            # final 缺失 → 空 map → 行内空数组，前端显示 '-'（降级面由 boardJoinDegraded 注记）
            # 2026-10-15：dragon_rows 增带 code，前端据此只渲染与本行 code 相同的那条龙序
            # （「领涨」列从「板块龙一二三全列」改为「本股身位」，非领涨股显示 '-'）
            from backend.operations.jev_label_jiuyan import jiuyan_board_dragons
            dragons = jiuyan_board_dragons(db, date, allow_midday_fallback=True)
            for stock in result.get("stocks") or []:
                stock["boardDragons"] = dragons.get(
                    stock.get("boardName") or stock.get("board") or "") or []
        except Exception as exc:  # noqa: BLE001 — 辅助 join 失败不阻断主读口（fail-visible 结构化旗标）
            result["boardJoinError"] = f"board_join_failed: {exc}"
        return result
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})


# ── 题材层「板块龙头隔日连板」投喂读口（2026-10-20 加） ──
# 集合：hotlist_jev_theme_leader_labels（17:30 每日投喂，2026-10-30 改时 / 或 scripts/theme_leader_pilot_eval 回填）
# 目的：让「v2 题目集 + 实际投喂的语料」在前端可见（研究↔展示同步，AGENTS §1.2-5）。
# 纯读；无文档 → no_data=true（fail-visible，不伪造空成功）。
@router.get("/theme-leaders")
def get_theme_leaders(date: str | None = None, start: str | None = None,
                      end: str | None = None, with_narrative: int = 0) -> Any:
    """龙头投喂读口：逐只结构事实 + 过门后答案 + 模型原答 + （可选）叙事全文。

    两种查询形态（二选一）：
    - `date=YYYY-MM-DD`：单日（根前端 JevNarrativePanel 消费，合同不变）；
    - `start`/`end`：闭区间（relay_page【题材龙头】子页与连板指数时间范围控件共用）。
      两参可只给其一（start=只看某日之后；end=只看某日之前）。

    - `with_narrative=1`：附带 `narrative`（实际投喂给 jev 的语料全文）与 `questionsRaw`
      （v2 题目集原文）——用于前端「投喂语料」抽屉；
    - `evidenceMissingReason` / `gate.reason` 逐只透出（口径差异必须人眼可见）；
    - `sampleOrigin` 区分 live 前瞻 / backfill 回填（回填含语料未来信息，不得当结论）；
    - `leaderSuperseded=True`（单一龙头对账退位行，2026-10-24）默认**不返回**——同一
      (date, board) 只出现任推导龙一；退位数在 `supersededCount` 披露（审计直接查库）。
    """
    # 无参 = 全量（relay_page 时间范围选「全部」时 start/end 均空）；根前端始终带 date。
    # date 与 start/end 同给时 date 优先（docstring 二选一契约）。
    try:
        db = repository_factory.get_runtime_mongodb_database()
        col = db["hotlist_jev_theme_leader_labels"]
        query: dict[str, Any] = {}
        if date:
            query["tradingDate"] = date
        else:
            rng: dict[str, Any] = {}
            if start:
                rng["$gte"] = start
            if end:
                rng["$lte"] = end
            if rng:
                query["tradingDate"] = rng
        # P2 修复（2026-10-20 review）：无区间全量加默认上限——relay_page 60s 轮询
        # 「全部」时无界拉取会随集合增长线性放大；上限 500 档（≈两个月），截断显式回显。
        cursor = col.find(query).sort([("tradingDate", -1), ("board", 1), ("code", 1)])
        if not query:
            cursor = cursor.limit(500)
        docs = list(cursor)
        truncated = bool(not query) and len(docs) >= 500
        if not docs:
            return {"ok": True, "date": date, "no_data": True, "leaders": [], "count": 0}
        # v12 A2 拆题：板块级 doc（docKind=sector）不单独出行，按 (date, board) 合入
        # 同板块龙头行的深度/延续字段（v12 龙头行这两题为 None；legacy 行保留自有值回退）
        sector_docs = {(str(d.get("tradingDate")), str(d.get("board"))): d
                       for d in docs if d.get("docKind") == "sector"}
        sector_count = len(sector_docs)
        rows = []
        for d in docs:
            if d.get("docKind") == "sector":
                continue
            ans = (d.get("answers") or {}).get("leader_nextday_continue") or {}
            model_ans = (d.get("modelAnswers") or {}).get("leader_nextday_continue") or {}
            # 键存在但值为 None（skipped 文档 answers=None）时 `d.get("answers", {})` 会返回
            # None → `.get` 崩 → 读口 502（2026-10-23 实测）；统一 `or {}` 模式
            stage = (d.get("answers") or {}).get("catalyst_stage") or {}
            # v12 A2：深度/延续优先取板块级 doc（龙头行 v12 起不再携带）；legacy 行回退自有值
            sec = sector_docs.get((str(d.get("tradingDate")), str(d.get("board"))))
            if sec is not None:
                depth_src = ((sec.get("answers") or {}).get("theme_speculation_depth") or {})
                contn_src = ((sec.get("answers") or {}).get("theme_continuation") or {})
            else:
                depth_src = ((d.get("answers") or {}).get("theme_speculation_depth") or {})
                contn_src = ((d.get("answers") or {}).get("theme_continuation") or {})
            # v12 分轨：main/growth；v12 及以后档缺 segment 显式标 legacy（fail-visible，
            # 不伪装成轨内行）；v11 及以前旧行版本徽章已可辨，不重复标。
            # P1-2（review）：版本号数值比较——字典序 "v9" >= "v12" 为 True 会把 v2-v9 误标 legacy
            def _ver_num(v: Any) -> int:
                try:
                    return int(str(v or "")[1:])
                except (ValueError, TypeError):
                    return 0
            segment = d.get("segment")
            segment_label = segment or (
                "legacy" if _ver_num(d.get("questionSetVersion")) >= 12 else None)
            row = {
                "docId": d.get("_id"),
                "tradingDate": d.get("tradingDate"),
                "code": d.get("code"), "name": d.get("name"), "board": d.get("board"),
                "streak": (d.get("structure") or {}).get("streak"),
                "time": (d.get("structure") or {}).get("time"),
                # 2026-10-27 空间龙一规则：断板反包候选标记 + 10 日涨幅（排序依据）
                "leaderSealedToday": (d.get("structure") or {}).get("leaderSealedToday"),
                "gain10": (d.get("structure") or {}).get("gain10"),
                "boardN": (d.get("structure") or {}).get("boardN"),
                "ladderFollowers": (d.get("structure") or {}).get("ladderFollowers"),
                "prevBoardN": (d.get("structure") or {}).get("prevBoardN"),
                # 落库口径（过门后）= 消费端单一事实源
                "choice": ans.get("choice"),
                "probabilities": ans.get("probabilities"),
                # 模型原答（审计；与落库口径不一致时前端要双显，不得只显示一个）
                "modelChoice": model_ans.get("choice"),
                "modelProbabilities": model_ans.get("probabilities"),
                "catalystStage": stage.get("choice"),
                # v12 分轨：main/growth/legacy（见上）
                "segment": segment,
                "segmentLabel": segment_label,
                # v12 A2：深度/延续合并自板块级 doc（legacy 行回退自有值）
                "themeSpeculationDepth": depth_src.get("choice"),
                "themeSpeculationDepthConfidence": depth_src.get("confidence"),
                "themeContinuation": contn_src.get("choice"),
                "themeContinuationConfidence": contn_src.get("confidence"),
                "sectorDocId": (sec or {}).get("_id"),
                "sectorQuestionSetVersion": (sec or {}).get("questionSetVersion"),
                "leaderHeadroom": ((d.get("answers") or {}).get(
                    "leader_headroom") or {}).get("choice"),
                # v5 四题逐题模型置信度（2026-10-24 用户需求「置信度必须可视化」；
                # 旧代文档缺 confidence 时为 None，前端缺省不显示，fail-visible）；
                # v12 拆题：深度/延续置信度已在上方取板块级 doc（此处不再从龙头行重复取）
                "choiceConfidence": ans.get("confidence"),
                "leaderHeadroomConfidence": ((d.get("answers") or {}).get(
                    "leader_headroom") or {}).get("confidence"),
                # v14（P3 工作流 B）：新龙人气成色（仅弱转强事件股判答；非事件日/旧代=None）
                "reboundPopularity": ((d.get("answers") or {}).get(
                    "leader_rebound_popularity") or {}).get("choice"),
                "reboundPopularityConfidence": ((d.get("answers") or {}).get(
                    "leader_rebound_popularity") or {}).get("confidence"),
                # v12 复盘 audit 标记（2026-10-28 两案：read口透传，页面徽章展示）
                "auditFlag": d.get("auditFlag"),
                "auditNote": d.get("auditNote"),
                "outcomeBoardNNextDay": d.get("outcomeBoardNNextDay"),
                "gate": d.get("gate"),
                # P2-2：结构化引用说明（模型产出才非空；引用义务的程序核验原料）
                "answerReasons": d.get("answerReasons") or {},
                "evidenceMissing": bool(d.get("evidenceMissing")),
                "evidenceMissingReason": d.get("evidenceMissingReason"),
                "evidenceIndustry": d.get("evidenceIndustry"),
                "evidenceEventTitles": d.get("evidenceEventTitles") or [],
                # 2026-11-02：题材新闻命中标题镜像（结构化层可见，与事件徽章同口径）
                "evidenceNewsTitles": d.get("evidenceNewsTitles") or [],
                # v3/v4：板内解析可用性 + Kword 题材标签（开盘啦新闻流）
                # （v5 起 status=skipped 不落库，读口无排除行）
                "evidenceBoardResolved": d.get("evidenceBoardResolved"),
                "evidenceKwordTags": d.get("evidenceKwordTags") or [],
                # 板内解析摘要（2026-10-27 用户裁决：事件列徽章 tooltip 必须可读完整
                # 题材驱动内容，不许「在场」占位话）——从叙事原文抽「板内解析/板内
                # 同伴驱动」行（含龙头驱动标签+解析摘录+同伴驱动全文）；旧档无叙事=None
                "evidenceBoardDigest": "\n".join(
                    ln for ln in str(d.get("narrative") or "").splitlines()
                    if ln.startswith(("板内解析", "板内同伴驱动"))) or None,
                "baselineKey": d.get("baselineKey"),
                "baselineMeta": d.get("baselineMeta"),
                "outcomeSealedNextDay": d.get("outcomeSealedNextDay"),
                "outcomeMeta": d.get("outcomeMeta"),
                # 后日 T+2 打板溢价（settle_day2 回填：openPct/closePct vs T+1 收盘；
                # T+1 断板=无打板入场记 skipped；未到/缺日线=pending 挂链自愈）
                "outcomeDay2": d.get("outcomeDay2"),
                "status": d.get("status"),
                "sampleOrigin": d.get("sampleOrigin") or "live",
                "questionSetVersion": d.get("questionSetVersion"),
                "questionSetHash": d.get("questionSetHash"),
                "ammoVersion": d.get("ammoVersion"),
                "usage": d.get("usage"),
                "latencyMs": d.get("latencyMs"),
                "model": d.get("model"),
                "computedAt": d.get("computedAt"),
                "errorCode": d.get("errorCode"),
                "errorDetail": d.get("errorDetail"),
            }
            if with_narrative:
                row["narrative"] = d.get("narrative")
                row["questionsRaw"] = d.get("questionsRaw")
                row["responseRaw"] = d.get("responseRaw")
                if sec is not None:
                    row["sectorNarrative"] = sec.get("narrative")   # 板块级叙事（双龙一并列）
            if d.get("leaderSuperseded"):
                row["_superseded"] = True   # 内部标记：下行过滤掉，不出响应
            rows.append(row)
        # P2（题材周期状态机，Q8/Q9 裁决）：join 热点周期状态与新龙事件——只加字段
        # 不改既有合同（根前端 JevNarrativePanel 不受影响）。
        # - cycleState：该行 (tradingDate, board, segment) 的状态机当 state；
        # - leaderRebound：该行 code 是否当日 leaderRebound 事件股（Q9:A 只标反包，
        #   benchmarkAdvance 属板块层事件不落到龙一行）；
        # - 状态机未覆盖的日期/板块（cycle 未回填）如实缺省，不伪态。
        cycle_keys = {(str(r.get("tradingDate")), str(r.get("board")),
                       str(r.get("segment") or "main")) for r in rows}
        cycle_map: dict[tuple[str, str, str], dict] = {}
        rebound_map: set[tuple[str, str, str, str]] = set()
        if cycle_keys:
            cd_dates = sorted({k[0] for k in cycle_keys})
            for cd in db["hotlist_jev_theme_cycle"].find(
                    {"tradingDate": {"$in": cd_dates}},
                    {"tradingDate": 1, "board": 1, "segment": 1, "state": 1,
                     "stateCn": 1, "migrated": 1, "transition": 1,
                     "terminatedOn": 1, "cycleRound": 1}):
                cycle_map[(str(cd.get("tradingDate")), str(cd.get("board")),
                           str(cd.get("segment") or "main"))] = cd
            for wd in db["hotlist_jev_leader_wzs"].find(
                    {"_id": {"$in": cd_dates}}, {"events": 1}):
                for e in wd.get("events") or []:
                    if e.get("type") == "leaderRebound":
                        rebound_map.add((str(wd["_id"]), str(e.get("board")),
                                         str(e.get("segment") or "main"),
                                         str(e.get("code"))))
        for r in rows:
            key = (str(r.get("tradingDate")), str(r.get("board")),
                   str(r.get("segment") or "main"))
            cd = cycle_map.get(key)
            if cd is not None:
                r["cycleState"] = cd.get("state")
                r["cycleStateCn"] = cd.get("stateCn")
                r["cycleMigrated"] = cd.get("migrated")
                r["cycleTrigger"] = ((cd.get("transition") or {}) or {}).get("trigger")
                r["cycleTerminatedOn"] = cd.get("terminatedOn")
                r["cycleRound"] = cd.get("cycleRound")
            r["leaderRebound"] = ((key[0], key[1], key[2], str(r.get("code")))
                                  in rebound_map) or None
        # 单一龙头对账（2026-10-24）：退位行（推导已不再指向的旧任龙头）默认不出——
        # 同 (date, board) 只出现任推导龙一；数量显式披露，审计直接查库
        superseded_count = sum(1 for d in docs if d.get("leaderSuperseded"))
        rows = [r for r in rows if not r.get("_superseded")]
        # 代际/来源分布（跨代混评是硬伤，前端要能一眼看出这天是不是混代）
        versions: dict[str, int] = {}
        origins: dict[str, int] = {}
        for r in rows:
            versions[str(r["questionSetVersion"])] = versions.get(str(r["questionSetVersion"]), 0) + 1
            origins[str(r["sampleOrigin"])] = origins.get(str(r["sampleOrigin"]), 0) + 1
        dates = sorted({str(r.get("tradingDate")) for r in rows if r.get("tradingDate")},
                       reverse=True)
        return {
            "ok": True, "date": date,
            "range": None if date else {"start": start, "end": end},
            "dates": None if date else dates,
            "count": len(rows),
            "sectorCount": sector_count,
            "supersededCount": superseded_count,
            "truncated": truncated,   # 无参全量触顶 500（响应注记，§4.0 不静默截断）
            "versions": versions, "mixedVersions": len(versions) > 1,
            "origins": origins,
            "questionSetHash": rows[0]["questionSetHash"] if rows else None,
            "ammoVersion": rows[0]["ammoVersion"] if rows else None,
            "statusCounts": {s: sum(1 for r in rows if r["status"] == s)
                             for s in {r["status"] for r in rows}},
            "gatedCount": sum(1 for r in rows if (r.get("gate") or {}).get("applied")),
            "sealedCount": sum(1 for r in rows if r.get("outcomeSealedNextDay") is not None),
            "leaders": rows,
        }
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})


class ThemeLeaderRerunPayload(BaseModel):
    """单只龙头-日重跑（页面【重跑】按钮；真实调用 jev ≈5-6K tokens/次（v12 叙事变长）；
    force 下同板块 sector doc 一并重烧再 +≈5K）。"""
    date: str
    code: str
    datasetId: str | None = None


@router.get("/theme-cycle")
def get_theme_cycle(date: str | None = None, start: str | None = None,
                    end: str | None = None) -> Any:
    """题材周期状态机读口（P2，每板块×轨每日一文档 hotlist_jev_theme_cycle）。

    - `date=YYYY-MM-DD`：单日；`start`/`end`：闭区间（与 theme-leaders 同形态）。
    - 迁移落痕（from/to/trigger/evidence）随行透出（fail-visible）。
    - 与 jev 深度三层的联立在【题材龙头】台账行内并列披露（Q8:A），本读口只出结构态。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
        query: dict[str, Any] = {}
        if date:
            query["tradingDate"] = date
        else:
            rng: dict[str, Any] = {}
            if start:
                rng["$gte"] = start
            if end:
                rng["$lte"] = end
            if rng:
                query["tradingDate"] = rng
        docs = list(db["hotlist_jev_theme_cycle"].find(query).sort(
            [("tradingDate", -1), ("board", 1), ("segment", 1)]))
        return {"ok": True, "date": date,
                "range": None if date else {"start": start, "end": end},
                "rows": docs, "count": len(docs)}
    except Exception as exc:   # noqa: BLE001 — 读口统一 502 范式
        return JSONResponse(status_code=502, content={
            "ok": False, "error": f"theme-cycle 读口异常：{exc}"})


@router.post("/theme-leaders/rerun")
def post_theme_leader_rerun(payload: ThemeLeaderRerunPayload) -> dict[str, Any]:
    """单只龙头-日**重跑**（2026-10-20 用户需求，对齐 relay-index/rerun 范式）：

    - 复用生产投喂入口 ``theme_leader_label.run``（叙事拼装 + ``_dispatch_jev``），
      ``codes`` 过滤只重建命中的龙头（不过滤会整日重跑烧 30K+ tokens）；
    - ``force=True`` 覆盖幂等（status=ok 档也重判）；失败照常落 degraded 文档；
    - 「本次是否真重判」以 ``computedAt`` 是否刷新为准（F6）：code 不在该日龙头集合、
      或 jev 通道不可达时**显式报错**，不得用旧档冒充成功（§4.0）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    date = (payload.date or "").strip()
    code = (payload.code or "").strip()
    if not date or not code:
        return {"ok": False, "errorCode": "bad_payload", "error": "date and code required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
        from backend.operations.theme_leader_label import COLLECTION, SAMPLE_ORIGIN_LIVE, run

        col = db[COLLECTION]
        # P1 修复（2026-10-20 review）：before 带出 sampleOrigin —— 重跑必须透传旧档起源，
        # 否则 run() 默认 live 会把 backfill 档静默翻成 live（泄漏进前瞻合计，破坏分组隔离）。
        before = col.find_one({"_id": f"{date}:{code}"}, {"computedAt": 1, "sampleOrigin": 1})
        before_at = (before or {}).get("computedAt")
        # P1 修复：datasetId 缺省必须用 DEFAULT_DATASET_ID（传 None 会查不到 snapshot_frames，
        # 重跑叙事的盘面事实行恒降级，且 force 覆盖掉原 ok 档）。
        summary = run(date, confirm_budget=True, force=True,
                      codes={code},
                      dataset_id=payload.datasetId or DEFAULT_DATASET_ID,
                      sample_origin=(before or {}).get("sampleOrigin") or SAMPLE_ORIGIN_LIVE)
        doc = col.find_one({"_id": f"{date}:{code}"})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"theme_leader_rerun_failed: {exc}"}
    if doc is None:
        return {"ok": False, "errorCode": "not_written",
                "error": f"{date}:{code} 无存档（该 code 不在当日龙头集合，或韭研 final 缺失）"}
    if before is not None and doc.get("computedAt") == before_at:
        return {"ok": False, "errorCode": "not_rerun",
                "error": f"{date}:{code} computedAt 未刷新（入口跳过或幂等命中，未真重判）"}
    return {
        "ok": True,
        "summary": {"labeled": summary.get("labeled"), "okCount": summary.get("ok"),
                    "degraded": summary.get("degraded"),
                    "tokensUsed": summary.get("tokensUsed")},
        "doc": {
            "tradingDate": doc.get("tradingDate"), "code": doc.get("code"),
            "name": doc.get("name"), "board": doc.get("board"),
            "status": doc.get("status"),
            "sampleOrigin": doc.get("sampleOrigin"),
            "choice": ((doc.get("answers") or {}).get("leader_nextday_continue") or {}).get("choice"),
            "gate": doc.get("gate"),
            "model": doc.get("model"), "usage": doc.get("usage"),
            "latencyMs": doc.get("latencyMs"),
            "errorCode": doc.get("errorCode"), "errorDetail": doc.get("errorDetail"),
            "computedAt": doc.get("computedAt"),
        },
    }


# ── 涨停复盘个股驱动打标「单股复跑」（2026-10-21 用户需求，日志详情卡【重跑】） ──
# 范式对齐 /theme-leaders/rerun（F6：computedAt 未刷新=未真重判，显式报错不冒充成功）。
class LimitupLabelRerunPayload(BaseModel):
    """单只个股-日驱动打标重跑（真实调用 jev ≈2K tokens/次）。"""
    date: str
    code: str
    datasetId: str | None = None


@router.post("/limitup-labels/rerun")
def post_limitup_label_rerun(payload: LimitupLabelRerunPayload) -> dict[str, Any]:
    """单股**重跑**驱动打标（涨停复盘行展开日志详情卡【重跑】按钮）：

    - 复用生产打标入口 ``jev_label_jiuyan.run``（``force=True`` + ``only_codes`` 单股过滤，
      不带 only_codes 会整日重烧 ≈21 万 tokens）；
    - 槽位沿用旧档 ``labelSlot``（midday 档沿午盘口径重判；伪午盘/名单缺失显式报错）；
    - 旧档带 phaseBand（五题合并代际）→ ``with_stock_phase=True`` 同 call 重建，相位不丢；
    - ``force=True`` 覆盖幂等；失败照常落 degraded 或不覆盖（computedAt 未刷新 → not_rerun）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    date = (payload.date or "").strip()
    code = (payload.code or "").strip()[-6:]
    if not date or not code:
        return {"ok": False, "errorCode": "bad_payload", "error": "date and code required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
        from backend.operations.jev_label_jiuyan import (
            DEFAULT_ACCOUNT_ID, SLOT_MIDDAY, midday_source_state, run)

        col = db["hotlist_jev_driver_labels"]
        before = col.find_one({"_id": f"{date}:{code}"})
        if before is None:
            return {"ok": False, "errorCode": "not_found",
                    "error": f"{date}:{code} 无驱动打标存档（该 code 不在当日名单）"}
        slot = before.get("labelSlot") if before.get("labelSlot") in ("final", "midday") else "final"
        if slot == SLOT_MIDDAY:
            state = midday_source_state(db, date)
            if not state["ok"]:
                return {"ok": False, "errorCode": "midday_not_feedable",
                        "error": f"午盘名单不可投喂（{state['reason']}）：{state['detail']}"
                                 f"；该档不可按午盘口径重判，走收盘链投喂"}
        before_at = before.get("computedAt")
        tok = os.environ.get("JEV_CF_TOKEN") or ""
        acc = os.environ.get("JEV_CF_ACCOUNT", DEFAULT_ACCOUNT_ID)
        run(date, date, False, tok, acc, workers=1,
            with_stock_phase=bool(before.get("phaseBand")),
            dataset_id=payload.datasetId or DEFAULT_DATASET_ID,
            confirm_budget=True, force=True, only_codes={code}, slot=slot)
        doc = col.find_one({"_id": f"{date}:{code}"})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"limitup_label_rerun_failed: {exc}"}
    if doc is None or doc.get("computedAt") == before_at:
        return {"ok": False, "errorCode": "not_rerun",
                "error": f"{date}:{code} computedAt 未刷新（入口跳过或两次 jev 调用均失败，未真重判）"}
    return {
        "ok": True,
        "doc": {
            "tradingDate": doc.get("tradingDate"), "code": doc.get("code"),
            "name": doc.get("name"), "labelSlot": doc.get("labelSlot"),
            "status": doc.get("status"), "label": doc.get("label"),
            # 2026-10-22 用户报障修复：返回档补 freshness/depth/buySide（此前复跑后详情卡
            # 横幅只回显驱动标签，新鲜度/深度/买盘变化不可见，用户误判复跑未生效）
            "catalystDepth": doc.get("catalystDepth"),
            "freshness": doc.get("freshness"),
            "buySideLogic": doc.get("buySideLogic"),
            "questionSetVersion": doc.get("questionSetVersion"),
            "errorCode": doc.get("errorCode"), "errorDetail": doc.get("errorDetail"),
            "model": doc.get("model"), "usage": doc.get("usage"),
            "latencyMs": doc.get("latencyMs"), "computedAt": doc.get("computedAt"),
        },
    }
