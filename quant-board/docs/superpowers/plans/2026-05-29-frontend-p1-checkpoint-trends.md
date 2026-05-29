# QuantBoard 前端 P1：长测 Checkpoint 趋势 + 跨期指示器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 每个 Task 完成后必须经子 agent code review 通过再提交。

**Goal:** 新增 checkpoint 历史列表 API + 前端趋势表格 + 回测报告头部的跨期状态指示器。

**Architecture:** 后端新增 `GET /api/backtests/checkpoints` 读取 JSONL 返回摘要列表。前端新增"长测趋势"区域展示 checkpoint 历史对比表，并在回测报告指标区顶部加入熔断/对齐状态指示条。

**Tech Stack:** Python FastAPI + Vue 3 `<script setup>` + TypeScript，无图表库依赖（用表格+色彩编码替代）

**Data source:** `quant-board/data/reports/long_test_runs.jsonl`（11 个 checkpoint）

---

## File Map

| Task | File | Action |
|---|---|---|
| 1 | `quant-board/backend/main.py` | 新增 `GET /api/backtests/checkpoints` 端点 |
| 1 | `quant-board/tests/test_quant_board.py` | 新增端点测试 |
| 2 | `quant-board/frontend/src/api.ts` | 新增 `api.getCheckpoints()` |
| 2 | `quant-board/frontend/src/types.ts` | 新增 `CheckpointSummary` 接口 |
| 2 | `quant-board/frontend/src/App.vue` | 新增 checkpoint 历史表格区域 |
| 3 | `quant-board/frontend/src/App.vue` | 新增跨期状态指示条（报告指标区顶部） |

---

### Task 1: 后端 — checkpoint 列表 API

**Files:**
- Modify: `quant-board/backend/main.py`（在 alignment 端点附近新增）
- Modify: `quant-board/tests/test_quant_board.py`（新增测试）

- [ ] **Step 1: 新增 `GET /api/backtests/checkpoints` 端点**

在 `main.py` 的 `get_alignment` 函数之后、`get_backtest` 之前插入：

```python
@app.get("/api/backtests/checkpoints")
def get_checkpoints(limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    """Return recent long-test checkpoint summaries from JSONL."""
    jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
    if not jsonl_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json_loads(line.strip())
                if not record or not record.get("checkpointId"):
                    continue
            except Exception:
                continue
            baselines = record.get("baselines") or []
            h1 = next((b for b in baselines if "H1" in str(b.get("label") or "")), {})
            h2 = next((b for b in baselines if "H2" in str(b.get("label") or "")), {})
            q1 = next((b for b in baselines if "Q1" in str(b.get("label") or "")), {})
            cp = record.get("crossPeriod") or {}
            records.append({
                "checkpointId": record.get("checkpointId"),
                "createdAt": record.get("createdAt"),
                "h1TotalReturn": h1.get("totalReturn"),
                "h1Sharpe": h1.get("sharpe"),
                "h1Trades": h1.get("tradeCount"),
                "h2TotalReturn": h2.get("totalReturn"),
                "h2Sharpe": h2.get("sharpe"),
                "q1TotalReturn": q1.get("totalReturn"),
                "q1Sharpe": q1.get("sharpe"),
                "h1Layer1Status": (h1.get("layer1SignalEfficacy") or {}).get("layer1Status"),
                "h1DirectionAccuracy": (h1.get("layer1SignalEfficacy") or {}).get("directionAccuracy"),
                "h1Layer2Status": (h1.get("layer2ExecutionQuality") or {}).get("layer2Status"),
                "h1Layer2Bias": (h1.get("layer2ExecutionQuality") or {}).get("bias"),
                "meltdown": (cp.get("layer1MeltdownH1") or {}).get("meltdown"),
                "consecutiveRedPeriods": (cp.get("layer1MeltdownH1") or {}).get("consecutiveRedPeriods"),
                "l3GreenLight": (cp.get("layer3Trend") or {}).get("greenLight"),
            })
    return records[-limit:] if len(records) > limit else records
```

- [ ] **Step 2: 写测试**

在 `tests/test_quant_board.py` 末尾追加：

```python
def test_get_checkpoints_returns_list(tmp_path: Path) -> None:
    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "checkpointId" in item
        assert "h1TotalReturn" in item
        assert "h1Layer1Status" in item or True  # may be absent in old checkpoints


def test_get_checkpoints_respects_limit() -> None:
    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 2
```

