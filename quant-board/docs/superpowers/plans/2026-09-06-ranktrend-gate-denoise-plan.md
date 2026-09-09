# 环境门去噪：多帧确认 + 迟滞实施计划（WP2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** lifecycle veto 与 B/D 环境降档增加可配的连续 K 帧确认、regime score 增加可配 EMA 与 strong 边界迟滞，默认参数（K=1/α=1/迟滞关）下零行为变化，消除 half_hour 帧粒度的门控单帧抖动。

**Architecture:** 不改 `lifecycle_decision`/`_synergy_tier`/`market_regime` 纯函数本体（golden 安全）——确认层与平滑层挂在调用侧：`GateConfirmState` 纯状态机（per-code 连续计数）在 `_build_signal` 内对 veto 结果与 lc_tier 值做确认；`RegimeSmoother` 包装 market_regime 输出。确认/平滑仅在"帧序列上下文"（replay、live frames 链路）激活，单股单帧链路每请求新建实例且上下文未激活 → 直通 = 现行为。

**Tech Stack:** Python 3 / pytest（Fake 无需 DB）。

**Spec:** `quant-board/docs/superpowers/specs/2026-09-06-ranktrend-gate-denoise-design.md`

**前置：** WP3.2 翻转率诊断脚本先行（`2026-09-06-ranktrend-acceptance-metrics-plan.md` Task 1-2，产出基线）；WP1c 消 lookahead 后才允许 2c 调参扫描（非本轮）。编码本身不依赖 WP1。

## Global Constraints

- **默认零行为变化是最高约束**：K=1、α=1.0、迟滞关闭时，全部现有测试（含 `tests/test_ranktrend_golden_alignment.py`）必须原样通过，golden 不漂移。
- **fail-visible**：被单帧翻转抑制的 veto/降档必须在 reasons 可见；平滑生效时 regime reasons 标注。
- 不给 lifecycle 加方向投票；不改 `market_regime` 打分构成；不改门禁参数默认值。
- 确认层状态只存活于引擎实例/请求级；`replay_frame_at` 与单股单帧链路必须保持现行为。
- 测试位置：`quant-board/tests/*.py`；pytest 只跑相关子集（全量有挂起问题，先 `--collect-only`）。
- 新参数进 `RankTrendConfig` 并登记 `docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`（8 月冻结纪律：默认值即现行为，未经 2c 证实不得改）。
- commit 风格 `feat(ranktrend): 中文描述`。

## 源文件坐标（执行者必读）

| 内容 | 位置 |
|---|---|
| lifecycle_decision 纯函数（**不动**） | `quant-board/backend/analysis/ranktrend/trend/lifecycle.py:215`；**返回键集合 = `action/confidence/reasons/discovery/evidence`，无 `veto` 布尔键——veto 恒以 `action == "veto"` 表达**（反证锚点：`tests/test_ranktrend_engine.py:276` 夹具 `"decision": {"action": "veto"}`） |
| _synergy_tier 纯函数（**不动**） | `quant-board/backend/analysis/ranktrend/ranking/volume_price.py:292-368`（E 连锁 L316-317、B/D 降档 L364-367，文本逐字 `"周期 {lc_tier} 环境降档"`） |
| assemble_observation（**加 1 个可选参数**） | `volume_price.py:371-417`；L409 内部取 `observation["lifecycle"]["signalTier"]` 作为 lc_tier 传入 _synergy_tier |
| lc_tier 真实来源 | `runtime.py:407` `compose_observation_scores` 经 `_lifecycle_tier_as_dict(cycle["stage"], action)` 写 `observation["lifecycle"]["signalTier"]`——**action 被确认层改写后该值自动跟随** |
| _build_signal（**接线点 A/B**） | `quant-board/backend/analysis/ranktrend/engine/runtime.py:1031-1110`（L1047 `code = str(stock.get("code") or "")` 现成局部变量、L1075-1077 `cycle = analyze_cycle_with_risk(...)`、L1078 compose_decision（只读 `cycle["stage"]`）、L1079-1081 compose_analysis_candidate_tier、L1083-1088 compose_observation_scores、L1090 tier_source） |
| action 的全部下游消费点（确认层改 action 后自动跟随） | `_lifecycle_tier` runtime.py:351、`compose_observation_scores` L404/407、`compose_strategy` L454、`compose_analysis_candidate_tier` L775、交易侧 `_lifecycle_decision_action` execution.py:883-886（读 `decision.get("action")`） |
| replay 帧循环（**接线点 C/D**） | `runtime.py:845-916`（L860 `self._atr_meta_by_code = {}` 初始化先例、L869 帧循环、L903 `regime = market_regime(frame)`；方法内无局部 `config`，引擎配置一律 `self.config`） |
| market_regime（**不动**） | `quant-board/backend/analysis/ranktrend/trend/risk.py:74`（state 判定 L149-154、`REGIME_STRONG_SCORE = 70.0` L67、返回 dict 仅 state/score/reasons 三键） |
| 引擎实例级跨帧容器先例 | `runtime.py:1169` `setdefault` 模式（`_atr_meta_by_code`） |
| live 单股链路（**必须直通**） | `ranktrend_routes.py:364 _analyze_one_stock`（进程池 worker 纯函数，args 尾部 `*history_args`：price_changes/amount_history/atr_history；L380 每 task 新建 `RankTrendPythonEngine(config=config)`） |
| live frames 链路（**需激活上下文**） | `ranktrend_routes.py:471 _analyze_frames`：**串行执行**（L587-590 注释明确"进程池是负优化，统一串行"，`results = [_analyze_one_stock(task) for task in full_tasks]`）；L580-585 构造 full_tasks；`main.py:931` 保持直通（非范围） |
| RankTrendConfig 参数区 | `quant-board/backend/analysis/ranktrend/engine/config.py`（`@dataclass`，L7-8；regime 门控参数 L115-120） |
| golden 对齐测试 | `quant-board/tests/test_ranktrend_golden_alignment.py`（`_make_frames` 帧工厂可复用）；replay 真实引擎测试另见 `tests/test_ranktrend_replay_resonance.py` |
| compose_analysis_candidate_tier | `runtime.py:753-766`（regime 门禁，内部读 action——自动跟随） |

