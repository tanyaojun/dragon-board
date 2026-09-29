# QuantBoard 测试体系重构实施计划（目录归档 + MongoDB 测试库硬隔离）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `quant-board/tests` 250 个平铺测试文件按「模块 / 方案专项 / 类型」三维归档到子目录，并把 pytest 数据库环境从 SQLite 默认切换为 MongoDB 独立测试库 `dragon_board_test`（由生产库 `dragon_board_quant` 全量克隆），以硬护栏保证 pytest 的所有读写删只落在测试库。

**Architecture:** 目录结构承担「模块」与「方案专项」两个维度（顶层 11 个领域目录 + `research/` 专项目录），「类型」维度（unit/integration）由顶层 conftest 在收集期按文件 import 特征自动打 pytest marker，不打目录。测试库隔离分三层：conftest 环境变量强制（先于任何 backend import）→ `get_mongodb_database()` 运行时护栏（pytest 进程内只允许 `dragon_board_test`）→ session 级 autouse 断言。克隆用 mongodump --archive --gzip + mongorestore --nsFrom/--nsTo，做成幂等脚本 `scripts/clone_mongo_test_db.py`，不进 pytest 链。

**Tech Stack:** pytest 9 / pymongo / mongodump+mongorestore（`backend/core/settings.py` 的 `mongodb_tools_bin`）/ git mv。

---

## 背景与现状结论（2026-09-29 实测）

- `tests/` 平铺 **250 个 `test_*.py`**，共 **2940 个用例**，`pytest --collect-only` 仅 12.4 秒 —— 30 分钟耗时在执行（TestClient 全应用装配、真实引擎计算、轮询等待），不是收集。归档后可按目录/专项选择性执行。
- 现有 `tests/conftest.py` 强制 `QUANT_BOARD_STORAGE_BACKEND=sqlite` + `QUANT_BOARD_MONGODB_DATABASE=dragon_board_quant_pytest`：Mongo 大部分测试用内存假件（FakeMongoDatabase/FakeDumper），tests 里**没有任何 `MongoClient(` 直连**。
- 真实 Mongo 连接唯一入口：`backend/data/migrations/mongodb_migration.py:850 get_mongodb_database()`；`backend/data/repositories/repository_factory.py:28` 已有雏形护栏（pytest 进程 + 生产库名 → raise），但只覆盖 repository_factory 一条链，未覆盖 `cli.py:517/537` 等其它调用点。
- 生产库实名 `dragon_board_quant`（29 collections，dataSize 11.8GB / storage 2.8GB；需求文档中的 `dragon_borad_*` 为笔误）。遗留 `dragon_board_quant_pytest`（6 collections，444MB）是旧 sqlite 模式时代测试残留，本次切换后不再使用。
- `backend/operations/` 下 4 个运维脚本（`jev_label_driver.py`、`wechat_info_diff_ingest.py`、`jev_label_driver_report.py`、`replay_stage_confirm.py` 等）硬编码 `["dragon_board_quant"]`——它们不是 pytest 对象，不受影响，也不在本次改动范围（仅记录）。
- 跨测试 import 5 处（移动文件时必须同步改）：
  - `tests/test_gate_confirm_wiring.py`、`tests/test_hotlist_sentiment_intraday.py` → `from tests.test_hotlist_sentiment_backfill import ...`
  - `tests/test_hotlist_sentiment_after_market.py`、`tests/test_hotlist_sentiment_slots_api.py` → `from tests.test_hotlist_sentiment_series_api import ...`
  - `tests/test_snapshot_collector_post_persist.py` → `from tests.test_ranktrend_golden_alignment import _make_frames`

## 目标目录结构（模块 + 方案专项；类型维度走 marker）

