# MongoDB Backtest Report Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 QuantBoard 大型回测报告导出避开一次性超大 JSON 聚合，并补齐 MongoDB 读写热路径的最小性能优化与验收。

**Architecture:** 新增流式报告导出能力，默认输出 `jsonl-bundle`，保留旧 `legacy-json` 兼容模式。报告明细从归一化集合迭代读取，`backtest_runs.resultCompressed` 和 `backtest_result_chunks` 只作为兼容完整结果追溯。MongoDB 写入侧先做低风险优化，避免新 run 明细保存前的无意义 `count_documents`。

**Tech Stack:** Python 3, FastAPI service layer, PyMongo repository, existing QuantBoard CLI, pytest.

---

## 影响文件

- Modify: `quant-board/backend/data/repository.py`
  - 为 SQLite/default repository 增加 `iter_backtest_trades()`、`iter_backtest_equity_curve()`、`iter_backtest_signals()` 默认方法，先复用现有列表读取，保证接口一致。
- Modify: `quant-board/backend/data/mongo_research_repository.py`
  - 增加 Mongo cursor 迭代读取方法。
  - 为 `save_backtest_signal_rows()`、`save_backtest_signals()`、`save_backtest_trades()`、`save_backtest_equity_curve()` 增加 `append: bool = True` 或等价内部参数；新 run 调用时跳过 `count_documents`。
- Modify: `quant-board/backend/data/mongodb_migration.py`
  - 补齐 `backtest_trades`、`backtest_equity_curve` 的 `{ backtestRunId, sequence }` 索引定义，并确认 `backtest_signals` 已覆盖同类索引。
- Modify: `quant-board/backend/services.py`
  - 新增 `BacktestService.export_report_bundle()` 和 `BacktestService.export_report_gzip()`。
  - 保留 `export_report()` 作为兼容完整报告入口。
  - 在 RankTrend、ThemeTrend、ThemeConfluence 新 run 保存明细时使用非追加模式。
- Modify: `quant-board/backend/cli.py`
  - `export-report` 增加 `--format jsonl-bundle|json.gz|legacy-json`，默认 `jsonl-bundle`。
  - 默认路径为目录时输出 bundle；`legacy-json` 保留现有写法。
- Modify: `quant-board/docs/api-cli.md`
  - 更新 CLI 文档和报告格式说明。
- Modify: `quant-board/docs/architecture.md`
  - 补充流式报告导出与归一化集合优先级。
- Modify: `quant-board/docs/mongodb-migration-plan.md`
  - 同步新增 sequence 排序索引和报告导出主路径说明。
- Test: `quant-board/tests/test_quant_board.py`
  - 覆盖 CLI 参数解析和小型 bundle 导出。
- Test: `quant-board/tests/test_mongo_research_repository.py`
  - 覆盖 Mongo iterator 顺序和非追加保存跳过前置 count 的行为。

## Task 1: CLI 格式参数和兼容入口

**Files:**
- Modify: `quant-board/backend/cli.py`
- Test: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: 写失败测试，确认默认格式为 `jsonl-bundle`**

在 `quant-board/tests/test_quant_board.py` 的 `export-report` 参数解析测试附近增加断言：

```python
export_args = parser.parse_args([
    "export-report",
    "--run-id",
    "bt_1",
    "--output",
    str(tmp_path / "bt_1"),
])
assert export_args.func.__name__ == "cmd_export_report"
assert export_args.format == "jsonl-bundle"
```

- [ ] **Step 2: 写失败测试，确认兼容格式可解析**

在同一测试函数中追加：

```python
legacy_args = parser.parse_args([
    "export-report",
    "--run-id",
    "bt_1",
    "--output",
    str(tmp_path / "bt_1.json"),
    "--format",
    "legacy-json",
])
assert legacy_args.format == "legacy-json"

gzip_args = parser.parse_args([
    "export-report",
    "--run-id",
    "bt_1",
    "--output",
    str(tmp_path / "bt_1.json.gz"),
    "--format",
    "json.gz",
])
assert gzip_args.format == "json.gz"
```

