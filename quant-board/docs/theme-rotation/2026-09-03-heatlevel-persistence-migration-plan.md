# heatLevel 落库与热度口径统一迁移 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** heatLevel（0-100 rank 百分位）成为题材热度相对分的单一事实源：heat 引擎生成 → sector row 落库 → 投影读出 → momentum/trend/rotation/backtest/前端统一消费，替代 `>100` 启发式。

**Architecture:** 新建共享纯函数模块 `backend/analysis/theme/heat_level.py`（生成 + 口径解释唯一实现）；落库行透传 heatLevel（数值或显式 None）；消费端按「heatLevel key 存在 → 直接用 / key 缺失 → 按 metadata.factorVersion 口径回退 / >100 一律缺失」三分支统一读取；前端约 12 处 0-100 阈值消费点从绝对值 heatScore 切换到 heatLevel，缺失传播不伪装 0。

**Tech Stack:** Python 3.11 + pytest（quant-board）、Vue 3 + TS + Vitest（根项目）、MongoDB 主库 + SQL/Supabase 备份。

**Spec:** `quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md`（本计划按其 §4 设计展开；执行者需同时读设计文档）。

## Global Constraints

- **统一消费规则（design §4.2，逐条实现不得偏离）**：
  1. `heatLevel` key 存在 → 数值直接用（0-100，含 SQL varchar 回读的字符串数字）；显式 `None`/非法值 = 诚实缺失，**不回退**。
  2. key 不存在（旧落库行）→ 看口径标记（`heatFactorVersion` 或 `metadata.factorVersion`）：`theme-market-v1` 或未标记 且 `heatScore <= 100` → heatScore 当相对分回退；`theme-market-v2` → **不回退**。
  3. `heatScore > 100` → 无论标记一律缺失（最后兜底）。返回值一律 clamp 到 [0, 100]；缺失返回 None/null，不伪装 0。
- **golden 不可变**：`theme_trend_ts_golden_v13.json`、`theme_heat_market_golden_v2.json` 禁止修改；新建 v14 / v3 fixture。
- **fail-visible**：无质量阻断；heatLevel 缺失只降级 + 标记，原始 heatScore 照落库；禁止 `?? 0` / `|| 0` 伪装缺失为 0（派生加权分中 null→0 合成必须在代码注释里写明理由）。
- **JS 陷阱**：`null < 20` 在 JS 中为 `true`（null 强转 0）。所有 `<` 阈值判断必须写 `value != null && value < 20`，禁止裸写 `value < 20`。
- **存储**：MongoDB 主库 schemaless 透传，零 schema 成本；SQL/Supabase `heat_level` 列是 varchar(40)，数值写入必须转字符串（读侧 `_num_or_none` 可解析）。
- **字段只增不删不改名**：sector row / stock row / API 输出既有字段全部保留（AI_COLLABORATION 硬约束 16）。`ThemePanelSummary.heatLevel`（string 档位标签）保留，新增 `heatLevelScore`（number）承载相对分。
- **禁止**：新增 MongoDB 集合/API、shadow/live 双跑、独立进程、环境变量、回滚历史落库行、修改 heat 公式与 `FACTOR_VERSION`。
- **测试位置**：后端 `quant-board/tests/test_*.py`；根项目前端 `src/**/__tests__/*.test.ts`。
- **验证命令**：
  - 后端：`cd quant-board && ./.venv/Scripts/python.exe -m pytest <file> -v`（全量收口用 `-m pytest`）。
  - 前端：根目录 `pnpm test`、`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- **提交**：每任务一个 commit，格式 `feat(theme): ...` / `test(theme): ...`，与近期历史风格一致。**禁止 `git add -A` / `git add .`**（工作区存在未跟踪的设计/计划文档等他人文件），一律显式路径。
- **执行前置（Step 0）**：实施开始前先把 design 与 plan 两份文档入库：
  `git add quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-plan.md && git commit -m "docs(theme): heatLevel 落库迁移设计与实施计划（评审修订版）"`

---

## 阶段 A：后端（可独立上线）

### Task 1: 共享模块 heat_level.py（生成 + 口径解释唯一实现）

**Files:**
- Create: `quant-board/backend/analysis/theme/heat_level.py`
- Test: `quant-board/tests/test_theme_heat_level.py`

**Interfaces:**
- Produces（后续所有任务消费）:
  - `rank_percentile(rank: int, ranked_total: int) -> float | None`
  - `attach_heat_levels(factors: list[dict[str, Any]]) -> None`（就地附加 `heatLevel` key）
  - `heat_caliber_of(row: dict[str, Any]) -> str`（读 `heatFactorVersion` 优先，其次 `metadata.factorVersion`，无标记返回 `""`）
  - `resolve_heat_level(row: dict[str, Any]) -> float | None`（design §4.2 三分支唯一实现）
  - 常量 `HEAT_CALIBER_V1 = "theme-market-v1"`、`HEAT_CALIBER_V2 = "theme-market-v2"`

- [ ] **Step 1: 写失败测试**

```python
# quant-board/tests/test_theme_heat_level.py
"""heatLevel（0-100 rank 百分位）生成与统一消费规则的锁定测试。

2026-09 heatLevel 落库迁移（design §4.2）：resolve_heat_level 是口径解释的唯一实现，
消费方（trend/momentum/rotation/backtest）不得再各自维护 ">100 视为缺失"启发式。
"""

from __future__ import annotations

from backend.analysis.theme.heat_level import (
    attach_heat_levels,
    heat_caliber_of,
    rank_percentile,
    resolve_heat_level,
)


def test_rank_percentile_bounds() -> None:
    assert rank_percentile(1, 10) == 100.0
    assert rank_percentile(10, 10) == 10.0
    assert rank_percentile(3, 8) == 75.0
    assert rank_percentile(0, 10) is None
    assert rank_percentile(1, 0) is None


def test_attach_heat_levels_marks_missing_explicitly() -> None:
    factors = [
        {"themeId": "AI", "heatScore": 2000, "rank": 1},
        {"themeId": "POWER", "heatScore": None, "rank": 0},
        {"themeId": "BANK", "heatScore": 500, "rank": 2},
    ]
    attach_heat_levels(factors)
    assert [f["heatLevel"] for f in factors] == [100.0, None, 50.0]
    # 降级帧：rank 全 0 → 全部显式 None，不回退 heatScore（2026-09 审计 M3 语义）
    degraded = [{"themeId": "AI", "heatScore": 85, "rank": 0}]
    attach_heat_levels(degraded)
    assert degraded[0]["heatLevel"] is None


def test_heat_caliber_of_reads_factor_version_then_metadata() -> None:
    assert heat_caliber_of({"heatFactorVersion": "theme-market-v2"}) == "theme-market-v2"
    assert heat_caliber_of({"metadata": {"factorVersion": "theme-market-v1"}}) == "theme-market-v1"
    assert heat_caliber_of({"metadata": {}}) == ""
    assert heat_caliber_of({}) == ""
    assert heat_caliber_of({"metadata": "bad"}) == ""


def test_resolve_rule1_heat_level_key_present() -> None:
    # key 存在：数值直接用（含 SQL varchar 回读的字符串数字）
    assert resolve_heat_level({"heatLevel": 96.3}) == 96.3
    assert resolve_heat_level({"heatLevel": "96.3"}) == 96.3
    # 显式 None / 非法值 = 诚实缺失，不回退 heatScore（M3：≤100 绝对值是冷题材人气总和）
    assert resolve_heat_level({"heatLevel": None, "heatScore": 85}) is None
    assert resolve_heat_level({"heatLevel": "abc", "heatScore": 85}) is None
    # 历史浏览器档位标签字符串（"热门"）不是数值，按缺失（评审 L2 混合行用例）
    assert resolve_heat_level({"heatLevel": "热门", "heatScore": 85}) is None


def test_resolve_rule2_missing_key_falls_back_by_caliber() -> None:
    assert resolve_heat_level({"heatScore": 85}) == 85.0  # 未标记：v1 语义回退（残留歧义 design §4.2 显式接受）
    assert resolve_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v1"}}) == 85.0
    assert resolve_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v1"}) == 85.0
    # v2 标记：绝对值口径不回退（M1 边界窗口消除）
    assert resolve_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v2"}}) is None
    assert resolve_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v2"}) is None


def test_resolve_rule3_absolute_heat_always_missing() -> None:
    assert resolve_heat_level({"heatScore": 2000}) is None
    assert resolve_heat_level({"heatScore": 2000, "metadata": {"factorVersion": "theme-market-v1"}}) is None
    assert resolve_heat_level({}) is None
    assert resolve_heat_level({"heatScore": "abc"}) is None


def test_resolve_clamps_to_0_100() -> None:
    assert resolve_heat_level({"heatLevel": 120}) == 100.0
    assert resolve_heat_level({"heatLevel": -5}) == 0.0
    assert resolve_heat_level({"heatScore": -5, "metadata": {"factorVersion": "theme-market-v1"}}) == 0.0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_level.py -v`
Expected: FAIL（`ModuleNotFoundError: backend.analysis.theme.heat_level`）

- [ ] **Step 3: 实现共享模块**

```python
# quant-board/backend/analysis/theme/heat_level.py
"""题材热度相对分（heatLevel，0-100 rank 百分位）的生成与统一解释。

2026-09 heatLevel 落库迁移（design:
docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md）：
- heatScore 是 KPL 人气总和（绝对值，热门题材可达数千，theme-market-v2）；
- 0-100 相对分统一由 heatLevel 承载（rank1 → 100）；
- 本模块是口径解释的唯一实现，消费方（trend/momentum/rotation/backtest）
  不得再各自维护 ">100 视为缺失" 的启发式。
"""
from __future__ import annotations

import math
from typing import Any

HEAT_CALIBER_V1 = "theme-market-v1"
HEAT_CALIBER_V2 = "theme-market-v2"


def _num_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def rank_percentile(rank: int, ranked_total: int) -> float | None:
    """rank 百分位（0-100，rank1 → 100）；rank 或总数无效时 None。"""
    if rank <= 0 or ranked_total <= 0:
        return None
    return round((1 - (rank - 1) / ranked_total) * 100, 1)


def attach_heat_levels(factors: list[dict[str, Any]]) -> None:
    """按 rank 百分位就地附加 heatLevel（rank1 → 100）。

    无热度（heatScore None）或无 rank（rank=0，降级帧）的 factor 显式置 None，
    不回退 heatScore（M3：≤100 绝对值是冷题材人气总和，不是相对分）。"""
    ranked_total = sum(1 for factor in factors if _int_or_zero(factor.get("rank")) > 0)
    for factor in factors:
        if factor.get("heatScore") is None:
            factor["heatLevel"] = None
            continue
        factor["heatLevel"] = rank_percentile(_int_or_zero(factor.get("rank")), ranked_total)


def heat_caliber_of(row: dict[str, Any]) -> str:
    """落库行/因子的热度口径标记：heatFactorVersion 优先，其次 metadata.factorVersion；无标记返回 ""。"""
    version = row.get("heatFactorVersion")
    if isinstance(version, str) and version.strip():
        return version.strip()
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("factorVersion") or "").strip()
        if value:
            return value
    return ""


def resolve_heat_level(row: dict[str, Any]) -> float | None:
    """heatLevel 统一消费规则（design §4.2 三分支，全部消费点必须走这里）：

    1. heatLevel key 存在 → 数值直接用（0-100，含 SQL varchar 回读的字符串数字）；
       显式 None / 非法值 = 诚实缺失，不回退。
    2. key 不存在（旧落库行）→ 按口径标记回退：theme-market-v1 或未标记 且
       heatScore <= 100 → heatScore 当相对分；theme-market-v2 → 不回退。
    3. heatScore > 100 → 一律缺失（最后兜底）。

    返回值 clamp 到 [0, 100]；缺失返回 None，不伪装 0。"""
    if "heatLevel" in row:
        numeric = _num_or_none(row.get("heatLevel"))
        if numeric is None:
            return None
        return max(0.0, min(100.0, numeric))
    numeric = _num_or_none(row.get("heatScore"))
    if numeric is None or numeric > 100.0:
        return None
    if heat_caliber_of(row) in ("", HEAT_CALIBER_V1):
        return max(0.0, min(100.0, numeric))
    return None
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_level.py -v`
Expected: PASS（7 个测试）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme/heat_level.py quant-board/tests/test_theme_heat_level.py
git commit -m "feat(theme): 新增 heat_level 共享模块（rank 百分位生成 + 4.2 口径三分支解释）"
```

---

### Task 2: heat 引擎输出 heatLevel + heat golden v3

**Files:**
- Modify: `quant-board/backend/analysis/theme/heat.py`（`_rank_and_summarize`，rank 赋值块之后）
- Create: `quant-board/tests/fixtures/theme_heat_market_golden_v3.json`（复制 v2，不可改 v2）
- Modify: `quant-board/tests/test_theme_heat_engine.py`（fixture 路径 v2 → v3）

**Interfaces:**
- Consumes: Task 1 `attach_heat_levels`
- Produces: `compute_theme_heat` 返回快照的 `factors[]` 每项带 `heatLevel: float | None`（key 恒存在）；`factorVersion` 保持 `theme-market-v2` 不变。

