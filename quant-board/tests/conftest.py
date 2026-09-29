from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_MONGODB_DATABASE = "dragon_board_test"

# ── pytest 环境强制：必须先于任何 backend import（settings._load_env_file 只补缺
#    不覆盖，此处先写死 os.environ 即可压过 .env.local 的生产配置）。
#    硬约束：pytest 所有读写删库动作只允许落在 dragon_board_test 测试库。──
os.environ["QUANT_BOARD_STORAGE_BACKEND"] = "mongodb"
os.environ["QUANT_BOARD_MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["QUANT_BOARD_MONGODB_DATABASE"] = TEST_MONGODB_DATABASE
os.environ["QUANT_BOARD_MONGODB_CONNECT_TIMEOUT_MS"] = "2000"
os.environ["QUANT_BOARD_MONGODB_SERVER_SELECTION_TIMEOUT_MS"] = "2000"
os.environ["QUANT_BOARD_MONGODB_SOCKET_TIMEOUT_MS"] = "30000"
# 测试专属 Redis 前缀，避免污染生产读口缓存键
os.environ["QUANT_BOARD_REDIS_KEY_PREFIX"] = "hellobiga:dragon-board:pytest"
# 2026-09-29 sqlite 链退役：不再注入任何 sqlite URL（pytest 全量不创建/触碰 sqlite 文件）

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

# 目录（模块/方案专项维度）→ marker 映射；类型维度（unit/integration）按文件
# 是否 import fastapi.testclient 自动判定
_DIR_MARKERS = {
    "ranktrend": "ranktrend",
    "theme": "theme",
    "snapshot": "snapshot",
    "snapshot_collector": "collector",
    "hotlist": "hotlist",
    "market": "market",
    "backtest": "backtest",
    "optimization": "optimization",
    "storage": "storage",
    "platform": "platform",
    "research": "research",
}

_import_scan_cache: dict[Path, bool] = {}


def _uses_testclient(path: Path) -> bool:
    if path in _import_scan_cache:
        return _import_scan_cache[path]
    uses = False
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        tree = None
    for node in ast.walk(tree) if tree else []:
        if isinstance(node, ast.Import):
            if any(alias.name == "fastapi.testclient" for alias in node.names):
                uses = True
                break
        elif isinstance(node, ast.ImportFrom) and node.module == "fastapi.testclient":
            uses = True
            break
    _import_scan_cache[path] = uses
    return uses


def pytest_collection_modifyitems(config, items):
    tests_root = ROOT / "tests"
    for item in items:
        path = Path(str(item.fspath))
        try:
            rel = path.relative_to(tests_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) > 1 and parts[0] in _DIR_MARKERS:
            item.add_marker(_DIR_MARKERS[parts[0]])
        item.add_marker("integration" if _uses_testclient(tests_root / rel) else "unit")


@pytest.fixture(scope="session", autouse=True)
def _guard_mongodb_test_database():
    """硬护栏：pytest 会话内配置必须指向 dragon_board_test 的 mongodb 后端，
    Redis 前缀必须是 pytest 专属前缀（2026-09-29 隔离裁决，防生产缓存串写）。"""
    from backend.core.settings import get_settings

    settings = get_settings()
    problems = []
    if settings.storage_backend != "mongodb":
        problems.append(f"storage_backend={settings.storage_backend}")
    if settings.mongodb_database != TEST_MONGODB_DATABASE:
        problems.append(f"mongodb_database={settings.mongodb_database}")
    if not settings.redis_key_prefix.startswith("hellobiga:dragon-board:pytest"):
        problems.append(f"redis_key_prefix={settings.redis_key_prefix}")
    if not settings.mongodb_uri.startswith("mongodb://127.0.0.1"):
        problems.append(f"mongodb_uri={settings.mongodb_uri}")
    if problems:
        pytest.fail(
            "pytest 环境被破坏：" + "；".join(problems)
            + f"（必须 mongodb/{TEST_MONGODB_DATABASE}/pytest 前缀/本机 URI）",
            pytrace=False,
        )
    yield
