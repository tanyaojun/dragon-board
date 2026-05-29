# QuantBoard 前端 P0：V2 四层框架面板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 每个 Task 完成后必须经子 agent code review 通过再提交。

**Goal:** 将后端已产出的 V2 Layer 1-3 数据在 QuantBoard 前端展示。

**Architecture:** 三步增量——先补 TypeScript 类型定义，再在现有质量 Tab 中新增 Layer 1-2 诊断卡片，最后新增 Layer 3 对齐面板。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript, Vite, Pinia 无（直接 computed）

**Context:** 后端 `dataQuality.layer1SignalEfficacy`、`dataQuality.layer2ExecutionQuality`、`GET /api/backtests/alignment` 均已在 Phase A-C 产出数据。前端 `dataQuality` computed 已自动从 API 响应读取这些字段，但 types.ts 无类型定义、App.vue 无渲染。

---

## File Map

| Task | File | Action |
|---|---|---|
| 1 | `quant-board/frontend/src/types.ts:360` | 新增 V2 Layer 1-3 接口定义 |
| 2 | `quant-board/frontend/src/App.vue:2427-2464` | 在质量 Tab 中新增 Layer 1-2 诊断卡片 |
| 3 | `quant-board/frontend/src/App.vue:2427` | 在报告页新增 Layer 3 对齐 Tab |

---

### Task 1: TypeScript 类型定义

**Files:**
- Modify: `quant-board/frontend/src/types.ts:360`

- [ ] **Step 1: 新增 V2 Layer 1-3 接口**

在 `types.ts` 末尾追加以下接口：

```typescript
// ── V2 四层决策框架 ─────────────────────────────

export interface Layer1SignalEfficacy {
  tierRatio: number | null;
  aPlusBTierCount: number;
  tierCounts: Record<string, number>;
  totalSignals: number;
  directionAccuracy: number | null;
  aMainSamples: number;
  nNeutralSamples: number;
  tierDiscrimination: number | null;
  binomialPValue: number | null;
  thresholds: {
    directionAccuracyMin: number;
    binomialPMax: number;
    tierDiscriminationMin: number;
    tierRatioMin: number;
    tierRatioMax: number;
  };
  layer1Status: "green" | "red";
}

export interface Layer2ExecutionQuality {
  bias: number;
  biasThreshold: number;
  biasOk: boolean;
  directionRatio: number;
  directionOk: boolean;
  tradeCountDiff: number;
  tradeCountDiffOk: boolean;
  drawdownDiff: number;
  drawdownDiffOk: boolean;
  layer2Status: "green" | "yellow" | "red";
}

export interface Layer3Alignment {
  checkpointId?: string;
  journalExecutedCount: number;
  signalCodeCount: number;
  intersectionCount: number;
  signalOnlyCount?: number;
  journalOnlyCount?: number;
  intersectionCodes: string[];
  intersectionPnl: number;
  intersectionPnlPct: number;
  sufficientSample: boolean;
  alignmentStatus: "sufficient" | "insufficient_data" | "unavailable";
}

export interface CrossPeriodState {
  layer1MeltdownH1: {
    meltdown: boolean;
    consecutiveRedPeriods: number;
    statuses: string[];
    recommendation: string | null;
  };
  layer3Trend: {
    greenLight: boolean;
    recentStatuses: string[];
    recommendation: string | null;
  };
}

export interface PriceQualityDiagnostics {
  role: "report_only";
  autoApplyDefaults: boolean;
  computedBeforeResearchFilters: boolean;
  crossMarketZeroPriceRows: {
    rowCount: number;
    snapshotCount: number;
    examples: Array<{ snapshotId: string; code: string; name: string }>;
    aShareUniverseAvailable: boolean;
    aShareUniverseCodeCount: number;
    skippedAllZeroPriceFrames: number;
  };
  allZeroPriceFrames: {
    frameCount: number;
    rowCount: number;
    snapshotIds: string[];
  };
  partialAshareZeroPriceRows: {
    rowCount: number;
    snapshotCount: number;
    examples: Array<{ snapshotId: string; code: string; name: string; price: number }>;
  };
}

export interface AlignmentApiResponse extends Layer3Alignment {
  checkpointId: string;
  signalOnlyCodes: string[];
  journalOnlyCodes: string[];
}
```