### 关键设计定稿（2026-09-06 审查修订版）

1. **veto 确认改写的是 `cycle["decision"]["action"]`**（后端无 `veto` 布尔键）：本帧 `action == "veto"` 视为触发条件，用 `GateConfirmState.confirmed_value(code, action, when_in=("veto",), default="caution")` 连续确认——连续达 K 帧保持 `"veto"`；未达 K 帧改写为该 code 上一帧已确认的非 veto action（首帧无历史用 `"caution"`，spec"档位维持前一帧结果"的落地语义；首帧边界为计划显式声明）。reasons 追加 `gate_reason` 不变。改写 action 后全部下游（E 连锁、candidate tier、observation、交易门控）自动跟随。
2. **B/D 降档确认走 `assemble_observation` 新增可选参数 `lc_tier_override`**（默认 None = 现行为零变化）：`_build_signal` 在组装 observation 后、调 `assemble_observation` 前对 `observation["lifecycle"]["signalTier"]` 做确认，未达 K 帧时把确认值经 `lc_tier_override` 传入（仅影响 synergy 连锁降档判断），**`observation.lifecycle.signalTier` 发布输出保持原始值**；tierReasons 追加抑制标注。抑制文案 `"周期 {tier} 环境降档 单帧确认未达（streak/K），暂缓"` 与 WP3.2 翻转提取器的精确锚点（`re.fullmatch(r"周期 [BD] 环境降档")`）互不误配——两计划协同约定，任一方不得单独改文案。
3. **上下文激活**：replay 入口自建 `GateConfirmState` + `self._gate_confirm_ctx = {"active": True}`、出口复位；live frames 链路由 `_analyze_frames` 构造**请求级** `GateConfirmState` 随 full_tasks args 尾部传入（串行执行，同一实例贯穿全部 task），`_analyze_one_stock` 解包到 `history_args[3]`，非 None 时挂到 engine 实例并置 active——不传（单股链路/replay_frame_at/main.py:931）则 ctx 不激活，直通 = 现行为。`_build_signal` 内仅 `ctx.active and K > 1` 才走确认，per-code 键用 L1047 现成局部变量 `code`。
4. **RegimeSmoother 直通保障**：α=1.0 且迟滞关时 `smooth()` 原样返回 market_regime 的 dict（不做任何替换）；迟滞关闭时 state 恒为 market_regime 原值（EMA 只在迟滞开启时参与 strong 边界重判）；迟滞只作用于 strong↔非 strong 边界（门禁仅消费 strong）。

---

### Task 1: GateConfirmState 纯状态机

**Files:**
- Create: `quant-board/backend/analysis/ranktrend/trend/gate_confirm.py`
- Test: `quant-board/tests/test_gate_confirm_state.py`（新建）

**Interfaces:**
- Produces（后续 Task 依赖）:
  - `GateConfirmState(required_frames: int = 1)`；`required_frames` 属性只读。
  - `reset() -> None`：清空全部 per-key 状态（replay 入口调用，保证两次 replay 互不污染）。
  - `confirm(key: str, *, condition: bool) -> bool`：condition 连续成立达 K 帧返回 True；中断（condition=False）清零该 key 并返回 False；K<=1 恒返回 condition（直通）。**通用 API，本计划接线不使用**（veto 确认走 `confirmed_value`，见 Task 3——后端 decision 无 veto 布尔键）。
  - `streak(key: str) -> int`：当前连续成立计数（reasons 文案用）。
  - `confirmed_value(key: str, value: str, *, when_in: tuple[str, ...], default: str) -> str`：value ∈ when_in 视为条件成立，连续达 K 返回 value 并记忆为该 key 已确认值；未达返回已确认值（无则 default）；value ∉ when_in 清零计数、更新已确认值为 value 并原样返回。K<=1 恒返回 value（直通）。
  - 模块级便捷函数 `gate_reason(label: str, streak: int, required: int) -> str`：统一 reasons 文案（如 `"周期 veto 单帧确认未达（1/2），暂缓"`）。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState, gate_reason


def test_k1_passthrough_matches_condition():
    state = GateConfirmState(required_frames=1)
    assert state.confirm("c1", condition=True) is True
    assert state.confirm("c2", condition=False) is False


def test_k2_requires_consecutive_true_frames():
    state = GateConfirmState(required_frames=2)
    assert state.confirm("c1", condition=True) is False      # 第 1 帧：未达
    assert state.streak("c1") == 1
    assert state.confirm("c1", condition=True) is True       # 第 2 帧：确认
    assert state.confirm("c1", condition=True) is True       # 已确认持续


def test_k2_interrupt_resets_streak():
    state = GateConfirmState(required_frames=2)
    state.confirm("c1", condition=True)
    assert state.confirm("c1", condition=False) is False     # 中断清零
    assert state.streak("c1") == 0
    assert state.confirm("c1", condition=True) is False      # 重新计 1 帧不够
    assert state.confirm("c1", condition=True) is True


def test_keys_are_isolated():
    state = GateConfirmState(required_frames=2)
    state.confirm("a", condition=True)
    assert state.confirm("b", condition=True) is False       # b 的计数独立


def test_reset_clears_all_keys():
    state = GateConfirmState(required_frames=2)
    state.confirm("a", condition=True)
    state.reset()
    assert state.streak("a") == 0
    assert state.confirm("a", condition=True) is False


def test_confirmed_value_holds_previous_until_k_reached():
    state = GateConfirmState(required_frames=2)
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "C"   # 首帧未达 → default
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "B"   # 第 2 帧达 → B


def test_confirmed_value_non_trigger_value_updates_baseline():
    state = GateConfirmState(required_frames=2)
    state.confirmed_value("s1", "A", when_in=("B", "D"), default="C")                 # A 非 B/D：基线 A
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "A"   # 未达 → 保持 A


