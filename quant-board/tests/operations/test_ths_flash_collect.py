# -*- coding: utf-8 -*-
"""同花顺 7×24 快讯采集测试（2026-11-14 盘前催化增量 C）——全部离线（mock 网络层），
零真实 HTTP / 零 jev 调用。

锁定口径（预登记 auction-preopen-catalyst-preregistration-20261114.md §4）：
1. 窗口 [T−1 日历日 15:00, 当日 09:26)（epoch 显式 UTC+8；09:26 截止防回放前视）；
2. 分页 ≤3 页，回溯至窗口起点即停 / 页尽即停；
3. 预算 `THS_FLASH_DAILY_CALL_BUDGET` 默认 8，逐页计数（失败同样计数）；
4. 页失败 60s 退避重试一次，仍失败 → meta.state=failed + degraded（有限次）；
5. 当日 meta ok 档在库 → 短路零 HTTP；items 幂等（首见不覆盖）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import ths_flash_collect as C
from backend.operations import ths_flash_fetch as F
from backend.operations import ths_flash_store as S
from backend.operations.jiuyan_theme_collect import THEME_COLLECT_RESULT_MARKER

TODAY = "2026-11-14"


def _item(idx: int, epoch: int, title: str = "物理AI板块午后拉升"):
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromtimestamp(epoch, timezone(timedelta(hours=8)))
    return {"id": str(1000 + idx), "seq": str(2000 + idx), "title": title,
            "digest": title, "ctimeEpoch": epoch, "ctimeDate": dt.strftime("%Y-%m-%d"),
            "ctimeHHMM": dt.strftime("%H:%M"), "source": "",
            "stocks": [{"name": "中科曙光", "code": "603019"}], "tags": ["AI"]}


def _payload(rows: list[dict]) -> dict:
    return {"code": "200", "data": {"list": [
        {"id": r["id"], "seq": r["seq"], "title": r["title"], "digest": r["digest"],
         "ctime": str(r["ctimeEpoch"]), "source": "",
         "stock": '[{"name": "中科曙光", "stockCode": "603019"}]',
         "tag": '[{"id": "1", "name": "AI"}]'} for r in rows]}}


# ── 解析层 ────────────────────────────────────────────────────────────
def test_parse_flash_payload_shape_and_ctime():
    from datetime import datetime, timedelta, timezone
    ep = int(datetime(2026, 11, 14, 8, 0, tzinfo=timezone(timedelta(hours=8))).timestamp())
    out = F.parse_flash_payload(_payload([_item(1, ep)]))
    assert out["ok"] is True and len(out["items"]) == 1
    it = out["items"][0]
    assert it["id"] == "1001" and it["ctimeEpoch"] == ep
    assert it["ctimeDate"] == "2026-11-14" and it["ctimeHHMM"] == "08:00"
    assert it["stocks"][0]["code"] == "603019" and it["tags"] == ["AI"]


def test_parse_flash_payload_rejects_bad_shape_and_missing_ctime():
    assert F.parse_flash_payload({"code": "500", "data": {"list": []}})["ok"] is False
    assert F.parse_flash_payload({"code": "200", "data": {"list": "str"}})["ok"] is False
    bad = F.parse_flash_payload({"code": "200", "data": {"list": [
        {"id": "x", "title": "无时间戳"}, {"id": "y", "title": "", "ctime": "123"}]}})
    assert bad["ok"] is True and bad["items"] == [], "缺 ctime/标题的残条如实剔除"


# ── 窗口与存储 ────────────────────────────────────────────────────────
def test_flash_window_epochs_utc8():
    start, end = S.flash_window_epochs("2026-11-14")
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    assert datetime.fromtimestamp(start, tz).strftime("%m-%d %H:%M") == "11-13 15:00"
    assert datetime.fromtimestamp(end, tz).strftime("%m-%d %H:%M") == "11-14 09:26"


def _fake_db():
    from tests.operations.test_jiuyan_theme_collect import FakeDb
    return FakeDb()


def test_save_flash_items_idempotent_and_window_query():
    db = _fake_db()
    start, end = S.flash_window_epochs(TODAY)
    in_win = _item(1, end - 3600, "固态电池量产发布")
    before_win = _item(2, start - 3600, "窗口前旧快讯")
    s1 = S.save_flash_items(db, fetch_date=TODAY, items=[in_win, before_win])
    assert s1["written"] == 2 and s1["skippedExisting"] == 0
    s2 = S.save_flash_items(db, fetch_date=TODAY, items=[in_win])
    assert s2 == {"written": 0, "skippedExisting": 1}, "重采幂等不覆盖"
    got = S.get_flash_window(db, start_epoch=start, end_epoch=end)
    assert [g["id"] for g in got] == ["1001"], "窗口过滤+降序"
    assert got[0]["firstSeenDate"] == TODAY


# ── 采集编排 ──────────────────────────────────────────────────────────
def test_collect_ok_stops_at_window_start(monkeypatch):
    db = _fake_db()
    start, end = S.flash_window_epochs(TODAY)
    page1 = [_item(i, end - 600 - i, f"物理AI{i}") for i in range(50)]   # 满页，继续翻
    pages = {
        1: page1,
        2: [_item(3, start - 600)],           # 首条已早于窗口起点 → 拉完即停
    }
    calls = {"n": 0}

    def fake_fetch(page, **kw):
        calls["n"] += 1
        return {"ok": True, "payload": _payload(pages.get(page, []))}
    monkeypatch.setattr(F, "fetch_flash_page", fake_fetch)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "ok"
    assert out["pages"] == 2 and out["reachedWindowStart"] is True
    assert calls["n"] == 2, "到窗口起点即停，第 3 页不发"
    assert out["written"] == 51 and S.calls_recorded(db, TODAY) == 2


def test_collect_short_circuit_when_meta_ok(monkeypatch):
    db = _fake_db()
    S.save_meta(db, fetch_date=TODAY, state="ok", pages=2, written=30, oldest_ctime=1)

    def _boom(page, **kw):
        raise AssertionError("meta ok 档在库必须短路零 HTTP")
    monkeypatch.setattr(F, "fetch_flash_page", _boom)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out.get("skipped") and out["reason"] == "already_covered"


def test_collect_budget_exhausted(monkeypatch):
    db = _fake_db()
    for _ in range(8):
        S.record_api_calls(db, TODAY, 1)

    def _boom(page, **kw):
        raise AssertionError("预算耗尽不得发 HTTP")
    monkeypatch.setattr(F, "fetch_flash_page", _boom)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["skippedByBudget"] == [C.SOURCE_FLASH]


def test_collect_disabled_switch(monkeypatch):
    db = _fake_db()
    monkeypatch.setenv("THS_FLASH_COLLECT_ENABLED", "0")

    def _boom(page, **kw):
        raise AssertionError("关断不得发 HTTP")
    monkeypatch.setattr(F, "fetch_flash_page", _boom)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out.get("skipped") and out["reason"] == "disabled"


def test_collect_page_fail_backoff_then_failed(monkeypatch):
    db = _fake_db()
    sleeps = []
    monkeypatch.setattr(C.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def fake_fetch(page, **kw):
        calls["n"] += 1
        return {"ok": False, "error": "ths_flash: HTTP 503"}
    monkeypatch.setattr(F, "fetch_flash_page", fake_fetch)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["state"] == "failed"
    assert calls["n"] == 2 and sleeps == [C.RETRY_SLEEP_SECONDS], "退避重试一次即停（有限次）"
    assert S.get_meta(db, date=TODAY)["state"] == "failed", "失败落 meta 覆盖档（fail-visible）"


def test_collect_second_attempt_recovers_after_failed_meta(monkeypatch):
    db = _fake_db()
    S.save_meta(db, fetch_date=TODAY, state="failed", pages=0, written=0, oldest_ctime=None)
    start, end = S.flash_window_epochs(TODAY)

    def fake_fetch(page, **kw):
        return {"ok": True, "payload": _payload([_item(1, end - 600)])}
    monkeypatch.setattr(F, "fetch_flash_page", fake_fetch)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "ok", "failed meta 不短路，下一槽可重试"


def test_cli_main_marker_and_exit_codes(monkeypatch, capsys):
    db = _fake_db()
    start, end = S.flash_window_epochs(TODAY)
    monkeypatch.setattr(F, "fetch_flash_page",
                        lambda page, **kw: {"ok": True,
                                            "payload": _payload([_item(1, end - 600)])})
    rc = C.main(["--date", TODAY])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith(THEME_COLLECT_RESULT_MARKER)]
    assert len(lines) == 1 and '"ok":true' in lines[0].replace(" ", "")


# ── 评审修复回归（2026-11-14 review）：预算准入 / dry-run 只读 / 半开窗口 ──

def test_collect_budget_admission_bounds_total_calls(monkeypatch):
    """每次 HTTP（首发+退避重试）前预算准入：总调用严格 ≤ 预算，超额即停落 failed。"""
    db = _fake_db()
    for _ in range(6):
        S.record_api_calls(db, TODAY, 1)          # 当日已用 6，预算 8
    sleeps = []
    monkeypatch.setattr(C.time, "sleep", lambda s: sleeps.append(s))

    def fake_fetch(page, **kw):
        return {"ok": False, "error": "ths_flash: HTTP 503"}   # 页1 恒失败 → 触发重试
    monkeypatch.setattr(F, "fetch_flash_page", fake_fetch)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["state"] == "failed"
    assert S.calls_recorded(db, TODAY) == 8, "首发+重试各计 1 次，达预算即停（不超耗）"
    assert sleeps == [C.RETRY_SLEEP_SECONDS]
    assert S.get_meta(db, date=TODAY)["state"] == "failed", "预算内耗尽也落 meta failed"


def test_collect_budget_admission_blocks_retry_after_exhaustion(monkeypatch):
    """满页消耗预算到上限后：下一页连首发都不发（准入拦截）。"""
    db = _fake_db()
    for _ in range(7):
        S.record_api_calls(db, TODAY, 1)          # 已用 7，预算 8 → 只够 1 次 HTTP
    start, _end = S.flash_window_epochs(TODAY)
    calls = {"n": 0}

    def fake_fetch(page, **kw):
        calls["n"] += 1
        # 满页（50 条）且全部在窗内 → 不触发页尽停机，继续翻第 2 页
        return {"ok": True,
                "payload": _payload([_item(i, start + 600 + i, f"物理AI{i}")
                                     for i in range(50)])}
    monkeypatch.setattr(F, "fetch_flash_page", fake_fetch)
    out = C.collect_once(db=db, fetch_date=TODAY)
    assert calls["n"] == 1, "第 2 页因预算准入不发 HTTP"
    assert out["ok"] is False and out["state"] == "failed"
    assert "budget_exhausted" in str(out.get("error"))


def test_collect_dry_run_is_read_only(monkeypatch):
    """dry-run 完全只读：不写预算计数、不落 items/meta（评审修复 P2-3）。"""
    db = _fake_db()
    start, end = S.flash_window_epochs(TODAY)
    monkeypatch.setattr(F, "fetch_flash_page",
                        lambda page, **kw: {"ok": True,
                                            "payload": _payload([_item(1, end - 600)])})
    out = C.collect_once(db=db, fetch_date=TODAY, dry_run=True)
    assert out["ok"] is True and out["written"] == 1
    assert S.calls_recorded(db, TODAY) == 0, "dry-run 不写生产预算计数"
    assert S.get_meta(db, date=TODAY) is None and not db[S.COLLECTION_FLASH].docs


def test_flash_window_half_open_excludes_exact_end():
    """半开区间 [T−1 15:00, 09:26)：恰 09:26:00 发布的条目不进晨间窗（评审修复 P2-2）。"""
    db = _fake_db()
    start, end = S.flash_window_epochs(TODAY)
    at_start = _item(1, start)                    # 恰起点 → 含
    at_end = _item(2, end)                        # 恰 09:26:00 → 不含
    inside = _item(3, end - 1)
    S.save_flash_items(db, fetch_date=TODAY, items=[at_start, at_end, inside])
    got = [g["id"] for g in S.get_flash_window(db, start_epoch=start, end_epoch=end)]
    assert sorted(got) == ["1001", "1003"], "半开窗口：起点含、终点 09:26:00 不含（降序返回）"
