"""jiuyan_mark_sync 测试：全程 mock，禁真连 MongoDB / 韭研官网（AGENTS.md 红线7）。"""
from __future__ import annotations

import os

import pytest

from backend.operations import jiuyan_mark_sync as S


# ---- FakeDB：仅实现本模块用到的 find_one 两种形态 ----
class FakeCollection:
    def __init__(self, docs):
        self.docs = docs  # {_id: doc}

    def find_one(self, filt, projection=None, sort=None):
        if "_id" in filt:
            return self.docs.get(filt["_id"])
        if filt.get("updateKind") == "final":
            finals = [d for d in self.docs.values()
                      if d.get("updateKind") == "final" and d.get("tradingDate")]
            return max(finals, key=lambda d: d["tradingDate"]) if finals else None
        return None


class FakeDB:
    def __init__(self, docs):
        self._docs = docs  # {_id: doc}

    def __getitem__(self, name):
        return FakeCollection(self._docs)


def _sample_mark_text():
    # 5 段齐全；含一个已有非韭研标记 + 一个多板块不会冲突的简单结构
    return (
        "[MARK]\r\n01601318=7\r\n00000504=7\r\n"
        "[TIP]\r\n01601318=旧来源\r\n00000504=医药医疗\r\n"
        "[TIPWORD]\r\n01601318=旧来源\r\n00000504=医药医疗\r\n"
        "[TIPCOLOR]\r\n01601318=65535\r\n00000504=12615680\r\n"
        "[TIME]\r\n01601318=\r\n00000504=20260930\r\n"
    )


# 1) 往返字节一致
def test_roundtrip_byte_identical():
    text = _sample_mark_text()
    sec, order = S.parse_mark(text)
    assert S.serialize_mark(sec, order) == text


# 1b) 含非 code=value 行也要保留
def test_roundtrip_preserves_raw_lines():
    text = "[MARK]\r\n000001=7\r\n[NOTE]\r\nhello\r\n"
    sec, order = S.parse_mark(text)
    out = S.serialize_mark(sec, order)
    assert "hello\r\n" in out and "[NOTE]\r\n" in out


# 2) 代码规范化
@pytest.mark.parametrize("inp,exp", [
    ("sz000504", "00000504"), ("sh601318", "01601318"), ("bj830799", "02830799"),
    ("601188", "01601188"), ("000858", "00000858"), ("300399", "00300399"),
    ("1601188", "01601188"), ("01603115", "01603115"), ("920819", "02920819"),
    ("abc", None), ("", None), (None, None), ("12", None),
])
def test_normalize_code(inp, exp):
    assert S.normalize_code(inp) == exp


# 3) 板块文档 → 映射（一股多板块用 / 连接）
def test_boards_from_doc_multi_board_and_warn():
    doc = {"fields": [
        {"name": "白酒", "stocks": [{"code": "sz000858"}, {"code": "sh600519"}]},
        {"name": "大金融", "stocks": [{"code": "sh600519"}, {"code": "bad"}]},
        {"name": "", "stocks": [{"code": "sz000001"}]},  # 无名称 → 跳过
    ]}
    warnings = []
    m = S.boards_from_doc(doc, warnings)
    assert m["00000858"] == ["白酒"]
    assert m["01600519"] == ["白酒", "大金融"]  # 多板块保序
    assert "00000001" not in m  # 无名称板块被跳过
    assert any("代码无法识别" in w for w in warnings)
    assert any("无名称板块" in w for w in warnings)


# 4) merge：只动韭研股，保留其它
def test_apply_merge_keeps_others():
    sec = {s: {} for s in S.SECTION_ORDER}
    sec["MARK"] = {"01601318": "7", "00999999": "7"}
    sec["TIP"] = {"01601318": "旧来源", "00999999": "别人的板块"}
    mapping = {"01601318": ["保险"], "00000858": ["白酒"]}
    stats = S.apply_merge(sec, mapping, "7", "65535", "20261015")
    assert sec["TIP"]["01601318"] == "保险"          # 覆盖
    assert sec["TIP"]["00999999"] == "别人的板块"     # 其它保留
    assert sec["TIP"]["00000858"] == "白酒"          # 新增
    assert sec["MARK"]["00000858"] == "7"
    assert sec["TIME"]["00000858"] == "20261015"
    assert stats["new_mark"] == 1 and stats["stocks"] == 2


# 5) fail-visible：final 缺失 → 不写
def test_sync_missing_final_no_write(tmp_path):
    p = tmp_path / "mark.dat"
    p.write_bytes(_sample_mark_text().encode("gbk"))
    before = p.read_bytes()
    db = FakeDB({})  # 无任何 final
    r = S.sync(db, date=None, mark_path=str(p), mark_color="7",
               tip_color="65535", apply=True, backup=True)
    assert r["ok"] is False and not r.get("written")
    assert p.read_bytes() == before  # 未改动


# 5b) fail-visible：final 存在但无成分 → 不写（不清除既有标记）
def test_sync_empty_fields_no_write(tmp_path):
    p = tmp_path / "mark.dat"
    p.write_bytes(_sample_mark_text().encode("gbk"))
    before = p.read_bytes()
    db = FakeDB({"2026-10-15:final": {"fields": [], "tradingDate": "2026-10-15",
                                       "updateKind": "final"}})
    r = S.sync(db, date="2026-10-15", mark_path=str(p), mark_color="7",
               tip_color="65535", apply=True, backup=True)
    assert r["ok"] is False and p.read_bytes() == before