def test_confirmed_value_k1_passthrough():
    state = GateConfirmState(required_frames=1)
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "B"


def test_gate_reason_format():
    assert gate_reason("周期 veto", 1, 2) == "周期 veto 单帧确认未达（1/2），暂缓"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_state.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_state.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

```python
"""门控多帧确认状态机（WP2a）。

纯状态、无 I/O：per-key 连续计数 + 已确认值记忆。默认 K=1 直通 = 现行为。
状态生命周期归引擎实例/请求级持有；replay 入口必须 reset()（两次 replay 互不污染）。
"""
from __future__ import annotations

from typing import Dict


def gate_reason(label: str, streak: int, required: int) -> str:
    return f"{label} 单帧确认未达（{streak}/{required}），暂缓"


class GateConfirmState:
    """布尔门（veto）与值门（lc_tier B/D）共用的连续 K 帧确认状态机。"""

    def __init__(self, required_frames: int = 1) -> None:
        self._required = max(int(required_frames), 1)
        self._streaks: Dict[str, int] = {}
        self._confirmed: Dict[str, str] = {}

    @property
    def required_frames(self) -> int:
        return self._required

    def reset(self) -> None:
        self._streaks.clear()
        self._confirmed.clear()

    def streak(self, key: str) -> int:
        return self._streaks.get(key, 0)

    def confirm(self, key: str, *, condition: bool) -> bool:
        if self._required <= 1:
            return bool(condition)
        if not condition:
            self._streaks[key] = 0
            return False
        self._streaks[key] = self.streak(key) + 1
        return self._streaks[key] >= self._required

    def confirmed_value(
        self,
        key: str,
        value: str,
        *,
        when_in: tuple[str, ...],
        default: str,
    ) -> str:
        if self._required <= 1 or value not in when_in:
            if value not in when_in:
                self._streaks[key] = 0
                self._confirmed[key] = value
            return value
        self._streaks[key] = self.streak(key) + 1
        if self._streaks[key] >= self._required:
            self._confirmed[key] = value
            return value
        return self._confirmed.get(key, default)
```

- [ ] **Step 4: 测试通过 + 提交**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_state.py -v`
Expected: 全部 PASS。

```bash
git add quant-board/backend/analysis/ranktrend/trend/gate_confirm.py quant-board/tests/test_gate_confirm_state.py
git commit -m "feat(ranktrend): GateConfirmState 门控连续 K 帧确认状态机（K=1 直通）"
```

---

### Task 2: RankTrendConfig 三参数 + L1 档案登记

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend/engine/config.py:115-120`（regime 门控参数区后追加）
- Modify: `docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`（新增组条目）
- Test: `quant-board/tests/test_ranktrend_config_denoise_params.py`（新建）

**Interfaces:**
- Produces（Task 3/4/5 依赖，字段名必须一致）:
  - `RankTrendConfig.lifecycleConfirmFrames: int = 1`
  - `RankTrendConfig.regimeScoreEmaAlpha: float = 1.0`
  - `RankTrendConfig.regimeStateHysteresis: bool = False`
  - `RankTrendConfig.regimeStrongHysteresisBand: float = 5.0`（strong 退出阈值 = 进入阈值 − band）

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.engine.config import RankTrendConfig


def test_denoise_defaults_are_current_behavior():
    config = RankTrendConfig()
    assert config.lifecycleConfirmFrames == 1
    assert config.regimeScoreEmaAlpha == 1.0
    assert config.regimeStateHysteresis is False
    assert config.regimeStrongHysteresisBand == 5.0


def test_denoise_params_accept_overrides():
    config = RankTrendConfig(
        lifecycleConfirmFrames=3,
        regimeScoreEmaAlpha=0.5,
        regimeStateHysteresis=True,
        regimeStrongHysteresisBand=6.0,
    )
    assert config.lifecycleConfirmFrames == 3
    assert config.regimeScoreEmaAlpha == 0.5
    assert config.regimeStateHysteresis is True
    assert config.regimeStrongHysteresisBand == 6.0
```

（若 `RankTrendConfig` 是 dataclass/TypedDict/pydantic 之外的自定义构造，测试按现有测试文件对 config 的构造惯例调整——`rg "RankTrendConfig(" quant-board/tests` 参照既有用法，断言字段名不变。）

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_config_denoise_params.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_config_denoise_params.py -v`

- [ ] **Step 3: 实现（config.py L120 后追加四字段，风格与相邻参数一致）**

```python
    # WP2 环境门去噪参数（默认值 = 现行为；L1 档案登记，未经 longterm-test 证实不得改默认）
    lifecycleConfirmFrames: int = 1        # veto/B-D 降档连续确认帧数
    regimeScoreEmaAlpha: float = 1.0       # regime score EMA 系数（1=直通）
    regimeStateHysteresis: bool = False    # strong 边界迟滞开关
    regimeStrongHysteresisBand: float = 5.0  # strong 退出阈值 = 进入阈值 - band
```

- [ ] **Step 4: L1 档案登记（新组条目，跟随该文档现有组格式）**

在 `ranktrend-l1-param-ledger.md` 按现有条目格式追加（该文档为 `## N. 标题` 节 + 表格结构，执行时照抄相邻节的表头）：

```markdown
## N. 环境门去噪参数（WP2，2026-09-06）

| 参数 | 默认值 | 语义 | 状态 |
|---|---|---|---|
| lifecycleConfirmFrames | 1 | veto/B-D 降档连续确认帧数（1=单帧即触发，现行为） | 待扫描 |
| regimeScoreEmaAlpha | 1.0 | regime score EMA 系数（1=直通） | 待扫描 |
| regimeStateHysteresis | false | strong 边界迟滞开关 | 待扫描 |
| regimeStrongHysteresisBand | 5.0 | strong 退出阈值 = 进入阈值(70.0) − band | 待扫描 |

- 扫描前置条件：WP1c lookahead 修复 + WP3.2 翻转率基线；K∈{1,2,3}、α 档位单变量。
- 冻结纪律：未经 longterm-test 流程"证实"，默认值不得变更。
```

