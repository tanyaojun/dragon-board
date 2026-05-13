# 交易日志模块 + 代码库清理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现深度交易日志模块（信号快照 + 截图 + 复盘标签）并清理 DragonAnalyzer 旧代码和 IndexedDB 残留。

**Architecture:** 四个独立阶段。Phase 1 直接删除 2 个确认死文件。Phase 2 将 6 个消费者从 DragonAnalyzer 迁移到 DragonReviewService（后者已有完整兼容 API）。Phase 3 在 QuantBoard 后端新增 trade_journal MongoDB collection + REST API + 前端管理面板。Phase 4 审计并迁移 IndexedDB 快照写入链到 MongoDB。

**Tech Stack:** Python FastAPI + PyMongo + MongoDB, Vue 3 + TypeScript + Pinia

---

## 重要前置发现

1. `DragonAnalyzerCompat.ts` **不存在**，从清理列表移除。
2. `DragonReviewService` 已有 `getAllLeaders(options?)` (line 207) 和 `getStats()` (line 256)，与 DragonAnalyzer 接口完全兼容。Phase 2 只需换 import 路径。
3. `VoiceService`, `exportService`, `SearchIndex`, `StockHotnessCalculator` 经 grep 验证均有活跃引用链，**全部保留**。

---

## Phase 1: 直接删除死代码

### Task 1: 删除 ContextBuilder.ts 及测试

**Files:**
- Delete: `src/services/dragon/ContextBuilder.ts`
- Delete: `src/services/dragon/__tests__/ContextBuilder.test.ts`

**引用证据：** `ContextBuilder.ts` 仅被自身测试文件 import (`grep -r ContextBuilder src/ → 仅 __tests__/ContextBuilder.test.ts`)。dragon/index.ts 不导出它。生产路径已离线。

- [ ] **Step 1: 确认零引用**

```bash
grep -rn "ContextBuilder" d:/dragon-board/src/ --include="*.ts" --include="*.vue" | grep -v "__tests__" | grep -v "ContextBuilder.ts"
```
Expected: no output

- [ ] **Step 2: 删除文件**

```bash
rm d:/dragon-board/src/services/dragon/ContextBuilder.ts
rm d:/dragon-board/src/services/dragon/__tests__/ContextBuilder.test.ts
```

- [ ] **Step 3: 验证构建**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | head -20
```
Expected: 无新增类型错误

- [ ] **Step 4: 运行测试**

```bash
cd d:/dragon-board && npx vitest run 2>&1 | tail -20
```
Expected: 所有测试通过（ContextBuilder.test.ts 不再存在）

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add -A && git commit -m "$(cat <<'EOF'
chore: delete dead ContextBuilder.ts

Zero production references (grep verified). Only had self-test import.
EOF
)"
```

---

### Task 2: 删除 moneyFlowDiagnostics.ts 及测试

**Files:**
- Delete: `src/services/moneyFlowDiagnostics.ts`
- Delete: `src/services/__tests__/moneyFlowDiagnostics.test.ts`

**引用证据：** 仅被自身测试文件 import，诊断工具不入业务链。

- [ ] **Step 1: 确认零引用**

```bash
grep -rn "moneyFlowDiagnostics" d:/dragon-board/src/ --include="*.ts" --include="*.vue" | grep -v "__tests__" | grep -v "moneyFlowDiagnostics.ts"
```
Expected: no output

- [ ] **Step 2: 删除文件**

```bash
rm d:/dragon-board/src/services/moneyFlowDiagnostics.ts
rm d:/dragon-board/src/services/__tests__/moneyFlowDiagnostics.test.ts
```

- [ ] **Step 3: 验证构建和测试**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | head -20
cd d:/dragon-board && npx vitest run 2>&1 | tail -10
```
Expected: 类型检查通过，测试全部通过

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add -A && git commit -m "$(cat <<'EOF'
chore: delete dead moneyFlowDiagnostics.ts

Diagnostic-only file with zero business imports (grep verified).
EOF
)"
```

---

## Phase 2: DragonAnalyzer 迁移到 DragonReviewService

### Task 3: 迁移 stores/stock.ts

**Files:** Modify `src/stores/stock.ts:10,285`

DragonReviewService 已有兼容的 `getAllLeaders()` (line 207) 和 `getStats()` (line 256)。

- [ ] **Step 1: 替换 import**

```typescript
// Before (line 10):
import { dragonAnalyzer } from '@/services/DragonAnalyzer'

// After:
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
```

- [ ] **Step 2: 替换调用 (line 285)**

```typescript
// Before:
const leaders = dragonAnalyzer.getAllLeaders?.() || []

// After:
const leaders = dragonReviewService.getAllLeaders?.() || []
```

- [ ] **Step 3: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "stock.ts"
```
Expected: no errors in stock.ts

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add src/stores/stock.ts && git commit -m "$(cat <<'EOF'
refactor: migrate stock store from DragonAnalyzer to DragonReviewService

DragonReviewService already provides compatible getAllLeaders() API.
EOF
)"
```

---

### Task 4: 迁移 ExportPanel.vue

**Files:** Modify `src/components/panels/ExportPanel.vue:104,163,190,222,234`

- [ ] **Step 1: 替换 import (line 104)**

```typescript
// Before:
import { dragonAnalyzer } from '@/services/DragonAnalyzer'

// After:
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
```

- [ ] **Step 2: 替换 getStats() 调用 (lines 163, 222, 234)**

```typescript
// Before (line 163):
const byLevel = dragonAnalyzer.getStats()

// After:
const byLevel = dragonReviewService.getStats()

// Before (line 222):
leaders: dragonAnalyzer.getStats(),

// After:
leaders: dragonReviewService.getStats(),

// Before (line 234):
leaders: dragonAnalyzer.getStats(),

// After:
leaders: dragonReviewService.getStats(),
```

- [ ] **Step 3: 替换 getAllLeaders() 调用 (line 190)**

```typescript
// Before:
const leaders = dragonAnalyzer.getAllLeaders?.() || []

// After:
const leaders = dragonReviewService.getAllLeaders?.() || []
```

- [ ] **Step 4: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "ExportPanel"
```
Expected: no errors

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add src/components/panels/ExportPanel.vue && git commit -m "$(cat <<'EOF'
refactor: migrate ExportPanel from DragonAnalyzer to DragonReviewService
EOF
)"
```

---

### Task 5: 迁移 exportService.ts

**Files:** Modify `src/services/exportService.ts:6,109,131,323`

- [ ] **Step 1: 替换 import (line 6)**

```typescript
// Before:
import { dragonAnalyzer } from './DragonAnalyzer'

// After:
import { dragonReviewService } from './dragon/DragonReviewService'
```

- [ ] **Step 2: 替换 getStats() 调用 (lines 109, 131)**

