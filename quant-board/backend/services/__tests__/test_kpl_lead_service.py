# -*- coding: utf-8 -*-
"""kpl_lead_service 单测（2026-11-10 板块身位/龙头三合一通道）。

口径：候选池=当日封板池∪近3交易日封板池（断板反包覆盖）；龙一=空间龙一锚
（rank_board_stocks_seal + segment_of，主轨优先）；龙二..N=dragon_rows 口径补位；
断板跌停剔除走 limit_rules.is_limit_down_pct（公共权威源，非硬编码）。
pytest 纪律：全部注入假库/注入 fetcher 桩，零真实 TDX/KPL/Mongo（红线 7）。
"""
from datetime import datetime

import pytest

from backend.services import kpl_lead_service as svc
from backend.services.kpl_lead_service import (
    archive_lead_snapshot,
    assemble_candidates,
    compute_and_archive_lead,
    compute_board_leads,
    lead_label,
    load_lead_corpus,
    state_boards,
    _hhmm,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

D_TODAY = "2026-11-10"       # 周二
D_D1 = "2026-11-09"          # 周一
D_D2 = "2026-11-06"          # 周五
POOL_DATES = [D_D2, D_D1]    # 升序（近3交易日，测试用 2 日足够）


def _ts(h: int, m: int) -> float:
    return datetime(2026, 11, 10, h, m, tzinfo=TZ_SHANGHAI).timestamp()


def _member(sid: str, *, state="首板", zt_time=None, plate_id="801159",
            pool_state="sealed", name=None) -> dict:
    return {"stock_id": sid, "name": name or f"股{sid}", "state": state,
            "zt_time": zt_time if zt_time is not None else _ts(9, 30),
            "plate_id": plate_id, "pool_state": pool_state}


class _LeadCollection:
    """仿 Mongo kpl_daban_pool：字段级 $set 合并 + 精确 _id 读（返回副本）。"""

    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows

    def update_one(self, q, update, upsert=False):
        assert "_id" not in update["$set"], "$set 不得改写 _id"
        row = self.rows.setdefault(q["_id"], {"_id": q["_id"]}) if upsert else self.rows.get(q["_id"])
        assert row is not None, "非 upsert 更新不应凭空造档"
        row.update(update["$set"])

    def find_one(self, q, projection=None):
        row = self.rows.get(q.get("_id"))
        return dict(row) if row else None


class _FramesCollection:
    def __init__(self, dates: list[str]) -> None:
        self._dates = dates

    def find(self, query, projection=None):
        lo = query.get("tradingDate", {}).get("$lt", "9999")
        return [{"tradingDate": d} for d in self._dates if d < lo]


class _LeadDb:
    def __init__(self, pool_rows: dict[str, dict], frame_dates: list[str]) -> None:
        self._pool = _LeadCollection(pool_rows)
        self._frames = _FramesCollection(frame_dates)

    def __getitem__(self, name: str):
        assert name in ("kpl_daban_pool", "snapshot_frames")
        return self._pool if name == "kpl_daban_pool" else self._frames


def _seed_db() -> _LeadDb:
    """三天池档：A(3连板 801159) / B(2连板) / C(首板 双创高 gain) / D(他板) / E(昨日封今日炸)
    / F(昨日封今日未封，断板反包候选高 gain) / H(昨日封今日跌停，剔除用)。"""
    pool_rows = {
        D_TODAY: {"_id": D_TODAY, "items": [
            _member("000001", state="5天3板", zt_time=_ts(9, 31)),        # A main
            _member("600001", state="2连板", zt_time=_ts(9, 30)),         # B main
            _member("300001", state="首板", zt_time=_ts(9, 35)),          # C growth
            _member("002001", plate_id="801464", zt_time=_ts(9, 40)),     # D 他板
            _member("000002", state="首板", pool_state="broken"),         # E 今日炸板=非封板
        ]},
        D_D1: {"_id": D_D1, "items": [
            _member("000001", state="4天3板"),
            _member("600001", state="2连板", zt_time=_ts(9, 29)),
            _member("000002", state="首板"),
            _member("603001", state="2连板", zt_time=_ts(9, 28)),         # F 断板反包候选
            _member("000003", state="首板"),                              # H 跌停剔除用
        ]},
        D_D2: {"_id": D_D2, "items": [
            _member("000001", state="3天2板"),
            _member("603001", state="2天2板"),   # F 连续两日封板后今日断板 → hist streak=2
        ]},
    }
    return _LeadDb(pool_rows, [D_D2, D_D1, D_TODAY])


def _gains_all(codes, date):
    table = {"000001": 25.0, "600001": 30.0, "300001": 60.0, "002001": 10.0,
             "603001": 40.0, "000002": 12.0, "000003": 5.0}
    return {c: table.get(c) for c in codes}


def _day_change(codes, date):
    return {"000002": -3.0, "000003": -10.5}    # H 主板 ≤-9.8 → 跌停剔除


# ── 纯函数 ────────────────────────────────────────────────────────────────────

def test_state_boards_and_labels():
    assert state_boards("5天3板") == 3 and state_boards("2连板") == 2
    assert state_boards("首板") == 1 and state_boards("昨日首板") is None
    assert state_boards("昨3连板") is None and state_boards("") is None
    # num 归一（韭研 num 格式）：_jiuyan_board_count 单源可解析 KPL 的连板/首板形态
    from backend.operations.jev_label_jiuyan import _jiuyan_board_count
    assert _jiuyan_board_count({"num": svc._num_jiuyan_format("2连板")}) == 2
    assert _jiuyan_board_count({"num": svc._num_jiuyan_format("首板")}) == 1
    assert _jiuyan_board_count({"num": svc._num_jiuyan_format("5天3板")}) == 3
    assert svc._num_jiuyan_format("昨日首板") is None
    assert lead_label(1) == "龙一" and lead_label(10) == "龙十"
    assert lead_label(11) == "十一" and lead_label(14) == "十四" and lead_label(20) == "二十"


def test_hhmm_epoch():
    assert _hhmm(_ts(9, 31)) == "09:31"
    assert _hhmm(0) is None and _hhmm(None) is None and _hhmm("x") is None


# ── 候选池组装 ────────────────────────────────────────────────────────────────

def test_assemble_candidates_union_and_unsealed():
    db = _seed_db()
    cands, meta = assemble_candidates(db, D_TODAY, pool_dates=POOL_DATES,
                                      gains_fetcher=_gains_all,
                                      day_change_fetcher=_day_change)
    assert cands is not None
    by = {c["code"]: c for c in cands}
    # 当日封板：streak=今日+连续封板日（A: 今日+11-09+11-06=3）
    assert by["000001"]["streak"] == 3 and by["000001"]["height"] == 3
    assert by["000001"]["time"] == "09:31" and by["000001"]["boards"] == 3
    # B: 今日+昨日=2；height=max(2, hist2)=2
    assert by["600001"]["streak"] == 2 and by["600001"]["height"] == 2
    # C: 今日首板（昨日未封）streak=1
    assert by["300001"]["streak"] == 1 and by["300001"]["height"] == 1
    # E 今日 broken=非封板 → 断板候选（sealed_today=False，hist streak=1）
    assert by["000002"]["sealed_today"] is False and by["000002"]["time"] is None
    assert by["000002"]["streak"] == 1
    # F 昨日封今日未封 → 断板候选，hist streak=2（连封两日后断板，近3日历史高度）
    assert by["603001"]["sealed_today"] is False and by["603001"]["height"] == 2
    # H 今日跌停（-10.5% 主板 ≤-9.8）→ 剔除（公共权威源 is_limit_down_pct）
    assert "000003" not in by
    assert meta["limit_down_excluded"].get("801159") and \
        meta["limit_down_excluded"]["801159"][0]["code"] == "000003"
    # 板块归属：全部候选带 plate_id（今日/最近封板日）
    assert by["000002"]["plate_id"] == "801159"   # 断板候选用最近封板日归属


def test_assemble_missing_day_and_plate():
    db = _seed_db()
    # 缺失池日：D_D2 无档日（换成一个无档日期）→ missing_pool_dates 披露
    cands, meta = assemble_candidates(db, D_TODAY, pool_dates=["2026-11-05", D_D1],
                                      gains_fetcher=_gains_all,
                                      day_change_fetcher=_day_change)
    assert meta["missing_pool_dates"] == ["2026-11-05"]
    assert meta["pool_dates"] == ["2026-11-05", D_D1]
    # 无 plate_id 的当日封板成员 → missing_plate 披露，不进板块榜
    db2 = _LeadDb({D_TODAY: {"_id": D_TODAY, "items": [
        _member("000009", plate_id="")]}}, [D_D2, D_D1])
    cands2, meta2 = assemble_candidates(db2, D_TODAY, pool_dates=POOL_DATES,
                                        gains_fetcher=_gains_all,
                                        day_change_fetcher=_day_change)
    assert meta2["missing_plate"] == ["000009"]
    assert all(c["code"] != "000009" for c in compute_board_leads(cands2)[0].get("801159", {}).get("items", []))


def test_assemble_no_pool_today():
    db = _seed_db()
    cands, _meta = assemble_candidates(db, "2026-11-01", pool_dates=POOL_DATES,
                                       gains_fetcher=_gains_all,
                                       day_change_fetcher=_day_change)
    assert cands is None        # 当日无池档 → None（不可计算，调用方不写库）


# ── 身位序列 ─────────────────────────────────────────────────────────────────

def test_compute_board_leads_ladder():
    db = _seed_db()
    cands, _meta = assemble_candidates(db, D_TODAY, pool_dates=POOL_DATES,
                                       gains_fetcher=_gains_all,
                                       day_change_fetcher=_day_change)
    boards, bmeta = compute_board_leads(cands)
    # gain 全缺披露（本样本 gain 全有 → 无）
    assert bmeta["gain_unavailable_plates"] == []
    lad = boards["801159"]["items"]
    codes = [it["code"] for it in lad]
    # 龙一锚=主轨空间龙一：空间板组（height≥2）gain10 最高 → F(40, main, 断板反包候选)
    assert lad[0]["code"] == "603001" and lad[0]["leader_basis"] == "space_main"
    assert lad[0]["label"] == "龙一" and lad[0]["sealed_today"] is False
    # 龙二..N = dragon_rows 口径（区间板数 M 降序 → 首封时间升序，断板 M 缺失垫后）：
    # A(3板) > B(2板) > 首板按时间 C(09:35) > E/M 缺失垫后
    assert codes[1:] == ["000001", "600001", "300001", "000002"]
    assert lad[1]["label"] == "龙二" and lad[1]["boards"] == 3
    assert lad[2]["label"] == "龙三" and lad[2]["boards"] == 2
    assert lad[3]["label"] == "龙四" and lad[3]["time"] == "09:35"
    assert lad[4]["label"] == "龙五" if len(lad) > 4 else True
    # 他板独立成榜（跨板块各排各的）
    assert [it["code"] for it in boards["801464"]["items"]] == ["002001"]
    assert boards["801464"]["items"][0]["leader_basis"] == "space_main"


def test_compute_board_leads_growth_only_plate():
    """纯双创板块：龙一锚取 growth 轨首位（_collapse_segment_rows 同构）。"""
    db = _LeadDb({D_TODAY: {"_id": D_TODAY, "items": [
        _member("300001", state="首板", zt_time=_ts(9, 35)),
        _member("688001", state="首板", zt_time=_ts(9, 36)),
    ]}}, [D_D2, D_D1])
    cands, _meta = assemble_candidates(db, D_TODAY, pool_dates=POOL_DATES,
                                       gains_fetcher=lambda c, d: {x: 10.0 for x in c},
                                       day_change_fetcher=_day_change)
    boards, _bm = compute_board_leads(cands)
    lad = boards["801159"]["items"]
    assert lad[0]["code"] == "300001" and lad[0]["leader_basis"] == "space_growth"


def test_gain_unavailable_disclosed():
    db = _seed_db()
    cands, _meta = assemble_candidates(db, D_TODAY, pool_dates=POOL_DATES,
                                       gains_fetcher=lambda c, d: {x: None for x in c},
                                       day_change_fetcher=_day_change)
    boards, bmeta = compute_board_leads(cands)
    # gain 全缺：不整板块跳过（展示层 §4.0），gain_unavailable 披露 + 排序按 -inf 退化
    assert "801159" in bmeta["gain_unavailable_plates"]
    assert boards["801159"]["gain_unavailable"] is True


# ── 落库/读口合同 ─────────────────────────────────────────────────────────────

def test_compute_and_archive_and_load():
    db = _seed_db()
    r = compute_and_archive_lead(db, D_TODAY,
                                 gains_fetcher=_gains_all,
                                 day_change_fetcher=_day_change)
    assert r["ok"] and r["boards_n"] == 2 and r["candidates_n"] >= 6
    loaded = load_lead_corpus(db, D_TODAY)
    assert loaded["ok"] and loaded["lane"] == "lead" and loaded["lead_source"] == "leader_trinity_v1"
    lad = loaded["lead_boards"]["801159"]["items"]
    assert lad[0]["code"] == "603001" and lad[0]["label"] == "龙一"
    assert loaded["lead_limit_down_excluded"]["801159"][0]["code"] == "000003"
    assert loaded["lead_pool_dates"] == POOL_DATES


def test_load_no_lead_corpus():
    db = _seed_db()
    loaded = load_lead_corpus(db, D_D2)     # 11-06 从未写过 lead
    assert loaded["ok"] is False and loaded["reason"] == "no_lead_corpus"


def test_archive_empty_payload_rejected():
    db = _LeadDb({}, [])
    r = archive_lead_snapshot(db, {"date": ""})
    assert r["ok"] is False and r["reason"] == "empty_lead_payload"
    r2 = compute_and_archive_lead(db, "2026-11-01",
                                  gains_fetcher=_gains_all,
                                  day_change_fetcher=_day_change)
    assert r2["ok"] is False and r2["reason"] == "no_pool_today"