- [ ] **Step 5: 测试通过 + 提交**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_config_denoise_params.py -v`
Expected: PASS。

```bash
git add quant-board/backend/analysis/ranktrend/engine/config.py quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md quant-board/tests/test_ranktrend_config_denoise_params.py
git commit -m "feat(ranktrend): 环境门去噪三参数入 RankTrendConfig + L1 档案登记"
```

---

### Task 3: veto（action）K 帧确认接线（上下文激活 + 单股直通）

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend/engine/runtime.py`（`_build_signal` L1075-1077 后插入确认；`replay` 入口激活/出口复位；引擎惰性挂状态容器）
- Modify: `quant-board/backend/api/ranktrend_routes.py`（`_analyze_frames` L580-585 请求级 state 随 args 传入；`_analyze_one_stock` L364 解包 history_args[3]）
- Test: `quant-board/tests/test_gate_confirm_wiring.py`（新建）

**Interfaces:**
- Consumes: Task 1 `GateConfirmState`/`gate_reason`、Task 2 `config.lifecycleConfirmFrames`。
- Produces:
  - `_build_signal` 内确认（改写 `cycle["decision"]["action"]`）：`ctx.active and K > 1` 且本帧 `action == "veto"` 时，`confirmed_value(code, action, when_in=("veto",), default="caution")` 未达 K → action 改写为返回值 + reasons 追加。
  - 引擎实例属性 `self._gate_confirm_state`（GateConfirmState）、`self._gate_confirm_ctx = {"active": bool}`（默认 False = 直通）。
  - `_analyze_one_stock` args 尾部第 4 个可选上下文 `gate_confirm_state`（`history_args[3]`，None = 直通）——沿用 price_changes/amount_history/atr_history 的追加传参先例。
  - `_analyze_frames` 请求级 `GateConfirmState` 实例，追加进每个 full_task。

- [ ] **Step 0: 精读定位（执行者必做）**

`rg -n "analyze_cycle_with_risk|code = str\(stock.get" quant-board/backend/analysis/ranktrend/engine/runtime.py` → 核对 `_build_signal` 内 cycle 产出点（约 L1075-1077）、compose_decision（约 L1078，只读 `cycle["stage"]`）、`code` 局部变量（约 L1047）。`cycle["decision"]` 的键集合为 `action/confidence/reasons/discovery/evidence`（无 `veto` 布尔键），确认层只操作 `action`。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState


def _apply_action_confirm(state: GateConfirmState, active: bool, code: str, cycle: dict) -> dict:
    """与 _build_signal 插入段等价的确认逻辑（集成断言由 Step 4 的真实引擎 replay 用例覆盖）。"""
    decision = cycle.setdefault("decision", {})
    action = str(decision.get("action") or "")
    required = state.required_frames
    if active and required > 1 and action == "veto":
        from backend.analysis.ranktrend.trend.gate_confirm import gate_reason

        confirmed = state.confirmed_value(code, action, when_in=("veto",), default="caution")
        if confirmed != action:
            decision["action"] = confirmed
            decision.setdefault("reasons", []).append(gate_reason("周期 veto", state.streak(code), required))
    return cycle


def test_veto_action_suppressed_on_first_frame_with_reason():
    state = GateConfirmState(required_frames=2)
    cycle = {"decision": {"action": "veto", "reasons": ["周期退潮"]}}
    result = _apply_action_confirm(state, True, "000001", cycle)
    assert result["decision"]["action"] == "caution"        # 首帧未达 → default
    assert any("确认未达（1/2）" in str(reason) for reason in result["decision"]["reasons"])
    assert "周期退潮" in result["decision"]["reasons"]       # 原因保留


def test_veto_action_holds_previous_non_veto_action():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "confirm", "reasons": []}})  # 基线 confirm
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    assert cycle["decision"]["action"] == "confirm"         # 未达 → 维持上一帧已确认 action


def test_veto_action_confirmed_on_second_consecutive_frame():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    assert cycle["decision"]["action"] == "veto"            # 连续第 2 帧：真 veto


def test_non_veto_action_updates_baseline_and_passthrough():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "caution", "reasons": []}})
    assert cycle["decision"]["action"] == "caution"         # 非 veto 直通 + 基线更新（中断计数）


def test_inactive_or_k1_passthrough():
    state = GateConfirmState(required_frames=2)
    cycle = {"decision": {"action": "veto", "reasons": []}}
    assert _apply_action_confirm(state, False, "000001", cycle)["decision"]["action"] == "veto"  # 单股链路直通
    state1 = GateConfirmState(required_frames=1)
    cycle1 = {"decision": {"action": "veto", "reasons": []}}
    assert _apply_action_confirm(state1, True, "000001", cycle1)["decision"]["action"] == "veto"  # K=1 现行为
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_wiring.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_wiring.py -v`
Expected: FAIL（`_apply_action_confirm` 未定义——本文件测试先以纯逻辑函数锁行为；Step 3 接线后补真实引擎集成用例）。

- [ ] **Step 3: 实现**

`runtime.py` `_build_signal` 内 L1077 `cycle = analyze_cycle_with_risk(...)` 之后、`compose_decision`（L1078）之前插入（`code` 用约 L1047 的现成局部变量）：

```python
        # WP2a：lifecycle veto（action）多帧确认（K>1 且帧序列上下文才生效；K=1 直通 = 现行为）。
        # 后端 decision 无 veto 布尔键，veto 恒以 action=="veto" 表达；抑制时改写 action，
        # 下游 _lifecycle_tier（不产 E）/E 连锁/compose_analysis_candidate_tier/compose_observation_scores/
        # compose_strategy/交易侧 _lifecycle_decision_action 全部自动跟随。
        self._gate_confirm_state = getattr(self, "_gate_confirm_state", None) or GateConfirmState(
            required_frames=int(getattr(self.config, "lifecycleConfirmFrames", 1))
        )
        self._gate_confirm_ctx = getattr(self, "_gate_confirm_ctx", None) or {"active": False}
        _decision = cycle.setdefault("decision", {})
        _action = str(_decision.get("action") or "")
        if (
            self._gate_confirm_ctx.get("active")
            and self._gate_confirm_state.required_frames > 1
            and _action == "veto"
        ):
            _confirmed_action = self._gate_confirm_state.confirmed_value(
                code, _action, when_in=("veto",), default="caution"
            )
            if _confirmed_action != _action:
                _decision["action"] = _confirmed_action
                _decision.setdefault("reasons", []).append(
                    gate_reason("周期 veto", self._gate_confirm_state.streak(code), self._gate_confirm_state.required_frames)
                )
        # 其余情况（未激活 / K=1 / 非 veto action）：直通，不触碰状态与决策。
