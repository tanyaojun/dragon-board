"""兼容门面：快照投影实现已迁至 backend/snapshot_derivation/projection.py。"""

from backend.snapshot_derivation.projection import (  # noqa: F401
    SECTOR_FACTOR_FIELDS,
    _derive_amplitude,
    _derive_limit_prices,
    _enrich_stock_rows_from_quotes,
    _finite_number,
    _first_present,
    _limit_ratio_for,
    _remove_unavailable_placeholder_zeros,
    build_ingest_payload,
)
