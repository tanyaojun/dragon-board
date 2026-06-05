# 热榜情绪替换市场情绪——实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 RankTrend 策略的情绪输入从全市场情绪（market_regime）切换为热榜情绪（hotlist_sentiment），新建 MongoDB 集合存储每日热榜情绪数据，改造 compose_strategy() 决策逻辑。

**Architecture:** TypeScript HotListSentimentAnalyzer 扩展全池覆盖和 turnover 计算能力，计算结果通过新 API 端点写入 MongoDB `hotlist_sentiment` 集合；Python 回测管线通过 HotListSentimentRepository 按交易日读取，注入 compose_strategy() 替换原有 market_regime()。

**Tech Stack:** TypeScript (Vue/browser), Python FastAPI, MongoDB (pymongo), Vitest (TS 测试), pytest (Python 测试)

**Spec:** `quant-board/docs/superpowers/specs/2026-06-05-hotlist-sentiment-strategy-design.md`

---

## Phase 1: Python 后端基础——Repository + API 端点

### Task 1: 新建 HotListSentimentRepository

**Files:**
- Create: `quant-board/backend/data/hotlist_sentiment_repo.py`
- Create: `quant-board/tests/test_hotlist_sentiment_repo.py`

- [ ] **Step 1: 写 repo 单元测试**

```python
# quant-board/tests/test_hotlist_sentiment_repo.py
import pytest
from backend.data.hotlist_sentiment_repo import HotListSentimentRepository


class FakeMongoCollection:
    def __init__(self):
        self._docs: dict[str, dict] = {}
        self.queries: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        self.queries.append(query)
        return self._docs.get(query.get("tradingDate", ""))

    def insert_one(self, doc: dict) -> None:
        self._docs[doc["tradingDate"]] = doc


class FakeMongoDb:
    def __init__(self):
        self._collections: dict[str, FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        if name not in self._collections:
            self._collections[name] = FakeMongoCollection()
        return self._collections[name]


def test_repo_returns_none_when_date_not_found():
    db = FakeMongoDb()
    repo = HotListSentimentRepository(db)
    result = repo.get_by_date("2026-04-01")
    assert result is None


def test_repo_returns_document_when_date_exists():
    db = FakeMongoDb()
    db["hotlist_sentiment"].insert_one({
        "tradingDate": "2026-06-05",
        "stage": "高潮",
        "riskLevel": "低",
    })
    repo = HotListSentimentRepository(db)
    result = repo.get_by_date("2026-06-05")
    assert result is not None
    assert result["stage"] == "高潮"
    assert result["riskLevel"] == "低"


def test_repo_caches_result_and_hits_mongo_only_once():
    db = FakeMongoDb()
    db["hotlist_sentiment"].insert_one({
        "tradingDate": "2026-06-05",
        "stage": "高潮",
    })
    repo = HotListSentimentRepository(db)
    repo.get_by_date("2026-06-05")
    repo.get_by_date("2026-06-05")
    repo.get_by_date("2026-06-05")
    assert len(db["hotlist_sentiment"].queries) == 1


def test_repo_returns_none_for_empty_db():
    db = FakeMongoDb()
    repo = HotListSentimentRepository(db)
    result = repo.get_by_date("any-date")
    assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_repo.py -v
```

Expected: 4 tests FAIL with ModuleNotFoundError

- [ ] **Step 3: 实现 HotListSentimentRepository**

```python
# quant-board/backend/data/hotlist_sentiment_repo.py
from __future__ import annotations

from typing import Any


class HotListSentimentRepository:
    def __init__(self, mongo_db: Any) -> None:
        self._collection = mongo_db["hotlist_sentiment"]
        self._cache: dict[str, dict | None] = {}

    def get_by_date(self, trading_date: str) -> dict | None:
        if trading_date not in self._cache:
            self._cache[trading_date] = self._collection.find_one(
                {"tradingDate": trading_date}
            )
        return self._cache[trading_date]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_hotlist_sentiment_repo.py -v
```

Expected: 4 tests PASS

---

### Task 2: 新增 POST /api/hotlist-sentiment/ingest 端点

**Files:**
- Modify: `quant-board/backend/api/routes.py` (或现有的 sentiment routes 文件)
- Modify: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: 写 API 端点测试**

在 `tests/test_quant_board.py` 末尾追加：