```

（`GateConfirmState`/`gate_reason` 加进 runtime.py 顶部 `from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState, gate_reason`；`self.config` 为引擎配置访问方式，方法内无局部 `config`。）

`replay` 入口（`self._atr_meta_by_code = {}` L860 旁）与出口复位（try/finally 包裹帧循环或对称复位）：

```python
        # WP2a：本次 replay 独占确认状态（两次 replay 互不污染）
        self._gate_confirm_state = GateConfirmState(
            required_frames=int(getattr(self.config, "lifecycleConfirmFrames", 1))
        )
        self._gate_confirm_ctx = {"active": True}
        try:
            ...  # 原帧循环
        finally:
            self._gate_confirm_ctx = {"active": False}
```

`ranktrend_routes.py` `_analyze_frames`（L580-585）：请求级 state 随 args 传入（串行执行，同一实例贯穿全部 task）：

```python
    # WP2a：请求级门控确认状态（_analyze_frames 串行执行，同一实例贯穿全部 full_task；
    # 单股链路不传该参数 → history_args[3] 为 None → 直通 = 现行为）
    gate_confirm_state = GateConfirmState(
        required_frames=int(getattr(engine.config, "lifecycleConfirmFrames", 1))
    )
    ...
            full_tasks.append((
                engine.config, stock, frame, ranks, percentiles, regime, hot_themes,
                momentum_v2_ctx, market_median, market_sample_count, market_median_percentile,
                price_changes, amount_history,
                atr_history,
                gate_confirm_state,
            ))
```

（文件顶部 `from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState`。）

`ranktrend_routes.py` `_analyze_one_stock`（L372-399）：解包与挂载：

```python
    price_changes = history_args[0] if history_args else None
    amount_history = history_args[1] if len(history_args) > 1 else None
    atr_history = history_args[2] if len(history_args) > 2 else None
    gate_confirm_state = history_args[3] if len(history_args) > 3 else None
    engine = RankTrendPythonEngine(config=config)
    if gate_confirm_state is not None:
        # WP2a：live frames 链路（_analyze_frames 串行）传入请求级确认状态；单股链路不传 → 直通
        engine._gate_confirm_state = gate_confirm_state
        engine._gate_confirm_ctx = {"active": True}
```

（`main.py:931` 链路与 `replay_frame_at` 不传该参数，ctx 恒不激活，直通。）

- [ ] **Step 4: 真实引擎集成断言（硬性，不可省略）+ 回归**

在 `tests/test_gate_confirm_wiring.py` 追加真实 replay 用例：复用 `tests/test_ranktrend_replay_resonance.py` 或 `tests/test_ranktrend_golden_alignment.py` 的 `_make_frames` 帧工厂（`rg -n "def _make_frames" quant-board/tests` 取其一），构造 K=2、3 帧序列——帧 1 该股 action 非 veto、帧 2/3 veto——断言 `signals` 中帧 2 的 `rankTrend.cycle.decision.action != "veto"` 且 reasons 含"确认未达（1/2）"、帧 3 `action == "veto"`；再以默认 K=1 配置跑同帧序列断言帧 2 直接 `action == "veto"`（现行为对照）。

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_wiring.py tests/test_gate_confirm_state.py tests/test_ranktrend_config_denoise_params.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_wiring.py tests/test_gate_confirm_state.py tests/test_ranktrend_config_denoise_params.py -v && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_golden_alignment.py -v && .venv/Scripts/python.exe -m pytest tests/ -k "analyze_one_stock or ranktrend_routes" -v`
Expected: 全部 PASS，golden 无漂移，live 单股链路既有测试无回归。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/ranktrend/engine/runtime.py quant-board/backend/api/ranktrend_routes.py quant-board/tests/test_gate_confirm_wiring.py
git commit -m "feat(ranktrend): lifecycle veto(action) 连续 K 帧确认接线（帧序列上下文激活，单股直通）"
```

---

### Task 4: B/D 环境降档 lc_tier 确认（assemble_observation 加 lc_tier_override）

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend/ranking/volume_price.py`（`assemble_observation` 加可选参数 `lc_tier_override: str | None = None`）
- Modify: `quant-board/backend/analysis/ranktrend/engine/runtime.py`（`_build_signal` 组装 observation 后、调 `assemble_observation` 前插入确认）
- Test: `quant-board/tests/test_gate_confirm_bd_tier.py`（新建）

**Interfaces:**
- Consumes: Task 1 `GateConfirmState.confirmed_value`/`gate_reason`、Task 3 已挂载的 `self._gate_confirm_state`/`_gate_confirm_ctx`。
- Produces:
  - `assemble_observation(..., lc_tier_override: str | None = None)`：None 时内部照旧取 `observation["lifecycle"]["signalTier"]`（volume_price.py:409 现逻辑零变化）；传值时以 override 作为 lc_tier 传入 `_synergy_tier`（仅影响 synergy 连锁降档判断）。
  - `_build_signal` 确认段：`ctx.active and K > 1` 且 `observation["lifecycle"]["signalTier"] ∈ {"B","D"}` 连续未达 K → `lc_tier_override` 传确认值 + tierReasons 追加抑制标注；`observation.lifecycle.signalTier` 发布输出保持原始值。
  - 抑制文案 `f"周期 {tier} 环境降档 单帧确认未达（{streak}/{K}），暂缓"`——与 WP3.2 翻转提取器的精确锚点 `re.fullmatch(r"周期 [BD] 环境降档")` 互不误配（跨计划协同约定，不得单独修改任一侧）。

