# 热榜情绪计算后端化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端 `HotListSentimentAnalyzer` 的热榜情绪计算完整移植为后端纯函数，新增 `GET /api/hotlist-sentiment/series` 读口，前端删除全部计算逻辑只消费后端生产数据。

**Architecture:** 三层收敛——`backend/analysis/hotlist/sentiment.py` 纯函数为唯一权威实现（golden fixture 与 TS 版逐 case 对齐）；`operations` EOD 入库与新增 `services/theme/hotlist_sentiment_compute.py` lazy-compute 编排都调用它；前端仅剩类型契约 + 薄 API client。输出是现有 `hotlist_sentiment` 库文档 schema 的超集，引擎 `market_regime` 消费不受影响。

**Tech Stack:** Python 3 / FastAPI（quant-board 后端）、MongoDB（测试用 Fake db）、Vue 3 + TypeScript + Vitest（根前端）、Express（proxy-server）。

**Spec:** `quant-board/docs/superpowers/specs/2026-09-06-hotlist-sentiment-backend-migration-design.md`

## Global Constraints

- **TDD 不可跳过**：每个任务先写测试锁行为，再写实现。
- **fail-visible**：数据缺失/异常输出结构化标注（`statusSourceCounts` / `missingEvidence` / degraded reason），禁止静默吞掉或伪造默认情绪。
- **禁止质量阻断**：编排层任何数据缺失都不阻断入库/返回，只打标。
- Python 算法只放 `backend/analysis/**`；有 I/O 编排放 `backend/services/**`；路由放 `backend/api/**`。
- 测试位置：Python → `quant-board/tests/*.py`；TS → 被测模块旁 `__tests__/*.test.ts`。
- **pytest 全量有挂起问题**：只跑相关子集；新测试文件先 `--collect-only` 确认可收集。
- TS 格式：无分号、单引号、printWidth=100。
- 禁止递归删除；只能一次删除一个明确路径的文件。
- 数值文案移植：JS `toFixed` 四舍五入半进位，Python `f"{x:.0f}"` 银行家舍入——`.5` 边界不一致时实现 `_js_to_fixed(value, digits)` 对齐 JS，不得放宽 golden 断言。
- 验证命令目录：pytest 在 `quant-board/`，vitest/vue-tsc 在仓库根。
- commit 风格：`feat(sentiment): 中文描述`。

## 源文件坐标（执行者必读）

| 内容                           | 位置                                                                                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| TS 完整实现（移植源）          | `src/services/hotlist/HotListSentimentAnalyzer.ts`（1341 行）                                                                        |
| TS golden 测试（fixture 来源） | `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts`（18 case）                                                         |
| 板块涨停阈值/容差              | `src/config/constants.ts` L594-626：MAIN 9.8 / GEM 19.8 / STAR 19.8 / NORTH 29.8，`CHANGE_TOLERANCE: 0.5`                            |
| 涨停判定                       | `src/utils/common.ts` L365-493：`isAlmostLimitUp = change >= threshold.up - tolerance*3`（即 up-1.5）；2026-09 起无 ST 特判          |
| 量比信任                       | `src/services/dataLoader/VolumeRatioTrust.ts`（11 行）                                                                               |
| 五阶段基础分                   | `src/types/emotion.ts` `EMOTION_CYCLE_STAGE_CONFIG`：冰点 56/启动 58/发酵 62/高潮 64/退潮 64                                         |
| 后端现状 EOD 入库              | `quant-board/backend/operations/hotlist_sentiment.py`（430 行，简化版待统一）                                                        |
| 后端存储封装                   | `quant-board/backend/services/theme/hotlist_sentiment_service.py`（upsert/get_by_date/单例/provider，不动）                          |
| 后端路由                       | `quant-board/backend/api/hotlist_routes.py`（prefix `/api/hotlist-sentiment`，已有 POST /ingest；main.py L114 已挂载）               |
| 库文档 schema 先例             | `operations/hotlist_sentiment.py` `build_hotlist_sentiment_document`（L199-230）                                                     |
| frame 市场证据                 | `quant-board/backend/snapshot_derivation/projection.py` L439-444：`limitSummary = {continuousBoards, zhaban, yesterdayZt, thsPools}` |
| snapshot_analysis 读口         | `quant-board/backend/data/repositories/mongo_repository.py` L1243 `load_snapshot_analysis(dataset_id, snapshot_id, code_list)`       |
| proxy 转发                     | `proxy-server/routes/quantBoardProxy.js` L8-36 `QUANT_BOARD_PREFIXES`（缺 `/api/hotlist-sentiment/`）                                |
| 面板消费方                     | `src/components/panels/DragonBreathPanel.vue` L1292-1358 `loadHotListSentiment`                                                      |

### TS→Python 移植总原则

- 纯函数签名与 TS `analyze(input)` 一一对应：

```python
def compute_hotlist_sentiment(
    stocks: list[dict],
    yesterday: dict | None = None,    # {"tradingDate": "...", "rows": [...]}；rows 对应 TS snapshot.hotlist
    day_before: dict | None = None,
    market_data: dict | None = None,  # TS DragonBreathMarketDataLike 形态
    top_n: int | None = None,
) -> dict:
```

- 输出行可带编排层注入的 `displayStatusLabel`（合法 8 状态标签字符串）；有则直接采用，无则走 fallback 分类。golden fixture 的输入行均无该键，全部走 fallback——与 TS 测试路径一致。
- `displayStatusLabel`/`_statusSource` 计数进 `statusSourceCounts`：`{"displayStatus": N, "fallback": M}`。
- 每个移植函数在模块内用 `# TS: HotListSentimentAnalyzer.ts L<行号>` 注释标注源行，便于 diff 对照。

---

### Task 1: golden fixture 提取（删除 TS 前先锁行为）

**Files:**

- Create（临时，本任务内删除）: `src/services/hotlist/__tests__/goldenExtraction.test.ts`
- Create: `quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json`

**Interfaces:**

- Produces: `golden_cases.json`，结构 `{"extractedFrom": "...", "extractedAt": "2026-09-06", "cases": [{"name", "input", "expected"}]}`；`input` 为 TS `analyze` 入参原样（stocks/yesterday/dayBefore/marketData/topN），`expected` 为完整 analyze 返回值。后续 Task 2/3/4 的 Python 测试按 case 名逐条断言。

- [ ] **Step 1: 写临时提取 spec**

新建 `src/services/hotlist/__tests__/goldenExtraction.test.ts`。头部：`import { describe, it, afterAll } from 'vitest'`、`import { writeFileSync, mkdirSync } from 'node:fs'`、`import { HotListSentimentAnalyzer } from '../HotListSentimentAnalyzer'`。

复刻测试文件的 `stock()` / `makeStocks()` 构造函数（照抄 `HotListSentimentAnalyzer.test.ts` L8-31），然后为现有 17 个 `it()` 逐个建同名 case：把每个 `it` 内的输入构造与 `analyze(...)` 调用移入数组，断言替换为收集结果。两个完整示例（其余 case 同法，输入构造逐字照抄现有测试对应 `it` 块）：

```ts
const cases: Array<{ name: string; input: any; expected: any }> = []

it('case: 强扩散但高拥挤时识别为高潮', () => {
  const analyzer = new HotListSentimentAnalyzer()
  const input = {
    stocks: makeStocks(120, (index) => ({
      change: index < 28 ? 9.8 : 2,
      turnoverRate: index < 28 ? 18 : 6,
      volumeRatio: index < 28 ? 2.6 : 1.2,
      turnover: index < 28 ? 20e8 : 8e8,
      zlje: index < 60 ? 2e8 : 0,
      zljzb: index < 60 ? 15 : 0,
      cddje: index < 60 ? 8000e4 : 0,
      cddjzb: index < 60 ? 6 : 0,
    })),
    yesterday: { tradingDate: '2026-04-29', hotlist: makeStocks(95) },
    dayBefore: { tradingDate: '2026-04-28', hotlist: makeStocks(88) },
  }
  cases.push({ name: '强扩散但高拥挤时识别为高潮', input, expected: analyzer.analyze(input) })
})

it('case: THS炸板池和涨停股回撤榜只作为全市场补充证据', () => {
  const analyzer = new HotListSentimentAnalyzer()
  const input = {
    stocks: makeStocks(100, (index) => ({
      change: index < 4 ? 9.9 : 1,
      zlje: index < 15 ? 2e8 : 0,
      zljzb: index < 15 ? 15 : 0,
      cddje: index < 15 ? 8000e4 : 0,
      cddjzb: index < 15 ? 6 : 0,
    })),
    marketData: {
      ztCount: 98,
      zhaban: { count: 24, fengbanRate: 80 },
      thsLimitUpPools: {
        source: 'ths-limitup-pools',
        degraded: false,
        errors: [],
        poolCounts: {
          one: 61,
          two: 14,
          three: 3,
          four: 1,
          high: 5,
          failed: 11,
          rushing: 8,
          drawdown: 7,
        },
        failedCount: 11,
        rushingCount: 8,
        drawdownCount: 7,
        drawdownRiskLabel: '涨停股回撤榜',
        maxDrawdown: -12.4,
        avgDrawdown: -6.3,
      },
    },
  }
  cases.push({
    name: 'THS炸板池和涨停股回撤榜只作为全市场补充证据',
    input,
    expected: analyzer.analyze(input),
  })
})

afterAll(() => {
  mkdirSync('quant-board/tests/fixtures/hotlist_sentiment', { recursive: true })
  writeFileSync(
    'quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json',
    JSON.stringify(
      {
        extractedFrom: 'src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts',
        extractedAt: '2026-09-06',
        cases,
      },
      null,
      2,
    ),
  )
  console.log(`[golden] dumped ${cases.length} cases`)
})
```

18 个 case 清单（名称必须与现有测试 `it` 名称一致，Task 2-4 按名引用）：强扩散但高拥挤时识别为高潮 / 强资确认增加且风险低时识别为发酵 / 新入和机会状态改善时识别为启动 / 风险状态上升且 TRIN 偏弱时识别为退潮 / 上涨承接较强时高风险压力不直接判为退潮 / 严重风险叠加昨日强票失败且成交承接转弱时识别为退潮 / 热榜收缩且机会少时识别为冰点 / 输出前20、前50、前100分层统计 / 输出全池 all 分层统计 / 统计热榜股票池每日进出明细（该 case 测的是 `computeTurnover`，input 记 `{todayStocks, yesterdayStocks}`，expected 记函数返回值）/ 分析结果包含当日 turnover 汇总 / 默认使用全热榜池统计主情绪指标 / 按A股板块阈值统计热榜涨停和近涨停证据（input 含 `topN: 100`）/ 热榜涨停证据只使用热榜交集，全市场数据仅作为背景 / THS炸板池和涨停股回撤榜只作为全市场补充证据 / 昨日热榜涨停今日表现纳入持续性证据 / fallback status ignores suspicious capped volume ratio when detecting crowded stocks / 统计昨日强票今日平均涨幅、正收益率和转弱率。

不提取 `persistHotListSentiment`（提交死代码，本次删除不迁移）。共提取 **18 个 case**（19 个 it 减 persist）。

- [ ] **Step 2: 运行提取**

Run: `pnpm vitest run src/services/hotlist/__tests__/goldenExtraction.test.ts`
Expected: 全部 case it 通过；控制台输出 `[golden] dumped 18 cases`；`quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json` 生成。

- [ ] **Step 3: 抽查 fixture**

打开 `golden_cases.json` 确认：18 个 case、每个 `expected.stage` 与现有测试断言一致（如"强扩散…"→`高潮`）、`expected.metrics.comparison.today.statusCounts` 为 8 键对象。

- [ ] **Step 4: 删除临时 spec 并提交**

```bash
rm src/services/hotlist/__tests__/goldenExtraction.test.ts
git add quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json
git commit -m "test(sentiment): 提取热榜情绪 TS 分析器 golden fixture（18 case，后端移植对齐基线）"
```

---

### Task 2: Python 纯函数——原语 + turnover + 分层 metrics

**Files:**

- Create: `quant-board/backend/analysis/hotlist/__init__.py`（空文件）
- Create: `quant-board/backend/analysis/hotlist/sentiment.py`
- Create: `quant-board/tests/test_hotlist_sentiment_compute.py`

**Interfaces:**

- Consumes: `golden_cases.json`（Task 1）。
- Produces（Task 3/4 依赖，签名固定）：
  - `to_number(value) -> float`
  - `sort_rows(rows) -> list[dict]`（按 compRank/rank 升序，无 code 行剔除，rank<=0 用 index+1）
  - `get_trusted_volume_ratio(stock) -> float`
  - `compute_turnover(today_rows, yesterday_rows) -> dict`（TS TurnoverResult 结构）
  - `build_day_metrics_from_sorted(sorted_rows, top_n, trading_date=None) -> dict`（TS HotListDayMetrics 结构）
  - `build_layer_metrics(rows, trading_date=None) -> dict`（top20/top50/top100/all）
  - `limit_threshold(code) -> float`、`check_limit_status(change, code) -> dict`（含 isAlmostLimitUp）
- Produces（测试基建）：`load_golden_cases()` helper 与 `assert_golden_case(case, result, keys)` 部分断言 helper。

- [ ] **Step 1: 写测试骨架 + 金量断言（先失败）**