```typescript
// Before (line 109):
leaders: dragonAnalyzer.getStats(),

// After:
leaders: dragonReviewService.getStats(),

// Before (line 131):
leaders: dragonAnalyzer.getStats(),

// After:
leaders: dragonReviewService.getStats(),
```

- [ ] **Step 3: 替换 getAllLeaders() 调用 (line 323)**

```typescript
// Before:
const leaders = dragonAnalyzer.getAllLeaders?.() || []

// After:
const leaders = dragonReviewService.getAllLeaders?.() || []
```

- [ ] **Step 4: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "exportService"
```
Expected: no errors

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add src/services/exportService.ts && git commit -m "$(cat <<'EOF'
refactor: migrate exportService from DragonAnalyzer to DragonReviewService
EOF
)"
```

---

### Task 6: 迁移 App.vue

**Files:** Modify `src/App.vue:223,514`

- [ ] **Step 1: 替换 import (line 223)**

```typescript
// Before:
import { dragonAnalyzer } from './services/DragonAnalyzer'    // 龙头分析

// After:
import { dragonReviewService } from './services/dragon/DragonReviewService'  // 龙头分析
```

- [ ] **Step 2: 替换 recalculateAll 调用 (line 514)**

```typescript
// Before:
safeExecute(dragonAnalyzer, 'recalculateAll', '旧龙头兼容计算').then(() => {})

// After:
safeExecute(dragonReviewService, 'recalculateAll', '旧龙头兼容计算').then(() => {})
```

- [ ] **Step 3: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "App.vue"
```
Expected: no errors related to dragonAnalyzer

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add src/App.vue && git commit -m "$(cat <<'EOF'
refactor: migrate App.vue from DragonAnalyzer to DragonReviewService
EOF
)"
```

---

### Task 7: 迁移 main.ts

**Files:** Modify `src/main.ts:41,67,101`

- [ ] **Step 1: 替换 import (line 41)**

```typescript
// Before:
import { dragonAnalyzer } from './services/DragonAnalyzer'

// After:
import { dragonReviewService } from './services/dragon/DragonReviewService'
```

- [ ] **Step 2: 替换 window 挂载 (line 67)**

```typescript
// Before:
;(window as any).dragonAnalyzer = dragonAnalyzer

// After:
;(window as any).dragonReviewService = dragonReviewService
```

- [ ] **Step 3: 替换 console.log (line 101)**

```typescript
// Before:
console.log('   ├─ dragonAnalyzer: 龙头分析')

// After:
console.log('   ├─ dragonReviewService: 龙头分析')
```

- [ ] **Step 4: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "main.ts"
```
Expected: no errors

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add src/main.ts && git commit -m "$(cat <<'EOF'
refactor: migrate main.ts from DragonAnalyzer to DragonReviewService
EOF
)"
```

---

### Task 8: 迁移 dragonDiagnostic.ts（诊断工具）

**Files:** Modify `src/devtools/diagnostics/dragonDiagnostic.ts:70,82,83,167,185`

- [ ] **Step 1: 替换 window 引用**

```typescript
// Before (line 70):
const leaders = window.dragonAnalyzer.getAllLeaders?.()

// After:
const leaders = window.dragonReviewService?.getAllLeaders?.()

// Before (line 82):
results.dragonAnalyzer.leaders = leaders

// After:
results.dragonReviewService.leaders = leaders

// Before (line 83):
results.dragonAnalyzer.status = '✅'

// After:
results.dragonReviewService.status = '✅'

// Before (line 167):
龙头分析器: ${results.dragonAnalyzer.status}

// After:
龙头分析器: ${results.dragonReviewService.status}

// Before (line 185):
leaders: results.dragonAnalyzer.leaders?.length || 0,

// After:
leaders: results.dragonReviewService.leaders?.length || 0,
```

- [ ] **Step 2: 验证（诊断文件不在 tsconfig 范围内，手动确认即可）**

```bash
grep -rn "dragonAnalyzer" d:/dragon-board/src/devtools/ --include="*.ts"
```
Expected: no output（确认已无残留引用）

- [ ] **Step 3: 提交**

```bash
cd d:/dragon-board && git add src/devtools/diagnostics/dragonDiagnostic.ts && git commit -m "$(cat <<'EOF'
refactor: migrate dragon diagnostic from DragonAnalyzer to DragonReviewService
EOF
)"
```

---

### Task 9: 删除 DragonAnalyzer.ts 及测试 — 最终验证

**Files:**
- Delete: `src/services/DragonAnalyzer.ts`
- Delete: `src/services/__tests__/DragonAnalyzer.test.ts`（如存在）

- [ ] **Step 1: 确认全项目零引用**

```bash
grep -rn "DragonAnalyzer" d:/dragon-board/src/ --include="*.ts" --include="*.vue" | grep -v "DragonBreathAnalyzer" | grep -v "node_modules"
```
Expected: 仅匹配 DragonAnalyzer.ts 自身

- [ ] **Step 2: 删除文件**

```bash
rm d:/dragon-board/src/services/DragonAnalyzer.ts
# 如有测试文件一并删除
rm -f d:/dragon-board/src/services/__tests__/DragonAnalyzer.test.ts
```

- [ ] **Step 3: 全量类型检查**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | tail -10
```
Expected: 无错误

- [ ] **Step 4: 全量测试**

```bash
cd d:/dragon-board && npx vitest run 2>&1 | tail -15
```
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add -A && git commit -m "$(cat <<'EOF'
refactor: delete DragonAnalyzer.ts after full migration to DragonReviewService

All 6 consumers migrated (App.vue, main.ts, ExportPanel.vue, exportService.ts,
stores/stock.ts, dragonDiagnostic.ts). DragonReviewService already provides
compatible getAllLeaders() and getStats() APIs.
EOF
)"
```

---

## Phase 3: 交易日志模块

### Task 10: 注册 trade_journal collection + indexes

**Files:** Modify `quant-board/backend/data/mongodb_migration.py`

- [ ] **Step 1: 添加 collection 名到集合元组**

在 `RESEARCH_COLLECTIONS` (line 22) 后新增一个 `JOURNAL_COLLECTIONS` 元组：

```python
# 在 line 34 之后添加:
JOURNAL_COLLECTIONS = ("trade_journal",)

# 修改 ALL_COLLECTIONS (line 38):
ALL_COLLECTIONS = (*SNAPSHOT_COLLECTIONS, *RESEARCH_COLLECTIONS, *THEME_COLLECTIONS, *RUNTIME_COLLECTIONS, *JOURNAL_COLLECTIONS)
```

- [ ] **Step 2: 添加 indexes 到 build_mongodb_indexes()**

在 `build_mongodb_indexes()` 函数的 return dict 中添加（在 `"migration_audit"` 条目之后）：