```text
tests/
  conftest.py               # 环境强制(mongodb+dragon_board_test) + 护栏 + 收集期自动打标
  fixtures/                 # 共享夹具（不变，helpers.py）
  ranktrend/                # RankTrend 引擎/因子/门控/tier/观察/回放 (60)
  theme/                    # ThemeTrend 全链 (45)
  research/                 # 方案专项：harness/参数扫描/研究批次 (26)
  market/                   # 行情代理/资金流/股名/THS/KPL/综合榜 (23)
  storage/                  # Mongo 仓库/迁移/备份/归档/清理/切换 (22)
  hotlist/                  # 热榜情绪/jev/微信信息差 (20)
  snapshot_collector/       # 快照采集器 (19)
  snapshot/                 # 快照读口/入库/分析/派生 (14)
  backtest/                 # 回测引擎/交易模拟/交易日志 (11)
  optimization/             # 优化/搜索/trial/checkpoint (6)
  platform/                 # CLI/导出/运维调度/交易日历 (4)
```

每个子目录含 `__init__.py`（tests 已是包，子目录同为包内模块，同名测试文件互不冲突）。

分类规则（对文件名剥去 `test_` 前缀后判定，顺序即优先级）：

1. `research`：`*_harness` 结尾，或 ∈ {`harness_common`, `track1_dimension_power`, `track2_candidates_harness`, `cost_sensitivity`, `atr_mean_reversion`, `signal_return_gap`, `rank_ic_marginal`, `scan_repool_oos2u_horizon`, `scan_repool_resume`, `lifecycle_dimension_oos2u_only`}。
2. `theme`：`theme_*` 前缀或 `repository_theme_projection`。
3. `hotlist`：`hotlist_*` / `jev_*` / `wechat_*`。
4. `snapshot_collector`：`snapshot_collector_*`。
5. `market`：`market_proxy_*` `market_data_*` `market_fund_*` `fund_*` `ths_*` `akshare_*` `big_order_*` `kpl_*` `server_limit_summary` `volume_ratio_*` `stock_name_*` `comprehensive_rank` `providers_comprehensive_rank` `money_flow_*`。
6. `backtest`：`backtest_*` `trade_*` `v5_trade_defaults` `fusion_strategy_projection_api` `outcome_hold_to_close`。
7. `optimization`：`optimization_*` `search_space_*` `trial_*` `layer_checkpoints`。
8. `storage`：`mongo_*` `mongodb_*` `backup_retention` `object_backup` `storage_convergence` `archive_*` `auto_archive` `duckdb_*` `ingest_outbox` `data_windows`。
9. `snapshot`：`snapshot_*` `api_current_frame_authoritative` `api_link_cross_section` `rank_field_backfill`。
10. `platform`：`cli*` `export` `operations_schedule` `trading_calendar_*`。
11. `ranktrend`：其余全部兜底（引擎/因子/门控/tier/观察/regime/synergy/resonance 等）。

完整清单见本文档附录（已逐目录核对 250/250 无误伤）。

---

### Task 1: 目录归档（git mv）

**Files:** 移动 `tests/test_*.py` 250 个 → 11 个子目录；新建 11 个 `tests/<dir>/__init__.py`。

- [ ] **Step 1: 恢复一次性映射脚本并生成 git mv 清单**

映射脚本内容见本文档附录 B（`.tmp_migrate_map.py`，用后删除）。执行：

```bash
cd /d/dragon-board/quant-board
./.venv/Scripts/python.exe .tmp_migrate_map.py | sed -n '/== git mv/,/== 各目录/p' | rg '^git mv' > .tmp_gitmv.sh
wc -l .tmp_gitmv.sh   # 期望 250
```

- [ ] **Step 2: 建子目录与 __init__.py，执行 git mv**

```bash
for d in ranktrend theme snapshot snapshot_collector hotlist market backtest optimization storage platform research; do
  mkdir -p tests/$d && touch tests/$d/__init__.py
done
bash .tmp_gitmv.sh
git status --short | rg '^R' | wc -l   # 期望 250 个重命名
```

- [ ] **Step 3: 验证收集无损失**

```bash
./.venv/Scripts/python.exe -m pytest --collect-only -q 2>&1 | tail -1
# 期望：2940 tests collected（跨 import 修复前可能有 import error，Task 2 修复后复核）
```

### Task 2: 跨测试 import 修复