`quant-board/tests/test_hotlist_sentiment_compute.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.hotlist.sentiment import (
    build_layer_metrics,
    check_limit_status,
    compute_turnover,
    sort_rows,
)

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hotlist_sentiment" / "golden_cases.json"


def load_golden_cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def get_case(cases: dict, name: str) -> dict:
    for case in cases["cases"]:
        if case["name"] == name:
            return case
    raise AssertionError(f"golden case 不存在: {name}")


def test_golden_all_pool_layer():
    case = get_case(load_golden_cases(), "输出全池 all 分层统计")
    rows = case["input"]["stocks"]
    layers = build_layer_metrics(rows)
    expected = case["expected"]["metrics"]["layers"]
    assert layers["all"]["topN"] == expected["all"]["topN"] == 120
    assert layers["all"]["upCount"] == 100
    assert layers["all"]["downCount"] == 20
    assert layers["all"]["upRatio"] == pytest.approx(expected["all"]["upRatio"])


def test_golden_layer_top20_50_100():
    case = get_case(load_golden_cases(), "输出前20、前50、前100分层统计")
    layers = build_layer_metrics(case["input"]["stocks"])
    expected = case["expected"]["metrics"]["layers"]
    assert layers["top20"]["topN"] == 20
    assert layers["top50"]["topN"] == 50
    assert layers["top100"]["topN"] == 100
    assert layers["top20"]["upRatio"] > layers["top100"]["upRatio"]
    assert layers["top20"]["activeOpportunityCount"] > 0
    assert layers["top20"]["statusCounts"] == expected["top20"]["statusCounts"]


def test_golden_turnover_details():
    case = get_case(load_golden_cases(), "统计热榜股票池每日进出明细")
    result = compute_turnover(case["input"]["todayStocks"], case["input"]["yesterdayStocks"])
    assert result == case["expected"]


def test_golden_limit_threshold_by_board():
    # 对应 TS case「按A股板块阈值统计热榜涨停和近涨停证据」的判定基线：
    # 主板 ST（*ST测试 4.9%）按 ±10% 判定，不计入涨停/近涨停
    assert check_limit_status(9.9, "600001")["isLimitUp"] is True
    assert check_limit_status(19.8, "688001")["isLimitUp"] is True
    assert check_limit_status(29.0, "830001")["isLimitUp"] is False      # 北交所阈值 29.8-0.5=29.3，29.0 未达
    assert check_limit_status(29.4, "830001")["isAlmostLimitUp"] is True
    assert check_limit_status(4.9, "000001")["isLimitUp"] is False
    assert check_limit_status(8.4, "000001")["isAlmostLimitUp"] is True  # 9.8-1.5=8.3
    assert check_limit_status(8.2, "000001")["isAlmostLimitUp"] is False


def test_get_trusted_volume_ratio_branches():
    # TS: VolumeRatioTrust.ts L1-12 四分支逐一对齐
    from backend.analysis.hotlist.sentiment import get_trusted_volume_ratio

    assert get_trusted_volume_ratio({"volumeRatio": 3.2}) == 3.2                                   # 无 meta → 原值直通
    assert get_trusted_volume_ratio({"volumeRatio": 3.2, "volumeRatioMeta": {"status": "fresh"}}) == 3.2
    assert get_trusted_volume_ratio({"volumeRatio": 3.2, "volumeRatioMeta": {"status": "suspicious"}}) == 0.0
    assert get_trusted_volume_ratio({"volumeRatio": 0}) == 0.0                                     # value<=0 → 0
    assert get_trusted_volume_ratio({"volumeRatio": "abc"}) == 0.0                                 # 非有限 → 0
```

注意 pytest 名不能与 case 名混淆：`test_golden_*` 直接命名，`get_case` 按中文名查。

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py --collect-only -q` 然后 `.venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v`
Expected: collect 成功；运行时 ImportError/ModuleNotFoundError（`backend.analysis.hotlist.sentiment` 不存在）。

- [ ] **Step 3: 实现原语层**

`quant-board/backend/analysis/hotlist/sentiment.py` 首批内容（完整实现，后续任务在此文件追加）：

```python
"""热榜情绪纯函数——TS HotListSentimentAnalyzer 的 Python 等价实现（唯一权威口径）。

移植源: src/services/hotlist/HotListSentimentAnalyzer.ts（golden 对齐基线见
quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json）。
纯函数：不做 I/O、不持有 db 句柄；缺失/NaN 按 fail-visible 输出标注，不伪造状态。
"""
from __future__ import annotations

import math
import re
from typing import Any

# TS: src/config/constants.ts LIMIT_UP_CONFIG
_LIMIT_THRESHOLDS = {"MAIN": 9.8, "GEM": 19.8, "STAR": 19.8, "NORTH": 29.8}
_CHANGE_TOLERANCE = 0.5

STATUS_LABELS = ["主升确认", "点火观察", "强资确认", "新入观察", "高位拥挤", "资金背离", "转弱预警", "样本不足"]
_YESTERDAY_STRONG_LABELS = {"主升确认", "点火观察", "强资确认"}


def to_number(value: Any) -> float:
    # TS: toNumber —— Number(value)，NaN→0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def normalize_code(value: Any) -> str:
    return str(value or "").strip()


def get_rank(stock: dict, fallback_index: int) -> int:
    # TS: getRank —— compRank ?? rank，>0 有效
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    return int(rank) if rank > 0 else fallback_index + 1


def sort_rows(rows: list[dict] | None) -> list[dict]:
    # TS: sortByRank —— 过滤无 code，按 rank 升序
    filtered = [row for row in (rows or []) if normalize_code(row.get("code"))]
    return sorted(filtered, key=lambda row: get_rank(row, 9999))


def get_trusted_volume_ratio(stock: dict) -> float:
    # TS: getTrustedVolumeRatio（VolumeRatioTrust.ts L1-12）逐分支对齐：
    # value 非有限或 <=0 → 0；无 meta → 原值直通（视为已收盘可信）；meta.status=='fresh' → 原值；否则 0
    value = to_number(stock.get("volumeRatio"))
    if value <= 0:
        return 0.0
    meta = stock.get("volumeRatioMeta")
    if not isinstance(meta, dict) or not meta:
        return value
    return value if meta.get("status") == "fresh" else 0.0


def limit_threshold(code: str) -> float:
    # TS: StockUtils.getLimitThreshold —— 688/689→STAR，30→GEM，43/8/92→NORTH，其余 MAIN；无 ST 特判
    normalized = str(code or "").strip()
    padded = normalized.zfill(6)
    if padded.startswith("688") or padded.startswith("689"):
        return _LIMIT_THRESHOLDS["STAR"]
    if padded.startswith("30"):
        return _LIMIT_THRESHOLDS["GEM"]
    if padded.startswith("43") or padded.startswith("8") or padded.startswith("92"):
        return _LIMIT_THRESHOLDS["NORTH"]
    return _LIMIT_THRESHOLDS["MAIN"]


def check_limit_status(change: float, code: str) -> dict:
    # TS: StockUtils.checkLimitStatus —— isAlmostLimitUp = change >= threshold.up - tolerance*3
    threshold = limit_threshold(code)
    tolerance = _CHANGE_TOLERANCE
    return {
        "isLimitUp": change >= threshold - tolerance,
        "isLimitDown": change <= -threshold + tolerance,
        "isAlmostLimitUp": change >= threshold - tolerance * 3,
        "isAlmostLimitDown": change <= -threshold + tolerance * 3,
        "threshold": {"up": threshold, "down": -threshold},
    }


def _entry_reason(stock: dict) -> str:
    # TS: classifyEntryReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitUp"]:
        return "limit_up"
    if to_number(stock.get("zlje")) > 0 or to_number(stock.get("zljzb")) > 0:
        return "strong_money"
    if get_trusted_volume_ratio(stock) > 2:
        return "new_high_volume"
    return "rank_surge"


def _exit_reason(stock: dict) -> str:
    # TS: classifyExitReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitDown"]:
        return "limit_down"
    if change < -3:
        return "weakening"
    return "rank_out_of_range"


def compute_turnover(today_rows: list[dict], yesterday_rows: list[dict]) -> dict:
    # TS: computeTurnover L291-320
    today = sort_rows(today_rows)
    yesterday = sort_rows(yesterday_rows)
    today_codes = {normalize_code(row.get("code")) for row in today}
    yesterday_codes = {normalize_code(row.get("code")) for row in yesterday}
    new_entries = [row for row in today if normalize_code(row.get("code")) not in yesterday_codes]
    eliminated = [row for row in yesterday if normalize_code(row.get("code")) not in today_codes]
    return {
        "previousPoolSize": len(yesterday),
        "currentPoolSize": len(today),
        "retainedFromYesterday": sum(1 for row in today if normalize_code(row.get("code")) in yesterday_codes),
        "newEntries": [normalize_code(row.get("code")) for row in new_entries],
        "eliminated": [normalize_code(row.get("code")) for row in eliminated],
        "newEntryDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "entryReason": _entry_reason(row),
            }
            for index, row in enumerate(new_entries)
        ],
        "eliminatedDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "exitReason": _exit_reason(row),
            }
            for index, row in enumerate(eliminated)
        ],
    }
```

继续同文件追加分层 metrics（完整实现）：

```python
def _parse_board_height_text(value: Any) -> int:
    # TS: parseBoardHeightText —— "首板"→1，正则 (\d+)\s*(?:连?板|天|日)?
    raw = str(value or "").strip()
    if not raw:
        return 0
    if "首板" in raw:
        return 1
    match = re.search(r"(\d+)\s*(?:连?板|天|日)?", raw)
    return int(to_number(match.group(1))) if match else 0


def _raw_board_height(stock: dict) -> int:
    # TS: getRawBoardHeight
    continuous_days = to_number(stock.get("continuousDays"))
    candidates = [
        to_number(stock.get("boardHeight")),
        to_number(stock.get("highDays")),
        continuous_days if continuous_days > 1 else 0,
        _parse_board_height_text(stock.get("lianbanStr")),
        _parse_board_height_text(stock.get("lianban")),
    ]
    return int(max(candidates))


def _has_limit_up_marker(stock: dict) -> bool:
    # TS: hasLimitUpMarker
    return bool(
        str(stock.get("firstZtTime") or "").strip()
        or str(stock.get("lastZtTime") or "").strip()
        or str(stock.get("first_limit_up_time") or "").strip()
        or str(stock.get("last_limit_up_time") or "").strip()
        or _raw_board_height(stock) > 0
    )


def _has_stock_zhaban_signal(stock: dict) -> bool:
    # TS: hasStockZhabanSignal
    return bool(
        stock.get("isZhaban") is True or stock.get("zhaban") is True
        or stock.get("openedLimit") is True or stock.get("limitOpened") is True
        or stock.get("failedLimitUp") is True or stock.get("isFailedLimitUp") is True
    )


def get_stock_limit_signal(stock: dict) -> dict:
    # TS: getStockLimitSignal L362-378
    code = normalize_code(stock.get("code"))
    status = check_limit_status(to_number(stock.get("change")), code)
    has_marker = _has_limit_up_marker(stock)
    board_height = max(_raw_board_height(stock), 1 if status["isLimitUp"] or has_marker else 0)
    return {
        "isLimitUp": status["isLimitUp"],
        "isAlmostLimitUp": status["isAlmostLimitUp"],
        "isLimitDown": status["isLimitDown"],
        "threshold": status["threshold"]["up"],
        "boardHeight": board_height,
        "isBoard2Plus": board_height >= 2,
        "hasLimitMarker": has_marker,
    }


def _has_limit_up_evidence(stock: dict) -> bool:
    signal = get_stock_limit_signal(stock)
    return signal["isLimitUp"] or signal["hasLimitMarker"]


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _resolve_sample_size(rows: list[dict], top_n: int | None) -> int:
    if top_n and top_n > 0:
        return min(len(rows), int(top_n))
    return len(rows)


def _calculate_hot_trin(up_count: int, down_count: int, up_turnover: float, down_turnover: float) -> float | None:
    # TS: calculateHotTrin —— 注意与旧 operations/_hot_trin 不同：turnover 取原值分桶
    if up_count <= 0 or down_count <= 0 or up_turnover <= 0 or down_turnover <= 0:
        return None
    return (up_count / down_count) / (up_turnover / down_turnover)


def build_day_metrics_from_sorted(sorted_rows: list[dict], top_n: int, trading_date: str | None = None) -> dict:
    # TS: buildDayMetricsFromSorted L458-546；状态计数依赖 Task 3 的 resolve_stock_status，
    # 本任务先接 fallback 版（Task 3 完成后自动升级为 displayStatus 优先）。
    top = sorted_rows[:top_n]
    status_counts = {label: 0 for label in STATUS_LABELS}
    status_source = {"displayStatus": 0, "fallback": 0}

    up_count = down_count = flat_count = 0
    up_turnover = down_turnover = total_turnover = 0.0
    main_net = super_net = change_sum = 0.0
    near_limit_up = high_gain = high_turnover = 0

    for stock in top:
        change = to_number(stock.get("change"))
        turnover = to_number(stock.get("turnover"))
        turnover_rate = to_number(stock.get("turnoverRate"))
        label = resolve_stock_status(stock, sorted_rows, status_source)
        status_counts[label] += 1
        total_turnover += turnover
        main_net += to_number(stock.get("zlje"))
        super_net += to_number(stock.get("cddje"))
        change_sum += change
        if change > 0:
            up_count += 1
            up_turnover += turnover
        elif change < 0:
            down_count += 1
            down_turnover += turnover
        else:
            flat_count += 1
        if get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            near_limit_up += 1
        if change >= 7:
            high_gain += 1
        if turnover_rate >= 10:
            high_turnover += 1

    total = len(top)
    status_shares = {label: _safe_divide(status_counts[label], total) for label in STATUS_LABELS}
    active = status_counts["主升确认"] + status_counts["点火观察"] + status_counts["强资确认"]
    opportunity = active + status_counts["新入观察"]
    risk = status_counts["资金背离"] + status_counts["转弱预警"]
    crowded = status_counts["高位拥挤"]
    return {
        "tradingDate": trading_date,
        "total": len(sorted_rows),
        "topN": total,
        "upCount": up_count,
        "downCount": down_count,
        "flatCount": flat_count,
        "upRatio": _safe_divide(up_count, total),
        "downRatio": _safe_divide(down_count, total),
        "hotTrin": _calculate_hot_trin(up_count, down_count, up_turnover, down_turnover),
        "totalTurnover": total_turnover,
        "upTurnover": up_turnover,
        "downTurnover": down_turnover,
        "mainNetAmount": main_net,
        "superNetAmount": super_net,
        "avgChange": _safe_divide(change_sum, total),
        "nearLimitUpCount": near_limit_up,
        "highGainCount": high_gain,
        "highTurnoverCount": high_turnover,
        "statusCounts": status_counts,
        "statusShares": status_shares,
        "activeOpportunityCount": active,
        "activeOpportunityShare": _safe_divide(active, total),
        "opportunityCount": opportunity,
        "opportunityShare": _safe_divide(opportunity, total),
        "riskCount": risk,
        "riskShare": _safe_divide(risk, total),
        "crowdedCount": crowded,
        "crowdedShare": _safe_divide(crowded, total),
    }