```python
def test_hotlist_sentiment_ingest_stores_and_retrieves():
    from backend.data.hotlist_sentiment_repo import HotListSentimentRepository

    client = TestClient(app)
    payload = {
        "tradingDate": "2026-06-05",
        "stage": "高潮",
        "riskLevel": "低",
        "confidence": 78,
        "summary": "测试",
        "metrics": {
            "poolSize": 218,
            "allPoolUpRatio": 0.48,
            "hotTrin": 0.82,
            "retentionRate1d": 0.73,
            "retentionRate2d": 0.58,
            "limitIntersectionRate": 0.18,
            "newEntryCount": 31,
            "eliminatedCount": 24,
        },
        "turnover": {
            "previousPoolSize": 225,
            "currentPoolSize": 218,
            "retainedFromYesterday": 187,
            "newEntries": ["000001"],
            "eliminated": ["300001"],
            "newEntryDetails": [],
            "eliminatedDetails": [],
        },
        "signals": ["资金偏强"],
        "warnings": [],
    }
    response = client.post("/api/hotlist-sentiment/ingest", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tradingDate"] == "2026-06-05"


def test_hotlist_sentiment_ingest_rejects_missing_trading_date():
    client = TestClient(app)
    response = client.post("/api/hotlist-sentiment/ingest", json={"stage": "高潮"})
    assert response.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py::test_hotlist_sentiment_ingest_stores_and_retrieves tests/test_quant_board.py::test_hotlist_sentiment_ingest_rejects_missing_trading_date -v
```

Expected: FAIL (404 或 422)

- [ ] **Step 3: 查找或新建 API routes 文件**

```bash
cd /d/dragon-board/quant-board && grep -r "APIRouter\|app = FastAPI\|include_router" backend/main.py backend/api/ --include="*.py" -l
```

确认路由注册方式后，在 `backend/api/` 下新建或修改文件。

- [ ] **Step 4: 实现 ingest 端点**

```python
# 在 backend/api/ 中新增 hotlist_routes.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/hotlist-sentiment", tags=["hotlist-sentiment"])


class HotListSentimentPayload(BaseModel):
    tradingDate: str
    stage: str = "启动"
    riskLevel: str = "中"
    confidence: float = 0
    summary: str = ""
    metrics: dict[str, Any] = {}
    turnover: dict[str, Any] = {}
    signals: list[str] = []
    warnings: list[str] = []


@router.post("/ingest")
def ingest_hotlist_sentiment(payload: HotListSentimentPayload, request: Any = None) -> dict:
    from backend.data.database import get_mongo_db

    db = get_mongo_db()
    collection = db["hotlist_sentiment"]

    doc = payload.model_dump()
    doc["_id"] = payload.tradingDate
    doc["snapshotType"] = "half_hour"

    collection.replace_one(
        {"tradingDate": payload.tradingDate}, doc, upsert=True
    )

    return {"status": "ok", "tradingDate": payload.tradingDate}
```

- [ ] **Step 5: 在 main.py 注册路由**

```python
from backend.api.hotlist_routes import router as hotlist_router
app.include_router(hotlist_router)
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py::test_hotlist_sentiment_ingest_stores_and_retrieves tests/test_quant_board.py::test_hotlist_sentiment_ingest_rejects_missing_trading_date -v
```

Expected: 2 tests PASS

---

## Phase 2: TypeScript 计算层改造

### Task 3: HotListSentimentAnalyzer 全池覆盖 + turnover 计算

**Files:**
- Modify: `src/services/hotlist/HotListSentimentAnalyzer.ts`
- Modify: `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts`

- [ ] **Step 1: 读当前代码确认改动点**

Read `src/services/hotlist/HotListSentimentAnalyzer.ts` 的 `buildLayerMetrics` 和 `analyze` 方法，确认当前只计算 top20/top50/top100 三层。

- [ ] **Step 2: 写 turnover 单元测试**

在 `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts` 追加：

```typescript
import { describe, it, expect } from 'vitest'

describe('computeTurnover', () => {
  it('detects new entries and eliminated stocks between two days', () => {
    const yesterday = [
      { code: '000001', name: 'A', rank: 10, change: 5.0, zlje: 1000, volumeRatio: 1.5 },
      { code: '000002', name: 'B', rank: 50, change: -2.0, zlje: -500, volumeRatio: 0.8 },
    ]
    const today = [
      { code: '000001', name: 'A', rank: 5, change: 9.8, zlje: 5000, volumeRatio: 2.5 },
      { code: '000003', name: 'C', rank: 30, change: 3.0, zlje: 800, volumeRatio: 1.2 },
    ]

    const result = computeTurnover(today, yesterday)

    expect(result.previousPoolSize).toBe(2)
    expect(result.currentPoolSize).toBe(2)
    expect(result.retainedFromYesterday).toBe(1)
    expect(result.newEntries).toEqual(['000003'])
    expect(result.eliminated).toEqual(['000002'])
  })

  it('classifies entry reason as limit_up for stocks with change >= 9.8', () => {
    const yesterday: any[] = []
    const today = [
      { code: '000001', name: 'A', rank: 1, change: 10.0, zlje: 0, volumeRatio: 1.0 },
    ]

    const result = computeTurnover(today, yesterday)
    expect(result.newEntryDetails[0].entryReason).toBe('limit_up')
  })

  it('classifies exit reason as weakening for declining stocks', () => {
    const yesterday = [
      { code: '000001', name: 'A', rank: 80, change: -5.0, zlje: 0, volumeRatio: 0.5 },
    ]
    const today: any[] = []

    const result = computeTurnover(today, yesterday)
    expect(result.eliminatedDetails[0].exitReason).toBe('weakening')
  })
})
```

