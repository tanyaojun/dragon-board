"""Discover live TDX client routes without packet capture.

This script stays read-only. It uses PowerShell to enumerate a running
``tdxw.exe`` process, its established TCP connections, and recent IP-bearing
lines from ``tdxsys3.log``. It does not modify client files and does not need
administrator privileges.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def normalize_process_name(name: str) -> str:
    text = name.strip()
    if text.lower().endswith(".exe"):
        return text[:-4]
    return text


def run_powershell(command: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f"exit={result.returncode}").strip()
        raise RuntimeError(message)
    return result.stdout


def ensure_list(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def load_processes(process_name: str) -> list[dict[str, Any]]:
    command = (
        f"Get-Process {normalize_process_name(process_name)} -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,Path,StartTime | ConvertTo-Json -Depth 3"
    )
    raw = run_powershell(command).strip()
    if not raw:
        return []
    return ensure_list(json.loads(raw))


def load_connections(pids: list[int]) -> list[dict[str, Any]]:
    if not pids:
        return []
    pid_text = ",".join(str(pid) for pid in pids)
    command = (
        f"$pids=@({pid_text}); "
        "Get-NetTCPConnection -State Established | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess | "
        "Sort-Object RemotePort,RemoteAddress | ConvertTo-Json -Depth 3"
    )
    raw = run_powershell(command).strip()
    if not raw:
        return []
    return ensure_list(json.loads(raw))


def read_text_best_effort(path: Path) -> str:
    encodings = ("gb18030", "utf-8", "utf-16")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except Exception as error:  # pragma: no cover
            last_error = error
    raise RuntimeError(f"unable to decode {path}: {last_error}")


def extract_recent_log_events(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = read_text_best_effort(path)
    matches: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        ips = IP_RE.findall(line)
        if not ips:
            continue
        matches.append({"lineNumber": line_no, "ips": ips, "line": line.strip()})
    return matches[-limit:]


def filter_connections(connections: list[dict[str, Any]], ports: set[int]) -> list[dict[str, Any]]:
    if not ports:
        return connections
    return [item for item in connections if int(item.get("RemotePort", -1)) in ports]


def unique_endpoints(connections: list[dict[str, Any]]) -> list[str]:
    endpoints = {
        f"{item.get('RemoteAddress')}:{item.get('RemotePort')}"
        for item in connections
        if item.get("RemoteAddress") and item.get("RemotePort") is not None
    }
    return sorted(endpoints)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live TDX route probe")
    parser.add_argument("--process-name", default="tdxw.exe")
    parser.add_argument("--tdx-root", default=r"D:\APP_SOFT\TDX")
    parser.add_argument("--ports", default="", help="Optional remote port filter, e.g. 7719,7712,7615")
    parser.add_argument("--log-tail", type=int, default=12, help="Number of recent IP-bearing log lines to keep")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    ports = {int(item.strip()) for item in args.ports.split(",") if item.strip()}
    tdx_root = Path(args.tdx_root)
    log_path = tdx_root / "T0001" / "tdxsys3.log"

    report: dict[str, Any] = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "read_only_tdx_live_route_probe",
        "processName": args.process_name,
        "tdxRoot": str(tdx_root),
        "portFilter": sorted(ports),
        "processes": [],
        "connections": [],
        "uniqueRemoteEndpoints": [],
        "logPath": str(log_path),
        "recentLogIpEvents": [],
    }

    processes = load_processes(args.process_name)
    report["processes"] = processes

    pids = [int(item["Id"]) for item in processes if "Id" in item]
    connections = filter_connections(load_connections(pids), ports)
    report["connections"] = connections
    report["uniqueRemoteEndpoints"] = unique_endpoints(connections)
    report["recentLogIpEvents"] = extract_recent_log_events(log_path, args.log_tail)

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "endpointCount": len(report["uniqueRemoteEndpoints"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
