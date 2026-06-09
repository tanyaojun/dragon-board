# RankTrend Hotlist Recall Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改 live 自动入池逻辑的前提下，扩展现有 shadow audit 工具链，支持“热榜买点型正样本 + jump confidence 区间搜索 + fusion 热榜适配归因”的 research-only 研究输出。

**Architecture:** 先在纯分析层补齐锚点样本 schema、热榜买点标签、confidence 区间扫描与 fusion 结构归因 helper，再在 `RankTrendLiveGateAuditService` 中把“最近一周逐帧 replay”接到这些 helper 上，形成统一研究报告。最后通过 CLI 暴露研究参数与锚点文件输入，并把合同同步到文档与测试。

**Tech Stack:** Python 3, QuantBoard backend analysis/services, pytest, argparse, Markdown docs

---

## 关键实现约束

- `jump confidence` 区间扫描只允许基于 `baselineSignal` 统计，禁止把 variant replay signal 回填成 baseline
- `jump confidence` 研究与 `jumpDeltaPct` / jump 定义变化研究必须拆成两个独立输出
- `focusFindings` 继续保留给排查视图，但不得作为“扩展热榜覆盖样本”的唯一来源
- `dragonboard_live` 扩展样本口径是“最近一周热榜覆盖样本”，不是全市场全量样本
- `002156` 在未确认具体 bar 位前，只能以 `status=borderline` 进入锚点文件，不进入首批主统计
- CLI 测试不得假设 `backend.cli.main()` 支持传 argv；应直接测试 `build_parser()` 和命令 handler

## File Map

- Modify: `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
  - 新增人工锚点样本 schema、热榜买点标签判定、confidence 扫描、fusion 误伤归因与研究报告 helper
- Modify: `quant-board/backend/services.py`
  - 扩展 `RankTrendLiveGateAuditService.run()`，支持锚点输入、confidence 区间搜索、研究报告聚合
- Modify: `quant-board/backend/cli.py`
  - 扩展 `audit-ranktrend-live-gates` 命令参数，支持 `--anchor-file` 与 confidence 扫描配置
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`
  - 覆盖锚点 schema、标签抽象、confidence 扫描、fusion 归因、CLI 合同
- Modify: `quant-board/docs/api-cli.md`
  - 补充 research-only 新参数、样例与输出结构
- Create: `quant-board/tests/fixtures/ranktrend_hotlist_anchor_samples.json`
  - 最小锚点样本夹具，锁定输入合同

---

## Task 1: 锁定锚点样本合同与热榜买点标签分析层

**Files:**
- Create: `quant-board/tests/fixtures/ranktrend_hotlist_anchor_samples.json`
- Modify: `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 先写失败测试，锁定锚点样本输入格式**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import load_hotlist_anchor_samples


def test_load_hotlist_anchor_samples_reads_minimal_contract(tmp_path) -> None:
    path = tmp_path / "anchors.json"
    path.write_text(
        """
        [
          {
            "code": "600186",
            "tradingDate": "2026-06-09",
            "slotTime": "10:30",
            "snapshotType": "half_hour",
            "label": "lotus_1030",
            "evidence": "技术三买共振，盘中热榜买点",
            "annotator": "user",
            "status": "confirmed"
          }
        ]
        """.strip(),
        encoding="utf-8",
    )

    anchors = load_hotlist_anchor_samples(path)

    assert anchors == [
        {
            "code": "600186",
            "tradingDate": "2026-06-09",
            "slotTime": "10:30",
            "snapshotType": "half_hour",
            "label": "lotus_1030",
            "evidence": "技术三买共振，盘中热榜买点",
            "annotator": "user",
            "status": "confirmed",
        }
    ]
```

- [ ] **Step 2: 再写失败测试，锁定热榜买点标签只做研究解释，不重引入硬 veto**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import classify_hotlist_buy_pattern