# 6) dry-run：不写盘
def test_sync_dry_run_no_write(tmp_path):
    p = tmp_path / "mark.dat"
    p.write_bytes(_sample_mark_text().encode("gbk"))
    before = p.read_bytes()
    db = FakeDB({"2026-10-15:final": _final_doc()})
    r = S.sync(db, date="2026-10-15", mark_path=str(p), mark_color="7",
               tip_color="65535", apply=False, backup=True)
    assert r["ok"] and r["written"] is False
    assert p.read_bytes() == before
    assert r["stats"]["stocks"] == 2


# 7) apply：落盘 + 备份 + 结果可再解析且保留非韭研股
def test_sync_apply_writes_and_backs_up(tmp_path):
    p = tmp_path / "mark.dat"
    p.write_bytes(_sample_mark_text().encode("gbk"))
    db = FakeDB({"2026-10-15:final": _final_doc()})
    r = S.sync(db, date="2026-10-15", mark_path=str(p), mark_color="7",
               tip_color="65535", apply=True, backup=True)
    assert r["ok"] and r["written"] and r["backup"]
    assert os.path.isfile(r["backup"])
    # 备份=原内容
    assert open(r["backup"], "rb").read() == _sample_mark_text().encode("gbk")
    # 落盘后可解析，韭研股上标，非韭研股(00999999)仍在
    sec, order = S.parse_mark(S.read_mark(str(p)))
    assert sec["TIP"]["00000858"] == "白酒"
    assert sec["TIP"]["01600519"] == "白酒/大金融"
    assert sec["MARK"]["00000858"] == "7"
    assert sec["TIPCOLOR"]["00000858"] == "65535"
    assert sec["TIME"]["00000858"] == "20261015"
    assert "01601318" in sec["MARK"]          # 非韭研保留
    assert sec["TIP"]["01601318"] == "旧来源"  # 非韭研 TIP 不动


def _final_doc():
    return {"_id": "2026-10-15:final", "kind": "jiuyan_action",
            "tradingDate": "2026-10-15", "updateKind": "final",
            "fields": [
                {"name": "白酒", "count": 2,
                 "stocks": [{"code": "sz000858"}, {"code": "sh600519"}]},
                {"name": "大金融", "count": 1, "stocks": [{"code": "sh600519"}]},
            ]}


# ---- after-collect 钩子 ----
from backend.core.settings import get_settings  # noqa: E402


def _cfg(monkeypatch, *, enabled=True, path="/x/mark.dat"):
    s = get_settings()
    monkeypatch.setattr(s, "jiuyan_mark_sync_enabled", enabled)
    monkeypatch.setattr(s, "jiuyan_mark_path", path)
    monkeypatch.setattr(s, "jiuyan_mark_mark_color", "7")
    monkeypatch.setattr(s, "jiuyan_mark_tip_color", "65535")


def test_maybe_sync_skips_midday():
    assert S.maybe_sync_after_collect(object(), "2026-10-15", "midday") == {"skipped": "not_final"}


def test_maybe_sync_skips_in_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")  # pytest 中恒设
    _cfg(monkeypatch, enabled=True)
    monkeypatch.setattr(S.os.path, "isfile", lambda p: True)
    called = []
    monkeypatch.setattr(S, "sync", lambda *a, **k: called.append(k) or {"ok": True})
    r = S.maybe_sync_after_collect(object(), "2026-10-15", "final")
    assert r == {"skipped": "pytest"} and called == []  # 禁真写


def test_maybe_sync_disabled(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    _cfg(monkeypatch, enabled=False)
    assert S.maybe_sync_after_collect(object(), "2026-10-15", "final") == {"skipped": "disabled"}


def test_maybe_sync_mark_missing(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    _cfg(monkeypatch, enabled=True, path="/no/such/mark.dat")
    monkeypatch.setattr(S.os.path, "isfile", lambda p: False)
    r = S.maybe_sync_after_collect(object(), "2026-10-15", "final")
    assert r["skipped"] == "mark_missing"


def test_maybe_sync_runs_on_final(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    _cfg(monkeypatch, enabled=True, path="/x/mark.dat")
    monkeypatch.setattr(S.os.path, "isfile", lambda p: True)
    seen = {}

    def spy(db, *, date, mark_path, mark_color, tip_color, apply, backup):
        seen.update(date=date, mark_path=mark_path, mark_color=mark_color,
                    tip_color=tip_color, apply=apply, backup=backup)
        return {"ok": True, "date": date, "stats": {"stocks": 3},
                "bytes": 1, "sections_after": {"MARK": 1}, "backup": "/x.bak"}

    monkeypatch.setattr(S, "sync", spy)
    r = S.maybe_sync_after_collect(object(), "2026-10-15", "final")
    assert r["ok"] is True
    assert seen["apply"] is True and seen["backup"] is True
    assert seen["date"] == "2026-10-15"
    assert seen["mark_color"] == "7" and seen["tip_color"] == "65535"
