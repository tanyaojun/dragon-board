# -*- coding: utf-8 -*-
"""竞价三字段（净额/成交额/换手）单一投影层（2026-11-19 用户裁决彻底版）。

计划单一依据：docs/hotlist-jev/auction-bidding-zero-trio-fix-plan-20261119.md。

根因（三层叠加，非解析丢字段）：
1. 服务端公布时点：净额/换手全市场、成交额沪市（60/68）只于 09:25 撮合后公布；
   深市成交额窗内有虚拟值。socket 2103 pid8 与 HTTP MBL col6/7/8 双通道逐值同源。
2. 成员制：撮合前掉池股（榜单截断排序）两通道都收不到撮合后公布 → 永久 0。
3. 消费层把未公布当事实 0（页面 kfmtAmt(0)='0'、聚合 sumN 计 0、语料 is not None 门）。

本模块 = 三字段语义唯一权威（AGENTS §1.2-1 单一事实源）：纯库读、零外呼、零写入。
raw 四存档（bid_items / kpl_morning_bidding_raw / kpl_bidding_series / kpl_mbl_series）
零改写——回退 = git revert 投影接入即恢复旧展示（原料无损，§4.0 fail-visible）。

语义裁决（2026-11-19，实证锚见计划 §1/§2）：
- 成交额：撮合后公布值（留池）→ 否则窗内末帧 col10（掉池股 = 掉池前虚拟观测，
  src/时点披露；600410=124381050@09:23:23）。col10 撮合收敛 = col8（603030/002685 实证）。
- 换手：公布值 → 否则派生 = 额 ÷ 流通市值 × 100（round 4 位，不预 rounding 到公布
  两位精度；锚 002685→5.8622≡公布 5.86、603030→1.0668≡1.07、600410→0.6132）。
- 净额：公布值（**留池真 0 保留**，状态门而非值门）→ 否则 None + state 缺位
  （掉池股 col14/15 窗内全 0 无源，不伪造）。窗内 09:15–09:25 净额对全市场未公布
  → 实时态也显缺位。

公布时点与陈旧页（实施轮实证精化，计划 §3.1 边界 refine；证据见实施偏差记录）：
- 公布分阶段：额/换手先（今日 09:25:13 首根沪市额非零帧），净额逐股随后
  （09:25:13–09:26:20 全部到齐；300857 净额 09:25:50 才到）。**ts≥09:25 本身
  不构成公布证据**。
- socket pid8 流含**陈旧页**（同一推送周期内多页新鲜度不一；300857 终帧回放
  09:19:05 虚拟值 8086800/net0，公布值 101707289/27741379 被覆盖）→ bid_items
  终态与 series 末帧都可能是陈旧值。公布值选取 = mbl 完整公布帧（HTTP 全量新鲜）
  优先 → MBL 冻结 → 留池持久证据（bid last_seen 严格晚于公布锚）+ series 公布后
  帧对拍（首个净额非零帧 / 首个脱离窗内虚拟态帧优先，陈旧回放页剔除）。
- 恰在公布帧掉池的股票该帧仍携带早退值（002729 实证：09:25:13 末帧与 09:24:36
  逐值相同）→ 按掉池缺位处理（exit_at_pub_frame 留痕），正值证据除外。
- 真 0 判定 = 公布完成后观测一致为 0（39 只 bid-only 留池股 577 帧净额恒 0 +
  600671/600615 一字无对手盘全日 (0,0,0)），非终帧单帧 0。

状态机（trio_state）六态 + 附加 reason：
  in_pool_matched / in_pool_pre_match / dropped_pre_match / dropped_post_match /
  not_in_auction_pool / no_mbl_series_day（≤11-16 历史日回退 + 状态门）；
  reason：no_float_cap / read_failed:<coll>:<exc> / exit_at_pub_frame /
  amount_mismatch_bid_frozen / bid_frozen_stale_diff / net_pub_pending /
  pub_values_equal_virtual / no_pub_beacon / sup_live_only（腾讯补源仅 live
  内存缓存未落库，离线重建不可恢复）。

消费方：/daban-list、/daban-list-history、/daban-bidding 读口合并（apply_trio）；
auction_trial_derive jj_amount/jj_turnover；auction_leader_label 龙头/板块语料；
rebuild_auction_bid_lines 今日语料外科重建（零 jev 零外呼，单写者 = 本入口）。
写侧 collector/archiver/protocol 零改动。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

COLLECTION_MBL_SERIES = "kpl_mbl_series"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"
COLLECTION_POOL = "kpl_daban_pool"
COLLECTION_SERIES = "kpl_bidding_series"
COLLECTION_LABELS = "hotlist_jev_auction_leader_labels"

_TZ_CST = timezone(timedelta(hours=8))
_MATCH_HMSS = "09:25:00"   # 撮合时点（公布证据另需公布锚精化，见模块头）

# MBL 17 列位（auction_bidding_direct._COLUMN_NAMES 同源；未破译列保原名）
_C_NET, _C_TUR, _C_AMT, _C_COL10, _C_CAP = 6, 7, 8, 10, 12


def _f(v: Any) -> float | None:
    """数值消毒（NaN/Inf → None，不伪装 0；与 auction_trial_derive._f 同口径）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _hmss(ts: Any) -> str | None:
    """epoch 秒 → CST HH:MM:SS（不可判 → None）。"""
    try:
        return datetime.fromtimestamp(float(ts), _TZ_CST).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso_epoch(iso: Any) -> float | None:
    """ISO 时点串（mbl 帧 ts / frozen fetchedAt）→ epoch 秒；不可判 → None。"""
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def _col(raw: Any, i: int) -> float | None:
    if not isinstance(raw, (list, tuple)) or len(raw) <= i:
        return None
    return _f(raw[i])