- [ ] **Step 3: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k export_report -q
```

Expected: FAIL，原因是 `args.format` 尚不存在。

- [ ] **Step 4: 实现 CLI 参数**

在 `quant-board/backend/cli.py` 的 `export_cmd` 定义处，将 help 从旧的 full JSON 描述改成报告导出描述，并增加格式参数：

```python
export_cmd = sub.add_parser("export-report", help="Export a backtest report")
export_cmd.add_argument(
    "--format",
    choices=("jsonl-bundle", "json.gz", "legacy-json"),
    default="jsonl-bundle",
    help="Report export format. Defaults to jsonl-bundle for large backtests.",
)
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k export_report -q
```

Expected: PASS.

## Task 2: Repository 迭代读取接口

**Files:**
- Modify: `quant-board/backend/data/repository.py`
- Modify: `quant-board/backend/data/mongo_research_repository.py`
- Test: `quant-board/tests/test_mongo_research_repository.py`

- [ ] **Step 1: 补齐 FakeCursor 的 batch API**

在 `quant-board/tests/test_mongo_research_repository.py` 的 `FakeCursor` 测试替身中增加：

```python
def batch_size(self, size: int):
    self.batch_size_value = size
    return self
```

该步骤只补测试替身能力，不改变生产代码。

- [ ] **Step 2: 写 Mongo iterator 顺序测试**

在 `quant-board/tests/test_mongo_research_repository.py` 中基于现有 `get_backtest_signals` 测试增加。测试数据必须显式保存乱序 `sequence` 或使用现有 fixture 中已能证明排序的 rows：

```python
rows = list(repo.iter_backtest_signals("bt_1", batch_size=2))
assert [row["code"] for row in rows] == ["000003", "000001", "000002"]
assert [row["sequence"] for row in rows] == [1, 2, 3]
```

同文件先保存 trades/equity 测试数据，再增加最小顺序断言：

```python
repo.save_backtest_trades("bt_1", [{"code": "000001"}, {"code": "000002"}])
repo.save_backtest_equity_curve("bt_1", [{"timestamp": "t1"}, {"timestamp": "t2"}])
```

```python
assert [row["sequence"] for row in repo.iter_backtest_trades("bt_1", batch_size=2)] == [1, 2]
assert [row["sequence"] for row in repo.iter_backtest_equity_curve("bt_1", batch_size=2)] == [1, 2]
```

- [ ] **Step 3: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py -k "iter_backtest" -q
```

Expected: FAIL，原因是 iterator 方法尚不存在。

- [ ] **Step 4: 在默认 repository 增加兼容 iterator**

在 `quant-board/backend/data/repository.py` 的研究 repository 类中增加：

```python
def iter_backtest_trades(self, run_id: str, batch_size: int = 1000):
    yield from self.get_backtest_trades(run_id)

def iter_backtest_equity_curve(self, run_id: str, batch_size: int = 1000):
    yield from self.get_backtest_equity_curve(run_id)

def iter_backtest_signals(self, run_id: str, batch_size: int = 1000):
    yield from self.get_backtest_signals(run_id)
```

如果类中已有相近命名，复用现有命名风格，不新增抽象基类。

- [ ] **Step 5: 在 Mongo repository 增加 cursor iterator**

在 `quant-board/backend/data/mongo_research_repository.py` 中增加：

