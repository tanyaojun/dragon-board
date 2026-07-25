from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class DepthLevel:
    price: float
    volume: float


@dataclass
class Depth10Book:
    code: str
    bids: list[DepthLevel] = field(default_factory=list)
    asks: list[DepthLevel] = field(default_factory=list)
    sourceTs: int = 0
    seq: int = 0
    timestamp: int = field(default_factory=now_ms)
    provider: str = "qmt"
    depthLevelCount: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bids"] = [asdict(level) for level in self.bids]
        payload["asks"] = [asdict(level) for level in self.asks]
        return payload


@dataclass
class TickTrade:
    code: str
    price: float
    volume: float
    amount: float
    side: str
    tradeTime: str
    sourceTs: int = 0
    timestamp: int = field(default_factory=now_ms)
    provider: str = "qmt"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class L2ProviderStatus:
    provider: str
    enabled: bool
    status: str
    message: str
    lastProbeTs: int = 0
    lastDataTs: int = 0
    subscribedCount: int = 0
    depthLevelCount: int = 0
    fallbackActive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class L2Snapshot:
    depth: list[Depth10Book] = field(default_factory=list)
    ticks: list[dict[str, Any]] = field(default_factory=list)
    status: L2ProviderStatus | None = None


class L2Provider(Protocol):
    def probe(self, codes: list[str]) -> L2ProviderStatus:
        ...

    def subscribe(self, codes: list[str]) -> L2ProviderStatus:
        ...

    def poll_snapshot(self, codes: list[str]) -> L2Snapshot:
        ...

    def close(self) -> None:
        ...