def _is_sh(code: str) -> bool:
    return code.startswith(("60", "68"))


def _derive_turnover(amount: float | None, cap: float | None) -> float | None:
    """派生换手% = 额 ÷ 流通市值 × 100（round 4 位原值，不预 rounding 到公布精度）。"""
    if amount is None or cap is None or cap <= 0 or amount <= 0:
        return None
    return round(amount / cap * 100, 4)


def _trio(amt: Any, tur: Any, net: Any) -> tuple:
    return (_f(amt), _f(tur), _f(net))


def _load_sources(db: Any, date: str) -> dict:
    """四源纯库读（单集合读异常 → 该源降级 + reason 留痕，不阻断其余源，§4.0）。"""
    reasons: list[str] = []
    out: dict[str, Any] = {"mbl_frames": [], "mbl_frozen": {}, "frozen_at": None,
                           "bid_items": {}, "bid_final_ts": None,
                           "series_last": {}, "series_final_ts": None,
                           "series_pre_last": {}, "series_post_obs": {},
                           "ts_pub_amt": None, "ts_pub_net": None,
                           "mbl_pub_frame": None, "mbl_amt_frame": None}
    # ① mbl_series 帧时序（raw 17 列；ts ISO 串；HTTP 全量新鲜帧，无陈旧页问题）
    try:
        doc = db[COLLECTION_MBL_SERIES].find_one({"_id": date}) or {}
        frames = []
        for fr in doc.get("frames") or []:
            iso = str(fr.get("ts") or "")
            ep = _iso_epoch(iso)
            rows = {}
            for raw in fr.get("rows") or []:
                if isinstance(raw, (list, tuple)) and raw:
                    c6 = str(raw[0])[-6:]
                    if c6:
                        rows[c6] = raw
            frames.append({"iso": iso, "hmss": iso[11:19], "epoch": ep, "rows": rows})
        frames.sort(key=lambda f: f["epoch"] or 0)
        out["mbl_frames"] = frames
        for fr in frames:
            if fr["hmss"] < _MATCH_HMSS:
                continue
            sh_amt = any(_is_sh(c) and (_col(r, _C_AMT) or 0) > 0
                         for c, r in fr["rows"].items())
            any_net = any((_col(r, _C_NET) or 0) != 0 for r in fr["rows"].values())
            if sh_amt and out["mbl_amt_frame"] is None:
                out["mbl_amt_frame"] = fr   # 额公布帧（净额可能未到齐）
            if sh_amt and any_net and out["mbl_pub_frame"] is None:
                out["mbl_pub_frame"] = fr   # 完整公布帧（额+净额均已公布）
                break
    except Exception as exc:  # noqa: BLE001 — 单源降级留痕不阻断
        reasons.append(f"read_failed:{COLLECTION_MBL_SERIES}:{type(exc).__name__}")
    # ② MBL 冻结（09:25–09:30 窗内真源头直采；成员 = 撮合后在榜）
    try:
        doc = db[COLLECTION_MBL_RAW].find_one({"_id": date}) or {}
        out["mbl_frozen"] = {str(c)[-6:]: r for c, r in (doc.get("rows") or {}).items()
                           if isinstance(r, dict)}
        out["frozen_at"] = _iso_epoch(doc.get("fetchedAt")) or _f(doc.get("time"))
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"read_failed:{COLLECTION_MBL_RAW}:{type(exc).__name__}")
    # ③ bid_items 终态 + last_seen_ts（socket pid8 成员时序；**终值可能是陈旧页**，
    #    公布值选取须与 series 公布后帧对拍，见模块头）
    try:
        doc = db[COLLECTION_POOL].find_one({"_id": date}, {"bid_items": 1, "bid_ts": 1}) or {}
        out["bid_items"] = {str(i.get("stock_id"))[-6:]: i
                            for i in doc.get("bid_items") or []
                            if isinstance(i, dict) and i.get("stock_id")}
        out["bid_final_ts"] = _f(doc.get("bid_ts"))
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"read_failed:{COLLECTION_POOL}:{type(exc).__name__}")
    # ④ bidding_series 成员时序 + 公布后观测序列（陈旧页剔除原料；
    #    2026-11-19 逐 tick 文档化后走 load_bidding_series 唯一读口）
    try:
        from backend.services.kpl_daban_archiver import load_bidding_series
        doc = load_bidding_series(db, date) or {}
        last: dict[str, tuple] = {}
        pre_last: dict[str, tuple] = {}
        post_obs: dict[str, list] = {}
        final_ts = None
        pub_amt = pub_net = None
        for t in doc.get("ticks") or []:
            ts = _f(t.get("ts"))
            if ts is None:
                continue
            final_ts = ts if final_ts is None or ts > final_ts else final_ts
            hm = _hmss(ts)
            post = hm is not None and hm >= _MATCH_HMSS
            for it in t.get("it") or []:
                c6 = str(it.get("s") or "")[-6:]
                if not c6:
                    continue
                trio = _trio(it.get("bidding_amount"), it.get("bidding_turnover"),
                             it.get("bidding_net"))
                cur = last.get(c6)
                if cur is None or ts >= cur[0]:
                    last[c6] = (ts, it)
                if post:
                    post_obs.setdefault(c6, []).append((ts, trio))
                    if pub_amt is None and _is_sh(c6) and (trio[0] or 0) > 0:
                        pub_amt = ts
                    if pub_net is None and (trio[2] or 0) != 0:
                        pub_net = ts
                else:
                    pre_last[c6] = trio
        out["series_last"] = last
        out["series_pre_last"] = pre_last
        out["series_post_obs"] = post_obs
        out["series_final_ts"] = final_ts
        out["ts_pub_amt"] = pub_amt
        out["ts_pub_net"] = pub_net
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"read_failed:{COLLECTION_SERIES}:{type(exc).__name__}")
    out["reasons"] = reasons
    return out