```python
"trade_journal": [
    {"keys": [("id", 1)], "unique": True},
    {"keys": [("stockCode", 1), ("tradeTime", -1)]},
    {"keys": [("tradeType", 1), ("createdAt", -1)]},
    {"keys": [("linkedEntryId", 1)]},
],
```

- [ ] **Step 3: 验证 Python 语法**

```bash
cd d:/dragon-board/quant-board && .\.venv\Scripts\python.exe -c "from backend.data.mongodb_migration import build_mongodb_indexes; indexes = build_mongodb_indexes(); print('trade_journal' in indexes)"
```
Expected: `True`

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add quant-board/backend/data/mongodb_migration.py && git commit -m "$(cat <<'EOF'
feat: add trade_journal collection and indexes to MongoDB schema
EOF
)"
```

---

### Task 11: 新增 TradeJournal 领域模型

**Files:** Modify `quant-board/backend/data/models.py`

- [ ] **Step 1: 在 models.py 末尾添加 TradeJournal 模型类**

读取 `models.py` 末尾，追加以下代码：

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TradeJournal:
    id: str
    stock_code: str
    stock_name: str
    direction: str  # "buy" | "sell"
    trade_type: str  # "entry" | "exit"
    price: float
    volume: int
    trade_time: str  # ISO 8601
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = field(default_factory=dict)
    notes: str = ""
    screenshot_paths: list[str] = field(default_factory=list)
    review_tags: list[str] = field(default_factory=list)
    pnl: float | None = None
    pnl_pct: float | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stockCode": self.stock_code,
            "stockName": self.stock_name,
            "direction": self.direction,
            "tradeType": self.trade_type,
            "price": self.price,
            "volume": self.volume,
            "tradeTime": self.trade_time,
            "linkedEntryId": self.linked_entry_id,
            "signalsSnapshot": self.signals_snapshot,
            "notes": self.notes,
            "screenshotPaths": self.screenshot_paths,
            "reviewTags": self.review_tags,
            "pnl": self.pnl,
            "pnlPct": self.pnl_pct,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradeJournal":
        return cls(
            id=str(data.get("id") or ""),
            stock_code=str(data.get("stockCode") or ""),
            stock_name=str(data.get("stockName") or ""),
            direction=str(data.get("direction") or ""),
            trade_type=str(data.get("tradeType") or "entry"),
            price=float(data.get("price") or 0),
            volume=int(data.get("volume") or 0),
            trade_time=str(data.get("tradeTime") or ""),
            linked_entry_id=data.get("linkedEntryId"),
            signals_snapshot=data.get("signalsSnapshot") or {},
            notes=str(data.get("notes") or ""),
            screenshot_paths=list(data.get("screenshotPaths") or []),
            review_tags=list(data.get("reviewTags") or []),
            pnl=float(data["pnl"]) if data.get("pnl") is not None else None,
            pnl_pct=float(data["pnlPct"]) if data.get("pnlPct") is not None else None,
            created_at=str(data.get("createdAt") or ""),
            updated_at=str(data.get("updatedAt") or ""),
        )
```

- [ ] **Step 2: 验证**

```bash
cd d:/dragon-board/quant-board && .\.venv\Scripts\python.exe -c "from backend.data.models import TradeJournal; t = TradeJournal(id='tj_test', stock_code='000001', stock_name='test', direction='buy', trade_type='entry', price=10.0, volume=100, trade_time='2026-05-13T10:00:00'); print(t.to_dict()['id'])"
```
Expected: `tj_test`

- [ ] **Step 3: 提交**

```bash
cd d:/dragon-board && git add quant-board/backend/data/models.py && git commit -m "$(cat <<'EOF'
feat: add TradeJournal domain model
EOF
)"
```

---

### Task 12: 新增 MongoResearchRepository trade_journal CRUD 方法

**Files:** Modify `quant-board/backend/data/mongo_research_repository.py`

- [ ] **Step 1: 在文件末尾追加 trade_journal CRUD 方法**

```python
    # ========== Trade Journal ==========

    def save_journal_entry(self, entry: "TradeJournal") -> "TradeJournal":
        from backend.data.models import TradeJournal
        doc = entry.to_dict()
        self.db["trade_journal"].replace_one({"id": entry.id}, doc, upsert=True)
        row = self.db["trade_journal"].find_one({"id": entry.id})
        return TradeJournal.from_dict(self._drop_mongo_id(row)) if row else entry

    def get_journal_entry(self, entry_id: str) -> dict[str, Any] | None:
        row = self.db["trade_journal"].find_one({"id": entry_id})
        return self._drop_mongo_id(row) if row else None

    def list_journal_entries(
        self,
        stock_code: str | None = None,
        trade_type: str | None = None,
        direction: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        review_tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if stock_code:
            query["stockCode"] = stock_code
        if trade_type:
            query["tradeType"] = trade_type
        if direction:
            query["direction"] = direction
        if date_from or date_to:
            query["tradeTime"] = {}
            if date_from:
                query["tradeTime"]["$gte"] = date_from
            if date_to:
                query["tradeTime"]["$lte"] = date_to
        if review_tags:
            query["reviewTags"] = {"$in": review_tags}

        cursor = (
            self.db["trade_journal"]
            .find(query)
            .sort([("tradeTime", -1)])
            .skip(offset)
            .limit(limit)
        )
        return [self._drop_mongo_id(row) for row in cursor]

    def count_journal_entries(
        self,
        stock_code: str | None = None,
        trade_type: str | None = None,
        direction: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> int:
        query: dict[str, Any] = {}
        if stock_code:
            query["stockCode"] = stock_code
        if trade_type:
            query["tradeType"] = trade_type
        if direction:
            query["direction"] = direction
        if date_from or date_to:
            query["tradeTime"] = {}
            if date_from:
                query["tradeTime"]["$gte"] = date_from
            if date_to:
                query["tradeTime"]["$lte"] = date_to
        return self.db["trade_journal"].count_documents(query)

    def delete_journal_entry(self, entry_id: str) -> bool:
        result = self.db["trade_journal"].delete_one({"id": entry_id})
        return result.deleted_count > 0

    def delete_linked_exits(self, linked_entry_id: str) -> int:
        result = self.db["trade_journal"].delete_many({"linkedEntryId": linked_entry_id})
        return result.deleted_count

    def update_journal_entry(self, entry_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updatedAt"] = datetime.now(UTC).isoformat()
        result = self.db["trade_journal"].update_one({"id": entry_id}, {"$set": updates})
        if result.matched_count == 0:
            return None
        return self.get_journal_entry(entry_id)

    def get_journal_stats(self) -> dict[str, Any]:
        pipeline = [
            {"$match": {"reviewTags": {"$ne": None, "$not": {"$size": 0}}}},
            {"$unwind": "$reviewTags"},
            {"$group": {"_id": "$reviewTags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        tag_counts = {
            doc["_id"]: doc["count"]
            for doc in self.db["trade_journal"].aggregate(pipeline)
        }

        entries_with_pnl = list(
            self.db["trade_journal"].find(
                {"pnl": {"$ne": None}, "tradeType": "exit"}
            )
        )
        total_pnl = sum(e.get("pnl", 0) for e in entries_with_pnl)
        win_count = sum(1 for e in entries_with_pnl if e.get("pnl", 0) > 0)
        total_exits = len(entries_with_pnl)

        return {
            "tagCounts": tag_counts,
            "totalPnl": total_pnl,
            "winRate": win_count / total_exits if total_exits > 0 else 0,
            "totalExits": total_exits,
        }
```

