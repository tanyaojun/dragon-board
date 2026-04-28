"""Read-only probe for TDX 7719/L2 exploration.

This script is intentionally isolated from python-bridge/main.py. It does not
modify the production bridge, does not install dependencies, and does not try to
inject or drive the official TDX client.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any

from mootdx.quotes import Quotes


DEFAULT_SERVERS = "218.6.170.47:7709,106.52.50.92:7719,124.71.222.84:7719"
DEFAULT_SYMBOLS = "000001,600000"


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_servers(raw: str) -> list[tuple[str, int]]:
    servers: list[tuple[str, int]] = []
    for item in raw.split(","):
        text = item.strip()
        if not text or ":" not in text:
            continue
        host, port_text = text.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            continue
        servers.append((host.strip(), port))
    return servers


def parse_symbols(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def frame_to_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return list(frame.to_dict("records"))
        except Exception:
            return []
    if isinstance(frame, dict):
        return [frame]
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def summarize_frame(frame: Any) -> dict[str, Any]:
    records = frame_to_records(frame)
    columns: list[str] = []
    if hasattr(frame, "columns"):
        try:
            columns = [str(item) for item in list(frame.columns)]
        except Exception:
            columns = []
    elif records:
        columns = [str(item) for item in records[0].keys()]

    sample = records[0] if records else {}
    return {
        "rows": len(records),
        "columns": columns,
        "sampleKeys": list(sample.keys())[:20],
        "sampleCode": sample.get("code") or sample.get("symbol"),
    }


def safe_call(label: str, fn) -> dict[str, Any]:
    started = now_ms()
    try:
        value = fn()
        return {
            "ok": True,
            "elapsedMs": now_ms() - started,
            "value": value,
        }
    except Exception as error:
        return {
            "ok": False,
            "elapsedMs": now_ms() - started,
            "errorType": type(error).__name__,
            "error": str(error),
            "label": label,
        }


def probe_tcp(host: str, port: int, timeout: float) -> dict[str, Any]:
    started = now_ms()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "ok": True,
                "elapsedMs": now_ms() - started,
            }
    except Exception as error:
        return {
            "ok": False,
            "elapsedMs": now_ms() - started,
            "errorType": type(error).__name__,
            "error": str(error),
        }


@dataclass
class ServerProbeResult:
    server: str
    tcp: dict[str, Any]
    connect: dict[str, Any]
    stockCountSh: dict[str, Any]
    stockCountSz: dict[str, Any]
    quotes: dict[str, Any]
    transaction: dict[str, Any]
    traffic: dict[str, Any]


def probe_mootdx(host: str, port: int, symbols: list[str], timeout: int) -> dict[str, Any]:
    client = None
    started = now_ms()
    try:
        client = Quotes.factory(
            market="std",
            server=(host, port),
            bestip=False,
            heartbeat=False,
            auto_retry=False,
            timeout=timeout,
        )
        connect_result = {
            "ok": True,
            "elapsedMs": now_ms() - started,
        }
    except Exception as error:
        return {
            "connect": {
                "ok": False,
                "elapsedMs": now_ms() - started,
                "errorType": type(error).__name__,
                "error": str(error),
            },
            "stockCountSh": {"ok": False, "skipped": True},
            "stockCountSz": {"ok": False, "skipped": True},
            "quotes": {"ok": False, "skipped": True},
            "transaction": {"ok": False, "skipped": True},
            "traffic": {"ok": False, "skipped": True},
        }

    try:
        stock_count_sh = safe_call("stock_count_sh", lambda: client.stock_count(market=1))
        stock_count_sz = safe_call("stock_count_sz", lambda: client.stock_count(market=0))
        quotes = safe_call("quotes", lambda: summarize_frame(client.quotes(symbol=symbols)))
        transaction_symbol = symbols[0] if symbols else "000001"
        transaction = safe_call(
            "transaction",
            lambda: summarize_frame(client.transaction(symbol=transaction_symbol, start=0, offset=20)),
        )
        traffic = safe_call("traffic", lambda: client.traffic() if hasattr(client, "traffic") else None)
        return {
            "connect": connect_result,
            "stockCountSh": stock_count_sh,
            "stockCountSz": stock_count_sz,
            "quotes": quotes,
            "transaction": transaction,
            "traffic": traffic,
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def probe_server(host: str, port: int, symbols: list[str], timeout: int) -> ServerProbeResult:
    tcp = probe_tcp(host, port, timeout)
    mootdx_result = probe_mootdx(host, port, symbols, timeout)
    return ServerProbeResult(
        server=f"{host}:{port}",
        tcp=tcp,
        connect=mootdx_result["connect"],
        stockCountSh=mootdx_result["stockCountSh"],
        stockCountSz=mootdx_result["stockCountSz"],
        quotes=mootdx_result["quotes"],
        transaction=mootdx_result["transaction"],
        traffic=mootdx_result["traffic"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only TDX 7719/L2 probe")
    parser.add_argument(
        "--servers",
        default=DEFAULT_SERVERS,
        help="Comma separated host:port list. Defaults to known 7709/7719 candidates.",
    )
    parser.add_argument(
        "--symbols",
        default=DEFAULT_SYMBOLS,
        help="Comma separated stock codes used for quote probes.",
    )
    parser.add_argument("--timeout", type=int, default=8, help="Socket/API timeout in seconds.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    servers = parse_servers(args.servers)
    symbols = parse_symbols(args.symbols)

    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "read_only_7719_probe",
        "symbols": symbols,
        "servers": [f"{host}:{port}" for host, port in servers],
        "results": [asdict(probe_server(host, port, symbols, args.timeout)) for host, port in servers],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(payload)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(payload)
            file.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