- [ ] **Step 3: 实现 computeTurnover 函数**

在 `HotListSentimentAnalyzer.ts` 中新增导出函数：

```typescript
export interface TurnoverEntryDetail {
  code: string
  name: string
  rank: number
  changePct: number
  entryReason?: string
}

export interface TurnoverExitDetail {
  code: string
  name: string
  rank: number
  changePct: number
  exitReason?: string
}

export interface TurnoverResult {
  previousPoolSize: number
  currentPoolSize: number
  retainedFromYesterday: number
  newEntries: string[]
  eliminated: string[]
  newEntryDetails: TurnoverEntryDetail[]
  eliminatedDetails: TurnoverExitDetail[]
}

export function computeTurnover(
  todayStocks: any[],
  yesterdayStocks: any[]
): TurnoverResult {
  const todayCodes = new Set(todayStocks.map((s) => s.code))
  const yesterdayCodes = new Set(yesterdayStocks.map((s) => s.code))

  const newEntries = todayStocks.filter((s) => !yesterdayCodes.has(s.code))
  const eliminated = yesterdayStocks.filter((s) => !todayCodes.has(s.code))

  return {
    previousPoolSize: yesterdayStocks.length,
    currentPoolSize: todayStocks.length,
    retainedFromYesterday: todayStocks.filter((s) => yesterdayCodes.has(s.code)).length,
    newEntries: newEntries.map((s) => s.code),
    eliminated: eliminated.map((s) => s.code),
    newEntryDetails: newEntries.map((s) => ({
      code: s.code,
      name: s.name || '',
      rank: s.rank ?? 999,
      changePct: s.change ?? 0,
      entryReason: classifyEntryReason(s),
    })),
    eliminatedDetails: eliminated.map((s) => ({
      code: s.code,
      name: s.name || '',
      rank: s.rank ?? 999,
      changePct: s.change ?? 0,
      exitReason: classifyExitReason(s),
    })),
  }
}

function classifyEntryReason(stock: any): string {
  if ((stock.change ?? 0) >= 9.8) return 'limit_up'
  if ((stock.zlje ?? 0) > 0) return 'strong_money'
  if ((stock.volumeRatio ?? 1) > 2) return 'new_high_volume'
  return 'rank_surge'
}

function classifyExitReason(stock: any): string {
  if ((stock.change ?? 0) <= -9.8) return 'limit_down'
  if ((stock.change ?? 0) < -3) return 'weakening'
  return 'rank_out_of_range'
}
```

- [ ] **Step 4: 扩展 buildLayerMetrics 增加 all 层**

在 `buildLayerMetrics` 返回对象中追加 `all` 层，使用全量 `stocks`：

```typescript
function buildLayerMetrics(stocks: any[]): HotListLayerSet {
  return {
    top20:  computeDayMetrics(stocks.slice(0, 20), 20),
    top50:  computeDayMetrics(stocks.slice(0, 50), 50),
    top100: computeDayMetrics(stocks.slice(0, 100), 100),
    all:    computeDayMetrics(stocks, stocks.length),  // 新增全池
  }
}
```

- [ ] **Step 5: 在 analyze() 中调用 computeTurnover**

在 `analyze` 方法的返回对象中追加 `turnover` 字段：

```typescript
const turnover = computeTurnover(stocks, input.yesterday?.hotlist ?? [])

return {
  stage,
  riskLevel,
  confidence,
  summary,
  metrics: { ...metrics, layers: layerMetrics },
  signals,
  warnings,
  turnover,  // 新增
}
```

- [ ] **Step 6: 扩展 HotListSentimentResult 类型**

```typescript
export interface HotListSentimentResult {
  stage: EmotionCycleStage
  riskLevel: HotListSentimentRiskLevel
  confidence: number
  summary: string
  metrics: HotListSentimentMetrics
  signals: string[]
  warnings: string[]
  turnover: TurnoverResult  // 新增
}
```

