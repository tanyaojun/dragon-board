# -*- coding: utf-8 -*-
"""全市场跌停源测试（market_dieban_pool，2026-10-16 口径修正）。

背景：10-15 语料审计发现「跌停 6 家」是 250 只**采集池**口径，全市场实际 26 家
（东财跌停池实证）；趋势也被扭曲（真实 8/11/26 家 vs 池内 4→6 家）。

上游选型（用户 2026-10-16 裁决，双源）：
- **主源**：东财 push2ex 跌停池 `getTopicDTPool`——有历史（近 30 自然日窗口）、
  权威、与涨停/炸板池同族。**不走 akshare**：其内部是裸 requests.get（无节流/
  无 Referer/无会话复用），违反 skills/a-stock-data 东财防封铁律；本项目直连端点
  并套用 eastmoney_fund_provider 同款纪律（串行间隔+抖动、连接复用、403/429 熔断）。
- **兜底**：market_proxy 全市场行情快照（Redis 共享层，腾讯源 ~5500 行，
  f3=涨跌幅%）——无上游 IP 风险，但只服务「当日」。
- **末位降级**：采集池口径（250 只），叙事内显式标注「全市场源缺失」。

懒加载只在「当日 + 已过收盘截点」发生；历史日一律只读参考集合（防一次叙事
20 连发外呼），由 `backfill` 显式回填。本文件禁触真实 Redis/Mongo/东财：
monkeypatch `get_hotlist_redis_client`/`today_str`/`_em_http_client`。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import market_dieban_pool as mdp


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.writes: list[tuple] = []

    def find(self, query=None, projection=None):
        q = query or {}

        def match(r):
            for k, v in q.items():
                if isinstance(v, dict):
                    if "$exists" in v and (r.get(k) is None) != (not v["$exists"]):
                        return False
                    if "$ne" in v and r.get(k) == v["$ne"]:
                        return False
                elif r.get(k) != v:
                    return False
            return True

        return [dict(r) for r in self.rows if match(r)]

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query)
        return found[0] if found else None

    def replace_one(self, q, doc, upsert=False):
        self.writes.append((q, doc))
        self.rows = [r for r in self.rows if r.get("_id") != doc.get("_id")]
        self.rows.append(dict(doc))


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


class _FakeRedis:
    """假 Redis 客户端：hgetall 返回 code→json 行（或按配置抛错/返空）。"""

    def __init__(self, rows=None, exc=None):
        self._rows = rows if rows is not None else {}
        self._exc = exc

    def hgetall(self, key):
        if self._exc:
            raise self._exc
        return self._rows


def _row(code, pct):
    return code, json.dumps({"f12": code, "f14": f"股{code}", "f3": pct})


def _patch_redis(monkeypatch, rows=None, exc=None):
    monkeypatch.setattr(mdp, "get_hotlist_redis_client", lambda: _FakeRedis(rows, exc))


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None, raw=""):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeHttp:
    """假 httpx.Client：按 date 记录请求，按队列返响应或抛错。"""

    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        self.calls.append(str((params or {}).get("date")))
        if self.exc is not None:
            raise self.exc
        item = self.responses.pop(0) if self.responses else _FakeResponse()
        return item if not isinstance(item, Exception) else (_ for _ in ()).throw(item)


def _pool_payload(n, tc=None):
    return {"data": {"tc": n if tc is None else tc,
                     "pool": [{"c": f"60000{i}"} for i in range(max(n, 0))]}}


def _patch_em(monkeypatch, *, responses=None, exc=None):
    """注入假东财客户端 + 冻结节流状态（禁测试内真 sleep / 禁触网）。"""
    fake = _FakeHttp(responses, exc)
    monkeypatch.setattr(mdp, "_em_http_client", lambda: fake)
    monkeypatch.setattr(mdp, "_EM_MIN_INTERVAL", 0.0)
    return fake


# ── fetch_limit_down_em：东财跌停池（主源）─────────────────────────────────

def test_fetch_limit_down_em_returns_count_in_window(monkeypatch):
    """窗口内 → EM 池家数（10-15 实证 26）。"""
    http = _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(26))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-10-15") == 26
    assert http.calls == ["20261015"]          # 日期传 EM 的 YYYYMMDD 形


def test_fetch_limit_down_em_uses_total_when_pool_truncated(monkeypatch):
    """池行数 < EM 自报 tc（分页截断）→ 以 tc 兜底，宁多勿少。"""
    _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(3, tc=26))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-10-15") == 26


def test_fetch_limit_down_em_empty_pool_is_legit_zero(monkeypatch):
    """窗口内返空池 = 合法 0（当日确实无跌停），不是「不可算」。"""
    _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(0))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-09-25") == 0


def test_fetch_limit_down_em_none_outside_window_without_calling(monkeypatch):
    """窗口外 → None 且**不外呼**（EM 对更早日期只返 0，伪 0 会污染分位数）。"""
    http = _patch_em(monkeypatch)
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-05-06") is None
    assert http.calls == []


def test_fetch_limit_down_em_none_on_transport_error(monkeypatch):
    """连接超时/被拒（瞬态）→ None，不进冷却（下次仍可试）。"""
    _patch_em(monkeypatch, exc=httpx.ConnectError("refused"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-10-15") is None
    assert mdp._em_state["cooldown_until"] <= time.monotonic()


def test_fetch_limit_down_em_rate_limit_cools_down_and_never_retries(monkeypatch):
    """429/403 = 东财风控信号：立即冷却且绝不重试（SKILL 铁律）。"""
    http = _patch_em(monkeypatch, responses=[_FakeResponse(status_code=403),
                                             _FakeResponse(payload=_pool_payload(26))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    assert mdp.fetch_limit_down_em("2026-10-15") is None
    assert mdp._em_state["cooldown_until"] > time.monotonic()
    # 冷却期内第二次调用直接返 None，不再打上游（不刺激 WAF）
    assert mdp.fetch_limit_down_em("2026-10-14") is None
    assert http.calls == ["20261015"]


def test_fetch_limit_down_em_none_on_bad_payload(monkeypatch):
    """HTTP 200 但 body 非池结构（风控返空/HTML）→ None，不当作空池。"""
    _patch_em(monkeypatch, responses=[_FakeResponse(payload={"data": {}}),
                                      _FakeResponse(raw="<html>"),
                                      _FakeResponse(payload=[1, 2])])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    for _ in range(3):
        assert mdp.fetch_limit_down_em("2026-10-15") is None


# ── 快照统计：板块阈值判定（core/limit_rules 单一权威）────────────────────

def test_full_market_dieban_counts_by_board_rule(monkeypatch):
    """判定走 limit_rules：主板 -10 计、创业板 -11.9 不计（20cm 板）、北交所 -19.5 不计。"""
    _patch_redis(monkeypatch, dict([
        _row("600693", -10.01),   # 主板跌停 ✓
        _row("600026", -9.98),    # 主板跌停 ✓
        _row("300301", -12.47),   # 创业板 20cm：-12.47 非跌停 ✗
        _row("920162", -19.49),   # 北交所 30cm：非跌停 ✗
        _row("600000", 1.68),     # 上涨 ✗
    ]))
    assert mdp.full_market_dieban_from_quotes() == 2


def test_full_market_dieban_skips_malformed_rows(monkeypatch):
    """单行畸形 JSON 跳过，不阻断整体统计。"""
    _patch_redis(monkeypatch, {"600693": "{not-json", "600026": json.dumps({"f3": -10.0}),
                               "600000": json.dumps({"f12": "600000"})})
    assert mdp.full_market_dieban_from_quotes() == 1


def test_full_market_dieban_none_when_redis_unavailable(monkeypatch):
    """Redis 不可用 / key 过期（空快照）→ None（不可算，调用方降级，不伪 0）。"""
    _patch_redis(monkeypatch, rows={})
    assert mdp.full_market_dieban_from_quotes() is None
    _patch_redis(monkeypatch, exc=ConnectionError("down"))
    assert mdp.full_market_dieban_from_quotes() is None
    monkeypatch.setattr(mdp, "get_hotlist_redis_client", lambda: None)
    assert mdp.full_market_dieban_from_quotes() is None


# ── limit_down_count：当日懒加载（EM 主 / 快照兜底）/ 历史只读 / 回退 ──────

def test_limit_down_count_lazy_em_first_for_today(monkeypatch):
    """当日 + 已过收盘截点 + 参考集合 miss → 先打 EM 跌停池，upsert 落库再读。"""
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    http = _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(26))])

    def _snap_boom():
        raise AssertionError("EM 可用时不得再打行情快照")

    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", _snap_boom)
    db = FakeDb({})
    assert mdp.limit_down_count(db, "2026-10-16") == (26, mdp.SOURCE_EM)
    col = db.cols[mdp.COLLECTION]
    assert len(col.writes) == 1 and col.rows[0]["_id"] == "2026-10-16"
    assert col.rows[0]["source"] == mdp.SOURCE_EM
    assert mdp.limit_down_count(db, "2026-10-16") == (26, mdp.SOURCE_EM)
    assert http.calls == ["20261016"]   # 二次调用命中已落库行，不外呼
    assert len(col.writes) == 1


def test_limit_down_count_snapshot_fallback_when_em_unavailable(monkeypatch):
    """EM 不可用（窗口外/上游错）→ 回退全市场行情快照，source 标 quotes_snapshot。"""
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", lambda: 19)
    db = FakeDb({})
    assert mdp.limit_down_count(db, "2026-10-16") == (19, mdp.SOURCE_SNAPSHOT)
    assert db.cols[mdp.COLLECTION].rows[0]["source"] == mdp.SOURCE_SNAPSHOT


def test_limit_down_count_history_date_never_fetches(monkeypatch):
    """历史日（≠当日）不读实时快照、也不外呼 EM——禁止拿实时行情冒充历史日收盘。"""
    def _boom(*a, **k):
        raise AssertionError("历史日不得懒加载外呼")

    monkeypatch.setattr(mdp, "fetch_limit_down_em", _boom)
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", _boom)
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    db = FakeDb({})
    assert mdp.limit_down_count(db, "2026-10-15") == (None, "missing")


def test_limit_down_count_falls_back_to_pool_rows(monkeypatch):
    """当日但 EM 与快照皆不可用 → 回退采集池口径并标注 pool_rows；池也无数据 → missing。"""
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", lambda: None)
    rows = [{"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
             "slotTime": "15:00", "code": "600693", "pctChange": -10.0},
            {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
             "slotTime": "15:00", "code": "600026", "pctChange": -9.98},
            {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
             "slotTime": "15:00", "code": "600000", "pctChange": 1.0}]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert mdp.limit_down_count(db, "2026-10-16") == (2, mdp.SOURCE_POOL)
    db2 = FakeDb({"snapshot_stock_rows": FakeCol([])})
    assert mdp.limit_down_count(db2, "2026-10-16") == (None, "missing")


def test_limit_down_count_no_fetch_when_disallowed(monkeypatch):
    """allow_fetch=False（历史分位样本）→ 只读，miss 不外呼。"""
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")

    def _boom():
        raise AssertionError("历史样本不得触发外呼")

    monkeypatch.setattr(mdp, "fetch_limit_down_em", _boom)
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", _boom)
    db = FakeDb({})
    assert mdp.limit_down_count(db, "2026-10-16", allow_fetch=False) == (None, "missing")


def test_limit_down_count_intraday_never_writes(monkeypatch):
    """盘中（未过收盘截点）不读不写——盘中值落库会被后续叙事当收盘数复用（持久错值）。"""
    def _boom():
        raise AssertionError("盘中不得外呼")

    monkeypatch.setattr(mdp, "fetch_limit_down_em", _boom)
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", _boom)
    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: False)
    db = FakeDb({})
    assert mdp.limit_down_count(db, "2026-10-16") == (None, "missing")
    assert db.cols[mdp.COLLECTION].writes == []


# ── reference_counts：历史分位批量同源采样（一次 find，禁逐日连发）────────

def test_reference_counts_batch_and_source_filter():
    """批量读 + source 过滤：跨口径混采会污染分位，历史样本必须与当日同源。"""
    col = FakeCol([
        {"_id": "2026-10-15", "count": 26, "source": mdp.SOURCE_EM},
        {"_id": "2026-10-14", "count": 11, "source": mdp.SOURCE_EM},
        {"_id": "2026-10-13", "count": 8, "source": mdp.SOURCE_SNAPSHOT},  # 异源，排除
        {"_id": "2026-10-12", "count": "x", "source": mdp.SOURCE_EM},      # 脏值，排除
        {"_id": "2026-10-09"},                                            # 无 count，排除
    ])
    db = FakeDb({mdp.COLLECTION: col})
    got = mdp.reference_counts(db, ["2026-10-09", "2026-10-12", "2026-10-13",
                                    "2026-10-14", "2026-10-15"], mdp.SOURCE_EM)
    assert got == {"2026-10-14": 11, "2026-10-15": 26}


# ── backfill：EM 跌停池回填（dry-run 默认，--apply 落库）─────────────────

def _frames_col(dates):
    return FakeCol([{"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
                     "slotTime": "15:00"} for d in dates])


def test_backfill_dry_run_writes_nothing(monkeypatch, capsys):
    """dry-run 默认：只披露计划，不写库。"""
    _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(26))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([])
    db = FakeDb({mdp.COLLECTION: col, "snapshot_frames": _frames_col(["2026-10-15"])})
    mdp.backfill(db, "2026-10-15", "2026-10-15", apply=False)
    assert col.writes == []
    out = capsys.readouterr().out
    assert "dry-run" in out and "20261015" not in out and "2026-10-15" in out


def test_backfill_applies_em_rows_and_skips_existing(monkeypatch):
    """--apply：窗口内逐日 fetch + upsert；已回填日跳过（幂等，不重复外呼）。"""
    http = _patch_em(monkeypatch, responses=[_FakeResponse(payload=_pool_payload(26))])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([{"_id": "2026-10-14", "count": 11, "source": mdp.SOURCE_EM}])
    db = FakeDb({mdp.COLLECTION: col,
                 "snapshot_frames": _frames_col(["2026-10-14", "2026-10-15"])})
    mdp.backfill(db, "2026-10-14", "2026-10-15", apply=True)
    assert http.calls == ["20261015"]                   # 10-14 已回填，跳过
    assert sorted(r["_id"] for r in col.rows) == ["2026-10-14", "2026-10-15"]
    assert col.rows[-1]["count"] == 26 and col.rows[-1]["source"] == mdp.SOURCE_EM


def test_backfill_outside_window_reports_gap_not_zero(monkeypatch, capsys):
    """EM 窗口外 → 披露缺口，不写 0 行（「取不到」≠「真的 0 家」，AGENTS §4.0）。"""
    http = _patch_em(monkeypatch)
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([])
    db = FakeDb({mdp.COLLECTION: col, "snapshot_frames": _frames_col(["2026-05-06"])})
    mdp.backfill(db, "2026-05-06", "2026-05-06", apply=True)
    assert col.writes == [] and col.rows == [] and http.calls == []
    out = capsys.readouterr().out
    assert "[缺口] 2026-05-06" in out


def test_backfill_aborts_on_consecutive_upstream_failures(monkeypatch, capsys):
    """连续失败即熔断（东财封 IP 前科）：不再逐日硬打，剩余日照实披露缺口。"""
    http = _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([])
    db = FakeDb({mdp.COLLECTION: col,
                 "snapshot_frames": _frames_col(["2026-10-13", "2026-10-14", "2026-10-15"])})
    mdp.backfill(db, "2026-10-13", "2026-10-15", apply=True)
    assert col.writes == []
    assert len(http.calls) == mdp._EM_MAX_CONSECUTIVE_FAILURES   # 只打满阈值即停
    out = capsys.readouterr().out
    assert "熔断" in out
    assert out.count("[缺口]") == 3          # 三日都披露，不静默丢弃


def test_backfill_health_check_reports_gaps_without_writing(monkeypatch, capsys):
    """无 apply 的健康检查：已回填日跳过、缺口日照实披露，不写库。"""
    _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([{"_id": "2026-10-15", "count": 26, "source": mdp.SOURCE_EM}])
    db = FakeDb({mdp.COLLECTION: col,
                 "snapshot_frames": _frames_col(["2026-10-14", "2026-10-15"])})
    mdp.backfill(db, "2026-10-14", "2026-10-15", apply=False)
    assert col.writes == []
    assert [r["_id"] for r in col.rows] == ["2026-10-15"]
    out = capsys.readouterr().out
    assert "缺口 1 日" in out and "[缺口] 2026-10-14" in out
    assert "dry-run" in out


# ── 消费方：盘面事实行跌停段 ───────────────────────────────────────────────

def _facts_frames():
    return FakeCol([
        {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
         "slotTime": "15:00", "snapshotId": "h1", "timestamp": 2,
         "limitSummary": {"zhaban": {"ztCount": 36, "count": 7, "rate": 16.3},
                          "drawdown": {"count": 5}, "continuousBoards": {"maxBoard": 11},
                          "thsPools": {"ok": True, "degraded": False,
                                       "pools": {"failed": {"total": 0, "items": []}}}}}])


def _facts_db(die_refs=None, hist_dates=()):
    cols = {"snapshot_frames": _facts_frames(),
            "jiuyan_action": FakeCol([{"_id": "2026-10-16:final", "fields": [
                {"name": "板块A", "stocks": [{"code": "600001", "name": "A"}]}]}]),
            "snapshot_stock_rows": FakeCol([
                {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
                 "slotTime": "15:00", "code": "600001", "pctChange": 10.0},
                {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": "2026-10-16",
                 "slotTime": "15:00", "code": "600002", "pctChange": -10.0}])}
    # 历史交易日帧（trading_dates_before 的取数源）
    for d in hist_dates:
        cols["snapshot_frames"].rows.append(
            {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
             "slotTime": "15:00", "limitSummary": {}})
    if die_refs:
        cols[mdp.COLLECTION] = FakeCol(list(die_refs))
    return FakeDb(cols)


def test_market_facts_line_dieban_em_scope_and_same_source_history(monkeypatch):
    """EM 源：口径标「全市场·东财跌停池」，历史分位只采同源行（percentile 需 ≥10 样本）。

    10-13 是快照源（异源）——若混入会改变分位；此处只验证它不进样本：
    11 个 EM 同源日 → 分位可算；把 10-13 也算进去仍是 12 样本、同样可算，
    故异源排除由 test_reference_counts_batch_and_source_filter 单层锁，本层只锁口径文案。
    """
    from backend.operations.jev_label_jiuyan import market_facts_line

    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    em_days = ["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22",
               "2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30",
               "2026-10-08"]
    refs = [{"_id": d, "count": c, "source": mdp.SOURCE_EM}
            for d, c in zip(em_days, [0, 1, 0, 2, 3, 13, 13, 56, 10, 9, 13])]
    refs.append({"_id": "2026-10-16", "count": 26, "source": mdp.SOURCE_EM})
    refs.append({"_id": "2026-10-13", "count": 999, "source": mdp.SOURCE_SNAPSHOT})  # 异源
    db = _facts_db(refs, hist_dates=em_days + ["2026-10-13"])
    line = market_facts_line(db, "2026-10-16")
    assert "跌停 26 家（全市场·东财跌停池，" in line
    assert "采集池口径" not in line and "行情快照" not in line
    assert "分位不可算" not in line.split(" · ")[1]     # 11 个同源样本 → 分位可算


def test_market_facts_line_dieban_snapshot_scope_label(monkeypatch):
    """快照源：口径标「全市场·行情快照」。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    db = _facts_db([{"_id": "2026-10-16", "count": 19, "source": mdp.SOURCE_SNAPSHOT}])
    line = market_facts_line(db, "2026-10-16")
    assert "跌停 19 家（全市场·行情快照" in line
    assert "采集池口径" not in line