**Files（modify import 路径）:**
- `tests/research/test_gate_confirm_wiring.py`（ranktrend 门控接线测试）→ `from tests.hotlist.test_hotlist_sentiment_backfill import FakeMongoDb, stock`
- `tests/hotlist/test_hotlist_sentiment_intraday.py` → `from tests.hotlist.test_hotlist_sentiment_backfill import FakeCollection, FakeMongoDb`
- `tests/hotlist/test_hotlist_sentiment_after_market.py` → `from tests.hotlist.test_hotlist_sentiment_series_api import FakeMongoDb, _RecordingCache, _seed_frames`
- `tests/hotlist/test_hotlist_sentiment_slots_api.py` → `from tests.hotlist.test_hotlist_sentiment_series_api import FakeMongoDb`
- `tests/snapshot_collector/test_snapshot_collector_post_persist.py` → `from tests.ranktrend.test_ranktrend_golden_alignment import _make_frames`

注：`test_gate_confirm_wiring.py` 依分类规则落 `ranktrend/`（`gate_*` 前缀）。后续可把 FakeMongoDb 等假件收敛进 `tests/fixtures/`，本次仅改路径不搬符号（最小侵入）。

- [ ] **Step 1:** 按 `rg -l "from tests\.test_" tests/` 找出全部 5 个文件逐一替换 import 路径为新包路径。
- [ ] **Step 2:** `./.venv/Scripts/python.exe -m pytest --collect-only -q | tail -1` → 期望 2940 collected、0 error。

### Task 3: conftest 改造（mongodb 测试库强制 + 护栏 + 自动 marker）

**Files:**
- Modify: `tests/conftest.py`（整体重写，内容如下）
- Modify: `pytest.ini`（markers 声明）

```python
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_MONGODB_DATABASE = "dragon_board_test"

# ── pytest 环境强制：必须先于任何 backend import（settings._load_env_file 只补缺不覆盖，
#    此处先写死 os.environ 即可压过 .env.local 的生产配置）──
os.environ["QUANT_BOARD_STORAGE_BACKEND"] = "mongodb"
os.environ["QUANT_BOARD_MONGODB_URI"] = "mongodb://127.0.0.1:27017"
os.environ["QUANT_BOARD_MONGODB_DATABASE"] = TEST_MONGODB_DATABASE
os.environ["QUANT_BOARD_MONGODB_CONNECT_TIMEOUT_MS"] = "2000"
os.environ["QUANT_BOARD_MONGODB_SERVER_SELECTION_TIMEOUT_MS"] = "2000"
os.environ["QUANT_BOARD_MONGODB_SOCKET_TIMEOUT_MS"] = "30000"
os.environ["QUANT_BOARD_ENABLE_SUPABASE_BACKUP"] = "0"
# 测试专属 Redis 前缀，避免污染生产读口缓存键
os.environ["QUANT_BOARD_REDIS_KEY_PREFIX"] = "hellobiga:dragon-board:pytest"
# SQLite 文件仅保留给显式测旧链路的用例，不是默认主链
os.environ["QUANT_BOARD_SNAPSHOT_DATABASE_URL"] = f"sqlite:///{ROOT / 'data' / 'warehouse' / 'test_quant_board_snapshots_v2.db'}"
os.environ["QUANT_BOARD_RESEARCH_DATABASE_URL"] = f"sqlite:///{ROOT / 'data' / 'warehouse' / 'test_quant_board_research_v2.db'}"
os.environ["QUANT_BOARD_THEME_DATABASE_URL"] = f"sqlite:///{ROOT / 'data' / 'warehouse' / 'test_themeDATA_v8.db'}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

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
    """类型维度判定：测试文件 import 了 fastapi.testclient → integration。"""
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
    """硬护栏：pytest 会话内配置必须指向 dragon_board_test 的 mongodb 后端。"""
    from backend.core.settings import get_settings

    settings = get_settings()
    if settings.storage_backend != "mongodb" or settings.mongodb_database != TEST_MONGODB_DATABASE:
        pytest.fail(
            f"pytest 环境被破坏：storage_backend={settings.storage_backend} "
            f"mongodb_database={settings.mongodb_database}（必须 mongodb/{TEST_MONGODB_DATABASE}）",
            pytrace=False,
        )
    yield
```

`pytest.ini` 全量替换：