- [ ] **Step 7: 运行 TS 测试**

```bash
cd /d/dragon-board && pnpm test src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts
```

Expected: 相关测试 PASS

---

### Task 4: TS 端 MongoDB 写入 + 每日收盘触发

**Files:**
- Modify: `src/services/hotlist/HotListSentimentAnalyzer.ts`
- Modify: `src/components/panels/DragonBreathPanel.vue` (或现有触发点)

- [ ] **Step 1: 新增 persistToBackend 方法**

在 `HotListSentimentAnalyzer.ts` 中新增：

```typescript
export async function persistHotListSentiment(
  result: HotListSentimentResult,
  tradingDate: string
): Promise<boolean> {
  try {
    const response = await fetch('/api/hotlist-sentiment/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tradingDate,
        stage: result.stage,
        riskLevel: result.riskLevel,
        confidence: result.confidence,
        summary: result.summary,
        metrics: {
          poolSize: result.metrics.layers.all.total,
          allPoolUpRatio: result.metrics.layers.all.upRatio,
          hotTrin: result.metrics.layers.all.hotTrin ?? 0,
          retentionRate1d: result.metrics.comparison.top100RetainRateFromYesterday,
          retentionRate2d: result.metrics.comparison.top100RetainRateFromDayBefore,
          limitIntersectionRate: result.metrics.limitEvidence.intersection.top100LimitUpShare,
          newEntryCount: result.turnover.newEntries.length,
          eliminatedCount: result.turnover.eliminated.length,
        },
        turnover: result.turnover,
        signals: result.signals,
        warnings: result.warnings,
      }),
    })
    return response.ok
  } catch {
    return false
  }
}
```

- [ ] **Step 2: 在 DragonBreathPanel 中接入触发逻辑**

在 DragonBreathPanel 的 `analyzeMarketBreath()` 或热榜情绪刷新完成回调中，检测是否为当日最后一帧（时间 ≥ 15:00），若是则调用 `persistHotListSentiment()`。

```typescript
const currentHour = new Date().getHours()
const currentMinute = new Date().getMinutes()
const isEndOfDay = currentHour >= 15

if (isEndOfDay && hotListSentiment.value) {
  const date = new Date().toISOString().slice(0, 10)
  persistHotListSentiment(hotListSentiment.value, date)
}
```

- [ ] **Step 3: 手动验证**

启动 dev server，确认收盘后 `hotlist_sentiment` 集合有数据写入。在 MongoDB shell 中执行 `db.hotlist_sentiment.find().pretty()` 确认。

---

## Phase 3: 历史数据回填

### Task 5: 历史回填脚本

**Files:**
- Create: `quant-board/scripts/backfill_hotlist_sentiment.py`

- [ ] **Step 1: 编写回填脚本**

