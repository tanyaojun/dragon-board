# 四计划交付评审报告（2026-09-09）

**评审范围**：2026-09-06 四份 spec（热榜情绪后端化 / 槽位落库+as-of / 验收口径修正 / 门控去噪）及对应 plan 的实施完成度复盘。
**提交链**：`885d3bb6..b076143e` 共 34 个提交（11 计划A + 9 计划B含2修复 + 6 计划C + 7 计划D + 1 文档入库），逐任务 TDD、逐任务独立提交、逐任务审查。
**执行模式**：主线程直接执行（用户裁定不开 subagent）；裁决台账见 `.superpowers/sdd/<plan-basename>/progress.md`（本地 scratch，不入库）。

## 一、总评

| 计划 | Spec | 交付判定 | 生产验证 |
|---|---|---|---|
| A · WP1a 热榜情绪后端化 | backend-migration-design | ✅ 完成（spec §11 已自附实施记录） | ✅ series 读口已在生产消费（每日 EOD 由 lazy compute 写入即证据） |
| B · WP1b+1c 槽位落库 + as-of | slotting-asof-design | ✅ 完成（含 2 个生产缺陷修复） | ✅ 迁移实跑 + 9/7 修复补采 + 9/8-9/9 双日稳态 |
| C · WP2 门控去噪 | gate-denoise-design | ✅ 完成（默认零行为变化达成） | ✅ 端到端翻转率与基线逐位一致 |
| D · WP3 验收口径修正 | acceptance-metrics-design | ✅ 完成 | ✅ 8 月冻结段基线 + 成本弹性表产出 |

**核心约束达成**：

1. **默认零行为变化**（计划 C 最高约束）：golden 回归无漂移 + WP3.2 端到端重跑翻转率逐位一致（veto=0.13760171403824675 / bd=0.08344539922047729 / regime_state=0.0010256877806395733；202 帧 / 45686 信号 / 1813 code）。
2. **无质量阻断**（AGENTS.md §4.0/§10）：情绪计算失败只打标不阻断帧采集；R6 事故恰好实证了兜底路径有效（AttributeError 只 log，帧照常落库）。
3. **8 月冻结纪律**：翻转率基线与成本扫描均为只读诊断，未回改任何历史结论与默认值。

## 二、逐 Spec 复盘

### 2.1 Spec A：热榜情绪计算后端化（fba8964d..88c91c81，11 提交）

| Spec 承诺 | 交付 | 提交 |
|---|---|---|
| §1 `analysis/hotlist/sentiment.py` 纯函数（5 证据 + 级联 + 8 状态 + fail-visible） | 913 行，18 case golden fixture 先行、全量对齐 | fba8964d→a1c2f011 |
| §2 operations 消除双口径 | `build_hotlist_sentiment_document` 改编排，EOD 口径升级为完整版（历史不重算，已声明） | b74852a4 |
| §3 `GET /series` lazy compute | days 默认 3 cap 30（真断言）、缺失日 fail-visible、幂等 | a05692f1 |
| §4 proxy 前缀修复（404 死链） | `/api/hotlist-sentiment/` 转发、不入缓存、边界用例 `hotlist-sentimentx` 防误转发 | f7332bb0 |
| §5 前端删除计算只消费 | 类型契约 + 薄 client（无兜底计算，missingDays 透传）+ 面板切换，-1856 行 | e8d0fc27/a34f2471/848a115b |
| §6 实时性行为变化 | 面板标注 slotTime 与缺失日 | a34f2471 |
| §8 文档注记 | 方案文档头部注记 + spec §11 实施记录 | 88c91c81 |

**偏差与裁决**（预检扫描 11 项）：EOD backfill 不 join displayStatus（spec 偏差，采纳计划三层论证：展示字段不影响入库数值与引擎消费）；"17/18 case"笔误以 18 case 清单为权威；golden fixture 1.5MB（结构所致，接受）。

**遗留**：① ~~`_build_market_data_like` 单测零覆盖~~ → **已闭环（2026-09-09）**：新增 `tests/test_hotlist_sentiment_market_data_like.py` 17 例锁行为测试（生产形状/mutation 验证），见第五节；② `run_for_date` 每日多一次 `trading_dates` 投影查询（低频性能项，保留）；③ 浏览器端到端当时受旧进程限制——生产侧 series 已被实际消费（每日 EOD lazy compute 写入），实质覆盖。

### 2.2 Spec B：槽位级落库 + 时点查询（5758e88a..e067f181 + df3f5351/c3b2d3f9，9 提交）

