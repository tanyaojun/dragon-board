# 交易日志模块 + 代码库清理 设计文档

**日期**: 2026-05-13
**状态**: 已确认
**涉及子系统**: QuantBoard 后端 (MongoDB), Dragon Board 前端 (Vue 3)

---

## 一、交易日志模块 (Trade Journal)

### 1.1 架构

新增 MongoDB collection `trade_journal`，走 `MongoResearchRepository` 双仓库模式（仅 MongoDB 路径，不新增 SQLite 兼容）。

```
前端 TradeJournalPanel.vue
  ↓ HTTP
/api/journal/* 路由 (journal_routes.py)
  ↓
MongoResearchRepository._trade_journal_xxx()
  ↓
MongoDB collection: trade_journal
```

截图通过 `POST /api/journal/entries/{id}/screenshot` 上传为 multipart form，后端存到 `quant-board/data/journal_screenshots/{entry_id}/` 目录，路径写入文档 `screenshotPaths` 字段。

### 1.2 MongoDB 文档结构

Collection: `trade_journal`

```json
{
  "id": "tj_a1b2c3d4e5f6g7h8",
  "stockCode": "000001",
  "stockName": "平安银行",
  "direction": "buy",
  "tradeType": "entry",
  "price": 12.35,
  "volume": 1000,
  "tradeTime": "2026-05-13T10:30:00+08:00",
  "linkedEntryId": null,
  "signalsSnapshot": {
    "dragon": {
      "dragonLevel": "TRUE_LEADER",
      "authorityClass": "MARKET_CORE",
      "tradeability": "ACTIONABLE"
    },
    "sentiment": {
      "emotionPhase": "高潮",
      "breathScore": 78
    },
    "rankTrend": {
      "candidateTier": "A_MAIN",
      "momentumComposite": 65,
      "attentionStage": "expansion",
      "decision": "buy"
    }
  },
  "notes": "",
  "screenshotPaths": [],
  "reviewTags": [],
  "pnl": null,
  "pnlPct": null,
  "createdAt": "2026-05-13T10:30:00+08:00",
  "updatedAt": "2026-05-13T10:30:00+08:00"
}
```

### 1.3 Indexes

```
trade_journal:
  - {id: 1} UNIQUE
  - {stockCode: 1, tradeTime: -1}
  - {tradeType: 1, createdAt: -1}
  - {linkedEntryId: 1}
```

### 1.4 API 路由

所有路由挂载在 `/api/journal` 前缀下，注册到 `main.py`。

| Method | Path | 说明 |
|--------|------|------|
| POST | `/entries` | 创建交易记录 |
| GET | `/entries` | 列表，支持 `stockCode`、`tradeType`、`direction`、`from`/`to` 时间、`reviewTags` 过滤，分页 `offset`/`limit` |
| GET | `/entries/{id}` | 单条详情 |
| PUT | `/entries/{id}` | 更新（出场填价/量、笔记、复盘标签） |
| DELETE | `/entries/{id}` | 删除记录及关联截图 |
| POST | `/entries/{id}/screenshot` | 上传截图（multipart, field: `file`） |
| GET | `/stats` | 聚合统计：复盘标签频次、按 emotionPhase/decision 的胜率、按 stockCode 的累计盈亏 |

### 1.5 前端面板 TradeJournalPanel.vue

- 左侧：交易记录列表（可按标的/方向/时间筛选）
- 右侧：录入/编辑表单
  - 标的选择器（支持搜索当前 DataLayer 热榜或手动输入代码）
  - 方向（买/卖）、交易类型（入场/出场）、价格、数量
  - "抓取当前信号"按钮 — 从 `dataLayer` 获取三个信号快照并展示
  - 笔记文本框
  - 截图拖拽上传区
  - 复盘标签多选（预设 + 自定义）
- 入场/出场联动：出场记录选择 `linkedEntryId` 后自动计算盈亏
- 统计面板（底部或弹窗）：标签分布饼图、按情绪阶段的胜率柱状图

### 1.6 错误处理

- 信号快照字段可空（非交易时段或 DataLayer 无数据时）
- 截图上传限制：单文件 ≤ 10MB，仅允许 png/jpg/webp
- 删除入场记录时级联删除关联的出场记录和截图目录

---

## 二、代码库清理

> **审计方法**：每个候选文件均通过 `grep` 精确验证 incoming imports（排除自身测试和索引文件）。以下引用数据均为实测结果。

### 2.1 A 类 — 可直接删除（3 个文件）

经 grep 验证零生产引用：

| # | 文件 | 证据 |
|---|------|------|
| 1 | `src/services/dragon/DragonAnalyzerCompat.ts` | 全项目 0 次 import |
| 2 | `src/services/dragon/ContextBuilder.ts` | 仅被自身测试 `__tests__/ContextBuilder.test.ts` 引用，生产路径已离线 |
| 3 | `src/devtools/diagnostics/moneyFlowDiagnostics.ts` | 仅被自身测试引用，诊断工具不入业务链 |