```python
def iter_backtest_trades(self, run_id: str, batch_size: int = 1000):
    cursor = (
        self.db["backtest_trades"]
        .find({"backtestRunId": run_id})
        .sort([("sequence", 1)])
        .batch_size(batch_size)
    )
    for row in cursor:
        yield self._drop_mongo_id(row)

def iter_backtest_equity_curve(self, run_id: str, batch_size: int = 1000):
    cursor = (
        self.db["backtest_equity_curve"]
        .find({"backtestRunId": run_id})
        .sort([("sequence", 1)])
        .batch_size(batch_size)
    )
    for row in cursor:
        yield self._drop_mongo_id(row)

def iter_backtest_signals(self, run_id: str, batch_size: int = 1000):
    cursor = (
        self.db["backtest_signals"]
        .find({"backtestRunId": run_id})
        .sort([("sequence", 1)])
        .batch_size(batch_size)
    )
    for row in cursor:
        yield self._drop_mongo_id(row)
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py -k "iter_backtest" -q
```

Expected: PASS.

## Task 3: Bundle 报告导出服务

**Files:**
- Modify: `quant-board/backend/services.py`
- Test: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: 写 bundle 导出测试**

在 `quant-board/tests/test_quant_board.py` 中新增一个使用临时 repository/session 的服务测试。测试应构造一个小型 run，保存 trades/equity/signals 后调用：

```python
summary = BacktestService(session).export_report_bundle("bt_1", tmp_path / "bt_1")
assert summary["ok"] is True
assert summary["format"] == "jsonl-bundle"
assert (tmp_path / "bt_1" / "manifest.json").exists()
assert (tmp_path / "bt_1" / "signals.jsonl").exists()
assert (tmp_path / "bt_1" / "trades.jsonl").exists()
assert (tmp_path / "bt_1" / "equity_curve.jsonl").exists()
assert (tmp_path / "bt_1" / "quality_report.json").exists()
```

读取 `manifest.json` 验证：

```python
manifest = json.loads((tmp_path / "bt_1" / "manifest.json").read_text(encoding="utf-8"))
assert manifest["runId"] == "bt_1"
assert manifest["files"]["signals"]["rows"] == 2
assert manifest["files"]["qualityReport"]["path"] == "quality_report.json"
```

- [ ] **Step 2: 写大报告流式回归测试**

新增 fake repository 或使用现有测试替身，构造 100_000 条 signals iterator。测试只验证行数与文件存在，不要求一次性读回全部 JSONL：

```python
summary = BacktestService(session).export_report_bundle("bt_large", tmp_path / "bt_large")
manifest = json.loads((tmp_path / "bt_large" / "manifest.json").read_text(encoding="utf-8"))
assert summary["format"] == "jsonl-bundle"
assert manifest["files"]["signals"]["rows"] == 100_000
with (tmp_path / "bt_large" / "signals.jsonl").open("r", encoding="utf-8") as handle:
    assert sum(1 for _ in handle) == 100_000
```

该测试的 fake repository 不应实现或调用 `export_report()` 完整聚合路径；目的在于防止回归到“一次性组装大 dict”。

- [ ] **Step 3: 写原子落盘失败测试**

构造一个 iterator 在第二行抛出异常：

```python
def broken_rows():
    yield {"sequence": 1}
    raise RuntimeError("simulated export failure")
```

调用 bundle 导出后断言：

```python
with pytest.raises(RuntimeError, match="simulated export failure"):
    BacktestService(session).export_report_bundle("bt_broken", tmp_path / "bt_broken")
assert not (tmp_path / "bt_broken" / "manifest.json").exists()
```

如果实现选择临时目录，允许临时目录存在，但最终输出目录不能出现可用 `manifest.json`。

- [ ] **Step 4: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k "export_report_bundle" -q
```

Expected: FAIL，原因是 `export_report_bundle` 尚不存在。

- [ ] **Step 5: 实现 JSONL 写辅助函数**

在 `quant-board/backend/services.py` 中新增私有方法：

```python
@staticmethod
def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json_dumps(row))
            handle.write("\n")
            count += 1
    return count
