# -*- coding: utf-8 -*-
"""研究 harness 公共库（2026-09-21 收敛；审计文档
docs/ranktrend-tier-backtest/harness-audit-20260921.md）。

背景：2026-09-20 P_repool 中期扫描 harness 字段路径 bug（读 signal["observation"]，
实际结构是 signal["rankTrend"]["observation"]）产出「lifecycle 档位 100% unknown」
假阴性结论。全量审计（39 harness × 5 类风险）发现的重复模式收敛为本库六组能力，
**新 harness 必须使用**（skill「harness 工程范式」清单第 1 条）；既有 harness 不强制
一次性迁移，触碰即迁移（重跑前补守卫）：

1. 窗口纪律 → load_frames（权威实现唯一化，assert_not_frozen 无条件内联）；
2. 字段路径 → sample_status_of / sample_quality_of / dimension_tier_of（维度档位唯一
   入口 tier_signal_of + DIMENSION_PATHS，禁止手写嵌套 get 链）；
3. 指标装配 → status_buckets / sa_excess / tier_summary（统一消费
   tier_forward_returns 的 tiers/unknownRate/monotonicity 键）；
4. override 断言 → assert_overrides_applied（from_patch 对未知字段静默忽略的防线）；
5. 报告落盘 → new_report / load_resume / save_report（schemaVersion 校验、跨进程
   windowsConsumed 并集、剥 __frames__、自动写 generatedAt/nature）；
6. 已知答案校验 → assert_known_answer（合成 mini replay + 结构/数据断言），新
   harness 跑全窗前强制先跑——2026-09-20 事故的结构性防线。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.research.tier_monotonicity import (
    DIMENSION_PATHS,
    TIER_VALUES,
    tier_forward_returns,
    tier_signal_of,
)
from backend.optimization.data_windows import assert_not_frozen

SCHEMA_VERSION = "harness-common-v1"

STATUS_VALUES = ("ok", "degraded", "insufficient")
_TIER_SUMMARY_TIERS = ("S", "A", "B", "C", "D", "E", "unknown")


# ── 1. 帧加载（窗口纪律内联）─────────────────────────────────────────────────
def load_frames(
    start: str,
    end: str,
    *,
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    purpose: str = "scan",
) -> list[dict[str, Any]]:
    """权威帧加载（原 optimize_resonance_parameters.load_frames 唯一化）。

    assert_not_frozen 无条件内联（审计 e 类 FAIL 修复：11 个旧 harness 默认窗覆盖
    8 月冻结窗且无守卫）。purpose 语义见 data_windows.assert_not_frozen：scan 等
    决策用途在帧含 FINAL（08-01~08-14）时 raise；仅最终报告呈现传 purpose="report"。
    """
    from backend.data.repositories.mongo_repository import MongoRepository
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        dataset_id,
        snapshot_type=snapshot_type,
        start_date=start,
        end_date=end,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    assert_not_frozen(frames, purpose)
    return frames


# ── 2. 信号结构访问器（字段路径单一源）───────────────────────────────────────
def dimension_tier_of(signal: dict[str, Any], dimension: str) -> str:
    """维度档位唯一读取器（tier_signal_of 转发，DIMENSION_PATHS 单一源）。"""
    return tier_signal_of(signal, dimension)


def sample_quality_of(signal: dict[str, Any]) -> dict[str, Any]:
    """sampleQuality 完整 dict（rankTrend.meta.sampleQuality；缺失返回空 dict）。"""
    return ((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality") or {}


def sample_status_of(signal: dict[str, Any]) -> str:
    """sampleQuality.status；字段缺失回退 "insufficient"（保守方向，与既有 harness
    语义一致，迁移时读数不变；缺失明细诊断用 sample_quality_of，不要静默吞）。"""
    return str(sample_quality_of(signal).get("status") or "insufficient")


# ── 3. 指标装配（评估工具返回键名统一消费）───────────────────────────────────
def status_buckets(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """三桶占比（ok/degraded/insufficient + total + share）。"""
    buckets = {"ok": 0, "degraded": 0, "insufficient": 0}
    for signal in signals:
        status = sample_status_of(signal)
        buckets[status] = buckets.get(status, 0) + 1
    total = sum(buckets.values())
    shares = {k: round(v / total, 4) for k, v in buckets.items()} if total else {}
    return {**buckets, "total": total, "share": shares}


def sa_excess(stats: dict[str, Any]) -> float | None:
    """S/A 合并加权 excessDirectionAccuracy（验收口径；None 不伪造 0）。"""
    tiers = stats.get("tiers") or {}
    s = tiers.get("S") or {}
    a = tiers.get("A") or {}
    s_count = int(s.get("count") or 0)
    a_count = int(a.get("count") or 0)
    total = s_count + a_count
    if total <= 0:
        return None
    s_ex = s.get("excessDirectionAccuracy")
    a_ex = a.get("excessDirectionAccuracy")
    if s_ex is None or a_ex is None:
        return None
    return (s_count * s_ex + a_count * a_ex) / total


def tier_summary(stats: dict[str, Any]) -> dict[str, Any]:
    """tier_forward_returns 输出摘要（原 optimize_resonance._tier_summary 语义）。"""
    tiers = stats.get("tiers") or {}
    mono = stats.get("monotonicity") or {}
    sa = sa_excess(stats)
    return {
        "saEx": round(sa, 4) if sa is not None else None,
        "spearman": mono.get("spearmanRankCorr"),
        "passHard": bool(mono.get("passHardConstraint")),
        "unknownRate": stats.get("unknownRate"),
        "distribution": {
            tier: (tiers.get(tier) or {}).get("count") for tier in _TIER_SUMMARY_TIERS
        },
    }


# ── 4. override 断言 ────────────────────────────────────────────────────────
def assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """逐键断言 override 真正落到 config。

    审计 d 类：from_patch 对未知字段静默忽略（config.py:408-409），拼错键名会跑成
    baseline 复刻产出假结论。dataclass kwargs 构造的 TypeError fail-fast 是等价
    保护，但 from_patch 路径必须显式断言。
    """
    for key, value in overrides.items():
        actual = getattr(config, key, None)
        if actual != value:
            raise RuntimeError(f"override 未生效：{key} 期望 {value}，实际 {actual}")


# ── 5. 报告落盘（schemaVersion / windowsConsumed / 剥帧缓存）────────────────
def new_report(
    out_path: str | Path,
    *,
    schema_version: str = SCHEMA_VERSION,
    nature: str = "",
) -> dict[str, Any]:
    """新建报告容器。__frames__ 为进程内帧缓存（save 时剥离，防 GB 级报告文件）。"""
    return {
        "__out__": str(out_path),
        "__schema__": schema_version,
        "__nature__": nature,
        "__frames__": {},
    }


def load_resume(out_path: str | Path, *, schema_version: str = SCHEMA_VERSION) -> dict[str, Any] | None:
    """加载 resume 缓存；schemaVersion 不匹配（含无版本字段的旧格式）返回 None——
    防止跨 schema 旧缓存被静默复用产出混合读数（scan_repool 审计发现的结构风险）。
    文件存在但被拒绝时 stderr 显式提示（缓存不会无声丢弃）；旧报告的 windowsConsumed
    并入 `__consumed__`（save 时与本进程消费窗取并集，跨进程消费记录不丢失）。
    """
    path = Path(out_path)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[harness] resume 文件存在但不可解析，将全新跑并覆盖：{path}", file=sys.stderr)
        return None
    if not isinstance(cached, dict) or cached.get("schemaVersion") != schema_version:
        print(
            f"[harness] resume 拒绝：文件 schemaVersion="
            f"{cached.get('schemaVersion') if isinstance(cached, dict) else type(cached).__name__!r}"
            f" != {schema_version}（旧缓存弃用，将全新跑并覆盖）：{path}",
            file=sys.stderr,
        )
        return None
    consumed = cached.pop("windowsConsumed", None) or []
    cached.pop("generatedAt", None)
    cached.pop("schemaVersion", None)
    return {
        "__out__": str(out_path),
        "__schema__": schema_version,
        "__nature__": cached.pop("nature", ""),
        "__frames__": {},
        "__consumed__": sorted(str(w) for w in consumed),
        **cached,
    }


def save_report(report: dict[str, Any]) -> Path:
    """落盘：剥离 __ 前缀内部键（帧缓存不落盘），写 generatedAt / windowsConsumed /
    schemaVersion / nature。windowsConsumed = 历史（resume 恢复的 __consumed__）与本
    进程已加载窗的并集——跨进程渐进 resume 时消费记录不丢失（M3 审计依据）。"""
    out_path = Path(report["__out__"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if not k.startswith("__")}
    payload["schemaVersion"] = report.get("__schema__", SCHEMA_VERSION)
    if report.get("__nature__"):
        payload["nature"] = report["__nature__"]
    payload["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    consumed = set(report.get("__consumed__") or ()) | set((report.get("__frames__") or {}).keys())
    payload["windowsConsumed"] = sorted(consumed)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def cached_frames(report: dict[str, Any], window: str) -> list[dict[str, Any]] | None:
    return (report.get("__frames__") or {}).get(window)


def cache_frames(report: dict[str, Any], window: str, frames: list[dict[str, Any]]) -> None:
    report.setdefault("__frames__", {})[window] = frames


# ── 6. 已知答案校验（新 harness 跑全窗前强制）────────────────────────────────
def _known_answer_frames() -> list[dict[str, Any]]:
    """合成 mini replay 场景：8 帧 × 2 股（rank 时变驱动 momentum/档位产出）。"""
    frames = []
    for i in range(8):
        frames.append(
            {
                "snapshotId": f"ka:{i}",
                "type": "half_hour",
                "timestamp": i,
                "tradingDate": "2026-06-05",
                "slotTime": "10:00",
                "marketContext": {
                    "payload": {
                        "sentiment": {"phaseName": "发酵期"},
                        "marketData": {"ztCount": 42, "dtCount": 1, "upCount": 3200, "downCount": 900},
                    }
                },
                "stocks": [
                    {
                        # rank 必须落在 1..帧内股票数：tier_forward_returns._percentile
                        # 对 rank>total 返回 0 → 样本被跳过（count 全 0）
                        "code": "000001",
                        "name": "KA甲",
                        "rank": 2 - (i % 2),
                        "avgRankNum": 20.0,
                        "change": 1.5,
                        "volumeRatio": 1.8,
                        "zlje": 1200,
                        "zljzb": 1.2,
                    },
                    {
                        "code": "000002",
                        "name": "KA乙",
                        "rank": 1 + (i % 2),
                        "avgRankNum": 20.0,
                        "change": -0.5,
                        "volumeRatio": 0.8,
                        "zlje": 300,
                        "zljzb": 0.4,
                    },
                ],
            }
        )
    return frames


def known_answer_issues() -> list[str]:
    """已知答案校验：合成 mini replay 断言信号结构与指标链路。

    结构断言（2026-09-20 事故防线）：signal 顶层/rankTrend 九键/sampleQuality.status
    三值/observation 挂载点/DIMENSION_PATHS 每维可走通；数据断言：synergy 档位非
    unknown、tier_forward_returns 有有效样本且 frameCount 一致。
    """
    issues: list[str] = []
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine

    frames = _known_answer_frames()
    # 裸构造默认 config：from_patch 未知键会被静默忽略（config.py from_patch hasattr
    # 语义），防线函数自身不得携带死参数（2026-09-21 review：minSampleCount 并非
    # RankTrendConfig 字段，patch 无效）
    engine = RankTrendPythonEngine(RankTrendConfig())
    signals = engine.replay(frames, meta={"sampleQuality": "ok"})
    if not signals:
        return ["mini replay 未产出信号"]
    signal = signals[-1]
    for key in ("snapshotId", "code", "rankTrend", "stage", "regime", "candidateTier"):
        if key not in signal:
            issues.append(f"signal 顶层缺键 {key}")
    rank_trend = signal.get("rankTrend") or {}
    for key in (
        "meta", "technical", "jump", "cycle", "risk",
        "decision", "observation", "strategy", "executionStrategy",
    ):
        if key not in rank_trend:
            issues.append(f"signal.rankTrend 缺键 {key}")
    status = str(((rank_trend.get("meta") or {}).get("sampleQuality") or {}).get("status") or "")
    if status not in STATUS_VALUES:
        issues.append(f"sampleQuality.status 异常：{status!r}（期望 {'/'.join(STATUS_VALUES)}）")
    if not isinstance(rank_trend.get("observation"), dict):
        issues.append("rankTrend.observation 不是 dict（assemble_observation 未挂载？）")
    non_unknown = [dim for dim in DIMENSION_PATHS if dimension_tier_of(signal, dim) != "unknown"]
    if "synergy" not in non_unknown:
        issues.append("synergy 档位为 unknown（合并档应恒产出）")
    if not non_unknown:
        issues.append("全部维度档位 unknown（DIMENSION_PATHS 漂移或 replay 断链）")

    stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")
    tiers = stats.get("tiers") or {}
    if set(tiers) != set(TIER_VALUES):
        issues.append(f"tier_forward_returns.tiers 键异常：{sorted(tiers)}")
    if stats.get("frameCount") != len(frames):
        issues.append(f"tier_forward_returns.frameCount={stats.get('frameCount')} != {len(frames)}")
    if stats.get("indexedFrameCount") != len(frames):
        issues.append("indexedFrameCount != frameCount（合成帧 snapshotId 重复？）")
    if not any((tiers.get(t) or {}).get("count") for t in ("S", "A", "B", "C")):
        issues.append("tier_forward_returns 无任何有效样本（S/A/B/C count 全 0）")
    return issues


def assert_known_answer() -> None:
    """校验失败立即 raise（先修 harness 再跑全窗，不产出假结论）。"""
    issues = known_answer_issues()
    if issues:
        raise RuntimeError("已知答案校验失败（先修 harness 再跑全窗）：" + "; ".join(issues))