def build_layer_metrics(rows: list[dict], trading_date: str | None = None) -> dict:
    # TS: buildLayerMetrics L731-739
    sorted_rows = sort_rows(rows)
    return {
        "top20": build_day_metrics_from_sorted(sorted_rows, 20, trading_date),
        "top50": build_day_metrics_from_sorted(sorted_rows, 50, trading_date),
        "top100": build_day_metrics_from_sorted(sorted_rows, 100, trading_date),
        "all": build_day_metrics_from_sorted(sorted_rows, len(sorted_rows), trading_date),
    }
```

同文件加临时占位状态函数（Task 3 替换为正式实现；本任务先让 import 可用且分层 case 走 fallback）：

```python
def resolve_stock_status(stock: dict, context_rows: list[dict], status_source: dict | None = None) -> str:
    # Task 3 将替换为 displayStatus 优先 + fallback 的正式实现
    return fallback_status_label(stock)


def fallback_status_label(stock: dict) -> str:
    # TS: getFallbackHistoricalStatus L395-417
    change = to_number(stock.get("change"))
    rank = int(to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank")))
    zlje = to_number(stock.get("zlje"))
    zljzb = to_number(stock.get("zljzb"))
    cddje = to_number(stock.get("cddje"))
    cddjzb = to_number(stock.get("cddjzb"))
    volume_ratio = get_trusted_volume_ratio(stock)
    turnover_rate = to_number(stock.get("turnoverRate"))
    strong_money = zlje > 0 and zljzb >= 8 and (cddje > 0 or cddjzb >= 3)
    money_weak = zlje < 0 or zljzb <= -8 or (cddje < 0 and cddjzb <= -3)
    high_position = change >= 8 or rank <= 30
    overheated = high_position and (volume_ratio >= 1.8 or turnover_rate >= 10)
    if money_weak and (rank <= 80 or change > 0):
        return "资金背离"
    if overheated:
        return "高位拥挤"
    if strong_money:
        return "强资确认"
    if change >= 3 or rank <= 100:
        return "新入观察"
    return "样本不足"
```

两个与旧 `operations/hotlist_sentiment.py` `_fallback_status_label` 的刻意差异（golden 基线以 TS 为准）：① TS 无 `change <= -3 → 转弱预警` 分支（末支直接样本不足）；② `highPosition` 的 rank 判断是 `rank <= 30`（rank=0 同样命中，不写 `0 < rank`）。执行时以 TS L395-417 源码逐行核对。

- [ ] **Step 4: 运行本任务测试通过**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v`
Expected: 4 个测试 PASS（分层 statusCounts 依赖 fallback 分类，应与 TS 输出一致；若不一致，逐行对照 TS 修正实现，不得改 golden）。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/hotlist/ quant-board/tests/test_hotlist_sentiment_compute.py
git commit -m "feat(sentiment): 热榜情绪后端纯函数原语层（turnover/分层metrics/涨停阈值，golden 对齐）"
```

---

### Task 3: Python 纯函数——displayStatus 优先状态解析 + limitEvidence + comparison

**Files:**

- Modify: `quant-board/backend/analysis/hotlist/sentiment.py`（替换 `resolve_stock_status` 占位；追加 limitEvidence/comparison）
- Modify: `quant-board/tests/test_hotlist_sentiment_compute.py`（追加测试）

**Interfaces:**

- Consumes: Task 2 全部函数。
- Produces（Task 4 依赖）：
  - `resolve_stock_status(stock, context_rows, status_source=None) -> str`（正式版：`displayStatusLabel` 优先，fallback 兜底，来源计数）
  - `build_market_limit_evidence(market_data) -> dict`
  - `build_limit_intersection_evidence(sorted_rows, top_n) -> dict`
  - `build_yesterday_hot_limit_evidence(yesterday_rows, today_rows, top_n) -> dict`
  - `build_limit_evidence(today_rows, yesterday_rows, top_n, market_data) -> dict`
  - `build_yesterday_strong_performance(yesterday_rows, today_rows, top_n) -> dict`
  - `build_comparison(stocks, yesterday_rows, day_before_rows, top_n) -> dict`（TS HotListThreeDayComparison 结构）

- [ ] **Step 1: 写失败测试**

追加到 `test_hotlist_sentiment_compute.py`（import 行补充 `build_comparison, build_limit_evidence, build_yesterday_strong_performance`）：

```python
def test_golden_limit_intersection_board_thresholds():
    case = get_case(load_golden_cases(), "按A股板块阈值统计热榜涨停和近涨停证据")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], case["input"].get("topN"), None)
    expected = case["expected"]["metrics"]["limitEvidence"]
    assert evidence["intersection"]["top100LimitUpCount"] == expected["intersection"]["top100LimitUpCount"] == 2
    assert evidence["intersection"]["top100NearLimitUpCount"] == expected["intersection"]["top100NearLimitUpCount"] == 3


def test_golden_market_evidence_passthrough():
    case = get_case(load_golden_cases(), "热榜涨停证据只使用热榜交集，全市场数据仅作为背景")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], None, case["input"]["marketData"])
    assert evidence["market"]["ztCount"] == 98
    assert evidence["market"]["zhabanCount"] == 24
    assert evidence["intersection"]["top100LimitUpCount"] == 4


def test_golden_ths_pools_evidence():
    case = get_case(load_golden_cases(), "THS炸板池和涨停股回撤榜只作为全市场补充证据")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], None, case["input"]["marketData"])
    assert evidence["market"]["thsPools"]["failedCount"] == 11
    assert evidence["market"]["thsPools"]["drawdownCount"] == 7
    assert evidence["market"]["thsPools"]["drawdownRiskLabel"] == "涨停股回撤榜"


def test_golden_yesterday_hot_limit():
    case = get_case(load_golden_cases(), "昨日热榜涨停今日表现纳入持续性证据")
    today = sort_rows(case["input"]["stocks"])
    yesterday = sort_rows(case["input"]["yesterday"]["hotlist"])
    evidence = build_limit_evidence(today, yesterday, None, None)
    expected = case["expected"]["metrics"]["limitEvidence"]["yesterdayHotLimit"]
    result = evidence["yesterdayHotLimit"]
    assert result["count"] == expected["count"] == 6
    assert result["retainedTop100Count"] == 6
    assert result["positiveRate"] == pytest.approx(expected["positiveRate"])
    assert result["failedOrWeakRate"] >= 0.5


def test_golden_yesterday_strong_performance():
    case = get_case(load_golden_cases(), "统计昨日强票今日平均涨幅、正收益率和转弱率")
    today = sort_rows(case["input"]["stocks"])
    yesterday = sort_rows(case["input"]["yesterday"]["hotlist"])
    result = build_yesterday_strong_performance(yesterday, today, None)
    assert result["count"] == 10
    assert result["matchedCount"] == 10
    assert result["positiveRate"] == pytest.approx(0.6)
    assert result["weakeningRate"] == pytest.approx(0.4)
    assert result["avgChange"] == pytest.approx(0)


def test_golden_comparison_three_day():
    case = get_case(load_golden_cases(), "热榜收缩且机会少时识别为冰点")
    yesterday_rows = case["input"]["yesterday"]["hotlist"]
    day_before_rows = case["input"]["dayBefore"]["hotlist"]
    comparison = build_comparison(case["input"]["stocks"], yesterday_rows, day_before_rows, None)
    assert comparison["totalChange1d"] == case["expected"]["metrics"]["comparison"]["totalChange1d"] < 0
    assert comparison["totalChange2d"] == case["expected"]["metrics"]["comparison"]["totalChange2d"] < 0


def test_display_status_preferred_over_fallback():
    row = {"code": "000001", "change": 5, "displayStatusLabel": "资金背离"}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_stock_status(row, [row], source) == "资金背离"
    assert source == {"displayStatus": 1, "fallback": 0}


def test_display_status_fallback_when_missing():
    row = {"code": "000001", "change": 5}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_stock_status(row, [row], source) == "新入观察"
    assert source == {"displayStatus": 0, "fallback": 1}


def test_display_status_invalid_label_falls_back():
    row = {"code": "000001", "change": 5, "displayStatusLabel": "无效标签"}
    assert resolve_stock_status(row, [row]) == "新入观察"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v`
Expected: 新增测试 ImportError（函数未定义）FAIL。

- [ ] **Step 3: 实现状态解析与证据层**

替换 Task 2 的占位 `resolve_stock_status`：

```python
def resolve_stock_status(stock: dict, context_rows: list[dict], status_source: dict | None = None) -> str:
    # TS: createStockStatusResolver L419-426 —— rankTrend displayStatus 优先，fallback 兜底。
    # 后端行由编排层注入 displayStatusLabel（snapshot_analysis.displayStatus 的规范 label）。
    label = stock.get("displayStatusLabel")
    if isinstance(label, str) and label in STATUS_LABELS:
        if status_source is not None:
            status_source["displayStatus"] += 1
        return label
    if status_source is not None:
        status_source["fallback"] += 1
    return fallback_status_label(stock)
```

`build_day_metrics_from_sorted` 内部已调用 `resolve_stock_status(stock, sorted_rows, status_source)`；把 `status_source` 的最新一次计数写进返回 dict 顶层键 `statusSourceCounts`（该键不属于 TS HotListDayMetrics，放 day metrics 顶层是后端超集约定；Task 6 的 series 文档透出）。在 `build_day_metrics_from_sorted` 返回 dict 前加：

```python
    result["statusSourceCounts"] = status_source
```

追加证据与对比层（完整实现）：

```python
def _empty_ths_pools() -> dict:
    # TS: createEmptyThsPoolsEvidence
    return {
        "source": "ths-limitup-pools", "degraded": False, "errors": [],
        "poolCounts": {"one": 0, "two": 0, "three": 0, "four": 0, "high": 0, "failed": 0, "rushing": 0, "drawdown": 0},
        "failedCount": 0, "rushingCount": 0, "drawdownCount": 0,
        "drawdownRiskLabel": "涨停股回撤榜", "maxDrawdown": None, "avgDrawdown": None,
    }


def build_market_limit_evidence(market_data: dict | None) -> dict:
    # TS: buildMarketLimitEvidence L586-607
    if not market_data:
        return {
            "ztCount": 0, "zhabanCount": 0, "fengbanRate": 0,
            "board1": 0, "board2": 0, "board3": 0, "board4Plus": 0,
            "maxContinuousDays": 0, "thsPools": _empty_ths_pools(),
        }
    zhaban = market_data.get("zhaban") if isinstance(market_data.get("zhaban"), dict) else {}
    limit_data = market_data.get("limitData") if isinstance(market_data.get("limitData"), dict) else {}
    board1 = to_number(limit_data.get("yiban"))
    board2 = to_number(limit_data.get("erban"))
    board3 = to_number(limit_data.get("sanban"))
    board4_plus = to_number(limit_data.get("sibanPlus"))
    fallback_max_days = 4 if board4_plus > 0 else 3 if board3 > 0 else 2 if board2 > 0 else 1 if board1 > 0 else 0
    return {
        "ztCount": to_number(market_data.get("ztCount")),
        "zhabanCount": to_number(zhaban.get("count")),
        "fengbanRate": to_number(zhaban.get("fengbanRate")),
        "board1": board1, "board2": board2, "board3": board3, "board4Plus": board4_plus,
        "maxContinuousDays": to_number(market_data.get("maxContinuousDays")) or fallback_max_days,
        "thsPools": market_data.get("thsLimitUpPools") if isinstance(market_data.get("thsLimitUpPools"), dict) else _empty_ths_pools(),
    }