- [ ] **Step 1: 写失败测试（golden v3 fixture）**

复制 `quant-board/tests/fixtures/theme_heat_market_golden_v2.json` 为 `theme_heat_market_golden_v3.json`，做且仅做以下修改：
- `caseId` 改为 `theme_heat_market_v3_001`（仅 fixture 自述字段）；
- `expected.factors[]` 中每个 factor 增加 `"heatLevel"`：AI（rank 1，唯一 rank>0）→ `100.0`；POWER（heatScore null，rank 0）→ `null`。
- `input` 与其余 expected 字段一律不动。

修改 `quant-board/tests/test_theme_heat_engine.py`：将 fixture 文件名引用 `"theme_heat_market_golden_v2.json"` 改为 `"theme_heat_market_golden_v3.json"`（用 `rg "theme_heat_market_golden_v2" quant-board/tests` 定位，仅应有一处），并更新该测试 docstring：注明 v3 起锁定 `factors[].heatLevel`（v2 不可变）。

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_engine.py -v`
Expected: FAIL（引擎输出无 `heatLevel` key，与 expected 不等）

- [ ] **Step 3: 实现**

`quant-board/backend/analysis/theme/heat.py` 顶部 import 区（`FACTOR_VERSION` 定义之前）加：

```python
from backend.analysis.theme.heat_level import attach_heat_levels
```

`_rank_and_summarize` 中，在 rank 赋值 if/else 块结束之后（`factors = eligible + ineligible` 之后、`kpl_available_count = sum(...)` 之前）插入：

```python
    # heatLevel（0-100 rank 百分位相对分）与 rank 同步附加：无热度/无 rank 的 factor
    # 显式 None（不回退 heatScore 绝对值），见 analysis/theme/heat_level.py。
    attach_heat_levels(factors)
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_engine.py tests/test_theme_heat_level.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 heat 链**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_service.py tests/test_theme_heat_api.py tests/test_theme_trend_heat_level.py -v`
Expected: PASS（heat 快照多出 heatLevel 字段不影响服务/API 断言；若有断言快照全等形状的测试失败，按「新增字段」更新该断言，不得删除字段）

- [ ] **Step 6: Commit**

```bash
git add quant-board/backend/analysis/theme/heat.py quant-board/tests/fixtures/theme_heat_market_golden_v3.json quant-board/tests/test_theme_heat_engine.py
git commit -m "feat(theme): heat 引擎 factor 输出 heatLevel（rank 百分位）+ golden v3"
```

---

### Task 3: trend.py 接入共享模块 + 口径标记透传 + ThemeFactorFrame 字段

**Files:**
- Modify: `quant-board/backend/analysis/theme/trend.py`（import 区、`_ts_heat_level` :433-447、`_attach_heat_levels` :450-462 删除、`_build_factor` :580-604、`ThemeFactorFrame` :33-48）
- Test: `quant-board/tests/test_theme_trend_heat_level.py`（追加测试）

**Interfaces:**
- Consumes: Task 1 `resolve_heat_level` / `attach_heat_levels`
- Produces:
  - `ThemeFactorFrame` 新增字段 `heatLevel: float | None = None`、`heatFactorVersion: str | None = None`（replay_typed / 研究帧 / `_to_typed_result` 自动携带）。
  - `_build_factor` 产物 dict：sector 行有 `heatLevel` key → factor 带 `heatLevel`（数值或显式 None）；无 key → 不伪造 key。sector metadata 有 `factorVersion` → factor 带 `heatFactorVersion: str`。
  - `_ts_heat_level(factor)` 签名不变，行为切换为 `resolve_heat_level`（新增：v2 标记行不回退）。

- [ ] **Step 1: 写失败测试（追加到 test_theme_trend_heat_level.py 末尾）**

```python
def test_ts_heat_level_respects_caliber_marking() -> None:
    """落库口径标记（design §4.2 规则2）：v2 行不回退 heatScore；v1 行与未标记行 ≤100 回退。"""
    assert _ts_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v2"}}) is None
    assert _ts_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v1"}}) == 85.0
    assert _ts_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v2"}) is None
    # 未标记行维持既有行为（残留歧义按 v1 语义回退，design §4.2 显式接受）
    assert _ts_heat_level({"heatScore": 85}) == 85.0


def test_build_factor_propagates_persisted_heat_level_and_caliber() -> None:
    """sector 行 heatLevel/metadata.factorVersion 透传进 factor（tri-state：无 key 不伪造）。"""
    from backend.analysis.theme.trend import ThemeTrendConfig, _build_factor

    base = {
        "entityKey": "ai",
        "entityName": "人工智能",
        "rank": 1,
        "heatScore": 2000,
        "momentumScore": 50,
        "breadthScore": 50,
        "fundScore": 50,
        "leadershipScore": 50,
        "correlationScore": 50,
        "crowdingRisk": 30,
        "persistenceScore": 50,
    }
    marked = _build_factor(
        {**base, "heatLevel": 96.3, "metadata": {"factorVersion": "theme-market-v2"}},
        ThemeTrendConfig(),
    )
    assert marked["heatLevel"] == 96.3
    assert marked["heatFactorVersion"] == "theme-market-v2"

    explicit_none = _build_factor(
        {**base, "heatLevel": None, "metadata": {"factorVersion": "theme-market-v2"}},
        ThemeTrendConfig(),
    )
    assert explicit_none["heatLevel"] is None

    legacy = _build_factor(dict(base), ThemeTrendConfig())
    assert "heatLevel" not in legacy
    assert "heatFactorVersion" not in legacy


def test_replay_sector_rows_with_heat_level_and_caliber() -> None:
    """replay 端到端：sector 行携带 heatLevel + 口径标记时 factor 完整透传。"""
    frames = [
        {
            "snapshotId": "snap_heat_level",
            "timestamp": 100,
            "tradingDate": "2026-09-03",
            "stocks": [],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "rank": 1,
                    "heatScore": 2000,
                    "heatLevel": 96.3,
                    "momentumScore": 50,
                    "breadthScore": 50,
                    "fundScore": 50,
                    "leadershipScore": 50,
                    "correlationScore": 50,
                    "crowdingRisk": 30,
                    "persistenceScore": 50,
                    "metadata": {"factorVersion": "theme-market-v2"},
                }
            ],
        }
    ]

    result = ThemeTrendPythonEngine().replay(frames)

    factor = result["factors"][0]
    assert factor["heatLevel"] == 96.3
    assert factor["heatFactorVersion"] == "theme-market-v2"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_trend_heat_level.py -v`
Expected: 新增 3 个测试 FAIL（v2 标记行仍回退；`_build_factor` 不透传）

- [ ] **Step 3: 实现 trend.py**

3a. import 区加（`from backend.analysis.theme.heat import compute_theme_heat` 之后）：

```python
from backend.analysis.theme.heat_level import attach_heat_levels, resolve_heat_level
```

3b. `_attach_heat_levels`（:450-462）整个函数删除；原调用点 :292 `_attach_heat_levels(factors)` 改为：

```python
    attach_heat_levels(factors)
```

3c. `_ts_heat_level`（:433-447）整个函数体替换为委托（保留函数名，测试与内部调用点不变）：

```python
def _ts_heat_level(factor: dict[str, Any]) -> float | None:
    """题材热度相对分（0-100）：统一走 heat_level.resolve_heat_level（design §4.2 三分支）。

    保留独立函数名：sector rows 路径因子与 themeContext 因子共用此入口，
    test_theme_trend_heat_level 直接锁定其行为。"""
    return resolve_heat_level(factor)
```

3d. `ThemeFactorFrame`（:36-37 `heatScore` 字段之后）插入两个字段：

```python
    # heatLevel：0-100 rank 百分位相对分；None = 缺失（无热度/降级帧 rank 全 0）
    heatLevel: float | None = None
    # heatFactorVersion：热度口径标记（theme-market-v1/v2），透传落库行 metadata.factorVersion
    heatFactorVersion: str | None = None
```

3e. `_build_factor`（:602-604）——在 `factor["qualityFlags"] = _quality_flags(...)` 之后、`return factor` 之前插入：

```python
    sector_metadata = sector.get("metadata") if isinstance(sector.get("metadata"), dict) else {}
    # heatLevel 落库透传（tri-state）：sector 行有 key → 数值或显式 None；
    # 无 key（旧落库行）→ 不伪造 key，消费端按口径标记回退（heat_level.resolve_heat_level）。
    if "heatLevel" in sector:
        heat_level = _num_or_none(sector.get("heatLevel"))
        factor["heatLevel"] = _round(heat_level) if heat_level is not None else None
    caliber = str(sector_metadata.get("factorVersion") or "").strip()
    if caliber:
        factor["heatFactorVersion"] = caliber
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_trend_heat_level.py tests/test_theme_trend.py tests/test_theme_trend_storage.py -v`
Expected: PASS（v13 golden 走 themeContext 路径，`factor_fields` 白名单不含 heatLevel，不受影响）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme/trend.py quant-board/tests/test_theme_trend_heat_level.py
git commit -m "feat(theme): trend 接入 heat_level 统一口径 + 落库 heatLevel/口径标记透传"
```

---

### Task 4: trend golden v14（heatLevel 纳入白名单比对）

**Files:**
- Create: `quant-board/tests/fixtures/theme_trend_ts_golden_v14.json`（复制 v13，不可改 v13）
- Modify: `quant-board/tests/test_theme_trend.py`（fixture 路径 + `factor_fields` 白名单）

**Interfaces:**
- Consumes: Task 2/3（themeContext 路径 factors 已带 heatLevel）
- Produces: v14 golden 锁定 `expected.factors[].heatLevel`；`tests/test_theme_trend.py` 两个测试（:26-28、:66-68）指向 v14。

- [ ] **Step 1: 创建 v14 fixture**

复制 `quant-board/tests/fixtures/theme_trend_ts_golden_v13.json` 为 `theme_trend_ts_golden_v14.json`，做且仅做以下修改：
- `expected.factors[]` 每个 factor 增加 `"heatLevel"`：AI（rank 1；POWER 无 KPL heatScore None → rank 0，ranked_total=1）→ `100.0`；POWER → `null`。
- 若 v13 fixture 的 factors 多于 AI/POWER 两个，每个 factor 的 heatLevel 按 `round((1 - (rank - 1) / ranked_total) * 100, 1)` 计算（ranked_total = rank>0 的 factor 数）。
- `input` 与其余 expected 字段一律不动。

- [ ] **Step 2: 更新测试（先失败）**

`quant-board/tests/test_theme_trend.py`：
- :27 与 :67 两处 `"theme_trend_ts_golden_v13.json"` → `"theme_trend_ts_golden_v14.json"`；
- `factor_fields` 列表（:32-46）在 `"heatScore"` 之后插入 `"heatLevel"`；
- :24-25 注释更新为 v14 说明（v14：heatLevel 纳入白名单比对；v13 不可变）。

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_trend.py -v`
Expected: 先 FAIL（若 fixture 值与引擎输出不一致则修正 fixture 期望值，禁止改引擎）

- [ ] **Step 3: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_trend.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add quant-board/tests/fixtures/theme_trend_ts_golden_v14.json quant-board/tests/test_theme_trend.py
git commit -m "test(theme): trend golden bump v14（heatLevel 纳入白名单比对）"
```

---

### Task 5: collector factor_to_sector 落库 heatLevel + 派生白名单放行（同批改）

**Files:**
- Modify: `quant-board/backend/snapshot_collector/service.py`（`factor_to_sector` :95-131）
- Modify: `quant-board/backend/snapshot_derivation/projection.py`（`SECTOR_FACTOR_FIELDS` :15-32）
- Test: `quant-board/tests/test_theme_heat_collector_contract.py`

**Interfaces:**
- Consumes: Task 2（heat 快照 factors 带 heatLevel）
- Produces: sector row 透传 `heatLevel`（数值或显式 None）；factor 无该 key 时**不写 key**（tri-state，消费端按 `metadata.factorVersion` 回退）。`metadata` 现有字段不变（`factorVersion` :102 已有，无需改）。
- **为什么白名单必须同批改（评审 H1）**：`SECTOR_FACTOR_FIELDS`（`projection.py:15-32`）是派生层落库 sector row 的唯一字段白名单（:661-663 逐字段拷贝）；collector 透传的 heatLevel 若不在白名单，端到端落库行仍没有该字段，本任务断言永远落空。白名单只增不改，既有测试不受影响。

- [ ] **Step 1: 写失败测试**

`quant-board/tests/test_theme_heat_collector_contract.py`：
- `FakeThemeHeatService.__init__` 增加 `self.include_heat_level = True`；
- `get_snapshot` 返回的 factors 中 AI factor 增加 `"heatLevel": 100.0`，POWER factor 增加 `"heatLevel": None`；
- `get_snapshot` 组装返回 dict 前加：

```python
        if not self.include_heat_level:
            for factor in factors:
                factor.pop("heatLevel", None)
```

（需把 factors 列表先赋给局部变量 `factors` 再组装返回值。）
- `test_collector_builds_all_theme_sector_rows` 追加断言（captured bundle 是派生后产物，能端到端锁定"透传 + 白名单放行"两环）：