### 2.2 B 类 — DragonAnalyzer 迁移后删除（1 个文件 + 连锁）

`src/services/DragonAnalyzer.ts` (22KB) 源码自注"已被 DragonReviewService 替代"，但**当前仍有 5 个活跃消费者**：

| 消费者 | 行号 | 引用方式 |
|--------|------|---------|
| `src/App.vue` | 223 | `import { dragonAnalyzer } from './services/DragonAnalyzer'` |
| `src/main.ts` | 41 | `import { dragonAnalyzer } from './services/DragonAnalyzer'` |
| `src/components/panels/ExportPanel.vue` | 104 | `import { dragonAnalyzer } from '@/services/DragonAnalyzer'` |
| `src/stores/stock.ts` | 10 | `import { dragonAnalyzer } from '@/services/DragonAnalyzer'` |
| `src/services/exportService.ts` | 6 | `import { dragonAnalyzer } from './DragonAnalyzer'` |

**迁移策略**：将 5 个消费者的 `dragonAnalyzer` 引用替换为 `DragonReviewService` 等效接口，验证无功能退化后删除 `DragonAnalyzer.ts` 及其测试文件。

### 2.3 C 类 — IndexedDB 残留清理

| 文件 | 现状 | 清理策略 |
|------|------|---------|
| `src/services/snapshot/store.ts` (50KB) | IndexedDB 持久层，MongoDB 后端已接管读写 | 确认 facade 所有读写路径已切到 backendRead/backendIngest 后删除 |
| `src/services/snapshot/runtime.ts` (75KB) | 核心采集引擎，含 IndexedDB 写入路径 | 拆出 IndexedDB 写入调用，保留采集和 MongoDB 写入逻辑 |
| `src/services/quantBoardBridge.ts` | 桥接层，含 IndexedDB 读取分支 | 确认 MongoDB 路径已替代后，移除 IndexedDB 分支 |

### 2.4 经审计确认保留的文件

以下在初版审计中被误判为"死代码"，经 grep 重新验证均有活跃引用链，**不做任何改动**：

| 文件 | 实际引用者 |
|------|-----------|
| `src/services/hotness/StockHotnessCalculator.ts` | `dataLoader/StockHotnessService.ts`（数据加载热链） |
| `src/services/VoiceService.ts` | `composables/useVoice.ts` + `big-order/BigOrderService.ts` |
| `src/services/exportService.ts` | `components/panels/ExportPanel.vue` |
| `src/services/SearchIndex.ts` | `components/common/SearchBox.vue` + `stores/selector.ts` + `composables/useStockSelector.ts` |
| `src/services/dragon/` 其余 14 个文件 | DragonReviewService 完整调用链，全部活跃 |
| `src/services/big-order/` 全部 3 个文件 | BigOrderService 活跃链，无冗余 |

### 2.5 删除流程

每批次：
1. `grep -r` 终轮确认零引用
2. 删除文件 + 对应测试
3. 更新聚合导出文件（如 `services/index.ts`、`dragon/index.ts`）
4. `pnpm typecheck` 确认无编译错误
5. `pnpm test` 确认无测试断裂
6. 提交，注明删除原因和 grep 证据

---

## 三、验证计划

### 任务一验证
1. `curl POST /api/journal/entries` 创建记录 → MongoDB 确认文档存在
2. `curl GET /api/journal/entries` 列表查询
3. 上传截图 → 确认文件落盘且路径写入文档
4. 前端面板在交易时段打开，确认"抓取信号"能正确读取 DataLayer
5. 入场 → 出场联动计算盈亏正确

### 任务二验证
1. `pnpm typecheck` 无新增错误
2. `pnpm test` 全量通过
3. 手动检查 `pnpm dev` 前端可正常启动

---

## 四、执行顺序

```
Phase 1: 直接删除（A 类，无依赖风险）
  ├── 删除 DragonAnalyzerCompat.ts
  ├── 删除 ContextBuilder.ts + 测试
  └── 删除 moneyFlowDiagnostics.ts + 测试

Phase 2: DragonAnalyzer 迁移（B 类，需改消费者）
  ├── 分析 DragonReviewService 对外接口
  ├── 迁移 5 个消费者到 DragonReviewService
  ├── typecheck + test 验证
  └── 删除 DragonAnalyzer.ts + 测试

Phase 3: 交易日志模块（全新功能，依赖干净代码库）
  ├── MongoDB collection + indexes
  ├── Repository CRUD 方法
  ├── API 路由 + main.py 注册
  └── 前端面板 TradeJournalPanel.vue

Phase 4: IndexedDB 残留清理（C 类，最后处理）
  ├── store.ts 读路径迁移确认
  ├── runtime.ts 写路径迁移
  └── quantBoardBridge.ts IndexedDB 分支移除
```

---

## 五、不在范围内的内容

- 不新增 SQLite 交易日志兼容路径
- 不修改现有回测/优化/主题模块
- 不处理 proxy-server 代码清理（独立进程，暂无冗余）
- 不修改 python-bridge