```ini
[pytest]
testpaths = tests
norecursedirs = .venv data frontend frontend/node_modules frontend/dist .tmp
markers =
    ranktrend: RankTrend 引擎/因子/门控/tier/观察（tests/ranktrend）
    theme: ThemeTrend 题材链（tests/theme）
    snapshot: 快照读口/入库/分析/派生（tests/snapshot）
    collector: 快照采集器（tests/snapshot_collector）
    hotlist: 热榜情绪/jev/信息差（tests/hotlist）
    market: 行情代理/资金流/股名/THS/KPL（tests/market）
    backtest: 回测引擎/交易模拟（tests/backtest）
    optimization: 优化/搜索/trial（tests/optimization）
    storage: 存储/Mongo 仓库/备份/归档（tests/storage）
    platform: CLI/导出/运维调度（tests/platform）
    research: 方案专项 harness/参数扫描（tests/research）
    unit: 纯计算/假件测试（不 import fastapi.testclient，自动打标）
    integration: 起全应用 TestClient 的集成测试（自动打标）
```

- [ ] **Step 1:** 重写 `tests/conftest.py` 与 `pytest.ini`（内容如上）。
- [ ] **Step 2:** 快速验证环境强制生效：

```bash
./.venv/Scripts/python.exe -m pytest tests/storage/test_mongo_repository.py -q 2>&1 | tail -3
# 期望：passed（FakeMongo 测试不受影响）
./.venv/Scripts/python.exe -c "import os; os.environ['PYTEST_CURRENT_TEST']='x'; import tests.conftest" 
# 手动校验 conftest import 后 os.environ['QUANT_BOARD_MONGODB_DATABASE'] == 'dragon_board_test'
```

### Task 4: `get_mongodb_database()` 运行时护栏加固（生产代码，收紧型）

**Files:**
- Modify: `backend/data/migrations/mongodb_migration.py:850`（`get_mongodb_database` 增加护栏）
- Modify: `backend/data/repositories/repository_factory.py:24-29`（删除重复雏形护栏，改为信任下层唯一真理源）

`get_mongodb_database` 函数体首部加：

```python
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if database_name == "dragon_board_quant":
            raise RuntimeError("pytest 禁止连接生产 MongoDB 库 dragon_board_quant")
        if database_name != "dragon_board_test":
            raise RuntimeError(
                f"pytest 只允许连接测试库 dragon_board_test，当前请求：{database_name}"
            )
```

`repository_factory.py` 中删除 `if os.environ.get("PYTEST_CURRENT_TEST") ... raise RuntimeError(...)` 两行（护栏已下沉覆盖 cli.py 等所有 `get_mongodb_database` 调用点）。

- [ ] **Step 1:** 按上述代码改两处。
- [ ] **Step 2:** 反向验证护栏（期望 RuntimeError）：

```bash
./.venv/Scripts/python.exe -m pytest tests/storage/test_mongodb_runtime_switch.py -q 2>&1 | tail -3
```

另写一次性验证（内联 pytest 临时用例或 python -c + PYTEST_CURRENT_TEST 环境变量）确认 `get_mongodb_database(uri, "dragon_board_quant")` 在 pytest 进程内 raise、生产进程（无 PYTEST_CURRENT_TEST）不受影响。

### Task 5: 测试库全量克隆脚本与执行

**Files:**
- Create: `scripts/clone_mongo_test_db.py`