def build_limit_intersection_evidence(sorted_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildLimitIntersectionEvidence L613-643
    top20 = sorted_rows[:20]
    top50 = sorted_rows[:50]
    top100 = sorted_rows[: _resolve_sample_size(sorted_rows, top_n)]
    near = board2plus = 0
    max_height = 0
    zhaban = 0
    for stock in top100:
        signal = get_stock_limit_signal(stock)
        if signal["isAlmostLimitUp"]:
            near += 1
        if signal["isBoard2Plus"]:
            board2plus += 1
        max_height = max(max_height, signal["boardHeight"])
        if _has_stock_zhaban_signal(stock):
            zhaban += 1
    limit_up = sum(1 for stock in top100 if _has_limit_up_evidence(stock))
    size = len(top100)
    return {
        "top20LimitUpCount": sum(1 for stock in top20 if _has_limit_up_evidence(stock)),
        "top50LimitUpCount": sum(1 for stock in top50 if _has_limit_up_evidence(stock)),
        "top100LimitUpCount": limit_up,
        "top100LimitUpShare": _safe_divide(limit_up, size),
        "top100NearLimitUpCount": near,
        "top100Board2PlusCount": board2plus,
        "top100MaxBoardHeight": max_height,
        "top100ZhabanCount": zhaban,
        "top100ZhabanShare": _safe_divide(zhaban, size),
    }


def build_yesterday_hot_limit_evidence(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayHotLimitEvidence L656-712
    empty = {"count": 0, "retainedTop100Count": 0, "avgChange": None, "positiveRate": None, "weakeningRate": None, "failedOrWeakRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_limit_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if _has_limit_up_evidence(row) and normalize_code(row.get("code"))
    ]
    if not yesterday_limit_codes:
        return empty

    matched = retained = positive = weakening = failed_or_weak = 0
    change_sum = 0.0
    for code in yesterday_limit_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            failed_or_weak += 1
            continue
        change = to_number(stock.get("change"))
        today_label = resolve_stock_status(stock, today_rows)
        is_risk = today_label in ("资金背离", "转弱预警")
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or is_risk:
            weakening += 1
        if change <= 0 or is_risk or not get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            failed_or_weak += 1
    return {
        "count": len(yesterday_limit_codes),
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningRate": _safe_divide(weakening, len(yesterday_limit_codes)),
        "failedOrWeakRate": _safe_divide(failed_or_weak, len(yesterday_limit_codes)),
    }


def build_limit_evidence(today_rows: list[dict], yesterday_rows: list[dict], top_n: int | None, market_data: dict | None) -> dict:
    # TS: buildLimitEvidence L714-725
    return {
        "market": build_market_limit_evidence(market_data),
        "intersection": build_limit_intersection_evidence(today_rows, top_n),
        "yesterdayHotLimit": build_yesterday_hot_limit_evidence(yesterday_rows, today_rows, top_n),
    }


def build_yesterday_strong_performance(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayStrongPerformance L754-814
    empty = {"count": 0, "matchedCount": 0, "retainedTop100Count": 0, "avgChange": None,
             "positiveCount": 0, "positiveRate": None, "weakeningCount": 0, "weakeningRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    strong_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if resolve_stock_status(row, yesterday_rows) in _YESTERDAY_STRONG_LABELS and normalize_code(row.get("code"))
    ]
    if not strong_codes:
        return empty

    matched = retained = positive = weakening = 0
    change_sum = 0.0
    for code in strong_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            continue
        change = to_number(stock.get("change"))
        today_label = resolve_stock_status(stock, today_rows)
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or today_label in ("资金背离", "转弱预警"):
            weakening += 1
    return {
        "count": len(strong_codes),
        "matchedCount": matched,
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveCount": positive,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningCount": weakening,
        "weakeningRate": _safe_divide(weakening, len(strong_codes)),
    }


def build_comparison(stocks: list[dict], yesterday_rows: list[dict], day_before_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildComparison L816-892
    today_rows = sort_rows(stocks)
    yesterday_sorted = sort_rows(yesterday_rows)
    day_before_sorted = sort_rows(day_before_rows)
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_sorted, top_n)
    day_before_size = _resolve_sample_size(day_before_sorted, top_n)

    today = build_day_metrics_from_sorted(today_rows, today_size)
    yesterday = build_day_metrics_from_sorted(yesterday_sorted, yesterday_size) if yesterday_sorted else None
    day_before = build_day_metrics_from_sorted(day_before_sorted, day_before_size) if day_before_sorted else None

    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_top_codes = {normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]}
    day_before_top_codes = {normalize_code(row.get("code")) for row in day_before_sorted[:day_before_size]}
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}

    retain_from_yesterday = len([c for c in today_top_codes if c in yesterday_top_codes])
    retain_from_day_before = len([c for c in today_top_codes if c in day_before_top_codes])
    new_top_codes = [c for c in today_top_codes if c not in yesterday_top_codes]
    new_strong = sum(
        1 for code in new_top_codes
        if code in today_by_code and resolve_stock_status(today_by_code[code], today_rows) == "强资确认"
    )
    yesterday_strong_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if resolve_stock_status(row, yesterday_sorted) == "强资确认" and normalize_code(row.get("code"))
    ]
    yesterday_crowded_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if resolve_stock_status(row, yesterday_sorted) == "高位拥挤" and normalize_code(row.get("code"))
    ]
    yesterday_strong_retain = (
        _safe_divide(len([c for c in yesterday_strong_codes if c in today_top_codes]), len(yesterday_strong_codes))
        if yesterday_strong_codes else None
    )
    yesterday_crowded_risk = sum(
        1 for code in yesterday_crowded_codes
        if code in today_by_code and resolve_stock_status(today_by_code[code], today_rows) in ("资金背离", "转弱预警")
    )
    return {
        "today": today,
        "yesterday": yesterday,
        "dayBefore": day_before,
        "totalChange1d": today["total"] - yesterday["total"] if yesterday else None,
        "totalChange2d": today["total"] - day_before["total"] if day_before else None,
        "top100RetainFromYesterday": retain_from_yesterday,
        "top100RetainFromDayBefore": retain_from_day_before,
        "top100RetainRateFromYesterday": _safe_divide(retain_from_yesterday, yesterday_size or today_size),
        "top100RetainRateFromDayBefore": _safe_divide(retain_from_day_before, day_before_size or today_size),
        "newTop100Count": len(new_top_codes),
        "newTop100StrongMoneyCount": new_strong,
        "yesterdayStrongRetainRate": yesterday_strong_retain,
        "yesterdayCrowdedRiskCount": yesterday_crowded_risk,
        "yesterdayStrongPerformance": build_yesterday_strong_performance(yesterday_sorted, today_rows, top_n),
    }
```

- [ ] **Step 4: 运行本任务测试通过**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v`
Expected: 全部 PASS（含 Task 2 的 4 个）。失败时逐行对照 TS 对应函数修正，不改 golden。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/hotlist/sentiment.py quant-board/tests/test_hotlist_sentiment_compute.py
git commit -m "feat(sentiment): 纯函数状态解析(displayStatus优先)+涨停证据+三日对比（golden 对齐）"
```

---

### Task 4: Python 纯函数——5 证据 evaluator + resolveStage 级联 + 主入口

**Files:**

- Modify: `quant-board/backend/analysis/hotlist/sentiment.py`（追加 evaluator/resolveStage/compute_hotlist_sentiment）
- Modify: `quant-board/tests/test_hotlist_sentiment_compute.py`（追加全量 golden 断言）

**Interfaces:**

- Consumes: Task 2/3 全部函数；`EMOTION_CYCLE_STAGE_CONFIG` 阶段基础分（冰点 56/启动 58/发酵 62/高潮 64/退潮 64，直接常量 `_STAGE_CONFIDENCE_BASE`）。
- Produces:
  - `compute_hotlist_sentiment(stocks, yesterday=None, day_before=None, market_data=None, top_n=None) -> dict`——完整 TS HotListSentimentResult 结构（stage/riskLevel/confidence/summary/metrics{topN,layers,comparison,limitEvidence}/turnover/signals/warnings + 后端超集键 statusSourceCounts/missingEvidence）。
  - `resolve_stage(comparison, layers, limit_evidence) -> dict`（stage/riskLevel/signals/warnings）
  - `_js_to_fixed(value, digits) -> str`（JS toFixed 半进位等价，文案格式化用）

- [ ] **Step 1: 写失败测试（全量 golden 对齐）**

追加到 `test_hotlist_sentiment_compute.py`：

```python
from backend.analysis.hotlist.sentiment import compute_hotlist_sentiment

# 阶段判定 + 风险 + 信号/警告文案全量对齐的 7+3 个 case（名称与 golden_cases.json 一致）
STAGE_CASES = [
    "强扩散但高拥挤时识别为高潮",
    "强资确认增加且风险低时识别为发酵",
    "新入和机会状态改善时识别为启动",
    "风险状态上升且 TRIN 偏弱时识别为退潮",
    "上涨承接较强时高风险压力不直接判为退潮",
    "严重风险叠加昨日强票失败且成交承接转弱时识别为退潮",
    "热榜收缩且机会少时识别为冰点",
    "输出前20、前50、前100分层统计",
    "输出全池 all 分层统计",
    "按A股板块阈值统计热榜涨停和近涨停证据",
    "热榜涨停证据只使用热榜交集，全市场数据仅作为背景",
    "THS炸板池和涨停股回撤榜只作为全市场补充证据",
    "昨日热榜涨停今日表现纳入持续性证据",
    "fallback status ignores suspicious capped volume ratio when detecting crowded stocks",
    "统计昨日强票今日平均涨幅、正收益率和转弱率",
    "默认使用全热榜池统计主情绪指标",
    "分析结果包含当日 turnover 汇总",
]


def _to_py_input(raw_input: dict) -> dict:
    def snap(snapshot: dict | None) -> dict | None:
        if not snapshot:
            return None
        return {"tradingDate": snapshot.get("tradingDate"), "rows": snapshot.get("hotlist") or snapshot.get("rows") or []}
    return {
        "stocks": raw_input.get("stocks") or [],
        "yesterday": snap(raw_input.get("yesterday")),
        "day_before": snap(raw_input.get("dayBefore")),
        "market_data": raw_input.get("marketData"),
        "top_n": raw_input.get("topN"),
    }


@pytest.mark.parametrize("name", STAGE_CASES)
def test_golden_stage_full_alignment(name: str) -> None:
    case = get_case(load_golden_cases(), name)
    if "todayStocks" in case["input"]:   # computeTurnover 直测 case，不经 analyze
        pytest.skip("computeTurnover case 已由 test_golden_turnover_details 覆盖")
    result = compute_hotlist_sentiment(**_to_py_input(case["input"]))
    expected = case["expected"]
    assert result["stage"] == expected["stage"], f"stage: {result['stage']} != {expected['stage']}"
    assert result["riskLevel"] == expected["riskLevel"]
    assert result["confidence"] == expected["confidence"]
    assert result["summary"] == expected["summary"]
    assert result["signals"] == expected["signals"], f"signals 差异:\n got={result['signals']}\n exp={expected['signals']}"
    assert result["warnings"] == expected["warnings"], f"warnings 差异:\n got={result['warnings']}\n exp={expected['warnings']}"
    assert result["turnover"] == expected["turnover"]
    expected_metrics = expected["metrics"]
    assert result["metrics"]["topN"] == expected_metrics["topN"]
    for layer in ("top20", "top50", "top100", "all"):
        assert result["metrics"]["layers"][layer]["statusCounts"] == expected_metrics["layers"][layer]["statusCounts"], layer
        assert result["metrics"]["layers"][layer]["hotTrin"] == expected_metrics["layers"][layer]["hotTrin"], layer
        assert result["metrics"]["layers"][layer]["nearLimitUpCount"] == expected_metrics["layers"][layer]["nearLimitUpCount"], layer
    cmp_expected = expected_metrics["comparison"]
    cmp_result = result["metrics"]["comparison"]
    for key in ("totalChange1d", "totalChange2d", "top100RetainFromYesterday", "top100RetainFromDayBefore",
                "newTop100Count", "newTop100StrongMoneyCount", "yesterdayStrongRetainRate", "yesterdayCrowdedRiskCount"):
        assert cmp_result[key] == cmp_expected[key], key
    assert cmp_result["yesterdayStrongPerformance"] == cmp_expected["yesterdayStrongPerformance"]
    assert result["metrics"]["limitEvidence"] == expected_metrics["limitEvidence"]


def test_insufficient_data_marks_missing_evidence():
    result = compute_hotlist_sentiment([])
    assert result["stage"] == "冰点"
    assert result["metrics"]["comparison"]["today"]["topN"] == 0
    assert result["statusSourceCounts"] == {"displayStatus": 0, "fallback": 0}


def test_summary_generated_for_each_stage():
    from backend.analysis.hotlist.sentiment import _STAGE_SUMMARY
    for stage in _STAGE_SUMMARY:
        assert _STAGE_SUMMARY[stage]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v -k golden_stage`
Expected: ImportError（`compute_hotlist_sentiment` 未定义）。

- [ ] **Step 3: 实现 evaluator + 级联 + 主入口**

追加到 `sentiment.py`（完整实现；`_js_to_fixed` 用 `decimal` 实现半进位）：

```python
from decimal import Decimal, ROUND_HALF_UP


def _js_to_fixed(value: float, digits: int = 0) -> str:
    # JS toFixed 等价：四舍五入半进位（Python format 是银行家舍入）
    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# TS: EMOTION_CYCLE_STAGE_CONFIG.confidenceBase（src/types/emotion.ts）
_STAGE_CONFIDENCE_BASE = {"冰点": 56, "启动": 58, "发酵": 62, "高潮": 64, "退潮": 64}
# TS: getEmotionCycleStageSummary 的五阶段 summary 文案（从 src/types/emotion.ts EMOTION_CYCLE_STAGE_CONFIG.summary 逐字复制）
_STAGE_SUMMARY = {
    "冰点": "机会稀少，风险或弱承接占优，优先控制仓位和交易频率。",
    "启动": "情绪开始修复，新增线索和点火机会增多，但持续性仍待确认。",
    "发酵": "强资金、点火和主线扩散形成合力，交易情绪处于扩散阶段。",
    "高潮": "前排强度和资金承接较强，但拥挤明显，适合强势识别，不宜盲目追高。",
    "退潮": "风险状态升温或强票承接走弱，交易情绪进入防守优先阶段。",
}


def _push_if(target: list[str], condition: bool, text: str) -> None:
    if condition:
        target.append(text)


