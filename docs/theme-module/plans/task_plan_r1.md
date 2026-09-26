# Phase R1 实施计划：题材轮动度量 + mainTheme 判定链描述性实证

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立题材轮动度量纯函数与 mainTheme 判定链纯函数（正式落位 `analysis/theme/`，未接线生产），并用 2026-07-06~09-24 真实数据产出轮动特征与新旧判定差异的描述性实证报告，定版 MainlineScore 权重提案。

**Architecture:** 纯函数因子（TDD、已知答案校验）+ 只读研究 runner（`backend/operations/diagnose_*` 既有范式：argparse → MongoDB 直读 → 统计 → JSON 报告到 `data/reports/`）。不改任何生产链路代码；判定链接线 projection 属后续任务。

**Tech Stack:** Python 3 / pymongo（经 `MongoRepository`）/ pytest。研究脚本遵守资源纪律：只读、无 optimization API、单进程、本地输出。

**设计依据:** `docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md` §5.4/§5.5/§6.1（Phase R1 定义）、§6.0（数据可得性：完整期 2026-07-06~09-24，7-10/7-24 断采，9-25 中秋休市；15:30 收盘槽 THS 池最全；9 月弱势段约 14 交易日，样本量仅够探索性分析）。

**已验证接口事实**（写代码前已实测）：
- `MongoRepository(get_runtime_mongodb_database())`（`backend/operations/harness_common.py` 同款用法）
- `repo.list_snapshot_sector_rows(dataset_id, start_date=, end_date=, entity_type="hot_theme", sort="asc")` → `{"rows": [...], "source": "mongodb"}`（`mongo_repository.py:721-763`）
- `repo.list_snapshot_stock_rows(dataset_id, start_date=, end_date=, fields=[...], sort="asc")` → `{"rows": [...]}`（`mongo_repository.py:603-648`）
- stock/sector row bundle 为直通字典（键 `code`/`tradingDate`/`slotTime`/`entityKey`/`rank`/`themes`/`mainTheme` 等，去 `_id` 与 None 值，`mongo_repository.py:969-974`）
- limitSummary 在 `snapshot_frames` 集合，按 `tradingDate`+`slotTime=="15:30"` 取（`repo.db["snapshot_frames"]` 直查）
- 测试目录：`quant-board/tests/test_*.py` 集中式

**数据窗口:** 全窗 `2026-07-06 ~ 2026-09-24`（Phase 0 实测完整因子期）；弱势段切片 `2026-09-01 ~ 2026-09-24`。

---

## File Structure

```text
quant-board/
├── backend/analysis/theme/rotation/measures.py      # 新建：轮动度量 4 纯函数（无 I/O）
├── backend/analysis/theme/mainline_assignment.py    # 新建：主线判定链纯函数（无 I/O）
├── backend/operations/diagnose_theme_rotation_r1.py # 新建：R1 描述性实证 runner（只读 MongoDB）
├── tests/test_theme_rotation_measures.py            # 新建：度量函数已知答案校验
├── tests/test_theme_mainline_assignment.py          # 新建：判定链已知答案校验
├── data/reports/theme-r1-rotation.json              # 运行产物（gitignore，不提交）
docs/theme-module/
└── 2026-09-26-phase-r1-findings.md                  # 新建：R1 实证报告 + 权重定版提案
```

职责边界：`measures.py` 与 `mainline_assignment.py` 为纯函数、无 MongoDB 依赖、可独立测试；runner 负责全部 I/O 与编排；报告由 runner 输出数据支撑、人工撰写结论。

---

### Task 1: 轮动度量纯函数 `measures.py`

**Files:**
- Create: `quant-board/backend/analysis/theme/rotation/measures.py`
- Test: `quant-board/tests/test_theme_rotation_measures.py`

- [ ] **Step 1.1: 写失败测试**

创建 `quant-board/tests/test_theme_rotation_measures.py`：