def test_market_facts_line_dieban_fallback_labels_pool_scope(monkeypatch):
    """EM 与快照皆不可用 → 回退采集池口径并标注，绝不自称全市场。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", lambda: None)
    db = _facts_db()   # 无参考集合行 → 懒加载 EM/快照皆败
    line = market_facts_line(db, "2026-10-16")
    assert "跌停 1 家（采集池口径，全市场源缺失" in line   # 池内仅 600002 一只跌停
    assert "全市场·" not in line


def test_market_facts_line_dieban_missing_no_fake_zero(monkeypatch):
    """采集池也无跌停记录（池空）→ 写不可算，不伪 0 家。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    _patch_em(monkeypatch, exc=httpx.ConnectError("blocked"))
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    monkeypatch.setattr(mdp, "full_market_dieban_from_quotes", lambda: None)
    db = _facts_db()
    db.cols["snapshot_stock_rows"] = FakeCol([])
    line = market_facts_line(db, "2026-10-16")
    assert "跌停 不可算" in line
    assert "跌停 0 家" not in line


def test_market_facts_line_no_empty_history_percentile_artifact(monkeypatch):
    """同源样本空（EM 窗口之前的历史日）→「分位不可算」，禁拼成「分位不可算 分位」病句。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    monkeypatch.setattr(mdp, "today_str", lambda: "2026-10-16")
    monkeypatch.setattr(mdp, "_snapshot_is_closing", lambda: True)
    db = _facts_db([{"_id": "2026-10-16", "count": 56, "source": mdp.SOURCE_EM}])
    line = market_facts_line(db, "2026-10-16")
    assert "分位不可算 分位" not in line
    assert "跌停 56 家（全市场·东财跌停池，分位不可算）" in line


def test_backfill_failure_counter_resets_on_success(monkeypatch, capsys):
    """熔断计数必须**成功即清零**（连续失败，不是累计失败）。

    累计计数下「一次抖动 + 隔日两次抖动」会在第 4 天误熔断，把 EM healthy 的日子整段
    标成缺口、叙事回退采集池口径——正是 §2.3 要避免的分位污染。上面那个全失败夹具
    区分不了两种语义，故补此例。_FakeHttp 队列里放 Exception 实例即模拟该日失败。
    """
    boom = httpx.ConnectError("blocked")
    ok11 = _FakeResponse(payload=_pool_payload(11))
    ok26 = _FakeResponse(payload=_pool_payload(26))
    # 09-17 失败 → 09-18/09-19 成功 → 09-22/09-23 失败 → 09-24 成功：
    # 最大连续失败只有 2（< 阈值 3），一日都不该被熔断跳过
    http = _patch_em(monkeypatch, responses=[boom, ok11, ok11, boom, boom, ok26])
    monkeypatch.setattr(mdp, "_em_window_start", lambda: "2026-09-16")
    col = FakeCol([])
    dates = ["2026-09-17", "2026-09-18", "2026-09-19", "2026-09-22", "2026-09-23", "2026-09-24"]
    db = FakeDb({mdp.COLLECTION: col, "snapshot_frames": _frames_col(dates)})
    mdp.backfill(db, "2026-09-17", "2026-09-24", apply=True)
    assert len(http.calls) == 6                 # 六日全部尝试过
    assert "连续失败熔断" not in capsys.readouterr().out   # 缺口行里的「熔断」二字是限流措辞
    assert sorted(r["_id"] for r in col.rows) == ["2026-09-18", "2026-09-19", "2026-09-24"]
    # 反证：真连续三次失败仍要熔断，第 4 日不外呼
    calls_before = len(http.calls)
    http.responses = [boom, boom, boom, ok26]
    col2 = FakeCol([])
    db2 = FakeDb({mdp.COLLECTION: col2,
                  "snapshot_frames": _frames_col(["2026-09-17", "2026-09-18", "2026-09-19",
                                                  "2026-09-22"])})
    mdp.backfill(db2, "2026-09-17", "2026-09-22", apply=True)
    assert len(http.calls) == calls_before + 3   # 第 4 日被熔断，未尝试
    assert "熔断" in capsys.readouterr().out
    assert [r["_id"] for r in col2.rows] == []