def _evaluate_tape_strength(today: dict, layers: dict | None) -> dict:
    # TS: evaluateTapeStrength L918-936
    top20 = (layers or {}).get("top20") or today
    top50 = (layers or {}).get("top50") or today
    signals: list[str] = []
    warnings: list[str] = []
    strong = top20["upRatio"] >= 0.65 and top50["upRatio"] >= 0.55 and today["upRatio"] >= 0.55
    firm = top20["upRatio"] >= 0.6 and today["upRatio"] >= 0.48
    weak = today["upRatio"] <= 0.42 or (top20["upRatio"] < 0.5 and top50["upRatio"] < 0.45)
    level = "strong" if strong else "firm" if firm else "weak" if weak else "mixed"
    _push_if(signals, strong, "前20/前50/全池上涨扩散较强")
    _push_if(signals, not strong and firm, "前排上涨修复，全池仍有承接")
    _push_if(signals, today["nearLimitUpCount"] >= 8, f"全池近涨停 {today['nearLimitUpCount']} 只")
    _push_if(signals, today["highGainCount"] >= 18, f"全池高涨幅 {today['highGainCount']} 只")
    _push_if(warnings, weak, f"热榜上涨宽度偏弱，全池上涨 {_js_to_fixed(today['upRatio'] * 100)}%")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_money_acceptance(today: dict) -> dict:
    # TS: evaluateMoneyAcceptance L938-954
    signals: list[str] = []
    warnings: list[str] = []
    level = "neutral"
    trin = today["hotTrin"]
    if trin is None:
        level = "unknown"
    elif trin < 1:
        level = "strong"
        signals.append(f"热榜 TRIN {_js_to_fixed(trin, 2)}，上涨股成交承接占优")
    elif trin > 1.15:
        level = "weak"
        warnings.append(f"热榜 TRIN {_js_to_fixed(trin, 2)}，上涨家数与成交承接不匹配")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_opportunity_expansion(comparison: dict) -> dict:
    # TS: evaluateOpportunityExpansion L956-978
    today = comparison["today"]
    yesterday = comparison.get("yesterday")
    signals: list[str] = []
    warnings: list[str] = []
    active_share = today["activeOpportunityShare"]
    strong_money_share = today["statusShares"]["强资确认"]
    opportunity_rising = bool(yesterday and active_share > yesterday["activeOpportunityShare"] + 0.04)
    broad = active_share >= 0.18 and strong_money_share >= 0.08
    improving = opportunity_rising or comparison["newTop100Count"] >= 25
    scarce = active_share < 0.08
    level = "broad" if broad else "improving" if improving else "scarce" if scarce else "normal"
    _push_if(signals, broad, f"强资确认与点火观察形成扩散，占比 {_js_to_fixed(active_share * 100)}%")
    _push_if(signals, not broad and opportunity_rising, "有效机会占比较昨日改善")
    _push_if(signals, not broad and comparison["newTop100Count"] >= 25, f"今日新入全池 {comparison['newTop100Count']} 只")
    _push_if(warnings, scarce, f"有效机会偏少，占比 {_js_to_fixed(active_share * 100)}%")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_risk_pressure(comparison: dict) -> dict:
    # TS: evaluateRiskPressure L980-1005
    today = comparison["today"]
    yesterday = comparison.get("yesterday")
    signals: list[str] = []
    warnings: list[str] = []
    risk_rising = bool(yesterday and today["riskShare"] > yesterday["riskShare"] + 0.04)
    crowded_rising = bool(yesterday and today["crowdedShare"] > yesterday["crowdedShare"] + 0.04)
    if today["riskShare"] >= 0.35:
        level = "severe"
    elif today["riskShare"] >= 0.2 or risk_rising:
        level = "high"
    elif today["crowdedShare"] >= 0.18 or crowded_rising:
        level = "crowded"
    else:
        level = "low"
    _push_if(warnings, today["riskShare"] >= 0.35, f"风险压力 {_js_to_fixed(today['riskShare'] * 100)}%，资金背离与转弱预警偏高")
    _push_if(warnings, 0.2 <= today["riskShare"] < 0.35, f"风险压力 {_js_to_fixed(today['riskShare'] * 100)}%")
    _push_if(warnings, risk_rising, "资金背离与转弱预警占比上升")
    _push_if(warnings, today["crowdedShare"] >= 0.18, f"高位拥挤 {_js_to_fixed(today['crowdedShare'] * 100)}%")
    _push_if(warnings, crowded_rising, "高位拥挤占比上升")
    _push_if(signals, level == "low", "风险压力暂未扩散")
    return {"level": level, "signals": signals, "warnings": warnings}


def _evaluate_continuity(comparison: dict) -> dict:
    # TS: evaluateContinuity L1007-1036
    signals: list[str] = []
    warnings: list[str] = []
    retain_rate = comparison.get("yesterdayStrongRetainRate")
    performance = comparison["yesterdayStrongPerformance"]
    positive_rate = performance.get("positiveRate")
    weakening_rate = performance.get("weakeningRate")
    weak = (weakening_rate is not None and weakening_rate >= 0.45) or (retain_rate is not None and retain_rate <= 0.25)
    strong = (not weak) and (
        (positive_rate is not None and positive_rate >= 0.6) or (retain_rate is not None and retain_rate >= 0.6)
    )
    _push_if(signals, retain_rate is not None and retain_rate >= 0.6, "昨日强资确认留榜率较高")
    _push_if(warnings, retain_rate is not None and retain_rate <= 0.25, "昨日强资确认留榜率偏低")
    _push_if(signals, positive_rate is not None and positive_rate >= 0.6,
             f"昨日强票今日正收益率 {_js_to_fixed((positive_rate or 0) * 100)}%")
    _push_if(warnings, weakening_rate is not None and weakening_rate >= 0.45,
             f"昨日强票转弱或掉榜率 {_js_to_fixed((weakening_rate or 0) * 100)}%")
    return {"level": "weak" if weak else "strong" if strong else "normal", "signals": signals, "warnings": warnings}


def _collect_limit_evidence_messages(limit_evidence: dict | None) -> dict:
    # TS: collectLimitEvidenceMessages L1038-1091
    signals: list[str] = []
    warnings: list[str] = []
    if not limit_evidence:
        return {"level": "neutral", "signals": signals, "warnings": warnings}
    market = limit_evidence["market"]
    intersection = limit_evidence["intersection"]
    yesterday_hot = limit_evidence["yesterdayHotLimit"]
    ths = market.get("thsPools") or {}
    _push_if(signals, intersection["top100LimitUpCount"] > 0 or intersection["top100NearLimitUpCount"] > 0,
             f"热榜全池涨停 {intersection['top100LimitUpCount']} 只，近涨停 {intersection['top100NearLimitUpCount']} 只")
    _push_if(signals, intersection["top100Board2PlusCount"] > 0,
             f"热榜全池二板以上 {intersection['top100Board2PlusCount']} 只，最高 {intersection['top100MaxBoardHeight']} 板")
    _push_if(signals, market["ztCount"] > 0,
             f"全市场涨停 {market['ztCount']} 只，封板率 {_js_to_fixed(market['fengbanRate'])}%")
    positive = yesterday_hot.get("positiveRate")
    _push_if(signals, positive is not None and positive >= 0.55,
             f"昨日热榜涨停今日正收益率 {_js_to_fixed((positive or 0) * 100)}%")
    _push_if(warnings, intersection["top100ZhabanCount"] > 0, f"热榜全池个股炸板 {intersection['top100ZhabanCount']} 只")
    failed_weak = yesterday_hot.get("failedOrWeakRate")
    _push_if(warnings, failed_weak is not None and failed_weak >= 0.5,
             f"昨日热榜涨停走弱或冲板失败率 {_js_to_fixed((failed_weak or 0) * 100)}%")
    _push_if(warnings, market["zhabanCount"] > 0, f"全市场炸板 {market['zhabanCount']} 只，仅作背景参考")
    _push_if(warnings, (ths.get("failedCount") or 0) > 0, f"THS炸板池 {ths.get('failedCount')} 只，仅作全市场炸板补充证据")
    _push_if(warnings, (ths.get("drawdownCount") or 0) > 0,
             f"{ths.get('drawdownRiskLabel')} {ths.get('drawdownCount')} 只，不等同于全市场亏钱效应")
    return {"level": "neutral", "signals": signals, "warnings": warnings}


def _resolve_risk_level(risk_pressure: dict, continuity: dict) -> str:
    # TS: resolveRiskLevel L1097-1108
    risk = risk_pressure["level"]
    cont = continuity["level"]
    if risk == "severe" or (risk == "high" and cont == "weak"):
        return "高"
    if risk in ("high", "crowded") or cont == "weak":
        return "中"
    return "低"


def resolve_stage(comparison: dict, layers: dict | None = None, limit_evidence: dict | None = None) -> dict:
    # TS: resolveStage L1110-1267 —— 级联顺序 retreat → climax → ferment → start → ice，逐条布尔条件不许简化
    today = comparison["today"]
    tape = _evaluate_tape_strength(today, layers)
    money = _evaluate_money_acceptance(today)
    expansion = _evaluate_opportunity_expansion(comparison)
    risk_pressure = _evaluate_risk_pressure(comparison)
    continuity = _evaluate_continuity(comparison)
    limit_messages = _collect_limit_evidence_messages(limit_evidence)
    signals = tape["signals"] + money["signals"] + expansion["signals"] + risk_pressure["signals"] + continuity["signals"] + limit_messages["signals"]
    warnings = tape["warnings"] + money["warnings"] + expansion["warnings"] + risk_pressure["warnings"] + continuity["warnings"] + limit_messages["warnings"]

    change1d = comparison.get("totalChange1d")
    total_expanded = change1d is not None and change1d > 0
    total_shrank = change1d is not None and change1d < 0
    risk_elevated = risk_pressure["level"] in ("high", "severe")
    risk_level = _resolve_risk_level(risk_pressure, continuity)
    tape_weak = tape["level"] == "weak"
    tape_strong = tape["level"] == "strong"
    tape_at_least_firm = tape["level"] in ("strong", "firm")
    money_weak = money["level"] == "weak"
    money_not_weak = money["level"] != "weak"
    money_strong = money["level"] == "strong"
    effective_spread = today["activeOpportunityShare"] >= 0.12 and today["statusShares"]["强资确认"] >= 0.08
    broad_spread = expansion["level"] == "broad"
    high_heat = today["nearLimitUpCount"] >= 10 or (today["highGainCount"] >= 25 and today["highTurnoverCount"] >= 20)
    intersection = (limit_evidence or {}).get("intersection")
    yesterday_hot = (limit_evidence or {}).get("yesterdayHotLimit")
    limit_spread = bool(intersection and (intersection["top100LimitUpCount"] >= 6 or intersection["top100NearLimitUpCount"] >= 10))
    front_limit_hot = bool(intersection and (intersection["top20LimitUpCount"] >= 3 or intersection["top50LimitUpCount"] >= 6))
    limit_height_confirmed = bool(intersection and (intersection["top100Board2PlusCount"] >= 3 or intersection["top100MaxBoardHeight"] >= 3))
    yesterday_limit_weak = bool(
        yesterday_hot and yesterday_hot["count"] >= 3
        and yesterday_hot.get("failedOrWeakRate") is not None and yesterday_hot["failedOrWeakRate"] >= 0.5
    )
    severe_risk_shrink = (
        risk_pressure["level"] == "severe" and total_shrank
        and expansion["level"] != "broad" and money["level"] != "strong"
    )

    _push_if(signals, total_expanded, f"热榜池较上一日扩张 {comparison['totalChange1d']} 只")
    _push_if(warnings, total_shrank, f"热榜池较上一日收缩 {abs(comparison.get('totalChange1d') or 0)} 只")
    _push_if(warnings, risk_level == "高" and not tape_weak and not money_weak,
             "风险等级高，但上涨和成交承接尚未破坏，按阶段主方向处理")

    retreat = (
        severe_risk_shrink
        or (yesterday_limit_weak and risk_elevated and (tape_weak or money_weak))
        or (risk_elevated and (tape_weak or money_weak))
        or (risk_pressure["level"] == "severe" and continuity["level"] == "weak"
            and today["upRatio"] < 0.52 and money["level"] != "strong")
        or (total_shrank and expansion["level"] == "scarce" and today["upRatio"] < 0.5 and (risk_elevated or money_weak))
    )
    if retreat:
        return {"stage": "退潮", "riskLevel": risk_level, "signals": signals,
                "warnings": warnings or ["风险状态占比偏高，先按防守阶段处理"]}

    climax = tape_strong and money_not_weak and (
        (money_strong and high_heat and broad_spread)
        or (front_limit_hot and limit_height_confirmed and today["crowdedShare"] >= 0.16 and broad_spread)
        or (today["nearLimitUpCount"] >= 8 and today["crowdedShare"] >= 0.18 and broad_spread)
        or (today["crowdedShare"] >= 0.28 and today["activeOpportunityShare"] >= 0.22)
    )
    if climax:
        return {"stage": "高潮", "riskLevel": risk_level,
                "signals": signals or ["前排高涨幅与高位拥挤同时增加"],
                "warnings": warnings or ["热度强但追击赔率下降，注意高位兑现风险"]}

    ferment = (
        (expansion["level"] == "broad" or effective_spread or (limit_spread and today["activeOpportunityShare"] >= 0.12))
        and tape_at_least_firm and money_not_weak
    )
    if ferment:
        return {"stage": "发酵", "riskLevel": risk_level,
                "signals": signals or ["强资确认与点火观察形成有效扩散"], "warnings": warnings}

    start = (
        (total_expanded or expansion["level"] == "improving" or comparison["newTop100Count"] >= 25
         or ((intersection or {}).get("top100NearLimitUpCount") or 0) >= 3)
        and today["upRatio"] >= 0.42 and money_not_weak and not tape_weak
    )
    if start:
        return {"stage": "启动", "riskLevel": risk_level,
                "signals": signals or ["热榜新增和机会状态开始改善"], "warnings": warnings}

    return {"stage": "冰点", "riskLevel": risk_level,
            "signals": signals or ["热榜机会状态尚未形成有效扩散"],
            "warnings": warnings or ["强资确认与点火观察偏少，等待下一轮扩散确认"]}


def _calculate_confidence(stage: str, signals: list[str], warnings: list[str]) -> int:
    # TS: calculateConfidence L1269-1273
    base = _STAGE_CONFIDENCE_BASE.get(stage, 58)
    adjustment = min(18, len(signals) * 5) - min(12, len(warnings) * 3)
    return max(45, min(90, base + adjustment))


