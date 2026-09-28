# Jev 阶段 3 — 涨停驱动类型分类验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每交易日带 `reason` 的涨停股（THS 池成员行），用"THS 涨停原因 + theme_stock_mappings 业务底座 + 行业"三源叙事让 jev 打驱动类型标签（Choice 七类）+ 催化-主业匹配度（Noul），验证标签对次日连板率/溢价是否有区分度。**不预测、只打标，验证权在结果数据。**

**用户拍板：** 33 天试点窗口（2026-08-11 → 09-24，与阶段 1/2 同窗可比）+ 七类词表。

**数据事实（已实地核验）：** `snapshot_stock_rows.reason`（THS limit_up_reason 映射，285K+ 行，5 月起有，只落采集池∩涨停池成员）；`theme_stock_mappings`（4,275 股 × 245 题材，stockReason=业务关联原因，stockTags=归属标签，每日 00:30 更新）；次日语料=次日同 code 行 pctChange（百分数，|pct|>21 剔除除权）；连板近似=昨日同 code 也有 reason 行；次日连板率近似=次日 pct≥9.8（不分板块，报告注明近似）。

**新增数据面：** 无新采集（全部存量）。落库 `hotlist_jev_driver_labels`，_id={date}:{code}。

**硬阈值（PASS_CANDIDATE）：** ① 有效样本 ≥800；② 驱动类型分组：连板率极差 ≥15pct 且 pct Kruskal p<0.05；③ 匹配度 Noul 高组(>0.7) vs 低组(<0.3) 次日 pct 差 ≥2pct 且方向为正、Mann-Whitney p<0.05；④ 稳定性重打 20 只 ≥80%。全过=PASS_CANDIDATE；部分=INSUFFICIENT；方向反=REJECT。

**成本：** ~2,600 调用 × ~500 token ≈ $0.08，双 worker 并发 ~30 分钟。

---

### Task 1: 驱动叙事构建器（TDD）

**Files:** Modify `backend/analysis/hotlist/jev_state.py`（追加 build_driver_label_narrative）；Test `tests/test_jev_state.py` 追加。

- [ ] 失败测试：三源齐全输出全要素（涨停原因原文/行业或 mainTheme/每条映射的题材+tags+reason）；无映射时如实输出"无题材映射记录"；总长 ≤1200 字符。
- [ ] 实现：`build_driver_label_narrative(ths_reason, row, mappings)`；mappings=[{themeName?, tags, reason}]（≤4 条，每条截断）。
- [ ] 测试过 → Commit `feat(hotlist-jev): 驱动叙事构建器（阶段3 TDD）`

### Task 2: 打标 runner

**Files:** Create `backend/operations/jev_label_driver.py`

- [ ] 实现：逐日取带 reason 的行（每 (date,code) 取当日最晚槽），join theme_stock_mappings（stockCode），QUESTIONS={driver_type: Choice 七类, business_match: Noul}；ThreadPoolExecutor(2) 并发；落库含 hadReasonYesterday、ruleTier、usage/latency；`--dry-run`。
- [ ] dry-run 2 天 → 全量 33 天（后台）
- [ ] Commit `feat(hotlist-jev): 驱动打标 runner + 全量执行`

### Task 3: 验证报告 + 判定

**Files:** Create `backend/operations/jev_label_driver_report.py`；Output `docs/hotlist-jev/phase3-driver-report.md`

- [ ] 指标：驱动类型分布/连板率/次日 pct 均值；Kruskal；Noul 匹配度分组；首板/连板分层；稳定性；退化率。
- [ ] 生成报告 + 硬阈值判定 → Commit `docs(hotlist-jev): 阶段3 驱动分类验证报告`
- [ ] 向用户汇报判定；PASS_CANDIDATE 才讨论下一步（扩窗加固/接入观察面），否则 jev 退役流程。
