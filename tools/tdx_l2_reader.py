"""
TDX 深度行情实验性内存扫描器
从正在运行的通达信客户端 (tdxw.exe) 进程内存中扫描疑似十档买卖结构。

用法:
    python tdx_l2_reader.py                          # 扫描模式，定位深度数据地址
    python tdx_l2_reader.py --monitor                 # 监控模式，持续输出候选深度 JSON
    python tdx_l2_reader.py --output l2_data.jsonl    # 输出到文件

编译为 .exe:
    pip install pyinstaller
    pyinstaller --onefile --console tdx_l2_reader.py

原理:
    通达信客户端在运行期间可能将十档数据缓存在进程内存的连续结构体中。
    本工具通过 Windows API ReadProcessMemory 直接从 tdxw.exe 读取这些数据，
    无需 DLL 注入、无需额外鉴权、不修改目标进程。

边界:
    这是隔离只读探针，不是生产 L2 行情链路，也不代表 7719 / 官方 L2 已完成。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import math
import os
import re
import struct
import sys
import time
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import dataclass, field

# ── Windows API ────────────────────────────────────────────────────────────

kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_IMAGE = 0x1000000
PAGE_READABLE = {2, 4, 6, 8, 32, 64, 128}

TH32CS_SNAPPROCESS = 0x00000002


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("PartitionId", ctypes.wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = ctypes.wintypes.BOOL
kernel32.Process32NextW.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = ctypes.wintypes.BOOL
kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.LPWSTR,
    ctypes.POINTER(ctypes.wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = ctypes.wintypes.BOOL
kernel32.VirtualQueryEx.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


# ── 进程工具 ────────────────────────────────────────────────────────────────

def find_tdx_process() -> list[dict]:
    """查找所有 tdxw.exe 进程，返回 PID 和路径列表。"""
    results: list[dict] = []
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.wintypes.HANDLE(-1).value:
        return results

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == "tdxw.exe":
                pid = entry.th32ProcessID
                path = resolve_process_exe_path(pid)
                results.append({"pid": pid, "path": path or ""})
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return results


def resolve_process_exe_path(pid: int) -> str | None:
    access = PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(512)
        size = ctypes.wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        kernel32.CloseHandle(handle)
    return None


def open_process(pid: int) -> int:
    """打开进程，返回句柄（整数）。"""
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise OSError(f"无法打开进程 PID={pid}")
    return handle


def close_process(handle: int) -> None:
    kernel32.CloseHandle(handle)


def read_bytes(handle: int, address: int, size: int) -> bytes:
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    if not kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read)
    ):
        return b""
    return buffer.raw[: bytes_read.value]


def read_float(handle: int, address: int) -> float:
    raw = read_bytes(handle, address, 4)
    if len(raw) < 4:
        return math.nan
    return struct.unpack("<f", raw)[0]


def read_int32(handle: int, address: int) -> int:
    raw = read_bytes(handle, address, 4)
    if len(raw) < 4:
        return 0
    return struct.unpack("<i", raw)[0]


def enumerate_regions(handle: int) -> list[dict]:
    """枚举进程所有已提交的私有内存区域。"""
    regions: list[dict] = []
    address = 0
    while True:
        mbi = MEMORY_BASIC_INFORMATION()
        result = kernel32.VirtualQueryEx(
            ctypes.c_void_p(handle), ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if result == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE and mbi.Protect in PAGE_READABLE:
            base = ctypes.cast(mbi.BaseAddress, ctypes.c_void_p).value
            size = mbi.RegionSize
            if base and size and size < 512 * 1024 * 1024:  # 排除超大保留区域
                regions.append({"base": base, "size": size})
        address = (mbi.BaseAddress or 0) + mbi.RegionSize
    return regions


# ── 模式匹配 ────────────────────────────────────────────────────────────────

def is_valid_price(val: float) -> bool:
    """检查浮点数是否可能是股票价格 (0.01 ~ 10000)。"""
    return math.isfinite(val) and 0.01 < val < 10000.0


def is_monotonic(values: list[float], descending: bool) -> bool:
    """检查浮点序列是否单调。"""
    if len(values) < 2:
        return True
    for a, b in zip(values, values[1:]):
        if descending and a < b:
            return False
        if not descending and a > b:
            return False
    return True


def score_depth_candidate(prices: list[float]) -> int:
    """给一个候选深度序列打分 (10 档买 + 10 档卖 = 20 个价格)。"""
    if len(prices) < 6:  # 至少要有少量价格
        return 0

    bids_valid = [p for p in prices[:10] if is_valid_price(p) and p > 0]
    asks_valid = [p for p in prices[10:20] if is_valid_price(p) and p > 0]

    if len(bids_valid) < 3 or len(asks_valid) < 3:
        return 0

    score = 0
    # 买盘单调递减
    if is_monotonic(bids_valid, descending=True):
        score += len(bids_valid) * 2
    # 卖盘单调递增
    if is_monotonic(asks_valid, descending=False):
        score += len(asks_valid) * 2
    # 买一 < 卖一
    if bids_valid and asks_valid and bids_valid[0] < asks_valid[-1] and bids_valid[0] < asks_valid[0]:
        score += 5
    # 买卖价格在合理区间
    if bids_valid and max(bids_valid) < min(asks_valid) * 1.5:
        score += 3

    return score


# ── 扫描 ────────────────────────────────────────────────────────────────────

@dataclass
class DepthCandidate:
    address: int
    bids_prices: list[float]
    asks_prices: list[float]
    bids_volumes: list[float]
    asks_volumes: list[float]
    score: int
    code_hint: str = ""


def scan_region(handle: int, base: int, size: int, step: int = 8) -> list[DepthCandidate]:
    """在内存区域中扫描 L2 深度数据结构。"""
    candidates: list[DepthCandidate] = []

    # 只扫描前 8MB 的较大区域（完整扫描太慢）
    scan_size = min(size, 8 * 1024 * 1024)
    try:
        data = read_bytes(handle, base, scan_size)
    except Exception:
        return candidates

    if len(data) < 80:
        return candidates

    # 策略：找到连续的价格浮点
    float_count = len(data) // 4
    prices: list[tuple[int, float]] = []
    for i in range(0, len(data) - 4, 4):
        val = struct.unpack_from("<f", data, i)[0]
        if is_valid_price(val):
            prices.append((base + i, val))

    # 查找 10 个递减（买盘）+ 10 个递增（卖盘）模式的连续价格组
    price_index = {addr: val for addr, val in prices}
    price_addrs = sorted(price_index.keys())

    for start_addr in price_addrs:
        # 尝试从 start_addr 开始读取 40 个 float（20 价格 + 20 量）
        chunk = read_bytes(handle, start_addr, 160)
        if len(chunk) < 40:
            continue

        floats = [struct.unpack_from("<f", chunk, i)[0] for i in range(0, len(chunk), 4)]

        # 检查前 20 个是否可能为买卖价格
        candidate_prices = floats[:20]
        score = score_depth_candidate(candidate_prices)
        if score >= 10:
            bids_p = [p for p in candidate_prices[:10] if is_valid_price(p) and p > 0]
            asks_p = [p for p in candidate_prices[10:20] if is_valid_price(p) and p > 0]
            if bids_p and asks_p:
                candidates.append(
                    DepthCandidate(
                        address=start_addr,
                        bids_prices=bids_p,
                        asks_prices=asks_p,
                        bids_volumes=floats[20:30],
                        asks_volumes=floats[30:40],
                        score=score,
                    )
                )

    # 去重：按地址排序，合并相近地址（8 字节内）
    candidates.sort(key=lambda c: c.score, reverse=True)
    unique: list[DepthCandidate] = []
    for c in candidates:
        if not any(abs(c.address - u.address) < 16 for u in unique):
            unique.append(c)
        if len(unique) >= 50:
            break

    return unique


def scan_all(handle: int, tdx_root: str) -> list[DepthCandidate]:
    """扫描所有堆区域，返回按分数排序的候选深度数据地址。"""
    regions = enumerate_regions(handle)
    heap_regions = [r for r in regions if r["size"] > 256 * 1024]  # 只扫描 >256KB 的区域
    heap_regions.sort(key=lambda r: r["size"], reverse=True)

    print(f"[扫描] {len(heap_regions)} 个堆区域待扫描...")
    all_candidates: list[DepthCandidate] = []

    total = len(heap_regions)
    for idx, region in enumerate(heap_regions):
        size_mb = region["size"] / (1024 * 1024)
        print(f"\r[扫描] {idx + 1}/{total} — 0x{region['base']:X} ({size_mb:.1f} MB)...", end="", flush=True)
        candidates = scan_region(handle, region["base"], region["size"])
        all_candidates.extend(candidates)

    print()
    all_candidates.sort(key=lambda c: c.score, reverse=True)
    return all_candidates


# ── 持续监控 ────────────────────────────────────────────────────────────────

def read_depth_record(handle: int, addr: int) -> dict | None:
    """从指定地址读取一条 L2 深度记录。"""
    chunk = read_bytes(handle, addr, 160)
    if len(chunk) < 40:
        return None

    floats = [struct.unpack_from("<f", chunk, i)[0] for i in range(0, len(chunk), 4)]
    bids_p = [round(p, 2) for p in floats[:10] if is_valid_price(p) and p > 0]
    asks_p = [round(p, 2) for p in floats[10:20] if is_valid_price(p) and p > 0]
    bids_v = [round(v, 0) for v in floats[20:30] if v > 0]
    asks_v = [round(v, 0) for v in floats[30:40] if v > 0]

    if not bids_p or not asks_p:
        return None

    return {
        "bids": [{"price": p, "volume": int(v)} for p, v in zip(bids_p, bids_v)]
        if bids_v
        else [{"price": p} for p in bids_p],
        "asks": [{"price": p, "volume": int(v)} for p, v in zip(asks_p, asks_v)]
        if asks_v
        else [{"price": p} for p in asks_p],
    }


def monitor_loop(handle: int, addresses: list[int], interval_ms: int = 500):
    """循环读取指定地址的深度数据并输出 JSON。"""
    print(f"[监控] {len(addresses)} 个地址, 间隔 {interval_ms}ms", file=sys.stderr)
    last_data: dict[int, str] = {}

    while True:
        ts = time.time()
        outputs: list[dict] = []

        for addr in addresses:
            record = read_depth_record(handle, addr)
            if record is None:
                continue
            payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
            if last_data.get(addr) != payload:
                last_data[addr] = payload
                outputs.append({"addr": f"0x{addr:X}", **record})

        if outputs:
            for item in outputs:
                print(json.dumps(item, ensure_ascii=False))

        elapsed = (time.time() - ts) * 1000
        sleep_ms = max(50, interval_ms - int(elapsed))
        time.sleep(sleep_ms / 1000)


# ── 持久化缓存 ────────────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tdx_l2_cache")


def save_addresses(tdx_root: str, addresses: list[int]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "addresses.json")
    with open(path, "w") as f:
        json.dump(
            {"tdx_root": tdx_root, "addresses": [f"0x{a:X}" for a in addresses], "ts": time.time()},
            f,
        )


def load_addresses(tdx_root: str) -> list[int] | None:
    path = os.path.join(CACHE_DIR, "addresses.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    if data.get("tdx_root") != tdx_root:
        return None
    return [int(addr, 16) for addr in data["addresses"]]


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = ArgumentParser(description="TDX 深度行情实验性内存扫描器")
    parser.add_argument("--monitor", action="store_true", help="持续监控模式")
    parser.add_argument("--scan", action="store_true", help="强制重新扫描内存")
    parser.add_argument("--tdx-root", default=r"D:\APP_SOFT\TDX", help="通达信安装目录")
    parser.add_argument("--interval", type=int, default=500, help="轮询间隔 (ms)")
    parser.add_argument("--output", help="输出文件路径（默认 stdout）")
    args = parser.parse_args()

    # 1. 查找进程
    processes = find_tdx_process()
    if not processes:
        print("[错误] 未找到运行中的 tdxw.exe 进程", file=sys.stderr)
        sys.exit(1)

    tdx = processes[0]
    print(f"[进程] tdxw.exe PID={tdx['pid']} 路径={tdx['path']}", file=sys.stderr)

    handle = open_process(tdx["pid"])
    try:
        # 2. 加载或扫描地址
        addresses = None if args.scan else load_addresses(args.tdx_root)

        if addresses is None:
            print("[扫描] 正在搜索内存中的疑似深度数据...", file=sys.stderr)
            candidates = scan_all(handle, args.tdx_root)

            if not candidates:
                print(
                    "[错误] 未找到 L2 深度数据。请确保:\n"
                    "  1. 通达信客户端已打开 L2 行情面板\n"
                    "  2. 当前为交易时段\n"
                    "  3. 至少有一只股票正在显示十档行情",
                    file=sys.stderr,
                )
                sys.exit(2)

            print(f"\n[结果] 找到 {len(candidates)} 个候选地址:", file=sys.stderr)
            for c in candidates[:20]:
                print(
                    f"  0x{c.address:08X}  score={c.score:2d}  "
                    f"bid1={c.bids_prices[0]:.2f}  ask1={c.asks_prices[0]:.2f}  "
                    f"bids={len(c.bids_prices)} asks={len(c.asks_prices)}",
                    file=sys.stderr,
                )

            # 取所有高分候选
            best_score = candidates[0].score
            addresses = [c.address for c in candidates if c.score >= max(best_score * 0.6, 10)]

            if addresses:
                save_addresses(args.tdx_root, addresses)
                print(f"[缓存] 已保存 {len(addresses)} 个地址", file=sys.stderr)

        # 3. 监控模式
        if args.monitor:
            if args.output:
                sys.stdout = open(args.output, "a", encoding="utf-8")
            monitor_loop(handle, addresses, args.interval)
        else:
            # 单次读取
            for addr in addresses:
                record = read_depth_record(handle, addr)
                if record:
                    print(json.dumps({"addr": f"0x{addr:X}", **record}, ensure_ascii=False))

    finally:
        close_process(handle)


if __name__ == "__main__":
    main()