def compute_hotlist_sentiment(
    stocks: list[dict],
    yesterday: dict | None = None,
    day_before: dict | None = None,
    market_data: dict | None = None,
    top_n: int | None = None,
) -> dict:
    # TS: analyze L1276-1303 的 Python 等价主入口
    sorted_stocks = sort_rows(stocks)
    yesterday_rows = sort_rows((yesterday or {}).get("rows") or [])
    top_n = top_n if top_n and top_n > 0 else None
    sample_size = _resolve_sample_size(sorted_stocks, top_n)
    layers = build_layer_metrics(stocks)
    comparison = build_comparison(stocks, yesterday_rows, sort_rows((day_before or {}).get("rows") or []), top_n)
    limit_evidence = build_limit_evidence(sorted_stocks, yesterday_rows, top_n, market_data)
    stage_evidence = resolve_stage(comparison, layers, limit_evidence)
    confidence = _calculate_confidence(stage_evidence["stage"], stage_evidence["signals"], stage_evidence["warnings"])

    status_source = {"displayStatus": 0, "fallback": 0}
    for row in sorted_stocks:
        resolve_stock_status(row, sorted_stocks, status_source)

    missing_evidence: list[str] = []
    if not market_data:
        missing_evidence.append("marketData")
    if not yesterday_rows:
        missing_evidence.append("yesterday")

    return {
        "stage": stage_evidence["stage"],
        "riskLevel": stage_evidence["riskLevel"],
        "confidence": confidence,
        "summary": _STAGE_SUMMARY[stage_evidence["stage"]],
        "metrics": {
            "topN": sample_size,
            "layers": layers,
            "comparison": comparison,
            "limitEvidence": limit_evidence,
        },
        "turnover": compute_turnover(sorted_stocks, yesterday_rows),
        "signals": stage_evidence["signals"],
        "warnings": stage_evidence["warnings"],
        "statusSourceCounts": status_source,
        "missingEvidence": missing_evidence,
    }
```

- [ ] **Step 4: 运行全量 golden 对齐**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py -v`
Expected: 全部 PASS。常见失败与修法：① signals 文案浮点差异 → 用 `_js_to_fixed` 对齐 TS toFixed 语义；② stage 不符 → 逐条对照 TS resolveStage 布尔条件查遗漏；③ statusCounts 差 → 查 fallback 分类顺序。**不得修改 golden fixture**（除非确认 fixture 本身错误，需在 commit message 说明）。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/hotlist/sentiment.py quant-board/tests/test_hotlist_sentiment_compute.py
git commit -m "feat(sentiment): 纯函数 5 证据 evaluator + resolveStage 级联 + 主入口，18 case golden 全量对齐"
```

---

### Task 5: operations 统一——EOD 入库切换到纯函数

**Files:**

- Modify: `quant-board/backend/operations/hotlist_sentiment.py`
- Modify: `quant-board/tests/test_hotlist_sentiment_backfill.py`（适配）
- Read: `quant-board/tests/test_hotlist_sentiment_repo.py`（确认不依赖被删函数）

**Interfaces:**

- Consumes: `compute_hotlist_sentiment`（Task 4）。
- Produces:
  - `build_hotlist_sentiment_document(*, dataset_id, snapshot_type, trading_date, frame, stocks, yesterday_stocks=None, day_before_stocks=None, market_data=None) -> dict`——输出仍满足现有库 schema（stage/riskLevel/confidence/summary/metrics/turnover/signals/warnings + `_id` 等），metrics 为现有键 + 新超集键；`market_data` 由 Task 6 的 compute service 传入（limitSummary 映射），默认 None 时行为与既有调用完全一致。
  - `HotListSentimentBackfillService.run_for_date` 新增 `day_before_stocks` 取数（前两个交易日）；取数方法去下划线转公开（`_trading_dates`→`trading_dates`、`_latest_frame`→`latest_frame`、`_stocks_for_frame`→`stocks_for_frame`、`_previous_day_stocks`→`previous_day_stocks`），operations 内部调用点同步更新（Task 6 的 compute service 跨服务调用这些公开方法）。
  - 删除 `_resolve_stage` / `_fallback_status_label` / `_confidence` / `_compute_metrics` / `_hot_trin`（口径统一到纯函数）。

- [ ] **Step 1: 确认现有 backfill 测试对旧行为的依赖**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py -v`
记录哪些断言会因口径切换失败（如断言 `_resolve_stage` 产出的具体 stage）。

- [ ] **Step 2: 重写 `build_hotlist_sentiment_document`（先改测试再改实现）**

在 `test_hotlist_sentiment_backfill.py` 追加口径测试（schema 保持 + 纯函数联动）：

```python
def test_build_document_uses_pure_function_schema():
    from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

    frame = {"snapshotId": "s1", "slotTime": "14:30", "timestamp": 1757000000}
    stocks = [
        {"code": "000001", "name": "甲", "compRank": 1, "change": 9.9, "turnover": 15e8,
         "zlje": 2e8, "zljzb": 15, "cddje": 8000e4, "cddjzb": 6, "volumeRatio": 2.0, "turnoverRate": 12},
        {"code": "000002", "name": "乙", "compRank": 2, "change": -3.5, "turnover": 3e8,
         "zlje": -1e8, "zljzb": -9, "cddje": -4000e4, "cddjzb": -4},
    ]
    doc = build_hotlist_sentiment_document(
        dataset_id="dragonboard_live", snapshot_type="half_hour",
        trading_date="2026-06-05", frame=frame, stocks=stocks,
    )
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    for key in ("datasetId", "snapshotType", "tradingDate", "snapshotId", "slotTime", "timestamp",
                "computedAt", "stage", "riskLevel", "confidence", "summary", "metrics", "turnover", "signals", "warnings"):
        assert key in doc, key
    metrics = doc["metrics"]
    for key in ("poolSize", "allPoolUpRatio", "hotTrin", "retentionRate1d", "retentionRate2d",
                "limitIntersectionRate", "newEntryCount", "eliminatedCount", "nearLimitUpCount",
                "highGainCount", "riskShare", "activeOpportunityShare", "strongMoneyShare", "crowdedShare"):
        assert key in metrics, key
    assert metrics["poolSize"] == 2
    assert doc["stage"] in ("冰点", "启动", "发酵", "高潮", "退潮")
    assert doc["riskLevel"] in ("低", "中", "高")
    assert "layers" in metrics and "limitEvidence" in metrics   # 超集键透出
```

然后重写 `build_hotlist_sentiment_document`（保留函数签名风格，内部编排纯函数）：

```python
from backend.analysis.hotlist.sentiment import compute_hotlist_sentiment

# TS persistHotListSentiment（HotListSentimentAnalyzer.ts L1306-1338）的 metrics 映射口径：
# 现有库文档键 ← 纯函数超集结果
def _metrics_projection(result: dict) -> dict:
    all_layer = result["metrics"]["layers"]["all"]
    comparison = result["metrics"]["comparison"]
    intersection = result["metrics"]["limitEvidence"]["intersection"]
    return {
        "poolSize": all_layer["total"],
        "topN": all_layer["topN"],
        "allPoolUpRatio": all_layer["upRatio"],
        "hotTrin": all_layer["hotTrin"],
        "retentionRate1d": comparison["top100RetainRateFromYesterday"],
        "retentionRate2d": comparison["top100RetainRateFromDayBefore"],
        "limitIntersectionRate": intersection["top100LimitUpShare"],
        "newEntryCount": len(result["turnover"]["newEntries"]),
        "eliminatedCount": len(result["turnover"]["eliminated"]),
        "nearLimitUpCount": all_layer["nearLimitUpCount"],
        "highGainCount": all_layer["highGainCount"],
        "riskShare": all_layer["riskShare"],
        "activeOpportunityShare": all_layer["activeOpportunityShare"],
        "strongMoneyShare": all_layer["statusShares"]["强资确认"],
        "crowdedShare": all_layer["crowdedShare"],
        "layers": result["metrics"]["layers"],
        "comparison": comparison,
        "limitEvidence": result["metrics"]["limitEvidence"],
        "statusSourceCounts": result["statusSourceCounts"],
        "missingEvidence": result["missingEvidence"],
    }


def build_hotlist_sentiment_document(
    *,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    frame: dict[str, Any],
    stocks: list[dict[str, Any]],
    yesterday_stocks: list[dict[str, Any]] | None = None,
    day_before_stocks: list[dict[str, Any]] | None = None,
    market_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = compute_hotlist_sentiment(
        stocks,
        yesterday={"rows": yesterday_stocks or []},
        day_before={"rows": day_before_stocks or []},
        market_data=market_data,
    )
    return {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}",
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "snapshotId": frame.get("snapshotId"),
        "slotTime": frame.get("slotTime"),
        "timestamp": frame.get("timestamp"),
        "computedAt": int(time.time()),
        "stage": result["stage"],
        "riskLevel": result["riskLevel"],
        "confidence": result["confidence"],
        "summary": result["summary"],
        "metrics": _metrics_projection(result),
        "turnover": result["turnover"],
        "signals": result["signals"],
        "warnings": result["warnings"],
    }
```

- [ ] **Step 3: 删除旧口径函数 + backfill 取数扩展**

删除 `operations/hotlist_sentiment.py` 中被替代的函数（逐个确认无其他引用后删）：`_resolve_stage`、`_fallback_status_label`、`_confidence`、`_compute_metrics`、`_hot_trin`、`_turnover`、`HIGH_POSITION_RANK_CUTOFF`。保留：`_compute_turnover`（若 backfill 测试直接引用则改为纯函数 `compute_turnover` 的转发或直接删除引用）、`_entry_reason`/`_exit_reason`（若仅被 `_compute_turnover` 用则一并删）。

`_previous_day_stocks` 改造为取前两个交易日，并按 Interfaces 约定**同步去下划线更名公开**（Task 6 compute service 跨服务调用）：

```python
    def previous_day_stocks(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, list[dict[str, Any]]]:
        dates = [d for d in self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type) if d < trading_date]
        result: dict[str, list[dict[str, Any]]] = {}
        if dates:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-1])
            result["yesterday"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
        if len(dates) >= 2:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-2])
            result["day_before"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
        return result
```

（同批更名：`_trading_dates`→`trading_dates`、`_latest_frame`→`latest_frame`、`_stocks_for_frame`→`stocks_for_frame`、`_previous_day_stocks`→`previous_day_stocks`；operations 文件内全部调用点用 rg 定位逐处更新。）

`run_for_date` 调用处同步改为：

```python
        previous = self.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
        )
```

- [ ] **Step 4: 适配既有 backfill 测试**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py -v`
对 Step 1 记录的失败断言：凡断言"入库文档含某键/入库行为"的保留；凡断言旧 `_resolve_stage` 具体阶段产出的，改为断言 `doc["stage"] in 五阶段` 或改用纯函数 golden 已覆盖的口径注释说明（stage 正确性由 Task 4 golden 保证，backfill 测试只管 schema 与入库行为）。

- [ ] **Step 5: 全量相关验证**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add quant-board/backend/operations/hotlist_sentiment.py quant-board/tests/test_hotlist_sentiment_backfill.py
git commit -m "feat(sentiment): EOD 入库统一到 analysis 纯函数口径（消除后端简化版双口径）"
```

---

### Task 6: lazy-compute 编排 + `GET /api/hotlist-sentiment/series` 读口

**Files:**

- Create: `quant-board/backend/services/theme/hotlist_sentiment_compute.py`
- Modify: `quant-board/backend/api/hotlist_routes.py`（追加 GET /series）
- Create: `quant-board/tests/test_hotlist_sentiment_series_api.py`

**Interfaces:**

- Consumes: `HotListSentimentBackfillService` 公开取数方法（Task 5：`trading_dates`/`latest_frame`/`stocks_for_frame`/`previous_day_stocks`）、`build_hotlist_sentiment_document`（Task 5，含 `market_data` 参数）、`HotListSentimentService.get_by_date/upsert`（现有）、`MongoRepository(db).load_snapshot_analysis(dataset_id, snapshot_id, codes) -> dict[str, dict]`（`mongo_repository.py` L1243-1251，实例方法——返回 `{code: analysis}`，displayStatus 是 analysis dict 内的条目）。
- Produces
  - `HotListSentimentComputeService(mongo_db).ensure_series(dataset_id, snapshot_type, days) -> list[dict]`——升序返回最多 `days` 条；每条为库文档或 `{"tradingDate": ..., "missing": True, "reason": "..."}`；最新交易日无库行时触发 lazy compute 并 upsert（幂等）。
  - `_build_market_data_like(limit_summary) -> dict | None`——frame.limitSummary → TS `DragonBreathMarketDataLike` 映射（执行者注意：本任务 Step 3 有完整代码）。
  - HTTP: `GET /api/hotlist-sentiment/series?dataset_id=&snapshot_type=&days=`，`days` 默认 3 上限 30；无任何可用数据时 HTTP 200 + `{"ok": false, "degraded": true, "reason": ...}`。

- [ ] **Step 1: 核对 `load_snapshot_analysis` 返回结构（已核实，执行时再确认一眼）**

`load_snapshot_analysis` 返回 `{code: analysis}`（`mongo_repository.py:1243-1251`，`row.get("analysis")` 为每 code 的 analysis dict）；displayStatus 取 `analysis["displayStatus"]`，条目若为 dict 取其 `label` 字段，若为 str 直接用——两者兼容的规范化在 `_normalize_display_label` 完成（本任务 Step 4 代码已按此实现）。

- [ ] **Step 2: 写失败 API 测试**

`quant-board/tests/test_hotlist_sentiment_series_api.py`（文件顶部**就地复制** `test_hotlist_sentiment_backfill.py` 的 `FakeCursor` / `FakeReplaceResult` / `FakeCollection` / `FakeMongoDb` 四个类定义——自包含，避免 tests 包导入路径问题；类代码逐字照抄该文件 L6-79）。测试函数：

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def _frame(dataset_id: str, snapshot_type: str, trading_date: str, snapshot_id: str) -> dict:
    return {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date,
            "snapshotId": snapshot_id, "slotTime": "14:30", "timestamp": 1757000000}