def _fact_skeleton() -> dict:
    return {"bidding_amount": None, "bidding_amount_src": None,
            "bidding_turnover": None, "bidding_turnover_src": None,
            "bidding_net": None, "bidding_net_state": "missing",
            "trio_state": "not_in_auction_pool", "amount_ts": None,
            "float_cap": None, "reasons": []}


def _published_fact(src: str, vals: tuple, amount_ts: str | None, cap: float | None,
                    *, in_pool: bool, reasons: list[str]) -> dict:
    fact = _fact_skeleton()
    amt, tur, net = vals
    fact.update({"bidding_amount": amt, "bidding_amount_src": src,
                 "bidding_turnover": tur, "bidding_turnover_src": src,
                 "bidding_net": net,
                 "bidding_net_state": "published" if net is not None else "missing",
                 "trio_state": "in_pool_matched" if in_pool else "dropped_post_match",
                 "amount_ts": amount_ts, "float_cap": cap, "reasons": list(reasons)})
    return fact


def _virtual_fact(state: str, amount: float | None, amount_src: str | None,
                  amount_ts: str | None, cap: float | None,
                  reasons: list[str]) -> dict:
    """未公布态（窗内虚拟 / 掉池前观测）：额=虚拟观测、换手=派生、净额=None 缺位。"""
    fact = _fact_skeleton()
    tur = _derive_turnover(amount, cap)
    rs = list(reasons)
    if amount is not None and cap is None:
        rs.append("no_float_cap")
    fact.update({"bidding_amount": amount, "bidding_amount_src": amount_src,
                 "bidding_turnover": tur,
                 "bidding_turnover_src": "derived_cap" if tur is not None else None,
                 "bidding_net": None, "bidding_net_state": "missing",
                 "trio_state": state, "amount_ts": amount_ts,
                 "float_cap": cap, "reasons": rs})
    return fact


def _pick_post_obs(obs: list[tuple], completion: float | None,
                   pre_virtual: tuple | None) -> tuple | None:
    """公布后观测选取（陈旧页剔除）：① 首个净额非零帧（净额公布确证）→
    ② 首个脱离窗内虚拟态帧（额/换手已变 = 公布态，真 0 净额股由此识别）→
    ③ 首帧（一字无对手盘等全日恒 0 形态）。completion 前观测不参与。"""
    pool = [(ts, tr) for ts, tr in obs if completion is None or ts >= completion]
    if not pool:
        pool = obs
    for ts, tr in pool:
        if (tr[2] or 0) != 0:
            return ts, tr
    if pre_virtual is not None:
        for ts, tr in pool:
            if (tr[0], tr[1]) != (pre_virtual[0], pre_virtual[1]):
                return ts, tr
    return pool[0] if pool else None