- [ ] **Step 0: 精读定位（执行者必做）**

`rg -n "signalTier" quant-board/backend/analysis/ranktrend/ranking/volume_price.py quant-board/backend/analysis/ranktrend/engine/runtime.py` → 确认两处：`assemble_observation` 内 lc_tier 取值（约 volume_price.py:409）与 `compose_observation_scores` 的 signalTier 写入（runtime.py:407 `_lifecycle_tier_as_dict(cycle["stage"], action)`——action 被 Task 3 确认层改写后该值自动跟随，故本 Task 只处理 B/D 值确认、不碰 E）。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.ranking.volume_price import assemble_observation
from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState, gate_reason


def _apply_bd_confirm(state: GateConfirmState, active: bool, code: str, lc_tier: str, reasons: list[str]) -> str | None:
    """与 _build_signal 插入段等价的确认逻辑：返回 lc_tier_override（None = 不 override）。"""
    required = state.required_frames
    if active and required > 1 and lc_tier in ("B", "D"):
        confirmed = state.confirmed_value(code, lc_tier, when_in=("B", "D"), default="C")
        if confirmed != lc_tier:
            reasons.append(gate_reason(f"周期 {lc_tier} 环境降档", state.streak(code), required))
            return confirmed
        return None                                    # 达 K：不 override，用原始值
    if lc_tier not in ("B", "D"):
        state.confirmed_value(code, lc_tier, when_in=("B", "D"), default="C")  # 非 B/D 帧更新基线
    return None


def test_bd_downgrade_held_on_first_frame():
    state = GateConfirmState(required_frames=2)
    reasons: list[str] = []
    override = _apply_bd_confirm(state, True, "000001", "D", reasons)
    assert override == "C"                                 # 首帧 D 未达 → override 为 C
    assert any("确认未达（1/2）" in reason for reason in reasons)


def test_bd_downgrade_passes_on_second_frame():
    state = GateConfirmState(required_frames=2)
    _apply_bd_confirm(state, True, "000001", "D", [])
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "D", reasons) is None  # 连续第 2 帧 → 生效，不 override
    assert not any("确认未达" in reason for reason in reasons)


def test_bd_interrupt_returns_to_baseline():
    state = GateConfirmState(required_frames=2)
    _apply_bd_confirm(state, True, "000001", "D", [])
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "A", reasons) is None  # 中断：基线更新为 A
    reasons2: list[str] = []
    override = _apply_bd_confirm(state, True, "000001", "D", reasons2)
    assert override == "A"                                 # 重新 1 帧不够 → 维持 A


def test_e_chain_not_touched_by_bd_confirm():
    state = GateConfirmState(required_frames=2)
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "E", reasons) is None  # E 不在 when_in：直通
    assert not reasons


def test_inactive_or_k1_passthrough():
    state = GateConfirmState(required_frames=2)
    assert _apply_bd_confirm(state, False, "000001", "D", []) is None      # 未激活：现行为
    state1 = GateConfirmState(required_frames=1)
    assert _apply_bd_confirm(state1, True, "000001", "D", []) is None      # K=1：现行为


def test_suppression_reason_not_matched_by_wp32_anchor():
    """跨计划协同：抑制文案不得被 WP3.2 的精确锚点（周期 [BD] 环境降档）误判为真实降档。"""
    import re

    suppression = gate_reason("周期 D 环境降档", 1, 2)
    assert re.fullmatch(r"周期 [BD] 环境降档", suppression) is None        # 带后缀 → 不误配
    assert re.fullmatch(r"周期 [BD] 环境降档", "周期 D 环境降档") is not None  # 真实降档文案命中
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_bd_tier.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_bd_tier.py -v`
Expected: FAIL（`assemble_observation` 无 `lc_tier_override` 参数 / `_apply_bd_confirm` 未定义）。

- [ ] **Step 3: 实现**

`volume_price.py` `assemble_observation` 签名加参，lc_tier 取值处（约 L409）改为：

```python
def assemble_observation(..., lc_tier_override: str | None = None) -> dict:
    ...
    # WP2a：B/D 降档确认 override（None = 现行为，照旧取 lifecycle.signalTier）
    lc_tier = str(lc_tier_override) if lc_tier_override else str(
        (observation.get("lifecycle") or {}).get("signalTier") or ""
    )
```

（其余逻辑不动；`_synergy_tier` 调用与 `observation["synergy"]["signalTier"/"tierReasons"]` 写入照旧。）

`runtime.py` `_build_signal` 内 observation 组装（compose_observation_scores 之后）、`assemble_observation(...)` 调用前插入：

```python
        # WP2a：B/D 环境降档连续确认（K>1 且激活时；E 连锁由 Task 3 的 action 确认覆盖）。
        # 仅 override synergy 侧判断，observation.lifecycle.signalTier 发布输出保持原始值。
        self._gate_confirm_ctx = getattr(self, "_gate_confirm_ctx", None) or {"active": False}
        lc_tier_override = None
        if self._gate_confirm_ctx.get("active") and self._gate_confirm_state.required_frames > 1:
            _raw_lc = str((observation.get("lifecycle") or {}).get("signalTier") or "")
            lc_tier_override = _apply_bd_confirm(  # 逻辑内联：confirmed_value + 抑制 reasons
                self._gate_confirm_state, True, code, _raw_lc,
                (observation.setdefault("synergy", {}).setdefault("tierReasons", [])),
            )