def _seed_frames(db, dataset_id: str, snapshot_type: str, dates: list[str]) -> None:
    for i, date in enumerate(dates):
        db["snapshot_frames"].rows.append(_frame(dataset_id, snapshot_type, date, f"snap-{date}"))
        db["snapshot_stock_rows"].rows.extend([
            {"datasetId": dataset_id, "snapshotId": f"snap-{date}", "code": "000001", "name": "甲",
             "compRank": 1, "change": 5.0, "turnover": 8e8, "zlje": 1e8, "zljzb": 12,
             "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1},
        ])


def test_series_lazy_computes_latest_day_and_persists(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-03", "2026-06-04", "2026-06-05"])
    # 历史日不做 lazy compute，前两日预置库文档；只有最新交易日走 lazy compute
    for date in ("2026-06-03", "2026-06-04"):
        fake_db["hotlist_sentiment"].rows.append({
            "_id": f"dragonboard_live:half_hour:{date}",
            "datasetId": "dragonboard_live", "snapshotType": "half_hour",
            "tradingDate": date, "stage": "启动", "riskLevel": "低", "confidence": 60,
            "summary": "预置",
            "metrics": {"topN": 1, "layers": {}, "comparison": {}, "limitEvidence": {}},
            "turnover": {"newEntries": [], "eliminated": []}, "signals": [], "warnings": [],
        })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/series", params={
        "dataset_id": "dragonboard_live", "snapshot_type": "half_hour", "days": 3,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    items = body["items"]
    assert [item["tradingDate"] for item in items] == ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert all(not item.get("missing") for item in items)
    assert all("stage" in item and "metrics" in item for item in items)
    # lazy compute 幂等：最新交易日已 upsert 到 hotlist_sentiment
    assert fake_db["hotlist_sentiment"].rows, "最新交易日应已入库"
    assert all(row["tradingDate"] in ("2026-06-03", "2026-06-04", "2026-06-05")
               for row in fake_db["hotlist_sentiment"].rows)


def test_series_second_call_reads_from_db(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-04", "2026-06-05"])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)
    client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})
    writes_after_first = len(fake_db["hotlist_sentiment"].rows)

    response = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})

    assert response.status_code == 200
    assert len(fake_db["hotlist_sentiment"].rows) == writes_after_first  # 未新增写库


def test_series_days_default_and_cap(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", [f"2026-05-{d:02d}" for d in range(1, 11)])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"}).json()
    assert len(body["items"]) <= 3

    body = client.get("/api/hotlist-sentiment/series",
                      params={"dataset_id": "dragonboard_live", "days": "99"}).json()
    assert len(body["items"]) <= 30


def test_series_no_frames_returns_degraded(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["reason"]


def test_series_empty_stock_rows_marks_missing_day(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    # 只有帧、没有 stock rows → 该日 missing 标注，不伪造
    fake_db["snapshot_frames"].rows.append(_frame("dragonboard_live", "half_hour", "2026-06-05", "snap-x"))
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/series",
                      params={"dataset_id": "dragonboard_live", "days": "1"}).json()
    assert body["ok"] is True
    assert body["items"][0]["missing"] is True
    assert body["items"][0]["reason"] == "empty_stock_rows"
```

- [ ] **Step 3: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_series_api.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_series_api.py -v`
Expected: 404（`/series` 路由不存在）。

- [ ] **Step 4: 实现 compute 编排 service**

`quant-board/backend/services/theme/hotlist_sentiment_compute.py`：

```python
"""热榜情绪 series 读口编排：lazy compute 最新交易日 + 缺失日 fail-visible 标注。

职责（backend 分层：有 I/O 编排 → services/）：
- 取最近 N 个交易日（snapshot_frames）
- 逐日读 hotlist_sentiment 库行；最新交易日缺行时经 HotListSentimentBackfillService
  触发纯函数计算并 upsert（幂等）
- displayStatus join（snapshot_analysis → rows.displayStatusLabel）
- frame.limitSummary → market_data 映射（ztCount/maxContinuousDays 无直接字段时推导）

无任何可用数据时返回 degraded 结构，不做质量阻断。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.sentiment import STATUS_LABELS
from backend.operations.hotlist_sentiment import HotListSentimentBackfillService


def _normalize_display_label(entry: Any) -> str | None:
    # snapshot_analysis 的 displayStatus 条目：dict 取 label，str 直接用；非法标签返回 None
    label = entry.get("label") if isinstance(entry, dict) else entry
    label = str(label or "").strip()
    return label if label in STATUS_LABELS else None


def _build_market_data_like(limit_summary: Any) -> dict | None:
    # frame.limitSummary = {continuousBoards, zhaban, yesterdayZt, thsPools}
    # → TS DragonBreathMarketDataLike {ztCount, zhaban, limitData, maxContinuousDays, thsLimitUpPools}
    if not isinstance(limit_summary, dict):
        return None
    boards = limit_summary.get("continuousBoards") if isinstance(limit_summary.get("continuousBoards"), dict) else {}
    yiban = float(boards.get("yiban") or 0)
    erban = float(boards.get("erban") or 0)
    sanban = float(boards.get("sanban") or 0)
    siban = float(boards.get("sibanPlus") or 0)
    max_days = 4 if siban > 0 else 3 if sanban > 0 else 2 if erban > 0 else 1 if yiban > 0 else 0
    return {
        "ztCount": yiban + erban + sanban + siban,   # limitSummary 无直接 ztCount，按连板结构聚合
        "zhaban": limit_summary.get("zhaban") if isinstance(limit_summary.get("zhaban"), dict) else {},
        "limitData": boards,
        "maxContinuousDays": max_days,
        "thsLimitUpPools": limit_summary.get("thsPools") if isinstance(limit_summary.get("thsPools"), dict) else None,
    }


def _join_display_status(db: Any, dataset_id: str, snapshot_id: str, rows: list[dict]) -> dict[str, Any]:
    """snapshot_analysis.displayStatus → rows[].displayStatusLabel（就地注入）。

    fail-visible：查询异常与个股无 displayStatus 分开结构化标注，不静默、不抛出（无质量阻断）。
    返回 {"joined": N, "noDisplayStatus": M, "joinFailed": bool, "reason": str | None}；
    调用方 _compute_and_persist 把标注追加进 doc["warnings"]。
    """
    try:
        from backend.data.repositories.mongo_repository import MongoRepository

        analysis_by_code = MongoRepository(db).load_snapshot_analysis(
            dataset_id, snapshot_id, [str(r.get("code") or "") for r in rows]
        )
    except Exception as exc:
        return {"joined": 0, "noDisplayStatus": 0, "joinFailed": True, "reason": f"join_failed: {exc}"}
    joined = no_display = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        # load_snapshot_analysis 返回 {code: analysis}；displayStatus 是 analysis 内的条目
        entry = analysis.get("displayStatus") if isinstance(analysis, dict) else None
        label = _normalize_display_label(entry)
        if label:
            row["displayStatusLabel"] = label
            joined += 1
        else:
            no_display += 1
    return {"joined": joined, "noDisplayStatus": no_display, "joinFailed": False, "reason": None}


def _join_warning(join_stats: dict[str, Any]) -> str | None:
    if join_stats.get("joinFailed"):
        return f"displayStatus join failed（fallback 分类接管）: {join_stats.get('reason')}"
    if join_stats.get("noDisplayStatus"):
        return f"displayStatus missing on {join_stats['noDisplayStatus']} stocks（fallback 分类接管）"
    return None


class HotListSentimentComputeService:
    def __init__(self, mongo_db: Any) -> None:
        self._backfill = HotListSentimentBackfillService(mongo_db)
        self._sentiment = mongo_db["hotlist_sentiment"]

    def ensure_series(self, dataset_id: str, snapshot_type: str, days: int) -> dict[str, Any]:
        dates = self._backfill.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not dates:
            return {"ok": False, "degraded": True, "reason": "no_snapshot_trading_date", "items": []}
        window = dates[-days:]
        latest = window[-1]

        items: list[dict[str, Any]] = []
        for trading_date in window:
            doc = self._sentiment.find_one({
                "datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": trading_date,
            })
            if doc is None and trading_date == latest:
                # lazy compute：仅最新交易日，幂等 upsert（取数→join→纯函数→upsert 一体）
                computed = self._compute_and_persist(dataset_id, snapshot_type, trading_date)
                if computed is None or computed.get("missing"):
                    items.append(computed or {"tradingDate": trading_date, "missing": True, "reason": "unknown"})
                    continue
                items.append(computed)
                continue
            if doc is None:
                items.append({"tradingDate": trading_date, "missing": True, "reason": "not_persisted"})
                continue
            items.append({key: value for key, value in doc.items() if key != "_id"})
        return {"ok": True, "items": items}
```

displayStatus join 与市场证据注入只在 series 读口生效（EOD backfill 维持不 join 的现状），因此 `_join_display_status` / `_build_market_data_like` 放 compute service 内，`_compute_and_persist` 本地完成取数 → join → `build_hotlist_sentiment_document`（带 `market_data`）→ upsert：

> **与 spec 的声明偏差（有意为之）**：spec 要求 EOD backfill 也 join displayStatus；本计划让 EOD 回填维持不 join。理由：① join 只影响 `signals[].displayStatusLabel` 这类展示字段，`stage/metrics/turnover` 等入库数值来自 fallback 分类，两路径 metrics 数值一致；② series 读口是唯一对外 join 口径，前端只消费 series；③ 历史大批量回填逐日 join snapshot_analysis 的额外读放大没有消费方。若未来 backfill 文档也要带 join 字段，回填后按日触发一次 series lazy compute 即可补齐。

```python
    def _compute_and_persist(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict | None:
        # 取数 → join displayStatus → 纯函数（含 limitSummary 市场证据）→ upsert。
        # 与 backfill.run_for_date 的差异仅两点：displayStatus join + limitSummary 市场证据注入。
        # market_data 缺失时 fail-visible：missingEvidence 由纯函数标注，不阻断入库。
        frame = self._backfill.latest_frame(dataset_id, snapshot_type, trading_date)
        if not frame:
            return {"tradingDate": trading_date, "missing": True, "reason": "no_snapshot_frame"}
        stocks = self._backfill.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
        if not stocks:
            return {"tradingDate": trading_date, "missing": True, "reason": "empty_stock_rows"}
        previous = self._backfill.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        join_stats = _join_display_status(self._backfill._db, dataset_id, str(frame.get("snapshotId") or ""), stocks)
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            market_data=_build_market_data_like(frame.get("limitSummary")),
        )
        join_note = _join_warning(join_stats)
        if join_note:
            doc.setdefault("warnings", []).append(join_note)  # fail-visible：join 异常/缺失随文档落库
        from backend.services.theme.hotlist_sentiment_service import HotListSentimentService

        HotListSentimentService(self._backfill._db).upsert(doc)
        return {key: value for key, value in doc.items() if key != "_id"}
```

文件顶部 import 同步为：

```python
from backend.operations.hotlist_sentiment import HotListSentimentBackfillService, build_hotlist_sentiment_document
```

`ensure_series` 的 lazy compute 分支改调 `self._compute_and_persist(...)`（替换原草稿中经 `run_for_date` 的分支）：

```python
            if doc is None and trading_date == latest:
                computed = self._compute_and_persist(dataset_id, snapshot_type, trading_date)
                if computed is None or computed.get("missing"):
                    items.append(computed or {"tradingDate": trading_date, "missing": True, "reason": "unknown"})
                    continue
                items.append(computed)
                continue
```

- [ ] **Step 5: 追加 GET /series 路由**

`quant-board/backend/api/hotlist_routes.py` 末尾追加：

```python
@router.get("/series")
def get_hotlist_sentiment_series(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    days: int = 3,
) -> dict[str, Any]:
    capped_days = max(1, min(int(days), 30))
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "items": []}
    try:
        from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

        return HotListSentimentComputeService(db).ensure_series(dataset_id, snapshot_type, capped_days)
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"series_compute_failed: {exc}", "items": []}
```

- [ ] **Step 6: 运行测试通过**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_series_api.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_api.py -v`
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add quant-board/backend/services/theme/hotlist_sentiment_compute.py quant-board/backend/api/hotlist_routes.py quant-board/backend/operations/hotlist_sentiment.py quant-board/tests/test_hotlist_sentiment_series_api.py
git commit -m "feat(sentiment): GET /api/hotlist-sentiment/series 读口（lazy compute + displayStatus join + fail-visible）"
```

---

### Task 7: proxy-server 转发前缀

**Files:**

- Modify: `proxy-server/routes/quantBoardProxy.js:8-36`

**Interfaces:**

- Consumes: 无。
- Produces: `/api/hotlist-sentiment/*` 请求由 proxy 转发到 QuantBoard 后端（8000）。

- [ ] **Step 1: 加前缀**

`QUANT_BOARD_PREFIXES` 数组中 `'/api/journal/'` 之前插入一行 `'/api/hotlist-sentiment/',`（与既有 `'/api/sentiment/'` 不同前缀，无冲突）。该端点是 lazy-compute 读口，**不加入** `CACHEABLE_RESOURCES`。

- [ ] **Step 2: 验证**

Run: `cd proxy-server && node --check routes/quantBoardProxy.js && node -e "import('./routes/quantBoardProxy.js').then(m => { console.log(m.shouldProxyToQuantBoard('/api/hotlist-sentiment/series')); console.log(m.shouldProxyToQuantBoard('/api/sentiment/foo')); console.log(m.shouldProxyToQuantBoard('/api/hotlist-sentimentx')); })"`
Expected: `true`、`true`、`false`（第三行确认前缀边界不误伤）。

- [ ] **Step 3: 提交**

```bash
git add proxy-server/routes/quantBoardProxy.js
git commit -m "fix(proxy): 转发 /api/hotlist-sentiment 前缀到 QuantBoard 后端（修复面板 404 死链）"
```

---

### Task 8: 前端类型契约 + 薄 API client

**Files:**

- Create: `src/types/hotlistSentiment.ts`
- Create: `src/services/hotlist/hotlistSentimentApi.ts`
- Create: `src/services/hotlist/__tests__/hotlistSentimentApi.test.ts`

**Interfaces:**

- Consumes: `GET /api/hotlist-sentiment/series` 响应（Task 6）；`UnifiedEmotionStage`（`src/types/emotion.ts`）。
- Produces:
  - `src/types/hotlistSentiment.ts`：`HotListStatusLabel` / `HotListDayMetrics` / `HotListLayerKey` / `HotListLayerSet` / `TurnoverEntryDetail` / `TurnoverExitDetail` / `TurnoverResult` / `HotListYesterdayStrongPerformance` / `HotListThreeDayComparison` / `HotListLimitMarketEvidence` / `HotListLimitIntersectionEvidence` / `HotListYesterdayHotLimitEvidence` / `HotListLimitEvidence` / `HotListSentimentMetrics` / `HotListSentimentRiskLevel` / `HotListSentimentResult`（全部从 `HotListSentimentAnalyzer.ts` L16-204 类型区原样迁移，字段不加不减）；新增 `HotListSentimentDayDoc`：

```ts
// src/types/hotlistSentiment.ts（新增部分；类型区从 HotListSentimentAnalyzer.ts 原样迁移）
export interface HotListSentimentDayDoc {
  datasetId: string
  snapshotType: string
  tradingDate: string
  snapshotId?: string
  slotTime?: string
  timestamp?: number
  stage: UnifiedEmotionStage
  riskLevel: HotListSentimentRiskLevel
  confidence: number
  summary: string
  metrics: HotListSentimentMetrics & {
    poolSize?: number
    allPoolUpRatio?: number
    retentionRate1d?: number | null
    retentionRate2d?: number | null
    limitIntersectionRate?: number
    newEntryCount?: number
    eliminatedCount?: number
    statusSourceCounts?: { displayStatus: number; fallback: number }
    missingEvidence?: string[]
  }
  turnover: TurnoverResult
  signals: string[]
  warnings: string[]
  missing?: boolean
  reason?: string
}
```

- `src/services/hotlist/hotlistSentimentApi.ts`：

```ts
// src/services/hotlist/hotlistSentimentApi.ts
// 薄 API client：只做 fetch + 类型化，无兜底计算（口径唯一来源 = QuantBoard 后端）
import type { HotListSentimentDayDoc } from '@/types/hotlistSentiment'

export interface HotlistSentimentSeriesResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  items: Array<HotListSentimentDayDoc | { tradingDate: string; missing: true; reason: string }>
}

export interface HotlistSentimentSeriesResult {
  items: HotListSentimentDayDoc[]
  degraded: boolean
  reason: string | null
}

export async function fetchHotlistSentimentSeries(
  days = 3,
  datasetId = 'dragonboard_live',
): Promise<HotlistSentimentSeriesResult> {
  const params = new URLSearchParams({ dataset_id: datasetId, days: String(days) })
  const response = await fetch(`/api/hotlist-sentiment/series?${params.toString()}`)
  if (!response.ok) {
    return { items: [], degraded: true, reason: `HTTP ${response.status}` }
  }
  const body = (await response.json()) as HotlistSentimentSeriesResponse
  if (!body.ok || body.degraded) {
    return { items: [], degraded: true, reason: body.reason || 'degraded' }
  }
  const docs = (body.items || []).filter((item): item is HotListSentimentDayDoc => !item.missing)
  return { items: docs, degraded: false, reason: body.reason || null }
}
```

- [ ] **Step 1: 迁移类型文件**

从 `src/services/hotlist/HotListSentimentAnalyzer.ts` L16-204 复制类型定义到 `src/types/hotlistSentiment.ts`（原样，不加不减）。类型文件落在 `src/types/` 目录内，同目录 import 用相对路径：`import type { ... } from './emotion'`（原文件 `../../types/emotion`）与 `import type { ThsLimitUpPoolEvidence } from './index'`（原文件 `../../types`，`ThsLimitUpPoolEvidence` 已核实从 `src/types/index.ts` 导出）。追加 `HotListSentimentDayDoc`（代码如上）。文件头注释注明"仅类型契约，计算在 QuantBoard 后端"。

- [ ] **Step 2: 实现 API client（代码如上）**

- [ ] **Step 3: 写 client 测试（先于实现跑一次确认失败亦可，此处 client 极薄，测试与实现同批提交）**

`src/services/hotlist/__tests__/hotlistSentimentApi.test.ts`：

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHotlistSentimentSeries } from '../hotlistSentimentApi'