def test_classify_hotlist_buy_pattern_marks_progressive_non_explosive_setup() -> None:
    tags = classify_hotlist_buy_pattern(
        {
            "change": 5.2,
            "rankTrend": {
                "jump": {"direction": "buy", "confidence": 78, "sustained": True},
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 7.3,
                        "mid": 24.9,
                        "long": 28.6,
                        "acceleration": 4.3,
                    },
                },
                "cycle": {"stage": "expansion"},
            },
        }
    )

    assert "technical_buy_alignment" in tags
    assert "progressive_rank_lift" in tags
    assert "non_explosive_but_valid" in tags
    assert "early_hotlist_ignition" not in tags
```

- [ ] **Step 3: 再写失败测试，锁定缺字段时返回空标签而不是抛异常**

```python
def test_classify_hotlist_buy_pattern_handles_missing_ranktrend_fields() -> None:
    tags = classify_hotlist_buy_pattern({"code": "000001"})
    assert tags == []
```

- [ ] **Step 4: 跑测试，确认新函数尚不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `load_hotlist_anchor_samples` / `classify_hotlist_buy_pattern` 未定义。

- [ ] **Step 5: 用最小实现补齐分析 helper**

```python
import json
from pathlib import Path


def load_hotlist_anchor_samples(path: str | Path) -> list[dict[str, str]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    output: list[dict[str, str]] = []
    for row in rows:
        output.append(
            {
                "code": str(row.get("code") or "").strip(),
                "tradingDate": str(row.get("tradingDate") or "").strip(),
                "slotTime": str(row.get("slotTime") or "").strip(),
                "snapshotType": str(row.get("snapshotType") or "half_hour").strip(),
                "label": str(row.get("label") or "").strip(),
                "evidence": str(row.get("evidence") or "").strip(),
                "annotator": str(row.get("annotator") or "").strip(),
                "status": str(row.get("status") or "confirmed").strip(),
            }
        )
    return output


def classify_hotlist_buy_pattern(signal: dict[str, Any]) -> list[str]:
    technical = _nested_get(signal, "rankTrend", "technical") or {}
    momentum = technical.get("momentumProfile") or {}
    tech_signals = technical.get("signals") or {}
    jump = _nested_get(signal, "rankTrend", "jump") or {}
    cycle_stage = str(_nested_get(signal, "rankTrend", "cycle", "stage") or "")
    tags: list[str] = []

    buy_votes = [
        _nested_get(tech_signals, "direction", "signal") == "buy",
        _nested_get(tech_signals, "acceleration", "signal") == "buy",
        _nested_get(tech_signals, "zeroCross", "signal") == "buy",
        _nested_get(technical, "macd", "cross") == "golden",
    ]
    if sum(1 for vote in buy_votes if vote) >= 3:
        tags.append("technical_buy_alignment")
    if jump.get("direction") == "buy" and _to_float(jump.get("confidence")) >= 70:
        tags.append("progressive_rank_lift")
    if (
        _to_float(momentum.get("short")) > 0
        and _to_float(momentum.get("mid")) > 0
        and _to_float(momentum.get("long")) > 0
        and _to_float(momentum.get("acceleration")) < 10
    ):
        tags.append("non-explosive_but_valid")
    if cycle_stage == "ignition":
        tags.append("early_hotlist_ignition")
    return tags
```

- [ ] **Step 6: 创建测试夹具文件，锁定首批锚点样本**

```json
[
  {
    "code": "600186",
    "tradingDate": "2026-06-09",
    "slotTime": "10:00",
    "snapshotType": "half_hour",
    "label": "lotus_1000",
    "evidence": "盘中热榜启动买点",
    "annotator": "user",
    "status": "confirmed"
  },
  {
    "code": "600186",
    "tradingDate": "2026-06-09",
    "slotTime": "10:30",
    "snapshotType": "half_hour",
    "label": "lotus_1030",
    "evidence": "技术三买共振，盘中热榜买点",
    "annotator": "user",
    "status": "confirmed"
  },
  {
    "code": "600183",
    "tradingDate": "2026-06-09",
    "slotTime": "10:00",
    "snapshotType": "half_hour",
    "label": "shengyi_1000",
    "evidence": "跳升启动买点",
    "annotator": "user",
    "status": "confirmed"
  },
  {
    "code": "600183",
    "tradingDate": "2026-06-09",
    "slotTime": "10:30",
    "snapshotType": "half_hour",
    "label": "shengyi_1030",
    "evidence": "加速确认买点",
    "annotator": "user",
    "status": "confirmed"
  },
  {
    "code": "002156",
    "tradingDate": "2026-06-09",
    "slotTime": "",
    "snapshotType": "half_hour",
    "label": "tfwd_pending",
    "evidence": "用户确认是盘中较好买点，但具体 bar 待补",
    "annotator": "user",
    "status": "borderline"
  }
]
```

- [ ] **Step 7: 重新跑测试，确认分析层新合同通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，且新增锚点/标签相关用例通过。

- [ ] **Step 8: 提交**

```powershell
git add quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py quant-board/tests/fixtures/ranktrend_hotlist_anchor_samples.json
git commit -m "feat: add hotlist anchor schema and buy-pattern tags"
```

---

## Task 2: 扩展 confidence 区间扫描与 fusion 误伤归因纯函数

**Files:**
- Modify: `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 先写失败测试，锁定 confidence 扫描输出不是单点神值，而是区间统计**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import scan_jump_confidence_thresholds


def test_scan_jump_confidence_thresholds_returns_interval_rows() -> None:
    findings = [
        {
            "code": "600186",
            "isAnchor": True,
            "isPositiveOutcome": True,
            "baselineSignal": {
                "rankTrend": {"jump": {"confidence": 79.8, "direction": "buy", "event": "jump", "sustained": True}}
            },
            "hotlistBuyTags": ["technical_buy_alignment"],
        },
        {
            "code": "300433",
            "isAnchor": False,
            "isPositiveOutcome": True,
            "baselineSignal": {
                "rankTrend": {"jump": {"confidence": 77.9, "direction": "buy", "event": "jump", "sustained": True}}
            },
            "hotlistBuyTags": ["technical_buy_alignment"],
        },
        {
            "code": "000001",
            "isAnchor": False,
            "isPositiveOutcome": False,
            "baselineSignal": {
                "rankTrend": {"jump": {"confidence": 81.0, "direction": "buy", "event": "jump", "sustained": True}}
            },
            "hotlistBuyTags": [],
        },
    ]

    rows = scan_jump_confidence_thresholds(findings, thresholds=[75, 80, 85, 90])

    assert [row["threshold"] for row in rows] == [75, 80, 85, 90]
    assert rows[0]["anchorRecallCount"] == 1
    assert rows[1]["anchorRecallCount"] == 0
    assert rows[0]["positiveRecallCount"] == 2
    assert rows[0]["noiseCount"] == 1
```

- [ ] **Step 2: 再写失败测试，锁定 fusion 误伤归因按 gate 拆解人工锚点与扩展样本**

```python
from backend.analysis.ranktrend_live_gate_shadow_audit import summarize_fusion_gate_misses


def test_summarize_fusion_gate_misses_separates_anchor_and_extended_samples() -> None:
    findings = [
        {
            "isAnchor": True,
            "hotlistBuyTags": ["technical_buy_alignment"],
            "variantResults": {
                "baseline": {
                    "fusion": {
                        "checks": [
                            {"name": "short_mid_long_positive", "passed": True},
                            {"name": "acceleration_ge_10_or_accdelta_ge_8", "passed": False},
                        ]
                    }
                }
            },
        },
        {
            "isAnchor": False,
            "hotlistBuyTags": ["technical_buy_alignment", "non_explosive_but_valid"],
            "variantResults": {
                "baseline": {
                    "fusion": {
                        "checks": [
                            {"name": "short_mid_long_positive", "passed": True},
                            {"name": "acceleration_ge_10_or_accdelta_ge_8", "passed": False},
                        ]
                    }
                }
            },
        },
    ]

    summary = summarize_fusion_gate_misses(findings)

    assert summary["anchorMissCounts"]["acceleration_ge_10_or_accdelta_ge_8"] == 1
    assert summary["extendedMissCounts"]["acceleration_ge_10_or_accdelta_ge_8"] == 1
```

- [ ] **Step 3: 跑测试，确认扫描与归因函数缺失导致失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `scan_jump_confidence_thresholds` / `summarize_fusion_gate_misses` 未定义。

- [ ] **Step 4: 最小实现 confidence 区间扫描与 fusion 归因 helper**

```python
def scan_jump_confidence_thresholds(
    findings: list[dict[str, Any]],
    thresholds: list[float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        anchor_recall = 0
        positive_recall = 0
        recalled_total = 0
        noise_count = 0
        for item in findings:
            jump = _nested_get(item, "baselineSignal", "rankTrend", "jump") or {}
            confidence = _to_float(jump.get("confidence"))
            recalled = (
                jump.get("event") == "jump"
                and jump.get("direction") == "buy"
                and jump.get("sustained") is True
                and confidence >= threshold
            )
            if not recalled:
                continue
            recalled_total += 1
            if item.get("isAnchor"):
                anchor_recall += 1
            if item.get("isPositiveOutcome"):
                positive_recall += 1
            if (
                not item.get("isAnchor")
                and not item.get("isPositiveOutcome")
                and "technical_buy_alignment" not in (item.get("hotlistBuyTags") or [])
            ):
                noise_count += 1
        rows.append(
            {
                "threshold": threshold,
                "anchorRecallCount": anchor_recall,
                "positiveRecallCount": positive_recall,
                "recalledCount": recalled_total,
                "noiseCount": noise_count,
            }
        )
    return rows


def summarize_fusion_gate_misses(findings: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    anchor_counts: dict[str, int] = {}
    extended_counts: dict[str, int] = {}
    for item in findings:
        failed = [
            check["name"]
            for check in (((item.get("variantResults") or {}).get("baseline") or {}).get("fusion") or {}).get("checks", [])
            if not check.get("passed")
        ]
        for name in failed:
            target = anchor_counts if item.get("isAnchor") else extended_counts
            target[name] = int(target.get(name) or 0) + 1
    return {
        "anchorMissCounts": anchor_counts,
        "extendedMissCounts": extended_counts,
    }
```

- [ ] **Step 5: 重新跑测试，确认纯函数层通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，新增 confidence 扫描与 fusion 归因用例通过。

- [ ] **Step 6: 提交**

```powershell
git add quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py
git commit -m "feat: add confidence scan and fusion miss summaries"
```

---

## Task 3: 扩展服务层，生成锚点样本、区间扫描、jump 定义研究与 fusion 归因报告

**Files:**
- Modify: `quant-board/backend/services.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`

- [ ] **Step 1: 先写失败测试，锁定服务层输出必须新增 3 个研究区块**

```python
def test_service_run_emits_anchor_findings_confidence_scan_and_fusion_summary(monkeypatch) -> None:
    service = RankTrendLiveGateAuditService(None)

    monkeypatch.setattr(
        service.repo,
        "load_dataset_bundle_slice",
        lambda *args, **kwargs: (
            [{"snapshotId": "half_hour:2026-06-09:10:30"}],
            [{"snapshotId": "half_hour:2026-06-09:10:30", "timestamp": 1, "tradingDate": "2026-06-09", "slotTime": "10:30"}],
            [{"snapshotId": "half_hour:2026-06-09:10:30", "code": "600186", "name": "莲花控股", "rank": 73, "change": 6.0}],
            [],
        ),
    )
    monkeypatch.setattr(
        service,
        "_replay_frame_signals_by_snapshot",
        lambda merged_frames, jump_delta_pct=15.0: {
            "half_hour:2026-06-09:10:30": {
                "600186": make_signal(snapshotId="half_hour:2026-06-09:10:30", tradingDate="2026-06-09", slotTime="10:30")
            }
        },
    )
    monkeypatch.setattr(service, "_replay_variant_signal_maps_by_snapshot", lambda merged_frames: {})

    result = service.run(
        {
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "start_date": "2026-06-09",
            "end_date": "2026-06-09",
            "anchor_samples": [
                {"code": "600186", "tradingDate": "2026-06-09", "slotTime": "10:30", "snapshotType": "half_hour", "label": "lotus_1030", "evidence": "盘中热榜买点", "annotator": "user", "status": "confirmed"}
            ],
            "confidence_thresholds": [75, 80, 85, 90],
            "research_all_frames": True,
        }
    )

    assert "anchorFindings" in result
    assert "extendedHotlistFindings" in result
    assert "confidenceThresholdScan" in result
    assert "jumpDefinitionReplaySummary" in result
    assert "fusionGateMissSummary" in result
    assert result["anchorFindings"][0]["isAnchor"] is True
    assert result["confidenceThresholdScan"][0]["threshold"] == 75
```

- [ ] **Step 2: 再写失败测试，锁定人工锚点需要写回 finding 级别字段**

```python
def test_focus_findings_mark_anchor_and_hotlist_tags(monkeypatch) -> None:
    service = RankTrendLiveGateAuditService(None)
    # 数据准备同上，略
    result = service.run(
        {
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "start_date": "2026-06-09",
            "end_date": "2026-06-09",
            "anchor_samples": [
                {"code": "600186", "tradingDate": "2026-06-09", "slotTime": "10:30", "snapshotType": "half_hour", "label": "lotus_1030", "evidence": "盘中热榜买点", "annotator": "user", "status": "confirmed"}
            ],
            "research_all_frames": True,
        }
    )

    finding = result["focusFindings"][0]
    assert finding["isAnchor"] is True
    assert finding["anchorLabel"] == "lotus_1030"
    assert "hotlistBuyTags" in finding
```

- [ ] **Step 3: 跑测试，确认服务层研究输出尚不存在而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `anchorFindings` / `extendedHotlistFindings` / `jumpDefinitionReplaySummary` 等区块缺失。

- [ ] **Step 4: 最小扩展 `RankTrendLiveGateAuditService.run()` 输出**

```python
anchor_samples = payload.get("anchor_samples") or payload.get("anchorSamples") or []
confidence_thresholds = payload.get("confidence_thresholds") or payload.get("confidenceThresholds") or [70, 75, 80, 85, 90, 95]
research_all_frames = bool(payload.get("research_all_frames") or payload.get("researchAllFrames") or False)

anchor_index = {
    (
        str(item.get("code") or ""),
        str(item.get("tradingDate") or ""),
        str(item.get("slotTime") or ""),
        str(item.get("snapshotType") or snapshot_type or "half_hour"),
    ): item
    for item in anchor_samples
    if str(item.get("status") or "confirmed") != "exclude"
}

for code in sorted(frame_codes):
    ...
    hotlist_tags = classify_hotlist_buy_pattern(signal)
    anchor = anchor_index.get(
        (
            code,
            str(frame.get("tradingDate") or ""),
            str(frame.get("slotTime") or ""),
            str(frame.get("type") or snapshot_type or "half_hour"),
        )
    )
    finding = {
        ...
        "baselineSignal": baseline_signal,
        "displaySignal": signal,
        "hotlistBuyTags": hotlist_tags,
        "isAnchor": anchor is not None,
        "anchorLabel": anchor.get("label") if anchor else None,
        "anchorEvidence": anchor.get("evidence") if anchor else None,
        "anchorStatus": anchor.get("status") if anchor else None,
        "isPositiveOutcome": compute_positive_outcome(...),
    }

research_findings = full_findings if research_all_frames else focus_findings
anchor_findings = [
    item for item in research_findings
    if item.get("isAnchor") and item.get("anchorStatus") == "confirmed"
]
extended_hotlist_findings = [
    item for item in research_findings
    if item.get("hotlistBuyTags")
]
confidence_scan = scan_jump_confidence_thresholds(
    anchor_findings + extended_hotlist_findings,
    [float(x) for x in confidence_thresholds],
)
jump_definition_replay_summary = summarize_jump_definition_replays(research_findings)
fusion_summary = summarize_fusion_gate_misses(extended_hotlist_findings)

return {
    "meta": {...},
    "focusFindings": focus_findings,
    "dailySummaries": daily_summaries,
    "rankingSuggestions": ranking_suggestions,
    "anchorFindings": anchor_findings,
    "extendedHotlistFindings": extended_hotlist_findings,
    "confidenceThresholdScan": confidence_scan,
    "jumpDefinitionReplaySummary": jump_definition_replay_summary,
    "fusionGateMissSummary": fusion_summary,
}
```

- [ ] **Step 5: 追加失败测试，锁定 `baselineSignal` 不能回落到 variant replay 信号**

```python
def test_service_keeps_baseline_signal_separate_from_variant_display_signal(monkeypatch) -> None:
    service = RankTrendLiveGateAuditService(None)
    # baseline 缺失，variant replay 命中
    ...
    result = service.run({"dataset_id": "dragonboard_live", "snapshot_type": "half_hour", "research_all_frames": True})
    finding = result["extendedHotlistFindings"][0]
    assert finding["baselineSignal"] is None
    assert finding["displaySignal"] is not None
```

- [ ] **Step 6: 跑测试，确认服务层新输出通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，服务层研究输出用例通过。

- [ ] **Step 7: 提交**

```powershell
git add quant-board/backend/services.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py
git commit -m "feat: emit hotlist recall research report sections"
```

---

## Task 4: 扩展 CLI 合同与文档，接通锚点输入和 confidence 扫描配置

**Files:**
- Modify: `quant-board/backend/cli.py`
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`
- Modify: `quant-board/docs/api-cli.md`

- [ ] **Step 1: 先写失败测试，锁定 CLI 支持锚点文件和 confidence 扫描参数**

```python
def test_cli_audit_ranktrend_live_gates_accepts_anchor_file_and_confidence_thresholds(tmp_path, monkeypatch) -> None:
    from backend import cli as cli_module

    anchor_file = tmp_path / "anchors.json"
    anchor_file.write_text(
        '[{"code":"600186","tradingDate":"2026-06-09","slotTime":"10:30","snapshotType":"half_hour","label":"lotus_1030","evidence":"盘中热榜买点","annotator":"user","status":"confirmed"}]',
        encoding="utf-8",
    )

    class StubService:
        def run(self, payload):
            assert payload["anchor_samples"][0]["code"] == "600186"
            assert payload["confidence_thresholds"] == [75.0, 80.0, 85.0, 90.0]
            return {"meta": {"datasetId": "dragonboard_live"}, "anchorFindings": [], "extendedHotlistFindings": [], "confidenceThresholdScan": [], "jumpDefinitionReplaySummary": {}, "fusionGateMissSummary": {}}

    monkeypatch.setattr(cli_module, "RankTrendLiveGateAuditService", lambda session=None: StubService())

    parser = cli_module.build_parser()
    args = parser.parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id", "dragonboard_live",
            "--snapshot-type", "half_hour",
            "--anchor-file", str(anchor_file),
            "--confidence-thresholds", "75,80,85,90",
            "--research-all-frames",
        ]
    )

    assert args.anchor_file == str(anchor_file)
    assert args.confidence_thresholds == "75,80,85,90"
    assert args.research_all_frames is True
    cli_module.cmd_audit_ranktrend_live_gates(args)
```

- [ ] **Step 2: 跑测试，确认 CLI 还不支持新参数而失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: FAIL，提示 `--anchor-file` / `--confidence-thresholds` / `--research-all-frames` 未注册。

- [ ] **Step 3: 最小扩展 CLI parser 与 command payload**

```python
audit_live_gates_cmd.add_argument("--anchor-file", default=None)
audit_live_gates_cmd.add_argument("--confidence-thresholds", default="70,75,80,85,90,95")
audit_live_gates_cmd.add_argument("--research-all-frames", action="store_true")
```

```python
def cmd_audit_ranktrend_live_gates(args):
    service = RankTrendLiveGateAuditService(get_session_or_none())
    anchor_samples = (
        load_hotlist_anchor_samples(args.anchor_file)
        if args.anchor_file
        else []
    )
    confidence_thresholds = [
        float(part.strip())
        for part in str(args.confidence_thresholds or "").split(",")
        if part.strip()
    ]
    result = service.run(
        {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "focus_codes": args.focus_code,
            "anchor_samples": anchor_samples,
            "confidence_thresholds": confidence_thresholds,
            "research_all_frames": args.research_all_frames,
        }
    )
```

- [ ] **Step 4: 同步文档，明确 research-only 参数与输出**

```md
新增参数：

- `--anchor-file`：人工锚点样本 JSON 文件
- `--confidence-thresholds`：jump confidence 扫描阈值列表，逗号分隔
- `--research-all-frames`：研究输出使用最近一周全部热榜覆盖样本，而不是只看 `focus-code`

新增输出：

- `anchorFindings`
- `extendedHotlistFindings`
- `confidenceThresholdScan`
- `jumpDefinitionReplaySummary`
- `fusionGateMissSummary`
```

- [ ] **Step 5: 重新跑测试，确认 CLI 与文档合同通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS，CLI 参数与输出用例通过。

- [ ] **Step 6: 提交**

```powershell
git add quant-board/backend/cli.py quant-board/tests/test_ranktrend_live_gate_shadow_audit.py quant-board/docs/api-cli.md
git commit -m "feat: wire hotlist recall research inputs into audit cli"
```

---

## Task 5: 端到端研究验证与文档收口

**Files:**
- Modify: `quant-board/tests/test_ranktrend_live_gate_shadow_audit.py`
- Modify: `quant-board/docs/superpowers/plans/2026-06-09-ranktrend-live-gate-shadow-audit-findings.md`

- [ ] **Step 1: 补一条端到端研究报告测试，锁定真实输出区块同时存在**

```python
def test_service_report_keeps_legacy_sections_and_adds_research_sections(monkeypatch) -> None:
    service = RankTrendLiveGateAuditService(None)
    # 复用前面 service stub 数据，略
    result = service.run(
        {
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "start_date": "2026-06-09",
            "end_date": "2026-06-09",
            "anchor_samples": [
                {"code": "600186", "tradingDate": "2026-06-09", "slotTime": "10:30", "snapshotType": "half_hour", "label": "lotus_1030", "evidence": "盘中热榜买点", "annotator": "user", "status": "confirmed"}
            ],
            "confidence_thresholds": [75, 80, 85, 90],
            "research_all_frames": True,
        }
    )

    assert set(result) >= {
        "meta",
        "focusFindings",
        "dailySummaries",
        "rankingSuggestions",
        "anchorFindings",
        "extendedHotlistFindings",
        "confidenceThresholdScan",
        "jumpDefinitionReplaySummary",
        "fusionGateMissSummary",
    }
```

- [ ] **Step 2: 跑目标测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`

Expected: PASS。

- [ ] **Step 3: 跑回归测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py tests/test_quant_board.py -q`

Expected: PASS，且 `test_quant_board.py` 无新增失败。

- [ ] **Step 4: 更新 findings 文档，明确旧结论只代表第一轮 gate 审计，新研究链以热榜召回设计为后续主线**

```md
补一段“后续研究方向”：

- 第一轮 findings 主要回答 hard veto 分布，不等于热榜买点归因结论
- 下一轮以 `2026-06-09-ranktrend-hotlist-recall-research-design.md` 为准
- `jump confidence=90` 的区间搜索与 `jumpDeltaPct` 的 replay 研究必须分开解释
- 当前“扩展样本”只代表 `dragonboard_live` 热榜覆盖范围，不代表全市场
```

- [ ] **Step 5: 提交**

```powershell
git add quant-board/tests/test_ranktrend_live_gate_shadow_audit.py quant-board/docs/superpowers/plans/2026-06-09-ranktrend-live-gate-shadow-audit-findings.md
git commit -m "docs: link shadow audit findings to hotlist recall research"
```

---

## Self-Review Checklist

- [ ] Spec coverage：计划已覆盖锚点 schema、热榜标签、confidence 区间扫描、fusion 误伤归因、CLI 输入与文档合同
- [ ] Placeholder scan：全文无 `TODO/TBD/类似 Task N`
- [ ] Type consistency：统一使用 `anchor_samples / confidence_thresholds / anchorFindings / extendedHotlistFindings / confidenceThresholdScan / jumpDefinitionReplaySummary / fusionGateMissSummary`

---

## Verification Commands

- `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py tests/test_quant_board.py -q`

Plan complete and saved to `quant-board/docs/superpowers/plans/2026-06-09-ranktrend-hotlist-recall-research-implementation-plan.md`.

Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints
