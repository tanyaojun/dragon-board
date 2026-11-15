# -*- coding: utf-8 -*-
"""竞价试盘溢价 / 封板率规则档评估（转正 2026-11-15，四轮迭代方法论固化）。

来源：60 日溢价分析 → 100 日扩窗 → 4 维度（板块/个股竞价成交额、首加额、最终额）
→ 封板率规则档。本脚本固化全部口径，零 jev、零生产写库；个股日线默认本地 vipdoc，
在线兜底预算化（--offline 可关）。评估文档见 docs/hotlist-jev/
auction-trial-premium-100d-evaluation-20261115.md。

口径（单一事实源，禁第二套实现）：
- 档位/限价/姿态复用 scripts/auction_trial_base_rate_eval.py（bre）：limit_pct/tier_jj/
  tier_end/settlement_tier/posture/load_rows。
- 封板 = trial percent ≥ 限价×0.99（percent 缺位 → TDX 收盘补证）；一字板 = TDX
  open≥涨停价 且 low≥涨停价（T 字板保留）；非一字封板 = 封板 ∧ 非一字（可买口径）。
- 溢价 = T+1 开/收 vs T 收盘；缺 T+1 棒 → 溢价 None 不进分母（fail-visible，不伪装 0）。
- 板块 = jiuyan root 粗桶全链（jiuyan_board.board_index → bk_name 桥 → 近 60 日打标
  分组兜底，与线上读口 get_auction_trial 同口径单源）；板块竞价强度 = 每日每板块
  Σjj_amount（试盘子集）。
- 交易轴 = 本地指数日历（sh000001.day）∪ 在线指数尾棒；假期守卫：试盘日不在轴上 →
  剔除并披露（2026-11-15 假期冒充档事故教训，回填须取交易日历 ∩ 源 dates[]）。

规则档（描述性拟合，落地须预登记 + 样本外验证）：
- 板块强度档：冷<5000万 / 温5000万-2亿 / 中热2-5亿 / 热5-10亿 / 过热≥10亿。
  中热 = 可买封板率 + 溢价双优甜区；热/过热 = 含一字封板高但溢价差（出货）。
- 个股强度档 tier_jj：top95（≥95%限价，封板高但近半一字）/ mid50_95（50-95%，可买
  封板甜区零一字）/ low_lt50。目标函数用「非一字封板 + 溢价」联合，勿用含一字封板单目标。

用法：./.venv/Scripts/python.exe scripts/auction_trial_premium_eval.py [--from X --to Y]
      [--simulate] [--offline] [--tag T]（stdout 表格，人工誊入评估文档）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

QB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QB))

_spec = importlib.util.spec_from_file_location("bre", QB / "scripts" / "auction_trial_base_rate_eval.py")
bre = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bre)

from backend.operations.market_dieban_tdx import read_lday, resolve_root  # noqa: E402
from backend.operations import jev_label_jiuyan as jj  # noqa: E402

EPS = 0.001
ONLINE_MAX = 80

# ── 板块竞价强度规则档（日 Σjj_amount，元）──
BOARD_TIERS = [("冷 <5000万", 5e7), ("温 5000万-2亿", 2e8), ("中热 2-5亿", 5e8),
               ("热 5-10亿", 1e9), ("过热 ≥10亿", float("inf"))]


# ══════════ 纯函数（无 IO，单元测试覆盖）══════════
def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def bucket(v, edges, labels):
    """左闭右开分桶；None → 缺值（fail-visible，不伪装 0）。"""
    if v is None:
        return "缺值"
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def board_tier(amt):
    if amt is None:
        return "未分板块"
    for name, hi in BOARD_TIERS:
        if amt < hi:
            return name
    return BOARD_TIERS[-1][0]


def jj_ratio(jp, pre_percent, limit, preseal):
    """竞价强度比（tier_jj 同锚）：PRESEAL 用 pre_percent，否则限价；缺值 → None。"""
    denom = pre_percent if preseal else limit
    if jp is None or not denom:
        return None
    return jp / denom * 100


def is_one_word(o, l, lp, eps=EPS):
    """一字板：开≥涨停价 且 低≥涨停价（T 字板低<涨停 → False，保留）。"""
    return o >= lp - eps and l >= lp - eps


def seal_outcome(trial_sealed, tdx_close, o, l, lp, eps=EPS):
    """封板结局：trial percent 权威（None → TDX 收盘补证）；非一字 = 封板 ∧ 非一字。"""
    one_word = is_one_word(o, l, lp, eps)
    seal_final = trial_sealed if trial_sealed is not None else (tdx_close >= lp - eps)
    return {"seal_all": bool(seal_final), "seal_n1w": bool(seal_final and not one_word),
            "one_word": bool(one_word)}


def premium_pct(close_t, open_t1):
    """隔日开盘溢价 %；缺值/零收盘 → None（不进分母，不伪装 0）。"""
    if close_t is None or open_t1 is None or not close_t:
        return None
    return round((open_t1 / close_t - 1) * 100, 2)


def on_trading_axis(date, index_dates):
    """假期守卫：试盘日须在指数交易日历上（剔假期冒充档）。"""
    return date in index_dates


# ══════════ IO（本地 vipdoc 优先，在线兜底预算化）══════════
def _make_online_ctx(root):
    return {"root": root, "calls": 0, "cache": {}, "bars": {}}


def _online_ohlc(ctx, code, offset=250):
    key = f"{code}:{offset}"
    if key in ctx["cache"]:
        return ctx["cache"][key]
    if ctx["calls"] >= ONLINE_MAX:
        return None
    from tdxpy.hq import TdxHq_API
    from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2
    TdxHq_API.setup = lambda self: (SetupCmd1(self.client).call_api(), SetupCmd2(self.client).call_api())
    pool = json.loads((QB.parent / "python-bridge" / "tdx_hosts.json").read_text(encoding="utf-8"))["candidates"]
    market = 1 if code.startswith(("6", "9")) else 0
    out = None
    for h in pool[:15]:
        api = TdxHq_API(); ctx["calls"] += 1
        try:
            if not api.connect(h["ip"], int(h.get("port") or 7709), time_out=5):
                continue
            api.client.settimeout(10)
            try:
                bars = api.get_security_bars(9, market, code, 0, offset)
            finally:
                api.disconnect()
            if bars:
                out = {f"{int(b['year']):04d}-{int(b['month']):02d}-{int(b['day']):02d}":
                       [float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])] for b in bars}
                break
        except Exception:
            continue
        finally:
            time.sleep(0.2)
    ctx["cache"][key] = out
    return out


def _online_index_tail(ctx):
    from tdxpy.hq import TdxHq_API
    from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2
    TdxHq_API.setup = lambda self: (SetupCmd1(self.client).call_api(), SetupCmd2(self.client).call_api())
    pool = json.loads((QB.parent / "python-bridge" / "tdx_hosts.json").read_text(encoding="utf-8"))["candidates"]
    for h in pool[:15]:
        api = TdxHq_API(); ctx["calls"] += 1
        try:
            if not api.connect(h["ip"], int(h.get("port") or 7709), time_out=5):
                continue
            api.client.settimeout(10)
            try:
                bars = api.get_index_bars(9, 1, "000001", 0, 12)
            finally:
                api.disconnect()
            if bars:
                return [f"{int(b['year']):04d}-{int(b['month']):02d}-{int(b['day']):02d}" for b in bars]
        except Exception:
            continue
        finally:
            time.sleep(0.2)
    return []


def load_bars(ctx, code, need_upto, offline):
    if code in ctx["bars"]:
        bars = ctx["bars"][code]
    else:
        bars = None
        for prefix, market in jj._LOCAL_MARKETS:
            if code.startswith(prefix):
                recs = read_lday(os.path.join(ctx["root"], "vipdoc", market, "lday", f"{market}{code}.day"), take=320)
                if recs:
                    bars = {f"{r[0]//10000:04d}-{r[0]//100%100:02d}-{r[0]%100:02d}":
                            [r[1]/100, r[2]/100, r[3]/100, r[4]/100] for r in recs}
                break
        if bars is None and not offline:
            bars = _online_ohlc(ctx, code, 250)
        ctx["bars"][code] = bars
    if bars and need_upto not in bars and max(bars) < need_upto and not offline:
        tail = _online_ohlc(ctx, code, 20)
        if tail:
            m = dict(tail); m.update(bars); bars = m; ctx["bars"][code] = bars
    return bars


def board_map(rows, db):
    """root 板块全链（线上读口同口径单源）：direct > bridge > hist；primary 单值。"""
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    from backend.api import hotlist_jev_auction_routes as rt
    b_idx, b_meta = jiuyan_board.board_index(db)
    root_idx = jiuyan_industry_root.root_index(db)
    root_alias = jiuyan_industry_root.root_alias_map(db)
    bridge = rt._bridge_maps(db)
    need = set()
    for r in rows:
        c6 = r["code"]; b = b_idx.get(c6)
        if b:
            r["board"] = b; continue
        bb = []
        for n in rt._bridge_lookup(r.get("bk_name"), bridge["maps"], bridge["inds"]):
            rn = root_idx.get(n) or n
            if rn and rn not in bb:
                bb.append(rn)
        if bb:
            r["board"] = bb[0]; continue
        r["board"] = None; need.add(c6)
    if need and bridge["hist"]:
        hist = rt._bridge_hist(bridge["hist"], need)
        for r in rows:
            if r["code"] in need and hist.get(r["code"]):
                seen = []
                for n in hist[r["code"]]:
                    rn = root_alias.get(n, n)
                    if rn and rn not in seen:
                        seen.append(rn)
                if seen:
                    r["board"] = seen[0]
    return b_meta


# ══════════ 统计输出 ══════════
def rate_cell(g):
    """(n, 封板含一字%, 非一字封板%, 非一字中开≥5%, 一字占比%)；分母=有结局。"""
    n = len(g)
    if not n:
        return (0, None, None, None, None)
    seal = sum(1 for r in g if r["seal_all"])
    n1w = sum(1 for r in g if r["seal_n1w"])
    ow = sum(1 for r in g if r["one_word"])
    prem = [r for r in g if r["seal_n1w"] and r["openPct"] is not None]
    p5 = (sum(1 for r in prem if r["openPct"] >= 5)/len(prem)*100) if prem else None
    return (n, seal/n*100, n1w/n*100, p5, ow/n*100)


def _show_rate(title, groups, order=None):
    print(f"\n── {title} ──（n / 封板含一字 / 非一字封板 / 非一字中开≥5% / 一字占比）")
    for k in (order or sorted(groups, key=lambda k: -len(groups[k]))):
        g = groups.get(k, [])
        n, sa, sn, p5, ow = rate_cell(g)
        if not n:
            continue
        mark = "" if n >= 30 else "  [小样本]"
        p5s = f"{p5:5.1f}%" if p5 is not None else "  -  "
        print(f"  {k:18s} n={n:4d}  封板 {sa:5.1f}%  非一字 {sn:5.1f}%  溢价 {p5s}  一字 {ow:4.1f}%{mark}")


def _show_gradient(title, groups, min_n=8):
    print(f"\n── {title} ──（封板非一字人群 n / 开≥5% / 开均值 / 收≥5%）")
    for k, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        n = len(g)
        h5 = sum(r["openPct"] >= 5 for r in g)/n*100
        mo = sum(r["openPct"] for r in g)/n
        c5 = sum(r["closePct"] >= 5 for r in g)/n*100
        mark = "" if n >= min_n else "  [小样本]"
        print(f"  {k:20s} n={n:4d}  开≥5% {h5:5.1f}%  开均值 {mo:+6.2f}%  收≥5% {c5:5.1f}%{mark}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="d_from", default=None)
    ap.add_argument("--to", dest="d_to", default=None)
    ap.add_argument("--simulate", action="store_true", help="附 9:25 可见选股模拟")
    ap.add_argument("--offline", action="store_true", help="禁在线兜底（纯本地 vipdoc，缺棒 fail-visible）")
    ap.add_argument("--tag", default="full")
    args = ap.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    assert db.name == "dragon_board_quant", f"评估只读生产库，禁测试库: {db.name}"
    rows = bre.load_rows(db, args.d_from, args.d_to)
    names = {d["code"]: d.get("name") or "" for d in db["stock_names"].find({}, {"code": 1, "name": 1, "_id": 0})}
    st_fix = 0
    for r in rows:
        if "ST" in names.get(r["code"], "").upper() and r["limit"] != 5.0:
            r["limit"] = 5.0
            r["preseal"] = (r.get("pre_percent") or 0) >= 5.0*0.99
            r["sealed"] = None if r.get("percent") is None else r["percent"] >= 5.0*0.99
            st_fix += 1
    dates = sorted({r["date"] for r in rows})
    b_meta = board_map(rows, db)
    mapped = sum(1 for r in rows if r["board"])
    print(f"[0] {len(rows)} 行（{dates[0]}..{dates[-1]}，{len(dates)} 日）；ST 限价修正 {st_fix}；"
          f"root 板块全链 {mapped}/{len(rows)} ({mapped/len(rows)*100:.1f}%)；meta={b_meta}")

    root, _ = resolve_root()
    ctx = _make_online_ctx(root)
    idx_recs = read_lday(os.path.join(root, "vipdoc", "sh", "lday", "sh000001.day"), take=320)
    idx_dates = {f"{r[0]//10000:04d}-{r[0]//100%100:02d}-{r[0]%100:02d}" for r in idx_recs}
    if not args.offline:
        idx_dates |= set(_online_index_tail(ctx))
    axis = sorted(d for d in idx_dates if d >= dates[0])
    nxt = {d: axis[i+1] for i, d in enumerate(axis[:-1])}
    off_axis = sorted({r["date"] for r in rows if not on_trading_axis(r["date"], idx_dates)})
    if off_axis:
        print(f"[假期守卫] 剔除非交易日试盘档 {off_axis}（假期冒充，不进分析）")
        rows = [r for r in rows if on_trading_axis(r["date"], idx_dates)]

    flow = Counter()
    for r in rows:
        code, d = r["code"], r["date"]
        bars = load_bars(ctx, code, nxt.get(d, d), args.offline)
        r["seal_all"] = r["seal_n1w"] = r["one_word"] = None
        r["openPct"] = r["closePct"] = None
        if not bars or d not in bars:
            flow["T日无棒"] += 1; continue
        prev = [x for x in bars if x < d]
        if not prev:
            flow["无前棒"] += 1; continue
        pc = bars[max(prev)][3]; lp = round(pc*(1+r["limit"]/100), 2)
        o, h, l, c = bars[d]
        out = seal_outcome(r["sealed"], c, o, l, lp)
        r.update(out)
        flow["一字板"] += out["one_word"]
        d1 = nxt.get(d)
        if d1 and bars.get(d1):
            r["openPct"] = premium_pct(c, bars[d1][0])
            r["closePct"] = premium_pct(c, bars[d1][3])
        else:
            flow["T+1无棒(缺溢价)"] += 1
    scored = [r for r in rows if r["seal_all"] is not None]
    sealed_pop = [r for r in scored if r["seal_n1w"] and r["openPct"] is not None]
    n_sa = sum(1 for r in scored if r["seal_all"]); n_sn = sum(1 for r in scored if r["seal_n1w"])
    print(f"[1] 样本流 {dict(flow)}；有结局(封板率分母) {len(scored)}；封板含一字 {n_sa} ({n_sa/len(scored)*100:.1f}%)，"
          f"非一字 {n_sn} ({n_sn/len(scored)*100:.1f}%)；封板非一字有溢价 {len(sealed_pop)}")
    if sealed_pop:
        ops = sorted(r["openPct"] for r in sealed_pop)
        h5 = sum(1 for x in ops if x >= 5)/len(ops)*100
        print(f"[2] 封板非一字基率：开≥5% {h5:.1f}%  开均值 {sum(ops)/len(ops):+.2f}%  中位 {ops[len(ops)//2]:+.2f}%  "
              f"负溢价 {sum(1 for x in ops if x<0)/len(ops)*100:.1f}%")

    # 板块强度 + 个股档
    bd_amt = defaultdict(float)
    for r in rows:
        if r["board"]:
            bd_amt[(r["date"], r["board"])] += fnum(r.get("jj_amount")) or 0.0
    for r in rows:
        r["board_amt"] = bd_amt.get((r["date"], r["board"])) if r["board"] else None
        r["btier"] = board_tier(r["board_amt"])
        r["jjtier"] = bre.tier_jj(r)
        r["settle"] = bre.settlement_tier(r)

    bord_order = [t[0] for t in BOARD_TIERS] + ["未分板块"]
    g = defaultdict(list)
    for r in scored:
        g[r["btier"]].append(r)
    _show_rate("A. 板块竞价强度档 → 封板率", g, bord_order)
    g = defaultdict(list)
    for r in scored:
        g[r["jjtier"]].append(r)
    _show_rate("B. 个股竞价强度档 tier_jj → 封板率", g, ["top95", "mid50_95", "low_lt50", "no_ratio"])
    g = defaultdict(list)
    for r in scored:
        g[r["settle"]].append(r)
    _show_rate("C. 个股五档形态 → 封板率", g,
               ["hard_oneword", "no_cancel_settle", "cancel_strong", "cancel_neutral", "cancel_weak", "other"])

    print("\n── D. 板块强度档 × 个股 tier_jj → 非一字封板率（n / 非一字% / 溢价%）──")
    for bt in bord_order:
        line = f"  {bt:14s}"
        for jt in ["top95", "mid50_95", "low_lt50"]:
            cell = [r for r in scored if r["btier"] == bt and r["jjtier"] == jt]
            n, sa, sn, p5, ow = rate_cell(cell)
            if n < 1:
                line += f" | {jt}: -      "
            else:
                p5s = f"{p5:.0f}" if p5 is not None else "-"
                line += f" | {jt} n{n} {sn:.0f}%/溢{p5s}"
        print(line)

    print("\n── E. 具体 root 板块封板率排行（非一字，n≥40，Top15）──")
    gb = defaultdict(list)
    for r in scored:
        if r["board"]:
            gb[r["board"]].append(r)
    rank = []
    for b, gg in gb.items():
        n, sa, sn, p5, ow = rate_cell(gg)
        if n >= 40:
            rank.append((b, n, sa, sn, p5))
    for b, n, sa, sn, p5 in sorted(rank, key=lambda x: -x[3])[:15]:
        p5s = f"{p5:.1f}%" if p5 is not None else "-"
        print(f"  {b:16s} n={n:4d}  封板 {sa:5.1f}%  非一字 {sn:5.1f}%  溢价 {p5s}")

    print("\n── F. 最高非一字封板率组合（板块档×tier_jj×姿态，n≥30，Top12）──")
    gc = defaultdict(list)
    for r in scored:
        gc[(r["btier"], r["jjtier"], bre.posture(r))].append(r)
    combos = []
    for (bt, jt, po), gg in gc.items():
        n, sa, sn, p5, ow = rate_cell(gg)
        if n >= 30:
            combos.append((bt, jt, po, n, sn, p5))
    for bt, jt, po, n, sn, p5 in sorted(combos, key=lambda x: -x[4])[:12]:
        p5s = f"{p5:.1f}%" if p5 is not None else "-"
        print(f"  {bt:14s} × {jt:9s} × {po:8s} n={n:4d}  非一字 {sn:5.1f}%  溢价 {p5s}")

    # 4 维度梯度（封板非一字人群）
    print("\n── G. 4 维度梯度（封板非一字人群）──")
    for title, fn in [
        ("个股竞价成交额 jj_amount", lambda r: bucket(fnum(r.get("jj_amount")), [5e6, 1e7, 3e7, 1e8],
         ["<500万", "500-1000万", "1000-3000万", "3000万-1亿", "≥1亿"])),
        ("首加额 first_add", lambda r: ("缺值" if fnum(r.get("first_add")) is None else
         ("无首加(0)" if fnum(r.get("first_add")) == 0 else
          bucket(fnum(r.get("first_add")), [1e6, 5e6, 2e7], ["≤100万", "100-500万", "500-2000万", "≥2000万"])))),
        ("最终额 last_amount", lambda r: bucket(fnum(r.get("last_amount")), [5e6, 1e7, 3e7, 1e8],
         ["<500万", "500-1000万", "1000-3000万", "3000万-1亿", "≥1亿"])),
        ("板块竞价成交额(日Σ)", lambda r: board_tier(r.get("board_amt"))),
    ]:
        gg = defaultdict(list)
        for r in sealed_pop:
            gg[fn(r)].append(r)
        _show_gradient(title, gg)

    if args.simulate:
        # success 需溢价：T+1 缺棒行不进分母（fail-visible，缺失≠失败）
        _simulate([r for r in scored if r["openPct"] is not None])

    print(f"\n[done] 在线连接 {ctx['calls']} 次（offline={args.offline}）；tag={args.tag}")
    return 0


def _simulate(scored):
    """9:25 可见选股模拟：每 root 板块按竞价强度取前三，success=封板非一字∧开≥5%。"""
    print("\n========== H. 9:25 可见选股模拟（全试盘人群）==========")
    for r in scored:
        jp = fnum(r.get("jj_percent"))
        r["jj_at_limit"] = jp is not None and jp >= r["limit"]*0.99
        r["success"] = bool(r["seal_n1w"] and r["openPct"] is not None and r["openPct"] >= 5)

    def sel_stats(g, label):
        n = len(g)
        if not n:
            print(f"  {label:28s} n=0"); return
        seal = sum(1 for r in g if r["seal_n1w"])/n*100
        succ = sum(1 for r in g if r["success"])/n*100
        print(f"  {label:28s} n={n:4d}  封板非一字 {seal:5.1f}%  success {succ:5.1f}%")

    sel_stats(scored, "全试盘(基线)")
    buyable = [r for r in scored if not r["jj_at_limit"]]
    sel_stats(buyable, "剔一字候选(jj<限价)")
    bd_groups = defaultdict(list)
    for r in buyable:
        if r["board"]:
            bd_groups[(r["date"], r["board"])].append(r)
    sel_stats([r for gg in bd_groups.values() for r in gg], "有板块·全体(对照)")
    keys = {
        "jj_amount(竞价成交)": lambda r: fnum(r.get("jj_amount")) or 0,
        "jj_percent(竞价涨幅)": lambda r: fnum(r.get("jj_percent")) or -99,
        "jj_ratio(竞价/限价)": lambda r: jj_ratio(fnum(r.get("jj_percent")), r.get("pre_percent"), r["limit"], r["preseal"]) or -99,
        "first_add(首加额)": lambda r: fnum(r.get("first_add")) or 0,
        "last_amount(最终额)": lambda r: fnum(r.get("last_amount")) or 0,
        "jj_turnover(竞价换手)": lambda r: fnum(r.get("jj_turnover")) or 0,
    }
    for kname, kfn in keys.items():
        sel = []
        for gg in bd_groups.values():
            sel.extend(sorted(gg, key=lambda x: -kfn(x))[:3])
        sel_stats(sel, f"top3·{kname}")


if __name__ == "__main__":
    sys.exit(main())