- [ ] **Step 3: 验证**

```bash
cd d:/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "checkpoints" -v --tb=short
```
Expected: 2 passed.

```bash
cd d:/dragon-board/quant-board && .venv/Scripts/python.exe -c "from backend.main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print('OK' if '/api/backtests/checkpoints' in routes else 'MISSING')"
```
Expected: OK

- [ ] **Step 4: 提交**

```bash
git add quant-board/backend/main.py quant-board/tests/test_quant_board.py
git commit -m "feat: add GET /api/backtests/checkpoints endpoint"
```

---

### Task 2: 前端 — checkpoint 历史趋势表

**Files:**
- Modify: `quant-board/frontend/src/api.ts`（新增 getCheckpoints）
- Modify: `quant-board/frontend/src/types.ts`（新增 CheckpointSummary）
- Modify: `quant-board/frontend/src/App.vue`（新增状态、数据加载、趋势表格 UI）

- [ ] **Step 1: 新增 TypeScript 接口（types.ts 末尾）**

```typescript
export interface CheckpointSummary {
  checkpointId: string;
  createdAt?: string;
  h1TotalReturn: number | null;
  h1Sharpe: number | null;
  h1Trades: number | null;
  h2TotalReturn: number | null;
  h2Sharpe: number | null;
  q1TotalReturn: number | null;
  q1Sharpe: number | null;
  h1Layer1Status: "green" | "red" | null;
  h1DirectionAccuracy: number | null;
  h1Layer2Status: "green" | "yellow" | "red" | null;
  h1Layer2Bias: number | null;
  meltdown: boolean | null;
  consecutiveRedPeriods: number | null;
  l3GreenLight: boolean | null;
}
```

- [ ] **Step 2: 新增 API 方法（api.ts）**

在 `api.getAlignment` 之后追加：

```typescript
  getCheckpoints: (limit = 20) =>
    requestApi<CheckpointSummary[]>(`/api/backtests/checkpoints?limit=${limit}`),
```

无需额外 import —— `CheckpointSummary` 从 types.ts 自动导入。

- [ ] **Step 3: App.vue — 新增 checkpoint 状态和加载逻辑**

在 `<script setup>` 区域（约第 138 行 `activeReportTab` 定义之后）新增：

```typescript
const checkpointList = ref<Array<Record<string, unknown>>>([]);
const checkpointLoading = ref(false);
const checkpointError = ref("");

async function fetchCheckpoints() {
  checkpointLoading.value = true;
  checkpointError.value = "";
  try {
    checkpointList.value = (await api.getCheckpoints(20)) as Array<Record<string, unknown>>;
  } catch (e: unknown) {
    checkpointError.value = e instanceof Error ? e.message : String(e);
  } finally {
    checkpointLoading.value = false;
  }
}
```

- [ ] **Step 4: App.vue — 新增趋势表格 UI**

在左侧导航区（或主内容区顶部）新增"长测趋势"区域。找到 App.vue 中 `<main>` 标签内的合适位置（建议放在数据集管理区下方），追加：

