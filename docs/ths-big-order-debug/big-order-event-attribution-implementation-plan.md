# THSBigOrder 高置信事件归因实施计划

**目标：** 用已批准的窗口归因规则替换旧单笔 marker，并保证延迟确认事件只播一次。

**执行方式：** 当前 `main` 工作区 Inline Execution。保留已有语音、热榜跟随和 UI 改动，不回滚、不做无关格式化；完成验证后按用户要求提交本轮修复。

## 文件边界

- 新增 `tools/THSBigOrder/Analytics/BigOrderEventDetector.cs`：阈值、连续事件、价格确认、买活跃和承接好。
- 修改 `tools/THSBigOrder/THSBigOrderDataProvider.cs`：`CalculateMarkers` 仅委托 detector，删除旧 50 秒/6 秒规则。
- 修改 `tools/THSBigOrder/BigOrderAnnouncementTracker.cs`：从普通订单计数改为已确认 marker 计数。
- 修改 `tools/THSBigOrder.Tests/LonghuFeatureTests.cs`、`Program.cs`：事件、拒绝条件、延迟确认和防重播测试。
- 更新本专题 design/findings/progress/task plan：记录最终实现和验证，不改 Redis/API 合同。

## Task 1：事件检测 RED → GREEN

- [x] RED：注册并编写测试，证明单笔 1000 万、三笔 500 万无价格响应、主动方向纯度不足、跨午休拼接均无 marker。
- [x] RED：编写三笔 500 万 + 3bp 冲击 + 8~10 秒保留的点火/砸盘测试，确认 marker 落在候选结束秒同方向最大真实成交。
- [x] RED：编写前 20 个完整分钟同 Type P90 高于 500 万时抬高阈值、少于 30 笔时回退 500 万的测试。
- [x] 运行 `dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release`，新测试按预期因旧算法合同失败。
- [x] GREEN：实现按交易日/上午下午分段、按秒聚合、10 秒窗口、70% 纯度、3bp、8~10 秒 50% 保留和同方向 20 秒冷却。
- [x] GREEN：`CalculateMarkers(List<BigOrderItem>)` 保持签名，只调用 detector；非法时间/Type/金额/价格行清空 marker 后跳过。
- [x] 重跑 C# runner，Task 1 用例通过。

## Task 2：买活跃与承接好 RED → GREEN

- [x] RED：点火后 8 秒内至少两笔主动买、合计达到 `L`、纯度 70% 时标记买活跃；无延续时只保留点火。
- [x] RED：砸盘前后具备不少于 `2L`、至少五笔卖方驱动压力，并有 `Type=3` 吸收或 `Type=2 >= L` 反击，但只有价格从低点恢复 50% 且不创新低时标记承接好。
- [x] RED：覆盖卖压后的大额主动买反击窗口归因，不声称逐单撮合。
- [x] 运行 runner，新增附加 marker 断言按预期失败。
- [x] GREEN：在 detector 的已确认主事件上计算附加 marker，不允许独立“买活跃/承接好”行。
- [x] 重跑 runner，Task 2 用例通过。

## Task 3：延迟确认语音 RED → GREEN

- [x] RED：首帧普通行无 marker；后续同一成交获得点火/买活跃时播一次；重复刷新、marker 暂时消失再恢复均不重播。
- [x] RED：合法重复的相同 marker 成交按最大出现次数只补播新增 occurrence；切股、切源、跨日仍只建基线。
- [x] RED：更新 MainForm 边界测试，替换旧的“marker 变化永不播”合同，同时保留特殊筛选、日期缺失和 re-enable barrier。
- [x] 运行 runner，tracker 新合同断言按预期失败。
- [x] GREEN：tracker 只统计带 marker 的 `订单指纹 + FundMarker + BuyMarker`；普通订单不进入语音 ledger，已见 marker 最大计数不回退。
- [x] GREEN：确认窗口必须关闭后才冻结 marker，防止 marker 组合升级导致重复播报。
- [x] 重跑 runner，Task 3 用例及既有 FIFO 文本测试通过。

## Task 4：最终验证

- [x] 运行 C# runner：77 PASS / 0 FAIL，退出码 0。
- [x] 运行 `dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore`：0 warning / 0 error。
- [x] 对 7/17 的 28 只归档用生产 detector 重放：169,623 条有效、247 条无效；24 点火、23 砸盘、5 买活跃、0 承接好。
- [x] 运行 `git diff --check`，人工核对本轮文件未混入热榜跟随、Redis 或其它 UI 重构。
- [x] 更新专题进度；盘中准确率保留为下一交易日人工验收，不用单日重放替代。