| Spec 承诺 | 交付 | 提交 |
|---|---|---|
| b1 槽位 `_id` 契约 + 四键唯一索引 + 存量迁移 | 迁移脚本（先查后改、--dry-run/--skip-index-drop）+ 索引扩四键 | 5758e88a/499b94d0 |
| b2 collector 挂载（不加进程/集合/API） | `compute_and_upsert_for_slot` 挂 completed 分支，失败不阻断 | f3243cb7 |
| b3 backfill 按帧遍历 | `run_for_date_slots`（slotErrors 继续 + 收尾补写 EOD） | 820365bb |
| c1 as-of 读口 | provider 闭包（当日 ≤slot 最新 → 前日 EOD "stale" → "missing"），内存缓存 O(天数) | 1bf8207c |
| c2 逐帧注入消 lookahead | `_ensure_hotlist_sentiment` 逐帧 + `hotlistSentimentStatus` 三态，`by_key` 删除 | 1bf8207c |
| c3 market_regime stale 标注 | reasons 追加、不改打分 | 13503252 |
| c4 L1 档案组 5 加注 | 已加"lookahead 已修复、待数据积累重验" | e067f181 |
| 文档同步 | database-migration-plan（新节）/ architecture（时点化 + 四键）/ L1 §6；api-cli 核对无需改 | e067f181 |

**实现形态偏差（如实记录）**：spec c1 预期 `service.get_as_of()` 方法，实际落地为 `make_hotlist_sentiment_provider` 闭包 + `list_slot_documents`/`get_eod_document` 读原语——功能语义（选择逻辑、缓存、三态）一致，且规避了工厂期触碰 MongoDB 的耦合（后被 R5 证明该松耦很关键）。

**裁决**：R1（fake 补 `$ne`）、R2（asof 测试 monkeypatch 防真实库）、R3（方法名以现文为准）、R4（compute 补 `self._db`）、R5（provider 惰性获取 service）、R6（repo 包装类暴露 `db`，见第四节）。

### 2.3 Spec C：环境门去噪（1f4b5760..9a3b6db7，6 提交）

| Spec 承诺 | 交付 | 提交 |
|---|---|---|
| 2a `GateConfirmState` 纯状态机（per-key 连续计数，K=1 直通） | 9 例状态机测试 | 1f4b5760 |
| 参数入 config + L1 登记 | `lifecycleConfirmFrames=1` 等四参数入 §7（R-C1：追加不重编号） | 1e78b582 |
| 2a 挂载三类链路 | replay 入口创建/出口复位 + veto(action) 每帧确认；live frames 经 history_args 传状态机；单股/replay_frame_at 直通（spec 明示边界） | ac78075d |
| 2a B/D 降档 K 确认 + E 连锁不回归 | `lc_tier_override` 经 `assemble_observation`，抑制标注后置追加（R-C4），lifecycle.signalTier 发布原始值 | 99f0df8b |
| 2b `RegimeSmoother`（EMA α + strong 迟滞） | 直通返回同一 dict 引用（零漂移保证），replay 挂载 + 随确认状态同批 reset | 5ced0656 |
| fail-visible 抑制标注 | reasons 追加确认进度；与 WP3.2 翻转率提取锚点 `fullmatch` 精确互斥（跨计划合同） | 同上 |
| golden 不漂移 + 状态隔离 | golden 28/10 例无漂移；T6 端到端重跑翻转率逐位一致 | 9a3b6db7 |

**执行期裁决**：R-C2（计划接线与自带测试矛盾 → 改每帧无条件过确认）；R-C3（出口对称复位等价 try/finally）；R-C4（计划 RED 落空补集成测试 + 抑制标注后置）；R-C5（K2 集成测试实证通道污染 → B/D 通道 key 加 `:lc` 命名空间）。

**非范围确认**：2c 调参扫描未做（研究任务）——其两项前置（lookahead 已修、翻转率基线已归档）均已满足，随时可启动。

### 2.4 Spec D：验收口径与噪音度量（8b82496e..94e7d1ec，7 提交）

| Spec 承诺 | 交付 | 提交 |
|---|---|---|
| 3.2 翻转率纯函数 + CLI + 基线 | 三纯函数（B/D 降档 fullmatch 精确锚点）+ diagnose CLI + 8 月冻结段基线归档（202 帧/45686 信号/1813 code） | 8b82496e/8b3bb1e7/63ac2fd1 |
| 3.1a1 hold-to-close 口径 | `evaluate(include_hold_to_close=False)` 默认关；同日尾帧强制出场；无 tradingDate → found=False（fail-visible） | ec720b7d |
| 3.1a2 成本敏感性 + fallbackSlippageRate 缺口 | 定值 0.001（运行时默认 0 → 唯一行为变化点，文档声明切换点不回改历史）+ 网格扫描 CLI | 041e2b12 |
| 3.1 验收口径声明 | h1 降诊断口径声明落入 signal-tier-backtest-plan.md | 49d1de9c |
| 3.3 命名同步 | 7 份文档勘误注记（不重写历史正文）+ 前端 13 处文案 | 49d1de9c/94e7d1ec |