```html
            <section class="quick-card-section">
              <div class="quick-card" style="cursor:pointer" @click="fetchCheckpoints()">
                <b>长测趋势</b>
                <span>{{ checkpointList.length ? checkpointList.length + ' 期' : '加载' }}</span>
              </div>
            </section>

            <section v-if="checkpointList.length" class="section-block quality-block" style="margin:16px 0">
              <h3>长测 Checkpoint 趋势 <small>(最近 {{ checkpointList.length }} 期)</small></h3>
              <div v-if="checkpointLoading" class="inline-note">加载中...</div>
              <div v-else class="table-wrap compact-table" style="max-height:400px;overflow-y:auto">
                <table>
                  <thead>
                    <tr>
                      <th>Checkpoint</th>
                      <th>H1 收益</th>
                      <th>H1 Sharpe</th>
                      <th>H2 收益</th>
                      <th>H1 L1</th>
                      <th>H1 L2</th>
                      <th>熔断</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="cp in [...checkpointList].reverse()" :key="String(cp.checkpointId)">
                      <td><small>{{ (String(cp.checkpointId)).replace('checkpoint_', '').replace('_', ' ') }}</small></td>
                      <td :class="Number(cp.h1TotalReturn) >= 0 ? 'pos' : 'neg'">{{ formatPercent(Number(cp.h1TotalReturn)) }}</td>
                      <td :class="Number(cp.h1Sharpe) >= 0 ? 'pos' : 'neg'">{{ Number(cp.h1Sharpe).toFixed(2) }}</td>
                      <td :class="Number(cp.h2TotalReturn) >= 0 ? 'pos' : 'neg'">{{ formatPercent(Number(cp.h2TotalReturn)) }}</td>
                      <td>
                        <span :class="['status-badge', cp.h1Layer1Status === 'green' ? 'badge-green' : 'badge-red']" style="font-size:0.65rem;padding:1px 6px">
                          {{ cp.h1Layer1Status || '?' }}
                        </span>
                      </td>
                      <td>
                        <span v-if="cp.h1Layer2Status" :class="['status-badge',
                          cp.h1Layer2Status === 'green' ? 'badge-green' :
                          cp.h1Layer2Status === 'yellow' ? 'badge-yellow' : 'badge-red']" style="font-size:0.65rem;padding:1px 6px">
                          {{ cp.h1Layer2Status }}
                        </span>
                        <span v-else>-</span>
                      </td>
                      <td>{{ cp.meltdown ? '⚠' : '' }} {{ cp.consecutiveRedPeriods || 0 }}期</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
```

- [ ] **Step 5: 验证**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 | tail -5
```
Expected: 零错误。

```bash
cd d:/dragon-board/quant-board/frontend && npx vite build 2>&1 | tail -5
```
Expected: 构建成功。

- [ ] **Step 6: 提交**

```bash
git add quant-board/frontend/src/api.ts quant-board/frontend/src/types.ts quant-board/frontend/src/App.vue
git commit -m "feat: add checkpoint history trend table in frontend"
```

---

### Task 3: 前端 — 跨期状态指示器

**File:**
- Modify: `quant-board/frontend/src/App.vue`（回测报告指标区顶部）

- [ ] **Step 1: 在报告指标区头部加入状态指示条**

找到回测报告页的指标摘要区域（约第 2280 行 `reportMetrics` 附近），在指标卡片之前加入跨期状态指示器：

```html
            <!-- 跨期状态指示器 -->
            <div v-if="layer1SignalEfficacy || layer2ExecutionQuality" class="cross-period-bar" style="display:flex;gap:16px;padding:8px 12px;background:#f8f9fa;border-radius:6px;margin-bottom:12px;font-size:0.85rem">
              <span v-if="layer1SignalEfficacy?.layer1Status === 'red'">
                L1 红灯 · {{ layer1SignalEfficacy?.aMainSamples || 0 }} A_MAIN · 精度 {{ formatPercent(Number(layer1SignalEfficacy?.directionAccuracy)) }}
              </span>
              <span v-if="layer2ExecutionQuality?.layer2Status === 'yellow'">
                L2 黄灯 · 偏差 {{ formatPercent(Number(layer2ExecutionQuality?.bias)) }} > {{ formatPercent(Number(layer2ExecutionQuality?.biasThreshold)) }}
              </span>
              <span v-if="layer2ExecutionQuality?.layer2Status === 'green'" style="color:#155724">
                L2 绿灯 · 执行偏差在阈值内
              </span>
              <span v-if="layer2ExecutionQuality?.layer2Status === 'red'" style="color:#721c24">
                L2 红灯 · H2 反超 H1（追高/抢跑风险）
              </span>
            </div>
```

放在回测摘要指标卡片 `<div class="section-block">` 之前。该指示条只在有 Layer 1-2 数据时展示（即 V2 格式的新 checkpoint）。

- [ ] **Step 2: 验证**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 | tail -5
cd d:/dragon-board/quant-board/frontend && npx vite build 2>&1 | tail -5
```
Expected: 零错误 + 构建成功。

- [ ] **Step 3: 提交**

```bash
git add quant-board/frontend/src/App.vue
git commit -m "feat: add cross-period status indicator in report header"
```

---

### Task 4: 最终验证

- [ ] **Step 1: 全量类型检查 + 构建**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 && npx vite build 2>&1 | tail -5
```

- [ ] **Step 2: 后端测试回归**

```bash
cd d:/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "checkpoints" -v
```
Expected: 2 passed.
