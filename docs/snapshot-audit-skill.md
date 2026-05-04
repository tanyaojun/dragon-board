---
name: snapshot-audit
description: 全面审计 src/services/snapshot/ 目录的快照保存/读取链路，检查 SQLite 迁移完成度，识别冗余代码并提出清理方案。当用户需要审查快照模块架构、清理废弃代码、或验证 IndexedDB→SQLite 迁移进度时使用。
---

# Snapshot 模块审计与清理

## 目标

对 `src/services/snapshot/` 目录做全面代码审计，产出：
1. 数据流拓扑图（写路径、读路径、同步路径）
2. IndexedDB vs SQLite 使用边界清单
3. 冗余/死代码清单
4. 清理方案与风险点

## 审计框架

### Phase 1：文件清单与职责映射

逐个读取 `src/services/snapshot/` 下的每个 `.ts` 文件（排除 `__tests__/`），对每个文件记录：

| 字段 | 说明 |
|------|------|
| 文件 | 相对路径 |
| 职责 | 一句话概括 |
| 被谁引用 | 哪些文件 import 了它 |
| 依赖了谁 | 它 import 了哪些文件/服务 |
| 存储层 | IndexedDB / SQLite / API / 无 |
| 是否被 facade 暴露 | 是/否，方法名 |

### Phase 2：存储边界分析

对每个存储操作标注归属：

- **IndexedDB（浏览器本地）**：`SnapshotStore`, `SnapshotFrameStore`, `SnapshotStockRowStore`, `SnapshotSectorRowStore`, `SnapshotProjectionMetaStore`, `SnapshotProjectionWriter`
- **SQLite（QuantBoard 后端）**：通过 `apiService` → `/api/snapshots/*` 端点的所有读写
- **双写路径**：同一份数据同时写入 IndexedDB 和后端 SQLite
- **备份路径**：localBackup(IndexedDB)、bucketBackup(StorageBucket API)、cloudBackup(R2/S3)

### Phase 3：冗余识别

检查以下典型冗余模式：

1. **重复的类型定义**：`types.ts` 与 `rankTrendDefaults.ts` 或其他文件中的重复接口
2. **重复的过滤/排序逻辑**：`SnapshotStore.list()`、`SnapshotFrameStore.list()`、`SnapshotStockRowStore.list()`、`SnapshotSectorRowStore.list()` 中的重叠代码块
3. **重复的 captureMode / type 校验**：`assertFormalSnapshotType` 在 `facade.ts` 和 `backendRead.ts` 中重复定义
4. **已废弃的存储兼容代码**：`migrateLegacySnapshotRecord`、`parseLegacySnapshotDate`、`LEGACY_LABEL_TO_TYPE` 等 V3 升级逻辑是否仍在使用
5. **未被调用的公开方法**：facade 中绑定了但无组件调用的方法
6. **仅用于 IndexedDB 但现在已走 SQLite 的读取路径**

### Phase 4：迁移完成度评估

对每个存储操作回答：
- 这个操作当前走的是 IndexedDB 还是 SQLite？
- 如果是 IndexedDB，是否有对应的后端 API？
- 如果已经走了 SQLite，IndexedDB 中的对应代码是否可以删除？

输出一张对照表：

| 操作 | 当前读路径 | 当前写路径 | 同步状态 | 可清理的旧路径 |
|------|-----------|-----------|---------|---------------|
| listSnapshots | SQLite (API) | - | - | IndexedDB 读可删除？ |
| getSnapshotById | SQLite (API) | - | - | - |
| saveXxxSnapshot | - | IndexedDB → SQLite | 多级同步 | - |
| ... | ... | ... | ... | ... |

### Phase 5：清理方案

基于审计结果，按优先级排列清理项：

- **P0（安全删除）**：已确认无调用方的死代码、重复定义
- **P1（高信心）**：已被 SQLite 替代的 IndexedDB 读取路径，删除后测试可验证
- **P2（需验证）**：疑似冗余但需要跑完整测试确认的代码
- **P3（保留观望）**：降级路径、兼容代码、尚未被 SQLite 覆盖的写入操作

每项需包含：文件、行号范围、原因、风险、验证命令。

## 关键边界约束

- `facade.ts` 的公开方法签名不能随意更改，它们被 `src/stores/` 和 `src/components/panels/` 消费
- `types.ts` 的类型定义与 QuantBoard 后端 API 有 contract 关系，修改前需确认后端兼容
- `runtime.ts` 承担了快照生成、调度、coverage、修复等编排逻辑，改动时需区分"存储层切换"和"业务逻辑调整"
- `store.ts` 中的 IndexedDB schema（version 9）升级逻辑需要保留，因为存量数据迁移依赖它
- 禁止在分析阶段做任何代码修改，必须先完成全部审计并得到用户确认

## 验证命令

修改完成后运行以下命令验证：

```powershell
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```