- [ ] **Step 2: 验证**

```bash
cd d:/dragon-board/quant-board && .\.venv\Scripts\python.exe -c "from backend.data.mongo_research_repository import MongoResearchRepository; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
cd d:/dragon-board && git add quant-board/backend/data/mongo_research_repository.py && git commit -m "$(cat <<'EOF'
feat: add trade_journal CRUD methods to MongoResearchRepository
EOF
)"
```

---

### Task 13: 新增 /api/journal 路由

**Files:** Create `quant-board/backend/api/journal_routes.py`

- [ ] **Step 1: 创建路由文件**

```python
from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.data.models import TradeJournal
from backend.data.repository_factory import create_repository


router = APIRouter(prefix="/api/journal", tags=["journal"])

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "journal_screenshots"
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _new_journal_id() -> str:
    return f"tj_{uuid.uuid4().hex[:16]}"


def _get_repo():
    return create_repository(None)


# --- Request Models ---

class CreateJournalEntryRequest(BaseModel):
    stock_code: str
    stock_name: str
    direction: str  # "buy" | "sell"
    trade_type: str = "entry"  # "entry" | "exit"
    price: float
    volume: int
    trade_time: str  # ISO 8601
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = None
    notes: str = ""


class UpdateJournalEntryRequest(BaseModel):
    stock_code: str | None = None
    stock_name: str | None = None
    direction: str | None = None
    trade_type: str | None = None
    price: float | None = None
    volume: int | None = None
    trade_time: str | None = None
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = None
    notes: str | None = None
    review_tags: list[str] | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


# --- Routes ---

@router.post("/entries")
def create_entry(payload: CreateJournalEntryRequest) -> dict[str, Any]:
    repo = _get_repo()
    now = datetime.now(UTC).isoformat()
    entry = TradeJournal(
        id=_new_journal_id(),
        stock_code=payload.stock_code,
        stock_name=payload.stock_name,
        direction=payload.direction,
        trade_type=payload.trade_type,
        price=payload.price,
        volume=payload.volume,
        trade_time=payload.trade_time,
        linked_entry_id=payload.linked_entry_id,
        signals_snapshot=payload.signals_snapshot,
        notes=payload.notes,
        created_at=now,
        updated_at=now,
    )
    repo.save_journal_entry(entry)
    return entry.to_dict()


@router.get("/entries")
def list_entries(
    stock_code: str | None = Query(None),
    trade_type: str | None = Query(None),
    direction: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    review_tags: str | None = Query(None),  # comma-separated
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    repo = _get_repo()
    tags_list = [t.strip() for t in review_tags.split(",") if t.strip()] if review_tags else None
    entries = repo.list_journal_entries(
        stock_code=stock_code,
        trade_type=trade_type,
        direction=direction,
        date_from=date_from,
        date_to=date_to,
        review_tags=tags_list,
        limit=limit,
        offset=offset,
    )
    total = repo.count_journal_entries(
        stock_code=stock_code,
        trade_type=trade_type,
        direction=direction,
        date_from=date_from,
        date_to=date_to,
    )
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str) -> dict[str, Any]:
    repo = _get_repo()
    entry = repo.get_journal_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    return entry


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, payload: UpdateJournalEntryRequest) -> dict[str, Any]:
    repo = _get_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    updates: dict[str, Any] = {}
    field_map = {
        "stock_code": "stockCode",
        "stock_name": "stockName",
        "direction": "direction",
        "trade_type": "tradeType",
        "price": "price",
        "volume": "volume",
        "trade_time": "tradeTime",
        "linked_entry_id": "linkedEntryId",
        "signals_snapshot": "signalsSnapshot",
        "notes": "notes",
        "review_tags": "reviewTags",
        "pnl": "pnl",
        "pnl_pct": "pnlPct",
    }
    for py_field, doc_field in field_map.items():
        value = getattr(payload, py_field)
        if value is not None:
            updates[doc_field] = value

    result = repo.update_journal_entry(entry_id, updates)
    if not result:
        raise HTTPException(status_code=500, detail="更新失败")
    return result


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str) -> dict[str, str]:
    repo = _get_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    repo.delete_linked_exits(entry_id)
    repo.delete_journal_entry(entry_id)

    entry_screenshots = SCREENSHOTS_DIR / entry_id
    if entry_screenshots.exists():
        shutil.rmtree(entry_screenshots)

    return {"status": "deleted", "id": entry_id}


@router.post("/entries/{entry_id}/screenshot")
def upload_screenshot(entry_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    repo = _get_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    contents = file.file.read()
    if len(contents) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=400, detail="截图不能超过 10MB")

    entry_dir = SCREENSHOTS_DIR / entry_id
    entry_dir.mkdir(parents=True, exist_ok=True)

    existing_files = list(entry_dir.glob(f"{entry_id}_*{ext}")) if ext else []
    suffix_index = len(existing_files) + 1
    filename = f"{entry_id}_{suffix_index}{ext}"
    filepath = entry_dir / filename

    with open(filepath, "wb") as f:
        f.write(contents)

    relative_path = f"journal_screenshots/{entry_id}/{filename}"

    screenshot_paths = list(existing.get("screenshotPaths") or [])
    screenshot_paths.append(relative_path)
    repo.update_journal_entry(entry_id, {"screenshotPaths": screenshot_paths})

    return {"path": relative_path, "screenshotPaths": screenshot_paths}


@router.get("/stats")
def get_stats(
    stock_code: str | None = Query(None),
) -> dict[str, Any]:
    repo = _get_repo()
    return repo.get_journal_stats()
```

- [ ] **Step 2: 验证路由文件语法**

```bash
cd d:/dragon-board/quant-board && .\.venv\Scripts\python.exe -c "from backend.api.journal_routes import router; print(f'Routes: {len(router.routes)}')"
```
Expected: `Routes: 7`

- [ ] **Step 3: 提交**

