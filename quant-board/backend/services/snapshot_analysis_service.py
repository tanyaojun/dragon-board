# -*- coding: utf-8 -*-
"""G4（2026-08-23 前后端分离）：analyze 结果持久化 service。

用户选择 A：采集后对快照帧全量跑 analyze，把每只股票 observation/displayStatus/meta/resonance
持久化到 snapshot_analysis collection（幂等 dataset+snapshot+code），前端读库获稳定回放值
（不随"每次实时算"漂移）。此处用**快照自身帧**作为 current_frame（无前端实时行情），
入库口径 = 采集时快照。

注意：这是**稳定口径入库**，与前端 current_frame 实时 analyze 是两套（用户已确认接受
牺牲实时 current_frame）。ingest 后触发 + 读口 API + 前端读库为后续子工程。

补跑（2026-09-10）：日常采集由 snapshot_collector 直写 MongoDB、**绕过 ingest 路由**，
本服务的持久化因此长期为空（实测 snapshot_analysis 0 文档），hotlist 展示状态 join 恒为 0。
补跑入口见 `backend/services/snapshot_analysis_backfill.py` 与 CLI `snapshot-analysis-backfill`；
"算"与"写"由本模块的 `compute_snapshot_analysis` / `persist_snapshot_analysis` 两个公开函数承载，
`analyze_snapshot_and_persist` 只是二者的组合（单一实现，禁止另写一套 analyze 组装）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.engine import RankTrendPythonEngine
from backend.api.ranktrend_routes import _analyze_frames, _load_frames_for_analysis


def _insufficient_entries(
    snapshot_frame: dict[str, Any],
    seen_codes: set[str],
) -> list[dict[str, Any]]:
    """对"有行情行但 analyze 未产出"的股票补一条 golden「无阶段」entry。

    为什么必须补（2026-09-10 用户裁决）：这些股票在历史窗口内没有有效的
    ``avgRankNum``（八平台均榜排名）→ 建不起 attention 序列 → 被 ``_analyze_frames``
    的 gate 跳过（``if not bars or pos is None: continue``）→ 不落
    ``snapshot_analysis`` → hotlist join 取不到 ``displayStatus`` → 落旧口径 ``fallback``。
    全库约 1/5 的 ``snapshot_stock_rows`` 无有效 ``avgRankNum``（625,218 行中仅
    490,974 行 > 0），所以兜底靠"补算"永远消不掉。

    **不伪造任何结论**：只把"算不出来"显式落库为 ``cycle=None`` +
    ``meta.sampleQuality.status=insufficient``；由 ``compute_display_status`` 的纯投影得出
    ``{stage: None, label: "无阶段", tooltip: ...}`` —— 阶段缺失在 ``stageCounts.unknown``
    里如实体现，而不是伪装成某个 lifecycle 阶段（spec §4）。
    效果：``statusSourceCounts.fallback`` 归零，而"算不出来"依然 fail-visible。
    """
    from backend.analysis.ranktrend.display_status import compute_display_status

    entries: list[dict[str, Any]] = []
    for row in snapshot_frame.get("stocks") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "")
        if not code or code in seen_codes:
            continue
        analysis: dict[str, Any] = {
            # 无阶段：诚实落在 stageCounts.unknown（spec §4），不伪装成任何 lifecycle 阶段
            "cycle": None,
            "meta": {
                "code": code,
                "sampleQuality": {"status": "insufficient", "timelineValid": False},
            },
            "observation": {"status": "insufficient"},
        }
        # displayStatus 必须随 entry 一起落库：hotlist join 只读 analysis.displayStatus
        analysis["displayStatus"] = compute_display_status(analysis, row)
        entries.append({"code": code, "analysis": analysis})
    return entries


def compute_snapshot_analysis(
    repo: Any,
    dataset_id: str,
    snapshot_type: str,
    snapshot_frame: dict[str, Any],
) -> list[dict[str, Any]]:
    """只算不写：对单帧全量 analyze，返回 ``[{"code", "analysis"}]``。

    产出 = ① golden analyze 有 observation 的股票 + ② **补全项**：有行情行但 analyze
    未产出的股票（落「样本不足」，见 ``_insufficient_entries``）。两者合起来覆盖当前帧的
    全部股票行，hotlist join 因此不再产生 ``fallback``。

    从 ``analyze_snapshot_and_persist`` 拆出，供 CLI dry-run 与补跑共用**同一实现**
    （禁止出现第二套 analyze 组装逻辑）。
    """
    frames, series_by_code = _load_frames_for_analysis(
        repo,
        dataset_id,
        snapshot_type,
        [],
        current_frame=snapshot_frame,
        codes=None,
    )
    entries: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    if frames:
        engine = RankTrendPythonEngine()
        output = _analyze_frames(engine, frames, series_by_code, [])
        if output:
            for stock in output[-1].get("stocks", []):
                analysis = stock.get("analysis") or {}
                if not analysis.get("observation"):
                    continue
                code = str(stock.get("code") or "")
                seen_codes.add(code)
                entries.append({"code": code, "analysis": analysis})
    # 无帧 / 无输出时同样走补全：整帧落「样本不足」，而不是静默返回空（fail-visible）
    entries.extend(_insufficient_entries(snapshot_frame, seen_codes))
    return entries


# analyze 产出的顶层字段全集（2026-09-10 核对）。
#
# 此前只落 5 个字段（observation/displayStatus/meta/resonance/cycle），导致
# technical（macd/movingAverage/momentumScore/crossSection/signals...）、risk、
# strategy、executionStrategy、jump、decision、themeMomentum 全部丢弃 —— 读口
# `GET /api/snapshots/analysis` 只能拿到残缺分析。四信号（共振 resonance /
# 趋势 observation.rankTrend / 横截面 observation.crossSection / 量价
# observation.volumePrice）虽已包含在 observation+resonance 内，但**裁剪落库
# 本身就是数据丢失**（AGENTS.md §4.0 fail-visible）：应落原始产物，而不是让
# 下游"再算一遍"或看到缺失后猜原因。
ANALYSIS_PERSIST_FIELDS: tuple[str, ...] = (
    "observation",  # 趋势 rankTrend / 横截面 crossSection / 量价 volumePrice / lifecycle 等
    "resonance",  # 共振
    "technical",  # 技术面多维（macd/movingAverage/momentumScore/crossSection/signals...）
    "risk",  # 风险四维（divergence/overheat/pressure/synergy）
    "strategy",  # 策略候选（action/candidateTier/momentum/regime/reasons）
    "executionStrategy",  # 执行策略（含 hotlist 维度）
    "jump",  # 跳跃/崩塌事件
    "decision",  # 决策基础与最终（base/final）
    "cycle",  # 生命周期阶段（阶段缺失判定的输入）
    "meta",  # 排名/分位/样本质量
    "displayStatus",  # 生命周期 5 态展示投影（stage/label/tooltip；无 classKey）
    "themeMomentum",  # 题材动量投影
)


def persist_snapshot_analysis(
    repo: Any,
    dataset_id: str,
    snapshot_id: str,
    entries: list[dict[str, Any]],
) -> int:
    """把 ``compute_snapshot_analysis`` 的产出幂等写入 ``snapshot_analysis``。

    落库字段 = ``ANALYSIS_PERSIST_FIELDS``（analyze 顶层字段全集），不再裁剪。

    ``cycle.stage`` 一旦缺失会被 join 层判成"阶段真缺失"（2026-09-10 实测
    stageMissing=5 假阳性），这是裁剪落库的直接代价；其余字段同理。

    返回持久化的股票数（fail-visible：空 entries 返回 0，不伪造）。
    """
    count = 0
    for entry in entries:
        analysis = entry.get("analysis") or {}
        payload: dict[str, Any] = {}
        for field in ANALYSIS_PERSIST_FIELDS:
            value = analysis.get(field)
            payload[field] = {} if field == "observation" and not value else value
        repo.upsert_snapshot_analysis(
            dataset_id,
            snapshot_id,
            str(entry.get("code") or ""),
            payload,
        )
        count += 1
    return count


def analyze_snapshot_and_persist(
    repo: Any,
    dataset_id: str,
    snapshot_id: str,
    snapshot_type: str,
    snapshot_frame: dict[str, Any],
) -> int:
    """对单个快照帧全量 analyze 并持久化 `ANALYSIS_PERSIST_FIELDS` 全部 12 组字段。

    返回持久化的股票数（fail-visible：无帧/无 observation 返回 0，不伪造）。
    """
    entries = compute_snapshot_analysis(repo, dataset_id, snapshot_type, snapshot_frame)
    return persist_snapshot_analysis(repo, dataset_id, snapshot_id, entries)