```

如当前文件未导入 `Path`、`Iterable` 或 `json_dumps`，按现有 import 风格补齐。若 `json_dumps` 已可用，复用它以保持 JSON 输出风格一致。

- [ ] **Step 6: 实现 `export_report_bundle()`**

在 `BacktestService` 中新增：

```python
def export_report_bundle(self, run_id: str, output: Path) -> dict[str, Any]:
    run = self.repo.get_backtest_run(run_id)
    if not run:
        return {"ok": False, "error": {"code": "backtest_run_not_found", "runId": run_id}}

    tmp_output = output.with_name(f"{output.name}.tmp")
    tmp_output.mkdir(parents=True, exist_ok=True)
    for name in ("signals.jsonl", "trades.jsonl", "equity_curve.jsonl", "quality_report.json", "result_summary.json", "manifest.json"):
        path = tmp_output / name
        if path.exists():
            path.unlink()
    result = loads_json_field(run.result_json, {})
    request = loads_json_field(run.request_json, {})

    signals_count = self._write_jsonl(tmp_output / "signals.jsonl", self.repo.iter_backtest_signals(run_id))
    trades_count = self._write_jsonl(tmp_output / "trades.jsonl", self.repo.iter_backtest_trades(run_id))
    equity_count = self._write_jsonl(tmp_output / "equity_curve.jsonl", self.repo.iter_backtest_equity_curve(run_id))
    quality_report = self.repo.get_backtest_quality_report(run_id)
    (tmp_output / "quality_report.json").write_text(json_dumps(quality_report or {}), encoding="utf-8")

    summary = {
        "runId": run.id,
        "datasetId": run.dataset_id,
        "snapshotType": run.snapshot_type,
        "strategyName": run.strategy_name,
        "strategyVersion": run.strategy_version,
        "configHash": run.config_hash,
        "randomSeed": run.random_seed,
        "metrics": {metric: self._metric_value(result, metric) for metric in sorted(BACKTEST_COMPARE_METRICS)},
        "request": request,
    }
    (tmp_output / "result_summary.json").write_text(json_dumps(summary), encoding="utf-8")

    manifest = {
        "ok": True,
        "format": "jsonl-bundle",
        "runId": run.id,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "files": {
            "manifest": {"path": "manifest.json"},
            "resultSummary": {"path": "result_summary.json"},
            "qualityReport": {"path": "quality_report.json", "present": quality_report is not None},
            "signals": {"path": "signals.jsonl", "rows": signals_count},
            "trades": {"path": "trades.jsonl", "rows": trades_count},
            "equityCurve": {"path": "equity_curve.jsonl", "rows": equity_count},
        },
    }
    (tmp_output / "manifest.json").write_text(json_dumps(manifest), encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("signals.jsonl", "trades.jsonl", "equity_curve.jsonl", "quality_report.json", "result_summary.json"):
        (tmp_output / name).replace(output / name)
    (tmp_output / "manifest.json").replace(output / "manifest.json")
    return manifest
```

如果 `services.py` 已有等价时间、JSON 或临时文件 helper，复用现有 helper，不新增重复工具。实现只能替换本导出器管理的固定文件名，不得删除输出目录中的未知文件。

- [ ] **Step 7: 运行测试确认通过**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k "export_report_bundle" -q
```

Expected: PASS.

## Task 4: CLI 接入 bundle、gzip 和 legacy

**Files:**
- Modify: `quant-board/backend/cli.py`
- Test: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: 写 CLI 行为测试**

为 `cmd_export_report` 增加 monkeypatch 测试，确认：

```python
args.format == "jsonl-bundle"
```

时调用 `BacktestService.export_report_bundle()`；`legacy-json` 时调用现有 `export_report()`。

- [ ] **Step 2: 写 gzip 流式导出测试**

新增服务测试，调用：

```python
summary = BacktestService(session).export_report_gzip("bt_1", tmp_path / "bt_1.json.gz")
assert summary["ok"] is True
assert summary["format"] == "json.gz"
```

用 gzip 读回并验证 JSON 结构：

```python
with gzip.open(tmp_path / "bt_1.json.gz", "rt", encoding="utf-8") as handle:
    payload = json.load(handle)
assert payload["runId"] == "bt_1"
assert "qualityReport" in payload
assert [row["sequence"] for row in payload["signals"]] == [1, 2]
```

该测试只使用小数据集验证结构；大数据稳定性由 Task 3 的 100k bundle 测试覆盖。

- [ ] **Step 3: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k "cmd_export_report" -q
```

Expected: FAIL，原因是 CLI 尚未按 format 分派。

- [ ] **Step 4: 改造 `cmd_export_report()`**

将 `cmd_export_report()` 改为：

```python
def cmd_export_report(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        service = BacktestService(session)
        output = Path(args.output)
        if args.format == "jsonl-bundle":
            result = service.export_report_bundle(args.run_id, output)
            print_json({**result, "output": str(output)})
            if not result.get("ok"):
                sys.exit(1)
            return
        if args.format == "json.gz":
            result = service.export_report_gzip(args.run_id, output)
            print_json({**result, "output": str(output)})
            if not result.get("ok"):
                sys.exit(1)
            return

        report = service.export_report(args.run_id)
        if report is None:
            print_json({"ok": False, "error": {"code": "backtest_run_not_found", "runId": args.run_id}})
            sys.exit(1)
        report = {**report, "exportedAt": datetime.now(timezone.utc).isoformat()}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print_json({"ok": True, "runId": args.run_id, "format": "legacy-json", "output": str(output)})
```

- [ ] **Step 5: 实现 gzip 流式导出**

在 `BacktestService` 中新增 `export_report_gzip()`。用 `gzip.open(tmp_output, "wt", encoding="utf-8")` 按 JSON token 写入，不先构造完整报告 dict。输出结构固定为：

```json
{
  "runId": "bt_1",
  "datasetId": "...",
  "snapshotType": "half_hour",
  "strategyName": "...",
  "strategyVersion": "...",
  "configHash": "...",
  "randomSeed": 0,
  "request": {},
  "metrics": {},
  "qualityReport": {},
  "trades": [],
  "equityCurve": [],
  "signals": []
}
```

实现时为每个数组写入 `[`，逐行遍历 iterator，用逗号连接元素，最后写 `]`。成功关闭 gzip 后用 `tmp_output.replace(output)` 替换最终文件。

- [ ] **Step 6: 运行测试确认通过**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_quant_board.py -k "cmd_export_report or export_report_bundle" -q
```

Expected: PASS.

## Task 5: 新 run 明细保存跳过前置 count

**Files:**
- Modify: `quant-board/backend/data/mongo_research_repository.py`
- Modify: `quant-board/backend/data/repository.py`
- Modify: `quant-board/backend/services.py`
- Test: `quant-board/tests/test_mongo_research_repository.py`

- [ ] **Step 1: 写行为测试**

在 Mongo repository 测试中保存新 run 明细时验证 sequence 从 1 开始：

```python
repo.save_backtest_signal_rows("bt_new", [{"code": "000001"}, {"code": "000002"}], append=False)
rows = repo.get_backtest_signals("bt_new")
assert [row["sequence"] for row in rows] == [1, 2]
```

对 trades/equity 做同类断言。

再增加一个 fake collection 计数测试，明确证明 `append=False` 不调用 `count_documents()`：

```python
signals = repo.db["backtest_signals"]
signals.count_documents_calls = 0
original_count_documents = signals.count_documents

def tracked_count_documents(query):
    signals.count_documents_calls += 1
    return original_count_documents(query)

signals.count_documents = tracked_count_documents
repo.save_backtest_signal_rows("bt_no_count", [{"code": "000001"}], append=False)
assert signals.count_documents_calls == 0
```

如果现有 fake collection 不允许 monkeypatch 方法，则在 fake collection 类中增加调用计数字段，再做同等断言。

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py -k "append_false" -q
```

Expected: FAIL，原因是方法签名不支持 `append=False`。

- [ ] **Step 3: 扩展 repository 方法签名**

将相关方法签名调整为：

```python
def save_backtest_signal_rows(self, run_id: str, rows: list[dict[str, Any]], append: bool = True) -> int:
def save_backtest_signals(self, run_id: str, strategy_decisions: dict[str, Any], append: bool = True) -> int:
def save_backtest_trades(self, run_id: str, trades: list[dict[str, Any]], append: bool = True) -> int:
def save_backtest_equity_curve(self, run_id: str, curve: list[dict[str, Any]], append: bool = True) -> int:
```

Mongo 实现中：

```python
existing = self.db["backtest_signals"].count_documents({"backtestRunId": run_id}) if append else 0
```

SQLite/default repository 同步签名，保持现有 append 默认行为。
`save_backtest_signals()` 必须把 `append` 传给 `save_backtest_signal_rows()`，不能只改低层 rows 方法。

- [ ] **Step 4: run 保存路径使用非追加模式**

在 `BacktestService.run_ranktrend()`、ThemeTrend run、ThemeConfluence run 保存新 run 的归一化明细处调用：

```python
self.repo.save_backtest_trades(run_id, trades, append=False)
self.repo.save_backtest_equity_curve(run_id, equity_curve, append=False)
self.repo.save_backtest_signal_rows(run_id, signal_rows, append=False)
self.repo.save_backtest_signals(run_id, strategy_decisions, append=False)
```

如果某条路径实际只调用 `save_backtest_signals()` 而没有 `signal_rows`，只给该调用增加 `append=False`。如果实际变量名不同，以当前源码变量名为准，只修改参数，不改变业务口径。

- [ ] **Step 5: 运行相关测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py tests\test_quant_board.py -k "backtest_signal or export_report or ranktrend" -q
```

Expected: PASS.

## Task 6: MongoDB sequence 排序索引

**Files:**
- Modify: `quant-board/backend/data/mongodb_migration.py`
- Test: `quant-board/tests/test_mongo_research_repository.py`

- [ ] **Step 1: 写索引定义测试**

在 `quant-board/tests/test_mongo_research_repository.py` 或已有 MongoDB migration 测试文件中增加：

```python
from backend.data.mongodb_migration import build_mongodb_indexes


def test_backtest_detail_sequence_indexes_are_declared():
    indexes = build_mongodb_indexes()
    assert [("backtestRunId", 1), ("sequence", 1)] in [
        item["keys"] for item in indexes["backtest_trades"]
    ]
    assert [("backtestRunId", 1), ("sequence", 1)] in [
        item["keys"] for item in indexes["backtest_equity_curve"]
    ]
    assert [("backtestRunId", 1), ("sequence", 1)] in [
        item["keys"] for item in indexes["backtest_signals"]
    ]
```

- [ ] **Step 2: 运行失败测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py -k "sequence_indexes" -q
```

Expected: FAIL，原因是 `backtest_trades` 和 `backtest_equity_curve` 尚未声明 sequence 排序索引。

- [ ] **Step 3: 补齐 `build_mongodb_indexes()`**

在 `quant-board/backend/data/mongodb_migration.py` 中为相关集合增加：

```python
{"keys": [("backtestRunId", 1), ("sequence", 1)]},
```

只补排序索引，不删除或改写已有 `{backtestRunId, code}`、`{backtestRunId, entryTime}`、`{backtestRunId, timestamp}` 索引。

- [ ] **Step 4: 增加人工 explain 验收命令**

在实现完成后，对真实 MongoDB 运行以下人工验收：

```javascript
db.backtest_signals.find({ backtestRunId: "<run-id>" }).sort({ sequence: 1 }).explain("executionStats")
db.backtest_trades.find({ backtestRunId: "<run-id>" }).sort({ sequence: 1 }).explain("executionStats")
db.backtest_equity_curve.find({ backtestRunId: "<run-id>" }).sort({ sequence: 1 }).explain("executionStats")
```

Expected: winningPlan 使用 `{ backtestRunId: 1, sequence: 1 }` 相关索引，且没有大规模 in-memory sort。

- [ ] **Step 5: 运行索引测试确认通过**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_mongo_research_repository.py -k "sequence_indexes" -q
```

Expected: PASS.

## Task 7: 文档同步

**Files:**
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/mongodb-migration-plan.md`

- [ ] **Step 1: 更新 CLI 文档**

在 `quant-board/docs/api-cli.md` 的回测报告导出段落补充：

```markdown
`export-report` 默认输出 `jsonl-bundle` 目录，用于大型回测报告：

- `manifest.json`：run 元信息、metrics、文件清单和行数。
- `signals.jsonl`：按 `sequence` 升序的信号明细。
- `trades.jsonl`：按 `sequence` 升序的交易明细。
- `equity_curve.jsonl`：按 `sequence` 升序的权益曲线。
- `quality_report.json`：质量门禁和样本质量报告。
- `result_summary.json`：轻量结果摘要。

如需兼容旧单文件 JSON，可显式传 `--format legacy-json`；大型数据集不推荐使用该模式。
```

- [ ] **Step 2: 更新架构文档**

在 `quant-board/docs/architecture.md` 的 `backtest_runs`/`backtest_result_chunks` 附近补充：常规报告导出和页面展示优先走归一化集合，完整 `resultCompressed` 只用于兼容追溯。

- [ ] **Step 3: 更新 MongoDB 迁移文档**

在 `quant-board/docs/mongodb-migration-plan.md` 中补充：`backtest_trades`、`backtest_equity_curve`、`backtest_signals` 的导出排序热路径应具备 `{ backtestRunId, sequence }` 索引；`backtest_result_chunks` 继续保持 `{ backtestRunId, sequence }` 唯一索引。

- [ ] **Step 4: 文档自检**

Run:

```powershell
rg -n "jsonl-bundle|legacy-json|quality_report|resultCompressed|backtest_result_chunks|backtestRunId.*sequence" quant-board/docs/api-cli.md quant-board/docs/architecture.md quant-board/docs/mongodb-migration-plan.md
```

Expected: 能看到新增格式说明，且未把 Dragon Board 描述成直接连接 MongoDB。

## Task 8: 最终验证

**Files:**
- No code changes beyond previous tasks.

- [ ] **Step 1: 运行 QuantBoard 后端测试**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
```

Expected: PASS.

- [ ] **Step 2: 运行一次小型 CLI smoke test**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id <existing-small-run-id> --output data\reports\<existing-small-run-id> --format jsonl-bundle
```

Expected: 输出 `{ "ok": true, "format": "jsonl-bundle" }`，目录中存在 `manifest.json`、`signals.jsonl`、`trades.jsonl`、`equity_curve.jsonl`、`quality_report.json`、`result_summary.json`。

- [ ] **Step 3: 检查 diff 范围**

Run:

```powershell
git diff --stat
git diff -- quant-board/backend/data/repository.py quant-board/backend/data/mongo_research_repository.py quant-board/backend/services.py quant-board/backend/cli.py quant-board/tests/test_quant_board.py quant-board/tests/test_mongo_research_repository.py quant-board/docs/api-cli.md quant-board/docs/architecture.md
```

Expected: diff 只包含本计划相关文件，没有无关格式化或业务口径重写。

## 回退策略

- 如果 bundle 导出有问题，保留 `--format legacy-json` 可回退到旧单文件行为。
- 如果 Mongo iterator 在某些测试替身 repository 上不兼容，默认 repository 的 `yield from get_*()` 可作为保守兜底。
- 如果 `append=False` 签名影响现有调用，默认参数必须保持 `append=True`，旧调用行为不变。

## 计划自审

- Spec coverage: 覆盖了流式导出、兼容 legacy、Mongo iterator、跳过新 run 前置 count、文档同步和最终验证。
- Placeholder scan: 本计划不包含占位符或未定义的后续任务。
- Type consistency: 所有新增方法名在服务层、repository 层和 CLI 分派中保持一致。