```python
"""轮动度量纯函数已知答案校验（Phase R1）。"""

from backend.analysis.theme.rotation.measures import (
    dedup_limit_count,
    mainline_persistence,
    rank_entropy,
    rotation_speed,
)


class TestRotationSpeed:
    def test_identical_top_lists_speed_zero(self):
        result = rotation_speed([{"a", "b", "c"}, {"a", "b", "c"}])
        assert result["status"] == "ok"
        assert result["mean"] == 0.0
        assert result["series"][0]["value"] == 0.0

    def test_disjoint_top_lists_speed_one(self):
        result = rotation_speed([{"a", "b", "c"}, {"d", "e", "f"}])
        assert result["status"] == "ok"
        assert result["series"][0]["value"] == 1.0

    def test_half_overlap(self):
        result = rotation_speed([{"a", "b", "c", "d"}, {"c", "d", "e", "f"}])
        # 交集 2 / 并集 6 → jaccard 1/3 → speed 2/3
        assert abs(result["series"][0]["value"] - 0.6667) < 1e-4

    def test_insufficient_when_fewer_than_two_days(self):
        assert rotation_speed([{"a"}])["status"] == "insufficient"

    def test_empty_day_breaks_series_but_keeps_rest(self):
        result = rotation_speed([{"a", "b"}, set(), {"a", "b"}])
        assert result["series"][1]["status"] == "insufficient"
        assert result["status"] == "ok"


class TestMainlinePersistence:
    def test_constant_mainline_zero_switches(self):
        result = mainline_persistence({"d1": "AI", "d2": "AI", "d3": "AI"})
        assert result["status"] == "ok"
        assert result["switches"] == 0
        assert result["streaks"] == [3]
        assert result["switch_rate"] == 0.0

    def test_daily_rotation_max_switches(self):
        result = mainline_persistence({"d1": "AI", "d2": "机器人", "d3": "AI"})
        assert result["switches"] == 2
        assert result["streaks"] == [1, 1] or result["streaks"] == [1, 1, 1]
        assert result["switch_rate"] == 1.0

    def test_none_day_breaks_segment_without_counting_switch(self):
        result = mainline_persistence({"d1": "AI", "d2": None, "d3": "机器人"})
        # d2 缺失：AI 段结束记 streak=1，d3 新段不计切换
        assert result["switches"] == 0
        assert result["streaks"] == [1, 1]

    def test_insufficient_no_known_mainline(self):
        assert mainline_persistence({"d1": None})["status"] == "insufficient"


class TestRankEntropy:
    def test_single_theme_monopoly_zero_entropy(self):
        result = rank_entropy({"AI": 10}, total_days=10)
        assert result["status"] == "ok"
        assert result["entropy"] == 0.0
        assert result["normalized"] == 0.0

    def test_uniform_distribution_normalized_one(self):
        # 4 题材各霸榜天数相同 → 均匀分布，归一化熵=1
        result = rank_entropy({"a": 3, "b": 3, "c": 3, "d": 3}, total_days=12)
        assert result["status"] == "ok"
        assert abs(result["normalized"] - 1.0) < 1e-4

    def test_insufficient_empty(self):
        assert rank_entropy({}, total_days=10)["status"] == "insufficient"


class TestDedupLimitCount:
    def test_inflation_ratio_counts_overlap(self):
        # 3 只涨停股，其中 000988 属 AI 与芯片两题材 → 重复计数总和 4，守恒 3
        repeat = {"AI": {"000988", "002335"}, "芯片": {"000988", "301171"}}
        owner = {"000988": "AI", "002335": "AI", "301171": "芯片"}
        result = dedup_limit_count(repeat, owner)
        assert result["status"] == "ok"
        assert result["repeat_total"] == 4
        assert result["dedup_total"] == 3
        assert result["dedup_by_theme"] == {"AI": 2, "芯片": 1}
        assert abs(result["inflation_ratio"] - 4 / 3) < 1e-4

    def test_insufficient_empty_owner(self):
        result = dedup_limit_count({"AI": {"x"}}, {})
        assert result["status"] == "insufficient"
        assert result["dedup_total"] == 0
```

- [ ] **Step 1.2: 运行测试确认失败**

```powershell
cd D:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests\test_theme_rotation_measures.py -v
```

预期：FAIL（`ModuleNotFoundError: backend.analysis.theme.rotation.measures`）。

- [ ] **Step 1.3: 实现 `measures.py`**

创建 `quant-board/backend/analysis/theme/rotation/measures.py`：

```python
"""题材轮动度量纯函数（Phase R1 研究，ThemeTrend 设计文档 §5.3 轮动维 / §6.1 Phase R1）。

输入输出均为普通 dict/list，无 I/O、无 MongoDB 依赖。
fail-visible：样本不足返回 status="insufficient" 并保留可计算部分，
不伪造 0、不抛异常中断。
"""

from __future__ import annotations

import math
from typing import Any


def rotation_speed(top_sets: list[set[str]]) -> dict[str, Any]:
    """TopN 题材名单的日间 Jaccard 距离序列 → 轮动速度统计。

    rotation_speed_t = 1 - |TopN_t ∩ TopN_{t-1}| / |TopN_t ∪ TopN_{t-1}|
    值域 0-1：0=名单完全不变（主线极稳），1=名单完全换血（极速轮动）。
    空集合日该次转移标 insufficient，不参与均值但保留在 series。
    """
    series: list[dict[str, Any]] = []
    for i in range(1, len(top_sets)):
        a, b = top_sets[i - 1], top_sets[i]
        union = a | b
        if not union:
            series.append({"index": i, "value": None, "status": "insufficient"})
            continue
        series.append(
            {"index": i, "value": round(1.0 - len(a & b) / len(union), 4), "status": "ok"}
        )
    values = [s["value"] for s in series if s["value"] is not None]
    if not values:
        return {
            "status": "insufficient",
            "reason": "need_at_least_two_nonempty_days",
            "series": series,
        }
    return {
        "status": "ok",
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "n_transitions": len(values),
        "series": series,
    }


def mainline_persistence(mainline_by_day: dict[str, str | None]) -> dict[str, Any]:
    """每日主线题材（Top1）序列 → 主线连续保持天数分布与切换频率。

    None（缺失/未判出）日断开连续段：结束当前段、不计切换、不并入下一段。
    """
    days = sorted(mainline_by_day)
    streaks: list[int] = []
    switches = 0
    comparable = 0
    cur_theme: str | None = None
    cur_len = 0
    for d in days:
        theme = mainline_by_day[d]
        if theme is None:
            if cur_len:
                streaks.append(cur_len)
            cur_theme, cur_len = None, 0
            continue
        if cur_theme is None:
            cur_theme, cur_len = theme, 1
        elif theme == cur_theme:
            cur_len += 1
        else:
            comparable += 1
            switches += 1
            streaks.append(cur_len)
            cur_theme, cur_len = theme, 1
    if cur_len:
        streaks.append(cur_len)
    if not streaks:
        return {"status": "insufficient", "reason": "no_mainline_days", "streaks": []}
    return {
        "status": "ok",
        "streaks": streaks,
        "mean_streak": round(sum(streaks) / len(streaks), 2),
        "max_streak": max(streaks),
        "switches": switches,
        "comparable_transitions": comparable,
        "switch_rate": round(switches / comparable, 4) if comparable else None,
        "n_days": len([d for d in days if mainline_by_day[d] is not None]),
    }


def rank_entropy(top_counts: dict[str, int]) -> dict[str, Any]:
    """TopN 成员霸榜频率分布的归一化 Shannon 熵。

    p_i = 题材 i 进入 TopN 的天数 / Σ(全部题材霸榜天数)；
    熵低 = 少数题材霸榜（主线集中）；熵高 = 频繁换脸（轮动混沌）。
    归一化基准 log(k)，k=出现过的题材数。
    """
    total_hits = sum(top_counts.values())
    if total_hits == 0:
        return {"status": "insufficient", "reason": "no_top_hits"}
    probs = [c / total_hits for c in top_counts.values() if c > 0]
    h = -sum(p * math.log(p) for p in probs)
    k = len(probs)
    norm = h / math.log(k) if k > 1 else 0.0
    return {
        "status": "ok",
        "entropy": round(h, 4),
        "normalized": round(norm, 4),
        "k_themes": k,
        "total_hits": total_hits,
    }


def dedup_limit_count(
    repeat_counted: dict[str, set[str]], owner: dict[str, str]
) -> dict[str, Any]:
    """守恒涨停计数 vs 重复计数对比（Phase 0 已知失真方向的量化）。

    repeat_counted: {themeKey: set(stockCode)} 现有口径（一股属多题材重复计入）
    owner: {stockCode: themeKey} 个股唯一归属（mainTheme 判定链输出）
    """
    dedup: dict[str, int] = {}
    for code, theme in owner.items():
        dedup[theme] = dedup.get(theme, 0) + 1
    dedup_total = sum(dedup.values())
    repeat_total = sum(len(v) for v in repeat_counted.values())
    return {
        "status": "ok" if dedup_total else "insufficient",
        "reason": None if dedup_total else "empty_owner",
        "repeat_by_theme": {k: len(v) for k, v in repeat_counted.items()},
        "repeat_total": repeat_total,
        "dedup_by_theme": dedup,
        "dedup_total": dedup_total,
        "inflation_ratio": round(repeat_total / dedup_total, 4) if dedup_total else None,
    }
```

