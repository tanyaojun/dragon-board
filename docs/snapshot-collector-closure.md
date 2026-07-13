# Backend Snapshot Collector 项目结项报告

> 2026-07-13 · 历时 33 天 · 503 tests

## 目标

将 Dragon Board 正式快照采集能力从浏览器运行时迁移到 QuantBoard 后端，实现不打开浏览器页面也能按时采集快照数据存入 MongoDB。

## 交付物

### 核心模块

| 文件 | 职责 |
|------|------|
| `quant-board/backend/snapshot_collector/slots.py` | 四类槽位表 + 调度器 |
| `quant-board/backend/snapshot_collector/providers.py` | 八平台热榜/行情/题材/涨停池数据采集 |
| `quant-board/backend/snapshot_collector/builder.py` | 快照数据组装 |
| `quant-board/backend/snapshot_collector/quality_gate.py` | 写入前质量检查（6 硬阻断 + 6 软告警） |
| `quant-board/backend/snapshot_collector/service.py` | 采集编排 |
| `quant-board/backend/snapshot_collector/scheduler.py` | 自动调度器 |
| `quant-board/backend/api/snapshot_collector_routes.py` | 7 REST 端点 |
| `python-bridge/main.py` | `GET /api/quotes/snapshot` 行情接口 |

### 配置

```env
QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=1
QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live
QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1
QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES=quarter_hour,half_hour,hourly,daily
```

### 测试

503 项 pytest 全部通过，覆盖 slots/provider/builder/quality_gate/service/api/cli/scheduler/mongo_integration。

## 生产事故

**时间**：2026-07-06 至 2026-07-10  
**根因**：`quality_gate.py` 第 170 行 `_has_invalid_stock_code()` 将设计文档的"全部无效才阻断"实现为"任一无效就阻断"（`any` 逻辑错误）  
**影响**：42 个半小时间隔快照槽位数据永久丢失（数据源不保留历史数据，无法恢复）  
**修复**：改为 `all()` 语义，2026-07-13 下午起全部槽位正常入库

## 复盘教训

1. **数据采集系统禁止质量阻断。** 唯一拒写条件：所有数据源不可用。其余情况一律保存+打标记。
2. **any→all 类语义偏差必须 Code Review 逐行比对设计文档。**
3. **分阶段影子验证无法暴露代码级 bug。** 直接生产小范围观察更有效。
4. **新功能上线后必须人工验证第一个交易日的 MongoDB 实际入库数据。**
5. **环境变量必须随代码一起管理，不能遗忘在 worktree 里。**

上述已写入 `AGENTS.md` §11 和 `CLAUDE.md` §10。

## 已知限制

- 采集窗口 5 分钟，后端重启导致历史槽位无法回补
- Phase 7 proxy-server 迁移待独立立项
- 2026-07-06~10 缺 42 个半小时间隔 + 2026-07-13 上午缺 17 个槽位，回测数据连续性受影响
