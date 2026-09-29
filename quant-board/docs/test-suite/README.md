# QuantBoard 测试体系指南

> 2026-09-29 重构落地 + 同日生产/测试完全隔离与 sqlite 链退役（实施记录见 [2026-09-29-test-restructure-plan.md](2026-09-29-test-restructure-plan.md) 与 [2026-09-29-env-isolation-plan.md](2026-09-29-env-isolation-plan.md)）。

## 目录结构（模块 + 方案专项；类型维度走 marker）

```text
tests/
  conftest.py               # 环境强制(mongodb + dragon_board_test + pytest redis 前缀) + 库护栏 + 收集期自动打标
  fixtures/                 # 共享夹具（helpers.py：BacktestRepoWriter 等）
  ranktrend/                # RankTrend 引擎/因子/门控/tier/观察/回放
  theme/                    # ThemeTrend 题材链
  research/                 # 方案专项：harness/参数扫描/研究批次
  market/                   # 行情代理/资金流/股名/THS/KPL/综合榜
  storage/                  # Mongo 仓库/迁移/备份/归档/清理/隔离护栏/后端切换
  hotlist/                  # 热榜情绪/jev/微信信息差
  snapshot_collector/       # 快照采集器
  snapshot/                 # 快照读口/入库/分析/派生
  backtest/                 # 回测引擎/交易模拟/交易日志
  optimization/             # 优化/搜索/trial/checkpoint
  platform/                 # CLI/导出/运维调度/交易日历/settings 护栏
```

2026-09-29 隔离退役后基线：**2853 用例（收集口径）**，全量热跑约 75 秒；pytest 级 skip 已清零（sqlite 遗留用例随链删除，git 历史可溯）。每个子目录有 `__init__.py`，测试模块是 `tests.<dir>.test_xxx` 包内路径。

## 常用命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest                                   # 全量（热库约 75s）
.\.venv\Scripts\python.exe -m pytest tests/ranktrend                   # 按目录跑专项
.\.venv\Scripts\python.exe -m pytest -m theme                          # 按 marker 跑模块
.\.venv\Scripts\python.exe -m pytest tests/snapshot_collector/test_snapshot_collector_slots.py  # 单文件
.\.venv\Scripts\python.exe -m pytest -m "not integration"              # 只跑不装全应用的轻量层
.\.venv\Scripts\python.exe -m pytest tests/storage -m integration      # 交叉筛选
```

Marker 两类：

- **模块/专项 marker**（11 个，`pytest.ini` 声明）：由顶层 conftest 按文件所在目录在收集期自动打标，手工打标不需要。
- **类型 marker**（自动判定）：文件 import 了 `fastapi.testclient` → `integration`，否则 `unit`。类型维度不落目录，避免目录树过深。

## MongoDB 测试库（硬约束：生产/测试完全隔离）

**pytest 的所有 MongoDB 读写删只允许落在 `dragon_board_test`**，禁止触碰生产库 `dragon_board_quant` 与生产 Redis 前缀。四层防护：

1. `tests/conftest.py` 顶层在任何 backend import 之前强制写死 `QUANT_BOARD_STORAGE_BACKEND=mongodb`、`QUANT_BOARD_MONGODB_DATABASE=dragon_board_test`（压过 `.env.local` 生产配置）、测试专属 Redis 前缀 `hellobiga:dragon-board:pytest`。sqlite URL 注入已删除——pytest 全量不创建任何 sqlite 文件。
2. `backend/data/migrations/mongodb_migration.py::get_mongodb_database()` 运行时护栏：pytest 进程内（存在 `PYTEST_CURRENT_TEST`）连 `dragon_board_quant` 直接 raise；连 `dragon_board_test` 以外的库名同样 raise。该函数是真实 Mongo 连接唯一入口，勿在调用方重复实现护栏。
3. conftest session 级 autouse fixture 复核四项：`storage_backend==mongodb`、`mongodb_database==dragon_board_test`、`redis_key_prefix` 以 `hellobiga:dragon-board:pytest` 开头、`mongodb_uri` 指向本机。
4. `repository_factory.create_repository` 与 `theme_database`：sqlite 分支已物理删除，任何非 mongodb 请求直接 raise；Supabase 备份链已整链删除（备份统一走 R2 对象存储），不存在 pytest 外发通道。

生产侧对称护栏：`settings.storage_backend` 默认 `mongodb`，解析为 sqlite 且未显式 `QUANT_BOARD_ALLOW_SQLITE_BACKEND=1` 时 raise；8000/8001 生产入口 startup fail-fast。

### 测试库形态与重建（手动执行，不进 pytest 链）

测试库为**「空结构 + 基础参照集合」**（29 集合骨架 + `stock_names`/`themes`/`theme_stock_mappings`/`theme_metadata`/`golden_ranktrend_cases` 播种，约 9.4MB），中间产物（frames/records/stock_rows/analysis/backtest 子树等）一律不落测试库——全部 2857 用例对克隆数据零函数级读取（2026-09-29 全量验证），集成用例自带种子。

```powershell
cd quant-board
.\.venv\Scripts\python.exe scripts\clone_mongo_test_db.py                    # --mode structure（默认）：空结构+参照集合播种
.\.venv\Scripts\python.exe scripts\clone_mongo_test_db.py --mode datasets --datasets dragonboard_live --collections snapshot_frames,snapshot_stock_rows
.\.venv\Scripts\python.exe scripts\clone_mongo_test_db.py --mode full        # 历史全量 dump+restore（归档/回滚件用途）
.\.venv\Scripts\python.exe scripts\clone_mongo_test_db.py --prune-residue --execute  # 清理 pytest 跨轮残留（默认 dry-run）
```

- 定向恢复注意：对 archive 做 mongorestore 必须带 `--nsInclude`（`--nsFrom/--nsTo` 只改名不过滤，会把整卷灌回）。
- **pytest 跨轮残留**：真实库写入用例会留下时间戳后缀 dataset；体积增长后跑 `--prune-residue` 手动卫生（pytest 不应删库，不进 pytest 链）。
- **research 锚代际**：`tests/research/*_harness` 的冻结锚期望（fund10 代际）与锚注册表（单一事实源，含 oos2u 新代际）存在 17 处待用户随 10/3 复跑裁决的漂移，属研究数据决策，不在测试基建范围内擅改。

## 验收三断言（隔离完成定义）

1. **回测入生产**：生产 env 产生的 backtest run 落 `dragon_board_quant.backtest_runs`；pytest 会话内同查询只落 `dragon_board_test`。
2. **回归隔离**：conftest 四断言 + `get_mongodb_database` pytest 护栏拒绝其他库名（`tests/storage/test_mongodb_runtime_switch.py`）。
3. **sqlite 退役**：`rg -l "sqlite" quant-board/backend` 仅剩迁移工具读源（`mongodb_migration.py`/`cli migrate-mongodb`）、settings 护栏与 410 桩文案、docstring；全量 pytest 不创建任何 sqlite 文件；`data/warehouse` 无新增 .db（历史 .db 文件待用户授权归档删除）。