```python
    assert captured["sectorRows"][0]["heatLevel"] == 100.0
    assert captured["sectorRows"][1]["heatLevel"] is None
```

- 新增测试（文件末尾，两个）：

```python
def test_sector_factor_fields_whitelist_includes_heat_level() -> None:
    """SECTOR_FACTOR_FIELDS 是落库 sector row 的唯一字段白名单（projection.py :661-663
    逐字段拷贝），heatLevel 不放行则 collector 透传在端到端被剥掉（评审 H1）。"""
    from backend.snapshot_derivation.projection import SECTOR_FACTOR_FIELDS

    assert "heatLevel" in SECTOR_FACTOR_FIELDS
    assert "heatScore" in SECTOR_FACTOR_FIELDS
    assert "metadata" in SECTOR_FACTOR_FIELDS


def test_collector_omits_heat_level_key_when_factor_lacks_it() -> None:
    """factor 无 heatLevel key（迁移前数据形态）时 sector row 不伪造该 key（tri-state）。
    注意：白名单未放行前本测试平凡通过，作为实现后的回归锁定；RED 由上面两个断言承担。"""
    captured: dict[str, Any] = {}

    def normalize(request):
        captured.update(request.bundle)
        bundle = request.bundle
        return (
            type("Dataset", (), {"id": request.dataset_id})(),
            bundle["items"], bundle["frames"], bundle["stockRows"], bundle["sectorRows"],
            "test-key",
        )

    repo = FakeRepo()
    theme_service = FakeThemeHeatService()
    theme_service.include_heat_level = False
    service = SnapshotCollectorService(
        repo=repo, collect_fn=_collect, normalize_fn=normalize,
        quality_fn=lambda **kwargs: QualityResult(True, [], [], {"ok": 3, "failed": 0}),
        theme_heat_service=theme_service,
    )
    request = CollectorRunRequest(
        dataset_id="dragonboard_backend_shadow", snapshot_type="half_hour",
        trading_date="2026-06-11", slot_time="10:00", dry_run=True,
    )

    result = service.run_once(request)

    assert result.status == "dry_run"
    assert len(captured["sectorRows"]) == 2
    assert all("heatLevel" not in row for row in captured["sectorRows"])
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_collector_contract.py -v`
Expected: FAIL 两处——`test_collector_builds_all_theme_sector_rows` 追加的 heatLevel 断言（白名单剥字段）与 `test_sector_factor_fields_whitelist_includes_heat_level`；`test_collector_omits_heat_level_key_when_factor_lacks_it` 此时平凡通过（预期内）。

- [ ] **Step 3: 实现（两处）**

3a. `quant-board/backend/snapshot_collector/service.py` :95-131，把 `return { ...字面量... }` 改为先赋值再条件透传（字面量内容一字不改）：

```python
    sector = {
        "code": str(factor.get("themeId") or ""),
        "name": str(factor.get("themeName") or factor.get("themeId") or ""),
        "entityType": "hot_theme",
        "rank": factor.get("rank", 0),
        "heatScore": factor.get("heatScore"),
        # ...（heatScore 以下到 metadata 的字段与原字面量完全一致，逐行保留）...
        "metadata": metadata,
    }
    # heatLevel 落库（2026-09 design B2）：数值或显式 None 透传；factor 无该 key
    # （迁移前数据形态）时不伪造 key，消费端按 metadata.factorVersion 口径回退。
    if "heatLevel" in factor:
        sector["heatLevel"] = factor.get("heatLevel")
    return sector
```

3b. `quant-board/backend/snapshot_derivation/projection.py` `SECTOR_FACTOR_FIELDS` 中 `"heatScore",` 之后插入：

```python
    "heatLevel",
```

（只增不改；`snapshot_ingest_normalizer` 与 `importers.sector_rows_from_record` 走 `**raw` 全量透传无白名单，无需改。）

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_heat_collector_contract.py tests/test_snapshot_derivation.py tests/test_snapshot_collector_builder.py -v`
Expected: PASS（既有 test_theme_heat_and_risk_flags_derived_from_sector 不受影响——白名单只增）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/snapshot_collector/service.py quant-board/backend/snapshot_derivation/projection.py quant-board/tests/test_theme_heat_collector_contract.py
git commit -m "feat(theme): collector sector row 落库 heatLevel + 派生白名单放行（数值/显式 None/缺 key 三态）"
```

---

### Task 6: Mongo 读侧 hotThemes 投影白名单加 heatLevel

**Files:**
- Modify: `quant-board/backend/data/repositories/mongo_repository.py`（get_frames 投影 fields 字典 :228-253）
- Test: `quant-board/tests/test_storage_convergence.py`（追加）

**Interfaces:**
- Produces: Mongo `ranktrend+themes` 投影返回的 hot_theme 行带 `heatLevel`（行内有值时）；`metadata` 已在白名单（口径标记可读）。SQL 读侧 `local_sector_to_bundle_dict` 已含 `heatLevel`（:1288）且 None 剥离（:1309），无需改。

- [ ] **Step 1: 写失败测试（追加到 test_storage_convergence.py）**

```python
def test_hot_theme_projection_whitelist_includes_heat_level() -> None:
    """hotThemes 读侧投影白名单必须放行 heatLevel 与 metadata（口径标记）。"""
    from backend.data.repositories.mongo_repository import HOT_THEME_FRAME_FIELDS

    assert HOT_THEME_FRAME_FIELDS["heatLevel"] == 1
    assert HOT_THEME_FRAME_FIELDS["heatScore"] == 1
    assert HOT_THEME_FRAME_FIELDS["metadata"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_storage_convergence.py::test_hot_theme_projection_whitelist_includes_heat_level -v`
Expected: FAIL（`ImportError: HOT_THEME_FRAME_FIELDS`）

- [ ] **Step 3: 实现**

`quant-board/backend/data/repositories/mongo_repository.py`：把 get_frames 调用中 `fields=( {...内联字段字典...} if projection == "ranktrend+themes" else None )` 的内联字典（实际位于 :228-253，20 键：_id/snapshotId/tradingDate/slotTime/timestamp/captureMode/source/entityType/entityKey/entityName/entityCode/rowId/rank/heatScore/crowdingRisk/rotationState/metadata/themeId/code/name——评审 L-1 已逐一核对）提取为模块级常量（放在 class 定义之前），并在 `"heatScore": 1,` 后加 `"heatLevel": 1,`。下方常量与实际源码字段集一致，提取时逐键比对：

```python
# hotThemes 读侧投影白名单（ranktrend+themes）：heatLevel 2026-09 落库迁移加入；
# metadata（口径标记 factorVersion）已在白名单。
HOT_THEME_FRAME_FIELDS: dict[str, int] = {
    "_id": 0,
    "snapshotId": 1,
    "tradingDate": 1,
    "slotTime": 1,
    "timestamp": 1,
    "captureMode": 1,
    "source": 1,
    "entityType": 1,
    "entityKey": 1,
    "entityName": 1,
    "entityCode": 1,
    "rowId": 1,
    "rank": 1,
    "heatScore": 1,
    "heatLevel": 1,
    "crowdingRisk": 1,
    "rotationState": 1,
    "metadata": 1,
    "themeId": 1,
    "code": 1,
    "name": 1,
}
```

原调用点改为：

```python
                fields=(
                    HOT_THEME_FRAME_FIELDS
                    if projection == "ranktrend+themes"
                    else None
                ),
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_storage_convergence.py tests/test_theme_database.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/data/repositories/mongo_repository.py quant-board/tests/test_storage_convergence.py
git commit -m "feat(theme): Mongo hotThemes 读侧投影白名单放行 heatLevel"
```

---

### Task 7: momentum 序列与角色判定吃 heatLevel + 量纲常量参数化

**Files:**
- Modify: `quant-board/backend/analysis/theme/momentum.py`（常量区 :14-22、`build_theme_strength_series` :95-125、`_theme_momentum_for` :139/:144/:167、`_role_for` :264-286）
- Test: `quant-board/tests/test_theme_momentum_series.py`（追加）

**Interfaces:**
- Consumes: Task 1 `resolve_heat_level`
- Produces: 常量 `THEME_RELATIVE_MOMENTUM_SCALE = 15.0`、`THEME_DRAWDOWN_SCALE = 20.0`（数值与被替换的字面量一致）；`THEME_JUMP_HEAT_DELTA=15` 保留不动（同源放大风险见 design §5.5，首日观察）；`THEME_MOMENTUM_VERSION` 从 `theme-momentum-v1` bump 到 `"theme-momentum-v2"`（消费对象换为 heatLevel 序列，输出量纲有变；已核实该常量仅 momentum.py :251 返回值引用、无测试/下游断言，bump 无破坏——评审 M6）。

- [ ] **Step 1: 写失败测试（追加到 test_theme_momentum_series.py 末尾）**

```python
# ── heatLevel 落库迁移：序列与角色判定统一走 heat_level.resolve_heat_level（design §4.2）──

def test_series_consumes_heat_level_rows():
    """collector 新行（heatScore 绝对值 + heatLevel 相对分）→ 序列吃 heatLevel。"""
    frames = [
        _frame(0, [
            _theme("A", 2000.0, 1, extra={"heatLevel": 100.0}),
            _theme("B", 300.0, 2, extra={"heatLevel": 50.0}),
        ]),
        _frame(1, [
            _theme("A", 2200.0, 1, extra={"heatLevel": 100.0}),
            _theme("B", 320.0, 2, extra={"heatLevel": 50.0}),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["A", "B"]
    assert series["A"][0][:2] == (0, 100.0)
    assert series["B"][1][:2] == (1, 50.0)


def test_series_explicit_none_heat_level_is_missing():
    """heatLevel 显式 None（降级行）：诚实缺失，不回退 heatScore 绝对值。"""
    frames = [_frame(0, [_theme("A", 2000.0, 1, extra={"heatLevel": None})])]
    assert build_theme_strength_series(frames) == {}


def test_series_v2_marked_small_absolute_heat_not_relative():
    """v2 标记行无 heatLevel key：≤100 绝对值不回退为相对分（M1 边界窗口消除）。"""
    frames = [
        _frame(0, [
            _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v2"}}),
        ]),
    ]
    assert build_theme_strength_series(frames) == {}


def test_series_v1_marked_row_heat_score_fallback():
    """v1 标记行无 heatLevel key：≤100 heatScore 回退为相对分（旧行为保留）。"""
    frames = [
        _frame(0, [
            _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v1"}}),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert series["A"][0][:2] == (0, 85.0)


def test_exposure_role_consumes_heat_level():
    """新行 heatLevel=92 → core 阈值恢复语义；heatScore 绝对值不参与阈值。"""
    theme = _theme("A", 2000.0, 1, extra={"heatLevel": 92.0})
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 10.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "core"


def test_exposure_role_v2_row_without_heat_level_heatless_not_noise():
    """v2 标记行无 heatLevel：热度缺失只按涨跌判定，正涨跌不误判 noise。"""
    theme = _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v2"}})
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 10.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "independent"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_momentum_series.py -v`
Expected: 新增 6 个测试中 **4 个 FAIL**（test_series_consumes_heat_level_rows / test_series_v2_marked / test_exposure_role_consumes_heat_level / test_exposure_role_v2_row）；`test_series_explicit_none` 与 `test_series_v1_marked_row` 在旧代码下平凡通过（旧行为已与期望一致），作为实现后的回归锁定——评审 M1。

- [ ] **Step 3: 实现 momentum.py**

3a. import 区加 `from backend.analysis.theme.heat_level import resolve_heat_level`（`import math` 之后）。

3b. 常量区（:19 `THEME_JUMP_HEAT_DELTA = 15.0` 之后）插入：

```python
# heatLevel 相对分（0-100 rank 百分位）量纲参数（2026-09 落库迁移 design D3）：
# 消费对象从 heatScore 改为 heatLevel 序列，数值沿用旧 0-100 校准值，上线后按真实数据核定。
# 注意（design §5.5）：rank 百分位与 rank 变化同源，THEME_JUMP_HEAT_DELTA 信号与
# rank_jump 信号可能同帧重复触发，首日观察重叠率后再核定，本次不重校。
THEME_RELATIVE_MOMENTUM_SCALE = 15.0
THEME_DRAWDOWN_SCALE = 20.0
```

3b'. `THEME_MOMENTUM_VERSION = "theme-momentum-v1"`（:22）改为 `"theme-momentum-v2"`，行尾注释注明（评审 M6）：

```python
THEME_MOMENTUM_VERSION = "theme-momentum-v2"  # 2026-09 heatLevel 落库迁移：序列消费对象 heatScore → heatLevel
```

3c. `build_theme_strength_series` docstring 与 heat 读取替换：

```python
    """每题材按 (frame_index, heatLevel, rank) 记录；仅 rankEligible 且热度相对分可用。

    热度读取统一走 heat_level.resolve_heat_level（design §4.2）：新落库行吃 heatLevel
    相对分；v1/未标记旧行 ≤100 heatScore 回退；v2 标记行不回退（M1 边界窗口消除）。"""
    series: dict[str, list[tuple[int, float, int | None]]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for theme in frame.get("hotThemes") or []:
            if not isinstance(theme, dict):
                continue
            if str(theme.get("entityType") or "hot_theme") != "hot_theme":
                continue
            theme_id = _theme_id(theme)
            heat = resolve_heat_level(theme)
            if not theme_id or heat is None or not _theme_rank_eligible(theme):
                continue
```