```bash
cd d:/dragon-board && git add quant-board/backend/api/journal_routes.py && git commit -m "$(cat <<'EOF'
feat: add trade journal REST API routes

POST /api/journal/entries - Create entry
GET  /api/journal/entries - List with filters
GET  /api/journal/entries/{id} - Single entry
PUT  /api/journal/entries/{id} - Update entry
DELETE /api/journal/entries/{id} - Delete + cascade
POST /api/journal/entries/{id}/screenshot - Upload screenshot
GET  /api/journal/stats - Aggregated statistics
EOF
)"
```

---

### Task 14: 在 main.py 注册路由

**Files:** Modify `quant-board/backend/main.py`

- [ ] **Step 1: 添加 import（在现有 import 块末尾）**

```python
from backend.api.journal_routes import router as journal_router
```

- [ ] **Step 2: 注册路由（在 `app = FastAPI(...)` 之后、第一个 `@app` 路由之前）**

```python
app.include_router(journal_router)
```

- [ ] **Step 3: 验证启动**

```bash
cd d:/dragon-board/quant-board && timeout 5 .\.venv\Scripts\python.exe -c "from backend.main import app; print('Router registered:', any(r for r in app.routes if hasattr(r, 'path') and '/api/journal' in str(r.path)))" 2>&1
```
Expected: `Router registered: True`

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add quant-board/backend/main.py && git commit -m "$(cat <<'EOF'
feat: register trade journal routes in main.py
EOF
)"
```

---

### Task 15: 创建前端 TradeJournalPanel.vue

**Files:** Create `src/components/panels/TradeJournalPanel.vue`

- [ ] **Step 1: 创建组件**

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dataLayer } from '@/services/DataLayer'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { getRankTrendAnalysis } from '@/services/rankTrend/compat'

interface JournalEntry {
  id: string
  stockCode: string
  stockName: string
  direction: string
  tradeType: string
  price: number
  volume: number
  tradeTime: string
  linkedEntryId: string | null
  signalsSnapshot: Record<string, any> | null
  notes: string
  screenshotPaths: string[]
  reviewTags: string[]
  pnl: number | null
  pnlPct: number | null
  createdAt: string
  updatedAt: string
}

// ---- State ----
const entries = ref<JournalEntry[]>([])
const loading = ref(false)
const selectedId = ref<string | null>(null)
const filterStock = ref('')
const filterDirection = ref('')

// Form state
const form = ref({
  stockCode: '',
  stockName: '',
  direction: 'buy' as 'buy' | 'sell',
  tradeType: 'entry' as 'entry' | 'exit',
  price: 0,
  volume: 0,
  tradeTime: new Date().toISOString(),
  linkedEntryId: null as string | null,
  notes: '',
  signalsSnapshot: null as Record<string, any> | null,
})

const reviewTagsInput = ref('')
const entryNotes = ref('')
const exitPrice = ref(0)
const exitVolume = ref(0)

const PRESET_TAGS = ['追高', '卖早', '信号正确未执行', '信号正确执行到位', '信号错误', '止损', '止盈', '恐慌卖出', '仓位过重', '仓位过轻']

// ---- Computed ----
const selectedEntry = computed(() => entries.value.find(e => e.id === selectedId.value) || null)

const linkedEntry = computed(() => {
  if (!selectedEntry.value?.linkedEntryId) return null
  return entries.value.find(e => e.id === selectedEntry.value!.linkedEntryId) || null
})

const filteredEntries = computed(() => {
  let list = entries.value
  if (filterStock.value) {
    const q = filterStock.value.toUpperCase()
    list = list.filter(e => e.stockCode.includes(q) || e.stockName.includes(q))
  }
  if (filterDirection.value) {
    list = list.filter(e => e.direction === filterDirection.value)
  }
  return list
})

const stats = ref<{ tagCounts: Record<string, number>; totalPnl: number; winRate: number; totalExits: number } | null>(null)

// ---- Methods ----
async function loadEntries() {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '100' })
    if (filterStock.value) params.set('stockCode', filterStock.value)
    if (filterDirection.value) params.set('direction', filterDirection.value)
    const res = await fetch(`/api/journal/entries?${params}`)
    const data = await res.json()
    entries.value = data.entries || []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const res = await fetch('/api/journal/stats')
    stats.value = await res.json()
  } catch { /* ignore */ }
}

function captureSignals(stockCode: string) {
  const stock = dataLayer.getStock(stockCode)
  const review = dragonReviewService.getLatestReview()
  const sentiment = dragonBreathAnalyzer.getMarketSentiment()
  const rankTrend = stock ? getRankTrendAnalysis(stock) : null

  const dragonRecord = review
    ? (review.trueLeaders || []).find(r => r.code === stockCode)
      || (review.heightBoard || []).find(r => r.code === stockCode)
      || (review.attentionBoard || []).find(r => r.code === stockCode)
      || review.marketCore
    : null

  form.value.signalsSnapshot = {
    dragon: dragonRecord ? {
      primaryRole: dragonRecord.primaryRole,
      authorityClass: dragonRecord.authority,
      tradeability: dragonRecord.tradeability,
    } : null,
    sentiment: {
      emotionPhase: sentiment?.phaseName || sentiment?.phase || '',
      breathScore: sentiment?.overall ?? 0,
    },
    rankTrend: rankTrend ? {
      candidateTier: rankTrend.strategy?.candidateTier || 'N_NEUTRAL',
      momentumComposite: rankTrend.technical.momentumProfile.composite,
      attentionStage: rankTrend.cycle.stage,
      decision: rankTrend.decision.final.signal,
    } : null,
  }
}

async function saveEntry() {
  const payload = {
    stock_code: form.value.stockCode,
    stock_name: form.value.stockName,
    direction: form.value.direction,
    trade_type: form.value.tradeType,
    price: form.value.price,
    volume: form.value.volume,
    trade_time: form.value.tradeTime,
    linked_entry_id: form.value.linkedEntryId,
    signals_snapshot: form.value.signalsSnapshot || {},
    notes: form.value.notes,
  }

  let res: Response
  if (selectedId.value) {
    res = await fetch(`/api/journal/entries/${selectedId.value}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } else {
    res = await fetch('/api/journal/entries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }

  if (res.ok) {
    resetForm()
    await loadEntries()
    await loadStats()
  }
}

async function recordExit() {
  if (!selectedEntry.value) return
  const exitPayload = {
    stock_code: selectedEntry.value.stockCode,
    stock_name: selectedEntry.value.stockName,
    direction: selectedEntry.value.direction === 'buy' ? 'sell' : 'buy',
    trade_type: 'exit',
    price: exitPrice.value,
    volume: exitVolume.value || selectedEntry.value.volume,
    trade_time: new Date().toISOString(),
    linked_entry_id: selectedEntry.value.id,
    notes: entryNotes.value,
  }
  const res = await fetch('/api/journal/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(exitPayload),
  })
  if (res.ok) {
    const exitData = await res.json()
    // 计算盈亏并更新入场记录
    const pnl = (exitPayload.price - selectedEntry.value.price) * exitPayload.volume
    const pnlPct = ((exitPayload.price - selectedEntry.value.price) / selectedEntry.value.price) * 100
    await fetch(`/api/journal/entries/${selectedEntry.value.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pnl, pnl_pct: pnlPct }),
    })
    exitPrice.value = 0
    exitVolume.value = 0
    entryNotes.value = ''
    await loadEntries()
    await loadStats()
  }
}

async function addReviewTags() {
  if (!selectedEntry.value || !reviewTagsInput.value) return
  const newTags = reviewTagsInput.value.split(',').map(t => t.trim()).filter(Boolean)
  const existingTags = selectedEntry.value.reviewTags || []
  const merged = [...new Set([...existingTags, ...newTags])]
  await fetch(`/api/journal/entries/${selectedEntry.value.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ review_tags: merged }),
  })
  reviewTagsInput.value = ''
  await loadEntries()
  await loadStats()
}

