# 2026-09-11 机器待机导致下午快照全丢复盘与修复

## 现象

2026-09-11（周四，交易日）下午 `half_hour` 13:00/13:30/14:00/14:30/15:00/15:30
及 `daily` 15:30 共 7 个槽位全部未保存；上午 09:30-11:30 五个槽位正常。
用户观察到的相关性是"浏览器主页没打开快照就不工作"。

## 取证结论（实机证据链）

| 证据 | 结果 |
| --- | --- |
| `snapshot_collector_runs` 当日记录 | 仅 5 条（09:30-11:30，completed）；下午缺失槽位**连 run 记录都没有**——不是 blocked/failed，是采集从未被触发 |
| 8001 进程 | 2026-09-10 20:34 启动后持续存活，error_count=0，无启动失败标记 |
| Windows Kernel-Power 事件 | **12:00:42 进入 Adaptive Connected Standby，19:02:29 唤醒**（待机 7 小时） |
| 历史对照 | 09-08/09-09/09-10 每日 11 槽齐全（下午人在用电脑），09-11 独缺下午 |

**根因不是浏览器依赖**（架构上 collector 的 InProcess 网关、进程内热榜服务、
bridge 行情均独立于浏览器页面），而是"人离开电脑 → 主页关闭 + 机器待机"的
共生现象：浏览器主页只是人在用电脑的表象。

## 丢失机制（旧实现的三个缺陷）

1. **调度器对过期槽位 fail-silent**（`scheduler.py::_collect_due_slots`）：
   唤醒后发现所有槽位超过 5 分钟 grace，直接 `_completed_today.add(sid)` 静默
   跳过——不采集、不写 run 记录、不置 last_error，`/api/health` 一切正常。
2. **catch-up 收盘后不作为**（`collector_main.py::_catchup_missing_slots`）：
   `is_in_collect_window`（09:00-16:00）外直接 `continue`，19:02 唤醒后对当日
   缺失槽位完全不尝试。
3. **catch-up 的 `attempted` 在执行前登记**：补采即使 blocked 也当天永不重试。

## 修复（TDD，测试先行）

- `tests/test_snapshot_collector_scheduler.py::TestMissedSlotVisibility`（6 用例）
- `tests/test_snapshot_collector_catchup.py`（7 用例，新建）

### 1. 调度器缺失自检（fail-visible）

`SnapshotCollectorScheduler._record_missed_slots_now`：每次定时器唤醒后、
触发采集前执行。对"已过 grace 且**未入库**"的当日槽位：

- 写 `blocked` run 记录（`blockingIssues=["slot_missed_grace_window"]`）；
- 置 `last_error/last_error_at/last_error_slot`（`/api/health` 契约转
  degraded，launcher 可见）；
- 标记 `_completed_today`，同槽位只记录一次（idle recheck 反复唤醒不重复）。

调用顺序关键：必须在 `_collect_due_slots` **之前**，否则过期槽位先被静默
标记完成，缺失不可见。不做补采决策（盘中槽用收盘数据回填会失真），补采
由 catch-up 或人工 `POST /api/snapshot-collector/run-once` 承担。

### 2. catch-up 窗口延展 + 失败重试

`_catchup_cycle`（自 `_catchup_missing_slots` 拆出，可单测）：

- 窗口内（09:00-16:00）：全部缺失槽可补（现状不变）。
- 窗口外（16:00 至次日 09:00）：**仅补 `slot_time >= "15:00"` 的收盘定格槽位**
  （15:00/15:30/daily，收盘后行情定格回填不失真）；盘中槽不自动回填。
- `attempted` 仅在 `completed/deduped` 后登记；blocked/failed 下一轮（15 分钟）
  重试，缺失与原因保持可见。

## 当日数据处置

- 15:00/15:30/daily 三槽已人工 `run-once` 补采（captureMode=delayed，
  quality warnings 含 `delayed_capture`），`snapshot_analysis` 由 after-save
  钩子异步产出。
- 13:00-14:30 盘中槽放弃：盘中价格无法真实恢复，不回填失真数据。

### 同日口径变更（后续确认）

2026-09-11 晚确认新口径：**`half_hour` 收敛为 10 槽（止于 15:00 收盘定格），
15:30 收盘定格值只由 `daily` 承担**（避免与 daily 终值重复）。`slots.py` /
前端 `schedule.ts` 槽位表同步移除 15:30；MongoDB 中历史 34 个交易日
（07-28 ~ 09-11）的 `half_hour:15:30` 帧及其 stock/sector rows、records、
analysis、hotlist_sentiment 关联数据已全量清理（删除前 mongodump 全量备份）。
本文上文"补采 15:30 half_hour"为当日处置的历史事实，口径以本节为准。

## 遗留与建议

- `TestRepositoryPortProtocol::test_fake_implements_all_protocol_methods`
  为**既有失败**（c3b2d3f9 给 protocol 新增 `db` 句柄，测试内
  FakeSnapshotRepository 未跟上），与本复盘修复无关，待单独处理。
- 机器睡眠仍会使盘中槽位真实缺失（不可恢复数据）；长期可选方案是
  Windows 电源策略禁止交易时段（09:00-15:35）自动待机，属系统运维项。