**关键结论产出**：8 月段成本网格 6 格全产出（57 笔，pf 1.4418→1.2153 单调递减），2×滑点+2×费率下 pf 仍 >1.2——four_dim pf 1.0377 近盈亏平衡结论对成本稳健。

**裁决**：R-D1（import 以 `backend.services.shared` 现文为准）；R-D2（基线备注按实情改写为"WP1c 后、WP2 前"，不照抄计划模板的虚假时序声明）。

## 三、生产验证时间线

| 日期 | 事件 | 结果 |
|---|---|---|
| 09-06 | B 迁移实跑（94 EOD 哨兵 + 四键唯一索引重建） | ✅ 终验通过 |
| 09-07 首日 | 首个采集日人工核对（AGENTS.md §11.5） | 帧 11/11 ✓、EOD ✓，**槽位文档 0/11 ✗ → R6** |
| 09-07 | R6 修复 + 补采（同源幂等，11/11 written） | ✅ 终态 12 条 |
| 09-08/09-09 | 双日复核 | ✅ 全绿：11/11 帧、11/11 槽位实时落库（computedAt=槽位时刻）、EOD 哨兵正确、零 skip 警告 |

## 四、生产缺陷复盘（R5/R6，均已闭环）

1. **R5（工厂期绑定回归）**：计划 B Task 3 把 service 获取提前到工厂期 → live 链路 20 测试失败。拦截失效原因：Task 3 回归清单未覆盖 analyze API 套件。修复 df3f5351（惰性获取 + 2 测试锁契约）。
2. **R6（槽位接线静默失效）**：`self._repo.db` 在实际注入的包装类 `_MongoSnapshotCollectorRepository` 上不存在，AttributeError 被外层 except 吞成 log-only → 全天槽位文档缺失且零警告。拦截失效原因：WP1b 测试直测 compute 函数（FakeMongoDb），从未经过真实 DI 接缝；"已核实 db 句柄"注释核实的是内层类而非实际注入类。修复 c3b2d3f9（包装类/protocol 暴露 `db` + 真实包装类集成测试 2 例）+ 数据补采。
3. **共同教训**：集成测试必须穿过真实依赖注入接缝；"已核实"类注释必须对准实际注入的类型；静默兜底路径（except→log）需要配套的可观测断言，否则等于无兜底。

## 五、验证证据汇总

- **后端**：情绪家族+门控 12 文件 83 passed；collector 系列 86/81/31 passed；execution/trade 113 passed；WP3 系列 15 passed；golden 全程无漂移；已知环境项：全量 pytest 挂起（test_archive_research）、`test_backtest_core` 单例环境 flake（复跑通过）。
- **前端**：vue-tsc 零错误；vitest 全量 127 文件 1048 测试全绿（Task 7 时点）。
- **MongoDB 实测**：索引状态、94 条哨兵迁移、四轮交易日帧/run/情绪文档核对、补采终验。
- **锁行为测试补齐（2026-09-09，本报告同批）**：`tests/test_hotlist_sentiment_market_data_like.py` 17 例，锁定 `_build_market_data_like` 映射合同（生产形状五键精确相等 / 非字典→None / 阶梯规则 / zhaban-{} 与 thsPools-None 不对称 / 字符串数字收敛 / build_limit_evidence 消费端贯通）；mutation 验证（错键名 sibanPlus→siban）3 例如预期变红后还原；情绪家族子集 58 passed（17 新 + 41 存量）。过程中修正一处用例预期误差（erban=0.5 参与阶梯应命中 2 档），实现零改动。

## 六、遗留与后续（按优先级）

1. **WP2 2c 调参扫描**（K∈{1,2,3}、α 档位、迟滞）——前置已全部满足，走 `ranktrend-tier-longterm-test` 8 步流程；只有"证实"类才动默认值。
2. **L1 档案组 5 regime 门控重验**——9 月数据正在累积，建议 10 月初首轮 rolling walk-forward（届时 lookahead 修复后的干净数据满一个月）。
3. ~~`_build_market_data_like` 补单测~~ → **已完成（2026-09-09）**，见第五节。
4. ~~本报告落盘~~ → **本文档即该项**。
5. `.claude/settings.json`/`settings.local.json` 本地配置改动未提交（用户自决，非交付物）。

**总体结论**：四份 spec 全部按批准范围交付，无范围蔓延，非范围项均未触碰；两处生产缺陷均由"首个上线日人工核对 MongoDB"这道防线按设计捕获，验证了 AGENTS.md §11 流程的有效性。