async function deleteEntry(id: string) {
  if (!confirm('确认删除此交易记录？关联的出场记录也会被删除。')) return
  await fetch(`/api/journal/entries/${id}`, { method: 'DELETE' })
  if (selectedId.value === id) selectedId.value = null
  await loadEntries()
  await loadStats()
}

async function uploadScreenshot(file: File) {
  if (!selectedId.value) return
  const formData = new FormData()
  formData.append('file', file)
  await fetch(`/api/journal/entries/${selectedId.value}/screenshot`, {
    method: 'POST',
    body: formData,
  })
  await loadEntries()
}

function resetForm() {
  selectedId.value = null
  form.value = {
    stockCode: '',
    stockName: '',
    direction: 'buy',
    tradeType: 'entry',
    price: 0,
    volume: 0,
    tradeTime: new Date().toISOString(),
    linkedEntryId: null,
    notes: '',
    signalsSnapshot: null,
  }
}

function selectEntry(entry: JournalEntry) {
  selectedId.value = entry.id
  form.value = {
    stockCode: entry.stockCode,
    stockName: entry.stockName,
    direction: entry.direction as 'buy' | 'sell',
    tradeType: entry.tradeType as 'entry' | 'exit',
    price: entry.price,
    volume: entry.volume,
    tradeTime: entry.tradeTime,
    linkedEntryId: entry.linkedEntryId,
    notes: entry.notes,
    signalsSnapshot: entry.signalsSnapshot,
  }
}

onMounted(() => {
  loadEntries()
  loadStats()
})

// Stock search: use current hotlist
const stockOptions = computed(() => {
  return dataLayer.getMergedStocks().slice(0, 200).map(s => ({
    code: s.code,
    name: s.name,
  }))
})

function selectStock(code: string, name: string) {
  form.value.stockCode = code
  form.value.stockName = name
  captureSignals(code)
}
</script>

<template>
  <div class="trade-journal-panel">
    <!-- Left: Entry List -->
    <div class="journal-list">
      <div class="list-header">
        <input v-model="filterStock" placeholder="搜索标的..." @input="loadEntries" />
        <select v-model="filterDirection" @change="loadEntries">
          <option value="">全部方向</option>
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
        <button @click="resetForm(); loadEntries()">+ 新增</button>
      </div>
      <div class="entries">
        <div
          v-for="entry in filteredEntries"
          :key="entry.id"
          :class="['entry-row', { selected: entry.id === selectedId }]"
          @click="selectEntry(entry)"
        >
          <span :class="`dir-${entry.direction}`">{{ entry.direction === 'buy' ? '买' : '卖' }}</span>
          <span class="code">{{ entry.stockCode }}</span>
          <span class="name">{{ entry.stockName }}</span>
          <span class="price">{{ entry.price }}</span>
          <span v-if="entry.pnl != null" :class="entry.pnl >= 0 ? 'pnl-pos' : 'pnl-neg'">
            {{ entry.pnl >= 0 ? '+' : '' }}{{ entry.pnl.toFixed(0) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Right: Form / Detail -->
    <div class="journal-form" v-if="selectedEntry || !selectedId">
      <template v-if="!selectedEntry?.tradeType || selectedEntry.tradeType === 'entry'">
        <h3>{{ selectedId ? '编辑入场记录' : '新增入场记录' }}</h3>
        <div class="form-group">
          <label>标的</label>
          <div class="stock-picker">
            <input v-model="form.stockCode" placeholder="代码" list="stock-list" />
            <input v-model="form.stockName" placeholder="名称" />
            <datalist id="stock-list">
              <option v-for="s in stockOptions" :key="s.code" :value="s.code">{{ s.code }} {{ s.name }}</option>
            </datalist>
            <button @click="captureSignals(form.stockCode)" :disabled="!form.stockCode">抓取信号</button>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>方向</label>
            <select v-model="form.direction">
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
          </div>
          <div class="form-group">
            <label>价格</label>
            <input v-model.number="form.price" type="number" step="0.01" />
          </div>
          <div class="form-group">
            <label>数量(股)</label>
            <input v-model.number="form.volume" type="number" />
          </div>
        </div>
        <div class="form-group">
          <label>笔记</label>
          <textarea v-model="form.notes" rows="3"></textarea>
        </div>

        <!-- Signal Snapshot Display -->
        <div v-if="form.signalsSnapshot" class="signals-display">
          <h4>信号快照</h4>
          <div v-if="form.signalsSnapshot.dragon" class="signal-block">
            <strong>龙头:</strong>
            {{ form.signalsSnapshot.dragon.primaryRole }} |
            {{ form.signalsSnapshot.dragon.authorityClass }} |
            {{ form.signalsSnapshot.dragon.tradeability }}
          </div>
          <div v-if="form.signalsSnapshot.sentiment" class="signal-block">
            <strong>情绪:</strong>
            {{ form.signalsSnapshot.sentiment.emotionPhase }} ({{ form.signalsSnapshot.sentiment.breathScore }})
          </div>
          <div v-if="form.signalsSnapshot.rankTrend" class="signal-block">
            <strong>排名趋势:</strong>
            {{ form.signalsSnapshot.rankTrend.candidateTier }} |
            动量: {{ form.signalsSnapshot.rankTrend.momentumComposite }} |
            {{ form.signalsSnapshot.rankTrend.attentionStage }} |
            {{ form.signalsSnapshot.rankTrend.decision }}
          </div>
        </div>

        <button class="btn-save" @click="saveEntry">保存</button>
      </template>

      <!-- Exit Recording -->
      <template v-if="selectedEntry && selectedEntry.tradeType === 'entry' && !selectedEntry.linkedEntryId">
        <h3>记录出场</h3>
        <div class="form-group">
          <label>卖出价格</label>
          <input v-model.number="exitPrice" type="number" step="0.01" />
        </div>
        <div class="form-group">
          <label>卖出数量</label>
          <input v-model.number="exitVolume" type="number" />
        </div>
        <div class="form-group">
          <label>复盘笔记</label>
          <textarea v-model="entryNotes" rows="3"></textarea>
        </div>
        <button class="btn-save" @click="recordExit" :disabled="!exitPrice">记录出场</button>
      </template>

      <!-- Review Tags -->
      <template v-if="selectedEntry">
        <h3>复盘标签</h3>
        <div class="tags-display">
          <span v-for="tag in selectedEntry.reviewTags" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="tag-input-row">
          <input v-model="reviewTagsInput" placeholder="添加标签（逗号分隔）" />
          <button @click="addReviewTags">添加</button>
        </div>
        <div class="preset-tags">
          <span v-for="tag in PRESET_TAGS" :key="tag" class="preset-tag" @click="reviewTagsInput = tag">{{ tag }}</span>
        </div>

        <!-- Screenshots -->
        <h3>截图</h3>
        <div class="screenshots">
          <div v-for="path in selectedEntry.screenshotPaths" :key="path" class="screenshot-thumb">
            <img :src="`/api/static/${path}`" />
          </div>
        </div>
        <input type="file" accept="image/png,image/jpeg,image/webp" @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) uploadScreenshot(f) }" />

        <button class="btn-delete" @click="deleteEntry(selectedEntry.id)">删除记录</button>
      </template>
    </div>

    <!-- Stats Footer -->
    <div class="stats-panel" v-if="stats">
      <span>总盈亏: <strong :class="stats.totalPnl >= 0 ? 'pnl-pos' : 'pnl-neg'">{{ stats.totalPnl >= 0 ? '+' : '' }}{{ stats.totalPnl.toFixed(0) }}</strong></span>
      <span>胜率: <strong>{{ (stats.winRate * 100).toFixed(1) }}%</strong></span>
      <span>已平仓: <strong>{{ stats.totalExits }}</strong>笔</span>
    </div>
  </div>