const docStub = {
  datasetId: 'dragonboard_live',
  snapshotType: 'half_hour',
  tradingDate: '2026-09-06',
  stage: '高潮' as const,
  riskLevel: '低' as const,
  confidence: 78,
  summary: '热榜情绪处于高潮阶段',
  metrics: { topN: 120, layers: {} as any, comparison: {} as any, limitEvidence: {} as any },
  turnover: {
    previousPoolSize: 0,
    currentPoolSize: 0,
    retainedFromYesterday: 0,
    newEntries: [],
    eliminated: [],
    newEntryDetails: [],
    eliminatedDetails: [],
  },
  signals: [],
  warnings: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('fetchHotlistSentimentSeries', () => {
  it('正常响应返回类型化 items', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true, items: [docStub] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(false)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].tradingDate).toBe('2026-09-06')
    expect(result.items[0].stage).toBe('高潮')
  })

  it('degraded 响应透传错误态，不伪造数据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: false,
            degraded: true,
            reason: 'no_snapshot_trading_date',
            items: [],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(true)
    expect(result.items).toHaveLength(0)
    expect(result.reason).toBe('no_snapshot_trading_date')
  })

  it('HTTP 错误返回错误态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('err', { status: 502 })))
    const result = await fetchHotlistSentimentSeries()
    expect(result.degraded).toBe(true)
    expect(result.reason).toBe('HTTP 502')
  })

  it('missing 日被过滤', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ok: true,
            items: [
              docStub,
              { tradingDate: '2026-09-05', missing: true, reason: 'empty_stock_rows' },
            ],
          }),
          { status: 200 },
        ),
      ),
    )
    const result = await fetchHotlistSentimentSeries()
    expect(result.items).toHaveLength(1)
    expect(result.items[0].tradingDate).toBe('2026-09-06')
  })

  it('请求参数包含 dataset_id 与 days', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, items: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await fetchHotlistSentimentSeries(5, 'my_dataset')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/hotlist-sentiment/series?dataset_id=my_dataset&days=5',
    )
  })
})
```

- [ ] **Step 4: 运行验证**

Run: `pnpm vitest run src/services/hotlist/__tests__/hotlistSentimentApi.test.ts && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 5 个测试 PASS；类型检查 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/types/hotlistSentiment.ts src/services/hotlist/hotlistSentimentApi.ts src/services/hotlist/__tests__/hotlistSentimentApi.test.ts
git commit -m "feat(sentiment): 前端热榜情绪类型契约与薄 API client（无兜底计算，口径唯一来源后端）"
```

---

### Task 9: DragonBreathPanel 切换到后端 series

**Files:**

- Modify: `src/components/panels/DragonBreathPanel.vue`（script 部分：导入、`loadHotListSentiment`、相关 ref 类型与辅助常量）

**Interfaces:**

- Consumes: `fetchHotlistSentimentSeries`（Task 8）、`HotListSentimentDayDoc`（Task 8）。
- Produces: 面板 `hotListSentiment` ref 类型改为 `HotListSentimentDayDoc | null`；新增 `hotListSentimentSlotTime` ref 供模板标注数据时点；`hotListSentimentError` 语义扩展（degraded reason 直接透出）。

- [ ] **Step 1: 改导入**

删除 L581-586 的：

```ts
import {
  hotListSentimentAnalyzer,
  type HotListDayMetrics,
  type HotListSentimentResult,
  type HotListStatusLabel,
} from '@/services/hotlist/HotListSentimentAnalyzer'
```

替换为：

```ts
import { fetchHotlistSentimentSeries } from '@/services/hotlist/hotlistSentimentApi'
import type { HotListSentimentDayDoc } from '@/types/hotlistSentiment'
```

同批删除 `SnapshotFrameBundle` / `FORMAL_SNAPSHOT_READ_POLICY` / `snapshotFacade` / `cacheManager` / `HOT_LIST_SENTIMENT_ROW_FIELDS` 中仅被旧 `loadHotListSentiment` 使用的导入与常量（先 grep 本文件内其他使用点，仍被池列表展示使用的保留——`dataLayer` 与 `dragonBreathAnalyzer` 保留不动）。

- [ ] **Step 2: 重写 loadHotListSentiment**

`hotListSentiment` ref 声明处类型改为 `ref<HotListSentimentDayDoc | null>(null)`；新增 `const hotListSentimentSlotTime = ref('')`。函数体替换为：

```ts
async function loadHotListSentiment() {
  // in-flight 防重入保留；历史 daily 帧查询/30min LRU 缓存删除（数据全部来自后端 series）
  if (hotListSentimentInFlight) return
  hotListSentimentInFlight = true
  hotListSentimentLoading.value = true
  hotListSentimentError.value = null

  try {
    const result = await fetchHotlistSentimentSeries(3)
    if (result.degraded || result.items.length === 0) {
      hotListSentiment.value = null
      hotListSentimentSlotTime.value = ''
      hotListSentimentError.value = result.reason || '热榜情绪数据暂不可用'
      scheduleHotListSentimentRetry()
      return
    }
    hotListSentimentRetryCount = 0
    const latest = result.items[result.items.length - 1]
    hotListSentiment.value = latest
    hotListSentimentSlotTime.value = latest.slotTime || ''
    // 失败原因可见：后端标注的 missingEvidence / statusSourceCounts 不在此吞掉，
    // 模板可经 hotListSentiment.metrics.missingEvidence 展示
  } catch (err: any) {
    console.warn('[DragonBreathPanel] 热榜情绪加载失败:', err)
    hotListSentiment.value = null
    hotListSentimentSlotTime.value = ''
    hotListSentimentError.value = err?.message || '热榜情绪加载失败'
    scheduleHotListSentimentRetry()
  } finally {
    hotListSentimentInFlight = false
    hotListSentimentLoading.value = false
  }
}
```

同时删除：`hotListSentimentFramesCache` 声明、`HOT_LIST_SENTIMENT_ROW_FIELDS` 常量、`marketData` computed 中仅供给旧分析器的部分（若 `marketData` 还被其他模板区块使用则保留）、旧注释中"今天数据来自 dataLayer 实时行"段落。

- [ ] **Step 3: 模板适配**

检查模板中 `hotListSentiment.` 的引用点：字段名（stage/riskLevel/confidence/summary/metrics.comparison.today._/metrics.layers._/turnover.\*）与后端文档一致，应零改动；若有个别引用了 TS 专有结构（如 `metrics.comparison.today.tradingDate`），改为顶层 `hotListSentiment.tradingDate`。在情绪卡片头部加时点标注（紧跟现有 header 区域）：

```html
<span v-if="hotListSentimentSlotTime" class="slot-time"
  >数据时点 {{ hotListSentimentSlotTime }}</span
>
```

（样式沿用现有 `.source-info` 类风格，加一行浅色小字即可。）

- [ ] **Step 4: 验证**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false && pnpm vitest run src/services/hotlist`
Expected: 类型检查 PASS（此时旧 analyzer 文件还在但面板已不引用）；hotlist 相关 vitest PASS。

- [ ] **Step 5: 浏览器冒烟（可选，受环境限制时说明）**

`pnpm dev` + QuantBoard 后端 8000 运行时，打开龙虎榜情绪面板确认：情绪卡片渲染、slotTime 显示、断开后端时显示错误文案而非空白假数据。

- [ ] **Step 6: 提交**

```bash
git add src/components/panels/DragonBreathPanel.vue
git commit -m "feat(sentiment): 龙虎榜情绪面板切换后端 series 读口（删除前端自算与 daily 帧查询）"
```

---

### Task 10: 删除 TS 计算实现 + 文档注记

**Files:**

- Delete: `src/services/hotlist/HotListSentimentAnalyzer.ts`
- Delete: `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts`
- Modify: `docs/热榜情绪分析器方案.md`（头部注记）

**Interfaces:**

- Consumes: Task 1-9 全部完成。
- Produces: 前端不再存在热榜情绪计算实现；文档指向 spec 与 series 读口。

- [ ] **Step 1: 残留引用检查**

Run: `rg -n "HotListSentimentAnalyzer|hotListSentimentAnalyzer|persistHotListSentiment" src/ --glob '!**/node_modules/**'`
Expected: 仅剩 `src/types/emotion.ts` L10 注释提到该名（保留，改为指向后端实现：把注释中 "与 HotListSentimentAnalyzer 都应输出这套阶段" 改为 "DragonBreathAnalyzer（前端）与 backend/analysis/hotlist/sentiment.py（后端，热榜情绪唯一实现）都应输出这套阶段"）。除注释外不得有残留 import；有则逐个清理。

- [ ] **Step 2: 删除文件（一次一个）**

```bash
git rm src/services/hotlist/HotListSentimentAnalyzer.ts
git rm src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts
```

- [ ] **Step 3: 全量类型与测试验证**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false && pnpm vitest run src/services/hotlist`
Expected: 类型检查 PASS；无测试引用断裂。再跑 `pnpm test` 全量（若耗时过长至少跑 `src/services` 与 `src/types` 相关子集）确认无间接依赖断裂。

- [ ] **Step 4: 后端全量相关验证（迁移收尾）**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_compute.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py tests/test_hotlist_sentiment_series_api.py tests/test_market_regime.py -v`
Expected: 全部 PASS（`test_market_regime.py` 确认引擎 regime 消费不受 schema 超集影响）。

- [ ] **Step 5: 文档注记**

`docs/热榜情绪分析器方案.md` 头部（标题后）插入：

```markdown
> **2026-09-06 迁移注记**：本文档描述的前端 TS 实现已删除。热榜情绪计算唯一实现在
> `quant-board/backend/analysis/hotlist/sentiment.py`（纯函数，golden 对齐基线
> `quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json`）。前端仅消费
> `GET /api/hotlist-sentiment/series`。设计与决策见
> `quant-board/docs/superpowers/specs/2026-09-06-hotlist-sentiment-backend-migration-design.md`。
> 以下正文保留为历史方案与口径说明，涉及前端计算的部分已失效。
```

- [ ] **Step 6: 提交**

```bash
git add -A src/services/hotlist src/types/emotion.ts docs/热榜情绪分析器方案.md
git commit -m "refactor(sentiment): 删除前端热榜情绪 TS 计算（后端唯一实现，前端只消费生产数据）"
```

---

## 实施记录

（任务执行后在此追加：完成日期、偏离计划的决定、golden 对齐中的例外。）