```python
# quant-board/scripts/backfill_hotlist_sentiment.py
"""一次性脚本：从 snapshot_frames 回填 hotlist_sentiment 历史数据。

用法：
  cd quant-board
  .venv/Scripts/python.exe scripts/backfill_hotlist_sentiment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.data.database import get_mongo_db


def compute_hot_trin(stocks: list[dict]) -> float | None:
    up_turnover = sum(
        float(s.get("turnover") or 0)
        for s in stocks
        if float(s.get("change") or 0) > 0
    )
    down_turnover = sum(
        float(s.get("turnover") or 0)
        for s in stocks
        if float(s.get("change") or 0) < 0
    )
    up_count = sum(1 for s in stocks if float(s.get("change") or 0) > 0)
    down_count = sum(1 for s in stocks if float(s.get("change") or 0) < 0)
    if down_count == 0 or down_turnover == 0:
        return None
    adv_ratio = up_count / down_count
    vol_ratio = up_turnover / down_turnover
    return round(adv_ratio / vol_ratio, 4) if vol_ratio > 0 else None


def compute_retention_rate(today_stocks: list[dict], yesterday_stocks: list[dict]) -> float:
    if not yesterday_stocks:
        return 0.0
    yesterday_codes = {s["code"] for s in yesterday_stocks}
    retained = sum(1 for s in today_stocks if s["code"] in yesterday_codes)
    return round(retained / len(yesterday_stocks), 4)


def compute_turnover(today_stocks: list[dict], yesterday_stocks: list[dict]) -> dict:
    today_codes = {s["code"] for s in today_stocks}
    yesterday_codes = {s["code"] for s in yesterday_stocks}
    new_entries = [s for s in today_stocks if s["code"] not in yesterday_codes]
    eliminated = [s for s in yesterday_stocks if s["code"] not in today_codes]

    def _entry_reason(s: dict) -> str:
        chg = float(s.get("change") or 0)
        if chg >= 9.8:
            return "limit_up"
        if float(s.get("zlje") or 0) > 0:
            return "strong_money"
        if float(s.get("volumeRatio") or 1) > 2:
            return "new_high_volume"
        return "rank_surge"

    def _exit_reason(s: dict) -> str:
        chg = float(s.get("change") or 0)
        if chg <= -9.8:
            return "limit_down"
        if chg < -3:
            return "weakening"
        return "rank_out_of_range"

    return {
        "previousPoolSize": len(yesterday_stocks),
        "currentPoolSize": len(today_stocks),
        "retainedFromYesterday": sum(1 for s in today_stocks if s["code"] in yesterday_codes),
        "newEntries": [s["code"] for s in new_entries],
        "eliminated": [s["code"] for s in eliminated],
        "newEntryDetails": [
            {"code": s["code"], "name": s.get("name", ""), "rank": s.get("rank", 999),
             "changePct": float(s.get("change") or 0), "entryReason": _entry_reason(s)}
            for s in new_entries
        ],
        "eliminatedDetails": [
            {"code": s["code"], "name": s.get("name", ""), "rank": s.get("rank", 999),
             "changePct": float(s.get("change") or 0), "exitReason": _exit_reason(s)}
            for s in eliminated
        ],
    }


def main():
    db = get_mongo_db()
    frames_coll = db["snapshot_frames"]
    sentiment_coll = db["hotlist_sentiment"]

    # 获取所有 half_hour 交易日
    dates = sorted(set(
        f["tradingDate"]
        for f in frames_coll.find(
            {"snapshotType": "half_hour"},
            {"tradingDate": 1}
        )
    ))

    print(f"Found {len(dates)} trading dates: {dates[0]} ~ {dates[-1]}")

    previous_stocks: list[dict] = []
    written = 0

    for date in dates:
        # 取当日最后一帧
        last_frame = frames_coll.find_one(
            {"tradingDate": date, "snapshotType": "half_hour"},
            sort=[("timestamp", -1)],
        )
        if not last_frame:
            print(f"  {date}: no frames, skipping")
            continue

        stocks = last_frame.get("stocks") or []
        if not stocks:
            print(f"  {date}: empty stocks, skipping")
            continue

        up_count = sum(1 for s in stocks if float(s.get("change") or 0) > 0)
        down_count = sum(1 for s in stocks if float(s.get("change") or 0) < 0)
        up_ratio = round(up_count / len(stocks), 4) if stocks else 0
        hot_trin = compute_hot_trin(stocks)
        retention = compute_retention_rate(stocks, previous_stocks)
        turnover = compute_turnover(stocks, previous_stocks)

        # 简化版阶段判断（基于热榜 TRIN 和上涨比例）
        if up_ratio >= 0.60 and hot_trin is not None and hot_trin < 0.8:
            stage = "高潮"
            risk = "低"
        elif up_ratio >= 0.50:
            stage = "发酵"
            risk = "中"
        elif up_ratio >= 0.40:
            stage = "启动"
            risk = "中"
        else:
            stage = "退潮"
            risk = "高"

        doc = {
            "_id": date,
            "tradingDate": date,
            "snapshotType": "half_hour",
            "stage": stage,
            "riskLevel": risk,
            "confidence": 60,
            "summary": f"回填数据：上涨比例 {up_ratio:.1%}，热榜 TRIN {hot_trin}",
            "metrics": {
                "poolSize": len(stocks),
                "allPoolUpRatio": up_ratio,
                "hotTrin": hot_trin,
                "retentionRate1d": retention,
                "retentionRate2d": 0,
                "limitIntersectionRate": 0,
                "newEntryCount": len(turnover["newEntries"]),
                "eliminatedCount": len(turnover["eliminated"]),
            },
            "turnover": turnover,
            "signals": [],
            "warnings": ["历史回填数据，阶段判断为简化版"],
        }

        sentiment_coll.replace_one({"tradingDate": date}, doc, upsert=True)
        written += 1
        previous_stocks = stocks
        print(f"  {date}: {len(stocks)} stocks, upRatio={up_ratio:.1%}, stage={stage}")

    print(f"\nDone: {written}/{len(dates)} dates written to hotlist_sentiment")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 执行回填**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe scripts/backfill_hotlist_sentiment.py
```

Expected: 输出 34+ 个交易日的回填结果。