（`heat = _num(theme.get("heatScore"), math.nan)` 与 `heat > 100.0` 过滤条件删除，其余行不动。）

3d. `_theme_momentum_for` 三处字面量替换：
- :139 `(short_change - market_median) / 15.0` → `(short_change - market_median) / THEME_RELATIVE_MOMENTUM_SCALE`
- :144 `... / 15.0,` → `... / THEME_RELATIVE_MOMENTUM_SCALE,`
- :167 `0.4 * drawdown / 20.0` → `0.4 * drawdown / THEME_DRAWDOWN_SCALE`

3e. `_role_for` 热度段（:271-283）替换：

```python
    # 热度阈值（70/45/20）消费 heatLevel 相对分（design §4.2）：缺失（含 v2 行显式
    # None / 绝对值）不参与热度分层，只保留涨跌侧的 noise 判定。
    heat = resolve_heat_level(theme)
    change = _num(stock.get("change"))
    if heat is not None:
        if heat >= 70 and change >= 5:
            return "core"
        if heat >= 45 and change > 0:
            return "follower"
        if heat < 20:
            return "noise"
    if change < -5:
        return "noise"
    return "independent"
```

（删除原 `raw_heat = theme.get("heatScore")` / `heat = _num(raw_heat, math.nan)` / `heat_0_100 = ...` 行。）

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_momentum_series.py -v`
Expected: 全部 PASS（含既有 11 个测试——未标记 ≤100 行为不变）

- [ ] **Step 5: 回归联动测试**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_resonance_fusion.py tests/test_theme_momentum_analyze_integration.py tests/test_theme_momentum_v2.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quant-board/backend/analysis/theme/momentum.py quant-board/tests/test_theme_momentum_series.py
git commit -m "feat(theme): momentum 序列/角色判定消费 heatLevel + 量纲常量参数化（D3）"
```

---

### Task 8: rotation 因子与引擎吃 heatLevel

**Files:**
- Modify: `quant-board/backend/analysis/theme/rotation/factors.py`（import 区、`strength_score` :50-102）
- Modify: `quant-board/backend/analysis/theme/rotation/engine.py`（:137、:154-156、:247-248、:300-303 + import）
- Test: `quant-board/tests/test_theme_rotation_factors.py`（追加）

**Interfaces:**
- Consumes: Task 1 `resolve_heat_level`
- Produces: `strength_score` 的 missing 标记名保持 `"heatScore"`（rotation 输出合同 `quality_flags` 不变，语义=热度维度缺失）。

- [ ] **Step 1: 写失败测试（追加到 test_theme_rotation_factors.py）**

```python
def test_strength_score_consumes_heat_level_row() -> None:
    """collector 新行：heatScore 绝对值 + heatLevel 相对分 → 强度因子吃 heatLevel。"""
    row = {
        "heatScore": 2000.0,
        "heatLevel": 96.3,
        "ztCount": 4,
        "change": 3.2,
    }
    score, missing = strength_score(row, [90.0, 92.0], [96.3, 50.0, 40.0], 1.0, 2)
    assert score is not None
    assert missing == []
    assert 0.0 <= score <= 100.0


def test_strength_score_v2_marked_row_without_heat_level_is_missing() -> None:
    """v2 标记行无 heatLevel key：≤100 绝对值不回退（M1 边界窗口消除）。"""
    row = {"heatScore": 85.0, "metadata": {"factorVersion": "theme-market-v2"}}
    score, missing = strength_score(row, [], [85.0], 1.0, 0)
    assert score is None
    assert "heatScore" in missing


def test_strength_score_unmarked_row_heat_score_fallback() -> None:
    """未标记旧行：≤100 heatScore 回退（旧行为保留）。"""
    row = {"heatScore": 85.0, "ztCount": 2}
    score, missing = strength_score(row, [80.0], [85.0, 50.0], 1.0, 1)
    assert score is not None
    assert missing == []
```

（`strength_score` 导入方式按该测试文件现有 import 为准；若尚未导入则 `from backend.analysis.theme.rotation.factors import strength_score`。）

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_factors.py -v`
Expected: 新增 3 个测试中第 1、2 个 FAIL

- [ ] **Step 3: 实现**

3a. `rotation/factors.py` import 区加 `from backend.analysis.theme.heat_level import resolve_heat_level`；`strength_score` 开头（:62-67）替换：

```python
    missing: list[str] = []
    heat = resolve_heat_level(row)
    if heat is None:
        missing.append("heatScore")
        return None, missing
    heat_score = heat
```

并把 docstring 中 `>100` 启发式描述改为：

```python
    """强度/动量：heat、横向 z、heat 斜率、涨停动能、板块超额。

    热度统一走 heat_level.resolve_heat_level（design §4.2）：heatLevel 相对分缺失时
    按缺失返回（missing 标记沿用 "heatScore" 名，rotation 合同不变），由
    combine_scores 按可用因子归一。"""
```

3b. `rotation/engine.py` import 区加 `from backend.analysis.theme.heat_level import resolve_heat_level`，四处替换：
- :137 `heat = _num(row.get("heatScore"))` → `heat = resolve_heat_level(row)`
- :154-156 全截面：

```python
        resolved_current_heats = [resolve_heat_level(r) for r in current_sector_rows]
        all_heats = [heat for heat in resolved_current_heats if heat is not None]
```

- :247-248 `_num(row.get("heatScore"))` → `resolve_heat_level(row)`
- :301 `robust_z(_num(r.get("heatScore"), 0.0), all_heats)` → `robust_z(resolve_heat_level(r) or 0.0, all_heats)`（缺失按 0.0 参与 z，与现状一致）

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_factors.py tests/test_theme_rotation_engine.py tests/test_theme_rotation_direction_labels.py tests/test_theme_rotation_service.py -v`
Expected: PASS（既有引擎测试的输入均为未标记 ≤100 行，行为不变）

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/analysis/theme/rotation/factors.py quant-board/backend/analysis/theme/rotation/engine.py quant-board/tests/test_theme_rotation_factors.py
git commit -m "feat(theme): rotation 强度因子/引擎热度读点统一走 heatLevel 口径"
```

---

### Task 9: backtest_service._persisted_heat_level 按口径消费 + 执行信号 themeHeat 透传切换（B10）

**Files:**
- Modify: `quant-board/backend/services/backtest_service.py`（`_persisted_heat_level` :217-224、调用点 :1240、themeHeat 透传点 :1249-1251 与 :1286、`_confluence_execution_signals` :1322-1325）
- Test: `quant-board/tests/test_theme_backtest.py`（追加）

**Interfaces:**
- Consumes: Task 3（replay factor 带 `heatLevel`/`heatFactorVersion`）
- Produces: `_persisted_heat_level(factor: object) -> float` —— **函数名与对外签名不变**（仍是单 object 参数，内部加 `isinstance(factor, dict)` 防御，None/非 dict 按 0.0——评审 M2 修正：不改签名为 `dict`，测试直接传 None 锁定防御）。语义：`heatLevel` key 存在 → 数值（0-100）或缺失按 0.0 计（回测置信度合成项，缺失不伪装满分）；key 不存在 → 按 `heat_caliber_of` 口径回退 heatScore（v1/未标记 ≤100），v2 不回退按 0 计。`:1244-1247` confluence 合成读的 `heat_level` 变量随之自动切到新口径（75 分门槛实际放宽，见 design §5.6）。

- [ ] **Step 1: 确认调用面**

Run: `cd quant-board && rg -n "_persisted_heat_level" backend tests`
Expected: 仅 `backtest_service.py` 定义 + :1240 一处调用（若 tests 有直接调用，一并在 Step 3 更新为传 factor dict）。

- [ ] **Step 2: 写失败测试（追加到 test_theme_backtest.py）**

```python
from backend.services.backtest_service import BacktestService, _persisted_heat_level


def test_persisted_heat_level_consumes_heat_level_and_caliber() -> None:
    """执行信号热度分量按 design §4.2 消费：heatLevel 优先，v2 绝对值不回退。"""
    assert _persisted_heat_level({"heatLevel": 96.3, "heatScore": 2000}) == 96.3
    assert _persisted_heat_level({"heatLevel": None, "heatScore": 2000}) == 0.0
    assert _persisted_heat_level({"heatScore": 85}) == 85.0
    assert _persisted_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v1"}}) == 85.0
    assert _persisted_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v2"}) == 0.0
    assert _persisted_heat_level({"heatScore": 2000}) == 0.0
    assert _persisted_heat_level({}) == 0.0
    assert _persisted_heat_level(None) == 0.0


def test_execution_signal_theme_heat_relative_caliber() -> None:
    """B10（评审 M4）：执行信号 themeHeat 透传字段改吃 heatLevel 相对分，不再透传绝对值。"""
    frames = [{
        "snapshotId": "snap_b10", "timestamp": 100,
        "tradingDate": "2026-09-03", "slotTime": "10:00",
        "stocks": [{"code": "600001", "name": "样本", "rank": 1, "price": 10.0, "change": 5.0}],
    }]
    factors = [{
        "snapshotId": "snap_b10", "themeName": "人工智能",
        "heatScore": 2000.0, "heatLevel": 96.3,
        "rotationState": "mainline", "crowdingRisk": 30,
    }]
    exposures = [{
        "snapshotId": "snap_b10", "code": "600001", "themeName": "人工智能",
        "role": "core", "themeContribution": 10.0, "exposureWeight": 82.0,
    }]
    signals = BacktestService._theme_execution_signals(frames, factors, exposures, "theme_rotation")
    assert signals[0]["themeHeat"] == 96.3

    # heatLevel 缺失 → 回退 stock.themeHeat（本例无）→ 0.0，不落绝对值
    factors_missing = [{**factors[0], "heatLevel": None}]
    signals_missing = BacktestService._theme_execution_signals(
        frames, factors_missing, exposures, "theme_rotation",
    )
    assert signals_missing[0]["themeHeat"] == 0.0
```

- [ ] **Step 3: 运行确认失败后实现**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_backtest.py -v` → 两个新测试 FAIL（旧实现把 heatLevel dict 当 value 解析得 0、v2 标记行错误回退；themeHeat 透传 2000.0）。

`backtest_service.py` 替换 `_persisted_heat_level`（:217-224）：

```python
def _persisted_heat_level(factor: object) -> float:
    """落库热度相对分解释（0-100，design §4.2 消费规则，2026-09 heatLevel 落库迁移）：

    factor.heatLevel key 存在 → 数值（0-100）直接用，缺失（None/非法）按 0 计
    （置信度合成项，缺失不伪装满分）；key 不存在 → 按 heatFactorVersion /
    metadata.factorVersion 口径回退 heatScore：theme-market-v1 或未标记且 ≤100
    有效，theme-market-v2 绝对值不回退按 0 计。"""
    if not isinstance(factor, dict):
        return 0.0
    if "heatLevel" in factor:
        numeric = _heat_score_number(factor.get("heatLevel"))
        return numeric if numeric is not None else 0.0
    numeric = _heat_score_number(factor.get("heatScore"))
    if numeric is None or numeric > 100.0:
        return 0.0
    if heat_caliber_of(factor) in ("", HEAT_CALIBER_V1):
        return numeric
    return 0.0


def _heat_score_number(value: object) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return max(0.0, min(100.0, numeric))
```

backtest_service.py 顶部 import 区加（确认无则添加）：

```python
import math

from backend.analysis.theme.heat_level import HEAT_CALIBER_V1, heat_caliber_of, resolve_heat_level
```

:1240 调用点 `heat_level = _persisted_heat_level(factor.get("heatScore"))` 改为：

```python
                heat_level = _persisted_heat_level(factor)
```

:1249-1251（`_theme_execution_signals` themeHeat 透传）改为：

```python
                # B10（评审 M4）：透传展示字段改吃 heatLevel 相对分（0-100），不再透传
                # 绝对值；缺失回退 stock 行 themeHeat，仍缺失按 0.0（展示合成项语义）。
                raw_theme_heat = resolve_heat_level(factor)
                if raw_theme_heat is None:
                    raw_theme_heat = stock.get("themeHeat")
```

（:1286 `"themeHeat": float(raw_theme_heat) if raw_theme_heat is not None else 0.0` 不动。）

:1322-1325（`_confluence_execution_signals`）同构替换：

```python
            # B10：与 _theme_execution_signals 同口径，themeHeat 透传相对分
            raw_theme_heat = resolve_heat_level(factor)
            if raw_theme_heat is None:
                raw_theme_heat = signal.get("themeHeat")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_theme_backtest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/services/backtest_service.py quant-board/tests/test_theme_backtest.py
git commit -m "feat(theme): 回测执行信号热度分量/themeHeat 透传按 heatLevel 口径消费（B10）"
```

---

### Task 10: 研究集合 _factor_doc 落 heatLevel + 口径标记