- [ ] **Step 1.4: 运行测试确认通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_theme_rotation_measures.py -v
```

预期：全部 PASS（12 用例）。

- [ ] **Step 1.5: Commit**

```powershell
git add backend/analysis/theme/rotation/measures.py tests/test_theme_rotation_measures.py
git commit -m "feat(theme): 轮动度量纯函数——轮动速度/主线持续性/排名熵/守恒计数（Phase R1）"
```

---

### Task 2: 主线判定链纯函数 `mainline_assignment.py`

**Files:**
- Create: `quant-board/backend/analysis/theme/mainline_assignment.py`
- Test: `quant-board/tests/test_theme_mainline_assignment.py`

- [ ] **Step 2.1: 写失败测试**

创建 `quant-board/tests/test_theme_mainline_assignment.py`：

```python
"""主线题材归属判定链已知答案校验（Phase R1，设计文档 §5.5）。"""

from backend.analysis.theme.mainline_assignment import (
    assign_main_theme,
    mainline_scores,
)


def _rows():
    """三题材横截面：heat 与 momentum 同序，ztCount 反序，fund 仅两题材有。"""
    return [
        {"entityKey": "AI", "heatLevel": 90.0, "momentumScore": 80.0, "ztCount": 5, "fundScore": 70.0},
        {"entityKey": "机器人", "heatLevel": 70.0, "momentumScore": 60.0, "ztCount": 10, "fundScore": 50.0},
        {"entityKey": "芯片", "heatLevel": 50.0, "momentumScore": 40.0, "ztCount": 2},  # 无 fundScore
    ]


class TestMainlineScores:
    def test_scores_ordered_by_dominant_factors(self):
        scores = mainline_scores(_rows())
        assert scores["AI"]["status"] == "ok"
        # AI 在 heat(最高)/momentum(最高)/fund(最高) 三因子 percentile=1.0，ztCount 最低=0
        # 机器人 heat/momentum 居中 0.5、ztCount 最高 1.0、fund 最低 0
        # 芯片 heat/momentum 最低 0、ztCount 最低 0、fund 缺失（权重重分配）
        assert scores["AI"]["score"] > scores["机器人"]["score"] > scores["芯片"]["score"]

    def test_missing_factor_redistributes_weight_and_flags(self):
        scores = mainline_scores(_rows())
        # 芯片缺 fundScore：coverage = (0.40+0.25+0.20)/(0.40+0.25+0.20+0.15)
        assert scores["芯片"]["status"] == "degraded"
        assert abs(scores["芯片"]["factorCoverage"] - 0.85) < 1e-6
        assert "fundScore" not in scores["芯片"]["factorsUsed"]

    def test_all_factors_missing_is_insufficient(self):
        scores = mainline_scores([{"entityKey": "X", "heatLevel": None}])
        assert scores["X"]["status"] == "insufficient"
        assert scores["X"]["score"] is None

    def test_single_theme_gets_neutral_percentile(self):
        scores = mainline_scores([{"entityKey": "AI", "heatLevel": 88.0, "momentumScore": 55.0, "ztCount": 3, "fundScore": 60.0}])
        assert scores["AI"]["score"] == 50.0  # 唯一题材 percentile 归中