</template>

<style scoped>
.trade-journal-panel { display: flex; flex-wrap: wrap; gap: 16px; padding: 16px; height: 100%; }
.journal-list { flex: 1; min-width: 300px; max-width: 400px; overflow-y: auto; }
.journal-form { flex: 2; min-width: 400px; }
.list-header { display: flex; gap: 8px; margin-bottom: 8px; }
.list-header input, .list-header select { flex: 1; padding: 4px; }
.entry-row { display: flex; gap: 8px; padding: 6px 8px; cursor: pointer; border-bottom: 1px solid #eee; }
.entry-row.selected { background: #e3f2fd; }
.entry-row:hover { background: #f5f5f5; }
.dir-buy { color: #e53935; font-weight: bold; }
.dir-sell { color: #43a047; font-weight: bold; }
.pnl-pos { color: #e53935; }
.pnl-neg { color: #43a047; }
.form-group { margin-bottom: 8px; }
.form-group label { display: block; font-size: 12px; color: #666; margin-bottom: 2px; }
.form-group input, .form-group select, .form-group textarea { width: 100%; padding: 4px 8px; border: 1px solid #ddd; border-radius: 4px; }
.form-row { display: flex; gap: 8px; }
.form-row .form-group { flex: 1; }
.stock-picker { display: flex; gap: 4px; align-items: center; }
.stock-picker input { flex: 1; }
.signals-display { background: #f5f5f5; padding: 8px; border-radius: 4px; margin: 8px 0; font-size: 12px; }
.signal-block { margin-bottom: 4px; }
.tags-display { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.tag { background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.preset-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 8px; }
.preset-tag { background: #f5f5f5; padding: 2px 8px; border-radius: 8px; font-size: 11px; cursor: pointer; }
.preset-tag:hover { background: #e0e0e0; }
.tag-input-row { display: flex; gap: 4px; margin-bottom: 8px; }
.tag-input-row input { flex: 1; }
.btn-save { background: #1565c0; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
.btn-delete { background: #c62828; color: #fff; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; margin-top: 16px; }
.stats-panel { width: 100%; display: flex; gap: 16px; padding: 8px; background: #f5f5f5; border-radius: 4px; font-size: 13px; }
.screenshots { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.screenshot-thumb img { max-width: 120px; max-height: 80px; border: 1px solid #ddd; border-radius: 4px; }
</style>
```

- [ ] **Step 2: 验证组件编译**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "TradeJournalPanel"
```
Expected: no errors

- [ ] **Step 3: 提交**

```bash
cd d:/dragon-board && git add src/components/panels/TradeJournalPanel.vue && git commit -m "$(cat <<'EOF'
feat: add TradeJournalPanel component

Deep trading journal with signal snapshot capture (dragon/sentiment/rankTrend),
exit tracking with P&L auto-calculation, review tags, screenshot upload, and
aggregated statistics display.
EOF
)"
```

---

### Task 16: 在 App.vue 注册面板入口

**Files:** Modify `src/App.vue`

App.vue 使用 `panels` ref 对象管理面板显隐（line 282-297），每个面板通过 `v-model:visible="panels.xxx"` 控制。

- [ ] **Step 1: 添加 import（在 ExportPanel import 附近，约 line 150 前）**

```typescript
import TradeJournalPanel from './components/panels/TradeJournalPanel.vue'
```

- [ ] **Step 2: 在 panels ref 中添加 journal 字段（line 291 后）**

```typescript
const panels = ref({
  // ... existing fields ...
  favorite: false,
  journal: false,  // 新增：交易日记面板
  sectorDetail: false,
  // ...
})
```

- [ ] **Step 3: 在模板中添加面板标签（在 FavoritePanel 之后）**

```html
<TradeJournalPanel v-model:visible="panels.journal" @close="panels.journal = false" />
```

- [ ] **Step 4: 在下拉菜单或导航中添加触发入口**

找到 App.vue 中的下拉菜单区域，添加交易日记触发项：

```html
<div class="dropdown-item" @click="panels.journal = true">📓 交易日记</div>
```

- [ ] **Step 5: 验证构建**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | tail -5
```
Expected: 无新增错误

- [ ] **Step 6: 提交**

```bash
cd d:/dragon-board && git add src/App.vue && git commit -m "$(cat <<'EOF'
feat: register TradeJournalPanel in App.vue

Adds journal panel accessible from the dropdown menu, following existing
v-model:visible pattern used by all other panels.
EOF
)"
```

---

## Phase 4: IndexedDB 残留清理

> Phase 4 是全局高风险的变更，涉及快照采集和持久化核心链路。每个任务独立验证后提交。

### Task 17: 审计快照写入链路

**Files:** 只读审计，不修改代码

- [ ] **Step 1: 追踪 SnapshotStore 的所有 write 调用**

```bash
grep -rn "snapshotStore\." d:/dragon-board/src/services/snapshot/runtime.ts | grep -v "// "
```

- [ ] **Step 2: 追踪 backendIngest 的所有调用**

```bash
grep -rn "backendIngest\|POST.*snapshots/ingest" d:/dragon-board/src/services/snapshot/ --include="*.ts"
```

- [ ] **Step 3: 记录发现** — 确认哪些写路径已走 MongoDB，哪些仍走 IndexedDB

根据审计结果，`runtime.ts` 仍通过 `snapshotStore.put()` 写入 IndexedDB，同时 `facade.ts` 有并行的 `backendIngest` MongoDB 写入路径。需要确认双写已稳定运行、MongoDB 路径可以独立接管后，才能移除 IndexedDB 写入。

### Task 18: 移除 runtime.ts 的 IndexedDB 写入（条件性）

**前置条件：** Task 17 确认 MongoDB 写入路径已完整覆盖

**Files:** Modify `src/services/snapshot/runtime.ts`

- [ ] **Step 1: 移除 SnapshotStore 初始化代码**

找到 `new SnapshotStore(...)` 调用（约 line 153），替换为 null：

```typescript
// Before:
this.snapshotStore = new SnapshotStore({...})

// After:
this.snapshotStore = null  // MongoDB backend handles persistence
```

- [ ] **Step 2: 条件化所有 `this.snapshotStore.put/getAll/delete` 调用**

每个调用点加 null guard：

```typescript
// Before:
await this.snapshotStore.put(record)

// After:
// Snapshot persistence handled by MongoDB backend via backendIngest
```

- [ ] **Step 3: 验证类型检查**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | grep -i "runtime.ts"
```

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add src/services/snapshot/runtime.ts && git commit -m "$(cat <<'EOF'
refactor: remove IndexedDB writes from snapshot runtime

MongoDB backend now handles all snapshot persistence via backendIngest.
EOF
)"
```

---

### Task 19: 删除 store.ts 及关联文件

**前置条件：** Task 18 完成且验证通过

**Files:**
- Delete: `src/services/snapshot/store.ts`
- Delete: `src/services/snapshot/__tests__/store.test.ts`
- Modify: `src/services/snapshot/backupSync.ts` — 移除对 store.ts 的 import

- [ ] **Step 1: 确认 store.ts 零引用（除 backupSync.ts 外）**

```bash
grep -rn "from.*['\"].*store['\"]" d:/dragon-board/src/ --include="*.ts" | grep -v "node_modules" | grep -v "__tests__"
```
Expected: 仅 `backupSync.ts` 和 `runtime.ts`（已在 Task 18 移除）

- [ ] **Step 2: 从 backupSync.ts 移除 store 依赖**

评估 backupSync.ts 是否仍需要——该文件通过 IndexedDB store 做备份同步。如果 MongoDB 后端已接管，backupSync.ts 可以整体移除。

- [ ] **Step 3: 删除文件**

```bash
rm d:/dragon-board/src/services/snapshot/store.ts
rm -f d:/dragon-board/src/services/snapshot/__tests__/store.test.ts
rm d:/dragon-board/src/services/snapshot/backupSync.ts  # 如确认无用
```

- [ ] **Step 4: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | tail -10
cd d:/dragon-board && npx vitest run 2>&1 | tail -10
```

- [ ] **Step 5: 提交**

```bash
cd d:/dragon-board && git add -A && git commit -m "$(cat <<'EOF'
refactor: delete IndexedDB snapshot store

MongoDB backend now serves as the sole persistence layer for snapshots.
EOF
)"
```

---

### Task 20: 移除 quantBoardBridge.ts 的 IndexedDB 回退

**Files:** Modify `src/services/quantBoardBridge.ts`

- [ ] **Step 1: 移除 IndexedDB 回退读取逻辑**

在 `quantBoardBridge.ts` 中找到 `indexedDB.open(...)` 相关代码块（约 lines 91-105, 360-365），移除 IndexedDB 回退路径，直接抛错或返回空：

```typescript
// Before (line 363):
throw new Error(`DragonBoard IndexedDB has no replayable ${snapshotType} frames`)

// After: MongoDB-only 读取已在 backendRead.ts 实现，此回退路径移除。
// 调用方应使用 snapshot/backendRead.ts 的公开 API。
```

- [ ] **Step 2: 确认调用方已迁移**

```bash
grep -rn "quantBoardBridge" d:/dragon-board/src/ --include="*.ts" --include="*.vue" | grep -v "node_modules" | grep -v "__tests__" | grep -v "quantBoardBridge.ts"
```

检查每个调用方是否已切换到 `backendRead.ts`。

- [ ] **Step 3: 验证**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json --pretty false 2>&1 | tail -10
```

- [ ] **Step 4: 提交**

```bash
cd d:/dragon-board && git add src/services/quantBoardBridge.ts && git commit -m "$(cat <<'EOF'
refactor: remove IndexedDB fallback from quantBoardBridge

All reads now go through MongoDB backend (backendRead.ts).
EOF
)"
```

---

## 验证矩阵

每个 Phase 完成后运行：

| Phase | 验证命令 | 通过标准 |
|-------|---------|---------|
| 1 | `npx vue-tsc --noEmit -p tsconfig.app.json` | 无新增错误 |
| 1 | `npx vitest run` | 全部通过 |
| 2 | `grep -rn "DragonAnalyzer" src/ --include="*.ts" --include="*.vue" \| grep -v "DragonBreathAnalyzer"` | 零输出 |
| 2 | `npx vue-tsc --noEmit -p tsconfig.app.json` | 无错误 |
| 2 | `npx vitest run` | 全部通过 |
| 3 | `python -c "from backend.api.journal_routes import router"` | 无错误 |
| 3 | `curl -X POST /api/journal/entries` (MongoDB 可用时) | 返回 200 |
| 3 | `npx vue-tsc --noEmit -p tsconfig.app.json` | 无 TradeJournalPanel 相关错误 |
| 4 | `grep -rn "indexedDB\|IndexedDB" src/services/snapshot/ --include="*.ts"` | 零输出 |
| 4 | `npx vue-tsc --noEmit -p tsconfig.app.json` | 无错误 |

---

## 不在范围内的内容

- 不修改 proxy-server（独立进程，无冗余）
- 不修改 python-bridge
- 不新增 SQLite trade_journal 兼容路径
- 不修改现有回测/优化/主题模块
- 不处理 MongoDB 不可用时的降级方案（trade_journal 依赖 MongoDB）