**Files:**
- Modify: `quant-board/backend/data/repositories/mongo_research_repository.py`（`_factor_doc` :751-775 + import）
- Test: `quant-board/tests/test_mongo_research_repository.py`（追加）

**Interfaces:**
- Consumes: Task 3 `ThemeFactorFrame.heatLevel` / `heatFactorVersion`（`item` 即 `frame.to_dict()`，字段自动出现）
- Produces: Mongo 研究集合 factor 文档新增 `heatLevel: float | None`、`heatFactorVersion: str | None`。`heatScore` 行 `"heatScore": float(item.get("heatScore") or 0.0)` 保持不动（既有历史语义）。研究集合仅 Mongo 主库（AI_COLLABORATION 硬约束 21），SQL 研究仓库是禁用的历史口径，不做同步。

- [ ] **Step 1: 写失败测试（追加到 test_mongo_research_repository.py）**

```python
def test_factor_doc_keeps_heat_level_and_caliber() -> None:
    doc = MongoResearchRepository._factor_doc({
        "datasetId": "d", "snapshotId": "s", "themeId": "ai", "themeName": "AI",
        "heatScore": 2000.0, "heatLevel": 96.3, "heatFactorVersion": "theme-market-v2",
    })
    assert doc["heatLevel"] == 96.3
    assert doc["heatFactorVersion"] == "theme-market-v2"

    missing = MongoResearchRepository._factor_doc({"datasetId": "d", "snapshotId": "s", "themeId": "ai"})
    assert missing["heatLevel"] is None
    assert missing["heatFactorVersion"] is None
```

（`MongoResearchRepository` 若测试文件已有 import 则复用。）

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_mongo_research_repository.py -v`
Expected: FAIL（`KeyError: 'heatLevel'`）

- [ ] **Step 3: 实现**

`mongo_research_repository.py` 顶部加 `import math`（`from datetime import ...` 之前）；`_factor_doc` 中 `"heatScore": float(item.get("heatScore") or 0.0),` 之后插入：

```python
            # heatLevel：0-100 相对分或 None（缺失，不伪装 0）；heatFactorVersion：热度口径标记
            "heatLevel": (
                float(item["heatLevel"])
                if isinstance(item.get("heatLevel"), (int, float)) and math.isfinite(float(item["heatLevel"]))
                else None
            ),
            "heatFactorVersion": str(item["heatFactorVersion"]) if item.get("heatFactorVersion") else None,
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_mongo_research_repository.py tests/test_theme_research.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/data/repositories/mongo_research_repository.py quant-board/tests/test_mongo_research_repository.py
git commit -m "feat(theme): 研究集合 factor 文档落 heatLevel + 热度口径标记"
```

---

### Task 11: 派生投影 stock row themeHeat 语义切换

**Files:**
- Modify: `quant-board/backend/snapshot_derivation/projection.py`（stock row heat 派生块 :582-592 + import）
- Test: `quant-board/tests/test_snapshot_derivation.py`（追加）

**Interfaces:**
- Consumes: Task 1 `resolve_heat_level`；Task 5 已放行 `SECTOR_FACTOR_FIELDS` 白名单（sector 行 heatLevel 已进落库行）
- Produces:
  - stock row `themeHeat` 语义 = 0-100 相对分或缺失（key 不存在），不再落绝对值。
- **设计偏离记录（需评审确认）**：design B7 写明 stock row 需要「行级口径标记」。核实结果：stock row 无通用 metadata dict（仅 `volumeRatioMeta`），新增标记字段需扩 `snapshot_ingest_normalizer` 字段白名单。本计划决定**不加行级标记**：`themeHeat` 值由 `resolve_heat_level(sector)` 派生，口径歧义已在 sector 行 `metadata.factorVersion` 层解决，值语义单一（相对分或缺失）。此偏离已写入 Task 18 文档收口。

- [ ] **Step 1: 写失败测试（追加到 test_snapshot_derivation.py）**

```python
def test_stock_theme_heat_consumes_sector_heat_level_and_caliber() -> None:
    """collector 新行：stock row themeHeat 吃 sector heatLevel 相对分（不再落绝对值）。"""
    fact = _fact_no_pre_close_with_theme()
    fact.sectors[0]["heatScore"] = 2000.0
    fact.sectors[0]["heatLevel"] = 96.3
    fact.sectors[0]["metadata"] = {"factorVersion": "theme-market-v2"}
    bundle = SnapshotDerivationService().derive(fact)
    assert bundle.stock_rows[0]["themeHeat"] == 96.3


