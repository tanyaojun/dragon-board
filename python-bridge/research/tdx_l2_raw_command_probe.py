"""Raw command probe for TDX 7719 candidates.

This is an isolated network probe. It sends known public TDX setup packets and
selected read-only quote-like packets, then records response header/body sizes
and hex prefixes. It does not modify local TDX files and does not inject into
the official client.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SERVERS = (
    "124.71.222.84:7719",
    "139.9.2.221:7719",
    "106.52.50.92:7719",
    "115.159.210.142:7719",
)

SETUP_PACKETS = [
    bytes.fromhex("0c 02 18 93 00 01 03 00 03 00 0d 00 01"),
    bytes.fromhex("0c 02 18 94 00 01 03 00 03 00 0d 00 02"),
    bytes.fromhex(
        "0c 03 18 99 00 01 20 00 20 00 db 0f d5 d0"
        "c9 cc d6 a4 a8 af 00 00 00 8f c2 25 40 13"
        "00 00 d5 00 c9 cc bd f0 d7 ea 00 00 00 02"
    ),
]


@dataclass
class RawResponse:
    ok: bool
    elapsed_ms: int
    header_hex: str = ""
    body_len: int = 0
    unzip_len: int = 0
    zip_len: int = 0
    body_prefix_hex: str = ""
    error: str = ""


def normalize_code(code: str) -> str:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    return digits[-6:]


def market_for_code(code: str) -> int:
    return 1 if normalize_code(code).startswith("6") else 0


def build_security_quotes_pkg(codes: list[str], command: int = 0x5053E) -> bytes:
    stock_pairs = [(market_for_code(code), normalize_code(code).encode("ascii")) for code in codes]
    stock_len = len(stock_pairs)
    payload_len = stock_len * 7 + 12
    pkg = bytearray(struct.pack("<HIHHIIHH", 0x10C, 0x02006320, payload_len, payload_len, command, 0, 0, stock_len))
    for market, code in stock_pairs:
        pkg.extend(struct.pack("<B6s", market, code))
    return bytes(pkg)


def build_transaction_pkg(code: str, start: int = 0, count: int = 60) -> bytes:
    normalized = normalize_code(code).encode("ascii")
    pkg = bytearray.fromhex("0c 17 08 01 01 01 0e 00 0e 00 c5 0f")
    pkg.extend(struct.pack("<H6sHH", market_for_code(code), normalized, start, count))
    return bytes(pkg)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_pkg(sock: socket.socket, pkg: bytes, timeout: float) -> RawResponse:
    started = time.perf_counter()
    try:
        sock.settimeout(timeout)
        sock.sendall(pkg)
        header = recv_exact(sock, 0x10)
        if len(header) != 0x10:
            return RawResponse(
                ok=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                header_hex=header.hex(" "),
                error=f"short_header:{len(header)}",
            )

        _, _, _, zip_len, unzip_len = struct.unpack("<IIIHH", header)
        body = recv_exact(sock, zip_len)
        if len(body) != zip_len:
            return RawResponse(
                ok=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                header_hex=header.hex(" "),
                body_len=len(body),
                zip_len=zip_len,
                unzip_len=unzip_len,
                body_prefix_hex=body[:96].hex(" "),
                error=f"short_body:{len(body)}/{zip_len}",
            )

        decoded = body
        if zip_len != unzip_len and body:
            try:
                decoded = zlib.decompress(body)
            except Exception:
                decoded = body

        return RawResponse(
            ok=True,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            header_hex=header.hex(" "),
            body_len=len(decoded),
            zip_len=zip_len,
            unzip_len=unzip_len,
            body_prefix_hex=decoded[:128].hex(" "),
        )
    except Exception as error:
        return RawResponse(
            ok=False,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            error=str(error),
        )


def run_setup(sock: socket.socket, timeout: float) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for index, pkg in enumerate(SETUP_PACKETS, start=1):
        rsp = send_pkg(sock, pkg, timeout)
        commands.append({"name": f"setup{index}", **rsp.__dict__})
        if not rsp.ok:
            break
    return commands


def probe_command(server: str, timeout: float, name: str, pkg: bytes) -> dict[str, Any]:
    host, port_text = server.rsplit(":", 1)
    port = int(port_text)
    result: dict[str, Any] = {"name": name}
    started = time.perf_counter()

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            result["connect"] = {"ok": True, "elapsedMs": int((time.perf_counter() - started) * 1000)}
            setup = run_setup(sock, timeout)
            result["setup"] = setup
            if not setup or not all(item.get("ok") for item in setup):
                result["response"] = {"ok": False, "elapsed_ms": 0, "error": "setup_failed"}
                return result

            result["response"] = send_pkg(sock, pkg, timeout).__dict__
    except Exception as error:
        result["connect"] = {"ok": False, "elapsedMs": int((time.perf_counter() - started) * 1000), "error": str(error)}

    return result


def probe_server(server: str, codes: list[str], timeout: float, sweep: bool) -> dict[str, Any]:
    commands: list[tuple[str, bytes]] = [
        ("std_quote_0x5053e", build_security_quotes_pkg(codes, 0x5053E)),
        ("std_transaction", build_transaction_pkg(codes[0] if codes else "000001")),
    ]

    if sweep:
        for command in range(0x50530, 0x50550):
            if command == 0x5053E:
                continue
            commands.append((f"quote_variant_{command:#x}", build_security_quotes_pkg(codes, command)))

    return {
        "server": server,
        "commands": [probe_command(server, timeout, name, pkg) for name, pkg in commands],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Raw TDX command probe for L2 7719 candidates")
    parser.add_argument("--servers", default=",".join(DEFAULT_SERVERS))
    parser.add_argument("--symbols", default="000001,600000")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    servers = [item.strip() for item in args.servers.split(",") if item.strip()]
    codes = [normalize_code(item) for item in args.symbols.split(",") if normalize_code(item)]

    report = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "raw_read_only_l2_command_probe",
        "symbols": codes,
        "servers": servers,
        "sweep": args.sweep,
        "results": [probe_server(server, codes, args.timeout, args.sweep) for server in servers],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "serverCount": len(servers)}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
