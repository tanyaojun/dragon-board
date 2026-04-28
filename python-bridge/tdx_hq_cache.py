import math
import os
import re
import struct
from dataclasses import dataclass
from typing import Any, Iterable


TH2_RECORD_SIZE = 172
PRICE_LIMIT = 100000.0
VOLUME_LIMIT = 10_000_000_000
TNF_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def infer_market(code: str) -> str:
    if code.startswith(("4", "8")):
        return "bj"
    if code.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def _read_u32(chunk: bytes, offset: int) -> int:
    return struct.unpack_from("<I", chunk, offset)[0]


def _read_f32(chunk: bytes, offset: int) -> float:
    return struct.unpack_from("<f", chunk, offset)[0]


def _is_price(value: float) -> bool:
    return math.isfinite(value) and 0.0 < value < PRICE_LIMIT


def _is_volume(value: int) -> bool:
    return 0 <= value < VOLUME_LIMIT


def _trim_levels(prices: list[float], volumes: list[int]) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    for price, volume in zip(prices, volumes):
        if not _is_price(price):
            continue
        if not _is_volume(volume):
            continue
        levels.append({"price": round(price, 3), "volume": float(volume)})
    return levels


def _monotonic_score(levels: list[dict[str, float]], descending: bool) -> int:
    prices = [float(item["price"]) for item in levels]
    if len(prices) < 2:
        return 0
    score = 0
    for left, right in zip(prices, prices[1:]):
        if descending and left >= right:
            score += 1
        if not descending and left <= right:
            score += 1
    return score


def _candidate_score(bids: list[dict[str, float]], asks: list[dict[str, float]]) -> int:
    if len(bids) < 3 or len(asks) < 3:
        return -1

    bid1 = float(bids[0]["price"])
    ask1 = float(asks[0]["price"])
    if ask1 < bid1:
        return -1

    bid_score = _monotonic_score(bids, descending=True)
    ask_score = _monotonic_score(asks, descending=False)
    level_score = len(bids) + len(asks)
    spread_score = 1 if (ask1 - bid1) <= max(1.0, bid1 * 0.1) else 0
    return bid_score + ask_score + level_score + spread_score


def parse_th2_record(chunk: bytes) -> dict[str, Any] | None:
    if len(chunk) < TH2_RECORD_SIZE:
        return None

    best_score = -1
    best_depth: dict[str, Any] | None = None

    for start in range(0, 33, 4):
        if start + 76 >= len(chunk):
            continue

        prices1 = [_read_f32(chunk, start + index * 4) for index in range(5)]
        vols1 = [_read_u32(chunk, start + 20 + index * 4) for index in range(5)]
        prices2 = [_read_f32(chunk, start + 40 + index * 4) for index in range(5)]
        vols2 = [_read_u32(chunk, start + 60 + index * 4) for index in range(5)]

        side1 = _trim_levels(prices1, vols1)
        side2 = _trim_levels(prices2, vols2)
        if not side1 or not side2:
            continue

        candidates = (
            (side1, side2),
            (side2, side1),
        )
        for bids, asks in candidates:
            score = _candidate_score(bids, asks)
            if score > best_score:
                best_score = score
                best_depth = {"bids": bids, "asks": asks}

    return best_depth


@dataclass
class MarketIndex:
    signature: tuple[int, int] | None = None
    codes: list[str] | None = None
    code_to_index: dict[str, int] | None = None


class OfficialHQCacheDepthReader:
    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self._markets: dict[str, MarketIndex] = {
            "sh": MarketIndex(),
            "sz": MarketIndex(),
            "bj": MarketIndex(),
        }

    def _tnf_path(self, market: str) -> str:
        return os.path.join(self.root, f"{market}s.tnf")

    def _th2_path(self, market: str) -> str:
        return os.path.join(self.root, f"{market}.th2")

    def _file_signature(self, path: str) -> tuple[int, int] | None:
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)

    def _load_market_index(self, market: str) -> dict[str, int]:
        state = self._markets[market]
        path = self._tnf_path(market)
        signature = self._file_signature(path)
        if not signature:
            return {}
        if state.signature == signature and state.code_to_index is not None:
            return state.code_to_index

        try:
            text = open(path, "rb").read().decode("gbk", "ignore")
        except OSError:
            return {}

        codes: list[str] = []
        seen: set[str] = set()
        for match in TNF_CODE_PATTERN.finditer(text):
            code = match.group(1)
            if code in seen:
                continue
            seen.add(code)
            codes.append(code)

        state.signature = signature
        state.codes = codes
        state.code_to_index = {code: index for index, code in enumerate(codes)}
        return state.code_to_index

    def read_depth(self, requested_codes: Iterable[str]) -> list[dict[str, Any]]:
        market_requests: dict[str, list[str]] = {"sh": [], "sz": [], "bj": []}
        seen: set[str] = set()
        for raw_code in requested_codes:
            code = "".join(ch for ch in str(raw_code or "") if ch.isdigit())[-6:]
            if len(code) != 6 or code in seen:
                continue
            seen.add(code)
            market_requests[infer_market(code)].append(code)

        items: list[dict[str, Any]] = []
        for market, codes in market_requests.items():
            if not codes:
                continue

            code_to_index = self._load_market_index(market)
            if not code_to_index:
                continue

            th2_path = self._th2_path(market)
            signature = self._file_signature(th2_path)
            if not signature:
                continue

            source_ts = int(signature[1] / 1_000_000)
            indexed_codes = [
                (code_to_index[code], code)
                for code in codes
                if code in code_to_index
            ]
            if not indexed_codes:
                continue

            indexed_codes.sort()
            try:
                with open(th2_path, "rb") as handle:
                    for index, code in indexed_codes:
                        offset = index * TH2_RECORD_SIZE
                        handle.seek(offset)
                        chunk = handle.read(TH2_RECORD_SIZE)
                        depth = parse_th2_record(chunk)
                        if not depth:
                            continue
                        items.append(
                            {
                                "code": code,
                                "bids": depth["bids"],
                                "asks": depth["asks"],
                                "sourceTs": source_ts,
                            }
                        )
            except OSError:
                continue

        return items