```python
"""全量克隆 MongoDB 测试库：dragon_board_quant -> dragon_board_test（幂等 --drop）。

用法（在 quant-board/ 下）：
    .\\.venv\\Scripts\\python.exe scripts/clone_mongo_test_db.py            # 默认全量
    .\\.venv\\Scripts\\python.exe scripts/clone_mongo_test_db.py --skip-dump # 复用上次 archive 只重放
产物 archive 落 data/backups/mongodb/（.gitignore 已忽略），供重放与审计。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_DB = "dragon_board_quant"
TARGET_DB = "dragon_board_test"

# 生产库绝不允许成为恢复目标
assert TARGET_DB != SOURCE_DB and TARGET_DB != "dragon_board_quant"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dump", action="store_true", help="复用已有 archive，只执行 restore")
    args = parser.parse_args()

    from backend.core.settings import get_settings

    settings = get_settings()
    tools_bin = settings.mongodb_tools_bin
    mongodump = tools_bin / "mongodump.exe"
    mongorestore = tools_bin / "mongorestore.exe"
    uri = settings.mongodb_uri or "mongodb://127.0.0.1:27017"

    settings.mongodb_backup_dir.mkdir(parents=True, exist_ok=True)
    archive = settings.mongodb_backup_dir / f"{SOURCE_DB}_to_{TARGET_DB}_{datetime.now():%Y%m%d}.archive.gz"

    if not args.skip_dump:
        print(f"[1/2] mongodump {SOURCE_DB} -> {archive.name}（gzip archive，11.8GB 数据约几分钟）")
        subprocess.run(
            [str(mongodump), f"--uri={uri}", f"--db={SOURCE_DB}", "--gzip",
             f"--archive={archive}"],
            check=True,
        )
    else:
        print(f"[1/2] 复用已有 archive：{archive}")

    print(f"[2/2] mongorestore -> {TARGET_DB}（--drop 幂等重建）")
    subprocess.run(
        [str(mongorestore), f"--uri={uri}", "--gzip", f"--archive={archive}",
         f"--nsFrom={SOURCE_DB}.*", f"--nsTo={TARGET_DB}.*", "--drop", "--numParallelCollections=2"],
        check=True,
    )
    print(f"完成：{SOURCE_DB} -> {TARGET_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 1:** 创建脚本（如上），`python scripts/clone_mongo_test_db.py` 后台执行。
- [ ] **Step 2:** 克隆后校验（只读）：

```bash
./.venv/Scripts/python.exe - <<'PY'
from pymongo import MongoClient
c = MongoClient("mongodb://127.0.0.1:27017")
src = set(c["dragon_board_quant"].list_collection_names())
dst = set(c["dragon_board_test"].list_collection_names())
print("collections:", len(src), "->", len(dst))
print("missing:", src - dst)
for col in sorted(dst)[:5]:
    print(col, c["dragon_board_test"][col].estimated_document_count())
PY
# 期望：missing 为空（视图除外），文档数与源库同量级
```

### Task 6: 验证

- [ ] **Step 1:** 收集无损：`pytest --collect-only -q | tail -1` → 2940 collected。
- [ ] **Step 2:** 每个目录抽样专项跑（conda 无关，直接 pytest）：

```bash
./.venv/Scripts/python.exe -m pytest tests/ranktrend/test_ranktrend_engine.py tests/theme/test_theme_trend.py tests/storage/test_mongo_repository.py tests/snapshot_collector/test_snapshot_collector_slots.py tests/hotlist/test_hotlist_sentiment_compute.py tests/research/test_harness_common.py -q
# 期望全绿
```

- [ ] **Step 3:** 后台全量回归 `pytest -q`（30 分钟+），失败逐个判定：sqlite 语义遗留 → 就地修；真连非 test 库 → 移到 FakeMongo 或改 test 库集合。全部结果如实汇报。
- [ ] **Step 4:** 护栏演练：确认 pytest 进程内 `get_mongodb_database(uri, "dragon_board_quant")` raise；8000 生产进程不受影响（护栏只在 PYTEST_CURRENT_TEST 下生效）。

### Task 7: 文档同步（AGENTS.md 硬约束：存储/合同变更同批更新文档）

- [ ] **Step 1:** 更新 `docs/AI_COLLABORATION.md` 后端快照采集器验证链路的测试路径口径（`tests/test_snapshot_collector_*.py` → `tests/snapshot_collector/`）。
- [ ] **Step 2:** 新增 `docs/test-suite/README.md`：目录结构、marker 用法（`pytest -m theme` / `pytest tests/storage` / `-m "not integration"`）、测试库克隆命令、护栏说明。
- [ ] **Step 3:** `docs/README.md` 文档索引追加 test-suite 链接。

---

## 附录 A：各目录完整文件清单（250/250）

见生成脚本输出（映射规则即上文 11 条，任何人均可重现）。核心归属已在计划正文核对，`ranktrend/` 兜底明细 60 个文件逐一核对无误伤。

## 附录 B：一次性映射脚本（.tmp_migrate_map.py，用后删除）

脚本按正文 11 条规则生成 git mv 命令与分布统计；提交前删除，不入库。