- [ ] **Step 3: 验证回填数据**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -c "
from backend.data.database import get_mongo_db
db = get_mongo_db()
docs = list(db['hotlist_sentiment'].find().sort('tradingDate', 1))
print(f'Total documents: {len(docs)}')
for d in docs[:3]:
    print(f'  {d[\"tradingDate\"]}: stage={d[\"stage\"]}, poolSize={d[\"metrics\"][\"poolSize\"]}')
print('...')
for d in docs[-3:]:
    print(f'  {d[\"tradingDate\"]}: stage={d[\"stage\"]}, poolSize={d[\"metrics\"][\"poolSize\"]}')
"
```

Expected: 所有交易日都有数据，poolSize 在 200-250 范围。

---

## Phase 4: compose_strategy() 改造——热榜情绪替换 market_regime

### Task 6: 改造 compose_strategy() 签名和逻辑

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend.py`
- Modify: `quant-board/tests/test_money_flow_quality_gate.py`

- [ ] **Step 1: 写 compose_strategy 新逻辑的测试**

在 `tests/test_money_flow_quality_gate.py` 追加：

```python
def test_compose_strategy_uses_hotlist_stage_instead_of_regime():
    from backend.analysis.ranktrend import (
        RankTrendConfig,
        compose_strategy,
    )

    technical = {
        "momentumProfile": {"short": 0.0, "mid": 5.0, "long": 3.0, "acceleration": 1.0},
        "signals": {
            "direction": {"signal": "buy"},
            "acceleration": {"signal": "buy"},
        },
        "macd": {"cross": "golden"},
    }
    cycle = {"stage": "expansion", "metrics": {}}
    risk = {"divergence": {"severity": 0.2}, "pressure": 0.2, "overheat": {"severity": 0.2}}

    # 高潮期 → A_MAIN 允许
    hotlist_climax = {"stage": "高潮", "riskLevel": "低", "confidence": 80}
    result = compose_strategy(technical, cycle, risk, hotlist=hotlist_climax)
    assert result["candidateTier"] == "A_MAIN"

    # 冰点期 → 禁止入场，应是 N_NEUTRAL
    hotlist_ice = {"stage": "冰点", "riskLevel": "高", "confidence": 20}
    result2 = compose_strategy(technical, cycle, risk, hotlist=hotlist_ice)
    assert result2["candidateTier"] != "A_MAIN"
    assert result2["candidateTier"] != "B_IGNITION"

    # 启动期 → 仅 B_IGNITION，A_MAIN 暂缓
    hotlist_start = {"stage": "启动", "riskLevel": "中", "confidence": 50}
    tech_ignition = {
        **technical,
        "momentumProfile": {"short": 4.0, "mid": 1.0, "long": 0.5, "acceleration": 0.8},
    }
    cycle_ignition = {"stage": "ignition", "metrics": {}}
    result3 = compose_strategy(tech_ignition, cycle_ignition, risk, hotlist=hotlist_start)
    assert result3["candidateTier"] == "B_IGNITION"

    # 退潮期 → D_EXIT_RISK 触发
    hotlist_retreat = {"stage": "退潮", "riskLevel": "高", "confidence": 30}
    tech_weak = {
        **technical,
        "momentumProfile": {"short": -3.0, "mid": -2.0, "long": -1.0, "acceleration": -3.0},
    }
    cycle_reversal = {"stage": "reversal", "metrics": {}}
    result4 = compose_strategy(tech_weak, cycle_reversal, risk, hotlist=hotlist_retreat)
    assert result4["candidateTier"] == "D_EXIT_RISK"


def test_compose_strategy_handles_none_hotlist():
    from backend.analysis.ranktrend import (
        RankTrendConfig,
        compose_strategy,
    )

    technical = {
        "momentumProfile": {"short": 0.0, "mid": 5.0, "long": 3.0, "acceleration": 1.0},
        "signals": {
            "direction": {"signal": "buy"},
            "acceleration": {"signal": "buy"},
        },
        "macd": {"cross": "golden"},
    }
    cycle = {"stage": "expansion", "metrics": {}}
    risk = {"divergence": {"severity": 0.2}, "pressure": 0.2, "overheat": {"severity": 0.2}}

    # None → 正常执行，不抛异常
    result = compose_strategy(technical, cycle, risk, hotlist=None)
    assert result["candidateTier"] in ("A_MAIN", "B_IGNITION", "N_NEUTRAL", "C_CROWDED", "D_EXIT_RISK")
    assert "reasons" in result
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py::test_compose_strategy_uses_hotlist_stage_instead_of_regime tests/test_money_flow_quality_gate.py::test_compose_strategy_handles_none_hotlist -v
```

Expected: FAIL (TypeError: compose_strategy() got unexpected keyword argument 'hotlist')