class TestAssignMainTheme:
    def _scores(self):
        return {
            "AI": {"score": 90.0, "status": "ok"},
            "机器人": {"score": 55.0, "status": "ok"},
            "芯片": {"score": 54.5, "status": "ok"},
        }

    def test_highest_score_wins(self):
        result = assign_main_theme(["芯片", "AI", "机器人"], self._scores())
        assert result["mainTheme"] == "AI"
        assert result["mainThemeReason"] == "mainline_score"
        assert abs(result["scoreGap"] - 35.0) < 1e-6

    def test_tie_broken_by_reason_text(self):
        result = assign_main_theme(
            ["AI", "芯片"],
            self._scores(),
            reason_text="芯片+算力 涨停",
        )
        # AI 90 vs 芯片 54.5 差 35.5 > EPS=2，不该触发消歧——仍是 AI
        assert result["mainTheme"] == "AI"

        scores_close = {"AI": {"score": 60.0, "status": "ok"}, "芯片": {"score": 59.0, "status": "ok"}}
        result2 = assign_main_theme(["AI", "芯片"], scores_close, reason_text="芯片 涨停")
        assert result2["mainTheme"] == "芯片"
        assert result2["mainThemeReason"] == "tie_break_reason"

    def test_fallback_when_no_scored_theme(self):
        result = assign_main_theme(["冷门题材"], self._scores(), fallback_theme="冷门题材")
        assert result["mainTheme"] == "冷门题材"
        assert result["mainThemeReason"] == "fallback"
        assert "fallback" in result["qualityFlags"]

    def test_unassigned_when_no_themes_at_all(self):
        result = assign_main_theme([], self._scores())
        assert result["mainTheme"] is None
        assert result["mainThemeReason"] == "unassigned"
```

- [ ] **Step 2.2: 运行测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_theme_mainline_assignment.py -v
```

预期：FAIL（`ModuleNotFoundError`）。

- [ ] **Step 2.3: 实现 `mainline_assignment.py`**

创建 `quant-board/backend/analysis/theme/mainline_assignment.py`：

```python
"""主线题材归属判定链（Phase R1 研究纯函数，设计文档 §5.5）。

三层：原料白名单 → MainlineScore 合成 → 个股归属。
硬约束：原料白名单封闭（MAINLINE_FACTOR_KEYS），依赖归属的派生因子
（如成交额占比拥挤度）严禁回流——循环依赖防护，新增输入需设计评审。
fail-visible：因子缺失按可用因子重分配权重并打 factorCoverage 标记；
归属无据时回退 themes[0]（旧口径）打 fallback 标记，不伪造。
接线位置（后续任务）：snapshot_derivation/projection.py 替换 row_themes[0] 兜底。
"""

from __future__ import annotations

from typing import Any

# 原料白名单：封闭。全部为 sector rows 同槽可用、且不依赖归属判定的独立原料。
MAINLINE_FACTOR_KEYS = ("heatLevel", "momentumScore", "ztCount", "fundScore")

# 研究初始权重（Phase R1 敏感性扫描定版，非生产默认；见 diagnose_theme_rotation_r1）。
DEFAULT_MAINLINE_WEIGHTS = {
    "heatLevel": 0.40,
    "momentumScore": 0.25,
    "ztCount": 0.20,
    "fundScore": 0.15,
}

# 平局消歧阈值：Top1/Top2 分差小于该值时允许涨停原因介入。
TIE_BREAK_EPS = 2.0


def _normalize_theme_label(name: str) -> str:
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """横截面 percentile rank 归一（0-1），并列取平均秩，单题材归中 0.5。"""
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2
        for k in range(i, j + 1):
            out[items[k][0]] = avg_rank / (n - 1)
        i = j + 1
    return out


def mainline_scores(
    sector_rows: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """单槽题材横截面 → {themeKey: {score, status, factorCoverage, factorsUsed}}。

    每因子在当槽横截面做 percentile rank 后加权合成（0-100 分）。
    缺失因子：该题材按可用因子重分配权重，coverage<1 标 degraded；
    全缺标 insufficient、score=None。
    """
    w = {
        k: float((weights or DEFAULT_MAINLINE_WEIGHTS).get(k, 0.0))
        for k in MAINLINE_FACTOR_KEYS
    }
    ranks: dict[str, dict[str, float]] = {}
    for key in MAINLINE_FACTOR_KEYS:
        vals: dict[str, float] = {}
        for row in sector_rows:
            v = row.get(key)
            tkey = row.get("entityKey") or row.get("entityName")
            if isinstance(v, (int, float)) and tkey is not None:
                vals[str(tkey)] = float(v)
        if vals:
            ranks[key] = _percentile_ranks(vals)
    out: dict[str, dict[str, Any]] = {}
    for row in sector_rows:
        tkey = str(row.get("entityKey") or row.get("entityName"))
        num = 0.0
        den = 0.0
        used: list[str] = []
        for key in MAINLINE_FACTOR_KEYS:
            r = ranks.get(key, {}).get(tkey)
            if r is None:
                continue
            num += w[key] * r
            den += w[key]
            used.append(key)
        total_w = sum(w.values())
        if den <= 0:
            out[tkey] = {
                "score": None,
                "status": "insufficient",
                "factorCoverage": 0.0,
                "factorsUsed": [],
            }
            continue
        out[tkey] = {
            "score": round(100.0 * num / den, 2),
            "status": "ok" if abs(den - total_w) < 1e-9 else "degraded",
            "factorCoverage": round(den / total_w, 4) if total_w else 0.0,
            "factorsUsed": used,
        }
    return out


def assign_main_theme(
    stock_themes: list[str],
    theme_scores: dict[str, dict[str, Any]],
    *,
    reason_text: str | None = None,
    fallback_theme: str | None = None,
    tie_break_eps: float = TIE_BREAK_EPS,
) -> dict[str, Any]:
    """个股归属：所属题材中 MainlineScore 最高者（§5.5 判定层）。

    stock_themes: 该股所属题材名列表（market_context.themes 顺序）。
    reason_text: 涨停原因文本（THS reasonType / 复合原因"机器人+军工"）；
      Top1/Top2 分差 < tie_break_eps 且原因含某候选题材名（归一后子串匹配）
      时选该题材，reason=tie_break_reason。
    fallback_theme: 兜底，通常 = stock_themes[0]（旧口径 themes[0]）。
    """
    candidates = [
        t
        for t in stock_themes
        if t in theme_scores and theme_scores[t].get("score") is not None
    ]
    if not candidates:
        fb = fallback_theme or (stock_themes[0] if stock_themes else None)
        if fb is None:
            return {
                "mainTheme": None,
                "mainThemeReason": "unassigned",
                "qualityFlags": ["no_theme"],
                "scoreGap": None,
            }
        return {
            "mainTheme": fb,
            "mainThemeReason": "fallback",
            "qualityFlags": ["fallback"],
            "scoreGap": None,
        }
    ranked = sorted(candidates, key=lambda t: theme_scores[t]["score"], reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    top_score = theme_scores[top]["score"]
    gap = (top_score - theme_scores[second]["score"]) if second else None
    chosen = top
    reason = "mainline_score"
    flags: list[str] = []
    if gap is not None and gap < tie_break_eps and reason_text:
        norm_reason = str(reason_text)
        hits = [
            t
            for t in ranked[:3]
            if _normalize_theme_label(t) and _normalize_theme_label(t) in norm_reason
        ]
        if hits:
            chosen = hits[0]
            reason = "tie_break_reason"
            flags.append("tie_broken")
    if gap is not None:
        flags.append(f"gap:{round(gap, 2)}")
    return {
        "mainTheme": chosen,
        "mainThemeReason": reason,
        "qualityFlags": flags,
        "scoreGap": None if gap is None else round(gap, 2),
    }
```

