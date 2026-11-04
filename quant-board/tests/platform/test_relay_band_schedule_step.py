# -*- coding: utf-8 -*-
"""分带表重算挂链测试（2026-10-19 用户裁决 A+A1：`_run_relay_band_step`）。

背景：分带表是 relay_page 常驻读数，长期靠人工手跑 → 序列前进、表停在旧日（滞后警告天天亮）。
A = 挂进 17:00 盘后链（advisory 步，零模型调用）；A1 = 全窗就地重建（审计靠产物 provenance）。

本测试全 monkeypatch（假 Mongo + 假 subprocess.run），零真实子进程、零网络、零模型调用
（AGENTS §1.2-7）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.jev import relay_band as bandmod

_OLD_TABLE = {"ok": True, "generatedAt": "2026-10-18T10:58:00",
              "window": {"start": "2026-05-06", "end": "2026-10-16", "judged": 108, "evaluated": 107},
              "days": [{"d": "2026-10-16", "idx": 47.7}]}
_NEW_TABLE = {"ok": True, "generatedAt": "2026-10-19T18:10:01",
              "window": {"start": "2026-05-06", "end": "2026-10-19", "judged": 109, "evaluated": 108},
              "days": [{"d": "2026-10-16", "idx": 47.7}, {"d": "2026-10-19", "idx": 40.7}]}


class FakeRelayCol:
    def __init__(self, dates: list[str]):
        self.dates = dates

    def find(self, _query, _projection=None):
        return [{"tradingDate": d} for d in self.dates]


class FakeDb:
    def __init__(self, dates: list[str]):
        self.dates = dates

    def __getitem__(self, name: str):
        if name == "hotlist_jev_relay_index":
            return FakeRelayCol(self.dates)
        raise KeyError(name)


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    """隔离产物/日志路径（env 覆盖，不动真实 data/backups）。"""
    target = tmp_path / "relay-band-table.json"
    log = tmp_path / "relay-band-refresh.log"
    monkeypatch.setenv(bandmod.RELAY_BAND_TABLE_ENV, str(target))
    monkeypatch.setenv(bandmod.RELAY_BAND_REFRESH_LOG_ENV, str(log))
    return target, log


def _use_db(monkeypatch: Any, dates: list[str]) -> None:
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(dates),
    )


def _fake_run(monkeypatch: Any, *, returncode: int = 0, payload: dict | None = _NEW_TABLE,
              exc: Exception | None = None) -> dict:
    """假 subprocess.run：把产物写到命令里的 --emit-json 目标（等价脚本行为）。"""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        if exc is not None:
            raise exc
        if payload is not None:
            tmp = Path(cmd[cmd.index("--emit-json") + 1])
            tmp.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(bandmod.subprocess, "run", fake_run)
    return captured


def test_relay_band_step_skips_when_up_to_date(monkeypatch: Any, paths: Any) -> None:
    """自愈门控：产物 window.end ≥ 最新 ok 判定日 → 跳过，不启动子进程（省 5–9 分钟）。"""
    from backend.operations import schedule

    target, _ = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    _use_db(monkeypatch, ["2026-10-16"])
    ran: list[str] = []
    monkeypatch.setattr(bandmod.subprocess, "run", lambda *a, **k: ran.append("spawn"))

    result = schedule._run_relay_band_step("2026-10-16")

    assert result["ok"] is True and result["skipped"] is True
    assert result["reason"].startswith("up_to_date")
    assert result["artifactEnd"] == "2026-10-16" and result["latestJudged"] == "2026-10-16"
    assert ran == []


def test_relay_band_step_skips_without_ok_judgment(monkeypatch: Any, paths: Any) -> None:
    """无任何 ok 判定日（如判定链未跑）→ 跳过并给结构化原因。"""
    from backend.operations import schedule

    _use_db(monkeypatch, [])
    ran: list[str] = []
    monkeypatch.setattr(bandmod.subprocess, "run", lambda *a, **k: ran.append("spawn"))

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is True and result["skipped"] is True
    assert result["reason"] == "no ok relay judgment"
    assert ran == []


def test_relay_band_step_stale_runs_and_atomically_swaps(monkeypatch: Any, paths: Any) -> None:
    """滞后（10-16 < 10-19）→ 跑诊断脚本、产物写临时文件后原子替换，旧表全程完整可读。"""
    from backend.operations import schedule

    target, log = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    _use_db(monkeypatch, ["2026-10-15", "2026-10-19"])
    captured = _fake_run(monkeypatch)

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is True, result
    assert result["reason"] == "stale (2026-10-16 < 2026-10-19)"
    assert result["returncode"] == 0 and result["latestJudged"] == "2026-10-19"
    assert result["artifactEndBefore"] == "2026-10-16" and result["windowEnd"] == "2026-10-19"
    cmd = captured["cmd"]
    assert Path(cmd[1]).name == "jev_relay_band_diagnostic.py"
    assert cmd[2] == "--emit-json"
    assert Path(cmd[3]).name.startswith(target.name), "先写临时文件，成功后替换"
    assert str(captured["kwargs"]["cwd"]).endswith("quant-board")
    # 产物已替换为新表，且不留临时文件
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-19"
    assert not list(target.parent.glob("*.tmp*"))
    assert result["logPath"] == str(log)


def test_relay_band_step_runs_when_artifact_missing(monkeypatch: Any, paths: Any) -> None:
    """产物缺失/损坏 → 同样重算（自愈），原因结构化标注。"""
    from backend.operations import schedule

    target, _ = paths
    _use_db(monkeypatch, ["2026-10-19"])
    _fake_run(monkeypatch)

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is True and result["reason"] == "artifact_missing_or_unreadable"
    assert result["artifactEndBefore"] is None
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-19"


def test_relay_band_step_failure_keeps_old_table(monkeypatch: Any, paths: Any) -> None:
    """脚本非 0 退出：旧表保持完整、半成品撤掉、结构化上报，且不抛异常（advisory）。"""
    from backend.operations import schedule

    target, _ = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    _use_db(monkeypatch, ["2026-10-19"])
    _fake_run(monkeypatch, returncode=3, payload="{partial")

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is False and result["error"] == "script_exit_3"
    assert result["latestJudged"] == "2026-10-19" and result["returncode"] == 3
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-16", \
        "失败不得破坏旧表"
    assert not list(target.parent.glob("*.tmp*")), "半成品须撤掉（不落 0/空表冒充）"


def test_relay_band_step_timeout_is_structured(monkeypatch: Any, paths: Any) -> None:
    """子进程超时 → 结构化 error（含时限），不抛异常、不破坏旧表。"""
    import subprocess as _subprocess

    from backend.operations import schedule

    target, _ = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    _use_db(monkeypatch, ["2026-10-19"])
    _fake_run(monkeypatch, exc=_subprocess.TimeoutExpired("cmd", 1))

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is False and "band_refresh_timeout" in result["error"]
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-16"


def test_relay_band_step_gate_error_skips(monkeypatch: Any, paths: Any) -> None:
    """门控查询失败 → skipped（与 11 个兄弟 advisory 步一致）。

    2026-10-19 评审 F1：旧实现 fail-open（“宁多跑一次也不漏刷新”）会让这两条既有
    `dry_run=False` 链测试（db stub 为字符串）真的起子进程，实测截断了真实
    `data/backups/relay-band-refresh.log`；且此时子进程读 Mongo 同样会失败，fail-open 收益≈零。
    """
    from backend.operations import schedule

    target, _ = paths

    def _boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database", _boom)
    ran: list[str] = []
    monkeypatch.setattr(bandmod.subprocess, "run", lambda *a, **k: ran.append("spawn"))

    result = schedule._run_relay_band_step("2026-10-19")

    assert result["ok"] is True and result["skipped"] is True
    assert result["reason"].startswith("gate error")
    assert result["date"] == "2026-10-19"
    assert ran == [], "门控失败不得起子进程（防测试污染 / 生产白跑）"
    assert not target.exists(), "不得写任何产物"


def test_relay_band_step_gate_query_matches_script_window(monkeypatch: Any, paths: Any) -> None:
    """门控口径与脚本取数一致：status=ok **且 relayIndex 非空**（评审 uncertain 2）。"""
    from backend.operations import schedule

    seen: dict = {}

    class Col:
        def find(self, query, _projection=None):
            seen["query"] = query
            return []

    class Db:
        def __getitem__(self, name):
            assert name == "hotlist_jev_relay_index"
            return Col()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database", lambda: Db())
    ran: list[str] = []
    monkeypatch.setattr(bandmod.subprocess, "run", lambda *a, **k: ran.append("spawn"))

    result = schedule._run_relay_band_step("2026-10-19")

    assert seen["query"] == {"status": "ok", "relayIndex": {"$ne": None}}
    assert result["skipped"] is True and ran == []


def test_relay_band_step_dry_run_short_circuits(monkeypatch: Any, paths: Any) -> None:
    """dry_run 短路（链上 dry 跑不触发重算）。"""
    from backend.operations import schedule

    _use_db(monkeypatch, ["2026-10-19"])
    ran: list[str] = []
    monkeypatch.setattr(bandmod.subprocess, "run", lambda *a, **k: ran.append("spawn"))

    result = schedule._run_relay_band_step("2026-10-19", dry_run=True)

    assert result == {"ok": True, "skipped": True, "reason": "dry_run", "date": "2026-10-19"}
    assert ran == []


def test_relay_band_step_is_advisory_in_chain() -> None:
    """链侧守卫：relayBand 不在 stopped_at 候选中（失败不翻转整体 ok）。"""
    import inspect

    from backend.operations import schedule

    src = inspect.getsource(schedule.run_after_market_once)
    assert '"relayBand": relay_band_result' in src, "结果须落 results.relayBand（fail-visible）"
    assert 'stopped_at = "relayBand"' not in src, "advisory 步不得参与 stopped_at"
    for blocking in ("hotlistSentiment", "mongodbBackup", "snapshotArchiveR2"):
        assert f'stopped_at = "{blocking}"' in src, "生产链停点不应被本次改动影响"

# ── 2026-10-19 评审修复的回归守卫（F3 替换失败清理 / F5 冒烟产物隔离）────────────
def test_run_sync_replace_failure_discards_tmp(monkeypatch: Any, paths: Any) -> None:
    """F3：os.replace 抛异常 → 结构化上报 + 撤掉半成品 + 旧表不动（四分支唯一漏清理的）。"""
    target, _ = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    _fake_run(monkeypatch)
    monkeypatch.setattr(bandmod, "replace_artifact",
                        lambda tmp, tgt: {"ok": False, "error": "artifact_replace_failed: sharing"})

    result = bandmod.run_band_refresh_sync()

    assert result["ok"] is False and "artifact_replace_failed" in result["error"]
    assert not list(target.parent.glob("*.tmp*")), "替换失败也必须撤掉半成品"
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-16"


def test_run_sync_days_uses_separate_smoke_artifact(monkeypatch: Any, paths: Any) -> None:
    """F5：--days N 只截断窗口但 window.end 仍是全量末日 → 必须另存，绝不覆盖正式读数。"""
    target, _ = paths
    target.write_text(json.dumps(_OLD_TABLE), encoding="utf-8")
    captured = _fake_run(monkeypatch)

    result = bandmod.run_band_refresh_sync(days=3)

    assert result["ok"] is True
    smoke = target.with_name(f"{target.stem}-days3{target.suffix}")
    assert captured["cmd"][captured["cmd"].index("--days") + 1] == "3"
    assert Path(result["artifactPath"]) == smoke and smoke.exists()
    # 正式产物必须原封不动（页面读数不受冒烟影响）
    assert json.loads(target.read_text(encoding="utf-8"))["window"]["end"] == "2026-10-16"
    assert not list(target.parent.glob("*.tmp*"))


def test_run_sync_log_open_failure_is_structured(monkeypatch: Any, paths: Any, tmp_path: Any) -> None:
    """F2：日志 open 失败不得抛穿（advisory 步在盘后链上是裸调用，抛出会中断整条链）。"""
    _, log = paths
    monkeypatch.setattr(bandmod, "relay_band_refresh_log_path",
                        lambda: tmp_path / "no-such-dir" / "log.txt")

    def _boom(*_a, **_k):
        raise PermissionError("locked")

    monkeypatch.setattr(bandmod, "open", _boom, raising=False)
    result = bandmod.run_band_refresh_sync()

    assert result["ok"] is False and "log_open_failed" in result["error"]