- [ ] **Step 2: 验证类型检查**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 | tail -5
```
Expected: 无新增错误（--strict 模式下未使用的类型不会报错）。

- [ ] **Step 3: 提交**

```bash
git add quant-board/frontend/src/types.ts
git commit -m "feat: add V2 Layer 1-3 TypeScript interfaces"
```

---

### Task 2: Layer 1-2 诊断卡片（质量 Tab）

**Files:**
- Modify: `quant-board/frontend/src/App.vue:2427-2464`（在"样本覆盖"区域之后新增）

- [ ] **Step 1: 新增 Layer 1-2 computed 属性**

在 `dataQuality` computed（现行第 524 行）之后，新增：

```typescript
const layer1SignalEfficacy = computed(() => {
  const raw = dataQuality.value.layer1SignalEfficacy;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
});

const layer2ExecutionQuality = computed(() => {
  const raw = dataQuality.value.layer2ExecutionQuality;
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
});

const priceQualityDiagnostics = computed(() => {
  const rd = dataQuality.value.reportOnlyDiagnostics;
  return rd && typeof rd === "object" ? ((rd as Record<string, unknown>).priceQuality as Record<string, unknown> | null) : null;
});
```

- [ ] **Step 2: 在质量 Tab 中新增 Layer 1 卡片**

找到质量 Tab 内 `<!-- 样本覆盖 -->` 区块结束位置（`</div>` after 第 2464 行 `</table>`），在其后追加：

```html
            <!-- V2 Layer 1: 信号有效性 -->
            <div v-if="layer1SignalEfficacy" class="section-block quality-block">
              <h3>V2 Layer 1 — 信号有效性
                <span :class="['status-badge', layer1SignalEfficacy.layer1Status === 'green' ? 'badge-green' : 'badge-red']">
                  {{ layer1SignalEfficacy.layer1Status }}
                </span>
              </h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>分层比例 (A+B)</span><b>{{ formatPercent(Number(layer1SignalEfficacy.tierRatio)) }} <small>(2%-15%)</small></b></div>
                <div><span>方向精度</span><b>{{ formatPercent(Number(layer1SignalEfficacy.directionAccuracy)) }} <small>(>55%)</small></b></div>
                <div><span>层级区分度</span><b>{{ formatPercent(Number(layer1SignalEfficacy.tierDiscrimination)) }} <small>(>5pp)</small></b></div>
                <div><span>二项检验 p 值</span><b>{{ Number(layer1SignalEfficacy.binomialPValue).toFixed(4) }} <small>(<0.10)</small></b></div>
                <div><span>A_MAIN 样本</span><b>{{ layer1SignalEfficacy.aMainSamples }}</b></div>
                <div><span>总信号数</span><b>{{ layer1SignalEfficacy.totalSignals }}</b></div>
              </div>
              <div class="inline-note">
                <b>信号层级分布：</b>
                <span v-for="(cnt, tier) in asRecord(layer1SignalEfficacy.tierCounts)" :key="String(tier)" style="margin-right:12px">
                  {{ tier }}: {{ cnt }}
                </span>
              </div>
            </div>

            <!-- V2 Layer 2: 执行质量 -->
            <div v-if="layer2ExecutionQuality" class="section-block quality-block">
              <h3>V2 Layer 2 — 执行质量 (H1 vs H2)
                <span :class="['status-badge',
                  layer2ExecutionQuality.layer2Status === 'green' ? 'badge-green' :
                  layer2ExecutionQuality.layer2Status === 'yellow' ? 'badge-yellow' : 'badge-red']">
                  {{ layer2ExecutionQuality.layer2Status }}
                </span>
              </h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>偏差 (H1-H2)</span><b>{{ formatPercent(Number(layer2ExecutionQuality.bias)) }} <small>(&lt; {{ formatPercent(Number(layer2ExecutionQuality.biasThreshold)) }})</small></b></div>
                <div><span>方向占比 (近4期)</span><b>{{ formatPercent(Number(layer2ExecutionQuality.directionRatio)) }} <small>(≥75%)</small></b></div>
                <div><span>交易数差异</span><b>{{ layer2ExecutionQuality.tradeCountDiff }}</b></div>
                <div><span>回撤差异</span><b>{{ formatPercent(Number(layer2ExecutionQuality.drawdownDiff)) }} <small>(<5pp)</small></b></div>
                <div><span>biasOk</span><b>{{ layer2ExecutionQuality.biasOk ? '✓' : '✗' }}</b></div>
                <div><span>drawdownOk</span><b>{{ layer2ExecutionQuality.drawdownDiffOk ? '✓' : '✗' }}</b></div>
              </div>
            </div>

            <!-- 价格质量诊断 -->
            <div v-if="priceQualityDiagnostics" class="section-block quality-block">
              <h3>价格质量诊断 (report-only)</h3>
              <div class="diagnostic-grid compact-diagnostic">
                <div><span>跨市场零行情</span><b>{{ priceQualityDiagnostics.crossMarketZeroPriceRows?.rowCount ?? 0 }} 行 / {{ priceQualityDiagnostics.crossMarketZeroPriceRows?.snapshotCount ?? 0 }} 快照</b></div>
                <div><span>全零异常帧</span><b>{{ priceQualityDiagnostics.allZeroPriceFrames?.frameCount ?? 0 }} 帧</b></div>
                <div><span>A股局部零价</span><b>{{ priceQualityDiagnostics.partialAshareZeroPriceRows?.rowCount ?? 0 }} 行 / {{ priceQualityDiagnostics.partialAshareZeroPriceRows?.snapshotCount ?? 0 }} 快照</b></div>
              </div>
              <div class="inline-note">诊断不参与过滤，不改变收益和质量等级。</div>
            </div>