```

（`code` 为约 L1047 现成局部变量；`observation` 为 compose_observation_scores 产出变量，执行时以实际变量名为准；`assemble_observation(...)` 调用追加实参 `lc_tier_override=lc_tier_override`。）

- [ ] **Step 4: 回归（含 golden 与 E 连锁既有测试）**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_bd_tier.py tests/test_gate_confirm_wiring.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_bd_tier.py tests/test_gate_confirm_wiring.py -v && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_golden_alignment.py -v && .venv/Scripts/python.exe -m pytest tests/ -k "synergy or volume_price or observation" -v`
Expected: 全部 PASS；`lc_tier_override=None` 默认下 assemble_observation 既有行为零变化（golden 覆盖）。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/ranktrend/ranking/volume_price.py quant-board/backend/analysis/ranktrend/engine/runtime.py quant-board/tests/test_gate_confirm_bd_tier.py
git commit -m "feat(ranktrend): B/D 环境降档连续 K 帧确认（lc_tier_override，E 连锁跟随 action 确认）"
```

---

### Task 5: RegimeSmoother（EMA + strong 边界迟滞）

**Files:**
- Create: `quant-board/backend/analysis/ranktrend/trend/regime_smoother.py`
- Modify: `quant-board/backend/analysis/ranktrend/engine/runtime.py`（replay L903 `regime = market_regime(frame)` 处挂 smoother）
- Test: `quant-board/tests/test_regime_smoother.py`（新建）

**Interfaces:**
- Consumes: Task 2 `regimeScoreEmaAlpha`/`regimeStateHysteresis`/`regimeStrongHysteresisBand`；strong 进入阈值常量（`rg -n "REGIME_" quant-board/backend/analysis/ranktrend/trend/risk.py` 取实际常量名与值，下文以 `REGIME_STRONG_SCORE` 代称）。
- Produces:
  - `RegimeSmoother(alpha: float = 1.0, hysteresis: bool = False, strong_enter: float = <REGIME_STRONG_SCORE 值>, strong_exit_band: float = 5.0)`。
  - `smooth(regime: dict) -> dict`：直通条件（`alpha >= 1.0 and not hysteresis`）**原样返回同一 dict 引用**（零漂移保障）；否则返回浅拷贝：`score` 换 EMA、迟滞开启时按 strong 边界重判 state、`reasons` 追加 `"regime score EMA 平滑生效（α=…）"`。
  - `reset() -> None`：清 EMA 与 prev_state（replay 入口调用，与确认状态同批）。
  - state 重判仅 strong↔非 strong 边界：EMA ≥ strong_enter → 允许进入 strong；prev_state=="strong" 且 EMA ≥ strong_enter − band → 保持 strong；其余用 market_regime 原值。

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from backend.analysis.ranktrend.trend.regime_smoother import RegimeSmoother


def _regime(score: float, state: str) -> dict:
    return {"score": score, "state": state, "reasons": [f"score={score}"]}


def test_passthrough_returns_same_dict_when_default_params():
    smoother = RegimeSmoother()  # alpha=1.0, hysteresis=False
    regime = _regime(80.0, "strong")
    assert smoother.smooth(regime) is regime          # 同一引用：零行为变化


def test_ema_smooths_score_with_alpha():
    smoother = RegimeSmoother(alpha=0.5)
    out1 = smoother.smooth(_regime(80.0, "strong"))
    assert out1["score"] == 80.0                      # 首帧 ema=score
    out2 = smoother.smooth(_regime(60.0, "normal"))
    assert out2["score"] == 70.0                      # 0.5*60 + 0.5*80
    out3 = smoother.smooth(_regime(60.0, "normal"))
    assert out3["score"] == 65.0
    assert any("EMA" in str(reason) for reason in out2["reasons"])


def test_state_untouched_when_hysteresis_off():
    smoother = RegimeSmoother(alpha=0.5)              # EMA 生效但迟滞关
    out = smoother.smooth(_regime(55.0, "weak"))
    assert out["state"] == "weak"                     # state 恒为 market_regime 原值
    assert out["score"] == 55.0


def test_hysteresis_keeps_strong_until_exit_band():
    smoother = RegimeSmoother(alpha=1.0, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    smoother.smooth(_regime(75.0, "strong"))          # 进入 strong
    out = smoother.smooth(_regime(67.0, "normal"))    # 67 ≥ 65 退出线：保持 strong
    assert out["state"] == "strong"
    out2 = smoother.smooth(_regime(60.0, "weak"))     # 60 < 65：退出
    assert out2["state"] == "weak"


def test_hysteresis_enters_strong_only_at_enter_threshold():
    smoother = RegimeSmoother(alpha=1.0, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    out = smoother.smooth(_regime(68.0, "normal"))    # 68 < 70：不进 strong
    assert out["state"] == "normal"
    out2 = smoother.smooth(_regime(72.0, "strong"))
    assert out2["state"] == "strong"


def test_reset_clears_ema_and_state_memory():
    smoother = RegimeSmoother(alpha=0.5)
    smoother.smooth(_regime(80.0, "strong"))
    smoother.reset()
    out = smoother.smooth(_regime(60.0, "normal"))
    assert out["score"] == 60.0                       # 首帧语义恢复
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_regime_smoother.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_regime_smoother.py -v`

- [ ] **Step 3: 实现**