def resolve_bidding_trio(db: Any, date: str, codes: Any = None) -> dict:
    """纯库读投影：{"facts": {code6: TrioFact}, "census": {...}, "state": {...}}。

    零外呼、零写入；按请求计算，不加跨请求缓存（避免双事实源）。
    codes 给出时并入宇宙（榜外入选股 → not_in_auction_pool，live 腾讯补源经
    apply_trio 优先保留实测值）。
    """
    src = _load_sources(db, date)
    reasons: list[str] = list(src["reasons"])
    frames = src["mbl_frames"]
    frozen = src["mbl_frozen"]
    frozen_at = src["frozen_at"]
    bid_items = src["bid_items"]
    series_last = src["series_last"]
    post_obs = src["series_post_obs"]
    pre_last = src["series_pre_last"]
    no_series_day = not frames and not series_last
    if not frames:
        reasons.append("no_mbl_series_day")   # 披露：mbl 帧档缺席（series 在则主路径仍可剔陈旧）
    pub_frame = src["mbl_pub_frame"]
    amt_frame = src["mbl_amt_frame"]
    # 公布锚：额锚（首根沪市额非零）+ 净额锚（首根任意净额非零），双通道取早
    beacons_amt = [b for b in (src["ts_pub_amt"],
                               amt_frame["epoch"] if amt_frame else None)
                   if b is not None]
    ts_pub_amt = min(beacons_amt) if beacons_amt else None
    beacons_net = [b for b in (src["ts_pub_net"],
                               pub_frame["epoch"] if pub_frame else None)
                   if b is not None]
    ts_pub_net = min(beacons_net) if beacons_net else None
    ts_pub = min([b for b in (ts_pub_amt, ts_pub_net) if b is not None], default=None)
    # 公布完成锚：完整公布帧时点（HTTP 全量新鲜）；缺则净额锚（live 早期降级）
    completion = pub_frame["epoch"] if pub_frame else ts_pub_net
    if not no_series_day and ts_pub is None:
        reasons.append("no_pub_beacon")
    # 逐股 mbl 帧索引（窗内末帧 / 末次在场帧）
    pre_last_fr: dict[str, dict] = {}
    any_last: dict[str, dict] = {}
    for fr in frames:
        for c6, raw in fr["rows"].items():
            rec = {"epoch": fr["epoch"], "hmss": fr["hmss"], "raw": raw}
            any_last[c6] = rec
            if fr["hmss"] < _MATCH_HMSS:
                pre_last_fr[c6] = rec
    universe = set(bid_items) | set(any_last) | set(series_last) | set(frozen)
    if codes:
        universe |= {str(c)[-6:] for c in codes if c}
    facts: dict[str, dict] = {}
    for code in sorted(universe):
        bi = bid_items.get(code) or {}
        bid_ls = _f(bi.get("last_seen_ts"))
        fr_pre = pre_last_fr.get(code)
        fr_any = any_last.get(code)
        ser = series_last.get(code)
        ser_ts = ser[0] if ser else None
        fz = frozen.get(code)
        obs = post_obs.get(code) or []
        cap_mbl = (_col(pub_frame["rows"][code], _C_CAP)
                   if pub_frame and code in pub_frame["rows"] else None) \
            or (_col(fr_pre["raw"], _C_CAP) if fr_pre else None) \
            or (_f(fz.get("circulated_value")) if fz else None)
        cap = cap_mbl if cap_mbl is not None else _f(bi.get("real_float"))
        if no_series_day:
            facts[code] = _resolve_fallback_day(bi, bid_ls, fz, frozen_at, cap, ser_ts)
            continue
        in_pool = (bid_ls is not None and _hmss(bid_ls) is not None
                   and _hmss(bid_ls) >= _MATCH_HMSS)
        # ── ① mbl 完整公布帧成员（HTTP 全量新鲜，权威；陈旧页免疫）──
        if pub_frame is not None and code in pub_frame["rows"]:
            raw = pub_frame["rows"][code]
            vals = (_col(raw, _C_AMT), _col(raw, _C_TUR), _col(raw, _C_NET))
            rs = []
            b_amt = _f(bi.get("bidding_amount"))
            if vals[0] is not None and b_amt is not None and bid_ls is not None \
                    and ts_pub_amt is not None and bid_ls > ts_pub_amt \
                    and b_amt != vals[0]:
                rs.append("amount_mismatch_bid_frozen")   # fail-visible 披露取 mbl
            facts[code] = _published_fact("mbl_postmatch", vals, pub_frame["hmss"],
                                          cap, in_pool=in_pool or bid_ls is None,
                                          reasons=rs)
            continue
        # ── ② MBL 冻结成员（采集合同保证 09:25–09:30 窗内直采；fetchedAt 在场时
        #    须晚于额锚，缺时戳按合同信任成员证据；仅板块 join 行（三字段全缺）
        #    不构成值源，落后续分支）──
        fz_vals = _trio(fz.get("bidding_amount"), fz.get("bidding_turnover"),
                        fz.get("bidding_net")) if fz is not None else (None, None, None)
        if fz is not None and any(v is not None for v in fz_vals) \
                and (frozen_at is None or ts_pub_amt is None
                     or frozen_at > ts_pub_amt):
            facts[code] = _published_fact("mbl_frozen", fz_vals, _hmss(frozen_at),
                                          cap, in_pool=True, reasons=[])
            continue
        # ── ③ 留池持久证据（bid last_seen 严格晚于额锚）+ series 公布后帧对拍 ──
        if bid_ls is not None and ts_pub_amt is not None and bid_ls > ts_pub_amt:
            cand = _trio(bi.get("bidding_amount"), bi.get("bidding_turnover"),
                         bi.get("bidding_net"))
            pick = _pick_post_obs(obs, completion, pre_last.get(code))
            rs = []
            if pick is not None and pick[1] != cand:
                # 终态陈旧页（300857 案）→ 取公布后选取帧
                facts[code] = _published_fact("series_postmatch", pick[1],
                                              _hmss(pick[0]), cap, in_pool=True,
                                              reasons=["bid_frozen_stale_diff"])
                continue
            if pick is not None and pre_last.get(code) is not None \
                    and pick[1] == pre_last[code] and (pick[1][2] or 0) == 0 \
                    and (pick[1][0] or 0) > 0 \
                    and not any((tr[2] or 0) != 0 for _, tr in obs):
                # 公布后观测恒等于窗内虚拟态且全日净额无非零观测：深市虚拟额
                # 撮合前收敛=公布额（002123 案 512502），真 0 与陈旧回放不可值门
                # 区分——留池持久+公布完成锚 = 公布态（状态门裁决），仅披露留痕
                rs.append("pub_values_equal_virtual")
            facts[code] = _published_fact("bid_frozen", cand, _hmss(bid_ls), cap,
                                          in_pool=True, reasons=rs)
            continue
        # ── ④ 额公布帧成员但净额未到齐（live 09:25:13–09:26:20 过渡态）──
        if amt_frame is not None and code in amt_frame["rows"]:
            raw = amt_frame["rows"][code]
            amt, tur = _col(raw, _C_AMT), _col(raw, _C_TUR)
            net = _col(raw, _C_NET)
            rs = []
            if net is None or net == 0:
                nz = next(((ts, tr) for ts, tr in obs if (tr[2] or 0) != 0), None)
                if nz is not None:
                    net = nz[1][2]
                else:
                    net = None
                    rs.append("net_pub_pending")
            facts[code] = _published_fact("mbl_postmatch", (amt, tur, net),
                                          amt_frame["hmss"], cap, in_pool=True,
                                          reasons=rs)
            continue
        # ── ⑤ 掉池于公布帧但已收到公布（正值证据抢救，dropped_post_match）──
        pos = next(((ts, tr) for ts, tr in obs
                    if (tr[2] or 0) != 0 or (tr[1] or 0) != 0
                    or (_is_sh(code) and (tr[0] or 0) > 0)), None)
        if pos is not None:
            vals = pos[1]
            rs = []
            if (vals[2] or 0) == 0:
                nz = next(((ts, tr) for ts, tr in obs if (tr[2] or 0) != 0), None)
                if nz is not None:
                    vals = (vals[0], vals[1], nz[1][2])
                else:
                    vals = (vals[0], vals[1], None)
                    rs.append("net_pub_pending")
            facts[code] = _published_fact("series_postmatch", vals, _hmss(pos[0]),
                                          cap, in_pool=in_pool, reasons=rs)
            continue
        # ── ⑥ 未公布：窗内虚拟（实时态）/ 掉池前观测 / 榜外 ──
        has_presence = fr_any is not None or bi or ser is not None
        if not has_presence:
            facts[code] = _fact_skeleton()   # not_in_auction_pool（三 None）
            continue
        if ts_pub is None:
            in_pool_now = (fr_any is not None and frames
                           and fr_any["epoch"] == frames[-1]["epoch"]) \
                or (bid_ls is not None and src["bid_final_ts"] is not None
                    and bid_ls >= src["bid_final_ts"]) \
                or (ser_ts is not None and src["series_final_ts"] is not None
                    and ser_ts >= src["series_final_ts"])
            state = "in_pool_pre_match" if in_pool_now else "dropped_pre_match"
        else:
            state = "dropped_pre_match"
        rs = []
        last_ep = max([e for e in (fr_any["epoch"] if fr_any else None,
                                   bid_ls, ser_ts) if e is not None], default=None)
        if ts_pub is not None and last_ep == ts_pub:
            rs.append("exit_at_pub_frame")   # 恰在公布帧掉池（002729 实证边界）
        amt, amt_src, amt_ts = _virtual_amount(code, fr_pre, bi, bid_ls, ser, state)
        # col10==0 / 早退无虚拟撮合 → 额 None（保守缺位，计划 §10 残留重裁前不烘 0）
        facts[code] = _virtual_fact(state, amt, amt_src, amt_ts, cap, rs)
    census = _census(facts)
    state = {"state": "ok" if facts else "absent",
             "source": "auction_bidding_facts",
             "tsPub": _hmss(ts_pub), "tsPubAmt": _hmss(ts_pub_amt),
             "tsPubNet": _hmss(ts_pub_net), "noMblSeriesDay": not frames,
             "mblFrameN": len(frames), "frozenN": len(frozen),
             "bidItemN": len(bid_items), "seriesCodeN": len(series_last)}
    if reasons:
        state["reasons"] = reasons
    return {"facts": facts, "census": census, "state": state}