- [ ] **Step 3: 改造 compose_strategy() 函数**

```python
def compose_strategy(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    hotlist: dict | None = None,      # 替换原 regime 参数
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    c = config or RankTrendConfig()
    hl = hotlist or {}
    hl_stage = hl.get("stage", "启动")
    hl_risk = hl.get("riskLevel", "中")
    
    tier = "N_NEUTRAL"
    reasons: list[str] = []
    
    # ── 退潮/冰点：只做退出判断 ──
    if hl_stage in ("退潮", "冰点"):
        if (momentum["short"] <= c.tierExitRiskShortMomentumMax
            or momentum["acceleration"] <= c.tierExitRiskAccelMax
            or risk["pressure"] >= c.tierExitRiskPressureMin):
            tier = "D_EXIT_RISK"
            reasons.append(f"热榜{hl_stage}期，动量衰减触发退出风险")
        else:
            reasons.append(f"热榜{hl_stage}期，暂停入场")
        reasons.append(f"热榜情绪: {hl_stage}(风险{hl_risk})")
        return {
            "momentum": momentum,
            "candidateTier": tier,
            "action": {"A_MAIN": "focus", "B_IGNITION": "watch", "C_CROWDED": "avoid",
                       "D_EXIT_RISK": "exit_watch"}.get(tier, "hold"),
            "reasons": reasons,
        }
    
    # ── 阶段权限 ──
    rally_open = hl_stage in ("高潮", "发酵") and hl_risk != "高"
    caution_only = hl_stage == "启动" or hl_risk == "高"
    
    trend_buy = (
        technical["signals"]["direction"]["signal"] == "buy"
        or technical["signals"]["acceleration"]["signal"] == "buy"
        or technical["macd"]["cross"] == "golden"
    )
    
    # A_MAIN: 需要 rally_open（高潮/发酵且非高风险）
    if (stage == "expansion"
        and momentum["mid"] >= c.tierAMainMidMomentumMin
        and momentum["short"] >= c.tierAMainShortMomentumMin
        and trend_buy
        and risk["divergence"]["severity"] < c.tierAMainDivergenceSeverityMax):
        if rally_open:
            tier = "A_MAIN"
            reasons.append("扩散阶段中周期动量确认，热榜情绪支持A_MAIN入场")
        elif caution_only:
            reasons.append("热榜启动期/高风险，A_MAIN暂缓，降级观察")
    
    # B_IGNITION: rally_open 或 caution_only 均可
    if tier == "N_NEUTRAL" and stage == "ignition":
        if (momentum["short"] >= c.tierBIgnitionShortMomentumMin
            and momentum["acceleration"] >= c.tierBIgnitionAccelMin
            and hl_stage not in ("退潮", "冰点")
            and risk["pressure"] < c.tierBIgnitionRiskPressureMax):
            if rally_open or caution_only:
                tier = "B_IGNITION"
                reasons.append("点火阶段短周期冲击增强，热榜情绪支持B_IGNITION")
    
    # C_CROWDED
    if tier == "N_NEUTRAL":
        if (stage == "crowded"
            or (momentum["long"] >= c.tierCrowdedLongMomentumMin
                and (momentum["acceleration"] <= c.tierCrowdedAccelMax
                     or risk["pressure"] >= c.tierCrowdedRiskPressureMin))):
            tier = "C_CROWDED"
            reasons.append("长周期热度高位停留，追高性价比下降")
    
    # 退潮期退出判断
    if stage in ("reversal", "cooling") and (
        momentum["short"] <= c.tierExitRiskShortMomentumMax
        or momentum["acceleration"] <= c.tierExitRiskAccelMax
        or risk["pressure"] >= c.tierExitRiskPressureMin
    ):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    
    if hl_stage == "高潮":
        reasons.append("高潮期热榜情绪活跃，允许跟踪点火/扩散机会")
    if hl_stage in ("退潮", "冰点"):
        reasons.append("热榜情绪退潮/冰点，优先控制回撤风险")
    if risk["divergence"]["severity"] >= 0.6:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= 0.65:
        reasons.append("过热压力较高")
    reasons.append(
        f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} "
        f"长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}"
    )
    reasons.append(f"热榜情绪: {hl_stage}(风险{hl_risk})")
    
    action = {"A_MAIN": "focus", "B_IGNITION": "watch", "C_CROWDED": "avoid",
              "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {
        "momentum": momentum,
        "candidateTier": tier,
        "action": action,
        "reasons": reasons,
    }
```

