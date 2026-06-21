"""Windows supervisor for the shadow snapshot collector runtime.

The supervisor owns only the isolated collector API on port 8001. Existing
Dragon Board services are reused only after their health contracts pass.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import urlopen


SHADOW_DATASET_ID = "dragonboard_backend_shadow"
COLLECTOR_PORT = 8001
COLLECTOR_STATUS_URL = (
    f"http://127.0.0.1:{COLLECTOR_PORT}/api/snapshot-collector/scheduler/status"
)


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    port: int
    working_directory: Path
    command: tuple[str, ...]
    health_url: str | None = None


def build_service_specs(
    *,
    quant_root: Path,
    python_executable: Path,
    node_executable: Path,
    bridge_python: Path,
) -> tuple[ServiceSpec, ...]:
    project_root = quant_root.parent
    return (
        ServiceSpec(
            "mongo",
            27017,
            Path("D:/APP_SOFT/MongoDB/bin"),
            (
                "D:/APP_SOFT/MongoDB/bin/mongod.exe",
                "--dbpath",
                "D:/APP_SOFT/MongoDB/data",
                "--logpath",
                "D:/APP_SOFT/MongoDB/log/mongod.log",
                "--port",
                "27017",
            ),
        ),
        ServiceSpec(
            "proxy",
            3000,
            project_root / "proxy-server",
            (str(node_executable), "server.js"),
            health_url="http://127.0.0.1:3000/health",
        ),
        ServiceSpec(
            "bridge",
            8765,
            project_root,
            (str(bridge_python), "python-bridge/main.py"),
            health_url="http://127.0.0.1:8765/health",
        ),
        ServiceSpec(
            "collector",
            COLLECTOR_PORT,
            quant_root,
            (
                str(python_executable),
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(COLLECTOR_PORT),
            ),
            health_url=COLLECTOR_STATUS_URL,
        ),
    )


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def collector_payload_is_healthy(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False
    data = payload.get("data")
    return bool(
        isinstance(data, dict)
        and data.get("enabled") is True
        and data.get("running") is True
        and data.get("dataset_id") == SHADOW_DATASET_ID
    )


def collector_is_healthy(url: str) -> bool:
    try:
        with urlopen(url, timeout=2.0) as response:  # noqa: S310 - localhost only
            payload = json.loads(response.read().decode("utf-8"))
        return collector_payload_is_healthy(payload)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def dependency_payload_is_healthy(name: str, payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False
    expected_service = {
        "proxy": "stock-proxy-server",
        "bridge": "tdx-quote-bridge",
    }.get(name)
    return expected_service is not None and payload.get("service") == expected_service


def dependency_is_healthy(spec: ServiceSpec) -> bool:
    if spec.name == "mongo":
        try:
            from pymongo import MongoClient

            client = MongoClient(
                f"mongodb://127.0.0.1:{spec.port}",
                serverSelectionTimeoutMS=1000,
            )
            try:
                client.admin.command("ping")
            finally:
                client.close()
            return True
        except Exception:
            return False

    if not spec.health_url:
        return False
    try:
        with urlopen(spec.health_url, timeout=2.0) as response:  # noqa: S310 - localhost only
            payload = json.loads(response.read().decode("utf-8"))
        return dependency_payload_is_healthy(spec.name, payload)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def launch_hidden(spec: ServiceSpec, log_dir: Path) -> subprocess.Popen[bytes]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{spec.name}.log"
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    with log_path.open("ab") as output:
        return subprocess.Popen(  # noqa: S603 - commands are fixed local specs
            spec.command,
            cwd=spec.working_directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )


class SnapshotCollectorSupervisor:
    def __init__(
        self,
        *,
        specs: Iterable[ServiceSpec],
        log_dir: Path,
        port_probe: Callable[[int], bool] = port_is_open,
        dependency_probe: Callable[[ServiceSpec], bool] = dependency_is_healthy,
        collector_probe: Callable[[str], bool] = collector_is_healthy,
        process_launcher: Callable[[ServiceSpec, Path], Any] = launch_hidden,
    ) -> None:
        self.specs = tuple(specs)
        self.log_dir = log_dir
        self._port_probe = port_probe
        self._dependency_probe = dependency_probe
        self._collector_probe = collector_probe
        self._process_launcher = process_launcher
        self._spawned: dict[str, Any] = {}

    def _spawned_is_running(self, name: str) -> bool:
        process = self._spawned.get(name)
        return process is not None and callable(getattr(process, "poll", None)) and process.poll() is None

    def _restart_owned(self, spec: ServiceSpec) -> None:
        process = self._spawned[spec.name]
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._spawned[spec.name] = self._process_launcher(spec, self.log_dir)

    def ensure_once(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for spec in self.specs:
            port_open = self._port_probe(spec.port)
            healthy = (
                self._collector_probe(spec.health_url)
                if spec.name == "collector" and spec.health_url
                else self._dependency_probe(spec)
            )
            if healthy:
                status[spec.name] = "healthy"
                continue
            if port_open:
                if self._spawned_is_running(spec.name):
                    try:
                        self._restart_owned(spec)
                        status[spec.name] = "restarted"
                    except (OSError, subprocess.SubprocessError) as exc:
                        logging.error("Failed to restart %s: %s", spec.name, exc)
                        status[spec.name] = "error"
                    continue
                status[spec.name] = "blocked"
                continue

            if self._spawned_is_running(spec.name):
                status[spec.name] = "starting"
                continue

            try:
                process = self._process_launcher(spec, self.log_dir)
                if process is not None:
                    self._spawned[spec.name] = process
                status[spec.name] = "started"
            except (OSError, subprocess.SubprocessError) as exc:
                logging.error("Failed to start %s: %s", spec.name, exc)
                status[spec.name] = "error"
        return status


def _configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "supervisor.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def main() -> None:
    quant_root = Path(__file__).resolve().parents[2]
    log_dir = quant_root / "data" / "logs" / "snapshot-collector"
    _configure_logging(log_dir)

    node = Path(shutil.which("node") or "node")
    bridge_python = Path(shutil.which("python") or sys.executable)
    specs = build_service_specs(
        quant_root=quant_root,
        python_executable=Path(sys.executable),
        node_executable=node,
        bridge_python=bridge_python,
    )
    supervisor = SnapshotCollectorSupervisor(specs=specs, log_dir=log_dir)
    logging.info("Snapshot collector supervisor started from %s", quant_root)

    while True:
        status = supervisor.ensure_once()
        logging.info("Runtime status: %s", status)
        time.sleep(15)


if __name__ == "__main__":
    main()
