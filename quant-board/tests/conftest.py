from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_SNAPSHOT_DB = ROOT / "data" / "warehouse" / "test_quant_board_snapshots_v2.db"
TEST_RESEARCH_DB = ROOT / "data" / "warehouse" / "test_quant_board_research_v2.db"
TEST_THEME_DB = ROOT / "data" / "warehouse" / "test_themeDATA_v8.db"
os.environ["QUANT_BOARD_SNAPSHOT_DATABASE_URL"] = f"sqlite:///{TEST_SNAPSHOT_DB}"
os.environ["QUANT_BOARD_RESEARCH_DATABASE_URL"] = f"sqlite:///{TEST_RESEARCH_DB}"
os.environ["QUANT_BOARD_THEME_DATABASE_URL"] = f"sqlite:///{TEST_THEME_DB}"
os.environ["QUANT_BOARD_STORAGE_BACKEND"] = "sqlite"
os.environ["QUANT_BOARD_MONGODB_DATABASE"] = "dragon_board_quant_pytest"
os.environ["QUANT_BOARD_ENABLE_SUPABASE_BACKUP"] = "0"
os.environ["QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK"] = "0"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