def _virtual_amount(code: str, fr_pre: dict | None, bi: dict, bid_ls: float | None,
                    ser: tuple | None, state: str) -> tuple:
    """未公布态成交额 = 掉池前/窗内虚拟观测（col10 优先 → bid 虚拟 → series 虚拟）。

    深市窗内虚拟额（socket 终态）与 mbl col10 同语义（帧间采样差披露，11-17 判约）；
    mbl 帧缺席时 bid/series 虚拟观测保全（§4.0 可计算部分不丢）。0/缺 → None。
    """
    pre = state == "in_pool_pre_match"
    if fr_pre is not None:
        v = _col(fr_pre["raw"], _C_COL10)
        if v is not None and v > 0:
            return v, ("mbl_col10_virtual" if pre else "mbl_col10_preexit"), fr_pre["hmss"]
    if bi:
        v = _f(bi.get("bidding_amount"))
        if v is not None and v > 0:
            return v, ("bid_virtual" if pre else "bid_preexit_virtual"), _hmss(bid_ls)
    if ser is not None:
        v = _f(ser[1].get("bidding_amount"))
        if v is not None and v > 0:
            return v, ("series_virtual" if pre else "series_preexit_virtual"), _hmss(ser[0])
    return None, None, None


def _resolve_fallback_day(bi: dict, bid_ls: float | None, fz: dict | None,
                          frozen_at: float | None, cap: float | None,
                          ser_ts: float | None) -> dict:
    """≤11-16 历史日（无 mbl_series 档）回退 + 状态门（计划 §3.1/§5）。

    公布/留池证据 = bid last_seen≥09:25 或 MBL 冻结成员（fetchedAt 窗内）。
    值门：净额/换手非 0 = 公布事实保留；==0 且留池证据 → 真 0 保留；
    ==0 且掉池证据 → None 缺位。额 >0 保留（深市虚拟/公布同语义观测），
    ==0 留池 → 真 0，==0 掉池 → None。换手缺公布 → 派生兜底。
    历史日无帧时序可剔陈旧页 → 降级口径披露（no_mbl_series_day）。
    """
    in_pool = (bid_ls is not None and _hmss(bid_ls) is not None
               and _hmss(bid_ls) >= _MATCH_HMSS) or fz is not None
    has_presence = bool(bi) or fz is not None or ser_ts is not None
    fact = _fact_skeleton()
    if not has_presence:
        return fact   # not_in_auction_pool
    fact["trio_state"] = "no_mbl_series_day"
    fact["float_cap"] = cap

    def _pick(pub_key: str):
        if fz is not None and _f(fz.get(pub_key)) is not None:
            return _f(fz.get(pub_key)), "mbl_frozen", _hmss(frozen_at)
        if bi and _f(bi.get(pub_key)) is not None:
            return _f(bi.get(pub_key)), "bid_frozen", _hmss(bid_ls)
        return None, None, None

    amt, a_src, a_ts = _pick("bidding_amount")
    tur, t_src, _ = _pick("bidding_turnover")
    net, n_src, _ = _pick("bidding_net")
    if amt is not None and amt == 0 and not in_pool:
        amt, a_src, a_ts = None, None, None
    if net is not None and net == 0 and not in_pool:
        net, n_src = None, None
    if tur is not None and tur == 0 and not in_pool:
        tur, t_src = None, None
    if tur is None and amt is not None:
        d = _derive_turnover(amt, cap)
        if d is not None:
            tur, t_src = d, "derived_cap"
        elif cap is None:
            fact["reasons"].append("no_float_cap")
    fact.update({"bidding_amount": amt, "bidding_amount_src": a_src,
                 "bidding_turnover": tur, "bidding_turnover_src": t_src,
                 "bidding_net": net,
                 "bidding_net_state": "published" if net is not None else "missing",
                 "amount_ts": a_ts})
    return fact


