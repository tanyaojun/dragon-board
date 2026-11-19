# -*- coding: utf-8 -*-
"""竞价三字段单一投影层测试（2026-11-19 用户裁决彻底版）。

fixture = 今日实档切片回放（tests/operations/fixtures/auction_trio_20261119.json，
只读勘察生成：bid_items 299 + mbl 8 帧 + 冻结 89 + series 关键帧压缩 + 15 labels doc）。
锚点（计划 §1/§2 实证）：600410 掉池 col10=124381050@09:23:23 / 派生换手 0.6132；
603030 公布 26669214/1.07/11109148；002685 公布 420443307/5.86/-8183651。
实施轮实证修正（见计划实施偏差记录）：census 净额缺位=218（非计划预期 36——
136 只深市掉池股虚拟额非零但净额未公布 + 34 沪市/早退 + 47 series-only + 002729
公布帧掉池）；留池真 0=40 保留；陈旧页（300857 终帧回放早退虚拟值）由 mbl 公布帧
优先 + series 公布后帧对拍剔除。零 jev 零外呼（AGENTS §1.2-7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_bidding_facts as M
from tests.series_fake import FakeSeriesCol, seed_series, seed_series_legacy

DATE = "2026-11-19"
FIXTURE = Path(__file__).parent / "fixtures" / "auction_trio_20261119.json"


def _col_for(name, v):
    """kpl_bidding_series 2026-11-19 逐 tick 文档化：旧嵌入 fixture 适配新形态。"""
    if name == "kpl_bidding_series":
        return seed_series_legacy(FakeSeriesCol(), v)
    return FakeCol(doc=v)


class FakeCol:
    def __init__(self, doc=None, docs=None):
        self.doc = doc
        self.docs = {str(d["_id"]): dict(d) for d in (docs or [])}
        self.updates = []

    def find_one(self, q=None, projection=None):
        if self.doc is not None:
            return json.loads(json.dumps(self.doc))
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return json.loads(json.dumps(d))
        return None

    def find(self, q=None, projection=None):
        out = []
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (q or {}).items()):
                out.append(json.loads(json.dumps(d)))
        return out

    def update_one(self, flt, update, upsert=False):
        self.updates.append((flt, update))
        d = self.docs.setdefault(flt["_id"], {"_id": flt["_id"]})
        d.update(update.get("$set") or {})


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}
        self.raises = set()

    def __getitem__(self, name):
        if name in self.raises:
            class Boom:
                def find_one(self, *a, **k):
                    raise RuntimeError("read_failed_simulated")

                def find(self, *a, **k):
                    raise RuntimeError("read_failed_simulated")
            return Boom()
        return self.cols.setdefault(name, FakeCol())


@pytest.fixture(scope="module")
def fx():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real(fx):
    db = FakeDb({k: _col_for(k, v) for k, v in fx.items()
                 if k != "hotlist_jev_auction_leader_labels"})
    db.cols["hotlist_jev_auction_leader_labels"] = FakeCol(
        docs=fx["hotlist_jev_auction_leader_labels"])
    return M.resolve_bidding_trio(db, DATE)


def _mk_db(bid_items=None, frames=None, frozen=None, ticks=None, bid_ts=None,
           fetched_at="2026-11-19T09:28:17+08:00"):
    cols = {}
    if bid_items is not None:
        cols["kpl_daban_pool"] = FakeCol({"_id": DATE, "bid_ts": bid_ts,
                                          "bid_items": bid_items})
    if frames is not None:
        cols["kpl_mbl_series"] = FakeCol({"_id": DATE, "frames": frames})
    if frozen is not None:
        cols["kpl_morning_bidding_raw"] = FakeCol(
            {"_id": DATE, "fetchedAt": fetched_at, "rows": frozen})
    if ticks is not None:
        cols["kpl_bidding_series"] = seed_series(FakeSeriesCol(), DATE, ticks)
    return FakeDb(cols)


def _raw(code, net=0, tur=0, amt=0, col10=0, cap=0):
    return [code, "", "", "", "", "", net, tur, amt, 0, col10, "", cap, "", 0, 0, ""]


def _frame(hmss, rows):
    return {"ts": f"{DATE}T{hmss}+08:00", "rows": rows}


def _tick(hmss, items):
    import datetime as dt
    ts = dt.datetime.fromisoformat(f"{DATE}T{hmss}+08:00").timestamp()
    return {"ts": ts, "it": items}


def _it(code, net=0.0, tur=0.0, amt=0.0, ztb=1e6, cap=None):
    d = {"s": code, "bidding_net": net, "bidding_turnover": tur,
         "bidding_amount": amt, "zt_buy_amount": ztb}
    if cap is not None:
        d["real_float"] = cap
    return d


# ══════ 实档回放（计划 §7-1/2/4/5/10 + 实施轮实证修正）══════

def test_replay_603030_in_pool_matched(real):
    f = real["facts"]["603030"]
    assert f["trio_state"] == "in_pool_matched"
    assert f["bidding_amount"] == 26669214.0
    assert f["bidding_amount_src"] == "mbl_postmatch"
    assert f["amount_ts"] == "09:26:20"
    assert f["bidding_turnover"] == 1.07
    assert f["bidding_net"] == 11109148.0
    assert f["bidding_net_state"] == "published"


def test_replay_600410_dropped_pre_match(real):
    """计划 §7-2 期望值：额=1.24 亿观测@09:23:23、换手派生 0.6132、净额缺位。"""
    f = real["facts"]["600410"]
    assert f["trio_state"] == "dropped_pre_match"
    assert f["bidding_amount"] == 124381050.0
    assert f["bidding_amount_src"] == "mbl_col10_preexit"
    assert f["amount_ts"] == "09:23:23"
    assert f["bidding_turnover"] == 0.6132
    assert f["bidding_turnover_src"] == "derived_cap"
    assert f["float_cap"] == 20285151636.0
    assert f["bidding_net"] is None and f["bidding_net_state"] == "missing"


def test_replay_002685_negative_net_published(real):
    f = real["facts"]["002685"]
    assert f["bidding_amount"] == 420443307.0
    assert f["bidding_turnover"] == 5.86           # 公布值优先于派生
    assert f["bidding_net"] == -8183651.0          # 负额公布事实保留
    assert f["bidding_net_state"] == "published"


def test_replay_census(real):
    """实施轮实证 census（计划预期 36 被原料证伪：136 深市掉池虚拟额股净额
    未公布 + 47 series-only + 002729 边界；按投影口径断言，计划 §7-10）。"""
    c = real["census"]
    assert c["total_n"] == 346          # bid 299 ∪ series 342 ∪ mbl/frozen
    assert c["matched_n"] == 128        # 留池到公布后（last_seen ≫ 公布锚）
    assert c["preexit_n"] == 218
    assert c["virtual_n"] == 0          # 盘后日无窗内态
    assert c["net_missing_n"] == 218
    assert c["true_zero_net_n"] == 40   # 真 0 保留（39 买卖平衡 + 1 冻结 col14/15=0）
    assert c["derived_tur_n"] == 191
    assert c["no_cap_n"] == 16
    assert real["state"]["tsPub"] == "09:25:13"
    assert real["state"]["noMblSeriesDay"] is False


def test_replay_true_zero_preserved(real):
    """状态门而非值门：留池撮合后真 0 是事实（一字无对手盘 + 买卖平衡）。"""
    for c in ("600671", "600615"):      # 一字板：全日 (0,0,0)
        f = real["facts"][c]
        assert f["trio_state"] == "in_pool_matched"
        assert f["bidding_amount"] == 0.0 and f["bidding_net"] == 0.0
        assert f["bidding_net_state"] == "published"
    f = real["facts"]["002123"]         # 买卖平衡：577 帧净额恒 0，虚拟额收敛=公布额
    assert f["bidding_net"] == 0.0 and f["bidding_net_state"] == "published"
    assert f["bidding_amount"] == 512502.0
    assert "pub_values_equal_virtual" in f["reasons"]   # 不可值门区分形态披露


def test_replay_stale_page_rescued_by_mbl(fx):
    """陈旧页案（300857，12:55 实证快照注入：终帧回放 09:19:05 虚拟值
    8086800/net0；生产库持续自愈，13:08 帧已覆写为公布值——投影对两种终态
    均正确）：mbl 公布帧 101707289/27741379 权威优先 + 对拍不一致披露。"""
    db = _labels_db(fx)
    bi = next(i for i in db.cols["kpl_daban_pool"].doc["bid_items"]
              if i["stock_id"] == "300857")
    bi["bidding_amount"] = 8086800.0   # 12:55 观测陈旧终态（实证锚）
    bi["bidding_net"] = 0.0
    bi["bidding_turnover"] = 0.0
    out = M.resolve_bidding_trio(db, DATE)
    f = out["facts"]["300857"]
    assert f["bidding_amount"] == 101707289.0
    assert f["bidding_net"] == 27741379.0
    assert f["bidding_amount_src"] == "mbl_postmatch"
    assert "amount_mismatch_bid_frozen" in f["reasons"]


def test_replay_exit_at_pub_frame(real):
    """002729：恰在公布帧（09:25:13）掉池，该帧仍携带早退值 → 缺位不烘 0。"""
    f = real["facts"]["002729"]
    assert f["trio_state"] == "dropped_pre_match"
    assert "exit_at_pub_frame" in f["reasons"]
    assert f["bidding_net"] is None
    assert f["bidding_amount"] == 283176.0   # col10 掉池前观测（09:24:51）


def test_replay_early_exit_no_virtual_match(real):
    """002799/002571：早退+无虚拟撮合（col10=0）→ 三字段保守缺位（计划 §10）。"""
    for c in ("002799", "002571"):
        f = real["facts"][c]
        assert f["trio_state"] == "dropped_pre_match"
        assert f["bidding_amount"] is None
        assert f["bidding_turnover"] is None
        assert f["bidding_net"] is None


# ══════ 合成边界（状态机/派生/回退/降级）══════

def test_live_pre_match_window_net_missing():
    """实时窗内（无公布锚）：留池股 net=None 不伪 0，额=col10 虚拟、换手派生。"""
    db = _mk_db(
        bid_items=[{"stock_id": "002685", "bidding_amount": 19641609.0,
                    "bidding_net": 0.0, "bidding_turnover": 0.0,
                    "real_float": 7172168867.0, "last_seen_ts": 1.0}],
        frames=[_frame("09:15:35", [_raw("002685", col10=19641609, cap=7172168867)]),
                _frame("09:17:11", [_raw("002685", col10=23274889, cap=7172168867)])],
        ticks=[_tick("09:15:35", [_it("002685", amt=19641609.0)]),
               _tick("09:17:11", [_it("002685", amt=23274889.0)])],
        bid_ts=1.0)
    # bid last_seen 设为末帧时点（在池）
    import datetime as dt
    ts = dt.datetime.fromisoformat(f"{DATE}T09:17:11+08:00").timestamp()
    db.cols["kpl_daban_pool"].doc["bid_items"][0]["last_seen_ts"] = ts
    db.cols["kpl_daban_pool"].doc["bid_ts"] = ts
    out = M.resolve_bidding_trio(db, DATE)
    f = out["facts"]["002685"]
    assert f["trio_state"] == "in_pool_pre_match"
    assert f["bidding_amount"] == 23274889.0
    assert f["bidding_amount_src"] == "mbl_col10_virtual"
    assert f["bidding_net"] is None and f["bidding_net_state"] == "missing"
    assert f["bidding_turnover"] == round(23274889 / 7172168867 * 100, 4)
    assert out["census"]["virtual_n"] == 1 and out["census"]["net_missing_n"] == 1


def test_derived_turnover_anchors():
    """派生换手锚（计划 §2-2）：002685→5.8622≡公布 5.86；603030→1.0668≡1.07。"""
    assert M._derive_turnover(420443307, 7172168867) == 5.8622
    assert M._derive_turnover(26669214, 2499813743) == 1.0668
    assert M._derive_turnover(124381050, 20285151636) == 0.6132
    assert M._derive_turnover(None, 1e9) is None
    assert M._derive_turnover(1e6, None) is None
    assert M._derive_turnover(1e6, 0) is None


def test_no_float_cap_reason():
    """掉池股有额无市值 → 换手 None + no_float_cap（census no_cap_n）。"""
    db = _mk_db(
        bid_items=[{"stock_id": "600410", "bidding_amount": 0.0,
                    "last_seen_ts": 1.0}],
        frames=[_frame("09:15:35", [_raw("600410", col10=124381050)]),
                _frame("09:24:51", [])])
    out = M.resolve_bidding_trio(db, DATE)
    f = out["facts"]["600410"]
    assert f["bidding_amount"] == 124381050.0
    assert f["bidding_turnover"] is None
    assert "no_float_cap" in f["reasons"]
    assert out["census"]["no_cap_n"] == 1


def test_no_mbl_series_day_fallback_state_gate():
    """历史日回退（≤11-16）：>0 保留；==0 留池真 0 保留；==0 掉池 → None。"""
    import datetime as dt
    t925 = dt.datetime.fromisoformat(f"{DATE}T09:26:00+08:00").timestamp()
    t916 = dt.datetime.fromisoformat(f"{DATE}T09:16:00+08:00").timestamp()
    db = _mk_db(bid_items=[
        {"stock_id": "603030", "bidding_amount": 26669214.0, "bidding_net": 0.0,
         "bidding_turnover": 1.07, "last_seen_ts": t925, "real_float": 2499813743.0},
        {"stock_id": "600410", "bidding_amount": 0.0, "bidding_net": 0.0,
         "bidding_turnover": 0.0, "last_seen_ts": t916, "real_float": 20285151636.0},
        {"stock_id": "002685", "bidding_amount": 420443307.0, "bidding_net": -8183651.0,
         "bidding_turnover": 5.86, "last_seen_ts": t916}])
    out = M.resolve_bidding_trio(db, DATE)
    assert out["state"]["noMblSeriesDay"] is True
    a = out["facts"]["603030"]   # 留池：真 0 净额保留
    assert a["trio_state"] == "no_mbl_series_day"
    assert a["bidding_net"] == 0.0 and a["bidding_net_state"] == "published"
    assert a["bidding_amount"] == 26669214.0
    b = out["facts"]["600410"]   # 掉池：零值缺位
    assert b["bidding_amount"] is None and b["bidding_net"] is None
    assert b["bidding_net_state"] == "missing"
    c = out["facts"]["002685"]   # 掉池但非 0 = 公布事实保留
    assert c["bidding_net"] == -8183651.0 and c["bidding_amount"] == 420443307.0


def test_not_in_auction_pool_and_tencent_priority():
    """榜外入选股三 None；腾讯补源实测值优先于派生（sup_live_only 留痕）。"""
    db = _mk_db(bid_items=[{"stock_id": "603030", "bidding_amount": 1.0,
                            "last_seen_ts": 1.0}])
    out = M.resolve_bidding_trio(db, DATE, codes=["999999"])
    f = out["facts"]["999999"]
    assert f["trio_state"] == "not_in_auction_pool"
    assert f["bidding_amount"] is None and f["bidding_net"] is None
    assert out["census"]["not_in_pool_n"] == 1
    items = {"999999": {"source": "tencent_auction", "bidding_pct": 10.0,
                        "bidding_amount": 5e6, "bidding_turnover": 0.5,
                        "bidding_net": -1e5, "zt_buy_amount": 8e6}}
    M.apply_trio(items, out["facts"])
    it = items["999999"]
    assert it["bidding_amount"] == 5e6 and it["bidding_net"] == -1e5
    assert it["bidding_amount_src"] == "tencent_auction"
    assert it["bidding_net_state"] == "published"
    assert "sup_live_only" in it["trio_reasons"]
    assert it["zt_buy_amount"] == 8e6   # 非三字段不碰


def test_read_failure_degrades_not_blocks():
    """单集合读异常 → 该源降级 + reason，其余源照常投影（§4.0）。"""
    db = _mk_db(bid_items=[{"stock_id": "603030", "bidding_amount": 26669214.0,
                            "bidding_net": 11109148.0, "bidding_turnover": 1.07,
                            "last_seen_ts": 1.0}])
    db.raises.add("kpl_mbl_series")
    out = M.resolve_bidding_trio(db, DATE)
    assert any(r.startswith("read_failed:kpl_mbl_series") for r in out["state"]["reasons"])
    f = out["facts"]["603030"]   # 无 mbl 帧 → 历史回退态，值仍可读
    assert f["bidding_amount"] == 26669214.0
    assert f["bidding_net"] == 11109148.0


def test_apply_trio_preserves_non_trio_fields(real):
    """apply_trio 只覆写三字段 + src/state；quotas/price/pct/委买额 raw 保全。"""
    item = {"stock_id": "600410", "name": "华胜天成", "bidding_pct": 9.98811,
            "bidding_amount": 0.0, "bidding_net": 0.0, "bidding_turnover": 0.0,
            "zt_buy_amount": 124802850.0, "pct": 9.99, "price": 12.3,
            "quotas": ["0"] * 28, "plate": "AI硬件"}
    M.apply_trio([item], real["facts"])
    assert item["bidding_amount"] == 124381050.0
    assert item["bidding_net"] is None
    assert item["bidding_net_state"] == "missing"
    assert item["trio_state"] == "dropped_pre_match"
    assert item["amount_ts"] == "09:23:23"
    assert item["zt_buy_amount"] == 124802850.0
    assert item["pct"] == 9.99 and item["price"] == 12.3
    assert item["quotas"] == ["0"] * 28 and item["plate"] == "AI硬件"
    assert item["bidding_pct"] == 9.98811   # 竞价涨幅 raw 不碰（早退观测语义独立）


def test_stale_bid_final_rescued_by_series_pick():
    """bid 终态陈旧 + 无 mbl 公布帧 → series 公布后首个净额非零帧对拍 rescue。"""
    import datetime as dt
    t_pub = dt.datetime.fromisoformat(f"{DATE}T09:25:13+08:00").timestamp()
    t_net = dt.datetime.fromisoformat(f"{DATE}T09:25:50+08:00").timestamp()
    t_end = dt.datetime.fromisoformat(f"{DATE}T11:29:01+08:00").timestamp()
    db = _mk_db(
        bid_items=[{"stock_id": "300857", "bidding_amount": 8086800.0,
                    "bidding_net": 0.0, "bidding_turnover": 0.0,
                    "last_seen_ts": t_end}],
        ticks=[_tick("09:24:36", [_it("300857", amt=39435400.0)]),
               _tick("09:25:13", [_it("300857", amt=101707289.0, tur=0.23),
                                  _it("603030", amt=26669214.0, tur=1.07)]),
               _tick("09:25:50", [_it("300857", amt=101707289.0, tur=0.23,
                                      net=27741379.0)]),
               _tick("11:29:01", [_it("300857", amt=8086800.0)])],
        bid_ts=t_end)
    out = M.resolve_bidding_trio(db, DATE)
    f = out["facts"]["300857"]
    assert f["bidding_amount"] == 101707289.0
    assert f["bidding_net"] == 27741379.0
    assert f["bidding_amount_src"] == "series_postmatch"
    assert "bid_frozen_stale_diff" in f["reasons"]


# ══════ 语料外科重建（计划 §4.8/§7-12）══════

def _labels_db(fx):
    db = FakeDb({k: _col_for(k, v) for k, v in fx.items()
                 if k != "hotlist_jev_auction_leader_labels"})
    db.cols["hotlist_jev_auction_leader_labels"] = FakeCol(
        docs=fx["hotlist_jev_auction_leader_labels"])
    return db


def test_rebuild_path_b_fallback_600410(fx):
    """今日存量档（无 bidLine）路径 B：600410 行无「竞价净额」、有「竞价成交额
    1.24亿」观测串；伪 0 竞昨比（旧额 0 派生）剔除；其余行零漂移。"""
    db = _labels_db(fx)
    doc0 = next(d for d in fx["hotlist_jev_auction_leader_labels"]
                if d.get("code") == "600410")
    rep = M.rebuild_auction_bid_lines(db, DATE)
    assert rep["ok"] and rep["fallback_n"] >= 1
    col = db.cols["hotlist_jev_auction_leader_labels"]
    new = col.docs[f"{DATE}:600410"]
    bid_lines = [ln for ln in new["narrative"].split("\n") if ln.startswith("竞价（")]
    assert len(bid_lines) == 1
    ln = bid_lines[0]
    assert "竞价净额" not in ln            # 缺位整段缺席（红线 8）
    assert "竞价成交额 1.24亿" in ln       # col10 掉池前观测
    assert "竞价换手 0.6132%" in ln        # 派生换手
    assert "竞昨比" not in ln              # 旧 ratio 0.00% 由缺位额派生 = 伪 0 → 剔除
    assert "同板竞价对比 华东重机 +10.04% 额 4.20亿" in ln   # peers 投影值
    assert new["bidLine"] == ln
    assert new["bidLineState"]["codes"]["600410"]["net_state"] == "missing"
    assert new["rebuiltAt"] and new["rebuildReason"]
    # 其余行零漂移（逐行对照，仅六件套行替换）
    old_lines = doc0["narrative"].split("\n")
    new_lines = new["narrative"].split("\n")
    assert len(old_lines) == len(new_lines)
    diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(diff) == 1 and diff[0][0].startswith("竞价（")


def test_rebuild_valid_ratio_carryover(fx):
    """留池股旧竞昨比（旧额>0 派生）原串保留（basis 离线不可恢复，零外呼）。"""
    db = _labels_db(fx)
    doc0 = next(d for d in fx["hotlist_jev_auction_leader_labels"]
                if d.get("code") == "603030")
    old_ln = next(ln for ln in doc0["narrative"].split("\n") if ln.startswith("竞价（"))
    import re
    m = re.search(r"竞昨比 ([\d.]+)%", old_ln)
    rep = M.rebuild_auction_bid_lines(db, DATE)
    new = db.cols["hotlist_jev_auction_leader_labels"].docs[f"{DATE}:603030"]
    new_ln = new["bidLine"]
    if m and float(m.group(1)) > 0:
        assert f"竞昨比 {m.group(1)}%" in new_ln
    assert "竞价净额 0.11亿" in new_ln   # 公布净额照出（11109148 → 0.11亿）
    assert rep["ok"]


def test_rebuild_path_a_exact_replace_and_remove(fx):
    """路径 A：doc.bidLine 精确整行替换；投影后全缺 → 删行；answers/outcome 不碰。"""
    db = _labels_db(fx)
    col = db.cols["hotlist_jev_auction_leader_labels"]
    # 600410 档注入 bidLine（路径 A）+ answers/outcome 守卫值
    doc = col.docs[f"{DATE}:600410"]
    old_ln = next(ln for ln in doc["narrative"].split("\n") if ln.startswith("竞价（"))
    doc["bidLine"] = old_ln
    doc["answers"] = {"auction_leader_seal_today": {"choice": "mid_45_65"}}
    doc["outcomeSealedToday"] = True
    rep = M.rebuild_auction_bid_lines(db, DATE)
    new = col.docs[f"{DATE}:600410"]
    assert new["answers"] == doc["answers"]
    assert new["outcomeSealedToday"] is True
    assert new["bidLine"] != old_ln and "竞价净额" not in new["bidLine"]
    entry = next(d for d in rep["per_doc"] if d["_id"] == f"{DATE}:600410")
    assert entry["fallback"] is False and entry["action"] == "replaced"
    # 删行路径：榜外股（投影全缺）doc → new=None → 整行移除
    ghost = {"_id": f"{DATE}:999999", "tradingDate": DATE, "docKind": "leader",
             "code": "999999", "name": "榜外股", "board": "测试板",
             "boardSource": "jiuyan_action_t1",
             "narrative": f"{DATE} 交易日 · 竞价龙头盘前投喂\n待判龙头：榜外股（999999）\n"
                          "竞价（09:25 匹配价）：榜外股 竞价涨幅 +5.00%\n题材证据块：测试",
             "bidLine": "竞价（09:25 匹配价）：榜外股 竞价涨幅 +5.00%"}
    col.docs[ghost["_id"]] = ghost
    rep2 = M.rebuild_auction_bid_lines(db, DATE)
    g2 = col.docs[ghost["_id"]]
    assert "竞价（" not in g2["narrative"]
    assert g2["bidLine"] is None
    e2 = next(d for d in rep2["per_doc"] if d["_id"] == ghost["_id"])
    assert e2["action"] == "removed" and rep2["removed_n"] >= 1


def test_rebuild_frozen_guard_default_deny(fx):
    """冻结守卫：corpusFrozen 默认拒绝；显式授权才绕过（留痕）。"""
    db = _labels_db(fx)
    col = db.cols["hotlist_jev_auction_leader_labels"]
    col.docs[f"{DATE}:600410"]["corpusFrozen"] = True
    rep = M.rebuild_auction_bid_lines(db, DATE)
    assert rep["skipped_frozen_n"] >= 1
    e = next(d for d in rep["per_doc"] if d["_id"] == f"{DATE}:600410")
    assert e["action"] == "skipped_frozen"
    assert "rebuiltAt" not in col.docs[f"{DATE}:600410"]
    rep2 = M.rebuild_auction_bid_lines(db, DATE, authorize_frozen_bypass=True,
                                       rebuild_reason="用户授权测试")
    e2 = next(d for d in rep2["per_doc"] if d["_id"] == f"{DATE}:600410")
    assert e2["action"] == "replaced"
    assert col.docs[f"{DATE}:600410"]["rebuildReason"] == "用户授权测试"


def test_rebuild_zero_jev_zero_external(fx, monkeypatch):
    """重建零 jev（§1.2-7）：_dispatch_jev 被调即炸；重建照常完成。"""
    def _boom(*a, **k):
        raise AssertionError("rebuild 禁止 jev 调用")
    monkeypatch.setattr("backend.services.jev.jev_sentiment_compute._dispatch_jev", _boom)
    db = _labels_db(fx)
    rep = M.rebuild_auction_bid_lines(db, DATE)
    assert rep["ok"] and rep["docs_n"] == 15
    assert rep["replaced_n"] + rep["removed_n"] + rep["no_change_n"] == 15


def test_rebuild_idempotent_second_run(fx):
    """二次重建幂等：首轮后 doc 带 bidLine（路径 A），新串==旧串 → no_change。"""
    db = _labels_db(fx)
    rep1 = M.rebuild_auction_bid_lines(db, DATE)
    assert rep1["replaced_n"] > 0
    rep2 = M.rebuild_auction_bid_lines(db, DATE)
    assert rep2["replaced_n"] == 0 and rep2["removed_n"] == 0
    assert rep2["no_change_n"] == rep2["docs_n"]
