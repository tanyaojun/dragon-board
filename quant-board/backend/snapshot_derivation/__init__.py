"""快照派生层：原始事实（MarketFactBundle）→ 完整快照（SnapshotBundle）。

派生服务无 I/O；投影实现位于 projection.py（由原 collector builder 迁入）。
"""

from backend.snapshot_derivation.models import MarketFactBundle, SnapshotBundle
from backend.snapshot_derivation.service import SnapshotDerivationService

__all__ = [
    "MarketFactBundle",
    "SnapshotBundle",
    "SnapshotDerivationService",
]
