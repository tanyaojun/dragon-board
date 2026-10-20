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


@pytest.fixture(autouse=True)
def _tdx_daily_bars_offline_guard(monkeypatch):
    """硬护栏（AGENTS §1.2-7 延伸）：默认把 TDX 日线/日内棒取数打成空。

    2026-10-16 停牌分辨起，封板链回溯（jiuyan_consecutive_streaks）开始读 TDX 日线
    （区分停牌/断板、补证炸板池缺失日）——不设护栏的话，任何走 N>M 回溯路径的用例都会
    静默连真实通达信节点，单测变慢且结论随上游数据漂移。需要日线的用例在自己的 body 里
    monkeypatch 覆盖（后应用的补丁胜出，见 test_jev_streak_map._suspension_db）。

    **两个模块都要打**：jev_relay_index 是 `from ... import _daily_bars`，在自己模块命名
    空间里持有独立绑定，只补 runner 的那个对它无效（2026-10-16 review 实测：
    test_run_relay_index_day_writes_doc 仍在探真实节点池，5 次外呼）。
    `_intraday_bars` 同族（stock_board_shape_line 的板型行读 5 分钟棒），打 runner 那个。
    """
    from backend.operations import jev_label_jiuyan as _runner
    from backend.operations import jev_relay_index as _relay

    # 真实现在此存档：护栏把模块属性打成空棒，需要测「_daily_bars 自身缓存语义」的用例
    # 从这两个名字取回（见 test_jev_streak_map.test_daily_bars_transient_failure_not_cached）
    _runner._REAL_DAILY_BARS = _runner._daily_bars
    _runner._REAL_INTRADAY_BARS = _runner._intraday_bars
    monkeypatch.setattr(_runner, "_daily_bars", lambda code: [])
    monkeypatch.setattr(_runner, "_intraday_bars", lambda code: [])
    monkeypatch.setattr(_relay, "_daily_bars", lambda code: [])
    _runner._DAILY_BARS_CACHE.clear()
    _runner._INTRA_CACHE.clear()
    yield
    _runner._DAILY_BARS_CACHE.clear()
    _runner._INTRA_CACHE.clear()
    del _runner._REAL_DAILY_BARS
    del _runner._REAL_INTRADAY_BARS


# jev_label_jiuyan 的模块级 IO/叙述缓存（键多为 (dataset, date) 或 code）：pytest 会话内
# 多文件共用进程，同日期不同夹具会互相污染 → 每个用例前后一律清空。
# 2026-10-20 v3.2 审查 P1-1：新增的五个叙事缓存（市场坐标/交易日轴/解析表/昨日板块/THS 池态）
# 必须同批清，否则只有自带 autouse 清理的 test_jev_label_v32_corpus 是隔离的，
# 其余调用 build_pilot_narrative 的文件会串读前一个夹具算出的文本（同日期）。
_JEV_RUNNER_CACHES = (
    "_STREAK_CACHE", "_FACTS_CACHE", "_ADVDEC_CACHE", "_THS_CACHE",
    "_DAILY_BARS_CACHE", "_INTRA_CACHE", "_DIV_LIST_CACHE", "_DIV_FAIL_UNTIL",
    "_MKT_COORD_CACHE", "_DATE_AXIS_CACHE", "_JIYAN_EXPOUND_CACHE",
    "_BOARD_PREV_CACHE", "_THS_STATE_CACHE", "_PREV_TRADING_DATE_CACHE",
)


def _clear_jev_runner_caches(runner) -> None:
    for name in _JEV_RUNNER_CACHES:
        cache = getattr(runner, name, None)
        if cache is not None:
            cache.clear()


@pytest.fixture(autouse=True)
def _clear_io_caches():
    """清 operations/jev_label_jiuyan 的模块级 IO 缓存（_STREAK_CACHE/_FACTS_CACHE/
    _ADVDEC_CACHE/_THS_CACHE/_DAILY_BARS_CACHE/_INTRA_CACHE）——这些缓存按 (dataset, date)
    或 code 键服务于盘后批量，但 pytest 会话内多测试文件共用同一进程，同日期不同夹具会互相污染
    （2026-10-16 streak_map 落地时实测复现：test_jev_streak_map 与
    test_jev_label_raw_material 同用 2026-09-30 夹具串读）。

    _DAILY_BARS_CACHE/_INTRA_CACHE 同批清：2026-10-16 停牌分辨（_traded_dates）开始读
    TDX 日线，漏清会让停牌判定跨用例残留。

    同批清 market_dieban_pool 的东财节流/冷却状态（_em_state）：跨用例残留会让
    后续用例撞上「冷却期内不外呼」而假失败。
    """
    from backend.operations import jev_label_jiuyan as _runner
    from backend.operations import market_dieban_pool as _dieban

    # 除权因子源（百度）的缓存/失败退避也是模块级 IO 状态：残留会让后续用例静默拿到
    # 空事件表而假失败（2026-10-16 实测：test_jev_streak_map 跑完后
    # test_jev_dividend_adjust 的除权解析用例 KeyError）
    _clear_jev_runner_caches(_runner)
    _dieban.reset_em_throttle_state()
    yield
    _clear_jev_runner_caches(_runner)
    _dieban.reset_em_throttle_state()


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
def _em_offline_guard(monkeypatch):
    """硬护栏（AGENTS §1.2-7 延伸）：任何测试路径触到真实东财一律离线失败。

    market_dieban_pool.fetch_limit_down_em 走项目直连的 push2ex 客户端（有节流/冷却），
    但测试忘注入假客户端时会静默打真实上游（2026-10-16 实测复现：backfill 健康检查
    用例真连了 push2ex 并拿到 11 家）。此处把客户端单例换成必失败函数，漏 mock 的
    用例在此显式炸掉；需要模拟东财的用例自行 monkeypatch `_em_http_client` 覆盖。
    """
    from backend.operations import market_dieban_pool as _dieban

    def _boom():
        raise AssertionError("测试禁止真实东财请求：必须 monkeypatch mdp._em_http_client")

    monkeypatch.setattr(_dieban, "_em_http_client", _boom)
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