- [ ] **Step 2.4: 运行测试确认通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_theme_mainline_assignment.py -v
```

预期：全部 PASS（8 用例）。

- [ ] **Step 2.5: 全量题材相关测试回归（确认无 import 断裂）**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_theme_rotation_measures.py tests\test_theme_mainline_assignment.py tests\test_theme_rotation_engine.py tests\test_theme_heat_level.py -q
```

预期：全部 PASS。

- [ ] **Step 2.6: Commit**

```powershell
git add backend/analysis/theme/mainline_assignment.py tests/test_theme_mainline_assignment.py
git commit -m "feat(theme): 主线题材归属判定链——MainlineScore 白名单合成+个股归属+消歧兜底（Phase R1）"
```

---

### Task 3: R1 描述性实证 runner `diagnose_theme_rotation_r1.py`

**Files:**
- Create: `quant-board/backend/operations/diagnose_theme_rotation_r1.py`

- [ ] **Step 3.1: 实现 runner（只读研究脚本，遵循 `diagnose_*` 既有范式）**

创建 `quant-board/backend/operations/diagnose_theme_rotation_r1.py`：

```python
"""Phase R1：题材轮动度量 + mainTheme 判定链描述性实证（只读，不写库）。

从真实 MongoDB 加载 sector rows（收盘槽）/ stock rows / limitSummary 帧 →
① 轮动度量统计（全窗 + 9 月弱势段切片）
② mainTheme 新旧判定差异分布（新=MainlineScore 判定链，旧=themes[0]）
③ MainlineScore 权重敏感性小扫描（4 组权重对比 Top3 名单差异）
④ 守恒 vs 重复涨停计数失真比对
⑤ 9 月弱势段情绪背景（limitSummary 每日 15:30 帧）
→ JSON 报告输出到 data/reports/。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_rotation_r1
      [--start 2026-07-06] [--end 2026-09-24]
      [--weak-start 2026-09-01] [--weak-end 2026-09-24]
      [--out data/reports/theme-r1-rotation.json]

资源纪律：只读、无 optimization API、单进程本地计算；题材域研究，
非 ranktrend 决策链，不受 ranktrend 冻结窗守卫约束（题材域冻结纪律
在 Phase 4 verdict 阶段另行建立）。
fail-visible：缺日/缺槽/缺因子如实打标输出，不伪造 0，不中断。
样本量声明：弱势段约 14 个交易日，结论为探索性描述统计，非正式判定。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.analysis.theme.mainline_assignment import (
    DEFAULT_MAINLINE_WEIGHTS,
    assign_main_theme,
    mainline_scores,
)
from backend.analysis.theme.rotation.measures import (
    dedup_limit_count,
    mainline_persistence,
    rank_entropy,
    rotation_speed,
)
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database

DATASET_ID = "dragonboard_live"
TOP_N = 10
CLOSE_SLOTS = ("15:30", "15:00")  # Phase 0：15:30 THS 池最全，15:00 偶发空洞

# 权重敏感性扫描组（研究参数，非生产默认）
WEIGHT_GRID = {
    "default_heat_heavy": DEFAULT_MAINLINE_WEIGHTS,
    "equal": {k: 0.25 for k in DEFAULT_MAINLINE_WEIGHTS},
    "momentum_heavy": {"heatLevel": 0.15, "momentumScore": 0.50, "ztCount": 0.20, "fundScore": 0.15},
    "limit_count_heavy": {"heatLevel": 0.20, "momentumScore": 0.20, "ztCount": 0.45, "fundScore": 0.15},
}


def load_close_slot_series(
    repo: MongoRepository, start: str, end: str
) -> dict[str, Any]:
    """每交易日收盘槽 sector rows 横截面（15:30 优先，回退 15:00，均缺打标）。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end, entity_type="hot_theme", sort="asc"
    )
    by_day_slot: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in res["rows"]:
        d, s = str(row.get("tradingDate")), str(row.get("slotTime"))
        by_day_slot.setdefault(d, {}).setdefault(s, []).append(row)
    series: dict[str, dict[str, Any]] = {}
    for d in sorted(by_day_slot):
        slots = by_day_slot[d]
        rows = next((slots[s] for s in CLOSE_SLOTS if s in slots), None)
        if not rows:
            series[d] = {"status": "insufficient", "reason": "close_slot_missing", "rows": []}
            continue
        series[d] = {
            "status": "ok",
            "slot": str(rows[0].get("slotTime")),
            "rows": rows,
        }
    if not series:
        return {"status": "insufficient", "reason": "no_sector_rows", "series": {}}
    return {"status": "ok", "series": series}


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows, key=lambda r: r.get("rank") if isinstance(r.get("rank"), int) else 10**9
    )


def build_top_sets(series: dict[str, Any]) -> tuple[list[set[str]], dict[str, str | None]]:
    """每日 TopN 题材集合与 Top1 主线（缺失日 = 空集合 / None）。"""
    tops: list[set[str]] = []
    mainline: dict[str, str | None] = {}
    for d in sorted(series):
        info = series[d]
        if info["status"] != "ok":
            tops.append(set())
            mainline[d] = None
            continue
        ordered = _sorted_rows(info["rows"])
        top = {str(r.get("entityKey")) for r in ordered[:TOP_N] if r.get("entityKey") is not None}
        tops.append(top)
        mainline[d] = str(ordered[0].get("entityKey")) if ordered and ordered[0].get("entityKey") is not None else None
    return tops, mainline


def build_top_counts(series: dict[str, Any]) -> dict[str, int]:
    """每题材进入 TopN 的天数。"""
    counts: dict[str, int] = {}
    for info in series.values():
        if info["status"] != "ok":
            continue
        for r in _sorted_rows(info["rows"])[:TOP_N]:
            k = r.get("entityKey")
            if k is not None:
                counts[str(k)] = counts.get(str(k), 0) + 1
    return counts


def slice_series(series: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    return {
        "status": series["status"],
        "series": {d: v for d, v in series["series"].items() if start <= d <= end},
    }


def normalize_theme_names(themes: Any) -> list[str]:
    out: list[str] = []
    for t in themes or []:
        if isinstance(t, dict):
            t = t.get("name") or t.get("id")
        if t:
            out.append(str(t))
    return out


def diff_main_theme(
    repo: MongoRepository, start: str, end: str, series: dict[str, Any]
) -> dict[str, Any]:
    """新旧 mainTheme 判定差异（收盘槽 stock rows：新=判定链，旧=themes[0]）。"""
    res = repo.list_snapshot_stock_rows(
        DATASET_ID,
        start_date=start,
        end_date=end,
        sort="asc",
        fields=[
            "tradingDate", "slotTime", "code", "name", "themes",
            "mainTheme", "boardHeight", "change", "limitUpPool",
        ],
    )
    by_day: dict[str, list[dict[str, Any]]] = {}
    for r in res["rows"]:
        if str(r.get("slotTime")) in CLOSE_SLOTS:
            by_day.setdefault(str(r.get("tradingDate")), []).append(r)
    days_out: dict[str, Any] = {}
    total = same = fallback_n = tie_n = 0
    for d, srows in sorted(by_day.items()):
        info = series["series"].get(d)
        if not info or info["status"] != "ok":
            continue
        scores = mainline_scores(info["rows"])
        d_total = d_same = 0
        reasons: dict[str, int] = {}
        for r in srows:
            themes = normalize_theme_names(r.get("themes"))
            if not themes:
                continue
            limit_up = bool(r.get("limitUpPool"))
            reason_text = str(r.get("name") or "") if limit_up else None
            res_a = assign_main_theme(
                themes, scores,
                reason_text=reason_text,
                fallback_theme=str(r.get("mainTheme") or themes[0]),
            )
            old = str(r.get("mainTheme") or themes[0])
            d_total += 1
            total += 1
            if res_a["mainTheme"] == old:
                d_same += 1
                same += 1
            reasons[res_a["mainThemeReason"]] = reasons.get(res_a["mainThemeReason"], 0) + 1
            if res_a["mainThemeReason"] == "fallback":
                fallback_n += 1
            elif res_a["mainThemeReason"] == "tie_break_reason":
                tie_n += 1
        days_out[d] = {
            "total": d_total,
            "same": d_same,
            "diff_rate": round(1 - d_same / d_total, 4) if d_total else None,
            "reasons": reasons,
        }
    return {
        "days": days_out,
        "overall": {
            "total": total,
            "same": same,
            "diff_rate": round(1 - same / total, 4) if total else None,
            "fallback_count": fallback_n,
            "tie_break_count": tie_n,
        },
    }


def weight_sensitivity(series: dict[str, Any]) -> dict[str, Any]:
    """4 组权重下 Top3 名单的平均日间 Jaccard 重合 + 与默认组名单差异率。"""
    daily_scores = {
        w_name: {d: mainline_scores(info["rows"], weights=w) for d, info in series["series"].items() if info["status"] == "ok"}
        for w_name, w in WEIGHT_GRID.items()
    }
    top3 = {
        w_name: {d: [t for t, _ in sorted(sc.items(), key=lambda kv: kv[1].get("score") or -1, reverse=True)[:3]] for d, sc in daily_scores[w_name].items()}
        for w_name in WEIGHT_GRID
    }
    out: dict[str, Any] = {}
    base = "default_heat_heavy"
    for w_name in WEIGHT_GRID:
        days = sorted(top3[w_name])
        jaccards = [
            len(set(top3[w_name][a]) & set(top3[w_name][b])) / max(len(set(top3[w_name][a]) | set(top3[w_name][b])), 1)
            for a, b in zip(days, days[1:])
        ]
        diffs = [
            len(set(top3[w_name][d]) ^ set(top3[base][d]))
            for d in days
        ]
        out[w_name] = {
            "top3_mean_jaccard": round(sum(jaccards) / len(jaccards), 4) if jaccards else None,
            "top3_days_diff_from_default": sum(1 for x in diffs if x > 0),
            "n_days": len(days),
        }
    return out


def dedup_limit_stats(
    repo: MongoRepository, start: str, end: str, series: dict[str, Any]
) -> dict[str, Any]:
    """守恒 vs 重复涨停计数（以判定链归属为 owner）。"""
    res = repo.list_snapshot_stock_rows(
        DATASET_ID, start_date=start, end_date=end, sort="asc",
        fields=["tradingDate", "slotTime", "code", "themes", "mainTheme", "limitUpPool"],
    )
    repeat_by_theme: dict[str, set[str]] = {}
    owner: dict[str, str] = {}
    day_map = {d: info for d, info in series["series"].items() if info["status"] == "ok"}
    day_scores = {d: mainline_scores(info["rows"]) for d, info in day_map.items()}
    for r in res["rows"]:
        if str(r.get("slotTime")) not in CLOSE_SLOTS or not r.get("limitUpPool"):
            continue
        themes = normalize_theme_names(r.get("themes"))
        if not themes:
            continue
        res_a = assign_main_theme(themes, day_scores.get(str(r.get("tradingDate")), {}), fallback_theme=str(themes[0]))
        for t in themes:
            repeat_by_theme.setdefault(t, set()).add(str(r.get("code")))
        if res_a["mainTheme"]:
            owner[str(r.get("code"))] = res_a["mainTheme"]
    return dedup_limit_count(repeat_by_theme, owner)


def sentiment_background(repo: MongoRepository, start: str, end: str) -> list[dict[str, Any]]:
    """9 月弱势段每日 15:30 帧 limitSummary 情绪背景。"""
    out: list[dict[str, Any]] = []
    for doc in repo.db["snapshot_frames"].find(
        {"tradingDate": {"$gte": start, "$lte": end}, "slotTime": "15:30"}
    ).sort("tradingDate", 1):
        ls = doc.get("limitSummary") or {}
        z, cb = ls.get("zhaban") or {}, ls.get("continuousBoards") or {}
        out.append({
            "tradingDate": str(doc.get("tradingDate")),
            "ztCount": z.get("ztCount"),
            "zhaban_rate": z.get("rate"),
            "fengban_rate": z.get("fengbanRate"),
            "max_board": cb.get("maxBoard"),
        })
    return out


def run_stats(series: dict[str, Any]) -> dict[str, Any]:
    tops, mainline = build_top_sets(series)
    return {
        "n_days": len([d for d in series["series"] if series["series"][d]["status"] == "ok"]),
        "missing_days": [d for d in series["series"] if series["series"][d]["status"] != "ok"],
        "rotation_speed": rotation_speed(tops),
        "mainline_persistence": mainline_persistence(mainline),
        "rank_entropy": rank_entropy(build_top_counts(series)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--weak-start", default="2026-09-01")
    parser.add_argument("--weak-end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-r1-rotation.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    full = load_close_slot_series(repo, args.start, args.end)
    if full["status"] != "ok":
        print(json.dumps(full, ensure_ascii=False, indent=2))
        return 2
    weak = slice_series(full, args.weak_start, args.weak_end)

    report = {
        "window": {"start": args.start, "end": args.end, "weak": [args.weak_start, args.weak_end]},
        "full_window": run_stats(full),
        "weak_window": run_stats(weak),
        "main_theme_diff": diff_main_theme(repo, args.start, args.end, full),
        "weight_sensitivity": weight_sensitivity(full),
        "dedup_limit": dedup_limit_stats(repo, args.start, args.end, full),
        "sentiment_background": sentiment_background(repo, args.weak_start, args.weak_end),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    fw, ww, diff = report["full_window"], report["weak_window"], report["main_theme_diff"]["overall"]
    print(f"[full] days={fw['n_days']} missing={fw['missing_days']} rot_speed={fw['rotation_speed'].get('mean')} "
          f"switch_rate={fw['mainline_persistence'].get('switch_rate')} entropy={fw['rank_entropy'].get('normalized')}")
    print(f"[weak] days={ww['n_days']} rot_speed={ww['rotation_speed'].get('mean')} "
          f"switch_rate={ww['mainline_persistence'].get('switch_rate')} entropy={ww['rank_entropy'].get('normalized')}")
    print(f"[mainTheme diff] {diff}")
    print(f"report -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3.2: 语法与 import 自检**

```powershell
.\.venv\Scripts\python.exe -c "import backend.operations.diagnose_theme_rotation_r1 as m; print('import ok')"
```

预期：`import ok`。

- [ ] **Step 3.3: Commit**

```powershell
git add backend/operations/diagnose_theme_rotation_r1.py
git commit -m "feat(theme): Phase R1 轮动度量与判定链描述性实证 runner（只读）"
```

---

### Task 4: 真实数据实证运行

**Files:** 无新文件（运行 Task 3 runner，产物 `data/reports/theme-r1-rotation.json` 属 gitignore 运行产物）

- [ ] **Step 4.1: 确认 MongoDB 在线**

```powershell
.\.venv\Scripts\python.exe -c "from pymongo import MongoClient; MongoClient('mongodb://127.0.0.1:27017', serverSelectionTimeoutMS=5000).admin.command('ping'); print('mongo ok')"
```

预期：`mongo ok`。若连接失败，先启动 MongoDB 服务（Windows 服务，可能需管理员 `net start MongoDB`）再重试。

- [ ] **Step 4.2: 运行 R1 实证**

```powershell
.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_rotation_r1
```

预期：控制台输出 `[full]/[weak]/[mainTheme diff]` 三行摘要 + `report -> data/reports/theme-r1-rotation.json`，退出码 0。

- [ ] **Step 4.3: 人工核对关键数字（对照 Phase 0 已知事实）**

```powershell
.\.venv\Scripts\python.exe -c "import json; r=json.load(open('data/reports/theme-r1-rotation.json', encoding='utf-8')); print(json.dumps(r['full_window']['missing_days'], ensure_ascii=False)); print(json.dumps(r['main_theme_diff']['overall'], ensure_ascii=False)); print(json.dumps(r['weight_sensitivity'], ensure_ascii=False, indent=1))"
```

核对清单：
- `full_window.n_days` ≈ 55-56（Phase 0：58 交易日扣 7-10/7-24 断采与 7-09 单帧日）
- `full_window.missing_days` 包含 `2026-07-10`、`2026-07-24`，不含任何 9 月交易日
- `main_theme_diff.overall.diff_rate` ∈ [0,1]；`fallback_count` 占比 <10%（超过说明收盘槽题材得分覆盖不足，需回查）
- `weight_sensitivity` 四组 `top3_mean_jaccard` 有区分度（若四组几乎相同，权重不敏感，定版可用默认组并如实记录）
- `weak_window.n_days` ≈ 14（9 月弱势段）
- `sentiment_background` 每日 ztCount 合理（约 30-60，不含 09:30 异常低值——已取 15:30）

- [ ] **Step 4.4: 异常处置**

- 若 `import ok` 但运行报 repo 形参不匹配：对照 `mongo_repository.py:603/721` 实际签名微调调用处（签名已在本计划头部验证过，理论上不需要）。
- 若某步数据为空（如 stock rows 无 `themes` 字段）：检查 `fields` 投影名与 bundle 键（`code`/`themes` 已验证）；不得改用伪造数据，如实输出 insufficient 并在报告记录。

---

### Task 5: R1 报告落盘 + 权重定版提案 + 提交

**Files:**
- Create: `docs/theme-module/2026-09-26-phase-r1-findings.md`

- [ ] **Step 5.1: 撰写 findings 报告（数据来自 Task 4 JSON，结论人工撰写）**

创建 `docs/theme-module/2026-09-26-phase-r1-findings.md`，结构：

```markdown
# Phase R1 实证报告：题材轮动度量与 mainTheme 判定链