```

- [ ] **Step 3: 新增 CSS 状态标签样式**

在 `<style scoped>` 区域末尾追加：

```css
.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  margin-left: 8px;
  vertical-align: middle;
}
.badge-green  { background: #d4edda; color: #155724; }
.badge-yellow { background: #fff3cd; color: #856404; }
.badge-red    { background: #f8d7da; color: #721c24; }
```

- [ ] **Step 4: 验证类型检查通过**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 | tail -5
```
Expected: 无新增类型错误。

- [ ] **Step 5: 提交**

```bash
git add quant-board/frontend/src/App.vue
git commit -m "feat: add V2 Layer 1-2 diagnostic cards in quality tab"
```

---

### Task 3: Layer 3 实盘对齐面板

**Files:**
- Modify: `quant-board/backend/main.py:1408-1440`（对齐端点支持 run_ids 参数）
- Modify: `quant-board/frontend/src/App.vue`（报告页 tab 栏 + 新增 tab 面板内容）
- Modify: `quant-board/frontend/src/types.ts:274`（扩展 BacktestReportTabKey）

- [ ] **Step 0: 后端 — 对齐端点支持 run_ids 参数**

找到 `main.py:1410` 的 `get_alignment` 函数，在参数中增加 `run_ids`：

```python
@app.get("/api/backtests/alignment")
def get_alignment(
    checkpoint_id: str | None = Query(None),
    run_ids: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict[str, Any]:
    """Cross-reference trade_journal execution records with backtest signals."""
    repo = create_repository(None)

    # Support both: checkpoint_id (reads JSONL) or run_ids (comma-separated)
    if run_ids:
        checkpoint_run_ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
    elif checkpoint_id:
        # Read checkpoint baselines from JSONL to extract run_ids
        jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
        checkpoint_run_ids: list[str] = []
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json_loads(line.strip())
                        if record and record.get("checkpointId") == checkpoint_id:
                            for baseline in (record.get("baselines") or []):
                                rid = baseline.get("runId") or baseline.get("id")
                                if rid:
                                    checkpoint_run_ids.append(rid)
                            break
                    except Exception:
                        continue
    else:
        checkpoint_run_ids = []

    alignment = compute_alignment(
        repo=repo,
        run_ids=checkpoint_run_ids,
        start_date=start_date,
        end_date=end_date,
    )
    return {"checkpointId": checkpoint_id, **alignment}
```

原有的 JSONL 读取逻辑不变，仅在外层包裹 `if run_ids` / `elif checkpoint_id` 分支。

- [ ] **Step 0.1: 验证端点**

```bash
cd d:/dragon-board/quant-board && .venv/Scripts/python.exe -c "from backend.main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print('OK' if '/api/backtests/alignment' in routes else 'MISSING')"
```
Expected: OK

```bash
cd d:/dragon-board/quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "alignment" -v 2>&1 | tail -5
```
Expected: 测试通过。

- [ ] **Step 0.2: 提交**

```bash
git add quant-board/backend/main.py
git commit -m "feat: support run_ids parameter in alignment endpoint"
```

- [ ] **Step 1: 扩展 BacktestReportTabKey 类型**

在 `types.ts` 的 `BacktestReportTabKey` 类型中追加 `"alignment"`：

找到第 274-279 行的类型定义：
```typescript
export type BacktestReportTabKey =
  | "trades"
  | "signals"
  | "quality"
  | "controls"
  | "matching"
  | "config";
```

改为：
```typescript
export type BacktestReportTabKey =
  | "trades"
  | "signals"
  | "quality"
  | "alignment"
  | "controls"
  | "matching"
  | "config";
```

- [ ] **Step 2: 在 api.ts 中新增对齐 API 方法**

在 `api.ts` 的 `api` 对象中（第 68 行起），在现有方法之后追加：

```typescript
  getAlignment: (runIds: string) =>
    requestApi<Record<string, unknown>>(`/api/backtests/alignment?run_ids=${encodeURIComponent(runIds)}`),
```

- [ ] **Step 2.1: 在 App.vue 中新增 Layer 3 状态和逻辑**

现行第 2 行 `import { computed, onMounted, reactive, ref, watch } from "vue"` 已包含 `watch`，无需修改。

在 `dataQuality` computed 定义之后（约第 524 行后），新增：

```typescript
const alignmentResult = ref<Record<string, unknown> | null>(null);
const alignmentLoading = ref(false);
const alignmentError = ref("");

async function fetchAlignment(runId: string) {
  if (!runId) return;
  alignmentLoading.value = true;
  alignmentError.value = "";
  try {
    alignmentResult.value = await api.getAlignment(runId);
  } catch (e: unknown) {
    alignmentError.value = e instanceof Error ? e.message : String(e);
    alignmentResult.value = null;
  } finally {
    alignmentLoading.value = false;
  }
}

// 切换到 alignment tab 时自动拉取
watch(activeReportTab, (tab) => {
  if (tab === "alignment" && activeRunId.value && !alignmentResult.value) {
    fetchAlignment(activeRunId.value);
  }
});
```

- [ ] **Step 3: 在报告页 tab 栏中新增 "对齐" 标签**

找到报告页 tab 栏（搜索 `activeReportTab === 'quality'` 附近），在 "质量" tab 之后追加：

```html
              <button
                :class="{ active: activeReportTab === 'alignment' }"
                @click="activeReportTab = 'alignment'"
              >对齐</button>
```

- [ ] **Step 4: 新增对齐 Tab 面板内容**

在质量 Tab 面板的 `</div>` 之后、`activeReportTab === 'controls'` 之前，追加：

```html
          <div v-if="activeReportTab === 'alignment'" class="report-tab-panel">
            <div class="section-block quality-block">
              <h3>V2 Layer 3 — 实盘对齐</h3>
              <div v-if="alignmentLoading" class="inline-note">加载中...</div>
              <div v-else-if="alignmentError" class="inline-note" style="color:#721c24">{{ alignmentError }}</div>
              <div v-else-if="!alignmentResult" class="inline-note">
                点击"对齐"标签自动加载。需要 MongoDB trade_journal 中有已执行的候选记录。
              </div>
              <template v-else>
                <div class="diagnostic-grid compact-diagnostic">
                  <div><span>已执行交易</span><b>{{ alignmentResult.journalExecutedCount ?? 0 }}</b></div>
                  <div><span>回测信号标的</span><b>{{ alignmentResult.signalCodeCount ?? 0 }}</b></div>
                  <div><span>交集标的</span><b>{{ alignmentResult.intersectionCount ?? 0 }}</b></div>
                  <div><span>交集 P&L</span><b>{{ Number(alignmentResult.intersectionPnl || 0).toFixed(2) }}</b></div>
                  <div><span>交集 P&L %</span><b>{{ formatPercent(Number(alignmentResult.intersectionPnlPct)) }}</b></div>
                  <div><span>对齐状态</span><b>{{ alignmentResult.alignmentStatus }}</b></div>
                </div>
                <div v-if="alignmentResult.sufficientSample" class="inline-note" style="color:#155724">
                  ✓ 样本充足（≥10 笔），对齐报告有效
                </div>
                <div v-else class="inline-note">
                  ⚠ 样本不足（<10 笔），暂不判定对齐质量
                </div>
                <div v-if="asRecord(alignmentResult).intersectionCodes?.length" style="margin-top:12px">
                  <b>交集标的：</b>{{ (asRecord(alignmentResult).intersectionCodes as string[])?.join(', ') }}
                </div>
              </template>
            </div>
          </div>
```

- [ ] **Step 5: 验证类型和构建**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1 | tail -5
```
Expected: 无新增类型错误。

```bash
cd d:/dragon-board/quant-board/frontend && npx vite build 2>&1 | tail -5
```
Expected: 构建成功。

- [ ] **Step 6: 提交**

```bash
git add quant-board/frontend/src/api.ts quant-board/frontend/src/App.vue quant-board/frontend/src/types.ts
git commit -m "feat: add V2 Layer 3 alignment tab in backtest report"
```

---

### Task 4: 类型检查与构建验证

**Files:**
- 无修改，仅验证

- [ ] **Step 1: 完整类型检查**

```bash
cd d:/dragon-board/quant-board/frontend && npx vue-tsc --noEmit 2>&1
```
Expected: 无新增 ERROR（允许已有 warning/deprecation）。

- [ ] **Step 2: 生产构建**

```bash
cd d:/dragon-board/quant-board/frontend && npx vite build 2>&1 | tail -10
```
Expected: 构建成功，无错误。

---
