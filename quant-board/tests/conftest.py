from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_DB = ROOT / "data" / "warehouse" / "test_quant_board.db"
os.environ["QUANT_BOARD_DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["QUANT_BOARD_ENABLE_SUPABASE_BACKUP"] = "0"
os.environ["QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK"] = "0"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