def _census(facts: dict[str, dict]) -> dict:
    c = {"total_n": len(facts), "matched_n": 0, "virtual_n": 0, "preexit_n": 0,
         "not_in_pool_n": 0, "no_series_day_n": 0, "net_missing_n": 0,
         "derived_tur_n": 0, "no_cap_n": 0, "true_zero_net_n": 0}
    for f in facts.values():
        st = f["trio_state"]
        if st in ("in_pool_matched", "dropped_post_match"):
            c["matched_n"] += 1
        elif st == "in_pool_pre_match":
            c["virtual_n"] += 1
        elif st == "dropped_pre_match":
            c["preexit_n"] += 1
        elif st == "not_in_auction_pool":
            c["not_in_pool_n"] += 1
        elif st == "no_mbl_series_day":
            c["no_series_day_n"] += 1
        if f["bidding_net"] is None:
            c["net_missing_n"] += 1
        elif f["bidding_net"] == 0:
            c["true_zero_net_n"] += 1
        if f["bidding_turnover_src"] == "derived_cap":
            c["derived_tur_n"] += 1
        if "no_float_cap" in f["reasons"]:
            c["no_cap_n"] += 1
    return c


def apply_trio(items: Any, facts: dict[str, dict]) -> Any:
    """消费方合并助手：三字段覆写为投影值 + 附 src/state 结构化字段（原地合并）。

    items = {code: item} 或 [item（stock_id/code）]。非三字段（quotas/price/pct/
    zt_buy_amount/…）一律不碰（raw 观测保全）。腾讯补源（source=tencent_auction）
    实测值优先于投影派生（计划 §4.3）：保留其 net/turnover/amount，src 留痕
    tencent_auction；缺位字段仍缺位（sup_live_only：离线重建不可恢复）。
    无投影 fact 的 code 不碰（fail-visible：不伪装已投影）。
    """
    if isinstance(items, dict):
        pairs = items.items()
    elif isinstance(items, list):
        pairs = [(str((it or {}).get("stock_id") or (it or {}).get("code") or "")[-6:], it)
                 for it in items if isinstance(it, dict)]
    else:
        return items
    for code, it in pairs:
        if not isinstance(it, dict):
            continue
        fact = facts.get(str(code)[-6:])
        if fact is None:
            continue
        if it.get("source") == "tencent_auction":
            for fld, src_key in (("bidding_amount", "bidding_amount_src"),
                                 ("bidding_turnover", "bidding_turnover_src")):
                if _f(it.get(fld)) is not None:
                    it[src_key] = "tencent_auction"
            net = _f(it.get("bidding_net"))
            it["bidding_net"] = net
            it["bidding_net_state"] = "published" if net is not None else "missing"
            it["trio_state"] = fact["trio_state"]
            rs = list(fact["reasons"])
            if "sup_live_only" not in rs:
                rs.append("sup_live_only")
            it["trio_reasons"] = rs
            continue
        it["bidding_amount"] = fact["bidding_amount"]
        it["bidding_amount_src"] = fact["bidding_amount_src"]
        it["bidding_turnover"] = fact["bidding_turnover"]
        it["bidding_turnover_src"] = fact["bidding_turnover_src"]
        it["bidding_net"] = fact["bidding_net"]
        it["bidding_net_state"] = fact["bidding_net_state"]
        it["trio_state"] = fact["trio_state"]
        it["amount_ts"] = fact["amount_ts"]
        it["float_cap"] = fact["float_cap"]
        if fact["reasons"]:
            it["trio_reasons"] = list(fact["reasons"])
        else:
            it.pop("trio_reasons", None)
    return items


