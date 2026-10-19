# -*- coding: utf-8 -*-
"""分带实测读数读口测试（GET /api/hotlist-jev/relay-band，2026-10-18 relay_page 可视化消费）。

读口语义：**不加工不重算**——把离线诊断（`scripts/jev_relay_band_diagnostic.py --emit-json`）
的产物原样交给前端；文件缺失/损坏/空 → ok=False + reason + hint（fail-visible：
前端显式标「分带表未生成」，不静默空表，也不拿前端序列直算冒充实测）。
全 monkeypatch（env 指向 tmp_path），零网络零真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.api.hotlist_jev_routes import RELAY_BAND_TABLE_ENV
from backend.main import app

client = TestClient(app)

_SAMPLE = {
    "ok": True,
    "generatedAt": "2026-10-18T10:58:00",
    "window": {"start": "2026-05-06", "end": "2026-10-16", "judged": 108, "evaluated": 107},
    "relayGeneration": ["v5"],
    "bars": {"okCodes": 2985, "codes": 2985, "localRoot": "D:/APP_SOFT/TDX"},
    "bands": [{"key": [40, 60], "name": "40-60", "n": 38, "promo": 21.2, "hiPromo": 37.9,
               "premA": 0.6, "premB": 0.7, "bigface": 13.7, "negA": 13}],
    "zones": [{"zone": "回避 40-60∧温≥56", "n": 11, "mean": -0.45}],
    "days": [{"d": "2026-05-06", "idx": 47.7, "temp": 55.9, "phase": "divergence",
              "money": "losing", "premA": 3.2, "bigface": 2.0, "cov": 145, "n_pool": 145}],
}


def _write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")
    return path


def test_relay_band_reads_artifact(tmp_path, monkeypatch):
    """产物存在 → 原样透传 + 附 artifactPath/artifactMtime（不加工不重算）。"""
    path = _write(tmp_path, "relay-band-table.json", _SAMPLE)
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(path))
    body = client.get("/api/hotlist-jev/relay-band").json()
    assert body["ok"] is True
    assert body["window"]["end"] == "2026-10-16"
    assert body["bands"][0]["name"] == "40-60"
    assert body["days"][0]["d"] == "2026-05-06"
    assert body["artifactPath"] == str(path)
    assert body["artifactMtime"] > 0


def test_relay_band_missing_is_fail_visible(tmp_path, monkeypatch):
    """产物缺失 → ok=False + reason + hint（前端标「未生成」，不静默空表）。"""
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(tmp_path / "nope.json"))
    body = client.get("/api/hotlist-jev/relay-band").json()
    assert body["ok"] is False and body["degraded"] is True
    assert body["reason"] == "band_table_missing"
    assert "jev_relay_band_diagnostic" in body["hint"]


def test_relay_band_unreadable_and_empty(tmp_path, monkeypatch):
    """损坏 JSON / 空 days 都按 fail-visible 返回结构化原因。"""
    bad = _write(tmp_path, "bad.json", "{not json")
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(bad))
    assert client.get("/api/hotlist-jev/relay-band").json()["reason"].startswith(
        "band_table_unreadable")

    empty = _write(tmp_path, "empty.json", {"ok": True, "days": []})
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(empty))
    assert client.get("/api/hotlist-jev/relay-band").json()["reason"] == "band_table_empty"


def test_relay_band_default_path_under_repo(tmp_path, monkeypatch):
    """默认路径 = quant-board/data/backups/relay-band-table.json（相对仓根解析）。"""
    monkeypatch.delenv(RELAY_BAND_TABLE_ENV, raising=False)
    body = client.get("/api/hotlist-jev/relay-band").json()
    expected = Path(__file__).resolve().parents[2] / "data" / "backups" / "relay-band-table.json"
    assert Path(body["artifactPath"]) == expected


def test_relay_band_rejects_non_list_days(tmp_path, monkeypatch):
    """days 非列表/空列表的损坏产物 → ok:false + reason（review P2-4），不得放行成 ok:true。"""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api import hotlist_jev_routes as routes

    bad = tmp_path / "relay-band-table.json"
    bad.write_text(json.dumps({"days": "x", "window": {}}), encoding="utf-8")
    monkeypatch.setattr(routes, "_relay_band_table_path", lambda: bad)
    r = TestClient(app).get("/api/hotlist-jev/relay-band")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["reason"] == "band_table_empty"
    assert body.get("hint") and body.get("artifactPath")


# ── 分带表刷新任务（POST/GET /api/hotlist-jev/relay-band/refresh，2026-10-19）──────
# 页面【分带观察】滞后/缺失时一键重算（零模型调用：只读 Mongo + 本地通达信日线）。
# 全 monkeypatch（假 Popen + 隔离产物/日志路径）：零真实子进程、零网络、零模型调用（§1.2-7）。
from backend.api import hotlist_jev_routes as routes  # noqa: E402

_ROUTE_REFRESH = "/api/hotlist-jev/relay-band/refresh"

_JOB_DEFAULTS = {"proc": None, "startedAt": None, "finishedAt": None, "returncode": None,
                 "error": None, "days": 0, "logPath": None, "tmpPath": None, "targetPath": None}


class _FakeProc:
    """最小 Popen 替身：poll() 由测试置 returncode 驱动（不真起子进程）。"""

    def __init__(self, args, **kwargs):
        self.args = list(args)
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture()
def band_job(tmp_path, monkeypatch):
    """隔离刷新任务全局状态 + 产物/日志路径；返回 (spawned, target, log)。"""
    target = tmp_path / "relay-band-table.json"
    log = tmp_path / "relay-band-refresh.log"
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(target))
    monkeypatch.setenv(routes.RELAY_BAND_REFRESH_LOG_ENV, str(log))
    spawned: list = []

    def _popen(args, **kw):
        proc = _FakeProc(args, **kw)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(routes.subprocess, "Popen", _popen)
    with routes._BAND_REFRESH_LOCK:
        routes._BAND_REFRESH.update(dict(_JOB_DEFAULTS))
    yield spawned, target, log
    with routes._BAND_REFRESH_LOCK:
        routes._BAND_REFRESH.update(dict(_JOB_DEFAULTS))


def _tmp_of(proc) -> Path:
    return Path(proc.args[proc.args.index("--emit-json") + 1])


def test_band_refresh_start_and_poll_swap(band_job):
    """起任务 → 运行中 running；成功退出 → tmp 原子替换（旧表全程可读，不落半成品）。"""
    spawned, target, log = band_job
    body = client.post(_ROUTE_REFRESH, json={}).json()
    assert body["ok"] is True and body["running"] is True and body["pid"] == 4242
    assert body["artifactPath"] == str(target)
    assert len(spawned) == 1
    args = spawned[0].args
    assert args[0] == sys.executable and args[1].endswith("jev_relay_band_diagnostic.py")
    assert args[-2] == "--emit-json"
    assert spawned[0].kwargs["cwd"].endswith("quant-board")
    tmp = _tmp_of(spawned[0])
    assert tmp != target and tmp.name.startswith(target.name), "须先写临时文件再原子替换"

    st = client.get(_ROUTE_REFRESH).json()
    assert st["running"] is True and st["ok"] is False

    tmp.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    spawned[0].returncode = 0
    st = client.get(_ROUTE_REFRESH).json()
    assert st["running"] is False and st["ok"] is True and st["returncode"] == 0
    assert st["error"] is None and not tmp.exists() and target.exists()
    rb = client.get("/api/hotlist-jev/relay-band").json()   # 读口立刻见新表
    assert rb["ok"] is True and rb["days"][0]["d"] == "2026-05-06"


def test_band_refresh_rejects_concurrent(band_job):
    """并发护栏：任务在跑时再 POST 不重复起（防 CPU/IO 打爆）。"""
    spawned, target, log = band_job
    assert client.post(_ROUTE_REFRESH, json={}).json()["ok"] is True
    again = client.post(_ROUTE_REFRESH, json={}).json()
    assert again["ok"] is False and again["reason"] == "already_running"
    assert len(spawned) == 1


def test_band_refresh_failure_keeps_old_table(band_job):
    """脚本非 0 退出：撤半成品、旧表保持完整、错误结构化透出（fail-visible）。"""
    spawned, target, log = band_job
    target.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    client.post(_ROUTE_REFRESH, json={})
    tmp = _tmp_of(spawned[0])
    tmp.write_text("{partial", encoding="utf-8")
    spawned[0].returncode = 3
    st = client.get(_ROUTE_REFRESH).json()
    assert st["running"] is False and st["ok"] is False and st["error"] == "script_exit_3"
    assert not tmp.exists(), "失败须撤掉半成品（不得落 0/空表冒充）"
    assert json.loads(target.read_text(encoding="utf-8"))["days"], "旧表须保持完整"


def test_band_refresh_success_without_artifact_is_error(band_job):
    """退出码 0 但没写出产物 → artifact_missing（不谎报 ok，也不清掉旧表）。"""
    spawned, target, log = band_job
    client.post(_ROUTE_REFRESH, json={})
    spawned[0].returncode = 0
    st = client.get(_ROUTE_REFRESH).json()
    assert st["ok"] is False and st["error"] == "artifact_missing"


def test_band_refresh_days_arg_and_bad_days(band_job):
    """--days N 透传（冒烟）；负数拒绝。"""
    spawned, target, log = band_job
    body = client.post(_ROUTE_REFRESH, json={"days": 5}).json()
    assert body["ok"] is True and body["days"] == 5
    assert spawned[0].args[-2:] == ["--days", "5"]
    spawned[0].returncode = 0
    client.get(_ROUTE_REFRESH)
    assert client.post(_ROUTE_REFRESH, json={"days": -1}).json()["reason"] == "bad_days"


def test_band_refresh_idle_status_and_poll_get(band_job):
    """未跑过 → 空闲态；GET /refresh 本就是**轮询读口**（返回任务状态，非 405）。"""
    spawned, target, log = band_job
    st = client.get(_ROUTE_REFRESH).json()
    assert st["running"] is False and st["ok"] is False and st["startedAt"] is None
    assert st["logPath"] and st["artifactPath"], "空闲态也要给出日志/产物路径（fail-visible 可定位）"
    assert client.get("/api/hotlist-jev/relay-band").status_code == 200


def test_band_refresh_smoke_days_never_touchs_production_artifact(band_job, monkeypatch):
    """F5（2026-10-19 评审）：days>0 冒烟跑的产物另存，绝不覆盖页面常驻读数。

    背景：`--days N` 只截断窗口，但产物 `window.end` 仍是全量最后一个判定日——
    若落正式路径，页面显示「只有 N 天」而盘后链门控认为已覆盖最新日、永久跳过全窗重建。
    """
    spawned, target, log = band_job
    target.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    body = client.post(_ROUTE_REFRESH, json={"days": 3}).json()

    smoke = target.with_name(f"{target.stem}-days3{target.suffix}")
    assert body["ok"] is True and body["days"] == 3
    tmp = _tmp_of(spawned[0])
    assert tmp.name.startswith(smoke.name) and tmp != smoke
    tmp.write_text(json.dumps({**_SAMPLE, "window": {**_SAMPLE["window"], "judged": 3}}),
                   encoding="utf-8")
    spawned[0].returncode = 0
    st = client.get(_ROUTE_REFRESH).json()
    assert st["ok"] is True and Path(st["artifactPath"]) == smoke
    assert smoke.exists() and target.read_text(encoding="utf-8") == before, \
        "正式产物必须原封不动（冒烟不得污染页面读数）"


def test_band_refresh_poll_replace_failure_discards_tmp(band_job, monkeypatch):
    """F3：轮询收尾时 os.replace 失败 → error 上报 + 撤半成品 + 旧表不动。"""
    spawned, target, log = band_job
    target.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    client.post(_ROUTE_REFRESH, json={})
    tmp = _tmp_of(spawned[0])
    tmp.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    monkeypatch.setattr(routes, "replace_artifact",
                        lambda a, b: {"ok": False, "error": "artifact_replace_failed: sharing"})
    spawned[0].returncode = 0

    st = client.get(_ROUTE_REFRESH).json()

    assert st["running"] is False and st["ok"] is False
    assert "artifact_replace_failed" in st["error"]
    assert not tmp.exists(), "替换失败也必须撤掉半成品"
    assert json.loads(target.read_text(encoding="utf-8"))["days"], "旧表须保持完整"


def test_band_refresh_poll_kills_stuck_job(band_job, monkeypatch):
    """U1（2026-10-19 评审）：后台任务挂死 → 超过预算即 kill + 结构化收尾（页面不再无限轮询）。"""
    spawned, target, log = band_job
    client.post(_ROUTE_REFRESH, json={})
    tmp = _tmp_of(spawned[0])
    tmp.write_text("{partial", encoding="utf-8")   # 半成品，超时收尾也必须撤掉
    monkeypatch.setattr(routes, "_BAND_REFRESH_MAX_RUNTIME_SECONDS", 0)  # 立即触发超时

    st = client.get(_ROUTE_REFRESH).json()

    assert st["running"] is False and st["ok"] is False
    assert "band_refresh_timeout" in st["error"]
    assert not tmp.exists(), "超时收尾同样要撤半成品"
    assert json.loads(target.read_text(encoding="utf-8"))["days"] if target.exists() else True
    # 状态机收尾：任务槽已清空；后续轮询是「已完成任务的终态视图」（保留 startedAt/finishedAt 供审计）
    st2 = client.get(_ROUTE_REFRESH).json()
    assert st2["running"] is False and st2["startedAt"] and st2["finishedAt"]
    assert st2["ok"] is False and "band_refresh_timeout" in st2["error"]
