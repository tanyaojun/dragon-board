# Jev 阶段 2（路径一）— 五维配置打标签验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日 15:00 收盘槽取热榜 top20 股，把五维（共振/技术/周期/题材/热度榜位）状态构建为叙事文本，让 jev 做 Choice 形态分类（6 类标签），落库后用 Tier 方法论验证：**标签组的次日 pctChange 是否有统计显著的区分度**。不预测、只打标。

**Architecture:** 复用阶段 1 全部基础设施（jev_client / 落库模式 / 回放框架）。新增：`jev_state.build_stock_config_narrative()`（五维叙事构建器）+ `operations/jev_label_stocks.py`（打标 runner）+ `operations/jev_label_report.py`（分组验证）。数据源 `snapshot_analysis`（282K 条，per 股 per 帧 analysis 文档含 resonance/technical/cycle/themeMomentum/decision/observation.rankTrend.signalTier），按 snapshotId 与 15:00 帧行关联。

**分类体系（6 类，与系统语言对齐）：** breakout 突破主升 / pullback 强势回踩 / bottom_reversal 超跌修复 / chase_risk 高位过热 / weak_drift 弱势漂移 / mixed_noise 信号矛盾。

**验证硬阈值（PASS_CANDIDATE 标准）：**
1. 有效标签（有次日匹配）≥200 个；
2. 标签组间次日 pctChange：最优组−最差组 ≥3pct 且 Kruskal-Wallis p<0.05；
3. **增量检验**：控制 signalTier 分层后组间区分度仍存在（jev 提供 Tier 之外的信息）；
4. 稳定性：抽 20 只相同输入重打，标签一致率 ≥80%。
任一不达 → INSUFFICIENT（样本/区分度不足）或 REJECT（反向/无差），jev 退役。

**成本：** ~660 次调用 × ~400 in-token ≈ $0.03。窗口与阶段 1 一致（2026-08-11 → 09-24，33 天）。

---

### Task 1: 五维叙事构建器（TDD）

**Files:**
- Modify: `quant-board/backend/analysis/hotlist/jev_state.py`（新增 build_stock_config_narrative）
- Test: `quant-board/tests/test_jev_state.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_stock_config_narrative():
    from backend.analysis.hotlist.jev_state import build_stock_config_narrative
    analysis = {"resonance": {"score": 45.2, "label": "较弱", "direction": "sell",
                              "relativeMomentum": -0.78, "acceleration": -0.99},
                "technical": {"movingAverage": {"trend": "down"},
                              "macd": {"cross": "death", "confirmed": True}},
                "cycle": {"stage": "cooling", "transition": "cooling", "confidence": 90,
                          "metrics": {"rankVelocity": -12.1}},
                "themeMomentum": {"themeName": "高股息", "score": 53.8, "direction": "neutral",
                                  "phaseLabel": "中性"},
                "decision": {"final": {"signal": "sell", "confidence": 45.2}},
                "observation": {"rankTrend": {"signalTier": "D", "tierReasons": ["趋势转弱/反向"]}}}
    row = {"code": "000592", "name": "平潭发展", "rank": 3}
    s = build_stock_config_narrative(analysis, row)
    assert "平潭发展" in s and "热榜第3" in s
    assert "共振" in s and "45.2" in s and "MACD" in s and "死叉" in s
    assert "cooling" in s and "高股息" in s and "D" in s

def test_stock_config_narrative_partial_missing():
    from backend.analysis.hotlist.jev_state import build_stock_config_narrative
    s = build_stock_config_narrative({"resonance": {"score": 70.0, "label": "强", "direction": "buy"}}, {"name": "X"})
    assert "共振" in s and "70" in s and "MACD" not in s  # 缺技术维则跳过该行，不伪造
```

- [ ] **Step 2: 跑失败 → Step 3: 实现**（构建器追加到 jev_state.py；缺维跳过对应行，不伪造；输出 ≤800 字符）

- [ ] **Step 4: 测试过 → Step 5: Commit** `feat(hotlist-jev): 五维叙事构建器（阶段2 TDD）`

### Task 2: 打标 runner

**Files:**
- Create: `quant-board/backend/operations/jev_label_stocks.py`

- [ ] **Step 1: 实现**（复用 call_jev/parse_jev_response；逐日 15:00 帧行 rank 前 20，按 snapshotId 取 analysis，构建叙事 → jev → 落 `hotlist_jev_stock_labels`，_id={snapshotId}:{code}，含 ruleTier/rowRank/次日待验证字段；`--dry-run` 支持；顺序执行 + 0.3s 间隔）

- [ ] **Step 2: dry-run 2 天**（state/narrative 打印、无异常）
- [ ] **Step 3: 全量 33 天**（~660 调用，后台）
- [ ] **Step 4: Commit** `feat(hotlist-jev): 五维打标 runner + 全量执行`

### Task 3: 分组验证报告 + 判定

**Files:**
- Create: `quant-board/backend/operations/jev_label_report.py`
- Output: `quant-board/docs/hotlist-jev/phase2-label-report.md`

- [ ] **Step 1: 验证脚本**（次日语料：次日同 code 行的 pctChange；四项硬阈值见头部；scipy.stats.kruskal；signalTier 分层增量检验；20 只重放稳定性）
- [ ] **Step 2: 生成报告 + 判定**（PASS_CANDIDATE / INSUFFICIENT / REJECT 三选一，标准写死）
- [ ] **Step 3: Commit** `docs(hotlist-jev): 阶段2 打标验证报告`；向用户汇报判定

## Self-Review 记录

- 与用户决策一致：路径一（不预测只打标）；避开阶段 1 双雷（无数值归纳、无预测问题）。
- 类型一致性：build_stock_config_narrative(analysis, row)->str；QUESTIONS 单 Choice 六类；落库 _id={snapshotId}:{code}。
- 风险披露：基线先验偏低（阶段 1 教训），本实验是 $0.03 级证伪实验，不是承诺。