# ══════ 语料外科重建（计划 §4.8；零 jev 零外呼；单写者 = 本入口，文档化）══════

_BID_LINE_PREFIX = "竞价（09:25 匹配价）："


def _locate_bid_line(doc: dict) -> tuple[str | None, bool]:
    """定位旧六件套行：路径 A = doc.bidLine 精确串（须在 narrative 整行在场）；
    路径 B = 行首前缀 fallback（今日存量档无 bidLine 字段）。返回 (old_line, fallback)。"""
    narrative = doc.get("narrative") or ""
    lines = narrative.split("\n")
    old = doc.get("bidLine")
    if isinstance(old, str) and old and old in lines:
        return old, False
    hit = next((ln for ln in lines if ln.startswith(_BID_LINE_PREFIX)), None)
    return hit, True


def _carry_ratio(old_line: str | None, label: str, old_amt: float | None) -> float | None:
    """竞昨比段原串保留（basis 离线不可恢复，零外呼）：从旧行该股段提取数值。

    伪 0 剔除（§4.0）：旧 ratio==0 且旧额缺/0 → 该 ratio 由缺位额派生 = 伪事实，
    不保留（缺位字段整段缺席）；旧额>0 或 ratio>0 → 原值保留。
    """
    if not old_line:
        return None
    import re
    seg_pat = re.compile(re.escape(label) + r"\s([^；]*?)(?=；|$)")
    m = seg_pat.search(old_line[len(_BID_LINE_PREFIX):])
    if not m:
        return None
    rm = re.search(r"竞昨比\s*(-?[\d.]+)%", m.group(1))
    if not rm:
        return None
    ratio = _f(rm.group(1))
    if ratio is None:
        return None
    if ratio == 0 and not (old_amt is not None and old_amt > 0):
        return None   # 缺位额派生的伪 0 → 缺席
    return ratio


def _bid_line_state(census: dict, facts: dict[str, dict], codes: list[str],
                    trio_state: dict | None = None) -> dict:
    return {"census": census,
            "trioState": trio_state,
            "codes": {c: {"trio_state": facts[c]["trio_state"],
                          "amount_src": facts[c]["bidding_amount_src"],
                          "turnover_src": facts[c]["bidding_turnover_src"],
                          "net_state": facts[c]["bidding_net_state"]}
                      for c in codes if c in facts}}


