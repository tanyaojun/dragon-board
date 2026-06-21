# Backend Snapshot Collector Autostart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让修复后的 shadow-only 后端快照采集器在 2026-06-22 开盘前自动就绪，并连续采集至少两个完整交易日，无需人工启动命令。

**Architecture:** 新增一个仅面向 Windows 本机运行的轻量 Python 守护模块，复用目标工作区代码并在独立端口 `8001` 启动 QuantBoard API，避免占用主工作区现有 `8000`。守护模块只在依赖端口缺失时启动 MongoDB、proxy 和 python-bridge，并持续检查采集 API 的结构化健康状态；Windows 计划任务负责登录启动和异常重启。

**Tech Stack:** Python 3.13、FastAPI/Uvicorn、Windows Task Scheduler、pytest、MongoDB

---

### Task 1: 固化守护进程合同

**Files:**
- Create: `quant-board/tests/test_snapshot_collector_supervisor.py`
- Create: `quant-board/backend/snapshot_collector/supervisor.py`

- [x] **Step 1: Write the failing tests**

  覆盖服务路径构造、已有端口不重复启动、缺失进程启动、collector 健康响应必须同时满足 `enabled=true`、`running=true` 和 shadow dataset。

- [x] **Step 2: Run tests to verify RED**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_supervisor.py -q`

  Expected: FAIL，因为 `backend.snapshot_collector.supervisor` 尚不存在。

- [x] **Step 3: Implement the minimal supervisor**

  仅实现以下职责：端口探测、collector HTTP 健康检查、缺失服务隐藏启动、日志重定向、循环守护；不修改采集业务口径，不接管现有 `8000` 服务。

- [x] **Step 4: Run tests to verify GREEN**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_supervisor.py -q`

  Expected: PASS。

### Task 2: 加固采集运行状态

**Files:**
- Modify: `quant-board/backend/snapshot_collector/scheduler.py`
- Modify: `quant-board/tests/test_snapshot_collector_scheduler.py`

- [x] **Step 1: Write a failing regression test**

  证明后台任务意外结束后 `status().running` 不能继续报告为真，并允许下一轮 `start()` 恢复任务。

- [x] **Step 2: Verify RED**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_scheduler.py -q`

  Expected: 新增用例 FAIL，暴露 `_task` 已完成但仍被当作运行中的问题。

- [x] **Step 3: Implement minimal task-state cleanup**

  在 `start()` 和 `status()` 中识别已完成任务并清理引用，不改变 slot、去重或质量门禁规则。

- [x] **Step 4: Verify GREEN**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_scheduler.py -q`

  Expected: PASS。

### Task 3: 安装并现场验收 Windows 自动启动

**Files:**
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`

- [x] **Step 1: Register the scheduled task**

  计划任务使用目标工作区作为工作目录、主工作区现有虚拟环境作为解释器，登录即启动，失败后自动重启；多实例策略为忽略新实例。

- [x] **Step 2: Start the task now**

  今天为非交易日，启动不会产生交易时段快照，但应使 MongoDB、proxy、bridge 和独立 collector API 就绪。

- [x] **Step 3: Verify runtime state**

  检查 `8001` 状态接口返回 `enabled=true`、`running=true`、`dataset_id=dragonboard_backend_shadow`；确认现有 `8000` PID 和命令行未被替换。

- [x] **Step 4: Document the operational boundary**

  明确 `sector_rows=0` 是当前外部 API 端口限制，不降低 stock rows、records、frames、时间戳和 MongoDB 写入门禁。

### Task 4: 最终验证与阶段 5 复评

**Files:**
- Modify: `quant-board/docs/superpowers/reviews/backend-snapshot-collector-code-review.md`（如已有则更新）

- [x] **Step 1: Run focused collector tests**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py -q`

- [x] **Step 2: Run bridge tests**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m unittest discover ..\python-bridge -p "test_*.py"`

- [x] **Step 3: Run full backend suite**

  Run: `D:\dragon-board\quant-board\.venv\Scripts\python.exe -m pytest -q`

- [x] **Step 4: Re-evaluate Stage 5**

  代码和自动运行门禁通过后，阶段 5 仍需等待两个完整交易日的真实 shadow 数据质量审计；不得用模拟测试替代真实交易日数据。