- [ ] **Step 4: 运行新测试确认通过**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py::test_compose_strategy_uses_hotlist_stage_instead_of_regime tests/test_money_flow_quality_gate.py::test_compose_strategy_handles_none_hotlist -v
```

Expected: 2 tests PASS

---

### Task 7: 更新 compose_strategy 所有调用方

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend.py` — `_build_signal()` 调用点
- Modify: `quant-board/backend/core/backtest/strategy.py` — 移除 `_get_final_signal` 中对 regime 的依赖
- Modify: `quant-board/backend/core/backtest/execution.py` — 适配

- [ ] **Step 1: 更新 _build_signal() 调用**

找到 `ranktrend.py` 中 `_build_signal` 方法对 `compose_strategy` 的调用（约第 798 行），将 `regime` 参数改为 `hotlist`：

搜索 `compose_strategy(` 在 ranktrend.py 中的调用，将 `regime=regime` 替换为 `hotlist=frame.get("hotlistSentiment")`。

- [ ] **Step 2: 在 replay() 中预加载热榜情绪并按帧分发**

```python
# 在 replay() 方法开头附近加入预加载逻辑
def replay(self, frames, ...):
    # 预加载热榜情绪
    from backend.data.hotlist_sentiment_repo import HotListSentimentRepository
    from backend.data.database import get_mongo_db
    
    hotlist_by_date: dict[str, dict] = {}
    try:
        db = get_mongo_db()
        repo = HotListSentimentRepository(db)
        for frame in frames:
            date = frame.get("tradingDate", "")
            if date and date not in hotlist_by_date:
                doc = repo.get_by_date(date)
                if doc:
                    hotlist_by_date[date] = doc
    except Exception:
        pass  # 回退：没有 MongoDB 也能跑
    
    for frame in frames:
        date = frame.get("tradingDate", "")
        frame["hotlistSentiment"] = hotlist_by_date.get(date)
        ...
```

- [ ] **Step 3: 更新现有 compose_strategy 测试**

修改 `tests/test_money_flow_quality_gate.py` 中 `test_compose_strategy_uses_config_tier_thresholds` 和 `test_compose_strategy_respects_b_ignition_config_thresholds` 的调用签名，将 `regime` 参数替换为 `hotlist` 参数。

```python
# 旧调用
result = compose_strategy(technical, cycle, risk, regime)
# 新调用
hotlist_default = {"stage": "发酵", "riskLevel": "中"}
result = compose_strategy(technical, cycle, risk, hotlist=hotlist_default)
```

- [ ] **Step 4: 运行全部策略相关测试**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py -v -k "compose_strategy or entry_signal or exit_signal or entry_candidates or ranktrend_config"
```

Expected: 全部 PASS

- [ ] **Step 5: 运行完整测试集**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py tests/test_hotlist_sentiment_repo.py -v
```

Expected: 全部 PASS (~35 tests)

---

## Phase 5: 端到端验证

### Task 8: 回测验证

- [ ] **Step 1: 跑 H2 half_hour/next_bar 回测**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m backend.cli run-ranktrend --dataset-id dragonboard_live --snapshot-type half_hour --execution-mode next_bar
```

Expected: 回测正常完成，无报错。

- [ ] **Step 2: 对比核心指标变化**

记录 totalReturn、Sharpe、tradeCount、winRate，与之前基线对比。

- [ ] **Step 3: 跑 long-test baselines checkpoint**

```bash
cd /d/dragon-board/quant-board && .venv/Scripts/python.exe -m backend.cli run-longtest-baselines --checkpoint-id checkpoint_2026-06-05_hotlist_sentiment
```

Expected: 三条基线正常完成，JSONL 追加记录。

---

## 文件结构总结

```
新建:
  quant-board/backend/data/hotlist_sentiment_repo.py    # MongoDB 查询封装
  quant-board/tests/test_hotlist_sentiment_repo.py      # Repo 单元测试
  quant-board/backend/api/hotlist_routes.py             # ingest API 端点
  quant-board/scripts/backfill_hotlist_sentiment.py     # 历史回填脚本

修改:
  src/services/hotlist/HotListSentimentAnalyzer.ts       # 全池/turnover/persist
  src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts  # 新用例
  src/components/panels/DragonBreathPanel.vue            # 收盘触发
  quant-board/backend/analysis/ranktrend.py              # compose_strategy() 改造
  quant-board/backend/core/backtest/strategy.py          # 调用方适配
  quant-board/backend/core/backtest/execution.py         # 调用方适配
  quant-board/backend/services.py                        # replay 管线注入
  quant-board/backend/main.py                            # 注册 hotlist routes
  quant-board/tests/test_money_flow_quality_gate.py     # 适配 + 新增测试
  quant-board/tests/test_quant_board.py                  # ingest API 测试
```