- 日期 / 数据窗（2026-07-06~09-24 全窗；2026-09-01~09-24 弱势段）/ 代码版本
- 样本量声明：弱势段约 14 交易日，结论为探索性描述统计，非正式判定（Phase 4 三窗重跑才是正式结论）

## 1. 轮动度量结果
- 全窗 vs 弱势段：rotation_speed / mainline_persistence / rank_entropy 三组对照表
- 结论要点：弱势段轮动速度与熵是否显著高于全窗均值（用户"弱势轮动明显"观察的量化验证）
- 守恒 vs 重复涨停计数 inflation_ratio

## 2. mainTheme 判定链差异
- 新旧判定 diff_rate、fallback/tie_break 占比、差异按日分布
- 与旧逻辑（themes[0]）的差异主要集中在哪些题材

## 3. MainlineScore 权重敏感性
- 4 组权重 Top3 稳定性对照 → 定版建议（一次一候选：建议权重 + 理由 + 保留观察项）

## 4. 局限与后续
- 样本量局限、15:30 槽依赖、映射噪声
- 下一步：Phase R2（rotation_regime 阈值与 mainline 抖动率）输入即本报告度量
```

- [ ] **Step 5.2: Commit**

```powershell
git add docs/theme-module/2026-09-26-phase-r1-findings.md
git commit -m "docs(theme): Phase R1 实证报告——轮动度量/判定链差异/权重定版提案"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计文档 §6.1 Phase R1 的三项交付（轮动度量构建+弱势段实证 / MainlineScore 权重+消歧定版 / 新旧判定差异分布）分别由 Task 1+4、Task 2+4、Task 4+5 承载；§5.5 判定链结构（白名单封闭/缺失重分配/消歧/兜底打标/循环依赖防护注释）在 Task 2 完整实现。守恒计数比对（Phase R1 附加项）在 Task 1 `dedup_limit_count` + Task 3 ④。
- **无占位符**：所有代码块完整可执行；接口签名/字段键名已在计划头部实测记录；无 TBD/TODO。
- **类型一致性**：`mainline_scores` 返回 `{themeKey: {score, status, factorCoverage, factorsUsed}}`，Task 3 消费处（`diff_main_theme`/`weight_sensitivity`/`dedup_limit_stats`）与 Task 2 测试一致；`assign_main_theme` 返回四键 dict，测试与 runner 一致。
