# -*- coding: utf-8 -*-
"""韭研早报晨间采集测试（2026-11-14 晨间例外）——全部离线（mock 网络层），零真实 HTTP / 零 jev 调用。

锁定口径（预登记 auction-preopen-catalyst-preregistration-20261114.md §3）：
1. `is_briefing` 语义：标题 ∈ BRIEFING_TITLES（早报/盘前必读）或正文「1、热点事件」开头；
   复盘/收盘必读是盘后产物**不收**（对 09:26 晨间窗是前视）；
2. 当日块缺席 = `not_published`（结构化状态非失败，等下一尝试槽）；
3. errCode=9 短时限流 → 60s 退避重试一次；authFailed → 清缓存自愈重试一次；均有限次；
4. 当日 ok 档在库 → 短路零 HTTP（重跑/补跑幂等）；空 content 不落 ok 档；
5. state 档（not_published/fetch_failed/rate_limited/auth_failed）落库供
   corpusState.morningState 披露；采集失败绝不阻塞打标。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_morning_collect as M
from backend.operations import jiuyan_theme_fetch as F
from backend.operations import jiuyan_theme_store as S
from backend.operations.jiuyan_theme_collect import THEME_COLLECT_RESULT_MARKER

TODAY = "2026-11-14"


def _news_payload(*, with_today=True, title="早报"):
    days = [{"date": "2026-11-17", "list": [
        {"article_id": "f1", "title": "2026年APEC领导人非正式会议", "content": "会议为期一周。"}]}]
    if with_today:
        days.insert(0, {"date": TODAY, "list": [
            {"article_id": "b1", "title": title,
             "content": "1、热点事件\n1）物理AI：英伟达GTC大会11月14日在柏林举行。\n2）固态电池：某厂发布量产时间表。\n旁注续行并入上一段。"}]})
    return {"errCode": 0, "data": days}


# ── 解析/识别层 ────────────────────────────────────────────────────────
def test_is_briefing_semantics():
    assert F.is_briefing({"title": "早报"}) is True
    assert F.is_briefing({"title": "盘前必读"}) is True
    assert F.is_briefing({"title": "某会议", "content": "1、热点事件\n1）xx"}) is True
    assert F.is_briefing({"title": "复盘"}) is False, "盘后产物对晨间窗是前视"
    assert F.is_briefing({"title": "收盘必读"}) is False
    assert F.is_briefing({"title": "英伟达GTC大会", "content": "黄仁勋演讲。"}) is False


def test_extract_briefing_today_only():
    days = F.parse_timeline_news_response(_news_payload())["days"]
    it = F.extract_briefing(days, TODAY)
    assert it is not None and it["articleId"] == "b1"
    assert F.extract_briefing(days, "2026-11-13") is None, "只认当日块，不回看"


def test_split_briefing_paragraphs():
    paras = F.split_briefing_paragraphs(
        "1、热点事件\n1）物理AI：GTC举行。\n旁注。\n2）固态电池：量产。\n3）算力：扩产。")
    assert len(paras) == 4, "「1、热点事件」标题行 + 3 个编号段"
    assert paras[0].startswith("1、热点事件")
    assert paras[1].startswith("1）物理AI") and "旁注" in paras[1], "续行归并"
    assert F.split_briefing_paragraphs("") == []
    assert F.split_briefing_paragraphs("无编号整段") == ["无编号整段"]


def test_parse_timeline_news_shapes_and_errcode():
    ok = F.parse_timeline_news_response(_news_payload())
    assert ok["ok"] is True and ok["days"][0]["date"] == TODAY
    wrapped = F.parse_timeline_news_response({"errCode": 0, "data": {"data": _news_payload()["data"]}})
    assert wrapped["ok"] is True and len(wrapped["days"]) == 2
    bad_shape = F.parse_timeline_news_response({"errCode": 0, "data": "str"})
    assert bad_shape["ok"] is False and bad_shape["days"] == []
    q = F.parse_timeline_news_response({"errCode": "9", "msg": "限流"})
    assert q["ok"] is False and q["rateLimited"] is True and q["authFailed"] is False
    a = F.parse_timeline_news_response({"errCode": 110, "msg": "token无效"})
    assert a["ok"] is False and a["authFailed"] is True


# ── 存储层 ────────────────────────────────────────────────────────────
def _fake_db():
    from tests.operations.test_jiuyan_theme_collect import FakeDb
    return FakeDb()


def test_store_morning_report_ok_and_no_overwrite():
    db = _fake_db()
    s3 = S.save_morning_report(db, fetch_date=TODAY, state="ok", content="", title="", paragraphs=[])
    assert s3["skipped"] is True and s3["reason"] == "empty_content", "空载荷不落 ok 档"
    assert S.get_morning_report(db, date=TODAY) is None
    s1 = S.save_morning_report(db, fetch_date=TODAY, state="ok", title="早报",
                               content="正文", paragraphs=["1）物理AI：GTC。"],
                               token_source="cache+minted")
    assert s1 == {"written": 1, "state": "ok"}
    doc = S.get_morning_report(db, date=TODAY)
    assert doc["state"] == "ok" and doc["paragraphs"] == ["1）物理AI：GTC。"]
    s2 = S.save_morning_report(db, fetch_date=TODAY, state="ok", title="早报",
                               content="新正文", paragraphs=["1）x"], token_source="x")
    assert s2["skipped"] is True, "ok 档不覆盖（幂等）"
    assert S.get_morning_report(db, date=TODAY)["content"] == "正文"


def test_store_morning_report_state_doc_and_first_seen():
    db = _fake_db()
    S.save_morning_report(db, fetch_date=TODAY, state="not_published", token_source="cache+minted")
    doc = S.get_morning_report(db, date=TODAY)
    assert doc["state"] == "not_published" and doc["firstSeenDate"] == TODAY
    S.save_morning_report(db, fetch_date=TODAY, state="ok", title="早报", content="正文",
                          paragraphs=["1）x"], token_source="cache+minted")
    doc2 = S.get_morning_report(db, date=TODAY)
    assert doc2["state"] == "ok" and doc2["firstSeenAt"] == doc["firstSeenAt"], "firstSeen 不覆盖"


# ── 采集编排 ──────────────────────────────────────────────────────────
class _FakeAuth:
    def __init__(self, ok=True, source="cache+minted", error=None):
        self.ok, self.source, self.error = ok, source, error

    def __call__(self, *a, **kw):
        if not self.ok:
            return {"ok": False, "error": self.error or "auth_missing", "authFailed": True,
                    "source": ""}
        return {"ok": True, "session": "s", "token": "t", "timestamp": "ts", "source": self.source}


@pytest.fixture()
def _no_sleep(monkeypatch):
    monkeypatch.setattr(M.time, "sleep", lambda *_: None)


def test_collect_once_ok_saves_paragraphs(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: dict(F.parse_timeline_news_response(_news_payload())))
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "ok"
    assert out["paragraphs"] == 3 and out["chars"] > 0, "「1、热点事件」+2 编号段（旁注归并）"
    doc = S.get_morning_report(db, date=TODAY)
    assert doc["state"] == "ok" and len(doc["paragraphs"]) == 3
    assert doc["quality"]["tokenSource"] == "cache+minted"


def test_collect_once_not_published_is_structured_ok(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: dict(F.parse_timeline_news_response(_news_payload(with_today=False))))
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "not_published", "非失败，等下一尝试槽"
    assert S.get_morning_report(db, date=TODAY)["state"] == "not_published"


def test_collect_once_short_circuit_already_ok_zero_http(monkeypatch, _no_sleep):
    db = _fake_db()
    S.save_morning_report(db, fetch_date=TODAY, state="ok", title="早报", content="正文",
                          paragraphs=["1）x"], token_source="x")

    def _boom(**kw):
        raise AssertionError("ok 档在库必须短路零 HTTP")
    monkeypatch.setattr(M.F, "fetch_timeline_news", _boom)
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out.get("skipped") and out["reason"] == "already_ok"


def test_collect_once_budget_exhausted(monkeypatch, _no_sleep):
    db = _fake_db()
    # 预写满额度计数
    from backend.operations import jiuyan_theme_store as S2
    for _ in range(12):
        S2.record_api_calls(db, TODAY, ("other",))
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("预算耗尽不得发 HTTP")))
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["skippedByBudget"] == [M.SOURCE_MORNING]


def test_collect_once_disabled_switch(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setenv("JIUYAN_MORNING_COLLECT_ENABLED", "0")
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("关断不得发 HTTP")))
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out.get("skipped") and out["reason"] == "disabled"


def test_collect_once_rate_limited_backoff_then_ok(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    calls = {"n": 0}

    def fake_fetch(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "rateLimited": True, "authFailed": False,
                    "error": "timeline/news: errCode=9 限流", "days": []}
        return dict(F.parse_timeline_news_response(_news_payload()))
    monkeypatch.setattr(M.F, "fetch_timeline_news", fake_fetch)
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "ok"
    assert calls["n"] == 2, "退避后重试一次即成功"
    assert S.calls_recorded(db, TODAY) == 2, "每次 HTTP 都计数（失败同样消耗服务端额度）"


def test_collect_once_auth_failed_self_heal_recovers(monkeypatch, _no_sleep):
    db = _fake_db()
    cleared = {"n": 0}
    from backend.operations import jiuyan_store as JS
    monkeypatch.setattr(JS, "clear_cached_token", lambda *a, **kw: cleared.__setitem__("n", cleared["n"] + 1))
    monkeypatch.setattr(JS, "clear_cached_session", lambda *a, **kw: cleared.__setitem__("n", cleared["n"] + 1))
    auth_states = {"n": 0}

    def fake_resolve(*, date=None, force_refresh=False):
        auth_states["n"] += 1
        return {"ok": True, "session": "s2", "token": "t2", "timestamp": "ts",
                "source": "login+minted"}
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", fake_resolve)
    calls = {"n": 0}

    def fake_fetch(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "rateLimited": False, "authFailed": True,
                    "error": "timeline/news: errCode=110", "days": []}
        assert kw["token"] == "t2", "自愈后必须用新凭据"
        return dict(F.parse_timeline_news_response(_news_payload()))
    monkeypatch.setattr(M.F, "fetch_timeline_news", fake_fetch)
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is True and out["state"] == "ok"
    assert cleared["n"] == 2 and calls["n"] == 2
    assert out.get("selfHeal", {}).get("ok") is True
    doc = S.get_morning_report(db, date=TODAY)
    assert doc["quality"]["selfHeal"]["ok"] is True, "自愈痕迹落档"


def test_collect_once_fetch_failed_persists_state(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: {"ok": False, "rateLimited": False, "authFailed": False,
                                      "error": "timeline/news: HTTP 500", "days": []})
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["state"] == "fetch_failed"
    assert out["degraded"] == [f"{M.SOURCE_MORNING}:fetch_failed"]
    assert S.get_morning_report(db, date=TODAY)["state"] == "fetch_failed"


def test_collect_once_auth_missing_persists_state(monkeypatch, _no_sleep):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth(ok=False, error="no_credentials"))
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False and out["state"] == "auth_failed"
    assert S.get_morning_report(db, date=TODAY)["state"] == "auth_failed"


def test_cli_main_marker_and_exit_codes(monkeypatch, _no_sleep, capsys):
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: dict(F.parse_timeline_news_response(_news_payload())))
    rc = M.main(["--date", TODAY])
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith(THEME_COLLECT_RESULT_MARKER)]
    assert len(lines) == 1, "stdout 机读接口=共享标记行单行 JSON"
    assert '"state": "ok"' in lines[0].replace(" ", "") or '"state":"ok"' in lines[0].replace(" ", "")

    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: dict(F.parse_timeline_news_response(_news_payload(with_today=False))))
    rc2 = M.main(["--date", TODAY])
    assert rc2 == 0, "not_published 非失败，exit 0（下一尝试槽承接）"


# ── 评审修复回归（2026-11-14 review）：dry-run 只读 / 重试前预算准入 ──

def test_collect_dry_run_is_read_only(monkeypatch, _no_sleep):
    """dry-run 完全只读：不写预算计数、不落 state/ok 档（评审修复 P2-3）。"""
    db = _fake_db()
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    monkeypatch.setattr(M.F, "fetch_timeline_news",
                        lambda **kw: dict(F.parse_timeline_news_response(_news_payload())))
    out = M.collect_once(db=db, fetch_date=TODAY, dry_run=True)
    assert out["ok"] is True and out["state"] == "ok" and out.get("paragraphs")
    assert S.calls_recorded(db, TODAY) == 0, "dry-run 不写生产预算计数"
    assert not db[S.COLLECTION_MORNING].docs, "dry-run 不落早报日档"


def test_collect_budget_admission_skips_retry_when_exhausted(monkeypatch, _no_sleep):
    """每次 HTTP 前预算准入：预算内首发后，重试前复查超额即不重试（总调用 ≤ 预算）。"""
    db = _fake_db()
    for _ in range(11):
        S.record_api_calls(db, TODAY, (M.SOURCE_MORNING,))   # 已用 11，预算 12
    monkeypatch.setattr(M.jiuyan_auth, "resolve_auth", _FakeAuth())
    calls = {"n": 0}

    def fake_fetch(**kw):
        calls["n"] += 1
        return {"ok": False, "rateLimited": True, "authFailed": False,
                "error": "timeline/news: errCode=9 限流", "days": []}
    monkeypatch.setattr(M.F, "fetch_timeline_news", fake_fetch)
    out = M.collect_once(db=db, fetch_date=TODAY)
    assert out["ok"] is False
    assert calls["n"] == 1, "预算耗尽后限流重试被准入拦截，不发第 2 次 HTTP"
    assert S.calls_recorded(db, TODAY) == 12, "总调用严格 ≤ 预算（首发计入后即封顶）"
    assert "budget_exhausted" in str((out.get("error") or {}).get("message"))
