# -*- coding: utf-8 -*-
"""KPL 板块身位（龙头三合一）当日实时计算与落库（2026-11-10 用户需求）。

背景（2026-11-10 实测固化）：KPL 官方「当日实时全梯队身位」无可消费上游面——
层3 ``ZhiShuStockList_W8`` 当日盘中 1020（带/不带 Date × apphwhq/apphq 四形态全 1020，
历史日 errcode=0 可用）；3001 混合流 quotas 68 列无身位串/身位列（盘中实帧全列扫描）；
``Section/GetSection`` 龙一/二/三标签的 SectionID 属文章卡 id 空间，801xxx 打入空表；
``XianHuoData/AllXianHuo`` 为商品现货目录非题材卡。live-stocks-meta 盘中只能探测回退
上一交易日构建（fb 只在概念列 tooltip 透出），前端「昨日身位 + 今日行情」同页混日
误读。用户裁决（2026-11-10）：标注是骗自己，要当日实时身位，还要落库；排序口径 =
自家龙头三合一（涨停打标 / 板块节点 / 题材龙头，v12 空间龙一排序），我们自己的最
权威，不做官方对照列。

口径（三合一单源纪律：排序复用 ``rank_board_stocks_seal``，禁止第二套实现）：
- 候选池 = 当日封板池（kpl_daban_pool 当日档 pool_state='sealed'，炸板 broken 不算
  封板——与韭研「触板−炸板二分」同哲学）∪ 近 3 个交易日封板池（断板反包覆盖）；
  按 ``plate_id``（2103 quotas[21] 涨停原因关联板块，KPL 板块体系 801xxx）分组，
  跨板块各排各的（与 relay 题材梯队表 _boards_of 分组口径一致）；
- 身位序列 = 龙一锚（主轨空间龙一：``rank_board_stocks_seal`` 全序 + ``segment_of``
  取 main 轨首位，纯双创板块取 growth 轨首位——与节点档 _collapse_segment_rows
  同构）+ 龙二..龙N（其余候选按 ``dragon_rows`` 口径：区间板数 M 降序 → 首封时间
  升序，M 缺失垫后、time 缺失垫底；``dragon_rows`` 只出 top3 不能直接复用全序列，
  排序键与其 lambda 逐字同构、M 解析复用 ``_jiuyan_board_count``）；
- height = 当日 streak 与近 3 日历史高度取大（rank_board_stocks_seal ①空间板组）；
  streak = 连续封板交易日数（池日档自算）；断板候选 ``sealed_today=False`` 如实注记；
- 断板不反包且今日跌停剔除：``limit_rules.is_limit_down_pct``（公共权威源，非硬编码；
  涨跌幅原料与题材链同款 TDX 日线当日 bar——注意涨跌幅阈值容差 0.2pp（-9.8/-19.8/
  -29.8）与题材链硬编码 -9.9/-19.9 略有差异，以公共函数为准）；
- gain10 = ``fetch_gains10``（TDX，与三合一链同一缓存哲学：当日 bar 首拉冻结，盘面
  事实行全日一致）；gain 不可考候选按 -inf 参与排序（rank_board_stocks_seal 原生语义），
  板块级 ``gain_unavailable`` 披露，**不整板块跳过**（与 upstream spaceErrors 跳过
  裁决的差异：身位榜是展示层，展示可计算部分 + 缺失位置，整板块隐身违反 §4.0）。

fail-visible：候选空 / 池日档缺日 / plate_id 缺失 / gain 缺失 / 跌停剔除全部结构化
透出，不伪装成功、不伪造身位。写入 ``kpl_daban_pool`` 日档 lead_ 前缀字段（字段级
$set，单写者 = DabanPoolArchiver 循环，与 gene/notice 通道同款并发合同）。
读口：``GET /api/kpl/daban-lead?date=``（load_day lane='lead' 委托 load_lead_corpus）。
本通道只供展示链消费，不进 jev 语料叙事（§1.2.8 纪律：接进题面/判据属方案变更须走
hotlist-jev 预登记）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from backend.core.limit_rules import is_limit_down_pct
from backend.analysis.hotlist.theme_leader_ammo import (
    rank_board_stocks_seal,
    segment_of,
)
from backend.operations.jev_label_jiuyan import _jiuyan_board_count, trading_dates_before
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

_COLLECTION = "kpl_daban_pool"
LEAD_SOURCE = "leader_trinity_v1"
POOL_LOOKBACK_DAYS = 3            # 断板反包回溯池（与三合一链 pool_dates 同参）

# 涨跌幅/日线取数默认实现 = 题材链同款 TDX（同进程单一事实源，不复制第二套实现）：
# gain10 → fetch_gains10；断板候选当日涨跌幅 → theme_leader_baseline 的 TDX 日线取数。
def _default_gains_fetcher(codes: list[str], date: str) -> dict[str, float | None]:
    from backend.operations.tdx_daily_bars import fetch_gains10
    return fetch_gains10(codes, date)


def _default_day_change_fetcher(codes: list[str], date: str) -> dict[str, float | None]:
    # 私有函数跨模块复用（同进程单源；与题材链当日涨跌幅口径逐字一致）。
    from backend.operations.theme_leader_baseline import _default_day_change_fetcher as _f
    return _f(codes, date)


def _cn_rank(n: int) -> str:
    """1..99 → 中文序数（KPL 官方 [24] 观察写法：一..十、十一..十九、二十..）。"""
    d = "零一二三四五六七八九"
    if 1 <= n <= 10:
        return d[n] if n < 10 else "十"
    if n < 20:
        return "十" + d[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        head = d[tens] + "十" if tens > 1 else "十"
        return head + (d[ones] if ones else "")
    return str(n)


def lead_label(rank: int) -> str:
    """身位标签：1~10「龙一..龙十」，11+ 无「龙」字（与 KPL 官方 [24] 写法一致）。"""
    if rank < 1:
        return ""
    return ("龙" + _cn_rank(rank)) if rank <= 10 else _cn_rank(rank)


def state_boards(state: Any) -> int | None:
    """2103 state 串（「N天M板」/「M连板」/「首板」）→ 区间板数 M；断板/未知 → None（不猜）。

    「M连板」与「N天M板」的 M 同义（真实板数）；「昨日首板/昨N连板」= 断板态返回 None。
    """
    import re
    s = str(state or "").strip()
    m = re.fullmatch(r"(\d+)天(\d+)板", s)
    if m:
        return int(m.group(2))
    m = re.fullmatch(r"(\d+)连板", s)
    if m:
        return int(m.group(1))
    if s == "首板":
        return 1
    return None


def _num_jiuyan_format(state: Any) -> str | None:
    """KPL state 串 → 韭研 num 格式（「N天M板」），供 _jiuyan_board_count 单源解析。

    「M连板」→「M天M板」、「首板」→「1天1板」；断板态/未知 → None（不猜）。
    """
    m = state_boards(state)
    if m is None:
        return None
    return f"{m}天{m}板" if str(state or "").strip() != "首板" else "1天1板"


def _hhmm(zt_time: Any) -> str | None:
    """2103 zt_time（epoch 秒）→ 北京时间 HH:MM；非法 → None（不猜）。"""
    try:
        ts = float(zt_time)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, TZ_SHANGHAI).strftime("%H:%M")


def _day_sealed(db: Any, date: str) -> dict[str, dict[str, Any]]:
    """某日日档封板成员（涨停池通道 pool_state='sealed'）→ {code: 成员 dict}；无档 → {}。

    涨停池通道在 _LANES 里 prefix=""（无前缀 items 字段，与 bid_/zb_/dt_ 不同）。
    """
    row = db[_COLLECTION].find_one({"_id": date}, {"items": 1}) or {}
    out: dict[str, dict[str, Any]] = {}
    for m in row.get("items") or []:
        sid = str(m.get("stock_id") or "")
        if sid and m.get("pool_state") == "sealed":
            out[sid] = m
    return out


def _streak_ending(sealed_by_day: dict[str, set[str]], days_desc: list[str],
                   code: str) -> int:
    """以 days_desc（新→旧）首个含 code 的日为终点向前连续封板天数；不在任何日 → 0。"""
    n = 0
    started = False
    for d in days_desc:
        if code in sealed_by_day.get(d, set()):
            n += 1
            started = True
        elif started:
            break
        elif not started:
            # 尚未起始（code 不在最近封板日）→ 继续向旧日找（断板候选最近封板日在更早）
            continue
    return n


def assemble_candidates(
    db: Any,
    date: str,
    *,
    pool_dates: list[str] | None = None,
    gains_fetcher: Callable[[list[str], str], dict[str, float | None]] | None = None,
    day_change_fetcher: Callable[[list[str], str], dict[str, float | None]] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """组装候选池（当日封板 ∪ 近 3 交易日封板，按最近已知 plate_id 归属）。

    返回 ``(candidates, meta)``；``candidates=None`` = 当日池档不存在（不可计算，
    fail-visible，调用方不写库）。meta 携带 pool_dates/missing_pool_dates/
    missing_plate/limit_down_excluded 等（逐项可审计）。
    """
    meta: dict[str, Any] = {"pool_dates": pool_dates or [], "missing_pool_dates": [],
                            "missing_plate": [], "limit_down_excluded": {},
                            "gain_missing_n": 0}
    today = _day_sealed(db, date)
    if not today and not db[_COLLECTION].find_one({"_id": date}, {"_id": 1}):
        return None, meta
    if pool_dates is None:
        pool_dates = trading_dates_before(db, date, POOL_LOOKBACK_DAYS)
    meta["pool_dates"] = list(pool_dates)
    days_desc = list(reversed(pool_dates))          # 新 → 旧
    sealed_by_day: dict[str, set[str]] = {}
    sealed_members_by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for pd in pool_dates:
        sealed = _day_sealed(db, pd)
        if not sealed and not db[_COLLECTION].find_one({"_id": pd}, {"_id": 1}):
            meta["missing_pool_dates"].append(pd)
        sealed_by_day[pd] = set(sealed)
        # 成员明细同轮预取（评审 P2：避免断板候选逐只重查 _day_sealed）
        sealed_members_by_day[pd] = sealed

    cands: list[dict[str, Any]] = []
    plate_of: dict[str, str] = {}
    # ① 当日封板候选（streak=今日 + 向前连续封板交易日数；今日不在 pool_dates 的
    # sealed_by_day 里，故从 1 起数）
    for code, m in today.items():
        pid = str(m.get("plate_id") or "")
        if pid:
            plate_of[code] = pid
        else:
            meta["missing_plate"].append(code)
        cands.append({
            "code": code, "name": m.get("name"),
            "time": _hhmm(m.get("zt_time")),
            "streak": 1,
            "sealed_today": True,
            "num_state": m.get("state"),
            "plate_id": pid or None,
        })
    for c in cands:
        n = 1
        for pd in days_desc:
            if c["code"] in sealed_by_day.get(pd, set()):
                n += 1
            else:
                break
        c["streak"] = n
    # ② 断板候选：近 3 日曾封、今日未封（断板反包 / 断板不反包）
    today_codes = set(today)
    for pd in days_desc:
        for code in sorted(sealed_by_day.get(pd, set()) - today_codes):
            if any(c["code"] == code for c in cands):
                continue
            m = sealed_members_by_day.get(pd, {}).get(code) or {}
            pid = str(m.get("plate_id") or "")
            if pid:
                plate_of[code] = pid
            elif code not in meta["missing_plate"]:
                meta["missing_plate"].append(code)
            cands.append({
                "code": code, "name": m.get("name"),
                "time": None,               # 今日未封：无当日首封时间（rank_board_stocks_seal 语义）
                "streak": _streak_ending(sealed_by_day, days_desc, code),
                "sealed_today": False,
                "num_state": m.get("state"),
                "plate_id": pid or None,
            })
    if not cands:
        return [], meta
    # ③ height 合成（rank_board_stocks_seal ①）：当日 streak 与近 3 日历史高度取大
    for c in cands:
        code = c["code"]
        hist = _streak_ending(sealed_by_day, days_desc, code) if c["sealed_today"] else c["streak"]
        hs = [h for h in (c["streak"] if c["sealed_today"] else None, hist)
              if isinstance(h, int) and h > 0]
        c["height"] = max(hs) if hs else None
        c["boards"] = state_boards(c.get("num_state"))      # 区间板数 M（dragon_rows 排序键）
    # ④ gain10 + 断板跌停剔除（公共权威源 is_limit_down_pct，非硬编码）
    codes = [c["code"] for c in cands]
    gains = (gains_fetcher or _default_gains_fetcher)(codes, date)
    meta["gain_missing_n"] = sum(1 for c in cands if (gains or {}).get(c["code"]) is None)
    for c in cands:
        c["gain10"] = (gains or {}).get(c["code"])
    unsealed = [c for c in cands if not c["sealed_today"]]
    if unsealed:
        changes = (day_change_fetcher or _default_day_change_fetcher)(
            [c["code"] for c in unsealed], date)
        kept: set[str] = set()
        for c in unsealed:
            chg = (changes or {}).get(c["code"])
            if is_limit_down_pct(chg, c["code"]):
                meta["limit_down_excluded"].setdefault(c["plate_id"] or "?", []).append(
                    {"code": c["code"], "name": c.get("name"), "pct": chg})
            else:
                kept.add(c["code"])          # 涨跌幅不可考 → 保留（不猜）
        cands = [c for c in cands if c["sealed_today"] or c["code"] in kept]
    for c in cands:
        c["plate_id"] = c["plate_id"] or plate_of.get(c["code"])
    return cands, meta


def compute_board_leads(
    cands: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """按 plate_id 分组出全梯队身位（龙一锚 = 三合一空间龙一；龙二.. = dragon_rows 口径）。

    排序单源纪律：龙一序复用 ``rank_board_stocks_seal``（v12 复合排序，禁止第二套）；
    龙二..N 序与 ``dragon_rows`` 排序键逐字同构（M 降序 → 首封时间升序，缺失垫后），
    M 解析复用 ``_jiuyan_board_count``（候选 num_state 与韭研 num 同为「N天M板」格式）。
    纯函数；返回 ({plate_id: {items, n, gain_unavailable}}, meta)。
    """
    boards: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {"gain_unavailable_plates": []}
    by_plate: dict[str, list[dict[str, Any]]] = {}
    for c in cands:
        pid = str(c.get("plate_id") or "")
        if not pid:
            continue
        by_plate.setdefault(pid, []).append(c)
    for pid, group in by_plate.items():
        # 候选挂 num（state 串归一成韭研 num 格式）供 _jiuyan_board_count 单源解析——
        # 韭研解析器只认「N天M板」，KPL 的「M连板/首板」形态不归一会塌成 0 键乱序
        for c in group:
            c["num"] = _num_jiuyan_format(c.get("num_state"))
        ordered = rank_board_stocks_seal(group)
        # 龙一锚：主轨首位优先，纯双创板块取 growth 轨首位（_collapse_segment_rows 同构）
        seg_first: dict[str, dict[str, Any]] = {}
        for s in ordered:
            seg = segment_of(s["code"])
            if seg and seg not in seg_first:
                seg_first[seg] = s
        anchor = seg_first.get("main") or seg_first.get("growth")
        gain_unavailable = all(s.get("gain10") is None for s in group)
        if gain_unavailable:
            meta["gain_unavailable_plates"].append(pid)
        rest = [s for s in ordered if s is not anchor]
        rest.sort(key=lambda s: (-(_jiuyan_board_count(s) or 0),
                                 str(s.get("time") or "99:99")))
        ladder = ([anchor] if anchor else []) + rest
        items = []
        for i, s in enumerate(ladder):
            items.append({
                "rank": i + 1,
                "label": lead_label(i + 1),
                "code": s["code"],
                "name": s.get("name"),
                "time": s.get("time"),
                "boards": state_boards(s.get("num_state")),
                "streak": s.get("streak"),
                "height": s.get("height"),
                "gain10": s.get("gain10"),
                "sealed_today": bool(s.get("sealed_today")),
                "leader_basis": ("space_" + segment_of(s["code"])) if s is anchor else None,
                "plate_id": pid,
            })
        boards[pid] = {"items": items, "n": len(items), "gain_unavailable": gain_unavailable}
    return boards, meta


def archive_lead_snapshot(db: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """把一份身位计算结果合并进 kpl_daban_pool 日档 lead_ 前缀字段（字段级 $set）。

    纯函数（db 注入）；payload 无 date / 无 boards → 结构化不写（不伪装成功）。
    """
    date = str(payload.get("date") or "")
    boards = payload.get("boards")
    if not date or boards is None:
        return {"ok": False, "reason": "empty_lead_payload", "date": date or None}
    now = payload.get("now") or datetime.now(TZ_SHANGHAI)
    doc = {
        "lead_date": date,
        "lead_ts": now.isoformat(),
        "lead_source": LEAD_SOURCE,
        "lead_boards": boards,
        "lead_candidates_n": payload.get("candidates_n") or 0,
        "lead_pool_dates": payload.get("pool_dates") or [],
        "lead_missing_pool_dates": payload.get("missing_pool_dates") or [],
        "lead_limit_down_excluded": payload.get("limit_down_excluded") or {},
        "lead_missing_plate": payload.get("missing_plate") or [],
        "lead_gain_unavailable_plates": payload.get("gain_unavailable_plates") or [],
        "lead_gain_missing_n": payload.get("gain_missing_n") or 0,
        "lead_archived_at": now.isoformat(),
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)
    return {"ok": True, "date": date, "boards_n": len(boards),
            "candidates_n": payload.get("candidates_n") or 0}


def compute_and_archive_lead(
    db: Any,
    date: str,
    *,
    gains_fetcher: Callable[[list[str], str], dict[str, float | None]] | None = None,
    day_change_fetcher: Callable[[list[str], str], dict[str, float | None]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """编排入口（DabanPoolArchiver 每轮在 pool 通道归档后调用）：组装 → 排序 → 落库。"""
    cands, meta = assemble_candidates(
        db, date, gains_fetcher=gains_fetcher, day_change_fetcher=day_change_fetcher)
    if cands is None:
        return {"ok": False, "reason": "no_pool_today", "date": date}
    boards, bmeta = compute_board_leads(cands)
    payload = {"date": date, "boards": boards, "candidates_n": len(cands),
               "now": now, **{k: meta.get(k) for k in
                              ("pool_dates", "missing_pool_dates", "missing_plate",
                               "limit_down_excluded", "gain_missing_n")},
               "gain_unavailable_plates": bmeta.get("gain_unavailable_plates") or []}
    return archive_lead_snapshot(db, payload)


def load_lead_corpus(db: Any, date: str) -> dict[str, Any]:
    """身位日档读口：无档 → 结构化降级（no_lead_corpus，不回退别日冒充）。"""
    row = db[_COLLECTION].find_one(
        {"_id": date},
        {"lead_date": 1, "lead_ts": 1, "lead_source": 1, "lead_boards": 1,
         "lead_candidates_n": 1, "lead_pool_dates": 1, "lead_missing_pool_dates": 1,
         "lead_limit_down_excluded": 1, "lead_missing_plate": 1,
         "lead_gain_unavailable_plates": 1, "lead_gain_missing_n": 1,
         "lead_archived_at": 1}) or {}
    if not row.get("lead_boards"):
        return {"ok": False, "degraded": True, "reason": "no_lead_corpus",
                "date": date, "lane": "lead"}
    row.pop("_id", None)
    return {"ok": True, "source": "local_archive", "lane": "lead", **row}
