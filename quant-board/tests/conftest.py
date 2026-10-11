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

# 2026-10-10 jev 真实通道隔离（红线 §1.2.7）：pytest 进程禁带任何真实 jev 凭据。
# settings._load_env_file 只补缺不覆盖，此处先写死空值即可压过 .env.local 的生产 key；
# 否则 _dispatch_jev 检测到 JEV_TYPESAFE_KEY 会绕过测试 monkeypatch 直连真实模型。
os.environ["JEV_TYPESAFE_KEY"] = ""
os.environ["JEV_CF_TOKEN"] = ""
os.environ.pop("JEV_TYPESAFE_PROXY", None)
os.environ.pop("JEV_CF_ACCOUNT", None)

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


@pytest.fixture(autouse=True)
def _forbid_real_jev_calls(monkeypatch):
    """硬护栏（AGENTS §1.2-7）：任何测试触发真实 jev 端点立即显式失败，
    而不是默默烧 token。漏 mock 的测试在此拦下（fail-visible）。"""
    import urllib.request as _urllib_request

    real_urlopen = _urllib_request.urlopen

    def _guarded_urlopen(req, *args, **kwargs):
        url = req.full_url if isinstance(req, _urllib_request.Request) else str(req)
        if any(host in url for host in ("api.cloudflare.com", "gateway.ai.cloudflare.com")):
            raise AssertionError(
                f"测试禁止真实 jev 调用（AGENTS §1.2-7）：必须 monkeypatch call_jev。url={url[:120]}")
        return real_urlopen(req, *args, **kwargs)

    monkeypatch.setattr(_urllib_request, "urlopen", _guarded_urlopen)
    yield


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


@pytest.fixture(autouse=True)
def _akshare_offline_stub(monkeypatch):
    """P1-1 review（2026-10-11）：任何测试路径触到 akshare 一律改为离线失败。

    除权日程取数（_div_event_list）捕获异常后回退原口径——把「测试意外触网」从静默外呼
    变为干净的离线回退，根绝 AGENTS §1.2-7 延伸违规；需要模拟百度日程的测试在用例内
    自行 monkeypatch.setitem(sys.modules, "akshare", fake) 覆盖本 stub（LIFO 还原）。
    """
    import types

    fake = types.ModuleType("akshare")

    def _offline(*_a, **_k):
        raise RuntimeError("akshare offline stub（测试禁网）")

    for name in ("news_trade_notify_dividend_baidu", "stock_zh_a_hist",
                 "stock_zh_a_hist_tx", "stock_zh_a_daily"):
        setattr(fake, name, _offline)
    monkeypatch.setitem(sys.modules, "akshare", fake)