```python
"""Regime score 平滑包装（WP2b）。

market_regime 纯函数本体不动：本包装只在其输出 dict 上做 EMA 与 strong 边界迟滞。
直通条件（alpha>=1 且迟滞关）原样返回同一 dict——引擎侧可据引用相等短路，保证零行为变化。
state 迟滞仅作用于 strong↔非 strong 边界（门禁 regimeGateStrongBan 仅消费 strong）。
"""
from __future__ import annotations

from typing import Any


class RegimeSmoother:
    def __init__(
        self,
        alpha: float = 1.0,
        hysteresis: bool = False,
        strong_enter: float = 70.0,
        strong_exit_band: float = 5.0,
    ) -> None:
        self._alpha = float(alpha)
        self._hysteresis = bool(hysteresis)
        self._strong_enter = float(strong_enter)
        self._strong_exit = float(strong_enter) - float(strong_exit_band)
        self._ema: float | None = None
        self._prev_state: str | None = None

    def reset(self) -> None:
        self._ema = None
        self._prev_state = None

    def smooth(self, regime: dict[str, Any]) -> dict[str, Any]:
        if self._alpha >= 1.0 and not self._hysteresis:
            return regime  # 直通：同一引用，零行为变化
        raw_score = float(regime.get("score") or 0.0)
        self._ema = raw_score if self._ema is None else self._alpha * raw_score + (1.0 - self._alpha) * self._ema
        smoothed = dict(regime)
        smoothed["score"] = self._ema
        raw_state = str(regime.get("state") or "")
        state = raw_state
        if self._hysteresis:
            prev = self._prev_state
            if self._ema >= self._strong_enter:
                state = "strong"
            elif prev == "strong" and self._ema >= self._strong_exit:
                state = "strong"  # 迟滞带内保持
            # 其余情况沿用 market_regime 原值
        self._prev_state = state
        smoothed["state"] = state
        reasons = list(regime.get("reasons") or [])
        reasons.append(f"regime score EMA 平滑生效（α={self._alpha:g}）")
        smoothed["reasons"] = reasons
        return smoothed
```

replay 挂载（`runtime.py` L903 处替换，入口与确认状态同批 reset）：

```python
            # WP2b：regime 输出经平滑包装（默认参数原样返回同一 dict，零行为变化）
            regime = self._smooth_regime(market_regime(frame))
```

引擎辅助方法（replay 内每次调用；实例属性惰性初始化）：

```python
    def _smooth_regime(self, regime: dict[str, Any]) -> dict[str, Any]:
        smoother = getattr(self, "_regime_smoother", None)
        if smoother is None:
            from backend.analysis.ranktrend.trend.regime_smoother import RegimeSmoother

            config = getattr(self, "config", None)
            smoother = RegimeSmoother(
                alpha=float(getattr(config, "regimeScoreEmaAlpha", 1.0)),
                hysteresis=bool(getattr(config, "regimeStateHysteresis", False)),
                strong_enter=float(<REGIME_STRONG_SCORE 常量值>),  # 执行时以 risk.py 实际常量代入
                strong_exit_band=float(getattr(config, "regimeStrongHysteresisBand", 5.0)),
            )
            self._regime_smoother = smoother
        return smoother.smooth(regime)
```

replay 入口（Task 3 的 reset 旁）加 `smoother = getattr(self, "_regime_smoother", None); smoother.reset() if smoother else None`（或直接重建实例）。`ranktrend_routes.py` `_analyze_frames` 与 `main.py:931` 的 `market_regime` 调用**保持直通不动**（非范围——该链路建信号发生在无确认上下文的轻量实例上，与 replay 行为边界一致）。

- [ ] **Step 4: 回归（含 golden）**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_regime_smoother.py tests/test_gate_confirm_wiring.py tests/test_gate_confirm_bd_tier.py --collect-only -q && .venv/Scripts/python.exe -m pytest tests/test_regime_smoother.py tests/test_gate_confirm_wiring.py tests/test_gate_confirm_bd_tier.py -v && .venv/Scripts/python.exe -m pytest tests/test_ranktrend_golden_alignment.py -v`
Expected: 全部 PASS，golden 无漂移。

- [ ] **Step 5: 提交**

```bash
git add quant-board/backend/analysis/ranktrend/trend/regime_smoother.py quant-board/backend/analysis/ranktrend/engine/runtime.py quant-board/tests/test_regime_smoother.py
git commit -m "feat(ranktrend): RegimeSmoother score EMA + strong 边界迟滞（默认直通零漂移）"
```

---

### Task 6: 端到端默认回归 + 计划文档收尾

**Files:**
- Read: `quant-board/tests/test_ranktrend_golden_alignment.py`、WP3.2 诊断脚本（对比基线用）

- [ ] **Step 1: 全相关子集回归**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_gate_confirm_state.py tests/test_ranktrend_config_denoise_params.py tests/test_gate_confirm_wiring.py tests/test_gate_confirm_bd_tier.py tests/test_regime_smoother.py tests/test_ranktrend_golden_alignment.py -v`
Expected: 全部 PASS。

- [ ] **Step 2: WP3.2 翻转率基线对比（默认参数下）**

用 `backend/operations/diagnose_gate_flip_rate.py`（WP3.2 产物）对同一数据段跑一次，确认默认参数下翻转率与 WP2 之前基线一致（默认零行为变化的端到端佐证）。结果数字记录到 commit message 或 L1 档案组 N 条目。

- [ ] **Step 3: 提交（如有档案/记录更新）**

```bash
git add quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md
git commit -m "docs(ranktrend): WP2 默认参数端到端回归记录（翻转率与基线一致）"
```

---

## 验证总清单

- Task 1-5 全部单测绿；`tests/test_ranktrend_golden_alignment.py` 全程无漂移。
- 默认参数下 WP3.2 翻转率与基线一致（端到端零行为变化佐证）。
- 单股链路（`_analyze_one_stock`）与 `replay_frame_at` 行为不变（Task 3/5 的直通保障 + 既有 live 测试回归）。

## 风险与回退

- 三个参数默认值即现行为，任何一处回归都可先 revert 对应 Task 的 commit。
- 确认层状态只在引擎实例/请求级内存中，无持久化、无 schema 变化；live frames 链路为串行执行，请求级实例传参无并发竞态。
- 关键锚点已由审查核实：`decision` 键集合无 `veto` 布尔键（action 表达）、action 全部下游消费点（runtime.py:351/404/407/454/775 + execution.py:883-886）自动跟随、`_analyze_frames` 串行（L587-590）、`REGIME_STRONG_SCORE=70.0`（risk.py:67）。执行时 Step 0 的 rg 复核仍必做（行号可能漂移）。
- veto 抑制改写 action 为上一帧已确认值（首帧 "caution"）——"caution" 在交易侧有扣分语义（execution.py L954），比直接放行保守；该边界语义已在本计划"关键设计定稿 1"声明，若 2c 扫描认为不合适可调 default 值（仅改 Task 3 一处常量）。