def rebuild_auction_bid_lines(db: Any, date: str, *,
                              authorize_frozen_bypass: bool = False,
                              rebuild_reason: str = "") -> dict:
    """今日语料外科重建入口（计划 §4.8）：只换六件套行，保其余行不漂移。

    - 目标集合 hotlist_jev_auction_leader_labels（leader + sector 两 docKind）。
    - 路径 A（新档有 bidLine）：整行精确替换；new=None → 删行。
    - 路径 B（存量档无 bidLine）：行首前缀 fallback 定位，报告逐 doc old/new。
    - 冻结守卫：corpusFrozen=True 默认拒绝（skipped_frozen_n）；显式
      authorize_frozen_bypass=True 才绕过（用户授权留痕 rebuildReason/rebuiltAt）。
    - 零 jev（§1.2-7）、零外呼：basis/腾讯补源离线不可恢复 → 竞昨比段原串保留
      （伪 0 剔除），sup_live_only 留痕；**禁止整篇 narrative 重生成**。
    - 单写者 = 本入口：update_one 字段级 $set（narrative/bidLine/bidLineState/
      rebuiltAt/rebuildReason），不碰 answers/outcome*/gate（防 look-ahead 漂移）。
    返回重建报告 {docs_n, replaced_n, removed_n, no_change_n, fallback_n,
    skipped_frozen_n, per_doc diff}。
    """
    from backend.analysis.hotlist.auction_leader_ammo import auction_bid_line
    from backend.services.kpl_daban_archiver import load_day

    trio = resolve_bidding_trio(db, date)
    facts, census = trio["facts"], trio["census"]
    payload = load_day(db, date, lane="bid")
    raw_bid: dict[str, dict] = {}
    if payload.get("ok"):
        for it in payload.get("items") or []:
            c6 = str((it or {}).get("stock_id") or "")[-6:]
            if c6 and c6 not in raw_bid:
                raw_bid[c6] = dict(it)
    bid = {c: dict(it) for c, it in raw_bid.items()}
    apply_trio(bid, facts)
    col = db[COLLECTION_LABELS]
    docs = list(col.find({"tradingDate": date}))
    leaders = [d for d in docs if d.get("docKind") == "leader"]
    # peers 重建宇宙：同板 + 同源桶（trial 隔离，runner by_board/by_board_trial 同口径）
    by_board: dict[tuple, list[dict]] = {}
    for d in leaders:
        bucket = "trial" if d.get("boardSource") == "jiuyan_root_trial" else "main"
        by_board.setdefault((str(d.get("board") or ""), bucket), []).append(d)
    report: dict[str, Any] = {"ok": True, "date": date, "docs_n": len(docs),
                              "replaced_n": 0, "removed_n": 0, "no_change_n": 0,
                              "fallback_n": 0, "skipped_frozen_n": 0,
                              "census": census, "trioState": trio["state"],
                              "per_doc": []}
    now = datetime.now(_TZ_CST).isoformat(timespec="seconds")
    for doc in docs:
        did = str(doc.get("_id"))
        kind = doc.get("docKind")
        if doc.get("corpusFrozen") and not authorize_frozen_bypass:
            report["skipped_frozen_n"] += 1
            report["per_doc"].append({"_id": did, "docKind": kind,
                                      "action": "skipped_frozen"})
            continue
        if kind == "sector":
            members = doc.get("segmentRows") or []
            codes = [str(m.get("code"))[-6:] for m in members if m.get("code")]
            entries = [{"label": str(m.get("name") or m.get("code")),
                        "item": _rebuild_item(bid.get(str(m.get("code"))[-6:]),
                                              raw_bid.get(str(m.get("code"))[-6:]),
                                              doc, str(m.get("name") or m.get("code")))}
                       for m in members if m.get("code")]
        else:
            code = str(doc.get("code") or "")[-6:]
            codes = [code]
            label = str(doc.get("name") or code)
            bucket = "trial" if doc.get("boardSource") == "jiuyan_root_trial" else "main"
            peers = [{"name": p.get("name"), "code": p.get("code"),
                      "pct": (bid.get(str(p.get("code"))[-6:]) or {}).get("bidding_pct"),
                      "amount": (bid.get(str(p.get("code"))[-6:]) or {}).get("bidding_amount")}
                     for p in by_board.get((str(doc.get("board") or ""), bucket), [])
                     if str(p.get("code"))[-6:] != code]
            entries = [{"label": label,
                        "item": _rebuild_item(bid.get(code), raw_bid.get(code), doc, label),
                        "peers": peers}]
        old_line, fallback = _locate_bid_line(doc)
        if fallback and old_line is not None:
            report["fallback_n"] += 1
        new_line = auction_bid_line(entries)
        entry_diff = {"_id": did, "docKind": kind, "old": old_line, "new": new_line,
                      "fallback": fallback}
        if old_line is None and new_line is None:
            report["no_change_n"] += 1
            entry_diff["action"] = "no_change"
            report["per_doc"].append(entry_diff)
            continue
        if old_line == new_line and "bidLine" in doc:
            report["no_change_n"] += 1
            entry_diff["action"] = "no_change"
            report["per_doc"].append(entry_diff)
            continue
        narrative = doc.get("narrative") or ""
        lines = narrative.split("\n")
        if old_line is not None:
            idx = lines.index(old_line)   # 整行精确（路径 A 串即整行；B 前缀定位行）
            if new_line is None:
                lines.pop(idx)
                report["removed_n"] += 1
                entry_diff["action"] = "removed"
            else:
                lines[idx] = new_line
                report["replaced_n"] += 1
                entry_diff["action"] = "replaced"
        elif new_line is not None:
            # 旧档无六件套行（当时全缺缺席）→ 投影后有信息量则补行（结构行前，
            # runner 叙事顺序固定；无锚则 evidence 块前）
            idx = next((i for i, ln in enumerate(lines)
                        if ln.startswith("昨日（") and "结构：" in ln), None)
            if idx is None:
                idx = next((i for i, ln in enumerate(lines)
                            if ln.startswith("题材证据块")), len(lines))
            lines.insert(idx, new_line)
            report["replaced_n"] += 1
            entry_diff["action"] = "inserted"
        else:
            report["no_change_n"] += 1
            entry_diff["action"] = "no_change"
            report["per_doc"].append(entry_diff)
            continue
        state = _bid_line_state(census, facts, codes, trio["state"])
        col.update_one({"_id": doc["_id"]}, {"$set": {
            "narrative": "\n".join(lines), "bidLine": new_line,
            "bidLineState": state, "rebuiltAt": now,
            "rebuildReason": rebuild_reason or "auction_bidding_zero_trio_fix_20261119"}})
        report["per_doc"].append(entry_diff)
    return report


def _rebuild_item(item: dict | None, raw_item: dict | None, doc: dict,
                  label: str) -> dict | None:
    """重建条目 = 投影合并后的 bid item + 旧行竞昨比原串保留（伪 0 剔除）。"""
    if item is None:
        return None
    out = dict(item)
    old_line, _ = _locate_bid_line(doc)
    old_amt = _f((raw_item or {}).get("bidding_amount"))
    ratio = _carry_ratio(old_line, label, old_amt)
    if ratio is not None:
        out["ratio_prev_vol"] = ratio
    return out
