from __future__ import annotations

from pathlib import Path
from typing import Any


def test_build_service_specs_uses_isolated_collector_port(tmp_path: Path) -> None:
    from backend.snapshot_collector.supervisor import build_service_specs

    project_root = tmp_path / "dragon-board"
    quant_root = project_root / "quant-board"
    specs = build_service_specs(
        quant_root=quant_root,
        python_executable=Path("C:/Python/python.exe"),
        node_executable=Path("C:/Node/node.exe"),
        bridge_python=Path("C:/Python313/python.exe"),
    )

    by_name = {spec.name: spec for spec in specs}
    assert set(by_name) == {"mongo", "proxy", "bridge", "collector"}
    assert by_name["proxy"].working_directory == project_root / "proxy-server"
    assert by_name["bridge"].working_directory == project_root
    assert by_name["collector"].working_directory == quant_root
    assert by_name["proxy"].health_url == "http://127.0.0.1:3000/health"
    assert by_name["bridge"].health_url == "http://127.0.0.1:8765/health"
    assert by_name["collector"].port == 8001
    assert by_name["collector"].command[-2:] == ("--port", "8001")


def test_collector_payload_requires_running_shadow_scheduler() -> None:
    from backend.snapshot_collector.supervisor import collector_payload_is_healthy

    healthy: dict[str, Any] = {
        "ok": True,
        "data": {
            "enabled": True,
            "running": True,
            "dataset_id": "dragonboard_backend_shadow",
        },
    }
    assert collector_payload_is_healthy(healthy) is True

    for field, value in (
        ("enabled", False),
        ("running", False),
        ("dataset_id", "dragonboard_live"),
    ):
        payload = {"ok": True, "data": dict(healthy["data"])}
        payload["data"][field] = value
        assert collector_payload_is_healthy(payload) is False


def test_dependency_payload_requires_expected_service_identity() -> None:
    from backend.snapshot_collector.supervisor import dependency_payload_is_healthy

    assert dependency_payload_is_healthy(
        "proxy", {"ok": True, "service": "stock-proxy-server"}
    )
    assert dependency_payload_is_healthy(
        "bridge", {"ok": True, "service": "tdx-quote-bridge"}
    )
    assert not dependency_payload_is_healthy(
        "proxy", {"ok": True, "service": "unrelated-service"}
    )


def test_ensure_once_reuses_proxy_without_starting_isolated_proxy(tmp_path: Path) -> None:
    from backend.snapshot_collector.supervisor import (
        ServiceSpec,
        SnapshotCollectorSupervisor,
    )

    specs = (
        ServiceSpec("mongo", 27017, tmp_path, ("mongod",)),
        ServiceSpec("proxy", 3000, tmp_path, ("node", "server.js")),
        ServiceSpec("bridge", 8765, tmp_path, ("python", "bridge.py")),
        ServiceSpec(
            "collector",
            8001,
            tmp_path,
            ("python", "-m", "uvicorn"),
            health_url="http://127.0.0.1:8001/api/snapshot-collector/scheduler/status",
        ),
    )
    launched: list[str] = []

    supervisor = SnapshotCollectorSupervisor(
        specs=specs,
        log_dir=tmp_path / "logs",
        port_probe=lambda port: port in {27017, 8765},
        dependency_probe=lambda spec: spec.name in {"mongo", "bridge"},
        collector_probe=lambda _url: False,
        process_launcher=lambda spec, _log_dir: launched.append(spec.name),
    )

    status = supervisor.ensure_once()

    assert launched == ["collector"]
    assert status == {
        "mongo": "healthy",
        "proxy": "blocked",
        "bridge": "healthy",
        "collector": "started",
    }


def test_ensure_once_does_not_replace_unknown_collector_port(tmp_path: Path) -> None:
    from backend.snapshot_collector.supervisor import (
        ServiceSpec,
        SnapshotCollectorSupervisor,
    )

    spec = ServiceSpec(
        "collector",
        8001,
        tmp_path,
        ("python", "-m", "uvicorn"),
        health_url="http://127.0.0.1:8001/api/snapshot-collector/scheduler/status",
    )
    launched: list[str] = []
    supervisor = SnapshotCollectorSupervisor(
        specs=(spec,),
        log_dir=tmp_path / "logs",
        port_probe=lambda _port: True,
        collector_probe=lambda _url: False,
        process_launcher=lambda service, _log_dir: launched.append(service.name),
    )

    assert supervisor.ensure_once() == {"collector": "blocked"}
    assert launched == []


def test_ensure_once_does_not_treat_open_dependency_port_as_healthy(
    tmp_path: Path,
) -> None:
    from backend.snapshot_collector.supervisor import (
        ServiceSpec,
        SnapshotCollectorSupervisor,
    )

    spec = ServiceSpec(
        "proxy",
        3000,
        tmp_path,
        ("node", "server.js"),
        health_url="http://127.0.0.1:3000/health",
    )
    supervisor = SnapshotCollectorSupervisor(
        specs=(spec,),
        log_dir=tmp_path / "logs",
        port_probe=lambda _port: True,
        dependency_probe=lambda _spec: False,
    )

    assert supervisor.ensure_once() == {"proxy": "blocked"}


def test_ensure_once_restarts_owned_unhealthy_collector(tmp_path: Path) -> None:
    from backend.snapshot_collector.supervisor import (
        ServiceSpec,
        SnapshotCollectorSupervisor,
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.running = True
            self.terminated = False

        def poll(self) -> int | None:
            return None if self.running else 0

        def terminate(self) -> None:
            self.terminated = True
            self.running = False

        def wait(self, timeout: float) -> int:
            assert timeout > 0
            return 0

    spec = ServiceSpec(
        "collector",
        8001,
        tmp_path,
        ("python", "-m", "uvicorn"),
        health_url="http://127.0.0.1:8001/api/snapshot-collector/scheduler/status",
    )
    processes: list[FakeProcess] = []
    port_open = False

    def launch(_spec: ServiceSpec, _log_dir: Path) -> FakeProcess:
        process = FakeProcess()
        processes.append(process)
        return process

    supervisor = SnapshotCollectorSupervisor(
        specs=(spec,),
        log_dir=tmp_path / "logs",
        port_probe=lambda _port: port_open,
        collector_probe=lambda _url: False,
        process_launcher=launch,
    )

    assert supervisor.ensure_once() == {"collector": "started"}
    port_open = True
    assert supervisor.ensure_once() == {"collector": "restarted"}
    assert len(processes) == 2
    assert processes[0].terminated is True