def test_stock_theme_heat_v2_sector_without_heat_level_stays_missing() -> None:
    """v2 标记 sector 行无 heatLevel key：≤100 绝对值不回退，themeHeat 保持缺失。"""
    fact = _fact_no_pre_close_with_theme()
    fact.sectors[0]["heatScore"] = 85.0
    fact.sectors[0]["metadata"] = {"factorVersion": "theme-market-v2"}
    bundle = SnapshotDerivationService().derive(fact)
    assert "themeHeat" not in bundle.stock_rows[0]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_snapshot_derivation.py -v`
Expected: 两个新测试 FAIL（前者得 2000.0，后者伪装落 85.0）；既有 `test_theme_heat_and_risk_flags_derived_from_sector` 应保持 PASS（未标记行 80.0 回退）

- [ ] **Step 3: 实现**

3a. `projection.py` import 区加 `from backend.analysis.theme.heat_level import resolve_heat_level`（`SECTOR_FACTOR_FIELDS` 白名单已在 Task 5 放行 `heatLevel`，本任务不再动）。

3b. stock row 派生块（:582-592）heat 段替换：

```python
        # 题材热度/拥挤风险：由该股主题材的 sector factor 派生（无匹配则保持缺失）。
        # themeHeat 落库语义 = 0-100 相对分或缺失（2026-09 design B7）：统一走
        # resolve_heat_level（sector 行口径标记消歧），不伪装 0、不落绝对值。
        main_theme = row.get("mainTheme")
        if main_theme:
            sector = sector_by_name.get(_normalize_theme_label(main_theme))
            if sector is not None:
                heat = resolve_heat_level(sector)
                if heat is not None:
                    row.setdefault("themeHeat", heat)
                crowding = _safe_float(sector.get("crowdingRisk"))
                if crowding >= 70:
                    row.setdefault("themeRiskFlags", ["题材拥挤风险高"])
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_snapshot_derivation.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/snapshot_derivation/projection.py quant-board/tests/test_snapshot_derivation.py
git commit -m "feat(theme): 派生投影透传 sector heatLevel + stock row themeHeat 改相对分口径"
```

---

### Task 12: SQL/Supabase 备份 heat_level varchar 数值写入转文本

**Files:**
- Modify: `quant-board/backend/data/repositories/snapshot_repository.py`（import 区 + `_sector_model` :1498 + 模块级 helper）
- Modify: `quant-board/backend/data/backup/supabase_homomorphic.py`（:911 + 模块级 helper + import）
- Test: `quant-board/tests/test_storage_convergence.py`（追加）

**Interfaces:**
- Produces: 数值 `heatLevel`（int/float）写入 `heat_level` varchar 列前统一转 `str`；读侧 `local_sector_to_bundle_dict`（:1288）原样返回字符串，消费端 `resolve_heat_level` 规则 1 可解析（Task 1 测试已锁定 `{"heatLevel": "96.3"} == 96.3`）。字符串档位标签（历史浏览器行）原样透传，不解析。格式说明（评审 L-3）：`str(float(v))` 对整数形态带小数尾缀（`88` → `"88.0"`、`96.3` → `"96.3"`），对解析无功能影响，不做格式修饰。

- [ ] **Step 1: 写失败测试（追加到 test_storage_convergence.py）**

```python
def test_sector_model_heat_level_numeric_persists_as_text() -> None:
    """heat_level 列是 varchar(40)：数值 heatLevel 统一转文本存储，读侧回字符串。"""
    from backend.data.repositories.snapshot_repository import SnapshotRepositoryMixin

    model = SnapshotRepositoryMixin._sector_model("ds1", {
        "entityType": "hot_theme", "entityKey": "ai", "entityName": "人工智能",
        "rank": 1, "heatScore": 2000.0, "heatLevel": 96.3,
    })
    assert model.heat_level == "96.3"

    label = SnapshotRepositoryMixin._sector_model("ds1", {
        "entityType": "hot_theme", "entityKey": "x", "entityName": "X",
        "heatLevel": "热门",
    })
    assert label.heat_level == "热门"

    none_case = SnapshotRepositoryMixin._sector_model("ds1", {
        "entityType": "hot_theme", "entityKey": "y", "entityName": "Y",
        "heatLevel": None,
    })
    assert none_case.heat_level is None

    bundle = SnapshotRepositoryMixin.local_sector_to_bundle_dict(model)
    assert bundle["heatLevel"] == "96.3"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_storage_convergence.py::test_sector_model_heat_level_numeric_persists_as_text -v`
Expected: FAIL（`model.heat_level == 96.3` float，非 str）

- [ ] **Step 3: 实现**

3a. `snapshot_repository.py` import 区加 `import math`（`from collections import defaultdict` 之前）；模块级（class 外）加 helper，`_sector_model` 中 `heat_level=item.get("heatLevel"),` 改为 `heat_level=_heat_level_text(item.get("heatLevel")),`：

```python
def _heat_level_text(value: object) -> str | None:
    """heat_level 列是 varchar(40)：数值 heatLevel 统一转文本存储；None/字符串（历史
    浏览器档位标签）原样。读侧回字符串，消费端 heat_level.resolve_heat_level 可解析。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return str(numeric) if math.isfinite(numeric) else None
    return str(value)
```

3b. `supabase_homomorphic.py` import 区加 `import math`（`import gzip` 之后）；模块级加同名 helper（内容与 3a 一致，文件顶部注释注明与 snapshot_repository 保持同构）；:911 改为：

```python
            "heat_level": _heat_level_text(item.get("heatLevel", item.get("heat_level"))),
```

（:1099 读侧 `row.get("heat_level")` 不动——回读字符串，消费端解析。:190 列名清单不动。）

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/test_storage_convergence.py tests/test_theme_database.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant-board/backend/data/repositories/snapshot_repository.py quant-board/backend/data/backup/supabase_homomorphic.py quant-board/tests/test_storage_convergence.py
git commit -m "fix(theme): SQL/Supabase heat_level varchar 数值写入统一转文本"
```

---

### Task 13: 阶段 A 全量收口

- [ ] **Step 1: 全量 pytest**

Run: `cd quant-board && ./.venv/Scripts/python.exe -m pytest`
Expected: 全绿。重点确认 2026-09-02 文档列出的 8 个 theme 测试文件 + `test_theme_rotation_engine.py`、`test_theme_research.py`、`test_snapshot_derivation.py`、`test_snapshot_collector_builder.py`。

- [ ] **Step 2: import 断裂检查（归档约束）**

Run: `cd quant-board && ./.venv/Scripts/python.exe -c "from backend.analysis.theme import heat, trend, momentum; from backend.analysis.theme.rotation import engine, factors; from backend.services import backtest_service; from backend.snapshot_collector import service; from backend.snapshot_derivation import projection; from backend.data.repositories import mongo_repository, snapshot_repository, mongo_research_repository; print('imports ok')"`
Expected: `imports ok`

- [ ] **Step 3: Commit（如有零星修复）**

```bash
git status --short  # 确认只有本计划触碰的文件；计划外文件保持原样不加（评审 M-4，禁 git add -A）
git add quant-board/backend/analysis/theme quant-board/backend/services quant-board/backend/snapshot_collector quant-board/backend/snapshot_derivation quant-board/backend/data quant-board/tests
git commit -m "test(theme): 阶段 A 全量回归收口（heatLevel 落库迁移）"
```
（无改动则跳过。）

---

## 阶段 B：前端（Dragon Board src/）

### Task 14: 前端类型与数据链（types → feed → projector → coordinator → DataLayer → meta → facade）

**Files:**
- Modify: `src/services/theme/types.ts`（`ThemeFactorSnapshot` :50 附近、`ThemePanelSummary` :105-133、`ThemeHeatApiFactor` :73-82、`ThemeStockExposure` :151）
- Modify: `src/services/theme/ThemeHeatFeed.ts`（`toRuntimeFactor` :78-114）
- Modify: `src/services/theme/ThemeStockProjector.ts`（`roleFor` :25-27、`reasonsFor` :51、`buildExposure` :73-77/:87、排序 :133）
- Modify: `src/services/theme/ThemeRuntimeCoordinator.ts`（`syncStocks` :110-134）
- Modify: `src/services/DataLayer.ts`（`updateStockThemes` :280-312）
- Modify: `src/services/theme/stockThemeMeta.ts`（`deriveThemeHeatLevel` :34-40、`StockThemeSnapshot` :12-16、`resolvePrimaryStockTheme` :69-85）
- Modify: `src/services/theme/ThemeFacade.ts`（`toHotThemeSummary` :274-313、`toStockTheme` :315-330）
- Modify: `src/types/data-layer.ts:223`、`src/types/core.ts:91`、`src/types/dragon.ts:95`、`src/services/dragon/types.ts:87`（themeHeat 类型放宽）
- Test: `src/services/theme/__tests__/`（ThemeHeatFeed/ThemeRuntimeCoordinator/stockThemeMeta 扩展；新建 ThemeStockProjector.test.ts）

**Interfaces:**
- Produces（阶段 B 后续任务消费）:
  - `ThemeFactorSnapshot.heatLevel: number | null`（runtime factor）
  - `ThemeHeatApiFactor.heatLevel: number | null`（必填 key，缺失=显式 null）
  - `ThemeStockExposure.themeScore: number | null`（= 主导 factor 的 heatLevel）
  - `ThemePanelSummary.heatLevelScore: number | null`（新增；`heatLevel: string` 档位标签保留）
  - `deriveThemeHeatLevel(score: number | null | undefined): string`（非有限值 → `''`）
  - `StockThemeSnapshot.themeHeat: number | null`
  - `MergedStock.themeHeat?: number | null`、`Stock.themeHeat?: number | null`、LeaderRecord/FrameNormalizer 对应放宽

- [ ] **Step 1: 写失败测试**

1a. `src/services/theme/__tests__/ThemeHeatFeed.test.ts`：apiSnapshot 两个 factor 字面量各加 `heatLevel`（AI → `88`，LOW → `null`），并追加（注意：LOW factor 原夹具 `rankEligible: false, heatScore: null`，会被 `getRuntimeFactors` 的 `rankEligible && Number.isFinite(heatScore)` 过滤掉，解构出的 `low` 是 undefined——必须覆盖这两个字段让它通过过滤器，才能锁定 heatLevel 缺失透传，评审 H-2a）：

```ts
  it('passes heatLevel through to runtime factors and keeps missing as null', async () => {
    const feed = new ThemeHeatFeed({
      getThemeHeat: async () => ({
        data: {
          ...apiSnapshot,
          factors: [
            { ...apiSnapshot.factors[0], heatLevel: 96.3 },
            // 覆盖 rankEligible/heatScore 使其通过 getRuntimeFactors 过滤器，只留 heatLevel 缺失
            { ...apiSnapshot.factors[1], rankEligible: true, heatScore: 30 },
          ],
        },
      }),
      getThemeHeatStocks: async () => ({ data: { stocks: [] } }),
    } as any)
    await feed.refresh({ force: true })
    const [ai, low] = feed.getRuntimeFactors()
    expect(ai.heatLevel).toBe(96.3)
    expect(low.heatLevel).toBeNull()
    feed.destroy()
  })
```

1b. `src/services/theme/__tests__/ThemeStockProjector.test.ts`（新建）：

```ts
import { describe, expect, it } from 'vitest'
import { projectThemeStockExposures } from '../ThemeStockProjector'
import type { ThemeFactorSnapshot, ThemeSourceContext } from '../types'

function factor(overrides: Partial<ThemeFactorSnapshot> = {}): ThemeFactorSnapshot {
  return {
    themeId: 'AI',
    themeName: '人工智能',
    source: 'market_aggregate',
    timestamp: 1,
    heatScore: 2000,
    heatLevel: 90,
    momentumScore: 0,
    breadthScore: 0,
    fundScore: null,
    leadershipScore: 0,
    correlationScore: 0,
    crowdingRisk: 0,
    persistenceScore: 0,
    rotationState: 'neutral',
    stockCount: 1,
    ztCount: 0,
    leaderCount: 0,
    netInflow: null,
    strength: 2000,
    volumeRatio: 0,
    rank: 1,
    relatedThemeIds: [],
    qualityFlags: [],
    components: { breadthScore: 0, fundScore: null, leadershipScore: 0, correlationScore: 0, riskPenalty: 0 },
    ...overrides,
  } as ThemeFactorSnapshot
}

function context(heatLevelStockChange = 10): ThemeSourceContext {
  return {
    timestamp: 1,
    themes: [{ id: 'AI', name: '人工智能' }],
    themeStocks: new Map([['AI', ['000001']]]),
    stockThemes: new Map([['000001', ['AI']]]),
    stocks: [{ code: '000001', name: '样本', change: heatLevelStockChange }],
    rotationAnalysis: null,
    correlations: new Map(),
  }
}

describe('ThemeStockProjector heatLevel caliber', () => {
  it('maps heatLevel to themeScore (relative score, not absolute heatScore)', () => {
    const result = projectThemeStockExposures(context(), [factor()])
    expect(result.byCode.get('000001')?.[0]?.themeScore).toBe(90)
  })

  it('treats missing heatLevel as heatless: positive change is not noise', () => {
    const result = projectThemeStockExposures(context(10), [factor({ heatLevel: null })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('independent')
  })

  it('heatLevel < 20 with positive change is noise: sub-threshold exposure filtered out', () => {
    // 评审 H-2b：noise 贡献度 (10*0.1 + 12*0.08)*0.15 ≈ 0.29 < 1，被既有 themeContribution<1
    // 规则过滤，byCode 无该股条目——旧代码（heatScore 2000 → core/follower）会保留 exposure，
    // 该断言是真正的 RED 判别点，不能断言 role 值（拿不到被过滤的 exposure）。
    const result = projectThemeStockExposures(context(1), [factor({ heatLevel: 10 })])
    expect(result.byCode.get('000001') ?? []).toHaveLength(0)
  })

  it('deep drop (change < -5) is noise regardless of high heatLevel (regression lock)', () => {
    // 深跌 noise 走 change<-5 分支，贡献度 (90*0.1 + 12*0.08)*0.15 ≈ 1.49 ≥ 1 → exposure 保留，
    // 可断言 role；新旧代码对该分支行为一致，作为回归锁定而非 RED 判别点。
    const result = projectThemeStockExposures(context(-6), [factor({ heatLevel: 90 })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('noise')
  })

  it('heatLevel >= 70 with change >= 5 is core', () => {
    const result = projectThemeStockExposures(context(6), [factor({ heatLevel: 72 })])
    expect(result.byCode.get('000001')?.[0]?.role).toBe('core')
  })
})
```

1c. `src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts`：`feedFactor` 基础字面量加 `heatLevel: 80,`；:147 断言 `expect(stock.themeHeat).toBeGreaterThan(0)` 改为 `expect(stock.themeHeat).toBe(80)`；追加（注意：DataLayer 3e 改造后 `themeLevel || undefined`，'' 会归一为 undefined，断言必须是 `toBeUndefined()` 而非 `toBe('')`，评审 H-2c）：

```ts
  it('propagates missing theme heat without disguising zero', () => {
    dataLayer.setMergedStocks([{ code: '000001', name: '样本一', change: 10 } as any])
    vi.mocked(themeHeatFeed.getRuntimeFactors).mockReturnValue([feedFactor({ heatLevel: null })])

    refreshRuntime({ source: 'test', context: context(), syncStocks: true, emitAlerts: false })
    const stock = dataLayer.getStock('000001') as any

    expect(stock.themeHeat).toBeUndefined()
    expect(stock.themeLevel).toBeUndefined()
  })
```

1d. `src/services/theme/__tests__/stockThemeMeta.test.ts` 追加：

```ts
describe('deriveThemeHeatLevel missing handling', () => {
  it('returns empty label for missing heat (not coldest tier)', () => {
    // 评审 H-2d：hasFiniteNumber(null) === true（Number(null) === 0），
    // 旧实现会把 null 判成 0 度"冰"；必须返回空标签表示缺失。
    expect(deriveThemeHeatLevel(null)).toBe('')
    expect(deriveThemeHeatLevel(undefined)).toBe('')
    expect(deriveThemeHeatLevel(Number.NaN)).toBe('')
  })
})

describe('resolvePrimaryStockTheme missing heat', () => {
  it('keeps themeHeat null when primary theme has no heatScore (not 0)', () => {
    const snap = resolvePrimaryStockTheme([{ id: 'AI', name: '人工智能', heatScore: null }])
    expect(snap.themeHeat).toBeNull()
    expect(snap.themeLevel).toBe('')
  })
})
```

（若该文件尚未 import `deriveThemeHeatLevel` 则补 import。）

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- src/services/theme`
Expected: 新增用例 FAIL；既有用例部分 FAIL（feedFactor 无 heatLevel / :147 断言）

- [ ] **Step 3: 实现**

3a. `types.ts`：
- `ThemeFactorSnapshot` `heatScore: number` 后加 `heatLevel: number | null`；
- `ThemeHeatApiFactor` 加 `heatLevel: number | null`（必填 key）；
- `ThemeStockExposure.themeScore: number` → `themeScore: number | null`；
- `ThemePanelSummary` `heatLevel: string` 后加 `heatLevelScore: number | null`。

3b. `ThemeHeatFeed.ts` `toRuntimeFactor`：`heatScore,` 之后加一行：

```ts
    heatLevel: nullableFinite(factor.heatLevel),
```

3c. `ThemeStockProjector.ts`：

```ts
  // 热度阈值（70/45/20）消费 heatLevel 相对分（0-100，后端 rank 百分位）。
  // 注意 JS 陷阱：null < 20 === true，必须显式 != null；缺失热度只按涨跌判定 noise。
  const heat = factor.heatLevel
  if (heat != null && heat >= 70 && toFiniteNumber(stock?.change) >= 5) return 'core'
  if (heat != null && heat >= 45 && toFiniteNumber(stock?.change) > 0) return 'follower'
  if ((heat != null && heat < 20) || toFiniteNumber(stock?.change) < -5) return 'noise'
  return 'independent'
```

`reasonsFor` :51 改：`if ((factor.heatLevel ?? 0) >= 70) reasons.push('题材热度强')`。
`buildExposure` :74 热度分量：`factor.heatScore * 0.1` → `(factor.heatLevel ?? 0) * 0.1`（加权合成项缺失→0，注释注明）；:87 `themeScore: factor.heatScore,` → `themeScore: factor.heatLevel,`；:133 排序 `right.themeScore - left.themeScore` → `(right.themeScore ?? 0) - (left.themeScore ?? 0)`。

3d. `ThemeRuntimeCoordinator.ts` `syncStocks`：

```ts
function syncStocks(exposures: ThemeExposureProjection): number {
  const updates = Array.from(exposures.byCode.entries()).map(([code, items]) => {
    const sorted = [...items].sort((a, b) => b.themeContribution - a.themeContribution)
    const main = sorted[0]
    // themeHeat = 主题材 heatLevel 相对分（0-100）或缺失（undefined，不伪装 0）
    const mainHeat = main?.themeScore ?? undefined
    return {
      code,
      themes: sorted.map((exposure) => ({
        id: exposure.themeId,
        name: exposure.themeName,
        heatScore: exposure.themeScore ?? undefined,
        role: exposure.role,
        roleScore: exposure.roleScore,
        exposureWeight: exposure.exposureWeight,
        themeContribution: exposure.themeContribution,
        riskPenalty: exposure.riskPenalty,
        reasons: exposure.reasons,
      })),
      mainTheme: main?.themeName,
      themeHeat: mainHeat,
      themeLevel: deriveThemeHeatLevel(main?.themeScore ?? null),
    }
  })
  if (updates.length) dataLayer.updateStockThemes(updates)
  return updates.length
}
```

（`themeHeat`/`themes[].heatScore` 的 `?? undefined` 是 null→undefined 的类型归一，缺失语义保持。）

3e. `DataLayer.ts` `updateStockThemes`：参数类型 `themeHeat?: number` → `themeHeat?: number | null`；:299-300 改：

```ts
        stock.themeHeat = themeHeat ?? undefined
        stock.themeLevel = themeLevel || undefined
```

（删除 `?? 0` 与 `|| '冷'` 伪装：缺失保持 undefined。）

3f. `stockThemeMeta.ts`：

```ts
export interface StockThemeSnapshot {
  mainTheme?: string
  /** 主题材 heatLevel 相对分（0-100）；null = 热度缺失或无题材，不伪装 0 */
  themeHeat: number | null
  themeLevel: string
}

export function deriveThemeHeatLevel(score: number | null | undefined): string {
  // JS 陷阱（评审 H-2d）：hasFiniteNumber(null) === true（Number(null) === 0），
  // 旧写法会把缺失热度判成 0 度"冰"；必须显式 null/undefined 判断，缺失返回 ''。
  if (score == null || typeof score !== 'number' || !Number.isFinite(score)) return ''
  if (score >= 80) return '热门'
  if (score >= 60) return '活跃'
  if (score >= 40) return '温'
  if (score >= 20) return '冷'
  return '冰'
}
```

`resolvePrimaryStockTheme` 改（同一陷阱：`hasFiniteNumber(null) === true` 会让 null 经 `normalizeThemeHeatScore` 伪装成 0，必须显式守卫）：

```ts
export function resolvePrimaryStockTheme(themes: StockThemeLike[]): StockThemeSnapshot {
  const [primaryTheme] = sortStockThemes(themes).filter((theme) => String(theme?.name || '').trim())
  if (!primaryTheme) {
    return { mainTheme: undefined, themeHeat: null, themeLevel: '' }
  }

  const themeHeat =
    primaryTheme.heatScore != null &&
    typeof primaryTheme.heatScore === 'number' &&
    Number.isFinite(primaryTheme.heatScore)
      ? normalizeThemeHeatScore(primaryTheme.heatScore)
      : null
  return {
    mainTheme: String(primaryTheme.name || '').trim() || undefined,
    themeHeat,
    themeLevel: primaryTheme.heatLevel || deriveThemeHeatLevel(themeHeat),
  }
}
```

（`deriveThemeHeatMeta` 保留原签名不动——sectorAnalyzer 仅用其初始化 0 值档位，无阈值语义。）

3g. `ThemeFacade.ts` `toHotThemeSummary`（:278-292 段）：

```ts
  // heatLevelScore：0-100 相对分（12 处阈值消费点统一输入）；heatScore 保持 KPL
  // 人气绝对值（人气量级展示/排序专用，如 DragonBreathPanel 3000/1500）。
  const heatLevelScore = factor.heatLevel ?? null
  const heatLevel = deriveThemeHeatLevel(heatLevelScore)
  const apiNetInflow = ...(原样保留)
  return {
    id: factor.themeId,
    name: factor.themeName,
    rank: factor.rank,
    heatScore: factor.heatScore,
    heatIcon: heatLevelScore == null ? '❄️' : heatLevelScore >= 80 ? '🔥' : heatLevelScore >= 60 ? '⚡' : heatLevelScore >= 40 ? '🌟' : '❄️',
    heatColor: heatLevelScore != null && heatLevelScore >= 80 ? '#ff4757' : heatLevelScore != null && heatLevelScore >= 60 ? '#f39c12' : '#3498db',
    heatLevel,
    heatLevelScore,
    ...(其余字段原样保留)
  }
```

`toStockTheme`（:320-321）：`heatScore: exposure.themeScore ?? undefined,`、`heatLevel: deriveThemeHeatLevel(exposure.themeScore),`。`:351` 排序 `b.heatScore - a.heatScore` 不动（人气绝对值排序）。`:305` `strength: factor.strength || factor.heatScore` 不动。

3h. 类型放宽（4 个文件）：
- `src/types/data-layer.ts:223` `themeHeat?: number` → `themeHeat?: number | null`
- `src/types/core.ts:91` `themeHeat?: number` → `themeHeat?: number | null`
- `src/types/dragon.ts:95` `themeHeat: number` → `themeHeat: number | null`
- `src/services/dragon/types.ts:87` `themeHeat?: number` → `themeHeat?: number | null`

- [ ] **Step 4: 类型补齐（vue-tsc 枚举）**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 报若干 `heatLevel` 缺失的 `ThemeFactorSnapshot`/`ThemeHeatApiFactor` 字面量构造错误（测试 fixture 与构造点清单**以 vue-tsc 实际输出为准**，本计划不预列文件名——评审 L-2）。逐个补 `heatLevel`：有 rank 的因子给数值（与该 fixture 语义一致的 0-100 值，如 80），无热度因子给 `null`。禁止用 `as any` 绕过。

- [ ] **Step 5: 运行确认通过**

Run: `pnpm test -- src/services/theme && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: PASS / 无类型错误

- [ ] **Step 6: Commit**

```bash
git add src/services/theme src/services/DataLayer.ts src/types src/services/dragon/types.ts src/services/theme/__tests__
git commit -m "feat(theme): 前端热度数据链切换 heatLevel 相对分口径（缺失传播不伪装 0）"
```

---

### Task 15: 前端阈值消费点切换（12 处）

**Files:**
- Modify: `src/config/factors.ts:114-121`（themeHeat 因子）
- Modify: `src/services/hotness/StockHotnessCalculator.ts:154-164`（themeSupportScore）
- Modify: `src/services/dragon/BattlefieldBuilder.ts`（:165、:175、:254、:341、:355、:427）
- Modify: `src/services/theme/ThemeAlertEngine.ts:101`
- Modify: `src/components/panels/ThemeCorrelationPanel.vue`（:68、:885）
- Modify: `src/components/panels/ThemeRiskDashboard.vue`（:395-402、:414、:426）
- Test: `src/services/hotness/__tests__/StockHotnessCalculator.test.ts`（追加）

**Interfaces:**
- Consumes: Task 14（`ThemeFactorSnapshot.heatLevel`、`ThemePanelSummary.heatLevelScore`、`MergedStock.themeHeat: number | null`）
- 不改动（语义自动恢复，验证即可）：
  - `src/services/dragon/helpers.ts:270` `battlefield.themeHeatScore * 0.24` 与 `src/services/dragon/ReviewComposer.ts:98` `themeHeatScore >= 60` —— 输入来自 BattlefieldBuilder seed（本任务切为 heatLevel），上游修好下游自动恢复（评审 L-1：ReviewComposer 实际位于 `src/services/dragon/`）；
  - `src/components/panels/DragonBreathPanel.vue:877,1126-1127` 3000/1500 —— 人气绝对值口径正确；
  - `src/services/sectorAnalyzer.ts` —— heatScore 为 init-only 0 值 + deriveThemeHeatMeta(0) 初始化，无阈值语义。

- [ ] **Step 1: 写失败测试（追加到 StockHotnessCalculator.test.ts）**

（该文件现有导出为 `calculateStockHotnessRecords` / `calculateStockHotnessUpdates`，夹具构造函数为 `createStock(overrides)`——评审 M-3 确认，直接使用；Task 14 类型放宽后 `themeHeat: null` 无需 `as any`。）

```ts
  it('themeSupport：>100 旧口径绝对值按缺失处理，真实冷门 heat 有效，null 不伪装', () => {
    // RED 判别点（评审 M-3/M5）：themeHeat=2000 是迁移前绝对值残留，旧代码
    // 2000*0.55 被 Math.min(100,...) clamp 到满分；新代码 0-100 区间守卫按缺失 → 0。
    const legacyAbsolute = calculateStockHotnessRecords([createStock({ themeHeat: 2000, themes: [] })], 8)
    const missing = calculateStockHotnessRecords([createStock({ themeHeat: null, themes: [] })], 8)
    const cold = calculateStockHotnessRecords([createStock({ themeHeat: 5, themes: [] })], 8)
    expect(legacyAbsolute[0].components.themeSupport).toBe(0)
    expect(missing[0].components.themeSupport).toBe(0)
    expect(cold[0].components.themeSupport).toBeGreaterThan(0)
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- src/services/hotness`
Expected: `legacyAbsolute` 断言 FAIL（旧代码 clamp 到 100）；`missing`/`cold` 两断言在旧代码下平凡通过（旧代码 toNumber(null)=0 同样得 0、5*0.55>0 同样成立），作为实现后的回归锁定。

- [ ] **Step 3: 实现**

3a. `src/config/factors.ts:117`：`return Math.min(100, exposure?.themeScore || 0)` →

```ts
        // themeScore 现为 heatLevel 相对分（0-100 | null）；评分因子缺失→0（合成项，不展示）
        return Math.min(100, exposure?.themeScore ?? 0)
```

3b. `StockHotnessCalculator.ts` `themeSupportScore`：

```ts
function themeSupportScore(stock: Pick<MergedStock, 'themeHeat' | 'themes'>): number {
  // themeHeat 现为 0-100 相对分或 null/undefined（缺失）：null = 热度缺失不伪装 0；
  // rank 末位 heatLevel>0 是真实冷，不是无信号（2026-09-03 design §4.4）；
  // >100 = 迁移前绝对值残留，按缺失处理（0-100 区间守卫，评审 M5），不参与加权。
  const themeHeat =
    typeof stock.themeHeat === 'number' &&
    Number.isFinite(stock.themeHeat) &&
    stock.themeHeat >= 0 &&
    stock.themeHeat <= 100
      ? stock.themeHeat
      : null
  const themeContributions = Array.isArray(stock.themes)
    ? stock.themes.map((theme: unknown) =>
        theme && typeof theme === 'object' ? toNumber((theme as { themeContribution?: unknown }).themeContribution) : 0,
      )
    : []
  const maxContribution = Math.max(0, ...themeContributions)
  if (themeHeat === null && maxContribution <= 0) return 0
  const heatPart = themeHeat === null ? 0 : themeHeat * 0.55
  return Math.min(100, heatPart + Math.min(18, maxContribution) * 2.5)
}
```

3c. `BattlefieldBuilder.ts`：
- :165 `const heatScore = params.hotTheme?.heatScore || 0` → `const heatScore = params.hotTheme?.heatLevelScore ?? 0`（:175 `heatScore >= 55` 不变）
- :254 `factor.rotationState === 'mainline' || factor.heatScore >= 75` → `factor.rotationState === 'mainline' || (factor.heatLevel ?? 0) >= 75`
- :341 `themeHeatScore: factor?.heatScore || hotTheme?.heatScore || 0,` → `themeHeatScore: factor?.heatLevel ?? hotTheme?.heatLevelScore ?? 0,`
- :355 `(hotTheme?.heatScore || 0) >= 60 ? \`题材热度 ${Math.round(hotTheme?.heatScore || 0)}\` : '题材热度一般',` → `(hotTheme?.heatLevelScore ?? 0) >= 60 ? \`题材热度 ${Math.round(hotTheme?.heatLevelScore ?? 0)}\` : '题材热度一般',`
- :427 `themeHeatScore: stock.themeHeat || 0,` → `themeHeatScore: stock.themeHeat ?? 0,`（加权合成项缺失→0）

3d. `ThemeAlertEngine.ts:101`：`factor.momentumScore >= 75 && factor.heatScore >= 70` → `factor.momentumScore >= 75 && (factor.heatLevel ?? 0) >= 70`

3e. `ThemeCorrelationPanel.vue`：
- :68 `:class="getStrengthClass(theme.strength)"` → `:class="getStrengthClass(theme.heatLevelScore ?? 0)"`（:69 `formatStrength(theme.strength)` 保持人气绝对值档位）
- :885 `isHot: theme.heatScore >= 65,` → `isHot: theme.heatLevelScore != null && theme.heatLevelScore >= 65,`
- :881 `strength: theme.heatScore` 与 :888 排序保持（人气量级展示/排序）

3f. `ThemeRiskDashboard.vue`：
- `RiskTheme` 接口（:395-402）加 `heatLevel: number | null`；:414 构造处加 `heatLevel: f.heatLevel,`
- :426 `|| f.heatScore >= 75` → `|| (f.heatLevel ?? 0) >= 75`
- 模板 :157/:204/:228 `{{ t.heatScore }}` 保持（人气绝对值展示）

- [ ] **Step 4: 运行确认通过**

Run: `pnpm test && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/config/factors.ts src/services/hotness src/services/dragon/BattlefieldBuilder.ts src/services/theme/ThemeAlertEngine.ts src/components/panels/ThemeCorrelationPanel.vue src/components/panels/ThemeRiskDashboard.vue
git commit -m "feat(theme): 12 处 0-100 阈值消费点从绝对值 heatScore 切换到 heatLevel"
```

---

### Task 16: 前端快照行类型与浏览器构建点 + context 行口径标记（B9）

**Files:**
- Modify: `src/services/snapshot/types.ts`（:157 `themeHeat?: number`、:192 `heatLevel?: string`）
- Modify: `src/services/snapshot/builders.ts`（:807、:842）
- Modify: `src/services/snapshot/buildContext.ts`（`getCurrentSnapshotBuildContext`，B9）
- Test: `src/services/snapshot/__tests__/builders.test.ts`（追加）
- Test: `src/services/snapshot/__tests__/buildContext.test.ts`（新建）

**Interfaces:**
- Produces:
  - `SnapshotStockRow.themeHeat?: number | null`（null = 热度缺失，跟随 Task 14 数据链）
  - `SnapshotSectorRow.heatLevel?: string | number | null`（过渡期放宽：写侧只产数值，读侧兼容历史字符串档位标签）
  - context 行（`hotThemes` / `themeHeatFactors`）统一带 `metadata.factorVersion`（快照缺失时按 `theme-market-v2` 兜底）；hotThemes 行 `heatLevel` 数值化（来源 `heatLevelScore`，无值不写 key）。设计依据：context 行每帧重建、不会随 collector 行累积消亡（评审 H2 修正），是 B9 的落点；`buildSectorMetadata`（builders.ts:179-190）透传 `payload.metadata`，标记可达落库行。
- 不改动：:838 `strength` 绝对值保留、:839-841 heatScore 数值透传保留。

- [ ] **Step 1: 写失败测试**

1a. `src/services/snapshot/__tests__/buildContext.test.ts`（新建）：

```ts
import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getHotThemes: vi.fn(),
  getSnapshot: vi.fn(),
}))

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: () => [],
    getDepth10Map: () => new Map(),
    getRecentTicksMap: () => new Map(),
    getL2SummaryMap: () => new Map(),
    getBreathData: () => null,
    getBreathMarketData: () => null,
    getHotThemes: () => mocks.getHotThemes(),
    getCurrentRotation: () => null,
    getBreathHistory: () => [],
    getBreathFactors: () => [],
    getMarketMode: () => 'normal',
    getVersion: () => ({ stocks: 0 }),
  },
}))
vi.mock('../../theme/ThemeHeatFeed', () => ({
  themeHeatFeed: { getSnapshot: () => mocks.getSnapshot() },
}))
vi.mock('../../theme/ThemeRuntimeCoordinator', () => ({
  getBackendRotationSummaryRaw: () => null,
}))

import { getCurrentSnapshotBuildContext } from '../buildContext'

describe('buildContext heatLevel caliber marking (B9)', () => {
  it('marks themeHeatFactors and hotThemes rows with metadata.factorVersion and numericizes hotThemes heatLevel', () => {
    mocks.getSnapshot.mockReturnValue({
      factorVersion: 'theme-market-v2',
      sources: {},
      factors: [{ themeId: 'AI', heatScore: 2000, heatLevel: 96.3, metadata: {} }],
    })
    mocks.getHotThemes.mockReturnValue([
      { id: 'AI', name: '人工智能', heatScore: 2000, heatLevelScore: 96.3, heatLevel: '热门' },
      { id: 'COLD', name: '冷门', heatScore: 12, heatLevelScore: undefined, heatLevel: '冰' },
    ])

    const context = getCurrentSnapshotBuildContext()

    expect(context.themeHeatFactors?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    // hotThemes 行 heatLevel 数值化（来自 heatLevelScore），字符串档位标签不再进入快照行
    expect(context.hotThemes?.[0]?.heatLevel).toBe(96.3)
    expect(context.hotThemes?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    // 无 heatLevelScore → 不写 heatLevel key（tri-state）
    expect(Object.prototype.hasOwnProperty.call(context.hotThemes?.[1], 'heatLevel')).toBe(false)
    expect(context.hotThemes?.[1]?.metadata?.factorVersion).toBe('theme-market-v2')
  })

  it('falls back to theme-market-v2 marking when snapshot factorVersion is missing', () => {
    mocks.getSnapshot.mockReturnValue({ sources: {}, factors: [{ themeId: 'AI', metadata: {} }] })
    mocks.getHotThemes.mockReturnValue([{ id: 'AI', name: '人工智能' }])

    const context = getCurrentSnapshotBuildContext()

    expect(context.themeHeatFactors?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
    expect(context.hotThemes?.[0]?.metadata?.factorVersion).toBe('theme-market-v2')
  })
})
```

1b. `src/services/snapshot/__tests__/builders.test.ts` 追加（按该文件现有 record 夹具构造方式复制一份）：

```ts
  it('writes numeric heatLevel only and keeps missing themeHeat as null', () => {
    // 复制现有 buildSnapshotSectorRows / buildSnapshotStockRows 用例夹具，payload 改为：
    //   hotTheme: { ..., heatScore: 2000, heatLevel: 96.3 }
    //   stock: { ..., themeHeat: null }
    // 断言：
    // expect(row.heatLevel).toBe(96.3)
    // expect(stockRow.themeHeat).toBeNull()
  })
```

（夹具构造代码必须真实可运行：复制同文件既有用例的 record/payload 构造，仅按上述注释修改字段与断言；禁止留注释体当实现。）

- [ ] **Step 2: 运行确认失败**

Run: `pnpm test -- src/services/snapshot`
Expected: FAIL（buildContext 行无 factorVersion 标记、hotThemes 行 heatLevel 是字符串；heatLevel 被丢弃 / themeHeat 伪装 0）

- [ ] **Step 3: 实现**

3a. `builders.ts` :807：

```ts
        themeHeat: finiteNumberOrNull(item.themeHeat),
```

:842：

```ts
    // 浏览器构建的正式 sector row 只落数值 heatLevel（非数值=历史字符串档位标签，不写）；
    // 相对分来源是 buildContext.themeHeatFactors / hotThemes（B9 数值化）
    heatLevel:
      typeof payload.heatLevel === 'number' && Number.isFinite(payload.heatLevel)
        ? payload.heatLevel
        : undefined,
```

3b. `snapshot/types.ts` :157 `themeHeat?: number` → `themeHeat?: number | null`；:192 `heatLevel?: string` → `heatLevel?: string | number | null`。

3c. `buildContext.ts` `getCurrentSnapshotBuildContext`（B9）：

```ts
export function getCurrentSnapshotBuildContext(): SnapshotBuildContext {
  const themeHeatSnapshot = themeHeatFeed.getSnapshot()
  const quoteSource = (themeHeatSnapshot?.sources?.quotes as any)?.source
  const fundSource = (themeHeatSnapshot?.sources?.funds as any)?.source
  // B9（2026-09 design §4.2 残留歧义修正）：context 行每帧重建、不会随 collector 行累积
  // 消亡，必须携带口径标记供消费端按 design §4.2 分支回退；快照缺失 factorVersion 时
  // 按当前 v2 口径兜底标记。hotThemes 行 heatLevel 从字符串档位标签数值化（来源
  // heatLevelScore，无值不写 key），字符串标签不再进入落库 sector row。
  const heatFactorVersion = themeHeatSnapshot?.factorVersion || 'theme-market-v2'

  return {
    stocks: dataLayer.getStocks() || [],
    depth10ByCode: dataLayer.getDepth10Map(),
    recentTicksByCode: dataLayer.getRecentTicksMap(),
    l2SummaryByCode: dataLayer.getL2SummaryMap(),
    breathData: dataLayer.getBreathData(),
    marketData: dataLayer.getBreathMarketData(),
    hotThemes: (dataLayer.getHotThemes() || []).map((theme: any) => ({
      ...theme,
      ...(typeof theme?.heatLevelScore === 'number' && Number.isFinite(theme.heatLevelScore)
        ? { heatLevel: theme.heatLevelScore }
        : {}),
      metadata: {
        ...(theme?.metadata || {}),
        factorVersion: heatFactorVersion,
      },
    })),
    themeHeatFactors: (themeHeatSnapshot?.factors || []).map((factor) => ({
      ...factor,
      metadata: {
        ...factor.metadata,
        quoteSource,
        fundSource,
        factorVersion: heatFactorVersion,
      },
    })),
    rotationAnalysis: dataLayer.getCurrentRotation(),
    // 原始后端引擎 rotationSummary（camelCase 全字段）；快照构建原样透传，不重序列化
    backendRotationSummary: getBackendRotationSummaryRaw(),
    breathHistory: dataLayer.getBreathHistory(),
    breathFactors: dataLayer.getBreathFactors(),
    marketMode: dataLayer.getMarketMode(),
    stocksVersion: dataLayer.getVersion().stocks,
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `pnpm test && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 全部 PASS。若既有 builders.test.ts 有断言"字符串 heatLevel 透传"的用例失败，按新语义（只写数值）更新该断言，不得恢复字符串写入；类型放宽后若下游出现 `string` 不兼容错误，逐个按「读取侧 _num 判别」修正，禁止改回窄类型。

- [ ] **Step 5: Commit**

```bash
git add src/services/snapshot
git commit -m "feat(theme): 快照 context 行口径标记 + heatLevel 数值透传 + themeHeat 缺失不伪装 0（B9）"
```

---

### Task 17: 阶段 B 收口与浏览器验收

- [ ] **Step 1: 全量验证**

Run: `pnpm test && pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false && pnpm build`
Expected: 全绿。

- [ ] **Step 2: playwright 真实浏览器验收（后端 8000 + 前端 5173 同时在线）**

人工验证清单（design §6 首日验证计划的前端半边）：
1. 题材热度分级不再全判「热门」：`/api/themes/heat` factor 带 heatLevel，热门/活跃/温/冷/冰 分布有层次；
2. DragonBreathPanel 热度数值仍是绝对值量级（3000/1500 阈值生效）；
3. ThemeMomentumPanel / 题材相关面板渲染无控制台错误；
4. 个股 hotness 分布与题材列（themeHeat 显示 0-100）正常；heatScore=null 显示 "--"。

- [ ] **Step 3: Commit（如有修复）**

```bash
git status --short  # 确认只有本计划触碰的文件；计划外文件保持原样不加（评审 M-4，禁 git add -A）
git add src
git commit -m "fix(theme): 阶段 B 浏览器验收修复"
```
（无改动则跳过。）

---

## 阶段 C：文档收口

### Task 18: 文档同步

**Files:**
- Create: `quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-implementation.md`（实施记录）
- Modify: `quant-board/docs/mongodb-migration-plan.md`（快照入库字段：sector row heatLevel 数值语义、stock row themeHeat 语义、研究集合 factor 文档新字段）
- Modify: `quant-board/docs/architecture.md`（heat_level 共享模块与统一消费规则入口）
- Modify: `quant-board/docs/api-cli.md`（`/api/themes/heat` factor 输出新增 heatLevel）
- Modify: `quant-board/docs/theme-rotation/2026-09-02-kpl-hotness-formula-migration.md`（残留 TODO 5 项逐条标注完成去向，指向本设计/计划/实施记录）
- Modify: `quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md`（B7 行级标记决策更新为「不加标记，由 sector 行口径标记 + resolve 派生消歧」，与 Task 11 偏离记录一致）

**Content（实施记录必须包含）:**

```markdown
# heatLevel 落库迁移实施记录（2026-09-03）

- 设计/计划：2026-09-03-heatlevel-persistence-migration-design.md / -plan.md（双 subagent 对抗性评审修订版）
- 阶段 A 改动清单：heat_level.py 共享模块（attach/resolve/口径常量）、heat.py 附加、
  trend（_ts_heat_level 委托 + _build_factor 透传 + ThemeFactorFrame 两字段）、
  collector factor_to_sector 落库（tri-state）+ 派生白名单 SECTOR_FACTOR_FIELDS 放行（H1 同批改）、
  Mongo 投影白名单 HOT_THEME_FRAME_FIELDS、momentum/rotation/backtest 统一走 resolve_heat_level
  （backtest 含 B10 themeHeat 透传切换）、研究集合 _factor_doc、
  stock row themeHeat 语义、SQL/备份 varchar 转文本。
- 阶段 B 改动清单：数据链（types/feed/projector/coordinator/DataLayer/stockThemeMeta/facade）
  + 12 处阈值消费点 + 快照行类型/构建点 + buildContext context 行口径标记与 heatLevel 数值化（B9）。
- golden：trend v14、heat v3（v13/v2 不可变）。
- 统一消费规则（4.2 三分支）唯一实现：backend/analysis/theme/heat_level.py resolve_heat_level。
- 验证：后端全量 pytest / 前端 pnpm test + vue-tsc + playwright 清单结果。
- 首日人工验证清单（design §6）与实际观察结果留空待上线日填写。
```

- [ ] **Step 1: 撰写实施记录**（骨架如上，改动清单按实际 commit 补全）
- [ ] **Step 2: 同步 4 份交叉文档**（各文档新增小节或更新既有字段清单；不重写无关段落）
- [ ] **Step 3: TODO 清单标注**（2026-09-02 文档「残留 TODO」5 项各加一行去向）
- [ ] **Step 4: 交叉检查**

Run: `rg -n "heatLevel" quant-board/docs | head -50` 与 `rg -n "残留 TODO" quant-board/docs/theme-rotation/2026-09-02-kpl-hotness-formula-migration.md`
Expected: 新字段在三份合同文档可检索到；TODO 有去向标注。

- [ ] **Step 5: Commit**

```bash
git add quant-board/docs
git commit -m "docs(theme): heatLevel 落库迁移文档收口（合同/架构/API/TODO 去向）"
```

---

## Self-Review 记录（计划完成后已执行；2026-09-03 双 subagent 对抗性评审修订后复核）

1. **Spec 覆盖**：design §4.3 B1-B10 → Task 1-3（B1）、5（B2 + 白名单放行）、6（B3）、7-9（B4）、10（B5）、7（B6 常量参数化 + THEME_MOMENTUM_VERSION bump 在 Task 7）、11（B7）、12（B8）、16（B9）、9（B10）；§4.4 前端 → Task 14-16；§4.5 golden/测试 → Task 2/4 + 各任务 TDD；§4.6 分阶段 → 阶段 A/B/C 划分与 Task 13/17/18 收口。B7 行级标记偏离已在 Task 11 显式记录并列入 Task 18 设计文档回写。
2. **占位符扫描**：Task 16 Step 1（1b）与 Task 15 Step 1 的测试要求引用同文件既有夹具构造（明确到字段与断言值，Task 15 已核实实际导出名 `calculateStockHotnessRecords` 与夹具 `createStock`）；Task 4/2 的 fixture 值给出计算公式与预期值；其余任务代码全部完整。无 TBD/待定实现。
3. **类型一致性**：`heatLevel: number | null`（TS runtime/api factor）、`heatLevelScore`（PanelSummary 新字段）、`heatLevel: float | None` + `heatFactorVersion: str | None`（Python frame）、`_persisted_heat_level(factor: object)` 签名不变（isinstance 防御，与 Task 9 测试一致）、`resolve_heat_level(row)` 与各消费任务一致、`HOT_THEME_FRAME_FIELDS` 与 Task 6 测试及实际源码 20 键字段集一致。
4. **评审修复复核**：H1（白名单前移 Task 5 同批改，端到端断言可 GREEN）、H2（B9 context 行标记，§4.2 残留歧义结论修正）、H-2a-d（Task 14 四处测试/实现矛盾全部修正，含 `hasFiniteNumber(null)===true` 陷阱）、M1-M6 与 L1-L3（设计侧与计划侧对应落点均已合入）、M-1-M-5（计划侧 RED 预期、签名措辞、hotness 判别用例、git add 显式路径、命令 bash 兼容）。
