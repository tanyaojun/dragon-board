# Backend Snapshot Collector 审查进度

## 2026-06-21

- 已读取根 `AGENTS.md` 与 `SKILLS.md`。
- 已确认目标 worktree、当前分支、近期提交和工作区未提交文件。
- 已建立全量审查计划；下一步读取专题文档与 QuantBoard 强制协作文档。
- 已读取 QuantBoard README、AI 协作合同、collector 设计/实施计划/阶段进度，并提取 Phase 1–5 验收条件。
- 已确定审查基线为 `main` merge-base `25b63cb1`；分支相对基线共 36 个文件、约 1.4 万行新增。
- 下一步运行 collector/bridge 基线测试，同时逐模块审查实现与合同。
- Collector 基线完成：451 passed、6 failed；已定位 compare 路由缺失和 `.env.local` 测试污染。
- Bridge 基线完成：28 passed，存在文件句柄 ResourceWarning。
- 已开始审查生产 Mongo compare 算法，发现核心测试复制 fake 实现且共同缺槽不可见。
- 已按 TDD 修复 compare 路由、共同缺槽、计数漂移、正式字段投影、资金流 provenance、force 覆盖和 bridge 陈旧时间戳。
- Collector 回归：464 passed；Bridge 回归：29 passed；compileall 通过。
- 已读取真实 MongoDB：shadow 仅 2026-06-15/16 两个完整交易日，槽位完整但每槽 100 行、0 sector rows，字段质量显著低于 live。
- 当前阶段 5 判定为 No-Go；下一步完成全量 QuantBoard pytest、diff 复审与文档一致性检查。
- QuantBoard 全量 pytest：949 passed / 3 failed；失败已在主工作区基线复现，均属于既有 ThemeSupport 问题。
- 最终验证：collector 464 passed；bridge 29 passed；`git diff --check` 通过。
- 审查与修复完成，阶段 5 结论为 No-Go；需要积累修复后新的两日 shadow 证据再复评。
- 2026-06-21：新增独立 collector supervisor 和调度器死任务恢复测试；安装 `DragonBoard Backend Snapshot Collector` 隐藏计划任务，当前 `8001` 状态为 enabled/running，下一次工作日触发时间为 2026-06-22 08:45。`sector_rows=0` 暂按外部板块 API 端口限制记录。
- 验证证据：collector 测试 469 passed；python-bridge 29 passed；故障恢复演练中 `8001` PID 19040 被终止后自动恢复为 PID 2088，scheduler 状态仍为 enabled/running。全量 QuantBoard 为 954 passed、3 failed，失败均来自未修改的 `tests/test_theme_support.py`，其输入缺少当前策略合同要求的 `finalSignal=buy`，单文件运行可稳定复现，记录为既有基线问题。
- 提交前 review 修复采用 TDD：新增依赖结构化健康、自有异常进程重启、force 写失败恢复测试；RED 为 5 failed / 17 passed，GREEN 为 22 passed，随后进入完整回归。
- 修复后 collector 回归为 473 passed，bridge 为 29 passed；QuantBoard 全量为 958 passed / 3 failed，主工作区基线运行 `test_theme_support.py` 同样为 3 failed / 7 passed，确认不是本分支引入。真实依赖探测返回 MongoDB、proxy、bridge、collector 全部 `healthy`。
- 提交门禁补充：排除已确认的基线失败文件 `tests/test_theme_support.py` 后，QuantBoard 其余 951 项全部通过；`compileall` 与 `git diff --check` 通过。
- 2026-06-27：已定位并修复 `2026-06-23 11:00`、`2026-06-26 11:30` count drift 根因。原因是 builder 在跳过无 code 股票前用原始 provider 行数写 `frame.stockRowCount`；新增失败优先回归测试后改为用最终 `stockRows` 数量回填，并将两个历史 shadow frame 摘要从 100 校正为实际 97/98，写入 `migration_audit`。
- 2026-06-27：按用户最新要求补齐 `2026-06-22 15:00` 缺槽。新增 `copy-missing-mongodb-snapshot-slots` 维护 CLI，先 dry-run 确认 live donor 同槽位存在 221 stock rows，再执行 `--apply` 复制到 `dragonboard_backend_shadow`，目标 frame 写入 `qualityFlags=copied_from_donor_dataset` 与 `metadata.repair`，并记录 `migration_audit(opType=mongodb_snapshot_slot_copy)`。复核审计显示 half_hour 全量 `70 frames / 70 records / 7116 stock rows / 9082 sector rows`，`missingSlots=[]`，`countDrifts=[]`；daily 仍无缺槽、无漂移。
- 2026-06-27：字段门禁复评完成。`depth10`、`sectorLabel` 属于后端采集器替代前端写库前的关键能力缺口；`limitUpPool`、`amplitude` 当前不单独阻塞槽位阶段，但应作为涨停池/高低价专项记录，不能用空值伪装修复。阶段 5 结论更新为：槽位/record/count drift 门槛通过，数据域替代门槛仍 No-Go。
- 2026-06-27：按“代码未实现/未接入前端数据源”做全面收束。已补默认挂载 `BridgeQuoteProvider`、`ProxyLimitUpProvider`、`ThemeMappingProvider`，修复 bridge `bids/asks` 盘口结构、`lastPrice/changePct/turnoverRate` quote 别名，以及 `high/low/preClose -> amplitude` 派生。只读 dry-run（2026-06-26 15:00，不写库）显示：213 stock rows 中 `price/change/turnoverRate/depth10/high/low/preClose/amplitude=213/213`，`themes/mainTheme/sectorLabel=205/213`，`limitUpPool=49/213`。结论更新：代码接入阻塞已清零；阶段 5 仍需修复后新落库两日审计，不能用历史缺字段库直接放行。
- 2026-07-03：Phase 5 收口复评完成。`dragonboard_live` 最近 5 个交易日（2026-06-29 至 2026-07-03）half_hour 分日审计均为 10 frames / 10 records，`missingSlots=[]`、`emptyFrames=[]`、`missingRecords=[]`、`countDrifts=[]`；`verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour` 返回 `ok=true`，shadow 同命令也返回 `ok=true`。本次将 Phase 5 硬门槛收敛为“前端默认不再自动生产正式快照，手动诊断入口保留，正式读取合同不变”，并在 `SnapshotRuntime` 增加 `enableFormalSnapshotSweep`，默认关闭 `snapshot.sweep` 正式写库调度；显式开启仍保留诊断能力。
- 2026-07-03：数据域缺口一次性定性：近期 live 仍存在 `sectorRows=0`，且 `limitUpPool`、`sectorLabel`、`moneyFlow`、`amplitude` 在 live 审计中为 100% 缺失；这些问题不再作为 Phase 5 前端生产职责退役的无限阻塞项，转入后续“数据域完整性/正式 live collector 切换”专题处理。阶段 5 当前结论更新为 Go：可以关闭前端默认自动写库，但不得据此宣布后端 collector 已正式写入 `dragonboard_live`；正式 live collector 切换仍需单独 Phase 6 门禁。
